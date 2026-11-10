/** Independent subscriptions: one download can never replace another's state. */
import { watchProgress, terminalStatuses } from './progress.js';

export function createDownloadQueue({ onChange = () => {}, onComplete = () => {}, watch = watchProgress } = {}) {
    const tasks = new Map();
    const subscriptions = new Map();

    function update(id, changes) {
        const previous = tasks.get(id);
        if (!previous || terminalStatuses.has(previous.status)) return previous;
        const task = { ...previous, ...changes, id };
        if (!['error', 'interrupted'].includes(task.status)) task.error = null;
        tasks.set(id, task);
        if (terminalStatuses.has(task.status)) {
            subscriptions.get(id)?.stop?.();
            subscriptions.delete(id);
        }
        onChange(list());
        if (task.status === 'completed') onComplete(task);
        return task;
    }

    function subscribe(task) {
        if (terminalStatuses.has(task.status) || subscriptions.has(task.id)) return;
        const entry = { stop: null };
        subscriptions.set(task.id, entry);
        const stop = watch(task.id, changes => {
            if (subscriptions.get(task.id) === entry) update(task.id, changes);
        });
        // A synchronous completion must not leave a subscription behind.
        if (terminalStatuses.has(tasks.get(task.id)?.status)) stop();
        else entry.stop = stop;
    }

    function add(snapshot) {
        if (tasks.has(snapshot.id)) return tasks.get(snapshot.id);
        const task = { created_at: Date.now() / 1000, status: 'queued', progress: 0, ...snapshot };
        if (!['error', 'interrupted'].includes(task.status)) task.error = null;
        tasks.set(task.id, task);
        onChange(list());
        subscribe(task);
        return task;
    }

    function remove(id) {
        subscriptions.get(id)?.stop?.();
        subscriptions.delete(id);
        tasks.delete(id);
        onChange(list());
    }

    function stopAll() {
        for (const entry of subscriptions.values()) entry.stop?.();
        subscriptions.clear();
    }

    function list() { return [...tasks.values()].sort((a, b) => b.created_at - a.created_at); }
    function resumeAll() { for (const task of tasks.values()) subscribe(task); }
    return { add, update, remove, stopAll, resumeAll, list, get: id => tasks.get(id) };
}
