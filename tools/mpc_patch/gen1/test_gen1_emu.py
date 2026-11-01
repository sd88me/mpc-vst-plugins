#!/usr/bin/env python3
"""Run the patched matcher and colour loop under Unicorn (armv7) against a patched copy made by make_patch_gen1.py -o.

    test_gen1_emu.py <stock MPC> <patched MPC>
"""
import struct, sys
from unicorn import *
from unicorn.arm_const import *

HELPER, COLOUR, RESUME = 0x28584e0, 0x2858740, 0x285876c
stock, new = open(sys.argv[1], "rb").read(), open(sys.argv[2], "rb").read()
SIZE = (len(new) + 0xfff) & ~0xfff
SENT, STK, TXT = 0xdead0000, 0x7e000000, 0x7d000000


def target(d, at):
    o = struct.unpack_from("<I", d, at)[0] & 0xffffff
    o -= (1 << 24) if o & 0x800000 else 0
    return at + 8 + o * 4


EQ, SETCOL = target(stock, HELPER + 8), target(stock, COLOUR + 0x1c)


def fresh():
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    mu.mem_map(0, SIZE); mu.mem_write(0, new)
    mu.mem_map(SENT, 0x1000); mu.mem_map(STK, 0x10000); mu.mem_map(TXT, 0x10000)
    return mu


def stub(mu, addr, fn):
    mu.hook_add(UC_HOOK_CODE, lambda u, a, s, ud: fn(u), begin=addr, end=addr)


names = ["Machinedrum Module", "Machinemodule", "6W6", "8W8", "CW-78", "9W9", "TR-MPC", "Lucky Dip"]
cases = names + ["DrumSynth:Multi", "Sampler", "", "6W", "6W66", "Machinedrum", "Lucky Dipx", "lucky dip"]
fails = 0
for c in cases:
    want = 1 if c in names else 0xEE
    mu = fresh()
    mu.mem_write(TXT, c.encode() + b"\0"); mu.mem_write(TXT + 0x100, struct.pack("<I", TXT))
    stub(mu, EQ, lambda u: (u.reg_write(UC_ARM_REG_R0, 0xEE), u.reg_write(UC_ARM_REG_PC, SENT)))
    mu.reg_write(UC_ARM_REG_R0, TXT + 0x100); mu.reg_write(UC_ARM_REG_LR, SENT); mu.reg_write(UC_ARM_REG_SP, STK + 0x8000)
    mu.reg_write(UC_ARM_REG_R4, 0x1234)
    mu.emu_start(HELPER, SENT, count=3000)
    got = mu.reg_read(UC_ARM_REG_R0)
    ok = got == want and mu.reg_read(UC_ARM_REG_R4) == 0x1234 and mu.reg_read(UC_ARM_REG_SP) == STK + 0x8000
    fails += not ok
    print("%-20r -> %#x %s" % (c, got, "ok" if ok else "FAIL (want %#x)" % want))
mu = fresh()
calls = []
stub(mu, SETCOL, lambda u: (calls.append((u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1), u.reg_read(UC_ARM_REG_R2))),
                            u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))))
mu.mem_write(STK + 0x100, struct.pack("<II", 0, 0x5000)); mu.reg_write(UC_ARM_REG_R5, STK + 0x100)
mu.reg_write(UC_ARM_REG_SP, STK + 0x8000)
mu.emu_start(COLOUR, RESUME, count=500)
pads = [c[1] for c in calls]
ok = pads == list(range(16)) and all(c[2] == 0x7f0000 and c[0] == 0x5000 for c in calls) and mu.reg_read(UC_ARM_REG_R0) == 0x5000
fails += not ok
print("colour loop: %d calls, pads in order %s, colours %s, r0 at resume %#x %s" % (len(calls), pads == list(range(16)), {hex(c[2]) for c in calls}, mu.reg_read(UC_ARM_REG_R0), "ok" if ok else "FAIL"))
sys.exit(1 if fails else 0)
