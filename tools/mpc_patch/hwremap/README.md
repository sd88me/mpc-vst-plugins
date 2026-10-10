# Optional: button remap (hwremap)

Not part of any plugin release. `hwremap-patch.sh` is a standalone script you run on the device yourself, if you want it. The installer app lists it in its read-only "Advanced: device patches" step, next to the 16-pad drum layout and the drive exec patch.

> **Tried on one Force, not on an MPC Live.** On a Force (MPC OS 3.x, 2026-10-10) this script's `install` ran, `status` reported patched, and every rule in the default options worked by hand, including the `combo` rules and the touch taps. The shim itself was also tried by its author on an MPC Live (Hakai, MPC 3.9.1) and a Force (stock firmware 3.9.0). Not yet run: the checklist on a real terminal, the Knobs options, the MPC Live map through this script, and `uninstall` on a device. It does **not** work on a Force that runs MockbaMod's input path (see NOTES 2026-10-10). Save the project before you run it: it stops and starts MPC.

## What it does
The devices have no setting for "this button opens that screen". `hwremap.so` is an `LD_PRELOAD` library that rewrites the controller's button stream, so a press can become other buttons, a pad, or a touchscreen tap. To MPC it looks like you did it yourself. Holding **Menu** and tapping a pad opens the icon in that cell of the Mode Menu, which is how a button opens a screen.

The library and the two example maps are inside the one script. Full behaviour, the config language and the button notes are in the upstream README (vendored notes in `VENDORED.md`): https://github.com/mmiroshnikov/akai_standalone_remap

| Device | What the script changes | Default map |
|---|---|---|
| Hakai (a launcher `/usr/bin/az01-launch-MPC`) | `/usr/lib/hwremap.so`, and that launcher's `LD_PRELOAD` lines. The root filesystem is remounted writable for a moment. | Pad Bank A–D and `+` / `−` open Mode Menu cells. Shift keeps the original button. |
| systemd (`acvs` or `inmusic-mpc`; a stock Force) | `/data/hwremap/hwremap.so`, and a drop-in that adds it to the service's `LD_PRELOAD`, keeping whatever was already there. | The options below (Mixer, Edit, Clip, Menu; the Knobs ones are off unless you pick them). |

## The Force options
The Force map is a set of options. Install asks which to turn on (a checklist on a terminal) or takes them as flags. The Knobs options change what a Knobs press does, so they start off.

| Option | Default | What it does |
|---|---|---|
| `mixer-master` | on | Mixer twice: Master (the first press opens the mixer as usual) |
| `mixer-tabs` | on | Mixer + Up / Down / Left / Right: the mixer's Pan & Volume / Effects / I/O / Sends tabs |
| `edit-editor` | on | Edit twice: the plugin / track editor (the stock Shift + Clip shortcut) |
| `clip-arrange` | on | Clip + Left: Menu, then Arrange |
| `menu-main-mode` | on | Menu twice: tap the Main Mode icon |
| `knobs-short` | off | Knobs, short press: Shift + Knobs (Shift + Knobs is then a plain Knobs press) |
| `knobs-long` | off | Knobs, long press: a plain Knobs tap |
| `knobs-double` | off | Knobs, double press: the original long press (Knobs held while you hold the button, at least `holdms`) |

`clip-arrange` and `menu-main-mode` tap Mode Menu icons by screen position, so they need the default Mode Menu layout: **Arrange in the top-left slot of page 1**, and Main Mode where `configs/force.conf` expects it. The mixer tabs and the Shift + Clip editor shortcut do not depend on any layout.

```
sh /tmp/hwremap-patch.sh options                          # the list above, with the defaults
sh /tmp/hwremap-patch.sh install                          # a checklist on a terminal, then the typed word
sh /tmp/hwremap-patch.sh install --options mixer-tabs,edit-editor   # exactly these (all and none also work)
sh /tmp/hwremap-patch.sh install --without clip-arrange   # the defaults, minus one
sh /tmp/hwremap-patch.sh install --with knobs-double      # the defaults, plus one
```
Without a terminal (over ssh with no tty) and without flags, install uses the defaults and says so. `--confirmed` never asks. The choice is recorded and `status` shows it. It only applies when the config is written, which is the first install: with a `/sdcard/hwremap.conf` already there the flags are ignored, so edit that file, or uninstall (an untouched config is removed with it) and install again.

The map is written to `/sdcard/hwremap.conf` only when that file is not already there. Editing it applies on the next button press; MPC does not restart for a config change. `--layout mpc-live` or `--layout force` picks the map on a device that is not the one it was written for.

## Use
```
scp tools/mpc_patch/hwremap/hwremap-patch.sh root@<device-ip>:/tmp/
ssh root@<device-ip>
sh /tmp/hwremap-patch.sh status                 # changes nothing
sh /tmp/hwremap-patch.sh install                # asks you to type PATCH; MPC restarts
sh /tmp/hwremap-patch.sh uninstall              # asks you to type REMOVE; MPC restarts
```
`install --confirmed` skips the typed question and the checklist (the installer app will use that later; it is not wired up yet). A backup of the launcher or the service environment goes to `/data/mpc-vst-plugins/backups`.

To turn the remap off without uninstalling, empty `/sdcard/hwremap.conf`. With no rules the shim passes every button through.

## Uninstall by hand
While the patch is installed it keeps the original launcher at `/data/hwremap/az01-launch-MPC.orig`. If the script is gone: stop MPC, remount `/` writable, copy that file back over `/usr/bin/az01-launch-MPC`, delete `/usr/lib/hwremap.so`, remount read-only, start MPC.

Force: remove `/etc/systemd/system/acvs.service.d/hwremap.conf` (or the `inmusic-mpc` one), `systemctl daemon-reload`, restart MPC, delete `/data/hwremap/hwremap.so`.

## Credit
`hwremap.c` and the Live config are https://github.com/mmiroshnikov/akai_standalone_remap at commit `9d2aa57a570b0c4788f88b04ca242bb82176c380`, MIT. Local changes: a `combo HOLD SRC tokens...` rule in `hwremap.c` (any button can be the modifier, not only Shift), and the Force map, which is this repo's own set of options. The device build here uses `arm32v7/gcc:11-bullseye` (glibc 2.31; the library needs glibc 2.17). See `VENDORED.md`.

## Tests
`python3 tools/test_hwremap_patch.py` (a scratch root, shims for `systemctl` and `pidof`: both install styles, the typed words, rollback, a config you edited, a preload that is not a plain path). `./build.sh test` runs the library's own host tests under ASan. Neither has been run on a device.
