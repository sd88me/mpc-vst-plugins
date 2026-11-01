#!/usr/bin/env python3
"""Screenshots from the catalog for the cards and the detail view. For every catalog entry (mpc-vst-plugins'
catalog/plugins/*.json) with a "screenshot", downloads it, crops it to 2:1 and writes images/shots/<id>.png at the
card's tile size (with a dark chip in the corner for the live INST/FX/ADDIN text) and images/shots_detail/<id>.png for the
detail view. Then writes the r<N>_shot and d_shot option parameters into params.json, a thumbnail button per id on
each card and the detail picture's file list into layout.conf, and src/shots.h (the ids, in option order) for the
engine. A plugin without a screenshot, or added to the catalog after this ran, keeps its initials.
Run it before a release:  python3 vst/shots.py [--gen2]  (default: every catalog screenshot, one skin for Gen1 and Gen2; --gen2: only the plugins with an aarch64 zip, a much lighter skin)  (MPC_VST: the mpc-vst-plugins checkout; needs Pillow)."""
import glob
import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
MPC_VST = os.environ.get("MPC_VST", os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(HERE, "images", "shots")
OUT_BIG = os.path.join(HERE, "images", "shots_detail")
W, H = 136, 68
BIG = (270, 135)   # layout.conf: picture ... key=d_shot
CHIP = (90, 51, 134, 66)   # behind the kind text (vst/make_rows.py rN_kindtxt)
ROWS = 5


def crop21(data):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    if w > 2 * h:
        x = (w - 2 * h) // 2
        return im.crop((x, 0, x + 2 * h, h))
    y = (h - w // 2) // 2
    return im.crop((0, y, w, y + w // 2))


def thumb(im):
    im = im.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im, "RGBA")
    d.rounded_rectangle(CHIP, 5, fill=(12, 12, 13, 210))
    d.rectangle((0, 0, W - 1, H - 1), outline=(52, 54, 59))
    return im


def prune(folder, ids):
    for f in os.listdir(folder):
        if f[:-4] not in ids:
            os.remove(os.path.join(folder, f))


def gen2_ids():
    """Catalog ids whose newest version has an aarch64 zip (the live catalog.json): the only ones a Gen2 MPC can install. Every thumbnail is
    one button per id per row (5 x 159 components made the Live III draw black patches in the header, 2026-10-28), so a lean Gen2 skin (--gen2) bakes only these."""
    url = os.environ.get("CATALOG_URL", "https://sd88me.github.io/mpc-vst-plugins/catalog.json")
    cat = json.load(io.BytesIO(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "openmpc-pm shots.py"}), timeout=60).read()))
    out = set()
    for p in cat["plugins"]:
        v = (p.get("versions") or [{}])[0]
        if "aarch64" in (v.get("assets") or {}):
            out.add(p["id"])
    return out


def main():
    entries = sorted(glob.glob(os.path.join(MPC_VST, "catalog", "plugins", "*.json")))
    if not entries:
        sys.exit("no catalog entries under %s (set MPC_VST)" % MPC_VST)
    if "--gen2" in sys.argv:   # the lean set: only plugins with an aarch64 zip (default: every catalog screenshot, one skin for Gen1 and Gen2)
        keep = gen2_ids()
        entries = [p for p in entries if os.path.basename(p)[:-5] in keep]
        print("Gen2 only: %d catalog ids have an aarch64 zip" % len(entries))
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(OUT_BIG, exist_ok=True)
    ids = []
    for path in entries:
        e = json.load(open(path))
        url = e.get("screenshot", "")
        if not url.startswith("https://"):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mpc-vst-manager shots.py"})
            im = crop21(urllib.request.urlopen(req, timeout=30).read())
        except Exception as ex:   # a broken link leaves that plugin on its initials
            print("skip %s: %s" % (e["id"], ex), file=sys.stderr)
            continue
        thumb(im).save(os.path.join(OUT, e["id"] + ".png"), optimize=True)
        im.resize(BIG, Image.LANCZOS).quantize(256).save(os.path.join(OUT_BIG, e["id"] + ".png"), optimize=True)
        ids.append(e["id"])
    prune(OUT, ids)
    prune(OUT_BIG, ids)

    pj = os.path.join(HERE, "params.json")
    p = json.load(open(pj))
    p["params"] = [x for x in p["params"] if not re.match(r"(r\d|d)_shot$", x["key"])]
    for r in range(1, ROWS + 1):
        p["params"].append({"key": "r%d_shot" % r, "name": "Card %d screenshot" % r, "options": ["none"] + ids})
    p["params"].append({"key": "d_shot", "name": "Detail screenshot", "options": ["hidden", "none"] + ids})
    open(pj, "w").write(json.dumps(p, indent=1) + "\n")

    # one image button per thumbnail, right after its card: MPC draws baked art (picture) under the cards, so the
    # thumbnails are live components like the badges; the same image on every row is stored once. The detail view
    # has no cards over it, so its screenshot is a picture (one baked image per plugin, no pressed copy).
    lc = os.path.join(HERE, "layout.conf")
    out, rows, big = [], 0, 0
    for line in open(lc).read().split("\n"):
        if "img=images/shots/" in line:
            continue
        if re.match(r"picture .*key=d_shot ", line):
            line = re.sub(r'files="[^"]*"', 'files=",images/tile_detail.svg,%s"' % ",".join("images/shots_detail/%s.png" % i for i in ids), line)
            big += 1
        out.append(line)
        m = re.match(r"list x=\d+ y=(\d+) .*key=card(\d)\b", line)
        if m:
            y, r = int(m.group(1)), int(m.group(2))
            rows += 1
            out += ['button cx=%d cy=%d label="" key=r%d_open img=images/shots/%s.png w=%d h=%d when=r%d_shot:%s'
                    % (34 + W // 2, y + 6 + H // 2, r, i, W, H, r, i) for i in ids]
    if rows != ROWS or big != 1:
        sys.exit("layout.conf: expected %d card lists and one d_shot picture, found %d and %d" % (ROWS, rows, big))
    open(lc, "w").write("\n".join(out))

    open(os.path.join(HERE, "..", "src", "shots.h"), "w").write(
        "/* generated by vst/shots.py: catalog ids with a screenshot, in r<N>_shot option order (from option 1; 0 none; d_shot: one later, 0 hidden) */\n"
        "static const char *const SHOTS[] = {\n%s};\n" % "".join('    "%s",\n' % i for i in ids))
    print("%d screenshots" % len(ids))


if __name__ == "__main__":
    main()
