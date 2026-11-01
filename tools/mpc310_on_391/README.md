# MPC 3.10 on an MPC Live III that stays on MPC OS 3.9.1

A USB stick that makes an MPC Live III (Gen2) run the **MPC 3.10** app at every start, while the device itself stays
on **MPC OS 3.9.1**. Useful if you want 3.10's features but need something only 3.9.1 allows, such as the USB-script
route developers use for SSH. Pull the stick and restart, and it is plain 3.9.1 again.

**Unofficial. Not made or supported by Akai.** Tested on one MPC Live III, 2026-10-24. Use at your own risk.

## What you need
- An **MPC Live III** (Gen2) on **MPC OS 3.9.1**. Other Gen2 models are untested.
- Two official update files from Akai's website: **MPC 3.10.0 for Gen2** and **MPC 3.9.1 for Gen2** (the `.img`
  files). This tool includes nothing from Akai: it takes the 3.10 app from the first and the stick's signature from
  the second, on your own computer.
- A **USB stick** (1 GB or more), formatted **FAT32**, that stays in the Live III.
- A computer with **Linux** or **Windows with WSL**, Python 3 and `debugfs` (`sudo apt install e2fsprogs`).
- About 450 MB free on the Live III's internal storage.

## Steps
1. Download this folder and the two Akai update files.
2. Build the stick contents:

       python3 build_stick.py --img310 MPC-3.10.0-Gen2-update.img --img391 MPC-3.9.1-Gen2-update.img --out stick

   (2-3 minutes; add `--ask` if you want MPC to ask before each start instead of running by itself.)
3. Copy **everything inside** the `stick` folder to the **root** of the FAT32 USB stick.
4. Save your project, put the stick in the Live III and restart it. On the first start the Live III copies the
   3.10 app to its internal storage (a minute or two), then MPC restarts as 3.10. Every later start takes a few
   seconds longer than usual and comes up in 3.10.
5. Leave the stick in.

What happened is written to `mpc310-result.txt` on the stick.

## Going back to 3.9.1
- For one start: put an empty file called `disable-310` on the stick, or take the stick out, and restart.
- For good: take the stick out. The 3.10 files stay in `/data/mpc310` (about 415 MB) until you delete them.

## Good to know
- **Projects and settings:** projects saved in 3.10 may not open in 3.9.1. Before its first 3.10 start the stick
  backs up MPC's settings file (`MPC.settings.bak-before-310`). Keep copies of projects you care about.
- **It runs as root.** MPC's USB-script feature runs the stick's script with full rights. Only use a stick you
  built yourself (or from someone you trust). The stick checks the 3.10 files against its own list before installing
  them.
- **Akai could close this.** A future MPC OS update may change or remove the USB-script feature.
- **Developers:** `--ssh-key ~/.ssh/id_ed25519.pub` also starts root SSH (key login only) for each start. Addins in
  `/data/mpc-addins/` are re-added each start (the Live III keeps their drop-in on /run), and an addin's own
  `boot.sh` there runs once per start, after 3.10 is set up (for example to start a helper the addin needs).
- **Never share a built stick**, and never publish the signature salt: build your own from the official files.

## How it works
MPC OS 3.9.1 runs a script from a USB stick at start-up when the stick carries `autorun/` with a matching
`autorun.check` (a SHA-256 over the stick's files plus a value inside the MPC program; `tools/saltscan.py` finds it
in the 3.9.1 image). The script (`stick/run.sh`) copies the 3.10 app to
`/data/mpc310` once, then for each start adds a temporary systemd drop-in that mounts the 3.10 program and its
`/usr/share/Akai` over the 3.9.1 ones inside MPC's service only, and restarts MPC. Nothing on the system partition
changes; the drop-in lives in RAM and is gone at the next restart.

Tests: `tests/run_test.sh` (Docker, BusyBox userland like the device).

## Credits
This builds on two people's work, credited equally: **TheKikGen**, whose MPC-LiveXplore wiki documented MPC OS's
USB autorun feature, and **Eurikon**, who worked out its check and first used it for a no-SSH USB plugin manager
(plugin-manager-usb, MIT). `tools/saltscan.py` was written in this repo and shared with Eurikon's project.

