#!/usr/bin/env python3
"""Generate mpc-drum-pad-patch.sh from script.template.sh, mpc-3.9.1.2.patch, gen2/mpc-gen2-*.patch and the name table in matcher.S.

Run make_patch.py and gen2/make_patch_gen2.py first (they write the .patch files). Output: patch/mpc-drum-pad-patch.sh (LF line endings).
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "8"

patch = open(os.path.join(HERE, "mpc-3.9.1.2.patch")).read().splitlines()
patched_md5 = next(l.split()[1] for l in patch if l.startswith("patched_md5"))
body = [l for l in patch if l.strip() and not l.startswith("#") and not l.startswith("stock_md5") and not l.startswith("patched_md5")]
def gen2(build):
    lines = open(os.path.join(HERE, "gen2", "mpc-gen2-%s.patch" % build)).read().splitlines()
    g = {l.split()[0]: l.split()[1] for l in lines if l.startswith(("stock_md5", "patched_md5"))}
    data = [l for l in lines if l.strip() and not l.startswith(("#", "stock_md5", "patched_md5"))]
    return g["stock_md5"], g["patched_md5"], "\n".join(data)


def gen1(build):
    lines = open(os.path.join(HERE, "gen1", "mpc-gen1-%s.patch" % build)).read().splitlines()
    g = {l.split()[0]: l.split()[1] for l in lines if l.startswith(("stock_md5", "patched_md5"))}
    data = [l for l in lines if l.strip() and not l.startswith(("#", "stock_md5", "patched_md5"))]
    return g["stock_md5"], g["patched_md5"], "\n".join(data)


sg1, pg1, dg1 = gen1("3.10.0")
s391, p391, d391 = gen2("3.9.1")
s310, p310, d310 = gen2("3.10.0")
names = re.findall(r'\.asciz\s+"([^"]+)"', open(os.path.join(HERE, "matcher.S")).read())
tpl = open(os.path.join(HERE, "script.template.sh")).read()
out = (tpl.replace("@@PATCH@@", "\n".join(body))
          .replace("@@PATCHED_MD5@@", patched_md5)
          .replace("@@STOCK_391@@", s391).replace("@@PATCHED_391@@", p391).replace("@@PATCH_391@@", d391)
          .replace("@@STOCK_310@@", s310).replace("@@PATCHED_310@@", p310).replace("@@PATCH_310@@", d310)
          .replace("@@STOCK_G1_310@@", sg1).replace("@@PATCHED_G1_310@@", pg1).replace("@@PATCH_G1_310@@", dg1)
          .replace("@@NAMES@@", ", ".join(names))
          .replace("@@COUNT@@", str(len(names)))
          .replace("@@VERSION@@", VERSION))
assert "@@" not in out
open(os.path.join(HERE, "mpc-drum-pad-patch.sh"), "w", newline="\n").write(out)
print("wrote mpc-drum-pad-patch.sh:", len(names), "names,", len(body), "regions, patched md5", patched_md5)
