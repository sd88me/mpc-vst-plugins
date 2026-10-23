# Maschine Group

An MPC instrument that opens a Native Instruments Maschine 2 group (`.mxgrp`) and plays it on the pads.

A group is sixteen sounds. Each sound is either a sample (a path into the library's `Samples/` folder) or a Maschine drumsynth (Kick, Snare, Hihat, Tom, Perc, Cymbal), plus the insert effects saved on that sound. Effects that match the stock MPC set are played in the instrument:

| Maschine device | Played as |
|---|---|
| Chorus | chorus |
| Flanger, Phaser | flanger / phaser |
| BeatDelay, GrainDelay | delay |
| Metaverb, PlateReverb, Iceverb | reverb |
| Saturator | saturator |
| Compressor | compressor |
| Maximizer | maximizer |
| Limiter | limiter |
| Gate | gate |
| Lo-Fi | lo-fi |

The MPC host cannot load one plugin from inside another, so these are the same kinds of effects as AIR's stock plugs, reading the knobs stored in the group. They are not a clone of the Maschine devices. Anything else (Freq Shifter, Reflex, Resochord, Grain Stretch, FM, …) is listed on the pad with a `*` and left out of the audio. Drumsynth engines are a tune/decay sketch of the Maschine one, not the original.

Pads follow the 4×4 grid. Each pad is tinted from its name: a kick is red, a snare orange, a hat, cymbal or shaker lilac, percussion blue, a tom green, and any other name yellow. With Pad Perform set to chromatic C, the bottom-left pad is MIDI note 48 and each row is the next four notes, so the pad is `note % 16` (note 48 is pad 1, bottom left, the same pad as note 0). Shifting the octave by 12 moves that corner off a multiple of 16 and the rows rotate. Tapping a pad on the plugin screen retriggers it, including while the sample is still playing. A closed hat chokes an open hat when the names say so.

The first screen is three columns: a list of groups on the left, the pads in the middle, and the pattern list on the right. Tapping a name loads that group. The first pattern cell is Empty. Switching groups keeps Empty if that is what was selected; if any other pattern was selected, the new group starts on its first pattern. Level and FX stay on the Q-Links.

The Patterns tab shows the selected pattern as sixteen time slices across the sixteen pads, and lists the patterns below it in large cells. A hit is a small rounded bar; a lower velocity is drawn more transparent. Host play starts the selected pattern at the host tempo, 960 ticks per quarter, and host stop ends it. While it plays, the same notes are sent on MIDI channel 1 (note 48 is pad 1, a 16th-note long) through an ALSA port named Maschine Group / MIDI Out. MPC connects that port to track input by itself. Arm the track whose MIDI input is that port and press Rec: the notes are written into the clip, the same way an arpeggiator can be recorded. Notes that come back into this plugin are ignored, so the pattern is not played twice.

The library has to sit next to the group: the `.mxgrp` lives under `Groups/`, and `Samples/` is a few folders up. A wav with the same filename in the group's own folder is used too, as is the path with `Samples/` left off (`One Shots/…` next to a parent of the group). Copy the library onto the card and pick that folder on Setup, or drop groups into the plugin folder's `groups/` directory. The list is only those two places, up to 1023 groups. A leftover `.mxgrp` somewhere else on the card is left alone.

The Setup tab shows the library path, Change folder / Use folder, and Refresh. A press lights the button orange. Change folder opens the folder list; Use folder is a separate button, so the same press does not close it again. The help text is how to copy Native Instruments `Groups/` and `Samples/` from "Maschine 2 Factory Library" onto the card. Refresh scans again and writes `Refreshing...` then `Found N groups, M samples` under the instructions. Change folder walks the card and uses the open directory as the only place to scan; Use folder on the list of places leaves the previous choice.

```
../../tools/test_port.sh vst/vst.json
../../tools/build_port.sh vst/vst.json
```
