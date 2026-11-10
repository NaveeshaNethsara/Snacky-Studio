/** One SSE subscription with a serial, cancellable polling fallback. */
import { request } from './api.js';

export const terminalStatuses = new Set(['completed', 'error', 'cancelled', 'interrupted']);

/** Compact task lists share one serial poll, leaving browser connections free for files. */
export function createTaskWatcher() {
    const listeners = new Map();
    let timer = null;
    let controller = null;
    let polling = false;
    let failures = 0;

    async function poll() {
        if (polling || !listeners.size) return;
        polling = true;
        controller = new AbortController();
        const timeout = setTimeout(() => controller?.abort(), 10000);
        try {
            const { tasks } = await request('/api/tasks', { signal: controller.signal });
            failures = 0;
            for (const [id, callback] of [...listeners]) {
                if (listeners.get(id) !== callback) continue;
                const task = tasks.find(item => item.id === id);
                if (task) callback(task);
                else callback({ id, status: 'interrupted', error: 'This task is no longer available. Start the download again.' });
            }
        } catch { failures += 1; }
        finally {
            clearTimeout(timeout);
            controller = null;
            polling = false;
            if (listeners.size) timer = setTimeout(poll, Math.min(10000, 800 * 2 ** Math.min(failures, 4)));
        }
    }

    return (id, callback) => {
        listeners.set(id, callback);
        if (!polling) { clearTimeout(timer); poll(); }
        return () => {
            if (listeners.get(id) === callback) listeners.delete(id);
            if (!listeners.size) { clearTimeout(timer); controller?.abort(); }
        };
    };
}

export function watchProgress(id, onUpdate, onConnection = () => {}) {
    let source = null;
    let timer = null;
    let controller = null;
    let stopped = false;
    let polling = false;
    let failures = 0;

    function stop() {
        stopped = true;
        source?.close();
        clearTimeout(timer);
        controller?.abort();
    }

    function deliver(data) {
        if (stopped) return;
        if (terminalStatuses.has(data.status)) stop();
        onUpdate(data);
    }

    async function poll() {
        if (stopped) return;
        controller = new AbortController();
        const timeout = setTimeout(() => controller?.abort(), 10000);
        try {
            const data = await request(`/api/progress/${id}`, { signal: controller.signal });
            if (stopped) return;
            failures = 0;
            onConnection('connected');
            deliver(data);
        } catch (error) {
            if (stopped) return;
            if ([404, 422].includes(error.status)) {
                deliver({ id, status: 'interrupted', error: 'This task is no longer available. Start the download again.' });
                return;
            }
            failures += 1;
            onConnection('reconnecting');
        } finally {
            clearTimeout(timeout);
        }
        if (!stopped) timer = setTimeout(poll, Math.min(10000, 800 * 2 ** Math.min(failures, 4)));
    }

    function fallback() {
        if (stopped || polling) return;
        polling = true;
        source?.close();
        clearTimeout(timer);
        poll();
    }

    if (typeof EventSource === 'undefined') {
        fallback();
    } else {
        source = new EventSource(`/api/stream-progress/${id}`);
        source.onopen = () => { clearTimeout(timer); onConnection('connected'); };
        source.onmessage = event => {
            try { deliver(JSON.parse(event.data)); } catch { fallback(); }
        };
        source.onerror = fallback;
        timer = setTimeout(fallback, 6000);
    }
    return stop;
}

