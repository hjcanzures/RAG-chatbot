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
      history: [], // completed turns sent to the server: [{ role, content }, ...]
      responseCount: 0,
      activeSpeech: null,
      feedback: new Map(), // session only; an integration can capture neu:feedback
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
        stopReading();
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
      link.textContent = 'Contact university support ↗';
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
        button.addEventListener('click', () => {
          if (state.feedback.get(responseId)?.rating === rating) return;
          const entry = { responseId, query, answer, sources: names.slice(), rating,
            createdAt: new Date().toISOString() };
          state.feedback.set(responseId, entry);
          if (state.feedback.size > 100) state.feedback.delete(state.feedback.keys().next().value);
          buttons.forEach((item) => item.button.setAttribute('aria-pressed', String(item.rating === rating)));
          status.textContent = rating === 'up' ? 'Marked helpful' : 'Marked unhelpful';
          if (rating === 'down') addSupportLink(message);
          else if (!requiresSupport) message.querySelector('.neu-support')?.remove();
          // Ratings are not sent to AWS by this widget; the host may wire this event
          // to a review endpoint. Never claim a server submission happened here.
          root.dispatchEvent(new CustomEvent('neu:feedback', {
            bubbles: true, detail: { ...entry, sources: entry.sources.slice() },
          }));
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