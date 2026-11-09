from cnsync.mapping import diff, page_to_row, post_to_row, row_to_properties


def test_post_to_row_uses_documented_fields(posts):
    row = post_to_row(posts[0])
    assert row["title"] == "Notion"
    assert row["canny_id"] == posts[0]["id"]
    assert row["status"] == "under review"
    assert row["votes"] == 258
    assert row["board"] == "Integrations"
    assert row["category"] == "Notion"
    assert row["tags"] == ["api", "sync"]
    assert row["author"] == "Alex Rivera"
    assert row["url"].startswith("https://demo.canny.io/")
    assert row["created"] == posts[0]["created"]
    assert row["status_changed"] == posts[0]["statusChangedAt"]
    assert "Push Canny posts" in row["details"]


def test_missing_fields_fall_back_safely():
    row = post_to_row({"id": "p1", "title": ""})
    assert row["title"] == "(untitled)"
    assert row["board"] is None and row["category"] is None
    assert row["status"] is None and row["votes"] is None
    assert row["tags"] == [] and row["details"] is None


def test_select_names_drop_commas_because_notion_rejects_them():
    row = post_to_row({
        "id": "p", "title": "t", "status": "Done, shipped",
        "board": {"name": "Ideas, misc"},
        "category": {"name": "A, B"},
        "tags": [{"name": "one,two"}],
    })
    assert row["status"] == "Done  shipped"
    assert row["board"] == "Ideas  misc"
    assert row["category"] == "A  B"
    assert row["tags"] == ["one two"]


def test_long_values_respect_notion_limits():
    row = post_to_row({"id": "p", "title": "x" * 5000, "url": "https://a/" + "y" * 3000,
                       "details": "d" * 5000})
    assert len(row["title"]) == 2000 and row["url"] is None
    assert len(row["details"]) == 2000


def test_properties_round_trip(posts):
    row = post_to_row(posts[1])
    props = row_to_properties(row, "Name")
    assert props["Name"] == {"title": [{"type": "text", "text": {"content": row["title"]}}]}
    assert props["Votes"] == {"number": row["votes"]}
    assert props["Status"] == {"select": {"name": row["status"]}}
    assert props["Tags"] == {"multi_select": [{"name": t} for t in row["tags"]]}
    page = {"properties": {k: {"type": next(iter(v)), **v} for k, v in props.items()}}
    for v in page["properties"].values():
        for r in v.get("title", []) + v.get("rich_text", []):
            r["plain_text"] = r["text"]["content"]
    assert page_to_row(page, "Name") == row


def test_diff_ignores_equal_timestamps_in_another_format():
    old = {"votes": 1, "status_changed": "2026-10-30T08:12:00.000+00:00"}
    new = {"votes": 2, "status_changed": "2026-10-30T08:12:00.000Z"}
    assert diff(old, new) == {"votes": (1, 2)}


def test_notion_minute_rounding_is_not_a_change():
    old = {"votes": 1, "status_changed": "2026-11-09T23:08:00.000+00:00",
           "created": "2019-01-01T12:00:00.000+00:00"}
    new = {"votes": 1, "status_changed": "2026-11-09T23:08:08.241Z",
           "created": "2019-01-01T12:00:30.000Z"}
    assert diff(old, new) == {}


def test_a_later_minute_is_a_change():
    old = {"votes": 1, "status_changed": "2026-11-09T23:08:00.000+00:00"}
    new = {"votes": 1, "status_changed": "2026-11-09T23:09:01.000Z"}
    assert "status_changed" in diff(old, new)


def test_field_change_in_same_minute_is_kept():
    old = {"votes": 1, "status": "planned", "status_changed": "2026-11-09T23:08:00.000+00:00"}
    new = {"votes": 1, "status": "in progress", "status_changed": "2026-11-09T23:08:45.000Z"}
    assert diff(old, new) == {"status": ("planned", "in progress")}
