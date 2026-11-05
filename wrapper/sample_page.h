/* sample_page.h: a port's own page on the MPC Sample's screen, from vst.json "sample_page" (gen_vst.py sample_lines()).
 * Included by vst2_wrap.c only when params.h defines SAMPLE_PAGE; it uses the wrapper's own helpers (get_norm, cc_set,
 * the program calls, param_name_text / param_value_text), so it is part of vst2_wrap.c, not a separate unit.
 *
 * The MPC Sample's UI has no plugin screen. With mpc-addin-sample-draw-handler installed, each instance opens a page
 * named after the plugin (PLUG_NAME): the RACK addin's dial press opens it, and a long hold of PAD FX goes back to RACK.
 * Anywhere else (other devices, no addin, the desktop VST3) sdc_page_open fails and none of this runs.
 *
 *   keys above the screen   with a "dial" param: < and > step it, the third key goes to the next bank of knobs;
 *                           without: < and > change bank
 *   data dial               steps the "dial" param (a preset list loads 250 ms after the dial stops)
 *   K1-K3                   the current bank's three params, picked up (soft takeover): a knob moves a param only once it
 *                           reaches the param's value (or passes it), so nothing jumps; the page shows where to turn
 *
 * Between the key bar and the knobs: the dial param's value (large), then the "lines" readouts, then whatever space is
 * left goes to the engine's mpc_engine_sample_draw() if it defines one (engine.h). */
#include "sample_draw.h"

#ifndef SAMPLE_FPS
#define SAMPLE_FPS 15
#endif

#define SP_KNOBS_Y 164
#define SP_BAR_H 20
static const uint32_t SP_BG = 0x0b0820, SP_PINK = 0xff2fa0, SP_TEXT = 0xf0e8ff, SP_DIM = 0x8a7ab8, SP_CYAN = 0x22e6ff,
                      SP_PANEL = 0x1a1040, SP_LOCK = 0x5a4a88;

typedef struct {
    wrap_t *w;
    sdc_page page;
    pthread_mutex_t mu;      /* the fields below: the draw handler's input thread and the page thread */
    int bank;
    int caught[3];           /* the knob has reached its param's value: it now moves it */
    int at[3];               /* where each knob is, 0..127 (-1: unknown until it moves or the handler reports it) */
    float set_v[3];          /* the value a caught knob last set (a change from elsewhere drops the catch) */
    int target, target_set;  /* the dial on a preset list: the preset to load, once it has been still for 250 ms */
    long long target_ms;
} sample_page_t;

static __attribute__((unused)) long long sp_now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1000LL + t.tv_nsec / 1000000; }

static int sp_knob(const sample_page_t *sp, int k) { return SAMPLE_BANKS[sp->bank].knob[k]; }

static void sp_bank(sample_page_t *sp, int d)
{
    sp->bank = ((sp->bank + d) % SAMPLE_NBANKS + SAMPLE_NBANKS) % SAMPLE_NBANKS;
    for (int k = 0; k < 3; k++) sp->caught[k] = 0;
}

#if SAMPLE_DIAL >= 0
static int sp_is_program(void)
{
#if defined(PROG_PARAM)
    return SAMPLE_DIAL == PROG_PARAM;
#else
    return 0;
#endif
}

/* the dial param's position in whole steps, and how many there are */
static int sp_steps(void)
{
    const param_t *p = &PARAMS[SAMPLE_DIAL];
    return p->nopts > 1 ? p->nopts : (int)lroundf(p->max - p->min) + 1;
}

static void sp_dial(sample_page_t *sp, int d)
{
    int n = sp_steps();
    if (n < 2) return;
    int cur = sp->target_set ? sp->target : (int)lroundf(get_norm(sp->w, SAMPLE_DIAL) * (n - 1));
    int to = cur + d;
    if (to < 0) to = 0;
    if (to > n - 1) to = n - 1;
    if (sp_is_program()) {   /* a preset loads on the page thread once the dial stops (a load can take a while) */
        sp->target = to; sp->target_set = 1; sp->target_ms = sp_now_ms();
    } else {
        cc_set(sp->w, SAMPLE_DIAL, (float)to / (n - 1));
    }
}
#endif

static void sp_input(void *user, const mpc_sdraw_event *e)
{
    sample_page_t *sp = user;
    pthread_mutex_lock(&sp->mu);
    if (e->type == MPC_SDRAW_EV_KEY && e->value) {
#if SAMPLE_DIAL >= 0
        if (e->id == 0) sp_dial(sp, -1);
        else if (e->id == 1) sp_dial(sp, 1);
        else if (e->id == 2) sp_bank(sp, 1);
#else
        if (e->id == 0) sp_bank(sp, -1);
        else if (e->id == 1) sp_bank(sp, 1);
#endif
    } else if (e->type == MPC_SDRAW_EV_DIAL) {
#if SAMPLE_DIAL >= 0
        sp_dial(sp, e->value);
#else
        sp_bank(sp, e->value > 0 ? 1 : -1);
#endif
    } else if (e->type == MPC_SDRAW_EV_KNOB_AT && e->id >= 0 && e->id < 3) {
        sp->at[e->id] = e->value;
        sp->caught[e->id] = 0;
    } else if (e->type == MPC_SDRAW_EV_KNOB && e->id >= 0 && e->id < 3) {
        int k = e->id, i = sp_knob(sp, k);
        int prev = sp->at[k];
        sp->at[k] = e->value;
        if (i >= 0) {
            float v = e->value / 127.0f, cur = get_norm(sp->w, i);
            if (!sp->caught[k]) {
                float pv = prev / 127.0f;
                if (fabsf(v - cur) <= 0.02f || (prev >= 0 && (pv - cur) * (v - cur) <= 0)) sp->caught[k] = 1;
            }
            if (sp->caught[k]) {
                cc_set(sp->w, i, v);
                sp->set_v[k] = get_norm(sp->w, i);
            }
        }
    }
    pthread_mutex_unlock(&sp->mu);
}

/* ---- drawing (the page thread) ---- */
static void sp_fit(char *out, size_t n, const char *s, int maxc)
{
    if ((int)strlen(s) <= maxc) { snprintf(out, n, "%s", s); return; }
    snprintf(out, n, "%.*s..", maxc - 2 > 0 ? maxc - 2 : 0, s);
}

static void sp_keybar(sdc_canvas *cv, const char *a, const char *b, const char *c)
{
    const char *k[3] = { a, b, c };
    for (int i = 0; i < 3; i++) {
        int x = i * 107, w = i == 2 ? cv->w - x : 106;
        sdc_fill(cv, x, 0, w, SP_BAR_H, SP_PANEL);
        char t[24];
        sp_fit(t, sizeof t, k[i], 8);
        if (t[0]) sdc_text(cv, x + (w - sdc_text_width(t, 2)) / 2, 3, 2, i == 2 ? SP_PINK : SP_TEXT, t);
    }
}

/* text wrapped at word boundaries into at most max_lines lines of cols characters; returns the y below it */
static __attribute__((unused)) int sp_wrap(sdc_canvas *cv, int x, int y, int scale, uint32_t col, const char *s, int cols, int max_lines)
{
    char line[64];
    int n = (int)strlen(s), pos = 0, lines = 0;
    while (pos < n && lines < max_lines) {
        while (s[pos] == ' ') pos++;
        int len = n - pos;
        if (len > cols) {
            len = cols;
            if (lines < max_lines - 1) { int b = len; while (b > 0 && s[pos + b] != ' ') b--; if (b > 0) len = b; }
        }
        if (len > (int)sizeof line - 1) len = sizeof line - 1;
        memcpy(line, s + pos, (size_t)len); line[len] = 0;
        if (lines == max_lines - 1 && pos + len < n && len >= 2) { line[len - 2] = '.'; line[len - 1] = '.'; }
        sdc_text(cv, x, y, scale, col, line);
        pos += len; lines++; y += 8 * scale + 3;
    }
    return lines ? y : y;
}

static void sp_render(void *user, sdc_canvas *cv)
{
    sample_page_t *sp = user;
    wrap_t *w = sp->w;
    char t[96], v[PARAM_TEXT_MAX > 96 ? PARAM_TEXT_MAX : 96];
    pthread_mutex_lock(&sp->mu);
#if SAMPLE_DIAL >= 0 && defined(PROG_PARAM)
    if (sp->target_set && sp_now_ms() - sp->target_ms >= 250) {
        int to = sp->target;
        sp->target_set = 0;
        pthread_mutex_unlock(&sp->mu);
        set_program(w, to);
        pthread_mutex_lock(&sp->mu);
        for (int k = 0; k < 3; k++) sp->caught[k] = 0;   /* a preset moves the knobs' params */
    }
#endif
    for (int k = 0; k < 3; k++) {   /* changed from elsewhere (the touchscreen, a preset, automation): pick up again */
        int i = sp_knob(sp, k);
        if (i >= 0 && sp->caught[k] && fabsf(get_norm(w, i) - sp->set_v[k]) > 0.02f) sp->caught[k] = 0;
    }
    sdc_fill(cv, 0, 0, cv->w, cv->h, SP_BG);

    /* key bar */
    const char *bank = SAMPLE_BANKS[sp->bank].name;
#if SAMPLE_DIAL >= 0
    char kl[24], kr[24], kb[24];
    param_name_text(w, SAMPLE_DIAL, t, sizeof t);
    snprintf(kl, sizeof kl, "< %.6s", t);
    snprintf(kr, sizeof kr, "%.6s >", t);
    snprintf(kb, sizeof kb, "%s >", SAMPLE_NBANKS > 1 ? bank : "");
    sp_keybar(cv, kl, kr, SAMPLE_NBANKS > 1 ? kb : "");
#else
    sp_keybar(cv, SAMPLE_NBANKS > 1 ? "< BANK" : "", SAMPLE_NBANKS > 1 ? "BANK >" : "", "");
#endif

    /* title line: the plugin, the bank */
    int y = SP_BAR_H + 5;
    sdc_text(cv, 6, y, 1, SP_DIM, PLUG_NAME);
    if (SAMPLE_NBANKS > 1) {
        snprintf(t, sizeof t, "%s %d/%d", bank, sp->bank + 1, SAMPLE_NBANKS);
        sdc_text(cv, cv->w - 6 - sdc_text_width(t, 1), y, 1, SP_CYAN, t);
    }
    y += 13;

    /* the dial param, large */
#if SAMPLE_DIAL >= 0
    int pending = sp->target_set;
    if (sp_is_program()) program_name(w, pending ? sp->target : get_program(w), v);
    else param_value_text(w, SAMPLE_DIAL, v, sizeof v);
    if (!v[0]) param_value_text(w, SAMPLE_DIAL, v, sizeof v);
    y = sp_wrap(cv, 6, y, 2, pending ? SP_PINK : SP_TEXT, v, 25, 2) + 2;
#endif

    /* readouts */
#if SAMPLE_NLINES > 0
    for (int l = 0; l < SAMPLE_NLINES && y < SP_KNOBS_Y - 10; l++) {
        const sample_line_t *ln = &SAMPLE_LINES[l];
        int s = ln->size < 1 ? 1 : ln->size > 4 ? 4 : ln->size;
        if (y + 8 * s > SP_KNOBS_Y - 4) break;
        param_value_text(w, ln->param, v, sizeof v);
        if (ln->label) {
            char nm[40];
            param_name_text(w, ln->param, nm, sizeof nm);
            snprintf(t, sizeof t, "%s: %s", nm, v);
        } else snprintf(t, sizeof t, "%s", v);
        sp_fit(v, sizeof v, t, (cv->w - 12) / (6 * s));
        sdc_text(cv, 6, y, s, ln->color ? ln->color : (s > 1 ? SP_TEXT : SP_DIM), v);
        y += 8 * s + 4;
    }
#endif

    /* the engine's own drawing in what's left */
    if (mpc_engine_sample_draw && SP_KNOBS_Y - 4 - y >= 16)
        mpc_engine_sample_draw(w->dsp, cv->px, cv->stride, 0, y, cv->w, SP_KNOBS_Y - 4 - y);

    /* the knobs */
    sdc_fill(cv, 0, SP_KNOBS_Y - 2, cv->w, 1, SP_LOCK);
    for (int k = 0; k < 3; k++) {
        int i = sp_knob(sp, k), x = k * 107 + 6;
        if (i < 0) continue;
        char nm[40];
        param_name_text(w, i, nm, sizeof nm);
        sp_fit(t, sizeof t, nm, 13);
        snprintf(nm, sizeof nm, "K%d %.13s", k + 1, t);
        sdc_text(cv, x, SP_KNOBS_Y + 4, 1, SP_DIM, nm);
        param_value_text(w, i, v, sizeof v);
        sp_fit(t, sizeof t, v, 8);
        sdc_text(cv, x, SP_KNOBS_Y + 18, 2, SP_TEXT, t);
        float cur = get_norm(w, i);
        int bw = 94, by = SP_KNOBS_Y + 42;
        sdc_fill(cv, x, by, bw, 6, SP_PANEL);
        sdc_fill(cv, x, by, (int)(bw * cur + 0.5f), 6, sp->caught[k] ? SP_CYAN : SP_DIM);
        if (!sp->caught[k]) {
            if (sp->at[k] >= 0) sdc_fill(cv, x + (int)(bw * sp->at[k] / 127.0f), by - 3, 2, 12, SP_PINK);
            const char *hint = sp->at[k] < 0 ? "TURN TO PICK UP" : sp->at[k] / 127.0f < cur ? "TURN >" : "< TURN";
            sdc_text(cv, x, by + 12, 1, SP_PINK, hint);
        }
    }
    pthread_mutex_unlock(&sp->mu);
}

static sample_page_t *sample_page_open(wrap_t *w)
{
    sample_page_t *sp = calloc(1, sizeof *sp);
    if (!sp) return NULL;
    sp->w = w;
    pthread_mutex_init(&sp->mu, NULL);
    for (int k = 0; k < 3; k++) sp->at[k] = -1;
    if (sdc_page_open(&sp->page, PLUG_NAME, SAMPLE_FPS, sp_render, sp) != 0) {   /* not on an MPC Sample with the addin */
        pthread_mutex_destroy(&sp->mu); free(sp); return NULL;
    }
    sdc_page_set_input(&sp->page, sp_input, sp);
    return sp;
}

/* before the engine goes: no frame or input call is in progress once this returns */
static void sample_page_close(sample_page_t *sp)
{
    if (!sp) return;
    sdc_page_close(&sp->page);
    pthread_mutex_destroy(&sp->mu);
    free(sp);
}
