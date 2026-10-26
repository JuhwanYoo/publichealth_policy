import json
from types import SimpleNamespace

from policybrief.analyze import ClaudeAnalyzer, _ClassifyBatch, _schema
from policybrief.models import Item, Topic


class _FakeMessages:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0),
        )


def _client(payloads):
    msgs = _FakeMessages(payloads)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def _items(n):
    return [Item(id=f"id{i}", source_id="s", source_name="S", category="media_health", lang="ko",
                 title=f"제목 {i}", url=f"https://x.test/{i}", summary="본문") for i in range(n)]


def test_classify_uses_structured_output_and_fills_missing():
    items = _items(2)
    payload = {"items": [{"id": "id0", "relevant": True, "topic": "의료인력", "title_ko": "제목 0",
                          "summary_ko": "요약", "importance": 4, "tags": ["전공의"]}]}
    client, msgs = _client([payload])
    analyzer = ClaudeAnalyzer(model="claude-opus-5-5", client=client)
    out = analyzer.classify(items)
    assert len(out) == 2
    assert out[0].analysis.topic == Topic.WORKFORCE and out[0].analysis.importance == 4
    assert out[1].analysis.tags == ["분류실패"]       # 모델이 빠뜨린 항목은 보수적으로 유지
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    schema = call["output_config"]["format"]["schema"]
    assert schema == _schema(_ClassifyBatch)
    item_schema = schema["$defs"]["ItemAnalysis"]
    assert item_schema["additionalProperties"] is False
    assert set(item_schema["required"]) == set(item_schema["properties"])
    assert "minimum" not in item_schema["properties"]["importance"]
    assert call["output_config"]["effort"] == "low"
    assert analyzer.usage()["input_tokens"] == 100


def test_synthesize_drops_unknown_ids():
    items = _items(1)
    classify = {"items": [{"id": "id0", "relevant": True, "topic": "기타", "title_ko": "t", "summary_ko": "s",
                           "importance": 3, "tags": []}]}
    synth = {"headline": "h", "key_issues": [{"title": "i", "description": "d", "item_ids": ["id0", "ghost"]}],
             "notable_papers": ["ghost"], "policy_outlook": "o"}
    client, _ = _client([classify, synth])
    analyzer = ClaudeAnalyzer(model="claude-opus-5-5", client=client)
    analyzed = analyzer.classify(items)
    s = analyzer.synthesize(analyzed)
    assert s.key_issues[0].item_ids == ["id0"]
    assert s.notable_papers == []
