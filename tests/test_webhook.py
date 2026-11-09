import base64
import json
import time
import urllib.error
import urllib.request

from cnsync.canny import Canny
from cnsync.fakes import FakeCanny, FakeNotion
from cnsync.notion import Notion
from cnsync.sync import Syncer
from cnsync.webhook import WebhookApp, make_server, sign, verify_signature


def _secret():
    return "whsec_" + base64.b64encode(b"unit-test-secret-bytes!!!!").decode()


def test_sign_and_verify_round_trip():
    secret = _secret()
    raw = b'{"type":"post.created"}'
    mid, ts = "msg_1", str(int(time.time()))
    sig = sign(secret, mid, ts, raw)
    headers = {"webhook-id": mid, "webhook-timestamp": ts, "webhook-signature": f"v1,{sig}"}
    assert verify_signature(secret, raw, headers)


def test_verify_rejects_wrong_secret_and_old_timestamp():
    secret = _secret()
    raw = b"{}"
    mid, ts = "msg_1", str(int(time.time()))
    sig = sign(secret, mid, ts, raw)
    headers = {"webhook-id": mid, "webhook-timestamp": ts, "webhook-signature": f"v1,{sig}"}
    other = "whsec_" + base64.b64encode(b"other-secret-bytes!!!!!!!!").decode()
    assert not verify_signature(other, raw, headers)
    headers["webhook-timestamp"] = str(int(time.time()) - 600)
    # Re-sign with old timestamp so the HMAC matches but age fails
    headers["webhook-signature"] = f"v1,{sign(secret, mid, headers['webhook-timestamp'], raw)}"
    assert not verify_signature(secret, raw, headers)


def test_http_server_accepts_signed_and_rejects_bad(posts, boards, events):
    fake_c = FakeCanny(posts, boards, api_key="k")
    fake_n = FakeNotion()
    canny = Canny("k", transport=fake_c)
    notion = Notion("tok", fake_n.database_id, transport=fake_n)
    notion.check_schema(fix=True)
    syncer = Syncer(canny, notion, log=lambda *_: None)
    syncer.backfill()

    secret = _secret()
    app = WebhookApp(secret, syncer, log=lambda *_: None)
    server = make_server(app, "127.0.0.1", 0)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/webhooks/canny"

    def post(event, secret_used=secret, age=0, mid="msg_ok"):
        raw = json.dumps(event).encode()
        ts = str(int(time.time()) - age)
        req = urllib.request.Request(url, data=raw, method="POST", headers={
            "Content-Type": "application/json",
            "webhook-id": mid,
            "webhook-timestamp": ts,
            "webhook-signature": f"v1,{sign(secret_used, mid, ts, raw)}",
        })
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    pid = posts[0]["id"]
    fake_c.posts[pid]["status"] = "in progress"
    fake_c.posts[pid]["statusChangedAt"] = "2026-11-09T20:05:00.000Z"
    assert post(events["02_status_changed.json"]) == 200
    app.queue.join()

    assert post(events["02_status_changed.json"], mid="msg_ok") == 200  # duplicate
    app.queue.join()

    bad = "whsec_" + base64.b64encode(b"bad-secret-bytes!!!!!!!!!!").decode()
    assert post(events["03_vote_created.json"], secret_used=bad, mid="msg_bad") == 401
    assert post(events["03_vote_created.json"], age=600, mid="msg_old") == 401
    server.shutdown()
