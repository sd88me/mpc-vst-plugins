#!/usr/bin/env python3
"""Writes vst/layout.conf (theme header + every tab). A tab is four rows of eight 158 px cells, as in Clementine-XT's skin: a frame spans
whole cells of one row and each control sits in one cell. The sequencer rows hold 16 smaller knobs each. Several `qlinks` lines in a tab
become Q-Link sub-pages (docs/PORTING.md); a page holds at most 16 keys."""
import sys

OUT = []
Y0, ROW_H, GAP, CELL, X0 = 92, 148, 6, 158, 10

def emit(s): OUT.append(s)
def ry(row): return Y0 + (ROW_H + GAP) * row
def cx(cell): return X0 + 77 + CELL * cell
def tab(name): emit("\n[tab %s]" % name)
def frame(row, cell, n, title): emit('frame x=%d y=%d w=%d h=%d title="%s"' % (X0 + CELL * cell, ry(row), CELL * n - GAP, ROW_H, title))
def knob(row, cell, label, key, r=26): emit('knob cx=%d cy=%d r=%d label="%s" key=%s' % (cx(cell), ry(row) + 72, r, label, key))
def toggle(row, cell, label, key): emit('toggle cx=%d cy=%d label="%s" key=%s' % (cx(cell), ry(row) + 80, label, key))
def popup(row, cell, label, key, w=134): emit('popup cx=%d cy=%d w=%d h=48 label="%s" key=%s' % (cx(cell), ry(row) + 104, w, label, key))
def stepper(row, cell, n, label, key): emit('stepper style=dotmatrix cx=%d cy=%d w=%d h=48 label="%s" key=%s' % (X0 + CELL * cell + (CELL * n - GAP) // 2, ry(row) + 104, CELL * n - 24, label, key))
def readout(row, cell, n, label, key): emit('readout style=dotmatrix cx=%d cy=%d w=%d h=48 label="%s" key=%s' % (X0 + CELL * cell + (CELL * n - GAP) // 2, ry(row) + 104, CELL * n - 24, label, key))
def qlinks(name, keys):
    assert len(keys) <= 16, (name, len(keys))
    emit('qlinks "%s" = %s' % (name, ",".join(keys)))
def row(r, cell, title, items):
    """items: [(label, key)]; key prefix '~' toggle, '^' popup, '' knob."""
    frame(r, cell, len(items), title)
    for i, (label, key) in enumerate(items):
        if key[0] == "~": toggle(r, cell + i, label, key[1:])
        elif key[0] == "^": popup(r, cell + i, label, key[1:])
        else: knob(r, cell + i, label, key)
    return [k.lstrip("~^") for _, k in items]

HEADER = """# Persimmon-PE skin: a charcoal plate with persimmon orange accents, drawn as our own motif (no logos, no traced panel art).
# Regenerate with tools/make_layout.sh (tools/gen_layout.py writes this whole file).
theme_bg=24201f
theme_panel=2c2826
theme_line=e8743b
theme_box=322d2a
theme_ink=f1e6d8
theme_ink_dim=c9b8a6
theme_ink_faint=8a7a6c
theme_accent=e8743b
theme_accent_hi=ffb37a
theme_knob_face=3a3431
theme_knob_ring=141210
theme_knob_dot=ffb37a
theme_seg_active=e8743b
theme_seg_active_tx=1a1716
theme_seg_inactive=4a423e
theme_btn_bg=4a423e
theme_btn_text=f1e6d8
theme_btn_text_plain=f1e6d8
theme_display_bg=1b1615
theme_display_cell=231d1b
theme_display_ink=ff9a52
theme_display_off=3a2c26
theme_display_bezel=e8743b
theme_lcd=1b1615"""

def main():
    emit(HEADER)
    # ---- PROGRAM
    tab("PROGRAM")
    frame(0, 0, 8, "PROGRAM")
    stepper(0, 0, 2, "BANK", "bank")
    readout(0, 2, 2, "", "bank_name")
    stepper(0, 4, 2, "PROGRAM", "program")
    readout(0, 6, 2, "", "patch_name")
    k1 = row(1, 0, "KEYS", [("KEY MODE", "^key_mode"), ("VOICES", "voices"), ("XPOSE", "key_xpose"), ("BEND", "bend_range"),
                            ("SLOP", "slop")])
    k2 = row(1, 5, "OUTPUT", [("VOLUME", "volume"), ("PAN", "^pan"), ("ENV SHAPE", "^env_shape")])
    k3 = row(2, 0, "SEQUENCER", [("RUN", "^seq_run"), ("CLOCK", "^clock_src"), ("BPM", "tempo"), ("DIVIDE", "^clock_div"),
                                 ("TRIGGER", "^trigger"), ("RESET", "seq_reset")])
    frame(2, 6, 2, "INFO")
    readout(2, 6, 2, "STATUS", "status")
    k4 = row(3, 0, "SEQ DESTINATIONS", [("SEQ 1", "seq1_dest"), ("SEQ 2", "seq2_dest"), ("SEQ 3", "seq3_dest"), ("SEQ 4", "seq4_dest"),
                                        ("OSC3 SHP", "^shapeseq3"), ("OSC4 SHP", "^shapeseq4")])
    qlinks("Program", ["program", "bank", "volume", "pan", "key_mode", "key_xpose", "bend_range", "slop",
                       "tempo", "clock_div", "trigger", "seq_run", "seq1_dest", "seq2_dest", "seq3_dest", "seq4_dest"])
    # ---- OSC
    tab("OSC")
    o1 = row(0, 0, "OSC 1 (ANALOG, LEFT)", [("FREQ", "osc1_freq"), ("FINE", "osc1_fine"), ("SHAPE/PW", "osc1_shape"), ("LEVEL", "osc1_level")])
    o2 = row(0, 4, "OSC 2 (ANALOG, RIGHT)", [("FREQ", "osc2_freq"), ("FINE", "osc2_fine"), ("SHAPE/PW", "osc2_shape"), ("LEVEL", "osc2_level")])
    g = row(1, 0, "GLIDE AND SYNC", [("GLIDE 1", "osc1_glide"), ("GLIDE 2", "osc2_glide"), ("SYNC 2>1", "~sync"),
                                     ("GLIDE 3", "osc3_glide"), ("GLIDE 4", "osc4_glide")])
    nz = row(1, 5, "NOISE / INPUT", [("NOISE", "noise_level"), ("EXT IN", "ext_level"), ("IN MODE", "^ext_mode")])
    o3 = row(2, 0, "OSC 3 (DIGITAL, LEFT)", [("FREQ", "osc3_freq"), ("FINE", "osc3_fine"), ("WAVE", "osc3_shape"), ("LEVEL", "osc3_level")])
    o4 = row(2, 4, "OSC 4 (DIGITAL, RIGHT)", [("FREQ", "osc4_freq"), ("FINE", "osc4_fine"), ("WAVE", "osc4_shape"), ("LEVEL", "osc4_level")])
    fm = row(3, 0, "FM / RING MOD", [("FM 4>3", "fm_43"), ("RM 4>3", "rm_43"), ("FM 3>4", "fm_34"), ("RM 3>4", "rm_34")])
    hk = row(3, 4, "HACK", [("IN HACK", "in_hack"), ("OUT HACK", "out_hack")])
    qlinks("Analog", o1 + o2 + ["osc1_glide", "osc2_glide", "sync", "noise_level", "slop", "bend_range", "key_xpose", "volume"])
    qlinks("Digital", o3 + o4 + ["osc3_glide", "osc4_glide", "fm_43", "rm_43", "fm_34", "rm_34", "shapeseq3", "shapeseq4"])
    # ---- FILTER / AMP
    tab("FILTER")
    f1 = row(0, 0, "LOWPASS (ANALOG)", [("FREQ", "lpf_freq"), ("RESO", "lpf_res"), ("ENV AMT", "lpf_env"), ("KEY AMT", "lpf_key"),
                                        ("VELOCITY", "lpf_vel"), ("AUDIO MOD", "lpf_audiomod"), ("L/R SPLIT", "lpf_split"), ("4 POLE", "~poles")])
    fe = row(1, 0, "FILTER ENVELOPE", [("ATTACK", "fenv_a"), ("DECAY", "fenv_d"), ("SUSTAIN", "fenv_s"), ("RELEASE", "fenv_r")])
    va = row(1, 4, "VCA", [("LEVEL", "vca_level"), ("ENV AMT", "vca_env"), ("VELOCITY", "vca_vel"), ("PAN", "^pan")])
    ae = row(2, 0, "AMP ENVELOPE", [("ATTACK", "aenv_a"), ("DECAY", "aenv_d"), ("SUSTAIN", "aenv_s"), ("RELEASE", "aenv_r")])
    hp = row(2, 4, "HIGHPASS / DISTORTION", [("HIGHPASS", "hpf"), ("DISTORT", "dist"), ("VOLUME", "volume"), ("ENV SHAPE", "^env_shape")])
    qlinks("Filter", f1 + fe + ["vca_level", "vca_env", "vca_vel", "hpf"])
    qlinks("Amp", ae + ["vca_level", "vca_env", "vca_vel", "volume", "lpf_freq", "lpf_res", "lpf_env", "hpf", "dist", "fenv_a", "fenv_d", "fenv_r"])
    # ---- FX
    tab("FX")
    fb = row(0, 0, "TUNED FEEDBACK", [("FREQ", "fb_freq"), ("LEVEL", "fb_level"), ("GRUNGE", "~grunge")])
    dd = row(0, 3, "DISTORTION / HACK", [("DISTORT", "dist"), ("HIGHPASS", "hpf"), ("OUT HACK", "out_hack")])
    d1 = row(1, 0, "DELAY TAPS", [("TIME 1", "dly1_time"), ("AMT 1", "dly1_level"), ("TIME 2", "dly2_time"), ("AMT 2", "dly2_level"),
                                  ("TIME 3", "dly3_time"), ("AMT 3", "dly3_level")])
    d2 = row(1, 6, "DELAY FEEDBACK", [("FB 1", "dly_fb1"), ("FB 2", "dly_fb2")])
    qlinks("FX", fb + dd + d1 + d2 + ["volume", "pan"])
    # ---- LFO / ENV 3
    tab("LFO")
    ls = []
    for n in range(4):
        r, c = n // 2, (n % 2) * 4
        ls += row(r, c, "LFO %d" % (n + 1), [("FREQ", "lfo%d_freq" % (n + 1)), ("SHAPE", "^lfo%d_shape" % (n + 1)),
                                            ("AMOUNT", "lfo%d_amt" % (n + 1)), ("DEST", "lfo%d_dest" % (n + 1))])
    e3 = row(2, 0, "ENVELOPE 3", [("DEST", "env3_dest"), ("AMOUNT", "env3_amt"), ("VELOCITY", "env3_vel"), ("DELAY", "env3_delay"),
                                  ("ATTACK", "env3_a"), ("DECAY", "env3_d"), ("SUSTAIN", "env3_s"), ("RELEASE", "env3_r")])
    qlinks("LFOs", ls)
    qlinks("Env 3", e3)
    # ---- MODS
    tab("MODS")
    m = []
    for n in range(4):
        r, c = n // 2, (n % 2) * 4
        m += row(r, c, "MOD %d" % (n + 1), [("SOURCE", "mod%d_src" % (n + 1)), ("AMOUNT", "mod%d_amt" % (n + 1)), ("DEST", "mod%d_dest" % (n + 1))])
    fx1 = row(2, 0, "VELOCITY / MOD WHEEL", [("VEL AMT", "vel_amt"), ("VEL DEST", "vel_dest"), ("WHL AMT", "wheel_amt"), ("WHL DEST", "wheel_dest")])
    fx2 = row(2, 4, "PRESSURE / BREATH", [("PRS AMT", "press_amt"), ("PRS DEST", "press_dest"), ("BRTH AMT", "breath_amt"), ("BRTH DEST", "breath_dest")])
    fx3 = row(3, 0, "FOOT / EXT INPUT", [("FOOT AMT", "foot_amt"), ("FOOT DEST", "foot_dest"), ("PEAK AMT", "peak_amt"), ("PEAK DEST", "peak_dest"),
                                         ("ENVF AMT", "envf_amt"), ("ENVF DEST", "envf_dest")])
    qlinks("Mods", m + ["vel_amt", "vel_dest", "wheel_amt", "wheel_dest"])
    qlinks("Fixed", fx1 + fx2 + fx3[:4] + fx3[4:])
    # ---- SEQ: two tabs, each track on two rows of eight steps, one Q-Link page per track
    for pair in ((1, 2), (3, 4)):
        tab("SEQ %d-%d" % pair)
        for j, t in enumerate(pair):
            keys = []
            for half in range(2):
                items = [("%d" % (8 * half + k + 1), "s%d_%d" % (t, 8 * half + k + 1)) for k in range(8)]
                keys += row(2 * j + half, 0, "SEQUENCE %d  STEPS %d-%d" % (t, 8 * half + 1, 8 * half + 8), items)
            qlinks("Seq %d" % t, keys)
    sys.stdout.write("\n".join(OUT) + "\n")

if __name__ == "__main__":
    main()
