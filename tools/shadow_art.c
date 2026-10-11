/* shadow_art.c — export MPC plugin-skin artwork drawn by force-shadow's own
 * offline renderer (tools/render_conf_preview.c), so a skin generated from a
 * shadow_page.conf is pixel-identical to the Force Shadow page it came from.
 *
 * Build (x86 host is fine; the renderer is vendored, see tools/vendor/force-shadow/README.md):
 *   gcc -O2 -Itools/vendor/force-shadow/tools -o shadow_art tools/shadow_art.c -lm
 *
 * Reads commands on stdin, one per line, fields separated by '|':
 *   clear|RRGGBB                      fill the whole 1280x800 canvas
 *   frame|x|y|w|h|TITLE               titled frame box
 *   frameblank|x|y|w|h                 frame box, no title text (a real TrueType font draws the
 *                                       title afterward via PIL -- see shadow_skin.py's TITLE_FONT)
 *   text|cx|y|scale|RRGGBB|TEXT       centred text (baked 9x9 font; uppercase only)
 *   knob|cx|cy|r|pct                  knob body: ring, face, pointer dot (no label/value)
 *   pill|cx|cy|on                     toggle pill (no label)
 *   button|cx|cy|RRGGBB|LABEL         push button
 *   boxbtn|x|y|w|h|RRGGBB|LABEL|SCALE sized button. Play/Stop are a triangle and a square;
 *                                     any other label is the 5x7 font, fitted, in the button-text colour
 *   seg|x|y|w|h|RRGGBB|RRGGBB|LABEL   one enum segment: fill colour, text colour
 *   crop|out.ppm|x|y|w|h              write a region of the canvas
 *   strip|out.ppm|r|frames|RRGGBB     vertical knob filmstrip (frames x (2r+10)^2) on a bg colour
 *   theme|conf                        apply a conf's style=/theme_* lines (render_conf_preview's load_conf)
 *   readout|cx|cy|w|h|LABEL           readout box + label, no text (MPC draws the live value)
 *   stepper|cx|cy|w|h|LABEL           < box > stepper + label, no text
 *   dotreadout|cx|cy|w|h|LABEL        dot-matrix LCD readout (JV-880-style), same "no text" convention
 *   dotstepper|cx|cy|w|h|LABEL        dot-matrix LCD stepper, same "no text" convention
 *   tile|x|y|w|h|FILL|BORDER|bw       list tile: fill, then a border of bw px (0 = the plate-line rules)
 *   nmark|w|h|FILL|ACCENT|radius|alpha  pattern hit at 0,0: flat cell, rounded bar blended by alpha 0..255
 *   sstrip|out.ppm|w|h|frames|v|RRGGBB  slider filmstrip (frames x w*h, stacked vertically); v=1 vertical
 */
#define main render_conf_preview_main
#include "render_conf_preview.c"
#undef main

static void write_region(FILE *f, int x, int y, int w, int h) {
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++) {
            int px = x + i, py = y + j;
            unsigned char c[3] = {0, 0, 0};
            if (px >= 0 && px < LAND_W && py >= 0 && py < LAND_H) memcpy(c, canvas[py][px], 3);
            fwrite(c, 1, 3, f);
        }
}

static void crop(const char *path, int x, int y, int w, int h) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    write_region(f, x, y, w, h);
    fclose(f);
}

/* frame_box_blank() lives in render_conf_preview.c now (frame_box() minus its baked title text,
 * sharing frame_border() with frame_box() so the TD3 style force-acid uses is handled too --
 * this file's own stub only covered the non-TD3 branch and has been dropped in favour of it). */

static void knob_body(int cx, int cy, int r, int pct) {
    /* widget_knob() minus its label/value text (those come from the skin). A dotted arc instead
     * of a solid ring, closer to the JV-880 shadow mockups' "dark knob, green dotted arc, small
     * pointer" look (docs/SHADOW-GUI-PROPOSAL.md) -- shadow_art.c's own addition (not shared with
     * force-shadow's real on-device renderer, which keeps its plain ring). Dot count scales with
     * radius so small/large knobs both read as a ring, not a sparse/crowded one. */
    int ndots = r < 24 ? 16 : (r < 36 ? 22 : 28);
    int dotr = r < 24 ? 1 : 2;
    for (int i = 0; i < ndots; i++) {
        double a = 2 * M_PI * i / ndots - M_PI / 2;
        int dx = cx + (int)lround((r + 4) * cos(a));
        int dy = cy + (int)lround((r + 4) * sin(a));
        fill_circle(dx, dy, dotr, KNOB_RING);
    }
    fill_circle(cx, cy, r, KNOB_FACE);
    int dx, dy;
    knob_dot(cx, cy, r, pct, &dx, &dy);
    fill_circle(dx, dy, r / 7 + 2, KNOB_DOT_COLOR);
}

static void pill(int cx, int cy, int on) {
    /* widget_toggle() minus its label */
    int pw = 51, ph = 27;
    fill_rect(cx - pw / 2, cy - ph / 2, pw, ph, 0x050403);
    draw_ring(cx - pw / 2 + ph / 2, cy, ph / 2 - 2, 1, PLATE_LINE);
    int lx = on ? (cx + pw / 2 - ph / 2) : (cx - pw / 2 + ph / 2);
    fill_circle(lx, cy, ph / 2 - 4, on ? ACCENT_HI : 0x4c473d);
}

static void clear(uint32_t c) {
    fill_rect(0, 0, LAND_W, LAND_H, c);
}

/* Self-contained dot-matrix readout/stepper for use INSIDE a plugin's own
 * canvas, unlike widget_readout()/widget_stepper()'s G_DSP branch (only
 * force_shadow.c's outer chrome, cy < TOPBAR_H, ever hits that). MPC skins
 * have no such chrome band -- our own "topbar" IS part of the tab -- so
 * this bakes the same bezel + dot_cell_fit() look at any position, gated
 * only by theme_*'s dot-matrix colours (set regardless of topbar_style so
 * this works even where render_conf_preview.c's own G_DSP stays off). */
static void dot_readout(int cx, int cy, int w, int h, const char *label) {
    int x0 = cx - w / 2, y0 = cy - h / 2;
    if (label[0]) draw_text(x0, y0 - 22, label, 1.5f, INK_DIM);
    fill_rr(x0 - 4, y0 - 4, w + 8, h + 8, 8, DSP_BEZEL);
    dot_cell_fit(x0, y0, w, h, "", DSP_CELL, DSP_OFF, DSP_INK);
}

static void dot_stepper(int cx, int cy, int w, int h, const char *label) {
    int x0 = cx - w / 2, y0 = cy - h / 2;
    if (label[0]) draw_text(x0, y0 - 22, label, 1.5f, INK_DIM);
    fill_rr(x0 - 4, y0 - 4, w + 8, h + 8, 8, DSP_BEZEL);
    fill_rr(x0, y0, h, h, 5, DSP_BEZEL);
    fill_rr(x0 + w - h, y0, h, h, 5, DSP_BEZEL);
    draw_arrow(x0 + h / 2, cy, h / 4, -1, DSP_BG);
    draw_arrow(x0 + w - h / 2, cy, h / 4, 1, DSP_BG);
    int bx = x0 + h + 3, bw = w - 2 * h - 6;
    dot_cell_fit(bx, y0, bw, h, "", DSP_CELL, DSP_OFF, DSP_INK);
}

static void strip(const char *path, int r, int frames, uint32_t bg) {
    int s = 2 * r + 10, c = s / 2;
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    fprintf(f, "P6\n%d %d\n255\n", s, s * frames);
    for (int k = 0; k < frames; k++) {
        fill_rect(0, 0, s, s, bg);
        knob_body(c, c, r, (int)lround(100.0 * k / (frames - 1)));
        write_region(f, 0, 0, s, s);
    }
    fclose(f);
}

/* Slider in the knob's palette: dark well, accent fill up to the value, knob-face thumb. */
static void slider_body(int x, int y, int w, int h, int vert, double t) {
    fill_rr(x, y, w, h, (vert ? w : h) / 2, 0x050403);
    int pad = 4, th = vert ? w - 2 * pad : h - 2 * pad;           /* thumb size */
    if (vert) {
        int travel = h - 2 * pad - th, ty = y + pad + (int)lround((1.0 - t) * travel);
        fill_rr(x + pad + (w - 2 * pad) / 2 - 3, ty + th / 2, 6, y + h - pad - (ty + th / 2), 3, KNOB_DOT_COLOR);
        fill_circle(x + w / 2, ty + th / 2, th / 2, KNOB_FACE);
        draw_ring(x + w / 2, ty + th / 2, th / 2 + 1, 2, KNOB_RING);
    } else {
        int travel = w - 2 * pad - th, tx = x + pad + (int)lround(t * travel);
        fill_rr(x + pad, y + h / 2 - 3, tx + th / 2 - (x + pad), 6, 3, KNOB_DOT_COLOR);
        fill_circle(tx + th / 2, y + h / 2, th / 2, KNOB_FACE);
        draw_ring(tx + th / 2, y + h / 2, th / 2 + 1, 2, KNOB_RING);
    }
}

static void sstrip(const char *path, int w, int h, int frames, int vert, uint32_t bg) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); exit(1); }
    fprintf(f, "P6\n%d %d\n255\n", w, h * frames);
    for (int k = 0; k < frames; k++) {
        fill_rect(0, 0, w + 4, h + 4, bg);
        slider_body(0, 0, w, h, vert, (double)k / (frames - 1));
        write_region(f, 0, 0, w, h);
    }
    fclose(f);
}

/* Transport marks, instead of the 9x9 font blown up to button size. */
static void play_glyph(int x, int y, int w, int h, uint32_t color) {
    int side = h / 2;
    if (side < 16) side = 16;
    int tw = side * 4 / 5;
    int x0 = x + (w - tw) / 2 + tw / 10;
    int cy = y + h / 2;
    for (int c = 0; c < tw; c++) {
        int half = (side / 2) * (tw - 1 - c) / (tw > 1 ? tw - 1 : 1);
        fill_rect(x0 + c, cy - half, 1, half * 2 + 1, color);
    }
}

static void stop_glyph(int x, int y, int w, int h, uint32_t color) {
    int s = h / 2;
    if (s < 14) s = 14;
    fill_rect(x + (w - s) / 2, y + (h - s) / 2, s, s, color);
}

/* Tight 5x7 label. The 9x9 font's cell is wider than its glyph, so a short word
 * blown up to button size reads as "C o p y". */
static void dot_label(int x, int y, int w, int h, const char *s, uint32_t ink) {
    int n = s ? (int)strlen(s) : 0;
    if (n <= 0 || n > 16) return;
    int p = 6;
    while (p > 2 && (n * 6 * p - p > w - 16 || 7 * p > h - 12)) p--;
    int tw = n * 6 * p - p, th = 7 * p;
    int ox = x + (w - tw) / 2, oy = y + (h - th) / 2;
    int dot = p > 2 ? p - 1 : p;
    for (int i = 0; i < n; i++) {
        const uint8_t *g = dot_glyph(s[i]);
        if (!g) continue;
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 5; c++)
                if (g[r] & (16 >> c))
                    fill_rect(ox + (i * 6 + c) * p, oy + r * p, dot, dot, ink);
    }
}

/* A pattern hit: the cell, then a rounded bar inset from its border. alpha 0..255
 * blends the accent onto the cell fill, so a quiet hit reads as transparent.
 * Coverage of a rounded rect: the shared fill_rr() does not cut a radius this small. */
static int rr_cover(int i, int j, int w, int h, int r) {
    if (r <= 0) return 255;
    float px = i + 0.5f, py = j + 0.5f, dx = 0, dy = 0;
    if (px < r) dx = r - px;
    else if (px > w - r) dx = px - (w - r);
    if (py < r) dy = r - py;
    else if (py > h - r) dy = py - (h - r);
    float d = sqrtf(dx * dx + dy * dy);
    if (d <= r - 0.5f) return 255;
    if (d >= r + 0.5f) return 0;
    return (int)((r + 0.5f - d) * 255);
}

static void fill_rr_blend(int x, int y, int w, int h, int r, uint32_t color, int a) {
    if (w <= 0 || h <= 0 || a <= 0) return;
    if (r * 2 > h) r = h / 2;
    if (r * 2 > w) r = w / 2;
    int cr = (color >> 16) & 255, cg = (color >> 8) & 255, cb = color & 255;
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++) {
            int cov = rr_cover(i, j, w, h, r);
            if (cov <= 0) continue;
            int aa = a * cov / 255;
            int px = x + i, py = y + j;
            if (aa <= 0 || px < 0 || py < 0 || px >= LAND_W || py >= LAND_H) continue;
            unsigned char *p = canvas[py][px];
            p[0] = (unsigned char)((p[0] * (255 - aa) + cr * aa) / 255);
            p[1] = (unsigned char)((p[1] * (255 - aa) + cg * aa) / 255);
            p[2] = (unsigned char)((p[2] * (255 - aa) + cb * aa) / 255);
        }
}

static void note_mark(int w, int h, uint32_t fill, uint32_t accent, int rad, int alpha) {
    fill_rect(0, 0, w, h, fill);
    int inset = 2;
    if (alpha > 0 && w > inset * 2 && h > inset * 2)
        fill_rr_blend(inset, inset, w - 2 * inset, h - 2 * inset, rad, accent, alpha);
}

#define HEX(s) ((uint32_t)strtoul((s), NULL, 16))

int main(void) {
    char line[512], *a[10];
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        int n = 0;
        for (char *t = strtok(line, "|"); t && n < 10; t = strtok(NULL, "|")) a[n++] = t;
        if (!n) continue;
        const char *op = a[0];
        if (!strcmp(op, "clear") && n == 2) clear(HEX(a[1]));
        else if (!strcmp(op, "frame") && n == 6) frame_box(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]), a[5]);
        else if (!strcmp(op, "frameblank") && n == 5) frame_box_blank(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]));
        else if (!strcmp(op, "text") && n == 6) draw_text_c(atoi(a[1]), atoi(a[2]), a[5], (float)atof(a[3]), HEX(a[4]));
        else if (!strcmp(op, "knob") && n == 5) knob_body(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]));
        else if (!strcmp(op, "pill") && n == 4) pill(atoi(a[1]), atoi(a[2]), atoi(a[3]));
        else if (!strcmp(op, "button") && n == 5) widget_button(atoi(a[1]), atoi(a[2]), a[4], HEX(a[3]));
        else if (!strcmp(op, "boxbtn") && n == 8) {
            int x = atoi(a[1]), y = atoi(a[2]), w = atoi(a[3]), h = atoi(a[4]);
            float scale = (float)atof(a[7]);
            int rad = h / 8;
            if (rad < 8) rad = 8;
            if (rad > 18) rad = 18;
            fill_rr(x, y, w, h, rad, HEX(a[5]));
            if (!strcmp(a[6], "Play")) play_glyph(x, y, w, h, 0x141210);
            else if (!strcmp(a[6], "Stop")) stop_glyph(x, y, w, h, 0x141210);
            else if (a[6][0] && strcmp(a[6], " ")) dot_label(x, y, w, h, a[6], 0x141210);
            (void)scale;
        }
        else if (!strcmp(op, "seg") && n == 8) {
            int x = atoi(a[1]), y = atoi(a[2]), w = atoi(a[3]), h = atoi(a[4]);
            fill_rect(x, y, w, h, HEX(a[5]));
            draw_text_c(x + w / 2, y + h / 2 - 6, a[7], 1.15f, HEX(a[6]));   /* was 1.5f, see shadow_skin.py's LABEL_SCALE */
        }
        else if (!strcmp(op, "theme") && n == 2) load_conf(a[1]);
        else if (!strcmp(op, "readout") && (n == 6 || n == 7)) widget_readout(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]), a[5][0] == '-' ? "" : a[5], "");
        else if (!strcmp(op, "stepper") && (n == 6 || n == 7)) widget_stepper(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]), a[5][0] == '-' ? "" : a[5], "");
        else if (!strcmp(op, "dotreadout") && (n == 6 || n == 7)) dot_readout(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]), a[5][0] == '-' ? "" : a[5]);
        else if (!strcmp(op, "dotstepper") && (n == 6 || n == 7)) dot_stepper(atoi(a[1]), atoi(a[2]), atoi(a[3]), atoi(a[4]), a[5][0] == '-' ? "" : a[5]);
        else if (!strcmp(op, "tile") && n == 8) {
            int x = atoi(a[1]), y = atoi(a[2]), w = atoi(a[3]), h = atoi(a[4]), bw = atoi(a[7]);
            fill_rect(x, y, w, h, HEX(a[5]));
            if (bw > 0) {
                fill_rect(x, y, w, bw, HEX(a[6])); fill_rect(x, y + h - bw, w, bw, HEX(a[6]));
                fill_rect(x, y, bw, h, HEX(a[6])); fill_rect(x + w - bw, y, bw, h, HEX(a[6]));
            } else {
                fill_rect(x, y, w, 1, PLATE_LINE); fill_rect(x, y + h - 1, w, 1, PLATE_LINE);
            }
        }
        else if (!strcmp(op, "nmark") && n == 7) note_mark(atoi(a[1]), atoi(a[2]), HEX(a[3]), HEX(a[4]), atoi(a[5]), atoi(a[6]));
        else if (!strcmp(op, "crop") && n == 6) crop(a[1], atoi(a[2]), atoi(a[3]), atoi(a[4]), atoi(a[5]));
        else if (!strcmp(op, "sstrip") && n == 7) sstrip(a[1], atoi(a[2]), atoi(a[3]), atoi(a[4]), atoi(a[5]), HEX(a[6]));
        else if (!strcmp(op, "strip") && n == 5) strip(a[1], atoi(a[2]), atoi(a[3]), HEX(a[4]));
        else { fprintf(stderr, "shadow_art: bad command: %s (%d fields)\n", op, n); return 1; }
    }
    return 0;
}
