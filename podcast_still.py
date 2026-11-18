#!/usr/bin/env python3
"""Give a talking-head photo a dark studio look: keep the subject, push the background down.

The subject is cut out with a segmentation mask. The background is blurred,
mostly desaturated, darkened and cooled slightly; the subject is warmed
slightly; a vignette is laid over both. The mask is saved next to the output
as <name>-mask.png so it can be checked or reused with --mask.
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
    p.add_argument("out", help="output image, for example still.jpg")
    p.add_argument("--mask", help="greyscale subject mask (white is the subject); skips the segmentation model")
    p.add_argument("--model", default="birefnet-portrait",
                   help="rembg model used when --mask is not given (default: birefnet-portrait)")
    p.add_argument("--bg-blur", type=float, default=6, help="background blur radius in pixels (default: 6)")
    p.add_argument("--bg-saturation", type=float, default=0.22,
                   help="background colour kept, 0 is grey and 1 is unchanged; low values mute "
                        "bright screens and coloured lights behind the subject (default: 0.22)")
    p.add_argument("--bg-brightness", type=float, default=0.42,
                   help="background brightness multiplier (default: 0.42)")
    p.add_argument("--vignette", type=float, default=0.45, help="vignette strength, 0 turns it off (default: 0.45)")
    a = p.parse_args()

    img = Image.open(a.src).convert("RGB")
    mask = subject_mask(img, a.mask, a.model).filter(ImageFilter.GaussianBlur(2))  # soften the cut edge
    m = np.asarray(mask, dtype=np.float32)[..., None] / 255.0

    fg = np.asarray(img, dtype=np.float32) / 255.0
    bg = np.asarray(img.filter(ImageFilter.GaussianBlur(a.bg_blur)), dtype=np.float32) / 255.0
    grey = bg.mean(axis=2, keepdims=True)
    bg = grey + (bg - grey) * a.bg_saturation
    bg = bg * a.bg_brightness
    bg = bg * np.array([1.0, 0.97, 1.03])      # cool, neutral shadows
    h, w = m.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    # centred slightly above the middle, where the face usually is; never darker than 35 percent
    vig = 1 - a.vignette * (((xx - w * 0.5) / (w * 0.6)) ** 2 + ((yy - h * 0.45) / (h * 0.75)) ** 2)
    vig = np.clip(vig, 0.35, 1)[..., None]
    fg = fg * np.array([1.02, 1.0, 0.97])      # a touch warmer on skin
    o = (fg * m + bg * (1 - m)) * vig
    Image.fromarray((np.clip(o, 0, 1) * 255).astype(np.uint8)).save(a.out, quality=95)
    mask_out = os.path.splitext(a.out)[0] + "-mask.png"
    Image.fromarray((m[..., 0] * 255).astype(np.uint8)).save(mask_out)
    print(f"wrote {a.out} and {mask_out}")


if __name__ == "__main__":
    sys.exit(main())
