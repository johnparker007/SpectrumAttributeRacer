"""Compile the coast circuit into Spectrum screen tiles and forward-only road updates."""

from collections import Counter
from functools import lru_cache
from math import cos, pi, sin
from pathlib import Path
from struct import pack


WIDTH, HEIGHT = 256, 192
HORIZON, DASH = 64, 168
STEPS, PHASES, JOBS = 64, 32, 24
PAGES = (0, 1, 3, 4, 6)

# Each material specifies its colour on the two screen banks. Bit 3 is BRIGHT.
VOID, GRASS, TEAL, KERB, PAINT, STEEL, LAMP, RUBY = range(8)
MATERIALS = [(0, 0), (4, 12), (13, 13), (15, 10), (15, 0), (7, 7),
             (14, 14), (10, 10)]
STATIC = len(MATERIALS)
MATERIALS += [(i, i) for i in range(16)]

# Compact lettering for the instrument fascia.
FONT = dict(zip("AEGPRS0123456789",
    "255755 744647 345553 655644 655655 346127 755557 262227 616447 616116 557111 746116 346552 711222 257552 255316".split()))
TITLE = {letter: bytes.fromhex(rows) for letter, rows in {
    "C": "0f 10 10 10 10 10 0f", "O": "0e 11 11 11 11 11 0e",
    "A": "0e 11 11 1f 11 11 11", "S": "0f 10 10 0e 01 01 1e",
    "T": "1f 04 04 04 04 04 04", "R": "1e 11 11 1e 14 12 11",
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
    left, right = max(0, left), min(WIDTH, right)
    if right > left:
        row[left:right] = bytes([material]) * (right - left)


def scenery():
    pic = [bytearray(WIDTH) for _ in range(HEIGHT)]
    for y in range(HORIZON):
        for x in range(WIDTH):
            # Sunset over two silhouettes, with a coastal radio mast on the ridge.
            colour = 0
            if (x-174)**2 + (y-34)**2 <= 24**2 and (y < 32 or y % 5 < 3):
                colour = 14 if y < 24 else 10 if y < 40 else 11
            ridge = 51 + 5*sin(x/14) + 4*cos(x/22) - 5*abs(sin(x/8))
            if y >= ridge:
                colour = 3
            if y >= 56 + 4*sin(x/25) - 2*abs(sin(x/5)):
                colour = 1
            if y == 63:
                colour = 13
            pic[y][x] = STATIC + colour
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
    for letter in "COAST RUN":
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


def halfwidth(d):
    return 5 + d * 1.05


def centre(step, d):
    bend = sin(2*pi*step/STEPS)
    return 128 + round(60 * bend * (1 - d / (DASH-HORIZON))**2)


def road(pic, step):
    for y in range(HORIZON, DASH):
        d = y - HORIZON
        row = pic[y]
        row[:] = bytes([GRASS]) * WIDTH
        mid, w = centre(step, d), halfwidth(d)
        left, right = round(mid-w), round(mid+w)
        kerb = 1 + d//18
        # An unpainted shoulder leaves room for the ULA cell containing each
        # kerb to use its second colour for paint, even on a diagonal.
        apron = 5 + d//12
        span(row, left-kerb-apron, right+kerb+apron+1, VOID)
        span(row, left-kerb, left, KERB)
        span(row, right+1, right+kerb+1, KERB)
        for sign in (-1, 1):
            mark = round(mid + sign*w*0.36)
            span(row, mark, mark+1+d//58, PAINT)

    # Two sets of roadside bollards, planted at equal world-space intervals.
    for distance in sorted(((1-(step/16 + offset) % 1) for offset in (0, 0.5)), reverse=True):
        d = round(8/(distance+0.065))
        if d >= DASH-HORIZON:
            continue
        for sign in (-1, 1):
            x = round(centre(step,d) + sign*(halfwidth(d)*1.16+4))
            h, w = max(2, d//5), max(1, d//28)
            for dy in range(h):
                span(pic[HORIZON+d-dy], x-w, x+w, RUBY if dy >= h*0.65 else STEEL)
            # Black-on-yellow bend board faces the approaching rider.
            direction = 1 if step < STEPS//2 else -1
            if d >= 18 and sign == -direction:
                top = HORIZON+d-h
                radius = max(2,d//12)
                for dy in range(-radius//2, radius//2+1):
                    line = pic[top+dy]
                    span(line,x-radius,x+radius+1,LAMP)
                    tip = x + direction*(radius//3-abs(dy))
                    span(line,tip-1,tip+1,VOID)

    # A slower rider ahead. Alternate passing sides on successive encounters.
    t = step % 32
    d = round(9/(1-t/34))
    x = round(centre(step,d) + (-1 if step < 32 else 1)*halfwidth(d)*0.48)
    h = max(3, round(d*0.26))
    foot = HORIZON + d
    for dy in range(h):
        row = pic[foot-h+dy]
        sy = (dy*24+12)//h
        for dx in range(h):
            shape = BIKE[min(23,sy)][min(23,(dx*24+12)//h)]
            if shape == "#":
                row[x-h//2+dx] = LAMP if sy<6 else TEAL if sy<16 else STEEL
            elif shape == ".":
                row[x-h//2+dx] = VOID
    return x, foot


def bitmap_offset(y, col):
    return ((y & 0xc0) << 5) + ((y & 7) << 8) + ((y & 0x38) << 2) + col


@lru_cache(maxsize=32768)
def encode(cell):
    # Both banks share a bitmap. Pick two materials for this cell, allowing the
    # bitmap edge to cross an attribute boundary at single-pixel precision.
    count = Counter(cell)
    weights = {KERB: 4, PAINT: 4, STEEL: 5, LAMP: 6, RUBY: 6, TEAL: 5}
    ranked = sorted(count, key=lambda m: count[m]*weights.get(m, 1), reverse=True)
    paper, ink = ranked[0], ranked[min(1,len(ranked)-1)]
    # The rider keeps background set bits under the transparent part of its
    # mask. Keep the black asphalt clear even in a mostly painted edge cell.
    if ink == VOID:
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


def pack_page(steps):
    tileset = {}
    for _, delta in steps:
        for _, tile in delta:
            tileset.setdefault(tile, len(tileset)*10)
    data = bytearray(b"".join(tileset))
    offsets = []
    for _, delta in steps:
        offsets.append(len(data))
        for n, tile in delta:
            data += pack("<HH", 0x5800+n, 0xc000+tileset[tile])
        # Fixed-size batches let the pre-display blitter run in constant time.
        data += data[-4:] * (-len(delta) % JOBS)
    return data, offsets


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
                out.extend((colours[r][c] & 7 | (64 if colours[r][c] >= 8 else 0),0))
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


def generate(out: Path):
    pic = scenery()
    states, encounters = [], []
    for step in range(STEPS):
        encounters.append(road(pic, step))
        states.append(tiles(pic))
    for bank in range(2):
        (out/f"screen{bank}.bin").write_bytes(screen(states[0], bank))
    groups = [[]]
    descriptors = []
    for i, state in enumerate(states):
        delta = [(n,tile) for n,tile in enumerate(state) if tile != states[i-1][n]]
        if not 0 < len(delta) <= JOBS*6:
            raise ValueError(f"Step {i}: {len(delta)} dirty tiles exceed the top-gear update window")
        if len(pack_page(groups[-1]+[(i,delta)])[0]) > 16384:
            groups.append([])
        groups[-1].append((i,delta))
    if len(groups) > len(PAGES):
        raise ValueError("Course exceeds the five available 16K banks")
    for page, steps in zip(PAGES, groups):
        data, offsets = pack_page(steps)
        (out/f"page{page}.bin").write_bytes(data)
        for (i,delta), offset in zip(steps, offsets):
            x, foot = encounters[i]
            descriptors.append(f"    db {page}, {(len(delta)+JOBS-1)//JOBS}, {x}, {min(foot,255)}\n"
                               f"    dw {0xc000+offset}")
    (out/"course.inc").write_text("\n".join(descriptors)+"\n")
    (out/"riders.bin").write_bytes(riders())
    (out/"road-phases.bin").write_bytes(bytes(
        0x1f if (int(4000/(y-HORIZON+5)) + phase) % PHASES >= PHASES//2 else 0x17
        for phase in range(PHASES) for y in range(HORIZON,DASH)))
    (out/"layout.inc").write_text(f"HORIZON equ {HORIZON}\nDASH equ {DASH}\nJOBS equ {JOBS}\n")
    return PAGES[:len(groups)]
