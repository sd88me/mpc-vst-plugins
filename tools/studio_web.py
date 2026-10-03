#!/usr/bin/env python3
"""Skin studio in the browser: a local editor for layout.conf (`studio.py serve`).

    studio.py serve [layout.conf | vst.json] [--params params.json] [--open] [--port 8765] [--host 127.0.0.1]

Without a layout the page opens on a start screen (recent layouts, a folder browser, new layouts); a port's
vst.json opens its layout with its parameters. The launchers at the repo root (SkinStudio.command / .bat / .sh)
run `serve --open`, so a double-click opens the editor in the default browser.

Serves tools/studio_web/ and a small JSON API. The page edits the layout; this side reads and writes it and
draws every widget with the browser renderer's own SVG (html_art.Art, styled by tools/html_art/default.css and
the layout's art_css=), so the canvas shows what `"art": "html"` bakes. The shadow_art renderer (the default)
draws the same geometry with its bitmap font; `studio.py preview` on a built skin shows that exactly.

Only the layout's own folder is served (/files/...) and written (save, CSS, uploads); writes need an X-Studio
header, which a page from another site can't send without a CORS preflight this server never answers.
Standard library only.

API (JSON):
  GET  /api/doc                      the layout as a document (below), the parameters, renderer defaults;
                                     {open: true, recent, ...} when no layout is open yet
  POST /api/browse {dir}             a folder's subfolders and layout / vst.json / parameter files
  POST /api/open {path, params, create}  edit a .conf or a port's vst.json (create: "empty" | "auto")
  POST /api/quit                     stop the server
  POST /api/render {head, widgets}   -> {vars, td3, css, items: [{svg, live, box, open, alts, warn}]} per widget
  POST /api/parse  {line}            -> {w} (a widget line typed by hand)
  POST /api/save   {head, tabs}      writes the layout (x.new, then renamed over it; the first save keeps x.bak)
  POST /api/file   {name, text}      writes a text file next to the layout (the art_css stylesheet)
  POST /api/upload?name=F            raw body -> a file next to the layout, or in one folder (images/x.png):
                                     images (tools/skin_assets.py), fonts, stylesheets

Document: {head: [raw lines before the first tab], tabs: [{name, lines: [item]}]}, where an item is
{t: "w", w: {...}, raw} (a widget), {t: "q", title, keys, raw} (a qlinks line) or {t: "x", raw} (comments,
blank lines). An item whose fields still match its raw line is written back as that line, so loading and
saving without edits reproduces the file exactly.
"""
import base64
import copy
import json
import os
import re
import sys
import threading
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import html_art  # noqa: E402
import shadow_skin  # noqa: E402
import skin_assets  # noqa: E402
import studio  # noqa: E402

WEB = os.path.join(HERE, "studio_web")
Y_OFF, W, H = shadow_skin.Y_OFF, shadow_skin.W, shadow_skin.H
THEME_GLOBALS = ("TD3", "FONT_LABEL_PATH") + tuple(shadow_skin.THEME_KEYS.values())
DEFAULTS = {k: getattr(shadow_skin, k) for k in THEME_GLOBALS}
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
         ".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2", ".png": "image/png",
         ".json": "application/json", ".conf": "text/plain", ".txt": "text/plain", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


# ---------------------------------------------------------------- the layout as a document

def load_doc(path):
    head, tabs = [], []
    for raw in open(path, encoding="utf-8").read().split("\n"):
        line = raw.strip()
        m = re.match(r"\[tab (.+)\]$", line)
        if m:
            tabs.append({"name": m.group(1).strip(), "raw": raw, "lines": []})
        elif not tabs:
            head.append(raw)
        elif not line or line.startswith("#") or line.startswith("qlinks_track"):
            tabs[-1]["lines"].append({"t": "x", "raw": raw})
        elif line.startswith("qlinks"):
            m = re.match(r'qlinks\s+"([^"]+)"\s*=\s*(.+)$', line)
            tabs[-1]["lines"].append({"t": "q", "title": m.group(1), "raw": raw,
                                      "keys": [k.strip() for k in m.group(2).split(",") if k.strip()]})
        else:
            tabs[-1]["lines"].append({"t": "w", "w": shadow_skin.parse_widget(line), "raw": raw})
    if tabs and tabs[-1]["lines"] and tabs[-1]["lines"][-1] == {"t": "x", "raw": ""}:
        tabs[-1]["lines"].pop()   # the file's final newline
    elif not tabs and head and head[-1] == "":
        head.pop()
    return {"head": head, "tabs": tabs}


def item_line(it):
    if it["t"] == "x":
        return it["raw"]
    if it["t"] == "q":
        line = 'qlinks "%s" = %s' % (it["title"], ",".join(it["keys"]))
        old = re.match(r'\s*qlinks\s+"([^"]+)"\s*=\s*(.+)$', it.get("raw") or "")
        if old and old.group(1) == it["title"] and [k.strip() for k in old.group(2).split(",") if k.strip()] == it["keys"]:
            return it["raw"]
        return line
    w = it["w"]
    if it.get("raw"):
        try:
            if shadow_skin.parse_widget(it["raw"].strip()) == w:
                return it["raw"]
        except ValueError:
            pass
    return studio.conf_line(w)


def dump_doc(doc):
    out = list(doc["head"])
    for tab in doc["tabs"]:
        m = re.match(r"\s*\[tab (.+)\]\s*$", tab.get("raw") or "")
        out.append(tab["raw"] if m and m.group(1).strip() == tab["name"] else "[tab %s]" % tab["name"])
        out += [item_line(it) for it in tab["lines"]]
    return "\n".join(out) + "\n"


def write_file(path, data):
    """x.new, then renamed over x; the first write ever keeps the original as x.bak."""
    mode = "wb" if isinstance(data, bytes) else "w"
    if os.path.exists(path) and not os.path.exists(path + ".bak"):
        with open(path, "rb") as src, open(path + ".bak", "wb") as bak:
            bak.write(src.read())
    with open(path + ".new", mode, **({} if mode == "wb" else {"encoding": "utf-8"})) as f:
        f.write(data)
    os.replace(path + ".new", path)


# ---------------------------------------------------------------- drawing widgets

def set_theme(head, base_dir="."):
    """shadow_skin's palette and look defaults for these top-level lines (from its defaults, so removed lines
    take effect), and an Art that links images through /files/ (or inlines ones outside the layout's folder)."""
    for k, v in DEFAULTS.items():
        setattr(shadow_skin, k, v)
    lines = [l.strip() for l in head if l.strip() and not l.strip().startswith("#") and "=" in l]
    root = os.path.realpath(base_dir)

    def href(path):
        real = os.path.realpath(path)
        if real.startswith(root + os.sep):
            return "/files/%s?v=%d" % (quote(os.path.relpath(real, root).replace(os.sep, "/")), int(os.path.getmtime(real)))
        with open(real, "rb") as f:
            return "data:%s;base64,%s" % (skin_assets.MIME.get(os.path.splitext(real)[1].lower(), "image/png"),
                                           base64.b64encode(f.read()).decode())
    art = html_art.Art(href=href)
    art.theme_lines([l for l in lines if not l.startswith("font_label=")])
    return art, lines


def live_text(x, y, w, h, text, size, colour, anchor="middle"):
    """MPC's own text (Titillium Web, drawn on the device over the skin): shown in the editor only."""
    tx = {"start": x, "middle": x + w / 2, "end": x + w}[anchor]
    return ('<text class="live" x="%g" y="%g" text-anchor="%s" dominant-baseline="central" '
            'style="font-size:%gpx;fill:#%s">%s</text>') % (tx, y + h / 2, anchor, size, colour, escape(text))


def resolve(w, params):
    """A copy of w with the options the builder would use (the parameter's, when the line gives none)."""
    w = copy.deepcopy(w)
    p = params.get(w.get("key"), {})
    if w["kind"] in ("enum_h", "enum_v", "popup") and not w.get("options"):
        opts = [str(o) for o in p.get("options") or []] or ["ONE", "TWO", "THREE"]
        w["options"] = [o.upper() for o in opts] if w["kind"] != "popup" else opts
    return w


def box_of(w, base_dir):
    k = w["kind"]
    if k == "art" and "w" not in w:
        return [0, Y_OFF, W, H]
    if k in ("frame", "list", "picture", "art"):
        return [w["x"], w["y"], w["w"], w["h"]]
    _, a = studio.shape_for(w, base_dir)
    return [a.get("x", a.get("cx", 0) - a.get("r", 0)), a.get("y", a.get("cy", 0) - a.get("r", 0)) + Y_OFF,
            a.get("width", 2 * a.get("r", 0)), a.get("height", 2 * a.get("r", 0))]


def widget_svg(w, art, params, base_dir):
    """-> {svg, live, box, open, alts, warn} for one widget, in shadow coords: the baked drawing, MPC's live text,
    the selection box, a popup's open list, a picture's image per option, a look that can't be built."""
    ss = shadow_skin
    w = resolve(w, params)
    k, p = w["kind"], params.get(w.get("key"), {})
    art.ops = []
    live, opened, alts, warn = [], "", [], ""
    name = w.get("label") or p.get("name") or w.get("key", "")
    first = (w.get("options") or [""])[0]
    lk = ss.look_of(w, base_dir)
    if lk:
        warn = skin_assets.check(w, lk) or ""
        if warn:
            lk = None
    if k == "art":
        for c in ss.baked_cmds(w, None, base_dir) if os.path.isfile(os.path.join(base_dir, w.get("file", ""))) else []:
            art.run(c)
    elif k == "picture":
        for f in [x.strip() for x in w.get("files", "").split(",") if x.strip()]:
            path = os.path.join(base_dir, f)
            alts.append(art.image(path, w["x"], w["y"], w["w"], w["h"], w.get("fit", "contain")) if os.path.isfile(path) else "")
    elif k in ("frame", "readout", "stepper", "menu", "popup", "list", "text"):
        for c in ss.baked_cmds(w, None, base_dir):
            art.run(c)
    if k == "knob":
        r = w["r"]
        s, cw = 2 * r + 10, max(130, 2 * r + 10)
        x0, y0 = w["cx"] - cw // 2, w["cy"] - s // 2
        art.ops.append(art.knob_frame(w["cx"], w["cy"], r, 40, lk))
        live += [live_text(x0, y0 + s // 2 + r + 2, cw, 20, name, 17, ss.INK),
                 live_text(x0, y0 + s // 2 + r + 24, cw, 26, "40", 22, ss.INK_DIM)]
    elif k == "meter" and lk and lk.get("look") == "native":
        # EXPERIMENTAL (docs/ROADMAP.md): static preview only -- the background image, then the peak image at a
        # fixed proportion (like studio.py preview, not a simulation of MPC's own unverified reveal logic)
        mw, mh = w["w"], w["h"]
        x0, y0 = w["cx"] - mw // 2, w["cy"] - mh // 2
        if lk.get("img"):
            art.ops.append(art.image(lk["img"], x0, y0, mw, mh, "stretch"))
        if lk.get("peak"):
            direction = w.get("direction", "up").lower()
            if direction == "right":
                bx, by, bw, bh = x0, y0, round(mw * 0.4), mh
            elif direction == "down":
                bx, by, bw, bh = x0, y0, mw, round(mh * 0.4)
            else:
                bx, by, bw, bh = x0, y0 + round(mh * 0.6), mw, mh - round(mh * 0.6)
            art.ops.append('<svg x="%d" y="%d" width="%d" height="%d" overflow="hidden">%s</svg>' % (
                bx, by, bw, bh, art.image(lk["peak"], x0 - bx, y0 - by, mw, mh, "stretch")))
    elif k in ("slider_v", "slider_h", "meter"):
        sw_, sh_ = w["w"], w["h"]
        sq, cw = max(sw_, sh_), max(130, max(sw_, sh_))
        x0, y0 = w["cx"] - cw // 2, w["cy"] - sq // 2
        art.ops.append(art.slider_frame(w["cx"] - sw_ // 2, w["cy"] - sh_ // 2, sw_, sh_, k != "slider_h", 0.4, lk)
                       if lk or k != "meter" else
                       '<rect x="%d" y="%d" width="%d" height="%d" style="fill:none;stroke:#%s;stroke-dasharray:4 3"/>' % (
                           w["cx"] - sw_ // 2, w["cy"] - sh_ // 2, sw_, sh_, ss.INK_DIM))
        if k != "meter":
            name_y = y0 + (sq - sh_) // 2 + sh_ + 2
            live += [live_text(x0, name_y, cw, 20, name, 17, ss.INK), live_text(x0, name_y + 22, cw, 26, "40", 22, ss.INK_DIM)]
    elif k == "toggle" and lk:
        x, y, tw, th = ss.toggle_rect(w, base_dir)
        art.ops.append(art.toggle_frame(x + tw / 2, y + th / 2, 0, tw, th, lk))
        live.append(live_text(w["cx"] - 60, y + th + 4, 120, 20, name, 15, ss.INK))
    elif k == "toggle":
        art.run("pill|%d|%d|0" % (w["cx"], w["cy"]))
        live.append(live_text(w["cx"] - 60, w["cy"] - 18 + 34, 120, 20, name, 15, ss.INK))
    elif k == "button" and lk:
        x, y, bw, bh = ss.button_rect(w, base_dir)
        art.ops.append(art.button_frame(x, y, bw, bh, 0, w.get("label", ""), lk))
    elif k == "button":
        art.run("button|%d|%d|%s|%s" % (w["cx"], w["cy"], w.get("color") or ss.BTN_BG or ss.ACCENT, w.get("label", "")))
    elif k in ("enum_h", "enum_v"):
        for c in ss.label_cmds(w):
            art.run(c)
        for o, (x, y, sw, sh) in enumerate(ss.seg_rects(w)):
            on = o == 0
            if lk:
                art.ops.append(art.seg_frame(x, y, sw, sh, on, ss.SEG_ON_TX if on else ss.INK, w["options"][o], lk))
            else:
                art.run("seg|%d|%d|%d|%d|%s|%s|%s" % (x, y, sw, sh, ss.SEG_ON if on else ss.SEG_OFF,
                                                      ss.SEG_ON_TX if on else ss.INK_DIM, w["options"][o]))
    elif k in ("readout", "menu", "popup"):
        x, y, rw, rh = w["cx"] - w["w"] // 2, w["cy"] - w["h"] // 2, w["w"], w["h"]
        dot = k == "readout" and w.get("style") == "dotmatrix"
        live.append(live_text(x + 8, y, rw - (44 if k == "popup" else 16), rh, first if k != "readout" else name,
                              26, ss.DISPLAY_INK if dot else ss.ACCENT))
        if k == "popup":
            cx, cy = w["cx"] + w["w"] // 2 - 22, w["cy"]
            art.ops.append('<path d="M%d %d L%d %d L%d %d Z" style="fill:#%s"/>' % (
                cx - 8, cy - 4, cx + 8, cy - 4, cx, cy + 5, ss.ACCENT))
            (px, py, pw, ph), orects = ss.popup_panel(w)
            ops, art.ops = art.ops, []
            if lk:
                art.ops.append(art.image(lk["img"], px, py, pw, ph, "stretch"))
            else:
                art.run("tile|%d|%d|%d|%d|%s|%s|2" % (px, py, pw, ph, ss.LCD, ss.ACCENT))
            for o, (ox, oy, ow, oh) in enumerate(orects):
                on = o == 0
                art.run("seg|%d|%d|%d|%d|%s|%s|%s" % (ox, oy, ow, oh, ss.SEG_ON if on else ss.LCD,
                                                      ss.SEG_ON_TX if on else ss.INK, w["options"][o]))
            opened, art.ops = "".join(art.ops), ops
    elif k == "stepper":
        h = w["h"]
        x0, y0 = w["cx"] - w["w"] // 2, w["cy"] - h // 2
        dot = w.get("style") == "dotmatrix"
        live.append(live_text(x0 + h + 11, y0, w["w"] - 2 * h - 22, h, name, 26, ss.DISPLAY_INK if dot else ss.ACCENT))
    elif k == "list":
        for (x, y, tw, th), sk in zip(ss.list_tiles(w), ss.list_keys(w)):
            live.append(live_text(x + 12, y, tw - 24, th, sk.replace("_", " "), 24, ss.ACCENT, "start"))
    try:
        box = box_of(w, base_dir)
    except (KeyError, ValueError):
        box = None
    return {"svg": "".join(art.ops), "live": "".join(live), "box": box, "open": opened, "alts": alts, "warn": warn}


def render(head, widgets, params, base_dir):
    art, lines = set_theme(head, base_dir)
    items = []
    for w in widgets:
        try:
            items.append(widget_svg(w, art, params, base_dir))
        except Exception as e:   # a half-typed line: show the error on that widget, keep the rest
            msg = "needs %s=" % e.args[0] if isinstance(e, KeyError) else "%s: %s" % (type(e).__name__, e)
            items.append({"svg": "", "live": "", "box": None, "open": "", "alts": [], "error": msg})
    vars_ = ";".join("--%s:%s" % (k.replace("_", "-"), html_art.hexc(v)) for k, v in art.theme.items())
    css = [l.partition("=")[2].strip() for l in lines if l.startswith("art_css=")]
    return {"vars": vars_, "td3": art.td3, "css": css, "items": items}


# ---------------------------------------------------------------- server

RECENT = os.path.join(os.path.expanduser("~"), ".mpc-skin-studio.json")
REPO = os.path.dirname(HERE)


def load_recent():
    try:
        with open(RECENT, encoding="utf-8") as f:
            return [r for r in json.load(f).get("recent", []) if os.path.isfile(r.get("layout", ""))]
    except (OSError, ValueError, AttributeError):
        return []


def remember(layout, params_path):
    rs = [r for r in load_recent() if r["layout"] != layout]
    rs.insert(0, {"layout": layout, "params": params_path or ""})
    try:
        with open(RECENT, "w", encoding="utf-8") as f:
            json.dump({"recent": rs[:12]}, f, indent=1)
    except OSError:
        pass


def port_config(path):
    """A port's vst.json -> (layout path or None, params path or None), both absolute."""
    here = os.path.dirname(os.path.abspath(path))
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    src = cfg.get("params") or cfg.get("module")
    return (os.path.join(here, cfg["layout"]) if cfg.get("layout") else None,
            os.path.join(here, src) if src else None)


def find_params(layout):
    """The parameter file that goes with a layout: the vst.json that names it (in its folder, the two above,
    or a folder directly inside one of those), else <stem>.params.json or params.json next to it."""
    layout = os.path.abspath(layout)
    d = os.path.dirname(layout)
    ups = [d, os.path.dirname(d), os.path.dirname(os.path.dirname(d))]
    near = []
    for up in ups:
        near.append(up)
        try:
            near += [os.path.join(up, n) for n in sorted(os.listdir(up)) if not n.startswith(".")]
        except OSError:
            pass
    for folder in dict.fromkeys(near):
        cfg = os.path.join(folder, "vst.json")
        if not os.path.isfile(cfg):
            continue
        try:
            lay, par = port_config(cfg)
        except (OSError, ValueError, KeyError):
            continue
        if lay and os.path.realpath(lay) == os.path.realpath(layout) and par and os.path.isfile(par):
            return par
    for name in (os.path.splitext(os.path.basename(layout))[0] + ".params.json", "params.json"):
        if os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


class Studio:
    def __init__(self):
        self.layout = self.dir = None
        self.params_path, self.params, self.sections, self.by_key = None, [], [], {}

    def open(self, layout, params_path=None):
        """Edit this layout (created when missing) with these parameters (found when not given)."""
        self.layout = os.path.abspath(layout)
        self.dir = os.path.dirname(self.layout)
        self.params_path = os.path.abspath(params_path) if params_path else find_params(self.layout)
        self.params, self.sections = [], []
        if self.params_path:
            ps, secs = studio.load_params(self.params_path)
            self.params = [{"key": p["key"], "name": p.get("name", p["key"]), "options": [str(o) for o in p.get("options") or []],
                            "hint": studio.kind_for(p)} for p in ps]
            self.sections = secs or []
        self.by_key = {p["key"]: p for p in self.params}
        remember(self.layout, self.params_path)

    def local(self, name):
        """A path inside the layout's folder, or None."""
        if not self.dir:
            return None
        path = os.path.realpath(os.path.join(self.dir, unquote(name)))
        return path if path == self.dir or path.startswith(self.dir + os.sep) else None

    def files(self, exts):
        """Files with these extensions under the layout's folder (for the page's pickers)."""
        out = []
        for root, dirs, names in os.walk(self.dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("build", "node_modules")]
            out += [os.path.join(root, n) for n in sorted(names) if os.path.splitext(n)[1].lower() in exts]
            if len(out) > 200:
                break
        return out

    def start(self):
        """What the start screen needs: recent layouts and where to browse from."""
        rs = load_recent()
        return {"open": True, "recent": rs, "home": os.path.expanduser("~"), "repo": REPO,
                "template": os.path.join(HERE, "skin_template.conf"), "sep": os.sep,
                "dir": os.path.dirname(rs[0]["layout"]) if rs else os.path.dirname(REPO)}

    def doc(self):
        if not self.layout:
            return self.start()
        if not os.path.exists(self.layout):
            d = {"head": [], "tabs": [{"name": "PAGE 1", "raw": "", "lines": []}]}
        else:
            d = load_doc(self.layout)
        d.update(path=self.layout, name=os.path.basename(self.layout), params=self.params, sections=self.sections,
                 params_path=self.params_path, theme=html_art.THEME, defs=html_art.DEFS,
                 css=[os.path.relpath(p, self.dir) for p in self.files((".css",))],
                 art=[os.path.relpath(p, self.dir) for p in self.files((".svg",))],
                 images=[dict(zip(("name", "w", "h"), (os.path.relpath(p, self.dir).replace(os.sep, "/"),) + tuple(skin_assets.image_size(p))))
                         for p in self.files(skin_assets.IMAGE_EXTS)],
                 looks=skin_assets.LOOKS, groups=skin_assets.GROUP,
                 fonts=[os.path.relpath(p, self.dir) for p in self.files((".ttf", ".otf", ".woff", ".woff2"))],
                 plugin={"w": W, "h": H, "y": Y_OFF})
        return d


def browse(path):
    """A folder's subfolders and the files the start screen can open."""
    path = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(path):
        path = os.path.dirname(path)
    dirs, files = [], []
    for n in sorted(os.listdir(path), key=str.lower):
        if n.startswith(".") or n in ("node_modules", "__pycache__"):
            continue
        full = os.path.join(path, n)
        ext = os.path.splitext(n)[1].lower()
        if os.path.isdir(full):
            dirs.append(n)
        elif n == "vst.json":
            files.append({"name": n, "kind": "port"})
        elif ext == ".conf":
            files.append({"name": n, "kind": "layout"})
        elif ext == ".json":
            files.append({"name": n, "kind": "params"})
    parent = os.path.dirname(path)
    return {"dir": path, "parent": parent if parent != path else None, "dirs": dirs, "files": files}


def open_request(st, req):
    """POST /api/open: {path (a .conf or a port's vst.json), params?, create?: "" | "empty" | "auto"}."""
    path = os.path.abspath(os.path.expanduser(req["path"]))
    params_path = req.get("params") or None
    note = ""
    if os.path.basename(path) == "vst.json":
        lay, par = port_config(path)
        params_path = params_path or par
        if not lay:
            lay = os.path.join(os.path.dirname(path), "layout.conf")
            note = 'vst.json has no "layout": add "layout": "layout.conf" to it so the build uses this file.'
        path = lay
        if not os.path.exists(path):
            req["create"] = req.get("create") or ("auto" if params_path else "empty")
    if req.get("create"):
        if os.path.exists(path):
            raise ValueError("%s already exists: open it instead" % path)
        if not path.endswith(".conf"):
            raise ValueError("a layout file name ends in .conf")
        text = "[tab PAGE 1]\n"
        if req["create"] == "auto":
            params_path = params_path or find_params(path)
            if not params_path:
                raise ValueError("a layout from parameters needs a parameter file")
            text = studio.auto_layout(*studio.load_params(params_path))
        write_file(path, text)
    elif not os.path.isfile(path):
        raise ValueError("no such file: %s" % path)
    st.open(path, params_path)
    d = st.doc()
    d["note"] = note
    return d


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
UPLOADS = skin_assets.IMAGE_EXTS + (".ttf", ".otf", ".woff", ".woff2", ".css")


def handler(st, host, stop):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            if "/api/" in (a[0] if a else ""):
                return
            sys.stderr.write("studio: " + fmt % a + "\n")

        def send(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes):
                body = (json.dumps(body) if ctype == "application/json" else body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or "json" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def host_ok(self):
            """Only requests addressed to this machine by name or loopback address (no DNS rebinding)."""
            h = self.headers.get("Host") or ""
            h = h[1:h.find("]")] if h.startswith("[") else h.split(":")[0]
            return h in LOCAL_HOSTS or h == host

        def static(self, root, rel):
            if not root:
                return self.send(404, {"error": "no layout open"})
            path = os.path.realpath(os.path.join(root, unquote(rel)))
            if not (path.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(path)):
                return self.send(404, {"error": "not found"})
            with open(path, "rb") as f:
                self.send(200, f.read(), TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, {"error": "bad Host"})
            u = urlparse(self.path)
            if u.path == "/api/doc":
                return self.send(200, st.doc())
            if u.path == "/":
                return self.static(WEB, "index.html")
            for prefix, root in (("/web/", WEB), ("/html_art/", os.path.join(HERE, "html_art")), ("/files/", st.dir)):
                if u.path.startswith(prefix):
                    return self.static(root, u.path[len(prefix):])
            self.send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            # a custom header: another site's page can't send it without a CORS preflight, which this never answers
            if self.headers.get("X-Studio") != "1" or not self.host_ok():
                return self.send(403, {"error": "missing X-Studio header"})
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                req = json.loads(body or b"{}") if u.path != "/api/upload" else {}
                if u.path == "/api/browse":
                    return self.send(200, browse(req.get("dir")))
                if u.path == "/api/open":
                    return self.send(200, open_request(st, req))
                if u.path == "/api/start":
                    return self.send(200, st.start())
                if u.path == "/api/quit":
                    self.send(200, {"bye": True})
                    return stop()
                if not st.layout:
                    return self.send(409, {"error": "no layout open"})
                if u.path == "/api/upload":
                    # a file name, optionally in one folder ("images/knob.png"), next to the layout
                    parts = parse_qs(u.query).get("name", [""])[0].replace("\\", "/").split("/")
                    ok = 1 <= len(parts) <= 2 and all(x and not x.startswith(".") for x in parts)
                    name = "/".join(parts)
                    path = st.local(name) if ok else None
                    if not path or os.path.splitext(name)[1].lower() not in UPLOADS:
                        return self.send(400, {"error": "images (%s), fonts (.ttf .otf .woff .woff2) and .css only"
                                                        % " ".join(skin_assets.IMAGE_EXTS)})
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    write_file(path, body)
                    is_img = os.path.splitext(name)[1].lower() in skin_assets.IMAGE_EXTS
                    return self.send(200, {"name": name, "size": skin_assets.image_size(path) if is_img else None})
                if u.path == "/api/render":
                    return self.send(200, render(req.get("head", []), req.get("widgets", []), st.by_key, st.dir))
                if u.path == "/api/parse":
                    return self.send(200, {"w": shadow_skin.parse_widget(req["line"].strip())})
                if u.path == "/api/save":
                    write_file(st.layout, dump_doc(req))
                    return self.send(200, {"saved": st.layout, "doc": st.doc()})
                if u.path == "/api/file":
                    path = st.local(req.get("name", ""))
                    if not path or os.path.splitext(path)[1].lower() not in (".css", ".svg"):
                        return self.send(400, {"error": "only .css and .svg files next to the layout"})
                    write_file(path, req.get("text", ""))
                    return self.send(200, {"name": req["name"]})
            except (OSError, ValueError, KeyError, IndexError) as e:
                return self.send(400, {"error": str(e) if isinstance(e, (OSError, ValueError)) else "%s: %s" % (type(e).__name__, e)})
            except SystemExit as e:   # params.load() and friends report bad files this way
                return self.send(400, {"error": str(e)})
            self.send(404, {"error": "not found"})
    return H


def serve(layout=None, params_path=None, host="127.0.0.1", port=8765, open_browser=False):
    """Serve the editor; without a layout (or given a port's vst.json) the page starts on its open screen.
    A busy port moves on to the next free one."""
    st = Studio()
    if layout and os.path.basename(layout) == "vst.json":
        open_request(st, {"path": layout, "params": params_path})
    elif layout:
        st.open(layout, params_path)
    srv = None
    for p in list(range(port, port + 20)) + [0]:
        try:
            srv = ThreadingHTTPServer((host, p), None)
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit("studio: no free port")
    srv.RequestHandlerClass = handler(st, host, lambda: threading.Thread(target=srv.shutdown, daemon=True).start())
    url = "http://%s:%d/" % ("localhost" if host in ("127.0.0.1", "::1") else host, srv.server_address[1])
    print("Skin Studio: %s" % url)
    print("  %s" % ("editing " + st.layout if st.layout else "open a layout in the browser"))
    print("  Keep this window open while you edit. To stop: Quit in the page, Ctrl+C, or close the window.")
    sys.stdout.flush()
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    print("Skin Studio stopped.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout", nargs="?", help="a layout.conf or a port's vst.json (default: choose in the browser)")
    ap.add_argument("--params")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the editor in the default browser")
    a = ap.parse_args()
    serve(a.layout, a.params, a.host, a.port, a.open)
