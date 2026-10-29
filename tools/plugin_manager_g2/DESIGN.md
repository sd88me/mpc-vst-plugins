# OpenMPC Plugin Manager G2: design

Status 2026-10-27. Evidence tags: **device** = seen on hardware (Live III, MPC 3.10.0.49, unless stated), **offline** = read
from source or images, **inference** = my reasoning, not checked. Facts about this repo's own code were read from
`src/manager.c` at `f01948b`; the manager was not run.

## 1. Goal and non-goals

Goal: browse, install, update and remove catalog plugins and addins from the MPC screen, on Gen2 first.
- **Right target, never silent.** Install only where MPC will give the plugin its skin, and say on screen when that is not possible.
- **Gen2 native.** aarch64 build, `/data/Settings`, `/nvme/Synths`, `pluginList-arm-64bit`, a restart that really restarts.
- **Safe.** A failed install leaves `MPC.settings` and the plugin folder as they were.
- **Coexists with poloq's manager** (own uid and id, own work folder), so both can be installed while this one matures.

Non-goals: no root route (that is the stick and the desktop app's job); no edits to `SynthContentLocations` (decided with
the user 2026-10-27: too much risk for a few edge cases); no takeover of MPC's screen.

## 2. What we start from

poloq's manager is one C file (`src/manager.c`, 1658 lines) that builds as a VST2 plugin through `mpc-vst-plugins`'
wrapper. It reads the device on open (`probe_device()`), fetches the catalog, queues installs, writes `apply.sh` and runs it
under `systemd-run` so stopping MPC does not kill it, then restarts MPC. Its test harness (`tests/run.sh`) builds the
file against fake devices (`tests/devices/*.sh`) in a `gcc:12` container.

### 2.1 Open work on poloq's repo (no reply from poloq for weeks) and what we do with it

| # | What | Disposition |
|---|---|---|
| PR #12 (ours) | Gen2: `/nvme`, `/data/Settings`, `pluginList-arm-64bit`, restart on aarch64, aarch64 build target | **Take as is** (5 files, +39/-16; includes `tests/devices/gen2.sh`). Branch `ref/pr12-gen2` |
| #9 | exFAT SD rejected; silent fall back to an unwritable internal path; state file in the wrong place | **Fix in section 5**: gate on writable + exec, not on filesystem name; report the reason; state file beside the settings |
| #10 | only the internal drive is offered | **Fix in section 5**: let the user pick among usable `SynthContentLocations` |
| #6 + PR #7 | catalog capped at 64 entries (`MAXPKG`); live catalog has 111+ | **Take the idea** (growable list, cached view). Author's licence unstated: re-implement or ask (see NOTICE.md) |
| #5 (and closed #4) | a plugin whose zip ships no `mpc-plugin.json` drops out of INSTALLED after an update | **Fix in section 6**: write the manifest from the catalog entry after a successful apply |
| PR #8 | reworked screen: category tabs, scrolling list, info overlay, search, thumbnails (+8658/-1045, 135 files) | **Later (M5)**. Read for ideas; ask FullPace before copying; credit as Padbangers |
| #3 | MPC OS 2.x support | **Out of scope for G2**. Plugins load on 2.x but skins do not draw (docs/OS2_SKINS.md in mpc-vst-plugins) |
| #13 (ours, 2026-10-27) | say on screen when the target is not a content location | **Implemented by design in section 5** |
| #11 (ours) | rebuild against the wrapper's Q-Link/automation fix | **Free**: we build against the current wrapper |

## 3. Gen2 facts the design relies on

- **Settings** at `/data/Settings/<profile>/MPC.settings`; Gen1 has `/media/az01-internal/Settings/...` (device, both).
- **Plugin list key** `pluginList-arm-64bit` on Gen2, `pluginList-arm` on Gen1 (device).
- **Storage on a Live III** (device): `/synths` (nvme0n1p1, exfat, **read-only**), `/nvme` (nvme0n1p2, exfat, **rw**, user drive),
  USB `/media/<label>` (vfat, **noexec** on the unit tested 2026-10-22). The only writable, exec-capable place is `/nvme/Synths`.
  Plugins loaded from there draw their skin once `/nvme/Synths` is a content location.
- **A fresh Gen2 may not list `/nvme/Synths`** (offline: stock data dump of 2026-10-09 lists `/synths/Synths`, `/synths/Expansions`,
  `/usr/share/Akai/Content/Synths` and two removable drives). On such a unit the writable drive is not a content location, so every install lands without a skin. Who added `/nvme/Synths` on the tested unit is unknown.
- **Skin rule** (device, MPC 3.10.0.49): the plugin loads from its `file=` path anywhere; its skin is found only through a listed
  `Synths` folder. A trailing `/` on the entry works, and MPC keeps it on save. Untested: a space in the path, a leaf not
  named `Synths`, a clean-quit rewrite of the file.
- **Restart**: `systemctl stop|start acvs` (or `inmusic-mpc` on Hakai firmware). On 3.10 the unit still runs from the
  3.9.1 rootfs with the 3.10 `MPC` bind-mounted over it (device); the restart is unchanged.
- **Root filesystem is dm-verity read-only on Gen2** (device): nothing outside `/data`, `/nvme`, `/media` can be written. This
  is why the addins folder stays `/data/mpc-addins`.
- **No filtering by filesystem type was found in MPC** (offline, strings only: no `noexec`, `/proc/mounts` or `exfat` strings in
  the four `MPC` binaries). `noexec` still blocks loading a `.so` (kernel behaviour).
- **exFAT has no symlinks or exec bits** (inference): `install.sh` restores exec bits and symlinks from a `MODES` file. A package
  with symlinks may fail on exFAT; the desktop app already refuses such a target for a package that needs links (section 4b). Needs a device test before we promise exFAT for everything.

## 4. Review of Eurikon's installer

Read: README, DEVELOPER_FAQ, CHANGELOG, file list (`src/main.cpp`, `backend.cpp`, `sd_install.cpp`, `manager_update.cpp`,
`startup/hotplug.cpp`, `startup/bootstrap.sh`, `tools/deploy.cpp`). Source files not read line by line yet.

**What it is:** a standalone SDL2 application, not a plugin. It is launched from a USB stick or SD card (autorun on 3.9.1; a
"helper" imported into MPC Documents plus Shift+Menu on 3.10), stops MPC, takes the screen, and returns to MPC after five idle minutes.
Its own tests are on a Live II (Gen1) only; our Live III run of 2026-10-27 found 3.9.1 works and 3.10 does not open (docs/NOTES.md, mpc-vst-plugins).

| Idea | Verdict for G2 | Why |
|---|---|---|
| Runs outside MPC (own screen, own process) | **Not adopted** | Takes over the screen, auto-exits, restarts MPC on return (30 s+ on Gen1), and its launch routes are firmware-specific. A plugin stays in the user's project flow. |
| Writes installs through package scripts with `-y -n -t <target>` and `MPC_SETTINGS` set | **Same as poloq** | Both use the package's own `install.sh`. We keep that contract. |
| Requires a settings file, a writable+exec target **and a registered content location** before it lets you install | **Adopt** | It refuses where poloq falls back silently: exactly the skin problem of section 5. |
| `tools/deploy.cpp`: snapshot payload, registry and settings; verify; restore on failure | **Adopt the idea** | Its own FAQ says the default bundle lacks it and script failure can leave partial changes. We add a settings snapshot + restore around the apply. See 7. |
| `plugin-history.json` (schema 1: id, version, installed flag, timestamp), atomic save (temp, fsync, rename), refuses to overwrite invalid data | **Adopt** | History survives a plugin being removed or a zip losing its manifest (#5). Small and independent of the UI. |
| Per-source `local-plugins/` folder (install a zip you put on the drive) | **Adopt later (M4)** | Offline installs; checksum shown, not trusted. |
| Hotplug watcher for USB/SD | **Skip** | Needed for a launcher on removable media, not for a plugin in MPC. |
| Manager self-update from the screen | **Adopt later (M4)** | poloq's manager updates through the catalog like any plugin; keep that, check the hash. |
| 5 min idle exit, restart on crash | **Skip** | Plugin lifetime is MPC's. |
| Install target fixed to `/sdcard/Expansions` | **Not adopted** | Expansions is Akai's content tree; we use `Synths` folders (section 5). Our skin evidence is for `Synths`. |

## 4b. Review of our desktop installer (`mpc-vst-plugins` `tools/desktop`)

Read: its README (all of it), `backups.go`, `remove.go` heads, and a count of what poloq's `manager.c` has (grep, 2026-10-27).
The desktop app runs on a computer over SSH; the manager runs on the device. Same `install.sh` contract, so the safety work
below transfers. What the desktop app does that poloq's manager does **not** (grep found no trace in `manager.c`):

| Desktop feature | In poloq's manager? | Verdict for G2 |
|---|---|---|
| **Zip inspected before it is accepted**: one top folder, the manifest present, no path that leaves the folder, links that stay inside, at most 2 GB unpacked | No: `unzip -q -o` straight into the work folder, after the sha256 check | **Adopt (M3).** The hash proves the file is the catalog's, not that the catalog's zip is well-formed. Do it on the device before `unzip` runs as root |
| **Refuses a target that cannot store symlinks** when the package needs them (FAT, exFAT, NTFS), and a target without room | Space only (64 MB). No link check | **Adopt (M2).** Matters on Gen2: `/nvme` is exFAT (device). Probe with a real `ln -s` in the target and read the package's `MODES` file; say "this plugin needs a drive that stores links" on screen. Plain plugins are unaffected |
| **glibc and OS compatibility** from the catalog (`os_compat`, `max_glibc`): "will not load" / "may show an empty page"; warns, never blocks | No | **Adopt (M3).** Read the device's glibc once; reuse the catalog fields |
| **`<Synths>/.mpc-store`** records what was installed, shared with `mpc-store.sh update` | No: own `.pluginmgr-installed` | **Adopt (M3).** Keep both files in step so a plugin installed by the desktop app or `mpc-store.sh` shows as INSTALLED in the manager and the other way round |
| **Register every plugin folder** (`sync.sh`): folders copied by hand, or dropped from the list by MPC because a card was out at startup, get registered again; the list is backed up first | No | **Adopt (M4)** as an on-screen "N folders are not in MPC's list: register". Same script, same backup |
| **Removal keeps the user's own files** (manifest `user_data`: ROMs, kits, dumps) and refuses what it cannot identify | Runs the package's `uninstall.sh`; no `user_data` handling | **Adopt (M3).** Delete the folder except `user_data`; unknown folders are listed, not removable |
| **Backup pruning** (`MPC.settings.bak-*`: keep the newest N, never the newest, only files named like that) | No: backups pile up | **Adopt (M4)**, on screen, never while MPC is being stopped |
| **Knows whether a release's installer understands `-n`** (`defer` in the catalog) and says how many restarts it will cost | No | **Adopt (M3).** One restart per batch is a user-visible promise |
| **Embedded copies of `plugin_list.awk` / `sync.sh` with a test that they equal the release copies** | n/a | **Adopt** the test: the manager must not drift from the installers |
| Device patches (`patches.json`), firmware-built stick, SSH setup, reconnect/keepalive, drive picker | n/a | Not for a plugin on the device |

Result: the desktop app is better on **package safety, link-capable targets, compatibility warnings, and tidiness**. Poloq's
manager is better on **being on the device** (no computer). G2 takes both.

## 5. Install-target policy (the core fix; closes #9, #10, #13)

Candidates are the **`SynthContentLocations` entries** read from `MPC.settings`, nothing else.
1. Normalise each entry: strip CR and trailing `/` (MPC accepts the slash, device).
2. A candidate is **usable** when it, or its parent if it does not exist yet, is on a mount that is `rw` and not `noexec` and has
   at least 64 MB free. **No filesystem-name whitelist** (poloq's `bad_fs()` accepts only ext3/ext4/f2fs/btrfs, which is why the
   Gen2 `/nvme` exFAT drive and #9's exFAT card are rejected). Keep the leaf rule (`.../Synths`) until the leaf test is done.
3. Show every candidate with its reason when unusable ("read-only", "noexec", "factory content", "under 64 MB").
4. **Pick**: internal storage first (`/nvme`, `/sdcard`, `/media/az01-internal`, or any location on an internal device: `/dev/nvme*`, `/dev/mmcblk0*`, `/dev/loop*`, which is how an MPC One Gen2's `/storage/Synths` (a loop image on eMMC; `/synths` there is read-only) is told from its SD card and USB sticks; the user's own mount and `SynthContentLocations` output, 2026-10-28, offline test `one-gen2-storage`; the symlink rule below applies, `/storage` being exFAT), then others; the user can change it from the
   screen (closes #10), and the place confirmed on the restart prompt is remembered (`.openmpcpm-target` beside the theme preference; used when that folder is still a usable location, kept when it is not); an existing install of a plugin updates in place.
5. **No usable listed location: stop, do not fall back.** Show "Can't install: none of MPC's content locations is writable"
   with the list and reasons, and write the same to `device.txt`. (poloq falls back to its own folder, an installed plugin's
   folder, or a hard-coded default; none of those is checked against the list, and the note goes only to a log file.)
   An **Advanced** switch for an unlisted folder was considered and **not built** (decision 2026-10-28): it would install plugins MPC draws no skin for, and adding a
   location to `MPC.settings` was already ruled out as too risky for a few edge cases. Instead the banner says what is wrong in plain words ("None of MPC's 3 Synths folders can take a plugin", "MPC lists no Synths folder to install into") and `device.txt` has each location's reason.
6. The state file (`.pluginmgr-installed`) sits next to the settings profile, not under the target, so a read-only or
   removed target cannot break it.

## 6. Catalog and the installed list (closes #6, #5)

- Growable arrays; no `MAXPKG`. Cached filtered view rebuilt on refresh, tab or filter change.
- Choose the zip by device architecture from the catalog's `assets.aarch64` / `assets.armv7`; a Gen2-only plugin
  (`gen2_only`) is hidden or marked on Gen1; a plugin with no build for this device is greyed, never queued. Catalog contract: `mpc-vst-plugins` docs/CATALOG_SPEC.md.
- After a successful apply write `mpc-plugin.json` into the plugin folder from the catalog entry (installed version, catalog
  format), so a zip without one still shows as INSTALLED (#5; the version string must match a catalog release).
- Keep `plugin-history.json` as a second source for "was installed".

## 6b. The catalog browser screen (your idea, 2026-10-27)

Wanted: **thinner rows so more fit on a page, a small thumbnail on each row, and a tap on the thumbnail opens a bigger preview.**
Today (poloq 1.2.0, `f01948b`; read, not run): 3 cards per page (`#define ROWS 3`, 118 px tall in a 1280 x 628 plugin area). **Each card
already carries a baked screenshot** (184 x 92, `images/shots/<id>.png`, 84 ids at this commit), picked by `when=r<N>_shot:<id>`
buttons that `vst/shots.py` writes into `layout.conf` (255 lines = 85 ids x 3 rows) and `src/shots.h`; a tap on it (`r1_open`) opens the
details page with a bigger picture (270 x 135, `d_shot`). A plugin added to the catalog after `shots.py` ran "keeps its initials".
So your idea is mostly a **density** change, not a new feature: more, thinner rows, a smaller thumbnail, and a preview that opens on a tap.

Constraints:
- **A skin cannot load a picture from the network.** Every picture is baked into the plugin (see 6c for swapping during a restart).
- The per-id `when=` buttons make `layout.conf` grow with rows x ids: 5 rows would be about 425 lines for 85 ids. Poloq's PR #8 instead bakes a
  filmstrip (frames stacked down one PNG, 140 x 69 per frame, frame 0 generic, at most 127 plugins; big picture 560 x 275, 44 frames per
  strip because a strip may be at most 12288 px). Pick one after measuring MPC's load time for the layout on the Live III.
- A plugin newer than the build shows initials or the generic frame until the next build or thumbnail pack (6c).

Design:
1. **Row**: thumbnail (about 70x35, scaled from the 140x69 frame or its own smaller frame), name, one line of author · tags, badges,
   one action button. Target 5 rows per page; set the row height from the list area once the offline skin preview shows the text fits.
2. **Preview**: tap the thumbnail, or the info icon, for an overlay: the big picture, description, version/size/CPU, INSTALL/UPDATE/REMOVE, BACK. PR #8 already has such an overlay; reimplement unless FullPace agrees to a copy (NOTICE.md).
3. **Budget**: thumbnails as a filmstrip cost the same per row, but each page now drives more widgets (5 rows x image, text, button). Check MPC's screen-thread cost on the Live III before M5 is called done (docs/BENCH.md in `mpc-vst-plugins` has the method).
**Built 2026-10-28 (offline: engine, 105 params, layout, tests pass; the populated rows not yet seen on a device):** `ROWS 5`, rows 74 px apart and 70 tall (`vst/make_rows.py` writes the row layout and params, so a row is described once), a 112 x 56 thumbnail (the baked 184 x 92 ones scaled down; `vst/shots.py` now makes them at that size, 159 catalog screenshots) with the name and one meta line beside it, the channel/CPU badges on the first line and old-install/tested on the second, version and the update's `from` to the right of them, a 150 x 44 action button. The row's size and info lines are gone (the details view still has them). The tap on the thumbnail or title still opens the details view (the overlay below is that view). **Still to measure:** the screen-thread cost of 5 rows (budget item 3).
4. Do this **after** M2 and M3: it changes no behaviour, and the target policy matters more than the picture.

**Cost found on the Live III (device, 2026-10-28):** every thumbnail button is a component on every row, and each skin load makes MPC write cache files to a RAM disk it never empties (NOTES, same date). With 159 ids x 5 rows one load cost 250 to 830 MB and filled the 3.9 GB volume after about ten loads (black patches in the header); with only the 39 ids that have an aarch64 zip a load adds about 14 MB. `vst/shots.py --gen2` bakes that lean set. **Decision 2026-10-28 (the owner's): one big skin for Gen1 and Gen2**, every catalog screenshot (162 ids, about 19 MB zipped, 3.4k components), because on the Force (Gen1) most plugins would otherwise show initials; the Force's cache RAM disk held 0 files with the manager open. The Live III cost is mitigated, not removed: the manager empties the image cache whenever it restarts MPC itself (`apply.sh`, nothing has the files open then) and warns at 85% full; a reboot is still the only other way to empty it. A filmstrip per row (PR #8's way) would cut it further; not needed yet.

## 6c. Thumbnails that are newer than the build

**Done 2026-10-29 (offline; first real run pending):** a weekly check, `.github/workflows/plugin-manager-g2-thumbs.yml` running `vst/thumbs_check.sh`, regenerates the thumbnails from the live catalog, keeps every image already in the repo as it is (the encoder differs between machines) and, when there are new plugins, pushes a branch and opens a PR, or an issue with a compare link because this repo does not let Actions create pull requests. A person merges it and runs the release workflow. The proper fix (a thumbnail pack the catalog serves and the manager installs into its own skin at apply, with generic numbered slots in the layout) is designed above and not built. (loading images "from the network")

A skin cannot fetch an image, and **MPC keeps skins in memory: re-inserting a plugin does not reload a changed skin, only an MPC
restart does** (device, verified 2026-10-04, `mpc-vst-plugins` SKILL.md step 5). So a downloaded picture cannot appear while the
manager is open. There is no way to push pixels either (README Limitations: only pre-drawn images and filmstrips).

What can work (all inference until tested):
1. **Baked strip + generic frame** (section 6b): no network; entries newer than the build show frame 0. First release.
2. **Thumbnail pack published with the catalog.** CI builds the filmstrip and an ids list (frame order) next to `catalog.json`; the
   manager downloads both, checks their sha256, and swaps the strip into its own skin folder **inside the apply, while MPC is stopped**,
   so the new thumbnails show after the restart the apply already does. No plugin rebuild per catalog entry.
3. **Safety**: swap with `x.new` then `mv`; keep the old strip for rollback (section 7); refuse a strip taller than 12288 px (stock sliders misbehave over it) or any image over 16384 px (`PORTING.md`); the ids list must match the frame count, else keep the baked strip.

**Device result 2026-10-27 (Live III, MPC 3.10.0.49):** with MPC stopped, a skin's 78 x 9984 filmstrip was replaced by a colour-swapped copy; after
the restart the knob drew with the new colours (the user's eye), then the original went back by hash. So swapping an image during a restart
works (mpc-vst-plugins docs/NOTES.md, same date). Not yet tested: the largest strip MPC accepts on Gen2, a swap with the plugin open, Gen1.

## 6d. Look and theme (your request, 2026-10-28)

Look: follow the catalog site (`mpc-vst-plugins` `tools/catalog_site/site.css`): warm light grey page `#e9e7e2`, panels `#f7f6f3`, text `#1b1c1f`,
red `#d63a30`, amber `#e0a100`. The dark theme stays as poloq drew it (`#0c0c0d` page), which is also the default.

Switch: **a theme setting that takes effect at the next restart.** An MPC skin is static pictures plus a layout, and a live switch would
double every picture and conditional widget. Instead the plugin folder ships both skins as `Plugin Skins.dark` and `Plugin Skins.light`,
and the manager copies the chosen one over `Plugin Skins` during the restart an apply already does (staged as `.new`, then `mv`). Device-verified
precedent: a replaced skin image shows after a restart (mpc-vst-plugins docs/NOTES.md, 2026-10-27).

Built so far (offline, 2026-10-28): `vst/make_light.py` makes the light skin from the dark one by a colour map by role (the dark skin is unchanged);
built in a scratch copy, rendered with `tools/studio.py preview`, and the restart prompt and header compare well side by side.
Screenshots stay as they are, as does the text over their baked dark corner chip (`*_kindtxt`).

Built (offline, 2026-10-28): the switch and everything behind it. A THEME pill in the header (`theme_btn`, live text `DARK` / `LIGHT  after restart`)
toggles the wanted theme, saved in `<settings base>/.openmpcpm-theme`; a pending theme counts as one queued change, so APPLY, the restart prompt (`Theme: light`)
and the restart flow carry it, and a theme-only apply is just the swap plus a restart. `apply.sh` stops MPC, then stages `Plugin Skins.<theme>` as `.skin.new`
and swaps it over `Plugin Skins` (the old one goes last). The theme in place is read from the file `.theme` inside the skin folder, so a self-update (which brings
the packaged dark skin) shows the pending change again instead of lying. The control is hidden unless both `Plugin Skins.dark` and `.light` are in the plugin
folder. `vst/build_themes.sh` builds both and lays them out; tests: fake plugin folder (`PM_OWN`), `theme` mode in `tests/drive.c`, and `run.sh` runs the generated
`apply.sh` and checks the swap.

Colours reviewed (offline, 2026-10-28, `studio.py preview` dark vs light): cards, the detail panel, INSTALL / UPDATE / queued / disabled buttons, the
"Old install" badge, the progress bar and the restart prompt read well; the "tested" badge border was too pale in light and is fixed in the map (`2f5e46` -> `5fae88`;
rebuild to see it). The live text could not be judged (the preview shows placeholders), only its colours. Logo: the four-square mark is poloq's, so the header and
the browser tile now use the catalog site's brand instead: a red dot with its soft halo and the letter-spaced wordmark (`OPEN MPC - PLUGIN MANAGER G2`).

Device finding (Live III, MPC 3.10.0, 2026-10-28): the manager opened, found `/nvme/Synths` (problem: none), showed 128 plugins and 11 updates with 3 cards per page, and the
THEME pill **flickered**: one tap sent `set theme_btn=1` twice (trace in the manager's log, no release in between), so the theme flipped and flipped back. Fixed: a second
press within 700 ms is ignored. Default is now **light** (no saved choice and the packaged `Plugin Skins` is the light skin; `build_themes.sh` lays it out so).

Not done / not verified: (1) live text colours on device; (2) **a device run**: whether MPC is happy with the extra `.theme` file and the `Plugin Skins.light/.dark` siblings, and that the swapped skin
shows after the restart (the swap itself is the 2026-10-27 device result, for one image); (3) **release packaging**: check that `release.py` ships the two extra
folders; (4) size: each skin is 7.8 MB, so the package grows by about 16 MB.

## 7. Apply and rollback

1. Queue on screen; **APPLY** asks, then writes `apply.sh` (poloq behaviour, kept).
2. `systemd-run` (or the cgroup-v2 fallback) detaches from MPC, stops MPC, **snapshots** `MPC.settings` and each touched plugin folder to a work folder on the same drive.
3. Runs each package's `install.sh -y -n -t <target>` or `uninstall.sh`, checks the exit status and that the plugin-list entry exists (`file=` and `uid`).
4. On any failure: restore the settings and the folders, mark the item failed with the log tail on screen, start MPC.
5. On success: refresh the manifest and history, start MPC.
The restart path must not be compiled out on aarch64 (poloq's `#ifdef __arm__` turned the apply into a dry run: PR #12 fixes it; keep a test that fails if the aarch64 build takes the dry-run branch).

## 8. Testing

Offline, in the existing harness plus new fake devices (each built from a real `MPC.settings` layout, CRLF included):

| Fake device | Case |
|---|---|
| `gen2` (from PR #12) | Live III 3.9.1: no `/sdcard`, `/data/Settings`, `/nvme` exFAT rw |
| `gen2-310` | `/nvme/Synths` **not** listed; listed read-only `/synths/Synths`; USB noexec. Expect "Can't install", no fallback |
| `gen2-nvme-listed` | `/nvme/Synths/` with a trailing slash, CRLF. Expect target `/nvme/Synths` |
| `exfat-sd` (#9) | exFAT card rw+exec listed; internal path unwritable. Expect the card |
| `two-targets` (#10) | two usable locations; pick changes the target |
| `catalog-111` (#6) | fixture with 120 entries; all shown |
| `no-manifest-zip` (#5) | zip without `mpc-plugin.json`; still INSTALLED after update |
| `apply-fails` | package script exits 1 mid-way; settings and folder restored |
| `aarch64-restart` | aarch64 build must call `systemctl`, not the dry run |

Real device, Live III on 3.9.1 and 3.10 (the unit is the user's live setup: ask before every restart, back up first):
adapt `docs/UPSTREAM_TESTING.md`, plus: unlisted target shows the banner; a listed one draws the skin; a failed install rolls back.

## 9. Plan

| Step | Content | Exit test |
|---|---|---|
| M0 | Baseline: run `tests/run.sh` on poloq's code as is | **2026-10-27 (offline): the fake devices and the addin flow pass; the wrapper host test did not.** It failed two checks on poloq's unmodified `f01948b` against today's wrapper (`tick 1 steps one option` and the parameter-0 toggle), and `run.sh` hid that (a pipe). **Fixed in M1** (below). Needs network, Docker `gcc:12` and the `mpc-vst-plugins` checkout next to this folder |
| M1 | Merge PR #12; rename (id, uid, work folder); build aarch64; clean host test | **done 2026-10-27 (offline).** aarch64 build OK; `tests/run.sh` exits 1 when the host test fails (`pipefail`); with the `mpc-vst-plugins` change (branch `host-test-live-params`: `"live": true` params, option tests skip parameter 0) the host test passes and `run.sh` exits 0. Until that change is merged, run with `MPC_VST` pointing at a checkout that has it |
| M2 | Section 5 target policy + fake devices | **M2a done 2026-10-27 (offline):** no filesystem whitelist (rw + not noexec + not tmpfs/ramfs/squashfs/erofs/iso9660/cramfs); no fallback, only usable `SynthContentLocations` entries (problem "No install location", every location and its reason in `device.txt`); `tests/devices/*.expect` are checked, new fake devices `gen2-310-unlisted`, `gen2-nvme-slash` (CRLF + trailing slash), `exfat-sd` (#9), `volatile-location`; a fake `/tmp/pm-mounts` (test builds only) stands in for `/proc/mounts`. **M2b-1 done 2026-10-27 (offline):** a package whose `MODES` lists a symlink is refused, before MPC is stopped, when the target cannot store links (`Linky: needs a drive that stores symbolic links, and <target> does not. Nothing on the MPC was changed.`); test fixture `Linky` + `PM_NOLINKS` hook. **M2b-2 done 2026-10-28 (offline: engine, layout, and an offline skin render of the prompt with `studio.py preview`; not seen on a device):** the restart prompt shows `Install to: <place>  (1 of 2)` and a CHANGE button when more than one usable location exists; CHANGE re-prepares (downloads are cached) and reopens the prompt; fake device `two-targets`, `pick` test. **M3 part 1 done 2026-10-28 (offline, tests `safety`, `arch`; not run on a device):** the zip is inspected before it is unpacked (no absolute or `..` names, no backslashes, under 600 MB unpacked), its manifest `arch` must match the device (refused before MPC stops, so the three wrong-arch updates of 2026-10-28 now say why on screen), each install/update/remove runs inside `item` in `apply.sh`, which snapshots the plugin folder and `MPC.settings`, restores both on a non-zero exit, and writes `id|ok|` or `id|fail|<last line>` to `/tmp/openmpc-pm/result`; after the restart the manager shows `Last apply: N done, M failed and put back as they were. <name>: <reason>` once; the catalog picks the zip by `assets.aarch64`/`assets.armv7` (device: acid-303, commander, tr-mpc queued correctly). **M3 part 2 done 2026-10-28 (offline, test `safety`):** a package that needs a newer glibc than the device (`max_glibc` in its manifest) or lists only another MPC OS (`os_compat`) is refused before MPC stops; the device's glibc is read at run time (`device.txt` has it) and MPC OS 2.x/3.x is *inferred* from it (below 2.39 reads as 2.x), because neither `/etc/os-release` (the Yocto base, 5.0.17) nor `MPC.settings` (stale, 3.9.1.2 on a 3.10 device) gives the MPC OS version (device, read 2026-10-28). **M3 part 3 done 2026-10-28 (offline, test `safety`):** the rollback copy of a plugin folder over 48 MB (`PM_SNAP_KB`) goes to a hidden `.pm-snap-<id>` beside it on its own drive after a free-space check (a copy in RAM could exhaust it), is removed on success, and an old one left by an interrupted update stops that plugin's next update; declared `user_data` is already kept by the package's own `uninstall.sh` (read from tools/release/uninstall.sh, not run). **M3 part 4 done 2026-10-28 (offline, test `safety`):** MPC starts once per apply: after each item `apply.sh` stops an MPC that an older installer without `-n` started again, and starts it at the end. Tests: `ONLY=<section> tests/run.sh` runs one section in about 25 s; the full run is about 9 minutes (it was about 25 until a quietly failing install step, which waited out a 120 s timeout on every device, was fixed on 2026-10-28). **M3 still to do:** `.mpc-store` sharing only (`user_data` is kept by the package's own uninstaller, and MPC now starts once per apply). **M2 finished 2026-10-28 (offline):** the red banner and the status line say what is wrong in plain words (device tests `no-synths-location.banner`, `volatile-location.banner`), and the Advanced switch for an unlisted folder was decided against (section 5); only device runs remain |
| M3 | Section 6 (catalog size, manifest), section 7 (rollback), and the 4b items marked M3 (zip inspection, glibc notes, `.mpc-store`, `user_data`, `-n` count) | `catalog-111`, `no-manifest-zip`, `apply-fails` pass |
| M4 | History file, local zips, self-update, register orphan folders, backup pruning (4b) | offline pass. **Done 2026-10-28 (offline, test `safety`):** `plugin-history.json` beside the state file (one line per plugin: id, version, installed, time; atomic; a file that is not ours is left alone; its version is a second source for an install the state file lacks); backup pruning (after a successful apply with MPC running, keep the newest 10 `MPC.settings.bak-*`, touch nothing else; automatic rather than a screen button, so it also runs for backups other installers made). **Local zips done 2026-10-28 (offline, test `safety`):** `<parent of a usable content location>/local-plugins/<name>.zip` becomes a card ("by local zip", its own sha256 on the card; nothing checks it against the catalog) and installs by the same steps as a catalog package. **Register orphan folders built 2026-10-28 (offline, test `safety`; not yet run on a device):** a folder in a usable content location with a `plugin-meta.xml` whose `file=` exists but whose file and uid no entry has is a card in INSTALLED ("not in MPC's list"); REGISTER queues it, and `apply.sh` adds the entry with the installer's own `plugin_list.awk` (embedded in `src/plugin_list_awk.h`, `vst/gen_awk.py`) inside `item`, which snapshots `MPC.settings` first. The Live III had no orphan (device: every folder in `/nvme/Synths` had an entry; both USB sticks are `noexec` vfat and not content locations), so a test folder was made there on 2026-10-28. **Still to do:** self-update |
| M5 | Screen rework: thin rows, thumbnails, preview (section 6b; ask FullPace before copying PR #8) | device run |
| Device | Live III 3.9.1, then 3.10; Gen1 (Force) regression | table in docs/ with dates |

## 10. Open questions and risks

- **Does `systemd-run` detach work on Gen2 3.10?** poloq's code has an "untested" cgroup fallback; only Gen1 was run. Device test needed before M3 is called done.
- **Leaf name**: must the location end in `Synths`? Untested on a device.
- **How is the manager itself installed on Gen2 3.10?** There is no autorun route; use `mpc-vst-plugins`' desktop app or Eurikon's helper (does not open on 3.10 yet).
- **Licence of PR #7/#8 code**: ask before copying (NOTICE.md).
- **Name**: "MPC" is Akai's mark; the project already uses it descriptively. Keep "OpenMPC" wording off logos and the plugin's skin art.
- **exFAT and symlinks** (section 3): test a package that ships a symlink on `/nvme`.
- **Catalog id**: poloq's manager is catalog id `plugin-manager`; this one needs its own id and uid, and a catalog entry only after a device pass.
