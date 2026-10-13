"""템포 도구: set_tempo.

음표 위치를 박 단위로 저장하므로 템포만 바꾸면 마디 · 박 위치는 그대로고 빠르기만 달라진다.
음표는 하나도 안 바뀌지만 곡 설정이 바뀐 것이라 changed_settings로 알린다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.project import Project
from app.tools.base import ToolError, ToolResult

MIN_BPM, MAX_BPM = 20.0, 300.0


class SetTempoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["set", "offset", "scale"] = Field(
        description="set = 이 BPM으로, offset = 지금 BPM에 더하기(빼기는 음수), scale = 지금 BPM에 곱하기"
    )
    value: float = Field(description="set이면 BPM(20~300), offset이면 더할 BPM(-100~100), scale이면 배수(0.25~4)")

    @model_validator(mode="after")
    def _check_value(self) -> "SetTempoArgs":
        low, high = {"set": (MIN_BPM, MAX_BPM), "offset": (-100, 100), "scale": (0.25, 4)}[self.mode]
        if not low <= self.value <= high:
            raise ValueError(f"{self.mode}의 value는 {low:g}~{high:g} 사이여야 해요")
        return self


def set_tempo(project: Project, args: SetTempoArgs) -> ToolResult:
    old = round(project.tempo, 2)  # MIDI에 저장된 템포는 84.0001처럼 끝자리 오차가 있어 표시용으로 반올림
    new = {"set": args.value, "offset": old + args.value, "scale": old * args.value}[args.mode]
    new = round(new, 2)
    if not MIN_BPM <= new <= MAX_BPM:
        raise ToolError(
            f"템포가 {new:g} BPM이 돼서 쓸 수 있는 범위({MIN_BPM:g}~{MAX_BPM:g} BPM)를 넘어요. 지금은 {old:g} BPM이에요.",
            code="out_of_range",
        )
    if abs(new - old) < 0.005:
        return ToolResult(project=project, summary=f"템포가 이미 {old:g} BPM이라 바뀐 게 없어요.")
    return ToolResult(
        project=project.model_copy(update={"tempo": new}),
        changed_settings=True,
        summary=f"템포를 {old:g} → {new:g} BPM으로 바꿨어요. 마디 위치는 그대로예요.",
    )
