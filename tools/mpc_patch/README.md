# Optional: MPC OS drum-pad patch (16-pad drum layout)

**Not part of any plugin release.** `mpc-drum-pad-patch.sh` is a standalone script you run on the device yourself, if you want it.

## What it does
Stock MPC OS 3.9.1.2 treats only Akai's own `DrumSynth:Multi` as a drum instrument. The patch makes MPC treat the plugins in its name table (Machinedrum Module / Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip) as drum instruments with **16 pads, all lit**; pad n sends MIDI note n-1, which these plugins accept. Akai's DrumSynth Multi keeps its layout but also shows 16 lit pads. The pad colour is one red for every plugin. You can edit the pad colours with the standard Pad Colour Editor like normal manually.

## Read this first
- It **modifies Akai's factory MPC program (`/usr/bin/MPC`)**. Use it at your own risk; it is not an Akai product.
- It works **only on MPC OS 3.9.1.2** (checked by the exact checksum) and refuses anything else. A firmware update replaces the file and removes the patch; run the script again afterwards (it refuses until this project supports the new build).
- Installing **stops and restarts MPC**: save your project first.
- You need root SSH access to the device. The script only runs on the device.
- Nothing of Akai's is in the script: only the changed bytes and checksums.

## Use
Copy it to the device and run it as root:
```
scp tools/mpc_patch/mpc-drum-pad-patch.sh root@<device-ip>:/tmp/
ssh root@<device-ip>
sh /tmp/mpc-drum-pad-patch.sh status      # changes nothing
sh /tmp/mpc-drum-pad-patch.sh install     # shows the warnings, asks you to type PATCH
sh /tmp/mpc-drum-pad-patch.sh uninstall   # puts the original bytes back
```
`install` saves the full original MPC (112 MB) and the original bytes to `/sdcard/MPC-backup` first, checks the result by checksum, and restores the original itself if that fails. A device that has the earlier Machinedrum-only patch is upgraded (the old patch is undone first).

## Files (maintainers)
- `matcher.S` (plugin-name table, one `.asciz` line per plugin), `cave2.S`, `helper.S`, `colours.S`, `colours_jump.S`: the ARM sources. `helper.S` and `colours*.S` come from mpc-vst-machinedrum's `release/mpc_patch` (same author), unchanged; the name table and `cave2.S` are new.
- `asm.sh` assembles them in an arm32v7 gcc container; `make_patch.py <stock MPC>` writes `mpc-3.9.1.2.patch` (our bytes only) and checks the branch chain; `build_script.py` generates `mpc-drum-pad-patch.sh` from the template and the patch.
- Tests: `test_matcher.sh` runs the name matcher under qemu-user at its real address (6 names match, 12 others fall through to Akai's original check, r4 preserved). `test_script.sh` runs the script in BusyBox 1.36 (the Force's shell) against copies of the binary: install, cancelled install, repeated install, uninstall from either backup, upgrade from the old patch, refusing a refused upgrade and other firmware. All pass.
- Patched checksum `f899e581cba179a831212083f9a55ae0`; stock `592eebc8e1ce0797dc8c98e7002143b8`.
- Adding a plugin: add its exact plugin name to the table in `matcher.S`, rebuild, re-run the tests. This folder is the one shared home: plugin repos link here instead of carrying a copy, so the patch is rebuilt in one place when the firmware changes.
