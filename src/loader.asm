; Invoked by BASIC in 128K mode. Load the same initial memory image as the SNA.
    device ZXSPECTRUM128
    org #7000
loader:
    ld sp,#7ef0
    res 4,(iy+1)
    ld hl,blocks
.block:
    ld a,(hl) : inc hl
    cp #ff : jp z,#8000
    ld bc,#7ffd : out (c),a : ld (23388),a
    ld e,(hl) : inc hl : ld d,(hl) : inc hl
    push de : pop ix
    ld e,(hl) : inc hl : ld d,(hl) : inc hl
    push hl
    ld a,255 : scf : call 1366
    jr nc,.error
    pop hl : jr .block
.error:
    ld a,2 : out (#fe),a : jr .error
blocks:
    include "blocks.inc"
    db #ff
    savebin "loader.bin",loader,$-loader
