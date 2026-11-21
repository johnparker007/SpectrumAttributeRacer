"""Exercise the release TAP, keyboard, frame deadlines and ULA output in headless ZEsarUX."""

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import tempfile

from build import BUILD, executable
from course import (ASPHALT, KERB, KERB_ATTRS, MATERIALS, PAINT, PHASES, TRAVEL_PER_STEP,
                    artwork, bitmap_offset, riders, road, scenery, screen, tiles, visible,
                    EARLY_TILES, EXTRA_TILES, FONT, MAP_WIDTH, MARGIN, POSES, SUBSTEPS)
from kerbs import FIRST_BAND, geometry, overlay_kerbs
from route import COURSES, DASH, STEPS, TOP, TYRES, drift, projection

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
        opts.extend(["--vofilefps","25","--frameskip","0","--disable-autoframeskip","--vofile",capture])
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


def raster(emulator, model, symbols, image):
    points = [("irq","TSTATESP"),("blitDone","TSTATES"),("latch","TSTATES*256+A"),
              ("afterLatch","TSTATES"),("rasterDone","TSTATES"),("frameWait","TSTATES")]
    events = trace(emulator,image,model,3,symbols,points)
    groups = []
    for key,value in events:
        if key=="irq":
            groups.append([])
        if groups:
            groups[-1].append((key,value))
    groups = [g for g in groups if any(k=="latch" for k,_ in g)]
    require(len(groups)>=5, f"{model} fewer than four full raster frames")
    first = []
    for group,following in zip(groups,groups[1:]):
        expected = ["irq","blitDone"] + ["latch","afterLatch"]*(DASH-TOP) + ["rasterDone","frameWait"]
        require([k for k,_ in group]==expected, f"{model} lost a raster event")
        require(following[0][1]//FRAME == group[0][1]//FRAME+1, f"{model} missed INT")
        require(group[1][1] < 23400, f"{model} top blit ran into road raster")
        writes = []
        for i in range(DASH-TOP):
            t,latch = divmod(group[2+2*i][1],256)
            require(group[3+2*i][1]-t==12 and latch in (0x17,0x1f), f"{model} contended or invalid OUT")
            writes.append(t+9)  # ZEsarUX 10.3 latches OUT (C),A three T before instruction end.
        require(all(t==writes[0]+i*LINE for i,t in enumerate(writes)), f"{model} line drift")
        require(23415 <= writes[0] <= 23467, f"{model} first OUT outside the chosen border slot: {writes[0]}")
        first.append(writes[0])
    return f"{len(first)} raster frames, first latch {min(first)}..{max(first)} T, {DASH-TOP} writes/frame at 228 T"


def fixture(folder, name, image, symbols, **changes):
    data = bytearray(image.read_bytes())
    for symbol, value in changes.items():
        addr = symbols[symbol]
        require(0x8000<=addr<0xc000, f"Invalid fixed-bank fixture address {symbol}")
        data[27+16384+addr-0x8000] = value
    path = folder/(name+".sna")
    path.write_bytes(data)
    return path


def gameplay(emulator,model,s,folder,image,expected):
    fast = fixture(folder,"lap",image,s,gear=4,lane=140)
    peek = lambda name: f"PEEK({s[name]:04X}H)"
    capture = folder/"lap.raw"
    events = trace(emulator,fast,model,44,s,[
        ("irq","TSTATESP"),("frameWait","TSTATES"),("advance.descriptor","A"),
        ("controls",peek("passes"))],capture=capture)
    starts = [v//FRAME for k,v in events if k=="irq"][2:]
    poses = [v for k,v in events if k=="advance.descriptor"]
    waits = [v for k,v in events if k=="frameWait"][2:]
    require(all(b==a+1 for a,b in zip(starts,starts[1:])),f"{model} missed a lap interrupt")
    require(poses[:POSES]==list(range(1,POSES))+[0],f"{model} incomplete lap ({len(poses)} poses)")
    require(any(k=="controls" and v==2 for k,v in events),f"{model} two clean passes were not counted")
    margin = FRAME-max(waits)
    require(margin>128,f"{model} bottom border overrun, {margin} T")
    seen,matched,active = set(),0,False
    for rows in paper_frames(capture,192):
        hit = expected.get(sha256(b"".join(rows)).digest())
        if hit is not None:
            active = True
            seen.add(hit)
            matched += 1
        elif active and len(seen)<POSES:
            raise ValueError(f"{model} unexpected in-motion pixels after {matched} matched frames, poses {len(seen)}")
        if len(seen)==POSES:
            break
    require(len(seen)==POSES,f"{model} real-video lap matched {len(seen)} poses")
    crash = fixture(folder,"contact",image,s,pose=123,travel=TRAVEL_PER_STEP//SUBSTEPS-4,gear=4,lane=78)
    values = trace(emulator,crash,model,1,s,[("controls",peek("gear")+"+256*"+peek("bump"))])
    require(any(v%256==1 and v//256>0 for _,v in values),f"{model} contact penalty")
    spool = folder/"keys.txt"
    spool.write_bytes(b"pqoapqoa "*20)
    keys = trace(emulator,image,model,4,s,[("advance",peek("gear")+"+256*"+peek("lane")),
                                        ("controls.leanDone","HL")],spool)
    leans={v-s["riderArt"] for k,v in keys if k=="controls.leanDone"}
    gears={v%256 for k,v in keys if k=="advance"}
    lanes={v//256 for k,v in keys if k=="advance"}
    require(leans=={0,162,324} and len(gears)>=2 and max(lanes)-min(lanes)>4,f"{model} keyboard path")
    return f"{matched} in-motion frames across all {POSES} poses, two passes, contact, O/P/Q/A, {margin} T headroom"


@lru_cache(maxsize=8192)
def pixels(attr, bits):
    level = 255 if attr & 64 else 192
    colours = [bytes(level if c & channel else 0 for channel in (1,4,2))
               for c in ((attr>>3)&7, attr&7)]  # ZEsarUX BGR24
    return b"".join(colours[bool(bits & (128>>bit))] for bit in range(8))


def verify_joins(course, art):
    # Measure the red stripe actually encoded in the bank-7 bitmap against
    # the continuous road, independently of the game's stamp lookup.
    ids,_,scales,atlases,stamps = art
    red = [[bytes(((t[1] >> (0 if bits & (128>>x) else 3)) & 7)==2 for x in range(8))
            for bits in t[2:]] for t in atlases[1]]
    joins = steps = absent = 0
    for pose in range(POSES):
        bands = geometry(pose,course)
        rows = projection(pose/SUBSTEPS,course)[1]
        for lane in (80,104,128,140,176):
            view = window(ids,scales,pose,1,lane,course,stamps)
            for k in range(1,8):
                if not (bands[k-1].use_stamp and bands[k].use_stamp):
                    continue
                samples = []
                for i,dy in ((k-1,7),(k,0)):
                    r = rows[64+i*8+dy]
                    mask = b"".join(red[t][dy] for t in view[32*i:32*i+32])
                    runs = [(m.start()+m.end()-1)/2 for m in re.finditer(b"\x01+",mask)
                            if m.start() and m.end()<256 and m.end()-m.start()>=r.kerb/2]
                    samples.append((r,runs))
                for side in (-1,1):
                    errors = []
                    for r,runs in samples:
                        centre = r.x+side*(r.halfwidth+(r.kerb+1)/2)-(lane-128)*TYRES/r.z
                        if not 12<centre<244:
                            break
                        errors.append(min((x-centre for x in runs),key=abs,default=256))
                    if len(errors)<2:
                        continue
                    joins += 1
                    if max(map(abs,errors))>12:
                        absent += 1
                    elif abs(errors[1]-errors[0])>4:
                        steps += 1
    require(joins>10000 and (steps+absent)/joins<.09,
            f"{course} foreground joins: {steps} excessive steps, {absent} obscured of {joins}")
    return f"{steps} steps over 4 px and {absent} obscured in {joins} foreground joins"


def verify_terrain(course, art):
    ids,_,_,atlases,_ = art
    kerb_rows = missing_rows = 0
    pic = scenery(course)
    crests, centres, depth_jumps = [], [], []
    simple_cells = crowded_cells = hidden_sections = 0
    terrain = {KERB, ASPHALT, PAINT}
    for step in range(STEPS):
        rival_x, rival_y = road(pic, step, course)
        samples, rows = projection(step, course)
        surface = [r for r in rows if r]
        crests.append(surface[0].y)
        centres.extend(r.x for r in surface)
        require(rows[-1].z == TYRES and rows[-1].x == 128, f"Road moved under tyres at {step}")
        if step in (31,63):
            require(rival_y == DASH-1 and rival_x == (74 if step==31 else 182), "Pass gate drift")
        require(rows[-1].kerb==18, "Expected an 18-pixel kerb at the tyres")
        for r in surface:
            require(r.kerb==round((4.5+39.5/r.z)/2), f"Kerb width at {step}, {r.y}")
        for a,b in zip(surface,surface[1:]):
            require(a.y+1 == b.y and a.z>b.z, f"Folded or missing road line at {step}")
            depth_jumps.append(a.z-b.z)
        hidden_sections += sum(TOP <= round(r.y) < DASH and not visible(rows, round(r.y), r.z)
                               for r in samples[::32])
        scene = tiles(pic)
        for y in range(TOP, DASH, 8):
            for col in range(32):
                cell = b"".join(line[8*col:8*col+8] for line in pic[y:y+8])
                materials = set(cell)
                if not materials <= terrain:
                    continue
                tile = scene[y//8*32+col]
                require(tile[0]&64, f"Missing BRIGHT on the bright terrain at {step}, {col}, {y}")
                require(not tile[1]&64, f"Bright dim-band tile at {step}, {col}, {y}")
                if len(materials)>2:
                    crowded_cells += 1  # A depth break can put a third material in a ULA cell.
                    continue
                simple_cells += 1
                if tile[:2]==KERB_ATTRS and (y-TOP)//8<FIRST_BAND:
                    band = (y-TOP)//8
                    tile_id = ids[step*SUBSTEPS][band*MAP_WIDTH+MARGIN//8+col]
                    stored = atlases[band//8][tile_id]
                    for source,row in zip(tile[2:],stored[2:]):
                        if source:
                            kerb_rows += 1
                            missing_rows += row==0
                for i,m in enumerate(cell):
                    shift = 0 if tile[2+i//8] & (128>>(i%8)) else 3
                    for bank,attr in enumerate(tile[:2]):
                        actual = (attr>>shift)&7
                        if attr&64:
                            actual += 8
                        require(actual==MATERIALS[m][bank], f"Edge colour at {step}, {col}, {y}, bank {bank}")
    require(kerb_rows and missing_rows < kerb_rows*.06,
            f"Tile compression dropped {missing_rows}/{kerb_rows} occupied kerb rows")
    require(crowded_cells*40 < simple_cells+crowded_cells, "Over 2.5% of terrain cells need three colours")
    require(max(crests)-min(crests)>=18 and max(depth_jumps)>8 and hidden_sections, "Missing hill occlusion")
    require(min(centres)<50 and max(centres)>200, "Insufficient left/right bend range")
    heights=[next(r.y for r in projection(q/SUBSTEPS,course)[1] if r) for q in range(POSES)]
    largest=max(abs(y-heights[i-1]) for i,y in enumerate(heights))
    require(largest<=3, f"{course} crest jumped {largest} scanlines in a quarter-step")
    return (f"{POSES} projected crests at lines {min(heights)}..{max(heights)}, largest step {largest} px, "
            f"{simple_cells} one/two-material cells checked at the {STEPS} whole stations")



def overlay(scr, bank, gear, passes):
    col = 14
    sprite = riders()[162:324]
    for tile in range(9):
        row, x = divmod(tile,3)
        address = 6144+(18+row)*32+col+x
        terrain = scr[address]
        solid = (terrain & 7) == ((terrain >> 3) & 7)
        if bank == 0:
            scr[address] = sprite[tile*18]
        elif solid:
            scr[address] = (terrain & 0x38) | sprite[tile*18+1]
        for dy in range(8):
            offset = bitmap_offset(144+8*row+dy,col+x)
            mask,ink = sprite[tile*18+2+dy*2:tile*18+4+dy*2]
            scr[offset] = ink if bank == 1 and solid else (scr[offset] & mask) | ink
    scr[6144+22*32+16:6144+22*32+20] = bytes([0x46]*gear+[1]*(4-gear))
    for x,digit in zip((25,26),f"{passes%100:02}"):
        scr[6144+22*32+x] = 0x47
        for dy,bits in enumerate(int(row,8)<<3 for row in "0"+FONT[digit]+"0"):
            scr[bitmap_offset(176+dy,x)] = bits


def window(ids,scales,pose,half,lane,course,stamps):
    result = bytearray()
    for row in range(half*8,half*8+8):
        offset = round(((lane & 252)-128)*scales[pose][row]/120)
        start = row*MAP_WIDTH + max(0,min(MAP_WIDTH-32,MARGIN//8+offset))
        result.extend(ids[pose][start:start+32])
    return overlay_kerbs(result,pose,lane,course,stamps) if half else result


def frame_hash(backdrop,atlases,shown,depths,phase,gear,passes):
    scene = backdrop.copy()
    scene[TOP*4:DASH*4] = [atlases[i//256][t] for i,t in enumerate(shown[0]+shown[1])]
    pair = [screen(scene,n) for n in (0,1)]
    for bank,scr in enumerate(pair):
        overlay(scr,bank,gear,passes)
    rows = []
    for y in range(192):
        d = depths[y-TOP] if TOP<=y<DASH else 64
        scr = pair[int(d!=64 and (d+phase)%32>=16)]
        attr = 6144+(y//8)*32
        bitmap = bitmap_offset(y,0)
        rows.append(b"".join(pixels(a,b) for a,b in zip(scr[attr:attr+32],scr[bitmap:bitmap+32])))
    return sha256(b"".join(rows)).digest()


def reference(course,art,gear,lane,frames):
    ids,depths,scales,atlases,stamps = art
    result = {}
    backdrop = tiles(scenery(course))
    shown = [window(ids,scales,0,h,128,course,stamps) for h in (0,1)]
    target = [a.copy() for a in shown]
    depth = bytearray(depths[0])
    resume = [0,0]
    pending = set()
    cached_lower = (0,128)
    half = pose = travel = phase = passes = 0
    for _ in range(frames):
        result[frame_hash(backdrop,atlases,shown,depth,phase,gear,passes)] = (pose,phase)
        order = [(resume[half]+i)%256 for i in range(256)]
        dirty = [i for i in order if shown[half][i]!=target[half][i]]
        if len(dirty)>=EARLY_TILES:
            resume[half]=(dirty[EARLY_TILES-1]+1)%256
        next_half = 1-half
        phase=(phase+gear)%32
        travel+=gear
        if travel>=TRAVEL_PER_STEP//SUBSTEPS:
            travel-=TRAVEL_PER_STEP//SUBSTEPS
            pose=(pose+1)%POSES
            lane=max(8,min(248,lane+drift(pose//4,course)*(1 if pose%2 else 2)))
            if pose%128==124:
                passes+=1  # test rides use clear lines past both rivals
            pending={0,1}
        if next_half in pending:
            cap=EARLY_TILES
            pending.remove(next_half)
            start=64*next_half
            depth[start:start+64]=depths[pose][start:start+64]
        else:
            cap=EARLY_TILES+EXTRA_TILES
        if next_half:
            state = (pose,lane & 252)
            if state!=cached_lower:
                cap=EARLY_TILES
            cached_lower=state
        for i in dirty[:cap]:
            shown[half][i]=target[half][i]
        half=next_half
        target[half]=window(ids,scales,pose,half,lane,course,stamps)
    return result


def paper_frames(raw,height):
    with raw.open("rb") as frames:
        while frame := frames.read(3*WIDTH*HEIGHT):
            require(len(frame)==3*WIDTH*HEIGHT,"Truncated real-video frame")
            yield [frame[3*((y+56)*WIDTH+48):3*((y+56)*WIDTH+304)] for y in range(height)]


def steering(emulator,model,s,folder,image,art,course):
    ids,depths,scales,atlases,stamps = art
    backdrop=tiles(scenery(course))
    near,far=[],[]
    for lane in (80,176):
        # Park forward travel to isolate camera parallax on the same bend.
        parked=fixture(folder,f"lane-{lane}",image,s,gear=0,lane=lane)
        raw=folder/"steering.raw"
        run(emulator,parked,model,2,["--vofilefps","25","--frameskip","0","--disable-autoframeskip","--vofile",raw])
        view=[window(ids,scales,0,h,lane,course,stamps) for h in (0,1)]
        expected=frame_hash(backdrop,atlases,view,depths[0],0,0,0)
        frames=list(deque(paper_frames(raw,192),maxlen=3))
        require(len(frames)==3 and all(sha256(b"".join(rows)).digest()==expected for rows in frames),
                f"{model} camera or anchored rider pixel mismatch at lane {lane}")
        line = frames[-1][135]
        r = projection(0,course)[1][135-TOP]
        centre = r.x-r.halfwidth-r.kerb/2-(lane-128)*TYRES/r.z
        # Track the middle of the painted left kerb in real video. Lane dashes
        # and roadside objects use a separate, coarser steering offset.
        mask = bytes(line[x:x+3] in (b"\xff"*3,b"\0\0\xc0") for x in range(0,len(line),3))
        runs = [(m.start()+m.end()-1)/2 for m in re.finditer(b"\x01{4,}",mask)]
        require(runs,f"{model} missing foreground kerb at lane {lane}")
        near.append(min(runs,key=lambda x:abs(x-centre)))
        far.append(frames[-1][87])
    def displacement(lines):
        shifts = [x for x in range(0,113) if lines[0][3*x:]==lines[1][:3*(256-x)]]
        require(len(shifts)==1,f"{model} ambiguous road displacement: {shifts}")
        return shifts[0]
    foreground,distance = near[0]-near[1],displacement(far)
    require(foreground>=40 and 0<=distance<foreground,f"{model} parallax {foreground}, {distance}")
    return f"steering moved the road {foreground} px nearby and {distance} px in the distance"


def video(emulator,model,folder,expected,tape):
    raw = folder/"capture.raw"
    log = run(emulator,tape,model,9,
              ["--vofilefps","50","--frameskip","0","--disable-autoframeskip","--vofile",raw])
    require("352 X 304, bgr24" in log,f"{model} unknown realvideo format")
    seen = set()
    # Match entire real-video rows. Bright rows may include white lane dashes.
    red, blue = b"\x00\x00\xc0", b"\xc0\x00\x00"
    dim_row = re.compile(b"".join(b"(?:" + colour + b")+" for colour in (blue, red, blue, red, blue)))
    black, white = bytes(3), bytes([255])*3
    black_run, white_run = b"(?:"+black+b")+", b"(?:"+white+b")+"
    bright_row = re.compile(black_run+white_run+black_run+b"(?:"+white_run+black_run+b"){1,3}")
    dim_lines, bright_lines = set(), set()
    previous = None
    for rows in paper_frames(raw,192):
        match = expected.get(sha256(b"".join(rows)).digest())
        if match is not None:
            seen.add(match)
            for y in range(TOP, DASH):
                if y not in dim_lines and dim_row.fullmatch(rows[y]):
                    dim_lines.add(y)
                if y not in bright_lines and bright_row.fullmatch(rows[y]):
                    bright_lines.add(y)
            if previous and previous[0]==match[0]:
                require(match[1]==(previous[1]+2)%PHASES, f"{model} unexpected stripe motion")
        previous = match
    steps,phases = {s for s,_ in seen},{p for _,p in seen}
    require(len(steps)>=4 and len(phases)>=8, f"{model} release tape pixel matches {sorted(seen)}")
    require(min(len(dim_lines),len(bright_lines))>=40,
            f"{model} complete kerb runs on {len(dim_lines)} dim and {len(bright_lines)} bright scanlines")
    return (f"retail tape matched {len(steps)} road poses, {len(phases)} raster phases and both kerbs on "
            f"{len(dim_lines)} blue/red and {len(bright_lines)} black/white scanlines")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator",type=Path)
    parser.add_argument("--model",choices=("128k","P2","P2A41"),action="append")
    parser.add_argument("--course",choices=COURSES)
    args = parser.parse_args()
    emu = executable(args.emulator,"ZESARUX","zesarux","Dropbox/ZX_Coding/ZEsarUX_win-10.3/zesarux.exe")
    for course in ([args.course] if args.course else COURSES):
        out = BUILD if course=="coast" else BUILD/course
        image = out/f"{course}-run.sna"
        symbols = {k:int(v,16) for k,v in re.findall(r"^(\S+): EQU 0x([0-9A-Fa-f]+)$",
                                                      (out/"racer.sym").read_text(), re.M)}
        symbols["afterLatch"] = symbols["latch"]+2
        art = artwork(course)
        print(f"{course}: {verify_terrain(course,art)}; {verify_joins(course,art)}",flush=True)
        expected = reference(course,art,2,128,128)
        terrain_frames = {key:pose for key,(pose,_) in reference(
            course,art,4,140,POSES*TRAVEL_PER_STEP//SUBSTEPS//4+4).items()}

        def check(model):
            with tempfile.TemporaryDirectory(prefix=f"{course}-{model}-") as scratch:
                folder = Path(scratch)
                def report(result):
                    print(f"{course} {model}: {result}",flush=True)
                report(raster(emu,model,symbols,image))
                report(gameplay(emu,model,symbols,folder,image,terrain_frames))
                report(steering(emu,model,symbols,folder,image,art,course))
                report(video(emu,model,folder,expected,image.with_suffix(".tap")))
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(check,args.model or ("128k","P2","P2A41")))


if __name__ == "__main__":
    main()
