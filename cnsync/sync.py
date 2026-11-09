"""Upsert logic shared by the backfill and the webhook receiver."""
from __future__ import annotations

from dataclasses import dataclass, field

from .canny import Canny
from .http import ApiError
from .mapping import DELETED_STATUS, diff, page_to_row, post_to_row, row_to_properties
from .notion import Notion

# Events that mean "read the current post and upsert it".
POST_TYPES = {
    "post.created",
    "post.status_changed",
    "vote.created",
    "vote.deleted",
    "post.jira_issue_linked",
    "post.jira_issue_unlinked",
}


@dataclass
class Result:
    action: str          # created, updated, unchanged, skipped, ignored
    post_id: str | None = None
    title: str | None = None
    changes: dict = field(default_factory=dict)
    note: str = ""

    def line(self) -> str:
        head = f"{self.action:<9} {self.post_id or '-'}"
        if self.title:
            head += f"  {self.title!r}"
        if self.changes:
            # Keep the line short: show at most a few fields.
            parts = []
            for k, (o, n) in list(self.changes.items())[:4]:
                parts.append(f"{k}: {o!r} -> {n!r}")
            head += "  " + ", ".join(parts)
            if len(self.changes) > 4:
                head += ", ..."
        if self.note:
            head += f"  ({self.note})"
        return head


class Syncer:
    def __init__(self, canny: Canny, notion: Notion, log=print):
        self.canny = canny
        self.notion = notion
        self.log = log

    def upsert(self, post: dict, index: dict | None = None) -> Result:
        self.notion.ensure_ready()
        title_prop = self.notion.title_prop
        row = post_to_row(post)
        key = row["canny_id"]

        if index is not None:
            page = index.get(key)
        else:
            found = self.notion.find_by_key(key)
            if len(found) > 1:
                self.log(f"warning: {len(found)} Notion pages share Canny ID {key}, updating the first")
            page = found[0] if found else None

        if page is None:
            created = self.notion.create_page(row_to_properties(row, title_prop))
            if index is not None:
                index[key] = created
            return Result("created", key, row["title"])

        changes = diff(page_to_row(page, title_prop), row)
        if not changes:
            return Result("unchanged", key, row["title"])
        updated = self.notion.update_page(page["id"], row_to_properties(row, title_prop))
        if index is not None:
            index[key] = updated
        return Result("updated", key, row["title"], changes)

    def backfill(self, page_size: int = 100, board_id: str | None = None) -> dict[str, int]:
        self.notion.ensure_ready()
        title_prop = self.notion.title_prop
        index: dict[str, dict] = {}
        for page in self.notion.iter_pages():
            key = page_to_row(page, title_prop).get("canny_id")
            if not key:
                continue
            if key in index:
                self.log(f"warning: more than one Notion page has Canny ID {key}, using the first")
                continue
            index[key] = page

        counts = {"created": 0, "updated": 0, "unchanged": 0}
        seen = set()
        for post in self.canny.iter_posts(limit=page_size, board_id=board_id):
            if post["id"] in seen:
                continue
            seen.add(post["id"])
            res = self.upsert(post, index)
            counts[res.action] += 1
            if res.action != "unchanged":
                self.log(res.line())
        return counts

    def handle_event(self, event: dict) -> Result:
        etype = event.get("type")
        obj = event.get("object") or {}

        if etype == "post.deleted":
            return self._mark_deleted(obj.get("id"))
        if etype not in POST_TYPES:
            return Result("ignored", note=f"type {etype}")

        post_id = _post_id_from_event(etype, obj)
        if not post_id:
            return Result("skipped", note=f"{etype} without a post id")

        # Events can arrive out of order, and vote events carry no score,
        # so I read the current post from the API every time.
        try:
            post = self.canny.get_post(post_id)
        except ApiError as e:
            if e.status == 404:
                return Result("skipped", post_id, note="post no longer exists in Canny")
            raise

        res = self.upsert(post)
        res.note = etype
        return res

    def _mark_deleted(self, post_id: str | None) -> Result:
        if not post_id:
            return Result("skipped", note="post.deleted without a post id")
        self.notion.ensure_ready()
        found = self.notion.find_by_key(post_id)
        if not found:
            return Result("unchanged", post_id, note="post.deleted, no Notion row")
        page = found[0]
        if page_to_row(page, self.notion.title_prop).get("status") == DELETED_STATUS:
            return Result("unchanged", post_id, note="post.deleted, already marked")
        self.notion.update_page(page["id"], {"Status": {"select": {"name": DELETED_STATUS}}})
        return Result("updated", post_id, note="post.deleted, row kept and marked")


def _post_id_from_event(etype: str, obj: dict) -> str | None:
    if etype.startswith("post."):
        return obj.get("id")
    if etype.startswith("vote."):
        # Vote objects include a nested post or a postID, depending on the docs era.
        if isinstance(obj.get("post"), dict):
            return obj["post"].get("id")
        return obj.get("postID") or obj.get("postId")
    return obj.get("id")
