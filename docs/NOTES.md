# Notes: native VST2 plugins on MPC OS standalone

Origin: mpc-forums thread "Proof of Concept: Custom Standalone Plugins"
(viewtopic.php?f=48&t=220981, Sep 2026). Verified on a Force (MPC OS, with MockbaMod) 2026-09-23; paths below are
from the Force and may differ on MPC Live/One/X/Key (e.g. `Force Documents` vs `MPC Documents`).

## Facts (verified)

- `/usr/bin/MPC` contains `"pluginList"` + `"-arm"`, `KNOWNPLUGINS`, `VSTPluginMain`.
- Settings: `/media/az01-internal/Settings/MPC/MPC.settings`. Edit **with `acvs`
  stopped**; back it up first (malformed XML ⇒ MPC resets it to defaults).
- Entry format:
  `<PLUGIN name="X" descriptiveName="X" format="VST" category="Synth|Effect" manufacturer="V"
  version="1.0" file="/sdcard/vst/x.so" uid="<hex uniqueID>" isInstrument="0|1" fileTime="0"
  infoUpdateTime="0" numInputs="2" numOutputs="2" isShell="0"/>`
- Device: armv7l, glibc 2.39 on MPC OS 3.x (2.32 on MPC OS 2.x). Build with an older glibc: `arm32v7/gcc:11-bullseye` (2.31) is what
  `build_port.sh` uses since 2026-10-02; `arm32v7/gcc:12` (2.36) binds some pthread symbols to `GLIBC_2.34` and does not load on 2.x.
- Audio: 44100 Hz, 128-frame period; the engine interface (`wrapper/engine.h`) renders in exactly those blocks.
- AEffect magic must be `'VstP'` (0x56737450). **The forum snippet's magic is wrong.**
- Instruments: set `effFlagsIsSynth`, category 2, answer `effCanDo "receiveVstEvents"`;
  MIDI arrives via `effProcessEvents`.
- Tempo: `audioMasterGetTime` with `kVstTempoValid` works for synced LFOs.
- State: `effFlagsProgramChunks` + `effGetChunk`/`effSetChunk`.
- Skin search path is `SynthContentLocations` in MPC.settings; `/sdcard/Synths` is one of them
  (also `/media/662522/Synths`, `/usr/share/Akai/Content/Synths`).
- Skin folder name `<manufacturer> - VST - <plugin name>` matched. Reference skins:
  `/usr/share/Akai/Content/Synths/*/Plugin Skins/` (e.g. Decimator = simple, Bassline = 4 tabs,
  knobs + `btnBypass` + `slider` + `comboBox` + `Label` + `Focus`).
- `importFiles` in `TUI.json` resolve relative to the skin; use absolute
  `/usr/share/Akai/Content/Synths/...` paths when the skin lives elsewhere.
- Component library: `AKAI Components/AKAI Generic Components.json` (knobBlack/Blue/Green/Grip/
  Point/Red/Silver/Witch/Yellow). Bassline defines its own `btnBypass`, `comboBox`, `slider` locally;
  that's where to copy switch/button/menu definitions from.
- Gen2 (offline, 2026-10-09, from the MPC OS 3.9.1 Gen2 update image's main rootfs, not a device): userland is aarch64 only, `/usr/lib/libc.so.6` is
  GNU libc 2.39, so a Gen2 plugin is a separate aarch64 build with a 2.39 glibc ceiling. See `docs/GEN2.md`.

## Open issues (reviewed 2026-09-25)

1. Note timing is quantised to 128-frame DSP blocks (the engine interface renders whole blocks; MIDI lands
   at the start of the next one).
2. **MIDI-output plugins: MPC OS ignores plugin MIDI out** (tested 2026-09-23 with `poc/midiout.c`).
   MPC never asks canDo `sendVstEvents`/`sendVstMidiEvent` (only `receiveVstMidiEvent`, `bypass`);
   `audioMasterProcessEvents` is accepted silently and the events go nowhere. A plugin can't be picked as
   a MIDI input on another track, and the track's "MIDI send to" only forwards the notes coming *into* it.
   Transport/tempo via `audioMasterGetTime` do work (flags 0x7fc4, tempo and ppqPos valid), and so does MIDI in.
   **Workaround, verified 2026-09-23 (`poc/midiport.c`):** the plugin opens its own ALSA sequencer client/port
   (`snd_seq_create_simple_port`, CAP_READ|SUBS_READ; link `-lasound`, which ships with MPC OS) and sends notes
   with `snd_seq_event_output_direct`, synced to host `ppqPos`/tempo. MPC's own seq client ("MPC") hot-detects the
   new port, creates a matching input ("<client> <port>") and connects it with no restart. Enable Track on it in
   Preferences → MIDI, then any track can select it as MIDI input. Plugin sequencers/arps can drive other tracks.
   **Force, 2026-10-08 (device):** Maschine Group opened client 130 / "MIDI Out" and MPC subscribed
   (`129:6 "Maschine Group MIDI Out"`), but `MidiDevices.AutoEnableForTracks` was `0` and the port was
   absent from `MidiDevices.Table`. Rec wrote no clip events until that input was Enable Track. Do not
   flip AutoEnable globally on a unit that already has a long MIDI table; add this one port with
   `track: true` or turn Enable Track in Preferences.
   **Maschine Group kit switch (offline, 2026-10-08):** loading another group keeps Empty if Empty was
   selected; if any other pattern was selected, the new group starts on its first pattern.
   **Maschine Group scan (offline, 2026-10-08):** the default walk is only the plugin `groups/` folder.
   Walking `/media` and `/sdcard` listed leftover `.mxgrp` files from the user's own library (a Flumex
   kit under `/media/MPC/M8`) that nobody put in the plugin. Setup → Change folder / Refresh is how a
   copied `Groups/` + `Samples/` tree is added. A group/pattern row tap that arrives as 0 is ignored so
   the automate-off echo of the previous row does not unload.
   **Maschine Group Change folder (offline, 2026-10-09):** `tsize=` + `get=help_6` put a Titillium Value
   label on top of the button, remapped to the help string. The tap set that string param, not
   `root_pick`, so the button did nothing. Skin: a near-invisible hit plate on top of the caption,
   Mouse Down → Toggle Switch, pressed fill `theme_accent`. Needs an MPC restart to load the skin.
   **Maschine Group folder browser (offline, 2026-10-09):** Change folder and Use folder shared
   `root_pick`, so the same press opened the list and immediately committed (empty place list =
   close). Use folder is now `root_use`, and commit is ignored for ~350 ms after open. Refresh
   has no arrow glyph. Folder rows use a lighter tile fill (`color=2a2622`).
   Most likely stock MPC OS behaviour: MockbaMod's MidiLoop (`tkgl_anyctrl_lt.so`) only filters or blacklists
   ports; it doesn't create them. **Still unconfirmed on a stock unit.** Latency is about one audio block
   (direct, unscheduled send).

Resolved (details in the sections below): option params render as image-button radio groups or `popup`s,
not knobs, and `comboBox` menus stay empty for VST2 (see "Native picker"); knob names come from `Label`
`"type": "Name"`; the port builder is generic (`tools/build_port.sh` + `vst.json`, 2026-09-24); custom
layouts render on device (every port since Maze Voice).

## Skin layout facts (verified 2026-09-23)

- Nested pages: several `tabs` entries with the same `fnKeyIndex` and `fnKeySubIndex` 0,1,2…; Q-Link map
  entries use `Tab` = fnKeyIndex+1, `SubTab` = fnKeySubIndex+1 (as in stock DrumSynthMulti).
- Q-Link numbering: the 4x4 grid counts from the bottom row up (stock: top-left control = Q-Link 13). With
  `Bank Direction: Column`, the Force's 8 knobs read bank 1 = Q-Links 13,9,5,1,14,10,6,2 and bank 2 = those +2.
  `gen_vst.py` lays each page out as 2 rows of 8 (row = knob bank) and maps through that order.
- Custom geometry (2026-09-23): `tools/shadow_skin.py` takes a Force Shadow style layout file per port
  (Maze: `mpc-vst-maze/vst/layout.conf`) and emits `TUI.json` with free placement, a per-tab
  background image (frames and labels baked in), a knob filmstrip per radius (128 frames, `numFrames` 127, as in
  stock strips), and on/off images for toggles, triggers and option segments. Shadow canvas y 86..714 maps to the
  1280x628 plugin area. Several `qlinks` lines in one tab become nested pages that share the design but have
  different Q-Link sets. Values are MPC `Label` `Value` components (Titillium; the baked labels use the shadow font).
  Seen on device with every port since.

**No per-plugin "save preset" UI for a VST2 instrument (verified on a Force, 2026-09-27, Monomodule One).**
Saving the whole track Program works and round-trips the plugin's chunk (so the sound is preserved), but MPC has
no separate "save this plugin's preset" action the way it does for native instruments -- the user tried two ways to
reach one and found neither. So a VST2 port's own in-skin preset browser (like Monomodule One's PRESET strip) is
still the only way to give users a browsable, swappable *sound* library shorter of a whole Program; MPC's Program
save/load is the mechanism for keeping/recalling one sound, not for organizing many.

## Beyond synths: apps as plugins (probe run on a Force 2026-09-24)

A VST2 plugin is ordinary native code inside the MPC process, which has root, the network and the
filesystem. force-shadow (LD_PRELOAD in the same process) already makes HTTP calls and writes files from there,
so a plugin should be able to as well. `poc/netprobe.c` checks this on a device: DNS + HTTP, a file write into the
documents folder, `posix_spawn` of `/bin/sh` and of a script on /sdcard (noexec check). Log: `/tmp/netprobe.log`.

Rules for app-like plugins:
- Never block the audio thread: network, disk and child processes go on a worker thread; audio goes through a ring buffer.
- Spawn children with `posix_spawn` (vfork-style), not `fork()`: forking MPC's large, multithreaded,
  real-time process copies its page tables (audio dropouts), and only async-signal-safe calls are allowed before exec.
  The webstream/cratedigger core uses `fork()` in two places (yt-dlp daemon, ffmpeg pipe), so switch those.
- A plugin crash takes MPC down with it, so risky parts (yt-dlp/Python, ffmpeg) belong in a child process.
- UI is only the skin: parameters with display strings, static images, buttons. No text entry, no dynamic lists or
  images. Dynamic text works through parameter display strings, e.g. "Result 1..8" slot params whose value text
  is a track title, and filter enums for genre/style/decade.
- Files the plugin writes appear in MPC's browser; the plugin can't tell MPC to load a program.

Probe results (Force, MPC OS + MockbaMod, 2026-09-24): the plugin runs as **uid 0**. DNS + HTTP work
(example.com 200; api.discogs.com answers 301 to HTTPS, so real APIs need TLS). Writing to
`/sdcard/Force Documents/` works. `/sdcard` is ext4 mounted rw with exec allowed.
**Spawning children:** `posix_spawn` itself works, but the child inherits MPC's environment, and on MockbaMod
units that includes `LD_PRELOAD` of C++ libraries (mockbaMagic.so, tkgl_anyctrl_lt.so) that fail in a plain
process ("undefined symbol _ZSt4cout", exit 127). Always spawn with a cleaned environment (drop LD_PRELOAD).
Stock MPC OS has no such preload.
- HTTPS: MPC OS ships `/usr/lib/libcurl.so.4` (8.x), `libssl.so.3` and `libcrypto.so.3`, so a plugin can `dlopen("libcurl.so.4")` for HTTPS without bundling TLS.

## Dynamic text in skins (verified on a Force, 2026-09-24, `poc/textprobe.c`)
MPC polls parameter **value text** (`effGetParamDisplay`) by itself: a counter the plugin changes with no
notification at all ticks live on a `Label` `Value`. Parameter **names** (`Label` `Name`) also update live when the
plugin calls `audioMasterUpdateDisplay` (opcode 42). So readouts (status, time, now playing), filter names and
result lists can be plain parameters whose display text the plugin changes. Name changes without
UpdateDisplay are untested; call it whenever a name changes.

## Skin studio text: readability findings (2026-09-24, building the jv880 port)
- `label_cmds()`'s baked text (knob/toggle/slider/enum_h/enum_v names) and `shadow_art.c`'s
  `seg`/`button` commands, plus `render_conf_preview.c`'s `frame_box()`/`widget_button()` titles, all
  used a fixed 1.5x scale on the 9x9 bitmap font (`font8x8.h`). That font DOES have lowercase
  (`font_chars` includes a-z), but converted layouts that kept the original all-caps shadow_page.conf
  labels ("CUTOFF", "TVF DEPTH") at 1.5x read as too wide/shouty. Fixed by lowering the scale to 1.15
  everywhere it's used (`shadow_skin.py`'s `LABEL_SCALE`/`text_width`, `shadow_art.c`'s `seg` command,
  and `render_conf_preview.c`'s `frame_box()`/`widget_button()`) and switching generated label/title/
  option text to Title Case (an acronym allowlist keeps e.g. LFO/TVF/FXM from becoming "Lfo"/"Tvf").
  `render_conf_preview.c` is mpc-vst's actual skin-asset renderer (shadow_art.c `#include`s it), not a
  preview-only tool here, but it's a separate hand-ported copy from force_shadow.c's own on-device
  renderer, so this change doesn't touch the real Force's live rendering.
- A long `enum_h` option row (e.g. an 8-option reverb TYPE) reads cramped in one row; wrapping to
  `rows=2` (already-supported layout.conf syntax) once options exceed ~6 fixes it.
- An `env`-style bar/knob group (or any control whose *component bounding box* is taller than its own
  visible art, e.g. a slider's box padded for its value-label text below) must be positioned by that
  box's real height, not by eyeballing the visible art's center — sizing off a frame's own content
  area (skip its title+divider band, ~44px) and computing the component center from the box height
  keeps it from poking into the frame's title text. Diagnosed by comparing a skin's baked `sh_bg_N.png`
  (correct) against `tools/studio.py preview`'s composited output (showed the corruption) — the studio.py
  preview pastes each component's real filmstrip art at its real bounds, so it catches oversized-bounds
  bugs invisible in the background PNG alone.

## Control names: native Label "Name" beats baked bitmap text (2026-09-24)
The font-scale/Title-Case fixes above (previous entry) still read as "monospace" for real words:
`font8x8.h`'s glyphs mostly fill their whole 9-column cell, so trimming the advance to each glyph's
actual ink width (also tried) barely helped -- the letterforms themselves are blocky pixel art, not a
real typeface, so no amount of scale/advance tuning gets genuinely "normal typed font" spacing out of
it. The real fix: MPC's own native `Label` `"type": "Name"` component (same mechanism as the existing
`"type": "Value"` one) shows the assigned parameter's name using MPC's own on-device Titillium Web
font -- real proportional metrics, rendered by the device itself, zero relation to shadow_art.c's
baked font. `shadow_skin.py`'s knob/toggle/slider_v/slider_h defs now include a `_name_label()` sub
alongside the existing `_value_label()`; `label_cmds()` no longer bakes text for those three kinds
(it still does for frame titles and enum_h/enum_v's own group label + per-option segment text, none of
which bind to a single parameter index the way Name/Value can).
Consequence: `tools/studio.py preview` couldn't show this at all (it only drew an outline box for any
`Label`, since it has no access to a real on-device font) -- upgraded it to render actual text for
`Name` labels via Pillow's own bundled scalable font (`ImageFont.load_default(size=...)`, present in
Pillow 10.1+; the `python:3.11-slim` container's `pip install pillow` pulls a recent enough one). Not
pixel-identical to Titillium Web, but proportional and good enough to sanity-check spacing/overlap
offline before ever touching a device.

## Real-device findings from the jv880 skin's first hardware test (2026-09-24)
A screenshot of the actual device (not the offline `studio.py preview`, which can't catch these)
turned up two more bugs, both now fixed:
- **Stepper arrows showed the word "Button"** literally overlapping the arrow glyph. A `_button()`
  with `onImage`/`offImage` = `""` (no asset) makes MPC render a generic placeholder caption instead
  of nothing. Fixed by cropping the arrow glyph already baked into that tab's background (drawn by
  `widget_stepper`/`dot_stepper`) as the tap-zone's own image, instead of an empty string.
- **MPC's bottom function-key tab strip is genuinely unreadable with long qlink bank names.** Nested
  `qlinks "<name>" = ...` banks (multiple sub-pages per tab, docs/PORTING.md) each set that sub-page's
  name in MPC's own tab strip -- and that strip is not sized for 20+ character names, even
  truncated: on device it read as one unbroken, mid-word-truncated run-on across the whole strip
  ("OUTPUT + MACROS (OF CONTROL + BEND / POR TONE 1 WAVE / PITCH + ..."). Stock skins (single qlinks
  bank per tab, e.g. Maze) never exercise this since they only ever show ONE short tab name. **Keep
  every qlinks bank name short (one or two words, no concatenated frame titles)** -- jv880 uses
  "Play"/"Sends", "Patch"/"FX", "Tone N"/"Env N"/"LFO N".

## String-valued display params showed "0" (2026-09-24, jv880: bank/patch name readouts)
`vst2_wrap.c`'s `effGetParamDisplay` unconditionally reformatted every parameter's `get_param()`
string through `atof()` + `snprintf("%.*f", ...)` -- fine for a real numeric display ("63.5"), but
it silently destroys any non-numeric string (a bank name, a patch name, a status message) down to
whatever leading digits `atof` can parse, which for text like "Preset A" or "A.Piano 1" is nothing,
hence the field just showed "0". Fixed with an explicit opt-in: `param_t` gained a `string_display`
field (`gen_vst.py`, from a parameter entry's `"display": "string"`), and `effGetParamDisplay`
copies the DSP's string straight through when it's set instead of reformatting it. Verified against
real ROMs on x86 (`patch_name` -> `'A.Piano 1   '`, `bank_name` -> `'Preset A'`) before redeploying.
A second, related bug: a `stepper`'s displayed text was hardcoded to the SAME parameter it Q-Link
steps (e.g. jv880's numeric `preset` index), when the design wants a DIFFERENT parameter's text
(`patch_name`) shown instead. Fixed by giving `stepper` an optional `get=<key>` attribute (mirroring
Force Shadow's own shadow_page.conf attribute of the same name, dropped during the jv880 conversion)
that binds the text label to its own `"Text"` handle (`_placed()`'s `extra=` param) independent of
the stepper's own `"Data"` handle -- so the arrows/Q-Link still nudge `preset`, but the center text
shows `get_param("patch_name")`.

## bench.sh understates real cost for plugins with a real-time-paced background thread (2026-09-24)
jv880's real synthesis work happens on its own thread (`jv880-emu`), which paces itself against the
actual wall clock to keep a small ring buffer full for real-time playback -- not against how many
`render_block()`/`processReplacing()` calls have happened. `tools/bench.c` has no `sleep`/pacing
anywhere: it calls `processReplacing()` back-to-back as fast as the CPU allows, so a stage that's
*supposed* to represent ~1s of real playback can complete in a few ms of actual wall-clock time. The
background thread, pacing itself to the real clock, sees almost no elapsed time and does almost no
work in that window -- but `threads%`'s formula (`(proc - self) / (nblocks * BUDGET_US)`) divides by
the *real-time-equivalent* duration regardless of how little wall-clock time actually passed, so the
true cost gets divided away to near-zero. Measured on the device: `tools/bench.sh` reported
0.2-0.5% "threads%" for jv880 (a clean PASS), but sampling the real `jv880-emu` thread's CPU ticks
via `/proc/<pid>/task/<tid>/stat` against `/proc/uptime` while it was actually loaded on a track and
playing gave **20.8% of one core, sustained** -- roughly matching force-jv880's own "2.81x real-time"
claim (`1/2.81 ≈ 36%`), and nothing like the bench's number. This is exactly the class of plugin
docs/BENCH.md's own "Limits" section already warns about ("app-style plugins... do their real work in
worker threads... watch `top` on the device instead") -- jv880 just wasn't recognized as fitting that
category until checked directly. **For any port whose real work runs on a background thread paced to
the wall clock (not to render_block() call count), don't trust `bench.sh`'s `threads%` at all** --
sample the real thread's ticks on the device during actual playback instead:
```
u1=$(awk '{print $14}' /proc/<pid>/task/<tid>/stat); s1=$(awk '{print $15}' ...); t1=$(awk '{print $1}' /proc/uptime)
# ...play for N seconds...
u2=...; s2=...; t2=...
# cpu% = (u2-u1 + s2-s1) / 100 (ticks/sec, usually HZ=100) / (t2-t1) * 100
```
Update 2026-09-27 (jv880 v1.0.0, Force): sampling the same thread gave 19.8-19.9% of one core with no notes
and 46.8% over 30 s of chords and held notes. `bench.sh` still passed with p99 3.3% and reported the thread at
2.4%. The thread cost is not fixed: it rises while notes sound.

## Qlink curation for tabs with >16 controls (2026-09-24, jv880 port)
A tab with more controls than one 16-key Q-Link bank needs several `qlinks "<name>" = ...` lines
(already-supported nested-page mechanism, docs/PORTING.md). A naive "first 16 in source order"
split is a bad default for a busy tab: it silently drops every control past the 16th and often grabs
all of one section while missing others entirely (e.g. a Tone tab's Pitch Env only, missing Filter/
Amp Env and both LFOs). Better: group by FRAME first (accumulate whole frame-sections into a bank
until the next one would push past 16, then start a new bank named after the section(s) it holds),
so every control ends up in some bank and each bank reads as one coherent area (e.g. jv880's Tone
tabs split cleanly into "Wave/Pitch + Pitch Env" / "Filter Env + Amp Env" / "LFO 1 + LFO 2", 44
controls in 3 evenly-sized banks instead of losing everything past the first section).

## Stepper "_prev"/"_next" needs a real DSP verb, or a step_of/step_delta opt-in (2026-09-24, jv880)
A stepper's arrows were bound to "<key>_prev"/"<key>_next" as if the DSP understood those literal
keys as increment/decrement verbs -- it doesn't have to. jv880's `preset` has no such verb (only an
absolute `set_param("preset", N)`), so the arrows silently did nothing (confirmed on device, then
root-caused and fixed before touching it again). Two independent fixes, both needed depending on
what the DSP actually offers:
- **A real verb under a different name** (jv880's bank: `next_bank`/`prev_bank`): give `stepper` an
  explicit `prev=<key>`/`next=<key>` override (mirrors Force Shadow's own shadow_page.conf attribute
  of the same name) so the arrows call the real verb directly, while the stepper's own `key` can be
  an inert dummy (Q-Link nudge on it is a no-op).
- **No verb at all** (jv880's preset): a param can declare `"step_of": "<key>", "step_delta": N`
  (gen_vst.py, -> `param_t.step_target`/`step_delta`) to nudge that OTHER param by a fixed amount
  instead -- the wrapper reads its current value straight from the DSP, adds the delta, clamps to
  its min/max, and sets it back. This trigger's own key is never sent to the DSP at all.
Verified against real ROMs on x86 before redeploying: `preset_next` x3 advances the patch (name
text updates each step), `preset_prev` reverses it, `next_bank` switches banks with `patch_name`
updating to match.

## Q-Link banks used to share one screen; frames must stay atomic across banks (2026-09-24, jv880)
Every Q-Link bank of a multi-bank tab rendered the SAME screen -- only the physical Q-Link mapping
differed underneath (`build()`'s `componentsData` was one `kids` list built once per TAB and reused
for every bank's page def). Fine for a stock skin that only ever uses one bank per tab, but not a
real multi-page design (confirmed via user feedback + an offline preview: Play/Sends both showed
Output+Macros+Effect Sends together). Fixed: widgets are grouped into frame-based segments, and each
bank's page gets its OWN background + component list, containing only the frame(s) that have a key
in that bank (a `persistent=1` readout/stepper, e.g. a tab-level bank/patch bar, opts into every
bank without needing its own frame). This makes frame membership a hard constraint: `make_banks()`
(the port's own converter) must never split one frame's keys across two banks, or `build()`'s
"include a frame if ANY of its keys are in this bank" rule pulls the WHOLE frame into both (found
exactly this way: Effect Sends' reverb key had been grouped into the Play bank, so the Sends bank,
which had the frame's OTHER keys, showed the whole frame too -- chorus/tones included).

## Optional real-TrueType frame titles (2026-09-24, jv880)
shadow_art.c's baked 9x9 bitmap font, even Title-Cased and tightened (see the font-spacing entries
above), is blocky pixel art, not a real typeface -- there's a ceiling on how good "normal typed
spacing" can look baked that way. `vst.json`'s optional `"title_font"` (a `.ttf`/`.otf` path) makes
`shadow_skin.py` draw frame titles with a real font via Pillow instead: the background script emits
`frameblank` (box only, no baked text) and a PIL pass draws the title afterward once the PNG exists.
Off by default (`SHADOW_TITLE_FONT` unset) -- every existing port keeps its exact current look.
Google Fonts' GitHub repo (`raw.githubusercontent.com/google/fonts/main/ofl/<name>/<Name>-Regular.ttf`)
is a reliable direct-download source when `fonts.google.com/download` itself returns an HTML page,
not a zip, for the same request.

## A static param bound silently clamps a value the DSP tracks dynamically (2026-09-24, jv880)
`preset`'s declared VST range was `min=0, max=127` (an early guess, back when only internal patches
were being tested). The real total is 4133 once all 19 SR-JV80 expansions are loaded on this
device (`get_param("total_patches")` has the live number). Any patch index above 127 -- which is
almost every expansion-backed patch, since internal-only patches stop at 191 and expansions start
past that -- got silently CLAMPED back to 127 by the step_target mechanism's own
`if (cur > tp->max) cur = tp->max`, landing in "Preset B"'s own internal-bank range. From the
user's side this read as "stepping patches while in an expansion keeps reverting to Preset B" --
a real, reproducible bug, not a display glitch, and the DSP's own num-patches count was never wrong;
only the WRAPPER's static idea of the param's range was. Same caveat as `expansion_index`'s
declared range: a VST param's bound is fixed at build time, but the real count is device/ROM-set-
dependent, so this needed a generously oversized static max (8191), not the exact number -- a
future refinement could read the live count via `get_param("total_patches")` at clamp time instead
of trusting the static declaration, for a port where this matters more precisely.

## A readout bound elsewhere (get=) needs audioMasterUpdateDisplay to ever refresh (2026-09-24, jv880)
Found live on a real device: patch_name/bank_name-style readouts (a stepper's get= binds its
displayed text to a DIFFERENT param than the one it steps, via a separate "Text" handle -- see the
"shows 0" entry above) painted correctly ONCE, then never updated again, regardless of whether the
underlying param changed via the stepper's own arrow tap or a direct Q-Link turn on the stepped
param. Root cause: such a readout is deliberately given a degenerate min==max range (its own
reported normalized value never changes, since nothing should ever Q-Link-nudge it meaningfully),
so MPC has no value-change signal telling it to re-poll THAT param's display text just because some
OTHER param changed it indirectly -- there's nothing to notice.
`audioMasterUpdateDisplay` (opcode 42) is the fix, already documented above as refreshing a Label
"Name" -- calling it makes MPC re-poll everything currently displayed, sidestepping the fact that it
has no way to know get='s cross-parameter dependency exists. **Not safe to call directly inside
setParameter()** though: this repo's wrapper already has an established rule against re-entering the
host from inside its own call to us (`w->release[]`'s existing comment, same reasoning -- momentary
triggers already defer their own `audioMasterAutomate` call to `processReplacing()` for exactly this
reason). Added a `need_update_display` flag alongside it, consumed the same way: coalesced to at
most one `audioMasterUpdateDisplay` per audio block, regardless of how many params changed within
it. Worth remembering for ANY future `get=`-bound (or otherwise cross-parameter-dependent) readout:
it needs this call somewhere, or it will only ever show its initial value.

## A continuously-nudgeable control on a synchronous, expensive DSP action can "hang" the plugin (2026-09-24, jv880)
Reported on device as "banks and patches hanging, says loading emulator". Root cause: jv880's
`jump_to_expansion` does a synchronous 8MB `memcpy` (plus a first-access disk read+unscramble --
measured ~900ms against real ROMs) with no debounce, and it was bound to a plain continuously-
nudgeable `knob`. One touch/turn gesture can fire several `setParameter` calls in quick succession
(each a real, distinct value along the drag), so a single knob nudge could queue up multiple ~1s
synchronous DSP calls back to back -- easily several real seconds of apparent hang. Notably, the
same DSP's own `preset` parameter handler already defers/debounces a cross-expansion patch change
by design (~9ms) for exactly this reason; `jump_to_expansion` just didn't have the same protection.
Fix was two-sided: added real `next_expansion`/`prev_expansion` DSP verbs (one bounded transition
per call, mirroring `next_bank`/`prev_bank`) and switched the control to a `stepper` -- an arrow tap
is structurally one discrete UI event, so it can't flood the DSP the way a knob drag can. **General
rule for a port: any VST parameter whose DSP-side `set_param` does real, slow, synchronous work
should be a discrete trigger/stepper, never a continuously-nudgeable knob or slider** -- a knob's
whole *value range* being reachable by one drag gesture means the DSP has to be able to absorb many
rapid calls, which is a much stronger requirement than "one value change is affordable".

## Split-screen Q-Link banks: tried, reverted -- the real fix was one bank per tab (2026-09-24, jv880)
The "every bank shows the same screen" architecture (see the section above) was built out into
real separate-screen pages, then reverted after user feedback on the actual device: a small tab
(Play/Sends, 17 controls -- one over the 16-key Q-Link limit) read as needlessly fragmented across
two screens when it fit comfortably on one combined page (this is, after all, exactly how the
original shadow page worked -- several Q-Link banks, one screen). The per-bank-page mechanism
(frame-based segments, `persistent=1`) was reverted entirely rather than left as a half-used code
path.

That combined-screen revert still left MPC's own sub-page NAVIGATION in place (the dots/arrows
letting you swipe between Play and Sends), even once their content was identical -- confirmed with
the user this was still the actual complaint, not just a display bug, before changing anything
further. The real fix isn't in mpc-vst-plugins' shared tooling at all: a tab only gets multiple
Q-Link pages because its OWN `layout.conf` declares multiple `qlinks "..." = ...` lines --
`shadow_skin.py` just does whatever the layout asks for. So a port that wants ZERO sub-page
swiping, even for a genuinely busy tab (jv880's Tone tabs, 44 controls), emits exactly ONE
`qlinks` line per tab, capped at 16 keys by priority (a main knob or an envelope LEVEL first, an
envelope TIME or enum selector next, a toggle/trigger last) -- the rest stay on screen and
touchable, just without a dedicated Q-Link knob. Confirmed directly with the user which tabs
should get this treatment (all of them, accepting that Tone tabs lose knob access to roughly half
their controls) rather than guessing a third time on a design question this session had already
gotten wrong twice.

## Dotted-arc knobs (2026-09-24, jv880)
shadow_art.c's `knob_body()` drew a solid ring; changed to a dotted arc (dot count/size scale with
radius) to match the JV-880 shadow mockups' "dark knob, green dotted arc, small pointer" look. Only
in shadow_art.c (this repo's own offline asset renderer) -- force-shadow's shared, on-device
`render_conf_preview.c` keeps its plain ring, so this doesn't touch how any real Force page looks.

## No draggable/graph widgets in plugin skins (checked 2026-09-24)
Pulled and inspected several stock `TUI.json` skins off the device, including AIR's own **TubeSynth**
(which has real ADSR envelopes) and **Electric**/**Hype**. The full set of distinct `type` values across
them is only knobs (`greyKnob`, `blueKnob`, `hypeKnobLarge`, …), `comboBox` variants, `fader`, `Button`,
`switchButton`, `bypassButton`, `Label`, `Value`, `Image`, `Decorator` — no graph/curve/XY-pad component
anywhere. So a Force Shadow-style draggable envelope graph (`env` widget) is not portable: Shadow can draw
one because it owns the whole touchscreen framebuffer and its own touch driver, but MPC's plugin skin is a
declarative JUCE component list bound directly to VST parameters, with no custom-drawn/gesture widget
escape hatch. Even TubeSynth, which needed one, uses plain knobs per envelope stage instead. Port envelope
UIs as knob rows (time/level per stage), not graphs.

## Native picker (menu overlay): not available to VST2 (tested 2026-09-24, `poc/menuprobe.c`)
MPC's menu overlay (`comboBox` / `Show Overlay "menu overlay"`) opens **empty** for VST2 parameters. MPC never
calls `effGetParameterProperties` (opcode 56; absent from the probe log), and a `<plugin>.vstxml` ValueType next to
the .so made no difference. Use image-button selectors (`enum_h`/`enum_v`) or steppers instead.

**Why Hype/TubeSynth's setup tabs look like they use it (checked on-device, 2026-09-24):** their
`TUI.json` (`/usr/share/Akai/Content/Synths/AIR Music Technology - MPC - {Hype,TubeSynth}/Plugin Skins/`)
does bind real `comboBox`/`blueComboBox` components straight to a plugin parameter (e.g. Hype's "Mode",
"Legato Mode", "MW Dest", "Ctrl LFO Shape"; TubeSynth's "Polyphony" is a `blueComboBox`), with no
option-text list embedded in the skin JSON — so the value list has to come from somewhere live, same
shape as our probe expected. But **Hype and TubeSynth are not external VST2 plugins at all**: there is
no `Hype`/`TubeSynth` `.so` anywhere under `/usr`, they never appear as `PLUGIN` entries in
`MPC.settings`, and `strings /usr/bin/MPC` shows them as internal DSP part types (`H3Part Type='Hype'`,
`Type='AnaloguePoly' Name='TubeSynth'`) baked directly into the MPC binary alongside AIR's other stock
instruments (Bassline, TubeDrive). They just reuse the VST-plugin-skin *format* (`TUI.json`,
`localComponentDefinitions`, the same component type names) for their UI. Because MPC owns the DSP
object directly with no VST2 ABI in between, it can supply the picker's live value list itself —
something a real, external, VST2-loaded plugin (including ours) structurally cannot get MPC to do,
since that path never calls `effGetParameterProperties`. Conclusion unchanged: for a real plugin, the
native picker is not available — this only rules out one theory for why *stock* skins can use it.

**Retest with a correct `.vstxml` (2026-09-24): still empty.** The first probe's `.vstxml` was malformed for
JUCE: `juce::VSTXMLInfo` (compiled into `/usr/bin/MPC`, as are `VSTParametersStructure`/`numberOfStates`)
only parses children of `<VSTParametersStructure>`, and the `<ValueType>` sat outside it, with no
`numberOfStates`. Fixed file (`poc/menuprobe.vstxml`, ValueType inside, `numberOfStates="4"`, plus a
states-only param) **was** read: MPC called `effGetParamName` only for the one param not in the xml, so JUCE
took names (and so the value strings) from it. All four menus still opened empty. So MPC's menu overlay
does not use JUCE's hosted-parameter value strings for a VST2 param; the list only exists for MPC's internal
instruments. Don't retry `.vstxml` / parameter properties.

## Conditional visibility works for VST2 params: `IndexedEnabling` (tested 2026-09-24, `poc/menuprobe_skin.py`)
A component's `bounds.additionalInvalidatingHandles: ["IndexedEnabling/<i>/<N>/Parameter <p>"]` shows it
only while parameter p, read as an N-way choice, is at index i (stock use: AIR Amp Sim swaps its whole
background image per amp model; also AIR Diff Delay, TouchFX, Hype's GUI-Popout). On the probe, four stacked
Value labels per param with `IndexedEnabling/0..3/4/Parameter p` showed exactly one at a time, following the
knob, for both a param with `.vstxml` states and one without — so MPC computes the index from the skin's N
and the normalized value itself; the plugin needs no metadata. Stock skins pair it with
`showWhenDataModelInvalid: "Show"`. Opens up: mode-dependent panels (show a different control set per osc
type), pictures that follow a value (per-waveform image), and a self-drawn pop-up picker (a hidden "open"
param toggled by tapping the field, an option list visible only while it's open).

**Pop-up picker prototype: works (2026-09-24, probe's PICKER tab).** Field = local component with
`Mouse Down`/`Enter Pressed` → `Toggle Switch` on the "open" param (Data handle), showing the enum's value via
a second `Text` handle. Panel image + one radio-group `Button` per option (bound to the enum), all with
`IndexedEnabling/1/2/Parameter <open>` and placed after the other page components. On device: tap opens it;
a visible panel takes the touch over a control underneath (no pass-through); a hidden panel takes no touches.
Auto-close: the plugin clears "open" when the enum is set while open and reports it with
`audioMasterAutomate(open, 0)` from `processReplacing` (not from inside `setParameter`); MPC re-evaluates the
visibility and the panel closes. Caveat: a Q-Link nudge of the enum while open also closes it (the plugin
can't tell a touch from a Q-Link).

**Now a layout control: `popup` (2026-09-25).** `shadow_skin.py` `popup cx= cy= w= h= key=<enum> [cols=]`;
the list opens below the field, else above, adding columns until it fits. `gen_vst.py` appends a hidden
`<key>__open` param (`popup_of` in params.h); `vst2_wrap.c` keeps it locally (not sent to the DSP, not in the
chunk) and closes it only on an exact option value, so a Q-Link nudge (between options) leaves it open.
**Verified on the Force 2026-09-25** (Maze Voice test build, LFO1 SYNC DIV as an 8-option popup): opens as a
two-column list under the field, a pick closes it and shows the choice, a Q-Link turn steps the value with the
list left open.

**Rolled out (2026-09-25; seen working on a Force the same day):** `studio.py auto` picks `popup` for 7+
options. Ports: Maze (LFO sync divisions), JV-880 (reverb type), Acid (scale, root, regen) and Euclidier (lane
divisions, randomise lane); the last two have hand-written wrappers and use `wrapper/popup.h`. Not used where a
list is filled at run time (Crate Digger's genre/style steppers): popup option text is baked into the artwork.
The artwork font gained `#` (force-shadow fa456fc), so note names like C# show; it still has no brackets.

**Mode panels: `when=<param>:<option>` (verified on a Force 2026-09-25, "Maze Skin Test": LFO1 SYNC swaps the RATE knob for a SYNC DIV popup and shows mode-only art).** Any layout line
can carry it. Its components get the same `IndexedEnabling/<option>/<count>/Parameter <p>` handle (with
`showWhenDataModelInvalid: "Show"`) as the popup list; its baked parts (frame, title, text boxes, group labels)
are drawn into a per-mode image, the page background redrawn with that mode's parts and cropped to them, placed
over the base background (which leaves them out). A popup's list itself isn't tagged, so a list left open
while the mode changes stays open until a pick.

## Browser-rendered artwork (verified on a Force 2026-09-25, "Maze Skin Test")
`tools/html_art.py` takes shadow_art.c's stdin commands and draws them as SVG in headless Chromium (Playwright
1.47, `tools/html_art/Dockerfile`), so the layout and skin builder are unchanged. Maze Voice's whole skin renders
in about 7 s. Differences that matter on a device: knob/slider filmstrips and the images of toggles, buttons and
option segments are **RGBA** (transparent edges, so they sit on art); stock skins' filmstrips are PNGs with
alpha, and MPC also honours alpha in a `Button`'s on/off images: controls showed clean edges over a gradient.
Real fonts, `art_css=` restyling and `art file=` SVG art all showed as previewed. Backgrounds, mode images and popup
panels stay opaque. `art file=` (SVG art) is only drawn by this renderer; shadow_skin refuses it otherwise.

## Patching MPC's own picker: not practical (checked 2026-09-25)
`/usr/bin/MPC` links JUCE statically and is stripped (no `.symtab`); of ~8000 exported dynamic symbols none
names a menu/overlay/combo/parameter class (only ~92 JUCE-related, all typeinfo/vtables of unrelated
templates). So `LD_PRELOAD` interposition can't reach the code that fills the menu overlay; the only route
would be reverse-engineering the 73 MB `.text` and patching it in memory per firmware build — crash risk to
MPC and breaks on every update. The skin-drawn `popup` covers the need.

## `.so` update without restarting MPC (verified 2026-09-24, menuprobe)
Replacing `/sdcard/vst/x.so` (staged `.new` + `mv`) and then removing **every** instance of the plugin and
inserting it again loaded the new build (version line in the probe log), no MPC restart. JUCE drops the module
once its last instance is gone and re-opens it on the next insert. A restart is still needed for a new
`MPC.settings` entry.

## Skin fonts: Titillium Web + Roboto only (tested 2026-09-24, `poc/menuprobe_skin.py`)
`Label` components name their font per component (`textStyle.font.name/style/height`). Stock skins use
`Titillium Web` (Regular/SemiBold/Light/Italic…) and `Roboto` (Regular/SemiBold); both are embedded in
`/usr/bin/MPC` in every weight, and both render. `Liberation Mono`/`Liberation Serif` (installed in
`/usr/share/fonts/ttf`, a fontconfig dir) and a bogus name all fell back to Titillium, so MPC does not resolve
system fonts by name and installing a `.ttf` on the device won't give skins a new native font. Choice for
live (value/name) text: those two families at any weight/size. Any other typeface has to be baked into PNGs
(`vst.json` `"title_font"`).

## VST3: not supported by MPC OS (checked on a Force, OS base 5.0.17, 2026-09-24, `tools/probe_device.sh`)
MPC's JUCE host has only `juce::VSTPluginFormat` compiled in. The binary has no `VST3PluginFormat` /
`VST3PluginInstance` RTTI and no `GetPluginFactory` string (which JUCE needs to load any VST3 module), and no LV2
either. The only `VST3` / `.vst3` strings are JUCE's wrapper-type names and a desktop-project file-extension list.
So a VST3 bundle can't be loaded, whatever the settings say, and VST3 value lists can't fix the empty picker.
Rerun the probe after firmware updates and on other models.

## MIDI-generator VST wrapping a standalone-process engine (Force Acid, 2026-09-24)
Force Acid (`force-acid`, a MockbaMod standalone process using RtMidi + a timer thread as its own
"chain host" for `acid_core.c`) ports to a VST2 the same way as a block-rendering engine for
the MIDI-out and clock problems, but needed a hand-written wrapper (`force-acid/vst/acid_vst.cpp`, not
`wrapper/vst2_wrap.c`, which assumes `render_block` audio DSP): `tools/gen_vst.py` still generates
params.h + the skin from a hand-written parameter file (transcribed from the standalone
build's CC table, kept in sync by hand) since that pipeline only cares about the key/name/min/max/options/
momentary shape, not the real host API.
- **Clock, without a physical MIDI cable:** the standalone build derives BPM/transport from real 0xF8/
  0xFA/0xFC MIDI clock (EMA of inter-pulse interval). A VST host hands this over cleanly instead:
  `audioMasterGetTime` gives exact `tempo` and `ppqPos`. The first port synthesized the same 24-PPQN clock byte
  stream from the ppqPos delta each block and let the core count pulses; **that is superseded (2026-10-08):
  pulse counting keeps the step phase relative, so a lost pulse, a mid-song start or a loop wrap shifts it
  for good. Place each step from `ppqPos` instead -- see docs/MIDI_TIMING.md** (mpc-vst-acid PR #8 does, unreleased as of 2026-10-08; the core
  only needed a 0xF9 "step boundary" message and the wrapper owns the grid).
- **Host API with no instance argument** (`host_api_v1_t.get_bpm`/`get_clock_status`, acid_core.h): fine
  to leave process-wide (one set of atomics, `move_midi_fx_init` called once), since MPC has one shared
  transport for every plugin instance anyway -- matches host_shim.cpp's own simplification.
- **MIDI out still needs the ALSA seq port workaround** (see "MIDI-generating plugins" above):
  `effProcessEvents`/VST MIDI out reaches nowhere, so generated notes go out `snd_seq_event_output_direct`
  from inside `processReplacing`, same as `poc/midiport.c`. Silence is written to the VST audio outputs
  (`numOutputs=2`, no DSP) since the plugin only exists to reach MPC's plugin-parameter automation and the
  MIDI routing UI.
- **Chunk save without a "state" key in the core:** upstream/host_shim has no preset serialisation
  (DESIGN.md's own "Known limitations"), so the wrapper builds its own `key=value;...` chunk from every
  non-momentary param's `get_param()` and replays it with `set_param()` on `effSetChunk` -- no core changes.
- Bench: **an app-style/MIDI-generator plugin's own work (clock synthesis + ALSA send) happens inside
  `processReplacing`** here (not a background thread like Crate Digger's stream player), so unlike Crate
  Digger, `tools/bench.sh` *does* exercise the real per-block cost. x86 local run (relative numbers only):
  PASS, worst block 2.0%, p99 0.1%. **Device run (Force, 2026-09-24): PASS, worst p99 0.7%, worst block
  1.4%, threads 0.0%** -- comfortable headroom for several instances alongside a live project.
- Verified with x86 host test under ASan/UBSan (two instances, enum/float param round-trip, a 400-block
  synthesized-clock run, chunk round-trip), an offline skin preview (`tools/studio.py preview`), and
  `tools/bench.sh` on a real Force. Installed and registered on a Force 2026-09-24 (`.so` on
  `/sdcard/vst`, skin on `/sdcard/Synths`, `pluginList-arm` entry added, `MPC.settings` backed up first).
  User plugin-list/insert/play/Q-Link/save-reload test on the touchscreen still pending.

## A skin needs its app's own theme copied in, not left at the tool's default (Force Acid, 2026-09-24)
Force Acid's first skin pass built and previewed without error -- correct layout, correct controls,
looked like a plausible plugin skin -- but didn't look anything like the real force-acid shadow page
(which is yellow chassis / red buttons / dark knobs, from `addon/shadow_page.conf`'s `theme_*` lines).
Cause: `vst/layout.conf` had no `style=`/`theme_*` lines at all, so `shadow_art` rendered with its own
generic default palette (cream knobs, dark plate, orange accent) -- the same palette Crate Digger's and
Maze's *un-themed* previews would also fall back to, except those two ports happened to copy their
source app's theme into `layout.conf` already, so the gap wasn't visible before. Fix: copy the
`style=`/`theme_*` block from the app's own `addon/shadow_page.conf` verbatim into the top of the
port's `layout.conf`. Mechanism: `shadow_skin.py`'s `build()` sends the whole layout file to `shadow_art`
as `theme|<layout.conf>`, which loads it with `render_conf_preview.c`'s own `load_conf()` -- the exact
theme system force-shadow's on-device renderer uses, every `theme_*` key, not just the dozen or so
`apply_theme()` uses Python-side for label text colour. This is now step 1 of docs/PORTING.md's Skin
section and called out in the skill's "Custom layouts from Force Shadow pages" section -- do this before
laying out a single control, and always compare the preview against the app's own screenshot/mockup
(not just "does this look like a plausible skin") before calling a skin done.

## DX7 port: moved to sd88me/mpc-vst-dx7 (2026-09-25)
Its findings (a retired control-socket attempt, then an in-process schwung-dx7 build that works) are in that
repo's `docs/NOTES.md`. The generic lessons are in `PORTING.md`: check for an in-process engine build before
writing a control-socket wrapper, and check an engine's data-folder convention under `MODULE_DIR`.

## No `Envelope`/`EnvelopeOverlay`/`XYPad`/`Plotter` component type in any stock skin (checked 2026-09-25)
Re-ran the "No draggable/graph widgets" check (2026-09-24) more broadly per a reverse-engineering reference
claiming these are real, template-verified component types (with a specific `envelopeName: "Pitch"` example).
`grep -rl '"Envelope"\|"EnvelopeOverlay"\|"XYPad"\|"Plotter"' "/usr/share/Akai/Content/Synths/"*/"Plugin
Skins/TUI.json"` on the Force found exactly one hit: AIR TubeSynth. Inspected it directly — both occurrences
are a **tab name** (`"tabName": "Envelope"`, TubeSynth's ADSR screen) and that tab's own `componentName`
field, not a `"type"` value; grepping every stock `TUI.json` for `"type": "Envelope..."` / `"XYPad"` /
`"Plotter"` (any file, not just the one hit) found zero matches anywhere. No stock instrument has a "Pitch"
envelope skin component. This confirms and extends the earlier finding: not just "TubeSynth's own ADSR UI
uses knobs instead" but "no shipping `TUI.json`, in any panel of any instrument, defines a component whose
`type` is Envelope/EnvelopeOverlay/XYPad/Plotter" — the reverse-engineering reference's terminal-component
list for these four does not match what's actually on this device. ROADMAP's Envelope/XYPad/Plotter item
resolved as **not available**, same conclusion as the native menu picker.

## KnobOverlay: works for VST2 params (verified on a Force 2026-09-25, Maze Voice)
Every knob/slider/stepper this repo builds already fires `Show Overlay "knob overlay"` on Double Click and
Enter (`shadow_skin.py`'s `_action`), but nothing had confirmed what actually renders. Double-clicking a
knob on an installed port (Maze Voice) on a real device: an overlay **does** appear, and it's fully
functional for a real VST2 parameter — shows the current value, shows the parameter's name/label, lets you
set a value directly from the overlay (drag/tap), and reflects a live Q-Link turn or an
`audioMasterAutomate` change from the plugin itself while it's open. Unlike the menu overlay (empty for
VST2, NOTES.md "Native picker"), this native overlay only needs the bound `Data` handle's normalized value
— no `effGetParameterProperties`/value-list dependency — so it plausibly worked as shipped the whole time.
ROADMAP's "Native overlays" item resolved for `KnobOverlay`.

**`NumericOverlay`: not a real overlay name (tested 2026-09-25, "Maze Skin Test").** Patched the already-
installed test skin's knob actions from `Show Overlay "knob overlay"` to `Show Overlay "numeric overlay"`
(every knob, reverted after) and tried it on a real device: a blank black overlay panel appears with no
content, and it doesn't dismiss on a second double-click or Enter the way the working `knob overlay` does —
had to navigate to a different menu and back to clear it. So `"numeric overlay"` is not a name MPC
recognizes for a typed-entry keypad (or any working overlay); it just falls into some default/broken empty
panel state. No native typed-value-entry overlay found under this name for VST2 params. Don't build on it;
`popup`/steppers stay the only precise-value input this repo has.

## Native `Meter` component: breaks the whole page, not just left unrendered (tested 2026-09-25, `poc/meterprobe`)
Built a small test port (`poc/meterprobe`: `engine.c` free-runs a ~2s sawtooth "Level" param with no user
input, `layout.conf` a single `meter ... look=native img=... peak=...` widget) to check the experimental
native `Meter` component (`tools/shadow_skin.py`'s `look=native` path, ROADMAP "A native Meter component",
merged unverified on `claude/native-meter-prototype`). Installed on a Force: **the whole plugin screen came
up blank/broken** (frame, title and the readout below the meter never appeared either), not just a missing
meter widget — MPC's own log only showed `Initialising VST: meterprobe` with nothing after, no crash, no
error text. Isolated with a same-layout rebuild swapping the native `Meter` for the existing (already
"built", NOTES "Control looks and images") filmstrip-fake `meter` (`strip=`/`frames=`, a plain `Knob`
component with `knobType: "FilmStrip"`) and nothing else changed: that skin rendered completely normally
(frame, meter art, readout all visible). So the JSON-level guessed `"type": "Meter"` component (`direction`,
`invert`, `inactiveImage`, `peakImage`/`peakHandle`) isn't just inert — MPC's TUI parser appears to fail
constructing the whole page when it hits an unrecognized top-level component type, unlike an unrecognized
*attribute* on a known type (which is silently ignored elsewhere in this repo's skins). **Conclusion: the
native `Meter` component as guessed from the reverse-engineering reference does not work on a real device
and should not be used** — ROADMAP's ports both this item and the filmstrip-fake `meter`'s design stays the
only working way to show a live level.

## Engine-driven parameter changes never reach the display: a `wrapper/vst2_wrap.c` gap, not an MPC limit (tested 2026-09-25, `poc/meterprobe`)
Same test port, filmstrip `meter` version (renders fine, see above): with the meter's "Level" param free-
running inside `engine.c`'s `render()` (called continuously — confirmed by testing with the transport
actually playing, not just sitting on the edit screen) neither the meter bar nor the "Level" readout text
next to it moved at all, even over several seconds of playback; touching/swiping the meter did make it
jump immediately to wherever the touch landed and updated the readout at that instant, but the free-running
value underneath was never reflected. This looks like it contradicts NOTES.md's "Dynamic text in skins"
entry (2026-09-24, `poc/textprobe.c`) that MPC polls a parameter's display text on its own with no plugin-
side notification — but the mechanism is different: `poc/textprobe.c` is a **hand-written** AEffect whose
`effGetParamDisplay` case (opcode 7) computed its text live from a counter on every call MPC made, and
separately called `master(e, audioMasterAutomate, ...)` once a second regardless of any touch. This repo's
**generic engine wrapper** (`wrapper/vst2_wrap.c`) is different: `setParameter()` sets `w->need_update_display`
and defers `audioMasterAutomate`/`audioMasterUpdateDisplay` calls to the next `processReplacing()` block
(`run_block()`, `w->release[]`/`need_update_display` handling) — but that flag is **only ever set from inside
`setParameter()`**, i.e. only in response to a host-initiated change (a touch or a Q-Link turn). Nothing in
`render_frames()`/`run_block()` calls back into the host when the DSP engine changes a bound parameter's
value on its own between host-initiated calls, so MPC is never told to re-poll — it's not that MPC can't
redraw a live plugin-driven value (textprobe already proved it can), it's that **this repo's generic wrapper
has no code path that reports an engine-driven change to the host at all**. A future engine-driven readout
(a meter, a "now playing" field whose text the plugin changes on its own with no user touch) built on
`engine.h`/`vst2_wrap.c` needs a new mechanism — e.g. the engine flagging "this key changed" and the wrapper
calling `audioMasterAutomate`/`audioMasterUpdateDisplay` from `run_block()` regardless of `setParameter()`
having fired — that doesn't exist yet. ROADMAP's "Meters" question (does MPC redraw a FilmStrip live from an
engine-set value) stays open for a genuinely live meter; this finding narrows it to a wrapper gap, not an
MPC limitation.

## CPU layout (Force, 2026-09-24)
RK3288, 4x Cortex-A17 @ 1.8 GHz (governor `performance`), `isolcpus=2-3`. MPC runs `AudioWorker0-3` (SCHED_FIFO),
one pinned per core, plus `Audio Processing` (prio 20). Plugins run on these workers, so tracks spread across
cores. `tools/bench.sh` measures a plugin against the 2902 µs block (docs/BENCH.md).

## Skin design lessons from the jv880 redesign (2026-09-26, verified on a Force)

**List tiles: the on/off state must not be the tile's text.** A `list` tile is bound to a string param whose
`get_param` is the tile's label. The wrapper derived the tile's value with `atof()` on that text, so any name that
started with a digit ("01 Pop", "10 Bass") read as 1 and drew the "on" border, while "Preset A" read as 0. Symptom:
highlights on some tiles and not others, on both lists. Fix (wrapper + DSP convention): for a `string_display`
param the wrapper first asks the DSP for `<key>_on` ("1"/"0") and uses that as the value, falling back to the old
path if the DSP returns nothing. The DSP answers it with real selection state (jv880: `bank_slot_N_on` = browsed bank,
`patch_slot_N_on` = loaded patch). MPC does not re-read a button's value on `audioMasterUpdateDisplay`, so
`run_block` also calls `audioMasterAutomate(i, value)` for each such param whenever its `_on` value changes
(`last_on[]` caches what the host was told). Without that push the highlight showed only sometimes.
  Follow-up (2026-10-08): MPC calls `setParameter` from inside that `audioMasterAutomate`. Fed back into the
  engine, the row that just turned off is selected again, so a tap above the current row never sticks and a
  long list only highlights. The wrapper now ignores that echo (the same index and value it just pushed).
  A real row touch changes the skin's host-side `Toggle Switch` before `setParameter`; the wrapper must copy
  that value into `last_on` when the call arrives. Otherwise the cache still thinks the row has its previous
  value and may never correct it, leaving several rows lit. With the cache synchronized, the next `<key>_on`
  poll turns the previous row off and leaves only the engine's single selection on.
  For lists whose rows are mutually exclusive by definition, `list select=<param> select_n=<N>` avoids that
  independent-switch state entirely: every row is a button in one radio group bound to the shared integer
  parameter (0 = none, 1..N = row). Until that lands in the skin builder, a row tap must ignore value 0
  so the automate-off echo of the previous row does not become a new selection.
  Follow-up (2026-10-01, Chordsmith): that push only ran after a parameter set, so a tile whose `_on` changed
  from MIDI alone (a pad plays a chord, nothing on screen touched) never lit. `housekeeping()` now polls every
  `_on` every 10 ms (441 frames) and pushes a change with `audioMasterAutomate` plus an `UpdateDisplay`;
  verified on the device: the tile lights while the pad is held and goes dark on release. A second poll, every
  100 ms (4410 frames, counted on its own whatever the block size), hashes every text readout's value and asks
  for an `UpdateDisplay` when it changed: on a page without tiles a chord
  name played from MIDI stayed stale until something else was tapped (seen in a screen recording). Skin side:
  `theme_tile_on=RRGGBB` fills the selected/sounding tile (default: the LCD fill, border only) and
  `list ... order=pads` numbers the rows from the bottom like a pad bank (pad 1 bottom left).

**The orange box on a control is the Focus subcomponent, not the Q-Link bounds.** `_focus()` in `shadow_skin.py`
adds a `WhenFocussed` outline plus a faint white fill sized to the control's whole placed slot (about 130 x 155 for a
knob or slider), so on dense envelope pages it spilled over neighbours and the frame below. `hideQLinkBounds` only
sets a per-component flag and did not remove it; zeroing `qlinkBoundsData` did not either. What worked: make the
focus style transparent (`backgroundColour` and `outlineColour` `00000000`, `outlineThickness` 0). List tiles keep
their selected look because that is baked into the tile image, not the focus ring. Page `qlinkBoundsData` is now
`"0 0 0 0"` and every `hideQLinkBounds` is true.
**Per-column outlines, opt-in (MPC One, 2026-09-30, MPC Plaits):** with `qlink_bounds=column` in the layout, pages get
one `qlinkBoundsData` rectangle per Q-Link column (slots 1-4, 5-8, ...) and `hideQLinkBounds` is false, as in stock skins
(AIR OPx-4): MPC outlines the column the Q-Links drive, and each press of the MPC One's Q-Link button moves the outline to
the next one. Buttons count toward their column's box. The orange box above was the Focus outline, so hiding the bounds
was never needed to fix it; still, the outline is only checked on an MPC One, so the default stays "0 0 0 0" and hidden.

**Q-Links stuck on integer params (fixed in `wrapper/vst2_wrap.c`).** Symptom: a Q-Link on a 0..127 param flicked
between two values on a slow turn and would not climb. Causes, in order: (1) the value went to the DSP as `%g` text
and the DSP `atoi()`ed it, which truncates ("5.99999" -> 5); (2) even rounded, MPC sends a slow turn as a step
smaller than one integer, and reads the value back from `getParameter`, which is the rounded integer, so every
nudge is lost. Fix: `norm_to_str` rounds params flagged `"display": "int"`, and the wrapper keeps `shadow[i]`, the
unrounded position last set, and returns that from `getParameter` while the DSP still holds the value it rounds to
(dropped if anything else changes the param). Applies to every port with `display: int` params (jv880, dx7).
Float params (maze) are parsed with `atof` and never had this.

**Native labels ignore `label=`.** A control's name text is the assigned parameter's own name (see "Control names"
above), so the same key placed twice shows the same name twice. A `REVERB` knob in an OUTPUT frame and the
reverb frame's `LEVEL` knob both read "REVERB". Don't repeat a key on one page; if a control must appear twice,
expect identical labels.

**Global CSS knobs and what they touch (`skin.css` `:root`).**
- `--button-size` sets button text, but the layout sizes each button from a much smaller font estimate
  (`text_width(label) + 36`, plus 28 + 4 for `style=td3`; "PREV" -> 108 x 52). A wide face at 21 px overflowed; 14 px fits.
- `--seg-size` (enum segment text, default 17 in a generated skin) and `--label-size` (the baked label above an
  enum/popup) apply to every page. Segment height is fixed at 33 px in `seg_rects`; only `sw=` is per widget.
- `--sheen` is one global gradient (buttons, segments, knob faces). A per-button gloss is not possible from CSS.
- Button colour comes from `theme_btn_bg` and `theme_btn_text` in the layout. Corner radius: override
  `.button-bg` and `.button-sheen` with `rx: 0` in `skin.css` for square keycaps.
- Give a `.button-bg` a `stroke` for a bezel; a black button on a dark panel is otherwise invisible.

**Measured spacing on the 1280 x 628 skin canvas** (layout y; the device screen shows it about 25 px lower under
its own header, and the tab bar cuts off at about layout y 712):
- A knob's value text sits at about `cy + r + 34 .. cy + r + 58` below its centre (label first, then value).
  Leave 60 px below `cy` before the next row's knob top, or 70 for r=27.
- An enum or popup draws its label about 30 px above its centre line; keep that clear of the row above.
- A frame's title rule is about 28 px below `frame y`; nothing should start within 12 px of it.
- `readout` with `style=dotmatrix` is 50 px tall, a `button` about 52.
- Three readouts and two buttons make a convincing single LCD strip: give the gaps a constant width and compute the
  button width from `button_rect` instead of guessing.

**Adding a param to an existing port.** Append it at the end of `chain_params`. MPC stores values by index, so
inserting mid-list shifts every later saved value (docs/RELEASING.md, versioning).

**Offline preview needs Pillow.** `tools/studio.py preview` imports `PIL`; on a bare WSL install it is missing and
there is no `pip`. Preview is what to look at before deploying; without it, deploy the skin alone (a changed skin
needs an MPC restart, see the 2026-10-04 note) and read the screenshot.

**Integer param display beats truncation everywhere.** Any port with integer DSP params should set
`"display": "int"` on them (gen_vst.py `int_display`): it fixes the formatting *and* enables the rounding and
shadow behaviour above.

## Portable layout verified on a Force (Dexed), 2026-09-29
Verified on a Force (armv7l, BusyBox 1.36.1 userland; MPC OS version not read directly, `MPC.settings` mentions 3.8.0.25 and
3.9.1), 2026-09-29, with `install-portable.sh` / `uninstall-portable.sh` from `claude/portable-installer` and a Dexed (DX7) 1.0.1
test zip (`docs/PORTABLE_TEST.md`). **Result: pass, steps 0-6.** The catalog check printed OK; the offline host test
(`tools/test_port.sh`) has one failure that predates this work (below).

| step | result |
|---|---|
| 0 prepare | pass. Settings backed up to the host (sha256 matched the device file); no `noexec` on any mount |
| 1 build the zip | pass. `catalog_check.py --catalog` OK, 0 warnings; `plugin-meta.xml` `file=` starts with `%payload-path%/` |
| 2 install (old layout to portable) | pass. Folder in `/sdcard/Synths`, `uid` count 1, `file=` is the `/sdcard/Synths/...` path, old `/sdcard/vst/dx7_dexed.so` removed, no duplicate entry |
| 3 use in MPC | pass (user report): listed once, adds to a track, plays, skin shows, Q-Links, project save and reload, banks found |
| 4 upgrade | pass. Second run: still one entry, plays, the user's test file and 35 banks they copied into `dx7_carts/` all kept (69 files), no `.new`/`.old`/`.keep` folders, a new `.bak-` file |
| 5 uninstall | pass. Entry gone (`<PLUGIN>` count 11 to 10), `.so`, skin and metadata gone, `dx7_carts/` (user data) kept, a project that used Dexed opens without it |
| 6 other location | pass. `-t /media/<id>/Synths` on the exfat USB stick: registered, loads and plays; then a reinstall at `/sdcard/Synths` moved the entry back and kept the 69 user files |

Mount lines (no `noexec` anywhere):
```
/dev/mmcblk0p7 on /media/acvs-synths type ext4 (ro,relatime)
/dev/mmcblk0p8 on /media/az01-internal type ext4 (rw,relatime)
/dev/mmcblk1p1 on /sdcard type ext4 (rw,relatime)
/dev/mmcblk1p1 on /media/az01-internal-sd type ext4 (rw,relatime)
/dev/sda1 on /media/<id> type exfat (rw,relatime,fmask=0022,dmask=0022,iocharset=utf8,errors=remount-ro,uhelper=edisksd)
```
Registered entry after step 2: `file="/sdcard/Synths/sd88me - VST - Dexed (DX7)/dx7_dexed.so" uid="46445832"`.

Findings:
- **MPC loads a `.so` from inside a Synths folder**, both on the internal SD card (`/sdcard/Synths`, ext4) and on a USB stick
  (exfat, which reports every file as executable through its mount mask). Neither is `noexec`.
- The stick's `Synths` folder was already one of MPC's `SynthContentLocations`, so the skin was found there too.
- **Engine data must sit next to the `.so`.** Dexed had `MODULE_DIR=/sdcard/vst/dx7_carts` hardcoded. It was changed to
  `"MODULE_SUBDIR": "dx7_carts"` (the absolute `MODULE_DIR` stays as a fallback) and `release.sh` got `--user-data dx7_carts`.
  In the old layout the `.so` is in `/sdcard/vst/`, so the same setting resolves to the old folder and still works.
- `--user-data` behaved as documented: files the user adds, or copies in, survive an upgrade and an uninstall.
- **Pre-existing host-test failure, not caused by the portable work:** for Dexed, `tools/test_port.sh` fails
  `set preset 0.25 -> get 0.000` with and without the `MODULE_SUBDIR` change (the other checks pass). Likely the host has no
  bank folder to scan; not investigated. On the device, preset selection worked.
- The installers were run by the user in a terminal (an automated `-y` run was declined by the tooling), so their console
  output was not captured here; the resulting state was checked from the device after each step.
- The old bank folder `/sdcard/vst/dx7_carts` is left behind by the move (unused). The installer does not remove data it did not install.

## Portable folder is now the only release layout (2026-09-29, offline only)
`tools/release.py` now writes one plugin folder, `portable/<skin>/` (`.so`, skin, data, `plugin-meta.xml`), with `install.sh` /
`uninstall.sh` (the former `-portable` scripts); `payload/`, `plugin.xml` and `--no-portable` are gone, the manifest has
`layout: "portable"` and `folder`. `--extra` DEST is relative to the plugin folder (a leading `vst/` is still accepted).
`install.sh` also handles an old `/sdcard/vst` install of the same plugin: after the settings edit succeeded it removes the old
`.so` and the data the package ships there, and moves the user's own `--user-data` folders from `/sdcard/vst/<path>` into the plugin
folder (merged over the shipped files; nothing else in `/sdcard/vst` is touched). `catalog_check.py` still accepts old-layout zips.
Checked offline only: `tools/test_catalog.py` (45 tests, dash), and a real Dexed build packaged and installed into scratch folders against
a copy of a real `MPC.settings` with a fake old install (one entry, old `.so` gone, user bank merged with the 33 shipped ones).
**Not yet run:** under BusyBox (no `busybox` on the build machine this time) or on a device with an old-layout install that has user
data, e.g. JV-880 ROMs.

### 2026-09-30: JV-880 v1.0.2 old-layout upgrade on the Force (install.sh, pre-restart checks)
Installed the published v1.0.2 zip over an old `/sdcard/vst` install with ROMs. Result: old `jv880.so` removed, `/sdcard/vst/jv880-roms` moved into `/sdcard/Synths/sd88me - VST - JV-880/jv880-roms/roms` (all ROM files present), one `jv880` entry in MPC.settings, settings backup made. Load test in MPC: OK (plugin loads, ROMs found).

### 2026-09-30: Monomodule One + FX in the portable layout (Force)
Per-user zip 0.9.2 (package.sh -> two release.py packages) installed over an old `/sdcard/vst` install: dumps moved into One's `monomodule/dumps`, old `.so` and OS copy removed, one settings entry each. Sound works. Gotcha: a `.so` built before the plugin-dir lookup (no `/proc/self/maps` string) ignores `MODULE_SUBDIR`, looks in the removed `/sdcard/vst/monomodule` and logs `engine failed: cannot open .../Elektron_SFX6-60_OS1.32B.syx` (no presets, no sound). That happened with 0.9.1; package.sh now refuses such a `.so`. Always rebuild the port before a layout release.

### 2026-09-30: lost exec bits / symlinks in a copied package (Crate Digger)
Staging a release for the Force by unzipping with Python `extractall` and `scp -r` dropped the exec bit on `yt-dlp`/`ffmpeg` and turned the private Python's symlinks into text files; the plugin loaded but search failed (`search_status=error` in `/tmp/cratedigger_vst.log`). The release zip itself was right (0755, symlinks). The same happens to anyone who unzips on Windows and copies the folder. `release.py` now writes a `MODES` file (executable files and symlinks inside the plugin folder) and `install.sh` re-applies it after copying (test: `test_lost_exec_bits_and_symlinks_are_restored`). Stage zips for a device as a tar stream that keeps modes, or unzip on the device.

### 2026-09-30: MockbaMod `vstscanner` / `vstmanager` (community tools, read + offline-tested; not run on a device)
MockbaMod users may use the Force VST distribution's `vstscanner.sh`. It rebuilds the WHOLE `pluginList-arm` from `/media/*/Synths/*/plugin-meta.xml` (filling `%payload-path%` with that Synths folder; `plugin-meta.xml.disabled` = disabled by `vstmanager`), between `MPC-CUSTOM-PLUGINS BEGIN/END` markers, stops/starts `acvs` and does NOT back up `MPC.settings`. Our portable plugin folders match that rule as they are: an offline run (script copy pointed at a fake `/media/card/Synths` holding the real JV-880 and Monomodule One packages, `systemctl` stubbed) registered both with the right name/uid/`file=`, a second run changed nothing, the settings stayed valid XML. Consequences: (1) a plugin still installed the old way (`.so` in `/sdcard/vst`, no folder in a Synths dir) is dropped by the next scan; (2) `/sdcard` and `/media/az01-internal-sd` are the same mount on the Force, so the scanner writes `file=/media/az01-internal-sd/Synths/...` where our installer writes `/sdcard/Synths/...` (our uninstall/upgrade match by uid too, so both work); (3) `install.sh` swaps the whole folder, so an upgrade re-enables a plugin that `vstmanager` had disabled. Kept out of the generic docs on purpose (MockbaMod-specific).

### 2026-09-30: user reports of plugins vanishing from the list after a restart (analysis, not reproduced on a device)
Community reports: "installed third-party plugins, restarted, they aren't in the list", "a command pasted into PuTTY uninstalled all
my plugins", "some install one way and some another, which rewrites the file that tells the MPC what's installed". The plugin list
is the single `pluginList-arm` value in `MPC.settings`, so every install method edits the same list and one can undo another. Likely
causes, from the facts above: (1) the file edited while `acvs` runs (the reason for the stop-first rule; MPC keeps its settings in
memory and saves them itself; not tested separately here); (2) a list-rebuilding scanner such as MockbaMod's `vstscanner` (entry
above), which drops every plugin that is not a Synths folder with a `plugin-meta.xml`, i.e. hand-added entries and old-layout
(`/sdcard/vst`) installs, while the files stay on the card; (3) malformed XML, which makes MPC reset the file to defaults (empty
list). Our current releases survive (2) because they are such folders; `install.sh` stops MPC before editing and re-adds only its
own entry, so re-running each plugin's installer is the safe recovery. The site's Install guide now has "If a plugin disappears after
a restart" with these causes, a check that lists each registered `file=` and whether it exists, and the recovery steps (generic
wording, no MockbaMod naming). Still unverified: that a running MPC actually overwrites an external edit, and whether a JUCE entry
whose file is missing at startup is dropped from the saved list.

### 2026-09-30: installer tests under BusyBox
`INSTALLER_TEST_PATH` with BusyBox 1.38 (static musl build, applets symlinked, python3 added): `tools.test_catalog.InstallerTest`, 11 tests OK, including the MODES restore. The Force has BusyBox 1.36.1, so this is close to, not identical to, the device userland.

### 2026-09-30: device hardware check for an on-device installer (Force, MPC OS, MockbaMod)
`wget` (GNU 1.20.3, musl) fetched this site's `catalog.json` over HTTPS and `curl` reached github.com; `/tmp` is a 1 GB tmpfs (RAM), `/sdcard` ext4 with GBs free. Present: `python3`, `dialog`, BusyBox `unzip`/`tar`/`sha256sum`/`nc` (no BusyBox `httpd`); `python3` and `dialog` may be MockbaMod additions. MPC drops a plugin-list entry whose file is missing at startup. `tools/mpc-store.sh` `list`, `install --dry-run acid` (real download + sha256 check from GitHub, extracted, nothing installed) and `sync --dry-run` (planned 4 additions: unregistered AIRWINDOWS folders) ran on the device against a catalog served from the device itself; MPC.settings unchanged.

## Multiple outputs and shared state between instances (tested on a Force, 2026-09-30)

- **MPC uses only the first stereo pair of a VST2 instrument.** `poc/multiout.c` (as registered, `numOutputs="8"`, one sine per
  output): MPC calls `effGetOutputProperties` up to pin 7 and passes 8 valid `processReplacing` buffers, but a track only offers
  one audio-out setting (1,2) and only the main pair is heard; the mixer's return/submix buses have no input selector. So per-track
  outputs from one instance are not possible.
- **Every instance of a plugin lives in one process with one copy of the library's statics.** `poc/shared.c` (three instances,
  a process-wide id counter, log in /tmp/shared.log): same pid, ids 0,1,2, `effClose` sees the shared count. `effOpen` is called
  twice per instance. `processReplacing` (n=128, every ~2.9 ms per instance) runs on MPC's pool of worker threads (4 on a Force),
  and the thread for one instance changes between calls, so instances run concurrently and in no fixed order: share data between
  them producer/consumer style, never drive a shared engine from a callback.
- Used by mpc-vst-machinedrum's Machinedrum Tap / Tap FX (separate plugins that read one Machinedrum Module's tracks and sends):
  measured on the Force, the primary's callback ran 166-256 us before the tap's in each period, so a tap can pick the same block.
  A plugin in its own Synths folder finds another plugin's loaded copy with `dlopen("<its soname>", RTLD_NOLOAD)` (or its path
  from /proc/self/maps).
- Build note: these PoCs are plain C; on a recent cross toolchain add `-U_TIME_BITS -D_TIME_BITS=32` if you call time functions,
  or the .so asks for GLIBC_2.34 time64 symbols.

### 2026-09-30: desktop installer (tools/desktop) verified against a stand-in device
Go app, one 7-8 MB static binary for Windows/macOS/Linux (amd64 and arm64 build fine). `go test -race`: package validation (traversal, absolute paths, escaping links, old layout, wrong arch), tar keeps modes/symlinks and drops the top folder, catalog download hash/size/https checks, the guard (token, Host, Origin, CSP), and a fake in-process SSH device running the whole install (one stop/start, exec bits and links survive, failure still restarts MPC and installs nothing after it, refused device untouched, shell quoting). Browser test (Playwright, sshd in a container with shims): real Acid 1.0.1 downloaded from GitHub, sha256 checked, installed with its old installer (which restarts MPC itself) plus a current-installer package in one batch: MPC calls stop/start, stop/start; both entries in MPC.settings; `.mpc-store` written; /tmp clean; page marks Acid "on the device". Found and fixed: the on-device list was only read at connect (now refreshed after an install); dialog said "restart once" although an old installer restarts it itself (now "at least once"). NOT yet run against the real Force (Docker here cannot reach the LAN).

### 2026-10-01: desktop installer tried on the real Force; filters added
Read-only pass and a same-version reinstall of Acid through the page on the real Force (MPC OS, key login): connect, device info, catalog marks, real Acid zip validated and installed; afterwards no /tmp/mpc-installer-* left, one settings entry per plugin, `.mpc-store` written, MPC active. Added to the page for a growing catalog: search, kind/developer/show/sort filters (updates use the versions recorded in `.mpc-store`), selection kept while filtering, sticky selection bar. Browser test with a 41-plugin synthetic catalog (`tools/desktop/ui_test/ui_filters.py`) found a real bug (toolbar ignored the hidden attribute before connecting); an apparently blank dropdown was a Playwright quirk (`select_option(value="")` selects nothing), not a page bug.

### 2026-10-01: desktop installer can remove plugins
Step 4 of the page lists the plugin folders on the device (uid and name read from each plugin-meta.xml) and removes the ones it can identify: stop MPC once, back up MPC.settings, edit the plugin list with the embedded plugin_list.awk (checked: root element, XML when python3 exists, the uid really gone), then delete the folder keeping the manifest's user_data, forget the recorded version, start MPC. Nothing is deleted if the settings edit cannot be trusted; MPC is always started. Unidentified folders are listed but refused (cannot tell which files are the user's). The plan is rebuilt on the server from the device and the catalog, never from the page. Tests: device-side behaviour against a fake SSH device (mutation-checked: skipping the delete makes three tests fail), refused plans (path tricks, bad uids, shell characters in keep paths), server refusal of unknown folders, embedded awk identical to the canonical one, and a browser run against the stand-in device. Not yet run on the real Force.

### 2026-10-01: re-release of Acid 1.0.2, Crate Digger 1.1.4, JV-880 1.0.3 in the current installer (verified on the Force)
Built in CI (mpc-vst-plugins d55a431: installer -n, MODES, new `user_data` input of the shared vst-release workflow; JV-880 got its own workflow, Acid/Crate Digger were re-pinned), no code changes since the previous releases (only docs). Dropped into the desktop app and installed in ONE batch on the Force: one MPC stop/start; JV-880 ROMs kept in `jv880-roms/roms`; one settings entry per plugin, valid XML; `.mpc-store` recorded the new versions; Crate Digger engine kept exec bits and symlinks; /tmp clean; plugins load and play. Published; the catalog lists them as latest. NOT re-released: Dexed (1.0.1 still has the old installer, so a batch with it restarts MPC twice). Its CI build fails because the skin fonts (EurostileExtendedBlack, FilmotypeFord, Helvetica) are commercial and deliberately not in the repo (gitignored, README: supply your own); it can only be built on a machine with the fonts and armhf emulation (`release.sh`). The `MPC.settings.bak-*` files pile up on the device (64 after a day of testing): the app and installers never prune them.

### 2026-10-01: catalog `defer` flag, installer-aware mpc-store.sh, backup pruning
`catalog_check` records `defer` per version (the zip's install.sh has `DEFER=`, i.e. understands -n); it is in catalog.json and the last column of catalog.tsv; the desktop app uses it for the exact restart count and marks older-installer releases. Bug found while doing it: `mpc-store.sh install` passed `-n` to EVERY installer, which an old one (Dexed 1.0.1) rejects; it now greps the downloaded install.sh, runs old installers first with their own restart, then the rest between one stop/start (test: a package with the -n option removed). Pruning: `MPC.settings.bak-*` files (64 after a day of testing on the Force) are deleted except the newest N (default 10, minimum 1), only files with that name, MPC untouched: app step 5 and `mpc-store.sh prune [--keep N]`; mutation-checked (an off-by-one in the kept count fails the tests).

### 2026-10-01: desktop app: install locations (cards and drives) and Register plugin folders
The device scan now lists every writable Synths location (/sdcard/Synths = the internal drive, default; /media/*/Synths for cards and drives), de-duplicated by storage (`stat -L -c %d:%i`; /sdcard and /media/az01-internal-sd are one), with filesystem, free space, whether MPC lists it as a content location (`<Location>` in MPC.settings) and whether it can hold symlinks (FAT/exFAT/NTFS cannot). Found on the real Force during a read-only run: `/media/acvs-synths/Synths` (read-only system mount, 0 KB free) was offered because `test -w` succeeds as root on a read-only mount; fixed by reading the mount options (a test covers it). Real Force locations: Internal drive (ext4, content location) and Drive 662522 (exFAT, content location, no symlinks). Install goes to the chosen location (installers get -t; state file `.mpc-store` per location), is refused for a package with symlinks on exFAT and when there is no room (checked with a tenth to spare, rounded up: a test with a tiny package found the integer-division hole), removal works per location (the plan is rebuilt server side from the device and catalog). New collapsed step 5 "Register plugin folders" (embedded sync.sh, dry-run for the list, one MPC stop/start to apply), backups became step 6. Tested: go test -race (fake device with a card, aliased storage, register, refusals; two mutations caught), browser run against a stand-in device with a second location (selector and warnings, register, install to the card, remove from the card). Not yet exercised on the real exFAT drive.

### 2026-10-01: wrapper no longer needs GLIBC_2.34 (MPC OS 2.x loads again)
Report: Dexed 1.0.1 does not load on a Gen-1 MPC One, MPC OS 2.15.1 (glibc 2.32): `/lib/ld-linux-armhf.so.3 --list <so>` says `version GLIBC_2.34 not found`; Dexed 0.4.0 loads. Cause (from source, not yet confirmed with `readelf -V` on the 1.0.1 .so): `plugin_dir.h` called `dladdr()`, which binds to `GLIBC_2.34` when built in `arm32v7/gcc:12` (glibc 2.36). `plugin_dir.h` now reads `/proc/self/maps` only (host-checked: returns the executable's directory). To test on a device without a toolchain: `/lib/ld-linux-armhf.so.3 --list <so>` must print no "not found". The catalog limit (`MAX_GLIBC` 2.36) still lets 2.34+ through, so ports can regress again; MPC OS 2.15.1 = glibc 2.32, MPC OS 3.x = 2.39.

### 2026-10-01: MPC's service is `inmusic-mpc` on Hakai-enabled systems (reported, fix not yet device-tested)
Issues sd88me/mpc-vst-plugins#88 and sd88me/mpc-vst-dx7#6 (user report, MPC OS 2.15.1 with Hakai): `systemctl stop acvs` fails with "Unit acvs.service not loaded", the desktop installer stops with status 3 and installs nothing; the reporter verified the unit is named `inmusic-mpc` there. The installers (`install.sh`, `uninstall.sh`, `sync.sh`, `mpc-store.sh`) and the desktop app's generated scripts now pick the service with `systemctl cat acvs` / `systemctl cat inmusic-mpc` (acvs if neither is found, so stock firmware is unchanged). Host-tested against a fake systemctl for both names; NOT yet run on a Hakai device or stock hardware. Zips already released still carry the old `install.sh` (acvs only), so Hakai users need the desktop app or a rebuilt release.


## 2026-10-02: arm builds move to glibc 2.31 (bullseye)

`arm32v7/gcc:12` (glibc 2.36) binds `pthread_create`, `pthread_join`, `pthread_setname_np` and `pthread_setaffinity_np` to `GLIBC_2.34`, like `dladdr` before, so any threaded port (JV-880 1.0.3, probably Crate Digger) does not load on MPC OS 2.x (glibc 2.32). `build_port.sh` and `bench.sh` now use `arm32v7/gcc:11-bullseye` (glibc 2.31): JV-880 builds with highest symbol `GLIBC_2.17`. `catalog_check.py` limit lowered from 2.36 to 2.32 so this cannot regress. Port CI workflows pin `tools_ref`: bump it to the merge commit of this change before the next CI release. Ports still to rebuild and re-release: acid, crate-digger, jv-880, maze-voice (Dexed 1.0.3 is already fine).

## 2026-10-02: optional drum-pad patch (tools/mpc_patch), verified on a Force
`tools/mpc_patch/mpc-drum-pad-patch.sh` gives chosen plugins MPC's 16-pad drum layout on MPC OS 3.9.1.2 (all 16 pads lit, pad n sends
note n-1). It patches Akai's factory `/usr/bin/MPC` on the device, so it is a standalone opt-in script (warnings, exact-checksum gate,
typed confirmation, full backup, `status` / `uninstall`), not part of any plugin release or installer. It generalises the
Machinedrum-only patch (mpc-vst-machinedrum `release/mpc_patch`): the plugin-name check is a table in `matcher.S`. Tested offline
(name matcher under qemu-user at its real address; the script in BusyBox 1.36 against copies of the binary: install, cancel, repeat,
uninstall from either backup, upgrade from the earlier patches, refusal of other firmware) and on a Force (6W6, 8W8, CW-78, 9W9: drum
layout, pads 1-n play voices 1-n). Needs plugin notes 0-15 for the pads (the tr-drums ports remap them). To add a plugin: add its exact
plugin name to the table, rebuild (`asm.sh`, `make_patch.py <stock MPC>`, `build_script.py`) and run both tests.

## Input probe: what MPC sends for a Q-Link turn, a data wheel click and a touch drag (2026-10-03, Force, MPC OS 3.9.1)
`poc/inputprobe` is a silent plugin with a continuous knob (`cont`), a whole-number knob (`int`, 1..8), a 9-option list
(`opt`) and a MARK button. It is built with `"defines": {"WRAP_TRACE": 1}`: the wrapper then calls `wrap_trace(kind, index,
value)` from `setParameter` (kind 0) and `getParameter` (kind 1), and the probe's engine writes `/tmp/inputprobe.log`
(`INPUTPROBE_LOG` moves it; it stops at 2 MB). `WRAP_TRACE` is off by default and costs nothing then. Why: #90 reports every
Q-Link event as one 1/128 step from the value MPC last read back (Key 37), while #130 reports data wheel ticks as the
current value plus a fraction of a step and drag/Q-Link sweeps measured from where they started (MPC One); the wrapper cannot tell
a wheel click from a Q-Link event by the number alone, so the two stepping designs need real numbers per device.

Log lines: `<ms> S <key> <host value> <value in the param's units>` (a raw setParameter), `<ms> G ...` (what getParameter
returned, only when it changed), `<ms> E <key> <string>` (what the wrapper handed the engine after rounding/stepping),
`<ms> MARK <n>` (the MARK button).

Test (one control at a time, tap MARK before each step so the log splits cleanly): focus the control, then (1) one slow click or
nudge, (2) five slow ones in a row, (3) one fast spin, (4) a reversal, (5) a touch drag across the control. Do it with the
Q-Link knob of that control and with the data wheel. Read `S` values to get the delta per event (in the param's own units: option
index, whole number, or the 0..1 value), and compare each `S` with the `G` just before it to see whether MPC measures from the
read-back value or from where the gesture started. Results go here, with the device, MPC OS version and date.

**Result (2026-10-03, Akai Force, MPC OS 3.9.1; one run, one device; Key 37 and MPC One not re-measured).** Every `S` is the
value MPC last read back (`G`) plus a small delta: nothing is measured from where a gesture started, for either input. Deltas
below are in 1/128 of the host's 0..1 range:
- **Q-Link, `cont` and `int`:** exactly 1 per event, one event per click. A fast spin sends 1..3 per event; a reversal is the same
  size, negative. (`int` 1..8: 1/128 of the range is 0.055 of a whole number.)
- **Data wheel, `cont` and `int`:** exactly 1.28 (0.01) per event, one event per click; fast spin 1.28 and 2.56. Reversal negative.
- **Touch drag, either control:** about 4 to 7 (0.04) per event, still from the last read-back, so a drag is a stream of larger nudges.
- **`opt` (9 options), Q-Link:** 1 per event (0.0625 of an option), 1..3 on a fast turn, negative on a reversal.
- **`opt`, data wheel:** 1.28 and 1.92 alternating (0.08 and 0.12 of an option) per event, one event per click; each event lands
  between options, so today's wrapper steps one option per click. The first attempt produced no `setParameter` at all (the
  wrapper logs before it acts, so MPC sent nothing); after a retry the wheel drove it. What changed between the two attempts
  (focus or tile selection) was not recorded.
- **Tap on an option tile:** one `S` on the exact option (a jump of up to 7 options).
- **Distinguishing wheel from Q-Link by delta:** not reliable. A slow wheel click (1.28) is only 28% above a Q-Link click (1),
  a fast Q-Link event (2..3) overlaps the wheel's 1.92 and 2.56, and a drag overlaps a fast spin. Treat both as "a small delta
  from the read-back value".
- **Consequence for #90 and #130:** counting several events per option (#90's `QLINK_TICKS` 3) also applies to wheel clicks, which
  arrive one per detent: three clicks per option. Tick counting therefore has to be a per-param opt-in (`qlink_ticks`, default 1),
  not a wrapper-wide default, until the wheel can be told apart.

## 2026-10-03: MPC OS 2.15.1: plugins load, skins do not draw (user reports on an MPC Live, plus other 2.x users; not reproduced by us)

Unit: MPC Live (first generation), MPC OS 2.15.1, Buildroot 2021.02, BusyBox userland (no `ldd`, `file`; `head -n`, not `head -3`; `tar` has no `-z`, so use `tar cf` and `gzip` separately if it exists), `armv7l`. **glibc 2.32** (measured 2026-10-05 by running the library: `/lib/libc.so.6` is executable and prints `GNU C Library (Buildroot) stable release version 2.32.`); the Force prints 2.39 the same way. `tools/mpc-store.sh` and the desktop app (PR #179) read it from that line, or from `libc-X.Y.so`. MPC runs as `inmusic-mpc.service`; there is no `acvs`.

- **Service name.** Release zips built before the installers picked the service themselves ran `systemctl stop acvs` and aborted ("Unit acvs.service not loaded") before touching `MPC.settings`. Fixed in the installers and in the desktop app (a `systemctl` shim for old zips, desktop v0.3.2).
- **glibc.** Builds that need `GLIBC_2.34` (`dladdr`, `pthread_*`: Dexed 1.0.1-1.0.2, JV-880 1.0.0-1.0.3, checked with `objdump -T`) were registered correctly (right `file=`, file present, executable) but MPC showed only "Load Plugin". Dexed 1.0.4 (needs 2.29) installed through the app loads: the log shows `Attempting to load VST`, `Creating VST instance`, `Initialising VST`. The two old releases per plugin are yanked in `catalog/yanked.json`.
- **Skin location was not the cause.** The plugin's folder was under a `Synths` path listed in `SynthContentLocations` (SSD and internal SD both tried), `Plugin Skins/TUI.json` present. The edit page showed MPC's frame (header "Plugin 001", preset `<none>`) with an empty body; the log has no skin or JSON message. Q-Links showed and drove the parameters.
- **2.x does read a skin from a plugin folder.** Copying the stock AIR Compressor `Plugin Skins` over the Dexed folder made the Compressor page appear as Dexed's edit page. So the fault is in our `TUI.json`, not in how MPC finds it.
- **Imports exist.** Our `TUI.json` imports `/usr/share/Akai/Content/Synths/Generic/Generic Knob Overlay.json` and `Generic Menu Overlay.json`; both exist on 2.15.1 (also `Generic Slider.json`, `version.xml`).
- **Format versions (counts of `"version": N` over every stock `Plugin Skins/TUI.json`).** 2.15.1: 1 = 10884, 2 = 3030, 3 = 45 (no 4 or 5). Force, OS base 5.0.17: 1 = 9259, 2 = 5929, 3 = 224, 4 = 388, 5 = 76. Our generator (`tools/shadow_skin.py`) writes component definitions at version 4 (94 in the Dexed skin), tabs at 3, film-strip knob data at 5, `Q-Links.json` at 4: the same shape as the Force's stock Decimator skin. Hypothesis: 2.x does not accept versions above its own. **Open:** the 2.x shape of those objects; needs a stock `TUI.json` (and one with knobs) from a 2.x unit. The same stock AIR Compressor skin lays out identically on 2.15.1 (MPC Live) and on the Force, so screen size is not the issue.
- Akai's support pages (read 2026-10-03) say standalone MPC does not support third-party plugins at all, list the standalone models, and say new built-in plugins need newer OS versions (Native Instruments 3.5+, Spitfire 3.7.1+). Forum posts say 2.15.x is no longer updated by Akai. None of this covers skin formats.

### 2026-10-03: addins installed end to end on a device (zip install.sh, mpc-store.sh, desktop app)
Both addins (remote 0.1.0 → 0.2.0, usb-audio 0.1.0) were installed, upgraded and removed through all three paths. The zip's `install.sh`/`uninstall.sh`, `mpc-store.sh install/update/remove` and the desktop app (drop both zips, one confirmation, remove one in step 4, the other stays) each passed. A batch of two addins restarts MPC once; an upgrade keeps an edited setting (`max_fps`); removal leaves the firmware's own `LD_PRELOAD` list and no drop-in. With both loaded, notes sent through the remote's MCP `play_notes` come out of the USB audio interface (main out about -25 dBFS, silent inputs about -98); all 17 MCP tools answer on the device. Found:
- `mpc-store.sh`'s `stop_mpc` ended with `pidof MPC && die`. As a function's last command it returns 1 when MPC has stopped, so `set -e` ended the script after stopping MPC (the EXIT trap started it again, so nothing was installed). Fixed.
- The addin `install.sh` summary named the shared drop-in as "the list", not the unit that sets it. Fixed.
- Remote addin: its capture opened `/dev/dri/card0`, and DRM makes the first opener of a card with no master the master. When it got there before MPC, MPC failed with "Failed to initialise display" and systemd gave up after its restart limit (`systemctl reset-failed acvs` and start). **Any addin or tool that opens the DRM card must `DRM_IOCTL_DROP_MASTER` right after opening it.** While MPC boots, the card scans out the console framebuffer (3840x800), not MPC's 1280x800. Fixed in 0.2.0.
- Remote addin: Chromium shows a multipart part only once the next part arrives, so a stream that sends frames only on change must resend the last frame when the screen goes idle; without that the page is blank until something changes. Fixed in 0.2.0.

### 2026-10-03: MPC leaks `temp_*.img` files in /var/tmp/filmstrips at every start
Each MPC start writes `temp_*.img` files (one start: 71 files, 178 MB; the largest 11 MB) to `/var/tmp/filmstrips` (the overlay's upper dir is on /data) and never deletes them. A day of restart-heavy testing left 2.5 GB of them and filled /data. Files no process holds open can be deleted. Delete them through `/var/tmp/filmstrips`: deleting them from the upper dir directly doesn't give the space back until `echo 2 > /proc/sys/vm/drop_caches`. Not a plugin or addin bug, but anything that restarts MPC often (installers, tests) adds to it.

### 2026-10-03: the Plugin Manager's TESTING.md passes on an MPC Key 37 (addins and the browser tile)
poloq-instruments/mpc-vst-manager#1 (addin support) run end to end on the Key 37 (MPC OS 3.9.1, install target `/storage/Synths`), with the two
addin catalog entries from #144 added to a copy of the live catalog (`CATALOG_URL` compiled to a `file://` path on the device, since the
device can't reach this computer's firewall-blocked HTTP server). All seven rows pass: Acid installed, loaded and removed through the manager
(one restart each way, `MPC.settings.bak-acid-*` written each time); MPC Remote 0.2.1 installed from the Addins pill to
`/data/mpc-addins/remote`, listed in the `90-mpc-addins.conf` drop-in and in MPC's own `LD_PRELOAD` after the restart, answering on 6720 with
a screen capture, then removed (folder, drop-in line and port gone). The manager's offline suite gained a fake device for the Key 37's layout.
Also verified: a vst.json `"tile"` (#90's tooling) shows in the INSTRUMENTS browser and opens its Default preset, which loads the plugin on
the track. Presets are indexed at MPC start only: a tile installed without a restart is drawn but its tap does nothing until the next start,
and the install's own restart covers it. Taps were injected over the network with the remote addin's standalone: a touch needs a hold of
about 300 ms to register, the first touch after a project opens is often dropped, and a field popup (PLUGIN) opens on a double-tap.

### 2026-10-03: the commander addin loads on the Key 37 without an MPC restart (pre-install check)
mpc-addin-commander 0.1.0 (the plugins MPC loads, served to a desktop app; a sequencer port for transport and MIDI; a project snapshot)
was checked on the Key 37 (MPC OS 3.9.1) before any install, by preloading its `.so` into a copy of `/usr/bin/dbus-monitor` renamed `MPC`
in `/tmp` (the addin gates on the executable's name, so this starts it without touching the real MPC; BusyBox applets can't be used for
this: a copy named `MPC` says "applet not found"). Verified: it starts and serves on its port; `GET /project` reads `recentProject1` from
`/media/az01-internal/Settings/MPC/MPC.settings`, inflates the `.xpj` with the device's `libz.so.1` (loaded at run time) and reports the
real project's tempo, current sequence and 36 tracks with mixer state and plugins (stock instruments show as format `MPC`, e.g. `MPC:Hype`;
track kinds seen: 0 drum, 3 plugin, 6 audio, 7 return, 8 submix, 9 output, 10 input). **MPC hot-detects a new sequencer client and
connects it both ways by itself**: within a second of the port appearing, MPC's client 129 had new ports "MPC Commander Out/In" connected to
the addin's `Out`/`In` (`/proc/asound/seq/clients`), with no restart and no preference change (`MidiDevices.AutoEnableForTracks=1`). Whether
MPC also sends clock/MMC on such a port without the sync output being enabled in preferences is not verified yet. A leftover check process
keeps its sequencer client (and MPC's mirror ports) until killed: find it through `/proc/*/exe`, never by the name `MPC`. Release tooling
found: `release_addin.py`/`release.py` read the glibc requirement by scanning the file for `GLIBC_x.y` strings, so a `dlvsym` version
name in `.rodata` counted as a requirement; both now parse the ELF version-needs section (41ebc53). The real install (restart) is pending.

### 2026-10-03: the commander addin installed on the Key 37: plugins, MIDI and transport verified
Installed with the zip's `install.sh` (one restart; `MPC.settings` backed up first), then restarted once more to swap
in a fix. Inside MPC with Matt1 open: both NAM instances listed with all 60 params, values and display text; a `set`
from the computer changed NAM's Bass and MPC showed the new value; a note played into the addin's `In` port with
`aplaymidi` arrived as `midi_in`. Transport, learned on the device:
- MPC connects a new sequencer client both ways by itself and lists it as "MPC Commander In" (MPC's output to it) and
  "MPC Commander Out" (MPC's input from it) in `MidiDevices.Table`, with track on and sync on the output side.
- With clock sync out on the port, MPC sends MIDI clock (24 per beat at the project tempo). After a restart it sent
  none until the sync preferences were set again.
- MPC's Play sends no MIDI start: it sends an MMC locate (`F0 7F 00 06 44 06 01 hh mm ss ff F7`, a time code
  position with no sub-frame byte, 12 bytes) then MMC play, and pauses its clock while stopped. A clock-only follower would miss start.
- Play and stop sent from the computer as MMC (with MIDI real-time alongside) did nothing until **Receive MMC** was on;
  then MPC obeyed both and reported each change back over MMC. Preference changes are not written to
  `MPC.settings` right away (still 0 there afterwards), so the file can't be used to check them.

### 2026-10-03: MPC obeys an MMC locate from the commander app
With Receive MMC on for the addin's port and the transport stopped, an MMC locate sent from the app
(`F0 7F 7F 06 44 06 01 hh mm ss ff sf F7`, 30 fps) moves MPC's playhead: after a locate to 0:00:10.05 (bar 5 at
94.19 bpm in 4/4) MPC's next Play reported its start as `F0 7F 00 06 44 06 01 00 00 0A 05 F7`, and after a locate
to zero as all zeros. MPC's own locate is the 12-byte form without the sub-frame byte, so a decoder that wants the
13-byte form misses it (the commander addin takes both since then).

### 2026-10-03: recording from the commander app; what a restart drops
- Record from the app works: the MMC record strobe then play (`F0 7F 7F 06 06 F7`, `F0 7F 7F 06 02 F7`) put MPC in
  record, and MPC reported it back over MMC (the addin's transport showed `recording: true`); MMC stop ended it.
- MPC ignores transport (MMC and real-time alike) while its New Project dialog is up, which it shows at startup
  when `MpcEditor.Show.NewProjectDialogAtStartup` is 1. Open or create a project first.
- Receive MMC set in the preferences was never written to `MPC.settings` (`receiveMMC` stayed 0), so a restart
  turned it off again. Setting `receiveMMC` to 1 in the file with MPC stopped keeps it across restarts. The port's
  per-device entry in `MidiDevices.Table` has its own `sync` flag per direction.

## 2026-10-03: drum-pad patch name table gains Machinemodule and Lucky Dip (script v3)
`matcher.S` now lists `Machinemodule` (the renamed Machinedrum Module; the old name stays for older installs) and `Lucky Dip`.
Patched checksum `7cf96599ec61b1079688f253f3b65b9f`. The script recognises the previous published build (`f899e581...`) as an
earlier version and upgrades it. Offline: `test_matcher.sh` (qemu-user, 8 names match, 15 others fall through) and
`test_script.sh` (BusyBox 1.36, 23 cases incl. upgrade from `f899e581...`; working copies are removed between cases to keep a
tmpfs from filling) all pass. Not yet run on a device in this form.
  Rebased on main's script v5 on 2026-10-04 (script v6): the same name table, regenerated with `build_script.py`, the patched
  checksum `7cf96599...` unchanged, v5's patched build (`f899e581...`) is recognised as an earlier version and upgraded;
  `catalog/patches.json` re-pinned to this script (`tools/patch_check.py` OK). `test_matcher.sh` (qemu-user) passes: the eight names
  match and `Lucky`, `Lucky Dips`, `Machinemodule Tap` and the others fall through. `tools/test_patches.py` has one failure
  (`test_confirmed_install_needs_no_typed_word_then_undo`) with this host's dash, identical on main, not caused by this change.

## Sample-accurate note starts (opt-in, 2026-10-03; offline only here, device numbers from issue #137)
`effProcessEvents` used to hand each event to `engine->midi()` and drop `VstMidiEvent.deltaFrames`, so every note started at
the block start (README's "128-sample blocks, ~3 ms"). Reported on a Force (MPC 3.x, issue #137): sequenced notes arrive with
`deltaFrames` 0..127 (e.g. 9, 73, 72, 8, 71, 7), drifting with tempo; live pad notes always 0. `"defines": {"SAMPLE_ACCURATE": 1}`
(instruments only; an effect build is an `#error`) makes the wrapper queue each block's events (256 at most, sorted by frame, more
are applied at once) and render the block in pieces: `render()` gets exactly the frames up to the next event, at most 128 per call,
the event goes in, the rest follows. No 128-frame buffering in that mode, so a host block that is not a multiple of 128 is
handled too, and there is no added latency. An event past the end of the block (`deltaFrames >= n`) goes in at the start of the next
one; a negative one at frame 0. Cost: up to one `render()` call per distinct event frame, so bench a dense chord on a heavy engine.
Default off: every existing port builds as before, because engines written for 128-frame blocks (block-counting sequencers,
fixed-block cores) may not take other sizes. Test: `poc/sampleprobe` (note-on switches a constant level on from the next frame) with
the `SAMPLE_PROBE` section of `tools/host_test.c`; with the define set to 0 the same checks fail, so they do test the wrapper.
Still to do on a device: the first real port to opt in.

- **A real 2.15.1 skin (stock Decimator `TUI.json` and `Q-Links.json`, sent by a user, read 2026-10-03; analysed in scratch, never committed).** `TUI.json`: tab `version 1` with the page inline as `componentDefinition` (`version 2`: `actions`, `backgroundData`, `ignoreMousePresses`, `disableCoarseDataWheel`, `componentsData`), no local definitions, children `version 2` with `bounds version 1`, knobs of the shared type `knobYellow` (from `AKAI Components/AKAI Generic Components.json`), imports by relative path (`../../Generic/...`, `../../AKAI Components/...`), one `Image` child for the artwork. Ours: tab `version 3` pointing at a local definition by `componentName` (plus `initialSize`, `scale`), definitions `version 4` (adds `repeats`, `hideQLinkBounds`), film-strip `Knob` data `version 5`, `Button` data `version 2` (adds `gestureBehaviour`), absolute imports. (`bounds version 2`, which adds `additionalInvalidatingHandles`, also exists on 2.15.1, so it is not a difference.) `Q-Links.json` is the same on 2.15.1 and on the Force (`version 4`, `Screen Mode Q-Links` `version 4`), so it is not the cause. A 2.15.1 skin with local definitions exists too (AIR Compressor `GUI-Popout.json`: `localComponentDefinitions`, `value.version 2`). **Film-strip knobs exist on 2.15.1 (AIR Amp Sim `TUI.json`, 2026-10-03):** type `Knob`, data `version 1` with only `knobType: FilmStrip`, `filmStrip`, `numFrames`, `handleName` (ours, version 5, also has `invert` and `dragOrientation`); `Button` data `version 1` has `onImage`, `offImage`, `buttonId`, `numButtonsInGroup`, `handleName`. `Image`, `Label` and `Focus` data are identical to ours. Local widget definitions are `value.version 2` (with `disableCoarseDataWheel`) or `1` (without it), never with `repeats` or `hideQLinkBounds`. **Offline conversion test (scratch, not in the repo):** Dexed 1.0.4's `TUI.json` converted by those rules (tab 3 to 1 with the page inlined, definitions 4 to 2 without `repeats`/`hideQLinkBounds`, `Knob` 5 to 1, `Button` 2 to 1) has only versions 1 and 2 (2009 and 1643 objects), and its tab and page-definition key sets equal the stock Amp Sim tab's. It loses `gestureBehaviour: Instant` on 79 buttons and `invert: false`, `dragOrientation: Vertical` on 3 knobs. **Not yet tried on a device.**


## 2026-10-03: Force SSD is mounted `noexec`, plugins installed there only show "Load Plugin" (user report, Force, volume `/media/SSD - Force`)

A user batch-installed plugins to the Force's SSD with the desktop installer: all listed under VST, each shows only "Load Plugin" when added to a track. The same plugins installed to the SD card load fine. The user's mount line:
```
/dev/sda1 on /media/SSD - Force type exfat (rw,nosuid,nodev,noexec,relatime,nosymfollow,fmask=0022,dmask=0022,iocharset=utf8,errors=remount-ro,uhelper=edisksd)
```
- **Cause: `noexec`.** MPC cannot `dlopen` a `.so` from that mount. Not the plugin build, not the glibc, and not the spaces in the volume name. This differs from the 2026-09-29 test, where an exFAT USB stick (`/dev/sda1`, no `noexec`) loaded and played, so the options depend on how the drive is mounted (here `uhelper=edisksd`, a drive in the Force's SSD slot): always check the mount line, not the filesystem.
- Independent report (issue #150, Force Gen1, MPC OS 3.9.1): the ForceHD SSD is `noexec`; their patch makes only `/media/ForceHD/vst` executable and loads Dexed and Plaits from it. Not run by us.
- Workaround: install to the internal drive or an SD card (`/sdcard/Synths`).
- Second user report (2026-10-04, Force, volume `/media/FORCE 2`, installer app / web UI): same "mounted noexec" refusal. Fix that worked for them: create a `Synths` folder at the root of the internal drive (with WinSCP) and install there; plugins then load. User report, not run by us. Remounting the drive `exec` is not something we do or document (it needs MPC stopped and a hand edit of the mounts); see `docs/PATCHES.md`.
- **Desktop app bug found while looking (not the cause), fixed:** `readInfo` (`tools/desktop/device.go`) took the mount point from `df ... $NF`, so `/media/SSD - Force` became `Force`; the `/proc/mounts` lookup then found nothing (it writes spaces as `\040`) and the filesystem and options came back empty, which also skipped the symlink and read-only checks. It now reads `df -kP` fields 6+ and matches the escaped name.
- **noexec check (host tests only, not run on a Force):** the app flags a location mounted `noexec` (`Root.NoExec`, a note on the location, install refused with the reason); `install.sh` prints a warning (it still installs, so a hand-made exec mount is not blocked). Tests: `TestNoexecMountWithSpacesInItsNameIsFlaggedAndRefused` (fake BusyBox-style `df` line and an escaped `/proc/mounts` line; fails with the old parsing), `tools.test_catalog` (70 OK), `install.sh` fragment run against a fake `df` and `/proc/mounts` with and without `noexec`.

## 2026-10-03: network addins bind to 127.0.0.1 by default; the hardened installer on a device (Key 37)
Remote 0.2.2 and Commander 0.1.1 (both built with the installer from 83c6cbd) installed with `install.sh -y -n`, then one
restart. Commander upgraded over 0.1.0 and kept the device's `bind=0.0.0.0`; Remote went on fresh and listened on
`127.0.0.1:6720` only (`netstat -ltn`). From a computer on the LAN, port 6720 refused the connection, and through
`ssh -N -L 16720:127.0.0.1:6720 root@<device>` `/info` and `/screen.png` answered. The shared drop-in gained its
`# lib: 2` line. `sh /data/mpc-addins/remote/uninstall.sh -y` then took Remote out of `LD_PRELOAD`, restarted MPC and
removed the folder (nothing else was in it); Commander and the usb-audio addin kept running. The install message of an
upgrade says the addin listens on the device only even when the kept settings say `bind=0.0.0.0`.

## Stepping of option lists and whole numbers: `settle()` (2026-10-04, offline; from #130 and the Force input probe)
Until now an integer param kept an unrounded "shadow" position so a slow Q-Link turn accumulated, and an option list stepped one
option per event. Two measurements say that cannot serve both inputs: on a Force (MPC OS 3.9.1, "Input probe" above) a Q-Link event
is the read-back value plus 1/128 of the range and a data wheel click the read-back value plus 0.01, one event per detent, so the
wrapper cannot tell them apart; on an MPC One (#130) the wheel on a 1..8 param "only trembled" with the shadow (0.07 of a step per
click, 14 clicks per step) and a drag or Q-Link sweep, measured from where it started, flickered between two values. `settle()`
(wrapper/vst2_wrap.c, code from #130 by poloq-instruments) rounds toward the way the value moves: from the host's last position
while it moves continuously, else from the current value; `shadow[]` is gone. Result: one step per wheel click or Q-Link event, a
sweep up or down without flicker. Cost: a short whole-number range (1..8) crosses its range in about seven Q-Link events on a Force,
where the shadow took about 18 per step. Counting several events per step is #90's opt-in `qlink_ticks`, because the wheel then needs
as many clicks. Test: `poc/steptest` with the stepping section of `tools/host_test.c` (six wheel clicks, six Q-Link events, a sweep
up and back, for an option list and an integer); on the previous wrapper the same checks fail. Not yet re-checked with a hand on a
Q-Link or the wheel after this change.

**Checked on a Force (MPC OS 3.9.1, 2026-10-04), probe build of poc/inputprobe with this wrapper:** `S` is what MPC sent, `E` what the engine got.
- Q-Link on `int` (1..8): each event is +0.055 from the read-back value and steps one whole number (4 events: 5, 6, 7, 8), the known
  cost. On `opt` (9 options) each event steps one option (8 events: 1 to 8).
- Data wheel: +0.07 (`int`) and +0.08/+0.12 (`opt`) per click, one step per click (0 to 5 in six clicks).
- A slow touch drag (0.2 to 0.3 step per event) goes up and back down steadily: engine values 1,2,2,3,3,3,3,4,4,4,4,5,5,5, then
  back to 1 with the reversal taking effect at once. No flicker.
- **A fast drag (0.5 to 0.9 step per event) flickered once:** positions 7.66, 7.22, 6.66, 6.11 gave 7, 7, 6, 7, then 5, 4, 3, 2, 1.
  When two events are half a step or more apart, `settle()` ignores the host's last position and takes the direction from the
  value: 6.11 against a value of 6 reads as "up". The same numbers are what a wheel reversal sends (pos = value - 0.07 after an up
  click, 0.86 above the previous position), so the two cannot be told apart from one event; the 0.5 limit is the compromise that keeps
  wheel reversals right. Known limit: a fast drag over a short range can step one the wrong way at a time.

## Restarting MPC from inside a plugin via `systemd-run` (MPC One, 2026-10-01)
For a plugin that must restart MPC (e.g. to register a new `pluginList-arm` entry), the restart script must not be a plain
child: `acvs.service` has `KillMode=control-group`, so `systemctl stop acvs` kills everything spawned from MPC.
`systemd-run --unit=<name> --collect /bin/sh <script>` starts a transient service in its own cgroup instead. Verified:
launched from a shell placed in `/system.slice/acvs.service` with `LD_PRELOAD=/usr/lib/libforce_cursor.so` set (as a
plugin child would be), `systemd-run` returned 0; the script ran in `/system.slice/<name>.service` with `LD_PRELOAD`
unset (systemd builds the unit's environment, nothing is inherited from MPC), stopped `acvs` (rc 0, inactive),
survived the stop, started it again (new MPC pid, active ~8 s later). The device also has `unzip`, `sha256sum`, `wget`
(BusyBox 1.36.1), `libarchive.so.13`, `libz.so.1`. On this unit `/sdcard` is an empty dir on the nearly full root fs
(~17 MB free); plugins live in `/media/az01-internal/Synths`.

## Plugin Manager POC: install from the MPC screen (MPC One, 2026-10-01)
`mpc-vst-manager` (separate folder) lists `catalog.json` on the plugin's screen, queues installs/removals and applies them:
the plugin downloads each zip with the system libcurl (`dlopen("libcurl.so.4")`, CA bundle `/etc/ssl/certs/ca-certificates.crt`),
checks the catalog sha256 with `sha256sum`, unpacks with `unzip` (children spawned with a clean environment), writes `apply.sh`
and starts it with `systemd-run`, which stops MPC, runs the package's own `install.sh -y [-n] -t /media/az01-internal/Synths`
and starts MPC. Verified end to end with MPC Plaits 1.0.0: one plugin-list entry, settings backup made, MPC back up.
Lessons: GitHub release downloads from the device can stall for tens of seconds (a 30 s low-speed abort failed at 4.5/7 MB),
so resume with `CURLOPT_RESUME_FROM_LARGE` and retry; and text a worker thread changes is never redrawn unless the plugin
sends `audioMasterUpdateDisplay`: `HAS_DISPLAY_REV` in the wrapper polls the engine's `display_rev` every ~100 ms for that.

## MPC's filmstrip cache fills internal storage over a session (MPC One, 2026-10-01)
Every time a plugin screen loads, MPC decodes its filmstrip images (knobs, sliders, `meter`s: `Knob` components with
`knobType: FilmStrip`) into `/var/tmp/filmstrips/temp_<hex>.img`, raw RGBA, and never deletes them while running. `/var` is
an overlay whose upper dir is on the internal data partition (`/data/system/var/overlay`, the same 2.7 GB partition as
`/media/az01-internal`), so the cache eats the space plugins and settings live on. All files dated from the last boot,
so a reboot seems to clear it (not confirmed); MPC restarts (`acvs`) don't. A test session with many plugin reloads
and restarts reached 729 files / 2.2 GB and filled the partition (copies failed with "No space left on device").
The files are not held open between loads, so `rm -f /var/tmp/filmstrips/temp_*.img` frees the space safely
(delete through `/var`, never the overlay's upper dir).
Size per load is frames × frame area × 4. Filmstrip frames used to be square-padded (`square_strip`), so a wide thin
bar as a `meter` was very expensive (a 360×4 bar became 128 frames of 360×360 = 66 MB per load); since 2026-10-07
slider and meter frames are their own w × h (see "reported by other forks" below), which makes that bar ~0.7 MB. For bars use `picture`
(one image per step, mode images, no filmstrip), as the Plugin Manager does.

## Device screenshots (MPC One, 2026-10-01)
`/dev/fb0` exists but stays black: MPC draws through DRM/KMS. The scanout buffer is readable instead: `/dev/dri/card0`
(the display; `card1` is the GPU and refuses KMS ioctls) has one active CRTC with an 800x1280 XRGB8888 buffer, linear
(modifier 0), so GETFB2 + PRIME export + mmap gives the exact screen. The panel is portrait: rotate 270 degrees. The plugin
area is 1280x628 at y=110 of the upright image. `tools/screenshot.sh` does all of it.
Same on an MPC Key 37 (MPC 3.9.1.2, 2026-10-05): the same 800x1280 portrait scanout, upright after the rotation, and
`--plugin` crops both an instrument's edit screen and an insert effect's screen cleanly (both headers are 110 px tall).
The catalog shots for NAM, Chordsmith and Keyscope were taken this way.

## 2026-10-03: patches step (read only) in the installer app, offline only
Design in `docs/PATCHES.md`. Built so far: the drum-pad patch script v4 (`status` ends with a `STATE` line; `install --confirmed` skips the typed question; `status` unmounts the bind mount of `/` that it opened, which v1-v3 left mounted: found by reading the script, fixed and checked with shimmed `mount`/`umount`/`mountpoint`), `catalog/patches.json` + `tools/patch_check.py` (the site build publishes it only if it validates), and step 7 of the app (list and `status` only; no apply). Checked on the host only: `tools/test_patches.py` (13 tests: the script contract against a synthetic stand-in for the MPC binary with its checksums rewritten, the checker, the site build), `go test -race` in `tools/desktop` (new `patches_test.go`, six mutations each fail a test), and `tools/desktop/ui_test/ui_patches.py` (Chromium, API stubbed). **Not run:** `tools/mpc_patch/test_script.sh` with Akai's real MPC (not in the repo), the app against a real Force, or any apply/undo from the app (not built).

### 2026-10-04: the first user of the patches step got "firmware not supported" on the machine the patch was built on (script v5)
Force, Settings says MPC OS 3.9.1. The page showed "This firmware is not supported" with no reason. `status` on the device: `MPC checksum: 7cf96599ec61b1079688f253f3b65b9f`, state unsupported, `/sdcard/MPC-backup/MPC-3.9.1.2.orig` present (its md5 is the stock `592eebc8...`, checked on the device) and `orig-regions.txt` present. So the program is an unrecognised build, most likely an earlier development version of the patch (not confirmed; that checksum is not in the repo): neither stock, nor the current patch (`f899e581...`), nor the two known earlier builds. The app and the script were right; the problem was that `install` and `uninstall` both refused an unknown build, leaving a verified stock backup unusable, and the page gave no reason. Script v5: `uninstall` restores an unknown build from the full backup only when the backup's md5 is the stock one (typed `RESTORE` or `--confirmed`, result verified), `status` ends with `checksum=`; the app shows the checksum, what the patch supports and a pointer to the restore. Tests: `tools/test_patches.py` (the restore, its four refusals, the typed word, the checksum; each mutation-checked) and `patches_test.go`. **Not yet run on the Force:** the restore itself (it stops and restarts MPC and copies 112 MB over `/usr/bin/MPC`).

### 2026-10-04: desktop v0.3.5 tried on the Force that has the unknown MPC build
The patches step (read only) showed what it should on that device: "This firmware is not supported", the device's checksum `7cf96599ec61b1079688f253f3b65b9f`, the checksum and OS the patch supports, and the pointer to the saved backup. One bug in the same row: "a backup goes to true" (the manifest's `backup` folder and the device's has-backup flag shared the JSON key `backup`; the flag won). Fixed (`hasBackup`), with a test of the JSON. The restore from the verified backup has still not been run on the Force.

### 2026-10-04: restore of an unknown MPC build and reinstall of the patch, verified on a Force (script v5)
Force, Settings: MPC OS 3.9.1, MockbaMod. The device had an unrecognised MPC build (checksum `7cf96599ec61b1079688f253f3b65b9f`, see the entry above; what made it is not known) and a saved full backup whose md5 was the stock `592eebc8e1ce0797dc8c98e7002143b8`. With the project saved, the user ran script v5 (`tools/mpc_patch/mpc-drum-pad-patch.sh` at commit `0adeb93`) on the device, over SSH as root: `uninstall` (typed `RESTORE`) printed `restored stock MPC from the full backup`; `install` (typed `PATCH`) printed `patched OK`; the final `status` ended with `state=patched` and the patched checksum `f899e581cba179a831212083f9a55ae0`; and step 7 of the desktop app (v0.3.5) then showed the patch as **Applied**. All four checks passed, reported by the user (the output was not pasted, so the exact lines were not captured here). So on one device and one firmware build the restore-from-backup path of `uninstall`, the reinstall, the `STATE` line with `checksum=` and the app's row all work. Not covered: another firmware, a backup that is not stock (refused in the offline tests only), a device with no backup (offline only), and Apply/Undo from the app (not built).

### Q-Link slow-down prototypes on a Force (MPC OS 3.9.1, 2026-10-04): none kept
Tried on top of `settle()` with the probe build (all offline-tested, then felt on the Force). A Q-Link event is the read-back value plus a
whole number of 1/128 of the range, exact to float precision; a slow turn sends a repeating 1, 2, 3 units.
- **Count units, suppress the event (4 units per step):** wheel and drags unaffected, but the knob does not follow between steps and
  the cadence is uneven (1, 2, 3 units per event): "sticky/jumpy". A touch drag event that happened to be a whole number of 1/128 within
  0.03 (8.03) was counted as a Q-Link burst and jumped two steps up in a downward drag; the test needs to be exact (0.002).
- **Smooth the knob (return a fractional read-back, 8 units per step):** works on an option list (MPC adopts the read-back: 41 events,
  a step per 8 units) but not on a whole number: MPC kept its own count (S 1.05, 1.11, 1.05, 1.11 against read-backs 1.00, 1.12), the
  event after the first looked like a drag and cleared the count, so a slow turn stayed on 1 for 153 events; fast turns jumped out of it.
  The old unrounded "shadow" worked because it returned exactly what MPC had sent; a scaled read-back does not.
- **Touch drag:** `settle()`'s ceil/floor makes the end values reachable only at the very end of the travel and the first event of a
  drag cannot be told from a wheel click (same numbers), so it can step one the wrong way. Plain rounding for continuous drags fixed the
  ends, but a selection on a step must clear the stored drag position or the next wheel click does nothing.
Not tried: what MPC does with a read-back on a multiple of 1/128 for a whole number, and how the stock plugins handle the same Q-Link
(ROADMAP). Per-param counting stays an opt-in in #90 (`qlink_ticks`) with this caveat.

## Engine-driven skins: long text, when= panels and meters switch without a tap (MPC One, 2026-10-01, poc/uiprobe)
`poc/uiprobe` (62 params, 152 IndexedEnabling parts, `HAS_DISPLAY_REV` + `PARAM_TEXT_MAX 128`), nothing touched:
- **Value text up to 80+ characters shows in full** on a wide readout. The 23-character limit was only the wrapper's own
  copy (`copy_str(…, 24)`); `PARAM_TEXT_MAX` raises it per port.
- **when= panels follow values the engine changes by itself** (a 4-state phase every 2 s, three rows with a 6-way
  button state and two badges, 40 three-way values every 0.5 s), once the wrapper reports them with
  `audioMasterAutomate` (it does now under `HAS_DISPLAY_REV`, for every non-text, non-trigger param whose value moved).
- **`meter` redraws live** from an engine-driven value (a 2 s sawtooth), pauses and resumes with it.
- **A dense page stays responsive**: the 40-value tab cycling every 0.5 s, with pads, scrolling and tab switches normal.
So a skin can be a real app screen: status lines, state-dependent buttons/badges/banners and progress bars, all driven
from a worker thread.
Since 2026-10-04 the wrapper re-reads every text readout every 100 ms anyway (see the readout poll above), which covers
status text on its own. `HAS_DISPLAY_REV` runs on that same poll and adds the rest: values that aren't text (states,
meters) and the `when=` panels that hang on them. Rebased on that poll 2026-10-05; not re-run on the device since.

## 2026-10-01: MIDI-generator and control-surface facts from Chordsmith on an MPC Key 37
- **Own port echoes back.** MPC enables a plugin's new ALSA port for track input (`MidiDevices.AutoEnableForTracks`), so every note-on and note-off a MIDI-generating plugin sends comes back into its own track moments later, on the channel it was sent on (verified: output on ch2 returns on ch2, keys stay on ch1). Count sent ons and offs per channel and note and swallow exactly those; filtering only "a note-on for a note still sounding" lets a re-chord's note-offs through as keys let go, which in a mode where every note is a root ran away into a cascade of chords.
- **MPC merges an echo with a held key on the same channel and note**: the key's note-off never reaches the plugin and its chord hangs. Default a generator's output to a channel other than the keys' (ch2). The merged echo's note-on never reaches the plugin either (verified 2026-10-01: the chord's other three echoes came back, the held note's did not, and no note-off followed the key release), so a plugin cannot detect the clash from the echo itself: Chordsmith flags it when a sent note on the keys' channel, for a key still held, has no echo back after 250 ms while other echoes have been seen.
- **Pads send their pad-mode notes**, not 36-51: with a scale pad layout the 16 pads sent C-major notes from C5 (72-98). A plugin that maps pads by note needs the track's pads on plain chromatic notes.
- **Q-Links** are relative encoders on the control surface (CC 0x10-0x13 on ch1, 01 = +1, 7f = -1, accelerated up to about ±4; CC 0x64 is the jog wheel). What MPC makes of them is in "Input probe" above: each event is the value MPC last read back plus a whole number of 1/128 of the range. The Key 37 measurement here (2026-10-02, a logging build, a hand on a Q-Link) agrees with the Force's: one 1/128 step per event on a slow turn, from the read-back value, never from where the turn started. The two differ only in a fast spin: the Key 37's smooth encoders give about 80 events per revolution (a hair of rotation is already 3) and accelerate to about 10 steps per event, 10 ms apart, where the Force probe saw 1 to 3 per event; one run each, so treat both as ranges. In a spin MPC's own running value drifts from the plugin's snapped option until it reads back (after about a second idle it reads back and starts from there again), so a counted direction is noisy and the direct-set branch (a move of half a step or more) does the work. With `settle()` (one step per event) a 9-option list races by on a Key 37 Q-Link and a wobble flips a switch. Opt-in `qlink_ticks` counts events per option or whole-number step instead: at 3 a 9-option list went by in a quarter turn; at 6 about half a turn, a wobble never flipped anything, and a spin walked the list without racing. The count does not time out, so two tiny nudges add up like a detented knob. It stays per param and off by default: the data wheel sends the same small moves (0.01 per click, "Input probe"), so it takes N clicks per step too, and on a Force a counted Q-Link felt sticky and uneven ("Q-Link slow-down prototypes on a Force" above). `"qlink_ticks": 6` is the value for a short list on a port that wants it, checked on a Key 37 only.
- **Tapping the option already selected in a popup list sends nothing** (no setParameter), so the wrapper can't close the list then; tapping the field again closes it.
- **Value text was cut at 23 characters** by the wrapper's own 24-byte copy in effGetParamDisplay, not by MPC. #130 adds `PARAM_TEXT_MAX` (48 in vst.json "defines" shows 47 characters) so a status readout can say a whole sentence; until it merges, text is cut at 23. MPC drew a 42-character readout whole (2026-10-01, Chordsmith).
- **Seven tabs** show as five plus a ">" pager; page 2 shows "<" and the last five.
- **Instruments-browser tiles** (verified 2026-10-01, Key 37, 3.9.1.2). Sounds > INSTRUMENTS draws a plugin as a 270x110 artwork tile when its plugin folder holds `Plugin Skins/browser_images/soundsmode.png` (`.jpg` is tried second); the page builder resolves every plugin in the plugin list to its folder (`<location>/Instruments/<folder>/Plugin Skins`, then `<location>/<folder>/Plugin Skins`) and looks there. The file is read when the page is drawn: no restart. Akai's own instruments map through a name table to firmware `soundsbrowser/sounds-<name>.png` instead (an earlier note here claimed no lookup happens for VSTs; wrong, the file was in the wrong place). Tapping the tile opens the plugin's preset page, which lists `<plugin folder>/Presets/*.xpl` (indexed at MPC startup: new files need a restart); with no presets the tap does nothing. An `.xpl` is `<pluginstate>` with the plugin's `<PLUGIN .../>` description, `<preset>Name</preset>` and a `<state>` holding a JUCE fxb chunk set (`CcnK`/`FBCh`, the uid, the wrapper's chunk) in JUCE's base64 variant (`<size>.` + 6-bit groups, low bits first); `tools/xpl.py` writes one with an empty chunk (the engine's defaults) and `gen_vst.py` ships it with the tile for a vst.json `"tile"`, `file=` using `%payload-path%` that install.sh fills in (whether MPC matches the preset by uid alone is untested). Stock DrumSynth folders also hold a 64x64 `browser_images/trackedit.png`; its use is unverified. Presets saved on the device go to `MPC Documents/Plugin Presets/Instruments/<folder>/`.
- **Toggle and knob names** (MPC draws them from the param names) are a fixed 15-17 px and ignore `label_scale`, so a layout at 1.3 had small names under big values and a toggle's name overran its 120 px box. `scale_names=1` in layout.conf makes them 21 px × label_scale and grows the toggle box and its Q-Link bounds with them (checked on the device at 1.3); it is opt-in so no existing skin re-renders.

### 2026-10-04: a changed skin needs an MPC restart; skins are found by folder name (Key 37, MPC OS 3.9.1)
- Re-inserting the plugin does **not** reload a changed skin: MPC keeps skins in memory and only a restart showed the new one. This
  corrects the 2026-09-24 note and the skill's earlier "skin-only change needs no restart". Browser tiles and `.so` updates are
  unchanged (see above).
- MPC finds a skin by folder name (`<vendor> - VST - <product>`, beside the plugin folder), even when the `.so` loads from another folder.
- The filmstrip cache (2026-10-03 note above) filled the 2.5 GB `/data` partition after a day of restarts (1,201 files, 2.4 GB): the next
  MPC start wrote empty cache files and an addin install failed with "No space left on device" (its `.new` staging kept the live install
  intact). The running MPC had none of the files open and deleting them freed the space. Whether a reboot clears the folder is not known.
- Credit: found by jacob-sabella (PR #162, closed; written up here).

## Knob filmstrips over 16384 px drift as they turn (MPC One, 2026-09-27, MPC Plaits)
A knob with r=80 (170 px frames x 128 = 21760 px strip) visibly moved up and down on the screen while its value
changed; r=58 knobs (126 px frames, 16128 px) on the same page were fine. Most likely MPC's image/texture limit of
16384 px, beyond which the strip is resampled and the frame offsets no longer line up. Keep `2r+10 <= 128`, i.e.
r <= 58 (the largest seen working; r=59 lands exactly on 16384 and is untested). `shadow_skin.py` now warns.

## step_of on an option param (2026-09-27, MPC Plaits)
`step_of`/`step_delta` now also works when the target is an option list: it steps by index, wrapping like a hardware
selector button, and reports the new value with `audioMasterAutomate` from `processReplacing` so the host redraws
anything bound to it (the value text, `IndexedEnabling` pictures). Used for Plaits' two model buttons (a `stepper`
with `prev=`/`next=`). Verified offline; not yet on a device.

## Eurorack/firmware DSP assumes zeroed RAM; a plugin's heap isn't (MPC One, 2026-09-27, MPC Plaits)
Plaits' FM 2-Op engine and most engines after it played silence inside MPC but fine in every offline test (x86,
32-bit ARM under QEMU, and `tools/bench.sh` on the device itself). A device log showed healthy raw engine output
and LPG gain, yet the voice output stayed at Plaits' silence value. Cause: several engines' `Init()` never set
some state (e.g. `FMEngine`'s downsampler taps). On the module that RAM is `.bss`, zeroed at boot; MPC's
long-running process hands the plugin reused heap, so the state could start as NaN, which then stuck in the
voice's LPG filter (a NaN reaches ARM's float->int conversion as 0, i.e. silence) and silenced every LPG engine
on that voice. Fresh test processes get zeroed pages, which is why nothing offline ever failed. Reproduced
offline by overriding `operator new` to fill allocations with 0xFF (`mpc-vst-plaits/tests/dirty_heap.cc`); fixed
by allocating the engine state with `calloc` + placement new. For any port of firmware code: allocate its state
zeroed, and run the host tests with a dirty heap.

## 2026-10-05: ForceHD VST Exec (timomacquis, #150) read in full, adapted and tested offline; not yet run on a device by us
The contributor shared his package (a systemd timer service that makes one folder of a `noexec` SSD executable) and gave it to the project (the maintainer's word; the maintainer is confirming the licence with him; a written confirmation on #150 is wanted). **Listed as untested** (2026-10-05): the maintainer has no SSD to test with, so the patch is marked untested in the manifest summary and the guides and testers are being asked for. All 25 files were read, nothing was run on a device; the shell files parse (`dash -n`), the distribution zip's scripts and units equal its `Source/`, no network access or `eval` anywhere.
- **His evidence (his logs, a Force Gen1, MPC OS 3.9.1, kernel `6.18.26-az01`):** the SSD is an exFAT partition that `edisksd` mounts at `/media/<volume label>` as `rw,nosuid,nodev,noexec,relatime,nosymfollow,...` (the same line our SSD user reported). `dlopen` of a probe library on it fails with "failed to map segment from shared object"; inside his child bind mount (remounted with `exec`, parent unchanged) it loads; a copy outside the folder still fails. Persistent after a full reboot (bootstrap 1.17 s, MPC active at 7.4 s), Dexed and Plaits sound and reopen a saved project. His stated gaps: auto-loading a project before the SSD is ready, absent/late/reconnected disk cases, and the 0.1.3 uninstall and helper apply/revert were not validated on hardware; the English edition was never run on a Force.
- **Our review found:** it hard-codes the drive name `/media/ForceHD` and the folder `vst`; the `/proc/self/mountinfo` compare (`awk '$5==p'`) cannot match a name with a space (the table writes `\040`; reproduced); our plugins keep the `.so` in `Synths/<skin>/`, which his folder choice leaves `noexec`; `status` exits non-zero when inactive and has no machine-readable line; the timer polls forever while the drive is absent; the unit goes into the factory image (`/usr/lib/systemd/system`, root remounted writable then restored). The mount logic itself is careful: `flock`, mount-ID ownership, parent-mount check, a rollback trap, no forced or lazy unmount.
- **Adapted (version 0.2.0, `tools/mpc_patch/drive_exec`, **renamed "drive exec" on 2026-10-05**: nothing in it is specific to that drive or to a Force, "ForceHD" was the label of the contributor's own drive; the on-device names are `/etc/drive-exec`, `drive-exec.timer` and so on, so it never collides with his original `force-vst-exec`, which `status` reports and `install` refuses to touch, `reason=other-install`):** drive and folder chosen and strictly validated (the config is sourced by a root service), default folder `Synths`, mountinfo paths compared escaped, the empty `acvs` drop-in dropped, a wrapper with the `STATE` line (new state `partial`, new `reason=` tokens), typed words, one file. His three systemd units are his, with only the names changed.
- **Tested offline, with real mounts** (`tools/test_drive_exec.py`, root, `unshare -m`): a `noexec` tmpfs at `/media/SSD - Force`; a compiled library really `dlopen`ed before, with, and after the patch (blocked, loads from `Synths`, outside stays blocked, blocked again after removal); the parent mount's id and options never change; install, status, uninstall, repeated apply, an absent drive, a plugin held by a process blocks removal, a failed install rolls back, the typed words, hostile drive and folder names (really mounted, e.g. a quote, `$(...)`), a foreign mount, another version, and the embedded files equal `src/`. Seven mutations of the script each fail a test. **Not covered (tmpfs is not exFAT, no systemd, no MPC):** a Force, exFAT specifics, a reboot, MPC loading a plugin from the folder, `Register plugin folders` after, and any firmware update. The patch is listed in `catalog/patches.json` (read-only in the app); applying it from the app is not built.

## 2026-10-05: button remap as a device patch (hwremap), installer tested offline only
`tools/mpc_patch/hwremap` vendors https://github.com/mmiroshnikov/akai_standalone_remap at `9d2aa57a570b` (MIT; `hwremap.c`, its host test, `configs/mpc-live.conf`, `configs/force.conf`, unchanged) and installs it the same way as the other device patches: one script, `status` / `install` / `uninstall`, a typed word, a backup under `/data/mpc-vst-plugins/backups`. Listed in `catalog/patches.json` as `button-remap`. The library is 32-bit ARM, built with `arm32v7/gcc:11-bullseye`; the highest glibc symbol it needs is 2.17 (`clock_gettime`), plus `pipe2` from 2.9.
- **What the shim's author already tried** (that repo's README, not re-checked here): an MPC Live on Hakai, MPC 3.9.1, and a Force on stock firmware 3.9.0. Hakai gets `/usr/lib/hwremap.so` and a line in `/usr/bin/az01-launch-MPC`. The Force gets `/data/hwremap/hwremap.so` and a systemd drop-in that keeps the `LD_PRELOAD` already on `acvs`. Config is `/sdcard/hwremap.conf`.
- **This installer** picks those two styles itself (launcher file, otherwise `acvs` or `inmusic-mpc`), stops and starts MPC, rolls back a failed install, and will not overwrite a config that is already there or a hwremap that was installed by hand. **Not run on a device.** Offline: `tools/test_hwremap_patch.py` (scratch root, shims; both styles, typed words, rollback, an edited config, a preload that is not a plain path; the unpacked library matches the built `.so`, and the same hex decodes identically with BusyBox awk). The library's host tests passed under ASan/UBSan in Docker (`gcc:11`). The manifest URL is pinned to `82e1c322f8a511e9c8546e9ad1f891b4df54c1c4`.
- **Review fixes (offline, host-tested with a fake systemctl; not run on a device):** a launcher line with an unquoted `LD_PRELOAD=a.so cmd` now gets `:/usr/lib/hwremap.so` (a space made the library the command that ran), and the script checks the unpacked library's size and sha256 before it moves it into place (the awk unpacker has to emit NUL bytes, and a device awk that drops them would otherwise put a corrupt library into MPC's `LD_PRELOAD`). The script now also needs `wc`, `tr`, `cut` and `sha256sum`.

## 2026-10-10: the button-remap installer run on a Force; MockbaMod's input path
Force, MPC OS 3.x, over ssh with no terminal (so the checklist did not show).
- **Stock path works.** With MockbaMod's `boot.sh` moved aside, `sh hwremap-patch.sh install` (typed word on stdin, default options) installed the drop-in and `/data/hwremap/hwremap.so`; `status` reported patched, MPC's `LD_PRELOAD` held the remote addin and hwremap, and the library hooked "Akai Pro Force Private". By hand, every default rule worked: Edit twice (editor), Clip + Left (Arrange), Menu twice (Main Mode), Mixer twice (Master), Mixer + the four arrows (tabs). With the `skipback` rule added, the log showed `remap 93 (double)` (the note-127 tap went out; nothing listens for it). The Mode Menu was at its default layout. Not run on a device: `uninstall`, the checklist, the Knobs options, the MPC Live map.
- **Two installer bugs only a device showed** (fixed in the same PR): `status` chose the launcher style on a Force because `/usr/bin/az01-launch-MPC` exists there without an `LD_PRELOAD` line, and BusyBox's shell exits on `read < /dev/tty` when there is no tty even with `2>/dev/null ||` after it (dash does not, so the offline tests missed it).
- **MockbaMod on: the remap does nothing.** MockbaMod running with MidiLoop, hwremap loaded (a small addon appended it to MockbaMod's preload list): MPC opens a `Virtual RawMIDI` port only and the library, which filters the port named "...Private", attached to nothing.
- **MockbaMod on, MidiLoop disabled (its launcher `AddOns/run_midiloop.sh` renamed): no pads and no buttons after the restart.** Restored by renaming it back and restarting. On that install the controller's pads and buttons seem to depend on MidiLoop's preload library (`tkgl_anyctrl_lt.so`) or process. Not separated from hwremap being loaded in the same run, and not investigated further.

## 2026-10-09: hwremap on a Force, checked by hand (button notes, touch taps, combo rule); the installer's options are offline only
Tried on a Force (MPC OS 3.x) with a build of the vendored library loaded through an `acvs` drop-in and a config in `/sdcard/hwremap.conf`; the installer script itself was not run on it.
- **Button notes** (channel 1, from the library's input log): Edit 37, Clip 9, Mixer 11, Menu 2, Shift 49, Up 112, Down 113, Left 114, Right 115 (Rec read as 93; not used).
- **Touch taps** (`tX,Y` writes `ABS_MT_POSITION_X/Y`): the panel reports X 0..1280 and Y 0..720 (`EVIOCGABS` on `/dev/input/event0`) and is rotated against the 1280 x 800 screen: raw x = screen y x 1.6, raw y = 720 - screen x x 0.5625. Checked by taps that opened Arrange (`280,487`), Grid View (`280,360`) and the mixer's bottom tabs (`1232,540 / 301 / 181 / 421`). The stock config's `331,655` converts to screen (115, 207): the Clip Matrix tile at the top of the fixed left column, not the Main Mode house in the grid.
- **`m<Name>` does nothing on a Force.** It presses note 123 (the MPC Live's Menu button) and a channel-10 pad; the Force's Menu is note 2. The rule is logged as fired and MPC ignores it. The Force map therefore taps by position (`b2 t...`).
- **`combo HOLD SRC tokens...`** (the local patch in `VENDORED.md`) fired as designed: Clip (9) + Left (114) and Mixer (11) + Up/Down/Left/Right. The Mixer double-press rule and the Mixer + arrow rules did not interfere. Edit twice sending `d49 b9 u49` (Shift + Clip) opened the plugin editor; Mixer twice reached Master.
- **MockbaMod diverts the buttons.** With MockbaMod's `boot.sh` running, MPC opened only a `Virtual RawMIDI` port and the library, which filters the port named "...Private", attached to nothing (its log showed no buttons). With `boot.sh` renamed away, MPC opened `hw:1,0,1` ("Akai Pro Force Private") and the library hooked it. MockbaMod also rebuilds MPC's `LD_PRELOAD` from its own list file, replacing the drop-in's value.
- **MPC holds the touchscreen**: reading `/dev/input/event0` while a finger (or the remote addin) tapped returned nothing, yet the library's writes to it land. Calibrate by `EVIOCGABS` and a known icon, not by capturing taps.
- **`LD_PRELOAD` in a drop-in needs quotes when it holds a space** (`Environment="LD_PRELOAD=a.so b.so"`): unquoted, systemd splits it into two assignments and drops the value (the loaded unit kept the old list). The installer already writes it quoted.
- **After a full reboot MPC started without the drop-in's preloads** (no `LD_PRELOAD` in its environment; no library mapped) until `systemctl restart acvs`. Cause not found.
- **Installer 0.2.0 (offline only):** the Force map is option blocks (`mixer-master`, `mixer-tabs`, `edit-editor`, `clip-arrange`, `menu-main-mode`, `knobs-short`, `knobs-long`, `knobs-double`; Knobs off by default; `skipback` off too: Rec Arm twice taps note 127 as a placeholder trigger for the skipback-save addin, nothing listens yet, Rec Arm read as note 93 from the press order only). Install shows a checklist on a terminal or takes `--options`, `--with`, `--without`; `options` lists them; `status` shows the choice. `status` on the Force said "launcher" because `/usr/bin/az01-launch-MPC` exists there too (the script the service runs; it sets no `LD_PRELOAD`), so the style check now needs an `LD_PRELOAD=` line in that file and otherwise takes the systemd drop-in. The first real install attempt over ssh with no terminal died at the typed-word prompt: BusyBox's shell exits when `read < /dev/tty` cannot open the tty (`can't open /dev/tty`), even with `2>/dev/null` and a `|| read` fallback, and dash (the offline tests) does not, so the tty is now tried in a subshell first (nothing had been changed at that point). 32 offline tests pass (`tools/test_hwremap_patch.py`, dash; one checks the script text for the unguarded form), and the option, checklist and render paths were run under BusyBox sh and awk in Docker. The manifest URL is pinned to the commit that holds this script.
- **The `skipback` option was removed again (2026-10-10).** It tapped note 127 as a placeholder trigger for a skipback addin. The MPC Skipback addin (`sd88me/mpc-addin-skipback`, 0.3.0) turned out not to need a remap: it hooks `snd_rawmidi_read` on the Private port (read below `hwremap.so` in the preload chain, so it sees the raw hardware bytes, and the bytes pass through unchanged), sees Rec Arm (note 93) pressed twice within 350 ms, saves, and blinks the LED by writing a control change on channel 1 to the same port (controller = button, value = state). Verified on the Force (MPC 3.9.1) with this patch's `hwremap.so` loaded: the double press saved 30.0 s and the LED flashed. A remap-side action would also have had to sit before the addin in `LD_PRELOAD` to inject a note it could read, which the installer's append order doesn't give. An `f/PATH` token that creates a file was built for the same purpose and dropped unpushed. Script otherwise unchanged; manifest re-pinned.

## 2026-10-05: long integer lists skipped entries on a Q-Link and the wheel (Dexed banks, a Force); `nudge_pct` and `order=cols`
Reported on a Force (Dexed 1.0.5 test build): on the BANKS tab the bank Q-Link and the wheel skipped several carts at a time. Cause, from the wrapper (`wrapper/vst2_wrap.c`, "whole numbers"): the bank index is an integer parameter spanning 0..998, and MPC sends a Q-Link event as the read-back value plus 1/128 of the range and a wheel click as plus 1/100 (NOTES "Input probe"), i.e. about 8 and 10 entries on that span; `settle()` rounds toward the move, so each event landed that far on (a short range such as 0..31 stays one step per event, as measured). Fix, opt-in per parameter: `"nudge_pct": N` (gen_vst.py, `param_t.nudge_pct`) makes any move up to N% of the range one step in its direction (combinable with `qlink_ticks`); a larger move still sets outright, and a move that lands on the minimum or maximum from inside that distance counts as a step, because MPC clamps what it sends (a nudge down from bank 3 sends 0, not -4.8). Test: `poc/steptest` has a `long` 0..998 param with `nudge_pct` 10, and `tools/host_test.c` checks six Q-Link events and six wheel clicks up one step each, back down to the minimum, a jump landing outright, and a clamped move at the top (all pass, `tools/test_port.sh poc/steptest/vst.json`, 31 checks). Offline only; not yet tried with a hand on the Force. Same report: the BANKS lists numbered across each row (1 2 / 3 4 ...), so a Q-Link stepping through them jumped left and right; `list ... order=cols` (`shadow_skin.list_keys`) numbers down each column first (left column 1..rows, then the next), so the lists read and step top to bottom.

## 2026-10-07: reported by other forks (Live II, 2026-10-02..05; read from their notes, not re-verified here)
`saustin2010/vst_instruments` keeps a patch against an older commit of this repo (`framework/mpc-vst-plugins.patch`)
whose NOTES sections were verified on an MPC Live II by its owner. Summarised here so ports don't re-learn them; each
needs a check on our devices before it becomes a rule. Survey of the techniques: `docs/COMMUNITY_SKINS.md`.
- **FilmStrip `numFrames` is the frame count.** Stock skins use non-square frames: frame height = image height /
  `numFrames` (Bassline `knob_phase` 76x258 = 3 frames of 86; Electric `slider_distance` 250x6969 = 101 of 69).
  Display meters square-padded and resampled to 128 frames with `numFrames` 127 drew each frame a few px off per step
  (~4.5 px with 32 frames of 141 px). Laid out as stock (frames of the meter's own w x h, `numFrames` = count) they
  drew right. Knob strips (128 square frames, `numFrames` 127) are fine as they are.
- **Tall slider strips.** Square-padded 128-frame slider strips 16640 to 30720 px tall animated wrongly; knob strips
  up to 96x12288 are fine. Their builder caps slider strips at 12288 px (fewer frames). Compare our own 16384 px
  knob limit ("Knob filmstrips over 16384 px drift", 2026-09-27).
- **Animation is expensive.** A display parameter changed from `processReplacing` plus `audioMasterUpdateDisplay` or
  `audioMasterAutomate` does repaint, but MPC's main (screen) thread pays: one 566x122 strip at 15 fps 25-55% of a
  core; a 48-column dot scope at 10 fps 46-58% (peaks ~95%); with one `audioMasterAutomate` per column 107-113%.
  Audio threads were unaffected. Keep pictures still between changes. MPC decodes skin images at 4 bytes/pixel:
  a 566x122 x 384-frame set is ~106 MB of ~970 MB free.
- **Q-Link outlines: one per column.** A 4-knob MPC drives one 4-slot column at a time and outlines that column's
  `qlinkBoundsData` rectangle, so lay each column's controls out together (cf. our `qlink_bounds=column`).
- **The Q-Link sidebar covers x >= ~1025.** Touching a Q-Link slides MPC's panel over the right ~255 px of the page;
  keep controls you watch while turning out of that strip.
- **MPC's PRESET menu lists VST programs** (`numPrograms`, `effGetProgramNameIndexed`, `effSetProgram`): their wrapper
  maps an engine preset parameter (vst.json `"programs"`) or a `presets.json` to programs. In this repo since 2026-10-07 (section "VST programs from the wrapper" below).
- **Plugin menu.** Sorted by type, VST plugins land in one VST folder (instruments, or effects with two inputs); the
  plugin-list `category` moves nothing. Sorted by manufacturer, each manufacturer is a folder. Names sort
  case-sensitively (digits, capitals, lower case).
- **Two-thread engine calls.** The JUCE host sets/reads parameters on its message thread while audio runs on another;
  an engine that assumes one caller can crash (Noisemaker's voice-count change). Their wrapper holds a recursive,
  priority-inheriting mutex per instance around every engine call. In this repo since 2026-10-07 (section "one engine
  call at a time" below).
- **Screen grabs.** `/dev/fb0` is black (MPC draws through a DRM plane); map the scanout buffer from `/dev/dri/cardN`
  (GETPLANE, GETFB, MAP_DUMB). The card number changed between boots (card0, then card1). Cf. `tools/drmgrab.c`.
- **ALSA mirror ports.** MPC adds its own copy ("<client> <port>") of each new sequencer port on its client, which has
  a lower number, so a substring search by port name finds MPC's copy first. Match exactly, or by pid.

## 2026-10-07: VST programs from the wrapper (offline; device-checked in part)
`wrapper/vst2_wrap.c` now reports VST programs (`numPrograms`, `effSetProgram`/`effGetProgram`, `effGetProgramName`,
`effGetProgramNameIndexed`) when vst.json has `"presets"` (a `presets.json` compiled into `params.h` by gen_vst.py) or
`"programs": {"param": key}` (an engine preset parameter: one program per option or whole number). Another fork saw
MPC's PRESET menu list and load such programs on a Live II ("reported by other forks" above). Behaviour, host-tested
(`tools/host_test.c` program checks, ASan) on `poc/steptest` variants:
- Picking a preset sets each listed parameter through the engine's `set_param`, in file order, and reports each one to
  the host from `housekeeping()` (never from inside the host's call), plus `audioMasterUpdateDisplay`.
- Picking the program that is already current does nothing, so a host re-selecting program 0 at load can't overwrite
  a restored chunk. The picked preset index isn't in the engine's state: after a project reload the menu shows the
  first preset's name (the sound is restored from the chunk as before).
- `"programs"` on a `"display": "int"` param names program n by `get_param("<key>:<n>")`, else "<Name> <n>".
- Device check (2026-10-07, Force, MPC OS version not noted; test port = `poc/steptest` copy with `presets.json` of Init/Bright/Dark
  and a 3-control layout): MPC's PRESET menu lists the presets, and picking Bright, Dark and Init moves MODE, NUM and CONT
  on screen (user-observed). **Not checked on the device:** a tweak surviving a project reload and the name the menu then
  shows, re-picking the current preset, and CC 20 moving the first Q-Link (the MIDI CC section stays offline only).

## 2026-10-07: one engine call at a time per instance (offline)
`wrapper/vst2_wrap.c` now wraps every engine call but create/destroy (`eng_set`, `eng_get`, `eng_midi`, `eng_render`,
`eng_process`) in a per-instance recursive, priority-inheriting mutex, never held while calling the host. Why: the
JUCE host calls parameters, chunks and displays on its message thread while audio runs on another, and another fork
saw an engine that assumed one caller abort MPC on a Live II ("reported by other forks" above). `tools/host_test.c`
now runs 3000 screen-side sets/reads/display reads on a second thread while rendering (ASan); every `poc/` port with
a test passes. Links need `-lpthread` (added to `build_port.sh` and `test_port.sh`): on the device toolchain's glibc
2.31, `pthread_mutexattr_setprotocol` is in libpthread. Not yet run on a device; the uncontended cost (one atomic
operation per call) should be checked with docs/BENCH.md.

## 2026-10-07: MIDI CC 20-35 and NRPN control in the wrapper (offline)
After the other fork's Live II finding ("reported by other forks": CC 20/21 from a sequencer moved an instrument's
controls through the track's MIDI input; MIDI-learning from a plugin's port froze MPC there):
- gen_vst.py writes `PLUG_CC[16]` from the first tab's first `qlinks` line (column 1 top to bottom = CC 20-23, column 2 =
  24-27, ...; `-`, triggers and text readouts get none). `effProcessEvents` sets the parameter as a touch would (option
  lists and whole numbers round to the nearest step) and keeps the CC from the engine.
- NRPN n (CC 99 MSB / 98 LSB) with its value on CC 6 (7-bit) and CC 38 (14-bit with the last CC 6) sets parameter n on
  any page; CC 101/100 (an RPN) deselects it and goes to the engine as before.
- The host hears of CC-driven changes from `housekeeping()` at most every 1024 frames, so the screen follows without a
  flood. On by default; vst.json `"cc": false` / `"nrpn": false` turn each off (an engine that reads those CCs itself).
host_test checks a CC 20 move and its report, and an NRPN set, on any parameter that keeps a value set from outside
(engine-driven displays don't). Not yet run on a device.

## 2026-10-07: drive exec `status` was confusing on a Force with two names under /media (user report, Discord, installer v0.4; offline fix)

A Force user saw `No drive under /media is mounted noexec` on the first `status`, then `Drives mounted noexec: /media/662522` (`state=stock`) after closing the plugin manager page and the terminal. Their `/media` held `662522`, `acvs-synths`, `az01-internal`, `az01-internal-sd` and `SSD - Force`; they asked whether the SSD, not `662522`, must be patched.
- `status` only lists mounts that `/proc/self/mountinfo` shows as `noexec` (`candidates`), so `662522` is the drive MPC mounted `noexec` at that time; `SSD - Force` was not a `noexec` mount then (not mounted, or mounted `exec`). `edisksd` names the mount point after the volume label, or a number when there is none; a leftover folder in `/media` is not proof of a mounted drive. Which of the two is the SSD was not shown by the output: needs `mount | grep /media` from the user (not yet received).
- Why the first run found nothing is not established (the drive was probably not mounted yet or was remounted; the user's mount lines were not captured).
- Change (offline only, tested against fake mountinfo and `tools/test_drive_exec.py`): `status` now also prints every mount under `/media` with filesystem, device and `exec`/`noexec`, so the output says which name is which drive.

### 2026-10-09: first Gen2 (MPC Live III) tester report, via SSH as root (device, user-reported)
- `MPC.settings` is at `/data/Settings/MPC/MPC.settings` on Gen2, not `/media/az01-internal/Settings/MPC/`. Our `install.sh` stopped with "MPC.settings not found (not an MPC OS device?)". The tester's staging folder was on a USB drive (`/media/<id>/VST Staging/`, read-only/noexec until `mount -o remount,rw,exec`).
- Fix (offline, host-tested only): every installer (`install.sh`, `uninstall.sh`, `sync.sh`, `mpc-store.sh`, `probe_device.sh`) and the desktop app's default settings glob now also look in `/data/Settings/*/MPC.settings`. Not yet re-run on a Gen2.
- The tester then hit "files damaged (SHA256SUMS mismatch)": expected after hand-editing `install.sh` (it is in SHA256SUMS). Not a bug; no key is involved. The fix above removes the reason to edit.
- Still unknown on Gen2: Synths dir location (`/sdcard/Synths` may not exist), the service name for the stop/start, whether `/sdcard` is the same mount. Ask for `probe_device.sh` output.

### 2026-10-09: Gen2 (MPC Live III) partition dumps read offline (`tools/gen2_image_facts.sh`, tester's `dd` images)
Eleven `mmcblk0pN` dumps, read read-only with `debugfs`. Layout: p1-p6 raw/boot data (not ext4), p7 `factory` (empty ext4), p8/p9 `kernel.fit` (A/B), p10 rootfs (4.1G ext4), p11 `data` (11G ext4, label `data`).
- Confirmed: `MPC.settings` is `Settings/MPC/MPC.settings` at the root of the `data` partition, i.e. `/data/Settings/MPC/MPC.settings` (matches the tester's shell). It holds 5 `<Location>` entries and one `pluginList-arm` line, as on Gen1.
- Confirmed: rootfs has `/usr/lib/ld-linux-aarch64.so.1` and `libstdc++.so.6.0.32` (GCC 13), consistent with glibc 2.39.
- Confirmed: the MPC service is `acvs.service` (plus `acvs-user-partition.service`); there is no `inmusic-mpc` unit on stock Gen2, so the installers' acvs default is right.
- Not yet known: the rootfs `/etc/fstab` does not mount `/sdcard`, so where the internal drive and Synths folders live comes from `acvs-user-partition.service` (see the next run of the script). The rootfs has top-level `/sdcard`, `/synths`, `/content`, `/storage`, `/nvme`, `/data`.

### 2026-10-10: Gen2 (MPC Live III) partition dumps, round 2 (offline, `tools/gen2_image_facts.sh` with symlink/unit output, same tester's `dd` images; p1-p6 raw strings)
- `/sdcard` is mounted from a real partition (`sdcard.mount`, `What=/dev/disk/by-path/...-part1`, i.e. a physical SD/MMC slot), not the internal drive, unlike Gen1/Force where `/sdcard` *is* the internal drive. `/synths`, by contrast, is a **plain empty rootfs directory with no `.mount` unit and no `/etc/fstab` line** on this unit; the rootfs itself is mounted `ro` (`/dev/root / auto ro`), so nothing can be written under `/synths` unless something else bind-mounts a writable filesystem there first.
- `acvs-user-partition.service` (`ExecStart=/usr/bin/setup-acvs-user-partition.sh`) only runs when the devicetree has `chosen/inmusic,acvs-loopback-content`. When it runs, it creates `/data/user-storage-image` (a GPT image file, one partition, PARTUUID `49e572b2-...`, label "MPC User"/"Force User", exFAT), loop-mounted at `/storage` (`storage.mount`, `What=PARTUUID=49e572b2-...`, `Where=/storage`) — this is Gen2's analog of Gen1's internal `/sdcard`. On this tester's device, `/data/user-storage-image` **does not exist**, so `/storage` has never been created/mounted there either.
- `MPC.settings`' `<SynthContentLocations>` (read from the `data` partition's real `/Settings/MPC/MPC.settings`, 82279 bytes) lists exactly: `/media/9A5E-BA8A/Synths`, `/media/Force Disk/Synths` (removable), `/synths/Expansions`, `/synths/Synths` (internal — the Gen2 analog of Gen1's `/sdcard/Synths`), `/usr/share/Akai/Content/Synths` (factory, read-only). Its one plugin-list key is `pluginList-arm` (see the `pluginList-arm-64bit` entry below), holding only factory AIR plugins (e.g. "AW Reverb - kCosmos") — this device has never had a third-party aarch64 `.so` registered, so it doesn't by itself prove what key an installed one would use.
- **Still open**: why `/synths/Synths` is listed in `MPC.settings` as a content location when nothing currently mounts anything at `/synths` on this unit. Possibilities: a udev rule or boot step we haven't found bind-mounts `/storage` (or the SD card) onto `/synths` once created; this tester's unit just never had its user partition provisioned; or `MPC.settings`' location list is written once at factory and is aspirational. Ask a tester to run `tools/probe_device.sh` (now also prints `mount | grep -E 'sdcard|synths|data|media|storage'`, `ls -ld /sdcard /synths /synths/Synths /content /storage`, and `systemctl cat acvs-user-partition`) on a live, booted Gen2.
- Fix applied regardless (harmless either way): `sync.sh`'s default Synths-folder scan now also looks at `/synths/Synths` when it's a real directory (in addition to `/sdcard/Synths` and `/media/*/Synths`), so a plugin manually placed there gets picked up once the mount question above is settled.
- Independently confirmed (second real device, matches the 2026-10-06 Discord report from different hardware): `strings` over the raw `spl1`/`spl2`/`uboot1`/`uboot2` partitions find **no `inmusic-unlock-magic` string**; fastboot plumbing is present but not the OEM unlock command (see `docs/FIRMWARE_BUILDER.md`).

### 2026-10-10: unverified third-party report — Gen2 plugin browser needs `pluginList-arm-64bit`, not `pluginList-arm` (device, not reproduced by us)
A beta tester of the Hakai VST Manager, testing the Crate Digger aarch64 test release, reports that MPC's plugin browser on a real Gen2 only shows a registered aarch64 `.so` when its entry is under `<VALUE name="pluginList-arm-64bit">`; an entry under `pluginList-arm` sits in `MPC.settings` but never appears in the browser. We have **not** reproduced this ourselves (no aarch64 pilot has loaded on hardware yet), and the one real Gen2 `MPC.settings` we've read offline (above) has only `pluginList-arm`, holding factory plugins — consistent with either key naming being right for third-party `.so` files. Treating it as credible but unconfirmed: `plugin_list.awk` now takes an optional `-v listkey=...`, and `install.sh`/`sync.sh` pick `pluginList-arm-64bit` for an `aarch64` package and `pluginList-arm` otherwise (`tools/desktop/sync.sh` and `tools/desktop/plugin_list.awk` kept identical to the `tools/release/` copies, as `test_catalog.py` checks). **Must be confirmed or corrected on real hardware** by the aarch64 pilot port (docs/GEN2.md item 3) before calling this settled either way.

## 2026-10-09: Maschine Group on an MPC Live (device)
GROUP and SETUP screenshots in `ports/maschine/docs/` (`tools/screenshot.sh --plugin`). Writing packed evdev events to the ILI2116 node updates absinfo but does not move MPC's UI (the main thread has that node open). Tab switches for the shots were done on the glass. SETUP showed the copied library path and the How to Add NI Groups copy. GROUP showed the kit list, 4×4 pads and pattern cells with 8-Ball Kit loaded (3 samples missing). Writing `/tmp/maschine-pattern.mid` cannot feed GRID Shift+Paste: `/usr/bin/MPC` has no system clipboard, and GRID reads MPC's own event buffer.

### 2026-10-10: installer app Apply / Undo on the Force (device, user-reported; PR #260)
The Force (MPC 3.9.1.2, drum-pad layout patch already applied, stock backup present, `status` read over SSH before the test) was driven through the 0.0.0-applytest build of the desktop app, step 7. The user reported that it "works well". What was and was not checked by us: before the test, `status` printed `STATE state=patched supported=1 backup=1 checksum=7cf96599ec61b1079688f253f3b65b9f` over SSH (read only); the click-through itself (Undo then Apply, typed `UNDO` / `APPLY`) was done by the user, and the checksums after each step were not read back by us. Only the drum-pad patch was tried; the drive exec and button remap patches have no Apply/Undo run yet, and the app offers default settings only (no per-patch options).
