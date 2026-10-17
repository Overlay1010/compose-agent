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
from app.tools.drums import SetDrumSoundArgs, set_drum_sound
from app.tools.feel import HumanizeArgs, VelocityRampArgs, humanize, velocity_ramp
from app.tools.info import ProjectInfoArgs, get_project_info
from app.tools.instrument import SetInstrumentArgs, set_instrument
from app.tools.mix import SetMixArgs, set_mix
from app.tools.notes import CopyBarsArgs, DeleteNotesArgs, SetLengthArgs, copy_bars, delete_notes, set_length
from app.tools.tempo import SetTempoArgs, set_tempo
from app.tools.tracks import DuplicateTrackArgs, duplicate_track

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
        Tool(
            "delete_notes",
            "고른 음을 지운다 (트랙 · 마디 · 음 번호로 범위를 정함). 곡 전체를 한 번에 지울 수는 없다.",
            DeleteNotesArgs,
            delete_notes,
        ),
        Tool(
            "set_length",
            "고른 음의 길이를 바꾼다: 곱하기(스타카토 = 0.5), 같은 길이로 맞추기, 레가토(다음 음까지 이어지게). 드럼은 건너뛴다.",
            SetLengthArgs,
            set_length,
        ),
        Tool(
            "copy_bars",
            "마디 범위를 다른 마디로 복사한다. times로 여러 번 이어 붙여 반복할 수 있다. 기본은 붙일 자리의 음을 지우고 넣는다.",
            CopyBarsArgs,
            copy_bars,
        ),
        Tool(
            "humanize",
            "사람이 친 것처럼 음 시작 위치와 세기를 조금씩 무작위로 흔든다 (퀀타이즈의 반대).",
            HumanizeArgs,
            humanize,
        ),
        Tool(
            "velocity_ramp",
            "범위 처음부터 끝까지 세기를 점점 바꾼다 (크레셴도 · 디크레셴도 · 페이드 인/아웃).",
            VelocityRampArgs,
            velocity_ramp,
        ),
        Tool(
            "set_mix",
            "트랙 전체의 볼륨(페이더)과 좌우 위치(팬)를 바꾼다. 곡 전체에만 걸리고 마디 범위는 정할 수 없다 (\"9마디부터 약하게\"처럼 마디가 붙으면 adjust_velocity). 음 세기는 그대로.",
            SetMixArgs,
            set_mix,
        ),
        Tool(
            "duplicate_track",
            "트랙을 복사해 새 트랙을 만든다. 옥타브를 옮기거나 악기를 바꿔 겹치기(더블링)에 쓴다. 결과에 새 트랙 id가 나온다.",
            DuplicateTrackArgs,
            duplicate_track,
        ),
        Tool(
            "set_drum_sound",
            "드럼 트랙에서 소리 하나(레인)만 다른 소리로 바꾼다 (예: 탐만 808 탐으로). 같은 역할의 소리끼리만. 킷 전체는 set_instrument.",
            SetDrumSoundArgs,
            set_drum_sound,
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
