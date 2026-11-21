"""Compile the foreground lane and kerb strokes used by the 128K renderer."""

from functools import lru_cache
from typing import NamedTuple

from route import TYRES, projection

FIRST_BAND = 8
SLOPES = tuple(range(-56,57,4))
WIDTHS = (2, 8, 12, 16)
PHASES = (0, 4)
STAMP_CELLS = 12
SCALE = 32
# One pointer-table page per width. Signed slope and horizontal phase select a blitter.
STAMP_ADDR = 0xec00
SHIFT_ADDR = 0x7100


class Point(NamedTuple):
    left: int
    right: int
    scale: int
    lane_left: int
    lane_right: int


class Band(NamedTuple):
    start: Point
    end: Point
    width: int
    use_stamp: bool


def camera_shift(lane, scale):
    """Signed offset in four-pixel units, as used by the native lookup."""
    return round(((lane & 252) - 128) * scale / (4*SCALE))


def section(row):
    return (row.x - row.halfwidth - row.kerb, row.x + row.halfwidth + 1, SCALE * TYRES / row.z,
            row.x - .36*row.halfwidth, row.x + .36*row.halfwidth)


@lru_cache(maxsize=None)
def geometry(pose, course):
    rows = projection(pose / 4, course)[1][FIRST_BAND * 8:]
    points = [Point(*map(round, section(row))) for row in rows[::8]]
    # The final endpoint is just below the dashboard. Extrapolate the last
    # scanline so the bottommost eight lines use the same interpolation rule.
    last, previous = section(rows[-1]), section(rows[-2])
    points.append(Point(*(round(2*a-b) for a,b in zip(last, previous))))
    bands = []
    for i, (start, end) in enumerate(zip(points, points[1:])):
        strip = rows[8*i:8*i+8]
        # Preserve the original silhouette at a depth break or where both
        # kerbs, the lane dashes and scenery crowd into a few distant cells.
        use_stamp = (max(abs(end.left-start.left), abs(end.right-start.right)) <= 25
                     and min(start.left, end.left) >= -16 and max(start.right, end.right) <= 272
                     and min(row.halfwidth for row in strip) >= 20
                     and max(a.z-b.z for a,b in zip(strip, strip[1:])) < 1)
        width = min(WIDTHS[1:], key=lambda w: abs(w-strip[4].kerb))
        bands.append(Band(start, end, width, use_stamp))
    return bands


@lru_cache(maxsize=None)
def stroke_offsets(slope, xgrid=1, ygrid=1):
    return tuple(xgrid*round(slope*(y//ygrid*ygrid+(ygrid-1)/2)/(8*xgrid)) for y in range(8))


@lru_cache(maxsize=None)
def masks(slope, width, phase, xgrid=1, ygrid=1):
    # Keep a common cell origin for the two paint boundaries. Width is an
    # extent, so an 18-pixel and a 10-pixel stripe can reuse the same edge tiles.
    start = 8 + phase - min(slope, 0)
    lines = []
    for offset in stroke_offsets(slope,xgrid,ygrid):
        left = start + offset
        lines.append(((1 << width) - 1) << (8*STAMP_CELLS-left-width))
    return tuple(bytes((row >> (8*(STAMP_CELLS-i-1))) & 255 for row in lines) for i in range(STAMP_CELLS))


def overlay_kerbs(view, pose, lane, course, stamp_ids):
    result = bytearray(view)
    for row, band in enumerate(geometry(pose, course)):
        if not band.use_stamp:
            continue
        for side, width in ((3,2),(4,2),(0,band.width),(1,band.width)):
            start, end = (round(point[side]/4) - camera_shift(lane, point.scale)
                          for point in (band.start, band.end))
            column, phase = divmod(min(start, end), 2)
            index = (SLOPES.index(4*(end-start))*len(WIDTHS)*2 + WIDTHS.index(width)*2 + phase)*STAMP_CELLS
            for i, tile in enumerate(stamp_ids[index:index+STAMP_CELLS]):
                x = column-1+i
                if tile and 0 <= x < 32 and not view[row*32+x]:
                    result[row*32+x] = tile
    return result


def stamp_source(ids):
    # Each signed-slope/phase lookup points to a short blitter. Its common
    # path writes a whole, visible stroke. Only a stamp touching the edge of
    # the display needs the clipped writer in fixed RAM.
    stubs = {}
    tables = []
    for w in range(len(WIDTHS)):
        table = [0]*128
        for i,slope in enumerate(SLOPES):
            for p in range(2):
                index = ((i*len(WIDTHS)+w)*2+p)*STAMP_CELLS
                tiles = ids[index:index+STAMP_CELLS]
                if not any(tiles):
                    continue
                first = next(j for j,t in enumerate(tiles) if t)
                last = max(j for j,t in enumerate(tiles) if t)+1
                shift = min(0,slope//4)
                # Lookup phase is relative to the starting endpoint.
                phase = (p-shift) % 2
                offset = (phase+shift)//2 - 1 + first - 16
                key = (offset,bytes(tiles[first:last]))
                code = stubs.setdefault(key,len(stubs)+1)
                table[((slope//4)*2+phase)%128] = code
        tables.append(table)
    lines = []
    for table in tables:
        lines.extend("    dw "+",".join(f"stroke{x}" for x in table[i:i+8])
                     for i in range(0,128,8))
    lines += ["stroke0: ret"]
    for (offset,tiles),i in stubs.items():
        lines += [f"stroke{i}:", f"    add a,{offset & 255} : cp {33-len(tiles)} : call nc,clip{len(tiles)}",
                  "    or c : ld e,a"]
        for tile in tiles:
            # Keep the four-byte layout consumed by clipStroke. An empty cell
            # in a steep stroke may already contain paint from another strip.
            write = "ld (de),a" if tile else "nop"
            lines.append(f"    ld a,{tile} : {write} : inc e")
        lines += ["    ret"]
    return "\n".join(lines)+"\n"


def math_data():
    return bytes(32-camera_shift(lane,s) for s in range(34) for lane in range(0,256,4))


def geometry_data(pose, course):
    bands = geometry(pose, course)
    data = bytearray()
    for point in [band.start for band in bands] + [bands[-1].end]:
        assert 0 <= point.scale < 34
        data.extend((SHIFT_ADDR+64*point.scale).to_bytes(2,"little"))
        data.extend((round(point.left/4) & 255, round(point.right/4) & 255,
                     round(point.lane_left/4), round(point.lane_right/4)))
    data.extend((STAMP_ADDR>>8)+WIDTHS.index(b.width) if b.use_stamp else 255 for b in bands)
    return data
