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
    // API Gateway invoke URL, no trailing slash. The widget POSTs to `${apiBase}/query`.
    apiBase: 'https://amccp1clpb.execute-api.us-east-1.amazonaws.com',
    botName: 'Neu',
    subtitle: 'New Era University assistant',
    greeting:
      "Hi! I'm Neu, New Era University's AI assistant. Ask me about programs, enrollment, or anything else about NEU.",
    placeholder: 'Message Neubie...',
    hintRotateMs: 10000,
    hintMessages: [
      'Ask Neu!',
      "Hi, I'm Neubie. How can I help you?",
      'Curious about NEU? Feel free to ask me!',
      "Got a question about enrollment or programs? I've got you!",
    ],
    networkErrorMessage: "Couldn't reach Neu right now. Check your connection and try again.",

    // Limits. maxQueryChars must not exceed MAX_QUERY_CHARS in query_lambda.py.
    maxQueryChars: 500,
    requestTimeoutMs: 30000,
    minSendIntervalMs: 1500,
    maxMessagesPerMinute: 10,
  };

  const config = Object.freeze(Object.assign({}, DEFAULT_CONFIG, window.NeuWidgetConfig || {}));

  const PANEL_ID = 'neu-panel';
  const INPUT_MAX_HEIGHT_PX = 90;
  const MAX_ANSWER_CHARS = 4000;
  const MAX_SOURCES = 10;
  const MAX_SOURCE_NAME_CHARS = 80;
  const MAX_SERVER_ERROR_CHARS = 200;
  const MINUTE_MS = 60 * 1000;

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

  const ROBOT_SVG = `
    <svg viewBox="0 0 137 117" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="70" cy="12" r="6" fill="var(--neu-robot-body)" />
      <rect x="68" y="16" width="4" height="10" rx="2" fill="var(--neu-robot-body)" />
      <rect x="20" y="24" width="100" height="72" rx="36" fill="var(--neu-robot-body)" />
      <rect x="12" y="44" width="9" height="26" rx="4" fill="var(--neu-robot-body)" />
      <rect x="118" y="44" width="9" height="26" rx="4" fill="var(--neu-robot-body)" />
      <rect x="25" y="29" width="90" height="63" rx="28" fill="var(--neu-robot-face)" />
      <ellipse cx="45" cy="58" rx="8" ry="11" fill="var(--neu-robot-body)" />
      <ellipse cx="95" cy="58" rx="8" ry="11" fill="var(--neu-robot-body)" />
      <path d="M 63 74 Q 70 78 77 74" stroke="var(--neu-robot-body)" stroke-width="2" stroke-linecap="round" fill="none" />
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
              aria-expanded="false" aria-controls="${PANEL_ID}">
        ${ROBOT_SVG}
      </button>

      <div class="neu-hint" aria-hidden="true">
        <span class="neu-hint__text"></span>
      </div>

      <section class="neu-panel" id="${PANEL_ID}" role="dialog"
               aria-label="Chat with ${escapeHtml(config.botName)}">
        <header class="neu-panel__header">
          <div class="neu-panel__avatar">${ROBOT_SVG}</div>
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

    const state = {
      isOpen: false,
      isSending: false,
      hintIndex: 0,
      sendTimestamps: [], // ms timestamps of recent sends, for the client-side limiter
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

    function setOpen(isOpen) {
      state.isOpen = isOpen;
      root.classList.toggle('neu-widget--open', isOpen);
      launcher.setAttribute('aria-expanded', String(isOpen));

      if (isOpen) {
        inputEl.focus();
        if (messagesEl.children.length === 0) addBotMessage(config.greeting);
      } else {
        launcher.focus();
      }
    }

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

    function addBotMessage(text, sources) {
      const message = createMessage('bot');
      const bubble = createBubble();
      bubble.innerHTML = renderMarkdown(text); // renderMarkdown escapes everything first
      message.appendChild(bubble);

      const names = extractSourceNames(sources);
      if (names.length) {
        const sourcesEl = document.createElement('div');
        sourcesEl.className = 'neu-sources';
        for (const name of names) {
          const chip = document.createElement('span');
          chip.className = 'neu-source';
          chip.textContent = name;
          chip.title = name;
          sourcesEl.appendChild(chip);
        }
        message.appendChild(sourcesEl);
      }

      messagesEl.appendChild(message);
      scrollToBottom();
    }

    function addErrorMessage(text) {
      const message = createMessage('bot');
      message.classList.add('neu-msg--error');
      const bubble = createBubble();
      bubble.textContent = text;
      message.appendChild(bubble);
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
      sendButton.disabled = true;
      showTyping();

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);

      try {
        const response = await fetch(`${apiBase}/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: text }),
          signal: controller.signal,
          mode: 'cors',
          credentials: 'omit', // never send the host site's cookies to the API
          cache: 'no-store',
          referrerPolicy: 'strict-origin-when-cross-origin',
        });
        const data = await readJson(response);
        hideTyping();

        if (!response.ok) {
          addErrorMessage(describeHttpError(response.status, data));
        } else if (!data || typeof data.answer !== 'string' || data.answer.trim() === '') {
          addErrorMessage('Neu sent back something unexpected. Please try again.');
        } else {
          addBotMessage(data.answer.slice(0, MAX_ANSWER_CHARS), data.sources);
        }
      } catch (error) {
        hideTyping();
        addErrorMessage(
          error && error.name === 'AbortError'
            ? 'Neu took too long to respond. Please try again.'
            : config.networkErrorMessage
        );
      } finally {
        clearTimeout(timeoutId);
        state.isSending = false;
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
