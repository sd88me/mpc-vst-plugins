#!/usr/bin/env python3
"""Draw vitOTTx's skin images (run once after a change; the PNGs are committed next to it). Needs Pillow.

    python3 ports/vitottx/art/make_art.py

bg.png       the whole plugin area (1280x628): light control panels either side of the dark band-meter panel
knob*.png    knob caps (img=, turned by the renderer) and their fixed scale (base=)
meter/       one image per meter step (the engine's METER_STEPS over METER_MIN_DB..METER_MAX_DB): per band, the
             output bar (zones + level + cursor) and the thin input strip. layout.conf shows them with `picture`.
Coordinates here must match layout.conf's (layout y = shadow y - 86).
"""
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 628
STEPS, MIN_DB, MAX_DB = 24, -60.0, 0.0
BAR_W, BAR_H, IN_H = 400, 40, 8
# band thresholds (lower, upper) as in src/engine.cpp
THRESH = {"h": (-35.0, -30.0), "m": (-36.0, -25.0), "l": (-35.0, -28.0)}
PANEL_L, PANEL_R = 400, 1010       # dark meter panel between them

LIGHT_TOP, LIGHT_BOT = (214, 222, 228), (188, 199, 207)
TEAL_TOP, TEAL_BOT = (22, 52, 60), (40, 70, 66)
BEIGE, BEIGE_DIM = (140, 134, 120), (78, 82, 76)
GREEN, GREEN_DIM = (82, 150, 96), (44, 84, 62)
GAP = (24, 44, 44)


def vgrad(d, box, top, bot):
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        t = (y - y0) / max(1, y1 - y0 - 1)
        d.line([(x0, y), (x1 - 1, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bot)))


def bg():
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    vgrad(d, (0, 0, W, H), LIGHT_TOP, LIGHT_BOT)
    vgrad(d, (PANEL_L, 0, PANEL_R, H), TEAL_TOP, TEAL_BOT)
    for x in (PANEL_L, PANEL_R - 1):   # bevel edges
        d.line([(x, 0), (x, H)], fill=(10, 24, 28), width=3)
    # value pills under the left knobs and the right knobs (MPC draws the value text on them)
    # (layout.conf knob cy - 86 + 82: where MPC draws a r=40 knob's value)
    for cx, cy in [(110, 316), (290, 316), (110, 536), (290, 536),
                   (1080, 206), (1210, 206), (1080, 406), (1080, 586), (1210, 586)]:
        d.rounded_rectangle([cx - 64, cy - 15, cx + 64, cy + 15], radius=8, fill=(44, 50, 56))
    for y in (124, 294, 464):   # band rows: the level readout's well
        d.rounded_rectangle([408, y - 22, 492, y + 22], radius=6, fill=(12, 30, 34))
    return im


def knob_cap(size, face_top, face_bot, ring, pointer):
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([s * .06, s * .09, s * .94, s * .97], fill=(0, 0, 0, 90))            # drop shadow
    d.ellipse([s * .04, s * .04, s * .96, s * .96], fill=ring)
    m = s * .12
    for i in range(int(s - 2 * m)):                                                  # face gradient
        t = i / (s - 2 * m)
        c = tuple(round(a + (b - a) * t) for a, b in zip(face_top, face_bot)) + (255,)
        y = m + i
        r = (s - 2 * m) / 2
        dy = abs(y - s / 2)
        if dy < r:
            dx = (r * r - dy * dy) ** .5
            d.line([(s / 2 - dx, y), (s / 2 + dx, y)], fill=c)
    d.line([(s / 2, s * .16), (s / 2, s * .40)], fill=pointer, width=int(s * .045))  # pointer, up = middle
    return im.resize((size, size), Image.LANCZOS)


def knob_scale(size, col):
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.arc([s * .01, s * .01, s * .99, s * .99], 135, 405, fill=col, width=int(s * .025))
    for a in (135, 405):   # end dots like the reference
        import math
        r = s * .47
        x, y = s / 2 + r * math.cos(math.radians(a)), s / 2 + r * math.sin(math.radians(a))
        d.ellipse([x - s * .02, y - s * .02, x + s * .02, y + s * .02], fill=col)
    return im.resize((size, size), Image.LANCZOS)


def x_of(db):
    return round((db - MIN_DB) / (MAX_DB - MIN_DB) * BAR_W)


def db_of(step):
    return MIN_DB + step * (MAX_DB - MIN_DB) / (STEPS - 1)


def bar(band, step):
    lo, hi = THRESH[band]
    im = Image.new("RGB", (BAR_W, BAR_H), GAP)
    d = ImageDraw.Draw(im)
    xl, xh, xv = x_of(lo), x_of(hi), x_of(db_of(step)) if step else 0
    d.rectangle([0, 0, xl - 1, BAR_H], fill=BEIGE_DIM)       # upward zone (below the lower threshold)
    d.rectangle([xh, 0, BAR_W, BAR_H], fill=GREEN_DIM)       # downward zone (above the upper threshold)
    if xv:                                                    # the level, lit
        d.rectangle([0, 0, min(xv, xl) - 1, BAR_H], fill=BEIGE)
        if xv > xh:
            d.rectangle([xh, 0, xv - 1, BAR_H], fill=GREEN)
        d.rectangle([xv - 3, 0, xv, BAR_H], fill=(250, 250, 250))
    else:
        d.rectangle([0, 0, 2, BAR_H], fill=(250, 250, 250))
    return im


def strip(step):
    im = Image.new("RGB", (BAR_W, IN_H), (16, 34, 38))
    if step:
        ImageDraw.Draw(im).rectangle([0, 1, x_of(db_of(step)) - 1, IN_H - 2], fill=(170, 186, 190))
    return im


def main():
    bg().save(os.path.join(HERE, "bg.png"))
    knob_cap(96, (78, 84, 90), (30, 34, 38), (26, 28, 30, 255), (240, 240, 240, 255)).save(os.path.join(HERE, "knob.png"))
    knob_scale(120, (40, 46, 52, 255)).save(os.path.join(HERE, "knob_scale.png"))
    knob_cap(70, (196, 222, 214), (120, 160, 150), (60, 80, 80, 255), (30, 40, 40, 255)).save(os.path.join(HERE, "knob_band.png"))
    knob_scale(92, (196, 222, 214, 255)).save(os.path.join(HERE, "knob_band_scale.png"))
    os.makedirs(os.path.join(HERE, "meter"), exist_ok=True)
    for b in THRESH:
        for k in range(STEPS):
            bar(b, k).save(os.path.join(HERE, "meter", "%s_out_%02d.png" % (b, k)))
    for k in range(STEPS):
        strip(k).save(os.path.join(HERE, "meter", "in_%02d.png" % k))


if __name__ == "__main__":
    main()
