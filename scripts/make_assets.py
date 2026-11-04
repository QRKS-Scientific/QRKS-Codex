"""Build the optimized logo and icon assets from the original brand files.

Usage:  python scripts/make_assets.py --src path/to/original_logos

Expected original files (as supplied by QRKS Scientific):
  qrks_brandmark.png  qrks_emblem.png  qrks_logo.png  qrks_white.png
  1.png (QRKSInsight)  2.png (QRKSDock)  3.png (QRKSAttest)

The originals are very large (up to 7000+ px), so the app ships only the
optimized copies written to assets/logos and assets/icons.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
ROOT = Path(__file__).resolve().parents[1]


def resize_to_height(im: Image.Image, height: int) -> Image.Image:
    w, h = im.size
    return im.resize((round(w * height / h), height), Image.LANCZOS)


def resize_to_width(im: Image.Image, width: int) -> Image.Image:
    w, h = im.size
    return im.resize((width, round(h * width / w)), Image.LANCZOS)


def white_to_alpha(im: Image.Image) -> Image.Image:
    """Convert an opaque logo on a white background to a transparent PNG."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    alpha = 255.0 - a.min(axis=2)                      # how far from white
    safe = np.maximum(alpha, 1.0)[..., None] / 255.0
    rgb = (a - 255.0 * (1.0 - safe)) / safe            # un-premultiply against white
    rgb = np.clip(rgb, 0, 255)
    out = np.dstack([rgb, alpha]).astype(np.uint8)
    out[alpha < 2] = 0
    return Image.fromarray(out, "RGBA")


def crop_to_content(im: Image.Image, margin: int = 12) -> Image.Image:
    bbox = im.getchannel("A").getbbox()
    if not bbox:
        return im
    l, t, r, b = bbox
    return im.crop((max(l - margin, 0), max(t - margin, 0),
                    min(r + margin, im.width), min(b + margin, im.height)))


def app_icon(brandmark: Image.Image, size: int = 1024) -> Image.Image:
    """White rounded-square tile with the brandmark centred (reads well on both OSes)."""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    pad = round(size * 0.04)
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=round(size * 0.22),
                        fill=(255, 255, 255, 255), outline=(213, 221, 234, 255), width=max(2, size // 256))
    mark = resize_to_height(brandmark, round(size * 0.62))
    tile.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return tile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    src = ap.parse_args().src
    logos, icons = ROOT / "assets" / "logos", ROOT / "assets" / "icons"
    logos.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)

    brandmark = Image.open(src / "qrks_brandmark.png").convert("RGBA")
    brandmark = resize_to_height(brandmark, 640)
    brandmark.save(logos / "brandmark.png", optimize=True)

    resize_to_height(Image.open(src / "qrks_emblem.png").convert("RGBA"), 1000).save(
        logos / "emblem.png", optimize=True)
    resize_to_height(Image.open(src / "qrks_white.png").convert("RGBA"), 640).save(
        logos / "brandmark_white.png", optimize=True)
    resize_to_width(white_to_alpha(Image.open(src / "qrks_logo.png")), 1800).save(
        logos / "qrks_horizontal.png", optimize=True)

    for fname, out in (("1.png", "qrksinsight.png"), ("2.png", "qrksdock.png"), ("3.png", "qrksattest.png")):
        im = crop_to_content(Image.open(src / fname).convert("RGBA"))
        resize_to_width(im, 900).save(logos / out, optimize=True)

    tile = app_icon(brandmark)
    tile.save(icons / "qrksdock_1024.png", optimize=True)
    tile.save(icons / "qrksdock.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    tile.save(icons / "qrksdock.icns")
    resize_to_height(tile, 256).save(icons / "qrksdock_256.png", optimize=True)
    print("assets written to", logos, "and", icons)


if __name__ == "__main__":
    main()
