# Optional: auto exec, run plugins from any noexec drive (no setup)

**Device-verified 2026-10-14 on a Force Gen1** with two USB sticks: install, a plugin loaded from the stick, a power cycle, release. Not yet tried: the SSD, an eject without `release`. This replaces `drive exec` (`../drive_exec`, one named drive), which stays only so it can be uninstalled. Offline tests: `tools/test_auto_exec.py`.

## What the device does (device-verified 2026-10-14, NOTES)
On a Force Gen1 the mount daemon `edisksd` mounts external drives `nosuid,nodev,noexec` (a USB stick showed it; the SSD report earlier). It has no config option for that, and MPC shares the shell's mount namespace. So the patch does not change how drives are mounted.

## What the patch does
A systemd timer (5 s after boot, then every 5 s) looks at the mounts. For every drive mounted `noexec` directly under `/media` (not the internal storage) that has a `Synths` folder, it makes a private bind mount of that folder and remounts only it with `exec`. The drive stays `noexec`. A drive that is already executable, has no `Synths` folder, or already has a foreign mount there is left alone. Drives plugged in later are picked up on the next pass; a drive that is gone is cleaned up. No folder is ever created. A backup of the mount table and unit files goes to `/data/mpc-vst-plugins/backups`. MPC is not restarted; `fstab` and `MPC.settings` are not touched.

## Use
```
scp tools/mpc_patch/auto_exec/auto-exec-patch.sh root@<device-ip>:/tmp/
ssh root@<device-ip>
sh /tmp/auto-exec-patch.sh status      # changes nothing
sh /tmp/auto-exec-patch.sh install     # asks you to type PATCH
sh /tmp/auto-exec-patch.sh verify      # does MPC itself see the executable folders; lists plugin folders
sh /tmp/auto-exec-patch.sh release     # before ejecting a drive
sh /tmp/auto-exec-patch.sh uninstall   # asks you to type REMOVE
```
Plugins go into a drive's `Synths` folder (the installer app: Create Synths folder, then Install to). The `verify` last line is `VERIFY result=ok|not-installed|not-active|mpc-blind|mpc-stopped|no-plugins`.

## Limits
- **Eject:** a drive with an executable folder on it is busy until the folder is released. Run `release` first (the timer then re-applies it on its next pass; stop the timer if you want it to stay off). An unplugged drive is cleaned up by the next pass.
- A plugin loaded from the drive keeps it busy: `release`/`uninstall` refuse then (save, stop MPC).
- A drive whose Synths folder is made after the patch is picked up within 5 s; MPC may already have dropped the plugin entries (run the app's Register plugin folders).
- A firmware update may remove the bootstrap unit in the system image: run `status`, then `install` again.
- **0.3.1 (2026-10-22; device-verified the same day on a tester's Force: two reboots with a USB stick as the exec drive):** the bootstrap unit is written through a bind mount of `/`, so it lands in the root filesystem even when an overlay is mounted over `/usr` (seen on a tester's Force). 0.3.0 wrote it into that overlay, which systemd cannot see at boot, so the patch never started after a reboot there. `status` now says `reason=bootstrap-missing` when the unit is not in the root filesystem. 
- **0.3.2 (2026-10-22, offline; BusyBox awk checked in Docker):** drives whose name has a space (`/media/Force SSD`) are found. BusyBox awk, the device's, read the old pattern `[^\/]` as "no backslash", so a mount point written `Force\040SSD` in mountinfo was skipped. **Updating (2026-10-22, offline):** 0.3.2 updates 0.3.0 and 0.3.1 in place: `status` says `state=old-patch`, and `install` (or Apply in the installer app) removes the old version with its own uninstaller, then installs. `uninstall` also removes those versions.
- It cannot be installed next to drive exec or the original ForceHD VST Exec (`status` says so); uninstall those first.
- 32-bit ARM (Gen1) only. Credit: mount logic and rollback after "ForceHD VST Exec 0.1.3" by timomacquis (#150).

## Files
`src/` has the files that get installed; `build_script.py` embeds them into `script.template.sh` and writes `auto-exec-patch.sh`. Tests: `sudo python3 tools/test_auto_exec.py` (or `DEX_IN_NS=1 unshare -rm --propagation private python3 tools/test_auto_exec.py` as a normal user).
