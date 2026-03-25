#!/usr/bin/env python3
"""
Ollama Vision Proxy
Runs on port 11435, forwards to Ollama on port 11434.
Injects "vision" capability for kimi models in /api/tags response.
"""

import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

OLLAMA_UPSTREAM = "http://127.0.0.1:11434"
PROXY_PORT = 11435

# Models that should have vision capability injected
VISION_MODELS = ["kimi-k2.5:cloud", "kimi", "qwen3-vl", "qwen2.5vl", "llava", "minicpm-v", "moondream"]


class OllamaProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default access logs (optional)
        pass

    def do_GET(self):
        self._proxy(method="GET")

    def do_POST(self):
        self._proxy(method="POST")

    def do_DELETE(self):
        self._proxy(method="DELETE")

    def do_HEAD(self):
        self._proxy(method="HEAD")

    def _proxy(self, method):
        # Read request body if present
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Build upstream URL
        upstream_url = OLLAMA_UPSTREAM + self.path

        # Build request
        req = urllib.request.Request(
            upstream_url,
            data=body,
            method=method,
        )
        # Forward headers (except host)
        for key, val in self.headers.items():
            if key.lower() not in ("host", "content-length"):
                req.add_header(key, val)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_body = resp.read()
                status = resp.status
                headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            response_body = e.read()
            status = e.code
            headers = dict(e.headers)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Proxy error: {e}".encode())
            return

        # Intercept /api/tags — inject vision tag for kimi models
        if self.path == "/api/tags":
            try:
                data = json.loads(response_body)
                modified = False
                for model in data.get("models", []):
                    name = model.get("name", "").lower()
                    if any(v in name for v in VISION_MODELS):
                        details = model.setdefault("details", {})
                        # Inject both families (clip) and capabilities
                        families = details.get("families") or []
                        if "clip" not in families:
                            families.append("clip")
                            details["families"] = families
                        # Add capabilities field
                        caps = model.get("capabilities") or []
                        if "vision" not in caps:
                            caps.append("vision")
                            model["capabilities"] = caps
                        modified = True
                        print(f"[ollama-proxy] Injected vision for: {model['name']}")
                if modified:
                    response_body = json.dumps(data).encode()
                    headers["Content-Length"] = str(len(response_body))
            except Exception as e:
                print(f"[ollama-proxy] Failed to patch /api/tags: {e}")

        # Intercept /api/show — pass through as-is (Ollama already returns capabilities correctly)
        elif "/api/show" in self.path:
            pass  # No modification needed, Ollama already returns vision capability

        # Send response
        self.send_response(status)
        for key, val in headers.items():
            if key.lower() in ("content-type", "content-length", "transfer-encoding"):
                try:
                    self.send_header(key, val)
                except Exception:
                    pass
        self.end_headers()
        self.wfile.write(response_body)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PROXY_PORT), OllamaProxyHandler)
    print(f"[ollama-proxy] Started on port {PROXY_PORT} → forwarding to {OLLAMA_UPSTREAM}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[ollama-proxy] Stopped.")
