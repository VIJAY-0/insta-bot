import unittest
from pathlib import Path

from reelbot.downloader import find_instagram_url, is_instagram_url, ytdlp_options


class InstagramUrlTest(unittest.TestCase):
    def test_finds_supported_link_forms(self):
        for url in ("https://www.instagram.com/reel/ABC_1-x/",
                    "https://instagram.com/reels/ABC/",
                    "http://m.instagram.com/p/ABC/",
                    "https://www.instagram.com/tv/ABC",
                    "https://www.instagram.com/some.user/reel/ABC/?igsh=abc=="):
            with self.subTest(url=url):
                self.assertEqual(find_instagram_url(f"look {url} wow"), url)
                self.assertTrue(is_instagram_url(url))

    def test_rejects_other_links(self):
        for text in ("https://www.instagram.com/some.user/", "https://example.com/reel/ABC", "", None):
            with self.subTest(text=text):
                self.assertIsNone(find_instagram_url(text))

    def test_is_instagram_url_must_start_with_the_link(self):
        self.assertFalse(is_instagram_url("see https://www.instagram.com/reel/ABC/"))


class YtdlpOptionsTest(unittest.TestCase):
    def test_cookies(self):
        opts = ytdlp_options(Path("out") / "%(id)s.%(ext)s", cookies_file=Path("c.txt"),
                             cookies_from_browser="Firefox")
        self.assertEqual(opts["outtmpl"], str(Path("out") / "%(id)s.%(ext)s"))
        self.assertEqual(opts["cookiefile"], "c.txt")
        self.assertEqual(opts["cookiesfrombrowser"], ("firefox",))

    def test_no_cookies_by_default(self):
        opts = ytdlp_options("x")
        self.assertNotIn("cookiefile", opts)
        self.assertNotIn("cookiesfrombrowser", opts)
