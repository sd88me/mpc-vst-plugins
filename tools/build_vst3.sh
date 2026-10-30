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
set -euo pipefail
MV="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
eval "$(python3 "$MV/tools/gen_vst.py" "$CFG" --shell)"
python3 "$MV/tools/gen_vst.py" "$CFG" --params-h
ADAPTER_SRC=""
[ -n "$ADAPTER" ] && ADAPTER_SRC="$MV/adapters/$ADAPTER/${ADAPTER}_engine.c"
case "$(uname -m)" in
  x86_64) ARCH=x86_64-linux ;;
  aarch64) ARCH=aarch64-linux ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac
SKIN=""
[ -z "${VST3_SKIN:-}" ] || SKIN="$(cd "$VST3_SKIN" && pwd)"
cd "$ROOT"
OUTDIR="$PORT/build/vst3"
OPT="-O2 -g0 -fPIC -fvisibility=hidden -Wall -Wextra -Wno-unused-parameter -DMPC_DESKTOP=1"
LDSAN=""
if [ -n "${VST3_SAN:-}" ]; then
  OUTDIR="$PORT/build/vst3-san"
  OPT="-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fPIC -fvisibility=hidden -Wall -Wextra -Wno-unused-parameter -DMPC_DESKTOP=1"
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
    *.cpp|*.cc|*.cxx) g++ $OPT -std=gnu++11 $CFLAGS -I"$MV/wrapper" -I"$PORT/build" -c "$f" -o "$o" ;;
    *) gcc $OPT -std=gnu11 $CFLAGS -I"$MV/wrapper" -I"$PORT/build" -c "$f" -o "$o" ;;
  esac
  OBJS="$OBJS $o"
done
for f in "$MV/wrapper/vst3_wrap.c" $ADAPTER_SRC; do
  o="$OBJ/$(basename "$f").o"
  gcc $OPT -std=gnu11 $EDITOR_CF -I"$MV/wrapper" -I"$PORT/build" -c "$f" -o "$o"
  OBJS="$OBJS $o"
done
SO="$BUNDLE/Contents/$ARCH/$NAME.so"
g++ -shared -fPIC $LDSAN $OBJS $LIBS $EDITOR_LIBS -lpthread -Wl,--no-undefined -o "$SO"
[ -n "${VST3_SAN:-}" ] || strip "$SO"
SUBDIR="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("defines", {}).get("MODULE_SUBDIR", "").strip("\""))' "$CFG")"
[ -z "$SUBDIR" ] || mkdir -p "$BUNDLE/Contents/$ARCH/$SUBDIR"
if [ -n "$EDITOR_CF" ]; then   # the skin, flattened for the editor, and its fonts (SIL OFL: the licence goes with them)
  RES="$BUNDLE/Contents/Resources/skin"
  python3 "$MV/tools/desktop_skin.py" "$SKIN" "$RES"
  cp "$MV"/tools/html_art/fonts/TitilliumWeb-{Regular,SemiBold,Bold}.ttf "$MV/tools/html_art/fonts/OFL.txt" "$RES/"
fi
echo "exported: $(readelf --dyn-syms -W "$SO" | grep -E ' GLOBAL .* [0-9]+ [A-Za-z]' | grep -v UND | awk '{print $8}' | tr '\n' ' ')"
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
