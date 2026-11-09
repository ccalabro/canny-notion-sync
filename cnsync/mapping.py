"""Canny post -> one flat row -> Notion property values, and back."""
from __future__ import annotations

# Notion property name -> Notion type. The title property is found by type,
# so it keeps whatever name the database already uses.
PROPERTIES = {
    "Canny ID": "rich_text",
    "Status": "select",
    "Votes": "number",
    "Board": "select",
    "Category": "select",
    "Tags": "multi_select",
    "Author": "rich_text",
    "Created": "date",
    "Status changed": "date",
    "Canny URL": "url",
    "Details": "rich_text",
}
KEY_PROPERTY = "Canny ID"
DELETED_STATUS = "Deleted in Canny"
DATE_FIELDS = {"created", "status_changed"}

# row field -> Notion property name
FIELDS = {
    "canny_id": "Canny ID",
    "status": "Status",
    "votes": "Votes",
    "board": "Board",
    "category": "Category",
    "tags": "Tags",
    "author": "Author",
    "created": "Created",
    "status_changed": "Status changed",
    "url": "Canny URL",
    "details": "Details",
}
TEXT_LIMIT = 2000  # Notion's limit for text.content and for URLs


def _select_name(value: str | None) -> str | None:
    if not value:
        return None
    # Notion option names can't contain commas.
    return value.replace(",", " ").strip()[:100] or None


def _url(u: str | None) -> str | None:
    return u if u and len(u) <= TEXT_LIMIT else None


def _tags(post: dict) -> list[str]:
    out = []
    for tag in post.get("tags") or []:
        name = _select_name(tag.get("name") if isinstance(tag, dict) else str(tag))
        if name and name not in out:
            out.append(name)
    return out


def post_to_row(post: dict) -> dict:
    board = post.get("board") or {}
    category = post.get("category") or {}
    author = post.get("author") or {}
    details = post.get("details") or ""
    return {
        "title": (post.get("title") or "(untitled)")[:TEXT_LIMIT],
        "canny_id": post["id"],
        "status": _select_name(post.get("status")),
        "votes": post.get("score"),
        "board": _select_name(board.get("name") if isinstance(board, dict) else None),
        "category": _select_name(category.get("name") if isinstance(category, dict) else None),
        "tags": _tags(post),
        "author": (author.get("name") if isinstance(author, dict) else None) or None,
        "created": post.get("created"),
        "status_changed": post.get("statusChangedAt"),
        "url": _url(post.get("url")),
        "details": details[:TEXT_LIMIT] if details else None,
    }


def _rich(text: str) -> list:
    return [{"type": "text", "text": {"content": text}}]


def row_to_properties(row: dict, title_prop: str) -> dict:
    props = {title_prop: {"title": _rich(row["title"])}}
    for field, name in FIELDS.items():
        value = row.get(field)
        kind = PROPERTIES[name]
        if kind == "rich_text":
            props[name] = {"rich_text": _rich(value) if value else []}
        elif kind == "select":
            props[name] = {"select": {"name": value} if value else None}
        elif kind == "multi_select":
            props[name] = {"multi_select": [{"name": t} for t in (value or [])]}
        elif kind == "number":
            props[name] = {"number": value}
        elif kind == "url":
            props[name] = {"url": value}
        elif kind == "date":
            props[name] = {"date": {"start": value} if value else None}
    return props


def _plain(rich: list | None) -> str:
    return "".join(r.get("plain_text") or (r.get("text") or {}).get("content", "") for r in rich or [])


def page_to_row(page: dict, title_prop: str) -> dict:
    """Read a Notion page back into the same row shape, to compare."""
    p = page.get("properties") or {}
    row = {"title": _plain((p.get(title_prop) or {}).get("title"))}
    for field, name in FIELDS.items():
        v = p.get(name) or {}
        kind = PROPERTIES[name]
        if kind == "rich_text":
            row[field] = _plain(v.get("rich_text")) or None
        elif kind == "select":
            row[field] = (v.get("select") or {}).get("name")
        elif kind == "multi_select":
            row[field] = [o.get("name") for o in (v.get("multi_select") or []) if o.get("name")]
        elif kind == "date":
            row[field] = (v.get("date") or {}).get("start")
        else:
            row[field] = v.get(kind)
    return row


def diff(old: dict, new: dict) -> dict:
    """Fields that change, as {field: (old, new)}.

    Canny posts have no general updatedAt. Change detection compares every
    mapped field. Date fields compare to the minute, because Notion stores
    date properties that way and may rewrite the format.
    """
    out = {}
    for k, v in new.items():
        before = old.get(k)
        if k in DATE_FIELDS and before and v and _same_instant(before, v):
            continue
        if before != v:
            out[k] = (before, v)
    return out


def _same_instant(a: str, b: str) -> bool:
    """True when both times fall in the same minute.

    A Canny time such as 2026-11-09T23:08:08.241Z comes back from Notion
    as 2026-11-09T23:08:00.000+00:00. Seconds are not a real change.
    """
    from datetime import datetime
    try:
        pa = datetime.fromisoformat(a.replace("Z", "+00:00"))
        pb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        return a == b
    return pa.replace(second=0, microsecond=0) == pb.replace(second=0, microsecond=0)
