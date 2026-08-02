# Ambience bed — sources and licence

The eight stems in this directory come from the ambient-mixer atmosphere
[Air Traffic Control with Plane](https://vehicles.ambient-mixer.com/air-traffic-control-with-plane)
(template 444055), retrieved 2026-08-02.

The atmosphere is published under the
**[Creative Commons Sampling Plus 1.0 License](https://creativecommons.org/licenses/sampling+/1.0/)**,
and the source page credits every sample it uses. Those credits are reproduced
below and, more importantly, are carried as data in `ambience.json` — one
`credit` field per channel plus a top-level `license` object — so the app can
display them rather than relying on this file being read.

## Credits

| Stem | Credited to |
|---|---|
| `1-ticking-clock.mp3` | Mariusz Jasionowicz — www.raresound.co.uk |
| `2-neon-lights-hum.mp3` | kbnevel, via freesound.org |
| `3-distant-jet-3.mp3` | Gigarama MAKS 2019 |
| `4-server-room-computer-lab.mp3` | BugInTheSYS, via freesound.org |
| `5-water-pump-engine.mp3` | bansemer, via freesound.org |
| `6-huge-slow-metal-fan.mp3` | SoundDogs |
| `7-distant-jet-2.mp3` | Gigarama MAKS 2019 |
| `8-distant-jet-1.mp3` | Gigarama MAKS 2019 |

Regenerate this list with `uv run --project . python tools/fetch_ambience.py`,
which scrapes the licence and the credits from the source page rather than
trusting a hard-coded copy. If the page ever stops declaring a licence, or
stops crediting a stem, the tool raises instead of writing a manifest — the
assets must never end up committed without provenance.

## Open questions before public distribution

squelch is currently a personal tool, and for personal use the terms above are
satisfied by attribution. Three things need resolving before it is distributed
or used commercially. They are recorded here rather than in an issue tracker
because whoever ships this will be looking at this file.

1. **CC Sampling Plus 1.0 is a retired licence.** Creative Commons deprecated
   it in 2011 and no longer recommends it. It permits sampling and
   noncommercial sharing of the whole work, but it specifically forbids use in
   advertising. It is a valid grant — it is simply not one of the six modern
   licences, so its compatibility with anything squelch might later be
   bundled into has to be reasoned about case by case rather than assumed.

2. **"Huge slow metal fan by SoundDogs" needs checking.** SoundDogs is a
   commercial sound-effects library that licenses per-seat, not under Creative
   Commons. A CC-licensed atmosphere containing a SoundDogs sample is a claim
   the uploader made, not one SoundDogs is bound by. This stem is the most
   likely to need replacing.

3. **The freesound-sourced stems have their own upstream terms.** Freesound
   samples are individually licensed — CC0, CC-BY, or CC-BY-NC — and the
   sample's own licence governs regardless of what the atmosphere is published
   under. The three affected stems (`kbnevel`, `BugInTheSYS`, `bansemer`)
   should be traced to their freesound pages and their actual licences
   recorded here. If a licence cannot be established for a stem, replace the
   stem rather than shipping it.

Note that the durations here are short and every stem is a loop or a
background layer, so replacing any single one is cheap: drop a new file into
the ambient-mixer template, re-run the fetch tool, and the manifest follows.
