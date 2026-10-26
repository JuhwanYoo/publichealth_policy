"""소스별 수집기. 각 수집기는 `(Source, now) -> list[Item]`을 돌려주고, 실패는 예외로 알린다."""

from __future__ import annotations

from datetime import datetime

from policybrief.models import Item, Source

from .pubmed import collect_pubmed
from .rss import collect_rss


def collect_source(source: Source, now: datetime) -> list[Item]:
    if source.kind == "rss":
        return collect_rss(source, now)
    if source.kind == "pubmed":
        return collect_pubmed(source, now)
    raise ValueError(f"unknown source kind: {source.kind}")


__all__ = ["collect_source", "collect_rss", "collect_pubmed"]
