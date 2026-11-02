#!/usr/bin/env python3
"""Generate everything a port needs from one small vst.json (used by tools/build_port.sh).

    gen_vst.py <port>/vst.json            -> <port>/build/params.h, skin/<vendor> - VST - <name>/, pluginlist-entry.xml
    gen_vst.py <port>/vst.json --shell    print the build settings as shell variables (for build_port.sh)
    gen_vst.py <port>/vst.json --params-h only <port>/build/params.h (no skin; for tools/test_port.sh)

vst.json (paths are relative to the vst.json's folder):
    {
      "name": "My Synth", "vendor": "me", "uid": "MySy", "version": 1000,
                                                 # VST2 int major*1000+minor*100+patch*10+build (3.1.2 -> 3120):
                                                 # PLUG_VERSION and the skin's version.xml (one digit each for
                                                 # minor/patch/build; docs/PORTING.md)
      "so": "my_synth.so",                       # lives in the plugin folder /sdcard/Synths/<vendor> - VST - <name>/
      "params": "params.json",                   # parameter list (tools/params.py), in VST index order
      "layout": "layout.conf",                   # optional; without it the skin studio's auto-layout is used
      "short_names": {"LFO1 > ": "L1 "},          # optional on-screen name shortening
      "art": "html",                             # optional: draw the skin artwork in a browser (tools/html_art.py)
      "tile": "art/tile.png",                    # optional: 270x110 Instruments-browser tile (+ a Default preset; tools/xpl.py)
      "effect": true,                            # optional: an audio effect (2 inputs, category Effect); the engine provides process()
      "skin_post": "skin_post.py",               # optional: run as `python3 skin_post.py <skin dir>` after the skin is built, to
                                                 #   adjust TUI.json the layout can't express (e.g. per-role live-text sizes/colours)
      "presets": "presets.json",                 # optional: the wrapper's own presets, listed in MPC's PRESET menu
      "programs": {"param": "preset"},           # optional instead: the engine's own preset parameter as that list
                                                 #   (both: program_lines() below)
      "cc": false, "nrpn": false,                # optional: no CC 20-35 -> first page's Q-Links / no NRPN -> any parameter
                                                 #   (both on by default; cc_lines() below)
      "custom_skin": true,                       # optional: params.h + plugin-list entry only; the port makes the skin itself
      "defines": {"HAS_LFO_BPM": 1},             # optional extra #defines in params.h
                                                 #   (HAS_LFO_BPM: host tempo as "lfo_bpm"; HAS_TRANSPORT: play/stop as "transport";
                                                 #   HAS_SONG_POS: the engine's song_pos(ppq, bpm, playing, frames) every block, for a MIDI generator)
                                                 #   (HAS_DISPLAY_REV: the DSP changes values by itself; the wrapper polls its "display_rev" and
                                                 #   refreshes the host; PARAM_TEXT_MAX: readout length, default 24 -- see wrapper/vst2_wrap.c)
      "build": {"root": "..", "sources": ["src/engine.c"], "cflags": ["-Isrc"], "libs": ["-lm"]}
                                                 #   "cflags_arm": [..] -- extra flags for the armhf device build only (not the x86 host test), e.g. ["-mfpu=neon"]
                                                 #   "cflags_aarch64": [..] -- the same for the Gen2 (aarch64) build
      "targets": ["armv7", "aarch64"],           # optional: device builds tools/build_port.sh makes (default ["armv7"] = Gen1 MPC / Force;
                                                 #   aarch64 = Gen2, docs/GEN2.md). `build_port.sh vst.json aarch64` builds just one.
    }
The sources provide mpc_engine() (wrapper/engine.h). An engine from another ecosystem names its own
parameter source instead of "params" and gets its adapter linked in (adapters/<name>/README.md).
The VST parameter index of each key is its position in the list; skins bind to it as "Parameter N".
A layout's popups add one hidden "<key>__open" param each, after the list.
Keep uid and so fixed across releases, and never reorder the list (saved projects store values by index): <port>/params.lock
(written on the first build, commit it) fails the build when an existing key changes index (check_lock() below).
"""
import json
import os
import shlex
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import params  # noqa: E402


def load(path):
    cfg = json.load(open(path))
    for k in ("name", "vendor", "uid", "so"):
        if k not in cfg:
            sys.exit("vst.json: missing %r" % k)
    if len(cfg["uid"]) != 4:
        sys.exit("vst.json: uid must be 4 characters (e.g. 'MzVc')")
    return cfg


def c_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def fl(x):
    return repr(float(x)) + "f"


def short(name, table):
    for a, b in table.items():
        name = name.replace(a, b)
    return name


def layout_warnings(cfg):
    """A port whose data folder is a fixed /sdcard or /media path breaks when the plugin folder is installed elsewhere
    (the portable layout, a card). MODULE_SUBDIR finds the folder next to the .so instead (wrapper/plugin_dir.h)."""
    d = cfg.get("defines", {})
    bad = [k for k, v in d.items() if isinstance(v, str) and ("/sdcard" in v or "/media/" in v)]
    if bad and "MODULE_SUBDIR" not in d:
        return ["%s hardcodes a device path (%s): set MODULE_SUBDIR so the data is found next to the .so "
                "(docs/PORTING.md); an absolute MODULE_DIR may stay as the fallback" % (cfg.get("name", "port"), ", ".join(bad))]
    return []


def check_lock(here, plist):
    """<port>/params.lock: the parameter keys in VST index order, written on the first build and extended as keys are appended.
    Saved projects, automation and Q-Link maps store parameters by index, so an existing key that moves (a param inserted
    mid-list, a reorder) fails the build; a key removed from the end is only a warning. GEN_VST_RELOCK=1 rewrites the file
    (a deliberate break, before a first release). The layout's hidden popup params come after the list and are not locked."""
    path = os.path.join(here, "params.lock")
    keys = [p["key"] for p in plist]
    if os.path.exists(path) and os.environ.get("GEN_VST_RELOCK") != "1":
        locked = [k for k in open(path).read().split() if k]
        for i, k in enumerate(locked):
            if i >= len(keys):
                print("warning: params.lock: %d locked key(s) from %r on are gone (removed from the end)" % (len(locked) - i, k),
                      file=sys.stderr)
                return
            if keys[i] != k:
                sys.exit("params.lock: parameter %d was %r and is now %r. Saved projects, automation and skins bind by index: "
                         "append new params at the end, never insert or reorder (GEN_VST_RELOCK=1 to accept the break)" % (i, k, keys[i]))
        if len(keys) == len(locked):
            return
    open(path, "w").write("".join(k + "\n" for k in keys))
    print("params.lock: %d keys" % len(keys))


def shown_keys(cfg, here, plist):
    """The param keys the skin's layout mentions anywhere (a widget's key=, get=, when=, a list, a qlinks line), or None when that
    can't be known (no layout: the auto-layout shows everything; custom_skin / skin_post: something else touches the skin; a widget
    value with a pattern such as %d). A "display":"string" param outside it is never polled (gen_params), unless "poll": true."""
    if not cfg.get("layout") or cfg.get("custom_skin") or cfg.get("skin_post"):
        return None
    import re
    import shadow_skin
    tabs, top = shadow_skin.parse_layout(os.path.join(here, cfg["layout"]))
    texts = list(top)
    for t in tabs:
        for w in t["widgets"]:
            for v in w.values():
                texts.append(",".join(x if isinstance(x, str) else ",".join(str(y) for y in x) for x in v) if isinstance(v, list)
                             else v if isinstance(v, str) else "")
        for _, ks in t["qlinks"]:
            texts.append(",".join(ks))
    if any(c in x for x in texts for c in "%*{$"):
        return None
    words = set()
    for x in texts:
        words.update(re.findall(r"[A-Za-z0-9_]+", x))
    # a list widget's key=bank_slot stands for bank_slot_1 .. bank_slot_N (its tiles), so a trailing _<number> counts as mentioned too
    return {p["key"] for p in plist if p["key"] in words or re.sub(r"_\d+$", "", p["key"]) in words}


def gen_params(cfg, params, out, shown=None):
    for w in layout_warnings(cfg):
        print("warning: " + w, file=sys.stderr)
    sn = cfg.get("short_names", {})
    lines = ["/* generated by mpc-vst-plugins tools/gen_vst.py from vst.json + the port's parameters: do not edit */",
             "#pragma once",
             "typedef struct { const char *key, *name, *unit; float min, max, def; int nopts; "
             "const char *const *opts; int momentary; int string_display; int int_display; "
             "int step_target; float step_delta; int popup_of; int hold_ms; int dynamic_name; int dynamic_display; "
             "int qlink_ticks; int no_poll; int nudge_pct; int nudge_gain; int refresh_display; int debounce_ms; } param_t;"]
    key_to_index = {p["key"]: i for i, p in enumerate(params)}
    rows = []
    for i, p in enumerate(params):
        opts = p.get("options") or []
        name = c_str(short(p.get("name", p["key"]), sn))
        # "display":"string" -- the DSP's get_param() returns real text (a bank/patch name, a
        # status string), not a number to reformat. Without this, effGetParamDisplay's default
        # atof()-and-reformat path mangles any non-numeric string down to "0" (see docs/NOTES.md).
        is_str = int(p.get("display") == "string")
        # "display":"int" -- force whole-number display regardless of range. Without this, a
        # narrow-range param (e.g. octave -4..4) shows one decimal place ("0.0") since the default
        # heuristic (range > 20 -> 0 decimals, else 1) assumes a narrow range means a fine-grained
        # continuous value; every jv880 param is a plain integer, narrow range or not.
        is_int = int(p.get("display") == "int")
        # "step_of"/"step_delta" -- a momentary trigger that nudges a DIFFERENT param by a fixed
        # amount, for a DSP with no native "next X"/"prev X" verb (e.g. jv880 has no "next preset",
        # only an absolute set_param("preset", N)). The wrapper reads that param's CURRENT value
        # straight from the DSP, adds step_delta, clamps to its min/max, and sets it back -- see
        # docs/NOTES.md. This trigger's OWN key is never sent to the DSP at all.
        step_target = key_to_index.get(p.get("step_of"), -1)
        step_delta = p.get("step_delta", 0)
        # "popup_of" -- a layout popup's hidden "open" flag (shadow_skin.popup_params): the wrapper
        # keeps its value itself, never sends it to the DSP, and clears it when that param is picked.
        popup_of = key_to_index.get(p.get("popup_of"), -1)
        # "dynamic_name" -- effGetParamName asks the DSP for get_param("<key>_name") first, falling back
        # to the static name. MPC re-reads a Label "Name" on audioMasterUpdateDisplay (docs/NOTES.md,
        # "Dynamic text in skins"), so a knob's own native label can follow e.g. the selected machine.
        dyn = int(bool(p.get("dynamic_name")))
        # "dynamic_display" -- likewise for the value text (effGetParamDisplay): get_param("<key>_display")
        # first. The value itself stays numeric, so knobs, Q-Links and automation work as usual.
        dyn_disp = int(bool(p.get("dynamic_display")))
        # "qlink_ticks" -- small moves (Q-Link or data wheel events) per option, or per integer step, for an
        # option list or a "display": "int" param. 0 or 1 = every move steps (settle() in vst2_wrap.c). Short
        # ranges a slow Q-Link turn races through (a MIDI channel, a list of sets) want more; the data wheel then
        # takes that many clicks per step too, since MPC sends both alike.
        qticks = int(p.get("qlink_ticks", 0))
        # "poll": false -- a "display":"string" param the wrapper should not poll for "<key>_on" (every 10 ms) and
        # for text changes (every 100 ms; housekeeping in vst2_wrap.c): a readout that only changes on a tap, or
        # one whose get_param() is costly. Left out of the polling too, without saying so: one the layout never mentions
        # (shown_keys); "poll": true polls it anyway (for example text the automation screen lists but the skin does not).
        # A param the layout never mentions has nothing on screen to refresh, so it is not polled either ("poll": true keeps it).
        no_poll = int(p.get("poll", True) is False or (is_str and "poll" not in p and shown is not None and p["key"] not in shown))
        # "nudge_pct" -- for a long "display": "int" list (a bank list of up to 998): any move up to this percent of the range
        # (a Q-Link event is 1/128 of it, a wheel click 1/100) is ONE step in its direction instead of crossing eight to ten
        # entries; a bigger move (automation, a drag) still sets the value outright. 0 = off. Combine with qlink_ticks to
        # slow it further. 10 suits a Q-Link and the wheel.
        nudge = int(p.get("nudge_pct", 0))
        # "nudge_gain" -- for a continuous or whole-number knob: multiply the small moves (a data wheel click is 1/100 of the range,
        # a Q-Link event 1/128) by this, so the jog wheel crosses 0-127 in fewer clicks. 0 or 1 = off; a drag or a jump (a move of 2%
        # of the range or more) is never scaled. 3 = about 40 clicks end to end.
        ngain = int(p.get("nudge_gain", 0))
        # "refresh_display": true -- a host write of this param also asks MPC for an audioMasterUpdateDisplay, for text that
        # depends on it and is not polled: a "poll": false readout bound with get=, another param's dynamic_name/_display.
        # Off by default: MPC answers every UpdateDisplay by rebuilding its parameter screen, and doing that on each host
        # write broke Q-Links on the automation screen (docs/NOTES.md, 2026-10-21). Polled readouts refresh on their own.
        refresh = int(bool(p.get("refresh_display")))
        # MPC delivers one tap on a drawn button as two presses 30-140 ms apart (the finger going down and lifting; Live III, 2026-10-30), so a
        # momentary param ignores a second press within debounce_ms (default 250) of the last one it acted on; "debounce_ms": 0 turns it off
        debounce = int(p.get("debounce_ms", 250 if p.get("momentary") else 0))
        if opts:
            lines.append("static const char *const OPTS_%d[] = {%s};" % (i, ", ".join(c_str(o) for o in opts)))
            d = p.get("default", 0)
            if isinstance(d, str):
                d = opts.index(d) if d in opts else 0
            norm = d / (len(opts) - 1) if len(opts) > 1 else 0
            rows.append("    {%s, %s, \"\", 0, 0, %s, %d, OPTS_%d, %d, %d, %d, %d, %s, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d}," % (
                c_str(p["key"]), name, fl(norm), len(opts), i, bool(p.get("momentary")), is_str, is_int,
                step_target, fl(step_delta), popup_of, p.get("hold_ms", 0), dyn, dyn_disp, qticks, no_poll, nudge, ngain, refresh, debounce))
        else:
            lo, hi = p.get("min", 0), p.get("max", 1)
            d = p.get("default", lo)
            norm = (d - lo) / (hi - lo) if hi > lo else 0
            rows.append("    {%s, %s, %s, %s, %s, %s, 0, 0, %d, %d, %d, %d, %s, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d}," % (
                c_str(p["key"]), name, c_str(p.get("unit", "")), fl(lo), fl(hi), fl(norm),
                bool(p.get("momentary")), is_str, is_int, step_target, fl(step_delta), popup_of, p.get("hold_ms", 0), dyn, dyn_disp,
                qticks, no_poll, nudge, ngain, refresh, debounce))
    lines += ["static const param_t PARAMS[] = {"] + rows + ["};", "#define NPARAMS %d" % len(params),
              "#define PLUG_NAME %s" % c_str(cfg["name"]), "#define PLUG_VENDOR %s" % c_str(cfg["vendor"]),
              "#define PLUG_UID 0x%08x /* '%s' */" % (int.from_bytes(cfg["uid"].encode(), "big"), cfg["uid"]),
              "#define PLUG_VERSION %d" % cfg.get("version", 1000)]
    lines += ["#define %s %s" % (k, v) for k, v in cfg.get("defines", {}).items()]
    # "live": true on a param -- the engine changes it by itself (a status readout, a progress value), not only when the host
    # writes it. host_test skips these in its "parameter 0 toggle changes nothing" check (PLUG_LIVE / PLUG_LIVE_COUNT).
    live = [i for i, q in enumerate(params) if q.get("live")]
    if live:
        lines += ["static const int PLUG_LIVE[] = {%s};" % ", ".join(str(i) for i in live), "#define PLUG_LIVE_COUNT %d" % len(live)]
    # "legacy": true on a param -- kept in the table only so saved projects and automation keep their indices, and not on any
    # screen. host_test never picks these as the representative knob, option list or whole number of its checks.
    legacy = [i for i, q in enumerate(params) if q.get("legacy")]
    if legacy:
        lines += ["static const int PLUG_LEGACY[] = {%s};" % ", ".join(str(i) for i in legacy), "#define PLUG_LEGACY_COUNT %d" % len(legacy)]
    if cfg.get("effect"):
        lines.append("#define PLUG_EFFECT 1")
    lines += program_lines(cfg, params, key_to_index)
    lines += cc_lines(cfg, params, key_to_index)
    open(out, "w").write("\n".join(lines) + "\n")


def preset_value(p, v, where):
    """A preset's value for parameter p, as the string the engine's set_param() gets (what the wrapper itself sends:
    an option's index, a whole number, or a number in the parameter's own units)."""
    opts = [str(o) for o in p.get("options") or []]
    if opts:
        if isinstance(v, str) and v in opts:
            return str(opts.index(v))
        if isinstance(v, str) and v.lower() in [o.lower() for o in opts]:
            return str([o.lower() for o in opts].index(v.lower()))
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(opts):
            return str(v)
        raise SystemExit("%s: %s=%r is not one of %s" % (where, p["key"], v, ",".join(opts)))
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SystemExit("%s: %s=%r is not a number" % (where, p["key"], v))
    lo, hi = p.get("min", 0), p.get("max", 1)
    if not lo <= v <= hi:
        raise SystemExit("%s: %s=%g is outside %g..%g" % (where, p["key"], v, lo, hi))
    return str(int(round(v))) if p.get("display") == "int" else "%g" % v


def program_lines(cfg, params, key_to_index):
    """VST programs, so MPC's PRESET menu lists them (docs/NOTES.md 2026-10-07):
       "presets": "presets.json"  -- the wrapper's own presets: {"presets": [{"name": "Init", "values": {key: value}}]}
                                     (or the bare list); values in the parameter's own units or an option's label
       "programs": {"param": key} -- the engine's own preset parameter: one program per option (named by the
                                     option), or per whole number of its range (named by get_param("<key>:<n>") when
                                     the engine answers, else "<name> <n>")."""
    if cfg.get("presets") and cfg.get("programs"):
        raise SystemExit("vst.json: use \"presets\" or \"programs\", not both")
    if cfg.get("presets"):
        here = os.path.dirname(os.path.abspath(sys.argv[1]))
        d = json.load(open(os.path.join(here, cfg["presets"])))
        presets = d["presets"] if isinstance(d, dict) else d
        if not presets:
            raise SystemExit("%s: no presets" % cfg["presets"])
        out = ["typedef struct { int param; const char *value; } preset_value_t;",
               "typedef struct { const char *name; int n; const preset_value_t *values; } preset_t;"]
        rows = []
        for n, pr in enumerate(presets):
            where = "%s: preset %r" % (cfg["presets"], pr.get("name", n))
            vals = []
            for k, v in pr.get("values", {}).items():   # in file order: the engine may need one set first
                if k not in key_to_index:
                    raise SystemExit("%s: %r is not a parameter" % (where, k))
                vals.append("{%d, %s}" % (key_to_index[k], c_str(preset_value(params[key_to_index[k]], v, where))))
            if not vals:
                raise SystemExit("%s: no values" % where)
            out.append("static const preset_value_t PRESET_%d[] = {%s};" % (n, ", ".join(vals)))
            rows.append("{%s, %d, PRESET_%d}" % (c_str(str(pr["name"])[:24]), len(vals), n))
        out += ["static const preset_t PRESETS[] = {%s};" % ", ".join(rows), "#define NPRESETS %d" % len(presets)]
        return out
    if cfg.get("programs"):
        k = cfg["programs"].get("param")
        if k not in key_to_index:
            raise SystemExit("vst.json programs: param %r is not a parameter" % k)
        p = params[key_to_index[k]]
        n = len(p.get("options") or []) or int(round(p.get("max", 0) - p.get("min", 0))) + 1
        if n < 2 or not (p.get("options") or p.get("display") == "int"):
            raise SystemExit("vst.json programs: %r must be an option list or a \"display\": \"int\" range" % k)
        return ["#define PROG_PARAM %d" % key_to_index[k], "#define NPROGRAMS %d" % min(n, 1024)]
    return []


def cc_lines(cfg, params, key_to_index):
    """MIDI control from outside the screen (wrapper/vst2_wrap.c midi_control()):
       CC 20-35 move the first tab's first `qlinks` line, slot by slot (column 1 top to bottom = CC 20-23, column 2 =
       24-27, ...; "-", triggers and text displays get none); vst.json "cc": false turns it off.
       NRPN n (CC 99/98, value on CC 6, fine on 38) sets parameter n, on any page; "nrpn": false turns it off."""
    out = []
    if cfg.get("cc", True) and cfg.get("layout"):
        import shadow_skin
        here = os.path.dirname(os.path.abspath(sys.argv[1]))
        tabs, _ = shadow_skin.parse_layout(os.path.join(here, cfg["layout"]))
        keys = tabs[0]["qlinks"][0][1] if tabs and tabs[0]["qlinks"] else []
        cc = []
        for k in keys[:16]:
            p = params[key_to_index[k]] if k in key_to_index else None
            ok = p is not None and not p.get("momentary") and p.get("display") != "string" and not p.get("step_of")
            cc.append(key_to_index[k] if ok else -1)
        if any(i >= 0 for i in cc):
            out += ["static const int PLUG_CC[16] = {%s};" % ", ".join(str(i) for i in cc + [-1] * (16 - len(cc))),
                    "#define HAS_CC_MAP 1"]
    if cfg.get("nrpn", True):
        out.append("#define HAS_NRPN 1")
    return out


def entry(cfg):
    fx = bool(cfg.get("effect"))
    return ('<PLUGIN name="{n}" descriptiveName="{n}" format="VST" category="{c}" manufacturer="{v}" version="1.0" '
            'file="/sdcard/Synths/{v} - VST - {n}/{so}" uid="{u:x}" isInstrument="{i}" fileTime="0" infoUpdateTime="0" numInputs="{ni}" '
            'numOutputs="2" isShell="0"/>').format(n=cfg["name"], v=cfg["vendor"], so=cfg["so"], c="Effect" if fx else "Synth",
                                                  i=0 if fx else 1, ni=2 if fx else 0,
                                                  u=int.from_bytes(cfg["uid"].encode(), "big"))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = os.path.abspath(sys.argv[1])
    here = os.path.dirname(path)
    cfg = load(path)
    build = os.path.join(here, "build")
    src, adapter = params.source(cfg)
    if sys.argv[2:] == ["--shell"]:
        b = cfg.get("build", {})
        root = os.path.normpath(os.path.join(here, b.get("root", ".")))
        for k, v in (("ROOT", root), ("PORT", os.path.relpath(here, root)), ("SO", cfg["so"]), ("NAME", cfg["name"]),
                     ("SOURCES", " ".join(b.get("sources", []))), ("CFLAGS", " ".join(b.get("cflags", []))),
                     ("CFLAGS_ARM", " ".join(b.get("cflags_arm", []))),
                     ("CFLAGS_A64", " ".join(b.get("cflags_aarch64", []))),
                     ("TARGETS", " ".join(cfg.get("targets", ["armv7"]))),
                     ("LIBS", " ".join(b.get("libs", ["-lm"]))),
                     ("LAYOUT", "1" if cfg.get("layout") else ""),
                     ("TITLE_FONT", cfg.get("title_font", "")),
                     ("ART", cfg.get("art", "")),
                     ("ADAPTER", adapter or "")):
            print("%s=%s" % (k, shlex.quote(v)))
        return
    plist, sections = params.load(os.path.join(here, src))
    check_lock(here, plist)
    import shadow_skin
    if cfg.get("layout"):
        plist = plist + shadow_skin.popup_params(os.path.join(here, cfg["layout"]), plist)
    os.makedirs(build, exist_ok=True)
    shown = shown_keys(cfg, here, plist)
    gen_params(cfg, plist, os.path.join(build, "params.h"), shown)
    skipped = [p["key"] for p in plist if p.get("display") == "string" and "poll" not in p and shown is not None and p["key"] not in shown]
    print("params.h: %d params%s" % (len(plist), "; %d text param(s) the layout never shows are not polled" % len(skipped) if skipped else ""))
    if sys.argv[2:] == ["--params-h"]:
        return
    open(os.path.join(build, "pluginlist-entry.xml"), "w").write(entry(cfg) + "\n")
    if cfg.get("custom_skin"):   # the port builds its own skin folder (e.g. from data it can't ship): nothing more to do
        print("custom_skin: the port builds its skin")
        return

    if cfg.get("layout"):
        layout = os.path.join(here, cfg["layout"])
    else:
        import studio
        ps, sections = studio.load_params(os.path.join(here, src))
        layout = os.path.join(build, "layout.auto.conf")
        open(layout, "w").write(studio.auto_layout(ps, sections))
        print("no layout in vst.json: auto-layout written to", layout)
    import shutil
    shutil.rmtree(os.path.join(build, "skin"), ignore_errors=True)   # no stale images from older builds
    art = os.environ.get("SHADOW_ART") or (os.path.join(TOOLS, "html_art.py") if cfg.get("art") == "html"
                                           else os.path.join(build, "shadow_art"))
    skin = shadow_skin.write_skin(os.path.join(build, "skin"), cfg["vendor"], cfg["name"], layout, plist, art,
                                  version=cfg.get("version", 1000))
    print("skin:", skin)
    import skin_check   # overlapping touch boxes, boxes off the screen, Q-Links on unseen parameters
    for f in skin_check.check(skin):
        sys.stderr.write("warning: skin: %s\n" % f)
    if cfg.get("skin_post"):   # the port's own TUI.json touch-ups; a non-zero exit fails the build
        import subprocess
        subprocess.run([sys.executable, os.path.join(here, cfg["skin_post"]), skin], cwd=here, check=True)
    if cfg.get("tile"):   # the browser tile only does something with a preset to open: ship a Default one with it
        import xpl
        print("tile:", xpl.write_tile(os.path.join(here, cfg["tile"]), skin))
        print("preset:", xpl.write_default_preset(skin, cfg["name"], cfg["vendor"], cfg["uid"], cfg["so"],
                                                  cfg.get("version", 1000), bool(cfg.get("effect"))))


if __name__ == "__main__":
    main()
