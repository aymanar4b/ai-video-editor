#!/usr/bin/env python3
"""
Auteur AI — Flask Web UI for AI Video Editor

Run with:
    python app.py
    # Opens at http://localhost:5000
"""

import os
import subprocess
import threading
import uuid
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file

# ─── Config ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
EXECUTION_DIR = BASE_DIR / "execution"
TMP_DIR = BASE_DIR / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

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
    return render_template('thumbnails.html', active_page='thumbnails')


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
    variations = request.form.get('variations', '3')
    refs = request.form.get('refs', '2')
    skip_match = request.form.get('skip_match') == 'true'
    prompt = request.form.get('prompt', '')

    # Handle image upload
    source_path = None
    if 'image' in request.files:
        f = request.files['image']
        source_path = TMP_DIR / f"thumb_source_{f.filename}"
        f.save(str(source_path))

    tasks[task_id] = {
        'state': 'running',
        'progress': 10,
        'status': 'Starting thumbnail generation...',
        'log': '',
        'thumbnails': [],
    }

    def run_thumbnails():
        try:
            tasks[task_id]['status'] = 'Generating thumbnails...'
            tasks[task_id]['progress'] = 30

            cmd = [PYTHON, str(EXECUTION_DIR / "recreate_thumbnails.py")]

            if youtube_url:
                cmd += ["--youtube", youtube_url]
            elif source_path:
                cmd += ["--source", str(source_path)]
            else:
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['error'] = 'No source provided'
                return

            cmd += ["--variations", variations, "--refs", refs]
            if skip_match:
                cmd.append("--no-match")
            if prompt:
                cmd += ["--prompt", prompt]

            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=str(BASE_DIR), timeout=300
            )
            tasks[task_id]['log'] = result.stdout + result.stderr
            tasks[task_id]['progress'] = 90

            if result.returncode != 0:
                tasks[task_id]['state'] = 'error'
                tasks[task_id]['error'] = 'Thumbnail generation failed'
                return

            # Find generated thumbnails
            from datetime import datetime
            today_dir = TMP_DIR / "thumbnails" / datetime.now().strftime("%Y%m%d")
            if today_dir.exists():
                thumbs = sorted(today_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
                tasks[task_id]['thumbnails'] = [
                    f"thumbnails/{today_dir.name}/{t.name}" for t in thumbs[:int(variations)]
                ]

            tasks[task_id]['state'] = 'done'
            tasks[task_id]['progress'] = 100
            tasks[task_id]['status'] = 'Complete!'

        except subprocess.TimeoutExpired:
            tasks[task_id]['state'] = 'error'
            tasks[task_id]['error'] = 'Generation timed out'
        except Exception as e:
            tasks[task_id]['state'] = 'error'
            tasks[task_id]['error'] = str(e)

    thread = threading.Thread(target=run_thumbnails, daemon=True)
    thread.start()

    return jsonify({'task_id': task_id})


# ─── API: Progress Polling ────────────────────────────────────────────────────

@app.route('/api/progress/<task_id>')
def api_progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'state': 'error', 'error': 'Task not found'}), 404
    return jsonify(task)


# ─── API: File Download ──────────────────────────────────────────────────────

@app.route('/api/download/<path:filename>')
def api_download(filename):
    file_path = TMP_DIR / filename
    if file_path.exists():
        return send_file(str(file_path))
    return 'File not found', 404


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n  Auteur AI - Video Editor")
    print("  http://localhost:8080\n")
    app.run(debug=False, port=8080)
