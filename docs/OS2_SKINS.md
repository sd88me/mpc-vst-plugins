# MPC OS 2.x skins: findings, open questions and the experiment plan

Written 2026-10-04 so the work can be picked up later. The verified facts, with dates, are in [NOTES.md](NOTES.md) (section
"2026-10-03: MPC OS 2.15.1"); this file is the plan and the state of play. Stock Akai skin files are analysed offline
only and are never committed (see `CLAUDE.md`).

## Where we are

- Plugins **load** on MPC OS 2.15.1 (an MPC Live, first generation) when built for glibc 2.32 or less, and their Q-Links work.
- Our generated skins **did not draw** there: MPC's frame, an empty body, nothing in the log. Other 2.x users report the same.
- 2.x does read a skin from a plugin folder (a stock skin copied into the plugin's folder showed up), so the problem was
  inside our `TUI.json`.
- Every JSON object in a skin has a `version`. The stock skins on 2.15.1 use versions 1 to 3; ours wrote 3, 4 and 5.
- **Confirmed 2026-10-03:** Dexed's skin rewritten in the 2.15.1 shape draws on the 2.15.1 MPC Live, and the same file draws on a
  Force (3.x) and looks the same on both. Touch behaviour on 2.x was still being checked.

The 2.x shape (what `to_mpc2x` in `tools/shadow_skin.py` writes, opt-in via `SHADOW_SKIN_MPC_OS=2`; merged 2026-10-05):

| Part of `TUI.json` | MPC OS 3.x shape (ours today) | MPC OS 2.15.1 shape |
|---|---|---|
| Tab | `version 3`, page named by `componentName`, plus `initialSize`, `scale` | `version 1`, page inline as `componentDefinition` |
| Page / widget definition | `version 4`, with `repeats` and `hideQLinkBounds` | `version 2`, without them |
| `Knob` data | `version 5`, with `invert`, `dragOrientation` | `version 1` (`knobType`, `filmStrip`, `numFrames`, `handleName`) |
| `Button` data | `version 2`, with `gestureBehaviour` | `version 1` |
| Actions (touch handlers) | `version 2`, with an always-empty `handle remapping` | `version 1` (found 2026-10-04; the first test skin still had version 2) |
| Same on both | `Image`, `Label`, `Focus` data; child `version 2`; `bounds` versions 1 and 2; `Q-Links.json` version 4 | |

What the Force's own stock skins (111 of them, read 2026-10-04) tell us: each component type has one data version per firmware
generation (Knob 5, Slider 4, Meter 3, Button 2); the fields we drop only ever hold one value (`gestureBehaviour` `Instant`,
`dragOrientation` `Vertical`, `invert` `False`, `repeats` 1, `hideQLinkBounds` `False`, tab `initialSize` `0 0 1280 628`,
`scale` 1.0), so dropping them most likely falls back to those defaults. The Force reads the older shapes too, so
**existing 3.x skins keep working on 3.x unchanged**; only 2.x users need the older shape.

## What the 2.15.1 stock skins say (110 skins, read 2026-10-04, compared with the Force's 111)

Per component type, data version on 2.15.1 versus the Force:

| Type | 2.15.1 | Force | Difference |
|---|---|---|---|
| Image, Label, Focus, Decorator, Indicator, Meter | 2 / 1 / 1 / 2 / 1 / 3 | same | none |
| Button | 1 | 2 | Force adds `gestureBehaviour` (always `Instant`) |
| Knob | 1 and 2 | 5 | v2 has `invert`, `textStyle`, `type`; v5 has `dragOrientation`, `polarity` (and `invert`, `textStyle`) |
| Slider | 1 and 3 | 4 | v3 has `direction`, `sliderType`, `thumbImage`, `revealedImage`, `thumbTrackVisible`; Force v4 adds `revealType` |

Structure: tab 1 (inline page) versus 3; page/widget definition 1 and 2 versus 4; action 1 versus 2 (adds an always-empty
`handle remapping`); `bounds` 1 and 2 on both; child entries, `Q-Links.json` (version 4), `backgroundData`, `textStyle`, `font` identical.
The 2.x version 3 count of 45 is 43 `Meter` plus 2 `Slider`. Role by role, the six released skins converted by `to_mpc2x`
(with the actions rule, PR #139) only use versions that 2.15.1's own skins use; before the actions rule, `actions` version 2
was the one role that did not. Check: collect each role's versions from a skin and compare them with the stock set (a version
histogram alone is too coarse: it passed with actions at version 2).

## Decision still open (do not change the generator default yet)

The concern: changing the default shape could affect skins the community already built, and nobody should have to re-release.
Options, to be chosen after the experiment:

1. Keep the default; the 2.x ("compatible") shape stays opt-in.
2. **Install-time conversion:** the installer app reads the device's MPC OS version and rewrites a skin when installing to a
   2.x device, so existing releases work on 2.x with no re-release (a Go port of `to_mpc2x`, with the same tests).
3. Only authors who want 2.x support re-release.

The project owner's preference (2026-10-05): an automatic catalog compatibility field plus the opt-in generator option, below; installer
conversion stays a later option. A Discord post asking the community for input was drafted on 2026-10-04.

## Proposed direction: a catalog compatibility field (2026-10-05, from the project owner)

The default skin shape does not change. Instead the catalog says, per version and up front, whether a plugin works on MPC OS 2.x
or only on 3.x, and the catalog works this out itself:

- **Verified, not declared.** `os_compat` is `["2.x","3.x"]` or `["3.x"]`. It is `2.x` only when (a) the `.so` needs glibc 2.32 or less
  (already a catalog rule) and (b) every role in the skin uses a version that 2.15.1's own skins use. The check reads the zip; a
  developer cannot claim it.
- **The table behind (b)** is a small data file in the repo (for example `tools/skin_roles_2x.json`): per role, and per component
  type, the data versions and field names seen in the 110 stock 2.15.1 skins. It holds version numbers and field names only, never
  a stock file, and it is rebuilt from a stock-skin tar (the commands are under "The experiment, A").
- **Optional for developers.** A plugin built the way it is today is classed `3.x` and stays fully listed. A developer who wants the
  badge builds the 2.x shape (`SHADOW_SKIN_MPC_OS=2`, PR #139, plus a `vst-release.yml` input) or writes it by hand, and the checker tells
  them what is left if it is not compatible yet (for example a `Slider` at data version 4).
- **Existing releases need no re-release to be classified.** `catalog_build.py` already opens each release zip; it computes the field for
  versions that lack it, so everything already in the catalog gets a label.
- **Where it shows.** The field flows like `max_glibc` does today: `release.py` writes it into `mpc-plugin.json`, `catalog_check.py` recomputes
  it and fails on a mismatch, `catalog_build.py` puts it in `catalog.json` for each version, the site shows a badge and a filter,
  and the installer app shows the badge and warns when it installs a `3.x` plugin to a device that looks like 2.x (glibc 2.32 or
  less, or Buildroot 2021.02, which is a heuristic, so a warning and not a block).
- **Say what was tested.** "Checked against 2.15.1's own skins" is not "tested on a 2.x unit". The badge says which, using the existing
  tested-on field; a plugin shows plain "2.x" only after a 2.x device test is listed.
- **Limits to state in the docs.** The table comes from one 2.x version (2.15.1); other 2.x versions are unchecked. A structural check
  cannot prove that touch behaves the same.

Phases: 1. the table, `skin_os_compat()` in `catalog_check.py`, the manifest and catalog field (no site or app change); 2. the site badge and
filter; 3. the installer app badge and warning; 4. the generator option and workflow input (PR #139) and the developer docs.
Install-time conversion in the installer app (the earlier option 2) stays possible later and does not conflict with this: it could turn a
`3.x` plugin into a working one on a 2.x device, and the badge would then say so.

## Known gaps

- `to_mpc2x` handles `Knob` (5 to 1), `Button` (2 to 1), actions (2 to 1), definitions and tabs. It does not touch `Slider`: the Force
  has data 4, 2.15.1 has 3 (drop `revealType`), not implemented. `Meter` is identical on both. None of the six released skins
  (Dexed, JV-880, Acid, Maze Voice, Crate Digger, Monomodule) use `Slider` or `Meter`, but other authors' skins might.
- What the dropped fields do on 3.x is inferred from Akai's skins only using one value each. Not tested by changing them.
- One 2.x unit (an MPC Live on 2.15.1). Other 2.x versions and models are untested.
- Only Dexed has been seen on a 2.x screen. The other skins convert cleanly on paper (nothing above version 2 remains).

## The experiment

**A. Compare the two firmware generations (reading only).** Ask a 2.x user for a tar of the stock skins and build the same
per-type version table the Force corpus gave:
```
cd /usr/share/Akai/Content/Synths
tar czf /tmp/stock_skins_2x.tgz */'Plugin Skins'/TUI.json */'Plugin Skins'/Q-Links.json
```
Compare per component type (Knob, Button, Slider, Meter, Image, Label, Focus, Decorator, Indicator and the data fields of each).
Then extend `to_mpc2x` for any type that differs (Slider first).

**B. Bisect what 2.x rejects.** Start from the compat skin that works and add back one 3.x element per variant (everything
else identical):

| Variant | Content |
|---|---|
| V0 | the normal 3.x skin (control) |
| V1 | the compat skin (known good on both) |
| V2 | V1 plus `Button` data version 2 with `gestureBehaviour` |
| V3 | V1 plus `Knob` data version 5 |
| V4 | V1 plus definition version 4 (`repeats`, `hideQLinkBounds`) |
| V5 | V1 plus tab version 3 (`componentName`, `initialSize`, `scale`) |
| V6 | V1 plus an unknown extra field on a version 2 object (does 2.x ignore unknown fields?) |
| V7 | V1 with actions at version 2 (the first test skin sent to the 2.x tester): does touch work, or does 2.x ignore them? |
| V8 | V1 with actions at version 1 (the corrected test skin, `os2test2`): the current best shape |

Ship them in one zip as `TUI.V0.json` to `TUI.V6.json` and have the 2.x tester swap one file at a time (`cp`), then add the plugin
to a new track and report drawn or blank. First find out whether re-adding the plugin picks up a changed `TUI.json` without an
MPC restart (try V0 against V1). Each variant is a normal release-style zip if dropped into the installer app (update
`SHA256SUMS`; `python3 tools/catalog_check.py <zip>` must say OK).

**C. Behaviour on the Force.** Install each variant and test buttons (do they respond and toggle as before), knob drags, Q-Links
and every tab. Do not put values Akai's skins never use into a skin on a live device.

How to rebuild a test zip from a release zip: read `Plugin Skins/TUI.json` from it, call `shadow_skin.to_mpc2x(obj)`, write
it back with the same file list and an updated `SHA256SUMS` line (the permission bits in the zip must be preserved).

## State of things (2026-10-04)

- **Merged by 2026-10-05:** the findings (#138), this plan (#166), the catalog check and `os_compat` per version (#177), the site badge
  and filter (#178), the installer app and `mpc-store.sh` badge and warnings (#179), and the glibc relaxation (2.33 to 2.36 is listed as
  3.x only, #180). Installer app v0.4.0 carries the app side (a draft until the owner publishes it). Every release in the catalog is
  labelled `3.x` today (67 versions), because none uses the 2.x skin shape.
- **Generator option (#139, merged 2026-10-05):** `SHADOW_SKIN_MPC_OS=2` writes the 2.x shape (`to_mpc2x`), after a 2.x tester reported the converted Dexed skin working on a 2.15.1 MPC Live; its unit
  tests (in `tools/test_shadow_skin.py`) pass offline.
- **User-facing docs (2026-10-05):** the main README, the install guide and the developer page (`catalog/pages/add.md`) describe the
  labels and say that making a plugin 2.x-capable, and re-releasing it, is up to its developer. The nine plugin READMEs (Dexed with its 1.0.5 release, the others by PR) carry the updated note: this release works on 3.x, 2.x needs a release with a compatible skin, the catalog labels each release (2026-10-05).
- The test Force has Dexed's converted `TUI.json` installed; the original is at `/sdcard/os2test-backup/TUI.json.os3` on that
  device (copy it back over `Plugin Skins/TUI.json` to restore). MPC restarted on its own within seconds of that file swap;
  the cause is unknown (no crash lines in the log), so do not swap skin files on a live unit without telling the owner.
- The 2.x user's stock-skin tar (A) arrived 2026-10-04 and is analysed above. The first test skin he installed had actions at
  version 2; a corrected one (`Dexed-DX7-1.0.4-os2test2`) with actions at version 1 was built, so his touch checks must be
  repeated with it (tap a knob: does its Q-Link select; double-tap: does the overlay open; do toggles flip?). Still awaiting those from the 2.x tester.
- **Force (3.x), 2026-10-04:** the corrected skin (`os2test2`, all roles in the 2.15.1 shape, actions at version 1) was swapped into Dexed's
  folder on the Force (no MPC restart). It draws as before and touch works as before (tapping knobs, double-tap pop-ups, toggles, all tabs).
  So on 3.x the older shape costs nothing visible. Only Dexed, one device of each kind.
- A social post asking for 2.x model and OS reports was published; a Discord post with the options above was drafted.

## Do not

- Change the generator's default shape, or ask authors to re-release: the catalog labels what each release is, and 2.x support is the developer's choice.
- Commit any stock Akai skin file (analysis copies live in a scratch folder and are deleted afterwards).
- Restart MPC on someone's device without asking first.
