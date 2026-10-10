import io
import json

from backend.app.llm import LLMSettings, QwenProvider


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_qwen_pins_first_tool_when_required_mode_has_multiple_tools(monkeypatch):
    payloads = []
    responses = [
        {
            "output": [{
                "type": "function_call", "name": "catalog", "arguments": "{}", "call_id": "call-1",
            }],
        },
        {
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": '{"selected": true}'}],
            }],
        },
    ]

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        return _Response(json.dumps(responses.pop(0)).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = QwenProvider(LLMSettings("qwen", "not-a-real-key", "https://example.test/v1", "qwen", False))
    tools = [
        {"type": "function", "name": "catalog", "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "search", "parameters": {"type": "object", "properties": {}}},
    ]
    result, trace = provider.generate_json_with_tools(
        "system", "user", tools=tools, tool_handlers={"catalog": lambda _: {"count": 1}},
        force_first_tool=True,
    )

    assert result == {"selected": True}
    assert trace[0]["tool"] == "catalog"
    assert payloads[0]["tool_choice"] == {"type": "function", "name": "catalog"}
    assert payloads[1]["tool_choice"] == "auto"


def test_qwen_finalizes_without_tools_after_tool_round_budget(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data)
        payloads.append(payload)
        round_number = len(payloads)
        response = {
            "output": [{
                "type": "function_call",
                "name": "catalog",
                "arguments": "{}",
                "call_id": f"call-{round_number}",
            }],
        }
        return _Response(json.dumps(response).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = QwenProvider(LLMSettings("qwen", "not-a-real-key", "https://example.test/v1", "qwen", False))
    monkeypatch.setattr(
        provider,
        "generate_json",
        lambda system, user, max_tokens, usage_path=None: {"experiment_ids": ["exp-1"], "rationale": "已有证据足够"},
    )
    tool = {"type": "function", "name": "catalog", "parameters": {"type": "object", "properties": {}}}

    result, trace = provider.generate_json_with_tools(
        "system", "user", tools=[tool], tool_handlers={"catalog": lambda _: {"count": 1}},
        max_tool_rounds=3, force_first_tool=True,
    )

    assert result["experiment_ids"] == ["exp-1"]
    assert len(trace) == 3
    assert len(payloads) == 3


def test_qwen_records_provider_reported_token_usage(monkeypatch, tmp_path):
    response = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _Response(json.dumps(response).encode()),
    )
    provider = QwenProvider(LLMSettings("qwen", "not-a-real-key", "https://example.test/v1", "qwen", False))
    usage_path = tmp_path / "usage.jsonl"

    assert provider.generate_json("system", "user", usage_path=usage_path) == {"ok": True}
    usage = json.loads(usage_path.read_text(encoding="utf-8"))
    assert usage == {
        "model": "qwen", "endpoint": "chat.completions",
        "input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
    }
