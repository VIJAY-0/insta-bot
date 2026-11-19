"""Download a reel from an Instagram link, or a video from a direct media URL.

Also used by the standalone command-line downloader (insta_reel_downloader.py).
"""

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import requests
import yt_dlp

# /reel/, /reels/, /p/ and /tv/ links, incl. instagram.com/<user>/reel/<id>/ and ?igsh=... params.
INSTAGRAM_URL = re.compile(
    r"https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/[\w-]+\S*",
    re.IGNORECASE,
)
MAX_BYTES = 300 * 1024 * 1024  # Instagram's size limit for Reels
VIDEO_SUFFIXES = {".mp4", ".mov"}


class DownloadError(Exception):
    pass


@dataclass
class Video:
    path: Path
    username: str | None = None  # original creator
    description: str | None = None  # the original post's caption


def find_instagram_url(text: str) -> str | None:
    """The first Instagram reel/post link in text, if any."""
    match = INSTAGRAM_URL.search(text or "")
    return match.group(0) if match else None


def is_instagram_url(url: str) -> bool:
    return INSTAGRAM_URL.match(url) is not None


class _SilentLogger:
    """Keeps yt-dlp quiet; failures still raise and are reported by the caller."""

    def debug(self, msg: str) -> None:
        pass

    info = warning = error = debug


def ytdlp_options(output_template: str | Path, cookies_file: str | Path | None = None,
                  cookies_from_browser: str | None = None) -> dict:
    """yt-dlp options shared by the bot and the command-line downloader."""
    opts = {
        "outtmpl": str(output_template),
        # With ffmpeg: merge best video + audio. Without: best single file that has both.
        "format": "bv*+ba/b" if shutil.which("ffmpeg") else "b",
        "merge_output_format": "mp4",
        "logger": _SilentLogger(),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser.lower(),)
    return opts


def download(url: str, out_dir: Path, cookies_file: str | None = None) -> Video:
    """Save the video at url into out_dir. Raises DownloadError with a user-presentable message."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if is_instagram_url(url):
        return _download_with_ytdlp(url, out_dir, cookies_file)
    return _download_direct(url, out_dir)


def _download_with_ytdlp(url: str, out_dir: Path, cookies_file: str | None) -> Video:
    opts = ytdlp_options(out_dir / "%(id)s.%(ext)s", cookies_file)
    opts["playlist_items"] = "1"  # carousel posts: take the first item
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e).removeprefix("ERROR: ")) from None

    if info.get("_type") == "playlist":
        info = next((entry for entry in info.get("entries") or [] if entry), {})
    downloads = info.get("requested_downloads") or []
    path = Path(downloads[0]["filepath"]) if downloads else None
    if path is None or not path.exists() or path.suffix.lower() not in VIDEO_SUFFIXES:
        raise DownloadError("That post doesn't contain a downloadable video.")
    return Video(path=path, username=info.get("channel"), description=info.get("description"))


def _download_direct(url: str, out_dir: Path) -> Video:
    path = out_dir / f"shared_{uuid.uuid4().hex[:12]}.mp4"
    try:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("video/"):
                raise DownloadError(f"The shared item is not a video ({content_type or 'unknown type'}).")
            size = 0
            with open(path, "wb") as f:
                for chunk in resp.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise DownloadError("The video is larger than Instagram's 300 MB limit.")
                    f.write(chunk)
    except requests.RequestException as e:
        path.unlink(missing_ok=True)
        raise DownloadError(f"Could not fetch the shared video: {e}") from None
    except DownloadError:
        path.unlink(missing_ok=True)
        raise
    return Video(path=path)
