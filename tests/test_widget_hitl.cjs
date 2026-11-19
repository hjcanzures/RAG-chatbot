const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = []; this.listeners = {}; this.attributes = {}; this.style = { setProperty(name, value) { this[name] = value; } };
    this.className = ''; this.value = ''; this.textContent = ''; this.disabled = false;
    this.classList = {
      add: (name) => { this.className += ` ${name}`; },
      contains: (name) => this.className.split(/\s+/).includes(name),
      toggle: (name, on) => {
        this.className = this.className.split(/\s+/).filter((item) => item !== name).join(' ');
        if (on) this.className += ` ${name}`;
      },
    };
  }
  set innerHTML(value) {
    this.html = value;
    if (value.includes('class="neu-launcher"')) {
      for (const name of ['neu-launcher', 'neu-hint__text', 'neu-panel__close', 'neu-messages', 'neu-input', 'neu-send']) {
        const element = new Element(); element.className = name; this.appendChild(element);
      }
    }
  }
  get innerHTML() { return this.html; }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  async click() { for (const callback of this.listeners.click || []) await callback({}); }
  dispatchEvent(event) { this.events.push(event); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const name = selector.slice(1); const result = [];
    for (const child of this.children) {
      if (child.classList.contains(name)) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  getBoundingClientRect() { return { left: 900, right: 988, top: 660, bottom: 748, width: 88, height: 88 }; }
  setPointerCapture(id) { this.capture = id; }
  hasPointerCapture(id) { return this.capture === id; }
  releasePointerCapture() { this.capture = null; }
  async emit(name, event) { for (const callback of this.listeners[name] || []) await callback(event); }
  focus() {}
  remove() { this.parent.children = this.parent.children.filter((child) => child !== this); }
}

function setup(data = { answer: 'Admissions answer', sources: [{ filename: 'guide.pdf' }] }, options = {}) {
  const body = new Element();
  const timers = new Map(); let timerId = 0;
  const context = {
    window: { innerWidth: 1024, innerHeight: 768, addEventListener() {}, ...options.window, NeuWidgetConfig: { hintMessages: ['Ask Neubie'], minSendIntervalMs: 0, ...options.config } },
    document: { body, readyState: 'complete', baseURI: 'http://localhost:8000/demo.html', createElement: () => new Element() },
    navigator: options.navigator || {},
    console: { error() {} }, URL, AbortController, setTimeout: (fn) => { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); }, setInterval() {},
    CustomEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init); } },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (url.endsWith('/feedback') && options.feedbackFail) return { ok: false, status: 500 };
      if (options.fail) throw new Error('Network failure');
      return { ok: options.status ? options.status < 400 : true, status: options.status || 200, json: async () => data };
    },
  };
  const calls = [];
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../widget/neu-widget.js'), 'utf8'), context);
  const root = body.children[0]; root.events = [];
  return { root, calls, finishReactions() { const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn()); }, async send(query = 'How do I enroll?') {
    root.querySelector('.neu-input').value = query;
    await root.querySelector('.neu-send').click();
    return root.querySelector('.neu-messages').children.at(-1);
  } };
}

test('visible viewport tracks keyboard resize and pan without negative bottom offsets', () => {
  const listeners = {};
  const viewport = { height: 700, offsetTop: 0, addEventListener(name, fn) { listeners[name] = fn; } };
  const ui = setup(undefined, { window: { innerHeight: 700, visualViewport: viewport } });
  assert.equal(ui.root.style['--neu-visible-height'], '700px');
  viewport.height = 340;
  listeners.resize();
  assert.equal(ui.root.style['--neu-visible-height'], '340px');
  assert.equal(ui.root.style['--neu-keyboard-bottom'], '360px');
  viewport.offsetTop = 30;
  listeners.scroll();
  assert.equal(ui.root.style['--neu-keyboard-bottom'], '330px');
  viewport.height = 700;
  listeners.resize();
  assert.equal(ui.root.style['--neu-keyboard-bottom'], '0px');
});

test('greeting has no rating; a successful reply has two accessible rating controls', async () => {
  const ui = setup();
  await ui.root.querySelector('.neu-launcher').click();
  assert.equal(ui.root.querySelectorAll('.neu-feedback__button').length, 0);
  const reply = await ui.send();
  assert.equal(reply.querySelectorAll('.neu-feedback__button').length, 2);
  assert.equal(reply.querySelector('.neu-source'), null);
  await reply.querySelector('.neu-feedback__button').click();
  assert.equal(ui.root.events[0].detail.sources[0], 'guide.pdf');
  assert.equal(reply.querySelector('.neu-feedback').getAttribute('aria-label'), 'Rate this answer');
  assert.equal(reply.querySelector('.neu-support'), null);
});

test('rating changes keep the same response ID and expose support for a downvote', async () => {
  const ui = setup(); const reply = await ui.send();
  const [up, down] = reply.querySelectorAll('.neu-feedback__button');
  await up.click(); await down.click(); await down.click();
  assert.equal(ui.root.events.length, 2);
  assert.equal(ui.root.events[0].detail.responseId, ui.root.events[1].detail.responseId);
  assert.equal(ui.root.events[1].type, 'neu:feedback');
  assert.equal(ui.root.events[1].detail.query, 'How do I enroll?');
  assert.equal(ui.root.events[1].detail.rating, 'down');
  assert.equal(up.getAttribute('aria-pressed'), 'false');
  assert.equal(down.getAttribute('aria-pressed'), 'true');
  assert.equal(reply.querySelector('.neu-support').href, 'https://neu.edu.ph/main/contact-us');
  assert.equal(reply.querySelector('.neu-support').rel, 'noopener noreferrer');
  assert.equal(ui.calls.filter(call => call.url.endsWith('/feedback')).length, 2, 'each changed rating is submitted once');
  await up.click(); assert.equal(reply.querySelector('.neu-support'), null);
});

test('explicit backend support flag and legacy fallback text both offer support', async () => {
  for (const data of [
    { answer: 'Ask a staff member.', needsSupport: true },
    { answer: 'Not certain.', confidence: 'low' },
    { answer: "I don't have that information in the NEU documents yet." },
    { answer: "I don't have any documents indexed yet, so I can't answer that." },
  ]) {
    const ui = setup(data); const reply = await ui.send();
    assert.ok(reply.querySelector('.neu-support'));
    await reply.querySelector('.neu-feedback__button').click();
    assert.ok(reply.querySelector('.neu-support'), 'helpful rating must not hide fallback support');
  }
});

test('network and server failures offer support without rating controls', async () => {
  for (const options of [{ fail: true }, { status: 500 }]) {
    const ui = setup({ error: 'Private backend detail' }, options); const reply = await ui.send();
    assert.ok(reply.querySelector('.neu-support'));
    assert.equal(reply.querySelectorAll('.neu-feedback__button').length, 0);
    assert.equal(ui.root.querySelector('.neu-send').disabled, false);
    assert.ok(!reply.querySelector('.neu-bubble').textContent.includes('Private backend detail'));
  }
});

test('unsafe support URLs are rejected', async () => {
  const ui = setup({ answer: 'Unknown', needsSupport: true }, { config: { supportUrl: 'javascript:alert(1)' } });
  const reply = await ui.send(); assert.equal(reply.querySelector('.neu-support'), null);
});

test('untrusted answer markup stays escaped while feedback associates the right query', async () => {
  const ui = setup({ answer: '<img src=x onerror="alert(1)"> **answer**' });
  const reply = await ui.send('First question');
  assert.ok(reply.querySelector('.neu-bubble').innerHTML.includes('&lt;img'));
  assert.ok(!reply.querySelector('.neu-bubble').innerHTML.includes('<img'));
  await reply.querySelector('.neu-feedback__button').click();
  assert.equal(ui.root.events[0].detail.query, 'First question');
});

test('conversation history stays bounded and excludes blocked replies', async () => {
  const ui = setup({ answer: 'A'.repeat(1500) });
  for (let i = 0; i < 5; i++) await ui.send(`Question ${i}`);
  const payload = JSON.parse(ui.calls[4].init.body);
  assert.equal(payload.history.length, 6);
  assert.equal(payload.history[0].content, 'Question 1');
  assert.equal(payload.history[1].content.length, 1000);
  assert.equal(payload.history[0].role, 'user');
  assert.equal(payload.history[1].role, 'assistant');
  const blocked = setup({ answer: 'Blocked answer', blocked: true });
  await blocked.send('First'); await blocked.send('Second');
  assert.equal(JSON.parse(blocked.calls[1].init.body).history.length, 0);
});

test('copy writes the answer and reports success without submitting feedback', async () => {
  let copied;
  const ui = setup({ answer: 'Copy this answer' }, {
    navigator: { clipboard: { writeText: async (text) => { copied = text; } } },
  });
  const reply = await ui.send();
  const button = reply.querySelector('.neu-feedback__copy');
  assert.equal(button.getAttribute('aria-label'), 'Copy answer');
  await button.click();
  assert.equal(copied, 'Copy this answer');
  assert.equal(reply.querySelector('.neu-feedback__status').textContent, 'Answer copied');
  assert.equal(button.disabled, false);
  assert.equal(ui.root.events.length, 0);
});

test('unavailable clipboard reports failure and restores the copy button', async () => {
  const ui = setup(); const reply = await ui.send();
  const button = reply.querySelector('.neu-feedback__copy');
  await button.click();
  assert.match(reply.querySelector('.neu-feedback__status').textContent, /Unable to copy/);
  assert.equal(button.disabled, false);
});

test('read aloud toggles playback and stops when the chat closes', async () => {
  let utterance; let cancellations = 0;
  const ui = setup({ answer: 'Hello' }, { window: {
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
    speechSynthesis: { speak: (value) => { utterance = value; }, cancel: () => { cancellations++; } },
  } });
  await ui.root.querySelector('.neu-launcher').click();
  const reply = await ui.send(); const button = reply.querySelector('.neu-feedback__read');
  await button.click(); assert.equal(utterance.text, 'Hello');
  assert.equal(button.getAttribute('aria-pressed'), 'true');
  await button.click(); assert.equal(cancellations, 1);
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  await button.click(); await ui.root.querySelector('.neu-panel__close').click();
  assert.equal(cancellations, 2);
  assert.equal(button.getAttribute('aria-pressed'), 'false');
});

test('toolbar handles unavailable speech and can expand and restore chat', async () => {
  const ui = setup(); const reply = await ui.send();
  await reply.querySelector('.neu-feedback__read').click();
  assert.match(reply.querySelector('.neu-feedback__status').textContent, /unavailable/);
  const button = reply.querySelector('.neu-feedback__expand');
  await button.click(); assert.equal(ui.root.classList.contains('neu-widget--expanded'), true);
  assert.equal(button.getAttribute('aria-label'), 'Restore chat size');
  await button.click(); assert.equal(ui.root.classList.contains('neu-widget--expanded'), false);
});

test('mascot stays anchored after pointer movement; keyboard click still opens', async () => {
  const ui = setup(); const launcher = ui.root.querySelector('.neu-launcher');
  await launcher.emit('pointerdown', { button: 0, isPrimary: true, pointerId: 1, clientX: 940, clientY: 700 });
  await launcher.emit('pointermove', { pointerId: 1, clientX: -2000, clientY: -2000 });
  assert.equal(ui.root.style['--neu-mascot-right'], undefined);
  assert.equal(ui.root.style['--neu-mascot-bottom'], undefined);
  await launcher.emit('pointerup', { pointerId: 1 });
  assert.equal(ui.root.classList.contains('neu-widget--open'), false);
  await launcher.emit('click', { detail: 0 });
  assert.equal(ui.root.classList.contains('neu-widget--open'), true);
});

test('mascot pointer click opens chat', async () => {
  const ui = setup(); const launcher = ui.root.querySelector('.neu-launcher');
  await launcher.emit('pointerdown', { button: 0, isPrimary: true, pointerId: 1, clientX: 940, clientY: 700 });
  await launcher.emit('pointermove', { pointerId: 1, clientX: 942, clientY: 701 });
  await launcher.emit('pointerup', { pointerId: 1 });
  await launcher.emit('click', { detail: 1 });
  assert.equal(ui.root.classList.contains('neu-widget--open'), true);
  assert.equal(ui.root.classList.contains('neu-widget--dragging'), false);
});


test('mascot reacts to answers and feedback then returns to idle without stale timers', async () => {
  const ui = setup();
  const reply = await ui.send();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'answer');
  const [up, down] = reply.querySelectorAll('.neu-feedback__button');
  await down.click();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'frown');
  await up.click();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'celebrate');
  ui.finishReactions();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'idle');
});

test('hover greeting is bounded and chat open/close replace the reaction', async () => {
  const ui = setup(); const launcher = ui.root.querySelector('.neu-launcher');
  await launcher.emit('pointerenter', { pointerType: 'mouse' });
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'greet');
  ui.finishReactions();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'idle');
  await launcher.click();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'hello');
  await ui.root.querySelector('.neu-panel__close').click();
  assert.equal(ui.root.getAttribute('data-neu-reaction'), 'goodbye');
});


test('feedback failure restores selection and support state and permits retry', async () => {
  const ui = setup(undefined, { feedbackFail: true });
  const reply = await ui.send();
  const down = reply.querySelectorAll('.neu-feedback__button')[1];
  await down.click();
  assert.equal(down.getAttribute('aria-pressed'), 'false');
  assert.equal(down.disabled, false);
  assert.equal(reply.querySelector('.neu-support'), null);
  await down.click();
  const calls = ui.calls.filter(call => call.url.endsWith('/feedback'));
  assert.equal(calls.length, 2);
  const first = JSON.parse(calls[0].init.body);
  const second = JSON.parse(calls[1].init.body);
  assert.equal(first.sessionId, second.sessionId);
  assert.equal(first.responseId, second.responseId);
  assert.equal(first.rating, 'down');
  assert.equal(calls[0].init.credentials, 'omit');
});
