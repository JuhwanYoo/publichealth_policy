from datetime import datetime
from zoneinfo import ZoneInfo

from policybrief.analyze import StubAnalyzer
from policybrief.models import DailyBrief, Item, SourceStatus, Synthesis, KeyIssue
from policybrief.render import build_site, render_markdown


def _brief():
    items = [
        Item(id="aaa", source_id="yna", source_name="연합뉴스", category="media_general", lang="ko",
             title="의대 정원 논의 재개", url="https://yna.test/1", summary="정부가 논의를 재개한다.",
             published=datetime(2026, 10, 26, 5, tzinfo=ZoneInfo("Asia/Seoul"))),
        Item(id="bbb", source_id="ha", source_name="Health Affairs", category="journal", lang="en",
             title="Medicaid Expansion And Hospital Finances", url="https://pubmed.test/2", summary="Abstract."),
    ]
    analyzed = StubAnalyzer().classify(items)
    analyzed[1].analysis.title_ko = "메디케이드 확대와 병원 재정"
    return DailyBrief(
        date="2026-10-26",
        generated_at=datetime(2026, 10, 26, 7, 5, tzinfo=ZoneInfo("Asia/Seoul")),
        model=None,
        items=analyzed,
        synthesis=Synthesis(headline="테스트 헤드라인",
                            key_issues=[KeyIssue(title="의대 정원", description="설명", item_ids=["aaa", "zzz"])],
                            notable_papers=["bbb"], policy_outlook="전망"),
        source_status=[SourceStatus(source_id="yna", source_name="연합뉴스", category="media_general", ok=True, fetched=2, new=2, kept=1),
                       SourceStatus(source_id="x", source_name="죽은 피드", category="gov", ok=False, error="HTTPStatusError: 404")],
    )


def test_render_markdown_contains_sections():
    md = render_markdown(_brief())
    assert "# 보건의료정책 데일리 브리핑 — 2026-10-26" in md
    assert "## 오늘의 핵심 이슈" in md and "의대 정원" in md
    assert "## 주목할 논문" in md and "메디케이드 확대와 병원 재정" in md
    assert "_Medicaid Expansion And Hospital Finances_" in md
    assert "❌ HTTPStatusError: 404" in md


def test_build_site(tmp_path):
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    (items_dir / "2026-10-26.json").write_text(_brief().model_dump_json(), encoding="utf-8")
    out = tmp_path / "site"
    build_site(items_dir, out)
    assert (out / "index.html").exists()
    assert (out / "archive" / "2026-10-26.html").exists()
    assert (out / "topics" / "other.html").exists()
    assert (out / "search.json").exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "테스트 헤드라인" in html and "style.css" in html
    assert "의대 정원 논의 재개" in (out / "search.json").read_text(encoding="utf-8")
