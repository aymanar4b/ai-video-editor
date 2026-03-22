#!/usr/bin/env python3
"""
Insert Swivel Teaser into Video

Inserts a "swivel teaser" at a specified point in a video - a fast-forward
preview of video content starting at 1 minute with 3D rotation effects.
Original audio continues playing throughout.

See: directives/pan_3d_transition.md for effect parameters.

Usage:
    # Insert 5-second swivel teaser at 3 seconds (previews from 1:00 to end)
    python execution/insert_3d_transition.py input.mp4 output.mp4

    # Custom teaser content start point
    python execution/insert_3d_transition.py input.mp4 output.mp4 \
        --teaser-start 90  # Preview starts at 1:30

    # With background image
    python execution/insert_3d_transition.py input.mp4 output.mp4 \
        --bg-image .tmp/background.png

Timeline Result:
    Video: [0-3s original] [3-8s swivel teaser showing content from 1:00 onwards] [8s+ original]
    Audio: [original audio plays continuously throughout]
"""

import subprocess
import tempfile
import os
import argparse
import sys
from pathlib import Path

# Add execution directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from pan_3d_transition import create_transition, get_video_info
from jump_cut_vad import get_cached_encoder_args

DEFAULT_INSERT_AT = 3.0
DEFAULT_DURATION = 5.0
DEFAULT_TEASER_START = 60.0
MAX_PLAYBACK_RATE = 100.0


def composite_with_transition(
    input_path: str,
    output_path: str,
    insert_at: float = DEFAULT_INSERT_AT,
    duration: float = DEFAULT_DURATION,
    teaser_start: float = DEFAULT_TEASER_START,
    bg_color: str = "#2d3436",
    bg_image: str = None,
) -> None:
    """
    Insert a swivel teaser into video while preserving original audio.

    The swivel teaser shows video content from teaser_start to end,
    compressed into the specified duration with 3D rotation effects.
    """
    info = get_video_info(input_path)
    total_duration = info["duration"]

    if teaser_start >= total_duration:
        raise ValueError(f"Teaser start ({teaser_start}s) must be less than video duration ({total_duration}s)")

    # Calculate content to preview
    available_content = total_duration - teaser_start
    uncapped_rate = available_content / duration

    if uncapped_rate > MAX_PLAYBACK_RATE:
        playback_rate = MAX_PLAYBACK_RATE
        teaser_content = duration * MAX_PLAYBACK_RATE
        print(f"   Capping speed at {MAX_PLAYBACK_RATE}x (would have been {uncapped_rate:.1f}x)")
    else:
        playback_rate = uncapped_rate
        teaser_content = available_content

    print(f"Insert Swivel Teaser")
    print(f"   Input: {input_path}")
    print(f"   Insert at: {insert_at}s")
    print(f"   Teaser duration: {duration}s")
    print(f"   Teaser content: {teaser_start}s -> {total_duration:.1f}s ({teaser_content:.1f}s at {playback_rate:.1f}x speed)")
    print()

    if insert_at + duration > total_duration:
        raise ValueError(f"Insert point + duration ({insert_at + duration}s) exceeds video duration ({total_duration}s)")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: Generate the swivel teaser
        transition_path = os.path.join(tmpdir, "transition.mp4")
        print(f"Generating swivel teaser...")

        create_transition(
            input_path=input_path,
            output_path=transition_path,
            start=teaser_start,
            source_duration=teaser_content,
            output_duration=duration,
            playback_rate=playback_rate,
            bg_color=bg_color,
            bg_image=bg_image,
        )

        # Step 2: Overlay transition onto original video
        # This preserves the original timeline and audio sync by replacing
        # only the video frames during the teaser window, rather than
        # splitting/re-encoding/concatenating which causes drift.
        print(f"\nOverlaying transition onto original video...")

        encoder_args = get_cached_encoder_args()

        # Use FFmpeg overlay filter to replace video during teaser window
        # - Input 0: original video (keeps audio and timeline intact)
        # - Input 1: transition video (overlaid during insert_at to insert_at+duration)
        insert_end = insert_at + duration

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", transition_path,
            "-filter_complex",
            (
                f"[1:v]setpts=PTS-STARTPTS[trans];"
                f"[0:v][trans]overlay="
                f"enable='between(t,{insert_at},{insert_end})':"
                f"shortest=1[outv]"
            ),
            "-map", "[outv]",
            "-map", "0:a",
            "-c:a", "copy",
        ] + encoder_args + [
            "-loglevel", "error",
            output_path
        ]
        subprocess.run(cmd, check=True)

    print(f"\nOutput saved to {output_path}")
    print(f"   Timeline: [0-{insert_at}s] [swivel teaser {duration}s] [{insert_at+duration}s-end]")
    print(f"   Teaser shows: {teaser_start}s -> {total_duration:.1f}s ({teaser_content:.1f}s at {playback_rate:.1f}x speed)")
    print(f"   Audio: Original audio preserved (overlay method, no re-sync needed)")


def main():
    parser = argparse.ArgumentParser(
        description="Insert 3D transition into video while preserving audio"
    )
    parser.add_argument("input", help="Input video file")
    parser.add_argument("output", help="Output video file")
    parser.add_argument("--insert-at", type=float, default=DEFAULT_INSERT_AT,
                        help=f"Insert point in seconds (default: {DEFAULT_INSERT_AT})")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                        help=f"Transition duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--teaser-start", type=float, default=DEFAULT_TEASER_START,
                        help=f"Where to start sourcing teaser content (default: {DEFAULT_TEASER_START}s = 1 minute)")
    parser.add_argument("--bg-color", type=str, default="#2d3436",
                        help="Background color (hex, default: #2d3436)")
    parser.add_argument("--bg-image", type=str, default=None,
                        help="Background image path (overrides --bg-color)")

    args = parser.parse_args()

    composite_with_transition(
        input_path=args.input,
        output_path=args.output,
        insert_at=args.insert_at,
        duration=args.duration,
        teaser_start=args.teaser_start,
        bg_color=args.bg_color,
        bg_image=args.bg_image,
    )


if __name__ == "__main__":
    main()
