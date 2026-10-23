# Install from a USB stick, no SSH (offline-built; device-verified on Force 2026-10-13)

Status (2026-10-13, device): **works end to end on a Force (stock 3.9.1.2 with addins), one run.** Stick made by `make_stick.py`
from the stock Force 3.9.1 MPC, FAT32 stick: the stock prompt appeared, Install ran `open.sh` as root, `mpc-store.sh` downloaded
`plugin-manager` 1.2.0 (hash-checked), stopped MPC, installed it, wrote the plugin-list entry (47 entries, `MPC.settings.bak-*`
kept) and started MPC again; the whole run took 5 seconds and wrote `mpc-install-result.txt` and `MPC.settings.backup` to the
stick. The user then loaded Plugin Manager on a track and reported it works (user-reported, not examined further by us). Not yet
seen: a stick made from a Gen1 image run on real Gen1 hardware, a real Gen2 run of this project's stick, offline use. Not
released and not in the installer app.

**MPC OS 3.10.0 breaks this route (2026-10-23, offline, static analysis only — not flashed to a device).** Comparing the stock
`MPC-3.9.1-Gen2-update.img` and `MPC-3.10.0-Gen2-update.img` binaries: 3.10's `MPC` no longer contains the `.check` string, the
`open.sh` string, or the salt bytes `saltscan.py` relies on — all gone. In their place, right next to the same "Script detected...
Do you want to run it?" prompt code, 3.10 adds `*.scriptpkg` and `/usr/bin/az01-signed-fs` — a signed-package scheme replacing the
salted hash. This matches TheKikGen's prediction below. **A stick built by this tool will not be accepted once a device is
updated to 3.10+;** it still works on any device still on 3.9.1 (or an earlier Gen1/Force build using the same scheme).

## How the route works

MPC OS up to 3.9.1 (Gen1 and Force) has a stock "USB script" reader. A stick with `autorun/autorun.json`, `autorun/autorun.check`
and the files the JSON lists makes MPC ask, then run `autorun/open.sh` as root (the journal shows `az01-script-runner` running
it). It is not an exploit, and not described in Akai's guide. Credit for finding it and working out the check: **Eurikon**
(<https://github.com/Eurikon/plugin-manager-usb-for-open-mpc>, MIT, tested on a Live II Retro, 3.9.1), whose own manager uses the
same route.

`autorun.check` is `sha256(autorun.json + open.sh + each listed file in the listed order + salt)` as hex text. The salt is 37
bytes kept XOR-obfuscated in the MPC executable (an 8-byte key, repeated), padded with zeros. The same salt value is in the stock
Gen1 3.9.1 MPC, the stock Force 3.9.1 MPC, a Force at 3.9.1.2, and the stock Gen2 3.9.1 MPC (offline scan, 2026-10-13/10-20); only
its position differs, and it appears twice. The scheme is gone in MPC OS 3.10.0 (see above).

## What is in this repo

- `tools/usb_stick/saltscan.py`: finds the salt by scanning a firmware file (a raw MPC executable, or an update image whose root
  filesystems are xz streams) instead of reading a fixed offset. A genuine salt is shorter than the 37-byte reserved field (zero
  padding); a candidate that fills the whole field with printable bytes is dropped as noise if a padded one is also found (needed
  on the Gen2 aarch64 rootfs, which has several such false positives — 2026-10-20). Refuses when there is no candidate or two
  different *padded* values. Refuses outright (no candidate at all) on a 3.10+ image.
- `tools/usb_stick/make_stick.py`: `--firmware <update.img | MPC> --out <folder> [--install id,id]
  [--ssh-key <path to a .pub file> | --ssh-password <password>]`. Writes the stick folder. `--ssh-key`/`--ssh-password` are
  advanced, optional, and separate from the autorun mechanism itself (below): they bundle `enable_ssh.sh` and either a copy of
  that one public key file (never the private key, which never goes near this tool) or a password file, so the stick also sets
  up an ordinary SSH login, not just the one-shot root shell the autorun prompt itself grants. Most people don't need either.
- `tools/usb_stick/enable_ssh.sh --key <authorized_key.pub> | --password <password>` (2026-10-23, password mode added
  2026-10-23): lets root in over SSH. `--key` doesn't weaken authentication (stock `sshd_config` already allows key-based root
  login and forbids passwords/empty passwords). `--password` does -- it sets root's password and turns password login on, so
  anyone who learns it gets a root shell; it needs a writable root to persist the password in, and is **refused outright** on a
  true read-only (dm-verity) root (most Gen2 units), rather than leaving the device half-changed. Detects writable-vs-not the
  same way `resolve_dropin_root()` in mpc-vst-plugins' addin installer does: a writable root (or one that can be remounted rw,
  Gen1/Force) gets the key/password installed persistently, `sshd` enabled at boot; a true read-only root (dm-verity, e.g.
  Gen2's Live III -- remount refused outright) gets a key on `/run` (tmpfs) and `sshd` started directly with it, for that boot
  only (re-run, i.e. reinsert the stick, after every reboot) -- or, for `--password`, is refused as above.
- `tools/usb_stick/open.sh` + `run.sh`: on the device. `open.sh` copies the runtime to RAM and starts `run.sh` as a systemd unit;
  `run.sh` first runs `enable_ssh.sh` if the stick carries a key or a password file, then reapplies every already-installed addin's
  `install.sh -y -n` (2026-10-23: a no-op where its LD_PRELOAD entry persisted; on a device with no persistent `/etc` at all,
  e.g. Gen2's Live III, the entry lives on `/run` and a reboot wiped it, while `/data/mpc-addins/<id>/` itself -- including its
  own copy of `install.sh` -- survived; mpc-vst-plugins `docs/ADDINS.md`, "A device with no persistent /etc"), then copies
  `MPC.settings` to the stick, then runs the bundled `mpc-store.sh -y install <ids>` (default `plugin-manager`; ids from
  `install.txt` on the stick) and writes `mpc-install-result.txt`. `mpc-store.sh` stops MPC once, starts it once, and starts it
  again on failure. It does not touch `LD_PRELOAD` itself, so addins keep working. `mpc-store.sh` already picks the aarch64 vs
  armv7 zip by `uname -m` and the right `MPC.settings` plugin-list key per generation, so the same stick build works unmodified
  on Gen1 and Gen2. The result: reinserting the stick restores SSH, every addin, and installs/updates catalog plugins, all in
  one step, on a device like the Live III where none of it survives a reboot on its own.
- `tools/test_usb_stick.py`, CI in `.github/workflows/usb-stick.yml`: made-up salt; the real one is never stored.
- `tools/desktop/stick.go` (2026-10-23): a Go port of `saltscan.py` and `make_stick.py` into the downloadable installer app, so a
  user who would rather not use Python/the CLI can build a stick from a web page -- a new top-level mode there ("Plugin install
  (no SSH or connection needed)"), independent of the SSH-based install steps, with an explanation of what it does and what it's
  compatible with up front. Same algorithm (`tools/desktop/stick_test.go` mirrors `tools/test_usb_stick.py`'s cases), same
  output. The firmware path and output folder each have a **Browse…** button (`tools/desktop/browse.go`, a server-side picker,
  since a browser's file input can't hand back a real path) and the output folder also lists mounted drives
  (`tools/desktop/drives_*.go`) so picking a USB stick there writes the build straight onto it -- `BuildStick`/`make_stick.py`'s
  `build()` accept an output folder that already exists, as long as it's empty, since a mounted drive's own root directory
  always "already exists" (it's the mount point); a non-empty folder is still refused (2026-10-23 fix: picking a drive from the
  list used to always fail with "already exists", since the first version only accepted a brand-new folder). "Empty" ignores a
  drive's own housekeeping (`System Volume Information`, `$RECYCLE.BIN`, dotfiles like `.Trashes`/`.DS_Store`/`.Spotlight-V100`)
  since a freshly formatted Windows drive always has `System Volume Information` on it on its own (2026-10-23 fix: a user's real
  freshly formatted stick was refused as "not empty" for exactly this). The salt scan (slow on a Gen2
  image, which needs the pure-Go xz decompressor) reports periodic progress so it doesn't look stuck. SSH access is its own
  collapsed, closed-by-default "Advanced" section: a key (paste one, or the app generates an ed25519 keypair and shows the
  private half once) or, with heavier warnings, a password -- most people leave this on "None". See `tools/desktop/README.md`.

## Rules

- The salt is Akai-derived: it is read from the user's own firmware when the stick is made, and is never committed, logged or put
  in a release. Do not publish a ready-made stick.
- Anything on the stick that the check covers (`autorun.json`, `open.sh`, `runtime/*`) is fixed once the check is made;
  `install.txt` sits outside it on purpose, so the plugin list can be edited.
- The plugin manager is `plugin-manager` from the catalog (a VST app listing the catalog on the MPC screen).

## Not known yet

- Not run end to end on real Gen1 hardware, or on any real Gen2 hardware (Gen2 autorun itself is community-reported to work —
  2026-10-20 — and the salt is confirmed offline in the Gen2 3.9.1 image, but this project's stick has not been run on a Gen2
  device). First run on a new device: back up `MPC.settings`, save the session, ask before the restart.
- The stick's default install, `plugin-manager` (poloq-instruments/mpc-vst-manager), had no aarch64 build at all until
  2026-10-23: `mpc-store.sh` would refuse it on Gen2 with no Gen2 build, so the stick's default install did nothing there.
  A Gen2-compat PR (device probe: `/nvme`, `/data/Settings`, `pluginList-arm-64bit`, plus an aarch64 build) is open at
  <https://github.com/poloq-instruments/mpc-vst-manager/pull/12>, offline-tested only (fake Gen2 device + aarch64/QEMU);
  not yet merged, not yet run on real Gen2 hardware.
- Needs internet on the device for the catalog. An offline stick (bundled zips) is not built.
- Other MPC OS 3.x point releases and Key/X/One: the salt scheme and the reader are still unchecked, beyond the 3.10.0 break
  above.
- Akai can change or close the route in an update (now confirmed happening at 3.10.0). The scripts run as root; keep the stick's
  contents to what the catalog installs.
- Turning an update image into a stick takes about a minute on a laptop (the root filesystem is scanned).
