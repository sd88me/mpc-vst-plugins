#!/usr/bin/env python3
"""An Instruments-browser tile and a Default preset for a port's skin folder (docs/NOTES.md, "Instruments-browser tiles").

MPC's Sounds > INSTRUMENTS browser draws a plugin as a 270x110 artwork tile when the plugin folder holds
`Plugin Skins/browser_images/soundsmode.png`, and tapping the tile opens the plugin's preset page, which lists the
`.xpl` files in the folder's `Presets/`; a tile without presets does nothing on a tap. gen_vst.py calls write_tile()
and write_default_preset() for a vst.json with a "tile", so both ship inside the skin folder with every release.

An .xpl is MPC's <pluginstate>: the plugin's description (as in the plugin list) and a <state> holding the JUCE
VST2 state, i.e. an fxb chunk set ("CcnK" / "FBCh" with the plugin uid) around the plugin's own chunk, encoded in
JUCE's base64 variant ("<size>." + 6-bit groups, least-significant first, over the alphabet T). The Default preset
carries an empty wrapper chunk, so loading it starts the engine from its defaults.

    python3 tools/xpl.py <skin folder> <name> <vendor> <uid4> <so> [tile.png]   # writes the preset (and tile)
    python3 tools/xpl.py --decode <file.xpl>                           # dumps the decoded <state> bytes
"""
import datetime
import os
from xml.sax.saxutils import quoteattr, escape
import re
import shutil
import struct
import sys

T = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
TILE_W, TILE_H = 270, 110
TILE_REL = os.path.join("Plugin Skins", "browser_images", "soundsmode.png")


def b64enc(b):
    """JUCE MemoryBlock::toBase64Encoding."""
    out = []
    for i in range((len(b) * 8 + 5) // 6):
        start = i * 6
        byte, off, res, sofar, nb = start >> 3, start & 7, 0, 0, 6
        while nb > 0 and byte < len(b):
            t = min(nb, 8 - off)
            res |= ((b[byte] & ((0xff >> (8 - t)) << off)) >> off) << sofar
            sofar += t
            nb -= t
            byte += 1
            off = 0
        out.append(T[res])
    return "%d.%s" % (len(b), "".join(out))


def b64dec(s):
    n, _, body = s.partition(".")
    n = int(n)
    out, acc, bits, bi = bytearray(n), 0, 0, 0
    for ch in body:
        acc |= T.index(ch) << bits
        bits += 6
        while bits >= 8 and bi < n:
            out[bi] = acc & 0xff
            acc >>= 8
            bits -= 8
            bi += 1
    return bytes(out)


def fxb_chunk_set(uid, version, chunk, num_programs=1):
    hdr = b"CcnK" + struct.pack(">i", 0) + b"FBCh" + struct.pack(">iiii", 1, uid, version, num_programs) + bytes(128)
    return hdr + struct.pack(">i", len(chunk)) + chunk


def xpl(name, vendor, so_path, uid, version, chunk, preset="Default", effect=False, date=None):
    """The .xpl text. so_path is what the plugin list's file= says (the installer fills in %payload-path%)."""
    state = b64enc(fxb_chunk_set(uid, version, chunk))
    date = date or datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n\n<pluginstate>\n  <version file="1" date="%s"/>\n'
            '  <PLUGIN name=%s descriptiveName=%s format="VST" category="%s" manufacturer=%s\n'
            '          version="1.0" file=%s uid="%08x" isInstrument="%d" fileTime="0"\n'
            '          infoUpdateTime="0" numInputs="%d" numOutputs="2" isShell="0"/>\n'
            '  <preset>%s</preset>\n  <state>%s</state>\n</pluginstate>\n'
            % (date, quoteattr(name), quoteattr(name), "Effect" if effect else "Synth", quoteattr(vendor), quoteattr(so_path), uid,
               0 if effect else 1, 2 if effect else 0, escape(preset), state))


def png_size(path):
    with open(path, "rb") as f:
        d = f.read(24)
    if d[:8] != b"\x89PNG\r\n\x1a\n" or d[12:16] != b"IHDR":
        raise SystemExit("tile: %s is not a PNG" % path)
    return struct.unpack(">II", d[16:24])


def write_tile(src, skin_folder):
    """Copy the 270x110 PNG to <skin>/Plugin Skins/browser_images/soundsmode.png."""
    w, h = png_size(src)
    if (w, h) != (TILE_W, TILE_H):
        raise SystemExit("tile: %s is %dx%d; the Instruments browser tile is %dx%d" % (src, w, h, TILE_W, TILE_H))
    dst = os.path.join(skin_folder, TILE_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def write_default_preset(skin_folder, name, vendor, uid4, so, version=1000, effect=False):
    """Write <skin>/Presets/0000-Default.xpl (empty chunk = the engine's defaults); returns its path."""
    skin_name = "%s - VST - %s" % (vendor, name)
    so_path = "%%payload-path%%/%s/%s" % (skin_name, so)
    dst = os.path.join(skin_folder, "Presets", "0000-Default.xpl")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    uid = int.from_bytes(uid4.encode(), "big")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(xpl(name, vendor, so_path, uid, version, b"\0", effect=effect))
    return dst


if __name__ == "__main__":
    if sys.argv[1:2] == ["--decode"]:
        for f in sys.argv[2:]:
            with open(f, encoding="utf-8") as fh:
                b = b64dec(re.search(r"<state>(.*?)</state>", fh.read(), re.S).group(1).strip())
            print("==", f, len(b), "bytes")
            for i in range(0, len(b), 16):
                c = b[i:i + 16]
                print("%04x  %-48s %s" % (i, " ".join("%02x" % x for x in c),
                                          "".join(chr(x) if 32 <= x < 127 else "." for x in c)))
    elif len(sys.argv) in (6, 7):
        skin, name, vendor, uid4, so = sys.argv[1:6]
        print(write_default_preset(skin, name, vendor, uid4, so))
        if len(sys.argv) == 7:
            print(write_tile(sys.argv[6], skin))
    else:
        sys.exit(__doc__)
