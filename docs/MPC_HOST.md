# MPC plugin host for desktop DAWs (idea and import survey)

**Status (2026-11-05): idea plus an offline survey. Nothing is built.**

The goal: one VST3 for desktop DAWs on Windows and macOS (Linux too) that loads MPC plugin `.so` files *as released*
(armv7 Gen1/Force, aarch64 Gen2) and browses them like MPC's plugin list. No second build of each plugin. This is a
different thing from `docs/DESKTOP_VST3.md`, which rebuilds a port from source as a native VST3. The host matters most
for plugins that only exist as MPC binaries.

## Approach

A plugin is an ARM Linux ELF shared object. It cannot be `dlopen`ed into an x86 or macOS DAW, and running Linux in a VM
(WSL2, Hyper-V, Virtualization.framework) is a heavy install with poor real-time behaviour. The plan is user-mode emulation
inside our own process, as console and Android emulators do:

1. **CPU:** dynarmic (AArch32 and AArch64 guest; x86-64 and arm64 host JIT; 0BSD). Unicorn as a slower fallback.
2. **Loader:** our own ELF loader maps the `.so` into a reserved 4 GB guest region and applies its relocations. armv7
   code needs 32-bit pointers.
3. **Imports go to native code.** Calls into libc, libm and libpthread are thunked to host functions: plain calls map 1:1,
   and `pthread_create` starts a host thread with its own guest CPU context. C++ ports can run Debian's armhf/arm64
   `libstdc++` as guest code, so only libc is thunked. Akai's files are never shipped.
4. **VST2 ABI:** `VSTPluginMain` runs as guest code. The host callback and the AEffect calls are thunks both ways (the
   ABI is already hand-written in `wrapper/vst2_wrap.c`).
5. **UI and library:** native. The skin renderer in `wrapper/vst3_editor.c` draws the plugin's `TUI.json` skin; it needs
   HWND and NSView window layers (see DESKTOP_VST3.md "No editor"). The browser reads the installed plugin folders and
   `mpc-plugin.json` (docs/CATALOG.md).

**Process layout.** On macOS a JIT needs `MAP_JIT` and the `com.apple.security.cs.allow-jit` entitlement. A hardened DAW
does not give that to a plugin loaded into it. So the emulator runs in our own signed helper process, and the VST3 is a
thin shell that talks to it over shared memory, with a ring one block ahead of the DAW (as in docs/EMULATOR_PORTS.md).
Use the same layout on Windows for crash isolation.

## Import survey (2026-11-05, offline)

Other people's plugin repos (and their release zips) were not reachable from the session that wrote this, so only this
repo's probes were measured. `poc/sampleprobe`, `poc/songpos` and `poc/inputprobe` were built for armv7 with Ubuntu's
`arm-linux-gnueabihf-gcc` (glibc 2.39 headers, not the bullseye image `build_port.sh` uses), using the same flags and
`wrapper/vst2_wrap.c`. Their undefined dynamic symbols:

- **NEEDED:** `libc.so.6`, `ld-linux-armhf.so.3`, plus `libm.so.6` for inputprobe.
- **Every probe** (the wrapper's floor, about 25 symbols): `calloc free memcpy memset strcmp strlen strncpy strtod strtol
  snprintf raise`, `pthread_mutex_{init,destroy,lock,unlock}`, `pthread_mutexattr_{init,destroy,settype,setprotocol}`,
  fortify and stack-protector helpers (`__snprintf_chk __stack_chk_fail __stack_chk_guard`), and the CRT weak symbols
  (`__cxa_finalize __gmon_start__ _ITM_*`).
- **inputprobe also:** `getenv fopen64 fflush __fprintf_chk __vfprintf_chk strcasecmp __ctype_b_loc clock_gettime`, and
  from libm `ceilf floorf fmaxf lroundf roundf`.
- A bullseye build gives the older names (`strtol`, not `__isoc23_strtol`; `clock_gettime`, not `__clock_gettime64`).
  The thunk table should cover both.

The wrapper is small and plain. Real engines will add more than the probes, and these are the known extras that need
special handling, not a 1:1 thunk:

| Use | Where | What the host does |
|---|---|---|
| `fopen("/proc/self/maps")` to find its own folder | `wrapper/plugin_dir.h` | serve a fake maps file naming the plugin's path |
| `/sys/devices/system/cpu/*/cpufreq` and `sched_setaffinity` | `wrapper/fast_cores.h` | fake one fast cluster; make affinity a no-op |
| `dlopen("libcurl.so.4")` for HTTPS | NOTES.md "HTTPS" | a native HTTP implementation behind libcurl's API, or refuse |
| ALSA sequencer MIDI out (`snd_seq_*`) | NOTES.md | route to the host's MIDI out, or drop |
| `/sdcard/...` and other absolute paths | ports | map to a library folder |

## Three real ports (2026-11-06, offline, from source)

Release zips were not downloadable from the session (HTTP 403), so the repos were cloned and read. Acid-303 was also built
for armv7 with Ubuntu's cross g++ (same cflags as its `vst.json`, `-mcpu=cortex-a17 -mfpu=neon-vfpv4`). They show three
tiers of difficulty:

- **Acid-303 (`sd88me/mpc-vst-acid303`): easy.** Its NEEDED libraries are libstdc++, libm, libgcc_s and libc. About 65
  imports: the probe set plus libm (`exp exp2 log log1p pow sin tan lrintf lround`), `memmove`, `strchr`, and the C++
  runtime (`operator new`/`delete`, `__cxa_*` exception and guard helpers, `__gxx_personality_v0`,
  `__aeabi_unwind_cpp_pr0/1`). The C++ runtime runs as guest code. One thing to check: the engine uses NEON intrinsics
  (`voice.cpp`, `__ARM_NEON`), so dynarmic's AArch32 ASIMD coverage has to include them.
- **Machinemodule (`sd88me/mpc-vst-machinedrum`): hard.**
  - Two plugins share state. The tap effects find the Module with `dlopen("machinedrum_one.so", RTLD_NOLOAD)`, or
    through `/proc/self/maps`, and use its statics. So every plugin instance must live in one guest address space, and
    the loader must answer `RTLD_NOLOAD` lookups.
  - The voice engine runs on parallel threads pinned with `sched_setaffinity`.
  - Once per flash image it runs a helper program, `posix_spawn("/bin/sh", "ulimit -s 8192; exec helper ...")`. The host
    would have to run a second guest executable, or ship the files that helper makes.
  - The Gen1 build is made by the user from their own firmware; no binary is released. The Gen2 aarch64 build runs the
    dsp56300 JIT, which writes arm64 code at run time. Under dynarmic that is a JIT inside a JIT: it needs `mmap`/`mprotect`
    thunks with executable memory and cache invalidation on `IC IVAU`/`__clear_cache`, and it will be slow.
- **Euclidier (`sd88me/mpc-vst-euclidier`): out of scope for in-process emulation.** The `.so` uses `posix_spawn` to
  start a separate static `euclidier` executable (RtMidi, `-lasound`), drives it over an `AF_UNIX` control socket, and
  routes MIDI through ALSA sequencer ports it opens itself. Hosting it means emulating a Linux process, its sockets and an
  ALSA sequencer: a qemu-user-sized job. It is a better fit for a native desktop build (DESKTOP_VST3.md), or for a host
  that speaks Euclidier's socket protocol itself.

So the first target is self-contained DSP ports like Acid-303. Shared-state and JIT ports come second. Ports that spawn
processes come last, or never.

## Next steps

1. Run the same survey on every catalog release (`catalog/plugins/*.json` repos, armv7 and aarch64 zips), from a session
   that can reach those repos, and list the union of imports and syscalls.
2. Prototype on Linux x86: dynarmic, the loader and thunks, with no DAW. Load `songpos.so`, render blocks, and compare CPU
   against the native VST3 build.
3. Then the helper process with shared-memory transport, the VST3 shell, the Windows/macOS builds and the editor windows.
