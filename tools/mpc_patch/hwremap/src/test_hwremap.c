// Host test: feeds byte streams through hwremap's read hook with a fake rawmidi.
#define CONF_PATH "/tmp/hwremap_test.conf"
#define LOG_PATH "/tmp/hwremap_test.log"
#define SETTINGS_PATH "/tmp/hwremap_test.settings"
#define TOUCH_PATH "/tmp/hwremap_test.touch"
#include "hwremap.c"

#include <assert.h>
#include <errno.h>
#include <unistd.h>

static const unsigned char *src;
static size_t src_len, src_pos, chunk;

static ssize_t fake_read(snd_rawmidi_t *h, void *buf, size_t size)
{
    (void)h;
    if (src_pos >= src_len)
        return -EAGAIN;
    size_t n = src_len - src_pos;
    if (n > size)
        n = size;
    if (n > chunk)
        n = chunk;
    memcpy(buf, src + src_pos, n);
    src_pos += n;
    return (ssize_t)n;
}

static size_t run(const unsigned char *in, size_t len, size_t ch, size_t rdsize, unsigned char *out)
{
    src = in;
    src_len = len;
    src_pos = 0;
    chunk = ch;
    size_t n = 0;
    for (;;) {
        ssize_t r = snd_rawmidi_read(priv_in, out + n, rdsize);
        if (r <= 0)
            break;
        n += (size_t)r;
    }
    return n;
}

static void expect(const char *what, const unsigned char *in, size_t len, const unsigned char *want, size_t wlen)
{
    unsigned char out[1024];
    size_t chunks[] = {1, 2, 3, 7, 256};
    size_t rds[] = {1, 3, 1024};
    for (size_t c = 0; c < sizeof chunks / sizeof *chunks; c++)
        for (size_t r = 0; r < sizeof rds / sizeof *rds; r++) {
            memset(held, 0, sizeof held);
            memset(swallow_release, 0, sizeof swallow_release);
            memset(last_press, 0, sizeof last_press);
            size_t n = run(in, len, chunks[c], rds[r], out);
            if (n != wlen || memcmp(out, want, wlen)) {
                printf("FAIL %s (chunk %zu, read %zu): got", what, chunks[c], rds[r]);
                for (size_t i = 0; i < n; i++)
                    printf(" %02X", out[i]);
                printf("\n");
                exit(1);
            }
        }
    printf("ok %s\n", what);
}

int main(void)
{
    FILE *f = fopen(CONF_PATH, "w");
    fprintf(f, "# test\nhold 49\n54 d123 p0x31 u123\n55 b126\n");
    fclose(f);
    real_read = fake_read;
    priv_in = (snd_rawmidi_t *)0x1;

    const unsigned char plus[] = {0x90, 54, 0x7f, 0x90, 54, 0x00};
    const unsigned char plus_out[] = {0x90, 123, 0x7f, 0x99, 0x31, 0x7f, 0x99, 0x31, 0x00, 0x90, 123, 0x00};
    expect("plus -> menu+pad", plus, sizeof plus, plus_out, sizeof plus_out);

    const unsigned char minus[] = {0x90, 55, 0x7f, 0x80, 55, 0x00};
    const unsigned char minus_out[] = {0x90, 126, 0x7f, 0x90, 126, 0x00};
    expect("minus -> button tap", minus, sizeof minus, minus_out, sizeof minus_out);

    const unsigned char shifted[] = {0x90, 49, 0x7f, 0x90, 54, 0x7f, 0x90, 54, 0x00, 0x90, 49, 0x00};
    expect("shift held passes plus", shifted, sizeof shifted, shifted, sizeof shifted);

    const unsigned char running[] = {0x99, 0x25, 0x40, 0x25, 0x00, 0xb0, 0x10, 0x01, 0x10, 0x7f};
    const unsigned char running_out[] = {0x99, 0x25, 0x40, 0x99, 0x25, 0x00, 0xb0, 0x10, 0x01, 0xb0, 0x10, 0x7f};
    expect("running status expanded", running, sizeof running, running_out, sizeof running_out);

    const unsigned char sx[] = {0xf0, 0x47, 0x7f, 0x3b, 0xf8, 0x01, 0xf7, 0x90, 54, 0x7f, 0x90, 54, 0x00};
    const unsigned char sx_out[] = {0xf0, 0x47, 0x7f, 0x3b, 0xf8, 0x01, 0xf7,
                                    0x90, 123, 0x7f, 0x99, 0x31, 0x7f, 0x99, 0x31, 0x00, 0x90, 123, 0x00};
    expect("sysex and realtime pass", sx, sizeof sx, sx_out, sizeof sx_out);

    const unsigned char other[] = {0x90, 56, 0x7f, 0x80, 56, 0x00, 0xa9, 0x25, 0x30};
    expect("other buttons untouched", other, sizeof other, other, sizeof other);

    f = fopen(SETTINGS_PATH, "w");
    fprintf(f, "<VALUE name=\"ModeMenuPage0Slot0\" val=\"Clip Matrix\"/>  <VALUE name=\"ModeMenuPage1Slot0\" val=\"XYFX\"/>"
               "<VALUE name=\"ModeMenuPage1Slot15\" val=\"Clip Matrix\"/><VALUE name=\"ModeMenuPage1Slot16\" val=\"Song\"/>\r\n");
    fclose(f);
    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "54 mClip_Matrix\n55 mSong\n");
    fclose(f);
    const unsigned char cm_out[] = {0x90, 123, 0x7f, 0x99, 0x52, 0x7f, 0x99, 0x52, 0x00, 0x90, 123, 0x00};
    expect("mode lookup -> menu + pad 4", plus, sizeof plus, cm_out, sizeof cm_out);
    const unsigned char minus_pass[] = {0x90, 55, 0x7f, 0x80, 55, 0x00};
    expect("mode outside grid passes through", minus_pass, sizeof minus_pass, minus_pass, sizeof minus_pass);
    remove(SETTINGS_PATH);

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "dblms 100\n55 b126\ndbl 55 b116\n");
    fclose(f);
    const unsigned char two[] = {0x90, 55, 0x7f, 0x90, 55, 0x00, 0x90, 55, 0x7f, 0x90, 55, 0x00};
    const unsigned char two_out[] = {0x90, 126, 0x7f, 0x90, 126, 0x00, 0x90, 116, 0x7f, 0x90, 116, 0x00};
    expect("double tap -> second action", two, sizeof two, two_out, sizeof two_out);
    const unsigned char three[] = {0x90, 55, 0x7f, 0x90, 55, 0x00, 0x90, 55, 0x7f, 0x90, 55, 0x00,
                                   0x90, 55, 0x7f, 0x90, 55, 0x00};
    const unsigned char three_out[] = {0x90, 126, 0x7f, 0x90, 126, 0x00, 0x90, 116, 0x7f, 0x90, 116, 0x00,
                                       0x90, 126, 0x7f, 0x90, 126, 0x00};
    expect("third tap starts over", three, sizeof three, three_out, sizeof three_out);
    {
        unsigned char out[64];
        memset(last_press, 0, sizeof last_press);
        size_t n = run(minus, sizeof minus, 256, 1024, out);
        usleep(150000);
        n += run(minus, sizeof minus, 256, 1024, out + n);
        const unsigned char slow_out[] = {0x90, 126, 0x7f, 0x90, 126, 0x00, 0x90, 126, 0x7f, 0x90, 126, 0x00};
        if (n != sizeof slow_out || memcmp(out, slow_out, n)) {
            printf("FAIL slow taps\n");
            return 1;
        }
        printf("ok slow taps stay single\n");
    }

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "dbl 11 b5\n");
    fclose(f);
    const unsigned char mix2[] = {0x90, 11, 0x7f, 0x90, 11, 0x00, 0x90, 11, 0x7f, 0x90, 11, 0x00};
    const unsigned char mix2_out[] = {0x90, 11, 0x7f, 0x90, 11, 0x00, 0x90, 5, 0x7f, 0x90, 5, 0x00};
    expect("double only: first press passes", mix2, sizeof mix2, mix2_out, sizeof mix2_out);

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "combo 10 20 b99\ncombo 11 20 b98\n");
    fclose(f);
    const unsigned char cmb_a[] = {0x90, 10, 0x7f, 0x90, 20, 0x7f, 0x90, 20, 0x00, 0x90, 10, 0x00};
    const unsigned char cmb_a_out[] = {0x90, 10, 0x7f, 0x90, 99, 0x7f, 0x90, 99, 0x00, 0x90, 10, 0x00};
    expect("combo: second hold button, first rule", cmb_a, sizeof cmb_a, cmb_a_out, sizeof cmb_a_out);
    const unsigned char cmb_b[] = {0x90, 11, 0x7f, 0x90, 20, 0x7f, 0x90, 20, 0x00, 0x90, 11, 0x00};
    const unsigned char cmb_b_out[] = {0x90, 11, 0x7f, 0x90, 98, 0x7f, 0x90, 98, 0x00, 0x90, 11, 0x00};
    expect("combo: same button, other hold button", cmb_b, sizeof cmb_b, cmb_b_out, sizeof cmb_b_out);
    const unsigned char cmb_n[] = {0x90, 20, 0x7f, 0x90, 20, 0x00};
    expect("combo: no hold button passes", cmb_n, sizeof cmb_n, cmb_n, sizeof cmb_n);

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "hold 49\n1 d49 b1 u49\nheld 1 u49 b1 d49\n");
    fclose(f);
    const unsigned char knobs[] = {0x90, 1, 0x7f, 0x90, 1, 0x00};
    const unsigned char knobs_out[] = {0x90, 49, 0x7f, 0x90, 1, 0x7f, 0x90, 1, 0x00, 0x90, 49, 0x00};
    expect("knobs -> shift+knobs", knobs, sizeof knobs, knobs_out, sizeof knobs_out);
    const unsigned char sknobs[] = {0x90, 49, 0x7f, 0x90, 1, 0x7f, 0x90, 1, 0x00, 0x90, 49, 0x00};
    const unsigned char sknobs_out[] = {0x90, 49, 0x7f, 0x90, 49, 0x00, 0x90, 1, 0x7f, 0x90, 1, 0x00,
                                        0x90, 49, 0x7f, 0x90, 49, 0x00};
    expect("shift+knobs -> knobs", sknobs, sizeof sknobs, sknobs_out, sizeof sknobs_out);

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "hold 49\nlongms 100\ntap 1 d49 b1 u49\nheld 1 u49 b1 d49\n");
    fclose(f);
    expect("short knobs -> shift+knobs on release", knobs, sizeof knobs, knobs_out, sizeof knobs_out);
    expect("tap rule: shift+knobs -> knobs", sknobs, sizeof sknobs, sknobs_out, sizeof sknobs_out);
    {
        const unsigned char down[] = {0x90, 1, 0x7f}, up[] = {0x90, 1, 0x00};
        unsigned char out[64];
        size_t n = run(down, sizeof down, 256, 1024, out);
        usleep(200000);
        n += run(NULL, 0, 256, 1024, out + n);
        n += run(up, sizeof up, 256, 1024, out + n);
        const unsigned char want[] = {0x90, 1, 0x7f, 0x90, 1, 0x00};
        if (n != sizeof want || memcmp(out, want, n)) {
            printf("FAIL long knobs (n=%zu)\n", n);
            return 1;
        }
        printf("ok long knobs passes through\n");

        int quiet[2];
        assert(pipe(quiet) == 0);
        assert(pipe2(wake_fd, O_NONBLOCK) == 0);
        priv_fd = quiet[0];
        n = run(down, sizeof down, 256, 1024, out);
        long long t0 = now_ms();
        struct pollfd pfd = {quiet[0], POLLIN, 0};
        int r = poll(&pfd, 1, 2000);
        long long dt = now_ms() - t0;
        n += run(NULL, 0, 256, 1024, out + n);
        n += run(up, sizeof up, 256, 1024, out + n);
        if (r != 1 || !(pfd.revents & POLLIN) || dt > 500 || n != sizeof want || memcmp(out, want, n)) {
            printf("FAIL poll wake (r=%d dt=%lld n=%zu)\n", r, dt, n);
            return 1;
        }
        r = poll(&pfd, 1, 50);
        if (r != 0) {
            printf("FAIL poll idle (r=%d)\n", r);
            return 1;
        }
        printf("ok poll wakes on long press\n");
        priv_fd = -1;
    }

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "hold 49\nlongms 100\nholdms 200\ndblms 100\ntap 1 d49 b1 u49\nlong 1 b1\ndbl 1 h1\n");
    fclose(f);
    {
        const unsigned char down[] = {0x90, 1, 0x7f}, up[] = {0x90, 1, 0x00};
        const unsigned char tap2[] = {0x90, 1, 0x7f, 0x90, 1, 0x00};
        const unsigned char plain[] = {0x90, 1, 0x7f, 0x90, 1, 0x00};
        unsigned char out[64];

        size_t n = run(tap2, sizeof tap2, 256, 1024, out);
        size_t early = n;
        usleep(170000);
        n += run(NULL, 0, 256, 1024, out + n);
        if (early || n != sizeof knobs_out || memcmp(out, knobs_out, n)) {
            printf("FAIL short waits out double window (early=%zu n=%zu)\n", early, n);
            return 1;
        }
        printf("ok short waits out double window\n");

        n = run(down, sizeof down, 256, 1024, out);
        usleep(170000);
        n += run(NULL, 0, 256, 1024, out + n);
        n += run(up, sizeof up, 256, 1024, out + n);
        if (n != sizeof plain || memcmp(out, plain, n)) {
            printf("FAIL long -> plain tap (n=%zu)\n", n);
            return 1;
        }
        printf("ok long -> plain tap\n");

        n = run(tap2, sizeof tap2, 256, 1024, out);
        n += run(down, sizeof down, 256, 1024, out + n);
        n += run(up, sizeof up, 256, 1024, out + n);
        size_t before_up = n;
        usleep(300000);
        n += run(NULL, 0, 256, 1024, out + n);
        usleep(150000);
        n += run(NULL, 0, 256, 1024, out + n);
        if (before_up != 3 || n != sizeof plain || memcmp(out, plain, n)) {
            printf("FAIL double -> held knobs (before_up=%zu n=%zu)\n", before_up, n);
            return 1;
        }
        printf("ok double -> held knobs, min hold\n");
    }

    usleep(10000);
    f = fopen(CONF_PATH, "w");
    fprintf(f, "touchms 10\ndbl 2 t331,655\n");
    fclose(f);
    {
        const unsigned char menu2[] = {0x90, 2, 0x7f, 0x90, 2, 0x00, 0x90, 2, 0x7f, 0x90, 2, 0x00};
        const unsigned char menu2_out[] = {0x90, 2, 0x7f, 0x90, 2, 0x00};
        unsigned char out[64];
        fclose(fopen(TOUCH_PATH, "w"));
        memset(last_press, 0, sizeof last_press);
        size_t n = run(menu2, sizeof menu2, 256, 1024, out);
        usleep(200000);
        struct ev evs[10];
        FILE *tf = fopen(TOUCH_PATH, "rb");
        size_t ne = fread(evs, sizeof evs[0], 10, tf);
        fclose(tf);
        if (n != sizeof menu2_out || memcmp(out, menu2_out, n) || ne != 10 || evs[1].code != 0x35 ||
            evs[1].value != 331 || evs[2].value != 655 || evs[7].value != -1) {
            printf("FAIL double tap -> touch (n=%zu ne=%zu)\n", n, ne);
            return 1;
        }
        printf("ok double tap -> touch\n");
        remove(TOUCH_PATH);
    }

    remove(CONF_PATH);
    usleep(10000);
    expect("no config passes plus", plus, sizeof plus, plus, sizeof plus);
    return 0;
}
