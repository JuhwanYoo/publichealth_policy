"""PubMed E-utilities 수집기: 저널명(+검색식)으로 esearch → efetch 로 초록을 받아온다."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from policybrief.models import Item, Source
from policybrief.prefilter import make_item_id

from .http import DEFAULT_TIMEOUT, USER_AGENT

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

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
        search = client.get(
            f"{EUTILS}/esearch.fcgi",
            params={
                **_base_params(),
                "term": build_term(source),
                "reldate": str(reldate),
                "datetype": "edat",
                "retmax": str(source.max_items),
                "sort": "date",
                "retmode": "json",
            },
        )
        search.raise_for_status()
        ids = search.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        fetch = client.get(
            f"{EUTILS}/efetch.fcgi",
            params={**_base_params(), "id": ",".join(ids), "retmode": "xml"},
        )
        fetch.raise_for_status()
    return parse_efetch(source, fetch.content)
