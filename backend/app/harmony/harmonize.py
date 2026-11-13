"""멜로디에 코드 붙이기 (화음 트랙 없이 멜로디 · 베이스 같은 한 줄짜리만 있는 곡).

분석 엔진(analyze)은 이미 깔린 화음을 읽는 용도라, 멜로디 한 줄만 주면 Ebmaj7/D · Absus2 · E/G(G 단조 곡에 E 장조)처럼
멜로디가 지나가는 음까지 코드 이름에 넣었다. 여기서는 조성 안의 화음 중에서 고른다:
- 단위: 반 마디. 반 마디마다 조성의 음계 화음(장조 I ii iii IV V vi, 단조 i III iv v V VI VII) 후보에 점수를 매기고
- 점수 = 멜로디가 그 코드에 얼마나 맞나(센박 · 긴 음일수록 크게: 코드 음 +, 코드 음 반음 위 -, 조성 밖 -)
       + 베이스 음이 근음인가 (한 줄짜리 베이스가 있으면)
       + 앞 코드에서 이어지기 자연스러운가 (화성학의 흔한 진행 — 아래 MOVES. 곡 데이터에서 뽑지 않는다:
         가진 샘플팩은 서비스 학습에 쓸 수 없어서, 재는 데만 쓴다)
- 가장 점수가 높은 이어짐을 비터비로 고른다. 마디 가운데서 코드를 바꾸면 벌점(반 마디마다 바뀌는 코드가 남발되지 않게).
멜로디가 쉬는 마디(아무 음도 없음)는 N.C.로 두고, 반주 쪽에서 앞뒤 진행으로 채운다 (app/generate/chords.fill_rests).
"""

from __future__ import annotations

import math

from app.harmony.analyze import ChordSpan, HarmonyAnalysis, KeyInfo, analyze, label, spell
from app.models.project import Note, Project, Track

# 후보 화음: 으뜸음에서의 거리 → 종류 ("" 장 · "m" 단)
CANDIDATES = {
    "major": [(0, ""), (2, "m"), (4, "m"), (5, ""), (7, ""), (9, "m")],
    "minor": [(0, "m"), (3, ""), (5, "m"), (7, "m"), (7, ""), (8, ""), (10, "")],
}
# 흔한 진행 (앞 → 뒤, 으뜸음에서의 거리 · 종류). 여기 있으면 +GOOD, 같은 코드 그대로는 따로, 나머지는 0
MOVES = {
    "major": {
        (0, ""): [(5, ""), (7, ""), (9, "m"), (2, "m")],
        (2, "m"): [(7, ""), (5, "")],
        (4, "m"): [(9, "m"), (5, "")],
        (5, ""): [(7, ""), (0, ""), (2, "m")],
        (7, ""): [(0, ""), (9, "m")],
        (9, "m"): [(2, "m"), (5, ""), (7, "")],
    },
    "minor": {
        (0, "m"): [(5, "m"), (8, ""), (10, ""), (3, ""), (7, "")],
        (3, ""): [(8, ""), (5, "m"), (10, "")],
        (5, "m"): [(7, ""), (0, "m"), (10, "")],
        (7, "m"): [(0, "m"), (8, "")],
        (7, ""): [(0, "m"), (8, "")],
        (8, ""): [(10, ""), (3, ""), (5, "m"), (7, "")],
        (10, ""): [(3, ""), (0, "m"), (8, "")],
    },
}
TRIADS = {"": (0, 4, 7), "m": (0, 3, 7)}
# 코드마다 기본 선호도 (반 마디마다, PRIOR_SCALE을 곱함): 으뜸 · 딸림 · 버금딸림이 가장 흔하다. 노팅엄 민요에서 멜로디만 보면
# vi를 정답보다 3배(757 vs 260), 단조 VII을 2.7배 붙이고 V는 덜 붙였다 (멜로디가 두 코드에 같이 든 음에 머물 때)
PRIOR = {
    "major": {(0, ""): 1.0, (7, ""): 1.0, (5, ""): 0.6, (2, "m"): 0.3, (9, "m"): 0.0, (4, "m"): -0.5},
    "minor": {(0, "m"): 1.0, (7, ""): 0.8, (5, "m"): 0.6, (7, "m"): 0.3, (3, ""): 0.3, (8, ""): 0.3, (10, ""): 0.0},
}
PRIOR_SCALE = 0.3

GOOD = 0.6  # 흔한 진행 가산점 (멜로디 맞음 점수와 같은 단위: 한 박 동안 코드 음 = 1)
STAY_BAR = 0.0  # 마디선에서 같은 코드 그대로 (민요는 0.3이 더 맞지만 루프 곡이 8마디 내내 코드 하나가 됐다)
CHANGE_MID = 1.0  # 마디 가운데서 코드를 바꾸는 벌점
START_TONIC = 0.5  # 첫 코드가 으뜸화음
FLAT_V = 0.3  # 단조의 v(단화음) 벌점 — 이끎음이 없으면 v도 맞지만, 끝맺음엔 V가 흔하다

# 멜로디 음 한 박의 점수 (코드 근음에서의 거리)
FIT_ROOT, FIT_THIRD, FIT_FIFTH = 1.0, 1.0, 0.8
FIT_SEVENTH = 0.3  # 7음 (그 코드를 7화음으로 들리게 할 뿐)
FIT_TENSION = 0.0  # 9 · 11 · 13음 중 코드 음과 반음으로 안 부딪히는 것
RUB = -0.8  # 코드 음의 반음 위 (단9로 부딪힘 — 장3화음 위의 4음 같은 것)
OUT_OF_KEY = -0.5
# 박 안의 자리마다 무게: 반 마디 첫 박 · 박 · 엇박. 앞에서 이어 끄는 음은 HELD
ON_UNIT, ON_BEAT, OFF_BEAT, HELD = 1.5, 1.0, 0.6, 0.8
BASS_ROOT, BASS_TONE, BASS_OTHER = 1.0, 0.2, -0.6  # 한 줄짜리 베이스 음 (한 박마다)
POLY = 0.1  # 같이 시작하는 음이 이 비율보다 많으면 화음 트랙
TOGETHER = 0.05  # 박. 이 안에서 시작하면 같이 누른 것 (손으로 친 화음의 어긋남)
BASS_BELOW = 48  # 음 높이 가운데값이 이보다 낮은 한 줄짜리 트랙은 베이스로 본다 (C3)


def is_line(track: Track) -> bool:
    """한 줄로 움직이는 트랙 — 멜로디 · 베이스 · 아르페지오. 화음 트랙은 여러 음을 같은 순간에 누른다.
    처음엔 음이 겹치는 비율로 봤는데, 꾸밈음 · 레가토로 음이 살짝씩 겹치는 멜로디(Cymatics Sphinx)가 화음 트랙이 돼
    코드를 붙이지 않고 예전처럼 멜로디 음으로 코드 이름을 지었다(E/G) → 같이 시작하는 음의 비율로."""
    starts = sorted(n.start for n in track.notes)
    if len(starts) < 2:
        return True
    together = sum(1 for a, b in zip(starts, starts[1:]) if b - a < TOGETHER)
    return together / (len(starts) - 1) < POLY


def needs_harmony(project: Project) -> bool:
    """화음을 치는 트랙이 하나도 없고(멜로디 · 베이스 같은 한 줄짜리만) 음은 있는 곡 — 코드를 읽을 게 아니라 붙여야 한다."""
    pitched = [t for t in project.tracks if not t.is_drum and t.notes]
    return bool(pitched) and all(is_line(t) for t in pitched)


def _is_bass(track: Track) -> bool:
    from app.tools.instrument import heard_program  # app.tools가 app.harmony를 부르므로 여기서

    pitches = sorted(n.pitch for n in track.notes)
    return 32 <= heard_program(track) <= 39 or pitches[len(pitches) // 2] < BASS_BELOW


def _place_weight(start: float, unit_start: float) -> float:
    if start < unit_start - 1e-6:
        return HELD
    if abs(start - unit_start) < 1e-6:
        return ON_UNIT
    return ON_BEAT if abs(start - round(start)) < 1e-6 else OFF_BEAT


def _fit(rel: int, quality: str, in_key: bool) -> float:
    """멜로디 음(코드 근음에서 rel 반음)이 그 코드에 얼마나 맞나."""
    third = 3 if quality == "m" else 4
    if rel == 0:
        return FIT_ROOT
    if rel == third:
        return FIT_THIRD
    if rel == 7:
        return FIT_FIFTH
    if any((rel - t) % 12 == 1 for t in TRIADS[quality]):
        return RUB
    if not in_key:
        return OUT_OF_KEY
    return FIT_SEVENTH if rel in (10, 11) else FIT_TENSION


def _unit_notes(notes: list[Note], s: float, e: float) -> list[tuple[Note, float]]:
    return [(n, min(e, n.start + n.duration) - max(s, n.start)) for n in notes
            if min(e, n.start + n.duration) - max(s, n.start) > 1e-6]


def harmonize(project: Project, key: KeyInfo | None = None) -> HarmonyAnalysis:
    """화음 트랙이 없는 곡에 반 마디 단위로 코드를 붙인다. 아무 음도 없는 반 마디는 N.C.
    key가 없으면 멜로디로 읽은 조성. 나란한조(G minor ↔ Bb major)로도 붙여 보고 점수가 높은 쪽을 고르게 해 봤는데,
    노팅엄 민요에서 조성 일치가 77 → 34%로 떨어지고 문턱을 둬도 나아지지 않아 뺐다."""
    bpb = project.beats_per_bar
    lines = [t for t in project.tracks if not t.is_drum and t.notes]
    basses = [t for t in lines if _is_bass(t)] if len(lines) > 1 else []
    tune = [n for t in lines if t not in basses for n in t.notes]
    low = [n for t in basses for n in t.notes]
    read = analyze(project.model_copy(update={"tracks": [t for t in lines if t not in basses] or lines})).key
    if not tune and not low:
        return HarmonyAnalysis(key=key or read, chords=[], beats_per_bar=bpb)
    chosen = key or read
    _, spans = _harmonize_in(chosen, tune, low, bpb)
    label(spans, chosen)
    return HarmonyAnalysis(key=chosen, chords=spans, beats_per_bar=bpb)


def _harmonize_in(key: KeyInfo, tune: list[Note], low: list[Note], bpb: float) -> tuple[float, list[ChordSpan]]:
    """key 안에서 비터비로 코드를 고른다. (가장 좋은 이어짐의 점수, 코드들)."""
    scale = {(key.tonic + i) % 12 for i in ((0, 2, 4, 5, 7, 9, 11) if key.mode == "major" else (0, 2, 3, 5, 7, 8, 10, 11))}
    cands = CANDIDATES[key.mode]
    end = max(n.start + n.duration for n in tune + low)
    half = bpb / 2
    units = [(i * half, (i + 1) * half) for i in range(math.ceil(end / half - 1e-6))]

    def emit(s: float, e: float) -> list[float] | None:
        heard = _unit_notes(tune, s, e)
        under = _unit_notes(low, s, e)
        if not heard and not under:
            return None
        out = []
        for rel_root, quality in cands:
            root = (key.tonic + rel_root) % 12
            # 멜로디 점수는 음 길이 합으로 나눠 반 마디 길이에 맞춘다 — 16분음표 위주 멜로디(트랩 리프)는 점수가 작아
            # 이어짐 가산점에 밀려 곡 전체가 코드 하나가 됐다
            weight = sum(ov * _place_weight(n.start, s) for n, ov in heard)
            score = sum(ov * _place_weight(n.start, s) * _fit((n.pitch - root) % 12, quality, n.pitch % 12 in scale)
                        for n, ov in heard) / weight * (e - s) if heard else 0.0
            for n, ov in under:
                rel = (n.pitch - root) % 12
                score += ov * (BASS_ROOT if rel == 0 else BASS_TONE if rel in TRIADS[quality] else BASS_OTHER)
            if key.mode == "minor" and (rel_root, quality) == (7, "m"):
                score -= FLAT_V
            out.append(score + PRIOR_SCALE * PRIOR[key.mode].get((rel_root, quality), 0.0))
        return out

    good = {a: set(b) for a, b in MOVES[key.mode].items()}

    def move(a: int, b: int, mid: bool) -> float:
        if a == b:
            return STAY_BAR if not mid else 0.0
        return (GOOD if cands[b] in good.get(cands[a], ()) else 0.0) - (CHANGE_MID if mid else 0.0)

    # 비터비. 소리가 없는 반 마디는 이어짐만 (N.C.로 내보내고, 다음 코드와의 이어짐은 앞 코드에서 그대로 잇는다)
    emissions = [emit(s, e) for s, e in units]
    tonic = [START_TONIC if c[0] == 0 else 0.0 for c in cands]
    best: list[float] = [0.0] * len(cands)
    back: list[list[int]] = []
    started = False
    for i, em in enumerate(emissions):
        mid = abs(units[i][0] % bpb) > 1e-6
        if em is None:
            back.append(list(range(len(cands))))
            continue
        if not started:
            best = [em[j] + tonic[j] for j in range(len(cands))]
            back.append(list(range(len(cands))))
            started = True
            continue
        row, ptr = [], []
        for j in range(len(cands)):
            k = max(range(len(cands)), key=lambda k: best[k] + move(k, j, mid))
            row.append(best[k] + move(k, j, mid) + em[j])
            ptr.append(k)
        best, back = row, back + [ptr]
    best = [b + t for b, t in zip(best, tonic)]  # 끝 코드도 으뜸화음이면
    j = max(range(len(cands)), key=lambda k: best[k])
    total = best[j]
    path = [0] * len(units)
    for i in range(len(units) - 1, -1, -1):
        path[i] = j
        j = back[i][j]

    # 한 마디보다 짧게 쉬는 곳(곡 중간)은 앞 코드를 이어 끈다 — 반 마디 쉼표마다 반주가 끊기지 않게.
    # 그보다 긴 빈 곳은 N.C.로 두고 반주 쪽(fill_rests)이 앞뒤 진행으로 채운다
    sounding = [em is not None for em in emissions]
    first = sounding.index(True)
    last = len(sounding) - 1 - sounding[::-1].index(True)
    i = first
    while i <= last:
        if sounding[i]:
            i += 1
            continue
        k = i
        while not sounding[k]:
            k += 1
        if (k - i) * half < bpb - 1e-6:
            for m in range(i, k):
                sounding[m] = True
        i = k

    spans: list[ChordSpan] = []
    for (s, e), heard, j in zip(units, sounding, path):
        if not heard:
            root = None
        else:
            rel_root, quality = cands[j]
            root = (key.tonic + rel_root) % 12
        if spans and spans[-1].root == root and (root is None or spans[-1].quality == quality):
            spans[-1].end = e
            continue
        if root is None:
            spans.append(ChordSpan(s, e, None, None, "N.C.", "", "", "", 0.0))
        else:
            spans.append(ChordSpan(s, e, root, root, spell(root, key) + quality, quality, "", "", 1.0))
    return total, spans


def song_chords(project: Project) -> HarmonyAnalysis:
    """곡의 코드: 화음 트랙이 있으면 읽고(analyze), 한 줄짜리만 있으면 붙인다(harmonize)."""
    return harmonize(project) if needs_harmony(project) else analyze(project)


__all__ = ["harmonize", "needs_harmony", "song_chords", "is_line"]
