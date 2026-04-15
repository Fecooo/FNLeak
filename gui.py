"""
FNLeak GUI — CustomTkinter-based frontend.
Runs on macOS (and Windows/Linux) with a dark, Fortnite-inspired theme.

Run:  python3 gui.py
"""

from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Optional

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

# Fortnite-inspired palette (used directly where ctk allows fg_color overrides)
C = {
    "bg":          "#0d1117",
    "sidebar":     "#161b22",
    "card":        "#21262d",
    "border":      "#30363d",
    "accent":      "#7b2fbe",   # Epic purple
    "accent_btn":  "#8b3fce",
    "blue":        "#3275c4",   # Rare blue
    "green":       "#2ea043",   # Success
    "orange":      "#c2712c",   # Legendary
    "red":         "#da3633",   # Error
    "text":        "#e6edf3",
    "text_dim":    "#8b949e",
    "input_bg":    "#0d1117",
}

FORTNITE_API = "https://fortnite-api.com"
SETTINGS_PATH = "settings.json"

RARITY_COLORS = {
    "common": "#636363", "uncommon": "#31a21f", "rare": "#3275c4",
    "epic": "#7d3dba", "legendary": "#c2712c", "mythic": "#e7c03a",
    "exotic": "#21c5e7", "slurp": "#00bcd4",
}


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
               "showitemsource", "TwitterSupport", "ShowValues_AtStart"):
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

        # Title
        ctk.CTkLabel(self, text="FNLeak", font=ctk.CTkFont(size=32, weight="bold"),
                     text_color=C["text"]).pack(pady=(30, 4))
        ctk.CTkLabel(self, text="Fortnite Cosmetic Leak Tool",
                     font=ctk.CTkFont(size=14), text_color=C["text_dim"]).pack(pady=(0, 30))

        # Stat cards row
        self._stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._stats_frame.pack(fill="x", padx=40, pady=10)

        self._build_label    = self._stat_card("Current Build",   "—",      C["blue"])
        self._items_label    = self._stat_card("New Items",       "—",      C["accent"])
        self._twitter_label  = self._stat_card("Twitter / X",     "Checking…", C["orange"])

        # Quick-action buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)

        for text, page in [
            ("Generate Cosmetics", "generate"),
            ("Search Cosmetic",    "search"),
            ("Item Shop",          "shop"),
            ("Monitors",           "monitors"),
        ]:
            ctk.CTkButton(
                btn_frame, text=text, width=180, height=45,
                fg_color=C["accent_btn"], hover_color=C["accent"],
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda p=page: app.show_page(p),
            ).pack(side="left", padx=8)

    def _stat_card(self, title: str, value: str, color: str) -> ctk.CTkLabel:
        card = ctk.CTkFrame(self._stats_frame, fg_color=C["card"],
                            corner_radius=10, border_width=1, border_color=C["border"])
        card.pack(side="left", expand=True, fill="both", padx=8)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11),
                     text_color=C["text_dim"]).pack(pady=(16, 2))
        val_lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold"),
                               text_color=color)
        val_lbl.pack(pady=(0, 16))
        return val_lbl

    def on_show(self):
        threading.Thread(target=self._fetch_stats, daemon=True).start()

    def _fetch_stats(self):
        try:
            r = requests.get(f"{FORTNITE_API}/v2/cosmetics/br/new",
                             params={"language": self.app.cfg.get("language","en")}, timeout=8)
            data = r.json()["data"]
            build = data.get("build","?")
            try:
                build = build.split("++Fortnite+Release-")[1].split("-CL-")[0]
            except Exception:
                pass
            count = len(data.get("items", []))
            self.after(0, lambda: self._build_label.configure(text=build))
            self.after(0, lambda: self._items_label.configure(text=str(count)))
        except Exception:
            self.after(0, lambda: self._build_label.configure(text="Error"))

        tw_ok = self.app.tw and self.app.tw.ready
        tw_text  = "Connected" if tw_ok else "Not configured"
        tw_color = C["green"] if tw_ok else C["text_dim"]
        self.after(0, lambda: self._twitter_label.configure(text=tw_text, text_color=tw_color))


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

        self._grid_cols = 5
        self._grid_count = 0
        self._thumb_cache: list[ctk.CTkImage] = []   # keep references alive

        ctk.CTkLabel(
            self._grid_frame,
            text="Generated cosmetic cards will appear here.",
            text_color=C["text_dim"], font=ctk.CTkFont(size=13)
        ).grid(row=0, column=0, columnspan=5, pady=40)

    # ── internal ──────────────────────────────────────────────────────────────

    def _clear_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._grid_count = 0
        self._thumb_cache.clear()

    def _add_thumb(self, path: str):
        """Add a thumbnail card to the grid (must be called from main thread)."""
        try:
            pil = PILImage.open(path).resize((100, 100), PILImage.LANCZOS)
            ctkimg = ctk.CTkImage(light_image=pil, dark_image=pil, size=(100, 100))
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
            resp = requests.get(f"{FORTNITE_API}/v2/cosmetics/br/new",
                                params={"language": lang}, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            self.app.log(f"API error: {e}", error=True)
            self.after(0, self._reset_btn)
            return

        data  = resp.json()["data"]
        items = data["items"]
        build_raw = data.get("build", "")
        try:
            build = build_raw.split("++Fortnite+Release-")[1].split("-CL-")[0]
        except Exception:
            build = build_raw

        self.app.log(f"Patch {build} — {len(items)} new cosmetics")
        delete_icons()

        ok = 0
        for idx, item in enumerate(items, 1):
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
class SearchPage(_Page):
    def __init__(self, master, app):
        super().__init__(master, app)
        self._thumb_ref = None

        ctk.CTkLabel(self, text="Search Cosmetic",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(24, 12))

        # Search bar
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(padx=40, pady=4, fill="x")
        self._entry = ctk.CTkEntry(bar, placeholder_text="Enter name or ID: prefix for exact ID…",
                                   height=40, fg_color=C["input_bg"],
                                   font=ctk.CTkFont(size=13))
        self._entry.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self._entry.bind("<Return>", lambda _: self._search())
        ctk.CTkButton(bar, text="Search", width=100, height=40,
                      fg_color=C["accent_btn"], hover_color=C["accent"],
                      command=self._search).pack(side="right")

        # Result area
        result = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=10)
        result.pack(fill="both", expand=True, padx=40, pady=12)

        # Left: image preview
        self._img_label = ctk.CTkLabel(result, text="", width=300, height=300)
        self._img_label.pack(side="left", padx=30, pady=30)

        # Right: item info
        info = ctk.CTkFrame(result, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=30)

        self._name_lbl  = ctk.CTkLabel(info, text="—",
                                        font=ctk.CTkFont(size=24, weight="bold"),
                                        text_color=C["text"], anchor="w")
        self._name_lbl.pack(anchor="w", pady=(0, 4))
        self._type_lbl  = ctk.CTkLabel(info, text="", text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=13), anchor="w")
        self._type_lbl.pack(anchor="w")
        self._rar_lbl   = ctk.CTkLabel(info, text="", text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=13), anchor="w")
        self._rar_lbl.pack(anchor="w")
        self._desc_lbl  = ctk.CTkLabel(info, text="", text_color=C["text_dim"],
                                        font=ctk.CTkFont(size=12), wraplength=360,
                                        anchor="w", justify="left")
        self._desc_lbl.pack(anchor="w", pady=(8, 0))
        self._id_lbl    = ctk.CTkLabel(info, text="", text_color=C["border"],
                                        font=ctk.CTkFont(size=11), anchor="w")
        self._id_lbl.pack(anchor="w", pady=(4, 0))

        self._tweet_btn = ctk.CTkButton(info, text="Tweet this card", width=140, height=34,
                                         fg_color=C["blue"], hover_color="#1e5faa",
                                         state="disabled", command=self._tweet_card)
        self._tweet_btn.pack(anchor="w", pady=(16, 0))

        self._open_btn = ctk.CTkButton(info, text="Open image", width=140, height=34,
                                        fg_color=C["card"], hover_color=C["border"],
                                        state="disabled", command=lambda: open_file(self._last_path))
        self._open_btn.pack(anchor="w", pady=(6, 0))

        self._last_item = None
        self._last_path = None

    def _search(self):
        query = self._entry.get().strip()
        if not query:
            return
        self._name_lbl.configure(text="Searching…")
        threading.Thread(target=self._do_search, args=(query,), daemon=True).start()

    def _do_search(self, query: str):
        cfg = self.app.cfg
        lang = cfg["language"]
        if query.startswith("ID:"):
            params = {"language": lang, "id": query[3:].strip()}
        else:
            params = {"language": lang, "name": query}

        try:
            resp = requests.get(f"{FORTNITE_API}/v2/cosmetics/br/search",
                                params=params, timeout=15)
        except Exception as e:
            self.after(0, lambda: self._name_lbl.configure(text=f"Error: {e}",
                                                             text_color=C["red"]))
            return

        if resp.status_code == 404:
            self.after(0, lambda: self._name_lbl.configure(text="Not found.",
                                                             text_color=C["red"]))
            return

        item = resp.json().get("data")
        if not item:
            self.after(0, lambda: self._name_lbl.configure(text="No result.",
                                                             text_color=C["red"]))
            return

        item_id  = item["id"]
        out_path = f"icons/{item_id}.png"
        url      = get_image_url(item, cfg["useFeaturedIfAvailable"])

        try:
            generate_card(
                item=item, icon_url=url, out_path=out_path,
                icon_type=cfg["iconType"], font_main=resolve_font(cfg["imageFont"]),
                font_side=resolve_font(cfg["sideFont"]),
                watermark=cfg["watermark"], show_source=cfg["showitemsource"],
            )
        except Exception as e:
            self.after(0, lambda: self._name_lbl.configure(text=f"Card error: {e}",
                                                             text_color=C["red"]))
            return

        self._last_item = item
        self._last_path = out_path
        self.after(0, lambda: self._update_result(item, out_path))

    def _update_result(self, item: dict, path: str):
        self._name_lbl.configure(text=item.get("name", "?"),
                                  text_color=C["text"])
        self._type_lbl.configure(text=f"Type: {(item.get('type') or {}).get('displayValue','?')}")
        self._rar_lbl.configure(text=f"Rarity: {(item.get('rarity') or {}).get('displayValue','?')}")
        self._desc_lbl.configure(text=item.get("description",""))
        self._id_lbl.configure(text=item.get("id",""))

        try:
            pil = PILImage.open(path).resize((256, 256), PILImage.LANCZOS)
            ctkimg = ctk.CTkImage(light_image=pil, dark_image=pil, size=(256, 256))
            self._thumb_ref = ctkimg
            self._img_label.configure(image=ctkimg)
        except Exception:
            pass

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
                r = requests.get(f"{FORTNITE_API}/v2/cosmetics/br/new",
                                  params={"language": lang}, timeout=10)
                h = r.json()["data"]["hash"]
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
                r = requests.get(f"{FORTNITE_API}/v2/shop/br",
                                  params={"language": lang}, timeout=10)
                sections = (r.json().get("data") or {}).get("featured", {}).get("sections", [])
                key = str([s.get("id") or s.get("sectionId") for s in sections])
                if old is None:
                    old = key
                    self.app.log("[Shop] Watching sections…")
                elif key != old:
                    self.app.log("[Shop] 🛒 Shop sections changed!")
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
        self._running = False

        ctk.CTkLabel(self, text="Item Shop",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=C["text"]).pack(pady=(24, 8))
        ctk.CTkLabel(self, text="Generate a grid image of today's Fortnite Item Shop.",
                     text_color=C["text_dim"], font=ctk.CTkFont(size=13)).pack(pady=(0, 20))

        self._gen_btn = ctk.CTkButton(
            self, text="🛒  Generate Shop Image", width=220, height=44,
            fg_color=C["accent_btn"], hover_color=C["accent"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_shop
        )
        self._gen_btn.pack(pady=10)

        self._prog = ctk.CTkProgressBar(self, height=8, progress_color=C["accent"])
        self._prog.set(0)
        self._prog.pack(fill="x", padx=60, pady=8)

        self._preview_label = ctk.CTkLabel(self, text="", image=None)
        self._preview_label.pack(pady=10, expand=True)

        self._open_btn = ctk.CTkButton(
            self, text="Open Merged Image", width=180, height=36,
            fg_color=C["card"], hover_color=C["border"],
            state="disabled",
            command=lambda: open_file("merged/shop.jpg")
        )
        self._open_btn.pack(pady=4)
        self._thumb_ref = None

    def _start_shop(self):
        if self._running:
            return
        self._running = True
        self._gen_btn.configure(state="disabled", text="Generating…")
        self._prog.set(0)
        threading.Thread(target=self._run_shop, daemon=True).start()

    def _run_shop(self):
        from ALmodules.shop import generate_shop
        generate_shop(self.app.cfg, self.app.tw)

        # Show preview of merged shop image
        self.after(0, self._show_preview)
        self.after(0, lambda: self._gen_btn.configure(state="normal",
                                                        text="🛒  Generate Shop Image"))
        self.after(0, lambda: self._prog.set(1.0))
        self.after(0, lambda: self._open_btn.configure(state="normal"))
        self._running = False

    def _show_preview(self):
        try:
            pil = PILImage.open("merged/shop.jpg")
            # Fit to ~500px wide
            ratio = 500 / pil.width
            new_h = int(pil.height * ratio)
            pil = pil.resize((500, new_h), PILImage.LANCZOS)
            ctkimg = ctk.CTkImage(light_image=pil, dark_image=pil, size=(500, new_h))
            self._thumb_ref = ctkimg
            self._preview_label.configure(image=ctkimg)
        except Exception:
            pass


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

        # Bottom console strip (always visible)
        self._console_strip = ctk.CTkTextbox(
            self, height=120, fg_color=C["input_bg"],
            font=_mono_font(11),
            text_color=C["text_dim"], state="disabled", corner_radius=0
        )
        self._console_strip.grid(row=1, column=0, columnspan=2, sticky="ew")

        # ── pages ─────────────────────────────────────────────────────────────
        self.pages: dict[str, _Page] = {}
        for key, PageClass in [
            ("dashboard", DashboardPage),
            ("generate",  GeneratePage),
            ("search",    SearchPage),
            ("shop",      ShopPage),
            ("monitors",  MonitorsPage),
            ("settings",  SettingsPage),
            ("console",   ConsolePage),
        ]:
            page = PageClass(self._content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

        # ── start ─────────────────────────────────────────────────────────────
        self.show_page("dashboard")
        self._poll_log_queue()

        # Redirect stdout
        sys.stdout = _ConsoleRedirector(self._log_queue)

    # ── sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> ctk.CTkFrame:
        sb = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, width=180)
        sb.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(20, weight=1)

        # Logo
        ctk.CTkLabel(sb, text="FNLeak",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=C["accent"]).grid(row=0, column=0, padx=16, pady=(20, 4))
        ctk.CTkLabel(sb, text="by Fevers",
                     font=ctk.CTkFont(size=10), text_color=C["text_dim"]).grid(
            row=1, column=0, padx=16, pady=(0, 16))

        nav = [
            ("dashboard", "🏠  Home"),
            ("generate",  "⚡  Generate"),
            ("search",    "🔍  Search"),
            ("shop",      "🛒  Item Shop"),
            ("monitors",  "👁  Monitors"),
            ("settings",  "⚙️  Settings"),
            ("console",   "🖥  Console"),
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
