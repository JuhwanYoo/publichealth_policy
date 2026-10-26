"""명령행 진입점: run / check-feeds / build-site."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from policybrief.analyze import make_analyzer
from policybrief.collect import collect_source
from policybrief.collect.fulltext import enrich
from policybrief.collect.pubmed import parse_efetch
from policybrief.collect.rss import parse_feed
from policybrief.config import KEYWORDS_PATH, ROOT, load_sources
from policybrief.models import DailyBrief, Item, Source, SourceStatus
from policybrief.prefilter import KeywordFilter, dedupe
from policybrief.render import build_site, render_markdown
from policybrief.state import SeenState

KST = ZoneInfo("Asia/Seoul")
DATA_DIR = ROOT / "data"
ITEMS_DIR = DATA_DIR / "items"
REPORTS_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"

log = logging.getLogger("policybrief")


def _collect(source: Source, now: datetime, fixtures: Path | None) -> list[Item]:
    if fixtures is None:
        return collect_source(source, now)
    # 픽스처 모드: 네트워크 대신 fixtures/<source_id>.xml 을 읽는다. 없으면 빈 결과.
    path = fixtures / f"{source.id}.xml"
    if not path.exists():
        return []
    raw = path.read_bytes()
    return parse_efetch(source, raw) if source.kind == "pubmed" else parse_feed(source, raw, now)


def cmd_run(args: argparse.Namespace) -> int:
    now = datetime.now(KST)
    date = args.date or now.strftime("%Y-%m-%d")
    fixtures = Path(args.fixtures) if args.fixtures else None
    sources = load_sources()
    if args.sources:
        wanted = set(args.sources.split(","))
        sources = [s for s in sources if s.id in wanted]
    keyword_filter = KeywordFilter.from_yaml(KEYWORDS_PATH)
    state = SeenState(DATA_DIR / "seen.json")

    statuses: list[SourceStatus] = []
    collected: list[Item] = []
    for source in sources:
        try:
            items = _collect(source, now, fixtures)
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

    analyzer = make_analyzer(no_llm=args.no_llm, model=args.model)
    log.info("분석 시작: %d건 (model=%s)", len(collected), analyzer.model_name or "stub")
    analyzed = analyzer.classify(collected)

    # 같은 날 재실행이면 기존 항목과 합친 뒤 종합을 다시 만든다.
    brief_path = ITEMS_DIR / f"{date}.json"
    if brief_path.exists() and not args.fresh:
        previous = DailyBrief.model_validate_json(brief_path.read_text(encoding="utf-8"))
        known = {ai.item.id for ai in analyzed}
        analyzed = [ai for ai in previous.items if ai.item.id not in known] + analyzed
        log.info("기존 브리핑과 병합: 총 %d건", len(analyzed))

    synthesis = analyzer.synthesize(analyzed)
    brief = DailyBrief(
        date=date,
        generated_at=now,
        model=analyzer.model_name,
        items=analyzed,
        synthesis=synthesis,
        source_status=statuses,
        usage=analyzer.usage(),
    )

    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    (REPORTS_DIR / f"{date}.md").write_text(render_markdown(brief), encoding="utf-8")

    state.mark([it.id for it in collected], now)
    state.prune(now)
    state.save()

    relevant = len(brief.relevant_items())
    failed = [s for s in statuses if not s.ok]
    print(f"✔ {date}: 수집 {len(collected)}건, 관련 {relevant}건 → reports/{date}.md")
    if failed:
        print(f"⚠ 실패 소스 {len(failed)}개: " + ", ".join(s.source_id for s in failed))
    if brief.usage:
        print(f"  토큰: {json.dumps(brief.usage)}")
    return 0


def cmd_check_feeds(args: argparse.Namespace) -> int:
    now = datetime.now(KST)
    sources = load_sources(include_disabled=args.include_disabled)
    bad = 0
    print(f"{'소스':<28} {'kind':<7} {'상태':<6} {'건수':>4}  비고")
    for source in sources:
        try:
            items = collect_source(source, now)
            note = ""
            if items:
                newest = max((it.published for it in items if it.published), default=None)
                note = f"최신 {newest:%Y-%m-%d}" if newest else "날짜 없음"
            else:
                note = "lookback 창 안에 항목 없음"
            state = "OK" if source.enabled else "OFF"
            print(f"{source.name:<28} {source.kind:<7} {state:<6} {len(items):>4}  {note}")
        except Exception as exc:
            bad += 1
            print(f"{source.name:<28} {source.kind:<7} {'FAIL':<6} {'-':>4}  {type(exc).__name__}: {str(exc)[:80]}")
    print(f"\n{len(sources) - bad}/{len(sources)} 정상")
    return 1 if bad and args.strict else 0


def cmd_build_site(args: argparse.Namespace) -> int:
    out = Path(args.out)
    build_site(ITEMS_DIR, out)
    n = len(list(ITEMS_DIR.glob("*.json")))
    print(f"✔ 사이트 생성: {out} ({n}일치)")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="policybrief", description="보건의료정책 이슈 자동 브리핑")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="수집 → 분석 → 리포트 생성")
    p_run.add_argument("--no-llm", action="store_true", help="Claude 호출 없이 스텁 분석기로 실행")
    p_run.add_argument("--model", help="Claude 모델 ID (기본: POLICYBRIEF_MODEL 또는 claude-opus-5-5)")
    p_run.add_argument("--date", help="브리핑 날짜 YYYY-MM-DD (기본: 오늘 KST)")
    p_run.add_argument("--sources", help="실행할 소스 id (쉼표 구분)")
    p_run.add_argument("--fixtures", help="네트워크 대신 이 디렉터리의 <source_id>.xml 사용")
    p_run.add_argument("--no-fulltext", action="store_true", help="기사 본문 보강 생략")
    p_run.add_argument("--limit", type=int, help="분석 항목 수 상한 (비용 제어/테스트용)")
    p_run.add_argument("--ignore-seen", action="store_true", help="seen.json 무시 (재처리)")
    p_run.add_argument("--fresh", action="store_true", help="같은 날 기존 브리핑과 병합하지 않고 덮어쓰기")
    p_run.set_defaults(func=cmd_run)

    p_chk = sub.add_parser("check-feeds", help="모든 소스 접근 가능 여부 점검")
    p_chk.add_argument("--include-disabled", action="store_true")
    p_chk.add_argument("--strict", action="store_true", help="실패 소스가 있으면 종료 코드 1")
    p_chk.set_defaults(func=cmd_check_feeds)

    p_site = sub.add_parser("build-site", help="data/items/*.json 으로 정적 사이트 생성")
    p_site.add_argument("--out", default=str(SITE_DIR))
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
