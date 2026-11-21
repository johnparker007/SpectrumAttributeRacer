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
from course import (DASH, GRASS, HORIZON, KERB, MATERIALS, PAINT, PHASES, STEPS, VOID,
                    bitmap_offset, centre, halfwidth, riders, road, scenery, screen,
                    shoulder_width, tiles)

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


def trace(emulator, image, model, seconds, symbols, points, spool=None):
    opts = ["--enable-breakpoints"]
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


def raster(emulator, model, symbols):
    points = [("irq","TSTATESP"),("blitDone","TSTATES"),("latch","TSTATES*256+A"),
              ("afterLatch","TSTATES"),("rasterDone","TSTATES"),("frameWait","TSTATES")]
    events = trace(emulator,BUILD/"coast-run.sna",model,3,symbols,points)
    groups = []
    for key,value in events:
        if key=="irq":
            groups.append([])
        if groups:
            groups[-1].append((key,value))
    require(len(groups)>=5, f"{model} fewer than four full raster frames")
    first = []
    for group,following in zip(groups,groups[1:]):
        expected = ["irq","blitDone"] + ["latch","afterLatch"]*(DASH-HORIZON) + ["rasterDone","frameWait"]
        require([k for k,_ in group]==expected, f"{model} lost a raster event")
        require(following[0][1]//FRAME == group[0][1]//FRAME+1, f"{model} missed INT")
        require(group[1][1] < 14360, f"{model} top blit ran into active display")
        writes = []
        for i in range(DASH-HORIZON):
            t,latch = divmod(group[2+2*i][1],256)
            require(group[3+2*i][1]-t==12 and latch in (0x17,0x1f), f"{model} contended or invalid OUT")
            writes.append(t+9)  # ZEsarUX 10.3 latches OUT (C),A three T before instruction end.
        require(all(t==writes[0]+i*LINE for i,t in enumerate(writes)), f"{model} line drift")
        require(28910 <= writes[0] <= 28940, f"{model} first OUT outside the chosen border slot")
        first.append(writes[0])
    return f"{len(first)} raster frames, first latch {min(first)}..{max(first)} T, 104 writes/frame at 228 T"


def fixture(folder, name, symbols, **changes):
    data = bytearray((BUILD/"coast-run.sna").read_bytes())
    for symbol, value in changes.items():
        addr = symbols[symbol]
        require(0x8000<=addr<0xc000, f"Invalid fixed-bank fixture address {symbol}")
        data[27+16384+addr-0x8000] = value
    path = folder/(name+".sna")
    path.write_bytes(data)
    return path


def gameplay(emulator,model,s,folder):
    # Seed top gear on the start line. The release input, motion and rendering
    # routines then run unmodified through left, right and lap wrap.
    fast = fixture(folder,"lap",s,gear=4,bikeCol=16)
    peek = lambda name: f"PEEK({s[name]:04X}H)"
    events = trace(emulator,fast,model,17,s,[
        ("irq","TSTATESP"),("frameWait","TSTATES"),
        ("advance.descriptor",peek("step")+"+256*"+peek("batches")),
        ("controls",peek("passes"))])
    starts = [v//FRAME for k,v in events if k=="irq"]
    steps = [v for k,v in events if k=="advance.descriptor"]
    waits = [v for k,v in events if k=="frameWait"][1:]
    require(all(b==a+1 for a,b in zip(starts,starts[1:])),f"{model} missed a lap frame")
    require(steps[:64]==list(range(1,64))+[0], f"{model} incomplete lap or overwritten tile queue ({len(steps)} steps)")
    require(any(k=="controls" and v==2 for k,v in events),f"{model} two clean passes were not counted")
    margin = FRAME-max(waits)
    require(margin>512,f"{model} bottom border overrun")

    crash = fixture(folder,"contact",s,step=30,travel=20,gear=4,bikeCol=8)
    values = trace(emulator,crash,model,2,s,[("controls",peek("gear")+"+256*"+peek("bump"))])
    require(any(v%256==1 and v//256>0 for _,v in values), f"{model} contact failed to reduce speed")
    spool = folder/"keys.txt"
    spool.write_bytes(b"pqoapqoa "*20)
    controls = trace(emulator,BUILD/"coast-run.sna",model,4,s,[
        ("advance",peek("gear")+"+256*"+peek("bikeCol")),
        ("controls.leanDone","HL")], spool)
    leans = {v-s["riderArt"] for k,v in controls if k=="controls.leanDone"}
    gears = {v%256 for k,v in controls if k=="advance"}
    positions = {v//256 for k,v in controls if k=="advance"}
    require(leans=={0,162,324} and len(gears)>=2 and len(positions)>1, f"{model} keyboard path {leans,gears,positions}")
    return f"lap and two passes, contact penalty, O/P/Q/A, {margin} T minimum lap headroom"


@lru_cache(maxsize=8192)
def pixels(attr, bits):
    level = 255 if attr & 64 else 192
    colours = [bytes(level if c & channel else 0 for channel in (1,4,2))
               for c in ((attr>>3)&7, attr&7)]  # ZEsarUX BGR24
    return b"".join(colours[bool(bits & (128>>bit))] for bit in range(8))


def verify_road_edges():
    pic = scenery()
    transitions = 0
    for step in range(STEPS):
        road(pic, step)
        scene = tiles(pic)
        # Foreground objects can legitimately take a colour away from the
        # paint in a distant 8x8 cell. The grass/shoulder boundary must be
        # correct even in a pose that draws a sign nearby.
        objects = {(y//8, x//8) for y in range(HORIZON, DASH)
                   for x, material in enumerate(pic[y]) if material not in (VOID, GRASS, KERB, PAINT)}
        for y in range(HORIZON, DASH):
            d = y - HORIZON
            mid, w = centre(step, d), halfwidth(d)
            kerb = 2 * (1 + d//18)
            shoulder = shoulder_width(d)
            for inner, direction in ((round(mid-w), -1), (round(mid+w), 1)):
                grass_x = inner + direction*(kerb + shoulder + 1)
                if 0 <= grass_x < 256 and 0 <= grass_x-direction < 256:
                    transitions += 1
                for offset in range(kerb + shoulder + 2):
                    x = inner + direction*offset
                    if not 0 <= x < 256:
                        continue
                    cell = (y//8, x//8)
                    if cell in objects and offset < kerb + shoulder:
                        continue
                    expected = VOID
                    if 0 < offset <= kerb:
                        expected = KERB
                    elif offset == kerb + shoulder + 1:
                        expected = GRASS
                    tile = scene[cell[0]*32 + cell[1]]
                    shift = 0 if tile[2+y%8] & (128 >> (x%8)) else 3
                    for bank, attr in enumerate(tile[:2]):
                        colour = (attr >> shift) & 7
                        if colour and attr & 64:
                            colour += 8
                        require(colour == MATERIALS[expected][bank],
                                f"Road edge mismatch at step {step}, ({x}, {y}), bank {bank}")
    return f"{transitions} visible grass boundaries and doubled kerbs checked across {STEPS} poses on both screens"


def initial_hud_and_rider(scr, step):
    # Idle keyboard, second gear. In the first nine poses the right-hand bend
    # displaces the rider a cell on steps 4, 6 and 8.
    col = 14 - len(range(4,step+1,2))
    sprite = riders()[162:324]
    for tile in range(9):
        row, x = divmod(tile,3)
        scr[6144+(18+row)*32+col+x] = sprite[tile*18]
        for dy in range(8):
            offset = bitmap_offset(144+8*row+dy,col+x)
            mask,ink = sprite[tile*18+2+dy*2:tile*18+4+dy*2]
            scr[offset] = (scr[offset] & mask) | ink
    scr[6144+22*32+16:6144+22*32+20] = bytes((0x46,0x46,1,1))
    for x in (25,26):
        scr[6144+22*32+x] = 0x47
        for dy,bits in enumerate((0,56,40,40,40,40,56,0)):
            scr[bitmap_offset(176+dy,x)] = bits


def reference():
    result = {}
    pic = scenery()
    for step in range(9):
        road(pic,step)
        scene = tiles(pic)
        pair = []
        for bank in (0,1):
            scr = screen(scene,bank)
            initial_hud_and_rider(scr,step)
            pair.append([b"".join(pixels(scr[6144+y//8*32+x],scr[bitmap_offset(y,x)])
                                  for x in range(32)) for y in range(192)])
        for phase in range(PHASES):
            rows = list(pair[0])
            for y in range(HORIZON,DASH):
                if (4000//(y-HORIZON+5)+phase)%32>=16:
                    rows[y] = pair[1][y]
            result[sha256(b"".join(rows)).digest()] = step,phase
    return result


def video(emulator,model,folder,expected):
    raw = folder/"capture.raw"
    log = run(emulator,BUILD/"coast-run.tap",model,7,
              ["--vofilefps","50","--frameskip","0","--disable-autoframeskip","--vofile",raw])
    require("352 X 304, bgr24" in log,f"{model} unknown realvideo format")
    seen = set()
    previous = None
    with raw.open("rb") as frames:
        while frame := frames.read(3*WIDTH*HEIGHT):
            require(len(frame)==3*WIDTH*HEIGHT,f"{model} truncated video")
            rows = [frame[3*((y+56)*WIDTH+48):3*((y+56)*WIDTH+304)] for y in range(192)]
            match = expected.get(sha256(b"".join(rows)).digest())
            if match:
                seen.add(match)
                if previous and previous[0]==match[0]:
                    require(match[1]==(previous[1]+2)%PHASES, f"{model} unexpected stripe motion")
            previous = match
    steps,phases = {s for s,_ in seen},{p for _,p in seen}
    require(len(steps)>=4 and len(phases)>=8, f"{model} release tape pixel matches {sorted(seen)}")
    return f"retail tape pixels matched {len(steps)} road poses and {len(phases)} raster phases"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator",type=Path)
    parser.add_argument("--model",choices=("128k","P2","P2A41"),action="append")
    args = parser.parse_args()
    emu = executable(args.emulator,"ZESARUX","zesarux","Dropbox/ZX_Coding/ZEsarUX_win-10.3/zesarux.exe")
    symbols = {k:int(v,16) for k,v in re.findall(r"^(\S+): EQU 0x([0-9A-Fa-f]+)$",
                                                  (BUILD/"racer.sym").read_text(),re.M)}
    symbols["afterLatch"] = symbols["latch"]+2
    print(verify_road_edges(), flush=True)
    expected = reference()
    def check(model):
        with tempfile.TemporaryDirectory(prefix="coast-"+model+"-") as scratch:
            folder = Path(scratch)
            for result in (raster(emu,model,symbols),gameplay(emu,model,symbols,folder),
                           video(emu,model,folder,expected)):
                print(f"{model}: {result}",flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(check,args.model or ("128k","P2","P2A41")))


if __name__ == "__main__":
    main()
