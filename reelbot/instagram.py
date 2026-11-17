"""Minimal Instagram Graph API client.

Works with both token types:
  - Instagram Login tokens (start with IGAA)                -> graph.instagram.com
  - Facebook / Unified login / system user tokens (EAA...)  -> graph.facebook.com
"""

import time

import requests

MESSAGE_LIMIT_BYTES = 1000  # Instagram's limit for a DM's text


class InstagramError(Exception):
    pass


class InstagramAPI:
    def __init__(self, access_token: str, api_version: str = "v27.0"):
        host = "graph.instagram.com" if access_token.startswith("IG") else "graph.facebook.com"
        self.base = f"https://{host}/{api_version}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    def username(self, ig_id: str) -> str | None:
        return self._request("GET", ig_id, params={"fields": "username"}).get("username")

    def publishing_limit(self, ig_id: str) -> dict:
        """{"quota_usage": posts in the last 24h, "config": {"quota_total": ...}}"""
        data = self._request("GET", f"{ig_id}/content_publishing_limit",
                             params={"fields": "config,quota_usage"})
        return (data.get("data") or [{}])[0]

    def send_text(self, ig_id: str, recipient_id: str, text: str) -> dict:
        text = text.encode("utf-8")[:MESSAGE_LIMIT_BYTES].decode("utf-8", errors="ignore")
        return self._request("POST", f"{ig_id}/messages",
                             json={"recipient": {"id": recipient_id}, "message": {"text": text}})

    def publish_reel(self, ig_id: str, video_url: str, caption: str = "",
                     poll_every: int = 20, timeout: int = 600) -> tuple[str, str | None]:
        """Create a Reels container from a public video URL, wait for processing, publish it.

        Returns (media_id, permalink).
        """
        container = self._request("POST", f"{ig_id}/media",
                                  json={"media_type": "REELS", "video_url": video_url, "caption": caption})
        self._wait_until_processed(container["id"], poll_every, timeout)
        media_id = self._request("POST", f"{ig_id}/media_publish", json={"creation_id": container["id"]})["id"]
        try:
            permalink = self._request("GET", media_id, params={"fields": "permalink"}).get("permalink")
        except InstagramError:
            permalink = None
        return media_id, permalink

    def _wait_until_processed(self, container_id: str, poll_every: int, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        while True:
            time.sleep(poll_every)
            status = self._request("GET", container_id, params={"fields": "status_code"}).get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Instagram could not process the video (status {status}). "
                                     "Check that PUBLIC_URL is reachable from the internet.")
            if time.monotonic() > deadline:
                raise InstagramError("Timed out waiting for Instagram to process the video.")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = self.session.request(method, f"{self.base}/{path}", timeout=60, **kwargs)
        except requests.RequestException as e:
            raise InstagramError(f"Network error talking to Instagram: {e}") from None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not resp.ok or "error" in data:
            err = data.get("error") or {}
            message = err.get("message") or resp.text[:300]
            raise InstagramError(f"{message} (HTTP {resp.status_code}, code {err.get('code')})")
        return data
