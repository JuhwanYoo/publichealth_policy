"""RSS/Atom 피드 수집 (feedparser)."""

from __future__ import annotations

import calendar
import html
import re
from datetime import datetime, timedelta, timezone

import feedparser

from policybrief.models import Item, Source
from policybrief.prefilter import make_item_id, normalize_url

from .http import get_bytes

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """HTML 태그·엔티티·공백을 정리한다."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def _entry_summary(entry) -> str:
    if entry.get("content"):
        for block in entry["content"]:
            if block.get("value"):
                return clean_text(block["value"])
    return clean_text(entry.get("summary") or entry.get("description"))


def parse_feed(source: Source, raw: bytes, now: datetime) -> list[Item]:
    """피드 바이트를 Item 목록으로 변환한다 (lookback 창 밖은 제외)."""
    feed = feedparser.parse(raw)
    if feed.get("bozo") and not feed.entries:
        raise ValueError(f"feed parse error: {feed.get('bozo_exception')}")

    cutoff = now - timedelta(hours=source.lookback_hours)
    items: list[Item] = []
    for entry in feed.entries:
        link = entry.get("link")
        title = clean_text(entry.get("title"))
        if not link or not title:
            continue
        published = _entry_datetime(entry)
        # 발행 시각이 없는 항목은 현재 시각으로 간주하고, 창 밖 항목은 버린다.
        if published is not None and published < cutoff:
            continue
        url = normalize_url(link)
        items.append(
            Item(
                id=make_item_id(url),
                source_id=source.id,
                source_name=source.name,
                category=source.category,
                lang=source.lang,
                title=title,
                url=url,
                published=published,
                summary=_entry_summary(entry),
                authors=[a.get("name", "") for a in entry.get("authors", []) if a.get("name")],
                journal=source.name if source.category == "journal" else None,
            )
        )
        if len(items) >= source.max_items:
            break
    return items


def collect_rss(source: Source, now: datetime) -> list[Item]:
    if not source.url:
        raise ValueError(f"source {source.id}: rss source needs url")
    raw = get_bytes(source.url)
    return parse_feed(source, raw, now)
