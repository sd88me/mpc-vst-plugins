#!/usr/bin/env python3
"""Check a built skin (what MPC loads) for mistakes the layout checks can't see:
    skin_check.py "<skin folder>/Plugin Skins"      (or the folder holding TUI.json; exit 1 on any finding)
Reports, per page (tab / Q-Link sub-page):
  TOUCH  two controls whose touch boxes overlap while both are visible: MPC gives the touch to one of them
         (knobs and sliders carry their name and value in the box; narrow them with bw=)
  EDGE   a control's box past the 1280 x 628 plugin area
  QLINK  a Q-Link on a parameter no control on that page is bound to (turning it changes something unseen)
  OPTS   a switch group (option segments, a popup list) missing some of its options on a page
(Q-Link order against the layout is not checked: the built skin doesn't carry the layout's order.)
Controls shown in different modes (when=) or on different sub-pages (banks=) never overlap each other.
gen_vst.py runs it after every skin build and prints the findings as warnings. Idea from
saustin2010/vst_instruments' check_skin.py (docs/COMMUNITY_SKINS.md)."""
import json
import os
import sys

W, H = 1280, 628
MIN_OVERLAP = 6   # px each way: a hairline shared edge is fine


def _rect(b):
    x, y, w, h = (float(v) for v in b.split())
    return x, y, w, h


def _param(c):
    for m in c.get("handle remapping", {}).get("map", []):
        if m.get("key") == "Data" and str(m.get("value", "")).startswith("Parameter "):
            return int(m["value"].split()[1])
    return None


def pages(tui):
    """(tab, page definition components) for each page, in either skin shape (MPC OS 3.x or 2.x)."""
    pd = tui["pageData"]
    defs = {d["key"]: d["value"] for d in pd["componentDefinitions"].get("localComponentDefinitions", [])}
    for t in pd["tabs"]:
        page = t.get("componentDefinition") or defs.get(t.get("componentName"), {})
        yield t, page.get("componentsData", []), defs


def check(skin_dir):
    if not os.path.exists(os.path.join(skin_dir, "TUI.json")):   # the plugin folder (write_skin's result)
        skin_dir = os.path.join(skin_dir, "Plugin Skins")
    tui = json.load(open(os.path.join(skin_dir, "TUI.json")))
    ql = json.load(open(os.path.join(skin_dir, "Q-Links.json")))
    qpages = {(q["Tab"], q["SubTab"]): q["Q-Links"] for q in ql.get("Screen Mode Q-Links", {}).get("map", [])}
    out = []
    for t, kids, defs in pages(tui):
        where = t["tabName"]
        controls = []
        for c in kids:
            cd = c["componentData"]
            p = _param(c)
            if p is None or cd["type"] in ("Image", "Label"):
                continue
            acts = defs.get(cd["type"], {}).get("actions", [])
            if not acts:   # display-only (meters, readouts with no tap): no touch
                continue
            x, y, w, h = _rect(c["bounds"]["bounds"])
            vis = tuple(sorted(c["bounds"].get("additionalInvalidatingHandles", [])))
            controls.append((cd["name"], p, (x, y, w, h), vis))
            if x < 0 or y < 0 or x + w > W or y + h > H:
                out.append("%s: EDGE  %s (%g %g %g %g) is past the %dx%d plugin area" % (where, cd["name"], x, y, w, h, W, H))
        for i, (n1, p1, r1, v1) in enumerate(controls):
            for n2, p2, r2, v2 in controls[i + 1:]:
                if v1 != v2 and v1 and v2:   # different modes: never on screen together
                    continue
                ox = min(r1[0] + r1[2], r2[0] + r2[2]) - max(r1[0], r2[0])
                oy = min(r1[1] + r1[3], r2[1] + r2[3]) - max(r1[1], r2[1])
                if ox > MIN_OVERLAP and oy > MIN_OVERLAP and p1 != p2:
                    out.append("%s: TOUCH %s and %s overlap by %gx%g px" % (where, n1, n2, ox, oy))
        groups = {}   # (param, visibility) -> (options in the group, button ids present)
        for c in kids:
            p = _param(c)
            for sub in defs.get(c["componentData"]["type"], {}).get("componentsData", []):
                d = sub["componentData"]
                if p is not None and d["type"] == "Button" and d["data"].get("numButtonsInGroup", 1) > 1:
                    vis = tuple(sorted(c["bounds"].get("additionalInvalidatingHandles", [])))
                    g = groups.setdefault((p, vis), [d["data"]["numButtonsInGroup"], set()])
                    g[1].add(d["data"]["buttonId"])
        for (p, _), (n, ids) in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1])):
            if ids != set(range(n)):
                out.append("%s: OPTS  parameter %d shows options %s of 0..%d" % (where, p, sorted(ids), n - 1))
        bound = {p for _, p, _, _ in controls} | {_param(c) for c in kids}
        q = qpages.get((t.get("fnKeyIndex", 0) + 1, t.get("fnKeySubIndex", 0) + 1), {})
        for slot, p in sorted(q.items()):
            if isinstance(p, int) and p >= 0 and p not in bound:
                out.append("%s: QLINK %s is on parameter %d, which no control on this page shows" % (where, slot, p))
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    found = check(sys.argv[1])
    for f in found:
        print(f)
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
