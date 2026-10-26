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


def test_dedupe_merges_gov_items_by_title():
    a = Item(id="a", source_id="mohw", source_name="복지부", category="gov", lang="ko",
             title="의약분업 원칙 위반해 비만치료 자가주사제 원내 조제·판매하는 병·의원 조사한다", url="https://mohw.test/1")
    b = Item(id="b", source_id="gnews", source_name="정책브리핑", category="gov", lang="ko",
             title="의약분업 원칙 위반해 비만치료 자가주사제 원내 조제·판매하는 병·의원 조사한다", url="https://news.google.test/2")
    c = Item(id="c", source_id="yna", source_name="연합", category="media_general", lang="ko",
             title="의약분업 원칙 위반해 비만치료 자가주사제 원내 조제·판매하는 병·의원 조사한다", url="https://yna.test/3")
    out = dedupe([a, b, c])
    assert [i.id for i in out] == ["a", "c"]
