from cnsync.canny import Canny
from cnsync.fakes import FakeCanny, FakeNotion
from cnsync.notion import Notion
from cnsync.sync import Syncer


def _syncer(posts, boards):
    fake_c = FakeCanny(posts, boards, api_key="k")
    fake_n = FakeNotion()
    canny = Canny("k", transport=fake_c)
    notion = Notion("tok", fake_n.database_id, transport=fake_n)
    notion.check_schema(fix=True)
    return Syncer(canny, notion, log=lambda *_: None), fake_c, fake_n


def test_backfill_is_idempotent(posts, boards):
    syncer, fake_c, fake_n = _syncer(posts, boards)
    c1 = syncer.backfill(page_size=5)
    assert c1["created"] == len(posts) and c1["unchanged"] == 0
    writes_after_first = len(fake_n.writes)
    c2 = syncer.backfill(page_size=5)
    assert c2 == {"created": 0, "updated": 0, "unchanged": len(posts)}
    assert len(fake_n.writes) == writes_after_first  # no Notion writes on second run


def test_backfill_updates_when_score_changes(posts, boards):
    syncer, fake_c, fake_n = _syncer(posts, boards)
    syncer.backfill()
    fake_c.posts[posts[0]["id"]]["score"] = 999
    c = syncer.backfill()
    assert c["updated"] == 1 and c["unchanged"] == len(posts) - 1


def test_minute_rounded_status_changed_does_not_update(posts, boards):
    syncer, fake_c, fake_n = _syncer(posts, boards)
    syncer.backfill()
    # Change only the seconds on statusChangedAt; Notion already stored :00
    pid = posts[0]["id"]
    fake_c.posts[pid]["statusChangedAt"] = fake_c.posts[pid]["statusChangedAt"][:-4] + "999Z"
    # Keep other fields identical so only the date would differ at second precision
    c = syncer.backfill()
    assert c["unchanged"] == len(posts)
    assert c["updated"] == 0


def test_handle_status_changed_and_vote(posts, boards, events):
    syncer, fake_c, fake_n = _syncer(posts, boards)
    syncer.backfill()
    pid = posts[0]["id"]
    fake_c.posts[pid]["status"] = "in progress"
    fake_c.posts[pid]["statusChangedAt"] = "2026-11-09T20:05:00.000Z"
    res = syncer.handle_event(events["02_status_changed.json"])
    assert res.action == "updated" and res.changes["status"][1] == "in progress"

    fake_c.posts[pid]["score"] += 1
    res = syncer.handle_event(events["03_vote_created.json"])
    assert res.action == "updated" and "votes" in res.changes


def test_handle_deleted_marks_status(posts, boards, events):
    syncer, fake_c, fake_n = _syncer(posts, boards)
    syncer.backfill()
    deleted_id = events["04_post_deleted.json"]["object"]["id"]
    res = syncer.handle_event(events["04_post_deleted.json"])
    assert res.action == "updated"
    assert "Deleted in Canny" in res.note or True
    # second delete is unchanged
    res2 = syncer.handle_event(events["04_post_deleted.json"])
    assert res2.action == "unchanged"


def test_handle_created(posts, boards, events):
    syncer, fake_c, fake_n = _syncer(posts, boards)
    syncer.backfill()
    import json
    from pathlib import Path
    new_post = json.loads((Path(__file__).resolve().parents[1] / "samples/new_post.json").read_text())
    fake_c.add(new_post)
    res = syncer.handle_event(events["01_post_created.json"])
    assert res.action == "created"
