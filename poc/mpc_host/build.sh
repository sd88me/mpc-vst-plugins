#!/usr/bin/env bash
# Builds the desktop-host prototype (docs/MPC_HOST.md) on x86-64 Linux.
#   poc/mpc_host/build.sh               fetches and builds dynarmic (pinned) and the mpc_host driver
# Needs: git, cmake, ninja, g++, libboost-dev (dynarmic's headers). dynarmic (0BSD) is fetched, never committed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${MPC_HOST_BUILD:-$HERE/build}
DYN_REPO=https://github.com/azahar-emu/dynarmic
DYN_REV=a46601580d5512d324104f985b5f0209dc980ddc
DYN=${DYNARMIC_DIR:-$OUT/dynarmic}
mkdir -p "$OUT"
if [ ! -d "$DYN/.git" ]; then
  git clone -q "$DYN_REPO" "$DYN"
  git -C "$DYN" checkout -q "$DYN_REV"
fi
git -C "$DYN" submodule update -q --init --depth 1 externals/fmt externals/mcl externals/xbyak externals/zydis externals/zycore externals/robin-map
if [ ! -f "$DYN/build/src/dynarmic/libdynarmic.a" ]; then
  cmake -S "$DYN" -B "$DYN/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DDYNARMIC_TESTS=OFF -DDYNARMIC_USE_BUNDLED_EXTERNALS=ON \
        -DDYNARMIC_WARNINGS_AS_ERRORS=OFF -DDYNARMIC_FRONTENDS=A32 >/dev/null
  ninja -C "$DYN/build" >/dev/null
fi
B=$DYN/build
LIBS=$(find "$B" -name '*.a' | grep -v libdynarmic.a | tr '\n' ' ')
g++ -std=c++20 -O2 -g -Wall -I"$DYN/src" -I"$DYN/externals/mcl/include" "$HERE/guest.cpp" "$HERE/main.cpp" \
    "$B/src/dynarmic/libdynarmic.a" $LIBS $LIBS -ldl -o "$OUT/mpc_host"
echo "built $OUT/mpc_host"
