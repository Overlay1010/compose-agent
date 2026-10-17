"""연주 느낌 도구: humanize(사람이 친 느낌), velocity_ramp(점점 세게 · 여리게).

모두 (Project, Args) -> ToolResult 순수 함수. 시간은 박 단위.
humanize는 무작위지만 seed가 같으면 결과도 같다 (미리보기 · 적용 · 평가에서 똑같이 나오게).
"""

from __future__ import annotations

import math
import random

from pydantic import Field

from app.models.project import Note, Project
from app.tools.base import Selection, ToolResult, edit_notes, result, round_beat

# ---------- humanize ----------


class HumanizeArgs(Selection):
    timing: float = Field(
        default=0.02, ge=0, le=0.08, description="시작 위치를 앞뒤로 흔들 최대 폭(박). 0.01 살짝, 0.02 보통, 0.04 많이"
    )
    velocity: int = Field(default=10, ge=0, le=30, description="세기를 위아래로 흔들 최대 폭. 6 살짝, 10 보통, 18 많이")
    seed: int = Field(default=0, ge=0, description="무작위 시드. 같은 설정으로 '다른 느낌'을 원하면 다른 값으로")


def humanize(project: Project, args: HumanizeArgs) -> ToolResult:
    rng = random.Random(args.seed)

    def shake(note: Note) -> Note:
        # 가운데에 몰리는 분포(두 균등분포의 평균)라 대부분은 조금, 가끔 크게 흔들린다
        dt = (rng.uniform(-1, 1) + rng.uniform(-1, 1)) / 2 * args.timing
        dv = (rng.uniform(-1, 1) + rng.uniform(-1, 1)) / 2 * args.velocity
        return note.model_copy(
            update={
                "start": max(0.0, round_beat(note.start + dt)),
                "velocity": max(1, min(127, math.floor(note.velocity + dv + 0.5))),
            }
        )

    new, counts = edit_notes(project, args, shake)
    return result(
        new,
        counts,
        f"을 사람이 친 것처럼 흔들었어요 (박자 ±{args.timing:g}박 · 세기 ±{args.velocity}).",
        "흔들 폭이 0이라 바뀐 게 없어요.",
    )


# ---------- velocity_ramp ----------


class VelocityRampArgs(Selection):
    start: float = Field(ge=0.1, le=2.0, description="범위 처음의 세기 배율 (1 = 그대로)")
    end: float = Field(ge=0.1, le=2.0, description="범위 끝의 세기 배율. 점점 작게 = start 1, end 0.4 / 점점 크게 = start 0.5, end 1")


def velocity_ramp(project: Project, args: VelocityRampArgs) -> ToolResult:
    # 배율은 범위 시작 → 끝까지 시간에 따라 곧게 바뀐다. 범위는 bars가 있으면 그 마디, 없으면 고른 음 전체
    bpb = project.beats_per_bar
    picked = [n for t in args.tracks(project) for n in t.notes if args.has(n, bpb)]
    if not picked:
        return ToolResult(project=project, summary="선택한 범위에 음이 없어요.")
    if args.bars:
        begin, finish = (args.bars[0] - 1) * bpb, args.bars[1] * bpb
    else:
        begin, finish = min(n.start for n in picked), max(n.start for n in picked)
    span = max(finish - begin, 1e-9)

    def ramp(note: Note) -> Note:
        k = min(1.0, max(0.0, (note.start - begin) / span))
        scale = args.start + (args.end - args.start) * k
        return note.model_copy(update={"velocity": max(1, min(127, math.floor(note.velocity * scale + 0.5)))})

    direction = "점점 세게" if args.end > args.start else "점점 여리게"
    new, counts = edit_notes(project, args, ramp)
    return result(new, counts, f"을 {direction} 바꿨어요 (세기 {args.start * 100:.0f}% → {args.end * 100:.0f}%).")
