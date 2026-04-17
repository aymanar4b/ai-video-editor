#!/usr/bin/env python3
"""
Recreate YouTube thumbnails with your face using Nano Banana Pro (Gemini).

This script:
1. Takes a YouTube URL or thumbnail image
2. Analyzes face direction in the source thumbnail
3. Finds the best-matching reference photo by face pose
4. Recreates it with your face swapped in
5. Generates 3 variations by default
6. Supports edit passes for refinements

Usage:
    # Basic recreation from YouTube URL
    python recreate_thumbnails.py --youtube "https://youtube.com/watch?v=VIDEO_ID"

    # From local image
    python recreate_thumbnails.py --source "path/to/thumbnail.jpg"

    # Edit pass (refine a generated thumbnail)
    python recreate_thumbnails.py --edit "path/to/generated.png" --prompt "change text to AGENTIC FLOWS"
"""

import argparse
import base64
import io
import math
import os
import re
import signal
import sys
from pathlib import Path
from datetime import datetime

import cv2
import mediapipe as mp
import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image, ImageFilter
from google import genai
from google.genai import types
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions

load_dotenv()

# Constants
REFERENCE_PHOTOS_DIR = Path(__file__).parent.parent / ".tmp" / "reference_photos"
OUTPUT_DIR = Path(__file__).parent.parent / ".tmp" / "thumbnails"
MODEL_PATH = Path(__file__).parent.parent / "models" / "face_landmarker.task"
API_KEY = os.getenv("NANO_BANANA_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # For GPT Image 1.5 (optional provider)

MODEL = "gemini-3-pro-image-preview"
ANALYSIS_MODEL = "gemini-2.5-pro"  # For analyzing source thumbnails (avoids image-gen model's content filter)
OPENAI_IMAGE_MODEL = "gpt-image-1.5"  # OpenAI alternate provider

THUMB_SIZE = (1280, 720)
REF_SIZE = (768, 768)
SWIPE_DIR = Path(__file__).parent / "swipe_examples"
API_TIMEOUT = 120  # seconds per API call


def _api_call_with_timeout(client_obj, model, contents, config, timeout=API_TIMEOUT):
    """Call Gemini API with a signal-based timeout to prevent hangs."""
    def _handler(signum, frame):
        raise TimeoutError(f"API call timed out after {timeout}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        response = client_obj.models.generate_content(
            model=model, contents=contents, config=config,
        )
        signal.alarm(0)
        return response
    except TimeoutError:
        signal.alarm(0)
        raise
    finally:
        signal.signal(signal.SIGALRM, old)

def _openai_generate_image(
    prompt: str,
    input_images: list,
    input_fidelity: str = "high",
    quality: str = "high",
    size: str = "1536x1024",
    timeout: int = 180,
):
    """Generate an image via OpenAI GPT Image 1.5 (/v1/images/edits).

    Accepts the same PIL Image objects we hand Gemini; serializes them to
    PNG bytes and calls the OpenAI images.edit endpoint with up to 16 input
    images. Returns a PIL Image normalized to 1280x720 16:9, or None on
    failure (missing key, quota, content filter, network, parse error).

    Uses `input_fidelity="high"` which is the key control for replicate mode:
    it biases the model toward preserving the source image's layout and
    composition when editing.
    """
    if not OPENAI_API_KEY:
        print("  OpenAI: OPENAI_API_KEY not set, skipping")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        print("  OpenAI: openai SDK not installed (pip install openai)")
        return None

    try:
        oai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=timeout)

        # Serialize each PIL image to an in-memory PNG with a filename
        # (OpenAI SDK inspects the filename extension to set MIME type).
        image_files = []
        for i, pil_img in enumerate(input_images[:16]):  # cap at 16 per API limit
            if pil_img is None:
                continue
            buf = io.BytesIO()
            # Convert to RGB to avoid RGBA issues
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            pil_img.save(buf, format="PNG")
            buf.seek(0)
            buf.name = f"image_{i}.png"  # SDK needs this for MIME detection
            image_files.append(buf)

        if not image_files:
            print("  OpenAI: no input images provided")
            return None

        print(f"  OpenAI: calling gpt-image-1.5 with {len(image_files)} image(s), "
              f"quality={quality}, input_fidelity={input_fidelity}, size={size}")

        response = oai_client.images.edit(
            model=OPENAI_IMAGE_MODEL,
            image=image_files,
            prompt=prompt,
            size=size,
            input_fidelity=input_fidelity,
            quality=quality,
        )

        if not response.data:
            print("  OpenAI: response.data was empty")
            return None

        b64 = response.data[0].b64_json
        if not b64:
            # Some responses return a URL instead
            url = getattr(response.data[0], "url", None)
            if url:
                import requests
                img_bytes = requests.get(url, timeout=30).content
                return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))
            print("  OpenAI: no b64_json and no url in response")
            return None

        img_bytes = base64.b64decode(b64)
        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))

    except Exception as e:
        print(f"  OpenAI error: {e}")
        return None


# ── TikScale Thumbnail Design Playbook (condensed) ──────────────────────────
PLAYBOOK = """TIKSCALE THUMBNAIL DESIGN PLAYBOOK — MANDATORY RULES:

1. GLANCE TEST: Shrink to mobile size (120px wide). If the core message isn't clear in under 1 second, the design FAILS. Design for the glance, not the stare.

2. THREE ELEMENTS MAX: Every thumbnail has a MAXIMUM of 3 design elements total. Pick from: face with emotion, compelling graphic, large text/numbers/$, aesthetic imagery, or color contrast. NEVER more than 3. Two often works better than three.

3. DESIRE LOOP: Before designing, answer: what does the viewer WANT when they click? (Make money, save time, avoid pain.) The thumbnail must visually activate that desire. Lead with the outcome — a revenue number, a result, a transformation.

4. TITLE-THUMBNAIL SYNERGY: Title and thumbnail are a TEAM. The thumbnail adds an emotional/visual layer the title doesn't have. NEVER repeat the title text. If title says "How I Built a $100k Business", thumbnail text should be "From Scratch" or show a revenue screenshot — NOT "$100k Business".

5. FACE EXPRESSION MUST MATCH THE VIDEO TONE:
   - Shocked/surprised → revelation content, counterintuitive findings
   - Confident/serious → authority content, strategy breakdowns
   - Smiling/happy → success stories, results, transformation proof
   - Concerned/intense → warning content, "stop doing this" videos
   NOTE: Exaggerated open-mouth shock is DEAD for business channels. Keep it credible.

6. TEXT RULES:
   - Text is the HIGHEST CONTRAST element on the page
   - 4 words MAXIMUM. The thumbnail is not a place for sentences.
   - If it looks too big in the design file, it's probably right at thumbnail size
   - SPELL EVERY WORD CORRECTLY — double-check each letter
   - White text on dark backgrounds, or dark text on bright backgrounds

7. COLOR CONTRAST:
   - Vivid, high-saturation colors that POP against the background
   - If the niche uses dark backgrounds, consider a light thumbnail to stand out
   - Orange vs blue = highest contrast combination
   - Green = good, Red = bad (universal)
   - NOTHING in the bottom-right corner (YouTube timestamp covers it)

8. SHADOWS FOR SEPARATION: Add drop shadow behind the subject to lift them off the background. Use dark overlay/gradient behind text for readability. This creates professional depth.

9. COMPOSITION TYPES:
   - Symmetrical: subject centered, both sides balanced — use when subject IS the focus
   - Asymmetrical (Rule of Thirds): subject at 1/3, text/graphic in remaining 2/3 — most common, most flexible
   - A/B Split: screen divided showing before/after or problem/solution — use for transformation content

10. THUMBNAIL STYLES THAT PERFORM:
    - Results-Forward: lead with a big number ($47k, 1M views). Number is dominant, impossible to miss.
    - Counterintuitive Statement: 4-word text challenging conventional wisdom ("Stop Using Calendly"). Simple background, strong contrast.
    - Before/After Split: pain state vs solution state side by side.
    - Authority/Credibility: large number, recognizable logo, or impressive stat front and center.
    - Diary of a CEO style: white text, red highlight word, dark background — extremely high contrast, text-first.

11. COGNITIVE DISSONANCE: Statements that challenge common beliefs create strong click pull. "You don't need more leads", "Cold email is killing you", "Posting more is wrong". The viewer's brain wants to resolve the contradiction.

QUALITY CHECKLIST:
☐ Passes glance test at mobile size in under 1 second
☐ Maximum 3 elements, each identifiable at mobile size
☐ Text is highest contrast, 4 words max, CORRECTLY SPELLED
☐ Face expression matches video tone
☐ Thumbnail does NOT repeat the title — it adds something new
☐ Colors are vivid and high-saturation, not muted
☐ Shadow separation between subject and background
☐ Nothing in bottom-right corner"""


def load_swipe_examples(
    only_files: list[str] | None = None,
    extra_paths: list[Path] | None = None,
) -> tuple[list[Image.Image], list[Image.Image]]:
    """Load swipe file thumbnails.

    Returns (universal_examples, client_examples):
    - Universal swipes are pixelated to bypass public-figure content filters.
    - Client swipes are sent at full quality — they're the client's own
      thumbnails and need to preserve exact style details.
    """
    # ── Universal swipes (pixelated) ──
    universal = []
    individual_dir = SWIPE_DIR / "individual"
    if individual_dir.exists():
        thumbs = sorted(individual_dir.glob("thumb_*.png"))
        if only_files is not None:
            allowed = set(only_files)
            thumbs = [t for t in thumbs if t.name in allowed]
        for p in thumbs:
            try:
                img = Image.open(p)
                img.thumbnail((768, 768), Image.Resampling.LANCZOS)
                w, h = img.size
                pw = max(160, w // 5)
                ph = max(90, h // 5)
                small = img.resize((pw, ph), Image.Resampling.NEAREST)
                img = small.resize((w, h), Image.Resampling.NEAREST)
                universal.append(img)
            except Exception:
                continue

    # ── Client swipes (full quality) ──
    client = []
    if extra_paths:
        for p in extra_paths:
            try:
                if p and Path(p).exists():
                    img = Image.open(Path(p))
                    img.thumbnail((768, 768), Image.Resampling.LANCZOS)
                    client.append(img)
            except Exception:
                continue

    print(f"Loaded swipe files: {len(universal)} universal (pixelated), {len(client)} client (full quality)")
    return universal, client


def analyze_swipe_style(client_swipes: list[Image.Image]) -> str:
    """Ask the model to describe the typography and visual style of client swipes.

    Returns a concrete style description that can be injected into generation prompts
    so the model knows exactly what fonts, colors, and layout to replicate.
    """
    if not client_swipes:
        return ""

    api_client = genai.Client(api_key=API_KEY)
    contents = []
    contents.append(f"Analyze these {len(client_swipes)} YouTube thumbnails from the SAME channel. They share a consistent visual style. Describe it precisely:")
    for img in client_swipes:
        contents.append(img)

    contents.append("""Describe the EXACT visual style of these thumbnails in a structured format. Be SPECIFIC — don't say "bold font", say exactly what kind (e.g. "extra-bold condensed sans-serif, all caps, with black outline/stroke").

Respond in EXACTLY this format (fill in each line):

FONT_STYLE: [exact font description — weight, width, case, serif/sans-serif]
TEXT_EFFECTS: [outline, stroke, shadow, glow, 3D, gradient fill — describe exactly]
TEXT_COLORS: [list the exact text colors used, e.g. "white with black outline, red accent text"]
TEXT_PLACEMENT: [where text appears — top, bottom, left, right, center, overlapping person]
TEXT_SIZE: [relative to frame — how much of the frame does text occupy]
WORD_COUNT: [typical number of words per thumbnail]
BACKGROUND_STYLE: [solid color, gradient, photo, composite — describe exactly]
BACKGROUND_COLORS: [dominant background colors]
PERSON_STYLE: [cutout on solid bg, environmental, studio, how much of frame they fill]
PERSON_PLACEMENT: [left, right, center, how positioned relative to text]
GRAPHIC_ELEMENTS: [arrows, icons, emojis, borders, shapes, overlays — list all recurring elements]
COLOR_PALETTE: [the 3-4 dominant colors across all thumbnails]
OVERALL_MOOD: [one sentence describing the energy/vibe]""")

    try:
        response = _api_call_with_timeout(api_client, MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT"]),
            timeout=30)
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    print(f"Style analysis:\n{part.text[:500]}")
                    return part.text
    except Exception as e:
        print(f"Style analysis failed: {e}")
    return ""


def normalize_to_thumbnail(img: Image.Image) -> Image.Image:
    """Resize/crop output to exactly 1280x720 without distorting proportions."""
    target_w, target_h = THUMB_SIZE
    target_ratio = target_w / target_h  # 1.778

    w, h = img.size
    current_ratio = w / h

    if abs(current_ratio - target_ratio) < 0.01:
        # Already correct ratio, just resize
        return img.resize(THUMB_SIZE, Image.Resampling.LANCZOS)

    # Crop to 16:9, then resize
    if current_ratio > target_ratio:
        # Too wide — crop sides (center)
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        # Too tall — crop from bottom to keep the head/face visible at top
        new_h = int(w / target_ratio)
        img = img.crop((0, 0, w, new_h))

    return img.resize(THUMB_SIZE, Image.Resampling.LANCZOS)


def get_face_pose(image: Image.Image) -> tuple[float, float] | None:
    """Extract yaw and pitch angles from a face in a PIL Image using MediaPipe."""
    img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        num_faces=1,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=True,
    )

    with FaceLandmarker.create_from_options(options) as landmarker:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                            data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        result = landmarker.detect(mp_image)

        if not result.face_landmarks:
            return None

        landmarks = result.face_landmarks[0]

        # Use 6 key landmarks for pose estimation via solvePnP
        model_points = np.array([
            (0.0, 0.0, 0.0),        # nose tip
            (0.0, -330.0, -65.0),    # chin
            (-225.0, 170.0, -135.0), # left eye outer
            (225.0, 170.0, -135.0),  # right eye outer
            (-150.0, -150.0, -125.0),# left mouth corner
            (150.0, -150.0, -125.0), # right mouth corner
        ], dtype=np.float64)

        landmark_indices = [1, 152, 33, 263, 61, 291]
        image_points = np.array([
            (landmarks[i].x * w, landmarks[i].y * h)
            for i in landmark_indices
        ], dtype=np.float64)

        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1],
        ], dtype=np.float64)

        dist_coeffs = np.zeros((4, 1))

        success, rotation_vec, translation_vec = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE
        )

        if not success:
            return None

        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        proj_matrix = np.hstack((rotation_mat, translation_vec))
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(proj_matrix)

        pitch = float(euler_angles[0][0])
        yaw = float(euler_angles[1][0])

        yaw = max(-90, min(90, yaw))
        pitch = max(-45, min(45, pitch))

        return (yaw, pitch)


def get_face_ratios(image: Image.Image) -> list[float] | None:
    """Extract normalized face geometry ratios from a PIL Image.

    Returns a vector of distance ratios between key landmarks that are
    relatively stable across poses/expressions and unique to each person
    (eye spacing, nose-to-chin, face width, etc.).
    """
    img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        num_faces=1,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )

    try:
        with FaceLandmarker.create_from_options(options) as landmarker:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            result = landmarker.detect(mp_image)

            if not result.face_landmarks:
                return None

            lm = result.face_landmarks[0]

            def dist(a, b):
                return math.sqrt((lm[a].x - lm[b].x)**2 + (lm[a].y - lm[b].y)**2)

            # Key structural distances
            eye_dist = dist(33, 263)        # left eye outer to right eye outer
            nose_to_chin = dist(1, 152)     # nose tip to chin
            face_width = dist(234, 454)     # left cheek to right cheek
            nose_width = dist(48, 278)      # left nostril to right nostril
            mouth_width = dist(61, 291)     # mouth corners
            forehead_to_nose = dist(10, 1)  # forehead to nose tip
            eye_to_mouth_l = dist(33, 61)   # left eye to left mouth
            eye_to_mouth_r = dist(263, 291) # right eye to right mouth

            # Normalize everything by eye distance (most stable reference)
            if eye_dist < 0.001:
                return None

            ratios = [
                nose_to_chin / eye_dist,
                face_width / eye_dist,
                nose_width / eye_dist,
                mouth_width / eye_dist,
                forehead_to_nose / eye_dist,
                eye_to_mouth_l / eye_dist,
                eye_to_mouth_r / eye_dist,
            ]
            return ratios
    except Exception:
        return None


def face_similarity(ratios_a: list[float], ratios_b: list[float]) -> float:
    """Compare two face ratio vectors. Returns 0-1 similarity (1 = identical)."""
    if len(ratios_a) != len(ratios_b):
        return 0.0
    diffs = [abs(a - b) for a, b in zip(ratios_a, ratios_b)]
    avg_diff = sum(diffs) / len(diffs)
    # Map to 0-1: diff of 0 = 1.0, diff of 0.5+ = ~0
    return max(0.0, 1.0 - avg_diff * 4)


def check_face_match(generated: Image.Image, reference_photos: list[Image.Image],
                     threshold: float = 0.05) -> bool:
    """Check if the face in the generated thumbnail matches the reference photos.

    Uses 2D facial landmark ratios which are POSE-SENSITIVE — if the generated image
    has a very different head angle from the refs (3/4 vs front), ratios diverge even
    for the same person. We treat that case as "can't compare" and defer to the
    semantic verify_and_fix pass rather than forcing retries on a broken signal.

    Returns True if the face matches OR if we can't reliably compare. Returns False
    only when we can confidently say the face is wrong.
    """
    gen_ratios = get_face_ratios(generated)
    if gen_ratios is None:
        return True  # Can't detect face in generated, skip check

    ref_scores = []
    for ref in reference_photos:
        ref_ratios = get_face_ratios(ref)
        if ref_ratios:
            score = face_similarity(gen_ratios, ref_ratios)
            ref_scores.append(score)

    if not ref_scores:
        return True  # Can't detect faces in refs, skip check

    best_score = max(ref_scores)
    print(f"  Face match score: {best_score:.2f} (threshold: {threshold})")

    # A score of exactly 0.0 means the landmark-ratio distance saturated the
    # similarity clamp — almost always a pose mismatch, not an identity mismatch.
    # Trust the semantic verify pass instead of forcing retries.
    if best_score == 0.0:
        print("  (Score 0.0 → likely pose mismatch, deferring to verify_and_fix)")
        return True

    return best_score >= threshold


def anonymize_source(image: Image.Image, level: int = 0) -> Image.Image:
    """Anonymize source thumbnail with escalating intensity.

    Level 0: Face-only blur (forehead-to-chin). Best detail preservation.
    Level 1: Face blur + moderate full-image blur to wash out identifying text.
    Level 2: Heavy center pixelation. Loses detail but reliably passes filters.
    """
    w, h = image.size
    result = image.copy()

    if level >= 2:
        # Heavy pixelation on center half — nuclear option
        x1, y1 = w // 4, 0
        x2, y2 = 3 * w // 4, h
        region = result.crop((x1, y1, x2, y2))
        pw, ph = region.size
        small = region.resize((20, 20), Image.Resampling.NEAREST)
        result.paste(small.resize((pw, ph), Image.Resampling.NEAREST), (x1, y1))
        return result

    # Level 0 and 1: face detection + blur
    img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    ih, iw = img_cv.shape[:2]

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        num_faces=5,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )

    try:
        with FaceLandmarker.create_from_options(options) as landmarker:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                data=cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
            detection = landmarker.detect(mp_image)

            if not detection.face_landmarks:
                cx = w // 2
                strip_w = w // 3
                region = result.crop((cx - strip_w // 2, 0, cx + strip_w // 2, h))
                result.paste(region.filter(ImageFilter.GaussianBlur(radius=30)),
                             (cx - strip_w // 2, 0))
            else:
                for landmarks in detection.face_landmarks:
                    xs = [lm.x * iw for lm in landmarks]
                    ys = [lm.y * ih for lm in landmarks]

                    face_w = max(xs) - min(xs)
                    face_h = max(ys) - min(ys)
                    pad_x = face_w * 0.3
                    pad_y = face_h * 0.35

                    fx1 = max(0, int(min(xs) - pad_x))
                    fy1 = max(0, int(min(ys) - pad_y))
                    fx2 = min(w, int(max(xs) + pad_x))
                    fy2 = min(h, int(max(ys) + pad_y))

                    if fx2 <= fx1 or fy2 <= fy1:
                        continue

                    face_region = result.crop((fx1, fy1, fx2, fy2))
                    blurred = face_region.filter(ImageFilter.GaussianBlur(radius=30))
                    result.paste(blurred, (fx1, fy1))

    except Exception:
        cx = w // 2
        strip_w = w // 3
        region = result.crop((cx - strip_w // 2, 0, cx + strip_w // 2, h))
        result.paste(region.filter(ImageFilter.GaussianBlur(radius=30)),
                     (cx - strip_w // 2, 0))

    # Level 1: also blur entire image to wash out identifying text
    if level >= 1:
        result = result.filter(ImageFilter.GaussianBlur(radius=10))

    return result


def find_best_reference(target_yaw: float, target_pitch: float) -> Path | None:
    """Find the reference photo with the closest matching face pose."""
    extensions = {".jpg", ".jpeg", ".png", ".webp"}
    refs = [
        f for f in REFERENCE_PHOTOS_DIR.iterdir()
        if f.suffix.lower() in extensions and f.name.startswith("nick_yaw")
    ]

    if not refs:
        return None

    pattern = r"nick_yaw(L|R)?(\d+|0)_pitch(U|D)?(\d+|0)"

    best_match = None
    best_distance = float("inf")

    for ref in refs:
        match = re.match(pattern, ref.stem)
        if not match:
            continue

        yaw_dir, yaw_val, pitch_dir, pitch_val = match.groups()

        yaw = int(yaw_val) if yaw_val != "0" else 0
        if yaw_dir == "L":
            yaw = -yaw

        pitch = int(pitch_val) if pitch_val != "0" else 0
        if pitch_dir == "D":
            pitch = -pitch

        distance = math.sqrt((target_yaw - yaw) ** 2 + (target_pitch - pitch) ** 2)

        if distance < best_distance:
            best_distance = distance
            best_match = ref

    return best_match


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_youtube_thumbnail(video_id: str) -> Image.Image | None:
    """Download YouTube thumbnail in best available quality."""
    qualities = ['maxresdefault', 'sddefault', 'hqdefault', 'mqdefault']

    for quality in qualities:
        url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                img = Image.open(io.BytesIO(response.content))
                if img.size[0] > 200:
                    print(f"Downloaded thumbnail: {quality} ({img.size})")
                    return img
        except Exception:
            continue

    return None


def download_image(url: str) -> Image.Image:
    """Download image from URL."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content))


def load_reference_photo(path: Path) -> Image.Image | None:
    """Load and resize a single reference photo, preserving aspect ratio."""
    try:
        img = Image.open(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # Center-crop to square first to avoid distorting face proportions
        w, h = img.size
        if w != h:
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
        img = img.resize(REF_SIZE, Image.Resampling.LANCZOS)
        print(f"Loaded reference: {path.name} ({w}x{h} -> {REF_SIZE[0]}x{REF_SIZE[0]})")
        return img
    except Exception as e:
        print(f"Warning: Could not load {path}: {e}")
        return None


def load_reference_photos(max_photos: int = 3, specific_path: Path | None = None,
                          only_files: list[str] | None = None) -> list[Image.Image]:
    """Load reference photos for face consistency.

    If only_files is provided, only load those specific filenames.
    """
    photos = []

    if not REFERENCE_PHOTOS_DIR.exists():
        print(f"Warning: Reference photos not found at {REFERENCE_PHOTOS_DIR}")
        return photos

    extensions = {".jpg", ".jpeg", ".png", ".webp"}

    if only_files is not None:
        # Load only the selected files
        for name in only_files:
            f = REFERENCE_PHOTOS_DIR / name
            if f.exists() and f.suffix.lower() in extensions:
                ref = load_reference_photo(f)
                if ref:
                    photos.append(ref)
                    if len(photos) >= max_photos:
                        break
        return photos

    if specific_path and specific_path.exists():
        ref = load_reference_photo(specific_path)
        if ref:
            photos.append(ref)
            if max_photos == 1:
                return photos

    photo_files = sorted([
        f for f in REFERENCE_PHOTOS_DIR.iterdir()
        if f.suffix.lower() in extensions and f != specific_path
    ])

    for photo_file in photo_files[:max_photos - len(photos)]:
        ref = load_reference_photo(photo_file)
        if ref:
            photos.append(ref)

    return photos


def enhance_prompt(source_image: Image.Image, user_prompt: str, video_title: str = "") -> str:
    """Use Gemini 2.5 Pro to rewrite a casual user prompt into precise image generation instructions.

    Analyzes the source thumbnail and converts natural language into structured
    KEEP/REMOVE/CHANGE/ADD directives that the image model follows more reliably.
    """
    if not user_prompt.strip():
        return ""

    client = genai.Client(api_key=API_KEY)

    thumb = source_image.copy()
    thumb.thumbnail((640, 360), Image.Resampling.LANCZOS)

    contents = [
        "Here is the source YouTube thumbnail that will be recreated:",
        thumb,
        f"""The user wants to modify this thumbnail with these instructions:
\"{user_prompt}\"
{f'Video title: "{video_title}"' if video_title else ''}

Your job: Rewrite ONLY what the user asked for into precise, structured directives for an image generation model. The image model is literal — it needs exact specifications.

CRITICAL RULES:
- ONLY include changes the user explicitly asked for. Do NOT invent, assume, or infer changes they didn't mention.
- If the user said "add X", only add X. Do NOT also remove or change other things unless the user said to.
- If the user's instructions are already clear and specific, just reformat them — don't embellish.
- Specify positions (top-left, center, etc.), colors, and sizes where the user was vague.
- Keep it concise — no explanations, no commentary, just directives.
- Do NOT repeat sections. Output each section exactly ONCE.

Output format — use ONLY these sections (skip any that don't apply):

CHANGE: [what to modify and exactly how — only things the user mentioned]
ADD: [new elements the user asked to include, with position/size/color]
TEXT: [exact text content, position, font style, color — only if the user specified text changes]
LAYOUT: [spatial arrangement — only if user mentioned layout changes]"""
    ]

    try:
        response = _api_call_with_timeout(
            client, ANALYSIS_MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT"]),
            timeout=30,
        )
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    enhanced = part.text.strip()
                    # Remove "Downloaded thumbnail..." debug line if present
                    lines = enhanced.split('\n')
                    lines = [l for l in lines if not l.strip().startswith('Downloaded thumbnail')]
                    if lines and lines[0].strip().startswith('Enhanced prompt'):
                        lines = lines[1:]
                    enhanced = '\n'.join(lines).strip()
                    # Remove duplicate paragraphs/lines
                    seen = set()
                    deduped = []
                    for line in enhanced.split('\n'):
                        key = line.strip()
                        if not key:
                            deduped.append(line)
                            continue
                        if key not in seen:
                            seen.add(key)
                            deduped.append(line)
                    enhanced = '\n'.join(deduped).strip()
                    print(f"Enhanced prompt:\n{enhanced}\n")
                    return enhanced
    except Exception as e:
        print(f"Prompt enhancement failed ({e}), using original prompt")

    return user_prompt


BLOCKED_SENTINEL = "BLOCKED"

def recreate_thumbnail(
    source_image: Image.Image,
    reference_photos: list[Image.Image],
    style_variation: str = "purple/teal gradient",
    additional_prompt: str = "",
    video_title: str = "",
    swipe_examples: list[Image.Image] | None = None,
    anon_level: int = 0,
    provider: str = "gemini",
    openai_quality: str = "high",
) -> Image.Image | str | None:
    """Recreate a thumbnail with the client as the featured person.

    Blurs eyes in the source thumbnail to bypass content filters on public figures,
    while preserving expression, pose, and layout for accurate replication.

    `swipe_examples` is accepted but intentionally ignored in replicate mode —
    the source image is the definitive layout reference, and adding swipe files
    causes the model to blend compositions.

    `provider` picks the image generation backend: "gemini" (default, current
    behavior) or "openai" (GPT Image 1.5 via /v1/images/edits with high
    input_fidelity for strong composition preservation).
    """
    del swipe_examples  # intentionally unused in replicate mode
    client = genai.Client(api_key=API_KEY)

    thumb = source_image.copy()
    thumb.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    # For OpenAI, skip anonymization on the first pass — OpenAI's content filter
    # is less aggressive about public figures and we want to see its natural
    # output. For Gemini, always anonymize at the requested level.
    if provider == "openai":
        thumb_anon = thumb
        print(f"\nSource thumbnail passed to OpenAI without anonymization")
    else:
        thumb_anon = anonymize_source(thumb, level=anon_level)
        anon_labels = {0: "face blur", 1: "face blur + text wash", 2: "heavy pixelation"}
        print(f"\nAnonymized source thumbnail ({anon_labels.get(anon_level, 'face blur')})")

    contents = []
    for i, ref in enumerate(reference_photos):
        contents.append(f"Reference photo {i+1} of the client — ONLY use this for the person's face and body appearance. IGNORE the background, setting, and environment in this photo:")
        contents.append(ref)

    # Source thumbnail goes LAST (right before the prompt) so it has the strongest
    # attention weight. In replicate mode the source IS the composition reference —
    # we intentionally skip swipe files here since they'd compete with the source
    # for layout influence and cause the model to blend compositions.
    contents.append("SOURCE THUMBNAIL — THIS IS THE EXACT LAYOUT TO COPY. Match its composition, framing, zoom level, person position, background, colors, text, props, and every other visual element. The only thing you should change is the person's face/identity (using the reference photos above). Everything else — INCLUDING framing and crop — must be identical:")
    contents.append(thumb_anon)

    title_section = ""
    if video_title:
        title_section = f"""
VIDEO TITLE: "{video_title}"
TITLE-THUMBNAIL SYNERGY: Title and thumbnail are a TEAM. The thumbnail adds an emotional/visual layer the title doesn't have. NEVER repeat the title. If title says "How I Built a $100k Business", thumbnail text should be "From Scratch" or show a revenue screenshot — NOT "$100k Business"."""

    user_overrides = ""
    if additional_prompt:
        user_overrides = f"""
=== PRIORITY INSTRUCTIONS (from the client — these OVERRIDE any conflicting rules below) ===
{additional_prompt}
=== END PRIORITY INSTRUCTIONS ===
Follow the instructions above EXACTLY. Where they conflict with the source layout or default rules below, the PRIORITY INSTRUCTIONS always win."""

    prompt = f"""You are an expert YouTube thumbnail designer. Create a new thumbnail based on the source layout above, featuring the client from the reference photos.
{user_overrides}

PERSON PORTRAYAL (from reference photos):
- Use reference photos ONLY for the person's face and body: bone structure, jawline, nose shape, eyebrow shape, skin tone, hair color/texture.
- IGNORE backgrounds/settings in reference photos — they are IRRELEVANT.
- Only the client should appear. No other people.
- Face proportions must be natural — no squeezing, stretching, or distortion.
- Match the pose, body position, and eye/gaze direction from the SOURCE THUMBNAIL. If the source person looks at the camera, the client should too. If the source person looks to the side or at a microphone, match that direction.
- Skin tone consistent across face, neck, hands, arms.
- TEXT ACCURACY: Spell EVERY word CORRECTLY. Double-check each letter.

LAYOUT RULES (from source thumbnail — follow unless overridden by PRIORITY INSTRUCTIONS):
- Use the source thumbnail as the base layout for composition, background, setting, and framing.
- Keep text overlays, graphic elements, logos, objects, props, and clothing consistent with the source.
- Do NOT bring backgrounds or settings from the reference photos.

FRAMING — MATCH THE SOURCE EXACTLY (THIS IS THE #1 PRIORITY):
- THE ENTIRE HEAD MUST BE VISIBLE IN THE FRAME. Every strand of hair, the top of the skull, the forehead, the chin, the ears — ALL visible. NOTHING cut off at the top or bottom.
- If the top of the hair is touching the top edge of the thumbnail, YOU ARE DOING IT WRONG. Leave a small gap above the hair, matching the source's headroom.
- Match the source's EXACT zoom level. If the source is waist-up, your output is waist-up. If the source is head-and-shoulders, match that.
- The person's EYES should be at roughly the same height in the frame as in the source's eyes.
- The person should occupy the SAME proportion of the frame as in the source — not bigger, not smaller.
- Do NOT zoom in closer than the source. Do NOT turn a medium/wide shot into a close-up headshot.
- Do NOT shove the person to the bottom of the frame with empty space above.
- COMMON MISTAKES THAT WILL FAIL THIS OUTPUT:
  * Cropping off the top of the hair/head — FAIL
  * Cropping off the chin — FAIL
  * Zooming into just the face when the source shows more of the body — FAIL
  * Pushing the person to the bottom of the frame with empty space above — FAIL
  * Leaving more headroom than the source has — FAIL
- Before finalizing, verify: "Can I see the entire top of the person's head with at least a small gap of space above it?" If no, you must redo the framing.

{PLAYBOOK}
{title_section}

OUTPUT: 1280x720 pixels, 16:9. Professional YouTube thumbnail."""

    contents.append(prompt)

    print(f"Generating with {len(reference_photos)} reference photos (provider={provider})...")

    # ── OpenAI GPT Image 1.5 branch ─────────────────────────────────────────
    if provider == "openai":
        # OpenAI's edit endpoint takes a single prompt string plus a list of
        # input images. We number the images explicitly in the prompt so the
        # model knows which is which, then pass reference photos + source.
        num_refs = len(reference_photos)
        image_guide_lines = []
        for i in range(num_refs):
            image_guide_lines.append(
                f"[IMAGE {i+1}] = reference photo of the client — use ONLY for face/body identity (bone structure, jawline, nose, eyebrows, skin tone, hair). Ignore its background."
            )
        image_guide_lines.append(
            f"[IMAGE {num_refs+1}] = SOURCE THUMBNAIL — this is the exact layout to copy. Preserve its composition, framing, zoom level, background, text, props, colors, and person position. Only the person's face/identity changes."
        )
        image_guide = "\n".join(image_guide_lines)

        openai_prompt = (
            "You are editing an existing YouTube thumbnail. Replace the person "
            "in the SOURCE THUMBNAIL with the client from the reference photos, "
            "while preserving EVERYTHING else about the source thumbnail exactly.\n\n"
            f"{image_guide}\n\n"
            f"{prompt}"
        )

        result = _openai_generate_image(
            prompt=openai_prompt,
            input_images=[*reference_photos, thumb_anon],
            input_fidelity="high",
            quality=openai_quality,
        )
        return result

    # ── Gemini 3 Pro Image branch (default / existing path) ─────────────────
    try:
        response = _api_call_with_timeout(client, MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    data = part.inline_data.data
                    if data:
                        img_bytes = base64.b64decode(data) if isinstance(data, str) else data
                        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))
                elif hasattr(part, 'text') and part.text:
                    print(f"Model note: {part.text[:200]}")
        else:
            # Check if blocked by content filter
            feedback = getattr(response, 'prompt_feedback', None)
            block_reason = getattr(feedback, 'block_reason', None) if feedback else None
            if response.candidates:
                c = response.candidates[0]
                print(f"  Candidate finish_reason: {getattr(c, 'finish_reason', 'N/A')}")
                print(f"  Safety ratings: {getattr(c, 'safety_ratings', 'N/A')}")
            else:
                print(f"  No candidates. Prompt feedback: {feedback}")

            if block_reason:
                print(f"  BLOCKED (reason: {block_reason})")
                return BLOCKED_SENTINEL

        print("No image in response")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def mashup_thumbnail(
    source_a: Image.Image,
    source_b: Image.Image,
    reference_photos: list[Image.Image],
    additional_prompt: str = "",
    video_title: str = "",
    swipe_examples: list[Image.Image] | None = None,
) -> Image.Image | None:
    """Merge two thumbnails together with the client's face.

    Blurs eyes in source thumbnails to bypass content filters on public figures.
    """
    api_client = genai.Client(api_key=API_KEY)

    thumb_a = source_a.copy()
    thumb_a.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
    thumb_b = source_b.copy()
    thumb_b.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    # Blur eyes in sources to anonymize
    thumb_a_anon = anonymize_source(thumb_a)
    thumb_b_anon = anonymize_source(thumb_b)
    print(f"\nAnonymized source thumbnails (pixelated for privacy)")

    contents = []
    for i, ref in enumerate(reference_photos):
        contents.append(f"Reference photo {i+1} of the client — this is the person who will be featured in the thumbnail:")
        contents.append(ref)

    contents.append("Thumbnail A (pixelated for privacy for privacy — use for composition, pose, expression, text, colors, style):")
    contents.append(thumb_a_anon)
    contents.append("Thumbnail B (pixelated for privacy for privacy — use for composition, pose, expression, text, colors, style):")
    contents.append(thumb_b_anon)

    # Add swipe file examples as style references
    if swipe_examples is None:
        u, c = load_swipe_examples()
        swipe_examples = u + c
    if swipe_examples:
        contents.append("STYLE REFERENCE — Real high-performing YouTube thumbnails (100k-3M+ views). Match this quality level:")
        for ex in swipe_examples:
            contents.append(ex)

    title_section = ""
    if video_title:
        title_section = f"""
VIDEO TITLE: "{video_title}"
TITLE-THUMBNAIL SYNERGY: Title and thumbnail are a TEAM. The thumbnail adds an emotional/visual layer the title doesn't have. NEVER repeat the title. Use shorter, punchier text (max 4 words) that pairs with the title."""

    prompt = f"""You are an expert YouTube thumbnail designer following the TikScale Thumbnail Design Playbook. Create a NEW thumbnail that merges the best elements from Thumbnail A and Thumbnail B above, featuring the client from the reference photos.

MASHUP RULES:
- Combine the strongest design elements from both thumbnails: composition, color scheme, text style, graphic elements, background.
- The person in the reference photos is the CLIENT. They must be the featured person.
- Accurately depict their exact appearance: bone structure, jawline, nose, eyebrows, skin tone, hair.
- Only the client should appear. Do not add other people.
- Face proportions must be natural — no squeezing or stretching.
- Pick the best composition from either thumbnail or blend them. Result must feel cohesive, not a collage.
- Skin tone must be consistent across face, neck, hands, arms. Match scene lighting.
- TEXT ACCURACY: Spell EVERY word CORRECTLY. Double-check each letter.

{PLAYBOOK}
{title_section}

OUTPUT: 1280x720 pixels, 16:9. Professional YouTube thumbnail.

{additional_prompt}"""

    contents.append(prompt)

    print(f"Mashup generating with {len(reference_photos)} reference photos...")

    try:
        response = _api_call_with_timeout(api_client, MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    data = part.inline_data.data
                    if data:
                        img_bytes = base64.b64decode(data) if isinstance(data, str) else data
                        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))
                elif hasattr(part, 'text') and part.text:
                    print(f"Model note: {part.text[:200]}")

        print("No image in response")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def collab_thumbnail(
    source_image: Image.Image,
    reference_photos: list[Image.Image],
    guest_photos: list[Image.Image],
    additional_prompt: str = "",
    video_title: str = "",
    swipe_examples: list[Image.Image] | None = None,
    anon_level: int = 0,
) -> Image.Image | str | None:
    """Recreate a thumbnail with the client AND a guest (two people).

    Uses source thumbnail for layout, client reference photos for person 1,
    and guest photos for person 2.
    """
    client = genai.Client(api_key=API_KEY)

    thumb = source_image.copy()
    thumb.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
    thumb_anon = anonymize_source(thumb, level=anon_level)

    contents = []

    # Client reference photos
    for i, ref in enumerate(reference_photos):
        contents.append(f"PERSON A (client) — reference photo {i+1}. Use for Person A's face and appearance:")
        contents.append(ref)

    # Guest photos
    for i, guest in enumerate(guest_photos):
        contents.append(f"PERSON B (guest) — reference photo {i+1}. Use for Person B's face and appearance:")
        contents.append(guest)

    contents.append("Source thumbnail — THIS is the master layout. It features TWO people. Replace their faces using Person A and Person B references above:")
    contents.append(thumb_anon)

    if swipe_examples is None:
        u, c = load_swipe_examples()
        swipe_examples = u + c
    if swipe_examples:
        contents.append("STYLE REFERENCE — Match this level of quality:")
        for ex in swipe_examples:
            contents.append(ex)

    title_section = ""
    if video_title:
        title_section = f'\nVIDEO TITLE: "{video_title}"'

    user_overrides = ""
    if additional_prompt:
        user_overrides = f"""
=== PRIORITY INSTRUCTIONS ===
{additional_prompt}
=== END PRIORITY INSTRUCTIONS ===
"""

    prompt = f"""You are an expert YouTube thumbnail designer. Recreate the source thumbnail above featuring TWO people.
{user_overrides}

TWO-PERSON RULES:
- Person A (client) uses the PERSON A reference photos. Person B (guest) uses the PERSON B reference photos.
- Both people must appear in the thumbnail. Match their positions from the source layout.
- Each person's face must accurately match their respective reference photos: bone structure, jawline, nose, eyebrows, skin tone, hair.
- Do NOT mix up the two people's faces. Person A's face comes ONLY from Person A refs. Person B's face comes ONLY from Person B refs.

LAYOUT RULES (from source thumbnail):
- Copy the source thumbnail's composition, background, text, props, and framing.
- Keep both people in the same positions as the source.

FRAMING:
- Both people must be fully visible — no cropping of heads or faces.

{PLAYBOOK}
{title_section}

OUTPUT: 1280x720 pixels, 16:9."""

    contents.append(prompt)

    print(f"Collab mode: generating with {len(reference_photos)} client refs + {len(guest_photos)} guest refs...")

    try:
        response = _api_call_with_timeout(client, MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    data = part.inline_data.data
                    if data:
                        img_bytes = base64.b64decode(data) if isinstance(data, str) else data
                        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))
                elif hasattr(part, 'text') and part.text:
                    print(f"Model note: {part.text[:200]}")
        else:
            feedback = getattr(response, 'prompt_feedback', None)
            block_reason = getattr(feedback, 'block_reason', None) if feedback else None
            if block_reason:
                print(f"  BLOCKED (reason: {block_reason})")
                return BLOCKED_SENTINEL
            print(f"  No candidates. Prompt feedback: {feedback}")

        print("No image in response")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def imagine_thumbnail(
    reference_photos: list[Image.Image],
    additional_prompt: str = "",
    video_title: str = "",
    swipe_examples: list[Image.Image] | None = None,
    client_swipes: list[Image.Image] | None = None,
    style_description: str = "",
    provider: str = "gemini",
    openai_quality: str = "high",
) -> Image.Image | None:
    """Generate a thumbnail from imagination using the playbook principles.

    `client_swipes` are full-quality client thumbnails used as primary style/layout
    templates. `swipe_examples` are pixelated universal references for general style.
    `style_description` is a pre-computed text description of the client's style from
    analyze_swipe_style() — gives the model concrete typography/color instructions.
    `provider` picks the backend: "gemini" (default) or "openai" (GPT Image 1.5).
    """
    api_client = genai.Client(api_key=API_KEY)

    contents = []
    for i, ref in enumerate(reference_photos):
        contents.append(f"Reference photo {i+1} of the person who must appear in the thumbnail:")
        contents.append(ref)

    has_client = client_swipes and len(client_swipes) > 0
    has_universal = swipe_examples and len(swipe_examples) > 0

    # Client swipes first — these are full quality and the PRIMARY style target
    if has_client:
        contents.append(f"""PRIMARY STYLE TEMPLATES ({len(client_swipes)} images) — These are the client's REAL thumbnails at full quality. Your output must look like the NEXT thumbnail in this series — as if the SAME designer made it.

REPLICATE THESE EXACTLY:
- LAYOUT: Copy the exact person placement, text positioning, and spatial arrangement from these thumbnails
- COLOR PALETTE: Use the SAME colors — background tones, text colors, accent colors, gradients
- TYPOGRAPHY: Match the EXACT font style — weight, case, size, stroke/outline treatment, shadow
- LIGHTING: Match the lighting mood — warm/cool, contrast level, rim lights, color gels
- GRAPHIC ELEMENTS: If they use arrows, icons, borders, cutout style — you use the same
- BACKGROUND STYLE: Same approach — solid, gradient, environmental, or composite
- OVERALL ENERGY: Same level of boldness, same density of elements, same polish level

Pick the layout from the template that best fits the prompt/title below, and reproduce that layout with new content. The result should be INDISTINGUISHABLE in style from these templates:""")
        for ex in client_swipes:
            contents.append(ex)

    # Universal swipes as supplementary style references (pixelated)
    if has_universal:
        label = "ADDITIONAL STYLE REFERENCES" if has_client else "STYLE REFERENCES"
        contents.append(f"""{label} ({len(swipe_examples)} images) — High-performing YouTube thumbnails for general style inspiration:""")
        for ex in swipe_examples:
            contents.append(ex)

    title_section = ""
    if video_title:
        title_section = f"""
VIDEO TITLE: "{video_title}"
TITLE-THUMBNAIL SYNERGY: This is CRITICAL. Title and thumbnail are a TEAM. The thumbnail adds an emotional/visual layer the title doesn't have. NEVER repeat the title. Use shorter, punchier overlay text (max 4 words) that pairs with the title. Example: if title is "I Made $50k in 30 Days", thumbnail text = "$50K" with shocked face — title provides context."""

    user_direction = ""
    if additional_prompt:
        user_direction = f"""
=== PRIORITY INSTRUCTIONS (these OVERRIDE any conflicting rules below) ===
{additional_prompt}
=== END PRIORITY INSTRUCTIONS ===
"""

    style_instruction = ""
    style_analysis_block = ""
    if has_client:
        style_instruction = "- CRITICAL: Your output must be a PIXEL-PERFECT STYLE MATCH to the primary style templates above. Same fonts, same colors, same composition, same energy. If in doubt, copy MORE from the templates, not less."
        if style_description:
            style_analysis_block = f"""
=== EXACT STYLE SPECIFICATION (extracted from client's thumbnails) ===
{style_description}
=== END STYLE SPECIFICATION ===
Follow this specification PRECISELY. Every font choice, color, outline, and layout decision must match."""
    elif has_universal:
        style_instruction = "- Match the general style and quality level of the style reference thumbnails."

    prompt = f"""You are an elite YouTube thumbnail designer. Create a stunning, high-CTR YouTube thumbnail featuring the person from the reference photos.
{user_direction}
{style_analysis_block}

STYLE REQUIREMENTS:
{style_instruction if style_instruction else '- FONTS: Use clean, bold, modern sans-serif fonts (like Montserrat, Inter, or similar). NEVER use dated, decorative, script, or clip-art-style fonts.'}
- COLORS: High contrast. Rich, cinematic color grading.
- LIGHTING: Cinematic, dramatic lighting with depth. NEVER flat, stock-photo lighting.
- COMPOSITION: Clean and uncluttered. One clear focal point. Person takes up 40-60% of frame.
- TEXT: Maximum 4 words. Large, bold, high contrast against background. Drop shadow or outline for readability. Positioned to not overlap the face.
- OVERALL: Must look like a thumbnail from a top-tier creator. Premium, polished, professional.

IDENTITY RULES — THIS IS NON-NEGOTIABLE:
- EVERY face in the thumbnail MUST be the person from the reference photos. No exceptions.
- There must be ONLY ONE person visible in the thumbnail (unless the prompt says otherwise).
- Copy EXACT bone structure, jawline, nose shape, eyebrow shape, skin tone, hair color and style.
- If you cannot make the face match perfectly, try harder. Do NOT substitute a different face.
- Face proportions must be NATURAL — no squeezing or stretching.

TEXT ACCURACY — ZERO TOLERANCE FOR ERRORS:
- Before finalizing, read back every word of text you placed in the thumbnail.
- Check each word letter by letter. No repeated letters, no missing letters, no swapped letters.
- If the prompt or title specifies text, spell it EXACTLY as given.
- Common mistakes to avoid: doubled letters (e.g. "STOPP"), missing letters (e.g. "AGNCY"), wrong letters.

{PLAYBOOK}
{title_section}

OUTPUT: 1280x720 pixels, 16:9. Must look like a top-tier professional YouTube thumbnail."""

    contents.append(prompt)

    print(f"\nImagine mode: generating with {len(reference_photos)} reference photos (provider={provider})...")

    # ── OpenAI GPT Image 1.5 branch ─────────────────────────────────────────
    if provider == "openai":
        # OpenAI edits endpoint takes a single prompt string plus up to 16
        # input images. For imagine mode we pass: reference photos first, then
        # the client's full-quality swipe file thumbnails as style templates.
        # Universal (pixelated) swipes are skipped since they'd waste the
        # 16-image budget on low-signal inputs.
        num_refs = len(reference_photos)
        num_client = len(client_swipes) if client_swipes else 0

        image_guide_lines = []
        for i in range(num_refs):
            image_guide_lines.append(
                f"[IMAGE {i+1}] = reference photo of the client — use ONLY for face/body identity (bone structure, jawline, nose, eyebrows, skin tone, hair)."
            )
        for j in range(num_client):
            image_guide_lines.append(
                f"[IMAGE {num_refs+j+1}] = style template from the client's channel — match its exact fonts, colors, layout, typography, and graphic style."
            )
        image_guide = "\n".join(image_guide_lines)

        openai_prompt = (
            "Create a brand new YouTube thumbnail from scratch. The person in "
            "the output MUST be the client from the reference photos. The visual "
            "style (fonts, colors, composition, typography, graphic treatment) "
            "MUST match the style templates provided.\n\n"
            f"{image_guide}\n\n"
            f"{prompt}"
        )

        openai_inputs = [*reference_photos]
        if client_swipes:
            openai_inputs.extend(client_swipes)

        result = _openai_generate_image(
            prompt=openai_prompt,
            input_images=openai_inputs,
            input_fidelity="low",  # imagine mode is creative, not strict edit
            quality=openai_quality,
        )
        return result

    # ── Gemini 3 Pro Image branch (default / existing path) ─────────────────
    try:
        response = _api_call_with_timeout(api_client, MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    data = part.inline_data.data
                    if data:
                        img_bytes = base64.b64decode(data) if isinstance(data, str) else data
                        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))
                elif hasattr(part, 'text') and part.text:
                    print(f"Model note: {part.text[:200]}")

        print("No image in response")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def verify_and_fix(
    generated: Image.Image,
    reference_photos: list[Image.Image],
) -> Image.Image:
    """Verify the generated thumbnail has correct identity and spelling. Fix if needed."""
    api_client = genai.Client(api_key=API_KEY)

    contents = []
    for i, ref in enumerate(reference_photos):
        contents.append(f"Reference photo {i+1} of the CORRECT person:")
        contents.append(ref)

    contents.append("Generated thumbnail to verify:")
    contents.append(generated)

    contents.append("""VERIFICATION TASK — Check this thumbnail for THREE issues. Be STRICT.

1. FACE IDENTITY (most important):
   - Count how many faces appear in the thumbnail.
   - There should be EXACTLY ONE face (the reference person) unless the original prompt specified multiple people.
   - Compare EACH face against the reference photos: check bone structure, jawline shape, nose shape, eyebrow thickness/arch, skin tone, hair color/style.
   - If ANY face does NOT match the reference person, or if there are extra faces that shouldn't be there, you MUST regenerate the thumbnail with ONLY the correct person's face.

2. TEXT SPELLING (zero tolerance):
   - Read every single word of text in the thumbnail out loud.
   - Spell each word letter by letter. Check for:
     * Doubled letters that shouldn't be there (e.g. "STOPP" → "STOP")
     * Missing letters (e.g. "AGNCY" → "AGENCY")
     * Wrong letters (e.g. "HRING" → "HIRING")
     * Extra words or garbled text
   - If ANY spelling error exists, fix it.

3. TEXT QUALITY:
   - Is the text readable and clear?
   - Is the font clean and modern (not dated or decorative)?
   - Does the text have proper contrast against the background?

If ALL checks pass, return the thumbnail EXACTLY as-is with no changes.
If ANY check fails, output a corrected version. Keep everything else identical — same composition, colors, layout, style. Only fix what's broken.

Output the image in 16:9 format (1280x720).""")

    try:
        response = _api_call_with_timeout(api_client, MODEL, contents,
            types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            timeout=90)

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    print(f"  Verify: {part.text[:200]}")
                if hasattr(part, 'inline_data') and part.inline_data:
                    data = part.inline_data.data
                    if data:
                        img_bytes = base64.b64decode(data) if isinstance(data, str) else data
                        print("  Verify: returned corrected image")
                        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))

        print("  Verify: no image returned, keeping original")
        return generated

    except Exception as e:
        print(f"  Verify error: {e}, keeping original")
        return generated


def edit_thumbnail(
    source_image: Image.Image,
    edit_instructions: str,
    reference_images: list[Image.Image] | None = None,
    style_reference: Image.Image | None = None,
) -> Image.Image | None:
    """Edit an existing thumbnail with high-level instructions.

    - `reference_images` (logos): treated as exact visual assets to swap in
      verbatim (colors, shape, typography).
    - `style_reference` (optional): a full-frame reference showing the desired
      overall look, layout, composition, and color grading — the model should
      emulate its aesthetic, NOT copy its content literally.
    """
    api_client = genai.Client(api_key=API_KEY)

    thumb = source_image.copy()
    thumb.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    # Normalize style reference to thumbnail size — it's a full-frame guide,
    # so we want it roughly the same resolution as the source.
    style_ref: Image.Image | None = None
    if style_reference is not None:
        style_ref = style_reference.copy()
        style_ref.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    # Normalize references to reasonable size (usually small logos, but cap
    # them so we don't blow up request payload on huge sources).
    refs: list[Image.Image] = []
    if reference_images:
        for ri in reference_images:
            rcopy = ri.copy()
            rcopy.thumbnail((512, 512), Image.Resampling.LANCZOS)
            refs.append(rcopy)

    # Build the image-numbering map dynamically so the prompt accurately
    # refers to each input by index. Source is always IMAGE 1.
    img_descriptions = ["IMAGE 1: A thumbnail that needs editing."]
    next_idx = 2
    style_ref_idx: int | None = None
    if style_ref is not None:
        style_ref_idx = next_idx
        img_descriptions.append(
            f"IMAGE {next_idx}: STYLE/LAYOUT REFERENCE. Match its composition, "
            f"spacing, color palette, lighting, and visual treatment. Do NOT "
            f"copy its content literally — use it ONLY as a guide for how the "
            f"final result should look and feel."
        )
        next_idx += 1

    logo_range: tuple[int, int] | None = None
    if refs:
        start = next_idx
        end = next_idx + len(refs) - 1
        logo_range = (start, end)
        if start == end:
            img_descriptions.append(
                f"IMAGE {start}: REFERENCE LOGO you MUST use to REPLACE a matching element in IMAGE 1."
            )
        else:
            img_descriptions.append(
                f"IMAGES {start}-{end}: REFERENCE LOGOS you MUST use to REPLACE matching elements in IMAGE 1."
            )
        img_descriptions.append(
            "- If any logo, brand mark, or element in IMAGE 1 depicts the same "
            "subject as a reference logo, you MUST FULLY REPLACE it — pixel for "
            "pixel — copying its exact colors, shape, typography, and proportions."
        )
        img_descriptions.append(
            "- Do NOT keep a modified version of the original. Do NOT blend. "
            "COMPLETELY SWAP IT OUT."
        )
        img_descriptions.append(
            "- Do NOT invent or approximate logos from memory. References are the source of truth."
        )
        next_idx = end + 1

    ref_block = "\n".join(img_descriptions) + "\n\n"

    prompt = f"""{ref_block}TASK: Make the following changes to the thumbnail (IMAGE 1):
{edit_instructions}

RULES:
- Apply the requested changes FULLY. Do not make them more subtle, softer, or smaller than described. If the user says "move X to the right," move it decisively. If they say "hide 50%," actually hide 50%.
- Preserve elements that are not being modified (position, style, composition).
- The PERSON in IMAGE 1 stays as the subject — never replace them with anyone from a reference image.
- Output in 16:9 format."""

    print(f"\nEditing with instructions: {edit_instructions[:100]}...")
    if style_ref is not None:
        print(f"Using style reference (IMAGE {style_ref_idx})")
    if refs:
        if logo_range and logo_range[0] == logo_range[1]:
            print(f"Using 1 reference logo (IMAGE {logo_range[0]})")
        elif logo_range:
            print(f"Using {len(refs)} reference logos (IMAGES {logo_range[0]}-{logo_range[1]})")

    try:
        # Order MUST match the numbering in ref_block:
        # [thumb, (style_ref?), *refs, prompt]
        call_parts: list = [thumb]
        if style_ref is not None:
            call_parts.append(style_ref)
        call_parts.extend(refs)
        call_parts.append(prompt)
        response = _api_call_with_timeout(api_client, MODEL, call_parts,
            types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]))

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    data = part.inline_data.data
                    if data:
                        img_bytes = base64.b64decode(data) if isinstance(data, str) else data
                        return normalize_to_thumbnail(Image.open(io.BytesIO(img_bytes)))
                elif hasattr(part, 'text') and part.text:
                    print(f"Model note: {part.text[:200]}")

        print("No image in response")
        return None

    except Exception as e:
        print(f"Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Recreate YouTube thumbnails with face swap"
    )
    parser.add_argument("--youtube", "-y", type=str,
                        help="YouTube video URL to recreate thumbnail from")
    parser.add_argument("--source", "-s", type=str,
                        help="Source thumbnail URL or file path")
    parser.add_argument("--edit", "-e", type=str,
                        help="Edit an existing thumbnail (path to image)")
    parser.add_argument("--mode", type=str, default="replicate",
                        choices=["replicate", "mashup", "collab", "imagine"],
                        help="Generation mode: replicate, mashup, collab, or imagine")
    parser.add_argument("--source2", type=str,
                        help="Second source thumbnail for mashup mode (URL or file path)")
    parser.add_argument("--youtube2", type=str,
                        help="Second YouTube URL for mashup mode")
    parser.add_argument("--style", type=str,
                        default="purple/teal gradient with modern aesthetic",
                        help="Style variation to apply")
    parser.add_argument("--prompt", "-p", type=str, default="",
                        help="Additional instructions (for recreation or edit)")
    parser.add_argument("--output", "-o", type=str,
                        help="Output filename")
    parser.add_argument("--refs", type=int, default=2,
                        help="Number of reference photos to use (1-5)")
    parser.add_argument("--variations", "-n", type=int, default=3,
                        help="Number of variations to generate (default: 3)")
    parser.add_argument("--no-match", action="store_true",
                        help="Skip face direction matching")
    parser.add_argument("--title", "-t", type=str, default="",
                        help="Video title — thumbnail will be designed to complement it")
    parser.add_argument("--ref-dir", type=str, default=None,
                        help="Override reference photos directory")
    parser.add_argument("--swipe-files", type=str, default="",
                        help="Comma-separated list of swipe example filenames to use (empty = all)")
    parser.add_argument("--guest-photos", type=str, default="",
                        help="Comma-separated paths to guest/second person photos (collab mode)")
    parser.add_argument("--selected-refs", type=str, default="",
                        help="Comma-separated filenames of selected reference photos (empty = all)")
    parser.add_argument("--skip-enhance", action="store_true",
                        help="Skip prompt enhancement (already done in frontend)")
    parser.add_argument("--reference-images", type=str, default="",
                        help="Comma-separated paths to reference images (edit mode): exact logos/assets to use verbatim")
    parser.add_argument("--style-reference", type=str, default="",
                        help="Path to a style/layout reference image (edit mode): guides the overall look without being copied literally")
    parser.add_argument("--client-swipe-files", type=str, default="",
                        help="Comma-separated absolute paths to client-specific swipe files (loaded alongside universal ones)")
    parser.add_argument("--provider", type=str, default="gemini",
                        choices=["gemini", "openai"],
                        help="Image generation provider for replicate/imagine modes (default: gemini)")
    parser.add_argument("--openai-quality", type=str, default="high",
                        choices=["low", "medium", "high"],
                        help="Quality tier for OpenAI GPT Image 1.5 (default: high)")

    args = parser.parse_args()

    if args.ref_dir:
        global REFERENCE_PHOTOS_DIR
        REFERENCE_PHOTOS_DIR = Path(args.ref_dir)

    if not API_KEY:
        print("Error: NANO_BANANA_API_KEY not set in .env")
        print("Get your API key from Google AI Studio and add to .env:")
        print("  NANO_BANANA_API_KEY=your_key_here")
        sys.exit(1)

    date_folder = OUTPUT_DIR / datetime.now().strftime("%Y%m%d")
    date_folder.mkdir(parents=True, exist_ok=True)
    time_stamp = datetime.now().strftime("%H%M%S")
    print(f"TIMESTAMP:{time_stamp}")

    # === EDIT MODE ===
    if args.edit:
        if not args.prompt:
            print("Error: --edit requires --prompt with edit instructions")
            sys.exit(1)

        print(f"Loading image to edit: {args.edit}")
        edit_image = Image.open(args.edit)
        print(f"Size: {edit_image.size}")

        # Load reference images (e.g. brand logos) if provided
        reference_images: list[Image.Image] = []
        if args.reference_images:
            for rp in args.reference_images.split(","):
                rp = rp.strip()
                if rp and Path(rp).exists():
                    try:
                        reference_images.append(Image.open(rp))
                    except Exception as e:
                        print(f"Warning: failed to load reference {rp}: {e}")
            print(f"Loaded {len(reference_images)} reference image(s)")

        # Load optional style/layout reference
        style_ref_image: Image.Image | None = None
        if args.style_reference and Path(args.style_reference).exists():
            try:
                style_ref_image = Image.open(args.style_reference)
                print(f"Loaded style reference: {args.style_reference}")
            except Exception as e:
                print(f"Warning: failed to load style reference: {e}")

        output_paths = []
        for i in range(args.variations):
            print(f"\n--- Variation {i + 1}/{args.variations} ---")
            result = edit_thumbnail(
                edit_image,
                args.prompt,
                reference_images=reference_images or None,
                style_reference=style_ref_image,
            )
            if result is None:
                print(f"Edit variation {i + 1} failed")
                continue

            if args.output and args.variations == 1:
                output_path = date_folder / args.output
            else:
                output_path = date_folder / f"{time_stamp}_edited_{i + 1}.png"

            result.save(output_path)
            output_paths.append(str(output_path))
            print(f"Saved: {output_path}")
            print(f"Size: {result.size}")

        if not output_paths:
            print("All edit variations failed")
            sys.exit(1)

        print(f"\n=== Generated {len(output_paths)}/{args.variations} edit variations ===")
        return output_paths

    # === LOAD SOURCE IMAGE(S) ===
    def load_source(youtube_arg, source_arg):
        """Load a source image from YouTube URL or file/URL path."""
        if youtube_arg:
            video_id = extract_video_id(youtube_arg)
            if not video_id:
                print(f"Error: Could not extract video ID from {youtube_arg}")
                sys.exit(1)
            print(f"Video ID: {video_id}")
            img = get_youtube_thumbnail(video_id)
            if not img:
                print("Error: Could not download YouTube thumbnail")
                sys.exit(1)
            return img
        elif source_arg:
            print(f"Loading source: {source_arg}")
            if source_arg.startswith(("http://", "https://")):
                return download_image(source_arg)
            else:
                return Image.open(source_arg)
        return None

    # Load swipe examples once for all variations.
    # Universal swipes come from --swipe-files (filenames in execution/swipe_examples/individual/).
    # Client-specific swipes come from --client-swipe-files (absolute paths).
    client_swipe_paths: list[Path] = []
    if args.client_swipe_files:
        client_swipe_paths = [
            Path(p.strip()) for p in args.client_swipe_files.split(',') if p.strip()
        ]

    # If --swipe-files was not provided at all (legacy CLI use), load ALL
    # universal swipes. Otherwise respect the explicit list (which may be
    # empty = "no universal swipes selected"). Client swipes are independent.
    swipe_files_provided = '--swipe-files' in sys.argv or args.swipe_files != ""
    if not swipe_files_provided and not client_swipe_paths:
        universal_swipes, client_swipes = load_swipe_examples()
    else:
        swipe_filter = [f.strip() for f in args.swipe_files.split(',') if f.strip()]
        universal_swipes, client_swipes = load_swipe_examples(
            only_files=swipe_filter,  # may be [] meaning "none from universal pool"
            extra_paths=client_swipe_paths or None,
        )
    # Combined list for modes that don't need the distinction
    swipe_examples = universal_swipes + client_swipes

    # === IMAGINE MODE (no source needed) ===
    if args.mode == "imagine":
        print(f"Mode: IMAGINE — generating from creativity")
        reference_photos = load_reference_photos(max_photos=args.refs)
        if not reference_photos:
            print("Warning: No reference photos found. Results may vary.")

        # Pre-analyze client swipe style once (shared across all variations)
        style_desc = ""
        if client_swipes:
            print("Analyzing client thumbnail style...")
            style_desc = analyze_swipe_style(client_swipes)

        output_paths = []
        for i in range(args.variations):
            print(f"\n--- Variation {i + 1}/{args.variations} ---")
            result = imagine_thumbnail(
                reference_photos=reference_photos,
                additional_prompt=args.prompt,
                video_title=args.title,
                swipe_examples=universal_swipes if universal_swipes else None,
                client_swipes=client_swipes if client_swipes else None,
                style_description=style_desc,
                provider=args.provider,
                openai_quality=args.openai_quality,
            )
            if result is None:
                print(f"Failed to generate variation {i + 1}")
                continue
            # Verify identity and spelling on EVERY variation
            if reference_photos:
                print(f"  Running verify & fix pass...")
                result = verify_and_fix(result, reference_photos)
            output_path = date_folder / f"{time_stamp}_{i + 1}.png"
            result.save(output_path)
            output_paths.append(str(output_path))
            print(f"Saved: {output_path}")
            print(f"Size: {result.size}")

        print(f"\n=== Generated {len(output_paths)}/{args.variations} variations ===")
        for path in output_paths:
            print(f"  - {path}")
        return output_paths

    # === REPLICATE, MASHUP & COLLAB MODES (need source) ===
    source_image = load_source(args.youtube, args.source)
    if not source_image:
        print("Error: Provide --youtube URL or --source image")
        sys.exit(1)
    print(f"Source size: {source_image.size}")

    # Load guest photos for collab mode
    guest_photos = []
    if args.mode == "collab" and args.guest_photos:
        for gp in args.guest_photos.split(","):
            gp = gp.strip()
            if gp and Path(gp).exists():
                guest = Image.open(gp)
                guest.thumbnail(REF_SIZE, Image.Resampling.LANCZOS)
                guest_photos.append(guest)
        print(f"Loaded {len(guest_photos)} guest photos")

    # Load second source for mashup
    source_image_b = None
    if args.mode == "mashup":
        source_image_b = load_source(args.youtube2, args.source2)
        if not source_image_b:
            print("Error: Mashup mode requires a second source (--youtube2 or --source2)")
            sys.exit(1)
        print(f"Source B size: {source_image_b.size}")

    # Analyze face direction
    best_reference = None
    if not args.no_match:
        print("\nAnalyzing face direction in source thumbnail...")
        pose = get_face_pose(source_image)
        if pose:
            yaw, pitch = pose
            print(f"Detected pose: yaw={yaw:+.1f}, pitch={pitch:+.1f}")
            best_reference = find_best_reference(yaw, pitch)
            if best_reference:
                print(f"Best matching reference: {best_reference.name}")
            else:
                print("No direction-labeled references found, using defaults")
        else:
            print("No face detected in source, using default references")

    # Filter to selected refs if specified
    selected_ref_filter = None
    if args.selected_refs:
        selected_ref_filter = [f.strip() for f in args.selected_refs.split(',') if f.strip()]
        print(f"Using {len(selected_ref_filter)} selected reference photos")

    reference_photos = load_reference_photos(
        max_photos=args.refs,
        specific_path=best_reference,
        only_files=selected_ref_filter,
    )
    if not reference_photos:
        print("Warning: No reference photos found. Results may vary.")

    # Enhance user prompt once (before all variations)
    enhanced_prompt = args.prompt
    if args.prompt.strip() and not args.skip_enhance:
        print("Enhancing prompt with AI...")
        enhanced_prompt = enhance_prompt(source_image, args.prompt, args.title)
    elif args.skip_enhance:
        print("Using pre-enhanced prompt from frontend")

    output_paths = []

    for i in range(args.variations):
        print(f"\n--- Variation {i + 1}/{args.variations} ---")

        result = None
        max_anon_level = 2
        for anon_level in range(max_anon_level + 1):
            if args.mode == "mashup":
                result = mashup_thumbnail(
                    source_a=source_image,
                    source_b=source_image_b,
                    reference_photos=reference_photos,
                    additional_prompt=enhanced_prompt,
                    video_title=args.title,
                    swipe_examples=swipe_examples,
                )
            elif args.mode == "collab":
                result = collab_thumbnail(
                    source_image=source_image,
                    reference_photos=reference_photos,
                    guest_photos=guest_photos,
                    additional_prompt=enhanced_prompt,
                    video_title=args.title,
                    swipe_examples=swipe_examples,
                    anon_level=anon_level,
                )
            else:
                result = recreate_thumbnail(
                    source_image=source_image,
                    reference_photos=reference_photos,
                    style_variation=args.style,
                    additional_prompt=enhanced_prompt,
                    video_title=args.title,
                    swipe_examples=swipe_examples,
                    anon_level=anon_level,
                    provider=args.provider,
                )

            if result == BLOCKED_SENTINEL:
                if anon_level < max_anon_level:
                    anon_labels = {0: "face blur", 1: "face + text blur", 2: "heavy pixelation"}
                    next_label = anon_labels.get(anon_level + 1, "heavier")
                    print(f"  RETRY: Content filter blocked, retrying with {next_label} (attempt {anon_level + 2}/{max_anon_level + 1})")
                    continue
                else:
                    print(f"  All anonymization levels exhausted, skipping variation")
                    result = None
                    break
            else:
                break  # Success or non-block failure

        if result is None or result == BLOCKED_SENTINEL:
            print(f"Failed to generate variation {i + 1}")
            continue

        # Face identity check — retry up to 2 times if face doesn't match
        # Skip for collab mode (two different people would confuse the checker)
        if reference_photos and args.mode != "collab":
            max_face_retries = 2
            for face_attempt in range(max_face_retries + 1):
                if check_face_match(result, reference_photos):
                    break
                if face_attempt < max_face_retries:
                    print(f"  FACE MISMATCH — regenerating (attempt {face_attempt + 2}/{max_face_retries + 1})")
                    if args.mode == "mashup":
                        result = mashup_thumbnail(
                            source_a=source_image, source_b=source_image_b,
                            reference_photos=reference_photos,
                            additional_prompt=enhanced_prompt,
                            video_title=args.title, swipe_examples=swipe_examples,
                        )
                    else:
                        result = recreate_thumbnail(
                            source_image=source_image, reference_photos=reference_photos,
                            style_variation=args.style, additional_prompt=enhanced_prompt,
                            video_title=args.title, swipe_examples=swipe_examples,
                            anon_level=0, provider=args.provider, openai_quality=args.openai_quality,
                        )
                    if result is None or result == BLOCKED_SENTINEL:
                        break
                else:
                    print(f"  Face still doesn't match after {max_face_retries + 1} attempts, keeping best result")

        if result is None or result == BLOCKED_SENTINEL:
            print(f"Failed to generate variation {i + 1}")
            continue

        # Verify spelling + identity on every variation
        if reference_photos:
            print(f"  Running verify & fix pass...")
            result = verify_and_fix(result, reference_photos)

        if args.output and args.variations == 1:
            output_path = date_folder / args.output
        else:
            output_path = date_folder / f"{time_stamp}_{i + 1}.png"

        result.save(output_path)
        output_paths.append(str(output_path))
        print(f"Saved: {output_path}")
        print(f"Size: {result.size}")

    print(f"\n=== Generated {len(output_paths)}/{args.variations} variations ===")
    for path in output_paths:
        print(f"  - {path}")

    return output_paths


if __name__ == "__main__":
    main()
