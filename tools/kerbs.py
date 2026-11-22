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


def smooth_camera_positions(column):
    # The triangular window wraps at the finish line and preserves linear motion.
    bounded = bounded_lap(column, 4)
    weights = (1, 2, 3, 4, 5, 4, 3, 2, 1)
    return [sum(w * bounded[(pose+offset) % len(bounded)]
                for offset, w in enumerate(weights, -4)) / 25
            for pose in range(len(bounded))]


@lru_cache(maxsize=2)
def lap_bands(course):
    frames = circuit_surface(course)
    first = [next(i for i, row in enumerate(frame) if row) for frame in frames]
    # Follow the first visible road line as it rises and falls over crests.
    # A fixed-screen-row filter alone samples different depths on the next pose.
    tips = [frame[top][0] for frame, top in zip(frames, first)]
    tips = bounded_lap(tips, 1)
    controls_by_pose = [[] for _ in frames]
    for y in range(0, LINES+1, 8):
        scale = camera_scale(y + FIRST)
        # Both ends of a band share this control point with their neighbour.
        # Its width and steering leverage stay fixed as the crest moves past.
        exact_width = 2.25 + 19.75 * scale / 140
        width = max(4, 2 * nearest(exact_width/2))
        columns = [[], [], []]
        for frame, top, tip in zip(frames, first, tips):
            samples = [section(frame, top, y+dy) for dy in (-8, 0, 8)]
            x, w = ((a + 2*b + c)/4 for a, b, c in zip(*samples))
            # Keep the first band tangent to the distant heading. Blend back
            # into the ordinary projected curve before the foreground.
            distance = max(0, y - top - 8)
            blend = min(1.0, distance / 48)
            # At foreground depth the original projected position is authoritative.
            near = min(1.0, max(0, (FIRST+y-88)/48))
            weight = max(near*near*(3-2*near), blend*blend*(3-2*blend))
            x = tip * (1-weight) + x*weight
            for column, value in zip(columns, (x-w-exact_width, x+w+1, x)):
                column.append(value)
        filtered = [smooth_camera_positions(column) for column in columns]
        painted = y + FIRST >= FOREGROUND
        for pose, values in enumerate(zip(*filtered)):
            grid = 2 if painted or y <= first[pose]+8 else 4
            left, right, mark = (nearest(2*v) + 256 for v in values)
            controls_by_pose[pose].append((scale, left, right, mark, width, painted, grid))
    return [(top, points[top//8:]) for top, points in zip(first, controls_by_pose)]


def bands(pose, course):
    return lap_bands(course)[pose]


def projected(point, lane):
    scale, left, right, mark, width, _, grid = point
    shift = scale * nearest((lane-128) * 128/112)
    # Coordinates are half-pixels. Combine the camera offset and the course
    # coordinate before snapping the result to the native stroke grid.
    unit = grid // 2
    def position(value):
        return ((64*value - shift + 128*unit) // (256*unit)) * unit
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
