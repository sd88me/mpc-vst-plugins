#!/usr/bin/env python3
"""Regenerates src/plugin_list_awk.h from the installer's plugin_list.awk (MPC_VST: the mpc-vst-plugins checkout)."""
import os
H = os.path.dirname(os.path.abspath(__file__))
mv = os.environ.get("MPC_VST", os.path.join(H, "..", "..", ".."))
awk = open(os.path.join(mv, "tools", "release", "plugin_list.awk")).read()
body = "\n".join('    "%s\\n"' % l.replace("\\", "\\\\").replace('"', '\\"') for l in awk.split("\n"))
open(os.path.join(H, "..", "src", "plugin_list_awk.h"), "w").write(
    "/* the installer's MPC.settings editor (mpc-vst-plugins tools/release/plugin_list.awk), used to register a folder; regenerate with vst/gen_awk.py */\n"
    "static const char PLUGIN_LIST_AWK[] =\n%s;\n" % body)
