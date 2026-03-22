# Video Editing Directive

Automatically edit talking-head videos: remove silences, enhance audio, add swivel teaser, and optionally upload to YouTube.

---

## Recommended Workflow (VAD + Swivel Teaser)

The best quality workflow uses neural voice activity detection for silence removal, then adds a swivel teaser preview.

### When User Says "Edit X Video"

1. Run Step 1 (VAD silence removal) on the input video
2. Run Step 2 (swivel teaser) on the edited output
3. Open the final video for user review

**Background image:** Use `.tmp/bg.png` if it exists, otherwise omit `--bg-image` (uses solid gray).

### Quick Start

**IMPORTANT: Always use the parallel version (`jump_cut_vad_parallel.py`) - it's 5-10x faster.**

```bash
# Step 1: Remove silences + enhance audio (PARALLEL version)
python3 execution/jump_cut_vad_parallel.py input.mp4 .tmp/edited.mp4 --enhance-audio

# Step 2: Add swivel teaser at 3 seconds (previews content from 1:00 onwards)
python3 execution/insert_3d_transition.py .tmp/edited.mp4 output.mp4 \
    --bg-image .tmp/background.png
```

### One-liner

```bash
python3 execution/jump_cut_vad_parallel.py input.mp4 .tmp/edited.mp4 --enhance-audio && \
python3 execution/insert_3d_transition.py .tmp/edited.mp4 output.mp4 --bg-image .tmp/bg.png
```

### What This Produces

| Step | Tool | Result |
|------|------|--------|
| 1 | `jump_cut_vad_parallel.py` | Silences removed via neural VAD, audio enhanced (EQ, compression, -16 LUFS) |
| 2 | `insert_3d_transition.py` | 5-second swivel teaser inserted at 3s, previewing content from 1:00 onwards |

**Timeline:**
```
[0-3s intro] [3-8s swivel teaser @ 60x] [8s onwards: edited content]
Audio: Original audio plays continuously throughout
```

### Full Options

```bash
# With "cut cut" restart detection (removes mistakes)
python3 execution/jump_cut_vad_parallel.py input.mp4 .tmp/edited.mp4 \
    --enhance-audio --detect-restarts

# With LUT color grading
python3 execution/jump_cut_vad_parallel.py input.mp4 .tmp/edited.mp4 \
    --enhance-audio --apply-lut .tmp/cinematic.cube

# Custom swivel teaser timing
python3 execution/insert_3d_transition.py .tmp/edited.mp4 output.mp4 \
    --insert-at 5 --duration 3 --teaser-start 90 --bg-image .tmp/bg.png
```

See `directives/jump_cut_vad.md` for full documentation.

---

## Alternative: Simple FFmpeg Workflow

For simpler needs, use the FFmpeg-based workflow with Auphonic upload.

### Execution Script

`execution/simple_video_edit.py`

### Workflow

**Always run local-first.** Never ask user whether to upload — just edit locally, present result, then upload when confirmed.

1. Run with `--no-upload` first
2. Present the edited video and metadata to user
3. Only upload via Auphonic after user confirms

```bash
# Step 1: Edit locally (always do this first)
python3 execution/simple_video_edit.py \
    --video .tmp/my_video.mp4 \
    --title "My Video Title" \
    --no-upload

# Step 2: After user confirms, upload
python3 execution/simple_video_edit.py \
    --video .tmp/my_video_edited.mp4 \
    --title "My Video Title" \
    --upload-only
```

Output:
- Edited video: `.tmp/{original_name}_edited.mp4`
- Metadata file: `.tmp/{original_name}_metadata.txt`

---

## What It Does (Pipeline)

1. **Silence Detection** - FFmpeg detects silences >= 3s at -35dB
2. **Silence Removal** - Cuts all detected silences (no AI decisions)
3. **Audio Normalization** - EBU R128 (-16 LUFS) + 80Hz highpass
4. **Transcription** - Whisper transcribes for metadata generation
5. **Metadata Generation** - Claude generates summary + chapters (saved to file)
6. **Auphonic Upload** - Uploads to Auphonic -> YouTube as private draft

---

## Recording Workflow

1. **Start recording** (1-3s silent intro is fine)
2. **Speak content** with natural pauses
3. **Long pause (3+ seconds)** = will be cut
4. **Say "cut cut"** to mark a mistake — the editor removes it and the previous segment
5. **Stop recording**

---

## Dependencies

```bash
pip install torch torchaudio whisper anthropic faster-whisper python-dotenv requests
brew install ffmpeg  # macOS
cd execution/video_effects && npm install  # For swivel teaser
```

### Environment Variables (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...
AUPHONIC_API_KEY=...          # Optional, for YouTube upload
AUPHONIC_PRESET_UUID=...      # Optional
YOUTUBE_SERVICE_UUID=...      # Optional
```
