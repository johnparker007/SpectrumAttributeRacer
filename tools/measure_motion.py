"""Measure foreground kerb motion directly in consecutive 50 Hz emulator images."""

import argparse
import json
from pathlib import Path
from statistics import median
import tempfile

from build import BUILD, executable
from verify import WIDTH, HEIGHT, fixture, run, symbols_for


def right_kerb(row):
    # The right kerb stays clear of the centred rider in this measurement area.
    # Red and white are its two beam-selected colours. Exclude narrow lane
    # paint, roadside objects and spans clipped at the right edge.
    spans = []
    start = None
    for x in range(145, 256):
        paint = row[3*x:3*x+3] in (b"\x00\x00\xc0", b"\xff\xff\xff")
        if paint and start is None:
            start = x
        elif not paint and start is not None:
            if start > 145 and 10 <= x-start <= 21:
                spans.append(start)
            start = None
    return spans[0] if len(spans) == 1 else None


def analyse(raw, frame_count):
    series = []
    with raw.open("rb") as stream:
        while frame := stream.read(WIDTH*HEIGHT*3):
            if len(frame) != WIDTH*HEIGHT*3:
                raise ValueError("Incomplete capture")
            edges = []
            for y in range(136, 167, 2):
                start = 3*((y+56)*WIDTH+48)
                edges.append(right_kerb(frame[start:start+768]))
            if not series and sum(x is not None for x in edges) < 8:
                continue
            series.append(edges)
            if len(series) == frame_count:
                break
    if len(series) != frame_count:
        raise ValueError(f"Captured {len(series)} of {frame_count} requested frames")
    changes, intervals, representative = [], [], []
    comparisons = 0
    moving_frames = set()
    for row, points in enumerate(zip(*series)):
        previous = changed_at = None
        for i, point in enumerate(points):
            if previous is not None and point is not None:
                comparisons += 1
                if point != previous:
                    moving_frames.add(i)
                    changes.append(abs(point-previous))
                    if changed_at is not None:
                        intervals.append(i-changed_at)
                    changed_at = i
            elif point is None:
                changed_at = None
            if row == 8 and point is not None and previous != point:
                representative.append((i, point))
            previous = point
    return {"frames":len(series), "row_comparisons":comparisons, "moves":len(changes),
            "moving_display_frames":len(moving_frames),
            "median_step_px":median(changes) if changes else None,
            "max_step_px":max(changes, default=0),
            "median_frames_between_moves":median(intervals) if intervals else None,
            "row_152":representative}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=BUILD, help="Course build root")
    parser.add_argument("--course", choices=("coast", "ridge"), required=True)
    parser.add_argument("--input", choices=("none", "right"), required=True)
    parser.add_argument("--emulator", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    emulator = executable(args.emulator, "ZESARUX", "zesarux",
                          "Dropbox/ZX_Coding/ZEsarUX_win-10.3/zesarux.exe")
    out = args.root.resolve() if args.course == "coast" else args.root.resolve()/"ridge"
    # The hands-off fixtures enter bends that sweep steadily across the
    # foreground. Steering fixtures leave the right kerb visible as P moves it.
    poses = {"coast": {"right": 239, "none": 190},
             "ridge": {"right": 182, "none": 153}}
    pose = poses[args.course][args.input]
    with tempfile.TemporaryDirectory(prefix="racer-kerb-motion-") as tmp:
        folder = Path(tmp)
        source = fixture(folder, "start", out/(args.course+"-run.sna"), symbols_for(out),
                         pose=pose, lane=128, displayLane=128, gear=4)
        raw = folder/"frames.raw"
        opts = ["--vofilefps","50","--frameskip","0","--disable-autoframeskip","--vofile",raw]
        if args.input == "right":
            spool = folder/"steering.txt"
            spool.write_bytes(b"p"*400)
            opts += ["--keyboardspoolfile",spool,"--keyboardspoolfile-play",
                     "--keyboardspoolfile-keylength","1","--keyboardspoolfile-nodelay"]
        run(emulator, source, "128k", 8, opts)
        metrics = analyse(raw, 84 if args.input == "right" else 160)
    result = {"course":args.course,"input":args.input,"initial_pose":pose,**metrics}
    print(json.dumps(result))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2)+"\n")


if __name__ == "__main__":
    main()
