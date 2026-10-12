# Timing for MIDI sequencers and arpeggiators

How a MIDI-generating plugin (sequencer, arp, euclidean, drum pattern) should place its notes against MPC's transport.
Short version: **put each step on the host's song position (`ppqPos`); do not count MIDI clock pulses you synthesized
yourself, and send each block's notes at the start of that block, not after it.** Reference implementation: `mpc-vst-acid`,
`vst/acid_vst.cpp` `feed_transport()` + `play_span()` (master after 1.0.7). Engine-process plugins use the same grid with a Song
Position Pointer: `transport_grid.h` in `mpc-vst-euclidier` (1.0.7) and `mpc-vst-maze/sequencer` (Maze Sequencer 1.0.6).

## What the host gives you (verified on a Force, MPC OS 3.9.1, 2026-10-07/08)
`audioMasterGetTime` with `kVstTempoValid | kVstPpqPosValid | kVstCyclePosValid`:
- `flags` was `0x7fc6` while playing: `kVstTransportPlaying` (bit 1) set. A plugin instance that is **not** running (idle, other
  track, stopped) reports stopped; an instance that stops keeps whatever `ppqPos` it last saw, so a log of "playing 0, ppq
  unchanged" is a stopped instance, not a broken host.
- `ppqPos` is the song position **at the start of the block** and advanced every block (0 blocks with an unchanged value in
  ~230,000), 128 frames per block, 44100 Hz both in `effSetSampleRate` and `VstTimeInfo.sampleRate`.
- **MPC reports its loop** (verified 2026-10-12): `kVstTransportCycleActive` (bit 2) and `kVstCyclePosValid` (bit 12) are set
  and `cycleStartPos`/`cycleEndPos` are the loop (`[0, 16)` for a 4-bar loop from bar 1).
- When the project loops, `ppqPos` jumps back to the loop start (a backward step of the loop length). Every block's `ppqPos`
  is that block's true start, so **the block that straddles the loop end still reports a pre-wrap position**: 16-beat loop,
  126 BPM: `15.998952`, then `0.005190` (the straddling block covers 15.99895..16.00505, i.e. 16.0 and 0.0 share it). Every
  wrap repeated the same numbers.
- `ppqPos` **jitters** around `k * blk`: rms 0.0004 beat (~0.2 ms), from -0.0009 to +0.0002 beat; `samplePos` steps 109-132
  frames for 128-frame blocks. The jitter is on the wrapped position (the block after a wrap reported 0.005190 for an
  expected 0.005048). Compare positions with a tolerance, never for equality.
- **A tempo change moves `ppqPos` back a little** (~0.07 beat seen on a Force, Acid PR #11, 2026-10-09), then it crawls forward
  again. Fast tempo changes (turning the tempo encoder quickly) do this repeatedly and also make it lurch ahead, so a block
  can both re-cover boundaries already played and skip some. Slow changes rarely showed a problem; fast ones did.
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

## Do: place each step from the song position, a block ahead
**Send the block about to play, at its start** (StepRunner-8 does this). Sending the interval since the previous block
(`[last_ppq, ppqPos)`, what Acid <= 1.0.7, Euclidier <= 1.0.6 and Maze Sequencer <= 1.0.5 did) puts every note one block
(~2.9 ms) behind its boundary, plus whatever comes after the plugin (MPC's MIDI input, an engine process). Users noticed:
"I have to add track delay to my main tracks" to line up a TR-MPC driven by Euclidier, and needed none with StepRunner-8.
Sent at the block's start, a note leaves 0 to 1 block early, which MPC's MIDI input path then absorbs. On a Force, Euclidier
1.0.7's notes measured at most 3.7 ms early and never late against the 16th grid.

Per block, with `sent_to` = the high-water mark (everything before it was sent):
1. `blk = frames * tempo / (60 * sampleRate)` (ppq per block); `start = sent_to`, `end = ppqPos + blk`.
2. `|ppqPos - sent_to| < 1 beat`: carry on from `sent_to`. That covers the jitter and **a tempo change**, whose `ppqPos` steps
   back a little: `end <= start` then sends nothing and `sent_to` stays, so nothing plays twice. (Acid used 0.25 beat
   first; a faster change stepped back further, was taken for a loop wrap and doubled steps. 1 beat is safe for loops of
   a bar or more.)
3. **Loop end inside the block** (cycle flags set, `cycleStartPos <= ppqPos < cycleEndPos < end`): send `[start, cycleEndPos)`,
   then re-anchor (rebase `next_k` / announce the Song Position) and send `[cycleStartPos, cycleStartPos + end - cycleEndPos)`;
   that end is the new `sent_to`. The next block then reports a position just past it and carries on normally. Without the
   split the look-ahead sends the loop start's notes under the position *after* the loop end.
4. `|ppqPos - sent_to| > 1 beat` (a wrap the host did not report, or a locate): re-anchor and start at `ppqPos - 0.002`
   (a little more than the jitter: a wrap reported at 0.0001 still plays the loop start's step), but not before
   `cycleStartPos`. For a **backward** jump with no loop reported start at `ppqPos` itself: the previous block's look-ahead
   may already have played that step (under the pre-wrap position), and 0.002 more would play it twice.
5. On Start (`kVstTransportPlaying` rises) set `sent_to = ppqPos` and let the first boundary at or after the playhead be step 0.

For each span sent:
- For every 16th `k` (`t = k/4`, plus the swing delay `swing_frac/4` for odd `k`): if `start <= t < end`, fire step `k`.
  `swing_frac = clamp((swing_pct-50)/50, 0, 0.5)` when swing is 50..75%. Because `t` is computed in ppq, any swing amount
  is exact, not rounded to a pulse.
- Keep any pulse "heartbeat" a core needs for its own fallback timer, but do not let it advance steps once the grid drives.
- **Make the pattern position a function of the song position too**, not only the timing. Acid 1.0.5-1.0.6 placed steps on
   the grid but its core still moved one pattern step per fired step, so every doubled or lost step on a fast tempo change
   shifted the pattern until Stop/Start ("tempo seems right but it's out of time, stopping and starting fixes it"). Acid
   1.0.7 hands the core the absolute 16th index `k` before each step (`set_param("song_step", k)`, then the step byte) and
   the core plays `k mod length` (Rev: `L-1 - k mod L`; Pendulum: period `2L-2`; reset-every-N-bars from `k mod N*16`;
   auto-regenerate when `k % N*16 == 0`). Also skip any `k` already fired (`k < next_k`), so a re-covered block never
   doubles a note. A step that is lost then costs one note, never the phase. Modes that are genuinely stateful (Acid's
   Chain, which alternates A and B passes) can stay step-counted. Side effect to state in release notes: starting
   mid-song picks the pattern up at the matching step, not at step 0.
   Engine plugins that take MIDI clock (Euclidier, Maze Sequencer) get the same effect from a Song Position Pointer
   (`songpos`) at Start, after a wrap/locate and once per bar, with the engine computing its step from its tick count.

## Note input and mute
- **Transpose by note input works** when the plugin's track receives MIDI (selected/armed). With record arm, MPC loops the
  plugin's own ALSA output straight back in as `VstMidiEvents`; filter those by an exact byte match against what was just
  sent (Acid's `was_just_sent()`), not by channel, or the user's real notes on the same channel are eaten too.
- **MPC's track Mute does not stop a MIDI generator**: the notes come from an ALSA port, not the track. Give the plugin its
  own Mute param (Acid 1.0.7): drop note-ons, let note-offs through so nothing hangs, and keep the sequence running so
  unmuting comes back on the beat. Users asked for this for live use.

## Plugins that run a separate engine process (Euclidier)
A report from a Force (MPC OS 3.9.1, stock and MockbaMod): Euclidier "stops after a few bars at a specific point in time,
independent of sequence length, and only a plugin reload brings it back". That pattern (silent, not drifting; reload
fixes it) points at the child engine dying or hanging, not at timing. Root cause not found (not reproduced); Euclidier
1.0.5 made it recover:
- **Watchdog** on the plugin's worker thread, ~1 s: `waitpid(WNOHANG)` for an exit, and a control-socket ping for a hang
  (5 failures, then `SIGKILL`). Restart with every cached param, the host tempo, and a Start + Song Position on the next
  block; log which one it was. host_test kills the engine mid-run and checks the restart and the restored settings.
- **Child stdout/stderr to `/dev/null`** (`posix_spawn_file_actions_addopen`): MPC's own may be a pipe that fills (blocks
  the engine) or closes (SIGPIPE kills it).
- **`steady_clock`, never `system_clock`, for engine timers** (note-offs, timeouts): the device can set its wall clock
  while playing, and a backward jump holds every pending note-off for that long.

## Test it
Offline (`host_test.c`, ASan/UBSan): require every step **in the block it is sent with**: after the block at true position `A`,
the steps fired so far are the 16ths before `A + blk` (within the jitter); the old block-late code fails this. Replay MPC's
measured jitter (-0.0009..+0.0002 beat, added after the wrap) with the loop reported, 50 loops: exactly 16 steps per loop,
pattern step = song position (Acid `host_test.c` case 5, `grid_test.cpp` in Euclidier and Maze Sequencer). Also run a loop
the host does *not* report: no step may double.
Drive `ppqPos` through 50 loops of 4 beats with a loop length that is not a multiple of the
block size, and require the step count to be exact (loops 6-50: 720 steps, within 1 for measurement lag), and a start at
ppq 3.3 must give exactly the grid-aligned steps. Expose a step counter through an `extern "C"` hook (hidden in the release
build with `-fvisibility=hidden`).
Tempo changes: step `ppqPos` back 0.1-0.15 beat and lurch it ahead 0.4 beat every few dozen blocks; the step count must
not double and the pattern step must equal the song position's (`acid_dbg_pos()` vs `k mod 16`, Acid `host_test.c` case 4).
On a device: log `steps` next to the pulse count in the periodic stats line; `steps` should stay at `pulses/6` for straight
timing. To debug a tempo report, log each block where `ppqPos` moved other than by `blk`, with the old/new tempo (only
tempo changes; logging every loop wrap floods the file). Keep file I/O out of `processReplacing` in release builds
(Acid's diagnostic builds wrote a note log from the audio thread; both times it was removed before release).

## Limits that remain
- An engine-process plugin (Euclidier) still adds its hop: ALSA into the engine, its MIDI thread, its output port. The
  look-ahead covers it when it is shorter than the time left in the block; it was not measured separately.
- Events go out `snd_seq_event_output_direct` at the start of a block: block resolution (~2.9 ms at 128 frames, 0 to 1 block
  early with the look-ahead), measured jitter 0.15-0.5 ms (sd). Ratchets and note lengths shorter than a block are quantized to blocks.
- What the Force does after the ALSA port (MIDI routing into the target track) is not visible from the plugin. A user
  report of drift that the plugin's own numbers cannot show points there. One Discord report said MPC's own arpeggiator
  stays in time when driven by MIDI Time Code but not by MIDI clock (unverified here).
