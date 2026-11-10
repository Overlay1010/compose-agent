"""실제 드러머 연주 찾기 (RAG) — 손으로 쓴 16칸 패턴 대신, 곡 · 말에 맞는 연주 루프를 찾아 곡 길이만큼 잇는다.

재료: grooves.json (Groove MIDI Dataset, Google LLC · Magenta, CC BY 4.0 — scripts/build_grooves.py로 루프를 잘라 고름).
- 찾기: 스타일이 맞는 루프 중 곡 템포에 가깝고(템포가 멀면 밀고 당김이 어색해진다) 밀도 · 스윙이 말과 맞는 것.
  점수가 비슷한 후보는 곡마다 순서를 바꾼다 (늘 같은 연주만 나오지 않게, 같은 곡이면 늘 같게). "다른 버전" = 다음 후보
- 깔기: 루프를 마디째 되풀이하고, 4마디마다 같은 연주의 필인 마디(같은 드러머가 그 연주에서 친 것), 필인 뒤 첫 박에 크래시.
  위치 · 세기는 연주 그대로 (격자에 맞추지 않는다 — 그게 사람의 밀고 당김이다)
- 4/4만 있다. 하우스 · 트랩은 데이터에 없어 손으로 쓴 패턴을 쓴다
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from random import Random

from app.models.project import Note

DATA = Path(__file__).with_name("grooves.json")
GROOVE_STYLES = ("rock", "boombap", "lofi", "pop", "funk", "soul", "jazz", "latin")
HIT = 0.2
LONG = {46: 1.0, 49: 1.0}  # 열린 햇 · 크래시는 길게 (다음 음이 오면 _untangle이 줄인다)
TIME_TARGET = {"low": 6.0, "mid": 9.0, "high": 15.0}  # 마디당 햇 · 라이드 수 (4분 · 8분 · 16분 쪽)
SWING_TARGET = {"jazz": 64.0, "lofi": 58.0}  # 말이 없을 때 이 스타일은 흔들리는 연주부터
TIE = 0.35  # 점수 차이가 이보다 작으면 같은 무리로 보고 곡마다 순서를 섞는다


@dataclass(frozen=True)
class Groove:
    id: str
    styles: tuple[str, ...]
    label: str  # Groove MIDI의 장르 이름 (funk/groove3 …)
    bpm: int
    drummer: str
    bars: int
    features: dict
    hits: tuple[tuple[float, int, int], ...]  # (루프 시작부터 박, GM 레인, 세기)
    fill: tuple[tuple[float, int, int], ...] | None


@lru_cache(maxsize=1)
def library() -> tuple[Groove, ...]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return tuple(
        Groove(g["id"], tuple(g["styles"]), g["label"], g["bpm"], g["drummer"], g["bars"], g["features"],
               tuple(map(tuple, g["hits"])), tuple(map(tuple, g["fill"])) if g["fill"] else None)
        for g in data["grooves"]
    )


def has_style(style: str) -> bool:
    return any(style in g.styles for g in library())


def _score(g: Groove, tempo: float, density: str | None, swing: float | None, style: str) -> float:
    """작을수록 맞음. 템포 차이(로그) → 밀도 → 스윙."""
    score = abs(math.log2(g.bpm / tempo)) * 6  # 템포가 12% 다르면 1점
    if density:
        score += abs(math.log2(max(g.features["time_per_bar"], 2) / TIME_TARGET[density])) * 2
    want = swing if swing is not None else SWING_TARGET.get(style)
    if want is not None:
        score += abs(g.features["swing"] - want) / (6 if swing is not None else 12)
    return score


def candidates(style: str, tempo: float, density: str | None = None, swing: float | None = None,
               seed: str = "") -> list[Groove]:
    """맞는 순서대로. 점수가 TIE 안쪽인 무리끼리는 seed(곡)로 섞는다."""
    pool = sorted((g for g in library() if style in g.styles), key=lambda g: (_score(g, tempo, density, swing, style), g.id))
    out: list[Groove] = []
    while pool:
        best = _score(pool[0], tempo, density, swing, style)
        tier = [g for g in pool if _score(g, tempo, density, swing, style) - best < TIE]
        Random(f"{seed}:{style}:{len(out)}").shuffle(tier)
        out += tier
        pool = [g for g in pool if g not in tier]
    return out


def _step(beat: float) -> int:
    return int(round(beat * 4))


def _fills(lane: int, vel: int, step: int) -> bool:
    """필인에서 치는 음인가: 탐 · 2 · 4박이 아닌 센 스네어."""
    return lane in (43, 45, 47, 48, 50) or (lane in (37, 38) and vel >= 45 and step not in (4, 12))


def groove_notes(groove: Groove, start: float, end: float, *, fills: bool, density: str, crash: int, toms: tuple[int, ...],
                 phrase: int = 4) -> tuple[list[Note], int]:
    """[start, end) 박에 루프를 마디째 잇는다 (4/4). (음, 넣은 필인 수)."""
    first_bar, last_bar = int(start // 4), math.ceil(end / 4 - 1e-9) - 1
    bars = last_bar - first_bar + 1
    fill_every = phrase if bars >= 2 * phrase else (bars if bars >= 2 else 0)
    by_bar: dict[int, list[tuple[float, int, int]]] = {}
    for beat, lane, vel in groove.hits:
        by_bar.setdefault(min(groove.bars - 1, max(0, int(round(beat * 4)) // 16)), []).append((beat, lane, vel))
    notes: list[Note] = []
    filled = 0
    after_fill = False
    for bar in range(first_bar, last_bar + 1):
        k = bar - first_bar
        src = k % groove.bars
        fill = bool(fills and fill_every and (k + 1) % fill_every == 0)
        hits = [(b - src * 4, lane, vel) for b, lane, vel in by_bar.get(src, [])]
        if fill:
            filled += 1
            if groove.fill:
                # 필인이 시작되는 박부터만 (늦어도 마디 후반부터) — 한 마디를 통째로 필인으로 채운 연주도 있어서,
                # 그대로 넣으면 4마디마다 한 마디가 통째로 필인이 됐다. 그 앞은 원래 루프
                start_step = max(8, min((_step(b) // 4 * 4 for b, lane, vel in groove.fill if _fills(lane, vel, _step(b))), default=12))
                hits = [h for h in hits if _step(h[0]) < start_step] + [h for h in groove.fill if _step(h[0]) >= start_step]
            else:  # 같은 연주에 필인이 없으면 마지막 박을 비우고 탐 넷
                hits = [h for h in hits if round(h[0] * 4) < 12] + [(3 + i * 0.25, tom, 96) for i, tom in enumerate(toms)]
        if density == "low":  # 고스트 노트와 16분 햇을 뺀다
            hits = [h for h in hits if h[2] >= 40 and not (h[1] in (42, 44) and round(h[0] * 4) % 2 == 1)]
        if after_fill:
            hits = [h for h in hits if not (h[1] == crash and round(h[0] * 4) == 0)] + [(0.0, crash, 110)]
        after_fill = fill
        for pos, lane, vel in hits:
            t = round(max(start, bar * 4 + pos), 4)  # 조금 일찍 친 곡의 첫 음은 시작에 맞춘다
            if not start - 1e-6 <= bar * 4 + max(pos, 0) < end - 1e-6:
                continue
            length = LONG.get(lane, HIT)
            notes.append(Note(pitch=lane, start=t, duration=round(max(0.05, min(length, end - t)), 4), velocity=vel))
    return notes, filled
