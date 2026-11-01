# Gen2 (aarch64) support: design and status

Gen2 MPC devices (MPC Live III and kin, RK3588) run a 64-bit userland: `/usr/bin/MPC` is ELF64 aarch64 with
`/usr/lib/ld-linux-aarch64.so.1` and there are no 32-bit libraries, so Gen1's armv7 `.so` files cannot load
(analysed 2026-10-06 from the 3.9.1 Gen2 update image, offline; see `docs/FIRMWARE_BUILDER.md`). A plugin needs a second, aarch64 build.

**Status (2026-10-11): two Gen2 device confirmations, pilot phase done.** Crate Digger 1.1.9 and Profit-08 0.1.1's aarch64 builds
both installed on a real MPC Live III (MPC OS 3.9.1, the official user-facing version; the "5.0.18 (scarthgap)" read on the
device is the underlying az01/buildroot base, not the MPC OS version), registered, showed up in MPC's plugin browser and ran (Crate Digger's skin
and open/close were checked in detail; Profit-08 was reported "working well" by the same tester, not yet broken down feature by
feature on our side). Both plugins' `tested.json` carry the device. This settles the open questions from the first pilot:
- **`pluginList-arm-64bit` is confirmed correct** for registering an aarch64 package (the earlier third-party tester report was
  right; `plugin_list.awk -v listkey=...` and `install.sh`/`sync.sh`'s arch-based choice need no further change).
- Install target: on this device `-t` had to point at a removable Synths folder (`/media/<label>/Synths`); `/sdcard` wasn't mounted
  and `/synths/Synths` was mounted read-only (see NOTES.md 2026-10-10). No Gen2-specific install default was needed.
- **Second Gen2 unit, MPC OS 3.9.1 (2026-10-22): the writable internal drive is `/nvme`.** On a user's MPC Live III (aarch64,
  glibc 2.39) the rootfs is dm-verity read-only, `/sdcard` isn't mounted, `/synths` is read-only, and the only `/media` drive was
  mounted `noexec` (unusable for a `.so`). The one writable+exec location is **`/nvme/Synths`** (`/dev/nvme0n1p2`, exfat); settings
  are at `/data/Settings/MPC/MPC.settings`. JV-880 1.0.8 aarch64 installed there (`install.sh -t /nvme/Synths`) loads, draws its
  skin, browses expansions and makes sound — `pluginList-arm-64bit` confirmed again. The installer now handles this: `mpc-store.sh`
  defaults to `/nvme/Synths` when `/sdcard` is absent, and `tools/desktop` scans `/nvme/Synths` and makes it the "internal drive".
- **MPC One (Gen2), MPC OS 3.9.1 (2026-10-28, a user's `mount`/`df -h` over SSH plus the stock firmware's mount units, offline):
  no NVMe.** `/` is a 624 MB dm-verity root (96% used); `/synths` is eMMC `mmcblk0p11` (17.8 GB, 91% used, 1.5 GB free);
  `/data` is `mmcblk0p12` (33 GB, shown 100% used: it holds the user-storage image); **`/storage` is a 31 GB loopback
  (`loop0p1`, 17 GB free)**, the Key 37's layout; the SD card is `/media/MPC`. The firmware mounts `/nvme`, `/content`,
  `/sdcard` or `/storage` depending on device tree flags under `/sys/firmware/devicetree/base/chosen/` (`inmusic,nvme-fitted`,
  `inmusic,emmc-content`, `inmusic,internal-sd-fitted`, `inmusic,acvs-loopback-content`), so the internal drive is not
  `/nvme/Synths` everywhere. `tools/desktop` now tries `/nvme/Synths` then `/storage/Synths` as the internal drive and lists
  `/storage` as a drive that can be given a Synths folder; `mpc-store.sh` falls back the same way. **Confirmed by the same
  user's follow-up (2026-10-28, `mount` and `grep` over SSH):** `/storage` is `exfat (rw,relatime,fmask=0022,dmask=0022,...)`,
  no `noexec`; `/synths` is `ext4 (ro)`; `/data` is `ext4 (rw)`. Their `MPC.settings` `SynthContentLocations` lists
  `/media/MPC/Synths` and `/storage/Synths`, and eight plugins (including Acid-303) are already installed and registered under
  `/storage/Synths`, so that folder exists, is executable and is what MPC scans; the full `/data` did not stop earlier
  settings edits. Their `Content.Manager.Directory` is `/media/MPC/` (the SD card, `mmcblk1p1`), so the community manager 1.2.1's
  "automatic" plugin location would be `/media/MPC/Synths` (also registered with MPC), not `/storage/Synths`; whether that SD
  mount permits executables was not shown (the manager refuses a `noexec` drive and then wants SETUP > Plugin location).
  `tools/release.py` used to print `-t /nvme/Synths` for every Gen2 build, wrong on a One: since 2026-10-28 a Gen2 `INSTALL.md` says
  `<your Synths folder>` and tells the reader to take it from `SynthContentLocations` (`/nvme/Synths` Live III, `/storage/Synths` One).
- `vst.json` `targets: ["armv7", "aarch64"]` + `tools/build_port.sh ... all` is now proven end to end on a second, ordinary port
  (Profit-08: no custom build script, just the generic path) — any future port can follow the same checklist (docs/PORTING.md).

Not yet working: Crate Digger's Discogs search returned an error on-device (not yet diagnosed; could be network, DNS, TLS/cert, or
something arch-specific in the bundled yt-dlp/Python). Not claiming full functional parity for it until that's resolved.

**Root/SSH on Gen2 (2026-10-22/23).** The autorun-stick mechanism (KikGen's write-up, see NOTES.md) works the same way on a real
Gen2 unit's stock MPC OS 3.9.1 as on Gen1/Force: inserting a stick with a signed `autorun.json`/`autorun.check` gets a root shell
on demand (not persistent across reboot; see `docs/USB_STICK.md` for the generator, offline-tested, not yet run by us on Gen2
hardware). **MPC OS 3.10.0 removes this mechanism** — confirmed by a static diff of the stock update images: the `.check`/`open.sh`
strings and the salt bytes are gone from 3.10.0's `MPC` binary, replaced by a `*.scriptpkg`/`az01-signed-fs` signed-package scheme.
A device already updated to 3.10+ has no documented root route from this project, but Eurikon's plugin manager stick works there (confirmed on a Live III running stock 3.10, 2026-10-29, device: it opened on insertion because the helper, `Plugin Manager helper.xpa`, had been imported earlier and persisted in the shared `/nvme/MPC Documents`; the helper is still required once on 3.10); it runs only his manager, not our SSH or addin steps (his helper copies a fixed, hash-checked file list and never runs the stick's `open.sh`, read from its `bootstrap.sh` v1.2.2). (One unverified community report says a live
OTA update to "3.10.0" left a device's rootfs still reporting "3.9.1" underneath — if real, that specific device might still take
an old-scheme stick; not something to rely on.)

Update (2026-10-20, community-reported, not run by us): the stock **autorun-stick route** (see NOTES.md 2026-10-13 and the
2026-10-20 entry) is now reported to work on **Gen2** — one user confirmed it on Gen2 and used the same bug to enable SSH.
If that holds, it would be a no-hack Gen2 root route usable by this project's USB stick, but we have not generated or run a
Gen2 autorun stick, and the Gen2 salt/offset is unverified. Akai is predicted (unverified) to patch autorun in firmware v3.10+.
Offline (2026-10-20, us): the autorun salt in the Gen2 stock image `MPC-3.9.1-Gen2-update.img` is **identical to Gen1/Force**
(same value, in the Gen2 main rootfs) — so the scheme carries to Gen2 and our `tools/usb_stick/` generator should produce an
accepted Gen2 stick. Fixed (2026-10-20, us): `saltscan.find_salt()` now auto-resolves on Gen2 (drops full-WIDTH, non-padded false
candidates), verified to return the same salt on Gen2/Gen1/Force; the generator can build a Gen2 stick with no manual override.
Still no real Gen2 device run. See NOTES.md 2026-10-20.

## One plugin, two zips
- `release.py` names the zip from the `.so`'s ELF machine: `<Name>-<ver>-mpc-armv7.zip` (Gen1, unchanged) or
  `<Name>-<ver>-mpc-aarch64.zip` (Gen2). Run it once per build. Both go on the **same** GitHub release / tag.
- Same `id`, `uid`, `version` and `param_compat` in both: saved projects move between generations. The manifest's `arch` says which.
- An aarch64 manifest has `os_compat: ["3.x"]` (Gen2 only ships MPC OS 3.x). The "3.x only" glibc warning is for armv7 only, and the glibc ceiling is 2.39 instead of 2.36.
- Skin, presets and `plugin_list.awk` are architecture-independent; only the `.so` (and any bundled binaries) differ.

## Catalog
- **One registry entry per plugin.** Do not add a second entry for Gen2 (uid and `file=` would collide).
- `catalog_build.py` looks for a sibling asset by swapping `armv7` for `aarch64` in `asset_pattern`. If present it must pass the same
  `catalog_check.py` run, be arch `aarch64`, and match the armv7 zip's version and uid. Each version then carries
  `assets: {armv7: {url, sha256, size}, aarch64: {...}}` and `gen2: true`. The top-level `url`/`sha256` stay the armv7 asset, so
  schema-1 readers keep working. A bad aarch64 asset is reported in `problems.json` and never hides the Gen1 release.
- **A plugin with only a Gen2 build** (its engine has no 32-bit ARM backend, e.g. a DSP56300 JIT emulator) uses `"asset_pattern": "*-mpc-aarch64.zip"`
  (no `armv7` in it). `catalog_build.py` then lists the one zip as the version's Gen2 asset: `assets: {aarch64: {...}}`, `gen2: true`,
  `gen2_only: true`, and `url`/`sha256`/`size` stay that zip so older readers keep parsing (their installer refuses a wrong-arch zip). The zip must be
  arch `aarch64` (checked). `catalog.tsv` has `-` in the size/sha256/url columns, so `mpc-store.sh` on a Gen1 device or a Force says "Gen2 only" and installs
  nothing (`list` shows `[Gen2 only]`), the desktop installer's `ForArch` refuses it the same way, and the site shows a "Gen2 only" tag and a single
  "Download (Gen2)" button. Offline tests only (`tools/test_catalog.py`, `tools/desktop/gen2_test.go`); the site template change is not run in a browser.
- **`mpc-store.sh install <id>...` with more than one id: an id with no build for this device's architecture is skipped, not fatal**
  (2026-10-25 fix -- found on a real Gen2 device: `install plugin-manager` used to abort the whole batch immediately with no build
  for Gen2, so the USB stick's default install, `plugin-manager`, silently prevented any other configured catalog plugin from
  being attempted, even though the stick's SSH setup and addin reapply run separately before it and were never affected). The
  summary line says how many were skipped and why (`"Installed 2 of 3 (1 skipped: no build for this device)."`), and the run is
  not reported as a failure (exit 0) when every requested id was skipped for this reason -- only a real error (download, checksum,
  unzip, or the plugin's own installer failing) still returns non-zero.

## Installer
- `install.sh` reads `arch` from the package's `mpc-plugin.json` (absent = armv7) and refuses on a mismatch with `uname -m`, naming the
  zip to download instead. This guards a hand-downloaded wrong zip.
- `install.sh`/`sync.sh` also use `arch` to pick which `MPC.settings` plugin-list key to register into: `pluginList-arm` for armv7,
  `pluginList-arm-64bit` for aarch64 (`plugin_list.awk -v listkey=...`). The aarch64 key is from unverified third-party tester feedback
  (2026-10-10, not reproduced by us; see `docs/NOTES.md`) — **confirm on real hardware** with the aarch64 pilot port (below) before
  trusting it. The default Synths-folder scan (`sync.sh`) also looks at `/synths/Synths` when present (Gen2's analog of Gen1's internal
  `/sdcard/Synths`; see `docs/NOTES.md` 2026-10-10 for why that mount is still unconfirmed on a live device).
- `mpc-store.sh` (the command the site gives) takes the aarch64 zip on an `aarch64` device and the armv7 one otherwise (`catalog.tsv` columns
  17-19: size64, sha256_64, url64; `-` when there is none). On Gen2 a plugin with no Gen2 build is refused before anything is downloaded,
  and `list` marks it `[no Gen2 build]`. `MPC_STORE_ARCH` overrides `uname -m` (tests). Addins can have an aarch64 build like any
  plugin (2026-10-23: catalog_check.py, release_addin.py and the shared addin installer no longer refuse one); none has shipped one yet.
  Because the extra columns follow `max_glibc`, an old `mpc-store.sh` reading the new `catalog.tsv` would take them as part of `max_glibc`;
  the script is fetched from the site on every run, so it and the table always match.
- The desktop installer app (`tools/desktop`) reads `versions[].assets.aarch64` from `catalog.json`, installs the zip that fits the connected
  device (`CatPlugin.ForArch`), accepts aarch64 devices, refuses a hand-added zip for the other generation (naming the zip to get), shows a
  Gen2 tag and a "no Gen2 build" note on a Gen2 device. Device-confirmed on a real Live III (2026-10-22/23): an install hang traced to
  `Run()` having no deadline/keepalive against that device's weaker Wi-Fi (fixed, #509, released as desktop-v0.6.1), then a full install
  of five plugins to `/nvme/Synths` through the app itself.

## Site
`index.html`: a **Gen2 build** tag on a version with an aarch64 asset (always that text and a neutral colour since 2026-10-12; whether it
was tested on a Gen2 unit is in its hover text, the card's Gen2 row and the Verified Gen2 badge), a **Device** filter (has a Gen2 build / Gen1 only), and two download buttons, "Download (Gen1)" and
"Download (Gen2)". A passing aarch64 build is not "tested": that needs the device string. Use e.g. `"device": "MPC Live III (Gen2)"` in `tested.json`.
The same rule splits the Verified badge (2026-10-12, offline): the newest stable release gets "Verified Gen2" from such an entry (only when it
has an aarch64 build) and "Verified Gen1" from any other entry, each its own badge and Tier filter option (`verified_on` in `catalog.json`).
Checked in Chromium (Playwright) against a fixture catalog with two Gen2 versions.

## Developers
Done (offline, 2026-10-09; checked with the `poc/inputprobe` port: armv7 and aarch64 builds, both zips through `release.py` and
`catalog_check.py --catalog`, `test_port.sh ... aarch64` PASSED in an arm64 container on an x86 host):
- `vst.json` `targets: ["armv7", "aarch64"]` (default `["armv7"]`) and optional `cflags_aarch64`. `tools/build_port.sh vst.json [armv7|aarch64|all]`
  builds armv7 into `build/<so>` as before and aarch64 into `build/aarch64/<so>` with `arm64v8/gcc:12-bookworm`.
- `tools/test_port.sh vst.json aarch64`: the host test in an arm64 container (UBSan only; ASan's shadow memory does not map under QEMU).
  The wrapper's VST2 structs use `intptr_t` for the pointer-sized fields, and the x86_64 host test already ran them in a 64-bit layout.
- Also fixed the Docker fallback of `test_port.sh` (a syntax error in its `bash -c`, and a duplicate mount for ports inside this repo).

- The reusable `vst-release.yml` sets up arm64 QEMU, and when the build left `build/aarch64/<so>` it packages that too (input `extra_aarch64` for its own `--extra` engine bundle, falling back to `extra`; no `--bench`: the
  CPU result is Gen1's), runs `catalog_check.py` on every zip and attaches all of them to the one draft release. A port that only builds armv7
  behaves as before. Not yet run in Actions (the YAML parses and the argument rewrite was tried in bash); a dry run on a real port is the check.

Still to do:
1. A port template repo with both builds in its `build.sh`.
2. ~~`bench.c` for aarch64~~: done, `tools/bench.sh` picks the build from the device (docs/BENCH.md).
3. Pilot with one real port. The glibc ceiling for aarch64 is 2.39 (MPC OS 3.x; Gen2 never runs 2.x); checked 2026-10-09 (offline, from `MPC-3.9.1-Gen2-update.img`'s main rootfs): `/usr/lib/libc.so.6` is aarch64 GNU libc 2.39, so the ceiling matches. libstdc++ was not inspected.
