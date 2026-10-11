# Optional: drive exec, run plugins from a `noexec` drive (an MPC/Force's SSD)

Not specific to one drive or device: it works on any drive MPC mounts `noexec` under `/media/<name>`. Its author named it "ForceHD VST Exec" after his own drive (labelled `ForceHD`); it is called **drive exec** here. It has only been tried on a Force Gen1 with MPC OS 3.9.1; nothing is known about other devices or firmware.

> **UNTESTED on a device by this project.** The original (0.1.3) was run by its author on one Force; this adapted version and its uninstall have only been tested offline (real mounts on a tmpfs, see below). **Testers wanted** (issue #150): a Force with a `noexec` SSD, comfortable with SSH. Report what `status`, `install`, a reboot, loading a plugin from the drive and `uninstall` printed.

**Not part of any plugin release.** `drive-exec-patch.sh` is a standalone script you run on the device yourself, if you want it. The installer app lists it in its read-only "Advanced: device patches" step.

## The problem
The Force's SSD (and other drives MPC mounts under `/media/<name>`) is mounted `noexec`. MPC cannot load a plugin's `.so` from such a drive: the plugin is listed under VST but only shows "Load Plugin" (NOTES 2026-10-03). The tests and the contributor's logs show the same thing at the system level: `dlopen` fails with "failed to map segment from shared object".

## What the patch does
One folder on the drive (default `Synths`, where our plugins install their `.so`, skin and data together) gets a private bind mount that is remounted with `exec`. The drive itself stays `noexec`, so nothing else on it can run. A systemd timer (5 s after boot, then every 5 s) applies it once the drive is mounted; MPC does not wait for it and is not restarted. `fstab`, MPC's program and `MPC.settings` are not touched. It adds a unit to the device's system image (`/usr/lib/systemd/system`, the root filesystem is remounted writable for a moment and restored), the timer and service in `/etc/systemd/system`, and `/etc/drive-exec/`. A patch-only backup (mount table, unit files, no projects) goes to `/data/mpc-vst-plugins/backups`.

## Use
Copy it to the device and run it as root:
```
scp tools/mpc_patch/drive_exec/drive-exec-patch.sh root@<device-ip>:/tmp/
ssh root@<device-ip>
sh /tmp/drive-exec-patch.sh status                      # changes nothing; lists the noexec drives
sh /tmp/drive-exec-patch.sh install --root "/media/<your drive>"      # asks you to type PATCH
sh /tmp/drive-exec-patch.sh uninstall                   # asks you to type REMOVE
```
`status` also lists every mount under `/media` (filesystem, device, `exec`/`noexec`). A drive is named by its label (`SSD - Force`) or, when it has none, by a number (`662522`); a folder in `/media` that has no line there is only an empty mount point left behind, not a drive. Patch the one marked `noexec`. `--root` can be left out when exactly one drive under `/media` is mounted `noexec`. `--exec-dir vst` makes the contributor's original folder executable instead of `Synths`. A drive name may have spaces. After installing, install plugins to that drive with the installer app (Install to: the drive) or by hand, and add them to MPC's plugin list (the app's "Register plugin folders").

Before removing it, save your project. `uninstall` refuses while MPC has a plugin from the folder loaded (stop MPC first); the plugins stay on the drive but will not load until the patch is back. Run `status` after a reboot to see `patched`.

## Credit and what changed
The mount logic, its checks and the rollback are **"ForceHD VST Exec 0.1.3" by timomacquis** (issue #150), tested by him on a Force Gen1 with MPC OS 3.9.1: persistent after a full reboot, the parent mount keeps `noexec`, Dexed and Plaits load from the SSD, no wait added to MPC's start. He contributed it to this project. Changes here (version 0.2.0):
- the drive and the folder are chosen (`/media/<name>`, spaces allowed, plain names only), instead of the fixed `/media/ForceHD/vst`; the config is shell sourced by a root service, so both names are validated strictly (letters, digits, `. _ + ( ) -` and spaces, starting with a letter or digit; internal storage and the system folder are refused);
- mount points are compared the way `/proc/self/mountinfo` writes them (a space is `\040`; his awk compare did not match such a name);
- the empty `acvs` drop-in is gone (his own review notes call it dead weight); the three systemd units are his (only the names changed from `force-vst-exec` to `drive-exec`, so it never collides with his original: if his original is installed, `status` says so and `install` refuses);
- `status` ends with a `STATE` line, `install`/`uninstall` ask for a typed word (`PATCH` / `REMOVE`, or `--confirmed`), and everything is one file with his scripts embedded as plain text;
- the service names `acvs` or `inmusic-mpc` are both handled, like the other scripts here.
Not changed: ordering with MPC (none), the timer, the root-bootstrap that adds the unit to the system image, the ownership and parent checks, no forced or lazy unmount.

## Known limits
- **Boot timing:** MPC does not wait for the mount. A project that opens by itself at start can open before the drive is ready; wait for the mount and reload it. MPC drops plugin-list entries whose file is missing at startup: run the app's "Register plugin folders" if entries disappear.
- A firmware update may remove the unit in the system image. Run `status`, then `install` again.
- The timer runs every 5 s while the drive is absent (journal noise, no other effect).
- Do not unplug the drive while a plugin from it is loaded.
- **Untested on a device by this project** (the contributor's 0.1.3 was; this adapted version and its uninstall have only been run offline). See NOTES.

## Files and tests
`src/` holds the files that get installed (the helper, the uninstaller, the bootstrap scripts and the three units); `build_script.py` embeds them into `script.template.sh` and writes `drive-exec-patch.sh` (`python3 build_script.py`). `tools/test_drive_exec.py` tests it with real mounts: as root, in a private mount namespace, a tmpfs mounted `noexec` at `/media/SSD - Force` stands for the SSD and a small shared library is really `dlopen`ed before the patch, with it and after removing it (outside the folder it stays blocked, the parent mount's options never change); also install and removal, repeated apply, an absent drive, a plugin held by a process, a failed install rolling back, the typed words, hostile drive and folder names, and that the embedded files equal `src/`. Run `sudo python3 tools/test_drive_exec.py` (as a normal user only the file checks run).
