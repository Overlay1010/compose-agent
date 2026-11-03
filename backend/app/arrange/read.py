"""곡 읽기: read_song(project) → SongMap.

트랙마다 역할 · 음역 · 소리 성격(길게 끄는지 · 밝기) · 리듬 밀도를 재고, 곡 전체의 음역 지도(빈 높이) · 빠진 역할을 정리한다.
음을 고치지 않는 순수 함수. 값은 사람이 읽는 말로도 풀어 둔다 (추천 이유 · LLM 설명에 그대로 쓰게).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

from app.arrange.sections import Structure, describe, read_structure
from app.generate.check import playable
from app.models.project import Project, Track
from app.tools.instrument import heard_program

Role = Literal["bass", "pad", "keys", "pluck", "lead"]
Character = Literal["long", "short", "mixed"]

ROLE_KO = {"bass": "베이스", "pad": "패드", "keys": "건반", "pluck": "플럭", "lead": "리드"}
CHARACTER_KO = {"long": "길게 끄는 소리", "short": "짧게 끊기는 소리", "mixed": "길고 짧은 소리가 섞임"}

# 곡에서 소리가 쓰이는 높이 (E1 ~ C7). 이 밖은 빈 높이로 치지 않는다
FLOOR, CEILING = 28, 96
GAP_MIN = 7  # 반음. 이보다 좁은 빈 곳은 빈 높이로 보지 않는다
MUD = 48  # C3. 이보다 낮은 빈 곳은 베이스 말고는 채울 자리가 아니다 (베이스 바로 위를 패드로 채우면 뭉개진다)
LONG_NOTE = 1.0  # 박. 이보다 긴 음이 많으면 길게 끄는 소리
# GM 악기 계열(번호 // 8)의 밝기 0~1 — 내 샘플이 아니면 이걸로 (피아노 · 크로마틱 타악기(벨) · 오르간 · 기타 · 베이스 · 현악 …)
FAMILY_BRIGHTNESS = [0.5, 0.8, 0.5, 0.5, 0.15, 0.45, 0.4, 0.6, 0.55, 0.6, 0.75, 0.35, 0.6, 0.6, 0.6, 0.5]
# 음이 없는 트랙의 소리 성격 (계열로): 오르간 · 현악 · 앙상블 · 금관 · 목관 · 피리 · 신스 패드는 길게
LONG_FAMILIES = {2, 5, 6, 7, 8, 9, 11}


@dataclass
class TrackProfile:
    id: str
    name: str
    drum: bool
    role: Role | None  # 드럼 · 오디오 루프면 None
    program: int  # 들리는 악기 (내 샘플이면 트랙 악기 번호)
    family: int  # GM 계열 (program // 8)
    low: int | None  # 음역: 아래 · 위 10% 를 뺀 높이 (튀는 음 하나에 끌려가지 않게)
    high: int | None
    center: int | None
    character: Character
    brightness: float  # 0 어두움 ~ 1 밝음
    density: float  # 마디당 새로 치는 횟수
    sample: str | None = None  # 내 샘플 이름

    @property
    def busy(self) -> bool:
        return self.density >= 8  # 8분음표로 계속 치는 정도


@dataclass
class SongMap:
    tracks: list[TrackProfile]
    bars: int
    flavor: Literal["acoustic", "electronic", "neutral"]
    gaps: list[tuple[int, int]] = field(default_factory=list)  # 아무 멜로디 트랙도 안 쓰는 높이 [아래, 위] (베이스 아래는 뺌)
    missing: list[Role] = field(default_factory=list)  # 곡에 없는 역할 (베이스 · 화음 · 위 선율 순으로 중요)
    structure: Structure | None = None  # 구간 · 프레이즈 · 멜로디가 쉬는 곳 (app/arrange/sections.py)
    beats_per_bar: float = 4.0

    @property
    def melodic(self) -> list[TrackProfile]:
        return [t for t in self.tracks if not t.drum and t.role is not None]

    def summary(self) -> str:
        """사람이 읽는 한 줄씩 (LLM에 넘기는 곡 읽기 결과)"""
        lines = []
        for t in self.melodic:
            where = f"{note_name(t.low)}~{note_name(t.high)}" if t.low is not None else "음 없음"
            sound = f"내 샘플 {t.sample}" if t.sample else f"악기 {t.program}"
            lines.append(f"- {t.name}: {ROLE_KO[t.role]} · {where} · {CHARACTER_KO[t.character]} · 마디당 {t.density:g}번 · {sound}")
        drums = [t.name for t in self.tracks if t.drum]
        if drums:
            lines.append(f"- 드럼: {', '.join(drums)}")
        if self.gaps:
            lines.append("- 빈 높이: " + ", ".join(f"{note_name(a)}~{note_name(b)}{' (맨 위)' if b == CEILING else ''}" for a, b in self.gaps))
        if self.missing:
            lines.append("- 없는 역할: " + ", ".join(ROLE_KO[r] for r in self.missing))
        if self.structure:
            lines += describe(self.structure, self.beats_per_bar)
        return "\n".join(lines)


def note_name(pitch: int | None) -> str:
    if pitch is None:
        return "-"
    return f"{['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][pitch % 12]}{pitch // 12 - 1}"


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def _character(track: Track, family: int) -> Character:
    if not track.notes:
        return "long" if family in LONG_FAMILIES else "short"
    long_share = sum(n.duration >= LONG_NOTE for n in track.notes) / len(track.notes)
    return "long" if long_share >= 0.6 else "short" if long_share <= 0.2 else "mixed"


def profile(track: Track, bars: int, bpb: float, samples: dict[str, object] | None = None) -> TrackProfile:
    from app.tools.samples import role_of  # 늦게 불러온다 (도구 목록이 이 모듈을 불러서 돌고 도는 import가 된다)

    program = heard_program(track)
    family = program // 8
    pitches = [n.pitch for n in track.notes]
    low = _percentile(pitches, 0.1) if pitches else None
    high = _percentile(pitches, 0.9) if pitches else None
    onsets = len({round(n.start, 3) for n in track.notes})
    info = samples.get(track.sample.id) if samples and track.sample else None
    brightness = getattr(info, "brightness", None)
    return TrackProfile(
        id=track.id, name=track.name, drum=track.is_drum, role=role_of(track), program=program, family=family,
        low=low, high=high, center=int(median(pitches)) if pitches else None,
        character=_character(track, family),
        brightness=round(brightness if brightness is not None else FAMILY_BRIGHTNESS[family], 2),
        density=round(onsets / max(1, bars), 1),
        sample=track.sample.name if track.sample else None,
    )


def _flavor(project: Project) -> Literal["acoustic", "electronic", "neutral"]:
    """생성기가 소리를 고르던 기준과 같다 (generate/chords.pad_program): 신스 리드 · 신스 베이스 · 일렉트로닉 킷이면 전자,
    현악 · 금관 · 목관이면 어쿠스틱"""
    heard = [heard_program(t) for t in project.tracks if not t.is_drum]
    kits = {t.program for t in project.tracks if t.is_drum}
    if any(80 <= p <= 87 or p in (38, 39) for p in heard) or kits & {24, 25, 26}:
        return "electronic"
    if any(40 <= p <= 79 for p in heard):
        return "acoustic"
    return "neutral"


def _gaps(tracks: list[TrackProfile]) -> list[tuple[int, int]]:
    """빈 높이. 맨 아래 트랙보다 낮은 곳은 빼고(베이스 밑은 채울 자리가 아니다), 맨 위는 남긴다 (벨 · 리드를 얹을 자리)"""
    used = [False] * 128
    for t in tracks:
        if t.low is not None and t.high is not None:
            for p in range(t.low, t.high + 1):
                used[p] = True
    gaps, start = [], None
    for p in range(FLOOR, CEILING + 1):
        if not used[p] and start is None:
            start = p
        if (used[p] or p == CEILING) and start is not None:
            end = p - 1 if used[p] else p
            if end - start + 1 >= GAP_MIN:
                gaps.append((start, end))
            start = None
    lowest = min((t.low for t in tracks if t.low is not None), default=None)
    out = []
    for a, b in gaps:
        if lowest is not None and a <= lowest:
            continue
        a = max(a, MUD)
        if b - a + 1 >= GAP_MIN:
            out.append((a, b))
    return out


def read_song(project: Project, samples: list[object] | tuple[object, ...] | None = None) -> SongMap:
    """samples: 브라우저가 보낸 내 샘플 이름표 (밝기를 쓰려고). 없으면 악기 계열로 짐작한다."""
    bpb = project.beats_per_bar
    last = max((n.start + n.duration for t in project.tracks for n in t.notes), default=0.0)
    bars = max(1, math.ceil(last / bpb - 1e-9))
    by_id = {getattr(s, "id"): s for s in samples or []}
    tracks = [profile(t, bars, bpb, by_id) for t in project.tracks if t.audio is None]
    melodic = [t for t in tracks if not t.drum and t.role is not None]
    roles = {t.role for t in melodic}
    missing: list[Role] = []
    if "bass" not in roles:
        missing.append("bass")
    if not roles & {"pad", "keys", "pluck"}:
        missing.append("pad")
    # 위 선율: 리드 역할이 없고, 가장 높은 트랙도 C5 아래면
    if "lead" not in roles and max((t.high or 0 for t in melodic), default=0) < 72:
        missing.append("lead")
    # 멜로디가 쉬는 곳은 리드(여럿이면 가장 높은 것), 리드가 없으면 가장 높은 멜로디 트랙으로 본다
    leads = [t for t in melodic if t.role == "lead" and t.center is not None] or [t for t in melodic if t.center is not None and t.role != "bass"]
    lead = max(leads, key=lambda t: t.center or 0).id if leads else None
    return SongMap(tracks=tracks, bars=bars, flavor=_flavor(project), gaps=_gaps(melodic), missing=missing,
                   structure=read_structure(project, bars, lead), beats_per_bar=bpb)


def fits(program: int, low: int, high: int) -> bool:
    """이 악기가 [low, high] 높이를 낼 수 있나 (check.playable 음역)"""
    a, b = playable(program)
    return a <= low and high <= b
