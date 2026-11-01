#!/usr/bin/env python3
"""Plugin Manager browser tile (270x110): wordmark at the left, a three-row plugin list with status pills at the
right, and a red download badge. Text is converted to outlines (Titillium Web Bold, SIL OFL) so the SVG renders
the same everywhere. Writes tile.svg next to this script; render it with
    rsvg-convert -w 270 -h 110 vst/art/tile.svg -o vst/art/tile.png
(needs fontTools: pip install fonttools)."""
import os, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

# Titillium Web ships with mpc-vst-plugins (tools/html_art/fonts); point MPC_VST or TILE_FONTS elsewhere if needed
FONTS = os.environ.get("TILE_FONTS") or os.path.join(
    os.environ.get("MPC_VST", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..")),
    "tools", "html_art", "fonts")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "tile.svg")

# the skin's palette (vst/make_images.py)
BG, PANEL, LINE, INK, DIM, MUTED = "#0c0c0d", "#151517", "#26272a", "#ececed", "#9da1a7", "#b4b7bc"
RED, AMBER, GREEN = "#e0342c", "#f0a830", "#7fd6a8"
CARD_ON, CARD_OFF, CARD_EDGE, THUMB, THUMB_EDGE = "#1d1e21", "#151517", "#222326", "#24262a", "#34363b"

_fonts = {}
def font(weight):
    if weight not in _fonts:
        _fonts[weight] = TTFont(os.path.join(FONTS, "TitilliumWeb-%s.ttf" % weight))
    return _fonts[weight]

def text_path(s, x, y, size, fill, weight="Bold", spacing=0.0, anchor="start"):
    """Outlines of `s` with its baseline at (x, y), as one <path>."""
    f = font(weight)
    upm = f["head"].unitsPerEm
    cmap = f.getBestCmap()
    gs = f.getGlyphSet()
    hmtx = f["hmtx"]
    k = size / upm
    names = [cmap[ord(c)] for c in s]
    width = sum(hmtx[n][0] * k for n in names) + spacing * (len(names) - 1)
    if anchor == "middle":
        x -= width / 2
    elif anchor == "end":
        x -= width
    pen = SVGPathPen(gs)
    cx = x
    for n in names:
        gs[n].draw(TransformPen(pen, (k, 0, 0, -k, cx, y)))
        cx += hmtx[n][0] * k + spacing
    return '<path fill="%s" d="%s"/>' % (fill, pen.getCommands()), width

def rr(x, y, w, h, r, fill, stroke=None, sw=1):
    s = '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s"' % (x, y, w, h, r, fill)
    if stroke:
        s += ' stroke="%s" stroke-width="%g"' % (stroke, sw)
    return s + "/>"

def stroke_icon(d, x, y, s, colour, width=2.5):
    """A 24x24 stroke icon drawn at (x, y) scaled to s px (same style as the skin's icons)."""
    return ('<g transform="translate(%g %g) scale(%g)" fill="none" stroke="%s" stroke-width="%g" '
            'stroke-linecap="round" stroke-linejoin="round">%s</g>') % (x, y, s / 24.0, colour, width, d)

DOWN = '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M4 20h16"/>'
CHECK = '<path d="M4 12.5l5 5L20 6.5"/>'
REFRESH = '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>'

W, H = 270, 110
body = []
# background: flat near-black with a slightly lighter panel sheen at the top, and a 1 px edge so the tile
# separates from the browser's own dark grey
body.append('<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#1b1c1f"/><stop offset="1" stop-color="%s"/></linearGradient></defs>' % BG)
body.append('<rect width="%d" height="%d" fill="url(#g)"/>' % (W, H))
body.append('<rect x="0.5" y="0.5" width="%d" height="%d" fill="none" stroke="#2e3034"/>' % (W - 1, H - 1))

# --- left: the catalog's mark (a red dot with a soft halo) + vendor, then the wordmark ---
body.append('<circle cx="21" cy="22" r="9" fill="%s" fill-opacity="0.22"/><circle cx="21" cy="22" r="6" fill="%s"/>' % (RED, RED))
p, _ = text_path("OPEN MPC  G2", 38, 27, 13, MUTED, "SemiBold", spacing=0.6)
body.append(p)
p, w1 = text_path("PLUGIN", 13, 62, 29, INK, "Bold", spacing=0.5)
body.append(p)
p, w2 = text_path("MANAGER", 13, 91, 29, INK, "Bold", spacing=0.5)
body.append(p)
# red underline accent, like the progress bar
body.append(rr(14, 96, 40, 3, 1.5, RED))

# --- right: three list rows (the app's plugin cards) with their status pills ---
rx, rw, rh, gap = 160, 100, 24, 5
rows = [("off", "check"), ("on", "down"), ("off", "update")]
ry0 = 14
for i, (state, pill) in enumerate(rows):
    y = ry0 + i * (rh + gap)
    on = state == "on"
    body.append(rr(rx + 0.5, y + 0.5, rw - 1, rh - 1, 5, CARD_ON if on else CARD_OFF, RED if on else CARD_EDGE, 1.2 if on else 1))
    # thumbnail square
    body.append(rr(rx + 5, y + 5, 14, 14, 3, THUMB, THUMB_EDGE, 1))
    # two text lines
    body.append(rr(rx + 24, y + 7, 34 if i != 1 else 40, 3.5, 1.75, INK if on else MUTED))
    body.append(rr(rx + 24, y + 14, 22, 3, 1.5, "#4a4c52"))
    # status pill at the right of the row
    px, pw, ph = rx + rw - 31, 26, 14
    py = y + (rh - ph) / 2
    if pill == "check":      # installed: outlined pill, green tick
        body.append(rr(px + 0.5, py + 0.5, pw - 1, ph - 1, 4, "none", "#2f5e46", 1))
        body.append(stroke_icon(CHECK, px + 7.5, py + 1.5, 11, GREEN, 3))
    elif pill == "down":     # install: the red button
        body.append(rr(px, py, pw, ph, 4, RED))
        body.append(stroke_icon(DOWN, px + 7.5, py + 1.5, 11, "#ffffff", 3))
    else:                    # update available: amber button
        body.append(rr(px, py, pw, ph, 4, AMBER))
        body.append(stroke_icon(REFRESH, px + 7.5, py + 1.5, 11, "#1a1205", 3))

svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">\n'
       '<!-- Plugin Manager browser tile. Type: Titillium Web Bold/SemiBold (SIL OFL 1.1), converted to outlines. -->\n'
       '%s\n</svg>\n') % (W, H, W, H, "\n".join(body))
open(OUT, "w").write(svg)
print("wrote", OUT, "wordmark widths", round(w1, 1), round(w2, 1))
