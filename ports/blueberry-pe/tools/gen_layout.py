#!/usr/bin/env python3
"""Writes vst/layout.conf and the signal-flow drawings vst/images/flow_*.svg.

The look takes its cues from the instrument's panel without copying it: an ultramarine plate, brighter rounded blue
sections, black pointer knobs, red LEDs, a grey LCD and amber signal-flow lines with arrows between the sections. The
tabs follow the panel's sections in signal order. Geometry is absolute (plugin area x 0-1280, y 92-720): a control sits
in a 140 px cell (MPC's value box under a knob is 130 px wide), a section row is 148 px tall. A page holds at most 16
Q-Link keys; several `qlinks` lines in a tab become sub-pages."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VST = os.path.join(HERE, "..", "vst")
OUT = []
CELL, ROW = 140, 150
FLOW = "#f5b400"

def emit(s): OUT.append(s)
def Y(i): return 92 + 154 * i     # section rows: 146 px sections, 8 px apart
def tab(name): emit("\n[tab %s]" % name)
def qlinks(name, keys):
    assert len(keys) <= 16, (name, len(keys))
    emit('qlinks "%s" = %s' % (name, ",".join(keys)))

def section(x, y, title, rows):
    """A frame whose rows are lists of (label, key); '~' marks a toggle (LED), '^' a popup, '' a knob, None an empty cell.
    Returns (keys in order, frame box)."""
    n = max(len(r) for r in rows)
    w, h = CELL * n, ROW * len(rows) - 4
    emit('frame x=%d y=%d w=%d h=%d title="%s"' % (x, y, w, h, title))
    keys = []
    for ri, items in enumerate(rows):
        ry = y + ROW * ri
        for ci, it in enumerate(items):
            if it is None:
                continue
            label, key = it
            cx = x + CELL * ci + CELL // 2
            if key[0] == "~":
                emit('toggle cx=%d cy=%d label="%s" key=%s look=led' % (cx, ry + 64, label, key[1:]))
            elif key[0] == "^":
                emit('popup cx=%d cy=%d w=126 h=48 label="%s" key=%s' % (cx, ry + 96, label, key[1:]))
            else:
                emit('knob cx=%d cy=%d r=24 label="%s" key=%s' % (cx, ry + 56, label, key))
            keys.append(key.lstrip("~^"))
    return keys, (x, y, w, h)

# ---- signal-flow drawings (one SVG per tab, drawn into the page background under the sections)
class Flow:
    def __init__(self, name):
        self.name, self.parts = name, []
    def line(self, *pts, arrow=True, dot=True):
        d = "M" + " L".join("%d,%d" % (x, y - 92) for x, y in pts)
        self.parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="3" stroke-linejoin="round"/>' % (d, FLOW))
        if dot:
            x, y = pts[0]
            self.parts.append('<circle cx="%d" cy="%d" r="5.5" fill="%s"/>' % (x, y - 92, FLOW))
        if arrow:
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            y0, y1 = y0 - 92, y1 - 92
            if x1 != x0:
                s = 1 if x1 > x0 else -1
                p = "%d,%d %d,%d %d,%d" % (x1, y1, x1 - 13 * s, y1 - 7, x1 - 13 * s, y1 + 7)
            else:
                s = 1 if y1 > y0 else -1
                p = "%d,%d %d,%d %d,%d" % (x1, y1, x1 - 7, y1 - 13 * s, x1 + 7, y1 - 13 * s)
            self.parts.append('<polygon points="%s" fill="%s"/>' % (p, FLOW))
    def label(self, x, y, text, anchor="start"):
        self.parts.append('<text x="%d" y="%d" font-family="Titillium Web, sans-serif" font-weight="700" font-size="15" '
                          'letter-spacing="2" fill="%s" text-anchor="%s">%s</text>' % (x, y - 92, FLOW, anchor, text))
    def write(self):
        os.makedirs(os.path.join(VST, "images"), exist_ok=True)
        path = os.path.join(VST, "images", "flow_%s.svg" % self.name)
        with open(path, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="628" viewBox="0 0 1280 628">\n%s\n</svg>\n'
                    % "\n".join(self.parts))
        emit('art file=images/flow_%s.svg x=0 y=92 w=1280 h=628' % self.name)

def wordmark(x, y, w=300, h=96):
    emit('art file=images/wordmark.svg x=%d y=%d w=%d h=%d' % (x, y, w, h))

def mid(b): return b[1] + b[3] // 2
def right(b): return b[0] + b[2]
def bottom(b): return b[1] + b[3]

HEADER = """# Blueberry-PE skin: an ultramarine plate with rounded blue sections, black pointer knobs, red LEDs, a grey LCD and amber
# signal-flow lines, drawn as our own motif (no logos, no traced panel art). Written by tools/gen_layout.py: do not edit.
theme_bg=1c2b93
theme_panel=2b47d6
theme_line=93a8ff
theme_box=2640c4
theme_ink=ffffff
theme_ink_dim=dfe5ff
theme_ink_faint=a9b6f2
theme_accent=f5b400
theme_accent_hi=ff2d55
theme_knob_face=151518
theme_knob_ring=0d1450
theme_knob_dot=ffffff
theme_seg_active=ff2d55
theme_seg_active_tx=ffffff
theme_seg_inactive=1f3299
theme_btn_bg=c8ccd6
theme_btn_text=15161a
theme_btn_text_plain=15161a
theme_display_bg=7f8782
theme_display_cell=78807b
theme_display_ink=23272a
theme_display_off=747c77
theme_display_bezel=101216
theme_lcd=15207a
art_css=skin.css"""

def main():
    emit(HEADER)

    # ---- PROGRAM: the display, the misc parameters and the sequencer's controls
    tab("PROGRAM")
    emit('frame x=10 y=92 w=1260 h=146 title="PROGRAM"')
    for x, label, key in ((20, "PROGRAM", "program"), (650, "BANK", "bank")):
        emit('stepper style=dotmatrix cx=%d cy=190 w=280 h=48 label="%s" key=%s' % (x + 150, label, key))
    emit('readout style=dotmatrix cx=470 cy=190 w=320 h=48 label="" key=patch_name')
    emit('readout style=dotmatrix cx=1095 cy=190 w=320 h=48 label="" key=bank_name')
    misc, _ = section(10, Y(1), "MISC PARAMETERS", [[("TRIGGER", "^trigger"), ("KEY MODE", "^key_mode"), ("KEY XPOSE", "key_xpose"),
                       ("PITCH WHEEL", "bend_range"), ("ENV SHAPE", "^env_shape"), ("INPUT MODE", "^ext_mode"), ("INPUT HACK", "in_hack"),
                       ("VOICES", "voices")]])
    seq, _ = section(10, Y(2), "SEQUENCER", [[("RUN", "^seq_run"), ("CLOCK", "^clock_src"), ("BPM", "tempo"), ("CLOCK DIVIDE", "^clock_div"),
                      ("RESET", "seq_reset")]])
    emit('frame x=740 y=%d w=530 h=146 title="STATUS"' % Y(2))
    emit('readout style=dotmatrix cx=1005 cy=%d w=490 h=48 label="" key=status' % (Y(2) + 98))
    dests, _ = section(10, Y(3), "SEQUENCE DESTINATIONS", [[("SEQ 1", "seq1_dest"), ("SEQ 2", "seq2_dest"), ("SEQ 3", "seq3_dest"),
                        ("SEQ 4", "seq4_dest"), ("OSC 3 SHAPE", "^shapeseq3"), ("OSC 4 SHAPE", "^shapeseq4")]])
    wordmark(880, Y(3) + 20, 360, 100)
    qlinks("Program", ["program", "bank", "volume", "pan", "key_mode", "key_xpose", "bend_range", "voices",
                       "tempo", "clock_div", "trigger", "seq_run", "seq1_dest", "seq2_dest", "seq3_dest", "seq4_dest"])

    # ---- OSC: four oscillators, noise and the external input, all into the filter
    tab("OSC")
    fl = Flow("osc")
    o1, b1 = section(10, Y(0), "OSC 1  ANALOG  LEFT", [[("FREQUENCY", "osc1_freq"), ("FINE", "osc1_fine"), ("SHAPE/PW", "osc1_shape"),
                      ("LEVEL", "osc1_level"), ("GLIDE", "osc1_glide"), ("SLOP", "slop")]])
    o2, b2 = section(10, Y(1), "OSC 2  ANALOG  RIGHT", [[("FREQUENCY", "osc2_freq"), ("FINE", "osc2_fine"), ("SHAPE/PW", "osc2_shape"),
                      ("LEVEL", "osc2_level"), ("GLIDE", "osc2_glide"), ("SYNC 2>1", "~sync")]])
    o3, b3 = section(10, Y(2), "OSC 3  DIGITAL  LEFT", [[("FREQUENCY", "osc3_freq"), ("FINE", "osc3_fine"), ("WAVE", "osc3_shape"),
                      ("LEVEL", "osc3_level"), ("GLIDE", "osc3_glide"), ("FM 4>3", "fm_43"), ("RING 4>3", "rm_43")]])
    o4, b4 = section(10, Y(3), "OSC 4  DIGITAL  RIGHT", [[("FREQUENCY", "osc4_freq"), ("FINE", "osc4_fine"), ("WAVE", "osc4_shape"),
                      ("LEVEL", "osc4_level"), ("GLIDE", "osc4_glide"), ("FM 3>4", "fm_34"), ("RING 3>4", "rm_34")]])
    nz, bn = section(1130, Y(0), "NOISE", [[("LEVEL", "noise_level")]])
    ex, be = section(1130, Y(1), "EXTERNAL IN", [[("LEVEL", "ext_level")]])
    bus = 1090
    for b in (b1, b2, b3, b4):
        fl.line((right(b), mid(b)), (bus, mid(b)), arrow=False)
    for b in (bn, be):
        fl.line((b[0], mid(b)), (bus, mid(b)), arrow=False)
    fl.line((bus, mid(bn)), (bus, mid(b4)), arrow=False, dot=False)
    yo = (mid(b3) + mid(b4)) // 2
    fl.line((bus, yo), (1255, yo))
    fl.label(1255, yo - 15, "LOW PASS", "end")
    fl.write()
    qlinks("Analog", o1 + o2 + ["noise_level", "ext_level", "key_xpose", "bend_range"])
    qlinks("Digital", o3 + o4 + ["shapeseq3", "shapeseq4"])

    # ---- FILTER: the low pass filter into the amplifier, laid out as the panel's two-row sections
    tab("FILTER")
    fl = Flow("filter")
    lp, bl = section(150, Y(0), "LOW PASS FILTER", [[("4/2 POLE", "~poles"), ("FREQUENCY", "lpf_freq"), ("RESONANCE", "lpf_res"),
                      ("ENV AMOUNT", "lpf_env"), ("VELOCITY", "lpf_vel"), ("KEY AMOUNT", "lpf_key")],
                      [("ATTACK", "fenv_a"), ("DECAY", "fenv_d"), ("SUSTAIN", "fenv_s"), ("RELEASE", "fenv_r"), ("AUDIO MOD", "lpf_audiomod"),
                       ("L/R SPLIT", "lpf_split")]])
    am, ba = section(150, Y(0) + 320, "AMPLIFIER", [[("VCA LEVEL", "vca_level"), ("ENV AMOUNT", "vca_env"), ("VELOCITY", "vca_vel"), ("OUTPUT PAN", "^pan")],
                      [("ATTACK", "aenv_a"), ("DECAY", "aenv_d"), ("SUSTAIN", "aenv_s"), ("RELEASE", "aenv_r")]])
    fl.label(20, 200, "OSC")
    fl.label(20, 220, "NOISE")
    fl.label(20, 240, "EXT IN")
    fl.line((22, 260), (150, 260), dot=False)
    fl.line((220, bottom(bl)), (220, ba[1]))
    fl.line((right(ba), mid(ba)), (1255, mid(ba)))
    fl.label(1255, mid(ba) - 15, "HIGH PASS", "end")
    fl.write()
    wordmark(860, Y(3) + 20, 360, 100)
    qlinks("Filter", lp + ["vca_level", "vca_env", "vca_vel", "volume"])
    qlinks("Amp", am[:3] + am[4:] + ["lpf_freq", "lpf_res", "lpf_env", "fenv_a", "fenv_d", "fenv_s", "fenv_r", "volume", "pan"])

    # ---- FX: high pass, tuned feedback, distortion, delay, output hack, voice volume, in the panel's order
    tab("FX")
    fl = Flow("fx")
    hp, bh = section(10, Y(0), "HP FILTER", [[("FREQUENCY", "hpf")]])
    fb, bf = section(190, Y(0), "TUNED FEEDBACK", [[("FREQUENCY", "fb_freq"), ("LEVEL", "fb_level"), ("GRUNGE", "~grunge")]])
    di, bd = section(650, Y(0), "DISTORTION", [[("AMOUNT", "dist")]])
    dl, bdl = section(370, 276, "DELAY", [[("TIME 1", "dly1_time"), ("TIME 2", "dly2_time"), ("TIME 3", "dly3_time"), ("FEEDBACK 1", "dly_fb1")],
                      [("AMOUNT 1", "dly1_level"), ("AMOUNT 2", "dly2_level"), ("AMOUNT 3", "dly3_level"), ("FEEDBACK 2", "dly_fb2")]])
    hk, bk = section(970, 276, "OUTPUT HACK", [[("AMOUNT", "out_hack")]])
    vv, bv = section(970, 456, "VOICE VOL", [[("LEVEL", "volume")]])
    fl.label(20, 262, "FROM AMP")
    fl.line((right(bh), mid(bh)), (bf[0], mid(bf)))
    fl.line((right(bf), mid(bf)), (bd[0], mid(bd)))
    fl.line((bd[0] + 70, bottom(bd)), (bd[0] + 70, bdl[1]))
    fl.line((right(bdl), mid(bk)), (bk[0], mid(bk)))
    fl.line((bk[0] + 70, bottom(bk)), (bk[0] + 70, bv[1]))
    fl.line((right(bv), mid(bv)), (1255, mid(bv)))
    fl.label(1255, mid(bv) - 15, "OUT", "end")
    fl.line((bdl[0], bdl[1] + 210), (300, bdl[1] + 210), (300, 600), arrow=True)
    fl.label(300, 624, "FEEDBACK 2 TO THE FILTER", "middle")
    fl.write()
    wordmark(880, Y(3) + 40, 360, 100)
    qlinks("FX", hp + fb + di + dl + hk + vv + ["pan"])

    # ---- MOD: envelope 3 and the four LFOs (the panel's top row)
    tab("MOD")
    e3, _ = section(10, Y(0), "ENVELOPE 3", [[("DESTINATION", "env3_dest"), ("AMOUNT", "env3_amt"), ("VELOCITY", "env3_vel"), ("DELAY", "env3_delay")],
                      [("ATTACK", "env3_a"), ("DECAY", "env3_d"), ("SUSTAIN", "env3_s"), ("RELEASE", "env3_r")]])
    lf = []
    for n in range(4):
        k, _ = section(700, Y(n), "LFO %d" % (n + 1), [[("FREQUENCY", "lfo%d_freq" % (n + 1)), ("SHAPE", "^lfo%d_shape" % (n + 1)),
                        ("AMOUNT", "lfo%d_amt" % (n + 1)), ("DESTINATION", "lfo%d_dest" % (n + 1))]])
        lf += k
    wordmark(100, Y(2) + 40, 420, 120)
    qlinks("LFOs", lf)
    qlinks("Env 3", e3)

    # ---- MODS: the four modulators and the fixed controller routes
    tab("MODS")
    mods = []
    for n in range(4):
        k, _ = section(10, Y(n), "MODULATOR %d" % (n + 1), [[("SOURCE", "mod%d_src" % (n + 1)), ("DESTINATION", "mod%d_dest" % (n + 1)),
                        ("AMOUNT", "mod%d_amt" % (n + 1))]])
        mods += k
    fixed = []
    pairs = [("MOD WHEEL", "wheel"), ("PRESSURE", "press"), ("BREATH", "breath"), ("VELOCITY", "vel"), ("FOOT CONTROLLER", "foot"),
             ("IN PEAK", "peak"), ("IN ENV FOLLOWER", "envf")]
    for i, (title, k) in enumerate(pairs):
        keys, _ = section(450 + 300 * (i % 2), Y(i // 2), title, [[("AMOUNT", "%s_amt" % k), ("DESTINATION", "%s_dest" % k)]])
        fixed += keys
    wordmark(1040, Y(3) + 30, 230, 70)
    qlinks("Mods", mods + ["wheel_amt", "wheel_dest", "press_amt", "press_dest"])
    qlinks("Fixed", fixed)

    # ---- SEQ: each track on two rows of eight steps, one Q-Link page per track
    for pair in ((1, 2), (3, 4)):
        tab("SEQ %d-%d" % pair)
        for j, t in enumerate(pair):
            keys = []
            for half in range(2):
                items = [[("%d" % (8 * half + k + 1), "s%d_%d" % (t, 8 * half + k + 1)) for k in range(8)]]
                ks, _ = section(80, Y(2 * j + half), "SEQUENCE %d  STEPS %d-%d" % (t, 8 * half + 1, 8 * half + 8), items)
                keys += ks
            qlinks("Seq %d" % t, keys)

    with open(os.path.join(VST, "layout.conf"), "w") as f:
        f.write("\n".join(OUT) + "\n")

if __name__ == "__main__":
    main()
