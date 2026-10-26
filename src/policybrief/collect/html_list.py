"""RSS가 없는 게시판(정부 보도자료 등)을 목록 페이지에서 직접 긁는다.

설정 예 (config/sources.yaml):
    kind: html_list
    url: https://www.mohw.go.kr/board.es?mid=a10503010100&bid=0027
    link_pattern: 'act=view'          # 이 문자열이 들어간 <a href>만 기사 링크로 본다
한 행(<tr> 또는 <li>) 안에서 링크의 텍스트를 제목으로, 같은 행의 YYYY-MM-DD/YYYY.MM.DD 를 날짜로 읽는다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from policybrief.models import Item, Source
from policybrief.prefilter import make_item_id, normalize_url

from .http import get_bytes

KST = ZoneInfo("Asia/Seoul")
_ROW_RE = re.compile(r"<(tr|li)\b[^>]*>(.*?)</\1>", re.S | re.I)
_LINK_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
_DATE_RE = re.compile(r"(20\d{2})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(html: str) -> str:
    return _WS_RE.sub(" ", unexcape_safe(html)).strip()


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
    items: list[Item] = []
    seen: set[str] = set()
    for _, row in _ROW_RE.findall(html):
        link = None
        for href, inner in _LINK_RE.findall(row):
            if pattern in href:
                title = _text(inner)
                if title:
                    link = (href, title)
                    break
        if link is None:
            continue
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
        if published is not None and published < cutoff:
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
    if not items and "<a" not in html:
        raise ValueError("목록 페이지에서 링크를 찾지 못했습니다 (차단 또는 구조 변경)")
    return items


def collect_html_list(source: Source, now: datetime) -> list[Item]:
    if not source.url:
        raise ValueError(f"source {source.id}: html_list source needs url")
    html = _decode(get_bytes(source.url))
    return parse_list(source, html, now)
