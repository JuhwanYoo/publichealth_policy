"""파이프라인 전반에서 쓰는 데이터 모델."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Topic(str, Enum):
    INSURANCE = "건강보험·수가"
    WORKFORCE = "의료인력"
    DELIVERY = "의료전달체계·공공의료"
    INFECTIOUS = "감염병·예방"
    PHARMA = "약가·의약품·기기"
    DIGITAL = "디지털헬스"
    FINANCE = "보건재정"
    LTC = "돌봄·장기요양"
    MENTAL = "정신건강"
    GOVERNANCE = "법제·거버넌스"
    GLOBAL = "국제보건"
    OTHER = "기타"


Category = Literal["journal", "media_general", "media_health", "gov"]

CATEGORY_LABELS: dict[str, str] = {
    "journal": "학술 저널",
    "media_general": "일간지·통신사",
    "media_health": "보건의료 전문지",
    "gov": "정부·공공기관",
}


class Source(BaseModel):
    id: str
    name: str
    kind: Literal["rss", "pubmed", "html_list"]
    category: Category
    lang: Literal["ko", "en"] = "ko"
    url: str | None = None          # rss
    journal: str | None = None      # pubmed: 저널명 ([ta] 검색)
    query: str | None = None        # pubmed: 추가 검색식 (AND 결합)
    link_pattern: str | None = None # html_list: 기사 링크 href에 포함돼야 하는 문자열
    lookback_hours: int = 36
    prefilter: Literal["none", "keywords"] = "none"
    fetch_fulltext: bool = False
    enabled: bool = True
    max_items: int = 60


class Item(BaseModel):
    """수집된 단일 기사/논문."""

    id: str                      # 정규화 URL의 sha1 앞 12자
    source_id: str
    source_name: str
    category: Category
    lang: str
    title: str
    url: str
    published: datetime | None = None
    summary: str = ""            # 피드 description / 초록 / 본문 발췌
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    doi: str | None = None


class ItemAnalysis(BaseModel):
    """Claude가 항목별로 돌려주는 분류·요약."""

    id: str
    relevant: bool
    topic: Topic = Topic.OTHER
    title_ko: str = ""
    summary_ko: str = ""
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)


class AnalyzedItem(BaseModel):
    item: Item
    analysis: ItemAnalysis


class KeyIssue(BaseModel):
    title: str
    description: str
    item_ids: list[str] = Field(default_factory=list)


class ResearchIdea(BaseModel):
    """오늘 수집된 자료에서 도출한 보건의료정책 연구 주제 제안."""

    title: str
    question: str                                   # 연구 질문
    rationale: str                                  # 왜 지금 이 주제인가 (근거 항목과 연결)
    approach: str = ""                              # 가능한 자료원·설계
    item_ids: list[str] = Field(default_factory=list)


class Synthesis(BaseModel):
    """하루 브리핑 종합 결과."""

    headline: str = ""
    key_issues: list[KeyIssue] = Field(default_factory=list)
    notable_papers: list[str] = Field(default_factory=list)   # item id
    policy_outlook: str = ""
    research_ideas: list[ResearchIdea] = Field(default_factory=list)


class SourceStatus(BaseModel):
    source_id: str
    source_name: str
    category: Category
    ok: bool
    fetched: int = 0
    new: int = 0
    kept: int = 0
    error: str | None = None


class RawBatch(BaseModel):
    """`policybrief collect`가 저장하는 수집 결과 (분석 전)."""

    date: str
    collected_at: datetime
    items: list[Item] = Field(default_factory=list)
    source_status: list[SourceStatus] = Field(default_factory=list)


class AnalysisFile(BaseModel):
    """세션(또는 외부)에서 작성한 분석 결과. `policybrief render`가 raw와 합친다."""

    items: list[ItemAnalysis]
    synthesis: Synthesis = Field(default_factory=Synthesis)
    analyst: str = "Claude Code 세션"


class DailyBrief(BaseModel):
    date: str                                  # YYYY-MM-DD (KST)
    generated_at: datetime
    model: str | None = None                   # None이면 --no-llm
    items: list[AnalyzedItem] = Field(default_factory=list)
    synthesis: Synthesis = Field(default_factory=Synthesis)
    source_status: list[SourceStatus] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)

    def relevant_items(self) -> list[AnalyzedItem]:
        def key(ai: AnalyzedItem) -> tuple[int, float]:
            ts = ai.item.published.timestamp() if ai.item.published else 0.0
            return (-ai.analysis.importance, -ts)

        return sorted((ai for ai in self.items if ai.analysis.relevant), key=key)
