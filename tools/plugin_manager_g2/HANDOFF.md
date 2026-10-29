# Handoff: Open MPC Plugin Manager G2 (2026-10-29)

**State:** release `plugin-manager-g2-v0.2.1` is published with a 32-bit (Gen1) and a 64-bit (Gen2) zip. The catalog lists it as **Open MPC Plugin Manager G2**,
Verified on Gen1 and Gen2 (device tests on an MPC Live III, MPC OS 3.10.0.49, and a Force, MPC OS 3.9.1.2).

## Where things live
- Code and docs: `tools/plugin_manager_g2/`. `README.md`: features, how to use, credits (poloq first). `DESIGN.md`: the design and the evidence behind it.
- Identity: release tag `plugin-manager-g2-v<version>`; assets `Plugin-Manager-G2-<version>-mpc-armv7.zip` and `-mpc-aarch64.zip`; catalog id
  `plugin-manager-g2` (registry entry `catalog/plugins/plugin-manager-g2.json`, `asset_pattern Plugin-Manager-G2-*-mpc-armv7.zip`, the aarch64 sibling is found by
  name); plugin name "Plugin Manager G2", manufacturer OpenMPC, VST uid `OMG2`, folder `OpenMPC - VST - Plugin Manager G2`.
- `tested.json` (repo root): one record per version and device. Each new release resets Verified until it is tested again.

## What it does (device-tested)
Browse the catalog and install, update and remove plugins on the MPC; checks every package first and puts the plugin folder and `MPC.settings` back if an install
fails; local zips; REGISTER for folders MPC does not list; light and dark theme; install history; pruning to the newest 10 `MPC.settings.bak-*`; the install
location confirmed on the restart prompt is remembered (device-tested on a Force); the manager empties MPC's skin image cache on every apply and warns at 85%
(device-tested on a Live III); one big skin with 162 thumbnails for both generations.

## How to release (about 15 minutes of CI)
1. Run `plugin-manager-g2.yml` (version, `dry_run` false): a **draft** with both zips. Start with `dry_run` true if the workflow changed.
2. Write the note as the release body. **Publishing posts to the project's Discord automatically** (`discord-release.yml`: the first 1800 characters of the body,
   and a role ping if the repo variable is set).
3. Publish, then dispatch `catalog.yml`.
4. After checking the zips on devices, add `tested.json` records in a PR. (That file is outside the catalog workflow's path filter, so such a PR has no checks.)

## Open items
1. Issue #610 / branch `pm-g2-thumbs-20261028`: the weekly thumbnail check (`plugin-manager-g2-thumbs.yml`, `vst/thumbs_check.sh`) found a new catalog screenshot
   (the manager's own). Merge it with the next release; thumbnails only reach devices in a release. Actions may not create PRs in this repo, so the check opens
   an issue with a compare link.
2. A MPC One Gen2 user's `/tmp/openmpc-pm/device.txt` and `mount` output: is their SD card `noexec`? (Their layout is covered by an offline test only.)
3. A catalog-served thumbnail pack with generic numbered slots, so new plugins get thumbnails without a release (DESIGN 6c; about a day; not built).
4. A fixed SATA SSD still counts as non-internal storage (a `/dev/sd...` drive); not urgent now that the chosen location is remembered.

## Things learned (see `docs/NOTES.md`, dated 2026-10-28)
- One tap can reach a plugin as two `set` events; the same button twice within 250 ms counts once.
- MPC's skin image cache (`/var/volatile/tmp/filmstrips`) is a RAM disk (3.9 GB on a Live III, 1 GB on a Force) that only a reboot empties; full, it makes parts of a
  skin draw black. A Force showed no cache growth with the manager open.
- The MPC OS version cannot be read reliably on a device; the manager infers 2.x or 3.x from glibc (2.39 reads as 3.x).

## Tests
`tools/plugin_manager_g2/tests/run.sh` (about 9 minutes, needs Docker and network); `ONLY=<section>` runs one section (devices, addins, links, pick, theme, safety, arch).
