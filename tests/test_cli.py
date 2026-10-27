import json

import pytest

from policybrief.cli import main


def _run(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    return exc.value.code


def test_collect_show_render_roundtrip(tmp_path, fixtures_dir, monkeypatch, capsys):
    monkeypatch.setenv("POLICYBRIEF_ROOT", str(tmp_path))
    date = "2026-10-26"

    assert _run(["collect", "--fixtures", str(fixtures_dir), "--date", date]) == 0
    raw_path = tmp_path / "data" / "raw" / f"{date}.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    assert len(raw["items"]) == 3                       # 교통사고·오래된 기사는 걸러짐
    assert (tmp_path / "data" / "seen.json").exists()

    # 같은 날 재수집: seen 때문에 신규 0건이어도 기존 항목이 유지된다
    assert _run(["collect", "--fixtures", str(fixtures_dir), "--date", date]) == 0
    assert len(json.loads(raw_path.read_text(encoding="utf-8"))["items"]) == 3

    assert _run(["show", "--date", date]) == 0
    out = capsys.readouterr().out
    assert "[id=" in out and "의대 정원" in out and "URL: https://" in out

    assert _run(["render", "--date", date, "--analysis", str(fixtures_dir / "analysis.json")]) == 0
    out = capsys.readouterr().out
    assert "알 수 없거나 비관련 id 1개" in out           # 'ghost' 제외 경고
    report = (tmp_path / "reports" / f"{date}.md").read_text(encoding="utf-8")
    assert "수가·의대정원 논의 동시 재개" in report
    assert "메디케이드 확대와 병원 재정" in report
    assert "### 의료인력" in report
    brief = json.loads((tmp_path / "data" / "items" / f"{date}.json").read_text(encoding="utf-8"))
    assert brief["model"] == "테스트"
    assert all(ai["analysis"]["relevant"] for ai in brief["items"])


def test_render_marks_missing_as_irrelevant_and_rejects_unknown(tmp_path, fixtures_dir, monkeypatch, capsys):
    monkeypatch.setenv("POLICYBRIEF_ROOT", str(tmp_path))
    date = "2026-10-26"
    _run(["collect", "--fixtures", str(fixtures_dir), "--date", date])

    partial = {"items": [], "synthesis": {"headline": "빈 분석"}}
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
    assert _run(["render", "--date", date, "--analysis", str(path)]) == 0
    assert "분석되지 않은 항목 3건" in capsys.readouterr().out

    bad = {"items": [{"id": "nope", "relevant": True}], "synthesis": {}}
    path.write_text(json.dumps(bad), encoding="utf-8")
    code = _run(["render", "--date", date, "--analysis", str(path)])
    assert code != 0 and "수집되지 않은 id" in str(code)


def test_weekly_show_and_render(tmp_path, fixtures_dir, monkeypatch, capsys):
    monkeypatch.setenv("POLICYBRIEF_ROOT", str(tmp_path))
    # 3일치 raw: 첫날은 픽스처 수집, 나머지는 첫날 파일을 복사해 날짜와 id만 바꾼다 (10-28은 비워둔다)
    _run(["collect", "--fixtures", str(fixtures_dir), "--date", "2026-10-27"])
    raw_dir = tmp_path / "data" / "raw"
    base = json.loads((raw_dir / "2026-10-27.json").read_text(encoding="utf-8"))
    ids = [it["id"] for it in base["items"]]
    for day, suffix in (("2026-10-29", "xb"), ("2026-10-30", "xc")):   # 'x'는 16진수가 아니라 원래 id와 겹치지 않는다
        copy = json.loads(json.dumps(base))
        copy["date"] = day
        for it in copy["items"]:
            it["id"] = it["id"][:-2] + suffix
            it["title"] = f"{it['title']} ({day})"
        copy["items"].append(dict(base["items"][0]))          # 같은 id가 다른 날 다시 오면 한 번만
        (raw_dir / f"{day}.json").write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8")

    assert _run(["show", "--week", "2026-10-30", "--from", "2026-10-27", "--titles"]) == 0
    captured = capsys.readouterr()
    assert "2026-10-28: 수집 파일 없음" in captured.err
    assert "2026-10-27 ~ 2026-10-30 (4일) 수집 항목 9건" in captured.out
    assert "2026-10-28 없음" in captured.out
    assert captured.out.count("[id=") == 9 and "URL:" not in captured.out

    assert _run(["show", "--week", "2026-10-30", "--from", "2026-10-27", "--ids", f"{ids[0]},nope"]) == 0
    captured = capsys.readouterr()
    assert captured.out.count("[id=") == 1 and "없는 id: nope" in captured.err

    analysis = json.loads((fixtures_dir / "analysis.json").read_text(encoding="utf-8"))
    analysis["synthesis"]["global_outlook"] = "미국 메디케이드 확대 논의가 이어졌다."
    path = tmp_path / "weekly.json"
    path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    assert _run(["render", "--week", "2026-10-30", "--from", "2026-10-27", "--analysis", str(path)]) == 0
    assert "2026-10-27 ~ 2026-10-30: 관련" in capsys.readouterr().out
    report = (tmp_path / "reports" / "2026-10-30.md").read_text(encoding="utf-8")
    assert report.startswith("# 보건의료정책 주간 브리핑 — 2026-10-27 ~ 2026-10-30")
    assert "## 이번 주 핵심 이슈" in report
    assert "**국내 흐름** 수가와 인력" in report and "**해외 흐름** 미국 메디케이드" in report
    brief = json.loads((tmp_path / "data" / "items" / "2026-10-30.json").read_text(encoding="utf-8"))
    assert brief["period_start"] == "2026-10-27" and brief["period_end"] == "2026-10-30"
    assert len(brief["items"]) == 9

    # 기본 7일 범위: --from 없이도 돌고, 일간 렌더는 period 없이 그대로
    assert _run(["render", "--date", "2026-10-27", "--analysis", str(path)]) == 0
    daily = json.loads((tmp_path / "data" / "items" / "2026-10-27.json").read_text(encoding="utf-8"))
    assert daily["period_start"] is None
    assert daily["synthesis"]["global_outlook"].startswith("미국")
    assert (tmp_path / "reports" / "2026-10-27.md").read_text(encoding="utf-8").startswith("# 보건의료정책 데일리 브리핑 — 2026-10-27")
