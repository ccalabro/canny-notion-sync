#!/usr/bin/env python3
"""Build sample boards, posts, and webhook events for the demo and tests."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BOARD = {
    "id": "board_integrations",
    "created": "2019-01-10T12:00:00.000Z",
    "name": "Integrations",
    "postCount": 20,
    "url": "https://demo.canny.io/admin/board/integrations",
}
BOARD_BUGS = {
    "id": "board_bugs",
    "created": "2019-02-01T12:00:00.000Z",
    "name": "Bug Reports",
    "postCount": 3,
    "url": "https://demo.canny.io/admin/board/bug-reports",
}

AUTHORS = [
    {"id": "u1", "name": "Alex Rivera", "email": "alex@example.com", "isAdmin": False,
     "created": "2020-01-01T00:00:00.000Z", "url": "https://demo.canny.io/admin/users/alex", "userID": "1"},
    {"id": "u2", "name": "Sam Chen", "email": "sam@example.com", "isAdmin": False,
     "created": "2020-02-01T00:00:00.000Z", "url": "https://demo.canny.io/admin/users/sam", "userID": "2"},
    {"id": "u3", "name": "Jordan Lee", "email": "jordan@example.com", "isAdmin": True,
     "created": "2019-06-01T00:00:00.000Z", "url": "https://demo.canny.io/admin/users/jordan", "userID": "3"},
]

STATUSES = ["open", "under review", "planned", "in progress", "complete", "closed"]
CATEGORIES = [
    {"id": "cat_notion", "name": "Notion", "postCount": 5,
     "url": "https://demo.canny.io/admin/board/integrations?category=notion"},
    {"id": "cat_zapier", "name": "Zapier", "postCount": 3,
     "url": "https://demo.canny.io/admin/board/integrations?category=zapier"},
    {"id": "cat_slack", "name": "Slack", "postCount": 2,
     "url": "https://demo.canny.io/admin/board/integrations?category=slack"},
]
TAGS = [
    {"id": "tag_api", "name": "api", "postCount": 8,
     "url": "https://demo.canny.io/admin/board/integrations?tags=api"},
    {"id": "tag_sync", "name": "sync", "postCount": 6,
     "url": "https://demo.canny.io/admin/board/integrations?tags=sync"},
    {"id": "tag_export", "name": "export", "postCount": 2,
     "url": "https://demo.canny.io/admin/board/integrations?tags=export"},
]

# First post mirrors Canny's public Notion request shape (votes approximate).
TITLES = [
    ("Notion", 258, "under review", "cat_notion", ["tag_api", "tag_sync"],
     "Push Canny posts into a Notion database. Title, details, status, and score."),
    ("Two way sync with Airtable", 91, "planned", "cat_zapier", ["tag_sync"],
     "Keep Airtable and Canny statuses in sync both ways."),
    ("GitHub issues two way", 74, "in progress", "cat_zapier", ["tag_api"],
     "Link posts to GitHub issues and sync status."),
    ("Linear status sync", 63, "planned", "cat_zapier", ["tag_sync"],
     "Update Linear when a Canny status changes."),
    ("Public roadmap embed", 55, "complete", "cat_slack", ["tag_export"],
     "Embed the public roadmap on a marketing site."),
    ("CSV export of votes", 48, "open", "cat_zapier", ["tag_export"],
     "Download a CSV of votes with company and MRR."),
    ("Slack status alerts", 41, "in progress", "cat_slack", ["tag_api"],
     "Post to a Slack channel when a status changes."),
    ("Asana task create", 37, "under review", "cat_zapier", ["tag_api"],
     "Create an Asana task from a planned post."),
    ("ClickUp link", 33, "open", "cat_zapier", [],
     "Link ClickUp tasks the way Jira links work."),
    ("Microsoft Teams bot", 29, "closed", "cat_slack", [],
     "A Teams bot for voting from chat."),
    ("Salesforce opportunity link", 26, "planned", "cat_zapier", ["tag_api"],
     "Attach opportunities to posts without Zapier."),
    ("HubSpot deal sync", 24, "under review", "cat_zapier", ["tag_sync"],
     "Pull deal stage into a custom field."),
    ("Intercom conversation attach", 21, "open", "cat_slack", [],
     "Attach Intercom conversations to a post."),
    ("Custom webhook filters", 19, "in progress", "cat_zapier", ["tag_api"],
     "Filter which boards fire a webhook."),
    ("Roadmap swimlanes by tag", 17, "open", None, ["tag_export"],
     "Group roadmap columns by tag."),
    ("Board level permissions API", 15, "under review", None, ["tag_api"],
     "Read private board membership from the API."),
    ("Duplicate post detection", 14, "planned", None, [],
     "Suggest duplicates when creating a post."),
    ("Mobile vote from email", 12, "open", None, [],
     "One tap vote from the weekly digest."),
    ("Dark mode portal", 11, "complete", None, [],
     "A dark theme for the public portal."),
    ("Timezone aware ETAs", 9, "open", None, [],
     "Show ETA dates in the viewer's timezone."),
]


def _tag(tid: str) -> dict:
    return next(t for t in TAGS if t["id"] == tid)


def _cat(cid: str | None) -> dict | None:
    if not cid:
        return None
    return next(c for c in CATEGORIES if c["id"] == cid)


def make_posts() -> list[dict]:
    posts = []
    for i, (title, score, status, cat, tag_ids, details) in enumerate(TITLES):
        board = BOARD if i < 17 else BOARD_BUGS
        slug = title.lower().replace(" ", "-")
        posts.append({
            "id": f"post_{i:02d}_{slug[:20]}",
            "author": AUTHORS[i % len(AUTHORS)],
            "board": {k: board[k] for k in ("id", "created", "name", "postCount", "url")},
            "category": _cat(cat),
            "commentCount": (i * 3) % 17,
            "created": f"2019-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}T12:00:00.000Z",
            "details": details,
            "score": score,
            "status": status,
            "statusChangedAt": f"2026-0{(i % 9) + 1}-15T14:{(i * 3) % 60:02d}:{(i * 7) % 60:02d}.000Z",
            "tags": [_tag(t) for t in tag_ids],
            "title": title,
            "url": f"https://demo.canny.io/admin/board/{board['name'].lower().replace(' ', '-')}/p/{slug}",
        })
    return posts


def main() -> None:
    posts = make_posts()
    (ROOT / "boards.json").write_text(json.dumps([BOARD, BOARD_BUGS], indent=2) + "\n")
    (ROOT / "posts.json").write_text(json.dumps(posts, indent=2) + "\n")

    new_post = {
        "id": "post_new_two-way-notion",
        "author": AUTHORS[0],
        "board": {k: BOARD[k] for k in ("id", "created", "name", "postCount", "url")},
        "category": _cat("cat_notion"),
        "commentCount": 0,
        "created": "2026-11-09T20:00:00.000Z",
        "details": "A fresh request for two way Notion sync.",
        "score": 1,
        "status": "open",
        "statusChangedAt": "2026-11-09T20:00:00.000Z",
        "tags": [_tag("tag_sync")],
        "title": "Two way sync with Notion databases",
        "url": "https://demo.canny.io/admin/board/integrations/p/two-way-sync-with-notion-databases",
    }
    (ROOT / "new_post.json").write_text(json.dumps(new_post, indent=2) + "\n")

    events = ROOT / "events"
    events.mkdir(exist_ok=True)
    notion = posts[0]
    (events / "01_post_created.json").write_text(json.dumps({
        "created": "2026-11-09T20:00:01.000Z",
        "object": new_post,
        "objectType": "post",
        "type": "post.created",
    }, indent=2) + "\n")
    changed = dict(notion)
    changed["status"] = "in progress"
    changed["statusChangedAt"] = "2026-11-09T20:05:00.000Z"
    (events / "02_status_changed.json").write_text(json.dumps({
        "created": "2026-11-09T20:05:00.000Z",
        "object": changed,
        "objectType": "post",
        "type": "post.status_changed",
    }, indent=2) + "\n")
    (events / "03_vote_created.json").write_text(json.dumps({
        "created": "2026-11-09T20:06:00.000Z",
        "object": {"id": "vote_1", "postID": notion["id"], "voterID": "u2"},
        "objectType": "vote",
        "type": "vote.created",
    }, indent=2) + "\n")
    (events / "04_post_deleted.json").write_text(json.dumps({
        "created": "2026-11-09T20:07:00.000Z",
        "object": {"id": posts[5]["id"], "title": posts[5]["title"]},
        "objectType": "post",
        "type": "post.deleted",
    }, indent=2) + "\n")
    print(f"wrote {len(posts)} posts, 2 boards, 4 events")


if __name__ == "__main__":
    main()
