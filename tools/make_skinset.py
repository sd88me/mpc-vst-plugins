#!/usr/bin/env python3
"""Merge several built skins into one skin folder that can be switched at runtime.

Why: MPC binds a skin when the plugin instance is inserted and has no reload API, but it reads
`Plugin Skins/TUI.json` on every insert. So if the *only* file that differs per interface is the TUI
(the artwork lives in per-interface subfolders), the plugin can switch interfaces by copying one small
JSON file — no image is touched, so a running instance cannot be disturbed mid-render.

Layout produced (inside an existing skin folder):

    Plugin Skins/
      TUI.json                 <- copy of the active interface, paths rewritten into its subfolder
      Q-Links.json             <- same, if the interface has one
      ui.txt                   <- name of the active interface (read by the plugin on load)
      studio/  TUI.json, Q-Links*.json, *.png
      classic/ ...
      rack/ ...

Usage:
    python3 make_skinset.py -o "portable/MPCDJ - VST - MPC DJ FX 2/Plugin Skins" \\
        studio=<built skin dir> classic=<built skin dir> rack=<built skin dir> [--active studio]

Every argument after -o is `name=directory`. The directory is a built skin folder (the one holding
TUI.json right after `gen_vst.py`), not the `Plugin Skins` parent. `name` becomes the subfolder, so it must
be one plain folder name (no separators, not `.` or `..`) and unique: the tool removes and rewrites exactly
that path on every run.
"""
import argparse
import json
import os
import shutil
import sys

ASSET_EXT = (".png", ".jpg", ".jpeg", ".webp")


def check_name(name):
    """A name becomes the subfolder under -o, and a rebuild rmtree()s exactly that path. Accept only one plain
    path component: empty, '.', '..', an absolute path or anything with a separator would reach outside it."""
    if not name or name in (".", "..") or os.path.isabs(name) or "/" in name or "\\" in name or "\0" in name:
        sys.exit("make_skinset: %r is not an interface name: one plain folder name, no path, no separators" % name)
    return name


def rewrite_paths(node, names, prefix):
    """Prefix every bare asset reference in `node` that names a file from this skin."""
    if isinstance(node, dict):
        return {k: rewrite_paths(v, names, prefix) for k, v in node.items()}
    if isinstance(node, list):
        return [rewrite_paths(v, names, prefix) for v in node]
    if isinstance(node, str):
        if node.startswith("/") or node.startswith(prefix + "/"):
            return node
        base = os.path.basename(node)
        if node == base and base.lower().endswith(ASSET_EXT) and base in names:
            return prefix + "/" + base
    return node


def load_variant(name, src):
    tui = os.path.join(src, "TUI.json")
    if not os.path.isfile(tui):
        sys.exit("make_skinset: %s has no TUI.json (%s)" % (name, src))
    assets = {f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))}
    names = {f for f in assets if f.lower().endswith(ASSET_EXT)}
    data = json.load(open(tui))
    return {
        "name": name,
        "src": src,
        "assets": assets,
        "tui": rewrite_paths(data, names, name),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True, help="skin folder to write (the 'Plugin Skins' one)")
    ap.add_argument("--active", help="interface that is active after the build (default: the first given)")
    ap.add_argument("variants", nargs="+", metavar="NAME=DIR")
    a = ap.parse_args()

    variants = []
    for spec in a.variants:
        if "=" not in spec:
            sys.exit("make_skinset: expected NAME=DIR, got %r" % spec)
        name, src = spec.split("=", 1)
        variants.append(load_variant(check_name(name), src))
    names = [v["name"] for v in variants]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        sys.exit("make_skinset: duplicate interface name(s): %s" % ", ".join(dupes))
    active = a.active or names[0]
    if active not in names:
        sys.exit("make_skinset: --active %r is not one of %s" % (active, ", ".join(names)))

    out = a.out
    os.makedirs(out, exist_ok=True)

    # 1. clear anything this tool owns (variant subfolders, top-level switching files)
    for v in names:
        shutil.rmtree(os.path.join(out, v), ignore_errors=True)
    for f in ("TUI.json", "Q-Links.json", "Q-Links - 8by1.json", "ui.txt"):
        p = os.path.join(out, f)
        if os.path.exists(p):
            os.remove(p)

    # 2. copy every interface into its own subfolder, with the TUI inside it
    for v in variants:
        dst = os.path.join(out, v["name"])
        os.makedirs(dst, exist_ok=True)
        for f in sorted(v["assets"]):
            if f == "TUI.json":
                continue
            shutil.copy2(os.path.join(v["src"], f), os.path.join(dst, f))
        with open(os.path.join(dst, "TUI.json"), "w") as fh:
            json.dump(v["tui"], fh, separators=(",", ":"))
        print("  %-10s %3d files" % (v["name"], len(v["assets"])))

    # 3. activate one: the top-level files are what MPC reads on insert
    top = [v for v in variants if v["name"] == active][0]
    with open(os.path.join(out, "TUI.json"), "w") as fh:
        json.dump(top["tui"], fh, separators=(",", ":"))
    for f in ("Q-Links.json", "Q-Links - 8by1.json"):
        if f in top["assets"]:
            shutil.copy2(os.path.join(top["src"], f), os.path.join(out, f))
    with open(os.path.join(out, "ui.txt"), "w") as fh:
        fh.write(active + "\n")

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(out) for f in fs)
    print("skinset: %s (%d interfaces, active %s, %.1f MB)" % (out, len(variants), active, total / 1e6))


if __name__ == "__main__":
    main()
