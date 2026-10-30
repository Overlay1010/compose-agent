"""편집 도구 공통: 음 선택(Selection), 결과(ToolResult), 오류(ToolError), 도구 등록 형식(Tool).

도구는 Project를 받아 새 Project를 돌려준다. 원본은 고치지 않고 version도 올리지 않는다
(버전은 저장소가 붙인다).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.project import Note, Project, Track

Bar = Annotated[int, Field(ge=1)]
Pitch = Annotated[int, Field(ge=0, le=127)]

NOTHING_CHANGED = "선택한 범위에서 바뀐 음이 없어요."


class ToolError(ValueError):
    """도구를 실행할 수 없을 때. API에서는 {"error": {"code", "message"}} 형식으로 바뀐다."""

    def __init__(self, message: str, code: str = "tool_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Selection(BaseModel):
    """편집할 음 고르기. 비워 둔 조건은 '전부'."""

    model_config = ConfigDict(extra="forbid")  # LLM이 인자 이름을 틀리면 조용히 무시하지 않고 오류로

    # 설명은 짧게: 이 네 인자가 거의 모든 도구에 붙어 도구 설명 토큰의 절반을 차지한다 (자세한 쓰임은 시스템 프롬프트 규칙에)
    track_ids: list[str] | None = Field(default=None, description="없으면 모든 트랙")
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    pitches: list[Pitch] | None = Field(default=None, description="이 음 번호만. 없으면 모든 음")
    beats: tuple[float, float] | None = Field(default=None, description="[시작, 끝) 박, 0부터. 화면에서 고른 부분. bars와 함께 쓰지 마")

    @field_validator("track_ids")
    @classmethod
    def _empty_means_all(cls, v: list[str] | None) -> list[str] | None:
        # LLM이 "모든 트랙"을 빈 목록으로 보내는 경우가 있다 (빈 목록 = 아무 트랙도 아님으로 받으면 아무것도 안 바뀜)
        return v or None

    @model_validator(mode="after")
    def _check_bars(self) -> "Selection":
        if self.bars and self.bars[0] > self.bars[1]:
            raise ValueError("bars는 [시작, 끝] 순서여야 해요 (시작 <= 끝).")
        if self.beats is not None:
            if self.beats[0] < 0 or self.beats[0] >= self.beats[1]:
                raise ValueError("beats는 [시작, 끝) 순서여야 해요 (0 <= 시작 < 끝).")
            if self.bars is not None:
                raise ValueError("bars와 beats는 함께 쓸 수 없어요. 하나만 써요.")
        return self

    def tracks(self, project: Project) -> list[Track]:
        """고른 트랙. 없는 id가 있으면 쓸 수 있는 id를 알려 주며 ToolError."""
        if self.track_ids is None:
            return list(project.tracks)
        by_id = {t.id: t for t in project.tracks}
        unknown = [i for i in self.track_ids if i not in by_id]
        if unknown:
            valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
            raise ToolError(
                f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track"
            )
        return [t for t in project.tracks if t.id in self.track_ids]

    def has(self, note: Note, beats_per_bar: float) -> bool:
        if self.pitches is not None and note.pitch not in self.pitches:
            return False
        if self.beats is not None and not (self.beats[0] - 1e-6 <= note.start < self.beats[1] - 1e-6):
            return False
        if self.bars is not None:
            bar = math.floor(note.start / beats_per_bar + 1e-9) + 1
            if not self.bars[0] <= bar <= self.bars[1]:
                return False
        return True


class ToolResult(BaseModel):
    project: Project | None = Field(default=None, description="편집된 새 프로젝트 (읽기 전용 도구는 None)")
    changed_notes: int = 0
    changed_settings: bool = Field(default=False, description="음표 말고 곡 설정(템포 등)이 바뀜")
    summary: str = Field(description="채팅 화면에 보여 줄 한 줄 요약")
    data: dict[str, Any] | None = Field(default=None, description="읽기 도구가 돌려주는 정보")
    view: dict[str, Any] | None = Field(default=None, description="화면에만 보내는 정보 (LLM에는 안 감 — 예: 리하모니 제안 코드 목록)")
    checks: list[str] = Field(default_factory=list, description="만들기 도구: 만든 음 검사에서 걸린 것 (app/generate/check.py). 비어야 정상")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[Project, Any], ToolResult]

    def spec(self) -> dict[str, Any]:
        """LLM 도구 호출에 넘길 형식 (이름 · 설명 · 인자 JSON Schema)."""
        return {"name": self.name, "description": self.description, "input_schema": compact_schema(self.args_model.model_json_schema())}


def compact_schema(s: Any) -> Any:
    """pydantic JSON Schema에서 LLM에게 뜻이 없는 부분을 덜어 낸다 (도구 설명이 입력 토큰의 대부분이라).

    - title: 인자 이름과 같다
    - X | None = None: anyOf [X, null] + default null → X (안 넣으면 없음. 검사는 pydantic이 그대로 한다)
    - 같은 타입 두 개짜리 tuple: prefixItems [a, a] → items a
    """
    if isinstance(s, list):
        return [compact_schema(x) for x in s]
    if not isinstance(s, dict):
        return s
    s = {k: compact_schema(v) for k, v in s.items() if k != "title" or not isinstance(v, str)}
    if s.get("default", ...) is None:
        del s["default"]
    alts = s.get("anyOf")
    if alts and {"type": "null"} in alts:
        rest = [a for a in alts if a != {"type": "null"}]
        s.pop("anyOf")
        s = {**(rest[0] if len(rest) == 1 else {"anyOf": rest}), **s}
    items = s.get("prefixItems")
    if items and all(i == items[0] for i in items):
        s.pop("prefixItems")
        s["items"] = items[0]
    return s


def round_beat(x: float) -> float:
    return round(x, 4)


def edit_notes(
    project: Project, sel: Selection, fn: Callable[[Note], Note], skip_drums: bool = False
) -> tuple[Project, list[tuple[str, int]]]:
    """고른 음에 fn을 적용한 새 Project와, 트랙별 실제로 바뀐 음 수 [(트랙 이름, 개수)]를 돌려준다."""
    ids = {t.id for t in sel.tracks(project) if not (skip_drums and t.is_drum)}
    new = project.model_copy(deep=True)
    bpb = project.beats_per_bar
    counts: list[tuple[str, int]] = []
    for track in new.tracks:
        if track.id not in ids:
            continue
        changed = 0
        for i, note in enumerate(track.notes):
            if not sel.has(note, bpb):
                continue
            edited = fn(note)
            if edited != note:
                track.notes[i] = edited
                changed += 1
        if changed:
            track.notes.sort(key=lambda n: (n.start, n.pitch))
            counts.append((track.name, changed))
    return new, counts


def result(project: Project, counts: list[tuple[str, int]], tail: str, nothing: str = NOTHING_CHANGED) -> ToolResult:
    """edit_notes 결과로 ToolResult를 만든다. tail은 '을 2반음 올렸어요.'처럼 조사부터."""
    total = sum(c for _, c in counts)
    if not total:
        return ToolResult(project=project, changed_notes=0, summary=nothing)
    names = ", ".join(name for name, _ in counts)
    return ToolResult(project=project, changed_notes=total, summary=f"{names} 트랙 {total}개 음{tail}")
