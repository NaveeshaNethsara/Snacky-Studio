import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const encode = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const apiUrl = encode(await readFile(new URL('../app/static/api.js', import.meta.url), 'utf8'));
const progressUrl = encode((await readFile(new URL('../app/static/progress.js', import.meta.url), 'utf8')).replace("'./api.js'", JSON.stringify(apiUrl)));
const { createTaskWatcher } = await import(progressUrl);
const { createDownloadQueue } = await import(encode((await readFile(new URL('../app/static/downloads.js', import.meta.url), 'utf8')).replace("'./progress.js'", JSON.stringify(progressUrl))));

function fixture() {
    const callbacks = new Map();
    const stopped = [];
    const completed = [];
    const queue = createDownloadQueue({
        watch: (id, callback) => { callbacks.set(id, callback); return () => stopped.push(id); },
        onComplete: task => completed.push(task.id),
    });
    return { queue, callbacks, stopped, completed };
}

test('two downloads retain independent state and each completes once', () => {
    const { queue, callbacks, stopped, completed } = fixture();
    queue.add({ id: 'first', status: 'downloading', title: 'First' });
    queue.add({ id: 'second', status: 'downloading', title: 'Second' });
    callbacks.get('first')({ status: 'completed', filename: 'first.mp4' });
    callbacks.get('first')({ status: 'completed', filename: 'wrong.mp4' });
    callbacks.get('second')({ id: 'first', status: 'processing', progress: 99 });
    assert.equal(queue.get('first').filename, 'first.mp4');
    assert.equal(queue.get('second').status, 'processing');
    assert.equal(queue.get('second').id, 'second');
    assert.deepEqual(stopped, ['first']);
    assert.deepEqual(completed, ['first']);
    callbacks.get('second')({ status: 'completed' });
    assert.deepEqual(completed, ['first', 'second']);
});

test('restoring stale snapshots cannot replace newer updates or duplicate subscriptions', () => {
    const { queue, callbacks } = fixture();
    queue.add({ id: 'first', status: 'downloading', progress: 10 });
    callbacks.get('first')({ status: 'processing', progress: 99 });
    queue.add({ id: 'first', status: 'queued', progress: 0 });
    assert.equal(queue.get('first').status, 'processing');
    assert.equal(callbacks.size, 1);
});

test('active snapshots discard stale errors while terminal failures retain them', () => {
    const { queue, callbacks } = fixture();
    queue.add({ id: 'first', status: 'downloading', error: 'Earlier server stopped' });
    assert.equal(queue.get('first').error, null);
    callbacks.get('first')({ status: 'processing', error: 'Earlier server stopped' });
    assert.equal(queue.get('first').error, null);
    callbacks.get('first')({ status: 'error', error: 'Conversion failed' });
    assert.equal(queue.get('first').error, 'Conversion failed');
    queue.add({ id: 'second', status: 'downloading' });
    callbacks.get('second')({ status: 'completed', error: 'Earlier server stopped' });
    assert.equal(queue.get('second').error, null);
});

test('synchronous completion still disposes the subscription', () => {
    let stops = 0;
    const queue = createDownloadQueue({ watch: (_id, callback) => {
        callback({ status: 'completed' });
        return () => { stops += 1; };
    } });
    queue.add({ id: 'first' });
    queue.stopAll();
    assert.equal(stops, 1);
});

test('disposal ignores late updates and a restored page resumes only active tasks', () => {
    const { queue, callbacks, completed } = fixture();
    queue.add({ id: 'first', status: 'downloading' });
    queue.add({ id: 'second', status: 'completed' });
    const oldCallback = callbacks.get('first');
    queue.stopAll();
    oldCallback({ status: 'completed' });
    assert.equal(queue.get('first').status, 'downloading');
    queue.resumeAll();
    oldCallback({ status: 'error' });
    assert.equal(queue.get('first').status, 'downloading');
    callbacks.get('first')({ status: 'completed' });
    assert.deepEqual(completed, ['first']);
    assert.equal(callbacks.has('second'), false);
});

test('hiding a task prevents late callbacks from recreating it', () => {
    const { queue, callbacks } = fixture();
    queue.add({ id: 'first' });
    queue.remove('first');
    callbacks.get('first')({ status: 'completed' });
    assert.equal(queue.get('first'), undefined);
});

test('many downloads share one pending task poll and stop polling on completion', async () => {
    let calls = 0;
    let resolveFetch;
    globalThis.fetch = () => { calls += 1; return new Promise(resolve => { resolveFetch = resolve; }); };
    const watch = createTaskWatcher();
    const updates = [];
    const stops = ['first', 'second', 'third'].map(id => watch(id, task => {
        updates.push(task.id);
        stops.forEach(stop => stop());
    }));
    assert.equal(calls, 1);
    resolveFetch({ ok: true, json: async () => ({ tasks: [{ id: 'first', status: 'completed' }] }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(updates, ['first']);
    assert.equal(calls, 1);
});

test('the last task subscriber aborts its pending poll and suppresses late updates', async () => {
    let signal;
    let resolveFetch;
    globalThis.fetch = (_url, options) => {
        signal = options.signal;
        return new Promise(resolve => { resolveFetch = resolve; });
    };
    const updates = [];
    const stop = createTaskWatcher()('first', task => updates.push(task));
    stop();
    assert.equal(signal.aborted, true);
    resolveFetch({ ok: true, json: async () => ({ tasks: [{ id: 'first', status: 'completed' }] }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(updates.length, 0);
});
