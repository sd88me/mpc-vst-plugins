# Community skins: techniques worth reusing

A study (2026-10-07, offline: read from each repo's `layout.conf`, art scripts, docs and tests; nothing re-run on a
device here) of six plugins built with this framework by other people. Each section says what the skin does, how,
and whether this repo's builder already supports it. The adoption list at the end feeds `docs/ROADMAP.md`.

| Plugin | Repo | Kind | Art |
|---|---|---|---|
| Keyscope | `jacob-sabella/mpc-vst-keyscope` | key/chord detector (effect) | synthwave theme, circle-of-fifths SVG drawn by a script |
| MPC Plaits | `poloq-instruments/mpc-vst-plaits` | Mutable Plaits (instrument) | the module's own panel artwork, re-flowed for the wide screen |
| Plugin Manager | `poloq-instruments/mpc-vst-manager` | catalog installer (utility) | flat app UI built almost entirely from `when=` state images |
| Liminal Hz | `gmorb/mpc-vst-liminal-hz` | IR reverb (effect) | textured page, waveform painted from parameters, type roles |
| 303, Mono Voice | `saustin2010/vst_instruments` (`schwung/instruments/`) | Schwung ports | Google Stitch mockups converted to layouts |

All six use `"art": "html"` plus an `art_css` file, and set the full `theme_*` palette rather than relying on a
`style=`. That is the pattern to recommend for new ports.

## Design techniques

**A designed background, live parts on top (all six).** One `art file=` per tab covers the whole plugin area
(`x=0 y=86 w=1280 h=628`, or `fit=stretch`); frames, captions and logos are baked into it, and only what changes is
a widget. The art is made by a script in the port (`art/gen.py`, `make_art.py`, `make_images.py`) so it can be
regenerated when the layout moves. Plaits comments "keep the positions below in sync with that script": put the
coordinates in one place (the script writes the layout, or reads it).

**Interactive diagrams from `list` cells (Keyscope).** The circle of fifths is a background SVG with 24
one-cell `list` widgets (`cols=1 rows=1`) placed on the ring, each bound to an engine-driven text parameter: the
engine lights and names them, a tap locks the key. Any radial or free-form hit target can be made this way.

**Value displays made of many `picture` columns (Liminal Hz).** The IR waveform is 12 `picture` widgets side by
side, each bound to a read-only option parameter with one PNG per level (a bar graph), plus a `picture` "playhead"
glow. MPC only switches images when the parameter changes, so it costs nothing at rest (see the animation cost below).

**State machines with `when=` (Plugin Manager).** Each row's action button is seven `button` lines on the same spot,
each with its own image and `when=r1_state:<state>` (install / update / installed / queued / disabled / menu); badges
(`stable`, `beta`, `cpu`, `tested`) are image buttons on `key=noop` shown by flags; an offline/empty screen is an
`art` overlay with `when=empty:offline`. The engine owns the state; the skin is pure presentation. This is the most
complete use of `IndexedEnabling` seen so far and a good template for any non-instrument app.

**Image controls.** Plaits steps models with `button ... img= img_on=` arrows round a `popup wheel=1`, and shows
the model's LED/icon with a `picture`. The Manager's tabs and filter pills are `enum_h ... img= img_on=`, and its
cards are `list ... img= img_on=` with the cell text placed by `tx= ty= ttw= tth=` and styled by `tsize= tweight=
tcolor=`. 303/Mono Voice set `toggle_img=`/`toggle_img_on=` once at the top level for every toggle.

**Typography as roles (Liminal Hz, Manager).** Liminal's rule: "what you read is bright, what names it is quiet,
and amber is kept for live values (knob arcs, the playhead), never for plain text". Captions are PNGs (exact font,
letter-spacing), live text sizes are set per role. The layout can't set a knob's name/value size and colour per
widget class, so Liminal patches `TUI.json` after the build (`vst/skin_post.py`, a table of definition-key prefix,
label name, height, colour, failing loudly when a prefix no longer matches). `vst.json` `"skin_post"` now runs such a
script as part of the build (added 2026-10-07). The Manager notes "live text sizes are MPC font heights = 1.52 x the
CSS font size": size live text in MPC units, not mockup pixels.

**Q-Links planned per hardware.** Keyscope gives each tab exactly one bank of 4 ("the MPC Key 37 has 4 physical
Q-Links and its Q-Link sub-pages don't cycle, so a second bank would be unreachable there") and keeps anything
destructive off Q-Links ("nothing that clears what was heard on a turn: RESET is a button"). 303 uses `-` slots so
each panel gets its own Q-Link column and outline (`3-2-4-3` panels). Liminal sets `qlinks_track`.

**Mockup-to-skin pipeline (vst_instruments).** Pages are designed as HTML in Google Stitch at 1280x628, rendered in
headless Chromium; each control is found by CSS selector, matched to a parameter, hidden, and the rest of the page
becomes the background; knob artwork is rendered at 64 angles into filmstrips. The previous grid layout is kept
as `layout.grid.conf`. This is the same idea as `studio.py from-svg`, from HTML instead of SVG.

## Quality process

- **Design QA file per plugin (vst_instruments `DESIGN-QA.md`):** the owner's notes from the device, what changed
  (a before/after Q-Link column table), what was left as is and why, and the checks run. A good model for skin
  review in this repo's PR template.
- **`check_skin.py` (vst_instruments `dev-tools/stitch/`):** reads the built `TUI.json`/`Q-Links.json` and reports
  BIND (control bound to the wrong parameter), QLINK (Q-Link off its page, out of order, more than 16), TOUCH
  (overlapping touch boxes: MPC gives the touch to one), EDGE (box past 1280x628), OPTS (option count mismatch).
  `qlink_overlay.py` draws the Q-Link outlines over a preview to check they don't overlap. This repo now has
  `tools/skin_check.py` (TOUCH/EDGE/QLINK, 2026-10-07) besides `skin_compat.py` (OS 2.x/3.x shape).
- **`showcase.py`:** README screenshots rendered with the engine's real values.
- **`tested.json`** (Keyscope, Plaits, Manager, Liminal): device, firmware, date per version; this repo's catalog
  already reads it (`docs/CATALOG.md`).
- **`TESTING.md`** (Keyscope, Manager): an offline section (sanitizers, real-time p99.9 of `process()` run on the
  device over ssh at nice 19 without touching MPC) and a numbered by-hand device table (check / how / expect).

## Device facts reported by these repos

`saustin2010/vst_instruments` ships a patch against an older commit of this repo with dated NOTES sections verified
on a Live II. They are summarised in `docs/NOTES.md` "Reported by other forks (2026-10-07)"; the headlines:
FilmStrip `numFrames` is the frame count (non-square frames are fine); slider strips over ~12288 px misbehave;
animated skins cost MPC's screen thread 25-110% of a core; the Q-Link sidebar hides x >= ~1025; MPC's PRESET menu
lists VST programs; engine calls need one-at-a-time locking per instance.

## Adoption list

Builder (`tools/shadow_skin.py`), all in the vst_instruments patch and so already written once:

1. `banks="A|B"`: a control or art line only on some Q-Link sub-pages. **Done 2026-10-07 (offline).**
2. `ns=` / `vs=` per knob and slider (name/value px). **Done 2026-10-07 (offline).** Readouts already have
   `tsize=`/`tcolor=`/`box=0`. Covers most of what Liminal's `skin_post.py` does by hand.
3. `bw=` touch-box width for close neighbours (**done for knobs and sliders, 2026-10-07**); `lay=side` knob
   (picture left, big value right; step cells). **All done 2026-10-07 (offline), toggles included.**
4. Sliders and display meters laid out as stock filmstrips (frames of the widget's own size, `numFrames` = count,
   strips under 12288 px). **Done 2026-10-07 (offline).**
5. `sh=` on `enum_h`/`enum_v`. **Done** (enum_h had it; enum_v 2026-10-07).
6. A skin checker like `check_skin.py` (BIND/QLINK/TOUCH/EDGE/OPTS). **TOUCH/EDGE/QLINK/OPTS done 2026-10-07**
   (`tools/skin_check.py`, run by `gen_vst.py`); Q-Link order against the layout is not checked.

Wrapper and gen_vst: `"programs"` / `"presets"` (MPC's PRESET menu; lists and loads on a Force), a per-instance
engine-call mutex, MIDI CC 20-35 to the first page's Q-Links and NRPN to any parameter: **all done 2026-10-07**
(the mutex and MIDI control offline only). Not taken: option `values`/`send`.

Docs and skill: the techniques above (done in the skill's "Design techniques"), Design QA + TESTING.md templates.
