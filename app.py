#!/usr/bin/env python3
"""
Auteur AI — Flask Web UI for AI Video Editor

Run with:
    python app.py
    # Opens at http://localhost:5000
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from functools import wraps

from flask import Flask, render_template, request, jsonify, send_file, Response

# ─── Config ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
EXECUTION_DIR = BASE_DIR / "execution"
TMP_DIR = BASE_DIR / ".tmp"
TMP_DIR.mkdir(exist_ok=True)
CLIENTS_DIR = TMP_DIR / "clients"
CLIENTS_DIR.mkdir(exist_ok=True)

VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python3"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB upload limit

# Task tracking
tasks = {}

# Persist tasks to disk so a server restart (OOM, redeploy) doesn't leave
# clients polling with a task_id the new process has never heard of. The
# subprocess handle itself can't be restored across restarts, so any task
# found in 'queued' or 'running' state at startup is marked as error with a
# clear message — far more useful than a bare 404 "Task not found".
TASKS_FILE = TMP_DIR / "tasks.json"
_tasks_lock = threading.Lock()


def _load_tasks():
    if not TASKS_FILE.exists():
        return
    try:
        loaded = json.loads(TASKS_FILE.read_text())
    except Exception as e:
        print(f"[tasks-persist] failed to load {TASKS_FILE}: {e}")
        return
    for tid, t in loaded.items():
        if t.get('state') in ('queued', 'running'):
            t['state'] = 'error'
            t['error'] = 'Server restarted during generation — any completed thumbnails are in History below.'
            t['progress'] = 100
        t['proc'] = None
        tasks[tid] = t
    print(f"[tasks-persist] restored {len(loaded)} task(s) from disk")


def _persist_tasks_loop():
    while True:
        time.sleep(2)
        try:
            # Copy keys first so we don't fault if another thread mutates
            # the dict while we build the snapshot.
            items = list(tasks.items())
            snapshot = {
                tid: {k: v for k, v in t.items() if k != 'proc'}
                for tid, t in items
            }
            with _tasks_lock:
                tmp = TASKS_FILE.with_suffix('.json.tmp')
                tmp.write_text(json.dumps(snapshot))
                tmp.replace(TASKS_FILE)
        except Exception as e:
            print(f"[tasks-persist] write failed: {e}")


_load_tasks()
threading.Thread(target=_persist_tasks_loop, daemon=True).start()


# ─── HEIC upload support ─────────────────────────────────────────────────────
# iPhone users regularly upload .HEIC photos. Browsers can't render them
# (outside Safari) and most downstream tools (Gemini, Replicate, OpenCV,
# older PIL) don't decode them. Transcode to JPEG at upload time so every
# path below sees a normal image file.
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception as _heif_e:
    print(f"[heic] pillow-heif not available: {_heif_e}")

_HEIC_EXTS = ('.heic', '.heif')


def _save_image_upload(fstore, dest_path: Path) -> Path:
    """Save a Flask FileStorage to disk, transcoding HEIC/HEIF → JPEG so
    the rest of the pipeline only ever sees formats PIL and browsers can
    handle. Returns the actual saved path (extension may change)."""
    from PIL import Image as _PImg, ImageOps as _PImgOps
    ext = Path(fstore.filename or '').suffix.lower()
    if ext in _HEIC_EXTS:
        jpeg_path = dest_path.with_suffix('.jpg')
        img = _PImg.open(fstore.stream)
        img = _PImgOps.exif_transpose(img)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(str(jpeg_path), 'JPEG', quality=92)
        return jpeg_path
    fstore.save(str(dest_path))
    return dest_path

# Concurrency cap for thumbnail generation. Default is effectively unlimited —
# every submitted job runs immediately. Set THUMB_CONCURRENCY env var to a small
# integer (e.g. 2) if you start hitting Gemini 429s or local resource limits.
THUMB_CONCURRENCY = int(os.getenv('THUMB_CONCURRENCY', '999'))
thumb_sem = threading.Semaphore(THUMB_CONCURRENCY)


# ─── Basic HTTP Auth ──────────────────────────────────────────────────────────
# Enabled only when APP_PASSWORD env var is set (i.e. in production / Render).
# Locally you can leave APP_PASSWORD unset and skip auth entirely. Username is
# fixed to "tikscale"; password comes from the env var. One shared credential.

APP_PASSWORD = os.getenv('APP_PASSWORD', '').strip()
APP_USERNAME = os.getenv('APP_USERNAME', 'tikscale').strip()


def _check_auth(username: str, password: str) -> bool:
    return (username == APP_USERNAME and password == APP_PASSWORD)


def _auth_required_response():
    return Response(
        'Authentication required.\n', 401,
        {'WWW-Authenticate': 'Basic realm="TikScale Thumbnail Generator"'},
    )


def _require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # If no password is configured (e.g. local dev), skip auth.
        if not APP_PASSWORD:
            return view(*args, **kwargs)
        auth = request.authorization
        if not auth or not _check_auth(auth.username or '', auth.password or ''):
            return _auth_required_response()
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def _global_auth_check():
    """Gate every request behind basic auth when APP_PASSWORD is set.

    Leaves /health open so Render's uptime checks don't fail.
    """
    if not APP_PASSWORD:
        return None
    if request.path == '/health' or request.path.startswith('/static/'):
        return None
    auth = request.authorization
    if not auth or not _check_auth(auth.username or '', auth.password or ''):
        return _auth_required_response()
    return None


@app.route('/health')
def health():
    """Render uptime check endpoint — unauthenticated on purpose."""
    return {'ok': True}, 200


def _extract_error_from_log(full_log: str, returncode: int, default: str = "Generation failed.") -> str:
    """Pull a human-readable error from a subprocess log instead of
    surfacing a generic "Check logs" message to the UI.

    Priority order:
      1. Known rate-limit / quota strings
      2. Known OpenAI-specific error lines
      3. The last Python Traceback's final line (the actual exception)
      4. The last line starting with "Error:" or "ERROR"
      5. If exit code != 0, the final non-empty log line
      6. Default fallback
    """
    if not full_log:
        return default

    lines = [ln.strip() for ln in full_log.splitlines() if ln.strip()]
    full = "\n".join(lines)

    # Rate limit / quota
    if "429" in full or "RESOURCE_EXHAUSTED" in full:
        return "Gemini API quota exhausted — wait and retry."
    if "insufficient_quota" in full or "You exceeded your current quota" in full:
        return "OpenAI API quota exhausted — check billing."
    if "invalid_api_key" in full or "Incorrect API key" in full:
        return "OpenAI API key is invalid — check OPENAI_API_KEY in .env"
    if "OPENAI_API_KEY not set" in full:
        return "OPENAI_API_KEY is empty — paste your OpenAI key into .env and restart."
    if "content_policy_violation" in full or "safety system" in full.lower():
        return "Blocked by OpenAI content filter."

    # Python traceback — find the last exception line
    last_traceback_idx = None
    for i, ln in enumerate(lines):
        if "Traceback (most recent call last)" in ln:
            last_traceback_idx = i
    if last_traceback_idx is not None:
        # The exception is usually the last line of the traceback block
        for ln in reversed(lines[last_traceback_idx:]):
            if ln and not ln.startswith("File ") and not ln.startswith("  "):
                return f"Crash: {ln[:200]}"

    # Last "Error:" or "ERROR" line
    for ln in reversed(lines):
        if ln.startswith("Error:") or ln.startswith("ERROR") or ln.startswith("OpenAI error:"):
            return ln[:200]

    if returncode != 0 and lines:
        return f"Exit {returncode}: {lines[-1][:200]}"

    return default


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def editor():
    videos = sorted([
        f.name for f in TMP_DIR.iterdir()
        if f.suffix.lower() in ('.mp4', '.mov', '.mkv', '.avi', '.webm')
    ])
    return render_template('editor.html', active_page='editor', existing_videos=videos)


@app.route('/thumbnails')
def thumbnails():
    clients = sorted([d.name for d in CLIENTS_DIR.iterdir() if d.is_dir()])
    return render_template('thumbnails.html', active_page='thumbnails', clients=clients)


@app.route('/about')
def about():
    return render_template('about.html', active_page='about')


# ─── API: Video Editing ──────────────────────────────────────────────────────

@app.route('/api/edit', methods=['POST'])
def api_edit():
    task_id = str(uuid.uuid4())[:8]

    # Get input file
    input_path = None
    if 'video' in request.files:
        f = request.files['video']
        if f.filename:
            input_path = TMP_DIR / f.filename
            f.save(str(input_path))
            print(f"[{task_id}] Uploaded: {f.filename} ({input_path.stat().st_size / (1024*1024):.1f} MB)")
    elif request.form.get('existing'):
        input_path = TMP_DIR / request.form['existing']
        print(f"[{task_id}] Using existing: {request.form['existing']}")

    if not input_path or not input_path.exists():
        print(f"[{task_id}] ERROR: No valid video file. files={list(request.files.keys())}, form={dict(request.form)}")
        return jsonify({'error': 'No video file provided'}), 400

    # Parse options
    enhance_audio = request.form.get('enhance_audio') == 'true'
    detect_restarts = request.form.get('detect_restarts') == 'true'
    add_teaser = request.form.get('add_teaser') == 'true'
    teaser_start = request.form.get('teaser_start', '60')

    # Output paths
    stem = input_path.stem
    edited_path = TMP_DIR / f"{stem}_edited.mp4"
    final_path = TMP_DIR / f"{stem}_final.mp4" if add_teaser else edited_path

    tasks[task_id] = {
        'state': 'running',
        'progress': 10,
        'status': 'Starting video processing...',
        'log': '',
        'output_file': final_path.name,
    }

    def run_edit():
        try:
            # Step 1: VAD silence removal
            tasks[task_id]['status'] = 'Removing silences & enhancing audio...'
            tasks[task_id]['progress'] = 20

            cmd = [
                PYTHON,
                str(EXECUTION_DIR / "jump_cut_vad_parallel.py"),
                str(input_path),
                str(edited_path),
            ]
            if enhance_audio:
                cmd.append("--enhance-audio")
            if detect_restarts:
                cmd.append("--detect-restarts")

            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(BASE_DIR), timeout=600
            )
            tasks[task_id]['log'] = result.stdout + result.stderr
            tasks[task_id]['progress'] = 70

            if result.returncode != 0:
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['error'] = 'Video editing failed'
                return

            # Step 2: Swivel teaser
            if add_teaser and edited_path.exists():
                tasks[task_id]['status'] = 'Adding swivel teaser...'
                tasks[task_id]['progress'] = 75

                cmd2 = [
                    PYTHON,
                    str(EXECUTION_DIR / "insert_3d_transition.py"),
                    str(edited_path),
                    str(final_path),
                    "--teaser-start", teaser_start,
                ]

                bg_image = TMP_DIR / "bg.png"
                if bg_image.exists():
                    cmd2 += ["--bg-image", str(bg_image)]

                result2 = subprocess.run(
                    cmd2, capture_output=True, text=True, cwd=str(BASE_DIR), timeout=300
                )
                tasks[task_id]['log'] += '\n' + result2.stdout + result2.stderr

                if result2.returncode != 0:
                    tasks[task_id]['output_file'] = edited_path.name

            # Done
            output_path = Path(TMP_DIR / tasks[task_id]['output_file'])
            tasks[task_id]['state'] = 'done'
            tasks[task_id]['progress'] = 100
            tasks[task_id]['status'] = 'Complete!'

            if input_path.exists() and output_path.exists():
                tasks[task_id]['input_size'] = f"{input_path.stat().st_size / (1024*1024):.1f}"
                tasks[task_id]['output_size'] = f"{output_path.stat().st_size / (1024*1024):.1f}"
                saved = (input_path.stat().st_size - output_path.stat().st_size) / (1024*1024)
                tasks[task_id]['saved'] = f"{saved:.1f}"

        except subprocess.TimeoutExpired:
            tasks[task_id]['state'] = 'error'
            tasks[task_id]['error'] = 'Processing timed out'
        except Exception as e:
            tasks[task_id]['state'] = 'error'
            tasks[task_id]['error'] = str(e)

    thread = threading.Thread(target=run_edit, daemon=True)
    thread.start()

    return jsonify({'task_id': task_id})


# ─── API: Thumbnail Generation ───────────────────────────────────────────────

@app.route('/api/thumbnails', methods=['POST'])
def api_thumbnails():
    task_id = str(uuid.uuid4())[:8]

    youtube_url = request.form.get('youtube_url', '')
    youtube_url2 = request.form.get('youtube_url2', '')
    variations = request.form.get('variations', '3')
    refs = request.form.get('refs', '2')
    skip_match = request.form.get('skip_match') == 'true'
    prompt = request.form.get('prompt', '')
    video_title = request.form.get('video_title', '')
    client_slug = request.form.get('client', '')
    mode = request.form.get('mode', 'replicate')
    swipe_files = request.form.get('swipe_files', '')
    client_swipes = request.form.get('client_swipe_files', '')  # comma-separated filenames
    selected_refs = request.form.get('selected_refs', '')
    skip_enhance = request.form.get('skip_enhance') == 'true'
    swipe_source_pool = request.form.get('swipe_source_pool', '')
    swipe_source_name = request.form.get('swipe_source_name', '')
    swipe_source_slug = request.form.get('swipe_source_slug', '')
    provider = request.form.get('provider', 'gemini')
    openai_quality = request.form.get('openai_quality', 'high')

    # Handle guest photo uploads (collab mode)
    # Filenames namespaced by task_id so concurrent jobs don't clobber each other.
    guest_photo_paths = []
    if mode == 'collab' and 'guest_photos' in request.files:
        guest_files = request.files.getlist('guest_photos')
        for gf in guest_files:
            if gf.filename:
                gp = TMP_DIR / f"guest_{task_id}_{gf.filename}"
                saved = _save_image_upload(gf, gp)
                guest_photo_paths.append(str(saved))

    # Handle swipe file as source (resolve to a file path)
    source_path = None
    if swipe_source_pool and swipe_source_name:
        if swipe_source_pool == 'client' and swipe_source_slug:
            swipe_src = CLIENTS_DIR / swipe_source_slug / "swipe_examples" / swipe_source_name
        else:
            swipe_src = EXECUTION_DIR / "swipe_examples" / "individual" / swipe_source_name
        if swipe_src.exists():
            source_path = swipe_src
            print(f"Using swipe file as source: {swipe_src}")

    # Handle image uploads
    if source_path is None and 'image' in request.files:
        f = request.files['image']
        if f.filename:
            source_path = _save_image_upload(
                f, TMP_DIR / f"thumb_source_{task_id}_{f.filename}"
            )
            print(f"[{task_id}] Uploaded source image saved to {source_path} "
                  f"({source_path.stat().st_size} bytes)")
        else:
            print(f"[{task_id}] Image field present but filename empty")
    elif source_path is None and mode != 'imagine':
        print(f"[{task_id}] No source provided: youtube_url={bool(youtube_url)}, "
              f"image_in_files={'image' in request.files}, mode={mode}")

    source_path2 = None
    if 'image2' in request.files:
        f2 = request.files['image2']
        if f2.filename:
            source_path2 = _save_image_upload(
                f2, TMP_DIR / f"thumb_source2_{task_id}_{f2.filename}"
            )

    tasks[task_id] = {
        'state': 'queued',
        'progress': 5,
        'status': 'Queued — waiting for an open slot...',
        'log': '',
        'thumbnails': [],
        'cancelled': False,
        'proc': None,
    }

    def run_thumbnails():
        # Cap concurrency: excess jobs sit in 'queued' state until a slot frees up.
        with thumb_sem:
            # If user cancelled while we were queued, exit immediately without
            # spawning the subprocess.
            if tasks[task_id].get('cancelled'):
                tasks[task_id]['state'] = 'cancelled'
                tasks[task_id]['status'] = 'Cancelled before starting'
                tasks[task_id]['progress'] = 100
                return
            try:
                tasks[task_id]['state'] = 'running'
                tasks[task_id]['status'] = 'Starting thumbnail generation...'
                tasks[task_id]['progress'] = 10
                _run_thumbnail_job(
                    task_id, mode, youtube_url, youtube_url2, source_path, source_path2,
                    variations, refs, skip_match, prompt, video_title, client_slug,
                    swipe_files, client_swipes, selected_refs, skip_enhance, guest_photo_paths,
                    provider, openai_quality,
                )
            except Exception as e:
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['error'] = str(e)

    def _run_thumbnail_job(
        task_id, mode, youtube_url, youtube_url2, source_path, source_path2,
        variations, refs, skip_match, prompt, video_title, client_slug,
        swipe_files, client_swipes, selected_refs, skip_enhance, guest_photo_paths,
        provider="gemini", openai_quality="high",
    ):
        try:

            cmd = [PYTHON, "-u", str(EXECUTION_DIR / "recreate_thumbnails.py")]
            cmd += ["--mode", mode]

            # Imagine mode doesn't need a source
            if mode == "imagine":
                pass
            elif youtube_url:
                cmd += ["--youtube", youtube_url]
            elif source_path:
                cmd += ["--source", str(source_path)]
            else:
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['error'] = 'No source provided'
                return

            # Second source for mashup mode
            if mode == "mashup":
                if youtube_url2:
                    cmd += ["--youtube2", youtube_url2]
                elif source_path2:
                    cmd += ["--source2", str(source_path2)]

            cmd += ["--variations", variations, "--refs", refs]
            if skip_match:
                cmd.append("--no-match")
            if prompt:
                cmd += ["--prompt", prompt]
            if video_title:
                cmd += ["--title", video_title]
            if client_slug:
                client_refs = CLIENTS_DIR / client_slug / "reference_photos"
                if client_refs.exists():
                    cmd += ["--ref-dir", str(client_refs)]
            if selected_refs:
                cmd += ["--selected-refs", selected_refs]
            if swipe_files:
                cmd += ["--swipe-files", swipe_files]
            # Resolve client-specific swipe filenames into absolute paths.
            # The frontend sends just the filenames; they live under
            # .tmp/clients/<slug>/swipe_examples/.
            if client_swipes and client_slug:
                client_swipe_dir = CLIENTS_DIR / client_slug / "swipe_examples"
                resolved = []
                for name in client_swipes.split(','):
                    name = name.strip()
                    if not name:
                        continue
                    p = client_swipe_dir / name
                    if p.exists():
                        resolved.append(str(p))
                if resolved:
                    cmd += ["--client-swipe-files", ",".join(resolved)]
            if skip_enhance:
                cmd.append("--skip-enhance")
            if guest_photo_paths:
                cmd += ["--guest-photos", ",".join(guest_photo_paths)]
            if provider and provider != "gemini":
                cmd += ["--provider", provider]
            if provider == "openai" and openai_quality:
                cmd += ["--openai-quality", openai_quality]

            num_vars = int(variations)
            log_lines = []
            run_timestamp = None  # Will be parsed from script output

            # Debug log to file (avoids stdout buffering)
            debug_log = BASE_DIR / "thumb_debug.log"
            with open(debug_log, "a") as dl:
                dl.write(f"\n=== [{task_id}] {datetime.now()} ===\n")
                dl.write(f"CMD: {' '.join(cmd)}\n")

            # Stream output for real progress
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(BASE_DIR)
            )
            # Expose the proc so the /cancel endpoint can kill it
            tasks[task_id]['proc'] = proc

            # Kill process after 10 minutes if it hangs
            kill_timer = threading.Timer(600, lambda: proc.kill())
            kill_timer.daemon = True
            kill_timer.start()

            for line in proc.stdout:
                log_lines.append(line.rstrip())
                tasks[task_id]['log'] = '\n'.join(log_lines[-30:])

                if line.startswith('TIMESTAMP:'):
                    run_timestamp = line.split(':', 1)[1].strip()
                elif 'Imagine mode' in line or 'Mashup generating' in line:
                    tasks[task_id]['status'] = 'Loading reference photos...'
                    tasks[task_id]['progress'] = 20
                elif 'Downloaded thumbnail' in line or 'Loading source' in line:
                    tasks[task_id]['status'] = 'Analyzing face direction...'
                    tasks[task_id]['progress'] = 20
                elif 'Enhancing prompt' in line:
                    tasks[task_id]['status'] = 'Enhancing prompt with AI...'
                    tasks[task_id]['progress'] = 25
                elif 'Detected pose' in line:
                    tasks[task_id]['status'] = 'Loading reference photos...'
                    tasks[task_id]['progress'] = 30
                elif line.strip().startswith('--- Variation'):
                    try:
                        cur = int(line.split('Variation')[1].split('/')[0].strip())
                        base = 30
                        per_var = 60 // num_vars
                        tasks[task_id]['progress'] = base + (cur - 1) * per_var
                        tasks[task_id]['status'] = f'Generating variation {cur}/{num_vars}...'
                    except (ValueError, IndexError):
                        pass
                elif 'Saved:' in line:
                    tasks[task_id]['progress'] = min(tasks[task_id]['progress'] + 10, 90)
                elif 'Error: 429' in line or 'RESOURCE_EXHAUSTED' in line:
                    tasks[task_id]['status'] = 'API rate limited, retrying...'
                elif 'FACE MISMATCH' in line:
                    tasks[task_id]['status'] = 'Wrong face detected, regenerating...'
                elif 'Face match score' in line:
                    tasks[task_id]['status'] = 'Checking face identity...'
                elif 'RETRY: Content filter blocked' in line:
                    tasks[task_id]['status'] = 'Content filter blocked, retrying with heavier anonymization...'
                elif 'All anonymization levels exhausted' in line:
                    tasks[task_id]['status'] = 'Content filter blocked all attempts for this variation'
                elif 'Failed to generate' in line:
                    pass  # already tracked

            proc.wait()
            kill_timer.cancel()

            # If user cancelled while running, short-circuit before doing
            # any cleanup or "no thumbnails generated" error reporting.
            if tasks[task_id].get('cancelled'):
                tasks[task_id]['state'] = 'cancelled'
                tasks[task_id]['status'] = 'Cancelled'
                tasks[task_id]['progress'] = 100
                return
            with open(debug_log, "a") as dl:
                dl.write(f"EXIT CODE: {proc.returncode}\n")
                dl.write(f"TIMESTAMP parsed: {run_timestamp}\n")
                # Capture enhanced prompt if present
                for ll in log_lines:
                    if 'Enhanced prompt:' in ll or (log_lines and any('Enhanced prompt:' in x for x in log_lines)):
                        break
                # Write all lines for full context
                dl.write(f"FULL LOG ({len(log_lines)} lines):\n")
                for ll in log_lines:
                    dl.write(f"  {ll}\n")
                dl.write(f"LAST 20 LINES:\n")
                for ll in log_lines[-20:]:
                    dl.write(f"  {ll}\n")

            # Find generated thumbnails — only from THIS run's timestamp
            today_dir = TMP_DIR / "thumbnails" / datetime.now().strftime("%Y%m%d")
            found_thumbs = []
            with open(debug_log, "a") as dl:
                dl.write(f"TODAY DIR: {today_dir} exists={today_dir.exists()}\n")
                if today_dir.exists():
                    all_pngs = list(today_dir.glob("*.png"))
                    dl.write(f"ALL PNGs in dir: {[p.name for p in all_pngs]}\n")
                    dl.write(f"Looking for pattern: {run_timestamp}_*.png\n")
            if today_dir.exists():
                if run_timestamp:
                    # Match only files from this run (e.g. 143052_1.png, 143052_2.png)
                    thumbs = sorted(today_dir.glob(f"{run_timestamp}_*.png"))
                else:
                    # Fallback: most recent files
                    thumbs = sorted(today_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
                    thumbs = thumbs[:num_vars]
                found_thumbs = [
                    f"thumbnails/{today_dir.name}/{t.name}" for t in thumbs
                ]
                tasks[task_id]['thumbnails'] = found_thumbs

            if found_thumbs:
                tasks[task_id]['state'] = 'done'
                tasks[task_id]['progress'] = 100
                tasks[task_id]['status'] = f'Generated {len(found_thumbs)} thumbnail(s)!'

                # Save generation metadata alongside thumbnails
                try:
                    import json as _json
                    meta = {
                        'mode': mode,
                        'provider': provider,
                        'youtube_url': youtube_url,
                        'youtube_url2': youtube_url2,
                        'prompt': prompt,
                        'video_title': video_title,
                        'client': client_slug,
                        'variations': variations,
                        'refs': refs,
                        'swipe_files': swipe_files,
                        'client_swipe_files': client_swipes,
                    }
                    # Save source thumbnail for reference
                    if youtube_url and run_timestamp:
                        try:
                            import re as _re
                            vid_match = _re.search(r'[?&]v=([A-Za-z0-9_-]{11})', youtube_url)
                            if vid_match:
                                vid_id = vid_match.group(1)
                                import urllib.request
                                source_img_path = today_dir / f"{run_timestamp}_source.jpg"
                                for qual in ['maxresdefault', 'hqdefault']:
                                    try:
                                        urllib.request.urlretrieve(
                                            f"https://img.youtube.com/vi/{vid_id}/{qual}.jpg",
                                            str(source_img_path)
                                        )
                                        meta['source_thumb'] = f"thumbnails/{today_dir.name}/{source_img_path.name}"
                                        break
                                    except Exception:
                                        continue
                        except Exception:
                            pass
                    elif source_path:
                        import shutil
                        src_copy = today_dir / f"{run_timestamp}_source{Path(str(source_path)).suffix}"
                        shutil.copy2(str(source_path), str(src_copy))
                        meta['source_thumb'] = f"thumbnails/{today_dir.name}/{src_copy.name}"

                    meta_path = today_dir / f"{run_timestamp}_meta.json"
                    with open(meta_path, 'w') as mf:
                        _json.dump(meta, mf)
                except Exception:
                    pass  # Metadata is non-critical
            else:
                # Extract a meaningful error from the log instead of "Check logs"
                full_log = '\n'.join(log_lines)
                error_msg = _extract_error_from_log(
                    full_log, proc.returncode,
                    default="No thumbnails were generated. All variations failed."
                )
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['progress'] = 100
                tasks[task_id]['error'] = error_msg
                tasks[task_id]['log'] = '\n'.join(log_lines[-50:])

        except subprocess.TimeoutExpired:
            tasks[task_id]['state'] = 'error'
            tasks[task_id]['error'] = 'Generation timed out'
        except Exception as e:
            tasks[task_id]['state'] = 'error'
            tasks[task_id]['error'] = str(e)

    thread = threading.Thread(target=run_thumbnails, daemon=True)
    thread.start()

    return jsonify({'task_id': task_id})


# ─── API: Image-URL proxy (for edit-mode logo URL previews) ──────────────────

@app.route('/api/fetch-image', methods=['POST'])
def api_fetch_image():
    """
    Download an image from a URL on behalf of the browser and return it
    as base64 so the frontend can preview it. Used by the edit modal's
    'Add from URL' flow to confirm the URL actually resolved to an image
    before the user commits to using it.
    """
    import base64 as _b64
    import urllib.request
    import urllib.error

    url = (request.json or {}).get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL required'}), 400
    if not (url.startswith('http://') or url.startswith('https://')):
        return jsonify({'error': 'URL must start with http:// or https://'}), 400

    try:
        req = urllib.request.Request(
            url,
            headers={
                # Some image hosts (incl. Google's img serving) block the
                # default Python UA. Pretend to be a regular browser.
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'image/*,*/*;q=0.8',
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            content_type = resp.headers.get('Content-Type', '').lower()
            data = resp.read(8 * 1024 * 1024)  # 8 MB hard cap
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'HTTP {e.code} — {e.reason}'}), 400
    except urllib.error.URLError as e:
        return jsonify({'error': f'Could not reach URL: {e.reason}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if 'image' not in content_type:
        return jsonify({'error': f'URL did not return an image (got {content_type or "unknown"})'}), 400

    # Sanity-check that PIL can actually decode it — catches bad MIME labels
    try:
        import io as _io
        from PIL import Image as _PILImage
        probe = _PILImage.open(_io.BytesIO(data))
        probe.verify()
    except Exception as e:
        return jsonify({'error': f'Image could not be decoded: {e}'}), 400

    # Figure out a clean extension for the data URL
    ext_map = {
        'image/png': 'png', 'image/jpeg': 'jpeg', 'image/jpg': 'jpeg',
        'image/webp': 'webp', 'image/gif': 'gif', 'image/svg+xml': 'svg+xml',
    }
    mime = content_type.split(';')[0].strip()
    ext = ext_map.get(mime, 'png')

    b64 = _b64.b64encode(data).decode('ascii')
    return jsonify({
        'data_url': f'data:image/{ext};base64,{b64}',
        'mime': mime,
        'size': len(data),
    })


# ─── API: Thumbnail Edit (Layer 1: text-based targeted edits) ────────────────

@app.route('/api/thumbnails/edit', methods=['POST'])
def api_thumbnails_edit():
    """
    Edit an existing generated thumbnail with a text instruction.
    Reuses the same job-tray flow + concurrency cap as /api/thumbnails.
    """
    task_id = str(uuid.uuid4())[:8]

    source_path_rel = (request.form.get('source_path') or '').strip()
    edit_prompt = (request.form.get('prompt') or '').strip()
    parent_meta_json = request.form.get('parent_meta', '')
    try:
        variations = max(1, min(5, int(request.form.get('variations', '1'))))
    except (TypeError, ValueError):
        variations = 1

    # Reference logo files uploaded directly
    ref_image_paths: list[str] = []
    if 'logo_files' in request.files:
        for i, lf in enumerate(request.files.getlist('logo_files')):
            if lf and lf.filename:
                # Namespace by task_id to avoid concurrent collisions
                dest = TMP_DIR / f"logo_{task_id}_{i}_{lf.filename}"
                saved = _save_image_upload(lf, dest)
                ref_image_paths.append(str(saved))

    # Optional style/layout reference — a single full-frame image that guides
    # the overall look. Distinct from reference logos (which are exact swaps).
    style_reference_path: str | None = None
    if 'style_reference' in request.files:
        sf = request.files['style_reference']
        if sf and sf.filename:
            dest = TMP_DIR / f"styleref_{task_id}_{sf.filename}"
            saved = _save_image_upload(sf, dest)
            style_reference_path = str(saved)

    # Reference logos by URL (already confirmed via /api/fetch-image preview).
    # We re-download on the server rather than round-trip the base64 from the
    # browser, to keep the request payload small.
    logo_urls_raw = (request.form.get('logo_urls') or '').strip()
    if logo_urls_raw:
        import urllib.request
        import urllib.error
        for j, u in enumerate(filter(None, (x.strip() for x in logo_urls_raw.split('\n')))):
            try:
                req = urllib.request.Request(u, headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/120.0.0.0 Safari/537.36'
                    ),
                    'Accept': 'image/*,*/*;q=0.8',
                })
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if 'image' not in (resp.headers.get('Content-Type') or '').lower():
                        continue
                    blob = resp.read(8 * 1024 * 1024)
                # Pick an extension from the URL or default to .png
                suffix = Path(u.split('?')[0]).suffix or '.png'
                if suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
                    suffix = '.png'
                dest = TMP_DIR / f"logo_{task_id}_url{j}{suffix}"
                dest.write_bytes(blob)
                ref_image_paths.append(str(dest))
            except Exception as e:
                print(f"[{task_id}] Failed to fetch logo URL {u}: {e}")

    if not source_path_rel or not edit_prompt:
        return jsonify({'error': 'source_path and prompt are required'}), 400

    # Resolve the source path safely — must live under TMP_DIR.
    source_abs = (TMP_DIR / source_path_rel).resolve()
    try:
        source_abs.relative_to(TMP_DIR.resolve())
    except ValueError:
        return jsonify({'error': 'Invalid source path'}), 400
    if not source_abs.exists():
        return jsonify({'error': 'Source thumbnail not found'}), 404

    # Parse parent meta so we can carry client/title forward into the new meta.
    parent_meta = {}
    if parent_meta_json:
        try:
            parent_meta = json.loads(parent_meta_json)
        except Exception:
            parent_meta = {}

    tasks[task_id] = {
        'state': 'queued',
        'progress': 5,
        'status': 'Queued — waiting for an open slot...',
        'log': '',
        'thumbnails': [],
        'cancelled': False,
        'proc': None,
    }

    def run_edit():
        with thumb_sem:
            if tasks[task_id].get('cancelled'):
                tasks[task_id]['state'] = 'cancelled'
                tasks[task_id]['status'] = 'Cancelled before starting'
                tasks[task_id]['progress'] = 100
                return
            try:
                tasks[task_id]['state'] = 'running'
                tasks[task_id]['status'] = 'Editing thumbnail...'
                tasks[task_id]['progress'] = 15

                cmd = [
                    PYTHON, "-u", str(EXECUTION_DIR / "recreate_thumbnails.py"),
                    "--edit", str(source_abs),
                    "--prompt", edit_prompt,
                    "--variations", str(variations),
                ]
                if ref_image_paths:
                    cmd += ["--reference-images", ",".join(ref_image_paths)]
                if style_reference_path:
                    cmd += ["--style-reference", style_reference_path]

                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=str(BASE_DIR)
                )
                tasks[task_id]['proc'] = proc

                kill_timer = threading.Timer(300, lambda: proc.kill())
                kill_timer.daemon = True
                kill_timer.start()

                log_lines = []
                run_timestamp = None
                for line in proc.stdout:
                    log_lines.append(line.rstrip())
                    tasks[task_id]['log'] = '\n'.join(log_lines[-30:])
                    if line.startswith('TIMESTAMP:'):
                        run_timestamp = line.split(':', 1)[1].strip()
                        tasks[task_id]['progress'] = 20
                    elif 'Loading image to edit' in line:
                        tasks[task_id]['status'] = 'Sending edit to Gemini...'
                        tasks[task_id]['progress'] = 30
                    elif line.strip().startswith('--- Variation'):
                        try:
                            cur = int(line.split('Variation')[1].split('/')[0].strip())
                            base = 30
                            per_var = 60 // variations
                            tasks[task_id]['progress'] = base + (cur - 1) * per_var
                            tasks[task_id]['status'] = (
                                f'Editing variation {cur}/{variations}...'
                                if variations > 1 else 'Applying edit...'
                            )
                        except (ValueError, IndexError):
                            pass
                    elif 'Saved:' in line:
                        tasks[task_id]['progress'] = min(tasks[task_id]['progress'] + 10, 90)
                    elif 'Error: 429' in line or 'RESOURCE_EXHAUSTED' in line:
                        tasks[task_id]['status'] = 'API rate limited, retrying...'

                proc.wait()
                kill_timer.cancel()

                if tasks[task_id].get('cancelled'):
                    tasks[task_id]['state'] = 'cancelled'
                    tasks[task_id]['status'] = 'Cancelled'
                    tasks[task_id]['progress'] = 100
                    return

                # Find produced edit files. recreate_thumbnails.py saves them as
                # {YYYYMMDD}/{HHMMSS}_edited_{N}.png (or _edited.png for legacy 1-var)
                today_dir = TMP_DIR / "thumbnails" / datetime.now().strftime("%Y%m%d")
                found = []
                if today_dir.exists() and run_timestamp:
                    found = sorted(today_dir.glob(f"{run_timestamp}_edited*.png"))

                if found:
                    rels = [f"thumbnails/{today_dir.name}/{p.name}" for p in found]
                    tasks[task_id]['thumbnails'] = rels
                    tasks[task_id]['state'] = 'done'
                    tasks[task_id]['progress'] = 100
                    tasks[task_id]['status'] = f'Edit complete ({len(rels)} variation{"s" if len(rels) != 1 else ""})!'

                    # Save metadata: carry parent client/title forward, mark as edit
                    try:
                        meta = {
                            'mode': 'edit',
                            'edited_from': source_path_rel,
                            'prompt': edit_prompt,
                            'video_title': parent_meta.get('video_title', ''),
                            'client': parent_meta.get('client', ''),
                            'variations': str(variations),
                            'source_thumb': source_path_rel,  # show the parent in history
                        }
                        meta_path = today_dir / f"{run_timestamp}_meta.json"
                        with open(meta_path, 'w') as mf:
                            json.dump(meta, mf)
                    except Exception:
                        pass
                else:
                    full_log = '\n'.join(log_lines)
                    # Pull the most relevant error line from the subprocess
                    # output instead of showing a generic "Check logs" string.
                    err = _extract_error_from_log(full_log, proc.returncode, default="Edit produced no output.")
                    tasks[task_id]['state'] = 'error'
                    tasks[task_id]['progress'] = 100
                    tasks[task_id]['error'] = err
                    tasks[task_id]['log'] = '\n'.join(log_lines[-50:])

            except Exception as e:
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['error'] = str(e)

    thread = threading.Thread(target=run_edit, daemon=True)
    thread.start()

    return jsonify({'task_id': task_id})


# ─── API: Clients & Reference Photos ────────────────────────────────────────

@app.route('/api/clients', methods=['GET'])
def api_clients():
    clients = sorted([d.name for d in CLIENTS_DIR.iterdir() if d.is_dir()])
    return jsonify(clients)


@app.route('/api/clients', methods=['POST'])
def api_create_client():
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Client name required'}), 400
    slug = name.lower().replace(' ', '-')
    client_dir = CLIENTS_DIR / slug
    refs_dir = client_dir / "reference_photos"
    refs_dir.mkdir(parents=True, exist_ok=True)
    # Save display name
    meta = {'name': name}
    (client_dir / "meta.json").write_text(json.dumps(meta))
    return jsonify({'slug': slug, 'name': name})


@app.route('/api/clients/<slug>/references', methods=['GET'])
def api_get_references(slug):
    refs_dir = CLIENTS_DIR / slug / "reference_photos"
    if not refs_dir.exists():
        return jsonify([])
    exts = {'.jpg', '.jpeg', '.png', '.webp'}
    photos = sorted([
        {'name': f.name, 'url': f'/api/clients/{slug}/references/{f.name}'}
        for f in refs_dir.iterdir() if f.suffix.lower() in exts
    ], key=lambda x: x['name'])
    return jsonify(photos)


@app.route('/api/clients/<slug>/references/<filename>')
def api_serve_reference(slug, filename):
    file_path = CLIENTS_DIR / slug / "reference_photos" / filename
    if file_path.exists():
        return send_file(str(file_path))
    return 'Not found', 404


@app.route('/api/clients/<slug>/references', methods=['POST'])
def api_upload_references(slug):
    refs_dir = CLIENTS_DIR / slug / "reference_photos"
    refs_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []
    files = request.files.getlist('photos')
    for f in files:
        if f.filename:
            save_path = refs_dir / f.filename
            saved = _save_image_upload(f, save_path)
            uploaded.append(saved.name)
            print(f"[{slug}] Uploaded reference: {saved.name}")
    return jsonify({'uploaded': uploaded, 'count': len(uploaded)})


@app.route('/api/clients/<slug>/references/<filename>', methods=['DELETE'])
def api_delete_reference(slug, filename):
    file_path = CLIENTS_DIR / slug / "reference_photos" / filename
    if file_path.exists():
        file_path.unlink()
        return jsonify({'deleted': filename})
    return jsonify({'error': 'Not found'}), 404


# ─── API: Client-Specific Swipe Files ────────────────────────────────────────

@app.route('/api/clients/<slug>/swipes', methods=['GET'])
def api_get_client_swipes(slug):
    swipes_dir = CLIENTS_DIR / slug / "swipe_examples"
    if not swipes_dir.exists():
        return jsonify([])
    exts = {'.jpg', '.jpeg', '.png', '.webp'}
    swipes = sorted([
        {'name': f.name, 'url': f'/api/clients/{slug}/swipes/{f.name}'}
        for f in swipes_dir.iterdir() if f.suffix.lower() in exts
    ], key=lambda x: x['name'])
    return jsonify(swipes)


@app.route('/api/clients/<slug>/swipes/<filename>')
def api_serve_client_swipe(slug, filename):
    file_path = CLIENTS_DIR / slug / "swipe_examples" / filename
    if file_path.exists():
        return send_file(str(file_path))
    return 'Not found', 404


@app.route('/api/clients/<slug>/swipes', methods=['POST'])
def api_upload_client_swipes(slug):
    swipes_dir = CLIENTS_DIR / slug / "swipe_examples"
    swipes_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []
    files = request.files.getlist('swipes')
    for f in files:
        if f.filename:
            save_path = swipes_dir / f.filename
            saved = _save_image_upload(f, save_path)
            uploaded.append(saved.name)
            print(f"[{slug}] Uploaded client swipe: {saved.name}")
    return jsonify({'uploaded': uploaded, 'count': len(uploaded)})


@app.route('/api/clients/<slug>/swipes/<filename>', methods=['DELETE'])
def api_delete_client_swipe(slug, filename):
    file_path = CLIENTS_DIR / slug / "swipe_examples" / filename
    if file_path.exists():
        file_path.unlink()
        return jsonify({'deleted': filename})
    return jsonify({'error': 'Not found'}), 404


# ─── API: Import YouTube Channel Thumbnails ─────────────────────────────────

@app.route('/api/clients/<slug>/import-youtube', methods=['POST'])
def api_import_youtube_thumbnails(slug):
    """Fetch video thumbnails from a YouTube channel URL using yt-dlp."""
    data = request.get_json(force=True)
    channel_url = (data.get('channel_url') or '').strip()
    if not channel_url:
        return jsonify({'error': 'channel_url is required'}), 400

    # Normalise: ensure we hit the /videos tab
    url = channel_url.rstrip('/')
    if not any(url.endswith(s) for s in ('/videos', '/streams', '/shorts')):
        url += '/videos'

    import shutil
    yt_dlp = shutil.which('yt-dlp', path=str(VENV_PYTHON.parent)) or shutil.which('yt-dlp') or 'yt-dlp'

    cmd = [
        yt_dlp,
        '--flat-playlist', '--no-download',
        '--playlist-end', '50',
        '-J',   # single JSON blob
        url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({'error': f'yt-dlp failed: {result.stderr[:300]}'}), 502
        import json as _json
        playlist = _json.loads(result.stdout)
        entries = playlist.get('entries') or []
        thumbnails = []
        for e in entries:
            title = e.get('title') or e.get('id', '')
            vid_id = e.get('id', '')
            # Use maxresdefault, fall back to hqdefault
            thumb_url = f'https://i.ytimg.com/vi/{vid_id}/maxresdefault.jpg'
            thumbnails.append({
                'id': vid_id,
                'title': title,
                'thumbnail': thumb_url,
            })
        return jsonify({'channel': playlist.get('channel', playlist.get('title', '')),
                        'thumbnails': thumbnails})
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'yt-dlp timed out — try a shorter URL'}), 504
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/clients/<slug>/import-youtube/save', methods=['POST'])
def api_save_youtube_thumbnails(slug):
    """Download selected YouTube thumbnails into the client's swipe folder."""
    data = request.get_json(force=True)
    items = data.get('items') or []  # [{id, title, thumbnail}, ...]
    if not items:
        return jsonify({'error': 'No items provided'}), 400

    swipes_dir = CLIENTS_DIR / slug / "swipe_examples"
    swipes_dir.mkdir(parents=True, exist_ok=True)

    import urllib.request
    saved = []
    for item in items:
        vid_id = item.get('id', '')
        title = item.get('title', vid_id)
        # Sanitise title for filename
        safe_title = "".join(c if c.isalnum() or c in ' -_' else '' for c in title).strip()[:60]
        fname = f"{safe_title}_{vid_id}.jpg" if safe_title else f"{vid_id}.jpg"
        dest = swipes_dir / fname
        if dest.exists():
            saved.append(fname)
            continue
        thumb_url = item.get('thumbnail', f'https://i.ytimg.com/vi/{vid_id}/maxresdefault.jpg')
        try:
            urllib.request.urlretrieve(thumb_url, str(dest))
            # Check if maxres returned a tiny placeholder (< 5KB) and fall back
            if dest.stat().st_size < 5000:
                dest.unlink()
                fallback = f'https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg'
                urllib.request.urlretrieve(fallback, str(dest))
            saved.append(fname)
            print(f"[{slug}] Imported YouTube thumb: {fname}")
        except Exception as exc:
            print(f"[{slug}] Failed to download {vid_id}: {exc}")
    return jsonify({'saved': saved, 'count': len(saved)})


# ─── API: Progress Polling ────────────────────────────────────────────────────

@app.route('/api/progress/<task_id>')
def api_progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'state': 'error', 'error': 'Task not found'}), 404
    # Strip non-JSON-serializable fields (the live Popen handle)
    return jsonify({k: v for k, v in task.items() if k != 'proc'})


@app.route('/api/thumbnails/<task_id>/cancel', methods=['POST'])
def api_cancel_thumbnail(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    if task.get('state') in ('done', 'error', 'cancelled'):
        return jsonify({'state': task.get('state'), 'noop': True})

    task['cancelled'] = True
    proc = task.get('proc')
    if proc and proc.poll() is None:
        # Job is actively running — kill the subprocess. The worker thread
        # will see the cancelled flag after proc.wait() returns and mark
        # state='cancelled'.
        try:
            proc.kill()
        except Exception:
            pass
    else:
        # Job is still queued (no proc yet). The worker checks the cancelled
        # flag immediately after acquiring the semaphore and exits cleanly.
        task['status'] = 'Cancelling...'

    return jsonify({'state': 'cancelling'})


# ─── API: Thumbnail History ──────────────────────────────────────────────────

@app.route('/api/thumbnails/history')
def api_thumbnail_history():
    """Return all saved thumbnails grouped by generation timestamp, newest first."""
    thumb_dir = BASE_DIR / ".tmp" / "thumbnails"
    if not thumb_dir.exists():
        return jsonify([])

    groups = []
    # Scan date folders in reverse order (newest date first)
    date_dirs = sorted(thumb_dir.iterdir(), reverse=True)
    for date_dir in date_dirs:
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name  # e.g. "20260329"

        # Group PNGs by timestamp prefix (HHMMSS)
        from collections import defaultdict
        ts_groups = defaultdict(list)
        ts_meta = {}
        for f in sorted(date_dir.glob("*.png")):
            # Skip source images (e.g. 104936_source.jpg saved as png)
            if '_source' in f.stem:
                continue
            parts = f.stem.split("_")  # e.g. "104936_1" -> ["104936", "1"]
            if len(parts) >= 2:
                ts_groups[parts[0]].append(f"thumbnails/{date_str}/{f.name}")

        # Load metadata files
        import json as _json
        for f in date_dir.glob("*_meta.json"):
            ts_key = f.stem.replace("_meta", "")
            try:
                with open(f) as mf:
                    ts_meta[ts_key] = _json.load(mf)
            except Exception:
                pass

        # Convert to list, newest timestamp first
        for ts in sorted(ts_groups.keys(), reverse=True):
            # Parse timestamp for display
            try:
                h, m = int(ts[:2]), int(ts[2:4])
                ampm = "AM" if h < 12 else "PM"
                h12 = h % 12 or 12
                time_label = f"{h12}:{m:02d} {ampm}"
            except (ValueError, IndexError):
                time_label = ts

            # Format date
            try:
                from datetime import datetime as dt
                d = dt.strptime(date_str, "%Y%m%d")
                date_label = d.strftime("%b %d")
            except ValueError:
                date_label = date_str

            entry = {
                'label': f"{date_label}, {time_label}",
                'paths': ts_groups[ts],
            }
            if ts in ts_meta:
                entry['meta'] = ts_meta[ts]
            groups.append(entry)

    return jsonify(groups)


# ─── API: Prompt Enhancement ─────────────────────────────────────────────────

@app.route('/api/enhance-prompt', methods=['POST'])
def api_enhance_prompt():
    """Enhance a user prompt using Gemini 2.5 Pro before generation."""
    prompt = request.form.get('prompt', '')
    youtube_url = request.form.get('youtube_url', '')
    video_title = request.form.get('video_title', '')

    if not prompt.strip():
        return jsonify({'enhanced': ''})

    try:
        cmd = [PYTHON, "-u", "-c", f"""
import sys, os, io
sys.path.insert(0, {repr(str(BASE_DIR))})
os.chdir({repr(str(BASE_DIR))})
# Suppress all debug output during import/execution
import logging
logging.disable(logging.CRITICAL)
old_stdout = sys.stdout
sys.stdout = io.StringIO()

from dotenv import load_dotenv
load_dotenv()
from PIL import Image
from execution.recreate_thumbnails import enhance_prompt, get_youtube_thumbnail
import re

source = None
url = {repr(youtube_url)}
if url:
    m = re.search(r'[?&]v=([A-Za-z0-9_-]{{11}})', url)
    if m:
        source = get_youtube_thumbnail(m.group(1))

# Capture only the enhanced prompt
sys.stdout = old_stdout
if source:
    result = enhance_prompt(source, {repr(prompt)}, {repr(video_title)})
    # Print ONLY the result, skip any debug output from enhance_prompt
    # by redirecting its prints
    pass
else:
    result = {repr(prompt)}

# Output clean result with delimiter
print("===ENHANCED===")
print(result)
"""]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        output = result.stdout.strip()
        # Extract only the content after our delimiter
        if '===ENHANCED===' in output:
            enhanced = output.split('===ENHANCED===', 1)[1].strip()
        else:
            enhanced = output
        if not enhanced:
            enhanced = prompt
        return jsonify({'enhanced': enhanced})
    except Exception as e:
        return jsonify({'enhanced': prompt, 'error': str(e)})


# ─── API: Favorites ──────────────────────────────────────────────────────────

FAVORITES_FILE = BASE_DIR / ".tmp" / "favorites.json"

def _load_favorites():
    if FAVORITES_FILE.exists():
        return json.loads(FAVORITES_FILE.read_text())
    return []

def _save_favorites(favs):
    FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAVORITES_FILE.write_text(json.dumps(favs))

@app.route('/api/favorites')
def api_get_favorites():
    return jsonify(_load_favorites())

@app.route('/api/favorites', methods=['POST'])
def api_add_favorite():
    path = request.json.get('path', '')
    if not path:
        return jsonify({'error': 'No path'}), 400
    favs = _load_favorites()
    if path not in favs:
        favs.append(path)
        _save_favorites(favs)
    return jsonify({'favorites': favs})

@app.route('/api/favorites', methods=['DELETE'])
def api_remove_favorite():
    path = request.json.get('path', '')
    favs = _load_favorites()
    if path in favs:
        favs.remove(path)
        _save_favorites(favs)
    return jsonify({'favorites': favs})


# ─── API: Delete Thumbnail ───────────────────────────────────────────────────

@app.route('/api/thumbnails/<path:thumb_path>', methods=['DELETE'])
def api_delete_thumbnail(thumb_path):
    """Delete a single generated thumbnail."""
    file_path = TMP_DIR / thumb_path
    if file_path.exists():
        file_path.unlink()
        # Also remove from favorites if present
        favs = _load_favorites()
        if thumb_path in favs:
            favs.remove(thumb_path)
            _save_favorites(favs)
        return jsonify({'deleted': thumb_path})
    return jsonify({'error': 'Not found'}), 404


# ─── API: Download ZIP ───────────────────────────────────────────────────────

@app.route('/api/download-zip', methods=['POST'])
def api_download_zip():
    """Download multiple thumbnails as a ZIP file."""
    import zipfile
    import tempfile
    paths = request.json.get('paths', [])
    if not paths:
        return jsonify({'error': 'No paths'}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    with zipfile.ZipFile(tmp.name, 'w') as zf:
        for p in paths:
            full = TMP_DIR / p
            if full.exists():
                zf.write(full, full.name)
    return send_file(tmp.name, as_attachment=True, download_name='thumbnails.zip')


# ─── API: File Download ──────────────────────────────────────────────────────

@app.route('/api/swipe-examples')
def api_swipe_examples():
    """List all available swipe file thumbnails."""
    swipe_dir = EXECUTION_DIR / "swipe_examples" / "individual"
    if not swipe_dir.exists():
        return jsonify([])
    thumbs = sorted(swipe_dir.glob("thumb_*.png"))
    return jsonify([
        {'name': t.name, 'url': f'/api/swipe-img/{t.name}'}
        for t in thumbs
    ])


@app.route('/api/swipe-img/<filename>')
def api_swipe_img(filename):
    """Serve a swipe example image."""
    file_path = EXECUTION_DIR / "swipe_examples" / "individual" / filename
    if file_path.exists():
        return send_file(str(file_path))
    return 'Not found', 404


@app.route('/api/download/<path:filename>')
def api_download(filename):
    file_path = TMP_DIR / filename
    if file_path.exists():
        return send_file(str(file_path))
    return 'File not found', 404


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n  Auteur AI - Video Editor")
    print("  http://localhost:3003\n")
    app.run(debug=False, port=3003)
