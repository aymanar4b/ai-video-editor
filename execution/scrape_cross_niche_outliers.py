#!/usr/bin/env python3
"""
Scrape YouTube for cross-niche business outliers with transferable content patterns.
Legacy version using yt-dlp (free but slower and prone to rate limiting).

For the recommended TubeLab API version, see scrape_cross_niche_tubelab.py.

Features:
- Monitors 49 channels across 8 niches
- Searches 16 cross-niche keywords
- Calculates outlier scores with recency boost
- Cross-niche filtering with comprehensive exclusions
- Title variant generation via Claude
- Transcript fetching with Apify fallback
- Output to Google Sheets

Usage:
    # Default: 90 days, ~20 outliers
    python execution/scrape_cross_niche_outliers.py

    # Fast test (skip transcripts)
    python execution/scrape_cross_niche_outliers.py --skip_transcripts

    # Keywords only (no channel monitoring)
    python execution/scrape_cross_niche_outliers.py --keywords_only
"""

import os
import sys
import json
import time
import datetime
import subprocess
import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from anthropic import Anthropic
import gspread
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

load_dotenv()

# Cross-Niche Keywords
CROSS_NICHE_KEYWORDS = [
    "how to scale a business",
    "business growth strategies",
    "increase business revenue",
    "gym launch strategy",
    "acquisition.com",
    "how to sell more",
    "closing sales techniques",
    "marketing funnel strategy",
    "lead generation tips",
    "how to make your first million",
    "millionaire business advice",
    "building wealth through business",
    "cash flow strategies",
    "entrepreneur mindset for success",
    "business systems automation",
    "scaling without burnout",
    "productivity for founders"
]

# =============================================================================
# CHANNEL LIST - Multi-Niche (49 channels across 8 niches)
# =============================================================================

MONITORED_CHANNELS = {
    # BUSINESS STRATEGY
    "UCMrnHNmYzP3LgvKzyq0ILgw": "Alex Hormozi",
    "UC3yRaQ9qZczN2M5C3kQZlaQ": "Leila Hormozi",
    "UCwgz-59Z39I8-ZrrHjy6nKw": "My First Million",
    "UCJustJoeTalks": "Codie Sanchez",
    "UCIgRClj26EZAKkamv1kzTdA": "Noah Kagan",
    "UCGy6QE39swWGy-Yb1lMZ_tA": "Greg Isenberg",
    "UC35LCBb7eVc9FXgwDKgBz2Q": "Dan Martell",
    "UCeqFD1zGwf7_LnrP6ANPlBw": "Patrick Bet-David",

    # PRODUCTIVITY & SYSTEMS
    "UCoOae5nYA7VqaXzerajD0lg": "Ali Abdaal",
    "UCG-KntY7aVnIGXYEBQvmBAQ": "Thomas Frank",
    "UCJ24N4O0bP7LGLBDvye7oCA": "Matt D'Avella",
    "UCIaH-gZIVC432YRjNVvnyCA": "Tiago Forte",
    "UC4xKdmAXFh4ACyhpiQ_3qBg": "Cal Newport",
    "UCfbGTpcJyEOMwKP-eYz3_fg": "August Bradley",

    # ACADEMIC & SCIENCE
    "UCHnyfMqiRRG1u-2MsSQLbXA": "Veritasium",
    "UCYO_jab_esuFRV4b17AJtAw": "3Blue1Brown",
    "UCsXVk37bltHxD1rDPwtNM8Q": "Kurzgesagt",
    "UCBcRF18a7Qf58cCRy5xuWwQ": "ASAP Science",
    "UC9-y-6csu5WGm29I7JiwpnA": "Computerphile",
    "UCZYTClx2T1of7BRZ86-8fow": "Scishow",
    "UCsooa4yRKGN_zEE8iknghZA": "TED-Ed",

    # BUSINESS STORYTELLING & DOCUMENTARY
    "UCqnbDFdCpuN8CMEg0VuEBqA": "Johnny Harris",
    "UCmyxyR7qlShxU0KXJGPE7aw": "Wendover Productions",
    "UCVHFbqXqoYvEWM1Ddxl0QKg": "Polymatter",
    "UCe0DNp0mKMqrYVaTundyr9w": "Economics Explained",
    "UCy-uo0eOdfnKBSjYwNaPjuw": "ColdFusion",
    "UC2C_jShtL725hvbm1arSV9w": "CGP Grey",
    "UCHdos0HAIEhIMqUc9L3Kb1Q": "Half as Interesting",

    # CREATOR ECONOMY & YOUTUBE STRATEGY
    "UCWsV__V0nANOeXa1bWgN3Xw": "Colin and Samir",
    "UC1dGTEzZFD0GXe9dEMJSblA": "Paddy Galloway",
    "UCqtL6ynOaJJ5j7S-4w7c1Fw": "Film Booth",
    "UCY1TadMVNLcdoKsDej2FHVA": "Jenny Hoyos",

    # FINANCE & INVESTING
    "UCV6KDgJskWaEckne5aPA0aQ": "Graham Stephan",
    "UCGy7SkBjcIAgTiwkXEtPnYg": "Andrei Jikh",
    "UCMtI88Kqc0RwSaLQxDMKCzA": "Mark Tilbury",
    "UCFCEuCsyWP0YkP3CZ3Mr01Q": "The Plain Bagel",
    "UCnMn36GT_H0X-w5_ckLtlgQ": "Minority Mindset",

    # SELF-IMPROVEMENT
    "UCGq7ov9-Xk9fkeQjeeXElkQ": "Chris Williamson",
    "UC2D2CMWXMOVWx7giW1n3LIg": "Huberman Lab",
    "UCvOreA_lxS92xVG-fE7fKtg": "Hamza",
    "UC-lHJZR3Gqxm24_Vd_AJ5Yw": "PewDiePie",
    "UCnQC_G5Xsjhp9fEJKuIcrSw": "Ben Shapiro",

    # WRITING & COMMUNICATION
    "UC9_p50tH3WmMslWRWKnM7dQ": "Simon Sinek",
    "UCAuUUnT6oDeKwE6v1NGQxug": "TED",
    "UCamLstJyCa-t5gfZegxsFMw": "Chris Do",

    # PHILOSOPHY & THINKING
    "UCfQgsKhHjSyRLOp9mnffqVg": "Pursuit of Wonder",
    "UCWOA1ZGywLbqmigxE4Qlvuw": "Academy of Ideas",
    "UC22BuJwmooPJLsRyDe9-cuw": "Einzelganger",
}

# =============================================================================
# EXCLUSION FILTERS
# =============================================================================

OWN_NICHE_TERMS = [
    "ai", "a.i.", "a.i", " ai ", "artificial intelligence",
    "gpt", "chatgpt", "chat gpt", "claude", "llm", "gemini",
    "machine learning", "neural network", "deep learning", "openai", "anthropic",
    "midjourney", "stable diffusion", "dall-e", "copilot",
    "automation", "automate", "automated", "n8n", "make.com", "zapier", "workflow",
    "integromat", "power automate", "ifttt", "airtable automation",
    "agent", "agentic", "langchain", "langgraph", "crewai", "autogen", "autogpt",
    "babyagi", "superagi", "agent gpt", "ai agent",
    "code", "coding", "programming", "programmer", "developer", "python", "javascript",
    "typescript", "api", "sdk", "github", "open source", "repository", "deploy",
    "docker", "kubernetes", "aws", "serverless", "backend", "frontend", "full stack",
    "cursor", "replit", "vs code", "vscode", "terminal", "command line", "cli",
    "notion ai", "obsidian", "roam research",
]

EXCLUDE_FORMATS = [
    "setup", "desk setup", "tour", "room tour", "office tour", "studio tour",
    "carry", "every day carry", "edc", "what's in my bag",
    "buying guide", "review", "unboxing", "hands on", "first look",
    "best laptop", "best phone", "best camera", "best mic", "best keyboard",
    "vs", "comparison", "compared", "which is better", "versus",
    "upgrade", "upgraded my", "new setup",
    "challenge", "challenged", "survive", "survived", "surviving",
    "win $", "won $", "winning", "prize", "giveaway",
    "battle", "competition", "race", "contest",
    "prank", "pranked", "pranking",
    "react", "reacts", "reacting", "reaction",
    "roast", "roasted", "roasting",
    "exposed", "exposing", "drama", "beef", "cancelled",
    "day in my life", "day in the life", "a day with",
    "morning routine", "night routine", "evening routine", "my routine",
    "what i eat", "what i ate", "full day of eating", "diet",
    "get ready with me", "grwm", "outfit", "fashion haul", "try on",
    "room makeover", "apartment tour", "house tour", "home tour",
    "travel vlog", "vacation", "trip to", "visiting",
    "wedding", "birthday", "anniversary", "holiday",
    "workout", "gym routine", "fitness routine", "exercise",
    "q&a", "ama", "ask me anything", "answering your questions",
    "reading comments", "responding to", "replying to",
    "shorts", "short", "#shorts", "tiktok", "reel",
    "clip", "clips", "highlight", "highlights", "compilation", "best of",
    "podcast ep", "full episode", "full interview",
    "live stream", "livestream", "streaming",
    "behind the scenes", "bts", "how we made",
    "bloopers", "outtakes", "deleted scenes",
    "breaking", "just announced", "breaking news",
    "news", "update", "updates", "announcement",
    "what happened", "drama explained",
    "election", "vote", "political", "trump", "biden", "congress",
    "israel", "palestine", "ukraine", "russia", "iran", "china",
    "inflation", "recession", "fed", "federal reserve",
    "crypto", "bitcoin", "ethereum", "cryptocurrency",
    "stock market", "stocks", "economy news",
    "immigration", "border", "deport",
    "youtube algorithm", "youtube update", "monetization",
    "subscriber", "subscribers", "sub count", "hitting",
    "play button", "silver play", "gold play",
    "channel update", "channel news",
    "tutorial", "how to edit", "editing tutorial",
    "photoshop", "premiere", "final cut", "davinci",
    "canva tutorial", "figma tutorial",
    "music video", "official video", "official audio", "lyric video",
    "cover", "remix", "mashup", "acoustic",
    "ft.", "feat.", "featuring",
    "album", "ep release", "single",
    "gameplay", "playthrough", "walkthrough", "let's play",
    "minecraft", "fortnite", "valorant", "league", "apex",
    "gaming", "gamer", "twitch", "esports",
    "recipe", "cooking", "baking", "how to cook", "how to make",
    "mukbang", "eating", "food review", "restaurant",
    "asmr", "relaxing", "sleep", "meditation", "ambient",
    "white noise", "rain sounds", "study music",
    "dating", "relationship", "boyfriend", "girlfriend", "marriage",
    "breakup", "ex", "crush", "love life",
    "storytime", "story time", "confession",
    "haul", "shopping haul", "favorites",
    "empties", "monthly favorites",
    "tier list", "ranking every",
]

TECHNICAL_TERMS = [
    "API", "Python", "code", "SDK", "framework", "JavaScript",
    "LangGraph", "CrewAI", "n8n", "Zapier", "Make.com", "GitHub",
    "programming", "developer", "coding", "script", "database",
    "server", "cloud", "saas", "software"
]

# Positive scoring hooks
MONEY_HOOKS = [
    "$", "revenue", "income", "profit", "money", "earn", "cash", "wealthy",
    "million", "millionaire", "billionaire", "rich", "wealth", "net worth",
    "salary", "raise", "pricing", "charge more", "high ticket", "premium"
]

TIME_HOOKS = [
    "faster", "save time", "productivity", "efficient", "quick", "speed",
    "in minutes", "in seconds", "instantly", "overnight", "shortcut",
    "hack", "hacks", "cheat code", "fast track", "accelerate"
]

CURIOSITY_HOOKS = [
    "?", "secret", "secrets", "nobody", "no one tells you", "they don't want",
    "this changed", "changed everything", "game changer", "mind blown",
    "shocking", "surprised", "unexpected", "plot twist",
    "never", "always", "stop", "don't", "quit", "avoid",
    "truth about", "real reason", "actually", "really",
    "hidden", "underground", "insider", "exclusive"
]

TRANSFORMATION_HOOKS = [
    "before", "after", "transformed", "transformation",
    "from zero", "from nothing", "started with",
    "how i went", "how i built", "journey",
    "changed my life", "life changing", "breakthrough"
]

CONTRARIAN_HOOKS = [
    "wrong", "mistake", "mistakes", "myth", "myths", "lie", "lies",
    "overrated", "underrated", "unpopular opinion", "controversial",
    "why i stopped", "why i quit", "the problem with",
    "nobody talks about", "uncomfortable truth"
]

URGENCY_HOOKS = [
    "before it's too late", "while you still can", "last chance",
    "now or never", "running out", "limited", "ending soon",
    "don't miss", "must watch", "need to know"
]

MAX_VIDEOS_PER_KEYWORD = 50
MAX_VIDEOS_PER_CHANNEL = 15
DAYS_BACK = 90
MIN_OUTLIER_SCORE = 1.1
MIN_VIDEO_DURATION_SECONDS = 180
MIN_VIEW_COUNT = 1000

USER_CHANNEL_NICHE = "AI agents, automation, LangGraph, CrewAI, agentic workflows"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def get_credentials():
    """Load Google credentials."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds:
        service_account_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        if os.path.exists(service_account_file):
            with open(service_account_file, 'r') as f:
                content = json.load(f)
            if "type" in content and content["type"] == "service_account":
                creds = ServiceAccountCredentials.from_service_account_file(service_account_file, scopes=SCOPES)
            elif "installed" in content or "web" in content:
                flow = InstalledAppFlow.from_client_secrets_file(service_account_file, SCOPES)
                creds = flow.run_local_server(port=0)
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())
    return creds


def run_ytdlp(command):
    """Run yt-dlp command and return JSON output."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
        items = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return items
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"    yt-dlp error: {str(e)[:100]}")
        return []


def calculate_cross_niche_score(title, base_outlier_score):
    """Calculate cross-niche potential score. Returns 0 for hard-excluded content."""
    title_lower = title.lower()
    score = base_outlier_score

    if any(term in title_lower for term in OWN_NICHE_TERMS):
        return 0

    if any(fmt in title_lower for fmt in EXCLUDE_FORMATS):
        score *= 0.3

    tech_count = sum(1 for term in TECHNICAL_TERMS if term.lower() in title_lower)
    score *= max(0.2, 1.0 - (tech_count * 0.2))

    if any(hook in title_lower for hook in MONEY_HOOKS):
        score *= 1.4
    if any(hook in title_lower for hook in CURIOSITY_HOOKS):
        score *= 1.3
    if any(hook in title_lower for hook in TRANSFORMATION_HOOKS):
        score *= 1.25
    if any(hook in title_lower for hook in CONTRARIAN_HOOKS):
        score *= 1.25
    if any(hook in title_lower for hook in TIME_HOOKS):
        score *= 1.2
    if any(hook in title_lower for hook in URGENCY_HOOKS):
        score *= 1.15
    if re.search(r'\b\d+\b', title):
        score *= 1.1

    return round(score, 2)


def scrape_keyword(keyword):
    """Scrape a single keyword using yt-dlp."""
    print(f"  - Searching: {keyword}")
    cmd = [
        "yt-dlp",
        f"ytsearch{MAX_VIDEOS_PER_KEYWORD}:{keyword}",
        "--dump-json",
        "--no-playlist",
        "--skip-download",
        "--no-warnings"
    ]

    items = run_ytdlp(cmd)
    videos = []
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=DAYS_BACK)).strftime("%Y%m%d")

    for item in items:
        upload_date = item.get("upload_date")
        if not upload_date or upload_date < cutoff_date:
            continue

        video_id = item.get("id")
        youtube_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else item.get("webpage_url")
        duration = item.get("duration", 0)
        view_count = item.get("view_count", 0)

        if duration < MIN_VIDEO_DURATION_SECONDS or view_count < MIN_VIEW_COUNT:
            continue

        video_data = {
            "title": item.get("title"),
            "url": youtube_url,
            "view_count": view_count,
            "duration": duration,
            "channel_name": item.get("uploader") or item.get("channel"),
            "channel_url": item.get("uploader_url") or item.get("channel_url"),
            "thumbnail_url": item.get("thumbnail"),
            "date": upload_date,
            "video_id": video_id,
            "source": f"keyword: {keyword}"
        }
        videos.append(video_data)

    return videos


def scrape_channel(channel_id, channel_name):
    """Scrape recent videos from a specific channel."""
    print(f"  - Monitoring channel: {channel_name}")
    channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"

    cmd = [
        "yt-dlp",
        channel_url,
        "--dump-json",
        "--playlist-end", str(MAX_VIDEOS_PER_CHANNEL),
        "--skip-download",
        "--no-warnings"
    ]

    items = run_ytdlp(cmd)
    videos = []
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=DAYS_BACK)).strftime("%Y%m%d")

    for item in items:
        upload_date = item.get("upload_date")
        if not upload_date or upload_date < cutoff_date:
            continue

        video_id = item.get("id")
        youtube_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else item.get("webpage_url")
        duration = item.get("duration", 0)
        view_count = item.get("view_count", 0)

        if duration < MIN_VIDEO_DURATION_SECONDS or view_count < MIN_VIEW_COUNT:
            continue

        video_data = {
            "title": item.get("title"),
            "url": youtube_url,
            "view_count": view_count,
            "duration": duration,
            "channel_name": channel_name,
            "channel_url": f"https://www.youtube.com/channel/{channel_id}",
            "thumbnail_url": item.get("thumbnail"),
            "date": upload_date,
            "video_id": video_id,
            "source": f"channel: {channel_name}"
        }
        videos.append(video_data)

    return videos


def get_channel_average(channel_url):
    """Get average view count for a channel."""
    if not channel_url:
        return 0

    cmd = [
        "yt-dlp",
        channel_url,
        "--dump-json",
        "--playlist-end", "10",
        "--flat-playlist",
        "--skip-download"
    ]

    items = run_ytdlp(cmd)
    views = [int(item.get("view_count")) for item in items if item.get("view_count") is not None]
    return sum(views) / len(views) if views else 0


def fetch_transcript(video_id):
    """Fetch transcript using youtube-transcript-api with Apify fallback."""
    if not video_id:
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        time.sleep(1)
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = ' '.join([entry['text'] for entry in transcript])
        return text
    except Exception as e:
        error_str = str(e).lower()
        if '429' in error_str or 'too many requests' in error_str:
            time.sleep(5)
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
                text = ' '.join([entry['text'] for entry in transcript])
                return text
            except Exception:
                pass

    apify_token = os.getenv("APIFY_API_TOKEN")
    if not apify_token:
        return None

    try:
        from apify_client import ApifyClient
        apify_client = ApifyClient(apify_token)
        run = apify_client.actor("karamelo/youtube-transcripts").call(
            run_input={"urls": [f"https://www.youtube.com/watch?v={video_id}"]},
            timeout_secs=120
        )
        dataset_items = list(apify_client.dataset(run["defaultDatasetId"]).iterate_items())
        if dataset_items and "captions" in dataset_items[0]:
            return " ".join(dataset_items[0]["captions"])
    except Exception:
        pass

    return None


def summarize_transcript(text, title):
    """Summarize transcript with focus on transferable patterns."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY not set"

    client = Anthropic(api_key=api_key)

    prompt = f"""Analyze this YouTube video for transferable content patterns.

Title: {title}

Transcript (first 8000 chars):
{text[:8000]}

Provide BRIEF analysis (3-4 sentences total) covering:
1. Core hook/angle and why it works
2. Key content structure or pattern
3. How to adapt this for AI/automation content

Keep it concise and actionable."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"Summarization error: {str(e)}"


def generate_title_variants(original_title, summary=None):
    """Generate 3 title variants adapted for AI/automation niche."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ["", "", ""]

    client = Anthropic(api_key=api_key)
    context = f"\n\nContext from original video: {summary}" if summary else ""

    prompt = f"""You're a YouTube strategist for a channel about {USER_CHANNEL_NICHE}.

Analyze this high-performing title from a different niche and generate 3 adapted variants for my channel.

Original Title: "{original_title}"{context}

Generate 3 NEW title variants that:
- Adapt the hook/structure to AI agents and automation
- Use the same emotional trigger and curiosity gap as original
- Are specific to {USER_CHANNEL_NICHE}
- Are meaningfully different from each other
- Stay under 100 characters

Return ONLY a JSON array of 3 strings (the variant titles), nothing else.
Example format: ["Variant 1", "Variant 2", "Variant 3"]"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text.strip()
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()

        variants = json.loads(response_text)
        if isinstance(variants, list) and len(variants) == 3:
            return variants
    except Exception as e:
        print(f"      Title variant error: {str(e)[:100]}")

    return ["", "", ""]


def categorize_content(title, summary=""):
    """Auto-categorize content type."""
    title_lower = title.lower()
    summary_lower = summary.lower() if summary else ""
    combined = title_lower + " " + summary_lower

    if any(word in combined for word in ["money", "revenue", "income", "profit", "$", "million"]):
        return "Money"
    elif any(word in combined for word in ["productivity", "time", "efficient", "faster"]):
        return "Productivity"
    elif any(word in combined for word in ["youtube", "content", "creator", "channel"]):
        return "Creator"
    elif any(word in combined for word in ["business", "startup", "founder", "entrepreneur"]):
        return "Business"
    else:
        return "General"


def is_noise_content(title):
    """Filter out content that should never appear in results."""
    title_lower = title.lower()

    hard_exclude = [
        "official music video", "official video", "lyric video", "music video",
        "ft.", "feat.", "(official audio)", "official audio",
        "minecraft", "fortnite", "valorant", "call of duty", "gta",
        "gameplay", "gaming", "let's play", "walkthrough", "playthrough",
        "asmr", "mukbang", "eating show",
        "#shorts", "tiktok compilation",
    ]

    if any(term in title_lower for term in OWN_NICHE_TERMS):
        return True

    return any(pattern in title_lower for pattern in hard_exclude)


def process_outlier_content(outlier, index, total, skip_transcripts=False):
    """Process a single outlier: fetch transcript, summarize, generate variants."""
    title_short = outlier['title'][:50] + "..." if len(outlier['title']) > 50 else outlier['title']
    print(f"\n  [{index}/{total}] {title_short}")

    if skip_transcripts:
        outlier["summary"] = "Skipped"
        outlier["transcript"] = ""
    else:
        print(f"    Fetching transcript...")
        transcript = fetch_transcript(outlier["video_id"])

        if transcript:
            print(f"    Got transcript ({len(transcript)} chars)")
            summary = summarize_transcript(transcript, outlier["title"])
            outlier["summary"] = summary
            outlier["transcript"] = transcript
        else:
            print(f"    No transcript available")
            outlier["summary"] = "No transcript available"
            outlier["transcript"] = ""

    outlier["category"] = categorize_content(outlier["title"], outlier.get("summary", ""))

    print(f"    Generating title variants...")
    variants = generate_title_variants(
        outlier["title"],
        outlier.get("summary") if not skip_transcripts else None
    )
    outlier["title_variant_1"] = variants[0] if len(variants) > 0 else ""
    outlier["title_variant_2"] = variants[1] if len(variants) > 1 else ""
    outlier["title_variant_3"] = variants[2] if len(variants) > 2 else ""

    print(f"    Done")
    return outlier


def main():
    parser = argparse.ArgumentParser(description="Scrape cross-niche business outliers (yt-dlp)")
    parser.add_argument("--limit", type=int, help="Limit outliers to process")
    parser.add_argument("--days", type=int, default=90, help="Days to look back (default: 90)")
    parser.add_argument("--min_score", type=float, default=1.1, help="Min outlier score (default: 1.1)")
    parser.add_argument("--keywords_only", action="store_true", help="Skip channel monitoring")
    parser.add_argument("--channels_only", action="store_true", help="Skip keyword searches")
    parser.add_argument("--skip_transcripts", action="store_true", help="Skip transcript fetching (faster)")
    parser.add_argument("--content_workers", type=int, default=5, help="Parallel workers (default: 5)")

    args = parser.parse_args()

    global DAYS_BACK, MIN_OUTLIER_SCORE
    DAYS_BACK = args.days
    MIN_OUTLIER_SCORE = args.min_score

    print(f"Cross-Niche Outlier Detection (yt-dlp)")
    print(f"  Days back: {DAYS_BACK}")
    print(f"  Min score: {MIN_OUTLIER_SCORE}")
    print(f"  Target: ~20 outliers per run")
    print()

    # Step 1: Scrape videos
    all_videos = []

    if not args.channels_only:
        print("Scraping keywords...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(scrape_keyword, kw) for kw in CROSS_NICHE_KEYWORDS]
            for future in as_completed(futures):
                all_videos.extend(future.result())

    if not args.keywords_only:
        print("\nMonitoring channels...")
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(scrape_channel, cid, cname)
                      for cid, cname in MONITORED_CHANNELS.items()]
            for future in as_completed(futures):
                all_videos.extend(future.result())

    # Deduplicate and filter noise
    seen = set()
    unique_videos = []
    filtered_count = 0
    for v in all_videos:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            if is_noise_content(v["title"]):
                filtered_count += 1
                continue
            unique_videos.append(v)

    print(f"\nFound {len(unique_videos)} unique videos (filtered {filtered_count} noise)")

    if not unique_videos:
        print("No videos found. Exiting.")
        return 0

    # Step 2: Calculate outlier scores
    print("\nCalculating outlier scores...")
    with ThreadPoolExecutor(max_workers=20) as executor:
        channel_futures = {v["channel_url"]: executor.submit(get_channel_average, v["channel_url"])
                          for v in unique_videos if v.get("channel_url")}
        channel_avgs = {url: future.result() for url, future in channel_futures.items()}

    outliers = []
    for video in unique_videos:
        channel_avg = channel_avgs.get(video.get("channel_url"), 0)
        if channel_avg > 0:
            raw_outlier_score = video["view_count"] / channel_avg

            upload_date = datetime.datetime.strptime(video["date"], "%Y%m%d")
            days_old = (datetime.datetime.now() - upload_date).days
            if days_old <= 1:
                recency_multiplier = 2.0
            elif days_old <= 3:
                recency_multiplier = 1.5
            elif days_old <= 7:
                recency_multiplier = 1.2
            else:
                recency_multiplier = 1.0

            outlier_score = raw_outlier_score * recency_multiplier

            if outlier_score >= MIN_OUTLIER_SCORE:
                cross_niche_score = calculate_cross_niche_score(video["title"], outlier_score)

                if cross_niche_score == 0:
                    continue

                video["outlier_score"] = round(outlier_score, 2)
                video["raw_outlier_score"] = round(raw_outlier_score, 2)
                video["channel_avg_views"] = int(channel_avg)
                video["cross_niche_score"] = cross_niche_score
                video["days_old"] = days_old
                outliers.append(video)

    outliers.sort(key=lambda x: x["cross_niche_score"], reverse=True)

    if args.limit:
        outliers = outliers[:args.limit]

    print(f"Found {len(outliers)} outliers")

    if not outliers:
        print("No outliers found. Try lowering --min_score.")
        return 0

    # Step 3: Process content
    print(f"\nProcessing {len(outliers)} outliers...")

    with ThreadPoolExecutor(max_workers=args.content_workers) as executor:
        futures = {
            executor.submit(
                process_outlier_content, outlier, i, len(outliers), args.skip_transcripts
            ): outlier
            for i, outlier in enumerate(outliers, 1)
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"    Error: {str(e)}")

    # Step 4: Create Google Sheet
    print("\nCreating Google Sheet...")
    creds = get_credentials()
    gc = gspread.authorize(creds)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sheet_title = f"Cross-Niche Outliers v2 - {timestamp}"
    spreadsheet = gc.create(sheet_title)
    worksheet = spreadsheet.sheet1

    headers = [
        "Cross-Niche Score", "Outlier Score (w/ Recency)", "Raw Outlier Score", "Days Old",
        "Category", "Title", "Video Link", "View Count", "Duration (min)",
        "Channel Name", "Channel Avg Views", "Thumbnail", "Summary",
        "Title Variant 1", "Title Variant 2", "Title Variant 3",
        "Raw Transcript", "Publish Date", "Source"
    ]

    rows = [headers]
    for o in outliers:
        rows.append([
            o["cross_niche_score"],
            o["outlier_score"],
            o.get("raw_outlier_score", o["outlier_score"]),
            o.get("days_old", "N/A"),
            o.get("category", "Unknown"),
            o["title"],
            o["url"],
            o["view_count"],
            round(o.get("duration", 0) / 60, 1),
            o["channel_name"],
            o["channel_avg_views"],
            f'=IMAGE("{o["thumbnail_url"]}")',
            o.get("summary", ""),
            o.get("title_variant_1", ""),
            o.get("title_variant_2", ""),
            o.get("title_variant_3", ""),
            o.get("transcript", "")[:50000],
            o["date"],
            o.get("source", "")
        ])

    worksheet.update(range_name='A1', values=rows, value_input_option='USER_ENTERED')

    print(f"\nDone! Created sheet with {len(outliers)} cross-niche outliers")
    print(f"Sheet URL: {spreadsheet.url}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
