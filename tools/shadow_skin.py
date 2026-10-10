"""Build an MPC plugin skin from a Force Shadow style layout (.conf).

The layout uses the shadow_page.conf widget syntax (see force-shadow's
docs/adding-a-page.md), so a page designed for Force Shadow becomes a native
MPC skin with the same look: shadow_art (force-shadow's own renderer) draws
backgrounds, knob filmstrips and button states; MPC draws live values.

Layout file:
    [tab NAME]
    frame   x= y= w= h= title="..."
    text    cx= cy= label="..." [size=1.5] [color=<hex>]   (free-standing static text, centred on cx,cy;
                                                        not bound to any parameter. size is a scale
                                                        multiplier (1.5 default, matches label text);
                                                        color defaults to theme_ink)
            [font="Titillium Web"] [fontfile=fonts/My.ttf (beside the layout; overrides font=)] [weight=400|600|700] [align=left|center|right] [spacing=<px>]
            [case=upper|none] [opacity=0..1] [italic=1]      (html art only; align is about cx: "left"
                                                        starts at cx, "right" ends at cx)
    knob    cx= cy= r= label="..." key=<param> [ink=<hex>] [ink_dim=<hex>]   (ink / ink_dim: this knob's name and value text colours)
    toggle  cx= cy= label="..." key=<param>
    button  cx= cy= label="..." key=<param> [w= h=] [label_on="..."] [tsize= get=<param>]
                                                        (trigger; w=/h= draw that size, label_on= is the text while on.
                                                        Pressed fill is theme_accent (or theme_btn_on=). tsize= with
                                                        get= draws that parameter's text in Titillium on the button.
                                                        A transparent hit plate sits on top of that caption so the
                                                        tap fires the trigger, not the text parameter.)
    enum_h  cx= cy= label="..." key=<param> [options="A,B,.."] [sw=<px>] [rows=<n>]
    enum_v  cx= cy= label="..." key=<param> [options="A,B,.."] [sw=<px>]   (options default to the param's)
    slider_v cx= cy= w= h= label="..." key=<param>     (vertical slider; value text below)
    slider_h cx= cy= w= h= label="..." key=<param>     (horizontal slider; value text below)
    readout cx= cy= w= h= label="..." key=<param> [label_align=center]   (live value text;
                                                        label_align=center needs the browser renderer, "art": "html")
    menu    cx= cy= w= h= label="..." key=<param>      (value text; tap opens MPC's native picker -- which
                                                         opens EMPTY for a VST2, see docs/NOTES.md; use popup)
    popup   cx= cy= w= h= label="..." key=<param> [options="A,B,.."] [cols=<n>] [groups="Title:count[:headFill[:headInk[:optFill[:optInk]]]],.."] [cw=<option cell width>] [wheel=1] [accent=<hex|none>] [field=none]
                                                       (value text; tap opens a drawn option list, a pick closes it.
                                                        Needs the hidden "<param>__open" param: popup_params())
    stepper cx= cy= w= h= label="..." key=<param> [label_align=center]   (live text;
                                                        arrows = <param>_prev / <param>_next;
                                                        label_align=center needs "art": "html")
    list    x= y= w= h= cols= rows= th= gap= key=<p>   (rows = params <p>_1..<p>_N: text + tap;
                                                        order=pads numbers the rows from the bottom, like a pad bank;
                                                        order=cols numbers down each column first, so it reads top to bottom;
                                                        tap=no draws the rows without toggling; mark=1 fills a lit row
                                                        with the accent instead of the selection border; mark=vel draws
                                                        a small rounded bar whose opacity follows the row's value 0..4;
                                                        tint=1 colors each row from tint_<n> (0..5), a gel washed over black)
    art     file="drawing.svg" [x= y= w= h=] [fit=]    (an SVG drawing, e.g. from studio.py from-svg, or a .png/.jpg/.webp
                                                        image, drawn into the page background: the whole plugin area, or
                                                        the box; fit=contain|cover|stretch; browser renderer only)
    picture x= y= w= h= key=<param> files="a.png,b.png,.." [fit=]
                                                       (one image per option of the parameter, the current one shown:
                                                        a when= art line per option, so mode images do the switching)
    meter   cx= cy= w= h= key=<param> strip=meter.png [frames=N]
                                                       (a display-only filmstrip following a parameter the engine sets;
                                                        experimental: see docs/SKIN_STUDIO.md)
    meter   cx= cy= w= h= key=<param> look=native ...  (NOT USABLE: a real native Meter component breaks the
                                                        whole plugin screen on a real device -- see docs/NOTES.md
                                                        "Native `Meter` component: breaks the whole page";
                                                        kept only so tools/skin_assets.py can refuse it with a
                                                        clear message. Use the filmstrip meter above.)
Controls can have looks: built-in drawings or images (look=, img=, img_on=, base=, strip=, frames=, peak=, rms=;
frames and popups take img=), per line or as top-level defaults (knob_look=moog): see tools/skin_assets.py. Looks,
images and pictures need the browser renderer.
    qlinks  "PAGE NAME" = key,key,...                  (optional, repeatable; "-" leaves a slot empty. Every 4 keys
                                                        are one Q-Link column -- one press of the MPC One's Q-Link
                                                        button. With qlink_bounds=column, MPC outlines that column)
Any widget line (frames and art too) can carry `banks="NAME|NAME"`: it is only on those Q-Link sub-pages of its tab
(the tab's `qlinks` titles), so a sub-page can show and touch-edit what its Q-Links edit; its baked parts become their
own image on those sub-pages.
Knobs and sliders take `ns=<px>` / `vs=<px>` (name / value text size; ns=0: no name) and `bw=<px>` (touch box and
text width, e.g. narrower than the usual 130 px where neighbours sit close and their boxes would overlap). `knob ... lay=side [bw= bh= vs=]`: the
knob's picture at the left of a bw x bh box (default 4 knobs wide), its value (vs= px, default 30) in the rest, no name.
Toggles take
`bw=` and `ns=0` too (other ns= sizes are not used on toggles); enum_v takes `sh=` like enum_h.
Any widget line (frames too) can end in `when=<param>:<option>` (option name or index): it is shown only
while that option parameter is at that option (MPC's IndexedEnabling), so a tab can swap control sets per
mode. Its baked parts (frame, title, text boxes, group labels) go into a per-mode image over the background.
Top level: `qlinks_track = key,...` sets the Q-Links used outside page-follow mode (default: page 1's).
`qlink_bounds=column` outlines the controls of the Q-Link column in use, as stock skins do (checked on an MPC One
only; default: no outline).
Top-level `style=` / `theme_<name>=RRGGBB` lines are the shadow_page.conf ones; `color=` on a
button overrides its fill. `art_css=skin.css` restyles the browser renderer's artwork (tools/html_art.py).

Coordinates are Force Shadow landscape pixels (1280x800); the plugin area is
1280x628, taken from y=Y_OFF. Each `qlinks` line makes one MPC sub-page of
that tab (same design, its own Q-Link set, max 16: 1-8 bank 1, 9-16 bank 2).
Without one, a tab's first 16 controls in file order get the Q-Links.
Option counts must match the parameter's own options.
"""
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skin_assets  # noqa: E402

W, H, Y_OFF = 1280, 628, 86
PLATE, INK, INK_DIM, ACCENT, ACCENT_HI = "131211", "efe9d8", "8f8878", "c1552f", "e2793f"
SEG_ON, SEG_OFF, SEG_ON_TX = "f2f1ee", "050403", "1c1a17"
LCD, LINE, BTN_BG, BTN_ON, BTN_TEXT, BOX = "1a120d", "2a2823", "", "", "fdf3ea", "1f1f1f"
TILE_ON = ""             # theme_tile_on: fill of a selected/sounding list tile ("" = the LCD fill, border only)
DISPLAY_INK = "cdeb63"   # theme_display_ink: live-text colour over a dotreadout/dotstepper (see readout/stepper below)
TD3 = False   # style=td3: frames are filled boxes, so widget crops sit on BOX, not the page bg
QLINK_COLUMNS = False   # qlink_bounds=column: per-column Q-Link outlines (qlink_column_bounds)
LABEL_SCALE = 1.0   # label_scale=<n>: scales knob/toggle/pill name+value live-text size and their boxes
FRAMES = 128               # filmstrip frames emitted by (l)sstrip / (l)strip
ROT_FRAMES = FRAMES - 1     # rotary knob FilmStrip: a rotation reads one fewer than the strip length
STRIP_FRAMES = FRAMES       # vertical slider / meter FilmStrip: value is the frame's vertical position, so
                            # numFrames must equal the exact strip length; FRAMES-1 mis-sizes the frame and
                            # shows a second thumb near the top (device-confirmed, MPC One). Their strips can
                            # have fewer frames (strip_frames); numFrames is always the count emitted.
MAX_STRIP = 12288           # tallest slider/meter filmstrip (px) seen drawing right: 128-frame strips of 16640+ px
                            # animated wrongly on a Live II; knob strips up to 96x12288 are fine (docs/NOTES.md 2026-10-07)


def strip_frames(h, want=FRAMES):
    """Frames of a slider/meter filmstrip whose frames are h px tall: as many as fit in MAX_STRIP (at most want)."""
    return max(2, min(want, MAX_STRIP // max(1, h)))


KNOB_QLINKS = [13, 9, 5, 1, 14, 10, 6, 2]
CONTROL_KINDS = ("knob", "slider_v", "slider_h", "toggle", "button", "enum_h", "enum_v", "readout", "stepper", "list", "menu",
                 "popup", "meter")
LOOK_DEFAULTS = {}         # top-level <group>_<attr>= lines (skin_assets.py), set by apply_theme()
OPEN_SUFFIX = "__open"     # popup: hidden wrapper-only param, 1 while the option list is shown
POP_ROW, POP_GAP, POP_PAD = 40, 2, 6
THEME_KEYS = {"bg": "PLATE", "ink": "INK", "ink_dim": "INK_DIM", "accent": "ACCENT", "accent_hi": "ACCENT_HI",
              "seg_active": "SEG_ON", "seg_inactive": "SEG_OFF", "seg_active_tx": "SEG_ON_TX",
              "lcd": "LCD", "line": "LINE", "btn_bg": "BTN_BG", "btn_on": "BTN_ON", "btn_text": "BTN_TEXT", "box": "BOX",
              "display_ink": "DISPLAY_INK", "tile_on": "TILE_ON"}


FONT_LABEL_PATH = None   # font_label=<path> (layout.conf top level) -- see apply_theme()

def text_width(s, scale=1.15):          # sizes a button's TUI.json bounds; must use the same SCALE as
                                         # widget_button()'s own draw call there (render_conf_preview.c).
                                         # That C text_width()/label_width() now advances per glyph's real
                                         # ink bbox span (proportional spacing, not a flat 10px/char cell),
                                         # which this flat font8x8 estimate deliberately over-sizes for --
                                         # safe (padding, no clipping) *for the baked bitmap font*, but a
                                         # font_label= TTF/OTF can be much wider per glyph (e.g. a display
                                         # face), so a button sized off this flat estimate clips the real
                                         # render (found porting force-acid: 2026-09-24). When font_label is
                                         # set, measure with that real font at render_conf_preview.c's own
                                         # TTF_PX(scale) size instead, so Python's box and the C pixel art
                                         # agree; +20% safety margin (hinting/rounding can differ slightly
                                         # from FreeType's rasterizer vs. the C side's stb_truetype).
    if FONT_LABEL_PATH:
        from PIL import ImageFont
        px = round(9 * scale * 1.6)   # mirrors render_conf_preview.c's TTF_PX macro (GLYPH_CELL=9)
        font = ImageFont.truetype(FONT_LABEL_PATH, px)
        return int(font.getlength(s) * 1.2)
    return int(len(s) * 10 * scale - scale)


def parse_layout(path):
    """Returns (tabs, top-level style/theme lines)."""
    tabs, top = [], []
    for raw in open(path):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not tabs and "=" in line and not line.startswith("[") and not line.startswith("qlinks_track"):
            top.append(line)
            continue
        m = re.match(r"\[tab (.+)\]$", line)
        if m:
            tabs.append({"name": m.group(1).strip(), "widgets": [], "qlinks": []})
            continue
        if line.startswith("qlinks_track"):
            top.append(line)
            continue
        if line.startswith("qlinks"):
            m = re.match(r'qlinks\s+"([^"]+)"\s*=\s*(.+)$', line)
            tabs[-1]["qlinks"].append((m.group(1), [k.strip() for k in m.group(2).split(",") if k.strip()]))
            continue
        tabs[-1]["widgets"].append(parse_widget(line))
    return tabs, top


INT_KEYS = ("x", "y", "w", "h", "cx", "cy", "r", "sw", "sh", "rows", "cols", "th", "gap", "cw", "ns", "vs", "bw", "bh")


def parse_widget(line):
    """One widget line -> dict (kind, then its key=value fields; numbers as ints, options as a list)."""
    toks = shlex.split(line)
    w = {"kind": toks[0]}
    for t in toks[1:]:
        k, _, v = t.partition("=")
        w[k] = v
    for k in INT_KEYS:
        if k in w:
            w[k] = int(w[k])
    if "options" in w:
        w["options"] = w["options"].split(",")
    if "groups" in w:   # popup headings: "Title:count[:headFill[:headInk[:optFill[:optInk]]]],..." (all colours RRGGBB, optional)
        gl = []
        for g in w["groups"].split(","):
            p = g.split(":") + [""] * 6
            hf, hi, of, oi = (p[2] or None), (p[3] or None), (p[4] or None), (p[5] or None)
            gl.append((p[0], int(p[1]), hf, hi, of, oi))
        w["groups"] = gl
    return w


def apply_theme(top):
    """theme_* lines override the palette used for text/segments/tiles drawn from Python. font_label=
    (render_conf_preview.c's own key, same layout file) is read here too, purely so text_width() can
    size button/enum boxes against the real font instead of the baked font8x8 estimate -- Python
    never rasterizes with it, that's still all done by shadow_art (render_conf_preview.c)."""
    g = globals()
    g["LOOK_DEFAULTS"] = skin_assets.defaults(top)
    g["QLINK_COLUMNS"] = False
    for line in top:
        if line.strip() == "style=td3":
            g["TD3"] = True
        if line.startswith("font_label="):
            g["FONT_LABEL_PATH"] = line[len("font_label="):].strip()
            continue
        if line.startswith("label_scale="):
            g["LABEL_SCALE"] = float(line[len("label_scale="):].strip())
            continue
        if line.startswith("qlink_bounds="):
            g["QLINK_COLUMNS"] = line[len("qlink_bounds="):].strip() == "column"
            continue
        if line.startswith("scale_names="):
            g["SCALE_NAMES"] = line[len("scale_names="):].strip() not in ("", "0", "no", "off")
            continue
        k, _, v = line.partition("=")
        if k.startswith("theme_") and k[6:] in THEME_KEYS:
            g[THEME_KEYS[k[6:]]] = v.strip()


def look_of(w, base_dir="."):
    """w's look (skin_assets.look_of with this layout's defaults), or None for the renderer's own drawing."""
    return skin_assets.look_of(w, LOOK_DEFAULTS, base_dir)


def expand_pictures(widgets):
    """picture lines -> one when= art line per option (the mode images show the current one)."""
    out = []
    for w in widgets:
        if w["kind"] != "picture":
            out.append(w)
            continue
        if w.get("when"):
            raise SystemExit("layout: picture %s: can't also have when= (it already follows its parameter)" % w.get("key"))
        for i, f in enumerate(x.strip() for x in w.get("files", "").split(",")):
            if f:
                out.append({"kind": "art", "file": f, "x": w["x"], "y": w["y"], "w": w["w"], "h": w["h"],
                            "fit": w.get("fit", "contain"), "when": "%s:%d" % (w["key"], i)})
    return out


# scale_names=1: the names MPC draws under knobs and toggles follow label_scale (21 px x it) and a toggle's box
# grows with them. Off (the default), they are the fixed 17 px (knob) / 15 px (toggle) names in the 120 px toggle box
# every existing skin was drawn with, whatever label_scale says.
SCALE_NAMES = False
def NAME_FONT(kind): return 21.0 * LABEL_SCALE if SCALE_NAMES else (17.0 if kind == "knob" else 15.0)
def NAME_H(): return round(28 * LABEL_SCALE) if SCALE_NAMES else 20
def TOG_W(): return round(170 * LABEL_SCALE) if SCALE_NAMES else 120


TEXT_WEIGHTS = {"regular": "Regular", "400": "Regular", "semibold": "SemiBold", "600": "SemiBold", "bold": "Bold",
                "700": "Bold", "light": "Light", "300": "Light"}
TEXT_JUST = {"left": "left verticallyCentred", "center": "horizontallyCentred verticallyCentred",
             "right": "right verticallyCentred"}
# talign= defaults: readouts centre their text (as they did before talign= existed, so existing skins keep their look);
# list rows start it at the left edge.
READOUT_JUST = TEXT_JUST["center"]
ROW_JUST = TEXT_JUST["left"]


def live_text(w, size, colour, just):
    """A readout's or list row's live text style, overridable per line: tsize= (px), tcolor= (hex), tweight=
    (regular|semibold|bold|light or 400/600/700/300), talign= (left|center|right; readouts default to center, list
    rows to left), tfont= (Titillium Web or Roboto, the families MPC renders).
    -> (size, colour, justification, style, font, signature for the component name)."""
    size = float(w.get("tsize", size))
    colour = w.get("tcolor", colour).lstrip("#")
    style = TEXT_WEIGHTS.get(str(w.get("tweight", "semibold")).lower(), "SemiBold")
    just = TEXT_JUST.get(w.get("talign"), just)
    font = w.get("tfont", "Titillium Web")
    sig = "" if not any(k in w for k in ("tsize", "tcolor", "tweight", "talign", "tfont")) else \
        "_%s" % slug("%g_%s_%s_%s_%s" % (size, colour, style, just.split()[0], font))
    return size, colour, just, style, font, sig


def card_art(img, x, y, tw, th, base_dir):
    """A list row drawn from the port's own picture (img=/img_on=) instead of the renderer's tile."""
    path = os.path.abspath(os.path.join(base_dir, img))
    return ("svg|%s|%d|%d|%d|%d" if path.lower().endswith(".svg") else "image|%s|%d|%d|%d|%d|stretch") % (path, x, y, tw, th)


def toggle_rect(w, base_dir="."):
    """A toggle's image box (shadow coords): the stock pill, or its look's size."""
    tw, th = skin_assets.toggle_size(w, look_of(w, base_dir))
    return (w["cx"] - tw // 2, w["cy"] - th // 2, tw, th)


def under():
    """Colour behind widgets: td3 frames are filled boxes."""
    return BOX if TD3 else PLATE


def slug(t):
    return "".join(c if c.isalnum() else "_" for c in t).strip("_") or "x"


# tint=1: index 0 is the fallback yellow, then kick, snare, hat/shaker, percussion, tom.
PAD_TINTS = ((0xe6, 0xc8, 0x4a), (0xe2, 0x3a, 0x32), (0xf0, 0x78, 0x20),
             (0xc4, 0x8e, 0xe0), (0x3e, 0xc4, 0xd4), (0x3c, 0xba, 0x6a))


def pad_gel(w, h, rgb, hot):
    """A pad washed with a translucent colour: darker at the rim, a little lighter in the middle."""
    from PIL import Image
    page, dark = (5, 4, 3), (14, 13, 12)
    rad = max(6, min(w, h) // 14)
    im = Image.new("RGB", (w, h), page)
    px = im.load()
    strength = 0.62 if hot else 0.46
    for y in range(h):
        for x in range(w):
            dx = 0.0 if rad <= x < w - rad else (rad - x if x < rad else x - (w - rad - 1))
            dy = 0.0 if rad <= y < h - rad else (rad - y if y < rad else y - (h - rad - 1))
            d = (dx * dx + dy * dy) ** 0.5
            if d >= rad + 0.5:
                continue
            cov = 1.0 if d <= rad - 0.5 else rad + 0.5 - d
            nx, ny = (x + 0.5) / w - 0.5, (y + 0.5) / h - 0.5
            fall = min(1.0, (nx * nx + ny * ny) ** 0.5 * 2.1)
            a = strength * (0.92 + 0.08 * fall)
            light = (1.0 - fall) * (0.42 if hot else 0.28)
            cr = min(255, rgb[0] + (255 - rgb[0]) * light)
            cg = min(255, rgb[1] + (255 - rgb[1]) * light)
            cb = min(255, rgb[2] + (255 - rgb[2]) * light)
            r = dark[0] * (1 - a) + cr * a
            g = dark[1] * (1 - a) + cg * a
            b = dark[2] * (1 - a) + cb * a
            px[x, y] = (int(page[0] * (1 - cov) + r * cov), int(page[1] * (1 - cov) + g * cov),
                        int(page[2] * (1 - cov) + b * cov))
    return im


def shade(hexcol, f):
    r, gr, b = (int(hexcol[i:i + 2], 16) for i in (0, 2, 4))
    return "%02x%02x%02x" % tuple(max(0, min(255, int(c * f))) for c in (r, gr, b))


def list_keys(w):
    """tile i's param: rows top-down, or bottom-up like a pad bank (order=pads: pad 1 is bottom left), or down each column
    first (order=cols: 1..rows in the left column, then the next column), so a list reads and steps top to bottom"""
    n, cols = w["cols"] * w["rows"], w["cols"]
    if w.get("order") == "cols":
        return ["%s_%d" % (w["key"], (i % cols) * w["rows"] + i // cols + 1) for i in range(n)]
    if w.get("order") == "pads":
        return ["%s_%d" % (w["key"], (w["rows"] - 1 - i // cols) * cols + i % cols + 1) for i in range(n)]
    return ["%s_%d" % (w["key"], i + 1) for i in range(n)]


def list_tiles(w):
    tw = (w["w"] - (w["cols"] - 1) * w["gap"]) // w["cols"]
    return [(w["x"] + (i % w["cols"]) * (tw + w["gap"]), w["y"] + (i // w["cols"]) * (w["th"] + w["gap"]), tw, w["th"])
            for i in range(w["cols"] * w["rows"])]


def stepper_arrows(w):
    x0, y0, h = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w["h"]
    return (x0, y0, h, h), (x0 + w["w"] - h, y0, h, h)


def popup_params(layout_path, params):
    """The hidden "<key>__open" params the layout's popups need, to append after the module's own
    (appending keeps every existing parameter index, so saved projects stay valid). The wrapper keeps
    their value itself (never sent to the DSP) and clears it when an option is picked."""
    have = {p["key"] for p in params}
    extra = []
    for tab in parse_layout(layout_path)[0]:
        for w in tab["widgets"]:
            if w["kind"] == "popup" and w["key"] + OPEN_SUFFIX not in have:
                src = next((p for p in params if p["key"] == w["key"]), {})
                extra.append({"key": w["key"] + OPEN_SUFFIX, "name": "%s List" % src.get("name", w["key"]),
                              "type": "enum", "options": ["Closed", "Open"], "default": 0, "popup_of": w["key"]})
                have.add(w["key"] + OPEN_SUFFIX)
    return extra


POP_GROUP_ROWS = 8   # a grouped list wraps a group into columns of at most this many options


def popup_layout(w):
    """Option list geometry (shadow coords): (panel rect, [option rects], [(heading rect, title)]). Opens below the
    field, else above, else from the top of the plugin area. Plain lists use columns when the options don't fit one;
    with groups=, every group gets a heading and its own column(s) of up to POP_GROUP_ROWS options."""
    n = len(w["options"])
    fx, fy, fw, fh = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w.get("cw") or w["w"], w["h"]   # cw=: option cell width
    below, above = Y_OFF + H - (fy + fh + 4), fy - 4 - Y_OFF
    groups = w.get("groups")
    if groups:
        rows = min(POP_GROUP_ROWS, max(g[1] for g in groups))
        cols = sum(-(-g[1] // rows) for g in groups)
        ph = (rows + 1) * (POP_ROW + POP_GAP) - POP_GAP + 2 * POP_PAD
    else:
        for cols in ([w["cols"]] if w.get("cols") else range(1, n + 1)):
            rows = -(-n // cols)
            ph = rows * (POP_ROW + POP_GAP) - POP_GAP + 2 * POP_PAD
            if ph <= max(below, above):
                break
    pw = cols * fw + (cols - 1) * POP_GAP + 2 * POP_PAD
    if ph <= below:
        py = fy + fh + 4
    elif ph <= above:
        py = fy - 4 - ph
    else:
        py = Y_OFF   # nothing fits beside the field: the list covers it (a pick still closes it)
    px = max(0, min(fx, W - pw))
    step = POP_ROW + POP_GAP
    if not groups:
        opts = [(px + POP_PAD + (o // rows) * (fw + POP_GAP), py + POP_PAD + (o % rows) * step, fw, POP_ROW) for o in range(n)]
        return (px, py, pw, ph), opts, []
    opts, heads, col = [], [], 0
    for title, count, *_colours in groups:
        gcols = -(-count // rows)
        heads.append(((px + POP_PAD + col * (fw + POP_GAP), py + POP_PAD, gcols * fw + (gcols - 1) * POP_GAP, POP_ROW), title))
        for o in range(count):
            opts.append((px + POP_PAD + (col + o // rows) * (fw + POP_GAP), py + POP_PAD + (1 + o % rows) * step, fw, POP_ROW))
        col += gcols
    return (px, py, pw, ph), opts, heads


def popup_panel(w):
    """(panel rect, [option rects]) of popup_layout()."""
    panel, opts, _ = popup_layout(w)
    return panel, opts


def mix_hex(a, b, t):
    """a blended toward b by t (0..1), both RRGGBB."""
    ca, cb = [int(a[i:i + 2], 16) for i in (0, 2, 4)], [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def popup_heading_cmds(w):
    """Art commands for a grouped popup's headings (none for a plain list): the group's heading fill and text colours;
    without them the heading is accent text on the list's own fill (a lone colour fills it, dark text)."""
    out = []
    for ((x, y, hw, hh), title), g in zip(popup_layout(w)[2], w.get("groups") or []):
        if g[2] or g[3]:
            fill, ink = g[2] or LCD, g[3] or ("101214" if g[2] else ACCENT)
        else:
            fill, ink = LCD, ACCENT
        out.append("seg|%d|%d|%d|%d|%s|%s|%s" % (x, y, hw, hh, fill, ink, title))
    return out


def popup_option_fills(w):
    """The fill of each option while not selected: the group's option colour, a faint tint of its heading colour, or the list's own."""
    fills = []
    for g in w.get("groups") or []:
        fills += [g[4] or (mix_hex(LCD, g[2], 0.22) if g[2] else LCD)] * g[1]
    return fills or [LCD] * len(w["options"])


def popup_option_inks(w):
    """The text colour of each option while not selected."""
    inks = []
    for g in w.get("groups") or []:
        inks += [g[5] or INK] * g[1]
    return inks or [INK] * len(w["options"])


def qlink_for_slot(slot):
    return KNOB_QLINKS[slot % 8] + 2 * (slot // 8)


# ---- geometry of each widget (shadow coords), mirroring render_conf_preview.c ----

def seg_rects(w):
    n = len(w["options"])
    if w["kind"] == "enum_v":
        sw, sh, gap = w.get("sw") or 135, w.get("sh") or 30, 2   # respect the layout's sw=/sh= (like enum_h), else 135 x 30
        y0 = w["cy"] - (n * (sh + gap)) // 2
        return [(w["cx"] - sw // 2, y0 + i * (sh + gap), sw, sh) for i in range(n)]
    sw, sh, gap = w.get("sw") or 117, w.get("sh") or 33, 2   # sw=/sh=: segment size
    rows = w.get("rows", 1)
    per = -(-n // rows)
    out = []
    for i in range(n):
        r, c = divmod(i, per)
        cnt = min(per, n - r * per)
        x0 = w["cx"] - (cnt * sw + (cnt - 1) * gap) // 2
        out.append((x0 + c * (sw + gap), w["cy"] - sh // 2 + r * (sh + gap), sw, sh))
    return out


LABEL_SCALE = 1.15   # was 1.5: the baked bitmap font (font8x8.h) IS mixed-case (has a-z), but at
                      # 1.5x its fixed monospace cell (10px/char * scale) read as too wide/shouty
                      # when paired with Title Case text -- see docs/NOTES.md. Only affects control
                      # name labels drawn via this function (shadow_art.c's own "text" command);
                      # frame titles use force-shadow's shared frame_box(), which this repo doesn't
                      # own and doesn't change.


def label_cmds(w, title_font=None):
    """Static text baked into the page background. knob/toggle/slider names come from a
    native Label 'Name' component instead (device-rendered Titillium Web -- see build()'s
    knob/toggle/slider defs and _name_label()), so this only bakes text where there's no
    single parameter index a native Name label could bind to: frame titles, group labels on
    enum_h/enum_v (whose per-OPTION segment text has no such binding either). When title_font
    is set, the enum_h/enum_v group label is skipped here and drawn with the real font instead
    (build()'s decor/title-overlay pass, which already does this for frame titles)."""
    k, lab = w["kind"], w.get("label", "")
    if not lab or k in ("knob", "toggle", "slider_v", "slider_h"):
        return []   # an empty TEXT field is swallowed by shadow_art's strtok, so skip the command entirely
    if title_font and k in ("enum_h", "enum_v"):
        return []
    s = LABEL_SCALE
    if k == "enum_h":
        return ["text|%d|%d|%s|%s|%s" % (w["cx"], w["cy"] - 33 // 2 - 22, s, INK, lab)]
    if k == "enum_v":
        n = len(w["options"])
        return ["text|%d|%d|%s|%s|%s" % (w["cx"], w["cy"] - (n * 32) // 2 - 24, s, ACCENT_HI, lab)]
    return []


def button_rect(w, base_dir="."):
    lk = look_of(w, base_dir)
    if "w" in w and "h" in w and not lk:
        return (w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w["w"], w["h"])
    if lk:
        bw, bh = skin_assets.button_size(w, lk, text_width(w.get("label", "")) + 36)
        return (w["cx"] - bw // 2, w["cy"] - bh // 2, bw, bh)
    bw, bh = text_width(w.get("label", "")) + 36, 39
    if TD3:   # widget_button(): +24 wide, 48 tall, plus a 2 px outline ring
        bw, bh = bw + 24 + 4, 48 + 4
    return (w["cx"] - bw // 2, w["cy"] - bh // 2, bw, bh)


def baked_cmds(w, title_font=None, base_dir="."):
    """shadow_art commands for the parts of w baked into the page background (frames, text boxes,
    list tiles, group labels, SVG art); the controls themselves are separate images/components."""
    cmds = []
    if w["kind"] == "art":
        path = os.path.abspath(os.path.join(base_dir, w["file"]))
        box = (w["x"], w["y"], w["w"], w["h"]) if "w" in w else (0, Y_OFF, W, H)
        if path.lower().endswith(".svg"):
            cmds.append("svg|%s|%d|%d|%d|%d" % ((path,) + box))
        else:
            cmds.append("image|%s|%d|%d|%d|%d|%s" % ((path,) + box + (w.get("fit", "contain"),)))
    elif w["kind"] == "frame" and look_of(w, base_dir):   # a panel picture instead of the drawn border
        cmds.append("iframe|%d|%d|%d|%d|%s|%s" % (w["x"], w["y"], w["w"], w["h"],
                                                  "-" if title_font or not w.get("title") else w["title"], look_of(w, base_dir)["img"]))
    elif w["kind"] == "frame":
        if title_font and w.get("title"):   # the title is drawn with the real font afterwards
            cmds.append("frameblank|%d|%d|%d|%d" % (w["x"], w["y"], w["w"], w["h"]))
        else:
            cmds.append("frame|%d|%d|%d|%d|%s" % (w["x"], w["y"], w["w"], w["h"], w.get("title") or "-"))
    elif w["kind"] == "readout" and str(w.get("box", "1")) == "0":
        pass   # box=0: live text only, over the page's own artwork
    elif w["kind"] in ("readout", "stepper", "menu", "popup"):
        op = "readout" if w["kind"] in ("menu", "popup") else w["kind"]
        if w["kind"] in ("readout", "stepper") and w.get("style") == "dotmatrix":
            op = "dot" + op
        cmd = "%s|%d|%d|%d|%d|%s" % (op, w["cx"], w["cy"], w["w"], w["h"], w.get("label") or "-")
        if w.get("label_align") == "center":   # only sent when non-default: keeps the wire
            cmd += "|center"                   # format backward-compatible with shadow_art.c
        if not (w["kind"] == "popup" and w.get("field") == "none"):   # field=none: no drawn box (the artwork supplies it)
            cmds.append(cmd)
    elif w["kind"] == "list":
        for (x, y, tw, th) in list_tiles(w):
            cmds.append(card_art(w["img"], x, y, tw, th, base_dir) if w.get("img")
                        else "tile|%d|%d|%d|%d|%s|%s|0" % (x, y, tw, th, w.get("color") or LCD, LINE))
    elif w["kind"] == "text":
        size = float(w.get("size", 1.5))
        color = w.get("color", INK)
        if any(k in w for k in TEXT_EXT):   # the browser renderer only; shadow_art's bitmap font has none of these
            anchor = {"left": "start", "right": "end"}.get(w.get("align", "center"), "middle")
            cmds.append("htext|%d|%d|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s" % (
                w["cx"], w["cy"], size, color, anchor, w.get("weight", ""), w.get("spacing", ""),
                w.get("case", ""), w.get("opacity", ""), 1 if w.get("italic") in ("1", 1, "yes", "true") else 0,
                ("@" + os.path.abspath(os.path.join(base_dir, w["fontfile"])) if w.get("fontfile")
                 else (w.get("font", "") or "")).replace("|", " "), w.get("label", "")))
        else:
            cmds.append("text|%d|%d|%s|%s|%s" % (w["cx"], w["cy"], size, color, w.get("label", "")))
    return cmds + label_cmds(w, title_font)


TEXT_EXT = ("font", "fontfile", "weight", "align", "spacing", "case", "opacity", "italic")


def text_box(w):
    """(x, y, w, h) in shadow coords of a free-standing text widget, generously; estimates the
    browser renderer's font (about 0.6 em per glyph plus letter spacing) when extended options are set."""
    size = float(w.get("size", 1.5))
    lab = w.get("label", "")
    if not any(k in w for k in TEXT_EXT):
        lw = text_width(lab, size)
    else:
        px = size * 10
        try:
            sp = float(w.get("spacing", 0.04 * px))
        except ValueError:
            sp = 0.0
        lw = int(len(lab) * (px * 0.62 + sp)) + 2
    th = int(16 * size)
    align = w.get("align", "center")
    x0 = w["cx"] if align == "left" else w["cx"] - lw if align == "right" else w["cx"] - lw // 2
    return (x0 - 4, w["cy"] - th // 2 - 4, lw + 8, th + 8)


def baked_rect(w):
    """Area (shadow coords) that baked_cmds(w) draws into, generously; None if it draws nothing."""
    k = w["kind"]
    if k == "art":
        return (w["x"] - 2, w["y"] - 2, w["w"] + 4, w["h"] + 4) if "w" in w else (0, Y_OFF, W, H)
    if k == "frame":
        return (w["x"] - 2, w["y"] - 2, w["w"] + 4, w["h"] + 4)
    if k in ("readout", "stepper", "menu", "popup"):
        return (w["cx"] - w["w"] // 2 - 4, w["cy"] - w["h"] // 2 - 34, w["w"] + 8, w["h"] + 38)
    if k == "list":
        return (w["x"] - 4, w["y"] - 4, w["w"] + 8, w["h"] + 8)
    if k in ("enum_h", "enum_v") and w.get("label"):
        rs = seg_rects(w)
        x0, y0 = min(r[0] for r in rs), min(r[1] for r in rs)
        x1 = max(r[0] + r[2] for r in rs)
        lw = text_width(w["label"], LABEL_SCALE)
        x0, x1 = min(x0, w["cx"] - lw // 2), max(x1, w["cx"] + lw // 2)
        return (x0 - 4, y0 - 48, x1 - x0 + 8, 48)
    if k == "text":
        return text_box(w)
    return None


# ---- TUI.json helpers ----

def _bounds(x, y, w, h, focus="No", show="Show", visible="Always"):
    return {"version": 2, "acceptsHWFocus": focus, "showWhenDataModelInvalid": show, "whenVisible": visible,
            "boundsType": "Absolute", "bounds": "%d %d %d %d" % (x, y, w, h), "additionalInvalidatingHandles": []}


def _sub(ctype, data, bnd, name=""):
    return {"version": 2, "componentData": {"version": 1, "name": name, "type": ctype, "data": data},
            "handle remapping": {"version": 1, "map": []}, "bounds": bnd}


def _action(on, handler, extra="", handle="Data"):
    return {"version": 2, "onAction": on, "handler": handler, "handleName": "" if handler == "Show Overlay" else handle,
            "additionalData": extra, "handle remapping": {"version": 1, "map": []}}


def _local(key, actions, children):
    clear = {"version": 1, "colour": "0", "image": ""}
    return {"key": key, "value": {"version": 4, "actions": actions,
                                  "backgroundData": {"version": 1, "focussed": clear, "unfocussed": clear},
                                  "ignoreMousePresses": False, "disableCoarseDataWheel": False, "repeats": 1,
                                  "hideQLinkBounds": not QLINK_COLUMNS, "componentsData": children}}


def _focus(w, h):
    return _sub("Focus", {"version": 1, "backgroundColour": "00000000", "outlineColour": "00000000",
                          "backgroundInset": 2.0, "outlineThickness": 0.0},
                _bounds(0, 0, w, h, visible="WhenFocussed"), "Focus")


def _value_label(x, y, w, h, size, colour, just="horizontallyCentred verticallyCentred", handle="Data", style="SemiBold",
                 font="Titillium Web"):
    return _sub("Label", {"version": 1, "textStyle": {"version": 1, "font": {"version": 1, "name": font,
                                                                         "style": style, "height": size},
                                                   "colour": "00000000" if colour == "none" else "ff" + colour, "justification": just, "case": "Original"},
                          "type": "Value", "handleName": handle}, _bounds(x, y, w, h), "Value")


def text_sfx(w, cw):
    """Definition-key suffix for a control's own ns=/vs=/bw= (controls that differ need their own definition)."""
    return "".join("_%s%d" % (k, w[k]) for k in ("ns", "vs", "bw") if w.get(k) is not None)


def _name_label(x, y, w, h, size, colour, just="horizontallyCentred verticallyCentred"):
    """Control name via MPC's OWN native Titillium Web renderer (the assigned parameter's
    name, i.e. PARAMS[i].name from params.h) -- genuinely proportional, device-rendered text,
    unlike shadow_art.c's baked 9x9 bitmap font (see docs/NOTES.md's font-spacing entries)."""
    return _sub("Label", {"version": 1, "textStyle": {"version": 1, "font": {"version": 1, "name": "Titillium Web",
                                                                         "style": "SemiBold", "height": size},
                                                   "colour": "ff" + colour, "justification": just, "case": "Original"},
                          "type": "Name", "handleName": "Data"}, _bounds(x, y, w, h), "Name")


def _button(on_img, off_img, bid, n, w, h, x=0, y=0):
    return _sub("Button", {"version": 2, "onImage": on_img, "offImage": off_img, "buttonId": bid,
                           "numButtonsInGroup": n, "handleName": "Data", "gestureBehaviour": "Instant"},
                _bounds(x, y, w, h), "Button")


def write_hit_png(skin_dir, w, h):
    """Near-invisible plate so a live caption on top of a button still receives the tap.
    Alpha 0 is skipped by some hosts; 1 is enough for a hit and does not show."""
    name = "sh_btn_hit_%dx%d.png" % (w, h)
    path = os.path.join(skin_dir, name)
    if not os.path.exists(path):
        from PIL import Image
        Image.new("RGBA", (w, h), (0, 0, 0, 1)).save(path)
    return name


def _placed(ctype, name, index, x, y, w, h, focus="Yes", extra=None):
    """extra: {handle_name: param_index} for sub-widgets bound to a DIFFERENT parameter than the
    main "Data" handle -- e.g. a stepper's Q-Link/inc-dec target vs. the text it displays (that
    sub's def must itself use handleName=extra's key, see the stepper's "Text" label)."""
    m = [{"key": "Data", "value": "Parameter %d" % index}]
    for hname, hindex in (extra or {}).items():
        m.append({"key": hname, "value": "Parameter %d" % hindex})
    return {"version": 2,
            "componentData": {"version": 1, "name": name, "type": ctype, "data": {"version": 1, "handleName": "Data"}},
            "handle remapping": {"version": 1, "map": m},
            "bounds": _bounds(x, y - Y_OFF, w, h, focus=focus, show="Hide")}


def build(layout_path, params, skin_dir, art_bin, png_from_ppm):
    """Returns (localComponentDefinitions, tabs, qlink map entries); writes PNGs into skin_dir."""
    index = {p["key"]: i for i, p in enumerate(params)}
    tabs_in, top = parse_layout(layout_path)
    apply_theme(top)
    work = os.path.join(skin_dir, ".art")
    os.makedirs(work, exist_ok=True)
    script, defs, pages, qmap, ppms = [], {}, [], [], []
    tint_sizes = set()
    # SHADOW_TITLE_FONT: a real TrueType font (.ttf/.otf) to draw frame titles with instead of
    # shadow_art.c's baked 9x9 bitmap font, which -- even Title-Cased and tightened (see
    # docs/NOTES.md's font-spacing entries) -- is blocky pixel art, not a real typeface. Optional
    # and off by default (every other port keeps the baked font unchanged).
    TITLE_FONT = os.environ.get("SHADOW_TITLE_FONT")
    decor = []    # (image, origin x, origin y, widgets): real-font titles and popup chevrons drawn after the PNG exists
    tagged = []   # [first, end (None: up to the last), widget]: a tab's when= widgets' components in kids
    label_overlays = []  # (final png path, w, h, text, hex colour): button/enum option text drawn with
                          # TITLE_FONT afterward, same idea as decor's frame titles -- see the button/
                          # enum_h/enum_v blocks below, which bake "" instead of the real label when
                          # TITLE_FONT is set so the baked bitmap font never shows through underneath.

    kid_banks = {}   # id(component) -> the Q-Link sub-pages (qlinks titles) it is on; absent: all of its tab's

    def banks_of(w):
        """banks="A|B" -> {"A", "B"}: the Q-Link sub-pages a widget is on (None: all of its tab's)."""
        b = w.get("banks")
        return {x.strip() for x in b.split("|") if x.strip()} if b else None

    def cond(w):
        """when=<param>:<option> -> the IndexedEnabling handle that shows w only in that mode (None: always)."""
        if not w.get("when"):
            return None
        k, _, o = w["when"].partition(":")
        opts = [str(x).lower() for x in (params[index[k]].get("options") or [])] if k in index else []
        if len(opts) < 2:
            raise SystemExit("layout: when=%s: %r is not an option parameter" % (w["when"], k))
        oi = opts.index(o.lower()) if o.lower() in opts else int(o) if o.isdigit() and int(o) < len(opts) else None
        if oi is None:
            raise SystemExit("layout: when=%s: %r is not one of %s" % (w["when"], o, ",".join(opts)))
        return "IndexedEnabling/%d/%d/Parameter %d" % (oi, len(opts), index[k])
    base_dir = os.path.dirname(os.path.abspath(layout_path))
    html = os.path.basename(art_bin).startswith("html_art")
    for tab in tabs_in:
        tab["widgets"] = expand_pictures(tab["widgets"])
        for w in tab["widgets"]:
            lk = look_of(w, base_dir)
            if w["kind"] == "meter" and not lk:
                raise SystemExit("layout: meter %s needs strip= (its filmstrip)" % w.get("key"))
            if lk and skin_assets.check(w, lk):
                raise SystemExit("layout: %s %s: %s" % (w["kind"], w.get("key") or w.get("title", ""), skin_assets.check(w, lk)))
            if w["kind"] == "art" and not os.path.isfile(os.path.join(base_dir, w["file"])):
                raise SystemExit("layout: art file=%s: no such file" % w["file"])
            if (lk or w["kind"] == "art") and not html:
                raise SystemExit("layout: %s %s: looks, images and art need the browser renderer (vst.json \"art\": \"html\")"
                                 % (w["kind"], w.get("key") or w.get("file") or w.get("title", "")))
    theme_conf = os.path.join(work, "theme.conf")
    open(theme_conf, "w").write("\n".join(   # art_css= is relative to the layout; the renderer runs elsewhere
        "art_css=" + os.path.join(base_dir, l[8:].strip()) if l.startswith("art_css=") else l
        for l in top if not l.startswith("qlinks_track")) + "\n")
    script.append("theme|" + theme_conf)

    def art(name):
        ppm = os.path.join(work, name + ".ppm")
        ppms.append((ppm, os.path.join(skin_dir, name + ".png")))
        return ppm

    popopt_img, popopt_done = {}, set()   # popup option images shared by identical options (text, colours, size)
    radii, sliders, looks = set(), set(), {}   # knob (r, look id), slider (image, w, h, vert, look id); look id -> look
    for t, tab in enumerate(tabs_in):
        kids, controls = [], []
        for w in tab["widgets"]:
            if w["kind"] not in CONTROL_KINDS:
                continue
            k = w["key"]
            need = list_keys(w) if w["kind"] == "list" else [k]
            if w["kind"] == "stepper":
                # prev=/next=: explicit override for the arrow tap-zones' bound parameter, for a
                # DSP with a real "advance"/"retreat" verb under a DIFFERENT name than "<key>_prev"/
                # "<key>_next" (e.g. jv880's bank stepper: key=bank_index (a dummy, Q-Link is a
                # no-op) but prev=prev_bank/next=next_bank, its own real DSP verbs). Falls back to
                # the "<key>_prev"/"<key>_next" convention when not given.
                need += [w.get("prev", k + "_prev"), w.get("next", k + "_next")]
                if w.get("get"):
                    need.append(w["get"])
            for nk in need:
                if nk not in index:
                    raise SystemExit("layout: key %r is not a plugin parameter" % nk)
            if w["kind"] == "list":
                controls += list_keys(w)
                continue
            if w["kind"] == "meter":   # display only: no Q-Link
                continue
            p = params[index[k]]
            if w["kind"] == "popup":
                if k + OPEN_SUFFIX not in index:
                    raise SystemExit("layout: popup %r needs param %r (build through gen_vst.py)" % (k, k + OPEN_SUFFIX))
                if not w.get("options"):
                    w["options"] = [str(o) for o in p.get("options") or []]
            if w["kind"].startswith("enum") and not w.get("options"):
                w["options"] = [str(o).upper() for o in p.get("options") or []]   # default: the parameter's own
            if w.get("groups") and sum(g[1] for g in w["groups"]) != len(w["options"]):
                raise SystemExit("layout: %s groups cover %d options, it has %d" % (k, sum(g[1] for g in w["groups"]), len(w["options"])))
            if (w["kind"].startswith("enum") or w["kind"] == "popup") and len(w["options"]) != len(p.get("options") or []):
                raise SystemExit("layout: %s has %d options, parameter has %d" % (k, len(w["options"]), len(p.get("options") or [])))
            controls.append(k)

        # background: frames + static labels, cropped to the plugin area. ONE shared screen per
        # TAB, reused by every Q-Link bank -- several qlinks lines just change which params the
        # physical Q-Link knobs are mapped to (same as any stock multi-bank page), the screen
        # itself doesn't change. A real per-bank SPLIT SCREEN was tried and reverted after user
        # feedback: a small tab (e.g. Play/Sends, 17 controls, comfortably fits on one screen) read
        # as needlessly fragmented, even though it helped a genuinely busy one (docs/NOTES.md). A
        # future per-tab opt-in split is a plausible follow-up, not a default.
        bg = "sh_bg_%d" % t
        titles_ = {q[0] for q in tab["qlinks"]} or {tab["name"]}
        for w in tab["widgets"]:
            if banks_of(w) and not banks_of(w) <= titles_:
                raise SystemExit("layout: banks=%s: not qlinks pages of tab %r (%s)" % (w["banks"], tab["name"], ",".join(sorted(titles_))))
        base = [w for w in tab["widgets"] if not cond(w) and not (banks_of(w) and baked_rect(w))]
        script.append("clear|" + PLATE)
        for w in base:
            script += baked_cmds(w, TITLE_FONT, base_dir)
        script.append("crop|%s|0|%d|%d|%d" % (art(bg), Y_OFF, W, H))
        decor.append((bg, 0, Y_OFF, base))
        kids.append(_sub("Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": bg + ".png"},
                         _bounds(0, 0, W, H), "Background"))
        # when= widgets: per mode, the background redrawn with that mode's baked parts, cropped to them
        modes = {}
        for w in tab["widgets"]:
            if cond(w):
                modes.setdefault(cond(w), []).append(w)
            elif banks_of(w) and baked_rect(w):   # baked parts on some sub-pages only: their own image, filtered below
                modes.setdefault(("banks", w["banks"]), []).append(w)
        for m_i, (hnd, ws) in enumerate(modes.items()):
            rects = [baked_rect(w) for w in ws if baked_rect(w)]
            if not rects:
                continue
            bx, by = max(0, min(r_[0] for r_ in rects)), max(Y_OFF, min(r_[1] for r_ in rects))
            bw = min(W, max(r_[0] + r_[2] for r_ in rects)) - bx
            bh = min(Y_OFF + H, max(r_[1] + r_[3] for r_ in rects)) - by
            img = "sh_mode_%d_%d" % (t, m_i)
            script.append("clear|" + PLATE)
            for w in base + ws:
                script += baked_cmds(w, TITLE_FONT, base_dir)
            script.append("crop|%s|%d|%d|%d|%d" % (art(img), bx, by, bw, bh))
            decor.append((img, bx, by, base + ws))
            c = _sub("Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": img + ".png"},
                     _bounds(bx, by - Y_OFF, bw, bh), "Mode")
            if isinstance(hnd, tuple):
                kid_banks[id(c)] = banks_of({"banks": hnd[1]})
            else:
                c["bounds"]["additionalInvalidatingHandles"] = [hnd]
            kids.append(c)
        # Stepper arrow tap-zones: crop the arrow glyph ALREADY drawn into this background (by
        # widget_stepper/dot_stepper) as the tap-zone's own on/off image. An empty onImage/
        # offImage ("") makes MPC show a generic placeholder caption ("Button") over the arrow
        # instead of nothing -- found on a real device (the stepper feature's first hardware test).
        for w in tab["widgets"]:
            if w["kind"] != "stepper":
                continue
            for side, (ax, ay, aw, ah) in zip(("prev", "next"), stepper_arrows(w)):
                img = "sh_arrow_%d_%s_%s" % (t, w["key"], side)
                script.append("crop|%s|%d|%d|%d|%d" % (art(img), ax, ay, aw, ah))

        on_top = []   # popup panels: drawn last, so an open list covers (and takes touches from) the page
        bpend = None   # (first kid, first on_top part, banks) of the last banks= control, tagged once it is done

        def close_banks():
            if bpend:
                for c in kids[bpend[0]:] + on_top[bpend[1]:]:
                    kid_banks[id(c)] = bpend[2]
        for w in tab["widgets"]:
            kind = w["kind"]
            if kind not in CONTROL_KINDS:
                continue
            close_banks()
            bpend = (len(kids), len(on_top), banks_of(w)) if banks_of(w) else None
            if tagged and tagged[-1][1] is None:
                tagged[-1][1] = len(kids)
            if cond(w):
                tagged.append([len(kids), None, w])
            i, name = index.get(w["key"], -1), w.get("label", w["key"])
            lk = look_of(w, base_dir)
            lid = skin_assets.look_id(lk)
            sfx = "_" + lid if lk else ""
            if lk:
                looks[lid] = lk
            if kind == "knob" and w.get("lay") == "side":
                # the knob's picture at the left of a bw x bh box, its value centred in the rest, no name: a big value
                # dragged like a knob (a sequencer's step cells; after saustin2010/vst_instruments' Stevequencer)
                r = w["r"]
                s_ = 2 * r + 10
                bw_, bh_ = w.get("bw") or 4 * s_, max(s_, w.get("bh") or s_)
                radii.add((r, lid))
                vs_ = float(w.get("vs") or 30)
                key = "shKnobSide%d%s_v%d_%dx%d" % (r, sfx, vs_, bw_, bh_)
                defs.setdefault(key, _local(key, [_action("Mouse Down", "Q-Link"),
                                                  _action("Double Click", "Show Overlay", "knob overlay"),
                                                  _action("Enter Pressed", "Show Overlay", "knob overlay")], [
                    _focus(bw_, bh_),
                    _sub("Knob", {"version": 5, "knobType": "FilmStrip", "filmStrip": "sh_knob_r%d%s.png" % (r, sfx),
                                  "numFrames": ROT_FRAMES, "invert": False, "dragOrientation": "Vertical",
                                  "handleName": "Data"}, _bounds(0, (bh_ - s_) // 2, s_, s_), "Knob"),
                    _value_label(s_ + 4, 0, bw_ - s_ - 8, bh_, vs_, w.get("ink") or INK)]))
                kids.append(_placed(key, name, i, w["cx"] - bw_ // 2, w["cy"] - bh_ // 2, bw_, bh_))
            elif kind == "knob":
                r = w["r"]
                s, cw = 2 * r + 10, max(round(130 * LABEL_SCALE) if SCALE_NAMES else 130, 2 * r + 10)   # value label width; LFO knobs sit 138 px apart
                if w.get("bw"):   # bw=: a narrower touch box (and name/value width) for close neighbours
                    cw = max(s, w["bw"])
                nfont = NAME_FONT("knob") if w.get("ns") is None else float(w["ns"])   # ns=/vs=: name/value px (ns=0: no name)
                vfont = 22.0 * LABEL_SCALE if w.get("vs") is None else float(w["vs"])
                if s * FRAMES > 16384:   # MPC garbles taller filmstrips (the knob drifts as it turns): docs/NOTES.md
                    sys.stderr.write("warning: knob r=%d (%s): its %d px filmstrip is over MPC's 16384 px image limit; "
                                     "use r <= %d\n" % (r, w["key"], s * FRAMES, (16384 // FRAMES - 10) // 2))
                name_h = NAME_H() if SCALE_NAMES else round(20 * LABEL_SCALE)
                if w.get("ns") is not None:
                    name_h = 0 if w["ns"] == 0 else max(name_h, round(w["ns"] * 1.2))
                name_y = s // 2 + r + 2
                value_y = name_y + name_h + (2 if name_h else 0)
                value_h = round(26 * LABEL_SCALE) if w.get("vs") is None else max(round(26 * LABEL_SCALE), round(w["vs"] * 1.2))
                ch = value_y + value_h + 6
                radii.add((r, lid))
                ink, dim = w.get("ink") or INK, w.get("ink_dim") or INK_DIM   # per-control label colours (ink=, ink_dim=)
                key = "shKnob%d%s%s%s" % (r, sfx, ("_ls%g" % LABEL_SCALE) if LABEL_SCALE != 1.0 else "",
                                          "_c%s%s" % (ink, dim) if (ink, dim) != (INK, INK_DIM) else "") + text_sfx(w, cw)
                defs.setdefault(key, _local(key, [_action("Mouse Down", "Q-Link"),
                                                  _action("Double Click", "Show Overlay", "knob overlay"),
                                                  _action("Enter Pressed", "Show Overlay", "knob overlay")], [
                    _focus(cw, ch),
                    _sub("Knob", {"version": 5, "knobType": "FilmStrip", "filmStrip": "sh_knob_r%d%s.png" % (r, sfx),
                                  "numFrames": ROT_FRAMES, "invert": False, "dragOrientation": "Vertical",
                                  "handleName": "Data"}, _bounds((cw - s) // 2, 0, s, s), "Knob"),
                    ] + ([_name_label(0, name_y, cw, name_h, nfont, ink)] if name_h else []) + [
                    _sub("Label", {"version": 1, "textStyle": {"version": 1, "font": {"version": 1, "name": "Titillium Web",
                                                                                     "style": "SemiBold", "height": vfont},
                                                               "colour": "ff" + dim,
                                                               "justification": "horizontallyCentred verticallyCentred",
                                                               "case": "Upper Case"},
                                   "type": "Value", "handleName": "Data"},
                         _bounds(0, value_y, cw, value_h), "Value")]))
                kids.append(_placed(key, name, i, w["cx"] - cw // 2, w["cy"] - s // 2, cw, ch))
            elif kind == "toggle" and lk:
                tw, th = skin_assets.toggle_size(w, lk)
                nn = w.get("ns") == 0   # ns=0: no name label, the box is just the picture
                key = "shToggle_%s_%dx%d" % (lid, tw, th) + text_sfx(w, 0)
                cw, ch = (tw, th) if nn else (max(w.get("bw") or TOG_W(), tw + 10), th + 6 + NAME_H())
                if key not in defs:
                    img = "sh_tog_%s_%dx%d" % (lid, tw, th)
                    for on in (0, 1):
                        script += ["clear|" + under(), "ltog|200|300|%d|%d|%d|%s" % (on, tw, th, skin_assets.encode(lk)),
                                   "crop|%s|200|300|%d|%d" % (art("%s_%s" % (img, "on" if on else "off")), tw, th)]
                    defs[key] = _local(key, [_action("Mouse Down", "Q-Link"), _action("Enter Pressed", "Toggle Switch")],
                                       [_focus(cw, ch), _button(img + "_on.png", img + "_off.png", 1, 1, tw, th, (cw - tw) // 2, 0)] +
                                       ([] if nn else [_name_label(0, th + 4, cw, NAME_H(), NAME_FONT("toggle"), INK)]))
                kids.append(_placed(key, name, i, w["cx"] - cw // 2, w["cy"] - th // 2, cw, ch))
            elif kind == "toggle":
                cw = max(53, w.get("bw") or TOG_W())   # bw=: a narrower touch box (and name) for close neighbours
                nn = w.get("ns") == 0   # ns=0: the pill alone, no name
                cw, th_ = (53, 37) if nn else (cw, 38 + NAME_H())
                key = "shToggle" + (("_ls%g" % LABEL_SCALE) if SCALE_NAMES and LABEL_SCALE != 1.0 else "") + text_sfx(w, 0)
                if key not in defs:
                    for on in (0, 1):
                        script += ["clear|" + under(), "pill|100|100|%d" % on,
                                   "crop|%s|74|86|53|29" % art("sh_pill_%s" % ("on" if on else "off"))]
                    defs[key] = _local(key, [_action("Mouse Down", "Q-Link"), _action("Enter Pressed", "Toggle Switch")],
                                       [_focus(cw, th_), _button("sh_pill_on.png", "sh_pill_off.png", 1, 1, 53, 29, (cw - 53) // 2, 4)] +
                                       ([] if nn else [_name_label(0, 34, cw, NAME_H(), NAME_FONT("toggle"), INK)]))
                kids.append(_placed(key, name, i, w["cx"] - cw // 2, w["cy"] - 18, cw, th_))
            elif kind == "button":
                x, y, bw, bh = button_rect(w, base_dir)
                lab_off = w.get("label", "")
                lab_on = w.get("label_on") or lab_off
                img = "sh_btn_%s_%s%s" % (w["key"], slug(lab_off + ("_" + lab_on if lab_on != lab_off else "")), sfx)
                base = w.get("color") or BTN_BG or ACCENT
                # shadow_art's "button" command has no '-' -> empty convention (unlike frame/
                # readout/stepper) and strtok() would collapse a genuinely empty field anyway,
                # so a single space is the baked placeholder when the real label is drawn later.
                sized = "w" in w and "h" in w and not lk
                longer = lab_on if len(lab_on) > len(lab_off) else lab_off
                scale = 1.15
                if sized and longer:
                    scale = min((bw - 24) / (max(len(longer), 1) * 10.0), (bh - 12) / 14.0)
                    if scale < 1.15:
                        scale = 1.15
                live_cap = bool(w.get("tsize") and w.get("get") in index)
                on_fill = BTN_ON or ACCENT
                for state, col, lab in (("off", base, lab_off), ("on", on_fill, lab_on)):
                    baked_label = " " if TITLE_FONT or live_cap else lab
                    if sized:
                        draw = "boxbtn|%d|%d|%d|%d|%s|%s|%g" % (x, y, bw, bh, col, baked_label, scale)
                    elif lk:
                        draw = "lbtn|%d|%d|%d|%d|%d|%s|%s" % (x, y, bw, bh, state == "on", baked_label, skin_assets.encode(lk))
                    else:
                        draw = "button|%d|%d|%s|%s" % (w["cx"], w["cy"], col, baked_label)
                    ppm = art("%s_%s" % (img, state))
                    script += ["clear|" + under(), draw, "crop|%s|%d|%d|%d|%d" % (ppm, x, y, bw, bh)]
                    if TITLE_FONT and lab:
                        label_overlays.append((ppms[-1][1], bw, bh, lab, "fdf3ea"))
                key = "shTrig_%s_%s%s" % (w["key"], slug(w.get("label", "")), sfx)
                parts = [_focus(bw, bh), _button(img + "_on.png", img + "_off.png", 1, 1, bw, bh)]
                extra = None
                if live_cap:
                    size, colour, just, style, font, sig = live_text(w, 46.0, INK, "horizontallyCentred verticallyCentred")
                    left = 12
                    parts.append(_value_label(left, 0, bw - left - 12, bh, size, colour, just,
                                              handle="Text", style=style, font=font))
                    extra = {"Text": index[w["get"]]}
                    hit = write_hit_png(skin_dir, bw, bh)
                    parts.append(_button(hit, hit, 1, 1, bw, bh))
                    key += sig
                defs[key] = _local(key, [_action("Mouse Down", "Toggle Switch"),
                                         _action("Enter Pressed", "Toggle Switch")], parts)
                kids.append(_placed(key, name, i, x, y, bw, bh, extra=extra))
            elif kind in ("slider_v", "slider_h"):
                sw_, sh_ = w["w"], w["h"]
                vert = kind == "slider_v"
                img = "sh_%s_%dx%d%s" % (kind, sw_, sh_, sfx)
                nfr = strip_frames(sh_)
                img += "_f%d" % nfr if nfr != FRAMES else ""
                sliders.add((img, sw_, sh_, vert, lid, nfr))
                # as stock skins (Electric slider_distance 250x6969 = 101 frames of 69): frames of the slider's own
                # w x h, numFrames = their count, bounds = the slider (docs/NOTES.md 2026-10-07)
                cw = max(sw_, w["bw"]) if w.get("bw") else max(130, sw_)
                nfont, vfont = float(17 if w.get("ns") is None else w["ns"]), float(22 if w.get("vs") is None else w["vs"])
                name_h = 0 if nfont == 0 else max(20, round(nfont * 1.2))
                value_h = max(26, round(vfont * 1.2))
                name_y = sh_ + 2
                value_y = name_y + name_h + (2 if name_h else 0)
                ch = value_y + value_h + 6
                key = "shSlider_%s_%dx%d%s%s" % ("v" if vert else "h", sw_, sh_, sfx, text_sfx(w, cw))
                defs.setdefault(key, _local(key, [_action("Mouse Down", "Q-Link"),
                                                  _action("Double Click", "Show Overlay", "knob overlay"),
                                                  _action("Enter Pressed", "Show Overlay", "knob overlay")], [
                    _focus(cw, ch),
                    _sub("Knob", {"version": 5, "knobType": "FilmStrip", "filmStrip": img + ".png",
                                  "numFrames": nfr, "invert": False,
                                  "dragOrientation": "Vertical" if vert else "Horizontal",
                                  "handleName": "Data"}, _bounds((cw - sw_) // 2, 0, sw_, sh_), "Slider"),
                    ] + ([_name_label(0, name_y, cw, name_h, nfont, INK)] if name_h else []) + [
                    _value_label(0, value_y, cw, value_h, vfont, INK_DIM)]))
                kids.append(_placed(key, name, i, w["cx"] - cw // 2, w["cy"] - sh_ // 2, cw, ch))
            elif kind == "meter" and lk and lk.get("look") == "native":
                # EXPERIMENTAL, unverified (docs/ROADMAP.md "A native Meter component"): a real Meter component
                # instead of a Knob/FilmStrip pretending to be one. inactiveImage is the constant background;
                # peakImage/rmsImage are guessed (by analogy with Slider's revealedImage/revealType, a confirmed
                # sibling mechanism) to be revealed proportionally to the bound handle -- unverified on a device.
                mw, mh = w["w"], w["h"]
                key = "shMeterN_%dx%d_%s" % (mw, mh, lid)
                if key not in defs:
                    direction = {"up": "Up", "down": "Down", "right": "Right"}.get(w.get("direction", "up").lower(), "Up")
                    data = {"version": 5, "direction": direction, "invert": w.get("invert") in ("1", "true", "True")}
                    for attr, field, handle in (("img", "inactiveImage", None), ("peak", "peakImage", "peakHandle"),
                                                ("rms", "rmsImage", "rmsHandle")):
                        if not lk.get(attr):
                            continue
                        img = "sh_meter_n_%s_%s" % (lid, attr)
                        script += ["clear|" + under(), "limg|%s|%d|%d|stretch" % (lk[attr], mw, mh),
                                   "crop|%s|0|0|%d|%d" % (art(img), mw, mh)]
                        data[field] = img + ".png"
                        if handle:
                            data[handle] = "Data"
                    defs[key] = _local(key, [], [_sub("Meter", data, _bounds(0, 0, mw, mh), "Meter")])
                kids.append(_placed(key, name, i, w["cx"] - mw // 2, w["cy"] - mh // 2, mw, mh, focus="No"))
            elif kind == "meter":   # a filmstrip with no actions: it shows the parameter, touch does nothing
                mw, mh = w["w"], w["h"]
                # laid out as stock display strips (Bassline knob_phase 76x258 = 3 frames of 86): frames of the meter's
                # own w x h, its strip's own frame count (frames=, else counted from the image), numFrames = that count
                own = (lk or {}).get("frames") or (skin_assets.strip_layout(lk["strip"], None, mh / max(1, mw))[2]
                                                   if lk and lk.get("strip") else FRAMES)
                nfr = strip_frames(mh, int(own))
                img = "sh_meter_%dx%d%s_f%d" % (mw, mh, sfx, nfr)
                sliders.add((img, mw, mh, 1, lid, nfr))
                key = "shMeter_%dx%d%s_f%d" % (mw, mh, sfx, nfr)
                defs.setdefault(key, _local(key, [], [
                    _sub("Knob", {"version": 5, "knobType": "FilmStrip", "filmStrip": img + ".png", "numFrames": nfr,
                                  "invert": False, "dragOrientation": "Vertical", "handleName": "Data"},
                         _bounds(0, 0, mw, mh), "Meter")]))
                kids.append(_placed(key, name, i, w["cx"] - mw // 2, w["cy"] - mh // 2, mw, mh, focus="No"))
            elif kind == "menu":
                x, y, rw, rh = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w["w"], w["h"]
                key = "shMenu_%dx%d" % (rw, rh)
                overlay = [_action("Mouse Down", "Show Overlay", "menu overlay"),
                           _action("Double Click", "Show Overlay", "menu overlay"),
                           _action("Enter Pressed", "Show Overlay", "menu overlay")]
                defs.setdefault(key, _local(key, overlay, [_focus(rw, rh), _value_label(8, 0, rw - 16, rh, 26.0, ACCENT)]))
                kids.append(_placed(key, name, i, x, y, rw, rh))
            elif kind == "popup":
                # Data = the "open" flag (a tap toggles it); Text = the enum, whose value the field shows.
                # The list is visible only while open (IndexedEnabling, docs/NOTES.md) and is one radio
                # group on the enum; the wrapper clears "open" when an option is picked.
                oi = index[w["key"] + OPEN_SUFFIX]
                x, y, rw, rh = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w["w"], w["h"]
                acc = w.get("accent") or ACCENT   # per-control field text colour (accent=)
                csfx = "_c" + acc if acc != ACCENT else ""
                if w.get("wheel") in ("1", "true", "yes"):
                    # wheel=1 (EXPERIMENTAL, unverified on a device): the field's Data handle is the enum itself, so the
                    # data wheel / a Q-Link step through the options while it has focus; a tap toggles the list through
                    # a second, named handle ("Open"), as stock skins name action handles.
                    key = "shPopFieldW_%dx%d%s" % (rw, rh, csfx)
                    defs.setdefault(key, _local(key, [_action("Mouse Down", "Toggle Switch", handle="Open"),
                                                      _action("Enter Pressed", "Toggle Switch", handle="Open")],
                                                [_focus(rw, rh), _value_label(8, 0, rw - 44, rh, 26.0, acc, handle="Text")]))
                    kids.append(_placed(key, name, i, x, y, rw, rh, extra={"Text": i, "Open": oi}))
                else:
                    key = "shPopField_%dx%d%s" % (rw, rh, csfx)
                    defs.setdefault(key, _local(key, [_action("Mouse Down", "Toggle Switch"), _action("Enter Pressed", "Toggle Switch")],
                                                [_focus(rw, rh), _value_label(8, 0, rw - 44, rh, 26.0, acc, handle="Text")]))
                    kids.append(_placed(key, name, oi, x, y, rw, rh, extra={"Text": i}))
                (px, py, pw, ph), orects = popup_panel(w)
                shown = "IndexedEnabling/1/2/Parameter %d" % oi
                panel = "sh_pop_%d_%s" % (t, w["key"])
                panel_draw = ("image|%s|%d|%d|%d|%d|stretch" % (lk["img"], px, py, pw, ph) if lk
                              else "tile|%d|%d|%d|%d|%s|%s|2" % (px, py, pw, ph, LCD, ACCENT))
                script += ["clear|" + LCD, panel_draw] + popup_heading_cmds(w) + ["crop|%s|%d|%d|%d|%d" % (art(panel), px, py, pw, ph)]
                pkey = "shPopPanel_%d_%s" % (t, w["key"])
                defs[pkey] = _local(pkey, [], [_sub("Image", {"version": 2, "imageType": "Regular", "colour": "0",
                                                              "image": panel + ".png"}, _bounds(0, 0, pw, ph), "Image")])
                parts = [_placed(pkey, "%s list" % name, oi, px, py, pw, ph, focus="No")]
                n = len(w["options"])
                fills, inks = popup_option_fills(w), popup_option_inks(w)
                for o, (ox, oy, ow, oh) in enumerate(orects):
                    # an option's two images depend only on its text, colours and size: pickers with the same options share them
                    # (a 76-option destination list used on two dozen controls was 3000 files)
                    sig = (w["options"][o], fills[o], inks[o], ow, oh)
                    img = popopt_img.setdefault(sig, "sh_po_%d" % len(popopt_img))
                    if img not in popopt_done:
                        popopt_done.add(img)
                        for state, fill, ink in (("on", SEG_ON, SEG_ON_TX), ("off", fills[o], inks[o])):
                            script += ["clear|" + LCD, "seg|%d|%d|%d|%d|%s|%s|%s" % (ox, oy, ow, oh, fill, ink, w["options"][o]),
                                       "crop|%s|%d|%d|%d|%d" % (art("%s_%s" % (img, state)), ox, oy, ow, oh)]
                    okey = "shPopOpt_%d_%s_%d" % (t, w["key"], o)
                    defs[okey] = _local(okey, [_action("Mouse Down", "Q-Link")],
                                        [_button(img + "_on.png", img + "_off.png", o, n, ow, oh)])
                    parts.append(_placed(okey, "%s %s" % (name, w["options"][o]), i, ox, oy, ow, oh, focus="No"))
                for c in parts:
                    c["bounds"]["showWhenDataModelInvalid"] = "Show"
                    c["bounds"]["additionalInvalidatingHandles"] = [shown]
                on_top += parts
            elif kind == "readout":
                x, y, rw, rh = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w["w"], w["h"]
                dot = w.get("style") == "dotmatrix"
                size, colour, just, style, font, sig = live_text(w, 26.0, DISPLAY_INK if dot else ACCENT, READOUT_JUST)
                pad = int(w.get("tpad", 8))
                key = "shReadout_%s%dx%d%s_p%d" % ("dot_" if dot else "", rw, rh, sig, pad) if sig or pad != 8 else \
                    "shReadout_%s%dx%d" % ("dot_" if dot else "", rw, rh)
                defs.setdefault(key, _local(key, [], [_value_label(pad, 0, rw - 2 * pad, rh, size, colour, just,
                                                                   style=style, font=font)]))
                kids.append(_placed(key, name, i, x, y, rw, rh, focus="No"))
            elif kind == "stepper":
                x0, y0 = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2
                h = w["h"]
                dot = w.get("style") == "dotmatrix"
                # "get=<key>": the text shown can be a DIFFERENT parameter than the one Q-Link
                # nudges (e.g. show patch_name's text while stepping the numeric preset index) --
                # see docs/NOTES.md's "shows 0" entry. Bound to its own "Text" handle so it's
                # independent of "Data" (the stepper's own Q-Link/inc-dec target).
                gi = index.get(w.get("get"), i) if w.get("get") else i
                size, colour, just, style, font, sig = live_text(w, 26.0, DISPLAY_INK if dot else ACCENT,
                                                                 "left verticallyCentred")
                key = "shStepText_%s%dx%d%s" % ("dot_" if dot else "", w["w"] - 2 * h - 6, h, sig)
                defs.setdefault(key, _local(key, [_action("Mouse Down", "Q-Link"),
                                                  _action("Double Click", "Show Overlay", "knob overlay")],
                                            [_focus(w["w"] - 2 * h - 6, h),
                                             _value_label(8, 0, w["w"] - 2 * h - 22, h, size, colour, just,
                                                          handle="Text", style=style, font=font)]))
                kids.append(_placed(key, name, i, x0 + h + 3, y0, w["w"] - 2 * h - 6, h, extra={"Text": gi}))
                for side, (ax, ay, aw, ah) in zip(("prev", "next"), stepper_arrows(w)):
                    aimg = "sh_arrow_%d_%s_%s.png" % (t, w["key"], side)
                    akey = "shTap_%d_%s_%s" % (t, w["key"], side)
                    defs.setdefault(akey, _local(akey, [_action("Enter Pressed", "Toggle Switch")],
                                                 [_button(aimg, aimg, 1, 1, aw, ah)]))
                    side_key = w.get(side, w["key"] + "_" + side)
                    kids.append(_placed(akey, "%s %s" % (name, side), index[side_key], ax, ay, aw, ah, focus="No"))
            elif kind == "list":
                tiles = list(zip(list_tiles(w), list_keys(w)))
                vel = w.get("mark") == "vel"
                if vel and tiles:
                    tw, th = tiles[0][0][2], tiles[0][0][3]
                    img = "sh_cell_%dx%d" % (tw, th)
                    script += ["clear|" + under(), "nmark|%d|%d|%s|%s|2|0" % (tw, th, LCD, ACCENT),
                               "crop|%s|0|0|%d|%d" % (art(img + "_off"), tw, th)]
                    for level, alpha in ((1, 90), (2, 150), (3, 205), (4, 255)):
                        script += ["clear|" + under(),
                                   "nmark|%d|%d|%s|%s|2|%d" % (tw, th, LCD, ACCENT, alpha),
                                   "crop|%s|0|0|%d|%d" % (art("sh_note_%dx%d_%d" % (tw, th, level)), tw, th)]
                tint = w.get("tint") in ("1", "yes", "on")
                for slot, ((x, y, tw, th), sk) in enumerate(tiles):
                    if tint:
                        tint_sizes.add((tw, th))
                        n = int(sk.rsplit("_", 1)[-1])
                        tk = "tint_%d" % n
                        if tk not in index:
                            raise SystemExit("layout: tint=1 on %s needs a parameter %s" % (sk, tk))
                        size, colour, just, style, font, sig = live_text(w, 24.0, INK, "horizontallyCentred verticallyCentred")
                        lx, ly = int(w.get("tx", 12)), int(w.get("ty", 0))
                        lw, lh = int(w.get("ttw", tw - lx - 12)), int(w.get("tth", th - ly))
                        acts = [_action("Mouse Down", "Toggle Switch"), _action("Enter Pressed", "Toggle Switch")]
                        for ci in range(len(PAD_TINTS)):
                            img = "sh_padtint_%dx%d_%d" % (tw, th, ci)
                            key = "shPadTint_%dx%d_%d%s" % (tw, th, ci, sig)
                            defs.setdefault(key, _local(key, acts, [
                                _focus(tw, th), _button(img + "_on.png", img + "_off.png", 1, 1, tw, th),
                                _value_label(lx, ly, lw, lh, size, colour, just, style=style, font=font)]))
                            c = _placed(key, "%s %d" % (name, slot + 1), index[sk], x, y, tw, th,
                                        focus="Yes" if slot == 0 and ci == 0 else "No")
                            c["bounds"]["additionalInvalidatingHandles"] = [
                                "IndexedEnabling/%d/%d/Parameter %d" % (ci, len(PAD_TINTS), index[tk])]
                            c["bounds"]["showWhenDataModelInvalid"] = "Hide"
                            kids.append(c)
                        continue
                    own = w.get("img")   # img=/img_on=: the port's own card pictures (off, selected)
                    mark = w.get("mark") in ("1", "yes", "on")
                    tile_fill = w.get("color") or LCD
                    img = "sh_tile_%dx%d" % (tw, th) if not own else "sh_card_%s_%dx%d" % (slug(w["key"]), tw, th)
                    if w.get("color") and not own:
                        img = "sh_tile_%dx%d_%s" % (tw, th, tile_fill)
                    if mark:
                        img = "sh_mark_%dx%d" % (tw, th)
                    if vel:
                        img = "sh_cell_%dx%d" % (tw, th)
                    else:
                        for state, border in (("on", 3), ("off", 0)):
                            if own:
                                drawn = card_art(w.get("img_on", own) if border else own, x, y, tw, th, base_dir)
                            elif mark:
                                drawn = "tile|%d|%d|%d|%d|%s|%s|0" % (x, y, tw, th, ACCENT if border else tile_fill, LINE)
                            else:
                                drawn = "tile|%d|%d|%d|%d|%s|%s|%d" % (x, y, tw, th, (TILE_ON or tile_fill) if border else tile_fill, SEG_ON if border else LINE, border)
                            script += ["clear|" + under(), drawn,
                                       "crop|%s|%d|%d|%d|%d" % (art("%s_%s" % (img, state)), x, y, tw, th)]
                    size, colour, just, style, font, sig = live_text(w, 24.0, ACCENT, ROW_JUST)
                    # tx=/ty=/ttw=/tth= place the row's text inside the card (default: the whole row, 12 px in)
                    lx, ly = int(w.get("tx", 12)), int(w.get("ty", 0))
                    lw, lh = int(w.get("ttw", tw - lx - 12)), int(w.get("tth", th - ly))
                    key = "shRow_%dx%d%s" % (tw, th, sig + ("_%d_%d_%d_%d" % (lx, ly, lw, lh) if (lx, ly, lw, lh) != (12, 0, tw - 24, th) else "")
                                            + ("_mark" if mark else "")
                                            + ("_vel" if vel else "")
                                            + ("_" + slug(w["key"]) if own else ""))
                    # the Value label lies over the button and takes the touch, so the row itself toggles on touch
                    acts = [] if w.get("tap") == "no" or vel else [_action("Mouse Down", "Toggle Switch"), _action("Enter Pressed", "Toggle Switch")]
                    on_img = img + "_off.png" if vel else img + "_on.png"
                    defs.setdefault(key, _local(key, acts,
                                                [_focus(tw, th), _button(on_img, img + "_off.png", 1, 1, tw, th),
                                                 _value_label(lx, ly, lw, lh, size, colour, just, style=style, font=font)]))
                    kids.append(_placed(key, "%s %d" % (name, slot + 1), index[sk], x, y, tw, th, focus="Yes" if slot == 0 else "No"))
                    if vel and sk in index:
                        for level in (1, 2, 3, 4):
                            note = "sh_note_%dx%d_%d.png" % (tw, th, level)
                            c = _sub("Image", {"version": 2, "imageType": "Regular", "colour": "0", "image": note},
                                     _bounds(x, y - Y_OFF, tw, th, focus="No", show="Hide"), "Note")
                            c["bounds"]["additionalInvalidatingHandles"] = [
                                "IndexedEnabling/%d/5/Parameter %d" % (level, index[sk])]
                            kids.append(c)
            else:  # enum_h / enum_v: radio group, one image button per option
                n = len(w["options"])
                for o, (x, y, sw, sh) in enumerate(seg_rects(w)):
                    img = "sh_seg_%s_%d" % (w["key"], o)
                    lab = w["options"][o]
                    baked_lab = " " if TITLE_FONT else lab   # see the button block's comment on this placeholder
                    for state, fill, ink in (("on", SEG_ON, SEG_ON_TX), ("off", SEG_OFF, INK_DIM)):
                        draw = ("lseg|%d|%d|%d|%d|%d|%s|%s|%s" % (x, y, sw, sh, state == "on", SEG_ON_TX if state == "on" else INK,
                                                                   baked_lab, skin_assets.encode(lk))
                                if lk else "seg|%d|%d|%d|%d|%s|%s|%s" % (x, y, sw, sh, fill, ink, baked_lab))
                        ppm = art("%s_%s" % (img, state))
                        script += ["clear|" + under(), draw, "crop|%s|%d|%d|%d|%d" % (ppm, x, y, sw, sh)]
                        if TITLE_FONT and lab:
                            label_overlays.append((ppms[-1][1], sw, sh, lab, SEG_ON_TX if state == "on" else INK_DIM))
                    key = "shSeg_%s_%d" % (w["key"], o)
                    defs[key] = _local(key, [_action("Mouse Down", "Q-Link")],
                                       [_button(img + "_on.png", img + "_off.png", o, n, sw, sh)])
                    kids.append(_placed(key, "%s %s" % (name, lab), i, x, y, sw, sh, focus="Yes" if o == 0 else "No"))

        for n0, n1, w in tagged:   # a when= widget's components show only in its mode
            for c in kids[n0:len(kids) if n1 is None else n1]:
                c["bounds"]["showWhenDataModelInvalid"] = "Show"
                c["bounds"]["additionalInvalidatingHandles"].append(cond(w))
        tagged.clear()
        close_banks()
        kids += on_top
        sets = tab["qlinks"] or [(tab["name"], controls[:16])]
        for sp, (title, keys) in enumerate(sets):
            if len(keys) > 16:
                raise SystemExit("layout: qlinks %r has %d keys (max 16)" % (title, len(keys)))
            ql = {"Q-Link %d" % (q + 1): -1 for q in range(16)}
            for s, k in enumerate(keys):
                if k == "-":
                    continue
                if k not in index:
                    raise SystemExit("layout: qlinks key %r is not a parameter" % k)
                ql["Q-Link %d" % qlink_for_slot(s)] = index[k]
            comp = "%s|%s" % (tab["name"], title)
            pages.append({"version": 3, "tabName": title, "fnKeyIndex": t, "fnKeySubIndex": sp,
                          "qlinkBoundsData": qlink_column_bounds(tab, keys, base_dir) if QLINK_COLUMNS else ["0 0 0 0"],
                          "componentName": comp,
                          "initialSize": "0 0 %d %d" % (W, H), "scale": 1.0})
            qmap.append({"Tab": t + 1, "SubTab": sp + 1, "Bank Direction": "Column", "Q-Links": ql})
            defs[comp] = {"key": comp, "value": {
                "version": 4, "actions": [],
                "backgroundData": {"version": 1, "focussed": {"version": 1, "colour": "ff" + PLATE, "image": ""},
                                   "unfocussed": {"version": 1, "colour": "ff" + PLATE, "image": ""}},
                "ignoreMousePresses": False, "disableCoarseDataWheel": False, "repeats": 1,
                "hideQLinkBounds": not QLINK_COLUMNS,
                "componentsData": [c for c in kids if title in kid_banks.get(id(c), {title})]}}

    for img, sw_, sh_, vert, lid, nfr in sorted(sliders):
        if lid:
            script.append("lsstrip|%s|%d|%d|%d|%d|%s" % (art(img), sw_, sh_, nfr, 1 if vert else 0, skin_assets.encode(looks[lid])))
        else:
            script.append("sstrip|%s|%d|%d|%d|%d|%s" % (art(img), sw_, sh_, nfr, 1 if vert else 0, under()))
    for r, lid in sorted(radii):
        if lid:
            script.append("lstrip|%s|%d|%d|%s" % (art("sh_knob_r%d_%s" % (r, lid)), r, FRAMES, skin_assets.encode(looks[lid])))
        else:
            script.append("strip|%s|%d|%d|%s" % (art("sh_knob_r%d" % r), r, FRAMES, under()))
    subprocess.run([art_bin], input="\n".join(script) + "\n", text=True, check=True)
    for ppm, png in ppms:
        png_from_ppm(ppm, png)
    for tw, th in sorted(tint_sizes):
        for ci, rgb in enumerate(PAD_TINTS):
            for state, hot in (("off", False), ("on", True)):
                pad_gel(tw, th, rgb, hot).save(os.path.join(skin_dir, "sh_padtint_%dx%d_%d_%s.png" % (tw, th, ci, state)))
    for img, ox, oy, ws in decor:
        titles = [w for w in ws if TITLE_FONT and w["kind"] == "frame" and w.get("title")]
        pops = [w for w in ws if w["kind"] == "popup"]
        groups = [w for w in ws if TITLE_FONT and w["kind"] in ("enum_h", "enum_v") and w.get("label")]
        if not titles and not pops and not groups:
            continue
        from PIL import Image, ImageDraw, ImageFont
        path = os.path.join(skin_dir, img + ".png")
        im = Image.open(path).convert("RGB")
        dr = ImageDraw.Draw(im)
        for w in titles:
            dr.text((w["x"] + 18 - ox, w["y"] + 8 - oy), w["title"], font=ImageFont.truetype(TITLE_FONT, 26),
                    fill="#" + ACCENT_HI)
        group_font = ImageFont.truetype(TITLE_FONT, 18) if TITLE_FONT else None
        for w in groups:   # enum_h/enum_v's own group label -- see label_cmds()'s title_font branch
            if w["kind"] == "enum_h":
                gx, gy, color = w["cx"], w["cy"] - 33 // 2 - 22, INK
            else:
                n = len(w["options"])
                gx, gy, color = w["cx"], w["cy"] - (n * 32) // 2 - 24, ACCENT_HI
            tb = dr.textbbox((0, 0), w["label"], font=group_font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            dr.text((gx - ox - tw / 2 - tb[0], gy - oy - th / 2 - tb[1]), w["label"], font=group_font, fill="#" + color)
        for w in [q for q in pops if q.get("accent") != "none" and q.get("field") != "none"]:   # the field's "opens a list" marker (accent=none: invisible field)
            x, y = w["cx"] + w["w"] // 2 - 22 - ox, w["cy"] - oy
            dr.polygon([(x - 8, y - 4), (x + 8, y - 4), (x, y + 5)], fill="#" + (w.get("accent") or ACCENT))
        im.save(path)
    if label_overlays:
        from PIL import Image, ImageDraw, ImageFont
        for path, w_px, h_px, text, color in label_overlays:
            im = Image.open(path).convert("RGB")
            dr = ImageDraw.Draw(im)
            font = ImageFont.truetype(TITLE_FONT, max(10, int(h_px * 0.42)))
            tb = dr.textbbox((0, 0), text, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            dr.text(((w_px - tw) / 2 - tb[0], (h_px - th) / 2 - tb[1]), text, font=font, fill="#" + color)
            im.save(path)
    for f in os.listdir(work):
        os.remove(os.path.join(work, f))
    os.rmdir(work)
    return list(defs.values()), pages, qmap


def qlink_column_bounds(tab, keys, base_dir="."):
    """One rectangle per Q-Link column, as stock skins do (e.g. AIR OPx-4): with "Bank Direction": "Column", slots
    1-4 are column 1, 5-8 column 2, ... (qlink_for_slot), and MPC outlines the column the Q-Links currently drive --
    on an MPC One each press of the Q-Link button moves to the next one. A single rectangle around all 16 left MPC
    outlining the wrong area. An empty column in the middle gets an empty rectangle; trailing ones are left out."""
    rects = [qlink_bounds(tab, [k for k in keys[c * 4:c * 4 + 4] if k != "-"], base_dir) for c in range(4)]
    while rects and rects[-1] is None:
        rects.pop()
    return [r or "0 0 0 0" for r in rects]


def qlink_bounds(tab, keys, base_dir="."):
    """Rectangle around the controls in keys (plugin coords), or None if none of them is on the page."""
    xs, ys = [], []
    for w in tab["widgets"]:
        if w["kind"] == "list":
            for (x, y, tw, th), k in zip(list_tiles(w), list_keys(w)):
                if k in keys:
                    xs += [x, x + tw]
                    ys += [y, y + th]
            continue
        if w.get("key") not in keys:
            continue
        if w["kind"] in ("slider_v", "slider_h"):
            xs += [w["cx"] - w["w"] // 2 - 8, w["cx"] + w["w"] // 2 + 8]
            ys += [w["cy"] - w["h"] // 2, w["cy"] + w["h"] // 2 + 56]
            continue
        if w["kind"] in ("readout", "stepper", "menu", "popup"):
            xs += [w["cx"] - w["w"] // 2, w["cx"] + w["w"] // 2]
            ys += [w["cy"] - w["h"] // 2 - 26, w["cy"] + w["h"] // 2]
            continue
        if w["kind"] == "knob":
            r = w["r"]
            xs += [w["cx"] - r - 10, w["cx"] + r + 10]
            ys += [w["cy"] - r - 8, w["cy"] + r + 40]
        elif w["kind"] == "button":   # boxes are per Q-Link column, so a trigger only stretches its own column's box
            x, y, bw, bh = button_rect(w, base_dir)
            xs += [x, x + bw]
            ys += [y, y + bh]
        elif w["kind"] == "meter":
            continue   # meters take no Q-Link
        elif w["kind"] == "toggle":
            xs += [w["cx"] - TOG_W() // 2, w["cx"] + TOG_W() // 2]
            ys += [w["cy"] - 18, w["cy"] + 18 + NAME_H()]
        else:
            for x, y, sw, sh in seg_rects(w):
                xs += [x, x + sw]
                ys += [y - 40, y + sh]
    if not xs:
        return None
    x0, y0 = max(0, min(xs) - 6), max(0, min(ys) - Y_OFF - 6)
    return "%d %d %d %d" % (x0, y0, min(W, max(xs) + 6) - x0, min(H, max(ys) - Y_OFF + 6) - y0)


AKAI = "/usr/share/Akai/Content/Synths/"


def program_qlinks(layout_path, params, qmap):
    """Q-Links outside page-follow (screen) mode: `qlinks_track = key,...` at the top of the layout
    (up to 16, same bank order as pages), else the first page's set."""
    index = {p["key"]: i for i, p in enumerate(params)}
    for line in parse_layout(layout_path)[1]:
        if line.startswith("qlinks_track"):
            keys = [k.strip() for k in line.split("=", 1)[1].split(",") if k.strip()]
            if len(keys) > 16:
                raise SystemExit("layout: qlinks_track has %d keys (max 16)" % len(keys))
            ql = {"Q-Link %d" % (q + 1): -1 for q in range(16)}
            for s_, k in enumerate(keys):
                if k not in index:
                    raise SystemExit("layout: qlinks_track key %r is not a parameter" % k)
                ql["Q-Link %d" % qlink_for_slot(s_)] = index[k]
            return ql
    return dict(qmap[0]["Q-Links"])


def to_mpc2x(tui):
    """Rewrite a generated TUI.json (the MPC OS 3.x format) in the shape MPC OS 2.15.1's own skins use, in place.

    Seen in 2.15.1's stock skins (AIR Amp Sim, Decimator; docs/NOTES.md): the tab is `version 1` with its page inline as
    `componentDefinition`, definitions are `version 2` without `repeats`/`hideQLinkBounds`, `Knob` data is `version 1`
    (no `invert`/`dragOrientation`), `Button` data is `version 1` (no `gestureBehaviour`) and actions are `version 1` (no
    `handle remapping`, which is always empty in Akai's own skins). Checked role by role against 110 stock 2.15.1 skins:
    every role in the six released ports' skins then has a version 2.15.1 itself uses. Experimental: touch behaviour on
    2.x not yet confirmed on a device."""
    pd = tui["pageData"]
    cdefs = pd["componentDefinitions"]
    defs = {d["key"]: d for d in cdefs["localComponentDefinitions"]}
    used = set()
    for t in pd["tabs"]:
        if t.get("version") == 3:
            key = t.pop("componentName")
            if key not in defs:
                raise SystemExit("to_mpc2x: tab %r points at missing definition %r" % (t.get("tabName"), key))
            t.pop("initialSize", None)
            t.pop("scale", None)
            t["componentDefinition"] = defs[key]["value"]
            t["version"] = 1
            used.add(key)
    cdefs["localComponentDefinitions"] = [d for d in cdefs["localComponentDefinitions"] if d["key"] not in used]

    def fix(o):
        if isinstance(o, dict):
            cd = o.get("componentData")
            if isinstance(cd, dict):
                dd = cd.get("data", {})
                if cd.get("type") == "Knob" and dd.get("version") == 5:
                    dd["version"] = 1
                    dd.pop("invert", None)
                    dd.pop("dragOrientation", None)
                elif cd.get("type") == "Button" and dd.get("version") == 2:
                    dd["version"] = 1
                    dd.pop("gestureBehaviour", None)
            if o.get("version") == 2 and "onAction" in o and "handler" in o:   # an action: 2.x only has version 1
                o["version"] = 1
                o.pop("handle remapping", None)
            if o.get("version") == 4 and "componentsData" in o:     # a page or widget definition
                o["version"] = 2
                o.pop("repeats", None)
                o.pop("hideQLinkBounds", None)
            for x in list(o.values()):
                fix(x)
        elif isinstance(o, list):
            for x in o:
                fix(x)
    fix(pd)
    return tui


def write_skin(outdir, vendor, name, layout_path, params, art_bin, mpc_os=None):
    """Build the whole skin folder <outdir>/<vendor> - VST - <name>/ from a layout. Needs Pillow.
    mpc_os=2 (or SHADOW_SKIN_MPC_OS=2) writes TUI.json in the older MPC OS 2.x shape (to_mpc2x); default is 3.x."""
    import json
    if mpc_os is None:
        mpc_os = int(os.environ.get("SHADOW_SKIN_MPC_OS", "3"))
    from PIL import Image
    d = os.path.join(outdir, "%s - VST - %s" % (vendor, name))
    skin = os.path.join(d, "Plugin Skins")
    os.makedirs(skin, exist_ok=True)
    comps, tabs, qmap = build(layout_path, params, skin, art_bin, lambda a, b: Image.open(a).save(b))
    tui = {"pageData": {
        "version": 1,
        "componentDefinitions": {"version": 2, "importFiles": [AKAI + "Generic/Generic Knob Overlay.json",
                                                              AKAI + "Generic/Generic Menu Overlay.json"],
                                 "localComponentDefinitions": comps},
        "info": {"version": 1, "type": "CompleteDescription"},
        "tabs": tabs}}
    if mpc_os == 2:
        to_mpc2x(tui)
    qlinks = {"version": 4, "info": {"version": 1, "type": "CompleteDescription"},
              "Screen Mode Q-Links": {"version": 4, "map": qmap},
              "Program Mode Q-Links": program_qlinks(layout_path, params, qmap)}
    open(os.path.join(d, "version.xml"), "w").write(
        "<?xml version='1.0' encoding='utf-8'?>\n<plugincontent version=\"1.0\">\n"
        "\t<identifier>%s.vst.%s</identifier>\n\t<version>1.0.0.0</version>\n</plugincontent>\n"
        % (vendor, name.lower().replace(" ", "")))
    for f, obj in (("TUI.json", tui), ("Q-Links.json", qlinks), ("Q-Links - 8by1.json", qlinks)):
        # a huge TUI.json (every nested Q-Link page repeats its tab's layout) is written compact: the indentation alone is
        # about 3/4 of the file, which MPC has to read and parse when the plugin loads. Small skins stay byte-identical.
        text = json.dumps(obj, separators=(",", ":"))
        open(os.path.join(skin, f), "w").write(text if len(text) > 8_000_000 else json.dumps(obj, indent=4))
    return d
