#include <string.h>
#include "presets.h"
#include "patch_tab.h"

typedef struct { const char *name; short kv[64][2]; } preset_t;
#define END {-1, 0}
#define S99(x) ((x) + 99)
/* Sequencer steps are given as {NPROG + track * 16 + step, value}. */
#define STEP(t, k, v) {NPROG + (t) * 16 + (k), v}

static const preset_t PRESETS[] = {
    {"Basic Program", {END}},
    {"Twin Saw Lead", {{P_OSC2_FINE, 57}, {P_OSC1_LEVEL, 60}, {P_OSC2_LEVEL, 60}, {P_LPF_FREQ, 70}, {P_LPF_RES, 30},
        {P_LPF_ENV, S99(55)}, {P_FENV_D, 55}, {P_FENV_S, 30}, {P_KEY_MODE, 10}, {P_OSC1_GLIDE, 25}, {P_OSC2_GLIDE, 25},
        {P_LFO1_FREQ, 95}, {P_LFO1_AMT, 0}, {P_WHEEL_AMT, S99(4)}, {P_WHEEL_DEST, 5}, {P_DLY1_TIME, 158}, {P_DLY1_LEVEL, 25}, {P_DLY_FB1, 30}, END}},
    {"Hollow Pad", {{P_OSC1_LEVEL, 0}, {P_OSC2_LEVEL, 0}, {P_OSC3_LEVEL, 60}, {P_OSC4_LEVEL, 60}, {P_OSC3_SHAPE, 12}, {P_OSC4_SHAPE, 40},
        {P_OSC4_FINE, 56}, {P_LPF_FREQ, 95}, {P_POLES, 0}, {P_LPF_RES, 20}, {P_AENV_A, 70}, {P_AENV_R, 75}, {P_FENV_A, 80},
        {P_FENV_S, 40}, {P_LPF_ENV, S99(25)}, {P_LFO1_FREQ, 25}, {P_LFO1_AMT, 12}, {P_LFO1_DEST, 20}, {P_LFO2_FREQ, 18},
        {P_LFO2_AMT, 6}, {P_LFO2_DEST, 25}, {P_DLY1_TIME, 100}, {P_DLY2_TIME, 106}, {P_DLY1_LEVEL, 30}, {P_DLY2_LEVEL, 25},
        {P_DLY_FB1, 45}, {P_SLOP, 3}, END}},
    {"Plucked Line", {{P_OSC1_LEVEL, 0}, {P_OSC2_LEVEL, 0}, {P_NOISE_LEVEL, 0}, {P_ENV3_DEST, 11}, {P_ENV3_AMT, S99(99)},
        {P_ENV3_D, 8}, {P_ENV3_S, 0}, {P_FB_FREQ, 0}, {P_FB_LEVEL, 97}, {P_MOD1_SRC, 20}, {P_MOD1_AMT, S99(99)}, {P_MOD1_DEST, 26},
        {P_LPF_FREQ, 130}, {P_AENV_D, 70}, {P_AENV_S, 0}, {P_AENV_R, 50}, {P_PAN, 3}, END}},
    {"Sequenced Bass", {{P_OSC1_FREQ, 12}, {P_OSC2_FREQ, 12}, {P_OSC2_SHAPE, 50}, {P_OSC2_FINE, 53}, {P_LPF_FREQ, 50}, {P_LPF_RES, 55},
        {P_LPF_ENV, S99(60)}, {P_FENV_D, 35}, {P_AENV_D, 45}, {P_AENV_S, 0}, {P_AENV_R, 10}, {P_TRIGGER, 5}, {P_CLOCK_DIV, 6},
        {P_SEQ1_DEST, 5}, {P_SEQ2_DEST, 20}, {P_DIST, 20},
        STEP(0, 0, 0), STEP(0, 1, 24), STEP(0, 2, 0), STEP(0, 3, 14), STEP(0, 4, 0), STEP(0, 5, 0), STEP(0, 6, 20), STEP(0, 7, 102),
        STEP(1, 0, 40), STEP(1, 1, 10), STEP(1, 2, 25), STEP(1, 3, 0), STEP(1, 4, 60), STEP(1, 5, 5), STEP(1, 6, 30), STEP(1, 7, 0),
        STEP(0, 8, 101), STEP(1, 8, 101), END}},
    {"Sync Sweep", {{P_SYNC, 1}, {P_OSC1_FREQ, 36}, {P_OSC2_LEVEL, 0}, {P_LFO1_FREQ, 40}, {P_LFO1_AMT, 30}, {P_LFO1_DEST, 1},
        {P_LFO1_SHAPE, 0}, {P_ENV3_DEST, 1}, {P_ENV3_AMT, S99(40)}, {P_ENV3_D, 60}, {P_LPF_FREQ, 110}, {P_LPF_RES, 15}, END}},
    {"Ring Bells", {{P_OSC1_LEVEL, 0}, {P_OSC2_LEVEL, 0}, {P_OSC3_LEVEL, 40}, {P_OSC4_LEVEL, 30}, {P_OSC3_SHAPE, 0}, {P_OSC4_SHAPE, 0},
        {P_OSC4_FREQ, 43}, {P_OSC4_FINE, 58}, {P_RM_43, 70}, {P_RM_34, 40}, {P_FM_43, 10}, {P_LPF_FREQ, 150}, {P_AENV_D, 75},
        {P_AENV_S, 0}, {P_AENV_R, 75}, {P_DLY1_TIME, 90}, {P_DLY1_LEVEL, 30}, {P_DLY_FB1, 40}, {P_HPF, 20}, END}},
    {"Feedback Drone", {{P_OSC1_SHAPE, 53}, {P_OSC2_SHAPE, 30}, {P_OSC2_FINE, 45}, {P_LPF_FREQ, 75}, {P_LPF_RES, 50}, {P_FB_LEVEL, 70},
        {P_FB_FREQ, 12}, {P_GRUNGE, 1}, {P_AENV_A, 60}, {P_AENV_R, 80}, {P_LFO1_FREQ, 10}, {P_LFO1_AMT, 20}, {P_LFO1_DEST, 26},
        {P_LFO2_FREQ, 22}, {P_LFO2_AMT, 25}, {P_LFO2_DEST, 13}, {P_LFO2_SHAPE, 0}, {P_LPF_SPLIT, 30}, {P_DLY1_TIME, 130},
        {P_DLY1_LEVEL, 30}, {P_DLY_FB2, 20}, END}},
};

int presets_count(void) { return (int)(sizeof PRESETS / sizeof PRESETS[0]); }
void presets_apply(int k, uint8_t *patch, char name[17]) {
    if (k < 0 || k >= presets_count()) return;
    const preset_t *p = &PRESETS[k];
    for (int i = 0; i < 64 && p->kv[i][0] >= 0; i++) patch[p->kv[i][0]] = (uint8_t)p->kv[i][1];
    strncpy(name, p->name, 16);
    name[16] = 0;
}
