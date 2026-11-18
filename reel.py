#!/usr/bin/env python3
"""Finish a jump-cut talking-head video: a punch-in zoom per cut and word-highlight captions.

Takes a video that has already been cut (the kept ranges joined end to end),
the list of ranges that were kept, and word timestamps on the original,
uncut timeline. Each kept range gets its own zoom level, so every jump cut
also changes the framing. Captions show up to three words at a time with the
spoken word highlighted, and are burned into the picture.

cuts.json: [[start, end], ...] the ranges kept from the source, in order, in
seconds on the source timeline. The input video must be exactly these ranges
joined together.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from common import load_words, probe_size

ZOOMS = "1.12,1.0,1.16,1.0,1.08,1.0"
REF_H = 1280       # caption sizes below were tuned on a 720x1280 frame and scale with frame height
FONT_SIZE = 68
OUTLINE, SHADOW = 6, 3
MARGIN_SIDE, MARGIN_BOTTOM = 40, 150
EDGE = 0.05        # a word this close outside a kept range still counts as inside it, seconds
MIN_WORD = 0.08    # shortest time a word stays highlighted, seconds
HOLD = 0.4         # how long the last caption stays after its last word, seconds
BREAK = ".,?!"     # a caption ends early on a word that ends with one of these


def ass_colour(rgb):
    """RRGGBB hex to an ASS colour, which is written blue-green-red."""
    rgb = rgb.lstrip("#")
    if len(rgb) != 6:
        raise argparse.ArgumentTypeError("colour must be RRGGBB hex, for example FFD400")
    int(rgb, 16)
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&".upper()


def fmt(sec):
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", help="the cut video (kept ranges joined end to end)")
    p.add_argument("cuts", help="cuts.json: [[start, end], ...] kept ranges on the source timeline")
    p.add_argument("words", help="word-timestamp JSON on the source (uncut) timeline")
    p.add_argument("out", help="output video; the captions are also saved next to it as .ass")
    p.add_argument("--zooms", default=ZOOMS,
                   help=f"zoom level per kept range, cycled (default: {ZOOMS})")
    p.add_argument("--anchor-y", type=float, default=0.18,
                   help="where the zoom crops vertically: share of the spare height left above the crop. "
                        "0 keeps the top edge, 0.5 is centred; a low value keeps a face in the upper part "
                        "of the frame in place (default: 0.18)")
    p.add_argument("--max-words", type=int, default=3, help="most words per caption (default: 3)")
    p.add_argument("--font", default="Montserrat",
                   help="caption font, must be installed; libass substitutes another if it is not (default: Montserrat)")
    p.add_argument("--font-size", type=float, default=None,
                   help=f"caption font size in pixels (default: {FONT_SIZE} at {REF_H} pixels of height, scaled to the video)")
    p.add_argument("--highlight", type=ass_colour, default="FFD400",
                   help="colour of the spoken word, RRGGBB hex (default: FFD400)")
    p.add_argument("--crf", type=int, default=18, help="x264 quality, lower is better (default: 18)")
    p.add_argument("--preset", default="slow", help="x264 preset (default: slow)")
    a = p.parse_args()

    with open(a.cuts, encoding="utf-8") as f:
        cuts = [(float(x), float(y)) for x, y in json.load(f)]
    if not cuts:
        sys.exit("cuts.json has no ranges")
    words, _ = load_words(a.words)
    zooms = [float(z) for z in a.zooms.split(",")]
    if any(z < 1 for z in zooms):
        p.error("zoom levels must be 1.0 or greater")
    W, H = probe_size(a.video)
    k = H / REF_H

    # where each kept range starts on the cut timeline
    offsets, t = [], 0.0
    for s, e in cuts:
        offsets.append(t)
        t += e - s

    def to_cut(ts):
        """Source time to cut-timeline time, or None if the time was cut out."""
        for (s, e), off in zip(cuts, offsets):
            if s - EDGE <= ts <= e + EDGE:
                return off + min(max(ts, s), e) - s
        return None

    ws = []
    for x in words:
        s, e = to_cut(x["start"]), to_cut(x["end"])
        if s is not None and e is not None:
            ws.append((x["word"].replace("{", "").replace("}", ""), s, max(e, s + MIN_WORD)))
    if not ws:
        sys.exit("no words fall inside the kept ranges; check that words and cuts use the same timeline")

    # captions of up to max-words words, ended early at punctuation
    chunks, cur = [], []
    for w in ws:
        cur.append(w)
        if len(cur) == a.max_words or w[0][-1] in BREAK:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    # one subtitle event per word: the whole caption, with that word in the highlight colour
    white = "&H00FFFFFF&"
    lines = []
    for ci, ch in enumerate(chunks):
        end_chunk = chunks[ci + 1][0][1] if ci + 1 < len(chunks) else ch[-1][2] + HOLD
        for wi, (word, s, e) in enumerate(ch):
            e_show = ch[wi + 1][1] if wi + 1 < len(ch) else end_chunk
            txt = " ".join(("{\\c" + a.highlight + "}" + x[0].strip(".,") + "{\\c" + white + "}")
                           if j == wi else x[0].strip(".,") for j, x in enumerate(ch))
            lines.append(f"Dialogue: 0,{fmt(s)},{fmt(e_show)},Cap,,0,0,0,,{txt}")

    size = a.font_size if a.font_size else FONT_SIZE * k
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{a.font},{size:.0f},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{OUTLINE * k:.1f},{SHADOW * k:.1f},2,{MARGIN_SIDE * k:.0f},{MARGIN_SIDE * k:.0f},{MARGIN_BOTTOM * k:.0f},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(lines) + "\n"

    # crop each kept range to its zoom level and scale it back up, then join and burn the captions in
    fc = ""
    for j, ((s, e), off) in enumerate(zip(cuts, offsets)):
        z = zooms[j % len(zooms)]
        cw, chh = int(W / z) // 2 * 2, int(H / z) // 2 * 2
        x, y = (W - cw) // 2, int((H - chh) * a.anchor_y)
        fc += (f"[0:v]trim={off:.3f}:{off + e - s:.3f},setpts=PTS-STARTPTS,crop={cw}:{chh}:{x}:{y},"
               f"scale={W}:{H}:flags=lanczos,setsar=1[v{j}];")

    # ffmpeg reads the captions from a temporary path that needs little escaping in a filter graph
    tmpdir = tempfile.mkdtemp(prefix="reel-")
    try:
        tmp_ass = os.path.join(tmpdir, "captions.ass")
        with open(tmp_ass, "w", encoding="utf-8") as f:
            f.write(ass)
        esc = tmp_ass.replace("\\", "/").replace(":", "\\\\:")
        fc += "".join(f"[v{j}]" for j in range(len(cuts))) + f"concat=n={len(cuts)}:v=1:a=0[vc];[vc]ass={esc}[v]"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-filter_complex", fc,
                        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", str(a.crf),
                        "-preset", a.preset, "-pix_fmt", "yuv420p", "-c:a", "copy", a.out], check=True)
        ass_path = os.path.splitext(a.out)[0] + ".ass"
        shutil.copyfile(tmp_ass, ass_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"wrote {a.out} with {len(cuts)} zoom segments and {len(lines)} caption events; captions saved to {ass_path}")


if __name__ == "__main__":
    sys.exit(main())
