#!/usr/bin/env python3
"""Run the patched matcher and colour loop under Unicorn (aarch64) against a patched copy made by make_patch_gen2.py -o.

    test_gen2_emu.py <3.9.1|3.10.0> <patched MPC>
"""
import struct, sys
from unicorn import *
from unicorn.arm64_const import *
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
src = open(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "make_patch_gen2.py")).read()
build, path = sys.argv[1], sys.argv[2]
ns = {"__file__": __file__}
exec(src.split("def md5")[0].replace("import keystone", "keystone=None"), ns)   # BUILDS only
B = ns["BUILDS"][build]
data = open(path, "rb").read()
SIZE = (len(data) + 0xfff) & ~0xfff
SENT, STK, TXT = 0xdead0000, 0x7e000000, 0x7d000000
def fresh():
    mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    mu.mem_map(0, SIZE); mu.mem_write(0, data)
    mu.mem_map(SENT, 0x1000); mu.mem_map(STK, 0x10000); mu.mem_map(TXT, 0x10000)
    return mu
def stub(mu, addr, fn):
    mu.hook_add(UC_HOOK_CODE, lambda u, a, s, ud: fn(u), begin=addr, end=addr)

# helper -> matcher
eq = None
w = struct.unpack_from("<I", data, B["helper"] + 12)[0]    # patched: nop; real b-target comes from the stock via the patch's matcher
fails = 0
cases = ["Machinedrum Module", "Machinemodule", "6W6", "8W8", "CW-78", "9W9", "TR-MPC", "Lucky Dip",
         "DrumSynth:Multi", "Sampler", "", "6W", "6W66", "Machinedrum", "Lucky Dipx", "lucky dip"]
want = {c: (1 if c in cases[:8] else 0xEE) for c in cases}
# find String::operator== (the fallback target) from the matcher's last instruction: scan the cave for the final b
mu = fresh()
code = B["code"]
# locate final `b EQ` by decoding every b in the cave's range
eqs = set()
for off in range(code, code + 0x120, 4):
    wd = struct.unpack_from("<I", data, off)[0]
    if wd & 0xfc000000 == 0x14000000:
        o = wd & 0x3ffffff; o -= 0x4000000 if o & 0x2000000 else 0
        t = off + o * 4
        if t < code or t > code + 0x200: eqs.add(t)
for t in eqs:
    pass
EQ = [t for t in eqs if t != B["resume"]]
assert len(EQ) == 1, EQ
EQ = EQ[0]
for c in cases:
    mu = fresh()
    mu.mem_write(TXT, c.encode() + b"\0"); mu.mem_write(TXT + 0x100, struct.pack("<Q", TXT))
    res = {}
    def eqfn(u):
        res["x0"] = 0xEE; u.reg_write(UC_ARM64_REG_X0, 0xEE); u.reg_write(UC_ARM64_REG_PC, SENT)
    stub(mu, EQ, eqfn)
    mu.reg_write(UC_ARM64_REG_X0, TXT + 0x100); mu.reg_write(UC_ARM64_REG_X30, SENT)
    mu.reg_write(UC_ARM64_REG_SP, STK + 0x8000)
    mu.emu_start(B["helper"], SENT, count=2000)
    got = mu.reg_read(UC_ARM64_REG_X0) & 0xffffffff
    ok = got == want[c]
    fails += not ok
    print("%-20r -> %#x %s" % (c, got, "ok" if ok else "FAIL (want %#x)" % want[c]))
# colour loop
mu = fresh()
calls = []
SETCOL = None
for off in range(code, code + 0x40, 4):
    wd = struct.unpack_from("<I", data, off)[0]
    if wd & 0xfc000000 == 0x94000000:
        o = wd & 0x3ffffff; o -= 0x4000000 if o & 0x2000000 else 0
        SETCOL = off + o * 4; break
stub(mu, SETCOL, lambda u: (calls.append((u.reg_read(UC_ARM64_REG_X0), u.reg_read(UC_ARM64_REG_W1), u.reg_read(UC_ARM64_REG_W2))),
                            u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30) - 4 + 4 - 4 + 4)))
mu.mem_write(STK + 0x100, struct.pack("<QQ", 0, 0x5000)); mu.reg_write(UC_ARM64_REG_X20, STK + 0x100)
mu.reg_write(UC_ARM64_REG_SP, STK + 0x8000)
mu.emu_start(B["colour"], B["resume"], count=500)
pads = sorted(c[1] for c in calls)
ok = pads == list(range(16)) and all(c[2] == 0x7f0000 and c[0] == 0x5000 for c in calls) and mu.reg_read(UC_ARM64_REG_X0) == 0x5000
fails += not ok
print("colour loop: %d calls, pads %s, colours %s, x0 at resume %#x %s" % (len(calls), pads == list(range(16)), {hex(c[2]) for c in calls}, mu.reg_read(UC_ARM64_REG_X0), "ok" if ok else "FAIL"))
sys.exit(1 if fails else 0)
