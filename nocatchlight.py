#!/usr/bin/env python3
"""Remove catchlights (the small bright reflections of a light) from the eyes in a still.

Give the approximate centre of each pupil in pixels. For each eye the tool
snaps to the darkest point nearby, builds a radial brightness profile of the
iris from a low percentile of each ring (so the reflections themselves do not
count), then replaces the pixels that are brighter than the profile with it,
keeping a little of the original grain.
"""
import argparse
import sys

import cv2
import numpy as np

SNAP = 6          # the centre snaps to the darkest blurred pixel within this many pixels
INNER = 4         # rings inside this radius share one profile value: the pupil is too small to sample per ring
PERCENTILE = 30   # per ring, the brightness percentile taken as "iris without reflection"
GRAIN = 0.4       # share of the original fine grain put back over the fill
GRAIN_CLIP = 5    # grain is limited to this many levels so no trace of the reflection comes back


def centre(text):
    try:
        x, y = text.split(",")
        return int(x), int(y)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected x,y in pixels, got {text!r}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", help="input image")
    p.add_argument("out", help="output image")
    p.add_argument("centres", nargs="+", type=centre, metavar="x,y",
                   help="approximate pupil centre of each eye, in pixels from the top left")
    p.add_argument("--iris-radius", type=int, default=12,
                   help="iris radius in pixels; set it to the iris size in your image (default: 12)")
    p.add_argument("--delta", type=int, default=15,
                   help="how much brighter than the iris profile a pixel must be to count as a reflection, "
                        "0 to 255 (default: 15)")
    a = p.parse_args()

    bgr = cv2.imread(a.src)
    if bgr is None:
        sys.exit(f"could not read {a.src}")
    im = bgr.astype(np.float32)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    out = im.copy()
    R = a.iris_radius
    h, w = g.shape
    yy, xx = np.mgrid[:h, :w]
    blur = cv2.GaussianBlur(g, (9, 9), 0)
    for cx, cy in a.centres:
        if not (SNAP <= cx < w - SNAP and SNAP <= cy < h - SNAP):
            sys.exit(f"centre {cx},{cy} is outside the image or too close to its edge")
        win = blur[cy - SNAP:cy + SNAP + 1, cx - SNAP:cx + SNAP + 1]
        dy, dx = np.unravel_index(np.argmin(win), win.shape)
        cx, cy = cx - SNAP + dx, cy - SNAP + dy
        r = np.hypot(xx - cx, yy - cy)
        disk = r <= R
        prof = np.zeros((R + 1, 3), np.float32)
        for ri in range(R + 1):
            ring = (r >= max(ri, INNER) - 1.5) & (r < max(ri, INNER) + 1.5)
            prof[ri] = np.percentile(im[ring], PERCENTILE, axis=0)
        fill = np.zeros_like(im)
        idx = np.clip(np.round(r), 0, R).astype(int)
        fill[disk] = prof[idx[disk]]
        flum = cv2.cvtColor(np.clip(fill, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
        bright = disk & (g > flum + a.delta)
        bright = cv2.dilate(bright.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & disk
        alpha = cv2.GaussianBlur(bright.astype(np.float32), (3, 3), 0)[..., None]
        grain = im - cv2.GaussianBlur(im, (5, 5), 0)
        out = out * (1 - alpha) + (fill + np.clip(grain, -GRAIN_CLIP, GRAIN_CLIP) * GRAIN) * alpha
        print(f"centre {cx},{cy}: replaced {int(bright.sum())} px")
    if not cv2.imwrite(a.out, np.clip(out, 0, 255).astype(np.uint8)):
        sys.exit(f"could not write {a.out}")


if __name__ == "__main__":
    sys.exit(main())
