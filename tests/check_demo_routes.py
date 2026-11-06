"""Check the demo's public asset routes and private-file exclusions."""
import importlib.util
import threading
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

spec = importlib.util.spec_from_file_location(
    "demo_server", Path(__file__).resolve().parents[1] / "widget/serve_demo.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
server = ThreadingHTTPServer(("127.0.0.1", 0), module.DemoHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
routes = {
    "/front-end/main/index.htm?mock=1": 200,
    "/widget/neu-widget.js": 200,
    "/widget/neu-widget.css": 200,
    "/widget/assets/neubie-logo-head.png": 200,
    "/assets/neubie-logo-head.png": 200,
    "/front-end/main/assets/scripts/neu-widget-config.js": 200,
    "/front-end/main/assets/styles/styles.css": 200,
    "/front-end/css2": 200,
    "/.env": 404,
    "/front-end/../env": 404,
    "/front-end/main/.env": 404,
}
try:
    for route, expected in routes.items():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{route}") as response:
                status = response.status
                response.read()
        except urllib.error.HTTPError as error:
            status = error.code
        assert status == expected, (route, status, expected)
        print(status, route)
finally:
    server.shutdown()
    server.server_close()
