# FNLeak

> **The original [AutoLeak](https://github.com/FortniteFevers/AutoLeak/tree/beta), rebuilt from the ground up.**

FNLeak is a Fortnite cosmetic datamine and leak tool — a full rewrite of my original **[AutoLeak](https://github.com/FortniteFevers/AutoLeak/tree/beta)** project, updated to work with modern Python, modern APIs, and featuring a brand-new cross-platform GUI.

The original AutoLeak was written years ago before tools like AI-assisted development existed. The core logic, features, and design are all mine — this version takes that original code and, using **[Claude Code](https://claude.ai/claude-code)** (Anthropic's AI coding tool), updates it to the maximum extent possible: fixing every deprecated API call, eliminating thousands of lines of duplicated code, adding a full GUI, and making it run natively on both macOS and Windows.

---

## What's new vs the original AutoLeak

| Area | Original AutoLeak | FNLeak |
|---|---|---|
| Interface | Terminal menu only | Full GUI + terminal CLI |
| Platform | Windows-focused | macOS + Windows |
| Pillow compat | Broke on Pillow 10+ (`ANTIALIAS`, `getsize`, `textsize` removed) | Pillow 10/11 fully compatible |
| Twitter/X | Tweepy v1.1 `update_with_media` (deprecated) | Tweepy v4, v2 API (`create_tweet` + `media_upload`) |
| Monitors | Recursive retry calls (stack overflow risk) | Proper `while` loops, all in background threads |
| Dependencies | Hard crash if `pypresence`/`tkinter` missing | Optional — gracefully disabled if absent |
| `benbot.app` | Hard dependency (often down) | Removed — all calls via `fortnite-api.com` |
| Code size | ~3,100 lines, heavily duplicated | ~1,400 lines, fully modular |
| Rarity assets | Required original proprietary files | Auto-generated gradient backgrounds on first run |

---

## Features

- **Generate Cosmetics** — Detect a new Fortnite update and generate styled card images for every new cosmetic
- **Search** — Look up any cosmetic by name or ID and generate its card
- **Item Shop** — Generate a full grid image of the current Item Shop
- **Update Mode** — Polls for hash changes and auto-generates on a new patch
- **BR News Watcher** — Monitors the Battle Royale news feed
- **Notices Watcher** — Monitors Fortnite emergency status changes
- **Staging Server Watcher** — Detects Epic's pre-release version bumps
- **Shop Sections Watcher** — Monitors Item Shop section layout changes
- **Set Search** — Generate cards for all items in a named cosmetic set
- **Pak Search** — Generate cards from a dynamic pak ID
- **Twitter/X Integration** — Auto-tweet generated images and updates

### Card styles (iconType)
- `new` — Large centred name + description (default)
- `cataba` — Fortnite-style layered composite with backend type badge
- `standard` — Centred name + description + item ID
- `clean` — Left-aligned minimal style
- `large` — Same layout as `new`, suited for featured images

---

## Requirements

| Requirement | Version |
|---|---|
| Python | **3.10 or newer** (3.13 recommended) |
| Pillow | 10.0+ |
| requests | 2.31+ |
| colorama | 0.4.6+ |
| tweepy | 4.14+ |
| customtkinter | 5.2+ *(GUI only)* |

---

## Installation

### macOS

```bash
# 1. Install Python 3.13 from https://www.python.org/downloads/
#    (or via Homebrew: brew install python@3.13)

# 2. Clone the repo
git clone https://github.com/FortniteFevers/FNLeak.git
cd FNLeak

# 3. Install dependencies + launch
./run.sh
```

### Windows

```batch
:: 1. Install Python 3.13 from https://www.python.org/downloads/
::    Make sure to check "Add Python to PATH" during install

:: 2. Clone the repo
git clone https://github.com/FortniteFevers/FNLeak.git
cd FNLeak

:: 3. Install dependencies + launch
run.bat
```

### Manual install (any platform)

```bash
pip install -r requirements.txt
python gui.py          # GUI
python bot.py          # Terminal CLI
```

---

## Configuration (`settings.json`)

Edit `settings.json` directly, or use the **Settings** page in the GUI.

```json
{
  "name": "YourLeakName",
  "language": "en",
  "iconType": "new",
  "watermark": "YourName",

  "twitAPIKey": "",
  "twitAPISecretKey": "",
  "twitAccessToken": "",
  "twitAccessTokenSecret": "",

  "MergeImages": true,
  "AutoTweetMerged": false,
  "BotDelay": 30
}
```

### All settings

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | `"FNLeak"` | Label shown in tweets and filenames |
| `footer` | string | `"#Fortnite"` | Appended to text-only tweets |
| `language` | string | `"en"` | Cosmetic language (`en`, `de`, `fr`, `es`, `ja`, `ko`, `ru`, `zh-CN`, + more) |
| `iconType` | string | `"new"` | Card style: `new` / `cataba` / `standard` / `clean` / `large` |
| `imageFont` | string | `"BurbankBigCondensed-Black.otf"` | Main font filename (place in `fonts/`) |
| `sideFont` | string | `"OpenSans-Regular.ttf"` | Secondary font filename (place in `fonts/`) |
| `watermark` | string | `""` | Text drawn top-left on every card |
| `useFeaturedIfAvailable` | bool | `false` | Use featured image over icon if available |
| `showitemsource` | bool | `true` | Draw the gameplay source tag on cards |
| `MergeImages` | bool | `true` | Auto-merge all cards into a grid image |
| `MergeWatermarkUrl` | string | `""` | URL or `image/<filename>` for merge watermark |
| `AutoTweetMerged` | bool | `false` | Auto-tweet merged image after generation |
| `BotDelay` | int | `30` | Seconds between monitor poll checks |
| `twitAPIKey` | string | `""` | Twitter/X API Key |
| `twitAPISecretKey` | string | `""` | Twitter/X API Secret |
| `twitAccessToken` | string | `""` | Twitter/X Access Token |
| `twitAccessTokenSecret` | string | `""` | Twitter/X Access Token Secret |

### Fonts (optional)

Place font `.otf`/`.ttf` files in the `fonts/` directory. The tool falls back to PIL's built-in font if none are present.

Recommended fonts that match the Fortnite style:
- **Burbank Big Condensed Black** (main card title font)
- **Open Sans Regular** (description/set text)

---

## Twitter / X Setup

1. Go to [developer.twitter.com](https://developer.twitter.com) and create an app
2. Under **Keys and Tokens**, generate your API Key, Secret, Access Token, and Access Token Secret
3. Add them to `settings.json` or the Settings page in the GUI
4. **Media uploads require Elevated access** — apply for it in the developer portal

---

## Project Structure

```
FNLeak/
├── gui.py              # GUI entry point (CustomTkinter)
├── bot.py              # Terminal CLI entry point
├── settings.json       # User configuration
├── requirements.txt    # Python dependencies
├── run.sh              # macOS/Linux launch script
├── run.bat             # Windows launch script
├── ALmodules/
│   ├── image_gen.py    # Cosmetic card generation (all icon styles)
│   ├── merger.py       # Grid image merger
│   ├── compressor.py   # Image compression for Twitter size limits
│   ├── twitter_client.py # Tweepy v4 wrapper
│   ├── monitors.py     # Update/news/notices/staging watchers
│   ├── shop.py         # Item Shop generation + shop sections watcher
│   └── setup.py        # First-run setup (directories + rarity assets)
├── fonts/              # Place your .otf / .ttf fonts here
├── rarities/           # Auto-generated rarity background PNGs
├── icons/              # Output: individual cosmetic card images
├── merged/             # Output: merged grid images
├── cache/              # Temp: downloaded icon images
└── assets/             # Static assets (watermark images, etc.)
```

---

## APIs used

| API | Purpose |
|---|---|
| [fortnite-api.com](https://fortnite-api.com) | Cosmetics, new items, AES keys, news, shop, status |
| [Twitter/X API v2](https://developer.twitter.com) | Posting tweets and media (optional) |
| Epic Games Staging | Pre-release version detection |

---

## License

This project is open-source for **educational and personal use**.

> All cosmetic images, names, and game assets are property of **Epic Games**.
> This tool uses publicly available third-party APIs and does not bypass any access controls.

---

## Credits

**Created by Fevers** ([@FortniteFevers](https://github.com/FortniteFevers))

Original project: **[AutoLeak](https://github.com/FortniteFevers/AutoLeak)**

This version was rewritten and updated using **[Claude Code](https://claude.ai/claude-code)** by Anthropic — the original logic, architecture, and feature set are entirely the work of Fevers.

---

*If you have issues or want to contribute, open an issue or join the [AutoLeak Discord](https://dsc.gg/autoleak).*
