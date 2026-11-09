"""Canny webhook receiver.

Canny signs deliveries with the Standard Webhooks spec:
  signed content = "{webhook-id}.{webhook-timestamp}.{raw body}"
  key = base64-decode of the secret after the "whsec_" prefix
  algorithm = HMAC-SHA256, base64, entries like "v1,<sig>" in webhook-signature

Docs: https://help.canny.io/en/articles/4195400-the-canny-api
Spec: https://github.com/standard-webhooks/standard-webhooks
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import queue
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOLERANCE_SECONDS = 300
MAX_BODY = 1_000_000


def _signing_key(secret: str) -> bytes:
    if not secret.startswith("whsec_"):
        raise ValueError("Canny webhook secrets start with whsec_")
    return base64.b64decode(secret[len("whsec_"):])


def sign(secret: str, msg_id: str, timestamp: str, raw_body: bytes) -> str:
    """Return the base64 signature for one Standard Webhooks entry."""
    key = _signing_key(secret)
    to_sign = f"{msg_id}.{timestamp}.".encode() + raw_body
    return base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode()


def verify_signature(secret: str, raw_body: bytes, headers: dict,
                     now: float | None = None) -> bool:
    """headers is a case-insensitive map of the three Standard Webhooks headers."""
    h = {k.lower(): v for k, v in headers.items()}
    msg_id = h.get("webhook-id")
    timestamp = h.get("webhook-timestamp")
    signature_header = h.get("webhook-signature")
    if not secret or not msg_id or not timestamp or not signature_header:
        return False
    if not timestamp.isdigit():
        return False
    now = time.time() if now is None else now
    if abs(now - int(timestamp)) > TOLERANCE_SECONDS:
        return False
    try:
        expected = sign(secret, msg_id, timestamp, raw_body)
    except (ValueError, base64.binascii.Error):
        return False
    for entry in signature_header.split(" "):
        if "," not in entry:
            continue
        version, sig = entry.split(",", 1)
        if version != "v1" or not sig:
            continue
        if hmac.compare_digest(expected, sig):
            return True
    return False


class SeenEvents:
    """Remembers the last N webhook-id values. Canny can retry the same delivery.
    The upsert is idempotent anyway, this just saves calls."""

    def __init__(self, maxsize: int = 10_000):
        self.maxsize = maxsize
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, event_id: str) -> bool:
        """True if the ID is new."""
        with self._lock:
            if event_id in self._ids:
                return False
            self._ids[event_id] = None
            if len(self._ids) > self.maxsize:
                self._ids.popitem(last=False)
            return True


class WebhookApp:
    """Verifies, then queues. One worker thread does the Notion writes, so
    events for the same post never race each other."""

    def __init__(self, secret: str, syncer, log=print, clock=time.time):
        self._secret = secret
        self.syncer = syncer
        self.log = log
        self.clock = clock
        self.seen = SeenEvents()
        self.queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

    def handle(self, headers: dict, raw_body: bytes) -> tuple[int, str]:
        h = {k.lower(): v for k, v in headers.items()}
        if not verify_signature(self._secret, raw_body, h, now=self.clock()):
            self.log("rejected  bad or old signature")
            return 401, "invalid signature"
        try:
            event = json.loads(raw_body)
        except ValueError:
            return 400, "invalid json"
        # Deduplicate on the Standard Webhooks message id when present.
        event_id = h.get("webhook-id") or event.get("id")
        if event_id and not self.seen.add(event_id):
            self.log(f"duplicate {event_id}, skipped")
            return 200, "duplicate"
        self.queue.put(event)
        return 200, "queued"

    def _work(self) -> None:
        while True:
            event = self.queue.get()
            try:
                res = self.syncer.handle_event(event)
                self.log(res.line())
            except Exception as e:  # keep the worker alive; backfill can repair later
                self.log(f"error     {event.get('type')}: {e}")
            finally:
                self.queue.task_done()


def make_server(app: WebhookApp, host: str, port: int, path: str = "/webhooks/canny"):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != path:
                return self._reply(404, "not found")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._reply(413, "too large")
            raw = self.rfile.read(length)
            status, msg = app.handle(dict(self.headers.items()), raw)
            self._reply(status, msg)

        def do_GET(self):
            self._reply(200 if self.path == "/health" else 404, "ok" if self.path == "/health" else "not found")

        def _reply(self, status: int, msg: str):
            body = json.dumps({"result": msg}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)
