"""PubMed E-utilities 수집기: 저널명(+검색식)으로 esearch → efetch 로 초록을 받아온다."""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from policybrief.models import Item, Source
from policybrief.prefilter import make_item_id

from .http import DEFAULT_TIMEOUT, USER_AGENT

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# NCBI 허용치: API 키 없이 초당 3회, 키가 있으면 10회. 소스가 많으므로 보수적으로 간격을 둔다.
_MIN_INTERVAL = 0.4
_last_request = 0.0


def _get(client: httpx.Client, url: str, params: dict, retries: int = 4) -> httpx.Response:
    """요청 간격을 지키고 429/5xx는 지수 백오프로 재시도한다."""
    global _last_request
    for attempt in range(retries + 1):
        wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        resp = client.get(url, params=params)
        _last_request = time.monotonic()
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < retries:
                time.sleep(1.5 * (2 ** attempt))
                continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("unreachable")

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def build_term(source: Source) -> str:
    term = f'"{source.journal}"[ta]'
    if source.query:
        term = f"{term} AND ({source.query})"
    return term


def _base_params() -> dict[str, str]:
    params = {"db": "pubmed", "tool": "policybrief", "email": "policybrief@example.com"}
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _article_date(article: ET.Element) -> datetime | None:
    # 전자 출판일 → 저널 발행일 순으로 찾는다.
    for path in (
        ".//ArticleDate[@DateType='Electronic']",
        ".//Journal/JournalIssue/PubDate",
        ".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']",
    ):
        node = article.find(path)
        if node is None:
            continue
        year = _text(node.find("Year"))
        if not year.isdigit():
            continue
        month_raw = _text(node.find("Month")) or "1"
        month = _MONTHS.get(month_raw[:3], int(month_raw) if month_raw.isdigit() else 1)
        day_raw = _text(node.find("Day"))
        day = int(day_raw) if day_raw.isdigit() else 1
        try:
            return datetime(int(year), month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_efetch(source: Source, xml_bytes: bytes) -> list[Item]:
    root = ET.fromstring(xml_bytes)
    items: list[Item] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article.find(".//PMID"))
        title = _text(article.find(".//ArticleTitle"))
        if not pmid or not title:
            continue
        abstract_parts = []
        for ab in article.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            text = _text(ab)
            abstract_parts.append(f"{label}: {text}" if label else text)
        doi = None
        for aid in article.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid)
        authors = []
        for au in article.findall(".//AuthorList/Author")[:6]:
            last, fore = _text(au.find("LastName")), _text(au.find("ForeName"))
            if last:
                authors.append(f"{fore} {last}".strip())
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        items.append(
            Item(
                id=make_item_id(url),
                source_id=source.id,
                source_name=source.name,
                category=source.category,
                lang=source.lang,
                title=title.rstrip("."),
                url=url,
                published=_article_date(article),
                summary=" ".join(abstract_parts),
                authors=authors,
                journal=_text(article.find(".//Journal/Title")) or source.name,
                doi=doi,
            )
        )
    return items


def collect_pubmed(source: Source, now: datetime) -> list[Item]:
    if not source.journal:
        raise ValueError(f"source {source.id}: pubmed source needs journal")
    reldate = max(1, source.lookback_hours // 24)
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
        search = _get(
            client,
            f"{EUTILS}/esearch.fcgi",
            {
                **_base_params(),
                "term": build_term(source),
                "reldate": str(reldate),
                "datetype": "edat",
                "retmax": str(source.max_items),
                "sort": "date",
                "retmode": "json",
            },
        )
        ids = search.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        fetch = _get(
            client,
            f"{EUTILS}/efetch.fcgi",
            {**_base_params(), "id": ",".join(ids), "retmode": "xml"},
        )
    return parse_efetch(source, fetch.content)
