"""만들기 도구 (v0.3): generate_chords.

곡의 코드(v0.2 분석)를 따라 새 트랙에 화음을 깐다. 음은 app/generate의 규칙이 만들고, LLM은 무늬 · 악기 · 음역 · 범위만 고른다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.generate.chords import pad_notes
from app.models.project import Project, Track
from app.tools.base import Bar, ToolError, ToolResult
from app.tools.instrument import display_name
from app.tools.tracks import free_name, new_track_id

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _note_name(pitch: int) -> str:
    return f"{NAMES[pitch % 12]}{pitch // 12 - 1}"


class GenerateChordsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: Literal["pad"] = Field(default="pad", description="pad = 코드마다 화음을 길게 누르기 (바닥에 깔리는 패드)")
    program: int | None = Field(
        default=None, ge=0, le=127,
        description="새 트랙 악기(General MIDI). 말이 없으면 비워 둬 — 곡 편성에 맞춰 고른다 (따뜻한 패드 89 · 폴리신스 90 · 스트링 48 …)",
    )
    height: Literal["low", "mid", "high"] | None = Field(
        default=None, description="음역. 말이 없으면 비워 둬 — 베이스와 멜로디 사이 빈 곳. low · high는 거기서 반 옥타브쯤 아래 · 위",
    )
    name: str | None = Field(default=None, max_length=40, description='새 트랙 이름. 없으면 "Pad"')
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    beats: tuple[float, float] | None = Field(default=None, description="[시작, 끝) 박 — 화면에서 고른 부분. bars와 함께 쓰지 마")

    @model_validator(mode="after")
    def _check(self) -> "GenerateChordsArgs":
        if self.bars and self.bars[0] > self.bars[1]:
            raise ValueError("bars는 [시작, 끝] 순서여야 해요 (시작 <= 끝).")
        if self.beats and (self.beats[0] < 0 or self.beats[0] >= self.beats[1]):
            raise ValueError("beats는 [시작, 끝) 순서여야 해요 (0 <= 시작 < 끝).")
        if self.bars and self.beats:
            raise ValueError("bars와 beats는 함께 쓸 수 없어요. 하나만 써요.")
        return self


def generate_chords(project: Project, args: GenerateChordsArgs) -> ToolResult:
    bpb = project.beats_per_bar
    start, end = 0.0, None
    if args.bars:
        start, end = (args.bars[0] - 1) * bpb, args.bars[1] * bpb
    elif args.beats:
        start, end = args.beats
    new_id = new_track_id(project)
    notes, plan = pad_notes(project, start, end, args.height)
    if not notes:
        raise ToolError("그 범위에서 읽을 코드가 없어요 (드럼만 있거나 음이 없음). 코드가 있는 곡이나 범위에서 해 주세요.", code="no_chords")
    program = plan.program if args.program is None else args.program
    name = args.name or free_name(project, "Pad")
    track = Track(id=new_id, name=name, program=program, program_set=True, notes=notes)
    return ToolResult(
        project=project.model_copy(update={"tracks": [*project.tracks, track]}),
        changed_notes=len(notes),
        summary=(
            f"새 트랙 {name}({new_id})에 곡의 코드 {plan.chords}개를 패드로 깔았어요 · "
            f"{display_name(program)} · 음역 {_note_name(plan.low)}~{_note_name(plan.high)}"
        ),
    )
