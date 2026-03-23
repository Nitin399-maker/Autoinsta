"""
Instagram News Bot — All-in-one main.py
========================================
Pipeline:
  1. Fetch top viral news from RSS feeds (all categories)
  2. Rewrite news content via Gemini 2.5 Pro (OpenRouter) → clean English + emojis
  3. Generate a viral image via Gemini 2.0 Flash Preview Image Generation (OpenRouter)
     with the headline overlaid at the bottom using Pillow
  4. Add background music → create 15s MP4 reel (moviepy)
  5. Build Instagram caption with emojis + hashtags
  6. Post to Instagram (instagrapi or Meta Graph API)
  7. Track posted articles to avoid duplicates

Required env vars:
  OPENROUTER_API_KEY       — OpenRouter API key (https://openrouter.ai)
  INSTAGRAM_USERNAME       — Instagram handle  (for instagrapi)
  INSTAGRAM_PASSWORD       — Instagram password (for instagrapi)
  OR
  INSTAGRAM_ACCESS_TOKEN   — Meta Graph API long-lived token
  INSTAGRAM_ACCOUNT_ID     — Instagram Business Account ID

Optional env vars:
  INSTA_WATERMARK          — Watermark text on image  (default: @NewsFlash)
  INSTA_POST_COUNT         — How many articles to post per run (default: 1)
  DRY_RUN                  — Set to "true" to skip actual Instagram posting
  IMGUR_CLIENT_ID          — Imgur API key (for Graph API media hosting)

Usage:
  python main.py               # Post top viral article
  python main.py --dry-run     # Test without posting
  python main.py --count 3     # Post top 3 articles
"""

# ─── Standard library ────────────────────────────────────────────────────────
import os
import sys
import re
import html
import json
import time
import random
import hashlib
import textwrap
import argparse
import base64
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path

# ─── Third-party ─────────────────────────────────────────────────────────────
import requests
import feedparser
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

try:
    from moviepy.video.io.ImageSequenceClip import ImageSequenceClip
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    from moviepy.audio.AudioClip import concatenate_audioclips
    from moviepy.video.VideoClip import ImageClip
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False

try:
    from instagrapi import Client as InstaClient
    INSTAGRAPI_AVAILABLE = True
except ImportError:
    INSTAGRAPI_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE    = "https://llmfoundry.straivedemo.com/openrouter/v1"

# Model used for text rewriting (content polish + emojis)
TEXT_MODEL  = "google/gemini-2.5-pro"
# Model used for image generation
IMAGE_MODEL = "google/gemini-3-pro-image-preview"

WATERMARK      = os.environ.get("INSTA_WATERMARK", "@NewsFlash")
POST_COUNT     = int(os.environ.get("INSTA_POST_COUNT", "1"))
DRY_RUN        = os.environ.get("DRY_RUN", "false").lower() == "true"
REEL_DURATION  = 15  # seconds

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR  = os.path.join(BASE_DIR, "assets")
FONTS_DIR   = os.path.join(ASSETS_DIR, "fonts")
MUSIC_DIR   = os.path.join(ASSETS_DIR, "music")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")
POSTED_LOG  = os.path.join(ASSETS_DIR, "posted_log.json")
SESSION_FILE = os.path.join(ASSETS_DIR, "session.json")

for _d in [ASSETS_DIR, FONTS_DIR, MUSIC_DIR, OUTPUT_DIR]:
    os.makedirs(_d, exist_ok=True)

IMG_WIDTH  = 1080
IMG_HEIGHT = 1080

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — RSS FETCHING
# ═════════════════════════════════════════════════════════════════════════════

RSS_FEEDS = [
    # World / International
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.cnn.com/rss/edition_world.rss",
    "https://feeds.reuters.com/reuters/worldNews",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    # India
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://www.thehindu.com/feeder/default.rss",
    "https://indianexpress.com/feed/",
    "https://www.ndtv.com/rss/top-stories",
    # Politics
    "https://feeds.bbci.co.uk/news/politics/rss.xml",
    "https://rss.cnn.com/rss/edition_politics.rss",
    "https://feeds.reuters.com/Reuters/PoliticsNews",
    # Technology
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://rss.cnn.com/rss/edition_technology.rss",
    "https://feeds.feedburner.com/TechCrunch",
    # Science / Health
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://rss.cnn.com/rss/edition_health.rss",
    # Entertainment / Viral
    "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    "https://rss.cnn.com/rss/edition_entertainment.rss",
    # Business
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.reuters.com/reuters/businessNews",
    # Sports
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://rss.cnn.com/rss/edition_sport.rss",
]

# Broad viral keywords — covers all news types, not just conflict
VIRAL_KEYWORDS = [
    # Conflict / breaking
    "war", "attack", "fight", "battle", "conflict", "strike", "killed", "dead",
    "explosion", "protest", "riot", "breaking", "urgent", "crisis", "emergency",
    "controversial", "scandal", "shocking", "exposed", "leaked", "banned",
    "arrested", "charged", "accused", "corruption", "resign", "fired", "ousted",
    "nuclear", "missile", "bomb", "invasion", "coup", "revolution", "uprising",
    "violence", "clash", "terror", "threat", "danger", "warning", "alert",
    # Viral / trending
    "historic", "record", "first ever", "never before", "massive", "huge",
    "major", "devastating", "brutal", "outrage", "fury", "anger", "demands",
    "refuses", "defies", "challenges", "viral", "trending", "shocking",
    # Tech / science
    "breakthrough", "discovery", "launch", "ai", "robot", "space", "nasa",
    "billion", "trillion", "ipo", "ban", "hack", "leak", "breach",
    # Entertainment / sports
    "win", "champion", "title", "award", "dead", "star", "celebrity",
    "fired", "quit", "comeback", "record", "divorce", "arrest",
    # General impact
    "million", "billion", "world", "global", "nation", "government",
    "president", "minister", "court", "supreme", "election", "vote",
]


def _clean_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _score_virality(title, summary=""):
    combined = (title + " " + summary).lower()
    return sum(1 for kw in VIRAL_KEYWORDS if kw in combined)


def fetch_news(max_articles=15):
    """Fetch and rank top viral articles from all RSS feeds."""
    articles = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", feed_url)
            for entry in feed.entries[:6]:
                title   = _clean_html(entry.get("title", ""))
                summary = _clean_html(entry.get("summary", entry.get("description", "")))
                if not title:
                    continue
                articles.append({
                    "title":     title,
                    "summary":   summary[:1000],
                    "link":      entry.get("link", ""),
                    "source":    source,
                    "published": entry.get("published", entry.get("updated", "")),
                    "score":     _score_virality(title, summary),
                })
        except Exception as e:
            print(f"[RSS] Error fetching {feed_url}: {e}")

    articles.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate by title prefix
    seen, unique = [], []
    for a in articles:
        key = a["title"].lower()[:60]
        if key not in seen:
            seen.append(key)
            unique.append(a)
    return unique[:max_articles]


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — GEMINI TEXT REWRITE via OpenRouter
# ═════════════════════════════════════════════════════════════════════════════

def rewrite_news_content(article):
    """
    Call Gemini 2.5 Pro via OpenRouter to rewrite the news in clear,
    engaging English with emojis. Returns a dict:
      {
        "rewritten_summary": str,   # 3-5 sentence polished summary with emojis
        "caption":           str,   # Full Instagram caption with hashtags
        "image_prompt":      str,   # Detailed image generation prompt
      }
    """
    if not OPENROUTER_API_KEY:
        print("[Gemini Text] OPENROUTER_API_KEY not set. Cannot proceed.")
        return None

    title   = article["title"].replace('"', '\\"').replace('\n', ' ')
    summary = article.get("summary", "").replace('"', '\\"').replace('\n', ' ')
    source  = article.get("source", "").replace('"', '\\"')
    watermark = WATERMARK

    prompt = f"""You are a viral social media news writer for Instagram. 
Given this news article, produce a JSON response with exactly these 3 keys:

1. "rewritten_summary": Rewrite the news in 3-5 sentences. Use clear, simple English that anyone can understand. Add relevant emojis naturally throughout. Make it engaging and easy to read.

2. "caption": Write a full Instagram caption (max 2000 chars). Include:
   - An attention-grabbing opening line with emojis (e.g. BREAKING NEWS!)
   - The rewritten summary
   - A call-to-action (e.g. What do you think? Comment below!)
   - 12-15 relevant trending hashtags at the end

3. "image_prompt": Write a detailed prompt for an AI image generator to create a complete, ready-to-post Instagram news image (1080x1080px square). Start the prompt with Generate and return an image. Then describe:
   - Main photorealistic news scene with cinematic lighting, dark vignette, dramatic mood
   - A semi-transparent dark bar at the bottom (last 300px) with thin red accent line at top
   - The headline text in large bold white font (56pt) inside the bottom bar, wrapped to 2-3 lines. The headline is: {title}
   - Source label with the source name in smaller gray text below headline. The source is: {source.upper()}
   - Red BREAKING badge in top-left corner (white text on red rounded rectangle)
   - Watermark in top-right corner (white bold text with black shadow). The watermark text is: {watermark}
   - Professional news broadcast aesthetic, viral-worthy, Instagram-ready
   End with: IMPORTANT You must generate and return the actual image file not just a description.
   The image should be COMPLETE with all text and graphics included - no post-processing needed.

News article:
Title: {title}
Summary: {summary}
Source: {source}

Respond with ONLY valid JSON, no markdown, no extra text."""

    try:
        resp = requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  "https://github.com/insta-news-bot",
                "X-Title":       "Insta News Bot",
            },
            json={
                "model": TEXT_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        print("[Gemini Text] Content rewritten successfully.")
        return {
            "rewritten_summary": data.get("rewritten_summary", summary),
            "caption":           data.get("caption", ""),
            "image_prompt":      data.get("image_prompt", _default_image_prompt(article)),
        }
    except Exception as e:
        print(f"[Gemini Text] API call failed: {e}")
        return None





def _default_image_prompt(article):
    title = article["title"]
    source = article.get("source", "NEWS")
    watermark = WATERMARK
    return (
        f"Generate and return an image. Create a viral Instagram news post image (1080x1080px square format) with these elements:\n\n"
        f"MAIN IMAGE: Photorealistic, dramatic news photograph representing: {title}. "
        f"Cinematic lighting, high contrast, professional news photography style. "
        f"Dark moody atmosphere with strong focal point. Apply dark vignette edges. "
        f"Slightly darkened/desaturated for dramatic news effect.\n\n"
        f"BOTTOM SECTION (last 300px): Semi-transparent dark overlay bar (black with 80% opacity) "
        f"with a thin red accent line at the top edge. Inside this bar, display the headline text in "
        f"large bold white font (56pt): \"{title}\". Wrap text to 2-3 lines if needed. "
        f"Below the headline, show \"📡 {source.upper()}\" in smaller gray text (30pt).\n\n"
        f"TOP LEFT CORNER: Red rounded rectangle badge with white bold text \"BREAKING\" (34pt).\n\n"
        f"TOP RIGHT CORNER: White bold text watermark \"{watermark}\" (28pt) with subtle black shadow.\n\n"
        f"STYLE: Ultra high quality, 4K, sharp details, professional news broadcast aesthetic, "
        f"Instagram-ready, viral-worthy composition."
        f"IMPORTANT: You must generate and return the actual image file, not just a description."
    )


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — GEMINI IMAGE GENERATION via OpenRouter
# ═════════════════════════════════════════════════════════════════════════════

def generate_image_with_gemini(image_prompt):
    """
    Call Gemini 2.0 Flash Preview Image Generation via OpenRouter.
    Returns a PIL Image object, or None on failure.
    """
    if not OPENROUTER_API_KEY:
        print("[Gemini Image] OPENROUTER_API_KEY not set.")
        return None

    print(f"[Gemini Image] Generating image...")
    print(f"[Gemini Image] Prompt: {image_prompt[:120]}...")

    try:
        resp = requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  "https://github.com/insta-news-bot",
                "X-Title":       "Insta News Bot",
            },
            json={
                "model": IMAGE_MODEL,
                "messages": [{"role": "user", "content": image_prompt}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract image URL from all known response structures
        def _extract_image_url(msg):
            # Pattern 1: message.images[0].image_url.url  (primary Gemini via OpenRouter)
            images = msg.get("images")
            if images and isinstance(images, list) and images[0]:
                url = (images[0].get("image_url") or {}).get("url", "")
                if url:
                    return url

            content = msg.get("content", "")

            # Pattern 2: content is a data:image URI string
            if isinstance(content, str) and "data:image" in content:
                return content

            # Pattern 3: content is a list of multimodal parts
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    # image_url part
                    if part.get("type") == "image_url":
                        url = (part.get("image_url") or {}).get("url", "")
                        if url:
                            return url
                    # inline_data / image part (Gemini native)
                    if part.get("type") == "image" or "inline_data" in part:
                        inline = part.get("inline_data", part)
                        b64 = inline.get("data", "")
                        mime = inline.get("mime_type", "image/png")
                        if b64:
                            return f"data:{mime};base64,{b64}"

            return None

        def _url_to_image(url):
            if url.startswith("data:image"):
                b64 = url.split(",", 1)[1]
                raw = base64.b64decode(b64)
            elif url.startswith("http"):
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                raw = r.content
            else:
                return None
            img = Image.open(BytesIO(raw)).convert("RGB")
            img = img.resize((IMG_WIDTH, IMG_HEIGHT), Image.LANCZOS)
            return img

        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            image_url = _extract_image_url(msg)
            if image_url:
                img = _url_to_image(image_url)
                if img:
                    print("[Gemini Image] Image generated successfully.")
                    return img

        # Debug dump so we can see exactly what the API returned
        print(f"[Gemini Image] No image found in response.")
        if data.get("choices"):
            msg = data["choices"][0].get("message", {})
            print(f"[Gemini Image] Message keys: {list(msg.keys())}")
            content = msg.get("content", "")
            print(f"[Gemini Image] Content type: {type(content).__name__}, preview: {str(content)[:300]}")
            if msg.get("images"):
                print(f"[Gemini Image] images field: {str(msg['images'])[:300]}")
        return None

    except Exception as e:
        print(f"[Gemini Image] Generation failed: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — IMAGE SAVING
# ═════════════════════════════════════════════════════════════════════════════

def build_final_image(article, gemini_image, watermark=WATERMARK):
    """
    Save the Gemini-generated image directly (no compositing, no fallback).
    All visual elements (headline, badge, watermark, styling) are included in the AI-generated image.
    Returns: path to saved JPEG, or None if generation failed
    """
    if gemini_image is None:
        print("[Image] Gemini generation failed. No fallback available.")
        return None

    safe = "".join(c if c.isalnum() else "_" for c in article["title"][:30])
    out_path = os.path.join(OUTPUT_DIR, f"post_{safe}.jpg")
    gemini_image.convert("RGB").save(out_path, "JPEG", quality=95)
    print(f"[Image] Saved: {out_path}")
    return out_path


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — MUSIC + VIDEO (moviepy)
# ═════════════════════════════════════════════════════════════════════════════

def _get_music_track():
    supported = {".mp3", ".wav", ".ogg", ".m4a"}
    local = [str(p) for p in Path(MUSIC_DIR).iterdir() if p.suffix.lower() in supported]
    if local:
        track = random.choice(local)
        print(f"[Music] Using: {track}")
        return track
    print("[Music] No music files found in assets/music/. Creating silent video.")
    return None


def create_reel(image_path, duration=REEL_DURATION):
    """Create a 15s MP4 reel from image + music. Falls back to image if moviepy missing."""
    if not MOVIEPY_AVAILABLE:
        print("[Reel] moviepy not installed. Posting image.")
        return image_path

    base = os.path.splitext(os.path.basename(image_path))[0]
    out  = os.path.join(OUTPUT_DIR, f"{base}.mp4")
    music = _get_music_track()

    try:
        clip = ImageClip(image_path, duration=duration).set_fps(24)
        if music:
            audio = AudioFileClip(music)
            if audio.duration < duration:
                loops = int(duration / audio.duration) + 1
                audio = concatenate_audioclips([audio] * loops)
            audio = audio.subclip(0, duration).fl(lambda gf, t: gf(t) * 0.6, keep_duration=True)
            clip  = clip.set_audio(audio)
        clip.write_videofile(out, codec="libx264", audio_codec="aac", fps=24, logger=None)
        print(f"[Reel] Video saved: {out}")
        return out
    except Exception as e:
        print(f"[Reel] Video creation failed: {e}. Using image.")
        return image_path


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — INSTAGRAM POSTING
# ═════════════════════════════════════════════════════════════════════════════

def _instagrapi_post(media_path, caption):
    if not INSTAGRAPI_AVAILABLE:
        raise ImportError("instagrapi not installed.")
    username = os.environ.get("INSTAGRAM_USERNAME", "")
    password = os.environ.get("INSTAGRAM_PASSWORD", "")
    if not username or not password:
        raise ValueError("INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD not set.")

    cl = InstaClient()
    cl.delay_range = [3, 7]

    # GitHub Actions: decode session from env var if no local file exists
    session_b64 = os.environ.get("INSTAGRAM_SESSION_B64", "")
    if not os.path.exists(SESSION_FILE) and session_b64:
        try:
            session_data = base64.b64decode(session_b64).decode("utf-8")
            with open(SESSION_FILE, "w") as f:
                f.write(session_data)
            print("[Instagram] Session restored from INSTAGRAM_SESSION_B64.")
        except Exception as e:
            print(f"[Instagram] Failed to decode session from env var: {e}")

    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            print("[Instagram] Logged in via saved session.")
        except Exception as session_err:
            print(f"[Instagram] Session login failed ({session_err}), retrying fresh login...")
            cl = InstaClient()
            cl.delay_range = [3, 7]
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            print("[Instagram] Fresh login successful.")
    else:
        print("[Instagram] No session file. Performing fresh login...")
        time.sleep(3)
        cl.login(username, password)
        cl.dump_settings(SESSION_FILE)
        print("[Instagram] Login successful. Session saved.")

    if str(media_path).lower().endswith((".mp4", ".mov")):
        media = cl.clip_upload(str(media_path), caption=caption)
    else:
        media = cl.photo_upload(str(media_path), caption=caption)
    print(f"[Instagram] Posted via instagrapi. ID: {media.pk}")
    return media.pk


def _upload_to_imgur(file_path):
    cid = os.environ.get("IMGUR_CLIENT_ID", "")
    if not cid:
        return None
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                "https://api.imgur.com/3/image",
                headers={"Authorization": f"Client-ID {cid}"},
                files={"image": f.read()},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["data"]["link"]
    except Exception as e:
        print(f"[Imgur] Upload failed: {e}")
        return None


def _graph_api_post(media_path, caption):
    token      = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
    if not token or not account_id:
        raise ValueError("INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID not set.")

    media_url = _upload_to_imgur(media_path)
    if not media_url:
        raise RuntimeError("Could not get public media URL (set IMGUR_CLIENT_ID).")

    is_video = str(media_path).lower().endswith((".mp4", ".mov"))
    base = f"https://graph.facebook.com/v19.0/{account_id}"

    payload = {"caption": caption, "access_token": token}
    if is_video:
        payload.update({"media_type": "REELS", "video_url": media_url})
    else:
        payload["image_url"] = media_url

    r = requests.post(f"{base}/media", data=payload, timeout=30)
    r.raise_for_status()
    container_id = r.json().get("id")

    if is_video:
        for _ in range(12):
            time.sleep(10)
            s = requests.get(
                f"https://graph.facebook.com/v19.0/{container_id}",
                params={"fields": "status_code", "access_token": token}, timeout=15
            ).json().get("status_code", "")
            if s == "FINISHED":
                break
            if s == "ERROR":
                raise RuntimeError("Video processing failed.")

    pub = requests.post(f"{base}/media_publish",
                        data={"creation_id": container_id, "access_token": token},
                        timeout=30)
    pub.raise_for_status()
    media_id = pub.json().get("id")
    print(f"[Instagram] Posted via Graph API. ID: {media_id}")
    return media_id


def post_to_instagram(media_path, caption):
    """Post using instagrapi first, fall back to Graph API."""
    if INSTAGRAPI_AVAILABLE and os.environ.get("INSTAGRAM_USERNAME"):
        try:
            return _instagrapi_post(media_path, caption)
        except Exception as e:
            print(f"[Instagram] instagrapi failed: {e}")

    if os.environ.get("INSTAGRAM_ACCESS_TOKEN"):
        try:
            return _graph_api_post(media_path, caption)
        except Exception as e:
            print(f"[Instagram] Graph API failed: {e}")

    print("[Instagram] No credentials configured. Dry-run output:")
    print(f"  Media: {media_path}")
    print(f"  Caption:\n{caption[:300]}...")
    return None





# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — POSTED LOG
# ═════════════════════════════════════════════════════════════════════════════

def _load_log():
    if os.path.exists(POSTED_LOG):
        try:
            with open(POSTED_LOG, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_log(posted):
    with open(POSTED_LOG, "w") as f:
        json.dump(list(posted)[-500:], f)


def _article_hash(article):
    key = article.get("link", "") or article.get("title", "")
    return hashlib.md5(key.encode()).hexdigest()


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — PIPELINE ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════════════

def process_article(article, dry_run=False):
    """Full pipeline: rewrite → generate image → create reel → post."""
    title = article["title"]
    print(f"\n{'='*62}")
    print(f"  Processing: {title[:68]}")
    print(f"  Score: {article.get('score', 0)}  |  Source: {article.get('source', '?')}")
    print(f"{'='*62}")

    # Step 1 — Rewrite content + get image prompt + caption via Gemini text
    print("\n[1/5] Rewriting content with Gemini 2.5 Pro...")
    content = rewrite_news_content(article)
    if content is None:
        print("[Pipeline] Content rewriting failed. Skipping article.")
        return None
    article["rewritten_summary"] = content["rewritten_summary"]

    # Step 2 — Generate complete image with Gemini 2.0 Flash (includes all text/graphics)
    print("\n[2/5] Generating complete Instagram post image with Gemini 2.0 Flash...")
    print("[2/5] (Image will include headline, badge, watermark, and styling)")
    gemini_img = generate_image_with_gemini(content["image_prompt"])

    # Step 3 — Save the generated image (no post-processing needed)
    print("\n[3/5] Saving final image...")
    image_path = build_final_image(article, gemini_img, watermark=WATERMARK)
    if image_path is None:
        print("[Pipeline] Image generation failed. Skipping article.")
        return None

    # Step 4 — Create reel with music
    print("\n[4/5] Creating video reel with music...")
    media_path = create_reel(image_path)

    # Step 5 — Post to Instagram
    caption = content.get("caption", "")
    if not caption:
        print("[Pipeline] No caption generated. Skipping article.")
        return None
    print(f"\n[5/5] {'DRY RUN — skipping post' if dry_run else 'Posting to Instagram...'}")
    print(f"Caption preview:\n{caption[:300]}\n...")

    if dry_run:
        print(f"[DRY RUN] Media: {media_path}")
        return "DRY_RUN"

    return post_to_instagram(media_path, caption)


def run(count=1, dry_run=False, article_index=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'#'*62}")
    print(f"  INSTA NEWS BOT  —  {ts}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE POST'}")
    print(f"{'#'*62}\n")

    print("[Bot] Fetching news...")
    articles = fetch_news(max_articles=20)
    if not articles:
        print("[Bot] No articles fetched. Exiting.")
        return

    print(f"[Bot] {len(articles)} articles fetched (ranked by virality):")
    for i, a in enumerate(articles[:8]):
        print(f"  [{i}] score={a['score']:2d}  {a['title'][:70]}")

    posted = _load_log()
    fresh  = [a for a in articles if _article_hash(a) not in posted]
    print(f"\n[Bot] {len(fresh)} fresh articles (not yet posted).")

    if not fresh:
        print("[Bot] All top articles already posted today. Skipping.")
        return

    to_post = [fresh[article_index]] if (article_index is not None and article_index < len(fresh)) else fresh[:count]

    results = []
    for article in to_post:
        media_id = process_article(article, dry_run=dry_run)
        if media_id:
            results.append(article)
            posted.add(_article_hash(article))
            print(f"\n[Bot] ✓ Posted: {article['title'][:65]}")
        else:
            print(f"\n[Bot] ✗ Failed: {article['title'][:65]}")

    if not dry_run:
        _save_log(posted)

    print(f"\n[Bot] Done. {len(results)}/{len(to_post)} article(s) posted.")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram News Bot — all-in-one")
    parser.add_argument("--dry-run",       action="store_true", help="Skip actual Instagram posting")
    parser.add_argument("--count",         type=int, default=POST_COUNT, help="Articles to post (default 1)")
    parser.add_argument("--article-index", type=int, default=None,       help="Post specific article by index")
    args = parser.parse_args()

    run(
        count=args.count,
        dry_run=args.dry_run or DRY_RUN,
        article_index=args.article_index,
    )
