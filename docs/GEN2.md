# Gen2 (aarch64) support: design and status

Gen2 MPC devices (MPC Live III and kin, RK3588) run a 64-bit userland: `/usr/bin/MPC` is ELF64 aarch64 with
`/usr/lib/ld-linux-aarch64.so.1` and there are no 32-bit libraries, so Gen1's armv7 `.so` files cannot load
(analysed 2026-10-06 from the 3.9.1 Gen2 update image, offline; see `docs/FIRMWARE_BUILDER.md`). A plugin needs a second, aarch64 build.

**Status (2026-10-11): two Gen2 device confirmations, pilot phase done.** Crate Digger 1.1.9 and Profit-08 0.1.1's aarch64 builds
both installed on a real MPC Live III (MPC OS 5.0.18), registered, showed up in MPC's plugin browser and ran (Crate Digger's skin
and open/close were checked in detail; Profit-08 was reported "working well" by the same tester, not yet broken down feature by
feature on our side). Both plugins' `tested.json` carry the device. This settles the open questions from the first pilot:
- **`pluginList-arm-64bit` is confirmed correct** for registering an aarch64 package (the earlier third-party tester report was
  right; `plugin_list.awk -v listkey=...` and `install.sh`/`sync.sh`'s arch-based choice need no further change).
- Install target: on this device `-t` had to point at a removable Synths folder (`/media/<label>/Synths`); `/sdcard` wasn't mounted
  and `/synths/Synths` was mounted read-only (see NOTES.md 2026-10-10). No Gen2-specific install default was needed.
- `vst.json` `targets: ["armv7", "aarch64"]` + `tools/build_port.sh ... all` is now proven end to end on a second, ordinary port
  (Profit-08: no custom build script, just the generic path) — any future port can follow the same checklist (docs/PORTING.md).

Not yet working: Crate Digger's Discogs search returned an error on-device (not yet diagnosed; could be network, DNS, TLS/cert, or
something arch-specific in the bundled yt-dlp/Python). Not claiming full functional parity for it until that's resolved. There is
still no SSH/root route on Gen2 *that this project provides or documents* — the Gen2 tester reached root via unofficial third-party
boot methods unrelated to this repo, so Gen2 plugin support remains usable only by people who already have root some other way.

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
- An aarch64-only plugin is not supported yet (the armv7 asset is still the required one).

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
  and `list` marks it `[no Gen2 build]`. `MPC_STORE_ARCH` overrides `uname -m` (tests). Addins are armv7 only, so they are refused on Gen2.
  Because the extra columns follow `max_glibc`, an old `mpc-store.sh` reading the new `catalog.tsv` would take them as part of `max_glibc`;
  the script is fetched from the site on every run, so it and the table always match.
- The desktop installer app (`tools/desktop`) reads `versions[].assets.aarch64` from `catalog.json`, installs the zip that fits the connected
  device (`CatPlugin.ForArch`), accepts aarch64 devices, refuses a hand-added zip for the other generation (naming the zip to get), shows a
  Gen2 tag and a "no Gen2 build" note on a Gen2 device. Tested against a fake SSH device only; no real Gen2.

## Site
`index.html`: a **Gen2** tag on a version with an aarch64 asset ("Gen2 build", or "Gen2 · tested" when a `tested.json` entry's `device`
contains "Gen2"), a **Device** filter (has a Gen2 build / Gen1 and Force only), and two download buttons, "Download (Gen1 / Force)" and
"Download (Gen2)". A passing aarch64 build is not "tested": that needs the device string. Use e.g. `"device": "MPC Live III (Gen2)"` in `tested.json`.
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
2. `bench.c` for aarch64, once a Gen2 device is reachable.
3. Pilot with one real port. The glibc ceiling for aarch64 is 2.39 (MPC OS 3.x; Gen2 never runs 2.x); checked 2026-10-09 (offline, from `MPC-3.9.1-Gen2-update.img`'s main rootfs): `/usr/lib/libc.so.6` is aarch64 GNU libc 2.39, so the ceiling matches. libstdc++ was not inspected.
