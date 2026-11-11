"""곡 구간 · 프레이즈 읽기: read_structure(project, bars, lead_id) → Structure.

마디마다 "어떤 트랙이 치는지 · 얼마나 촘촘한지"로 에너지를 재고, 프레이즈(4 · 8마디) 단위로 묶어 편성이나 에너지가 바뀌는 곳에서
구간을 나눈다. 이름은 에너지로 붙인다: 가장 꽉 찬 구간 = 후렴, 앞의 조용한 구간 = 인트로, 끝의 조용한 구간 = 아웃트로, 나머지 = 벌스.
바뀌는 곳이 없으면 한 구간짜리 루프. 멜로디(리드)가 2박 넘게 쉬는 곳도 찾는다 — 필인 · 오픈햇 · 대답하는 선율을 둘 자리.
멜로디 생성기 · 드럼 맞추기가 같이 쓴다 (docs/roadmap.md v0.3 "곡 읽기 · 트랙끼리 맞추기").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.project import Project

SECTION_KO = {"intro": "인트로", "verse": "벌스", "chorus": "후렴", "outro": "아웃트로", "loop": "루프"}
REST_MIN = 2.0  # 박. 이보다 길게 쉬어야 "멜로디가 쉬는 곳"
CHANGE = 0.25  # 마디 에너지가 이만큼 뛰면 바뀌는 곳
SPLIT = 0.15  # 프레이즈 평균 에너지가 이만큼 다르면 다른 구간
CLEAR = 0.1  # 후렴 · 인트로 · 아웃트로라고 부르려면 다른 구간과 이만큼은 달라야


@dataclass
class Section:
    start: int  # 마디 (1부터, 끝 포함)
    end: int
    label: str  # intro · verse · chorus · outro · loop
    energy: float  # 0 ~ 1 (곡에서 가장 꽉 찬 마디가 1에 가까움)
    tracks: list[str] = field(default_factory=list)  # 이 구간에서 치는 트랙 이름
    entered: list[str] = field(default_factory=list)  # 앞 구간에 없다가 들어온 트랙
    left: list[str] = field(default_factory=list)  # 앞 구간에 있다가 빠진 트랙

    @property
    def name(self) -> str:
        return SECTION_KO[self.label]


@dataclass
class Structure:
    phrase: int  # 프레이즈 길이 (마디)
    sections: list[Section]
    phrase_ends: list[int]  # 프레이즈가 끝나는 마디
    rests: list[tuple[float, float]]  # 멜로디가 쉬는 박 [시작, 끝)
    rest_track: str | None  # 쉬는 곳을 본 트랙 (리드, 없으면 가장 높은 트랙)
    energy: list[float]  # 마디마다

    def section_at(self, bar: int) -> Section | None:
        return next((s for s in self.sections if s.start <= bar <= s.end), None)


def _bar_activity(project: Project, bars: int) -> tuple[list[set[str]], list[int]]:
    """마디마다 치는(울리는) 트랙 id와 새로 치는 횟수"""
    bpb = project.beats_per_bar
    active: list[set[str]] = [set() for _ in range(bars)]
    onsets = [0] * bars
    for t in project.tracks:
        if t.audio is not None:
            continue
        for n in t.notes:
            first = int(n.start // bpb)
            last = int(max(n.start, n.start + n.duration - 1e-6) // bpb)
            for b in range(max(0, first), min(bars - 1, last) + 1):
                active[b].add(t.id)
            if 0 <= first < bars:
                onsets[first] += 1
    return active, onsets


def _phrase(active: list[set[str]], energy: list[float], bars: int) -> int:
    if bars < 4:
        return bars
    changes = [b for b in range(1, bars) if active[b] != active[b - 1] or abs(energy[b] - energy[b - 1]) > CHANGE]
    if bars >= 16 and changes and all(b % 8 == 0 for b in changes):
        return 8
    return 4


def _label(sections: list[Section]) -> None:
    if len(sections) == 1:
        sections[0].label = "loop"
        return
    top = max(s.energy for s in sections)
    low = min(s.energy for s in sections)
    for s in sections:
        s.label = "chorus" if top - low > CLEAR and s.energy >= top - 0.05 else "verse"
    first, last = sections[0], sections[-1]
    if first.label != "chorus" and first.energy < sections[1].energy - CLEAR:
        first.label = "intro"
    if len(sections) > 2 and last.label != "chorus" and last.energy < sections[-2].energy - CLEAR:
        last.label = "outro"


def _rests(project: Project, track_id: str | None, end_beat: float) -> list[tuple[float, float]]:
    track = next((t for t in project.tracks if t.id == track_id), None)
    if track is None or not track.notes:
        return []
    out: list[tuple[float, float]] = []
    edge = 0.0
    for n in sorted(track.notes, key=lambda n: n.start):
        if n.start - edge >= REST_MIN:
            out.append((round(edge, 3), round(n.start, 3)))
        edge = max(edge, n.start + n.duration)
    if end_beat - edge >= REST_MIN:
        out.append((round(edge, 3), round(end_beat, 3)))
    return out


def _energy(project: Project, active: list[set[str]], onsets: list[int]) -> list[float]:
    """마디 에너지 0~1: 치는 트랙 비율 0.6 + 새로 치는 횟수(곡에서 가장 많은 마디 대비) 0.4."""
    playing = [t for t in project.tracks if t.audio is None and t.notes]
    top = max(onsets, default=0) or 1
    return [round(0.6 * len(active[b]) / max(1, len(playing)) + 0.4 * onsets[b] / top, 3) for b in range(len(active))]


def bar_energy(project: Project, bars: int) -> list[float]:
    """마디마다 에너지 (구간 나누기와 같은 잣대 — 편곡 점검의 "더 꽉 차게"도 이걸로 잰다)."""
    active, onsets = _bar_activity(project, bars)
    return _energy(project, active, onsets)


def read_structure(project: Project, bars: int, lead_id: str | None) -> Structure:
    bpb = project.beats_per_bar
    names = {t.id: t.name for t in project.tracks}
    active, onsets = _bar_activity(project, bars)
    energy = _energy(project, active, onsets)
    phrase = _phrase(active, energy, bars)

    # 프레이즈마다: 절반 넘는 마디에서 치는 트랙 · 평균 에너지. 앞 프레이즈와 다르면 새 구간
    sections: list[Section] = []
    for start in range(0, bars, phrase):
        span = range(start, min(bars, start + phrase))
        counts: dict[str, int] = {}
        for b in span:
            for tid in active[b]:
                counts[tid] = counts.get(tid, 0) + 1
        members = sorted((tid for tid, k in counts.items() if k * 2 > len(span)), key=list(names).index)
        level = sum(energy[b] for b in span) / len(span)
        prev = sections[-1] if sections else None
        if prev and not any(onsets[b] for b in span):  # 새로 치는 음 없이 앞 음의 울림만 남은 마디는 앞 구간에 붙인다
            prev.end = span[-1] + 1
            continue
        if prev and [names[i] for i in members] == prev.tracks and abs(level - prev.energy) <= SPLIT:
            size_prev = prev.end - prev.start + 1
            prev.energy = round((prev.energy * size_prev + level * len(span)) / (size_prev + len(span)), 3)
            prev.end = span[-1] + 1
            continue
        section = Section(start=start + 1, end=span[-1] + 1, label="verse", energy=round(level, 3), tracks=[names[i] for i in members])
        if prev:
            section.entered = [n for n in section.tracks if n not in prev.tracks]
            section.left = [n for n in prev.tracks if n not in section.tracks]
        sections.append(section)
    if sections:
        _label(sections)
    ends = list(range(phrase, bars + 1, phrase)) if phrase else []
    if bars and (not ends or ends[-1] != bars):
        ends.append(bars)
    return Structure(phrase=phrase, sections=sections, phrase_ends=ends, rests=_rests(project, lead_id, bars * bpb),
                     rest_track=names.get(lead_id) if lead_id else None, energy=energy)


def where(beat: float, bpb: float) -> str:
    """박 → "9마디 1박" (사람이 읽는 자리)"""
    bar = int(beat // bpb) + 1
    inside = beat - (bar - 1) * bpb
    return f"{bar}마디" if inside < 1e-6 else f"{bar}마디 {inside + 1:g}박"


def describe(structure: Structure, bpb: float) -> list[str]:
    """곡 읽기 요약에 붙일 줄들"""
    lines = []
    if structure.sections:
        parts = []
        top = max(s.energy for s in structure.sections) or 1
        for s in structure.sections:
            # 세기는 곡 안의 다른 구간과 견줘서 (모든 구간이 "꽉 참"으로 나와 쓸모가 없었다). 루프 하나면 안 붙인다
            ratio = s.energy / top
            level = "" if s.label == "loop" else "가장 꽉 참" if ratio >= 0.97 else "조용함" if ratio <= 0.7 else "보통"
            change = []
            if s.entered:
                change.append(f"{', '.join(s.entered)} 들어옴")
            if s.left:
                change.append(f"{', '.join(s.left)} 빠짐")
            span = f"{s.start}~{s.end}마디" if s.start != s.end else f"{s.start}마디"
            detail = " · ".join(x for x in [level, *change] if x)
            parts.append(f"{span} {s.name}{f'({detail})' if detail else ''}")
        lines.append("- 구간: " + " / ".join(parts))
    if structure.phrase:
        lines.append(f"- 프레이즈: {structure.phrase}마디 (끝: {' · '.join(map(str, structure.phrase_ends))}마디)")
    if structure.rest_track and structure.rests:
        spots = ", ".join(f"{where(a, bpb)}~{where(b, bpb) if b % bpb else f'{int(b // bpb)}마디 끝'}" for a, b in structure.rests[:6])
        lines.append(f"- {structure.rest_track}가 쉬는 곳: {spots}")
    return lines
