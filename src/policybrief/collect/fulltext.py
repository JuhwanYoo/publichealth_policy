"""기사 본문 보강 (trafilatura). 실패해도 파이프라인은 계속 간다."""

from __future__ import annotations

import logging

import httpx
import trafilatura

from policybrief.models import Item

from .http import USER_AGENT

log = logging.getLogger(__name__)

MAX_CHARS = 3000


def fetch_fulltext(url: str, timeout: float = 10.0) -> str | None:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except (httpx.HTTPError, UnicodeDecodeError) as exc:
        log.debug("fulltext fetch failed %s: %s", url, exc)
        return None
    text = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True)
    if not text:
        return None
    return text[:MAX_CHARS]


def enrich(items: list[Item]) -> int:
    """본문을 받아 summary 보다 길면 교체한다. 보강된 항목 수를 돌려준다."""
    enriched = 0
    for item in items:
        body = fetch_fulltext(item.url)
        if body and len(body) > len(item.summary):
            item.summary = body
            enriched += 1
    return enriched
