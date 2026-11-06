// Prototype guest: 4 GB guest space, a small ELF32 loader for armhf shared objects, dynarmic A32, and thunks that
// route the plugin's libc/libm/libstdc++ imports to host code. See docs/MPC_HOST.md.
#include "guest.h"

#include <dynarmic/interface/A32/a32.h>
#include <dynarmic/interface/A32/config.h>
#include <dynarmic/interface/exclusive_monitor.h>

#include <cctype>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <elf.h>
#include <fstream>
#include <functional>
#include <map>
#include <sys/mman.h>
#include <unordered_map>

namespace mpchost {

namespace {
constexpr uint64_t kSpace = 1ull << 32;
constexpr gaddr kThunks = 0x00001000;     // svc #n; bx lr  per import (8 bytes each), up to 0x7000
constexpr gaddr kData = 0x00008000;       // misc guest data (ctype table, stack guard, nothrow)
constexpr gaddr kLoad = 0x00100000;       // load bias of the plugin
constexpr gaddr kHeap = 0x10000000;
constexpr gaddr kHeapEnd = 0xE0000000;
constexpr gaddr kStackTop = 0xF0000000;   // 8 MB stack below this
constexpr uint32_t kRetSvc = 0xFFFFFF;    // svc number of the "return to host" stub
}  // namespace

struct Impl;
using Thunk = std::function<void(Guest::Impl&)>;

struct Guest::Impl final : Dynarmic::A32::UserCallbacks {
    Guest& g;
    uint8_t* m;
    Dynarmic::ExclusiveMonitor monitor{1};   // LDREX/STREX (one guest CPU)
    std::unique_ptr<Dynarmic::A32::Jit> jit;
    std::vector<Thunk> thunks;               // index = svc number
    std::vector<std::string> thunk_names;
    std::unordered_map<std::string, gaddr> dynsyms;
    gaddr data_next = kData;
    gaddr heap_next = kHeap;
    std::map<uint32_t, std::vector<gaddr>> free_lists;   // by rounded size
    std::unordered_map<gaddr, uint32_t> sizes;
    int depth = 0;

    explicit Impl(Guest& g_) : g(g_), m(g_.mem_) {}

    // --- dynarmic callbacks (fastmem covers almost everything; these are the slow path) ---
    template <class T> T rd(uint32_t a) { T v; std::memcpy(&v, m + a, sizeof v); return v; }
    template <class T> void wr(uint32_t a, T v) { std::memcpy(m + a, &v, sizeof v); }
    uint8_t MemoryRead8(uint32_t a) override { return rd<uint8_t>(a); }
    uint16_t MemoryRead16(uint32_t a) override { return rd<uint16_t>(a); }
    uint32_t MemoryRead32(uint32_t a) override { return rd<uint32_t>(a); }
    uint64_t MemoryRead64(uint32_t a) override { return rd<uint64_t>(a); }
    void MemoryWrite8(uint32_t a, uint8_t v) override { wr(a, v); }
    void MemoryWrite16(uint32_t a, uint16_t v) override { wr(a, v); }
    void MemoryWrite32(uint32_t a, uint32_t v) override { wr(a, v); }
    void MemoryWrite64(uint32_t a, uint64_t v) override { wr(a, v); }
    bool MemoryWriteExclusive8(uint32_t a, uint8_t v, uint8_t) override { wr(a, v); return true; }
    bool MemoryWriteExclusive16(uint32_t a, uint16_t v, uint16_t) override { wr(a, v); return true; }
    bool MemoryWriteExclusive32(uint32_t a, uint32_t v, uint32_t) override { wr(a, v); return true; }
    bool MemoryWriteExclusive64(uint32_t a, uint64_t v, uint64_t) override { wr(a, v); return true; }
    void InterpreterFallback(uint32_t pc, size_t) override { std::fprintf(stderr, "guest: interpreter fallback at %08x\n", pc); std::abort(); }
    void ExceptionRaised(uint32_t pc, Dynarmic::A32::Exception e) override {
        using E = Dynarmic::A32::Exception;
        if (e == E::PreloadData || e == E::PreloadDataWithIntentToWrite || e == E::PreloadInstruction || e == E::Yield ||
            e == E::SendEvent || e == E::SendEventLocal || e == E::WaitForEvent || e == E::WaitForInterrupt) return;   // hints
        std::fprintf(stderr, "guest: exception %d at %08x\n", (int)e, pc);
        std::abort();
    }
    void AddTicks(uint64_t) override {}
    uint64_t GetTicksRemaining() override { return 1ull << 40; }
    void CallSVC(uint32_t n) override {
        if (n == kRetSvc) { jit->HaltExecution(); return; }
        if (n >= thunks.size()) { std::fprintf(stderr, "guest: bad svc %u\n", n); std::abort(); }
        thunks[n](*this);
    }

    // --- argument access (armhf AAPCS) ---
    uint32_t& r(int i) { return jit->Regs()[i]; }
    uint32_t arg(int i) { return i < 4 ? r(i) : rd<uint32_t>(r(13) + 4 * (i - 4)); }
    float s(int i) { float f; std::memcpy(&f, &jit->ExtRegs()[i], 4); return f; }
    double d(int i) { uint64_t u = jit->ExtRegs()[2 * i] | (uint64_t)jit->ExtRegs()[2 * i + 1] << 32; double v; std::memcpy(&v, &u, 8); return v; }
    void ret(uint32_t v) { r(0) = v; }
    void ret64(uint64_t v) { r(0) = (uint32_t)v; r(1) = (uint32_t)(v >> 32); }
    void ret_f(float f) { std::memcpy(&jit->ExtRegs()[0], &f, 4); }
    void ret_d(double v) { uint64_t u; std::memcpy(&u, &v, 8); jit->ExtRegs()[0] = (uint32_t)u; jit->ExtRegs()[1] = (uint32_t)(u >> 32); }
    char* str(gaddr a) { return reinterpret_cast<char*>(m + a); }

    gaddr add_thunk(const std::string& name, Thunk t) {
        const uint32_t n = (uint32_t)thunks.size();
        const gaddr at = kThunks + 8 * n;
        if (at + 8 > kData) { std::fprintf(stderr, "guest: thunk page full\n"); std::abort(); }
        wr<uint32_t>(at, 0xEF000000u | n);   // svc #n
        wr<uint32_t>(at + 4, 0xE12FFF1Eu);   // bx lr
        thunks.push_back(std::move(t));
        thunk_names.push_back(name);
        return at;
    }
    gaddr data(uint32_t size, uint32_t align = 8) {
        data_next = (data_next + align - 1) & ~(align - 1);
        const gaddr a = data_next;
        data_next += size;
        return a;
    }

    // --- guest heap: size classes, 16-byte aligned ---
    static uint32_t cls(uint32_t n) { uint32_t c = 16; while (c < n) c <<= 1; return c; }
    gaddr malloc_(uint32_t n) {
        const uint32_t c = cls(n ? n : 1);
        auto& fl = free_lists[c];
        gaddr p;
        if (!fl.empty()) { p = fl.back(); fl.pop_back(); }
        else {
            if (heap_next + c > kHeapEnd) return 0;
            p = heap_next; heap_next += c;
        }
        sizes[p] = c;
        return p;
    }
    void free_(gaddr p) {
        if (!p) return;
        auto it = sizes.find(p);
        if (it == sizes.end()) { std::fprintf(stderr, "guest: free of unknown %08x\n", p); return; }
        free_lists[it->second].push_back(p);
        sizes.erase(it);
    }

    // --- printf: format from guest memory with guest varargs ---
    struct VarArgs {
        Impl& i; int reg; uint32_t sp;
        uint32_t next32() { if (reg < 4) return i.r(reg++); const uint32_t v = i.rd<uint32_t>(sp); sp += 4; return v; }
        uint64_t next64() {
            if (reg < 4) { if (reg & 1) reg++; if (reg < 4) { const uint64_t v = i.r(reg) | (uint64_t)i.r(reg + 1) << 32; reg += 2; return v; } }
            sp = (sp + 7) & ~7u; const uint64_t v = i.rd<uint64_t>(sp); sp += 8; return v;
        }
    };
    std::string format(const char* f, VarArgs va) {
        std::string out;
        char tmp[512];
        while (*f) {
            if (*f != '%') { out += *f++; continue; }
            const char* start = f++;
            if (*f == '%') { out += '%'; f++; continue; }
            std::string spec = "%";
            while (std::strchr("-+ #0", *f)) spec += *f++;
            if (*f == '*') { spec += std::to_string((int32_t)va.next32()); f++; } else while (std::isdigit((unsigned char)*f)) spec += *f++;
            if (*f == '.') { spec += *f++; if (*f == '*') { spec += std::to_string((int32_t)va.next32()); f++; } else while (std::isdigit((unsigned char)*f)) spec += *f++; }
            int lng = 0;   // 0 int, 2 long long
            while (std::strchr("hlLzjt", *f)) { if (*f == 'l' && f[1] == 'l') { lng = 2; f += 2; } else { if (*f == 'L') lng = 3; f++; } }
            const char c = *f++;
            spec += (lng == 2 && std::strchr("diouxX", c)) ? std::string("ll") + c : std::string(1, c);
            switch (c) {
            case 'd': case 'i': if (lng == 2) std::snprintf(tmp, sizeof tmp, spec.c_str(), (long long)va.next64()); else std::snprintf(tmp, sizeof tmp, spec.c_str(), (int32_t)va.next32()); break;
            case 'o': case 'u': case 'x': case 'X': if (lng == 2) std::snprintf(tmp, sizeof tmp, spec.c_str(), (unsigned long long)va.next64()); else std::snprintf(tmp, sizeof tmp, spec.c_str(), va.next32()); break;
            case 'c': std::snprintf(tmp, sizeof tmp, spec.c_str(), (int)va.next32()); break;
            case 's': { const uint32_t p = va.next32(); std::snprintf(tmp, sizeof tmp, spec.c_str(), p ? str(p) : "(null)"); break; }
            case 'p': std::snprintf(tmp, sizeof tmp, "0x%x", va.next32()); break;
            case 'f': case 'F': case 'e': case 'E': case 'g': case 'G': case 'a': case 'A': {
                const uint64_t u = va.next64(); double v; std::memcpy(&v, &u, 8);
                if (lng == 3) spec.erase(spec.size() - 1, 1), spec += c;   // long double == double on armhf
                std::snprintf(tmp, sizeof tmp, spec.c_str(), v); break;
            }
            default: out.append(start, f); continue;
            }
            out += tmp;
        }
        return out;
    }
    void put(gaddr buf, uint32_t n, const std::string& s) {
        if (n) { const size_t k = std::min<size_t>(s.size(), n - 1); std::memcpy(m + buf, s.data(), k); m[buf + k] = 0; }
        ret((uint32_t)s.size());
    }

    void install_libc();
};

// Host libc, libm and libstdc++ for the guest. Signatures follow armhf (floats/doubles in VFP registers).
void Guest::Impl::install_libc() {}

namespace {
using I = Guest::Impl;
struct Entry { const char* name; Thunk fn; };

void abort_named(I& i, const std::string& n) { std::fprintf(stderr, "guest: called %s (not supported), lr=%08x\n", n.c_str(), i.r(14)); std::abort(); }

std::vector<Entry> libc_table() {
    std::vector<Entry> t;
    auto add = [&](const char* n, Thunk f) { t.push_back({n, std::move(f)}); };
    // memory and strings
    add("malloc", [](I& i) { i.ret(i.malloc_(i.r(0))); });
    add("calloc", [](I& i) { const uint64_t n = (uint64_t)i.r(0) * i.r(1); const gaddr p = n > 0xffffffff ? 0 : i.malloc_((uint32_t)n); if (p) std::memset(i.m + p, 0, (size_t)n); i.ret(p); });
    add("realloc", [](I& i) {
        const gaddr old = i.r(0); const uint32_t n = i.r(1);
        const gaddr p = i.malloc_(n);
        if (old && p) { std::memcpy(i.m + p, i.m + old, std::min(n, i.sizes[old])); i.free_(old); }
        i.ret(p);
    });
    add("free", [](I& i) { i.free_(i.r(0)); });
    add("memcpy", [](I& i) { std::memcpy(i.m + i.r(0), i.m + i.r(1), i.r(2)); });
    add("memmove", [](I& i) { std::memmove(i.m + i.r(0), i.m + i.r(1), i.r(2)); });
    add("memset", [](I& i) { std::memset(i.m + i.r(0), (int)i.r(1), i.r(2)); });
    add("memcmp", [](I& i) { i.ret((uint32_t)std::memcmp(i.m + i.r(0), i.m + i.r(1), i.r(2))); });
    add("strlen", [](I& i) { i.ret((uint32_t)std::strlen(i.str(i.r(0)))); });
    add("strcmp", [](I& i) { i.ret((uint32_t)std::strcmp(i.str(i.r(0)), i.str(i.r(1)))); });
    add("strncmp", [](I& i) { i.ret((uint32_t)std::strncmp(i.str(i.r(0)), i.str(i.r(1)), i.r(2))); });
    add("strcasecmp", [](I& i) { i.ret((uint32_t)::strcasecmp(i.str(i.r(0)), i.str(i.r(1)))); });
    add("strncpy", [](I& i) { std::strncpy(i.str(i.r(0)), i.str(i.r(1)), i.r(2)); });
    add("strcpy", [](I& i) { std::strcpy(i.str(i.r(0)), i.str(i.r(1))); });
    add("strchr", [](I& i) { const char* p = std::strchr(i.str(i.r(0)), (int)i.r(1)); i.ret(p ? (uint32_t)(reinterpret_cast<const uint8_t*>(p) - i.m) : 0); });
    add("strrchr", [](I& i) { const char* p = std::strrchr(i.str(i.r(0)), (int)i.r(1)); i.ret(p ? (uint32_t)(reinterpret_cast<const uint8_t*>(p) - i.m) : 0); });
    add("strstr", [](I& i) { const char* p = std::strstr(i.str(i.r(0)), i.str(i.r(1))); i.ret(p ? (uint32_t)(reinterpret_cast<const uint8_t*>(p) - i.m) : 0); });
    auto strtol_ = [](I& i) { char* e; const long v = std::strtol(i.str(i.r(0)), &e, (int)i.r(2)); if (i.r(1)) i.wr<uint32_t>(i.r(1), (uint32_t)(reinterpret_cast<uint8_t*>(e) - i.m)); i.ret((uint32_t)(int32_t)v); };
    add("strtol", strtol_);
    add("__isoc23_strtol", strtol_);
    add("strtoul", [](I& i) { char* e; const unsigned long v = std::strtoul(i.str(i.r(0)), &e, (int)i.r(2)); if (i.r(1)) i.wr<uint32_t>(i.r(1), (uint32_t)(reinterpret_cast<uint8_t*>(e) - i.m)); i.ret((uint32_t)v); });
    add("__isoc23_strtoul", t.back().fn);
    add("strtod", [](I& i) { char* e; const double v = std::strtod(i.str(i.r(0)), &e); if (i.r(1)) i.wr<uint32_t>(i.r(1), (uint32_t)(reinterpret_cast<uint8_t*>(e) - i.m)); i.ret_d(v); });
    add("strtof", [](I& i) { char* e; const float v = std::strtof(i.str(i.r(0)), &e); if (i.r(1)) i.wr<uint32_t>(i.r(1), (uint32_t)(reinterpret_cast<uint8_t*>(e) - i.m)); i.ret_f(v); });
    add("atof", [](I& i) { i.ret_d(std::atof(i.str(i.r(0)))); });
    add("atoi", [](I& i) { i.ret((uint32_t)std::atoi(i.str(i.r(0)))); });
    add("getenv", [](I& i) { i.ret(0); });   // no environment for guests
    // printf family
    add("snprintf", [](I& i) { const gaddr b = i.r(0); const uint32_t n = i.r(1); i.put(b, n, i.format(i.str(i.r(2)), {i, 3, i.r(13)})); });
    add("__snprintf_chk", [](I& i) { const gaddr b = i.r(0); const uint32_t n = i.r(1); i.put(b, n, i.format(i.str(i.arg(4)), {i, 4, i.r(13) + 4})); });
    add("sprintf", [](I& i) { const gaddr b = i.r(0); i.put(b, 0x7fffffff, i.format(i.str(i.r(1)), {i, 2, i.r(13)})); });
    add("__sprintf_chk", [](I& i) { const gaddr b = i.r(0); i.put(b, 0x7fffffff, i.format(i.str(i.r(3)), {i, 4, i.r(13)})); });
    add("puts", [](I& i) { std::fprintf(stderr, "[guest] %s\n", i.str(i.r(0))); i.ret(1); });
    add("printf", [](I& i) { const std::string s = i.format(i.str(i.r(0)), {i, 1, i.r(13)}); std::fprintf(stderr, "[guest] %s", s.c_str()); i.ret((uint32_t)s.size()); });
    add("__printf_chk", [](I& i) { const std::string s = i.format(i.str(i.r(1)), {i, 2, i.r(13)}); std::fprintf(stderr, "[guest] %s", s.c_str()); i.ret((uint32_t)s.size()); });
    add("__fprintf_chk", [](I& i) { const std::string s = i.format(i.str(i.r(2)), {i, 3, i.r(13)}); std::fprintf(stderr, "[guest] %s", s.c_str()); i.ret((uint32_t)s.size()); });
    add("fprintf", [](I& i) { const std::string s = i.format(i.str(i.r(1)), {i, 2, i.r(13)}); std::fprintf(stderr, "[guest] %s", s.c_str()); i.ret((uint32_t)s.size()); });
    add("fflush", [](I& i) { i.ret(0); });
    add("fopen", [](I& i) { i.ret(0); });     // no files yet: fopen fails
    add("fopen64", [](I& i) { i.ret(0); });
    // time
    add("__clock_gettime64", [](I& i) { timespec ts; clock_gettime((clockid_t)i.r(0), &ts); const gaddr p = i.r(1); i.wr<int64_t>(p, ts.tv_sec); i.wr<int32_t>(p + 8, (int32_t)ts.tv_nsec); i.wr<int32_t>(p + 12, 0); i.ret(0); });
    add("clock_gettime", [](I& i) { timespec ts; clock_gettime((clockid_t)i.r(0), &ts); const gaddr p = i.r(1); i.wr<int32_t>(p, (int32_t)ts.tv_sec); i.wr<int32_t>(p + 4, (int32_t)ts.tv_nsec); i.ret(0); });
    // threads: one guest thread, so locks are no-ops
    for (const char* n : {"pthread_mutex_init", "pthread_mutex_destroy", "pthread_mutex_lock", "pthread_mutex_unlock", "pthread_mutex_trylock",
                          "pthread_mutexattr_init", "pthread_mutexattr_destroy", "pthread_mutexattr_settype", "pthread_mutexattr_setprotocol"})
        add(n, [](I& i) { i.ret(0); });
    // process
    add("raise", [](I& i) { std::fprintf(stderr, "guest: raise(%u)\n", i.r(0)); std::abort(); });
    add("abort", [](I& i) { abort_named(i, "abort"); });
    add("__stack_chk_fail", [](I& i) { abort_named(i, "__stack_chk_fail (stack smashed)"); });
    add("__cxa_finalize", [](I&) {});
    add("__cxa_atexit", [](I& i) { i.ret(0); });
    add("__aeabi_atexit", [](I& i) { i.ret(0); });
    // C++ runtime
    for (const char* n : {"_Znwj", "_Znaj", "_ZnwjRKSt9nothrow_t", "_ZnajRKSt9nothrow_t"})
        add(n, [](I& i) { i.ret(i.malloc_(i.r(0))); });
    for (const char* n : {"_ZdlPv", "_ZdaPv", "_ZdlPvj", "_ZdaPvj", "_ZdlPvRKSt9nothrow_t", "_ZdaPvRKSt9nothrow_t"})
        add(n, [](I& i) { i.free_(i.r(0)); });
    add("__cxa_guard_acquire", [](I& i) { i.ret(i.m[i.r(0)] ? 0 : 1); });
    add("__cxa_guard_release", [](I& i) { i.m[i.r(0)] = 1; });
    add("__cxa_guard_abort", [](I&) {});
    add("__cxa_pure_virtual", [](I& i) { abort_named(i, "__cxa_pure_virtual"); });
    // libm (double in d0/d1, float in s0/s1)
#define D1(n) add(#n, [](I& i) { i.ret_d(std::n(i.d(0))); });
#define D2(n) add(#n, [](I& i) { i.ret_d(std::n(i.d(0), i.d(1))); });
#define F1(n, h) add(#n, [](I& i) { i.ret_f(std::h(i.s(0))); });
#define F2(n, h) add(#n, [](I& i) { i.ret_f(std::h(i.s(0), i.s(1))); });
    D1(exp) D1(exp2) D1(log) D1(log2) D1(log10) D1(log1p) D1(expm1) D1(sin) D1(cos) D1(tan) D1(sinh) D1(cosh) D1(tanh) D1(asin) D1(acos) D1(atan)
    D1(sqrt) D1(floor) D1(ceil) D1(round) D1(trunc) D1(fabs) D1(cbrt)
    D2(pow) D2(atan2) D2(fmod) D2(fmax) D2(fmin) D2(hypot)
    F1(expf, exp) F1(exp2f, exp2) F1(logf, log) F1(log2f, log2) F1(log10f, log10) F1(sinf, sin) F1(cosf, cos) F1(tanf, tan) F1(tanhf, tanh)
    F1(sqrtf, sqrt) F1(floorf, floor) F1(ceilf, ceil) F1(roundf, round) F1(truncf, trunc) F1(fabsf, fabs) F1(atanf, atan)
    F2(powf, pow) F2(atan2f, atan2) F2(fmodf, fmod) F2(fmaxf, fmax) F2(fminf, fmin)
    add("lrintf", [](I& i) { i.ret((uint32_t)(int32_t)std::lrint(i.s(0))); });
    add("lroundf", [](I& i) { i.ret((uint32_t)(int32_t)std::lround(i.s(0))); });
    add("lrint", [](I& i) { i.ret((uint32_t)(int32_t)std::lrint(i.d(0))); });
    add("lround", [](I& i) { i.ret((uint32_t)(int32_t)std::lround(i.d(0))); });
    add("sincosf", [](I& i) { const float x = i.s(0); i.wr<float>(i.r(0), std::sin(x)); i.wr<float>(i.r(1), std::cos(x)); });
    add("sincos", [](I& i) { const double x = i.d(0); i.wr<double>(i.r(0), std::sin(x)); i.wr<double>(i.r(1), std::cos(x)); });
#undef D1
#undef D2
#undef F1
#undef F2
    return t;
}

// Imports that are data, not code.
bool is_data_import(const std::string& n) { return n == "__stack_chk_guard" || n == "_ZSt7nothrow" || n == "stderr" || n == "stdout"; }
}  // namespace

Guest::Guest() {
    void* p = mmap(nullptr, kSpace, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) { std::perror("mmap 4 GB"); std::abort(); }
    mem_ = static_cast<uint8_t*>(p);
    impl_ = new Impl(*this);
    // index 0: a trap at guest address 0 (a call through a null pointer, e.g. an unresolved weak import)
    impl_->add_thunk("<null>", [](I& i) { std::fprintf(stderr, "guest: call to address 0 from lr=%08x\n", i.r(14)); std::abort(); });
    impl_->wr<uint32_t>(0, 0xEF000000u);   // svc #0 at address 0
    const gaddr ret = kData - 8;
    impl_->wr<uint32_t>(ret, 0xEF000000u | kRetSvc);

    Dynarmic::A32::UserConfig cfg;
    cfg.callbacks = impl_;
    cfg.global_monitor = &impl_->monitor;
    cfg.fastmem_pointer = reinterpret_cast<uintptr_t>(mem_);
    cfg.arch_version = Dynarmic::A32::ArchVersion::v7;   // the plugins are built for armv7-a
    cfg.enable_cycle_counting = false;
    if (std::getenv("MPC_HOST_UNSAFE")) {   // faster float maths, less exact NaN/rounding handling (dynarmic's "unsafe" flags)
        cfg.unsafe_optimizations = true;
        cfg.optimizations |= Dynarmic::OptimizationFlag::Unsafe_UnfuseFMA | Dynarmic::OptimizationFlag::Unsafe_ReducedErrorFP |
                             Dynarmic::OptimizationFlag::Unsafe_InaccurateNaN | Dynarmic::OptimizationFlag::Unsafe_IgnoreStandardFPCRValue;
    }
    impl_->jit = std::make_unique<Dynarmic::A32::Jit>(cfg);
}

Guest::~Guest() {
    delete impl_;
    munmap(mem_, kSpace);
}

uint32_t Guest::rd32(gaddr a) const { return impl_->rd<uint32_t>(a); }
void Guest::wr32(gaddr a, uint32_t v) { impl_->wr<uint32_t>(a, v); }
gaddr Guest::alloc(uint32_t n) { return impl_->malloc_(n); }
void Guest::dealloc(gaddr p) { impl_->free_(p); }
gaddr Guest::strdup(const char* s) { const uint32_t n = (uint32_t)std::strlen(s) + 1; const gaddr p = alloc(n); std::memcpy(mem_ + p, s, n); return p; }

gaddr Guest::symbol(const char* name) const {
    auto it = impl_->dynsyms.find(name);
    return it == impl_->dynsyms.end() ? 0 : it->second;
}

gaddr Guest::host_callback(HostCallback fn) {
    return impl_->add_thunk("<host callback>", [fn](I& i) {
        float opt; std::memcpy(&opt, &i.jit->ExtRegs()[0], 4);
        i.ret(fn(i.g, i.r(0), (int32_t)i.r(1), (int32_t)i.r(2), (int32_t)i.r(3), i.arg(4), opt));
    });
}

uint32_t Guest::call(gaddr fn, const std::vector<uint32_t>& ints, const std::vector<float>& floats) {
    I& i = *impl_;
    if (i.depth) { std::fprintf(stderr, "guest: nested call from a thunk (not supported)\n"); std::abort(); }
    auto& R = i.jit->Regs();
    const auto saved = R;
    uint32_t sp = R[13] ? R[13] : kStackTop;
    const size_t nstack = ints.size() > 4 ? ints.size() - 4 : 0;
    sp -= (uint32_t)(4 * nstack);
    sp &= ~7u;
    for (size_t k = 0; k < nstack; k++) i.wr<uint32_t>(sp + 4 * (uint32_t)k, ints[4 + k]);
    for (size_t k = 0; k < 4 && k < ints.size(); k++) R[k] = ints[k];
    for (size_t k = 0; k < floats.size() && k < 16; k++) std::memcpy(&i.jit->ExtRegs()[k], &floats[k], 4);
    R[13] = sp;
    R[14] = kData - 8;   // return stub
    R[15] = fn & ~1u;
    i.jit->SetCpsr(0x10 | ((fn & 1) ? 0x20 : 0));   // user mode, Thumb if bit 0
    i.depth++;
    i.jit->Run();
    i.jit->ClearHalt(Dynarmic::HaltReason::UserDefined1);
    i.depth--;
    const uint32_t r0 = R[0];
    R = saved;
    R[0] = r0;
    if (!saved[13]) R[13] = 0;
    return r0;
}

float Guest::call_f(gaddr fn, const std::vector<uint32_t>& ints, const std::vector<float>& floats) {
    call(fn, ints, floats);
    return impl_->s(0);
}

bool Guest::load(const std::string& path) {
    I& i = *impl_;
    std::ifstream f(path, std::ios::binary);
    if (!f) { err_ = "cannot open " + path; return false; }
    std::vector<uint8_t> file((std::istreambuf_iterator<char>(f)), {});
    if (file.size() < sizeof(Elf32_Ehdr)) { err_ = "not an ELF file"; return false; }
    const auto* eh = reinterpret_cast<const Elf32_Ehdr*>(file.data());
    if (std::memcmp(eh->e_ident, ELFMAG, SELFMAG) || eh->e_ident[EI_CLASS] != ELFCLASS32 || eh->e_machine != EM_ARM || eh->e_type != ET_DYN) {
        err_ = "not a 32-bit ARM shared object (a Gen2 aarch64 build needs the A64 front end)"; return false;
    }
    const auto* ph = reinterpret_cast<const Elf32_Phdr*>(file.data() + eh->e_phoff);
    const Elf32_Dyn* dyn = nullptr;
    for (int k = 0; k < eh->e_phnum; k++) {
        if (ph[k].p_type == PT_LOAD) {
            std::memcpy(mem_ + kLoad + ph[k].p_vaddr, file.data() + ph[k].p_offset, ph[k].p_filesz);
            std::memset(mem_ + kLoad + ph[k].p_vaddr + ph[k].p_filesz, 0, ph[k].p_memsz - ph[k].p_filesz);
        } else if (ph[k].p_type == PT_DYNAMIC) dyn = reinterpret_cast<const Elf32_Dyn*>(mem_ + kLoad + ph[k].p_vaddr);
    }
    if (!dyn) { err_ = "no PT_DYNAMIC"; return false; }
    // dynamic section (read after the copy: it lives in a loaded segment)
    uint32_t symtab = 0, strtab = 0, rel = 0, relsz = 0, jmprel = 0, pltrelsz = 0, init = 0, init_array = 0, init_arraysz = 0;
    for (const Elf32_Dyn* d = reinterpret_cast<const Elf32_Dyn*>(mem_ + (reinterpret_cast<const uint8_t*>(dyn) - mem_)); d->d_tag != DT_NULL; d++) {
        switch (d->d_tag) {
        case DT_SYMTAB: symtab = d->d_un.d_ptr; break;
        case DT_STRTAB: strtab = d->d_un.d_ptr; break;
        case DT_REL: rel = d->d_un.d_ptr; break;
        case DT_RELSZ: relsz = d->d_un.d_val; break;
        case DT_JMPREL: jmprel = d->d_un.d_ptr; break;
        case DT_PLTRELSZ: pltrelsz = d->d_un.d_val; break;
        case DT_INIT: init = d->d_un.d_ptr; break;
        case DT_INIT_ARRAY: init_array = d->d_un.d_ptr; break;
        case DT_INIT_ARRAYSZ: init_arraysz = d->d_un.d_val; break;
        case DT_RELA: err_ = "RELA relocations (not armhf)"; return false;
        }
    }
    // symbol count from the section headers (.dynsym)
    uint32_t nsyms = 0;
    const auto* sh = reinterpret_cast<const Elf32_Shdr*>(file.data() + eh->e_shoff);
    for (int k = 0; k < eh->e_shnum; k++) if (sh[k].sh_type == SHT_DYNSYM) nsyms = sh[k].sh_size / sizeof(Elf32_Sym);
    const auto* syms = reinterpret_cast<const Elf32_Sym*>(mem_ + kLoad + symtab);
    const char* strs = reinterpret_cast<const char*>(mem_ + kLoad + strtab);

    // imports -> thunks
    std::unordered_map<std::string, Thunk> table;
    for (auto& e : libc_table()) table.emplace(e.name, std::move(e.fn));
    std::vector<gaddr> symaddr(nsyms, 0);
    for (uint32_t k = 1; k < nsyms; k++) {
        const std::string name = strs + syms[k].st_name;
        if (syms[k].st_shndx != SHN_UNDEF) {
            symaddr[k] = kLoad + syms[k].st_value;
            if (ELF32_ST_BIND(syms[k].st_info) != STB_LOCAL) i.dynsyms[name] = symaddr[k];
            continue;
        }
        if (name.empty()) continue;
        if (is_data_import(name)) {
            const gaddr a = i.data(64);
            if (name == "__stack_chk_guard") i.wr<uint32_t>(a, 0xC0FFEE00u);
            symaddr[k] = a;
            continue;
        }
        if (name == "__ctype_b_loc") {
            // glibc's table is indexed from -128; both armhf and x86-64 glibc are little-endian with the same bits
            const gaddr tbl = i.data(384 * 2, 4), pp = i.data(4, 4);
            std::memcpy(mem_ + tbl, *__ctype_b_loc() - 128, 384 * 2);
            i.wr<uint32_t>(pp, tbl + 256);
            symaddr[k] = i.add_thunk(name, [pp](I& ii) { ii.ret(pp); });
            continue;
        }
        auto it = table.find(name);
        if (it != table.end()) { symaddr[k] = i.add_thunk(name, it->second); continue; }
        if (ELF32_ST_BIND(syms[k].st_info) == STB_WEAK) { symaddr[k] = 0; continue; }
        missing_.push_back(name);
        symaddr[k] = i.add_thunk(name, [name](I& ii) { abort_named(ii, name); });
    }

    // relocations
    auto apply = [&](uint32_t at, uint32_t size) -> bool {
        for (uint32_t off = 0; off < size; off += sizeof(Elf32_Rel)) {
            const auto* rr = reinterpret_cast<const Elf32_Rel*>(mem_ + kLoad + at + off);
            const uint32_t type = ELF32_R_TYPE(rr->r_info), sym = ELF32_R_SYM(rr->r_info);
            const gaddr P = kLoad + rr->r_offset;
            const uint32_t S = sym < nsyms ? symaddr[sym] : 0;
            switch (type) {
            case R_ARM_RELATIVE: i.wr<uint32_t>(P, i.rd<uint32_t>(P) + kLoad); break;
            case R_ARM_GLOB_DAT: case R_ARM_JUMP_SLOT: i.wr<uint32_t>(P, S); break;
            case R_ARM_ABS32: i.wr<uint32_t>(P, i.rd<uint32_t>(P) + S); break;
            case R_ARM_NONE: break;
            default: err_ = "unsupported relocation type " + std::to_string(type); return false;
            }
        }
        return true;
    };
    if (!apply(rel, relsz) || !apply(jmprel, pltrelsz)) return false;

    // constructors
    if (init) call(kLoad + init, {});
    for (uint32_t k = 0; k < init_arraysz / 4; k++) {
        const gaddr fn = i.rd<uint32_t>(kLoad + init_array + 4 * k);
        if (fn && fn != 0xffffffffu) call(fn, {});
    }
    return true;
}

}  // namespace mpchost
