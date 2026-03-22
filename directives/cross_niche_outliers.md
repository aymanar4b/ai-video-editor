# Cross-Niche Outlier Detection

## Goal
Identify high-performing videos from adjacent business niches to extract transferable content patterns, hooks, and structures. Uses TubeLab API for pre-calculated outlier scores.

## Quick Start

```bash
# Default: 1 query = 5 credits, ~100 outliers from last 30 days
python3 execution/scrape_cross_niche_tubelab.py

# Custom search term
python3 execution/scrape_cross_niche_tubelab.py --terms "business strategy"

# Multiple queries (uses more credits)
python3 execution/scrape_cross_niche_tubelab.py --queries 3 --terms "entrepreneur" "business" "productivity"

# Skip transcripts (faster, cheaper Claude costs)
python3 execution/scrape_cross_niche_tubelab.py --skip_transcripts
```

## How It Works

### 1. Video Discovery
- Searches TubeLab's 4M+ video outlier database
- Filters: English only, long-form videos, min 10k views
- Server-side date filtering (default: last 30 days)

### 2. Cross-Niche Filtering
- **Hard excludes** own niche (AI, automation, coding terms)
- **Heavy penalty** for non-transferable formats (reviews, challenges, vlogs, news)
- **Bonuses** for proven hooks:
  - +40% money hooks ($, revenue, income)
  - +30% curiosity hooks (secrets, "this changed everything")
  - +25% transformation hooks (before/after, "how I built")
  - +25% contrarian hooks (myths, mistakes, "why I quit")
  - +20% time hooks (faster, productivity, shortcuts)
  - +15% urgency hooks (before it's too late)
  - +10% numbers in title (listicles)

### 3. Content Processing (per outlier)
- Fetch transcript (youtube-transcript-api → Apify fallback)
- Summarize with Claude (transferable patterns focus)
- Generate 3 title variants adapted to your niche

### 4. Output to Google Sheet
Creates sheet with 27 columns including scores, stats, summaries, title variants, and raw transcripts.

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `--queries N` | Number of search queries (5 credits each) | 1 |
| `--terms "a" "b"` | Custom search terms | entrepreneur |
| `--size N` | Results per query | 100 |
| `--min_views N` | Minimum view count | 10,000 |
| `--max_days N` | Max video age in days | 30 |
| `--min_score X` | Minimum cross-niche score | 1.5 |
| `--limit N` | Max outliers to process | None |
| `--skip_transcripts` | Skip transcript/summary | False |
| `--workers N` | Parallel workers | 3 |

## Dependencies

```bash
pip install anthropic gspread google-auth google-auth-oauthlib youtube-transcript-api python-dotenv requests
```

### Environment Variables (`.env`)

```
TUBELAB_API_KEY=your_tubelab_key
ANTHROPIC_API_KEY=sk-ant-...
APIFY_API_TOKEN=...          # Optional, for fallback transcripts
```

### Google Sheets Auth
Place `credentials.json` (OAuth or service account) in project root. First run will create `token.json`.

## Workflow Integration

After finding outliers, generate face-swapped thumbnails:
```bash
# From an outlier's thumbnail URL
python3 execution/recreate_thumbnails.py --source "THUMBNAIL_URL"

# Or from the YouTube video directly
python3 execution/recreate_thumbnails.py --youtube "VIDEO_LINK"
```

## Cost & Time

- **Per query:** 5 TubeLab credits
- **Claude costs:** ~$0.15-0.25 per outlier (summary + 3 title variants)
- **Full run with transcripts:** ~5-10 minutes
- **Fast mode** (`--skip_transcripts`): ~30 seconds
- **Recommended frequency:** Weekly
