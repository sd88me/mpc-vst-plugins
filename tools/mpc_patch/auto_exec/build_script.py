#!/usr/bin/env python3
"""Generate auto-exec-patch.sh from script.template.sh and the plain-text files in src/ (embedded as quoted heredocs, so a
reader sees exactly what gets installed; no encoding). Output: auto-exec-patch.sh (LF line endings). Run after editing src/."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1"   # this wrapper's revision (the patch itself is 0.3.2)
FILES = [("auto-exec.sh", "755"), ("uninstall.sh", "755"), ("bootstrap.sh", "755"), ("root-bootstrap.sh", "755"),
         ("auto-exec.service", "644"), ("auto-exec.timer", "644"), ("auto-exec-bootstrap.service", "644")]


def payload():
    out = []
    for name, _ in FILES:
        body = open(os.path.join(HERE, "src", name), encoding="utf-8").read()
        marker = "AEX_EOF_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
        assert marker not in body and body.endswith("\n"), name
        out.append("    cat > \"$d/%s\" <<'%s'\n%s%s" % (name, marker, body, marker))
    return "\n".join(out)


tpl = open(os.path.join(HERE, "script.template.sh"), encoding="utf-8").read()
res = tpl.replace("@@PAYLOAD@@", payload()).replace("@@VERSION@@", VERSION)
assert "@@" not in res
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "auto-exec-patch.sh")   # an argument: write there instead (tests)
with open(out, "w", newline="\n", encoding="utf-8") as f:
    f.write(res)
print("wrote", os.path.basename(out) + ":", len(res.splitlines()), "lines")
