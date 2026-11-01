#!/usr/bin/env bash
# CPU stress test for a plugin .so on an MPC OS device (see docs/BENCH.md).
#   tools/bench.sh <plugin.so> <device-ip> [bench args...]   build bench for the device's CPU (armhf Gen1, aarch64 Gen2), run it there
#   tools/bench.sh <plugin.so> local [bench args...]         build + run on this PC (x86 .so, relative numbers only)
# Nothing is installed: the bench and a copy of the plugin go to /tmp on the device and are removed after.
set -euo pipefail
so="$1"; target="$2"; shift 2
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$here/../build"
if [ "$target" = local ]; then
  gcc -O2 -Wall -o "$here/../build/bench-host" "$here/bench.c" -ldl -lm
  exec "$here/../build/bench-host" "$so" "$@"
fi
# The device's architecture picks the build: Gen1 is armv7 (armhf), Gen2 is aarch64. The plugin .so must match.
arch=$(ssh "root@$target" uname -m)
case "$arch" in
  aarch64) bin="$here/../build/bench-aarch64"; image=arm64v8/gcc:12-bookworm; platform=linux/arm64
           # Gen2 (MPC Live III): MPC's audio workers sit on cores 4-7, the fast cores (Cortex-A76); bench on core 4.
           mask=${BENCH_CPUMASK:-10} ;;
  arm*|armv7*) bin="$here/../build/bench-armhf"; image=arm32v7/gcc:11-bullseye; platform=linux/arm/v7
           # Gen1 (Force): core 1 (MPC isolates cores 2-3 for its busiest audio workers).
           mask=${BENCH_CPUMASK:-2} ;;
  *) echo "unsupported device architecture: $arch" >&2; exit 2 ;;
esac
file "$so" 2>/dev/null | grep -qi "$( [ "$arch" = aarch64 ] && echo aarch64 || echo ARM)" || \
  echo "warning: $so may not be a $arch build" >&2
if [ ! -f "$bin" ] || [ "$here/bench.c" -nt "$bin" ]; then
  docker run --rm --platform "$platform" -u "$(id -u):$(id -g)" -v "$here/..":/b -w /b "$image" \
    gcc -O2 -Wall -o "build/$(basename "$bin")" tools/bench.c -ldl -lm
fi
scp -q "$bin" "root@$target:/tmp/vstbench"
b=$(basename "$so"); scp -q "$so" "root@$target:/tmp/$b"
# Pinned at normal priority: MPC's real-time threads always win, and the bench times its own thread CPU clock,
# so preemption doesn't skew the numbers.
ssh "root@$target" "taskset $mask /tmp/vstbench /tmp/$b $*; r=\$?; rm -f /tmp/vstbench /tmp/$b; exit \$r"
