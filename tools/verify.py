"""Exercise the release TAP, keyboard, frame deadlines and ULA output in headless ZEsarUX."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import tempfile

from build import BUILD, executable
from course import ATTRS, riders
from kerbs import FIRST, LINES, bands, nearest, projected, ribbons, surface
from route import COURSES, DASH
from strokes import object_cells

FRAME, LINE = 70908, 228
WIDTH, HEIGHT = 352, 304
HIT = re.compile(r"Catch breakpoint: ([^\n]+)\n(\d+)\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(emulator, image, model, seconds, options):
    load = (["--fastautoload","--tape",image] if image.suffix == ".tap" else
            ["--snap-no-change-machine","--snap",image])
    args = [emulator,"--noconfigfile","--vo","null","--ao","null","--realvideo",
            "--disable-debug-console-win","--nowelcomemessage","--stats-disable-check-updates",
            "--stats-disable-check-yesterday-users","--machine",model,*load,"--verbose","2",
            "--exit-after",str(seconds),"--quickexit",*options]
    proc = subprocess.run(args,cwd=emulator.parent,capture_output=True,text=True,errors="replace",
                          timeout=seconds+35,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    require(proc.returncode == 0, f"{model} emulator exit {proc.returncode}: {proc.stderr[-1500:]}")
    return proc.stdout+proc.stderr


def trace(emulator, image, model, seconds, symbols, points, spool=None, capture=None):
    opts = ["--enable-breakpoints"]
    if capture:
        opts.extend(["--vofilefps","50","--frameskip","0","--disable-autoframeskip","--vofile",capture])
    labels = {}
    for i,(name,expr) in enumerate(points,1):
        condition = f"PC={symbols[name]:04X}H"
        opts.extend(["--set-breakpoint",str(i),condition,"--set-breakpointaction",str(i),"printe "+expr])
        labels[condition] = name
    if spool:
        opts.extend(["--keyboardspoolfile",spool,"--keyboardspoolfile-play","--keyboardspoolfile-keylength","8"])
    log = run(emulator,image,model,seconds,opts)
    hits = [(labels[k],int(v)) for k,v in HIT.findall(log)]
    require(hits and len(hits)==log.count("Catch breakpoint:"), f"{model} incomplete debugger capture")
    return hits


def fixture(folder, name, image, symbols, **changes):
    data = bytearray(image.read_bytes())
    for symbol, value in changes.items():
        addr = symbols[symbol]
        require(0x8000<=addr<0xc000, f"Invalid fixed-bank fixture address {symbol}")
        data[27+16384+addr-0x8000] = value
    path = folder/(name+".sna")
    path.write_bytes(data)
    return path


@lru_cache(maxsize=8192)
def pixels(attr, bits):
    level = 255 if attr & 64 else 192
    colours = [bytes(level if c & channel else 0 for channel in (1,4,2))
               for c in ((attr>>3)&7, attr&7)]  # ZEsarUX BGR24
    return b"".join(colours[bool(bits & (128>>bit))] for bit in range(8))


def paper_frames(raw,height):
    with raw.open("rb") as frames:
        while frame := frames.read(3*WIDTH*HEIGHT):
            require(len(frame)==3*WIDTH*HEIGHT,"Truncated real-video frame")
            yield [frame[3*((y+56)*WIDTH+48):3*((y+56)*WIDTH+304)] for y in range(height)]



@lru_cache(maxsize=384)
def scene_pixels(course,pose,lane,lean):
    """Project intervals directly, independently of the Z80's glyph atlas."""
    first,points=bands(pose,course)
    bits=[0]*LINES
    styles=bytearray(LINES*4)
    for i,(a,b) in enumerate(zip(points,points[1:])):
        band=first//8+i
        for start,end,w,v,style in ribbons(a,b,lane):
            for dy in range(8):
                lo=2*(start-64)+(2*(end-start)*dy+4)//8
                hi=2*(start-64)+w+((2*(end-start)+v-w)*dy+4)//8
                lo,hi=max(0,lo),min(256,hi)
                if lo>=hi: continue
                for c in range(lo//8,(hi-1)//8+1):
                    index=band*32+c
                    if styles[index]!=1:styles[index]=style
                y=band*8+dy
                if y>=first: bits[y]|=((1<<(hi-lo))-1)<<(256-hi)
    for width,cells in object_cells(pose,course):
        shift=(128+width*nearest((lane-128)*128/112))//256
        if width<34:shift=(shift+1)//2*2
        shift=(shift+2)//4
        for band,base,style,glyph in cells:
            col=base-shift
            if not 0<=col<32:continue
            index=band*32+col
            if styles[index] in (1,2):continue
            styles[index]=style
            for dy,byte in enumerate(glyph):
                bits[band*8+dy]|=byte<<(248-8*col)
    art=riders()[162*lean:162*(lean+1)]
    for cell in range(9):
        r,x=divmod(cell,3);col=14+x; y0=144-FIRST+r*8;index=y0//8*32+col
        if styles[index] not in (1,2):styles[index]=(5,3,5,6,6,6,5,5,5)[cell]
        for k in range(8):
            mask,ink=art[cell*18+2+2*k:cell*18+4+2*k]
            bits[y0+k]=(bits[y0+k]&~((mask^255)<<(248-8*col)))|(ink<<(248-8*col))
    return bits, styles


def foreground_boundaries(course, pose, lane):
    """The six edges of the visible paint at each of the five foreground knots."""
    crest, points = bands(pose, course)
    result = []
    for y in range(136, 169, 8):
        point = points[(y-FIRST)//8-crest//8]
        left, right, centre, width = projected(point, lane)
        left, right, centre = (2*(x-64) for x in (left, right, centre))
        result.append((left, left+width, right, right+width, centre, centre+2))
    return result


def apply_foreground_midpoint(course, pose, lane, next_pose, next_lane, bits, styles):
    old = foreground_boundaries(course, pose, lane)
    target = foreground_boundaries(course, next_pose, next_lane)
    middle = [old[0]] + [tuple((a+b)//2 for a,b in zip(start,end))
                         for start,end in zip(old[1:],target[1:])]
    planes = [bits.copy(), bits.copy()]

    def paint_span(left, right):
        # The native patch clips its two boundary coordinates to byte range.
        left, right = (min(255, max(0, v)) for v in (left, right))
        return ((1 << (right-left)) - 1) << (256-right)

    for band in range(4):
        y0 = 136+band*8
        cells = styles[(y0-FIRST)//8*32:(y0-FIRST)//8*32+32]
        for side in range(3):
            centre = side == 2
            allowed = (0,2) if centre else (0,1)
            mask = int.from_bytes(bytes(255 if style in allowed and
                                        (y0 < 144 or not 14 <= col <= 16) else 0
                                        for col,style in enumerate(cells)), 'big')
            for dy in range(8):
                spans = []
                for shape in (old, middle):
                    top = shape[band][2*side:2*side+2]
                    bottom = shape[band+1][2*side:2*side+2]
                    left, right = ((a*(8-dy)+b*dy+4)//8 for a,b in zip(top,bottom))
                    spans.append(paint_span(left,right))
                change = (spans[0] ^ spans[1]) & mask
                y = y0+dy-FIRST
                planes[0][y] ^= change
                if not centre:
                    planes[1][y] ^= change
    return planes


@lru_cache(maxsize=384)
def picture(course, pose, lane, lean, next_pose=None, next_lane=None):
    bits, styles = scene_pixels(course,pose,lane,lean)
    planes = ((bits,bits) if next_pose is None else
              apply_foreground_midpoint(course,pose,lane,next_pose,next_lane,bits,styles))
    pair = [[],[]]
    for bank, rows in enumerate(planes):
        for y, row in enumerate(rows):
            attrs = styles[(y//8)*32:(y//8+1)*32]
            pair[bank].append(b''.join(pixels(ATTRS[style][bank],value)
                                      for style,value in zip(attrs,row.to_bytes(32,'big'))))
    return pair


def road_image(course,pose,lane,lean,phase,next_pose=None,next_lane=None):
    screens=picture(course,pose,lane,lean,next_pose,next_lane)
    return [screens[int(r is None or (r[2]+phase)&16!=0)][y] for y,r in enumerate(surface(pose,course))]


def symbols_for(out):
    return {k:int(v,16) for k,v in re.findall(r'^(\S+): EQU 0x([0-9A-Fa-f]+)$',
                                               (out/'racer.sym').read_text(),re.M)}
def frame_states(events):
    frames = []
    for label, value in events:
        if label == "calibrated":
            frames.append((value&255, (value>>8)&255, (value>>16)&3, value>>18))
        elif label == "turnRaster" and frames and value&1:
            frames[-1] += ((value>>8)&255, (value>>16)&255)
    return frames


@lru_cache(maxsize=4096)
def frame_digest(course,pose,lane,lean,phase,next_pose=None,next_lane=None):
    return sha256(b"".join(road_image(course,pose,lane,lean,phase,next_pose,next_lane))).digest()


def compare_capture(raw,course,states):
    actual=[sha256(b"".join(rows[FIRST:DASH])).digest() for rows in paper_frames(raw,192)]
    expected=[frame_digest(course,*state) for state in states]
    # Tape loading and IRQ calibration precede the first live frame. Once
    # synchronised, require consecutive matches, including held road poses.
    probe=min(10,len(expected))
    start=next((i for i,a in enumerate(actual) if a==expected[0] and actual[i:i+probe]==expected[:probe]),None)
    require(start is not None, f"{course}: could not synchronise the video with the displayed camera")
    count=min(len(expected),len(actual)-start)
    require(abs(len(expected)-(len(actual)-start))<=2,f"{course}: trace/video lengths differ")
    for i in range(count):
        require(actual[start+i]==expected[i],f"{course} torn or incorrect pixels at video frame {start+i}, camera {states[i]}")
    return start,count


def check_timing(emu,model,image,s,seconds=8,spool=None):
    ev=trace(emu,image,model,seconds,s,[("irq","TSTATESP"),("burstOut","TSTATES"),("tailOut","TSTATES")],spool)
    groups=[]
    for k,v in ev:
        if k=="irq": groups.append([])
        elif groups: groups[-1].append(v)
    timed=[g for g in groups if len(g)==LINES]
    require(len(timed)>20,f"{model} incomplete timing trace")
    for g in timed:
        require(all(b-a==LINE for a,b in zip(g,g[1:])),f"{model} scanline drift at latch {g[0]}")
    return f"{len(timed)} complete rasters, {LINES} latches at {LINE} T"


def check_drive(emu,model,image,s,course,folder,seconds,keys=True,tape=False,full_lap=False):
    def peek(name):return f"PEEK({s[name]:04X}H)"
    state=peek("displayPose")+"+256*"+peek("displayLane")+"+65536*"+peek("displayLean")+"+262144*"+peek("phase")
    points=[("calibrated",state),("irq","TSTATESP"),("showState","TSTATESP"),
            ("rasterDone.finish","TSTATES"),("controls",peek("passes")+"+256*"+peek("gear"))]
    if "midState" in s:
        target = peek("midState")+"+256*"+peek("drawingPose")+"+65536*"+peek("drawingLane")
        points.append(("turnRaster",target))
    if tape:
        points.append(("start", "PEEK(5B5CH)"))
    raw=folder/"drive.raw"
    spool=None
    if keys:
        spool=folder/"drive.txt"
        spool.write_bytes(b"     p    oo   p       p oo    p         "*28)
    source=image.with_suffix(".tap") if tape else fixture(folder,"top-gear",image,s,gear=4,lane=132,displayLane=132)
    ev=trace(emu,source,model,seconds,s,points,spool,capture=raw)
    if tape:
        writer_byte = (image.parent / "copy5.bin").read_bytes()[0x5c]
        require(("start", writer_byte) in ev, f"{model} ROM loader damaged the bank 5 bitmap writer")
    states=frame_states(ev)
    require(states,f"{model} never displayed a racing frame")
    irqs=[v//FRAME for k,v in ev if k=="irq"][2:]
    require(all(b==a+1 for a,b in zip(irqs,irqs[1:])),f"{model} missed an interrupt")
    start,frames=compare_capture(raw,course,states)
    if "midState" in s and (not tape or full_lap):
        require(any(len(frame)==6 for frame in states[:frames]),f"{model} never displayed an intermediate road frame")
    poses=[k[0] for k in states[:frames]]
    changes=[q for i,q in enumerate(poses) if i==0 or poses[i-1]!=q]
    require(all(q==(p+1)%256 for p,q in zip(changes,changes[1:])),f"{model} skipped a camera position")
    if not tape or full_lap:
        require(len(set(poses))==256 and 0 in changes[1:],f"{model} missed part of a lap ({len(set(poses))} poses)")
        require({v[2] for v in states}=={0,1,2},f"{model} steering did not exercise both directions")
    else:
        require(len(set(poses))>=3,f"{model} retail TAP did not start moving")
    if not tape:
        require(any(v%256>=2 for k,v in ev if k=="controls"),f"{model} overtake counter")
    waits=[v for k,v in ev if k=="rasterDone.finish"]
    headroom=FRAME-max(waits)
    require(headroom>300,f"{model} trailing border exhausted")
    return f"{frames} consecutive pixel-exact frames, {len(set(poses))} poses, {headroom} T before interrupt",start,states


def check_controls(emu,model,image,s,folder):
    spool=folder/"gears.txt"
    def peek(name):return f"PEEK({s[name]:04X}H)"
    # Sample after the keyboard poll and at the point where the renderer takes
    # its camera snapshot. A queued target would keep moving after release.
    state = peek("lane")+"+256*"+peek("lean")+"+1024*"+peek("gear")
    camera = peek("lane")+"+256*"+peek("drawingLane")
    for start, keys, limit in ((10,b"ooo ppp q a ",8), (246,b"ppp ooo a q ",248)):
        spool.write_bytes(keys*10)
        ride = fixture(folder,"steer",image,s,lane=start,displayLane=start)
        ev = trace(emu,ride,model,7,s,[("tick",state),("prepare.cachedLane",camera)],spool)
        previous = start
        lanes, leans, gears = set(), set(), set()
        cameras = 0
        for label,value in ev:
            lane = value % 256
            if label == "prepare.cachedLane":
                require(lane == value//256, f"{model} camera lagged the sampled lane")
                cameras += 1
                continue
            lean = value//256 % 4
            require(lane == max(8,min(248,previous+lean-1)),
                    f"{model} steering step from {previous} to {lane}, lean {lean}")
            previous = lane
            lanes.add(lane); leans.add(lean); gears.add(value//1024)
        require(limit in lanes and len(lanes)>4 and leans=={0,1,2} and len(gears)>1 and cameras>5,
                f"{model} incomplete direct steering exercise")
    collision=fixture(folder,"contact",image,s,pose=123,gear=4,lane=78,displayLane=78)
    ev=trace(emu,collision,model,3,s,[("tick",peek("gear")+"+256*"+peek("bump"))])
    require(any(v%256==4 and v>=256 for _,v in ev),f"{model} missed collision")

    # Hold Q at the verge and through an overtake. Check the stripe phase too:
    # a speed penalty can leave the displayed gear untouched.
    spool.write_bytes(b"q"*100)
    state = peek("gear")+"+256*"+peek("phase")+"+8192*"+peek("bump")
    for name, lane in (("verge",8), ("rival",78)):
        ride = fixture(folder,name,image,s,pose=123,lane=lane,displayLane=lane,gear=2)
        ev = trace(emu,ride,model,7,s,[("tick",state)],spool)
        samples = [value for _, value in ev]
        first = next((i for i,v in enumerate(samples) if v % 256 == 4),len(samples))
        top = samples[first:]
        require(len(top) > 50 and all(v % 256 == 4 for v in top),
                f"{model} lost top gear on {name}")
        require(all(((b//256-a//256) % 32) == 4 for a,b in zip(top,top[1:])),
                f"{model} lost wheel speed on {name}")
        if name == "rival":
            require(any(v//8192 for v in samples), f"{model} missed held-Q contact fixture")


def check_kerb_motion(course):
    # These scanlines reversed direction repeatedly through the same bend.
    # With the keys released, the lateral camera coordinate stays fixed.
    for lane in (8,64,128,192,248):
        previous = None
        for step in range(257):
            pose = step % 256
            crest, points = bands(pose, course)
            a,b = (projected(p,lane) for p in points[:2])
            # Measure at the actual (moving) first visible scanline.
            edges = [2*(a[i]-64) + (2*(b[i]-a[i])*(crest%8)+4)//8 for i in (0,1)]
            centre = (sum(edges)+a[3])/2
            if previous is not None:
                require(abs(centre-previous) <= 3, f"{course} horizon jumped at pose {pose}")
            previous = centre

    cases = ([(239, 128, 137, 0), (184, 128, 84, 0)]
             if course == "coast" else [(182, 155, 152, 1)])
    for first_pose, lane, y, side in cases:
        positions = []
        for step in range(5):
            pose = (first_pose + step) % 256
            crest, points = bands(pose, course)
            band = (y - FIRST)//8 - crest//8
            a, b = (projected(point, lane)[side] for point in points[band:band+2])
            positions.append(2*(a-64) + (2*(b-a)*(y % 8)+4)//8)
        distance = sum(abs(b-a) for a, b in zip(positions, positions[1:]))
        require(distance == abs(positions[-1]-positions[0]),
                f"{course} kerb reversed at scanline {y}, pose {first_pose}: {positions}")


def check_reference(course):
    from road_model import lap
    # Rasterise the port's spans, including the outer edge of tapered paint.
    # Compare to the double-precision model before any knot or grid rounding.
    worst = 0.0
    for pose, view in enumerate(lap(course)):
        crest, knots = bands(pose,course)
        for lane in (8,64,128,192,248):
            points = [projected(k,lane) for k in knots]
            for y in range(FIRST+crest,DASH):
                band = (y-FIRST)//8-crest//8
                a,b = points[band:band+2]
                ideal = view.boundaries(y,lane)
                for edge,(i,outer) in enumerate(((0,False),(0,True),(1,False),(1,True))):
                    start = 2*(a[i]-64)+(a[3] if outer else 0)
                    end = 2*(b[i]-64)+(b[3] if outer else 0)
                    pixel = start+((end-start)*(y%8)+4)//8
                    worst = max(worst,abs(pixel-ideal[edge]))
    require(worst <= 3, f"{course} kerb exceeded the reference by {worst:.2f} pixels")
    return worst


def check_geometry(course,out):
    check_kerb_motion(course)
    reference_error = check_reference(course)
    from strokes import ATLAS, SHAPE_BASE
    glyphs=(out/"glyphs.bin").read_bytes()
    table=(out/"shapes.bin").read_bytes()
    pairs={};seen=set()
    for q in range(256):
        _,points=bands(q,course)
        for a,b in zip(points,points[1:]):
            pairs[a[4],b[4]]=True
    pages=sorted({(2,2),*pairs})
    def word(data,index):return int.from_bytes(data[index:index+2],"little")
    for q in range(256):
        first,points=bands(q,course)
        old_first,previous=bands((q-1)%256,course)
        require(abs(first-old_first)<=3,f"{course} crest popped at {q}")
        for lane in range(8,249):
            for row,(a,b) in enumerate(zip(points,points[1:]),first//8):
                # Shared endpoints encompass every visible scanline. Linear
                # interpolation cannot overshoot either endpoint between bands.
                for point,bandrow in ((a,row),(b,row+1)):
                    if bandrow>=old_first//8:
                        old=previous[bandrow-old_first//8]
                        now=projected(point,lane);before=projected(old,lane)
                        require(all(abs(i-j)<=2 for i,j in zip(now[:3],before[:3])),
                                f"{course} uncommanded move beyond four pixels at {q}, band {bandrow}, lane {lane}")
                for start,end,w,v,style in ribbons(a,b,lane):
                    if max(start,end)*2+max(w,v)<=128 or min(start,end)*2>=384:continue
                    key=(end-start,w,v,start%4)
                    if key in seen:continue
                    seen.add(key)
                    dx,w,v,p=key
                    pos=word(table,2*pages.index((w,v)))-SHAPE_BASE+(dx+32)*8+2*p
                    entry=word(table,pos)-SHAPE_BASE
                    offset=-(table[entry]>>4)
                    count=table[entry]&15;result=[0]*8
                    for col in range(count):
                        ptr=word(table,entry+1+2*col)
                        if not ptr:continue
                        require(ptr&7==style,"wrong paint palette")
                        glyph=(ptr&~7)-ATLAS
                        for y,bits in enumerate(glyphs[glyph:glyph+8]):
                            result[y] |= (int(f"{bits:08b}"[::-1],2)<<(8*col))
                    for y,line in enumerate(result):
                        lo=2*p+(2*dx*y+4)//8-8*offset
                        hi=2*p+w+((2*dx+v-w)*y+4)//8-8*offset
                        require(hi>lo and line==((1<<(hi-lo))-1)<<lo,
                                f"{course} split kerb or lane dash in {key} on line {y}")
    return f"256 poses x 241 steering positions, {len(seen)} lossless paint shapes, max reference error {reference_error:.2f} px"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator",type=Path)
    parser.add_argument("--model",choices=("128k","P2","P2A41"),action="append")
    parser.add_argument("--course",choices=COURSES)
    args=parser.parse_args()
    emu=executable(args.emulator,"ZESARUX","zesarux","Dropbox/ZX_Coding/ZEsarUX_win-10.3/zesarux.exe")
    for course in ([args.course] if args.course else COURSES):
        out=BUILD if course=="coast" else BUILD/course
        image=out/f"{course}-run.sna";s=symbols_for(out)
        print(course,check_geometry(course,out),flush=True)
        def check(model):
            with tempfile.TemporaryDirectory(prefix=f"racer-{model}-") as directory:
                folder=Path(directory)
                print(course,model,check_timing(emu,model,image,s),flush=True)
                if course == "ridge" and model == "P2A41":
                    # A large change at the entry to this bend uses the in-raster
                    # bitmap writer and exposes a late +2A calibration slot.
                    peak = fixture(folder,"burst",image,s,pose=239,lane=128,displayLane=128,gear=4,travel=13)
                    steering = folder/"burst-keys.txt"
                    steering.write_bytes(b"p oo pp oo pp " * 12)
                    print(course,model,"burst",check_timing(emu,model,peak,s,20,steering),flush=True)
                result,_,_=check_drive(emu,model,image,s,course,folder,240)
                print(course,model,result,flush=True)
                check_controls(emu,model,image,s,folder)
                result,_,_=check_drive(emu,model,image,s,course,folder,240,tape=True,full_lap=True)
                print(course,model,"retail TAP",result,flush=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(check,args.model or ("128k","P2","P2A41")))


if __name__=="__main__":
    main()
