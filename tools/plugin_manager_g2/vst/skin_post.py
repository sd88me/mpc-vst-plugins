#!/usr/bin/env python3
"""vst.json "skin_post": the screenshots make up most of the skin (a thumbnail button per plugin on each card, with
its pressed copy, and the detail view's baked pictures). Their built PNGs are reduced to 256 colours, and images that
came out identical (the same thumbnail on each card row: the builder names them after the row's parameter) are kept
once, TUI.json pointing at that copy. Small images (the artwork, text) are left as built.
Readouts (live text) ignore touches: they sit over the cards and the detail view's tag buttons, whose taps must reach
the card or button under them."""
import hashlib
import json
import os
import sys

from PIL import Image

MIN = 16000   # bytes: below this a PNG is artwork, not a screenshot

for root, _, files in os.walk(sys.argv[1]):
    if "TUI.json" not in files:
        continue
    same = {}   # duplicate name -> the kept one
    first = {}
    for f in sorted(files):
        path = os.path.join(root, f)
        if not f.endswith(".png"):
            continue
        if os.path.getsize(path) >= MIN:
            im = Image.open(path)
            q = im.quantize(256, method=Image.Quantize.FASTOCTREE) if im.mode == "RGBA" else im.convert("RGB").quantize(256)
            q.save(path, optimize=True)
        h = hashlib.sha1(open(path, "rb").read()).hexdigest()
        if h in first:
            same[f] = first[h]
            os.remove(path)
        else:
            first[h] = f
    tui = os.path.join(root, "TUI.json")
    src = open(tui, encoding="utf-8").read()
    for dup, keep in same.items():
        src = src.replace('"%s"' % dup, '"%s"' % keep)
    t = json.loads(src)
    quiet = 0
    for d in t["pageData"]["componentDefinitions"]["localComponentDefinitions"]:
        if d["key"].startswith("shReadout_"):
            d["value"]["ignoreMousePresses"] = True
            quiet += 1
    open(tui, "w", encoding="utf-8").write(json.dumps(t, indent=4))
    print("skin_post: readouts ignore touches (%d)" % quiet)
    print("skin_post: %d duplicate images merged" % len(same))
