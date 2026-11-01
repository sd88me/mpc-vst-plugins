#!/usr/bin/env python3
"""Build the Gen1 (armv7: MPC Live/One/X/Key) drum-layout patch for a stock MPC 3.10.0 and check it against the user's own copy.

    make_patch_gen1.py <stock /usr/bin/MPC> [-o patched-copy-for-checking]

The same three changes as the Force patch (../make_patch.py), at the addresses found by structural matching against it:
  1. the one-caller helper "is this the DrumSynth:Multi program?" jumps to a name table matcher;
  2. the six `movne r1,#8` pad counts become `movne r1,#16`;
  3. the 8-pad colour loop is replaced by a 16-pad one (one red).
Needs `pip install keystone-engine`. Writes mpc-gen1-3.10.0.patch (our bytes only; no Akai bytes) and never an Akai file.
"""
import argparse, hashlib, os, struct, sys
import keystone

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = ["Machinedrum Module", "Machinemodule", "6W6", "8W8", "CW-78", "9W9", "TR-MPC", "Lucky Dip"]
MOVNE8 = bytes.fromhex("0810a013")
B = dict(
    md5="b6cc8e7a398bdf6c3fd8f7176eecd3ee",
    helper=0x28584e0, string=0x4d41ec0,
    colour=0x2858740, resume=0x285876c,
    sites=[0x1193600, 0x1194100, 0x11942c0, 0x11954bc, 0x1195550, 0x11958a8],
    code=0x6c7c730, limit=0x6c7d000)      # the zero tail of the R+X segment's last mapped page


def md5(b):
    return hashlib.md5(b).hexdigest()


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def bl_target(b, at):
    w = u32(b, at)
    assert w >> 24 in (0xea, 0xeb), hex(at)
    o = w & 0xffffff
    if o & 0x800000:
        o -= 1 << 24
    return at + 8 + o * 4


def asm(src, addr):
    ks = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
    out, _ = ks.asm(src, addr)
    return bytes(out)


def jump(at, dest):
    """ldr ip,[pc,#0]; add pc,pc,ip; .word delta  (12 bytes, position independent, reaches any address)"""
    return asm("ldr ip,[pc,#0]; add pc,pc,ip", at) + struct.pack("<I", (dest - (at + 4 + 8)) & 0xffffffff)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stock")
    ap.add_argument("-o")
    a = ap.parse_args()
    stock = open(a.stock, "rb").read()
    if md5(stock) != B["md5"]:
        sys.exit("not the stock 3.10.0 Gen1 MPC")
    new = bytearray(stock)
    regions = []

    def put(off, data):
        regions.append((off, data))
        new[off:off + len(data)] = data

    h, c = B["helper"], B["colour"]
    # original helper: ldr r1,[pc,#4]; add r1,pc,r1; b String::operator==; .word (string - pc)
    assert stock[h:h + 8] == bytes.fromhex("04109fe501108fe0"), "helper is not the expected one"
    eq = bl_target(stock, h + 8)
    assert (h + 12 + u32(stock, h + 12)) & 0xffffffff == B["string"], "helper does not load DrumSynth:Multi"
    # original colour loop head (the Force patch's), 8 pads from a 12-byte-stride table
    assert stock[c + 8:c + 8 + 20] == bytes.fromhex("0c4086e26c6086e20c1014e5042014e50c4084e2"), "colour loop is not the expected one"
    setcol = bl_target(stock, c + 0x1c)
    assert stock[c + 0x20:c + 0x2c] == bytes.fromhex("060054e1040095e5f8ffff1a"), "colour loop tail unexpected"
    assert stock[B["resume"]:B["resume"] + 8] == bytes.fromhex("0010a0e3280080e2"), "resume point is not `mov r1,#0; add r0,r0,#0x28`"
    for s in B["sites"]:
        assert stock[s:s + 4] == MOVNE8, hex(s)

    colours_at = B["code"]
    # in: r5 = the lambda's closure, [r5,#4] = ProgramPads. r4 is caller-saved here (the original loop used it).
    colours = asm("""
        mov  r4, #0
    L:  ldr  r0, [r5, #4]
        mov  r1, r4
        mov  r2, #0x7f0000
        ldr  ip, Lset
    A:  add  ip, pc, ip
        blx  ip
        add  r4, r4, #1
        cmp  r4, #16
        bne  L
        ldr  r0, [r5, #4]
        ldr  ip, Lret
    B:  add  pc, pc, ip
    Lset: .word %d
    Lret: .word %d
    """ % (0, 0), colours_at)
    # the two data words depend on label addresses: recompute from the assembled layout
    n = len(colours)
    # layout is fixed: 13 instructions then the two words; `add ip,pc,ip` is the 6th, `add pc,pc,ip` the 13th
    a_at, b_at = colours_at + 5 * 4, colours_at + 12 * 4
    assert n == 15 * 4, n
    colours = colours[:13 * 4] + struct.pack("<II", (setcol - (a_at + 8)) & 0xffffffff, (B["resume"] - (b_at + 8)) & 0xffffffff)
    assert asm("add ip,pc,ip", a_at) == colours[5 * 4:6 * 4] and asm("add pc,pc,ip", b_at) == colours[12 * 4:13 * 4]
    matcher_at = colours_at + len(colours)
    table = b"".join(n.encode() + b"\0" for n in NAMES) + b"\0"
    # in: r0 = juce::String*, r2 = its UTF-8 text (the helper's first instruction), lr = return address into the caller
    m = bytearray(asm("""
        push {r4}
        adr  r1, table
    next: ldrb r4, [r1]
        cmp  r4, #0
        beq  none
        mov  r3, r2
    cmpl: ldrb r4, [r3], #1
        ldrb ip, [r1], #1
        cmp  r4, ip
        bne  skip
        cmp  r4, #0
        bne  cmpl
        pop  {r4}
        mov  r0, #1
        bx   lr
    skip: cmp ip, #0
        beq  next
    skl: ldrb ip, [r1], #1
        cmp  ip, #0
        bne  skl
        b    next
    none: pop {r4}
        ldr  r1, L1
    Ladd1: add r1, pc, r1
        ldr  ip, L2
    Ladd2: add pc, pc, ip
    L1: .word 0
    L2: .word 0
    table:
    """, matcher_at))
    # the last 8 bytes are the L1/L2 words; the instructions before them are fixed in number
    ni = (len(m) - 8) // 4
    add1_at, add2_at = matcher_at + (ni - 3) * 4, matcher_at + (ni - 1) * 4
    assert m[(ni - 3) * 4:(ni - 2) * 4] == asm("add r1,pc,r1", add1_at) and m[(ni - 1) * 4:ni * 4] == asm("add pc,pc,ip", add2_at)
    m[-8:] = struct.pack("<II", (B["string"] - (add1_at + 8)) & 0xffffffff, (eq - (add2_at + 8)) & 0xffffffff)
    m += table
    end = matcher_at + len(m)
    if end > B["limit"]:
        sys.exit("cave is %d bytes too long" % (end - B["limit"]))
    assert not any(stock[B["code"]:end]), "cave is not zero"
    put(colours_at, colours)
    put(matcher_at, bytes(m))
    put(h + 4, jump(h + 4, matcher_at))                 # ldr r2,[r0] goes first, in the helper's first 4 bytes
    put(h, asm("ldr r2,[r0]", h))
    put(c, jump(c, colours_at))
    for s in B["sites"]:
        put(s, bytes([0x10]))
    lines = ["%x %s" % (o, d.hex()) for o, d in regions]
    pm = md5(bytes(new))
    out = os.path.join(HERE, "mpc-gen1-3.10.0.patch")
    with open(out, "w", newline="\n") as f:
        f.write("# MPC OS 3.10.0 Gen1 (armv7) drum-layout patch: <hex offset> <new bytes>  (no Akai bytes; the device saves its own originals)\n")
        f.write("stock_md5 %s\npatched_md5 %s\n" % (B["md5"], pm))
        f.write("\n".join(lines) + "\n")
    if a.o:
        open(a.o, "wb").write(bytes(new))
    print("patched md5", pm, "-", len(lines), "regions; cave", hex(B["code"]), "-", hex(end))


main()
