import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reelbot.config import Settings


class DownloadDirTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()  # a project folder without .env
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)

    def download_dir(self, value: str | None) -> Path:
        env = {k: v for k, v in os.environ.items() if k != "DOWNLOAD_DIR"}
        if value is not None:
            env["DOWNLOAD_DIR"] = value
        with mock.patch.dict(os.environ, env, clear=True):
            return Settings.from_env(self.project).download_dir

    def test_defaults_to_downloads_in_the_project(self):
        self.assertEqual(self.download_dir(None), self.project / "downloads")
        self.assertEqual(self.download_dir(""), self.project / "downloads")

    def test_relative_paths_are_relative_to_the_project(self):
        self.assertEqual(self.download_dir("media/reels"), self.project / "media" / "reels")

    def test_absolute_path(self):
        absolute = self.project.parent / "elsewhere"
        self.assertEqual(self.download_dir(str(absolute)), absolute)

    def test_home_folder(self):
        self.assertEqual(self.download_dir("~/reels"), Path.home() / "reels")
