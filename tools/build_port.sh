#!/usr/bin/env bash
# Build a port as an MPC OS VST2 instrument from its vst.json (see tools/gen_vst.py).
#   tools/build_port.sh path/to/vst.json [armv7|aarch64|all]
# Output in <vst.json folder>/build/: <so> (Gen1/Force, armv7), aarch64/<so> (Gen2, only when vst.json "targets" lists aarch64), skin/<vendor> - VST - <name>/, pluginlist-entry.xml, params.h.
# Needs Docker (with QEMU for arm32v7 and arm64). The skin artwork renderer is vendored in tools/vendor/force-shadow/.
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
# SHADOW_SKIN_MPC_OS=2 in the caller's environment writes the skin in the MPC OS 2.x shape (shadow_skin.py to_mpc2x,
# experimental); unset or 3 is the normal 3.x skin.
SKIN_ENV=()
if [ -n "${SHADOW_SKIN_MPC_OS:-}" ]; then
  SKIN_ENV=(-e "SHADOW_SKIN_MPC_OS=$SHADOW_SKIN_MPC_OS")
fi
if [ "$ART" = html ]; then
  docker run --rm -u "$U" -e HOME=/tmp -v "$ROOT":/w -v "$MV":/mv:ro ${FONT_MOUNT[@]+"${FONT_MOUNT[@]}"} ${FONT_ENV[@]+"${FONT_ENV[@]}"} ${SKIN_ENV[@]+"${SKIN_ENV[@]}"} -w /w mpc-vst-html-art \
    python3 /mv/tools/gen_vst.py "$PORT/vst.json"
else
  docker run --rm -u "$U" -v "$ROOT":/w -v "$MV":/mv:ro ${FONT_MOUNT[@]+"${FONT_MOUNT[@]}"} ${FONT_ENV[@]+"${FONT_ENV[@]}"} ${SKIN_ENV[@]+"${SKIN_ENV[@]}"} -w /w python:3.11-slim sh -c \
    "pip install -q --no-warn-script-location --target /tmp/p pillow >/dev/null 2>&1; PYTHONPATH=/tmp/p python3 /mv/tools/gen_vst.py '$PORT/vst.json'"
fi

build_target() {   # build_target <image> <docker platform> <extra cflags> <output dir, relative to ROOT>
  local IMG="$1" PLAT="$2" XF="$3" OUT="$4"
  mkdir -p "$ROOT/$OUT"
# 3. the plugin, once per target (armhf, glibc 2.31 (bullseye) so it loads on MPC OS 2.x (glibc 2.32) as well as 3.x (2.39); keep the highest symbol <= 2.32 or the plugin is listed as MPC OS 3.x only)
# All-C sources (every port so far): unchanged single gcc command (byte-identical Maze builds).
# Any .cpp source (e.g. a real emulator engine like jv880's): vst2_wrap.c is always plain C
# (gcc -std=gnu11; it uses void*-to-typed-pointer conversions g++ rejects), so each source compiles
# separately by its own extension, then everything links with g++ (handles both, pulls in libstdc++).
case "$SOURCES" in
  *.cpp*|*.cc*|*.cxx*) CXXPORT=1 ;;
  *) CXXPORT=0 ;;
esac
if [ "$CXXPORT" = 0 ]; then
  docker run --rm --platform $PLAT -u "$U" -v "$ROOT":/b -v "$MV":/mv:ro -w /b $IMG bash -euc "
    gcc -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -shared -fvisibility=hidden -std=gnu11 $CFLAGS $XF -I'$PORT/build' -I/mv/wrapper \
        $SOURCES $ADAPTER_SRC /mv/wrapper/vst2_wrap.c $LIBS -lpthread -Wl,--no-undefined -o '$OUT/$SO'
    strip '$OUT/$SO'
    echo \"exported: \$(readelf --dyn-syms -W '$OUT/$SO' | grep -E ' GLOBAL .* [0-9]+ [A-Za-z]' | grep -v UND | awk '{print \$8}' | tr '\n' ' ')\"
    echo \"highest glibc: \$(readelf -V '$OUT/$SO' | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1) (device has 2.39)\"
  "
else
  docker run --rm --platform $PLAT -u "$U" -v "$ROOT":/b -v "$MV":/mv:ro -w /b $IMG bash -euc "
    OBJS=''
    for f in $SOURCES; do
      o=\"$OUT/\${f//\//_}.o\"
      case \"\$f\" in
        *.cpp|*.cc|*.cxx) g++ -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -fvisibility=hidden -std=gnu++11 $CFLAGS $XF -I'$PORT/build' -I/mv/wrapper -c \"\$f\" -o \"\$o\" ;;
        *) gcc -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -fvisibility=hidden -std=gnu11 $CFLAGS $XF -I'$PORT/build' -I/mv/wrapper -c \"\$f\" -o \"\$o\" ;;
      esac
      OBJS=\"\$OBJS \$o\"
    done
    gcc -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -fvisibility=hidden -std=gnu11 -I'$PORT/build' -c /mv/wrapper/vst2_wrap.c -o '$OUT/vst2_wrap.o'
    if [ -n '$ADAPTER_SRC' ]; then
      gcc -O2 -Wall -Wextra -fPIC -fvisibility=hidden -std=gnu11 -c '$ADAPTER_SRC' -o '$OUT/adapter.o'
      OBJS=\"\$OBJS $OUT/adapter.o\"
    fi
    g++ -O2 -shared -fPIC -fvisibility=hidden \$OBJS '$OUT/vst2_wrap.o' $LIBS -lpthread -Wl,--no-undefined -o '$OUT/$SO'
    strip '$OUT/$SO'
    echo \"exported: \$(readelf --dyn-syms -W '$OUT/$SO' | grep -E ' GLOBAL .* [0-9]+ [A-Za-z]' | grep -v UND | awk '{print \$8}' | tr '\n' ' ')\"
    echo \"highest glibc: \$(readelf -V '$OUT/$SO' | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1) (device has 2.39)\"
  "
fi
  md5sum "$ROOT/$OUT/$SO"
}

# Targets: vst.json "targets" (default ["armv7"]); the second argument picks one (armv7 = Gen1 MPC and Force, aarch64 = Gen2) or "all".
WANT="${2:-all}"
for t in $TARGETS; do
  [ "$WANT" = all ] || [ "$WANT" = "$t" ] || continue
  case "$t" in
    armv7)   build_target arm32v7/gcc:11-bullseye linux/arm/v7 "$CFLAGS_ARM" "$PORT/build" ;;
    # aarch64: Gen2 runs MPC OS 3.x only (glibc 2.39), so bookworm (2.36) is fine; no 2.x ceiling to respect
    aarch64) build_target arm64v8/gcc:12-bookworm linux/arm64 "$CFLAGS_A64" "$PORT/build/aarch64" ;;
    *) echo "unknown target $t" >&2; exit 1 ;;
  esac
done
