import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dotenv import dotenv_values


class LLMError(RuntimeError):
    """不包含密钥和请求头的模型调用错误。"""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str
    base_url: str
    model: str
    enable_thinking: bool

    @classmethod
    def load(cls) -> "LLMSettings":
        env_path = Path(__file__).resolve().parents[1] / ".env"
        file_values = dotenv_values(env_path) if env_path.exists() else {}

        def value(name: str, default: str = "") -> str:
            file_value = file_values.get(name)
            if file_value not in (None, ""):
                return str(file_value)
            return os.getenv(name) or default

        return cls(
            provider=value("MODEL_PROVIDER", "rules").lower(),
            api_key=value("DASHSCOPE_API_KEY"),
            base_url=value("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/"),
            model=value("QWEN_MODEL", "qwen3.6-plus"),
            enable_thinking=value("QWEN_ENABLE_THINKING", "false").lower() == "true",
        )


class QwenProvider:
    name = "qwen"

    def __init__(self, settings: LLMSettings):
        if not settings.api_key:
            raise LLMError("MODEL_PROVIDER=qwen，但未配置 DASHSCOPE_API_KEY")
        self.settings = settings

    def _record_usage(self, result: dict[str, Any], endpoint: str, usage_path: Path | None = None) -> None:
        usage = result.get("usage") or {}
        if not isinstance(usage, dict):
            return
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or input_tokens + output_tokens)
        record = {
            "model": self.settings.model,
            "endpoint": endpoint,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
        target = usage_path or (Path(value) if (value := os.getenv("RESEARCHVIZ_USAGE_FILE")) else None)
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 2400,
        usage_path: Path | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_tokens,
            "enable_thinking": self.settings.enable_thinking,
        }
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
            self._record_usage(result, "chat.completions", usage_path)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(raw).get("error", {})
                message = detail.get("message") or detail.get("code") or f"HTTP {exc.code}"
            except json.JSONDecodeError:
                message = f"HTTP {exc.code}"
            raise LLMError(f"Qwen 调用失败: {message}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise LLMError(f"Qwen 网络请求失败: {type(exc).__name__}") from exc

        try:
            content = result["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("Qwen 未返回有效 JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMError("Qwen 输出必须是 JSON 对象")
        return parsed

    def generate_json_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
        max_tool_rounds: int = 3,
        max_tokens: int = 2400,
        force_first_tool: bool = False,
        usage_path: Path | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        conversation: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        trace: list[dict[str, Any]] = []
        endpoint = f"{self.settings.base_url}/responses"

        for round_index in range(max_tool_rounds + 1):
            if round_index >= max_tool_rounds:
                # Qwen may keep emitting function_call items even when tools are
                # omitted from a final Responses request. End the ReAct loop at
                # the configured budget and use a tool-free JSON call to turn
                # the collected evidence into the required final object.
                evidence_parts = []
                for item in trace:
                    evidence_parts.append({
                        "round": item["round"],
                        "tool": item["tool"],
                        "arguments": item["arguments"],
                        "result": item["result"],
                    })
                evidence = json.dumps(evidence_parts, ensure_ascii=False, default=str)
                if len(evidence) > 30000:
                    evidence = evidence[:30000] + "\n[工具证据因长度限制已截断]"
                final = self.generate_json(
                    system_prompt + "\n工具调用已经终止。只能基于已有证据返回最终 JSON，不得请求或描述新的工具调用。",
                    f"{user_prompt}\n\n已有工具证据：\n{evidence}",
                    max_tokens=max_tokens,
                    usage_path=usage_path,
                )
                return final, trace

            payload = {
                "model": self.settings.model,
                "instructions": system_prompt,
                "input": conversation,
                "max_output_tokens": max_tokens,
                "enable_thinking": self.settings.enable_thinking,
            }
            if round_index < max_tool_rounds:
                payload["tools"] = tools
                if force_first_tool and round_index == 0:
                    # Qwen Responses rejects `required` when several tools are
                    # registered. Pin the first tool explicitly, then return to
                    # auto mode on subsequent ReAct rounds.
                    payload["tool_choice"] = (
                        "required" if len(tools) == 1
                        else {"type": "function", "name": tools[0]["name"]}
                    )
                else:
                    payload["tool_choice"] = "auto"
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    result = json.load(response)
                self._record_usage(result, "responses", usage_path)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                try:
                    body = json.loads(raw)
                    detail = body.get("error", {}) if isinstance(body, dict) else {}
                    if isinstance(detail, dict):
                        message = (
                            detail.get("message") or detail.get("code")
                            or body.get("message") or body.get("code") or f"HTTP {exc.code}"
                        )
                    else:
                        message = str(detail) or body.get("message") or body.get("code") or f"HTTP {exc.code}"
                except (json.JSONDecodeError, AttributeError):
                    message = raw[:500] or f"HTTP {exc.code}"
                raise LLMError(f"Qwen Responses API 调用失败: {message}") from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                raise LLMError(f"Qwen Responses API 网络请求失败: {type(exc).__name__}") from exc

            output = result.get("output", [])
            function_calls = [item for item in output if item.get("type") == "function_call"]
            if function_calls:
                for call in function_calls:
                    name = call.get("name", "")
                    if name not in tool_handlers:
                        raise LLMError(f"模型请求了未注册工具: {name}")
                    try:
                        arguments = json.loads(call.get("arguments") or "{}")
                    except json.JSONDecodeError as exc:
                        raise LLMError(f"工具 {name} 参数不是有效 JSON") from exc
                    if not isinstance(arguments, dict):
                        raise LLMError(f"工具 {name} 参数必须是 JSON 对象")
                    tool_result = tool_handlers[name](arguments)
                    trace.append({"round": round_index + 1, "tool": name, "arguments": arguments, "result": tool_result})
                    conversation.append(
                        {
                            "type": "function_call",
                            "name": name,
                            "arguments": call.get("arguments") or "{}",
                            "call_id": call.get("call_id"),
                        }
                    )
                    conversation.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.get("call_id"),
                            "output": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )
                continue

            texts: list[str] = []
            for item in output:
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        texts.append(content["text"])
            content = (result.get("output_text") or "\n".join(texts)).strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise LLMError("Qwen Function Calling 最终输出不是有效 JSON") from exc
            if not isinstance(parsed, dict):
                raise LLMError("Qwen Function Calling 最终输出必须是 JSON 对象")
            return parsed, trace

        raise LLMError("Qwen Function Calling 未生成最终结果")


def get_llm_provider() -> QwenProvider | None:
    settings = LLMSettings.load()
    if settings.provider == "rules":
        return None
    if settings.provider != "qwen":
        raise LLMError(f"不支持的 MODEL_PROVIDER: {settings.provider}")
    return QwenProvider(settings)
