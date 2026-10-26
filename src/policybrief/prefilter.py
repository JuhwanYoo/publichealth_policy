"""URL 정규화, 항목 id, 키워드 사전 필터."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from policybrief.models import Item

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "spm", "igshid")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(query), ""))


def make_item_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:12]


class KeywordFilter:
    def __init__(self, keywords: list[str]):
        self.keywords = [k for k in keywords if k]
        # 영문 키워드는 대소문자 무시, 한글은 그대로 부분 일치.
        self._pattern = re.compile("|".join(re.escape(k) for k in self.keywords), re.IGNORECASE) if self.keywords else None

    @classmethod
    def from_yaml(cls, path: Path) -> "KeywordFilter":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        keywords: list[str] = []
        for key, lang_list in data.items():
            if key == "exclude":
                continue
            keywords.extend(str(k) for k in (lang_list or []))
        return cls(keywords)

    def matches(self, item: Item) -> bool:
        if self._pattern is None:
            return True
        return bool(self._pattern.search(f"{item.title}\n{item.summary}"))

    def apply(self, items: list[Item]) -> list[Item]:
        return [it for it in items if self.matches(it)]


_TITLE_NORM_RE = re.compile(r"[\s\W_]+")


def title_key(title: str) -> str:
    return _TITLE_NORM_RE.sub("", title).lower()


def dedupe(items: list[Item]) -> list[Item]:
    """같은 실행 안에서 URL이 겹치는 항목을 제거한다 (먼저 온 것을 남김).

    정부·공공기관 자료는 기관 사이트 원본과 정책브리핑 전재본이 서로 다른 URL로 들어오므로 제목으로도 합친다.
    """
    seen: set[str] = set()
    seen_titles: set[str] = set()
    out: list[Item] = []
    for item in items:
        if item.id in seen:
            continue
        if item.category == "gov":
            key = title_key(item.title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
        seen.add(item.id)
        out.append(item)
    return out


class ExcludeFilter:
    """제목에 홍보·동정성 표현이 있는 기사를 걸러낸다 (언론 소스 전용)."""

    def __init__(self, patterns: list[str]):
        self.patterns = [p for p in patterns if p]
        self._pattern = re.compile("|".join(re.escape(p) for p in self.patterns), re.IGNORECASE) if self.patterns else None

    @classmethod
    def from_yaml(cls, path: Path) -> "ExcludeFilter":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls([str(p) for p in (data.get("exclude") or [])])

    def excluded(self, item: Item) -> bool:
        return bool(self._pattern and self._pattern.search(item.title))

    def apply(self, items: list[Item]) -> list[Item]:
        return [it for it in items if not self.excluded(it)]
