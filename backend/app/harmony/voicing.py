"""제안한 코드로 음 바꾸기 (apply_chords): 리듬 · 세기는 그대로 두고 음높이만 새 코드에 맞춘다.

- 화음 트랙(건반 · 패드): 같이 친 음 묶음마다 가장 가까운 새 코드 음으로 옮긴다 (덜 움직이게).
  옮기고 나서 3음 · 7음이 빠졌으면 근음 · 5음이나 겹친 음 하나를 그쪽으로 보낸다 — 코드 색을 정하는 음이라서.
- 베이스: 원래 근음에서 새 근음까지 가까운 쪽으로 통째로 옮긴다 (G → Db이면 6반음). 지나가는 음 모양은 그대로.
  베이스 트랙 없이 건반 하나만 있으면 묶음의 맨 아래 음을 새 근음으로.
- 새 코드가 마디 중간에 시작하면(뒤 반 마디에 끼운 딸림7) 그 자리에 걸친 음을 나눈다: 앞은 원래 음, 뒤는 새 코드 음.
- 멜로디 · 드럼은 그대로 (멜로디와 부딪히는 대리코드는 제안할 때 이미 뺐다).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from app.harmony.analyze import CLOSE_BASS, ChordSpan, melody_ids
from app.harmony.reharm import INTERVALS
from app.models.project import Note, Project

EPS = 1e-6
MIN_PIECE = 0.05  # 박. 나누고 남은 조각이 이보다 짧으면 버린다 (사람이 친 흔들림으로 코드 바뀜 직전에 살짝 걸친 음)


@dataclass
class Segment:
    """코드가 바뀌는 구간: [start, end)에서 old → new."""

    start: float
    end: float
    new: ChordSpan
    old: ChordSpan


def segments(base: list[ChordSpan], new: list[ChordSpan]) -> list[Segment]:
    """새 코드 진행에서 원래와 이름이 다른 구간 (원래도 같은 코드가 울리던 곳은 뺀다)."""
    out = []
    for c in new:
        if c.root is None:
            continue
        for b in base:
            s, e = max(c.start, b.start), min(c.end, b.end)
            if e - s > EPS and b.root is not None and b.name != c.name:
                out.append(Segment(s, e, c, b))
    return out


def _tones(c: ChordSpan) -> list[int]:
    return [(c.root + i) % 12 for i in INTERVALS.get(c.quality, (0, 4, 7))]


def _nearest(pitch: int, pcs: set[int], used: set[int]) -> int:
    """pitch에서 가장 가까운, pcs에 드는 음 (같으면 아래로). used는 피한다."""
    for d in range(12):
        for q in (pitch - d, pitch + d):
            if 0 <= q <= 127 and q % 12 in pcs and q not in used:
                return q
    return pitch


# 음이 모자랄 때 먼저 넣을 음 (근음에서 반음 수): 코드 색을 정하는 3음 · 변한 5음 · 7음(6음), 텐션, 그다음 5음 · 근음.
# 베이스가 근음을 치므로 건반은 근음을 맨 나중에 — 재즈 건반의 근음 없는 보이싱 (Cmaj9 = E B D + 베이스 C)
PRIORITY = (3, 4, 6, 8, 10, 11, 2, 9, 5, 7, 0)
SEARCH = 6  # 음 개수가 이보다 많으면 모든 짝을 다 보지 않고 가까운 음부터 (6! = 720가지)


def _octave_near(pitch: int, pc: int) -> int:
    """pitch에서 가장 가까운 pc 음 (같으면 아래로)."""
    down = pitch - (pitch - pc) % 12
    up = down + 12
    q = down if pitch - down <= up - pitch else up
    return min(127, max(0, q))


def revoice(pitches: list[int], chord: ChordSpan, root_below: bool = False, floor: int | None = None) -> list[int]:
    """같이 친 음 묶음을 새 코드 음으로 (순서는 pitches 그대로).

    음 개수만큼 중요한 코드 음을 고르고(PRIORITY), 덜 움직이게 짝을 짓는다. 한 음뿐이면(펼침화음) 가장 가까운 코드 음.
    root_below: 베이스 트랙이 없을 때 — 맨 아래 음을 새 근음으로.
    floor: 이 음보다 위로만 (같은 트랙의 베이스 음 아래로 내려가면 코드 자리가 바뀐다 — Dm9가 Fmaj7/C로)
    """
    if floor is not None:
        pitches_in = pitches
        out = revoice(pitches_in, chord, root_below)
        return [q if q > floor else q + 12 * ((floor - q) // 12 + 1) for q in out]
    ivs = INTERVALS.get(chord.quality, (0, 4, 7))
    if len(pitches) == 1:
        return [_octave_near(pitches[0], chord.root) if root_below else _nearest(pitches[0], set(_tones(chord)), set())]
    order = sorted(range(len(pitches)), key=lambda i: pitches[i])
    out = [0] * len(pitches)
    if root_below:
        out[order[0]] = _octave_near(pitches[order[0]], chord.root)
        order = order[1:]
    priority = PRIORITY if not chord.quality.endswith("13") else (3, 4, 10, 11, 9, 2, 5, 7, 0)  # 13 코드는 13음을 9음보다 먼저
    ranked = [(chord.root + i) % 12 for i in priority if i in ivs]
    if root_below:
        ranked = [pc for pc in ranked if pc != chord.root] or [chord.root]
    want = [ranked[k % len(ranked)] for k in range(len(order))]  # 모자라면 앞에서부터 겹친다
    rest = [pitches[i] for i in order]
    if len(rest) <= SEARCH:
        best = min((
            (sum(abs(_octave_near(p, pc) - p) for p, pc in zip(rest, perm)), perm)
            for perm in set(permutations(want))
            if len({_octave_near(p, pc) for p, pc in zip(rest, perm)}) == len(rest)  # 같은 음 두 번은 안 됨
        ), default=None)
        chosen = best[1] if best else want
    else:
        chosen = want
    used: set[int] = {out[i] for i in range(len(out)) if out[i]}
    for i, pc in zip(order, chosen):
        q = _octave_near(pitches[i], pc)
        if q in used:
            q = _nearest(pitches[i], {pc}, used)
        out[i] = q
        used.add(q)
    return out


def _shift(old_root: int, new_root: int) -> int:
    """근음 사이 가까운 쪽 반음 수 (−6 ~ +5)."""
    return (new_root - old_root + 6) % 12 - 6


# 코드 음의 자리: 3음 · 5음 · 7음. 베이스가 원래 코드의 5음을 쳤으면 새 코드의 5음으로 (Dm9 → Dm7b5면 A → Ab)
DEGREES = ({3, 4}, {6, 7, 8}, {9, 10, 11})


def bass_note(pitch: int, old: ChordSpan, new: ChordSpan) -> int:
    """베이스 음 하나: 근음 차이만큼 옮기고, 원래 코드 음(3 · 5 · 7음)이었으면 새 코드의 같은 자리 음으로. 지나가는 음은 옮기기만."""
    q = pitch + _shift(old.root, new.root)
    was = (pitch - old.root) % 12
    if was in INTERVALS.get(old.quality, (0, 4, 7)):
        ivs = INTERVALS.get(new.quality, (0, 4, 7))
        for degree in DEGREES:
            same = [i for i in ivs if i in degree]
            if was in degree and same and was not in same:
                q += min(same, key=lambda i: abs(i - was)) - was
    return min(127, max(0, q))


def _pieces(n: Note, segs: list[Segment]) -> list[tuple[float, float, Segment | None]]:
    """음을 코드 바뀜 자리에서 나눈 조각 [(시작, 끝, 그 조각이 든 바뀐 구간 또는 None)]."""
    end = n.start + n.duration
    cuts = sorted({n.start, end, *(t for s in segs for t in (s.start, s.end) if n.start + EPS < t < end - EPS)})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        seg = next((s for s in segs if s.start - EPS <= a < s.end - EPS), None)
        out.append((a, b, seg))
    return out


STRUM = 0.1  # 박. 이만큼 안에 시작한 음은 같이 친 한 화음 (사람이 친 흔들림 · 스트럼)


def _strokes(idx: list[int], notes: list[Note]) -> list[list[int]]:
    """한 구간 안의 조각들을 같이 친 화음 묶음으로."""
    out: list[list[int]] = []
    for i in sorted(idx, key=lambda i: notes[i].start):
        if out and notes[i].start - notes[out[-1][0]].start <= STRUM:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def self_bass(notes: list[Note], i: int, old: ChordSpan, first: bool) -> bool:
    """베이스 트랙이 없을 때 notes[i]가 베이스 음인가: 그 순간 맨 아래이고, 위 음과 5도 넘게 떨어졌거나, 구간 첫 묶음에서
    원래 코드의 근음 (F A C처럼 붙여 친 기본 자리 — Dm9로 바꾸면 맨 아래도 D로), 또는 구간 첫 박에 혼자 친 음 (왈츠의 "쿵").
    근음 규칙을 첫 묶음에만 쓰는 이유: 왈츠의 "짝" 화음(C E)도 맨 아래가 근음이지만 베이스가 아니다."""
    n = notes[i]
    sounding = [m.pitch for m in notes if m is not n and m.start <= n.start + 1e-6 < m.start + m.duration]
    if any(q < n.pitch for q in sounding):
        return False
    above = [q for q in sounding if q > n.pitch]
    if not above:
        return first
    return min(above) - n.pitch >= CLOSE_BASS or (first and n.pitch % 12 == old.root)


def apply_progression(project: Project, base: list[ChordSpan], new: list[ChordSpan]) -> tuple[Project, dict[str, int]]:
    """(새 프로젝트, 트랙 이름별 바뀐 음 수). 원래 project는 고치지 않는다."""
    segs = segments(base, new)
    melody = melody_ids(project)
    harmonic = [t for t in project.tracks if not t.is_drum and t.notes and t.id not in melody]
    bass = min(harmonic, key=lambda t: sum(n.pitch for n in t.notes) / len(t.notes)).id if len(harmonic) > 1 else None
    out = project.model_copy(deep=True)
    counts: dict[str, int] = {}
    harmonic_ids = {t.id for t in harmonic}
    for track in out.tracks:
        if track.id not in harmonic_ids:
            continue
        notes: list[Note] = []
        by_seg: dict[int, list[int]] = {}  # 바뀐 구간마다 그 안에 든 조각
        for n in track.notes:
            parts = _pieces(n, segs)
            if all(seg is None for _, _, seg in parts):
                notes.append(n)
                continue
            for a, b, seg in parts:
                if b - a < MIN_PIECE:
                    continue
                notes.append(n.model_copy(update={"start": round(a, 4), "duration": round(b - a, 4)}))
                if seg is not None:
                    by_seg.setdefault(segs.index(seg), []).append(len(notes) - 1)
        for k, idx in by_seg.items():
            seg = segs[k]
            if track.id == bass:
                # 근음이 바뀌면 그 구간 첫 베이스 음은 새 근음 — 뒤 반 마디에 끼운 B7이 원래 패턴의 5음(F#)부터 시작하면
                # F#m6처럼 들린다. 근음이 같으면(텐션만, 자리바꿈 C/E → Cmaj9/E) 그대로
                first = min(idx, key=lambda i: notes[i].start)
                for i in idx:
                    pitch = notes[i].pitch
                    q = bass_note(pitch, seg.old, seg.new)
                    if i == first and seg.new.root != seg.old.root:
                        # 옥타브는 원래 베이스의 근음 자리에서 가까운 쪽 (5음 A45 → 근음 D38 → Db37, 위로 올라가 건반과 겹치지 않게)
                        q = min(127, max(0, pitch - (pitch - seg.old.root) % 12 + _shift(seg.old.root, seg.new.root)))
                    notes[i] = notes[i].model_copy(update={"pitch": q})
                continue
            # 베이스 트랙이 없으면(왈츠 왼손 "쿵-짝-짝", 한 트랙에 베이스 · 화음 · 윗선율이 섞인 루프) 음마다 베이스인지 본다:
            # 그 순간 울리는 음 중 맨 아래이고 위 음과 5도 넘게 떨어졌거나, 구간 첫 박에 혼자 친 음. 베이스는 베이스 트랙처럼 옮긴다
            for k, stroke in enumerate(_strokes(idx, notes)):
                low = min(stroke, key=lambda i: notes[i].pitch)
                floor = None
                if bass is None and self_bass(notes, low, seg.old, first=k == 0 and notes[low].start <= seg.start + 0.25):
                    notes[low] = notes[low].model_copy(update={"pitch": bass_note(notes[low].pitch, seg.old, seg.new)})
                    floor = notes[low].pitch
                    stroke = [i for i in stroke if i != low]
                if stroke:
                    moved = revoice([notes[i].pitch for i in stroke], seg.new, floor=floor)
                    for i, p in zip(stroke, moved):
                        notes[i] = notes[i].model_copy(update={"pitch": p})
        changed = sum(len(idx) for idx in by_seg.values())
        if changed:
            track.notes = sorted(notes, key=lambda n: (n.start, n.pitch))
            counts[track.name] = changed
    return out, counts
