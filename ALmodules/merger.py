"""
merger.py — Grid-merge all PNG files in a folder into a single image.

Improvements over the original:
  - ANTIALIAS → LANCZOS
  - Handles arbitrary icon counts (not just fixed grid sizes)
  - Optional watermark overlay (URL or local file path)
  - Returns the output path for chaining
"""

from __future__ import annotations

import io
import math
import os
from typing import Optional

import requests
from PIL import Image

RESAMPLE  = Image.LANCZOS
ICON_SIZE = 512
COLS      = 6     # icons per row (same feel as original)


def _load_watermark(source: str) -> Optional[Image.Image]:
    """Load a watermark from a URL or local path. Returns None on any failure."""
    if not source:
        return None

    if source.startswith("image/"):
        # Local file in assets/
        path = os.path.join("assets", source[len("image/"):])
        if os.path.exists(path):
            try:
                return Image.open(path).convert("RGBA").resize((ICON_SIZE, ICON_SIZE), RESAMPLE)
            except Exception:
                pass
        return None

    # Try as URL
    try:
        resp = requests.get(source, timeout=10)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA").resize((ICON_SIZE, ICON_SIZE), RESAMPLE)
    except Exception:
        pass

    # Try as local file
    if os.path.exists(source):
        try:
            return Image.open(source).convert("RGBA").resize((ICON_SIZE, ICON_SIZE), RESAMPLE)
        except Exception:
            pass

    return None


def merge_icons(
    icons_dir: str,
    out_path: str,
    cols: int = COLS,
    icon_size: int = ICON_SIZE,
    watermark_url: str = "",
    bg_color: tuple[int, int, int] = (30, 30, 30),
) -> str:
    """
    Merge all PNG files in icons_dir into a grid image saved at out_path.

    Parameters
    ----------
    icons_dir   : Directory containing <id>.png icon files
    out_path    : Output file path (jpg or png)
    cols        : Number of icons per row
    icon_size   : Pixel size of each icon cell
    watermark_url : URL or local path of a watermark to append as an extra cell
    bg_color    : RGB background fill colour

    Returns
    -------
    str : The resolved out_path
    """
    icon_files = sorted([
        os.path.join(icons_dir, f)
        for f in os.listdir(icons_dir)
        if f.lower().endswith(".png")
    ])

    if not icon_files:
        raise ValueError(f"No PNG files found in {icons_dir}")

    # Load watermark (appended as the last "icon cell" if present)
    wm_img = _load_watermark(watermark_url)
    if wm_img:
        # Save to icons dir with a guaranteed last-sort key
        wm_path = os.path.join(icons_dir, "zzz_watermark.png")
        wm_img.save(wm_path)
        icon_files.append(wm_path)

    total = len(icon_files)
    rows  = math.ceil(total / cols)

    grid_w = cols * icon_size
    grid_h = rows * icon_size

    canvas = Image.new("RGB", (grid_w, grid_h), bg_color)

    for idx, path in enumerate(icon_files):
        try:
            icon = Image.open(path).convert("RGB").resize((icon_size, icon_size), RESAMPLE)
        except Exception:
            icon = Image.new("RGB", (icon_size, icon_size), (80, 80, 80))

        row = idx // cols
        col = idx % cols
        canvas.paste(icon, (col * icon_size, row * icon_size))

    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)

    # Determine format
    fmt = "JPEG" if out_path.lower().endswith((".jpg", ".jpeg")) else "PNG"
    save_kwargs = {"quality": 92, "optimize": True} if fmt == "JPEG" else {}
    canvas.save(out_path, fmt, **save_kwargs)

    # Clean up watermark temp file
    if wm_img:
        try:
            os.remove(wm_path)
        except OSError:
            pass

    return out_path
