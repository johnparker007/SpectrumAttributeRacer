"""Project connected kerbs and lane paint for each visible scanline."""

from functools import lru_cache
from math import floor

from road_model import FIRST, LINES, lap, leverage
from route import TOP, projection

FOREGROUND = 104


def nearest(value):
    return floor(value + 0.5)


@lru_cache(maxsize=512)
def surface(pose, course):
    view = lap(course)[pose]
    rows = projection(pose/4,course)[1][FIRST-TOP:]
    return tuple(None if row is None else (*view.section(y),int(row.z*56)%32)
                 for y,row in enumerate(rows,FIRST))


def camera_scale(y):
    return nearest(112*leverage(y))


@lru_cache(maxsize=512)
def bands(pose, course):
    view = lap(course)[pose]
    first = next(i for i,row in enumerate(surface(pose,course)) if row)
    points = []
    for row in range(first//8*8, LINES+1, 8):
        y = FIRST+row
        left, inner, right, _ = view.boundaries(y)
        centre = (inner+right-1)/2
        width = 2*nearest((inner-left)/2)
        coords = tuple(256+nearest(2*x) for x in (left,right,centre))
        points.append((camera_scale(y), *coords, width, y>=FOREGROUND))
    return first,points


def projected(point, lane):
    scale, left, right, mark, width, _ = point
    shift = scale * nearest((lane-128) * 128/112)
    # Coordinates are half-pixels. Combine the camera offset and the course
    # coordinate before snapping the result to the native stroke grid.
    def position(value):
        return (64*value - shift + 128) // 256
    return position(left), position(right), position(mark), width


def ribbons(a, b, lane):
    left, right, mark, width = projected(a, lane)
    next_left, next_right, next_mark, next_width = projected(b, lane)
    result = [(left, next_left, width, next_width, 1),
              (right, next_right, width, next_width, 1)]
    if a[5] and b[5]:
        result.append((mark, next_mark, 2, 2, 2))
    return result


@lru_cache(None)
def masks(slope, width, next_width, phase):
    first = min(phase, phase + 2*slope) // 8
    lines = []
    for y in range(8):
        left = phase + (2*slope*y + 4)//8
        right = phase + width + ((2*slope + next_width-width)*y + 4)//8
        lines.append((left, right))
    end = (max(right for _, right in lines) + 7)//8
    tiles = []
    for col in range(first, end):
        tiles.append(bytes(sum(128 >> bit for bit in range(8) if left <= 8*col + bit < right)
                           for left, right in lines))
    return first, tuple(tiles)
