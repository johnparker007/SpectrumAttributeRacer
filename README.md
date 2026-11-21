# Spectrum Attribute Racer

Two motorcycle circuits for the ZX Spectrum 128K. The camera follows the bike from behind. Steer to move the road under the tyres, watch for riders coming back into view over crests, and pass on either side. Contact or running wide drops the bike to first gear. Each clean overtake adds one to the dashboard counter.

| Circuit | Ride | Emulator capture |
| --- | --- | --- |
| [Coast Run](play/coast-run.tap) | Climb the headland past the beacons, drop into a hooked ravine, then cross the low causeway before the paired summit bends. | [Watch a lap](docs/coast-run.gif) |
| [Ridge Run](play/ridge-run.tap) | Follow the pines into a steep switchback climb. The road disappears over a blind summit, opens into a downhill S-bend and climbs a second ridge. | [Watch a lap](docs/ridge-run.gif) |

![Ridge Run riding over the mountain pass in ZEsarUX](docs/ridge-run.gif)

## Play

Open either TAP with tape autoload on a 128K Spectrum, +2 or +2A emulator. Enable mid-frame shadow-screen switching (Real Video in ZEsarUX). Both rides start in second gear.

| Keys | Action |
| --- | --- |
| O / P | Steer left / right. The bike leans near the centre and the foreground road shifts underneath it. |
| Q / A | Shift up / down through four gears |

## Build and test

Run these commands from the checkout with Python 3.10 or later. The build uses SjASMPlus. The headless tests use ZEsarUX. On the original Windows development machine both commands find the same installations as the shmup.

```powershell
python tools/build.py
python tools/verify.py
```

Both commands accept `--course coast` or `--course ridge`. The verifier also accepts `--model 128k`, `--model P2` or `--model P2A41`. Set `SJASMPLUS` and `ZESARUX` to the tool paths if needed, or pass `--assembler <path>` and `--emulator <path>` respectively. The build writes a TAP, an instant-start SNA and a symbol map for each circuit in `build/` (Coast Run) and `build/ridge/` (Ridge Run). On Windows, `Build-TAP.bat` also rebuilds both.

## How the road works

The starting point was the shmup's Ringo-8/Blokius renderer. An interrupt synchronises the frame, and scheduled writes to `#7FFD` let the ULA fetch colours from either screen. The racer has its own raster loop, course compiler and sprite compositor. [Shmup source and timing measurements](https://github.com/johnparker007/SpectrumAttributeShmup/blob/b9f0878/docs/timing-baseline.md)

* Each circuit has a closed elevation and curvature profile. The compiler projects 256 camera positions around the lap at quarter-station intervals. At each position a scanline takes the nearest visible ground. A crest can hide a valley, a sign or an approaching rider. A gentle angular compression at the edges of the field of view softens the reveal of distant switchbacks.
* O and P move the camera across the road, and curvature pushes it outwards over successive quarter-steps. The bike stays near x=124. The lane dividers and kerbs share the same steering projection. Roadside scenery scrolls according to depth.
* In the foreground, each painted strip joins shared endpoints on a four-pixel horizontal grid. The compiler fits the whole eight-scanline stroke into the tile set. The two-pixel lane dividers and the common kerb diagonals are rasterised at single-scanline resolution. Steeper kerbs can use a coarser slope. The native renderer selects a short Z80 routine for each stroke, clips it at the screen edge and overlays the roadside objects. [Compare the same moving bend in both builds](docs/kerb-comparison.png)
* Bright bands show white kerbs and lane dividers on black. Normal-intensity bands show red kerbs on blue and hide the dividers. Foreground kerbs use widths of 8, 12 and 16 pixels. The distant road keeps its projected silhouette over crests, and the lane paint starts where the projected road is at least 40 pixels wide.
* The 50 Hz raster chooses a screen in the horizontal border before each of 128 scanlines. Between switches it compares 256 visible tiles from one half of the road with the requested view. It alternates halves each frame and resumes at the first unprocessed area when a large bend or a steering input changes many tiles. A fixed batch is drawn before the next road raster, with additional tiles drawn behind the beam when the course data is already current.
* Each quarter-step stores changes to the distant tile map, foreground kerb endpoints, roadside tiles and scanline depths. In second gear the road takes a new position every seven display frames. In fourth it alternates between three and four frames. Striping, steering input and rider lean update every display frame.

Edit the course profiles and projection in [tools/route.py](tools/route.py), scenery and tile conversion in [tools/course.py](tools/course.py), and the running game in [src/racer.asm](src/racer.asm).

## Timing checks

The verifier boots both release tapes through the ROM loader and checks the real-video image. A separate top-gear run compares the moving picture with the expected camera, rider, road and dashboard throughout a lap, including partially redrawn bends. Parked left- and right-lane fixtures check the amount and direction of foreground and distant movement against captured pixels. The verifier checks every compiled paint stroke for holes and measures complete lane and kerb runs in the moving emulator capture. A separate geometry check measures both visible kerbs immediately above and below each foreground band boundary at five steering positions. It compares the measured step with the slope of the projected road. Keyboard, overtakes, contact and interrupt deadlines are checked separately.

The program measures its drawing time against the ULA interrupt at startup to locate the horizontal border on each machine. Successive road latches are 228 T-states apart on the 128K, grey +2 and +2A in ZEsarUX 10.3.
