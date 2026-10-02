#!/usr/bin/env bash
# Build a port as an MPC OS VST2 instrument from its vst.json (see tools/gen_vst.py).
#   tools/build_port.sh path/to/vst.json
# Output in <vst.json folder>/build/: <so>, skin/<vendor> - VST - <name>/, pluginlist-entry.xml, params.h.
# Needs Docker (with QEMU for arm32v7). The skin artwork renderer is vendored in tools/vendor/force-shadow/.
set -euo pipefail
MV="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
eval "$(python3 "$MV/tools/gen_vst.py" "$CFG" --shell)"
# an engine from another ecosystem: its adapter (adapters/<name>/) provides mpc_engine()
ADAPTER_SRC=""
[ -n "$ADAPTER" ] && ADAPTER_SRC="/mv/adapters/$ADAPTER/${ADAPTER}_engine.c"
U="$(id -u):$(id -g)"
mkdir -p "$ROOT/$PORT/build"

# 1. skin artwork renderer: shadow_art (host binary), or with vst.json "art": "html" a browser
# (tools/html_art.py in the mpc-vst-html-art image: headless Chromium + Pillow)
if [ "$ART" = html ]; then
  docker build -q -t mpc-vst-html-art "$MV/tools/html_art" >/dev/null
else
  docker run --rm -u "$U" -v "$ROOT":/w -v "$MV":/mv:ro -w /w gcc:12 \
    gcc -O2 -I/mv/tools/vendor/force-shadow/tools -o "$PORT/build/shadow_art" /mv/tools/shadow_art.c -lm
fi

# 2. params.h, skin, plugin-list entry
# TITLE_FONT (vst.json's optional "title_font", a .ttf/.otf path relative to vst.json): a real
# TrueType font for frame titles instead of shadow_art.c's baked bitmap font (shadow_skin.py's
# SHADOW_TITLE_FONT env var). Mounted read-only into the container at the same relative path so
# gen_vst.py's own repo-relative path resolution still works unchanged.
FONT_MOUNT=()
FONT_ENV=()
if [ -n "$TITLE_FONT" ]; then
  FONT_MOUNT=(-v "$ROOT/$PORT/$TITLE_FONT:/w/$PORT/$TITLE_FONT:ro")
  FONT_ENV=(-e "SHADOW_TITLE_FONT=/w/$PORT/$TITLE_FONT")
fi
if [ "$ART" = html ]; then
  docker run --rm -u "$U" -e HOME=/tmp -v "$ROOT":/w -v "$MV":/mv:ro "${FONT_MOUNT[@]}" "${FONT_ENV[@]}" -w /w mpc-vst-html-art \
    python3 /mv/tools/gen_vst.py "$PORT/vst.json"
else
  docker run --rm -u "$U" -v "$ROOT":/w -v "$MV":/mv:ro "${FONT_MOUNT[@]}" "${FONT_ENV[@]}" -w /w python:3.11-slim sh -c \
    "pip install -q --no-warn-script-location --target /tmp/p pillow >/dev/null 2>&1; PYTHONPATH=/tmp/p python3 /mv/tools/gen_vst.py '$PORT/vst.json'"
fi

# 3. the plugin (armhf, glibc 2.31 (bullseye) so it loads on MPC OS 2.x (glibc 2.32) as well as 3.x (2.39); keep the highest symbol <= 2.32)
# All-C sources (every port so far): unchanged single gcc command (byte-identical Maze builds).
# Any .cpp source (e.g. a real emulator engine like jv880's): vst2_wrap.c is always plain C
# (gcc -std=gnu11; it uses void*-to-typed-pointer conversions g++ rejects), so each source compiles
# separately by its own extension, then everything links with g++ (handles both, pulls in libstdc++).
case "$SOURCES" in
  *.cpp*|*.cc*|*.cxx*) CXXPORT=1 ;;
  *) CXXPORT=0 ;;
esac
if [ "$CXXPORT" = 0 ]; then
  docker run --rm --platform linux/arm/v7 -u "$U" -v "$ROOT":/b -v "$MV":/mv:ro -w /b arm32v7/gcc:11-bullseye bash -euc "
    gcc -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -shared -fvisibility=hidden -std=gnu11 $CFLAGS -I'$PORT/build' \
        $SOURCES $ADAPTER_SRC /mv/wrapper/vst2_wrap.c $LIBS -Wl,--no-undefined -o '$PORT/build/$SO'
    strip '$PORT/build/$SO'
    echo \"exported: \$(readelf --dyn-syms -W '$PORT/build/$SO' | grep -E ' GLOBAL .* [0-9]+ [A-Za-z]' | grep -v UND | awk '{print \$8}' | tr '\n' ' ')\"
    echo \"highest glibc: \$(readelf -V '$PORT/build/$SO' | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1) (device has 2.39)\"
  "
else
  docker run --rm --platform linux/arm/v7 -u "$U" -v "$ROOT":/b -v "$MV":/mv:ro -w /b arm32v7/gcc:11-bullseye bash -euc "
    OBJS=''
    for f in $SOURCES; do
      o=\"$PORT/build/\${f//\//_}.o\"
      case \"\$f\" in
        *.cpp|*.cc|*.cxx) g++ -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -fvisibility=hidden -std=gnu++11 $CFLAGS -I'$PORT/build' -c \"\$f\" -o \"\$o\" ;;
        *) gcc -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -fvisibility=hidden -std=gnu11 $CFLAGS -I'$PORT/build' -c \"\$f\" -o \"\$o\" ;;
      esac
      OBJS=\"\$OBJS \$o\"
    done
    gcc -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -fvisibility=hidden -std=gnu11 -I'$PORT/build' -c /mv/wrapper/vst2_wrap.c -o '$PORT/build/vst2_wrap.o'
    if [ -n '$ADAPTER_SRC' ]; then
      gcc -O2 -Wall -Wextra -fPIC -fvisibility=hidden -std=gnu11 -c '$ADAPTER_SRC' -o '$PORT/build/adapter.o'
      OBJS=\"\$OBJS $PORT/build/adapter.o\"
    fi
    g++ -O2 -shared -fPIC -fvisibility=hidden \$OBJS '$PORT/build/vst2_wrap.o' $LIBS -Wl,--no-undefined -o '$PORT/build/$SO'
    strip '$PORT/build/$SO'
    echo \"exported: \$(readelf --dyn-syms -W '$PORT/build/$SO' | grep -E ' GLOBAL .* [0-9]+ [A-Za-z]' | grep -v UND | awk '{print \$8}' | tr '\n' ' ')\"
    echo \"highest glibc: \$(readelf -V '$PORT/build/$SO' | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1) (device has 2.39)\"
  "
fi
md5sum "$ROOT/$PORT/build/$SO"
