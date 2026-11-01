#!/usr/bin/env python3
"""Flatten a built MPC skin (TUI.json and its images) into the plain list the desktop VST3 editor draws
(wrapper/vst3_editor.c), and copy the images it uses:

    desktop_skin.py <skin folder> <out folder>

<skin folder> is gen_vst.py's `build/skin/<vendor> - VST - <name>` (either skin shape: MPC OS 3.x pages named by
`componentName`, or 2.x pages inline). <out folder> gets `desktop.skin` and the PNGs. Read like studio.py preview reads a
skin, so what the editor shows is what the offline preview shows, with live values.

desktop.skin: one item per line, tab-separated, the first field its kind, then key=value fields. Items are drawn in file
order; a click goes to the last visible `hit` under the pointer. `if=p:i,...` shows an item only while parameter p is at
option i (IndexedEnabling: when= panels, open popups). Parameters are the VST2 indices (params.h).
    mpcskin 1
    size    w= h=                             the page, in MPC pixels (1280 x 628)
    tab     name=                             a page; the items after it belong to it
    img     x y w h src= [if=]                a still image
    film    x y w h src= param= frames= [if=] a filmstrip frame chosen by the value (knobs, sliders, pictures)
    btn     x y w h on= off= param= id= n= [if=]   on/off image: on while the value is option id of n (n = 1: while on)
    label   x y w h param= kind=value|name text= just=l|c|r upper= colour=AARRGGBB size= style= [if=]
    hit     x y w h param= mode=radio|toggle|drag id= n= [if=]
"""
import json
import os
import re
import shutil
import sys


def handles(c):
    """IndexedEnabling conditions: [(option index, option count, parameter index)] (studio.handles)."""
    return [tuple(int(g) for g in m.groups()) for m in
            (re.match(r"IndexedEnabling/(\d+)/(\d+)/Parameter (\d+)$", h) for h in c["bounds"].get("additionalInvalidatingHandles", []))
            if m]


def rect(b):
    return [int(round(float(v))) for v in b["bounds"].split()]


def remap(c):
    """handle name -> parameter index, from a component's "handle remapping" ("Data" -> "Parameter 12")."""
    out = {}
    for m in c["handle remapping"]["map"]:
        g = re.match(r"Parameter (\d+)$", m.get("value", ""))
        if g:
            out[m.get("key", "Data")] = int(g.group(1))
    return out


def clean(s):
    return str(s).replace("\t", " ").replace("\n", " ")


def convert(skin_dir, out_dir):
    tui = os.path.join(skin_dir, "TUI.json")
    if not os.path.exists(tui):
        tui = os.path.join(skin_dir, "Plugin Skins", "TUI.json")
    src_dir = os.path.dirname(tui)
    t = json.load(open(tui))["pageData"]
    defs = {d["key"]: d["value"] for d in t["componentDefinitions"]["localComponentDefinitions"]}
    os.makedirs(out_dir, exist_ok=True)
    images = set()
    lines = ["mpcskin\t1"]
    size = None

    def img(name):
        images.add(name)
        return clean(name)

    for tab in t["tabs"]:
        page = tab["componentDefinition"] if "componentDefinition" in tab else defs[tab["componentName"]]
        if size is None:
            x0, y0, w0, h0 = [int(float(v)) for v in str(tab.get("initialSize", "0 0 1280 628")).split()]
            size = (w0, h0)
            lines.append("size\tw=%d\th=%d" % size)
        lines.append("tab\tname=%s" % clean(tab["tabName"]))
        for c in page["componentsData"]:
            cd = c["componentData"]
            x, y, w, h = rect(c["bounds"])
            cond = ",".join("%d:%d" % (p, i) for i, n, p in handles(c))
            cond = ("\tif=" + cond) if cond else ""
            geo = "x=%d\ty=%d\tw=%d\th=%d" % (x, y, w, h)
            if cd["type"] == "Image":
                if cd["data"].get("image"):
                    lines.append("img\t%s\tsrc=%s%s" % (geo, img(cd["data"]["image"]), cond))
                continue
            d = defs.get(cd["type"])
            if d is None:
                continue
            params = remap(c)
            data_p = params.get("Data", -1)
            group = None   # the Button's (id, n, param) and rect, which say how a tap sets the value
            btn_rect = None
            value_rects = []   # value labels: one over the button takes the touch (shadow_skin.py, list rows)
            has_knob = False
            for s in d["componentsData"]:
                sd = s["componentData"]
                if s["bounds"].get("whenVisible") == "WhenFocussed" or sd["type"] == "Focus":
                    continue
                sx, sy, sw, sh = rect(s["bounds"])
                sgeo = "x=%d\ty=%d\tw=%d\th=%d" % (x + sx, y + sy, sw, sh)
                dd = sd.get("data", {})
                p = params.get(dd.get("handleName", "Data"), data_p)
                if sd["type"] == "Image" and dd.get("image"):
                    lines.append("img\t%s\tsrc=%s%s" % (sgeo, img(dd["image"]), cond))
                elif sd["type"] == "Knob" and dd.get("filmStrip"):
                    has_knob = True
                    lines.append("film\t%s\tsrc=%s\tparam=%d\tframes=%d%s" % (sgeo, img(dd["filmStrip"]), p, int(dd.get("numFrames") or 127), cond))
                elif sd["type"] == "Button":
                    on, off = dd.get("onImage") or "", dd.get("offImage") or ""
                    bid, n = int(dd.get("buttonId", 1)), int(dd.get("numButtonsInGroup", 1))
                    if group is None:
                        group, btn_rect = (bid, n, p), (sx, sy, sw, sh)
                    lines.append("btn\t%s\ton=%s\toff=%s\tparam=%d\tid=%d\tn=%d%s" % (sgeo, img(on) if on else "", img(off) if off else "", p, bid, n, cond))
                elif sd["type"] == "Label":
                    ts = dd.get("textStyle", {})
                    just = ts.get("justification", "")
                    j = "c" if "horizontallyCentred" in just else "r" if "right" in just else "l"
                    kind = "name" if dd.get("type") == "Name" else "value"
                    if kind == "value":
                        value_rects.append((sx, sy, sw, sh))
                    lines.append("label\t%s\tparam=%d\tkind=%s\ttext=%s\tjust=%s\tupper=%d\tcolour=%s\tsize=%g\tstyle=%s%s" % (
                        sgeo, p, kind, clean(cd.get("name", "")) if kind == "name" else "", j, int(ts.get("case") == "Upper Case"),
                        ts.get("colour", "ffffffff"), float(ts.get("font", {}).get("height", 20)), clean(ts.get("font", {}).get("style", "SemiBold")), cond))
            acts = {(a["onAction"], a["handler"]) for a in d.get("actions", [])}
            # On MPC a Button takes a touch itself (segments, popup options, toggles), unless a value label lies over it
            # (then the component needs its own Mouse Down -> Toggle Switch; without one it does not respond to touch).
            covered = btn_rect is not None and any(
                lx < btn_rect[0] + btn_rect[2] and btn_rect[0] < lx + lw and ly < btn_rect[1] + btn_rect[3] and btn_rect[1] < ly + lh
                for lx, ly, lw, lh in value_rects)
            tap = ("Mouse Down", "Toggle Switch") in acts or (group is not None and not covered)
            if d.get("ignoreMousePresses"):
                tap = False
            if tap and (data_p >= 0 or group):
                bid, n, gp = group or (1, 1, data_p)
                mode = "radio" if n > 1 else "toggle"
                lines.append("hit\t%s\tparam=%d\tmode=%s\tid=%d\tn=%d%s" % (geo, gp, mode, bid, n, cond))
            elif data_p >= 0 and has_knob and ("Mouse Down", "Q-Link") in acts:
                lines.append("hit\t%s\tparam=%d\tmode=drag\tid=0\tn=0%s" % (geo, data_p, cond))
    for name in sorted(images):
        s = os.path.join(src_dir, name)
        if os.path.exists(s):
            shutil.copyfile(s, os.path.join(out_dir, os.path.basename(name)))
        else:
            sys.stderr.write("warning: desktop skin: %s is missing\n" % name)
    open(os.path.join(out_dir, "desktop.skin"), "w").write("\n".join(lines) + "\n")
    return len(t["tabs"]), len(lines), len(images)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    tabs, n, imgs = convert(sys.argv[1], sys.argv[2])
    print("desktop skin: %d pages, %d items, %d images" % (tabs, n, imgs))
