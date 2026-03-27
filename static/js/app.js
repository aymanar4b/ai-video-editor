// ═══════════════════════════════════════════════════════════════════════════
// AUTEUR AI — Frontend JavaScript
// ═══════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    initToasts();
    initEditor();
    initThumbnails();
});

// ─── TOAST NOTIFICATIONS ────────────────────────────────────────────────────

function initToasts() {
    if (!document.querySelector('.toast-container')) {
        const container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
}

function showToast(message, type = 'error', duration = 10000) {
    const container = document.querySelector('.toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icon = type === 'error' ? '!' : '\u2713';
    const title = type === 'error' ? 'Error' : 'Success';

    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-body">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${escapeHtml(message)}</div>
            ${type === 'error' ? `<div class="toast-actions"><button class="toast-copy-btn" onclick="copyToastError(this)">Copy Error</button></div>` : ''}
        </div>
        <button class="toast-close" onclick="dismissToast(this)">&times;</button>
    `;

    container.appendChild(toast);

    if (duration > 0) {
        setTimeout(() => dismissToast(toast.querySelector('.toast-close')), duration);
    }
}

function dismissToast(btn) {
    const toast = btn.closest('.toast');
    if (!toast || toast.classList.contains('toast-exit')) return;
    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 250);
}

function copyToastError(btn) {
    const message = btn.closest('.toast-body').querySelector('.toast-message').textContent;
    navigator.clipboard.writeText(message).then(() => {
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy Error'; }, 1500);
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

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
            overlay.classList.add('hidden');
            showToast(data.error || 'Upload failed', 'error');
            return;
        }

        // Start polling for progress
        pollProgress(data.task_id);
    } catch (err) {
        overlay.classList.add('hidden');
        showToast(err.message, 'error');
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
                overlay.classList.add('hidden');
                showToast(data.error, 'error');
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

    // ─── Client Management ───────────────────────────────────────────
    const clientSelect = document.getElementById('clientSelect');
    const newClientBtn = document.getElementById('newClientBtn');
    const newClientForm = document.getElementById('newClientForm');
    const newClientName = document.getElementById('newClientName');
    const saveClientBtn = document.getElementById('saveClientBtn');
    const refPhotosSection = document.getElementById('refPhotosSection');
    const refPhotosGrid = document.getElementById('refPhotosGrid');
    const refUploadZone = document.getElementById('refUploadZone');
    const refFileInput = document.getElementById('refFileInput');

    newClientBtn.addEventListener('click', () => {
        newClientForm.classList.toggle('hidden');
        newClientName.focus();
    });

    saveClientBtn.addEventListener('click', async () => {
        const name = newClientName.value.trim();
        if (!name) return;
        const formData = new FormData();
        formData.append('name', name);
        const res = await fetch('/api/clients', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.slug) {
            const opt = document.createElement('option');
            opt.value = data.slug;
            opt.textContent = data.slug;
            clientSelect.appendChild(opt);
            clientSelect.value = data.slug;
            clientSelect.dispatchEvent(new Event('change'));
            newClientForm.classList.add('hidden');
            newClientName.value = '';
        }
    });

    newClientName.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') saveClientBtn.click();
    });

    clientSelect.addEventListener('change', () => {
        const slug = clientSelect.value;
        if (slug) {
            refPhotosSection.classList.remove('hidden');
            loadReferences(slug);
        } else {
            refPhotosSection.classList.add('hidden');
            refPhotosGrid.innerHTML = '';
        }
    });

    async function loadReferences(slug) {
        refPhotosGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">Loading...</p>';
        const res = await fetch(`/api/clients/${slug}/references`);
        const photos = await res.json();
        refPhotosGrid.innerHTML = '';
        if (photos.length === 0) {
            refPhotosGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">No reference photos yet</p>';
            return;
        }
        photos.forEach(photo => {
            const item = document.createElement('div');
            item.className = 'ref-photo-item';
            item.innerHTML = `
                <img src="${photo.url}" alt="${photo.name}">
                <button class="ref-delete-btn" data-name="${photo.name}" title="Remove">&times;</button>
            `;
            item.querySelector('.ref-delete-btn').addEventListener('click', async (e) => {
                e.stopPropagation();
                const name = e.target.dataset.name;
                await fetch(`/api/clients/${slug}/references/${name}`, { method: 'DELETE' });
                loadReferences(slug);
            });
            refPhotosGrid.appendChild(item);
        });
    }

    // Reference photo upload
    refUploadZone.addEventListener('click', () => refFileInput.click());
    refUploadZone.addEventListener('dragover', (e) => { e.preventDefault(); refUploadZone.classList.add('dragover'); });
    refUploadZone.addEventListener('dragleave', () => refUploadZone.classList.remove('dragover'));
    refUploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        refUploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) uploadRefPhotos(e.dataTransfer.files);
    });
    refFileInput.addEventListener('change', () => {
        if (refFileInput.files.length) uploadRefPhotos(refFileInput.files);
    });

    async function uploadRefPhotos(files) {
        const slug = clientSelect.value;
        if (!slug) return;
        const formData = new FormData();
        for (const f of files) formData.append('photos', f);
        refUploadZone.querySelector('p').textContent = `Uploading ${files.length} photos...`;
        await fetch(`/api/clients/${slug}/references`, { method: 'POST', body: formData });
        refUploadZone.querySelector('p').innerHTML = 'Drop face photos or <span class="coral-text">browse</span>';
        refFileInput.value = '';
        loadReferences(slug);
    }

    // ─── Mode Switching ─────────────────────────────────────────────
    window._thumbMode = 'replicate';
    const modeButtons = [
        document.getElementById('modeReplicate'),
        document.getElementById('modeMashup'),
        document.getElementById('modeImagine'),
    ];
    const modeDesc = document.getElementById('modeDescription');
    const sourceCard = document.getElementById('sourceCard');
    const sourceBSection = document.getElementById('sourceBSection');
    const sourceALabel = document.getElementById('sourceALabel');
    const skipMatchOption = document.getElementById('skipMatchOption');
    const thumbPrompt = document.getElementById('thumbPrompt');

    const modeDescriptions = {
        replicate: 'Recreate an existing thumbnail with your face swapped in.',
        mashup: 'Merge two thumbnails together — takes the best elements from both.',
        imagine: 'AI creates a thumbnail from scratch using the playbook. Add instructions or leave blank for full creativity.',
    };
    const modePlaceholders = {
        replicate: "e.g. 'Make expression confident and serious' or 'Boost contrast, make text pop more'",
        mashup: "e.g. 'Use the composition from A and the color scheme from B' or 'Combine the text style of A with the background of B'",
        imagine: "e.g. 'Results-forward style with $50k revenue number' or 'Counterintuitive statement: Stop Using Calendly' — leave blank for full AI creativity",
    };

    modeButtons.forEach(btn => {
        if (!btn) return;
        btn.addEventListener('click', () => {
            modeButtons.forEach(b => b && b.classList.remove('active'));
            btn.classList.add('active');
            window._thumbMode = btn.dataset.mode;

            modeDesc.textContent = modeDescriptions[window._thumbMode];
            thumbPrompt.placeholder = modePlaceholders[window._thumbMode];

            // Show/hide source card for imagine mode
            if (window._thumbMode === 'imagine') {
                sourceCard.classList.add('hidden');
                skipMatchOption.classList.add('hidden');
            } else {
                sourceCard.classList.remove('hidden');
                skipMatchOption.classList.remove('hidden');
            }

            // Show/hide source B for mashup
            if (window._thumbMode === 'mashup') {
                sourceBSection.classList.remove('hidden');
                sourceALabel.textContent = 'THUMBNAIL A';
            } else {
                sourceBSection.classList.add('hidden');
                sourceALabel.textContent = 'SOURCE THUMBNAIL';
            }
        });
    });

    // ─── Source Toggle (A) ────────────────────────────────────────────
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

    // Upload zone A
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

    // ─── Source Toggle (B — mashup) ──────────────────────────────────
    const btnYoutube2 = document.getElementById('btnYoutube2');
    const btnUpload2 = document.getElementById('btnUpload2');
    const youtubeInput2 = document.getElementById('youtubeInput2');
    const uploadInput2 = document.getElementById('uploadInput2');
    const thumbUploadZone2 = document.getElementById('thumbUploadZone2');
    const thumbFile2 = document.getElementById('thumbFile2');

    if (btnYoutube2) {
        btnYoutube2.addEventListener('click', () => {
            btnYoutube2.classList.add('active');
            btnUpload2.classList.remove('active');
            youtubeInput2.classList.remove('hidden');
            uploadInput2.classList.add('hidden');
        });
        btnUpload2.addEventListener('click', () => {
            btnUpload2.classList.add('active');
            btnYoutube2.classList.remove('active');
            uploadInput2.classList.remove('hidden');
            youtubeInput2.classList.add('hidden');
        });
    }
    if (thumbUploadZone2) {
        thumbUploadZone2.addEventListener('click', () => thumbFile2.click());
        thumbFile2.addEventListener('change', () => {
            if (thumbFile2.files.length) {
                thumbUploadZone2.querySelector('p').textContent = thumbFile2.files[0].name;
            }
        });
    }

    // ─── Sliders ─────────────────────────────────────────────────────
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

    // Generate button — require client selection
    const generateBtn = document.getElementById('generateBtn');
    if (generateBtn) {
        generateBtn.disabled = true;
        generateBtn.addEventListener('click', () => generateThumbnails());
    }

    // Enable/disable generate based on client selection
    if (clientSelect && generateBtn) {
        clientSelect.addEventListener('change', () => {
            generateBtn.disabled = !clientSelect.value;
        });
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
    const mode = window._thumbMode || 'replicate';
    formData.append('mode', mode);

    // Source A (not needed for imagine mode)
    if (mode !== 'imagine') {
        const btnYoutube = document.getElementById('btnYoutube');
        if (btnYoutube.classList.contains('active')) {
            formData.append('youtube_url', document.getElementById('youtubeUrl').value);
        } else {
            const thumbFile = document.getElementById('thumbFile');
            if (thumbFile.files.length) {
                formData.append('image', thumbFile.files[0]);
            }
        }
    }

    // Source B (mashup only)
    if (mode === 'mashup') {
        const btnYoutube2 = document.getElementById('btnYoutube2');
        if (btnYoutube2.classList.contains('active')) {
            formData.append('youtube_url2', document.getElementById('youtubeUrl2').value);
        } else {
            const thumbFile2 = document.getElementById('thumbFile2');
            if (thumbFile2.files.length) {
                formData.append('image2', thumbFile2.files[0]);
            }
        }
    }

    formData.append('variations', document.getElementById('variations').value);
    formData.append('refs', document.getElementById('refs').value);
    formData.append('skip_match', document.getElementById('skipMatch').checked);
    formData.append('prompt', document.getElementById('thumbPrompt').value);
    formData.append('video_title', document.getElementById('videoTitle').value);
    formData.append('client', document.getElementById('clientSelect').value);

    try {
        const response = await fetch('/api/thumbnails', {
            method: 'POST',
            body: formData,
        });

        const data = await response.json();
        if (!response.ok || data.error) {
            overlay.classList.add('hidden');
            showToast(data.error || 'Failed to start generation', 'error');
            return;
        }
        pollThumbnailProgress(data.task_id);
    } catch (err) {
        overlay.classList.add('hidden');
        showToast(err.message, 'error');
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
                    window._thumbPaths = data.thumbnails;
                    grid.innerHTML = data.thumbnails.map((path, i) =>
                        `<div class="thumb-result-item" data-index="${i}">
                            <img src="/api/download/${path}" alt="Generated thumbnail">
                            <a href="/api/download/${path}" download class="thumb-download-btn">Download</a>
                        </div>`
                    ).join('');
                    // Click to open lightbox
                    grid.querySelectorAll('.thumb-result-item img').forEach(img => {
                        img.addEventListener('click', (e) => {
                            const idx = parseInt(e.target.closest('.thumb-result-item').dataset.index);
                            openLightbox(idx);
                        });
                    });
                }
                return;
            }

            if (data.state === 'error') {
                overlay.classList.add('hidden');
                showToast(data.error, 'error');
                return;
            }

            setTimeout(poll, 1000);
        } catch (err) {
            setTimeout(poll, 2000);
        }
    };

    poll();
}

// ─── LIGHTBOX ───────────────────────────────────────────────────────────────

let _lightboxIndex = 0;

function openLightbox(index) {
    _lightboxIndex = index;
    const paths = window._thumbPaths || [];
    if (!paths.length) return;

    const existing = document.querySelector('.lightbox-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.innerHTML = `
        <div class="lightbox-container">
            <button class="lightbox-arrow lightbox-prev">&lsaquo;</button>
            <img class="lightbox-img" src="/api/download/${paths[index]}" alt="Thumbnail preview">
            <button class="lightbox-arrow lightbox-next">&rsaquo;</button>
            <button class="lightbox-close">&times;</button>
            <span class="lightbox-counter">${index + 1} / ${paths.length}</span>
            <a class="lightbox-download" href="/api/download/${paths[index]}" download>Download</a>
        </div>
    `;

    document.body.appendChild(overlay);

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeLightbox();
    });

    overlay.querySelector('.lightbox-close').addEventListener('click', closeLightbox);
    overlay.querySelector('.lightbox-prev').addEventListener('click', () => navigateLightbox(-1));
    overlay.querySelector('.lightbox-next').addEventListener('click', () => navigateLightbox(1));

    document.addEventListener('keydown', lightboxKeyHandler);
}

function navigateLightbox(dir) {
    const paths = window._thumbPaths || [];
    if (!paths.length) return;
    _lightboxIndex = (_lightboxIndex + dir + paths.length) % paths.length;

    const overlay = document.querySelector('.lightbox-overlay');
    if (!overlay) return;

    overlay.querySelector('.lightbox-img').src = `/api/download/${paths[_lightboxIndex]}`;
    overlay.querySelector('.lightbox-counter').textContent = `${_lightboxIndex + 1} / ${paths.length}`;
    overlay.querySelector('.lightbox-download').href = `/api/download/${paths[_lightboxIndex]}`;
}

function closeLightbox() {
    const overlay = document.querySelector('.lightbox-overlay');
    if (overlay) overlay.remove();
    document.removeEventListener('keydown', lightboxKeyHandler);
}

function lightboxKeyHandler(e) {
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowLeft') navigateLightbox(-1);
    if (e.key === 'ArrowRight') navigateLightbox(1);
}
