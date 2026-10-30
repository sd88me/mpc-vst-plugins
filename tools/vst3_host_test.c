/* Offline test of a VST3 build (tools/build_vst3.sh), run by tools/test_vst3.sh under ASan/UBSan: loads the bundle's .so
 * the way a DAW does and drives it through wrapper/vst3_abi.h.
 *
 *   vst3_host_test <plugin.so> [--passthrough] [--shots <dir>]
 *
 * Checks: the factory and class; one object answers IComponent, IAudioProcessor and IEditController; every parameter's info
 * and text; audio at 44.1, 48 and 96 kHz in uneven block sizes (finite, sane level; an effect's bypass is its input delayed by
 * exactly getLatencySamples(); with --passthrough, an effect that passes audio unchanged must do so at that same delay, which
 * checks the resampling and the reported latency); whether an instrument sounds on a note (reported, not failed: a
 * MIDI tool makes no sound); a list parameter set through process()
 * survives getState/setState into a second instance; the editor, when built in: createView, X11 embedding, size and its
 * aspect-keeping constraint (the window itself is not opened). --shots <dir> renders every skin page as the editor would
 * draw it now (after the audio and MIDI tests, so readouts show something) to <dir>/page<N>.png. Exit status 0 = all passed. */
#include "vst3_abi.h"
#include <dlfcn.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
#define CHECK(cond, ...) do { if (!(cond)) { failures++; printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void ascii(char *dst, const char16 *src, int max) {
    int i = 0;
    for (; src[i] && i < max - 1; i++) dst[i] = src[i] < 128 ? (char)src[i] : '?';
    dst[i] = 0;
}

/* ---- host objects: a memory stream, parameter changes, an event list (static, never freed: refcounts are no-ops) ---- */
static tresult no_query(void *s, const TUID iid, void **obj) { (void)s; (void)iid; *obj = NULL; return kNoInterface; }
static uint32_t one(void *s) { (void)s; return 1; }

typedef struct { const IBStreamVtbl *v; char *buf; int64_t len, cap, pos; } mem_stream;
static tresult ms_read(void *s, void *b, int32_t n, int32_t *done) {
    mem_stream *m = s;
    int64_t k = m->len - m->pos < n ? m->len - m->pos : n;
    if (k < 0) k = 0;
    memcpy(b, m->buf + m->pos, (size_t)k);
    m->pos += k;
    if (done) *done = (int32_t)k;
    return kResultOk;
}
static tresult ms_write(void *s, void *b, int32_t n, int32_t *done) {
    mem_stream *m = s;
    if (m->pos + n > m->cap) { m->cap = (m->pos + n) * 2; m->buf = realloc(m->buf, (size_t)m->cap); }
    memcpy(m->buf + m->pos, b, (size_t)n);
    m->pos += n;
    if (m->pos > m->len) m->len = m->pos;
    if (done) *done = n;
    return kResultOk;
}
static tresult ms_seek(void *s, int64_t pos, int32_t mode, int64_t *res) {
    mem_stream *m = s;
    m->pos = mode == 0 ? pos : mode == 1 ? m->pos + pos : m->len + pos;
    if (res) *res = m->pos;
    return kResultOk;
}
static tresult ms_tell(void *s, int64_t *pos) { *pos = ((mem_stream *)s)->pos; return kResultOk; }
static const IBStreamVtbl ms_vtbl = { no_query, one, one, ms_read, ms_write, ms_seek, ms_tell };

typedef struct { const IParamValueQueueVtbl *v; uint32_t id; int n; int32_t off[16]; double val[16]; } queue_t;
static uint32_t q_id(void *s) { return ((queue_t *)s)->id; }
static int32_t q_count(void *s) { return ((queue_t *)s)->n; }
static tresult q_get(void *s, int32_t i, int32_t *off, double *v) {
    queue_t *q = s;
    if (i < 0 || i >= q->n) return kInvalidArgument;
    *off = q->off[i]; *v = q->val[i];
    return kResultOk;
}
static tresult q_add(void *s, int32_t off, double v, int32_t *i) {
    queue_t *q = s;
    if (q->n == 16) return kResultFalse;
    q->off[q->n] = off; q->val[q->n] = v; *i = q->n++;
    return kResultOk;
}
static const IParamValueQueueVtbl q_vtbl = { no_query, one, one, q_id, q_count, q_get, q_add };

typedef struct { const IParameterChangesVtbl *v; int n; queue_t q[64]; } changes_t;
static int32_t pc_count(void *s) { return ((changes_t *)s)->n; }
static IParamValueQueue *pc_get(void *s, int32_t i) {
    changes_t *c = s;
    return i >= 0 && i < c->n ? (IParamValueQueue *)&c->q[i] : NULL;
}
static IParamValueQueue *pc_add(void *s, const uint32_t *id, int32_t *i) {
    changes_t *c = s;
    for (int k = 0; k < c->n; k++) if (c->q[k].id == *id) { *i = k; return (IParamValueQueue *)&c->q[k]; }
    if (c->n == 64) return NULL;
    queue_t *q = &c->q[c->n];
    memset(q, 0, sizeof *q);
    q->v = &q_vtbl; q->id = *id;
    *i = c->n++;
    return (IParamValueQueue *)q;
}
static const IParameterChangesVtbl pc_vtbl = { no_query, one, one, pc_count, pc_get, pc_add };
static void changes_init(changes_t *c) { c->v = &pc_vtbl; c->n = 0; }
static void changes_set(changes_t *c, uint32_t id, double v) {
    int32_t i, j;
    IParamValueQueue *q = pc_add(c, &id, &i);
    q->v->addPoint(q, 0, v, &j);
}

typedef struct { const IEventListVtbl *v; int n; Event e[32]; } events_t;
static int32_t ev_count(void *s) { return ((events_t *)s)->n; }
static tresult ev_get(void *s, int32_t i, Event *e) {
    events_t *l = s;
    if (i < 0 || i >= l->n) return kInvalidArgument;
    *e = l->e[i];
    return kResultOk;
}
static tresult ev_add(void *s, Event *e) { events_t *l = s; if (l->n == 32) return kResultFalse; l->e[l->n++] = *e; return kResultOk; }
static const IEventListVtbl ev_vtbl = { no_query, one, one, ev_count, ev_get, ev_add };

/* ---- the plugin ------------------------------------------------------------------------- */
#define VT(T, p) (*(const T *const *)(p))

typedef struct {
    void *comp, *proc, *ctrl;
    const ComponentVtbl *c;
    const ProcessorVtbl *p;
    const ControllerVtbl *e;
} plug_t;

static void *g_factory;
static TUID g_cid;
static int g_effect;

static int plug_new(plug_t *pl) {
    const FactoryVtbl *f = VT(FactoryVtbl, g_factory);
    memset(pl, 0, sizeof *pl);
    if (f->createInstance(g_factory, (const char *)g_cid, (const char *)iid_IComponent, &pl->comp) != kResultOk || !pl->comp) return 0;
    pl->c = VT(ComponentVtbl, pl->comp);
    if (pl->c->initialize(pl->comp, NULL) != kResultOk) return 0;
    if (pl->c->queryInterface(pl->comp, iid_IAudioProcessor, &pl->proc) != kResultOk) return 0;
    if (pl->c->queryInterface(pl->comp, iid_IEditController, &pl->ctrl) != kResultOk) return 0;
    pl->p = VT(ProcessorVtbl, pl->proc);
    pl->e = VT(ControllerVtbl, pl->ctrl);
    return pl->e->initialize(pl->ctrl, NULL) == kResultOk;
}

static void plug_free(plug_t *pl) {
    if (pl->ctrl) { pl->e->terminate(pl->ctrl); pl->e->release(pl->ctrl); }
    if (pl->proc) pl->p->release(pl->proc);
    if (pl->comp) { pl->c->terminate(pl->comp); pl->c->release(pl->comp); }
}

static int setup(plug_t *pl, double rate) {
    ProcessSetup ps = { 0, 0, 1024, rate };
    uint64_t st = 3;
    if (g_effect) pl->p->setBusArrangements(pl->proc, &st, 1, &st, 1);
    else pl->p->setBusArrangements(pl->proc, NULL, 0, &st, 1);
    if (pl->p->setupProcessing(pl->proc, &ps) != kResultOk) return 0;
    if (pl->c->setActive(pl->comp, 1) != kResultOk) return 0;
    return pl->p->setProcessing(pl->proc, 1) == kResultOk;
}
static void teardown(plug_t *pl) { pl->p->setProcessing(pl->proc, 0); pl->c->setActive(pl->comp, 0); }

/* one process() call; in may be NULL (an instrument) */
static void run(plug_t *pl, float *inl, float *inr, float *outl, float *outr, int n, changes_t *pc, events_t *ev, changes_t *out_pc) {
    float *ib[2] = { inl, inr }, *ob[2] = { outl, outr };
    AudioBusBuffers in = { 2, 0, ib }, out = { 2, 0, ob };
    ProcessContext ctx;
    memset(&ctx, 0, sizeof ctx);
    ctx.state = kTempoValid; ctx.tempo = 120;
    ProcessData d = { 0, 0, n, g_effect ? 1 : 0, 1, g_effect ? &in : NULL, &out, (IParameterChanges *)pc, (IParameterChanges *)out_pc,
                      (IEventList *)ev, NULL, &ctx };
    tresult r = pl->p->process(pl->proc, &d);
    CHECK(r == kResultOk, "process() returned %d", r);
}

static uint32_t find_param(plug_t *pl, int want_flags, int min_steps) {
    int n = pl->e->getParameterCount(pl->ctrl);
    for (int i = 0; i < n; i++) {
        ParameterInfo pi;
        if (pl->e->getParameterInfo(pl->ctrl, i, &pi) != kResultOk) continue;
        if ((pi.flags & want_flags) == want_flags && !(pi.flags & (kIsReadOnly | kIsHidden | kIsBypass | kIsProgramChange)) && pi.stepCount >= min_steps)
            return pi.id;
    }
    return 0xFFFFFFFFu;
}

static void test_params(plug_t *pl) {
    int n = pl->e->getParameterCount(pl->ctrl), visible = 0, bypass = 0;
    CHECK(n > 0, "no parameters");
    for (int i = 0; i < n; i++) {
        ParameterInfo pi;
        char16 txt[128];
        char name[128], val[128];
        CHECK(pl->e->getParameterInfo(pl->ctrl, i, &pi) == kResultOk, "getParameterInfo(%d)", i);
        ascii(name, pi.title, sizeof name);
        CHECK(name[0], "parameter %d has no name", i);
        if (pi.flags & kIsBypass) bypass++;
        if (pi.flags & kIsHidden) continue;
        visible++;
        double v = pl->e->getParamNormalized(pl->ctrl, pi.id);
        CHECK(v >= 0 && v <= 1, "%s: value %g out of 0..1", name, v);
        CHECK(pl->e->getParamStringByValue(pl->ctrl, pi.id, v, txt) == kResultOk, "%s: no text", name);
        ascii(val, txt, sizeof val);
        if (!(pi.flags & kIsReadOnly) && pi.stepCount > 0) {
            double back = -1;
            CHECK(pl->e->getParamValueByString(pl->ctrl, pi.id, txt, &back) == kResultOk && fabs(back - v) < 0.5 / pi.stepCount + 1e-9,
                  "%s: text \"%s\" reads back as %g, not %g", name, val, back, v);
        }
    }
    CHECK(bypass == 1, "%d bypass parameters (want 1)", bypass);
    printf("parameters: %d (%d visible)\n", n, visible);
}

static double rms(const float *x, int n) { double s = 0; for (int i = 0; i < n; i++) s += (double)x[i] * x[i]; return n ? sqrt(s / n) : 0; }

static void test_audio(plug_t *pl, double rate, int passthrough) {
    if (!setup(pl, rate)) { CHECK(0, "%.0f Hz: setup failed", rate); return; }
    int lat = (int)pl->p->getLatencySamples(pl->proc), N = (int)rate * 2;
    float *inl = calloc(N, 4), *inr = calloc(N, 4), *outl = calloc(N, 4), *outr = calloc(N, 4);
    for (int i = 0; i < N; i++) { inl[i] = 0.25f * sinf(2 * (float)M_PI * 440 * i / (float)rate); inr[i] = 0.25f * sinf(2 * (float)M_PI * 660 * i / (float)rate); }
    static const int sizes[] = { 37, 128, 512, 1, 1000, 255, 64, 1024 };
    events_t ev = { &ev_vtbl, 0, {{0}} };
    changes_t pc, out_pc;
    uint32_t bypass_id = 0x7FFF0001u;
    int bypass_from = N / 2;   /* effect: second half bypassed */
    for (int pos = 0, k = 0; pos < N; k++) {
        int n = sizes[k % 8];
        if (n > N - pos) n = N - pos;
        changes_init(&pc); changes_init(&out_pc);
        ev.n = 0;
        if (!g_effect && pos == 0) {   /* an instrument: a note for the first second */
            Event e; memset(&e, 0, sizeof e);
            e.type = kNoteOnEvent; e.noteOn.pitch = 60; e.noteOn.velocity = 0.8f; e.noteOn.noteId = -1; e.sampleOffset = 0;
            ev.e[ev.n++] = e;
        }
        if (!g_effect && pos < (int)rate && pos + n >= (int)rate) {
            Event e; memset(&e, 0, sizeof e);
            e.type = kNoteOffEvent; e.noteOff.pitch = 60; e.noteOff.noteId = -1; e.sampleOffset = (int)rate - pos;
            ev.e[ev.n++] = e;
        }
        if (g_effect && pos == 0) changes_set(&pc, bypass_id, 0);
        if (g_effect && pos <= bypass_from && pos + n > bypass_from) { bypass_from = pos; changes_set(&pc, bypass_id, 1); }
        run(pl, g_effect ? inl + pos : NULL, g_effect ? inr + pos : NULL, outl + pos, outr + pos, n, &pc, &ev, &out_pc);
        pos += n;
    }
    int finite = 1;
    float peak = 0;
    for (int i = 0; i < N; i++) { if (!isfinite(outl[i]) || !isfinite(outr[i])) finite = 0; peak = fmaxf(peak, fmaxf(fabsf(outl[i]), fabsf(outr[i]))); }
    CHECK(finite, "%.0f Hz: non-finite output", rate);
    CHECK(peak < 4, "%.0f Hz: output peak %.2f", rate, peak);
    if (g_effect) {
        /* bypass: the input delayed by the latency, sample for sample */
        int bad = 0;
        for (int i = bypass_from; i < N; i++) if (outl[i] != inl[i - lat] || outr[i] != inr[i - lat]) bad++;
        CHECK(!bad, "%.0f Hz: bypassed output is not the input delayed by %d (%d frames differ)", rate, lat, bad);
        if (passthrough) {
            float err[2][4096];
            int from = lat + (int)rate / 4, cnt = bypass_from - from;
            if (cnt > 4096) cnt = 4096;
            for (int i = 0; i < cnt; i++) { err[0][i] = outl[from + i] - inl[from + i - lat]; err[1][i] = outr[from + i] - inr[from + i - lat]; }
            double e = (rms(err[0], cnt) + rms(err[1], cnt)) / 2 / 0.1768;
            CHECK(e < 2e-3, "%.0f Hz: passthrough is not the input delayed by %d (relative error %.1e)", rate, lat, e);
            printf("%6.0f Hz: latency %d, passthrough error %.1e (%.0f dB), peak %.3f\n", rate, lat, e, 20 * log10(e + 1e-12), peak);
        } else {
            printf("%6.0f Hz: latency %d, peak %.3f\n", rate, lat, peak);
        }
    } else {
        double r = rms(outl, (int)rate);
        if (r <= 1e-5) printf("note: %.0f Hz: silent after a note (a MIDI tool or a probe makes no sound; a synth should)\n", rate);
        printf("%6.0f Hz: rms over the note %.4f, peak %.3f\n", rate, r, peak);
    }
    teardown(pl);
    free(inl); free(inr); free(outl); free(outr);
}

/* a program-change parameter (vst.json "presets"): picking the last program reads back as picked and moves some parameter */
static void test_programs(plug_t *pl) {
    int n = pl->e->getParameterCount(pl->ctrl);
    ParameterInfo prog;
    int found = 0;
    for (int i = 0; i < n && !found; i++)
        if (pl->e->getParameterInfo(pl->ctrl, i, &prog) == kResultOk && (prog.flags & kIsProgramChange)) found = 1;
    if (!found) { printf("programs: none\n"); return; }
    double before[4096];
    int m = n < 4096 ? n : 4096;
    for (int i = 0; i < m; i++) { ParameterInfo pi; pl->e->getParameterInfo(pl->ctrl, i, &pi); before[i] = pl->e->getParamNormalized(pl->ctrl, pi.id); }
    if (!setup(pl, 48000)) { CHECK(0, "programs: setup failed"); return; }
    changes_t pc, out_pc;
    changes_init(&pc); changes_init(&out_pc);
    changes_set(&pc, prog.id, 1.0);
    float l[64] = {0}, r[64] = {0}, ol[64], orr[64];
    run(pl, l, r, ol, orr, 64, &pc, NULL, &out_pc);
    char16 txt[128];
    char name[128];
    pl->e->getParamStringByValue(pl->ctrl, prog.id, 1.0, txt);
    ascii(name, txt, sizeof name);
    CHECK(fabs(pl->e->getParamNormalized(pl->ctrl, prog.id) - 1.0) < 1e-9, "programs: the last program does not read back as picked");
    int moved = 0;
    for (int i = 0; i < m; i++) {
        ParameterInfo pi;
        pl->e->getParameterInfo(pl->ctrl, i, &pi);
        if (pi.id != prog.id && fabs(pl->e->getParamNormalized(pl->ctrl, pi.id) - before[i]) > 1e-9) moved++;
    }
    CHECK(moved > 0, "programs: picking \"%s\" changed no parameter", name);
    printf("programs: %d, \"%s\" moved %d parameter(s), %d reported to the host\n", prog.stepCount + 1, name, moved, out_pc.n);
    teardown(pl);
}

/* MIDI CC through IMidiMapping: CC 1 and pitch bend on channel 1 map to parameters, and a move goes through process() */
static void test_midi_cc(plug_t *pl) {
    void *mm = NULL;
    CHECK(pl->c->queryInterface(pl->comp, iid_IMidiMapping, &mm) == kResultOk, "no IMidiMapping");
    if (!mm) return;
    const MidiMappingVtbl *m = VT(MidiMappingVtbl, mm);
    uint32_t cc1 = 0, bend = 0;
    CHECK(m->getMidiControllerAssignment(mm, 0, 0, 1, &cc1) == kResultOk, "CC 1 not mapped");
    CHECK(m->getMidiControllerAssignment(mm, 0, 0, 129, &bend) == kResultOk && bend != cc1, "pitch bend not mapped");
    m->release(mm);
    if (!setup(pl, 48000)) { CHECK(0, "midi cc: setup failed"); return; }
    changes_t pc, out_pc;
    changes_init(&pc); changes_init(&out_pc);
    changes_set(&pc, cc1, 1.0);
    changes_set(&pc, bend, 0.75);
    float l[64] = {0}, r[64] = {0}, ol[64], orr[64];
    run(pl, l, r, ol, orr, 64, &pc, NULL, &out_pc);
    /* what the engine shows now, for a port that echoes controllers on a readout */
    int n = pl->e->getParameterCount(pl->ctrl), shown = 0;
    printf("midi cc: CC 1 = 127 and pitch bend sent; readouts:");
    for (int i = 0; i < n && shown < 6; i++) {
        ParameterInfo pi;
        char16 txt[128];
        char val[128];
        if (pl->e->getParameterInfo(pl->ctrl, i, &pi) != kResultOk || !(pi.flags & kIsReadOnly) || (pi.flags & kIsHidden)) continue;
        pl->e->getParamStringByValue(pl->ctrl, pi.id, 0, txt);
        ascii(val, txt, sizeof val);
        printf(" [%s]", val);
        shown++;
    }
    printf("\n");
    teardown(pl);
}

static void test_state(plug_t *a) {
    uint32_t id = find_param(a, kIsList, 2);
    if (id == 0xFFFFFFFFu) id = find_param(a, kCanAutomate, 1);
    if (id == 0xFFFFFFFFu) { printf("state: no settable parameter, skipped\n"); return; }
    if (!setup(a, 48000)) { CHECK(0, "state: setup failed"); return; }
    changes_t pc, out_pc;
    changes_init(&pc); changes_init(&out_pc);
    double was = a->e->getParamNormalized(a->ctrl, id), want = was < 0.5 ? 1 : 0;
    changes_set(&pc, id, want);
    float l[64] = {0}, r[64] = {0}, ol[64], orr[64];
    run(a, l, r, ol, orr, 64, &pc, NULL, &out_pc);
    double now = a->e->getParamNormalized(a->ctrl, id);
    CHECK(fabs(now - want) < 1e-6, "state: parameter %u set to %g through process() reads %g", id, want, now);
    mem_stream s1 = { &ms_vtbl, NULL, 0, 0, 0 }, s2 = { &ms_vtbl, NULL, 0, 0, 0 };
    CHECK(a->c->getState(a->comp, (IBStream *)&s1) == kResultOk && s1.len > 0, "getState");
    teardown(a);
    plug_t b;
    CHECK(plug_new(&b), "second instance");
    s1.pos = 0;
    CHECK(b.c->setState(b.comp, (IBStream *)&s1) == kResultOk, "setState");
    double got = b.e->getParamNormalized(b.ctrl, id);
    CHECK(fabs(got - want) < 1e-6, "state: parameter %u restored as %g, not %g", id, got, want);
    CHECK(b.c->getState(b.comp, (IBStream *)&s2) == kResultOk, "getState after setState");
    if (s2.len != s1.len || memcmp(s1.buf, s2.buf, (size_t)s1.len))   /* values the engine works out itself, not marked "live" */
        printf("note: state saved again after a restore differs (%lld vs %lld bytes)\n", (long long)s2.len, (long long)s1.len);
    printf("state: %lld bytes, parameter %u round trip ok\n", (long long)s1.len, id);
    plug_free(&b);
    free(s1.buf); free(s2.buf);
}

#ifdef HOST_X11
/* The editor in a real X11 window, as a DAW embeds it, but hidden: the parent is never mapped, so nothing shows on the
 * desktop. A fake IPlugFrame offers an IRunLoop like Reaper's; the test pumps it, clicks the page tab and then the first
 * always-shown radio button whose option isn't already picked, and checks the parameter moves once process() runs. */
#include <X11/Xlib.h>
#include <poll.h>
#include <time.h>
typedef struct {
    const PlugFrameVtbl *frame;
    const RunLoopVtbl *loop;
    void *fd_handler, *timer;
    int fd, refs;
} fake_frame_t;
#define FF(ptr, m) ((fake_frame_t *)((char *)(ptr) - offsetof(fake_frame_t, m)))
static tresult ff_query(fake_frame_t *f, const TUID iid, void **o) {
    if (!memcmp(iid, iid_IRunLoop, 16)) { *o = &f->loop; f->refs++; return kResultOk; }
    if (!memcmp(iid, iid_IPlugFrame, 16) || !memcmp(iid, iid_FUnknown, 16)) { *o = &f->frame; f->refs++; return kResultOk; }
    *o = NULL;
    return kNoInterface;
}
static tresult fr_q(void *s, const TUID iid, void **o) { return ff_query(FF(s, frame), iid, o); }
static uint32_t fr_ref(void *s) { return ++FF(s, frame)->refs; }
static uint32_t fr_rel(void *s) { return --FF(s, frame)->refs; }
static tresult fr_resize(void *s, void *view, ViewRect *r) { (void)s; (void)view; (void)r; return kResultOk; }
static tresult rl_q(void *s, const TUID iid, void **o) { return ff_query(FF(s, loop), iid, o); }
static uint32_t rl_ref(void *s) { return ++FF(s, loop)->refs; }
static uint32_t rl_rel(void *s) { return --FF(s, loop)->refs; }
static tresult rl_reg_ev(void *s, void *h, int fd) { FF(s, loop)->fd_handler = h; FF(s, loop)->fd = fd; return kResultOk; }
static tresult rl_unreg_ev(void *s, void *h) { if (FF(s, loop)->fd_handler == h) FF(s, loop)->fd_handler = NULL; return kResultOk; }
static tresult rl_reg_tm(void *s, void *h, uint64_t ms) { (void)ms; FF(s, loop)->timer = h; return kResultOk; }
static tresult rl_unreg_tm(void *s, void *h) { if (FF(s, loop)->timer == h) FF(s, loop)->timer = NULL; return kResultOk; }
static const PlugFrameVtbl fr_vtbl = { fr_q, fr_ref, fr_rel, fr_resize };
static const RunLoopVtbl rl_vtbl = { rl_q, rl_ref, rl_rel, rl_reg_ev, rl_unreg_ev, rl_reg_tm, rl_unreg_tm };

/* a DAW's IComponentHandler: records the editor's last gesture */
typedef struct { const IComponentHandlerVtbl *v; int begins, ends, edits; uint32_t id; double value; } fake_handler_t;
static tresult fh_q(void *s, const TUID iid, void **o) { (void)s; (void)iid; *o = NULL; return kNoInterface; }
static uint32_t fh_ref(void *s) { (void)s; return 1; }
static tresult fh_begin(void *s, uint32_t id) { ((fake_handler_t *)s)->begins++; ((fake_handler_t *)s)->id = id; return kResultOk; }
static tresult fh_perform(void *s, uint32_t id, double v) { fake_handler_t *h = s; h->edits += h->id == id; h->value = v; return kResultOk; }
static tresult fh_end(void *s, uint32_t id) { ((fake_handler_t *)s)->ends += ((fake_handler_t *)s)->id == id; return kResultOk; }
static tresult fh_restart(void *s, int32_t f) { (void)s; (void)f; return kResultOk; }
static const IComponentHandlerVtbl fh_vtbl = { fh_q, fh_ref, fh_ref, fh_begin, fh_perform, fh_end, fh_restart };

static void pump(fake_frame_t *f, int ms) {
    for (int t = 0; t < ms; t += 10) {
        struct pollfd pf = { f->fd, POLLIN, 0 };
        if (f->fd_handler && poll(&pf, 1, 10) > 0) VT(EventHandlerVtbl, f->fd_handler)->onFDIsSet(f->fd_handler, f->fd);
        else if (!f->fd_handler) { struct timespec ts = { 0, 10000000 }; nanosleep(&ts, NULL); }
        if (f->timer) VT(TimerHandlerVtbl, f->timer)->onTimer(f->timer);
    }
}

static void test_window(plug_t *pl, const char *so_path) {
    Display *dpy = getenv("DISPLAY") ? XOpenDisplay(NULL) : NULL;
    if (!dpy) { printf("editor window: not tried (no X display)\n"); return; }
    /* the radio buttons, from the bundle's desktop.skin */
    char path[1024], line[4096];
    snprintf(path, sizeof path, "%s", so_path);
    char *slash = strrchr(path, '/');
    if (slash) *slash = 0;
    strncat(path, "/../Resources/skin/desktop.skin", sizeof path - strlen(path) - 1);
    FILE *sk = fopen(path, "r");
    int tabs = 0, hx = 0, hy = 0, hp = -1, htab = 0;
    double want = 0;
    while (sk && fgets(line, sizeof line, sk)) {
        if (!strncmp(line, "tab\t", 4)) tabs++;
        if (hp >= 0 || strncmp(line, "hit\t", 4) || !strstr(line, "mode=radio") || strstr(line, "\tif=")) continue;
        int x, y, w, h, p, id, n;
        if (sscanf(line, "hit\tx=%d\ty=%d\tw=%d\th=%d\tparam=%d\tmode=radio\tid=%d\tn=%d", &x, &y, &w, &h, &p, &id, &n) != 7 || n < 2) continue;
        double v = (double)id / (n - 1);
        if (fabs(pl->e->getParamNormalized(pl->ctrl, (uint32_t)p) - v) < 1e-6) continue;
        hx = x + w / 2; hy = y + h / 2; hp = p; want = v; htab = tabs - 1;
    }
    if (sk) fclose(sk);
    Window parent = XCreateSimpleWindow(dpy, DefaultRootWindow(dpy), 0, 0, 1280, 700, 0, 0, 0);   /* never mapped */
    XFlush(dpy);
    fake_frame_t f = { &fr_vtbl, &rl_vtbl, NULL, NULL, -1, 1 };
    void *view = pl->e->createView(pl->ctrl, "editor");
    const PlugViewVtbl *v = VT(PlugViewVtbl, view);
    CHECK(v->setFrame(view, &f.frame) == kResultOk, "editor: setFrame");
    CHECK(v->attached(view, (void *)(uintptr_t)parent, "X11EmbedWindowID") == kResultOk, "editor: attached");
    CHECK(f.fd_handler && f.timer, "editor: did not register with the host run loop");
    pump(&f, 200);
    Window root, par, *kids = NULL;
    unsigned nk = 0;
    XQueryTree(dpy, parent, &root, &par, &kids, &nk);
    CHECK(nk == 1, "editor: %u child windows (want 1)", nk);
    if (nk == 1 && hp >= 0) {
        if (!setup(pl, 44100)) CHECK(0, "editor window: setup");
        fake_handler_t fh = { &fh_vtbl, 0, 0, 0, 0xFFFFFFFFu, -1 };
        pl->e->setComponentHandler(pl->ctrl, (IComponentHandler *)&fh);
        for (int k = 0; k < 4; k++) {   /* press and release on the page's tab (above the page, 44 px), then on the button */
            int type = k & 1 ? ButtonRelease : ButtonPress;
            XEvent e;
            memset(&e, 0, sizeof e);
            e.xbutton.type = type; e.xbutton.display = dpy; e.xbutton.window = kids[0]; e.xbutton.root = root;
            e.xbutton.x = k < 2 ? (int)((htab + 0.5) * 1280 / tabs) : hx;
            e.xbutton.y = k < 2 ? 22 : hy + 44;
            e.xbutton.button = Button1; e.xbutton.same_screen = True;
            XSendEvent(dpy, kids[0], False, type == ButtonPress ? ButtonPressMask : ButtonReleaseMask, &e);
        }
        XFlush(dpy);
        pump(&f, 200);
        CHECK(fh.begins == 1 && fh.edits == 1 && fh.ends == 1 && fh.id == (uint32_t)hp && fabs(fh.value - want) < 1e-6,
              "editor window: the click reached the host as %d begin / %d perform / %d end on %u = %g (want 1/1/1 on %d = %g)",
              fh.begins, fh.edits, fh.ends, fh.id, fh.value, hp, want);
        pl->e->setComponentHandler(pl->ctrl, NULL);
        changes_t pc;   /* the host sends the edit back in process(), as a DAW does */
        changes_init(&pc);
        changes_set(&pc, (uint32_t)hp, fh.value);
        float buf[4][128] = {{0}};
        run(pl, buf[0], buf[1], buf[2], buf[3], 128, &pc, NULL, NULL);
        double got = pl->e->getParamNormalized(pl->ctrl, (uint32_t)hp);
        CHECK(fabs(got - want) < 1e-6, "editor window: a click on parameter %d's option left it at %g, not %g", hp, got, want);
        printf("editor window: drawn, a click on page %d set parameter %d to %g\n", htab + 1, hp, got);
        teardown(pl);
    } else printf("editor window: drawn (no radio button to click)\n");
    if (kids) XFree(kids);
    CHECK(v->removed(view) == kResultOk, "editor: removed");
    CHECK(!f.fd_handler && !f.timer, "editor: still registered with the run loop after removed()");
    CHECK(v->release(view) == 0, "editor: view still referenced after release");
    XQueryTree(dpy, parent, &root, &par, &kids, &nk);
    CHECK(nk == 0, "editor: its window outlived removed()");
    if (kids) XFree(kids);
    XDestroyWindow(dpy, parent);
    XCloseDisplay(dpy);
}
#endif

static void test_editor(plug_t *pl, void *so, const char *shots) {
    void *view = pl->e->createView(pl->ctrl, "editor");
    if (!view) { printf("editor: none\n"); return; }
    const PlugViewVtbl *v = VT(PlugViewVtbl, view);
    CHECK(v->isPlatformTypeSupported(view, "X11EmbedWindowID") == kResultOk, "editor: X11EmbedWindowID not supported");
    CHECK(v->isPlatformTypeSupported(view, "HWND") != kResultOk, "editor: claims HWND");
    ViewRect r = {0, 0, 0, 0};
    CHECK(v->getSize(view, &r) == kResultOk && r.right > 0 && r.bottom > 0, "editor: getSize");
    ViewRect half = {0, 0, r.right / 2, r.bottom};
    CHECK(v->checkSizeConstraint(view, &half) == kResultOk && labs((long)half.bottom * r.right - (long)r.bottom * half.right) <= r.right,
          "editor: checkSizeConstraint does not keep the shape (%dx%d for %dx%d)", half.right, half.bottom, r.right, r.bottom);
    printf("editor: %dx%d\n", r.right, r.bottom);
    CHECK(v->release(view) == 0, "editor: view still referenced after release");
    int (*snap)(void *, int, const char *) = (int (*)(void *, int, const char *))dlsym(so, "mpc_vst3_snapshot");
    if (!shots || !snap) return;
    char path[1024];
    int n = 0;
    for (; n < 64; n++) {
        snprintf(path, sizeof path, "%s/page%d.png", shots, n + 1);
        if (!snap(pl->comp, n, path)) break;
    }
    printf("editor: %d pages drawn to %s\n", n, shots);
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s plugin.so [--passthrough]\n", argv[0]); return 2; }
    int passthrough = 0;
    const char *shots = NULL;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--passthrough")) passthrough = 1;
        else if (!strcmp(argv[i], "--shots") && i + 1 < argc) shots = argv[++i];
    }
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!h) { printf("FAIL: dlopen: %s\n", dlerror()); return 1; }
    int (*entry)(void *) = (int (*)(void *))dlsym(h, "ModuleEntry");
    int (*leave)(void) = (int (*)(void))dlsym(h, "ModuleExit");
    void *(*get_factory)(void) = (void *(*)(void))dlsym(h, "GetPluginFactory");
    if (!entry || !leave || !get_factory) { printf("FAIL: missing ModuleEntry/ModuleExit/GetPluginFactory\n"); return 1; }
    CHECK(entry(h), "ModuleEntry");
    g_factory = get_factory();
    const FactoryVtbl *f = VT(FactoryVtbl, g_factory);
    void *f2 = NULL;
    CHECK(f->queryInterface(g_factory, iid_IPluginFactory2, &f2) == kResultOk, "no IPluginFactory2");
    CHECK(f->countClasses(g_factory) == 1, "class count %d", f->countClasses(g_factory));
    PClassInfo2 ci;
    CHECK(f->getClassInfo2(g_factory, 0, &ci) == kResultOk, "getClassInfo2");
    memcpy(g_cid, ci.cid, 16);
    g_effect = !strncmp(ci.subCategories, "Fx", 2);
    printf("class: %s (%s) by %s, version %s\n", ci.name, ci.subCategories, ci.vendor, ci.version);

    plug_t pl;
    if (!plug_new(&pl)) { printf("FAIL: could not create an instance with all three interfaces\n"); return 1; }
    TUID ccid;
    CHECK(pl.c->getControllerClassId(pl.comp, ccid) != kResultOk, "getControllerClassId names a separate controller");
    CHECK(pl.c->getBusCount(pl.comp, kEvent, kInput) == 1, "no MIDI input bus");
    test_params(&pl);
    test_audio(&pl, 44100, passthrough);
    test_audio(&pl, 48000, passthrough);
    test_audio(&pl, 96000, passthrough);
    test_programs(&pl);
    test_midi_cc(&pl);
    test_state(&pl);
    test_editor(&pl, h, shots);
#ifdef HOST_X11
    void *probe = pl.e->createView(pl.ctrl, "editor");   /* is there an editor? */
    if (probe) { VT(PlugViewVtbl, probe)->release(probe); test_window(&pl, argv[1]); }
#endif
    plug_free(&pl);
    CHECK(leave(), "ModuleExit");
    (void)h;   /* not dlclose()d: LeakSanitizer can then name the plugin's frames */
    printf(failures ? "%d FAILED\n" : "all passed\n", failures);
    return failures ? 1 : 0;
}
