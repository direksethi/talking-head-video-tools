"""Helpers shared by the tools: word-timestamp loading, ffprobe, subject masks."""
import json
import subprocess
import sys


def load_words(path):
    """Read a word-timestamp file and return (words, duration).

    Accepted shapes:
      {"duration": 12.3, "words": [{"word": "Hello", "start": 0.10, "end": 0.42}, ...]}
      [{"word": "Hello", "start": 0.10, "end": 0.42}, ...]
    The short keys "w", "s", "e" are accepted in place of "word", "start", "end".
    Times are seconds. When "duration" is missing it is None.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    raw = data["words"] if isinstance(data, dict) else data
    duration = data.get("duration") if isinstance(data, dict) else None
    words = []
    for x in raw:
        word = x.get("word", x.get("w"))
        start = x.get("start", x.get("s"))
        end = x.get("end", x.get("e"))
        if word is None or start is None or end is None:
            sys.exit(f"{path}: every word needs word, start and end: {x}")
        word = str(word).strip()
        if word:
            words.append({"word": word, "start": float(start), "end": float(end)})
    if not words:
        sys.exit(f"{path}: no words found")
    return words, duration


def probe_duration(path):
    """Container duration in seconds, from ffprobe."""
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path])
    return float(out)


def probe_size(path):
    """(width, height) of the first video stream, from ffprobe."""
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                   "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path])
    w, h = out.decode().strip().split("x")[:2]
    return int(w), int(h)


def subject_mask(img, mask_path=None, model="birefnet-portrait"):
    """Greyscale PIL mask of the subject, white where the subject is.

    With mask_path the mask is read from that file and no model is needed.
    Otherwise rembg computes it with the named model, which rembg downloads on
    first use.
    """
    from PIL import Image
    if mask_path:
        mask = Image.open(mask_path).convert("L")
        if mask.size != img.size:
            mask = mask.resize(img.size, Image.LANCZOS)
        return mask
    try:
        from rembg import new_session, remove
    except ImportError:
        sys.exit("rembg is not installed. Install it (pip install 'rembg[cpu]') or pass --mask with a subject mask.")
    return remove(img, session=new_session(model), only_mask=True).convert("L")
