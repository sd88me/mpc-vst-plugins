#!/usr/bin/env python3
"""The plugin rows (DESIGN.md 6b): writes ROWS thin rows into layout.conf and their params into params.json, so a row is
described once here instead of copied by hand. Run it, then vst/shots.py (it adds each row's thumbnail buttons), then the build.
    python3 vst/make_rows.py
Everything between the first card list and the detail-view comment in layout.conf is replaced (the thumbnail lines come back
from shots.py); in params.json the card<N>_1 and r<N>_* params (not r<N>_shot) are replaced, at the place of the first one."""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = 5
TOP, PITCH, H = 210, 84, 80   # the list area is y 210..630 (the footer starts at 640); rows 84 apart, 80 tall
THUMB = (136, 68)             # keep in step with vst/shots.py and make_images.py (card_off.svg)


def layout_rows():
    out = []
    for r in range(1, ROWS + 1):
        t = TOP + PITCH * (r - 1)
        c = t + 40
        b = lambda cx, cy, key, img, w, h, when: out.append(   # noqa: E731
            'button cx=%d cy=%d label="" key=%s img=images/%s w=%d h=%d when=%s' % (cx, cy, key, img, w, h, when))
        k = "r%d_" % r
        out.append('list x=24 y=%d w=1232 h=%d cols=1 rows=1 th=%d gap=0 key=card%d img=images/card_off.svg img_on=images/card_on.svg '
                   'tx=160 ty=2 ttw=516 tth=44 tsize=37 tweight=bold tcolor=ececed when=%svis:on' % (t, H, H, r, k))
        # the thumbnails (shots.py adds them here), then the initials of a plugin without one and the corner text
        out.append('readout box=0 w=136 h=40 cx=102 cy=%d label="" key=%sinit tsize=38 tweight=bold tcolor=ececed talign=center tpad=0 when=%sshot:none' % (c - 2, k, k))
        out.append('readout box=0 w=46 h=16 cx=146 cy=%d label="" key=%skindtxt tsize=14 tcolor=c9ccd1 talign=right tpad=2' % (t + 64, k))
        out.append('readout box=0 w=516 h=30 cx=442 cy=%d label="" key=%smeta tsize=26 tweight=regular tcolor=b4b7bc talign=left tpad=0' % (t + 61, k))
        b(450, c - 2, k + "open", "card_hit.svg", 530, 70, k + "vis:on")
        # badges: the channel and CPU on the first line, the old-install and tested ones on the second
        b(736, t + 23, "noop", "badge_stable.svg", 72, 26, k + "chan:stable")
        b(732, t + 23, "noop", "badge_beta.svg", 64, 26, k + "chan:beta")
        b(836, t + 23, "noop", "badge_cpu.svg", 112, 26, k + "cpu:on")
        b(752, t + 58, "noop", "badge_old.svg", 104, 26, k + "old:on")
        b(912, t + 58, "noop", "badge_tested.svg", 200, 26, k + "tested:on")
        out.append('readout box=0 w=166 h=26 cx=924 cy=%d label="" key=%stested_txt tsize=22 tcolor=7fd6a8 talign=left tpad=0 when=%stested:on' % (t + 58, k, k))
        out.append('readout box=0 w=90 h=36 cx=950 cy=%d label="" key=%sver tsize=34 tcolor=ececed talign=left tpad=0' % (t + 23, k))
        out.append('readout box=0 w=64 h=22 cx=1014 cy=%d label="" key=%sfrom tsize=22 tcolor=f0b44a talign=left tpad=0' % (t + 25, k))
        for st, img in (("install", "btn_install"), ("update", "btn_update"), ("installed", "btn_installed"), ("q_install", "btn_q_install"),
                        ("q_update", "btn_q_update"), ("q_remove", "btn_q_remove"), ("disabled", "btn_disabled"),
                        ("register", "btn_register"), ("q_register", "btn_q_register")):
            b(1129, c, k + "act", img + ".svg", 150, 48, "%sstate:%s" % (k, st))
        b(1094, c, k + "reinstall", "btn_reinstall.svg", 76, 48, k + "state:menu")
        b(1172, c, k + "remove", "btn_remove.svg", 76, 48, k + "state:menu")
        b(1236, c, k + "more", "more.svg", 44, 48, k + "inst:yes")
    return out


def main():
    lc = os.path.join(HERE, "layout.conf")
    lines = open(lc).read().split("\n")
    first = next(i for i, l in enumerate(lines) if re.match(r"list x=24 y=\d+ .*key=card1\b", l))
    last = max(i for i, l in enumerate(lines) if re.search(r"key=r\d_more\b", l))
    lines[first:last + 1] = layout_rows()
    open(lc, "w").write("\n".join(lines))

    pj = os.path.join(HERE, "params.json")
    p = json.load(open(pj))
    ps = p["params"]
    rowp = lambda x: re.match(r"(card\d_1|r\d_(?!shot$).*)$", x["key"])   # noqa: E731
    tmpl = [x for x in ps if re.match(r"(card1_1|r1_(?!shot$).*)$", x["key"])]
    at = next(i for i, x in enumerate(ps) if rowp(x))
    rest = [x for x in ps if not rowp(x)]
    new = []
    for r in range(1, ROWS + 1):
        for x in tmpl:
            y = json.loads(json.dumps(x))
            y["key"] = re.sub(r"^(card|r)1", lambda m: m.group(1) + str(r), y["key"])
            y["name"] = re.sub(r"\b1\b", str(r), y["name"])
            new.append(y)
    p["params"] = rest[:at] + new + rest[at:]
    open(pj, "w").write(json.dumps(p, indent=1) + "\n")
    print("%d rows: %d layout lines, %d params" % (ROWS, len(layout_rows()), len(new)))


if __name__ == "__main__":
    main()
