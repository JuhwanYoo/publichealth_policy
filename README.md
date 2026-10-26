# 보건의료정책 데일리 브리핑

해외·국내 보건의료정책 저널, 국내 주요 언론·보건의료 전문지, 정부·공공기관 보도자료에서
보건의료정책 이슈를 **매일 아침 자동으로 수집하고 Claude로 한국어 요약·분류**해
Markdown 리포트(`reports/`)와 GitHub Pages 사이트로 게시합니다.

```
수집 (RSS · PubMed) → 중복 제거 · 키워드 사전 필터 → 본문 보강 → Claude 분류·요약 → 하루 종합
   → reports/YYYY-MM-DD.md  +  data/items/YYYY-MM-DD.json  →  정적 사이트 (GitHub Pages)
```

## 동작 방식

- **수집 (자동, 무료)**: GitHub Actions가 매일 07:00 KST에 모든 소스를 수집해 `data/raw/YYYY-MM-DD.json`을 커밋합니다. API 키가 필요 없습니다.
- **분석·요약 (Claude Code 세션)**: 세션에서 *"10월 26일 브리핑 만들어줘"* 라고 하면 Claude가 수집 파일을 읽고
  분류·요약·종합을 작성해 `reports/YYYY-MM-DD.md`와 `data/items/YYYY-MM-DD.json`을 만들어 푸시합니다 (절차는 `CLAUDE.md`).
  구독 사용량에 포함되므로 별도 API 과금이 없습니다.
- **사이트 (자동)**: `main`에 `data/items/**`가 푸시되면 `Deploy site` 워크플로가 GitHub Pages를 다시 배포합니다.

## 처음 설정 (한 번만)

1. **GitHub Pages**: Settings → Pages → *Build and deployment* → Source = **GitHub Actions**.
2. Actions 탭 → **Daily policy brief** → *Run workflow* → `mode = check` 로 한 번 실행해 피드 상태를 확인하고,
   죽은 소스는 `config/sources.yaml`에서 URL을 고치거나 `enabled: false`로 끕니다.
3. 같은 워크플로를 `mode = collect`(기본)로 실행하면 오늘 자 수집 파일이 커밋됩니다. 이후엔 매일 자동 실행됩니다.

### (선택) Claude API로 완전 자동화

분석까지 Actions에서 돌리고 싶으면 Secrets에 `ANTHROPIC_API_KEY`를 넣고 Variables에 `POLICYBRIEF_MODE = full`을 설정합니다
(선택: `POLICYBRIEF_MODEL`, 기본 `claude-opus-5-5`). 하루 100~200건 기준 약 $0.5~1/일이 과금됩니다.

## 로컬 실행

```bash
pip install -e ".[dev]"

python -m policybrief check-feeds                 # 소스 상태 점검
python -m policybrief collect                     # 수집 → data/raw/<오늘>.json
python -m policybrief show --date 2026-10-26      # 수집 항목 읽기
python -m policybrief render --date 2026-10-26    # data/analysis/<date>.json + raw → 리포트
python -m policybrief build-site --out site       # 사이트 생성 → site/index.html
python -m policybrief run                         # (선택) Claude API로 수집~리포트 한 번에
pytest
```

공통 옵션: `--date`, `--sources id1,id2`, `--fixtures DIR`(네트워크 대신 `DIR/<source_id>.xml`),
`--no-fulltext`, `--limit N`, `--ignore-seen`, `--fresh`. `POLICYBRIEF_ROOT`로 데이터·리포트 출력 위치를 바꿀 수 있습니다.

## 소스 추가·수정

`config/sources.yaml`에 항목을 추가합니다. `profile`로 기본값(journal / media_general / media_health / gov)을 받고 필요한 필드만 덮어씁니다.

```yaml
- id: some_journal
  name: Some Journal
  profile: journal            # kind: pubmed, lookback 14일
  journal: "Some J"           # PubMed 저널 약칭 ([ta] 검색)
  query: *policy_query        # 선택: 정책 관련 논문만 (종합의학 저널용)

- id: some_media
  name: 어떤 신문 사회면
  profile: media_general      # kind: rss, 키워드 사전 필터 적용, 본문 보강
  url: https://example.com/rss/society.xml
```

- 일반 일간지는 `config/keywords.yaml`의 키워드가 제목·요약에 있어야 분석 단계로 넘어갑니다. 전문지·저널·정부자료는 전부 분석합니다.
- 주제 분류 체계는 `src/policybrief/models.py`의 `Topic`, 분류·종합 프롬프트는 `src/policybrief/analyze.py`에 있습니다.

## 구조

| 경로 | 역할 |
|---|---|
| `src/policybrief/collect/` | RSS(`rss.py`), PubMed(`pubmed.py`), 본문 보강(`fulltext.py`) |
| `src/policybrief/prefilter.py` | URL 정규화, 중복 제거, 키워드 필터 |
| `src/policybrief/state.py` | `data/seen.json` — 처리한 항목 60일 보관 |
| `src/policybrief/analyze.py` | 분류·요약 기준(시스템 프롬프트), (선택) Claude API 분석기 |
| `src/policybrief/cli.py` | `collect` / `show` / `render` / `build-site` / `run` / `check-feeds` |
| `CLAUDE.md` | 세션에서 브리핑을 만드는 절차 |
| `src/policybrief/render.py`, `templates/` | Markdown 리포트, 정적 사이트(아카이브·주제별·검색) |
| `.github/workflows/daily-brief.yml` | 매일 07:00 KST 수집·커밋 (`mode=full`이면 API 분석·배포까지) |
| `.github/workflows/deploy-site.yml` | `data/items/**` 푸시 시 Pages 배포 |
