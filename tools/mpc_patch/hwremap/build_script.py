#!/usr/bin/env python3
"""Generate hwremap-patch.sh from script.template.sh, the two configs and src/hwremap.so.

The library is embedded as hex so the one script the device runs is the whole patch (docs/PATCHES.md).
Build the library first (build.sh). Output is LF. A path argument writes there instead (tests).
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def hex_lines(data):
    h = data.hex()
    return "\n".join(h[i:i + 64] for i in range(0, len(h), 64)) + "\n"


def load(name):
    body = open(os.path.join(HERE, name), encoding="utf-8").read()
    if not body.endswith("\n"):
        body += "\n"
    return body


so_path = os.path.join(HERE, "src", "hwremap.so")
if not os.path.isfile(so_path):
    sys.exit("missing %s: run tools/mpc_patch/hwremap/build.sh first" % so_path)
so = open(so_path, "rb").read()
if so[:4] != b"\x7fELF" or so[4] != 1 or so[18] != 40:
    sys.exit("src/hwremap.so is not a 32-bit ARM ELF")

live = load(os.path.join("configs", "mpc-live.conf"))
force = load(os.path.join("configs", "force.conf"))
for label, body in (("mpc-live.conf", live), ("force.conf", force)):
    if "HW_CONF_" in body or "@@" in body:
        sys.exit("%s collides with a script marker" % label)

tpl = open(os.path.join(HERE, "script.template.sh"), encoding="utf-8").read()
res = (tpl.replace("@@SO_HEX@@", hex_lines(so))
          .replace("@@SO_SIZE@@", str(len(so)))
          .replace("@@SO_SHA256@@", hashlib.sha256(so).hexdigest())
          .replace("@@CONF_LIVE@@", live)
          .replace("@@CONF_FORCE@@", force))
if "@@" in res:
    sys.exit("unreplaced marker in the generated script")
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "hwremap-patch.sh")
with open(out, "w", newline="\n", encoding="utf-8") as f:
    f.write(res)
print("wrote", os.path.basename(out) + ":", len(res.splitlines()), "lines")
