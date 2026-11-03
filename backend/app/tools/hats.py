"""깔린 하이햇 손보기: vary_hats.

"햇을 중간중간 듬성듬성 · 오픈햇 조금 더"를 처음에는 할 도구가 없어서, 에이전트가 3~6마디 닫힌 햇을 통째로 지우거나
(delete_notes) 단순하게 다시 만들었다 (8분 간격 그대로라 여전히 일정). 여기서는 있는 하이햇을 그대로 두고
마디마다 다른 자리에서 한두 개씩 비우거나, 열린 햇을 더하거나(닫힌 햇은 그대로), 닫힌 햇을 열린 햇으로 바꾼다.
"""

from __future__ import annotations

import math
from random import Random
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.project import Note, Project, Track
from app.tools.base import Bar, ToolError, ToolResult

CLOSED = {42, 44}  # 닫힌 · 페달 햇
OPEN = 46
ROLL_GAP = 0.2  # 박. 이보다 붙은 햇은 롤(32분 · 셋잇단) — 비우거나 열지 않는다
OPEN_MIN_VELOCITY = 80  # 열린 햇은 너무 작으면 안 들린다
# 비우기: 한 마디에 구멍 몇 개 · 구멍 하나에 몇 타 · 구멍 뒤 가장 긴 빈틈(박) · 비우는 마디 비율
SPACE = {"little": ((1, 1), (1, 2), 1.0, 0.75), "more": ((1, 2), (1, 2), 1.5, 1.0)}
OPEN_SPOTS = {1.5: 3, 3.5: 3, 0.5: 1, 2.5: 1}  # 마디 안 박 → 고를 비중 (2 · 4박 뒤 8분이 가장 흔한 자리)


class VaryHatsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_ids: list[str] | None = Field(default=None, description="없으면 하이햇이 있는 드럼 트랙 모두")
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    space: Literal["none", "little", "more"] = Field(
        default="none", description="닫힌 햇을 군데군데 비우기 — little = 마디마다 한두 개, more = 더 듬성듬성, none = 안 비움"
    )
    open_hats: Literal["same", "more", "swap", "fewer"] = Field(
        default="same",
        description="more = 닫힌 햇은 그대로 두고 열린 햇을 더한다, swap = 닫힌 햇 몇 개를 열린 햇으로 바꾼다, fewer = 열린 햇을 줄인다",
    )
    version: int = Field(default=1, ge=1, le=99, description="같은 요청을 다른 자리로 = +1")

    @model_validator(mode="after")
    def _something(self) -> "VaryHatsArgs":
        if self.bars and self.bars[0] > self.bars[1]:
            raise ValueError("bars는 [시작, 끝] 순서여야 해요 (시작 <= 끝).")
        if self.space == "none" and self.open_hats == "same":
            raise ValueError("space나 open_hats 중 하나는 바꿔야 해요.")
        return self


def _slot(beat: float) -> float:
    """가장 가까운 16분 자리 (손으로 친 곡은 박에서 조금씩 어긋나 있다)"""
    return round(beat * 4) / 4


def _rolled(hats: list[Note]) -> set[int]:
    """롤에 든 햇 (앞이나 뒤 햇과 ROLL_GAP보다 붙음)의 위치"""
    out: set[int] = set()
    for i in range(len(hats) - 1):
        if hats[i + 1].start - hats[i].start < ROLL_GAP:
            out |= {i, i + 1}
    return out


def _longest_gap(starts: list[float], bar_start: float, bpb: float) -> float:
    edges = [bar_start, *starts, bar_start + bpb]
    return max(b - a for a, b in zip(edges, edges[1:]))


def _space_bar(hats: list[Note], bar_start: float, bpb: float, rng: Random, level: str, before: set[float]) -> set[int]:
    """한 마디에서 비울 닫힌 햇의 위치. 마디 첫 박 · 롤은 그대로, 앞 마디에서 비운 자리는 피한다 (똑같이 비면 또 규칙처럼 들림)"""
    holes, size, max_gap, share = SPACE[level]
    if rng.random() >= share:
        return set()
    rolled = _rolled(hats)
    pos = [_slot(n.start - bar_start) for n in hats]
    picked: set[int] = set()
    for _ in range(rng.randint(*holes)):
        cands = [i for i in range(len(hats)) if i not in picked and i not in rolled and pos[i] > 1e-6 and pos[i] not in before]
        weights = [3 if pos[i] % 1 else 1 for i in cands]  # 뒷박 · 16분이 비어야 덜 어색하다
        for _ in range(8):
            if not cands:
                break
            i = rng.choices(cands, weights)[0]
            run = [i] + ([i + 1] if rng.randint(*size) == 2 and i + 1 < len(hats) and i + 1 not in rolled else [])
            trial = picked | set(run)
            kept = [hats[j].start for j in range(len(hats)) if j not in trial]
            if len(trial) <= len(hats) * 0.4 and _longest_gap(kept, bar_start, bpb) <= max_gap + 1e-6:
                picked = trial
                break
    return picked


def _open_bar(hats: list[Note], gone: set[int], bar_start: float, rng: Random, before: float | None) -> int | None:
    """닫힌 햇 하나를 열린 햇으로 바꿀 위치. 뒷박 8분 중에서, 앞 마디에서 연 자리는 피한다"""
    rolled = _rolled(hats)
    cands = [
        i for i, n in enumerate(hats)
        if i not in gone and i not in rolled and _slot(n.start - bar_start) in OPEN_SPOTS and _slot(n.start - bar_start) != before
    ]
    if not cands:
        return None
    return rng.choices(cands, [OPEN_SPOTS[_slot(hats[i].start - bar_start)] for i in cands])[0]


def _add_open(hats: list[Note], gone: set[int], opens: list[Note], bar_start: float, rng: Random,
              before: float | None) -> tuple[float, int, bool] | None:
    """닫힌 햇은 그대로 두고 열린 햇을 더할 자리 (박, 세기, 빈자리였나). 뒷박 8분 중 비어 있는 자리를 먼저 (비운 햇 자리 포함),
    없으면 그 자리의 닫힌 햇에 겹친다. 롤 안 · 이미 열린 햇이 있는 자리 · 앞 마디에서 더한 자리는 피한다.
    "오픈햇 추가"를 닫힌 햇을 바꾸는 것으로만 했더니 "닫힌 햇은 안 건드리면서 열린 햇 추가"를 못 했다."""
    rolled = _rolled(hats)
    kept = [n for i, n in enumerate(hats) if i not in gone]
    level = round(sum(n.velocity for n in kept) / len(kept)) if kept else 90
    cands: list[tuple[float, int, bool]] = []
    weights: list[int] = []
    for spot, weight in OPEN_SPOTS.items():
        at = bar_start + spot
        if spot == before or any(abs(o.start - at) < 0.1 for o in opens):
            continue
        if any(abs(hats[i].start - at) < ROLL_GAP for i in rolled):
            continue
        near = next((n for n in kept if abs(n.start - at) < 0.07), None)
        if near is None:
            cands.append((round(at, 4), level, True))
            weights.append(weight * 3)
        else:  # 닫힌 햇과 같은 순간 (손으로 친 곡은 그 햇의 어긋난 박 그대로)
            cands.append((near.start, near.velocity, False))
            weights.append(weight)
    return rng.choices(cands, weights)[0] if cands else None


def _vary(track: Track, args: VaryHatsArgs, bpb: float) -> tuple[list[Note], int, int, int, int, int]:
    """(새 음, 군데군데 비운 수, 바꾼 수, 빈자리에 더한 수, 겹쳐 더한 수, 닫은 수)"""
    def bar_of(n: Note) -> int:
        return math.floor(n.start / bpb + 1e-9) + 1

    in_range = (lambda b: True) if args.bars is None else (lambda b: args.bars[0] <= b <= args.bars[1])  # noqa: E731
    by_bar: dict[int, list[Note]] = {}
    for n in track.notes:
        if n.pitch in CLOSED and in_range(bar_of(n)):
            by_bar.setdefault(bar_of(n), []).append(n)
    drop: set[int] = set()  # id(note)
    spaced = 0
    opened: dict[int, Note] = {}
    extra: list[Note] = []
    filled = 0
    spaced_before: set[float] = set()
    opened_before: float | None = None
    for bar in sorted(by_bar):
        hats = sorted(by_bar[bar], key=lambda n: n.start)
        start = (bar - 1) * bpb
        rng = Random(f"{track.id}:{bar}:{args.version}")
        gone = _space_bar(hats, start, bpb, rng, args.space, spaced_before) if args.space != "none" else set()
        spaced_before = {_slot(hats[i].start - start) for i in gone}
        drop |= {id(hats[i]) for i in gone}
        spaced += len(gone)
        has_open = any(n.pitch == OPEN and bar_of(n) == bar for n in track.notes)
        # 더 · 바꾸기: 4마디 중 3마디쯤 (이미 열린 햇이 있는 마디는 반쯤만 하나 더)
        if args.open_hats == "more" and rng.random() < (0.4 if has_open else 0.75):
            opens = [n for n in track.notes if n.pitch == OPEN and bar_of(n) == bar]
            spot = _add_open(hats, gone, opens, start, rng, opened_before)
            opened_before = None if spot is None else _slot(spot[0] - start)
            if spot is not None:
                at, velocity, empty = spot
                extra.append(Note(pitch=OPEN, start=at, duration=0.25, velocity=max(velocity, OPEN_MIN_VELOCITY)))
                filled += empty
        if args.open_hats == "swap" and rng.random() < (0.4 if has_open else 0.75):
            i = _open_bar(hats, gone, start, rng, opened_before)
            if i is not None:
                n = hats[i]
                opened[id(n)] = n.model_copy(update={"pitch": OPEN, "velocity": max(n.velocity, OPEN_MIN_VELOCITY)})
                opened_before = _slot(n.start - start)
                # 바로 뒤 16분 햇은 빼서 열린 햇이 울리게 (닫힌 햇이 열린 햇을 끊는다)
                drop |= {id(m) for m in hats if n.start < m.start < n.start + 0.3}
            else:
                opened_before = None
    closed = 0
    notes: list[Note] = []
    open_seen = 0
    for n in sorted([*track.notes, *extra], key=lambda n: (n.start, n.pitch)):
        if id(n) in drop:
            continue
        if id(n) in opened:
            notes.append(opened[id(n)])
            continue
        # 덜: 열린 햇을 하나 걸러 하나 닫는다 (4마디 끝 열린 햇은 남게 — 짝수 번째를 닫음)
        if args.open_hats == "fewer" and n.pitch == OPEN and in_range(bar_of(n)):
            open_seen += 1
            if open_seen % 2 == 1:
                notes.append(n.model_copy(update={"pitch": 42}))
                closed += 1
                continue
        notes.append(n)
    return notes, spaced, len(opened), filled, len(extra) - filled, closed


def vary_hats(project: Project, args: VaryHatsArgs) -> ToolResult:
    by_id = {t.id: t for t in project.tracks}
    if args.track_ids:
        unknown = [i for i in args.track_ids if i not in by_id]
        if unknown:
            valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
            raise ToolError(f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
        not_drum = [by_id[i].name for i in args.track_ids if not by_id[i].is_drum]
        if not_drum:
            raise ToolError(f"드럼 트랙이 아니에요: {', '.join(not_drum)}. 하이햇은 드럼 트랙에만 있어요.", code="not_drum")
        targets = [by_id[i] for i in args.track_ids]
    else:
        targets = [t for t in project.tracks if t.is_drum and any(n.pitch in CLOSED | {OPEN} for n in t.notes)]
    if not targets:
        raise ToolError("하이햇이 있는 드럼 트랙이 없어요. 먼저 드럼을 깔아야 해요 (generate_drums).", code="no_hats")

    bpb = project.beats_per_bar
    where = "" if args.bars is None else (f" {args.bars[0]}마디" if args.bars[0] == args.bars[1] else f" {args.bars[0]}~{args.bars[1]}마디")
    new_tracks: dict[str, list[Note]] = {}
    parts: list[str] = []
    total = 0
    for track in targets:
        notes, spaced, opened, filled, layered, closed = _vary(track, args, bpb)
        if not (spaced or opened or filled or layered or closed):
            continue
        new_tracks[track.id] = notes
        total += spaced + opened + filled + layered + closed
        what = []
        if spaced:
            what.append(f"닫힌 햇 {spaced}개를 군데군데 비웠어요 (마디마다 다른 자리, 마디 첫 박과 롤은 그대로).")
        if filled or layered:
            where_ = " · ".join(x for x in [f"빈 뒷박 {filled}곳" if filled else "", f"닫힌 햇에 겹쳐 {layered}곳" if layered else ""] if x)
            what.append(f"열린 햇 {filled + layered}개를 더했어요 ({where_}, 닫힌 햇은 그대로).")
        if opened:
            what.append(f"닫힌 햇 {opened}개를 열린 햇으로 바꿨어요 (닫힌 햇이 그만큼 줄고, 울리도록 바로 뒤 16분 햇은 뺌).")
        if closed:
            what.append(f"열린 햇 {closed}개를 닫힌 햇으로 바꿨어요.")
        parts.append(f"{track.name}{where}: {' '.join(what)}")
    if not total:
        return ToolResult(project=project, summary="바꿀 하이햇이 없어요 (고른 범위에 닫힌 햇이 없거나, 비울 만한 자리가 없어요).")
    return ToolResult(
        project=project.model_copy(
            update={"tracks": [t.model_copy(update={"notes": new_tracks[t.id]}) if t.id in new_tracks else t for t in project.tracks]}
        ),
        changed_notes=total,
        summary=" / ".join(parts) + f" 버전 {args.version}.",
    )
