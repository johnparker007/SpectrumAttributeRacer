; Both screen pages carry the same road bitmap. Publish a prepared camera view
; in the borders, finishing any lower-road blocks before the beam reaches them.
    device ZXSPECTRUM128
    include "layout.inc"
    include "shape-layout.inc"
TOP_BLOCKS equ 102
    org #8000
start:
    di : ld sp,#bdf0
    ld a,#17 : ld bc,#7ffd : out (c),a : xor a : out (#fe),a
    ld hl,#be00 : ld de,#be01 : ld bc,256 : ld (hl),#bf : ldir
    ld a,#be : ld i,a : im 2
    ld hl,occupied : ld de,occupied+1 : ld bc,255 : ld (hl),0 : ldir
    ld hl,padding : ld de,padding+2 : ld bc,2*(TOP_BLOCKS-1) : ldir
    call prepare
    ld hl,packets : ld de,(packetEnd) : call sendBlocks
    call publishAttrs : call showState : call updateHud
    ei
frameWait:
    halt
mainLoop:
    ld a,(ready) : or a : jr nz,frameWait
    ld a,(requested) : or a : jr z,frameWait
    xor a : ld (requested),a
    call prepare
    ld a,1 : ld (ready),a
    jr frameWait

; An IRQ can arrive during scene preparation, including while a course bank
; is selected. The caller's registers and paging latch are restored on exit.
irqEntry:
    ld (returnSP+1),sp : ld sp,irqStackEnd
    push af : push bc : push de : push hl : push ix : push iy
    exx : push bc : push de : push hl : exx
    ld a,#17 : ld bc,#7ffd : out (c),a
    ld hl,(topEntry) : ld de,(topEnd) : call sendBlocks
afterPad:
    xor a : ld (inFlight),a
syncJump:
    jp calibrate
calibrated:
    ld (rasterSP+1),sp : ld sp,(visibleWords)
    ld hl,(visibleDepth)
    ld a,(phase) : ld e,a : ld iy,portColours : ld bc,#7ffd
    ld a,64 : ex af,af'
rasterDelay:
    ld bc,145
.wait:
    dec bc : ld a,b : or c : jr nz,.wait
    ld bc,#7ffd : nop
    macro ROAD_LATCH
        ld a,(hl) : inc hl : add a,e : ld iyl,a : ld a,(iy) : out (c),a
    endm
    macro SCREEN_WORD
        ld (hl),e : inc l : ld (hl),d
        set 7,h : ld (hl),d : dec l : ld (hl),e
    endm
scanline:
    exx : pop hl : pop de : exx
    ROAD_LATCH
burstOut equ $-2
    exx : SCREEN_WORD : exx
    dup 14
        nop
    edup
    ret c
    ex af,af' : dec a : jr z,turnRaster : ex af,af' : jr scanline
turnRaster:
    ; Match the last iteration to the regular scanline, including its prefetch.
    ld a,LINES-64 : ex af,af'
    dup 7
        nop
    edup
scanTail:
    ROAD_LATCH
tailOut equ $-2
    dup 35
        nop
    edup
    ex af,af' : dec a : jp z,rasterEnd : ex af,af' : jp scanTail
rasterEnd:
    dup 24
        nop
    edup
    ex af,af'
    ld a,#17 : out (c),a
rasterSP:
    ld sp,0
rasterDone:
    call controls
    call tick
    ld a,(ready) : cp 1 : jr nz,.noFrame
    call publishAttrs
    ld hl,packets : ld de,(splitEntry) : call sendBlocks
    ld hl,(nextTop) : ld (topEntry),hl
    ld hl,(listEnd) : ld (topEnd),hl
    ld hl,(nextWords) : ld (visibleWords),hl
    call showState : ld a,1 : ld (inFlight),a : xor a : ld (ready),a : jr .finish
.noFrame:
    call applyMotion
    ld hl,dummyWords : ld (visibleWords),hl
    ld hl,padding : ld (topEntry),hl : ld hl,packets : ld (topEnd),hl
.finish:
    call updateHud
    ld a,(selectedBank) : ld bc,#7ffd : out (c),a
    exx : pop hl : pop de : pop bc : exx
    pop iy : pop ix : pop hl : pop de : pop bc : pop af
returnSP:
    ld sp,0 : ei : ret
sendBlocks:
    ; Each block writer returns through the next address in this list.
    ; Replace its sentinel temporarily so the same list can be split at any block.
    ld (packetSP+1),sp
    ex de,hl : ld c,(hl) : ld (hl),low packetReturn : inc hl
    ld b,(hl) : ld (hl),high packetReturn : ld (packetRestore+1),hl
    ex de,hl : ld sp,hl : ret
packetReturn:
packetRestore:
    ld hl,0 : ld (hl),b : dec hl : ld (hl),c
packetSP:
    ld sp,0 : ret


; Apply a prepared subframe while the ULA is below the road. Packets contain
; a screen address and an XOR mask. Bit 7 of the address selects centre paint,
; which is visible only in the bright bank. Kerbs use both screen pages.
applyMotion:
    ld a,(motionPending) : or a : ret z
    ld (motionStack+1),sp : ld sp,packets
    ld a,(motionCount) : dec a : ld c,a : srl a : srl a : inc a : ld b,a
    ld a,c : cpl : and 3 : add a,a : ld e,a : ld d,0
    ld hl,motionEntries : add hl,de : ld a,(hl) : inc hl : ld h,(hl) : ld l,a : jp (hl)
motionEntries:
    dw motionGroup,motionTwo,motionThree,motionFour
    macro MOTION_BYTE
        ; Pop a word and a byte. The following entry shares the spare byte.
        pop hl : pop de : dec sp
        ld a,h : xor #80 : ld c,a : res 7,h
        ld a,(hl) : xor e : ld (hl),a : ld h,c : ld (hl),a
    endm
motionGroup: MOTION_BYTE
motionTwo:   MOTION_BYTE
motionThree: MOTION_BYTE
motionFour:  MOTION_BYTE
    djnz motionGroup
motionStack:
    ld sp,0
    xor a : ld (motionPending),a : inc a : ld (midState),a : ret

; Fetch and consume the forced halves for a 16x8 pair. Their final image
; can equal the original even when the intervening XOR changed the screen.
motionHalfMask:
    sub 176 : jr nc,.foreground : xor a : ret
.foreground:
    add a,low motionForce : ld l,a : ld h,high motionForce
    ld a,(hl) : ld (hl),0 : or a : ret

calibrate:
    ld hl,calibrated : ld (syncJump+1),hl
    ld hl,endCalibration : ld (irq+1),hl
    ld hl,0 : ei
.count: inc hl : nop : nop : jr .count
endCalibration:
    di : pop de
    ; Hold each latch in horizontal blanking. The final latch remains active
    ; through the whole last paper scanline before returning to the HUD page.
    ld de,1762 : or a : sbc hl,de
    ; The +2A top-border writers can measure either 33 or 34 delay loops
    ; depending on the instruction that accepted the calibration interrupt.
    ; Use the earlier slot: one extra loop puts the first real burst store
    ; into ULA contention. The 128K and grey +2 measure a longer delay.
    ld a,l : cp 34 : jr nz,.storeDelay : dec hl
.storeDelay:
    ld (rasterDelay+1),hl
    ld hl,irqEntry : ld (irq+1),hl
    xor a : ld (ready),a
    exx : pop hl : pop de : pop bc : exx
    pop iy : pop ix : pop hl : pop de : pop bc : pop af
    ld sp,(returnSP+1) : ei : jp frameWait

showState:
    xor a : ld (midState),a
    ld hl,(drawingDepth) : ld de,(visibleDepth)
    ld (visibleDepth),hl : ld (drawingDepth),de
    ld a,(drawingPose) : ld (displayPose),a
    ld a,(drawingLane) : ld (displayLane),a
    ld a,(drawingLean) : ld (displayLean),a
    ret

tick:
    ld a,(gear) : ld b,a
    ld a,(phase) : add a,b : and 31 : ld (phase),a
    ld a,(travel) : add a,b : cp SUBSTEP_TRAVEL : jr c,.store
    sub SUBSTEP_TRAVEL : ld (travel),a : ld a,1 : ld (forward),a : jr .request
.store: ld (travel),a
    ld a,(lane) : ld hl,displayLane : cp (hl) : jr nz,.request
    ld a,(lean) : ld hl,displayLean : cp (hl) : ret z
.request:
    ld a,1 : ld (requested),a : ret

prepare:
    ld a,#11 : ld (selectedBank),a : ld bc,#7ffd : out (c),a
    ; Input is sampled once for the whole view, including the scenery.
    ld a,(forward) : or a : jr z,.station
    xor a : ld (forward),a
    ld a,(pose) : inc a : ld (pose),a
    ld a,(pose) : and 127 : cp 124 : call z,judgePass
.station:
    ld a,(pose) : ld (drawingPose),a
    ld l,a : ld h,0 : ld d,h : ld e,l : add hl,hl : add hl,de
    ld de,course : add hl,de : ld e,(hl) : inc hl : ld d,(hl)
    inc hl : ld a,(hl) : ld (selectedBank),a : ld bc,#7ffd : out (c),a
    ex de,hl : ld c,(hl) : inc hl : ld b,(hl) : inc hl : ld de,sceneData : ldir
    ld a,#16 : ld (selectedBank),a : ld bc,#7ffd : out (c),a
    ld a,(lean) : ld (drawingLean),a
    ld a,(lane) : ld (drawingLane),a
    ; Projection and scenery both use 128 + scale * steering. Keep all 113
    ; products in one little-endian table. The cell palette grid is applied
    ; only when the product is consumed.
.cachedLane:
    cp 0 : jp z,.depthSetup : ld (.cachedLane+1),a
    ld l,a : ld h,0 : add hl,hl : ld de,#fe00 : add hl,de
    ld e,(hl) : inc hl : ld d,(hl) : ld hl,128
    dup 113,scale
        ld (roadShift+scale*2),hl
        add hl,de
    edup
.depthSetup:
    ld hl,sceneData+3 : ld de,(drawingDepth) : ld a,(sceneData) : ld b,a : ld a,64
.sky: ld (de),a : inc de : djnz .sky
    ld hl,(drawingDepth) : ld de,LINES-1 : add hl,de : ex de,hl
    ld hl,sceneData+3
    ld a,(sceneData) : ld c,a : ld a,LINES : sub c : ld b,a : ld c,0
    ; Each nibble is either a delta or an escape followed by an absolute
    ; phase. An escape consumes three nibbles, so either case changes parity.
.high:
    ld a,(hl) : rrca : rrca : rrca : rrca : and 15 : cp 15 : jr z,.highEscape
    add a,c : and 31
.highWrite:
    ld c,a : ld (de),a : dec de : djnz .low : jr .depthDone
.highEscape:
    ld a,(hl) : and 1 : rrca : rrca : rrca : rrca : ld c,a : inc hl
    ld a,(hl) : rrca : rrca : rrca : rrca : and 15 : or c : jr .highWrite
.low:
    ld a,(hl) : inc hl : and 15 : cp 15 : jr z,.lowEscape
    add a,c : and 31
.lowWrite:
    ld c,a : ld (de),a : dec de : djnz .high : jr .depthDone
.lowEscape:
    ld a,(hl) : inc hl : and 31 : jr .lowWrite
.depthDone:
    ld a,(sceneData+2) : ld l,a : ld h,0 : ld de,sceneData+3 : add hl,de
    push hl : ld a,(sceneData) : and #f8 : rrca : rrca : ld l,a : ld h,0
    ld de,bandMeta : add hl,de : push hl : pop iy : pop hl
    ld a,(sceneData+1) : inc a : ld b,a : ld ix,projected
.project:
    ld a,(iy) : ld (ix),a : add a,a : ld e,a : ld d,high roadShift
    ld a,(de) : ld c,a : inc e : ld a,(de) : ld e,a
    ld d,(hl) : inc hl
    ld a,d : and 1 : rrca : sub c : ld c,a
    ld a,1 : sbc a,e : ld e,c : ld c,a
    dup 3,i
        ld a,d : and #c0 : add a,e : ld a,(hl) : adc a,c : ld (ix+i+1),a
        inc hl : rlc d : rlc d
    edup
    ; Six rotations leave the saved coarse-grid flag in bit 6.
    bit 6,d : jr z,.fine
    res 0,(ix+1) : res 0,(ix+2) : res 0,(ix+3)
.fine:
    ld a,(iy+1) : ld (ix+4),a : inc iy : inc iy : ld de,5 : add ix,de
    djnz .project
    ld (objectsPtr+2),hl
    call #fa00
    ld hl,(poolBase) : ld de,(poolSpare) : ld (poolSpare),hl : ld (poolBase),de : ld (poolNext),de
    ld hl,overlays : ld (overlayEnd),hl
    ld a,#16 : ld (selectedBank),a : ld bc,#7ffd : out (c),a
    ld a,(sceneData) : and #f8 : ld (renderY),a
    ld ix,projected
.band:
    ld a,(renderY) : call mapRow
    ld l,(ix+4) : ld h,high SHAPE_BASE : ld c,(hl) : inc l : ld b,(hl) : ld (lookupBase+1),bc
    ld l,(ix+1) : ld h,(ix+6) : call drawStrip
    ld l,(ix+2) : ld h,(ix+7) : call drawStrip
    bit 7,(ix) : jr z,.next
    bit 7,(ix+5) : jr z,.next
    ld bc,CENTRE_BASE : ld (lookupBase+1),bc
    ld l,(ix+3) : ld h,(ix+8) : call drawStrip
.next: ld de,5 : add ix,de : ld a,(renderY) : add a,8 : ld (renderY),a : cp LINES : jr nz,.band
    ld a,#10 : ld (selectedBank),a : ld bc,#7ffd : out (c),a
    call mergeAll : call trimCrest
objectsPtr:
    ld ix,0 : call drawProps : call mergeAll : call drawRider
    call changes
    ld a,#17 : ld (selectedBank),a : ld bc,#7ffd : out (c),a : ret

mapRow:
    ld l,a : add a,a : ld (bandPairs+1),a : ld h,0 : add hl,hl : add hl,hl : add hl,hl
    ld de,targetMap : add hl,de : ld (stripRow+1),hl : ret

drawStrip:
    ; Coordinates are biased two-pixel units. The slope and four horizontal
    ; phases address a tightly packed table for this pair of kerb widths.
    ld a,h : sub l : add a,32 : ld e,l : ld l,a : ld h,0
    add hl,hl : add hl,hl : add hl,hl : ld a,e : and 3 : add a,a : or l : ld l,a
lookupBase:
    ld bc,0 : add hl,bc : ld a,(hl) : inc hl : ld h,(hl) : ld l,a
    ld a,e : srl a : srl a : sub 16 : ld c,a
    ld a,(hl) : inc hl : ld b,a : and #f0 : rrca : rrca : rrca : rrca : ld e,a
    ld a,c : sub e : ld c,a : ld a,b : and 15 : ld b,a
    inc b : dec b : ret z : ld a,c : cp 32 : jr nc,lookupBase.clip
    add a,b : cp 33 : jr nc,lookupBase.clip
    ; Mark the full interval once. In a shallow bend most ribbons fit in
    ; one or two cells and can stream directly from the course bank.
    push hl : ld a,c : srl a : ld e,a : ld a,c : add a,b : dec a : srl a : sub e : inc a : ld d,a
bandPairs:
    ld a,0 : or e : ld l,a : ld h,high occupied
    ; New occupancy is bit 1. If none of these pairs has been touched by
    ; an earlier ribbon, even the transparent tile slots can be streamed.
    xor a
.mark: or (hl) : set 1,(hl) : inc l : dec d : jr nz,.mark
    bit 1,a : jr nz,.mixed
    pop hl : ld de,(stripRow+1) : ld a,c : add a,a : add a,e : ld e,a
    ld a,b : add a,a : ld c,a : ld b,0 : ldir : ret
.mixed:
    pop hl : ld de,(stripRow+1) : ld a,c : add a,a : add a,e : ld e,a
    ld a,b : add a,a : ld c,a : ld b,0
.tile:
    inc e : ld a,(de) : dec e : or a : jr nz,.occupied
    ldi : ldi : jp pe,.tile : ret
.occupied:
    inc hl : ld a,(hl) : dec hl : or a : jr z,.skip
    push bc : push hl : push de
    ld c,(hl) : inc hl : ld b,(hl) : ex de,hl : ld e,c : ld d,b
    call appendOverlay
    pop de : pop hl : pop bc
.skip:
    inc e : inc e : inc hl : inc hl : dec c : dec c : jr nz,.tile : ret
lookupBase.clip:
    ld e,(hl) : inc hl : ld d,(hl) : inc hl
    ld a,c : cp 32 : jr nc,stripRow.skip : ld a,d : or a : jr z,stripRow.skip
    push hl : ld a,c : add a,a
stripRow:
    ld hl,0 : add a,l : ld l,a : call putGlyph : pop hl
.skip: inc c : djnz lookupBase.clip : ret

putGlyph:
    inc hl : ld a,(hl) : or a : jr nz,.overlap
    ld (hl),d : dec hl : ld (hl),e : jp touch
.overlap: dec hl
appendOverlay:
    push hl : ld hl,(overlayEnd) : ld (hl),e : inc hl : ld (hl),d : inc hl
    pop de : ld (hl),e : inc hl : ld (hl),d : inc hl : ld (overlayEnd),hl : ret

touch:
    ld a,l : rrca : rrca : and 63 : ld e,a
    ld a,h : sub high targetMap : rrca : rrca : or e : ld l,a : ld h,high occupied : set 1,(hl) : ret

mergeAll:
    ld ix,overlays
.loop:
    ld hl,(overlayEnd) : push ix : pop de : or a : sbc hl,de : jr z,.done
    ld l,(ix+2) : ld h,(ix+3) : ld a,(ix) : and 7 : call writable
    ; HL is the eight-byte destination and DE the incoming transparent mask.
    ld e,(ix) : ld d,(ix+1) : ld a,e : and #f8 : ld e,a
    dup 8
        ld a,(de) : or (hl) : ld (hl),a : inc e : inc l
    edup
    ld de,4 : add ix,de : jr .loop
.done: ld hl,overlays : ld (overlayEnd),hl : ret

writable:
    ld c,a : ld e,(hl) : inc hl : ld d,(hl) : dec hl
    ld a,e : and 7 : or a : jr z,.style : cp 3 : jr nc,.style : ld c,a
.style: ld a,e : and #f8 : ld e,a : ld a,d : or a : jr z,.empty
    cp #c0 : jr nc,.copy
    ld a,e : or c : ld (hl),a : ex de,hl : ret
.empty: ld de,blank
.copy: push de : ld de,(poolNext)
    ld a,e : or c : ld (hl),a : inc hl : ld (hl),d
    ld hl,8 : add hl,de : ld (poolNext),hl
    pop hl : push de
    dup 8
        ldi
    edup
    pop hl : ret

trimCrest:
    ld a,(sceneData) : and 7 : ret z : ld (trimCount+1),a
    ld a,(sceneData) : and #f8 : call mapRow : ld b,32
.tile: inc hl : ld a,(hl) : dec hl : or a : jr z,trimCount.next
    push bc : push hl : ld a,(hl) : and 7 : call writable
trimCount:
    ld b,0 : xor a
.clear: ld (hl),a : inc l : djnz .clear : pop hl : pop bc
.next: inc hl : inc hl : djnz trimCrest.tile : ret

drawProps:
    ld a,(ix) : inc ix : or a : ret z : ld (objectCount),a
.object:
    ld a,(ix) : add a,a : inc a : ld e,a : ld d,high roadShift : ld a,(de)
    ld c,a : ld a,(ix) : cp 34 : ld a,c : jr nc,.rounded : inc a : and #fe
.rounded:
    add a,2 : sra a : sra a : ld (objectShift+1),a
    ld b,(ix+1) : inc ix : inc ix : inc b : dec b : jr z,objectShift.end
.tile: ld a,(ix+1)
objectShift: sub 0 : cp 32 : jr nc,.skip
    ld c,a : ld a,(ix) : ld l,a : ld h,0
    add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ld e,c : ld d,0 : add hl,de : add hl,hl : ld de,targetMap : add hl,de
    ld a,(hl) : and 7 : jr z,.place : cp 3 : jr c,.skip
.place: ld e,(ix+2) : ld d,(ix+3) : call putGlyph
.skip: ld de,4 : add ix,de : djnz drawProps.tile
.end: ld hl,objectCount : dec (hl) : jr nz,drawProps.object : ret

drawRider:
    ld a,(drawingLean) : ld iy,riderArt : or a : jr z,.source
    ld de,162 : add iy,de : dec a : jr z,.source : add iy,de
.source:
    dup 3,ry
        ld hl,occupied+16*((144-FIRST)/8+ry)+7 : set 1,(hl) : inc l : set 1,(hl)
    edup
    dup 3,ry
        dup 3,rx
            ; An empty cell has a precomposited rider glyph in this lean.
            ld hl,(targetMap+2*(((144-FIRST)/8+ry)*32+14+rx))
            ld a,h : or a : jr nz,1f
            ld l,(iy) : ld h,(iy+1)
            ld (targetMap+2*(((144-FIRST)/8+ry)*32+14+rx)),hl : jr 2f
1:          ld hl,targetMap+2*(((144-FIRST)/8+ry)*32+14+rx)
            if ry==0 && rx==1
                ld a,3
            else
                if ry==1
                    ld a,6
                else
                    ld a,5
                endif
            endif
            call writable
            dup 8,dy
                ld a,(hl) : and (iy+2+dy*2) : or (iy+3+dy*2) : ld (hl),a : inc l
            edup
2:          ld de,18 : add iy,de
        edup
    edup
    ret

changes:
    ld a,(motionPending) : or a : jr nz,changes
    ld a,(inFlight) : or a : jr nz,changes
    ld hl,packets : ld (packetEnd),hl : ld hl,attrJobs : ld (attrEnd),hl
    ld hl,occupied : ld de,activeList : ld b,15
.scan:
    dup 16
        ld a,(hl) : or a : jr z,1f
        ld a,l : ld (de),a : inc e : srl (hl)
1:      inc l
    edup
    dec b : jp nz,.scan
    ld a,e : ld (activeLimit+1),a
    ld hl,activeList
nextPair:
    ld a,l
activeLimit:
    cp 0 : jp z,activeDone
    ld a,(hl) : inc l : push hl
    ld (blockNumber),a : ld c,a : call motionHalfMask : ld (dirtyHalves),a
    ld a,c : ld l,a : ld h,0 : add hl,hl : add hl,hl
    ld de,targetMap : add hl,de : ld d,h : ld e,l
    ld bc,previousMap-targetMap : add hl,bc
    ; Most stable foreground pairs have identical glyph references on the
    ; two maps. Writable glyphs alternate pools on every prepared scene.
    jr nz,.change
    ld a,(de) : cp (hl) : jr nz,.change
    inc e : inc l : ld a,(de) : cp (hl) : jr nz,.back1
    inc e : inc l : ld a,(de) : cp (hl) : jr nz,.back2
    inc e : inc l : ld a,(de) : cp (hl) : jr nz,.back3
    xor a : ld (de),a : dec e : ld (de),a : dec e : ld (de),a : dec e : ld (de),a
    pop hl : jp nextPair
.back3: dec e : dec l
.back2: dec e : dec l
.back1: dec e : dec l
.change: ld a,(blockNumber)
    ; DE and HL walk the two adjacent cells together. The secondary set
    ; carries the row of prepared pixel bytes and its attribute address.
    exx
    ld l,a : ld h,0 : add hl,hl
    ld de,#5800+FIRST*4 : add hl,de : ld b,h : ld c,l
    ld l,a : ld h,0 : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ld de,stageBits : add hl,de : ld d,h : ld e,l
    exx
    call stageCell
    exx : inc e : inc c : exx
    call stageCell
    ld a,(dirtyHalves) : or a : jr z,.next : ld b,a
    ld a,(blockNumber) : ld l,a : ld h,0 : add hl,hl
    ld de,writerIndex : add hl,de : ld e,(hl) : inc hl : ld d,(hl)
    ld hl,(packetEnd) : bit 0,b : jr z,.lower
    ld (hl),e : inc hl : ld (hl),d : inc hl
.lower: bit 1,b : jr z,.end : ld a,e : add a,37 : ld e,a : jr nc,.addr : inc d
.addr: ld (hl),e : inc hl : ld (hl),d : inc hl
.end: ld (packetEnd),hl
.next:
    pop hl : jp nextPair
activeDone:
    ; Stage the overflow in scanline order. The first 64 road scanlines
    ; can copy four-line blocks farther down the screen before the ULA
    ; reaches them. Both screens already hold the rest of the new pose.
    ld hl,(packetEnd) : ld de,packets+2*154 : or a : sbc hl,de
    jr nc,.overflow : ld hl,0
.overflow:
    ld a,l : rrca : and 127 : cp 17 : jr c,.count : ld a,16
.count:
    ld (burstCount),a : add a,a : ld e,a : ld d,0
    ld hl,(packetEnd) : or a : sbc hl,de : ld (listEnd),hl
    ld de,-2*TOP_BLOCKS : add hl,de : ld (nextTop),hl
    ld de,packets : or a : sbc hl,de : jr c,.short : add hl,de : ex de,hl
.short:
    ld (splitEntry),de
    ld a,(burstCount) : ld l,a : ld h,0 : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ex de,hl : ld hl,dummyWords : or a : sbc hl,de : ld (nextWords),hl : ex de,hl
    ld a,(burstCount) : or a : ret z
    ld a,#17 : ld (selectedBank),a : ld bc,#7ffd : out (c),a
    ld hl,(listEnd)
.build:
    ld c,(hl) : inc hl : ld b,(hl) : inc hl : push hl : push bc : pop ix
    dup 4,i
        ld a,(ix+4+9*i) : ld (de),a : inc de : ld a,(ix+5+9*i) : ld (de),a : inc de
        ld l,(ix+1+9*i) : ld h,(ix+2+9*i) : ld a,(hl) : ld (de),a : inc de
        inc l : ld a,(hl) : ld (de),a : inc de
    edup
    pop hl : ld a,(burstCount) : dec a : ld (burstCount),a : jp nz,.build : ret

stageCell:
    ld a,(de) : ld c,a : xor (hl) : ld b,a : ld (hl),c : xor a : ld (de),a
    inc l : inc e
    ld a,(de) : cp (hl) : ld (hl),a : jr nz,.changed
    ld a,b : or a : jr nz,.changed
    ld (de),a : inc l : inc e : ret
.changed:
    ld a,b : and 7 : jr z,.pixels
    xor c : or c : and 6 : jr z,.pixels
    push hl : ld a,c : and 7 : ld l,a : ld h,high attr0
    ld a,(hl) : inc h : ld h,(hl) : ld l,a : push hl
    exx
    pop hl : push de : ld de,(attrEnd) : ex de,hl
    ld (hl),c : inc hl : ld (hl),b : inc hl : ld (hl),e : inc hl : ld (hl),d : inc hl
    ld (attrEnd),hl : pop de
    exx : pop hl
.pixels:
    ld a,(de) : push hl : ld h,a : ld a,c : and #f8 : ld l,a
    ld a,h : or a : jr nz,.source : ld hl,blank
.source:
    push hl : exx : pop hl : push de : push bc
    ld c,0
    ld a,(de) : cp (hl) : jr nz,.copy00
    inc l : inc e : inc e
    ld a,(de) : cp (hl) : jr nz,.copy01
    inc l : inc e : inc e
    ld a,(de) : cp (hl) : jr nz,.copy02
    inc l : inc e : inc e
    ld a,(de) : cp (hl) : jr nz,.copy03
    inc l : inc e : inc e
    jr .done0
.copy00: ld a,(hl) : ld (de),a : inc l : inc e : inc e
.copy01: ld a,(hl) : ld (de),a : inc l : inc e : inc e
.copy02: ld a,(hl) : ld (de),a : inc l : inc e : inc e
.copy03: ld a,(hl) : ld (de),a : inc l : inc e : inc e
    set 0,c
.done0:
    ld a,(de) : cp (hl) : jr nz,.copy10
    inc l : inc e : inc e
    ld a,(de) : cp (hl) : jr nz,.copy11
    inc l : inc e : inc e
    ld a,(de) : cp (hl) : jr nz,.copy12
    inc l : inc e : inc e
    ld a,(de) : cp (hl) : jr nz,.copy13
    inc l : inc e : inc e
    jr .done1
.copy10: ld a,(hl) : ld (de),a : inc l : inc e : inc e
.copy11: ld a,(hl) : ld (de),a : inc l : inc e : inc e
.copy12: ld a,(hl) : ld (de),a : inc l : inc e : inc e
.copy13: ld a,(hl) : ld (de),a : inc l : inc e : inc e
    set 1,c
.done1:
    ld a,(dirtyHalves) : or c : ld (dirtyHalves),a
    pop bc : pop de : exx : pop hl
.next:
    xor a : ld (de),a : inc l : inc e : ret

publishAttrs:
    ld hl,(attrEnd) : ld de,attrJobs : or a : sbc hl,de : ret z
    srl h : rr l : srl h : rr l : ld b,l
    ld (attrSP+1),sp : ld sp,attrJobs
.loop: pop hl : pop de : ld (hl),e : set 7,h : ld (hl),d : djnz .loop
attrSP: ld sp,0 : ret

controls:
    ld l,1
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
    ld l,2
.notRight:
    cp 2
    jr nz,.leanDone
    ld l,0
.leanDone:
    ld a,l : ld (lean),a
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
    ld a,(lane) : cp 8 : ret z
    dec a : ld (lane),a : ret
steerRight:
    ld a,(lane) : cp 248 : ret z
    inc a : ld (lane),a : ret

judgePass:
    ; The bike is anchored at X=124. Lane is the world-space camera offset.
    ld a,(pose) : and 128 : ld b,78 : jr z,.left
    ld b,186
.left:
    ld a,(lane) : sub b : add a,12 : cp 25 : jr nc,.clear
    ld a,20 : ld (bump),a : ret
.clear:
    ld a,(passes) : add a,1 : daa : ld (passes),a : ret

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

selectedBank: db #17
topEntry: dw padding
topEnd: dw packets
nextTop: dw padding
splitEntry: dw packets
packetEnd: dw packets
attrEnd: dw attrJobs
blockNumber: db 0
stagePointer: dw 0
dirtyHalves: db 0
attrAddress: dw 0
activeEnd: dw activeList
cellPointers: ds 8
halfOffset: db 0
poolBase: dw poolA
poolSpare: dw poolB
poolNext: dw 0
overlayEnd: dw overlays
drawingDepth: dw depthA
visibleDepth: dw depthB
nextWords: dw dummyWords
visibleWords: dw dummyWords
listEnd: dw packets
burstCount: db 0
ready: db 0
inFlight: db 0
requested: db 0
forward: db 0
lane: db 128
gear: db 2
phase: db 0
travel: db 0
pose: db 0
displayPose: db 0
drawingPose: db 0
displayLane: db 128
drawingLane: db 128
lean: db 1
displayLean: db 1
drawingLean: db 1
gearTimer: db 0
passes: db 0
bump: db 0
hudGear: db 255
hudPass: db 255
objectCount: db 0
nybbleFlag: db 0
renderY: db 0
depthA: ds LINES,64
depthB: ds LINES,64

riderArt:
    dup 27,tile
        if tile%9==1
            dw (riderGlyphs+tile*8)|3
        else
            if tile%9>=3 && tile%9<6
                dw (riderGlyphs+tile*8)|6
            else
                dw (riderGlyphs+tile*8)|5
            endif
        endif
        incbin "riders.bin",tile*18+2,16
    edup
bandMeta: incbin "band-meta.bin"
digits: incbin "digits.bin"



    align 256
roadShift: ds 256
attr0: incbin "attr0.bin"
    align 8
riderGlyphs:
    dup 27,tile
        dup 8,y
            db {b riderArt+tile*18+3+2*y}
        edup
    edup
    assert $ <= attr0+256
    align 256
attr1: incbin "attr1.bin"
motionOld: ds 30
motionNext: ds 30
motionHaveOld: db 0
motionPending: db 0
motionCount: db 0
midState: db 0
motionForce: ds 64
    assert (low motionForce)+64 <= 256

    align 256
portColours:
    dup 64,i
        db #17+((i&16)>>1)
    edup
    ds 32,#1f
    align 8
blank: ds 8
sceneData: ds 384
projected: ds 80
    align 256
targetMap: ds LINES*8
previousMap: ds LINES*8
writerIndex:
    dup LINES/8*16,num
        if 2*num<252
            dw #db00+37*(2*num)
        else
            if 2*num<396
                dw #5b00+37*(2*num-252)
            else
                dw #7100+37*(2*num-396)
            endif
        endif
    edup
padding:
    dw paddingWriter : ds (TOP_BLOCKS-1)*2
packets: ds 2*256+2
    align 256
stageBits: ds LINES*32
attrJobs equ #6fd0
rasterWords: ds 16*16
dummyWords:
    ; Idle slots use a scratch word in uncontended bank 2. Setting bit 7 of H
    ; in SCREEN_WORD leaves this address unchanged for the second write.
    dup 64
        dw #bff8,0
    edup
irqStack: ds 96
irqStackEnd:
    assert $ <= poolA
    org #bfbf
irq: jp irqEntry
    savebin "core.bin",start,$-start

    ; Each queued writer copies four two-byte words from the prepared image.
    macro COPY_BLOCK groupIndex
        dup 4,dy
            ld hl,(stageBits+((groupIndex)/2)*16+((groupIndex)&1)*8+2*dy)
            ld (#4000+(((FIRST/8+((groupIndex)/32))&24)*256)+(((FIRST/8+((groupIndex)/32))&7)*32)+(((groupIndex)&1)*4+dy)*256+(((groupIndex)/2)&15)*2),hl
            ld (#c000+(((FIRST/8+((groupIndex)/32))&24)*256)+(((FIRST/8+((groupIndex)/32))&7)*32)+(((groupIndex)&1)*4+dy)*256+(((groupIndex)/2)&15)*2),hl
        edup
        ret
    endm
    page 7
    org #db00
copy7:
    dup 252,n
        COPY_BLOCK n
    edup
paddingWriter:
    dup 4
        ld hl,(stageBits) : ld (#7dfc),hl : ld (#fffa),hl
    edup
    ret
    assert $<=#10000
    savebin "copy7.bin",copy7,$-copy7
    org #5b00
copy5:
    dup 144,n
        COPY_BLOCK n+252
    edup
    savebin "copy5.bin",copy5,$-copy5
    org #7100
copy5High:
    dup 84,n
        COPY_BLOCK n+396
    edup
    savebin "copy5high.bin",copy5High,$-copy5High

occupied equ #7e00
activeList equ #7f00
overlays equ #bd00
poolA equ #ba60
poolB equ #bbc0



    page 1
    org #fc00
course: include "course.inc"
    savebin "descriptors.bin",course,$-course
