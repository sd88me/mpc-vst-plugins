// hwremap: LD_PRELOAD shim for MPC OS standalone that turns hardware buttons into
// button/pad sequences. It filters the controller's "Private" rawmidi input
// (buttons = note on/off on channel 1, pads = notes on channel 10).
//
// Config (re-read whenever its mtime changes): /sdcard/hwremap.conf
//   log 1                     log every input byte to /tmp/hwremap.log
//   hold 49                   while this button is held, remapped buttons pass through
//   held 1 u49 b1 d49         ...unless a "held" rule exists for them: run it instead
//   tap 1 d49 b1 u49          short press runs this on release; held past longms (default 400)
//                             the button itself goes through, down at the threshold, up on release
//   long 1 b1                 ...or this runs at the threshold instead
//   dbl 1 h1                  with a tap rule: a second press within dblms runs this (the tap
//                             waits out the window); hN holds N down while the button is held,
//                             at least holdms (default 800)
//   54 d123 p49 u123          on press of note 54: Menu down, tap pad note 49, Menu up
//   54 mClip_Matrix           Menu + the pad under that mode in the Mode Menu grid
//   dbl 55 b116               second press within dblms (default 350) runs this instead;
//                             without a single rule the first press passes through
//   dblms 350
//   dbl 2 t331,655            tap the touchscreen at x,y (raw touch units), touchms later
//   touchms 150
// Tokens: dN button down, uN button up, bN button tap, pN pad tap, xHH raw byte, tX,Y touch, hN hold,
// mName (underscores = spaces; looked up in MPC.settings at press time, used alone).
// N is decimal or 0x hex. The source button's release is swallowed.

#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

typedef struct _snd_rawmidi snd_rawmidi_t;
typedef struct _snd_rawmidi_info snd_rawmidi_info_t;

#ifndef CONF_PATH
#define CONF_PATH "/sdcard/hwremap.conf"
#endif
#ifndef LOG_PATH
#define LOG_PATH "/tmp/hwremap.log"
#endif
#ifndef SETTINGS_PATH
#define SETTINGS_PATH "/media/az01-internal/Settings/MPC/MPC.settings"
#endif
#ifndef TOUCH_PATH
#define TOUCH_PATH "/dev/input/event0"
#endif
#define MENU_NOTE 123
#define MENU_GRID_PAGE "ModeMenuPage1Slot"
#define MODE_NAME_MAX 48
#define LOG_MAX (256 * 1024)
#define MAX_SEQ 64
#define QSIZE 4096

static int (*real_open)(snd_rawmidi_t **, snd_rawmidi_t **, const char *, int);
static ssize_t (*real_read)(snd_rawmidi_t *, void *, size_t);

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static snd_rawmidi_t *priv_in;

struct action {
    unsigned char seq[MAX_SEQ];
    int len;
    char mode[MODE_NAME_MAX];
    int touch, tx, ty;
    int keep; // button + 1 held down while the source button is held
};

static struct action single[128], dbl[128], shifted[128], tapped[128], longp[128];
static int long_ms = 400, hold_ms = 800;
static int tap_pending[128], long_active[128], tap_wait[128];
static int keep_out[128], keep_up_btn[128];
static long long keep_start[128];
static unsigned press_seq[128];
static int priv_fd = -1;
static int wake_fd[2] = {-1, -1};
static long long last_press[128];
static int dbl_ms = 350;
static int touch_ms = 150;

// pad note for each Mode Menu grid slot: slot 0 is top left (pad 13), rows go down
static const unsigned char slot_pad[16] = {
    0x31, 0x37, 0x33, 0x35, // pads 13-16
    0x30, 0x2F, 0x2D, 0x2B, // pads 9-12
    0x28, 0x26, 0x2E, 0x2C, // pads 5-8
    0x25, 0x24, 0x2A, 0x52, // pads 1-4
};

static char grid[16][MODE_NAME_MAX];
static time_t settings_mtime = -1;
static long settings_mtime_ns = -1;
static int hold_note = -1;
#define MAX_COMBO 32
static struct {
    int hold, src;
    struct action a;
} combo[MAX_COMBO];
static int ncombo;
static int log_on;
static time_t conf_mtime = -1;
static long conf_mtime_ns = -1;

static int held[128];
static int swallow_release[128];

static unsigned char q[QSIZE];
static int qhead, qtail;

static unsigned char msg[3];
static int msg_len, msg_need, in_sysex;

static void logf_(const char *fmt, ...)
{
    if (!log_on)
        return;
    struct stat st;
    if (stat(LOG_PATH, &st) == 0 && st.st_size > LOG_MAX)
        rename(LOG_PATH, LOG_PATH ".1");
    FILE *f = fopen(LOG_PATH, "a");
    if (!f)
        return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fclose(f);
}

static void push(unsigned char b)
{
    int next = (qtail + 1) % QSIZE;
    if (next == qhead)
        return;
    q[qtail] = b;
    qtail = next;
}

static int add_tok(struct action *a, const char *tok)
{
    unsigned char *p = a->seq + a->len;
    int room = MAX_SEQ - a->len;
    char kind = tok[0];
    if (kind == 'm') {
        snprintf(a->mode, MODE_NAME_MAX, "%s", tok + 1);
        for (char *c = a->mode; *c; c++)
            if (*c == '_')
                *c = ' ';
        return a->mode[0] ? 0 : -1;
    }
    if (kind == 't') {
        char *end;
        long x = strtol(tok + 1, &end, 0);
        if (*end != ',')
            return -1;
        long y = strtol(end + 1, &end, 0);
        if (*end || x < 0 || y < 0 || x > 65535 || y > 65535)
            return -1;
        a->touch = 1;
        a->tx = (int)x;
        a->ty = (int)y;
        return 0;
    }
    long v = strtol(tok + 1, NULL, kind == 'x' ? 16 : 0);
    if (v < 0 || v > (kind == 'x' ? 255 : 127))
        return -1;
    if (kind == 'h') {
        a->keep = (int)v + 1;
        return 0;
    }
    int n = 0;
    unsigned char b[6];
    switch (kind) {
    case 'd': b[0] = 0x90; b[1] = v; b[2] = 0x7f; n = 3; break;
    case 'u': b[0] = 0x90; b[1] = v; b[2] = 0x00; n = 3; break;
    case 'b': b[0] = 0x90; b[1] = v; b[2] = 0x7f; b[3] = 0x90; b[4] = v; b[5] = 0x00; n = 6; break;
    case 'p': b[0] = 0x99; b[1] = v; b[2] = 0x7f; b[3] = 0x99; b[4] = v; b[5] = 0x00; n = 6; break;
    case 'x': b[0] = v; n = 1; break;
    default: return -1;
    }
    if (n > room)
        return -1;
    memcpy(p, b, n);
    a->len += n;
    return 0;
}

static void reset_conf(void)
{
    memset(single, 0, sizeof single);
    memset(dbl, 0, sizeof dbl);
    memset(shifted, 0, sizeof shifted);
    memset(tapped, 0, sizeof tapped);
    memset(longp, 0, sizeof longp);
    long_ms = 400;
    hold_ms = 800;
    hold_note = -1;
    ncombo = 0;
    log_on = 0;
    dbl_ms = 350;
    touch_ms = 150;
}

static void load_conf(void)
{
    struct stat st;
    if (stat(CONF_PATH, &st) != 0) {
        if (conf_mtime != 0) {
            reset_conf();
            conf_mtime = 0;
        }
        return;
    }
    if (st.st_mtim.tv_sec == conf_mtime && st.st_mtim.tv_nsec == conf_mtime_ns)
        return;
    conf_mtime = st.st_mtim.tv_sec;
    conf_mtime_ns = st.st_mtim.tv_nsec;

    FILE *f = fopen(CONF_PATH, "r");
    if (!f)
        return;
    reset_conf();
    char line[512];
    while (fgets(line, sizeof line, f)) {
        char *hash = strchr(line, '#');
        if (hash)
            *hash = 0;
        char *save = NULL;
        char *w = strtok_r(line, " \t\r\n", &save);
        if (!w)
            continue;
        if (!strcmp(w, "log")) {
            char *v = strtok_r(NULL, " \t\r\n", &save);
            log_on = v && atoi(v);
            continue;
        }
        if (!strcmp(w, "hold")) {
            char *v = strtok_r(NULL, " \t\r\n", &save);
            hold_note = v ? (int)strtol(v, NULL, 0) : -1;
            continue;
        }
        if (!strcmp(w, "dblms")) {
            char *v = strtok_r(NULL, " \t\r\n", &save);
            dbl_ms = v ? atoi(v) : 350;
            continue;
        }
        if (!strcmp(w, "touchms")) {
            char *v = strtok_r(NULL, " \t\r\n", &save);
            touch_ms = v ? atoi(v) : 150;
            continue;
        }
        if (!strcmp(w, "longms")) {
            char *v = strtok_r(NULL, " \t\r\n", &save);
            long_ms = v ? atoi(v) : 400;
            continue;
        }
        if (!strcmp(w, "holdms")) {
            char *v = strtok_r(NULL, " \t\r\n", &save);
            hold_ms = v ? atoi(v) : 800;
            continue;
        }
        if (!strcmp(w, "combo")) {
            // combo HOLD SRC tokens: while button HOLD is held, pressing SRC runs the tokens
            char *h = strtok_r(NULL, " \t\r\n", &save);
            char *n = strtok_r(NULL, " \t\r\n", &save);
            long hb = h ? strtol(h, NULL, 0) : -1, sb = n ? strtol(n, NULL, 0) : -1;
            if (hb < 0 || hb > 127 || sb < 0 || sb > 127 || ncombo >= MAX_COMBO)
                continue;
            memset(&combo[ncombo], 0, sizeof combo[ncombo]);
            combo[ncombo].hold = (int)hb;
            combo[ncombo].src = (int)sb;
            for (char *t = strtok_r(NULL, " \t\r\n", &save); t; t = strtok_r(NULL, " \t\r\n", &save)) {
                if (add_tok(&combo[ncombo].a, t) != 0) {
                    logf_("bad token '%s' for combo %ld %ld\n", t, hb, sb);
                    break;
                }
            }
            ncombo++;
            continue;
        }
        struct action *table = single;
        if (!strcmp(w, "dbl") || !strcmp(w, "held") || !strcmp(w, "tap") || !strcmp(w, "long")) {
            table = w[0] == 'd' ? dbl : w[0] == 'h' ? shifted : w[0] == 't' ? tapped : longp;
            w = strtok_r(NULL, " \t\r\n", &save);
            if (!w)
                continue;
        }
        long src = strtol(w, NULL, 0);
        if (src < 0 || src > 127)
            continue;
        struct action *a = &table[src];
        memset(a, 0, sizeof *a);
        for (char *t = strtok_r(NULL, " \t\r\n", &save); t; t = strtok_r(NULL, " \t\r\n", &save)) {
            if (add_tok(a, t) != 0) {
                logf_("bad token '%s' for %ld\n", t, src);
                break;
            }
        }
    }
    fclose(f);
    logf_("config loaded\n");
}

static void load_grid(void)
{
    struct stat st;
    if (stat(SETTINGS_PATH, &st) != 0)
        return;
    if (st.st_mtim.tv_sec == settings_mtime && st.st_mtim.tv_nsec == settings_mtime_ns)
        return;
    FILE *f = fopen(SETTINGS_PATH, "r");
    if (!f)
        return;
    char *buf = malloc((size_t)st.st_size + 1);
    size_t n = buf ? fread(buf, 1, (size_t)st.st_size, f) : 0;
    fclose(f);
    if (!buf)
        return;
    buf[n] = 0;
    settings_mtime = st.st_mtim.tv_sec;
    settings_mtime_ns = st.st_mtim.tv_nsec;
    memset(grid, 0, sizeof grid);
    static const char key[] = "<VALUE name=\"" MENU_GRID_PAGE;
    for (char *k = strstr(buf, key); k; k = strstr(k + 1, key)) {
        char *end;
        long slot = strtol(k + sizeof key - 1, &end, 10);
        if (slot < 0 || slot >= 16 || strncmp(end, "\" val=\"", 7))
            continue;
        char *v = end + 7;
        char *q2 = strchr(v, '"');
        if (!q2)
            continue;
        int len = (int)(q2 - v) < MODE_NAME_MAX - 1 ? (int)(q2 - v) : MODE_NAME_MAX - 1;
        memcpy(grid[slot], v, len);
        grid[slot][len] = 0;
    }
    free(buf);
    logf_("menu grid loaded\n");
}

static int push_mode(const char *name)
{
    load_grid();
    for (int slot = 0; slot < 16; slot++) {
        if (strcmp(grid[slot], name))
            continue;
        unsigned char pad = slot_pad[slot];
        const unsigned char s[] = {0x90, MENU_NOTE, 0x7f, 0x99, pad, 0x7f, 0x99, pad, 0x00, 0x90, MENU_NOTE, 0x00};
        for (size_t i = 0; i < sizeof s; i++)
            push(s[i]);
        logf_("mode '%s' -> slot %d\n", name, slot);
        return 1;
    }
    logf_("mode '%s' not in the menu grid\n", name);
    return 0;
}

// struct input_event with the kernel's native-long time fields
struct ev {
    unsigned long sec, usec;
    unsigned short type, code;
    int value;
};

struct tap {
    int x, y, delay_ms;
};

static void *tap_thread(void *arg)
{
    struct tap t = *(struct tap *)arg;
    free(arg);
    struct timespec d = {t.delay_ms / 1000, (long)(t.delay_ms % 1000) * 1000000};
    nanosleep(&d, NULL);
    int fd = open(TOUCH_PATH, O_WRONLY);
    if (fd < 0) {
        logf_("touch open failed\n");
        return NULL;
    }
    static int tracking_id = 30000;
    const struct ev down[] = {
        {0, 0, 3, 0x39, tracking_id++ & 0xffff}, // ABS_MT_TRACKING_ID
        {0, 0, 3, 0x35, t.x},                   // ABS_MT_POSITION_X
        {0, 0, 3, 0x36, t.y},                   // ABS_MT_POSITION_Y
        {0, 0, 1, 0x14a, 1},                    // BTN_TOUCH
        {0, 0, 3, 0x00, t.x},                   // ABS_X
        {0, 0, 3, 0x01, t.y},                   // ABS_Y
        {0, 0, 0, 0, 0},                        // SYN_REPORT
    };
    const struct ev up[] = {
        {0, 0, 3, 0x39, -1},
        {0, 0, 1, 0x14a, 0},
        {0, 0, 0, 0, 0},
    };
    ssize_t w = write(fd, down, sizeof down);
    struct timespec hold = {0, 40 * 1000000};
    nanosleep(&hold, NULL);
    w += write(fd, up, sizeof up);
    close(fd);
    logf_("touch %d,%d (%zd bytes)\n", t.x, t.y, w);
    return NULL;
}

static void start_tap(int x, int y)
{
    struct tap *t = malloc(sizeof *t);
    if (!t)
        return;
    t->x = x;
    t->y = y;
    t->delay_ms = touch_ms;
    pthread_t th;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&th, &attr, tap_thread, t) != 0)
        free(t);
    pthread_attr_destroy(&attr);
}

static int mapped(const struct action *a)
{
    return a->len || a->mode[0] || a->touch || a->keep;
}

static int run_action(const struct action *a)
{
    if (a->mode[0] && !push_mode(a->mode))
        return 0;
    for (int i = 0; i < a->len; i++)
        push(a->seq[i]);
    if (a->touch)
        start_tap(a->tx, a->ty);
    return 1;
}

static long long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void wake_reader(void)
{
    if (wake_fd[1] >= 0) {
        char c = 1;
        ssize_t r = write(wake_fd[1], &c, 1);
        (void)r;
    }
}

static void push_btn(int note, int vel)
{
    push(0x90);
    push((unsigned char)note);
    push((unsigned char)vel);
}

enum { T_LONG, T_WAIT, T_KEEPUP };

struct timer {
    int note, kind, delay_ms;
    unsigned seq;
};

static void *timer_thread(void *arg)
{
    struct timer t = *(struct timer *)arg;
    free(arg);
    struct timespec d = {t.delay_ms / 1000, (long)(t.delay_ms % 1000) * 1000000};
    nanosleep(&d, NULL);
    pthread_mutex_lock(&lock);
    int n = t.note;
    if (t.kind == T_KEEPUP) {
        push_btn(keep_up_btn[n], 0);
        wake_reader();
    } else if (press_seq[n] == t.seq && t.kind == T_LONG && tap_pending[n]) {
        tap_pending[n] = 0;
        if (mapped(&longp[n])) {
            run_action(&longp[n]);
            swallow_release[n] = 1;
        } else {
            long_active[n] = 1;
            push_btn(n, 0x7f);
        }
        logf_("long press %d\n", n);
        wake_reader();
    } else if (press_seq[n] == t.seq && t.kind == T_WAIT && tap_wait[n]) {
        tap_wait[n] = 0;
        run_action(&tapped[n]);
        logf_("remap %d (tap)\n", n);
        wake_reader();
    }
    pthread_mutex_unlock(&lock);
    return NULL;
}

static void start_timer(int note, int kind, int delay_ms)
{
    struct timer *t = malloc(sizeof *t);
    if (!t)
        return;
    t->note = note;
    t->kind = kind;
    t->delay_ms = delay_ms;
    t->seq = kind == T_KEEPUP ? 0 : ++press_seq[note];
    pthread_t th;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&th, &attr, timer_thread, t) != 0)
        free(t);
    pthread_attr_destroy(&attr);
}

static void handle_msg(void)
{
    int st = msg[0] & 0xf0, ch = msg[0] & 0x0f;
    if (ch == 0 && (st == 0x90 || st == 0x80) && msg_len == 3) {
        int note = msg[1];
        int press = st == 0x90 && msg[2] > 0;
        load_conf();
        int holding = hold_note >= 0 && held[hold_note];
        if (!press && keep_out[note]) {
            int btn = keep_out[note] - 1;
            keep_out[note] = 0;
            long long left = hold_ms - (now_ms() - keep_start[note]);
            if (left > 0) {
                keep_up_btn[note] = btn;
                start_timer(note, T_KEEPUP, (int)left);
            } else {
                push_btn(btn, 0);
            }
            return;
        }
        if (!press && tap_pending[note]) {
            tap_pending[note] = 0;
            if (mapped(&dbl[note])) {
                tap_wait[note] = 1;
                start_timer(note, T_WAIT, dbl_ms);
            } else {
                run_action(&tapped[note]);
                logf_("remap %d (tap)\n", note);
            }
            return;
        }
        if (!press && long_active[note]) {
            long_active[note] = 0;
            push_btn(note, 0);
            return;
        }
        if (press) {
            int hit = 0;
            for (int i = 0; i < ncombo && !hit; i++)
                if (combo[i].src == note && held[combo[i].hold] && mapped(&combo[i].a)) {
                    run_action(&combo[i].a);
                    swallow_release[note] = 1;
                    logf_("remap %d (combo with %d)\n", note, combo[i].hold);
                    hit = 1;
                }
            if (hit)
                return;
        }
        if (press && !holding && mapped(&tapped[note])) {
            if (tap_wait[note]) {
                tap_wait[note] = 0;
                ++press_seq[note];
                run_action(&dbl[note]);
                if (dbl[note].keep) {
                    push_btn(dbl[note].keep - 1, 0x7f);
                    keep_out[note] = dbl[note].keep;
                    keep_start[note] = now_ms();
                } else {
                    swallow_release[note] = 1;
                }
                logf_("remap %d (double)\n", note);
                return;
            }
            tap_pending[note] = 1;
            start_timer(note, T_LONG, long_ms);
            return;
        }
        if (press && holding && mapped(&shifted[note])) {
            run_action(&shifted[note]);
            swallow_release[note] = 1;
            logf_("remap %d (hold)\n", note);
            return;
        }
        if (press && (mapped(&single[note]) || mapped(&dbl[note])) && !holding) {
            long long t = now_ms();
            const struct action *a = &single[note];
            if (mapped(&dbl[note]) && last_press[note] && t - last_press[note] <= dbl_ms) {
                a = &dbl[note];
                last_press[note] = 0;
            } else {
                last_press[note] = t;
            }
            if (mapped(a) && run_action(a)) {
                swallow_release[note] = 1;
                logf_("remap %d%s\n", note, a == &dbl[note] ? " (double)" : "");
                return;
            }
        }
        if (!press && swallow_release[note]) {
            swallow_release[note] = 0;
            return;
        }
        held[note] = press;
    }
    for (int i = 0; i < msg_len; i++)
        push(msg[i]);
}

static int data_len(unsigned char s)
{
    switch (s & 0xf0) {
    case 0xc0:
    case 0xd0:
        return 1;
    case 0xf0:
        return s == 0xf1 || s == 0xf3 ? 1 : s == 0xf2 ? 2 : 0;
    default:
        return 2;
    }
}

static void feed(unsigned char b)
{
    if (b >= 0xf8) {
        push(b);
        return;
    }
    if (b == 0xf0) {
        in_sysex = 1;
        msg[0] = 0;
        msg_len = 0;
        push(b);
        return;
    }
    if (in_sysex) {
        if (b == 0xf7 || !(b & 0x80)) {
            push(b);
            if (b == 0xf7)
                in_sysex = 0;
            return;
        }
        in_sysex = 0;
    }
    if (b & 0x80) {
        msg[0] = b;
        msg_len = 1;
        msg_need = data_len(b);
        if (msg_need == 0) {
            push(b);
            msg_len = 0;
        }
        return;
    }
    if (msg_len == 0) {
        if (msg[0] < 0x80 || msg[0] >= 0xf0) {
            push(b);
            return;
        }
        msg_len = 1;
    }
    msg[msg_len++] = b;
    if (msg_len == msg_need + 1) {
        handle_msg();
        msg_len = 0;
    }
}

static void init_syms(void)
{
    if (!real_open)
        real_open = dlsym(RTLD_NEXT, "snd_rawmidi_open");
    if (!real_read)
        real_read = dlsym(RTLD_NEXT, "snd_rawmidi_read");
}

static int is_private(snd_rawmidi_t *h, const char *name)
{
    size_t (*info_sizeof)(void) = dlsym(RTLD_DEFAULT, "snd_rawmidi_info_sizeof");
    int (*info)(snd_rawmidi_t *, snd_rawmidi_info_t *) = dlsym(RTLD_DEFAULT, "snd_rawmidi_info");
    const char *(*subname)(const snd_rawmidi_info_t *) =
        dlsym(RTLD_DEFAULT, "snd_rawmidi_info_get_subdevice_name");
    const char *(*devname)(const snd_rawmidi_info_t *) = dlsym(RTLD_DEFAULT, "snd_rawmidi_info_get_name");
    int found = 0;
    if (info_sizeof && info && subname && devname) {
        snd_rawmidi_info_t *ri = calloc(1, info_sizeof());
        if (ri && info(h, ri) == 0) {
            const char *sn = subname(ri), *dn = devname(ri);
            logf_("open %s: '%s' / '%s'\n", name ? name : "?", dn ? dn : "", sn ? sn : "");
            found = (sn && strstr(sn, "Private")) || (dn && strstr(dn, "Private"));
        }
        free(ri);
    }
    return found;
}

__attribute__((visibility("default"))) int snd_rawmidi_open(snd_rawmidi_t **in, snd_rawmidi_t **out,
                                                             const char *name, int mode)
{
    init_syms();
    int r = real_open(in, out, name, mode);
    if (r == 0 && in && *in) {
        pthread_mutex_lock(&lock);
        load_conf();
        if (is_private(*in, name)) {
            priv_in = *in;
            int (*pdesc)(snd_rawmidi_t *, struct pollfd *, unsigned int) =
                dlsym(RTLD_DEFAULT, "snd_rawmidi_poll_descriptors");
            struct pollfd pfd;
            priv_fd = pdesc && pdesc(*in, &pfd, 1) == 1 ? pfd.fd : -1;
            if (wake_fd[0] < 0 && pipe2(wake_fd, O_NONBLOCK | O_CLOEXEC) != 0)
                wake_fd[0] = wake_fd[1] = -1;
            memset(tap_pending, 0, sizeof tap_pending);
            memset(long_active, 0, sizeof long_active);
            memset(tap_wait, 0, sizeof tap_wait);
            memset(keep_out, 0, sizeof keep_out);
            logf_("private fd %d\n", priv_fd);
            qhead = qtail = 0;
            msg_len = 0;
            in_sysex = 0;
            memset(held, 0, sizeof held);
            memset(swallow_release, 0, sizeof swallow_release);
            logf_("hooked private input %p\n", (void *)priv_in);
        }
        pthread_mutex_unlock(&lock);
    }
    return r;
}

// The reader waits in poll() on the private fd; a long press fires from a timer, so poll also
// watches a wake pipe and reports the private fd readable while injected bytes are queued.
__attribute__((visibility("default"))) int poll(struct pollfd *fds, nfds_t nfds, int timeout)
{
    static int (*real_poll)(struct pollfd *, nfds_t, int);
    if (!real_poll)
        real_poll = dlsym(RTLD_NEXT, "poll");
    int idx = -1;
    if (priv_fd >= 0 && wake_fd[0] >= 0 && nfds < 16)
        for (nfds_t i = 0; i < nfds; i++)
            if (fds[i].fd == priv_fd && (fds[i].events & POLLIN))
                idx = (int)i;
    if (idx < 0)
        return real_poll(fds, nfds, timeout);

    pthread_mutex_lock(&lock);
    int queued = qhead != qtail;
    pthread_mutex_unlock(&lock);
    if (queued) {
        for (nfds_t i = 0; i < nfds; i++)
            fds[i].revents = 0;
        fds[idx].revents = POLLIN;
        return 1;
    }

    struct pollfd all[16];
    memcpy(all, fds, nfds * sizeof *fds);
    all[nfds].fd = wake_fd[0];
    all[nfds].events = POLLIN;
    all[nfds].revents = 0;
    int r = real_poll(all, nfds + 1, timeout);
    if (r < 0)
        return r;
    for (nfds_t i = 0; i < nfds; i++)
        fds[i].revents = all[i].revents;
    if (all[nfds].revents) {
        char drain[64];
        while (read(wake_fd[0], drain, sizeof drain) > 0)
            ;
        r--;
        if (!fds[idx].revents) {
            fds[idx].revents = POLLIN;
            r++;
        }
    }
    return r;
}

__attribute__((visibility("default"))) int __poll_chk(struct pollfd *fds, nfds_t nfds, int timeout, size_t len)
{
    (void)len;
    return poll(fds, nfds, timeout);
}

__attribute__((visibility("default"))) ssize_t snd_rawmidi_read(snd_rawmidi_t *h, void *buffer, size_t size)
{
    init_syms();
    if (h != priv_in || size == 0)
        return real_read(h, buffer, size);

    unsigned char *out = buffer;
    size_t n = 0;
    pthread_mutex_lock(&lock);
    while (n < size && qhead != qtail) {
        out[n++] = q[qhead];
        qhead = (qhead + 1) % QSIZE;
    }
    while (n == 0) {
        unsigned char tmp[256];
        size_t want = size < sizeof tmp ? size : sizeof tmp;
        pthread_mutex_unlock(&lock);
        ssize_t r = real_read(h, tmp, want);
        pthread_mutex_lock(&lock);
        if (r <= 0) {
            pthread_mutex_unlock(&lock);
            return r;
        }
        if (log_on) {
            char hex[3 * 256 + 1];
            for (ssize_t i = 0; i < r; i++)
                sprintf(hex + 3 * i, "%02X ", tmp[i]);
            logf_("in: %s\n", hex);
        }
        for (ssize_t i = 0; i < r; i++)
            feed(tmp[i]);
        while (n < size && qhead != qtail) {
            out[n++] = q[qhead];
            qhead = (qhead + 1) % QSIZE;
        }
    }
    pthread_mutex_unlock(&lock);
    return (ssize_t)n;
}
