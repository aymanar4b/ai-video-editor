// ═══════════════════════════════════════════════════════════════════════════
// AUTEUR AI — Frontend JavaScript
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initEditor();
    initThumbnails();
});

// ─── EDITOR ──────────────────────────────────────────────────────────────────

function initEditor() {
    const uploadZone = document.getElementById('uploadZone');
    const videoFile = document.getElementById('videoFile');
    const existingFile = document.getElementById('existingFile');
    const editBtn = document.getElementById('editBtn');
    const addTeaser = document.getElementById('addTeaser');
    const teaserOptions = document.getElementById('teaserOptions');

    if (!uploadZone) return; // Not on editor page

    window._selectedFile = null;

    // Drag and drop
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    uploadZone.addEventListener('click', (e) => {
        // Don't double-trigger if clicking the Browse Files label (it already opens the input)
        if (e.target.closest('.btn-browse') || e.target === videoFile) return;
        videoFile.click();
    });

    videoFile.addEventListener('change', (e) => {
        if (e.target.files.length) {
            handleFileSelect(e.target.files[0]);
        }
    });

    function handleFileSelect(file) {
        window._selectedFile = file;
        existingFile.value = '';
        uploadZone.classList.add('has-file');
        uploadZone.querySelector('.upload-text').textContent = file.name;
        uploadZone.querySelector('.upload-hint').textContent =
            `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
        updateEditBtn();
    }

    existingFile.addEventListener('change', () => {
        if (existingFile.value) {
            window._selectedFile = null;
            uploadZone.classList.remove('has-file');
            uploadZone.querySelector('.upload-text').textContent = 'Drag and drop video files';
            uploadZone.querySelector('.upload-hint').textContent = 'LIMIT 200MB PER FILE \u2022 MP4, MOV, WEBM';
        }
        updateEditBtn();
    });

    function updateEditBtn() {
        const hasFile = window._selectedFile || existingFile.value;
        editBtn.disabled = !hasFile;
        // Update estimate
        const est = document.getElementById('estimateTime');
        if (est) est.textContent = hasFile ? '2m 45s' : '--';
    }

    // Teaser toggle
    if (addTeaser) {
        addTeaser.addEventListener('change', () => {
            teaserOptions.classList.toggle('hidden', !addTeaser.checked);
        });
    }

    // Edit button
    editBtn.addEventListener('click', () => startEditing());
}

async function startEditing() {
    const overlay = document.getElementById('progressOverlay');
    const bar = document.getElementById('progressBar');
    const status = document.getElementById('progressStatus');
    const log = document.getElementById('progressLog');

    overlay.classList.remove('hidden');
    bar.style.width = '5%';
    status.textContent = 'Uploading video...';
    log.textContent = '';

    const formData = new FormData();

    const videoFile = document.getElementById('videoFile');
    const existingFile = document.getElementById('existingFile');

    if (window._selectedFile) {
        formData.append('video', window._selectedFile);
    } else if (videoFile.files.length) {
        formData.append('video', videoFile.files[0]);
    } else if (existingFile.value) {
        formData.append('existing', existingFile.value);
    }

    formData.append('enhance_audio', document.getElementById('enhanceAudio').checked);
    formData.append('detect_restarts', document.getElementById('detectRestarts').checked);
    formData.append('add_teaser', document.getElementById('addTeaser').checked);
    formData.append('teaser_start', document.getElementById('teaserStart').value);

    bar.style.width = '15%';
    status.textContent = 'Processing...';

    try {
        const response = await fetch('/api/edit', {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();

        if (!response.ok || data.error) {
            status.textContent = `Error: ${data.error || 'Upload failed'}`;
            bar.style.width = '100%';
            bar.style.background = 'var(--red)';
            setTimeout(() => overlay.classList.add('hidden'), 3000);
            return;
        }

        // Start polling for progress
        pollProgress(data.task_id);
    } catch (err) {
        status.textContent = `Error: ${err.message}`;
        bar.style.width = '100%';
        bar.style.background = 'var(--red)';
        setTimeout(() => overlay.classList.add('hidden'), 3000);
    }
}

async function pollProgress(taskId) {
    const bar = document.getElementById('progressBar');
    const status = document.getElementById('progressStatus');
    const log = document.getElementById('progressLog');
    const overlay = document.getElementById('progressOverlay');

    const poll = async () => {
        try {
            const res = await fetch(`/api/progress/${taskId}`);
            const data = await res.json();

            bar.style.width = `${data.progress}%`;
            status.textContent = data.status;
            if (data.log) {
                log.textContent = data.log;
                log.scrollTop = log.scrollHeight;
            }

            if (data.state === 'done') {
                overlay.classList.add('hidden');
                showResult(data);
                return;
            }

            if (data.state === 'error') {
                status.textContent = `Error: ${data.error}`;
                bar.style.background = 'var(--red)';
                setTimeout(() => overlay.classList.add('hidden'), 3000);
                return;
            }

            setTimeout(poll, 1000);
        } catch (err) {
            setTimeout(poll, 2000);
        }
    };

    poll();
}

function showResult(data) {
    const overlay = document.getElementById('resultOverlay');
    const video = document.getElementById('resultVideo');
    const stats = document.getElementById('resultStats');
    const downloadLink = document.getElementById('downloadLink');

    overlay.classList.remove('hidden');
    video.src = `/api/download/${data.output_file}`;
    downloadLink.href = `/api/download/${data.output_file}`;
    downloadLink.download = data.output_file;

    if (data.input_size && data.output_size) {
        stats.textContent = `Input: ${data.input_size} MB \u2192 Output: ${data.output_size} MB | Saved: ${data.saved} MB`;
    }
}

function closeResult() {
    document.getElementById('resultOverlay').classList.add('hidden');
}

// ─── THUMBNAILS ──────────────────────────────────────────────────────────────

function initThumbnails() {
    const btnYoutube = document.getElementById('btnYoutube');
    const btnUpload = document.getElementById('btnUpload');
    const youtubeInput = document.getElementById('youtubeInput');
    const uploadInput = document.getElementById('uploadInput');

    if (!btnYoutube) return; // Not on thumbnails page

    // Toggle source mode
    btnYoutube.addEventListener('click', () => {
        btnYoutube.classList.add('active');
        btnUpload.classList.remove('active');
        youtubeInput.classList.remove('hidden');
        uploadInput.classList.add('hidden');
    });

    btnUpload.addEventListener('click', () => {
        btnUpload.classList.add('active');
        btnYoutube.classList.remove('active');
        uploadInput.classList.remove('hidden');
        youtubeInput.classList.add('hidden');
    });

    // Upload zone click
    const thumbUploadZone = document.getElementById('thumbUploadZone');
    const thumbFile = document.getElementById('thumbFile');
    if (thumbUploadZone) {
        thumbUploadZone.addEventListener('click', () => thumbFile.click());
        thumbFile.addEventListener('change', () => {
            if (thumbFile.files.length) {
                thumbUploadZone.querySelector('p').textContent = thumbFile.files[0].name;
            }
        });
    }

    // Slider values
    const variations = document.getElementById('variations');
    const refs = document.getElementById('refs');
    const variationsValue = document.getElementById('variationsValue');
    const refsValue = document.getElementById('refsValue');

    if (variations) {
        variations.addEventListener('input', () => {
            variationsValue.textContent = String(variations.value).padStart(2, '0');
        });
    }
    if (refs) {
        refs.addEventListener('input', () => {
            refsValue.textContent = String(refs.value).padStart(2, '0');
        });
    }

    // Generate button
    const generateBtn = document.getElementById('generateBtn');
    if (generateBtn) {
        generateBtn.addEventListener('click', () => generateThumbnails());
    }
}

async function generateThumbnails() {
    const overlay = document.getElementById('thumbProgressOverlay');
    const bar = document.getElementById('thumbProgressBar');
    const status = document.getElementById('thumbProgressStatus');

    overlay.classList.remove('hidden');
    bar.style.width = '10%';
    status.textContent = 'Starting generation...';

    const formData = new FormData();

    const btnYoutube = document.getElementById('btnYoutube');
    if (btnYoutube.classList.contains('active')) {
        formData.append('youtube_url', document.getElementById('youtubeUrl').value);
    } else {
        const thumbFile = document.getElementById('thumbFile');
        if (thumbFile.files.length) {
            formData.append('image', thumbFile.files[0]);
        }
    }

    formData.append('variations', document.getElementById('variations').value);
    formData.append('refs', document.getElementById('refs').value);
    formData.append('skip_match', document.getElementById('skipMatch').checked);
    formData.append('prompt', document.getElementById('thumbPrompt').value);

    try {
        const response = await fetch('/api/thumbnails', {
            method: 'POST',
            body: formData,
        });

        const taskId = (await response.json()).task_id;
        pollThumbnailProgress(taskId);
    } catch (err) {
        status.textContent = `Error: ${err.message}`;
    }
}

async function pollThumbnailProgress(taskId) {
    const bar = document.getElementById('thumbProgressBar');
    const status = document.getElementById('thumbProgressStatus');
    const overlay = document.getElementById('thumbProgressOverlay');
    const placeholder = document.getElementById('previewPlaceholder');
    const grid = document.getElementById('previewGrid');

    const poll = async () => {
        try {
            const res = await fetch(`/api/progress/${taskId}`);
            const data = await res.json();

            bar.style.width = `${data.progress}%`;
            status.textContent = data.status;

            if (data.state === 'done') {
                overlay.classList.add('hidden');

                // Show generated thumbnails
                if (data.thumbnails && data.thumbnails.length) {
                    placeholder.classList.add('hidden');
                    grid.classList.remove('hidden');
                    grid.innerHTML = data.thumbnails.map(path =>
                        `<a href="/api/download/${path}" download>
                            <img src="/api/download/${path}" alt="Generated thumbnail">
                        </a>`
                    ).join('');
                }
                return;
            }

            if (data.state === 'error') {
                status.textContent = `Error: ${data.error}`;
                setTimeout(() => overlay.classList.add('hidden'), 3000);
                return;
            }

            setTimeout(poll, 1500);
        } catch (err) {
            setTimeout(poll, 2000);
        }
    };

    poll();
}
