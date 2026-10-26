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
