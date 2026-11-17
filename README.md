# Instagram DM → Reel bot

DM one of your Instagram accounts a reel link (or share a reel to it). The bot downloads the
video, publishes it as a Reel on **the account that received the DM**, and replies with the link.

```
reelbot/                    the bot (run: python -m reelbot)
  __main__.py               entry point: load config, start the worker, serve HTTP
  config.py                 server settings from .env
  accounts.py               loads and validates accounts.toml, reloads it when it changes
  server.py                 HTTP routes: health, Meta webhook, temporary /media/ URLs
  messages.py               webhook payload -> jobs (routing, allowed senders, dedupe)
  bot.py                    job queue and worker: download -> publish -> reply
  downloader.py             downloads reels with yt-dlp, or shared videos by direct URL
  instagram.py              Graph API client (send DM, create container, wait, publish)
  checks.py                 startup checks for each account and PUBLIC_URL
tests/                      unit tests (run: python -m unittest)
insta_reel_downloader.py    standalone CLI, not needed by the bot:
                            python insta_reel_downloader.py "<reel link>"
```

## Configuration

| File | What goes in it | In git? |
|---|---|---|
| `.env` | Server settings: `PUBLIC_URL`, `APP_SECRET`, `VERIFY_TOKEN`, `DRY_RUN`, `PORT` | No (template: `.env.example`) |
| `accounts.toml` | One block per Instagram account: ID, token, allowed senders | No (template: `accounts.example.toml`) |

```toml
[accounts.gta6ontape]
ig_account_id = "17841426634636903"
access_token = "EAA..."
allowed_senders = ["1352797710166784"]
# enabled = false   # ignore this account
# dry_run = true    # don't post for this account
```

The bot reloads `accounts.toml` when you save it. Changes to `.env` need a restart.

## Setup

1. **Install:** `pip install -r requirements.txt`
2. **Meta app** (developers.facebook.com → your app → Use cases → Instagram API):
   - Each Instagram account must be a **professional** account.
   - Permissions: `instagram_basic`, `instagram_content_publish`, `instagram_manage_messages`.
   - Token: a system user token (EAA…, never expires) that has the Instagram account assigned
     in Business settings, or an Instagram Login token (IGAA…, lasts 60 days).
3. **Public URL:** point a public HTTPS address at this machine's `PORT` and set `PUBLIC_URL`.
   Instagram downloads the video from `PUBLIC_URL/media/...` when publishing.
4. **Webhook** (Use cases → Instagram API → API setup):
   - Callback URL: `PUBLIC_URL/webhook`, verify token: `VERIFY_TOKEN` from `.env`.
   - Subscribe to the **messages** field.
   - On each Instagram account: Settings → Messages and story replies → Message controls →
     **Allow access to messages**.
   - In Development mode Meta only delivers DMs from accounts with a role on the app.
5. **Run:** `python -m reelbot` (or double-click `run_bot.bat`). The startup log checks every account.

## Adding an account or a sender

1. DM the account from the sender's Instagram.
2. The log shows one of:
   - `DM to Instagram account 1784..., which is not in accounts.toml` → add an
     `[accounts.<name>]` block with that `ig_account_id` and a token that can manage it.
   - `Ignoring DM to [name] from sender 135...` → add that ID to the account's `allowed_senders`.
3. Save `accounts.toml`. A person's sender ID is different on every account.

## Using it

- Send a reel link → it's posted with a credit line, e.g. `🎥 @originalcreator`.
- Text in the same message as the link becomes the caption:
  `Monday mood https://www.instagram.com/reel/...`
- Sharing a reel with the Share button also works. If a shared reel fails, send its link instead.

Repost only content you own or have permission to use; reposting others' reels can lead to
copyright strikes on the account.
