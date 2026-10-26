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
