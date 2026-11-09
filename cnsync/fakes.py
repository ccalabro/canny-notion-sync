"""In-memory stand-ins for the Canny and Notion APIs.

They plug in as transports, so the real client code runs end to end in the
demo and the tests, without keys and without network.
"""
from __future__ import annotations

import copy
import json
import uuid
from urllib.parse import urlsplit


def _notion_date(value: dict) -> dict:
    """Notion date properties keep the minute and come back in UTC.

    A written 2026-11-09T23:08:08.241Z is stored as 2026-11-09T23:08:00.000+00:00.
    """
    from datetime import datetime, timezone
    out = copy.deepcopy(value)
    for key in ("start", "end"):
        text = out.get(key)
        if not isinstance(text, str) or "T" not in text:
            continue
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc).replace(second=0, microsecond=0)
        out[key] = dt.strftime("%Y-%m-%dT%H:%M:00.000+00:00")
    return out


def _ok(payload, status=200):
    if payload == "success":
        return status, {"Content-Type": "text/plain"}, b"success"
    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode()


class FakeCanny:
    """Enough of Canny's POST-with-apiKey API for posts and boards."""

    def __init__(self, posts: list[dict], boards: list[dict], api_key: str = "demo_key"):
        self.posts = {p["id"]: copy.deepcopy(p) for p in posts}
        self.order = [p["id"] for p in posts]
        self.boards = boards
        self.api_key = api_key
        self.calls: list[str] = []

    def add(self, post: dict) -> None:
        if post["id"] not in self.posts:
            self.order.append(post["id"])
        self.posts[post["id"]] = copy.deepcopy(post)

    def __call__(self, method, url, headers, body):
        parts = urlsplit(url)
        self.calls.append(f"{method} {parts.path}")
        data = json.loads(body) if body else {}
        if data.get("apiKey") != self.api_key:
            return _ok({"error": "invalid api key"}, 401)
        if parts.path == "/api/v1/boards/list":
            return _ok({"boards": self.boards})
        if parts.path == "/api/v1/posts/list":
            limit = int(data.get("limit") or 10)
            skip = int(data.get("skip") or 0)
            board_id = data.get("boardID")
            ids = self.order
            if board_id:
                ids = [i for i in ids if (self.posts[i].get("board") or {}).get("id") == board_id]
            chunk = ids[skip:skip + limit]
            return _ok({
                "posts": [self.posts[i] for i in chunk],
                "hasMore": skip + limit < len(ids),
            })
        if parts.path == "/api/v1/posts/retrieve":
            pid = data.get("id")
            if pid not in self.posts:
                return _ok({"error": "post not found"}, 404)
            return _ok(self.posts[pid])
        return _ok({"error": f"no route {parts.path}"}, 404)


class FakeNotion:
    """Just enough of Notion's data source model for this tool."""

    def __init__(self, database_id="db_demo", data_source_id="ds_demo", title_name="Name"):
        self.database_id = database_id
        self.data_source_id = data_source_id
        self.schema = {title_name: {"id": "title", "name": title_name, "type": "title", "title": {}}}
        self.pages: dict[str, dict] = {}
        self.writes: list[str] = []

    def __call__(self, method, url, headers, body):
        path = urlsplit(url).path
        data = json.loads(body) if body else {}
        if not headers.get("Notion-Version"):
            return _ok({"object": "error", "code": "missing_version", "message": "Notion-Version header missing"}, 400)
        if method == "GET" and path == f"/v1/databases/{self.database_id}":
            return _ok({"object": "database", "id": self.database_id,
                        "data_sources": [{"id": self.data_source_id, "name": "Canny posts"}]})
        if path == f"/v1/data_sources/{self.data_source_id}":
            if method == "PATCH":
                for name, spec in data["properties"].items():
                    kind = next(iter(spec))
                    self.schema[name] = {"id": name[:4], "name": name, "type": kind, kind: spec[kind]}
                self.writes.append("schema")
            return _ok({"object": "data_source", "id": self.data_source_id, "properties": self.schema})
        if method == "POST" and path == f"/v1/data_sources/{self.data_source_id}/query":
            return _ok(self._query(data))
        if method == "POST" and path == "/v1/pages":
            if data["parent"].get("data_source_id") != self.data_source_id:
                return _ok({"object": "error", "code": "validation_error", "message": "bad parent"}, 400)
            err = self._check(data["properties"])
            if err:
                return _ok({"object": "error", "code": "validation_error", "message": err}, 400)
            page = {"object": "page", "id": str(uuid.uuid4()), "in_trash": False,
                    "properties": self._store(data["properties"], {})}
            self.pages[page["id"]] = page
            self.writes.append(f"create {page['id']}")
            return _ok(page)
        if method == "PATCH" and path.startswith("/v1/pages/"):
            pid = path.rsplit("/", 1)[1]
            if pid not in self.pages:
                return _ok({"object": "error", "code": "object_not_found", "message": "no page"}, 404)
            err = self._check(data["properties"])
            if err:
                return _ok({"object": "error", "code": "validation_error", "message": err}, 400)
            page = self.pages[pid]
            page["properties"] = self._store(data["properties"], page["properties"])
            self.writes.append(f"update {pid}")
            return _ok(page)
        return _ok({"object": "error", "code": "invalid_request_url", "message": f"{method} {path}"}, 400)

    def _check(self, props):
        for name in props:
            if name not in self.schema:
                return f"{name} is not a property that exists."
        return None

    def _store(self, props, existing):
        out = copy.deepcopy(existing)
        for name, value in props.items():
            kind = self.schema[name]["type"]
            v = copy.deepcopy(value[kind])
            if kind in ("title", "rich_text"):
                for r in v:
                    r["plain_text"] = r["text"]["content"]
            if kind == "select" and v:
                opts = self.schema[name][kind].setdefault("options", [])
                if v["name"] not in [o["name"] for o in opts]:
                    opts.append({"name": v["name"], "color": "default"})
            if kind == "multi_select" and v:
                opts = self.schema[name][kind].setdefault("options", [])
                for item in v:
                    if item["name"] not in [o["name"] for o in opts]:
                        opts.append({"name": item["name"], "color": "default"})
            if kind == "date" and v:
                v = _notion_date(v)
            out[name] = {"id": self.schema[name]["id"], "type": kind, kind: v}
        return out

    def _query(self, data):
        rows = list(self.pages.values())
        f = data.get("filter")
        if f:
            want = f["rich_text"]["equals"]
            rows = [p for p in rows
                    if "".join(r["plain_text"] for r in (p["properties"].get(f["property"]) or {}).get("rich_text", [])) == want]
        size = data.get("page_size", 100)
        start = int(data.get("start_cursor") or 0)
        chunk = rows[start:start + size]
        more = start + size < len(rows)
        return {"object": "list", "results": copy.deepcopy(chunk),
                "has_more": more, "next_cursor": str(start + size) if more else None}

    def rows(self, title_prop="Name"):
        from .mapping import page_to_row
        return [page_to_row(p, title_prop) for p in self.pages.values()]
