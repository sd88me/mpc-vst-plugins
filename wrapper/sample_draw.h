/* sample_draw.h: a plugin's own page on the MPC Sample's screen, through mpc-addin-sample-draw-handler.
 *
 * The MPC Sample has no plugin editor: MPC shows a fixed list of its own effects. The draw handler addin owns the
 * screen and hands it to one client at a time (the page button, a long hold of PAD FX, cycles MPC -> each open client
 * -> MPC). This header is the client side for a plugin: open a page when the plugin is created, and a thread calls the
 * plugin's render function while the page has the screen (and only then), then shows the frame.
 *
 *     static void render(void *user, sdc_canvas *cv) { sdc_fill(cv, 0, 0, cv->w, cv->h, 0x101020); ... }
 *     sdc_page page;
 *     sdc_page_open(&page, "NAM", 15, render, plugin);   // effect creation; -1 = no draw handler: nothing to do
 *     sdc_page_close(&page);                             // effClose, before anything render reads is freed
 *
 * Header-only, C and C++, no link dependency: the addin's entry point is looked up at run time, so a plugin built with
 * this loads on every device and draws only where the addin runs (the MPC Sample). render runs on the page's own thread,
 * never MPC's audio or UI thread: read plugin state the way any other non-audio thread would.
 *
 * Input (draw handler 0.3+): sdc_page_set_input() takes the three keys above the screen, the data dial and the knobs
 * K1-K3 while the page has the screen (and, 0.4+, the dial pressed in: key 3) (pads, transport and every other button stay with MPC). The callback runs on the
 * addin's thread; a page drawn from state it changes shows the change on the next frame.
 *
 * The API struct below is a copy of mpc-addin-sample-draw-handler's src/mpc_sample_draw.h (API version 3): keep them
 * in step. The font is a 5x7 bitmap (upper case, digits and common punctuation), drawn at any whole-number scale. */
#ifndef MPC_VST_SAMPLE_DRAW_H
#define MPC_VST_SAMPLE_DRAW_H
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

/* ---- the addin's interface (copy of mpc_sample_draw.h, API version 1) ---- */
#ifndef MPC_SAMPLE_DRAW_H
#define MPC_SAMPLE_DRAW_H
#define MPC_SDRAW_ENTRY "mpc_sample_draw_api"
#define MPC_SDRAW_API_VERSION 3
typedef struct mpc_sdraw_client mpc_sdraw_client;
typedef void (*mpc_sdraw_focus_fn)(void *user, int has_screen);
enum { MPC_SDRAW_EV_KEY = 1, MPC_SDRAW_EV_DIAL = 2, MPC_SDRAW_EV_KNOB = 3, MPC_SDRAW_EV_KNOB_AT = 4 };
/* key: id 0-2 (soft keys) or 3 (the dial pressed in, version >= 3), value 1/0; dial: value steps; knob: id 0-2, position 0-127 after a turn; knob_at: where knob id already is
 * (sent when the page gets the screen, nothing turned: for pickup, catch a value only once the knob reaches it) */
typedef struct { int type, id, value; } mpc_sdraw_event;
typedef void (*mpc_sdraw_input_fn)(void *user, const mpc_sdraw_event *e);
typedef struct {
    int version;
    int width, height;
    mpc_sdraw_client *(*open)(const char *name, mpc_sdraw_focus_fn focus, void *user);
    void (*close)(mpc_sdraw_client *c);
    int (*request)(mpc_sdraw_client *c);
    void (*release)(mpc_sdraw_client *c);
    int (*has_screen)(mpc_sdraw_client *c);
    uint32_t *(*pixels)(mpc_sdraw_client *c, int *stride);
    void (*present)(mpc_sdraw_client *c, int x, int y, int w, int h);
    void (*set_input)(mpc_sdraw_client *c, mpc_sdraw_input_fn fn, void *user);   /* version >= 2 only */
    int (*show)(mpc_sdraw_client *c, const char *name);   /* version >= 3 only: hand the screen to the page named name */
} mpc_sdraw_api;
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---- drawing ---- */
typedef struct { uint32_t *px; int stride, w, h; } sdc_canvas;   /* 0x00RRGGBB, row-major */

static inline void sdc_fill(sdc_canvas *cv, int x, int y, int w, int h, uint32_t col)
{
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > cv->w) w = cv->w - x;
    if (y + h > cv->h) h = cv->h - y;
    for (int r = 0; r < h; r++) {
        uint32_t *p = cv->px + (size_t)(y + r) * (size_t)cv->stride + x;
        for (int i = 0; i < w; i++) p[i] = col;
    }
}

static inline void sdc_frame(sdc_canvas *cv, int x, int y, int w, int h, int t, uint32_t col)
{
    sdc_fill(cv, x, y, w, t, col); sdc_fill(cv, x, y + h - t, w, t, col);
    sdc_fill(cv, x, y, t, h, col); sdc_fill(cv, x + w - t, y, t, h, col);
}

static const char SDC_GLYPHS[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.:/%-#+=()_,'!?&<>*";
static const uint8_t SDC_FONT[][7] = {
    {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},{31,2,4,2,1,17,14},{2,6,10,18,31,2,2},
    {31,16,30,1,1,17,14},{6,8,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},{14,17,17,15,1,2,12},
    {14,17,17,31,17,17,17},{30,17,17,30,17,17,30},{14,17,16,16,16,17,14},{28,18,17,17,17,18,28},
    {31,16,16,30,16,16,31},{31,16,16,30,16,16,16},{14,17,16,23,17,17,15},{17,17,17,31,17,17,17},
    {14,4,4,4,4,4,14},{7,2,2,2,2,18,12},{17,18,20,24,20,18,17},{16,16,16,16,16,16,31},{17,27,21,21,17,17,17},
    {17,17,25,21,19,17,17},{14,17,17,17,17,17,14},{30,17,17,30,16,16,16},{14,17,17,17,21,18,13},
    {30,17,17,30,20,18,17},{15,16,16,14,1,1,30},{31,4,4,4,4,4,4},{17,17,17,17,17,17,14},{17,17,17,17,17,10,4},
    {17,17,17,21,21,21,10},{17,17,10,4,10,17,17},{17,17,17,10,4,4,4},{31,1,2,4,8,16,31},
    {0,0,0,0,0,12,12},{0,12,12,0,12,12,0},{0,1,2,4,8,16,0},{24,25,2,4,8,19,3},{0,0,0,31,0,0,0},
    {10,10,31,10,31,10,10},{0,4,4,31,4,4,0},{0,0,31,0,31,0,0},
    {2,4,8,8,8,4,2},{8,4,2,2,2,4,8},{0,0,0,0,0,0,31},{0,0,0,0,12,4,8},{4,4,8,0,0,0,0},{4,4,4,4,4,0,4},
    {14,17,1,2,4,0,4},{12,18,20,8,21,18,13},{2,4,8,16,8,4,2},{8,4,2,1,2,4,8},{0,4,21,14,21,4,0},
};

/* Width in pixels of s drawn at scale (a glyph is 6 * scale wide, the last one 5 * scale). */
static inline int sdc_text_width(const char *s, int scale) { int n = (int)strlen(s); return n ? (6 * n - 1) * scale : 0; }

static const uint8_t SDC_FLAT[7] = {16,16,16,22,25,18,28};

/* Text with its top left at (x, y), 7 * scale high. Lower case is drawn as upper case, anything else unknown as a space;
 * a lower-case b right after a note letter A-G and not before another letter is a flat sign ("Ab" stays readable).
 * Returns the x after the text. */
static inline int sdc_text(sdc_canvas *cv, int x, int y, int scale, uint32_t col, const char *s)
{
    char prev = 0;
    for (; *s; prev = *s, s++, x += 6 * scale) {
        char ch = *s >= 'a' && *s <= 'z' ? (char)(*s - 32) : *s;
        int flat = *s == 'b' && prev >= 'A' && prev <= 'G' &&
                   !((s[1] >= 'a' && s[1] <= 'z') || (s[1] >= 'A' && s[1] <= 'Z'));
        const char *g = ch ? strchr(SDC_GLYPHS, ch) : NULL;
        if (!g && !flat) continue;
        const uint8_t *rows = flat ? SDC_FLAT : SDC_FONT[g - SDC_GLYPHS];
        for (int r = 0; r < 7; r++)
            for (int b = 0; b < 5; b++)
                if (rows[r] & (16 >> b)) sdc_fill(cv, x + b * scale, y + r * scale, scale, scale, col);
    }
    return x;
}

/* ---- the page ---- */
typedef void (*sdc_render_fn)(void *user, sdc_canvas *cv);

typedef struct {
    const mpc_sdraw_api *api;
    mpc_sdraw_client *c;
    sdc_render_fn render;
    void *user;
    int period_ms;
    int run;          /* __atomic */
    pthread_t th;
} sdc_page;

static inline const mpc_sdraw_api *sdc_api(void)
{
    typedef const mpc_sdraw_api *(*get_fn)(int);
    get_fn get = (get_fn)dlsym(RTLD_DEFAULT, MPC_SDRAW_ENTRY);
    if (!get) return NULL;
    for (int v = MPC_SDRAW_API_VERSION; v >= 1; v--) {   /* an older addin: what it has (1: drawing only) */
        const mpc_sdraw_api *api = get(v);
        if (api) return api;
    }
    return NULL;
}

static inline void sdc_sleep_ms(int ms)
{
    struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

static void *sdc_page_thread(void *arg)
{
    sdc_page *pg = (sdc_page *)arg;
    while (__atomic_load_n(&pg->run, __ATOMIC_ACQUIRE)) {
        if (!pg->api->has_screen(pg->c)) { sdc_sleep_ms(100); continue; }
        sdc_canvas cv;
        cv.px = pg->api->pixels(pg->c, &cv.stride);
        cv.w = pg->api->width; cv.h = pg->api->height;
        pg->render(pg->user, &cv);
        pg->api->present(pg->c, 0, 0, 0, 0);
        sdc_sleep_ms(pg->period_ms);
    }
    return NULL;
}

static void sdc_page_focus(void *user, int has_screen) { (void)user; (void)has_screen; }   /* the thread polls has_screen */

/* Opens the page (named on the draw handler's status) and starts its thread. 0, or -1 when there's no draw handler
 * here (any device but the MPC Sample, or the addin not installed): pg is then inert and sdc_page_close is a no-op. */
static inline int sdc_page_open(sdc_page *pg, const char *name, int fps, sdc_render_fn render, void *user)
{
    memset(pg, 0, sizeof *pg);
    const mpc_sdraw_api *api = sdc_api();
    if (!api || !render) return -1;
    pg->c = api->open(name, sdc_page_focus, pg);
    if (!pg->c) return -1;
    pg->api = api; pg->render = render; pg->user = user;
    pg->period_ms = 1000 / (fps > 0 && fps <= 60 ? fps : 15);
    __atomic_store_n(&pg->run, 1, __ATOMIC_RELEASE);
    if (pthread_create(&pg->th, NULL, sdc_page_thread, pg) != 0) {
        api->close(pg->c); memset(pg, 0, sizeof *pg); return -1;
    }
    return 0;
}

/* Take the soft keys, the dial and the knobs while the page has the screen. 0, or -1 when the draw handler is too old
 * for input (or there is none). */
static inline int sdc_page_set_input(sdc_page *pg, mpc_sdraw_input_fn fn, void *user)
{
    if (!pg->api || pg->api->version < 2 || !pg->api->set_input) return -1;
    pg->api->set_input(pg->c, fn, user);
    return 0;
}

/* Hand the screen to the open page called name (a rack opening a plugin's page). While that page has it, a long hold of
 * the page button comes back here. 0, or -1 (no such page, or a draw handler older than 0.4). */
static inline int sdc_page_show(sdc_page *pg, const char *name)
{
    if (!pg->api || pg->api->version < 3 || !pg->api->show) return -1;
    return pg->api->show(pg->c, name);
}

/* Stops the thread (waits for a frame in progress) and gives the screen back to MPC if the page had it. */
static inline void sdc_page_close(sdc_page *pg)
{
    if (!pg->api) return;
    __atomic_store_n(&pg->run, 0, __ATOMIC_RELEASE);
    pthread_join(pg->th, NULL);
    pg->api->close(pg->c);
    memset(pg, 0, sizeof *pg);
}

#ifdef __cplusplus
}
#endif
#endif
