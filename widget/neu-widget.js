/**
 * Ask Neu — embeddable chat widget
 *
 * Usage (on any page):
 *   <link rel="stylesheet" href="/assets/neu-widget.css">
 *   <script src="/assets/neu-widget.js" defer></script>
 *
 * Optional overrides — define BEFORE this script loads:
 *   <script>
 *     window.NeuWidgetConfig = { apiBase: 'https://your-api.example.com' };
 *   </script>
 *
 * Security notes (see also query_lambda.py, which enforces the same limits
 * server-side — client checks are for UX, the server is the real gate):
 *   - Only https:// API endpoints are accepted (http:// only for localhost).
 *   - No cookies/credentials are sent, nothing is stored in the browser.
 *   - Ratings (query, answer, source names, thumbs up/down) are sent to
 *     POST {apiBase}/feedback and stored server-side.
 *   - All server text is rendered via textContent or escaped before markup.
 *   - Responses are shape-checked and size-capped before display.
 */
(function () {
  'use strict';

  // Guard against the script being included twice on one page.
  if (window.__neuWidgetLoaded) return;
  window.__neuWidgetLoaded = true;

  /* ------------------------------------------------------------------ *
   * Config
   * ------------------------------------------------------------------ */

  const DEFAULT_CONFIG = {
    apiBase: 'https://amccp1clpb.execute-api.us-east-1.amazonaws.com',
    botName: 'Neu',
    subtitle: 'New Era University assistant',
    greeting:
      "Hi! I'm Neubie, but most call me Neu! Ask me about programs, enrollment, or anything else about NEU.",
    placeholder: 'Message Neubie...',
    hintRotateMs: 10000,
    hintMessages: [
      'Ask Neu!',
      "Hi, I'm Neubie. How can I help you?",
      'Curious about NEU? Feel free to ask me!',
      "Got a question about enrollment or programs? I've got you!",
    ],
    networkErrorMessage: "Couldn't reach Neu right now. Check your connection and try again.",
    supportUrl: 'https://neu.edu.ph/main/contact-us',

    // Limits. maxQueryChars must not exceed MAX_QUERY_CHARS in query_lambda.py.
    maxQueryChars: 500,
    requestTimeoutMs: 30000,
    minSendIntervalMs: 1500,
    maxMessagesPerMinute: 10,
  };

  const config = Object.freeze(Object.assign({}, DEFAULT_CONFIG, window.NeuWidgetConfig || {}));

  const PANEL_ID = 'neu-panel';
  const INPUT_MAX_HEIGHT_PX = 100;
  const MAX_ANSWER_CHARS = 4000;
  const MAX_SOURCES = 10;
  const MAX_SOURCE_NAME_CHARS = 80;
  const MAX_SERVER_ERROR_CHARS = 200;
  const MINUTE_MS = 60 * 1000;

  // Conversation history sent with each query. Keep these within the
  // server-side MAX_HISTORY_MESSAGES / MAX_HISTORY_CHARS in the query Lambda.
  const MAX_HISTORY_MESSAGES = 6;
  const MAX_HISTORY_CHARS = 1000;

  // Control characters except tab (\x09) and newline (\x0A).
  const CONTROL_CHARS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;

  /**
   * Accepts https:// endpoints (and http:// for localhost development only).
   * Returns a normalized base URL with no trailing slash, or null if unsafe.
   */
  function resolveApiBase(value) {
    let url;
    try {
      url = new URL(String(value));
    } catch (error) {
      return null;
    }
    const isLocalhost = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
    const isSecure = url.protocol === 'https:' || (isLocalhost && url.protocol === 'http:');
    if (!isSecure || url.username || url.password) return null;
    return url.origin + url.pathname.replace(/\/+$/, '');
  }

  const apiBase = resolveApiBase(config.apiBase);
  if (!apiBase) {
    console.error('[Ask Neu] Widget disabled: apiBase must be an https:// URL.');
    return;
  }

  /* ------------------------------------------------------------------ *
   * Markup
   * ------------------------------------------------------------------ */

  // Resolve assets beside this script so the widget works on other host pages.
  const mascotHeadUrl = new URL('assets/neubie-logo-head.png', document.currentScript?.src || document.baseURI).href;
  const ROBOT_SVG = `
    <svg class="neu-mascot" viewBox="0 0 140 184" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="neu-mascot-metal" x1="40" y1="100" x2="100" y2="160" gradientUnits="userSpaceOnUse">
          <stop stop-color="#f4f8ff"/><stop offset="0.5" stop-color="#c5d4ec"/><stop offset="1" stop-color="#8da4c8"/>
        </linearGradient>
        <radialGradient id="neu-mascot-screen" cx="40%" cy="15%" r="90%">
          <stop stop-color="#243a66"/><stop offset="0.6" stop-color="#101f42"/><stop offset="1" stop-color="#09142d"/>
        </radialGradient>
      </defs>
      <g class="neu-mascot__leg neu-mascot__leg--left">
        <rect x="47" y="145" width="17" height="26" rx="8" fill="#162b50" stroke="#b8cbe7" stroke-width="3"/>
        <path d="M44 166h23v11H39v-4q0-7 5-7Z" fill="#e3edfc" stroke="#89a7d4" stroke-width="2"/>
      </g>
      <g class="neu-mascot__leg neu-mascot__leg--right">
        <rect x="76" y="145" width="17" height="26" rx="8" fill="#162b50" stroke="#b8cbe7" stroke-width="3"/>
        <path d="M73 166h23q5 0 5 7v4H73v-11Z" fill="#e3edfc" stroke="#89a7d4" stroke-width="2"/>
      </g>
      <g class="neu-mascot__arm neu-mascot__arm--left">
        <path d="M38 109 24 130" stroke="#90a9cf" stroke-width="14" stroke-linecap="round"/>
        <path d="M38 109 24 130" stroke="#e3edfc" stroke-width="8" stroke-linecap="round"/>
        <circle cx="21" cy="137" r="10" fill="#e3edfc" stroke="#8da7ce" stroke-width="2"/>
        <path d="M17 136v4m5-4v5" stroke="#9bb4da" stroke-width="2" stroke-linecap="round"/>
      </g>
      <g class="neu-mascot__arm neu-mascot__arm--right">
        <path d="m102 109 14 21" stroke="#90a9cf" stroke-width="14" stroke-linecap="round"/>
        <path d="m102 109 14 21" stroke="#e3edfc" stroke-width="8" stroke-linecap="round"/>
        <circle cx="119" cy="137" r="10" fill="#e3edfc" stroke="#8da7ce" stroke-width="2"/>
        <path d="M115 136v4m5-4v5" stroke="#9bb4da" stroke-width="2" stroke-linecap="round"/>
      </g>
      <rect x="58" y="86" width="24" height="19" rx="7" fill="#172d51" stroke="#92afd7" stroke-width="2"/>
      <rect x="36" y="99" width="68" height="56" rx="22" fill="url(#neu-mascot-metal)" stroke="#dce9fc" stroke-width="2"/>
      <rect x="45" y="108" width="50" height="34" rx="13" fill="#142746" stroke="#7197cd" stroke-width="1.5"/>
      <path d="M62 132v-15l16 15v-15" stroke="#80b8ff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
      <circle class="neu-mascot__light" cx="70" cy="148" r="3" fill="#70d4ff"/>
      <g class="neu-mascot__head">
        <image href="${escapeHtml(mascotHeadUrl)}" x="9" y="0" width="122" height="101" preserveAspectRatio="xMidYMid meet"/>
        <g class="neu-mascot__emotions">
          <path d="M70 35C42 35 33 43 33 61C33 82 37 88 70 88C101 88 107 82 107 61C107 43 98 35 70 35Z" fill="url(#neu-mascot-screen)"/>
          <g class="neu-mascot__expression neu-mascot__expression--neutral">
            <g class="neu-mascot__eyes"><rect x="43" y="51" width="10" height="18" rx="5" fill="#d5f8ff"/><rect x="85" y="51" width="10" height="18" rx="5" fill="#d5f8ff"/></g>
            <path d="M62 74q8 8 16 0"/>
          </g>
          <g class="neu-mascot__expression neu-mascot__expression--frown">
            <path d="m43 52 11-4m30 0 11 4" stroke-width="2.5"/>
            <rect x="45" y="57" width="8" height="12" rx="4" fill="#d5f8ff" stroke="none"/><rect x="85" y="57" width="8" height="12" rx="4" fill="#d5f8ff" stroke="none"/>
            <path d="M62 79q8-8 16 0"/>
          </g>
          <g class="neu-mascot__expression neu-mascot__expression--wink">
            <rect x="43" y="51" width="10" height="18" rx="5" fill="#d5f8ff"/>
            <path d="m84 61 5-4 6 4M62 73q8 9 17-1"/>
          </g>
          <g class="neu-mascot__expression neu-mascot__expression--excited">
            <path d="M43 59q5-12 11 0M84 59q5-12 11 0"/>
            <path d="M60 70h20q-1 14-10 14T60 70Z" fill="#d5f8ff" stroke-width="2"/>
            <path d="M40 68h5m50 0h5" stroke="#779dff" stroke-width="3"/>
          </g>
          <g class="neu-mascot__expression neu-mascot__expression--laughing">
            <path d="m43 55 10 5-10 5m51-10-10 5 10 5"/>
            <path d="M59 70h22q0 15-11 15T59 70Z" fill="#d5f8ff" stroke-width="2"/>
            <path d="M65 81q5-5 10 0" stroke="#779dff" stroke-width="3"/>
          </g>
        </g>
      </g>
    </svg>`;

  const CLOSE_ICON_SVG = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>`;

  const SEND_ICON_SVG = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </svg>`;

  function buildWidgetHtml() {
    return `
      <button class="neu-launcher" type="button"
              aria-label="Open chat with ${escapeHtml(config.botName)}"
              aria-expanded="false" aria-controls="${PANEL_ID}" title="Click to chat">
        ${ROBOT_SVG}
      </button>

      <div class="neu-hint" aria-hidden="true">
        <span class="neu-hint__text"></span>
      </div>

      <section class="neu-panel" id="${PANEL_ID}" role="dialog"
               aria-label="Chat with ${escapeHtml(config.botName)}">
        <header class="neu-panel__header">
          <div class="neu-panel__avatar"><img src="${escapeHtml(mascotHeadUrl)}" alt="" width="32" height="32"></div>
          <div class="neu-panel__title">
            <b class="neu-panel__name">Ask ${escapeHtml(config.botName)}</b>
            <div class="neu-panel__status"><i></i> ${escapeHtml(config.subtitle)}</div>
          </div>
          <button class="neu-panel__close" type="button" aria-label="Close chat">
            ${CLOSE_ICON_SVG}
          </button>
        </header>

        <div class="neu-messages" role="log" aria-live="polite"></div>

        <div class="neu-input-row">
          <textarea class="neu-input" rows="1"
                    maxlength="${Number(config.maxQueryChars) || 500}"
                    autocomplete="off"
                    placeholder="${escapeHtml(config.placeholder)}"
                    aria-label="Your message"></textarea>
          <button class="neu-send" type="button" aria-label="Send message">
            ${SEND_ICON_SVG}
          </button>
        </div>
      </section>`;
  }

  /* ------------------------------------------------------------------ *
   * Helpers
   * ------------------------------------------------------------------ */

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Minimal markdown: escapes HTML first, then re-introduces only
   * **bold** and "- " bullet lists. No links, images, or raw HTML are ever
   * produced, so model/server output cannot inject markup.
   */
  function renderMarkdown(text) {
    const escaped = escapeHtml(text);
    const withBold = escaped.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');

    let html = '';
    let inList = false;
    let paragraph = [];

    function flushParagraph() {
      if (paragraph.length) {
        html += `<p>${paragraph.join('<br>')}</p>`;
        paragraph = [];
      }
    }

    for (const line of withBold.split('\n')) {
      const trimmed = line.trim();

      if (trimmed.startsWith('- ')) {
        flushParagraph();
        if (!inList) {
          html += '<ul>';
          inList = true;
        }
        html += `<li>${trimmed.slice(2)}</li>`;
        continue;
      }

      if (inList) {
        html += '</ul>';
        inList = false;
      }

      if (trimmed === '') {
        flushParagraph();
      } else {
        paragraph.push(trimmed);
      }
    }

    if (inList) html += '</ul>';
    flushParagraph();

    return html || '<p></p>';
  }

  /** Random per-page-load ID that groups one visitor's ratings. Kept in memory only. */
  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function sanitizeUserInput(text) {
    return String(text).replace(CONTROL_CHARS, '').trim();
  }

  /** Unique, trimmed, length-capped filenames from an untrusted `sources` value. */
  function extractSourceNames(sources) {
    if (!Array.isArray(sources)) return [];
    const names = [];
    for (const source of sources) {
      const name =
        source && typeof source.filename === 'string'
          ? source.filename.replace(CONTROL_CHARS, '').trim().slice(0, MAX_SOURCE_NAME_CHARS)
          : '';
      if (name && !names.includes(name)) names.push(name);
      if (names.length >= MAX_SOURCES) break;
    }
    return names;
  }

  /** Picks a user-facing message for a failed HTTP response. */
  function describeHttpError(status, data) {
    if (status === 429) {
      return 'Neu is getting a lot of questions right now. Please try again in a moment.';
    }
    const serverMessage = data && typeof data.error === 'string' ? data.error : '';
    if (status >= 400 && status < 500 && serverMessage && serverMessage.length <= MAX_SERVER_ERROR_CHARS) {
      return serverMessage;
    }
    return `Something went wrong (${status}). Try again in a moment.`;
  }

  /* ------------------------------------------------------------------ *
   * Widget
   * ------------------------------------------------------------------ */

  function init() {
    const root = document.createElement('div');
    root.className = 'neu-widget';
    root.innerHTML = buildWidgetHtml();
    document.body.appendChild(root);

    const $ = (selector) => root.querySelector(selector);

    const launcher = $('.neu-launcher');
    const hintText = $('.neu-hint__text');
    const closeButton = $('.neu-panel__close');
    const messagesEl = $('.neu-messages');
    const inputEl = $('.neu-input');
    const sendButton = $('.neu-send');

    // Follow the visible screen when a mobile keyboard resizes or pans it.
    function syncViewport() {
      const viewport = window.visualViewport;
      const height = viewport ? viewport.height : window.innerHeight;
      const bottom = viewport ? Math.max(0, window.innerHeight - height - viewport.offsetTop) : 0;
      root.style.setProperty('--neu-visible-height', `${height}px`);
      root.style.setProperty('--neu-keyboard-bottom', `${bottom}px`);
    }
    syncViewport();
    window.addEventListener('resize', syncViewport);
    window.visualViewport?.addEventListener('resize', syncViewport);
    window.visualViewport?.addEventListener('scroll', syncViewport);

    const state = {
      isOpen: false,
      isSending: false,
      hintIndex: 0,
      sendTimestamps: [], // ms timestamps of recent sends, for the client-side limiter
      history: [], // completed turns sent to the server: [{ role, content }, ...]
      responseCount: 0,
      activeSpeech: null,
      feedback: new Map(), // session only; also emitted as a neu:feedback event
      sessionId: createSessionId(),
    };

    /* ---------- Hint rotation ---------- */

    hintText.textContent = config.hintMessages[0] || '';

    if (config.hintMessages.length > 1) {
      setInterval(() => {
        hintText.style.opacity = 0;
        setTimeout(() => {
          state.hintIndex = (state.hintIndex + 1) % config.hintMessages.length;
          hintText.textContent = config.hintMessages[state.hintIndex];
          hintText.style.opacity = 1;
        }, 400);
      }, config.hintRotateMs);
    }

    /* ---------- Open / close ---------- */

    let reactionTimer;
    function react(kind, duration = 1600) {
      clearTimeout(reactionTimer);
      root.setAttribute('data-neu-reaction', kind);
      if (duration) reactionTimer = setTimeout(() => root.setAttribute('data-neu-reaction', 'idle'), duration);
    }
    root.setAttribute('data-neu-reaction', 'idle');

    function setOpen(isOpen) {
      react(isOpen ? 'hello' : 'goodbye');
      state.isOpen = isOpen;
      root.classList.toggle('neu-widget--open', isOpen);
      launcher.setAttribute('aria-expanded', String(isOpen));

      if (isOpen) {
        inputEl.focus();
        if (messagesEl.children.length === 0) addBotMessage(config.greeting);
      } else {
        stopReading();
        launcher.focus();
      }
    }

    function greet() {
      if (!state.isOpen && root.getAttribute('data-neu-reaction') === 'idle' && !root.classList.contains('neu-widget--thinking')) react('greet', 1400);
    }
    launcher.addEventListener('pointerenter', (event) => { if (event.pointerType === 'mouse') greet(); });
    launcher.addEventListener('focus', greet);
    launcher.addEventListener('pointermove', (event) => {
      if (event.pointerType === 'mouse') {
        const bounds = launcher.getBoundingClientRect();
        launcher.style.setProperty('--neu-gaze-x', `${Math.max(-3, Math.min(3, (event.clientX - bounds.left - bounds.width / 2) / 12))}deg`);
      }
    });
    launcher.addEventListener('pointerleave', () => launcher.style.setProperty('--neu-gaze-x', '0deg'));
    launcher.addEventListener('click', () => setOpen(!state.isOpen));
    closeButton.addEventListener('click', () => setOpen(false));
    root.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && state.isOpen) setOpen(false);
    });

    /* ---------- Messages ---------- */

    function scrollToBottom() {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function createMessage(modifier) {
      const message = document.createElement('div');
      message.className = `neu-msg neu-msg--${modifier}`;
      return message;
    }

    function createBubble() {
      const bubble = document.createElement('div');
      bubble.className = 'neu-bubble';
      return bubble;
    }

    function addUserMessage(text) {
      const message = createMessage('user');
      const bubble = createBubble();
      bubble.textContent = text;
      message.appendChild(bubble);
      messagesEl.appendChild(message);
      scrollToBottom();
    }

    function addSupportLink(message) {
      if (message.querySelector('.neu-support')) return;
      let url;
      try {
        url = new URL(config.supportUrl, document.baseURI);
        if (url.protocol !== 'https:' && url.protocol !== 'mailto:') return;
        if (url.username || url.password) return;
      } catch (error) {
        return;
      }
      const link = document.createElement('a');
      link.className = 'neu-support';
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Contact university support â†—';
      message.appendChild(link);
    }

    function needsSupport(text, data) {
      // Prefer a backend flag; recognize existing fallback wording for older APIs.
      return Boolean(data && (data.needsSupport === true || data.confidence === 'low' || data.status === 'fallback')) ||
        /(?:don['’]t|do not) have (?:that|any|enough|this) information|don['’]t have any documents|(?:cannot|can['’]t|unable to) (?:answer|confirm|verify)|not enough information/i.test(text);
    }

    // Static outline icons; no server content is inserted into SVG markup.
    function actionIcon(paths) {
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`;
    }
    const COPY_ICON = actionIcon('<rect x="8" y="8" width="12" height="12" rx="3"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>');
    const UP_ICON = actionIcon('<path d="M7 10v10H4a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1h3Zm0 0 5-7a2 2 0 0 1 2 2l-1 5h5a3 3 0 0 1 3 3l-2 6a2 2 0 0 1-2 1H7"/>');
    const DOWN_ICON = actionIcon('<path d="M7 14V4H4a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h3Zm0 0 5 7a2 2 0 0 0 2-2l-1-5h5a3 3 0 0 0 3-3l-2-6a2 2 0 0 0-2-1H7"/>');

    const SPEAKER_ICON = actionIcon('<path d="m11 4-5 4H3v8h3l5 4V4Z"/><path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>');
    const EXPAND_ICON = actionIcon('<path d="M14 4h6v6m0-6-8 8M4 14v6h6"/>');

    function stopReading() {
      if (!state.activeSpeech) return;
      window.speechSynthesis.cancel();
      state.activeSpeech.button.setAttribute('aria-pressed', 'false');
      state.activeSpeech.button.setAttribute('aria-label', 'Read answer aloud');
      state.activeSpeech.button.title = 'Read answer aloud';
      state.activeSpeech = null;
    }

    /** Sends one rating to the backend. Resolves true on success, false on any failure. */
    async function submitFeedback(entry) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);
      try {
        const response = await fetch(`${apiBase}/feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sessionId: state.sessionId,
            responseId: entry.responseId,
            rating: entry.rating,
            query: entry.query,
            answer: entry.answer,
            sources: entry.sources,
          }),
          signal: controller.signal,
          mode: 'cors',
          credentials: 'omit',
          cache: 'no-store',
          referrerPolicy: 'strict-origin-when-cross-origin',
        });
        return response.ok;
      } catch (error) {
        return false;
      } finally {
        clearTimeout(timeoutId);
      }
    }

    function addFeedback(message, query, answer, names, requiresSupport) {
      const responseId = `${Date.now()}-${++state.responseCount}`;
      const controls = document.createElement('div');
      controls.className = 'neu-feedback';
      controls.setAttribute('role', 'group');
      controls.setAttribute('aria-label', 'Rate this answer');
      const status = document.createElement('span');
      status.className = 'neu-feedback__status';
      status.setAttribute('role', 'status');
      const copyButton = document.createElement('button');
      copyButton.type = 'button';
      copyButton.className = 'neu-feedback__copy';
      copyButton.innerHTML = COPY_ICON;
      copyButton.title = 'Copy answer';
      copyButton.setAttribute('aria-label', 'Copy answer');
      copyButton.addEventListener('click', async () => {
        copyButton.disabled = true;
        try {
          await navigator.clipboard.writeText(answer);
          status.textContent = 'Answer copied';
        } catch (error) {
          status.textContent = 'Unable to copy. Select the answer to copy it.';
        } finally {
          copyButton.disabled = false;
        }
      });
      controls.appendChild(copyButton);
      const readButton = document.createElement('button');
      readButton.type = 'button';
      readButton.className = 'neu-feedback__read';
      readButton.innerHTML = SPEAKER_ICON;
      readButton.title = 'Read answer aloud';
      readButton.setAttribute('aria-label', 'Read answer aloud');
      readButton.setAttribute('aria-pressed', 'false');
      readButton.addEventListener('click', () => {
        if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
          status.textContent = 'Read aloud is unavailable in this browser.';
          return;
        }
        const isReading = state.activeSpeech?.button === readButton;
        stopReading();
        if (isReading) return;
        const speech = new window.SpeechSynthesisUtterance(message.querySelector('.neu-bubble').innerText || answer);
        state.activeSpeech = { button: readButton, speech };
        readButton.setAttribute('aria-pressed', 'true');
        readButton.setAttribute('aria-label', 'Stop reading');
        readButton.title = 'Stop reading';
        const finish = () => {
          if (state.activeSpeech?.speech !== speech) return;
          readButton.setAttribute('aria-pressed', 'false');
          readButton.setAttribute('aria-label', 'Read answer aloud');
          readButton.title = 'Read answer aloud';
          state.activeSpeech = null;
        };
        speech.onend = finish;
        speech.onerror = () => { finish(); status.textContent = 'Unable to read this answer aloud.'; };
        window.speechSynthesis.speak(speech);
      });
      controls.appendChild(readButton);
      const buttons = [];
      for (const [rating, icon, label] of [
        ['up', UP_ICON, 'Helpful answer'], ['down', DOWN_ICON, 'Unhelpful answer'],
      ]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'neu-feedback__button';
        button.innerHTML = icon;
        button.title = label;
        button.setAttribute('aria-label', label);
        button.setAttribute('aria-pressed', 'false');
        button.addEventListener('click', async () => {
          if (button.disabled || state.feedback.get(responseId)?.rating === rating) return;
          const previous = state.feedback.get(responseId);
          const entry = { responseId, query, answer, sources: names.slice(), rating,
            createdAt: new Date().toISOString() };
          state.feedback.set(responseId, entry);
          if (state.feedback.size > 100) state.feedback.delete(state.feedback.keys().next().value);
          buttons.forEach((item) => item.button.setAttribute('aria-pressed', String(item.rating === rating)));
          react(rating === 'up' ? 'celebrate' : 'frown', rating === 'up' ? 1800 : 2800);
          if (rating === 'down') addSupportLink(message);
          else if (!requiresSupport) message.querySelector('.neu-support')?.remove();
          // Still emitted so a host page can listen if it wants to.
          root.dispatchEvent(new CustomEvent('neu:feedback', {
            bubbles: true, detail: { ...entry, sources: entry.sources.slice() },
          }));

          // Lock both buttons while saving so rapid up/down clicks can't arrive out of order.
          buttons.forEach((item) => { item.button.disabled = true; });
          status.textContent = 'Saving…';
          const saved = await submitFeedback(entry);
          buttons.forEach((item) => { item.button.disabled = false; });

          if (saved) {
            status.textContent = rating === 'up' ? 'Thanks! Marked helpful' : 'Thanks! Marked unhelpful';
          } else {
            // Roll back so the user can tap again instead of silently losing the rating.
            if (previous) state.feedback.set(responseId, previous);
            else state.feedback.delete(responseId);
            buttons.forEach((item) => item.button.setAttribute('aria-pressed', String(previous?.rating === item.rating)));
            if (previous?.rating === 'down' || requiresSupport) addSupportLink(message);
            else message.querySelector('.neu-support')?.remove();
            status.textContent = "Couldn't save your feedback. Please try again.";
          }
          scrollToBottom();
        });
        buttons.push({ button, rating });
        controls.appendChild(button);
      }
      const expandButton = document.createElement('button');
      expandButton.type = 'button';
      expandButton.className = 'neu-feedback__expand';
      expandButton.innerHTML = EXPAND_ICON;
      expandButton.title = 'Expand chat';
      expandButton.setAttribute('aria-label', 'Expand chat');
      expandButton.setAttribute('aria-pressed', String(root.classList.contains('neu-widget--expanded')));
      expandButton.addEventListener('click', () => {
        const expanded = !root.classList.contains('neu-widget--expanded');
        root.classList.toggle('neu-widget--expanded', expanded);
        root.querySelectorAll('.neu-feedback__expand').forEach((button) => {
          button.setAttribute('aria-pressed', String(expanded));
          button.setAttribute('aria-label', expanded ? 'Restore chat size' : 'Expand chat');
          button.title = expanded ? 'Restore chat size' : 'Expand chat';
        });
        scrollToBottom();
      });
      controls.appendChild(expandButton);
      controls.appendChild(status);
      message.appendChild(controls);
    }

    function addBotMessage(text, sources, options = {}) {
      const message = createMessage('bot');
      const bubble = createBubble();
      bubble.innerHTML = renderMarkdown(text); // renderMarkdown escapes everything first
      message.appendChild(bubble);

      const names = extractSourceNames(sources);
      if (options.query) {
        const requiresSupport = needsSupport(text, options.data);
        addFeedback(message, options.query, text, names, requiresSupport);
        if (requiresSupport) addSupportLink(message);
      }

      messagesEl.appendChild(message);
      scrollToBottom();
    }

    function addErrorMessage(text, offerSupport = false) {
      const message = createMessage('bot');
      message.classList.add('neu-msg--error');
      const bubble = createBubble();
      bubble.textContent = text;
      message.appendChild(bubble);
      if (offerSupport) addSupportLink(message);
      messagesEl.appendChild(message);
      scrollToBottom();
    }

    function showTyping() {
      const typing = document.createElement('div');
      typing.className = 'neu-typing';
      typing.innerHTML = '<span></span><span></span><span></span>';
      messagesEl.appendChild(typing);
      scrollToBottom();
    }

    function hideTyping() {
      const typing = $('.neu-typing');
      if (typing) typing.remove();
    }

    /* ---------- Input ---------- */

    function autoGrowInput() {
      inputEl.style.height = 'auto';
      inputEl.style.height = `${Math.min(inputEl.scrollHeight, INPUT_MAX_HEIGHT_PX)}px`;
    }

    /**
     * Client-side pacing (UX only; the server enforces the real limits).
     * Returns a message if the user should wait, or null if sending is OK.
     */
    function checkSendRate() {
      const now = Date.now();
      state.sendTimestamps = state.sendTimestamps.filter((t) => now - t < MINUTE_MS);
      const last = state.sendTimestamps[state.sendTimestamps.length - 1];

      if (last !== undefined && now - last < config.minSendIntervalMs) {
        return 'Please wait a moment before sending another message.';
      }
      if (state.sendTimestamps.length >= config.maxMessagesPerMinute) {
        return "You're sending messages too quickly. Please wait a minute and try again.";
      }
      return null;
    }

    /** Parses a JSON body, returning null (not throwing) if it isn't valid JSON. */
    async function readJson(response) {
      try {
        return await response.json();
      } catch (error) {
        return null;
      }
    }

    async function sendMessage() {
      if (state.isSending) return;

      const text = sanitizeUserInput(inputEl.value);
      if (!text) return;

      if (text.length > config.maxQueryChars) {
        addErrorMessage(`Please keep your message under ${config.maxQueryChars} characters.`);
        return;
      }

      const rateMessage = checkSendRate();
      if (rateMessage) {
        addErrorMessage(rateMessage);
        return;
      }
      state.sendTimestamps.push(Date.now());

      addUserMessage(text);
      inputEl.value = '';
      autoGrowInput();
      state.isSending = true;
      react('idle', 0);
      root.classList.add('neu-widget--thinking');
      sendButton.disabled = true;
      showTyping();

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);

      try {
        const response = await fetch(`${apiBase}/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: text, history: state.history }),
          signal: controller.signal,
          mode: 'cors',
          credentials: 'omit', // never send the host site's cookies to the API
          cache: 'no-store',
          referrerPolicy: 'strict-origin-when-cross-origin',
        });
        const data = await readJson(response);
        hideTyping();

        if (!response.ok) {
          addErrorMessage(describeHttpError(response.status, data), true);
        } else if (!data || typeof data.answer !== 'string' || data.answer.trim() === '') {
          addErrorMessage('Neu sent back something unexpected. Please try again.', true);
        } else {
          const answer = data.answer.slice(0, MAX_ANSWER_CHARS);
          addBotMessage(answer, data.sources, { query: text, data });
          if (!data.blocked) react('answer');

          // Save the turn as a user/assistant pair so history always starts
          // with a user turn and alternates. Blocked turns are left out so
          // they can't skew retrieval for the next question.
          if (!data.blocked) {
            state.history.push(
              { role: 'user', content: text },
              { role: 'assistant', content: answer.slice(0, MAX_HISTORY_CHARS) }
            );
            state.history = state.history.slice(-MAX_HISTORY_MESSAGES);
          }
        }
      } catch (error) {
        hideTyping();
        addErrorMessage(
          error && error.name === 'AbortError'
            ? 'Neu took too long to respond. Please try again.'
            : config.networkErrorMessage,
          true
        );
      } finally {
        clearTimeout(timeoutId);
        state.isSending = false;
        root.classList.toggle('neu-widget--thinking', false);
        sendButton.disabled = false;
        inputEl.focus();
      }
    }

    sendButton.addEventListener('click', sendMessage);
    inputEl.addEventListener('input', autoGrowInput);
    inputEl.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
