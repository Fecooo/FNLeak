"""
FNLeak GUI — CustomTkinter-based frontend.
Runs on macOS (and Windows/Linux) with a dark, Fortnite-inspired theme.

Run:  python3 gui.py
"""

from __future__ import annotations

import io
import json
import os
import re
import queue
import subprocess
import webbrowser
import sys
import threading
import time
from datetime import datetime
from typing import Optional

# ── PyInstaller bundle: set up working directory ──────────────────────────────
# When macOS launches a .app the CWD is ~, not inside the bundle.
# We keep read-only assets in the bundle (sys._MEIPASS) and copy them + all
# writable runtime dirs into ~/Library/Application Support/FNLeak on first run.
if hasattr(sys, "_MEIPASS"):
    import shutil as _shutil
    _BUNDLE = sys._MEIPASS
    _DATA   = os.path.expanduser("~/Library/Application Support/FNLeak")
    os.makedirs(_DATA, exist_ok=True)

    # Copy read-only asset trees once (fonts, rarities, assets)
    for _d in ("fonts", "rarities", "assets"):
        _src, _dst = os.path.join(_BUNDLE, _d), os.path.join(_DATA, _d)
        if os.path.isdir(_src) and not os.path.isdir(_dst):
            _shutil.copytree(_src, _dst)

    # Copy default config files if not already customised
    for _f in ("settings.json", "shop_history.json"):
        _dst = os.path.join(_DATA, _f)
        _src = os.path.join(_BUNDLE, _f)
        if not os.path.exists(_dst) and os.path.exists(_src):
            _shutil.copy(_src, _dst)

    # Ensure writable runtime dirs exist
    for _d in ("cache", "icons", "merged"):
        os.makedirs(os.path.join(_DATA, _d), exist_ok=True)

    os.chdir(_DATA)
    del _shutil, _BUNDLE, _DATA, _d, _f, _src, _dst

import tkinter as tk
import customtkinter as ctk
import requests
from PIL import Image as PILImage

# ── back-end imports ──────────────────────────────────────────────────────────
from ALmodules.setup import ensure_directories, ensure_rarity_assets, resolve_font
from ALmodules.image_gen import generate_card
from ALmodules.merger import merge_icons
from ALmodules.compressor import compress_image
from ALmodules.twitter_client import TwitterClient

# ── theme ─────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Dark grey / bone-white palette
C = {
    "bg":          "#141414",
    "sidebar":     "#0f0f0f",
    "card":        "#1e1e1e",
    "border":      "#2d2d2d",
    "accent":      "#3a3a3a",   # dark grey
    "accent_btn":  "#4d4d4d",   # mid grey
    "blue":        "#3275c4",   # Rare blue
    "green":       "#2ea043",   # Success / Spotify
    "orange":      "#c2712c",   # Legendary
    "red":         "#da3633",   # Error / stop
    "text":        "#f0ece6",   # bone white
    "text_dim":    "#808080",   # neutral grey
    "input_bg":    "#111111",
}

FORTNITE_API = "https://fortnite-api.com"
SETTINGS_PATH = "settings.json"

RARITY_COLORS = {
    "common": "#636363", "uncommon": "#31a21f", "rare": "#3275c4",
    "epic": "#7d3dba", "legendary": "#c2712c", "mythic": "#e7c03a",
    "exotic": "#21c5e7", "slurp": "#00bcd4",
}

PAK_REGEX = re.compile(r'pakchunk\d{4}-WindowsClient\.pak')


# ── console redirector ─────────────────────────────────────────────────────────
class _ConsoleRedirector:
    """Pushes anything written to stdout/stderr into a thread-safe queue."""
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str):
        if text.strip():
            self._q.put(text)

    def flush(self):
        pass


# ── settings helpers ───────────────────────────────────────────────────────────
DEFAULTS = {
    "name": "FNLeak", "footer": "#Fortnite", "language": "en",
    "imageFont": "BurbankBigCondensed-Black.otf", "sideFont": "OpenSans-Regular.ttf",
    "placeholderUrl": "https://i.imgur.com/W22Foja.png", "watermark": "",
    "useFeaturedIfAvailable": False, "iconType": "new",
    "twitAPIKey": "", "twitAPISecretKey": "", "twitAccessToken": "", "twitAccessTokenSecret": "",
    "tweetUpdate": False, "tweetAes": False, "TweetSearch": False, "AutoTweetMerged": False,
    "MergeImages": True, "MergeWatermarkUrl": "", "ShowDescOnNPCs": False,
    "ShopSections_Image": True, "ImageColor": "394ff7", "showitemsource": True,
    "CreatorCode": "", "apikey": "", "BotDelay": 30, "ShowValues_AtStart": False,
    "TwitterSupport": False,
    "autoOpenImage": False,
}


def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH) as f:
            user = json.load(f)
        for k, v in user.items():
            if not k.startswith("_"):
                cfg[k] = v
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    for k in ("useFeaturedIfAvailable", "tweetUpdate", "tweetAes", "TweetSearch",
               "MergeImages", "AutoTweetMerged", "ShowDescOnNPCs", "ShopSections_Image",
               "showitemsource", "TwitterSupport", "ShowValues_AtStart", "autoOpenImage"):
        if isinstance(cfg[k], str):
            cfg[k] = cfg[k].strip().lower() in ("true", "1", "yes")
    return cfg


def save_settings(cfg: dict):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def get_image_url(item: dict, use_featured: bool) -> str:
    imgs = item.get("images") or {}
    if use_featured and imgs.get("featured"):
        return imgs["featured"]
    return imgs.get("icon") or "https://i.ibb.co/KyvMydQ/do-Not-Delete.png"


def delete_icons():
    import shutil
    try:
        shutil.rmtree("icons")
    except FileNotFoundError:
        pass
    os.makedirs("icons", exist_ok=True)


def _mono_font(size: int) -> ctk.CTkFont:
    """Return a monospace CTkFont that exists on macOS, Windows, and Linux."""
    if sys.platform == "darwin":
        family = "Menlo"
    elif sys.platform == "win32":
        family = "Consolas"
    else:
        family = "DejaVu Sans Mono"
    return ctk.CTkFont(family=family, size=size)


def open_file(path: str):
    """Open a file with the system default app (macOS/Linux/Windows)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=True)
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.run(["xdg-open", path], check=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Page base class
# ══════════════════════════════════════════════════════════════════════════════
class _Page(ctk.CTkFrame):
    def __init__(self, master, app: "FNLeakApp", **kwargs):
        super().__init__(master, fg_color=C["bg"], **kwargs)
        self.app = app

    def on_show(self):
        """Called when this page becomes visible."""
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard page
# ══════════════════════════════════════════════════════════════════════════════
class DashboardPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._news_img_refs = []

        # Title
        ctk.CTkLabel(self, text="FNLeak", font=ctk.CTkFont(size=32, weight="bold"),
                     text_color=C["text"]).pack(pady=(24, 4))
        ctk.CTkLabel(self, text="Fortnite Cosmetic Leak Tool",
                     font=ctk.CTkFont(size=14), text_color=C["text_dim"]).pack(pady=(0, 16))

        # Stat cards row
        self._stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_frame.pack(fill="x", padx=40, pady=(0, 8))

        self._build_label   = self._stat_card("Current Build",  "—",          C["blue"])
        self._items_label   = self._stat_card("New Items",      "—",          C["accent"])
        self._aes_label     = self._stat_card("AES / Patch",    "Loading…",   C["orange"])
        self._twitter_label = self._stat_card("Twitter / X",    "Checking…",  C["text_dim"])

        # API status bar
        api_bar = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=8)
        api_bar.pack(fill="x", padx=40, pady=(4, 0))
        ctk.CTkLabel(api_bar, text="fortnite-api.com",
                     font=ctk.CTkFont(size=12), text_color=C["text_dim"]).pack(
                         side="left", padx=(12, 6), pady=8)
        self._api_dot = ctk.CTkLabel(api_bar, text="●",
                                      font=ctk.CTkFont(size=14),
                                      text_color=C["text_dim"])
        self._api_dot.pack(side="left")
        self._api_status_lbl = ctk.CTkLabel(api_bar, text="Checking…",
                                             font=ctk.CTkFont(size=12),
                                             text_color=C["text_dim"])
        self._api_status_lbl.pack(side="left", padx=(4, 0))

        # Response time (right side)
        self._api_ping_lbl = ctk.CTkLabel(api_bar, text="",
                                           font=_mono_font(11),
                                           text_color=C["text_dim"])
        self._api_ping_lbl.pack(side="right", padx=12)

        # Quick-action buttons (2 rows of 4)
        btn_outer = ctk.CTkFrame(self, fg_color="transparent")
        btn_outer.pack(pady=(8, 12))

        _actions = [
            ("Generate",     "generate"),
            ("Search",       "search"),
            ("Item Shop",    "shop"),
            ("Jam Tracks",   "jamtracks"),
            ("Player Stats", "stats"),
            ("Map Viewer",   "map"),
            ("Game Modes",   "playlists"),
            ("Creator Code", "creator"),
        ]

        row1 = ctk.CTkFrame(btn_outer, fg_color="transparent")
        row1.pack()
        row2 = ctk.CTkFrame(btn_outer, fg_color="transparent")
        row2.pack(pady=(6, 0))

        for i, (text, page) in enumerate(_actions):
            parent = row1 if i < 4 else row2
            ctk.CTkButton(
                parent, text=text, width=148, height=38,
                fg_color=C["card"], hover_color=C["border"],
                text_color=C["text"],
                font=ctk.CTkFont(size=12, weight="bold"),
                border_width=1, border_color=C["border"],
                command=lambda p=page: app.show_page(p),
            ).pack(side="left", padx=4)

        # AES section
        self._aes_dynamic_keys: list = []
        self._aes_expanded = False

        aes_outer = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=8)
        aes_outer.pack(fill="x", padx=40, pady=(0, 4))

        # Main key row
        aes_strip = ctk.CTkFrame(aes_outer, fg_color="transparent")
        aes_strip.pack(fill="x")

        ctk.CTkLabel(aes_strip, text="MAIN AES KEY",
                     font=ctk.CTkFont(size=10), text_color=C["text_dim"]).pack(side="left", padx=12, pady=8)
        self._aes_key_lbl = ctk.CTkLabel(aes_strip, text="—",
                                          font=_mono_font(11), text_color=C["green"])
        self._aes_key_lbl.pack(side="left", padx=4, pady=8)
        self._aes_copy_btn = ctk.CTkButton(
            aes_strip, text="Copy", width=50, height=22,
            fg_color=C["border"], hover_color=C["input_bg"],
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
            command=lambda: self._copy_to_clipboard(self._aes_key_lbl.cget("text"))
        )
        self._aes_copy_btn.pack(side="left", padx=4)

        self._dyn_toggle_btn = ctk.CTkButton(
            aes_strip, text="▼  Dynamic Keys (—)", width=160, height=22,
            fg_color=C["border"], hover_color=C["input_bg"],
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
            command=self._toggle_aes_panel
        )
        self._dyn_toggle_btn.pack(side="right", padx=12, pady=8)

        # Collapsible dynamic keys panel
        self._aes_panel = ctk.CTkFrame(aes_outer, fg_color=C["input_bg"], corner_radius=0)
        # (hidden by default — shown on toggle)

        # News feed
        ctk.CTkLabel(self, text="📰  Fortnite News",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text_dim"]).pack(anchor="w", padx=40, pady=(0, 6))

        self._news_frame = ctk.CTkScrollableFrame(
            self, fg_color=C["card"], corner_radius=8, height=160,
            orientation="horizontal",
            scrollbar_button_color=C["border"]
        )
        self._news_frame.pack(fill="x", padx=40, pady=(0, 12))

        ctk.CTkLabel(self._news_frame, text="Loading news…",
                     text_color=C["text_dim"]).pack(padx=12, pady=20)

    def _stat_card(self, title: str, value: str, color: str) -> ctk.CTkLabel:
        card = ctk.CTkFrame(self._stats_frame, fg_color=C["card"],
                            corner_radius=10, border_width=1, border_color=C["border"])
        card.pack(side="left", expand=True, fill="both", padx=6)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11),
                     text_color=C["text_dim"]).pack(pady=(14, 2))
        val_lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=20, weight="bold"),
                               text_color=color)
        val_lbl.pack(pady=(0, 14))
        return val_lbl

    def on_show(self):
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def _fetch_all(self):
        # ── Cosmetics / build ─────────────────────────────────────────────────
        try:
            r = requests.get(f"{FORTNITE_API}/v2/cosmetics/new",
                             params={"language": self.app.cfg.get("language", "en")}, timeout=8)
            data = r.json()["data"]
            build = data.get("build", "?")
            try:
                build = build.split("++Fortnite+Release-")[1].split("-CL-")[0]
            except Exception:
                pass
            count = len(data.get("items", {}).get("br", []))
            self.after(0, lambda: self._build_label.configure(text=build))
            self.after(0, lambda: self._items_label.configure(text=str(count)))
        except Exception:
            self.after(0, lambda: self._build_label.configure(text="Error"))

        # ── AES keys + API status ─────────────────────────────────────────────
        try:
            t0 = time.time()
            r  = requests.get(f"{FORTNITE_API}/v2/aes", timeout=8)
            r.raise_for_status()
            ping_ms = int((time.time() - t0) * 1000)
            aes = r.json()["data"]
            raw_build = aes.get("build", "")
            try:
                patch = raw_build.split("++Fortnite+Release-")[1].split("-CL-")[0]
            except Exception:
                patch = raw_build[:20]
            main_key  = aes.get("mainKey", "—")
            dyn_keys  = aes.get("dynamicKeys") or []
            self._aes_dynamic_keys = sorted(
                (key for key in dyn_keys if key.get("pakFilename") and PAK_REGEX.match(key.get("pakFilename"))),
                key=lambda key: key["pakFilename"],
            )
            dyn_count = len(self._aes_dynamic_keys)
            self.after(0, lambda: self._aes_label.configure(text=patch or "—"))
            self.after(0, lambda: self._aes_key_lbl.configure(text=main_key))
            self.after(0, lambda n=dyn_count: self._dyn_toggle_btn.configure(
                text=f"▼  Dynamic Keys ({n})"))
            # API is up
            self.after(0, lambda p=ping_ms: (
                self._api_dot.configure(text_color=C["green"]),
                self._api_status_lbl.configure(text="Online", text_color=C["green"]),
                self._api_ping_lbl.configure(text=f"{p} ms", text_color=C["text_dim"]),
            ))
        except Exception:
            self.after(0, lambda: self._aes_label.configure(text="Error"))
            self.after(0, lambda: (
                self._api_dot.configure(text_color=C["red"]),
                self._api_status_lbl.configure(text="Offline", text_color=C["red"]),
                self._api_ping_lbl.configure(text="", text_color=C["text_dim"]),
            ))

        # ── Twitter ───────────────────────────────────────────────────────────
        tw_ok    = self.app.tw and self.app.tw.ready
        tw_text  = "Connected" if tw_ok else "Not configured"
        tw_color = C["green"] if tw_ok else C["text_dim"]
        self.after(0, lambda: self._twitter_label.configure(text=tw_text, text_color=tw_color))

        # ── News ──────────────────────────────────────────────────────────────
        try:
            r = requests.get(f"{FORTNITE_API}/v2/news",
                             params={"language": self.app.cfg.get("language", "en")}, timeout=8)
            motds = (r.json().get("data") or {}).get("br", {}).get("motds") or []
            self.after(0, lambda m=motds: self._populate_news(m))
        except Exception:
            pass

    def _populate_news(self, motds: list):
        # Clear placeholder
        for w in self._news_frame.winfo_children():
            w.destroy()
        self._news_img_refs.clear()

        for item in motds[:8]:
            if item.get("hidden"):
                continue
            card = ctk.CTkFrame(self._news_frame, fg_color=C["input_bg"],
                                corner_radius=8, width=220)
            card.pack(side="left", padx=6, pady=8, fill="y")
            card.pack_propagate(False)

            # Image
            img_url = item.get("tileImage") or item.get("image")
            if img_url:
                threading.Thread(target=self._load_news_img,
                                 args=(card, img_url), daemon=True).start()

            ctk.CTkLabel(card, text=item.get("title", ""),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["text"], wraplength=200).pack(padx=8, pady=(4, 2))
            ctk.CTkLabel(card, text=item.get("body", ""),
                         font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                         wraplength=200, justify="left").pack(padx=8, pady=(0, 8))

    def _load_news_img(self, card, url: str):
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            pil = PILImage.open(io.BytesIO(r.content)).convert("RGB")
            pil = pil.resize((210, 90), PILImage.LANCZOS)
            ctkimg = ctk.CTkImage(light_image=pil, dark_image=pil, size=(210, 90))
            self._news_img_refs.append(ctkimg)
            lbl = ctk.CTkLabel(card, text="", image=ctkimg)
            self.after(0, lambda l=lbl: l.pack(padx=5, pady=(8, 2)))
        except Exception:
            pass

    # ── AES helpers ───────────────────────────────────────────────────────────
    def _toggle_aes_panel(self):
        self._aes_expanded = not self._aes_expanded
        if self._aes_expanded:
            self._populate_aes_panel()
            self._aes_panel.pack(fill="x", padx=0, pady=(0, 4))
            self._dyn_toggle_btn.configure(
                text=f"▲  Dynamic Keys ({len(self._aes_dynamic_keys)})")
        else:
            self._aes_panel.pack_forget()
            self._dyn_toggle_btn.configure(
                text=f"▼  Dynamic Keys ({len(self._aes_dynamic_keys)})")

    def _populate_aes_panel(self):
        for w in self._aes_panel.winfo_children():
            w.destroy()

        if not self._aes_dynamic_keys:
            ctk.CTkLabel(self._aes_panel, text="No dynamic keys available.",
                         text_color=C["text_dim"],
                         font=ctk.CTkFont(size=11)).pack(padx=12, pady=8)
            return

        # Scrollable inner list (max height so it doesn't eat the whole dashboard)
        scroll = ctk.CTkScrollableFrame(
            self._aes_panel, fg_color="transparent",
            height=min(len(self._aes_dynamic_keys) * 36, 220),
            scrollbar_button_color=C["border"]
        )
        scroll.pack(fill="x", padx=0)

        for dk in self._aes_dynamic_keys:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)

            filename = dk.get("pakFilename", "unknown")
            key_val  = dk.get("key", "—")
            short_fn = filename.replace("WindowsClient.", "").replace("-", " ")

            ctk.CTkLabel(row, text=short_fn,
                         font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                         width=220, anchor="w").pack(side="left", padx=(0, 6))

            key_lbl = ctk.CTkLabel(row, text=key_val[:32] + "…",
                                    font=_mono_font(10), text_color=C["green"],
                                    anchor="w")
            key_lbl.pack(side="left", expand=True, fill="x")

            ctk.CTkButton(
                row, text="Copy", width=50, height=22,
                fg_color=C["border"], hover_color=C["input_bg"],
                font=ctk.CTkFont(size=10), text_color=C["text_dim"],
                command=lambda k=key_val: self._copy_to_clipboard(k)
            ).pack(side="right", padx=(4, 0))

    def _copy_to_clipboard(self, text: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Generate page
# ══════════════════════════════════════════════════════════════════════════════
class GeneratePage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._running = False

        # ── top bar ───────────────────────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(20, 8))

        ctk.CTkLabel(top, text="Generate Cosmetics",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        self._open_btn = ctk.CTkButton(
            top, text="Open Icons Folder", width=150, height=32,
            fg_color=C["card"], hover_color=C["border"],
            command=lambda: open_file("icons")
        )
        self._open_btn.pack(side="right", padx=4)

        self._gen_btn = ctk.CTkButton(
            top, text="⚡  Generate Now", width=160, height=36,
            fg_color=C["accent_btn"], hover_color=C["accent"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_generate
        )
        self._gen_btn.pack(side="right", padx=4)

        # ── progress ──────────────────────────────────────────────────────────
        prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        prog_frame.pack(fill="x", padx=24, pady=4)
        self._prog_bar = ctk.CTkProgressBar(prog_frame, height=8,
                                             progress_color=C["accent"])
        self._prog_bar.set(0)
        self._prog_bar.pack(fill="x", side="left", expand=True, padx=(0, 12))
        self._prog_label = ctk.CTkLabel(prog_frame, text="Ready",
                                         font=ctk.CTkFont(size=11),
                                         text_color=C["text_dim"], width=80)
        self._prog_label.pack(side="right")

        # ── image grid ────────────────────────────────────────────────────────
        self._grid_frame = ctk.CTkScrollableFrame(
            self, fg_color=C["card"], corner_radius=10,
            scrollbar_button_color=C["border"]
        )
        self._grid_frame.pack(fill="both", expand=True, padx=24, pady=(8, 16))

        self._grid_cols   = 7      # default for square cards; reset when first card arrives
        self._grid_count  = 0
        self._thumb_w     = 140    # thumbnail cell width  (reset on first card)
        self._thumb_h     = 140    # thumbnail cell height (reset on first card)
        self._thumb_cache: list[ctk.CTkImage] = []   # keep references alive

        ctk.CTkLabel(
            self._grid_frame,
            text="Generated cosmetic cards will appear here.",
            text_color=C["text_dim"], font=ctk.CTkFont(size=13)
        ).grid(row=0, column=0, columnspan=7, pady=40)

    # ── internal ──────────────────────────────────────────────────────────────

    def _clear_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._grid_count = 0
        self._thumb_cache.clear()

    def _add_thumb(self, path: str):
        """Add a thumbnail card to the grid (must be called from main thread)."""
        try:
            pil = PILImage.open(path)
            card_w, card_h = pil.size

            # First card determines thumbnail dimensions and column count for
            # the whole batch — keeps square cards square and landscape cards
            # landscape instead of force-squishing everything to 100×100.
            if self._grid_count == 0:
                if card_w > card_h:
                    # Landscape (large style 1793×1080) → wider thumbnails, fewer cols
                    self._thumb_w = 280
                    self._thumb_h = round(280 * card_h / card_w)
                    self._grid_cols = 4
                else:
                    # Square / portrait → tighter grid filling the window
                    self._thumb_w = 140
                    self._thumb_h = round(140 * card_h / card_w)
                    self._grid_cols = 7

            thumb = pil.convert("RGB").resize(
                (self._thumb_w, self._thumb_h), PILImage.LANCZOS
            )
            ctkimg = ctk.CTkImage(
                light_image=thumb, dark_image=thumb,
                size=(self._thumb_w, self._thumb_h)
            )
            self._thumb_cache.append(ctkimg)
            row = self._grid_count // self._grid_cols
            col = self._grid_count % self._grid_cols
            ctk.CTkLabel(self._grid_frame, image=ctkimg, text="").grid(
                row=row, column=col, padx=3, pady=3
            )
            self._grid_count += 1
        except Exception:
            pass

    def _start_generate(self):
        if self._running:
            return
        self._running = True
        self.app.stop_event.clear()   # reset any previous stop
        self._gen_btn.configure(state="disabled", text="Generating…")
        self._clear_grid()
        self._prog_bar.set(0)
        self._prog_label.configure(text="Starting…")
        threading.Thread(target=self._run_generate, daemon=True).start()

    def _run_generate(self):
        cfg       = self.app.cfg
        lang      = cfg["language"]
        icon_type = cfg["iconType"]
        use_feat  = cfg["useFeaturedIfAvailable"]
        watermark = cfg["watermark"]
        font_main = resolve_font(cfg["imageFont"])
        font_side = resolve_font(cfg["sideFont"])
        merge_wm  = cfg["MergeWatermarkUrl"]
        name_lbl  = cfg["name"]
        do_merge  = cfg["MergeImages"]
        auto_tw   = cfg["AutoTweetMerged"]

        self.app.log("Fetching new cosmetics…")
        try:
            resp = requests.get(f"{FORTNITE_API}/v2/cosmetics/new",
                                params={"language": lang}, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.app.log(f"API error: {e}", error=True)
            self.after(0, self._reset_btn)
            return

        data  = resp.json().get("data") or {}
        items = data.get("items", {}).get("br", [])
        build_raw = data.get("build", "")
        try:
            build = build_raw.split("++Fortnite+Release-")[1].split("-CL-")[0]
        except Exception:
            build = build_raw

        self.app.log(f"Patch {build} — {len(items)} new cosmetics")
        delete_icons()

        ok = 0
        for idx, item in enumerate(items, 1):
            if self.app.stop_event.is_set():
                self.app.log("⏹ Generation stopped by user.")
                break
            item_id = item.get("id", f"item_{idx}")
            out_path = f"icons/{item_id}.png"
            try:
                url = get_image_url(item, use_feat)
                generate_card(
                    item=item, icon_url=url, out_path=out_path,
                    icon_type=icon_type, font_main=font_main, font_side=font_side,
                    watermark=watermark, show_source=cfg["showitemsource"], build=build,
                )
                ok += 1
                pct = idx / len(items)
                self.after(0, lambda p=pct, i=idx, t=len(items):
                           (self._prog_bar.set(p),
                            self._prog_label.configure(text=f"{i}/{t}")))
                self.after(0, lambda p=out_path: self._add_thumb(p))
                self.app.log(f"  [{idx}/{len(items)}] {item_id}")
            except Exception as e:
                self.app.log(f"  Skipped {item_id}: {e}", warn=True)

        self.app.log(f"Done — {ok}/{len(items)} cards generated.")
        self.after(0, lambda: self._prog_bar.set(1.0))
        self.after(0, lambda: self._prog_label.configure(text=f"{ok} done",
                                                          text_color=C["green"]))

        if do_merge and ok > 0:
            self.app.log("Merging images…")
            try:
                merged = merge_icons("icons", "merged/merge.jpg", watermark_url=merge_wm)
                self.app.log(f"Saved → {merged}")
                if self.app.auto_open:
                    self.after(0, lambda p=merged: open_file(p))

                if auto_tw and self.app.tw and self.app.tw.ready:
                    text = f"[{name_lbl}] Found {ok} leaked cosmetics from Patch {build}."
                    try:
                        self.app.tw.tweet_with_media(merged, text)
                        self.app.log("Tweeted!")
                    except Exception as e:
                        self.app.log(f"Tweet failed, compressing: {e}", warn=True)
                        compress_image(merged)
                        try:
                            self.app.tw.tweet_with_media(merged, text)
                            self.app.log("Tweeted (compressed)!")
                        except Exception as e2:
                            self.app.log(f"Tweet failed: {e2}", error=True)
            except Exception as e:
                self.app.log(f"Merge failed: {e}", error=True)

        self.after(0, self._reset_btn)

    def _reset_btn(self):
        self._gen_btn.configure(state="normal", text="⚡  Generate Now")
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
# Search page
# ══════════════════════════════════════════════════════════════════════════════

# All BR cosmetic types in display order
_SEARCH_FILTERS = [
    ("All",           ""),
    ("Outfits",       "outfit"),
    ("Back Blings",   "backpack"),
    ("Pickaxes",      "pickaxe"),
    ("Gliders",       "glider"),
    ("Emotes",        "emote"),
    ("Wraps",         "wrap"),
    ("Sprays",        "spray"),
    ("Loading Screens","loadingscreen"),
    ("Music",         "music"),
    ("Shoes",         "shoe"),
    ("Contrails",     "contrail"),
    ("Emoticons",     "emoji"),
    ("Banners",       "banner"),
]

class SearchPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._thumb_ref   = None
        self._last_item   = None
        self._last_path   = None
        self._active_type = ""   # "" = All
        self._history: list = []  # persistent history of selected items
        self._hist_visible  = False

        # ── Header ────────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Search Cosmetic",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(20, 8))

        # ── Search bar ────────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(padx=40, pady=(0, 6), fill="x")
        self._entry = ctk.CTkEntry(bar,
                                   placeholder_text="Name, or ID: prefix for exact ID…",
                                   height=40, fg_color=C["input_bg"],
                                   font=ctk.CTkFont(size=13))
        self._entry.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self._entry.bind("<Return>", lambda _: self._search())
        self._search_btn = ctk.CTkButton(bar, text="Search", width=100, height=40,
                                          fg_color=C["accent_btn"], hover_color=C["accent"],
                                          font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._search)
        self._search_btn.pack(side="right")

        # ── Type filter pills ─────────────────────────────────────────────────
        pill_outer = ctk.CTkFrame(self, fg_color="transparent")
        pill_outer.pack(padx=40, pady=(0, 10), fill="x")

        pill_scroll = ctk.CTkScrollableFrame(pill_outer, fg_color="transparent",
                                              height=38, orientation="horizontal",
                                              scrollbar_button_color=C["border"])
        pill_scroll.pack(fill="x")

        self._filter_btns: dict[str, ctk.CTkButton] = {}
        for label, type_val in _SEARCH_FILTERS:
            btn = ctk.CTkButton(
                pill_scroll, text=label,
                width=max(60, len(label) * 8), height=28,
                corner_radius=14,
                fg_color=C["border"] if type_val == "" else C["card"],
                hover_color=C["accent_btn"],
                text_color=C["text"] if type_val == "" else C["text_dim"],
                font=ctk.CTkFont(size=11),
                command=lambda tv=type_val: self._set_filter(tv),
            )
            btn.pack(side="left", padx=4)
            self._filter_btns[type_val] = btn

        # ── Main area: results list (left) + detail panel (right) ─────────────
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=40, pady=(0, 8))
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)

        # Results list (left column) — gridded then hidden until a search returns multiple hits
        self._results_scroll = ctk.CTkScrollableFrame(
            main, fg_color=C["card"], corner_radius=10, width=220,
            scrollbar_button_color=C["border"]
        )
        self._results_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._results_scroll.grid_remove()   # hidden until we have multiple results

        # Detail panel (right column)
        detail = ctk.CTkFrame(main, fg_color=C["card"], corner_radius=10)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.grid_columnconfigure(1, weight=1)
        detail.grid_rowconfigure(0, weight=1)

        # Card preview (left of detail)
        self._img_label = ctk.CTkLabel(detail, text="Search for a cosmetic above.",
                                        text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=13),
                                        width=280, height=280)
        self._img_label.grid(row=0, column=0, padx=20, pady=20, sticky="n")

        # Info (right of detail)
        info = ctk.CTkFrame(detail, fg_color="transparent")
        info.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=20)

        self._name_lbl = ctk.CTkLabel(info, text="—",
                                       font=ctk.CTkFont(size=22, weight="bold"),
                                       text_color=C["text"], anchor="w", wraplength=380)
        self._name_lbl.pack(anchor="w", pady=(0, 6))

        # Type / rarity row
        tr_row = ctk.CTkFrame(info, fg_color="transparent")
        tr_row.pack(anchor="w", pady=(0, 4))
        self._type_lbl = ctk.CTkLabel(tr_row, text="", text_color=C["text_dim"],
                                       font=ctk.CTkFont(size=12))
        self._type_lbl.pack(side="left")
        self._rar_lbl  = ctk.CTkLabel(tr_row, text="", text_color=C["text_dim"],
                                       font=ctk.CTkFont(size=12))
        self._rar_lbl.pack(side="left", padx=(12, 0))

        self._set_lbl  = ctk.CTkLabel(info, text="", text_color=C["text_dim"],
                                       font=ctk.CTkFont(size=12), anchor="w")
        self._set_lbl.pack(anchor="w")

        self._intro_lbl = ctk.CTkLabel(info, text="", text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=12), anchor="w")
        self._intro_lbl.pack(anchor="w")

        self._desc_lbl = ctk.CTkLabel(info, text="", text_color=C["text_dim"],
                                       font=ctk.CTkFont(size=12), wraplength=380,
                                       anchor="w", justify="left")
        self._desc_lbl.pack(anchor="w", pady=(8, 0))

        # ID row with copy button
        id_row = ctk.CTkFrame(info, fg_color="transparent")
        id_row.pack(anchor="w", pady=(8, 0))
        self._id_lbl = ctk.CTkLabel(id_row, text="", text_color=C["border"],
                                     font=_mono_font(11))
        self._id_lbl.pack(side="left")
        self._copy_id_btn = ctk.CTkButton(
            id_row, text="Copy ID", width=70, height=24,
            fg_color=C["border"], hover_color=C["input_bg"],
            font=ctk.CTkFont(size=10), text_color=C["text_dim"],
            state="disabled",
            command=self._copy_id,
        )
        self._copy_id_btn.pack(side="left", padx=(8, 0))

        # Action buttons
        btn_row = ctk.CTkFrame(info, fg_color="transparent")
        btn_row.pack(anchor="w", pady=(16, 0))

        self._tweet_btn = ctk.CTkButton(btn_row, text="Tweet card", width=110, height=34,
                                         fg_color=C["blue"], hover_color="#1e5faa",
                                         font=ctk.CTkFont(size=12),
                                         state="disabled", command=self._tweet_card)
        self._tweet_btn.pack(side="left", padx=(0, 8))

        self._open_btn = ctk.CTkButton(btn_row, text="Open image", width=110, height=34,
                                        fg_color=C["card"], hover_color=C["border"],
                                        font=ctk.CTkFont(size=12),
                                        state="disabled",
                                        command=lambda: open_file(self._last_path))
        self._open_btn.pack(side="left")

    # ── filter pills ──────────────────────────────────────────────────────────
    def _set_filter(self, type_val: str):
        self._active_type = type_val
        for tv, btn in self._filter_btns.items():
            if tv == type_val:
                btn.configure(fg_color=C["border"], text_color=C["text"])
            else:
                btn.configure(fg_color=C["card"], text_color=C["text_dim"])

    # ── search ────────────────────────────────────────────────────────────────
    def _search(self):
        query = self._entry.get().strip()
        if not query:
            return
        self._name_lbl.configure(text="Searching…", text_color=C["text_dim"])
        self._search_btn.configure(state="disabled")
        threading.Thread(target=self._do_search, args=(query,), daemon=True).start()

    def _do_search(self, query: str):
        cfg  = self.app.cfg
        lang = cfg["language"]

        if query.startswith("ID:"):
            params   = {"language": lang, "id": query[3:].strip()}
            endpoint = f"{FORTNITE_API}/v2/cosmetics/br/search"
        else:
            params   = {"language": lang, "name": query}
            if self._active_type:
                params["type"] = self._active_type
            endpoint = f"{FORTNITE_API}/v2/cosmetics/br/search/all"

        try:
            resp = requests.get(endpoint, params=params, timeout=15)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda m=msg: (
                self._name_lbl.configure(text=f"Error: {m}", text_color=C["red"]),
                self._search_btn.configure(state="normal"),
            ))
            return
        finally:
            self.after(0, lambda: self._search_btn.configure(state="normal"))

        if resp.status_code == 404:
            self.after(0, lambda: self._name_lbl.configure(
                text="No results found.", text_color=C["text_dim"]))
            return

        raw = resp.json().get("data")
        if not raw:
            self.after(0, lambda: self._name_lbl.configure(
                text="No results found.", text_color=C["text_dim"]))
            return

        # single-item endpoint returns dict; search/all returns list
        items = raw if isinstance(raw, list) else [raw]
        self.after(0, lambda it=items: self._show_results(it))

    def _show_results(self, items: list):
        # Auto-select the best match — this also adds it to history
        self._select_item(items[0])

    # ── history helpers ───────────────────────────────────────────────────────
    def _add_to_history(self, item: dict):
        """Prepend item to history (deduplicated). Show panel on first add."""
        iid = item.get("id", "")
        # Remove existing entry so it moves to top
        self._history = [h for h in self._history if h.get("id") != iid]
        self._history.insert(0, item)
        self._rebuild_history_panel()
        if not self._hist_visible:
            self._results_scroll.grid()
            self._hist_visible = True

    def _rebuild_history_panel(self):
        """Rebuild the history list widget."""
        for w in self._results_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._results_scroll, text="HISTORY",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=C["text_dim"]).pack(anchor="w", padx=8, pady=(6, 2))
        for it in self._history:
            name = it.get("name", "?")
            rarity_color = {
                "common": "#aaaaaa", "uncommon": "#5aff5a",
                "rare": "#4fc3f7", "epic": "#ce93d8",
                "legendary": "#ffb347", "mythic": "#ffe57f",
            }.get((it.get("rarity") or {}).get("value", "").lower(), C["text"])
            btn = ctk.CTkButton(
                self._results_scroll, text=name, anchor="w",
                width=200, height=30,
                fg_color="transparent", hover_color=C["border"],
                font=ctk.CTkFont(size=11), text_color=rarity_color,
                command=lambda i=it: self._select_item(i),
            )
            btn.pack(fill="x", padx=4, pady=1)

    def _select_item(self, item: dict):
        cfg      = self.app.cfg
        item_id  = item["id"]
        out_path = f"icons/{item_id}.png"
        url      = get_image_url(item, cfg["useFeaturedIfAvailable"])

        # Add to persistent history
        self._add_to_history(item)

        # Update info panel immediately
        self._update_info(item)

        # Generate card in background
        threading.Thread(target=self._gen_card,
                         args=(item, url, out_path, cfg), daemon=True).start()

    def _gen_card(self, item, url, out_path, cfg):
        try:
            generate_card(
                item=item, icon_url=url, out_path=out_path,
                icon_type=cfg["iconType"], font_main=resolve_font(cfg["imageFont"]),
                font_side=resolve_font(cfg["sideFont"]),
                watermark=cfg["watermark"], show_source=cfg["showitemsource"],
            )
            self._last_item = item
            self._last_path = out_path
            self.after(0, lambda: self._update_preview(out_path))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda m=msg: self._name_lbl.configure(
                text=f"Card error: {m}", text_color=C["red"]))

    def _update_info(self, item: dict):
        self._name_lbl.configure(text=item.get("name", "?"), text_color=C["text"])

        type_str   = (item.get("type")   or {}).get("displayValue", "")
        rarity_str = (item.get("rarity") or {}).get("displayValue", "")
        self._type_lbl.configure(text=type_str)
        self._rar_lbl.configure(text=f"· {rarity_str}" if rarity_str else "")

        set_name = (item.get("set") or {}).get("value", "")
        self._set_lbl.configure(text=f"Set: {set_name}" if set_name else "")

        intro = item.get("introduction") or {}
        chapter, season = intro.get("chapter", ""), intro.get("season", "")
        intro_text = f"Introduced: Chapter {chapter}, Season {season}" if chapter else ""
        self._intro_lbl.configure(text=intro_text)

        self._desc_lbl.configure(text=item.get("description", ""))
        self._id_lbl.configure(text=item.get("id", ""))
        self._copy_id_btn.configure(state="normal")
        self._tweet_btn.configure(state="normal")
        self._open_btn.configure(state="disabled")   # until card is generated

    def _update_preview(self, path: str):
        try:
            pil = PILImage.open(path)
            w, h = pil.size
            disp_w = min(w, 320)
            disp_h = round(disp_w * h / w)
            thumb  = pil.convert("RGB").resize((disp_w, disp_h), PILImage.LANCZOS)
            ctkimg = ctk.CTkImage(light_image=thumb, dark_image=thumb,
                                  size=(disp_w, disp_h))
            self._thumb_ref = ctkimg
            self._img_label.configure(image=ctkimg, text="", width=disp_w, height=disp_h,
                                      cursor="hand2")
            self._img_label.bind("<Button-1>", lambda _: self._open_fullscreen())
            self._open_btn.configure(state="normal")
        except Exception:
            pass

    def _open_fullscreen(self):
        path = self._last_path
        if not path or not os.path.exists(path):
            return
        try:
            pil = PILImage.open(path).convert("RGB")
        except Exception:
            return

        win = ctk.CTkToplevel(self)
        win.title("Preview")
        win.configure(fg_color=C["bg"])
        win.attributes("-topmost", True)

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        max_w = min(sw - 80, 900)
        max_h = min(sh - 120, 900)
        ratio  = min(max_w / pil.width, max_h / pil.height, 1.0)
        disp_w = int(pil.width  * ratio)
        disp_h = int(pil.height * ratio)
        pil_disp = pil.resize((disp_w, disp_h), PILImage.LANCZOS)

        ctkimg = ctk.CTkImage(light_image=pil_disp, dark_image=pil_disp,
                               size=(disp_w, disp_h))
        win._img_ref = ctkimg   # prevent GC on window object

        win.geometry(f"{disp_w}x{disp_h + 48}")
        ctk.CTkLabel(win, text="", image=ctkimg).pack(expand=True, fill="both")
        ctk.CTkButton(win, text="Close", width=100, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      command=win.destroy).pack(pady=6)
        win.bind("<Escape>", lambda _: win.destroy())

    # ── actions ───────────────────────────────────────────────────────────────
    def _copy_id(self):
        cid = self._id_lbl.cget("text")
        if not cid:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(cid)
            self.update()
        except Exception:
            pass
        self._copy_id_btn.configure(text="✓ Copied!", text_color=C["green"])
        self.after(2000, lambda: self._copy_id_btn.configure(
            text="Copy ID", text_color=C["text_dim"]))

        tweet_state = "normal" if (self.app.tw and self.app.tw.ready) else "disabled"
        self._tweet_btn.configure(state=tweet_state)
        self._open_btn.configure(state="normal")

    def _tweet_card(self):
        if not self._last_item or not self._last_path:
            return
        item = self._last_item
        name   = item.get("name", item["id"])
        itype  = (item.get("type") or {}).get("displayValue", "")
        rarity = (item.get("rarity") or {}).get("displayValue", "")
        desc   = item.get("description", "")
        season = (item.get("introduction") or {}).get("season", "?")
        text   = f"[{self.app.cfg['name']}] {name} ({itype})\nRarity: {rarity}\n{desc}\nSeason {season}"
        threading.Thread(
            target=lambda: self.app.tw.tweet_with_media(self._last_path, text),
            daemon=True
        ).start()
        self.app.log(f"Tweeting {name}…")


# ══════════════════════════════════════════════════════════════════════════════
# Monitors page
# ══════════════════════════════════════════════════════════════════════════════
class MonitorsPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}

        ctk.CTkLabel(self, text="Monitors",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(24, 8))
        ctk.CTkLabel(self, text="Each monitor polls for changes and optionally tweets when detected.",
                     text_color=C["text_dim"], font=ctk.CTkFont(size=12)).pack(pady=(0, 20))

        monitors = [
            ("update",   "Update Mode",       "Detects new cosmetics hash changes"),
            ("news",     "BR News Feed",       "Detects BR news tile updates"),
            ("notices",  "Emergency Notices",  "Detects Fortnite status/notice changes"),
            ("staging",  "Staging Servers",    "Detects Epic's pre-release server version bump"),
            ("shop",     "Shop Sections",      "Detects changes in Item Shop sections"),
        ]

        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._toggle_btns: dict[str, ctk.CTkButton]  = {}

        for key, name, desc in monitors:
            row = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=8,
                                border_width=1, border_color=C["border"])
            row.pack(fill="x", padx=30, pady=5)

            ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=C["text"], width=170, anchor="w").pack(side="left", padx=16, pady=12)
            ctk.CTkLabel(row, text=desc, text_color=C["text_dim"],
                         font=ctk.CTkFont(size=12), anchor="w").pack(side="left", padx=4)

            status = ctk.CTkLabel(row, text="Idle", text_color=C["text_dim"],
                                   font=ctk.CTkFont(size=12), width=80)
            status.pack(side="right", padx=12)
            self._status_labels[key] = status

            btn = ctk.CTkButton(row, text="Start", width=80, height=30,
                                 fg_color=C["green"], hover_color="#1e7a35",
                                 font=ctk.CTkFont(size=12),
                                 command=lambda k=key: self._toggle(k))
            btn.pack(side="right", padx=8)
            self._toggle_btns[key] = btn

    def _toggle(self, key: str):
        if key in self._threads and self._threads[key].is_alive():
            self._stop(key)
        else:
            self._start(key)

    def _start(self, key: str):
        stop_evt = threading.Event()
        self._stop_events[key] = stop_evt
        t = threading.Thread(target=self._run_monitor, args=(key, stop_evt), daemon=True)
        self._threads[key] = t
        t.start()
        self._status_labels[key].configure(text="Running", text_color=C["green"])
        self._toggle_btns[key].configure(text="Stop", fg_color=C["red"],
                                          hover_color="#a02020")

    def _stop(self, key: str):
        if key in self._stop_events:
            self._stop_events[key].set()
        self._status_labels[key].configure(text="Stopping…", text_color=C["orange"])

    def _mark_stopped(self, key: str):
        self._status_labels[key].configure(text="Idle", text_color=C["text_dim"])
        self._toggle_btns[key].configure(text="Start", fg_color=C["green"],
                                          hover_color="#1e7a35")

    def _run_monitor(self, key: str, stop_evt: threading.Event):
        cfg   = self.app.cfg
        tw    = self.app.tw
        delay = cfg["BotDelay"]
        lang  = cfg["language"]

        try:
            if key == "update":
                self._monitor_update(cfg, tw, stop_evt, delay, lang)
            elif key == "news":
                self._monitor_news(cfg, tw, stop_evt, delay, lang)
            elif key == "notices":
                self._monitor_notices(cfg, tw, stop_evt, delay)
            elif key == "staging":
                self._monitor_staging(cfg, tw, stop_evt, delay)
            elif key == "shop":
                self._monitor_shop(cfg, tw, stop_evt, delay, lang)
        except Exception as e:
            self.app.log(f"Monitor [{key}] error: {e}", error=True)
        finally:
            self.after(0, lambda k=key: self._mark_stopped(k))

    # ── individual monitor loops ───────────────────────────────────────────────
    def _monitor_update(self, cfg, tw, stop, delay, lang):
        old_hash = None
        count = 0
        while not stop.is_set():
            try:
                r = requests.get(f"{FORTNITE_API}/v2/cosmetics/new",
                                  params={"language": lang}, timeout=10)
                h = r.json()["data"]["hashes"]["br"]
                if old_hash is None:
                    old_hash = h
                    self.app.log("[Update] Watching for cosmetic hash change…")
                elif h != old_hash:
                    self.app.log("[Update] 🎉 Hash changed — generating cosmetics…")
                    # Trigger a full generate on the main thread
                    self.after(0, lambda: self.app.show_page("generate"))
                    self.after(100, self.app.pages["generate"]._start_generate)
                    old_hash = h
                else:
                    count += 1
                    self.app.log(f"[Update] Check #{count} — no change")
            except Exception as e:
                self.app.log(f"[Update] Error: {e}", warn=True)
            stop.wait(delay)

    def _monitor_news(self, cfg, tw, stop, delay, lang):
        old_hash = None
        count = 0
        while not stop.is_set():
            try:
                r = requests.get(f"{FORTNITE_API}/v2/news/br",
                                  params={"language": lang}, timeout=10)
                h = (r.json().get("data") or {}).get("hash")
                if old_hash is None:
                    old_hash = h
                    self.app.log("[News] Watching…")
                elif h != old_hash:
                    self.app.log("[News] 📰 News updated!")
                    old_hash = h
                else:
                    count += 1
                    self.app.log(f"[News] Check #{count}")
            except Exception as e:
                self.app.log(f"[News] Error: {e}", warn=True)
            stop.wait(delay)

    def _monitor_notices(self, cfg, tw, stop, delay):
        old = None
        count = 0
        while not stop.is_set():
            try:
                r = requests.get(f"{FORTNITE_API}/v2/status", timeout=10)
                curr = str(r.json().get("data"))
                if old is None:
                    old = curr
                    self.app.log("[Notices] Watching…")
                elif curr != old:
                    self.app.log("[Notices] ⚠️  Status changed!")
                    if tw and tw.ready:
                        tw.tweet(f"[{cfg['name']}] Fortnite status changed!\n{curr[:200]}")
                    old = curr
                else:
                    count += 1
                    self.app.log(f"[Notices] Check #{count}")
            except Exception as e:
                self.app.log(f"[Notices] Error: {e}", warn=True)
            stop.wait(delay)

    def _monitor_staging(self, cfg, tw, stop, delay):
        old = None
        count = 0
        STAGING = "https://fortnite-public-service-stage.ol.epicgames.com/fortnite/api/version"
        while not stop.is_set():
            try:
                r = requests.get(STAGING, timeout=10)
                v = r.json().get("version","")
                if old is None:
                    old = v
                    self.app.log(f"[Staging] Watching — current: {v}")
                elif v != old:
                    self.app.log(f"[Staging] 🚀 Updated: {old} → {v}")
                    if tw and tw.ready:
                        tw.tweet(f"[{cfg['name']}] Fortnite staging updated to v{v}!")
                    old = v
                else:
                    count += 1
                    self.app.log(f"[Staging] Check #{count}")
            except Exception as e:
                self.app.log(f"[Staging] Error: {e}", warn=True)
            stop.wait(delay)

    def _monitor_shop(self, cfg, tw, stop, delay, lang):
        old = None
        count = 0
        while not stop.is_set():
            try:
                r = requests.get(f"{FORTNITE_API}/v2/shop",
                                  params={"language": lang}, timeout=10)
                key = (r.json().get("data") or {}).get("hash", "")
                if old is None:
                    old = key
                    self.app.log("[Shop] Watching shop hash…")
                elif key != old:
                    self.app.log("[Shop] Shop updated!")
                    old = key
                else:
                    count += 1
                    self.app.log(f"[Shop] Check #{count}")
            except Exception as e:
                self.app.log(f"[Shop] Error: {e}", warn=True)
            stop.wait(delay)


# ══════════════════════════════════════════════════════════════════════════════
# Shop page
# ══════════════════════════════════════════════════════════════════════════════
class ShopPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._running      = False
        self._img_refs     = []
        self._content_frame: Optional[ctk.CTkFrame] = None
        self._gen_start:   float = 0.0

        ctk.CTkLabel(self, text="Item Shop",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(24, 8))
        ctk.CTkLabel(self, text="Generate today's Fortnite Item Shop — split by section.",
                     text_color=C["text_dim"], font=ctk.CTkFont(size=13)).pack(pady=(0, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(0, 8))

        self._gen_btn = ctk.CTkButton(
            btn_row, text="Generate Shop Image", width=200, height=44,
            fg_color=C["accent_btn"], hover_color=C["accent"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_shop
        )
        self._gen_btn.pack(side="left", padx=6)

        self._open_btn = ctk.CTkButton(
            btn_row, text="Open Folder", width=130, height=44,
            fg_color=C["card"], hover_color=C["border"],
            state="disabled",
            command=lambda: open_file("merged")
        )
        self._open_btn.pack(side="left", padx=6)

        self._prog = ctk.CTkProgressBar(self, height=8, progress_color=C["border"])
        self._prog.set(0)
        self._prog.pack(fill="x", padx=60, pady=(0, 2))

        self._eta_lbl = ctk.CTkLabel(self, text="", text_color=C["text_dim"],
                                     font=ctk.CTkFont(size=11))
        self._eta_lbl.pack(pady=(0, 4))

        self._status_lbl = ctk.CTkLabel(self, text="", text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=12))
        self._status_lbl.pack(pady=(0, 4))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["card"], corner_radius=8,
            scrollbar_button_color=C["border"]
        )
        self._scroll.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        self._content_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True)

    def _replace_content(self) -> ctk.CTkFrame:
        if self._content_frame is not None:
            try:
                self._content_frame.destroy()
            except Exception:
                pass
        self._img_refs.clear()
        f = ctk.CTkFrame(self._scroll, fg_color="transparent")
        f.pack(fill="both", expand=True)
        self._content_frame = f
        return f

    def _start_shop(self):
        if self._running:
            return
        self._running    = True
        self._gen_start  = time.time()
        self.app.stop_event.clear()
        self._gen_btn.configure(state="disabled", text="Generating…")
        self._prog.set(0)
        self._eta_lbl.configure(text="")
        self._status_lbl.configure(text="")
        self._replace_content()
        threading.Thread(target=self._run_shop, daemon=True).start()

    def _run_shop(self):
        from ALmodules.shop import generate_shop

        def _on_progress(frac: float):
            elapsed = time.time() - self._gen_start
            if frac > 0.03 and elapsed > 1:
                remaining = (elapsed / frac) - elapsed
                if remaining < 60:
                    eta = f"~{int(remaining)}s remaining"
                else:
                    m, s = int(remaining // 60), int(remaining % 60)
                    eta = f"~{m}m {s:02d}s remaining"
            else:
                eta = "Estimating…"
            self.after(0, lambda f=frac, e=eta: (
                self._prog.set(f),
                self._eta_lbl.configure(text=e),
            ))

        generate_shop(self.app.cfg, self.app.tw, progress_cb=_on_progress)
        self.after(0, self._show_all_sections)
        self.after(0, lambda: self._gen_btn.configure(state="normal",
                                                       text="Generate Shop Image"))
        self.after(0, lambda: self._prog.set(1.0))
        self.after(0, lambda: self._eta_lbl.configure(text=""))
        self.after(0, lambda: self._open_btn.configure(state="normal"))
        self._running = False

    def _copy_section(self, path: str):
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    ["osascript", "-e",
                     f'set the clipboard to (read (POSIX file "{os.path.abspath(path)}") as JPEG picture)'],
                    check=True,
                )
            elif sys.platform == "win32":
                try:
                    import win32clipboard, win32con
                    with PILImage.open(path) as img:
                        output = io.BytesIO()
                        img.convert("RGB").save(output, "BMP")
                        data = output.getvalue()[14:]
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_DIB, data)
                    win32clipboard.CloseClipboard()
                except ImportError:
                    pass
        except Exception as e:
            self.app.log(f"Copy failed: {e}")

    def _show_leaving_detail(self, sec_label: str, leaving_str: str, out_date: str):
        """Show a small popup with the exact leaving date and time."""
        win = ctk.CTkToplevel(self)
        win.title("Leaving Date")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(fg_color=C["bg"])

        ctk.CTkLabel(win, text=sec_label,
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C["text"]).pack(padx=32, pady=(24, 4))

        ctk.CTkLabel(win, text=leaving_str,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text_dim"]).pack(padx=32, pady=(0, 12))

        # Parse exact date/time from ISO string
        exact = ""
        if out_date:
            try:
                dt = datetime.fromisoformat(out_date.replace("Z", "+00:00"))
                day   = dt.strftime("%A")
                date  = dt.strftime("%B %d, %Y")
                clock = dt.strftime("%I:%M %p UTC").lstrip("0") or dt.strftime("%I:%M %p UTC")
                exact = f"{day}, {date}\nat {clock}"
            except Exception:
                exact = out_date

        if exact:
            ctk.CTkLabel(win, text=exact,
                         font=ctk.CTkFont(size=20, weight="bold"),
                         text_color=C["text"],
                         justify="center").pack(padx=32, pady=(0, 20))

        ctk.CTkButton(win, text="Close", width=100, height=30,
                      fg_color=C["card"], hover_color=C["border"],
                      command=win.destroy).pack(pady=(0, 20))
        win.bind("<Escape>", lambda _: win.destroy())

    def _show_all_sections(self):
        import glob as _glob, json as _json
        cf    = self._replace_content()
        files = sorted(_glob.glob("merged/shop_*.jpg"))
        if not files:
            files = ["merged/shop.jpg"] if os.path.exists("merged/shop.jpg") else []
        if not files:
            self._status_lbl.configure(text="No shop images found.")
            return

        # Load section metadata (is_new, leaving) saved by generate_shop
        meta: dict = {}
        try:
            with open("merged/shop_meta.json") as _mf:
                meta = _json.load(_mf)
        except Exception:
            pass

        count  = 0
        win_w  = max(self.winfo_width(), 900)
        disp_w = int(win_w * 0.88)

        for path in files:
            try:
                fname = os.path.basename(path)
                # Reconstruct section label from filename
                parts     = fname.replace("shop_", "", 1).rsplit("_", 1)
                sec_label = parts[0].replace("_", " ").strip() if parts else fname

                # Skip jam-track images — they belong on the Jam Tracks page
                if "jam" in sec_label.lower():
                    continue

                # Pull metadata tags
                m         = meta.get(fname, {})
                is_new    = m.get("is_new", False)
                leaving   = m.get("leaving", "")
                out_date  = m.get("out_date", "")
                # Use stored label if available (preserves original casing)
                sec_label = m.get("label", sec_label)

                # ── Section header row: label + NEW badge + Copy button ───────
                hdr = ctk.CTkFrame(cf, fg_color="transparent")
                hdr.pack(fill="x", padx=8, pady=(12, 2))

                ctk.CTkLabel(
                    hdr, text=sec_label,
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=C["text"],
                ).pack(side="left")

                if is_new:
                    ctk.CTkLabel(
                        hdr, text="NEW",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        text_color="#0d0d0d",
                        fg_color="#37dcc3", corner_radius=4,
                        width=38, height=20,
                    ).pack(side="left", padx=(8, 0))

                ctk.CTkButton(
                    hdr, text="Copy", width=60, height=26,
                    fg_color=C["card"], hover_color=C["border"],
                    font=ctk.CTkFont(size=11),
                    command=lambda p=path: self._copy_section(p),
                ).pack(side="right", padx=(0, 4))

                # ── Leaving banner (own row, prominent, clickable) ────────────
                if leaving:
                    ctk.CTkButton(
                        cf,
                        text=leaving,
                        width=disp_w, height=36,
                        font=ctk.CTkFont(size=15, weight="bold"),
                        fg_color=C["card"],
                        hover_color=C["border"],
                        text_color=C["text"],
                        border_width=1, border_color=C["border"],
                        anchor="center",
                        command=lambda lv=leaving, od=out_date, sl=sec_label:
                            self._show_leaving_detail(sl, lv, od),
                    ).pack(pady=(0, 2))

                # ── Section image ─────────────────────────────────────────────
                pil    = PILImage.open(path)
                disp_h = round(disp_w * pil.height / pil.width)
                thumb  = pil.resize((disp_w, disp_h), PILImage.LANCZOS)
                ctkimg = ctk.CTkImage(light_image=thumb, dark_image=thumb,
                                      size=(disp_w, disp_h))
                self._img_refs.append(ctkimg)
                img_lbl = ctk.CTkLabel(cf, text="", image=ctkimg)
                img_lbl.pack(pady=(0, 4))
                img_lbl.bind("<Button-1>", lambda e, p=path: open_file(p))
                img_lbl.configure(cursor="hand2")
                count += 1
            except Exception:
                pass

        self._status_lbl.configure(
            text=f"{count} section(s) — scroll to view all"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Jam Tracks page
# ══════════════════════════════════════════════════════════════════════════════
class JamTracksPage(_Page):
    """Browse today's Jam Tracks with Spotify / Apple Music links."""

    def __init__(self, master, app):
        super().__init__(master, app)
        self._loaded    = False
        self._img_refs  = []
        self._art_cache: dict[str, PILImage.Image] = {}
        self._tracks: list = []
        self._content_frame: Optional[ctk.CTkFrame] = None

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 8))
        ctk.CTkLabel(hdr, text="Jam Tracks",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(hdr, text="↻  Refresh", width=90, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      command=self._reload).pack(side="right", padx=4)

        self._status_lbl = ctk.CTkLabel(self, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=C["text_dim"])
        self._status_lbl.pack(pady=(0, 6))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"], corner_radius=0,
            scrollbar_button_color=C["border"]
        )
        self._scroll.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        # Placeholder content frame
        self._content_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(self._content_frame, text="Click the page to load jam tracks.",
                     text_color=C["text_dim"]).pack(pady=40)

    def on_show(self):
        if not self._loaded:
            self._reload()

    def _replace_content(self) -> ctk.CTkFrame:
        if self._content_frame is not None:
            try:
                self._content_frame.destroy()
            except Exception:
                pass
        self._img_refs.clear()
        self._art_cache.clear()
        f = ctk.CTkFrame(self._scroll, fg_color="transparent")
        f.pack(fill="both", expand=True)
        self._content_frame = f
        return f

    def _reload(self):
        self._loaded = False
        self._tracks.clear()
        cf = self._replace_content()
        ctk.CTkLabel(cf, text="Loading jam tracks…",
                     text_color=C["text_dim"]).pack(pady=40)
        self._status_lbl.configure(text="")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            from ALmodules.shop import fetch_jam_tracks
            tracks = fetch_jam_tracks(self.app.cfg.get("language", "en"))
            self._tracks = tracks
            self._loaded = True
            self.after(0, lambda t=tracks: self._render(t))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda m=msg: self._show_error(m))

    def _render(self, tracks: list):
        cf = self._replace_content()

        if not tracks:
            ctk.CTkLabel(cf, text="No jam tracks in today's shop.",
                         text_color=C["text_dim"]).pack(pady=40)
            return

        self._status_lbl.configure(text=f"{len(tracks)} tracks in today's shop")

        COLS = 3
        row_frame: Optional[ctk.CTkFrame] = None
        for idx, track in enumerate(tracks):
            if idx % COLS == 0:
                row_frame = ctk.CTkFrame(cf, fg_color="transparent")
                row_frame.pack(fill="x", pady=4)
                for c in range(COLS):
                    row_frame.grid_columnconfigure(c, weight=1)
            self._make_card(row_frame, track, 0, idx % COLS)

    def _make_card(self, parent, track: dict, row: int, col: int):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=10)
        card.grid(row=row, column=col, padx=8, pady=0, sticky="nsew")

        # Album art (square thumbnail)
        art_lbl = ctk.CTkLabel(card, text="♪", width=200, height=200,
                               fg_color=C["input_bg"], corner_radius=8,
                               font=ctk.CTkFont(size=40),
                               text_color=C["text_dim"])
        art_lbl.pack(padx=16, pady=(16, 8))

        art_url = track.get("albumArt", "")
        if art_url:
            threading.Thread(target=self._load_art,
                             args=(art_lbl, art_url), daemon=True).start()

        # Title
        ctk.CTkLabel(card, text=track.get("title", "Unknown"),
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["text"], wraplength=220).pack(padx=12, pady=(0, 2))

        # Artist
        ctk.CTkLabel(card, text=track.get("artist", ""),
                     font=ctk.CTkFont(size=12),
                     text_color=C["text_dim"], wraplength=220).pack(padx=12)

        # Price
        price = track.get("price", 500)
        ctk.CTkLabel(card, text=f"🎵  {price} V-Bucks",
                     font=ctk.CTkFont(size=12),
                     text_color=C["accent"]).pack(pady=(4, 8))

        # Link buttons row
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(pady=(0, 14))

        spotify_url = track.get("spotify", "")
        apple_url   = track.get("appleMusic", "")

        if spotify_url:
            ctk.CTkButton(
                btns, text="▶  Spotify", width=100, height=30,
                fg_color="#1db954", hover_color="#17a347",
                font=ctk.CTkFont(size=12, weight="bold"), text_color="white",
                command=lambda u=spotify_url: webbrowser.open(u),
            ).pack(side="left", padx=(0, 6))

        if apple_url:
            ctk.CTkButton(
                btns, text="  Apple Music", width=120, height=30,
                fg_color="#fc3c44", hover_color="#e02a32",
                font=ctk.CTkFont(size=12, weight="bold"), text_color="white",
                command=lambda u=apple_url: webbrowser.open(u),
            ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btns, text="Copy Post", width=90, height=30,
            fg_color=C["card"], hover_color=C["border"],
            font=ctk.CTkFont(size=12), text_color=C["text"],
            border_width=1, border_color=C["border"],
            command=lambda t=track: self._copy_jam_post(t),
        ).pack(side="left")

    def _load_art(self, lbl: ctk.CTkLabel, url: str):
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            pil_full = PILImage.open(io.BytesIO(r.content)).convert("RGB")
            self._art_cache[url] = pil_full
            pil    = pil_full.resize((200, 200), PILImage.LANCZOS)
            ctkimg = ctk.CTkImage(light_image=pil, dark_image=pil, size=(200, 200))
            self._img_refs.append(ctkimg)
            self.after(0, lambda l=lbl, i=ctkimg: l.configure(image=i, text=""))
        except Exception:
            pass

    def _copy_jam_post(self, track: dict):
        title   = track.get("title", "Unknown")
        artist  = track.get("artist", "")
        price   = track.get("price", 500)
        spotify = track.get("spotify", "")
        apple   = track.get("appleMusic", "")
        art_url = track.get("albumArt", "")

        lines = [f'"{title}" by {artist}',
                 f"🎵 {price} V-Bucks | Now in the Fortnite Item Shop"]
        if spotify:
            lines.append(f"Spotify: {spotify}")
        if apple:
            lines.append(f"Apple Music: {apple}")
        lines.append("#Fortnite #JamTracks #FNLeak")
        post_text = "\n".join(lines)

        win = ctk.CTkToplevel(self)
        win.title("Copy Post")
        win.configure(fg_color=C["bg"])
        win.attributes("-topmost", True)
        win.geometry("480x320")

        ctk.CTkLabel(win, text=title,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["text"]).pack(pady=(14, 4))

        tb = ctk.CTkTextbox(win, width=440, height=160,
                            fg_color=C["card"], text_color=C["text"],
                            font=ctk.CTkFont(size=12))
        tb.pack(padx=16, pady=(0, 8))
        tb.insert("1.0", post_text)
        tb.configure(state="disabled")

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=(0, 14))

        def _copy_text():
            win.clipboard_clear()
            win.clipboard_append(post_text)

        def _copy_img():
            pil = self._art_cache.get(art_url)
            if pil is None:
                return
            safe = "".join(c if c.isalnum() else "_" for c in title)
            path = os.path.join("icons", f"jam_{safe}.jpg")
            os.makedirs("icons", exist_ok=True)
            pil.convert("RGB").save(path, "JPEG", quality=95)
            try:
                if sys.platform == "darwin":
                    subprocess.run(
                        ["osascript", "-e",
                         f'set the clipboard to (read (POSIX file "{os.path.abspath(path)}") as JPEG picture)'],
                        check=True,
                    )
                elif sys.platform == "win32":
                    try:
                        import win32clipboard, win32con
                        output = io.BytesIO()
                        pil.convert("RGB").save(output, "BMP")
                        data = output.getvalue()[14:]
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardData(win32con.CF_DIB, data)
                        win32clipboard.CloseClipboard()
                    except ImportError:
                        pass
            except Exception as e:
                self.app.log(f"Copy image failed: {e}")

        ctk.CTkButton(btn_row, text="Copy Text", width=120, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      text_color=C["text"], border_width=1, border_color=C["border"],
                      command=_copy_text).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Copy Image", width=120, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      text_color=C["text"], border_width=1, border_color=C["border"],
                      command=_copy_img).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Close", width=80, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      text_color=C["text_dim"],
                      command=win.destroy).pack(side="left", padx=6)

        win.bind("<Escape>", lambda _: win.destroy())

    def _show_error(self, msg: str):
        cf = self._replace_content()
        ctk.CTkLabel(cf, text=f"Error: {msg}",
                     text_color=C["red"], wraplength=400).pack(pady=40)


# ══════════════════════════════════════════════════════════════════════════════
# Player Stats page
# ══════════════════════════════════════════════════════════════════════════════
class StatsPage(_Page):
    """Look up any player's lifetime BR stats and display a generated image card."""

    def __init__(self, master, app):
        super().__init__(master, app)
        self._img_ref: Optional[ctk.CTkImage] = None
        self._content_frame: Optional[ctk.CTkFrame] = None
        self._last_img_path: Optional[str] = None
        self._last_stats_name: str = ""

        # ── Header ──────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Player Stats",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(20, 4))
        ctk.CTkLabel(self, text="Look up lifetime Battle Royale stats for any player.",
                     font=ctk.CTkFont(size=12), text_color=C["text_dim"]).pack(pady=(0, 16))

        # ── Search bar ──────────────────────────────────────────────────────
        search_row = ctk.CTkFrame(self, fg_color="transparent")
        search_row.pack(padx=40, pady=(0, 8))

        self._username_entry = ctk.CTkEntry(
            search_row, placeholder_text="Enter username…",
            width=320, height=36,
            fg_color=C["input_bg"], border_color=C["border"],
            text_color=C["text"]
        )
        self._username_entry.pack(side="left", padx=(0, 8))
        self._username_entry.bind("<Return>", lambda _: self._search())

        self._platform_var = ctk.StringVar(value="epic")
        platform_menu = ctk.CTkOptionMenu(
            search_row, variable=self._platform_var,
            values=["epic", "psn", "xbl"],
            width=90, height=36,
            fg_color=C["card"], button_color=C["border"],
            text_color=C["text"],
        )
        platform_menu.pack(side="left", padx=(0, 8))

        self._search_btn = ctk.CTkButton(
            search_row, text="Search", width=90, height=36,
            fg_color=C["accent_btn"], hover_color=C["accent"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._search,
        )
        self._search_btn.pack(side="left")

        # ── Status label ────────────────────────────────────────────────────
        self._status_lbl = ctk.CTkLabel(self, text="",
                                         font=ctk.CTkFont(size=12),
                                         text_color=C["text_dim"])
        self._status_lbl.pack(pady=(0, 8))

        # ── Result area ─────────────────────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"], corner_radius=0,
            scrollbar_button_color=C["border"]
        )
        self._scroll.pack(fill="both", expand=True, padx=0, pady=(0, 0))

        self._content_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(self._content_frame,
                     text="Enter a username above to look up stats.",
                     text_color=C["text_dim"]).pack(pady=60)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _replace_content(self) -> ctk.CTkFrame:
        if self._content_frame is not None:
            try:
                self._content_frame.destroy()
            except Exception:
                pass
        self._img_ref = None
        f = ctk.CTkFrame(self._scroll, fg_color="transparent")
        f.pack(fill="both", expand=True)
        self._content_frame = f
        return f

    def _search(self):
        username = self._username_entry.get().strip()
        if not username:
            return
        platform = self._platform_var.get()
        self._search_btn.configure(state="disabled")
        self._status_lbl.configure(text="Fetching stats…", text_color=C["text_dim"])
        cf = self._replace_content()
        ctk.CTkLabel(cf, text="Loading…", text_color=C["text_dim"]).pack(pady=60)
        threading.Thread(
            target=self._fetch, args=(username, platform), daemon=True
        ).start()

    def _fetch(self, username: str, platform: str):
        try:
            from ALmodules.stats_gen import fetch_and_generate
            font_path = resolve_font(self.app.cfg.get("imageFont", "BurbankBigCondensed-Black.otf"))
            api_key = self.app.cfg.get("apikey", "").strip() or None
            data, img_path = fetch_and_generate(
                username, account_type=platform,
                font_path=font_path,
                out_dir="icons",
                api_key=api_key,
            )
            self.after(0, lambda d=data, p=img_path: self._show_result(d, p))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda m=msg: self._show_error(m))

    def _show_result(self, data: dict, img_path: str):
        self._search_btn.configure(state="normal")
        name = (data.get("account") or {}).get("name", "?")
        self._status_lbl.configure(
            text=f"Stats for {name}", text_color=C["green"]
        )
        cf = self._replace_content()

        # Store for copy/tweet actions
        self._last_img_path   = img_path
        self._last_stats_name = name

        # Reserve a placeholder frame for the image (must come first for pack order)
        img_frame = ctk.CTkFrame(cf, fg_color="transparent")
        img_frame.pack(fill="x", pady=(8, 4))

        # Action buttons below the image
        btn_row = ctk.CTkFrame(cf, fg_color="transparent")
        btn_row.pack(pady=(4, 16))

        ctk.CTkButton(
            btn_row, text="Open Image", width=130, height=32,
            fg_color=C["card"], hover_color=C["border"],
            font=ctk.CTkFont(size=12),
            command=lambda p=img_path: open_file(p),
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            btn_row, text="Copy Image", width=130, height=32,
            fg_color=C["card"], hover_color=C["border"],
            font=ctk.CTkFont(size=12),
            command=self._copy_image,
        ).pack(side="left", padx=4)

        tw_state = "normal" if (self.app.tw and self.app.tw.ready) else "disabled"
        ctk.CTkButton(
            btn_row, text="Tweet Stats", width=130, height=32,
            fg_color=C["blue"], hover_color="#1e5faa",
            font=ctk.CTkFont(size=12),
            state=tw_state,
            command=self._tweet_stats,
        ).pack(side="left", padx=4)

        # Load image after layout settles so winfo_width() is accurate
        try:
            pil = PILImage.open(img_path).convert("RGB")
            self.after(80, lambda p=pil, f=img_frame: self._place_stats_image(p, f))
        except Exception as ex:
            ctk.CTkLabel(img_frame, text=f"Could not load image: {ex}",
                         text_color=C["red"]).pack(pady=20)

    def _place_stats_image(self, pil: "PILImage.Image", img_frame):
        """Scale and render the stats PIL image to exactly fill the page width."""
        page_w = self.winfo_width()
        if page_w < 200:
            page_w = 1200
        display_w = max(600, page_w - 32)   # 16px margin each side
        ratio     = display_w / pil.width
        display_h = int(pil.height * ratio)
        pil_disp  = pil.resize((display_w, display_h), PILImage.LANCZOS)
        ctkimg    = ctk.CTkImage(light_image=pil_disp, dark_image=pil_disp,
                                  size=(display_w, display_h))
        self._img_ref = ctkimg
        lbl = ctk.CTkLabel(img_frame, text="", image=ctkimg)
        lbl.pack(anchor="w")

    def _show_error(self, msg: str):
        self._search_btn.configure(state="normal")
        self._status_lbl.configure(text=f"Error: {msg}", text_color=C["red"])
        cf = self._replace_content()
        ctk.CTkLabel(cf, text=f"⚠  {msg}",
                     text_color=C["red"], wraplength=600).pack(pady=60)

    def _copy_image(self):
        path = self._last_img_path
        if not path:
            return
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    ["osascript", "-e",
                     f'set the clipboard to (read (POSIX file "{os.path.abspath(path)}") as JPEG picture)'],
                    check=True,
                )
            elif sys.platform == "win32":
                try:
                    import win32clipboard, win32con
                    with PILImage.open(path) as img:
                        output = io.BytesIO()
                        img.convert("RGB").save(output, "BMP")
                        data = output.getvalue()[14:]
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_DIB, data)
                    win32clipboard.CloseClipboard()
                except ImportError:
                    pass
        except Exception as e:
            self.app.log(f"Copy image failed: {e}")

    def _tweet_stats(self):
        path = self._last_img_path
        if not path or not self.app.tw or not self.app.tw.ready:
            return
        text = f"[FNLeak] Stats for {self._last_stats_name}\n#Fortnite #FNLeak"
        threading.Thread(
            target=lambda: self.app.tw.tweet_with_media(path, text),
            daemon=True,
        ).start()
        self.app.log(f"Tweeting stats for {self._last_stats_name}…")


# ══════════════════════════════════════════════════════════════════════════════
# Creator Code page
# ══════════════════════════════════════════════════════════════════════════════
class CreatorCodePage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)

        ctk.CTkLabel(self, text="Creator Code Lookup",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(32, 6))
        ctk.CTkLabel(self, text="Check if a Support-a-Creator code is active and who owns it.",
                     font=ctk.CTkFont(size=13), text_color=C["text_dim"]).pack(pady=(0, 24))

        # Search bar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(padx=120, fill="x")
        self._entry = ctk.CTkEntry(bar, placeholder_text="Enter creator code…",
                                   height=44, fg_color=C["input_bg"],
                                   font=ctk.CTkFont(size=14))
        self._entry.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self._entry.bind("<Return>", lambda _: self._lookup())
        self._search_btn = ctk.CTkButton(bar, text="Look Up", width=110, height=44,
                                          fg_color=C["accent_btn"], hover_color=C["accent"],
                                          font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._lookup)
        self._search_btn.pack(side="right")

        # Result card
        self._result = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=12)
        self._result.pack(fill="x", padx=120, pady=24)

        self._status_icon  = ctk.CTkLabel(self._result, text="",
                                           font=ctk.CTkFont(size=48))
        self._status_icon.pack(pady=(28, 4))

        self._code_lbl = ctk.CTkLabel(self._result, text="",
                                       font=ctk.CTkFont(size=28, weight="bold"),
                                       text_color=C["text"])
        self._code_lbl.pack()

        self._name_lbl = ctk.CTkLabel(self._result, text="",
                                       font=ctk.CTkFont(size=16),
                                       text_color=C["text_dim"])
        self._name_lbl.pack(pady=(4, 0))

        self._badge_lbl = ctk.CTkLabel(self._result, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=C["text_dim"])
        self._badge_lbl.pack(pady=(4, 28))

    def _lookup(self):
        code = self._entry.get().strip().lower()
        if not code:
            return
        self._search_btn.configure(state="disabled", text="…")
        self._status_icon.configure(text="⏳")
        self._code_lbl.configure(text="")
        self._name_lbl.configure(text="")
        self._badge_lbl.configure(text="")
        threading.Thread(target=self._fetch, args=(code,), daemon=True).start()

    def _fetch(self, code: str):
        try:
            r = requests.get(f"{FORTNITE_API}/v2/creatorcode",
                             params={"name": code}, timeout=10)
            if r.status_code == 404:
                self.after(0, lambda: self._show_result(None, code))
            else:
                self.after(0, lambda d=r.json().get("data"): self._show_result(d, code))
        except Exception as e:
            self.after(0, lambda: self._show_error(str(e)))
        finally:
            self.after(0, lambda: self._search_btn.configure(state="normal", text="Look Up"))

    def _show_result(self, data, code: str):
        if not data:
            self._status_icon.configure(text="❌")
            self._code_lbl.configure(text=f'"{code}"', text_color=C["red"])
            self._name_lbl.configure(text="Code not found or inactive.")
            self._badge_lbl.configure(text="")
            return

        active   = data.get("status", "") == "ACTIVE"
        verified = data.get("verified", False)
        account  = (data.get("account") or {}).get("name", "Unknown")
        raw_code = data.get("code", code)

        icon       = "✅" if active else "🚫"
        code_color = C["green"] if active else C["red"]
        status_str = "ACTIVE" if active else "INACTIVE"

        self._status_icon.configure(text=icon)
        self._code_lbl.configure(text=raw_code.upper(), text_color=code_color)
        self._name_lbl.configure(text=f"Owned by  {account}")
        badges = [status_str]
        if verified:
            badges.append("✓ Verified")
        self._badge_lbl.configure(text="  ·  ".join(badges))

    def _show_error(self, msg: str):
        self._status_icon.configure(text="⚠️")
        self._code_lbl.configure(text="API Error", text_color=C["orange"])
        self._name_lbl.configure(text=msg[:80])
        self._badge_lbl.configure(text="")


# ══════════════════════════════════════════════════════════════════════════════
# Map Viewer page
# ══════════════════════════════════════════════════════════════════════════════

# Chapter/season display names — matches internal numbering used for the
# fortnite.gg deep-link fallback when the image isn't available via public CDN.
_MAP_SEASONS = [
    ("current", "Current Season  (Live)"),
    ("c1s1",    "C1 S1  — The Original Island"),
    ("c1s2",    "C1 S2  — Tilted Towers"),
    ("c1s3",    "C1 S3  — Comet"),
    ("c1s4",    "C1 S4  — Dusty Divot"),
    ("c1s5",    "C1 S5  — Rift Zones"),
    ("c1s6",    "C1 S6  — Corrupted"),
    ("c1s7",    "C1 S7  — Ice Storm"),
    ("c1s8",    "C1 S8  — Volcano"),
    ("c1s9",    "C1 S9  — Neo Tilted"),
    ("c1sx",    "C1 SX  — Zero Point"),
    ("c2s1",    "C2 S1  — The Flood"),
    ("c2s2",    "C2 S2  — Ghost vs Shadow"),
    ("c2s3",    "C2 S3  — Splashdown"),
    ("c2s4",    "C2 S4  — Marvel"),
    ("c2s5",    "C2 S5  — Zero Point Crystal"),
    ("c2s6",    "C2 S6  — Primal"),
    ("c2s7",    "C2 S7  — Invasion"),
    ("c2s8",    "C2 S8  — Cube Queen"),
    ("c3s1",    "C3 S1  — Flipped"),
    ("c3s2",    "C3 S2  — Resistance"),
    ("c3s3",    "C3 S3  — Vibin'"),
    ("c3s4",    "C3 S4  — Chrome"),
    ("c4s1",    "C4 S1  — New Beginning"),
    ("c4s2",    "C4 S2  — Mega"),
    ("c4s3",    "C4 S3  — WILDS"),
    ("c4s4",    "C4 S4  — Last Resort"),
    ("c4og",    "C4  OG"),
    ("c5s1",    "C5 S1  — Underground"),
    ("c5s2",    "C5 S2  — Myths & Mortals"),
    ("c5s3",    "C5 S3  — Wrecked"),
    ("c5s4",    "C5 S4  — Absolute Doom"),
    ("c5remix", "C5  Remix"),
    ("c6s1",    "C6 S1  - 鬼HUNTERS"),
    ("c6s2",    "C6 S2  - LAWLESS"),
    ("c6sm1",    "Chapter 6 Mini Season 1  - Galactic Battle"),
    ("c6s3",    "C6 S3 - Super"),
    ("c6s4",    "C7 S4 - Shock N’ Awesome"),
    ("c6sm2",    "Chapter 6 Mini Season 2  - The Simpsons"),
    ("c7s1",    "C7 S1  - Pacific Break"),
    ("c7s2",    "C7 S2  - Showdown"),
]

# Map of season-key → fortnite.gg version string for map image
_FGG_VERSION = {
    "c1s1":    "1.0",
    "c1s2":    "2.0",
    "c1s3":    "3.0",
    "c1s4":    "4.5",
    "c1s5":    "5.41",
    "c1s6":    "6.31",
    "c1s7":    "7.40",
    "c1s8":    "8.51",
    "c1s9":    "9.41",
    "c1sx":    "10.40",
    "c2s1":    "11.31",
    "c2s2":    "12.60",
    "c2s3":    "13.30",
    "c2s4":    "14.40",
    "c2s5":    "15.40",
    "c2s6":    "16.50",
    "c2s7":    "17.50",
    "c2s8":    "18.40",
    "c3s1":    "19.40",
    "c3s2":    "20.40",
    "c3s3":    "21.51",
    "c3s4":    "22.40",
    "c4s1":    "23.50",
    "c4s2":    "24.40",
    "c4s3":    "25.11",
    "c4s4":    "26.30",
    "c4og":    "27.11",
    "c5s1":    "28.01",
    "c5s2":    "29.40",
    "c5s3":    "30.30",
    "c5s4":    "31.10",
    "c5remix": "32.11",
    "c6s1":    "33.30",
    "c6s2":    "34.00",
    "c6sm1":    "35.00",
    "c6s3":    "36.00",
    "c6s4":    "37.00",
    "c6sm2":    "38.00",
    "c7s1":    "39.00",
    "c7s2":    "40.00",
}


class MapPage(_Page):
    """Fortnite map viewer — current season (live) or browse historical seasons."""

    def __init__(self, master, app):
        super().__init__(master, app)
        self._img_ref:   Optional[ctk.CTkImage] = None
        self._pil_full:  Optional[PILImage.Image] = None
        self._blank_url: Optional[str] = None
        self._pois_url:  Optional[str] = None
        self._show_pois: bool = True
        self._loaded:    bool = False
        self._load_gen:  int  = 0   # increment to cancel stale loads

        # ── Header row ──────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 6))

        ctk.CTkLabel(hdr, text="Map Viewer",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        # Refresh button (right side)
        ctk.CTkButton(hdr, text="↻  Refresh", width=90, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      text_color=C["text"],
                      command=self._reload).pack(side="right", padx=4)

        # POI toggle
        self._poi_btn = ctk.CTkButton(
            hdr, text="◉  POI Names: ON", width=148, height=32,
            fg_color=C["card"], hover_color=C["border"],
            text_color=C["green"],
            command=self._toggle_pois,
        )
        self._poi_btn.pack(side="right", padx=(0, 6))

        # ── Season selector ──────────────────────────────────────────────────
        sel_row = ctk.CTkFrame(self, fg_color="transparent")
        sel_row.pack(fill="x", padx=24, pady=(0, 4))

        ctk.CTkLabel(sel_row, text="Season:",
                     font=ctk.CTkFont(size=13), text_color=C["text_dim"]).pack(
                         side="left", padx=(0, 8))

        season_labels = [label for _, label in _MAP_SEASONS]
        self._season_var = ctk.StringVar(value=season_labels[0])
        self._season_menu = ctk.CTkOptionMenu(
            sel_row, variable=self._season_var,
            values=season_labels,
            width=340, height=32,
            fg_color=C["card"], button_color=C["border"],
            text_color=C["text"],
            dropdown_fg_color=C["card"],
            dropdown_text_color=C["text"],
            command=self._on_season_change,
        )
        self._season_menu.pack(side="left")

        # ── Status label ────────────────────────────────────────────────────
        self._status_lbl = ctk.CTkLabel(self, text="",
                                         font=ctk.CTkFont(size=11),
                                         text_color=C["text_dim"])
        self._status_lbl.pack(pady=(0, 4))

        # ── Map display area ────────────────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"], corner_radius=0,
            scrollbar_button_color=C["border"],
        )
        self._scroll.pack(fill="both", expand=True, padx=0, pady=(0, 0))

        self._content_frame: Optional[ctk.CTkFrame] = None
        self._replace_content()
        ctk.CTkLabel(self._content_frame,
                     text="Click the page to load the map.",
                     text_color=C["text_dim"]).pack(pady=80)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _replace_content(self) -> ctk.CTkFrame:
        if self._content_frame is not None:
            try:
                self._content_frame.destroy()
            except Exception:
                pass
        self._img_ref = None
        f = ctk.CTkFrame(self._scroll, fg_color="transparent")
        f.pack(fill="both", expand=True)
        self._content_frame = f
        return f

    def on_show(self):
        if not self._loaded:
            self._reload()

    def _reload(self):
        """Fetch and display whichever season is currently selected."""
        selected_label = self._season_var.get()
        # Find the key for the selected label
        season_key = "current"
        for key, label in _MAP_SEASONS:
            if label == selected_label:
                season_key = key
                break

        self._load_gen += 1
        if season_key == "current":
            self._fetch_current()
        else:
            self._show_historical(season_key, selected_label)

    def _on_season_change(self, selected_label: str):
        self._reload()

    # ── current map (live API) ────────────────────────────────────────────────

    def _fetch_current(self):
        self._blank_url = None
        self._pois_url  = None
        cf = self._replace_content()
        ctk.CTkLabel(cf, text="Fetching current map…",
                     text_color=C["text_dim"]).pack(pady=80)
        self._status_lbl.configure(text="")
        gen = self._load_gen
        threading.Thread(target=self._dl_current_meta,
                         args=(gen,), daemon=True).start()

    def _dl_current_meta(self, gen: int):
        try:
            r = requests.get(f"{FORTNITE_API}/v1/map",
                             params={"language": "en"}, timeout=10)
            r.raise_for_status()
            imgs = r.json()["data"]["images"]
            blank = imgs.get("blank", "")
            pois  = imgs.get("pois",  "") or imgs.get("blank", "")
            if gen != self._load_gen:
                return
            self._blank_url = blank
            self._pois_url  = pois
            url = pois if self._show_pois else blank
            self.after(0, lambda u=url, g=gen: self._dl_image(u, g))
        except Exception as e:
            msg = str(e)
            if gen == self._load_gen:
                self.after(0, lambda m=msg: self._show_error(m))

    # ── historical season ─────────────────────────────────────────────────────

    def _show_historical(self, key: str, display_name: str):
        self._poi_btn.configure(state="disabled", text_color=C["text_dim"])
        cf = self._replace_content()
        self._status_lbl.configure(text="")
        ctk.CTkLabel(cf, text=f"Loading {display_name}…",
                     text_color=C["text_dim"]).pack(pady=80)

        version = _FGG_VERSION.get(key)
        if not version:
            self._loaded = True
            self._replace_content()
            ctk.CTkLabel(self._content_frame,
                         text="No map image available for this season.",
                         text_color=C["text_dim"]).pack(pady=80)
            return

        url = f"https://fortnite.gg/img/maps/{version}.jpg"
        gen = self._load_gen
        threading.Thread(target=self._do_dl, args=(url, gen), daemon=True).start()

    # ── image downloading + rendering ─────────────────────────────────────────

    def _dl_image(self, url: str, gen: int):
        """Download map image in background and render it."""
        threading.Thread(target=self._do_dl, args=(url, gen), daemon=True).start()

    def _do_dl(self, url: str, gen: int):
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            pil = PILImage.open(io.BytesIO(r.content)).convert("RGB")
            if gen != self._load_gen:
                return
            self.after(0, lambda p=pil, g=gen: self._render_map(p, g))
        except Exception as e:
            msg = str(e)
            if gen == self._load_gen:
                self.after(0, lambda m=msg: self._show_error(m))

    def _render_map(self, pil: PILImage.Image, gen: int):
        if gen != self._load_gen:
            return
        self._loaded = True
        # Re-enable POI toggle only for current season (historical has one image)
        is_current = self._season_var.get().startswith("Current")
        if is_current:
            self._poi_btn.configure(state="normal", text_color=C["green"])
            self._update_poi_label()

        # Fit image to available scroll area (both width and height)
        avail_w = max(self._scroll.winfo_width()  - 24, 400)
        avail_h = max(self._scroll.winfo_height() - 24, 400)
        ratio     = min(avail_w / pil.width, avail_h / pil.height, 1.0)
        display_w = int(pil.width  * ratio)
        display_h = int(pil.height * ratio)
        pil_disp  = pil.resize((display_w, display_h), PILImage.LANCZOS)
        ctkimg    = ctk.CTkImage(light_image=pil_disp, dark_image=pil_disp,
                                  size=(display_w, display_h))
        cf = self._replace_content()
        self._img_ref    = ctkimg
        self._pil_full   = pil   # store for zoom
        lbl = ctk.CTkLabel(cf, text="", image=ctkimg, cursor="hand2")
        lbl.pack(padx=8, pady=8)
        lbl.bind("<Button-1>", lambda _: self._open_map_zoom())
        self._status_lbl.configure(
            text=f"Map loaded  •  {pil.width}×{pil.height}  •  Click to zoom"
        )

    # ── zoom window ──────────────────────────────────────────────────────────

    def _open_map_zoom(self):
        from PIL import ImageTk

        pil = self._pil_full
        if pil is None:
            return

        win = ctk.CTkToplevel(self)
        win.title("Map Viewer")
        win.configure(fg_color=C["bg"])

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win_w = min(sw - 80, 1400)
        win_h = min(sh - 80, 1000)
        win.geometry(f"{win_w}x{win_h}")

        # ── toolbar ──────────────────────────────────────────────────────────
        toolbar = ctk.CTkFrame(win, fg_color=C["card"], height=44, corner_radius=0)
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        _btn_kw = dict(width=38, height=28, fg_color=C["bg"], hover_color=C["border"],
                       text_color=C["text"], font=ctk.CTkFont(size=14, weight="bold"),
                       corner_radius=6)

        # zoom controls
        ctk.CTkLabel(toolbar, text="Zoom:", font=ctk.CTkFont(size=12),
                     text_color=C["text_dim"]).pack(side="left", padx=(10, 2), pady=8)
        ctk.CTkButton(toolbar, text="−", **_btn_kw,
                      command=lambda: zoom_center(-1)).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(toolbar, text="+", **_btn_kw,
                      command=lambda: zoom_center(+1)).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(toolbar, text="Fit", width=42, height=28,
                      fg_color=C["bg"], hover_color=C["border"],
                      text_color=C["text"], font=ctk.CTkFont(size=12),
                      corner_radius=6,
                      command=lambda: zoom_fit()).pack(side="left", padx=(2, 14), pady=8)

        # pan controls
        ctk.CTkLabel(toolbar, text="Pan:", font=ctk.CTkFont(size=12),
                     text_color=C["text_dim"]).pack(side="left", padx=(0, 2), pady=8)
        ctk.CTkButton(toolbar, text="◀", **_btn_kw,
                      command=lambda: pan(-80, 0)).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(toolbar, text="▲", **_btn_kw,
                      command=lambda: pan(0, -80)).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(toolbar, text="▼", **_btn_kw,
                      command=lambda: pan(0, +80)).pack(side="left", padx=2, pady=8)
        ctk.CTkButton(toolbar, text="▶", **_btn_kw,
                      command=lambda: pan(+80, 0)).pack(side="left", padx=2, pady=8)

        zoom_lbl = ctk.CTkLabel(toolbar, text="100%", font=ctk.CTkFont(size=12),
                                text_color=C["text_dim"], width=52)
        zoom_lbl.pack(side="left", padx=(10, 0), pady=8)

        ctk.CTkButton(toolbar, text="✕  Close", width=80, height=28,
                      fg_color=C["bg"], hover_color=C["border"],
                      text_color=C["text_dim"], font=ctk.CTkFont(size=12),
                      corner_radius=6, command=win.destroy).pack(side="right", padx=10, pady=8)

        # ── canvas + scrollbars ───────────────────────────────────────────────
        canvas = tk.Canvas(win, bg="#0d0d0d", highlightthickness=0,
                           xscrollincrement=1, yscrollincrement=1)
        h_bar  = tk.Scrollbar(win, orient="horizontal", command=canvas.xview)
        v_bar  = tk.Scrollbar(win, orient="vertical",   command=canvas.yview)
        canvas.configure(xscrollcommand=h_bar.set, yscrollcommand=v_bar.set)
        h_bar.pack(side="bottom", fill="x")
        v_bar.pack(side="right",  fill="y")
        canvas.pack(fill="both", expand=True)

        fit_scale = min(win_w / pil.width, win_h / pil.height, 1.0)
        state = {"scale": fit_scale, "tk_img": None, "img_id": None,
                 "drag_x": 0, "drag_y": 0}

        def redraw(pivot_cx=None, pivot_cy=None, pivot_sx=None, pivot_sy=None):
            scale  = state["scale"]
            disp_w = max(1, int(pil.width  * scale))
            disp_h = max(1, int(pil.height * scale))
            resized = pil.resize((disp_w, disp_h), PILImage.LANCZOS)
            tk_img  = ImageTk.PhotoImage(resized)
            state["tk_img"] = tk_img
            if state["img_id"] is not None:
                canvas.itemconfigure(state["img_id"], image=tk_img)
            else:
                state["img_id"] = canvas.create_image(0, 0, anchor="nw", image=tk_img)
            canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
            if pivot_cx is not None:
                canvas.xview_moveto(max(0, pivot_cx - pivot_sx) / disp_w)
                canvas.yview_moveto(max(0, pivot_cy - pivot_sy) / disp_h)
            zoom_lbl.configure(text=f"{int(scale * 100)}%")

        def zoom(delta: int, sx: int, sy: int):
            old = state["scale"]
            new = max(0.05, min(old * (1.2 if delta > 0 else 1 / 1.2), 10.0))
            if new == old:
                return
            cx, cy = canvas.canvasx(sx), canvas.canvasy(sy)
            state["scale"] = new
            redraw(cx * new / old, cy * new / old, sx, sy)

        def zoom_center(delta: int):
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            zoom(delta, cw // 2, ch // 2)

        def zoom_fit():
            state["scale"] = fit_scale
            redraw()
            canvas.xview_moveto(0)
            canvas.yview_moveto(0)

        def pan(dx: int, dy: int):
            if dx:
                canvas.xview_scroll(dx, "units")
            if dy:
                canvas.yview_scroll(dy, "units")

        # scroll-wheel zoom
        canvas.bind("<MouseWheel>", lambda e: zoom(e.delta, e.x, e.y))
        canvas.bind("<Button-4>",   lambda e: zoom(+1, e.x, e.y))
        canvas.bind("<Button-5>",   lambda e: zoom(-1, e.x, e.y))

        # drag to pan
        canvas.bind("<ButtonPress-1>", lambda e: state.update(drag_x=e.x, drag_y=e.y))
        canvas.bind("<B1-Motion>", lambda e: (
            canvas.xview_scroll(state["drag_x"] - e.x, "units"),
            canvas.yview_scroll(state["drag_y"] - e.y, "units"),
            state.update(drag_x=e.x, drag_y=e.y),
        ))

        win.bind("<Escape>", lambda _: win.destroy())
        win.after(50, redraw)

    # ── POI toggle ────────────────────────────────────────────────────────────

    def _toggle_pois(self):
        if not self._loaded or not self._blank_url:
            return
        self._show_pois = not self._show_pois
        self._update_poi_label()
        url = self._pois_url if self._show_pois else self._blank_url
        gen = self._load_gen
        self._replace_content()
        ctk.CTkLabel(self._content_frame, text="Switching…",
                     text_color=C["text_dim"]).pack(pady=80)
        self._dl_image(url, gen)

    def _update_poi_label(self):
        if self._show_pois:
            self._poi_btn.configure(text="◉  POI Names: ON",  text_color=C["green"])
        else:
            self._poi_btn.configure(text="◉  POI Names: OFF", text_color=C["text_dim"])

    def _show_error(self, msg: str):
        cf = self._replace_content()
        ctk.CTkLabel(cf, text=f"⚠  {msg}",
                     text_color=C["red"], wraplength=500).pack(pady=80)


# ══════════════════════════════════════════════════════════════════════════════
# Playlists page
# ══════════════════════════════════════════════════════════════════════════════
class PlaylistsPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._all_playlists: list  = []
        self._img_refs: list       = []
        self._loaded               = False
        self._render_gen           = 0
        self._content_frame: Optional[ctk.CTkFrame] = None

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 8))
        ctk.CTkLabel(hdr, text="Game Modes",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(hdr, text="↻  Refresh", width=90, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      command=self._reload).pack(side="right", padx=4)

        # Search bar
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkEntry(bar, placeholder_text="Search game modes…",
                     textvariable=self._search_var,
                     height=36, fg_color=C["input_bg"],
                     font=ctk.CTkFont(size=13)).pack(fill="x")

        # Filter toggles
        tog = ctk.CTkFrame(self, fg_color="transparent")
        tog.pack(fill="x", padx=24, pady=(0, 8))
        self._show_ltm  = ctk.BooleanVar(value=True)
        self._show_tour = ctk.BooleanVar(value=True)
        for text, var in [("LTMs", self._show_ltm), ("Tournaments", self._show_tour)]:
            ctk.CTkCheckBox(tog, text=text, variable=var,
                            fg_color=C["accent"], hover_color=C["accent_btn"],
                            font=ctk.CTkFont(size=12), text_color=C["text_dim"],
                            command=self._filter).pack(side="left", padx=(0, 16))

        # Scrollable container — we NEVER call winfo_children() on this directly
        # (that returns CTk internals). We manage our own _content_frame instead.
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"], corner_radius=0,
            scrollbar_button_color=C["border"]
        )
        self._scroll.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        # Initial placeholder inside our own tracked frame
        self._content_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._content_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(self._content_frame, text="Click Game Modes to load…",
                     text_color=C["text_dim"]).pack(pady=40)

    def on_show(self):
        if not self._loaded:
            self._reload()

    def _replace_content(self) -> ctk.CTkFrame:
        """Destroy old content frame, create and return a fresh one."""
        if self._content_frame is not None:
            try:
                self._content_frame.destroy()
            except Exception:
                pass
        self._img_refs.clear()
        frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        frame.pack(fill="both", expand=True)
        self._content_frame = frame
        return frame

    def _reload(self):
        self._loaded = False
        self._all_playlists.clear()
        cf = self._replace_content()
        ctk.CTkLabel(cf, text="Loading game modes…",
                     text_color=C["text_dim"]).pack(pady=40)
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            # Use startup preloaded data if available (avoids crash on first open)
            cached = self.app._preload_cache.pop("playlists", None)
            if cached is not None:
                unique = cached
            else:
                r = requests.get(f"{FORTNITE_API}/v1/playlists",
                                 params={"language": self.app.cfg.get("language", "en")},
                                 timeout=12)
                r.raise_for_status()
                all_data = r.json().get("data") or []

                # Filter: must have a showcase image
                with_img = [p for p in all_data
                            if (p.get("images") or {}).get("showcase")]

                # Deduplicate by name — keep first occurrence
                seen: set = set()
                unique = []
                for p in with_img:
                    name = p.get("name", "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        unique.append(p)

            self._all_playlists = unique
            self._loaded = True
            self.after(0, self._render)
        except Exception as e:
            msg = str(e)
            self.after(0, lambda m=msg: self._show_error(m))

    def _filter(self):
        if not self._all_playlists:
            return
        query     = self._search_var.get().strip().lower()
        show_ltm  = self._show_ltm.get()
        show_tour = self._show_tour.get()

        filtered = []
        for p in self._all_playlists:
            if query and query not in p.get("name", "").lower():
                continue
            if not show_ltm and p.get("isLimitedTimeMode"):
                continue
            if not show_tour and p.get("isTournament"):
                continue
            filtered.append(p)

        self._render(filtered)

    def _render(self, playlists: list = None):
        if playlists is None:
            playlists = self._all_playlists

        self._render_gen += 1
        gen = self._render_gen

        cf = self._replace_content()

        if not playlists:
            ctk.CTkLabel(cf, text="No game modes match your search.",
                         text_color=C["text_dim"]).pack(pady=40)
            return

        # Pack rows of 3 cards — avoids grid/pack conflicts inside CTkScrollableFrame
        COLS = 3
        row_frame: Optional[ctk.CTkFrame] = None
        for idx, p in enumerate(playlists):
            if idx % COLS == 0:
                row_frame = ctk.CTkFrame(cf, fg_color="transparent")
                row_frame.pack(fill="x", pady=4)
                for c in range(COLS):
                    row_frame.grid_columnconfigure(c, weight=1)
            col = idx % COLS
            self._make_card(row_frame, p, 0, col, gen)

    def _make_card(self, parent, p: dict, row: int, col: int, gen: int):
        card = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=10)
        card.grid(row=row, column=col, padx=8, pady=0, sticky="nsew")

        img_lbl = ctk.CTkLabel(card, text="", height=120)
        img_lbl.pack(fill="x")

        name = p.get("name", "Unknown")
        ctk.CTkLabel(card, text=name,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=C["text"], wraplength=260).pack(padx=12, pady=(8, 2))

        desc = (p.get("description") or "").strip()
        if desc:
            ctk.CTkLabel(card, text=desc,
                         font=ctk.CTkFont(size=11), text_color=C["text_dim"],
                         wraplength=260, justify="left").pack(padx=12, pady=(0, 6))

        # Badges row
        badge_row = ctk.CTkFrame(card, fg_color="transparent")
        badge_row.pack(padx=12, pady=(0, 10), anchor="w")

        max_sz = p.get("maxTeamSize") or 0
        if max_sz:
            self._badge(badge_row, f"👥 {max_sz}p", C["blue"])
        if p.get("isTournament"):
            self._badge(badge_row, "🏆 Tournament", C["orange"])
        if p.get("isLimitedTimeMode"):
            self._badge(badge_row, "⏱ LTM", C["accent"])

        # Load showcase image in background; abort if generation changed
        url = (p.get("images") or {}).get("showcase")
        if url:
            threading.Thread(target=self._load_img,
                             args=(img_lbl, url, gen), daemon=True).start()

    def _badge(self, parent, text: str, color: str):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=10),
                     fg_color=color, corner_radius=4,
                     text_color="white").pack(side="left", padx=(0, 4))

    def _load_img(self, lbl, url: str, gen: int):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            pil  = PILImage.open(io.BytesIO(r.content)).convert("RGB")
            pil  = pil.resize((360, 120), PILImage.LANCZOS)
            cimg = ctk.CTkImage(light_image=pil, dark_image=pil, size=(360, 120))
            self._img_refs.append(cimg)
            def _apply(l=lbl, i=cimg):
                if gen != self._render_gen:
                    return
                try:
                    l.configure(image=i)
                except Exception:
                    pass
            self.after(0, _apply)
        except Exception:
            pass

    def _show_error(self, msg: str):
        cf = self._replace_content()
        ctk.CTkLabel(cf, text=f"Error: {msg}",
                     text_color=C["red"], wraplength=400).pack(pady=40)


# ══════════════════════════════════════════════════════════════════════════════
# Settings page
# ══════════════════════════════════════════════════════════════════════════════
class SettingsPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._vars: dict = {}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 8))
        ctk.CTkLabel(header, text="Settings",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")

        btn_row = ctk.CTkFrame(header, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(btn_row, text="Open settings.json", width=160, height=32,
                      fg_color=C["card"], hover_color=C["border"],
                      command=lambda: open_file(SETTINGS_PATH)).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Save", width=100, height=32,
                      fg_color=C["green"], hover_color="#1e7a35",
                      font=ctk.CTkFont(weight="bold"),
                      command=self._save).pack(side="right", padx=4)

        # Scrollable form
        form = ctk.CTkScrollableFrame(self, fg_color=C["card"], corner_radius=10,
                                       scrollbar_button_color=C["border"])
        form.pack(fill="both", expand=True, padx=24, pady=(0, 16))
        form.grid_columnconfigure(1, weight=1)

        self._form = form
        self._build_form()

    def _build_form(self):
        f = self._form
        cfg = self.app.cfg

        sections = [
            ("General", [
                ("name",        "Bot Name",         "entry"),
                ("footer",      "Tweet Footer",     "entry"),
                ("language",    "Language",         "option", ["en","de","fr","es","es-419","it","ja","ko","pl","pt-BR","ru","tr","ar","zh-CN","zh-Hant"]),
                ("watermark",   "Watermark Text",   "entry"),
                ("iconType",    "Icon Style",       "option", ["new","cataba","standard","clean","large"]),
                ("useFeaturedIfAvailable", "Use Featured Image", "bool"),
                ("showitemsource",         "Show Item Source",   "bool"),
                ("ImageColor",  "BG Color (hex)",   "entry"),
            ]),
            ("Image Generation", [
                ("imageFont",      "Main Font Filename",  "entry"),
                ("sideFont",       "Side Font Filename",  "entry"),
                ("MergeImages",    "Auto-merge Images",   "bool"),
                ("MergeWatermarkUrl", "Merge Watermark URL", "entry"),
            ]),
            ("Twitter / X", [
                ("twitAPIKey",            "API Key",           "entry_secret"),
                ("twitAPISecretKey",       "API Secret",        "entry_secret"),
                ("twitAccessToken",        "Access Token",      "entry_secret"),
                ("twitAccessTokenSecret",  "Access Token Secret","entry_secret"),
                ("AutoTweetMerged",        "Auto-tweet Merged", "bool"),
                ("TweetSearch",            "Tweet Search Results","bool"),
            ]),
            ("Monitor Settings", [
                ("BotDelay", "Poll Interval (seconds)", "entry"),
                ("TwitterSupport", "Enable Twitter Features", "bool"),
            ]),
        ]

        row_idx = 0
        for section_name, fields in sections:
            lbl = ctk.CTkLabel(f, text=section_name,
                               font=ctk.CTkFont(size=14, weight="bold"),
                               text_color=C["accent"])
            lbl.grid(row=row_idx, column=0, columnspan=2, sticky="w",
                     padx=16, pady=(14, 4))
            row_idx += 1

            for field in fields:
                key, label, kind = field[0], field[1], field[2]
                val = cfg.get(key, DEFAULTS.get(key, ""))

                ctk.CTkLabel(f, text=label, text_color=C["text_dim"],
                             font=ctk.CTkFont(size=12), anchor="e").grid(
                    row=row_idx, column=0, sticky="e", padx=(16, 8), pady=4)

                if kind == "bool":
                    var = ctk.BooleanVar(value=bool(val))
                    self._vars[key] = var
                    ctk.CTkSwitch(f, text="", variable=var,
                                   onvalue=True, offvalue=False,
                                   progress_color=C["accent"]).grid(
                        row=row_idx, column=1, sticky="w", padx=4, pady=4)

                elif kind in ("entry", "entry_secret"):
                    var = ctk.StringVar(value=str(val))
                    self._vars[key] = var
                    show = "*" if kind == "entry_secret" else ""
                    ctk.CTkEntry(f, textvariable=var, show=show, height=30,
                                  fg_color=C["input_bg"],
                                  font=ctk.CTkFont(size=12)).grid(
                        row=row_idx, column=1, sticky="ew", padx=(4, 16), pady=4)

                elif kind == "option":
                    options = field[3]
                    var = ctk.StringVar(value=str(val))
                    self._vars[key] = var
                    ctk.CTkOptionMenu(f, values=options, variable=var,
                                       fg_color=C["card"],
                                       button_color=C["accent"],
                                       dropdown_fg_color=C["card"]).grid(
                        row=row_idx, column=1, sticky="w", padx=(4, 16), pady=4)

                row_idx += 1

    def _save(self):
        cfg = self.app.cfg
        for key, var in self._vars.items():
            val = var.get()
            cfg[key] = val
        save_settings(cfg)
        # Rebuild Twitter client with potentially new keys
        self.app.tw = TwitterClient(
            cfg["twitAPIKey"], cfg["twitAPISecretKey"],
            cfg["twitAccessToken"], cfg["twitAccessTokenSecret"],
        )
        self.app.log("Settings saved.")

    def on_show(self):
        # Refresh values from cfg whenever we navigate to settings
        cfg = self.app.cfg
        for key, var in self._vars.items():
            val = cfg.get(key, DEFAULTS.get(key, ""))
            try:
                var.set(val)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Console page
# ══════════════════════════════════════════════════════════════════════════════
class ConsolePage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(20, 8))
        ctk.CTkLabel(top, text="Console",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(top, text="Clear", width=80, height=30,
                      fg_color=C["card"], hover_color=C["border"],
                      command=self._clear).pack(side="right")

        self._text = ctk.CTkTextbox(self, fg_color=C["input_bg"],
                                     font=_mono_font(12),
                                     text_color=C["text"], state="disabled",
                                     corner_radius=8)
        self._text.pack(fill="both", expand=True, padx=24, pady=(0, 16))

    def append(self, text: str, color: Optional[str] = None):
        """Append text to the console (must be called from main thread)."""
        self._text.configure(state="normal")
        self._text.insert("end", text + "\n")
        self._text.configure(state="disabled")
        self._text.see("end")

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


# ══════════════════════════════════════════════════════════════════════════════
# Main App
# ══════════════════════════════════════════════════════════════════════════════
class FNLeakApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FNLeak")
        self.geometry("1200x780")
        self.minsize(960, 620)
        self.configure(fg_color=C["bg"])

        # On macOS give the window a proper name in the dock
        try:
            self.createcommand("tk::mac::Quit", self.destroy)
        except Exception:
            pass

        # ── state ─────────────────────────────────────────────────────────────
        self._log_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()   # set this to abort running jobs
        self.cfg = load_settings()
        self.tw  = TwitterClient(
            self.cfg["twitAPIKey"], self.cfg["twitAPISecretKey"],
            self.cfg["twitAccessToken"], self.cfg["twitAccessTokenSecret"],
        )

        # ── layout ────────────────────────────────────────────────────────────
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._sidebar  = self._build_sidebar()
        self._content  = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        # ── Footer bar (always visible, above console) ────────────────────────
        self._footer = ctk.CTkFrame(
            self, fg_color=C["sidebar"], corner_radius=0, height=34
        )
        self._footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._footer.grid_propagate(False)

        # Clear Cache button (left side of footer)
        self._clear_cache_btn = ctk.CTkButton(
            self._footer,
            text="🗑  Clear Cache",
            width=120, height=24,
            font=ctk.CTkFont(size=11),
            fg_color=C["card"],
            hover_color=C["red"],
            text_color=C["text_dim"],
            command=self._clear_cache,
        )
        self._clear_cache_btn.pack(side="left", padx=12, pady=5)

        # Emergency stop button
        self._stop_btn = ctk.CTkButton(
            self._footer,
            text="⏹  Stop",
            width=90, height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["red"],
            hover_color="#a01f1f",
            text_color="white",
            command=self._emergency_stop,
        )
        self._stop_btn.pack(side="left", padx=(0, 12), pady=5)

        self._auto_open_var = ctk.BooleanVar(value=self.cfg.get("autoOpenImage", False))
        self._auto_open_chk = ctk.CTkCheckBox(
            self._footer,
            text="Auto-open image after merge",
            variable=self._auto_open_var,
            font=ctk.CTkFont(size=12),
            text_color=C["text_dim"],
            fg_color=C["accent"],
            hover_color=C["accent_btn"],
            checkmark_color=C["text"],
            border_color=C["border"],
            width=20, height=20,
            command=self._toggle_auto_open,
        )
        self._auto_open_chk.pack(side="right", padx=16, pady=7)

        # Thin separator between the two checkboxes
        ctk.CTkLabel(self._footer, text="|", text_color=C["border"],
                     font=ctk.CTkFont(size=14)).pack(side="right", pady=7)

        self._show_console_var = ctk.BooleanVar(value=True)
        self._show_console_chk = ctk.CTkCheckBox(
            self._footer,
            text="Show console",
            variable=self._show_console_var,
            font=ctk.CTkFont(size=12),
            text_color=C["text_dim"],
            fg_color=C["accent"],
            hover_color=C["accent_btn"],
            checkmark_color=C["text"],
            border_color=C["border"],
            width=20, height=20,
            command=self._toggle_console,
        )
        self._show_console_chk.pack(side="right", padx=16, pady=7)

        # Bottom console strip (shown by default)
        self._console_strip = ctk.CTkTextbox(
            self, height=120, fg_color=C["input_bg"],
            font=_mono_font(11),
            text_color=C["text_dim"], state="disabled", corner_radius=0
        )
        self._console_strip.grid(row=2, column=0, columnspan=2, sticky="ew")

        # ── preload cache (populated at startup before dashboard shows) ───────
        self._preload_cache: dict = {}

        # ── pages ─────────────────────────────────────────────────────────────
        self.pages: dict[str, _Page] = {}
        for key, PageClass in [
            ("dashboard", DashboardPage),
            ("generate",  GeneratePage),
            ("search",    SearchPage),
            ("shop",      ShopPage),
            ("jamtracks", JamTracksPage),
            ("stats",     StatsPage),
            ("map",       MapPage),
            ("playlists", PlaylistsPage),
            ("creator",   CreatorCodePage),
            ("monitors",  MonitorsPage),
            ("settings",  SettingsPage),
            ("console",   ConsolePage),
        ]:
            page = PageClass(self._content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

        # ── start ─────────────────────────────────────────────────────────────
        self._show_startup_loader()
        self._poll_log_queue()

        # Redirect stdout
        sys.stdout = _ConsoleRedirector(self._log_queue)

    # ── sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> ctk.CTkFrame:
        sb = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, width=180)
        sb.grid(row=0, column=0, rowspan=3, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(20, weight=1)

        # Logo
        ctk.CTkLabel(sb, text="FNLeak",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["text"]).grid(row=0, column=0, padx=16, pady=(20, 4))
        ctk.CTkLabel(sb, text="by Fevers",
                     font=ctk.CTkFont(size=10), text_color=C["text_dim"]).grid(
            row=1, column=0, padx=16, pady=(0, 16))

        nav = [
            ("dashboard", "Dashboard"),
            ("generate",  "Generate"),
            ("search",    "Search"),
            ("shop",      "Item Shop"),
            ("jamtracks", "Jam Tracks"),
            ("stats",     "Player Stats"),
            ("map",       "Map Viewer"),
            ("playlists", "Game Modes"),
            ("creator",   "Creator Code"),
            ("monitors",  "Monitors"),
            ("settings",  "Settings"),
            ("console",   "Console"),
        ]

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for i, (key, label) in enumerate(nav):
            btn = ctk.CTkButton(
                sb, text=label, anchor="w",
                width=160, height=36,
                fg_color="transparent",
                hover_color=C["card"],
                text_color=C["text_dim"],
                font=ctk.CTkFont(size=13),
                command=lambda k=key: self.show_page(k),
            )
            btn.grid(row=i + 2, column=0, padx=10, pady=2)
            self._nav_buttons[key] = btn

        return sb

    # ── navigation ────────────────────────────────────────────────────────────
    # ── startup loader ────────────────────────────────────────────────────────
    def _show_startup_loader(self):
        """Show a brief loading overlay while preloading heavy data (game modes)."""
        overlay = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        overlay.grid(row=0, column=0, sticky="nsew")
        overlay.grid_columnconfigure(0, weight=1)
        overlay.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(overlay, fg_color="transparent")
        inner.grid(row=0, column=0)

        ctk.CTkLabel(inner, text="FNLeak",
                     font=ctk.CTkFont(size=36, weight="bold"),
                     text_color=C["text"]).pack(pady=(0, 4))
        status_lbl = ctk.CTkLabel(inner, text="Starting up…",
                                   font=ctk.CTkFont(size=13),
                                   text_color=C["text_dim"])
        status_lbl.pack(pady=(0, 16))
        bar = ctk.CTkProgressBar(inner, width=300, mode="indeterminate",
                                  fg_color=C["card"], progress_color=C["border"])
        bar.pack()
        bar.start()

        def _do_preload():
            try:
                status_lbl.configure(text="Loading game modes…")
                r = requests.get(
                    f"{FORTNITE_API}/v1/playlists",
                    params={"language": self.cfg.get("language", "en")},
                    timeout=12,
                )
                r.raise_for_status()
                all_data = r.json().get("data") or []
                with_img = [p for p in all_data
                            if (p.get("images") or {}).get("showcase")]
                seen: set = set()
                unique = []
                for p in with_img:
                    name = p.get("name", "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        unique.append(p)
                self._preload_cache["playlists"] = unique
            except Exception as e:
                self.log(f"Preload warning: {e}")
            self.after(0, _finish)

        def _finish():
            bar.stop()
            overlay.destroy()
            self.show_page("dashboard")

        threading.Thread(target=_do_preload, daemon=True).start()

    def show_page(self, key: str):
        if key not in self.pages:
            return
        # Reset all nav buttons
        for k, btn in self._nav_buttons.items():
            btn.configure(fg_color="transparent", text_color=C["text_dim"])
        # Highlight active
        self._nav_buttons[key].configure(fg_color=C["card"], text_color=C["text"])
        # Raise page
        self.pages[key].tkraise()
        self.pages[key].on_show()

    # ── logging ───────────────────────────────────────────────────────────────
    def log(self, msg: str, error: bool = False, warn: bool = False):
        """Thread-safe log — can be called from any thread."""
        self._log_queue.put(msg)

    def _poll_log_queue(self):
        """Drain the log queue and write to both console widgets."""
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_console(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _append_console(self, text: str):
        # Bottom strip
        self._console_strip.configure(state="normal")
        self._console_strip.insert("end", text.strip() + "\n")
        self._console_strip.configure(state="disabled")
        self._console_strip.see("end")
        # Dedicated console page
        self.pages["console"].append(text)

    # ── auto-open toggle ──────────────────────────────────────────────────────
    def _clear_cache(self):
        """Delete cache/ and icons/ folders, then recreate them empty."""
        import shutil as _shutil
        cleared = []
        for d in ("cache", "icons"):
            try:
                _shutil.rmtree(d)
                cleared.append(d)
            except FileNotFoundError:
                pass
            os.makedirs(d, exist_ok=True)
        self.log(f"Cleared: {', '.join(cleared) or 'nothing to clear'}")
        # Flash button text briefly
        self._clear_cache_btn.configure(text="✓  Cleared", text_color=C["green"])
        self.after(2000, lambda: self._clear_cache_btn.configure(
            text="🗑  Clear Cache", text_color=C["text_dim"]))

    def _emergency_stop(self):
        """Signal all running background jobs to abort."""
        self.stop_event.set()
        self.log("⏹ Emergency stop signalled — aborting current job…")
        self._stop_btn.configure(text="⏹  Stopping…", fg_color="#a01f1f")
        # Auto-reset after 3 s so next job can run
        self.after(3000, self._reset_stop)

    def _reset_stop(self):
        self.stop_event.clear()
        self._stop_btn.configure(text="⏹  Stop", fg_color=C["red"])

    def _toggle_auto_open(self):
        """Save the auto-open preference whenever the checkbox is toggled."""
        self.cfg["autoOpenImage"] = bool(self._auto_open_var.get())
        save_settings(self.cfg)

    def _toggle_console(self):
        """Show or hide the bottom console strip."""
        if self._show_console_var.get():
            self._console_strip.grid()
        else:
            self._console_strip.grid_remove()

    @property
    def auto_open(self) -> bool:
        return bool(self._auto_open_var.get())


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════
def main():
    ensure_directories()
    ensure_rarity_assets(RARITY_COLORS)

    app = FNLeakApp()
    app.mainloop()


if __name__ == "__main__":
    main()
