#!/usr/bin/env python3
"""Draw the Home Screen icons: a green highway guide sign with a white "TN".

Writes three PNGs to src/icons/, which build.py copies into dist/:

- apple-touch-icon.png  180x180, no transparency (the iPhone Home Screen icon)
- icon-192.png          192x192 (the manifest's "any" icon)
- icon-512.png          512x512 (the manifest's "any" and "maskable" icon)

The square is filled edge to edge in the page's guide green (#1f5f3f), with a
white rounded border set in from the edge and "TN" in Overpass ExtraBold (800),
drawn from the self-hosted src/fonts/overpass/overpass-variable.woff2. All the
artwork sits inside the central 80%, within the maskable safe-zone circle, so
the 512 icon also works as a maskable icon that a phone crops to a circle.

Needs Pillow, which is only for running this tool, never for an Instance:
    python3 -m pip install Pillow      (or: apt install python3-pil)

Usage:
    python3 tools/make_icons.py
    python3 build.py                   (copies the icons into dist/)
"""
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = ROOT / "src" / "fonts" / "overpass" / "overpass-variable.woff2"
OUT = ROOT / "src" / "icons"
GREEN = (0x1F, 0x5F, 0x3F)
WHITE = (0xFF, 0xFF, 0xFF)
SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}
SCALE = 4  # draw large and shrink, so the edges are smooth

# Geometry as fractions of the icon's side. The border's outer corner arcs stay
# within 0.4 of the center, the radius of the maskable safe zone.
BORDER_HALF = 0.31   # half the border's outer width
BORDER_RADIUS = 0.10
BORDER_WIDTH = 0.035
TEXT_WIDTH = 0.40    # width of the "TN" ink


def draw(size):
    big = size * SCALE
    img = Image.new("RGB", (big, big), GREEN)
    d = ImageDraw.Draw(img)
    lo, hi = big * (0.5 - BORDER_HALF), big * (0.5 + BORDER_HALF)
    d.rounded_rectangle((lo, lo, hi, hi), radius=big * BORDER_RADIUS, outline=WHITE, width=round(big * BORDER_WIDTH))

    font = ImageFont.truetype(str(FONT), 100)
    font.set_variation_by_axes([800])
    left, top, right, bottom = font.getbbox("TN")
    font = ImageFont.truetype(str(FONT), round(100 * big * TEXT_WIDTH / (right - left)))
    font.set_variation_by_axes([800])
    left, top, right, bottom = font.getbbox("TN")
    # Center the ink itself, not the line box, so "TN" sits in the middle of the sign.
    x = (big - (right - left)) / 2 - left
    y = (big - (bottom - top)) / 2 - top
    d.text((x, y), "TN", font=font, fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        draw(size).save(OUT / name, optimize=True)
        print(f"Wrote {OUT / name} ({size}x{size})")


if __name__ == "__main__":
    main()
