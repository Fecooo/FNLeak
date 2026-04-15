"""
shop.py — Fortnite Item Shop image generation + shop-sections watcher.

Generates a grid image of all currently listed shop items and optionally
tweets it.  Also provides a polling loop that tweets whenever the shop
sections layout changes.
"""

from __future__ import annotations

import io
import os
import time
from typing import Optional

import requests
from colorama import Fore
from PIL import Image, ImageDraw, ImageFont

from ALmodules.image_gen import generate_card, load_font, RESAMPLE, SIZE
from ALmodules.merger import merge_icons
from ALmodules.compressor import compress_image
from ALmodules.setup import resolve_font

FORTNITE_API = "https://fortnite-api.com"


def _get_json(url: str, params: dict | None = None, timeout: int = 15) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(Fore.RED + f"  API error: {e}")
        return None


def _get_image_url(entry: dict, use_featured: bool) -> str:
    imgs = entry.get("images") or {}
    if use_featured and imgs.get("featured"):
        return imgs["featured"]
    return imgs.get("icon") or "https://i.ibb.co/KyvMydQ/do-Not-Delete.png"


# ── shop generation ───────────────────────────────────────────────────────────

def generate_shop(cfg: dict, tw) -> None:
    """Generate an Item Shop image, save it, and optionally tweet it."""
    language  = cfg["language"]
    icon_type = cfg["iconType"]
    use_feat  = cfg["useFeaturedIfAvailable"]
    watermark = cfg["watermark"]
    font_main = resolve_font(cfg["imageFont"])
    font_side = resolve_font(cfg["sideFont"])
    merge_wm  = cfg["MergeWatermarkUrl"]
    name_lbl  = cfg["name"]
    do_merge  = cfg["MergeImages"]
    auto_tw   = cfg["AutoTweetMerged"]

    print(Fore.CYAN + "\nFetching Item Shop…")
    data = _get_json(f"{FORTNITE_API}/v2/shop/br", params={"language": language})
    if not data:
        print(Fore.RED + "Failed to fetch shop.")
        return

    entries = data.get("data", {}).get("featured", {}).get("entries", []) + \
              data.get("data", {}).get("daily", {}).get("entries", [])

    if not entries:
        # Try the combined endpoint (newer API format)
        entries = data.get("data", {}).get("entries", [])

    if not entries:
        print(Fore.RED + "No shop entries found.")
        return

    # Flatten: each entry can have multiple items
    items_flat = []
    for entry in entries:
        items_flat.extend(entry.get("items", []))

    print(Fore.GREEN + f"Found {len(items_flat)} shop items\n")

    # Clear icons dir and generate each card
    try:
        import shutil
        shutil.rmtree("icons")
    except FileNotFoundError:
        pass
    os.makedirs("icons", exist_ok=True)

    ok = 0
    for idx, item in enumerate(items_flat, 1):
        item_id = item.get("id", f"item_{idx}")
        try:
            url = _get_image_url(item, use_feat)
            generate_card(
                item=item,
                icon_url=url,
                out_path=f"icons/{item_id}.png",
                icon_type=icon_type,
                font_main=font_main,
                font_side=font_side,
                watermark=watermark,
                show_source=False,  # Shop items: no source tag
            )
            ok += 1
            print(Fore.CYAN + f"  [{idx}/{len(items_flat)}] {item_id}", end="\r")
        except Exception as e:
            print(Fore.YELLOW + f"\n  Skipped {item_id}: {e}")

    print(Fore.GREEN + f"\nGenerated {ok} shop cards.")

    if do_merge and ok > 0:
        merged = merge_icons("icons", "merged/shop.jpg", watermark_url=merge_wm)
        print(Fore.GREEN + f"Shop image → {merged}")

        if auto_tw and tw.ready:
            text = f"[{name_lbl}] Today's Fortnite Item Shop — {ok} items."
            try:
                tw.tweet_with_media(merged, text)
                print(Fore.GREEN + "Tweeted shop!")
            except Exception as e:
                print(Fore.YELLOW + f"  Compressing and retrying: {e}")
                compress_image(merged)
                try:
                    tw.tweet_with_media(merged, text)
                    print(Fore.GREEN + "Tweeted shop (compressed)!")
                except Exception as e2:
                    print(Fore.RED + f"  Tweet failed: {e2}")
        else:
            print(Fore.WHITE + f"Done. Image saved to {merged}")


# ── shop sections watcher ─────────────────────────────────────────────────────

def _build_sections_image(sections: list, bg_color: str, font_main: Optional[str]) -> Optional[str]:
    """Create a simple text-list image of shop section names."""
    if not sections:
        return None

    line_h = 50
    padding = 20
    height = line_h * len(sections) + padding * 2

    try:
        r = int(bg_color[0:2], 16)
        g = int(bg_color[2:4], 16)
        b = int(bg_color[4:6], 16)
    except (ValueError, IndexError):
        r, g, b = 57, 79, 247  # default blue

    img  = Image.new("RGB", (800, height), (r, g, b))
    draw = ImageDraw.Draw(img)
    font = load_font(font_main, 28)

    for i, section in enumerate(sections):
        name = section.get("sectionId", "") or section.get("landingPriority", str(i))
        draw.text((padding, padding + i * line_h), str(name), font=font, fill="white")

    out = "merged/shop_sections.jpg"
    os.makedirs("merged", exist_ok=True)
    img.save(out, "JPEG", quality=90)
    return out


def watch_shop_sections(cfg: dict, tw) -> None:
    """Poll for shop section layout changes and optionally tweet them."""
    delay     = cfg["BotDelay"]
    language  = cfg["language"]
    name_lbl  = cfg["name"]
    bg_color  = cfg.get("ImageColor", "394ff7")
    font_main = resolve_font(cfg["imageFont"])
    do_image  = cfg.get("ShopSections_Image", True)

    print(Fore.CYAN + f"\n-- Shop Sections Watcher --  (delay={delay}s)")
    print(Fore.YELLOW + "Press Ctrl-C to stop.\n")

    old_sections = None
    count        = 0

    try:
        while True:
            data = _get_json(f"{FORTNITE_API}/v2/shop/br", params={"language": language})
            if data:
                sections = (data.get("data") or {}).get("featured", {}).get("sections", [])
                sections_key = str([s.get("id") or s.get("sectionId") for s in sections])

                if old_sections is None:
                    old_sections = sections_key
                    print(Fore.GREEN + "  Watching shop sections…")
                elif sections_key != old_sections:
                    print(Fore.CYAN + "\n  [!] Shop sections changed!")
                    tweet_text = f"[{name_lbl}] Fortnite Item Shop sections have updated!"

                    if do_image and sections:
                        img_path = _build_sections_image(sections, bg_color, font_main)
                        if img_path and tw.ready:
                            try:
                                tw.tweet_with_media(img_path, tweet_text)
                                print(Fore.GREEN + "  Tweeted sections image!")
                            except Exception as e:
                                print(Fore.RED + f"  Tweet failed: {e}")
                        elif tw.ready:
                            tw.tweet(tweet_text)
                        else:
                            print(Fore.YELLOW + f"  (Twitter not configured)\n{tweet_text}")
                    elif tw.ready:
                        tw.tweet(tweet_text)
                    else:
                        print(Fore.YELLOW + f"  (Twitter not configured)\n{tweet_text}")
                    old_sections = sections_key
                else:
                    count += 1
                    print(Fore.GREEN + f"  Watching… ({count})", end="\r")
            time.sleep(delay)
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\nShop sections watcher stopped.")
