# Roadmap

Repo-level features still to do, in rough priority order. Verified behaviour goes in `NOTES.md`; move an item
there (with the date) once it's done and seen on a device. Port-specific work lives in each port's repo.

## Skin controls
Building on parameter-driven visibility (`IndexedEnabling`, NOTES "Conditional visibility").

- [ ] **Font choice for live text.** Let a layout pick `Titillium Web` or `Roboto` and the weight/size for
      names and values (the only two families MPC resolves).
- [ ] **Build and preview from the browser editor.** A button in `studio.py serve` that builds the port's skin and
      shows `studio.py preview`'s pages (needs the port's vst.json and the renderer's Docker image).
- [ ] **Looks and images on a device.** Built and previewed offline (2026-09-25): check a skin with image knobs,
      an imported filmstrip, image toggles/buttons/segments, a panel picture, a popup list picture and a `picture`
      (one image per option) on a Force.
- [ ] **Builder features from other forks (docs/COMMUNITY_SKINS.md "Adoption list", 2026-10-07).** Port from
      `saustin2010/vst_instruments`' patch to `tools/shadow_skin.py`. Done offline 2026-10-07 (device check pending):
      `banks=`, `ns=`/`vs=`/`bw=` on knobs and sliders. Sliders and meters as stock filmstrips (frames of their own size, `numFrames` = count,
      <= 12288 px) done 2026-10-07. `lay=side` knobs, `ns=0`/`bw=` on toggles and `sh=` on enum_v
      followed the same day. All offline; check on a device.
- [ ] **Skin checker: the rest.** `tools/skin_check.py` (2026-10-07) covers TOUCH / EDGE / QLINK and runs in
      `gen_vst.py`; OPTS (incomplete switch groups) added the same day. Still to add: Q-Links out of the layout's order
      (needs the layout next to the skin).
- [ ] **VST programs and wrapper presets: device check.** vst.json `"programs"` / `"presets"` are in (2026-10-07, offline,
      host-tested); device-checked 2026-10-07 on a Force: the
      PRESET menu lists and loads them. Still to check on a device: a tweak surviving a project reload (and the name the menu
      then shows) and re-picking the current preset. Not yet supported: programs whose count
      changes at run time (user banks) or names stepped from an engine that can't name a preset without loading it.
- [ ] **MIDI CC 20-35 / NRPN control: device check.** In the wrapper 2026-10-07 (offline, host-tested); the other fork saw
      CC 20/21 from a sequencer move an instrument's controls on a Live II. Confirm with one of ours, and that MPC keeps
      none of CC 20-35 for itself.
- [ ] **One engine call at a time: device check.** Done offline 2026-10-07 (`eng_set()` etc. in `wrapper/vst2_wrap.c`, a
      two-thread section in `tools/host_test.c`); measure the uncontended cost on a device with docs/BENCH.md.
- [ ] **Engine-driven live updates need a new wrapper mechanism.** (Partly stale: `HAS_DISPLAY_REV` now polls an
      engine's `display_rev` and refreshes the host, NOTES "display_rev"; another fork measured that repainting
      costs MPC's screen thread a lot, NOTES 2026-10-07. Re-check what is left before working on this.) Confirmed on a Force 2026-09-25
      (`poc/meterprobe`): `wrapper/vst2_wrap.c` never calls `audioMasterAutomate`/`audioMasterUpdateDisplay`
      for a parameter the DSP engine changes on its own between host-initiated calls (only in response to a
      touch/Q-Link, via `setParameter`'s `need_update_display`) — so a filmstrip `meter` or any other display
      bound to a free-running engine value never visibly updates, even during playback. Needs the engine
      interface (`wrapper/engine.h`) or wrapper to gain a way for an engine to flag "this key changed" so
      `run_block()` can call the host back regardless of whether `setParameter()` fired. See NOTES.md.
- [ ] **Tab images.** MPC draws the function-key tab bar; find how stock skins give tabs on/off images (from a
      stock TUI.json, described in NOTES, not committed) and whether a plugin skin can. `Indicator`
      (`indicatorId`, `numIndicatorsInGroup`, on/off images — see below) is an unverified candidate.
- [ ] **`MenuOverlay` naming check.** Very likely the same native list picker already confirmed **empty for
      VST2** (NOTES.md "Native picker (menu overlay): not available to VST2", 2026-09-24) under its real
      component name, not a new option — `popup` stays the way to do a list. Not separately verified.
## Porting and tooling
- [ ] **Catalog: MPC OS 2.x / 3.x compatibility field.** Derived by the release and catalog checks (glibc 2.32 or less, and the skin only uses
      versions 2.15.1's own skins use); badge and filter on the site, badge and warning in the installer app; developers opt in with the
      2.x skin shape. Plan and phases: [docs/OS2_SKINS.md](OS2_SKINS.md) ("Proposed direction").
- [ ] **Q-Link feel on option lists and whole numbers.** A Q-Link event is one step on a Force (docs/NOTES.md "Stepping of option lists
      and whole numbers"), which is quick on a short range; the data wheel is right. Three prototypes of slowing it failed (NOTES). First
      thing to try: how the stock plugins (AIR, Akai) respond to the same Q-Link on a stepped param, by logging what MPC sends them
      and what they read back, then match that.
- [ ] **A reference port on `engine.h` + `params.json`** (e.g. `poc/synth.c` turned into a full example), so
      the repo shows a port that needs no adapter.

## Community catalog
The catalog, its site and the installer app are live (see Done). Still open, in `docs/CATALOG.md`:
- [ ] **Failure handling:** a bad new version is excluded and the previous good one kept; open an issue on the plugin's repo.
- [ ] **A port template repo** (`vst.json`, `build.sh`, release workflow, `tested.json` stub, README) so a new plugin is
      catalog-ready from its first commit.
- [ ] **Update notices honour `param_compat`** (a major bump warns that saved projects will change).
- [ ] **Announce to the community** and collect what people ask for before building more.

## Patches (installer app)
- [ ] **"Advanced" step for device patches** (`tools/mpc_patch`: the drum-pad layout and drive exec, from #150). Plan in
      `docs/PATCHES.md`: a manifest, the script stays the unit (`status` / `install` / `uninstall`), typed confirmation, staged rollout.
      Built (2026-10-03/04): the script contract (`STATE` line with checksum, `install --confirmed`, restore of an unknown build from a
      verified stock backup), `catalog/patches.json`, and a read-only step 7 in the app. Seen on a Force 2026-10-04: the app's row, the
      restore and the reinstall (NOTES 2026-10-04). The drive exec patch from #150 (run plugins from a `noexec` drive) is built and listed
      (2026-10-05, offline only, real-mount tests). The button remap (`tools/mpc_patch/hwremap`, from akai_standalone_remap) is built and listed
      the same day, also offline only: the shim's author had already tried it on an MPC Live (Hakai) and a Force; this installer has not been run on a device.
      **Still to do:** a Force run of the drive exec patch (install, reboot, a plugin loads, uninstall), a device run of the button-remap installer, and
      Apply and Undo from the app (then a Force test).

## Verification
- [ ] **Stock, unmodded MPC and other models:** the ALSA MIDI-out port (`poc/midiport.c`) without MockbaMod,
      and `tools/probe_device.sh` after firmware updates. Needs the hardware.

## Done
- [x] Community catalog and installer (2026-10-02): https://sd88me.github.io/mpc-vst-plugins/ lists the community's plugins
      (registry in `catalog/plugins/`, releases read from GitHub nightly, every zip checked, per-version "Tested on", all-time
      downloads, Atom feed), with guides and a one-line shell install (`mpc-store.sh`). The MPC plugin installer app
      (Windows, Mac, Linux; `tools/desktop`, 0.3.x) installs, removes and prunes over SSH with one MPC restart. Plugins
      from several authors are listed, and build-yourself ports (Monomodule, Machinemodule) for engines that need your own
      firmware. Phases 0 to 4 of `docs/CATALOG.md` are done apart from the items above.
- [x] Loads on MPC OS 2.x (2026-10-02): the shared tools and the ports build against glibc 2.31 (`arm32v7/gcc:11-bullseye`; the
      build-yourself ports use a `debian:bullseye` cross image), and the catalog lists anything above 2.32 as MPC OS 3.x only (and rejects above 2.36, 2026-10-05). The installers
      use `acvs`, or `inmusic-mpc` where there is no `acvs`. NOTES 2026-10-01 has the report that led to this.
- [x] Control looks and images, offline (2026-09-25): built-in looks (knobs moog/chicken/metal/cap, slider fader,
      toggles led/switch), turning knob images with a still base, filmstrip import (knobs, sliders, meters), slider
      thumb/track, on/off images for toggles, buttons and segments, frame and popup panel pictures, bitmap and
      placed `art`, `picture` (images that follow a value), per-kind layout defaults; editor Look section and
      Assets tab. A skin without looks builds byte-identical to before.
- [x] Browser editor for layouts, `studio.py serve` (2026-09-25): canvas drawn by the browser renderer, move/resize,
      inspector, tabs, modes, Q-Link sets, theme colours, `art_css` editing with fonts, SVG art import, checks.
      Verified offline in Chromium: load and save without edits gives the identical file. Double-click launchers
      (`SkinStudio.command` / `.bat` / `.sh`) with a start screen; the `.sh` one tested on Linux, the macOS and
      Windows ones not yet run on those systems.
- [x] Browser renderer (`"art": "html"`, `art_css=`), SVG background art (`art file=`, studio round trip) and
      mode panels (`when=`), verified on a Force (2026-09-25); real-font baked text comes with the browser renderer.
- [x] Popups in Maze, JV-880, Acid and Euclidier, verified on a Force (2026-09-25).
- [x] Auto-layout picks `popup` for 7+ options; `wrapper/popup.h` shared by hand-written wrappers (2026-09-25).
- [x] One-command offline test: `tools/test_port.sh <vst.json>` (2026-09-25).
- [x] NOTES open issues reviewed and resolved items folded down (2026-09-25).
- [x] `popup` control, verified on a Force (2026-09-25).
- [x] Generic engine interface + `adapters/schwung` (2026-09-25).
- [x] `Envelope`/`EnvelopeOverlay`, `XYPad`/`Plotter`: checked on a Force (2026-09-25) — no stock `TUI.json`
      defines a component of any of these types; the one grep hit (TubeSynth) was a tab name, not a component
      type. Not available; see NOTES.md.
- [x] `KnobOverlay`: verified on a Force (2026-09-25, Maze Voice) — works fully for VST2 params (value, name,
      settable, reflects live Q-Link/automated changes). `NumericOverlay`: tested on a Force (2026-09-25,
      Maze Skin Test) — not a recognized overlay name, shows a blank/stuck panel instead. See NOTES.md.
- [x] Native `Meter` component: tested on a Force (2026-09-25, `poc/meterprobe`) — breaks the whole plugin
      screen (blank), not just left unrendered. Not usable; `look=native` now refuses at build time
      (`tools/skin_assets.py`) instead of building a broken skin (the filmstrip-fake `meter` stays the
      only way to show a level). See NOTES.md.
