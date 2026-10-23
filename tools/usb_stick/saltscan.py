"""Find the autorun check's salt in MPC firmware.

The stock USB-script reader validates autorun/autorun.check = sha256(autorun.json + open.sh + the listed files + salt). The salt
is a short string kept XOR-obfuscated in the MPC executable. Discovered and first used by Eurikon (plugin-manager-usb, MIT);
this module finds it by scanning instead of reading a fixed offset, so it works on any firmware build that keeps the same scheme.

Nothing Akai-derived is stored in this repo: the salt is read from the user's own firmware at generation time.
"""
import lzma
import re

KEY = (0xc9771b45f9913b87).to_bytes(8, "little")   # from the firmware's scheme (see docs/USB_STICK.md); not a secret
WIDTH = 37                                          # bytes reserved for the salt, padded with zeros
MIN_LEN = 16
CHUNK = 8 << 20
_RUN = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_LEN)


def scan(stream):
    """Yield (offset, salt) for every candidate in a binary file object; offsets are into the stream."""
    base, tail = 0, b""
    while True:
        data = stream.read(CHUNK)
        if not data and not tail:
            return
        block = tail + data
        start = base - len(tail)
        final = not data
        for align in range(8):
            dec = _xor_for(block, start, align)
            for m in _RUN.finditer(dec):
                rs, e = m.span()
                # the salt ends where the printable run ends (zero padding follows); it starts at the first byte of the run
                # (at most WIDTH back) that is aligned with the key. A random printable byte just before it may join the run.
                lo = max(rs, e - WIDTH)
                s0 = lo + ((align - (start + lo)) % 8)
                if e - s0 < MIN_LEN:
                    continue
                if s0 + WIDTH > len(block) and not final:
                    continue                      # the window continues in the next chunk
                if any(dec[e:s0 + WIDTH]):
                    continue
                if start + s0 + WIDTH <= base:
                    continue                      # lay wholly in the previous chunk: already reported
                yield start + s0, dec[s0:e]
        base += len(data)
        tail = block[-(WIDTH + 8):] if data else b""
        if final:
            return


def _xor_for(block, start, align):
    # the key's byte 0 meets the stream offset `align` (mod 8); byte i of block is at stream offset start + i
    n = len(block)
    k = (start - align) % 8
    key = KEY[k:] + KEY[:k]
    pad = (key * (n // 8 + 1))[:n]
    return (int.from_bytes(block, "little") ^ int.from_bytes(pad, "little")).to_bytes(n, "little")


class _Xz:
    """A read() over one xz stream that starts at `offset` in an update image."""
    def __init__(self, f, offset):
        f.seek(offset)
        self.f, self.dec = f, lzma.LZMADecompressor(format=lzma.FORMAT_XZ)

    def read(self, n):
        out = b""
        while len(out) < n and not self.dec.eof:
            if self.dec.needs_input:
                raw = self.f.read(1 << 20)
                if not raw:
                    break
                out += self.dec.decompress(raw)
            else:
                out += self.dec.decompress(b"")
        return out


def xz_offsets(path):
    """Offsets of xz streams in an update image (its root filesystems are xz-compressed)."""
    found, magic = [], b"\xfd7zXZ\x00"
    with open(path, "rb") as f:
        pos, carry = 0, b""
        while True:
            data = f.read(1 << 24)
            if not data:
                break
            blk = carry + data
            i = 0
            while (i := blk.find(magic, i)) >= 0:
                found.append(pos - len(carry) + i)
                i += 1
            carry = blk[-5:]
            pos += len(data)
    return found


def find_salt(path):
    """The salt in a firmware file: a raw MPC executable, or an update image whose root filesystems are xz streams.

    Returns (salt_bytes, hits) where hits is a list of (where, offset). Raises ValueError when there is no candidate or the
    candidates disagree (the scheme changed, or the file is not stock firmware): never guesses.
    """
    hits = []
    with open(path, "rb") as f:
        for off, salt in scan(f):
            hits.append(("file", off, salt))
    if not hits:
        for off in xz_offsets(path):
            with open(path, "rb") as f:
                try:
                    for o, salt in scan(_Xz(f, off)):
                        hits.append((f"xz@{off}", o, salt))
                except lzma.LZMAError:
                    continue
    if not hits:
        raise ValueError("no salt found: not stock MPC firmware, or the scheme changed")
    values = {h[2] for h in hits}
    if len(values) > 1:
        # The salt lives in a WIDTH-byte reserved field padded with zeros, so a genuine candidate is shorter
        # than WIDTH (at least one trailing \0). Coincidental printable runs instead fill the whole field with
        # printable bytes and have length == WIDTH -- the aarch64 Gen2 rootfs yields several of these. Drop them;
        # if that leaves exactly one value, it is the salt.
        padded = {v for v in values if len(v) < WIDTH}
        if padded:
            values = padded
    if len(values) != 1:
        raise ValueError(f"{len(values)} different salt candidates; refusing to guess")
    salt = next(iter(values))
    return salt, [(w, o) for w, o, s in hits if s == salt]
