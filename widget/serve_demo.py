"""Serve only public demo assets; never expose .env or repository files."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import argparse

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "front-end"
ASSETS = {"/": "/demo.html", "/demo.html": "/demo.html",
          "/neu-widget.js": "/neu-widget.js", "/neu-widget.css": "/neu-widget.css",
          "/assets/neubie-logo-head.png": "/assets/neubie-logo-head.png"}


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        route = unquote(urlsplit(self.path).path)
        if route in ASSETS:
            self.directory = str(ROOT)
            self.path = ASSETS[route]
        elif route in ("/widget/neu-widget.js", "/widget/neu-widget.css", "/widget/assets/neubie-logo-head.png"):
            self.directory = str(ROOT)
            self.path = route.removeprefix("/widget")
        elif route.startswith("/front-end/"):
            relative = route.removeprefix("/front-end/")
            target = (FRONTEND / relative).resolve()
            public_extensions = {".htm", ".html", ".css", ".js", ".webp", ".jpg", ".png", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".mp4"}
            if not target.is_relative_to(FRONTEND.resolve()) or not target.is_file() or (
                target.suffix.lower() not in public_extensions and relative not in
                {"css2", "css2-1", "css2-2", "css2-3", "css/avenir"}
            ):
                self.send_error(404)
                return None
            self.directory = str(FRONTEND)
            self.path = "/" + relative
        else:
            self.send_error(404)
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="Local server port (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; use 0.0.0.0 for phone testing on your private Wi-Fi")
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), DemoHandler) as server:
        port = server.server_address[1]
        print(f"Neubie website (live API): http://127.0.0.1:{port}/front-end/main/index.htm", flush=True)
        print(f"Widget demo (mock): http://127.0.0.1:{port}/demo.html?mock=1", flush=True)
        if args.host == "0.0.0.0":
            print(f"Phone: use http://YOUR-PC-IP:{port}/front-end/main/index.htm (same private Wi-Fi).", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nNeubie demo stopped.", flush=True)
