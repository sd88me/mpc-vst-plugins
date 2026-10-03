#!/usr/bin/env python3
"""Generate mpc-drum-pad-patch.sh from script.template.sh, mpc-3.9.1.2.patch and the name table in matcher.S.

Run make_patch.py first (it writes mpc-3.9.1.2.patch). Output: patch/mpc-drum-pad-patch.sh (LF line endings).
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "3"

patch = open(os.path.join(HERE, "mpc-3.9.1.2.patch")).read().splitlines()
patched_md5 = next(l.split()[1] for l in patch if l.startswith("patched_md5"))
body = [l for l in patch if l.strip() and not l.startswith("#") and not l.startswith("stock_md5") and not l.startswith("patched_md5")]
names = re.findall(r'\.asciz\s+"([^"]+)"', open(os.path.join(HERE, "matcher.S")).read())
tpl = open(os.path.join(HERE, "script.template.sh")).read()
out = (tpl.replace("@@PATCH@@", "\n".join(body))
          .replace("@@PATCHED_MD5@@", patched_md5)
          .replace("@@NAMES@@", ", ".join(names))
          .replace("@@COUNT@@", str(len(names)))
          .replace("@@VERSION@@", VERSION))
assert "@@" not in out
open(os.path.join(HERE, "mpc-drum-pad-patch.sh"), "w", newline="\n").write(out)
print("wrote mpc-drum-pad-patch.sh:", len(names), "names,", len(body), "regions, patched md5", patched_md5)
