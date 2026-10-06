/* Engine checks: every built-in program sounds, pitch is right, the sequencer plays with no key held, state and SysEx round-trip.
 *   gcc -O1 -fsanitize=address,undefined -Isrc -I../../wrapper -o /tmp/pe_test test/test_engine.c src/[!t]*.c -lm && /tmp/pe_test */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "engine.h"
#include "patch_tab.h"
#include "presets.h"
#include "syx.h"
#include "waves.h"

static int fails;
#define CHECK(c, ...) do { int ok_ = (c); printf(ok_ ? "ok   " : "FAIL "); printf(__VA_ARGS__); printf("\n"); fails += !ok_; } while (0)

static const mpc_engine_t *E;
static void setp(void *h, const char *k, int v) { char b[16]; snprintf(b, sizeof b, "%d", v); E->set_param(h, k, b); }
static void midi3(void *h, int a, int b, int c) { uint8_t m[3] = {(uint8_t)a, (uint8_t)b, (uint8_t)c}; E->midi(h, m, 3); }
/* renders n blocks, returns rms of the left channel; peak and NaN-free in *peak */
static double render(void *h, int blocks, float *peak, int16_t *keep) {
    int16_t o[256];
    double r = 0;
    *peak = 0;
    for (int k = 0; k < blocks; k++) {
        E->render(h, o, 128);
        for (int i = 0; i < 128; i++) {
            r += (double)o[2 * i] * o[2 * i];
            if (abs(o[2 * i]) > *peak) *peak = (float)abs(o[2 * i]);
            if (keep) keep[k * 128 + i] = o[2 * i];
        }
    }
    return sqrt(r / (blocks * 128.0)) / 32768;
}
/* frequency by zero crossings of a mono render */
static double zc_freq(const int16_t *x, int n) {
    int c = 0, first = -1, last = -1;
    for (int i = 1; i < n; i++)
        if (x[i - 1] < 0 && x[i] >= 0) { if (first < 0) first = i; last = i; c++; }
    return c > 1 ? (c - 1) * 44100.0 / (last - first) : 0;
}

int main(void) {
    E = mpc_engine();
    void *h = E->create(NULL);
    char b[1024];
    float pk;
    static int16_t buf[128 * 400];

    /* every built-in program makes sound when played, without overloading */
    for (int p = 0; p < presets_count(); p++) {
        setp(h, "program", p);
        E->get_param(h, "patch_name", b, sizeof b);
        char name[64]; snprintf(name, sizeof name, "%.60s", b);
        midi3(h, 0x90, 48, 100); midi3(h, 0x90, 55, 100);
        double r = render(h, 300, &pk, NULL);
        midi3(h, 0x80, 48, 0); midi3(h, 0x80, 55, 0);
        render(h, 200, &pk, NULL);
        CHECK(r > 0.005 && r < 0.6, "program %d \"%s\" sounds (rms %.3f)", p + 1, name, r);
    }

    /* pitch: Basic Program (osc 1+2 sawtooth at C0, key transpose -24) plays A4 at 440 Hz */
    setp(h, "program", 0);
    setp(h, "osc2_level", 0); setp(h, "lpf_freq", 164);
    midi3(h, 0x90, 69, 100);
    render(h, 20, &pk, NULL);
    render(h, 200, &pk, buf);
    double f = zc_freq(buf, 128 * 200);
    CHECK(fabs(f - 440) < 2, "A4 plays at %.1f Hz", f);
    midi3(h, 0x80, 69, 0);
    render(h, 200, &pk, NULL);
    double tail = render(h, 50, &pk, NULL);
    CHECK(tail < 1e-4, "release dies away (rms %.6f)", tail);

    /* digital oscillator alone, wave 1 (sine) */
    setp(h, "osc1_level", 0); setp(h, "osc3_level", 100); setp(h, "osc3_shape", 0);
    midi3(h, 0x90, 57, 100);
    render(h, 20, &pk, NULL);
    render(h, 200, &pk, buf);
    f = zc_freq(buf, 128 * 200);
    CHECK(fabs(f - 220) < 1.5, "Osc 3 sine plays A3 at %.1f Hz", f);
    midi3(h, 0x80, 57, 0);
    render(h, 300, &pk, NULL);

    /* the sequencer plays voice 1 with no key down when started */
    setp(h, "program", 4);   /* Sequenced Bass: Key Gates Seq Rst */
    setp(h, "trigger", 0);
    setp(h, "seq_run", 1); setp(h, "clock_src", 0);
    double r = render(h, 400, &pk, NULL);
    CHECK(r > 0.003, "sequencer running plays without a key (rms %.3f)", r);
    setp(h, "seq_run", 0);
    render(h, 400, &pk, NULL);
    r = render(h, 100, &pk, NULL);
    CHECK(r < 0.001, "stopped sequencer goes quiet (rms %.4f)", r);

    /* gated trigger mode: a key starts its own sequence */
    setp(h, "program", 4);
    midi3(h, 0x90, 40, 100);
    r = render(h, 300, &pk, NULL);
    CHECK(r > 0.003, "key-gated sequence plays (rms %.3f)", r);
    midi3(h, 0x80, 40, 0);
    render(h, 300, &pk, NULL);

    /* all parameters at their extremes: no NaN, nothing stuck at full scale */
    for (int pass = 0; pass < 2; pass++) {
        for (int i = 0; i < NPATCH; i++) setp(h, PTAB[i].key, pass ? PTAB[i].max : PTAB[i].min);
        midi3(h, 0x90, 60, 127); midi3(h, 0x90, 64, 127);
        r = render(h, 200, &pk, NULL);
        CHECK(r == r && r < 1.0, "all parameters at %s render (rms %.3f)", pass ? "maximum" : "minimum", r);
        midi3(h, 0xB0, 123, 0);
        render(h, 50, &pk, NULL);
    }

    /* state round trip */
    setp(h, "program", 2);
    setp(h, "lpf_res", 77);
    static char st[8192];
    E->get_param(h, "state", st, sizeof st);
    void *h2 = E->create(NULL);
    E->set_param(h2, "state", st);
    E->get_param(h2, "lpf_res", b, sizeof b);
    CHECK(atoi(b) == 77, "state restores lpf_res (%s)", b);
    E->get_param(h2, "patch_name", b, sizeof b);
    CHECK(!strcmp(b, "Hollow Pad"), "state restores the name (%s)", b);
    E->get_param(h2, "osc3_shape_display", b, sizeof b);
    CHECK(!strcmp(b, "13"), "wave display is 1-based (%s)", b);
    E->get_param(h2, "dly1_time_display", b, sizeof b);
    CHECK(strstr(b, "ms") != NULL, "delay time shows ms (%s)", b);
    E->get_param(h2, "lfo1_freq_display", b, sizeof b);
    CHECK(!strcmp(b, "0.16 Hz") || b[0], "LFO frequency text (%s)", b);

    /* SysEx program dump: pack and unpack */
    uint8_t prog[192], msg[300], back[192];
    for (int i = 0; i < 192; i++) prog[i] = (uint8_t)((i * 37) & 0xFF);
    int n = syx_write_program(prog, 2, 17, msg);
    CHECK(n == 228, "program dump is 228 bytes (%d)", n);
    int m = syx_unpack(msg + 7, n - 8, back, 192);
    CHECK(m == 192 && !memcmp(prog, back, 192), "program dump round-trips");
    n = syx_write_program(prog, -1, 0, msg);
    CHECK(n == 226, "edit buffer dump is 226 bytes (%d)", n);

    /* waveshape dump: a 12-bit ramp lands in its slot */
    uint8_t wraw[256], wmsg[400];
    for (int i = 0; i < 128; i++) { int16_t v = (int16_t)((i - 64) * 32); wraw[2 * i] = (uint8_t)(v & 0xFF); wraw[2 * i + 1] = (uint8_t)((v >> 8) & 0xFF); }
    wmsg[0] = 99;
    int wn = 1 + syx_pack(wraw, 256, wmsg + 1);
    float w[PE_WLEN];
    int slot = waves_from_dump(wmsg, wn, w);
    CHECK(wn == 294 && slot == 99 && fabsf(w[0] + 1.0f) < 1e-6f && fabsf(w[127] - 0.984375f) < 1e-6f, "waveshape dump decodes (%d bytes, slot %d, %.4f..%.4f)", wn, slot, w[0], w[127]);

    /* a folder of .syx files: two banks of programs and a waveshape become banks and a user wave */
    {
        char dir[] = "/tmp/pe_test_XXXXXX";
        if (mkdtemp(dir)) {
            char path[256];
            snprintf(path, sizeof path, "%s/My Banks.syx", dir);
            FILE *fp = fopen(path, "wb");
            uint8_t pr[192];
            for (int i = 0; i < 192; i++) pr[i] = (uint8_t)PTAB[i].def;
            pr[22] = 66;   /* resonance */
            for (int bk = 0; bk < 2; bk++)
                for (int k = 0; k < 3; k++) {
                    uint8_t mm[300];
                    int l = syx_write_program(pr, bk, k, mm); fwrite(mm, 1, (size_t)l, fp);
                    char nm[17]; snprintf(nm, sizeof nm, "B%c P%c", (char)('1' + bk), (char)('1' + k));
                    l = syx_write_name(nm, bk, k, mm); fwrite(mm, 1, (size_t)l, fp);
                }
            uint8_t hdr[5] = {0xF0, 0x01, 0x20, 0x01, 0x0A}, end = 0xF7;
            fwrite(hdr, 1, 5, fp); fwrite(wmsg, 1, (size_t)wn, fp); fwrite(&end, 1, 1, fp);
            fclose(fp);
            void *h3 = E->create(dir);
            E->get_param(h3, "status", b, sizeof b);
            CHECK(!strcmp(b, "3 banks, user waves"), "folder scan finds two banks and a user wave (%s)", b);
            setp(h3, "bank", 2);
            E->get_param(h3, "bank_name", b, sizeof b);
            CHECK(!strcmp(b, "My Banks B2"), "bank name from the file (%s)", b);
            setp(h3, "program", 1);
            E->get_param(h3, "patch_name", b, sizeof b);
            char res[16]; E->get_param(h3, "lpf_res", res, sizeof res);
            CHECK(!strcmp(b, "B2 P2") && atoi(res) == 66, "program and name load from the bank (%s, res %s)", b, res);
            E->destroy(h3);
            remove(path);
            snprintf(path, sizeof path, "%s/SYSEX", dir); rmdir(path);
            rmdir(dir);
        }
    }

    E->destroy(h); E->destroy(h2);
    printf(fails ? "FAILED\n" : "PASSED\n");
    return fails;
}
