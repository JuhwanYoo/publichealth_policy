"""DailyBrief → Markdown 리포트 및 정적 사이트."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from policybrief.models import CATEGORY_LABELS, AnalyzedItem, DailyBrief, Topic

TEMPLATES = Path(__file__).parent / "templates"

TOPIC_SLUGS: dict[Topic, str] = {
    Topic.INSURANCE: "insurance",
    Topic.WORKFORCE: "workforce",
    Topic.DELIVERY: "delivery",
    Topic.INFECTIOUS: "infectious",
    Topic.PHARMA: "pharma",
    Topic.DIGITAL: "digital",
    Topic.FINANCE: "finance",
    Topic.LTC: "ltc",
    Topic.MENTAL: "mental",
    Topic.GOVERNANCE: "governance",
    Topic.GLOBAL: "global",
    Topic.OTHER: "other",
}

SITE_TITLE = "보건의료정책 데일리 브리핑"
KST = ZoneInfo("Asia/Seoul")


def _env(autoescape: bool) -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]) if autoescape else False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["date"] = lambda dt, fmt="%Y-%m-%d": dt.astimezone(KST).strftime(fmt) if dt else "날짜 불명"
    env.filters["category_label"] = lambda c: CATEGORY_LABELS.get(c, c)
    env.filters["topic_slug"] = lambda t: TOPIC_SLUGS[Topic(t)]
    env.filters["stars"] = lambda n: "●" * n + "○" * (5 - n)
    env.globals["site_title"] = SITE_TITLE
    return env


def group_by_topic(items: list[AnalyzedItem]) -> list[tuple[Topic, list[AnalyzedItem]]]:
    """토픽별 묶음. 항목이 많은 토픽부터, '기타'는 항상 마지막."""
    buckets: dict[Topic, list[AnalyzedItem]] = defaultdict(list)
    for ai in items:
        buckets[ai.analysis.topic].append(ai)
    ordered = sorted(
        buckets.items(),
        key=lambda kv: (kv[0] == Topic.OTHER, -len(kv[1])),
    )
    return ordered


def _context(brief: DailyBrief) -> dict:
    relevant = brief.relevant_items()
    by_id = {ai.item.id: ai for ai in relevant}
    papers = [by_id[i] for i in brief.synthesis.notable_papers if i in by_id]
    issues = [
        {"title": k.title, "description": k.description, "linked": [by_id[i] for i in k.item_ids if i in by_id]}
        for k in brief.synthesis.key_issues
    ]
    return {
        "brief": brief,
        "relevant": relevant,
        "topics": group_by_topic(relevant),
        "issues": issues,
        "papers": papers,
        "counts": {
            "total": len(brief.items),
            "relevant": len(relevant),
            "journal": sum(1 for ai in relevant if ai.item.category == "journal"),
            "media": sum(1 for ai in relevant if ai.item.category.startswith("media")),
            "gov": sum(1 for ai in relevant if ai.item.category == "gov"),
        },
    }


def render_markdown(brief: DailyBrief) -> str:
    return _env(autoescape=False).get_template("report.md.j2").render(**_context(brief))


# ── 사이트 ──────────────────────────────────────────────────────────────────

def load_briefs(items_dir: Path) -> list[DailyBrief]:
    briefs = []
    for path in sorted(items_dir.glob("*.json")):
        briefs.append(DailyBrief.model_validate_json(path.read_text(encoding="utf-8")))
    return sorted(briefs, key=lambda b: b.date, reverse=True)


def build_site(items_dir: Path, out_dir: Path, topic_window_days: int = 30) -> None:
    briefs = load_briefs(items_dir)
    env = _env(autoescape=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "archive").mkdir(exist_ok=True)
    (out_dir / "topics").mkdir(exist_ok=True)
    for asset in ("style.css", "app.js"):
        shutil.copy(TEMPLATES / asset, out_dir / asset)

    dates = [b.date for b in briefs]
    day_tpl = env.get_template("day.html.j2")
    for brief in briefs:
        html = day_tpl.render(**_context(brief), dates=dates, root="../", is_index=False)
        (out_dir / "archive" / f"{brief.date}.html").write_text(html, encoding="utf-8")

    if briefs:
        latest = briefs[0]
        html = day_tpl.render(**_context(latest), dates=dates, root="", is_index=True)
    else:
        html = env.get_template("empty.html.j2").render(root="", dates=[])
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # 토픽별 페이지: 최근 N일 항목을 모은다.
    recent = briefs[:topic_window_days]
    topic_items: dict[Topic, list[tuple[str, AnalyzedItem]]] = defaultdict(list)
    for b in recent:
        for ai in b.relevant_items():
            topic_items[ai.analysis.topic].append((b.date, ai))
    topic_tpl = env.get_template("topic.html.j2")
    for topic in Topic:
        rows = topic_items.get(topic, [])
        html = topic_tpl.render(topic=topic, rows=rows, dates=dates, root="../", window=topic_window_days)
        (out_dir / "topics" / f"{TOPIC_SLUGS[topic]}.html").write_text(html, encoding="utf-8")

    # 클라이언트 검색 인덱스 (최근 90일)
    index = []
    for b in briefs[:90]:
        for ai in b.relevant_items():
            index.append(
                {
                    "date": b.date,
                    "title": ai.analysis.title_ko or ai.item.title,
                    "orig": ai.item.title,
                    "summary": ai.analysis.summary_ko,
                    "url": ai.item.url,
                    "source": ai.item.source_name,
                    "topic": ai.analysis.topic.value,
                    "tags": ai.analysis.tags,
                }
            )
    (out_dir / "search.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
