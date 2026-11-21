; Spectrum Attribute Racer. Code, stack and raster tables live in fixed bank 2.
    device ZXSPECTRUM128
    include "layout.inc"
BIKE_COL equ 14
    ; Equal-length hit and miss paths. Collect the changed tile ID and its
    ; column in two working pages of uncontended RAM while the ULA scans.
    macro COMPARE_TILE slow
        ld a,(de) : xor (hl)
        if slow
            jp z,1f
        else
            jr z,1f
        endif
        ld a,e : ld (bc),a : inc bc
        ld a,(hl) : ld (bc),a : inc bc
        jr 2f
1:
        if slow
            dup 7
                ld a,0
            edup
        else
            dup 11
                nop
            edup
        endif
2:      inc l : inc e
    endm
    ; Recompose the anchored rider directly from the terrain tile. Both paths
    ; write the two screens at the same time even in a mixed kerb cell.
    macro RIDER_PIXELS row,col,solid
        dup 8,line
            ld a,(hl) : inc hl : pop bc : and c : or b
            ld (#5000+row*32+col+BIKE_COL+64+line*256),a
            if solid
                ld a,b
            else
                nop
            endif
            ld (#d000+row*32+col+BIKE_COL+64+line*256),a
        edup
    endm
    org #6000
worldMap:   incbin "world.bin"
bandScale:  incbin "scale0.bin"
course:     include "course.inc"
    align 256
scroll:     incbin "scroll.bin"
    assert $ <= #7000
    savebin "working.bin",worldMap,$-worldMap
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
    ld a,(shownMap) : ld h,a : ld l,0 : ld (dirty),hl
    ld hl,dirty : ld de,dirty+2 : ld bc,2*EARLY_TILES-2 : ldir
    call updateHud
frameWait:
    ei
    halt
    di
    ld (restoreSP+1),sp
    ld sp,dirty
    ld hl,riderSource : ld (afterJobs+1),hl
    ld a,EARLY_TILES
tileLoop:
    ex af,af'
    pop bc                      ; C is the cell and B its atlas tile ID
drawHalf:
    ld h,high shownMap
    ld l,c : ld (hl),b
    ld l,b
drawAtlas:
    ld h,high atlasLo0
    ld a,(hl) : inc h : ld h,(hl) : ld l,a
    ld (nextJob+1),sp : ld sp,hl
    ld a,c : add a,RASTER_TOP*4 : ld l,a
attrHalf:
    ld a,#58
    adc a,0 : ld h,a
    ld e,l : rlca : rlca : rlca : and #18 : or #40 : ld d,a
    pop bc
    ld (hl),c : set 7,h : ld (hl),b
    ex de,hl : ld e,l : ld d,h : set 7,d
    dup 4
        pop bc
        ld a,c : ld (hl),a : ld (de),a : inc h : inc d
        ld a,b : ld (hl),a : ld (de),a : inc h : inc d
    edup
nextJob:
    ld sp,0
    ex af,af'
    dec a : jp nz,tileLoop
afterJobs:
    jp riderSource

riderSource:
    ld sp,riderArt+162
    dup 3, ry
        dup 3, rx
            ld a,(shownMap+(18+ry-RASTER_TOP/8)*32+BIKE_COL+rx)
            ld l,a : ld h,high atlasLo1
            ld a,(hl) : inc h : ld h,(hl) : ld l,a
            inc hl : pop bc : ld a,c : ld (#5800+(18+ry)*32+BIKE_COL+rx),a
            ld a,(hl) : inc hl : ld c,a : rrca : rrca : rrca : xor c : and 7
            jp nz,1f
            ld a,c : and #38 : or b
            ld (#d800+(18+ry)*32+BIKE_COL+rx),a
            RIDER_PIXELS ry,rx,1
            jp 2f
1:          ld a,c : ld b,0 : nop
            ld (#d800+(18+ry)*32+BIKE_COL+rx),a
            RIDER_PIXELS ry,rx,0
            jp 2f
2:
        edup
    edup
restoreSP:
    ld sp,0
blitDone:
calibrationJump:
    jp measurePrelude
calibrationReady:
    ; Calibrated from IM2 entry. No video RAM or I/O access in this delay.
scanSource:
    ld hl,targetMap
scanShown:
    ld de,shownMap
    ld bc,dirty
    exx
rasterDelay:
    ld bc,90
.align:
    dec bc : ld a,b : or c : jr nz,.align
    ld hl,activeDepth
    ld d,high portColours
    ld bc,#7ffd
    ld ixl,DASH-RASTER_TOP
scanline:
    ld a,(hl)
phaseAdd:
    add a,0
    ld e,a
    ld a,(de)
    inc hl
latch:
    out (c),a
    exx
    COMPARE_TILE 0
    COMPARE_TILE 1
    exx
    dec ixl
    jp nz,scanline              ; 228 T from OUT to OUT, including the final line
    ld a,#17
    out (c),a
rasterDone:
    exx : ld (dirtyEnd),bc : exx
    call finishList
    call controls
    call advance
    call applyHalf
    call viewport
    call extraTiles
    call updateHud
    jp frameWait

controls:
    ld hl,riderArt+162
    ld bc,#dffe                 ; P, O, I, U, Y
    in a,(c)
    cpl
    and 3
    ld d,a
    ld a,d : cp 1 : call z,steerRight
    ld a,d : cp 2 : call z,steerLeft
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
    ld a,(lane) : cp 10 : ret c
    sub 2 : ld (lane),a : ret
steerRight:
    ld a,(lane) : cp 247 : ret nc
    add a,2 : ld (lane),a : ret

finishList:
    ld a,(scanHalf) : add a,high shownMap : ld (drawHalf+1),a
    ld a,(scanHalf) : add a,#58 : ld (attrHalf+1),a
    ld a,(scanHalf) : add a,a : add a,high atlasLo0 : ld (drawAtlas+1),a
    xor a : ld (overflow),a
    ld hl,(dirtyEnd) : ld de,dirty : or a : sbc hl,de
    ld a,h : or a : jr nz,fullList
    ld a,l : cp EARLY_TILES*2 : jr nc,fullList
    or a : jr nz,.pad
    ld hl,(scanShown+1) : ld a,l : ld (dirty),a
    ld a,(hl) : ld (dirty+1),a
    ld a,2
.pad:
    ; Repeat the first valid job to keep the pre-raster blit cycle-exact.
    ; Each PUSH fills a complete record while the screens are idle.
    rrca : ld e,a : ld d,0 : ld hl,padJobs : add hl,de
    ld de,(dirty) : ld (padSP+1),sp : ld sp,dirty+EARLY_TILES*2
    jp (hl)
padJobs:
    dup EARLY_TILES
        push de
    edup
padSP:
    ld sp,0 : jr nextHalf
fullList:
    srl h : rr l : ld a,l : sub EARLY_TILES : ld (overflow),a
    ; Resume beyond the final published cell when this half returns.
    ld a,(scanHalf) : ld e,a : ld d,0 : ld hl,resumeCol : add hl,de
    ld a,(dirty+(EARLY_TILES-1)*2) : inc a : ld (hl),a
nextHalf:
    ld a,(scanHalf) : xor 1 : ld (scanHalf),a
    ld e,a : ld d,0 : ld hl,resumeCol : add hl,de : ld l,(hl)
    ld h,a : ld a,high shownMap : add a,h : ld (scanShown+2),a
    ld a,high targetMap : add a,h : ld (scanSource+2),a
    ld a,l : ld (scanShown+1),a : ld (scanSource+1),a
    ret

advance:
    ld a,(lane) : cp 18 : jr c,.grass : cp 239 : jr c,.travel
.grass:
    ld a,1 : ld (gear),a
.travel:
    ld a,(gear) : ld b,a
    ld a,(phase) : add a,b : and 31 : ld (phase),a : ld (phaseAdd+1),a
    ld a,(travel) : add a,b : cp SUBSTEP_TRAVEL
    jr nc,.next
    ld (travel),a : ret
.next:
    sub SUBSTEP_TRAVEL : ld (travel),a
    ld a,(pose) : inc a : ld (pose),a
.descriptor:
    ld l,a : ld h,0 : add hl,hl : add hl,hl
    ld de,course : add hl,de
    ld e,(hl) : inc hl : ld d,(hl) : inc hl
    ld a,(hl) : ld (bankValue+1),a : inc hl : ld bc,#7ffd : out (c),a
    ld a,(lane) : add a,(hl) : cp 8 : jr nc,.upper : ld a,8
.upper:
    cp 249 : jr c,.lane : ld a,248
.lane:
    ld (lane),a
    ex de,hl
    ld e,(hl) : inc hl : ld d,(hl) : inc hl
    ld (upperPatch+1),hl : add hl,de : ld (lowerPatch+1),hl
    ld a,3 : ld (pending),a
    ld bc,#7ffd : ld a,#17 : out (c),a
    ld a,(pose) : and 127 : cp 124 : ret nz
judgePass:
    ; The bike is anchored at X=124. Lane is the world-space camera offset.
    ld a,(pose) : and 128 : ld b,78 : jr z,.left
    ld b,186
.left:
    ld a,(lane) : sub b : add a,12 : cp 25 : jr nc,.clear
    ld a,1 : ld (gear),a : ld a,20 : ld (bump),a : ret
.clear:
    ld a,(passes) : add a,1 : daa : ld (passes),a : ret

applyHalf:
    ld a,EXTRA_TILES : ld (extraLimit),a
    ld a,(scanHalf) : or a : jr nz,applyLower
    ld a,(pending) : bit 0,a : ret z
    res 0,a : ld (pending),a
upperPatch:
    ld hl,0
    ld de,worldMap : ld ix,activeDepth : jr patchPage
applyLower:
    ld a,(pending) : bit 1,a : ret z
    res 1,a : ld (pending),a
lowerPatch:
    ld hl,0
    ld de,worldMap+8*MAP_WIDTH : ld ix,activeDepth+64
patchPage:
    ld bc,#7ffd
bankValue:
    ld a,0 : out (c),a
patchLoop:
    ld a,(hl) : inc hl : or a : jr z,patchDepth
    jp m,.literal
    add a,e : ld e,a : jr nc,patchLoop : inc d : jr patchLoop
.literal:
    and 127 : ld c,a : ld b,0 : ldir : jr patchLoop
patchDepth:
    push ix : pop de
    dup 64
        ldi
    edup
    ld de,bandScale : ld a,(scanHalf) : or a : jr z,.scale
    ld de,bandScale+8
.scale:
    dup 8
        ldi
    edup
    xor a : ld (extraLimit),a
    ld bc,#7ffd : ld a,#17 : out (c),a : ret

extraTiles:
    ld a,(overflow) : or a : ret z
    ld hl,extraLimit : cp (hl) : jr c,.count : ld a,(hl)
.count:
    or a : ret z
    ld (lateSP+1),sp : ld sp,dirty+2*EARLY_TILES
    ld hl,lateSP : ld (afterJobs+1),hl
    jp tileLoop
lateSP:
    ld sp,0 : ret

    macro VIEW_BAND row
        ld a,(bandScale+row)
        rrca : rrca : ld h,a : and #c0 : or c : ld l,a
        ld a,h : and 3 : add a,high scroll : ld h,a : ld a,(hl)
        ld hl,worldMap+row*MAP_WIDTH
        add a,l : ld l,a : jr nc,1f : inc h
1:      dup 32
            ldi
        edup
        ; LDI consumes BC, restore the lane index for the next strip.
        ld a,(lane) : rrca : rrca : and 63 : ld c,a
    endm
viewport:
    ld a,(lane) : rrca : rrca : and 63 : ld c,a
    ld a,(scanHalf) : or a : jp nz,.lower
    ld de,targetMap
    dup 8,y
        VIEW_BAND y
    edup
    ret
.lower:
    ld de,targetMap+256
    dup 8,y
        VIEW_BAND (y+8)
    edup
    ret

updateHud:
    ; The ULA reads the dashboard from bank 5 alone.
    ld a,(gear) : ld b,a
    ld a,(hudGear) : cp b : jr nz,.draw
    ld a,(passes) : ld hl,hudPass : cp (hl) : jr nz,.draw
    ld a,(bump) : or a : ret z
.draw:
    ld a,b : ld (hudGear),a
    ld a,(passes) : ld (hudPass),a
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
    dec a : ld (bump),a : ld a,255 : ld (hudGear),a : ld a,#42
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

    ; Measure the prelude against an entire ULA frame once. Both the probe
    ; and the border delay use 26-T loops in fixed RAM. This also accounts for
    ; the different visible-display contention on the +2A.
measurePrelude:
    ld hl,calibrationReady : ld (calibrationJump+1),hl
    ld hl,finishMeasure : ld (irq+1),hl
    ld hl,0 : ei
.count:
    inc hl : nop : nop : jr .count
finishMeasure:
    di : pop de
    ld de,1828 : or a : sbc hl,de : ld (rasterDelay+1),hl
    ld hl,irqReturn : ld (irq+1),hl
    jp frameWait
irqReturn:
    ei : ret

lane:       db 128
gear:       db 2
phase:      db 0
travel:     db 0
pose:       db 0
passes:     db 0
bump:       db 0
gearTimer:  db 0
scanHalf:   db 0
resumeCol:  dw 0
dirtyEnd:   dw dirty
hudGear:    db 255
hudPass:    db 0
pending:    db 0
overflow:   db 0
extraLimit: db 0
dirty:      ds 512

riderArt:   incbin "riders.bin"
digits:     incbin "digits.bin"
    align 256
activeDepth: incbin "depth0.bin"
    align 256
portColours:
    dup 64, stripe
        db #17 + ((stripe & 16) >> 1)
    edup
    ds 32,#17
    align 256
shownMap:   incbin "shown.bin"
targetMap:  incbin "shown.bin"

atlasLo0:
    dup 256,id
        db low (atlas0+id*10)
    edup
    dup 256,id
        db high (atlas0+id*10)
    edup
atlasLo1:
    dup 256,id
        db low (atlas1+id*10)
    edup
    dup 256,id
        db high (atlas1+id*10)
    edup
atlas0:     incbin "atlas0.bin"
atlas1:     incbin "atlas1.bin"
    assert $ < #bd00
    org #bfbf
irq:
    jp irqReturn
    savebin "core.bin",start,$-start
