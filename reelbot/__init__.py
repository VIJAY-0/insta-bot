"""Instagram DM -> Reel bot.

When an allowed sender DMs one of the accounts in accounts.toml a reel link (or shares a reel
with it):
  1. Meta's Messaging webhook delivers the DM            (server.py, messages.py)
  2. the video is downloaded                             (bot.py, downloader.py)
  3. it is published as a Reel on the account that received the DM; Instagram fetches the
     file from PUBLIC_URL/media/...                      (bot.py, instagram.py)
  4. the sender gets a DM reply with the result.

Run with ``python -m reelbot``. Setup: see README.md.
"""
