# policybrief — Claude Code 세션 작업 지침

이 저장소는 보건의료정책 브리핑 파이프라인이다 (수집 매일, 브리핑 매주 월요일). **수집은 GitHub Actions가, 분석·요약은 Claude Code 세션(너)이** 한다.
Anthropic API는 쓰지 않는다 (사용자가 과금을 원치 않음). `policybrief run`은 API 키가 있을 때만 쓰는 선택 경로다.

## "이번 주 브리핑 만들어줘" 를 받으면 (매주 월요일 아침, 기본 흐름)

**수집은 매일(Actions), 브리핑은 주 1회(월요일)** 다. 사용자 결정(2026-10-27): 매일 브리핑은 하루치가 얇고 중복이 생겨
연구 주제 발굴에는 한 주치를 묶는 쪽이 낫다. 수집을 주 1회로 줄이면 안 된다 — RSS 피드는 최근 50~100건만 담아 주 초반 기사가 빠진다.

이 샌드박스는 외부 네트워크(RSS·PubMed)에 접근하지 못한다. 수집은 반드시 GitHub Actions 결과(`data/raw/`)를 쓴다.

1. **기간 확정**: 브리핑 키 `D` = 오늘(월요일) 날짜. 대상 raw = `D-6 … D` 7개(화~월 수집분 ≈ 지난 월~일 기사).
   직전 브리핑과 겹치지 않게 하려면 `--from <직전 브리핑 다음 날>`. (첫 주간 2026-11-02는 `--from 2026-10-28`: 10/27까지는 일간 브리핑이 있다.)
2. **최신 상태 받기**
   ```bash
   git pull --rebase origin main
   ls data/raw/
   ```
3. **빠진 날이 있으면** `show --week`가 `⚠ 날짜: 수집 파일 없음`으로 알려준다. 오늘(`D`) 파일이 없으면 Actions `Daily policy brief`를
   `mode=collect`로 실행(`actions_run_trigger`)하고 완료까지 기다린 뒤(`actions_list`, 보통 2~4분) 다시 `git pull`.
   과거 날짜는 다시 수집해도 피드에 남은 만큼만 들어오므로, 빠진 날은 그대로 두고 리포트 보고 때 알린다.
4. **항목 읽기 — 두 단계** (주간은 300~400건이라 처음부터 본문을 다 읽지 않는다)
   ```bash
   python -m policybrief show --week D [--from START] --titles                 # 1차: 제목·소스·날짜 한 줄씩 (날짜별 건수 포함)
   python -m policybrief show --week D [--from START] --ids id1,id2,...        # 2차: 고른 후보만 본문
   python -m policybrief show --week D [--from START] --category journal --titles   # 카테고리별로 나눠 보기
   ```
   1차에서 정책 관련 후보(보통 80~120건)를 고르고, 2차는 카테고리별·30~40건씩 나눠 읽는다. `[id=...]`가 분석 파일의 키다.
   기간 병합 때 같은 id나 같은 제목의 정부 자료가 다른 날 또 오면 한 번만 보이며, 빠진 id는 `render`가 분석 파일에서도 무시한다.
5. **분석 파일 작성** → `data/analysis/D.json` (키 = 월요일 날짜)
   - 형식은 `src/policybrief/models.py`의 `AnalysisFile` (아래 예시). `analyst`는 `"Claude Code 세션"`.
   - **분류 기준·요약 톤은 `src/policybrief/analyze.py`의 `CLASSIFY_SYSTEM`, `SYNTHESIS_SYSTEM`을 그대로 따른다.**
     - `relevant`: 보건의료 *정책* 관련성. 임상 단신·병원/기업 홍보(수상·협약·기부·행사·인사·출시·주가)·건강 상식·사건사고는 false.
     - **이슈성 기준이 엄격하다.** 리포트 본문에는 `importance >= 3`인 항목만 실리고(2 이하는 접힌 '참고 항목'으로만),
       사용자는 "이슈가 되는 기사만" 원한다. 주간 기준으로 **3 이상은 20~30건, 4 이상은 10건 안팎**으로 묶는다.
       3 이상은 제도 결정·입법·예산, 이해관계자 쟁점, 새 통계·근거, 법원·헌재 판단, 주요 저널 논문처럼 독자가 알아야 할 *변화*가
       있는 항목에만. 같은 사건의 여러 날 보도는 대표 1~2건만 3 이상으로 하고 나머지는 2.
     - `topic`: `Topic` enum 값 문자열 그대로 (건강보험·수가 / 의료인력 / 의료전달체계·공공의료 / 감염병·예방 / 약가·의약품·기기 /
       디지털헬스 / 보건재정 / 돌봄·장기요양 / 정신건강 / 법제·거버넌스 / 국제보건 / 기타).
     - `title_ko`: 한국어 제목(영문은 번역). `summary_ko`: 2~3문장, 입력에 없는 사실 금지. `importance` 1~5. `tags` 2~5개.
     - 1차 제목 선별에서 떨어진 항목도 포함해 **모든 수집 항목에** relevant true/false를 넣는다 (제목만 본 항목은 summary 빈 문자열, importance 1).
       빠뜨린 id는 자동으로 `relevant=false` 처리되지만 경고가 난다.
   - `synthesis`: 핵심 이슈 **6~10개**(한 주 동안 이어진 사건은 하나로 묶고 `item_ids`로 근거 연결, 뉴스와 논문 교차 연결),
     주목할 논문 최대 8개 id, 정책 동향 3~4문장(이번 주 흐름 + 다음 주 예정된 결정·시행일). 입력에 없는 사실을 추가하지 않는다.
   - `synthesis.research_ideas`: **보건의료정책 연구 주제 제안 5~8개** (사용자가 가장 원하는 항목).
     각 항목은 `title`, `question`(검증 가능한 연구 질문), `rationale`(이번 주 어떤 뉴스·논문·보도자료가 이 주제를 시의성 있게 만드는지),
     `approach`(활용 가능한 자료원 — 건보 청구자료, 심평원 비급여 보고, 한국의료패널, NEDIS, 감염병 신고 등 — 과 설계: DID, 단절적 시계열,
     회귀단절, 코호트 연계, 질적 연구 등), `item_ids`. 뉴스가 던진 정책 논쟁을 실증 가능한 질문으로 바꾸는 데 집중하고,
     이미 답이 나온 주제나 자료가 존재하지 않는 설계는 피한다. 한 주에 여러 번 보도된 쟁점을 우선한다.
6. **렌더 및 확인**
   ```bash
   python -m policybrief render --week D [--from START]   # → data/items/D.json, reports/D.md
   sed -n '1,80p' reports/D.md
   python -m pytest -q                                   # 코드 변경이 있었을 때만
   ```
7. **커밋·푸시**
   - 커밋 대상: `data/analysis/`, `data/items/`, `reports/` (raw·seen은 Actions가 이미 커밋함).
   - 메시지: `brief: D (weekly)`.
   - **사용자가 `main` 직접 푸시를 허용했다 (2026-10-26).** 브리핑 데이터와 코드 변경 모두 `main`에 바로 푸시한다 (`git push origin HEAD:main`).
   - `main`에 `data/items/**`가 푸시되면 `Deploy site` 워크플로가 Pages를 다시 배포한다.
8. 사용자에게 결과를 짧게 보고: 기간, 이슈 N건(중요도 3 이상)/총 M건, 핵심 이슈 제목들, 연구 주제 제목들, 수집이 빠진 날짜와 실패한 소스.

### 일간 브리핑이 필요할 때 ("N월 N일 브리핑 만들어줘")

같은 절차에서 `--week D`를 `--date YYYY-MM-DD`로 바꾸면 된다 (하루치 raw, 분석 파일 키도 그 날짜, 커밋 메시지 `brief: YYYY-MM-DD`).
하루치는 40~60건이라 `--titles` 단계 없이 바로 본문을 읽어도 된다. 핵심 이슈 4~7개, 연구 주제 3~6개.

## 분석 파일 예시

```json
{
  "analyst": "Claude Code 세션",
  "items": [
    {"id": "4f2a9c1e0b7d", "relevant": true, "topic": "의료인력", "title_ko": "전공의 복귀율 80% 넘어…의대 정원 논의 재개",
     "summary_ko": "…", "importance": 5, "tags": ["의대 정원", "전공의"]},
    {"id": "a1b2c3d4e5f6", "relevant": false, "topic": "기타", "title_ko": "…", "summary_ko": "", "importance": 1, "tags": []}
  ],
  "synthesis": {
    "headline": "…",
    "key_issues": [{"title": "…", "description": "…", "item_ids": ["4f2a9c1e0b7d"]}],
    "notable_papers": ["…"],
    "policy_outlook": "…"
  }
}
```

## 코드 작업 시

- 테스트: `pip install -e ".[dev]" && python -m pytest -q` (PATH의 `pytest`는 다른 인터프리터일 수 있다). 네트워크 없이 `--fixtures tests/fixtures`로 전체 흐름을 재현할 수 있다
  (`POLICYBRIEF_ROOT`로 출력 경로를 바꿀 수 있음).
- 소스 추가는 `config/sources.yaml` (kind: rss / pubmed / html_list). 일반 언론 사전 필터 키워드와 언론 공통 제외 키워드(`exclude:`)는 `config/keywords.yaml`.
- 리포트에 싣는 중요도 문턱은 `src/policybrief/render.py`의 `MIN_IMPORTANCE`(기본 3).
- 피드 상태 점검은 Actions `mode=check` (샌드박스에서는 네트워크가 막혀 `check-feeds`가 전부 실패한다).
