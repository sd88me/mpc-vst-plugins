/* Maschine group instrument. Scans for .mxgrp files off the audio thread, loads the
 * one the user picks, and plays its pads. Chromatic C lines the bottom-left pad up
 * with MIDI 48 (note % 16). Notes 0–15 are the same sixteen pads. */
#include "engine.h"
#include "mxgrp.h"
#include "play.h"
#include <ctype.h>
#include <dirent.h>
#include <dlfcn.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

enum { MAX_KITS = 1023, PATH_N = 512, SR = 44100, KIT_ROWS = 8, BROW_ROWS = 8, DIR_CAP = 128 };
/* 1023 so a Q-Link step (1/128 of the range) is not a whole number of groups */

typedef struct {
    pthread_mutex_t mu;
    pthread_t thread;
    int thread_on;
    volatile int stop;

    char files[MAX_KITS][PATH_N];
    int nfiles;
    int scan_done;

    int kit_index;     /* 0 = none, else 1-based into files */
    int kit_scroll;    /* kit index of the first row in the on-screen list */
    int loaded;        /* index currently sounding, -1 if never applied */
    int need_load;
    char want[256];    /* basename to select once the scan publishes it */
    int level;         /* 0..100 */
    int fx;            /* 0/1 */
    int rev;
    char err[80];
    float bpm;
    int pat_sel;       /* 0 = the empty pattern, else 1-based into the group's patterns */
    int transport;     /* host play/stop */
    int preview;
    uint8_t grid[16][16]; /* loudest velocity in each pad/slice; 0 is empty */
    char pat_msg[80];

    char data_dir[PATH_N]; /* plugin groups folder, next to the .so */
    char root[PATH_N];     /* library the user picked; empty scans the usual places */
    char here[PATH_N];     /* folder open on SETUP; empty is the list of places */
    char loaded_name[256];
    int picking;
    unsigned block_n;
    unsigned browse_lock;  /* ignore Use folder until this block: same press must not close */
    int rescan;
    int scan_report;   /* Refresh was pressed: show Refreshing… / Found N */
    int nsamples;
    volatile int thread_done;
    int scan_depth;
    int brow_off;
    int ndirs;
    int up;                /* dirs[0] is the parent, drawn as .. */
    char dirs[DIR_CAP][PATH_N];

    PlayKit *kit;

    int beep;
    double beep_ph;

    void *seq;          /* ALSA sequencer, or NULL when the library is absent */
    int seq_port;
    void *seq_lib;
    int (*seq_out)(void *, void *);
    int echo_on[128];   /* notes we sent, waiting to come back and be ignored */
    int echo_off[128];
} State;

static int put(char *buf, int n, const char *s) {
    if (!buf || n <= 0) return 0;
    if (!s) s = "";
    snprintf(buf, (size_t)n, "%s", s);
    return (int)strlen(buf);
}

static void stem(const char *path, char *out, int n) {
    const char *b = strrchr(path, '/');
    b = b ? b + 1 : path;
    snprintf(out, (size_t)n, "%s", b);
    size_t L = strlen(out);
    if (L > 6 && !strcmp(out + L - 6, ".mxgrp")) out[L - 6] = 0;
}

static int cmp_path(const void *a, const void *b) { return strcmp(a, b); }

/* The same 28-byte event ALSA's snd_seq_event_t uses. Sent direct to whoever
 * subscribed, which on MPC is the track input it creates for this port. */
typedef struct {
    unsigned char client, port;
} seq_addr;
typedef struct {
    unsigned char type, flags, tag, queue;
    unsigned int time_tick;
    unsigned int time_pad;
    seq_addr source, dest;
    unsigned char data[12];
} seq_ev;
#if defined(__arm__)
_Static_assert(sizeof(seq_ev) == 28, "ALSA snd_seq_event_t is 28 bytes");
#endif

enum {
    SEQ_OPEN_OUTPUT = 1,
    SEQ_CAP_READ = 1 << 0,
    SEQ_CAP_SUBS_READ = 1 << 5,
    SEQ_TYPE_MIDI = 1 << 1,
    SEQ_TYPE_APP = 1 << 20,
    SEQ_ADDR_UNKNOWN = 253,
    SEQ_ADDR_SUBS = 254,
    SEQ_QUEUE_DIRECT = 253,
    SEQ_NOTEON = 6,
    SEQ_NOTEOFF = 7
};

static void seq_close(State *s) {
    if (s->seq && s->seq_lib) {
        int (*fn)(void *) = dlsym(s->seq_lib, "snd_seq_close");
        if (fn) fn(s->seq);
    }
    if (s->seq_lib) dlclose(s->seq_lib);
    s->seq = NULL;
    s->seq_lib = NULL;
    s->seq_out = NULL;
    s->seq_port = -1;
}

static void seq_open(State *s) {
    s->seq_port = -1;
    void *lib = dlopen("libasound.so.2", RTLD_NOW | RTLD_LOCAL);
    if (!lib) return;
    int (*open_fn)(void **, const char *, int, int) = dlsym(lib, "snd_seq_open");
    int (*name_fn)(void *, const char *) = dlsym(lib, "snd_seq_set_client_name");
    int (*port_fn)(void *, const char *, unsigned, unsigned) = dlsym(lib, "snd_seq_create_simple_port");
    int (*out_fn)(void *, void *) = dlsym(lib, "snd_seq_event_output_direct");
    if (!open_fn || !name_fn || !port_fn || !out_fn) { dlclose(lib); return; }
    void *seq = NULL;
    if (open_fn(&seq, "default", SEQ_OPEN_OUTPUT, 0) < 0 || !seq) { dlclose(lib); return; }
    name_fn(seq, "Maschine Group");
    int port = port_fn(seq, "MIDI Out", SEQ_CAP_READ | SEQ_CAP_SUBS_READ, SEQ_TYPE_MIDI | SEQ_TYPE_APP);
    if (port < 0) {
        int (*close_fn)(void *) = dlsym(lib, "snd_seq_close");
        if (close_fn) close_fn(seq);
        dlclose(lib);
        return;
    }
    s->seq_lib = lib;
    s->seq = seq;
    s->seq_port = port;
    s->seq_out = out_fn;
}

static void seq_send(State *s, int status, int note, int vel) {
    if (!s->seq || !s->seq_out || note < 0 || note > 127) return;
    seq_ev ev;
    memset(&ev, 0, sizeof ev);
    ev.queue = SEQ_QUEUE_DIRECT;
    ev.dest.client = SEQ_ADDR_SUBS;
    ev.dest.port = SEQ_ADDR_UNKNOWN;
    ev.source.port = (unsigned char)s->seq_port;
    int on = (status & 0xf0) == 0x90 && vel > 0;
    ev.type = (unsigned char)(on ? SEQ_NOTEON : SEQ_NOTEOFF);
    ev.data[0] = (unsigned char)(status & 0x0f);
    ev.data[1] = (unsigned char)note;
    ev.data[2] = (unsigned char)(on ? vel : 0);
    s->seq_out(s->seq, &ev);
}

static void send_preview_midi(State *s) {
    if (!s->kit) return;
    uint8_t ev[64][4];
    int n = play_midi_out(s->kit, ev, 64);
    for (int i = 0; i < n; i++) {
        int st = ev[i][1], note = ev[i][2], vel = ev[i][3];
        if (note < 0 || note > 127) continue;
        if ((st & 0xf0) == 0x90 && vel > 0) {
            if (s->echo_on[note] < 16) s->echo_on[note]++;
        } else if (s->echo_off[note] < 16) {
            s->echo_off[note]++;
        }
        seq_send(s, st, note, vel);
    }
}

static int swallow_echo(State *s, int status, int note, int vel) {
    if ((status & 0x0f) != 0 || note < 0 || note > 127) return 0;
    int st = status & 0xf0;
    if (st == 0x90 && vel > 0 && s->echo_on[note] > 0) { s->echo_on[note]--; return 1; }
    if ((st == 0x80 || (st == 0x90 && vel == 0)) && s->echo_off[note] > 0) { s->echo_off[note]--; return 1; }
    return 0;
}

static int is_sample_name(const char *name) {
    const char *dot = strrchr(name, '.');
    if (!dot || !dot[1]) return 0;
    return !strcasecmp(dot, ".wav") || !strcasecmp(dot, ".aif") || !strcasecmp(dot, ".aiff") ||
           !strcasecmp(dot, ".ncw") || !strcasecmp(dot, ".rex") || !strcasecmp(dot, ".rx2");
}

static void count_samples(State *s, int *nsamp, const char *dir, int depth) {
    if (s->stop || depth < 0 || !dir) return;
    DIR *d = opendir(dir);
    if (!d) return;
    struct dirent *de;
    while ((de = readdir(d)) && !s->stop) {
        if (de->d_name[0] == '.') continue;
        char path[PATH_N];
        int wr = snprintf(path, sizeof path, "%s/%s", dir, de->d_name);
        if (wr < 0 || wr >= (int)sizeof path) continue;
        struct stat st;
        if (lstat(path, &st) != 0 || S_ISLNK(st.st_mode)) continue;
        if (S_ISREG(st.st_mode)) {
            if (is_sample_name(de->d_name)) (*nsamp)++;
        } else if (S_ISDIR(st.st_mode)) {
            count_samples(s, nsamp, path, depth - 1);
        }
    }
    closedir(d);
}

static void walk(State *s, char (*paths)[PATH_N], int *n, int *nsamp, const char *dir, int depth) {
    if (s->stop || depth < 0 || *n >= MAX_KITS) return;
    DIR *d = opendir(dir);
    if (!d) return;
    struct dirent *de;
    while ((de = readdir(d)) && *n < MAX_KITS && !s->stop) {
        if (de->d_name[0] == '.') continue;
        if (!strcmp(de->d_name, "Documentation") || !strcmp(de->d_name, "PAResources"))
            continue;
        char path[PATH_N];
        int wr = snprintf(path, sizeof path, "%s/%s", dir, de->d_name);
        if (wr < 0 || wr >= (int)sizeof path) continue;
        struct stat st;
        if (lstat(path, &st) != 0 || S_ISLNK(st.st_mode)) continue;
        if (S_ISREG(st.st_mode)) {
            size_t L = strlen(de->d_name);
            if (L > 6 && !strcmp(de->d_name + L - 6, ".mxgrp")) {
                snprintf(paths[*n], PATH_N, "%s", path);
                (*n)++;
            }
        } else if (S_ISDIR(st.st_mode)) {
            if (!strcmp(de->d_name, "Samples") || !strcmp(de->d_name, "samples"))
                count_samples(s, nsamp, path, 8);
            else
                walk(s, paths, n, nsamp, path, depth - 1);
        }
    }
    closedir(d);
}

static void *scan_main(void *arg) {
    State *s = arg;
    char (*paths)[PATH_N] = malloc((size_t)MAX_KITS * PATH_N);
    if (!paths) {
        pthread_mutex_lock(&s->mu);
        s->scan_done = 1;
        s->thread_done = 1;
        s->rev++;
        pthread_mutex_unlock(&s->mu);
        return NULL;
    }
    int n = 0, nsamp = 0;
    /* create() parks the search roots in files[] and sets nfiles to that count.
     * Copy them out before the walk; the publish below replaces files[] with groups. */
    char roots_buf[6][PATH_N];
    int nroots = s->nfiles;
    if (nroots > 6) nroots = 6;
    for (int i = 0; i < nroots; i++) snprintf(roots_buf[i], PATH_N, "%s", s->files[i]);
    for (int i = 0; i < nroots; i++) walk(s, paths, &n, &nsamp, roots_buf[i], s->scan_depth);
    if (n > 1) qsort(paths, (size_t)n, PATH_N, cmp_path);
    /* drop duplicate paths */
    int w = 0;
    for (int i = 0; i < n; i++) {
        if (w && !strcmp(paths[w - 1], paths[i])) continue;
        if (w != i) memcpy(paths[w], paths[i], PATH_N);
        w++;
    }
    pthread_mutex_lock(&s->mu);
    if (!s->stop) {
        for (int i = 0; i < w; i++) memcpy(s->files[i], paths[i], PATH_N);
        s->nfiles = w;
        s->nsamples = nsamp;
        s->scan_done = 1;
        s->rev++;
    }
    s->thread_done = 1;
    pthread_mutex_unlock(&s->mu);
    free(paths);
    return NULL;
}

static int is_dir(const char *p) {
    struct stat st;
    return p && p[0] && stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}

static int ends_dir(const char *path, const char *name) {
    const char *b = strrchr(path, '/');
    b = b ? b + 1 : path;
    return strcasecmp(b, name) == 0;
}

static void copy_fit(const char *s, char *out, int n) {
    if (!s) s = "";
    if (n <= 1) { if (n == 1) out[0] = 0; return; }
    if ((int)strlen(s) < n) { snprintf(out, (size_t)n, "%s", s); return; }
    int keep = n - 4;
    if (keep < 1) keep = 1;
    snprintf(out, (size_t)n, "...%s", s + (int)strlen(s) - keep);
}

/* Groups and Samples live next to each other under one library folder. A group
 * file stores paths like Samples/Drums/Kick/Kick.wav. */
static void format_place(const char *root, char *out, int n) {
    if (!root || !root[0]) { copy_fit("", out, n); return; }
    char base[PATH_N], groups[PATH_N], samples[PATH_N];
    snprintf(base, sizeof base, "%s", root);
    if (ends_dir(base, "Groups") || ends_dir(base, "groups")) {
        snprintf(groups, sizeof groups, "%s", base);
        char *sl = strrchr(base, '/');
        if (sl && sl != base) *sl = 0;
    } else {
        snprintf(groups, sizeof groups, "%s/Groups", base);
        if (!is_dir(groups)) snprintf(groups, sizeof groups, "%s/groups", base);
    }
    snprintf(samples, sizeof samples, "%s/Samples", base);
    if (!is_dir(samples)) snprintf(samples, sizeof samples, "%s/samples", base);
    int hg = is_dir(groups), hs = is_dir(samples);
    char line[PATH_N * 2];
    if (hg && hs) snprintf(line, sizeof line, "%s   ·   %s", groups, samples);
    else if (hg) snprintf(line, sizeof line, "%s", groups);
    else if (hs) snprintf(line, sizeof line, "%s", samples);
    else snprintf(line, sizeof line, "%s", root);
    if ((int)strlen(line) >= n && hg && hs) snprintf(line, sizeof line, "%s", base[0] ? base : root);
    copy_fit(line, out, n);
}

/* The library is the folder that contains Groups/. */
static int library_of(const char *file, char *out, int n) {
    char dir[PATH_N];
    snprintf(dir, sizeof dir, "%s", file);
    for (int up = 0; up < 8; up++) {
        char *sl = strrchr(dir, '/');
        if (!sl || sl == dir) break;
        if (ends_dir(sl + 1, "Groups") || ends_dir(sl + 1, "groups")) {
            *sl = 0;
            snprintf(out, (size_t)n, "%s", dir);
            return 1;
        }
        *sl = 0;
    }
    return 0;
}

static void place_text(State *s, char *buf, int n) {
    if (s->picking) {
        if (!s->here[0]) copy_fit("choose a folder", buf, n);
        else format_place(s->here, buf, n);
        return;
    }
    if (s->root[0]) { format_place(s->root, buf, n); return; }
    if (!s->scan_done) { copy_fit("scanning…", buf, n); return; }
    if (s->nfiles <= 0) {
        if (s->data_dir[0]) format_place(s->data_dir, buf, n);
        else copy_fit("no groups", buf, n);
        return;
    }
    int i = (s->loaded > 0 && s->loaded <= s->nfiles) ? s->loaded - 1 : 0;
    char lib[PATH_N];
    if (library_of(s->files[i], lib, sizeof lib)) format_place(lib, buf, n);
    else {
        snprintf(lib, sizeof lib, "%s", s->files[i]);
        char *sl = strrchr(lib, '/');
        if (sl && sl != lib) *sl = 0;
        format_place(lib, buf, n);
    }
}

static void add_place(State *s, const char *p) {
    if (!is_dir(p) || s->ndirs >= DIR_CAP) return;
    for (int i = 0; i < s->ndirs; i++)
        if (!strcmp(s->dirs[i], p)) return;
    snprintf(s->dirs[s->ndirs], PATH_N, "%s", p);
    s->ndirs++;
}

static void fill_dirs(State *s) {
    s->ndirs = 0;
    s->up = 0;
    if (!s->here[0]) {
        add_place(s, s->data_dir);
        add_place(s, "/sdcard");
        add_place(s, "/media");
        DIR *d = opendir("/media");
        if (d) {
            struct dirent *de;
            while ((de = readdir(d)) && s->ndirs < DIR_CAP) {
                if (de->d_name[0] == '.') continue;
                char p[PATH_N];
                int wr = snprintf(p, sizeof p, "/media/%s", de->d_name);
                if (wr > 0 && wr < (int)sizeof p) add_place(s, p);
            }
            closedir(d);
        }
        add_place(s, "/Users/Shared");
        return;
    }
    s->up = 1;
    char parent[PATH_N];
    snprintf(parent, sizeof parent, "%s", s->here);
    char *sl = strrchr(parent, '/');
    if (!sl || sl == parent) parent[0] = 0;
    else *sl = 0;
    snprintf(s->dirs[0], PATH_N, "%s", parent);
    s->ndirs = 1;
    DIR *d = opendir(s->here);
    if (d) {
        struct dirent *de;
        while ((de = readdir(d)) && s->ndirs < DIR_CAP) {
            if (de->d_name[0] == '.') continue;
            char p[PATH_N];
            int wr = snprintf(p, sizeof p, "%s/%s", s->here, de->d_name);
            if (wr < 0 || wr >= (int)sizeof p) continue;
            if (is_dir(p)) {
                snprintf(s->dirs[s->ndirs], PATH_N, "%s", p);
                s->ndirs++;
            }
        }
        closedir(d);
    }
    if (s->ndirs > 2) qsort(s->dirs + 1, (size_t)(s->ndirs - 1), PATH_N, cmp_path);
}

/* kind: 0 blank, 1 back, 2 more, 3 dirs[idx] */
static void brow_slot(const State *s, int row, int *kind, int *idx, int *step) {
    *kind = 0;
    *idx = -1;
    *step = 0;
    if (!s->picking || row < 1 || row > BROW_ROWS) return;
    int back = s->brow_off > 0;
    int slots = BROW_ROWS - (back ? 1 : 0);
    int left = s->ndirs - s->brow_off;
    int more = left > slots;
    if (more) slots--;
    *step = slots > 0 ? slots : 1;
    if (back && row == 1) { *kind = 1; return; }
    if (more && row == BROW_ROWS) { *kind = 2; return; }
    int e = row - (back ? 2 : 1);
    if (e >= 0 && e < slots) {
        int i = s->brow_off + e;
        if (i >= 0 && i < s->ndirs) { *kind = 3; *idx = i; }
    }
}

static void enter_dir(State *s, const char *path) {
    if (!path || !path[0]) s->here[0] = 0;
    else snprintf(s->here, PATH_N, "%s", path);
    s->brow_off = 0;
    fill_dirs(s);
    s->rev++;
}

static void open_browser(State *s) {
    s->picking = 1;
    if (s->root[0] && is_dir(s->root)) snprintf(s->here, PATH_N, "%s", s->root);
    else if (s->scan_done && s->nfiles > 0) {
        int i = (s->loaded > 0 && s->loaded <= s->nfiles) ? s->loaded - 1 : 0;
        char lib[PATH_N];
        if (library_of(s->files[i], lib, sizeof lib)) snprintf(s->here, PATH_N, "%s", lib);
        else s->here[0] = 0;
    } else s->here[0] = 0;
    s->brow_off = 0;
    fill_dirs(s);
    /* Use folder sits in the same slot. Ignore it until this press is over. */
    s->browse_lock = s->block_n + 120;
    s->rev++;
}

static void commit_folder(State *s) {
    if (!s->here[0]) { /* still on the places list: leave without changing the folder */
        s->picking = 0;
        s->rev++;
        return;
    }
    if (strcmp(s->root, s->here) != 0) {
        snprintf(s->root, PATH_N, "%s", s->here);
        if (!s->want[0] && s->loaded_name[0])
            snprintf(s->want, sizeof s->want, "%s", s->loaded_name);
        s->loaded = -1;
        s->need_load = 1;
        s->rescan = 1;
    }
    s->picking = 0;
    s->rev++;
}

static void park_roots(State *s) {
    const char *roots[6];
    int nr = 0;
    if (s->root[0]) roots[nr++] = s->root;
    else if (s->data_dir[0]) roots[nr++] = s->data_dir;
    for (int i = 0; i < nr; i++) snprintf(s->files[i], PATH_N, "%s", roots[i]);
    s->nfiles = nr;
    s->scan_done = 0;
    s->scan_depth = s->root[0] ? 8 : 6;
}

/* Join the finished walk off the lock, then start another. A walk still in
 * progress is asked to stop and joined on a later block, once it has exited. */
static void kick_scan(State *s) {
    if (!s->rescan) return;
    if (s->thread_on && !s->thread_done) {
        s->stop = 1;
        return;
    }
    s->rescan = 0;
    pthread_t th = s->thread;
    int join = s->thread_on;
    s->thread_on = 0;
    pthread_mutex_unlock(&s->mu);
    if (join) pthread_join(th, NULL);
    pthread_mutex_lock(&s->mu);
    s->stop = 0;
    s->thread_done = 0;
    if (!s->want[0] && s->loaded_name[0]) {
        snprintf(s->want, sizeof s->want, "%s", s->loaded_name);
        s->loaded = -1;
        s->need_load = 1;
    }
    park_roots(s);
    if (pthread_create(&s->thread, NULL, scan_main, s) == 0) s->thread_on = 1;
    else { s->nfiles = 0; s->scan_done = 1; s->thread_done = 1; }
    s->rev++;
}

/* Keep the selected group inside the eight visible rows. */
static void reveal_kit(State *s) {
    if (s->kit_index < s->kit_scroll) s->kit_scroll = s->kit_index;
    else if (s->kit_index >= s->kit_scroll + KIT_ROWS)
        s->kit_scroll = s->kit_index - (KIT_ROWS - 1);
    if (s->kit_scroll < 0) s->kit_scroll = 0;
    int listed = s->scan_done ? s->nfiles : 0;
    int lim = listed + 1 - KIT_ROWS;
    if (lim < 0) lim = 0;
    if (s->kit_scroll > lim) s->kit_scroll = lim;
}

static void follow_transport(State *s);
static void rebuild_grid(State *s);

static void service(State *s) {
    s->block_n++;
    kick_scan(s);
    if (s->want[0] && s->nfiles > 0 && s->scan_done) {
        for (int i = 0; i < s->nfiles; i++) {
            char name[256];
            stem(s->files[i], name, sizeof name);
            if (!strcmp(name, s->want)) {
                s->kit_index = i + 1;
                s->need_load = 1;
                break;
            }
        }
        s->want[0] = 0;
    }
    if (!s->need_load) return;
    s->need_load = 0;
    int idx = s->kit_index;
    if (idx < 0) idx = 0;
    if (s->scan_done && idx > s->nfiles) idx = s->nfiles;
    s->kit_index = idx;
    {
        int prev = s->kit_scroll;
        reveal_kit(s);
        if (s->kit_scroll != prev) s->rev++;
    }
    if (!s->scan_done && idx > 0) {
        /* the list isn't there yet; try again next block */
        s->need_load = 1;
        return;
    }
    if (idx == s->loaded) return;
    PlayKit *next = NULL;
    char path[PATH_N];
    path[0] = 0;
    s->err[0] = 0;
    if (idx > 0) {
        snprintf(path, sizeof path, "%s", s->files[idx - 1]);
        next = play_load(path);
        if (!next) snprintf(s->err, sizeof s->err, "couldn't open group");
    }
    int keep_pat = s->pat_sel > 0;
    play_free(s->kit);
    s->kit = next;
    s->loaded = idx;
    if (idx > 0 && next) stem(path, s->loaded_name, sizeof s->loaded_name);
    else if (idx == 0) s->loaded_name[0] = 0;
    /* Empty stays Empty. A real pattern follows the new group to its first one. */
    if (keep_pat && next && play_npat(next) > 0) s->pat_sel = 1;
    else s->pat_sel = 0;
    s->pat_msg[0] = 0;
    if (next) play_set_bpm(next, s->bpm);
    follow_transport(s);
    rebuild_grid(s);
    s->rev++;
}

/* The first list row is silence. The group's own patterns follow it. */
static void follow_transport(State *s) {
    if (!s->kit) return;
    if (s->transport && s->pat_sel > 0) play_preview(s->kit, s->pat_sel - 1, 1);
    else play_preview(s->kit, 0, 0);
}

static void rebuild_grid(State *s) {
    memset(s->grid, 0, sizeof s->grid);
    if (s->kit && s->pat_sel > 0) play_pat_levels(s->kit, s->pat_sel - 1, 16, s->grid);
}

static void *create(const char *data_dir) {
    State *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    pthread_mutex_init(&s->mu, NULL);
    s->level = 80;
    s->fx = 1;
    s->bpm = 120.f;
    s->pat_sel = 0;
    s->loaded = -1;
    s->kit_index = 0;
    if (data_dir && data_dir[0]) snprintf(s->data_dir, PATH_N, "%s", data_dir);
    park_roots(s);
    if (pthread_create(&s->thread, NULL, scan_main, s) == 0) s->thread_on = 1;
    else { s->nfiles = 0; s->scan_done = 1; s->thread_done = 1; }
    seq_open(s);
    return s;
}

static void destroy(void *inst) {
    State *s = inst;
    if (!s) return;
    s->stop = 1;
    if (s->thread_on) pthread_join(s->thread, NULL);
    play_free(s->kit);
    seq_close(s);
    pthread_mutex_destroy(&s->mu);
    free(s);
}

static void midi(void *inst, const uint8_t *msg, int len) {
    State *s = inst;
    if (len < 3) return;
    int st = msg[0] & 0xf0;
    int note = msg[1], vel = msg[2];
    pthread_mutex_lock(&s->mu);
    if (swallow_echo(s, msg[0], note, vel)) {
        pthread_mutex_unlock(&s->mu);
        return;
    }
    if (st == 0x90 && vel > 0) {
        if (s->kit) play_note(s->kit, note, vel);
        else { s->beep = SR / 8; s->beep_ph = 0; }
    } else if (st == 0x80 || st == 0x90) {
        if (s->kit) play_note(s->kit, note, 0);
    }
    pthread_mutex_unlock(&s->mu);
}

static int copy_bin(const char *cmd, const uint8_t *data, int n) {
    FILE *p = popen(cmd, "w");
    if (!p) return 0;
    if (n > 0) fwrite(data, 1, (size_t)n, p);
    return pclose(p) == 0;
}

/* GRID paste reads MPC's own event buffer, which a plugin cannot fill (no system
 * clipboard on the device). Write a standard MIDI file and hand that file to a
 * clipboard tool when one exists. */
static void copy_pattern(State *s) {
    uint8_t *mid = malloc(16384);
    if (!mid) return;
    int n = 0;
    int bpm = (int)(s->bpm + 0.5f);
    if (s->kit && s->pat_sel > 0) n = play_pattern_midi(s->kit, s->pat_sel - 1, bpm, mid, 16384);
    if (n <= 0) {
        snprintf(s->pat_msg, sizeof s->pat_msg, "no events");
        free(mid);
        return;
    }
    FILE *f = fopen("/tmp/maschine-pattern.mid", "wb");
    if (f) { fwrite(mid, 1, (size_t)n, f); fclose(f); }
    int clipped = 0;
    if (access("/usr/bin/wl-copy", F_OK) == 0 || access("/bin/wl-copy", F_OK) == 0)
        clipped = copy_bin("wl-copy -t audio/midi", mid, n);
    else if (access("/usr/bin/xclip", F_OK) == 0 || access("/bin/xclip", F_OK) == 0)
        clipped = copy_bin("xclip -selection clipboard -t audio/midi", mid, n);
    else if (access("/usr/bin/pbcopy", F_OK) == 0)
        clipped = copy_bin("pbcopy", mid, n);
    free(mid);
    if (clipped) snprintf(s->pat_msg, sizeof s->pat_msg, "copied MIDI");
    else snprintf(s->pat_msg, sizeof s->pat_msg, "MIDI file saved");
}

static void set_param(void *inst, const char *key, const char *val) {
    State *s = inst;
    if (!key || !val) return;
    pthread_mutex_lock(&s->mu);
    if (!strcmp(key, "kit")) {
        s->kit_index = atoi(val);
        if (s->kit_index < 0) s->kit_index = 0;
        s->need_load = 1;
    } else if (!strncmp(key, "krow_", 5) && !strstr(key, "_on")) {
        /* Only a tap that turns the row on. The off echo from the previous row must not unload. */
        if (atoi(val) > 0 && s->scan_done) {
            int n = atoi(key + 5);
            if (n >= 1 && n <= KIT_ROWS) {
                int idx = s->kit_scroll + n - 1;
                if (idx >= 0 && idx <= s->nfiles) {
                    s->kit_index = idx;
                    s->need_load = 1;
                }
            }
        }
    } else if (!strcmp(key, "level")) {
        s->level = atoi(val);
        if (s->level < 0) s->level = 0;
        if (s->level > 100) s->level = 100;
    } else if (!strcmp(key, "fx")) {
        s->fx = atoi(val) ? 1 : 0;
    } else if (!strncmp(key, "pad_", 4) && !strstr(key, "_on")) {
        /* The tile is a switch, so a second tap arrives as 0 while the sample is
         * still playing. Either value retriggers; a screen tap is not a note-off. */
        int n = atoi(key + 4);
        if (n >= 1 && n <= MX_PADS && s->kit)
            play_note(s->kit, n - 1, 110);
    } else if (!strcmp(key, "lfo_bpm")) {
        s->bpm = (float)atof(val);
        if (s->bpm < 20.f || s->bpm > 400.f) s->bpm = 120.f;
        if (s->kit) play_set_bpm(s->kit, s->bpm);
    } else if (!strncmp(key, "pat_", 4) && isdigit((unsigned char)key[4]) && !strstr(key, "_on")) {
        if (atoi(val) > 0) {
            int n = atoi(key + 4);
            if (n >= 1 && n <= MX_PATS) {
                s->pat_sel = n - 1;
                s->pat_msg[0] = 0;
                rebuild_grid(s);
                follow_transport(s);
                s->rev++;
            }
        }
    } else if (!strcmp(key, "transport")) {
        s->transport = atoi(val) ? 1 : 0;
        follow_transport(s);
    } else if (!strcmp(key, "pat_play")) {
        /* The on-screen button is gone. Play and stop are the host transport. */
    } else if (!strcmp(key, "pat_copy")) {
        if (atoi(val) > 0) copy_pattern(s);
    } else if (!strcmp(key, "root_pick")) {
        if (atoi(val) > 0 && !s->picking) open_browser(s);
    } else if (!strcmp(key, "root_use")) {
        if (atoi(val) > 0 && s->picking && s->block_n >= s->browse_lock)
            commit_folder(s);
    } else if (!strcmp(key, "root_refresh")) {
        if (atoi(val) > 0) {
            s->scan_report = 1;
            s->rescan = 1;
        }
    } else if (!strncmp(key, "frow_", 5) && !strstr(key, "_on")) {
        if (atoi(val) > 0) {
            int n = atoi(key + 5);
            int kind = 0, idx = -1, step = 1;
            brow_slot(s, n, &kind, &idx, &step);
            if (kind == 1) {
                s->brow_off -= step;
                if (s->brow_off < 0) s->brow_off = 0;
                s->rev++;
            } else if (kind == 2) {
                s->brow_off += step;
                s->rev++;
            } else if (kind == 3 && idx >= 0) {
                if (s->up && idx == 0) enter_dir(s, s->dirs[0]);
                else enter_dir(s, s->dirs[idx]);
            }
        }
    } else if (!strcmp(key, "state")) {
        /* "1\t<group name>\t<level>\t<fx>". The name may be empty (no group loaded). */
        if (strncmp(val, "1\t", 2) == 0) {
            const char *p = val + 2;
            const char *tab = strchr(p, '\t');
            int level = s->level, fx = s->fx;
            if (tab && sscanf(tab + 1, "%d\t%d", &level, &fx) == 2) {
                int nlen = (int)(tab - p);
                if (nlen > 0) {
                    if (nlen >= (int)sizeof s->want) nlen = (int)sizeof s->want - 1;
                    memcpy(s->want, p, (size_t)nlen);
                    s->want[nlen] = 0;
                    s->loaded = -1;
                    s->need_load = 1;
                }
                if (level < 0) level = 0;
                if (level > 100) level = 100;
                s->level = level;
                s->fx = fx ? 1 : 0;
                const char *t1 = strchr(tab + 1, '\t');
                const char *t2 = t1 ? strchr(t1 + 1, '\t') : NULL;
                if (t2 && strcmp(s->root, t2 + 1) != 0) {
                    snprintf(s->root, PATH_N, "%s", t2 + 1);
                    s->rescan = 1;
                }
            }
        }
    }
    send_preview_midi(s);
    pthread_mutex_unlock(&s->mu);
}

static int pad_index(const char *key) {
    if (strncmp(key, "pad_", 4) != 0) return -1;
    int n = atoi(key + 4);
    if (n < 1 || n > MX_PADS) return -1;
    return n - 1;
}

static int get_param(void *inst, const char *key, char *buf, int buf_len) {
    State *s = inst;
    if (!key) return 0;
    pthread_mutex_lock(&s->mu);
    int r = 0;
    if (!strcmp(key, "display_rev")) {
        char t[16];
        snprintf(t, sizeof t, "%d", s->rev);
        r = put(buf, buf_len, t);
    } else if (!strcmp(key, "state")) {
        char name[256];
        name[0] = 0;
        if (s->loaded > 0 && s->loaded <= s->nfiles) stem(s->files[s->loaded - 1], name, sizeof name);
        char t[800];
        snprintf(t, sizeof t, "1\t%s\t%d\t%d\t%s", name, s->level, s->fx, s->root);
        r = put(buf, buf_len, t);
    } else if (!strcmp(key, "kit")) {
        char t[16];
        snprintf(t, sizeof t, "%d", s->kit_index);
        r = put(buf, buf_len, t);
    } else if (!strcmp(key, "kit_name")) {
        if (s->kit_index > 0 && s->kit_index <= s->nfiles && s->scan_done) {
            char name[256];
            stem(s->files[s->kit_index - 1], name, sizeof name);
            r = put(buf, buf_len, name);
        } else {
            r = put(buf, buf_len, "—");
        }
    } else if (!strcmp(key, "level")) {
        char t[16];
        snprintf(t, sizeof t, "%d", s->level);
        r = put(buf, buf_len, t);
    } else if (!strcmp(key, "fx")) {
        r = put(buf, buf_len, s->fx ? "1" : "0");
    } else if (!strncmp(key, "krow_", 5)) {
        int n = atoi(key + 5);
        int on = strstr(key, "_on") != NULL;
        int idx = (n >= 1 && n <= KIT_ROWS) ? s->kit_scroll + n - 1 : -1;
        int listed = s->scan_done ? s->nfiles : -1;
        if (on) {
            r = put(buf, buf_len, (idx >= 0 && idx == s->kit_index) ? "1" : "0");
        } else if (!s->scan_done) {
            r = put(buf, buf_len, n == 1 ? "scanning…" : "");
        } else if (idx == 0) {
            r = put(buf, buf_len, "—");
        } else if (idx >= 1 && idx <= listed) {
            char name[96];
            stem(s->files[idx - 1], name, sizeof name);
            r = put(buf, buf_len, name);
        } else {
            r = put(buf, buf_len, "");
        }
    } else if (!strcmp(key, "status")) {
        if (s->pat_msg[0]) r = put(buf, buf_len, s->pat_msg);
        else if (s->kit) r = put(buf, buf_len, play_status(s->kit));
        else if (s->err[0]) r = put(buf, buf_len, s->err);
        else if (!s->scan_done) r = put(buf, buf_len, "scanning…");
        else if (s->nfiles == 0) r = put(buf, buf_len, "no groups");
        else {
            char t[64];
            snprintf(t, sizeof t, "%d groups", s->nfiles);
            r = put(buf, buf_len, t);
        }
    } else if (!strcmp(key, "info")) {
        r = put(buf, buf_len, s->kit ? play_info(s->kit) : "");
    } else if (!strcmp(key, "pat_play")) {
        r = put(buf, buf_len, s->preview ? "1" : "0");
    } else if (!strcmp(key, "pat_info")) {
        if (s->pat_msg[0]) r = put(buf, buf_len, s->pat_msg);
        else if (s->pat_sel <= 0) {
            r = put(buf, buf_len, "Empty");
        } else if (s->kit && s->pat_sel - 1 < play_npat(s->kit)) {
            char t[80];
            snprintf(t, sizeof t, "%s · %d events", play_pat_name(s->kit, s->pat_sel - 1),
                     play_pat_events(s->kit, s->pat_sel - 1));
            r = put(buf, buf_len, t);
        } else if (s->kit && play_npat(s->kit) == 0) {
            r = put(buf, buf_len, "no patterns");
        } else {
            r = put(buf, buf_len, "");
        }
    } else if (!strncmp(key, "pat_", 4) && isdigit((unsigned char)key[4])) {
        int n = atoi(key + 4);
        int on = strstr(key, "_on") != NULL;
        if (n >= 1 && n <= MX_PATS && on) {
            r = put(buf, buf_len, (s->pat_sel == n - 1) ? "1" : "0");
        } else if (n == 1) {
            r = put(buf, buf_len, "Empty");
        } else if (n >= 2 && n <= MX_PATS) {
            int pi = n - 2;
            const char *nm = (s->kit && pi < play_npat(s->kit)) ? play_pat_name(s->kit, pi) : "";
            r = put(buf, buf_len, nm[0] ? nm : "—");
        }
    } else if (!strcmp(key, "libpath")) {
        char t[96];
        place_text(s, t, (int)sizeof t);
        r = put(buf, buf_len, t);
    } else if (!strcmp(key, "browse")) {
        r = put(buf, buf_len, s->picking ? "1" : "0");
    } else if (!strncmp(key, "help_", 5)) {
        int n = atoi(key + 5);
        if (n == 1) r = put(buf, buf_len, "How to Add NI Groups:");
        else if (n == 2) r = put(buf, buf_len, "1. On your computer, find the \"Maschine 2 Factory Library\" folder.");
        else if (n == 3) r = put(buf, buf_len, "2. Copy the \"Samples\" and \"Groups\" folders to a folder on your MPC.");
        else if (n == 4) r = put(buf, buf_len, "3. Press \"Refresh\".");
        else if (n == 5) {
            if (!s->scan_report) r = put(buf, buf_len, "");
            else if (!s->scan_done) r = put(buf, buf_len, "Refreshing...");
            else {
                char t[80];
                snprintf(t, sizeof t, "Found %d groups, %d samples", s->nfiles, s->nsamples);
                r = put(buf, buf_len, t);
            }
        } else if (n == 6) r = put(buf, buf_len, s->picking ? "Use folder" : "Change folder");
        else if (n == 7) r = put(buf, buf_len, "Refresh");
        else r = put(buf, buf_len, "");
    } else if (!strncmp(key, "frow_", 5)) {
        int n = atoi(key + 5);
        int on = strstr(key, "_on") != NULL;
        int kind = 0, idx = -1, step = 1;
        brow_slot(s, n, &kind, &idx, &step);
        if (on) {
            r = put(buf, buf_len, "0");
        } else if (kind == 1) {
            r = put(buf, buf_len, "back");
        } else if (kind == 2) {
            r = put(buf, buf_len, "more");
        } else if (kind == 3 && idx >= 0) {
            if (s->up && idx == 0) r = put(buf, buf_len, "..");
            else {
                const char *b = strrchr(s->dirs[idx], '/');
                r = put(buf, buf_len, b && b[1] ? b + 1 : s->dirs[idx]);
            }
        } else {
            r = put(buf, buf_len, "");
        }
    } else if (!strncmp(key, "tint_", 5)) {
        int n = atoi(key + 5);
        int t = 0;
        if (n >= 1 && n <= MX_PADS && s->kit) t = play_pad_tint(play_pad_name(s->kit, n - 1));
        char b[8];
        snprintf(b, sizeof b, "%d", t);
        r = put(buf, buf_len, b);
    } else if (!strncmp(key, "cell_", 5)) {
        int n = atoi(key + 5);
        int band = 0;
        if (n >= 1 && n <= 256) {
            int row = (n - 1) / 16, col = (n - 1) % 16;
            band = play_vel_band(s->grid[row][col]);
        }
        char t[8];
        snprintf(t, sizeof t, "%d", band);
        r = put(buf, buf_len, t);
    } else {
        int pad = pad_index(key);
        int on = strstr(key, "_on") != NULL;
        if (pad >= 0 && on) {
            r = put(buf, buf_len, (s->kit && play_pad_active(s->kit, pad)) ? "1" : "0");
        } else if (pad >= 0) {
            const char *nm = s->kit ? play_pad_name(s->kit, pad) : "";
            r = put(buf, buf_len, nm[0] ? nm : "—");
        }
    }
    pthread_mutex_unlock(&s->mu);
    return r;
}

static void render(void *inst, int16_t *out, int frames) {
    State *s = inst;
    pthread_mutex_lock(&s->mu);
    service(s);
    float master = s->level / 100.f;
    if (s->kit) {
        play_set_bpm(s->kit, s->bpm);
        play_render(s->kit, out, frames, master, s->fx);
    } else {
        for (int i = 0; i < frames; i++) {
            float y = 0;
            if (s->beep > 0) {
                s->beep_ph += 2.0 * 3.1415926535 * 440.0 / SR;
                float env = s->beep / (float)(SR / 8);
                y = sin(s->beep_ph) * env * 0.25f;
                s->beep--;
            }
            int16_t v = (int16_t)(y * 32000.f);
            out[2 * i] = out[2 * i + 1] = v;
        }
    }
    send_preview_midi(s);
    pthread_mutex_unlock(&s->mu);
}

static const mpc_engine_t ENGINE = { create, destroy, midi, set_param, get_param, render, NULL };
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
