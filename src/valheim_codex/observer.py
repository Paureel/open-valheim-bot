"""Loopback-only brain observer. No game API, mutation routes, or directory listing."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .brain import read_feed
from .config import ROOT


class ObserverServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, home, port=8733):
        self.feed = home / "run/brain.json"
        super().__init__(("127.0.0.1", port), ObserverHandler)


class ObserverHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origins = {"http://" + host for host in hosts}
        if self.headers.get("Host") not in hosts or self.headers.get("Origin") not in (None, *origins):
            self.send_error(403); return
        route = urlsplit(self.path).path
        assets = {"/":("index.html","text/html; charset=utf-8"),
                  "/brain.css":("brain.css","text/css; charset=utf-8"),
                  "/brain.js":("brain.js","text/javascript; charset=utf-8")}
        if route == "/api/state":
            body = json.dumps(read_feed(self.server.feed), ensure_ascii=False).encode()
            mime = "application/json; charset=utf-8"
        elif route in assets:
            filename, mime = assets[route]
            body = (ROOT / "web/brain" / filename).read_bytes()
        else:
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)


def serve(config, port=8733):
    import signal
    import threading
    server = ObserverServer(config.home, port)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"Brain observer: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever(poll_interval=.25)
    finally:
        server.server_close()
