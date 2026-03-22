# Jump Cut Editor (VAD-based)

Automatically remove silences from talking-head videos using neural voice activity detection (Silero VAD). More accurate than FFmpeg silence detection, especially for videos with background noise, breathing sounds, or quiet speech.

## Execution Script

`execution/jump_cut_vad.py` (sequential) or `execution/jump_cut_vad_parallel.py` (parallel, 4-6x faster)

---

## Quick Start

```bash
# Basic silence removal
python3 execution/jump_cut_vad_parallel.py input.mp4 output.mp4

# With audio enhancement and color grading
python3 execution/jump_cut_vad_parallel.py input.mp4 output.mp4 \
    --enhance-audio \
    --apply-lut .tmp/cinematic.cube

# With "cut cut" restart detection (removes mistakes)
python3 execution/jump_cut_vad_parallel.py input.mp4 output.mp4 \
    --detect-restarts \
    --enhance-audio
```

---

## What It Does

1. **Extracts audio** from video as WAV
2. **Runs Silero VAD** (neural voice activity detection) to identify speech segments
3. **Optionally detects "cut cut"** restart phrases and removes mistake segments
4. **Concatenates speech segments** with padding
5. **Applies audio enhancement** (optional): EQ, compression, loudness normalization
6. **Applies color grading** (optional): LUT-based color correction

---

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `input` | required | Input video file path |
| `output` | required | Output video file path |
| `--min-silence` | 0.5 | Minimum silence gap to cut (seconds) |
| `--min-speech` | 0.25 | Minimum speech duration to keep (seconds) |
| `--padding` | 50/100 | Padding around speech in milliseconds |
| `--merge-gap` | 0.3 | Merge segments closer than this (seconds) |
| `--keep-start` | true | Preserve intro (start from 0:00) |
| `--no-keep-start` | - | Allow cutting silence at the beginning |
| `--enhance-audio` | false | Apply audio enhancement chain |
| `--detect-restarts` | false | Detect "cut cut" and remove mistakes |
| `--restart-phrase` | "cut cut" | Custom restart trigger phrase |
| `--whisper-model` | base | Whisper model for restart detection |
| `--apply-lut` | none | Path to LUT file for color grading |
| `--workers` | 4 | Parallel encoding workers (parallel version only) |
| `--smart-render` | false | Smart render for faster processing |

---

## Features

### 1. Silero VAD (Voice Activity Detection)

Uses a neural network trained specifically for voice detection:

| Silero VAD | FFmpeg silencedetect |
|------------|---------------------|
| Detects actual speech | Detects volume drops |
| Ignores breathing | Cuts on breathing pauses |
| Works with background noise | Fails with background noise |
| Handles quiet speech | Misses quiet speech |

### 2. "Cut Cut" Restart Detection

Say "cut cut" during recording to mark a mistake. The script will:
1. Detect the phrase using Whisper transcription
2. Remove the segment containing "cut cut"
3. Remove the **previous** segment (where the mistake is)

### 3. Audio Enhancement

```
highpass=f=80            # Remove rumble below 80Hz
lowpass=f=12000          # Remove harsh highs above 12kHz
equalizer (200Hz, -1dB)  # Reduce muddiness
equalizer (3kHz, +2dB)   # Boost presence/clarity
acompressor              # Gentle compression (3:1 ratio)
loudnorm=I=-16           # YouTube loudness standard (-16 LUFS)
```

### 4. LUT Color Grading

**Supported formats:** `.cube`, `.3dl`, `.dat`, `.m3d`, `.csp`

### 5. Parallel Encoding (parallel version)

Encodes 4 segments simultaneously using ThreadPoolExecutor. On Apple Silicon with VideoToolbox, this is 4-6x faster than sequential.

### 6. Smart Rendering (parallel version)

For long segments (>5s), only re-encodes 1s at each cut edge and stream-copies the middle. 10-20x faster for long segments.

---

## Parameter Tuning

| Goal | Parameter | Value |
|------|-----------|-------|
| More aggressive cuts | `--min-silence` | 0.3-0.4 |
| Preserve natural pauses | `--min-silence` | 0.8-1.0 |
| Tight cuts | `--padding` | 50-80 |
| Natural feel | `--padding` | 100-150 |
| Extra breathing room | `--padding` | 200-300 |

---

## Hardware Encoding

Automatically uses **h264_videotoolbox** on macOS when available:

| Encoding | Speed | When Used |
|----------|-------|-----------|
| Hardware (h264_videotoolbox) | 5-10x faster | macOS with Apple Silicon/Intel |
| Software (libx264) | Baseline | Fallback if hardware unavailable |

---

## Dependencies

```bash
pip install torch torchaudio          # For Silero VAD
pip install openai-whisper            # For restart detection (optional)
brew install ffmpeg                   # macOS
```
