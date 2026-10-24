"""Serve only public demo assets; never expose .env or repository files."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "front-end"
ASSETS = {"/": "/demo.html", "/demo.html": "/demo.html",
          "/neu-widget.js": "/neu-widget.js", "/neu-widget.css": "/neu-widget.css"}


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        route = unquote(urlsplit(self.path).path)
        if route in ASSETS:
            self.directory = str(ROOT)
            self.path = ASSETS[route]
        elif route in ("/widget/neu-widget.js", "/widget/neu-widget.css"):
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
    print("Neubie demo: http://127.0.0.1:8000/demo.html?mock=1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), DemoHandler).serve_forever()
