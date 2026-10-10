/* Offline check against the two factory kits. Not part of the plugin build. */
#include "play.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static float rms_note(PlayKit *k, int note, int blocks) {
    play_note(k, note, 110);
    double acc = 0;
    int n = 0;
    int16_t buf[256];
    for (int b = 0; b < blocks; b++) {
        play_render(k, buf, 128, 0.8f, 1);
        for (int i = 0; i < 128; i++) {
            float s = buf[2 * i] / 32768.f;
            acc += (double)s * s;
            n++;
        }
    }
    return sqrtf((float)(acc / n));
}

static int fail(const char *m) { printf("FAIL %s\n", m); return 1; }

int main(void) {
    const char *a = "/Users/Shared/Maschine 2 Factory Library Library/Groups/Kits/808 Kit.mxgrp";
    const char *b = "/Users/Shared/Maschine 2 Factory Library Library/Groups/Kits/3l3ktr0 Kit.mxgrp";
    int bad = 0;
    PlayKit *k = play_load(a);
    if (!k) return fail("808 load");
    printf("808 status: %s\n", play_status(k));
    if (play_npad(k) != 16) bad += fail("808 pads");
    if (!strstr(play_status(k), "16 samples")) bad += fail("808 samples");
    if (strcmp(play_pad_name(k, 0), "Kick 808 1")) bad += fail("808 name");
    if (play_pad_tint("Kick 808 1") != 1 || play_pad_tint("Snare") != 2 || play_pad_tint("Closed HH") != 3 ||
        play_pad_tint("OpenHH") != 3 || play_pad_tint("Shaker") != 3 || play_pad_tint("Woodblock") != 4 ||
        play_pad_tint("Tamb") != 4 || play_pad_tint("Tom") != 5 || play_pad_tint("Chord") != 0 ||
        play_pad_tint("Synth") != 0) bad += fail("pad tint");
    if (!strstr(play_info(k), "sample")) bad += fail("808 info");
    float kick = rms_note(k, 48, 80); /* chromatic C, bottom-left */
    printf("  kick rms %.4f  info %s\n", kick, play_info(k));
    if (kick < 0.02f) bad += fail("808 kick silent");
    if (strstr(play_info(k), "Chorus")) bad += fail("808 note 48 not the kick");
    float crash = rms_note(k, 60, 120); /* pad 13, top row, chorus */
    printf("  crash rms %.4f  info %s\n", crash, play_info(k));
    if (crash < 0.01f) bad += fail("808 crash silent");
    if (!strstr(play_info(k), "Chorus")) bad += fail("808 chorus");
    play_note(k, 51, 120); /* open hat, pad 4 */
    play_render(k, (int16_t[256]){0}, 128, 0.8f, 1);
    if (!play_pad_active(k, 3)) bad += fail("open hat not active");
    play_note(k, 50, 120); /* closed chokes open */
    play_render(k, (int16_t[256]){0}, 128, 0.8f, 1);
    if (play_pad_active(k, 3)) bad += fail("open hat not choked");
    printf("  patterns %d\n", play_npat(k));
    if (play_npat(k) < 2) bad += fail("808 pattern count");
    if (strcmp(play_pat_name(k, 0), "Pattern 1")) bad += fail("808 pattern name");
        if (play_pat_events(k, 0) < 20) bad += fail("808 pattern events");
        {
            char text[8192];
            int nev = play_pattern_text(k, 0, text, sizeof text);
            printf("%s", text);
            if (nev < 20 || !strstr(text, "note\ttick\tvelocity")) bad += fail("808 pattern text");
            if (!strstr(text, "\n48\t960\t")) bad += fail("808 kick not on beat 2");
            if (!strstr(text, "\n53\t960\t")) bad += fail("808 snare not on the backbeat");
            if (strstr(text, "\n60\t1440\t")) bad += fail("808 silent crash was played");
            if (!strstr(text, "# length: 7680\n")) bad += fail("808 pattern length");
            uint8_t mid[8192];
            int nb = play_pattern_midi(k, 0, 120, mid, (int)sizeof mid);
            int kick = 0;
            if (nb < 22 || memcmp(mid, "MThd", 4) != 0) bad += fail("808 midi header");
            else for (int i = 0; i + 2 < nb; i++) if (mid[i] == 0x90 && mid[i + 1] == 48) kick = 1;
            if (!kick) bad += fail("808 midi kick");
            uint16_t cols[16];
            play_pat_columns(k, 0, 16, cols);
            if ((cols[0] & (1u << 2)) == 0) bad += fail("808 kick column");
            if ((cols[5] & (1u << 2)) == 0) bad += fail("808 snare column");
            uint8_t lv[16][16];
            play_pat_levels(k, 0, 16, lv);
            if (lv[0][2] == 0) bad += fail("808 kick velocity");
            if (play_vel_band(0) != 0 || play_vel_band(20) != 1 || play_vel_band(60) != 2 ||
                play_vel_band(90) != 3 || play_vel_band(120) != 4) bad += fail("velocity bands");
            if (play_vel_band(lv[0][2]) < 1) bad += fail("808 kick band");
            play_set_bpm(k, 120);
            play_preview(k, 0, 1);
            int saw_on = 0, saw_off = 0;
            for (int b = 0; b < 220 && (!saw_on || !saw_off); b++) {
                play_render(k, (int16_t[256]){0}, 128, 0.8f, 1);
                uint8_t ev[64][4];
                int n = play_midi_out(k, ev, 64);
                for (int i = 0; i < n; i++) {
                    if (ev[i][1] == 0x90 && ev[i][2] == 48) saw_on = 1;
                    if (ev[i][1] == 0x80 && ev[i][2] == 48) saw_off = 1;
                }
            }
            if (!saw_on) bad += fail("808 midi out kick");
            if (!saw_off) bad += fail("808 midi out kick off");
            play_preview(k, 0, 0);
        }
    play_set_bpm(k, 120);
    play_preview(k, 0, 1);
    {
        double acc = 0; int n = 0; int16_t buf[256];
        for (int b = 0; b < 400; b++) {
            play_render(k, buf, 128, 0.8f, 1);
            for (int i = 0; i < 128; i++) { float s = buf[2 * i] / 32768.f; acc += (double)s * s; n++; }
        }
        float pr = sqrtf((float)(acc / n));
        printf("  preview rms %.4f\n", pr);
        if (pr < 0.01f) bad += fail("808 preview silent");
    }
    play_free(k);

    PlayKit *e = play_load(b);
    if (!e) return fail("3l3ktr0 load");
    printf("3l3ktr0 status: %s\n", play_status(e));
    if (!strstr(play_status(e), "drumsynth")) bad += fail("3l3ktr0 kind");
    if (!strstr(play_status(e), "Flanger")) bad += fail("3l3ktr0 group fx");
    if (!strstr(play_status(e), "FM*")) bad += fail("3l3ktr0 skipped fx");
    float sub = rms_note(e, 48, 80);
    printf("  sub rms %.4f  info %s\n", sub, play_info(e));
    if (sub < 0.02f) bad += fail("3l3ktr0 kick silent");
    play_note(e, 53, 100); /* pad 6 clap, snare + reverb */
    printf("  after clap info %s\n", play_info(e));
    if (!strstr(play_info(e), "Reverb")) bad += fail("3l3ktr0 clap reverb");
    float clap = 0;
    {
        double acc = 0; int n = 0; int16_t buf[256];
        for (int b = 0; b < 80; b++) {
            play_render(e, buf, 128, 0.8f, 1);
            for (int i = 0; i < 128; i++) { float s = buf[2 * i] / 32768.f; acc += (double)s * s; n++; }
        }
        clap = sqrtf((float)(acc / n));
    }
    printf("  clap rms %.4f\n", clap);
    if (clap < 0.01f) bad += fail("3l3ktr0 clap silent");
    play_free(e);
    /* Flumex on a card that has the wavs beside the group, and One Shots/ one folder up,
     * with no Samples/ directory. */
    {
        const char *src = "/Users/Shared/Maschine 2 Factory Library Library/Samples";
        const char *kit = "/Users/Shared/Maschine 2 Factory Library Library/Groups/Kits/Flumex Kit.mxgrp";
        const char *flat = "/tmp/flumex-flat";
        const char *names[] = {
            "Kick Flumex.wav", "Snare Flumex.wav", "ClosedHH Flumex 1.wav", "SFX Flumex.wav",
            "ClosedHH Flumex 2.wav", "Stick Flumex.wav", "Tom Flumex.wav", "Synth C Flumex.wav",
            "Crash Flumex.wav", "Synth[140] Gm Flumex.wav"
        };
        const char *rel[] = {
            "Drums/Kick/Kick Flumex.wav", "Drums/Snare/Snare Flumex.wav",
            "Drums/Hihat/ClosedHH Flumex 1.wav", "One Shots/SFX/SFX Flumex.wav",
            "Drums/Hihat/ClosedHH Flumex 2.wav", "Drums/Snare/Stick Flumex.wav",
            "Drums/Tom/Tom Flumex.wav", "One Shots/Synth Note/Synth C Flumex.wav",
            "Drums/Cymbal/Crash Flumex.wav", "Loops/Synth/Synth[140] Gm Flumex.wav"
        };
        char cmd[640];
        snprintf(cmd, sizeof cmd, "rm -rf '%s' && mkdir -p '%s/EDM' '%s/One Shots/Synth Note' '%s/One Shots/Distortion'",
                 flat, flat, flat, flat);
        if (system(cmd) != 0) bad += fail("flumex stage");
        char dst[512];
        snprintf(dst, sizeof dst, "%s/EDM/Flumex Kit.mxgrp", flat);
        if (symlink(kit, dst) != 0) bad += fail("flumex kit link");
        for (int i = 0; i < 10; i++) {
            snprintf(dst, sizeof dst, "%s/EDM/%s", flat, names[i]);
            char from[512];
            snprintf(from, sizeof from, "%s/%s", src, rel[i]);
            if (symlink(from, dst) != 0) bad += fail("flumex wav link");
        }
        const char *up[][2] = {
            {"One Shots/Synth Note/Bass A Flumex.wav", "One Shots/Synth Note/Bass A Flumex.wav"},
            {"One Shots/Synth Note/Bass C Flumex.wav", "One Shots/Synth Note/Bass C Flumex.wav"},
            {"One Shots/Synth Note/Pad G Flumex.wav", "One Shots/Synth Note/Pad G Flumex.wav"},
            {"One Shots/Distortion/Dist Flumex.wav", "One Shots/Distortion/Dist Flumex.wav"},
        };
        for (int i = 0; i < 4; i++) {
            snprintf(dst, sizeof dst, "%s/%s", flat, up[i][0]);
            char from[512];
            snprintf(from, sizeof from, "%s/%s", src, up[i][1]);
            if (symlink(from, dst) != 0) bad += fail("flumex parent link");
        }
        char grp[512];
        snprintf(grp, sizeof grp, "%s/EDM/Flumex Kit.mxgrp", flat);
        PlayKit *f = play_load(grp);
        if (!f) bad += fail("flumex load");
        else {
            printf("flumex status: %s\n", play_status(f));
            if (strstr(play_status(f), "library not found")) bad += fail("flumex library");
            if (strstr(play_status(f), "missing")) bad += fail("flumex missing");
            float fk = rms_note(f, 48, 40);
            printf("  flumex kick rms %.4f\n", fk);
            if (fk < 0.01f) bad += fail("flumex silent");
            play_free(f);
        }
    }
    {
        PlayKit *ball = play_load("/Users/Shared/Maschine 2 Factory Library Library/Groups/Kits/8-Ball Kit.mxgrp");
        if (!ball) bad += fail("8-ball load");
        else {
            char text[16384];
            printf("8-ball patterns %d nev %d\n", play_npat(ball), play_pat_events(ball, 0));
            if (play_npat(ball) < 2 || strcmp(play_pat_name(ball, 0), "Pattern 1")) bad += fail("8-ball name");
            play_pattern_text(ball, 0, text, sizeof text);
            /* Swung kick and snare. A 1/32 grid check used to drop these and play the wrong pads. */
            if (!strstr(text, "\n48\t2405\t")) bad += fail("8-ball kick");
            if (!strstr(text, "\n49\t810\t")) bad += fail("8-ball snare");
            play_free(ball);
        }
        PlayKit *flu = play_load("/Users/Shared/Maschine 2 Factory Library Library/Groups/Kits/Flumex Kit.mxgrp");
        if (!flu) bad += fail("flumex pattern load");
        else {
            char text[16384];
            printf("flumex patterns %d first '%s'\n", play_npat(flu), play_pat_name(flu, 0));
            if (play_npat(flu) < 5 || strcmp(play_pat_name(flu, 0), "1-140 Bpm")) bad += fail("flumex patterns");
            play_pattern_text(flu, 0, text, sizeof text);
            if (!strstr(text, "\n50\t720\t")) bad += fail("flumex hat");
            play_pattern_text(flu, 1, text, sizeof text);
            if (!strstr(text, "\n48\t")) bad += fail("flumex kick");
            play_free(flu);
        }
    }
    printf("%s\n", bad ? "FAILED" : "PASSED");
    return bad ? 1 : 0;
}
