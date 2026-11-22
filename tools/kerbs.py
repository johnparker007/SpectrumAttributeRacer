"""Project connected kerbs and lane paint for each visible scanline."""

from functools import lru_cache
from math import floor

from route import DASH, TOP, projection

FIRST = 48
LINES = DASH - FIRST
FOREGROUND = 104


def nearest(value):
    return floor(value + 0.5)


def bounded_lap(values, speed):
    """Limit movement per pose in both directions round the closed circuit."""
    def lower_envelope(sequence):
        result = sequence * 3
        for i in range(1, len(result)):
            result[i] = min(result[i], result[i-1] + speed)
        for i in range(len(result)-2, -1, -1):
            result[i] = min(result[i], result[i+1] + speed)
        return result[len(sequence):2*len(sequence)]

    lower = lower_envelope(values)
    negative_upper = lower_envelope([-v for v in values])
    return [(a-b)/2 for a, b in zip(lower, negative_upper)]


@lru_cache(maxsize=2)
def circuit_surface(course):
    frames = []
    for pose in range(256):
        rows = projection(pose/4, course)[1][FIRST-TOP:]
        centre, halfwidth = 128.0, 112.0
        lines = []
        for row in reversed(rows):
            if row is not None:
                centre += max(-3.5, min(3.5, row.x - centre))
                halfwidth += max(-2.0, min(0.0, row.halfwidth - halfwidth))
            phase = None if row is None else int(row.z * 56) % 32
            lines.append([centre, halfwidth, phase])
        frames.append(list(reversed(lines)))

    for y in range(LINES):
        for axis, limit in ((0, 4.0), (1, 1.5)):
            filtered = bounded_lap([frame[y][axis] for frame in frames], limit)
            for frame, value in zip(frames, filtered):
                frame[y][axis] = value
    return [tuple(None if phase is None else (x, w, phase) for x, w, phase in frame)
            for frame in frames]


def surface(pose, course):
    return circuit_surface(course)[pose]


def camera_scale(y):
    depth = max(0, y - FIRST) / LINES
    return min(112, nearest(112 * depth ** 1.55))


def section(frame, top, y):
    # Extrapolate the end slope at the skyline and the tyres.
    index = max(top, min(y, LINES-1))
    x, width, _ = frame[index]
    if index != y:
        neighbour = frame[index+1] if y < index else frame[index-1]
        distance = abs(index-y)
        x += (x - neighbour[0]) * distance
        width += (width - neighbour[1]) * distance
    return x, max(3, width)


@lru_cache(maxsize=2)
def lap_bands(course):
    frames = circuit_surface(course)
    first = [next(i for i, row in enumerate(frame) if row) for frame in frames]
    controls_by_pose = [[] for _ in frames]
    for y in range(0, LINES+1, 8):
        scale = camera_scale(y + FIRST)
        # Both ends of a band share this control point with their neighbour.
        # Its width and steering leverage stay fixed as the crest moves past.
        exact_width = 2.25 + 19.75 * scale / 140
        width = max(4, 2 * nearest(exact_width/2))
        columns = [[], [], []]
        for frame, top in zip(frames, first):
            samples = [section(frame, top, y+dy) for dy in (-8, 0, 8)]
            x, w = ((a + 2*b + c)/4 for a, b, c in zip(*samples))
            for column, value in zip(columns, (x-w-exact_width, x+w+1, x)):
                column.append(value)
        filtered = [bounded_lap(column, 4) for column in columns]
        painted = y + FIRST >= FOREGROUND
        grid = 2 if painted else 4
        for pose, values in enumerate(zip(*filtered)):
            left, right, mark = (grid//2 * nearest(v/grid) + 64 for v in values)
            controls_by_pose[pose].append((scale, left, right, mark, width, painted, grid))
    return [(top, points[top//8:]) for top, points in zip(first, controls_by_pose)]


def bands(pose, course):
    return lap_bands(course)[pose]


def projected(point, lane):
    scale, left, right, mark, width, _, grid = point
    shift = (128 + scale * nearest((lane-128) * 128/112)) // 256
    if grid == 4:
        shift = (shift+1)//2 * 2
    return left-shift, right-shift, mark-shift, width


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
