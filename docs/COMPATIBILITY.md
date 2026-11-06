# Compatibility, limits and device details

Reference material moved out of the README (2026-11-05). Verified facts with dates are in [NOTES.md](NOTES.md); the
MPC OS 2.x skin plan is in [OS2_SKINS.md](OS2_SKINS.md); Gen2 is in [GEN2.md](GEN2.md).

## What we've learned

- **The plugin host is a full citizen.** Plugins get MIDI in, the song tempo and transport, project save/restore
  and Q-Links, the same as Akai's own plugins.
- **A plugin is ordinary code inside MPC.** It can use the network (HTTP and HTTPS), read and write files, and run
  helper programs, which is how Crate Digger streams records. It shares MPC's audio threads, so it has to stay
  light and never make the audio wait.
- **The page is declarative, not drawn.** MPC builds the page from the skin's description; the plugin can't paint
  on screen. But parameter text updates live, and controls can be shown or hidden by a parameter's value, which
  is enough for readouts, status lines, result lists, mode-dependent panels and pop-up pickers.
- **Akai's own "plugins" are special.** Hype, TubeSynth and friends look like plugins but are built into MPC itself.
  Some of their tricks (the native drop-down picker) aren't available to real plugins, so we built our own.
- **Budget matters.** Gen1 hardware is a 4-core ARM chip at 1.8 GHz. A plugin gets about 2.9 ms per audio block and
  shares it with everything else in the project, so every port is benchmarked on the device before release.

## Limitations

- **MPC OS 2.x needs a compatible skin.** A plugin marked *MPC OS 3.x only* loads on 2.x and plays from the Q-Links, but its
  touchscreen page stays empty until its developer releases a version with a compatible skin. See
  [MPC OS 2.x vs 3.x](#mpc-os-2x-vs-3x).
- **A plugin shows no skin (just "Load Plugin") when its folder isn't a content location.** MPC finds a plugin's skin only through
  a `Synths` folder listed under `SynthContentLocations` in `MPC.settings`. The plugin still loads from its `file=` path, so
  it works but looks bare. Install into a listed folder (the installers warn when the target isn't one: `install.sh -t <folder>`),
  or add the folder to the list with MPC stopped and `MPC.settings` backed up, then start MPC. A trailing `/` is fine. Checked
  on a Live III (MPC 3.10.0), 2026-10-27; details in docs/NOTES.md.
- **VST2 only.** MPC OS has no VST3 or LV2 support. (For a desktop DAW, a port can also be built as a VST3 on this machine:
  [docs/DESKTOP_VST3.md](DESKTOP_VST3.md); its window shows the port's MPC skin.)
- **Setup needs root SSH to the device**, to copy the plugin and add it to `MPC.settings`, so it is for modded units.
  Adding a new plugin needs one MPC restart; the installers stop and start MPC for you (the service is `acvs`, or
  `inmusic-mpc` on firmware that has no `acvs`).
- **No native drop-down picker.** MPC's own menu opens empty for plugins (and can't practically be patched), so option
  lists are drawn by the skin instead: segment buttons or our own pop-up.
- **No custom-drawn widgets.** No live-drawn graphs or XY pads; only knobs, faders, buttons, text and images. Displays
  are pre-drawn pictures or filmstrips that follow a parameter (a waveform per wave shape, an envelope that follows its
  knobs: docs/COMMUNITY_SKINS.md), kept still between changes, since animating them costs MPC's screen thread a lot.
- **Two fonts for live text:** Titillium Web and Roboto. Any other typeface has to be baked into the artwork.
- **No text entry** on the page.
- **Plugin MIDI out is ignored by MPC.** Generators work around it by opening their own MIDI port, which MPC picks up
  like a new device. This is confirmed on a modded Force but not yet on a stock unit.
- **Timing resolution:** notes land on 128-sample blocks (about 3 ms), because the wrapper ignores the in-block position MPC
  sends with sequenced notes. An instrument whose engine renders any 1..128 frames can opt in to sample-accurate starts
  (`"defines": {"SAMPLE_ACCURATE": 1}`, docs/NOTES.md "Sample-accurate note starts").
- A plugin crash takes MPC down with it, so risky work belongs in a separate process.

## Device details

1. MPC OS reads `<VALUE name="pluginList-arm"><KNOWNPLUGINS>…` from its `MPC.settings` at startup (on the Force:
   `/media/az01-internal/Settings/MPC/MPC.settings`) and adds each
   `<PLUGIN format="VST" file="/sdcard/Synths/<vendor> - VST - <name>/x.so" …/>` to its plugin list. Edit it with MPC stopped and back it up
   first: malformed XML makes MPC reset it to defaults.
2. The `.so` exports `VSTPluginMain` (VST2 ABI, hand-written, no Steinberg SDK). Build for armhf against glibc 2.31
   (`arm32v7/gcc:11-bullseye`, which `tools/build_port.sh` uses) so it loads on MPC OS 2.x (glibc 2.32) and 3.x (2.39). A
   newer toolchain binds `pthread_create` and friends to `GLIBC_2.34`, which older firmware cannot load; the catalog
   check lists anything above 2.32 (up to 2.36) as MPC OS 3.x only and rejects more than that. Audio is 44.1 kHz in 128-frame blocks.
3. A skin folder `/sdcard/Synths/<manufacturer> - VST - <name>/` (`version.xml`, `Plugin Skins/TUI.json`,
   `Q-Links.json`) gives it a native screen. Controls bind to `"Parameter N"`, the VST parameter index.

## MPC OS 2.x vs 3.x

What differs, and what the catalog does about it (checked on an MPC Live on 2.15.1 and a Force on 3.x; details and dates in
[docs/NOTES.md](NOTES.md), the plan and open questions in [docs/OS2_SKINS.md](OS2_SKINS.md)):

- **System library.** MPC OS 2.x has glibc 2.32 (measured on a 2.15.1 MPC Live); 3.x and the Force have 2.39. A build that needs
  `GLIBC_2.34` (older Dexed and JV-880 releases, built with a newer toolchain) is listed by MPC on 2.x but shows only
  "Load Plugin"; those releases are yanked. The log lines to look for are `Attempting to load VST: ...` and
  `Initialising VST: ...` in `journalctl -u inmusic-mpc`.
- **Service name.** On 2.15.1 MPC runs as `inmusic-mpc`, not `acvs`. The installer app and current release zips detect it.
- **Skin format.** Every JSON object in a skin carries a `version`, and each kind of object has its own. The stock skins of
  2.15.1 use versions 1 to 3; the Force's use 1 to 5. Our generator wrote the Force's shape (tab 3, definitions 4, film-strip
  knobs 5, buttons 2, actions 2), which 2.x does not draw: the page stays empty and the log says nothing. The 2.x shape puts
  the page inline in the tab (tab 1, definitions 2) with knob, button and action data at version 1; the full table is in
  docs/OS2_SKINS.md. `Q-Links.json` is the same on both.
- **Both can read the older shape.** Dexed's skin written in the 2.x shape draws on a 2.15.1 MPC Live and on a Force. On the
  Force touch works as before, and a tester on a 2.15.1 MPC Live reported the same skin working there too.
- **The catalog decides, from the files.** For every release it works out `os_compat`: **2.x + 3.x** when the library needs
  glibc 2.32 or less and every object in the skin has a version and fields that 2.15.1's own skins use, otherwise **3.x only**
  (the reasons show on the catalog card's MPC OS line). Developers do not declare it. It is a check against one 2.x version's own
  skins, not a test on a 2.x unit, so the only badge, **MPC OS 2.x tested**, also needs a 2.x device test listed.
- **For developers: opting in is optional.** To make a plugin 2.x-capable, write its skin in the 2.x shape, check it with
  `python3 tools/skin_compat.py check "<skin>/Plugin Skins/TUI.json" "<skin>/Plugin Skins/Q-Links.json"` (it lists what still
  stops 2.x) and publish a new release; the label changes by itself on the next catalog build. Releases that are not
  re-released stay listed as 3.x only. The skin generator writes the 2.x shape when built with `SHADOW_SKIN_MPC_OS=2` (docs/PORTING.md); a plugin written by hand needs the table in docs/OS2_SKINS.md.

**Help us:** tell us your model, your MPC OS version (Settings), whether a plugin's page appeared, and what the
screen shows. If you are comfortable in a terminal and on 2.x, the output of this read-only command is very useful:
`cat /usr/share/Akai/Content/Synths/*/'Plugin Skins'/TUI.json | grep -o '"version": *[0-9]*' | sort | uniq -c`.

## Repository layout

- `wrapper/vst2_wrap.c` + `wrapper/engine.h`: a generic VST2 wrapper around a small engine interface
  (create, MIDI, string parameters, 128-frame int16 render). Link it with any engine plus a generated `params.h`.
- `adapters/`: engines written for other hosts, mapped onto that interface without code changes
  (`adapters/schwung/`).
- `tools/build_port.sh` + `tools/gen_vst.py`: the generic port builder. An engine ports with one small
  `vst.json` (name, uid, parameters, sources, optional layout) and no wrapper code: `tools/build_port.sh path/to/vst.json`
  makes the `.so`, the skin and the `pluginList` entry. See [docs/PORTING.md](PORTING.md).
- `tools/shadow_skin.py` + `tools/shadow_art.c`: build a skin from a Force Shadow style layout
  (`shadow_page.conf` widget syntax: frames, knobs, toggles, triggers, option segments, pop-ups, plus
  `qlinks` lines for nested pages). The artwork (backgrounds, knob filmstrips, button states) is drawn by
  [force-shadow](https://github.com/sd88me/force-shadow)'s own renderer, so the MPC page matches the
  shadow page pixel for pixel. That renderer is vendored in `tools/vendor/force-shadow/`, so no force-shadow
  checkout is needed.
- `tools/html_art.py` + `tools/html_art/`: the optional browser renderer for skin artwork (`"art": "html"`):
  the same layouts drawn as SVG/CSS in headless Chromium, restyled per port with a stylesheet.
- `tools/mpc310_on_391/`: a USB stick that runs the MPC 3.10 app on an MPC Live III that stays on MPC OS 3.9.1 (which
  keeps the USB-script route developers use for SSH). Built on your computer from Akai's two official Gen2 update
  images; nothing from Akai is in the repo. See [its README](../tools/mpc310_on_391/README.md).
- `tools/skin_check.py`: checks a built skin for overlapping touch areas, controls off the screen, Q-Links on hidden
  parameters and switches missing options; `gen_vst.py` runs it after every build.
- `tools/studio.py` + `tools/skin_template.svg`: the skin studio. Auto-layout from a port's
  parameters, a browser editor (`studio.py serve`, `tools/studio_web/`, started by the `SkinStudio.*` launchers), an
  Inkscape/Penpot SVG round trip, and page previews. Controls can use built-in looks or your own images and
  filmstrips (`tools/skin_assets.py`). See [docs/SKIN_STUDIO.md](SKIN_STUDIO.md).
- `tools/test_port.sh` + `tools/host_test.c`: the offline x86 test of a port under ASan (instances, params, options,
  popups, MIDI→audio, legacy `process()`, chunks), PASSED/FAILED.
- `tools/test_sample_page.sh` + `tools/sample_page_test.c`: the offline test of a port's MPC Sample page under
  ThreadSanitizer, with a stand-in draw handler.
- `tools/build_vst3.sh` + `wrapper/vst3_wrap.c`: the same port as a VST3 for a desktop DAW (Linux), for local use, with
  `wrapper/vst3_editor.c` drawing its MPC skin (flattened by `tools/desktop_skin.py`) in the plugin window;
  `tools/test_vst3.sh` + `tools/vst3_host_test.c` test it offline under ASan. See [docs/DESKTOP_VST3.md](DESKTOP_VST3.md).
- `tools/bench.sh` + `tools/bench.c`: a CPU stress test run on the device, with a PASS/WARN/FAIL verdict for Gen1
  hardware. See [docs/BENCH.md](BENCH.md).
- `tools/desktop/`: the MPC plugin installer app (Go; a local web page that installs, updates and removes plugins over SSH).
- `tools/plugin_manager_g2/`: the OpenMPC Plugin Manager VST, a VST that browses the catalog and installs, updates and removes plugins on the MPC itself (Gen2 first, with rollback; a fork of poloq's MIT `mpc-vst-manager`). See [its README](../tools/plugin_manager_g2/README.md) and `DESIGN.md`.
- `tools/mpc-store.sh`: the same install, update, remove, prune and sync from a shell on the device, for the catalog's one-line command.
- `tools/release.py`: packages a plugin as one shareable zip with an installer, an uninstaller and generated
  INSTALL.md. See [docs/RELEASING.md](RELEASING.md).
- `tools/probe_device.sh`: a read-only device report (CPU, 32/64-bit MPC, audio threads, plugin formats: VST2 yes,
  VST3 no on current firmware).
- `poc/gain.c`, `poc/synth.c`: minimal effect / instrument examples.
- `poc/midiport.c`: a MIDI-generating plugin (tempo-synced) that drives other tracks through an ALSA port
  (MPC OS ignores VST MIDI output; `poc/midiout.c` shows that).
- `poc/menuprobe.c`, `poc/textprobe.c`, `poc/netprobe.c`: the probes behind the picker, live-text and
  network findings in NOTES.
