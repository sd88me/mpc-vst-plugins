#!/usr/bin/env bash
# Offline x86 test of a port, before anything goes to a device:
#   tools/test_port.sh path/to/vst.json
# Generates the port's params.h, builds tools/host_test.c with the wrapper, the port's sources and its
# adapter under ASan/UBSan, and runs it (exit status = the test's). Uses the host gcc/g++ when present,
# else the gcc:12 Docker image. Ports with their own hand-written wrapper have their own host test.
set -euo pipefail
MV="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
eval "$(python3 "$MV/tools/gen_vst.py" "$CFG" --shell)"
python3 "$MV/tools/gen_vst.py" "$CFG" --params-h
ADAPTER_SRC=""
[ -n "$ADAPTER" ] && ADAPTER_SRC="$MV/adapters/$ADAPTER/${ADAPTER}_engine.c"
OUT="$ROOT/$PORT/build/host_test"
SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1"

build='
  set -e
  OBJS=""
  for f in $SOURCES; do
    o="$PORT/build/host_${f//\//_}.o"
    case "$f" in
      *.cpp|*.cc|*.cxx) g++ $SAN -std=gnu++11 $CFLAGS -I"$PORT/build" -I"$MV/wrapper" -c "$f" -o "$o" ;;
      *) gcc $SAN -std=gnu11 $CFLAGS -I"$PORT/build" -I"$MV/wrapper" -c "$f" -o "$o" ;;
    esac
    OBJS="$OBJS $o"
  done
  for f in "$MV/tools/host_test.c" "$MV/wrapper/vst2_wrap.c" $ADAPTER_SRC; do
    o="$PORT/build/host_$(basename "$f").o"
    gcc $SAN -std=gnu11 -I"$PORT/build" -c "$f" -o "$o"
    OBJS="$OBJS $o"
  done
  g++ $SAN $OBJS $LIBS -lpthread -o "$OUT"
'
export SOURCES CFLAGS PORT LIBS SAN MV ADAPTER_SRC OUT
cd "$ROOT"
if command -v gcc >/dev/null && command -v g++ >/dev/null; then
  bash -c "$build"
  "$OUT"
else
  docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT":"$ROOT" -v "$MV":"$MV":ro -w "$ROOT" \
    -e SOURCES -e CFLAGS -e PORT -e LIBS -e SAN -e MV -e ADAPTER_SRC -e OUT gcc:12 bash -c "$build && \"\$OUT\""
fi
