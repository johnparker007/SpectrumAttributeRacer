# Spectrum Attribute Racer

Two motorcycle circuits for the ZX Spectrum 128K. The camera follows the bike from behind. Steer to move the road under the tyres, watch for riders coming back into view over crests, and pass on either side. Contact or running wide drops the bike to first gear. Each clean overtake adds one to the dashboard counter.

| Circuit | Ride | Emulator capture |
| --- | --- | --- |
| [Coast Run](play/coast-run.tap) | Climb the headland past the beacons, drop into a hooked ravine, then cross the low causeway before the paired summit bends. | [Watch a bend](docs/coast-run.gif) |
| [Ridge Run](play/ridge-run.tap) | Follow the pines into a steep switchback climb. The road disappears over a blind summit, opens into a downhill S-bend and climbs a second ridge. | [Watch a bend](docs/ridge-run.gif) |

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

* Each circuit has 256 camera positions around a closed elevation and curvature profile. A crest can hide a valley or a rider. The compiler smooths the reveal across neighbouring positions, including the end of the lap.
* O and P move the road beneath the rider. The two kerbs and the dashed centreline follow the same camera. Adjacent eight-scanline sections share their endpoints. Between those endpoints the renderer tapers the paint on each individual scanline. Foreground positions have two-pixel precision and distant positions have four-pixel precision. [Compare the same bends in the previous and current builds](docs/kerb-comparison.png)
* Bright bands show white paint on black. Normal-intensity bands show red kerbs on blue. A single two-pixel white centreline appears in the bright foreground bands. Road paint has priority where a roadside object shares its colour cell.
* The Z80 prepares a complete camera position in spare RAM as the previous view stays on screen. It identifies the changed bitmap blocks and colour cells, then writes them to both screen banks while those rows are outside the beam. The depth profile changes with the geometry. Every displayed scanline therefore belongs to the same camera position.
* The colour bands scroll at 50 Hz. Camera positions take longer to prepare. In the recorded steering laps the road advances about 3.5 positions per second, with the bike held near the middle of the screen.

Edit the elevation and curvature in [tools/route.py](tools/route.py), the projected kerbs in [tools/kerbs.py](tools/kerbs.py), the compiled paint shapes in [tools/strokes.py](tools/strokes.py), and the native renderer in [src/racer.asm](src/racer.asm).

## Timing and picture checks

The verifier steers through a full lap of each course in ZEsarUX and captures every 50 Hz display frame. It independently draws the expected kerbs, centreline, roadside objects and rider for the camera and stripe phase that the game published. It compares every pixel of all 120 road scanlines in sequence, including frames held between camera updates. It runs a second full lap from the playable TAP through the ROM loader, using the default starting gear and scripted steering.

An offline check covers all 256 positions and all 241 steering settings on each circuit. It decodes the compiled kerb and centreline shapes and checks the paint on each scanline. With steering held constant, an endpoint can move at most four pixels between consecutive course positions. The emulator checks the keyboard, overtakes, contact, interrupt deadlines and 228-T-state spacing between screen selections on the 128K, grey +2 and +2A.
