#!/usr/bin/env bash
# Offline test of a port's VST3 build (tools/build_vst3.sh), before loading it in a DAW:
#   tools/test_vst3.sh path/to/vst.json [--passthrough] [--shots <dir>]
# Builds the bundle with ASan/UBSan (build/vst3-san), then loads it with tools/vst3_host_test.c: interfaces, parameters, audio
# at 44.1/48/96 kHz, latency, bypass and state. --passthrough: the port is an effect that passes audio through unchanged
# (an analyser), so its output must equal its input delayed by the reported latency. With VST3_VALIDATOR set to Steinberg's
# `validator` (built from the VST3 SDK, outside this repo), the normal build is also run through `validator -e`.
# VST3_TARGET=windows cross-builds the Windows bundle (no sanitizers) and runs the same test under Wine (wine and mingw-w64 needed).
set -euo pipefail
MV="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
eval "$(python3 "$MV/tools/gen_vst.py" "$CFG" --shell)"
if [ "${VST3_TARGET:-}" = windows ]; then
  "$MV/tools/build_vst3.sh" "$CFG" | grep -v '^exported'
  D="$ROOT/$PORT/build/vst3"
  x86_64-w64-mingw32-gcc -O1 -g -std=gnu11 -Wall -Wextra -I"$MV/wrapper" "$MV/tools/vst3_host_test.c" -lm -static -o "$D/vst3_host_test.exe"
  cd "$D"
  WINEDEBUG=-all exec wine ./vst3_host_test.exe "Z:$D/$NAME.vst3/Contents/x86_64-win/$NAME.vst3" "${@:2}"
fi
VST3_SAN=1 "$MV/tools/build_vst3.sh" "$CFG" | grep -v '^exported'
case "$(uname -m)" in x86_64) ARCH=x86_64-linux ;; *) ARCH=aarch64-linux ;; esac
SO="$ROOT/$PORT/build/vst3-san/$NAME.vst3/Contents/$ARCH/$NAME.so"
TEST="$ROOT/$PORT/build/vst3-san/vst3_host_test"
X11F=""
pkg-config --exists x11 && X11F="-DHOST_X11 $(pkg-config --cflags --libs x11)"   # the editor in a hidden X11 window
gcc -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -std=gnu11 -Wall -Wextra -I"$MV/wrapper" \
    "$MV/tools/vst3_host_test.c" -ldl -lm $X11F -o "$TEST"
# the engine's own threads may still be winding down at exit; leaks inside the plugin show up as ASan errors either way
ASAN_OPTIONS="${ASAN_OPTIONS:-detect_leaks=1}" "$TEST" "$SO" "${@:2}"
if [ -n "${VST3_VALIDATOR:-}" ]; then
  "$MV/tools/build_vst3.sh" "$CFG" >/dev/null
  "$VST3_VALIDATOR" -e "$ROOT/$PORT/build/vst3/$NAME.vst3" > "$ROOT/$PORT/build/vst3/validator.log" 2>&1 || true
  grep -E '^Result:' "$ROOT/$PORT/build/vst3/validator.log"
  grep -q 'Result: .* 0 tests failed' "$ROOT/$PORT/build/vst3/validator.log" || { echo "validator failed: build/vst3/validator.log"; exit 1; }
fi
