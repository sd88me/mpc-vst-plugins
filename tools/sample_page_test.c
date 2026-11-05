/* Offline test of a port's MPC Sample page (vst.json "sample_page", wrapper/sample_page.h), run by tools/test_sample_page.sh
 * under ThreadSanitizer. This file stands in for mpc-addin-sample-draw-handler (it exports mpc_sample_draw_api, so the
 * page opens here as it does on the device) and for the host. Checks:
 *   - no page at creation (a scan or probe instance), one page, named after the plugin, at effMainsChanged
 *   - knob pickup: a knob that reaches the param's value moves it, at the next audio block
 *   - the dial: a programs dial loads the next program once still for 250 ms; another dial steps its param
 *   - the page's input thread, its drawing thread, the audio thread and a host thread setting and reading params all at
 *     once for a while: no data race (TSan) and no crash
 * Exit 1 on a failed check (TSan's own exit code on a race). */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <pthread.h>
#include "params.h"

typedef struct AEffect AEffect;
typedef intptr_t (*cb)(AEffect*,int32_t,int32_t,intptr_t,void*,float);
struct AEffect { int32_t magic; intptr_t (*d)(AEffect*,int32_t,int32_t,intptr_t,void*,float);
 void*p; void (*setP)(AEffect*,int32_t,float); float (*getP)(AEffect*,int32_t);
 int32_t np,npar,ni,no,flags; intptr_t r1,r2; int32_t a,b,c; float io; void*obj,*user; int32_t uid,ver;
 void (*pr)(AEffect*,float**,float**,int32_t); void*pdr; char f[56]; };
extern AEffect* VSTPluginMain(cb);

static double ti[16];
static intptr_t host(AEffect*e,int32_t op,int32_t i,intptr_t v,void*p,float o){
    (void)e; (void)i; (void)v; (void)p; (void)o;
    if (op == 7) { ti[4] = 120.0; ((int32_t*)&ti[8])[5] = 1 << 10; return (intptr_t)ti; }
    return 0;
}
static int fails;
#define CHECK(c, ...) do { printf("%s ", (c) ? "ok  " : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!(c)) fails++; } while (0)

/* ---- the stand-in draw handler (the API in wrapper/sample_draw.h, version 3) ---- */
typedef struct mpc_sdraw_client mpc_sdraw_client;
typedef void (*focus_fn)(void *user, int has_screen);
typedef struct { int type, id, value; } ev_t;
typedef void (*input_fn)(void *user, const ev_t *e);
typedef struct {
    int version, width, height;
    mpc_sdraw_client *(*open)(const char *name, focus_fn focus, void *user);
    void (*close)(mpc_sdraw_client *c);
    int (*request)(mpc_sdraw_client *c);
    void (*release)(mpc_sdraw_client *c);
    int (*has_screen)(mpc_sdraw_client *c);
    uint32_t *(*pixels)(mpc_sdraw_client *c, int *stride);
    void (*present)(mpc_sdraw_client *c, int x, int y, int w, int h);
    void (*set_input)(mpc_sdraw_client *c, input_fn fn, void *user);
    int (*show)(mpc_sdraw_client *c, const char *name);
} api_t;
struct mpc_sdraw_client { char name[64]; uint32_t px[320 * 240]; };
static int opens, closes, frames;
static char opened_name[64];
static input_fn in_fn;
static void *in_user;
static pthread_mutex_t hmu = PTHREAD_MUTEX_INITIALIZER;   /* the handler's own lock, as the real one has */

static mpc_sdraw_client *h_open(const char *name, focus_fn f, void *u)
{
    (void)f; (void)u;
    mpc_sdraw_client *c = calloc(1, sizeof *c);
    snprintf(c->name, sizeof c->name, "%s", name);
    pthread_mutex_lock(&hmu); opens++; snprintf(opened_name, sizeof opened_name, "%s", name); pthread_mutex_unlock(&hmu);
    return c;
}
static void h_close(mpc_sdraw_client *c) { pthread_mutex_lock(&hmu); closes++; in_fn = NULL; pthread_mutex_unlock(&hmu); free(c); }
static int h_request(mpc_sdraw_client *c) { (void)c; return 0; }
static void h_release(mpc_sdraw_client *c) { (void)c; }
static int h_has_screen(mpc_sdraw_client *c) { (void)c; return 1; }
static uint32_t *h_pixels(mpc_sdraw_client *c, int *stride) { *stride = 320; return c->px; }
static void h_present(mpc_sdraw_client *c, int x, int y, int w, int h) { (void)c; (void)x; (void)y; (void)w; (void)h; __atomic_add_fetch(&frames, 1, __ATOMIC_RELAXED); }
static void h_set_input(mpc_sdraw_client *c, input_fn fn, void *u) { (void)c; pthread_mutex_lock(&hmu); in_fn = fn; in_user = u; pthread_mutex_unlock(&hmu); }
static int h_show(mpc_sdraw_client *c, const char *name) { (void)c; (void)name; return 0; }
static const api_t API = { 3, 320, 240, h_open, h_close, h_request, h_release, h_has_screen, h_pixels, h_present, h_set_input, h_show };
const api_t *mpc_sample_draw_api(int version) { (void)version; return &API; }

/* an input event, delivered as the handler's input thread does: under its lock, one at a time */
static void send_ev(int type, int id, int value)
{
    ev_t e = { type, id, value };
    pthread_mutex_lock(&hmu);
    if (in_fn) in_fn(in_user, &e);
    pthread_mutex_unlock(&hmu);
}
enum { KEY = 1, DIAL = 2, KNOB = 3, KNOB_AT = 4 };

static void sleep_ms(int ms) { struct timespec t = { ms / 1000, (long)(ms % 1000) * 1000000L }; nanosleep(&t, NULL); }

/* ---- the audio thread and a host thread ---- */
static AEffect *fx;
static int run_flag = 1;
static void *audio(void *arg)
{
    (void)arg;
    float L[128], R[128], I0[128] = {0}, I1[128] = {0}, *o[2] = {L, R}, *in[2] = {I0, I1};
    while (__atomic_load_n(&run_flag, __ATOMIC_ACQUIRE)) { fx->pr(fx, fx->ni >= 2 ? in : 0, o, 128); sleep_ms(3); }
    return NULL;
}
static int host_busy;
static void *host_ui(void *arg)
{
    (void)arg;
    unsigned s = 1;
    while (__atomic_load_n(&run_flag, __ATOMIC_ACQUIRE)) {
        if (__atomic_load_n(&host_busy, __ATOMIC_ACQUIRE)) {
            s = s * 1103515245u + 12345u;
            int i = (int)((s >> 8) % NPARAMS);
            if (!PARAMS[i].momentary) fx->setP(fx, i, fx->getP(fx, i));   /* MPC's own writes: what it read back */
            char buf[64];
            fx->d(fx, 7, i, 0, buf, 0);   /* effGetParamDisplay */
        }
        sleep_ms(2);
    }
    return NULL;
}

static void blocks_ms(int ms) { sleep_ms(ms); }   /* the audio thread runs meanwhile */

int main(void)
{
    fx = VSTPluginMain(host);
    CHECK(fx != NULL, "an instance");
    if (!fx) return 1;
    CHECK(opens == 0, "no page at creation (a scan or probe instance opens none)");
    fx->d(fx, 12, 0, 1, 0, 0);   /* effMainsChanged on */
    fx->d(fx, 12, 0, 0, 0, 0);
    fx->d(fx, 12, 0, 1, 0, 0);
    CHECK(opens == 1 && !strcmp(opened_name, PLUG_NAME), "one page at effMainsChanged, named \"%s\" (%d opened)", opened_name, opens);

    pthread_t at, ht;
    pthread_create(&at, NULL, audio, NULL);
    pthread_create(&ht, NULL, host_ui, NULL);
    blocks_ms(200);
    int nf = __atomic_load_n(&frames, __ATOMIC_RELAXED);
    CHECK(nf > 0, "the page draws (%d frames)", nf);

    /* knob pickup on the first bank's first knob */
    int i = SAMPLE_BANKS[0].knob[0];
    if (i >= 0) {
        fx->setP(fx, i, 0.25f);
        blocks_ms(30);
        float before = fx->getP(fx, i);
        send_ev(KNOB_AT, 0, 100);       /* the knob is far from the value */
        send_ev(KNOB, 0, 101);
        blocks_ms(30);
        CHECK(fabsf(fx->getP(fx, i) - before) < 1e-4f, "K1 away from the param's value doesn't move it (pickup)");
        int at_v = (int)lroundf(before * 127);
        send_ev(KNOB, 0, at_v);         /* reaches it: caught */
        send_ev(KNOB, 0, at_v + 20 > 127 ? 127 : at_v + 20);
        blocks_ms(30);
        CHECK(fx->getP(fx, i) > before + 0.05f, "K1 moves the param once it reaches its value (%.3f -> %.3f)", before, fx->getP(fx, i));
    }
#if SAMPLE_DIAL >= 0
#if defined(PROG_PARAM) && SAMPLE_DIAL == PROG_PARAM
    fx->d(fx, 2, 0, 0, 0, 0);   /* effSetProgram 0 */
    blocks_ms(30);
    int p0 = (int)fx->d(fx, 3, 0, 0, 0, 0);
    send_ev(DIAL, 0, 1);
    send_ev(DIAL, 0, 1);
    blocks_ms(100);
    CHECK((int)fx->d(fx, 3, 0, 0, 0, 0) == p0, "no program load while the dial moves");
    blocks_ms(400);
    int p1 = (int)fx->d(fx, 3, 0, 0, 0, 0);
    CHECK(p1 == p0 + 2, "two dial steps load program %d, 250 ms after the dial stops (got %d)", p0 + 2, p1);
    for (int k = 0; k < NPROGRAMS + 5; k++) send_ev(DIAL, 0, 1);   /* past the end: stays on the last program */
    blocks_ms(500);
    p1 = (int)fx->d(fx, 3, 0, 0, 0, 0);
    CHECK(p1 == NPROGRAMS - 1, "the dial stops at the last program (%d of %d)", p1, NPROGRAMS);
#else
    float d0 = fx->getP(fx, SAMPLE_DIAL);
    send_ev(DIAL, 0, 1);
    blocks_ms(30);
    CHECK(fx->getP(fx, SAMPLE_DIAL) != d0 || d0 >= 1.0f, "the dial steps its param");
#endif
#endif

    /* everything at once: keys, the dial, knobs, bank changes, while the host sets and reads params and the page draws */
    __atomic_store_n(&host_busy, 1, __ATOMIC_RELEASE);
    unsigned s = 7;
    for (int n = 0; n < 3000; n++) {
        s = s * 1103515245u + 12345u;
        int r = (int)((s >> 8) % 10);
        if (r < 5) send_ev(KNOB, (int)((s >> 4) % 3), (int)((s >> 12) % 128));
        else if (r < 7) send_ev(KNOB_AT, (int)((s >> 4) % 3), (int)((s >> 12) % 128));
        else if (r < 9) send_ev(DIAL, 0, (s >> 16) & 1 ? 1 : -1);
        else send_ev(KEY, (int)((s >> 4) % 3), 1);
        if (n % 50 == 0) sleep_ms(1);
    }
    blocks_ms(400);
    CHECK(1, "3000 page events while the host and the audio thread run");

    __atomic_store_n(&run_flag, 0, __ATOMIC_RELEASE);
    pthread_join(ht, NULL);
    pthread_join(at, NULL);
    fx->d(fx, 1, 0, 0, 0, 0);   /* effClose: closes the page first */
    CHECK(closes == 1, "effClose closes the page");
    printf(fails ? "FAILED (%d)\n" : "PASSED\n", fails);
    return fails ? 1 : 0;
}
