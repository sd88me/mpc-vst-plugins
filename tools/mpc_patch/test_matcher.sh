#!/bin/sh
# Run matcher.S under qemu-user (arm32v7 container) at its real address, with the two stock-binary targets stubbed:
#   docker run --rm --platform linux/arm/v7 -v "$PWD/patch":/p -w /p arm32v7/gcc:12 sh test_matcher.sh
set -e
mkdir -p out
sed -e 's/_start/mstart/g' -e 's/^ *\.text/        .section .mtch,"ax"/' matcher.S > out/m.S
cat > out/stubs.S <<'EOF'
        .arm
        .section .stub1,"a"
        .asciz "DrumSynth:Multi"
        .section .stub2,"ax"
        .globl stub_eq
stub_eq:                        @ stands in for juce::String::operator==(const char*): return r1 so the test sees which string it got
        mov   r0, r1
        bx    lr
EOF
cat > out/t.c <<'EOF'
#include <stdio.h>
#include <string.h>
static unsigned call(const char *text) {
    register unsigned r0 __asm__("r0") = 0x1234;
    register const char *r2 __asm__("r2") = text;
    register unsigned r4 __asm__("r4") = 0xC0FFEE;
    __asm__ volatile("blx %[f]" : "+r"(r0), "+r"(r4) : "r"(r2), [f] "r"(0x6872980u) : "r1", "r3", "ip", "lr", "cc", "memory");
    if (r4 != 0xC0FFEE) { printf("r4 NOT PRESERVED\n"); return 0xdead; }
    return r0;
}
int main(void) {
    struct { const char *name; unsigned want; } t[] = {
        {"Machinedrum Module", 1}, {"6W6", 1}, {"8W8", 1}, {"CW-78", 1}, {"9W9", 1}, {"TR-MPC", 1},
        {"Machinemodule", 1}, {"Lucky Dip", 1},
        {"DrumSynth:Multi", 0x4ab2760}, {"Machinedrum Mod", 0x4ab2760}, {"Machinedrum Modules", 0x4ab2760},
        {"6W", 0x4ab2760}, {"6W66", 0x4ab2760}, {"TR-MPC2", 0x4ab2760}, {"CW-7", 0x4ab2760}, {"", 0x4ab2760},
        {"Monomodule One", 0x4ab2760}, {"Clementine-XT", 0x4ab2760}, {"Dexed", 0x4ab2760}, {"9W", 0x4ab2760}, {"Lucky", 0x4ab2760}, {"Lucky Dips", 0x4ab2760}, {"Machinemodule Tap", 0x4ab2760},
    };
    int bad = 0;
    for (unsigned i = 0; i < sizeof t / sizeof *t; ++i) {
        unsigned got = call(t[i].name);
        int ok = got == t[i].want; bad += !ok;
        printf("%s \"%s\" -> %#x (want %#x)\n", ok ? "ok  " : "FAIL", t[i].name, got, t[i].want);
    }
    puts(bad ? "FAILED" : "PASSED");
    return bad != 0;
}
EOF
as -march=armv7-a out/m.S -o out/m.o
as -march=armv7-a out/stubs.S -o out/stubs.o
gcc -O1 -static -c out/t.c -o out/t.o
gcc -static out/t.o out/m.o out/stubs.o -o out/t \
    -Wl,--section-start=.mtch=0x6872980 -Wl,--section-start=.stub1=0x4ab2760 -Wl,--section-start=.stub2=0x9289ec
./out/t
