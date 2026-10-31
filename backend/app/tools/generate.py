"""만들기 도구 (v0.3): add_track · generate_chords (패드 · 끊어 치기 · 아르페지오) · generate_bassline.

곡의 코드(v0.2 분석)나 사용자가 말한 진행을 따라 새 트랙에 음을 깐다. 음은 app/generate의 규칙이 만들고,
LLM은 무늬 · 스타일 · 악기 · 음역 · 범위만 고른다.
만든 음은 app/generate/check.py로 한 번 더 검사해 결과(checks)에 적는다.
"다른 버전"은 같은 트랙(track_id)을 version만 올려 다시 만든다 (새 트랙을 또 쌓지 않게). 지금 음과 똑같이 나오면 다음 버전으로.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.generate.bass import bass_notes
from app.generate.chords import chord_notes
from app.generate.check import check
from app.models.project import Note, Project, Track
from app.tools.base import Bar, ToolError, ToolResult
from app.tools.instrument import display_name, kit_name
from app.tools.tracks import free_name, new_track_id

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
EPS = 1e-6
TRIES = 8  # 다른 버전이 지금 음과 같게 나오면 버전을 올려 이만큼 더 해 본다
PATTERN_KO = {"pad": "패드", "stab": "끊어 치기", "arpeggio": "아르페지오"}
TRACK_NAMES = {"pad": "Pad", "stab": "Chords", "arpeggio": "Arp"}
STYLE_KO = {"root": "베이스라인으로", "root_fifth": "근음 · 5음 베이스로", "octave": "옥타브 베이스로", "walking": "워킹 베이스로"}


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



class _MakeArgs(BaseModel):
    """만들기 도구가 같이 쓰는 인자: 따라갈 진행 · 범위 · 악기 · 다시 만들기."""

    model_config = ConfigDict(extra="forbid")

    progression: list[str] | None = Field(
        default=None, min_length=1, max_length=16,
        description='사용자가 말한 코드 진행 (예: ["C", "Am", "F", "G"]). 말한 그대로 적어. 없으면 비워 둬 — 곡의 코드를 따른다',
    )
    bars_per_chord: Literal[0.5, 1, 2, 4] = Field(default=1, description="progression에서 한 코드의 마디 수 (\"반 마디씩\" = 0.5)")
    program: int | None = Field(default=None, ge=0, le=127, description="악기(General MIDI). 말이 없으면 비워 둬 — 곡 편성에 맞춰 고른다")
    name: str | None = Field(default=None, max_length=40, description="새 트랙 이름. 없으면 기본 이름")
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    beats: tuple[float, float] | None = Field(default=None, description="[시작, 끝) 박 — 화면에서 고른 부분. bars와 함께 쓰지 마")
    track_id: str | None = Field(
        default=None, description="다시 만들 트랙 (\"다른 버전\"). 주면 새 트랙 대신 이 트랙의 그 범위 음을 바꾼다. 처음 만들 때는 비워 둬",
    )
    version: int = Field(default=1, ge=1, le=99, description="버전 번호. 처음은 1, \"다른 버전\"이면 앞 결과의 버전 + 1")

    @model_validator(mode="after")
    def _check(self) -> "_MakeArgs":
        if self.bars and self.bars[0] > self.bars[1]:
            raise ValueError("bars는 [시작, 끝] 순서여야 해요 (시작 <= 끝).")
        if self.beats and (self.beats[0] < 0 or self.beats[0] >= self.beats[1]):
            raise ValueError("beats는 [시작, 끝) 순서여야 해요 (0 <= 시작 < 끝).")
        if self.bars and self.beats:
            raise ValueError("bars와 beats는 함께 쓸 수 없어요. 하나만 써요.")
        return self


class GenerateChordsArgs(_MakeArgs):
    pattern: Literal["pad", "stab", "arpeggio"] = Field(
        default="pad",
        description="pad = 코드마다 길게 누르기 (바닥에 깔리는 패드) · stab = 리듬으로 끊어 치기 (반주 · 컴핑) · arpeggio = 한 음씩 펼치기",
    )
    height: Literal["low", "mid", "high"] | None = Field(
        default=None, description="음역. 말이 없으면 비워 둬 — 베이스와 멜로디 사이 빈 곳. low · high는 거기서 반 옥타브쯤 아래 · 위",
    )


class GenerateBasslineArgs(_MakeArgs):
    style: Literal["root", "root_fifth", "octave", "walking"] = Field(
        default="root",
        description="root = 근음 (기본) · root_fifth = 근음과 5음 번갈아 · octave = 근음과 옥타브 위 번갈아 (디스코 · 하우스) · walking = 워킹 베이스 (재즈, 4분음표)",
    )


def _make(
    project: Project, args: _MakeArgs, make: Callable[[Project, float, float | None, int | None, int], tuple[list[Note], Any]],
    default_name: str, what: str, key_check: bool = False,
) -> ToolResult:
    """만들기 공통: 범위를 박으로 바꾸고, 다시 만들 트랙이 있으면 그 트랙을 뺀 곡으로 만들어 그 범위만 바꾼다.
    "다른 버전"이 지금 음과 같게 나오면 다음 버전으로. 만든 음은 검사(check)해 결과에 적는다.
    make(곡, 시작, 끝, 악기, 버전) → (음, 계획: program · low · high · chords (· key))."""
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
    # 다시 만들 때는 그 트랙을 빼고 곡을 읽는다 (앞 버전이 코드 읽기 · 음역 · 소리 고르기에 끼지 않게)
    song = project.model_copy(update={"tracks": [t for t in project.tracks if t is not target]})
    program = args.program if args.program is not None else (target.program if target else None)
    lo, hi = start - EPS, (end if end is not None else float("inf")) - EPS
    old = sorted((n.pitch, n.start) for n in target.notes if lo <= n.start < hi) if target else []
    for version in range(args.version, args.version + TRIES):
        try:
            notes, plan = make(song, start, end, program, version)
        except ValueError as e:
            raise ToolError(
                f"모르는 코드 이름이에요: {e}. \"C · Am7 · F#m7b5 · Bbmaj7 · C/E\"처럼 적어 주세요.", code="unknown_chord",
            ) from None
        if sorted((n.pitch, n.start) for n in notes) != old:
            break
    if not notes:
        raise ToolError(
            "그 범위에서 읽을 코드가 없어요 (드럼만 있거나 음이 없음). 진행을 말해 주면(예: C – Am – F – G) 그대로 깔 수 있어요.",
            code="no_chords",
        )
    checks = check(notes, plan.program, chords=plan.chords, key=plan.key if key_check else None, starts=(start,))
    sound = f"{display_name(plan.program)} · 음역 {_note_name(plan.low)}~{_note_name(plan.high)}" + (f" · {plan.feel}" if plan.feel else "")         + (f" · 버전 {version}" if version > 1 else "")
    source = f"진행 {' – '.join(args.progression)}" if args.progression else "곡의 코드"
    if target is not None:
        kept = [n for n in target.notes if not lo <= n.start < hi]
        track = target.model_copy(update={
            "notes": sorted([*kept, *notes], key=lambda n: (n.start, n.pitch)),
            "program": plan.program, "program_set": True, **({"name": args.name} if args.name else {}),
        })
        return ToolResult(
            project=project.model_copy(update={"tracks": [track if t is target else t for t in project.tracks]}),
            changed_notes=len(notes),
            summary=f"{track.name}({track.id}) 트랙을 {source}(코드 {len(plan.chords)}개) {what} 다시 깔았어요 · {sound}",
            checks=checks,
        )
    new_id = new_track_id(project)
    name = args.name or free_name(project, default_name)
    track = Track(id=new_id, name=name, program=plan.program, program_set=True, notes=notes)
    return ToolResult(
        project=project.model_copy(update={"tracks": [*project.tracks, track]}),
        changed_notes=len(notes),
        summary=f"새 트랙 {name}({new_id})에 {source}(코드 {len(plan.chords)}개)를 {what} 깔았어요 · {sound}",
        checks=checks,
    )


def generate_chords(project: Project, args: GenerateChordsArgs) -> ToolResult:
    def make(song: Project, start: float, end: float | None, program: int | None, version: int):
        return chord_notes(song, start, end, args.height, program, version, args.pattern, args.progression, args.bars_per_chord)

    return _make(project, args, make, TRACK_NAMES[args.pattern], f"{PATTERN_KO[args.pattern]}로")


def generate_bassline(project: Project, args: GenerateBasslineArgs) -> ToolResult:
    def make(song: Project, start: float, end: float | None, program: int | None, version: int):
        return bass_notes(song, start, end, args.style, program, version, args.progression, args.bars_per_chord)

    # 베이스는 지나가는 음이 있어 코드 밖 대신 음계 밖으로 검사한다 (코드 음이면 음계 밖이어도 된다)
    return _make(project, args, make, "Bass", STYLE_KO[args.style], key_check=True)
