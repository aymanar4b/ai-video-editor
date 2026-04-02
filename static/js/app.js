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
    const toastMsg = btn.closest('.toast-body').querySelector('.toast-message');
    // Use innerText (not textContent) and trim to get only the visible error message
    const message = (toastMsg.innerText || toastMsg.textContent || '').trim();
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

function addGenerationGroup(paths, label, meta) {
    const placeholder = document.getElementById('previewPlaceholder');
    const grid = document.getElementById('previewGrid');
    if (!grid || !paths.length) return;

    placeholder.classList.add('hidden');
    grid.classList.remove('hidden');

    if (!window._thumbPaths) window._thumbPaths = [];
    const startIdx = window._thumbPaths.length;
    window._thumbPaths.push(...paths);

    // Build source thumbnail: from saved file, or derive from YouTube URL
    let sourceSrc = '';
    if (meta && meta.source_thumb) {
        sourceSrc = `/api/download/${meta.source_thumb}`;
    } else if (meta && meta.youtube_url) {
        const m = meta.youtube_url.match(/(?:youtu\.be\/|[?&]v=)([A-Za-z0-9_-]{11})/);
        if (m) sourceSrc = `https://img.youtube.com/vi/${m[1]}/hqdefault.jpg`;
    }

    // Build meta details HTML
    let metaHtml = '';
    if (meta) {
        const pills = [];
        if (meta.mode) pills.push(`<span class="gen-meta-pill">${escapeHtml(meta.mode)}</span>`);
        if (meta.client) pills.push(`<span class="gen-meta-pill">${escapeHtml(meta.client)}</span>`);
        if (meta.variations) pills.push(`<span class="gen-meta-pill">${meta.variations} vars</span>`);

        metaHtml = `<div class="gen-meta-panel hidden">
            ${sourceSrc ? `<div class="gen-meta-source"><img src="${sourceSrc}" alt="Source thumbnail"><span class="gen-meta-source-label">Source</span></div>` : ''}
            <div class="gen-meta-details">
                ${pills.length ? `<div class="gen-meta-pills">${pills.join('')}</div>` : ''}
                ${meta.video_title ? `<div class="gen-meta-row"><span class="gen-meta-key">Title</span><span class="gen-meta-val">${escapeHtml(meta.video_title)}</span></div>` : ''}
                ${meta.prompt ? `<div class="gen-meta-row"><span class="gen-meta-key">Prompt</span><span class="gen-meta-val">${escapeHtml(meta.prompt)}</span></div>` : ''}
                ${meta.youtube_url ? `<div class="gen-meta-row"><span class="gen-meta-key">URL</span><span class="gen-meta-val gen-meta-url">${escapeHtml(meta.youtube_url)}</span></div>` : ''}
            </div>
        </div>`;
    }

    const hasMeta = !!metaHtml;
    const group = document.createElement('div');
    group.className = 'generation-group';
    group.innerHTML = `
        <div class="generation-header${hasMeta ? ' clickable' : ''}">
            <span>Generated ${label}</span>
            ${hasMeta ? '<span class="gen-meta-chevron">&#9662;</span>' : ''}
        </div>
        ${metaHtml}
        ${sourceSrc ? `<div class="gen-source-row">
            <div class="thumb-result-item thumb-source-item">
                <img src="${sourceSrc}" alt="Source thumbnail" data-full-src="${sourceSrc}">
                <span class="thumb-source-badge">Source</span>
            </div>
        </div>` : ''}
        <div class="generation-thumbs">
            ${paths.map((path, i) =>
                `<div class="thumb-result-item" data-index="${startIdx + i}" data-path="${path}">
                    <img src="/api/download/${path}" alt="Generated thumbnail">
                    <button class="thumb-fav-btn" data-path="${path}" title="Favorite"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg></button>
                    <button class="thumb-delete-btn" data-path="${path}" title="Delete">&times;</button>
                    <a href="/api/download/${path}" download class="thumb-download-btn">Download</a>
                </div>`
            ).join('')}
        </div>
        <div class="gen-regen-bar">
            <button class="gen-regen-btn">Regenerate</button>
            <button class="gen-zip-btn" title="Download all as ZIP">Download All</button>
        </div>
    `;

    // Click header row to toggle meta panel
    const header = group.querySelector('.generation-header');
    const panel = group.querySelector('.gen-meta-panel');
    if (header && panel) {
        header.addEventListener('click', () => {
            panel.classList.toggle('hidden');
            header.classList.toggle('expanded');
        });
    }

    // Regenerate: load ALL original settings back into the form and scroll to it
    const regenBtn = group.querySelector('.gen-regen-btn');
    regenBtn.addEventListener('click', () => {
        if (meta) {
            // Mode (replicate/mashup/imagine)
            if (meta.mode) {
                const modeIds = {replicate: 'modeReplicate', mashup: 'modeMashup', collab: 'modeCollab', imagine: 'modeImagine'};
                const modeBtn = document.getElementById(modeIds[meta.mode]);
                if (modeBtn) modeBtn.click();
            }
            // Source URL
            if (meta.youtube_url) {
                const urlEl = document.getElementById('youtubeUrl');
                if (urlEl) { urlEl.value = meta.youtube_url; urlEl.dispatchEvent(new Event('input')); }
            }
            // Video title
            if (meta.video_title) {
                const titleEl = document.getElementById('videoTitle');
                if (titleEl) titleEl.value = meta.video_title;
            }
            // Client
            if (meta.client) {
                const clientEl = document.getElementById('clientSelect');
                if (clientEl) { clientEl.value = meta.client; clientEl.dispatchEvent(new Event('change')); }
            }
            // Prompt
            if (meta.prompt) {
                const promptEl = document.getElementById('thumbPrompt');
                if (promptEl) promptEl.value = meta.prompt;
            }
            // Variations slider
            if (meta.variations) {
                const varEl = document.getElementById('variations');
                const varVal = document.getElementById('variationsValue');
                if (varEl) { varEl.value = meta.variations; if (varVal) varVal.textContent = String(meta.variations).padStart(2, '0'); }
            }
            // Refs slider
            if (meta.refs) {
                const refsEl = document.getElementById('refs');
                const refsVal = document.getElementById('refsValue');
                if (refsEl) { refsEl.value = meta.refs; if (refsVal) refsVal.textContent = String(meta.refs).padStart(2, '0'); }
            }
            // Swipe file selections
            if (meta.swipe_files !== undefined) {
                const savedSwipes = new Set(meta.swipe_files.split(',').filter(s => s));
                document.querySelectorAll('#swipePickerGrid .swipe-pick-item').forEach(item => {
                    const name = item.dataset.name;
                    if (savedSwipes.has(name)) {
                        item.classList.add('selected');
                        if (window._swipeSelections) window._swipeSelections.add(name);
                    } else {
                        item.classList.remove('selected');
                        if (window._swipeSelections) window._swipeSelections.delete(name);
                    }
                });
            }
        }
        // Scroll to the prompt field so user can edit and hit Generate
        const promptEl = document.getElementById('thumbPrompt');
        if (promptEl) {
            promptEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            promptEl.focus();
        }
    });

    // Source thumbnail click — open in lightbox
    const sourceImg = group.querySelector('.thumb-source-item img');
    if (sourceImg) {
        const src = sourceImg.getAttribute('data-full-src');
        // Add source to _thumbPaths so lightbox can show it
        const sourceIdx = window._thumbPaths.length;
        window._thumbPaths.push(src);
        sourceImg.addEventListener('click', () => openLightbox(sourceIdx));
    }

    group.querySelectorAll('.generation-thumbs .thumb-result-item img').forEach(img => {
        img.addEventListener('click', (e) => {
            const idx = parseInt(e.target.closest('.thumb-result-item').dataset.index);
            openLightbox(idx);
        });
    });

    // Favorite buttons
    group.querySelectorAll('.thumb-fav-btn').forEach(btn => {
        const path = btn.dataset.path;
        // Check if already favorited
        if (window._favorites && window._favorites.has(path)) {
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';
            btn.classList.add('active');
        }
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const isFav = btn.classList.contains('active');
            const method = isFav ? 'DELETE' : 'POST';
            const res = await fetch('/api/favorites', {
                method, headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path}),
            });
            const data = await res.json();
            window._favorites = new Set(data.favorites);
            const starSvg = (filled) => `<svg width="14" height="14" viewBox="0 0 24 24" fill="${filled ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
            btn.innerHTML = starSvg(!isFav);
            btn.classList.toggle('active');
            _updateFavButton();
        });
    });

    // Delete buttons
    group.querySelectorAll('.thumb-delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const path = btn.dataset.path;
            const item = btn.closest('.thumb-result-item');
            const res = await fetch(`/api/thumbnails/${path}`, {method: 'DELETE'});
            if (res.ok) {
                item.remove();
                // Remove from _thumbPaths
                const idx = window._thumbPaths.indexOf(path);
                if (idx > -1) window._thumbPaths.splice(idx, 1);
                // If no thumbs left in group, remove group
                if (!group.querySelector('.generation-thumbs .thumb-result-item')) {
                    group.remove();
                }
            }
        });
    });

    // Download ZIP button
    const zipBtn = group.querySelector('.gen-zip-btn');
    if (zipBtn) {
        zipBtn.addEventListener('click', async () => {
            const res = await fetch('/api/download-zip', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({paths}),
            });
            if (res.ok) {
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'thumbnails.zip';
                a.click();
                URL.revokeObjectURL(url);
            }
        });
    }

    return group;
}

function _updateFavButton() {
    const btn = document.getElementById('viewFavoritesBtn');
    if (btn) {
        btn.classList.toggle('hidden', !window._favorites || window._favorites.size === 0);
    }
}

async function loadThumbnailHistory() {
    // Load favorites first so stars show correctly
    try {
        const favRes = await fetch('/api/favorites');
        window._favorites = new Set(await favRes.json());
        _updateFavButton();
    } catch { window._favorites = new Set(); }

    // View Favorites button
    const viewFavBtn = document.getElementById('viewFavoritesBtn');
    if (viewFavBtn) {
        viewFavBtn.addEventListener('click', () => {
            const grid = document.getElementById('previewGrid');
            const isFiltered = viewFavBtn.classList.contains('active');
            viewFavBtn.classList.toggle('active');

            if (!isFiltered) {
                // Show only favorites
                viewFavBtn.textContent = 'Show All';
                grid.querySelectorAll('.generation-group').forEach(g => g.classList.add('hidden'));
                grid.querySelectorAll('.thumb-result-item[data-path]').forEach(item => {
                    if (window._favorites.has(item.dataset.path)) {
                        item.closest('.generation-group').classList.remove('hidden');
                        item.style.display = '';
                    }
                });
            } else {
                // Show all
                viewFavBtn.textContent = 'Favorites';
                grid.querySelectorAll('.generation-group').forEach(g => g.classList.remove('hidden'));
                grid.querySelectorAll('.thumb-result-item').forEach(item => item.style.display = '');
            }
        });
    }

    try {
        const res = await fetch('/api/thumbnails/history');
        const groups = await res.json();
        if (!groups.length) return;

        const grid = document.getElementById('previewGrid');
        // Append in order (already newest-first from API)
        for (const g of groups) {
            const el = addGenerationGroup(g.paths, g.label, g.meta || null);
            if (el) grid.appendChild(el);
        }

        // Show clear history button
        let clearBtn = document.getElementById('clearHistoryBtn');
        if (!clearBtn) {
            const placeholder = document.getElementById('previewPlaceholder');
            clearBtn = document.createElement('button');
            clearBtn.id = 'clearHistoryBtn';
            clearBtn.className = 'clear-history-btn';
            clearBtn.textContent = 'Clear History';
            clearBtn.addEventListener('click', () => {
                grid.innerHTML = '';
                grid.classList.add('hidden');
                placeholder.classList.remove('hidden');
                window._thumbPaths = [];
                clearBtn.remove();
            });
            grid.parentElement.querySelector('.preview-dots').appendChild(clearBtn);
        }
    } catch (err) {
        // Silent fail — history is non-critical
    }
}

function initThumbnails() {
    window._thumbPaths = [];
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
        window._selectedRefs = new Set();

        const selectBtns = document.getElementById('refSelectBtns');

        if (photos.length === 0) {
            refPhotosGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">No reference photos yet</p>';
            if (selectBtns) selectBtns.style.display = 'none';
            return;
        }

        if (selectBtns) selectBtns.style.display = 'flex';

        // All selected by default
        photos.forEach(p => window._selectedRefs.add(p.name));

        photos.forEach(photo => {
            const item = document.createElement('div');
            item.className = 'ref-photo-item';
            item.dataset.name = photo.name;
            item.innerHTML = `
                <img src="${photo.url}" alt="${photo.name}">
                <div class="ref-check">\u2713</div>
                <button class="ref-delete-btn" data-name="${photo.name}" title="Remove">&times;</button>
            `;
            // Toggle selection on click
            item.addEventListener('click', () => {
                const name = item.dataset.name;
                if (item.classList.contains('deselected')) {
                    item.classList.remove('deselected');
                    window._selectedRefs.add(name);
                } else {
                    item.classList.add('deselected');
                    window._selectedRefs.delete(name);
                }
            });
            item.querySelector('.ref-delete-btn').addEventListener('click', async (e) => {
                e.stopPropagation();
                const name = e.target.dataset.name;
                await fetch(`/api/clients/${slug}/references/${name}`, { method: 'DELETE' });
                window._selectedRefs.delete(name);
                loadReferences(slug);
            });
            refPhotosGrid.appendChild(item);
        });

        // All / None buttons
        const allBtn = document.getElementById('refSelectAll');
        const noneBtn = document.getElementById('refSelectNone');
        if (allBtn) {
            allBtn.onclick = () => {
                refPhotosGrid.querySelectorAll('.ref-photo-item').forEach(item => {
                    item.classList.remove('deselected');
                    window._selectedRefs.add(item.dataset.name);
                });
            };
        }
        if (noneBtn) {
            noneBtn.onclick = () => {
                refPhotosGrid.querySelectorAll('.ref-photo-item').forEach(item => {
                    item.classList.add('deselected');
                    window._selectedRefs.delete(item.dataset.name);
                });
            };
        }
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
        document.getElementById('modeCollab'),
        document.getElementById('modeImagine'),
    ];
    const modeDesc = document.getElementById('modeDescription');
    const sourceCard = document.getElementById('sourceCard');
    const sourceBSection = document.getElementById('sourceBSection');
    const sourceALabel = document.getElementById('sourceALabel');
    const skipMatchOption = document.getElementById('skipMatchOption');
    const guestSection = document.getElementById('guestSection');
    const thumbPrompt = document.getElementById('thumbPrompt');

    const modeDescriptions = {
        replicate: 'Recreate an existing thumbnail with your face swapped in.',
        mashup: 'Merge two thumbnails together — takes the best elements from both.',
        collab: 'Recreate a thumbnail featuring the client + a guest (two people).',
        imagine: 'AI creates a thumbnail from scratch using the playbook. Add instructions or leave blank for full creativity.',
    };
    const modePlaceholders = {
        replicate: "e.g. 'Make expression confident and serious' or 'Boost contrast, make text pop more'",
        mashup: "e.g. 'Use the composition from A and the color scheme from B'",
        collab: "e.g. 'Client on the left, guest on the right' or 'Podcast interview style'",
        imagine: "e.g. 'Results-forward style with $50k revenue number' — leave blank for full AI creativity",
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

            // Show/hide guest section for collab
            if (window._thumbMode === 'collab') {
                guestSection.classList.remove('hidden');
            } else {
                guestSection.classList.add('hidden');
            }
        });
    });

    // ─── Guest Photos Upload (collab mode) ───────────────────────────
    const guestUploadZone = document.getElementById('guestUploadZone');
    const guestFiles = document.getElementById('guestFiles');
    const guestPreviewGrid = document.getElementById('guestPreviewGrid');
    window._guestFiles = [];

    if (guestUploadZone) {
        guestUploadZone.addEventListener('click', () => guestFiles.click());
        guestUploadZone.addEventListener('dragover', (e) => { e.preventDefault(); guestUploadZone.classList.add('drag-over'); });
        guestUploadZone.addEventListener('dragleave', () => guestUploadZone.classList.remove('drag-over'));
        guestUploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            guestUploadZone.classList.remove('drag-over');
            _addGuestFiles(e.dataTransfer.files);
        });
        guestFiles.addEventListener('change', () => _addGuestFiles(guestFiles.files));
    }

    function _addGuestFiles(files) {
        for (const f of files) {
            if (!f.type.startsWith('image/')) continue;
            window._guestFiles.push(f);
            const url = URL.createObjectURL(f);
            const idx = window._guestFiles.length - 1;
            const thumb = document.createElement('div');
            thumb.className = 'guest-thumb';
            thumb.innerHTML = `<img src="${url}"><button class="guest-remove" data-idx="${idx}">&times;</button>`;
            thumb.querySelector('.guest-remove').addEventListener('click', () => {
                window._guestFiles[idx] = null;
                thumb.remove();
            });
            guestPreviewGrid.appendChild(thumb);
        }
    }

    // ─── Source Toggle (A) ────────────────────────────────────────────
    btnYoutube.addEventListener('click', () => {
        btnYoutube.classList.add('active');
        btnUpload.classList.remove('active');
        youtubeInput.classList.remove('hidden');
        uploadInput.classList.add('hidden');
    });

    // Thumbnail preview on URL paste/input
    function extractVideoId(url) {
        const m = url.match(/(?:youtu\.be\/|[?&]v=)([A-Za-z0-9_-]{11})/);
        return m ? m[1] : null;
    }

    function showThumbPreview(inputEl, previewEl, imgEl) {
        const vid = extractVideoId(inputEl.value);
        if (vid) {
            imgEl.src = `https://img.youtube.com/vi/${vid}/maxresdefault.jpg`;
            imgEl.onerror = () => {
                imgEl.src = `https://img.youtube.com/vi/${vid}/hqdefault.jpg`;
            };
            previewEl.classList.remove('hidden');
        } else {
            previewEl.classList.add('hidden');
        }
    }

    const urlInput = document.getElementById('youtubeUrl');
    const thumbPreview = document.getElementById('thumbPreview');
    const thumbPreviewImg = document.getElementById('thumbPreviewImg');
    const triggerPreview1 = () => showThumbPreview(urlInput, thumbPreview, thumbPreviewImg);
    urlInput.addEventListener('input', triggerPreview1);
    urlInput.addEventListener('paste', () => setTimeout(triggerPreview1, 50));
    urlInput.addEventListener('change', triggerPreview1);
    urlInput.addEventListener('keyup', triggerPreview1);

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
    // Thumbnail preview for source B (mashup)
    const urlInput2 = document.getElementById('youtubeUrl2');
    const thumbPreview2 = document.getElementById('thumbPreview2');
    const thumbPreviewImg2 = document.getElementById('thumbPreviewImg2');
    if (urlInput2 && thumbPreview2) {
        const triggerPreview2 = () => showThumbPreview(urlInput2, thumbPreview2, thumbPreviewImg2);
        urlInput2.addEventListener('input', triggerPreview2);
        urlInput2.addEventListener('paste', () => setTimeout(triggerPreview2, 50));
        urlInput2.addEventListener('change', triggerPreview2);
        urlInput2.addEventListener('keyup', triggerPreview2);
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

    // ─── Swipe File Picker ──────────────────────────────────────────
    loadSwipePicker();

    // ─── Load Previous Thumbnails ────────────────────────────────────
    loadThumbnailHistory();
}

async function loadSwipePicker() {
    const grid = document.getElementById('swipePickerGrid');
    const selectAll = document.getElementById('swipeSelectAll');
    const selectNone = document.getElementById('swipeSelectNone');
    if (!grid) return;

    try {
        const res = await fetch('/api/swipe-examples');
        const examples = await res.json();
        if (!examples.length) {
            grid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">No swipe examples found</p>';
            return;
        }

        window._swipeSelections = new Set(); // none selected by default
        grid.innerHTML = examples.map(ex =>
            `<div class="swipe-pick-item" data-name="${ex.name}">
                <img src="${ex.url}" alt="${ex.name}" loading="lazy">
                <div class="swipe-pick-check">\u2713</div>
            </div>`
        ).join('');

        // Toggle on click
        grid.querySelectorAll('.swipe-pick-item').forEach(item => {
            item.addEventListener('click', () => {
                const name = item.dataset.name;
                if (item.classList.contains('selected')) {
                    item.classList.remove('selected');
                    window._swipeSelections.delete(name);
                } else {
                    item.classList.add('selected');
                    window._swipeSelections.add(name);
                }
            });
        });

        // Select all / none
        selectAll.addEventListener('click', () => {
            grid.querySelectorAll('.swipe-pick-item').forEach(item => {
                item.classList.add('selected');
                window._swipeSelections.add(item.dataset.name);
            });
        });
        selectNone.addEventListener('click', () => {
            grid.querySelectorAll('.swipe-pick-item').forEach(item => {
                item.classList.remove('selected');
            });
            window._swipeSelections.clear();
        });
    } catch (err) {
        grid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">Failed to load swipe examples</p>';
    }
}

function _buildFormData() {
    const formData = new FormData();
    const mode = window._thumbMode || 'replicate';
    formData.append('mode', mode);

    if (mode !== 'imagine') {
        const btnYoutube = document.getElementById('btnYoutube');
        if (btnYoutube.classList.contains('active')) {
            formData.append('youtube_url', document.getElementById('youtubeUrl').value);
        } else {
            const thumbFile = document.getElementById('thumbFile');
            if (thumbFile.files.length) formData.append('image', thumbFile.files[0]);
        }
    }

    if (mode === 'mashup') {
        const btnYoutube2 = document.getElementById('btnYoutube2');
        if (btnYoutube2.classList.contains('active')) {
            formData.append('youtube_url2', document.getElementById('youtubeUrl2').value);
        } else {
            const thumbFile2 = document.getElementById('thumbFile2');
            if (thumbFile2.files.length) formData.append('image2', thumbFile2.files[0]);
        }
    }

    formData.append('variations', document.getElementById('variations').value);
    formData.append('refs', document.getElementById('refs').value);
    formData.append('skip_match', document.getElementById('skipMatch').checked);
    formData.append('prompt', document.getElementById('thumbPrompt').value);
    formData.append('video_title', document.getElementById('videoTitle').value);
    if (window._swipeSelections) {
        formData.append('swipe_files', Array.from(window._swipeSelections).join(','));
    }
    formData.append('client', document.getElementById('clientSelect').value);

    // Selected reference photos (if any are deselected)
    if (window._selectedRefs && window._selectedRefs.size > 0) {
        formData.append('selected_refs', Array.from(window._selectedRefs).join(','));
    }

    // Guest photos for collab mode
    if (mode === 'collab' && window._guestFiles) {
        window._guestFiles.forEach((f, i) => {
            if (f) formData.append('guest_photos', f);
        });
    }

    return formData;
}

async function _submitGeneration(formData) {
    const overlay = document.getElementById('thumbProgressOverlay');
    const bar = document.getElementById('thumbProgressBar');
    const status = document.getElementById('thumbProgressStatus');

    overlay.classList.remove('hidden');
    bar.style.width = '10%';
    status.textContent = 'Starting generation...';

    try {
        const response = await fetch('/api/thumbnails', { method: 'POST', body: formData });
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

async function generateThumbnails() {
    const formData = _buildFormData();
    const prompt = document.getElementById('thumbPrompt').value.trim();

    // If there's a prompt, offer to enhance it first
    if (prompt) {
        const previewOverlay = document.getElementById('promptPreviewOverlay');
        const enhancedText = document.getElementById('enhancedPromptText');
        const progressOverlay = document.getElementById('thumbProgressOverlay');
        const bar = document.getElementById('thumbProgressBar');
        const status = document.getElementById('thumbProgressStatus');

        // Show progress while enhancing
        progressOverlay.classList.remove('hidden');
        bar.style.width = '5%';
        status.textContent = 'Enhancing prompt with AI...';

        try {
            const enhanceData = new FormData();
            enhanceData.append('prompt', prompt);
            enhanceData.append('youtube_url', document.getElementById('youtubeUrl')?.value || '');
            enhanceData.append('video_title', document.getElementById('videoTitle')?.value || '');

            const res = await fetch('/api/enhance-prompt', { method: 'POST', body: enhanceData });
            const data = await res.json();

            progressOverlay.classList.add('hidden');

            if (data.enhanced && data.enhanced !== prompt) {
                // Show preview modal
                enhancedText.value = data.enhanced;
                previewOverlay.classList.remove('hidden');

                // Wait for user choice
                await new Promise((resolve) => {
                    const approve = document.getElementById('approveEnhancedBtn');
                    const skip = document.getElementById('skipEnhancedBtn');

                    const cleanup = () => {
                        previewOverlay.classList.add('hidden');
                        approve.removeEventListener('click', onApprove);
                        skip.removeEventListener('click', onSkip);
                    };
                    const onApprove = () => {
                        // Use the (possibly edited) enhanced prompt — skip backend enhancement
                        formData.set('prompt', enhancedText.value);
                        formData.set('skip_enhance', 'true');
                        cleanup();
                        resolve();
                    };
                    const onSkip = () => {
                        // Keep original prompt — skip backend enhancement
                        formData.set('skip_enhance', 'true');
                        cleanup();
                        resolve();
                    };
                    approve.addEventListener('click', onApprove);
                    skip.addEventListener('click', onSkip);
                });
            }
        } catch (err) {
            progressOverlay.classList.add('hidden');
            // Enhancement failed, proceed with original
        }
    }

    _submitGeneration(formData);
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

                if (data.thumbnails && data.thumbnails.length) {
                    const now = new Date();
                    const timeStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
                    // Capture current form state as meta
                    const liveMeta = {
                        mode: window._thumbMode || 'replicate',
                        youtube_url: document.getElementById('youtubeUrl')?.value || '',
                        prompt: document.getElementById('thumbPrompt')?.value || '',
                        video_title: document.getElementById('videoTitle')?.value || '',
                        client: document.getElementById('clientSelect')?.value || '',
                        variations: document.getElementById('variations')?.value || '',
                        refs: document.getElementById('refs')?.value || '',
                        swipe_files: window._swipeSelections ? Array.from(window._swipeSelections).join(',') : '',
                    };
                    const group = addGenerationGroup(data.thumbnails, timeStr, liveMeta);
                    if (group) {
                        grid.prepend(group);

                        // Show clear history button
                        let clearBtn = document.getElementById('clearHistoryBtn');
                        if (!clearBtn) {
                            clearBtn = document.createElement('button');
                            clearBtn.id = 'clearHistoryBtn';
                            clearBtn.className = 'clear-history-btn';
                            clearBtn.textContent = 'Clear History';
                            clearBtn.addEventListener('click', () => {
                                grid.innerHTML = '';
                                grid.classList.add('hidden');
                                placeholder.classList.remove('hidden');
                                window._thumbPaths = [];
                                clearBtn.remove();
                            });
                            grid.parentElement.querySelector('.preview-dots').appendChild(clearBtn);
                        }
                        // Scroll to the new generation
                        group.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
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

function thumbSrc(path) {
    // If it's already a full URL or starts with /, use as-is; otherwise prepend /api/download/
    if (path.startsWith('http') || path.startsWith('/')) return path;
    return `/api/download/${path}`;
}

function openLightbox(index) {
    _lightboxIndex = index;
    const paths = window._thumbPaths || [];
    if (!paths.length) return;

    const existing = document.querySelector('.lightbox-overlay');
    if (existing) existing.remove();

    const src = thumbSrc(paths[index]);
    const overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.innerHTML = `
        <div class="lightbox-container">
            <button class="lightbox-arrow lightbox-prev">&lsaquo;</button>
            <img class="lightbox-img" src="${src}" alt="Thumbnail preview">
            <button class="lightbox-arrow lightbox-next">&rsaquo;</button>
            <button class="lightbox-close">&times;</button>
            <span class="lightbox-counter">${index + 1} / ${paths.length}</span>
            <a class="lightbox-download" href="${src}" download>Download</a>
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

    const src = thumbSrc(paths[_lightboxIndex]);
    overlay.querySelector('.lightbox-img').src = src;
    overlay.querySelector('.lightbox-counter').textContent = `${_lightboxIndex + 1} / ${paths.length}`;
    overlay.querySelector('.lightbox-download').href = src;
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
