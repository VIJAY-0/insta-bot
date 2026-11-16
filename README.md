# Instagram DM → Reel bot

DM your Instagram account a reel link (or share a reel to it). The bot downloads the video,
publishes it as a Reel on the account, and replies in the DM with the post link.

- `app.py` – webhook server, job queue, publishing flow (original prototype kept as `app_prototype.py`)
- `downloader.py` – downloads reels with yt-dlp, or shared videos by direct URL
- `instagram_api.py` – Graph API calls (send DM, create container, wait, publish)
- `insta_reel_downloader.py` – standalone command-line downloader, not needed by the bot:
  `python insta_reel_downloader.py "<reel link>"`

## Setup

1. **Install:** `pip install -r requirements.txt`

2. **Meta app** (developers.facebook.com → your app → Instagram → *API setup with Instagram login*):
   - The Instagram account must be a **professional** account (Business or Creator).
   - Permissions: `instagram_business_basic`, `instagram_business_manage_messages`,
     `instagram_business_content_publish`.
   - Put the access token in `.env` as `ACCESS_TOKEN`. A system user token (EAA...) never
     expires; an Instagram Login token (IGAA...) lasts 60 days.
   - Put the app secret in `.env` as `APP_SECRET`.
   - `IG_ACCOUNT_ID`: if the token can't reveal it, the bot logs it from the first DM; paste it in.

3. **Public URL:** point a public HTTPS address at this machine's port 5000 and set
   `PUBLIC_URL=https://your-domain` in `.env` (no trailing slash). Instagram downloads the video
   from `PUBLIC_URL/media/...` when publishing.

4. **Webhook** (same Meta page → *Configure webhooks*):
   - Callback URL: `PUBLIC_URL/webhook` · Verify token: value of `VERIFY_TOKEN` (`omvrti123`)
   - Subscribe to the **messages** field.
   - In Development mode Meta only delivers DMs from accounts with a role on the app
     (add them as Instagram testers) — or switch the app to Live.

5. **Run:** `python app.py`. The startup log checks the token, publish permission and PUBLIC_URL.

6. **Allow senders:** DM the account from your personal Instagram. The log prints
   `Ignoring DM from sender 1234567890...` → put that ID in `ALLOWED_SENDER_IDS` (comma-separate
   several) and restart. Only these accounts can trigger posts.

7. **Test, then go live:** with `DRY_RUN=true` the bot downloads and replies but doesn't post.
   When that works, set `DRY_RUN=false` and restart.

## Using it

- Send a reel link → it's posted with a credit line, e.g. `🎥 @originalcreator`.
- Text in the same message as the link becomes the caption:
  `Monday mood https://www.instagram.com/reel/...`
- Sharing a reel with the Share button also works. If a shared reel fails, send its link instead.

Repost only content you own or have permission to use; reposting others' reels can lead to
copyright strikes on the account.
