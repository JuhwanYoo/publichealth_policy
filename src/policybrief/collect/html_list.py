"""RSS가 없는 게시판(정부 보도자료 등)을 목록 페이지에서 직접 긁는다.

설정 예 (config/sources.yaml):
    kind: html_list
    url: https://www.mohw.go.kr/board.es?mid=a10503010100&bid=0027
    link_pattern: 'act=view'          # 이 문자열이 들어간 <a href>만 기사 링크로 본다
한 행(<tr> 또는 <li>) 안에서 링크의 텍스트를 제목으로, 같은 행의 YYYY-MM-DD/YYYY.MM.DD 를 날짜로 읽는다.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from policybrief.models import Item, Source
from policybrief.prefilter import make_item_id, normalize_url

from .http import get_bytes

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)
_ROW_RE = re.compile(r"<(tr|li)\b[^>]*>(.*?)</\1>", re.S | re.I)
_LINK_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
_DATE_RE = re.compile(r"(20\d{2})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(html: str) -> str:
    return _WS_RE.sub(" ", unexcape_safe(html)).strip()


def _clean_title(text: str) -> str:
    """일부 사이트는 제목 anchor 안에 BOM(U+FEFF)으로 구분된 요약문까지 넣는다. 첫 조각만 제목으로 쓴다."""
    text = text.replace("\u200b", "")
    if "\ufeff" in text:
        text = text.split("\ufeff", 1)[0]
    return text.strip()


def unexcape_safe(html: str) -> str:
    return unescape(_TAG_RE.sub(" ", html))


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_list(source: Source, html: str, now: datetime) -> list[Item]:
    pattern = source.link_pattern or "view"
    cutoff = now - timedelta(hours=source.lookback_hours)
    trace = bool(os.environ.get("POLICYBRIEF_TRACE"))
    items: list[Item] = []
    seen: set[str] = set()
    rows = _ROW_RE.findall(html)
    n_link = n_old = 0
    for _, row in rows:
        # 같은 행에 같은 글로 가는 링크가 여럿이면(제목·부제·요약) 가장 짧은 텍스트를 제목으로 쓴다.
        candidates: dict[str, str] = {}
        for href, inner in _LINK_RE.findall(row):
            if pattern not in href:
                continue
            title = _clean_title(_text(inner))
            if len(title) < 4:
                continue
            if href not in candidates or len(title) < len(candidates[href]):
                candidates[href] = title
        if not candidates:
            continue
        href, title = next(iter(candidates.items()))
        link = (href, title)
        n_link += 1
        href, title = link
        url = normalize_url(urljoin(source.url or "", unescape(href)))
        if url in seen:
            continue
        seen.add(url)
        published = None
        m = _DATE_RE.search(_text(row))
        if m:
            try:
                published = datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=KST).astimezone(timezone.utc)
            except ValueError:
                published = None
        if trace and n_link <= 3:
            print(f"    [trace] row link: {title[:40]!r} date={m.group(0) if m else None} href={href[:80]}")
        if published is not None and published < cutoff:
            n_old += 1
            continue
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
                summary="",
            )
        )
        if len(items) >= source.max_items:
            break
    if trace:
        total_links = sum(1 for h, _ in _LINK_RE.findall(html) if pattern in h)
        print(f"    [trace] rows={len(rows)} row-links={n_link} old={n_old} kept={len(items)} "
              f"links-with-pattern(total)={total_links} cutoff={cutoff:%Y-%m-%d %H:%M}")
    if not items:
        items = _parse_flat(source, html, cutoff, seen)
        if trace:
            print(f"    [trace] flat fallback kept={len(items)}")
    if not items and "<a" not in html:
        raise ValueError("목록 페이지에서 링크를 찾지 못했습니다 (차단 또는 구조 변경)")
    return items


def _parse_flat(source: Source, html: str, cutoff: datetime, seen: set[str]) -> list[Item]:
    """행 구조를 못 찾았을 때: 패턴에 맞는 링크를 모두 모으고 날짜는 링크 뒤 400자 안에서 찾는다."""
    pattern = source.link_pattern or "view"
    items: list[Item] = []
    for m in _LINK_RE.finditer(html):
        href, inner = m.group(1), m.group(2)
        if pattern not in href:
            continue
        title = _clean_title(_text(inner))
        if not title or len(title) < 6:
            continue
        url = normalize_url(urljoin(source.url or "", unescape(href)))
        if url in seen:
            continue
        seen.add(url)
        published = None
        dm = _DATE_RE.search(_text(html[m.end(): m.end() + 400]))
        if dm:
            try:
                published = datetime(int(dm[1]), int(dm[2]), int(dm[3]), tzinfo=KST).astimezone(timezone.utc)
            except ValueError:
                published = None
        if published is not None and published < cutoff:
            continue
        items.append(Item(id=make_item_id(url), source_id=source.id, source_name=source.name, category=source.category,
                          lang=source.lang, title=title, url=url, published=published, summary=""))
        if len(items) >= source.max_items:
            break
    return items


def collect_html_list(source: Source, now: datetime) -> list[Item]:
    if not source.url:
        raise ValueError(f"source {source.id}: html_list source needs url")
    html = _decode(get_bytes(source.url))
    return parse_list(source, html, now)
