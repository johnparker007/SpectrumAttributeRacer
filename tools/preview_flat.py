"""Interactive flat-road study. Launch with Preview-Road.bat on Windows."""

from time import monotonic
import tkinter as tk
from tkinter import ttk

from flat_road import H, LENGTH, SHOTS, W, render


def main():
    root=tk.Tk()
    root.title('Hang-On | Flat road study')
    root.resizable(False,False)
    panel=ttk.Frame(root,padding=10)
    panel.pack()
    screen=ttk.Label(panel)
    screen.pack()
    scenes=ttk.Frame(panel)
    scenes.pack(fill='x',pady=(8,4))
    selected=tk.IntVar(value=0)
    position=tk.DoubleVar()
    lane=tk.DoubleVar()
    speed=tk.DoubleVar(value=28)
    running=tk.BooleanVar(value=False)
    rider=tk.BooleanVar(value=True)
    keys=set()

    def choose(i):
        _,s,x,_=SHOTS[i]
        selected.set(i)
        position.set(s)
        lane.set(x)
        running.set(False)

    for i,shot in enumerate(SHOTS):
        ttk.Radiobutton(scenes,text=shot[0],variable=selected,value=i,
                        command=lambda i=i:choose(i)).pack(side='left',padx=4)
        root.bind(str(i+1),lambda event,i=i:choose(i))
    controls=ttk.Frame(panel)
    controls.pack(fill='x')
    ttk.Checkbutton(controls,text='Ride',variable=running).pack(side='left')
    ttk.Checkbutton(controls,text='Rider',variable=rider).pack(side='left')
    for name,var,lo,hi,size in [('Speed',speed,0,65,100),('Lane',lane,-1.2,1.2,105),
                                ('Lap',position,0,LENGTH-.001,170)]:
        ttk.Label(controls,text=name).pack(side='left',padx=(8,2))
        ttk.Scale(controls,variable=var,from_=lo,to=hi,length=size).pack(side='left')
    ttk.Label(panel,text='1–4 select a view     Space rides or pauses     O / P or ← / → move across the road').pack(pady=(7,0))
    def toggle(event):
        running.set(not running.get())
        return 'break'
    root.bind('<space>',toggle)
    def down(event):
        keys.add(event.keysym.lower())
    root.bind('<KeyPress>',down,add='+')
    root.bind('<KeyRelease>',lambda event:keys.discard(event.keysym.lower()))
    root.bind('<FocusOut>',lambda event:keys.clear())
    last=monotonic()
    previous=None
    def draw():
        nonlocal last,previous
        now=monotonic()
        dt=min(.1,now-last)
        last=now
        direction=int(bool(keys & {'right','p'}))-int(bool(keys & {'left','o'}))
        if direction:
            lane.set(max(-1.2,min(1.2,lane.get()+dt*direction*.48)))
        if running.get():
            position.set((position.get()+dt*speed.get())%LENGTH)
        state=position.get(),lane.get(),SHOTS[selected.get()][3],rider.get()
        if state!=previous:
            pixels=render(*state)
            ppm=f'P6\n{W} {H}\n255\n'.encode()+pixels
            screen.image=tk.PhotoImage(data=ppm,format='PPM').zoom(2)
            screen.configure(image=screen.image)
            previous=state
        root.after(max(1,round(1000*(1/60-(monotonic()-now)))),draw)
    choose(0)
    draw()
    root.mainloop()


if __name__=='__main__':
    main()
