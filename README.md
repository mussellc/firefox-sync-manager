# Firefox Extension Manager

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

