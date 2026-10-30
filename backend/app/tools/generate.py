"""만들기 도구 (v0.3): add_track · generate_chords.

곡의 코드(v0.2 분석)를 따라 새 트랙에 화음을 깐다. 음은 app/generate의 규칙이 만들고, LLM은 무늬 · 악기 · 음역 · 범위만 고른다.
만든 음은 app/generate/check.py로 한 번 더 검사해 결과(checks)에 적는다.
"다른 버전"은 같은 트랙(track_id)을 version만 올려 다시 만든다 (새 트랙을 또 쌓지 않게). 지금 음과 똑같이 나오면 다음 버전으로.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.generate.chords import pad_notes
from app.generate.check import check
from app.models.project import Project, Track
from app.tools.base import Bar, ToolError, ToolResult
from app.tools.instrument import display_name, kit_name
from app.tools.tracks import free_name, new_track_id

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
EPS = 1e-6
TRIES = 8  # 다른 버전이 지금 음과 같게 나오면 버전을 올려 이만큼 더 해 본다


def _note_name(pitch: int) -> str:
    return f"{NAMES[pitch % 12]}{pitch // 12 - 1}"


class AddTrackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=40, description='새 트랙 이름. 없으면 "Track" (드럼이면 "Drums")')
    program: int | None = Field(default=None, ge=0, le=127, description="악기(General MIDI). 드럼이면 킷 번호. 말이 없으면 비워 둬")
    drums: bool = Field(default=False, description="드럼 트랙 (음 번호가 곧 드럼 소리)")


def add_track(project: Project, args: AddTrackArgs) -> ToolResult:
    new_id = new_track_id(project)
    name = args.name or free_name(project, "Drums" if args.drums else "Track")
    track = Track(
        id=new_id, name=name, is_drum=args.drums, program=args.program or 0, program_set=args.program is not None,
    )
    sound = kit_name(track.program) + " 킷" if args.drums else (display_name(track.program) if args.program is not None else "")
    return ToolResult(
        project=project.model_copy(update={"tracks": [*project.tracks, track]}),
        changed_settings=True,
        summary=f"빈 {'드럼 ' if args.drums else ''}트랙 {name}({new_id})을 만들었어요" + (f" · {sound}" if sound else ""),
    )


class GenerateChordsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: Literal["pad"] = Field(default="pad", description="pad = 코드마다 화음을 길게 누르기 (바닥에 깔리는 패드)")
    program: int | None = Field(
        default=None, ge=0, le=127,
        description="악기(General MIDI). 말이 없으면 비워 둬 — 곡 편성에 맞춰 고른다 (따뜻한 패드 89 · 폴리신스 90 · 스트링 48 …)",
    )
    height: Literal["low", "mid", "high"] | None = Field(
        default=None, description="음역. 말이 없으면 비워 둬 — 베이스와 멜로디 사이 빈 곳. low · high는 거기서 반 옥타브쯤 아래 · 위",
    )
    name: str | None = Field(default=None, max_length=40, description='새 트랙 이름. 없으면 "Pad"')
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    beats: tuple[float, float] | None = Field(default=None, description="[시작, 끝) 박 — 화면에서 고른 부분. bars와 함께 쓰지 마")
    track_id: str | None = Field(
        default=None, description="다시 만들 트랙 (\"다른 버전\"). 주면 새 트랙 대신 이 트랙의 그 범위 음을 바꾼다. 처음 만들 때는 비워 둬",
    )
    version: int = Field(default=1, ge=1, le=99, description="버전 번호. 처음은 1, \"다른 버전\"이면 앞 결과의 버전 + 1")

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
    target = None
    if args.track_id is not None:
        target = next((t for t in project.tracks if t.id == args.track_id), None)
        if target is None or target.is_drum:
            valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks if not t.is_drum)
            raise ToolError(f"다시 만들 수 없는 트랙이에요: {args.track_id}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    # 다시 만들 때는 그 트랙을 빼고 곡을 읽는다 (앞 버전 패드가 코드 읽기 · 음역 · 소리 고르기에 끼지 않게)
    song = project.model_copy(update={"tracks": [t for t in project.tracks if t is not target]})
    program = args.program if args.program is not None else (target.program if target else None)
    lo, hi = start - EPS, (end if end is not None else float("inf")) - EPS
    old = sorted((n.pitch, n.start) for n in target.notes if lo <= n.start < hi) if target else []
    for version in range(args.version, args.version + TRIES):
        notes, plan = pad_notes(song, start, end, args.height, program, version)
        if sorted((n.pitch, n.start) for n in notes) != old:
            break
    if not notes:
        raise ToolError("그 범위에서 읽을 코드가 없어요 (드럼만 있거나 음이 없음). 코드가 있는 곡이나 범위에서 해 주세요.", code="no_chords")
    checks = check(notes, plan.program, chords=plan.chords, starts=(start,))
    sound = f"{display_name(plan.program)} · 음역 {_note_name(plan.low)}~{_note_name(plan.high)}" + (f" · 버전 {version}" if version > 1 else "")
    if target is not None:
        kept = [n for n in target.notes if not lo <= n.start < hi]
        track = target.model_copy(update={
            "notes": sorted([*kept, *notes], key=lambda n: (n.start, n.pitch)),
            "program": plan.program, "program_set": True, **({"name": args.name} if args.name else {}),
        })
        return ToolResult(
            project=project.model_copy(update={"tracks": [track if t is target else t for t in project.tracks]}),
            changed_notes=len(notes),
            summary=f"{track.name}({track.id}) 트랙을 곡의 코드 {len(plan.chords)}개로 다시 깔았어요 · {sound}",
            checks=checks,
        )
    new_id = new_track_id(project)
    name = args.name or free_name(project, "Pad")
    track = Track(id=new_id, name=name, program=plan.program, program_set=True, notes=notes)
    return ToolResult(
        project=project.model_copy(update={"tracks": [*project.tracks, track]}),
        changed_notes=len(notes),
        summary=f"새 트랙 {name}({new_id})에 곡의 코드 {len(plan.chords)}개를 패드로 깔았어요 · {sound}",
        checks=checks,
    )
