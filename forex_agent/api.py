"""Dependency-free local HTTP API. Deploy behind a maintained TLS reverse proxy."""

from __future__ import annotations

from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
import threading
import time
from urllib.parse import parse_qs, urlsplit
from .agent import ForexAgent
from .journal import Journal
from .models import RiskPolicy, ValidationError, utc


def handler_factory(db_path: str, token: str, policy: RiskPolicy):
    traffic = defaultdict(deque)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ForexAgent/0.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, fmt, *args):
            # Do not log payload, headers, tokens, or user-supplied URL parameters.
            pass

        def send(self, code, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def permitted(self):
            provided = self.headers.get("Authorization", "")
            if not hmac.compare_digest(provided.encode(), ("Bearer " + token).encode()):
                self.send(401, {"error": "Bearer token diperlukan."})
                return False
            with lock:
                key, now = self.client_address[0], time.monotonic()
                # Bounded storage: remove inactive IP entries before adding this request.
                for ip in list(traffic):
                    while traffic[ip] and traffic[ip][0] <= now - 60:
                        traffic[ip].popleft()
                    if not traffic[ip]:
                        del traffic[ip]
                if len(traffic[key]) >= 60:
                    self.send(429, {"error": "Batas 60 request/menit tercapai."})
                    return False
                traffic[key].append(now)
            return True

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self.send(200, {"status": "ok", "execution_enabled": False})
                return
            if not self.permitted():
                return
            if parsed.path == "/v1/journal":
                simulated = parse_qs(parsed.query).get("simulated", ["false"])[0] == "true"
                with Journal(db_path) as journal:
                    self.send(200, journal.summary(simulated))
            else:
                self.send(404, {"error": "Endpoint tidak ditemukan."})

        def do_POST(self):
            if not self.permitted():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4 * 1024 * 1024:
                    self.send(413, {"error": "Body harus 1 byte–4 MiB."})
                    return
                if self.headers.get_content_type() != "application/json":
                    self.send(415, {"error": "Gunakan application/json."})
                    return
                raw = self.rfile.read(length)
                payload = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValidationError("Angka JSON tidak valid.")))
                if not isinstance(payload, dict):
                    raise ValidationError("Body harus object JSON.")
                path = urlsplit(self.path).path
                with Journal(db_path) as journal:
                    agent = ForexAgent(journal, policy)
                    if path == "/v1/analyze":
                        mode = payload.get("mode", "analyst")
                        if mode not in ("analyst", "signal"):
                            raise ValidationError("Gunakan /v1/risk untuk mode risk.")
                        result = agent.analyze(payload["snapshot"], payload.get("timeframe", "M15"), mode)
                    elif path == "/v1/risk":
                        result = agent.analyze(payload["snapshot"], payload.get("timeframe", "M15"), "risk", payload["proposed_trade"])
                    elif path == "/v1/journal/open":
                        result = {"trade_id": journal.open_trade(payload), "status": "recorded"}
                    elif path == "/v1/journal/close":
                        journal.close_trade(payload["trade_id"], payload["net_pnl"], utc(payload["closed_at"]))
                        result = {"status": "closed"}
                    else:
                        self.send(404, {"error": "Endpoint tidak ditemukan."})
                        return
                self.send(200, result)
            except (ValidationError, KeyError, ValueError, TypeError, AttributeError) as exc:
                self.send(400, {"error": str(exc)})
            except Exception:
                self.send(500, {"error": "Operasi gagal; tidak ada sinyal yang dapat digunakan."})

    return Handler


def serve(db_path="data/journal.sqlite3", host="127.0.0.1", port=8000, policy=None):
    token = os.getenv("FOREX_API_TOKEN", "")
    if len(token) < 32:
        raise ValidationError("Set FOREX_API_TOKEN minimal 32 karakter sebelum menjalankan API.")
    server = ThreadingHTTPServer((host, port), handler_factory(db_path, token, policy or RiskPolicy()))
    print(f"Forex Agent API: http://{host}:{port} — hentikan dengan Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
