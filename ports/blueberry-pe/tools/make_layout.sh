#!/usr/bin/env bash
# Regenerate vst/params.json, src/patch_tab.h, vst/layout.conf and vst/images/flow_*.svg.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$HERE/tools/gen_patch.py" --params > "$HERE/vst/params.json"
python3 "$HERE/tools/gen_patch.py" --header > "$HERE/src/patch_tab.h"
python3 "$HERE/tools/gen_layout.py"
echo "wrote vst/params.json, src/patch_tab.h, vst/layout.conf ($(grep -c '^\[tab' "$HERE/vst/layout.conf") tabs)"
