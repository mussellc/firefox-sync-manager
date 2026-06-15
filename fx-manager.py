#!/usr/bin/env python3
"""
fx-manager.py — Firefox Sync Manager

Commands:
  sync     Sync UUID map and extension storage to backup zip
  init     Bootstrap a new Firefox profile from a transfer package

Usage:
  fx-manager.py sync [--profile PATH] [--backup PATH] [--export]
  fx-manager.py init [--profile PATH] [--firefox PATH]
"""

import argparse
import configparser
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile


# ---------------------------------------------------------------------------
# Constants — only true hardcodes, everything else lives in fx-manager.conf
# ---------------------------------------------------------------------------

CONFIG_FILENAME = "fx-manager.conf"

DEFAULT_BACKUP_DIR        = os.path.join(os.path.expanduser("~"), "Documents", "firefox-sync-manager")
DEFAULT_BACKUP_FILENAME   = "firefox-backup.zip"
DEFAULT_TRANSFER_FILENAME = "firefox-transfer.zip"
README_FILENAME           = "README.md"

UUID_PREF_KEY       = "extensions.webextensions.uuids"
COMMENT_HEADER      = "// Extensions UUID Map (managed by fx-manager.py — do not edit manually)"
LEGEND_HEADER       = "# Firefox Extension Storage Legend"
UUID_COL_WIDTH      = 38
EXT_ID_COL_WIDTH    = 50
UUID_COMMENT_FORMAT = "// {{uuid:<{w1}}} | {{ext_id:<{w2}}} | {{name}}".format(
    w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
)

FIREFOX_COMMON_PATHS_LINUX = [
    "/usr/bin/firefox",
    "/usr/lib/firefox/firefox",
    "/snap/bin/firefox",
    "flatpak run org.mozilla.firefox",
]
FIREFOX_COMMON_PATHS_WIN = [
    os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Mozilla Firefox", "firefox.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Mozilla Firefox", "firefox.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Mozilla Firefox", "firefox.exe"),
]


# ---------------------------------------------------------------------------
# readme command
# ---------------------------------------------------------------------------
 
README_CONTENT = """\
# Firefox Sync Manager
 
## Overview
 
Firefox Sync handles extensions, bookmarks, passwords, and history — but it does not transfer browser layouts or extension runtime data. Layouts such as toolbar arrangement and vertical tabs are stored as preferences that do not sync. Extension runtime data is stored in directories named after randomly generated UUIDs that Firefox assigns per-profile, meaning the same extension gets a different UUID on every fresh profile, making storage folders impossible to copy directly between systems.
 
This tool maintains UUID uniformity across systems so that extension runtime data can be transferred reliably. It also carries your `user.js` configuration into the backup, so any Firefox layout preferences you maintain there transfer alongside the extension data. A human-readable legend is generated with every backup so you can see exactly which extension each UUID belongs to.
 
---
 
## Requirements
 
- Python 3.6 or later
- Firefox must be installed on the machine running any command
 
---
 
## Setup
 
Place `fx-manager.py` in a permanent location. On first run the tool will create two files alongside it:
 
- `fx-manager.conf` — machine-specific configuration
- No backup zip exists yet until you run `sync`
 
### fx-manager.conf
 
```ini
[paths]
backup_dir =
 
[firefox]
bin =
```
 
`backup_dir` — where the backup zip and README are stored. Defaults to `~/Documents/firefox-extension-manager/` if left blank.
 
`bin` — path to the Firefox executable. Auto-detected on first `init` run, or set manually. Only needed for `init`.
 
---
 
## Commands
 
### sync
 
```bash
python3 fx-manager.py sync
```
 
Run this after closing Firefox whenever you want to back up your current state. This includes any new extensions installed, runtime data changes, and updates to your `user.js` if you have one.
 
On first run with no existing backup, `sync` creates the backup zip from scratch. On subsequent runs it checks for UUID mismatches between the backup and the current profile, corrects any it finds, then writes a fresh backup.
 
Optional flags:
 
```bash
python3 fx-manager.py sync --export
```
 
Packages `fx-manager.py`, `firefox-backup.zip`, and `README.md` into `firefox-transfer.zip` in your backup directory after syncing. Use this when you want to transfer your setup to another system. `README.md` is included if found in the backup directory — a warning is printed if it is missing.
 
```bash
python3 fx-manager.py sync --backup /custom/path/firefox-backup.zip
```
 
Override the backup zip location for this run.
 
---
 
### init
 
```bash
python3 fx-manager.py init
```
 
Run this on a fresh machine after:
 
1. Installing Firefox
2. Signing in to your Firefox account
3. Waiting for extensions to sync
4. Closing Firefox
 
`init` expects `firefox-backup.zip` to be in the same directory as the script. Unzip `firefox-transfer.zip` and run from there.
 
What `init` does:
 
1. Injects the backup `user.js` into the profile — this carries both your layout preferences and the correct UUID assignments into `prefs.js` on the next launch
2. Wipes existing extension storage folders and extracts the backed-up ones
3. Copies the backup zip to your configured backup directory
4. Launches Firefox and waits for you to sign in and let sync complete, then close it
5. Removes the injected `user.js` and restores any pre-existing one
6. Runs `sync` automatically to correct any UUID mismatches and refresh the backup
 
After `init` completes the setup is fully initialized. Run `sync` after closing Firefox going forward.
 
```bash
python3 fx-manager.py init --firefox /path/to/firefox
```
 
Override the Firefox executable path for this run. The path is saved to `fx-manager.conf` for future use.
 
---
 
## What Is in the Backup
 
```
firefox-backup.zip
├── user.js
├── uuid-legend.txt
└── storage/
    └── default/
        ├── moz-extension+++{uuid}/
        ├── moz-extension+++{uuid}^userContextId=4294967295/
        └── ...
```
 
**`user.js`** — your Firefox preference overrides, with the UUID map appended. On a fresh profile this file enforces the correct UUID assignments and any layout preferences you maintain. It is injected once during `init` and then removed so it does not interfere with normal Firefox operation.
 
**`uuid-legend.txt`** — a human-readable table mapping each UUID to its extension ID and name. Updated on every sync.
 
**`storage/default/moz-extension+++{uuid}/`** — extension runtime data. Each folder contains the local storage for one extension. Folders suffixed with `^userContextId=` are container-specific variants of the same extension and are backed up and restored alongside the base folder.
 
---
 
## user.js and UUID Uniformity
 
Firefox stores extension UUID assignments in `prefs.js` under `extensions.webextensions.uuids`. This file cannot be edited directly — Firefox overwrites it. The only way to enforce specific UUID values is through a `user.js` file in the profile directory, which Firefox reads on launch and uses to overwrite matching entries in `prefs.js`.
 
On a fresh profile after sync, Firefox assigns new random UUIDs to every extension. The backed-up storage folders are named after the old UUIDs and would be unreachable. `init` injects a `user.js` with the original UUID assignments, Firefox reads it on launch and corrects `prefs.js`, and the storage folders become reachable again.
 
After that one launch the `user.js` is removed. The UUIDs are now correct in `prefs.js` and stay correct as long as the same extensions remain installed. Any UUID drift (from reinstalling Firefox or extensions) is detected and corrected by `sync`.
 
### Note on existing user.js files
 
If you already have a `user.js` in your profile that enforces UUID values different from the backup, those values will override the tool and break storage folder alignment. Remove or update any UUID entries in your local `user.js` before running `init`. The tool never modifies the `user.js` living in your profile — it only reads it to carry it into the backup.
 
---
 
## Sync Whitelist
 
Firefox Sync supports opting individual preferences into sync via `services.sync.prefs.sync.<pref.name>`. Setting the following in `about:config` would cause the UUID map to sync across profiles automatically:
 
```
services.sync.prefs.sync.extensions.webextensions.uuids = true
```
 
If this works reliably, UUID mismatches after a fresh profile would resolve themselves without needing `init`. This has not been verified and Mozilla does not expose it as a supported sync option. Worth testing — if it works, the UUID correction steps of this tool become redundant, though storage folder transfer would still require it.
 
"""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def config_path():
    return os.path.join(script_dir(), CONFIG_FILENAME)


def load_config():
    """
    Load fx-manager.conf from script directory.
    Create it with blank defaults if it doesn't exist.
    Returns a dict of resolved config values.
    """
    cfg = configparser.ConfigParser()
    cfg_path = config_path()

    if not os.path.isfile(cfg_path):
        cfg["paths"] = {
            "backup_dir": "",
        }
        cfg["firefox"] = {
            "bin": "",
        }
        with open(cfg_path, "w") as f:
            cfg.write(f)
        print(f"Config created: {cfg_path}")
    else:
        cfg.read(cfg_path)

    def get(section, key, default):
        try:
            val = cfg.get(section, key).strip()
            return os.path.expanduser(val) if val else default
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    backup_dir  = get("paths", "backup_dir", DEFAULT_BACKUP_DIR)
    firefox_bin = get("firefox", "bin", "")

    return {
        "backup_dir":    backup_dir,
        "backup_path":   os.path.join(backup_dir, DEFAULT_BACKUP_FILENAME),
        "transfer_path": os.path.join(backup_dir, DEFAULT_TRANSFER_FILENAME),
        "firefox_bin":   firefox_bin,
    }


def save_config_value(section, key, value):
    """Write a single value back to the config file."""
    cfg = configparser.ConfigParser()
    cfg_path = config_path()
    if os.path.isfile(cfg_path):
        cfg.read(cfg_path)
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, key, value)
    with open(cfg_path, "w") as f:
        cfg.write(f)


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


def find_firefox(config, override=None):
    """
    Resolve the Firefox executable.
    Priority: --firefox flag > config > common path detection > ask user.
    Saves to config if newly detected or provided.
    """
    if override:
        save_config_value("firefox", "bin", override)
        return override

    if config["firefox_bin"]:
        return config["firefox_bin"]

    # Try common paths
    candidates = FIREFOX_COMMON_PATHS_WIN if sys.platform == "win32" else FIREFOX_COMMON_PATHS_LINUX
    for path in candidates:
        # Handle flatpak-style commands
        exe = path.split()[0]
        if os.path.isfile(exe) or shutil.which(exe):
            print(f"  Found Firefox: {path}")
            save_config_value("firefox", "bin", path)
            return path

    # Ask user
    print("Could not find Firefox automatically. Tried:")
    for p in candidates:
        print(f"  {p}")
    path = input("Enter path to Firefox executable: ").strip()
    if not path:
        die("No Firefox path provided.")
    save_config_value("firefox", "bin", path)
    return path


def find_backup(config, override=None):
    return override if override else config["backup_path"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def die(msg):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_uuid_pref(text):
    """
    Extract extensions.webextensions.uuids JSON from a prefs.js or user.js string.
    Returns dict {ext_id: uuid} or {} if not found.
    """
    match = re.search(
        r'user_pref\("' + UUID_PREF_KEY + r'",\s*"(.+?)"\);',
        text
    )
    if not match:
        return {}
    raw = match.group(1).replace('\\"', '"')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def build_pref_line(uuid_map):
    """Serialize uuid_map back into the user_pref line."""
    inner = json.dumps(uuid_map, separators=(",", ":"))
    escaped = inner.replace('"', '\\"')
    return f'user_pref("{UUID_PREF_KEY}", "{escaped}");'


def build_comment_block(uuid_map, name_map):
    """Build the UUID comment block for user.js."""
    lines = [COMMENT_HEADER]
    lines.append("// {:<{w1}} | {:<{w2}} | {}".format(
        "UUID", "Extension ID", "Name", w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
    ))
    lines.append("// " + "-" * (UUID_COL_WIDTH + EXT_ID_COL_WIDTH + 10))
    for ext_id, uuid in uuid_map.items():
        name = name_map.get(ext_id, ext_id)
        lines.append(UUID_COMMENT_FORMAT.format(uuid=uuid, ext_id=ext_id, name=name))
    return "\n".join(lines)


def build_userjs(uuid_map, name_map, profile_userjs=None):
    """
    Build the zip's user.js:
    - If the profile has a user.js, include its content first (UUID-free)
    - Append the UUID comment block and pref line
    The profile's user.js is never expected to contain a UUID section.
    """
    uuid_section = build_comment_block(uuid_map, name_map) + "\n" + build_pref_line(uuid_map) + "\n"
    if profile_userjs:
        return profile_userjs.rstrip("\n") + "\n\n" + uuid_section
    return uuid_section


def build_legend(uuid_map, name_map):
    """Build uuid-legend.txt content."""
    lines = [
        LEGEND_HEADER,
        "# Generated by fx-manager.py",
        "#",
        "# {:<{w1}} | {:<{w2}} | {}".format(
            "UUID", "Extension ID", "Name", w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
        ),
        "# " + "-" * (UUID_COL_WIDTH + EXT_ID_COL_WIDTH + 10),
    ]
    for ext_id, uuid in uuid_map.items():
        name = name_map.get(ext_id, ext_id)
        lines.append("  {:<{w1}} | {:<{w2}} | {}".format(
            uuid, ext_id, name, w1=UUID_COL_WIDTH, w2=EXT_ID_COL_WIDTH
        ))
    return "\n".join(lines) + "\n"


def get_all_names(profile, uuid_map):
    """
    Read extensions.json once and return {ext_id: name} for all ext_ids in uuid_map.
    Falls back to ext_id if not found.
    """
    name_map = {ext_id: ext_id for ext_id in uuid_map}
    ext_json_path = os.path.join(profile, "extensions.json")
    if not os.path.isfile(ext_json_path):
        return name_map
    try:
        with open(ext_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for addon in data.get("addons", []):
            ext_id = addon.get("id")
            if ext_id in name_map:
                name_map[ext_id] = addon.get("defaultLocale", {}).get("name", ext_id)
    except (json.JSONDecodeError, OSError):
        pass
    return name_map


def get_storage_dir(profile):
    return os.path.join(profile, "storage", "default")


def get_uuid_folders(storage_dir, uuid):
    """Return all paths matching moz-extension+++{uuid}* (catches ^userContextId variants)."""
    return glob.glob(os.path.join(storage_dir, f"moz-extension+++{uuid}*"))


def rename_storage_folders(profile, old_uuid, new_uuid):
    """Rename all storage folders for old_uuid to new_uuid, including ^userContextId variants."""
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


def correct_prefs_uuid(prefs_path, ext_id, old_uuid, new_uuid):
    """Replace the UUID for a single ext_id in prefs.js."""
    with open(prefs_path, "r", encoding="utf-8") as f:
        text = f.read()
    old_pair = f'\\"{ext_id}\\":\\"{old_uuid}\\"'
    new_pair = f'\\"{ext_id}\\":\\"{new_uuid}\\"'
    new_text = text.replace(old_pair, new_pair, 1)
    with open(prefs_path, "w", encoding="utf-8") as f:
        f.write(new_text)


# ---------------------------------------------------------------------------
# Zip operations
# ---------------------------------------------------------------------------

def read_userjs_from_zip(zip_path):
    """Read user.js from zip and return its text, or None if not present."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "user.js" in zf.namelist():
                return zf.read("user.js").decode("utf-8")
    except (zipfile.BadZipFile, OSError):
        pass
    return None


def write_zip(zip_path, userjs_text, legend_text, storage_dir):
    """
    Write a fresh zip:
    - user.js
    - uuid-legend.txt
    - All moz-extension+++ folders from storage_dir (wiped and recopied fresh)
    Returns count of storage folders written.
    """
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    tmp_path = zip_path + ".tmp"
    storage_count = 0
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("user.js", userjs_text)
        zf.writestr("uuid-legend.txt", legend_text)

        if os.path.isdir(storage_dir):
            for entry in os.listdir(storage_dir):
                if not entry.startswith("moz-extension+++"):
                    continue
                storage_count += 1
                folder_path = os.path.join(storage_dir, entry)
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        abs_path = os.path.join(root, file)
                        arc_path = os.path.join(
                            "storage", "default", entry,
                            os.path.relpath(abs_path, folder_path)
                        )
                        zf.write(abs_path, arc_path)

    if os.path.exists(zip_path):
        os.remove(zip_path)
    os.rename(tmp_path, zip_path)
    return storage_count


def cmd_readme(config):
    """Write README.md to backup_dir."""
    os.makedirs(config["backup_dir"], exist_ok=True)
    readme_path = os.path.join(config["backup_dir"], README_FILENAME)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(README_CONTENT)
    print(f"  README written: {readme_path}")
    return readme_path


def export_transfer(zip_path, config):
    """Package manager + backup files into a transfer zip in backup_dir."""
    script_path = os.path.abspath(__file__)
    transfer_path = config["transfer_path"]
    tmp_path = transfer_path + ".tmp"
    os.makedirs(config["backup_dir"], exist_ok=True)
    readme_path = cmd_readme(config)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(script_path, "fx-manager.py")
        if os.path.isfile(zip_path):
            zf.write(zip_path, DEFAULT_BACKUP_FILENAME)
        else:
            die(f"Backup zip not found at {zip_path} — run sync first.")
        zf.write(readme_path, README_FILENAME)
    if os.path.exists(transfer_path):
        os.remove(transfer_path)
    os.rename(tmp_path, transfer_path)
    print(f"  Transfer package ready: {transfer_path}")


# ---------------------------------------------------------------------------
# sync command
# ---------------------------------------------------------------------------

def cmd_sync(profile, zip_path, export=False, config=None):
    prefs_path = os.path.join(profile, "prefs.js")
    storage_dir = get_storage_dir(profile)

    if not os.path.isfile(prefs_path):
        die(f"prefs.js not found in profile: {profile}")

    prefs_text = open(prefs_path, "r", encoding="utf-8").read()
    prefs_map = parse_uuid_pref(prefs_text)

    if not prefs_map:
        print("No extensions found in prefs.js UUID map. Nothing to do.")
        return

    # --- Check for existing zip and handle mismatches ---
    mismatch_count = 0
    existing_userjs = read_userjs_from_zip(zip_path) if os.path.isfile(zip_path) else None

    if existing_userjs:
        zip_map = parse_uuid_pref(existing_userjs)
        mismatches = [
            (ext_id, prefs_map[ext_id], zip_uuid)
            for ext_id, zip_uuid in zip_map.items()
            if ext_id in prefs_map and prefs_map[ext_id] != zip_uuid
        ]
        mismatch_count = len(mismatches)
        if mismatches:
            print(f"\nMismatches ({mismatch_count}) — zip's user.js is authoritative:")
            for ext_id, prefs_uuid, correct_uuid in mismatches:
                print(f"  {ext_id}: {prefs_uuid} -> {correct_uuid}")
                rename_storage_folders(profile, prefs_uuid, correct_uuid)
                correct_prefs_uuid(prefs_path, ext_id, prefs_uuid, correct_uuid)
                prefs_map[ext_id] = correct_uuid
        else:
            print("No UUID mismatches.")
    else:
        print("No existing backup found — creating from scratch.")

    # --- Build name map, user.js, and legend from current prefs_map ---
    name_map = get_all_names(profile, prefs_map)
    # Read profile's user.js if present — carried into zip, UUID section appended
    profile_userjs_path = os.path.join(profile, "user.js")
    profile_userjs = None
    if os.path.isfile(profile_userjs_path):
        profile_userjs = open(profile_userjs_path, "r", encoding="utf-8").read()
    userjs_text = build_userjs(prefs_map, name_map, profile_userjs)
    legend_text = build_legend(prefs_map, name_map)

    # --- Write zip (wipes and recopies storage fresh) ---
    storage_count = write_zip(zip_path, userjs_text, legend_text, storage_dir)

    # --- Export transfer package if requested ---
    if export and config:
        print("\nExporting transfer package...")
        export_transfer(zip_path, config)

    # --- Summary ---
    mismatch_str = f", {mismatch_count} mismatches corrected" if mismatch_count else ""
    print(f"\nSync complete — {len(prefs_map)} extensions{mismatch_str}, {storage_count} storage folders backed up.")


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------

def cmd_init(profile, firefox_bin):
    ref_zip = os.path.join(script_dir(), DEFAULT_BACKUP_FILENAME)

    # --- Check reference zip exists ---
    if not os.path.isfile(ref_zip):
        die(
            f"No backup zip found at {ref_zip}\n"
            f"  Make sure {DEFAULT_BACKUP_FILENAME} is in the same directory as this script."
        )

    # --- Check profile is ready ---
    prefs_path = os.path.join(profile, "prefs.js")
    if not os.path.isfile(prefs_path):
        die(
            "Firefox profile not ready. Please:\n"
            "  1. Launch Firefox\n"
            "  2. Sign in to your Firefox account\n"
            "  3. Wait for extensions to sync\n"
            "  4. Close Firefox\n"
            "  5. Run init again"
        )

    storage_dir = get_storage_dir(profile)
    userjs_path = os.path.join(profile, "user.js")

    # --- Inject user.js from zip ---
    userjs_text = read_userjs_from_zip(ref_zip)
    if not userjs_text:
        die(f"Could not read user.js from {ref_zip} — zip may be corrupt.")

    existing_userjs = None
    if os.path.isfile(userjs_path):
        bak_path = userjs_path + ".bak"
        shutil.copy2(userjs_path, bak_path)
        existing_userjs = open(userjs_path, "r", encoding="utf-8").read()
        print(f"  Existing user.js backed up to {bak_path}")

    with open(userjs_path, "w", encoding="utf-8") as f:
        f.write(userjs_text)
    print("  user.js injected into profile")

    # --- Wipe existing moz-extension+++ folders ---
    wiped = 0
    if os.path.isdir(storage_dir):
        for entry in os.listdir(storage_dir):
            if entry.startswith("moz-extension+++"):
                shutil.rmtree(os.path.join(storage_dir, entry))
                wiped += 1
    print(f"  Wiped {wiped} existing storage folders")

    # --- Extract storage folders from zip ---
    os.makedirs(storage_dir, exist_ok=True)
    with zipfile.ZipFile(ref_zip, "r") as zf:
        for name in zf.namelist():
            if not name.startswith("storage/default/moz-extension+++"):
                continue
            rel = os.path.relpath(name, "storage/default")
            dest = os.path.join(storage_dir, rel)
            if name.endswith("/"):
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    extracted = len(set(
        n.split("/")[2] for n in zipfile.ZipFile(ref_zip).namelist()
        if n.startswith("storage/default/moz-extension+++")
    ))
    print(f"  Extracted {extracted} storage folders")

    # --- Launch Firefox, wait for close ---
    print(f"\n  Launching Firefox ({firefox_bin})...")
    print("  Please sign in, wait for sync to complete, then close Firefox.")
    try:
        cmd = firefox_bin.split() if " " in firefox_bin else [firefox_bin]
        subprocess.run(cmd, check=False)
    except (OSError, FileNotFoundError) as e:
        die(f"Could not launch Firefox: {e}\n  Check the 'bin' value in fx-manager.conf")
    print("  Firefox closed.")

    # --- Remove injected user.js, restore original if there was one ---
    if existing_userjs:
        with open(userjs_path, "w", encoding="utf-8") as f:
            f.write(existing_userjs)
        print("  Original user.js restored")
    else:
        os.remove(userjs_path)
        print("  Injected user.js removed")

    # --- Copy reference zip to backup_path ---
    cfg = load_config()
    backup_path = cfg["backup_path"]
    if os.path.isfile(backup_path):
        print(f"  Warning: existing backup at {backup_path} will be overwritten")
    os.makedirs(cfg["backup_dir"], exist_ok=True)
    shutil.copy2(ref_zip, backup_path)
    print(f"  Reference zip copied to {backup_path}")

    # --- Run sync to correct UUID mismatches and refresh zip ---
    print("\nRunning sync...")
    cmd_sync(profile, backup_path, config=cfg)

    print("\nInitialization complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Firefox Sync Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # sync
    p_sync = sub.add_parser("sync", help="Sync browser configuration settings to backup zip")
    p_sync.add_argument("--profile", help="Path to Firefox profile directory")
    p_sync.add_argument("--backup", help="Path to backup zip file")
    p_sync.add_argument("--export", action="store_true", help="Package script and backup zip into a transfer zip after syncing")

    # init
    p_init = sub.add_parser("init", help="Bootstrap a new Firefox profile from a transfer package")
    p_init.add_argument("--profile", help="Path to Firefox profile directory")
    p_init.add_argument("--firefox", help="Path to Firefox executable")

    args = parser.parse_args()
    config = load_config()
    profile = find_profile(args.profile)
    print(f"Profile: {profile}")

    if args.command == "sync":
        zip_path = find_backup(config, args.backup if hasattr(args, "backup") else None)
        print(f"Backup:  {zip_path}")
        cmd_sync(profile, zip_path, export=args.export, config=config)

    elif args.command == "init":
        firefox_bin = find_firefox(config, args.firefox if hasattr(args, "firefox") else None)
        cmd_init(profile, firefox_bin)


if __name__ == "__main__":
    main()
