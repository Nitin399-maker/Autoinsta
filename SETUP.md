# ⚙️ Setup Guide — Instagram News Bot

Follow this guide to get the bot running locally and on GitHub Actions.

---

## Step 1 — Get an OpenRouter API Key

1. Go to [openrouter.ai](https://openrouter.ai) and sign up (free)
2. Go to **Keys** → **Create Key**
3. Copy the key — it starts with `sk-or-...`

This single key powers both:
- **Gemini 2.5 Pro** (`google/gemini-2.5-pro`) — Rewrites news content, generates captions, creates image prompts
- **Gemini 3 Pro Image Preview** (`google/gemini-3-pro-image-preview`) — Generates complete Instagram images with all text, badges, and styling baked in

> OpenRouter offers free credits on signup. Image generation costs are very low.

---

## Step 2 — Install Dependencies

```bash
cd insta
pip install -r requirements.txt
```

This installs:
- `feedparser` — RSS parsing from 23+ news feeds
- `requests` — HTTP calls to OpenRouter + Instagram APIs
- `Pillow` — Image handling (saving Gemini-generated images)
- `moviepy` — Creates 15-second MP4 reels from image + music
- `instagrapi` — Instagram posting (unofficial API)

**Note:** No image compositing/fallback code. Gemini generates complete images with headlines, badges, watermarks, and styling already included.

> **System requirement for moviepy**: `ffmpeg` must be installed.
> - Windows: `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html)
> - Ubuntu/GitHub Actions: `sudo apt-get install ffmpeg`
> - macOS: `brew install ffmpeg`

---

## Step 3 — Add Background Music

Place one or more `.mp3` files inside `insta/assets/music/`.

The bot randomly picks one per post and loops/trims it to 15 seconds at 60% volume.

Recommended free sources:
- [pixabay.com/music](https://pixabay.com/music/) — filter by **Cinematic** or **News**
- [freemusicarchive.org](https://freemusicarchive.org/) — CC0 licensed tracks
- [mixkit.co/free-stock-music](https://mixkit.co/free-stock-music/) — free for social media

> If no music files are found, the bot creates a silent video.

---

## Step 4 — Configure Instagram Credentials (Option A — Personal/Creator Account)

> **IMPORTANT**: Your Instagram password is a secret credential. Never commit it to GitHub. Use GitHub Secrets (Step 7) to store it safely.

This section walks you through setting up Instagram posting using `instagrapi`, which works with Personal, Creator, and Business accounts.

---

### 4.0 — Prerequisites

Before starting, make sure you have:

- An **Instagram account** (Personal, Creator, or Business — all work)
- The **username** and **password** for that account
- **Two-factor authentication (2FA) disabled** on the account, OR access to the device/browser where you're already logged in

> **Best practice**: Create a dedicated Instagram account for the bot (e.g. `@YourNewsPage`) instead of using your personal account. This keeps your personal account safe and allows you to customize the bot's profile, bio, and branding.

---

### 4.1 — Create or Prepare Your Instagram Account

#### If you're creating a new account:

1. Open the Instagram app or go to [instagram.com](https://instagram.com)
2. Click **Sign up** and create a new account
3. Choose a username related to your news page (e.g. `breakingnews_daily`, `viral_news_hub`)
4. Complete the profile:
   - **Profile picture**: Use a logo or news-themed image
   - **Bio**: Describe your page (e.g. "🔥 Breaking news every 2 hours | Powered by AI 🤖")
   - **Website**: Add your website or a link aggregator (e.g. Linktree)

#### If you're using an existing account:

1. Make sure you know the **username** and **password**
2. If the account has 2FA enabled, you have two options:
   - **Option 1 (Recommended)**: Disable 2FA temporarily in Instagram Settings → Security → Two-Factor Authentication → Turn Off
   - **Option 2**: Log in from the same device/browser where you'll run the bot, so Instagram recognizes it as a trusted device

---

### 4.2 — Disable Two-Factor Authentication (Recommended)

The `instagrapi` library works best without 2FA. To disable it:

1. Open Instagram app → Profile → Menu (☰) → Settings
2. Go to **Security** → **Two-Factor Authentication**
3. If it's enabled, tap the method (SMS or Authenticator App) and choose **Turn Off**
4. Confirm by entering your password

> **Security note**: If you're concerned about security, you can re-enable 2FA after the bot successfully logs in and saves a session file. The bot will reuse the saved session and won't need to log in again unless the session expires.

---

### 4.3 — Get Your Instagram Username and Password

You need two pieces of information:

1. **Username**: Your Instagram handle (without the `@` symbol)
   - Example: If your profile is `instagram.com/breakingnews_daily`, your username is `breakingnews_daily`

2. **Password**: The password you use to log into Instagram
   - Make sure it's correct — test it by logging into Instagram on a browser first

---

### 4.4 — Set the Environment Variables

Once you have your username and password, set them as environment variables:

**Windows (PowerShell):**
```powershell
$env:INSTAGRAM_USERNAME = "your_instagram_handle"
$env:INSTAGRAM_PASSWORD = "your_instagram_password"
```

**Mac/Linux:**
```bash
export INSTAGRAM_USERNAME="your_instagram_handle"
export INSTAGRAM_PASSWORD="your_instagram_password"
```

**Example:**
```powershell
$env:INSTAGRAM_USERNAME = "breakingnews_daily"
$env:INSTAGRAM_PASSWORD = "MySecurePassword123!"
```

> **For local development**, you can also create a `.env` file in the `insta/` folder (never commit this file):
> ```
> INSTAGRAM_USERNAME=breakingnews_daily
> INSTAGRAM_PASSWORD=MySecurePassword123!
> OPENROUTER_API_KEY=sk-or-...
> ```
> Add `.env` to your `.gitignore` to prevent accidentally committing it.

---

### 4.5 — How Session Management Works

The first time the bot runs, it will:

1. Log into Instagram using your username and password
2. Save a **session file** at `insta/assets/session.json`
3. On subsequent runs, it will **reuse the session** instead of logging in again

This means:
- ✅ You only need to log in once
- ✅ Instagram is less likely to flag your account for suspicious activity
- ✅ The bot runs faster (no login delay)

> **If Instagram asks for a challenge** (e.g. "We detected unusual activity"), the bot will try to handle it automatically. If it fails, log into Instagram manually from the same device/browser, complete the challenge, then run the bot again.

---

### 4.6 — Test the Login Locally

Before automating with GitHub Actions, test the login locally:

```bash
cd insta
python main.py --dry-run
```

You should see:
```
[Instagram] Logging in as breakingnews_daily...
[Instagram] Login successful! Session saved to assets/session.json
[Instagram] Dry run mode — skipping actual post
```

If you see an error like:
- `[Instagram] Login failed: Bad password` → Double-check your password
- `[Instagram] Challenge required` → Log into Instagram manually from a browser on the same device, complete the challenge, then try again
- `[Instagram] Two-factor authentication required` → Disable 2FA (see Step 4.2)

---

### 4.7 — Optional: Switch to a Professional Account

If you want access to Instagram Insights (analytics), you can switch to a Creator or Business account:

1. Open Instagram app → Profile → Menu (☰) → Settings
2. Go to **Account** → **Switch to Professional Account**
3. Choose **Creator** (for influencers, artists, public figures) or **Business** (for brands, organizations)
4. Follow the prompts to complete the setup

> **Note**: This is optional. The bot works with Personal accounts too. Professional accounts just give you access to analytics and insights.

---

### Option B — Business Account via Meta Graph API (Alternative)

Use this if you prefer the official Meta Graph API (requires Instagram Business/Creator account + Facebook Page). This method is more complex but is officially supported by Meta.

> **Note**: Most users should use Option A above. Option B is only needed if you want to use the official API or if Option A doesn't work for your use case.

For detailed Option B setup, see the [Meta Graph API documentation](https://developers.facebook.com/docs/instagram-api/guides/content-publishing).

---

## Step 5 — Optional Configuration

```bash
# Watermark text shown in the top-right corner of every image
export INSTA_WATERMARK="@YourPageName"

# Number of articles to post per run (default: 1)
export INSTA_POST_COUNT="1"

# Set to "true" to run without actually posting to Instagram
export DRY_RUN="false"
```

---

## Step 6 — Test Locally

```bash
cd insta

# Full dry run — fetches news, generates image, builds caption, but does NOT post
python main.py --dry-run

# Post 1 article for real
python main.py

# Post top 2 articles
python main.py --count 2

# Post a specific article by index (0 = highest virality score)
python main.py --article-index 0
```

You'll find generated images and videos in `insta/output/` after each run.

---

## Step 7 — Set Up GitHub Actions (Automated Posting)

### 7.1 Push your code to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 7.2 Add GitHub Secrets

Go to: **GitHub Repo → Settings → Secrets and variables → Actions → New repository secret**

Add the following secrets:

| Secret Name | Value | When Needed |
|---|---|---|
| `OPENROUTER_API_KEY` | Your OpenRouter key | ✅ Always |
| `INSTAGRAM_USERNAME` | Instagram handle | ✅ Option A |
| `INSTAGRAM_PASSWORD` | Instagram password | ✅ Option A |
| `INSTAGRAM_ACCESS_TOKEN` | Meta Graph API token | ✅ Option B |
| `INSTAGRAM_ACCOUNT_ID` | IG Business Account ID | ✅ Option B |
| `IMGUR_CLIENT_ID` | Imgur API Client ID | Option B only |
| `INSTA_WATERMARK` | e.g. `@BreakingNewsHQ` | Optional |

### 7.3 The workflow file

The workflow is at `.github/workflows/insta_news_bot.yml`. It runs automatically at these times (IST):

| IST | UTC Cron |
|---|---|
| 06:00 AM | `30 0 * * *` |
| 08:00 AM | `30 2 * * *` |
| 10:00 AM | `30 4 * * *` |
| 12:00 PM | `30 6 * * *` |
| 02:00 PM | `30 8 * * *` |
| 04:00 PM | `30 10 * * *` |
| 06:00 PM | `30 12 * * *` |
| 08:00 PM | `30 14 * * *` |
| 10:00 PM | `30 16 * * *` |
| 11:30 PM | `0 18 * * *` |

### 7.4 Manual trigger

Go to **GitHub → Actions → Insta News Bot → Run workflow**

You can set:
- **dry_run**: `true` to test without posting
- **count**: how many articles to post (default `1`)

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `feedparser` not found | Run `pip install -r requirements.txt` |
| `[Gemini Image] No image found in response` | Check your `OPENROUTER_API_KEY` and that the model `google/gemini-2.0-flash-preview-image-generation` is available in your OpenRouter account |
| `[Gemini Text] API call failed` | Check key, or model name `google/gemini-2.5-pro-preview-03-25` — update if a newer preview is released |
| `[Reel] Video creation failed` | Install ffmpeg: `winget install ffmpeg` (Windows) / `brew install ffmpeg` (Mac) / `sudo apt install ffmpeg` (Linux) |
| `[Font] Download failed` | Check internet connection, or manually place `NotoSans-Bold.ttf` and `NotoSans-Regular.ttf` in `assets/fonts/` |
| Instagram login challenge / 2FA error | Disable 2FA on the bot account, or log in from a browser on the same machine first to verify the device |
| `[Instagram] No credentials configured` | Set `INSTAGRAM_USERNAME` + `INSTAGRAM_PASSWORD` env vars |
| All articles already posted | Delete or clear `assets/posted_log.json` to reset the tracker |
| GitHub Actions not triggering | Ensure the repo has the workflow file at `.github/workflows/insta_news_bot.yml` and that Actions are enabled in repo settings |
