/* Neubie UI: the demo website only renders chat and calls the standalone API. */
(() => {
  const history = [];
  let busy = false;
  const input = document.getElementById('neubie-input');
  const sendButton = document.getElementById('neubie-send-btn');
  if (!input || !sendButton) return;
  input.maxLength = 2000;

  window.neubieToggle = (force) => {
    const panel = document.getElementById('neubie-window');
    const open = force !== undefined ? force : !panel.classList.contains('neubie-open');
    panel.classList.toggle('neubie-open', open);
    if (open) input.focus();
  };

  function append(role, text) {
    const body = document.getElementById('neubie-body');
    const bubble = document.createElement('div');
    bubble.className = `neubie-msg neubie-msg-${role}`;
    bubble.textContent = text;
    body.appendChild(bubble);
    body.scrollTop = body.scrollHeight;
    return bubble;
  }

  window.neubieSend = async () => {
    const message = input.value.trim();
    if (busy || !message) return;
    const config = window.NEUBIE_CONFIG || {};
    if (!config.apiEndpoint) {
      append('bot', 'Neubie is waiting for its AWS connection. Set the API endpoint in chatbot-config.js.');
      return;
    }
    append('user', message);
    input.value = '';
    busy = true;
    sendButton.disabled = true;
    input.disabled = true;
    const reply = append('bot', 'Typing…');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.requestTimeoutMs || 32000);
    try {
      const response = await fetch(config.apiEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, history }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const data = await response.json();
      if (typeof data.answer !== 'string' || !data.answer.trim()) throw new Error('API returned no answer');
      reply.textContent = data.answer;
      // Keep complete conversation pairs within the API's size and entry limits.
      history.push({ role: 'user', content: message }, { role: 'assistant', content: data.answer.slice(0, 2000) });
      history.splice(0, Math.max(0, history.length - 20));
    } catch (error) {
      console.error('Neubie failed:', error);
      reply.textContent = error.name === 'AbortError'
        ? 'The response took too long. Please try again.'
        : "Sorry, I couldn't reach the assistant right now. Please try again later.";
    } finally {
      clearTimeout(timer);
      busy = false;
      sendButton.disabled = false;
      input.disabled = false;
      input.focus();
    }
  };

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      window.neubieSend();
    }
  });
})();
