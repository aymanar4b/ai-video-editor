#!/usr/bin/env python3
"""
AI Video Editor — Silence Removal + Audio Enhancement
Uses Silero VAD for neural voice activity detection and FFmpeg for processing.

Usage:
    python edit_video.py input.mp4 [--output output.mp4] [--silence-threshold 0.5]
                                    [--min-silence 0.4] [--padding 0.08]
                                    [--enhance-audio] [--preview]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def check_ffmpeg():
    """Verify FFmpeg is installed."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("ERROR: FFmpeg not found. Install with: brew install ffmpeg")
        return False


def get_video_info(input_path):
    """Get video duration and metadata using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)
    duration = float(info["format"]["duration"])

    # Find video stream for resolution
    video_stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    width = int(video_stream["width"]) if video_stream else 1920
    height = int(video_stream["height"]) if video_stream else 1080
    fps = video_stream.get("r_frame_rate", "30/1") if video_stream else "30/1"

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
    }


def extract_audio(input_path, output_wav, sample_rate=16000):
    """Extract audio from video as 16kHz mono WAV (required by Silero VAD)."""
    print("  Extracting audio...")
    cmd = [
        "ffmpeg", "-i", input_path, "-vn",
        "-acodec", "pcm_s16le", "-ar", str(sample_rate), "-ac", "1",
        "-y", output_wav
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def detect_speech_segments(wav_path, threshold=0.5, min_silence_duration=0.4, padding=0.08):
    """
    Use Silero VAD to detect speech segments.
    Returns list of (start, end) tuples in seconds.
    """
    import torch
    import torchaudio

    print("  Loading Silero VAD model...")
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=False,
    )
    (get_speech_timestamps, _, read_audio, _, _) = utils

    print("  Running voice activity detection...")
    wav = read_audio(wav_path, sampling_rate=16000)

    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        threshold=threshold,
        min_silence_duration_ms=int(min_silence_duration * 1000),
        speech_pad_ms=int(padding * 1000),
        sampling_rate=16000,
    )

    # Convert sample indices to seconds
    segments = []
    for ts in speech_timestamps:
        start = ts["start"] / 16000.0
        end = ts["end"] / 16000.0
        segments.append((start, end))

    return segments


def merge_close_segments(segments, max_gap=0.15):
    """Merge segments that are very close together to avoid choppy cuts."""
    if not segments:
        return segments

    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    return merged


def build_ffmpeg_filter(segments, enhance_audio=False):
    """
    Build FFmpeg filter_complex for cutting and concatenating segments.
    Uses the trim/atrim approach for precise cuts.
    """
    video_parts = []
    audio_parts = []

    for i, (start, end) in enumerate(segments):
        # Video trim
        video_parts.append(
            f"[0:v]trim=start={start:.4f}:end={end:.4f},setpts=PTS-STARTPTS[v{i}]"
        )
        # Audio trim
        audio_parts.append(
            f"[0:a]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS[a{i}]"
        )

    # Concatenate all parts
    n = len(segments)
    video_labels = "".join(f"[v{i}]" for i in range(n))
    audio_labels = "".join(f"[a{i}]" for i in range(n))

    concat_filter = f"{video_labels}{audio_labels}concat=n={n}:v=1:a=1[outv][outa]"

    all_filters = video_parts + audio_parts + [concat_filter]

    # Audio enhancement chain (optional)
    if enhance_audio:
        all_filters.append(
            "[outa]"
            # Highpass to remove low rumble
            "highpass=f=80,"
            # Compress dynamic range (makes voice more consistent)
            "compand=attacks=0.02:decays=0.3:points=-80/-80|-45/-30|-27/-20|-10/-10|0/-5:gain=3,"
            # Light noise reduction via gentle lowpass on quiet parts
            "afftdn=nf=-25,"
            # Normalize volume
            "loudnorm=I=-16:TP=-1.5:LRA=11"
            "[outa_enhanced]"
        )
        final_audio = "[outa_enhanced]"
    else:
        final_audio = "[outa]"

    filter_complex = ";".join(all_filters)

    return filter_complex, final_audio


def process_video(input_path, output_path, segments, enhance_audio=False, video_info=None):
    """
    Process the video: cut segments and concatenate using FFmpeg.
    Uses hardware acceleration where available.
    """
    print(f"  Processing {len(segments)} speech segments...")

    filter_complex, final_audio = build_ffmpeg_filter(segments, enhance_audio)

    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", final_audio,
        # Encoding settings — use h264 with good quality
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-y",
        output_path,
    ]

    # Try hardware acceleration on macOS
    if sys.platform == "darwin":
        cmd_hw = cmd.copy()
        # Replace libx264 with videotoolbox for macOS hardware encoding
        idx = cmd_hw.index("libx264")
        cmd_hw[idx] = "h264_videotoolbox"
        # Remove CRF (not supported by videotoolbox), use bitrate instead
        crf_idx = cmd_hw.index("-crf")
        cmd_hw[crf_idx] = "-b:v"
        cmd_hw[crf_idx + 1] = "8M"

        print("  Trying hardware-accelerated encoding (VideoToolbox)...")
        result = subprocess.run(cmd_hw, capture_output=True, text=True)
        if result.returncode == 0:
            return True
        print("  Hardware encoding failed, falling back to software...")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFmpeg error: {result.stderr[-500:]}")
        return False
    return True


def print_summary(video_info, segments, input_path, output_path):
    """Print a summary of what was done."""
    original_duration = video_info["duration"]
    edited_duration = sum(end - start for start, end in segments)
    removed = original_duration - edited_duration

    output_size = os.path.getsize(output_path) / (1024 * 1024)
    input_size = os.path.getsize(input_path) / (1024 * 1024)

    print("\n" + "=" * 50)
    print("  VIDEO EDIT COMPLETE")
    print("=" * 50)
    print(f"  Original:  {original_duration:.1f}s ({original_duration/60:.1f} min) — {input_size:.1f} MB")
    print(f"  Edited:    {edited_duration:.1f}s ({edited_duration/60:.1f} min) — {output_size:.1f} MB")
    print(f"  Removed:   {removed:.1f}s of silence ({removed/original_duration*100:.1f}%)")
    print(f"  Segments:  {len(segments)} speech segments kept")
    print(f"  Output:    {output_path}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="AI Video Editor — Silence Removal")
    parser.add_argument("input", help="Input video file path")
    parser.add_argument("--output", "-o", help="Output video file path (default: input_edited.mp4)")
    parser.add_argument("--silence-threshold", "-t", type=float, default=0.5,
                        help="VAD confidence threshold (0-1, lower = more aggressive silence detection, default: 0.5)")
    parser.add_argument("--min-silence", "-s", type=float, default=0.4,
                        help="Minimum silence duration to cut in seconds (default: 0.4)")
    parser.add_argument("--padding", "-p", type=float, default=0.08,
                        help="Padding around speech in seconds (default: 0.08)")
    parser.add_argument("--merge-gap", "-g", type=float, default=0.15,
                        help="Merge segments closer than this many seconds (default: 0.15)")
    parser.add_argument("--enhance-audio", "-e", action="store_true",
                        help="Apply audio enhancement (compression, noise reduction, normalization)")
    parser.add_argument("--preview", action="store_true",
                        help="Only show what would be cut, don't process")
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    if not check_ffmpeg():
        sys.exit(1)

    # Default output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        stem = Path(input_path).stem
        ext = Path(input_path).suffix
        output_path = str(Path(input_path).parent / f"{stem}_edited{ext}")

    print(f"\n  AI Video Editor")
    print(f"  Input: {input_path}")
    print(f"  Settings: threshold={args.silence_threshold}, min_silence={args.min_silence}s, padding={args.padding}s")
    print()

    start_time = time.time()

    # Step 1: Get video info
    print("[1/4] Analyzing video...")
    video_info = get_video_info(input_path)
    print(f"  Duration: {video_info['duration']:.1f}s ({video_info['duration']/60:.1f} min)")
    print(f"  Resolution: {video_info['width']}x{video_info['height']}")

    # Step 2: Extract audio
    print("\n[2/4] Extracting audio for analysis...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        extract_audio(input_path, wav_path)

        # Step 3: Detect speech
        print("\n[3/4] Detecting speech segments (Silero VAD)...")
        segments = detect_speech_segments(
            wav_path,
            threshold=args.silence_threshold,
            min_silence_duration=args.min_silence,
            padding=args.padding,
        )

        # Merge close segments
        segments = merge_close_segments(segments, max_gap=args.merge_gap)

        speech_duration = sum(end - start for start, end in segments)
        silence_duration = video_info["duration"] - speech_duration

        print(f"  Found {len(segments)} speech segments")
        print(f"  Speech: {speech_duration:.1f}s | Silence: {silence_duration:.1f}s ({silence_duration/video_info['duration']*100:.1f}%)")

        if args.preview:
            print("\n  PREVIEW MODE — showing first 20 segments:")
            for i, (start, end) in enumerate(segments[:20]):
                print(f"    [{i+1:3d}] {start:7.2f}s — {end:7.2f}s  ({end-start:.2f}s)")
            if len(segments) > 20:
                print(f"    ... and {len(segments) - 20} more segments")
            print(f"\n  Would remove {silence_duration:.1f}s of silence ({silence_duration/video_info['duration']*100:.1f}%)")
            return

        if not segments:
            print("  No speech detected! Check your threshold or input file.")
            sys.exit(1)

        # Step 4: Process video
        print(f"\n[4/4] Building edited video{' with audio enhancement' if args.enhance_audio else ''}...")
        success = process_video(input_path, output_path, segments, args.enhance_audio, video_info)

        if success:
            elapsed = time.time() - start_time
            print_summary(video_info, segments, input_path, output_path)
            print(f"  Processing time: {elapsed:.1f}s")
        else:
            print("\n  ERROR: Video processing failed.")
            sys.exit(1)

    finally:
        # Clean up temp WAV
        if os.path.exists(wav_path):
            os.unlink(wav_path)


if __name__ == "__main__":
    main()
