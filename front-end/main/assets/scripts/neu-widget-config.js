/** Public widget configuration for the mock university website. */
(function () {
  'use strict';
  const params = new URLSearchParams(location.search);
  const mock = params.get('mock') === '1';
  const api = params.get('api');
  window.NeuWidgetConfig = Object.assign({}, window.NeuWidgetConfig || {},
    api ? { apiBase: api } : {});

  // Mock replies are enabled only when explicitly requested in the URL.
      if (mock) {
        const realFetch = window.fetch.bind(window);
        const reply = (status, body) => new Promise((resolve) => setTimeout(() => resolve(
          new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
        ), 900));

        window.fetch = (url, options) => {
          if (!String(url).endsWith('/query')) return realFetch(url, options);
          const q = JSON.parse(options.body).query.toLowerCase();
          if (q.includes('error')) return reply(500, { error: 'INTERNAL DETAIL THAT MUST NOT APPEAR', requestId: 'demo' });
          if (q.includes('limit')) return reply(429, { error: 'ignored' });
          if (q.includes('unknown')) return reply(200, {
            answer: "I don't have that information in the NEU documents yet. Please contact the relevant NEU office.",
            sources: [], needsSupport: true,
          });
          if (q.includes('xss')) return reply(200, {
            answer: '<img src=x onerror="alert(1)"> and **bold** survive as plain text.',
            sources: [{ filename: '<b>evil</b>.pdf' }],
          });
          return reply(200, {
            answer: 'This is a **mock answer**. Steps:\n\n- Prepare your documents\n- Submit the form\n- Wait for confirmation',
            sources: [{ filename: 'enrollment-guide.pdf' }, { filename: 'enrollment-guide.pdf' }, { filename: 'programs.docx' }],
          });
        };
      }

})();
