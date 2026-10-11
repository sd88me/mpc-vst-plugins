/* Dev dump: gcc -std=gnu11 -Wall -Wextra -o /tmp/mxdump src/dump.c src/mxgrp.c -lm && /tmp/mxdump file.mxgrp */
#include "mxgrp.h"
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    int bad = 0;
    for (int a = 1; a < argc; a++) {
        FILE *f = fopen(argv[a], "rb");
        if (!f) { perror(argv[a]); bad++; continue; }
        fseek(f, 0, SEEK_END);
        long n = ftell(f);
        rewind(f);
        uint8_t *d = malloc((size_t)n);
        if (!d || fread(d, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(d); bad++; continue; }
        fclose(f);
        MxGroup g;
        if (mx_parse(d, (int)n, &g) != 0) {
            printf("FAIL %s\n", argv[a]);
            bad++;
            free(d);
            continue;
        }
        printf("== %s  group \"%s\"  pads %d  groupfx [%s]\n", argv[a], g.name, g.npad, g.group_fx);
        for (int i = 0; i < g.npad; i++) {
            MxPad *p = &g.pad[i];
            printf("  %2d %-16s src %d gain %.3f pan %.2f tune %.2f start %d end %d loop %d\n",
                   i, p->name, p->src, p->gain, p->pan, p->tune, p->start, p->end, p->loop);
            if (p->sample[0]) printf("      %s\n", p->sample);
            if (p->ns) {
                printf("      synth");
                for (int k = 0; k < p->ns; k++) printf(" %.3f", p->sp[k]);
                printf("\n");
            }
            for (int k = 0; k < p->nfx; k++) {
                printf("      fx %s", p->fx[k].name);
                for (int t = 0; t < p->fx[k].n; t++) printf(" %.3f", p->fx[k].p[t]);
                printf("\n");
            }
            printf("      chain %s\n", p->chain);
            if (p->nchoke) {
                printf("      choke");
                for (int c = 0; c < p->nchoke; c++) printf(" %d", p->choke[c]);
                printf("\n");
            }
        }
        for (int i = 0; i < g.ngfx; i++) {
            printf("  group %s", g.gfx[i].name);
            for (int t = 0; t < g.gfx[i].n; t++) printf(" %.3f", g.gfx[i].p[t]);
            printf("\n");
        }
        free(d);
    }
    return bad ? 1 : 0;
}
