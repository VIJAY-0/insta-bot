import os
import tempfile
import unittest
from pathlib import Path

from reelbot.accounts import AccountStore, ConfigError, load_accounts

from .helpers import ACCOUNTS_TOML, IG_ID


class AccountsFileTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "accounts.toml"

    def write(self, text: str) -> None:
        self.path.write_text(text, encoding="utf-8")


class LoadAccountsTest(AccountsFileTestCase):
    def test_loads_accounts_by_id(self):
        self.write(ACCOUNTS_TOML + """
[accounts.second]
ig_account_id = 17841400000000002
access_token = "IGAA-test"
allowed_senders = [7, " 8 ", ""]
enabled = false
dry_run = true
""")
        accounts = load_accounts(self.path, "v27.0")
        main, second = accounts[IG_ID], accounts["17841400000000002"]
        self.assertEqual((main.name, main.allowed_senders, main.enabled, main.dry_run),
                         ("main", {"42"}, True, False))
        self.assertEqual((second.name, second.allowed_senders, second.enabled, second.dry_run),
                         ("second", {"7", "8"}, False, True))
        self.assertTrue(main.api.base.startswith("https://graph.facebook.com/"))
        self.assertTrue(second.api.base.startswith("https://graph.instagram.com/"))

    def test_default_dry_run_applies_unless_account_sets_it(self):
        self.write(ACCOUNTS_TOML)
        self.assertTrue(load_accounts(self.path, "v27.0", default_dry_run=True)[IG_ID].dry_run)
        self.write(ACCOUNTS_TOML + "dry_run = false\n")
        self.assertFalse(load_accounts(self.path, "v27.0", default_dry_run=True)[IG_ID].dry_run)

    def test_invalid_files(self):
        cases = {
            "not valid TOML": "[accounts.main",
            "no [accounts.<name>] sections": "",
            "numeric Instagram account ID": ACCOUNTS_TOML.replace(IG_ID, "@me"),
            "access_token is missing": ACCOUNTS_TOML.replace('"EAA-test"', '""'),
            "must be a list": ACCOUNTS_TOML.replace('["42"]', '"42"'),
            "enabled must be true or false": ACCOUNTS_TOML + 'enabled = "false"\n',
            "already used by [accounts.main]": ACCOUNTS_TOML + ACCOUNTS_TOML.replace("main", "copy"),
            "expected a section": 'accounts.main = "x"',
        }
        for expected, text in cases.items():
            with self.subTest(expected):
                self.write(text)
                with self.assertRaisesRegex(ConfigError, expected.replace("[", r"\[")):
                    load_accounts(self.path, "v27.0")

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_accounts(self.path, "v27.0")


class AccountStoreTest(AccountsFileTestCase):
    def touch_later(self) -> None:
        """Make sure the next write gets a new mtime, however coarse the filesystem clock is."""
        stat = self.path.stat()
        os.utime(self.path, (stat.st_atime, stat.st_mtime + 10))

    def test_first_load_error_raises(self):
        store = AccountStore(self.path, "v27.0")
        with self.assertRaises(ConfigError):
            store.get()

    def test_reloads_when_file_changes(self):
        self.write(ACCOUNTS_TOML)
        store = AccountStore(self.path, "v27.0")
        self.assertEqual(store.get()[IG_ID].allowed_senders, {"42"})

        self.write(ACCOUNTS_TOML.replace('["42"]', '["42", "43"]'))
        self.touch_later()
        with self.assertLogs("reelbot.accounts", "INFO"):
            self.assertEqual(store.get()[IG_ID].allowed_senders, {"42", "43"})

    def test_bad_edit_keeps_previous_accounts(self):
        self.write(ACCOUNTS_TOML)
        store = AccountStore(self.path, "v27.0")
        before = store.get()

        self.write("[accounts.main")
        self.touch_later()
        with self.assertLogs("reelbot.accounts", "ERROR"):
            self.assertIs(store.get(), before)
