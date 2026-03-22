#!/usr/bin/env python3
"""
Jump Cut Editor v2 - Silero VAD Based

Uses Silero VAD (Voice Activity Detection) instead of FFmpeg silence detection.
Much more accurate at detecting actual speech vs silence/noise.

See: directives/jump_cut_vad.md for full documentation.

Features:
- Automatic silence removal using neural voice activity detection
- "Cut cut" restart phrase detection to remove mistakes
- Audio enhancement (EQ, compression, loudness normalization)
- LUT-based color grading via FFmpeg lut3d filter

Usage:
    # Basic silence removal
    python execution/jump_cut_vad.py input.mp4 output.mp4

    # With audio enhancement and color grading
    python execution/jump_cut_vad.py input.mp4 output.mp4 \
        --enhance-audio --apply-lut .tmp/cinematic.cube

    # With "cut cut" restart detection
    python execution/jump_cut_vad.py input.mp4 output.mp4 --detect-restarts
"""

import subprocess
import tempfile
import os
import argparse
import time
from pathlib import Path

# Configurable parameters
MIN_SILENCE_DURATION = 0.5  # Minimum gap between speech to cut (seconds)
PADDING_MS = 100  # Padding around speech segments (milliseconds)
MIN_SPEECH_DURATION = 0.25  # Minimum speech duration to keep (seconds)
RESTART_PHRASE = "cut cut"  # Phrase that triggers a restart/redo
RESTART_LOOKBACK = 10.0  # How far back to look for checkpoint (seconds)

# Audio enhancement settings
AUDIO_FILTERS = {
    "highpass": "highpass=f=80",  # Remove rumble below 80Hz
    "lowpass": "lowpass=f=12000",  # Remove harsh highs above 12kHz
    "presence": "equalizer=f=3000:t=q:w=1.5:g=2",  # Slight boost at 3kHz for clarity
    "warmth": "equalizer=f=200:t=q:w=1:g=-1",  # Slight cut at 200Hz to reduce muddiness
    "compression": "acompressor=threshold=-20dB:ratio=3:attack=5:release=50",  # Gentle compression
    "loudnorm": "loudnorm=I=-16:TP=-1.5:LRA=11",  # YouTube loudness standard (-16 LUFS)
}

# Supported LUT formats
SUPPORTED_LUT_FORMATS = [".cube", ".3dl", ".dat", ".m3d", ".csp"]

# Video encoding settings
HARDWARE_ENCODER = "h264_videotoolbox"
SOFTWARE_ENCODER = "libx264"
HARDWARE_BITRATE = "10M"  # 10 Mbps for hardware encoding (no CRF support)
SOFTWARE_CRF = "18"  # CRF 18 for software encoding (high quality)


def check_hardware_encoder_available() -> bool:
    """Check if h264_videotoolbox hardware encoder is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5
        )
        return "h264_videotoolbox" in result.stdout
    except Exception:
        return False


def get_video_encoder_args(use_hardware: bool = True) -> list[str]:
    """Get FFmpeg video encoder arguments."""
    if use_hardware and check_hardware_encoder_available():
        return ["-c:v", HARDWARE_ENCODER, "-b:v", HARDWARE_BITRATE]
    else:
        return ["-c:v", SOFTWARE_ENCODER, "-preset", "fast", "-crf", SOFTWARE_CRF]


# Cache the encoder check result (only check once per run)
_hardware_encoder_available = None

def get_cached_encoder_args() -> list[str]:
    """Get encoder args with cached hardware availability check."""
    global _hardware_encoder_available
    if _hardware_encoder_available is None:
        _hardware_encoder_available = check_hardware_encoder_available()
        if _hardware_encoder_available:
            print(f"Hardware encoding enabled (h264_videotoolbox)")
        else:
            print(f"Using software encoding (libx264)")
    return get_video_encoder_args(_hardware_encoder_available)


def extract_audio(input_path: str, output_path: str, sample_rate: int = 16000):
    """Extract audio from video as WAV for VAD processing."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-ar", str(sample_rate), "-ac", "1",
        "-acodec", "pcm_s16le",
        "-loglevel", "error", output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def transcribe_with_whisper(audio_path: str, model_name: str = "base") -> list[dict]:
    """Transcribe audio with Whisper to get word-level timestamps."""
    import whisper

    print(f"Transcribing with Whisper ({model_name})...")
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, word_timestamps=True)

    words = []
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            words.append({
                "word": word_info["word"].strip().lower(),
                "start": word_info["start"],
                "end": word_info["end"]
            })

    print(f"   Transcribed {len(words)} words")
    return words


def find_restart_phrases(words: list[dict], phrase: str = "cut cut") -> list[float]:
    """Find occurrences of the restart phrase in the transcript."""
    phrase_words = phrase.lower().split()
    phrase_len = len(phrase_words)

    restart_times = []

    for i in range(len(words) - phrase_len + 1):
        match = True
        for j, target_word in enumerate(phrase_words):
            actual_word = words[i + j]["word"].strip().lower()
            actual_word = ''.join(c for c in actual_word if c.isalnum())
            if actual_word != target_word:
                match = False
                break

        if match:
            phrase_end = words[i + phrase_len - 1]["end"]
            restart_times.append(phrase_end)
            print(f"   Found '{phrase}' at {phrase_end:.2f}s")

    return restart_times


def find_previous_checkpoint(restart_time: float, speech_segments: list[tuple[float, float]],
                             lookback: float = 10.0) -> float:
    """Find the previous silence gap (checkpoint) before the restart phrase."""
    for i, (seg_start, seg_end) in enumerate(speech_segments):
        if seg_start <= restart_time <= seg_end:
            if i > 0:
                return speech_segments[i - 1][1]
            else:
                return seg_start

    for i in range(len(speech_segments) - 1, -1, -1):
        if speech_segments[i][0] < restart_time:
            return speech_segments[i][0]

    return 0.0


def apply_restart_cuts(speech_segments: list[tuple[float, float]],
                       restart_times: list[float],
                       lookback: float = 10.0) -> list[tuple[float, float]]:
    """
    Apply restart cuts to the speech segments.

    For each "cut cut" phrase:
    - Remove the segment containing "cut cut" (the trigger phrase)
    - Remove the segment BEFORE it (where the mistake is)
    """
    if not restart_times:
        return speech_segments

    restart_times = sorted(restart_times)
    segments_to_remove = set()

    for restart_time in restart_times:
        for i, (seg_start, seg_end) in enumerate(speech_segments):
            if seg_start <= restart_time <= seg_end:
                segments_to_remove.add(i)
                print(f"   Removing segment {i} ({seg_start:.2f}s - {seg_end:.2f}s) - contains restart phrase")

                if i > 0:
                    prev_start, prev_end = speech_segments[i - 1]
                    segments_to_remove.add(i - 1)
                    print(f"   Removing segment {i-1} ({prev_start:.2f}s - {prev_end:.2f}s) - mistake before restart")
                break

    result_segments = []
    for i, segment in enumerate(speech_segments):
        if i not in segments_to_remove:
            result_segments.append(segment)

    return result_segments


def get_speech_timestamps_silero(audio_path: str, min_speech_duration: float = 0.25, min_silence_duration: float = 0.5):
    """Use Silero VAD to detect speech segments."""
    import torch

    model, utils = torch.hub.load(
        repo_or_dir='snakers4/silero-vad',
        model='silero_vad',
        force_reload=False,
        trust_repo=True
    )

    (get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = utils

    SAMPLE_RATE = 16000
    wav = read_audio(audio_path, sampling_rate=SAMPLE_RATE)

    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=SAMPLE_RATE,
        threshold=0.5,
        min_speech_duration_ms=int(min_speech_duration * 1000),
        min_silence_duration_ms=int(min_silence_duration * 1000),
        speech_pad_ms=100,
    )

    segments = []
    for ts in speech_timestamps:
        start_sec = ts['start'] / SAMPLE_RATE
        end_sec = ts['end'] / SAMPLE_RATE
        segments.append((start_sec, end_sec))

    return segments


def merge_close_segments(segments: list[tuple[float, float]], max_gap: float) -> list[tuple[float, float]]:
    """Merge segments that are very close together."""
    if not segments:
        return []

    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]

        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    return merged


def add_padding(segments: list[tuple[float, float]], padding_s: float, duration: float) -> list[tuple[float, float]]:
    """Add padding around segments and merge any overlaps."""
    if not segments:
        return []

    padded = []
    for start, end in segments:
        new_start = max(0, start - padding_s)
        new_end = min(duration, end + padding_s)
        padded.append((new_start, new_end))

    merged = [padded[0]]
    for start, end in padded[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return merged


def build_audio_filter_chain(enhance: bool = False) -> str:
    """Build FFmpeg audio filter chain for voice enhancement."""
    if not enhance:
        return ""

    filters = [
        AUDIO_FILTERS["highpass"],
        AUDIO_FILTERS["lowpass"],
        AUDIO_FILTERS["warmth"],
        AUDIO_FILTERS["presence"],
        AUDIO_FILTERS["compression"],
        AUDIO_FILTERS["loudnorm"],
    ]
    return ",".join(filters)


def build_video_filter_chain(lut_path: str = None) -> str:
    """Build FFmpeg video filter chain for color grading."""
    filters = []

    if lut_path:
        filters.append(f"lut3d='{lut_path}':interp=trilinear")

    return ",".join(filters) if filters else ""


def concatenate_segments(input_path: str, segments: list[tuple[float, float]], output_path: str,
                         enhance_audio: bool = False, lut_path: str = None):
    """Extract and concatenate video segments using hardware encoding when available."""

    print(f"Concatenating {len(segments)} segments...")
    if enhance_audio:
        print(f"Audio enhancement enabled")
    if lut_path:
        print(f"Color grading with LUT: {os.path.basename(lut_path)}")

    start_time = time.time()

    encoder_args = get_cached_encoder_args()
    audio_filter = build_audio_filter_chain(enhance_audio)
    video_filter = build_video_filter_chain(lut_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        segment_files = []

        for i, (start, end) in enumerate(segments):
            seg_path = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            duration = end - start

            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-ss", str(start),
                "-t", str(duration),
            ]

            if video_filter:
                cmd.extend(["-vf", video_filter])

            cmd.extend(encoder_args)

            if audio_filter:
                cmd.extend(["-af", audio_filter, "-c:a", "aac", "-b:a", "192k"])
            else:
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])

            cmd.extend(["-avoid_negative_ts", "make_zero", "-loglevel", "error", seg_path])
            subprocess.run(cmd, capture_output=True)
            segment_files.append(seg_path)

            if (i + 1) % 10 == 0 or (i + 1) == len(segments):
                elapsed = time.time() - start_time
                print(f"   Encoded {i+1}/{len(segments)} segments ({elapsed:.1f}s elapsed)")

        # Create concat file
        concat_path = os.path.join(tmpdir, "concat.txt")
        with open(concat_path, "w") as f:
            for seg_path in segment_files:
                f.write(f"file '{seg_path}'\n")

        # Concatenate
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path,
            "-c", "copy", "-loglevel", "error", output_path
        ]
        subprocess.run(cmd, capture_output=True)

    total_time = time.time() - start_time
    print(f"Output saved to {output_path} (total: {total_time:.1f}s)")


def get_duration(input_path: str) -> float:
    """Get video duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description="Jump cut editor using Silero VAD")
    parser.add_argument("input", help="Input video file")
    parser.add_argument("output", help="Output video file")
    parser.add_argument("--min-silence", type=float, default=MIN_SILENCE_DURATION,
                        help=f"Minimum silence duration to cut (default: {MIN_SILENCE_DURATION}s)")
    parser.add_argument("--min-speech", type=float, default=MIN_SPEECH_DURATION,
                        help=f"Minimum speech duration to keep (default: {MIN_SPEECH_DURATION}s)")
    parser.add_argument("--padding", type=int, default=PADDING_MS,
                        help=f"Padding around speech in ms (default: {PADDING_MS})")
    parser.add_argument("--merge-gap", type=float, default=0.3,
                        help="Merge segments closer than this (default: 0.3s)")
    parser.add_argument("--keep-start", action="store_true", default=True,
                        help="Always start from 0:00 (preserve intro, default: True)")
    parser.add_argument("--no-keep-start", action="store_false", dest="keep_start",
                        help="Allow cutting silence at the very beginning")
    parser.add_argument("--enhance-audio", action="store_true", default=False,
                        help="Apply audio enhancement (EQ, compression, loudness normalization)")
    parser.add_argument("--detect-restarts", action="store_true", default=False,
                        help=f"Detect '{RESTART_PHRASE}' and remove mistake segments")
    parser.add_argument("--restart-phrase", type=str, default=RESTART_PHRASE,
                        help=f"Phrase to trigger restart (default: '{RESTART_PHRASE}')")
    parser.add_argument("--whisper-model", type=str, default="base",
                        help="Whisper model size for restart detection (default: base)")
    parser.add_argument("--apply-lut", type=str, default=None,
                        help="Path to LUT file for color grading (.cube, .3dl, .dat, .m3d, .csp)")

    args = parser.parse_args()

    # Validate LUT file if provided
    if args.apply_lut:
        lut_path = Path(args.apply_lut)
        if not lut_path.exists():
            print(f"LUT file not found: {args.apply_lut}")
            return
        if lut_path.suffix.lower() not in SUPPORTED_LUT_FORMATS:
            print(f"Unsupported LUT format: {lut_path.suffix}")
            print(f"   Supported: {', '.join(SUPPORTED_LUT_FORMATS)}")
            return

    input_path = args.input
    output_path = args.output

    print(f"Jump Cut Editor (Silero VAD)")
    print(f"   Input: {input_path}")
    print(f"   Output: {output_path}")
    print()

    overall_start = time.time()

    # Get video duration
    duration = get_duration(input_path)
    print(f"Video duration: {duration:.2f}s")

    # Extract audio for VAD
    print(f"Extracting audio...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        extract_audio(input_path, audio_path)

        # Run Silero VAD
        print(f"Running Silero VAD (min_silence={args.min_silence}s, min_speech={args.min_speech}s)...")
        speech_segments = get_speech_timestamps_silero(
            audio_path,
            min_speech_duration=args.min_speech,
            min_silence_duration=args.min_silence
        )
        print(f"   Found {len(speech_segments)} speech segments")

        for i, (start, end) in enumerate(speech_segments[:5]):
            print(f"     {i+1}. {start:.2f}s - {end:.2f}s ({end-start:.2f}s)")
        if len(speech_segments) > 5:
            print(f"     ... and {len(speech_segments) - 5} more")

    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

    if not speech_segments:
        print("No speech detected!")
        return

    # Merge close segments
    speech_segments = merge_close_segments(speech_segments, args.merge_gap)
    print(f"After merging close segments: {len(speech_segments)} segments")

    # Add padding
    padding_s = args.padding / 1000
    speech_segments = add_padding(speech_segments, padding_s, duration)
    print(f"After adding {args.padding}ms padding: {len(speech_segments)} segments")

    # Detect restart phrases
    if args.detect_restarts:
        print(f"\nDetecting restart phrases ('{args.restart_phrase}')...")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            whisper_audio_path = tmp.name

        try:
            extract_audio(input_path, whisper_audio_path, sample_rate=16000)
            words = transcribe_with_whisper(whisper_audio_path, model_name=args.whisper_model)
            restart_times = find_restart_phrases(words, phrase=args.restart_phrase)

            if restart_times:
                print(f"   Found {len(restart_times)} restart phrase(s)")
                speech_segments = apply_restart_cuts(speech_segments, restart_times, RESTART_LOOKBACK)
                print(f"   After restart cuts: {len(speech_segments)} segments")
            else:
                print(f"   No restart phrases found")
        finally:
            if os.path.exists(whisper_audio_path):
                os.remove(whisper_audio_path)

    # Keep start: force first segment to start at 0:00
    if args.keep_start and speech_segments and speech_segments[0][0] > 0:
        first_start, first_end = speech_segments[0]
        speech_segments[0] = (0.0, first_end)
        print(f"Preserving intro: extended first segment to start at 0:00")

    # Concatenate
    concatenate_segments(input_path, speech_segments, output_path,
                         enhance_audio=args.enhance_audio, lut_path=args.apply_lut)

    # Stats
    new_duration = get_duration(output_path)
    removed = duration - new_duration
    overall_time = time.time() - overall_start

    print()
    print(f"Stats:")
    print(f"   Original: {duration:.2f}s")
    print(f"   New: {new_duration:.2f}s")
    print(f"   Removed: {removed:.2f}s ({100*removed/duration:.1f}%)")
    print(f"   Total processing time: {overall_time:.1f}s")


if __name__ == "__main__":
    main()
