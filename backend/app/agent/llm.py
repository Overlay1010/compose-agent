"""LLM 호출을 한 곳에 모은다.

메시지 형식은 OpenAI Chat Completions를 그대로 쓴다. Ollama · Gemini 같은 서버도 같은 형식을
지원해서, 다른 모델과 비교할 때는 OPENAI_BASE_URL과 OPENAI_MODEL만 바꾸면 된다.
형식이 다른 API(Anthropic 등)를 붙일 때는 LLM 프로토콜을 따르는 클래스를 하나 더 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app import config


class LLMUnavailable(RuntimeError):
    """API 키가 없어서 LLM을 쓸 수 없을 때."""


class LLMError(RuntimeError):
    """LLM 호출이 실패했을 때 (네트워크, 인증, 사용량 한도 등)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # LLM이 준 JSON 문자열 그대로. 파싱과 검증은 에이전트 루프에서 한다


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    model: str

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply: ...


def to_openai_tool(spec: dict[str, Any]) -> dict[str, Any]:
    """registry.tool_specs()의 한 항목 → OpenAI function tool 형식."""
    return {
        "type": "function",
        "function": {"name": spec["name"], "description": spec["description"], "parameters": spec["input_schema"]},
    }


class OpenAIChat:
    def __init__(
        self, model: str, api_key: str, base_url: str | None = None, reasoning_effort: str | None = None
    ) -> None:
        import openai

        self.model = model
        self.reasoning_effort = reasoning_effort
        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=60, max_retries=2)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply:
        extra: dict[str, Any] = {}
        if self.reasoning_effort:
            extra["reasoning_effort"] = self.reasoning_effort
        try:
            r = self._client.chat.completions.create(
                model=self.model, messages=messages, tools=[to_openai_tool(t) for t in tools], **extra
            )
        except self._openai.BadRequestError as e:
            # 일부 추론 모델은 Chat Completions에서 도구를 쓰려면 reasoning_effort를 'none'으로 꼭 지정해야 한다.
            # 그런 오류면 한 번만 'none'으로 바꿔 다시 부르고, 이후 호출에도 그대로 쓴다.
            if getattr(e, "param", None) == "reasoning_effort" and self.reasoning_effort != "none":
                self.reasoning_effort = "none"
                return self.complete(messages, tools)
            raise LLMError(f"LLM 호출에 실패했어요: {e}") from e
        except self._openai.OpenAIError as e:
            raise LLMError(f"LLM 호출에 실패했어요: {e}") from e

        msg = r.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in (msg.tool_calls or [])]
        usage = r.usage
        return LLMReply(
            text=msg.content or "",
            tool_calls=calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


_default: LLM | None = None


def get_llm() -> LLM:
    """API에서 쓰는 기본 LLM (.env 설정). 테스트에서는 FastAPI dependency override로 바꿔 끼운다."""
    global _default
    if _default is None:
        if not config.OPENAI_API_KEY:
            raise LLMUnavailable("OPENAI_API_KEY가 없어요. backend/.env에 넣고 서버를 다시 켜 주세요.")
        _default = OpenAIChat(
            config.OPENAI_MODEL, config.OPENAI_API_KEY, config.OPENAI_BASE_URL, config.OPENAI_REASONING_EFFORT
        )
    return _default
