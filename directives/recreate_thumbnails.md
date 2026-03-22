# Recreate YouTube Thumbnails

## Goal
Face-swap YouTube thumbnails to feature your face using Nano Banana Pro (Gemini image model). The system:
- Analyzes face direction (yaw/pitch) in the source thumbnail
- Finds the best-matching reference photo by pose
- Generates 3 variations by default
- Supports iterative edit passes for refinements

## Quick Start

```bash
# Generate 3 variations from a YouTube video
python execution/recreate_thumbnails.py --youtube "https://youtube.com/watch?v=VIDEO_ID"

# Generate from a local thumbnail
python execution/recreate_thumbnails.py --source ".tmp/thumbnails/source_yt_thumb.jpg"

# Edit pass on a generated thumbnail
python execution/recreate_thumbnails.py --edit ".tmp/thumbnails/20251205/104016_1.png" \
  --prompt "Change colors to teal. Change 'AI GOLD RUSH' to 'AGENTIC FLOWS'."
```

## Full Workflow

### Step 1: Build Reference Photo Bank (One-time setup)

Drop 30-40 photos in various face directions into the raw folder:
```bash
mkdir -p .tmp/reference_photos/raw
# Add photos here...
```

Analyze and rename with face direction metadata:
```bash
python execution/analyze_face_directions.py

# Preview without renaming
python execution/analyze_face_directions.py --preview
```

This creates files like:
- `nick_yawL30_pitchU10.jpg` — looking 30° left, 10° up
- `nick_yawR45_pitch0.jpg` — looking 45° right, level
- `nick_yaw0_pitchD15.jpg` — straight ahead, 15° down

### Step 2: Generate Thumbnails

```bash
# From YouTube URL (auto-analyzes face, finds best reference, generates 3 variations)
python execution/recreate_thumbnails.py --youtube "https://youtube.com/watch?v=VIDEO_ID"

# From local image
python execution/recreate_thumbnails.py --source "path/to/thumbnail.jpg"

# Custom variation count
python execution/recreate_thumbnails.py --source "thumbnail.jpg" -n 5

# Skip direction matching (use default references)
python execution/recreate_thumbnails.py --source "thumbnail.jpg" --no-match
```

### Step 3: Select Best & Edit

```bash
# Single edit
python execution/recreate_thumbnails.py --edit ".tmp/thumbnails/recreated_v3.png" \
  --prompt "Change colors to teal. Change 'AI GOLD RUSH' to 'AGENTIC FLOWS'."

# Chain multiple edits
python execution/recreate_thumbnails.py --edit ".tmp/thumbnails/edited_1.png" \
  --prompt "Make the graph show two bounces instead of one."
```

## File Locations

| Path | Purpose |
|------|---------|
| `.tmp/reference_photos/` | Direction-labeled reference photos |
| `.tmp/reference_photos/raw/` | Drop new photos here for analysis |
| `.tmp/thumbnails/YYYYMMDD/` | Generated thumbnails organized by date |
| `execution/recreate_thumbnails.py` | Main script |
| `execution/analyze_face_directions.py` | Reference photo analyzer |

## CLI Reference

### recreate_thumbnails.py

| Flag | Description |
|------|-------------|
| `--youtube`, `-y` | YouTube video URL |
| `--source`, `-s` | Source thumbnail path or URL |
| `--edit`, `-e` | Image to edit (enables edit mode) |
| `--prompt`, `-p` | Additional instructions (required for edit mode) |
| `--variations`, `-n` | Number of variations (default: 3) |
| `--refs` | Number of reference photos (default: 2) |
| `--output`, `-o` | Custom output filename |
| `--no-match` | Skip face direction matching |

### analyze_face_directions.py

| Flag | Description |
|------|-------------|
| `--preview`, `-p` | Show analysis without renaming |
| `--single`, `-s` | Analyze a single image |
| `--find` | Find closest reference for yaw,pitch (e.g., `--find "-30,10"`) |

## API Notes

- **Model:** `gemini-3-pro-image-preview` (Nano Banana Pro)
- **Cost:** ~$0.14-0.24 per generation/edit
- **API key:** `NANO_BANANA_API_KEY` in `.env`
- **2 reference photos is optimal** — 1 loses likeness, 3+ can cause full regeneration

## Dependencies

```bash
pip install opencv-python mediapipe google-genai Pillow python-dotenv requests
```

### Environment Variables (`.env`)

```
NANO_BANANA_API_KEY=your_gemini_api_key
```
