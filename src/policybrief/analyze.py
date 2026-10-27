"""Claude API로 항목 분류·요약 및 하루 종합을 생성한다. `--no-llm`이면 스텁 분석기를 쓴다."""

from __future__ import annotations

import json
import logging
import os
from zoneinfo import ZoneInfo
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from policybrief.models import (
    AnalyzedItem,
    CATEGORY_LABELS,
    Item,
    ItemAnalysis,
    KeyIssue,
    ResearchIdea,
    Synthesis,
    Topic,
)

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_MODEL = "claude-opus-5-5"
BATCH_SIZE = 15
MAX_SUMMARY_CHARS = 2500      # 항목당 입력 본문 상한 (토큰 절약)

TOPIC_LIST = "\n".join(f"- {t.value}" for t in Topic)

CLASSIFY_SYSTEM = f"""당신은 보건의료정책 전문 애널리스트입니다. 매일 아침 보건의료정책 연구자·실무자를 위한 브리핑을 만듭니다.
입력으로 뉴스 기사, 학술 논문 초록, 정부 보도자료 목록을 받으면 각 항목을 아래 기준으로 분류·요약합니다.

[관련성 relevant]
- true: 보건의료 "정책"과 관련이 있는 항목 — 건강보험·수가·급여, 의료인력·의대정원·수련, 의료전달체계·공공의료·지역의료,
  감염병 대응 체계·예방접종 정책, 약가·의약품·의료기기 규제, 디지털헬스·의료데이터 정책, 보건재정, 돌봄·장기요양, 정신건강 정책,
  보건의료 법제·거버넌스, 국제보건 정책, 보건의료체계 성과·형평성 연구 등.
- false: 개별 질병의 임상 연구, 신약 임상시험 결과, 병원·기업 홍보(수상, 협약, 기부, 행사, 인사, 제품 출시, 주가), 건강 상식,
  사건사고 단신, 정책 함의가 거의 없는 기초 연구.
  단, 임상 연구라도 정책적 함의(비용효과, 접근성, 형평성, 제도 변화)를 핵심으로 다루면 true.
- 브리핑에는 "이슈가 되는" 항목만 싣습니다. 제도 결정·입법·예산, 이해관계자 간 쟁점, 새로운 통계·근거, 법원·헌재 판단,
  주요 저널 논문처럼 독자가 알아야 할 변화가 있는 항목에 importance 3 이상을 주고, 단순 동정·행사 안내·반복 보도는 2 이하로 둡니다.

[주제 topic] 다음 중 하나를 정확히 그대로 사용:
{TOPIC_LIST}

[title_ko] 한국어 제목. 원문이 한국어면 그대로(불필요한 꾸밈 제거), 영어면 자연스러운 한국어로 번역.
[summary_ko] 2~3문장의 한국어 요약. 무엇이 결정/발표/발견되었는지, 왜 정책적으로 중요한지를 담는다. 논문이면 연구 설계와 핵심 결과를 포함.
  입력에 없는 사실을 지어내지 말 것. 정보가 부족하면 제목에서 알 수 있는 범위만 요약.
[importance] 1~5. 5 = 제도 변화·법 개정·대규모 재정 결정·주요 저널의 획기적 연구, 3 = 통상적 정책 뉴스, 1 = 주변적.
[tags] 핵심 키워드 2~5개 (기관명, 제도명, 질환군 등).

relevant=false인 항목도 id와 relevant는 반드시 포함하되 나머지 필드는 간단히 채웁니다."""

SYNTHESIS_SYSTEM = """당신은 보건의료정책 전문 애널리스트입니다. 오늘 수집·분류된 항목 목록(뉴스, 논문, 보도자료)을 보고
연구자·정책 실무자가 아침에 5분 안에 읽을 수 있는 하루 종합을 작성합니다.

[headline] 오늘 브리핑을 한 문장으로 요약 (40자 내외).
[key_issues] 오늘의 핵심 이슈 4~7개. 각 이슈는
  - title: 이슈명 (명사구, 25자 내외)
  - description: 3~5문장. 무슨 일이 있었고, 이해관계자들의 입장은 무엇이며, 앞으로 무엇을 지켜봐야 하는지. 관련 연구가 있으면 뉴스와 연결해 해석.
  - item_ids: 이 이슈를 뒷받침하는 항목 id 목록 (입력에 있는 id만, 1개 이상).
  같은 사건을 다룬 여러 기사는 하나의 이슈로 묶습니다. 중요도와 보도량이 큰 순서로 배열합니다.
[notable_papers] 정책적 함의가 가장 큰 학술 논문 항목의 id 최대 5개 (논문이 없으면 빈 배열).
[policy_outlook] 국내 흐름 2~3문장. 오늘 흐름이 시사하는 한국 보건의료정책의 중장기 방향 또는 주목할 일정.
[global_outlook] 해외 흐름 2~3문장. 해외 저널·국제 뉴스에서 읽히는 글로벌 보건의료정책 동향과 한국에 주는 시사점. 해외 항목이 없으면 빈 문자열.
[research_ideas] 오늘 자료에서 도출되는 보건의료정책 연구 주제 3~6개. 각각
  - title: 주제명, question: 검증 가능한 연구 질문 1~2문장,
  - rationale: 왜 지금 이 주제가 중요한지 — 오늘 항목(뉴스·보도자료·논문)과 연결해 설명,
  - approach: 활용 가능한 자료원(건보 청구자료, 한국의료패널, 기관 통계 등)과 설계(DID, 단절적 시계열, 질적 연구 등),
  - item_ids: 근거 항목 id.
  뉴스가 던진 정책 논쟁을 실증 가능한 질문으로 바꾸는 데 집중하고, 이미 답이 나온 주제는 피합니다.

입력에 없는 사실을 추가하지 마십시오. 모든 출력은 한국어입니다."""


class _ClassifyBatch(BaseModel):
    items: list[ItemAnalysis]


class _SynthesisOut(BaseModel):
    headline: str
    key_issues: list[KeyIssue]
    notable_papers: list[str] = Field(default_factory=list)
    policy_outlook: str
    global_outlook: str = ""
    research_ideas: list[ResearchIdea] = Field(default_factory=list)


class Analyzer(Protocol):
    model_name: str | None

    def classify(self, items: list[Item]) -> list[AnalyzedItem]: ...
    def synthesize(self, items: list[AnalyzedItem]) -> Synthesis: ...
    def usage(self) -> dict[str, int]: ...


# ── 스텁 (--no-llm) ──────────────────────────────────────────────────────────

class StubAnalyzer:
    """LLM 없이 파이프라인·렌더링을 검증하기 위한 분석기."""

    model_name = None

    def classify(self, items: list[Item]) -> list[AnalyzedItem]:
        out = []
        for it in items:
            out.append(
                AnalyzedItem(
                    item=it,
                    analysis=ItemAnalysis(
                        id=it.id,
                        relevant=True,
                        topic=Topic.OTHER,
                        title_ko=it.title,
                        summary_ko=(it.summary[:200] + "…") if len(it.summary) > 200 else it.summary,
                        importance=3,
                        tags=[],
                    ),
                )
            )
        return out

    def synthesize(self, items: list[AnalyzedItem]) -> Synthesis:
        papers = [ai.item.id for ai in items if ai.item.category == "journal"][:5]
        return Synthesis(
            headline="(LLM 미사용) 수집 항목 원문 요약",
            key_issues=[],
            notable_papers=papers,
            policy_outlook="",
        )

    def usage(self) -> dict[str, int]:
        return {}


# ── Claude ──────────────────────────────────────────────────────────────────

def _item_block(item: Item, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    cat = CATEGORY_LABELS.get(item.category, item.category)
    date = item.published.astimezone(KST).strftime("%Y-%m-%d") if item.published else "날짜 불명"
    body = item.summary[:max_chars]
    head = f"[id={item.id}] ({cat} / {item.source_name} / {date})\n제목: {item.title}\nURL: {item.url}"
    if item.authors:
        head += f"\n저자: {', '.join(item.authors[:4])}"
    return f"{head}\n내용: {body or '(본문 없음)'}"


_STRIP_KEYS = {"title", "default", "minimum", "maximum", "description"}


def _clean_schema(node):
    """structured outputs가 받지 않는 키를 걷어내고 객체를 닫힌 스키마로 만든다."""
    if isinstance(node, dict):
        out = {k: _clean_schema(v) for k, v in node.items() if k not in _STRIP_KEYS}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(node, list):
        return [_clean_schema(v) for v in node]
    return node


def _schema(model: type[BaseModel]) -> dict:
    return _clean_schema(model.model_json_schema())


class ClaudeAnalyzer:
    def __init__(self, model: str | None = None, client=None):
        import anthropic

        self.model_name = model or os.environ.get("POLICYBRIEF_MODEL", DEFAULT_MODEL)
        self.client = client or anthropic.Anthropic()
        self._anthropic = anthropic
        self._usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    def usage(self) -> dict[str, int]:
        return dict(self._usage)

    def _call(self, system: str, user: str, schema: dict, effort: str, max_tokens: int) -> dict | None:
        anthropic = self._anthropic
        try:
            response = self.client.beta.messages.create(
                model=self.model_name,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            log.error("rate limited: %s", exc)
            raise
        except anthropic.APIStatusError as exc:
            log.error("API error %s: %s", exc.status_code, exc.message)
            raise
        except anthropic.APIConnectionError as exc:
            log.error("connection error: %s", exc)
            raise

        u = response.usage
        self._usage["input_tokens"] += u.input_tokens or 0
        self._usage["output_tokens"] += u.output_tokens or 0
        self._usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0

        if response.stop_reason == "refusal":
            log.warning("model refused batch: %s", getattr(response, "stop_details", None))
            return None
        if response.stop_reason == "max_tokens":
            log.warning("response truncated at max_tokens=%d", max_tokens)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            log.error("invalid JSON from model: %s", exc)
            return None

    def classify(self, items: list[Item]) -> list[AnalyzedItem]:
        out: list[AnalyzedItem] = []
        by_id = {it.id: it for it in items}
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start : start + BATCH_SIZE]
            user = "다음 항목들을 분류·요약하세요.\n\n" + "\n\n---\n\n".join(_item_block(it) for it in batch)
            data = self._call(CLASSIFY_SYSTEM, user, _schema(_ClassifyBatch), effort="low", max_tokens=16000)
            parsed: dict[str, ItemAnalysis] = {}
            if data:
                try:
                    for a in _ClassifyBatch.model_validate(data).items:
                        parsed[a.id] = a
                except ValidationError as exc:
                    log.error("classification validation failed: %s", exc)
            for it in batch:
                analysis = parsed.get(it.id)
                if analysis is None:
                    # 모델이 빠뜨린 항목은 보수적으로 '관련 있음·기타'로 남겨 사람이 볼 수 있게 한다.
                    analysis = ItemAnalysis(id=it.id, relevant=True, topic=Topic.OTHER, title_ko=it.title,
                                            summary_ko=it.summary[:200], importance=2, tags=["분류실패"])
                out.append(AnalyzedItem(item=by_id[it.id], analysis=analysis))
            log.info("classified %d/%d", min(start + BATCH_SIZE, len(items)), len(items))
        return out

    def synthesize(self, items: list[AnalyzedItem]) -> Synthesis:
        relevant = [ai for ai in items if ai.analysis.relevant]
        if not relevant:
            return Synthesis(headline="오늘은 관련 항목이 수집되지 않았습니다.")
        lines = []
        for ai in relevant:
            a, it = ai.analysis, ai.item
            cat = CATEGORY_LABELS.get(it.category, it.category)
            lines.append(
                f"[id={it.id}] ({cat} / {it.source_name} / 중요도 {a.importance} / {a.topic.value})\n"
                f"{a.title_ko}\n{a.summary_ko}"
            )
        user = "오늘 수집된 항목입니다. 하루 종합을 작성하세요.\n\n" + "\n\n".join(lines)
        data = self._call(SYNTHESIS_SYSTEM, user, _schema(_SynthesisOut), effort="high", max_tokens=16000)
        if not data:
            return Synthesis(headline="종합 생성 실패 — 항목 목록을 참고하세요.")
        try:
            parsed = _SynthesisOut.model_validate(data)
        except ValidationError as exc:
            log.error("synthesis validation failed: %s", exc)
            return Synthesis(headline="종합 생성 실패 — 항목 목록을 참고하세요.")
        valid_ids = {ai.item.id for ai in relevant}
        issues = [
            KeyIssue(title=k.title, description=k.description, item_ids=[i for i in k.item_ids if i in valid_ids])
            for k in parsed.key_issues
        ]
        ideas = [
            ResearchIdea(title=r.title, question=r.question, rationale=r.rationale, approach=r.approach,
                         item_ids=[i for i in r.item_ids if i in valid_ids])
            for r in parsed.research_ideas
        ]
        return Synthesis(
            headline=parsed.headline,
            key_issues=issues,
            notable_papers=[i for i in parsed.notable_papers if i in valid_ids],
            policy_outlook=parsed.policy_outlook,
            global_outlook=parsed.global_outlook,
            research_ideas=ideas,
        )


def make_analyzer(no_llm: bool, model: str | None = None) -> Analyzer:
    if no_llm:
        return StubAnalyzer()
    return ClaudeAnalyzer(model=model)
