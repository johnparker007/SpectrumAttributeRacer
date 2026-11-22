"""Compare real 128K display frames with the flat Python road and the ULA palette."""

import argparse
from itertools import groupby
from functools import lru_cache
from hashlib import sha256
from math import floor
import re
from statistics import median
import tempfile
from pathlib import Path

import flat_road as road
from build import executable
from build_flat import LANDMARK_PERIOD, OUT, POSES, ROWS, SCALE, TOP, SIZES, artwork, colour_tables, landmark_tables, native_colour, profile, templates, Tables
from verify import FRAME, paper_frames, require, trace


@lru_cache(None)
def patterns(theme):
    _,ids=templates(Tables())
    groups,attrs,_,pixels,n=colour_tables(ids,theme)
    return {v:k for k,v in ids.items()},groups,attrs,pixels,n


@lru_cache(None)
def art(theme,lean=None):
    return artwork(theme,lean)


@lru_cache(None)
def backdrop(theme):
    tiles=art(theme)
    data=bytearray(112*32)
    attrs=bytearray(14*32)
    for i in range(14*32):
        attrs[i]=tiles[9*i]
        y,x=divmod(i,32)
        for dy in range(8):data[(8*y+dy)*32+x]=tiles[9*i+1+dy]
    return data,attrs


@lru_cache(None)
def ula(attribute,byte):
    bright=8 if attribute&64 else 0
    paper=bytes(reversed(native_colour(bright+(attribute>>3&7))))
    ink=bytes(reversed(native_colour(bright+(attribute&7))))
    return b''.join(ink if byte&(128>>x) else paper for x in range(8))


def expected(position,lane_number,theme):
    q=position>>6
    cam=road.Camera(q*road.LENGTH/POSES,0)
    lane=(lane_number-128)/100
    period=64 if theme=='coast' else 32
    pan=round(cam.heading*period/road.HEADING[road.LENGTH])%period
    phase=position*round(road.LENGTH/(4*road.STRIPE_LENGTH))>>8
    bitmap=bytearray(192*32)
    attributes=bytearray(24*32)
    sky,sky_attrs=backdrop(theme)
    for y in range(TOP):
        for col in range(32):
            index=y*32+col
            # Only the horizon panorama scrolls. The sky above it is uniform.
            source=(col+pan)%period if y>=64 else col
            empty=theme=='coast' and y>=64 and source<32
            bitmap[index]=0 if empty else sky[y*32+source%32]
            attributes[y//8*32+col]=9 if empty else sky_attrs[y//8*32+source%32]

    ids,groups,attrs,pixels,ngroups=patterns(theme)
    centres=[]
    material_rows=[]
    states=[]
    for dy in range(ROWS):
        z=profile(dy)
        x,w,t=cam.section(z)
        centre=round(x*SCALE)-round(lane*road.LANE_SCALE*SCALE*t)
        centres.append(centre)
        line=road.line_width(w)*SCALE
        w*=SCALE
        edge=w*road.KERB_RATIO
        def bound(value):
            return (centre//8)*8+round(centre%8+value)
        bounds=[bound(v) for v in (-w-edge,-w,-w+line,-line*.48,line*.48,w-line,w,w+edge)]
        materials=bytearray(256)
        for l,r,mat in zip(bounds,bounds[1:],(2,3,1,4,1,3,2)):
            l,r=max(0,min(256,l)),max(0,min(256,r))
            materials[l:r]=bytes([mat])*(r-l)
        material_rows.append(materials)
        states.append(((phase+floor(z*256/(4*road.STRIPE_LENGTH)))&255)//64)
    for by in range(0,ROWS,8):
        for col in range(32):
            tile=[tuple(row[col*8:col*8+8]) for row in material_rows[by:by+8]]
            mask=0
            for row,state in zip(tile,states[by:by+8]):
                materials=(0,1,2 if state&1 else 3,3,3 if theme=='coast' and not state&2 else 1)
                for m in set(row):mask|=1<<materials[m]
            group=groups[mask]
            attributes[(TOP+by)//8*32+col]=attrs[group]
            for i,row in enumerate(tile):
                index=((2*states[by+i]+i%2)*ngroups+group)*256+ids[row]
                # The native bulk fill is retained in uniform verge cells.
                if mask==1:
                    index=((2*states[by+i]+i%2)*ngroups+groups[2])*256+ids[(1,)*8]
                bitmap[(TOP+by+i)*32+col]=pixels[index]

    # Project the actual roadside stations, applying the port's sprite LOD.
    s=((position*round(road.LENGTH/LANDMARK_PERIOD)>>8)&255)*LANDMARK_PERIOD/256
    last=floor((s+road.NEAR-road.LANDMARK_OFFSET)/road.LANDMARK_SPACING)
    for station in range(last+4,last,-1):
        z=station*road.LANDMARK_SPACING+road.LANDMARK_OFFSET-s
        _,width,t=cam.section(z)
        foot=round(t*(ROWS-1))
        delta=round(road.landmark_offset(station,width)*SCALE)
        x=centres[foot]+delta
        if not 0<=x<256:continue
        size=min(SIZES,key=lambda n:abs(n-road.NEAR/z*(52*3.55 if theme=='coast' else 38*2.1)*(ROWS-1)/(road.H-1-road.SKY)))
        _,trees=tree_art()
        off=(0 if theme=='coast' else sum(SIZES))+sum(SIZES[:SIZES.index(size)])
        for dy in range(size):
            y=TOP+foot-size+dy
            bitmap[y*32+x//8]=trees[off+dy]
            attributes[y//8*32+x//8]=((0x26 if y>=TOP else 0x0e) if theme=='coast' else 0x34)

    lean=round(2*max(-1,min(1,road.curvature(cam.s+5)*.92)))/2
    rider=iter(art('coast',lean))
    for by in range(128,192,8):
        for col in range(13,19):
            attr=next(rider)
            if attr==255:continue
            attributes[by//8*32+col]=attr
            for y in range(by,by+8):
                i=y*32+col
                bitmap[i]=bitmap[i]&next(rider)|next(rider)
    return b''.join(ula(attributes[(y//8)*32+x],bitmap[y*32+x]) for y in range(192) for x in range(32))


tree_art=lru_cache(None)(landmark_tables)


def check(model,emulator,folder,tape=False):
    s={k:int(v,16) for k,v in re.findall(r'^(\S+): EQU 0x([0-9a-fA-F]+)$',(OUT/'flat.sym').read_text(),re.M)}
    def peek(k,offset=0):return f'PEEK({s[k]+offset:04X}H)'
    state=peek('viewPos')+'+256*'+peek('viewPos',1)+'+65536*'+peek('viewLane')+'+16777216*'+peek('viewTheme')
    raw=folder/'video.raw'
    keys=folder/'keys.txt'
    # Repeat the sequence because tape startup includes ROM loading time.
    keys.write_bytes((b'1111222233334444  pppqq   ooaa  '*30))
    image=OUT/('flat-run.tap' if tape else 'flat-run.sna')
    ev=trace(emulator,image,model,48 if tape else 28,s,[('presented',state),('frame','TSTATESP')],keys,raw)
    captured=[sha256(b''.join(rows)).digest() for rows in paper_frames(raw,192)]
    states=[v for k,v in ev if k=='presented']
    presets=[(round(dist*65536/road.LENGTH),128+round(lane*100),theme.lower()) for _,dist,lane,theme in road.SHOTS]
    views=[(v&65535,v>>16&255,'desert' if v>>24 else 'coast') for v in states]
    decoded=set(views)
    require(set(presets)<=decoded,f'{model} missing keyboard presets {set(presets)-decoded}')
    require(len(decoded-set(presets))>=4,f'{model} no moving camera')
    digests={v:sha256(expected(*v)).digest() for v in decoded}
    first=captured.index(digests[views[0]])
    actual=[h for h,_ in groupby(captured[first:])]
    wanted=[h for h,_ in groupby(digests[v] for v in views)]
    require(actual==wanted[:len(actual)] and len(wanted)-len(actual)<=1,
            f'{model} displayed a partial or incorrect road frame')
    shots={digests[v]:i+1 for i,v in enumerate(presets)}
    for rows in paper_frames(raw,192):
        bgr=b''.join(rows)
        index=shots.pop(sha256(bgr).digest(),None)
        if index:
            pixels=bytearray(bgr);pixels[::3]=bgr[2::3];pixels[2::3]=bgr[::3]
            (OUT/f'shot-{model}-{index}.ppm').write_bytes(b'P6\n256 192\n255\n'+pixels)
        if not shots:break
    ticks=[v for k,v in ev if k=='frame']
    intervals=[round((b-a)/FRAME) for a,b in zip(ticks,ticks[1:])]
    print(model,image.suffix,len(decoded),'distinct cameras;',len(captured)-first,'consecutive video frames matched, median',median(intervals),'refreshes per view',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=('128k','P2','P2A41'),default='128k')
    parser.add_argument('--tape',action='store_true')
    args=parser.parse_args()
    emu=executable(None,'ZESARUX','zesarux','Dropbox/ZX_Coding/ZEsarUX_win-10.3/zesarux.exe')
    with tempfile.TemporaryDirectory(prefix='flat-verify-') as tmp:
        check(args.model,emu,Path(tmp),args.tape)
