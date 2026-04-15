"""
twitter_client.py — Tweepy v4 wrapper.

Changes vs the original AutoLeak:
  - Uses tweepy.Client (v2 API) for text-only tweets instead of the
    deprecated api.update_status() (v1.1).
  - Media upload still uses tweepy.API (v1.1) because Twitter's v2
    media endpoint is not yet available to most tiers.
  - Gracefully disables itself when no API keys are present, so the
    rest of the program works without Twitter configured.
  - Single class, no global state.
"""

from __future__ import annotations

from typing import Optional


class TwitterClient:
    """
    Wraps tweepy for both text tweets (v2) and media tweets (v1.1 upload + v2 post).

    If any credential is missing/empty, self.ready is False and all
    methods become no-ops with a warning instead of crashing.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
    ) -> None:
        self.ready = False
        self._client = None
        self._api    = None

        if not all([api_key, api_secret, access_token, access_token_secret]):
            return

        try:
            import tweepy

            # v1.1 API (needed for media_upload)
            auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
            self._api = tweepy.API(auth)

            # v2 Client (preferred for creating tweets)
            self._client = tweepy.Client(
                consumer_key=api_key,
                consumer_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
            )

            self.ready = True
        except ImportError:
            print("[TwitterClient] tweepy not installed — Twitter disabled.")
        except Exception as e:
            print(f"[TwitterClient] Auth error: {e}")

    # ── public methods ────────────────────────────────────────────────────────

    def tweet(self, text: str) -> None:
        """Post a text-only tweet via the v2 API."""
        if not self.ready:
            print("[TwitterClient] Not configured — skipping tweet.")
            return
        try:
            self._client.create_tweet(text=text)
        except Exception as e:
            raise RuntimeError(f"Tweet failed: {e}") from e

    def tweet_with_media(self, image_path: str, text: str) -> None:
        """
        Upload an image via v1.1 media_upload, then post a tweet with it via v2.

        Requires Elevated access on the Twitter Developer Portal for media uploads.
        """
        if not self.ready:
            print("[TwitterClient] Not configured — skipping media tweet.")
            return
        try:
            media = self._api.media_upload(filename=image_path)
            self._client.create_tweet(text=text, media_ids=[media.media_id])
        except Exception as e:
            raise RuntimeError(f"Media tweet failed: {e}") from e
