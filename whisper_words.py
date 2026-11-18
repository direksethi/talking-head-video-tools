#!/usr/bin/env python3
"""Convert a Whisper word-timestamp transcript to the words.json format the tools read.

Reads the JSON written by openai-whisper with word timestamps enabled, or any
transcript with the same layout (WhisperX uses it too):

  {"segments": [{"words": [{"word": " Hello", "start": 0.10, "end": 0.42}, ...]}, ...]}

Writes {"duration": seconds, "words": [{"word", "start", "end"}, ...]}.
"""
import argparse
import json
import sys

from common import probe_duration


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript", help="Whisper JSON with word timestamps")
    p.add_argument("out", help="output words.json")
    p.add_argument("--audio", help="the transcribed audio or video file; its length becomes \"duration\". "
                                   "Without it, duration is the end of the last word")
    a = p.parse_args()

    with open(a.transcript, encoding="utf-8") as f:
        data = json.load(f)
    words = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            text = str(w.get("word", "")).strip()
            # WhisperX leaves the times off words it could not align
            if text and "start" in w and "end" in w:
                words.append({"word": text, "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)})
    if not words:
        sys.exit("no word timestamps found; run Whisper with word timestamps enabled (--word_timestamps True)")
    duration = probe_duration(a.audio) if a.audio else words[-1]["end"]
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"duration": duration, "words": words}, f, indent=1)
    print(f"{len(words)} words, duration {duration:.2f}s")


if __name__ == "__main__":
    sys.exit(main())
