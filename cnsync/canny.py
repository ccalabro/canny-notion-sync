"""Canny API: only the calls this tool needs.

Auth is a secret apiKey sent in the JSON POST body on every call.
Docs: https://developers.canny.io/api-reference
"""
from __future__ import annotations

from typing import Iterator

from .http import JsonClient, Transport

BASE_URL = "https://canny.io"
PAGE_LIMIT = 100  # posts/list accepts large limits; 100 keeps pages small


class Canny:
    def __init__(self, api_key: str, transport: Transport | None = None, **kw):
        # The key lives only in request bodies, never in headers we might log.
        self._api_key = api_key
        self.http = JsonClient(
            "Canny", BASE_URL,
            {"Accept": "application/json"},
            transport=transport, **kw)

    def _post(self, path: str, **fields):
        body = {"apiKey": self._api_key, **{k: v for k, v in fields.items() if v is not None}}
        return self.http.request("POST", path, body=body)

    def iter_posts(self, limit: int = PAGE_LIMIT, board_id: str | None = None) -> Iterator[dict]:
        """POST /api/v1/posts/list with skip pagination until hasMore is false."""
        skip = 0
        seen_skips = set()
        while True:
            page = self._post("/api/v1/posts/list", limit=limit, skip=skip, boardID=board_id)
            posts = (page or {}).get("posts") or []
            yield from posts
            if not (page or {}).get("hasMore"):
                return
            if skip in seen_skips:
                raise RuntimeError("Canny posts/list returned hasMore without advancing, stopping")
            seen_skips.add(skip)
            skip += len(posts) if posts else limit
            if not posts:
                return

    def get_post(self, post_id: str) -> dict:
        return self._post("/api/v1/posts/retrieve", id=post_id)

    def list_boards(self) -> list[dict]:
        resp = self._post("/api/v1/boards/list")
        return (resp or {}).get("boards") or []
