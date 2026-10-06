#!/usr/bin/env python3
"""The Poly Evolver program format as one table: 128 program parameters (in the instrument's own SysEx order) and 64 sequencer steps.

    gen_patch.py --params     -> vst/params.json  (VST parameter list; index = position, append only)
    gen_patch.py --header     -> src/patch_tab.h  (the engine's table: key, range, init value, display format)

Ranges are the manual's (Program Parameter Data, p. 66-71) and agree with the range table in the DSP firmware 3.5 (checked
2026-10-06, all 128 match). Init values are this project's own basic sound, not the factory's.
"""
import json
import sys

# formats (how the engine prints the value): int, note, cents, ashape, wave, s99 (value-99), lfof, lfoamt, dest, sdest, src,
# dtime, glide, xpose, opt (an option list, given), hpf/dist (0-99 post, 100-199 pre), tempo, onoff
LFO_SHAPES = ["Triangle", "Rev Saw", "Sawtooth", "Square", "Random"]
PANS = ["L....R", ".L..R.", "..LR..", ".Mono.", "..RL..", ".R..L.", "R....L"]
TRIGS = ["Seq or Key", "Seq Only", "Key Only", "Key Rst Seq", "Key Gates Seq", "KeyGate SeqRst", "Ext In", "ExtIn RstSeq",
         "ExtIn GateSeq", "ExtIn GtSeqRst", "Key SeqOnce", "Key SeqOnceRst", "ExtIn StepSeq", "Key StepSeq"]
CLKDIV = ["Half", "Quarter", "Eighth", "8 half", "8 swing", "8 trip", "16th", "16 half", "16 swing", "16 trip", "32nd", "32 trip", "64 trip"]
EXTMODE = ["Stereo", "Mono Left", "Mono Right", "LCon RAudio"]
KEYPRI = ["Low", "LowRetrig", "High", "HighRetrg", "Last", "LastRetrg"]
KEYMODES = ["%s %s" % (g, k) for g in ("Poly", "Mono", "Uni1", "Uni2") for k in KEYPRI]
SHAPESEQ = ["Off", "Seq 1", "Seq 2", "Seq 3", "Seq 4"]

def osc(n, analog):
    sh = ("ashape", 102, 0) if analog else ("wave", 127, 0)
    return [("osc%d_freq" % n, "Osc%d Freq" % n, 120, 24, "note"), ("osc%d_fine" % n, "Osc%d Fine" % n, 100, 50, "cents"),
            ("osc%d_shape" % n, "Osc%d Shape" % n, sh[1], sh[2], sh[0]), ("osc%d_level" % n, "Osc%d Level" % n, 100, 50 if analog else 0, "int")]

def lfo(n):
    return [("lfo%d_freq" % n, "LFO%d Freq" % n, 160, 60, "lfof"), ("lfo%d_shape" % n, "LFO%d Shape" % n, 4, 0, LFO_SHAPES),
            ("lfo%d_amt" % n, "LFO%d Amt" % n, 200, 0, "lfoamt"), ("lfo%d_dest" % n, "LFO%d Dest" % n, 68, 0, "dest")]

def mod(n):
    return [("mod%d_src" % n, "Mod%d Source" % n, 24, 0, "src"), ("mod%d_amt" % n, "Mod%d Amt" % n, 198, 99, "s99"),
            ("mod%d_dest" % n, "Mod%d Dest" % n, 68, 0, "dest")]

P = (osc(1, 1) + osc(2, 1) + osc(3, 0) + osc(4, 0) + [
    ("lpf_freq", "LPF Freq", 164, 120, "int"), ("lpf_env", "LPF Env Amt", 198, 99, "s99"),
    ("fenv_a", "FEnv Attack", 110, 0, "int"), ("fenv_d", "FEnv Decay", 110, 40, "int"), ("fenv_s", "FEnv Sustain", 100, 0, "int"),
    ("fenv_r", "FEnv Release", 110, 30, "int"), ("lpf_res", "Resonance", 100, 0, "int"), ("lpf_key", "LPF Key Amt", 100, 0, "int"),
    ("vca_level", "VCA Level", 100, 0, "int"), ("vca_env", "VCA Env Amt", 100, 100, "int"),
    ("aenv_a", "AEnv Attack", 110, 0, "int"), ("aenv_d", "AEnv Decay", 110, 0, "int"), ("aenv_s", "AEnv Sustain", 100, 100, "int"),
    ("aenv_r", "AEnv Release", 110, 30, "int"), ("pan", "Output Pan", 6, 0, PANS), ("volume", "Volume", 100, 75, "int"),
    ("fb_freq", "FBack Freq", 48, 24, "fbnote"), ("fb_level", "FBack Level", 100, 0, "int"), ("grunge", "Grunge", 1, 0, "onoff"),
    ("dly1_time", "Delay1 Time", 166, 70, "dtime"), ("dly1_level", "Delay1 Amt", 100, 0, "int"),
    ("dly_fb1", "Delay FB1", 100, 0, "int"), ("dly_fb2", "Delay FB2", 100, 0, "int"), ("out_hack", "Output Hack", 14, 0, "int")]
    + lfo(1) + lfo(2) + [
    ("env3_amt", "Env3 Amt", 198, 99, "s99"), ("env3_dest", "Env3 Dest", 68, 0, "dest"), ("env3_a", "Env3 Attack", 110, 0, "int"),
    ("env3_d", "Env3 Decay", 110, 40, "int"), ("env3_s", "Env3 Sustain", 100, 0, "int"), ("env3_r", "Env3 Release", 110, 30, "int"),
    ("trigger", "Trigger", 13, 0, TRIGS), ("key_xpose", "Key Xpose", 73, 13, "xpose"),
    ("seq1_dest", "Seq1 Dest", 75, 0, "sdest"), ("seq2_dest", "Seq2 Dest", 75, 0, "sdest"),
    ("seq3_dest", "Seq3 Dest", 75, 0, "sdest"), ("seq4_dest", "Seq4 Dest", 75, 0, "sdest"),
    ("noise_level", "Noise", 100, 0, "int"), ("ext_level", "Ext In", 100, 0, "int"), ("ext_mode", "Input Mode", 3, 0, EXTMODE),
    ("in_hack", "Input Hack", 14, 0, "int"),
    ("osc1_glide", "Osc1 Glide", 200, 0, "glide"), ("sync", "Sync 2>1", 1, 0, "onoff"), ("tempo", "BPM", 250, 120, "tempo"),
    ("clock_div", "Clock Div", 12, 6, CLKDIV), ("osc2_glide", "Osc2 Glide", 200, 0, "glide"), ("slop", "Osc Slop", 5, 0, "int"),
    ("bend_range", "Bend Range", 12, 2, "int"), ("key_mode", "Key Mode", 23, 4, KEYMODES),
    ("osc3_glide", "Osc3 Glide", 200, 0, "glide"), ("fm_43", "FM 4>3", 100, 0, "int"), ("shapeseq3", "Osc3 ShpSeq", 4, 0, SHAPESEQ),
    ("rm_43", "RM 4>3", 100, 0, "int"), ("osc4_glide", "Osc4 Glide", 200, 0, "glide"), ("fm_34", "FM 3>4", 100, 0, "int"),
    ("shapeseq4", "Osc4 ShpSeq", 4, 0, SHAPESEQ), ("rm_34", "RM 3>4", 100, 0, "int"),
    ("poles", "4 Pole", 1, 1, ["2 Pole", "4 Pole"]), ("lpf_vel", "LPF Velocity", 100, 0, "int"),
    ("lpf_audiomod", "Audio Mod", 100, 0, "int"), ("lpf_split", "L/R Split", 100, 0, "int"), ("hpf", "Highpass", 199, 0, "hpf")]
    + mod(1) + [("env_shape", "Env Shape", 1, 0, ["Expo", "Linear"]), ("vca_vel", "VCA Velocity", 100, 0, "int")]
    + mod(2) + mod(3) + mod(4) + [
    ("dly2_time", "Delay2 Time", 166, 70, "dtime"), ("dly2_level", "Delay2 Amt", 100, 0, "int"),
    ("dly3_time", "Delay3 Time", 166, 70, "dtime"), ("dly3_level", "Delay3 Amt", 100, 0, "int"), ("dist", "Distortion", 199, 0, "dist")]
    + lfo(3) + lfo(4) + [
    ("env3_delay", "Env3 Delay", 100, 0, "int"), ("env3_vel", "Env3 Velocity", 100, 0, "int"),
    ("peak_amt", "In Peak Amt", 198, 99, "s99"), ("peak_dest", "In Peak Dest", 68, 0, "dest"),
    ("envf_amt", "In EnvF Amt", 198, 99, "s99"), ("envf_dest", "In EnvF Dest", 68, 0, "dest"),
    ("vel_amt", "Velocity Amt", 198, 99, "s99"), ("vel_dest", "Velocity Dest", 68, 0, "dest"),
    ("wheel_amt", "ModWheel Amt", 198, 99, "s99"), ("wheel_dest", "ModWheel Dest", 68, 0, "dest"),
    ("press_amt", "Pressure Amt", 198, 99, "s99"), ("press_dest", "Pressure Dest", 68, 0, "dest"),
    ("breath_amt", "Breath Amt", 198, 99, "s99"), ("breath_dest", "Breath Dest", 68, 0, "dest"),
    ("foot_amt", "Foot Amt", 198, 99, "s99"), ("foot_dest", "Foot Dest", 68, 0, "dest")])
assert len(P) == 128, len(P)
MIN = {"tempo": 30}

STEPS = [("s%d_%d" % (s, k), "Seq%d Step%d" % (s, k), 102 if s == 1 else 101, 0, "step%d" % (1 if s == 1 else 2))
         for s in range(1, 5) for k in range(1, 17)]

# host-side parameters after the program (append only)
EXTRA = [
    {"key": "bank", "name": "Bank", "min": 0, "max": 63, "default": 0, "display": "int", "dynamic_display": True},
    {"key": "program", "name": "Program", "min": 0, "max": 127, "default": 0, "display": "int", "dynamic_display": True},
    {"key": "patch_name", "name": "Name", "min": 0, "max": 1, "default": 0, "display": "string"},
    {"key": "bank_name", "name": "Bank Name", "min": 0, "max": 1, "default": 0, "display": "string"},
    {"key": "seq_run", "name": "Seq Run", "options": ["Stop", "Run", "Transport"], "default": 0},
    {"key": "clock_src", "name": "Clock", "options": ["Program", "Host"], "default": 1},
    {"key": "seq_reset", "name": "Seq Reset", "min": 0, "max": 1, "default": 0, "momentary": True},
    {"key": "voices", "name": "Voices", "min": 1, "max": 8, "default": 4, "display": "int"},
    {"key": "status", "name": "Status", "min": 0, "max": 1, "default": 0, "display": "string"},
] + [{"key": "%s_%s" % (k, d), "name": "%s %s" % (k.title(), "<" if d == "prev" else ">"), "min": 0, "max": 1, "default": 0,
      "momentary": True, "type": "trigger", "step_of": k, "step_delta": -1 if d == "prev" else 1}
     for k in ("bank", "program") for d in ("prev", "next")]

def params_json():
    out = []
    for key, name, mx, d, fmt in P + STEPS:
        e = {"key": key, "name": name}
        if isinstance(fmt, list):
            e["options"] = fmt
            e["default"] = d
        else:
            e.update({"min": MIN.get(fmt, 0), "max": mx, "default": d, "display": "int"})
            if fmt not in ("int",):
                e["dynamic_display"] = True
        out.append(e)
    out += EXTRA
    return {"name": "Blueberry-PE", "params": out}

def header():
    L = ["/* generated by tools/gen_patch.py: do not edit */", "#pragma once",
         "enum { NPROG = 128, NSTEP = 64, NPATCH = NPROG + NSTEP };",
         "typedef struct { const char *key; short min, max, def; const char *fmt; } ptab_t;",
         "static const ptab_t PTAB[NPATCH] = {"]
    for key, name, mx, d, fmt in P + STEPS:
        f = "opt" if isinstance(fmt, list) else fmt
        L.append('    {"%s", %d, %d, %d, "%s"},' % (key, MIN.get(f, 0), mx, d, f))
    L.append("};")
    for key, name, mx, d, fmt in P:
        if isinstance(fmt, list):
            L.append("static const char *const OPT_%s[] = {%s};" % (key.upper(), ", ".join('"%s"' % o for o in fmt)))
    L.append("enum {")
    for i, (key, *_r) in enumerate(P):
        L.append("    P_%s = %d," % (key.upper(), i))
    L.append("};")
    return "\n".join(L) + "\n"

if __name__ == "__main__":
    if "--params" in sys.argv: print(json.dumps(params_json(), indent=1))
    elif "--header" in sys.argv: sys.stdout.write(header())
    else: sys.exit(__doc__)
