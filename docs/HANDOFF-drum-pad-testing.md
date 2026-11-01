# Handoff: testing the 16-pad drum layout patch (2026-10-31)

All of it is merged to `main` (PRs #659, #660, #662). The script is `tools/mpc_patch/mpc-drum-pad-patch.sh` (version 8); the
catalog entry `drum-pad-layout` is pinned to it. What is verified and what is not:

| Target | Stock MPC md5 | Status |
|---|---|---|
| Force, MPC OS 3.9.1.2 | `592eebc8e1ce0797dc8c98e7002143b8` | long verified on a Force |
| Gen2 (Live III) 3.10.0 kit | `15a664f6b6ae591c8b78baae8b376f02` | device: install, 16 lit pads, reapply, uninstall, reinstall |
| Gen2 3.9.1 | `a7ace6a9993df33afeae50571755bbf9` | **offline only** |
| Gen1 (Live/One/X/Key) 3.10.0 | `b6cc8e7a398bdf6c3fd8f7176eecd3ee` | **offline only** |
| Gen1 3.9.1 | `250368c6a337970028b2a5ce96308d15` | not supported (UPX-packed) |

Run every test on the device as root over ssh; copy the script with scp. `sh mpc-drum-pad-patch.sh status` changes nothing and
ends with a `STATE` line. Save your project first: install and uninstall restart MPC.

## Gen2 3.9.1 (needs plain 3.9.1, not the 3.10 kit)
1. Put `disable-310` at the root of the mpc310-on-391 stick and boot with it (or remove `/run/.../95-mpc310.conf` and
   `systemctl restart acvs`). Check: `status` says `Gen2 3.9.1`.
2. `sh mpc-drum-pad-patch.sh install`, type PATCH. Expect "patched OK", MPC restarts, and a plugin from the table
   (Machinedrum Module, Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip) shows 16 lit red pads.
3. `uninstall` and check `status` is stock again. Report the `md5sum /proc/$(pidof MPC)/exe` after install (want `0c819376e5a72803ec97c5c8b582f36e`).

## Stick boot calling `reapply` (Gen2, 3.10 kit)
With the drum patch installed (`/data/mpc-drumpad/mpc-drum-pad-patch.sh` exists), reboot with the mpc310-on-391 stick in.
Read `mpc310-result.txt` on the stick: expect a "Restarting MPC with the drum-pad patch" or "already" line, then
`status` says PATCHED and running. Without the stick the stock MPC runs after a reboot (the drop-in lives in /run).

## Gen1 3.10.0 (a Live / One / X / Key; never run on a device)
Rootfs is patched in place (like the Force), full backup goes to `/sdcard/MPC-backup/MPC-3.10.0-Gen1.orig` (about 115 MB free needed).
1. `status` should say `stock Gen1 MPC OS 3.10.0`. If it says unsupported, send the printed MPC checksum.
2. `install`, type PATCH. Expect "patched OK" (checksum `496c22afe2f57f5c583072a02d754f07`) and MPC back after about 5 s.
   If MPC does not start, the script restores the original by itself on a checksum failure; otherwise `uninstall` or copy
   the backup over `/usr/bin/MPC`.
3. Load a table plugin as a drum program: 16 lit red pads, pad n sends note n-1; Akai's own DrumSynth also shows 16 red pads.
4. `uninstall` restores stock.

## If something goes wrong
Gen2: `uninstall` removes the copy and the drop-in; a reboot also clears the drop-in. Gen1/Force: `uninstall`, or
`cat /sdcard/MPC-backup/<backup file> > /usr/bin/MPC` with the root remounted rw.

Source and offline tests: `tools/mpc_patch/` (`gen1/`, `gen2/`, `test_script*.sh`); findings in `docs/NOTES.md` (2026-10-30, 2026-10-31).
