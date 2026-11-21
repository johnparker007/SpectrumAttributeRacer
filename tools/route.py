"""Project each closed circuit from the rider's position and local heading."""

from dataclasses import dataclass
from functools import lru_cache
from math import cos, pi


STEPS = 64
TOP, DASH = 40, 168
FAR = 28.0
TYRES = 1.25
FOCAL, SKYLINE = 84, 71

# Course distance, elevation, signed curvature. The last knot joins the first.
# The coast sweep climbs onto a headland, drops into a hooked ravine, crosses
# a long low causeway and climbs back through two blind summit bends.
COAST = (
    (0, 0.0, .030), (5, .35, .085), (11, 2.4, .145),
    (16, 4.0, .015), (21, 2.0, -.195), (26, -.5, -.080),
    (31, -.8, .145), (36, .0, .015), (41, .0, .000),
    (46, 1.4, -.115), (50, 3.0, -.165), (55, .7, .085),
    (59, 1.45, .120), (64, .0, .030),
)


RIDGE = (
    (0, .0, -.065), (5, .2, -.185), (10, 1.9, .185),
    (16, 5.6, .115), (20, 5.1, -.095), (26, .8, -.155),
    (30, -.7, .035), (35, 1.4, .185), (39, 3.3, -.035),
    (44, .6, -.190), (49, -1.1, -.050), (54, .1, .145),
    (59, .8, .040), (64, .0, -.065),
)
COURSES = {"coast": COAST, "ridge": RIDGE}


def grade_at(knots, index):
    prev = knots[(index-1) % (len(knots)-1)]
    following = knots[(index+1) % (len(knots)-1)]
    return (following[1]-prev[1]) / ((following[0]-prev[0]) % STEPS)


def profile(distance, course):
    knots = COURSES[course]
    station = distance % STEPS
    for i, ((a, h0, k0), (b, h1, k1)) in enumerate(zip(knots, knots[1:])):
        if station < b:
            u = (station-a) / (b-a)
            smooth = u*u*(3-2*u)
            h = h0 + (h1-h0)*smooth + (b-a)*u*(1-u)*((1-u)*grade_at(knots, i) - u*grade_at(knots, i+1))
            return .75*h, 2.05*(k0 + (k1-k0)*(1-cos(pi*u))/2)


@dataclass(frozen=True)
class Section:
    z: float
    y: float
    x: float

    @property
    def halfwidth(self):
        return 140 / self.z

    @property
    def kerb(self):
        return round(4.5 + 39.5 / self.z)


@lru_cache(maxsize=None)
def projection(step, course):
    """Near-to-far samples and the nearest visible surface on each screen line."""
    height, _ = profile(step + TYRES, course)
    # The camera looks level. Elevation is relative to the point below the
    # bike. The road meets the tyres at the same screen line on every grade.
    spacing = 1/32
    heading = lateral = 0.0
    samples = []
    for i in range(1, round(FAR/spacing)+1):
        z = i * spacing
        _, turn = profile(step + z - spacing/2, course)
        lateral += spacing * (heading + turn*spacing/2)
        heading += turn * spacing
        if z < TYRES:
            continue
        if z == TYRES:
            near_direction = lateral/z
        x = 128 + FOCAL * (lateral/z - near_direction)
        h, _ = profile(step + z, course)
        y = SKYLINE + ((DASH-1-SKYLINE)*TYRES + FOCAL*(height-h))/z
        samples.append(Section(z, y, x))

    rows = [None] * (DASH-TOP)
    next_y = DASH-1
    for a, b in zip(samples, samples[1:]):
        # A ridge hides any farther surface projecting below its crest.
        while next_y >= TOP and b.y <= next_y <= a.y + 1e-9:
            t = (a.y-next_y) / (a.y-b.y) if a.y != b.y else 0
            rows[next_y-TOP] = Section(a.z + t*(b.z-a.z), next_y, a.x + t*(b.x-a.x))
            next_y -= 1
    return samples, rows


def at_distance(samples, z):
    index = min(len(samples)-2, max(0, int((z-samples[0].z)*32)))
    a, b = samples[index:index+2]
    t = (z-a.z)/(b.z-a.z)
    return Section(z, a.y+t*(b.y-a.y), a.x+t*(b.x-a.x))


def drift(step, course):
    turn = profile(step+TYRES, course)[1]
    if abs(turn) < .085 or (abs(turn) < .265 and step % 2):
        return 0
    return -1 if turn > 0 else 1
