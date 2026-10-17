"""도구 목록과 실행 진입점. LLM 단계에서는 tool_specs()를 넘기고, 호출이 오면 run_tool()로 실행한다."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.models.project import Project
from app.tools.base import Tool, ToolError, ToolResult
from app.tools.edits import (
    AdjustVelocityArgs,
    QuantizeArgs,
    ShiftOctaveArgs,
    SwingArgs,
    TransposeArgs,
    adjust_velocity,
    quantize,
    shift_octave,
    swing,
    transpose,
)
from app.tools.info import ProjectInfoArgs, get_project_info
from app.tools.instrument import SetInstrumentArgs, set_instrument
from app.tools.tempo import SetTempoArgs, set_tempo

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "get_project_info",
            "템포 · 박자 · 마디 수와 트랙별 id · 이름 · 드럼 여부 · 음 개수 · 음역을 읽는다. "
            "편집 전에 트랙 id를 확인할 때 쓴다. 프로젝트는 바꾸지 않는다.",
            ProjectInfoArgs,
            get_project_info,
        ),
        Tool(
            "transpose",
            "고른 음을 반음 단위로 올리거나 내린다. 드럼 트랙은 건너뛴다.",
            TransposeArgs,
            transpose,
        ),
        Tool(
            "shift_octave",
            "고른 음을 옥타브 단위로 올리거나 내린다. 드럼 트랙은 건너뛴다.",
            ShiftOctaveArgs,
            shift_octave,
        ),
        Tool(
            "quantize",
            "음 시작 위치를 격자에 맞춰 박자를 정리한다. 길이는 그대로 (quantize_ends로 끝도 맞출 수 있음).",
            QuantizeArgs,
            quantize,
        ),
        Tool(
            "adjust_velocity",
            "음 세기(velocity)를 곱하기 · 더하기 · 고정값으로 바꾼다. 결과는 1~127.",
            AdjustVelocityArgs,
            adjust_velocity,
        ),
        Tool(
            "swing",
            "격자의 뒷박(두 칸 중 두 번째)에 있는 음을 늦춰 스윙감을 준다. 앞박과 길이는 그대로.",
            SwingArgs,
            swing,
        ),
        Tool(
            "set_tempo",
            "곡 템포(BPM)를 바꾼다. 음표의 박 위치는 그대로라 마디는 안 바뀌고 빠르기만 달라진다.",
            SetTempoArgs,
            set_tempo,
        ),
        Tool(
            "set_instrument",
            "트랙의 악기(General MIDI 악기 번호)를 바꾼다. 음은 그대로고 소리만 달라진다. 드럼 트랙은 건너뛴다.",
            SetInstrumentArgs,
            set_instrument,
        ),
    ]
}


def tool_specs() -> list[dict[str, Any]]:
    return [t.spec() for t in TOOLS.values()]


def run_tool(project: Project, name: str, args: dict[str, Any] | None = None) -> ToolResult:
    """이름과 인자(dict)로 도구를 실행한다. 인자가 틀리면 어디가 틀렸는지 담아 ToolError."""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"없는 도구예요: {name}. 쓸 수 있는 도구: {', '.join(TOOLS)}", code="unknown_tool")
    try:
        parsed = tool.args_model.model_validate(args or {})
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(map(str, err['loc'])) or '인자'}: {err['msg'].removeprefix('Value error, ')}"
            for err in e.errors()
        )
        hint = ""
        if any(err["type"] in ("less_than_equal", "greater_than_equal") for err in e.errors()):
            hint = " 한 번에 넣을 수 있는 범위를 넘었어요. 나눠서 여러 번 불러 같은 결과를 낼 수 있으면 그렇게 하고, 아니면 다른 값으로 바꾸지 말고 사용자에게 알려 주세요."
        raise ToolError(f"{name} 인자가 올바르지 않아요 — {problems}.{hint}", code="invalid_args") from e
    return tool.fn(project, parsed)
