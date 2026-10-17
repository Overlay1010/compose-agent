"""트랙 도구: duplicate_track.

트랙을 복사해 새 트랙을 만든다. 옥타브를 옮기거나 악기를 바꿔 겹치기("멜로디를 스트링으로 한 옥타브 아래 겹쳐줘")에 쓴다.
voice로 화음에서 맨 위 음만(탑노트) · 맨 아래 음만(베이스 라인) 뽑아 새 트랙으로 만들 수도 있다.
새 멜로디를 지어내지는 않는다 (원래 트랙에 있는 음만 쓴다).
새 트랙 id는 아직 안 쓴 가장 작은 번호(t6 …).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import Note, Project
from app.tools.base import ToolError, ToolResult
from app.tools.instrument import gm_name

MAX_TRACKS = 32
CHORD_GAP = 0.06  # 박. 이만큼 안에 시작한 음은 같은 화음으로 본다 (사람이 친 코드는 조금씩 어긋남)
VOICE_NAMES = {"top": "탑노트", "bottom": "베이스"}


def pick_voice(notes: list[Note], voice: str) -> list[Note]:
    """화음마다 가장 높은(top) · 낮은(bottom) 음만. all이면 그대로."""
    if voice == "all":
        return list(notes)
    groups: list[list[Note]] = []
    for n in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if groups and n.start - groups[-1][0].start <= CHORD_GAP:
            groups[-1].append(n)
        else:
            groups.append([n])
    choose = max if voice == "top" else min
    return [choose(g, key=lambda n: n.pitch) for g in groups]


class DuplicateTrackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(description='복사할 트랙 id (예: "t5")')
    name: str | None = Field(default=None, max_length=40, description='새 트랙 이름. 없으면 "원래 이름 2"')
    octaves: int = Field(default=0, ge=-3, le=3, description="새 트랙을 옮길 옥타브 (겹치기: 한 옥타브 아래 = -1)")
    program: int | None = Field(default=None, ge=0, le=127, description="새 트랙 악기(General MIDI 번호). 없으면 원래 악기")
    voice: Literal["all", "top", "bottom"] = Field(
        default="all",
        description="all = 음 전부 (겹치기 · 복사), top = 화음마다 가장 높은 음만 (탑노트 · 탑라인 · 맨 위 선율), "
        "bottom = 가장 낮은 음만 (코드에서 베이스 라인 뽑기)",
    )


def duplicate_track(project: Project, args: DuplicateTrackArgs) -> ToolResult:
    source = next((t for t in project.tracks if t.id == args.track_id), None)
    if source is None:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {args.track_id}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    if len(project.tracks) >= MAX_TRACKS:
        raise ToolError(f"트랙은 {MAX_TRACKS}개까지만 만들 수 있어요.", code="too_many_tracks")
    if source.is_drum and (args.octaves or args.program is not None or args.voice != "all"):
        raise ToolError(
            "드럼 트랙은 음 번호가 곧 드럼 소리라 옥타브 · 악기 · 화음 고르기(voice) 없이 그대로 복사만 할 수 있어요.",
            code="drum_track",
        )
    picked = pick_voice(source.notes, args.voice)
    shift = args.octaves * 12
    if shift and picked:
        low, high = min(n.pitch for n in picked), max(n.pitch for n in picked)
        if low + shift < 0 or high + shift > 127:
            raise ToolError(
                f"{args.octaves:+d}옥타브 옮기면 MIDI 음 범위(0~127)를 벗어나요. 이 트랙 음역은 {low}~{high}예요.",
                code="out_of_range",
            )

    used = {t.id for t in project.tracks}
    new_id = next(f"t{i}" for i in range(1, MAX_TRACKS + 2) if f"t{i}" not in used)
    names = {t.name for t in project.tracks}
    base = f"{source.name} {VOICE_NAMES[args.voice]}" if args.voice in VOICE_NAMES else source.name
    candidates = [base] if args.voice in VOICE_NAMES else []
    candidates += [f"{base} {i}" for i in range(2, MAX_TRACKS + 2)]
    name = args.name or next(c for c in candidates if c not in names)
    copy = source.model_copy(
        update={
            "id": new_id,
            "name": name,
            "notes": [n.model_copy(update={"pitch": n.pitch + shift}) for n in picked],
            **({"program": args.program, "program_set": True} if args.program is not None else {}),
        }
    )
    how = []
    if args.voice != "all":
        how.append(f"화음마다 맨 {'위' if args.voice == 'top' else '아래'} 음만, 원래 음 {len(source.notes)}개 중")
    if args.octaves:
        how.append(f"{abs(args.octaves)}옥타브 {'위' if args.octaves > 0 else '아래'}")
    if args.program is not None:
        how.append(f"악기 {gm_name(args.program)}")
    detail = f" ({', '.join(how)})" if how else ""
    return ToolResult(
        project=project.model_copy(update={"tracks": [*project.tracks, copy]}),
        changed_notes=len(copy.notes),
        summary=f"{source.name} 트랙을 복사해 새 트랙 {name}({new_id})을 만들었어요{detail}. 음 {len(copy.notes)}개.",
    )
