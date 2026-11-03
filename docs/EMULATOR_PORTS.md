# Porting an emulator (firmware / DSP emulation) to an MPC plugin

What the emulator ports (Osirus, Xenia, JV-880, Machinemodule, Monomodule, JE-8086, MS2KR) taught, in the order a new port
meets it. Read with `PORTING.md` (the general checklist) and `BENCH.md`. Facts dated; "device" = measured on an MPC Live III,
"offline" = x86 or the device without MPC.

## 1. Know the CPU before you design threads (Gen2 is big.LITTLE)

- **MPC Live III: cores 0-3 Cortex-A55 1.8 GHz, cores 4-7 Cortex-A76 2.4 GHz** (`/proc/cpuinfo` part `0xd05` / `0xd0b`;
  `cpuinfo_max_freq` 1800000 / 2400000). Check every core: the first lines of cpuinfo only show the A55s. (device 2026-11-03)
- The A76 does **~3x the work per thread**, much more than the clock ratio. Paced bench, 8 voices, plugin threads in % of one
  core, slow cores 0-2 vs fast cores 4-6 (device 2026-11-03, outside MPC):

  | Port | as shipped | cores 0-2 | cores 4-6 |
  |---|---|---|---|
  | Osirus | 40-57 (threads wander) | 91 | 31 |
  | Xenia | 110 | 190 | 62 |
  | JV-880 | 56 (pins itself to 0-2) | 56 | 22 |
  | Machinemodule | 78, audio-thread p99 120% | 76 | 27, p99 35% |
  | JE-8086 | 70 (mostly on 4-7 already) | | 52 with `fast_cores.h` built in |

  JE-8086's smaller gain: unpinned, its gearmulator threads already sat on the A76s most of the time. Built-in pinning still
  gives it a fixed 25% (device 2026-11-03, paced bench outside MPC).

- **MPC's own threads:** "AudioWorker0-3" and "Audio Processing" are `SCHED_RR` **rt priority 20**, pinned one per core to
  4, 5, 6, 7 ("Audio Processing" shares 7 with AudioWorker3); MIDI and FileIO threads are pinned to core 3 (rt 10 / 1);
  MPC's main/UI threads float. (device 2026-11-03)
- So: **put heavy engine threads on the fast cores, leave out core 7, and stay below rt priority 20.** Unpinned, Linux spreads
  them over the slow cores part of the time (MS2KR: ring empty in most 5 s windows, dropouts; pinned to 4-6 by hand: none).
  A "least busy core" picker (`/proc/stat`) chooses the A55s, because MPC keeps the A76s busy.
- `wrapper/fast_cores.h` does it: `fastcores::pin_this_thread()` (fastest cores by `cpuinfo_max_freq`, minus the highest-numbered
  when three or more; a no-op on same-speed CPUs, so the Force and Gen1 keep their tuning) and `fastcores::rt_priority(p)`
  (caps a `SCHED_FIFO` priority at 15 on big.LITTLE). Call it in the emulator thread **before** it starts the DSP thread or voice
  workers: new threads inherit the mask. A port with a hard-coded core list (`CPU_SET(0..2)`) or a load-based picker: use
  `usable()` on Gen2, keep the old choice on Gen1.
- **Never let a plugin thread outrank MPC's audio threads on their cores.** `SCHED_FIFO` 30 or 45 was harmless on cores MPC
  doesn't use; on 4-7 it would preempt MPC's audio engine. `rt_priority()` handles it.
- The Force (Gen1) is different: four equal Cortex-A53 cores, cores 2-3 isolated for MPC's busiest audio workers
  (`NOTES.md`). Nothing above changes it.

## 2. Thread layout: run the emulator ahead, the host only copies

- The host calls `render()` with 128 frames (MPC on the Live III reads exactly one 128-frame block per call, device
  2026-11-03). An emulator's cost per block is uneven (firmware does bursts of work), so emulate on a thread of your own,
  into a ring kept N frames ahead; `render()` copies and counts underruns. Osirus: 768 frames (~17 ms). MS2KR: 768, growing by
  itself up to 3072 if the host reads in bigger bursts.
- MIDI into the emulator thread through a single-producer FIFO (the wrapper never calls two engine functions at once for one
  instance, so `midi()` and `set_param()` are one producer). Anything that reads or writes emulator memory (SysEx, peeks for
  favourites/state) runs **on** the emulator thread: post a closure, and wait for its answer only from non-audio calls.
- Boot on that thread too, with `render()` silent until ready: a firmware's own boot is often slower than real time
  (MS2KR's DSP program upload: 131% of real time for a second).
- Emulators that already split the CPU and the DSP onto two threads (gearmulator, ms2000r-emu's DSP-THREAD) are a good start:
  each thread then needs well under a core. Turn it on.

## 3. Events that stall the emulator: run further ahead first

- Some events cost the **host** far more than their machine time: a program change that uploads new DSP code makes the
  DSP56300 JIT recompile (MS2KR: one 1.45 ms chunk took 17 ms on x86, ~45 ms on the A55/A76 device, more than the ring).
  ROM/bank loads and big SysEx dumps can do the same.
- Fix (MS2KR, offline + device 2026-11-03): hold such an event back, let the emulator thread run until the ring is ~58 ms
  ahead (it runs faster than real time, so ~60 ms), then apply it; the stall eats the extra and the ring settles back. Intercept
  MIDI program changes in the emulator thread's MIDI pull (stop the pull there so later events keep their order); for SysEx-based
  changes keep the boost ~400 ms, because the firmware stalls when the transfer *ends*. Normal latency stays at the base ring.
- JE-8086 (gearmulator, no DSP56300) does the same with a simpler trigger: every non-note command (patch load as DT1 SysEx,
  program change, state restore) raises the ring target from ~35 ms to ~60 ms for 400 ms (offline + device test 2026-11-03;
  MPC soak pending).
- A soak with program changes every 0.3 s and a chord held shows it at once (Osirus has `osirus_soak`, MS2KR's engine test a
  "program-change stress").

## 4. Measure inside MPC, and log what the ring does

- Offline tests (even paced, even on the device) do not have MPC's real-time threads on the fast cores: MS2KR passed with 0
  dropouts offline and dropped out in MPC. Always finish with a device run in MPC.
- Log one line every ~5 s to stderr (it lands in `journalctl -u acvs` on Gen2): dropouts, ring minimum since the last line,
  the host's largest read burst, the slowest chunk the emulator produced. MS2KR's line found both of its problems in two runs.
  Show the dropout count in the skin too (a status readout), so the user can report it. A status text that changes while MPC's
  PRESET menu is open makes MPC rebuild the menu (it flickers and resets): freeze the readout for ~15 s after the host asks for
  program names, and round CPU to 10% steps (Osirus, JE-8086; device 2026-11-02). Log only when dropouts rose, with an env
  var for always (JE-8086 `JE_RINGLOG=1`), so a healthy session writes nothing.
- Per-thread CPU over SSH: parse `/proc/<pid>/task/<tid>/stat` **after the last `)`** (MPC's thread names contain spaces, which
  shift the fields), utime+stime are fields 12+13 of the rest, the current core field 37; this kernel has no `schedstat`.
- `tools/bench.sh` is not paced: it calls `render()` as fast as it can, so an emulator thread runs flat out and "background
  threads %" measures saturation, not cost. For emulator ports, pace it (sleep to the next 2902 us after each block) and keep
  all of the plugin's threads on one core set from outside (`taskset -p` on every tid, once a second) to compare placements.

## 5. Build: profile-guided optimisation pays

- `-fprofile-generate` build of the engine test, run on the device (the real CPU), `.gcda` copied back, `-fprofile-use` build:
  MS2KR -21% (device 2026-11-02), bit-exact output. The `.gcda` names embed the build directory: rename them, or build both
  in the same directory. Add `-fprofile-partial-training -Wno-missing-profile -Wno-coverage-mismatch` so later edits
  don't break the build. LTO gave another ~8% on x86.
- Prove every speed change bit-exact: render a fixed MIDI sequence to WAV and compare its SHA-1 before and after.

## 6. Firmware-specific traps seen so far

- A dumped unit's Global MIDI channel may not be 1: ask the firmware (Device Inquiry `F0 7E 7F 06 01 F7`, the reply carries the
  channel) and move incoming channel messages there. Send test notes only after boot; notes during boot are lost.
- Upstream emulators written for Windows include `<intrin.h>` and call `_ReturnAddress()`: a two-line shim header
  (`x86intrin.h` on x86, `__builtin_return_address(0)`) instead of editing vendored code.
- Upstream JITs may have x64-only fast paths (MS2KR: dsp56300's cycle-bounded trampoline); check what the arm64 build
  actually runs, and that debug code doesn't touch a pointer that is null on arm64.
- Keep emulator process-wide state in mind: one machine per process unless upstream says otherwise; never `chdir()` inside MPC
  (pass absolute ROM paths), never install process-wide signal handlers.
- gearmulator `synthLib::Plugin` (JE-8086, device 2026-11-02): give it real zero input buffers and its own output buffers (its
  shared dummy buffer is written by one side and read by the other: impulses in the output); pass bpm 0 to `process()` unless
  you want MIDI clock (any bpm makes it send F8 every block); keep host commands queued until the firmware has booted, or a
  restored state is lost; `RomLoader::addSearchPath` is a process-wide set: lock it when two instances boot at once.
- A momentary skin key sends only the press: if the firmware scans keys, hold the emulated key down ~100 ms on the emulator
  thread, then release it there.
