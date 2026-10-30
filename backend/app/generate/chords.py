"""코드 반주 만들기 (generate_chords). 첫 무늬는 패드: 곡의 코드마다 화음을 길게 누른다.

코드는 v0.2 분석 엔진이 읽은 곡의 코드를 그대로 따라가고, 음 고르기는 v0.2 apply_chords의 보이싱(revoice)을 다시 쓴다.
- 음역: 베이스 위쪽과 멜로디 아래쪽 사이 빈 곳 — 다른 악기와 같은 높이에서 겹치지 않게
- 보이싱: 4음. 첫 코드는 음역 가운데, 다음 코드부터는 앞 코드에서 가장 덜 움직이게 (패드가 코드마다 뛰지 않게)
- 소리: 곡 편성에 맞춰 — 스트링 · 관악기가 있으면 스트링 앙상블, 신스 리드 · 신스 베이스 · 일렉트로닉 킷이 있으면
  폴리신스 패드, 그 밖(건반 · 로파이 · 피아노)은 따뜻한 패드. 이미 같은 소리가 있으면 다른 패드.
  템포로는 고르지 않는다 (150 BPM 피아노 왈츠에 신스 패드가 깔렸다)
- 세기: 원래 곡보다 조금 작게 (뒤에 깔리게)
- 다른 버전: version마다 첫 코드를 다른 모양(촘촘하게 · 넓게 · 높게 · 4도로 벌려)으로 짜고, 거기서부터 이어 간다
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from random import Random
from statistics import mean, median

from app.generate.check import playable
from app.harmony import ChordSpan, analyze
from app.harmony.analyze import melody_ids
from app.harmony.reharm import INTERVALS
from app.harmony.voicing import revoice
from app.models.project import Note, Project, Track
from app.tools.instrument import heard_program

VOICES = 4
LOW, HIGH = 45, 79  # 패드가 머무를 바깥 한계 (A2 ~ G5)
GAP = 2  # 반음. 베이스 · 멜로디와 이만큼은 떨어진다
NARROW = 10  # 반음. 빈 곳이 이보다 좁으면 멜로디 아래쪽에 붙여 놓는다
DRIFT = 5  # 반음. 보이싱 가운데가 음역 가운데에서 이만큼 넘게 끌려가면 다시 가운데에서 짠다
SOFTER = 0.75  # 원래 곡 세기에 곱한다
CLUSTER = 6  # 반음 붙은 두 음의 벌점 (움직임 반음 수로)
HEIGHT_SHIFT = {"low": -7, "mid": 0, "high": 7}
SHAPES = [(-7, -3, 2, 6), (-10, -3, 4, 9), (-4, 0, 5, 9), (-12, -5, 0, 7)]  # 버전마다 첫 코드를 짤 모양 (음역 가운데에서 반음)

WARM_PAD, POLYSYNTH_PAD, STRINGS = 89, 90, 48
OTHER_PADS = [91, 88, 95]  # 콰이어 · 뉴에이지 · 스윕 패드 (이미 같은 소리가 있을 때)
ELECTRONIC_KITS = {24, 25, 26}  # 일렉트로닉 · TR-808 · 하우스


@dataclass
class PadPlan:
    program: int
    low: int  # 실제로 쓴 가장 낮은 · 높은 음
    high: int
    chords: list[ChordSpan] = field(default_factory=list)  # 패드를 놓은 코드 (검사에도 쓴다)


def pad_program(project: Project) -> int:
    heard = [heard_program(t) for t in project.tracks if not t.is_drum]
    kits = {t.program for t in project.tracks if t.is_drum}
    if any(40 <= p <= 79 for p in heard):  # 스트링 · 앙상블 · 금관 · 목관 — 어쿠스틱 편성에 신스 패드는 튄다
        want = STRINGS
    elif any(80 <= p <= 87 or p in (38, 39) for p in heard) or kits & ELECTRONIC_KITS:
        want = POLYSYNTH_PAD
    else:
        want = WARM_PAD
    used = set(heard)
    return next((p for p in [want, WARM_PAD, POLYSYNTH_PAD, *OTHER_PADS] if p not in used), want)


def _percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def pad_window(project: Project, start: float, end: float) -> tuple[int, int]:
    """패드가 머무를 [가장 낮은, 가장 높은] 음. 베이스(따로 있을 때) 위쪽 · 멜로디 아래쪽 사이 빈 곳."""
    pitched = [t for t in project.tracks if not t.is_drum and t.notes]
    melody = melody_ids(project)
    harmonic = [t for t in pitched if t.id not in melody]

    def heard(t: Track) -> list[int]:
        return [n.pitch for n in t.notes if n.start < end and n.start + n.duration > start]

    low, high = LOW, HIGH
    if len(harmonic) > 1:  # 베이스 트랙이 따로 있다 (가장 낮은 화음 트랙)
        bass = min(harmonic, key=lambda t: sum(n.pitch for n in t.notes) / len(t.notes))
        if pitches := heard(bass):
            low = max(low, _percentile(pitches, 0.9) + GAP)
    tune = [p for t in pitched if t.id in melody for p in heard(t)]
    if tune:
        high = min(high, _percentile(tune, 0.1) - GAP)
    if high - low < NARROW:  # 좁으면 멜로디 바로 아래 한 옥타브 (멜로디를 가리지 않게, 베이스와는 조금 겹쳐도)
        high = max(LOW + 12, min(HIGH, high))
        low = high - 12
    return low, high


def _must(chord: ChordSpan) -> set[int]:
    """꼭 넣을 음: 코드 색을 정하는 3음 · 7음(6음) · 변한 5음. 7음이 없는 3화음이면 세 음 모두."""
    ivs = INTERVALS.get(chord.quality, (0, 4, 7))
    color = {i for i in ivs if i in (3, 4, 6, 8, 9, 10, 11)}
    picked = color if any(i in (9, 10, 11) for i in ivs) else set(ivs)
    return {(chord.root + i) % 12 for i in picked}


def lead(prev: list[int], chord: ChordSpan, low: int, high: int) -> list[int]:
    """prev(4음)에서 가장 덜 움직여 chord로 가는 4음. 목소리마다 코드 음 중 가까운 후보를 두고, 겹치지 않고 음역 안이며
    꼭 넣을 음을 다 넣는 조합 중 움직임 합이 가장 작은 것 (후보가 적어 다 따져 본다).
    v0.2 보이싱 규칙(3음부터 겹치기)을 그대로 쓰면 Am에서 C를 겹치느라 한 음이 음역 밖으로 뛰고, 안으로 들이면 같은 음이 둘이 됐다."""
    pcs = {(chord.root + i) % 12 for i in INTERVALS.get(chord.quality, (0, 4, 7))}
    must = _must(chord)
    options = []
    for p in prev:
        near = {p - (p - pc) % 12 for pc in pcs} | {p - (p - pc) % 12 + 12 for pc in pcs}
        options.append(sorted((q for q in near if low - GAP <= q <= high + GAP), key=lambda q: abs(q - p))[:4])
    best = None
    for combo in product(*options):
        if len(set(combo)) < len(combo) or not must <= {q % 12 for q in combo}:
            continue
        cost = sum(abs(a - b) for a, b in zip(combo, prev))
        voiced = sorted(combo)  # 이웃한 두 음이 반음이면 탁하다 (Dm9의 E F를 붙여 쌓던 것) — 반음 6개 움직임만큼 피한다
        cost += CLUSTER * sum(1 for x, y in zip(voiced, voiced[1:]) if y - x == 1)
        if best is None or cost < best[0]:
            best = (cost, combo)
    return sorted(best[1]) if best else sorted(revoice(prev, chord))


def shape(version: int) -> list[int]:
    """version번째 첫 코드 모양. 모양을 다 쓰면 조금씩 흔들어 새 모양을 만든다."""
    base = SHAPES[(version - 1) % len(SHAPES)]
    if version <= len(SHAPES):
        return list(base)
    rng = Random(version)
    return [x + rng.choice((-2, -1, 1, 2)) for x in base]


def voicings(chords: list[ChordSpan], low: int, high: int, center: int, version: int = 1) -> list[list[int]]:
    """코드마다 4음. 앞 코드에서 가장 덜 움직이게 잇고, 가운데에서 너무 멀어지면 다시 가운데에서. 음역 [low, high] 안."""
    seed = [center + x for x in shape(version)]
    out: list[list[int]] = []
    prev: list[int] = seed
    for c in chords:
        v = lead(prev, c, low, high)
        if abs(mean(v) - center) > DRIFT:
            v = lead(seed, c, low, high)
        out.append(v)
        prev = v
    return out


def pad_notes(
    project: Project, start: float = 0.0, end: float | None = None, height: str | None = None,
    program: int | None = None, version: int = 1,
) -> tuple[list[Note], PadPlan]:
    """[start, end) 박에 곡의 코드대로 패드 음. 코드가 없는 구간(N.C.)은 비운다. program이 없으면 곡 편성에 맞춰 고른다."""
    program = pad_program(project) if program is None else program
    a = analyze(project)
    end = a.chords[-1].end if end is None and a.chords else (end or 0.0)
    chords = [c for c in a.chords if c.root is not None and c.end > start + 1e-6 and c.start < end - 1e-6]
    if not chords:
        return [], PadPlan(program, 0, 0)
    low, high = pad_window(project, start, end)
    shift = HEIGHT_SHIFT.get(height or "mid", 0)
    low, high = max(LOW - 7, low + shift), min(HIGH + 7, high + shift)
    floor, ceil = playable(program)  # 고른 악기로 낼 수 있는 높이 안에서만 (보이싱이 GAP만큼 넘칠 수 있어 그만큼 안쪽)
    low, high = max(low, floor + GAP), min(high, ceil - GAP)
    if high - low < 12:
        low, high = max(floor + GAP, min(low, ceil - GAP - 12)), min(ceil - GAP, max(high, floor + GAP + 12))
    center = (low + high) // 2
    played = [n.velocity for t in project.tracks if not t.is_drum for n in t.notes]
    velocity = max(35, min(90, round(median(played) * SOFTER))) if played else 64
    notes = []
    for c, voicing in zip(chords, voicings(chords, low, high, center, version)):
        s, e = max(c.start, start), min(c.end, end)
        notes += [Note(pitch=p, start=round(s, 4), duration=round(e - s, 4), velocity=velocity) for p in voicing]
    pitches = [n.pitch for n in notes]
    return notes, PadPlan(program, min(pitches), max(pitches), chords)
