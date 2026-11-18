#!/usr/bin/env python3
"""Shorten the pauses between words, then speed the speech up without changing pitch.

Reads a voice recording and its word timestamps. Writes the tightened audio and
a new word-timestamp file that matches it, so captions and retiming made from
the new file stay in sync.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

from common import load_words, probe_duration

LEAD = 0.12   # most silence kept before the first word, seconds
PAD = 0.04    # extra air kept after a word whose pause was cut, so consonants are not clipped
TAIL = 0.30   # most audio kept after the last word, seconds
FADE = 200    # samples of fade-out at each cut, so the cut does not click


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio", help="input voice recording (any format libsndfile reads: wav, flac, ogg)")
    p.add_argument("words", help="word-timestamp JSON for the input audio")
    p.add_argument("out_audio", help="output audio path, for example tight.wav")
    p.add_argument("out_words", help="output word-timestamp JSON, retimed to the output audio")
    p.add_argument("--tempo", type=float, default=1.12,
                   help="speed factor applied after pauses are cut, pitch preserved (default: 1.12)")
    p.add_argument("--max-gap", type=float, default=0.18,
                   help="longest pause kept between two words, in seconds (default: 0.18)")
    a = p.parse_args()
    if a.tempo <= 0:
        p.error("--tempo must be positive")

    audio, sr = sf.read(a.audio)
    words, duration = load_words(a.words)
    src_dur = len(audio) / sr
    if duration is None:
        duration = src_dur

    pieces, new_words, t = [], [], 0.0
    lead = min(words[0]["start"], LEAD)
    pieces.append(audio[int((words[0]["start"] - lead) * sr):int(words[0]["start"] * sr)])
    t += lead
    for i, w in enumerate(words):
        start = w["start"]
        nxt = words[i + 1]["start"] if i + 1 < len(words) else min(duration, w["end"] + TAIL)
        gap = nxt - w["end"]
        keep_end = w["end"] + (gap if gap <= a.max_gap else a.max_gap + PAD)
        keep_end = min(keep_end, nxt)
        seg = audio[int(start * sr):int(keep_end * sr)]
        if keep_end < nxt and len(seg) > FADE:
            seg = seg.copy()
            ramp = np.linspace(1, 0, FADE)
            seg[-FADE:] *= ramp if seg.ndim == 1 else ramp[:, None]
        new_words.append({"word": w["word"], "start": t, "end": t + (w["end"] - start)})
        pieces.append(seg)
        t += len(seg) / sr

    for path in (a.out_audio, a.out_words):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        sf.write(tmp, np.concatenate(pieces), sr)
        # atempo is a time-stretch: it changes speed and leaves pitch alone
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-filter:a", f"atempo={a.tempo}",
                        a.out_audio], check=True)
    finally:
        os.remove(tmp)

    for w in new_words:
        w["start"] = round(w["start"] / a.tempo, 3)
        w["end"] = round(w["end"] / a.tempo, 3)
    out_dur = probe_duration(a.out_audio)
    with open(a.out_words, "w", encoding="utf-8") as f:
        json.dump({"duration": out_dur, "tempo": a.tempo, "max_gap": a.max_gap, "words": new_words}, f, indent=1)
    print(f"{src_dur:.2f}s -> {out_dur:.2f}s ({len(new_words)} words)")


if __name__ == "__main__":
    sys.exit(main())
