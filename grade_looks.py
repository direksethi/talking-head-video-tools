#!/usr/bin/env python3
"""Render five colour grades of a talking-head photo, to compare looks side by side.

Each look separates the subject from the background with a segmentation mask,
adds a soft key light on the subject, treats the background on its own
(blurred, desaturated, darkened), then applies a grade to the result.

  1-clean-tech.jpg     neutral and crisp, deep blacks, background pushed down
  2-teal-orange.jpg    warm skin, teal shadows and background
  3-warm-creator.jpg   bright, soft and warm, background kept visible
  4-moody-podcast.jpg  one-sided key light, dark room, muted colour
  5-dark-tech-rgb.jpg  near-black room with a violet and blue glow behind the subject

The mask is saved as mask.png in the output folder and reused on later runs.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

from common import subject_mask


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", help="input photo or video frame")
    p.add_argument("out_dir", help="output folder for the five images and mask.png")
    p.add_argument("--mask", help="greyscale subject mask (white is the subject); skips the segmentation model")
    p.add_argument("--model", default="birefnet-portrait",
                   help="rembg model used when no mask is given or cached (default: birefnet-portrait)")
    a = p.parse_args()

    out = a.out_dir
    os.makedirs(out, exist_ok=True)
    img = Image.open(a.src).convert("RGB")
    cached = os.path.join(out, "mask.png")
    if a.mask or not os.path.exists(cached):
        subject_mask(img, a.mask, a.model).save(cached)
    mask = subject_mask(img, cached)
    m = np.asarray(mask.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)[..., None] / 255.0
    src = np.asarray(img, dtype=np.float32) / 255.0
    h, w = src.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    def lum(x):
        return (x * [0.2126, 0.7152, 0.0722]).sum(-1, keepdims=True)

    def sat(x, s):
        l = lum(x)
        return l + (x - l) * s

    def contrast(x, c, pivot=0.45):
        return (x - pivot) * c + pivot

    def curve(x, lift=0.0, gamma=1.0, gain=1.0):
        return lift + (gain - lift) * np.clip(x, 0, 1) ** gamma

    def tint(x, shadows, highlights):
        """Add one RGB offset in the shadows and another in the highlights."""
        l = np.clip(lum(x), 0, 1)
        return x + (1 - l) * np.array(shadows) + l * np.array(highlights)

    def key(cx, cy, r, strength):
        """Soft pool of light centred on (cx, cy), in 0..1 frame coordinates."""
        d = ((xx / w - cx) ** 2 + (yy / h - cy) ** 2) / r ** 2
        return (1 + strength * np.exp(-d))[..., None]

    def vignette(s, cy=0.45):
        d = ((xx / w - 0.5) / 0.75) ** 2 + ((yy / h - cy) / 0.85) ** 2
        return np.clip(1 - s * d, 0, 1)[..., None]

    def comp(fg, bg):
        return fg * m + bg * (1 - m)

    def save(x, name):
        Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8)).save(os.path.join(out, name), quality=95)
        print("wrote", os.path.join(out, name))

    blur_bg = np.asarray(img.filter(ImageFilter.GaussianBlur(5)), dtype=np.float32) / 255.0

    # 1 Clean tech: neutral, crisp, deep blacks, background pushed down.
    fg = contrast(sat(src, 1.02), 1.12) * key(0.45, 0.35, 0.45, 0.10)
    bg = sat(blur_bg, 0.6) * 0.42
    x = curve(comp(fg, bg), 0.0, 1.05, 1.0) * vignette(0.25)
    save(tint(x, [0, 0.005, 0.015], [0.01, 0.0, -0.01]), "1-clean-tech.jpg")

    # 2 Teal and orange: warm skin, teal shadows and background.
    fg = contrast(sat(src, 1.1), 1.15) * key(0.4, 0.35, 0.5, 0.12)
    fg = tint(fg, [-0.02, 0.0, 0.02], [0.05, 0.015, -0.04])
    bg = tint(sat(blur_bg, 0.5) * 0.5, [-0.03, 0.03, 0.06], [-0.02, 0.02, 0.04])
    x = comp(fg, bg) * vignette(0.35)
    save(curve(x, 0.02, 1.08, 0.97), "2-teal-orange.jpg")

    # 3 Warm creator: bright, soft, warm, background kept visible.
    fg = contrast(sat(src, 1.05), 1.05) * key(0.45, 0.35, 0.5, 0.08)
    fg = tint(fg, [0.015, 0.005, -0.01], [0.04, 0.02, -0.02])
    bg = tint(sat(blur_bg, 0.85) * 0.72, [0.03, 0.01, -0.02], [0.04, 0.015, -0.03])
    x = comp(fg, bg) * vignette(0.18)
    save(curve(x, 0.035, 0.95, 0.98), "3-warm-creator.jpg")

    # 4 Moody podcast: key light from the left that falls off to the right, dark room, muted colour.
    side = np.clip(1.15 - 0.55 * (xx / w), 0.55, 1.15)[..., None]
    fg = contrast(sat(src, 0.88), 1.18) * side * key(0.38, 0.33, 0.35, 0.10)
    fg = tint(fg, [0.0, 0.0, 0.01], [0.03, 0.012, -0.015])
    bg = sat(blur_bg, 0.45) * 0.28
    x = comp(fg, bg) * vignette(0.45)
    save(curve(x, 0.015, 1.12, 0.96), "4-moody-podcast.jpg")

    # 5 Dark tech with RGB backlight: near-black room, violet glow on the left and blue on the
    # right behind the subject, neutral skin, and a thin rim of the glow colour on the subject's edge.
    fg = contrast(sat(src, 1.0), 1.12) * key(0.45, 0.35, 0.45, 0.08)
    glow = np.zeros_like(src)
    glow += np.exp(-(((xx / w - 0.2) / 0.35) ** 2 + ((yy / h - 0.45) / 0.45) ** 2))[..., None] * np.array([0.32, 0.12, 0.55])
    glow += np.exp(-(((xx / w - 0.82) / 0.3) ** 2 + ((yy / h - 0.4) / 0.45) ** 2))[..., None] * np.array([0.05, 0.25, 0.55])
    bg = sat(blur_bg, 0.2) * 0.22 + glow * 0.55
    eroded = Image.fromarray((m[..., 0] * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(9))
    rim = np.clip(m - np.asarray(eroded, dtype=np.float32)[..., None] / 255.0, 0, 1)
    x = comp(fg, bg) + rim * glow * 0.8
    save(curve(x * vignette(0.3), 0.01, 1.05, 1.0), "5-dark-tech-rgb.jpg")


if __name__ == "__main__":
    sys.exit(main())
