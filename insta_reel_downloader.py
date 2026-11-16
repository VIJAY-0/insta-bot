#!/usr/bin/env python3
"""Download Instagram Reels (and video posts) from their URLs.

Usage:
    python insta_reel_downloader.py https://www.instagram.com/reel/XXXXXXXXXXX/
    python insta_reel_downloader.py URL1 URL2 -o my_reels
    python insta_reel_downloader.py -f urls.txt
    python insta_reel_downloader.py URL --cookies-from-browser firefox
    python insta_reel_downloader.py            (prompts for a URL)

Only download content you own or have permission to save.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Run:  pip install -r requirements.txt")

# Matches /reel/, /reels/, /p/ and /tv/ links, including the newer
# instagram.com/<username>/reel/<id>/ form and links with ?igsh=... tracking params.
INSTAGRAM_URL = re.compile(
    r"^https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/[\w-]+",
    re.IGNORECASE,
)

LOGIN_HINTS = ("login", "log in", "cookies", "rate-limit", "rate limit", "private", "not available")


class SilentLogger:
    """Keeps yt-dlp quiet; errors are still raised and reported by main()."""

    def debug(self, msg: str) -> None: pass
    def info(self, msg: str) -> None: pass
    def warning(self, msg: str) -> None: pass
    def error(self, msg: str) -> None: pass


def progress_hook(d: dict) -> None:
    if d["status"] == "downloading":
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            msg = f"{done / total * 100:5.1f}% of {total / 1_048_576:.1f} MB"
        else:
            msg = f"{done / 1_048_576:.1f} MB"
        print(f"\r  Downloading... {msg}   ", end="", flush=True)
    elif d["status"] == "finished":
        print("\r  Download finished." + " " * 30)


def build_options(output_dir: Path, args: argparse.Namespace, saved: list) -> dict:
    has_ffmpeg = shutil.which("ffmpeg") is not None
    opts = {
        "outtmpl": str(output_dir / "%(uploader|instagram)s_%(id)s.%(ext)s"),
        # With ffmpeg: merge the best video and audio streams.
        # Without it: take the best single file that already has both.
        "format": "bv*+ba/b" if has_ffmpeg else "b",
        "merge_output_format": "mp4",
        "logger": SilentLogger(),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "progress_hooks": [progress_hook],
        "post_hooks": [saved.append],  # receives the final file path
    }
    if args.cookies:
        opts["cookiefile"] = str(args.cookies)
    if args.cookies_from_browser:
        opts["cookiesfrombrowser"] = (args.cookies_from_browser.lower(),)
    return opts


def collect_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls)
    if args.file:
        for line in args.file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        entered = input("Paste an Instagram reel URL: ").strip()
        if entered:
            urls.append(entered)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Instagram Reels from their URLs.")
    parser.add_argument("urls", nargs="*", help="one or more Instagram reel/post URLs")
    parser.add_argument("-f", "--file", type=Path, help="text file with one URL per line")
    parser.add_argument("-o", "--output", type=Path, default=Path("downloads"),
                        help="folder to save videos in (default: ./downloads)")
    parser.add_argument("--cookies", type=Path,
                        help="Netscape-format cookies.txt exported from a browser logged in to Instagram")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="use Instagram login cookies from a browser: firefox, chrome, edge, brave, ...")
    args = parser.parse_args()

    urls = collect_urls(args)
    if not urls:
        parser.error("no URL given")

    valid = []
    for url in urls:
        if INSTAGRAM_URL.match(url):
            valid.append(url)
        else:
            print(f"Skipping (not an Instagram reel/post URL): {url}")
    if not valid:
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    failed: list[str] = []

    with yt_dlp.YoutubeDL(build_options(args.output, args, saved)) as ydl:
        for i, url in enumerate(valid, 1):
            print(f"[{i}/{len(valid)}] {url}")
            try:
                ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                failed.append(url)
                message = str(e)
                print(f"  Failed: {message.removeprefix('ERROR: ')}")
                if any(h in message.lower() for h in LOGIN_HINTS):
                    print("  Tip: Instagram often requires a login. Retry with\n"
                          "       --cookies-from-browser firefox   (log in to Instagram in Firefox first)\n"
                          "    or --cookies cookies.txt            (exported from a logged-in browser)")

    print()
    for path in saved:
        print(f"Saved: {Path(path).resolve()}")
    print(f"Done: {len(valid) - len(failed)} succeeded, {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
