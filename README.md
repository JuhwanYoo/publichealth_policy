# 보건의료정책 데일리 브리핑

해외·국내 보건의료정책 저널, 국내 주요 언론·보건의료 전문지, 정부·공공기관 보도자료에서
보건의료정책 이슈를 **매일 아침 자동으로 수집하고 Claude로 한국어 요약·분류**해
Markdown 리포트(`reports/`)와 GitHub Pages 사이트로 게시합니다.

```
수집 (RSS · PubMed) → 중복 제거 · 키워드 사전 필터 → 본문 보강 → Claude 분류·요약 → 하루 종합
   → reports/YYYY-MM-DD.md  +  data/items/YYYY-MM-DD.json  →  정적 사이트 (GitHub Pages)
```

## 처음 설정 (한 번만)

1. **Secrets** (Settings → Secrets and variables → Actions)
   - `ANTHROPIC_API_KEY` — 필수.
   - `NCBI_API_KEY` — 선택. PubMed 요청 한도를 늘려 줍니다.
2. **Variables** (같은 화면의 Variables 탭) — 선택
   - `POLICYBRIEF_MODEL` — 분석 모델. 기본 `claude-opus-5-5`. 비용을 줄이려면 `claude-sonnet-5-5` 또는 `claude-haiku-5-5`.
3. **GitHub Pages**: Settings → Pages → *Build and deployment* → Source = **GitHub Actions**.
4. Actions 탭에서 **Daily policy brief** 워크플로를 `Run workflow`로 한 번 실행합니다.
   - 처음에는 `check_feeds = true` 로 실행해 어떤 피드가 살아 있는지 확인하고,
     죽은 소스는 `config/sources.yaml`에서 URL을 고치거나 `enabled: false`로 끕니다.
   - 그다음 `no_llm = true`로 한 번 돌려 수집·렌더링을 확인한 뒤, 기본값으로 실제 실행합니다.

이후에는 매일 **07:00 KST**에 자동 실행되어 `reports/`와 `data/`를 커밋하고 사이트를 다시 배포합니다.
같은 날 여러 번 실행하면 새 항목만 추가로 분석해 기존 브리핑과 합칩니다.

## 로컬 실행

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...

python -m policybrief check-feeds                 # 소스 상태 점검
python -m policybrief run --no-llm                # Claude 없이 파이프라인만
python -m policybrief run --limit 30              # 30건만 분석 (비용 제어)
python -m policybrief run                         # 전체 실행
python -m policybrief build-site --out site       # 사이트 생성 → site/index.html
pytest
```

`run` 옵션: `--date`, `--sources id1,id2`, `--fixtures DIR`(네트워크 대신 `DIR/<source_id>.xml`),
`--no-fulltext`, `--ignore-seen`, `--fresh`, `--model`.

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

## 비용

사전 필터 후 하루 100~200건을 분석할 때 Opus 5.5 기준 대략 **$0.5~1/일**(분류 15건씩 배치 + 종합 1회, 시스템 프롬프트 캐시 사용).
리포트 하단 "수집 상태"에 그날의 토큰 사용량이 기록됩니다.

## 구조

| 경로 | 역할 |
|---|---|
| `src/policybrief/collect/` | RSS(`rss.py`), PubMed(`pubmed.py`), 본문 보강(`fulltext.py`) |
| `src/policybrief/prefilter.py` | URL 정규화, 중복 제거, 키워드 필터 |
| `src/policybrief/state.py` | `data/seen.json` — 처리한 항목 60일 보관 |
| `src/policybrief/analyze.py` | Claude 분류·요약 / 하루 종합, `--no-llm` 스텁 |
| `src/policybrief/render.py`, `templates/` | Markdown 리포트, 정적 사이트(아카이브·주제별·검색) |
| `.github/workflows/daily-brief.yml` | 매일 07:00 KST 실행, 커밋, Pages 배포 |
