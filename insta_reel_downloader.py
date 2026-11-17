#!/usr/bin/env python3
"""Download Instagram Reels (and video posts) from their URLs. The bot doesn't need this.

Usage:
    python insta_reel_downloader.py https://www.instagram.com/reel/XXXXXXXXXXX/
    python insta_reel_downloader.py URL1 URL2 -o my_reels
    python insta_reel_downloader.py -f urls.txt
    python insta_reel_downloader.py URL --cookies-from-browser firefox
    python insta_reel_downloader.py            (prompts for a URL)

Only download content you own or have permission to save.
"""

import argparse
import sys
from pathlib import Path

try:
    import yt_dlp

    from reelbot.downloader import is_instagram_url, ytdlp_options
except ImportError as e:
    sys.exit(f"{e}. Run:  pip install -r requirements.txt")

LOGIN_HINTS = ("login", "log in", "cookies", "rate-limit", "rate limit", "private", "not available")


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


def build_options(args: argparse.Namespace, saved: list[str]) -> dict:
    opts = ytdlp_options(args.output / "%(uploader|instagram)s_%(id)s.%(ext)s",
                         cookies_file=args.cookies, cookies_from_browser=args.cookies_from_browser)
    opts["progress_hooks"] = [progress_hook]
    opts["post_hooks"] = [saved.append]  # receives the final file path
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


def parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(description="Download Instagram Reels from their URLs.")
    parser.add_argument("urls", nargs="*", help="one or more Instagram reel/post URLs")
    parser.add_argument("-f", "--file", type=Path, help="text file with one URL per line")
    parser.add_argument("-o", "--output", type=Path, default=Path("downloads"),
                        help="folder to save videos in (default: ./downloads)")
    parser.add_argument("--cookies", type=Path,
                        help="Netscape-format cookies.txt exported from a browser logged in to Instagram")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="use Instagram login cookies from a browser: firefox, chrome, edge, brave, ...")
    return parser, parser.parse_args()


def main() -> int:
    parser, args = parse_args()
    urls = collect_urls(args)
    if not urls:
        parser.error("no URL given")

    valid = []
    for url in urls:
        if is_instagram_url(url):
            valid.append(url)
        else:
            print(f"Skipping (not an Instagram reel/post URL): {url}")
    if not valid:
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    failed: list[str] = []

    with yt_dlp.YoutubeDL(build_options(args, saved)) as ydl:
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
