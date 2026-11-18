#!/usr/bin/env python3
"""Retime a screen recording so each on-screen step lasts as long as its voiceover line.

A cue file lists the steps in narration order. Each step names the phrase that
starts it in the voiceover and the part of the recording to show. The step is
sped up or slowed down to fill the time until the next step's phrase is spoken.
The recording's own audio is dropped and the voiceover becomes the soundtrack.

Cue file (JSON), a list of segments in narration order:

  [
    {"at": 0,                    "in": 0.0,  "out": 2.0},
    {"cue": "open the settings", "in": 2.0,  "out": 4.6},
    {"cue": "and you are done",  "in": 12.0, "out": 12.4, "zoom": true, "after": 8}
  ]

  cue    phrase that starts the segment, matched against the word timestamps
         (case and the punctuation , . ! ? are ignored)
  at     start time in seconds, in place of "cue" (use 0 for the opening segment)
  after  only match the phrase at or after this many seconds (for repeated phrases)
  in/out part of the recording to show, in seconds on the recording's timeline
  zoom   true adds a slow push-in, for a short clip that is held for a long line
"""
import argparse
import json
import subprocess
import sys

from common import load_words, probe_size

STRIP = ",.!?"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", help="screen recording (its audio is ignored)")
    p.add_argument("voice", help="voiceover audio")
    p.add_argument("words", help="word-timestamp JSON for the voiceover")
    p.add_argument("cues", help="cue file (JSON), see above")
    p.add_argument("out", help="output video, for example out.mp4")
    p.add_argument("--lead", type=float, default=0.12,
                   help="seconds the picture changes before the cue word is spoken (default: 0.12)")
    p.add_argument("--tail", type=float, default=0.6,
                   help="seconds of picture and silence after the voiceover ends (default: 0.6)")
    p.add_argument("--fps", type=int, default=30, help="output frame rate (default: 30)")
    p.add_argument("--zoom-amount", type=float, default=0.10,
                   help="how far a zoom segment pushes in by its end, 0.10 is 10 percent (default: 0.10)")
    p.add_argument("--crf", type=int, default=18, help="x264 quality, lower is better (default: 18)")
    p.add_argument("--preset", default="slow", help="x264 preset (default: slow)")
    a = p.parse_args()

    words, dur = load_words(a.words)
    if dur is None:
        dur = words[-1]["end"]
    W = [w["word"].lower().strip(STRIP) for w in words]
    S = [w["start"] for w in words]

    def at(phrase, after=0.0):
        """Start time of the first occurrence of a phrase at or after `after` seconds."""
        seq = [x.lower().strip(STRIP) for x in phrase.split()]
        for i in range(len(W) - len(seq) + 1):
            if S[i] >= after and W[i:i + len(seq)] == seq:
                return S[i]
        sys.exit(f"cue not found in the words file: {phrase!r}" + (f" (after {after}s)" if after else ""))

    with open(a.cues, encoding="utf-8") as f:
        cues = json.load(f)
    if isinstance(cues, dict):
        cues = cues["segments"]
    if not cues:
        sys.exit("the cue file has no segments")

    segs = []  # (voiceover start, source in, source out, zoom)
    for n, c in enumerate(cues, 1):
        if "in" not in c or "out" not in c or c["out"] <= c["in"]:
            sys.exit(f"segment {n}: needs \"in\" and \"out\" with out greater than in")
        if "cue" in c:
            t0 = max(0.0, at(c["cue"], float(c.get("after", 0))) - a.lead)
        elif "at" in c:
            t0 = float(c["at"])
        else:
            sys.exit(f"segment {n}: needs \"cue\" or \"at\"")
        if segs and t0 <= segs[-1][0]:
            sys.exit(f"segment {n} starts at {t0:.2f}s, not after the previous segment ({segs[-1][0]:.2f}s); "
                     "segments must be in narration order")
        segs.append((t0, float(c["in"]), float(c["out"]), bool(c.get("zoom", False))))

    end = dur + a.tail
    if end <= segs[-1][0]:
        sys.exit("the last segment starts after the voiceover ends")
    sw, sh = probe_size(a.video)
    w, h = sw // 2 * 2, sh // 2 * 2

    filters, labels = [], []
    for i, (t0, src_in, src_out, zoom) in enumerate(segs):
        t1 = segs[i + 1][0] if i + 1 < len(segs) else end
        speed = (src_out - src_in) / (t1 - t0)
        f = f"[0:v]trim={src_in}:{src_out},setpts=(PTS-STARTPTS)/{speed:.5f},fps={a.fps}"
        if zoom:
            # zoompan works on whole pixels, so zoom on a 2x upscale to keep the push-in smooth
            n = max(1, round((t1 - t0) * a.fps))
            f += (f",scale={w * 2}:{h * 2},zoompan=z='1+{a.zoom_amount}*on/{n}':x='iw/2-iw/zoom/2'"
                  f":y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={a.fps}")
        elif (w, h) != (sw, sh):
            f += f",scale={w}:{h}"
        f += f",trim=duration={t1 - t0:.4f},setpts=PTS-STARTPTS,setsar=1[v{i}]"
        filters.append(f)
        labels.append(f"[v{i}]")
        print(f"{t0:6.2f}-{t1:6.2f}  src {src_in:6.2f}-{src_out:6.2f}  x{speed:.2f}{'  zoom' if zoom else ''}")

    filters.append(f"{''.join(labels)}concat=n={len(segs)}:v=1:a=0[v]")
    filters.append(f"[1:a]apad=whole_dur={end},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-i", a.voice,
                    "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-t", f"{end}", "-movflags", "+faststart", a.out], check=True)
    print(f"wrote {a.out} ({end:.2f}s, {len(segs)} segments)")


if __name__ == "__main__":
    sys.exit(main())
