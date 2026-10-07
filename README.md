# VST Plugins for MPC OS

> 💬 **Community:** join [**Open MPC** on Discord](https://discord.gg/sRRysZSgu3) for support, release announcements, plugin requests and MPC hacking.

Native plugins for **Akai MPC OS standalone devices** (MPC Live/One/X/Key, Force): a catalog to find and install them,
an installer app, and the tools to build, test and release your own.

> **MPC OS 2.x and 3.x.** Plugins here are built and tested on **MPC OS 3.x**. On **MPC OS 2.x** a plugin loads and its
> Q-Links work, but its touchscreen page only appears if the plugin's skin is written in the older format 2.x reads. The
> catalog says which each release is (**MPC OS 2.x + 3.x** or **MPC OS 3.x only**), checked from its files, so you know
> before you install. A 3.x-only plugin becomes 2.x-capable when its developer re-releases it with a compatible skin
> (how, and what the catalog checks: [MPC OS 2.x vs 3.x](#mpc-os-2x-vs-3x) below).

## Plugin catalog

**[MPC OS Plugin Catalog](https://sd88me.github.io/mpc-vst-plugins/)**: one browsable list of the community's VST2
plugins for MPC OS, with each plugin's current version, license, source link and a checksummed download.

[![The MPC OS Plugin Catalog home page](docs/img/catalog-home.png)](https://sd88me.github.io/mpc-vst-plugins/)

- **Find a plugin.** Search, filter by kind, style, developer, license or distribution, and sort by recently updated or
  most downloaded. Every version shows its date and SHA-256, and what it was tested on. There is an Atom feed
  (`feed.xml`) of new releases.
- **Install with the installer app.** The [MPC plugin installer](https://github.com/sd88me/mpc-vst-plugins/releases/latest) is a
  small Windows, Mac and Linux app: connect to your device, tick plugins from the catalog (or drop in zips, including
  build-yourself ones), and it checks each download, installs the batch with one MPC restart and backs up your settings
  first. It can also remove plugins (keeping your own files), install to an SD card or USB drive, register plugin folders
  MPC does not know about, and clean up old settings backups. Needs root SSH access. Source in
  [tools/desktop](tools/desktop/README.md).
- **Guides on the site:** [install a downloaded plugin](https://sd88me.github.io/mpc-vst-plugins/install.html),
  [build a plugin](https://sd88me.github.io/mpc-vst-plugins/build.html), the
  [release workflow](https://sd88me.github.io/mpc-vst-plugins/workflow.html) and
  [how to get yours listed](https://sd88me.github.io/mpc-vst-plugins/add.html).
- **Get your plugin listed.** Publish a GitHub release built with `tools/release.py` (or the reusable
  `vst-release.yml` workflow), then open a PR adding one small file, `catalog/plugins/<id>.json`. After that new
  releases appear on their own: the catalog reads your releases every night and checks each zip. Open-source licenses,
  or public source with a limited-use license (shown with a "Restricted use" badge).
- **Plugins built from your own firmware** (so a built zip can never be shared) are listed as **Build it yourself**:
  no download, just what you need, the exact build command and a warning.
- Details: [docs/CATALOG.md](docs/CATALOG.md) (design and roadmap), [docs/CATALOG_SPEC.md](docs/CATALOG_SPEC.md) (formats),
  [catalog/README.md](catalog/README.md) (how to contribute).

MPC OS has a plugin host built in: a copy of the JUCE framework that can load Linux VST2 plugins. This repo builds
plugins for it. They behave like MPC's own instruments and effects: you add them to a track, play them from pads,
keys or the sequencer, turn them with Q-Links, and they're saved with the project. Each one gets its own **native
MPC touchscreen page**. There's no bridge, no background app and no LD_PRELOAD: the plugin runs inside MPC.

<img width="906" height="570" alt="A plugin's custom page on the MPC touchscreen" src="https://github.com/user-attachments/assets/3bb29544-0cd0-409f-b5b4-7df67ddbaf9a" />

## Where we are

This started as a proof of concept in September 2026. It is now a working ecosystem: plugins are released by their
authors, listed in the catalog, and installed by people on their own units.

- **Plugins you can install today**: synths, samplers, drum machines, sequencers, an amp simulator and a record-digging
  streamer, from several authors. Among them are Dexed (DX7), JV-880, Acid, Maze Voice and Maze Sequencer, Crate Digger,
  Plaits and NAM, plus **Build it yourself** ports (Monomodule, Machinemodule) for engines that need your own firmware.
  The [catalog](https://sd88me.github.io/mpc-vst-plugins/) has the current list and versions.
- **A release you can trust.** Every release is built in CI on a pinned toolchain, checked against the catalog's rules
  (layout, checksums, glibc and CPU limits), smoke-tested on a real device and only then published. Each version
  shows its SHA-256 and what it was tested on.
- **MPC OS 2.x and 3.x, labelled per release.** Plugins are built against glibc 2.31, so they load on older firmware
  (glibc 2.32, e.g. MPC OS 2.15) as well as current (2.39). The catalog checks each release's library and skin and labels it
  **MPC OS 2.x + 3.x** or **MPC OS 3.x only**; the installers warn before putting a 3.x-only plugin on a device that looks
  like 2.x. Every release so far (2026-10) is 3.x only: whether to publish a 2.x-capable skin is up to each plugin's developer.
  A plugin that needs more than 2.32 (up to 2.36) is listed as 3.x only; the catalog refuses more than 2.36.
- **Tested on a Force** (MPC OS 3.9.1) as the reference device. Other Gen1 MPC OS devices (Live and Live II, One, X,
  Key 61) run the same `MPC` program. A user's MPC One on MPC OS 2.15 is what led to the glibc 2.31 builds; reports
  from other models are welcome. Gen2 devices (e.g. Live III) are reported to be more locked down.

What the plugins can do:
- **Instruments and effects** that play from pads, keys and MIDI clips, with Q-Links, automation, and settings saved
  in the project.
- **Custom touchscreen pages**: knobs, switches, buttons, option selectors, pop-up lists, live text readouts and
  artwork, in the same style as the Force Shadow pages many were ported from.

What the tools can do:
- **A porting kit**: describe an engine's parameters in one small file and the tools build the plugin, its page and
  its Q-Link map, test it on a PC, check its CPU cost on the device, and package it as a shareable zip with an
  installer.
- **A release workflow** (`vst-release.yml`): a reusable GitHub Actions workflow that builds, tests, previews and
  packages a port into a draft release; you test the draft zip on a device, then publish.
- **Skin Studio**, a page editor in your browser: double-click `SkinStudio.command` (macOS), `SkinStudio.bat`
  (Windows) or `SkinStudio.sh` (Linux). It needs Python 3. See [docs/SKIN_STUDIO.md](docs/SKIN_STUDIO.md).

## How it works

1. **The plugin** is a small Linux library (`.so`) built for the device's ARM processor. It goes in the plugin's own folder in `/sdcard/Synths/`, next to its skin and data.
2. **MPC finds it** through its settings file: one line per plugin in `MPC.settings` tells MPC where the file is and
   what it's called. MPC reads that list at startup and shows the plugin in its plugin browser.
3. **Its page** is the skin in that same folder (`Plugin Skins/`), in the same format Akai uses for its own plugins: a JSON
   description of the controls plus PNG artwork. Each knob or button is bound to one of the plugin's parameters, so
   MPC draws and drives the page itself; the plugin just reports values and their text.

This repo's tools make all three. A port says what its engine is and what its parameters are; the wrapper turns the
engine into a VST2 plugin, and the skin tools draw a page for it, either laid out automatically or from a layout you
design.

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

## What's possible

- Synths, samplers, drum machines and effects ported from existing C/C++ engines. Engines written for Ableton Move's
  Schwung host build unchanged through an adapter.
- MIDI generators (sequencers, arpeggiators) that play other tracks, synced to MPC's tempo.
- App-like plugins: things that fetch from the web, stream, or write files that MPC's browser can open.
- Pages with pop-up option lists, panels that change with a mode, live readouts, and your own look: any font,
  knob style, gradient or shadow, and artwork drawn in Inkscape, baked into the page.
- Presets in MPC's PRESET menu, from the engine's own preset parameter or a `presets.json` (the menu listing and loading
  checked on a Force; offline-tested otherwise). CC 20-35 and NRPN control from MIDI (offline-tested only so far).
- Updating a plugin without restarting MPC: replace the file, remove every copy from the project, insert it again.
- Shipping a plugin as one zip with an install script.

## Limitations

- **MPC OS 2.x needs a compatible skin.** A plugin marked *MPC OS 3.x only* loads on 2.x and plays from the Q-Links, but its
  touchscreen page stays empty until its developer releases a version with a compatible skin. See
  [MPC OS 2.x vs 3.x](#mpc-os-2x-vs-3x).
- **VST2 only.** MPC OS has no VST3 or LV2 support.
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

What's next is in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Technical details

### Documentation

- [docs/NOTES.md](docs/NOTES.md): everything verified on hardware, with dates, plus open issues. The source of truth.
- [docs/PORTING.md](docs/PORTING.md): the checklist for turning an engine or app into a plugin.
- [docs/SKIN_STUDIO.md](docs/SKIN_STUDIO.md): laying out and previewing pages.
- [docs/BENCH.md](docs/BENCH.md): the on-device CPU check. [docs/RELEASING.md](docs/RELEASING.md): release zips.
- [docs/ROADMAP.md](docs/ROADMAP.md): repo features still to do.
- [docs/OS2_SKINS.md](docs/OS2_SKINS.md): the MPC OS 2.x skin findings, the shape table, the plan and its open questions.

### Device details

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

### MPC OS 2.x vs 3.x

What differs, and what the catalog does about it (checked on an MPC Live on 2.15.1 and a Force on 3.x; details and dates in
[docs/NOTES.md](docs/NOTES.md), the plan and open questions in [docs/OS2_SKINS.md](docs/OS2_SKINS.md)):

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
  (the reasons show on hover). Developers do not declare it. It is a check against one 2.x version's own skins, not a test on a
  2.x unit, so a plain "2.x" badge also needs a 2.x device test listed.
- **For developers: opting in is optional.** To make a plugin 2.x-capable, write its skin in the 2.x shape, check it with
  `python3 tools/skin_compat.py check "<skin>/Plugin Skins/TUI.json" "<skin>/Plugin Skins/Q-Links.json"` (it lists what still
  stops 2.x) and publish a new release; the label changes by itself on the next catalog build. Releases that are not
  re-released stay listed as 3.x only. The skin generator writes the 2.x shape when built with `SHADOW_SKIN_MPC_OS=2` (docs/PORTING.md); a plugin written by hand needs the table in docs/OS2_SKINS.md.

**Help us:** tell us your model, your MPC OS version (Settings), whether a plugin's page appeared, and what the
screen shows. If you are comfortable in a terminal and on 2.x, the output of this read-only command is very useful:
`cat /usr/share/Akai/Content/Synths/*/'Plugin Skins'/TUI.json | grep -o '"version": *[0-9]*' | sort | uniq -c`.

### Layout

- `wrapper/vst2_wrap.c` + `wrapper/engine.h`: a generic VST2 wrapper around a small engine interface
  (create, MIDI, string parameters, 128-frame int16 render). Link it with any engine plus a generated `params.h`.
- `adapters/`: engines written for other hosts, mapped onto that interface without code changes
  (`adapters/schwung/`).
- `tools/build_port.sh` + `tools/gen_vst.py`: the generic port builder. An engine ports with one small
  `vst.json` (name, uid, parameters, sources, optional layout) and no wrapper code: `tools/build_port.sh path/to/vst.json`
  makes the `.so`, the skin and the `pluginList` entry. See [docs/PORTING.md](docs/PORTING.md).
- `tools/shadow_skin.py` + `tools/shadow_art.c`: build a skin from a Force Shadow style layout
  (`shadow_page.conf` widget syntax: frames, knobs, toggles, triggers, option segments, pop-ups, plus
  `qlinks` lines for nested pages). The artwork (backgrounds, knob filmstrips, button states) is drawn by
  [force-shadow](https://github.com/sd88me/force-shadow)'s own renderer, so the MPC page matches the
  shadow page pixel for pixel. That renderer is vendored in `tools/vendor/force-shadow/`, so no force-shadow
  checkout is needed.
- `tools/html_art.py` + `tools/html_art/`: the optional browser renderer for skin artwork (`"art": "html"`):
  the same layouts drawn as SVG/CSS in headless Chromium, restyled per port with a stylesheet.
- `tools/skin_check.py`: checks a built skin for overlapping touch areas, controls off the screen, Q-Links on hidden
  parameters and switches missing options; `gen_vst.py` runs it after every build.
- `tools/studio.py` + `tools/skin_template.svg`: the skin studio. Auto-layout from a port's
  parameters, a browser editor (`studio.py serve`, `tools/studio_web/`, started by the `SkinStudio.*` launchers), an
  Inkscape/Penpot SVG round trip, and page previews. Controls can use built-in looks or your own images and
  filmstrips (`tools/skin_assets.py`). See [docs/SKIN_STUDIO.md](docs/SKIN_STUDIO.md).
- `tools/test_port.sh` + `tools/host_test.c`: the offline x86 test of a port under ASan (instances, params, options,
  popups, MIDI→audio, legacy `process()`, chunks), PASSED/FAILED.
- `tools/bench.sh` + `tools/bench.c`: a CPU stress test run on the device, with a PASS/WARN/FAIL verdict for Gen1
  hardware. See [docs/BENCH.md](docs/BENCH.md).
- `tools/desktop/`: the MPC plugin installer app (Go; a local web page that installs, updates and removes plugins over SSH).
- `tools/mpc-store.sh`: the same install, update, remove, prune and sync from a shell on the device, for the catalog's one-line command.
- `tools/release.py`: packages a plugin as one shareable zip with an installer, an uninstaller and generated
  INSTALL.md. See [docs/RELEASING.md](docs/RELEASING.md).
- `tools/probe_device.sh`: a read-only device report (CPU, 32/64-bit MPC, audio threads, plugin formats: VST2 yes,
  VST3 no on current firmware).
- `poc/gain.c`, `poc/synth.c`: minimal effect / instrument examples.
- `poc/midiport.c`: a MIDI-generating plugin (tempo-synced) that drives other tracks through an ALSA port
  (MPC OS ignores VST MIDI output; `poc/midiout.c` shows that).
- `poc/menuprobe.c`, `poc/textprobe.c`, `poc/netprobe.c`: the probes behind the picker, live-text and
  network findings in NOTES.

## Credits

The route was first described on the MPC-Forums thread
"Proof of Concept: Custom Standalone Plugins" (Sep 2026) by NoQuestion and dustyslices.
[Schwung](https://github.com/charlesvestal/schwung) by @charlesvestal, the open module platform for Ableton Move,
inspired a good part of how this project is built: the small engine interface that our wrapper and the
`adapters/schwung` adapter follow, the build, test and release workflow for modules, and the catalog model (a registry
of plugins, releases found on GitHub, a static catalog site, and installer apps that fetch from it). We looked at how
Schwung does these things and made our own versions for MPC OS; thank you for building it in the open.

Credits also to the MockbaMod community for assistance in development, especially @Locrian.

## Legal

The code in this repository is under the MIT licence (see [LICENSE](LICENSE)); vendored third-party files keep their own licences.

VST2 is a deprecated Steinberg format; this project uses a hand-written ABI
header and is for personal, non-commercial experimentation on hardware you own.
No Akai content is redistributed. Editing `MPC.settings` is at your own risk; back it up first.
