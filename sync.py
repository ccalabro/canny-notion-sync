#!/usr/bin/env python3
"""Canny to Notion sync.

  python3 sync.py setup [--check]   create or check the Notion properties
  python3 sync.py backfill          copy every Canny post into Notion
  python3 sync.py serve             receive Canny webhooks
  python3 sync.py demo              run everything on fake data, no keys

Config comes from env vars: CANNY_API_KEY, NOTION_TOKEN, NOTION_DATABASE_ID,
CANNY_WEBHOOK_SECRET (serve only), and optionally NOTION_DATA_SOURCE_ID and
CANNY_BOARD_ID. Values are never printed.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from cnsync.canny import Canny
from cnsync.notion import Notion, SchemaError
from cnsync.sync import Syncer
from cnsync.webhook import WebhookApp, make_server, sign

ROOT = Path(__file__).resolve().parent


def need(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit("missing env vars: " + ", ".join(missing))
    return {n: os.environ[n] for n in names}


def notion_from_env() -> Notion:
    env = need("NOTION_TOKEN", "NOTION_DATABASE_ID")
    return Notion(env["NOTION_TOKEN"], env["NOTION_DATABASE_ID"],
                  data_source_id=os.environ.get("NOTION_DATA_SOURCE_ID") or None)


def canny_from_env() -> Canny:
    return Canny(need("CANNY_API_KEY")["CANNY_API_KEY"])


def cmd_setup(args) -> None:
    notion = notion_from_env()
    missing = notion.check_schema(fix=not args.check)
    if not missing:
        print(f"Notion database is ready. Title property: {notion.title_prop!r}")
    elif args.check:
        sys.exit("missing properties: " + ", ".join(missing) + ". Run `python3 sync.py setup` to add them.")
    else:
        print("added properties: " + ", ".join(missing))


def cmd_backfill(args) -> None:
    syncer = Syncer(canny_from_env(), notion_from_env())
    board_id = os.environ.get("CANNY_BOARD_ID") or None
    counts = syncer.backfill(board_id=board_id)
    print(_summary(counts))


def cmd_serve(args) -> None:
    secret = need("CANNY_WEBHOOK_SECRET")["CANNY_WEBHOOK_SECRET"]
    syncer = Syncer(canny_from_env(), notion_from_env())
    syncer.notion.ensure_ready()
    app = WebhookApp(secret, syncer)
    server = make_server(app, args.host, args.port)
    print(f"listening on http://{args.host}:{args.port}/webhooks/canny")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def _summary(c: dict) -> str:
    return f"{c['created']} created, {c['updated']} updated, {c['unchanged']} unchanged"


def _demo_secret() -> str:
    # A valid Standard Webhooks secret: whsec_ + base64 of 24 random bytes.
    return "whsec_" + base64.b64encode(b"canny-demo-secret-bytes!!").decode()


def cmd_demo(args) -> None:
    from cnsync.fakes import FakeCanny, FakeNotion

    posts = json.loads((ROOT / "samples/posts.json").read_text())
    boards = json.loads((ROOT / "samples/boards.json").read_text())
    api_key = "demo_key"
    canny_fake = FakeCanny(posts, boards, api_key=api_key)
    notion_fake = FakeNotion()
    canny = Canny(api_key, transport=canny_fake)
    notion = Notion("ntn_demo_not_a_real_token", notion_fake.database_id, transport=notion_fake)
    log = lambda s: print("  " + s)
    syncer = Syncer(canny, notion, log=log)

    print("== 1. setup on an empty Notion database")
    print("  added: " + ", ".join(notion.check_schema(fix=True)))
    print("  second check, missing: " + (", ".join(notion.check_schema()) or "nothing"))

    print(f"\n== 2. backfill ({len(posts)} posts, Canny pages of {args.page_size})")
    counts = syncer.backfill(page_size=args.page_size)
    pages = sum(1 for c in canny_fake.calls if c == "POST /api/v1/posts/list")
    print(f"  {_summary(counts)}, read in {pages} Canny pages")

    print("\n== 3. backfill again, nothing should change")
    canny_fake.calls.clear()
    before = len(notion_fake.writes)
    print("  " + _summary(syncer.backfill(page_size=args.page_size))
          + f", Notion writes: {len(notion_fake.writes) - before}")

    print("\n== 4. webhooks through the real HTTP server on 127.0.0.1")
    secret = _demo_secret()
    app = WebhookApp(secret, syncer, log=log)
    server = make_server(app, "127.0.0.1", 0)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/webhooks/canny"
    msg_counter = 0

    def send(event: dict, *, secret_used=secret, age=0, label="", msg_id=None):
        nonlocal msg_counter
        msg_counter += 1
        mid = msg_id or f"msg_demo_{msg_counter:04d}"
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
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        app.queue.join()
        print(f"  -> {label or event['type']}: HTTP {status}")

    ev = {p.name: json.loads(p.read_text()) for p in sorted((ROOT / "samples/events").glob("*.json"))}
    notion_id = posts[0]["id"]

    canny_fake.add(json.loads((ROOT / "samples/new_post.json").read_text()))
    send(ev["01_post_created.json"])

    canny_fake.posts[notion_id]["status"] = "in progress"
    canny_fake.posts[notion_id]["statusChangedAt"] = "2026-11-09T20:05:00.000Z"
    send(ev["02_status_changed.json"], label="post.status_changed")

    canny_fake.posts[notion_id]["score"] += 1
    send(ev["03_vote_created.json"])

    send(ev["03_vote_created.json"], label="same vote.created again", msg_id="msg_demo_0003")

    deleted_id = ev["04_post_deleted.json"]["object"]["id"]
    canny_fake.posts.pop(deleted_id)
    canny_fake.order.remove(deleted_id)
    send(ev["04_post_deleted.json"])

    forged = copy.deepcopy(ev["03_vote_created.json"])
    wrong_secret = "whsec_" + base64.b64encode(b"definitely-not-the-key!!").decode()
    send(forged, secret_used=wrong_secret, label="wrong secret", msg_id="msg_forged")
    old = copy.deepcopy(ev["03_vote_created.json"])
    send(old, age=600, label="10 minute old timestamp", msg_id="msg_old")
    server.shutdown()

    print("\n== 5. Notion rows now (top 6 by votes)")
    rows = sorted(notion_fake.rows(notion.title_prop), key=lambda r: -(r["votes"] or 0))
    print(f"  {'Votes':>5}  {'Status':<14} {'Board':<14} Title")
    for r in rows[:6]:
        print(f"  {r['votes']:>5}  {r['status'] or '':<14} {r['board'] or '':<14} {r['title']}")
    print(f"  ... {len(rows)} rows in total")
    print(f"  {len(notion_fake.writes)} writes to the fake Notion, no calls to the real Canny or Notion")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="create or check the Notion properties")
    s.add_argument("--check", action="store_true", help="only check, change nothing")
    s.set_defaults(fn=cmd_setup)
    sub.add_parser("backfill", help="copy every Canny post into Notion").set_defaults(fn=cmd_backfill)
    s = sub.add_parser("serve", help="receive Canny webhooks")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("demo", help="run on fake data, no keys needed")
    s.add_argument("--page-size", type=int, default=10)
    s.set_defaults(fn=cmd_demo)
    args = p.parse_args(argv)
    try:
        args.fn(args)
    except SchemaError as e:
        sys.exit(f"Notion schema problem: {e}")


if __name__ == "__main__":
    main()
