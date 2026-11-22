"""Inspect the floating-point road and its compiled Spectrum geometry side by side."""

import argparse
from math import floor
from time import monotonic
import tkinter as tk
from tkinter import ttk

from kerbs import FIRST, FOREGROUND, bands, projected, nearest
from road_model import view_at
from route import COURSES, DASH, TOP, project_view, projection

BLACK, BLUE = b"\0\0\0", b"\0\0\xc0"
WHITE, RED = b"\xff\xff\xff", b"\xc0\0\0"


def paint(row, left, right, colour):
    left = max(0,min(256,nearest(left)))
    right = max(left,min(256,nearest(right)))
    row[3*left:3*right] = colour*(right-left)


def render(course, pose, lane, phase):
    """Return native-resolution RGB pixels for the ideal and compiled views."""
    index = floor(pose)%256
    view = view_at(course,pose)
    rows = projection(index/4,course)[1]
    ideal = rows if pose==index else project_view((pose%256)/4,course)[1]
    crest, knots = bands(index,course)
    points = [projected(k,lane) for k in knots]
    panels = [bytearray(),bytearray()]
    for y in range(FIRST,DASH):
        for side,panel in enumerate(panels):
            section = (ideal if side==0 else rows)[y-TOP]
            z = section.z if section else None
            if z is None:
                panel.extend(BLUE*256)
                continue
            dark = (int(z*56)+int(phase))&16
            row = bytearray((BLUE if dark else BLACK)*256)
            if side==0:
                left,inner,right,outer = view.boundaries(y,lane)
                mark = view.section(y,lane)[0]
            else:
                k = (y-FIRST)//8-crest//8
                p,q = points[k:k+2]
                def edge(i, outside=False):
                    start = 2*(p[i]-64) + (p[3] if outside else 0)
                    end = 2*(q[i]-64) + (q[3] if outside else 0)
                    return start+((end-start)*(y%8)+4)//8
                left,inner,right,outer = edge(0),edge(0,True),edge(1),edge(1,True)
                mark = edge(2)
            for x1,x2 in ((left,inner),(right,outer)):
                paint(row,x1,x2,RED if dark else WHITE)
            if not dark and y>=FOREGROUND:
                paint(row,mark,mark+2,WHITE)
            panel.extend(row)
    return panels


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course',choices=COURSES,default='coast')
    args=parser.parse_args()
    root=tk.Tk()
    root.title('Spectrum Attribute Racer | Road reference')
    course=tk.StringVar(value=args.course)
    gear=tk.IntVar(value=2)
    lane=tk.DoubleVar(value=128)
    position=tk.DoubleVar(value=0)
    running=tk.BooleanVar(value=True)
    frames=ttk.Frame(root,padding=10)
    frames.pack()
    images=[]
    for column,title in enumerate(('Python reference','Spectrum geometry')):
        ttk.Label(frames,text=title).grid(row=0,column=column)
        image=ttk.Label(frames)
        image.grid(row=1,column=column,padx=2)
        images.append(image)
    controls=ttk.Frame(root,padding=8)
    controls.pack(fill='x')
    ttk.Checkbutton(controls,text='Run',variable=running).pack(side='left')
    ttk.OptionMenu(controls,course,args.course,*COURSES).pack(side='left')
    ttk.Label(controls,text='Gear').pack(side='left')
    ttk.OptionMenu(controls,gear,2,1,2,3,4).pack(side='left')
    for title,var,lo,hi in [('Track position',position,0,255.99),('Lane',lane,8,248)]:
        ttk.Label(controls,text=title).pack(side='left',padx=5)
        ttk.Scale(controls,variable=var,from_=lo,to=hi,length=210).pack(side='left')
    status=tk.StringVar()
    ttk.Label(root,textvariable=status).pack(pady=(0,6))
    keys=set()
    root.bind('<KeyPress>',lambda e:keys.add(e.keysym.lower()))
    root.bind('<KeyRelease>',lambda e:keys.discard(e.keysym.lower()))
    root.bind('<FocusOut>',lambda e:keys.clear())
    def pause(event):
        running.set(not running.get())
        return 'break'
    root.bind('<space>',pause)
    last=monotonic()
    phase=0.0
    def draw():
        nonlocal last,phase
        now=monotonic()
        dt=min(.1,now-last)
        last=now
        direction=int('p' in keys)-int('o' in keys)
        if direction:
            lane.set(max(8,min(248,lane.get()+direction*50*dt)))
        if running.get():
            advance=gear.get()*50*dt
            phase=(phase+advance)%32
            position.set((position.get()+advance/14)%256)
        current=position.get()
        current_lane=nearest(lane.get())
        status.set(f'Course position {current:6.2f} / 256     Lane {current_lane:3} / 248     '
                   'Space pauses     O / P move across the track')
        panels=render(course.get(),current,current_lane,phase)
        for label,data in zip(images,panels):
            ppm=b'P6\n256 120\n255\n'+data
            label.image=tk.PhotoImage(data=ppm,format='PPM').zoom(2)
            label.configure(image=label.image)
        root.after(16,draw)
    draw()
    root.mainloop()


if __name__=='__main__':
    main()
