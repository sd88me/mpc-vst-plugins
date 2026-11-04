#!/usr/bin/env python3
"""Regenerates src/web_page.h from src/web_page.html (the Plugin Manager's web page, served by src/web.c)."""
import json, os
H = os.path.dirname(os.path.abspath(__file__))
page = open(os.path.join(H, "..", "src", "web_page.html")).read()
lines = page.splitlines(keepends=True)
out = "/* src/web_page.html, served by src/web.c; regenerate with vst/gen_web.py */\nstatic const char WEB_PAGE[] =\n"
out += "".join("    %s\n" % json.dumps(l, ensure_ascii=False).replace("?", "\\?") for l in lines) + "    ;\n"
open(os.path.join(H, "..", "src", "web_page.h"), "w").write(out)
