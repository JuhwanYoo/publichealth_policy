"""명령행 진입점.

기본 흐름 (API 키 불필요):
    collect  → data/raw/<date>.json        (GitHub Actions가 매일 실행)
    show     → 항목을 읽기 좋은 텍스트로 출력 (세션에서 사람이/Claude가 읽고 분석)
    render   → data/raw + data/analysis → data/items/<date>.json, reports/<date>.md
    build-site → site/

선택 흐름 (ANTHROPIC_API_KEY 있을 때):
    run      → collect + Claude API 분석 + render 를 한 번에
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from policybrief.analyze import _item_block, make_analyzer
from policybrief.collect import collect_source
from policybrief.collect.fulltext import enrich
from policybrief.collect.html_list import parse_list
from policybrief.collect.pubmed import parse_efetch
from policybrief.collect.rss import parse_feed
from policybrief.config import KEYWORDS_PATH, ROOT, load_sources
from policybrief.models import (
    CATEGORY_LABELS,
    AnalysisFile,
    AnalyzedItem,
    DailyBrief,
    Item,
    ItemAnalysis,
    KeyIssue,
    RawBatch,
    ResearchIdea,
    Source,
    SourceStatus,
    Synthesis,
    Topic,
)
from policybrief.prefilter import ExcludeFilter, KeywordFilter, dedupe, title_key
from policybrief.render import build_site, render_markdown
from policybrief.state import SeenState

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger("policybrief")


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def data(self) -> Path: return self.root / "data"
    @property
    def raw(self) -> Path: return self.data / "raw"
    @property
    def analysis(self) -> Path: return self.data / "analysis"
    @property
    def items(self) -> Path: return self.data / "items"
    @property
    def seen(self) -> Path: return self.data / "seen.json"
    @property
    def reports(self) -> Path: return self.root / "reports"
    @property
    def site(self) -> Path: return self.root / "site"


def paths() -> Paths:
    # 테스트에서 작업 디렉터리를 바꿀 수 있도록 환경변수로 루트를 덮어쓴다.
    return Paths(Path(os.environ.get("POLICYBRIEF_ROOT") or ROOT))


def _today(now: datetime, override: str | None) -> str:
    return override or now.strftime("%Y-%m-%d")


# ── 수집 ────────────────────────────────────────────────────────────────────

def _collect_one(source: Source, now: datetime, fixtures: Path | None) -> list[Item]:
    if fixtures is None:
        return collect_source(source, now)
    # 픽스처 모드: 네트워크 대신 fixtures/<source_id>.xml 을 읽는다. 없으면 빈 결과.
    path = fixtures / f"{source.id}.xml"
    if not path.exists():
        return []
    raw = path.read_bytes()
    if source.kind == "pubmed":
        return parse_efetch(source, raw)
    if source.kind == "html_list":
        return parse_list(source, raw.decode("utf-8"), now)
    return parse_feed(source, raw, now)


def collect_all(args: argparse.Namespace, now: datetime, state: SeenState) -> tuple[list[Item], list[SourceStatus]]:
    """소스 전체를 돌며 수집 → seen 제외 → 키워드 필터 → 중복 제거 → 본문 보강."""
    fixtures = Path(args.fixtures) if args.fixtures else None
    sources = load_sources()
    if args.sources:
        wanted = set(args.sources.split(","))
        sources = [s for s in sources if s.id in wanted]
    keyword_filter = KeywordFilter.from_yaml(KEYWORDS_PATH)
    exclude_filter = ExcludeFilter.from_yaml(KEYWORDS_PATH)

    statuses: list[SourceStatus] = []
    collected: list[Item] = []
    for source in sources:
        try:
            items = _collect_one(source, now, fixtures)
        except Exception as exc:  # 소스 하나가 죽어도 나머지는 계속
            log.warning("[%s] 실패: %s", source.id, exc)
            statuses.append(SourceStatus(source_id=source.id, source_name=source.name, category=source.category,
                                         ok=False, error=f"{type(exc).__name__}: {str(exc)[:120]}"))
            continue
        fetched = len(items)
        items = [it for it in items if it.id not in state or args.ignore_seen]
        new = len(items)
        if source.prefilter == "keywords":
            items = keyword_filter.apply(items)
        if source.category != "journal":
            items = exclude_filter.apply(items)
        statuses.append(SourceStatus(source_id=source.id, source_name=source.name, category=source.category,
                                     ok=True, fetched=fetched, new=new, kept=len(items)))
        log.info("[%s] 수집 %d → 신규 %d → 필터 통과 %d", source.id, fetched, new, len(items))
        collected.extend(items)

    collected = dedupe(collected)
    if args.limit:
        collected = collected[: args.limit]

    if not args.no_fulltext and fixtures is None:
        by_source = {s.id: s for s in sources}
        targets = [it for it in collected if by_source[it.source_id].fetch_fulltext]
        if targets:
            n = enrich(targets)
            log.info("본문 보강 %d/%d", n, len(targets))
    return collected, statuses


def _print_status_summary(statuses: list[SourceStatus]) -> None:
    failed = [s for s in statuses if not s.ok]
    if failed:
        print(f"⚠ 실패 소스 {len(failed)}개: " + ", ".join(f"{s.source_id}({s.error})" for s in failed))


def cmd_collect(args: argparse.Namespace) -> int:
    p = paths()
    now = datetime.now(KST)
    date = _today(now, args.date)
    state = SeenState(p.seen)
    items, statuses = collect_all(args, now, state)

    raw_path = p.raw / f"{date}.json"
    if raw_path.exists() and not args.fresh:
        previous = RawBatch.model_validate_json(raw_path.read_text(encoding="utf-8"))
        known = {it.id for it in items}
        items = [it for it in previous.items if it.id not in known] + items
        log.info("기존 raw와 병합: 총 %d건", len(items))

    batch = RawBatch(date=date, collected_at=now, items=items, source_status=statuses)
    p.raw.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(batch.model_dump_json(indent=2), encoding="utf-8")

    state.mark([it.id for it in items], now)
    state.prune(now)
    state.save()

    print(f"✔ {date}: 수집 {len(items)}건 → {raw_path.relative_to(p.root)}")
    _print_status_summary(statuses)
    print(f"  다음: python -m policybrief show --date {date}")
    return 0


# ── 보기 ────────────────────────────────────────────────────────────────────

def _load_raw(p: Paths, date: str) -> RawBatch:
    raw_path = p.raw / f"{date}.json"
    if not raw_path.exists():
        sys.exit(f"수집 파일이 없습니다: {raw_path}  (먼저 `policybrief collect --date {date}`)")
    return RawBatch.model_validate_json(raw_path.read_text(encoding="utf-8"))


def _week_range(end: str, start: str | None) -> list[str]:
    """주간 브리핑이 합칠 raw 날짜 목록. 기본은 end-6 … end (7일)."""
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    start_d = datetime.strptime(start, "%Y-%m-%d").date() if start else end_d - timedelta(days=6)
    if start_d > end_d:
        sys.exit(f"--from({start_d})이 --week({end_d})보다 늦습니다.")
    return [(start_d + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_d - start_d).days + 1)]


def _load_raw_range(p: Paths, dates: list[str]) -> tuple[RawBatch, list[str], dict[str, int], set[str]]:
    """여러 날의 raw를 하나로 합친다. (합친 배치, 없는 날짜 목록, 날짜별 건수, 중복으로 뺀 id)

    id가 같은 항목은 한 번만 남기고, 정부·공공기관 자료는 기관 원본과 정책브리핑 전재본이 다른 날 들어올 수
    있으므로 제목으로도 합친다. source_status는 마지막으로 존재하는 날의 것을 쓴다.
    """
    items: list[Item] = []
    seen_ids: set[str] = set()
    seen_gov_titles: set[str] = set()
    missing: list[str] = []
    per_day: dict[str, int] = {}
    dropped: set[str] = set()
    last: RawBatch | None = None
    for date in dates:
        raw_path = p.raw / f"{date}.json"
        if not raw_path.exists():
            missing.append(date)
            continue
        batch = RawBatch.model_validate_json(raw_path.read_text(encoding="utf-8"))
        last = batch
        n = 0
        for it in batch.items:
            if it.id in seen_ids:
                dropped.add(it.id)
                continue
            if it.category == "gov":
                key = title_key(it.title)
                if key in seen_gov_titles:
                    dropped.add(it.id)
                    continue
                seen_gov_titles.add(key)
            seen_ids.add(it.id)
            items.append(it)
            n += 1
        per_day[date] = n
    if last is None:
        sys.exit(f"수집 파일이 하나도 없습니다: data/raw/{dates[0]}.json … {dates[-1]}.json")
    merged = RawBatch(date=dates[-1], collected_at=last.collected_at, items=items, source_status=last.source_status)
    return merged, missing, per_day, dropped - seen_ids


def _resolve_batch(p: Paths, args: argparse.Namespace, now: datetime) -> tuple[RawBatch, list[str], dict[str, int], set[str]]:
    """--week 가 있으면 기간을 합친 배치를, 아니면 --date 하루치를 돌려준다.

    반환: (배치, 날짜 목록, 날짜별 건수, 기간 병합 중 중복으로 뺀 id)
    """
    if getattr(args, "week", None):
        dates = _week_range(args.week, getattr(args, "from_date", None))
        batch, missing, per_day, dropped = _load_raw_range(p, dates)
        for d in missing:
            print(f"⚠ {d}: 수집 파일 없음 (건너뜀)", file=sys.stderr)
        return batch, dates, per_day, dropped
    date = _today(now, args.date)
    batch = _load_raw(p, date)
    return batch, [date], {date: len(batch.items)}, set()


def _title_line(it: Item) -> str:
    cat = CATEGORY_LABELS.get(it.category, it.category)
    date = it.published.astimezone(KST).strftime("%m-%d") if it.published else "??-??"
    return f"[id={it.id}] {date} {cat}/{it.source_name}: {it.title}"


def cmd_show(args: argparse.Namespace) -> int:
    p = paths()
    batch, dates, per_day, _ = _resolve_batch(p, args, datetime.now(KST))
    items = batch.items
    if args.category:
        items = [it for it in items if it.category == args.category]
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        items = [it for it in items if it.id in wanted]
        unknown = wanted - {it.id for it in items}
        if unknown:
            print(f"⚠ 없는 id: {', '.join(sorted(unknown))}", file=sys.stderr)
    order = {"journal": 0, "gov": 1, "media_health": 2, "media_general": 3}
    items = sorted(items, key=lambda it: (order.get(it.category, 9), it.source_name, it.title))

    counts: dict[str, int] = {}
    for it in batch.items:
        counts[it.category] = counts.get(it.category, 0) + 1
    label = f"{dates[0]} ~ {dates[-1]} ({len(dates)}일)" if len(dates) > 1 else batch.date
    print(f"# {label} 수집 항목 {len(batch.items)}건 "
          + " · ".join(f"{CATEGORY_LABELS[c]} {n}" for c, n in counts.items()))
    if len(dates) > 1:
        print("# 날짜별: " + " · ".join(f"{d} {per_day.get(d, '없음')}" for d in dates))
    print(f"# 수집 시각 {batch.collected_at.astimezone(KST):%Y-%m-%d %H:%M KST}")
    failed = [s for s in batch.source_status if not s.ok]
    if failed:
        print("# 실패 소스: " + ", ".join(s.source_name for s in failed))
    if args.category or args.ids:
        print(f"# 출력 {len(items)}건")
    print()
    if args.titles:
        for it in items:
            print(_title_line(it))
        return 0
    for it in items:
        print(_item_block(it, max_chars=args.max_chars))
        print()
    return 0


# ── 렌더 ────────────────────────────────────────────────────────────────────

def assemble_brief(batch: RawBatch, analysis: AnalysisFile, now: datetime,
                   period: tuple[str, str] | None = None) -> tuple[DailyBrief, list[str]]:
    """raw + analysis → DailyBrief. 경고 메시지 목록을 함께 돌려준다."""
    warnings: list[str] = []
    by_id = {it.id: it for it in batch.items}
    unknown = [a.id for a in analysis.items if a.id not in by_id]
    if unknown:
        raise ValueError(f"분석 파일에 수집되지 않은 id가 있습니다: {', '.join(unknown[:10])}")

    analyzed_by_id = {a.id: a for a in analysis.items}
    analyzed: list[AnalyzedItem] = []
    missing = 0
    for it in batch.items:
        a = analyzed_by_id.get(it.id)
        if a is None:
            missing += 1
            a = ItemAnalysis(id=it.id, relevant=False, topic=Topic.OTHER, title_ko=it.title)
        analyzed.append(AnalyzedItem(item=it, analysis=a))
    if missing:
        warnings.append(f"분석되지 않은 항목 {missing}건은 relevant=false 로 처리했습니다.")

    valid = {ai.item.id for ai in analyzed if ai.analysis.relevant}
    issues = []
    for k in analysis.synthesis.key_issues:
        ids = [i for i in k.item_ids if i in valid]
        dropped = len(k.item_ids) - len(ids)
        if dropped:
            warnings.append(f"이슈 '{k.title}'에서 알 수 없거나 비관련 id {dropped}개를 제외했습니다.")
        issues.append(KeyIssue(title=k.title, description=k.description, item_ids=ids))
    ideas = [
        ResearchIdea(title=r.title, question=r.question, rationale=r.rationale, approach=r.approach,
                     item_ids=[i for i in r.item_ids if i in valid])
        for r in analysis.synthesis.research_ideas
    ]
    synthesis = Synthesis(
        headline=analysis.synthesis.headline,
        key_issues=issues,
        notable_papers=[i for i in analysis.synthesis.notable_papers if i in valid],
        policy_outlook=analysis.synthesis.policy_outlook,
        global_outlook=analysis.synthesis.global_outlook,
        research_ideas=ideas,
    )
    brief = DailyBrief(
        date=batch.date,
        generated_at=now,
        period_start=period[0] if period else None,
        period_end=period[1] if period else None,
        model=analysis.analyst,
        items=analyzed,
        synthesis=synthesis,
        source_status=batch.source_status,
    )
    return brief, warnings


def _write_brief(p: Paths, brief: DailyBrief) -> None:
    p.items.mkdir(parents=True, exist_ok=True)
    p.reports.mkdir(parents=True, exist_ok=True)
    (p.items / f"{brief.date}.json").write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    (p.reports / f"{brief.date}.md").write_text(render_markdown(brief), encoding="utf-8")


def cmd_render(args: argparse.Namespace) -> int:
    p = paths()
    now = datetime.now(KST)
    batch, dates, _, dropped = _resolve_batch(p, args, now)
    date = batch.date
    period = (dates[0], dates[-1]) if len(dates) > 1 else None
    analysis_path = Path(args.analysis) if args.analysis else p.analysis / f"{date}.json"
    if not analysis_path.exists():
        sys.exit(f"분석 파일이 없습니다: {analysis_path}")
    try:
        analysis = AnalysisFile.model_validate_json(analysis_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        sys.exit(f"분석 파일 형식 오류:\n{exc}")
    dup = [a.id for a in analysis.items if a.id in dropped]
    if dup:
        # 다른 날 raw에 같은 항목(또는 같은 제목의 정부 자료)이 먼저 있어 병합 때 빠진 id — 분석에서도 뺀다.
        analysis.items = [a for a in analysis.items if a.id not in dropped]
        print(f"⚠ 기간 병합에서 중복으로 제외된 id {len(dup)}개는 분석에서 무시했습니다: {', '.join(dup[:5])}")
    try:
        brief, warnings = assemble_brief(batch, analysis, now, period=period)
    except ValueError as exc:
        sys.exit(str(exc))
    _write_brief(p, brief)
    for w in warnings:
        print(f"⚠ {w}")
    label = f"{period[0]} ~ {period[1]}" if period else date
    print(f"✔ {label}: 관련 {len(brief.relevant_items())}/{len(brief.items)}건 → reports/{date}.md, data/items/{date}.json")
    return 0


# ── 전체 실행 (API) ─────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    p = paths()
    now = datetime.now(KST)
    date = _today(now, args.date)
    state = SeenState(p.seen)
    collected, statuses = collect_all(args, now, state)

    analyzer = make_analyzer(no_llm=args.no_llm, model=args.model)
    log.info("분석 시작: %d건 (model=%s)", len(collected), analyzer.model_name or "stub")
    analyzed = analyzer.classify(collected)

    # 같은 날 재실행이면 기존 항목과 합친 뒤 종합을 다시 만든다.
    brief_path = p.items / f"{date}.json"
    if brief_path.exists() and not args.fresh:
        previous = DailyBrief.model_validate_json(brief_path.read_text(encoding="utf-8"))
        known = {ai.item.id for ai in analyzed}
        analyzed = [ai for ai in previous.items if ai.item.id not in known] + analyzed
        log.info("기존 브리핑과 병합: 총 %d건", len(analyzed))

    brief = DailyBrief(
        date=date,
        generated_at=now,
        model=analyzer.model_name,
        items=analyzed,
        synthesis=analyzer.synthesize(analyzed),
        source_status=statuses,
        usage=analyzer.usage(),
    )
    _write_brief(p, brief)

    state.mark([it.id for it in collected], now)
    state.prune(now)
    state.save()

    print(f"✔ {date}: 수집 {len(collected)}건, 관련 {len(brief.relevant_items())}건 → reports/{date}.md")
    _print_status_summary(statuses)
    if brief.usage:
        print(f"  토큰: {json.dumps(brief.usage)}")
    return 0


# ── 기타 ────────────────────────────────────────────────────────────────────

def _debug_snippet(source: Source) -> str:
    """실패하거나 비어 있는 소스의 응답 앞부분을 보여준다 (URL 교정용)."""
    if source.kind == "pubmed" or not source.url:
        return ""
    from policybrief.collect.http import get_bytes
    try:
        raw = get_bytes(source.url)
    except Exception as exc:
        return f"    [debug] fetch 실패: {type(exc).__name__}: {str(exc)[:160]}"
    text = raw[:6000].decode("utf-8", errors="replace")
    lines = [f"    [debug] {len(raw)} bytes, 시작: {text[:300]!r}"]
    import re as _re
    links = _re.findall(r'href=["\']([^"\']*(?:view|rss|xml)[^"\']*)', text)[:8]
    if links:
        lines.append("    [debug] 링크 예시: " + " | ".join(links))
    return "\n".join(lines)


def cmd_check_feeds(args: argparse.Namespace) -> int:
    now = datetime.now(KST)
    sources = load_sources(include_disabled=args.include_disabled)
    if args.sources:
        wanted = set(args.sources.split(","))
        sources = [s for s in sources if s.id in wanted]
    bad = 0
    if args.debug:
        os.environ["POLICYBRIEF_TRACE"] = "1"
    print(f"{'소스':<28} {'kind':<7} {'상태':<6} {'건수':>4}  비고")
    for source in sources:
        try:
            items = collect_source(source, now)
            if items:
                newest = max((it.published for it in items if it.published), default=None)
                note = f"최신 {newest:%Y-%m-%d}" if newest else "날짜 없음"
            else:
                note = "lookback 창 안에 항목 없음"
            state = "OK" if source.enabled else "OFF"
            print(f"{source.name:<28} {source.kind:<7} {state:<6} {len(items):>4}  {note}")
            if args.debug and not items:
                print(_debug_snippet(source))
        except Exception as exc:
            bad += 1
            print(f"{source.name:<28} {source.kind:<7} {'FAIL':<6} {'-':>4}  {type(exc).__name__}: {str(exc)[:80]}")
            if args.debug:
                print(_debug_snippet(source))
    print(f"\n{len(sources) - bad}/{len(sources)} 정상")
    return 1 if bad and args.strict else 0


def cmd_probe(args: argparse.Namespace) -> int:
    """URL을 받아 제목과 게시판 링크 후보를 보여준다 (RSS/목록 주소 찾기용)."""
    import re as _re
    from policybrief.collect.http import get_bytes

    keyword = _re.compile(args.grep, _re.I) if args.grep else None
    for url in args.urls:
        print(f"=== {url}")
        try:
            raw = get_bytes(url)
        except Exception as exc:
            print(f"    fetch 실패: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        text = raw.decode("utf-8", errors="replace")
        title = _re.search(r"<title[^>]*>(.*?)</title>", text, _re.S | _re.I)
        print(f"    {len(raw)} bytes · title: {(title.group(1).strip() if title else '-')[:120]}")
        rss = _re.findall(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', text, _re.I)
        for tag in rss[:5]:
            print(f"    <link rss>: {tag[:200]}")
        anchors = _re.findall(r"<a\b([^>]*)>(.*?)</a>", text, _re.S | _re.I)
        shown = 0
        for attrs, inner in anchors:
            label = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", inner)).strip()
            hay = attrs + " " + label
            if keyword and not keyword.search(hay):
                continue
            if not keyword and len(label) < 8:
                continue
            print(f"    - {label[:70]!r} :: {_re.sub(r'\\s+', ' ', attrs)[:220]}")
            shown += 1
            if shown >= args.limit:
                break
        if shown == 0:
            print(f"    (조건에 맞는 링크 없음; 전체 anchor {len(anchors)}개)")
            m = _re.search(r"list_no|brdBltNo|brdScnBltNo|nttId|boardId", text)
            if m:
                start = max(0, m.start() - 300)
                print("    문맥: " + _re.sub(r"\s+", " ", text[start:m.start() + 300])[:600])
    return 0


def cmd_build_site(args: argparse.Namespace) -> int:
    p = paths()
    out = Path(args.out) if args.out else p.site
    build_site(p.items, out)
    n = len(list(p.items.glob("*.json")))
    print(f"✔ 사이트 생성: {out} ({n}일치)")
    return 0


def _add_period_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", help="일간: 브리핑 날짜 YYYY-MM-DD (기본: 오늘 KST)")
    parser.add_argument("--week", metavar="END", help="주간: 마지막 날짜(월요일). 기본 7일(END-6 … END)의 raw를 합친다")
    parser.add_argument("--from", dest="from_date", metavar="START", help="주간 시작 날짜 (기본: END-6)")


def _add_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", help="브리핑 날짜 YYYY-MM-DD (기본: 오늘 KST)")
    parser.add_argument("--sources", help="실행할 소스 id (쉼표 구분)")
    parser.add_argument("--fixtures", help="네트워크 대신 이 디렉터리의 <source_id>.xml 사용")
    parser.add_argument("--no-fulltext", action="store_true", help="기사 본문 보강 생략")
    parser.add_argument("--limit", type=int, help="항목 수 상한")
    parser.add_argument("--ignore-seen", action="store_true", help="seen.json 무시 (재처리)")
    parser.add_argument("--fresh", action="store_true", help="같은 날 기존 결과와 병합하지 않고 덮어쓰기")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="policybrief", description="보건의료정책 이슈 자동 브리핑")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_col = sub.add_parser("collect", help="수집만 → data/raw/<date>.json")
    _add_collect_args(p_col)
    p_col.set_defaults(func=cmd_collect)

    p_show = sub.add_parser("show", help="수집 항목을 읽기 좋게 출력")
    _add_period_args(p_show)
    p_show.add_argument("--category", choices=list(CATEGORY_LABELS))
    p_show.add_argument("--ids", help="이 id들만 출력 (쉼표 구분)")
    p_show.add_argument("--titles", action="store_true", help="본문 없이 한 줄씩 제목만 (1차 선별용)")
    p_show.add_argument("--max-chars", type=int, default=600, help="항목당 본문 출력 상한 (기본 600자)")
    p_show.set_defaults(func=cmd_show)

    p_ren = sub.add_parser("render", help="raw + analysis → 리포트")
    _add_period_args(p_ren)
    p_ren.add_argument("--analysis", help="분석 파일 경로 (기본: data/analysis/<date>.json)")
    p_ren.set_defaults(func=cmd_render)

    p_run = sub.add_parser("run", help="수집 → Claude API 분석 → 리포트 (ANTHROPIC_API_KEY 필요)")
    _add_collect_args(p_run)
    p_run.add_argument("--no-llm", action="store_true", help="Claude 호출 없이 스텁 분석기로 실행")
    p_run.add_argument("--model", help="Claude 모델 ID (기본: POLICYBRIEF_MODEL 또는 claude-opus-5-5)")
    p_run.set_defaults(func=cmd_run)

    p_chk = sub.add_parser("check-feeds", help="모든 소스 접근 가능 여부 점검")
    p_chk.add_argument("--include-disabled", action="store_true")
    p_chk.add_argument("--sources", help="점검할 소스 id (쉼표 구분)")
    p_chk.add_argument("--debug", action="store_true", help="실패/0건 소스의 응답 앞부분 출력")
    p_chk.add_argument("--strict", action="store_true", help="실패 소스가 있으면 종료 코드 1")
    p_chk.set_defaults(func=cmd_check_feeds)

    p_probe = sub.add_parser("probe", help="페이지의 제목과 게시판 링크 후보 출력 (주소 찾기용)")
    p_probe.add_argument("urls", nargs="+")
    p_probe.add_argument("--grep", help="링크 속성/텍스트에서 찾을 정규식 (예: 'bid=|rss|보도')")
    p_probe.add_argument("--limit", type=int, default=25)
    p_probe.set_defaults(func=cmd_probe)

    p_site = sub.add_parser("build-site", help="data/items/*.json 으로 정적 사이트 생성")
    p_site.add_argument("--out")
    p_site.set_defaults(func=cmd_build_site)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.WARNING)
    sys.exit(args.func(args))
