; Native flat circuit. Sample input at 50 Hz, compose into the hidden 128K
; display file, then flip the complete bitmap and attributes at vertical blank.
    device ZXSPECTRUM128
    include "solid.inc"
    include "config.inc"
    org #8000
start:
    di : ld sp,#bdf0 : xor a : out (#fe),a
    call clearMaterial
    ld a,7 : call page
    ld hl,#dc00 : ld de,poseIndex : ld bc,3072 : ldir
    ld de,indices : ld bc,2283 : ldir
    ld hl,#4000 : ld de,#4001 : ld bc,6911 : ld (hl),0 : ldir
    ld hl,#be00 : ld de,#be01 : ld bc,256 : ld (hl),#bf : ldir
    ld a,#be : ld i,a : im 2
    ld hl,shots : call selectShot : ld a,1 : ld (running),a
    ei
frame:
    di
    ld hl,(position) : ld (viewPos),hl
    ld a,(lane) : ld (viewLane),a
    ld a,(theme) : ld (viewTheme),a
    ei
    call setup
    call materialRows
    ld a,7 : call page
    ld a,(displayBit) : xor 8 : rrca : rrca : rrca : ld e,a : ld d,0
    ld hl,skyTheme : add hl,de : ld a,(viewTheme) : cp (hl) : jr z,.skyReady
    ld (hl),a : call drawSky
.skyReady:
    call horizon
    call drawRoad
    call trees
    call drawBike
    halt
publish:
    ld a,(displayBit) : xor 8 : ld (displayBit),a : ld (page.mask+1),a
    ld a,7 : call page
presented:
    jp frame

page:
.mask: or 0
    or #10 : ld bc,#7ffd : out (c),a : ret

; A three-byte bank/address pointer. Return HL pointing into the selected bank.
fetch:
    ld a,(hl) : inc hl : ld e,(hl) : inc hl : ld d,(hl) : ex de,hl : jp page

selectShot:
    ld e,(hl) : inc hl : ld d,(hl) : inc hl : ld (position),de
    ld a,(hl) : inc hl : ld (lane),a : ld a,(hl) : ld (theme),a
    xor a : ld (running),a : ret

irq:
    push af : push bc : push de : push hl
    ld bc,#f7fe : in a,(c) : cpl : and 15 : ld d,a
    ld a,(shotKeys) : cpl : and d : ld e,a : ld a,d : ld (shotKeys),a
    ld a,e : or a : jr z,.space
    ld hl,shots : ld bc,4
.pick: rrca : jr c,.picked : add hl,bc : jr .pick
.picked: call selectShot
.space:
    ld bc,#7ffe : in a,(c) : cpl : and 1 : ld d,a
    ld a,(spaceKey) : xor d : and d : jr z,.store
    ld a,(running) : xor 1 : ld (running),a
.store: ld a,d : ld (spaceKey),a
    ld bc,#dffe : in a,(c) : cpl : and 3 : ld e,a
    ld a,(lane) : ld d,a : ld a,e : cp 1 : jr nz,.left
    ld a,d : cp 248 : jr nc,.speed : inc a : jr .lane
.left: cp 2 : jr nz,.speed : ld a,d : cp 8 : jr z,.speed : dec a
.lane: ld (lane),a
.speed:
    ld a,(gearWait) : or a : jr z,.poll : dec a : ld (gearWait),a : jr .travel
.poll: ld bc,#fbfe : in a,(c) : cpl : and 1 : ld e,a
    ld b,#fd : in a,(c) : cpl : and 1 : add a,a : or e
    cp 1 : jr nz,.down : ld a,(gear) : cp 4 : jr z,.travel : inc a : jr .gear
.down: cp 2 : jr nz,.travel : ld a,(gear) : cp 1 : jr z,.travel : dec a
.gear: ld (gear),a : ld a,7 : ld (gearWait),a
.travel:
    ld a,(running) : or a : jr z,.end
    ld a,(gear) : add a,a : add a,a : add a,a : ld e,a : ld d,0
    ld hl,(position) : add hl,de : ld (position),hl
.end: pop hl : pop de : pop bc : pop af : ei : reti

setup:
    ; Position is one unsigned turn; bits 15..6 select a geometry sample.
    ld hl,(viewPos) : ld a,l : and #c0 : rlca : rlca : ld e,a
    ld a,h : ld d,0 : ld l,a : ld h,d : add hl,hl : add hl,hl : add hl,de
    ld a,7 : call page
    push hl : ld de,#f100 : add hl,de : ld a,(hl) : ld (viewLean),a
    ld de,1024 : add hl,de : ld a,(viewTheme) : or a : jr z,.pan : add hl,de
.pan: ld a,(hl) : ld (viewPan),a
    pop hl : ld d,h : ld e,l : add hl,hl : add hl,de : ld de,poseIndex : add hl,de
    call fetch
    and 7
    ; The banked pointer is the shape identity (identical profiles are shared).
    ; The pointer and bank together identify a complete scanline profile.
    ld de,(lastGeometry) : or a : sbc hl,de : add hl,de : jr nz,.geometry
    ld hl,lastBank : cp (hl) : jr nz,.reload
    ld a,(viewLane) : ld hl,lastLane : cp (hl) : jr z,.unchanged
    jr .steer
.reload: ld hl,(lastGeometry)
.geometry:
    ld (lastGeometry),hl : ld (lastBank),a
    ld de,centres : ld c,(hl) : inc hl : ld a,c : ld (de),a : inc e
.run: ld a,(hl) : inc hl : ld b,a : and 15 : cp 15 : jr z,.escape : sub 7 : jr .step
.escape: ld a,(hl) : inc hl
.step: ld (.delta+1),a : ld a,b : rrca : rrca : rrca : rrca : and 15 : inc a : ld b,a
    ld a,c
.delta: add a,0 : ld (de),a : inc e : djnz .delta
    ld c,a : ld a,e : cp 80 : jr nz,.run
.steer:
    ld a,1 : ld (changed),a : ld a,(viewLane) : ld (lastLane),a
    sub 128 : jp p,.positive : neg : ld (laneIndex),a
    xor a : jr .sign
.positive: ld (laneIndex),a : ld a,1
.sign: ld (subtractLane),a
    ld a,(laneIndex) : ld l,a : ld h,0 : ld e,a : ld d,h : add hl,hl : add hl,de
    ld de,indices+1920 : add hl,de : call fetch : ld de,shifts : ld bc,80 : ldir
.unchanged:
    ld hl,(viewPos)
    include "paint-phase.inc"
    ld a,h : ld (phase),a
    ld a,(displayBit) : or a : ld a,#c0 : jr z,.base : ld a,#40
.base: ld (screenHigh),a
    ld a,(viewTheme) : ld hl,paletteTheme : cp (hl) : ret z : ld (hl),a
    ld hl,dirty : ld de,dirty+1 : ld bc,9 : ld (hl),1 : ldir
    ld hl,palettes : or a : jr z,.palette : ld de,32 : add hl,de
.palette: ld de,groupMap : ld bc,32 : ldir
    ret

; The blitter reads just the visible bytes of each pre-shifted material row.
clearMaterial:
    ld hl,materials : ld de,materials+1 : ld bc,4095 : ld (hl),0 : ldir : ret

materialRows:
    ld a,(changed) : or a : ret z : xor a : ld (changed),a
    ld hl,indices : ld (template+1),hl : xor a : ld (row),a
materialLoop:
    ld a,(row) : ld l,a : ld h,high centres : ld e,(hl)
    inc h : ld c,(hl) : ld d,0 : ld b,d : ex de,hl
    ld a,(subtractLane) : or a : jr z,.add : sbc hl,bc : jr .pos
.add: add hl,bc
.pos:
    ; Cache the exact signed pixel centre. A distant curve often changes
    ; just a handful of scanlines between neighbouring course positions.
    ld a,(row) : add a,a : ld e,a : ld d,0 : push hl
    ld hl,oldCentres : add hl,de : pop de : ld a,(hl) : cp e : jr nz,.change
    inc hl : ld a,(hl) : cp d : jr nz,.changeHigh
    ld hl,(template+1) : ld de,24 : add hl,de : ld (template+1),hl : jp materialNext
.change: ld (hl),e : inc hl
.changeHigh: ld (hl),d : ex de,hl : push hl
    ld a,(row) : rrca : rrca : rrca : and 15 : ld l,a : ld h,high dirty : ld (hl),1
    ld hl,stageAddresses : ld a,(row) : add a,a : ld e,a : ld d,0 : add hl,de
    ld e,(hl) : inc hl : ld d,(hl) : ex de,hl
    ; Clear the previous silhouette even when it crossed a screen edge.
    dup 32
      ld (hl),0 : inc l
    edup
    pop hl
    ld a,l : and 7 : ld e,a : add a,a : add a,e : ld e,a : ld d,0
    sra h : rr l : sra h : rr l : sra h : rr l : ld a,l : ld (column+1),a
template: ld hl,0 : push hl : add hl,de : call fetch : pop de : ex de,hl
    ld bc,24 : add hl,bc : ld (template+1),hl : ex de,hl
column: ld a,0 : add a,(hl) : inc hl : ld c,(hl) : inc hl
    bit 7,a : jr z,.right
    neg : cp c : jr nc,materialNext : ld e,a : ld d,0 : add hl,de : ld a,c : sub e : ld c,a : xor a
.right: cp 32 : jr nc,materialNext : ld (startCol),a : ld e,a : add a,c : cp 33 : jr c,materialLength
    ld a,32 : sub e : ld c,a
materialLength: ld b,0
    push hl : ld hl,stageAddresses : ld a,(row) : add a,a : ld e,a : ld d,0
    add hl,de : ld e,(hl) : inc hl : ld d,(hl) : pop hl
    ld a,(startCol) : add a,e : ld e,a : ldir
materialNext:
    ld hl,row : inc (hl) : ld a,(hl) : cp 80 : jp nz,materialLoop : ret

drawRoad:
    xor a : ld (band),a
roadBand:
    ld a,(band) : add a,a : add a,a : add a,a : ld (row),a
    ; Select the PC-compiled bitmap/palette response for this stripe phase.
    ld a,(band) : ld e,a : add a,a : add a,e : ld e,a : ld d,0
    ld hl,configs : add hl,de : call fetch : ld a,(phase) : ld e,a : ld d,0 : add hl,de
    ld a,(hl) : ld l,a : ld h,0 : ld d,h : ld e,l : add hl,hl : add hl,de : push hl
    ld hl,configs+30 : ld a,(viewTheme) : or a : jr z,.map : inc hl : inc hl : inc hl
.map: call fetch : pop de : add hl,de : call fetch
    ld de,groupRows+8 : ld bc,MATRIX_SIZE : ldir : ld de,road0 : ld bc,8 : ldir
    ld ix,pres0+1 : ld de,presStride
    dup 8
      ld a,(hl) : ld (ix),a : inc hl : add ix,de
    edup
    ld a,7 : call page
    ; Fill each scanline with the stripe's asphalt byte. Plain grass cells
    ; use identical ink and paper, so those bits can be shared with the road.
    ld a,(band) : add a,a : add a,a : add a,a : add a,112 : ld (fillY),a
    ld ix,road0 : ld b,8
.fill: push bc : ld a,(fillY) : call addr : ld a,(ix+0)
    dup 32
      ld (hl),a : inc l
    edup
    inc ix : ld hl,fillY : inc (hl) : pop bc : djnz .fill
    ld a,(band) : ld l,a : ld h,0 : add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    push hl : ld bc,baseAttrs : add hl,bc : ld (basePtr),hl : pop hl
    push hl : ld bc,mixedCols : add hl,bc : ld (listPtr),hl : pop hl
    ld a,(band) : ld c,a : ld b,high dirty : ld a,(bc) : or a : jr z,.known
    xor a : ld (bc),a : push hl : call classify : pop hl
.known:
    push hl : ld bc,#19c0 : add hl,bc : ld a,(screenHigh) : add a,h : ld h,a : ex de,hl
    ld (attrStart),de : ld hl,(basePtr) : ld bc,32 : ldir : pop hl
    ld a,h : add a,high materials : ld (sourceHigh+1),a : ld a,l : ld (sourceLow+1),a
    ld a,(band) : add a,a : add a,a : add a,a : add a,112 : call addr : ld (destStart),hl
    ld a,(band) : ld l,a : ld h,high counts : ld a,(hl) : or a : jp z,finishBand
    ld (cols),a : ld hl,(listPtr) : ld (nextMixed+1),hl
nextMixed: ld hl,0 : ld a,(hl) : inc hl : ld (nextMixed+1),hl : ld c,a : ld b,0
    ld hl,(attrStart) : add hl,bc : ld (attribute+1),hl
    ld hl,(destStart) : add hl,bc : ex de,hl
sourceLow: add a,0 : ld l,a
sourceHigh: ld h,0
    xor a : ex af,af'
pres0:
    dup 8
      ld b,0 : ld c,(hl) : ld a,(bc) : ld c,a : ex af,af' : or c : ex af,af' : inc h : inc h
    edup
presStride equ ($-pres0)/8
    ex af,af' : ld c,a : ld b,high groupMap : ld a,(bc)
    push hl : add a,a : add a,a : add a,a : ld l,a : ld h,high groupRows : push hl : pop ix
    pop hl : ld a,(sourceHigh+1) : ld h,a
    dup 8,i
      ld b,(ix+i) : ld c,(hl) : ld a,(bc) : ld (de),a : inc h : inc h : inc d
    edup
    ld a,ixl : rrca : rrca : rrca : add a,16 : ld c,a : ld b,high groupMap : ld a,(bc)
writeAttr:
attribute: ld bc,0 : ld (bc),a
    ld a,(cols) : dec a : ld (cols),a : jp nz,nextMixed
finishBand:
    ld a,(band) : inc a : ld (band),a : cp 10 : jp nz,roadBand : ret

; Record which columns have paint or a silhouette crossing an 8x8 cell.
; Reuse these lists while that band's eight projected centres stay fixed.
classify:
    ld a,h : add a,high materials : ld h,a : ld (classHigh+1),a
    ld ix,(basePtr) : ld de,(listPtr) : ld b,32 : ld c,0
.cell: ld a,(hl) : or a : jr z,.test : cp ROAD_ID : jr nz,.mixed
.test:
    dup 7
      inc h : inc h : cp (hl) : jr nz,.mixed
    edup
    or a : ld a,(groupMap+16) : jr z,.store
    ld a,(groupMap+2) : push hl : add a,16 : ld l,a : ld h,high groupMap : ld a,(hl) : pop hl : jr .store
.mixed: ld a,32 : sub b : ld (de),a : inc de : inc c
.store: ld (ix),a : inc ix
classHigh: ld h,0 : inc l : djnz classify.cell
    ld a,(band) : ld l,a : ld h,high counts : ld (hl),c : ret

; The preparation loop patches one operand for each stripe row.
road0: ds 8

; A = physical scanline, HL = first byte in the hidden display file.
addr:
    ld c,a : and 7 : ld h,a : ld a,c : rrca : rrca : rrca : and #18 : or h : ld h,a
    ld a,(screenHigh) : or h : ld h,a : ld a,c : rlca : rlca : and #e0 : ld l,a : ret

drawSky:
    ld hl,artIndex : ld a,(viewTheme) : or a : jr z,.go : ld de,42 : add hl,de
.go: xor a : ld (tileBand),a
.band: push hl : call fetch : ld de,artCache
.run: ld a,(hl) : inc hl : or a : jr z,.ready : ld b,a : ld a,(hl) : inc hl
.fill: ld (de),a : inc de : djnz .fill : jr .run
.ready: ld a,7 : call page : ld ix,artCache
    ld a,(tileBand) : add a,a : add a,a : add a,a : call addr
    ld a,(tileBand) : ld e,a : ld d,0 : ex de,hl
    add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ld a,(screenHigh) : add a,#18 : add a,h : ld h,a : ex de,hl
    ld b,32
.cell: push bc : push hl : ld a,(ix) : inc ix : ld (de),a : inc de
    dup 8
      ld a,(ix) : inc ix : ld (hl),a : inc h
    edup
    pop hl : inc l : pop bc : djnz .cell
    pop hl : inc hl : inc hl : inc hl : ld a,(tileBand) : inc a : ld (tileBand),a : cp 14 : jp nz,.band
    ; Cache the unshifted panorama in scanline order.
    ld de,skyCache : ld a,64
.cache: push af : push de : call addr : pop de : ld bc,32 : ldir : pop af : inc a : cp 112 : jr nz,.cache
    ld a,(screenHigh) : add a,#19 : ld h,a : ld l,0 : ld bc,192 : ldir
    ld a,255 : ld (cachedLean),a : ld (lastPan),a : ld (lastPan+1),a : ret

; Refresh a panning skyline or restore only the bands touched by the previous
; roadside sprites in this display file.
horizon:
    ld a,(displayBit) : and 8 : add a,a : add a,a : add a,a
    ld e,a : ld d,0 : ld hl,treeDamage : add hl,de : ld (damagePtr),hl
    ld hl,lastPan : ld a,e : or a : jr z,.slot : inc hl
.slot: ld a,(viewPan) : cp (hl) : jp z,restoreTrees
    ld (hl),a : ld hl,(damagePtr) : ld (hl),0
    ld a,64 : ld (skyY),a
.line: ld a,(skyY) : call addr : ex de,hl : ld a,(skyY) : sub 64
    ld l,a : ld h,0 : add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    ld bc,skyCache : add hl,bc : xor a : call panRow
    ld a,(skyY) : and 7 : jr nz,.next
    ld a,(skyY) : sub 64 : ld l,a : ld h,0 : add hl,hl : add hl,hl
    push hl : ld bc,skyCache+1536 : add hl,bc : ex de,hl : pop hl
    ld bc,#1900 : add hl,bc : ld a,(screenHigh) : add a,h : ld h,a : ex de,hl
    ld a,#09 : call panRow
.next: ld a,(skyY) : inc a : ld (skyY),a : cp 112 : jr nz,.line : ret

restoreTrees:
    ld hl,(damagePtr) : ld a,(hl) : ld (hl),0 : or a : ret z
.next: push af : inc hl : ld a,(hl) : inc hl : ld e,(hl) : push hl
    ld (skyY),a : push de : call addr : pop de : ld d,0 : add hl,de : push hl
    ld a,(viewPan) : add a,e : ld e,a : ld a,(viewTheme) : or a : jr nz,.land
    bit 5,e : jr nz,.land : pop hl
    dup 8
      ld (hl),0 : inc h
    edup
    ld a,9 : jr .attribute
.land: ld a,e : and 31 : ld e,a : ld a,(skyY) : sub 64 : ld l,a : ld h,0
    add hl,hl : add hl,hl : add hl,hl : add hl,hl : add hl,hl
    add hl,de : ld bc,skyCache : add hl,bc : pop de : ld bc,32
    dup 8
      ld a,(hl) : ld (de),a : inc d : add hl,bc
    edup
    pop hl : push hl : ld a,(hl) : ld e,a : ld a,(viewPan) : add a,e : and 31 : ld e,a : ld d,0
    ld a,(skyY) : sub 64 : ld l,a : ld h,0 : add hl,hl : add hl,hl : add hl,de
    ld de,skyCache+1536 : add hl,de : ld a,(hl)
.attribute:
    pop hl : push hl : ld e,(hl) : ld d,0 : ld c,a : ld a,(skyY) : ld l,a : ld h,0
    add hl,hl : add hl,hl : add hl,de : ld a,(screenHigh) : add a,#18 : add a,h : ld h,a : ld (hl),c
    pop hl : pop af : dec a : jp nz,.next : ret

panRow:
    ; HL = source, DE = screen. Split a circular 32-byte row at the window edge.
    ld (blank+1),a : ld a,(viewPan) : and 31 : ld c,a : ld b,0
    push hl : add hl,bc : ld a,32 : sub c : ld c,a
    ld a,(viewTheme) : or a : jr nz,.first : ld a,(viewPan) : cp 32 : jr nc,.first
    call fillSky : jr .second
.first: ldir
.second: pop hl : ld a,(viewPan) : and 31 : ret z : ld c,a : ld b,0
    ld a,(viewTheme) : or a : jr nz,.copy : ld a,(viewPan) : cp 32 : jr nc,fillSky
.copy: ldir : ret
fillSky:
    ld b,c
blank: ld a,0
.loop: ld (de),a : inc de : djnz .loop : ret

trees:
    ld hl,(viewPos)
    include "scenery-phase.inc"
    ld a,h : and 15 : ld (treePhase),a : ld a,h : rrca : rrca : rrca : rrca : and 15
    ld e,a : ld d,0 : ld l,e : ld h,d : add hl,hl : add hl,de
    ld de,landmarkIndex : add hl,de : call fetch
    ld a,(treePhase) : ld e,a : ld d,0 : ex de,hl : add hl,hl : add hl,hl
    push hl : add hl,hl : add hl,hl : pop bc : add hl,bc : add hl,de
    ld de,treeData : ld bc,20 : ldir : ld a,7 : call page
    ld ix,treeData : ld b,4
.next: push bc : call tree : ld de,5 : add ix,de : pop bc : djnz .next : ret

tree:
    ld l,(ix+0) : ld h,high centres : ld e,(hl) : ld d,0 : inc h : ld c,(hl) : ld b,d
    ex de,hl : ld a,(subtractLane) : or a : jr z,.add : sbc hl,bc : jr .offset
.add: add hl,bc
.offset: ld e,(ix+1) : ld d,(ix+2) : add hl,de
    ld a,h : or a : ret nz
    ld a,l : rrca : rrca : rrca : and 31 : ld (treeCol),a
    ld a,(viewTheme) : or a : ld a,(ix+3) : ld de,treeBits : jr z,.size
    ld a,(ix+4) : ld de,treeBits+111
.size: ld c,a : ld b,0 : ld hl,treeOffsets : add hl,bc : ld l,(hl) : ld h,b : add hl,de
    ld (treeSource+1),hl : ld hl,treeSizes : add hl,bc : ld a,(hl) : ld (treeHeight),a
    ld c,a : ld a,(ix) : add a,112 : sub c : ld (treeY),a
treeChunk:
    ld a,(treeY) : cp 112 : jr nc,.road
    ; Only these sky cells need restoring when this display file is reused.
    ld hl,(damagePtr) : ld e,(hl) : inc (hl) : ld d,0 : sla e : add hl,de
    inc hl : and #f8 : ld (hl),a : inc hl : ld a,(treeCol) : ld (hl),a
    ld a,(viewTheme) : or a : ld a,#0e : jr z,.attr : ld a,#34 : jr .attr
.road: ld a,(viewTheme) : or a : ld a,#26 : jr z,.attr : ld a,#34
.attr: ld c,a : ld a,(treeY) : and #f8 : ld l,a : ld h,0 : add hl,hl : add hl,hl
    ld a,(treeCol) : add a,l : ld l,a : ld a,(screenHigh) : add a,#18 : add a,h : ld h,a : ld (hl),c
    ld a,(treeY) : call addr : ld a,(treeCol) : add a,l : ld l,a
    ld a,(treeY) : and 7 : ld c,a : ld a,8 : sub c : ld b,a : ld a,(treeHeight)
    cp b : jr nc,.height : ld b,a
.height: sub b : ld (treeHeight),a : ld a,(treeY) : add a,b : ld (treeY),a
treeSource: ld de,0
.copy: ld a,(de) : ld (hl),a : inc de : inc h : djnz .copy
    ld (treeSource+1),de : ld a,(treeHeight) : or a : jp nz,treeChunk : ret

drawBike:
    ld a,(viewLean) : ld hl,cachedLean : cp (hl) : jr z,.cached : ld (hl),a
    ld l,a : ld h,0 : ld e,l : ld d,h : add hl,hl : add hl,de : ld de,artIndex+84 : add hl,de : call fetch
    ld c,(hl) : inc hl : ld b,(hl) : inc hl : ld de,artCache : ldir : ld a,7 : call page
.cached:
    ld ix,artCache : ld a,128 : ld (bikeY),a
.band: ld a,(bikeY) : call addr : ld a,l : add a,13 : ld l,a
    push hl : ld a,(bikeY) : ld l,a : ld h,0 : add hl,hl : add hl,hl
    ld de,#180d : add hl,de : ld a,(screenHigh) : add a,h : ld h,a : ex de,hl : pop hl
    ld b,6
.cell: ld a,(ix) : inc ix : cp 255 : jr z,.skip : ld (de),a
    push bc : push de : push hl : push ix : ex de,hl : pop hl
    dup 8
      ld a,(de) : and (hl) : inc hl : or (hl) : inc hl : ld (de),a : inc d
    edup
    push hl : pop ix : pop hl : pop de : pop bc
.skip: inc l : inc de : djnz .cell
    ld a,(bikeY) : add a,8 : ld (bikeY),a : cp 192 : jp nz,.band : ret

oldCentres: ds 160,#7f
paletteTheme: db 255
stageAddresses:
    dup 80,i
      dw materials+512*(i%8)+32*(i/8)
    edup
    align 256
dirty: ds 10
    align 256
counts: ds 10
    align 256
groupRows: ds 80
cols: db 0
fillY: db 0
basePtr: dw 0
listPtr: dw 0
attrStart: dw 0
destStart: dw 0
baseAttrs equ #5e40
mixedCols equ #bc00
    assert $<=COLOUR_BASE
    org COLOUR_BASE
colours: incbin "colours.bin"
    align 256
groupMap: ds 32   ; followed at +16 by the ULA attribute for each group
configs: incbin "configs.bin"
    align 256
centres: ds 80
    align 256
shifts: ds 80
changed: db 1
lastGeometry: dw 0
lastBank: db #ff
lastLane: db 0
palettes: incbin "palette.bin"
artIndex: incbin "art-index.bin"
shots: incbin "shots.bin"

landmarkIndex: incbin "landmark-index.bin"
treeSizes: incbin "sizes.bin"
treeOffsets: incbin "sprite-offs.bin"
treeBits: incbin "landmarks.bin"
treeData: ds 20
treePhase: db 0
treeY: db 0
treeCol: db 0
treeHeight: db 0
viewPan: db 0
lastPan: db 255,255
damagePtr: dw 0
treeDamage: ds 128
skyY: db 0
viewPos: dw 0
position: dw 0
gear: db 2
gearWait: db 0
running: db 1
lane: db 128
theme: db 0
spaceKey: db 0
shotKeys: db 0
viewLane: db 128
viewTheme: db 0
viewLean: db 0
cachedLean: db 255
skyTheme: db 255,255
tileBand: db 0
bikeY: db 0
laneIndex: db 0
subtractLane: db 0
startCol: db 0
phase: db 0
row: db 0
band: db 0
screenHigh: db #c0
displayBit: db 0
    assert $<poseIndex
    assert poseIndex+3072<#bdf0
    org #bfbf
    jp irq
    savebin "flat.bin",#8000,$-#8000

poseIndex equ #b000
indices equ #7000
materials equ #6000
artCache equ #5b00
skyCache equ #7900
