# Neubie widget demo

Run from the repository root:

```powershell
python widget/serve_demo.py
```

Open `http://127.0.0.1:8000/demo.html?mock=1` for UI testing without AWS calls.
Remove `?mock=1` to call the existing `/query` API. The allowlisted demo server
serves the widget assets and public files in `front-end`; it does not serve `.env` or repository secrets.

## Testing on a phone

Connect your PC and phone to the same private Wi-Fi. Start the allowlisted server
with `python widget/serve_demo.py --host 0.0.0.0 --port 8002`, then use `ipconfig`
to find the PC's Wi-Fi IPv4 address. On the phone, open
`http://YOUR-PC-IP:8002/front-end/main/index.htm?mock=1` for sample replies;
remove `?mock=1` for AWS answers. Do not use `127.0.0.1` on the phone: that refers
to the phone itself. Stop the server with Ctrl+C when finished. Clipboard APIs
can be unavailable over plain LAN HTTP; deployed HTTPS should be tested too.

Check portrait and landscape, keyboard visibility, scrolling long answers,
feedback buttons, close/reopen, and navigation between local pages.

## HITL controls

- Each successful API reply has an outline-icon toolbar with copy, read aloud, helpful/unhelpful, and expand controls. Copy uses the browser clipboard and reports failures when clipboard access is unavailable. The greeting, typing
  indicator, and error messages cannot be rated.
- Read aloud uses browser speech synthesis and stops when the chat closes. Expand toggles a larger chat panel that stays within the viewport. Citation chips remain hidden.
- Users may change a rating; the selected state is accessible through
  `aria-pressed`. Ratings are held in memory for this session, capped at 100.
- The bubbling `neu:feedback` event includes `responseId`, `query`, `answer`,
  `sources`, `rating` (`up`/`down`), and `createdAt`. The demo console counts these
  events. Live mode submits ratings to `POST {apiBase}/feedback` with an in-memory
  session ID. Save failures restore the previous selection and allow retry. Mock
  mode intercepts both query and feedback requests without contacting AWS.
- Support appears for backend `needsSupport: true`, `confidence: 'low'`, or
  `status: 'fallback'`, and recognized fallback phrases from the older backend.
  This text recognition is not a calculated model confidence score.
- Support also appears on failed API requests and when a user marks a reply
  unhelpful. It opens NEU's official contact directory, rather than creating a
  ticket or claiming a staff member has been notified.

Override the support destination before loading the script:

```html
<script>
  window.NeuWidgetConfig = {
    supportUrl: 'https://neu.edu.ph/main/contact-us'
  };
</script>
```

Use an HTTPS page or `mailto:` URL. The default is the
[NEU contact directory](https://neu.edu.ph/main/contact-us).

## The emailed .env

This static widget does not load `.env`. Do not put it in `widget/`, upload it with
frontend assets, or paste secrets into `NeuWidgetConfig`. The browser only needs
the public API base URL. AWS credentials belong in private backend tooling or a
properly configured AWS profile. The repository ignores `.env`, but git-ignore
rules do not prevent a web server from exposing files.

Ask the sender which backend command reads the supplied `.env`; the current
widget demo requires none. Do not commit the file or share its secret values.

## Mock university website

The homepage at `front-end/main/index.htm` loads the shared `widget/neu-widget.css`
and `widget/neu-widget.js`. Its public configuration is in
`front-end/main/assets/scripts/neu-widget-config.js`.

With the server running, open:
- `http://127.0.0.1:8000/front-end/main/index.htm?mock=1` for sample replies.
- `http://127.0.0.1:8000/front-end/main/index.htm` for the existing AWS `/query` API.

For VS Code Live Server, open the repository root as the workspace so both
`front-end/` and `widget/` are available. Add `?mock=1` to the homepage URL for
mock replies, or `?api=https://YOUR-API-BASE` to override the public API base.

## Interactive Neubie mascot

The launcher uses the supplied Ask Neu logo face as a transparent PNG, with a
matching SVG body, hands, and legs. It stays fixed in the bottom-right corner,
breathes and blinks at idle, and gives one small jump and wave per hover entry.
Opening chat and receiving answers trigger a happy nod. Helpful feedback gets a
brief laughing bounce; unhelpful feedback gets a brief frown. Closing chat triggers
a goodbye wave. Each reaction settles back to idle; expressions do not cycle.
While waiting, the head tilts and the chest light pulses.
Click (or Enter/Space when focused) to open chat above the mascot. Dragging is disabled.
Reduced-motion preferences disable character animations. Deploy
`assets/neubie-logo-head.png` alongside `neu-widget.js` and `neu-widget.css`;
the script resolves the image relative to its own URL. No pet runtime is needed.
