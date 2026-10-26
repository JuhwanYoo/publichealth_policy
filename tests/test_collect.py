from policybrief.collect.pubmed import build_term, parse_efetch
from policybrief.collect.rss import parse_feed
from policybrief.models import Source


def test_rss_parse_filters_window_and_cleans(now, fixtures_dir):
    src = Source(id="docdocdoc", name="청년의사", kind="rss", category="media_health",
                 url="https://example.invalid", lookback_hours=36)
    items = parse_feed(src, (fixtures_dir / "docdocdoc.xml").read_bytes(), now)
    assert len(items) == 1
    it = items[0]
    assert it.title == "복지부, 2027년 수가 협상 앞두고 필수의료 보상 강화 방안 논의"
    assert "utm_source" not in it.url
    assert it.summary.startswith("보건복지부가")
    assert it.published is not None


def test_pubmed_parse(fixtures_dir):
    src = Source(id="health_affairs", name="Health Affairs", kind="pubmed", category="journal",
                 lang="en", journal="Health Aff (Millwood)", lookback_hours=336)
    items = parse_efetch(src, (fixtures_dir / "health_affairs.xml").read_bytes())
    assert len(items) == 1
    it = items[0]
    assert it.url == "https://pubmed.ncbi.nlm.nih.gov/41000001/"
    assert it.doi == "10.1377/hlthaff.2026.00001"
    assert "RESULTS: Uncompensated care" in it.summary
    assert it.authors == ["Jiwon Kim", "Sumin Lee"]
    assert it.published.strftime("%Y-%m-%d") == "2026-10-20"


def test_pubmed_term_with_query():
    src = Source(id="nejm", name="NEJM", kind="pubmed", category="journal", journal="N Engl J Med",
                 query="health policy[tiab]")
    assert build_term(src) == '"N Engl J Med"[ta] AND (health policy[tiab])'


def test_html_list_parse(now, fixtures_dir):
    from policybrief.collect.html_list import parse_list
    src = Source(id="mohw_press", name="보건복지부 보도자료", kind="html_list", category="gov",
                 url="https://www.mohw.go.kr/board.es?mid=a10503010100&bid=0027", link_pattern="act=view",
                 lookback_hours=48)
    items = parse_list(src, (fixtures_dir / "mohw_list.html").read_text(encoding="utf-8"), now)
    assert [it.title for it in items] == ["2027년 건강보험료율 결정 관련 건강보험정책심의위원회 개최", "지역의사제 선발 세부 기준 발표"]
    assert items[0].url.startswith("https://mohw.go.kr/board.es?")
    assert "list_no=1500001" in items[0].url
    assert items[1].published.astimezone(now.tzinfo).strftime("%Y-%m-%d") == "2026-10-25"


def test_exclude_filter_drops_pr_titles():
    from policybrief.prefilter import ExcludeFilter
    from policybrief.models import Item
    ef = ExcludeFilter(["수상", "협약", "주가"])
    mk = lambda t: Item(id="x", source_id="s", source_name="S", category="media_health", lang="ko", title=t, url="https://x.test/1")
    assert ef.excluded(mk("고대구로병원 최의경 교수팀, 과학기술우수논문상 수상"))
    assert not ef.excluded(mk("신경외과의사회, 관리급여 재검토 촉구"))


def test_rss_recovers_from_bare_ampersand(now):
    raw = (b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
           b'<item><title>A & B</title><link>https://x.test/1</link>'
           b'<pubDate>Sun, 26 Oct 2026 06:10:00 +0900</pubDate></item></channel></rss>')
    src = Source(id="x", name="X", kind="rss", category="gov", url="https://x.test", lookback_hours=48)
    items = parse_feed(src, raw, now)
    assert len(items) == 1 and items[0].title == "A & B"
