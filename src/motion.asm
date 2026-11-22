; Bank 6 is selected throughout this routine. Keep the original shape tables
; below this code and the steering slopes above it.
    device ZXSPECTRUM128
    include "motion-symbols.inc"
    org #fa00
motionBuild:
    ; IX is one point past the newly projected road. Expand the last five
    ; shared knots to the six actual paint boundaries in two-pixel units.
    ld de,-25 : add ix,de
    ld iy,motionNext : ld hl,widths : ld b,5
.expand:
    ld c,(hl) : inc hl
    ld a,(ix+1) : ld (iy),a : add a,c : ld (iy+1),a
    ld a,(ix+2) : ld (iy+2),a : add a,c : ld (iy+3),a
    ld a,(ix+3) : ld (iy+4),a : inc a : ld (iy+5),a
    ld de,5 : add ix,de : inc de : add iy,de : djnz .expand
    ld a,(motionHaveOld) : or a : jr z,.save
.wait: ld a,(inFlight) : or a : jr nz,.wait
    ld hl,packets : ld (output+1),hl : xor a : ld (motionCount),a
    ld ix,motionOld : ld iy,motionNext : ld a,136
.band:
    ld (bandY),a : sub 48 : ld l,a : ld h,0
    add hl,hl : add hl,hl : add hl,hl : ld de,previousMap : add hl,de : ld (ownerBand+1),hl
    ld a,(bandY) : sub 136 : add a,a : ld e,a : ld d,0 : ld hl,motionForce : add hl,de : ld (forceBand+1),hl
    ld a,e : add a,176 : ld (touchBand+1),a
    ld a,(bandY) : and #38 : add a,a : add a,a : ld (addressBand+1),a
    ld b,6
.edge:
    push bc : ld a,b : cp 3 : sbc a,a : ld (centre),a
    call edge
    pop bc : inc ix : inc iy : djnz .edge
    ld a,(bandY) : add a,8 : cp 168 : jr nz,.band
    ld a,(motionCount) : or a : jr z,.save : cp 193 : jr c,.publish
    xor a : ld (motionCount),a : jr .save
.publish:
    ld a,1 : ld (motionPending),a
.save:
    ld hl,motionNext : ld de,motionOld : ld bc,30 : ldir
    ld a,1 : ld (motionHaveOld),a : ret

; Accumulators are biased two-pixel coordinates in 8.8 fixed point. A
; quarter unit rounds interpolation to the closest physical pixel.
edge:
    ld a,(ix+6) : cp (iy+6) : jr nz,.checkVisible
    ld a,(bandY) : cp 136 : ret z
    ld a,(ix) : cp (iy) : ret z
.checkVisible:
    ld a,(ix) : or (iy) : or (ix+6) : or (iy+6) : cp 64 : ret c
    ld a,(ix) : and (iy) : and (ix+6) : and (iy+6) : cp 192 : ret nc
    ld a,(ix+6) : sub (ix) : call times16 : add hl,hl : ld (oldSlope+1),hl
    ld e,(ix) : ld d,(iy) : ld a,(bandY) : cp 136 : jr nz,.midTop : ld d,e
.midTop:
    ld a,d : add a,e : rra : ld h,a : ld a,0 : rra : add a,64 : ld l,a
    ld (midCoord+1),hl
    ld a,(iy+6) : sub d : call times16
    ld de,(oldSlope+1) : sra d : rr e : add hl,de : ld (midSlope+1),hl
    ld a,(bandY) : ld (rowY),a
    exx
midCoord:
    ld hl,0
midSlope:
    ld de,0
    exx
    ld h,(ix) : ld l,64
oldSlope:
    ld de,0
line:
    call screenX : add hl,de : exx : ld c,a
    call screenX : add hl,de : cp c : jr z,.steady
    push hl : push de : call span : pop de : pop hl
.steady:
    exx : ld a,(rowY) : inc a : ld (rowY),a : and 7 : jr nz,line
    ret

times16:
    ld l,a : add a,a : sbc a,a : ld h,a
    add hl,hl : add hl,hl : add hl,hl : add hl,hl : ret
screenX:
    ld a,h : sub 64 : jr c,.zero : cp 128 : jr nc,.max
    add a,a : bit 7,l : ret z : inc a : ret
.zero: xor a : ret
.max: ld a,255 : ret

; XOR a short contiguous run, merging the bits belonging to each byte.
; Preserve the resident rider and the old roadside objects throughout the step.
span:
    jr c,.order : ld b,a : ld a,c : ld c,b
.order:
    ld b,a
    ld a,c : sub b : ld (length),a
    ld a,b : and 7 : ld e,a : ld d,0 : ld hl,startBits : add hl,de : ld c,(hl)
    ld a,b : rrca : rrca : rrca : and 31 : ld (column),a
    ld a,(length) : ld b,a : xor a
.bits:
    or c : rrc c : jr c,.flush
    djnz .bits : jp storeByte
.flush:
    push bc : call storeByte : pop bc : ld hl,column : inc (hl) : xor a
    djnz .bits : ret

storeByte:
    ld (mask),a
    ld a,(column) : ld c,a
    ld a,(rowY) : cp 144 : jr c,.owner
    ld a,c : sub 14 : cp 3 : ret c
.owner:
    ; previousMap is 64 bytes per band, two bytes per attribute cell.
ownerBand:
    ld hl,0 : ld a,c : add a,a : add a,l : ld l,a
    ld a,(hl) : and 7 : ld b,a : ld a,(centre) : or a : jr z,ownerBand.kerb
    ld a,b : or a : jr z,ownerBand.emit : cp 2 : ret nz : jr ownerBand.emit
.kerb:
    ld a,b : cp 2 : ret nc
.emit:
    ld hl,motionCount : ld a,(hl) : cp 192 : jr c,.room
    ld (hl),193 : ret
.room:
    inc (hl)
    ; Each pair of ULA columns owns two independently queued four-line blocks.
    ld a,c : srl a : ld e,a : ld d,0
forceBand:
    ld hl,0 : add hl,de
    ld a,(rowY) : and 4 : jr z,.upper
    set 1,(hl) : jr .touch
.upper:
    set 0,(hl)
.touch:
    ld a,e
touchBand:
    add a,0 : ld l,a : ld h,high occupied : set 0,(hl)
    ld a,c
addressBand:
    or 0 : ld e,a : ld a,(rowY) : and 7 : or #50 : ld d,a
    ld a,(centre) : and #80 : or d : ld d,a
output:
    ld hl,0 : ld (hl),e : inc hl : ld (hl),d : inc hl
    ld a,(mask) : ld (hl),a : inc hl : ld (output+1),hl : ret
widths: include "motion-widths.inc"
startBits: db #80,#40,#20,#10,#08,#04,#02,#01
oldX: db 0
mask: db 0
column: db 0
length: db 0
rowY: db 0
bandY: db 0
centre: db 0
    assert $<=#fe00
    savebin "motion.bin",#fa00,$-#fa00
