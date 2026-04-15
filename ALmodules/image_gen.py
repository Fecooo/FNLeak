"""
image_gen.py — Pillow 10+ compatible cosmetic card generator.

Key fixes vs the original AutoLeak:
  - PIL.Image.ANTIALIAS removed in Pillow 10 → use PIL.Image.LANCZOS
  - font.getsize() removed → use font.getbbox()
  - draw.textsize() removed → use draw.textbbox()
  - Consolidated all icon-type branches into one function instead of
    copy-pasted newcnew_fnbrapi / generate_cosmetics / newiconsfnapi etc.
"""

from __future__ import annotations

import io
import os
from enum import Enum
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── constants ─────────────────────────────────────────────────────────────────
SIZE        = 512
RESAMPLE    = Image.LANCZOS        # Was PIL.Image.ANTIALIAS (removed in Pillow 10)
FALLBACK_BG = (50, 50, 80, 255)   # Dark blue-grey RGBA


class CardStyle(str, Enum):
    STANDARD = "standard"
    CLEAN    = "clean"
    NEW      = "new"
    CATABA   = "cataba"
    LARGE    = "large"


# ── Pillow-compat helpers ─────────────────────────────────────────────────────

def text_size(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    """Return (width, height) of rendered text — Pillow 10+ compatible."""
    bbox = font.getbbox(text)          # (left, top, right, bottom)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """Return (width, height) via draw.textbbox — Pillow 10+ compatible."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def centered_x(img_width: int, text: str, font: ImageFont.FreeTypeFont) -> int:
    w, _ = text_size(font, text)
    return (img_width - w) // 2


# ── font loader ───────────────────────────────────────────────────────────────

def load_font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType/OpenType font, falling back to PIL's built-in default."""
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    # Pillow 10+ default font is bitmap but always available
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10 doesn't accept size kwarg on load_default
        return ImageFont.load_default()


# ── icon downloader ───────────────────────────────────────────────────────────

def fetch_icon(url: str) -> Image.Image:
    """Download and return a 512×512 RGBA icon image."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        return img.resize((SIZE, SIZE), RESAMPLE)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch icon from {url}: {e}") from e


# ── rarity background loader ──────────────────────────────────────────────────

def load_rarity_bg(icon_type: str, rarity: str) -> Image.Image:
    """
    Load a rarity background PNG from rarities/<icon_type>/<rarity>.png.
    Falls back to 'common' if the specific rarity file is missing.
    Falls back to a generated solid-colour image if even common is missing.
    """
    base = os.path.join("rarities", icon_type)
    for name in (rarity, "common"):
        path = os.path.join(base, f"{name}.png")
        if os.path.exists(path):
            try:
                return Image.open(path).convert("RGBA").resize((SIZE, SIZE), RESAMPLE)
            except Exception:
                pass
    # Last resort: solid colour
    return Image.new("RGBA", (SIZE, SIZE), FALLBACK_BG)


def load_rarity_layer(icon_type: str, prefix: str, rarity: str) -> Optional[Image.Image]:
    """Load an optional overlay/border layer (e.g. border{rarity}.png)."""
    base = os.path.join("rarities", icon_type)
    for name in (rarity, "common"):
        path = os.path.join(base, f"{prefix}{name}.png")
        if os.path.exists(path):
            try:
                return Image.open(path).convert("RGBA").resize((SIZE, SIZE), RESAMPLE)
            except Exception:
                pass
    return None


# ── source tag helper ─────────────────────────────────────────────────────────

def get_source_tag(item: dict, build: str = "") -> str:
    """Extract a human-readable source tag from gameplay tags."""
    tags = item.get("gameplayTags") or []
    for tag in tags:
        if "Cosmetics.Source.ItemShop" in tag:
            return "Cosmetics.Source.ItemShop"
        if "BattlePass.Paid" in tag:
            return f"Cosmetics.Source.Season{build}.BattlePass.Paid"
        if "Cosmetics.Set." in tag:
            set_val = (item.get("set") or {}).get("value", "")
            return f"Cosmetics.Set.{set_val.replace(' ', '')}"
    return ""


# ── per-style renderers ───────────────────────────────────────────────────────

def _render_standard(img: Image.Image, item: dict,
                      font_main: str, font_side: str,
                      watermark: str, show_source: bool, build: str) -> Image.Image:
    """Standard style: centred name + description + type text."""
    draw  = ImageDraw.Draw(img)
    name  = (item.get("name") or "TBD").upper()
    desc  = item.get("description") or ""
    cos_t = (item.get("type") or {}).get("displayValue", "")
    item_id = item.get("id", "")

    name_len = len(name)
    fs = 40 if name_len <= 20 else (30 if name_len <= 30 else 20)

    font  = load_font(font_main, fs)
    fw, _ = draw_text_size(draw, name, font)
    draw.text(((SIZE - fw) / 2, 390), name, font=font, fill="white")

    font_sm = load_font(font_main, 20)
    fw, _ = draw_text_size(draw, cos_t, font_sm)
    draw.text(((SIZE - fw) / 2, 430), cos_t, font=font_sm, fill="white")

    font_xs = load_font(font_side, 15)
    fw, _ = draw_text_size(draw, desc, font_xs)
    draw.text(((SIZE - fw) / 2, 455), desc, font=font_xs, fill="white")

    fw, _ = draw_text_size(draw, item_id, font_xs)
    draw.text(((SIZE - fw) / 2, 475), item_id, font=font_xs, fill="white")

    if watermark:
        wm_font = load_font(font_main, 25)
        draw.text((10, 9), watermark, font=wm_font, fill="white")

    return img


def _render_clean(img: Image.Image, item: dict,
                  font_main: str, font_side: str,
                  watermark: str, show_source: bool, build: str) -> Image.Image:
    """Clean style: left-aligned name + type."""
    draw  = ImageDraw.Draw(img)
    name  = item.get("name") or "TBD"
    cos_t = (item.get("type") or {}).get("displayValue", "")

    name_len = len(name)
    fs = 40 if name_len <= 20 else (30 if name_len <= 30 else 20)

    font = load_font(font_main, fs)
    draw.text((25, 440), name, font=font, fill="white")

    font_type = load_font(font_main, 30)
    draw.text((25, 402), cos_t, font=font_type, fill="white")

    if watermark:
        wm_font = load_font(font_main, 25)
        draw.text((30, 30), watermark, font=wm_font, fill="white")

    return img


def _render_new(img: Image.Image, item: dict,
                font_main: str, font_side: str,
                watermark: str, show_source: bool, build: str) -> Image.Image:
    """
    'New' style: large centred name + description + set text.
    Mirrors the newcnew_fnbrapi / newiconsfnapi logic from the original.
    """
    draw = ImageDraw.Draw(img)
    cx   = SIZE // 2   # horizontal centre

    name = (item.get("name") or "TBD").upper()
    desc = item.get("description") or "TBD"
    set_text = (item.get("set") or {}).get("text")

    # --- Name ---
    if len(name) > 17:
        name_font = load_font(font_main, 45)
        name_y    = 440
        desc_nudge = True
    else:
        name_font = load_font(font_main, 60)
        name_y    = 450
        desc_nudge = False

    draw.text((cx, name_y), name, font=name_font, fill="white", anchor="ms")

    # --- Description ---
    desc_len = len(desc)
    if desc_len > 95:
        d_font = load_font(font_side, 10)
        d_y    = 470
    elif desc_len > 45:
        d_font = load_font(font_side, 14)
        d_y    = (474 if set_text else 480) - (8 if desc_nudge else 0)
    else:
        d_font = load_font(font_side, 16)
        d_y    = (475 if set_text else 480) - (2 if desc_nudge else 0)

    draw.text((cx, d_y), desc, font=d_font, fill="white", anchor="ms")

    # --- Set text ---
    if set_text:
        s_font = load_font(font_side, 15)
        draw.text((cx, 500), set_text, font=s_font, fill="white", anchor="ms")

    # --- Watermark ---
    if watermark:
        wm_font = load_font(font_main, 25)
        draw.text((10, 9), watermark, font=wm_font, fill="white")
        wm_y = 30
    else:
        wm_y = 10

    # --- Source tag ---
    if show_source:
        tag = get_source_tag(item, build)
        if tag:
            tag_font = load_font(font_main, 15)
            draw.text((10, wm_y), tag, font=tag_font, fill="white")

    return img


def _render_cataba(img: Image.Image, item: dict,
                   font_main: str, font_side: str,
                   watermark: str, show_source: bool, build: str) -> Image.Image:
    """
    'Cataba' style: centred name + description (upper-cased) + backend type badge.
    Matches the catabaicons / catabasearch logic.
    """
    draw        = ImageDraw.Draw(img)
    name        = (item.get("name") or "TBD").upper()
    description = (item.get("description") or "").upper()
    backend_t   = (item.get("type") or {}).get("value", "").upper()

    # Use BurbankBigRegular-BlackItalic if available, else fall back to font_main
    cataba_font_path = os.path.join("fonts", "BurbankBigRegular-BlackItalic.otf")
    if not os.path.exists(cataba_font_path):
        cataba_font_path = font_main

    name_font = load_font(cataba_font_path, 31)
    desc_font = load_font(cataba_font_path, 10)
    type_font = load_font(cataba_font_path, 14)

    draw.text((256, 472), name,        font=name_font, fill="white", anchor="ms")
    draw.text((256, 501), description, font=desc_font, fill="white", anchor="ms")
    draw.text((6,   495), backend_t,   font=type_font, fill="white")

    return img


# ── cataba layer compositor ───────────────────────────────────────────────────

def _composite_cataba(rarity: str, icon_img: Image.Image, has_variants: bool) -> Image.Image:
    """Build the cataba layered composite (background → overlay → icon → foreground → rarity badge)."""
    base = os.path.join("rarities", "cataba")

    def try_open(name: str) -> Optional[Image.Image]:
        path = os.path.join(base, name)
        if os.path.exists(path):
            try:
                return Image.open(path).resize((SIZE, SIZE), RESAMPLE).convert("RGBA")
            except Exception:
                pass
        return None

    canvas = Image.new("RGB", (SIZE, SIZE))

    # Layer 1: rarity background
    layer = try_open(f"{rarity}.png") or try_open("common.png") or Image.new("RGBA", (SIZE, SIZE), FALLBACK_BG)
    canvas.paste(layer)

    # Layer 2: overlay
    overlay = try_open(f"{rarity}_overlay.png") or try_open("common_overlay.png")
    if overlay:
        canvas.paste(overlay, (0, 0), overlay)

    # Layer 3: icon
    canvas.paste(icon_img, (0, 0), icon_img)

    # Layer 4: foreground
    fg = try_open(f"{rarity}_background.png") or try_open("common_background.png")
    if fg:
        canvas.paste(fg, (0, 0), fg)

    # Layer 5: rarity badge
    badge = try_open(f"{rarity}_rarity.png") or try_open("placeholder_rarity.png")
    if badge:
        canvas.paste(badge, (0, 0), badge)

    # Layer 6: variants plus-sign
    if has_variants:
        plus = try_open("PlusSign.png")
        if plus:
            canvas.paste(plus, (0, 0), plus)

    return canvas


# ── main public function ──────────────────────────────────────────────────────

def generate_card(
    item: dict,
    icon_url: str,
    out_path: str,
    icon_type: str,
    font_main: Optional[str],
    font_side: Optional[str],
    watermark: str = "",
    show_source: bool = True,
    build: str = "",
) -> None:
    """
    Generate a styled cosmetic card image and write it to out_path.

    Parameters
    ----------
    item       : Fortnite-API cosmetic item dict
    icon_url   : URL of the cosmetic's icon/featured image
    out_path   : Where to save the finished PNG
    icon_type  : One of 'standard', 'clean', 'new', 'cataba', 'large'
    font_main  : Path to primary font (None → PIL default)
    font_side  : Path to secondary font (None → PIL default)
    watermark  : Text watermark drawn top-left
    show_source: Whether to draw the gameplay source tag
    build      : Fortnite version label (used in source tag)
    """
    rarity = (item.get("rarity") or {}).get("value", "common").lower()

    # ── 1. Download icon ──────────────────────────────────────────────────────
    icon_img = fetch_icon(icon_url)   # 512×512 RGBA

    # ── 2. Build base composite ───────────────────────────────────────────────
    if icon_type == CardStyle.CATABA:
        has_variants = bool(item.get("variants"))
        img = _composite_cataba(rarity, icon_img, has_variants)
        img = img.convert("RGB")      # cataba canvas is RGB
    else:
        bg     = load_rarity_bg(icon_type, rarity)
        border = load_rarity_layer(icon_type, "border", rarity)

        # Paste icon onto background
        canvas = bg.copy()
        canvas.paste(icon_img, (0, 0), icon_img)

        if border:
            canvas.paste(border, (0, 0), border)

        img = canvas.convert("RGB")

    # ── 3. Draw text overlay ──────────────────────────────────────────────────
    style_renderers = {
        CardStyle.STANDARD: _render_standard,
        CardStyle.CLEAN:    _render_clean,
        CardStyle.NEW:      _render_new,
        CardStyle.CATABA:   _render_cataba,
        CardStyle.LARGE:    _render_new,   # 'large' uses the same text layout as 'new'
    }
    renderer = style_renderers.get(icon_type, _render_new)
    img = renderer(img, item, font_main, font_side, watermark, show_source, build)

    # ── 4. Save ───────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    img.save(out_path)
