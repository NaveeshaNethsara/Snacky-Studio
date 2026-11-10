import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const encode = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const apiSource = await readFile(new URL('../app/static/api.js', import.meta.url), 'utf8');
const apiUrl = encode(apiSource);
const api = await import(apiUrl);
const progressSource = (await readFile(new URL('../app/static/progress.js', import.meta.url), 'utf8')).replace("'./api.js'", JSON.stringify(apiUrl));
const { watchProgress } = await import(encode(progressSource));

class FakeSource {
    static instances = [];
    constructor() { this.closed = false; FakeSource.instances.push(this); }
    close() { this.closed = true; }
}

test('completion closes SSE and late events cannot complete the task twice', () => {
    globalThis.EventSource = FakeSource;
    const updates = [];
    const stop = watchProgress('id', task => updates.push(task));
    const source = FakeSource.instances.at(-1);
    source.onmessage({ data: JSON.stringify({ status: 'completed', progress: 100 }) });
    source.onmessage({ data: JSON.stringify({ status: 'completed', progress: 100 }) });
    assert.equal(source.closed, true);
    assert.equal(updates.length, 1);
    stop();
});

test('multiple SSE errors start only one polling request', async () => {
    globalThis.EventSource = FakeSource;
    let calls = 0;
    globalThis.fetch = async () => {
        calls += 1;
        return { ok: true, json: async () => ({ status: 'completed' }) };
    };
    const updates = [];
    const stop = watchProgress('id', task => updates.push(task));
    const source = FakeSource.instances.at(-1);
    source.onerror();
    source.onerror();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls, 1);
    assert.equal(updates.length, 1);
    stop();
});

test('stopping a poll aborts its fetch and suppresses late updates', async () => {
    globalThis.EventSource = FakeSource;
    let signal;
    globalThis.fetch = (_path, options) => {
        signal = options.signal;
        return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))));
    };
    const updates = [];
    const stop = watchProgress('id', task => updates.push(task));
    FakeSource.instances.at(-1).onerror();
    stop();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(signal.aborted, true);
    assert.equal(updates.length, 0);
});

test('validation errors are shown as readable text', async () => {
    globalThis.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ msg: 'Choose a valid bitrate.' }] }) });
    await assert.rejects(api.request('/api/download'), error => error.message === 'Choose a valid bitrate.' && error.status === 422);
});
