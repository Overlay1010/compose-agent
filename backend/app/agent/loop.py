"""에이전트 루프: LLM이 도구를 고르면 실행하고 결과를 돌려주기를, 답이 나올 때까지 반복한다.

편집은 작업용 사본(draft)에만 쌓인다. 저장소에 버전으로 남기는 건 사용자가 미리보기를 적용할 때다.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app import config
from app.agent.llm import LLM
from app.agent.prompt import system_prompt
from app.models.project import Project
from app.tools import ToolError, run_tool, tool_specs

TOO_MANY_STEPS = "한 번에 처리하기엔 단계가 너무 많아서 멈췄어요. 지금까지 바뀐 부분은 미리보기로 보여 드릴게요. 나눠서 다시 말씀해 주세요."


class ToolStep(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    summary: str = Field(description="도구 결과 요약 또는 오류 메시지")
    changed_notes: int = 0


class AgentResult(BaseModel):
    reply: str
    steps: list[ToolStep] = Field(default_factory=list)
    draft: Project | None = Field(default=None, description="바뀐 음이 있을 때만. 없으면 None")
    model: str = ""
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def label(self) -> str:
        """버전 기록에 남길 한 줄 (성공한 편집 요약)."""
        return " · ".join(s.summary for s in self.steps if s.ok and s.changed_notes)


def _run_call(draft: Project, name: str, raw_args: str) -> tuple[Project, ToolStep, dict[str, Any]]:
    """도구 하나를 실행해 (새 draft, 기록, LLM에 돌려줄 내용)을 만든다. 실패해도 예외를 던지지 않는다."""
    try:
        args = json.loads(raw_args or "{}")
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        msg = "인자는 JSON 객체여야 해요."
        return draft, ToolStep(name=name, ok=False, summary=msg), {"ok": False, "error": msg}

    try:
        result = run_tool(draft, name, args)
    except ToolError as e:
        return draft, ToolStep(name=name, args=args, ok=False, summary=e.message), {"ok": False, "error": e.message}

    step = ToolStep(name=name, args=args, ok=True, summary=result.summary, changed_notes=result.changed_notes)
    content: dict[str, Any] = {"ok": True, "summary": result.summary, "changed_notes": result.changed_notes}
    if result.data is not None:
        content["data"] = result.data
    return result.project or draft, step, content


def run_agent(
    project: Project,
    message: str,
    llm: LLM,
    history: list[dict[str, Any]] | None = None,
    pending: list[str] | None = None,
    max_steps: int | None = None,
) -> AgentResult:
    """project(현재 버전 또는 미리보기)에 message를 적용해 본다. project 자체는 바꾸지 않는다."""
    max_steps = max_steps or config.AGENT_MAX_STEPS
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(project, pending)},
        *(history or []),
        {"role": "user", "content": message},
    ]
    tools = tool_specs()
    draft = project
    out = AgentResult(reply="", model=llm.model)

    for _ in range(max_steps):
        reply = llm.complete(messages, tools)
        out.llm_calls += 1
        out.input_tokens += reply.input_tokens
        out.output_tokens += reply.output_tokens

        if not reply.tool_calls:
            out.reply = reply.text.strip() or "알겠어요."
            break

        messages.append(
            {
                "role": "assistant",
                "content": reply.text or None,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in reply.tool_calls
                ],
            }
        )
        for call in reply.tool_calls:
            draft, step, content = _run_call(draft, call.name, call.arguments)
            out.steps.append(step)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(content, ensure_ascii=False)})
    else:
        out.reply = TOO_MANY_STEPS

    if any(s.ok and s.changed_notes for s in out.steps):
        out.draft = draft
    return out
