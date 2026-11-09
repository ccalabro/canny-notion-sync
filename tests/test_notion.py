from cnsync.fakes import FakeNotion
from cnsync.mapping import PROPERTIES
from cnsync.notion import Notion, SchemaError
import pytest


def test_setup_adds_missing_properties():
    fake = FakeNotion()
    n = Notion("tok", fake.database_id, transport=fake)
    missing = n.check_schema(fix=True)
    assert len(missing) == len(PROPERTIES)
    assert n.title_prop == "Name"
    assert n.check_schema(fix=False) == []


def test_wrong_property_type_raises():
    fake = FakeNotion()
    fake.schema["Votes"] = {"id": "v", "name": "Votes", "type": "rich_text", "rich_text": {}}
    n = Notion("tok", fake.database_id, transport=fake)
    with pytest.raises(SchemaError, match="Votes"):
        n.check_schema()


def test_create_and_find_by_key():
    fake = FakeNotion()
    n = Notion("tok", fake.database_id, transport=fake)
    n.check_schema(fix=True)
    from cnsync.mapping import row_to_properties
    row = {
        "title": "Hello", "canny_id": "p1", "status": "open", "votes": 3,
        "board": "Integrations", "category": None, "tags": ["api"], "author": "Alex",
        "created": "2026-01-01T00:00:00.000Z", "status_changed": "2026-01-02T00:00:08.241Z",
        "url": "https://example.com/p", "details": "hi",
    }
    page = n.create_page(row_to_properties(row, n.title_prop))
    found = n.find_by_key("p1")
    assert len(found) == 1 and found[0]["id"] == page["id"]
    # Notion rounds the date to the minute
    stored = found[0]["properties"]["Status changed"]["date"]["start"]
    assert stored.endswith(":00.000+00:00")
