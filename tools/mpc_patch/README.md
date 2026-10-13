# Optional device patches (`tools/mpc_patch`)

**None of these is part of any plugin release.** Each is a standalone script you run on the device yourself, if you want it. They change the device, not just add files, so each has its own warnings, backups and uninstall.

| Patch | What it does | Script | Details |
|---|---|---|---|
| 16-pad drum layout (this page) | Lets MPC treat selected plugins as drum instruments with 16 lit pads. Patches `/usr/bin/MPC`; MPC OS 3.9.1.2 only. | `mpc-drum-pad-patch.sh` | below |
| Drive exec | Makes one folder on a `noexec` drive (a Force's SSD) executable so plugins load from it. No MPC restart. Untested on a device by this project. | `drive_exec/drive-exec-patch.sh` | [`drive_exec/README.md`](drive_exec/README.md) |
| Button remap (hwremap) | An `LD_PRELOAD` shim that turns a button into other buttons, a pad or a touchscreen tap. Restarts MPC. Tried on one Force; not with MidiLoop / MockbaMod. | `hwremap/hwremap-patch.sh` | [`hwremap/README.md`](hwremap/README.md) |

## Ways to install
All three scripts share one interface (`status`, `install`, `uninstall`, and `--confirmed` to skip the typed question), so both routes run the same code.
1. **The installer app, "Advanced: device patches" step** (`docs/PATCHES.md`). It lists the patches from `catalog/patches.json`, shows `status` for each (applied / not applied / unsupported firmware), and runs `install` / `uninstall` after you type the confirmation word. It downloads the script, checks its sha256 and passes `--confirmed` itself. Apply and Undo from the app are built and tested offline only (not yet on a device); the step is otherwise read-only. The same patches are on the catalog page's **Device patches** tab, with a guide page each.
2. **By hand over SSH** (always available): copy the script to the device and run it as root; see "Use" below and each patch's README.

Every patch is opt-in: nothing applies by default, as part of a plugin install, or as part of an update. Save your project first (the drum-pad and hwremap patches restart MPC).

# 16-pad drum layout (`mpc-drum-pad-patch.sh`)

## What it does
Stock MPC OS 3.9.1.2 treats only Akai's own `DrumSynth:Multi` as a drum instrument. The patch makes MPC treat the plugins in its name table (Machinedrum Module / Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip) as drum instruments with **16 pads, all lit**; pad n sends MIDI note n-1, which these plugins accept. Akai's DrumSynth Multi keeps its layout but also shows 16 lit pads. The pad colour is one red for every plugin. You can edit the pad colours with the standard Pad Colour Editor like normal manually.

## Read this first
- It **modifies Akai's factory MPC program (`/usr/bin/MPC`)**. Use it at your own risk; it is not an Akai product.
- It works **only on MPC OS 3.9.1.2** (checked by the exact checksum) and refuses anything else. A firmware update replaces the file and removes the patch; run the script again afterwards (it refuses until this project supports the new build).
- Installing **stops and restarts MPC**: save your project first.
- You need root SSH access to the device. The script only runs on the device.
- Nothing of Akai's is in the script: only the changed bytes and checksums.

## Use
By hand, copy it to the device and run it as root (or use the installer app, above):
```
scp tools/mpc_patch/mpc-drum-pad-patch.sh root@<device-ip>:/tmp/
ssh root@<device-ip>
sh /tmp/mpc-drum-pad-patch.sh status      # changes nothing
sh /tmp/mpc-drum-pad-patch.sh install     # shows the warnings, asks you to type PATCH
sh /tmp/mpc-drum-pad-patch.sh uninstall   # puts the original bytes back
```
For programs (the installer app's patches step, `docs/PATCHES.md`): `status` ends with one line `STATE state=stock|patched|old-patch|unsupported supported=0|1 backup=0|1`, and `install --confirmed` skips the typed question (the caller has shown the warnings and asked for the word itself). Everything else is unchanged; other firmware is refused either way.
`install` saves the full original MPC (112 MB) and the original bytes to `/sdcard/MPC-backup` first, checks the result by checksum, and restores the original itself if that fails. A device that has the earlier Machinedrum-only patch is upgraded (the old patch is undone first).

## If `status` says your MPC is a build this script does not know
`status` prints the checksum of `/usr/bin/MPC`. Stock 3.9.1.2 and the builds this script made are recognised; anything else (another firmware, or an earlier development version of this patch) is refused by `install`, and the page in the installer app shows the checksum as the reason.

If an earlier install saved a full backup (`/sdcard/MPC-backup/MPC-3.9.1.2.orig`), `uninstall` can put the stock program back from it even then. It first checks that the backup's checksum is the stock one (`592eebc8e1ce0797dc8c98e7002143b8`) and refuses otherwise, asks you to type `RESTORE` (or takes `--confirmed`), copies the backup over `/usr/bin/MPC`, checks the result and restarts MPC: save your project first. Afterwards `install` applies the current patch. Check the backup yourself first with `md5sum /sdcard/MPC-backup/MPC-3.9.1.2.orig`. If there is no backup, or it is not the stock program, nothing is touched; restore the factory MPC OS the way Akai documents.

## Files (maintainers)
- `matcher.S` (plugin-name table, one `.asciz` line per plugin), `cave2.S`, `helper.S`, `colours.S`, `colours_jump.S`: the ARM sources. `helper.S` and `colours*.S` come from mpc-vst-machinedrum's `release/mpc_patch` (same author), unchanged; the name table and `cave2.S` are new.
- `asm.sh` assembles them in an arm32v7 gcc container; `make_patch.py <stock MPC>` writes `mpc-3.9.1.2.patch` (our bytes only) and checks the branch chain; `build_script.py` generates `mpc-drum-pad-patch.sh` from the template and the patch.
- Tests: `test_matcher.sh` runs the name matcher under qemu-user at its real address (6 names match, 12 others fall through to Akai's original check, r4 preserved). `test_script.sh` runs the script in BusyBox 1.36 (the Force's shell) against copies of the binary: install, cancelled install, repeated install, uninstall from either backup, upgrade from the old patch, refusing a refused upgrade and other firmware. All pass.
- Patched checksum `f899e581cba179a831212083f9a55ae0`; stock `592eebc8e1ce0797dc8c98e7002143b8`.
- Adding a plugin: add its exact plugin name to the table in `matcher.S`, rebuild, re-run the tests. This folder is the one shared home: plugin repos link here instead of carrying a copy, so the patch is rebuilt in one place when the firmware changes.
