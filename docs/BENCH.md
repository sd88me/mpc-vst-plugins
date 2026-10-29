# CPU check: will a port run on Gen1 hardware?

`tools/bench.sh` plays a plugin the way MPC does and reports how much of one audio block it uses. Run it on a
real device before releasing anything. Numbers from a PC say nothing about an MPC.

```
tools/bench.sh build/x.so <device-ip> [-s secs] [-v 1,4,8,16] [-p] [-j]   # on the device (armhf Gen1, or
                                                                        # build/aarch64/x.so on a Gen2)
tools/bench.sh build/x-x86.so local                                     # on a PC: relative numbers only
```

Nothing is installed: the bench and a copy of the `.so` go to `/tmp` on the device and are deleted afterwards. MPC
can keep running.

## What it does
- 44100 Hz, 128-frame blocks (the budget is 2902 µs per block), host transport playing at 120 BPM.
- Stages: **idle**. For instruments, **N-voice chords** re-struck every half second (default 1, 4, 8 and 16 voices;
  effects get noise input instead). Then a **Q-Link sweep** (4 random parameters per block while holding 8 voices;
  `-p` sweeps every parameter). Then the **release tail** after note-off, which catches denormal slowdowns.
  Finally **trigger fire**: every one-shot parameter (`"momentary": true`) is tapped once, eight blocks apart.
- **Triggers are not swept.** Before the stages, the bench asks the plugin which parameters are one-shot triggers
  through the wrapper's vendor opcode `0x7F01` (`EFF_MPC_IS_MOMENTARY`). Those are excluded from the random sweep
  and measured in **trigger fire** instead: a tap is one discrete event, a drag is a stream, and only the stream is
  what a Q-Link can flood. A plugin built before that opcode existed answers 0 for every index, so the sweep covers
  all parameters as it always did. The trigger stage does not decide the verdict the way a continuous stage does,
  but a tap that reaches 90 % of a block (`TRIGGER_WARN_PCT` in `tools/bench.c`) turns a PASS into a WARN: such a
  tap glitches the block after it.
- Each block is timed with the thread's own CPU clock (`CLOCK_THREAD_CPUTIME_ID`), so time MPC's real-time threads
  take from us doesn't count. The plugin's own worker threads are reported separately (`threads%`).
- The bench runs at normal priority, so MPC's audio always wins and nothing glitches. It pins to core 1 on Gen1 and
  to core 4 on Gen2 (the Live III's audio workers sit on its four fast cores, 4-7); `BENCH_CPUMASK=<hex>` overrides.
  `bench.sh` asks the device for its architecture and builds the bench for it, so give it the matching `.so`.

## Verdict
The p99 and worst block, as a percentage of one block on one core:

| Verdict | p99 | worst block | Meaning |
|---|---|---|---|
| PASS | ≤ 15% | ≤ 50% | Several instances alongside a normal project |
| WARN | ≤ 35% | ≤ 80% | One or two instances; say so in the release notes |
| FAIL | above | above | Will glitch in real projects: optimise first |

Why those numbers: on the Force, MPC runs one audio worker per core (`AudioWorker0-3`, SCHED_FIFO, cores 2-3
isolated) and spreads tracks across them. Stock engines, effects and other plugins share the same four
2902 µs windows, so a single plugin should take a small slice, and never a spike near a whole block.

Exit code is 1 on FAIL, so the bench can gate a release script. `-j` adds a JSON line; `tools/release.py --bench`
puts it into the release's INSTALL.md. When triggers were found, the JSON also carries `triggers` and
`trigger_max_pct`, so the trigger cost is recorded next to the verdict instead of hiding inside it.

Limits: the bench drives the audio path only. App-style plugins (e.g. Crate Digger) do their real work in worker
threads and child processes that the bench doesn't trigger. Watch `top` on the device while using them instead.
This also catches out instruments whose synthesis runs on a background thread paced to the real wall clock
rather than to how many blocks the bench has called (e.g. jv880: a ring-buffer-filling emulator thread) --
`bench.c` has no pacing/sleep, so it races through blocks far faster than real time, and `threads%`'s formula
divides by the *assumed* real-time-equivalent duration regardless of how little wall-clock time actually
passed, making that thread's true cost vanish. Confirmed on device: bench reported 0.2-0.5% for jv880 (PASS),
but the real `jv880-emu` thread measured **20.8% of one core** sampled directly via `/proc` while actually
playing (see mpc-vst's own docs/NOTES.md). Don't trust `threads%` for this class of plugin; sample the real
thread's ticks on the device during actual playback instead.

## Reference results (Force, RK3288 Cortex-A17 @ 1.8 GHz, MPC running, 2026-09-24)

| Plugin | idle | 16 voices / audio | Q-Link sweep p99 | worst block | Verdict |
|---|---|---|---|---|---|
| Maze Voice (mono synth) | 6.8% | 7.1% | 9.6% | 10.3% | PASS |
| Crate Digger (stream player, idle) | 0.1% | 0.1% | 1.0% | 5.9% | PASS |

## Gen2 devices
`bench.sh` runs on a Gen2 device the same way (aarch64 bench from `arm64v8/gcc:12-bookworm`, so the build needs
Docker with arm64 emulation). Verified on a MPC Live III (2026-10-23): 8 cores, 0-3 Cortex-A55 @ 1.8 GHz and 4-7
Cortex-A76 @ 2.4 GHz, MPC's `AudioWorker0-3` pinned to 4-7 under SCHED_FIFO.

**Denormals.** armv7 NEON flushes denormals to zero by itself; aarch64 does not, and denormal arithmetic is far
slower. A feedback-heavy plugin can run fine on Gen1 and spike by orders of magnitude on Gen2: Acid-303's first
aarch64 build measured a worst block of 3870% (Q-Link sweep) and went to 17% after setting FPCR.FZ around its render
call. If a Gen2 bench shows huge worst blocks in the release tail or the sweep, look here first.

| Plugin (Gen2, Live III) | idle | 16 voices | Q-Link sweep p99 | worst block | Verdict |
|---|---|---|---|---|---|
| Acid-303 (HQ, 4x circuit model) | 0.8% | 8.5% | 15.1% | 17.0% | WARN (p99 over 15% by 0.1) |
