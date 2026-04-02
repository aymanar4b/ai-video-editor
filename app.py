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
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file

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
    selected_refs = request.form.get('selected_refs', '')
    skip_enhance = request.form.get('skip_enhance') == 'true'

    # Handle guest photo uploads (collab mode)
    guest_photo_paths = []
    if mode == 'collab' and 'guest_photos' in request.files:
        guest_files = request.files.getlist('guest_photos')
        for gf in guest_files:
            if gf.filename:
                gp = TMP_DIR / f"guest_{gf.filename}"
                gf.save(str(gp))
                guest_photo_paths.append(str(gp))

    # Handle image uploads
    source_path = None
    if 'image' in request.files:
        f = request.files['image']
        if f.filename:
            source_path = TMP_DIR / f"thumb_source_{f.filename}"
            f.save(str(source_path))

    source_path2 = None
    if 'image2' in request.files:
        f2 = request.files['image2']
        if f2.filename:
            source_path2 = TMP_DIR / f"thumb_source2_{f2.filename}"
            f2.save(str(source_path2))

    tasks[task_id] = {
        'state': 'running',
        'progress': 10,
        'status': 'Starting thumbnail generation...',
        'log': '',
        'thumbnails': [],
    }

    def run_thumbnails():
        try:
            tasks[task_id]['status'] = 'Downloading source thumbnail...'
            tasks[task_id]['progress'] = 10

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
            if skip_enhance:
                cmd.append("--skip-enhance")
            if guest_photo_paths:
                cmd += ["--guest-photos", ",".join(guest_photo_paths)]

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
                        'youtube_url': youtube_url,
                        'youtube_url2': youtube_url2,
                        'prompt': prompt,
                        'video_title': video_title,
                        'client': client_slug,
                        'variations': variations,
                        'refs': refs,
                        'swipe_files': swipe_files,
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
                # Extract a meaningful error from the log
                full_log = '\n'.join(log_lines)
                if '429' in full_log or 'RESOURCE_EXHAUSTED' in full_log:
                    error_msg = 'Gemini API quota exhausted. Upgrade to a paid plan or wait for quota reset.'
                elif proc.returncode != 0:
                    error_msg = 'Thumbnail generation failed. Check logs for details.'
                else:
                    error_msg = 'No thumbnails were generated. All variations failed.'
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
            f.save(str(save_path))
            uploaded.append(f.filename)
            print(f"[{slug}] Uploaded reference: {f.filename}")
    return jsonify({'uploaded': uploaded, 'count': len(uploaded)})


@app.route('/api/clients/<slug>/references/<filename>', methods=['DELETE'])
def api_delete_reference(slug, filename):
    file_path = CLIENTS_DIR / slug / "reference_photos" / filename
    if file_path.exists():
        file_path.unlink()
        return jsonify({'deleted': filename})
    return jsonify({'error': 'Not found'}), 404


# ─── API: Progress Polling ────────────────────────────────────────────────────

@app.route('/api/progress/<task_id>')
def api_progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'state': 'error', 'error': 'Task not found'}), 404
    return jsonify(task)


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
import sys, os, requests, io
sys.path.insert(0, {repr(str(BASE_DIR))})
os.chdir({repr(str(BASE_DIR))})
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
if source:
    print(enhance_prompt(source, {repr(prompt)}, {repr(video_title)}))
else:
    print({repr(prompt)})
"""]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        enhanced = result.stdout.strip()
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
