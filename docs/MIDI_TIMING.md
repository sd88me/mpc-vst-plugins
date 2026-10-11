# Timing for MIDI sequencers and arpeggiators

How a MIDI-generating plugin (sequencer, arp, euclidean, drum pattern) should place its notes against MPC's transport.
Short version: **put each step on the host's song position (`ppqPos`); do not count MIDI clock pulses you synthesized
yourself.** Reference implementation: `mpc-vst-acid`, `vst/acid_vst.cpp` `feed_transport()` (mpc-vst-acid PR #8, not yet released).

## What the host gives you (verified on a Force, MPC OS 3.9.1, 2026-10-07/08)
`audioMasterGetTime` with `kVstTempoValid | kVstPpqPosValid`:
- `flags` was `0x7fc6` while playing: `kVstTransportPlaying` (bit 1) set. A plugin instance that is **not** running (idle, other
  track, stopped) reports stopped; an instance that stops keeps whatever `ppqPos` it last saw, so a log of "playing 0, ppq
  unchanged" is a stopped instance, not a broken host.
- `ppqPos` is the song position **at the start of the block** and advanced every block (0 blocks with an unchanged value in
  ~230,000), 128 frames per block, 44100 Hz both in `effSetSampleRate` and `VstTimeInfo.sampleRate`.
- When the project loops, `ppqPos` jumps back to the loop start in the middle of the stream (a backward step of the loop
  length). The block that straddles the loop end carries a position just after the loop start.
- Over 5-9 minute runs the plugin's wall clock (`CLOCK_MONOTONIC`) and the host's audio clock (`samplePos/sampleRate`)
  differed by ~0.1-0.3 ms per 7.5 s loop (tens of ppm). **Never pace musical timing from the wall clock**; use only host
  position and the frame count of each block. Wall time is fine for CPU statistics.

## Do not: step on pulses you counted
The first Force port (Acid <= 1.0.4) turned `ppqPos` into a 24-PPQN MIDI clock (`ceil(last/step)*step .. end`) and fed it to a
core that counted 6 pulses per 16th. That keeps tempo right but the step phase is **relative**: every lost, added or
unaligned pulse stays in the phase until the next Start. Where it goes wrong:
- a start in the middle of a 16th or beat (the first pulse after Start becomes step 0 wherever the playhead was);
- a loop wrap: the old code resynced with `start = end`, dropping the boundary that falls in the straddling block;
- a locate/jump, or any block where the host position and your pulse count disagree;
- swing rounded to whole pulses (6 per 16th, so only a few swing amounts exist).
A reporter saw Acid's tempo correct but its offset against other tracks growing on a Force. It could not be reproduced with
the old code on the same Force over ~6 minutes, so the pulse-counting link to that report is **not proven**; the design is
still wrong for the cases above, and Stevequencer (which steps from absolute position) did not show the report.

## Do: place each step from the song position
Per block, with `start = last_ppq` and `end = ppqPos` (the interval covered since the previous block; notes go out one
block, ~2.9 ms, after their boundary, which is a constant and not drift):
1. `blk = frames * tempo / (60 * sampleRate)` (ppq per block).
2. `end < start` (loop wrap): `start = end - blk`, so the boundary at the loop start (inside the straddling block) is not lost.
   `end - start > 1.0` (forward jump/locate): `start = end`, do not flood.
3. For every 16th `k` (`t = k/4`, plus the swing delay `swing_frac/4` for odd `k`): if `start <= t < end`, fire step `k`.
   `swing_frac = clamp((swing_pct-50)/50, 0, 0.5)` when swing is 50..75%. Because `t` is computed in ppq, any swing amount
   is exact, not rounded to a pulse.
4. On Start (`kVstTransportPlaying` rises) set `last_ppq = ppqPos` and let the first boundary at or after the playhead be step 0.
5. Keep any pulse "heartbeat" a core needs for its own fallback timer, but do not let it advance steps once the grid drives.
Acid's core keeps its incremental pattern position (so pendulum/random/chain modes behave as before): the **timing grid**
is absolute, the pattern position is not derived from the song position. Decide that per plugin; making pattern position
a pure function of song position changes how non-forward modes behave.

## Test it
Offline (`host_test.c`, ASan/UBSan): drive `ppqPos` through 50 loops of 4 beats with a loop length that is not a multiple of the
block size, and require the step count to be exact (loops 6-50: 720 steps, within 1 for measurement lag), and a start at
ppq 3.3 must give exactly the grid-aligned steps. Expose a step counter through an `extern "C"` hook (hidden in the release
build with `-fvisibility=hidden`).
On a device: log `steps` next to the pulse count in the periodic stats line; `steps` should stay at `pulses/6` for straight
timing. Keep file I/O out of `processReplacing` in release builds (Acid's diagnostic build wrote a note log from the audio
thread; that was removed before release).

## Limits that remain
- Events go out `snd_seq_event_output_direct` at the start of a block: block resolution (~2.9 ms at 128 frames), measured
  jitter 0.15-0.5 ms (sd). Ratchets and note lengths shorter than a block are quantized to blocks.
- What the Force does after the ALSA port (MIDI routing into the target track) is not visible from the plugin. A user
  report of drift that the plugin's own numbers cannot show points there. One Discord report said MPC's own arpeggiator
  stays in time when driven by MIDI Time Code but not by MIDI clock (unverified here).
