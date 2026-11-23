"""Cut the user's 「黃」 badge out of its screenshot for 叮當's cap.

Input : characters/dingdong/source/badge_original.jpg (fake checkerboard
        background, plus a screenshot UI button in one corner)
Output: characters/dingdong/source/badge.png — transparent, cropped,
        240 px wide, palette-quantised so it embeds compactly in the SVGs.

The background is flood-filled from the image border through light,
low-saturation pixels (the checkerboard); the badge's black outline stops
the fill. Only the largest remaining shape (the badge) is kept, which
drops the corner button.

Usage:  python -I scripts/prepare_dingdong_badge.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1] / "characters" / "dingdong" / "source"
WIDTH = 240


def main() -> None:
    image = Image.open(ROOT / "badge_original.jpg").convert("RGB")
    rgb = np.asarray(image).astype(int)
    light = (rgb.min(axis=2) > 170) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 24)
    labels, _ = ndimage.label(light)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    background = np.isin(labels, list(border))

    foreground, count = ndimage.label(~background)
    if count > 1:
        sizes = ndimage.sum(np.ones(foreground.shape), foreground, range(1, count + 1))
        keep = foreground == (int(np.argmax(sizes)) + 1)
    else:
        keep = ~background
    keep = ndimage.binary_fill_holes(keep)

    alpha = Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    badge = image.convert("RGBA")
    badge.putalpha(alpha)
    badge = badge.crop(badge.getbbox())
    height = round(badge.height * WIDTH / badge.width)
    badge = badge.resize((WIDTH, height), Image.LANCZOS)
    badge = badge.quantize(colors=96, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    badge.save(ROOT / "badge.png", optimize=True)
    print(f"badge.png {WIDTH}x{height}, {(ROOT / 'badge.png').stat().st_size} bytes")


if __name__ == "__main__":
    main()
