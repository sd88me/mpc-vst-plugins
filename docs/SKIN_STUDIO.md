# Skin studio

Tools for designing MPC plugin skins without hand-placing pixels. Every route ends in the same
`layout.conf` (Force Shadow `shadow_page.conf` widget syntax), which `tools/shadow_skin.py` turns into the
skin (`TUI.json`, Q-Links, artwork). Use any step on its own or chain them:

```
params ──auto──► layout.conf ──to-svg──► layout.svg ──(Inkscape)──► from-svg ──► layout.conf ──► skin ──preview──► PNGs
                     ▲ │
                     └─┴── serve: edit it in the browser
```

| Step | Command | Use it when |
|---|---|---|
| Auto-layout | `tools/studio.py auto params.json -o layout.conf` | You want a working first page in seconds |
| Browser editor | double-click `SkinStudio.command` / `.bat` / `.sh`, or `tools/studio.py serve [layout.conf \| vst.json]` | You want to lay out, restyle and check it by hand |
| To SVG | `tools/studio.py to-svg layout.conf -o layout.svg --params params.json` | You want to rearrange it visually |
| From SVG | `tools/studio.py from-svg layout.svg -o layout.conf` | You've edited the SVG |
| Build skin | the port's gen script (`shadow_skin.write_skin(...)`) | Always last |
| Preview | `tools/studio.py preview "<skin>/Plugin Skins" -o page_%d.png` | Before deploying anything (a page with popups also gets `page_N_open.png`, and one with mode panels a `page_N_mode<p>-<i>.png` per other option) |

The tools need Python 3; the skin build and preview also need Pillow (the ports run them in a
`python:3.11-slim` container). The browser renderer (below) runs in its own image, `mpc-vst-html-art`.

## Auto-layout
- Input: the port's parameter file (`tools/params.py`; its `sections` become frames), or an adapter's
  source (see `adapters/`). Without sections, parameters are grouped by key prefix.
- Output: pages of 2 rows × 8 slots. Row 1 is Q-Link bank 1 (Q-Links 1–8) and row 2 is bank 2 (9–16).
  Each section becomes a titled frame, and a section with more than 8 controls gets its own page.
- Control types: numbers → knob, off/on → toggle, `momentary` / trigger → button,
  up to 6 options → vertical selector, 7+ → `popup` (a field that opens the full list), readout/stepper →
  2-slot text box.
- A `popup` list opens under the field (else above, adding columns until it fits) and closes on a pick; a
  Q-Link turn steps the value and leaves it open. Swap any `enum_h`/`enum_v` line for
  `popup cx= cy= w= h= key=<param>` by hand when an option list takes too much room.
- Labels are shortened to fit (an `LFO1 > ` prefix is dropped, since the frame title already says it).

### Text widget

`text cx= cy= label="..."` draws free-standing static text (no parameter), baked into the page background. Options:
`size=` (scale, 1.5 = the label size, about 10 px per 1.0), `color=`, and, with the browser renderer (`"art": "html"`):
`align=left|center|right` (about `cx`), `weight=400|600|700`, `spacing=<px>` (letter spacing), `case=upper|none`,
`opacity=0..1`, `italic=1`, `font=<family>` (only families the renderer's image has; Titillium Web is bundled) and
`fontfile=<file.ttf|otf|woff|woff2>` (beside the layout; embedded, so any typeface works and it wins over `font=`; in the editor pick one from the list or **Upload…** to put it in `fonts/`). A font uploaded in the Style panel is also usable by family name in `font=`. Use a font
whose licence lets you ship it. All of these are in the inspector when a text widget is selected. Baked text only:
MPC's live names and values stay in Titillium Web.

## Browser editor
Double-click the launcher at the repo root: `SkinStudio.command` on macOS, `SkinStudio.bat` on Windows, `SkinStudio.sh`
on Linux (run it from the file manager, or `./SkinStudio.sh`). It opens the editor in your default browser; keep the
window it runs in open while you edit, and use **Quit** in the page (or close that window) to stop it. It needs
Python 3 only (python.org; on Windows tick "Add python.exe to PATH"), no Docker, Pillow or Chromium.
- macOS: the first time, right-click the launcher, **Open**, then **Open** again if macOS says it's from an
  unidentified developer.
- Windows: drop a `layout.conf` or a port's `vst.json` on `SkinStudio.bat` to open it straight away.

The start screen lists recent layouts and has a folder browser. Click a `.conf` to edit it, or a port's `vst.json` to
edit its layout with its parameters (a port without a layout gets a first-pass one from `auto`; add `"layout":
"layout.conf"` to its vst.json so the build uses it). **New layout in this folder** makes an empty one or one from a
parameter file. The parameter file is found for you: the vst.json that names the layout, else `<name>.params.json` or
`params.json` next to it. **Open…** switches layouts. Recent layouts are kept in `~/.mpc-skin-studio.json`.

From a terminal: `tools/studio.py serve [layout.conf | vst.json] [--params params.json] [--open]` (port 8765, or the
next free one). To try the editor, copy `tools/skin_template.conf` and `tools/skin_template.params.json` into a folder
as `layout.conf` and `params.json` and open it.

- **The canvas is the skin.** Each widget is drawn with the browser renderer's own SVG and stylesheets
  (`tools/html_art.py`, `default.css`, the layout's `art_css=`), so it looks like a `"art": "html"` build. MPC's own text
  (names, values, list rows) is drawn on top in Titillium Web where the device puts it (**Live text**). A skin built with
  the default renderer (shadow_art) has the same geometry but its bitmap font; `preview` shows that exactly.
- **Layout:** drag to move (Shift locks an axis), drag the corner handle to resize (knob radius, box size, segment
  width), arrows nudge by 1 (Shift: 10), drag across empty canvas to select several, then align or spread them.
  Toggles, buttons and vertical selectors have renderer-fixed sizes, so they only move. **Slots** shows the
  auto-layout's 8 × 2 grid.
- **Inspector:** every field of the selected line, a parameter picker, `when=` with the parameter's options, and the
  whole layout line to edit by hand (anything the fields don't cover).
- **Tabs and layers:** add, rename (double-click), reorder, duplicate or delete tabs; reorder lines, duplicate
  (Ctrl+D), delete. Frames and art are drawn behind the controls, as in the built skin.
- **Modes:** a tab with `when=` lines gets a mode bar; pick an option to see that mode (**Other modes** dims the rest).
- **Q-Links:** one card per `qlinks` set (sub-page), 16 slots in the two banks. Click a slot, then a control on the
  canvas. The canvas numbers the selected set's controls. `qlinks_track` is below.
- **Theme:** `style=` and a colour picker per `theme_*` colour, shown live.
- **Style:** creates or edits the `art_css=` stylesheet with a live preview: sliders for the renderer's text sizes,
  corner radius and sheen, font upload (`@font-face` added for you) and a font picker for labels and frame titles.
  Fonts only change baked text; MPC draws names and values in its own fonts (docs/NOTES.md).
- **Looks** (inspector) and **Assets** (tab): see "Looks and images" below. **Background…** puts an image or SVG
  drawing behind the tab; **Place image…** puts one on the page at its own shape (a logo, a panel photo).
- **Checks:** unknown parameters, option counts that differ from the parameter, bad `when=`, controls overlapping or
  past the plugin area's edge, broken lines, Q-Link sets over 16. Click one to select the widget.
- **Saving** (Ctrl+S) writes the layout as `layout.conf.new`, then renames it over the old one; the first save keeps the
  original as `layout.conf.bak`. Lines you didn't change are written back exactly as they were, comments included;
  a changed line is rewritten in `from-svg`'s format. Undo/redo cover every edit.

The server listens on 127.0.0.1 only (`--host` to change it) and answers only requests addressed to this machine.
It reads and writes files only in the open layout's folder; the start screen can list any folder and open or create
a layout there.

## Looks and images
Controls can be drawn by the renderer (the default), with a built-in look, or from your own images. Every route
needs the browser renderer (`"art": "html"` in vst.json); the builder refuses them otherwise. Paths are relative to
the layout; the editor uploads into `images/` next to it. Keep images inside the port's folder: `build_port.sh` runs
the build in Docker with only that folder (and this repo) mounted. Images: `.png .jpg .jpeg .webp .gif .svg`
(`tools/skin_assets.py` has the details).

| Asset | Layout | Notes |
|---|---|---|
| Knob, built-in | `knob ... look=moog` | `moog`, `chicken`, `metal`, `cap` (the theme's knob colours), `prophet` (ribbed skirt, silver ring, brushed black top, white pointer; keeps the theme's value arc), plus the 303-style hardware set: `hardware` (glossy black dome, engraved ticks, `--tick` colour), `chrome` (mirror dome), `bakelite` (brown, cream pointer), `davies` (stepped cap, pointer to the rim), `rubber` (matte, dot in the theme's `knob_dot`), `ledring` (LED ring that lights to the value; theme `accent_hi`) |
| Knob image | `knob ... img=knob.png [base=scale.png]` | turned through 270°; draw it pointing up (= the middle of the travel); `base` stays still under it |
| Knob filmstrip | `knob ... strip=knob_strip.png [frames=N]` | frames stacked down (or across), minimum first; resampled to MPC's 128 |
| Slider | `slider_v ... look=fader`, or `img=thumb.png [base=track.png]`, or `strip=` | the thumb is as wide as a vertical slider; the track is stretched to it |
| Toggle / switch | `toggle ... look=led` (or `switch`), or `img=off.png [img_on=on.png] [w= h=]` | sized from the image (or `w`/`h`); without `img_on`, on = the off image brightened |
| Button, key, pad | `button ... img=pad.png [img_on=pad_lit.png] [w= h=]` | the label is drawn on top; `label=""` for none |
| Option segments | `enum_h` / `enum_v ... img=seg.png [img_on=seg_lit.png]` | each option: the image, its name on top |
| Panel | `frame ... img=panel.png` | the picture (stretched) instead of the drawn border; the title on top |
| Pop-out list | `popup ... img=list.png` | the open list's panel, under the options |
| Page background | `art file=bg.jpg [fit=cover]` | fills the plugin area (`fit`: contain, cover, stretch) |
| Placed image, logo | `art file=logo.png x= y= w= h=` | anywhere, at any size; ends up baked into the background |
| Value pictures | `picture x= y= w= h= key=<param> files="a.png,b.png,.."` | one image per option of the parameter, the current one shown (MPC switches them: mode images) |
| Meter | `meter cx= cy= w= h= key=<param> strip=meter.png` | a display-only filmstrip. The engine sets the parameter; MPC redraws it live when the wrapper reports the change (`HAS_DISPLAY_REV`, verified on an MPC One). Frames are the meter's own w x h, as many as the strip has (`frames=`, else counted), at most 12288 px of strip (2026-10-07, as stock skins; device check pending) |

**Defaults for a whole kind:** a top-level `<group>_<attr>=` line, e.g. `knob_look=moog`, `slider_img=images/cap.png`,
`seg_img=images/seg.png` (groups `knob`, `slider`, `toggle`, `button`, `seg`, `frame`, `popup`, `meter`). A line that
sets any look attribute ignores the defaults; `look=drawn` keeps the renderer's drawing. In the editor: set a control's
look, then **Use for every …**; the Theme panel lists the defaults.

**In the editor:** the inspector's **Look** section picks the look and each image (with upload), and a filmstrip's
frame count (shown as "auto: N" when the image's shape gives it). The **Assets** tab shows the images next to the
layout; pick one, then what it's for (the selected control's image, filmstrip, base, on image, a picture's next
option, placed on the page, or the page background).

**Built-in looks** draw with `look-*` classes (`tools/html_art/default.css`), so a stylesheet can recolour them. An
image segment's name uses the theme's `ink` (off) and `seg_active_tx` (selected); restyle `.seg.look-image .seg-tx`.

**Images from other skins:** stock MPC skin art is Akai's. Never commit it to this repo (it keeps a reference copy
in the git-ignored `Assets/`); a port whose skin uses it ships it in its release zip, which is the port owner's call.

## Inkscape (or Penpot) round trip
- Open `layout.svg` in Inkscape. Each tab is a **layer** (`tab <NAME>`); only the first is visible,
  so toggle layers in the Layers panel.
- Each control is a group whose **label** (Object Properties or the Layers and Objects panel) is its
  layout line without coordinates, e.g. `knob key=cutoff label="CUTOFF"`. Move, resize, duplicate or delete
  it; the converter reads the position and size from the circle or rect inside.
- To add a control, copy one from `tools/skin_template.svg` (one of every kind) and change its label.
- Knob size = circle radius. Slider/readout/stepper/popup/list size = rect size (`slider_v` / `slider_h`). Horizontal-segment width = rect
  width ÷ options per row. Toggles, buttons and vertical selectors use only the centre (their size
  is fixed by the renderer).
- Q-Link sets live in the layer's **description** (`qlinks "PAGE" = key,...`, one line per nested page).
- Placed and bitmap images (`art file=... x= y= w= h=`, `picture`) come across as linked images in a labelled group:
  move or resize the image.
- Anything without a control label (your own drawings, gradients, text, logos) is **background artwork**:
  `from-svg` writes each tab's to `<layout>.<tab>.art.svg` next to the layout and adds an `art file=...` line,
  and `to-svg` puts it back as editable shapes. Put a drawing in a group labelled `art when=<param>:<option>`
  to show it only in that mode. Art needs the browser renderer.
- `to-svg` → `from-svg` without edits reproduces the layout exactly (verified on Maze Voice: identical
  `TUI.json`, Q-Links and every image).

## Artwork renderers
The layout says where everything goes; a renderer draws it. Two do, from the same layout:

- **shadow_art** (default): force-shadow's own renderer (vendored), so a skin matches the Force Shadow page it
  was ported from pixel for pixel. Bitmap font; controls are opaque squares on the plate colour.
- **Browser** (`"art": "html"` in vst.json): `tools/html_art.py` draws each piece as SVG in headless Chromium
  (`tools/html_art/`, built into the `mpc-vst-html-art` Docker image by `tools/build_port.sh`). Text is real
  Titillium Web by default (MPC's own live-text font, so baked and live text match), knobs have a value arc,
  controls have transparent edges so they sit on artwork, and `art file=` drawings go into the background.
  Restyle it with a stylesheet: a top-level `art_css=skin.css` line in the layout, loaded after
  `tools/html_art/default.css` (its header lists the classes and variables). Any font (`@font-face` with a
  file next to the CSS), knob look, gradient or shadow; `theme_*` lines still set the colours. Only colours,
  shapes and effects change (a shared `filter: url(#grain)` gives a plate a painted-metal grain and wear): sizes and positions stay the layout's, because MPC puts its live controls there.

A port with its own build script runs `gen_vst.py` inside `mpc-vst-html-art` instead of `python:3.11-slim`
(see `tools/build_port.sh`).

## Mode panels
End any layout line (a frame too) with `when=<param>:<option>` to show it only while that option parameter is at
that option (option name, any case, or its index). Stack alternatives in the same place, one line per mode:
```
knob  cx=221 cy=410 r=30 label="RATE" key=lfo1_rate when=lfo1_sync:free
popup cx=221 cy=404 w=200 h=44 label="SYNC DIV" key=lfo1_div when=lfo1_sync:sync
```
MPC switches them itself as the parameter changes (IndexedEnabling, docs/NOTES.md). A hidden control keeps its
Q-Link, so either leave it in the page's `qlinks` set or map only controls every mode shows. The preview draws the
page with every option parameter at its first option, plus one `page_N_mode<p>-<i>.png` per other option (p = the
parameter's index). One condition per line: for a control shown in two modes, repeat the line.

## Q-Links
MPC reads two maps from the skin's `Q-Links.json`:
- **Screen mode** (Q-Links follow the page on screen): one map per page. In the layout, each `qlinks "PAGE" =
  key,...` line in a tab gives that page's set, in order: keys 1–8 on knob bank 1, 9–16 on bank 2 (converted to
  MPC's bottom-up grid numbering for you). Without a `qlinks` line, a tab uses its first 16 controls in file order.
- **Program/track mode** (Q-Links fixed to the track or program, whatever page is showing): one map. Set it with a
  top-level `qlinks_track = key,...` line (same ordering); without it, page 1's set is used.
- **Per sub-page controls (2026-10-07, offline):** `banks="ONE|TWO"` on a control, frame, text or art line keeps it to
  those `qlinks` pages of its tab, so each sub-page can show and touch-edit what its Q-Links turn (a step sequencer's
  PITCH / GATE lanes in the same cells). Baked parts get their own image on those sub-pages. Not yet seen on a device.

## Built-skin check (2026-10-07)
`tools/skin_check.py "<plugin folder>"` reads the built `TUI.json`/`Q-Links.json` and reports, per page: TOUCH (two
controls' touch boxes overlap while both show: MPC gives the touch to one), EDGE (a box past 1280x628) and QLINK (a
Q-Link on a parameter no control on that page shows) and OPTS (a switch group missing some of its options). `gen_vst.py` runs it after every skin build and prints the
findings as `warning: skin:` lines. It complements the browser editor's layout checks, and sees what the builder made
(label widths, `when=` modes, `banks=` sub-pages).

## Text size and touch width per control (2026-10-07, offline)
`knob` and `slider_v`/`slider_h` take `ns=<px>` (name text; `ns=0` drops the name), `vs=<px>` (value text) and
`bw=<px>` (touch box and text width; default 130). Narrow `bw=` where neighbours sit closer than ~130 px, or MPC gives
a touch to the wrong control. Toggles take `bw=` and `ns=0` (the switch alone); `enum_v` takes `sh=` like `enum_h`.
`knob ... lay=side bw= bh= vs=` puts the knob's picture at the left of a bw x bh box and its value, large, in the rest
(no name): a step cell you drag like a knob. From `saustin2010/vst_instruments`' fork; not yet seen on a device.

## Coming next
Tracked in [ROADMAP.md](ROADMAP.md) ("Skin controls" and "Porting and tooling"), including a build-and-preview
button in the browser editor.
