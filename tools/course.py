"""Build the skyline, dashboard, rider artwork and projected roadside objects."""

from collections import Counter
from functools import lru_cache
from math import cos, sin
from struct import pack

from kerbs import FIRST, LINES, camera_scale, nearest, surface
from route import DASH, STEPS, TOP, TYRES, at_distance, projection

WIDTH, HEIGHT = 256, 192
PHASES = 32
TRAVEL_PER_STEP = 56
SUBSTEPS = 4
POSES = STEPS * SUBSTEPS
# The static artwork uses the Spectrum's eight normal and eight bright colours.
STATIC = 8
PAGES = (1, 3, 4)
PAGE_START = {page: 0xc000 for page in PAGES}

# Compact lettering for the instrument fascia.
FONT = dict(zip("AEGPRS0123456789",
    "255755 744647 345553 655644 655655 346127 755557 262227 616447 616116 557111 746116 346552 711222 257552 255316".split()))
TITLE = {letter: bytes.fromhex(rows) for letter, rows in {
    "C": "0f 10 10 10 10 10 0f", "O": "0e 11 11 11 11 11 0e",
    "A": "0e 11 11 1f 11 11 11", "S": "0f 10 10 0e 01 01 1e",
    "T": "1f 04 04 04 04 04 04", "R": "1e 11 11 1e 14 12 11",
    "I": "1f 04 04 04 04 04 1f", "D": "1e 11 11 11 11 11 1e",
    "G": "0f 10 10 17 11 11 0f", "E": "1f 10 10 1e 10 10 1f",
    "U": "11 11 11 11 11 11 0e", "N": "11 19 19 15 13 13 11",
}.items()}


def text_at(pic, x, y, text, colour, scale=1):
    for letter in text:
        for dy, row in enumerate(FONT.get(letter, "")):
            for dx in range(3):
                if int(row, 8) & (4 >> dx):
                    for line in pic[y + dy*scale:y + (dy+1)*scale]:
                        line[x + dx*scale:x + (dx+1)*scale] = bytes([colour]) * scale
        x += 4 * scale


def span(row, left, right, material):
    left, right = max(0, left), min(len(row), right)
    if right > left:
        row[left:right] = bytes([material]) * (right - left)


def scenery(course="coast"):
    pic = [bytearray(WIDTH) for _ in range(HEIGHT)]
    for y in range(64):
        for x in range(WIDTH):
            # Sunset over two silhouettes, with a coastal radio mast on the ridge.
            colour = 0
            if (x-174)**2 + (y-34)**2 <= 24**2 and (y < 32 or y % 5 < 3):
                colour = 14 if y < 24 else 10 if y < 40 else 11
            ridge = 51 + 5*sin(x/14) + 4*cos(x/22) - 5*abs(sin(x/8))
            if course == "ridge":
                ridge = 53 - max(0, 25-abs(x-75)*.72, 33-abs(x-107)*.85, 23-abs(x-206)*.64)
            if y >= ridge:
                colour = 3
            if course == "ridge" and ridge < 37 and ridge <= y < ridge + 3:
                colour = 7
            if y >= 56 + 4*sin(x/25) - 2*abs(sin(x/5)):
                colour = 1
            if y == 63:
                colour = 13
            pic[y][x] = STATIC + colour
    # The sea and its distant headland appear below the mountains on a descent.
    for y in range(64, DASH):
        for x in range(WIDTH):
            headland = y < 68 + 6*cos(x/72) + 2*sin(x/17)
            pic[y][x] = STATIC + (1 if headland else (4 if course == "ridge" else 5))
    for x, y in [(12, 17), (37, 9), (49, 31), (68, 15), (93, 7),
                 (117, 27), (131, 12), (212, 11), (237, 25), (225, 36)]:
        pic[y][x] = STATIC + 7
    for y in range(30, 56):
        w = 1 + (y - 30)//8
        pic[y][38-w] = pic[y][38+w] = STATIC + 5
        if y % 6 == 0:
            span(pic[y], 38-w, 39+w, STATIC + 5)
    pic[29][38] = STATIC + 10
    for y in (169, 189):
        span(pic[y], 104, 248, STATIC + 1)
    x = 7
    for letter in ("COAST RUN" if course == "coast" else "RIDGE RUN"):
        if letter == " ":
            x += 3
            continue
        for y, bits in enumerate(TITLE[letter]):
            for col in range(5):
                if bits & (16 >> col):
                    left = x + 2*col + (6-y)//3
                    for dy in (0,1):
                        span(pic[173+2*y+dy],left,left+2,STATIC+(13 if x<60 else 15))
        x += 11
    text_at(pic, 106, 178, "GEAR", STATIC+13)
    text_at(pic, 172, 178, "PASS", STATIC+13)
    for y in range(177,183):
        for x in range(128,160):
            if 1 <= (x + (y-177)//2) % 8 <= 5:
                pic[y][x] = STATIC+14
    return pic


def visible(rows, y, z):
    return TOP <= y < DASH and (rows[y-TOP] is None or rows[y-TOP].z >= z-.04)


def bitmap_offset(y, col):
    return ((y & 0xc0) << 5) + ((y & 7) << 8) + ((y & 0x38) << 2) + col


@lru_cache(maxsize=32768)
def encode(cell):
    count = Counter(cell)
    ranked = sorted(count, key=count.get, reverse=True)
    paper, ink = ranked[0], ranked[min(1, len(ranked)-1)]
    if ink == 0:
        paper, ink = ink, paper
    # Zero-filled sky and dashboard cells use black. The static scene assigns
    # the same palette to both screens.
    paper_colour = max(0, paper-STATIC)
    ink_colour = max(0, ink-STATIC)
    attr = ((paper_colour & 7) << 3) | (ink_colour & 7)
    if max(ink_colour, paper_colour) >= 8:
        attr |= 64
    bits = bytes(sum(128 >> x for x in range(8) if cell[8*y+x] == ink)
                 for y in range(8)) if paper != ink else bytes(8)
    return bytes((attr, attr)) + bits


def tiles(pic):
    return [encode(b"".join(row[x:x+8] for row in pic[y:y+8]))
            for y in range(0,HEIGHT,8) for x in range(0,WIDTH,8)]


def screen(scene, bank):
    out = bytearray(6912)
    for n, tile in enumerate(scene):
        y, col = divmod(n, 32)
        out[6144+n] = tile[bank]
        for i, value in enumerate(tile[2:]):
            out[bitmap_offset(y*8+i,col)] = value
    return out


BIKE = (
    "          ####          ", "         ######         ", "        ########        ",
    "        ##....##        ", "        ########        ", "         ######         ",
    "       ###....###       ", "     ######..######     ",
    "    ###.########.###    ", "   ###..########..###   ", "  ###...##....##...###  ",
    "  ##   .########.   ##  ", "  ###   .######.   ###  ", "   #####.######.#####   ",
    "     ##############     ", "    ###..........###    ",
    "   ###..########..###   ", "   ##...########...##   ", "  ###  ##......##  ###  ",
    "  ###  ###....###  ###  ", "  ##    ###..###    ##  ", "        ##.##.##        ",
    "         ##..##         ", "          ####          ",
)


def riders():
    out = bytearray()
    for lean in (-1,0,1):
        for r in range(3):
            for c in range(3):
                colours = ((7,14,7),(10,10,10),(7,15,7))
                ink = colours[r][c] & 7
                out.extend((ink | (64 if colours[r][c] >= 8 else 0), ink))
                for y in range(r*8,r*8+8):
                    mask, bits = 255, 0
                    for x in range(c*8,c*8+8):
                        sx = x - lean*round(2*(23-y)/23)
                        ch = BIKE[y][sx] if 0 <= sx < 24 else " "
                        if ch != " ":
                            mask &= ~(128 >> (x%8))
                        if ch == "#":
                            bits |= 128 >> (x%8)
                    out.extend((mask,bits))
    return out


# IDs below map to a pair of ULA attributes. Kerb cells take priority when
# another part of the scene passes through the same eight-pixel square.
ATTRS = ((0x47,0x0a), (0x47,0x0a), (0x47,0x09), (0x46,0x0e),
         (0x44,0x0c), (0x47,0x0f), (0x42,0x0a), (0x45,0x0d))


def sprite_shape(kind,height):
    """Transparent spans, in pixel coordinates local to the sprite."""
    rows=[]
    for y in range(height):
        t=(y+.5)/height
        if kind=="bike":
            source=BIKE[min(23,int(t*24))]
            width=height
            ink=[source[min(23,(x*24+12)//width)]=="#" for x in range(width)]
            style=3 if t<.29 else 7 if t<.66 else 5
        else:
            width=max(3,round(height*(.64 if kind=="tree" else .40)))|1
            mid=width//2
            if kind=="tree":
                extent=1 if t>.9 else max(1,round(mid*max(
                    (t-base)/(bottom-base) for base,bottom in ((0,.53),(.24,.71),(.43,.91)) if t>=base and (t<bottom or base==.43))))
                ink=[abs(x-mid)<extent for x in range(width)]
                style=4
            elif kind=="tower":
                extent=max(1,round(mid*(.65+.35*t)))
                ink=[abs(x-mid)<extent for x in range(width)]
                style=3 if t<.2 else 6 if .42<t<.63 else 5
            else:
                ink=[t<.34 or abs(x-mid)<=max(0,width//7) for x in range(width)]
                style=3 if t<.34 else 5
        runs=[]
        for x,on in enumerate(ink):
            if on and (x==0 or not ink[x-1]):
                runs.append([x,0])
            if on: runs[-1][1]+=1
        rows.append((style,runs))
    return width,rows


def actors(pose,course):
    step=pose/SUBSTEPS
    samples,rows=projection(step,course)
    objects=[]
    for station in range(2,STEPS,6):
        z=(station-step)%STEPS
        if not TYRES<=z<=16: continue
        r=at_distance(samples,z)
        section=surface(pose,course)[max(0,min(LINES-1,round(r.y)-FIRST))]
        cx,half=(section[:2] if section else (r.x,r.halfwidth))
        for side in (-1,1):
            kind=("tower" if course=="coast" and station in (8,38) and side==-1 else
                  "tree" if course=="ridge" and station%12==2 else "post")
            h=max(3,min(24,round({"tower":85,"tree":63,"post":26}[kind]/z)))
            x=round(cx+side*(half+r.kerb+14+20/z))
            objects.append((z,kind,h,x,round(r.y),camera_scale(round(r.y))))
    z=TYRES+(31-step%32)*.42
    r=at_distance(samples,z)
    h=max(3,min(24,round(31/z)))
    section=surface(pose,course)[max(0,min(LINES-1,round(r.y)-FIRST))]
    cx,half=(section[:2] if section else (r.x,r.halfwidth))
    x=round(cx+(-1 if step<32 else 1)*half*.48)
    objects.append((z,"bike",h,x,round(r.y),camera_scale(round(r.y))))
    result=[]
    for z,kind,h,x,foot,w in sorted(objects,reverse=True):
        # Seven depth scales share silhouettes across both circuits.
        h=min((3,5,7,10,14,19,24),key=lambda a:abs(a-h))
        width,_=sprite_shape(kind,h)
        top=foot-h+1
        start=max(0,FIRST-top)
        end=min(h,DASH-top)
        vis=[i for i in range(start,end) if visible(rows,top+i,z)]
        if vis and -125<=x-width//2<=380:
            result.append((kind,h,x-width//2,top,vis[0],vis[-1]+1,w))
    return result


def backdrop(course):
    pic=scenery(course)
    sky=pic[:64]
    for y in range(FIRST):
        pic[y]=sky[y*64//FIRST]
    base=tiles(pic)
    pair=[screen(base,b) for b in (0,1)]
    for b,scr in enumerate(pair):
        for y in range(FIRST,DASH):
            pos=bitmap_offset(y,0)
            scr[pos:pos+32]=bytes(32)
        scr[6144+FIRST*4:6144+DASH*4]=bytes([ATTRS[0][b]])*((DASH-FIRST)*4)
    return pair


def generate(out,course):
    from strokes import compile_scene
    compile_scene(out,course)
    (out/"riders.bin").write_bytes(riders())
    for bank,data in enumerate(backdrop(course)): (out/f"screen{bank}.bin").write_bytes(data)
    (out/"layout.inc").write_text(f"FIRST equ {FIRST}\nDASH equ {DASH}\nLINES equ {LINES}\n"
        f"SUBSTEP_TRAVEL equ {TRAVEL_PER_STEP//SUBSTEPS}\n")
    (out/"attr0.bin").write_bytes(bytes(a for a,b in ATTRS))
    (out/"attr1.bin").write_bytes(bytes(b for a,b in ATTRS))
    (out/"fine-slope.bin").write_bytes(b"".join(pack("<h",nearest((lane-128)*128/112)) for lane in range(256)))
    return PAGES
