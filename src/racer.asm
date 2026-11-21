; Coast Run. Code, stack, raster table and pending writes live in fixed bank 2.
    device ZXSPECTRUM128
    include "layout.inc"
    ; SP streams a 14-byte tile job. Both loops use the same fixed-cost stores.
    macro BLIT_TILE
        pop hl                      ; normal attribute address
        pop de                      ; matching bitmap address
        pop bc                      ; the two palettes
        ld (hl),c
        set 7,h
        ld (hl),b
        ex de,hl
        ld e,l
        ld d,h
        set 7,d
        dup 4
            pop bc
            ld a,c : ld (hl),a : ld (de),a : inc h : inc d
            ld a,b : ld (hl),a : ld (de),a : inc h : inc d
        edup
    endm
    org #8000
start:
    di
    ld sp,#bdf0
    ld bc,#7ffd
    ld a,#17
    out (c),a
    xor a
    out (#fe),a
    ld hl,#be00
    ld de,#be01
    ld bc,256
    ld (hl),#bf
    ldir
    ld a,#be
    ld i,a
    im 2
    call updateHud
frameWait:
    ei
    halt
    di
    ; These two blits have identical instruction paths for all game states.
    ; They finish before the first active display fetch (including on +2A).
    ld (restoreSP+1),sp
    ld sp,jobs
    ld a,TOP_TILES
tileLoop:
    ex af,af'
    BLIT_TILE
    ex af,af'
    dec a
    jp nz,tileLoop

riderSource:
    ld sp,riderArt+162
    ; Cache the underlying two attributes and shared bitmap before compositing.
    ; POP BC supplies transparency mask C and solid ink bits B on each line.
    dup 3, ry
        dup 3, rx
            ld a,(bikeCol) : add a,((18+ry)*32+rx) & 255 : ld l,a : ld e,a
            ld h,#5a : ld d,#da
            ld a,(hl) : ld (underlay+(ry*3+rx)*10),a
            ld a,(de) : ld (underlay+(ry*3+rx)*10+1),a
            pop bc : ld (hl),c : ld a,c : ld (de),a
            ld h,#50 : ld d,#d0
            dup 8, scan
                ld a,(hl) : ld (underlay+(ry*3+rx)*10+2+scan),a
                pop bc : and c : or b : ld (hl),a : ld (de),a
                inc h : inc d
            edup
        edup
    edup
restoreSP:
    ld sp,0
blitDone:
    ; Calibrated from IM2 entry. No video RAM or I/O access in this delay.
    ld bc,582
.align:
    dec bc : ld a,b : or c : jr nz,.align
phasePointer:
    ld hl,phaseTable
    ld bc,#7ffd
    ld e,DASH-HORIZON
scanline:
    ld a,(hl)
    inc hl
latch:
    out (c),a
    ld d,11
.delay:
    dec d : jr nz,.delay
    ld a,0
    nop
    dec e
    jp nz,scanline              ; 228 T from OUT to OUT, including the final line
    ld a,#17
    out (c),a
rasterDone:
    ; The ULA has passed the rider. Restore the track before applying next
    ; frame's updates, so a rival, a road marking and the rider can overlap.
    dup 3, ry
        dup 3, rx
            ld a,(bikeCol) : add a,((18+ry)*32+rx) & 255 : ld l,a : ld e,a
            ld h,#5a : ld d,#da
            ld a,(underlay+(ry*3+rx)*10) : ld (hl),a
            ld a,(underlay+(ry*3+rx)*10+1) : ld (de),a
            ld h,#50 : ld d,#d0
            dup 8, scan
                ld a,(underlay+(ry*3+rx)*10+2+scan) : ld (hl),a : ld (de),a
                inc h : inc d
            edup
        edup
    edup
    call controls
    call advance
    call prepareTiles
    call updateHud
    jp frameWait

controls:
    ld hl,riderArt+162
    ld bc,#dffe                 ; P, O, I, U, Y
    in a,(c)
    cpl
    and 3
    ld d,a
    ld a,(steerTimer)
    or a
    jr z,.canSteer
    dec a
    ld (steerTimer),a
    jr .lean
.canSteer:
    ld a,d
    cp 1
    call z,steerRight
    ld a,d
    cp 2
    call z,steerLeft
    ld a,d
    or a
    jr z,.lean
    ld a,2
    ld (steerTimer),a
.lean:
    ld a,d
    cp 1
    jr nz,.notRight
    ld hl,riderArt+324
.notRight:
    cp 2
    jr nz,.leanDone
    ld hl,riderArt
.leanDone:
    ld (riderSource+1),hl
    ld bc,#fbfe                 ; Q accelerates, A brakes
    in a,(c)
    cpl : and 1 : ld d,a
    ld b,#fd
    in a,(c)
    cpl : and 1 : add a,a : or d : ld d,a
    ld a,(gearTimer)
    or a
    jr z,.gear
    dec a : ld (gearTimer),a
    ret
.gear:
    ld a,d
    cp 1
    jr z,.up
    cp 2
    ret nz
    ld a,(gear)
    cp 1 : ret z
    dec a : jr .set
.up:
    ld a,(gear)
    cp 4 : ret z
    inc a
.set:
    ld (gear),a
    ld a,7 : ld (gearTimer),a
    ret

steerLeft:
    ld a,(bikeCol)
    or a : ret z
    dec a : ld (bikeCol),a : ret
steerRight:
    ld a,(bikeCol)
    cp 29 : ret z
    inc a : ld (bikeCol),a : ret

advance:
    ld a,(bikeCol)
    or a : jr z,.grass
    cp 29 : jr c,.travel
.grass:
    ld a,1 : ld (gear),a
.travel:
    ld a,(gear) : ld b,a
    ld a,(phase) : add a,b : and 31 : ld (phase),a
    ; The raster phase is a distance coordinate, wrapped independently of laps.
    ld e,a : ld d,0
    ld hl,phaseTable
    add a,a : add a,a : add a,a   ; 8*p (fits in a byte)
    ld e,a
    add hl,de
    sla e : rl d                 ; 16*p
    sla e : rl d                 ; 32*p
    add hl,de
    sla e : rl d                 ; 64*p
    add hl,de                    ; 104*p
    ld (phasePointer+1),hl
    ld a,(travel) : add a,b
    cp 24
    jr nc,.next
    ld (travel),a : ret
.next:
    sub 24 : ld (travel),a
    ld a,(step) : inc a : and 63 : ld (step),a
    ; A bend nudges the rider to the outside every other track step.
    bit 0,a : jr nz,.descriptor
    cp 4 : jr c,.descriptor
    cp 29 : jr c,.left
    cp 36 : jr c,.descriptor
    cp 61 : jr nc,.descriptor
    call steerRight : jr .descriptor
.left:
    call steerLeft
.descriptor:
    ld a,(step)
    ld l,a : ld h,0 : add hl,hl
    ld e,l : ld d,h : add hl,hl : add hl,de
    ld de,course : add hl,de
    ld a,(hl) : or #10 : ld (dataPage),a : inc hl
    ld a,(hl) : ld (batches),a : inc hl
    ld b,(hl) : inc hl
    ld c,(hl) : inc hl
    ld e,(hl) : inc hl : ld d,(hl) : ld (cursor),de
    ld (rivalFoot),bc
    ret
judgePass:
    ; Once per pass, compare centres at the rider's depth.
    ld bc,(rivalFoot)
    ld a,c : cp 160 : ret c
    ld a,(bikeCol) : add a,a : add a,a : add a,a : add a,12
    sub b : add a,12 : cp 25
    jr nc,.clear
    ld a,1 : ld (gear),a
    ld a,20 : ld (bump),a : ret
.clear:
    ld a,(passes) : add a,1 : daa : ld (passes),a : ret

prepareTiles:
    ld a,(batches) : or a : ret z
    dec a : ld (batches),a
    ld (streamSP+1),sp
    ld sp,(cursor)
    ld a,(dataPage)
    ld bc,#7ffd : out (c),a
    ld de,jobs
    ld a,BATCH_TILES
.tile:
    ex af,af'
    pop hl                      ; attribute low byte is also bitmap low byte
    ld a,l : ld (de),a : inc de
    ld a,h : ld (de),a : inc de
    ld a,l : ld (de),a : inc de
    ld a,h : rlca : rlca : rlca : and #18 : or #40 : ld (de),a : inc de
    pop hl
    dup 10
        ldi
    edup
    ex af,af'
    dec a : jp nz,.tile
    ld (cursor),sp
    ld bc,#7ffd : ld a,#17 : out (c),a
    ; The beam has passed the road and the previous rider is restored. Apply
    ; the last five jobs here, then the first 24 before the next active display.
    ld sp,jobs+TOP_TILES*14
    ld a,BOTTOM_TILES
.bottomTile:
    ex af,af'
    BLIT_TILE
    ex af,af'
    dec a : jp nz,.bottomTile
streamSP:
    ld sp,0
    ld a,(batches) : or a : ret nz
    jp judgePass

updateHud:
    ; The ULA reads the dashboard from bank 5 alone.
    ld a,(gear) : ld b,a
    ld hl,#5800+22*32+16
    ld c,4
.bars:
    ld a,b : or a : jr z,.unlit
    dec b : ld a,#46 : jr .bar
.unlit:
    ld a,#01
.bar:
    ld (hl),a : inc hl : dec c : jr nz,.bars
    ld a,(bump) : or a : jr z,.steady
    dec a : ld (bump),a : ld a,#42
    jr .passColour
.steady:
    ld a,#47
.passColour:
    ld (#5800+22*32+25),a
    ld (#5800+22*32+26),a
    ld a,(passes) : rrca : rrca : rrca : rrca
    ld de,#50c0+25 : call digit
    ld a,(passes) : ld de,#50c0+26
digit:
    and 15 : add a,a : add a,a : add a,a
    ld l,a : ld h,0 : ld bc,digits : add hl,bc
    dup 8
        ld a,(hl) : ld (de),a : inc hl : inc d
    edup
    ret

bikeCol:    db 14
gear:       db 2
phase:      db 0
travel:     db 0
step:       db 0
passes:     db 0
bump:       db 0
steerTimer: db 0
gearTimer:  db 0
batches:    db 0
dataPage:   db 0
rivalFoot:  dw 0
cursor:     dw 0
underlay:   ds 90
jobs:
    dup BATCH_TILES
        dw #6800,#6000,0
        ds 8
    edup
course:     include "course.inc"
riderArt:   incbin "riders.bin"
phaseTable: incbin "road-phases.bin"
digits:     incbin "digits.bin"
    assert $ < #bd00
    org #bfbf
irq:
    ei : ret
    savebin "core.bin",start,$-start
