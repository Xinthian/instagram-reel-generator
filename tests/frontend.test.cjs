const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'server.py'), 'utf8');
const html = source.split('html_content = r"""')[1].split('"""')[0];
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}

function harness({ fetch, storage, aiCaptionsEnabled = true } = {}) {
    const elements = {};
    for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
        const classes = new Set();
        elements[id] = {
            id, value: '', files: [], style: {}, disabled: false, required: false,
            listeners: {}, attributes: {},
            classList: { add: value => classes.add(value), remove: value => classes.delete(value) },
            setAttribute(name, value) { this.attributes[name] = value; },
            addEventListener(name, listener) { this.listeners[name] = listener; },
        };
    }
    const calls = [];
    const alerts = [];
    const anchors = [];
    const timers = [];
    const revoked = [];
    const context = {
        document: {
            getElementById: id => elements[id],
            querySelectorAll: () => [elements['btn-url'], elements['btn-custom']],
            createElement() {
                const anchor = { style: {}, click() { this.clicked = true; }, remove() { this.removed = true; } };
                anchors.push(anchor);
                return anchor;
            },
            body: { appendChild(anchor) { anchor.appended = true; } },
        },
        FormData: class {
            constructor() { this.fields = new Map(); }
            append(name, value) { this.fields.set(name, value); }
        },
        fetch: async (...args) => {
            calls.push(args);
            if (!fetch) throw new Error('Unexpected request');
            return fetch(...args);
        },
        URL: { createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url) },
        localStorage: storage || { getItem: () => null, setItem() {} },
        alert: message => alerts.push(message),
        setTimeout: (callback, delay) => timers.push({ callback, delay }),
        location: { href: '', assign(url) { this.href = url; } },
    };
    context.window = context;
    vm.createContext(context);
    vm.runInContext(script.replace('__AI_CAPTIONS_ENABLED__', String(aiCaptionsEnabled)), context);
    return {
        context, elements, calls, alerts, anchors, timers, revoked,
        submit: () => elements.genForm.listeners.submit({ preventDefault() {} }),
        upload() {
            context.switchTab('custom');
            elements.video.files = [{ name: 'video.mp4', size: 1024 }];
            elements.screenshot.files = [{ name: 'caption.png', size: 1024 }];
            elements.caption.value = 'Original caption';
        },
    };
}

const failure = (detail, status = 422) => ({ ok: false, status, text: async () => JSON.stringify({ detail }) });
const videoResponse = { ok: true, blob: async () => ({ type: 'video/mp4' }) };

test('inactive controls leave validation and preserve their values across modes', () => {
    const h = harness();
    assert.equal(h.elements.url.disabled, false);
    for (const id of ['video', 'screenshot', 'btn-generate-caption']) {
        assert.equal(h.elements[id].disabled, true, id);
    }
    assert.equal(h.elements.caption.disabled, false);
    h.elements.url.value = 'not a valid URL';
    h.context.switchTab('custom');
    assert.equal(h.elements.url.disabled, true);
    assert.equal(h.elements.url.required, false);
    assert.equal(h.elements.video.required, true);
    assert.equal(h.elements.caption.required, true);
    assert.equal(h.elements.caption.disabled, false);
    h.context.switchTab('url');
    assert.equal(h.elements.url.value, 'not a valid URL');
    assert.equal(h.elements.caption.required, false);
});

test('manual URL captions are submitted whether AI captions are enabled or disabled', async () => {
    for (const aiCaptionsEnabled of [true, false]) {
        const h = harness({ aiCaptionsEnabled, fetch: () => videoResponse });
        h.elements.url.value = 'https://www.instagram.com/reel/example/';
        h.elements.caption.value = '{A manual} Instagram caption';
        assert.equal(h.elements.caption.required, !aiCaptionsEnabled);
        assert.equal(h.elements.caption.disabled, false);
        assert.equal(h.elements['ai-caption-status'].style.display, aiCaptionsEnabled ? 'none' : 'block');
        await h.submit();
        assert.equal(h.calls[0][1].body.fields.get('caption'), '{A manual} Instagram caption');
        assert.equal(h.calls[0][1].body.fields.get('url'), h.elements.url.value);
        assert.equal(h.anchors[0].clicked, true);
        assert.equal(h.elements.caption.disabled, false);
        assert.equal(h.elements.caption.required, !aiCaptionsEnabled);
    }
});

test('disabled AI keeps OCR unavailable and requires manual captions in both modes', async () => {
    const h = harness({ aiCaptionsEnabled: false, fetch: () => videoResponse });
    assert.equal(h.elements.caption.required, true);
    h.upload();
    assert.equal(h.elements.caption.required, true);
    assert.equal(h.elements.screenshot.disabled, true);
    assert.equal(h.elements['btn-generate-caption'].disabled, true);
    await h.context.generateCaption();
    assert.equal(h.calls.length, 0);
    await h.submit();
    assert.equal(h.calls[0][1].body.fields.get('caption'), 'Original caption');
    assert.equal(h.elements['btn-generate-caption'].disabled, true);
    h.context.switchTab('url');
    assert.equal(h.elements.caption.value, 'Original caption');
    assert.equal(h.elements.caption.required, true);
});

test('enabled AI allows a URL without a manual caption', async () => {
    const h = harness({ aiCaptionsEnabled: true, fetch: () => videoResponse });
    assert.equal(h.elements.caption.required, false);
    await h.submit();
    assert.equal(h.calls[0][1].body.fields.has('caption'), false);
    h.upload();
    assert.equal(h.elements.caption.required, true);
    assert.equal(h.elements['btn-generate-caption'].disabled, false);
});

test('OCR failures preserve caption and reenable controls', async () => {
    const h = harness({ fetch: () => failure('No text could be extracted from the screenshot.') });
    h.upload();
    await h.context.generateCaption();
    assert.equal(h.elements.caption.value, 'Original caption');
    assert.match(h.alerts[0], /^OCR_FAULT: No text could be extracted/);
    assert.equal(h.elements.submitBtn.disabled, false);
    assert.equal(h.elements['btn-generate-caption'].disabled, false);
});


test('pending OCR prevents duplicate extraction, mode changes, and generation with stale text', async () => {
    const pending = deferred();
    const h = harness({ fetch: () => pending.promise });
    h.upload();
    const extraction = h.context.generateCaption();
    assert.equal(h.elements.caption.disabled, true);
    assert.equal(h.elements.submitBtn.disabled, true);
    h.context.switchTab('url');
    await h.context.generateCaption();
    await h.submit();
    assert.equal(h.calls.length, 1);
    pending.resolve({ ok: true, json: async () => ({ caption: 'Fresh extracted caption' }) });
    await extraction;
    assert.equal(h.elements.caption.value, 'Fresh extracted caption');
    assert.equal(h.elements.caption.disabled, false);
    assert.equal(h.elements.url.disabled, true);
});

test('empty or oversized successful OCR responses preserve existing caption', async () => {
    for (const caption of ['', ' '.repeat(3), 'x'.repeat(501), null]) {
        const h = harness({ fetch: () => ({ ok: true, json: async () => ({ caption }) }) });
        h.upload();
        await h.context.generateCaption();
        assert.equal(h.elements.caption.value, 'Original caption');
        assert.equal(h.alerts.length, 1);
    }
});

test('generation failures preserve form and stop duplicate or OCR requests while pending', async () => {
    const pending = deferred();
    const h = harness({ fetch: () => pending.promise });
    h.upload();
    const generation = h.submit();
    await h.submit();
    await h.context.generateCaption();
    h.context.switchTab('url');
    assert.equal(h.calls.length, 1);
    assert.equal(h.elements['btn-custom'].disabled, true);
    assert.equal(h.calls[0][1].body.fields.get('caption'), 'Original caption');
    pending.resolve(failure('Another job is running. Try again shortly.', 429));
    await generation;
    assert.match(h.alerts[0], /Another job is running/);
    assert.equal(h.elements.caption.value, 'Original caption');
    assert.equal(h.elements.video.files[0].name, 'video.mp4');
    assert.equal(h.elements.submitBtn.disabled, false);
    assert.equal(h.elements.url.disabled, true);
    assert.equal(h.elements.loader.style.display, 'none');
});

test('downloads succeed when storage reads or writes are blocked and defer blob cleanup', async () => {
    for (const storage of [
        { getItem() { throw new Error('Blocked'); }, setItem() { throw new Error('Blocked'); } },
        { getItem: () => '12', setItem() { throw new Error('Quota exceeded'); } },
    ]) {
        const h = harness({ fetch: () => videoResponse, storage });
        h.elements.url.value = 'https://www.instagram.com/reel/example/';
        await h.submit();
        assert.deepEqual(h.alerts, []);
        assert.equal(h.anchors.length, 1);
        assert.equal(h.anchors[0].clicked, true);
        assert.equal(h.anchors[0].removed, true);
        assert.match(h.anchors[0].download, /^BLUNT INDIAN V000(01|12)\.mp4$/);
        assert.deepEqual(h.revoked, []);
        assert.equal(h.timers.length, 1);
        assert.ok(h.timers[0].delay >= 1000);
        h.timers[0].callback();
        assert.deepEqual(h.revoked, ['blob:test']);
    }
});

test('corrupt stored counters do not produce malformed filenames', async () => {
    for (const stored of ['NaN', '-1', '0', '3.2', '12oops', '9007199254740992']) {
        const h = harness({ fetch: () => videoResponse, storage: { getItem: () => stored, setItem() {} } });
        await h.submit();
        assert.equal(h.anchors[0].download, 'BLUNT INDIAN V00001.mp4');
    }
});

test('oversized uploads fail early with no request', async () => {
    const h = harness();
    h.upload();
    h.elements.screenshot.files[0].size = 10 * 1024 * 1024 + 1;
    await h.context.generateCaption();
    h.elements.video.files[0].size = 100 * 1024 * 1024 + 1;
    await h.submit();
    assert.equal(h.calls.length, 0);
    assert.match(h.alerts[0], /Screenshot must be 10 MiB or smaller/);
    assert.match(h.alerts[1], /Video must be 100 MiB or smaller/);
    assert.equal(h.elements.submitBtn.disabled, false);
});

test('HTML gateway failures show a useful status instead of markup', async () => {
    const h = harness({ fetch: () => ({ ok: false, status: 502, text: async () => '<html>Gateway error</html>' }) });
    await h.submit();
    assert.equal(h.alerts[0], 'SYS_ERROR: Reel generation failed (HTTP 502).');
});
