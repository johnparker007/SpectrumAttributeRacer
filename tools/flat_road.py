"""Flat-road Hang-On study. All distances and steering are continuous PC coordinates."""

from bisect import bisect_right
from functools import lru_cache
from math import cos, pi, sin, floor, ceil

W, H, SKY = 344, 240, 137
NEAR, FAR = 4., 180.
LANE_SCALE = 188
KERB_RATIO = .19
STRIPE_LENGTH = .72
LANDMARK_SPACING, LANDMARK_OFFSET = 12, 9.5
# Integrated lateral curvature. Constant stretches are long enough to study
# the same turn at several speeds, then ease into a straight or a reversal.
KNOTS = ((0,0.),(225,0.),(310,.52),(550,.52),(665,0.),(735,0.),
         (835,1.48),(1070,1.48),(1190,0.),(1290,-1.40),(1510,-1.40),
         (1630,0.),(1728,0.))
LENGTH = KNOTS[-1][0]
# Name, distance, lateral offset in road half-widths, palette.
SHOTS = (('Opening straight',12,0.,'Coast'),('Coastal right',352,.81,'Coast'),
         ('Desert right',856,.52,'Desert'),('Desert left',1308,-.80,'Desert'))


def curvature(s):
    s %= LENGTH
    i = bisect_right(KNOTS,(s,float('inf')))-1
    a,k = KNOTS[i]
    b,target = KNOTS[i+1]
    t = (s-a)/(b-a)
    return k+(target-k)*t*t*(3-2*t)


# Integrate once for heading and twice for lateral position. The projected
# camera subtracts its own heading; the extra distance spans the lap seam.
TURN = [curvature(i+.5) for i in range(LENGTH+int(FAR)+2)]
HEADING, PATH = [0.], [0.]
for k in TURN:
    PATH.append(PATH[-1]+HEADING[-1]+.5*k)
    HEADING.append(HEADING[-1]+k)


def path(s):
    i = floor(s)
    t = s-i
    return PATH[i]+t*(HEADING[i]+.5*t*TURN[i]), HEADING[i]+t*TURN[i]


def depth_at_fraction(t):
    return 1/(1/FAR+t*(1/NEAR-1/FAR))


def depth(y):
    return depth_at_fraction((y-SKY)/(H-1-SKY))


def line_width(halfwidth):
    return max(.4,halfwidth*.019)


def landmark_offset(station,halfwidth):
    return (-1 if station%3==1 else 1)*halfwidth*(1.42+.12*(station%2))



DEPTHS = tuple(depth(y) for y in range(SKY,H))


class Camera:
    def __init__(self, distance, lane):
        self.s = distance%LENGTH
        self.lane = lane
        self.x,self.heading = path(self.s)
        self.near_angle = self.angle(NEAR)

    def angle(self,z):
        x,_ = path(self.s+z)
        return (x-self.x)/z-self.heading

    def section(self,z):
        t = (1/z-1/FAR)/(1/NEAR-1/FAR)
        # A finite draw distance compresses the remote sweep. The heading
        # at the tyres anchors the near road while the far bend swings away.
        bend = 6.3*(self.angle(z)-self.near_angle)*(1-NEAR/z)/(1+z/40)
        return W/2+bend-self.lane*LANE_SCALE*t, 2+LANE_SCALE*t, t


def rgb(value):
    return bytes.fromhex(value)


def span(image,y,l,r,colour):
    if 0<=y<H:
        a=max(0,min(W,round(l)))
        b=max(a,min(W,round(r)))
        image[(y*W+a)*3:(y*W+b)*3]=colour*(b-a)


def polygon(image,points,colour):
    colour=rgb(colour)
    edges=list(zip(points,points[1:]+points[:1]))
    for y in range(max(0,ceil(min(p[1] for p in points)-.5)),
                   min(H,ceil(max(p[1] for p in points)-.5))):
        line=y+.5
        cuts=sorted(x+(line-h)*(u-x)/(v-h) for (x,h),(u,v) in edges
                    if min(h,v)<=line<max(h,v))
        for l,r in zip(cuts[::2],cuts[1::2]):
            span(image,y,l,r,colour)


@lru_cache(maxsize=2)
def scenery(theme):
    desert=theme=='Desert'
    sky,ground=('ffa500','e7d394') if desert else ('1017ef','00b993')
    image=bytearray(rgb(sky)*W*SKY+rgb(ground)*W*(H-SKY))
    # Distant silhouettes sit on a single horizontal ground plane.
    if desert:
        for x in range(W):
            ridge=4+4*sin(x*.051)+2*cos(x*.16)
            ridge+=22*max(0,min(1,(24-abs(x-122))/12))
            ridge+=10*max(0,min(1,(33-abs(x-246))/10))
            top=SKY-max(1,int(ridge)//2*2)
            for y in range(top,SKY):
                band=int(x//2+sin(y*.53+x*.05)*2)%9
                colour=('d79512','b87a0a','a76d0c','cf9115','966616')[band//2]
                if y>SKY-3:colour='c49840'
                span(image,y,x,x+1,rgb(colour))
    else:
        peaks=[(-25,132),(6,124),(17,121),(28,117),(34,118),(46,108),
               (57,103),(64,94),(71,105),(80,106),(98,119),(107,116),
               (122,115),(136,126),(156,132),(184,123),(192,124),
               (208,115),(219,110),(231,119),(249,122),(264,120),
               (282,130),(304,128),(330,134),(355,132)]
        polygon(image,peaks+[(355,SKY),(-25,SKY)],'a8b9ed')
        for i in (2,7,11,17,20):
            x,y=peaks[i]
            polygon(image,[(x,y),(x+4,y+9),(x+2,y+11),(x+14,y+16),
                           (x+24,SKY),(x+7,SKY),(x-4,y+12)],'858ec9')
        for x in range(W):
            h=3+int(2*sin(x*.39)+1.6*cos(x*.77))
            for y in range(SKY-h,SKY):
                span(image,y,x,x+1,rgb('6fbe87' if (x+2*y)%5<2 else '459a79'))
        for x in range(W):
            # Bring each end of the panoramic strip down to the horizon.
            visible=min(1,min(x,W-1-x)/24)
            for y in range(90,SKY-int(55*visible)):
                span(image,y,x,x+1,rgb(sky))
    for j in range(8):
        colours=('00988e','00a790','00b495') if not desert else ('c7ad71','dbc68c','e4d091')
        span(image,SKY+j,0,W,rgb(colours[min(2,j//2)]))
    return bytes(image)


def bike(image,x,y,scale,lean):
    # Rear view in local pixel coordinates. Rotate about a point inside the
    # bike so the contact patch and helmet move to opposite sides on a turn.
    angle=lean*.58
    co,si=cos(angle),sin(angle)
    def part(colour,points):
        pts=[(x+scale*(u*co-(v+26)*si),y+scale*(u*si+(v+26)*co-26))
             for u,v in points]
        polygon(image,pts,colour)
    polygon(image,[(x-14*scale,y-3*scale),(x+4*scale,y-5*scale),
                   (x+16*scale,y-2*scale),(x+9*scale,y),(x-12*scale,y)],'454748')
    part('232629',[(-8,-29),(7,-29),(8,-8),(5,0),(-5,0),(-8,-7)])
    part('888d88',[(-5,-24),(-3,-13),(3,-12),(6,-22),(5,-10),(1,-6),(-4,-8)])
    part('183e77',[(-13,-49),(12,-49),(17,-37),(14,-19),(9,-16),(7,-32),(-8,-32),(-11,-16),(-16,-19),(-17,-37)])
    part('087ce0',[(-16,-41),(-9,-38),(-10,-24),(-14,-21)])
    part('ff6322',[(-12,-44),(12,-44),(10,-32),(6,-29),(-6,-29),(-11,-33)])
    part('41464b',[(-8,-32),(-5,-35),(5,-35),(9,-31),(5,-27),(-5,-27)])
    part('ef9300',[(-12,-28),(-10,-33),(-8,-30),(-9,-21),(-12,-22)])
    part('ecf1df',[(10,-34),(13,-33),(12,-22),(9,-21)])
    part('073685',[(-10,-63),(9,-63),(15,-56),(18,-46),(14,-39),(7,-41),(-8,-41),(-15,-39),(-18,-46),(-15,-56)])
    part('faf4dc',[(-8,-63),(8,-63),(14,-56),(17,-48),(14,-45),(8,-51),(8,-46),(-8,-46),(-8,-51),(-14,-44),(-17,-48),(-14,-56)])
    part('147ac6',[(-8,-45),(-5,-48),(5,-48),(9,-44),(7,-41),(-7,-41)])
    part('ed4409',[(-13,-57),(-8,-65),(8,-65),(13,-57),(8,-58),(0,-52),(-8,-59)])
    part('f9f1d7',[(-8,-66),(-8,-72),(-4,-77),(3,-78),(8,-73),(9,-67),(6,-63),(-5,-63)])
    part('e94506',[(-7,-70),(-4,-75),(3,-76),(6,-72),(8,-66),(5,-65),(2,-69),(-4,-70)])
    part('0059bf',[(-7,-66),(-5,-70),(1,-71),(6,-68),(5,-65),(-3,-66)])


def landmark(image,x,y,s,desert):
    def shape(col,coords):
        polygon(image,[(x+s*u,y+s*v) for u,v in coords],col)
    shape('89783f' if desert else '21765b',[(-8,0),(-3,-2),(7,-2),(9,0)])
    if desert:
        outline=[(-2,0),(-3,-14),(-7,-16),(-8,-26),(-6,-28),(-5,-19),
                 (-3,-18),(-2,-35),(1,-38),(3,-35),(3,-17),(5,-19),
                 (6,-30),(8,-29),(8,-16),(3,-12),(2,0)]
        shape('047823',outline)
        shape('50ae20',[(-2,-33),(0,-36),(0,-2),(-2,-1)])
    else:
        shape('80561f',[(-2,0),(-1,-23),(2,-23),(2,0)])
        shape('aba921',[(-3,-13),(-7,-22),(-8,-38),(-6,-48),(-2,-52),
                        (4,-50),(8,-41),(7,-24),(4,-16)])
        shape('e9cb22',[(-5,-23),(-6,-42),(-2,-49),(2,-48),(4,-42),
                        (0,-39),(3,-35),(-1,-29),(1,-24)])
        shape('797d1c',[(3,-17),(3,-25),(5,-30),(5,-41),(7,-38),(6,-24)])


PALETTES = {
    'Coast': ('555e60','626265','ad1809','f5f3df','faf9fc'),
    'Desert':('a7a699','b6b5a7','ad1809','ece8ce','faf6e6'),
}


def render(s,lane,theme,show_bike=True):
    camera=Camera(s,lane)
    background=scenery(theme)
    image=bytearray(background)
    # Pan the distant skyline with heading. A whole number of panorama turns
    # per lap keeps the finish line continuous.
    coast = theme=='Coast'
    period = (2 if coast else 1)*W
    shift = round(camera.heading*period/HEADING[LENGTH])%period
    clear_sky = rgb('1017ef')*W
    for y in range(90,SKY):
        start=3*y*W
        row=background[start:start+3*W]
        panorama = clear_sky+row if coast else row
        image[start:start+3*W]=(panorama+panorama)[3*shift:3*(shift+W)]
    road_a,road_b,red,cream,white=map(rgb,PALETTES[theme])
    for y,z in enumerate(DEPTHS,SKY):
        x,w,t=camera.section(z)
        # World-space paint travels towards the rider as distance advances.
        band=floor((camera.s+z)/STRIPE_LENGTH)
        stripe=red if band%2 else cream
        edge=KERB_RATIO*w
        line=line_width(w)
        span(image,y,x-w-edge,x+w+edge,stripe)
        span(image,y,x-w,x+w,road_b if band%2 else road_a)
        span(image,y,x-w,x-w+line,white)
        span(image,y,x+w-line,x+w,white)
        if theme=='Coast' and floor((camera.s+z)/(2*STRIPE_LENGTH))%2==0:
            span(image,y,x-line*.48,x+line*.48,white)
    # Objects are anchored in the same world and projection as the kerbs.
    spacing, offset = LANDMARK_SPACING, LANDMARK_OFFSET
    for i in range(floor((camera.s+FAR-offset)/spacing),floor((camera.s+NEAR-offset)/spacing),-1):
        z=i*spacing+offset-camera.s
        x,w,t=camera.section(z)
        scale=NEAR/z*(2.1 if theme=='Desert' else 3.55)
        landmark(image,x+landmark_offset(i,w),SKY+t*(H-1-SKY),scale,theme=='Desert')
    if show_bike:
        bike(image,W/2,H-1,1.,max(-1,min(1,curvature(camera.s+5)*.92)))
    return bytes(image)
