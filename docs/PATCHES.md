# Design: an "Advanced" patches step in the installer app (built up to a read-only list)

Status 2026-10-04: the design below is the plan; steps 1 and 2 of "Order of work" are built and merged (#154, #156), so the app has a read-only step 7 (in the desktop app from v0.3.5). **Apply and Undo from the app: built 2026-10-10, offline only (PR draft), not yet run on a device.** `POST /api/patch/run` `{id, action: install|uninstall, confirm}` (typed `APPLY` / `UNDO`, not the `PATCH` / `RESTORE` the scripts ask for on a terminal: the app passes `--confirmed`), default settings only (no per-patch options yet), result checked by a second `status`. Tests: `patches_run_test.go`, `ui_test/ui_patches.py`. Verified facts go in `NOTES.md`; this file says what we build and what is still unknown.

Web catalog (2026-10-06): `tools/catalog_site.py` also renders `catalog/patches.json` as the **Device patches** tab of the catalog page, the same cards as its own page (`patches.html`, 2026-10-09: out of the top menu, linked from the tab) and one guide page per patch (`patch-<id>.html`, from the patch's `docs` README, out of the menu). The installer app and the site read the same manifest, so a patch added there appears in both; `tools/test_patches.py` checks each patch gets its page.

## Why
Some community work is not a plugin: it changes the device itself. Today that is `tools/mpc_patch` (16-pad drum layout, patches Akai's
`/usr/bin/MPC`, checked on MPC OS 3.9.1.2), the drive exec patch (makes one folder on a `noexec` drive executable so plugins can load from it;
NOTES 2026-10-05), and the button remap (`tools/mpc_patch/hwremap`, an `LD_PRELOAD` shim vendored from akai_standalone_remap; the shim was tried
by its author, the installer here is offline only). People run these by hand over SSH. The installer app
already has the SSH session, the backups and the "stop MPC once" logic, so it can run them with the safety rails the scripts already have.

## What it must not become
A plugin install is additive (files plus one settings entry). A patch rewrites Akai's program or the mounts and survives reboots. So:
- its own tab, collapsed behind a warning, off the plugin list and out of the batch install; nothing runs at connect time except `status`;
- never applied by default, never as part of an update, never without the user's click and a typed confirmation;
- one patch at a time, with what it changes, what it backs up and how to undo it shown first.

## Shape
1. **Manifest** `catalog/patches.json` (checked by a script like `catalog_check.py`; nothing hand-edited on the site). Per patch: `id`, `title`,
   `summary`, `author`, `license`, `script` (URL in this repo or the author's, pinned to a commit), `sha256`, `supports` (exact firmware
   checksum or version list), `modifies` (`/usr/bin/MPC`, `fstab`, ...), `reversible`, `restarts_mpc`, `docs`.
2. **The script stays the unit.** The app downloads it, checks the sha256, copies it to the device's `/tmp` and runs `status`, `install`,
   `uninstall`. The patch logic is not reimplemented in Go, so the manual route and the app route stay the same code.
3. **Contract each script must meet** (a `patch_check.py` would test it):
   - `status` changes nothing and prints `key=value` lines (`state=stock|patched|old-patch|unsupported`, `checksum=`, `backup=`) next to the human text;
   - `install --yes-i-understand` (name open) skips the typed prompt, because the app shows the same warning and takes the typed word itself;
     today `mpc-drum-pad-patch.sh` reads the word from `/dev/tty` and falls back to stdin, so piping `PATCH` would already work, but an explicit flag is clearer;
   - exact-match gate on the firmware (checksum), refusal otherwise, full backup before the first write, checked result, automatic restore on failure;
   - `uninstall` that works even if the app is gone;
   - exit status 0 only when the device ended in the state asked for.
4. **App flow:** Advanced tab, warning, list from the manifest with the device's `status` per patch (supported / applied / unsupported firmware),
   a detail view (what it does, what it changes, backup location), Apply and Undo behind a typed confirmation, the script's output streamed like an install.
   MPC is stopped and started by the script or by the app, never twice.
5. **Staged rollout:** (a) docs only: the tab lists patches with copy-paste commands, no Run; (b) read-only `status` per patch; (c) Apply and Undo.
   Stop at (b) until a patch has been applied from the app on a real device.

## Spec

### Manifest `catalog/patches.json`
```json
{
  "schema": 1,
  "patches": [
    {
      "id": "drum-pad-layout",
      "title": "16-pad drum layout for selected plugins",
      "summary": "Machinedrum Module, 6W6, 8W8, CW-78, 9W9 and TR-MPC get MPC's drum layout with all 16 pads lit.",
      "author": "sd88me",
      "license": "MIT",
      "docs": "tools/mpc_patch/README.md",
      "script": {"url": "https://raw.githubusercontent.com/sd88me/mpc-vst-plugins/<commit>/tools/mpc_patch/mpc-drum-pad-patch.sh",
                 "sha256": "4b9a8b08ef00e17639e7976d243431bc216864939981a48d6dc5719f4a1425cb"},
      "supports": {"mpc_md5": ["592eebc8e1ce0797dc8c98e7002143b8"], "os": "MPC OS 3.9.1.2", "arch": "armv7l"},
      "modifies": ["/usr/bin/MPC"],
      "backup": "/sdcard/MPC-backup",
      "restarts_mpc": true,
      "reversible": true
    }
  ]
}
```
- `url` is pinned to a commit (never a branch), `https` only, and `sha256` is re-checked after download, as the catalog zips are. The sha256 above is the
  current script; it changes with every rebuild, so the manifest entry is updated in the same commit that rebuilds the script.
- `supports` is advisory text for the page; the script's own checksum gate is what actually refuses.
- `modifies`, `backup`, `restarts_mpc`, `reversible` are shown before anything runs and must be true statements (a test per patch checks `uninstall`).
- A `tools/patch_check.py` validates the file (schema, https, 40-hex commit in the URL, sha256 matches the downloaded or local script, every field present) and
  runs in CI next to `catalog_check.py`.

### Script contract (each patch script)
| Command | Must |
|---|---|
| `status` | change nothing; print the human text and, last, one line `STATE state=<stock\|patched\|old-patch\|unsupported> supported=<0\|1> backup=<0\|1>` |
| `status` (v5) | also end the `STATE` line with `checksum=<md5>` of the device's MPC program, so the app can say why a build is unsupported |
| `uninstall` of an unknown build (v5) | only from a saved full backup whose md5 is the stock program's; typed `RESTORE` or `--confirmed`; verify the result; otherwise touch nothing |
| `install --confirmed` | do what `install` does but skip the typed prompt (the app shows the same warnings and takes the typed word itself); refuse unsupported firmware; back up first; verify; restore on failure |
| `install` | unchanged: show warnings, ask for the typed word |
| `uninstall` | work without the app; exit non-zero if the device did not return to stock |
| exit status | 0 only if the device ended in the requested state |
`mpc-drum-pad-patch.sh` needs two small edits (the `STATE` line in `cmd_status`, and `--confirmed` in `cmd_install`); both go through `script.template.sh` and `build_script.py`,
then `test_script.sh` gets a case each (status line for stock, patched, old-patch and other firmware; `--confirmed` installs without a prompt and still refuses other firmware).

### App (tools/desktop)
- `patches.go`: fetch and verify the manifest (same https/hash/size rules as `catalog.go`), `PatchStatus(dev, p)` (copy script to the device's `/tmp`, run `status`, parse the `STATE` line,
  remove it), `RunPatch(dev, p, action, j)` (copy, run `install --confirmed` or `uninstall`, stream output into a `Job`, always remove the copy). The plan is rebuilt on the server from the
  manifest and the device; the page only sends `{id, action}` and the typed word.
- `server.go`: `GET /api/patches` (manifest plus the status per patch, read-only), `POST /api/patch` (`{id, action: install|uninstall, typed: "PATCH"}`), reusing `/api/job` for the output. Same guard as the other endpoints (token, Host, Origin).
  The typed word is checked on the server (it must equal the word the manifest or script names), not only in the page.
- `web/index.html`: step 7, "Advanced: device patches", collapsed with a red warning, after "Clean up old backups". The page is one stepped page, not tabs, so a collapsed final step matches it; a real tab bar can come later if there are more advanced tools than patches.
  Per patch: name, summary, state badge (not applied / applied / unsupported firmware), "What it changes" (`modifies`, `backup`, `restarts_mpc`), Apply and Undo buttons that open a confirm box with the typed word.
- MPC stop/start stays inside the script (it already does both); the app does not stop MPC for a patch, so there is never a double restart or a start while the patch is writing.
- Never run a patch as part of install, update, register or the batch; never remember a patch as "wanted".

### Tests (before stage (c))
Using the existing fake device (`fakedev_test.go`, shims for `systemctl` etc.): a fake patch script that records its arguments and honours `status`/`install --confirmed`/`uninstall`;
checks that (1) a wrong sha256 is refused before anything is copied, (2) `status` is the only call made on connect, (3) `install` without the typed word is refused by the server, (4) the copy in `/tmp` is removed after success and after failure,
(5) a non-zero exit is reported as failed and never as applied, (6) unsupported firmware offers no Apply. Mutation-check each (remove the check, see the test fail). Then run the real script under BusyBox against copies of the binary (`test_script.sh`) and once on a real Force with a stock `MPC`.

### Order of work
1. **Done (2026-10-03; host tests, then script v5 run on a Force 2026-10-04, see below):** `STATE` line and `--confirmed` in `mpc-drum-pad-patch.sh` (script v3), `catalog/patches.json`, `tools/patch_check.py`, `tools/test_patches.py` (11 tests, mutation-checked, CI in `.github/workflows/patches.yml`). The script contract is tested on a synthetic stand-in for the MPC binary (checksums rewritten), not on Akai's file or a device; run `tools/mpc_patch/test_script.sh` with the real fixtures and a Force before relying on it. The repo is MIT licensed (`LICENSE`, added 2026-10-03), so the drum-pad entry says `MIT`.
2. **Done (2026-10-03; host tests, then seen on a Force 2026-10-04, see below):** `patches.go`, `GET /api/patches` and step 7 in read-only mode (stage (b)): the page asks the device only when step 7 is opened or "Check the device" is pressed (not at connect), the script is downloaded and checked against the manifest's sha256 before it reaches the device, only `status` runs, the copy on the device is removed, and while a job runs the device is not asked. Tests: `patches_test.go` (Go, fake device, six mutations checked) and `ui_test/ui_patches.py` (Chromium, API stubbed). Finding on the way: `status` left a bind mount of `/` behind (`mount --bind / /tmp/mpc-patch-root`); script v4 unmounts it when it opened it (checked with shimmed `mount`/`umount`/`mountpoint`, not on a device).
   **Verified on a Force, 2026-10-04 (NOTES):** the step 7 row on desktop v0.3.5 (state, the device's checksum and the reason, the pointer to the backup), `uninstall` restoring an unknown MPC build from the verified stock backup (typed `RESTORE`), `install` (typed `PATCH`), the `STATE` line with `checksum=`, and the row then reading Applied. One firmware build, one device; the refusals (backup not stock, no backup) are offline tests only.
3. **Built 2026-10-10 (offline):** `POST /api/patch/run`, the confirm box, the fake-device tests (stage (c)). Still to do: a Force test of Apply and Undo; then release.
4. **Built (2026-10-05, offline only):** the drive exec patch from #150 (originally "ForceHD VST Exec") (`tools/mpc_patch/drive_exec`, listed in `catalog/patches.json`) after its script was read in full and adapted to the contract: `partial` state and `reason=` tokens in the `STATE` line, the drive and exec folder chosen (default `Synths`, names with spaces), real-mount tests. **Not yet run on a device by this project**; see NOTES 2026-10-05 and the handoff below.
5. **Built (2026-10-05, offline only):** the button remap (`tools/mpc_patch/hwremap`, `catalog/patches.json` id `button-remap`). The shim is vendored from https://github.com/mmiroshnikov/akai_standalone_remap at `9d2aa57a570b` with one local change (a `combo` rule, `VENDORED.md`), the Live config unchanged, and the Force map is this repo's own set of install-time options (NOTES 2026-10-09). Its author tried that shim on an MPC Live (Hakai, MPC 3.9.1) and a Force (stock 3.9.0). The installer script (Hakai launcher or a systemd drop-in, typed `PATCH` / `REMOVE`, backup, rollback) has been tested on a scratch root only (`tools/test_hwremap_patch.py`); the library's own host tests passed under ASan in Docker. **Run on one Force on 2026-10-10** (install, status, every default rule by hand; NOTES 2026-10-10). Not yet on a device: `uninstall`, the checklist on a real terminal, the Knobs options and the MPC Live map. Script 0.2.0 adds the option checklist and flags. The manifest URL is pinned to `0f5d20f5d8fa98d56d91017ce6dbd4323c943196`, the commit that holds the 0.2.0 script.

## Open questions
- **The drive exec patch is built but untested on a device by us.** Reviewed in full (NOTES 2026-10-05); the layout question is settled by making `Synths` the executable folder (the contributor's `vst` stays available with `--exec-dir vst`). Open: a run of `install`, a reboot, plugins loading from the SSD, `uninstall` (the contributor's own 0.1.3 uninstall was not validated either), on a Force whose SSD name has spaces; behaviour after a firmware update; boot timing against MPC's plugin scan.
- **Firmware drift:** every MPC OS update breaks a binary patch. The manifest's `supports` list is what makes the app refuse instead of guess.
- **Support load:** "my Force will not start" lands on us. The backup and `uninstall` path must be tested on a device before stage (c), and the README must say how to restore by hand.
- **Rules for authors:** nothing of Akai's in a script (only changed bytes and checksums, as in `tools/mpc_patch`); a licence; a `status` and an `uninstall`.
- **Device facts to check:** whether the app can run an interactive script over a plain `exec` session (no tty) on a Force; whether two patches can touch the same file.

## Handoff (2026-10-04): where this stands and how to resume

**State (2026-10-05).** Merged to `main`: the design, the script contract, `catalog/patches.json` + `tools/patch_check.py`, the site publishing `patches.json`, the read-only step 7 in `tools/desktop`, and two listed patches: the drum-pad layout (`tools/mpc_patch/mpc-drum-pad-patch.sh`, script **v6**: v5's contract plus Machinemodule and Lucky Dip in the name table) and the **drive exec patch** (`tools/mpc_patch/drive_exec/drive-exec-patch.sh`, contributed by timomacquis in #150, **listed as untested on a device**, testers wanted). Desktop **v0.3.5** is published (built from `d6b2444`); the drum patch's row, restore and reinstall were tried on a Force with it (NOTES 2026-10-04). Both manifest entries pin their script to a commit and a sha256; any script edit needs a new commit, a re-pin of `url` and `sha256`, and `python3 tools/patch_check.py` (CI fails a stale hash on purpose). A third patch, the **button remap** (`tools/mpc_patch/hwremap/hwremap-patch.sh`, **install and rules tried on one Force, 2026-10-10**), is pinned to `0f5d20f5d8fa98d56d91017ce6dbd4323c943196` (script 0.2.0).

**Not in a release yet (the next desktop release should carry it).** Since the v0.3.5 build (`git log d6b2444..main -- tools/desktop`): patch rows understand the `partial` state ("Installed, not active") and `reason=` tokens, and the "not supported" text no longer assumes an MPC checksum (#176); and other work merged meanwhile: installing and removing addins in the app, connecting to a device whose root has no password, and addin manifest parsing (`docs/ADDINS.md`). The v0.3.5 app lists the drive exec patch but words an unsupported row like the drum patch's. The release procedure (draft by workflow, delete a stale draft first, the owner publishes) is under "Gotchas".

**Open threads.** (1) The drive exec patch's licence: the maintainer is confirming with the contributor; a one-line written confirmation on #150 ("MIT, credit me") is wanted. (2) Testers for the drive exec patch (a Force with a `noexec` SSD, comfortable with SSH): their output goes into NOTES and, when it passes, the "untested" markers come out (manifest summary, `drive_exec/README.md` banner, the install guide). (3) Release notes for Discord were drafted in the session, not posted.

**Next, in this order.**
1. **Apply and Undo from the app** (step 3 of "Order of work"): `POST /api/patch` with `{id, action, typed}`, the server checks the typed word (`PATCH` to apply, `RESTORE` for the unknown-build restore, per the script), runs `install --confirmed` / `uninstall --confirmed` over the existing job/stream machinery, never from install, update, register or the batch. Needs the fake-device tests listed under "Tests", a mutation check of each refusal, and a run on a real Force before release. It changes Akai's program, so agree the wording of the confirm box with the owner first.
2. **Run the drive exec patch on a Force** (built 2026-10-05, offline only; the maintainer's SSD is named with spaces, a good test of the adaptation): `status`, `install --root "/media/<drive>"` (type `PATCH`), reboot, `status` again, install a plugin to that drive and load it, `uninstall` (type `REMOVE`); each step's output goes into NOTES. Ask the contributor (timomacquis, #150) to confirm in writing on the issue that he contributes it under the repository's MIT licence.
3. **Support more firmware builds** only with the exact stock binary in hand; never add an unseen checksum to the known list (the unknown-build restore exists so that nobody has to).

**Known gaps.** The refusals of the restore (backup not stock, no backup) and `install --confirmed` are tested offline only; `tools/mpc_patch/test_script.sh` has not been run with Akai's real MPC (it is not in the repo); other firmware than the one tested is untried.

**Gotchas from this work.**
- Two JSON fields with the same key in one struct (`Patch.Backup`, a folder, and the device's flag) silently shadowed each other: the page printed "a backup goes to true". The flag is `hasBackup` now. A stubbed browser test cannot catch this, so keep a Go test on the real JSON.
- `status` used to leave `mount --bind / /tmp/mpc-patch-root` mounted; v4 unmounts it when it opened it. The app runs `status` only when step 7 is opened or "Check the device" is pressed, never at connect or during a job.
- The patch script's `uninstall` of a known build writes the saved regions and falls back to the full backup; of an unknown build it only ever copies the full backup, and only after its md5 matches the stock program.
- Releases: the desktop workflow (`desktop.yml`, "Run workflow", inputs `version` and `changes` separated by `|`) builds a **draft**; it cannot be re-run for a version whose draft or release still exists, so delete the draft first. The agent sessions cannot publish or delete releases; the owner does that on the Releases page. The site (`catalog.yml`) redeploys by itself on a push to `main` that touches `catalog/**`; a GitHub Pages deploy cannot be checked from the agent session (github.io is blocked), so open `https://sd88me.github.io/mpc-vst-plugins/patches.json` by hand.
- The device is shared with the owner's live setup: every device step in this work was run by the owner, with the project saved, from commands we wrote. Keep it that way.

**To resume.** Read this file, NOTES 2026-10-03 and 2026-10-04, `tools/mpc_patch/README.md`, then run `go test -race ./...` in `tools/desktop`, `python3 tools/test_patches.py`, `python3 tools/patch_check.py` and `python3 tools/desktop/ui_test/ui_patches.py` (needs Playwright and a Chromium) to see the baseline.
