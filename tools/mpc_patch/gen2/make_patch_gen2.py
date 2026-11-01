#!/usr/bin/env python3
"""Build the Gen2 (aarch64) drum-layout patch for a stock MPC 3.9.1 or 3.10.0 and check it against the user's own copy.

    make_patch_gen2.py <build: 3.9.1|3.10.0> <stock /usr/bin/MPC> [-o patched-copy-for-checking]

Same three changes as the armv7 patch (../make_patch.py), at the aarch64 addresses found by a string/table cross-reference:
  1. the one-caller helper "is this the DrumSynth:Multi program?" jumps to a name table matcher;
  2. the six `mov w1,#8` pad counts become `mov w1,#16`;
  3. the 8-pad colour loop is replaced by a 16-pad one (one red).
Needs `pip install keystone-engine`. Writes <build>.patch (our bytes only; no Akai bytes) and never an Akai file.
"""
import argparse, hashlib, os, struct, sys
import keystone

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = ["Machinedrum Module", "Machinemodule", "6W6", "8W8", "CW-78", "9W9", "TR-MPC", "Lucky Dip"]
MOV8, MOV16 = bytes.fromhex("01018052"), bytes.fromhex("01028052")   # mov w1,#8 / mov w1,#16

BUILDS = {
    "3.10.0": dict(
        md5="15a664f6b6ae591c8b78baae8b376f02",
        helper=0x2c0cf80, string=0x4dd00f8, eq=None,            # eq (String::operator==) read from the helper's own `b`
        colour=0x2c0d170, resume=0x2c0d198, setcol=None,         # setcol read from the loop's own `bl`
        sites_fix=[0x1795268, 0x1795d08, 0x1795ec0, 0x1796f8c, 0x179702c, 0x179733c],
        code=0x79a71a0, table=None, limit=0x79a8000),            # all in the zero tail of the code segment's last page
    "3.9.1": dict(
        md5="a7ace6a9993df33afeae50571755bbf9",
        helper=0x28b00a0, string=0x4b77eb8,
        colour=0x28b0290, resume=0x28b02b8,
        sites_fix=[0x1e42ba8, 0x1e43500, 0x1e435ac, 0x1e445ec, 0x1e4468c, 0x1e44eac],
        code=0x4b3b908, table=0x4c92f3c, limit=0x4b3b980),        # code after .fini; table in a zero run in .rodata
}


def md5(b):
    return hashlib.md5(b).hexdigest()


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def branch_target(b, at):                 # b / bl at file offset `at` (file offset == VA in the code segment)
    w = u32(b, at)
    assert w & 0x7c000000 == 0x14000000, hex(at)
    o = w & 0x3ffffff
    if o & 0x2000000:
        o -= 0x4000000
    return at + o * 4


def asm(src, addr):
    ks = keystone.Ks(keystone.KS_ARCH_ARM64, keystone.KS_MODE_LITTLE_ENDIAN)
    out, _ = ks.asm(src, addr)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build", choices=sorted(BUILDS))
    ap.add_argument("stock")
    ap.add_argument("-o")
    a = ap.parse_args()
    B = BUILDS[a.build]
    stock = open(a.stock, "rb").read()
    if md5(stock) != B["md5"]:
        sys.exit("not the stock %s Gen2 MPC" % a.build)
    new = bytearray(stock)
    regions = []

    def put(off, data):
        regions.append((off, data))
        new[off:off + len(data)] = data

    # --- original helper: bti c; adrp x1,STR; add x1,x1,#lo; b EQ
    h = B["helper"]
    assert u32(stock, h) == 0xd503245f, "helper does not start with bti c"
    eq = branch_target(stock, h + 12)
    # --- original colour loop head: adrp x19,TBL; add x19,x19,#lo; str x21,[sp,#0x20]; add x21,x19,#0x60; ldr w2,[x19,#8]; ldr w1,[x19],#0xc; bl SET
    c = B["colour"]
    want = asm("str x21,[sp,#0x20]; add x21,x19,#0x60; ldr w2,[x19,#8]; ldr w1,[x19],#0xc", c + 8)
    assert bytes(stock[c + 8:c + 24]) == want, "colour loop is not the expected one"
    setcol = branch_target(stock, c + 24)
    assert bytes(stock[B["resume"]:B["resume"] + 4]) == asm("add x0,x0,#0x50", 0), "resume point is not `add x0,x0,#0x50`"
    for s in B["sites_fix"]:
        assert stock[s:s + 4] == MOV8, hex(s)

    code = B["code"]
    colours_at = code
    colours_src = """
        str  x21, [sp, #0x20]
        mov  w21, #16
    L:  ldr  x0, [x20, #8]
        sub  w1, w21, #1
        movz w2, #0x7f, lsl #16
        bl   #%#x
        subs w21, w21, #1
        b.ne L
        ldr  x0, [x20, #8]
        b    #%#x
    """ % (setcol, B["resume"])
    colours = asm(colours_src, colours_at)
    matcher_at = colours_at + len(colours)
    table = b"".join(n.encode() + b"\0" for n in NAMES) + b"\0"
    table_at = B["table"] if B["table"] else None
    # the matcher is assembled twice: once to learn its length (the table follows it unless it has its own home)
    def matcher(tab_at):
        return asm("""
            ldr  x2, [x0]
            adrp x1, #%#x
            add  x1, x1, #%#x
        next: ldrb w4, [x1]
            cbz  w4, none
            mov  x3, x2
        cmpl: ldrb w4, [x3], #1
            ldrb w5, [x1], #1
            cmp  w4, w5
            b.ne skip
            cbnz w4, cmpl
            mov  w0, #1
            ret
        skip: cbz w5, next
        skl: ldrb w5, [x1], #1
            cbnz w5, skl
            b    next
        none: adrp x1, #%#x
            add  x1, x1, #%#x
            b    #%#x
        """ % (tab_at & ~0xfff, tab_at & 0xfff, B["string"] & ~0xfff, B["string"] & 0xfff, eq), matcher_at)
    m = matcher(matcher_at)
    if table_at is None:
        table_at = (matcher_at + len(m) + 3) & ~3
    m = matcher(table_at)
    end = matcher_at + len(m) + (len(table) if B["table"] is None else 0)
    if end > B["limit"]:
        sys.exit("cave is %d bytes too long" % (end - B["limit"]))
    if B["table"]:
        assert not any(stock[B["table"]:B["table"] + len(table)]), "table home is not zero"
    assert not any(stock[code:end]) or a.build == "3.9.1" and not any(stock[code:end]), "cave is not zero"
    put(colours_at, colours)
    put(matcher_at, m)
    put(table_at, table)
    # --- hooks
    put(h + 4, asm("b #%#x" % matcher_at, h + 4) + b"\0\0\0\0\0\0\0\0"[:0])   # bti c stays; b matcher; the old adrp/add/b are dead
    put(h + 8, bytes.fromhex("1f2003d5") * 2)                                 # nop nop (the old add and b)
    put(c, asm("b #%#x" % colours_at, c))
    for s in B["sites_fix"]:
        put(s, MOV16)
    lines = ["%x %s" % (o, d.hex()) for o, d in regions]
    pm = md5(bytes(new))
    out = os.path.join(HERE, "mpc-gen2-%s.patch" % a.build)
    with open(out, "w", newline="\n") as f:
        f.write("# MPC OS %s Gen2 (aarch64) drum-layout patch: <hex offset> <new bytes>  (no Akai bytes; the device saves its own originals)\n" % a.build)
        f.write("stock_md5 %s\npatched_md5 %s\n" % (B["md5"], pm))
        f.write("\n".join(lines) + "\n")
    if a.o:
        open(a.o, "wb").write(bytes(new))
    print("patched md5", pm, "-", len(lines), "regions; cave", hex(code), "-", hex(end))


main()
