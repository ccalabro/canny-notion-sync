from cnsync.canny import Canny
from cnsync.fakes import FakeCanny
from cnsync.http import ApiError
import pytest


def test_iter_posts_pages_with_skip(posts, boards):
    fake = FakeCanny(posts, boards, api_key="k")
    client = Canny("k", transport=fake)
    got = list(client.iter_posts(limit=7))
    assert len(got) == len(posts)
    assert [c for c in fake.calls if c.endswith("/posts/list")] == [
        "POST /api/v1/posts/list",
        "POST /api/v1/posts/list",
        "POST /api/v1/posts/list",
    ]


def test_get_post_and_boards(posts, boards):
    fake = FakeCanny(posts, boards, api_key="k")
    client = Canny("k", transport=fake)
    assert client.get_post(posts[0]["id"])["title"] == "Notion"
    assert {b["name"] for b in client.list_boards()} == {"Integrations", "Bug Reports"}


def test_wrong_api_key_raises(posts, boards):
    fake = FakeCanny(posts, boards, api_key="k")
    client = Canny("wrong", transport=fake)
    with pytest.raises(ApiError) as e:
        client.list_boards()
    assert e.value.status == 401


def test_missing_post_is_404(posts, boards):
    fake = FakeCanny(posts, boards, api_key="k")
    client = Canny("k", transport=fake)
    with pytest.raises(ApiError) as e:
        client.get_post("nope")
    assert e.value.status == 404
