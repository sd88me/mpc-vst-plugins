# Releasing a plugin

A release is **one zip** people can share around: `<Name>-<version>-mpc-armv7.zip`. It unpacks to a folder with
the plugin as one folder (`portable/<skin>/`: the `.so`, the skin, its data and a `plugin-meta.xml`), `install.sh` /
`uninstall.sh` and a generated `INSTALL.md` (scripted and manual steps, requirements, CPU result, checksums). The folder is
the only layout: it can be dropped into any `Synths` folder by other installers too (`docs/CATALOG_SPEC.md`, "Plugin folder").

## Checklist
1. **Build** with the port's `build.sh` (armhf, `arm32v7/gcc:11-bullseye`; highest GLIBC symbol ≤ 2.32).
2. **Host test** (x86, ASan): `tools/test_port.sh <port>/vst.json` (must print PASSED), or the port's own test for a
   hand-written wrapper. It must be clean.
3. **Skin preview**: `tools/studio.py preview "<skin>/Plugin Skins" -o page_%d.png`, and look at every page.
4. **CPU**: `tools/bench.sh build/x.so <ip> -j | tee build/bench.txt`. It must PASS, or WARN with a note
   (docs/BENCH.md).
5. **Device smoke test**: install with the zip's own `install.sh` (step 6 first). Load the plugin on a track, play
   it, turn every page and Q-Link, save and reload a project, then `uninstall.sh`.
6. **Package**:
   ```
   tools/release.py --so build/x.so --skin "build/skin/<vendor> - VST - <Name>" \
       --entry build/pluginlist-entry.xml --version 1.2.0 --bench build/bench.txt \
       --about "One line about the plugin." [--extra engine:engine] [--user-data roms] -o dist
   ```
   Add `--repo owner/name --license <SPDX> [--id my-plugin]` to make it listable in the catalog
   (`docs/CATALOG_SPEC.md`), then check it: `tools/catalog_check.py dist/<zip> --catalog`.
   `--extra SRC:DEST` ships extra runtime files in the plugin folder, next to the `.so` (an engine bundle, presets; `DEST` is
   relative to the plugin folder, a leading `vst/` from older scripts is still accepted). `--user-data <folder>` marks a folder
   where the user adds files (ROMs, kits, banks); the installer keeps it.
7. **Publish**: tag `<port>-vX.Y.Z` in the port's repo and attach the zip:
   `gh release create maze-voice-vst-v1.2.0 dist/Maze-Voice-1.2.0-mpc-armv7.zip --notes-file ...`
   Paste the zip's INSTALL.md "Requirements" and "Install" sections into the notes.

**Catalog rule:** always pass `--repo` and `--license` (CI: `plugin_id`, `license`, `requires`) and run the `--catalog` check; see PORTING.md section 5.

## Releasing from CI
`.github/workflows/vst-release.yml` is a reusable workflow that does steps 1, 2, 3 (as images) and 6 in GitHub Actions
and attaches the zip to a **draft** release in the port's repo. Steps 4 and 5 stay on a device, and they are what
you do to the draft's zip before publishing it, so the zip you tested is the zip people get.

A port calls it from its own repo with a `workflow_dispatch` workflow that takes the version. Pin this repo to one
commit in both places:
```yaml
jobs:
  vst:
    uses: sd88me/mpc-vst-plugins/.github/workflows/vst-release.yml@<sha>
    permissions: { contents: write }
    with:
      tag: my-port-vst-v${{ inputs.version }}
      version: ${{ inputs.version }}
      tools_ref: <sha>                 # the same commit
      vst_dir: vst                     # the build writes vst/build/<so>, skin/, pluginlist-entry.xml
      build: vst/build.sh              # run from the port repo root; MPC_VST is set
      host_test: '"$MPC_VST/tools/test_port.sh" vst/vst.json'   # optional
      about: One line about the plugin.
      dry_run: ${{ inputs.dry_run }}   # optional: zip and previews as run artifacts only
```
Optional inputs: `extra` (release.py `--extra` specs), `user_data` (release.py `--user-data` folders, space-separated: the user's ROMs/banks, kept across upgrades and moved in from an old install) and `zig` (a zig version to install). The run's artifacts hold the zip and one PNG per skin page, and its summary lists what is left
to do. CPU (step 4) comes from `<vst_dir>/bench.txt` when the port commits the `-j` output of `tools/bench.sh`;
without it INSTALL.md has no CPU section. Re-running with the same version replaces the draft's zip. It refuses a
version that is already published. Publishing the draft creates the tag.

## Versioning
- `X.Y.Z` in the zip name and INSTALL.md. Bump Z for fixes, Y for new parameters or pages, X when parameter
  indices change. Changing the indices breaks saved projects, because MPC stores values by index.
- Keep the plugin `uid` and `.so` name fixed across versions: the installer replaces the entry with the same
  `uid` or `file=`, and projects find the plugin by uid.
- Release data the user adds to (ROMs, kits, banks) with `--user-data <folder>`; `--extra SRC:DEST` ships data next to the
  `.so` (`DEST` is relative to the plugin folder).

## What the installer does
Run on the device as root (`sh install.sh [-y] [-n] [-t <synths-dir>]`):
1. Checks root, armv7, that `MPC.settings` exists and `SHA256SUMS`, and asks for confirmation.
2. Stops MPC (`systemctl stop acvs`, or `inmusic-mpc` where that is the service name) and waits for it to exit. A trap restarts MPC on any error.
   `-n` (also on `uninstall.sh`) defers this to the caller: the script neither stops nor starts MPC and refuses to run while MPC is
   running. A batch installer stops MPC once, runs every plugin's `install.sh -y -n`, then starts MPC once. The caller must
   start MPC again even if one install fails.
3. Copies `portable/<skin>/` next to its target (`/sdcard/Synths`, or `-t <folder>`), carries over the files the user
   added (the manifest's `user_data`, see `--user-data`), and swaps the new folder in.
   Then it puts back executable bits and symlinks from the package's `MODES` file (written by `release.py`): a zip unpacked
   on Windows, or copied file by file, loses both, and an engine that bundles binaries (yt-dlp, ffmpeg, a private Python) then fails.
4. Backs up `MPC.settings` to `MPC.settings.bak-<so>-<date>`. `plugin_list.awk` (BusyBox awk) drops any entry with
   the same `file=` or `uid` (an older install at another path) and inserts the folder's `plugin-meta.xml`, with
   `%payload-path%` replaced by the Synths folder, into `pluginList-arm`, creating the list if needed. The result is
   checked (exactly one entry, valid XML when python3 exists) before it replaces the original.
5. If the plugin was installed the old way (`.so` in `/sdcard/vst`): removes that `.so` and the data the package ships
   there, and moves the user's own files (`user_data`) from `/sdcard/vst/<path>` into the plugin folder. Done only after
   the settings edit succeeded; nothing else in `/sdcard/vst` is touched.
6. Starts MPC.

Why MPC is stopped for the edit: it holds its settings in memory while it runs and saves them itself, so an edit made
underneath it can be lost (then the plugin is missing after the next restart). Tools that rebuild the whole list from the
plugin folders in the `Synths` folders keep a plugin installed this way, because each one is such a folder with its own
`plugin-meta.xml`; a plugin registered any other way (by hand, or the old `/sdcard/vst` layout) is dropped by such a rebuild.

The settings edit was tested 2026-09-24 against a copy of a real Force `MPC.settings`: replacing an entry, running
twice (identical output), removing, a missing `pluginList-arm`, and a self-closing `<KNOWNPLUGINS/>`. A full
scripted install on a device (which restarts MPC) is step 5 of the checklist.

Audience: root access is needed to edit `MPC.settings`, so releases are for modded units. Say so up front.

## Keeping the plugin list in step with the folders: `tools/release/sync.sh`

`sh sync.sh [-y] [-n] [--dry-run] [-t <synths-dir>]...` (BusyBox `sh`, needs `plugin_list.awk` next to it) makes MPC.settings' plugin list
follow the plugin folders in `/sdcard/Synths` and every `/media/*/Synths` (or the `-t` folders): it registers a folder that has no entry,
replaces an entry with the same uid whose `.so` is gone, removes an entry that points into a Synths folder whose `.so` is gone, and
leaves every other entry alone. Nothing to do means no restart; otherwise it backs up `MPC.settings`, checks the result and stops and
starts MPC once (`-n`: the caller does, as for `install.sh -n`). `--dry-run` prints the plan only. It uses the same folder rule as
MockbaMod's `vstscanner.sh` (`/media/*/Synths/*/plugin-meta.xml`) but not its whole-list rebuild, so entries from other tools survive.
It is not shipped in the release zips yet; the device-side store script (docs/CATALOG.md, Phase 4) will call it after a batch of
`install.sh -y -n`. Only the first `<PLUGIN>` in a `plugin-meta.xml` is read (the packages `release.py` builds have one).
