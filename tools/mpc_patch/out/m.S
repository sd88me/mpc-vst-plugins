@ Name matcher for the MPC 3.9.1.2 drum-layout patch. Linked at 0x6872980: zero padding after the R+X LOAD segment's file
@ data (ends 0x687288c), inside its last mapped page (ends 0x6873000), after colours.S (0x6872900-0x6872948).
@ Called through cave2.S from the helper at 0x2494954, which `ldr r2,[r0]` first.
@ In: r0 = juce::String* (the plugin's name), r2 = its UTF-8 text, lr = return address into the caller (0x24fe2e0).
@ Out: r0 = 1 if the name is in `table` below, else the result of the original String == "DrumSynth:Multi" check
@ (a tail call; r0 still the String*, lr intact). Clobbers r1, r3, ip as the old cave did; r4 is saved.
@ Adding a plugin = one more .asciz line in the table; the whole routine has ~1.8 KB of room left in that page.
        .arm
        .section .mtch,"ax"
        .globl mstart
        .equ  BASE, 0x6872980
mstart:
        push  {r4}
        adr   r1, table
next:   ldrb  r4, [r1]              @ first char of the entry; 0 = end of table
        cmp   r4, #0
        beq   none
        mov   r3, r2                @ restart at the start of the plugin name
cmpl:   ldrb  r4, [r3], #1
        ldrb  ip, [r1], #1
        cmp   r4, ip
        bne   skip
        cmp   r4, #0
        bne   cmpl
        pop   {r4}                  @ both strings ended together: a match
        mov   r0, #1
        bx    lr
skip:   cmp   ip, #0                @ the table entry already ended: r1 is the next entry
        beq   next
skl:    ldrb  ip, [r1], #1          @ else skip the rest of this entry
        cmp   ip, #0
        bne   skl
        b     next
none:   pop   {r4}
        ldr   r1, L1
Ladd1:  add   r1, pc, r1            @ r1 = 0x4ab2760 "DrumSynth:Multi"
        ldr   ip, L2
Ladd2:  add   pc, pc, ip            @ -> 0x9289ec  bool juce::String::operator==(const char*)
L1:     .word 0x4ab2760 - (BASE + (Ladd1 - mstart) + 8)
L2:     .word 0x9289ec  - (BASE + (Ladd2 - mstart) + 8)
table:
        .asciz "Machinedrum Module"
        .asciz "Machinemodule"
        .asciz "6W6"
        .asciz "8W8"
        .asciz "CW-78"
        .asciz "9W9"
        .asciz "TR-MPC"
        .asciz "Lucky Dip"
        .byte 0
