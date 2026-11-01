#!/usr/bin/env python3
"""The light theme, made from the dark skin by a colour map (so the dark skin stays exactly as make_images.py draws it).

    python3 vst/make_light.py <a copy of vst/>      rewrites images/*.svg, layout.conf and skin.css in that folder in place

The light colours are the catalog site's (mpc-vst-plugins tools/catalog_site/site.css: bg #e9e7e2, panel #f7f6f3, text #1b1c1f, red #d63a30,
amber #e0a100). Each dark colour maps by its role (page, panel, line, text, accent, amber, green). Screenshots (PNG) are left as they are,
and so is the text drawn over their dark corner chip (the *_kindtxt readouts): that chip is baked dark in both themes.
The skin the device runs is one folder, "Plugin Skins"; the manager swaps in `Plugin Skins.light` or `Plugin Skins.dark` during a restart."""
import glob
import os
import re
import sys

# dark -> light, by role
MAP = {
    # page, panels, cards
    "0c0c0d": "e9e7e2", "121214": "efede8", "151517": "f7f6f3", "1d1e21": "ffffff",
    # lines, strokes, placeholders
    "222326": "d8d5ce", "24262a": "dcd9d2", "26272a": "cdcac2", "26272b": "cdcac2", "2a2b2f": "d6d3cb",
    "2e3034": "c9c6bd", "34363b": "bdbab1", "3a3c41": "b3b0a7", "4a4c52": "a7a49b", "5c5f65": "8f8d85", "6b6e74": "7f7d76",
    # text
    "ececed": "1b1c1f", "d6d8db": "2a2b2f", "c9ccd1": "3a3c41", "b4b7bc": "55575d", "9da1a7": "64666d", "7c8086": "7b7d84",
    # red accent (the fill stays strong; red text gets darker for contrast on light)
    "e0342c": "d63a30", "ff9a93": "b8281f", "ff7a72": "c4302a", "ffb4ae": "b8281f", "6b2a26": "e0a7a1", "2a1514": "fbe6e3",
    # amber (fill, text, the warning box); #1a1205 is the dark text on an amber button, it stays
    "f0a830": "e0a100", "f0b44a": "7a5600", "b88426": "b38200", "6b5220": "d9b45a", "2a2210": "fbf1d6",
    # green
    "7fd6a8": "1e7a52", "3fbf7f": "1f9a62", "2f5e46": "5fae88",
}
HEX = re.compile(r"#([0-9a-fA-F]{6})\b")
TOKEN = re.compile(r"\b(tcolor|theme_[a-z_]+)=([0-9a-fA-F]{6})\b")


def svg_color(m):
    return "#" + MAP.get(m.group(1).lower(), m.group(1))


def layout_line(line):
    if "kindtxt" in line:   # over the screenshot's baked dark corner chip
        return line
    return TOKEN.sub(lambda m: "%s=%s" % (m.group(1), MAP.get(m.group(2).lower(), m.group(2))), line)


def main(folder):
    n = 0
    for f in glob.glob(os.path.join(folder, "images", "**", "*.svg"), recursive=True):
        s = open(f).read()
        t = HEX.sub(svg_color, s)
        if t != s:
            open(f, "w").write(t)
            n += 1
    p = os.path.join(folder, "layout.conf")
    s = open(p).read()
    open(p, "w").write("".join(layout_line(l) for l in s.splitlines(True)))
    print("light theme: %d svg files recoloured, layout.conf rewritten in %s" % (n, folder))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
