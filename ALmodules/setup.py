"""
setup.py — First-run setup helpers.

  ensure_directories()     — create cache/, icons/, merged/
  ensure_rarity_assets()   — generate rarity background PNGs with colour
                             gradients if the rarities/ folder is empty
  resolve_font()           — return a font path if it exists, else None
                             (image_gen.py falls back to PIL default)
"""

from __future__ import annotations

import os
from typing import Optional

from PIL import Image, ImageDraw

RESAMPLE  = Image.LANCZOS
ICON_SIZE = 512

ICON_TYPES = ("standard", "clean", "new", "cataba")

# Per-rarity hex colours used for gradient backgrounds
RARITY_GRADIENTS: dict[str, tuple[str, str]] = {
    # (top_hex, bottom_hex)
    "common":     ("#9d9d9d", "#636363"),
    "uncommon":   ("#5dde46", "#31a21f"),
    "rare":       ("#4f9ae0", "#3275c4"),
    "epic":       ("#b478e8", "#7d3dba"),
    "legendary":  ("#e8a554", "#c2712c"),
    "mythic":     ("#f5e46a", "#e7c03a"),
    "exotic":     ("#7de8f5", "#21c5e7"),
    "slurp":      ("#40d9e8", "#00bcd4"),
    "dc":         ("#6a9fd9", "#4a90d9"),
    "marvel":     ("#f57272", "#e52020"),
    "starwars":   ("#fff57f", "#ffe81f"),
    "icon":       ("#45db71", "#1db954"),
    "lambskin":   ("#e0c494", "#d4a574"),
    "shadowfoil": ("#7a7aaa", "#4a4a6a"),
    "frozen":     ("#c8e8f5", "#a8d8ea"),
    "lava":       ("#ff9060", "#ff6b35"),
    "dark":       ("#6040a8", "#2d1b69"),
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _make_gradient(top_hex: str, bottom_hex: str, size: int = ICON_SIZE) -> Image.Image:
    """Create a vertical linear gradient RGBA image."""
    top    = _hex_to_rgb(top_hex)
    bottom = _hex_to_rgb(bottom_hex)
    img    = Image.new("RGBA", (size, size))
    pixels = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            pixels[x, y] = (r, g, b, 255)
    return img


def _make_border(color_hex: str, size: int = ICON_SIZE, border: int = 8) -> Image.Image:
    """Create a transparent image with a coloured border ring."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rgb  = _hex_to_rgb(color_hex)
    for i in range(border):
        draw.rectangle([i, i, size - 1 - i, size - 1 - i], outline=rgb + (255,))
    return img


def ensure_rarity_assets(rarity_colors: dict[str, str]) -> None:
    """
    For each icon type, generate gradient background + border PNGs for every
    rarity if they don't already exist.  This lets the tool run without the
    original proprietary asset pack.
    """
    for icon_type in ICON_TYPES:
        base = os.path.join("rarities", icon_type)
        os.makedirs(base, exist_ok=True)

        for rarity, grad_pair in RARITY_GRADIENTS.items():
            bg_path     = os.path.join(base, f"{rarity}.png")
            border_path = os.path.join(base, f"border{rarity}.png")

            if not os.path.exists(bg_path):
                bg = _make_gradient(grad_pair[0], grad_pair[1])
                bg.save(bg_path)

            if not os.path.exists(border_path):
                # Border colour = the brighter (top) colour
                border = _make_border(grad_pair[0])
                border.save(border_path)

        # cataba-specific layers (overlay / background / rarity badge)
        if icon_type == "cataba":
            for rarity, grad_pair in RARITY_GRADIENTS.items():
                for suffix in ("_background", "_overlay", "_rarity"):
                    path = os.path.join(base, f"{rarity}{suffix}.png")
                    if not os.path.exists(path):
                        # Overlay = semi-transparent dark gradient
                        overlay = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 80))
                        overlay.save(path)

            # PlusSign (variants indicator)
            plus_path = os.path.join(base, "PlusSign.png")
            if not os.path.exists(plus_path):
                plus = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
                draw = ImageDraw.Draw(plus)
                draw.text((ICON_SIZE - 30, 6), "+", fill=(255, 255, 255, 200))
                plus.save(plus_path)

            # placeholder_rarity
            ph_path = os.path.join(base, "placeholder_rarity.png")
            if not os.path.exists(ph_path):
                Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0)).save(ph_path)


def ensure_directories() -> None:
    """Create required runtime directories."""
    for d in ("cache", "icons", "merged", "fonts", "assets"):
        os.makedirs(d, exist_ok=True)
    for it in ICON_TYPES:
        os.makedirs(os.path.join("rarities", it), exist_ok=True)


def resolve_font(font_name: str) -> Optional[str]:
    """
    Return the full path to a font if it exists in the fonts/ directory.
    Returns None if not found (callers fall back to PIL's built-in font).
    """
    if not font_name:
        return None
    path = os.path.join("fonts", font_name)
    return path if os.path.exists(path) else None
