/* Popup "open" flags for any wrapper (wrapper/vst2_wrap.c, or a port's own hand-written one).
 * A layout `popup` widget needs a hidden "<key>__open" param (params.h: popup_of = the enum it opens).
 * The flag lives in the wrapper only: never sent to the engine, never saved in the chunk.
 * Include after params.h. Usage:
 *   setParameter:  if (popup_set(w->open, i, n)) { if (w->open[i] > 0.5f) popup_close_others(w->open, w->holdFrames, i); return; }
 *                                                                 before anything else
 *                  ... set the value ...
 *                  if (!nudge) popup_picked(w->open, w->holdFrames, i);   exact option picked
 *   getParameter:  if (popup_is(i)) return w->open[i];
 *   chunk, engine polling: skip popup_is(i) params.
 *   processReplacing already reports holdFrames[] flags to the host with audioMasterAutomate(i, 0). */
#ifndef MPC_POPUP_H
#define MPC_POPUP_H

static inline int popup_is(int i) { return PARAMS[i].popup_of >= 0; }

/* A popup field tapped: show/hide its option list (skin IndexedEnabling). 1 if i is a popup flag. */
static inline int popup_set(float *open, int i, float n) {
    if (!popup_is(i)) return 0;
    open[i] = n > 0.5f ? 1.0f : 0.0f;
    return 1;
}

/* A popup flag was just opened: every other open list closes (two lists on screen cover each other, and the big ones cover
 * the page). The host hears "open = 0" from processReplacing via holdFrames[]. */
static inline void popup_close_others(float *open, volatile int *holdFrames, int i) {
    for (int j = 0; j < NPARAMS; j++)
        if (j != i && PARAMS[j].popup_of >= 0 && open[j] > 0.5f) { open[j] = 0; holdFrames[j] = 1; }
}

/* An option of param i picked exactly (a list button). A Q-Link nudge lands between options and
 * must not call this, so turning the knob leaves the list open. Closes i's open popup; the host
 * hears "open = 0" from processReplacing via holdFrames[], not from inside its own setParameter call. */
static inline void popup_picked(float *open, volatile int *holdFrames, int i) {
    for (int j = 0; j < NPARAMS; j++)
        if (PARAMS[j].popup_of == i && open[j] > 0.5f) { open[j] = 0; holdFrames[j] = 1; }
}

#endif
