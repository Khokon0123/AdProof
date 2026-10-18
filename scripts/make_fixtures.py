"""Generate the synthetic AeroBeat ad images (PNG) used by the demo and the evaluation.

neutral  : product illustration, no offer text
price49  : same, plus a badge saying "Only $49" (contradicts the $60 page price)
blurry   : same badge, but the price is blurred until unreadable
Run: python -m scripts.make_fixtures
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures"
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]


def font(size: int):
    for p in FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def base() -> Image.Image:
    W = H = 1024
    img = Image.new("RGB", (W, H), (236, 241, 247))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 150], fill=(20, 33, 61))
    d.text((60, 42), "AeroBeat AB-01", font=font(64), fill=(255, 255, 255))
    # headphone illustration
    cx, cy = 512, 520
    d.arc([cx - 230, cy - 260, cx + 230, cy + 200], start=190, end=350, fill=(40, 52, 80), width=38)
    for sx in (-1, 1):
        x = cx + sx * 215
        d.rounded_rectangle([x - 70, cy - 20, x + 70, cy + 190], radius=48, fill=(40, 52, 80))
        d.rounded_rectangle([x - 46, cy + 10, x + 46, cy + 160], radius=34, fill=(92, 110, 150))
    d.text((60, 820), "Wireless noise-cancelling headphones", font=font(40), fill=(20, 33, 61))
    d.text((60, 880), "Splash-resistant · Foldable · Bluetooth 5.3", font=font(32), fill=(70, 84, 110))
    d.text((60, 960), "Synthetic demo product", font=font(24), fill=(120, 130, 150))
    return img


def badge(img: Image.Image, text: str) -> tuple[int, int, int, int]:
    d = ImageDraw.Draw(img)
    box = (640, 190, 984, 330)
    d.rounded_rectangle(box, radius=28, fill=(200, 30, 45))
    f = font(56)
    w = d.textlength(text, font=f)
    d.text(((box[0] + box[2] - w) / 2, 228), text, font=f, fill=(255, 255, 255))
    return box


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    neutral = base()
    neutral.save(OUT / "aerobeat_neutral.png")
    p49 = base()
    badge(p49, "Only $49")
    p49.save(OUT / "aerobeat_price49.png")
    blurry = base()
    box = badge(blurry, "Only $49")
    region = blurry.crop(box).filter(ImageFilter.GaussianBlur(18))
    blurry.paste(region, box[:2])
    blurry.save(OUT / "aerobeat_blurry.png")
    manifest = {}
    for name in ("aerobeat_neutral.png", "aerobeat_price49.png", "aerobeat_blurry.png"):
        manifest[name] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Wrote", ", ".join(manifest))


if __name__ == "__main__":
    main()
