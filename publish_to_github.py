"""
publish_to_github.py — Push FNLeak to GitHub without needing git installed.

Uses the GitHub REST API directly via requests (already installed).

Usage:
    python3 publish_to_github.py

You will be prompted for:
  - Your GitHub Personal Access Token
  - The repo name (default: FNLeak)
  - Whether to make it public or private
"""

import base64
import json
import os
import sys
import time

import requests

# ── files to include in the repo ─────────────────────────────────────────────
# Everything except the auto-generated/runtime directories
EXCLUDE_DIRS  = {"cache", "icons", "merged", "__pycache__", ".git", "rarities", "venv", ".venv"}
EXCLUDE_FILES = {"publish_to_github.py"}   # don't push this script itself
INCLUDE_EXTS  = {".py", ".json", ".txt", ".md", ".sh", ".bat", ".gitignore"}
INCLUDE_NAMES = {".gitignore"}   # exact filenames to always include regardless of extension


def collect_files(root: str) -> dict[str, bytes]:
    """Walk the project directory and return {relative_path: bytes}."""
    files: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded directories in-place (modifies list to stop os.walk descending)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]

        for fname in filenames:
            if fname in EXCLUDE_FILES:
                continue
            # Always include exact name matches (e.g. .gitignore)
            if fname not in INCLUDE_NAMES:
                if fname.startswith("."):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in INCLUDE_EXTS:
                    continue

            full_path = os.path.join(dirpath, fname)
            rel_path  = os.path.relpath(full_path, root).replace(os.sep, "/")

            try:
                with open(full_path, "rb") as f:
                    files[rel_path] = f.read()
            except Exception as e:
                print(f"  Warning: could not read {rel_path}: {e}")

    return files


def github_request(method: str, url: str, token: str, **kwargs) -> requests.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return requests.request(method, url, headers=headers, **kwargs)


def create_repo(token: str, owner: str, repo_name: str, public: bool, description: str) -> dict:
    """Create the repo. Returns the repo JSON dict."""
    url  = "https://api.github.com/user/repos"
    data = {
        "name":        repo_name,
        "description": description,
        "private":     not public,
        "auto_init":   False,
    }
    resp = github_request("POST", url, token, json=data)
    if resp.status_code == 422:
        # Repo already exists — fetch it instead
        print(f"  Repo already exists, fetching existing repo…")
        resp2 = github_request("GET", f"https://api.github.com/repos/{owner}/{repo_name}", token)
        resp2.raise_for_status()
        return resp2.json()
    resp.raise_for_status()
    return resp.json()


def upload_file(token: str, owner: str, repo: str, path: str, content: bytes, message: str) -> bool:
    """Create or update a single file in the repo. Returns True on success."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    # Check if file already exists (needed for SHA when updating)
    sha = None
    check = github_request("GET", url, token)
    if check.status_code == 200:
        sha = check.json().get("sha")

    payload: dict = {
        "message": message,
        "content": base64.b64encode(content).decode(),
    }
    if sha:
        payload["sha"] = sha

    resp = github_request("PUT", url, token, json=payload)
    return resp.status_code in (200, 201)


def get_authenticated_user(token: str) -> str:
    resp = github_request("GET", "https://api.github.com/user", token)
    resp.raise_for_status()
    return resp.json()["login"]


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    print("\n  FNLeak → GitHub Publisher")
    print("  ─────────────────────────────────────────────")
    print()
    print("  You need a Personal Access Token with 'repo' scope.")
    print("  Create one at:  https://github.com/settings/tokens/new")
    print("  → Select scope:  repo  (full control of private repositories)")
    print("  → Click 'Generate token' and copy it")
    print()

    token = input("  Paste your token here (hidden when you type): ").strip()
    if not token:
        print("No token provided. Exiting.")
        sys.exit(1)

    print("\n  Verifying token…", end=" ", flush=True)
    try:
        owner = get_authenticated_user(token)
    except Exception as e:
        print(f"\n  ERROR: Token invalid or network issue: {e}")
        sys.exit(1)
    print(f"Logged in as: {owner}")

    repo_name   = input(f"\n  Repo name (press Enter for 'FNLeak'): ").strip() or "FNLeak"
    visibility  = input("  Public or private? (public/private, Enter = public): ").strip().lower()
    public      = visibility != "private"
    description = "Fortnite cosmetic leak tool — rebuilt AutoLeak with GUI, Pillow 10+, macOS + Windows support"

    print(f"\n  Creating repo '{owner}/{repo_name}' ({'public' if public else 'private'})…", end=" ")
    try:
        repo = create_repo(token, owner, repo_name, public, description)
    except Exception as e:
        print(f"\n  ERROR creating repo: {e}")
        sys.exit(1)
    html_url = repo.get("html_url", f"https://github.com/{owner}/{repo_name}")
    print(f"OK\n  → {html_url}")

    # Collect files
    root  = os.path.dirname(os.path.abspath(__file__))
    files = collect_files(root)
    print(f"\n  Found {len(files)} files to upload:")
    for p in sorted(files):
        print(f"    {p}")

    print(f"\n  Uploading to GitHub…")
    ok = 0
    fail = 0
    commit_msg = "Initial release — FNLeak (rebuilt AutoLeak with Claude Code)"

    for i, (path, content) in enumerate(sorted(files.items()), 1):
        print(f"  [{i:2d}/{len(files)}] {path}", end=" … ", flush=True)
        try:
            success = upload_file(token, owner, repo_name, path, content, commit_msg)
            if success:
                print("✓")
                ok += 1
            else:
                print("✗ (unexpected response)")
                fail += 1
        except Exception as e:
            print(f"✗ ({e})")
            fail += 1
        # GitHub API rate limit: 5000 requests/hour for authenticated users,
        # but creating file contents can be slow — small sleep keeps it stable
        time.sleep(0.3)

    print(f"\n  ─────────────────────────────────────────────")
    print(f"  Uploaded {ok}/{len(files)} files  ({fail} failed)")
    print(f"\n  Repo live at: {html_url}")
    print()


if __name__ == "__main__":
    main()
