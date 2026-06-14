#!/usr/bin/env python3
"""
fx-manager.py — Firefox Extension & Profile Backup Manager

Commands:
  sync     Keep user.js UUID map current with prefs.js, refresh backup zip
  init     (todo) Package current profile into backup zip for first time
  restore  (todo) Bootstrap a new Firefox profile from backup zip

Usage:
  fx-manager.py sync [--profile PATH] [--backup PATH] [--prune]
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys
import zipfile


# ---------------------------------------------------------------------------
# User configuration — edit these if your paths differ
# ---------------------------------------------------------------------------

BACKUP_DIR = os.path.join(os.path.expanduser("~"), "Documents", "firefox-extension-manager")
BACKUP_PATH = os.path.join(BACKUP_DIR, "firefox-backup.zip")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKUP_FILENAME = "firefox-backup.zip"
UUID_COMMENT_HEADER = "// Extensions UUID Map (managed by fx-manager.py — do not edit manually)"
UUID_PREF_KEY = "extensions.webextensions.uuids"
UUID_COL_WIDTH = 38
EXT_ID_COL_WIDTH = 50
UUID_COMMENT_FORMAT = "// {{uuid:<{w1}}} | {{ext_id:<{w2}}} | {{name}}".format(
    w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
)


# ---------------------------------------------------------------------------
# Profile detection
# ---------------------------------------------------------------------------

def find_profile(profile_path=None):
    if profile_path:
        if not os.path.isdir(profile_path):
            die(f"Profile path does not exist: {profile_path}")
        return profile_path

    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    else:
        # Covers Linux (including Fedora's ~/.config/mozilla) and macOS
        candidates = [
            os.path.expanduser("~/.config/mozilla/firefox"),
            os.path.expanduser("~/.mozilla/firefox"),
            os.path.expanduser("~/Library/Application Support/Firefox/Profiles"),
        ]
        base = next((c for c in candidates if os.path.isdir(c)), None)
        if not base:
            die("Could not find Firefox profile directory. Use --profile to specify one.")

    matches = glob.glob(os.path.join(base, "*.default-release"))
    for m in matches:
        if os.path.isfile(os.path.join(m, "prefs.js")):
            return m

    die("Could not find a Firefox profile with prefs.js. Use --profile to specify one.")


def find_backup(backup_arg=None):
    return backup_arg if backup_arg else BACKUP_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def die(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_uuid_pref(text):
    """
    Extract extensions.webextensions.uuids JSON from a prefs.js or user.js file string.
    Returns dict {ext_id: uuid} or {} if not found.
    """
    match = re.search(
        r'user_pref\("extensions\.webextensions\.uuids",\s*"(.+?)"\);',
        text
    )
    if not match:
        return {}
    raw = match.group(1).replace('\\"', '"')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def parse_comment_block(text):
    """
    Extract the name mapping from the existing comment block in user.js.
    Returns dict {ext_id: name} parsed from comment lines.
    Comment line format: // <uuid> | <ext_id> | <name>
    """
    names = {}
    for line in text.splitlines():
        if line.startswith("//") and "|" in line and UUID_COMMENT_HEADER not in line:
            parts = [p.strip() for p in line.lstrip("/").split("|")]
            if len(parts) == 3:
                _, ext_id, name = parts
                if ext_id:
                    names[ext_id] = name
    return names


def lookup_name_in_extensions_json(profile, ext_id):
    """
    Early-exit parse of extensions.json to find the name for a single ext_id.
    Returns name string or ext_id as fallback.
    """
    ext_json_path = os.path.join(profile, "extensions.json")
    if not os.path.isfile(ext_json_path):
        return ext_id
    try:
        with open(ext_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for addon in data.get("addons", []):
            if addon.get("id") == ext_id:
                return addon.get("defaultLocale", {}).get("name", ext_id)
    except (json.JSONDecodeError, OSError):
        pass
    return ext_id


def build_comment_block(uuid_map, name_map):
    """
    Build the full comment block string for the UUID section in user.js.
    uuid_map: {ext_id: uuid}
    name_map: {ext_id: name}
    """
    lines = [UUID_COMMENT_HEADER]
    lines.append("// {:<{w1}} | {:<{w2}} | {}".format(
        "UUID", "Extension ID", "Name", w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
    ))
    lines.append("// " + "-" * (UUID_COL_WIDTH + EXT_ID_COL_WIDTH + 10))
    for ext_id, uuid in uuid_map.items():
        name = name_map.get(ext_id, ext_id)
        lines.append(UUID_COMMENT_FORMAT.format(uuid=uuid, ext_id=ext_id, name=name))
    return "\n".join(lines)


def build_pref_line(uuid_map):
    """
    Serialize uuid_map back into the user_pref line.
    """
    inner = json.dumps(uuid_map, separators=(",", ":"))
    escaped = inner.replace('"', '\\"')
    return f'user_pref("extensions.webextensions.uuids", "{escaped}");'


def replace_uuid_section(userjs_text, new_comment_block, new_pref_line):
    """
    Replace the UUID comment block + pref line in user.js text.
    If not found, append to end.
    """
    pattern = re.compile(
        r'// Extensions UUID Map \(managed by fx-manager\.py[^\n]*\n'  # header
        r'(?://[^\n]*\n)*'                                              # any comment lines
        r'user_pref\("extensions\.webextensions\.uuids"[^\n]*\);',
        re.DOTALL
    )
    replacement = new_comment_block + "\n" + new_pref_line
    if pattern.search(userjs_text):
        return pattern.sub(replacement, userjs_text)
    else:
        sep = "\n\n" if userjs_text and not userjs_text.endswith("\n\n") else "\n"
        return userjs_text.rstrip("\n") + sep + replacement + "\n"


def get_storage_dir(profile):
    return os.path.join(profile, "storage", "default")


def uuid_folder_prefix(uuid):
    return f"moz-extension+++{uuid}"


def get_uuid_folders(storage_dir, uuid):
    """
    Return all storage folder paths matching moz-extension+++{uuid}*
    to catch base folder and any ^userContextId= variants.
    """
    pattern = os.path.join(storage_dir, f"moz-extension+++{uuid}*")
    return glob.glob(pattern)


def rename_storage_folders(profile, old_uuid, new_uuid):
    """
    Rename all storage folders for old_uuid to new_uuid, including ^userContextId variants.
    """
    storage = get_storage_dir(profile)
    folders = get_uuid_folders(storage, old_uuid)
    if not folders:
        print(f"  Warning: no storage folders found for old UUID {old_uuid}")
        return
    for old_path in folders:
        suffix = os.path.basename(old_path)[len(f"moz-extension+++{old_uuid}"):]
        new_name = f"moz-extension+++{new_uuid}{suffix}"
        new_path = os.path.join(storage, new_name)
        os.rename(old_path, new_path)
        print(f"  Renamed: {os.path.basename(old_path)} -> {new_name}")


def prune_storage_folders(profile, uuid, ext_id):
    """
    Delete all storage folders for uuid, including ^userContextId variants.
    """
    storage = get_storage_dir(profile)
    folders = get_uuid_folders(storage, uuid)
    if not folders:
        print(f"  Note: no storage folders found for removed extension: {ext_id}")
        return
    for path in folders:
        shutil.rmtree(path)
        print(f"  Pruned: {os.path.basename(path)} ({ext_id})")


def refresh_zip(backup_path, profile, uuid_map):
    """
    Refresh the backup zip:
    - user.js from profile
    - uuid-legend.txt generated from current uuid_map + names from comment block
    - storage/default/moz-extension+++* folders that exist in profile
    """
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    userjs_path = os.path.join(profile, "user.js")
    storage_dir = get_storage_dir(profile)

    # Read current user.js to extract name map for legend
    userjs_text = open(userjs_path, "r", encoding="utf-8").read() if os.path.isfile(userjs_path) else ""
    name_map = parse_comment_block(userjs_text)

    tmp_path = backup_path + ".tmp"
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # user.js
        if os.path.isfile(userjs_path):
            zf.write(userjs_path, "user.js")

        # uuid-legend.txt
        legend_lines = [
            "# Firefox Extension Storage Legend",
            "# Generated by fx-manager.py",
            "# Format: UUID | Extension ID | Name",
            "#",
            "# {:<{w1}} | {:<{w2}} | {}".format(
                "UUID", "Extension ID", "Name", w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
            ),
            "# " + "-" * (UUID_COL_WIDTH + EXT_ID_COL_WIDTH + 10),
        ]
        for ext_id, uuid in uuid_map.items():
            name = name_map.get(ext_id, ext_id)
            legend_lines.append(
                "  {:<{w1}} | {:<{w2}} | {}".format(
                    uuid, ext_id, name, w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
                )
            )
        zf.writestr("uuid-legend.txt", "\n".join(legend_lines) + "\n")

        # storage folders
        if os.path.isdir(storage_dir):
            for entry in os.listdir(storage_dir):
                if not entry.startswith("moz-extension+++"):
                    continue
                folder_path = os.path.join(storage_dir, entry)
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        arc_path = os.path.join(
                            "storage", "default", entry,
                            os.path.relpath(abs_path, folder_path)
                        )
                        zf.write(abs_path, arc_path)

    # Atomic replace
    if os.path.exists(backup_path):
        os.remove(backup_path)
    os.rename(tmp_path, backup_path)
    print(f"  Backup zip refreshed: {backup_path}")


# ---------------------------------------------------------------------------
# sync command
# ---------------------------------------------------------------------------

def cmd_sync(profile, backup_path, prune=False):
    prefs_path = os.path.join(profile, "prefs.js")
    userjs_path = os.path.join(profile, "user.js")

    if not os.path.isfile(prefs_path):
        die(f"prefs.js not found in profile: {profile}")
    if not os.path.isfile(userjs_path):
        die(
            "user.js not found. Run 'init' to create your initial backup, "
            "or 'restore' if setting up from an existing backup on a new machine."
        )

    prefs_text = open(prefs_path, "r", encoding="utf-8").read()
    userjs_text = open(userjs_path, "r", encoding="utf-8").read()

    prefs_map = parse_uuid_pref(prefs_text)   # {ext_id: uuid} from prefs.js
    userjs_map = parse_uuid_pref(userjs_text)  # {ext_id: uuid} from user.js
    name_map = parse_comment_block(userjs_text) # {ext_id: name} from existing comments

    if not prefs_map:
        print("No extensions found in prefs.js UUID map.")

    mismatches = []
    additions = []
    seen = set()

    # Single pass over prefs.js map
    for ext_id, uuid in prefs_map.items():
        seen.add(ext_id)
        if ext_id not in userjs_map:
            additions.append(ext_id)
        elif userjs_map[ext_id] != uuid:
            # user.js is authoritative — prefs_uuid is the wrong one
            # rename storage from prefs_uuid -> userjs_uuid
            mismatches.append((ext_id, prefs_uuid, userjs_map[ext_id]))

    # Anything in user.js map not seen in prefs.js = removed
    removals = [ext_id for ext_id in userjs_map if ext_id not in seen]

    changed = bool(mismatches or additions or removals)

    if not changed:
        print("No changes detected.")
        return

    # --- Handle mismatches ---
    if mismatches:
        print(f"\nMismatches ({len(mismatches)}):")
        for ext_id, old_uuid, new_uuid in mismatches:
            name = name_map.get(ext_id, ext_id)
            print(f"  {name} ({ext_id}): renaming storage {prefs_uuid} -> {correct_uuid}")
            rename_storage_folders(profile, prefs_uuid, correct_uuid)

    # --- Handle removals ---
    if removals:
        print(f"\nRemovals ({len(removals)}):")
        for ext_id in removals:
            uuid = userjs_map.pop(ext_id)
            name = name_map.pop(ext_id, ext_id)
            print(f"  Removed: {name} ({ext_id})")
            if prune:
                prune_storage_folder(profile, uuid, ext_id)
            else:
                print(f"  Warning: orphaned storage folder remains: {uuid_folder_prefix(uuid)}")
                print(f"           Run with --prune to delete it.")

    # --- Handle additions ---
    if additions:
        print(f"\nAdditions ({len(additions)}):")
        for ext_id in additions:
            name = lookup_name_in_extensions_json(profile, ext_id)
            name_map[ext_id] = name
            uuid = prefs_map[ext_id]
            print(f"  Added: {name} ({ext_id}) -> {uuid}")

    # --- Always mirror full pref line from prefs.js ---
    # prefs_map already reflects the current Firefox state including ordering
    new_comment_block = build_comment_block(prefs_map, name_map)
    new_pref_line = build_pref_line(prefs_map)
    userjs_text = replace_uuid_section(userjs_text, new_comment_block, new_pref_line)

    with open(userjs_path, "w", encoding="utf-8") as f:
        f.write(userjs_text)
    print(f"\nuser.js updated.")

    # --- Refresh zip ---
    refresh_zip(backup_path, profile, prefs_map, name_map)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Firefox Extension & Profile Backup Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    p_sync = sub.add_parser("sync", help="Sync user.js UUID map with prefs.js and refresh backup zip")
    p_sync.add_argument("--profile", help="Path to Firefox profile directory")
    p_sync.add_argument("--backup", help="Path to backup zip file")
    p_sync.add_argument("--prune", action="store_true", help="Delete orphaned storage folders for removed extensions")

    args = parser.parse_args()

    profile = find_profile(args.profile)
    backup_path = find_backup(args.backup)
    print(f"Profile: {profile}")
    print(f"Backup:  {backup_path}")

    if args.command == "sync":
        cmd_sync(profile, backup_path, prune=args.prune)


if __name__ == "__main__":
    main()
