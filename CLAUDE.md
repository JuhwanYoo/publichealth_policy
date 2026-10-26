# policybrief — Claude Code 세션 작업 지침

이 저장소는 보건의료정책 데일리 브리핑 파이프라인이다. **수집은 GitHub Actions가, 분석·요약은 Claude Code 세션(너)이** 한다.
Anthropic API는 쓰지 않는다 (사용자가 과금을 원치 않음). `policybrief run`은 API 키가 있을 때만 쓰는 선택 경로다.

## "N월 N일 브리핑 만들어줘" 를 받으면

이 샌드박스는 외부 네트워크(RSS·PubMed)에 접근하지 못한다. 수집은 반드시 GitHub Actions 결과(`data/raw/`)를 쓴다.

1. **최신 상태 받기**
   ```bash
   git pull --rebase origin main
   ls data/raw/
   ```
2. **raw가 없으면** GitHub Actions `Daily policy brief` 워크플로를 `mode=collect`로 실행(`actions_run_trigger`)하고,
   완료될 때까지 기다린 뒤(`actions_list`로 run 상태 확인, 보통 2~4분) 다시 `git pull`.
   같은 날짜 파일이 이미 있어도 오후에 다시 수집하면 새 항목이 병합된다.
3. **항목 읽기**
   ```bash
   python -m policybrief show --date YYYY-MM-DD              # 전체
   python -m policybrief show --date YYYY-MM-DD --category journal
   ```
   항목이 많으면(>80건) 카테고리별로 나눠 읽는다. 출력의 `[id=...]`가 분석 파일의 키다.
4. **분석 파일 작성** → `data/analysis/YYYY-MM-DD.json`
   - 형식은 `src/policybrief/models.py`의 `AnalysisFile` (아래 예시). `analyst`는 `"Claude Code 세션"`.
   - **분류 기준·요약 톤은 `src/policybrief/analyze.py`의 `CLASSIFY_SYSTEM`, `SYNTHESIS_SYSTEM`을 그대로 따른다.**
     - `relevant`: 보건의료 *정책* 관련성. 임상 단신·병원 홍보·건강 상식·사건사고는 false.
     - `topic`: `Topic` enum 값 문자열 그대로 (건강보험·수가 / 의료인력 / 의료전달체계·공공의료 / 감염병·예방 / 약가·의약품·기기 /
       디지털헬스 / 보건재정 / 돌봄·장기요양 / 정신건강 / 법제·거버넌스 / 국제보건 / 기타).
     - `title_ko`: 한국어 제목(영문은 번역). `summary_ko`: 2~3문장, 입력에 없는 사실 금지. `importance` 1~5. `tags` 2~5개.
     - 모든 수집 항목에 대해 relevant true/false를 판단해 넣는다. 빠뜨린 id는 자동으로 `relevant=false` 처리되지만 경고가 난다.
   - `synthesis`: 핵심 이슈 4~7개(같은 사건은 하나로 묶고 `item_ids`로 근거 연결, 뉴스와 논문 교차 연결), 주목할 논문 최대 5개 id,
     정책 동향 2~3문장. 입력에 없는 사실을 추가하지 않는다.
5. **렌더 및 확인**
   ```bash
   python -m policybrief render --date YYYY-MM-DD      # → data/items/, reports/
   sed -n '1,80p' reports/YYYY-MM-DD.md
   pytest -q                                           # 코드 변경이 있었을 때만
   ```
6. **커밋·푸시**
   - 커밋 대상: `data/analysis/`, `data/items/`, `reports/` (raw·seen은 Actions가 이미 커밋함).
   - 메시지: `brief: YYYY-MM-DD`.
   - 브리핑 데이터는 사용자가 허락했다면 `main`에 직접 푸시한다. 허락이 없으면 세션 브랜치에 푸시하고 PR을 안내한다.
   - `main`에 `data/items/**`가 푸시되면 `Deploy site` 워크플로가 Pages를 다시 배포한다.
7. 사용자에게 결과를 짧게 보고: 관련 N/총 M건, 핵심 이슈 제목들, 실패한 소스가 있으면 이름.

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

- 테스트: `pip install -e ".[dev]" && pytest -q`. 네트워크 없이 `--fixtures tests/fixtures`로 전체 흐름을 재현할 수 있다
  (`POLICYBRIEF_ROOT`로 출력 경로를 바꿀 수 있음).
- 소스 추가는 `config/sources.yaml`, 일반 언론 사전 필터 키워드는 `config/keywords.yaml`.
- 피드 상태 점검은 Actions `mode=check` (샌드박스에서는 네트워크가 막혀 `check-feeds`가 전부 실패한다).
