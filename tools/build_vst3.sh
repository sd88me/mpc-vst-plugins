#!/usr/bin/env bash
# Build a port as a VST3 plugin for a desktop DAW on this machine (Linux x86_64), from the same vst.json as the MPC build:
#   tools/build_vst3.sh path/to/vst.json [--install]
# Output: <vst.json folder>/build/vst3/<name>.vst3 (wrapper/vst3_wrap.c around the port's engine); --install copies it to
# ~/.vst3. Local use only: MPC OS loads VST2, so build_port.sh stays the device build. Uses the host gcc/g++ (no Docker).
# VST3_SAN=1 (tools/test_vst3.sh) builds with ASan/UBSan into build/vst3-san instead, unstripped.
# Every source is compiled with -DMPC_DESKTOP=1, so a port can leave out what only makes sense on a device (drawing on MPC's
# screen, say). A MODULE_SUBDIR port gets that folder, empty, next to the .so in the bundle (where the engine looks for its data:
# DrumGizmo's kits); --install keeps the files already in the installed bundle's folder.
# The editor (wrapper/vst3_editor.c: the MPC skin in the plugin window) is built in when the port's skin has been built
# (build_port.sh writes <vst.json folder>/build/skin/<vendor> - VST - <name>/, or set VST3_SKIN to a skin folder) and cairo,
# FreeType and X11 are installed (pkg-config); otherwise the plugin has no editor and a DAW shows its generic one.
# VST3_TARGET=windows cross-builds a 64-bit Windows bundle (<name>.vst3/Contents/x86_64-win/<name>.vst3) with mingw-w64
# (x86_64-w64-mingw32-gcc/g++); the engine, winpthreads and the C++ runtime are linked in statically, so the DLL stands alone.
# No editor yet on Windows (a DAW shows its generic parameter view); --install is not supported there (copy the bundle to
# %CommonProgramFiles%\VST3).
set -euo pipefail
MV="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
eval "$(python3 "$MV/tools/gen_vst.py" "$CFG" --shell)"
python3 "$MV/tools/gen_vst.py" "$CFG" --params-h
ADAPTER_SRC=""
[ -n "$ADAPTER" ] && ADAPTER_SRC="$MV/adapters/$ADAPTER/${ADAPTER}_engine.c"
CC=gcc; CXX=g++; STRIP=strip; PIC="-fPIC -fvisibility=hidden"
if [ "${VST3_TARGET:-}" = windows ]; then
  T=x86_64-w64-mingw32
  command -v $T-gcc >/dev/null || { echo "VST3_TARGET=windows needs mingw-w64 ($T-gcc)" >&2; exit 1; }
  [ "${2:-}" != --install ] || { echo "--install is for Linux; copy the bundle to %CommonProgramFiles%\\VST3" >&2; exit 1; }
  CC=$T-gcc; CXX=$T-g++; STRIP=$T-strip; PIC=""; ARCH=x86_64-win
else
  case "$(uname -m)" in
    x86_64) ARCH=x86_64-linux ;;
    aarch64) ARCH=aarch64-linux ;;
    *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
  esac
fi
SKIN=""
[ -z "${VST3_SKIN:-}" ] || SKIN="$(cd "$VST3_SKIN" && pwd)"
cd "$ROOT"
OUTDIR="$PORT/build/vst3"
OPT="-O2 -g0 $PIC -Wall -Wextra -Wno-unused-parameter -DMPC_DESKTOP=1"
LDSAN=""
if [ -n "${VST3_SAN:-}" ]; then
  OUTDIR="$PORT/build/vst3-san"
  OPT="-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined $PIC -Wall -Wextra -Wno-unused-parameter -DMPC_DESKTOP=1"
  LDSAN="-fsanitize=address,undefined"
fi
OBJ="$OUTDIR/obj"
if [ -z "$SKIN" ]; then
  for d in "$ROOT/$PORT"/build/skin/*" - VST - $NAME"; do [ -d "$d" ] && SKIN="$d"; done
fi
EDITOR_CF=""
EDITOR_LIBS=""
if [ -z "$SKIN" ]; then
  echo "editor: none (no built skin in $PORT/build/skin; run build_port.sh, or set VST3_SKIN)"
elif [ "$ARCH" = x86_64-win ]; then
  echo "editor: none (not on Windows yet)"
elif ! pkg-config --exists cairo freetype2 x11; then
  echo "editor: none (cairo, freetype2 and x11 development files are needed)"
else
  EDITOR_CF="-DVST3_EDITOR $(pkg-config --cflags cairo freetype2 x11)"
  EDITOR_LIBS="$(pkg-config --libs cairo freetype2 x11)"
fi
BUNDLE="$OUTDIR/$NAME.vst3"
rm -rf "$OBJ" "$BUNDLE"
mkdir -p "$OBJ" "$BUNDLE/Contents/$ARCH"
OBJS=""
for f in $SOURCES; do
  o="$OBJ/${f//\//_}.o"
  case "$f" in
    *.cpp|*.cc|*.cxx) $CXX $OPT -std=gnu++11 $CFLAGS -I"$MV/wrapper" -I"$PORT/build" -c "$f" -o "$o" ;;
    *) $CC $OPT -std=gnu11 $CFLAGS -I"$MV/wrapper" -I"$PORT/build" -c "$f" -o "$o" ;;
  esac
  OBJS="$OBJS $o"
done
for f in "$MV/wrapper/vst3_wrap.c" $ADAPTER_SRC; do
  o="$OBJ/$(basename "$f").o"
  $CC $OPT -std=gnu11 $EDITOR_CF -I"$MV/wrapper" -I"$PORT/build" -c "$f" -o "$o"
  OBJS="$OBJS $o"
done
if [ "$ARCH" = x86_64-win ]; then
  SO="$BUNDLE/Contents/$ARCH/$NAME.vst3"
  $CXX -shared $LDSAN $OBJS $LIBS -static -lpthread -Wl,--no-undefined -o "$SO"
else
  SO="$BUNDLE/Contents/$ARCH/$NAME.so"
  $CXX -shared -fPIC $LDSAN $OBJS $LIBS $EDITOR_LIBS -lpthread -Wl,--no-undefined -o "$SO"
fi
[ -n "${VST3_SAN:-}" ] || $STRIP "$SO"
SUBDIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("defines", {}).get("MODULE_SUBDIR", "").strip("\""))' "$CFG")"
[ -z "$SUBDIR" ] || mkdir -p "$BUNDLE/Contents/$ARCH/$SUBDIR"
if [ -n "$EDITOR_CF" ]; then   # the skin, flattened for the editor, and its fonts (SIL OFL: the licence goes with them)
  RES="$BUNDLE/Contents/Resources/skin"
  python3 "$MV/tools/desktop_skin.py" "$SKIN" "$RES"
  cp "$MV"/tools/html_art/fonts/TitilliumWeb-{Regular,SemiBold,Bold}.ttf "$MV/tools/html_art/fonts/OFL.txt" "$RES/"
fi
if [ "$ARCH" = x86_64-win ]; then
  echo "exported: $(x86_64-w64-mingw32-objdump -p "$SO" | awk '/Ordinal\/Name Pointer/{f=1;next} f&&NF==0{f=0} f{print $NF}' | tr '\n' ' ')"
else
  echo "exported: $(readelf --dyn-syms -W "$SO" | grep -E ' GLOBAL .* [0-9]+ [A-Za-z]' | grep -v UND | awk '{print $8}' | tr '\n' ' ')"
fi
echo "bundle: $ROOT/$BUNDLE"
if [ "${2:-}" = --install ]; then
  mkdir -p "$HOME/.vst3"
  rm -rf "$HOME/.vst3/$NAME.vst3.new"
  cp -r "$BUNDLE" "$HOME/.vst3/$NAME.vst3.new"
  OLD_DATA="$HOME/.vst3/$NAME.vst3/Contents/$ARCH/$SUBDIR"
  if [ -n "$SUBDIR" ] && [ -d "$OLD_DATA" ]; then   # the user's data (kits, models) moves into the new bundle
    rm -rf "$HOME/.vst3/$NAME.vst3.new/Contents/$ARCH/$SUBDIR"
    mv "$OLD_DATA" "$HOME/.vst3/$NAME.vst3.new/Contents/$ARCH/$SUBDIR"
  fi
  rm -rf "$HOME/.vst3/$NAME.vst3"
  mv "$HOME/.vst3/$NAME.vst3.new" "$HOME/.vst3/$NAME.vst3"
  echo "installed: $HOME/.vst3/$NAME.vst3"
fi
