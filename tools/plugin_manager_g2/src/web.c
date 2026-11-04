/* A web page on the local network while the manager is loaded on a track:
 * http://<mpc address>:WEB_PORT/ is the catalog with Install / Update / Remove and APPLY, the same queue as the screen.
 * GET /api/state is the state as JSON; POST /api/queue?id=<id>&do=install|remove|cancel,
 * /api/apply (prepare, then a second call restarts MPC), /api/refresh change it. A POST must carry "X-PM: 1" and no
 * foreign Origin, so another web site open in the same browser cannot drive it (the header forces a CORS preflight,
 * which is never answered). MPC creates the plugin
 * more than once, so only one instance holds the port: the others retry the bind every couple of seconds and take
 * over when it is closed. Included by manager.c (it reads mgr_t under mu). */
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <ifaddrs.h>
#include <arpa/inet.h>

#ifndef WEB_PORT
#define WEB_PORT 8790
#endif

static void web_addr(char *b, int n) {   /* the first non-loopback IPv4 address, "" none */
    struct ifaddrs *ia, *i;
    b[0] = 0;
    if (getifaddrs(&ia)) return;
    for (i = ia; i; i = i->ifa_next)
        if (i->ifa_addr && i->ifa_addr->sa_family == AF_INET && strcmp(i->ifa_name, "lo")) {
            inet_ntop(AF_INET, &((struct sockaddr_in *)i->ifa_addr)->sin_addr, b, n);
            break;
        }
    freeifaddrs(ia);
}

typedef struct { char *s; size_t n, cap; } wbuf_t;

static void wput(wbuf_t *w, const char *fmt, ...) {
    va_list ap;
    for (;;) {
        va_start(ap, fmt);
        int k = vsnprintf(w->s ? w->s + w->n : NULL, w->s ? w->cap - w->n : 0, fmt, ap);
        va_end(ap);
        if (k < 0) return;
        if (w->s && w->n + k < w->cap) { w->n += k; return; }
        size_t c = (w->cap + k + 1) * 2;
        char *s = realloc(w->s, c);
        if (!s) return;
        w->s = s, w->cap = c;
    }
}

static void wesc(wbuf_t *w, const char *s, int html) {   /* JSON string body, or HTML text */
    for (; *s; s++) {
        unsigned char c = *s;
        if (html) wput(w, c == '<' ? "&lt;" : c == '>' ? "&gt;" : c == '&' ? "&amp;" : c == '"' ? "&quot;" : "%c", c);
        else if (c == '"' || c == '\\') wput(w, "\\%c", c);
        else if (c < 0x20) wput(w, "\\u%04x", c);
        else wput(w, "%c", c);
    }
}

static const char *const WEB_ST[] = {"none", "install", "update", "installed", "q_install", "q_update", "q_remove", "disabled", "menu", "register", "q_register"};

static void web_state(mgr_t *m, wbuf_t *w) {
    pthread_mutex_lock(&m->mu);
    char st[200];   /* what the screen's status line shows (mgr_get_param "status", without the search hints) */
    if (m->sticky) snprintf(st, sizeof st, "%s", m->status);
    else queue_text(m, st, sizeof st);
    wput(w, "{\"status\":\"");
    wesc(w, st, 0);
    wput(w, "\",\"status_kind\":%d,\"online\":%d,\"loaded\":%d,\"busy\":%d,\"ready\":%d,\"failed\":%d,\"queued\":%d,"
            "\"problem\":\"", m->sticky ? m->status_kind : OK, m->online, m->loaded, m->busy, m->ready, m->failed,
         count_queued(m)
         );
    wesc(w, m->dev->problem, 0);
    wput(w, "\",\"downloading\":%d,\"progress\":%.2f,\"disk\":\"", m->downloading, m->progress);
    wesc(w, m->disk_free, 0);
    wput(w, "\",\"tsel\":%d,\"targets\":[", ntargets(m) ? m->tsel % ntargets(m) : 0);
    for (int k = 0; k < ntargets(m) && k < 4; k++) {   /* where new installs go (the screen's drive menu shows four) */
        wput(w, "%s{\"name\":\"", k ? "," : "");
        wesc(w, target_name(m, k), 0);
        wput(w, "\",\"path\":\"");
        wesc(w, target_at(m, k), 0);
        wput(w, "\"}");
    }
    wput(w, "],\"plugins\":[");
    for (int i = 0, n = 0; i < m->npkg; i++) {
        const pkg_t *p = &m->pkg[i];
        if (!p->url[0] && !installed(p)) continue;   /* as the screen: no download for this MPC (a Gen1-only zip on a Gen2), not listed */
        wput(w, "%s{\"id\":\"", n++ ? "," : "");
        wesc(w, p->id, 0);
        wput(w, "\",\"name\":\"");
        wesc(w, p->name, 0);
        wput(w, "\",\"author\":\"");
        wesc(w, p->author, 0);
        wput(w, "\",\"kind\":\"");
        wesc(w, p->kind, 0);
        wput(w, "\",\"installed\":\"");
        wesc(w, p->installed, 0);
        wput(w, "\",\"latest\":\"");
        wesc(w, p->latest, 0);
        wput(w, "\",\"files\":%d,\"state\":\"%s\"}", p->ufiles, WEB_ST[pkg_state(m, i)]);
    }
    wput(w, "]}");
    pthread_mutex_unlock(&m->mu);
}

static int web_hex(int c) { return c >= '0' && c <= '9' ? c - '0' : (c | 32) >= 'a' && (c | 32) <= 'f' ? (c | 32) - 'a' + 10 : -1; }

static int web_arg(const char *q, const char *k, char *b, int n) {   /* ?k=v from the request line, %XX and + decoded */
    size_t kl = strlen(k);
    for (const char *p = q; p && *p && *p != ' '; p++) {
        if ((p == q || p[-1] == '?' || p[-1] == '&') && !strncmp(p, k, kl) && p[kl] == '=') {
            int i = 0;
            for (p += kl + 1; *p && *p != '&' && *p != ' ' && i < n - 1; p++)
                if (*p == '%' && web_hex(p[1]) >= 0 && web_hex(p[2]) >= 0) b[i++] = web_hex(p[1]) * 16 + web_hex(p[2]), p += 2;
                else b[i++] = *p == '+' ? ' ' : *p;
            b[i] = 0;
            return 1;
        }
    }
    return 0;
}

static const char *web_post(mgr_t *m, const char *path) {   /* "" done, else why not */
    char id[48], d[16];
    const char *err = "";
    pthread_mutex_lock(&m->mu);
    int busy = m->busy == J_PREPARE || m->busy == J_LAUNCH;
    if (!strncmp(path, "/api/refresh", 12)) post(m, J_REFRESH);
    else if (busy) err = "busy";
    else if (!strncmp(path, "/api/queue?", 11) && web_arg(path + 10, "id", id, sizeof id) && web_arg(path + 10, "do", d, sizeof d)) {
        int i = 0;
        while (i < m->npkg && strcmp(m->pkg[i].id, id)) i++;
        if (i == m->npkg) err = "unknown plugin";
        else {
            int st = pkg_state(m, i);
            if (!strcmp(d, "install") && (st == S_INSTALL || st == S_UPDATE)) act(m, i, "act");
            else if (!strcmp(d, "reinstall") && st == S_INSTALLED) act(m, i, "reinstall");
            else if (!strcmp(d, "remove") && (st == S_INSTALLED || st == S_UPDATE)) act(m, i, "remove");
            else if (!strcmp(d, "cancel") && (st == S_Q_INSTALL || st == S_Q_UPDATE || st == S_Q_REMOVE || st == S_Q_REGISTER)) requeue(m, &m->pkg[i], 0);
            else if (!strcmp(d, "register") && st == S_REGISTER) act(m, i, "act");
            else err = "not possible now";
            m->menu = -1;
        }
    } else if (!strncmp(path, "/api/target?", 12) && web_arg(path + 11, "k", d, sizeof d)) {   /* the screen's drive menu pick */
        int k = atoi(d);
        if (k < 0 || k >= ntargets(m) || k >= 4) err = "no such drive";
        else if (k != m->tsel % ntargets(m)) {
            m->tsel = k;
            target_save(m);
            m->ready = 0;
            post(m, J_REFRESH);
        }
    } else if (!strncmp(path, "/api/apply", 10)) {   /* the page asked first: the second call is the restart prompt's GO */
        if (m->ready) { m->ready = 0; post(m, J_LAUNCH); }
        else if (count_queued(m) && !m->dev->problem[0]) post(m, J_PREPARE);
        else err = "nothing queued";
    } else err = "unknown request";
    m->rev++;
    pthread_mutex_unlock(&m->mu);
    return err;
}

#include "web_page.h"

static int web_header(const char *req, const char *name, char *b, int n) {   /* a request header's value, case-insensitive name */
    size_t nl = strlen(name);
    for (const char *p = strstr(req, "\r\n"); p && p[2]; p = strstr(p + 2, "\r\n"))
        if (!strncasecmp(p + 2, name, nl) && p[2 + nl] == ':') {
            const char *v = p + 3 + nl;
            while (*v == ' ') v++;
            int i = 0;
            while (v[i] && v[i] != '\r' && i < n - 1) b[i] = v[i], i++;
            b[i] = 0;
            return 1;
        }
    return 0;
}


/* ---- the user's files (ROMs): only into a folder the installed plugin's mpc-plugin.json names in user_files ---- */
#define WEB_MAXFILE (64 << 20)

static int web_safe_rel(const char *p) {   /* "roms", "data/roms": no "..", no leading /, plain characters */
    if (!p[0] || p[0] == '/' || strstr(p, "..") || strlen(p) > 100) return 0;
    for (; *p; p++) if (!isalnum((unsigned char)*p) && !strchr(" ._/-", *p)) return 0;
    return 1;
}

static int web_safe_name(const char *n) {   /* the desktop app's rule: ^[A-Za-z0-9][A-Za-z0-9 ._()+,'&-]{0,150}$ */
    if (!isalnum((unsigned char)n[0]) || strlen(n) > 151) return 0;
    for (const char *p = n + 1; *p; p++) if (!isalnum((unsigned char)*p) && !strchr(" ._()+,'&-", *p)) return 0;
    return 1;
}

/* the installed plugin's folder for ?id=, and (with want_path) the checked group folder ?path= inside it; "" + why on failure */
static const char *web_target(mgr_t *m, const char *q, int want_path, char *folder, int fn, char *grp, int gn) {
    char id[48];
    folder[0] = 0;
    if (!web_arg(q, "id", id, sizeof id)) return "no id";
    pthread_mutex_lock(&m->mu);
    for (int i = 0; i < m->npkg; i++)
        if (!strcmp(m->pkg[i].id, id) && m->pkg[i].folder[0]) snprintf(folder, fn, "%s", m->pkg[i].folder);
    pthread_mutex_unlock(&m->mu);
    if (!folder[0]) return "not installed";
    if (!want_path) return "";
    if (!web_arg(q, "path", grp, gn) || !web_safe_rel(grp)) return "bad folder";
    char mp[400], pat[140], pat2[140];
    snprintf(mp, sizeof mp, "%s/mpc-plugin.json", folder);
    char *js = slurp(mp, 64 << 10);
    snprintf(pat, sizeof pat, "\"path\": \"%s\"", grp);
    snprintf(pat2, sizeof pat2, "\"path\":\"%s\"", grp);
    const char *u = js ? strstr(js, "\"user_files\"") : NULL;
    int ok = u && (strstr(u, pat) || strstr(u, pat2));
    free(js);
    return ok ? "" : "this plugin has no such folder for your files";
}

static int web_mkdirs(const char *base, const char *rel) {
    char p[600];
    int n = snprintf(p, sizeof p, "%s/%s", base, rel), b = strlen(base);
    if (n >= (int)sizeof p) return -1;
    for (int i = b + 1; i <= n; i++)
        if (p[i] == '/' || !p[i]) {
            char c = p[i];
            p[i] = 0;
            if (mkdir(p, 0755) && errno != EEXIST) return -1;
            p[i] = c;
        }
    return 0;
}

static void web_ls(const char *dir, wbuf_t *w) {
    wput(w, "[");
    DIR *d = opendir(dir);
    struct dirent *e;
    int first = 1;
    while (d && (e = readdir(d))) {
        char fp[900];
        struct stat st;
        if (e->d_name[0] == '.') continue;
        snprintf(fp, sizeof fp, "%s/%s", dir, e->d_name);
        if (stat(fp, &st) || !S_ISREG(st.st_mode)) continue;
        wput(w, "%s{\"name\":\"", first ? "" : ",");
        wesc(w, e->d_name, 0);
        wput(w, "\",\"size\":%lld}", (long long)st.st_size);
        first = 0;
    }
    if (d) closedir(d);
    wput(w, "]");
}

/* PUT body: `have` bytes already read after the headers, then the rest from the socket, into <dir>/<name>.part, renamed when complete */
static const char *web_save(int c, const char *dir, const char *name, const char *have, long have_n, long len) {
    char fp[900], part[910];
    snprintf(fp, sizeof fp, "%s/%s", dir, name);
    snprintf(part, sizeof part, "%s.part", fp);
    int f = open(part, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (f < 0) return "cannot write on the drive";
    long done = 0;
    if (have_n > len) have_n = len;
    if (have_n > 0 && write(f, have, have_n) != have_n) { close(f); unlink(part); return "write failed"; }
    done = have_n;
    char buf[65536];
    struct pollfd pf = {c, POLLIN, 0};
    while (done < len) {
        if (poll(&pf, 1, 10000) <= 0) break;
        long want = len - done > (long)sizeof buf ? (long)sizeof buf : len - done;
        ssize_t k = read(c, buf, want);
        if (k <= 0 || write(f, buf, k) != k) break;
        done += k;
    }
    if (done != len || fsync(f) || close(f)) { if (done != len) close(f); unlink(part); return "the upload stopped part way"; }
    if (rename(part, fp)) { unlink(part); return "cannot write on the drive"; }
    return "";
}

static void web_reply(int c, mgr_t *m) {
    char req[4096];
    int n = 0, k;
    struct pollfd pf = {c, POLLIN, 0};
    while (n < (int)sizeof req - 1 && poll(&pf, 1, 2000) > 0 && (k = read(c, req + n, sizeof req - 1 - n)) > 0) {
        n += k;
        req[n] = 0;
        if (strstr(req, "\r\n\r\n")) break;
    }
    req[n] = 0;
    wbuf_t w = {0};
    const char *type = "text/html; charset=utf-8", *code = "200 OK";
    int hl = strstr(req, "\r\n\r\n") ? (int)(strstr(req, "\r\n\r\n") - req) + 4 : n;
    char x[8], origin[200], host[200];
    int trusted = web_header(req, "X-PM", x, sizeof x) && !strcmp(x, "1") &&
                  !(web_header(req, "Origin", origin, sizeof origin) && (!web_header(req, "Host", host, sizeof host) ||
                    strncmp(origin, "http://", 7) || strcmp(origin + 7, host)));
    char folder[256], grp[120], name[160], dir[400];
    const char *why;
    if (!strncmp(req, "GET /api/state ", 15)) web_state(m, &w), type = "application/json";
    else if (!strncmp(req, "GET /api/manifest?", 18)) {   /* the plugin's mpc-plugin.json as it is (its user_files rules) */
        if ((why = web_target(m, req + 17, 0, folder, sizeof folder, grp, sizeof grp))[0]) code = "404 Not Found", wput(&w, "%s\n", why), type = "text/plain";
        else {
            char mp[400];
            snprintf(mp, sizeof mp, "%s/mpc-plugin.json", folder);
            char *js = slurp(mp, 64 << 10);
            if (js) wput(&w, "%s", js), type = "application/json"; else code = "404 Not Found", type = "text/plain";
            free(js);
        }
    } else if (!strncmp(req, "GET /api/ls?", 12)) {
        if ((why = web_target(m, req + 11, 1, folder, sizeof folder, grp, sizeof grp))[0]) code = "404 Not Found", wput(&w, "%s\n", why), type = "text/plain";
        else snprintf(dir, sizeof dir, "%s/%s", folder, grp), web_ls(dir, &w), type = "application/json";
    } else if ((!strncmp(req, "PUT /api/file?", 14) || !strncmp(req, "POST /api/delfile?", 18)) && trusted) {
        const char *q = req[0] == 'P' && req[1] == 'U' ? req + 13 : req + 17;
        char cl[24];
        long len = web_header(req, "Content-Length", cl, sizeof cl) ? atol(cl) : -1;
        type = "text/plain";
        if ((why = web_target(m, q, 1, folder, sizeof folder, grp, sizeof grp))[0]) code = "409 Conflict", wput(&w, "%s\n", why);
        else if (!web_arg(q, "name", name, sizeof name) || !web_safe_name(name)) code = "409 Conflict", wput(&w, "that file name cannot be used\n");
        else if (req[1] == 'O') {   /* delfile */
            snprintf(dir, sizeof dir, "%s/%s/%s", folder, grp, name);
            if (unlink(dir)) code = "409 Conflict", wput(&w, "no such file\n"); else wput(&w, "ok\n");
        } else if (len < 0 || len > WEB_MAXFILE) code = "413 Payload Too Large", wput(&w, "too big (64 MB at most)\n");
        else if (web_mkdirs(folder, grp)) code = "409 Conflict", wput(&w, "cannot make the folder\n");
        else {
            snprintf(dir, sizeof dir, "%s/%s", folder, grp);
            if ((why = web_save(c, dir, name, req + hl, n - hl, len))[0]) code = "409 Conflict", wput(&w, "%s\n", why);
            else wput(&w, "ok\n");
        }
    }
    else if (!strncmp(req, "GET / ", 6)) wput(&w, "%s", WEB_PAGE);
    else if (!strncmp(req, "POST /api/", 10) || !strncmp(req, "PUT /api/", 9)) {
        type = "text/plain";
        if (!trusted) code = "403 Forbidden", wput(&w, "refused: not from this page\n");
        else {
            char path[300];
            sscanf(req + 5, "%299s", path);
            const char *err = web_post(m, path);
            if (err[0]) code = "409 Conflict", wput(&w, "%s\n", err);
            else wput(&w, "ok\n");
        }
    } else code = "404 Not Found", wput(&w, "not found\n"), type = "text/plain";
    char h[200];
    int hn = snprintf(h, sizeof h, "HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
                      code, type, w.n);
    if (write(c, h, hn) == hn && w.s) { ssize_t r = write(c, w.s, w.n); (void)r; }
    free(w.s);
}

static int web_quit(mgr_t *m) {
    pthread_mutex_lock(&m->mu);
    int q = m->quit;
    pthread_mutex_unlock(&m->mu);
    return q;
}

static void *web_thread(void *ud) {
    mgr_t *m = ud;
    int s = -1;
    long long last = -100;   /* when the address was read: it can change (Wi-Fi joined later, DHCP), so every few seconds */
    while (!web_quit(m)) {
        if (s < 0) {
            s = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
            int one = 1;
            struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(WEB_PORT), .sin_addr.s_addr = htonl(INADDR_ANY)};
            if (s >= 0) setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
            if (s < 0 || bind(s, (struct sockaddr *)&a, sizeof a) || listen(s, 4)) {   /* another instance has it */
                if (s >= 0) close(s);
                s = -1;
                for (int i = 0; i < 4 && !web_quit(m); i++) usleep(500000);
                continue;
            }
        }
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        if (ts.tv_sec - last >= 5) {
            char a[48], u[64] = "";
            web_addr(a, sizeof a);
            if (a[0]) snprintf(u, sizeof u, "http://%s:%d", a, WEB_PORT);
            pthread_mutex_lock(&web_mu);
            snprintf(web_url, sizeof web_url, "%s", u);
            pthread_mutex_unlock(&web_mu);
            last = ts.tv_sec;
        }
        struct pollfd pf = {s, POLLIN, 0};
        if (poll(&pf, 1, 500) <= 0) continue;
        int c = accept4(s, NULL, NULL, SOCK_CLOEXEC);
        if (c < 0) continue;
        web_reply(c, m);
        close(c);
    }
    if (s >= 0) {
        close(s);
        pthread_mutex_lock(&web_mu);
        web_url[0] = 0;   /* nobody serves the page now (another instance may take the port and set it again) */
        pthread_mutex_unlock(&web_mu);
    }
    return NULL;
}
