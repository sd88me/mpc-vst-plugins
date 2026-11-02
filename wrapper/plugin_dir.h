/* Where is this plugin? The directory its own .so was loaded from, so an engine can find presets, banks, ROMs and
 * other files shipped next to it wherever it was installed (/sdcard/Synths/<folder>, /media/<card>/Synths/<folder>,
 * or the old /sdcard/vst): no hardcoded /sdcard, and no need to parse MPC.settings. The path comes from /proc/self/maps (the mapping that holds this
 * function), which is the file= path the host passed to dlopen().
 *
 *   char dir[512];
 *   if (mpc_plugin_dir(dir, sizeof dir)) ...      dir = "/sdcard/Synths/<folder>", no trailing slash
 *
 * Define _GNU_SOURCE before the first #include (vst2_wrap.c does). Header-only, static inline. Returns 1 on
 * success, 0 if it can't tell (buf is then ""). Deliberately avoids dladdr(): built against glibc >= 2.34 it binds to
 * GLIBC_2.34, which MPC OS 2.x (glibc 2.32) lacks, so the .so would not load there. */
#ifndef MPC_PLUGIN_DIR_H
#define MPC_PLUGIN_DIR_H

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#endif

static inline int mpc_dirname_of(const char *path, char *buf, size_t n) {
    const char *slash = strrchr(path, '/');
#ifdef _WIN32
    const char *bs = strrchr(path, '\\');
    if (bs && (!slash || bs > slash)) slash = bs;
#endif
    size_t len = slash ? (size_t)(slash - path) : 0;
    if (!slash || len == 0 || len >= n) return 0;
    memcpy(buf, path, len);
    buf[len] = 0;
    return 1;
}

static inline int mpc_plugin_dir(char *buf, size_t n) {
    if (n) buf[0] = 0;
    if (!n) return 0;
#ifdef _WIN32   /* the DLL that holds this function */
    HMODULE m = NULL;
    char path[MAX_PATH];
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCSTR)&mpc_plugin_dir, &m) || !GetModuleFileNameA(m, path, sizeof path))
        return 0;
    return mpc_dirname_of(path, buf, n);
#else
    FILE *f = fopen("/proc/self/maps", "r");   /* the mapping that contains this function */
    if (!f) return 0;
    char line[1024];
    unsigned long me = (unsigned long)&mpc_plugin_dir;
    int ok = 0;
    while (!ok && fgets(line, sizeof line, f)) {
        unsigned long lo, hi;
        char *p = strchr(line, '/');
        if (sscanf(line, "%lx-%lx", &lo, &hi) == 2 && me >= lo && me < hi && p) {
            p[strcspn(p, "\n")] = 0;
            ok = mpc_dirname_of(p, buf, n);
        }
    }
    fclose(f);
    return ok;
#endif
}

#endif
