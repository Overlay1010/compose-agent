"""베이스라인 만들기 (generate_bassline). 코드는 반주와 같이 곡의 코드(분석) 또는 사용자가 말한 진행을 따른다 (chords.follow).

- 리듬: 드럼에 킥이 있으면 킥 자리에 친다 (16분음표 격자에 맞춰서, 다음 킥까지 누름). 킥이 없거나 다른 버전이면 정해 둔 리듬
- 음: 코드가 바뀌는 첫 음은 근음 (슬래시 코드면 그 베이스 음). 나머지는 스타일대로
  - root: 근음만 · root_fifth: 근음과 5음을 번갈아 · octave: 근음과 한 옥타브 위를 번갈아
  - walking: 4분음표로 근음 → 코드 음 → 코드 음 → 다음 근음으로 이어 주는 음 (재즈)
- 이어 주는 음: 코드의 마지막 음이 짧으면(1박 이하) 다음 근음의 반음 · 온음 위나 아래 중 조성 음계에 드는 음으로 (워킹은 늘)
- 음역: 근음은 E1 ~ D#2 (4현 베이스가 편한 자리), 5음 · 옥타브 · 코드 음은 그 위로. 워킹은 근음을 바로 앞 음에서 가장 가까운
  옥타브(E1 ~ B2)로 골라 선이 이어지게 한다 (늘 같은 높이면 G2까지 올라갔다가 다음 근음 F1로 한 옥타브 넘게 떨어졌다)
- 소리: 신스 리드 · 일렉트로닉 킷 · 신스 베이스가 있으면 신스 베이스, 스트링 · 관악기 편성이면 어쿠스틱(콘트라) 베이스, 그 밖은 핑거 베이스
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from app.generate.check import SCALES
from app.generate.chords import ELECTRONIC_KITS, follow
from app.harmony import ChordSpan, analyze
from app.harmony.analyze import KeyInfo, decide_key
from app.harmony.reharm import INTERVALS
from app.midi_io.convert import KICKS
from app.models.project import Note, Project
from app.tools.instrument import heard_program

ROOT_LOW = 28  # E1. 근음은 E1 ~ D#2
WALK_HIGH = 47  # B2. 워킹 베이스의 근음은 E1 ~ B2에서 앞 음과 가까운 옥타브
GRID = 0.25
LONGEST = 2.0  # 박. 킥을 따라 칠 때 한 음을 이보다 길게 누르지 않는다
DENSE = 8  # 한 마디에 킥이 이보다 많으면(드럼 앤 베이스 · 트랩 롤) 킥 대신 정해 둔 리듬
APPROACH = 1.0  # 박. 코드의 마지막 음이 이 이하이면 다음 근음으로 이어 주는 음

# 킥이 없을 때 · 다른 버전의 리듬: 한 마디(4박) 안의 (시작 박, 길이). 3/4는 마디 안에 드는 것만
BASS_RHYTHMS = [
    ((0, 1.5), (1.5, 1), (2.5, 1.5)),  # 쿵 - 따 쿵
    ((0, 1), (1, 1), (2, 1), (3, 1)),  # 4분음표
    ((0, 2), (2, 2)),  # 2분음표
    ((0, 0.75), (0.75, 0.75), (1.5, 1), (2.5, 0.5), (3, 1)),  # 당겨서
]
RHYTHM_NAMES = ["쿵 - 따 쿵 리듬", "4분음표 리듬", "2분음표 리듬", "당긴 리듬"]  # 결과 요약에 (LLM이 리듬을 짐작해 말하지 않게)
WALK = ((0, 1), (1, 1), (2, 1), (3, 1))

FINGER, ACOUSTIC_BASS, SYNTH_BASS = 33, 32, 38


@dataclass
class BassPlan:
    program: int
    low: int
    high: int
    chords: list[ChordSpan] = field(default_factory=list)
    key: KeyInfo | None = None
    feel: str = ""  # 쓴 리듬 ("킥에 맞춤" · "쿵 - 따 쿵 리듬" …)


def bass_program(project: Project) -> int:
    heard = [heard_program(t) for t in project.tracks if not t.is_drum]
    kits = {t.program for t in project.tracks if t.is_drum}
    if any(80 <= p <= 87 or p in (38, 39) for p in heard) or kits & ELECTRONIC_KITS:
        return SYNTH_BASS
    if any(40 <= p <= 79 for p in heard):
        return ACOUSTIC_BASS
    return FINGER


def kick_hits(project: Project, start: float, end: float) -> list[float]:
    """[start, end)의 킥 자리 (16분음표 격자에 맞춤, 같은 자리는 하나로). 킥이 없거나 너무 빽빽하면 []."""
    hits = sorted({round(n.start / GRID) * GRID for t in project.tracks if t.is_drum for n in t.notes
                   if n.pitch in KICKS and start - 1e-6 <= n.start < end - 1e-6})
    bars = max(1, math.ceil((end - start) / project.beats_per_bar - 1e-9))
    return [h for h in hits if h < end - 1e-6] if hits and len(hits) / bars <= DENSE else []


def _root_pitch(pc: int, near: int | None = None) -> int:
    """pc의 근음 높이: E1 ~ D#2. near를 주면 E1 ~ B2 중 near에서 가장 가까운 옥타브 (워킹)."""
    low = ROOT_LOW + (pc - ROOT_LOW) % 12
    if near is None:
        return low
    return min((q for q in (low, low + 12) if q <= WALK_HIGH), key=lambda q: abs(q - near))


def _approach(next_root: int, scale: set[int], above: bool = False, avoid: int | None = None) -> int:
    """다음 근음(음 높이)으로 이어 주는 음: 반음 아래 · 위, 온음 아래 · 위 중 음계에 드는 첫 음.
    above: 위에서 내려오며 다가갈 때 (위 음부터 본다). avoid: 바로 앞 음 (같은 음을 두 번 치지 않게)."""
    for d in ((1, -1, 2, -2) if above else (-1, 1, -2, 2)):
        if (next_root + d) % 12 in scale and next_root + d != avoid:
            return next_root + d
    return next_root - 1


def _bass_pc(chord: ChordSpan) -> int:
    """코드가 바뀔 때 칠 음: 슬래시 코드면 그 베이스, 아니면 근음."""
    return chord.bass if chord.bass is not None else chord.root


def _pitches(chord: ChordSpan, n: int, style: str) -> list[int]:
    """코드 하나 안의 n개 음 (워킹 말고, 이어 주는 음 자리는 나중에 바꾼다)."""
    ivs = INTERVALS.get(chord.quality, (0, 4, 7))
    root = _root_pitch(chord.root)
    first = _root_pitch(_bass_pc(chord)) if _bass_pc(chord) != chord.root else root
    fifth = root + next((i for i in ivs if i in (6, 7, 8)), 7)
    if style == "root_fifth":
        cycle = [root, fifth]
    elif style == "octave":
        cycle = [root, root + 12]
    else:
        cycle = [root]
    out = [cycle[k % len(cycle)] for k in range(n)]
    out[0] = first
    return out


def _walk(chord: ChordSpan, n: int, root: int, target: int | None, scale: set[int]) -> list[int]:
    """워킹 베이스 한 코드 (4분음표 n개): 근음 → 다음 근음(target) 쪽으로 한 방향으로 걷고 → 마지막은 target 바로 옆 음.
    가운데 음은 코드 음을 먼저, 없으면 음계 음(지나가는 음). 다음 근음이 가까우면(4도 안쪽) 다른 옥타브의 근음으로 걸어가고,
    그것도 음역 밖이거나 사이에 디딜 음이 없으면 한 번 돌아 온다 (낮은 자리면 위로).
    근음 · 3음 · 5음을 늘 올라가며 치면 다음 근음 앞에서 한 옥타브씩 떨어졌다."""
    pcs = {(chord.root + i) % 12 for i in INTERVALS.get(chord.quality, (0, 4, 7))}
    steps = [q for q in range(ROOT_LOW - 4, WALK_HIGH + 9) if q % 12 in pcs | scale]

    def nearest(aim: float, ok=lambda q: True) -> int | None:
        found = [q for q in steps if q != line[-1] and ok(q)]
        return min(found, key=lambda q: abs(q - aim) + (0 if q % 12 in pcs else 1)) if found else None

    line = [root]
    middle = n - 2 if target is not None else n - 1
    goal = target if target is not None else root
    if target is not None and abs(goal - root) < 5:
        goal = next((q for q in (goal + 12, goal - 12) if ROOT_LOW <= q <= WALK_HIGH and 5 <= abs(q - root) <= 12), goal)
    last = _approach(goal, scale, above=root > goal) if target is not None else None
    if last is not None and abs(last - root) > middle:  # 한 방향으로 걷기: 근음과 이어 주는 음 사이에서
        lo, hi = sorted((root, last))
        for k in range(1, middle + 1):
            q = nearest(root + (last - root) * k / (middle + 1), lambda q: lo < q < hi and (q - line[-1]) * (last - root) > 0)
            if q is None:
                break
            line.append(q)
    if len(line) < middle + 1:  # 돌아 오기: 근음 → 4도쯤 → 2도쯤
        line = [root]
        turn = 5 if root < 40 else -5
        for k in range(1, middle + 1):
            line.append(nearest(root + turn * (1 - (k - 1) / max(1, middle) * 0.6)))
    if last is not None and n > 1:
        line.append(_approach(goal, scale, above=line[-1] > goal, avoid=line[-1]))
    return line[:n]


def bass_notes(
    project: Project, start: float = 0.0, end: float | None = None, style: str = "root", program: int | None = None,
    version: int = 1, progression: list[str] | None = None, bars_per_chord: float = 1.0,
) -> tuple[list[Note], BassPlan]:
    """[start, end) 박에 코드대로 베이스. 코드가 없는 구간(N.C.)은 비운다. progression의 모르는 코드 이름은 ValueError."""
    program = bass_program(project) if program is None else program
    bpb = project.beats_per_bar
    chords, end = follow(project, start, end, progression, bars_per_chord)
    if not chords:
        return [], BassPlan(program, 0, 0)
    if progression:
        hist = [0.0] * 12
        for c in chords:
            for i in INTERVALS.get(c.quality, (0, 4, 7)):
                hist[(c.root + i) % 12] += c.end - c.start
        key = decide_key(hist, chords)
    else:
        key = analyze(project).key
    scale = {(key.tonic + i) % 12 for i in SCALES[key.mode]}

    # 리듬: 킥 → 정해 둔 리듬 순으로 버전마다 다음 (워킹은 늘 4분음표)
    kicks = kick_hits(project, start, end) if style != "walking" else []
    options: list[list[tuple[float, float]] | None] = ([None] if kicks else []) + [list(r) for r in BASS_RHYTHMS]
    pick = [list(WALK)] if style == "walking" else options
    rhythm = pick[(version - 1) % len(pick)]
    if rhythm is None:
        hits = [(h, min(LONGEST, nxt - h)) for h, nxt in zip(kicks, [*kicks[1:], end])]
    else:
        bar_rhythm = [(o, d) for o, d in rhythm if o < bpb - 1e-6]
        hits = [(b * bpb + o, d) for b in range(int(start // bpb), math.ceil(end / bpb)) for o, d in bar_rhythm]

    played = [n.velocity for t in project.tracks if not t.is_drum for n in t.notes]
    velocity = max(60, min(110, round(median(played)))) if played else 90
    notes: list[Note] = []
    prev: int | None = None  # 워킹: 바로 앞 음
    for k, c in enumerate(chords):
        s, e = max(c.start, start), min(c.end, end)
        mine = [(h, d) for h, d in hits if s - 1e-6 <= h < e - 1e-6]
        if not mine or mine[0][0] > s + 1e-6:  # 코드가 바뀌는 자리엔 늘 친다 (킥이 그 자리에 없어도)
            first_len = (mine[0][0] if mine else e) - s
            mine = [(s, min(first_len, LONGEST if rhythm is None else first_len))] + mine
        nxt = chords[k + 1] if k + 1 < len(chords) and abs(chords[k + 1].start - c.end) < 1e-6 else None
        if style == "walking":
            root = _root_pitch(_bass_pc(c), prev)
            target = _root_pitch(_bass_pc(nxt), root) if nxt is not None else None  # 다음 코드는 이어 주는 음에서 가까운 옥타브로 시작
            pitches = _walk(c, len(mine), root, target, scale)
        else:
            pitches = _pitches(c, len(mine), style)
            last_start, last_len = mine[-1]
            if nxt is not None and len(mine) > 1 and min(last_len, e - last_start) <= APPROACH:
                pitches[-1] = _approach(_root_pitch(_bass_pc(nxt)), scale)
        prev = pitches[-1]
        for (h, d), p in zip(mine, pitches):
            dur = min(d, e - h)
            if dur > 1e-6:
                notes.append(Note(pitch=p, start=round(h, 4), duration=round(dur, 4), velocity=velocity))
    pitches_all = [n.pitch for n in notes]
    if style == "walking":
        feel = "4분음표"
    elif rhythm is None:
        feel = "드럼 킥에 맞춤"
    else:
        feel = RHYTHM_NAMES[BASS_RHYTHMS.index(tuple(rhythm))] + (" (킥 없음)" if not kicks else "")
    return notes, BassPlan(program, min(pitches_all), max(pitches_all), chords, key, feel)
