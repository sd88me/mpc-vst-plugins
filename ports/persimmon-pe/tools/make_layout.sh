#!/usr/bin/env bash
# Regenerate vst/params.json, src/patch_tab.h and vst/layout.conf.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$HERE/tools/gen_patch.py" --params > "$HERE/vst/params.json"
python3 "$HERE/tools/gen_patch.py" --header > "$HERE/src/patch_tab.h"
python3 "$HERE/tools/gen_layout.py" > "$HERE/vst/layout.conf"
echo "wrote vst/params.json, src/patch_tab.h, vst/layout.conf ($(grep -c '^\[tab' "$HERE/vst/layout.conf") tabs)"
