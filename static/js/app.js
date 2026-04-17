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
        if (meta.provider && meta.provider !== 'gemini') pills.push(`<span class="gen-meta-pill" style="background: rgba(16,163,127,0.2); color: #10a37f;">GPT Image 1.5</span>`);
        if (meta.provider === 'gemini' || !meta.provider) pills.push(`<span class="gen-meta-pill">Gemini 3 Pro</span>`);
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
    // Tag the group with its client slug so we can filter history by client.
    group.dataset.client = (meta && meta.client) ? meta.client : '';
    group.innerHTML = `
        <div class="generation-header${hasMeta ? ' clickable' : ''}">
            <span>Generated ${label}${meta && meta.video_title ? ` <span class="gen-header-title">— ${escapeHtml(meta.video_title)}</span>` : ''}</span>
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
                    <button class="thumb-edit-btn" data-path="${path}" title="Edit this thumbnail">Edit</button>
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
            // Swipe file selections (universal pool)
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
            // Client swipe selections — wait for the client tab to reload
            // (it auto-loads via the client change above), then re-apply.
            if (meta.client_swipe_files !== undefined) {
                const savedClientSwipes = new Set(meta.client_swipe_files.split(',').filter(s => s));
                window._clientSwipeSelections = new Set(savedClientSwipes);
                // The client grid renders async after the client change fires.
                // Defer to the next tick + small delay so the grid items exist.
                setTimeout(() => {
                    document.querySelectorAll('#swipeClientGrid .swipe-pick-item').forEach(item => {
                        if (savedClientSwipes.has(item.dataset.name)) {
                            item.classList.add('selected');
                        }
                    });
                    _updateSwipeSelectedCount();
                }, 200);
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

    // Edit buttons — open modal pre-loaded with this thumbnail
    group.querySelectorAll('.thumb-edit-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openEditModal(btn.dataset.path, meta || {});
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

// Filter the rendered history groups by client.
// Empty string = show all clients. Any other value = show only groups
// whose meta.client matches.
function applyHistoryClientFilter(clientSlug) {
    const grid = document.getElementById('previewGrid');
    const placeholder = document.getElementById('previewPlaceholder');
    if (!grid) return;
    const groups = grid.querySelectorAll('.generation-group');
    let visibleCount = 0;
    groups.forEach(g => {
        const gc = g.dataset.client || '';
        const match = !clientSlug || gc === clientSlug;
        g.classList.toggle('hidden', !match);
        if (match) visibleCount++;
    });
    // If nothing visible, hide the grid wrapper and show placeholder.
    // If at least one match, make sure the grid is visible.
    if (groups.length > 0) {
        if (visibleCount === 0) {
            grid.classList.add('hidden');
            if (placeholder) placeholder.classList.remove('hidden');
        } else {
            grid.classList.remove('hidden');
            if (placeholder) placeholder.classList.add('hidden');
        }
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

        // Apply the client filter now that history is populated. If a client
        // is pre-selected (e.g. last selection sticky), only their history shows.
        const clientSelectEl = document.getElementById('clientSelect');
        applyHistoryClientFilter(clientSelectEl ? clientSelectEl.value : '');
    } catch (err) {
        // Silent fail — history is non-critical
    }
}

function initThumbnails() {
    window._thumbPaths = [];
    const btnYoutube = document.getElementById('btnYoutube');
    const btnUpload = document.getElementById('btnUpload');
    const btnSwipeSource = document.getElementById('btnSwipeSource');
    const youtubeInput = document.getElementById('youtubeInput');
    const uploadInput = document.getElementById('uploadInput');
    const swipeSourceInput = document.getElementById('swipeSourceInput');
    window._swipeSourceSelected = null; // {url, name, pool: 'client'|'universal'}

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
    // ─── Image Model Provider Toggle ────────────────────────────────
    window._thumbProvider = 'gemini';
    const providerButtons = [
        document.getElementById('btnProviderGemini'),
        document.getElementById('btnProviderOpenAI'),
    ];
    const providerDesc = document.getElementById('providerDescription');
    const providerDescriptions = {
        gemini: 'Gemini 3 Pro Image — current default. Switch to GPT Image 1.5 for A/B testing replicate & imagine modes.',
        openai: 'GPT Image 1.5 — OpenAI alternative. Uses input_fidelity=high in replicate mode for strong composition preservation. Only affects replicate + imagine modes.',
    };
    const openaiQualitySection = document.getElementById('openaiQualitySection');
    const openaiQualitySlider = document.getElementById('openaiQuality');
    const openaiQualityLabel = document.getElementById('openaiQualityLabel');
    const openaiQualityCost = document.getElementById('openaiQualityCost');
    const qualityMap = ['low', 'medium', 'high'];
    const qualityLabels = { low: 'LOW', medium: 'MED', high: 'HIGH' };
    const qualityCosts = {
        low: '~$0.05-0.08/image — draft quality, fastest',
        medium: '~$0.15-0.20/image — balanced quality and cost',
        high: '~$0.35-0.40/image — best output quality',
    };
    window._openaiQuality = 'high';

    if (openaiQualitySlider) {
        openaiQualitySlider.addEventListener('input', () => {
            const q = qualityMap[openaiQualitySlider.value];
            window._openaiQuality = q;
            if (openaiQualityLabel) openaiQualityLabel.textContent = qualityLabels[q];
            if (openaiQualityCost) openaiQualityCost.textContent = qualityCosts[q];
        });
    }

    providerButtons.forEach(btn => {
        if (!btn) return;
        btn.addEventListener('click', () => {
            providerButtons.forEach(b => b && b.classList.remove('active'));
            btn.classList.add('active');
            window._thumbProvider = btn.dataset.provider;
            if (providerDesc) providerDesc.textContent = providerDescriptions[window._thumbProvider];
            if (openaiQualitySection) {
                openaiQualitySection.classList.toggle('hidden', window._thumbProvider !== 'openai');
            }
        });
    });

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
    function setSourceMode(mode) {
        btnYoutube.classList.toggle('active', mode === 'youtube');
        btnUpload.classList.toggle('active', mode === 'upload');
        if (btnSwipeSource) btnSwipeSource.classList.toggle('active', mode === 'swipe');
        youtubeInput.classList.toggle('hidden', mode !== 'youtube');
        uploadInput.classList.toggle('hidden', mode !== 'upload');
        if (swipeSourceInput) swipeSourceInput.classList.toggle('hidden', mode !== 'swipe');
        if (mode === 'swipe') loadSwipeSourceGrid();
    }
    btnYoutube.addEventListener('click', () => setSourceMode('youtube'));

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

    btnUpload.addEventListener('click', () => setSourceMode('upload'));
    if (btnSwipeSource) btnSwipeSource.addEventListener('click', () => setSourceMode('swipe'));

    // Upload zone A
    const thumbUploadZone = document.getElementById('thumbUploadZone');
    const thumbFile = document.getElementById('thumbFile');
    if (thumbUploadZone) {
        const showUploadedPreview = () => {
            if (!thumbFile.files.length) return;
            const file = thumbFile.files[0];
            const url = URL.createObjectURL(file);
            // Replace drop-zone contents with an image preview + filename
            thumbUploadZone.innerHTML = `
                <img src="${url}" alt="${escapeHtml(file.name)}"
                     style="max-width: 100%; max-height: 180px; border-radius: 8px; display: block; margin: 0 auto;">
                <p style="margin-top: 8px; font-size: 12px; color: var(--text-muted); text-align: center;">
                    ${escapeHtml(file.name)} — <span class="coral-text" style="cursor: pointer;">change</span>
                </p>
            `;
            // Re-attach the hidden input and click handler after innerHTML wipe
            thumbUploadZone.appendChild(thumbFile);
            thumbUploadZone.querySelector('.coral-text').addEventListener('click', (e) => {
                e.stopPropagation();
                thumbFile.click();
            });
        };
        thumbUploadZone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'INPUT') thumbFile.click();
        });
        thumbUploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            thumbUploadZone.classList.add('drag-over');
        });
        thumbUploadZone.addEventListener('dragleave', () => {
            thumbUploadZone.classList.remove('drag-over');
        });
        thumbUploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            thumbUploadZone.classList.remove('drag-over');
            if (e.dataTransfer.files.length) {
                thumbFile.files = e.dataTransfer.files;
                showUploadedPreview();
            }
        });
        thumbFile.addEventListener('change', showUploadedPreview);
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
    // AND filter history to show only the selected client (or all if cleared).
    if (clientSelect && generateBtn) {
        clientSelect.addEventListener('change', () => {
            generateBtn.disabled = !clientSelect.value;
            applyHistoryClientFilter(clientSelect.value);
        });
    }

    // ─── Cmd/Ctrl+Enter to generate ─────────────────────────────────
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            if (generateBtn && !generateBtn.disabled) {
                e.preventDefault();
                generateBtn.click();
            }
        }
    });

    // ─── Swipe File Picker ──────────────────────────────────────────
    loadSwipePicker();
    initYouTubeImport();

    // ─── Load Previous Thumbnails ────────────────────────────────────
    loadThumbnailHistory();
}

// Two pools, one selection model:
//   window._swipeSelections        — Set<filename> from execution/swipe_examples/individual/
//   window._clientSwipeSelections  — Set<filename> from .tmp/clients/<slug>/swipe_examples/
// Both are sent to the backend in _buildFormData and unified into a single
// list of swipe examples by recreate_thumbnails.py.
function _updateSwipeSelectedCount() {
    const el = document.getElementById('swipeSelectedCount');
    if (!el) return;
    const u = window._swipeSelections ? window._swipeSelections.size : 0;
    const c = window._clientSwipeSelections ? window._clientSwipeSelections.size : 0;
    const total = u + c;
    if (total === 0) {
        el.textContent = '';
    } else if (c === 0) {
        el.textContent = `${u} selected`;
    } else if (u === 0) {
        el.textContent = `${c} selected`;
    } else {
        el.textContent = `${u} + ${c} selected`;
    }
}

async function loadSwipePicker() {
    const universalGrid = document.getElementById('swipePickerGrid');
    const clientGrid = document.getElementById('swipeClientGrid');
    const clientPanel = document.getElementById('swipeClientPanel');
    const tabs = document.querySelectorAll('.swipe-tab');
    const tabClient = document.getElementById('swipeTabClient');
    const selectAll = document.getElementById('swipeSelectAll');
    const selectNone = document.getElementById('swipeSelectNone');
    const clientUploadZone = document.getElementById('swipeClientUploadZone');
    const clientFileInput = document.getElementById('swipeClientFileInput');
    if (!universalGrid) return;

    window._swipeSelections = new Set();
    window._clientSwipeSelections = new Set();

    // ─── Universal pool ───
    try {
        const res = await fetch('/api/swipe-examples');
        const examples = await res.json();
        if (!examples.length) {
            universalGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">No swipe examples found</p>';
        } else {
            universalGrid.innerHTML = examples.map(ex =>
                `<div class="swipe-pick-item" data-name="${ex.name}">
                    <img src="${ex.url}" alt="${ex.name}" loading="lazy">
                    <div class="swipe-pick-check">\u2713</div>
                </div>`
            ).join('');
            universalGrid.querySelectorAll('.swipe-pick-item').forEach(item => {
                item.addEventListener('click', () => {
                    const name = item.dataset.name;
                    if (item.classList.contains('selected')) {
                        item.classList.remove('selected');
                        window._swipeSelections.delete(name);
                    } else {
                        item.classList.add('selected');
                        window._swipeSelections.add(name);
                    }
                    _updateSwipeSelectedCount();
                });
            });
        }
    } catch (err) {
        universalGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">Failed to load swipe examples</p>';
    }

    // ─── Tab switching ───
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.disabled) return;
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const which = tab.dataset.swipeTab;
            if (which === 'universal') {
                universalGrid.classList.remove('hidden');
                clientPanel.classList.add('hidden');
            } else {
                universalGrid.classList.add('hidden');
                clientPanel.classList.remove('hidden');
            }
        });
    });

    // ─── Select All / None — operates on the currently visible tab ───
    const getActivePool = () => {
        const active = document.querySelector('.swipe-tab.active');
        if (active && active.dataset.swipeTab === 'client') {
            return { grid: clientGrid, set: window._clientSwipeSelections };
        }
        return { grid: universalGrid, set: window._swipeSelections };
    };
    selectAll.addEventListener('click', () => {
        const { grid, set } = getActivePool();
        grid.querySelectorAll('.swipe-pick-item').forEach(item => {
            item.classList.add('selected');
            set.add(item.dataset.name);
        });
        _updateSwipeSelectedCount();
    });
    selectNone.addEventListener('click', () => {
        const { grid, set } = getActivePool();
        grid.querySelectorAll('.swipe-pick-item').forEach(item => {
            item.classList.remove('selected');
            set.delete(item.dataset.name);
        });
        _updateSwipeSelectedCount();
    });

    // ─── Client pool — load when client changes ───
    const clientSelect = document.getElementById('clientSelect');
    if (clientSelect) {
        clientSelect.addEventListener('change', () => {
            loadClientSwipes(clientSelect.value);
        });
        // If a client is already selected on first init, load right away
        if (clientSelect.value) loadClientSwipes(clientSelect.value);
    }

    // ─── Client upload zone (drop / click to pick) ───
    if (clientUploadZone) {
        clientUploadZone.addEventListener('click', () => clientFileInput.click());
        clientUploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            clientUploadZone.classList.add('drag-over');
        });
        clientUploadZone.addEventListener('dragleave', () => {
            clientUploadZone.classList.remove('drag-over');
        });
        clientUploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            clientUploadZone.classList.remove('drag-over');
            if (e.dataTransfer.files.length) uploadClientSwipes(e.dataTransfer.files);
        });
        clientFileInput.addEventListener('change', () => {
            if (clientFileInput.files.length) uploadClientSwipes(clientFileInput.files);
            clientFileInput.value = '';
        });
    }

    _updateSwipeSelectedCount();
}

async function loadClientSwipes(slug) {
    const clientGrid = document.getElementById('swipeClientGrid');
    const tabClient = document.getElementById('swipeTabClient');
    if (!clientGrid) return;

    // Selections are PER-CLIENT — clear when switching to a different client.
    if (window._currentSwipeClient !== slug) {
        window._clientSwipeSelections = new Set();
        window._currentSwipeClient = slug;
        _updateSwipeSelectedCount();
    }

    if (!slug) {
        clientGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">Select a client to manage their swipes.</p>';
        if (tabClient) {
            tabClient.disabled = true;
            tabClient.textContent = 'Client';
        }
        return;
    }

    if (tabClient) tabClient.disabled = false;

    try {
        const res = await fetch(`/api/clients/${slug}/swipes`);
        const swipes = await res.json();
        if (tabClient) {
            tabClient.textContent = `${slug} (${swipes.length})`;
        }
        if (!swipes.length) {
            clientGrid.innerHTML = `<p style="color: var(--text-muted); font-size: 13px;">No swipes for ${escapeHtml(slug)} yet — drop some thumbnails above to add.</p>`;
            return;
        }
        clientGrid.innerHTML = swipes.map(s =>
            `<div class="swipe-pick-item" data-name="${escapeHtml(s.name)}">
                <img src="${s.url}" alt="${escapeHtml(s.name)}" loading="lazy">
                <div class="swipe-pick-check">\u2713</div>
                <button class="ref-delete-btn" data-name="${escapeHtml(s.name)}" title="Remove">&times;</button>
            </div>`
        ).join('');
        clientGrid.querySelectorAll('.swipe-pick-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.classList.contains('ref-delete-btn')) return;
                const name = item.dataset.name;
                if (item.classList.contains('selected')) {
                    item.classList.remove('selected');
                    window._clientSwipeSelections.delete(name);
                } else {
                    item.classList.add('selected');
                    window._clientSwipeSelections.add(name);
                }
                _updateSwipeSelectedCount();
            });
        });
        clientGrid.querySelectorAll('.ref-delete-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const name = btn.dataset.name;
                if (!confirm(`Remove "${name}" from ${slug}'s swipes?`)) return;
                await fetch(`/api/clients/${slug}/swipes/${encodeURIComponent(name)}`, { method: 'DELETE' });
                window._clientSwipeSelections.delete(name);
                loadClientSwipes(slug);
            });
        });
    } catch (err) {
        clientGrid.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">Failed to load client swipes</p>';
    }
}

async function uploadClientSwipes(files) {
    const clientSelect = document.getElementById('clientSelect');
    const slug = clientSelect ? clientSelect.value : '';
    if (!slug) {
        showToast('Select a client first', 'error');
        return;
    }
    const formData = new FormData();
    for (const f of files) {
        if (f && f.type.startsWith('image/')) formData.append('swipes', f);
    }
    try {
        await fetch(`/api/clients/${slug}/swipes`, { method: 'POST', body: formData });
        loadClientSwipes(slug);
    } catch (err) {
        showToast('Upload failed: ' + err.message, 'error');
    }
}

// ─── Swipe File as Source ────────────────────────────────────────────────────

async function loadSwipeSourceGrid() {
    const grid = document.getElementById('swipeSourceGrid');
    if (!grid) return;

    const slug = (document.getElementById('clientSelect') || {}).value;
    let items = [];

    // Fetch client swipes first (if a client is selected), then universal
    try {
        if (slug) {
            const res = await fetch(`/api/clients/${slug}/swipes`);
            const clientSwipes = await res.json();
            items = clientSwipes.map(s => ({...s, pool: 'client', slug}));
        }
        const res2 = await fetch('/api/swipe-examples');
        const universalSwipes = await res2.json();
        items = items.concat(universalSwipes.map(s => ({...s, pool: 'universal'})));
    } catch (err) {
        grid.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">Failed to load swipe files</p>';
        return;
    }

    if (!items.length) {
        grid.innerHTML = '<p style="color: var(--text-muted); font-size: 12px;">No swipe files available</p>';
        return;
    }

    grid.innerHTML = items.map(s =>
        `<div class="swipe-source-item${window._swipeSourceSelected && window._swipeSourceSelected.name === s.name && window._swipeSourceSelected.pool === s.pool ? ' selected' : ''}" data-name="${escapeHtml(s.name)}" data-url="${escapeHtml(s.url)}" data-pool="${s.pool}"${s.slug ? ` data-slug="${escapeHtml(s.slug)}"` : ''}>
            <img src="${s.url}" alt="${escapeHtml(s.name)}" loading="lazy">
            <div class="swipe-pick-check">\u2713</div>
            ${s.pool === 'client' ? '<span class="swipe-source-badge">client</span>' : ''}
        </div>`
    ).join('');

    grid.querySelectorAll('.swipe-source-item').forEach(item => {
        item.addEventListener('click', () => {
            // Deselect previous
            grid.querySelectorAll('.swipe-source-item.selected').forEach(el => el.classList.remove('selected'));
            item.classList.add('selected');
            window._swipeSourceSelected = {
                name: item.dataset.name,
                url: item.dataset.url,
                pool: item.dataset.pool,
                slug: item.dataset.slug || '',
            };
        });
    });
}

// ─── YouTube Channel Import ──────────────────────────────────────────────────

function initYouTubeImport() {
    const overlay = document.getElementById('ytImportOverlay');
    const btn = document.getElementById('btnImportYouTube');
    const closeBtn = document.getElementById('ytImportClose');
    const fetchBtn = document.getElementById('ytFetchBtn');
    const urlInput = document.getElementById('ytChannelUrl');
    const grid = document.getElementById('ytImportGrid');
    const status = document.getElementById('ytImportStatus');
    const actions = document.getElementById('ytImportActions');
    const saveBtn = document.getElementById('ytSaveSelected');
    const selectAllBtn = document.getElementById('ytSelectAll');
    const selectNoneBtn = document.getElementById('ytSelectNone');
    const countEl = document.getElementById('ytSelectedCount');
    if (!overlay || !btn) return;

    let ytThumbnails = [];   // fetched items
    let ytSelected = new Set();

    function open()  { overlay.classList.remove('hidden'); }
    function close() { overlay.classList.add('hidden'); }

    btn.addEventListener('click', () => {
        const slug = (document.getElementById('clientSelect') || {}).value;
        if (!slug) { showToast('Select a client first', 'error'); return; }
        open();
    });
    closeBtn.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    function updateCount() {
        countEl.textContent = ytSelected.size ? `${ytSelected.size} selected` : '';
    }

    function renderGrid() {
        if (!ytThumbnails.length) {
            grid.innerHTML = '';
            actions.classList.add('hidden');
            return;
        }
        actions.classList.remove('hidden');
        grid.innerHTML = ytThumbnails.map(t =>
            `<div class="yt-thumb-item${ytSelected.has(t.id) ? ' selected' : ''}" data-id="${escapeHtml(t.id)}">
                <img src="${escapeHtml(t.thumbnail)}" alt="${escapeHtml(t.title)}" loading="lazy"
                     onerror="this.src='https://i.ytimg.com/vi/${escapeHtml(t.id)}/hqdefault.jpg'">
                <div class="yt-thumb-check">\u2713</div>
                <div class="yt-thumb-title">${escapeHtml(t.title)}</div>
            </div>`
        ).join('');
        grid.querySelectorAll('.yt-thumb-item').forEach(item => {
            item.addEventListener('click', () => {
                const id = item.dataset.id;
                if (ytSelected.has(id)) {
                    ytSelected.delete(id);
                    item.classList.remove('selected');
                } else {
                    ytSelected.add(id);
                    item.classList.add('selected');
                }
                updateCount();
            });
        });
        updateCount();
    }

    selectAllBtn.addEventListener('click', () => {
        ytThumbnails.forEach(t => ytSelected.add(t.id));
        renderGrid();
    });
    selectNoneBtn.addEventListener('click', () => {
        ytSelected.clear();
        renderGrid();
    });

    fetchBtn.addEventListener('click', async () => {
        const slug = (document.getElementById('clientSelect') || {}).value;
        const url = urlInput.value.trim();
        if (!url) { showToast('Paste a YouTube channel URL', 'error'); return; }

        fetchBtn.disabled = true;
        fetchBtn.textContent = 'Fetching...';
        status.textContent = 'Scanning channel — this may take a moment...';
        grid.innerHTML = '';
        actions.classList.add('hidden');
        ytThumbnails = [];
        ytSelected.clear();

        try {
            const res = await fetch(`/api/clients/${slug}/import-youtube`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({channel_url: url}),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to fetch');
            ytThumbnails = data.thumbnails || [];
            status.textContent = ytThumbnails.length
                ? `Found ${ytThumbnails.length} videos from ${data.channel || 'channel'} — click to select thumbnails to import`
                : 'No videos found on this channel.';
            renderGrid();
        } catch (err) {
            status.textContent = '';
            showToast('YouTube fetch failed: ' + err.message, 'error');
        } finally {
            fetchBtn.disabled = false;
            fetchBtn.textContent = 'Fetch';
        }
    });

    // Also allow Enter key in the URL input
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); fetchBtn.click(); }
    });

    saveBtn.addEventListener('click', async () => {
        const slug = (document.getElementById('clientSelect') || {}).value;
        if (!ytSelected.size) { showToast('Select at least one thumbnail', 'error'); return; }

        const items = ytThumbnails.filter(t => ytSelected.has(t.id));
        saveBtn.disabled = true;
        saveBtn.textContent = `Importing ${items.length}...`;

        try {
            const res = await fetch(`/api/clients/${slug}/import-youtube/save`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({items}),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Save failed');
            showToast(`Imported ${data.count} thumbnails`, 'success');
            close();
            // Refresh client swipe grid
            loadClientSwipes(slug);
        } catch (err) {
            showToast('Import failed: ' + err.message, 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Import Selected';
        }
    });
}

function _buildFormData() {
    const formData = new FormData();
    const mode = window._thumbMode || 'replicate';
    formData.append('mode', mode);
    formData.append('provider', window._thumbProvider || 'gemini');
    if (window._thumbProvider === 'openai') {
        formData.append('openai_quality', window._openaiQuality || 'high');
    }

    if (mode !== 'imagine') {
        const btnYoutube = document.getElementById('btnYoutube');
        const btnSwipeSrc = document.getElementById('btnSwipeSource');
        if (btnSwipeSrc && btnSwipeSrc.classList.contains('active') && window._swipeSourceSelected) {
            // Swipe file as source — send pool + filename so backend can resolve the path
            formData.append('swipe_source_pool', window._swipeSourceSelected.pool);
            formData.append('swipe_source_name', window._swipeSourceSelected.name);
            formData.append('swipe_source_slug', window._swipeSourceSelected.slug || '');
        } else if (btnYoutube.classList.contains('active')) {
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
    if (window._clientSwipeSelections && window._clientSwipeSelections.size > 0) {
        formData.append('client_swipe_files', Array.from(window._clientSwipeSelections).join(','));
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

// ─── Job Tray (multi-job, non-blocking progress) ────────────────────────
window._activeJobs = window._activeJobs || new Map();

function _ensureJobTray() {
    let tray = document.getElementById('jobTray');
    if (!tray) {
        tray = document.createElement('div');
        tray.id = 'jobTray';
        tray.className = 'job-tray hidden';
        document.body.appendChild(tray);
    }
    return tray;
}

function _addJobRow(rowId, label) {
    const tray = _ensureJobTray();
    tray.classList.remove('hidden');
    const row = document.createElement('div');
    row.className = 'job-row job-state-pending';
    row.dataset.rowId = rowId;
    row.innerHTML = `
        <div class="job-row-head">
            <span class="job-row-label">${escapeHtml(label)}</span>
            <button class="job-row-action" type="button" title="Cancel">Cancel</button>
        </div>
        <div class="job-row-bar"><div class="job-row-bar-fill" style="width:5%"></div></div>
        <div class="job-row-status">Submitting&hellip;</div>
    `;
    row.querySelector('.job-row-action').addEventListener('click', async () => {
        const job = window._activeJobs.get(rowId);
        const state = (row.className.match(/job-state-(\w+)/) || [])[1];

        // If job is finished/errored/cancelled, the action is just dismiss.
        if (state === 'done' || state === 'error' || state === 'cancelled') {
            _removeJobRow(rowId);
            return;
        }

        // Otherwise it's an active or queued job — request server-side cancel.
        if (job && job.taskId) {
            try {
                await fetch(`/api/thumbnails/${job.taskId}/cancel`, { method: 'POST' });
                // The poller will see state='cancelled' and update the row.
                _updateJobRow(rowId, { status: 'Cancelling...' });
            } catch (err) {
                // Network failure — drop it from the tray anyway
                _removeJobRow(rowId);
            }
        } else {
            // No taskId yet (still in the submit window). Just remove the row;
            // the in-flight POST will land on a row that no longer exists, which
            // is fine — its updates become no-ops.
            _removeJobRow(rowId);
        }
    });
    tray.appendChild(row);
    return row;
}

function _updateJobRow(rowId, { progress, status, state } = {}) {
    const row = document.querySelector(`.job-row[data-row-id="${rowId}"]`);
    if (!row) return;
    if (typeof progress === 'number') {
        row.querySelector('.job-row-bar-fill').style.width = `${progress}%`;
    }
    if (status) {
        row.querySelector('.job-row-status').textContent = status;
    }
    if (state) {
        row.classList.remove(
            'job-state-pending', 'job-state-running', 'job-state-queued',
            'job-state-done', 'job-state-error', 'job-state-cancelled'
        );
        row.classList.add(`job-state-${state}`);
        // Swap action button label/title once the job reaches a terminal state.
        const action = row.querySelector('.job-row-action');
        if (action) {
            if (state === 'done' || state === 'error' || state === 'cancelled') {
                action.textContent = '×';
                action.title = 'Dismiss';
                action.classList.add('job-row-action-dismiss');
            } else {
                action.textContent = 'Cancel';
                action.title = 'Cancel';
                action.classList.remove('job-row-action-dismiss');
            }
        }
    }
}

function _removeJobRow(rowId) {
    const row = document.querySelector(`.job-row[data-row-id="${rowId}"]`);
    if (row) row.remove();
    window._activeJobs.delete(rowId);
    const tray = document.getElementById('jobTray');
    if (tray && tray.children.length === 0) tray.classList.add('hidden');
}

function _jobLabel(meta) {
    const mode = meta.mode || 'replicate';
    const client = meta.client ? ` · ${meta.client}` : '';
    const prov = meta.provider && meta.provider !== 'gemini' ? ` · ${meta.provider.toUpperCase()}` : '';
    return `${mode}${client}${prov}`;
}

// ─── Edit Modal (Layer 1: text-based targeted edits) ────────────────────
function openEditModal(thumbPath, parentMeta) {
    const overlay = document.getElementById('editThumbnailOverlay');
    const img = document.getElementById('editThumbnailImg');
    const promptEl = document.getElementById('editThumbnailPrompt');
    const submitBtn = document.getElementById('submitEditBtn');
    const cancelBtn = document.getElementById('cancelEditBtn');
    const varsEl = document.getElementById('editVariations');
    const varsValEl = document.getElementById('editVariationsValue');

    // Reference logos UI
    const logoUrlEl = document.getElementById('editLogoUrl');
    const logoAddBtn = document.getElementById('editLogoAddUrlBtn');
    const logoError = document.getElementById('editLogoUrlError');
    const logoPreview = document.getElementById('editLogoUrlPreview');
    const logoPreviewImg = document.getElementById('editLogoUrlPreviewImg');
    const logoConfirmBtn = document.getElementById('editLogoUrlConfirmBtn');
    const logoRejectBtn = document.getElementById('editLogoUrlRejectBtn');
    const logoDropZone = document.getElementById('editLogoDropZone');
    const logoFileInput = document.getElementById('editLogoFileInput');
    const logoChips = document.getElementById('editLogoChips');

    // Style reference UI
    const styleRefDropZone = document.getElementById('editStyleRefDropZone');
    const styleRefFileInput = document.getElementById('editStyleRefFileInput');
    const styleRefPreview = document.getElementById('editStyleRefPreview');
    const styleRefPreviewImg = document.getElementById('editStyleRefPreviewImg');
    const styleRefRemoveBtn = document.getElementById('editStyleRefRemoveBtn');

    if (!overlay || !img || !promptEl) return;

    img.src = `/api/download/${thumbPath}`;
    promptEl.value = '';
    if (varsEl) {
        varsEl.value = '1';
        if (varsValEl) varsValEl.textContent = '01';
    }

    // Fresh state for each modal open
    const state = {
        urls: [],            // logo URLs: [{ url, dataUrl }]
        files: [],           // logo files: [File]
        pendingPreview: null, // { url, dataUrl } from /api/fetch-image
        styleRef: null,      // { file: File, objectUrl: string } | null
    };
    logoError.classList.add('hidden');
    logoError.textContent = '';
    logoPreview.classList.add('hidden');
    logoUrlEl.value = '';
    logoChips.innerHTML = '';
    if (styleRefPreview) styleRefPreview.classList.add('hidden');
    if (styleRefPreviewImg) styleRefPreviewImg.removeAttribute('src');
    if (styleRefDropZone) styleRefDropZone.classList.remove('hidden');

    const renderChips = () => {
        logoChips.innerHTML = '';
        // URL chips first, then file chips
        state.urls.forEach((item, i) => {
            const chip = document.createElement('div');
            chip.className = 'edit-logo-chip';
            chip.innerHTML = `<img src="${item.dataUrl}"><button type="button" class="edit-logo-chip-remove" title="Remove">&times;</button>`;
            chip.querySelector('.edit-logo-chip-remove').addEventListener('click', () => {
                state.urls.splice(i, 1);
                renderChips();
            });
            logoChips.appendChild(chip);
        });
        state.files.forEach((f, i) => {
            if (!f) return;
            const chip = document.createElement('div');
            chip.className = 'edit-logo-chip';
            const url = URL.createObjectURL(f);
            chip.innerHTML = `<img src="${url}"><button type="button" class="edit-logo-chip-remove" title="Remove">&times;</button>`;
            chip.querySelector('.edit-logo-chip-remove').addEventListener('click', () => {
                state.files[i] = null;
                URL.revokeObjectURL(url);
                renderChips();
            });
            logoChips.appendChild(chip);
        });
    };

    // ─── URL preview flow ───
    const clearPreview = () => {
        logoPreview.classList.add('hidden');
        logoPreviewImg.removeAttribute('src');
        state.pendingPreview = null;
    };
    const showError = (msg) => {
        logoError.textContent = msg;
        logoError.classList.remove('hidden');
    };
    const hideError = () => {
        logoError.classList.add('hidden');
        logoError.textContent = '';
    };

    const onAddUrl = async () => {
        const url = logoUrlEl.value.trim();
        if (!url) return;
        hideError();
        clearPreview();
        logoAddBtn.disabled = true;
        const origLabel = logoAddBtn.textContent;
        logoAddBtn.textContent = 'Fetching…';
        try {
            const res = await fetch('/api/fetch-image', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            });
            const data = await res.json();
            if (!res.ok || data.error) {
                showError(data.error || 'Failed to fetch image');
                return;
            }
            state.pendingPreview = { url, dataUrl: data.data_url };
            logoPreviewImg.src = data.data_url;
            logoPreview.classList.remove('hidden');
        } catch (err) {
            showError(err.message || 'Network error');
        } finally {
            logoAddBtn.disabled = false;
            logoAddBtn.textContent = origLabel;
        }
    };
    const onConfirmUrl = () => {
        if (!state.pendingPreview) return;
        state.urls.push(state.pendingPreview);
        clearPreview();
        logoUrlEl.value = '';
        logoUrlEl.focus();
        renderChips();
    };
    const onRejectUrl = () => {
        clearPreview();
        logoUrlEl.focus();
    };
    const onUrlKey = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (state.pendingPreview) {
                onConfirmUrl();
            } else {
                onAddUrl();
            }
        }
    };

    // ─── File upload + drop flow ───
    const addFiles = (fileList) => {
        for (const f of fileList) {
            if (f && f.type.startsWith('image/')) state.files.push(f);
        }
        renderChips();
    };
    const onDropZoneClick = () => logoFileInput.click();
    const onFileInput = () => {
        if (logoFileInput.files.length) addFiles(logoFileInput.files);
        logoFileInput.value = '';
    };
    const onDragOver = (e) => { e.preventDefault(); logoDropZone.classList.add('drag-over'); };
    const onDragLeave = () => logoDropZone.classList.remove('drag-over');
    const onDrop = (e) => {
        e.preventDefault();
        logoDropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    };

    // ─── Style reference (single image, replaces on re-pick) ───
    const setStyleRef = (file) => {
        if (!file || !file.type.startsWith('image/')) return;
        // Revoke previous object URL if any
        if (state.styleRef && state.styleRef.objectUrl) {
            URL.revokeObjectURL(state.styleRef.objectUrl);
        }
        const objectUrl = URL.createObjectURL(file);
        state.styleRef = { file, objectUrl };
        styleRefPreviewImg.src = objectUrl;
        styleRefPreview.classList.remove('hidden');
        styleRefDropZone.classList.add('hidden');
    };
    const clearStyleRef = () => {
        if (state.styleRef && state.styleRef.objectUrl) {
            URL.revokeObjectURL(state.styleRef.objectUrl);
        }
        state.styleRef = null;
        styleRefPreviewImg.removeAttribute('src');
        styleRefPreview.classList.add('hidden');
        styleRefDropZone.classList.remove('hidden');
    };
    const onStyleRefDropZoneClick = () => styleRefFileInput.click();
    const onStyleRefFileInput = () => {
        if (styleRefFileInput.files.length) setStyleRef(styleRefFileInput.files[0]);
        styleRefFileInput.value = '';
    };
    const onStyleRefDragOver = (e) => { e.preventDefault(); styleRefDropZone.classList.add('drag-over'); };
    const onStyleRefDragLeave = () => styleRefDropZone.classList.remove('drag-over');
    const onStyleRefDrop = (e) => {
        e.preventDefault();
        styleRefDropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) setStyleRef(e.dataTransfer.files[0]);
    };
    const onStyleRefRemove = () => clearStyleRef();

    // ─── Variations ───
    const onVarsInput = () => {
        if (varsValEl) varsValEl.textContent = String(varsEl.value).padStart(2, '0');
    };

    // ─── Submit + cleanup ───
    const cleanup = () => {
        overlay.classList.add('hidden');
        submitBtn.removeEventListener('click', onSubmit);
        cancelBtn.removeEventListener('click', onCancel);
        document.removeEventListener('keydown', onKey);
        if (varsEl) varsEl.removeEventListener('input', onVarsInput);
        logoAddBtn.removeEventListener('click', onAddUrl);
        logoConfirmBtn.removeEventListener('click', onConfirmUrl);
        logoRejectBtn.removeEventListener('click', onRejectUrl);
        logoUrlEl.removeEventListener('keydown', onUrlKey);
        logoDropZone.removeEventListener('click', onDropZoneClick);
        logoDropZone.removeEventListener('dragover', onDragOver);
        logoDropZone.removeEventListener('dragleave', onDragLeave);
        logoDropZone.removeEventListener('drop', onDrop);
        logoFileInput.removeEventListener('change', onFileInput);
        styleRefDropZone.removeEventListener('click', onStyleRefDropZoneClick);
        styleRefDropZone.removeEventListener('dragover', onStyleRefDragOver);
        styleRefDropZone.removeEventListener('dragleave', onStyleRefDragLeave);
        styleRefDropZone.removeEventListener('drop', onStyleRefDrop);
        styleRefFileInput.removeEventListener('change', onStyleRefFileInput);
        styleRefRemoveBtn.removeEventListener('click', onStyleRefRemove);
    };
    const onCancel = () => cleanup();
    const onSubmit = async () => {
        const prompt = promptEl.value.trim();
        if (!prompt) {
            promptEl.focus();
            return;
        }
        const variations = varsEl ? parseInt(varsEl.value, 10) || 1 : 1;
        const logoUrls = state.urls.map(x => x.url);
        const logoFiles = state.files.filter(Boolean);
        const styleRefFile = state.styleRef ? state.styleRef.file : null;
        cleanup();
        await _submitEdit(thumbPath, prompt, parentMeta, variations, logoUrls, logoFiles, styleRefFile);
    };
    const onKey = (e) => {
        // Don't intercept Escape / Cmd+Enter while typing in the URL field
        // (Enter there is handled by onUrlKey).
        if (e.key === 'Escape') onCancel();
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') onSubmit();
    };

    // Wire everything up
    submitBtn.addEventListener('click', onSubmit);
    cancelBtn.addEventListener('click', onCancel);
    document.addEventListener('keydown', onKey);
    if (varsEl) varsEl.addEventListener('input', onVarsInput);
    logoAddBtn.addEventListener('click', onAddUrl);
    logoConfirmBtn.addEventListener('click', onConfirmUrl);
    logoRejectBtn.addEventListener('click', onRejectUrl);
    logoUrlEl.addEventListener('keydown', onUrlKey);
    logoDropZone.addEventListener('click', onDropZoneClick);
    logoDropZone.addEventListener('dragover', onDragOver);
    logoDropZone.addEventListener('dragleave', onDragLeave);
    logoDropZone.addEventListener('drop', onDrop);
    logoFileInput.addEventListener('change', onFileInput);
    styleRefDropZone.addEventListener('click', onStyleRefDropZoneClick);
    styleRefDropZone.addEventListener('dragover', onStyleRefDragOver);
    styleRefDropZone.addEventListener('dragleave', onStyleRefDragLeave);
    styleRefDropZone.addEventListener('drop', onStyleRefDrop);
    styleRefFileInput.addEventListener('change', onStyleRefFileInput);
    styleRefRemoveBtn.addEventListener('click', onStyleRefRemove);

    overlay.classList.remove('hidden');
    setTimeout(() => promptEl.focus(), 50);
}

async function _submitEdit(thumbPath, prompt, parentMeta, variations = 1, logoUrls = [], logoFiles = [], styleRefFile = null) {
    // Build a captured meta for the tray + history. Mark it as 'edit' so the
    // history label and regeneration logic don't try to re-run a normal flow.
    const capturedMeta = {
        mode: 'edit',
        prompt: prompt,
        video_title: parentMeta.video_title || '',
        client: parentMeta.client || '',
        variations: String(variations),
        edited_from: thumbPath,
    };
    const rowId = 'job-' + Math.random().toString(36).slice(2, 10);
    const refCount = logoUrls.length + logoFiles.length;
    const styleSuffix = styleRefFile ? ' +style' : '';
    const refSuffix = (refCount > 0 ? ` +${refCount} ref` : '') + styleSuffix;
    const label = variations > 1
        ? `edit ×${variations}${refSuffix} · ${parentMeta.client || 'thumbnail'}`
        : `edit${refSuffix} · ${parentMeta.client || 'thumbnail'}`;
    _addJobRow(rowId, label);

    try {
        const formData = new FormData();
        formData.append('source_path', thumbPath);
        formData.append('prompt', prompt);
        formData.append('variations', String(variations));
        // Pass parent meta so the backend can persist client/title in the new meta.
        formData.append('parent_meta', JSON.stringify({
            video_title: parentMeta.video_title || '',
            client: parentMeta.client || '',
        }));
        // Reference logos: URLs are passed as newline-delimited text (backend
        // re-downloads), files are uploaded directly.
        if (logoUrls.length > 0) {
            formData.append('logo_urls', logoUrls.join('\n'));
        }
        for (const f of logoFiles) {
            formData.append('logo_files', f);
        }
        // Style/layout reference (optional, single file)
        if (styleRefFile) {
            formData.append('style_reference', styleRefFile);
        }

        const response = await fetch('/api/thumbnails/edit', { method: 'POST', body: formData });
        const data = await response.json();
        if (!response.ok || data.error) {
            _updateJobRow(rowId, { state: 'error', status: data.error || 'Failed to start edit' });
            showToast(data.error || 'Failed to start edit', 'error');
            return;
        }
        window._activeJobs.set(rowId, { taskId: data.task_id, meta: capturedMeta });
        pollThumbnailProgress(data.task_id, rowId, capturedMeta);
    } catch (err) {
        _updateJobRow(rowId, { state: 'error', status: err.message });
        showToast(err.message, 'error');
    }
}

async function _submitGeneration(formData, capturedMeta) {
    // Use a stable client-side rowId so we can update the tray row before
    // (and after) the backend returns a task_id.
    const rowId = 'job-' + Math.random().toString(36).slice(2, 10);
    _addJobRow(rowId, _jobLabel(capturedMeta));

    try {
        const response = await fetch('/api/thumbnails', { method: 'POST', body: formData });
        const data = await response.json();
        if (!response.ok || data.error) {
            _updateJobRow(rowId, {
                state: 'error',
                status: data.error || 'Failed to start generation',
            });
            showToast(data.error || 'Failed to start generation', 'error');
            return;
        }
        window._activeJobs.set(rowId, { taskId: data.task_id, meta: capturedMeta });
        pollThumbnailProgress(data.task_id, rowId, capturedMeta);
    } catch (err) {
        _updateJobRow(rowId, { state: 'error', status: err.message });
        showToast(err.message, 'error');
    }
}

async function generateThumbnails() {
    const formData = _buildFormData();
    const prompt = document.getElementById('thumbPrompt').value.trim();

    // Capture form state RIGHT NOW so it's preserved across the async enhance step
    // and the eventual completion — even if the user changes the form to start
    // another generation in the meantime.
    const capturedMeta = {
        mode: window._thumbMode || 'replicate',
        provider: window._thumbProvider || 'gemini',
        youtube_url: document.getElementById('youtubeUrl')?.value || '',
        prompt: prompt,
        video_title: document.getElementById('videoTitle')?.value || '',
        client: document.getElementById('clientSelect')?.value || '',
        variations: document.getElementById('variations')?.value || '',
        refs: document.getElementById('refs')?.value || '',
        swipe_files: window._swipeSelections ? Array.from(window._swipeSelections).join(',') : '',
        client_swipe_files: window._clientSwipeSelections ? Array.from(window._clientSwipeSelections).join(',') : '',
    };

    // If there's a prompt AND enhance toggle is on, offer to enhance it first
    const enhanceOn = document.getElementById('enhancePromptToggle')?.checked;
    if (prompt && enhanceOn) {
        const previewOverlay = document.getElementById('promptPreviewOverlay');
        const enhancedText = document.getElementById('enhancedPromptText');
        const generateBtn = document.getElementById('generateBtn');
        const origText = generateBtn ? generateBtn.textContent : '';

        // Brief inline feedback on the Generate button instead of a blocking overlay
        if (generateBtn) {
            generateBtn.textContent = 'Enhancing prompt…';
            generateBtn.disabled = true;
        }

        try {
            const enhanceData = new FormData();
            enhanceData.append('prompt', prompt);
            enhanceData.append('youtube_url', capturedMeta.youtube_url);
            enhanceData.append('video_title', capturedMeta.video_title);

            const res = await fetch('/api/enhance-prompt', { method: 'POST', body: enhanceData });
            const data = await res.json();

            if (generateBtn) {
                generateBtn.textContent = origText;
                generateBtn.disabled = !document.getElementById('clientSelect').value;
            }

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
                        capturedMeta.prompt = enhancedText.value;
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
            if (generateBtn) {
                generateBtn.textContent = origText;
                generateBtn.disabled = !document.getElementById('clientSelect').value;
            }
            // Enhancement failed, proceed with original
        }
    }

    // If enhance is off, tell backend to skip too
    if (!enhanceOn) {
        formData.set('skip_enhance', 'true');
    }

    _submitGeneration(formData, capturedMeta);
}

async function pollThumbnailProgress(taskId, rowId, capturedMeta) {
    const placeholder = document.getElementById('previewPlaceholder');
    const grid = document.getElementById('previewGrid');

    const poll = async () => {
        try {
            const res = await fetch(`/api/progress/${taskId}`);
            const data = await res.json();

            _updateJobRow(rowId, {
                progress: data.progress,
                status: data.status,
                state: data.state,
            });

            if (data.state === 'done') {
                if (data.thumbnails && data.thumbnails.length) {
                    const now = new Date();
                    const timeStr = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
                    // Use the meta captured at submit time, NOT live form state —
                    // the form may have been changed for a subsequent generation.
                    const group = addGenerationGroup(data.thumbnails, timeStr, capturedMeta);
                    if (group) {
                        grid.prepend(group);

                        // Re-apply the client filter so a newly finished job
                        // for a different client doesn't bypass the filter.
                        const csel = document.getElementById('clientSelect');
                        applyHistoryClientFilter(csel ? csel.value : '');

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
                // Auto-dismiss the tray row after a brief moment so the user
                // can see the completion state.
                setTimeout(() => _removeJobRow(rowId), 3500);
                return;
            }

            if (data.state === 'error') {
                _updateJobRow(rowId, { state: 'error', status: data.error || 'Generation failed' });
                showToast(data.error || 'Generation failed', 'error');
                // Leave error rows in tray until the user dismisses them.
                return;
            }

            if (data.state === 'cancelled') {
                _updateJobRow(rowId, { state: 'cancelled', status: data.status || 'Cancelled' });
                // Auto-dismiss cancelled rows quickly — the user already
                // intended to get rid of them.
                setTimeout(() => _removeJobRow(rowId), 1500);
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
