"""Image assets and looks for skin controls (used by shadow_skin.py, html_art.py and the browser editor).

A control's look comes from its layout line, else from a top-level default for its group:

    knob     look=moog | img=knob.png [base=scale.png] | strip=knobs.png [frames=N]
    slider_v / slider_h   look=fader | img=cap.png [base=track.png] | strip=fader.png [frames=N]
    toggle   look=led | img=off.png [img_on=on.png] [w= h=]
    button   img=pad.png [img_on=pad_lit.png] [w= h=]          (the label is drawn on top; label="" for none)
    enum_h / enum_v   img=seg.png [img_on=seg_lit.png]         (each option: the image, its name on top)
    frame    img=panel.png                                     (a panel picture instead of the drawn border)
    popup    img=list.png                                      (the open list's panel, under the options)
    meter    strip=meter.png [frames=N]                        (a display-only filmstrip: see shadow_skin.py)
    meter    look=native img=bg.png [peak=fill.png] [rms=fill2.png] [direction=up|down|right] [invert=1]
                                                       (EXPERIMENTAL, unverified: a real native Meter component
                                                        instead of the filmstrip fake above; see docs/ROADMAP.md
                                                        "A native Meter component". direction/invert are read
                                                        straight off the widget, not part of the look.)

    top level: <group>_<attr>=value, e.g. knob_look=moog, slider_img=cap.png, toggle_img=led_off.png
    (groups: knob, slider, toggle, button, seg, frame, popup, meter). A line that sets any look attribute ignores the defaults;
    look=drawn keeps the renderer's own drawing.

img is the moving part: a knob image turns through the knob's 270 degrees (drawn pointing up = the middle of the
travel), a slider image is the thumb (as wide as a vertical slider, as tall as a horizontal one). base stays still
under it (a knob's scale or skirt; a slider's track, stretched to the slider). strip is a ready filmstrip, frames
stacked down (or across, for a wide image), minimum at the top/left; the frame count comes from the image shape
unless frames= says. On/off images: img is off, img_on is on (without it, img brightened). peak/rms are a native
meter's own overlay images (see above). Paths are relative to the layout. Images: .png .jpg .jpeg .webp .gif .svg.
Looks need the browser renderer ("art": "html"). Standard library only.
"""
import hashlib
import json
import os
import re
import struct

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
        ".svg": "image/svg+xml"}
ATTRS = ("look", "img", "img_on", "base", "strip", "frames", "peak", "rms")
FILE_ATTRS = ("img", "img_on", "base", "strip", "peak", "rms")
GROUP = {"knob": "knob", "slider_v": "slider", "slider_h": "slider", "toggle": "toggle", "button": "button",
         "enum_h": "seg", "enum_v": "seg", "frame": "frame", "popup": "popup", "meter": "meter"}
LOOKS = {"knob": ("moog", "chicken", "metal", "cap", "prophet", "hardware", "chrome", "bakelite", "davies", "rubber", "ledring", "taper"), "slider": ("fader",), "toggle": ("led", "switch"),
         "button": (), "seg": (), "frame": (), "popup": (),
         "meter": ("native",)}   # EXPERIMENTAL: a real Meter component instead of the filmstrip fake
DEFAULT_RE = re.compile(r"(%s)_(%s)$" % ("|".join(LOOKS), "|".join(ATTRS)))
TOGGLE_SIZE = {"led": (30, 30), "switch": (34, 50)}


def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def image_size(path):
    """(width, height) of a PNG, JPEG, GIF, WebP or SVG file, without Pillow; (0, 0) when unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(64 * 1024)
    except OSError:
        return (0, 0)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", head[6:10])
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        kind = head[12:16]
        if kind == b"VP8X":
            return (1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little"))
        if kind == b"VP8L":
            b = int.from_bytes(head[21:25], "little")
            return (1 + (b & 0x3FFF), 1 + ((b >> 14) & 0x3FFF))
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", head[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
    if head[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                i += 1
                continue
            marker, size = head[i + 1], struct.unpack(">H", head[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", head[i + 5:i + 9])
                return (w, h)
            i += 2 + size
        return (0, 0)
    m = re.search(rb"<svg\b[^>]*>", head)
    if m:
        tag = m.group(0).decode("utf-8", "replace")
        num = lambda k: re.search(r'\b%s="\s*([\d.]+)\s*(px)?\s*"' % k, tag)
        w, h = num("width"), num("height")
        if w and h:
            return (round(float(w.group(1))), round(float(h.group(1))))
        vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', tag)
        if vb:
            return (round(float(vb.group(1))), round(float(vb.group(2))))
    return (0, 0)


def strip_layout(path, frames=None, aspect=1.0):
    """A filmstrip -> (image width, height, frame count, stacked down?). aspect = frame height / width, used to
    count frames when frames= isn't given."""
    iw, ih = image_size(path)
    down = ih >= iw
    if frames:
        n = int(frames)
    elif down:
        n = round(ih / max(1.0, iw * aspect))
    else:
        n = round(iw * aspect / max(1, ih))
    return iw, ih, max(1, n), down


def defaults(lines):
    """Top-level <group>_<attr>= lines -> {"knob_look": "moog", ...}."""
    out = {}
    for line in lines:
        k, _, v = line.strip().partition("=")
        if DEFAULT_RE.match(k.strip()):
            out[k.strip()] = v.strip()
    return out


def look_of(w, defs, base_dir="."):
    """The look of widget w as a dict (file paths absolute), or None for the renderer's own drawing."""
    g = GROUP.get(w["kind"])
    if not g:
        return None
    src = w if any(a in w for a in ATTRS) else {a: defs[g + "_" + a] for a in ATTRS if g + "_" + a in defs}
    d = {a: src[a] for a in ATTRS if src.get(a) not in (None, "")}
    if not d or d.get("look") == "drawn":
        return None
    for a in FILE_ATTRS:
        if a in d:
            d[a] = os.path.abspath(os.path.join(base_dir, d[a]))
    if "frames" in d:
        d["frames"] = int(d["frames"])
    return d


def check(w, look):
    """Why this look can't be built, or None."""
    g = GROUP[w["kind"]]
    if g == "meter" and look.get("look") == "native":
        return ("look=native (the real Meter component) breaks the whole plugin screen on a real device "
                "(verified 2026-09-25, docs/NOTES.md) -- use strip= (the filmstrip meter) instead")
    if g == "meter" and not look.get("strip"):
        return "a meter needs strip= (its filmstrip)"
    if g in ("frame", "popup") and not look.get("img"):
        return "%s: only img= (a panel picture)" % w["kind"]
    if look.get("look") and look["look"] not in LOOKS[g]:
        return "look=%s: %s has %s" % (look["look"], w["kind"], ", ".join(LOOKS[g]) + " or drawn" if LOOKS[g] else "no built-in looks (use img=)")
    for a in FILE_ATTRS:
        if a in look and not os.path.isfile(look[a]):
            return "%s=%s: no such file" % (a, look[a])
        if a in look and not is_image(look[a]):
            return "%s=%s: not an image (%s)" % (a, look[a], " ".join(IMAGE_EXTS))
        if a in look and image_size(look[a]) == (0, 0):
            return "%s=%s: can't read its size" % (a, look[a])
    return None


def look_id(look):
    """A short stable name for a look (image names and component keys in the skin)."""
    return hashlib.sha1(json.dumps(look, sort_keys=True).encode()).hexdigest()[:8] if look else ""


def fit(path, max_w, max_h):
    """An image's size scaled to fit max_w x max_h (keeping its shape)."""
    iw, ih = image_size(path)
    if not iw or not ih:
        return max_w, max_h
    s = min(max_w / iw, max_h / ih)
    return max(8, round(iw * s)), max(8, round(ih * s))


def toggle_size(w, look):
    """A toggle's image size: w=/h= on its line, else its look's own size (the stock pill: 51 x 27)."""
    if w.get("w") and w.get("h"):
        return int(w["w"]), int(w["h"])
    if not look:
        return 51, 27
    if look.get("img"):
        return fit(look["img"], 110, 44)
    return TOGGLE_SIZE.get(look.get("look"), (51, 27))


def button_size(w, look, label_w):
    """A button's size with a look: w=/h= on its line, else its image scaled to 39 px tall."""
    if w.get("w") and w.get("h"):
        return int(w["w"]), int(w["h"])
    if look and look.get("img"):
        return fit(look["img"], max(240, label_w), 39)
    return label_w, 39


def encode(look):
    """A look as one field of a renderer command (JSON; paths never hold a newline)."""
    return json.dumps(look, separators=(",", ":")).replace("|", "\\u007c")


def decode(s):
    return json.loads(s) if s and s != "-" else None
