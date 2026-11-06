#!/usr/bin/env bash
# Offline test of a port's MPC Sample page (vst.json "sample_page"): builds the port with the wrapper and
# tools/sample_page_test.c (a stand-in draw handler and host) under ThreadSanitizer, and runs it.
#   tools/test_sample_page.sh <port>/vst.json
# Needs the host gcc/g++ (no Docker fallback). Exit status = the test's (TSan exits 66 on a data race).
set -euo pipefail
MV="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
eval "$(python3 "$MV/tools/gen_vst.py" "$CFG" --shell)"
python3 "$MV/tools/gen_vst.py" "$CFG" --params-h
grep -q '^#define SAMPLE_PAGE' "$ROOT/$PORT/build/params.h" || { echo "$CFG has no \"sample_page\": nothing to test"; exit 0; }
ADAPTER_SRC=""
[ -n "$ADAPTER" ] && ADAPTER_SRC="$MV/adapters/$ADAPTER/${ADAPTER}_engine.c"
B="$ROOT/$PORT/build/spt"
mkdir -p "$B"
SAN="-fsanitize=thread -fno-omit-frame-pointer -g -O1"
cd "$ROOT"
OBJS=""
for f in $SOURCES; do
  o="$B/${f//\//_}.o"
  case "$f" in
    *.cpp|*.cc|*.cxx) g++ $SAN -std=gnu++11 $CFLAGS -I"$PORT/build" -I"$MV/wrapper" -c "$f" -o "$o" ;;
    *) gcc $SAN -std=gnu11 $CFLAGS -I"$PORT/build" -I"$MV/wrapper" -c "$f" -o "$o" ;;
  esac
  OBJS="$OBJS $o"
done
for f in "$MV/tools/sample_page_test.c" "$MV/wrapper/vst2_wrap.c" $ADAPTER_SRC; do
  o="$B/$(basename "$f").o"
  gcc $SAN -std=gnu11 -Wall -I"$PORT/build" -c "$f" -o "$o"
  OBJS="$OBJS $o"
done
g++ $SAN -rdynamic $OBJS $LIBS -ldl -lpthread -o "$B/sample_page_test"
"$B/sample_page_test"
