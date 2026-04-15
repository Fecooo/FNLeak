"""
compressor.py — Reduce an image's file size until it fits Twitter's 5 MB limit.

The original had separate compress_* functions for every use case.
This module provides one general-purpose function used everywhere.
"""

from __future__ import annotations

import os

from PIL import Image

RESAMPLE        = Image.LANCZOS
TWITTER_MAX_MB  = 4.5   # Stay safely under Twitter's 5 MB limit
TWITTER_MAX_BYTES = int(TWITTER_MAX_MB * 1024 * 1024)


def compress_image(
    src_path: str,
    max_bytes: int = TWITTER_MAX_BYTES,
    min_quality: int = 30,
    scale_step: float = 0.85,
) -> str:
    """
    Compress an image so its file size is <= max_bytes.

    Strategy:
      1. First try progressively lowering JPEG quality (100 → min_quality).
      2. If still too large, scale down dimensions by scale_step each round.

    Returns the path to the compressed file (overwrites the original in-place).
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    if os.path.getsize(src_path) <= max_bytes:
        return src_path

    img = Image.open(src_path).convert("RGB")

    # ── Phase 1: reduce JPEG quality ─────────────────────────────────────────
    for quality in range(90, min_quality - 1, -5):
        img.save(src_path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(src_path) <= max_bytes:
            return src_path

    # ── Phase 2: scale down dimensions ───────────────────────────────────────
    w, h = img.size
    for _ in range(10):          # max 10 scaling rounds
        w = int(w * scale_step)
        h = int(h * scale_step)
        if w < 64 or h < 64:
            break
        resized = img.resize((w, h), RESAMPLE)
        resized.save(src_path, "JPEG", quality=min_quality, optimize=True)
        if os.path.getsize(src_path) <= max_bytes:
            return src_path

    # Best effort — return whatever we have
    return src_path
