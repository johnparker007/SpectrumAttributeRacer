"""Compile a circuit into Spectrum screen tiles and forward-only road updates."""

from collections import Counter
from functools import lru_cache
from math import cos, sin
from pathlib import Path
from struct import pack

from route import DASH, STEPS, TOP, TYRES, at_distance, drift, profile, projection

WIDTH, HEIGHT = 256, 192
PHASES = 32
TRAVEL_PER_STEP = 56
SUBSTEPS = 4
POSES = STEPS * SUBSTEPS
MARGIN = 112
MAP_WIDTH = 32 + 2*MARGIN//8
EARLY_TILES, EXTRA_TILES = 33, 18
PAGES = (0, 1, 3, 4, 6, 7)
PAGE_START = {p:(0xdc00 if p==7 else 0xc000) for p in PAGES}

# Each material specifies its colour on the two screen banks. Bit 3 is BRIGHT.
VOID, GRASS, TEAL, KERB, PAINT, STEEL, LAMP, RUBY, ASPHALT = range(9)
# Bank 7 uses normal intensity across the entire road, including the objects.
# Its lane paint matches the asphalt so the dashes disappear into the blue.
MATERIALS = [(0, 0), (12, 4), (13, 5), (15, 2), (15, 1), (7, 7),
             (14, 6), (10, 2), (0, 1)]
STATIC = len(MATERIALS)
MATERIALS += [(i, i) for i in range(16)]

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


@lru_cache(maxsize=2)
def background(course):
    return tuple(bytes(row) for row in scenery(course)[:DASH])


@lru_cache(maxsize=None)
def edges(step, course):
    """Separate the kerb edges within each ULA band, independently across a crest."""
    rows = projection(step, course)[1]
    result = [None] * len(rows)
    for band in range(0, len(rows), 8):
        start = band
        while start < band+8:
            if rows[start] is None:
                start += 1
                continue
            end = start+1
            while end < band+8 and rows[end] and rows[end-1].z - rows[end].z < 3:
                end += 1
            sides = []
            for side in (-1, 1):
                spans = []
                for r in rows[start:end]:
                    inner = round(r.x + side*r.halfwidth)
                    lo = inner - r.kerb if side < 0 else inner + 1
                    spans.append((lo, lo+r.kerb))
                seam = 8 * round((max(lo for lo, _ in spans) + min(hi for _, hi in spans))/16)
                # Keep tight downhill bends on their projected path even when
                # the kerb crosses several character columns in eight lines.
                offsets = [max(seam-hi, min(0, seam-lo)) for lo,hi in spans]
                sides.append([lo + max(-5, min(5, offset)) for (lo,_),offset in zip(spans,offsets)])
            result[start:end] = list(zip(*sides))
            start = end
    return result


def visible(rows, y, z):
    return TOP <= y < DASH and (rows[y-TOP] is None or rows[y-TOP].z >= z-.04)


def road(pic, step, course="coast", margin=0):
    samples, rows = projection(step, course)
    for i, (r, pair) in enumerate(zip(rows, edges(step, course))):
        row = pic[TOP+i]
        if r is None:
            sky = background(course)[TOP+i]
            row[:] = sky[:1]*margin + sky + sky[-1:]*margin
            continue
        lo, hi = (x+margin for x in pair)
        row[:] = bytes([GRASS]) * len(row)
        span(row, lo, lo+r.kerb, KERB)
        span(row, lo+r.kerb, hi, ASPHALT)
        span(row, hi, hi+r.kerb, KERB)
        for side in (-1, 1):
            mark = margin + round(r.x + side*r.halfwidth*.36)
            span(row, max(lo+r.kerb+1, mark), min(hi-1, mark+1+int(r.z<2.3)), PAINT)

    # World-space objects use the same depth and elevation as their road.
    # Test each object scanline so a nearer crest can hide its lower half.
    actors = []
    for station in range(2, STEPS, 6):
        z = (station-step) % STEPS
        if TYRES <= z <= 16:
            actors.append((z, station))
    rival_z = TYRES + (31-step%32)*.42
    actors.append((rival_z, None))
    rival_x = rival_y = 0
    for z, station in sorted(actors, key=lambda a: -a[0]):
        r = at_distance(samples, z)
        foot = round(r.y)
        if station is None:
            rival_x = round(r.x + (-1 if step<32 else 1)*r.halfwidth*.48)
            rival_y = foot
            h = max(3, round(31/z))
            for dy in range(h):
                y = foot-h+dy
                if not visible(rows, y, z):
                    continue
                sy = min(23, (dy*24+12)//h)
                for dx in range(h):
                    x = margin+rival_x-h//2+dx
                    if not 0 <= x < len(pic[y]):
                        continue
                    shape = BIKE[sy][min(23, (dx*24+12)//h)]
                    if shape == "#":
                        pic[y][x] = LAMP if sy<6 else TEAL if sy<16 else STEEL
                    elif shape == ".":
                        pic[y][x] = ASPHALT
            continue
        direction = 1 if profile(station, course)[1] > 0 else -1
        for side in (-1, 1):
            x = margin + round(r.x + side*(r.halfwidth+r.kerb+10+20/z))
            if course == "coast" and station in (8, 38) and side == -1:
                # A red-banded navigation tower with a lit lantern.
                height = round(85/z)
                for dy in range(height):
                    y = foot-dy
                    if visible(rows, y, z):
                        w = max(1, round((12-5*dy/height)/z))
                        ink = LAMP if dy > .85*height else RUBY if .38*height < dy < .63*height else STEEL
                        span(pic[y], x-w, x+w+1, ink)
                continue
            if course == "ridge" and station % 12 == 2:
                # Three overlapping whorls give the pines a readable silhouette.
                height = round(63/z)
                for dy in range(height):
                    y = foot-dy
                    if visible(rows, y, z):
                        t = dy/height
                        whorl = max((tip-t for base,tip in ((.12,.72),(.38,.86),(.61,1))
                                     if t >= base), default=0)
                        w = max(1, round(19*whorl/z))
                        span(pic[y], x-w, x+w+1, STATIC+1 if whorl else VOID)
                continue
            h, w = max(2,round(26/z)), max(1,round(3/z))
            for dy in range(h):
                y = foot-dy
                if visible(rows,y,z):
                    span(pic[y], x-w,x+w, RUBY if dy>h*.65 else STEEL)
            if z < 9 and side == -direction:
                radius = max(2,round(12/z))
                for dy in range(-radius//2,radius//2+1):
                    y = foot-h+dy
                    if visible(rows,y,z):
                        span(pic[y],x-radius,x+radius+1,LAMP)
                        tip = x+direction*(radius//3-abs(dy))
                        span(pic[y],tip-1,tip+1,VOID)
    return rival_x, rival_y


def bitmap_offset(y, col):
    return ((y & 0xc0) << 5) + ((y & 7) << 8) + ((y & 0x38) << 2) + col


@lru_cache(maxsize=32768)
def encode(cell):
    # Both banks share a bitmap. Pick two materials for this cell, allowing the
    # bitmap edge to cross an attribute boundary at single-pixel precision.
    count = Counter(cell)
    if KERB in count and ASPHALT in count and len(count) > 2 and GRASS not in count:
        # A distant rider can occupy the same cell as the inner edge. Draw
        # its highlights in the kerb ink so both silhouettes survive the swap.
        cell = bytes(ASPHALT if m in (ASPHALT, PAINT) else KERB for m in cell)
        count = Counter(cell)
    weights = {KERB: 4, PAINT: 4, STEEL: 5, LAMP: 6, RUBY: 6, TEAL: 5}
    ranked = sorted(count, key=lambda m: count[m]*weights.get(m, 1), reverse=True)
    paper, ink = ranked[0], ranked[min(1,len(ranked)-1)]
    # The rider keeps background set bits under the transparent part of its
    # mask. Keep the black asphalt clear even in a mostly painted edge cell.
    if ink in (ASPHALT, VOID):
        paper, ink = ink, paper
    attrs = []
    for page in range(2):
        p, i = MATERIALS[paper][page], MATERIALS[ink][page]
        attrs.append(((p & 7) << 3) | (i & 7) | (64 if max(p,i) >= 8 else 0))
    # In a mixed edge cell, keep small painted details and clip excess verge.
    bits = bytes(sum(128 >> x for x in range(8) if cell[8*y+x] == ink)
                 for y in range(8)) if paper != ink else bytes(8)
    return bytes(attrs) + bits


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



def course_maps(course):
    pic = [bytearray(row[:1]*MARGIN+row+row[-1:]*MARGIN) for row in scenery(course)]
    maps = []
    depths = []
    scales = []
    for pose in range(POSES):
        step = pose/SUBSTEPS
        road(pic, step, course, MARGIN)
        maps.append([encode(b"".join(line[x:x+8] for line in pic[y:y+8]))
                     for y in range(TOP,DASH,8) for x in range(0,8*MAP_WIDTH,8)])
        rows = projection(step,course)[1]
        depths.append(bytes(64 if r is None else int(r.z*TRAVEL_PER_STEP)%PHASES for r in rows))
        scales.append(bytes(round(15*TYRES/r.z) if r else 0 for r in rows[4::8]))
    return maps,depths,scales


def tile_atlas(strips):
    # Keep both attributes exact. Spend the remaining tile IDs on common
    # bitmaps, then match rarer edge shapes by their eight scanline masks.
    counts = Counter(t for row in strips for t in row)
    groups = {}
    for t,_ in counts.most_common():
        groups.setdefault(t[:2],[]).append(t)
    if len(groups)>256:
        raise ValueError("A road half exceeds the 256 tile attribute pairs available")
    atlas = list(dict.fromkeys([g[0] for g in groups.values()] + [t for t,_ in counts.most_common()]))[:256]
    candidates = {pair:[(i,int.from_bytes(t[2:],"little")) for i,t in enumerate(atlas) if t[:2]==pair]
                  for pair in groups}
    mapping = {t:i for i,t in enumerate(atlas)}
    for t in counts.keys()-mapping.keys():
        bits = int.from_bytes(t[2:],"little")
        mapping[t] = min(candidates[t[:2]],key=lambda c:(c[1]^bits).bit_count())[0]
    return atlas, mapping


def map_delta(old, new):
    # 01..7F skips unchanged cells. 81..FF copies literal tile IDs.
    data = bytearray()
    i = 0
    while i < len(new):
        changed = old[i] != new[i]
        j = i+1
        while j < len(new) and j-i < 127:
            if changed:
                if old[j]==new[j] and (j+1==len(new) or old[j+1]==new[j+1]):
                    break
            elif old[j]!=new[j]:
                break
            j += 1
        if changed or j!=len(new):
            data.append((128 if changed else 0) + j-i)
            if changed:
                data.extend(new[i:j])
        i = j
    return data + b"\0"


def artwork(course):
    maps,depths,scales = course_maps(course)
    half = len(maps[0])//2
    ids = [bytearray() for _ in maps]
    atlases = []
    for n in range(2):
        strips = [m[n*half:(n+1)*half] for m in maps]
        atlas,mapping = tile_atlas(strips)
        atlases.append(atlas)
        for dst,strip in zip(ids,strips):
            dst.extend(mapping[t] for t in strip)
    # Hold sub-pixel edge noise until it visibly changes the tile. Compare
    # against the last emitted shape, so successive small movements accumulate.
    for half_index,atlas in enumerate(atlases):
        bits = [int.from_bytes(t[2:],"little") for t in atlas]
        close = [{j for j,b in enumerate(bits) if atlas[i][:2]==atlas[j][:2] and
                  (a^b).bit_count()<=5} for i,a in enumerate(bits)]
        begin = half_index*half
        previous = ids[-1][begin:begin+half]
        original = [m[begin:begin+half] for m in ids]
        # Two laps settle the threshold at the join as well as on the straights.
        for lap in range(2):
            for m,row in zip(ids,original):
                previous = bytearray(b if b in close[a] else a for a,b in zip(row,previous))
                if lap:
                    m[begin:begin+half] = previous
    return ids,depths,scales,atlases


def generate(out: Path, course):
    ids,depths,scales,atlases = artwork(course)
    half = len(ids[0])//2
    for n,atlas in enumerate(atlases):
        (out/f"atlas{n}.bin").write_bytes(b"".join(atlas))
    shown = bytes(ids[0][row*MAP_WIDTH+MARGIN//8+x] for row in range(16) for x in range(32))
    (out/"shown.bin").write_bytes(shown)
    (out/"world.bin").write_bytes(ids[0])
    initial = tiles(scenery(course))
    initial[TOP*4:DASH*4] = [atlases[i//256][tile] for i,tile in enumerate(shown)]
    for bank in range(2):
        (out/f"screen{bank}.bin").write_bytes(screen(initial,bank))
    (out/"depth0.bin").write_bytes(depths[0])
    (out/"scale0.bin").write_bytes(scales[0])
    (out/"riders.bin").write_bytes(riders())
    # Keep both halves of each quarter-step together in a pageable bank.
    pages = [bytearray() for _ in PAGES]
    descriptor = []
    for q in range(POSES):
        d = depths[q]
        halves = []
        for n in range(2):
            begin = n*half
            segment = d[n*64:n*64+64]
            halves.append(map_delta(ids[q-1][begin:begin+half],ids[q][begin:begin+half])
                          +segment+scales[q][n*8:n*8+8])
        route = pack("<H",len(halves[0]))+b"".join(halves)
        index = min(range(len(pages)),key=lambda i:PAGE_START[PAGES[i]]+len(pages[i]))
        page = pages[index]
        descriptor.append(f"    dw {PAGE_START[PAGES[index]]+len(page)}\n    db {16+PAGES[index]}, "
                          f"{drift(q//SUBSTEPS,course)*(1 if q%2 else 2) & 255}")
        page.extend(route)
        if PAGE_START[PAGES[index]]+len(page)>0x10000:
            raise ValueError(f"{course} course exceeds bank {PAGES[index]} at pose {q}")
    for page,data in zip(PAGES,pages):
        (out/f"page{page}.bin").write_bytes(data)
    (out/"course.inc").write_text("\n".join(descriptor)+"\n")
    (out/"layout.inc").write_text(f"RASTER_TOP equ {TOP}\nDASH equ {DASH}\nMAP_WIDTH equ {MAP_WIDTH}\n"
                                  f"SUBSTEP_TRAVEL equ {TRAVEL_PER_STEP//SUBSTEPS}\n"
                                  f"EARLY_TILES equ {EARLY_TILES}\nEXTRA_TILES equ {EXTRA_TILES}\n")
    # One fixed-point perspective offset per band, expressed in map columns.
    (out/"scroll.bin").write_bytes(bytes(max(0,min(MAP_WIDTH-32, MARGIN//8+round((lane-128)*z/(15*8))))
                                         for z in range(16) for lane in range(0,256,4)))
    return PAGES
