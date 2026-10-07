# Boris Granular (MPC VST effect)

Real-time granular insert effect for MPC OS / Force: incoming audio goes into a 10 s buffer and up to 24 overlapping
grains replay it with per-grain random size, delay, pitch, direction, volume and pan. DSP from
[boris-move](https://github.com/filliformes/boris-move) (plain C), itself a port of
[Boris Granular Station](https://github.com/glesdora/boris-granular-station) by Alessandro Gaiba. The skin follows Boris
Granular Station's own GUI: black plate, deep-purple panels, aliceblue ink, lavender accent, TEMPO / SIZE / PITCH SHIFT /
ENVELOPE across the top.

![skin preview](docs/skin-preview.png)

## Controls
One page, two Q-Link sets: **GRAIN** (density, size, position, pitch, feedback, pan width, freeze, dry/wet, envelope,
drift, rdm size/delay/shift, reverse, rdm vol, chance) and **TEMPO** (sync, division, rhythm, input, mute, voices).
Sync locks grain triggers to MPC's tempo (division 1/16 to 4/1, normal / dotted / triplet).

## Build
`./build.sh` (Docker; `tools/build_port.sh`). Offline test: `tools/test_port.sh ports/boris-granular/vst/vst.json`.

## License
GPL-3.0 (`LICENSE`), as the upstream projects. See `src/VENDORED.md`.
