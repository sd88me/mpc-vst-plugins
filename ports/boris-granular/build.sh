#!/usr/bin/env bash
# Build Boris Granular as an MPC OS VST2 effect: skin, params.h, .so and plugin-list entry in vst/build/.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/../../tools/build_port.sh" "$here/vst/vst.json"
