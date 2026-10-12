"""편집 도구 5개: transpose, shift_octave, quantize, adjust_velocity, swing.

모두 (Project, Args) -> ToolResult 순수 함수. 시간은 박 단위.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.project import Note, Project
from app.tools.base import Selection, ToolError, ToolResult, edit_notes, result, round_beat

# ---------- transpose / shift_octave ----------


class TransposeArgs(Selection):
    semitones: int = Field(ge=-24, le=24, description="옮길 반음 수. 양수면 올리고 음수면 내린다 (12 = 1옥타브)")


class ShiftOctaveArgs(Selection):
    octaves: int = Field(ge=-3, le=3, description="옮길 옥타브 수. 양수면 올리고 음수면 내린다")


def transpose(project: Project, args: TransposeArgs) -> ToolResult:
    return _move_pitch(project, args, args.semitones, f"{abs(args.semitones)}반음")


def shift_octave(project: Project, args: ShiftOctaveArgs) -> ToolResult:
    return _move_pitch(project, args, args.octaves * 12, f"{abs(args.octaves)}옥타브")


def _move_pitch(project: Project, sel: Selection, semitones: int, amount: str) -> ToolResult:
    # 드럼은 음 번호가 곧 악기(36 킥, 38 스네어 …)라서 옮기면 다른 소리가 된다. 그래서 건너뛴다.
    tracks = sel.tracks(project)
    bpb = project.beats_per_bar
    pitches = [n.pitch for t in tracks if not t.is_drum for n in t.notes if sel.has(n, bpb)]
    if pitches and not (0 <= min(pitches) + semitones and max(pitches) + semitones <= 127):
        lo, hi = -min(pitches), 127 - max(pitches)
        raise ToolError(
            f"{amount} 옮기면 MIDI 음 범위(0~127)를 벗어나는 음이 있어요. "
            f"이 선택은 {lo}~+{hi}반음 사이로만 옮길 수 있어요.",
            code="out_of_range",
        )

    new, counts = edit_notes(
        project, sel, lambda n: n.model_copy(update={"pitch": n.pitch + semitones}), skip_drums=True
    )
    verb = "올렸어요" if semitones > 0 else "내렸어요"
    res = result(new, counts, f"을 {amount} {verb}.")
    drums = [t.name for t in tracks if t.is_drum]
    if sel.track_ids and drums:
        res.summary += f" 드럼 트랙({', '.join(drums)})은 음 번호가 곧 악기라서 건너뛰었어요."
    return res


# ---------- quantize ----------

GRIDS = {
    1.0: "4분음표",
    0.5: "8분음표",
    0.25: "16분음표",
    0.125: "32분음표",
    1 / 3: "8분음표 셋잇단",
    1 / 6: "16분음표 셋잇단",
}


class QuantizeArgs(Selection):
    grid: float = Field(
        default=0.25,
        description="격자 간격(박). 1 = 4분음표, 0.5 = 8분, 0.25 = 16분, 0.125 = 32분, "
        "0.3333 = 8분 셋잇단, 0.1667 = 16분 셋잇단",
    )
    strength: float = Field(default=1.0, ge=0, le=1, description="1이면 격자에 딱 맞추고, 0.5면 절반만 당긴다")
    quantize_ends: bool = Field(default=False, description="음 끝 위치도 격자에 맞출지 (기본은 길이 유지)")

    @field_validator("grid")
    @classmethod
    def _known_grid(cls, v: float) -> float:
        # 셋잇단(1/3, 1/6)은 JSON에서 정확히 못 쓰므로 가까운 값이면 받아 준다
        for g in GRIDS:
            if abs(v - g) < 0.01:
                return g
        raise ValueError("grid는 1, 0.5, 0.25, 0.125, 0.3333(셋잇단), 0.1667(셋잇단) 중 하나여야 해요.")


def _snap(x: float, grid: float) -> float:
    return math.floor(x / grid + 0.5) * grid  # 반올림 (파이썬 round는 짝수 쪽으로 가서 안 씀)


def quantize(project: Project, args: QuantizeArgs) -> ToolResult:
    g, s = args.grid, args.strength

    def pull(x: float) -> float:
        return x + (_snap(x, g) - x) * s

    def fix(note: Note) -> Note:
        start = max(0.0, round_beat(pull(note.start)))
        if not args.quantize_ends:
            return note.model_copy(update={"start": start})
        end = round_beat(pull(note.start + note.duration))
        if end <= start:  # 짧은 음이 시작과 같은 칸으로 붙으면 한 칸 길이로
            end = round_beat(start + g)
        return note.model_copy(update={"start": start, "duration": round_beat(end - start)})

    new, counts = edit_notes(project, args, fix)
    extra = [f"강도 {s * 100:.0f}%"] if s < 1 else []
    if args.quantize_ends:
        extra.append("끝 위치 포함")
    detail = f" ({', '.join(extra)})" if extra else ""
    return result(new, counts, f"을 {GRIDS[g]} 격자에 맞췄어요{detail}.", "선택한 음이 이미 격자에 맞아 바뀐 게 없어요.")


# ---------- adjust_velocity ----------

VELOCITY_LIMITS = {"scale": (0.1, 4.0), "offset": (-126, 126), "set": (1, 127)}


class AdjustVelocityArgs(Selection):
    mode: Literal["scale", "offset", "set"] = Field(
        description="scale = 곱하기 (0.7이면 70%로), offset = 더하기 (-20이면 20 낮춤), set = 모두 같은 값으로"
    )
    value: float = Field(description="scale: 0.1~4, offset: -126~126, set: 1~127. 결과 세기는 1~127로 자른다")

    @model_validator(mode="after")
    def _check_value(self) -> "AdjustVelocityArgs":
        lo, hi = VELOCITY_LIMITS[self.mode]
        if not lo <= self.value <= hi:
            raise ValueError(f"{self.mode} 모드의 value는 {lo}~{hi} 사이여야 해요.")
        return self


def adjust_velocity(project: Project, args: AdjustVelocityArgs) -> ToolResult:
    mode, v = args.mode, args.value

    def change(note: Note) -> Note:
        raw = note.velocity * v if mode == "scale" else note.velocity + v if mode == "offset" else v
        return note.model_copy(update={"velocity": max(1, min(127, math.floor(raw + 0.5)))})

    if mode == "scale":
        how = f"{v * 100:.0f}%로 {'줄였어요' if v < 1 else '키웠어요'}"
    elif mode == "offset":
        how = f"{abs(v):g} {'낮췄어요' if v < 0 else '높였어요'}"
    else:
        how = f"모두 {round(v)}에 맞췄어요"
    new, counts = edit_notes(project, args, change)
    return result(new, counts, f"의 세기를 {how}.")


# ---------- swing ----------

OFFBEAT_TOLERANCE = 0.02  # 박. 이만큼 안에 있으면 뒷박에 있는 음으로 본다


class SwingArgs(Selection):
    percent: float = Field(
        ge=50, le=75, description="스윙 정도(%). 50 = 정박(변화 없음), 66 ≈ 셋잇단 느낌, 75 = 가장 강함"
    )
    grid: Literal[0.5, 0.25] = Field(default=0.5, description="스윙할 음표 단위(박). 0.5 = 8분음표, 0.25 = 16분음표")


def swing(project: Project, args: SwingArgs) -> ToolResult:
    # DAW 방식: 격자를 두 칸씩 묶어 두 번째 칸(홀수 번째)에 있는 음만 늦춘다.
    # 60%면 두 칸 길이의 60% 지점으로 → 늦추는 양 = (percent/100*2 - 1) * grid
    g = args.grid
    delay = (args.percent / 100 * 2 - 1) * g

    def push(note: Note) -> Note:
        k = round(note.start / g)
        if k % 2 == 1 and abs(note.start - k * g) <= OFFBEAT_TOLERANCE:
            return note.model_copy(update={"start": round_beat(note.start + delay)})
        return note

    new, counts = edit_notes(project, args, push)
    name = "8분음표" if g == 0.5 else "16분음표"
    nothing = (
        "스윙 50%는 정박이라 바뀐 게 없어요."
        if delay == 0
        else f"{name} 뒷박에 있는 음이 없어 바뀐 게 없어요. 타이밍이 흔들린 곡이면 먼저 퀀타이즈해 보세요."
    )
    return result(new, counts, f"에 {name} 스윙 {args.percent:g}%를 넣었어요.", nothing)
