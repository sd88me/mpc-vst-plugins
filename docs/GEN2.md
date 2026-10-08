# Gen2 (aarch64) support: design and status

Gen2 MPC devices (MPC Live III and kin, RK3588) run a 64-bit userland: `/usr/bin/MPC` is ELF64 aarch64 with
`/usr/lib/ld-linux-aarch64.so.1` and there are no 32-bit libraries, so Gen1's armv7 `.so` files cannot load
(analysed 2026-10-06 from the 3.9.1 Gen2 update image, offline; see `docs/FIRMWARE_BUILDER.md`). A plugin needs a second, aarch64 build.

**Status (2026-10-09, offline only):** the packaging, validation and catalog plumbing below exists and is unit-tested. Nothing has
been built for or run on a Gen2 device: there is no known SSH/root route on Gen2 yet. Nothing may be called "Gen2 verified"
until a plugin has loaded on real hardware (`tested.json` carries the device).

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
- Still to do: the installer app / `mpc-store.sh` picks the asset for the device's `uname -m` automatically.

## Developers
Done (offline, 2026-10-09; checked with the `poc/inputprobe` port: armv7 and aarch64 builds, both zips through `release.py` and
`catalog_check.py --catalog`, `test_port.sh ... aarch64` PASSED in an arm64 container on an x86 host):
- `vst.json` `targets: ["armv7", "aarch64"]` (default `["armv7"]`) and optional `cflags_aarch64`. `tools/build_port.sh vst.json [armv7|aarch64|all]`
  builds armv7 into `build/<so>` as before and aarch64 into `build/aarch64/<so>` with `arm64v8/gcc:12-bookworm`.
- `tools/test_port.sh vst.json aarch64`: the host test in an arm64 container (UBSan only; ASan's shadow memory does not map under QEMU).
  The wrapper's VST2 structs use `intptr_t` for the pointer-sized fields, and the x86_64 host test already ran them in a 64-bit layout.
- Also fixed the Docker fallback of `test_port.sh` (a syntax error in its `bash -c`, and a duplicate mount for ports inside this repo).

- The reusable `vst-release.yml` sets up arm64 QEMU, and when the build left `build/aarch64/<so>` it packages that too (no `--bench`: the
  CPU result is Gen1's), runs `catalog_check.py` on every zip and attaches all of them to the one draft release. A port that only builds armv7
  behaves as before. Not yet run in Actions (the YAML parses and the argument rewrite was tried in bash); a dry run on a real port is the check.

Still to do:
1. A port template repo with both builds in its `build.sh`.
2. `bench.c` for aarch64, once a Gen2 device is reachable.
3. Site: Gen2 badge and filter from `gen2`; installer app asset choice; `tested.json` device field to tell "builds" from "verified on Gen2".
4. Pilot with one real port. The glibc ceiling for aarch64 is 2.39 (MPC OS 3.x; Gen2 never runs 2.x); checked 2026-10-09 (offline, from `MPC-3.9.1-Gen2-update.img`'s main rootfs): `/usr/lib/libc.so.6` is aarch64 GNU libc 2.39, so the ceiling matches. libstdc++ was not inspected.
