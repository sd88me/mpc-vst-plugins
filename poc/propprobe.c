/* Parameter-properties probe (effGetParameterProperties, opcode 56): does MPC's host ask for it, and does it honour
   the flags? Silent instrument, five params; every dispatcher opcode the host sends and every setParameter value is
   logged to /tmp/propprobe.log (opcode, index, how often).
     0 "Switch"  - kVstParameterIsSwitch
     1 "IntStep" - integer min 0, max 7, step 1 (UsesIntegerMinMax | UsesIntStep)
     2 "FltStep" - float step 0.25 (UsesFloatStep)
     3 "Plain"   - no properties (returns 0)
     4 "Names"   - kVstParameterSupportsDisplayIndex, with a short label
   Things to read from the log: is opcode 56 ever sent (and for which indices), do Q-Link turns arrive as steps for
   IntStep/Switch (compare the setParameter values with those for Plain), and does the automation screen change. */
#include <stdint.h>
#include <string.h>
#include <stdio.h>

typedef struct AEffect AEffect;
typedef intptr_t (*audioMasterCallback)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
struct AEffect {
    int32_t magic;
    intptr_t (*dispatcher)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
    void (*process)(AEffect *, float **, float **, int32_t);
    void (*setParameter)(AEffect *, int32_t, float);
    float (*getParameter)(AEffect *, int32_t);
    int32_t numPrograms, numParams, numInputs, numOutputs, flags;
    intptr_t resvd1, resvd2;
    int32_t initialDelay, realQualities, offQualities;
    float ioRatio;
    void *object, *user;
    int32_t uniqueID, version;
    void (*processReplacing)(AEffect *, float **, float **, int32_t);
    void (*processDoubleReplacing)(AEffect *, double **, double **, int32_t);
    char future[56];
};
/* VST 2.x VstParameterProperties (128 bytes) */
typedef struct {
    float stepFloat, smallStepFloat, largeStepFloat;
    char label[64];
    int32_t flags;
    int32_t minInteger, maxInteger, stepInteger, largeStepInteger;
    char shortLabel[8];
    int16_t displayIndex, category, numParametersInCategory, reserved;
    char categoryLabel[24];
    char future[16];
} props_t;
enum { IS_SWITCH = 1, INT_MINMAX = 2, FLOAT_STEP = 4, INT_STEP = 8, DISPLAY_INDEX = 16 };

static FILE *lg;
static float val[5] = {0, 0, 0, 0, 0};
static int seen[256];     /* dispatcher opcodes: count (log the first few) */
static int setn[5];

static void logf_(const char *fmt, int a, int b, long c) {
    if (!lg) return;
    fprintf(lg, fmt, a, b, c);
    fflush(lg);
}

static intptr_t dispatcher(AEffect *e, int32_t op, int32_t idx, intptr_t v, void *p, float o) {
    (void)e; (void)o;
    if (op >= 0 && op < 256 && seen[op]++ < 3) logf_("op %d idx %d val %ld\n", op, idx, (long)v);
    switch (op) {
    case 35: return 2;
    case 45: case 48: strcpy(p, "MPC Props Probe"); return 1;
    case 47: strcpy(p, "sd88me"); return 1;
    case 58: return 2400;
    case 8: {
        static const char *n[5] = {"Switch", "IntStep", "FltStep", "Plain", "Names"};
        strcpy(p, idx >= 0 && idx < 5 ? n[idx] : "?");
        return 1;
    }
    case 7: {
        if (idx == 1) snprintf(p, 24, "step %d", (int)(val[1] * 7 + 0.5f));
        else snprintf(p, 24, "%.3f", val[idx < 5 ? idx : 0]);
        return 1;
    }
    case 6: strcpy(p, ""); return 1;
    case 56: { /* effGetParameterProperties */
        props_t *q = p;
        logf_("PROPS requested idx %d (%d,%ld)\n", idx, 0, 0);
        memset(q, 0, sizeof *q);
        snprintf(q->label, sizeof q->label, "Prop%d", idx);
        if (idx == 0) { q->flags = IS_SWITCH; return 1; }
        if (idx == 1) { q->flags = INT_MINMAX | INT_STEP; q->minInteger = 0; q->maxInteger = 7; q->stepInteger = 1; q->largeStepInteger = 1; return 1; }
        if (idx == 2) { q->flags = FLOAT_STEP; q->stepFloat = 0.25f; q->smallStepFloat = 0.25f; q->largeStepFloat = 0.25f; return 1; }
        if (idx == 4) { q->flags = DISPLAY_INDEX; q->displayIndex = 0; strcpy(q->shortLabel, "Nm"); return 1; }
        return 0;
    }
    default: return 0;
    }
}
static float getParameter(AEffect *e, int32_t i) { (void)e; return i >= 0 && i < 5 ? val[i] : 0; }
static void setParameter(AEffect *e, int32_t i, float v) {
    (void)e;
    if (i < 0 || i >= 5) return;
    val[i] = v;
    if (setn[i]++ < 40) { if (lg) { fprintf(lg, "set %d = %.4f\n", i, v); fflush(lg); } }
}
static void processReplacing(AEffect *e, float **in, float **out, int32_t n) {
    (void)e; (void)in;
    memset(out[0], 0, n * sizeof(float));
    memset(out[1], 0, n * sizeof(float));
}

__attribute__((visibility("default"))) AEffect *VSTPluginMain(audioMasterCallback m) {
    static AEffect fx;
    (void)m;
    if (!lg) lg = fopen("/tmp/propprobe.log", "a");
    memset(&fx, 0, sizeof fx);
    fx.magic = 0x56737450;
    fx.dispatcher = dispatcher;
    fx.getParameter = getParameter;
    fx.setParameter = setParameter;
    fx.processReplacing = processReplacing;
    fx.numParams = 5; fx.numInputs = 0; fx.numOutputs = 2;
    fx.flags = (1 << 4) | (1 << 8);
    fx.uniqueID = 0x5072506f; /* 'PrPo' */
    fx.version = 1000;
    return &fx;
}
