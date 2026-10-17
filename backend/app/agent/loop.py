"""에이전트 루프: LLM이 도구를 고르면 실행하고 결과를 돌려주기를, 답이 나올 때까지 반복한다.

편집은 작업용 사본(draft)에만 쌓인다. 저장소에 버전으로 남기는 건 사용자가 미리보기를 적용할 때다.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, Field

from app import config
from app.agent.llm import LLM
from app.agent.prompt import system_prompt
from app.models.project import Project
from app.tools import ToolError, run_tool, tool_specs

START_OVER = "start_over"
START_OVER_SPEC = {
    "name": START_OVER,
    "description": (
        "이번 명령에서 한 편집과 적용 전 미리보기를 모두 버리고 현재 버전에서 다시 시작한다. "
        "1) 사용자가 '아니', '말고', '대신', '다시'처럼 방금 만든 미리보기를 고치라고 하면 먼저 이걸 부르고 원하는 편집을 처음부터 한다. "
        "2) 나눠서 하다가 중간에 실패해 요청을 다 채우지 못하면, 반쯤 바뀐 상태로 두지 말고 이걸 불러 되돌린 뒤 왜 안 되는지 알려 준다."
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
}

# 진행 상황 알림: (종류, 내용). 화면에 실시간으로 보여 주려고 쓴다 (app/api/chat.py의 스트리밍).
#   "thinking"   LLM에게 묻는 중          {"round": 1}
#   "tool_start" 도구를 부르기 시작       {"name": ..., "args": {...}}
#   "tool_done"  도구가 끝남              ToolStep
OnEvent = Callable[[str, dict[str, Any]], None]

TOO_MANY_STEPS = "한 번에 처리하기엔 단계가 너무 많아서 멈췄어요. 지금까지 바뀐 부분은 미리보기로 보여 드릴게요. 나눠서 다시 말씀해 주세요."


class ToolStep(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    summary: str = Field(description="도구 결과 요약 또는 오류 메시지")
    changed_notes: int = 0
    changed_settings: bool = False  # 템포처럼 음표 말고 곡 설정이 바뀜

    @property
    def changed(self) -> bool:
        return self.ok and (self.changed_notes > 0 or self.changed_settings)


class AgentResult(BaseModel):
    reply: str
    steps: list[ToolStep] = Field(default_factory=list)
    draft: Project | None = Field(default=None, description="바뀐 음이 있을 때만. 없으면 None")
    model: str = ""
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    started_over_at: int | None = Field(default=None, description="start_over를 부른 단계 번호 (미리보기를 버림)")

    @property
    def kept_steps(self) -> list[ToolStep]:
        """마지막 start_over 뒤의 단계 (그 앞 편집은 버려졌다)."""
        return self.steps if self.started_over_at is None else self.steps[self.started_over_at + 1 :]

    @property
    def label(self) -> str:
        """버전 기록에 남길 한 줄 (성공한 편집 요약)."""
        return " · ".join(s.summary for s in self.kept_steps if s.changed)


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

    step = ToolStep(
        name=name, args=args, ok=True, summary=result.summary,
        changed_notes=result.changed_notes, changed_settings=result.changed_settings,
    )
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
    base: Project | None = None,
    on_event: OnEvent | None = None,
) -> AgentResult:
    """project(현재 버전 또는 미리보기)에 message를 적용해 본다. project 자체는 바꾸지 않는다.

    base: 현재 버전(미리보기 전). 주면 start_over 도구가 생겨 이번 명령의 편집과 미리보기를 버리고 base에서 다시 할 수 있다.
    """
    max_steps = max_steps or config.AGENT_MAX_STEPS
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(project, pending)},
        *(history or []),
        {"role": "user", "content": message},
    ]
    tools = tool_specs() + ([START_OVER_SPEC] if base is not None else [])
    draft = project
    out = AgentResult(reply="", model=llm.model)
    emit = on_event or (lambda kind, data: None)

    for round_no in range(1, max_steps + 1):
        emit("thinking", {"round": round_no})
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
            try:
                shown_args = json.loads(call.arguments or "{}")
            except ValueError:
                shown_args = {}
            emit("tool_start", {"name": call.name, "args": shown_args if isinstance(shown_args, dict) else {}})
            if call.name == START_OVER and base is not None:
                draft = base
                out.started_over_at = len(out.steps)
                step = ToolStep(name=START_OVER, ok=True, summary=f"미리보기를 버리고 v{base.version}에서 다시 시작해요.")
                content = {"ok": True, "summary": step.summary}
            else:
                draft, step, content = _run_call(draft, call.name, call.arguments)
            out.steps.append(step)
            emit("tool_done", step.model_dump())
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(content, ensure_ascii=False)})
    else:
        out.reply = TOO_MANY_STEPS

    if any(s.changed for s in out.kept_steps):
        out.draft = draft
    return out
