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

MODEL = "gemini-3-pro-image-preview"
ANALYSIS_MODEL = "gemini-2.5-pro"  # For analyzing source thumbnails (avoids image-gen model's content filter)

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


def load_swipe_examples(only_files: list[str] | None = None) -> list[Image.Image]:
    """Load individual cropped swipe file thumbnails, anonymized to bypass content filters.

    If only_files is set, load only those filenames.
    All swipe examples are pixelated to avoid triggering public-figure filters.
    """
    individual_dir = SWIPE_DIR / "individual"
    if not individual_dir.exists():
        return []
    thumbs = sorted(individual_dir.glob("thumb_*.png"))
    if only_files:
        allowed = set(only_files)
        thumbs = [t for t in thumbs if t.name in allowed]
    examples = []
    for p in thumbs:
        try:
            img = Image.open(p)
            img.thumbnail((768, 768), Image.Resampling.LANCZOS)
            # Full pixelation for swipe examples — they're style references only,
            # so exact detail isn't needed, just composition/color/text style
            w, h = img.size
            small = img.resize((30, 30), Image.Resampling.NEAREST)
            img = small.resize((w, h), Image.Resampling.NEAREST)
            examples.append(img)
        except Exception:
            continue
    print(f"Loaded {len(examples)} swipe file thumbnails (anonymized)")
    return examples


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
                     threshold: float = 0.15) -> bool:
    """Check if the face in the generated thumbnail matches the reference photos.

    Returns True if the face matches (or if we can't detect faces to compare).
    Returns False only if we can confidently say the face is wrong.
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
                    # Remove duplicate sections (model sometimes repeats)
                    lines = enhanced.split('\n')
                    seen_sections = set()
                    deduped = []
                    for line in lines:
                        stripped = line.strip()
                        if stripped.endswith(':') and stripped[:-1] in ('CHANGE', 'ADD', 'TEXT', 'LAYOUT', 'KEEP', 'REMOVE'):
                            if stripped in seen_sections:
                                # Skip this section and everything until next section
                                deduped.append(None)  # marker
                                continue
                            seen_sections.add(stripped)
                        if deduped and deduped[-1] is None:
                            if stripped.endswith(':') and stripped[:-1] in ('CHANGE', 'ADD', 'TEXT', 'LAYOUT', 'KEEP', 'REMOVE'):
                                if stripped not in seen_sections:
                                    deduped[-1] = line  # replace marker
                                    seen_sections.add(stripped)
                                continue
                            continue
                        deduped.append(line)
                    enhanced = '\n'.join(l for l in deduped if l is not None)
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
) -> Image.Image | str | None:
    """Recreate a thumbnail with the client as the featured person.

    Blurs eyes in the source thumbnail to bypass content filters on public figures,
    while preserving expression, pose, and layout for accurate replication.
    """
    client = genai.Client(api_key=API_KEY)

    thumb = source_image.copy()
    thumb.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    # Anonymize source to bypass public figure filter
    thumb_anon = anonymize_source(thumb, level=anon_level)
    anon_labels = {0: "face blur", 1: "face blur + text wash", 2: "heavy pixelation"}
    print(f"\nAnonymized source thumbnail ({anon_labels.get(anon_level, 'face blur')})")

    contents = []
    for i, ref in enumerate(reference_photos):
        contents.append(f"Reference photo {i+1} of the client — ONLY use this for the person's face and body appearance. IGNORE the background, setting, and environment in this photo:")
        contents.append(ref)

    contents.append("Source thumbnail — THIS is the master layout. Copy its EXACT background, setting, environment, colors, objects, props, text, and composition. Only replace the person's face/appearance using the reference photos above:")
    contents.append(thumb_anon)

    # Add swipe file examples as style references
    if swipe_examples is None:
        swipe_examples = load_swipe_examples()
    if swipe_examples:
        contents.append("STYLE REFERENCE — These are real high-performing YouTube thumbnails (100k-3M+ views). Study their style, composition, contrast, and text treatment. Your output should match this level of quality:")
        for ex in swipe_examples:
            contents.append(ex)

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
- Match expression and pose from the SOURCE THUMBNAIL.
- Skin tone consistent across face, neck, hands, arms.
- TEXT ACCURACY: Spell EVERY word CORRECTLY. Double-check each letter.

LAYOUT RULES (from source thumbnail — follow unless overridden by PRIORITY INSTRUCTIONS):
- Use the source thumbnail as the base layout for composition, background, setting, and framing.
- Keep text overlays, graphic elements, logos, objects, props, and clothing consistent with the source.
- Do NOT bring backgrounds or settings from the reference photos.

FRAMING:
- The person MUST be fully visible — never crop out head, forehead, chin, or visible body parts.
- Leave adequate headroom.

{PLAYBOOK}
{title_section}

OUTPUT: 1280x720 pixels, 16:9. Professional YouTube thumbnail."""

    contents.append(prompt)

    print(f"Generating with {len(reference_photos)} reference photos...")

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
        swipe_examples = load_swipe_examples()
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
        swipe_examples = load_swipe_examples()
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
) -> Image.Image | None:
    """Generate a thumbnail from imagination using the playbook principles."""
    api_client = genai.Client(api_key=API_KEY)

    contents = []
    for i, ref in enumerate(reference_photos):
        contents.append(f"Reference photo {i+1} of the person who must appear in the thumbnail:")
        contents.append(ref)

    # Add swipe file examples as style references
    if swipe_examples is None:
        swipe_examples = load_swipe_examples()

    has_swipe = swipe_examples and len(swipe_examples) > 0
    if has_swipe:
        contents.append("""STYLE REFERENCES — These are REAL high-performing YouTube thumbnails (100k-3M+ views).
Your output MUST closely match the STYLE, AESTHETIC, and QUALITY of these examples:
- Study the exact FONT STYLES used (modern, bold, clean sans-serif — NOT dated/decorative fonts)
- Study the COLOR PALETTES (high contrast, cinematic tones)
- Study the COMPOSITION (person placement, text placement, negative space)
- Study the LIGHTING (cinematic, professional — NOT flat or stock-photo-like)
- Study the OVERALL FEEL (premium, polished, 2024/2025 YouTube aesthetic)
Your thumbnail MUST look like it belongs in the same collection as these:""")
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

    prompt = f"""You are an elite YouTube thumbnail designer. Create a stunning, high-CTR YouTube thumbnail featuring the person from the reference photos.
{user_direction}

MODERN STYLE REQUIREMENTS (2024/2025 YouTube aesthetic):
- FONTS: Use clean, bold, modern sans-serif fonts (like Montserrat, Inter, or similar). NEVER use dated, decorative, script, or clip-art-style fonts.
- COLORS: High contrast. Rich, cinematic color grading. Popular palettes: dark backgrounds with bright accent colors, gradient overlays, or clean whites with bold color pops.
- LIGHTING: Cinematic, dramatic lighting with depth. Rim lighting, color gels, or moody window light. NEVER flat, stock-photo lighting.
- COMPOSITION: Clean and uncluttered. One clear focal point. Strategic use of negative space. Person takes up 40-60% of frame.
- TEXT: Maximum 4 words. Large, bold, high contrast against background. Drop shadow or outline for readability. Positioned to not overlap the face.
- OVERALL: Must look like a thumbnail from a top-tier creator (MrBeast, Ali Abdaal, MKBHD level quality). Premium, polished, professional.
{'- MATCH THE STYLE of the provided style reference thumbnails EXACTLY.' if has_swipe else ''}

IDENTITY RULES:
- ONLY the person from the reference photos may appear. Copy exact bone structure, jawline, nose, eyebrows, skin tone, hair.
- Face proportions must be NATURAL — no squeezing or stretching.
- Skin tone consistent across face, neck, hands, arms.
- TEXT ACCURACY: Spell EVERY word CORRECTLY.

{PLAYBOOK}
{title_section}

OUTPUT: 1280x720 pixels, 16:9. Must look like a top-tier professional YouTube thumbnail."""

    contents.append(prompt)

    print(f"\nImagine mode: generating with {len(reference_photos)} reference photos...")

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

    contents.append("""VERIFICATION TASK — Check this thumbnail for TWO issues:

1. FACE IDENTITY: Does every face in this thumbnail match the reference person above? Check bone structure, jawline, nose, eyebrows, skin tone, hair. If ANY face belongs to a different person, regenerate the ENTIRE thumbnail with the correct person's face.

2. TEXT SPELLING: Read every word of text in the thumbnail. Is every word spelled correctly? Check letter by letter. If any word has repeated letters (e.g. "ASLEEEP"), missing letters, or misspellings, fix the text.

If BOTH checks pass, return the thumbnail EXACTLY as-is with no changes.
If EITHER check fails, output a corrected version of the thumbnail with the issues fixed. Keep everything else identical — same composition, colors, layout, style.

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
) -> Image.Image | None:
    """Edit an existing thumbnail with high-level instructions."""
    api_client = genai.Client(api_key=API_KEY)

    thumb = source_image.copy()
    thumb.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)

    prompt = f"""IMAGE 1: A thumbnail that needs editing.

TASK: Make the following changes to this thumbnail:
{edit_instructions}

Keep everything else exactly the same. Only modify what is explicitly requested.

Output in 16:9 format."""

    print(f"\nEditing with instructions: {edit_instructions[:100]}...")

    try:
        response = _api_call_with_timeout(api_client, MODEL, [thumb, prompt],
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

        result = edit_thumbnail(edit_image, args.prompt)

        if result is None:
            print("Edit failed")
            sys.exit(1)

        if args.output:
            output_path = date_folder / args.output
        else:
            output_path = date_folder / f"{time_stamp}_edited.png"

        result.save(output_path)
        print(f"\nSaved: {output_path}")
        print(f"Size: {result.size}")
        return [str(output_path)]

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

    # Load swipe examples once for all variations
    if args.swipe_files == "":
        # No --swipe-files arg: load all
        swipe_examples = load_swipe_examples()
    else:
        # Explicit list (possibly empty = none selected)
        swipe_filter = [f.strip() for f in args.swipe_files.split(',') if f.strip()]
        swipe_examples = load_swipe_examples(only_files=swipe_filter) if swipe_filter else []

    # === IMAGINE MODE (no source needed) ===
    if args.mode == "imagine":
        print(f"Mode: IMAGINE — generating from creativity")
        reference_photos = load_reference_photos(max_photos=args.refs)
        if not reference_photos:
            print("Warning: No reference photos found. Results may vary.")

        output_paths = []
        for i in range(args.variations):
            print(f"\n--- Variation {i + 1}/{args.variations} ---")
            result = imagine_thumbnail(
                reference_photos=reference_photos,
                additional_prompt=args.prompt,
                video_title=args.title,
                swipe_examples=swipe_examples,
            )
            if result is None:
                print(f"Failed to generate variation {i + 1}")
                continue
            # Verify identity and spelling
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
                            anon_level=0,
                        )
                    if result is None or result == BLOCKED_SENTINEL:
                        break
                else:
                    print(f"  Face still doesn't match after {max_face_retries + 1} attempts, keeping best result")

        if result is None or result == BLOCKED_SENTINEL:
            print(f"Failed to generate variation {i + 1}")
            continue

        # Verify spelling with the existing pass
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
