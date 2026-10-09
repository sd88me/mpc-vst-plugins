#!/usr/bin/env python3
"""html_art: skin artwork drawn by a browser (headless Chromium), as an alternative to shadow_art.c.

Reads the same commands as shadow_art.c on stdin (see its header; shadow_skin.py writes them) and writes the
same PPM files, so the layout, the skin builder and the skin format don't change: only how things look.
Each drawing becomes SVG styled by CSS (tools/html_art/default.css, then the layout's own `art_css=` file),
so a port can use any font, knob style, gradient or shadow. Geometry comes from the commands as before.

Extra commands, which only this renderer has (looks and images: tools/skin_assets.py; LOOK is its JSON):
  svg|file.svg|x|y|w|h                 draw an SVG drawing into that box (a layout's `art file=...` line)
  image|file|x|y|w|h|fit               draw an image file into that box (fit: contain, cover or stretch)
  iframe|x|y|w|h|title|file            a frame drawn as a panel picture (stretched), its title on top
  lstrip|out|r|frames|LOOK             a knob filmstrip with a look (built-in, turning image, or a filmstrip)
  lsstrip|out|w|h|frames|vert|LOOK     a slider filmstrip with a look
  ltog|x|y|on|w|h|LOOK                 a toggle with a look;  lbtn|x|y|w|h|on|label|LOOK   a button
  lseg|x|y|w|h|on|ink|label|LOOK       an option segment over an image
  limg|path|w|h|fit                    one alpha-preserving image, at (0,0)..(w,h) (an EXPERIMENTAL native
                                        Meter's inactiveImage/peakImage/rmsImage; shadow_skin.py crops it per use)

Controls (knob and slider strips, toggles, buttons, option segments, tiles: a canvas holding just one of them)
come out with a transparent background, so they sit on any artwork; they are written as RGBA PNG data under the
.ppm name the command gave (Pillow, which converts them, reads either). Backgrounds stay opaque.

Runs where Playwright's Chromium is (tools/html_art/Dockerfile). Select it with vst.json "art": "html"
(tools/build_port.sh), or SHADOW_ART=tools/html_art.py for gen_vst.py.
"""
import io
import math
import os
import re
import sys
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shadow_skin  # noqa: E402  (button sizes must match the skin builder's own)
import skin_assets  # noqa: E402

W, H = 1280, 800
# theme_<key> -> CSS variable --<key with dashes>; defaults are render_conf_preview.c's
THEME = {"bg": "131211", "panel": "1c1a17", "line": "2a2823", "ink": "efe9d8", "ink_dim": "8f8878",
         "ink_faint": "5c584c", "accent": "c1552f", "accent_hi": "e2793f", "knob_face": "efe9d8",
         "knob_ring": "2a2823", "knob_dot": "c1552f", "lcd": "1a120d", "seg_active": "f2f1ee",
         "seg_inactive": "050403", "seg_active_tx": "1c1a17", "box": "1f1f1f", "btn_bg": "e8341c",
         "btn_text": "050403", "btn_text_plain": "fdf3ea", "display_bg": "1c2612", "display_cell": "24301a",
         "display_ink": "cdeb63", "display_off": "2c3a1d", "display_bezel": "0d1108"}
DEFS = """<defs>
<linearGradient id="sheen-linear" x1="0" y1="0" x2="0" y2="1">
 <stop offset="0" stop-color="#fff" style="stop-opacity:var(--sheen)"/><stop offset="0.55" stop-color="#fff" stop-opacity="0"/>
</linearGradient>
<radialGradient id="sheen-radial" cx="0.35" cy="0.3" r="0.8">
 <stop offset="0" stop-color="#fff" style="stop-opacity:calc(var(--sheen) * 2.5)"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
</radialGradient>
<radialGradient id="metal-radial" cx="0.4" cy="0.35" r="0.75">
 <stop offset="0" stop-color="#f6f6f4"/><stop offset="0.55" stop-color="#b9b9b6"/><stop offset="1" stop-color="#6c6c69"/>
</radialGradient>
<linearGradient id="metal-linear" x1="0" y1="0" x2="1" y2="1">
 <stop offset="0" stop-color="#e8e8e6"/><stop offset="0.5" stop-color="#8e8e8b"/><stop offset="1" stop-color="#d6d6d3"/>
</linearGradient>
<filter id="grain" x="0" y="0" width="100%" height="100%">
 <feTurbulence type="fractalNoise" baseFrequency="0.85 0.55" numOctaves="3" seed="7" result="n"/>
 <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0.5 0.5 0 0 -0.42" result="speck"/>
 <feComposite in="speck" in2="SourceGraphic" operator="in" result="s2"/>
 <feTurbulence type="fractalNoise" baseFrequency="0.012 0.03" numOctaves="2" seed="3" result="b"/>
 <feColorMatrix in="b" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.16 -0.04" result="wear"/>
 <feComposite in="wear" in2="SourceGraphic" operator="in" result="w2"/>
 <feMerge><feMergeNode in="SourceGraphic"/><feMergeNode in="w2"/><feMergeNode in="s2"/></feMerge>
</filter>
<linearGradient id="key-linear" x1="0" y1="0" x2="0" y2="1">
 <stop offset="0" stop-color="#ff6a50"/><stop offset="0.08" stop-color="#f04a30"/><stop offset="0.6" stop-color="#d82c14"/><stop offset="1" stop-color="#a81a08"/>
</linearGradient>
<linearGradient id="key-gloss" x1="0" y1="0" x2="0" y2="1">
 <stop offset="0" stop-color="#fff" stop-opacity="0.35"/><stop offset="0.45" stop-color="#fff" stop-opacity="0.06"/><stop offset="0.5" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.18"/>
</linearGradient>
<linearGradient id="chrome-linear" x1="0" y1="0" x2="0" y2="1">
 <stop offset="0" stop-color="#f4f6f8"/><stop offset="0.42" stop-color="#9aa0a8"/><stop offset="0.5" stop-color="#2a2d33"/><stop offset="0.62" stop-color="#6c727a"/><stop offset="1" stop-color="#eceef0"/>
</linearGradient>
<radialGradient id="bake-radial" cx="0.38" cy="0.32" r="0.8">
 <stop offset="0" stop-color="#7a4a2e"/><stop offset="0.4" stop-color="#3a1e10"/><stop offset="1" stop-color="#140803"/>
</radialGradient>
<radialGradient id="dome-radial" cx="0.38" cy="0.32" r="0.8">
 <stop offset="0" stop-color="#6a6c70"/><stop offset="0.35" stop-color="#2c2d30"/><stop offset="1" stop-color="#050506"/>
</radialGradient>
<linearGradient id="rim-linear" x1="0.2" y1="0" x2="0.8" y2="1">
 <stop offset="0" stop-color="#d8dadd"/><stop offset="0.45" stop-color="#3a3b3e"/><stop offset="1" stop-color="#9a9ca0"/>
</linearGradient>
</defs>"""


# ---- built-in looks (skin_assets.LOOKS). Parts carry look-* classes, coloured in default.css, so a stylesheet can
# recolour them. a = the knob's angle in degrees (0 = up); what turns sits in a rotated group.

def _turn(a, cx, cy, body):
    return '<g transform="rotate(%.2f %g %g)">%s</g>' % (a, cx, cy, body)


def knob_moog(cx, cy, r, a):
    """Black knob with a knurled skirt, a white line and a metal cap (the 1970s synth knob)."""
    R = r + 3
    n = max(24, int(R * 1.2))
    dash = 2 * math.pi * (R - 2) / n / 2
    return ('<circle class="look-skirt" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            _turn(a, cx, cy, '<circle class="look-knurl" cx="%g" cy="%g" r="%g" style="stroke-width:3.5;stroke-dasharray:%.2f %.2f"/>'
                  % (cx, cy, R - 2, dash, dash)) +
            '<circle class="look-body" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.84) +
            _turn(a, cx, cy, '<line class="look-line" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.55, cx, cy - R * 0.8, max(2, r / 11))) +
            '<circle class="look-cap" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.5) +
            '<circle class="knob-sheen" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.84))


def knob_chicken(cx, cy, r, a):
    """A pointed chicken-head knob over a round base."""
    R = r + 3
    head = ('<path class="look-head" d="M0,-0.98 C0.12,-0.98 0.44,0.02 0.44,0.3 A0.44,0.44 0 0 1 -0.44,0.3 '
            'C-0.44,0.02 -0.12,-0.98 0,-0.98 Z"/><path class="look-line" d="M0,-0.86 L0,-0.32" style="stroke-width:0.07"/>'
            '<circle class="knob-sheen" cx="0" cy="0.25" r="0.4"/>')
    return ('<circle class="look-base" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.9) +
            '<g transform="translate(%g %g) rotate(%.2f) scale(%g)">%s</g>' % (cx, cy, a, R, head))


def knob_metal(cx, cy, r, a):
    """Brushed aluminium with a notch."""
    R = r + 3
    return ('<circle class="look-metal" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            '<circle class="look-metal-top" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.82) +
            _turn(a, cx, cy, '<line class="look-notch" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.3, cx, cy - R * 0.76, max(2, r / 10))) +
            '<circle class="knob-sheen" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.82))


def knob_cap(cx, cy, r, a):
    """A coloured cap on a dark ring (the theme's knob_dot and knob_ring)."""
    R = r + 2
    return ('<circle class="look-cap-ring" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            '<circle class="look-cap-top" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.8) +
            '<circle class="knob-sheen" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.8) +
            _turn(a, cx, cy, '<line class="look-line" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.25, cx, cy - R * 0.7, max(2, r / 10))))


def knob_prophet(cx, cy, r, a):
    """A ribbed black skirt, a silver ring and a black brushed top with a white pointer, seen from above (the Prophet '08 knob).
    Drawn a little inside r so a value arc (class knob-arc, drawn by knob_frame) sits outside it."""
    R = r - 0.5
    n = 34
    dash = 2 * math.pi * (R - 1.8) / n / 2
    brush = "".join('<line x1="%g" y1="%g" x2="%g" y2="%g"/>' % (
        cx + R * 0.1 * math.sin(k * math.pi / 14), cy - R * 0.1 * math.cos(k * math.pi / 14),
        cx + R * 0.7 * math.sin(k * math.pi / 14), cy - R * 0.7 * math.cos(k * math.pi / 14)) for k in range(28))
    return ('<circle class="look-pshadow" cx="%g" cy="%g" r="%g"/>' % (cx, cy + 1.5, R) +
            '<circle class="look-pskirt" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            _turn(a, cx, cy, '<circle class="look-prib" cx="%g" cy="%g" r="%g" style="stroke-width:3.6;stroke-dasharray:%.2f %.2f"/>'
                  % (cx, cy, R - 1.8, dash, dash)) +
            '<circle class="look-pring" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.83) +
            '<circle class="look-pbevel" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.72) +
            '<circle class="look-ptop" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.68) +
            _turn(a, cx, cy, '<g class="look-pbrush">%s</g>' % brush) +
            _turn(a, cx, cy, '<line class="look-pline" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.1, cx, cy - R * 0.66, max(2.0, r / 10))) +
            '<ellipse class="knob-sheen look-psheen" cx="%g" cy="%g" rx="%g" ry="%g"/>' % (cx - R * 0.18, cy - R * 0.3, R * 0.45, R * 0.28))


def _rim_dashes(cx, cy, R, n, a, cls, sw):
    dash = 2 * math.pi * R / n / 2
    return _turn(a, cx, cy, '<circle class="%s" cx="%g" cy="%g" r="%g" style="stroke-width:%g;stroke-dasharray:%.2f %.2f"/>' % (cls, cx, cy, R, sw, dash, dash))


def _spec(cx, cy, R, dx, dy, rx, ry, rot=True):
    return '<ellipse class="look-hspec" cx="%g" cy="%g" rx="%g" ry="%g"%s/>' % (
        cx + R * dx, cy + R * dy, R * rx, R * ry, ' transform="rotate(-30 %g %g)"' % (cx + R * dx, cy + R * dy) if rot else "")


def _hshadow(cx, cy, R, k=0.06):
    return '<ellipse class="look-hshadow" cx="%g" cy="%g" rx="%g" ry="%g"/>' % (cx + R * k, cy + R * 0.2, R * 1.02, R)


def knob_hardware(cx, cy, r, a):
    """A glossy black hardware knob: a ring of engraved scale ticks, a ribbed skirt, a domed top with a specular highlight and a
    contact shadow, and a tapered white pointer (the MM-303 / TB-303 look). The ticks sit outside the knob and don't turn."""
    R = r * 0.84
    ticks = ""
    for k in range(31):
        th = math.radians(-135 + 270 * k / 30)
        r0, r1 = r * 0.93, r * (1.06 if k % 5 == 0 else 1.0)
        ticks += '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>' % (
            cx + r0 * math.sin(th), cy - r0 * math.cos(th), cx + r1 * math.sin(th), cy - r1 * math.cos(th))
    return ('<g class="look-hticks">%s</g>' % ticks + _hshadow(cx, cy, R, 0.08) +
            '<circle class="look-hskirt" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            _rim_dashes(cx, cy, R - 1.5, 40, a, "look-hrib", 3) +
            '<circle class="look-hrim" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.86) +
            '<circle class="look-hdome" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.8) +
            _turn(a, cx, cy, '<path class="look-hpointer" d="M%g,%g L%g,%g L%g,%g Z"/>' % (
                cx - R * 0.07, cy - R * 0.12, cx, cy - R * 0.78, cx + R * 0.07, cy - R * 0.12)) +
            _spec(cx, cy, R, -0.28, -0.38, 0.3, 0.14) +
            '<circle class="look-hglint" cx="%g" cy="%g" r="%g"/>' % (cx + R * 0.34, cy + R * 0.4, R * 0.1))


def knob_chrome(cx, cy, r, a):
    """A polished chrome dome: a mirror horizon band across the top, a bright rim, a dark engraved pointer."""
    R = r * 0.86
    return (_hshadow(cx, cy, R) +
            '<circle class="look-crim" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            '<circle class="look-cdome" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.86) +
            _turn(a, cx, cy, '<line class="look-cline" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.1, cx, cy - R * 0.8, max(2.2, r / 9))) +
            _spec(cx, cy, R, -0.12, -0.5, 0.4, 0.12, False))


def knob_bakelite(cx, cy, r, a):
    """Vintage glossy brown-black bakelite with a ribbed skirt and a cream pointer line."""
    R = r * 0.86
    return (_hshadow(cx, cy, R) +
            '<circle class="look-bskirt" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            _rim_dashes(cx, cy, R - 1.5, 36, a, "look-brib", 3) +
            '<circle class="look-btop" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.78) +
            _turn(a, cx, cy, '<line class="look-bline" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.18, cx, cy - R * 0.74, max(2.2, r / 9))) +
            _spec(cx, cy, R, -0.3, -0.4, 0.28, 0.12))


def knob_davies(cx, cy, r, a):
    """A stepped Davies-style knob: a wide skirt, a smaller raised cap, and a bright pointer running from the cap to the rim."""
    R = r * 0.9
    return (_hshadow(cx, cy, R) +
            '<circle class="look-dskirt" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            '<circle class="look-dstep" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.66) +
            '<circle class="look-dcap" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.6) +
            _turn(a, cx, cy, '<line class="look-dline" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.62, cx, cy - R * 0.97, max(3, r / 7))) +
            _spec(cx, cy, R, -0.2, -0.28, 0.22, 0.1))


def knob_rubber(cx, cy, r, a):
    """A matte soft-touch rubber knob with a grip ring and a coloured dot (the theme's knob_dot) by the rim."""
    R = r * 0.88
    return (_hshadow(cx, cy, R, 0.05) +
            '<circle class="look-rbody" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            _rim_dashes(cx, cy, R - 2.5, 28, a, "look-rgrip", 4) +
            '<circle class="look-rtop" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R * 0.74) +
            _turn(a, cx, cy, '<circle class="look-rdot" cx="%g" cy="%g" r="%g"/>' % (cx, cy - R * 0.55, max(2.4, r / 9))))


def knob_ledring(cx, cy, r, a):
    """A matte dark knob inside a ring of 21 LEDs that light up to the pointer (the theme's accent colour)."""
    R = r * 0.66
    leds = ""
    for k in range(21):
        ang = -135 + 270 * k / 20
        th = math.radians(ang)
        x, y = cx + r * 0.88 * math.sin(th), cy - r * 0.88 * math.cos(th)
        leds += '<circle class="look-led%s" cx="%.2f" cy="%.2f" r="%g"/>' % ("-on" if ang <= a + 0.01 else "-off", x, y, max(1.8, r / 14))
    return (leds + _hshadow(cx, cy, R, 0.05) +
            '<circle class="look-lbody" cx="%g" cy="%g" r="%g"/>' % (cx, cy, R) +
            _turn(a, cx, cy, '<line class="look-lline" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:%g"/>'
                  % (cx, cy - R * 0.3, cx, cy - R * 0.85, max(2.2, r / 10))) +
            _spec(cx, cy, R, -0.25, -0.4, 0.3, 0.12, False))


KNOB_LOOKS = {"moog": knob_moog, "chicken": knob_chicken, "metal": knob_metal, "cap": knob_cap, "prophet": knob_prophet,
              "hardware": knob_hardware, "chrome": knob_chrome,
              "bakelite": knob_bakelite, "davies": knob_davies, "rubber": knob_rubber, "ledring": knob_ledring}
ARC_LOOKS = ("prophet",)     # looks that keep the value arc round the knob (the theme's knob-track / knob-arc)


def fader_track(x, y, w, h, vert, th):
    """A mixer fader's slot with a tick scale (th: the cap's length along the travel)."""
    o = ""
    if vert:
        o += '<rect class="look-slot" x="%g" y="%g" width="6" height="%g" rx="3"/>' % (x + w / 2 - 3, y + 4, h - 8)
        for k in range(11):
            ty = y + th / 2 + k * (h - th) / 10
            o += '<line class="look-tick" x1="%g" y1="%g" x2="%g" y2="%g"/><line class="look-tick" x1="%g" y1="%g" x2="%g" y2="%g"/>' % (
                x + 1, ty, x + w / 2 - 7, ty, x + w / 2 + 7, ty, x + w - 1, ty)
    else:
        o += '<rect class="look-slot" x="%g" y="%g" width="%g" height="6" rx="3"/>' % (x + 4, y + h / 2 - 3, w - 8)
        for k in range(11):
            tx = x + th / 2 + k * (w - th) / 10
            o += '<line class="look-tick" x1="%g" y1="%g" x2="%g" y2="%g"/><line class="look-tick" x1="%g" y1="%g" x2="%g" y2="%g"/>' % (
                tx, y + 1, tx, y + h / 2 - 7, tx, y + h / 2 + 7, tx, y + h - 1)
    return o


def fader_cap(x, y, w, h, vert):
    """A fader cap filling the box x,y,w,h, with grip ridges and a centre line."""
    o = '<rect class="look-fader" x="%g" y="%g" width="%g" height="%g" rx="3"/>' % (x, y, w, h)
    if vert:
        for f in (0.25, 0.75):
            o += '<line class="look-ridge" x1="%g" y1="%g" x2="%g" y2="%g"/>' % (x + 3, y + h * f, x + w - 3, y + h * f)
        o += '<line class="look-line" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:2"/>' % (x + 2, y + h / 2, x + w - 2, y + h / 2)
    else:
        for f in (0.25, 0.75):
            o += '<line class="look-ridge" x1="%g" y1="%g" x2="%g" y2="%g"/>' % (x + w * f, y + 3, x + w * f, y + h - 3)
        o += '<line class="look-line" x1="%g" y1="%g" x2="%g" y2="%g" style="stroke-width:2"/>' % (x + w / 2, y + 2, x + w / 2, y + h - 2)
    return o


def hexc(s):
    return "#" + s.strip().lstrip("#")


def scope_svg(src, prefix):
    """An SVG inlined into the page shares one document with every other one, so its ids (gradients, clip paths,
    filters) and the class names its <style> defines would collide with another image's. Prefix both."""
    ids = set(re.findall(r'\sid="([^"]+)"', src))
    if ids:
        ref = lambda m: m.group(1) + (prefix + "-" + m.group(2) if m.group(2) in ids else m.group(2)) + m.group(3)
        src = re.sub(r'(\sid=")([^"]+)(")', ref, src)
        src = re.sub(r'(url\(\s*[\'"]?#)([^)\'"\s]+)([\'"]?\s*\))', ref, src)
        src = re.sub(r'(href="#)([^"]+)(")', ref, src)
    if "<style" in src:
        classes = set(c for v in re.findall(r'\sclass="([^"]*)"', src) for c in v.split())
        if classes:
            src = re.sub(r'(\sclass=")([^"]*)(")',
                         lambda m: m.group(1) + " ".join(prefix + "-" + c for c in m.group(2).split()) + m.group(3), src)
            src = re.sub(r"(<style[^>]*>)(.*?)(</style>)", lambda m: m.group(1) + re.sub(
                r"\.(-?[_a-zA-Z][\w-]*)(?![\w-])",
                lambda c: "." + (prefix + "-" + c.group(1) if c.group(1) in classes else c.group(1)), m.group(2))
                + m.group(3), src, flags=re.S)
    return src


class Art:
    def __init__(self, href=None):
        self.href = href         # the editor's path -> URL; None: the renderer inlines each image once (page defs)
        self.images = {}         # image path -> its id in the page's defs (renderer)
        self.theme = dict(THEME)
        self.td3 = False
        self.css = []            # the port's own stylesheet(s)
        self.ops = []            # SVG for the current canvas
        self.kinds = []          # the command behind each op, to tell a lone control from a background
        self.jobs = []           # ("crop", svg, path, x, y, w, h) | ("strip", ...) | ("sstrip", ...)

    # ---- commands ----
    def load_theme(self, path):
        self.theme_lines([l.strip() for l in open(path) if l.strip() and not l.strip().startswith("#")])

    def theme_lines(self, lines):
        shadow_skin.apply_theme(lines)   # font_label= sizes buttons, exactly as the skin builder does
        for l in lines:
            k, _, v = l.partition("=")
            if k == "style":
                self.td3 = v.strip() == "td3"
            elif k.startswith("theme_") and k[6:] in self.theme:
                self.theme[k[6:]] = v.strip()
            elif k == "art_css":
                self.css.append(v.strip())

    def text(self, x, y, s, cls, anchor="middle", extra=""):
        return '<text class="%s" x="%g" y="%g" text-anchor="%s" dominant-baseline="central"%s>%s</text>' % (
            cls, x, y, anchor, extra, escape(s))

    def frame(self, x, y, w, h, title):
        if self.td3:
            o = '<rect class="frame-border" x="%d" y="%d" width="%d" height="%d" rx="10"/>' % (x + 1, y + 1, w - 2, h - 2)
            o += '<line class="frame-rule" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (x + 18, y + 38.5, x + w - 18, y + 38.5)
        else:
            o = '<rect class="frame-border" x="%g" y="%g" width="%d" height="%d"/>' % (x + 0.5, y + 0.5, w - 1, h - 1)
            o += '<line class="frame-rule" x1="%d" y1="%g" x2="%d" y2="%g"/>' % (x + 18, y + 36.5, x + w - 18, y + 36.5)
        if title:
            o += self.text(x + 18, y + 20, title, "frame-title", "start")
        self.ops.append(o)

    def knob_arc(self, cx, cy, r, pct):
        R = r + 2.5
        a0, a1 = -135.0, -135.0 + 270.0 * pct / 100.0
        pt = lambda a, rad: (cx + rad * math.sin(math.radians(a)), cy - rad * math.cos(math.radians(a)))
        sx, sy = pt(a0, R)
        ex, ey = pt(135.0, R)
        o = '<path class="knob-track" style="stroke-width:%g" d="M%.2f %.2f A%g %g 0 1 1 %.2f %.2f"/>' % (
            max(2, r / 10), sx, sy, R, R, ex, ey)
        if pct > 0:
            vx, vy = pt(a1, R)
            o += '<path class="knob-arc" style="stroke-width:%g" d="M%.2f %.2f A%g %g 0 %d 1 %.2f %.2f"/>' % (
                max(2, r / 10), sx, sy, R, R, 1 if a1 - a0 > 180 else 0, vx, vy)
        return o

    def knob_svg(self, cx, cy, r, pct):
        R = r + 2.5
        a0, a1 = -135.0, -135.0 + 270.0 * pct / 100.0
        pt = lambda a, rad: (cx + rad * math.sin(math.radians(a)), cy - rad * math.cos(math.radians(a)))
        o = self.knob_arc(cx, cy, r, pct)
        o += '<circle class="knob-face" cx="%g" cy="%g" r="%g"/>' % (cx, cy, r - 2)
        o += '<circle class="knob-sheen" cx="%g" cy="%g" r="%g"/>' % (cx, cy, r - 2)
        px0, py0 = pt(a1, r * 0.3)
        px1, py1 = pt(a1, r * 0.75)
        o += '<line class="knob-pointer" style="stroke-width:%g" x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>' % (
            max(2, r / 9), px0, py0, px1, py1)
        return '<g class="knob">%s</g>' % o

    def slider_svg(self, x, y, w, h, vert, t):
        return "".join(self.slider_parts(x, y, w, h, vert, t))

    def slider_parts(self, x, y, w, h, vert, t):
        """The stock slider as (well and fill, thumb)."""
        o = '<rect class="slider-well" x="%d" y="%d" width="%d" height="%d" rx="%g"/>' % (x, y, w, h, (w if vert else h) / 2)
        pad = 4
        th = (w if vert else h) - 2 * pad
        if vert:
            ty = y + pad + round((1 - t) * (h - 2 * pad - th))
            o += '<rect class="slider-fill" x="%g" y="%d" width="6" height="%d" rx="3"/>' % (x + w / 2 - 3, ty + th // 2, max(0, y + h - pad - (ty + th // 2)))
            return o, '<circle class="slider-thumb" cx="%g" cy="%g" r="%g"/>' % (x + w / 2, ty + th / 2, th / 2)
        tx = x + pad + round(t * (w - 2 * pad - th))
        o += '<rect class="slider-fill" x="%d" y="%g" width="%d" height="6" rx="3"/>' % (x + pad, y + h / 2 - 3, max(0, tx + th // 2 - x - pad))
        return o, '<circle class="slider-thumb" cx="%g" cy="%g" r="%g"/>' % (tx + th / 2, y + h / 2, th / 2)

    # ---- images and looks ----
    def image(self, path, x, y, w, h, fit="contain", vb=None):
        """An image file drawn into the box x,y,w,h (fit: contain, cover or stretch); vb: a region of it (a
        filmstrip frame). The renderer puts each file in the page once (a data: URI) and uses it by reference."""
        iw, ih = skin_assets.image_size(path)
        if not iw or not ih or w <= 0 or h <= 0:
            return ""
        if self.href:
            inner = '<image href="%s" width="%d" height="%d" preserveAspectRatio="none"/>' % (escape(self.href(path)), iw, ih)
        else:
            self.images.setdefault(path, "img%d" % len(self.images))
            inner = '<use href="#%s"/>' % self.images[path]
        par = {"cover": "xMidYMid slice", "stretch": "none"}.get(fit, "xMidYMid meet")
        return '<svg x="%g" y="%g" width="%g" height="%g" viewBox="%s" preserveAspectRatio="%s" overflow="hidden">%s</svg>' % (
            x, y, w, h, vb or "0 0 %d %d" % (iw, ih), par, inner)

    def strip_frame(self, path, x, y, w, h, t, frames=None, aspect=1.0):
        """The frame of a filmstrip for value t (0..1), drawn into the box."""
        iw, ih, n, down = skin_assets.strip_layout(path, frames, aspect)
        i = min(n - 1, max(0, round(t * (n - 1))))
        vb = "0 %g %g %g" % (i * ih / n, iw, ih / n) if down else "%g 0 %g %g" % (i * iw / n, iw / n, ih)
        return self.image(path, x, y, w, h, "contain", vb)

    def lit(self, look, on, x, y, w, h, fit="contain"):
        """An on/off image: img off, img_on on (or img brightened)."""
        if on and look.get("img_on"):
            return self.image(look["img_on"], x, y, w, h, fit)
        o = self.image(look["img"], x, y, w, h, fit)
        return '<g class="look-lit">%s</g>' % o if on else o

    def knob_frame(self, cx, cy, r, pct, look):
        """One knob position (pct 0..100): the stock drawing, a built-in look, a turning image over a still base,
        or a filmstrip frame, all in the same 2r+8 box."""
        if not look:
            return self.knob_svg(cx, cy, r, pct)
        a = -135.0 + 270.0 * pct / 100.0
        b = (cx - r - 4, cy - r - 4, 2 * r + 8, 2 * r + 8)
        if look.get("strip"):
            o = self.strip_frame(look["strip"], *b, pct / 100.0, look.get("frames"))
        else:
            o = self.image(look["base"], *b) if look.get("base") else ""
            if look.get("img"):
                o += _turn(a, cx, cy, self.image(look["img"], *b))
            elif look.get("look") in KNOB_LOOKS:
                if look["look"] in ARC_LOOKS:
                    o += self.knob_arc(cx, cy, r, pct)
                o += KNOB_LOOKS[look["look"]](cx, cy, r, a)
        return '<g class="knob look-%s">%s</g>' % (look.get("look", "image"), o)

    def slider_frame(self, x, y, w, h, vert, t, look):
        """One slider position (t 0..1) with a look: track (base image, fader slot or stock) and thumb."""
        if not look:
            return self.slider_svg(x, y, w, h, vert, t)
        if look.get("strip"):
            return self.strip_frame(look["strip"], x, y, w, h, t, look.get("frames"), h / max(1, w))
        fader = look.get("look") == "fader"
        track, thumb = self.slider_parts(x, y, w, h, vert, t)
        if look.get("img"):
            iw, ih = skin_assets.image_size(look["img"])
            if vert:
                tw, th = w, min(h / 2, w * ih / max(1, iw))
            else:
                tw, th = min(w / 2, h * iw / max(1, ih)), h
        elif fader:
            tw, th = (w, max(14, min(w * 0.55, h / 4))) if vert else (max(14, min(h * 0.55, w / 4)), h)
        else:
            tw = th = 0
        tx, ty = (x, y + (1 - t) * (h - th)) if vert else (x + t * (w - tw), y)
        if look.get("base"):
            track = self.image(look["base"], x, y, w, h, "stretch")
        elif fader:
            track = fader_track(x, y, w, h, vert, th if vert else tw)
        if look.get("img"):
            thumb = self.image(look["img"], tx, ty, tw, th)
        elif fader:
            thumb = fader_cap(tx, ty, tw, th, vert)
        return '<g class="slider look-%s">%s%s</g>' % (look.get("look", "image"), track, thumb)

    def toggle_frame(self, cx, cy, on, w, h, look):
        """A toggle with a look, centred on cx,cy in a w x h box."""
        x, y = cx - w / 2, cy - h / 2
        name = look.get("look", "image")
        if look.get("img"):
            o = self.lit(look, on, x, y, w, h)
        elif name == "led":
            r = min(w, h) / 2 - 3
            o = ('<circle class="look-led-bezel" cx="%g" cy="%g" r="%g"/><circle class="look-led" cx="%g" cy="%g" r="%g"/>'
                 '<circle class="look-led-glint" cx="%g" cy="%g" r="%g"/>') % (cx, cy, r + 2, cx, cy, r, cx - r * 0.35, cy - r * 0.35, r * 0.3)
        else:   # switch: a bat lever, up for on
            nut = min(w, h * 0.6) / 2
            tip = y + w * 0.2 if on else y + h - w * 0.2
            o = ('<circle class="look-nut" cx="%g" cy="%g" r="%g"/>'
                 '<path class="look-bat" d="M%g %g L%g %g L%g %g L%g %g Z"/><circle class="look-bat-tip" cx="%g" cy="%g" r="%g"/>') % (
                cx, cy, nut, cx - w * 0.11, cy, cx + w * 0.11, cy, cx + w * 0.06, tip, cx - w * 0.06, tip, cx, tip, w * 0.17)
        return '<g class="toggle look-%s%s">%s</g>' % (name, " on" if on else "", o)

    def button_frame(self, x, y, w, h, on, label, look):
        """A button drawn from its on/off images, the label on top."""
        o = self.lit(look, on, x, y, w, h, "stretch")
        if label:
            o += self.text(x + w / 2, y + h / 2, label, "button-tx")
        return '<g class="button look-image%s">%s</g>' % (" on" if on else "", o)

    def seg_frame(self, x, y, w, h, on, ink, label, look):
        """An option segment drawn from its on/off images, the option's name on top."""
        o = self.lit(look, on, x, y, w, h, "stretch") + self.text(x + w / 2, y + h / 2, label, "seg-tx")
        return '<g class="seg look-image%s" style="--ink:%s">%s</g>' % (" on" if on else "", hexc(ink), o)

    def box_label(self, x0, y0, label, align="left", w=0):
        if not label:
            return ""
        if align == "center":
            return self.text(x0 + w / 2, y0 - 15, label, "box-label", "middle")
        return self.text(x0, y0 - 15, label, "box-label", "start")

    def arrow(self, cx, cy, size, d, cls):
        b = cx - d * size
        return '<path class="%s" d="M%d %d L%d %d L%d %d Z"/>' % (cls, b, cy - size, b, cy + size, cx, cy)

    def dot_cell(self, x, y, w, h):
        p = 4
        gcols, grows = (w - 8) // p, (h - 6) // p
        gx, gy = x + (w - gcols * p) // 2, y + (h - grows * p) // 2 + 1
        pid = "dots%d_%d" % (len(self.ops), len(self.jobs))
        return ('<rect class="dot-cell" x="%d" y="%d" width="%d" height="%d" rx="5"/>'
                '<pattern id="%s" x="%d" y="%d" width="%d" height="%d" patternUnits="userSpaceOnUse">'
                '<rect width="%d" height="%d" style="fill:var(--display-off)"/></pattern>'
                '<rect x="%d" y="%d" width="%d" height="%d" fill="url(#%s)"/>') % (
            x, y, w, h, pid, gx, gy, p, p, p - 2, p - 2, gx, gy, gcols * p, grows * p, pid)

    def svg_file(self, path, x, y, w, h):
        src = open(path, encoding="utf-8").read()
        m = re.search(r"<svg\b[^>]*>", src)
        end = src.rfind("</svg>")
        if not m or end < 0:
            raise SystemExit("html_art: %s is not an SVG file" % path)
        vb = re.search(r'viewBox="([^"]+)"', m.group(0))
        vb = vb.group(1) if vb else "0 0 %d %d" % (w, h)
        self.ops.append('<svg x="%d" y="%d" width="%d" height="%d" viewBox="%s" overflow="hidden">%s</svg>' % (
            x, y, w, h, vb, src[m.end():end]))

    def run(self, line):
        a = line.split("|")
        op, n = a[0], len(a)
        if op not in ("theme", "crop", "strip", "sstrip"):
            self.kinds.append(op)
        I = lambda k: int(a[k])
        if op == "clear" and n == 2:
            self.ops = ['<rect x="0" y="0" width="%d" height="%d" fill="%s"/>' % (W, H, hexc(a[1]))]
            self.kinds = ["clear"]
        elif op == "theme" and n == 2:
            self.load_theme(a[1])
        elif op == "frame" and n == 6:
            self.frame(I(1), I(2), I(3), I(4), "" if a[5] == "-" else a[5])
        elif op == "frameblank" and n == 5:
            self.frame(I(1), I(2), I(3), I(4), "")
        elif op == "text" and n == 6:
            sc = float(a[3])
            self.ops.append(self.text(I(1), I(2) + 4.5 * sc, a[5], "text", extra=' style="fill:%s"' % hexc(a[4])))
        elif op == "htext" and n >= 13:
            # htext|cx|cy|size|color|anchor|weight|spacing|case|opacity|italic|font|text
            sc = float(a[3])
            st = "fill:%s;font-size:%gpx" % (hexc(a[4]), sc * 10)
            if a[6]: st += ";font-weight:%d" % int(float(a[6]))
            if a[7]: st += ";letter-spacing:%gpx" % float(a[7])
            if a[8] == "upper": st += ";text-transform:uppercase"
            elif a[8] == "none": st += ";text-transform:none"
            if a[9]: st += ";opacity:%g" % float(a[9])
            if a[10] == "1": st += ";font-style:italic"
            if a[11].startswith("@"):
                import base64, hashlib
                path = a[11][1:]
                fam = "ft" + hashlib.md5(path.encode()).hexdigest()[:8]
                mime = {".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}.get(os.path.splitext(path)[1].lower(), "font/ttf")
                b64 = base64.b64encode(open(path, "rb").read()).decode()
                self.ops.append('<defs><style>@font-face{font-family:"%s";src:url(data:%s;base64,%s)}</style></defs>' % (fam, mime, b64))
                st += ";font-family:'%s',var(--font)" % fam
            elif a[11].strip():
                fam = a[11].replace('"', "").replace("'", "").replace(";", "").replace("<", "").replace(">", "").strip()
                st += ";font-family:'%s',var(--font)" % fam
            self.ops.append(self.text(I(1), I(2), "|".join(a[12:]), "text", anchor=a[5], extra=' style="%s"' % st))
        elif op == "knob" and n == 5:
            self.ops.append(self.knob_svg(I(1), I(2), I(3), I(4)))
        elif op == "pill" and n == 4:
            cx, cy, on = I(1), I(2), I(3)
            lx = cx + 51 // 2 - 27 // 2 if on else cx - 51 // 2 + 27 // 2
            self.ops.append('<g class="pill%s"><rect class="pill-track" x="%g" y="%g" width="50" height="26" rx="13"/>'
                            '<circle class="pill-thumb" cx="%d" cy="%d" r="9.5"/></g>' % (
                                " on" if on else "", cx - 25, cy - 13, lx, cy))
        elif op == "button" and n == 5:
            cx, cy, col, lab = I(1), I(2), hexc(a[3]), a[4]
            bw, bh = shadow_skin.text_width(lab) + 36, 39
            if self.td3:
                bw, bh = bw + 28, 52
            x, y = cx - bw // 2, cy - bh // 2
            self.ops.append('<g class="button%s" style="--fill:%s">'
                            '<rect class="button-bg" x="%d" y="%d" width="%d" height="%d"/>'
                            '<rect class="button-sheen" x="%d" y="%d" width="%d" height="%d"/>%s</g>' % (
                                " td3" if self.td3 else "", col, x + 2, y + 2, bw - 4, bh - 4, x + 2, y + 2, bw - 4, bh - 4,
                                self.text(cx, cy, lab, "button-tx")))
        elif op == "seg" and n == 8:
            x, y, w, h = I(1), I(2), I(3), I(4)
            self.ops.append('<g class="seg" style="--fill:%s;--ink:%s"><rect class="seg-bg" x="%d" y="%d" width="%d" height="%d"/>'
                            '<rect class="seg-sheen" x="%d" y="%d" width="%d" height="%d"/>%s</g>' % (
                                hexc(a[5]), hexc(a[6]), x, y, w, h, x, y, w, h, self.text(x + w / 2, y + h / 2, a[7], "seg-tx")))
        elif op in ("readout", "stepper", "dotreadout", "dotstepper") and n in (6, 7):
            cx, cy, w, h = I(1), I(2), I(3), I(4)
            x0, y0 = cx - w // 2, cy - h // 2
            align = a[6] if n == 7 else "left"   # label_align=center on the layout line
            o = self.box_label(x0, y0, "" if a[5] == "-" else a[5], align, w)
            if op == "readout":
                o += '<rect class="box" x="%g" y="%g" width="%d" height="%d"/>' % (x0 + 0.5, y0 + 0.5, w - 1, h - 1)
            elif op == "stepper":
                bx, bw = x0 + h + 3, w - 2 * h - 6
                o += '<rect class="arrow-bg" x="%d" y="%d" width="%d" height="%d" rx="5"/>' % (x0, y0, h, h)
                o += '<rect class="arrow-bg" x="%d" y="%d" width="%d" height="%d" rx="5"/>' % (x0 + w - h, y0, h, h)
                o += self.arrow(x0 + h // 2, cy, h // 4, -1, "arrow") + self.arrow(x0 + w - h // 2, cy, h // 4, 1, "arrow")
                o += '<rect class="box" x="%g" y="%g" width="%d" height="%d"/>' % (bx + 0.5, y0 + 0.5, bw - 1, h - 1)
            else:
                o += '<rect class="dot-bezel" x="%d" y="%d" width="%d" height="%d" rx="8"/>' % (x0 - 4, y0 - 4, w + 8, h + 8)
                if op == "dotstepper":
                    o += '<rect class="dot-bezel" x="%d" y="%d" width="%d" height="%d" rx="5"/>' % (x0, y0, h, h)
                    o += '<rect class="dot-bezel" x="%d" y="%d" width="%d" height="%d" rx="5"/>' % (x0 + w - h, y0, h, h)
                    o += self.arrow(x0 + h // 2, cy, h // 4, -1, "dot-arrow") + self.arrow(x0 + w - h // 2, cy, h // 4, 1, "dot-arrow")
                    o += self.dot_cell(x0 + h + 3, y0, w - 2 * h - 6, h)
                else:
                    o += self.dot_cell(x0, y0, w, h)
            self.ops.append(o)
        elif op == "tile" and n == 8:
            x, y, w, h, bw = I(1), I(2), I(3), I(4), I(7)
            o = '<g style="--fill:%s;--border:%s"><rect class="tile" x="%d" y="%d" width="%d" height="%d"/>' % (
                hexc(a[5]), hexc(a[6]), x, y, w, h)
            if bw > 0:
                o += '<rect class="tile-border" style="stroke-width:%d" x="%g" y="%g" width="%g" height="%g"/>' % (
                    bw, x + bw / 2, y + bw / 2, w - bw, h - bw)
            else:
                o += '<rect class="tile-rule" x="%d" y="%d" width="%d" height="1"/><rect class="tile-rule" x="%d" y="%d" width="%d" height="1"/>' % (
                    x, y, w, x, y + h - 1, w)
            self.ops.append(o + "</g>")
        elif op == "svg" and n == 6:
            self.svg_file(a[1], I(2), I(3), I(4), I(5))
        elif op == "limg" and n == 5:
            self.ops.append(self.image(a[1], 0, 0, I(2), I(3), a[4]))
        elif op == "iframe" and n == 7:
            x, y = I(1), I(2)
            o = self.image(a[6], x, y, I(3), I(4), "stretch")
            if a[5] != "-":
                o += self.text(x + 18, y + 20, a[5], "frame-title", "start")
            self.ops.append('<g class="frame look-image">%s</g>' % o)
        elif op == "image" and n == 7:
            self.ops.append(self.image(a[1], I(2), I(3), I(4), I(5), a[6]))
        elif op == "ltog" and n == 7:
            self.ops.append(self.toggle_frame(I(1) + I(4) / 2, I(2) + I(5) / 2, I(3), I(4), I(5), skin_assets.decode(a[6])))
        elif op == "lbtn" and n == 8:
            self.ops.append(self.button_frame(I(1), I(2), I(3), I(4), I(5), a[6], skin_assets.decode(a[7])))
        elif op == "lseg" and n == 9:
            self.ops.append(self.seg_frame(I(1), I(2), I(3), I(4), I(5), a[6], a[7], skin_assets.decode(a[8])))
        elif op == "lstrip" and n == 5:
            r, frames, look = I(2), I(3), skin_assets.decode(a[4])
            s = 2 * r + 10
            self.jobs.append(("strip", a[1], s, s, frames,
                              [self.knob_frame(s / 2, s / 2, r, 100.0 * k / (frames - 1), look) for k in range(frames)]))
        elif op == "lsstrip" and n == 7:
            w, h, frames, vert, look = I(2), I(3), I(4), I(5), skin_assets.decode(a[6])
            self.jobs.append(("strip", a[1], w, h, frames,
                              [self.slider_frame(0, 0, w, h, vert, k / (frames - 1), look) for k in range(frames)]))
        elif op == "crop" and n == 6:
            lone = self.kinds[:1] == ["clear"] and len(self.kinds) == 2 and self.kinds[1] in (
                "pill", "button", "seg", "tile", "knob", "ltog", "lbtn", "lseg", "limg")
            svg = "".join(self.ops[1:] if lone else self.ops)
            self.jobs.append(("crop", svg, a[1], I(2), I(3), I(4), I(5), lone))
        elif op == "strip" and n == 5:
            r, frames = I(2), I(3)
            s = 2 * r + 10
            self.jobs.append(("strip", a[1], s, s, frames,
                              [self.knob_svg(s / 2, s / 2, r, round(100.0 * k / (frames - 1))) for k in range(frames)]))
        elif op == "sstrip" and n == 7:
            w, h, frames, vert = I(2), I(3), I(4), I(5)
            self.jobs.append(("strip", a[1], w, h, frames,
                              [self.slider_svg(0, 0, w, h, vert, k / (frames - 1)) for k in range(frames)]))
        else:
            raise SystemExit("html_art: bad command: %s (%d fields)" % (op, n))

    # ---- rendering ----
    def image_defs(self):
        """Each image the drawings use, once, as a data: URI (they refer to it with <use>)."""
        import base64
        out = []
        for path, iid in self.images.items():
            iw, ih = skin_assets.image_size(path)
            if path.lower().endswith(".svg"):
                # inlined, not a data: URI: an SVG drawn as an image can't use the page's fonts, so its text would fall
                # back to a serif. Inline it keeps Titillium Web (and any @font-face the stylesheets add).
                src = scope_svg(re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", open(path, encoding="utf-8").read()).strip(), iid)
                m = re.match(r"<svg\b", src)
                if m:
                    out.append('<svg id="%s" width="%d" height="%d"%s' % (iid, iw, ih, re.sub(r'\s(id|width|height)="[^"]*"', "",
                                                                                             src[4:src.index(">") + 1]))
                               + src[src.index(">") + 1:])
                    continue
            mime = skin_assets.MIME.get(os.path.splitext(path)[1].lower(), "image/png")
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            out.append('<image id="%s" width="%d" height="%d" preserveAspectRatio="none" href="data:%s;base64,%s"/>' % (
                iid, iw, ih, mime, data))
        return "<defs>%s</defs>" % "".join(out) if out else ""

    def page(self):
        css = ['<link rel="stylesheet" href="file://%s">' % os.path.join(HERE, "html_art", "default.css")]
        css += ['<link rel="stylesheet" href="file://%s">' % os.path.abspath(c) for c in self.css]
        vars_ = ";".join("--%s:%s" % (k.replace("_", "-"), hexc(v)) for k, v in self.theme.items())
        return ('<!doctype html><html><head><meta charset="utf-8"><style>:root{%s}html,body{margin:0;background:transparent}'
                'svg{display:block}</style>%s</head><body><svg id="c" xmlns="http://www.w3.org/2000/svg" class="%s" '
                'width="%d" height="%d">%s%s<g id="g"></g></svg></body></html>') % (
            vars_, "".join(css), "td3" if self.td3 else "", W, H, DEFS, self.image_defs())

    def render(self):
        from PIL import Image
        from playwright.sync_api import sync_playwright
        tmp = os.path.join(os.path.dirname(os.path.abspath(self.jobs[0][2] if self.jobs[0][0] == "crop" else self.jobs[0][1])),
                           "html_art_page.html")
        open(tmp, "w", encoding="utf-8").write(self.page())
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            pg = browser.new_page(viewport={"width": W, "height": H})
            pg.goto("file://" + tmp)
            pg.evaluate("document.fonts.ready")
            last = None

            def show(svg, w, h):
                pg.set_viewport_size({"width": w, "height": h})
                pg.evaluate("([s, w, h]) => { const c = document.getElementById('c'); c.setAttribute('width', w);"
                            " c.setAttribute('height', h); document.getElementById('g').innerHTML = s; }", [svg, w, h])
                # a layout pass first: a font (e.g. an embedded fontfile=) only starts loading once text uses it
                pg.evaluate("async () => { void document.body.offsetHeight; await document.fonts.ready; }")

            for job in self.jobs:
                if job[0] == "crop":
                    _, svg, path, x, y, w, h, lone = job
                    if svg != last:
                        show(svg, W, H)
                        last = svg
                    out = Image.new("RGBA" if lone else "RGB", (w, h), (0, 0, 0, 0) if lone else (0, 0, 0))
                    cx0, cy0, cx1, cy1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
                    if cx1 > cx0 and cy1 > cy0:
                        shot = pg.screenshot(clip={"x": cx0, "y": cy0, "width": cx1 - cx0, "height": cy1 - cy0},
                                             omit_background=lone)
                        out.paste(Image.open(io.BytesIO(shot)).convert(out.mode), (cx0 - x, cy0 - y))
                    out.save(path, "PNG" if lone else "PPM")
                else:
                    _, path, fw, fh, frames, parts = job
                    out = Image.new("RGBA", (fw, fh * frames), (0, 0, 0, 0))
                    per = max(1, 8000 // fh)
                    for k0 in range(0, frames, per):
                        chunk = parts[k0:k0 + per]
                        svg = "".join('<g transform="translate(0 %d)">%s</g>' % (i * fh, p) for i, p in enumerate(chunk))
                        show(svg, fw, fh * len(chunk))
                        last = None
                        shot = pg.screenshot(clip={"x": 0, "y": 0, "width": fw, "height": fh * len(chunk)}, omit_background=True)
                        out.paste(Image.open(io.BytesIO(shot)).convert("RGBA"), (0, k0 * fh))
                    out.save(path, "PNG")
            browser.close()
        os.remove(tmp)


def main():
    art = Art()
    for raw in sys.stdin:
        line = raw.rstrip("\r\n")
        if line:
            art.run(line)
    if art.jobs:
        art.render()


if __name__ == "__main__":
    main()
