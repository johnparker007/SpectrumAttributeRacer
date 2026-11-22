"""Compile the PC flat circuit into native 128K scanline and colour tables."""

from functools import lru_cache
from math import floor
from struct import pack
from itertools import groupby
from pathlib import Path
import argparse
import subprocess

import flat_road as road
from build import ROOT, BUILD, basic_number, executable, header, tape_block

TOP, ROWS, POSES = 112, 80, 1024
SCALE = 256/road.W
OUT = BUILD/'flat-native'
BANKS = (0,1,3,4,6)
GRASS, ROAD, KERB, LINE = range(4)
LANDMARK_PERIOD = 6*road.LANDMARK_SPACING


def profile(y):
    t = y/(ROWS-1)
    return road.depth_at_fraction(t)


class Tables:
    def __init__(self):
        self.pages = {n:bytearray() for n in BANKS}
        self.locations = {}

    def put(self,data):
        data = bytes(data)
        if data not in self.locations:
            page = min(BANKS,key=lambda n:len(self.pages[n]))
            offset = len(self.pages[page])
            if offset+len(data)>16384:
                raise ValueError(f'128K table banks full at {sum(map(len,self.pages.values()))} bytes')
            self.pages[page].extend(data)
            self.locations[data] = page,0xc000+offset
        return self.locations[data]


def pointer(loc):
    bank,address=loc
    return pack('<BH',bank,address)


def track_rows(tables):
    pointers=bytearray()
    for pose in range(POSES):
        cam=road.Camera(pose*road.LENGTH/POSES,0)
        xs=[round(cam.section(profile(y))[0]*SCALE) for y in range(ROWS)]
        assert min(xs)>=0 and max(xs)<256
        # Four-bit signed steps and run lengths free bank space for the
        # complete per-band ULA palette configurations.
        encoded=bytearray(xs[:1])
        for delta,run in groupby(b-a for a,b in zip(xs,xs[1:])):
            count=sum(1 for _ in run)
            while count:
                size=min(16,count)
                code=delta+7 if -7<=delta<=7 else 15
                encoded.append((size-1)*16+code)
                if code==15:encoded.append(delta&255)
                count-=size
        pointers.extend(pointer(tables.put(encoded)))
    return pointers


def templates(tables):
    ids={}
    pointers=bytearray()
    cam=road.Camera(0,0)
    for y in range(ROWS):
        _,w,_=cam.section(profile(y))
        line=road.line_width(w)*SCALE
        w*=SCALE
        edge=road.KERB_RATIO*w
        # At runtime the integer camera centre selects one of eight alignments.
        # Only the active part is stored. The Z80 pads and clips the two verges.
        for phase in range(8):
            left,right = round(phase-w-edge),round(phase+w+edge)
            lo,hi=left//8,(right+7)//8
            packed=[]
            for col in range(lo,hi):
                pattern=[]
                for bit in range(8):
                    x=8*col+bit
                    if x<left or x>=right: mat=GRASS
                    elif x<round(phase-w) or x>=round(phase+w):mat=KERB
                    elif x<round(phase-w+line) or x>=round(phase+w-line):mat=LINE
                    elif round(phase-line*.48)<=x<round(phase+line*.48):mat=4
                    else:mat=ROAD
                    pattern.append(mat)
                key=tuple(pattern)
                packed.append(ids.setdefault(key,len(ids)+1))
            assert len(ids)<256
            pointers.extend(pointer(tables.put(bytes([lo&255,len(packed),*packed]))))
    return pointers,{0:(GRASS,)*8,**{v:k for k,v in ids.items()}}


def best_pair(mask,theme):
    # Each ULA cell has two colours. Keep the road/land silhouette at mixed
    # cells, and reserve red/white for cells entirely occupied by painted kerb.
    grass=4 if theme=='coast' else 6
    shades=[grass,7,2,15]
    present=[i for i in range(4) if mask&(1<<i)]
    if len(present)==1:
        m=present[0]
        return [(grass,grass),(7,0),(2,2),(15,15)][m]
    if mask==9:return grass,7
    if mask==10:return 7,0
    if 0 in present and 1 in present:return grass,7
    if 2 in present and 3 in present and 0 not in present:return 2,7
    if len(present)>1:return shades[present[0]],shades[present[1]]
    return grass,grass


def colour_tables(ids,theme):
    grass=4 if theme=='coast' else 6
    groups=[]
    masks=[]
    for mask in range(16):
        pair=best_pair(mask,theme)
        if pair not in groups:groups.append(pair)
        masks.append(groups.index(pair))
    attrs=[((a&7)*8+(b&7)+(64 if a>=8 or b>=8 else 0)) for a,b in groups]
    # Four stripe states resolve logical paint and centre dashes before
    # attributes are chosen. The upper bits of the output are horizontal pixels.
    presence=bytearray()
    pixels=bytearray()
    for state in range(4):
        lookup=[0,1,2 if state&1 else 3,3,3 if theme=='coast' and not state&2 else 1]
        patterns=[tuple(lookup[m] for m in ids.get(i,ids[0])) for i in range(256)]
        presence.extend(sum(1<<m for m in set(p)) for p in patterns)
        for parity in range(2):
            for a,b in groups:
                for p in patterns:
                    bits=0
                    for x,m in enumerate(p):
                        colour=(grass,7,2,15)[m]
                        if (a,b)==(7,0) and m==1:
                            ink=(x+parity*2)%4==0 if state&1 else bool(parity) and x%4==1
                        elif (a,b)==(2,7) and m==1:
                            ink=not (parity and x%4==1 and state&1)
                        elif colour==a:ink=False
                        elif colour==b:ink=True
                        elif m==3:ink=(b&7)==7
                        elif m==2:ink=(b&7)==2 or ((b&7)==7 and (x+parity)%2==0)
                        else:ink=(b&7)==(colour&7)
                        bits=bits*2+ink
                    pixels.append(bits)
    return bytes(masks),bytes(attrs),presence,pixels,len(groups)


def native_colour(index):
    v=255 if index&8 else 192
    return tuple(v if index&bit else 0 for bit in (2,4,1))


def distance(a,b):
    return sum((x-y)**2*w for x,y,w in zip(a,b,(3,5,2)))


@lru_cache(None)
def fit_cell(histogram):
    # Pick actual ULA colour pairs, respecting the single brightness bit.
    costs={colour:[distance(colour,native_colour(i)) for i in range(16)]
           for colour,_ in histogram}
    def error(pair):
        a,b=pair
        return sum(count*min(costs[c][a],costs[c][b]) for c,count in histogram)
    pairs=((a,b) for a in range(16) for b in range(a//8*8,a+1))
    a,b=min(pairs,key=error)
    return ((a&7)*8+(b&7)+(64 if a&8 else 0),
            {c:costs[c][b]<costs[c][a] for c,_ in histogram})


def artwork(theme,lean=None):
    from collections import Counter
    if lean is None:
        source=road.scenery('Coast' if theme=='coast' else 'Desert')
        x0,y0,w,h=0,0,256,TOP
    else:
        source=bytearray([1,2,3])*(road.W*road.H)
        road.bike(source,road.W/2,road.H-1,1.,lean)
        x0,y0,w,h=104,128,48,64
    data=bytearray()
    for by in range(y0,y0+h,8):
        for bx in range(x0,x0+w,8):
            colours=[]
            for y in range(by,by+8):
                sy=(int(y*road.SKY/TOP) if lean is None else
                    round(road.SKY+(y-TOP)*(road.H-1-road.SKY)/(ROWS-1)))
                for x in range(bx,bx+8):
                    i=3*(sy*road.W+int(x*road.W/256))
                    c=tuple(source[i:i+3])
                    if lean is None and theme=='desert':
                        r,g,_=c
                        if sy<road.SKY and c==(255,165,0):
                            c=(255,255,0)
                        else:
                            c=(0,0,0) if ((x&3)+4*(y&3))<max(1,(193-g)//11) else (192,192,0)
                    colours.append(c)
            bg=(1,2,3)
            hist=Counter(c for c in colours if c!=bg)
            if not hist:
                data.append(255)
                continue
            if lean is not None and len(hist) and bg in colours:
                hist[(170,170,170)]+=colours.count(bg)
            attr,inks=fit_cell(tuple(sorted(hist.items())))
            data.append(attr)
            for i in range(0,64,8):
                row=colours[i:i+8]
                if lean is not None:data.append(sum((c==bg)<<(7-j) for j,c in enumerate(row)))
                data.append(sum(inks.get(c,False)<<(7-j) for j,c in enumerate(row)))
    return data


SIZES=(4,6,9,13,18,25,36)


def landmark_tables():
    # One 72-unit block contains a complete repeat of the six tree placements.
    records=bytearray()
    for phase in range(256):
        s=phase*LANDMARK_PERIOD/256
        current=floor((s+road.NEAR-road.LANDMARK_OFFSET)/road.LANDMARK_SPACING)
        for i in range(current+4,current,-1):
            z=i*road.LANDMARK_SPACING+road.LANDMARK_OFFSET-s
            _,w,t=road.Camera(s,0).section(z)
            delta=round(road.landmark_offset(i,w)*SCALE)
            foot=round(t*(ROWS-1))
            records.extend(pack('<Bh',foot,delta))
            for height in (52*3.55,38*2.1):
                h=road.NEAR/z*height*(ROWS-1)/(road.H-1-road.SKY)
                records.append(min(range(len(SIZES)),key=lambda j:abs(SIZES[j]-h)))
    sprites=bytearray()
    for desert in (False,True):
        for size in SIZES:
            image=bytearray(road.W*road.H*3)
            road.landmark(image,32,64,size/(38 if desert else 52),desert)
            # One eight-pixel column with a striped trunk/interior highlight.
            for y in range(64-size,64):
                byte=0
                for x in range(8):
                    sx=round(32+(x-3.5)*max(1,size/24))
                    pixel=image[(y*road.W+sx)*3:(y*road.W+sx)*3+3]
                    if any(pixel):byte|=128>>x
                sprites.append(byte)
    return records,sprites


def build(assembler):
    out=OUT
    out.mkdir(exist_ok=True,parents=True)
    tables=Tables()
    geom=track_rows(tables)
    shape,ids=templates(tables)
    (out/'solid.inc').write_text(f'ROAD_ID equ {next(i for i,v in ids.items() if v==(ROAD,)*8)}\n')
    lanes=bytearray()
    for lane in range(121):
        shift=[round(lane/100*road.LANE_SCALE*SCALE*y/(ROWS-1)) for y in range(ROWS)]
        lanes.extend(pointer(tables.put(shift)))
    # Every stripe phase for an eight-line ULA band has a small exact set
    # of palette choices. Intern full configurations once across the circuit.
    signatures={}
    signature_maps=bytearray()
    for y in range(0,ROWS,8):
        phases=[]
        for phase in range(256):
            key=tuple(((floor(profile(y+i)*256/(4*road.STRIPE_LENGTH))+phase)&255)//64 for i in range(8))
            phases.append(signatures.setdefault(key,len(signatures)))
        signature_maps.extend(pointer(tables.put(phases)))
    palette=bytearray()
    unique=[]
    def page(data):
        data=bytes(data)
        if data not in unique:unique.append(data)
        return 0x91+unique.index(data)
    config_sizes=set()
    for theme in ('coast','desert'):
        groups,attrs,pres,pix,n=colour_tables(ids,theme)
        palette.extend(groups)
        palette.extend(attrs+bytes(16-n))
        response_pages=[page(pix[k:k+256]) for k in range(0,len(pix),256)]
        presence=[page(pres[k:k+256]) for k in range(0,1024,256)]
        pure_road=next(i for i,p in ids.items() if p==(ROAD,)*8)
        pointers=bytearray()
        for sig in signatures:
            config=bytearray()
            for group in range(1,n):
                config.extend(response_pages[(2*state+i%2)*n+group] for i,state in enumerate(sig))
            config.extend(pix[((2*state+i%2)*n+groups[2])*256+pure_road] for i,state in enumerate(sig))
            config.extend(presence[state] for state in sig)
            pointers.extend(pointer(tables.put(config)))
        signature_maps.extend(pointer(tables.put(pointers)))
        config_sizes.add((n-1)*8)
    assert len(config_sizes)==1
    config_size=config_sizes.pop()
    (out/'config.inc').write_text(f'MATRIX_SIZE equ {config_size}\nCOLOUR_BASE equ #9100\n')
    (out/'configs.bin').write_bytes(signature_maps)
    (out/'colours.bin').write_bytes(b''.join(unique))
    (out/'palette.bin').write_bytes(palette)
    (out/'indices.bin').write_bytes(geom+shape+lanes)
    # Generate short constant-multiply routines for distance phases directly
    # from the master's repeat lengths. HL starts at the fractional lap position.
    for name,period in [('paint',4*road.STRIPE_LENGTH),('scenery',LANDMARK_PERIOD)]:
        cycles=round(road.LENGTH/period)
        assert abs(cycles*period-road.LENGTH)<1e-6, 'pattern must wrap at the finish'
        code=['    ld d,h : ld e,l']
        for bit in bin(cycles)[3:]:
            code.append('    add hl,hl')
            if bit=='1':code.append('    add hl,de')
        (out/f'{name}-phase.inc').write_text('\n'.join(code)+'\n')
    shots=bytearray()
    for _,s,l,t in road.SHOTS:
        pos=round(s*65536/road.LENGTH)
        shots.extend(pack('<HBB',pos,128+round(l*100),int(t=='Desert')))
    (out/'shots.bin').write_bytes(shots)
    # Artwork is only fetched when a palette or lean changes. Store compressed
    # runs to leave the resident colour and geometry tables room in 128K.
    def encoded(data):
        result=bytearray()
        for value,grp in groupby(data):
            count=sum(1 for _ in grp)
            while count:
                n=min(count,255);result.extend((n,value));count-=n
        result.append(0)
        return result
    sky=bytearray()
    for theme in ('coast','desert'):
        # Store one row of tiles at a time so artwork shares free bank tails.
        data=artwork(theme)
        for i in range(TOP//8):
            sky.extend(pointer(tables.put(encoded(data[i*288:(i+1)*288]))))
    # These five silhouettes come from the PC artist routine.
    lean=[]
    for v in (-1,-.5,0,.5,1):
        sprite=artwork('coast',v)
        lean.append(tables.put(pack('<H',len(sprite))+sprite))
    (out/'art-index.bin').write_bytes(sky+b''.join(pointer(p) for p in lean))
    landmarks,sprites=landmark_tables()
    # A row repeats at 72 world units. Split it so no bank needs a 5K hole.
    signposts=[tables.put(landmarks[i:i+320]) for i in range(0,len(landmarks),320)]
    (out/'landmark-index.bin').write_bytes(b''.join(pointer(p) for p in signposts))
    (out/'landmarks.bin').write_bytes(sprites)
    (out/'sizes.bin').write_bytes(bytes(SIZES))
    (out/'sprite-offs.bin').write_bytes(bytes(sum(SIZES[:i]) for i in range(len(SIZES))))
    views=bytearray(2+round(2*max(-1,min(1,road.curvature(q*road.LENGTH/POSES+5)*.92))) for q in range(POSES))
    for period in (64,32):
        views.extend(round(road.Camera(q*road.LENGTH/POSES,0).heading*period/road.HEADING[road.LENGTH])%period for q in range(POSES))
    (out/'views.bin').write_bytes(views)
    for n,data in tables.pages.items():(out/f'bank{n}.bin').write_bytes(data)
    print('Flat road bank sizes', [len(p) for p in tables.pages.values()],flush=True)
    def assemble(src):
        subprocess.run([assembler,'--nologo',f'--inc={out}',f'--sym={src.stem}.sym',src],cwd=out,check=True)
    assemble(ROOT/'src/flat.asm')
    blocks=[(16+n,0xc000,f'bank{n}.bin') for n in BANKS]
    blocks.extend([(23,0xdc00,'indices.bin'),(23,0xf100,'views.bin'),(16,0x8000,'flat.bin')])
    (out/'blocks.inc').write_text(''.join(f'    db {n}\n    dw {addr},{(out/file).stat().st_size}\n' for n,addr,file in blocks))
    assemble(ROOT/'src/loader.asm')
    line=b'\xfd'+basic_number(0x6fff)+b':\xef""\xaf:\xf9\xc0'+basic_number(0x7000)+b'\r'
    basic=b'\0\x0a'+pack('<H',len(line))+line
    tap=header(0,b'Flat racer',basic,10,len(basic))+header(3,b'FLAT RACER',(out/'loader.bin').read_bytes(),0x7000,0x8000)
    (out/'flat-run.tap').write_bytes(tap+b''.join(tape_block(255,(out/file).read_bytes()) for _,_,file in blocks))
    snap=out/'snapshot.asm'
    snap.write_text('    device ZXSPECTRUM128\n'+''.join(f'    page {n&7}\n    org {addr}\n    incbin "{file}"\n' for n,addr,file in blocks)+'    page 0\n    savesna "flat-run.sna",#8000\n')
    assemble(snap)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assembler',type=Path)
    args=parser.parse_args()
    build(executable(args.assembler,'SJASMPLUS','sjasmplus','Desktop/_temp/sjasmplus-1.20.2.win/sjasmplus.exe'))
