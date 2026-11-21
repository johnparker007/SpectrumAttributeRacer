"""Compile eight-scanline kerb shapes and their shared, steerable endpoints."""

from functools import lru_cache
from typing import NamedTuple

from route import TYRES, projection

FIRST_BAND = 8
SLOPES = (-32, -24, -20, -16, -14, -12, -10, -8, -6, -4, -2, 0,
          2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32)
WIDTHS = range(4, 20, 2)
SCALE = 32
# One 256-byte page per slope. Width and horizontal phase form the low byte.
STAMP_ADDR = 0xe800
MATH_ADDR = 0x7100
SHIFT_ADDR = MATH_ADDR + 256


class Point(NamedTuple):
    left: int
    right: int
    scale: int


class Band(NamedTuple):
    start: Point
    end: Point
    width: int
    use_stamp: bool


def camera_shift(lane, scale):
    """Signed offset in two-pixel units, as used by the native lookup."""
    return round(round(((lane & 252) - 128) * scale / SCALE) / 2)


def section(row):
    radius = row.halfwidth + row.kerb / 2
    return row.x - radius, row.x + radius, SCALE * TYRES / row.z


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
                     and min(start.left, end.left) >= 0 and max(start.right, end.right) <= 255
                     and min(row.halfwidth for row in strip) >= 20
                     and max(a.z-b.z for a,b in zip(strip, strip[1:])) < 1)
        width = min(WIDTHS, key=lambda w: abs(w-strip[4].kerb))
        bands.append(Band(start, end, width, use_stamp))
    return bands


@lru_cache(maxsize=None)
def masks(slope, width, phase):
    # Anchor the strip two cells before its leftmost centre. Negative slopes
    # start at the right of the stamp and move towards that anchor.
    start = 16 + phase - min(slope, 0)
    lines = []
    for y in range(8):
        left = round(start + slope*y/8 - width/2)
        lines.append(((1 << width) - 1) << (64-left-width))
    return tuple(bytes((row >> (56-8*i)) & 255 for row in lines) for i in range(8))


@lru_cache(maxsize=None)
def slope_index(delta):
    return min(range(len(SLOPES)), key=lambda i: abs(SLOPES[i]-delta))


def overlay_kerbs(view, pose, lane, course, stamp_ids):
    result = bytearray(view)
    for row, band in enumerate(geometry(pose, course)):
        if not band.use_stamp:
            continue
        for side in (0, 1):
            start, end = (round(point[side]/2) - camera_shift(lane, point.scale)
                          for point in (band.start, band.end))
            column, phase = divmod(min(start, end), 4)
            index = (slope_index(2*(end-start))*256 + WIDTHS.index(band.width)*32 + phase*8)
            for i, tile in enumerate(stamp_ids[index:index+8]):
                x = column - 2 + i
                if tile and 0 <= x < 32 and not view[row*32+x]:
                    result[row*32+x] = tile
    return result


def stamp_data(ids):
    packed = bytearray()
    for i in range(0, len(ids), 8):
        group = ids[i:i+8]
        first = next(j for j,tile in enumerate(group) if tile)
        end = max(j for j,tile in enumerate(group) if tile) + 1
        count = end - first
        assert 1 <= count <= 7
        packed.extend(bytes([first*8+count]) + group[first:end] + bytes(7-count))
    return packed


def math_data():
    pages = bytes((STAMP_ADDR >> 8) + slope_index(2*((v+128) % 256-128)) for v in range(256))
    shifts = bytes(64 - camera_shift(lane, s) for s in range(34) for lane in range(0, 256, 4))
    return pages + shifts


def geometry_data(pose, course):
    bands = geometry(pose, course)
    data = bytearray()
    for point in [band.start for band in bands] + [bands[-1].end]:
        assert 0 <= point.scale < 34
        data.extend((point.scale, round(point.left/2), round(point.right/2)))
    data.extend(WIDTHS.index(b.width)*32 if b.use_stamp else 255 for b in bands)
    return data
