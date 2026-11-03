# MPC Add-Ins patch for 3.10

Restore MPC add-ins (LD_PRELOAD addins in `/data/mpc-addins`) after a reboot on MPC OS 3.10 (Gen2 / aarch64).

## The problem

On MPC OS 3.10, addins load through a systemd drop-in in `/run` (tmpfs). After every reboot that drop-in is gone, so the addins do not load until someone writes it again. This means SSH'ing in and re-running install scripts after every power cycle.

## What this patch does

Installs a Lua device script on the persistent content drive (`/nvme` on a Live III, `/sdcard` on others). MPC loads device scripts from `MPC Documents/Devices/` at every start. The script:

1. Checks `/data/mpc-addins/` for installed addins
2. Checks MPC's `LD_PRELOAD` to see if they are loaded
3. If any are missing: writes the `/run/systemd/system/acvs.service.d/90-mpc-addins.conf` drop-in
4. Schedules a single detached `systemctl restart acvs` (8-second delay)
5. A guard file (`/run/addin-restore-done`) prevents restart loops

The user sees one automatic MPC restart after a reboot. After that, all addins work.

## Usage

```sh
# Copy to the device
scp addin-restore-patch.sh root@<device-ip>:/tmp/

# SSH in
ssh root@<device-ip>

# Check the current state
sh /tmp/addin-restore-patch.sh status

# Install
sh /tmp/addin-restore-patch.sh install

# Remove
sh /tmp/addin-restore-patch.sh uninstall
```

Or install through the Plugin Manager app's patches section.

## Requirements

- Gen2 device (aarch64): Live III, MPC Key 61/37, etc.
- MPC OS 3.10
- At least one addin installed in `/data/mpc-addins/`

## What it installs

Three files in `<content root>/MPC Documents/Devices/Addin Restore/`:

| File | Purpose |
|------|---------|
| `addin_restore.ini` | Device script registration (device name, checksum) |
| `addin_restore.lua` | Lua script: discovers the .so path, calls it via `package.loadlib()` |
| `addin_restore.so`  | Native aarch64 library: reads addins, checks LD_PRELOAD, writes drop-in, restarts |

All files are on the persistent content drive. They survive reboots and firmware updates. The system image is not modified.

## Uninstall

`sh addin-restore-patch.sh uninstall` removes the three files. Addins already loaded in the current session are not affected. After the next reboot, addins will not be restored automatically.
