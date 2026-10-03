        .arm
        .section .stub1,"a"
        .asciz "DrumSynth:Multi"
        .section .stub2,"ax"
        .globl stub_eq
stub_eq:                        @ stands in for juce::String::operator==(const char*): return r1 so the test sees which string it got
        mov   r0, r1
        bx    lr
