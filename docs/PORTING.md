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
- **App** (network, files, child processes): allowed, see NOTES "Beyond synths". Keep the audio thread
  non-blocking, use `posix_spawn` with LD_PRELOAD stripped (never `fork()`), and use libcurl for HTTPS.

## Quick start (block-rendering engine)
Add a `vst.json` next to the engine (format in `tools/gen_vst.py`'s docstring; example:
`mpc-vst-maze/vst/vst.json`), then run `tools/build_port.sh path/to/vst.json`. That builds the skin from
`layout` (or from an auto-layout when there's none, which is a good first pass), `params.h`, the `.so` (linked with
`wrapper/vst2_wrap.c`) and `pluginlist-entry.xml`, all in `build/` next to `vst.json`. The port's own `build.sh` should
just call it. Don't vendor copies of the wrapper or tools -- a port source that implements `mpc_engine()` itself
can `#include "engine.h"` directly (the builder puts `wrapper/` on the include path). Then bench it (docs/BENCH.md) and package it (docs/RELEASING.md).

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
- [ ] Engine with NEON intrinsics (Vital DSP, many C++ DSP libraries): put `-mfpu=neon` (and any ARM-only defines, e.g.
      Vital's `-DNEON_ARM32`, since `vdivq_f32` is AArch64-only) in vst.json `build.cflags_arm`, which only the device
      compile gets, so the x86 host test still builds (`ports/vitottx`).
- [ ] Optional, instruments only: `"defines": {"SAMPLE_ACCURATE": 1}` starts each note at its in-block position (MPC sends 0..127 for
      sequenced notes) instead of at the 128-frame block start. The engine's `render()` must then accept any 1..128 frames
      (check block-counting clocks, fixed-block cores) and `tools/test_port.sh` plus a bench (docs/BENCH.md) must pass.
- [ ] Optional: an engine that changes values by itself (a worker thread, a state machine, status text) sets `"defines": {"HAS_DISPLAY_REV": 1}` and
      bumps a `display_rev` value whenever something changed; the wrapper polls it every ~100 ms and tells the host (text, `when=` panels, meters).
      Readouts longer than 24 characters need `"PARAM_TEXT_MAX": <n>` (NOTES.md; `poc/uiprobe` is the example).
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
- [ ] State saved via chunks (`effGetChunk`/`effSetChunk`).
- [ ] Offline x86 test: `tools/test_port.sh <port>/vst.json` prints PASSED (instances, parameter round-trip,
      options, popups, MIDI → audio, chunk restore, under ASan).

## 2. Parameters
- [ ] Stable order (the VST index is what skins and projects bind to). Append only; never reorder a shipped plugin.
- [ ] Options: an index; nudges step one option (the wrapper does this). Triggers: `"momentary": true`, which springs back.
- [ ] Display strings are the only dynamic text channel into the skin (see NOTES on refresh behaviour).
      A param whose `get_param()` returns real text (a name, a status message), not a number, needs
      `"display": "string"` in its parameter entry -- otherwise the wrapper's default numeric
      reformatting mangles it down to "0" (see NOTES).

## 3. Skin
- [ ] Design in a layout `.conf` (Force Shadow widget syntax plus `qlinks`/`rows=`), or port an existing shadow page.
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
