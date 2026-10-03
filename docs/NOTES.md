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
- Device: armv7l, glibc 2.39 (build with an older glibc, e.g. `arm32v7/gcc:12` docker = 2.36).
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
  `audioMasterGetTime` gives exact `tempo` and `ppqPos` already, so the wrapper synthesizes the same
  24-PPQN clock byte stream from the ppqPos delta each block (`ceil(last/step)*step .. end`, step =
  1/24 quarter note) and feeds it to the engine's own `process_midi()` unchanged -- no core changes
  needed.
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

**The orange box on a control is the Focus subcomponent, not the Q-Link bounds.** `_focus()` in `shadow_skin.py`
adds a `WhenFocussed` outline plus a faint white fill sized to the control's whole placed slot (about 130 x 155 for a
knob or slider), so on dense envelope pages it spilled over neighbours and the frame below. `hideQLinkBounds` only
sets a per-component flag and did not remove it; zeroing `qlinkBoundsData` did not either. What worked: make the
focus style transparent (`backgroundColour` and `outlineColour` `00000000`, `outlineThickness` 0). List tiles keep
their selected look because that is baked into the tile image, not the focus ring. Page `qlinkBoundsData` is now
`"0 0 0 0"` and every `hideQLinkBounds` is true.

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
there is no `pip`. Preview is what to look at before deploying; without it, deploy the skin alone (skin-only
changes need no restart, re-insert the plugin) and read the screenshot.

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

## 2026-10-03: MPC OS 2.15.1: plugins load, skins do not draw (user reports on an MPC Live, plus other 2.x users; not reproduced by us)

Unit: MPC Live (first generation), MPC OS 2.15.1, Buildroot 2021.02, BusyBox userland (no `ldd`, `file`; `head -n`, not `head -3`), `armv7l`. MPC runs as `inmusic-mpc.service`; there is no `acvs`.

- **Service name.** Release zips built before the installers picked the service themselves ran `systemctl stop acvs` and aborted ("Unit acvs.service not loaded") before touching `MPC.settings`. Fixed in the installers and in the desktop app (a `systemctl` shim for old zips, desktop v0.3.2).
- **glibc.** Builds that need `GLIBC_2.34` (`dladdr`, `pthread_*`: Dexed 1.0.1-1.0.2, JV-880 1.0.0-1.0.3, checked with `objdump -T`) were registered correctly (right `file=`, file present, executable) but MPC showed only "Load Plugin". Dexed 1.0.4 (needs 2.29) installed through the app loads: the log shows `Attempting to load VST`, `Creating VST instance`, `Initialising VST`. The two old releases per plugin are yanked in `catalog/yanked.json`.
- **Skin location was not the cause.** The plugin's folder was under a `Synths` path listed in `SynthContentLocations` (SSD and internal SD both tried), `Plugin Skins/TUI.json` present. The edit page showed MPC's frame (header "Plugin 001", preset `<none>`) with an empty body; the log has no skin or JSON message. Q-Links showed and drove the parameters.
- **2.x does read a skin from a plugin folder.** Copying the stock AIR Compressor `Plugin Skins` over the Dexed folder made the Compressor page appear as Dexed's edit page. So the fault is in our `TUI.json`, not in how MPC finds it.
- **Imports exist.** Our `TUI.json` imports `/usr/share/Akai/Content/Synths/Generic/Generic Knob Overlay.json` and `Generic Menu Overlay.json`; both exist on 2.15.1 (also `Generic Slider.json`, `version.xml`).
- **Format versions (counts of `"version": N` over every stock `Plugin Skins/TUI.json`).** 2.15.1: 1 = 10884, 2 = 3030, and 45 for a value cut off in the report (probably 3). Force, OS base 5.0.17: 1 = 9259, 2 = 5929, 3 = 224, 4 = 388, 5 = 76. Our generator (`tools/shadow_skin.py`) writes component definitions at version 4 (94 in the Dexed skin), tabs at 3, film-strip knob data at 5, `Q-Links.json` at 4: the same shape as the Force's stock Decimator skin. Hypothesis: 2.x does not accept versions above its own. **Open:** the 2.x shape of those objects; needs a stock `TUI.json` (and one with knobs) from a 2.x unit. The same stock AIR Compressor skin lays out identically on 2.15.1 (MPC Live) and on the Force, so screen size is not the issue.
- Akai's support pages (read 2026-10-03) say standalone MPC does not support third-party plugins at all, list the standalone models, and say new built-in plugins need newer OS versions (Native Instruments 3.5+, Spitfire 3.7.1+). Forum posts say 2.15.x is no longer updated by Akai. None of this covers skin formats.

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
