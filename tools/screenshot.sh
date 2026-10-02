#!/usr/bin/env bash
# A screenshot of the device's screen, as MPC shows it right now:
#   tools/screenshot.sh <ssh target> out.png [--plugin]      e.g. tools/screenshot.sh "root@<ip>" shot.png
#   (extra ssh options via SSH_OPTS, e.g. SSH_OPTS="-p 2222")
# Builds tools/drmgrab.c for 32-bit ARM (Docker), runs it once from /tmp on the device and deletes it: it reads the
# buffer the display is scanning out (DRM GETFB2 + dma-buf mmap, read-only; /dev/fb0 stays black, MPC draws through DRM).
# The panel is portrait, so the image is rotated upright. --plugin crops to the plugin area (1280x628 at y=110).
# Verified on an MPC One (docs/NOTES.md).
set -euo pipefail
[ $# -ge 2 ] || { sed -n 2,8p "$0"; exit 1; }
MV="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$1"; OUT="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; CROP="${3:-}"
BIN="$MV/tools/build/drmgrab"
mkdir -p "$MV/tools/build"
if [ ! -x "$BIN" ] || [ "$MV/tools/drmgrab.c" -nt "$BIN" ]; then
  docker run --rm --platform linux/arm/v7 -v "$MV/tools":/t -w /t arm32v7/gcc:12 bash -c \
    'apt-get -qq update >/dev/null && apt-get -qq install -y libdrm-dev >/dev/null && gcc -O2 -static -I/usr/include/libdrm -o build/drmgrab drmgrab.c'
fi
RAW="$(mktemp)"
trap 'rm -f "$RAW"' EXIT
# shellcheck disable=SC2086
ssh $SSH_OPTS "$TARGET" 'cat > /tmp/drmgrab && chmod +x /tmp/drmgrab && /tmp/drmgrab /dev/dri/card0 || /tmp/drmgrab /dev/dri/card1; rc=$?; rm -f /tmp/drmgrab; exit $rc' < "$BIN" > "$RAW"
docker run --rm -v "$RAW":/raw:ro -v "$(dirname "$OUT")":/out mpc-vst-html-art python3 -c "
from PIL import Image
raw = open('/raw', 'rb').read(); hdr, px = raw.split(b'\n', 1)
w, h, p = map(int, hdr.split()[:3])
im = Image.frombuffer('RGBA', (w, h), px[:p * h], 'raw', 'BGRA', p, 1).convert('RGB')
im = im.rotate(270, expand=True) if h > w else im
if '$CROP' == '--plugin': im = im.crop((0, 110, 1280, 738))
im.save('/out/$(basename "$OUT")', optimize=True)"
echo "$OUT"
