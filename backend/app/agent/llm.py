"""LLM 호출을 한 곳에 모은다.

에이전트 루프는 메시지를 OpenAI Chat Completions 형식으로 쌓는다. 각 LLM 클래스가 자기 API 형식으로 바꿔 보낸다.
- AnthropicChat: Claude (Messages API). LLM_PROVIDER=anthropic
- OpenAIChat: OpenAI, 그리고 같은 형식을 쓰는 서버(Ollama · Gemini 등, OPENAI_BASE_URL). LLM_PROVIDER=openai
"""

from __future__ import annotations

import json
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
    cached_tokens: int = 0  # 입력 중 캐시에서 읽은 것 (Claude 프롬프트 캐시)


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
            # 그런 오류면 'none'으로 바꿔 다시 부르고, 이후 호출에도 그대로 쓴다.
            # 이번 요청이 실제로 보낸 값으로 판단한다: 여러 요청이 동시에 실패하면 그중 하나가 먼저
            # self.reasoning_effort를 바꿔 놓아서, 그 값으로 판단하면 나머지는 재시도 없이 실패한다.
            if getattr(e, "param", None) == "reasoning_effort" and extra.get("reasoning_effort") != "none":
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


# ---------- Claude (Anthropic Messages API) ----------

PROMPT_SPLIT = "\n현재 프로젝트\n"  # app/agent/prompt.py: 이 앞(규칙)은 매번 같고, 뒤(프로젝트 요약)는 바뀐다


def to_anthropic(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """OpenAI 형식 메시지 → (system 블록들, messages).

    - 맨 앞 system = 시스템 프롬프트. 규칙 부분과 프로젝트 부분으로 나눠 규칙만 캐시한다.
    - 대화 중간의 system(적용 · 취소 알림)은 Claude에 system 역할이 없어서 사용자 쪽 알림 글로 넣는다.
    - assistant의 tool_calls → tool_use 블록, tool 역할 → 사용자 쪽 tool_result 블록.
    - 같은 역할이 연달아 오면 한 메시지로 합친다 (tool_result 여러 개 등).
    """
    system: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":
            if not out:
                text = content or ""
                cut = text.find(PROMPT_SPLIT)
                parts = [text[:cut], text[cut:]] if cut > 0 else [text]
                system += [{"type": "text", "text": p} for p in parts if p.strip()]
            else:
                push("user", [{"type": "text", "text": f"(알림) {content}"}])
        elif role == "user":
            push("user", [{"type": "text", "text": content or ""}])
        elif role == "assistant":
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            for c in m.get("tool_calls") or []:
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                blocks.append(
                    {"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": args if isinstance(args, dict) else {}}
                )
            if blocks:
                push("assistant", blocks)
        elif role == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content or ""}])
    return system, out


class AnthropicChat:
    """Claude. 도구 설명 · 규칙은 명령마다 같아서 프롬프트 캐시를 건다 (두 번째 호출부터 그 부분은 싸고 빠름)."""

    MAX_TOKENS = 2048  # 도구 호출 + 한두 문장 답이면 충분

    def __init__(self, model: str, api_key: str) -> None:
        import anthropic

        self.model = model
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=60, max_retries=2)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMReply:
        system, msgs = to_anthropic(messages)
        cache = {"type": "ephemeral"}
        tool_defs = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]} for t in tools]
        if tool_defs:
            tool_defs[-1]["cache_control"] = cache  # 도구 설명 전체 (맨 앞이라 모든 명령이 같이 씀)
        if system:
            system[0]["cache_control"] = cache  # 규칙
        if msgs and msgs[-1]["content"]:
            msgs[-1]["content"][-1]["cache_control"] = cache  # 한 명령 안에서 도구 결과를 보고 다시 물을 때
        try:
            r = self._client.messages.create(
                model=self.model, max_tokens=self.MAX_TOKENS, system=system, messages=msgs, tools=tool_defs
            )
        except self._anthropic.APIError as e:
            raise LLMError(f"LLM 호출에 실패했어요: {e}") from e

        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, json.dumps(b.input, ensure_ascii=False)) for b in r.content if b.type == "tool_use"]
        u = r.usage
        # 캐시에서 읽은 · 캐시에 쓴 토큰도 모델이 읽은 입력이다 (비교를 위해 합쳐서 센다)
        read = (u.input_tokens or 0) + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        return LLMReply(
            text=text, tool_calls=calls, input_tokens=read, output_tokens=u.output_tokens or 0,
            cached_tokens=u.cache_read_input_tokens or 0,
        )


def make_llm(model: str | None = None) -> LLM:
    """설정(LLM_PROVIDER)이나 모델 이름(claude-…)으로 LLM을 만든다. 키가 없으면 LLMUnavailable."""
    if model:
        provider = "anthropic" if model.startswith("claude") else "openai"
    else:
        provider = config.LLM_PROVIDER
    if provider == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise LLMUnavailable("ANTHROPIC_API_KEY가 없어요. backend/.env에 넣고 서버를 다시 켜 주세요.")
        return AnthropicChat(model or config.ANTHROPIC_MODEL, config.ANTHROPIC_API_KEY)
    if not config.OPENAI_API_KEY:
        raise LLMUnavailable("OPENAI_API_KEY가 없어요. backend/.env에 넣고 서버를 다시 켜 주세요.")
    return OpenAIChat(model or config.OPENAI_MODEL, config.OPENAI_API_KEY, config.OPENAI_BASE_URL, config.OPENAI_REASONING_EFFORT)


_default: LLM | None = None


def get_llm() -> LLM:
    """API에서 쓰는 기본 LLM (.env 설정). 테스트에서는 FastAPI dependency override로 바꿔 끼운다."""
    global _default
    if _default is None:
        _default = make_llm()
    return _default
