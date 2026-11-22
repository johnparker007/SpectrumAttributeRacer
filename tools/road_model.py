"""Floating-point road geometry shared by the PC preview and Spectrum compiler."""

from dataclasses import dataclass
from functools import lru_cache
from math import floor

from route import DASH, at_distance, projection

FIRST = 48
LINES = DASH - FIRST


def leverage(y):
    return max(0.0, min(1.0, (y-FIRST)/LINES)) ** 2.0


@dataclass(frozen=True)
class RoadView:
    crest: float
    far_x: float
    bend_x: float
    far_width: float

    def section(self, y, lane=128):
        # A cubic in screen depth gives each scanline its own tangent. The
        # horizon tangent is vertical and the near handle follows local yaw.
        t = (y-self.crest)/(DASH-1-self.crest)
        u = 1-t
        x = self.far_x*u*u*(1+2*t) + 3*u*t*t*self.bend_x + 128*t*t*t
        width = self.far_width + (112-self.far_width)*t
        return x - (lane-128)*leverage(y), max(2.0, width)

    def boundaries(self, y, lane=128):
        centre, half = self.section(y,lane)
        paint = max(4.0, 2.25 + 15.8*leverage(y))
        return centre-half-paint, centre-half, centre+half+1, centre+half+1+paint


@lru_cache(maxsize=2)
def lap(course):
    # Fit screen-space handles to several distances along the projected course.
    # All filtering is periodic, including the crossing of the finish line.
    values = []
    for pose in range(256):
        samples, _ = projection(pose/4, course)
        highest = min(samples, key=lambda row: row.y)
        near = at_distance(samples, 5)
        far = at_distance(samples, 16)
        values.append((max(FIRST,highest.y), 128+(far.x-128)*.46,
                       128+(near.x-128)*1.05, min(30,highest.halfwidth)))
    def smooth(column, radius, limit):
        # Symmetric slope-limited envelopes keep distant yaw readable across
        # a crest. Wrap both passes so the finish line has the same continuity.
        def envelope(sign):
            out = [sign*row[column] for row in values]*3
            for i in range(1,len(out)):
                out[i] = min(out[i],out[i-1]+limit)
            for i in range(len(out)-2,-1,-1):
                out[i] = min(out[i],out[i+1]+limit)
            return out[256:512]
        low, high = envelope(1), envelope(-1)
        bounded = [(a-b)/2 for a,b in zip(low,high)]
        return [sum((radius+1-abs(d))*bounded[(i+d)%256]
                    for d in range(-radius,radius+1))/(radius+1)**2 for i in range(256)]
    return [RoadView(*controls) for controls in zip(
        smooth(0,6,.9), smooth(1,8,.95), smooth(2,8,3), smooth(3,8,.5))]


def view_at(course, pose):
    views = lap(course)
    index = floor(pose)
    a,b = views[index%256],views[(index+1)%256]
    t = pose-index
    return RoadView(*(v+(w-v)*t for v,w in zip(
        (a.crest,a.far_x,a.bend_x,a.far_width),(b.crest,b.far_x,b.bend_x,b.far_width))))
