from datetime import timedelta

from policybrief.models import Item
from policybrief.prefilter import KeywordFilter, dedupe, make_item_id, normalize_url
from policybrief.state import SeenState


def _item(title, url="https://x.test/a", summary=""):
    return Item(id=make_item_id(url), source_id="s", source_name="S", category="media_general",
                lang="ko", title=title, url=url, summary=summary)


def test_normalize_url_strips_tracking_and_www():
    a = normalize_url("https://www.Example.com/news/1/?utm_source=rss&id=3")
    b = normalize_url("https://example.com/news/1?id=3")
    assert a == b
    assert make_item_id(a) == make_item_id(b)


def test_keyword_filter_matches_title_or_summary():
    kf = KeywordFilter(["건강보험", "health policy"])
    assert kf.matches(_item("건강보험료 인상 논의"))
    assert kf.matches(_item("아무 제목", summary="This is about Health Policy."))
    assert not kf.matches(_item("교통사고 소식"))


def test_dedupe_keeps_first():
    items = [_item("a", "https://x.test/1"), _item("b", "https://x.test/1?utm_medium=x"), _item("c", "https://x.test/2")]
    assert [i.title for i in dedupe(items)] == ["a", "c"]


def test_seen_state_roundtrip_and_prune(tmp_path, now):
    path = tmp_path / "seen.json"
    st = SeenState(path)
    st.mark(["old"], now - timedelta(days=90))
    st.mark(["new"], now)
    st.save()

    st2 = SeenState(path)
    assert "old" in st2 and "new" in st2
    st2.prune(now)
    assert "old" not in st2 and "new" in st2
