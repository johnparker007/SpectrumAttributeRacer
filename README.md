# Spectrum Attribute Racer

Two motorcycle circuits for the ZX Spectrum 128K. Countersteer through bends, watch for riders coming back into view over crests, and pass on either side. Contact or running wide drops the bike to first gear. Each clean overtake adds one to the dashboard counter.

| Circuit | Ride | Emulator capture |
| --- | --- | --- |
| [Coast Run](play/coast-run.tap) | Climb the headland past the beacons, drop into a hooked ravine, then cross the low causeway before the paired summit bends. | [Watch a lap](docs/coast-run.gif) |
| [Ridge Run](play/ridge-run.tap) | Follow the pines into a steep switchback climb. The road disappears over a blind summit, opens into a downhill S-bend and climbs a second ridge. | [Watch a lap](docs/ridge-run.gif) |

![Ridge Run riding over the mountain pass in ZEsarUX](docs/ridge-run.gif)

## Play

Open either TAP with tape autoload on a 128K Spectrum, +2 or +2A emulator. Enable mid-frame shadow-screen switching (Real Video in ZEsarUX). Both rides start in second gear.

| Keys | Action |
| --- | --- |
| O / P | Steer and lean left / right |
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

* Each circuit has a closed profile of elevation and signed curvature. For each of 64 rider positions, the compiler projects road sections from near to far. Each scanline takes its nearest visible surface. A crest can hide a whole valley, the lower half of a sign or an approaching rider. The distance of the visible road also sets the stripe spacing and kerb width.
* Both screen banks hold the road bitmap. The bright bands use green grass, white kerbs and black asphalt with white lane dashes. The alternating dim bands use normal green, red, blue, red and green across the screen. The dashes blend into the blue asphalt. The kerbs reach 36 pixels at the tyres. Their edges can move up to five pixels towards an attribute boundary to reduce colour clash.
* The Z80 selects a screen in the horizontal border before each of 128 scanlines. Sky lines select the scenic background. Road lines look up the current depth plus a phase that advances with gear at 50 Hz.
* The rider saves the track underneath its 24×24 masked bitmap. Once the beam passes the bike, the game restores the background, reads the keyboard and stages up to 29 changed tiles. It writes six behind the beam and 23 before active display after the next IM 2 interrupt. Each batch also refreshes the corresponding scanline depths. Common tile graphics occupy fixed RAM, and five pageable banks hold the course updates.

Edit the course profiles and projection in [tools/route.py](tools/route.py), scenery and tile conversion in [tools/course.py](tools/course.py), and the running game in [src/racer.asm](src/racer.asm).

## Timing checks

The verifier boots both release tapes through the ROM loader and compares real-video pixels with the expected two-screen composite. Separate snapshot runs check the terrain around a full lap, keyboard controls, both overtakes, contact penalties and the time remaining before the next interrupt.

Measured with SjASMPlus 1.20.2 and ZEsarUX 10.3 on the 128K, grey +2 and +2A emulations. The first road latch falls at T-states 23,452–23,455 relative to frame start. Successive road latches are 228 T-states apart.
