#!/usr/bin/env python3
"""Skin studio: first-pass layouts, an Inkscape round trip, and previews for MPC plugin skins.

    studio.py auto     PARAMS -o layout.conf [--title NAME]    parameters -> first-pass layout
    studio.py to-svg   layout.conf -o layout.svg               layout -> editable SVG (Inkscape/Penpot)
    studio.py from-svg layout.svg -o layout.conf               edited SVG -> layout
    studio.py preview  SKIN_DIR -o out_%d.png                  built skin -> one PNG per page
    studio.py serve    [layout.conf | vst.json] [--open]       edit a layout in the browser (studio_web.py)

PARAMS is a port's parameter file (tools/params.py; its "sections" become frames), or an
adapter's source (adapters/). The layout is the shadow_page.conf-style file that
shadow_skin.py builds skins from (see its docstring), so every route ends in the same pipeline:

    auto ──► layout.conf ──► to-svg ──► (edit in Inkscape) ──► from-svg ──► layout.conf ──► skin
             (or hand-edit layout.conf directly; any step is optional)

SVG conventions (what to-svg writes and from-svg reads), all in plugin pixels (1280x628):
  - one Inkscape layer per tab, labelled `tab <NAME>`; only the first is visible by default
  - the layer's <desc> holds `qlinks "PAGE" = key,...` lines (one per nested page; optional)
  - each control is an element (usually a group) whose Inkscape label is its layout line without
    coordinates, e.g. `knob key=cutoff label="CUTOFF"`, `frame title="FILTER"`,
    `list key=result cols=2 rows=4 gap=4`; the geometry comes from its first circle/rect
  - knobs: a circle (centre + radius); everything else: a rect (centre and/or size, by kind)
  - anything without such a label (drawings, text, images) is background artwork: from-svg writes each
    tab's to `<layout>.<tab>.art.svg` and adds an `art file=...` line (drawn by the browser renderer,
    vst.json "art": "html"); a group labelled `art when=<param>:<option>` becomes art for that mode only
Moving, resizing and duplicating elements in Inkscape is all you need; transforms are handled.
"""
import argparse
import json
import math
import os
import re
import shlex
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shadow_skin  # noqa: E402
import params  # noqa: E402

W, H, Y_OFF = shadow_skin.W, shadow_skin.H, shadow_skin.Y_OFF
SVG_NS = "http://www.w3.org/2000/svg"
INK_NS = "http://www.inkscape.org/namespaces/inkscape"
SODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
ET.register_namespace("", SVG_NS)
ET.register_namespace("inkscape", INK_NS)
ET.register_namespace("sodipodi", SODI_NS)
LABEL = "{%s}label" % INK_NS
GROUPMODE = "{%s}groupmode" % INK_NS
GEOM_KEYS = ("x", "y", "w", "h", "cx", "cy", "r", "sw")


# ---------------------------------------------------------------- parameters

def load_params(path):
    """-> (params list, sections [(label, [keys])]); without sections, group by key prefix"""
    ps, sections = params.load(path)
    if sections:
        seen = {k for _, ks in sections for k in ks}
        rest = [p["key"] for p in ps if p["key"] not in seen]
        return ps, sections + ([("More", rest)] if rest else [])
    groups = {}
    for p in ps:
        groups.setdefault(p["key"].split("_")[0], []).append(p["key"])
    return ps, [(g.upper(), ks) for g, ks in groups.items()]


def kind_for(p):
    t = p.get("type", "float")
    if t in ("readout", "stepper"):
        return t
    if t == "trigger" or p.get("momentary"):
        return "button"
    if t == "slot":
        return "slot"
    opts = [str(o).lower() for o in p.get("options") or []]
    if opts:
        if len(opts) == 2 and opts[0] in ("off", "free", "no"):
            return "toggle"
        return "enum_v" if len(opts) <= 6 else "popup"   # 7+ won't fit one column: a field that opens a list
    return "knob"


# ---------------------------------------------------------------- auto layout

SLOT_W, SLOT_X0 = 158, 8
ROW_Y = (Y_OFF + 6, Y_OFF + 6 + 312)     # frame tops (shadow coords) of the two rows
ROW_H = 304


def auto_layout(params, sections, title=None):
    """Sections -> titled frames; rows of 8 slots (= a Q-Link bank); 2 rows per tab."""
    byk = {p["key"]: p for p in params}
    items = []   # (section label, key, slots): steppers/readouts take 2 slots
    for label, ks in sections:
        for k in ks:
            kd = kind_for(byk[k])
            is_arrow = (k.endswith("_prev") or k.endswith("_next")) and k[:-5] in byk
            if kd == "slot" or is_arrow:   # result rows and stepper arrows belong to their widget
                continue
            items.append((label, k, 2 if kd in ("readout", "stepper") else 1))
    # Pack into rows of 8 slots. A section that won't fit in what's left of a row starts a new row;
    # one bigger than a row (e.g. an LFO with 14 controls) starts a new tab and fills its rows.
    tabs, cur, row, used = [], [], [], 0

    def close_row():
        nonlocal row, used, cur
        if row:
            cur.append(row)
        row, used = [], 0
        if len(cur) == 2:
            tabs.append(cur)
            cur = []

    for i, it in enumerate(items):
        if not row or it[0] != row[-1][0]:
            need = sum(x[2] for x in items[i:] if x[0] == it[0])
            if need > 8:
                close_row()
                if cur:
                    tabs.append(cur)
                    cur = []
            elif used + need > 8:
                close_row()
        if used + it[2] > 8:
            close_row()
        row.append(it)
        used += it[2]
    close_row()
    if cur:
        tabs.append(cur)

    out = ["# first-pass layout from studio.py auto; edit freely (or round-trip through to-svg)"]
    for t, trows in enumerate(tabs):
        names = []
        for r in trows:
            for lab in dict.fromkeys(x[0] for x in r):
                if lab not in names:
                    names.append(lab)
        tab_name = " / ".join(names).upper()
        if len(tab_name) > 28:
            tab_name = names[0].upper() + " +%d" % (len(names) - 1)
        out += ["", "[tab %s]" % tab_name]
        qkeys = []
        for r_i, r in enumerate(trows):
            y0 = ROW_Y[r_i]
            slot = 0
            start = 0
            while start < len(r):   # one frame per run of the same section
                end = start
                while end < len(r) and r[end][0] == r[start][0]:
                    end += 1
                span = sum(x[2] for x in r[start:end])
                fx = SLOT_X0 + slot * SLOT_W
                out.append('frame x=%d y=%d w=%d h=%d title="%s"' % (fx + 2, y0, span * SLOT_W - 6, ROW_H, r[start][0].upper()))
                for label, k, width in r[start:end]:
                    cx = SLOT_X0 + slot * SLOT_W + width * SLOT_W // 2
                    out.append(widget_line(byk[k], kind_for(byk[k]), cx, y0, width))
                    qkeys.append(k)
                    slot += width
                start = end
        out.append('qlinks "%s" = %s' % (tab_name, ",".join(qkeys[:16])))
    return "\n".join(out) + "\n"


def short_label(name, n):
    """Fit a label to n chars of the shadow font: drop an 'LFO1 >' style prefix (the frame
    title already says it), keep only glyphs the font has, then truncate."""
    t = name.split(">")[-1].strip().upper()
    t = "".join(c if c.isalnum() or c in " .-/%+:#" else " " for c in t)
    return " ".join(t.split())[:n]


def widget_line(p, kind, cx, y0, width):
    lab = short_label(p.get("name") or p["key"], 10 * width)
    cy = y0 + 150
    if kind == "knob":
        return 'knob cx=%d cy=%d r=36 label="%s" key=%s' % (cx, cy - 20, lab, p["key"])
    if kind == "toggle":
        return 'toggle cx=%d cy=%d label="%s" key=%s' % (cx, cy - 20, lab, p["key"])
    if kind == "button":
        return 'button cx=%d cy=%d label="%s" key=%s' % (cx, cy - 20, lab[:7], p["key"])
    if kind == "enum_v":
        opts = ",".join(short_label(str(o), 8) or "-" for o in p["options"])
        top = y0 + 76   # below the frame title and the selector's own label
        return 'enum_v cx=%d cy=%d label="%s" key=%s options="%s"' % (cx, top + len(p["options"]) * 16, lab, p["key"], opts)
    if kind == "enum_h":   # two columns of 66 px segments, option names squeezed to 4 chars
        opts = ",".join(short_label(str(o), 12).replace(" ", "")[:4] or "-" for o in p["options"])
        rows = (len(p["options"]) + 1) // 2
        return 'enum_h cx=%d cy=%d label="%s" key=%s options="%s" sw=66 rows=%d' % (cx, y0 + 92, lab, p["key"], opts, rows)
    w = width * SLOT_W - 24
    return '%s cx=%d cy=%d w=%d h=48 label="%s" key=%s' % (kind, cx, cy, w, lab, p["key"])


# ---------------------------------------------------------------- conf <-> svg

def conf_line(w):
    """Widget dict -> layout line (inverse of shadow_skin.parse_layout)."""
    parts = [w["kind"]]
    for k in GEOM_KEYS + ("rows", "cols", "th", "gap"):
        if k in w:
            parts.append("%s=%d" % (k, w[k]))
    for k, v in w.items():
        if k in GEOM_KEYS + ("kind", "rows", "cols", "th", "gap"):
            continue
        if k == "options":
            v = ",".join(v)
        parts.append('%s="%s"' % (k, v) if (" " in str(v) or k in ("label", "title", "options")) else "%s=%s" % (k, v))
    return " ".join(parts)


def shape_for(w, base_dir="."):
    """Widget (shadow coords) -> (svg tag, attrs) in plugin coords. base_dir: the layout's folder (image looks
    size toggles and buttons)."""
    k = w["kind"]
    if k in ("frame", "picture") or (k == "art" and "w" in w):
        return "rect", dict(x=w["x"], y=w["y"] - Y_OFF, width=w["w"], height=w["h"])
    if k == "knob":
        return "circle", dict(cx=w["cx"], cy=w["cy"] - Y_OFF, r=w["r"])
    if k == "list":
        return "rect", dict(x=w["x"], y=w["y"] - Y_OFF, width=w["w"], height=w["h"])
    if k in ("readout", "stepper", "slider_v", "slider_h", "menu", "popup", "meter"):
        return "rect", dict(x=w["cx"] - w["w"] / 2, y=w["cy"] - w["h"] / 2 - Y_OFF, width=w["w"], height=w["h"])
    if k == "toggle" and shadow_skin.look_of(w, base_dir):
        x, y, tw, th = shadow_skin.toggle_rect(w, base_dir)
        return "rect", dict(x=x, y=y - Y_OFF, width=tw, height=th)
    if k == "toggle":
        return "rect", dict(x=w["cx"] - 25.5, y=w["cy"] - 13.5 - Y_OFF, width=51, height=27)
    if k == "button":
        x, y, bw, bh = shadow_skin.button_rect(w, base_dir)
        return "rect", dict(x=x, y=y - Y_OFF, width=bw, height=bh)
    if k in ("enum_h", "enum_v"):
        rs = shadow_skin.seg_rects(w)
        x0, y0 = min(r[0] for r in rs), min(r[1] for r in rs)
        x1, y1 = max(r[0] + r[2] for r in rs), max(r[1] + r[3] for r in rs)
        return "rect", dict(x=x0, y=y0 - Y_OFF, width=x1 - x0, height=y1 - y0)
    if k == "text":
        x, y, bw, bh = shadow_skin.text_box(w)
        return "rect", dict(x=x + 4, y=y + 4 - Y_OFF, width=bw - 8, height=bh - 8)
    raise ValueError(k)


STYLE = {"frame": "fill:none;stroke:#8f8a78;stroke-width:2",
         "knob": "fill:#e9e4d3;stroke:#3a352c;stroke-width:3",
         "default": "fill:#c7c2b0;fill-opacity:0.6;stroke:#2f4a6b;stroke-width:2"}


SKIP_TAGS = ("desc", "title", "metadata", "namedview", "defs")


def art_children(path):
    """An art file's drawing elements (for to-svg to put back into the layer)."""
    root = ET.parse(path).getroot()
    return [ch for ch in root if ch.tag.split("}")[-1] not in ("metadata", "namedview", "title", "desc")]


def to_svg(conf_path, params_path=None):
    tabs, top = shadow_skin.parse_layout(conf_path)
    conf_dir = os.path.dirname(os.path.abspath(conf_path))
    opts = {}
    if params_path:
        for p in load_params(params_path)[0]:
            if p.get("options"):
                opts[p["key"]] = [str(o).upper() for o in p["options"]]
    shadow_skin.apply_theme(top)
    root = ET.Element("{%s}svg" % SVG_NS, {"width": str(W), "height": str(H), "viewBox": "0 0 %d %d" % (W, H)})
    ET.SubElement(root, "{%s}desc" % SVG_NS).text = "\n".join(top)   # style/theme lines ride along
    ET.SubElement(root, "{%s}rect" % SVG_NS, {"x": "0", "y": "0", "width": str(W), "height": str(H),
                                              "style": "fill:#%s" % shadow_skin.PLATE, LABEL: "page background"})
    for t, tab in enumerate(tabs):
        layer = ET.SubElement(root, "{%s}g" % SVG_NS, {GROUPMODE: "layer", LABEL: "tab " + tab["name"], "id": "tab%d" % t})
        if t:
            layer.set("style", "display:none")
        ET.SubElement(layer, "{%s}desc" % SVG_NS).text = "\n".join(
            'qlinks "%s" = %s' % (n, ",".join(ks)) for n, ks in tab["qlinks"])
        for i, w in enumerate(tab["widgets"]):
            if w["kind"] == "art" and ("w" in w or not w["file"].lower().endswith(".svg")):
                # a placed or bitmap image: linked, its line (file= included) on the group
                box = (w["x"], w["y"] - Y_OFF, w["w"], w["h"]) if "w" in w else (0, 0, W, H)
                g = ET.SubElement(layer, "{%s}g" % SVG_NS, {LABEL: strip_geom(conf_line(w)), "id": "t%dw%d" % (t, i)})
                ET.SubElement(g, "{%s}image" % SVG_NS, {"href": w["file"], "x": str(box[0]), "y": str(box[1]),
                                                         "width": str(box[2]), "height": str(box[3])})
                continue
            if w["kind"] == "art":   # the drawing itself, editable; the group's label keeps any when=
                rest = {k: v for k, v in w.items() if k != "file"}
                g = ET.SubElement(layer, "{%s}g" % SVG_NS, {LABEL: conf_line(rest), "id": "t%dw%d" % (t, i)})
                g.extend(art_children(os.path.join(conf_dir, w["file"])))
                continue
            if w["kind"].startswith("enum") and not w.get("options") and w.get("key") in opts:
                w["options"] = opts[w["key"]]
            tag, attrs = shape_for(w, conf_dir)
            label = strip_geom(conf_line(w))
            if w["kind"] == "enum_h" and not w.get("options"):   # no option count to recompute sw from
                label += " sw=%d" % (w.get("sw") or 117)
            g = ET.SubElement(layer, "{%s}g" % SVG_NS, {LABEL: label, "id": "t%dw%d" % (t, i)})
            a = {k: str(v) for k, v in attrs.items()}
            a["style"] = STYLE.get(w["kind"], STYLE["default"])
            ET.SubElement(g, "{%s}%s" % (SVG_NS, tag), a)
            txt = w.get("title") or w.get("label") or w.get("key", "")
            tx = attrs.get("cx", attrs.get("x", 0) + attrs.get("width", 0) / 2)
            ty = (attrs.get("cy", 0) + attrs.get("r", 0) + 16) if tag == "circle" else attrs["y"] - 4
            if w["kind"] == "frame":
                tx, ty = attrs["x"] + 12, attrs["y"] + 20
            e = ET.SubElement(g, "{%s}text" % SVG_NS, {"x": str(tx), "y": str(ty),
                                                        "style": "font:bold 13px sans-serif;fill:#%s;text-anchor:%s" % (
                                                            shadow_skin.INK, "start" if w["kind"] == "frame" else "middle")})
            e.text = txt
    return ET.tostring(root, encoding="unicode")


def strip_geom(line):
    return " ".join(t for t in shlex.split(line, posix=False) if t.split("=")[0] not in GEOM_KEYS + ("th",))


# -- svg -> conf

def parse_transform(s):
    m = [1, 0, 0, 1, 0, 0]
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "translate":
            t = [1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0]
        elif name == "scale":
            t = [v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0]
        elif name == "matrix":
            t = v
        elif name == "rotate" and len(v) == 1:
            c, sn = math.cos(math.radians(v[0])), math.sin(math.radians(v[0]))
            t = [c, sn, -sn, c, 0, 0]
        else:
            continue
        m = mul(m, t)
    return m


def mul(a, b):
    return [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3],
            a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]]


def apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def geometry(el, m):
    """First circle/ellipse/rect under el -> ('circle', cx, cy, r) or ('rect', x, y, w, h), plugin coords."""
    for node in el.iter():
        tag = node.tag.split("}")[-1]
        nm = mul(m, parse_transform(node.get("transform"))) if node is not el else m
        if tag in ("circle", "ellipse"):
            cx, cy = apply(nm, float(node.get("cx", 0)), float(node.get("cy", 0)))
            r = float(node.get("r") or node.get("rx") or 0) * math.sqrt(abs(nm[0] * nm[3] - nm[1] * nm[2]))
            return ("circle", cx, cy, r)
        if tag in ("rect", "image"):
            x, y = float(node.get("x", 0)), float(node.get("y", 0))
            w, h = float(node.get("width", 0)), float(node.get("height", 0))
            pts = [apply(nm, px, py) for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return ("rect", min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return None


def element_to_line(label, geo, base_dir="."):
    toks = shlex.split(label)
    kind, attrs = toks[0], dict(t.split("=", 1) for t in toks[1:] if "=" in t)
    w = {"kind": kind, **attrs}
    if geo[0] == "circle":
        _, cx, cy, r = geo
        x, y, gw, gh = cx - r, cy - r, 2 * r, 2 * r
    else:
        _, x, y, gw, gh = geo
        cx, cy = x + gw / 2, y + gh / 2
    Y = Y_OFF
    if kind in ("frame", "list", "picture", "art"):
        w.update(x=round(x), y=round(y + Y), w=round(gw), h=round(gh))
        if kind == "list":
            rows, gap = int(w.get("rows", 4)), int(w.get("gap", 4))
            w["th"] = round((gh - (rows - 1) * gap) / rows)
            for k in ("rows", "cols", "gap"):
                w[k] = int(w.get(k, {"rows": 4, "cols": 1, "gap": 4}[k]))
    elif kind == "knob":
        w.update(cx=round(cx), cy=round(cy + Y), r=max(12, round(gw / 2)))
    elif kind in ("readout", "stepper", "slider_v", "slider_h", "menu", "popup", "meter"):
        w.update(cx=round(cx), cy=round(cy + Y), w=round(gw), h=round(gh))
    elif kind == "enum_h":
        w.update(cx=round(cx), cy=round(cy + Y))
        if "options" in w or "n" in w:
            n = len(w["options"].split(",")) if "options" in w else int(w.pop("n"))
            rows = int(w.get("rows", 1))
            per = -(-n // rows)
            w["sw"] = max(20, round((gw - 2 * (per - 1)) / per))
    else:
        w.update(cx=round(cx), cy=round(cy + Y))
    for k in ("sw", "rows", "cols"):
        if k in w and not isinstance(w[k], int):
            w[k] = int(w[k])
    if "options" in w:
        w["options"] = w["options"].split(",")
    if "cx" in w and kind != "knob" and (kind != "enum_h" or w.get("options") or "sw" in w):
        # the anchor isn't always the shape's centre (odd sizes, multi-row selectors): place the
        # shape this anchor would draw, and shift the anchor by the difference
        _, a = shape_for(w, base_dir)
        w["cx"] += round(cx - (a["x"] + a["width"] / 2))
        w["cy"] += round(cy - (a["y"] + a["height"] / 2))
    return conf_line(w)


def matrix_attr(m):
    return "matrix(%s)" % " ".join("%g" % v for v in m)


def write_art(path, defs, parts):
    """parts: [(matrix, [elements])] -> a standalone 1280x628 SVG drawn by `art file=`."""
    root = ET.Element("{%s}svg" % SVG_NS, {"width": str(W), "height": str(H), "viewBox": "0 0 %d %d" % (W, H)})
    if len(defs):
        root.append(defs)
    for m, els in parts:
        g = ET.SubElement(root, "{%s}g" % SVG_NS, {"transform": matrix_attr(m)})
        g.extend(els)
    ET.ElementTree(root).write(path, encoding="unicode", xml_declaration=False)


def from_svg(svg_path, out_path=None):
    root = ET.parse(svg_path).getroot()
    out = ["# from %s via studio.py from-svg" % os.path.basename(svg_path)]
    out_dir = os.path.dirname(os.path.abspath(out_path or svg_path))
    stem = os.path.splitext(os.path.basename(out_path or svg_path))[0]
    defs = ET.Element("{%s}defs" % SVG_NS)   # gradients, patterns, ... wherever Inkscape put them
    for d in root.iter("{%s}defs" % SVG_NS):
        defs.extend(list(d))
    desc = root.find("{%s}desc" % SVG_NS)
    if desc is not None and desc.text:
        out += [l.strip() for l in desc.text.splitlines() if l.strip()]
    base = parse_transform(root.get("transform"))
    for layer in root.findall("{%s}g" % SVG_NS):
        lab = layer.get(LABEL, "")
        if not lab.startswith("tab "):
            continue
        out += ["", "[%s]" % lab]
        lm = mul(base, parse_transform(layer.get("transform")))
        tab_slug = re.sub("_+", "_", shadow_skin.slug(lab[4:]).lower())
        lines, loose, groups = [], [], []

        def walk(el, m):
            for ch in el:
                cm = mul(m, parse_transform(ch.get("transform")))
                l = ch.get(LABEL, "")
                kind = l.split(" ")[0]
                if kind in shadow_skin.CONTROL_KINDS + ("frame", "picture") or (kind == "art" and "file=" in l):
                    geo = geometry(ch, cm)
                    if geo:
                        lines.append(element_to_line(l, geo, out_dir))
                elif kind == "art":
                    groups.append((l, cm, list(ch)))
                elif ch.tag.endswith("}g") and not l:
                    walk(ch, cm)
                elif ch.tag.split("}")[-1] not in SKIP_TAGS:
                    loose.append((m, ch))   # a drawing: background artwork
        walk(layer, lm)
        arts = [("art", [(m, [e]) for m, e in loose])] if loose else []
        arts += [(l, [(m, els)]) for l, m, els in groups]
        for n, (l, parts) in enumerate(arts):
            name = "%s.%s.art%s.svg" % (stem, tab_slug, n or "")
            write_art(os.path.join(out_dir, name), defs, parts)
            out.append(conf_line({"kind": "art", "file": name, **dict(t.split("=", 1) for t in shlex.split(l)[1:] if "=" in t)}))
        out += lines
        d = layer.find("{%s}desc" % SVG_NS)
        if d is not None and d.text:
            out += [l.strip() for l in d.text.splitlines() if l.strip().startswith("qlinks")]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- preview

def handles(c):
    """A component's IndexedEnabling conditions: [(option index, option count, parameter index)]."""
    return [tuple(int(g) for g in m.groups()) for m in
            (re.match(r"IndexedEnabling/(\d+)/(\d+)/Parameter (\d+)$", h) for h in c["bounds"].get("additionalInvalidatingHandles", []))
            if m]


def shown(c, state):
    """Would MPC show component c with parameters at state {param index: option index} (others at 0)?"""
    return all(state.get(p, 0) == i for i, n, p in handles(c))


def preview(skin_dir, out_pattern, frame=40):
    """Composite a built skin into PNGs (what MPC should draw), one per page with every option parameter
    at its first option, plus "<page>_open" with the page's popups open and "<page>_mode<p>-<i>" for each
    other option of a parameter that switches controls (when=). Needs Pillow."""
    from PIL import Image, ImageDraw, ImageFont
    t = json.load(open(os.path.join(skin_dir, "TUI.json")))["pageData"]
    defs = {d["key"]: d["value"] for d in t["componentDefinitions"]["localComponentDefinitions"]}
    xywh = lambda b: [int(float(v)) for v in b["bounds"].split()]
    outs = []
    pages = []
    for n, tab in enumerate(t["tabs"]):
        comps = defs[tab["componentName"]]["componentsData"]
        base, ext = os.path.splitext(out_pattern % n)
        pages.append((out_pattern % n, tab, {}, ""))
        opens = {int(m.group(1)) for c in comps if c["componentData"]["type"].startswith("shPopField_")
                 for m in [re.match(r"Parameter (\d+)", c["handle remapping"]["map"][0]["value"])] if m}
        if opens:
            pages.append((base + "_open" + ext, tab, {p: 1 for p in opens}, " (popups open)"))
        modes = sorted({(p, n_) for c in comps for _, n_, p in handles(c) if p not in opens})
        for p, n_ in modes:
            for i in range(1, n_):
                pages.append(("%s_mode%d-%d%s" % (base, p, i, ext), tab, {p: i}, " (parameter %d = option %d)" % (p, i)))
    for out, tab, state, note in pages:
        im = Image.new("RGB", (W, H), (0, 0, 0))
        dr = ImageDraw.Draw(im)
        for c in defs[tab["componentName"]]["componentsData"]:
            if not shown(c, state):
                continue
            cd = c["componentData"]
            x, y, w, h = xywh(c["bounds"])
            if cd["type"] == "Image":
                img = Image.open(os.path.join(skin_dir, cd["data"]["image"])).convert("RGBA")
                im.paste(img, (x, y), img)
                continue
            for s in defs[cd["type"]]["componentsData"]:
                sd = s["componentData"]
                sx, sy, sw, sh = xywh(s["bounds"])
                if sd["type"] == "Image":
                    img = Image.open(os.path.join(skin_dir, sd["data"]["image"])).convert("RGBA")
                    im.paste(img, (x + sx, y + sy), img)
                elif sd["type"] == "Knob":
                    st = Image.open(os.path.join(skin_dir, sd["data"]["filmStrip"])).convert("RGBA")
                    fw = st.size[0]
                    fr = st.crop((0, frame * fw, fw, (frame + 1) * fw))
                    im.paste(fr, (x + sx, y + sy), fr)
                elif sd["type"] == "Button":
                    img = sd["data"]["offImage"]
                    if img:
                        img = Image.open(os.path.join(skin_dir, img)).convert("RGBA")
                        im.paste(img, (x + sx, y + sy), img)
                elif sd["type"] == "Meter":
                    # EXPERIMENTAL (docs/ROADMAP.md): a static approximation only -- draws the resting/inactive
                    # image, then the peak overlay revealed by a fixed fraction `prop` from the low end of its
                    # `direction`. This tool doesn't simulate MPC's own, unverified fill-reveal logic; the real
                    # device may draw this quite differently, if at all.
                    bg = sd["data"].get("inactiveImage")
                    if bg:
                        img = Image.open(os.path.join(skin_dir, bg)).convert("RGBA")
                        im.paste(img, (x + sx, y + sy), img)
                    peak = sd["data"].get("peakImage")
                    if peak:
                        img = Image.open(os.path.join(skin_dir, peak)).convert("RGBA")
                        prop = frame / (shadow_skin.FRAMES - 1)
                        direction = sd["data"].get("direction", "Up")
                        if direction == "Right":
                            box = (0, 0, round(sw * prop), sh)
                        elif direction == "Down":
                            box = (0, 0, sw, round(sh * prop))
                        else:   # Up: fills from the bottom
                            box = (0, sh - round(sh * prop), sw, sh)
                        crop = img.crop(box)
                        im.paste(crop, (x + sx + box[0], y + sy + box[1]), crop)
                elif sd["type"] == "Label":
                    # "Name" labels show the real, device-rendered Titillium Web text on MPC
                    # (proportional, not shadow_art.c's baked bitmap font); approximate with
                    # Pillow's own bundled scalable font so layout/spacing can be sanity-checked
                    # offline (not pixel-identical to Titillium Web -- see docs/NOTES.md).
                    # "Value" labels show a live number unavailable at preview time, so stay an
                    # outline placeholder.
                    if sd["data"].get("type") == "Name":
                        text = cd.get("name", "")
                        ts = sd["data"]["textStyle"]
                        colour = ts["colour"]
                        rgb = tuple(int(colour[i:i + 2], 16) for i in (2, 4, 6)) if len(colour) >= 8 else (200, 200, 200)
                        font = ImageFont.load_default(size=int(ts["font"]["height"]))
                        bbox = dr.textbbox((0, 0), text, font=font)
                        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                        dr.text((x + sx + (sw - tw) // 2 - bbox[0], y + sy + (sh - th) // 2 - bbox[1]),
                                text, font=font, fill=rgb)
                    else:
                        dr.rectangle([x + sx, y + sy, x + sx + sw - 1, y + sy + sh - 1], outline=(70, 110, 160))
        for c, rect in enumerate(tab["qlinkBoundsData"]):   # one per Q-Link column, numbered
            qx, qy, qw, qh = [int(v) for v in rect.split()]
            if qw and qh:
                dr.rectangle([qx, qy, qx + qw, qy + qh], outline=(80, 200, 120))
                dr.text((qx + 4, qy + 2), str(c + 1), fill=(80, 200, 120))
        im.save(out)
        outs.append((out, tab["tabName"] + note))
    return outs


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auto"); a.add_argument("params"); a.add_argument("-o", required=True)
    s = sub.add_parser("to-svg"); s.add_argument("conf"); s.add_argument("-o", required=True)
    s.add_argument("--params", help="the port's parameter file, to fill in omitted option lists")
    f = sub.add_parser("from-svg"); f.add_argument("svg"); f.add_argument("-o", required=True)
    p = sub.add_parser("preview"); p.add_argument("skin"); p.add_argument("-o", required=True)
    w = sub.add_parser("serve", help="edit a layout in the browser (tools/studio_web.py)")
    w.add_argument("conf", nargs="?", help="a layout.conf or a port's vst.json (default: choose in the browser)")
    w.add_argument("--params", help="the port's parameter file (found from vst.json when not given)")
    w.add_argument("--host", default="127.0.0.1"); w.add_argument("--port", type=int, default=8765)
    w.add_argument("--open", action="store_true", help="open the editor in the default browser")
    args = ap.parse_args()
    if args.cmd == "serve":
        import studio_web
        return studio_web.serve(args.conf, args.params, args.host, args.port, args.open)
    if args.cmd == "auto":
        params, sections = load_params(args.params)
        open(args.o, "w").write(auto_layout(params, sections))
    elif args.cmd == "to-svg":
        open(args.o, "w").write(to_svg(args.conf, args.params))
    elif args.cmd == "from-svg":
        open(args.o, "w").write(from_svg(args.svg, args.o))
    else:
        for out, name in preview(args.skin, args.o):
            print(out, name)
    print("wrote", args.o)


if __name__ == "__main__":
    main()
