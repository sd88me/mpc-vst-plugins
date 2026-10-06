#!/usr/bin/env python3
"""Poly Evolver firmware decoder (development tool; works on your own update files, ships nothing).

    pe_fw.py info    FILE.syx...            what each update file is (target chip, payload size)
    pe_fw.py unpack  FILE.syx -o OUT.bin    the decoded image (local use only: never commit it)
    pe_fw.py dsp-map DSP.syx                the DSP boot stream: records, addresses, what is code and what is data
    pe_fw.py tables  DSP.syx                the voice tables the engine's curves are fitted to, in physical units
    pe_fw.py check   DSP.syx                the firmware's parameter range table against the manual's (src/patch_tab.h)

Format (found 2026-10-06, docs/FIRMWARE.md): F0 01 20 01 <target> <payload> F7, targets 0x68 main CPU, 0x69 voice CPU, 0x78 DSP.
The payload is the manual's "packed MS bit" format, but restarted every 1024 decoded bytes: each 1171-byte slice unpacks to 1024
bytes on its own (146 groups of 8 plus one group of 3). Unpacking the payload as one stream goes wrong from byte 1024 on, which
looks like encryption but is not. Each image ends with one extra byte.
"""
import argparse
import math
import os
import re
import struct
import sys

TARGETS = {0x68: "main CPU (dsPIC, 24-bit words stored as 3 bytes)", 0x69: "voice CPU (PIC18)", 0x78: "DSP (ADSP-219x boot stream)"}


def unpack7(d):
    out = bytearray()
    for i in range(0, len(d), 8):
        m = d[i]
        for j, b in enumerate(d[i + 1:i + 8]):
            out.append(b | (((m >> j) & 1) << 7))
    return bytes(out)


def unpack_fw(path):
    d = open(path, "rb").read()
    if len(d) < 7 or d[:4] != b"\xf0\x01\x20\x01" or d[-1] != 0xF7:
        sys.exit("%s: not a DSI firmware SysEx (F0 01 20 01 ... F7)" % path)
    body = d[5:-1]
    out = bytearray()
    for i in range(0, len(body), 1171):
        out += unpack7(body[i:i + 1171])
    return d[4], bytes(out)


def dsp_load(img):
    """-> (records, mem): the ADSP-219x boot stream as {address: 24-bit word}. 32-bit little-endian words; a 24-bit
    instruction/data word sits in the top 24 bits. First a 3-word header (0x2f, 0, n) and n words for PM 0..n-1, then records
    [addr << 16 | flags][count << 16]: flags bit 2 = zero-fill (no data words follow), bit 0 = 16-bit data (in the top 16 bits)."""
    w = struct.unpack("<%dI" % (len(img) // 4), img[:len(img) // 4 * 4])
    mem, recs = {}, []
    n = w[2]
    for k in range(n):
        mem[k] = w[3 + k] >> 8
    recs.append((12, 0, 0, n))
    i = 3 + n
    while i < len(w) - 1:
        h, c = w[i], w[i + 1]
        addr, flags, cnt = h >> 16, h & 0xFFFF, c >> 16
        if flags & ~5 or c & 0xFFFF or cnt == 0:
            break
        recs.append((i * 4, addr, flags, cnt))
        if flags & 4:
            for k in range(cnt):
                mem[addr + k] = 0
            i += 2
        else:
            for k in range(cnt):
                mem[addr + k] = (w[i + 2 + k] >> 16) << 8 if flags & 1 else w[i + 2 + k] >> 8
            i += 2 + cnt
    return recs, mem


# Where the DSP 3.5 tables sit (word addresses). Other DSP versions may move them: the "check" command finds the range table by content.
T_RANGE, T_SEQMAX, T_PITCH, T_ENV, T_LFO, T_DELAY, T_HPF = 0x1800, 0x1880, 0x18C0, 0x1CD6, 0x1E8E, 0x201F, 0x2369


def s24(x):
    return x - (1 << 24) if x & 0x800000 else x


def hpf_cutoffs(mem, base):
    import cmath

    def resp(secs, f):
        z = cmath.exp(-1j * 2 * math.pi * f / 48000)
        h = 1
        for b0, b1, b2, a1, a2 in secs:
            h *= (b0 + b1 * z + b2 * z * z) / (1 - a1 * z - a2 * z * z)
        return abs(h)
    out = []
    for k in range(100):
        a = base + 10 * k
        secs = [[s24(mem.get(a + 5 * j + i, 0)) / 2 ** 22 for i in range(5)] for j in range(2)]
        hf = resp(secs, 23999)
        lo, hi = 1.0, 23999.0
        for _ in range(50):
            mid = math.sqrt(lo * hi)
            if resp(secs, mid) / hf < 1 / math.sqrt(2):
                lo = mid
            else:
                hi = mid
        out.append(mid)
    return out


def manual_ranges():
    """The range column of src/patch_tab.h (the manual's ranges)."""
    h = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "patch_tab.h")).read()
    return [int(m.group(1)) for m in re.finditer(r'\{"\w+", -?\d+, (\d+), -?\d+, "\w+"\}', h)][:128]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["info", "unpack", "dsp-map", "tables", "check"])
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    if a.cmd == "info":
        for f in a.files:
            t, img = unpack_fw(f)
            print("%s: target 0x%02x %s, %d bytes decoded" % (f, t, TARGETS.get(t, "?"), len(img)))
        return
    t, img = unpack_fw(a.files[0])
    if a.cmd == "unpack":
        open(a.out or os.path.basename(a.files[0]) + ".bin", "wb").write(img)
        return
    if t != 0x78:
        sys.exit("%s is not a DSP update (target 0x%02x)" % (a.files[0], t))
    recs, mem = dsp_load(img)
    if a.cmd == "dsp-map":
        for off, addr, flags, cnt in recs:
            print("stream 0x%05x  addr 0x%04x..0x%04x  %5d words  %s" % (off, addr, addr + cnt - 1, cnt,
                  "zero" if flags & 4 else "16-bit data" if flags & 1 else "24-bit"))
        print("vectors 0x0000-0x01ff (32 words apart), code from 0x0200, tables from 0x1800 (24-bit block), 16-bit block 0x8000+ zeroed")
        return
    if a.cmd == "check":
        man = manual_ranges()
        fw = [mem.get(T_RANGE + i, 0) >> 8 for i in range(128)]
        bad = [(i, man[i], fw[i]) for i in range(128) if man[i] != fw[i]]
        print("parameter ranges: %d of 128 agree with src/patch_tab.h" % (128 - len(bad)))
        for i, m, f in bad:
            print("  param %d: manual %d, firmware %d" % (i, m, f))
        steps = [mem.get(T_SEQMAX + i, 0) >> 8 for i in range(64)]
        print("sequencer step maxima: track 1 %d, tracks 2-4 %d" % (steps[0], steps[16]))
        return
    # tables, in physical units
    p0 = mem[T_PITCH]
    print("pitch: 128 phase increments, 23-bit phase at 48 kHz: note 0 = %.3f Hz, semitone ratio %.5f" % (
        p0 * 48000 / 2 ** 23, mem[T_PITCH + 1] / p0))
    print("envelope (0..110, ticks for full scale):", " ".join("%d:%.1f" % (i, 2 ** 23 / mem[T_ENV + i]) for i in range(111)))
    lfo90 = mem[T_LFO + 90]
    print("LFO (0..150, Hz):", " ".join("%d:%.4g" % (i, mem[T_LFO + i] * 8.1757989 / lfo90) for i in range(151)))
    print("delay (0..150, samples at 48 kHz):", " ".join("%d:%.1f" % (i, s24(mem[T_DELAY + i]) / 256) for i in range(151)))
    print("highpass (0..99, -3 dB Hz):", " ".join("%d:%.0f" % (i, f) for i, f in enumerate(hpf_cutoffs(mem, T_HPF))))


if __name__ == "__main__":
    main()
