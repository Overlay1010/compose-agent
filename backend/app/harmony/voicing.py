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
from app.harmony.reharm import INTERVALS, rubs
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


def fill_tone(
    pitches: list[int], chord: ChordSpan, have: set[int] | None = None, floor: int | None = None, ceiling: int | None = None,
) -> int | None:
    """옮긴 화음 묶음(pitches)에 더할 빠진 코드 음 하나 (근음 · 5음 말고, PRIORITY 순): 음이 적은 건반(3음)에 Cmaj9를 담으면
    9음이 빠져 Cmaj7로 들린다. 빠진 게 없거나 자리가 없으면 None.
    have: 이미 울리는 음 (기본은 pitches). floor · ceiling: 이 사이로만 (같은 트랙의 베이스 위 · 윗선율 아래).
    자리는 묶음 안쪽 → 위 → 아래, 한 음뿐이면 아래 → 위 (윗선율 위로 올라가지 않게). 같은 음 · 반음으로 붙는 자리는 피한다."""
    ivs = INTERVALS.get(chord.quality, (0, 4, 7))
    have = have if have is not None else {p % 12 for p in pitches}
    missing = [(chord.root + i) % 12 for i in PRIORITY if i in ivs and i not in (0, 7) and (chord.root + i) % 12 not in have]
    if not missing:
        return None
    low, high = min(pitches), max(pitches)
    lo = floor + 1 if floor is not None else 0
    hi = ceiling - 1 if ceiling is not None else 127
    near = [q for q in range(low - 12, high + 13) if q % 12 == missing[0] and lo <= q <= hi and all(abs(q - p) > 1 for p in pitches)]
    inside = [q for q in near if low < q < high]
    above = [q for q in near if q > high]
    below = [q for q in near if q < low][::-1]
    for group in (inside, above, below) if len(pitches) > 1 else (below, above):
        if group:
            return group[0]
    return None


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


PASSING = 1.0  # 박. 이보다 짧은 코드 밖 음은 지나가는 음 (그대로 둔다)


def line_note(n: Note, old: ChordSpan, new: ChordSpan) -> int:
    """혼자 친 음(펼침화음 · 한 트랙에 섞인 윗선율)의 새 음높이.

    코드 음이거나 길게 누른 음은 가까운 새 코드 음으로, 짧게 지나가는 코드 밖 음은 그대로 — 새 코드와 반음으로 부딪힐 때만 옮긴다.
    지나가는 음까지 다 옮기면 내려가는 선율 98 96 94 93이 98 94 94 94처럼 같은 음 되풀이가 된다 (Astroworld).
    """
    chord_tone = (n.pitch - old.root) % 12 in INTERVALS.get(old.quality, (0, 4, 7))
    if chord_tone or n.duration >= PASSING or rubs(n.pitch % 12, new.root, new.quality):
        return _nearest(n.pitch, set(_tones(new)), set())
    return n.pitch


OWN = 1.0  # 박. 코드 경계에 걸친 음의 한쪽이 이만큼 이하이고 다른 쪽이 그 두 배 이상이면 자르지 않고 긴 쪽 코드의 음으로 본다


def _pieces(n: Note, segs: list[Segment]) -> list[tuple[float, float, Segment | None]]:
    """음을 코드 바뀜 자리에서 나눈 조각 [(시작, 끝, 그 조각이 든 바뀐 구간 또는 None)].

    당겨 친 음(마디보다 1박 먼저 친 Eb 화음)과 살짝 넘어간 꼬리는 자르지 않는다 — 자르면 같은 음을 마디선에서 다시 치거나
    누르던 음이 중간에 바뀐다. 조각은 가운데가 든 구간의 것 (당겨 친 음은 다음 코드의 음).
    """
    end = n.start + n.duration
    bounds = sorted({t for s in segs for t in (s.start, s.end) if n.start + EPS < t < end - EPS})
    # 당겨 친 음 = 짧게(1박 이하) 먼저 치고 그 두 배 이상을 다음 코드에서 울림. 반씩 걸친 음(사람이 친 흔들림)은 자른다
    keep = lambda short, long: short <= OWN and long >= 2 * short  # noqa: E731
    cuts = [t for t in bounds if not (keep(t - n.start, end - t) or keep(end - t, t - n.start))]
    edges = [n.start, *cuts, end]
    out = []
    for a, b in zip(edges, edges[1:]):
        mid = (a + b) / 2
        seg = next((s for s in segs if s.start - EPS <= mid < s.end - EPS), None)
        out.append((a, b, seg))
    return out


STRUM = 0.1  # 박. 이만큼 안에 시작한 음은 같이 친 한 화음 (사람이 친 흔들림 · 스트럼)


def _strokes(idx: list[int], notes: list[Note], seg_start: float) -> list[list[int]]:
    """한 구간 안의 조각들을 같이 친 화음 묶음으로. 당겨 친 음은 구간 첫 박에 친 것으로 본다."""
    at = lambda i: max(notes[i].start, seg_start)  # noqa: E731
    out: list[list[int]] = []
    for i in sorted(idx, key=at):
        if out and at(i) - at(out[-1][0]) <= STRUM:
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


def _add(notes: list[Note], origin: list[int], stroke: list[int], pitch: int | None) -> None:
    """stroke(같이 친 음 번호들)와 같은 박 · 길이 · 세기로 pitch 음을 더한다 (origin -1 = 원래 없던 음)."""
    if pitch is None:
        return
    s = min(notes[i].start for i in stroke)
    e = max(notes[i].start + notes[i].duration for i in stroke)
    vel = round(sum(notes[i].velocity for i in stroke) / len(stroke))
    notes.append(Note(pitch=pitch, start=round(s, 4), duration=round(e - s, 4), velocity=vel))
    origin.append(-1)


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
        origin: list[int] = []  # 조각이 나온 원래 음 번호 (같은 음높이로 남은 조각은 다시 잇는다)
        by_seg: dict[int, list[int]] = {}  # 바뀐 구간마다 그 안에 든 조각
        for j, n in enumerate(track.notes):
            parts = _pieces(n, segs)
            if all(seg is None for _, _, seg in parts):
                notes.append(n)
                origin.append(j)
                continue
            for a, b, seg in parts:
                if b - a < MIN_PIECE:
                    continue
                notes.append(n.model_copy(update={"start": round(a, 4), "duration": round(b - a, 4)}))
                origin.append(j)
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
            opening = None  # 구간 첫 묶음 (베이스 뺀 음, 베이스 음)
            added = len(notes)  # 이 구간에서 더한 음은 여기부터
            for k, stroke in enumerate(_strokes(idx, notes, seg.start)):
                stroke = sorted(stroke, key=lambda i: notes[i].pitch)
                low = stroke[0]
                floor = None
                if bass is None and self_bass(notes, low, seg.old, first=k == 0 and notes[low].start <= seg.start + 0.25):
                    notes[low] = notes[low].model_copy(update={"pitch": bass_note(notes[low].pitch, seg.old, seg.new)})
                    floor = notes[low].pitch
                    stroke = stroke[1:]
                if k == 0:
                    opening = (stroke, floor)
                # 맨 위 음이 바로 아래 음과 5도 넘게 떨어졌으면 화음이 아니라 윗선율 (한 트랙에 섞인 멜로디). 혼자 친 음도 선율처럼
                gap = len(stroke) >= 2 and notes[stroke[-1]].pitch - notes[stroke[-2]].pitch >= CLOSE_BASS
                line = stroke if len(stroke) == 1 else stroke[-1:] if gap else []
                stroke = [i for i in stroke if i not in line]
                for i in line:
                    notes[i] = notes[i].model_copy(update={"pitch": line_note(notes[i], seg.old, seg.new)})
                if len(stroke) == 1:
                    notes[stroke[0]] = notes[stroke[0]].model_copy(update={"pitch": line_note(notes[stroke[0]], seg.old, seg.new)})
                elif stroke:
                    moved = revoice([notes[i].pitch for i in stroke], seg.new, floor=floor)
                    for i, p in zip(stroke, moved):
                        notes[i] = notes[i].model_copy(update={"pitch": p})
                    # 음이 모자라 3 · 7음이나 텐션(9 · 13음)이 빠졌으면 같은 박 · 세기로 한 음 더한다 (Cmaj9가 Cmaj7로 들리지 않게)
                    have = {notes[i].pitch % 12 for i in [*stroke, *line]} | ({floor % 12} if floor is not None else set())
                    ceiling = min((notes[i].pitch for i in line), default=None)
                    _add(notes, origin, stroke, fill_tone([notes[i].pitch for i in stroke], seg.new, have, floor, ceiling))
            # 묶음이 선율 · 펼침화음으로 흩어져 있으면(Dreamer: 베이스 + 펼친 3화음 + 위 두 음) 구간 전체에 없을 때 첫 묶음에
            if opening and opening[0]:
                upper, floor = opening
                have = {notes[i].pitch % 12 for i in [*idx, *range(added, len(notes))]}
                _add(notes, origin, upper, fill_tone([notes[i].pitch for i in upper], seg.new, have, floor))
        # 나눈 조각이 다시 같은 음높이면 잇는다 (자른 자리에서 같은 음을 두 번 치지 않게)
        joined: list[Note] = []
        for i, n in enumerate(notes):
            prev = joined[-1] if joined and i > 0 and origin[i] == origin[i - 1] else None
            if prev is not None and prev.pitch == n.pitch and abs(prev.start + prev.duration - n.start) < 1e-3:
                joined[-1] = prev.model_copy(update={"duration": round(n.start + n.duration - prev.start, 4)})
            else:
                joined.append(n)
        before = {(n.pitch, n.start, n.duration) for n in track.notes}
        changed = sum((n.pitch, n.start, n.duration) not in before for n in joined)
        if changed:
            track.notes = sorted(joined, key=lambda n: (n.start, n.pitch))
            counts[track.name] = changed
    return out, counts
