import { request } from './api.js';
import { createTaskWatcher, terminalStatuses } from './progress.js';
import { createDownloadQueue } from './downloads.js';

const $ = id => document.getElementById(id);
const state = {
    info: null, format: 'mp4', quality: 'best', files: [], filter: 'all',
    submitting: false, compatible: true, analysis: null, pendingDelete: null, libraryExpanded: false,
};
const browserRequests = new Set();
const browserWanted = restoreBrowserWanted();
let taskRenderKey = '';
const downloads = createDownloadQueue({ onChange: handleTaskChanges, onComplete: () => loadLibrary(), watch: createTaskWatcher() });
const mediaIcons = { video: 'i-video', audio: 'i-audio', photos: 'i-photo' };

function fileKind(file) {
    return file.kind || (['ZIP', 'JPG', 'JPEG', 'PNG', 'WEBP', 'GIF', 'AVIF'].includes(file.format) ? 'photos' : ['MP4', 'WEBM'].includes(file.format) ? 'video' : 'audio');
}

function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#${name}`);
    svg.append(use);
    return svg;
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function showNotice(message, kind = 'error') {
    $('status-banner').className = `notice ${kind}`;
    $('banner-text').textContent = message;
    $('status-banner').hidden = false;
}

function hideNotice() { $('status-banner').hidden = true; }

function setAnalyzing(loading) {
    $('btn-analyze').disabled = loading;
    $('btn-paste').disabled = loading;
    $('btn-analyze').setAttribute('aria-busy', String(loading));
    let photoLink = false;
    try {
        const url = new URL($('yt-url-input').value);
        photoLink = (url.hostname === 'facebook.com' || url.hostname.endsWith('.facebook.com')) && (url.pathname.includes('/photo') || url.searchParams.has('fbid'));
    } catch { /* A general media link uses Continue. */ }
    $('btn-analyze').querySelector('.btn-text').textContent = loading ? 'Checking…' : photoLink ? 'Get photo' : 'Continue';
    $('analyze-spinner').hidden = !loading;
}

function invalidateAnalysis() {
    state.analysis?.abort();
    state.analysis = null;
    state.info = null;
    $('video-preview-card').hidden = true;
    $('btn-clear').hidden = !$('yt-url-input').value;
    $('yt-url-input').removeAttribute('aria-invalid');
    setAnalyzing(false);
}

async function analyze() {
    const raw = $('yt-url-input').value.trim();
    try {
        const parsed = new URL(raw);
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error();
    } catch {
        showNotice('Paste a valid public media link starting with https://.');
        $('yt-url-input').setAttribute('aria-invalid', 'true');
        $('yt-url-input').focus();
        return;
    }
    invalidateAnalysis();
    hideNotice();
    const controller = new AbortController();
    state.analysis = controller;
    setAnalyzing(true);
    try {
        const data = await request('/api/info', { method: 'POST', body: { url: raw }, signal: controller.signal });
        if (state.analysis !== controller) return;
        state.info = data;
        renderPreview(data);
    } catch (error) {
        if (error.name !== 'AbortError' && state.analysis === controller) showNotice(error.message);
    } finally {
        if (state.analysis === controller) { state.analysis = null; setAnalyzing(false); }
    }
}

function renderPreview(info) {
    const thumbnail = info.thumbnail;
    let safeThumbnail = false;
    try { safeThumbnail = ['https:', 'http:'].includes(new URL(thumbnail).protocol); } catch { /* Use the fallback. */ }
    $('video-thumb').hidden = !safeThumbnail;
    $('thumbnail-fallback').hidden = safeThumbnail;
    if (safeThumbnail) $('video-thumb').src = thumbnail;
    else $('video-thumb').removeAttribute('src');
    $('video-duration').textContent = info.duration;
    $('video-title').textContent = info.title;
    $('video-title').title = info.title;
    $('video-author').textContent = info.uploader;
    $('platform-badge').textContent = info.platform?.name || 'Web media';
    $('video-preview-card').hidden = false;
    const photos = info.media_type === 'photos';
    const singlePhoto = photos && info.photo_count === 1 && !info.has_music;
    $('video-preview-card').classList.toggle('single-photo', singlePhoto);
    $('single-photo-actions').hidden = !singlePhoto;
    $('output-controls').hidden = singlePhoto;
    $('video-formats').hidden = photos;
    $('photo-formats').hidden = !photos;
    $('photo-post-note').hidden = !photos;
    $('tab-format-slideshow').disabled = !info.has_music;
    $('tab-format-slideshow').title = info.has_music ? '' : 'The original music is not available for this post.';
    $('photo-previews').hidden = !photos || singlePhoto;
    $('photo-previews').replaceChildren();
    if (photos) {
        for (const [index, photo] of (info.photos || []).entries()) {
            const frame = element('div', 'photo-preview');
            const label = element('span', '', String(index + 1));
            const image = element('img');
            let safe = false;
            try { safe = ['http:', 'https:'].includes(new URL(photo.url).protocol); } catch { /* Use the photo number. */ }
            image.alt = `Photo ${index + 1} of ${info.photo_count}`;
            image.loading = 'lazy';
            image.referrerPolicy = 'no-referrer';
            image.addEventListener('error', () => { image.hidden = true; });
            if (safe) { image.src = photo.url; frame.append(image); }
            frame.append(label);
            $('photo-previews').append(frame);
        }
    }
    setFormat(photos ? 'photos' : 'mp4');
}

function setFormat(format) {
    state.format = format;
    for (const candidate of ['mp4', 'mp3', 'photos', 'slideshow']) {
        $(`tab-format-${candidate}`).classList.toggle('active', candidate === format);
        $(`tab-format-${candidate}`).setAttribute('aria-pressed', String(candidate === format));
    }
    $('quality-group-label').textContent = format === 'mp3' ? 'Bitrate' : 'Quality';
    $('output-note').hidden = format !== 'mp3';
    $('quality-control').hidden = format === 'photos';
    $('output-controls').classList.toggle('photos-output', format === 'photos');
    if (state.info?.media_type === 'photos') {
        const music = state.info.music?.title;
        $('photo-post-note').textContent = state.info.photo_count === 1 && !state.info.has_music
            ? 'Save the photo in its source format, or choose PNG.' : format === 'photos'
            ? `All ${state.info.photo_count} photo${state.info.photo_count === 1 ? '' : 's'}, in order, in one ZIP file.${music ? ` Music: ${music}.` : ' Original music is unavailable for this post.'}`
            : `Original music: ${music || 'Post soundtrack'}. Photos play in order, evenly timed across the music clip.`;
    }
    const options = (format === 'mp3' ? state.info?.audio_qualities : state.info?.qualities) || [];
    state.quality = options[0]?.id || (format === 'mp3' ? '320' : 'best');
    $('quality-select').replaceChildren();
    for (const option of options) {
        const choice = element('option', '', option.id === 'best' && format !== 'slideshow' ? 'Original (best)' : option.badge);
        choice.value = option.id;
        $('quality-select').append(choice);
    }
    $('quality-select').value = state.quality;
    updateSelection();
}

function updateSelection() {
    $('download-cta-label').textContent = state.submitting ? 'Starting…' : state.format === 'photos'
        ? 'Download all photos' : state.format === 'slideshow' ? 'Download slideshow' : 'Download';
    for (const id of ['btn-start-download', 'btn-save-photo', 'btn-save-png']) $(id).disabled = state.submitting || !state.compatible;
}

function browserDownload(id) {
    browserRequests.add(id);
    browserWanted.delete(id);
    persistBrowserWanted();
    const link = element('a');
    link.href = '/api/browser-download/' + encodeURIComponent(id);
    link.download = '';
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
    renderTasks();
}

function resetInput() {
    $('yt-url-input').value = '';
    invalidateAnalysis();
    $('yt-url-input').focus();
}

async function startDownload(payload = null) {
    if (!state.compatible) { showNotice('Use the updated app window to start new downloads. This earlier server is finishing your existing video.'); return; }
    if (state.submitting || (!state.info && !payload)) return;
    const info = state.info;
    const input = $('yt-url-input').value;
    const body = {
        ...(payload || { url: info.url, format: state.format, quality: state.quality }),
        title: Array.from(payload?.title || info?.title || 'Your media').slice(0, 180).join(''),
    };
    state.submitting = true;
    updateSelection();
    hideNotice();
    try {
        const data = await request('/api/download', { method: 'POST', body });
        const id = data.download_id;
        wantBrowser(id);
        downloads.add({ ...body, ...data.task, id, photo_count: info?.photo_count });
        if ($('yt-url-input').value === input) resetInput();
        showNotice('Preparing your file. It will save in your browser when ready. You can paste another link now.', 'success');
    } catch (error) {
        showNotice(error.message);
    } finally {
        state.submitting = false;
        updateSelection();
        renderTasks();
    }
}

const taskLabels = {
    queued: 'Queued', fetching_info: 'Checking source', downloading: 'Downloading',
    processing: 'Converting', finishing: 'Finishing', cancelling: 'Cancelling',
    cancelled: 'Cancelled', interrupted: 'Interrupted', completed: 'File ready',
    error: 'Failed',
};

function handleTaskChanges(tasks) {
    renderTasks();
    for (const task of tasks) {
        if (!browserWanted.has(task.id)) continue;
        // A complete, sized attachment avoids Chrome's long-running 0-byte request.
        if (task.status === 'completed' && !browserRequests.has(task.id)) browserDownload(task.id);
        if (terminalStatuses.has(task.status)) { browserWanted.delete(task.id); persistBrowserWanted(); }
    }
}

function taskFormat(task) {
    return task.format === 'photos' ? 'Photos · ZIP' : task.format === 'slideshow' ? 'Slideshow · MP4'
        : task.format === 'photo' ? 'Photo' : task.format === 'png' ? 'Photo · PNG' : task.format.toUpperCase();
}

function renderTasks() {
    const all = downloads.list();
    const active = all.filter(task => !terminalStatuses.has(task.status));
    const recent = all.filter(task => terminalStatuses.has(task.status)).slice(0, 3);
    const visible = [...active, ...recent].sort((a, b) => b.created_at - a.created_at);
    const key = JSON.stringify([state.submitting, ...visible.map(task => [task.id, task.status, task.detail, task.title, task.format, task.error, task.filename, task.managed_here, browserRequests.has(task.id), browserWanted.has(task.id)])]);
    if (key === taskRenderKey) { updateTaskProgress(visible); return; }
    taskRenderKey = key;
    $('tasks-section').hidden = !visible.length;
    $('tasks-count').textContent = active.length ? active.length + ' active' : '';
    const list = $('tasks-list');
    list.replaceChildren();
    for (const task of visible) {
        const terminal = terminalStatuses.has(task.status);
        const row = element('article', 'task-item ' + task.status);
        row.dataset.downloadId = task.id;
        const info = element('div', 'task-info');
        const title = element('span', 'task-title', task.title || 'Your media');
        title.title = task.title || 'Your media';
        const status = task.status === 'downloading' && task.detail ? task.detail : taskLabels[task.status] || 'Preparing';
        info.append(title, element('span', 'task-status', taskFormat(task) + ' · ' + status));
        if (!terminal) {
            const meter = element('progress', 'task-progress');
            meter.max = 100;
            meter.setAttribute('aria-label', 'Preparation progress for ' + (task.title || 'download'));
            info.append(meter, element('span', 'task-detail'));
        }
        if (terminal && task.error) info.append(element('p', 'task-error', task.error));
        const actions = element('div', 'task-actions');
        if (task.status === 'completed') {
            const save = element('a', 'button button-quiet', 'Save again');
            save.href = '/api/file/' + task.id;
            save.download = task.filename || '';
            save.addEventListener('click', () => { browserRequests.add(task.id); });
            actions.append(save);
        } else if (!terminal && !browserWanted.has(task.id)) {
            const save = element('button', 'button button-quiet', 'Save when ready');
            save.addEventListener('click', () => { wantBrowser(task.id); renderTasks(); });
            actions.append(save);
        } else if (terminal) {
            const retry = element('button', 'button button-quiet', 'Retry');
            retry.disabled = state.submitting;
            retry.addEventListener('click', () => startDownload({
                url: task.url, format: task.format, quality: task.quality,
                photo_index: task.photo_index || 0, title: task.title || 'Your media',
            }));
            actions.append(retry);
        }
        if (!terminal && task.managed_here !== false) {
            const cancel = element('button', 'text-button', task.status === 'cancelling' ? 'Cancelling…' : 'Cancel');
            cancel.setAttribute('aria-label', 'Cancel ' + (task.title || 'download'));
            cancel.disabled = task.status === 'cancelling';
            cancel.addEventListener('click', () => cancelDownload(task.id));
            actions.append(cancel);
        } else if (terminal) {
            const dismiss = element('button', 'icon-button');
            dismiss.setAttribute('aria-label', 'Hide download ' + (task.title || ''));
            dismiss.append(icon('i-close'));
            dismiss.addEventListener('click', () => downloads.remove(task.id));
            actions.append(dismiss);
        }
        row.append(info, actions);
        list.append(row);
    }
    updateTaskProgress(visible);
}

function updateTaskProgress(tasks) {
    for (const task of tasks) {
        if (terminalStatuses.has(task.status)) continue;
        const row = document.querySelector(`[data-download-id="${task.id}"]`);
        if (!row) continue;
        const percentage = Math.min(99, Math.max(0, Number(task.progress) || 0));
        const meter = row.querySelector('.task-progress');
        if (task.status === 'downloading' && task.total_bytes > 0) meter.value = percentage;
        else meter.removeAttribute('value');
        const details = [];
        if (task.status === 'downloading') {
            if (task.total_bytes > 0) details.push(`${percentage}% · ${readableSize(task.downloaded_bytes || 0)} / ${readableSize(task.total_bytes)}`);
            if (task.speed && task.speed !== '—') details.push(task.speed);
            if (task.eta && /^\d+s$/.test(task.eta)) details.push(formatRemaining(Number(task.eta.slice(0, -1))));
        }
        if (task.managed_here === false) details.push('Running in the previous window');
        if (Date.now() / 1000 - task.updated_at > 60) details.push('Waiting for a source update');
        row.querySelector('.task-detail').textContent = details.join(' · ') || (task.detail || 'Preparing the file for your browser');
    }
}

function formatRemaining(seconds) {
    if (seconds >= 3600) return `${Math.floor(seconds / 3600)}h ${Math.ceil(seconds % 3600 / 60)}m remaining`;
    if (seconds >= 60) return `${Math.ceil(seconds / 60)}m remaining`;
    return `${seconds}s remaining`;
}

async function restoreTasks() {
    try {
        const { tasks } = await request('/api/tasks');
        const failures = tasks.filter(task => ['error', 'interrupted', 'cancelled'].includes(task.status)).slice(0, 3);
        for (const task of [...tasks.filter(task => !terminalStatuses.has(task.status) || browserWanted.has(task.id)), ...failures]) downloads.add(task);
        try { sessionStorage.removeItem('snacky.activeTask'); } catch { /* Optional old-session cleanup. */ }
    } catch { /* Health and library errors provide connection feedback. */ }
}

function restoreBrowserWanted() {
    try {
        const ids = JSON.parse(sessionStorage.getItem('snacky.browserWanted') || '[]');
        return new Set(Array.isArray(ids) ? ids.filter(id => typeof id === 'string' && /^[a-f0-9-]{36}$/.test(id)) : []);
    } catch { return new Set(); }
}

function persistBrowserWanted() {
    try { sessionStorage.setItem('snacky.browserWanted', JSON.stringify([...browserWanted])); } catch { /* Saving still works without storage. */ }
}

function wantBrowser(id) { browserWanted.add(id); persistBrowserWanted(); }

async function cancelDownload(id) {
    try {
        const task = await request('/api/cancel/' + id, { method: 'POST' });
        downloads.update(id, task);
    } catch (error) { showNotice(error.message); }
}

async function loadLibrary() {
    $('btn-refresh-history').disabled = true;
    try {
        const data = await request('/api/history');
        state.files = data.files;
        renderLibrary();
    } catch (error) {
        $('library-summary').textContent = 'Library unavailable. Try Refresh when the server is running.';
        showNotice(error.message);
    } finally { $('btn-refresh-history').disabled = false; }
}

function readableSize(bytes) {
    for (const unit of ['B', 'KB', 'MB', 'GB']) {
        if (bytes < 1024 || unit === 'GB') return `${bytes.toFixed(bytes < 10 ? 1 : 0)} ${unit}`;
        bytes /= 1024;
    }
}

function renderLibrary() {
    $('history-title').textContent = state.libraryExpanded ? 'All downloads' : 'Recent downloads';
    $('library-toolbar').hidden = !state.libraryExpanded;
    $('btn-toggle-library').hidden = !state.files.length;
    $('btn-toggle-library').textContent = state.libraryExpanded ? 'Show less' : `View all (${state.files.length})`;
    $('btn-toggle-library').setAttribute('aria-expanded', String(state.libraryExpanded));
    const query = $('library-search').value.trim().toLocaleLowerCase();
    const matches = state.files.filter(file => {
        return (state.filter === 'all' || state.filter === fileKind(file)) && file.filename.toLocaleLowerCase().includes(query);
    });
    const files = state.libraryExpanded ? matches : state.files.slice(0, 3);
    $('history-list').replaceChildren();
    if (!files.length) {
        const empty = element('div', 'history-empty');
        empty.append(element('h3', '', state.files.length ? 'No matching files' : 'No downloads yet'),
            element('p', '', state.files.length ? 'Try another search or file type.' : 'Your saved files will appear here.'));
        $('history-list').append(empty);
    }
    for (const file of files) {
        const kind = fileKind(file);
        const row = element('article', 'history-item');
        const info = element('div', 'history-file-info');
        const fileIcon = element('span', `file-icon ${kind}`);
        fileIcon.append(icon(mediaIcons[kind]));
        const details = element('div', 'file-details');
        const displayName = file.filename.replace(/\s\[[a-f0-9-]{6,36}\](?=\.[^.]+$)/i, '');
        const name = element('span', 'file-name', displayName);
        name.title = file.filename;
        details.append(name, element('span', 'file-subtitle', `${file.format === 'ZIP' ? 'Photos · ZIP' : file.format} · ${file.size}`));
        info.append(fileIcon, details);
        const meta = element('div', 'file-meta');
        const date = new Date(file.created_at * 1000);
        const time = element('time', '', date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }));
        time.dateTime = date.toISOString();
        meta.append(time);
        const actions = element('div', 'history-actions');
        const save = element('a', 'button button-quiet');
        save.href = `/api/download-file?filename=${encodeURIComponent(file.filename)}`;
        save.download = file.filename;
        save.setAttribute('aria-label', `Save ${displayName}`);
        save.append(icon('i-download'), element('span', '', 'Save'));
        const remove = element('button', 'icon-button');
        remove.setAttribute('aria-label', `Delete ${displayName}`);
        remove.append(icon('i-trash'));
        remove.addEventListener('click', () => {
            state.pendingDelete = file.filename;
            $('delete-filename').textContent = file.filename;
            $('delete-dialog').showModal();
            $('btn-delete-cancel').focus();
        });
        actions.append(save, remove);
        row.append(info, meta, actions);
        $('history-list').append(row);
    }
    const size = state.files.reduce((total, file) => total + file.size_bytes, 0);
    $('library-summary').textContent = state.files.length
        ? `${state.libraryExpanded ? `${files.length} of ` : ''}${state.files.length} ${state.files.length === 1 ? 'file' : 'files'} · ${readableSize(size)}` : '';
}

async function deleteFile() {
    if (!state.pendingDelete) return;
    $('btn-delete-confirm').disabled = true;
    try {
        await request(`/api/history/${encodeURIComponent(state.pendingDelete)}`, { method: 'DELETE' });
        $('delete-dialog').close();
        state.pendingDelete = null;
        await loadLibrary();
        showNotice('File removed from your downloads folder.', 'success');
    } catch (error) { $('delete-dialog').close(); showNotice(error.message); }
    finally { $('btn-delete-confirm').disabled = false; }
}

async function openFolder() {
    try { await request('/api/open-folder', { method: 'POST' }); showNotice('Your downloads folder is open.', 'success'); }
    catch (error) { showNotice(error.message); }
}

async function checkHealth() {
    try {
        const health = await request('/api/health');
        const [major, minor] = (health.version || '').split('.').map(Number);
        state.compatible = major > 2 || (major === 2 && minor >= 3);
        updateSelection();
        if (!state.compatible) showNotice('Use the updated app window to start new downloads. This earlier server is finishing your existing video.');
        $('connection-status').className = 'connection-pill online';
        $('connection-label').textContent = 'Local';
    } catch {
        $('connection-status').className = 'connection-pill offline';
        $('connection-label').textContent = 'Server offline';
    }
}

$('url-form').addEventListener('submit', event => { event.preventDefault(); analyze(); });
$('yt-url-input').addEventListener('input', invalidateAnalysis);
$('btn-clear').addEventListener('click', () => { $('yt-url-input').value = ''; invalidateAnalysis(); hideNotice(); $('yt-url-input').focus(); });
$('btn-paste').addEventListener('click', async () => {
    try {
        const text = await navigator.clipboard.readText();
        if (!text.trim()) { showNotice('Your clipboard is empty. Copy a media link first.'); return; }
        $('yt-url-input').value = text.trim();
        await analyze();
    } catch { showNotice('Clipboard access is unavailable. Paste your link with Ctrl+V or ⌘V.'); $('yt-url-input').focus(); }
});
$('video-thumb').addEventListener('error', () => { $('video-thumb').hidden = true; $('thumbnail-fallback').hidden = false; });
$('tab-format-mp4').addEventListener('click', () => setFormat('mp4'));
$('tab-format-mp3').addEventListener('click', () => setFormat('mp3'));
$('tab-format-photos').addEventListener('click', () => setFormat('photos'));
$('tab-format-slideshow').addEventListener('click', () => setFormat('slideshow'));
$('quality-select').addEventListener('change', event => { state.quality = event.target.value; updateSelection(); });
$('btn-start-download').addEventListener('click', () => startDownload());
$('btn-save-photo').addEventListener('click', () => startDownload({ url: state.info.url, format: 'photo', quality: 'best', photo_index: 0 }));
$('btn-save-png').addEventListener('click', () => startDownload({ url: state.info.url, format: 'png', quality: 'best', photo_index: 0 }));
$('btn-download-another').addEventListener('click', () => {
    resetInput(); hideNotice();
    window.scrollTo({ top: 0, behavior: 'smooth' });
});
$('btn-open-folder').addEventListener('click', openFolder);
$('btn-refresh-history').addEventListener('click', loadLibrary);
$('btn-toggle-library').addEventListener('click', () => {
    state.libraryExpanded = !state.libraryExpanded;
    if (!state.libraryExpanded) {
        state.filter = 'all';
        $('library-search').value = '';
        document.querySelectorAll('[data-filter]').forEach(button => {
            const active = button.dataset.filter === 'all';
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', String(active));
        });
    }
    renderLibrary();
});
$('library-search').addEventListener('input', renderLibrary);
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(item => {
        item.classList.toggle('active', item === button);
        item.setAttribute('aria-pressed', String(item === button));
    });
    renderLibrary();
}));
$('btn-dismiss-banner').addEventListener('click', hideNotice);
$('btn-guide').addEventListener('click', () => $('guide-dialog').showModal());
$('btn-close-guide').addEventListener('click', () => $('guide-dialog').close());
$('btn-guide-done').addEventListener('click', () => $('guide-dialog').close());
$('btn-delete-cancel').addEventListener('click', () => $('delete-dialog').close());
$('btn-delete-confirm').addEventListener('click', deleteFile);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { checkHealth(); loadLibrary(); } });
window.addEventListener('pagehide', () => { downloads.stopAll(); state.analysis?.abort(); });
window.addEventListener('pageshow', event => { if (event.persisted) downloads.resumeAll(); });
document.querySelectorAll('svg.icon').forEach(svg => svg.setAttribute('aria-hidden', 'true'));
Promise.allSettled([checkHealth(), loadLibrary(), restoreTasks()]);
