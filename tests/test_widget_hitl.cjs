const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = []; this.listeners = {}; this.attributes = {}; this.style = {};
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
  focus() {}
  remove() { this.parent.children = this.parent.children.filter((child) => child !== this); }
}

function setup(data = { answer: 'Admissions answer', sources: [{ filename: 'guide.pdf' }] }, options = {}) {
  const body = new Element();
  const context = {
    window: { ...options.window, NeuWidgetConfig: { hintMessages: ['Ask Neubie'], minSendIntervalMs: 0, ...options.config } },
    document: { body, readyState: 'complete', baseURI: 'http://localhost:8000/demo.html', createElement: () => new Element() },
    navigator: options.navigator || {},
    console: { error() {} }, URL, AbortController, setTimeout: () => 1, clearTimeout() {}, setInterval() {},
    CustomEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init); } },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.fail) throw new Error('Network failure');
      return { ok: options.status ? options.status < 400 : true, status: options.status || 200, json: async () => data };
    },
  };
  const calls = [];
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../widget/neu-widget.js'), 'utf8'), context);
  const root = body.children[0]; root.events = [];
  return { root, calls, async send(query = 'How do I enroll?') {
    root.querySelector('.neu-input').value = query;
    await root.querySelector('.neu-send').click();
    return root.querySelector('.neu-messages').children.at(-1);
  } };
}

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
  assert.equal(ui.calls.length, 1, 'rating must not pretend to submit to an AWS endpoint');
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
