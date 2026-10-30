# Porting an engine to an MPC OS plugin

## 0. Classify it
- **Block-rendering engine** (a synth/effect core): implement `mpc_engine()` (`wrapper/engine.h`) and wrap with
  `wrapper/vst2_wrap.c`; parameters come from a `params.json` (`tools/params.py`). An engine already written for
  another host plugs in through its adapter (`adapters/`, e.g. `adapters/schwung/` for Maze Voice, JV-880).
- **Engine with host-side glue** (control-socket keys that aren't DSP params, dynamic lists): write a port-specific
  wrapper on the same ABI (see the crate digger port) with virtual parameters for the glue. First check whether the
  same engine has an in-process build that fits the first category: an engine designed as an always-running
  standalone process (control socket, shared-memory audio) gives `processReplacing` nothing to read without real
  bridge work on the engine side. The DX7 port hit this and switched to an in-process build of the same engine.
- A port can live in its own repo next to a checkout of this one (`MPC_VST`), as mpc-vst-maze/-dx7/-acid do.
- **MIDI generator** (sequencer/arp): MPC ignores VST MIDI out, so send through an ALSA seq port (`poc/midiport.c`).
  Place steps from the host song position, not by counting MIDI clock pulses you synthesized, and send each block's steps
  at its start (look ahead one block, split at MPC's loop end): `docs/MIDI_TIMING.md`.
  A generator on the shared wrapper (no hand-written one) sets `"defines": {"HAS_SONG_POS": 1}` and provides `song_pos()` in
  `mpc_engine_t`: called once per block with `ppqPos`, tempo, play state and block length (`poc/songpos` is the test engine).
  Offline only until a device port uses it.
- **App** (network, files, child processes): allowed, see NOTES "Beyond synths". Keep the audio thread
  non-blocking, use `posix_spawn` with LD_PRELOAD stripped (never `fork()`), and use libcurl for HTTPS.

## Quick start (block-rendering engine)
Add a `vst.json` next to the engine (format in `tools/gen_vst.py`'s docstring; example:
`mpc-vst-maze/vst/vst.json`), then run `tools/build_port.sh path/to/vst.json`. That builds the skin from
`layout` (or from an auto-layout when there's none, which is a good first pass), `params.h`, the `.so` (linked with
`wrapper/vst2_wrap.c`) and `pluginlist-entry.xml`, all in `build/` next to `vst.json`. The port's own `build.sh` should
just call it (a build that links `wrapper/vst2_wrap.c` itself must add `-lpthread`: the wrapper's engine lock needs
it on the device's glibc 2.31 toolchain). Don't vendor copies of the wrapper or tools -- a port source that implements `mpc_engine()` itself
can `#include "engine.h"` directly (the builder puts `wrapper/` on the include path). Then bench it (docs/BENCH.md) and package it (docs/RELEASING.md).

`vst.json` `"version"` is the VST2 int, `major*1000 + minor*100 + patch*10 + build` (3.1.2 -> `3120`): gen_vst.py
writes it as `PLUG_VERSION` and the skin's `version.xml` now takes its four-part `<version>` from it too (2026-10-28,
offline-tested: the int decomposition and the file contents in `tools/test_shadow_skin.py`) -- before, every skin
shipped `1.0.0.0` and MPC listed a 3.1.1 plugin as 1.0.0.0. One decimal digit each for minor, patch and build, any
number for major: a patch above 9 rolls into the minor (that cannot be told from the int), so bump the minor.

**Vendor the engine's own source into the port's repo; don't fetch it at build time.** If the DSP comes from a
third-party upstream (another project's synth module, an emulator core, anything not written in this repo), `git clone` it
into the port's repo as committed files (`src/dsp/` or similar), not into a gitignored scratch dir pulled fresh
on every build. A `git clone` at build time makes the port fail offline, on a network hiccup, or the moment the
upstream repo moves/is deleted -- none of which is "fully self-contained." Copy the philosophy the DX7 engine itself
uses for MSFA (a vendored, committed copy, not a fetch of Dexed): pull the upstream source in once, apply any
local fixes directly to the vendored copy (no runtime patch-apply step), add the upstream's `LICENSE` if it
differs from the port repo's own (most engines here are GPL-3.0-compatible; check), and write a short
`src/VENDORED.md` recording the exact upstream commit vendored from, and precisely what was changed locally, so
a future re-vendor from a newer upstream is a real diff, not archaeology (see `mpc-vst-dx7`'s `src/VENDORED.md`
for the pattern). This applies to every future port, not just ones that hit the problem the hard way.

## 1. Engine
- [ ] Third-party DSP source (not written in this repo) is vendored -- committed into the port's own repo,
      not fetched at build time. See the Quick Start section above for exactly how and why.
- [ ] Builds for armhf with glibc ≤ the device's (`arm32v7/gcc:11-bullseye`, glibc 2.31, is what `build_port.sh` uses; bookworm images bind pthread_create to GLIBC_2.34 and do not load on MPC OS 2.x), exporting only `VSTPluginMain`.
- [ ] 44.1 kHz / 128-frame blocks (MPC's own period). Compile out host-specific quirks with `-D<NAME>_VST`.
- [ ] Build links with `-Wl,--no-undefined` (build_port.sh does): an unresolved symbol would otherwise only
      show up as MPC crashing when the plugin loads.
- [ ] Per-instance state; several instances may run at once.
- [ ] An engine that scans a data folder (banks, patches, samples) under `MODULE_DIR`: check its own path
      convention (`MODULE_DIR` itself, or `MODULE_DIR/banks/`?) against the port's on-device layout. A mismatch
      fails silently (no files found, default patch) and an offline test built on the upstream's own folder
      layout never shows it; build the test fixture to the port's layout.
- [ ] Optional, instruments only: `"defines": {"SAMPLE_ACCURATE": 1}` starts each note at its in-block position (MPC sends 0..127 for
      sequenced notes) instead of at the 128-frame block start. The engine's `render()` must then accept any 1..128 frames
      (check block-counting clocks, fixed-block cores) and `tools/test_port.sh` plus a bench (docs/BENCH.md) must pass.
- [ ] Optional: an engine that changes values by itself (a worker thread, a state machine, status text) sets `"defines": {"HAS_DISPLAY_REV": 1}` and
      bumps a `display_rev` value whenever something changed; the wrapper polls it every ~100 ms and tells the host (text, `when=` panels, meters). With a PRESET menu and live meters add
      `"DISPLAY_REV_NO_UPDATE": 1`: it reports only the moved values, no full `UpdateDisplay` (which closes the popup 10 times a second);
      text readouts then stop refreshing, so draw live numbers as `picture` widgets keyed on the same value (ottmpc: `vst/art/make_art.py`).
      Readouts longer than 24 characters need `"PARAM_TEXT_MAX": <n>` (NOTES.md; `poc/uiprobe` is the example).
- [ ] Optional: an engine that sets its own parameters from something the host doesn't see (MIDI on an ALSA port of its
      own, say) can instead define `mpc_engine_changed()` (`wrapper/engine.h`) and return each key it changed: the wrapper
      tells the host as it does for a MIDI CC (at most every 1024 frames per control; an option list also gets an
      UpdateDisplay), so the screen follows, and nothing is polled. Nothing to set in vst.json
      (`poc/selfset` is the test engine).
- [ ] Never hardcode `/sdcard/...` in an engine. Set `"defines": {"MODULE_SUBDIR": "\"engine\""}` in vst.json and
      the wrapper passes `<dir of the .so>/engine` to `create()`, found at runtime with `dladdr` (`wrapper/plugin_dir.h`,
      also usable directly via `mpc_plugin_dir()`), so the plugin works from `/sdcard/Synths`, `/media/*/Synths` or anywhere
      else. The `.so` must be dlopen'd by absolute path (MPC does this from the plugin list's `file=`). `gen_vst.py` warns when a
      `defines` value is a fixed `/sdcard` or `/media` path and `MODULE_SUBDIR` is not set (an absolute `MODULE_DIR` may stay as the fallback).
- [ ] An engine that lets the user pick files (ROMs, kits, IRs, models, dumps) from folders it scans:
      scan when the plugin opens and on request, on a separate thread, never on the audio thread; limit the depth (3-4 levels)
      and don't follow symlinks; sort the list (folder, then name) so a Q-Link position always means the same file; save the
      chosen file by NAME in the plugin state, not by position (positions shift when files are added), and re-find it by name
      if it moved; a missing file shows as not found and the audio keeps running. Users keep collections on cards, so an engine
      may also look for its data folder under `/media` (the plugin's own folder first), not only next to the `.so`.
- [ ] No I/O in `set_param()`/`get_param()`: one lock (`w->lock`, `wrapper/vst2_wrap.c`) covers set, get, MIDI and render,
      so a slow call on the host's thread delays audio. A port author's 50-130 ms SQLite query inside `set_param` clicked on every
      press, and no de-click fade can hide a late audio callback. Post the work to a worker thread (`nice(10)` is fine), publish the
      result under a short mutex of its own, and pick it up in `render()` with `pthread_mutex_trylock`.
- [ ] Every report to the host (`audioMasterAutomate`, `UpdateDisplay`, momentary buttons springing back, readout polls) is
      sent from `processReplacing()`. When MPC stops calling it, nothing goes out, so don't treat render as a heartbeat. A
      status light that must move while idle needs its own timer (MM-303 runs a 50 ms ticker per instance).
- [ ] Polled readouts cost one `get_param()` each on the audio thread (every 10 ms for `<key>_on`, every 100 ms for text).
      The wrapper spreads them over the blocks (each block reads its share of the list, never all of it), and `gen_vst.py` leaves
      out a text param the layout never mentions (its key, `get=`, a `when=`, a list or a `qlinks` line); `"poll": true` keeps one the
      skin does not show but you want refreshed. A layout with a pattern in a widget value (`%`, `*`, `{`), no layout, `custom_skin` and
      `skin_post` polls everything. Still set `"poll": false` on readouts that only change on a tap, and keep anything costly out of
      a polled key (docs/BENCH.md).
- [ ] State saved via chunks (`effGetChunk`/`effSetChunk`).
- [ ] Offline x86 test: `tools/test_port.sh <port>/vst.json` prints PASSED (instances, parameter round-trip,
      options, popups, MIDI → audio, chunk restore, under ASan).
- [ ] Desktop VST3 (optional, local use only, never shipped to a device): `tools/test_vst3.sh <port>/vst.json` prints "all passed";
      `tools/build_vst3.sh <port>/vst.json --install` puts it in `~/.vst3` (docs/DESKTOP_VST3.md). Run it after `build_port.sh`, so
      the plugin window has the skin; `--shots <dir>` on the test writes each page to look over.
- [ ] Gen2 (optional, proven on two ports as of 2026-10-11 — Crate Digger, Profit-08, both loaded on a real MPC Live III): `"targets":
      ["armv7", "aarch64"]` in vst.json, `tools/build_port.sh <port>/vst.json aarch64` builds `build/aarch64/<so>` (`arm64v8/gcc:12-bookworm`),
      `tools/test_port.sh <port>/vst.json aarch64` must print PASSED (UBSan, arm64 container), and the release carries both zips
      (docs/RELEASING.md, docs/GEN2.md). Still say "offline only" (or name the device once it's run there) until it has loaded on a Gen2
      device of your own. A documented root route exists for Gen2 on MPC OS 3.9.1 (the autorun USB stick, docs/USB_STICK.md — on demand,
      not persistent across a reboot); MPC OS 3.10.0 removes it (docs/GEN2.md, docs/NOTES.md 2026-10-23), so a device already updated to
      3.10+ has none from this project.

## 2. Parameters
- [ ] Stable order (the VST index is what skins and projects bind to). Append only; never reorder a shipped plugin.
      `gen_vst.py` writes `params.lock` next to `vst.json` on the first build: commit it. A build fails when an existing key
      changes index; `GEN_VST_RELOCK=1` accepts the break (before a first release only). Rebuild the skin after any change.
- [ ] Options: an index; nudges step one option (the wrapper does this). Triggers: `"momentary": true`, which springs back.
- [ ] MPC delivers one tap on a drawn button as **two presses 30 to 140 ms apart** with no release between (the finger going down and lifting;
      measured on a Live III, MPC OS 3.9.1, 2026-10-30: `set k_A=1` twice per tap). A momentary param therefore ignores a second press within
      `"debounce_ms"` of the last one it acted on (default 250; the wrapper does this, so "Program >" steps one program and a drawn keyboard types
      one letter). Set `"debounce_ms": 0` on a trigger that must fire as fast as it is tapped. Releases (the spring-back to 0, the host's echo of it)
      are never held back. Plugins built before this change double-fire: rebuild and re-release them with the current wrapper.
- [ ] A control can't be disabled from the host side: the wrapper has no `effGetParameterProperties`, and JUCE's VST2
      host has no "disabled" flag anyway. Hide it in the skin (`when=`). A control with nothing to do (a pager with one
      page, "next" at the end of a list) must do nothing in the engine: clamp and ignore it there. `setParameter` still
      arrives for a param that isn't automatable. A button with an empty on/off image draws MPC's generic "Button"
      caption: give it real artwork.
- [ ] Display strings are the only dynamic text channel into the skin (see NOTES on refresh behaviour).
      A param whose `get_param()` returns real text (a name, a status message), not a number, needs
      `"display": "string"` in its parameter entry -- otherwise the wrapper's default numeric
      reformatting mangles it down to "0" (see NOTES).

## 3. Skin
- [ ] Design in a layout `.conf` (Force Shadow widget syntax plus `qlinks`/`rows=`), or port an existing shadow page.
- [ ] **No other company's name or logo in the skin** (manufacturer wordmarks, logo-bearing panel artwork, trademarked
      product art), none in the plugin name or the catalog `screenshot`. The summary and tags may say what you model
      ("X-style") but not imply the maker's endorsement. A hardware-clone skin needs its own artwork and generic labels. See `catalog/README.md` "Skins and branding".
- [ ] **If the app has its own `addon/shadow_page.conf`, copy its `style=`/`theme_*` lines verbatim into
      the top of the port's `layout.conf` before anything else.** Without them the skin renders in
      `shadow_art`'s generic default palette (cream knobs, dark plate, orange accent) instead of the
      app's real look (e.g. force-acid's yellow chassis / red buttons) -- easy to miss because the build
      succeeds and the layout is otherwise correct; only the offline preview shows the mismatch.
      `shadow_skin.py` forwards the whole layout file to `shadow_art` as `theme|<layout.conf>`, which
      applies it exactly like force-shadow's own on-device renderer (`render_conf_preview.c`'s
      `load_conf`) -- every `theme_*` key a shadow page uses, not just the small subset
      `apply_theme()` uses Python-side for label text. If there's no shadow page to copy from, pick
      theme colours deliberately instead of leaving the default.
- [ ] Generate (`tools/shadow_skin.py` via the port's gen script), then look at an offline composite
      (`tools/studio.py preview`) before deploying -- compare it against the real shadow page's own
      screenshot/mockup if one exists (`docs/*.png` in the app's repo), not just "does it look plausible".
- [ ] No skin image taller than 16384 px. A filmstrip of many frames of a tall control passes that easily, and MPC then
      draws it wrongly (misaligned half-frames); reduce the frame count or size. (Reported by another port author; not yet
      reproduced on our device. `catalog_check.py` warns about such images.)
- [ ] Q-Links: 1–8 = knob bank 1, 9–16 = bank 2; nested pages via several `qlinks` lines.
- [ ] Labels or unpolled text that follow another param (`dynamic_name` / `dynamic_display` reading a selector, a
      `"poll": false` readout bound with `get=`), or a skin `when=` panel that follows a param the engine derives from another
      (TR-MPC's `sNN_fam`, set by the voice `sNN_src`): put `"refresh_display": true` on the param that is written. A plain host write
      no longer asks MPC for an UpdateDisplay (NOTES.md 2026-10-21). Test Q-Links on track edit → automation, not only
      on the plugin screen: that screen takes a different host path.
- [ ] A param the engine changes by itself (a network or status readout, a progress value) gets `"live": true` in params.json:
      `gen_vst.py` lists it as `PLUG_LIVE` in params.h and `host_test`'s "parameter 0 toggle changes nothing" check skips it. Without it that check
      fails offline (2026-10-27, found porting the Plugin Manager). `host_test` also no longer uses parameter 0 for its option-step tests: the
      wrapper holds parameter 0 for MPC's STOP toggle, so a one-event move of it does not step.
- [ ] A param you retired from the screen but kept in the table, so saved projects and automation keep their indices, gets
      `"legacy": true` in params.json: `gen_vst.py` lists it as `PLUG_LEGACY` in params.h and `host_test` no longer picks it as
      the first knob, option list or whole number of its checks (2026-10-29, offline: `poc/steptest` with its first param flagged
      moved the knob check to the next one). Keep the param in the table; do not reorder it away to get a green test.
- [ ] Option lists and `"display": "int"` params step one option or whole number per Q-Link event and per data wheel
      click (`settle()`). If a short one races by under a Q-Link, `"qlink_ticks": N` on that param (opt-in, off by default)
      counts N events per step: 6 suited a 9-option list on a Key 37. It costs N wheel clicks per step too, and on a Force
      a counted Q-Link felt sticky and uneven on whole numbers (NOTES.md "Q-Link slow-down prototypes on a Force"), so
      use it per param, only where it is wanted, and try it on the device. A long `"display": "int"` list (a bank list of up to
      998) has the opposite problem: a Q-Link event (1/128 of the range) or wheel click (1/100) crosses eight to ten entries, so
      add `"nudge_pct": 10` (a move up to 10% of the range is one step; a bigger one sets outright). A two-column `list` can
      number down each column first with `order=cols`, so it reads and steps top to bottom.
- [ ] MPC OS 2.x: skins are written in the MPC OS 3.x format by default. `SHADOW_SKIN_MPC_OS=2` in the environment of the build
      (`tools/build_port.sh` passes it on) writes the older shape MPC OS 2.15.1 reads, which a Force on 3.x reads too (docs/OS2_SKINS.md).
      The release tool prints `MPC OS compatibility: ...` and the catalog labels the version from the skin and the library's glibc.
- [ ] Choice lists: `enum_h`/`enum_v` (all options on screen) or `popup` (a field; a tap opens a drawn list, a
      pick closes it). Not `menu`: MPC's native picker opens empty for a VST2. A `popup` adds a hidden
      `<key>__open` param after the port's own (gen_vst.py), kept by `wrapper/vst2_wrap.c`. A hand-written
      wrapper includes `wrapper/popup.h` (after params.h) and follows its usage note, or its lists won't close. `studio.py preview`
      writes a `_open` image per page with popups.
- [ ] Look: the default renderer copies a Force Shadow page exactly; for a new look (any font, gradients,
      artwork drawn in Inkscape) set `"art": "html"` and restyle with `art_css=` (SKIN_STUDIO "Artwork renderers").
- [ ] Controls that only matter in one mode (per oscillator type, sync on/off): `when=<param>:<option>` on their
      layout lines, so each mode shows its own set in the same space (SKIN_STUDIO "Mode panels").
- [ ] Instruments-browser tile: `"tile": "art/tile.png"` (270x110 PNG) in vst.json puts the artwork tile in the Sounds >
      INSTRUMENTS browser and ships a Default preset so the tile opens the plugin (`tools/xpl.py`; NOTES.md
      "Instruments-browser tiles"). Without it the plugin is a folder tile in the browser.
- [ ] Presets in MPC's PRESET menu (2026-10-07; menu listing and loading checked on a Force, reload behaviour not yet): an engine with its own preset parameter
      sets vst.json `"programs": {"param": "<key>"}` (an option list, or a `"display": "int"` range whose names the engine
      gives as `get_param("<key>:<n>")`); one without sets `"presets": "presets.json"` (`{"presets": [{"name", "values":
      {key: value}}]}`, values in each parameter's units or an option's label; gen_vst.py checks them). Set every
      parameter in every preset, in the order the engine needs, and make the first one the plugin's default sound.
- [ ] MIDI control (2026-10-07, offline): CC 20-35 on the track's MIDI input move the first page's Q-Links (first `qlinks`
      line, column 1 top to bottom = CC 20-23) and NRPN n (CC 99/98, value on CC 6, fine on 38) sets parameter n. Both on by
      default, and those CCs then don't reach the engine: an engine that reads CC 20-35 or NRPN itself sets vst.json
      `"cc": false` / `"nrpn": false`.
- [ ] Skin touch-ups the layout can't express (per-role live-text sizes/colours in `TUI.json`): a script named by
      vst.json `"skin_post"`, run on the built skin folder; make it fail when its targets are missing. Design ideas from
      other ports: `docs/COMMUNITY_SKINS.md`.

## 4. Device
- [ ] The plugin is one folder, `/sdcard/Synths/<vendor> - VST - <name>/`: the `.so`, `Plugin Skins/`, `version.xml` and any data next to the `.so`.
- [ ] `pluginList-arm` entry (MPC stopped, settings backed up), then restart (ask first).
- [ ] User test: list → insert → play → skin → Q-Links → save/reload project. Record results in NOTES.md.

## 5. Make it catalog-ready (do this from the first commit)
Every port is meant to be listed in the plugin catalog (`docs/CATALOG.md`, `catalog/README.md`). Nothing to type per release
if you do this once:
- [ ] Repo is public with an SPDX `LICENSE` file (MAME-style or other non-open licences need `source_available`, see `catalog/README.md`). No closed binaries or copyrighted ROMs in the repo or zip.
- [ ] Release only through `tools/release.py` / the reusable `vst-release.yml` workflow **with** `--repo owner/name --license <SPDX> [--id kebab-id] [--requires "..."]` (workflow inputs `plugin_id`, `license`, `requires`). That writes `mpc-plugin.json`; a zip without it is not listable.
- [ ] Gate: `tools/catalog_check.py dist/<zip> --catalog --expect-id <id> --expect-repo owner/name` must print OK.
- [ ] Optional `tested.json` at the repo root (`[{version, device, firmware, date}]`) after each device test: shown as "Tested on".
- [ ] One PR adding `catalog/plugins/<id>.json` to mpc-vst-plugins (first release only). Never put versions or checksums in it.
- [ ] Keep the `uid` and `.so` name fixed; bump `param_compat` (X of X.Y.Z) only when parameter indices change.
- [ ] **Firmware-derived port?** If the DSP is compiled from the user's own firmware (so the built `.so` embeds firmware
      code, or the zip carries ROM samples or the OS file), you cannot publish a zip at all. Opt out of the release path:
      list it as `"distribution": "build-yourself"` (`catalog/README.md`, `docs/CATALOG_SPEC.md`). The repo then needs a
      one-command build script that makes a per-user installer (and a bit-exactness gate if the recompile can drift), a
      `vX.Y.Z` tag containing that script, an open licence, and **no** `*-mpc-armv7.zip` on any GitHub release. Still
      build the installer with `release.py --repo --license` so it is `mpc-plugin.json`-conformant locally
      (`catalog_check.py --catalog`), but never upload it.
