/* vst3_editor.c — the desktop VST3 editor: draws the port's MPC skin in the plugin window, with live values, and turns
 * clicks, drags and the mouse wheel into parameter changes. Included at the end of vst3_wrap.c when tools/build_vst3.sh
 * builds with -DVST3_EDITOR (it shares that file's statics), and linked with X11, cairo and FreeType.
 *
 * The skin comes from tools/desktop_skin.py, which flattens the built skin (TUI.json) into <bundle>/Contents/Resources/skin/
 * desktop.skin and copies its images there: the same rules studio.py preview uses, so the window shows what the offline
 * preview shows. MPC draws the page tabs on its function keys; here a strip above the page holds them.
 *
 * Threads: X11 events and the redraw timer come through the host's IRunLoop (the VST3 rule on Linux), on the host's UI
 * thread, so edits go to the host with performEdit like any controller's. Without an IRunLoop a thread of our own runs both,
 * and edits go through a queue process() drains instead (performEdit is for the UI thread only). Text a readout shows and
 * values are read straight from the engine (under its lock) at most 30 times a second, and only a page whose values
 * changed is redrawn.
 *
 * mpc_vst3_snapshot() renders a page to a PNG without any window (tools/vst3_host_test.c --shots). */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <cairo.h>
#include <cairo-xlib.h>
#include <cairo-ft.h>
#include <ft2build.h>
#include FT_FREETYPE_H
#include <poll.h>
#include <unistd.h>
#include "plugin_dir.h"

#define TAB_H 44          /* the tab strip above the page, in skin pixels */
#define MAX_ITEMS 8192
#define MAX_IMAGES 1024
#define MAX_TABS 32
#define DRAG_PX 300.0     /* a vertical drag across this many skin pixels covers a knob's whole range */

enum { IT_IMG, IT_FILM, IT_BTN, IT_LABEL, IT_HIT };
enum { HIT_RADIO, HIT_TOGGLE, HIT_DRAG };

typedef struct { int p, i; } cond_t;
typedef struct {
    int kind, tab, x, y, w, h, param, img, img2, frames, id, n, mode, just, upper, style;
    double size;
    uint32_t colour;
    char *text;
    int ncond;
    cond_t cond[4];
} item_t;

typedef struct {
    int w, h, ntabs;
    char tabname[MAX_TABS][32];
    item_t *items;
    int nitems;
    char *imgname[MAX_IMAGES];
    cairo_surface_t *img[MAX_IMAGES];
    int nimg;
    cairo_font_face_t *font[3];   /* Regular, SemiBold, Bold */
    double font_ratio[3];         /* em size for a font height (MPC's height is ascent + descent) */
} skin_t;

/* ---- the skin file ----------------------------------------------------------------------------------------------- */
static int skin_image(skin_t *s, const char *dir, const char *name) {
    if (!name[0]) return -1;
    for (int i = 0; i < s->nimg; i++) if (!strcmp(s->imgname[i], name)) return i;
    if (s->nimg == MAX_IMAGES) return -1;
    char path[1024];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    cairo_surface_t *im = cairo_image_surface_create_from_png(path);
    if (cairo_surface_status(im) != CAIRO_STATUS_SUCCESS) { cairo_surface_destroy(im); im = NULL; }
    s->imgname[s->nimg] = strdup(name);
    s->img[s->nimg] = im;
    return s->nimg++;
}

/* Each face has a FreeType library of its own, freed with it. cairo keeps font faces alive in its caches after
 * cairo_font_face_destroy() and frees them later, from any thread, so a library shared by the skin could be gone by then. */
typedef struct { FT_Library lib; FT_Face face; } ft_font_t;
static void ft_done(void *p) {
    ft_font_t *f = p;
    FT_Done_Face(f->face);
    FT_Done_FreeType(f->lib);
    free(f);
}

static void skin_fonts(skin_t *s, const char *dir) {
    static const char *files[3] = { "TitilliumWeb-Regular.ttf", "TitilliumWeb-SemiBold.ttf", "TitilliumWeb-Bold.ttf" };
    static cairo_user_data_key_t key;
    for (int k = 0; k < 3; k++) {
        char path[1024];
        s->font_ratio[k] = 1.0;
        snprintf(path, sizeof path, "%s/%s", dir, files[k]);
        ft_font_t *f = calloc(1, sizeof *f);
        if (!f) continue;
        if (FT_Init_FreeType(&f->lib)) { free(f); continue; }
        if (FT_New_Face(f->lib, path, 0, &f->face)) { FT_Done_FreeType(f->lib); free(f); continue; }
        FT_Face face = f->face;
        s->font[k] = cairo_ft_font_face_create_for_ft_face(face, 0);
        if (cairo_font_face_set_user_data(s->font[k], &key, f, ft_done) != CAIRO_STATUS_SUCCESS) {
            cairo_font_face_destroy(s->font[k]);
            s->font[k] = NULL;
            ft_done(f);
            continue;
        }
        if (face->ascender - face->descender > 0) s->font_ratio[k] = (double)face->units_per_EM / (face->ascender - face->descender);
    }
}

static void skin_free(skin_t *s) {
    if (!s) return;
    for (int i = 0; i < s->nitems; i++) free(s->items[i].text);
    free(s->items);
    for (int i = 0; i < s->nimg; i++) { free(s->imgname[i]); if (s->img[i]) cairo_surface_destroy(s->img[i]); }
    for (int k = 0; k < 3; k++) if (s->font[k]) cairo_font_face_destroy(s->font[k]);   /* FreeType goes with them (ft_done) */
    free(s);
}

static const char *field(char **f, int nf, const char *key) {
    size_t k = strlen(key);
    for (int i = 1; i < nf; i++) if (!strncmp(f[i], key, k) && f[i][k] == '=') return f[i] + k + 1;
    return "";
}

static skin_t *skin_load(void) {
    char here[512], dir[700], path[760];
    if (!mpc_plugin_dir(here, sizeof here)) return NULL;
    snprintf(dir, sizeof dir, "%s/../Resources/skin", here);
    snprintf(path, sizeof path, "%s/desktop.skin", dir);
    FILE *f = fopen(path, "r");
    if (!f) return NULL;
    skin_t *s = calloc(1, sizeof *s);
    s->items = calloc(MAX_ITEMS, sizeof *s->items);
    s->w = 1280; s->h = 628;
    char line[4096];
    int tab = -1;
    while (fgets(line, sizeof line, f)) {
        char *fl[40];
        int nf = 0;
        line[strcspn(line, "\n")] = 0;
        for (char *t = strtok(line, "\t"); t && nf < 40; t = strtok(NULL, "\t")) fl[nf++] = t;
        if (!nf) continue;
        if (!strcmp(fl[0], "size")) { s->w = atoi(field(fl, nf, "w")); s->h = atoi(field(fl, nf, "h")); continue; }
        if (!strcmp(fl[0], "tab")) {
            if (s->ntabs < MAX_TABS) snprintf(s->tabname[s->ntabs++], 32, "%s", field(fl, nf, "name"));
            tab = s->ntabs - 1;
            continue;
        }
        int kind = !strcmp(fl[0], "img") ? IT_IMG : !strcmp(fl[0], "film") ? IT_FILM : !strcmp(fl[0], "btn") ? IT_BTN
                 : !strcmp(fl[0], "label") ? IT_LABEL : !strcmp(fl[0], "hit") ? IT_HIT : -1;
        if (kind < 0 || tab < 0 || s->nitems == MAX_ITEMS) continue;
        item_t *it = &s->items[s->nitems++];
        it->kind = kind; it->tab = tab;
        it->x = atoi(field(fl, nf, "x")); it->y = atoi(field(fl, nf, "y"));
        it->w = atoi(field(fl, nf, "w")); it->h = atoi(field(fl, nf, "h"));
        it->param = *field(fl, nf, "param") ? atoi(field(fl, nf, "param")) : -1;
        it->img = it->img2 = -1;
        if (kind == IT_IMG || kind == IT_FILM) it->img = skin_image(s, dir, field(fl, nf, "src"));
        if (kind == IT_BTN) { it->img = skin_image(s, dir, field(fl, nf, "on")); it->img2 = skin_image(s, dir, field(fl, nf, "off")); }
        it->frames = atoi(field(fl, nf, "frames"));
        it->id = atoi(field(fl, nf, "id"));
        it->n = atoi(field(fl, nf, "n"));
        const char *m = field(fl, nf, "mode");
        it->mode = !strcmp(m, "radio") ? HIT_RADIO : !strcmp(m, "drag") ? HIT_DRAG : HIT_TOGGLE;
        if (kind == IT_LABEL) {
            const char *j = field(fl, nf, "just"), *st = field(fl, nf, "style");
            it->just = *j == 'c' ? 1 : *j == 'r' ? 2 : 0;
            it->upper = atoi(field(fl, nf, "upper"));
            it->colour = (uint32_t)strtoul(field(fl, nf, "colour"), NULL, 16);
            it->size = atof(field(fl, nf, "size"));
            it->style = strstr(st, "Bold") && !strstr(st, "Semi") ? 2 : strstr(st, "Semi") ? 1 : 0;
            if (!strcmp(field(fl, nf, "kind"), "name")) it->text = strdup(field(fl, nf, "text"));
        }
        const char *c = field(fl, nf, "if");
        while (*c && it->ncond < 4) {
            it->cond[it->ncond].p = atoi(c);
            const char *colon = strchr(c, ':');
            if (!colon) break;
            it->cond[it->ncond++].i = atoi(colon + 1);
            c = strchr(colon, ',');
            if (!c) break;
            c++;
        }
    }
    fclose(f);
    skin_fonts(s, dir);
    if (!s->ntabs) { skin_free(s); return NULL; }
    return s;
}

/* ---- values -------------------------------------------------------------------------------------------------------- */
static double ed_norm(v3_t *w, int p) {
    if (p < 0 || p >= NPARAMS) return 0;
    if (popup_is(p)) return w->open[p];
    return get_norm(w, p);
}
static int ed_option(v3_t *w, int p, int n) {   /* the option index a value stands for, among n */
    return n > 1 ? (int)lround(ed_norm(w, p) * (n - 1)) : ed_norm(w, p) > 0.5;
}
static int ed_shown(v3_t *w, const item_t *it) {
    for (int k = 0; k < it->ncond; k++) {
        int p = it->cond[k].p;
        if (p < 0 || p >= NPARAMS) return 0;
        int n = PARAMS[p].nopts > 1 ? PARAMS[p].nopts : 2;
        if (ed_option(w, p, n) != it->cond[k].i) return 0;
    }
    return 1;
}
static void ed_text(v3_t *w, const item_t *it, char *buf, size_t len) {
    char k2[96];
    if (it->text && it->param >= 0 && it->param < NPARAMS && PARAMS[it->param].dynamic_name
        && (snprintf(k2, sizeof k2, "%s_name", PARAMS[it->param].key), eng_get(w, k2, buf, len) > 0)) {
        /* a name the engine sets (vst2_wrap.c effGetParamName: MPC re-reads it into the Name label) */
    } else if (it->text) snprintf(buf, len, "%s", it->text);
    else if (it->param >= 0 && it->param < NPARAMS && !popup_is(it->param)) value_text(w, (uint32_t)it->param, get_norm(w, it->param), buf, len);
    else buf[0] = 0;
    if (it->upper) for (char *c = buf; *c; c++) *c = (char)toupper((unsigned char)*c);
}

/* ---- drawing ------------------------------------------------------------------------------------------------------- */
static void draw_image(cairo_t *cr, cairo_surface_t *im, double x, double y, double w, double h, double sy, double sh) {
    /* the source rows sy..sy+sh of im into the box x,y,w,h */
    if (!im || w <= 0 || h <= 0) return;
    double iw = cairo_image_surface_get_width(im);
    cairo_save(cr);
    cairo_rectangle(cr, x, y, w, h);
    cairo_clip(cr);
    cairo_translate(cr, x, y);
    cairo_scale(cr, w / iw, h / sh);
    cairo_set_source_surface(cr, im, 0, -sy);
    cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_GOOD);
    cairo_paint(cr);
    cairo_restore(cr);
}

static void draw_text(skin_t *s, cairo_t *cr, const item_t *it, const char *text) {
    if (!text[0]) return;
    cairo_save(cr);
    cairo_rectangle(cr, it->x, it->y, it->w, it->h);
    cairo_clip(cr);
    if (s->font[it->style]) cairo_set_font_face(cr, s->font[it->style]);
    else cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, it->style ? CAIRO_FONT_WEIGHT_BOLD : CAIRO_FONT_WEIGHT_NORMAL);
    cairo_set_font_size(cr, it->size * s->font_ratio[it->style]);
    cairo_font_extents_t fe;
    cairo_text_extents_t te;
    cairo_font_extents(cr, &fe);
    cairo_text_extents(cr, text, &te);
    double x = it->just == 1 ? it->x + (it->w - te.x_advance) / 2 : it->just == 2 ? it->x + it->w - te.x_advance : it->x;
    double y = it->y + it->h / 2.0 + (fe.ascent - fe.descent) / 2;
    uint32_t c = it->colour;
    cairo_set_source_rgba(cr, ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0, ((c >> 24) & 255) / 255.0);
    cairo_move_to(cr, x, y);
    cairo_show_text(cr, text);
    cairo_restore(cr);
}

static void draw_tabs(skin_t *s, cairo_t *cr, int cur) {
    cairo_set_source_rgb(cr, 0.06, 0.06, 0.08);
    cairo_rectangle(cr, 0, 0, s->w, TAB_H);
    cairo_fill(cr);
    double tw = (double)s->w / (s->ntabs > 0 ? s->ntabs : 1);
    for (int t = 0; t < s->ntabs; t++) {
        if (t == cur) {
            cairo_set_source_rgb(cr, 0.16, 0.16, 0.20);
            cairo_rectangle(cr, t * tw + 2, 4, tw - 4, TAB_H - 8);
            cairo_fill(cr);
            cairo_set_source_rgb(cr, 1.0, 0.61, 0.94);
            cairo_rectangle(cr, t * tw + 2, TAB_H - 6, tw - 4, 3);
            cairo_fill(cr);
        }
        item_t lab = { .x = (int)(t * tw), .y = 0, .w = (int)tw, .h = TAB_H, .just = 1, .style = 1, .size = 22,
                       .colour = t == cur ? 0xffffffffu : 0xff8a8a99u };
        draw_text(s, cr, &lab, s->tabname[t]);
    }
}

/* the page in skin pixels, the tab strip above it; cr is already scaled */
static void draw_page(skin_t *s, v3_t *w, cairo_t *cr, int tab) {
    cairo_set_source_rgb(cr, 0, 0, 0);
    cairo_paint(cr);
    draw_tabs(s, cr, tab);
    cairo_save(cr);
    cairo_translate(cr, 0, TAB_H);
    cairo_rectangle(cr, 0, 0, s->w, s->h);
    cairo_clip(cr);
    char text[256];
    for (int i = 0; i < s->nitems; i++) {
        const item_t *it = &s->items[i];
        if (it->tab != tab || it->kind == IT_HIT || !ed_shown(w, it)) continue;
        if (it->kind == IT_IMG && it->img >= 0 && s->img[it->img]) {
            cairo_surface_t *im = s->img[it->img];
            draw_image(cr, im, it->x, it->y, it->w, it->h, 0, cairo_image_surface_get_height(im));
        } else if (it->kind == IT_FILM && it->img >= 0 && s->img[it->img]) {
            /* frames are image height / count tall; knobs carry one more square frame than numFrames says (studio.py) */
            cairo_surface_t *im = s->img[it->img];
            int iw = cairo_image_surface_get_width(im), ih = cairo_image_surface_get_height(im);
            int n = it->frames > 0 ? it->frames : 127, nimg = ih == (n + 1) * iw ? n + 1 : n;
            double fh = (double)ih / nimg;
            int k = (int)lround(clamp01(ed_norm(w, it->param)) * (nimg - 1));
            draw_image(cr, im, it->x, it->y, it->w, it->h, k * fh, fh);
        } else if (it->kind == IT_BTN) {
            int on = it->param >= 0 && ed_option(w, it->param, it->n > 1 ? it->n : 1) == (it->n > 1 ? it->id : 1);
            int k = on ? it->img : it->img2;
            if (k >= 0 && s->img[k]) draw_image(cr, s->img[k], it->x, it->y, it->w, it->h, 0, cairo_image_surface_get_height(s->img[k]));
        } else if (it->kind == IT_LABEL) {
            ed_text(w, it, text, sizeof text);
            draw_text(s, cr, it, text);
        }
    }
    cairo_restore(cr);
}

/* a fingerprint of what the page shows: redraw only when it changes */
static uint64_t page_hash(skin_t *s, v3_t *w, int tab) {
    uint64_t h = 1469598103934665603ull;
    char text[256];
    for (int i = 0; i < s->nitems; i++) {
        const item_t *it = &s->items[i];
        if (it->tab != tab || it->kind == IT_HIT || it->kind == IT_IMG) { if (it->tab == tab && it->ncond) h = (h ^ (uint64_t)ed_shown(w, it)) * 1099511628211ull; continue; }
        if (!ed_shown(w, it)) { h = (h ^ 7) * 1099511628211ull; continue; }
        if (it->kind == IT_LABEL) {
            ed_text(w, it, text, sizeof text);
            for (const char *c = text; *c; c++) h = (h ^ (unsigned char)*c) * 1099511628211ull;
        } else {
            uint64_t v = (uint64_t)llround(ed_norm(w, it->param) * 1e6);
            h = (h ^ v) * 1099511628211ull;
        }
    }
    return h;
}

/* ---- the view ------------------------------------------------------------------------------------------------------ */
typedef struct {
    const PlugViewVtbl *vt;
    const EventHandlerVtbl *ev;
    const TimerHandlerVtbl *tm;
    uint32_t refs;
    v3_t *w;
    skin_t *skin;
    void *frame;
    void *loop;            /* IRunLoop, or NULL: our own thread */
    pthread_t thread;
    pthread_mutex_t lock;  /* the window and its size: our own thread's tick() against the host's onSize() */
    volatile int stop;
    int thread_on;
    Display *dpy;
    Window win;
    int width, height;     /* window pixels */
    double scale;
    cairo_surface_t *xs, *back;   /* the window, and the image the page is drawn into */
    int tab;
    uint64_t last_hash;
    int dirty;
    int drag_param, drag_steps, press_param;
    double drag_start_v, drag_y, drag_v;
} view_t;

#define VIEW(ptr, member) ((view_t *)((char *)(ptr) - offsetof(view_t, member)))

static void ui_set(view_t *v, int p, double val, int phase);

static int page_w(view_t *v) { return v->skin->w; }
static int page_h(view_t *v) { return v->skin->h + TAB_H; }

/* The page is drawn into an image the window's size, then copied to the window in one paint. Drawing the skin's images
 * straight onto the X surface would leave an uploaded copy cached on each of them, holding the X connection open past
 * removed(); only this backbuffer gets one, and view_detach() frees it first. */
static void redraw(view_t *v) {
    if (!v->xs) return;
    if (!v->back || cairo_image_surface_get_width(v->back) != v->width || cairo_image_surface_get_height(v->back) != v->height) {
        if (v->back) cairo_surface_destroy(v->back);
        v->back = cairo_image_surface_create(CAIRO_FORMAT_RGB24, v->width, v->height);
    }
    cairo_t *cr = cairo_create(v->back);
    cairo_set_source_rgb(cr, 0, 0, 0);
    cairo_paint(cr);
    double sx = (double)v->width / page_w(v), sy = (double)v->height / page_h(v);
    v->scale = sx < sy ? sx : sy;
    cairo_scale(cr, v->scale, v->scale);
    draw_page(v->skin, v->w, cr, v->tab);
    cairo_destroy(cr);
    cr = cairo_create(v->xs);
    cairo_set_source_surface(cr, v->back, 0, 0);
    cairo_set_operator(cr, CAIRO_OPERATOR_SOURCE);
    cairo_paint(cr);
    cairo_destroy(cr);
    cairo_surface_flush(v->xs);
    XFlush(v->dpy);
    v->dirty = 0;
}

static const item_t *hit_at(view_t *v, double px, double py) {
    for (int i = v->skin->nitems - 1; i >= 0; i--) {
        const item_t *it = &v->skin->items[i];
        if (it->tab != v->tab || it->kind != IT_HIT) continue;
        if (px < it->x || py < it->y || px >= it->x + it->w || py >= it->y + it->h) continue;
        if (ed_shown(v->w, it)) return it;
    }
    return NULL;
}

static int param_steps(int p) {
    const param_t *pp = &PARAMS[p];
    if (pp->nopts > 1) return pp->nopts - 1;
    if (pp->int_display && pp->max > pp->min) return (int)lroundf(pp->max - pp->min);
    return 0;
}

static void close_popups(view_t *v, int except) {
    for (int j = 0; j < NPARAMS; j++)
        if (j != except && popup_is(j) && v->w->open[j] > 0.5) { v->w->open[j] = 0; v->dirty = 1; }
}

static void press(view_t *v, double px, double py) {
    if (py < TAB_H) {
        int t = (int)(px / ((double)v->skin->w / v->skin->ntabs));
        if (t >= 0 && t < v->skin->ntabs && t != v->tab) { v->tab = t; close_popups(v, -1); v->dirty = 1; }
        return;
    }
    const item_t *it = hit_at(v, px, py - TAB_H);
    if (!it) { close_popups(v, -1); return; }
    int p = it->param;
    if (p < 0 || p >= NPARAMS) return;
    if (popup_is(p)) {   /* a popup field: its list opens over the page; one at a time */
        double now = v->w->open[p] > 0.5 ? 0 : 1;
        close_popups(v, p);
        v->w->open[p] = now;
        v->dirty = 1;
        return;
    }
    const param_t *pp = &PARAMS[p];
    if (it->mode == HIT_DRAG) {
        v->drag_param = p;
        v->drag_start_v = get_norm(v->w, p);
        v->drag_y = py;
        v->drag_steps = param_steps(p);
        v->drag_v = v->drag_start_v;
        ui_set(v, p, v->drag_start_v, 0);
        return;
    }
    if (it->mode == HIT_RADIO) {
        ui_set(v, p, it->n > 1 ? (double)it->id / (it->n - 1) : 0, 3);
        for (int j = 0; j < NPARAMS; j++)   /* an option picked closes its list (popup.h popup_picked) */
            if (PARAMS[j].popup_of == p && v->w->open[j] > 0.5) { v->w->open[j] = 0; v->dirty = 1; }
        return;
    }
    if (pp->momentary || pp->step_target >= 0) {   /* held while the button is */
        v->press_param = p;
        ui_set(v, p, 1, 0);
        return;
    }
    ui_set(v, p, get_norm(v->w, p) > 0.5 ? 0 : 1, 3);
}

static void motion(view_t *v, double py) {
    if (v->drag_param < 0) return;
    double val = clamp01(v->drag_start_v + (v->drag_y - py) / DRAG_PX);
    if (v->drag_steps > 0) val = round(val * v->drag_steps) / v->drag_steps;
    if (val == v->drag_v) return;
    v->drag_v = val;
    ui_set(v, v->drag_param, val, 1);
}

static void unpress(view_t *v) {
    if (v->drag_param >= 0) { ui_set(v, v->drag_param, v->drag_v, 2); v->drag_param = -1; }
    if (v->press_param >= 0) { ui_set(v, v->press_param, 0, 2); v->press_param = -1; }
}

static void wheel(view_t *v, double px, double py, int up) {
    if (py < TAB_H) return;
    const item_t *it = hit_at(v, px, py - TAB_H);
    if (!it || it->param < 0 || it->param >= NPARAMS || popup_is(it->param)) return;
    int p = it->param, steps = param_steps(p);
    if (it->mode != HIT_DRAG && steps == 0) return;
    double step = steps > 0 ? 1.0 / steps : 0.01, val = clamp01(get_norm(v->w, p) + (up ? step : -step));
    ui_set(v, p, val, 3);
}

static void handle_events(view_t *v) {
    if (!v->dpy) return;
    while (XPending(v->dpy)) {
        XEvent e;
        XNextEvent(v->dpy, &e);
        double s = v->scale > 0 ? v->scale : 1;
        switch (e.type) {
        case Expose: if (!e.xexpose.count) v->dirty = 1; break;
        case ConfigureNotify:
            if (e.xconfigure.width != v->width || e.xconfigure.height != v->height) {
                v->width = e.xconfigure.width; v->height = e.xconfigure.height;
                cairo_xlib_surface_set_size(v->xs, v->width, v->height);
                v->dirty = 1;
            }
            break;
        case ButtonPress:
            if (e.xbutton.button == 1) press(v, e.xbutton.x / s, e.xbutton.y / s);
            else if (e.xbutton.button == 4 || e.xbutton.button == 5) wheel(v, e.xbutton.x / s, e.xbutton.y / s, e.xbutton.button == 4);
            break;
        case ButtonRelease: if (e.xbutton.button == 1) unpress(v); break;
        case MotionNotify: motion(v, e.xmotion.y / s); break;
        default: break;
        }
    }
}

static void tick(view_t *v) {
    pthread_mutex_lock(&v->lock);
    handle_events(v);
    uint64_t h = page_hash(v->skin, v->w, v->tab);   /* once a tick: each one reads every value under the engine lock */
    if (v->dirty || h != v->last_hash) { redraw(v); v->last_hash = h; }
    pthread_mutex_unlock(&v->lock);
}

/* An edit from the window. phase: 0 begins a gesture, 1 moves it, 2 ends it, 3 is a whole one-shot edit. Parameters the host
 * automates go through the host (performEdit, then process()); readouts and list tiles, which the host can't set, go through
 * the queue process() drains, as does everything when there is no host run loop. */
static void ui_set(view_t *v, int p, double val, int phase) {
    v3_t *w = v->w;
    IComponentHandler *h = w->handler;
    int via_host = h && v->loop && is_param((uint32_t)p) && !PARAMS[p].string_display;
    if (via_host) {
        if (phase == 0 || phase == 3) h->v->beginEdit(h, (uint32_t)p);
        h->v->performEdit(h, (uint32_t)p, val);
        if (phase == 2 || phase == 3) h->v->endEdit(h, (uint32_t)p);
        w->hostval[p] = val;
    } else {
        unsigned head = __atomic_load_n(&w->uiq_head, __ATOMIC_RELAXED);
        if (head - __atomic_load_n(&w->uiq_tail, __ATOMIC_ACQUIRE) < UIQ) {
            w->uiq[head % UIQ].p = p;
            w->uiq[head % UIQ].v = val;
            w->hostval[p] = val;
            __atomic_store_n(&w->uiq_head, head + 1, __ATOMIC_RELEASE);
        }
    }
    v->dirty = 1;
}

/* ---- COM plumbing ---------------------------------------------------------------------------------------------------- */
static tresult view_query(view_t *v, const TUID iid, void **obj) {
    void *p = NULL;
    if (iid_eq(iid, iid_FUnknown) || iid_eq(iid, iid_IPlugView)) p = &v->vt;
    else if (iid_eq(iid, iid_IEventHandler)) p = &v->ev;
    else if (iid_eq(iid, iid_ITimerHandler)) p = &v->tm;
    if (!p) { *obj = NULL; return kNoInterface; }
    __atomic_add_fetch(&v->refs, 1, __ATOMIC_ACQ_REL);
    *obj = p;
    return kResultOk;
}
static void view_detach(view_t *v);
static uint32_t view_release(view_t *v) {
    uint32_t r = __atomic_sub_fetch(&v->refs, 1, __ATOMIC_ACQ_REL);
    if (!r) {
        view_detach(v);
        skin_free(v->skin);
        release(v->w);
        pthread_mutex_destroy(&v->lock);
        free(v);
    }
    return r;
}
#define VIEW_UNKNOWN(pre, member) \
    static tresult pre##_q(void *s, const TUID iid, void **o) { return view_query(VIEW(s, member), iid, o); } \
    static uint32_t pre##_ref(void *s) { return __atomic_add_fetch(&VIEW(s, member)->refs, 1, __ATOMIC_ACQ_REL); } \
    static uint32_t pre##_rel(void *s) { return view_release(VIEW(s, member)); }
VIEW_UNKNOWN(pv, vt)
VIEW_UNKNOWN(pe, ev)
VIEW_UNKNOWN(pt, tm)

static void ev_fd(void *s, int fd) { (void)fd; tick(VIEW(s, ev)); }
static void tm_timer(void *s) { tick(VIEW(s, tm)); }
static const EventHandlerVtbl ev_vtbl = { pe_q, pe_ref, pe_rel, ev_fd };
static const TimerHandlerVtbl tm_vtbl = { pt_q, pt_ref, pt_rel, tm_timer };

static void *own_loop(void *arg) {   /* no host run loop: events and the redraw timer on this thread */
    view_t *v = arg;
    struct pollfd pf = { ConnectionNumber(v->dpy), POLLIN, 0 };
    while (!v->stop) {
        poll(&pf, 1, 33);
        tick(v);
    }
    return NULL;
}

static tresult pv_platform(void *s, const char *type) { (void)s; return type && !strcmp(type, "X11EmbedWindowID") ? kResultOk : kResultFalse; }

static tresult pv_attached(void *s, void *parent, const char *type) {
    view_t *v = VIEW(s, vt);
    if (!type || strcmp(type, "X11EmbedWindowID") || v->dpy) return kResultFalse;
    /* Our connection is only ever used under v->lock, so it needs no Xlib locking of its own. XInitThreads() is for Xlib's
     * shared state; libX11 1.8 and later call it when it loads, which makes this a no-op there. */
    XInitThreads();
    v->dpy = XOpenDisplay(NULL);
    if (!v->dpy) return kResultFalse;
    int scr = DefaultScreen(v->dpy);
    v->win = XCreateSimpleWindow(v->dpy, (Window)(uintptr_t)parent, 0, 0, (unsigned)v->width, (unsigned)v->height, 0, 0,
                                 BlackPixel(v->dpy, scr));
    XSelectInput(v->dpy, v->win, ExposureMask | ButtonPressMask | ButtonReleaseMask | PointerMotionMask | StructureNotifyMask);
    XMapWindow(v->dpy, v->win);
    v->xs = cairo_xlib_surface_create(v->dpy, v->win, DefaultVisual(v->dpy, scr), v->width, v->height);
    XFlush(v->dpy);
    v->dirty = 1;
    FUnknown *fr = v->frame;
    void *loop = NULL;
    if (fr && fr->v->queryInterface(fr, iid_IRunLoop, &loop) == kResultOk && loop) {
        v->loop = loop;
        const RunLoopVtbl *rl = *(const RunLoopVtbl **)loop;
        rl->registerEventHandler(loop, &v->ev, ConnectionNumber(v->dpy));
        rl->registerTimer(loop, &v->tm, 33);
    } else {
        v->stop = 0;
        if (pthread_create(&v->thread, NULL, own_loop, v)) v->stop = 1;
        else v->thread_on = 1;
    }
    return kResultOk;
}

static void view_detach(view_t *v) {
    if (v->loop) {
        const RunLoopVtbl *rl = *(const RunLoopVtbl **)v->loop;
        rl->unregisterTimer(v->loop, &v->tm);
        rl->unregisterEventHandler(v->loop, &v->ev);
        ((FUnknown *)v->loop)->v->release(v->loop);
        v->loop = NULL;
    }
    if (v->thread_on) { v->stop = 1; pthread_join(v->thread, NULL); v->thread_on = 0; }
    cairo_device_t *dev = v->xs ? cairo_device_reference(cairo_surface_get_device(v->xs)) : NULL;
    if (v->back) { cairo_surface_destroy(v->back); v->back = NULL; }
    if (v->xs) { cairo_surface_destroy(v->xs); v->xs = NULL; }
    if (dev) { cairo_device_finish(dev); cairo_device_destroy(dev); }   /* cairo's per-connection state, before the connection goes */
    if (v->dpy) {
        XDestroyWindow(v->dpy, v->win);
        XCloseDisplay(v->dpy);
        v->dpy = NULL;
    }
    close_popups(v, -1);
}

static tresult pv_removed(void *s) { view_detach(VIEW(s, vt)); return kResultOk; }
static tresult pv_wheel(void *s, float d) { (void)s; (void)d; return kResultFalse; }
static tresult pv_key(void *s, char16 k, int16_t c, int16_t m) { (void)s; (void)k; (void)c; (void)m; return kResultFalse; }
static tresult pv_get_size(void *s, ViewRect *r) {
    view_t *v = VIEW(s, vt);
    r->left = r->top = 0; r->right = v->width; r->bottom = v->height;
    return kResultOk;
}
static tresult pv_on_size(void *s, ViewRect *r) {
    view_t *v = VIEW(s, vt);
    pthread_mutex_lock(&v->lock);
    v->width = r->right - r->left;
    v->height = r->bottom - r->top;
    if (v->dpy) {
        XResizeWindow(v->dpy, v->win, (unsigned)v->width, (unsigned)v->height);
        cairo_xlib_surface_set_size(v->xs, v->width, v->height);
        v->dirty = 1;
        XFlush(v->dpy);
    }
    pthread_mutex_unlock(&v->lock);
    return kResultOk;
}
static tresult pv_focus(void *s, uint8_t f) { (void)s; (void)f; return kResultOk; }
static tresult pv_set_frame(void *s, void *frame) { VIEW(s, vt)->frame = frame; return kResultOk; }
static tresult pv_can_resize(void *s) { (void)s; return kResultOk; }
static tresult pv_constraint(void *s, ViewRect *r) {   /* keep the page's shape, at least a quarter of its size */
    view_t *v = VIEW(s, vt);
    int w = r->right - r->left;
    if (w < page_w(v) / 4) w = page_w(v) / 4;
    r->right = r->left + w;
    r->bottom = r->top + (int)lround((double)w * page_h(v) / page_w(v));
    return kResultOk;
}
static const PlugViewVtbl pv_vtbl = {
    pv_q, pv_ref, pv_rel, pv_platform, pv_attached, pv_removed, pv_wheel, pv_key, pv_key,
    pv_get_size, pv_on_size, pv_focus, pv_set_frame, pv_can_resize, pv_constraint,
};

static void *editor_create(v3_t *w, const char *name) {
    if (name && strcmp(name, "editor")) return NULL;
    skin_t *s = skin_load();
    if (!s) return NULL;
    view_t *v = calloc(1, sizeof *v);
    if (!v) { skin_free(s); return NULL; }
    pthread_mutexattr_t ma;   /* recursive: a host may call onSize() back from inside an edit made in tick() */
    pthread_mutexattr_init(&ma);
    pthread_mutexattr_settype(&ma, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&v->lock, &ma);
    pthread_mutexattr_destroy(&ma);
    v->vt = &pv_vtbl; v->ev = &ev_vtbl; v->tm = &tm_vtbl;
    v->refs = 1;
    v->w = w;
    add_ref(w);
    v->skin = s;
    v->width = page_w(v);
    v->height = page_h(v);
    v->scale = 1;
    v->drag_param = v->press_param = -1;
    return &v->vt;
}

/* Test hook (tools/vst3_host_test.c): render page `tab` of the instance whose IComponent is `component` into a PNG, as the
 * window would show it now. Returns 1 on success, 0 without a skin. */
__attribute__((visibility("default"))) int mpc_vst3_snapshot(void *component, int tab, const char *png) {
    v3_t *w = FROM(component, comp);
    skin_t *s = skin_load();
    if (!s) return 0;
    if (tab < 0 || tab >= s->ntabs) { skin_free(s); return 0; }
    cairo_surface_t *im = cairo_image_surface_create(CAIRO_FORMAT_RGB24, s->w, s->h + TAB_H);
    cairo_t *cr = cairo_create(im);
    draw_page(s, w, cr, tab);
    cairo_destroy(cr);
    int ok = cairo_surface_write_to_png(im, png) == CAIRO_STATUS_SUCCESS;
    cairo_surface_destroy(im);
    skin_free(s);
    return ok;
}
