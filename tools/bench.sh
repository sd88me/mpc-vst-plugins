#!/usr/bin/env bash
# CPU stress test for a plugin .so on an MPC OS device (see docs/BENCH.md).
#   tools/bench.sh <plugin.so> <device-ip> [bench args...]   build bench for armhf, run it on the device
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
bin="$here/../build/bench-armhf"
if [ ! -f "$bin" ] || [ "$here/bench.c" -nt "$bin" ]; then
  docker run --rm --platform linux/arm/v7 -u "$(id -u):$(id -g)" -v "$here/..":/b -w /b arm32v7/gcc:11-bullseye \
    gcc -O2 -Wall -o build/bench-armhf tools/bench.c -ldl -lm
fi
scp -q "$bin" "root@$target:/tmp/vstbench"
b=$(basename "$so"); scp -q "$so" "root@$target:/tmp/$b"
# Pin to core 1 (MPC isolates cores 2-3 for its busiest audio workers) at normal priority: MPC's real-time
# threads always win, and the bench times its own thread CPU clock, so preemption doesn't skew the numbers.
ssh "root@$target" "taskset 2 /tmp/vstbench /tmp/$b $*; r=\$?; rm -f /tmp/vstbench /tmp/$b; exit \$r"
