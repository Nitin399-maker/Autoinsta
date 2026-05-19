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
POST_COUNT     = int(os.environ.get("INSTA_POST_COUNT", "0"))   # 0 = one per category
DRY_RUN        = os.environ.get("DRY_RUN", "false").lower() == "true"
REEL_DURATION  = 15  # seconds

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR  = os.path.join(BASE_DIR, "assets")
FONTS_DIR   = os.path.join(ASSETS_DIR, "fonts")
MUSIC_DIR   = os.path.join(ASSETS_DIR, "music")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")
POSTED_LOG    = os.path.join(ASSETS_DIR, "posted_log.json")
DAILY_TRACKER = os.path.join(ASSETS_DIR, "daily_tracker.json")
SESSION_FILE  = os.path.join(ASSETS_DIR, "session.json")

for _d in [ASSETS_DIR, FONTS_DIR, MUSIC_DIR, OUTPUT_DIR]:
    os.makedirs(_d, exist_ok=True)

IMG_WIDTH  = 1080
IMG_HEIGHT = 1080

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — RSS FETCHING
# ═════════════════════════════════════════════════════════════════════════════

# The 10 required content categories (alternating between two sets)
# Odd days (1, 3, 5, ...): First 5 categories
# Even days (2, 4, 6, ...): Last 5 categories
ALL_CATEGORIES = [
    "politics",      # 1. Politics — government decisions, elections, policies, leaders, laws
    "economy",       # 2. Economy / Business — markets, companies, jobs, GDP, stocks
    "world",         # 3. World (International) — global events, wars, treaties, diplomacy
    "sports",        # 4. Sports — matches, tournaments, athletes
    "entertainment", # 5. Entertainment — movies, celebrities, OTT, music
    "technology",    # 6. Technology / Science — AI, gadgets, space, research
    "health",        # 7. Health — diseases, healthcare, medicine
    "environment",   # 8. Environment — climate change, pollution, disasters
    "crime",         # 9. Crime / Law — criminal cases, legal actions, justice system
    "lifestyle",     # 10. Lifestyle / Society — daily life, culture, education, trends
]

ODD_DAY_CATEGORIES = ALL_CATEGORIES[:5]   # First 5: politics, economy, world, sports, entertainment
EVEN_DAY_CATEGORIES = ALL_CATEGORIES[5:]  # Last 5: technology, health, environment, crime, lifestyle

def get_today_categories():
    """Return the 5 categories for today based on odd/even day."""
    day_of_month = datetime.now(timezone.utc).day
    if day_of_month % 2 == 1:  # Odd day
        return ODD_DAY_CATEGORIES
    else:  # Even day
        return EVEN_DAY_CATEGORIES

REQUIRED_CATEGORIES = get_today_categories()  # Dynamic based on current day

# Each entry is (category, url)  — at least 3 feeds per required category
RSS_FEEDS = [
    # ── 1. Politics ──────────────────────────────────────────────────────────
    ("politics",      "https://feeds.bbci.co.uk/news/politics/rss.xml"),
    ("politics",      "https://rss.cnn.com/rss/edition_politics.rss"),
    ("politics",      "https://feeds.reuters.com/Reuters/PoliticsNews"),
    ("politics",      "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("politics",      "https://www.ndtv.com/india-news/rss"),

    # ── 2. Economy / Business ────────────────────────────────────────────────
    ("economy",       "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("economy",       "https://feeds.reuters.com/reuters/businessNews"),
    ("economy",       "https://feeds.reuters.com/reuters/financialNews"),
    ("economy",       "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),

    # ── 3. World / International ─────────────────────────────────────────────
    ("world",         "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("world",         "https://rss.cnn.com/rss/edition_world.rss"),
    ("world",         "https://feeds.reuters.com/reuters/worldNews"),
    ("world",         "https://www.aljazeera.com/xml/rss/all.xml"),
    ("world",         "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),

    # ── 4. Sports ────────────────────────────────────────────────────────────
    ("sports",        "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("sports",        "https://rss.cnn.com/rss/edition_sport.rss"),
    ("sports",        "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
    ("sports",        "https://timesofindia.indiatimes.com/rss/4719161.cms"),

    # ── 5. Entertainment ─────────────────────────────────────────────────────
    ("entertainment", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
    ("entertainment", "https://rss.cnn.com/rss/edition_entertainment.rss"),
    ("entertainment", "https://variety.com/feed/"),
    ("entertainment", "https://timesofindia.indiatimes.com/rss/4719148.cms"),

    # ── 6. Technology / Science ──────────────────────────────────────────────
    ("technology",    "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("technology",    "https://rss.cnn.com/rss/edition_technology.rss"),
    ("technology",    "https://feeds.feedburner.com/TechCrunch"),
    ("technology",    "https://www.theverge.com/rss/index.xml"),

    # ── 7. Health ────────────────────────────────────────────────────────────
    ("health",        "https://feeds.bbci.co.uk/news/health/rss.xml"),
    ("health",        "https://rss.cnn.com/rss/edition_health.rss"),
    ("health",        "https://feeds.reuters.com/reuters/healthNews"),
    ("health",        "https://www.who.int/rss-feeds/news-english.xml"),

    # ── 8. Environment ───────────────────────────────────────────────────────
    ("environment",   "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("environment",   "https://www.theguardian.com/environment/rss"),
    ("environment",   "https://rss.nytimes.com/services/xml/rss/nyt/Climate.xml"),

    # ── 9. Crime / Law ───────────────────────────────────────────────────────
    ("crime",         "https://rss.nytimes.com/services/xml/rss/nyt/Crime.xml"),
    ("crime",         "https://rss.cnn.com/rss/edition_us.rss"),
    ("crime",         "https://feeds.reuters.com/reuters/domesticNews"),
    ("crime",         "https://feeds.bbci.co.uk/news/uk/rss.xml"),

    # ── 10. Lifestyle / Society ──────────────────────────────────────────────
    ("lifestyle",     "https://feeds.bbci.co.uk/news/education/rss.xml"),
    ("lifestyle",     "https://www.theguardian.com/society/rss"),
    ("lifestyle",     "https://rss.cnn.com/rss/cnn_living.rss"),
    ("lifestyle",     "https://timesofindia.indiatimes.com/rss/4719168.cms"),
]

# Words too common to be meaningful trend signals
_STOP_WORDS = {
    "this", "that", "with", "from", "have", "been", "will", "what",
    "when", "where", "which", "their", "there", "they", "than", "then",
    "after", "about", "into", "over", "more", "some", "also", "just",
    "says", "said", "were", "would", "could", "should", "very", "much",
    "people", "year", "years", "time", "week", "month", "days", "hours",
    "news", "post", "today", "back", "like", "make", "made", "come",
    "know", "want", "give", "take", "your", "being", "doing", "going",
    "new", "old", "big", "long", "high", "even", "only", "while",
}

# Minimal fallback used only when every live source fails
_FALLBACK_KEYWORDS = [
    "breaking", "crisis", "attack", "record", "first", "billion",
    "war", "election", "arrest", "launch", "viral", "shocking",
]

# Daily cache: {"date": "YYYY-MM-DD", "keywords": [...]}
_trending_cache: dict = {}


def fetch_trending_keywords() -> list:
    """
    Return today's trending keywords pulled from:
      1. Wikipedia trending pages (free REST API, no auth)
      2. Reddit r/worldnews + r/news + r/technology hot post titles

    Results are cached for the calendar day so the network is only hit once.
    Falls back to a minimal static list only if every source is unreachable.
    """
    from datetime import timedelta
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _trending_cache.get("date") == today:
        return _trending_cache["keywords"]

    keywords: set = set()

    # ── Source 1: Wikipedia Trending pages (free REST API, no auth) ─────────
    try:
        _headers = {"User-Agent": "AutoInstaNewsBot/2.0"}
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
        wiki_url = (
            f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
            f"en.wikipedia/all-access/{yesterday}"
        )
        resp = requests.get(wiki_url, headers=_headers, timeout=10)
        if resp.ok:
            for item in resp.json()["items"][0]["articles"][:60]:
                title = item["article"].replace("_", " ").lower()
                for word in re.findall(r"[a-zA-Z]{3,}", title):
                    keywords.add(word)
        print(f"[TRENDS] Wikipedia trending: {len(keywords)} keywords so far")
    except Exception as e:
        print(f"[TRENDS] Wikipedia trending unavailable: {e}")

    # ── Source 2: Reddit hot posts (public JSON, no auth needed) ─────────────
    try:
        _headers = {"User-Agent": "AutoInstaNewsBot/2.0"}
        for sub in ["worldnews", "news", "technology", "india",
                    "politics", "sports", "entertainment", "health",
                    "environment", "crime", "todayilearned"]:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=20",
                headers=_headers, timeout=8,
            )
            if resp.ok:
                for post in resp.json()["data"]["children"]:
                    title = post["data"]["title"].lower()
                    for word in re.findall(r"[a-zA-Z]{4,}", title):
                        keywords.add(word)
        print(f"[TRENDS] After Reddit: {len(keywords)} keywords total")
    except Exception as e:
        print(f"[TRENDS] Reddit unavailable: {e}")

    # ── Filter stop words ────────────────────────────────────────────────────
    keywords -= _STOP_WORDS

    result = list(keywords) if keywords else list(_FALLBACK_KEYWORDS)
    _trending_cache["date"] = today
    _trending_cache["keywords"] = result
    print(f"[TRENDS] Using {len(result)} live trending keywords for {today}")
    print("[TRENDS] Keywords: " + ", ".join(sorted(result)))
    return result


def _clean_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _score_virality(title, summary=""):
    combined = (title + " " + summary).lower()
    return sum(1 for kw in fetch_trending_keywords() if kw in combined)


def fetch_news(max_per_feed=8):
    """Fetch articles from all RSS feeds, tagged by category, deduped by title.

    Returns ALL fetched articles (sorted by virality score) so that
    pick_one_per_category / pick_diverse_articles can make the final selection.
    """
    articles = []
    for category, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", feed_url)
            for entry in feed.entries[:max_per_feed]:
                title   = _clean_html(entry.get("title", ""))
                summary = _clean_html(entry.get("summary", entry.get("description", "")))
                if not title:
                    continue
                articles.append({
                    "title":     title,
                    "summary":   summary,
                    "link":      entry.get("link", ""),
                    "source":    source,
                    "category":  category,
                    "published": entry.get("published", entry.get("updated", "")),
                    "score":     _score_virality(title, summary),
                })
        except Exception as e:
            print(f"[RSS] Error fetching {feed_url}: {e}")

    # Deduplicate by title prefix (keep first occurrence across all categories)
    seen, unique = [], []
    for a in articles:
        key = a["title"].lower()[:60]
        if key not in seen:
            seen.append(key)
            unique.append(a)

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique


def pick_diverse_articles(articles, posted, count=3):
    """
    Pick `count` fresh articles from different categories.
    Falls back to best-scoring fresh articles if not enough categories available.
    """
    fresh = [a for a in articles if _article_hash(a) not in posted]
    # One best article per category (already sorted by score)
    seen_cats, picked = set(), []
    for a in fresh:
        cat = a.get("category", "other")
        if cat not in seen_cats:
            seen_cats.add(cat)
            picked.append(a)
        if len(picked) == count:
            break
    # If we still need more (fewer categories than count), fill from remaining fresh
    if len(picked) < count:
        used_links = {a["link"] for a in picked}
        for a in fresh:
            if a["link"] not in used_links:
                picked.append(a)
                used_links.add(a["link"])
            if len(picked) == count:
                break
    return picked


def pick_one_per_category(articles, posted):
    """
    For each of the 10 required categories, pick the highest-scoring
    fresh article (not yet posted).  Falls back to the best available
    article in that category if no fresh ones remain.  Categories with
    zero articles are skipped with a warning.

    Articles must already be sorted by score descending (fetch_news does this).
    """
    # Group by category, preserving score order
    by_category: dict = {}
    for a in articles:
        cat = a.get("category", "other")
        by_category.setdefault(cat, []).append(a)

    # Each per-category list is already score-sorted; keep it that way
    # (articles were globally sorted, so insertion order = score order within cat)

    picked = []
    for cat in REQUIRED_CATEGORIES:
        cat_articles = by_category.get(cat, [])

        # Prefer a fresh (not yet posted) article
        fresh = [a for a in cat_articles if _article_hash(a) not in posted]
        if fresh:
            best = fresh[0]
            picked.append(best)
            print(f"[Category] ✓ {cat:15s}  score={best['score']:2d}  {best['title'][:55]}")
        elif cat_articles:
            # No fresh articles — re-use the best one anyway so every category
            # is always represented in the run
            best = cat_articles[0]
            picked.append(best)
            print(f"[Category] ~ {cat:15s}  score={best['score']:2d}  (no fresh — reusing)  {best['title'][:40]}")
        else:
            print(f"[Category] ✗ {cat:15s}  no articles found — skipping")

    return picked


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
Given this news article, produce a JSON response with exactly these 4 keys:

1. "rewritten_summary": Rewrite the news in 3-5 sentences. Use clear, simple English that anyone can understand. Add relevant emojis naturally throughout. Make it engaging and easy to read.

2. "viral_headline": Write ONE ultra-punchy, eye-catching headline (max 12 words) for this news story. It must:
   - Use power words that trigger curiosity, urgency, or emotion (e.g. SHOCKING, MASSIVE, JUST IN, EXPOSED)
   - Be written in TITLE CASE
   - NOT use clickbait or misleading language — must reflect the actual story
   - Be short enough to fit on 2 lines inside a news lower-third banner
   - Feel like a live breaking-news ticker headline

3. "caption": Write a full Instagram caption (max 2000 chars). Include:
   - An attention-grabbing opening line with emojis (e.g. BREAKING NEWS!)
   - The rewritten summary
   - A call-to-action (e.g. What do you think? Comment below!)
   - 12-15 relevant trending hashtags at the end

4. "image_prompt": Write a detailed prompt for an AI image generator to create a complete, ready-to-post Instagram news image (1080x1080px square). Start the prompt with: Generate and return an image. Then describe every element precisely:
   MAIN SCENE: Ultra-photorealistic, hyper-detailed news photograph representing the story. Shot with a 24mm lens at f/1.8, golden-hour or dramatic overcast lighting, shallow depth of field, natural motion blur on background elements. RAW photo quality — every texture, shadow, and highlight rendered at 8K resolution. Cinematic color grading (teal-orange LUT), dark vignette on all four edges. The scene must look indistinguishable from a real AFP/Reuters press photo. Use the full story context to choose the most visually dramatic scene: {summary}
   BOTTOM BAR (pixels 780–1080, full width): Solid semi-transparent black overlay (85% opacity). A 4px-thick bright red horizontal line runs along the very top edge of this bar. Inside the bar: viral headline in large bold white sans-serif font (56pt), word-wrapped to 2–3 lines, left-aligned with 40px left margin. The viral headline text to render is the viral_headline you generated above. Directly below the headline: "📡 {source.upper()}" in light gray (30pt).
   TOP-LEFT CORNER (anchored to 0,0): A bold red rounded-rectangle badge (padding 12px 24px, corner radius 8px) pinned flush to the top-left corner. Inside: white bold uppercase text "⚡ BREAKING NEWS" (32pt). Badge must have a 2px white inner border and a soft drop shadow.
   TOP-RIGHT CORNER (anchored to top-right edge): White bold text watermark "{watermark}" (28pt) with a 2px black outline and subtle drop shadow, flush to the top-right corner with 16px margin from edges.
   OVERALL STYLE: Ultra-realistic, 8K, zero artifacts, sharp foreground details, professional breaking-news broadcast aesthetic. The final image must look like a real live-news screenshot overlaid with native TV chyrons — completely Instagram-ready with no post-processing needed.
   End with: IMPORTANT: You must generate and return the actual image file, not a description. All text badges and overlays must be rendered directly onto the image at the specified corners.

News article:
Title: {title}
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
        viral_headline = data.get("viral_headline", title)
        # If LLM left a literal placeholder in the image_prompt, replace it with the actual headline
        raw_img_prompt = data.get("image_prompt", "")
        if raw_img_prompt:
            raw_img_prompt = raw_img_prompt.replace("viral_headline", viral_headline)
        image_prompt = raw_img_prompt if raw_img_prompt else _default_image_prompt(article, viral_headline)
        return {
            "rewritten_summary": data.get("rewritten_summary", summary),
            "viral_headline":    viral_headline,
            "caption":           data.get("caption", ""),
            "image_prompt":      image_prompt,
        }
    except Exception as e:
        print(f"[Gemini Text] API call failed: {e}")
        return None





def _default_image_prompt(article, viral_headline=None):
    title = article["title"]
    summary = article.get("summary", title)
    source = article.get("source", "NEWS")
    watermark = WATERMARK
    headline_text = viral_headline if viral_headline else title
    return (
        f"Generate and return an image. Create a viral Instagram news post image (1080x1080px square format) with these elements:\n\n"
        f"MAIN SCENE: Ultra-photorealistic, hyper-detailed news photograph. "
        f"Use the full story context below to choose the single most visually dramatic, emotionally charged scene: {summary}. "
        f"Shot with a 24mm lens at f/1.8, dramatic natural lighting (golden-hour or stormy overcast), "
        f"shallow depth of field with razor-sharp subject and naturally blurred background. "
        f"RAW photo quality at 8K resolution — every texture, skin pore, fabric fiber, and reflective surface rendered with absolute realism. "
        f"Cinematic teal-orange color grade, deep shadows, bright highlights. Dark vignette on all four edges. "
        f"The scene must be indistinguishable from a real AFP/Reuters wire photo.\n\n"
        f"BOTTOM BAR (rows 780–1080, full width): Semi-transparent black overlay (85% opacity). "
        f"A bold 4px bright-red horizontal line runs along the very top edge of this bar (full width). "
        f"Inside the bar: white bold sans-serif viral headline text (56pt), word-wrapped to 2–3 lines, "
        f"left-aligned with 40px left margin: \"{headline_text}\". "
        f"Directly below: \"📡 {source.upper()}\" in light gray (30pt).\n\n"
        f"TOP-LEFT CORNER (flush to 0,0 with 0px margin): Bold red rounded-rectangle badge "
        f"(corner radius 8px, inner padding 12px 24px, 2px white inner border, soft drop shadow). "
        f"Badge text: \"⚡ BREAKING NEWS\" in white bold uppercase (32pt). Must be pinned to the very top-left corner.\n\n"
        f"TOP-RIGHT CORNER (flush to top-right edge, 16px margin): "
        f"White bold watermark text \"{watermark}\" (28pt) with 2px black outline and drop shadow. "
        f"Must be pinned to the very top-right corner.\n\n"
        f"OVERALL STYLE: 8K ultra-realistic, zero compression artifacts, professional breaking-news broadcast aesthetic. "
        f"Looks like a real live TV news screenshot with native chyrons burned into the frame. "
        f"Instagram-ready, no post-processing needed.\n\n"
        f"IMPORTANT: You must generate and return the actual image file, not a description. "
        f"All text overlays and badges must be rendered directly onto the image at the exact specified corners."
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

# Path to persisted device fingerprint (kept across GitHub Actions runs via session)
DEVICE_FILE = os.path.join(ASSETS_DIR, "device.json")

# Realistic Android device profiles to mimic a real phone
_DEVICE_PROFILES = [
    {
        "app_version":        "269.0.0.18.75",
        "android_version":    31,
        "android_release":    "12",
        "dpi":                "480dpi",
        "resolution":         "1080x2400",
        "manufacturer":       "samsung",
        "device":             "SM-G991B",
        "model":              "SM-G991B",
        "cpu":                "exynos2100",
        "version_code":       "314665256",
    },
    {
        "app_version":        "269.0.0.18.75",
        "android_version":    30,
        "android_release":    "11",
        "dpi":                "420dpi",
        "resolution":         "1080x2340",
        "manufacturer":       "OnePlus",
        "device":             "OnePlus8T",
        "model":              "KB2005",
        "cpu":                "qcom",
        "version_code":       "314665256",
    },
    {
        "app_version":        "269.0.0.18.75",
        "android_version":    33,
        "android_release":    "13",
        "dpi":                "560dpi",
        "resolution":         "1440x3088",
        "manufacturer":       "samsung",
        "device":             "SM-S908B",
        "model":              "SM-S908B",
        "cpu":                "exynos2200",
        "version_code":       "314665256",
    },
]


def _human_sleep(min_sec, max_sec):
    """Sleep for a random duration between min_sec and max_sec."""
    t = random.uniform(min_sec, max_sec)
    print(f"[Human] Pausing {t:.1f}s...")
    time.sleep(t)


def _build_insta_client():
    """
    Build an instagrapi Client with a consistent device fingerprint.
    The fingerprint is persisted in device.json so every run looks
    like the same physical phone.
    """
    cl = InstaClient()
    # Slow, human-like request pacing
    cl.delay_range = [4, 12]

    if os.path.exists(DEVICE_FILE):
        # Reuse the same device identity across all runs
        with open(DEVICE_FILE, "r") as f:
            device = json.load(f)
        print("[Instagram] Loaded persisted device fingerprint.")
    else:
        # First run: pick a random profile and persist it forever
        device = random.choice(_DEVICE_PROFILES)
        with open(DEVICE_FILE, "w") as f:
            json.dump(device, f)
        print(f"[Instagram] Created new device fingerprint: {device['device']}")

    cl.set_device(device)
    return cl


def _human_warmup(cl):
    """
    Simulate brief human browsing before posting:
    view own profile info + peek at timeline.
    This mimics what a real user does before uploading.
    """
    try:
        _human_sleep(3, 8)
        cl.get_timeline_feed()          # scroll home feed
        _human_sleep(5, 14)
        cl.user_info(cl.user_id)        # view own profile
        _human_sleep(4, 9)
        print("[Human] Warm-up browsing complete.")
    except Exception as e:
        print(f"[Human] Warm-up skipped ({e}).")


def _instagrapi_post(media_path, caption):
    if not INSTAGRAPI_AVAILABLE:
        raise ImportError("instagrapi not installed.")
    username = os.environ.get("INSTAGRAM_USERNAME", "")
    password = os.environ.get("INSTAGRAM_PASSWORD", "")
    if not username or not password:
        raise ValueError("INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD not set.")

    cl = _build_insta_client()

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
            _human_sleep(2, 6)          # realistic pause before login request
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            print("[Instagram] Logged in via saved session.")
        except Exception as session_err:
            print(f"[Instagram] Session login failed ({session_err}), retrying fresh login...")
            cl = _build_insta_client()
            _human_sleep(8, 20)         # longer cooldown before fresh login
            cl.login(username, password)
            cl.dump_settings(SESSION_FILE)
            print("[Instagram] Fresh login successful.")
    else:
        print("[Instagram] No session file. Performing fresh login...")
        _human_sleep(5, 15)
        cl.login(username, password)
        cl.dump_settings(SESSION_FILE)
        print("[Instagram] Login successful. Session saved.")

    # Warm-up browsing — act like a real user before uploading
    _human_warmup(cl)

    # Final pause before the actual upload — mimics user composing/reviewing post
    _human_sleep(10, 30)

    if str(media_path).lower().endswith((".mp4", ".mov")):
        media = cl.clip_upload(str(media_path), caption=caption)
    else:
        media = cl.photo_upload(str(media_path), caption=caption)

    print(f"[Instagram] Posted via instagrapi. ID: {media.pk}")
    # Brief cool-down after posting
    _human_sleep(5, 12)
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


# ── Daily category tracker ────────────────────────────────────────────────────
# Tracks which categories have already been posted today so each hourly
# GitHub Actions run can pick the NEXT unposted category automatically.

def _load_daily_tracker():
    """Return list of categories already posted today (UTC date)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if os.path.exists(DAILY_TRACKER):
        try:
            with open(DAILY_TRACKER, "r") as f:
                data = json.load(f)
            if data.get("date") == today:
                return list(data.get("posted_categories", []))
        except Exception:
            pass
    return []


def _save_daily_tracker(categories_done_today):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(DAILY_TRACKER, "w") as f:
        json.dump({"date": today, "posted_categories": categories_done_today}, f, indent=2)


def pick_next_category_article(articles, posted, posted_today_categories):
    """
    Find the next required category not yet posted today and return the
    highest-scoring fresh article for it.

    Returns (category_name, article_dict) or (None, None) if all 10
    categories have already been covered today.
    """
    remaining = [c for c in REQUIRED_CATEGORIES if c not in posted_today_categories]
    if not remaining:
        return None, None

    by_category: dict = {}
    for a in articles:
        by_category.setdefault(a.get("category", "other"), []).append(a)

    for cat in remaining:
        cat_articles = by_category.get(cat, [])
        # Prefer fresh (not yet posted across all time) articles
        fresh = [a for a in cat_articles if _article_hash(a) not in posted]
        if fresh:
            return cat, fresh[0]
        elif cat_articles:
            # Category exists but all articles already posted — reuse best
            return cat, cat_articles[0]

    return None, None


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


def run(count=0, dry_run=False, article_index=None, all_today=False):
    """
    Posting modes (in priority order):
      --article-index N  → post one specific article by its fetched index
      --all-today        → post ALL remaining categories for today, ~1 hr apart
                           (local use; GitHub Actions uses hourly cron instead)
      --count N (N>0)    → legacy: post N diverse articles
      default (count=0)  → post ONE article — the next unposted-today category
                           (this is what every hourly GitHub Actions run calls)
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'#'*62}")
    print(f"  INSTA NEWS BOT  —  {ts}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE POST'}")
    if all_today:
        mode_label = "all remaining categories today (~1 hr gaps)"
    elif count and count > 0:
        mode_label = f"{count} diverse articles"
    else:
        mode_label = "next unposted-today category (1 post)"
    print(f"  Post strategy: {mode_label}")
    print(f"{'#'*62}\n")

    print("[Bot] Fetching news from all categories...")
    articles = fetch_news()
    if not articles:
        print("[Bot] No articles fetched. Exiting.")
        return

    print(f"[Bot] {len(articles)} articles fetched (ranked by virality score):")
    for i, a in enumerate(articles[:12]):
        print(f"  [{i:2d}] score={a['score']:2d}  [{a.get('category','?'):15s}]  {a['title'][:55]}")

    posted        = _load_log()
    posted_today  = _load_daily_tracker()
    
    # Get today's active categories (odd/even day split)
    today_categories = get_today_categories()
    day_type = "ODD" if datetime.now(timezone.utc).day % 2 == 1 else "EVEN"
    print(f"\n[Bot] Day type: {day_type} (categories: {', '.join(today_categories)})")
    print(f"[Bot] Categories posted today so far: "
          f"{posted_today if posted_today else 'none'}")
    remaining_today = [c for c in today_categories if c not in posted_today]
    print(f"[Bot] Remaining today: {remaining_today}\n")

    # ── Build the list of articles to post ───────────────────────────────────
    if article_index is not None:
        fresh    = [a for a in articles if _article_hash(a) not in posted]
        to_post  = [fresh[article_index]] if article_index < len(fresh) else []

    elif all_today:
        # Post every remaining category for today, ~1 hr gap between each
        to_post = []
        by_cat: dict = {}
        for a in articles:
            by_cat.setdefault(a.get("category", "other"), []).append(a)
        for cat in remaining_today:
            cat_arts = by_cat.get(cat, [])
            fresh    = [a for a in cat_arts if _article_hash(a) not in posted]
            if fresh:
                to_post.append(fresh[0])
            elif cat_arts:
                to_post.append(cat_arts[0])
        if not to_post:
            print("[Bot] All categories already covered today. Nothing to post.")
            return

    elif count and count > 0:
        to_post = pick_diverse_articles(articles, posted, count=count)

    else:
        # Default: one post — next unposted-today category
        cat, article = pick_next_category_article(articles, posted, posted_today)
        if article is None:
            print("[Bot] All 10 categories already posted today. Nothing to do.")
            return
        print(f"[Bot] Next category: {cat}  →  {article['title'][:65]}")
        to_post = [article]

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n[Bot] {len(to_post)} article(s) queued:")
    for a in to_post:
        print(f"  [{a.get('category','?'):15s}]  score={a.get('score',0):2d}  {a['title'][:55]}")

    # ── Post loop ─────────────────────────────────────────────────────────────
    results = []
    for idx, article in enumerate(to_post):
        # For --all-today: wait ~1 hour (±15 min random) between posts
        if idx > 0 and not dry_run:
            gap = random.uniform(45 * 60, 75 * 60)
            print(f"\n[Bot] Waiting {gap/60:.1f} min before next post (~1 hr pacing)...")
            time.sleep(gap)

        media_id = process_article(article, dry_run=dry_run)
        if media_id:
            results.append(article)
            posted.add(_article_hash(article))
            posted_today.append(article.get("category", "other"))
            if not dry_run:
                _save_log(posted)
                _save_daily_tracker(posted_today)
            cat_label = article.get("category", "?")
            print(f"\n[Bot] ✓ Posted [{cat_label}]: {article['title'][:60]}")
        else:
            print(f"\n[Bot] ✗ Failed: {article['title'][:65]}")

    if not dry_run:
        _save_log(posted)
        _save_daily_tracker(posted_today)

    today_categories = get_today_categories()
    covered = len([c for c in posted_today if c in today_categories])
    total   = len(today_categories)
    print(f"\n[Bot] Done. {len(results)}/{len(to_post)} posted. "
          f"Today's progress: {covered}/{total} categories covered.")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram News Bot — all-in-one")
    parser.add_argument("--dry-run",
                        action="store_true",
                        help="Skip actual Instagram posting")
    parser.add_argument("--count",
                        type=int, default=POST_COUNT,
                        help="Post N articles (diverse). 0 = next-category mode (default).")
    parser.add_argument("--all-today",
                        action="store_true",
                        help="Post all remaining categories for today with ~1 hr gaps "
                             "(for local use; GitHub Actions uses hourly cron instead)")
    parser.add_argument("--article-index",
                        type=int, default=None,
                        help="Post a specific article by its fetched index")
    args = parser.parse_args()

    run(
        count=args.count,
        dry_run=args.dry_run or DRY_RUN,
        article_index=args.article_index,
        all_today=args.all_today,
    )
