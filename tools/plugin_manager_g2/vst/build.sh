#!/usr/bin/env bash
# Build the Plugin Manager with mpc-vst-plugins' generic port builder (vst.json).
#   vst/build/plugin_manager.so, vst/build/skin/<folder>/, vst/build/pluginlist-entry.xml
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
MPC_VST="${MPC_VST:-$here/../../..}"
[ -x "$MPC_VST/tools/build_port.sh" ] || { echo "need an mpc-vst-plugins checkout (MPC_VST)" >&2; exit 1; }
exec "$MPC_VST/tools/build_port.sh" "$here/vst.json"
