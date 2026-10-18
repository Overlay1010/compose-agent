"""조성 · 코드 분석.

- 조성: Krumhansl–Kessler 장 · 단조 기준 분포와 곡의 음 길이 분포(12음)의 상관을 24개 조에 대해 비교한다.
  나란한 장 · 단조(C 장조 ↔ A 단조)가 비슷하면 마지막 코드의 근음으로 정한다.
- 코드: 구간(기본 한 마디)마다 12개 근음 후보에 "근음 · 3도 · 5도 · 7도가 얼마나 울리나 + 베이스가 그 음인가" 점수를
  매겨 근음을 고르고, 실제로 울린 음정으로 이름을 붙인다 (maj9 · m7b5 · sus4 · 13 · 슬래시 코드 …).
  근음을 빼고 치는 건반 보이싱(Fmaj9 = 건반 A C E G + 베이스 F)도 베이스를 함께 봐서 읽는다.
  한 마디를 반으로 나눈 쪽이 확실히 더 잘 맞고 근음이 다르면 두 코드로 본다.
- 로마숫자 · 기능: 키 기준 I · ii · V7 …, 다음 코드로 5도 내려가는 딸림7화음은 부속 화음(V7/ii)으로 적는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.models.project import Project, Track

# (음 번호, 시작, 길이, 가중치) — 멜로디 트랙은 가중치를 낮춰 지나가는 음이 코드음으로 잡히지 않게 한다
Tone = tuple[int, float, float, float]
MELODY_WEIGHT = 0.5

# ---------- 이름 ----------

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# 플랫으로 적는 조 (장조 으뜸음 / 단조 으뜸음)
FLAT_MAJOR = {5, 10, 3, 8, 1, 6}  # F Bb Eb Ab Db Gb
FLAT_MINOR = {2, 7, 0, 5, 10, 3}  # D G C F Bb Eb


def pc_name(pc: int, flats: bool) -> str:
    return (FLAT if flats else SHARP)[pc % 12]


# ---------- 조성 ----------

# Krumhansl & Kessler (1982) 조성 기준 분포 (으뜸음 = 0)
KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


@dataclass
class KeyInfo:
    tonic: int  # 0 = C
    mode: str  # "major" | "minor"
    name: str  # "C major" / "A minor"
    name_ko: str  # "C 장조" / "A 단조"
    confidence: float  # 1등과 2등 상관의 차 (0~)
    alternatives: list[str] = field(default_factory=list)  # 다음 후보 (예: ["A minor", "G major"])

    @property
    def flats(self) -> bool:
        return self.tonic in (FLAT_MAJOR if self.mode == "major" else FLAT_MINOR)


def _corr(a: list[float], b: list[float]) -> float:
    ma, mb = sum(a) / 12, sum(b) / 12
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def _key_name(tonic: int, mode: str) -> tuple[str, str]:
    flats = tonic in (FLAT_MAJOR if mode == "major" else FLAT_MINOR)
    n = pc_name(tonic, flats)
    return f"{n} {mode}", f"{n} {'장조' if mode == 'major' else '단조'}"


def find_key(hist: list[float]) -> KeyInfo:
    """음 분포만으로 정한 대략의 키 (코드 이름의 #/b를 고르는 데 쓴다. 최종 키는 decide_key)."""
    scores = []
    for tonic in range(12):
        rotated = [hist[(tonic + i) % 12] for i in range(12)]
        scores.append((_corr(rotated, KK_MAJOR), tonic, "major"))
        scores.append((_corr(rotated, KK_MINOR), tonic, "minor"))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    name, name_ko = _key_name(best[1], best[2])
    alts = [_key_name(t, m)[0] for _, t, m in scores[1:4] if (t, m) != (best[1], best[2])][:2]
    return KeyInfo(best[1], best[2], name, name_ko, round(best[0] - second[0], 3), alts)


# ---------- 코드 ----------

# 근음에서의 음정 → 코드음으로서 얼마나 그럴듯한가 (음수 = 그 근음이면 어색한 음)
FIT = {0: 1.0, 4: 0.8, 3: 0.8, 7: 0.55, 10: 0.45, 11: 0.45, 2: 0.25, 9: 0.25, 5: 0.05, 6: -0.25, 8: -0.3, 1: -0.6}
BASS_BONUS = 0.25  # 근음 없는 보이싱(베이스가 근음)은 읽고, 자리바꿈(C/E)은 베이스를 근음으로 오해하지 않는 정도
PRESENT = 0.12  # 구간에서 가장 많이 울린 음의 이만큼 이상이면 "울린 음"으로 본다


@dataclass
class ChordSpan:
    start: float  # 박
    end: float
    root: int | None  # None = 화음 없음 (N.C.)
    bass: int | None
    name: str  # "Fmaj9", "C/E", "N.C."
    quality: str  # "maj9", "m7", "" …
    roman: str  # "IVmaj7", "V7/ii", "" …
    function: str  # "T" | "S" | "D" | "부속" | "차용" | ""
    score: float  # 근음 판단 점수 (높을수록 확실)


def _weights(tones: list[Tone], start: float, end: float) -> tuple[list[float], int | None, list[float]]:
    """구간에서 12음이 울린 길이(가중치 반영), 그리고 베이스음.

    베이스 = 구간 첫 박에 울리는 가장 낮은 음 (왈츠의 "쿵"처럼 첫 박 음이 베이스다).
    첫 박에 울리는 음이 없으면, 같은 음높이 길이를 합쳐 구간의 1/4 이상 울린 음 중 가장 낮은 음
    (짧게 반복하는 베이스도 잡히게).
    """
    w = [0.0] * 12
    wh = [0.0] * 12  # 화음 트랙(멜로디 말고)만 — 9 · 11 · 13 같은 덧붙인 음은 여기 있을 때만 이름에 넣는다
    by_pitch: dict[int, float] = {}
    first: list[int] = []
    for pitch, n_start, dur, weight in tones:
        overlap = min(end, n_start + dur) - max(start, n_start)
        if overlap <= 1e-6:
            continue
        w[pitch % 12] += overlap * weight
        if weight >= 1.0:
            wh[pitch % 12] += overlap
        by_pitch[pitch] = by_pitch.get(pitch, 0.0) + overlap
        if n_start <= start + 0.25 and n_start + dur > start + 1e-6:
            first.append(pitch)
    if not by_pitch:
        return w, None, wh
    if first:
        return w, min(first) % 12, wh
    span = end - start
    solid = [p for p, d in by_pitch.items() if d >= span * 0.25] or list(by_pitch)
    return w, min(solid) % 12, wh


def _best_root(w: list[float], bass: int | None) -> tuple[int, float]:
    total = sum(w) or 1.0
    best = (0, -9.0)
    for r in range(12):
        score = sum(w[pc] * FIT[(pc - r) % 12] for pc in range(12)) / total
        if bass == r:
            score += BASS_BONUS
        if score > best[1]:
            best = (r, score)
    return best


def _quality(present: set[int]) -> str:
    """근음 기준 음정 집합 → 코드 종류 이름 (근음 이름 뒤에 붙는 부분)."""
    maj3, min3 = 4 in present, 3 in present
    p5, b5, s5 = 7 in present, 6 in present, 8 in present
    m7, M7, d7 = 10 in present, 11 in present, 9 in present
    nine, eleven, thirteen = 2 in present, 5 in present, 9 in present
    if min3 and not maj3:
        if b5 and not p5:
            if m7:
                return "m7b5"
            if d7:
                return "dim7"
            return "dim"
        if M7:
            return "m(maj7)"
        if m7:
            return "m11" if eleven and nine else "m9" if nine else "m7"
        if thirteen:
            return "m6"
        return "madd9" if nine else "m"
    if maj3:
        if s5 and not p5 and not (m7 or M7):
            return "aug"
        if M7:
            return "maj13" if thirteen and nine else "maj9" if nine else "maj7"
        if m7:
            return "13" if thirteen else "9" if nine else "7"
        if thirteen:
            return "6/9" if nine else "6"
        return "add9" if nine else ""
    # 3음이 없음
    if eleven:
        return "7sus4" if m7 else "sus4"
    if nine:
        return "sus2"
    return "5" if p5 else ""


def name_chord(
    w: list[float], bass: int | None, flats: bool, wh: list[float] | None = None
) -> tuple[int | None, str, str, float]:
    """(근음, 이름, 종류, 점수). 울린 음이 없으면 근음 None · "N.C."."""
    if sum(w) <= 1e-6:
        return None, "N.C.", "", 0.0
    root, score = _best_root(w, bass)
    top = max(w)
    present = {(pc - root) % 12 for pc in range(12) if w[pc] >= top * PRESENT}
    # 덧붙인 음(9 · 11 · 13)은 화음 트랙에서 울렸을 때만 (멜로디의 지나가는 음은 빼고)
    if wh is not None and sum(wh) > 1e-6:
        htop = max(wh)
        present = {i for i in present if i not in (2, 5, 9) or wh[(root + i) % 12] >= htop * 0.15}
    q = _quality(present)
    name = pc_name(root, flats) + q
    if bass is not None and bass != root:
        name += "/" + pc_name(bass, flats)
    return root, name, q, round(score, 3)


# ---------- 로마숫자 · 기능 ----------

MAJOR_DEGREES = {0: "I", 2: "II", 4: "III", 5: "IV", 7: "V", 9: "VI", 11: "VII"}
MINOR_DEGREES = {0: "I", 2: "II", 3: "III", 5: "IV", 7: "V", 8: "VI", 10: "VII", 11: "VII"}
SEVENTH = {"maj7": "maj7", "maj9": "maj7", "maj13": "maj7", "7": "7", "9": "7", "13": "7", "7sus4": "7sus4",
           "m7": "7", "m9": "7", "m11": "7", "m(maj7)": "maj7", "m7b5": "ø7", "dim7": "°7", "dim": "°"}


def _numeral(interval: int, quality: str, key: KeyInfo) -> str:
    degrees = MAJOR_DEGREES if key.mode == "major" else MINOR_DEGREES
    if interval in degrees:
        base = degrees[interval]
        if key.mode == "minor" and interval == 11:
            base = "#VII"  # 단조의 이끎음 (화성 단음계)
    else:
        # 음계 밖: 반음 위 음의 단계에 b (bII · bIII · bVI · bVII · bV)
        base = "b" + (MAJOR_DEGREES if key.mode == "major" else MINOR_DEGREES).get((interval + 1) % 12, "?")
    if family(quality) in ("min", "dim"):
        base = base.lower()  # 단화음 · 감화음은 소문자 (ii, vii°)
    return base + SEVENTH.get(quality, "")


def _function(interval: int, quality: str, key: KeyInfo) -> str:
    minor_like = family(quality) == "min"
    if key.mode == "major":
        diatonic = {0: "T", 4: "T", 9: "T", 2: "S", 5: "S", 7: "D", 11: "D"}
    else:
        diatonic = {0: "T", 3: "T", 8: "T", 2: "S", 5: "S", 7: "D", 10: "D", 11: "D"}
    f = diatonic.get(interval)
    if f is None:
        return "차용"
    # 장조에서 iv(단화음 IV)처럼 음계와 다른 종류면 차용으로
    if key.mode == "major" and interval in (5, 7, 0) and minor_like:
        return "차용"
    return f


def label(spans: list[ChordSpan], key: KeyInfo) -> None:
    """각 코드에 로마숫자와 기능을 붙인다 (부속 딸림화음은 다음 코드를 보고 정한다)."""
    for i, c in enumerate(spans):
        if c.root is None:
            continue
        interval = (c.root - key.tonic) % 12
        c.roman = _numeral(interval, c.quality, key)
        c.function = _function(interval, c.quality, key)
        dominant = c.quality in ("7", "9", "13") and interval != 7
        nxt = next((s for s in spans[i + 1:] if s.root is not None), None)
        if dominant and nxt is not None and (nxt.root - c.root) % 12 == 5:
            # 다음 코드로 완전5도 내려가는 딸림7화음 = 그 코드의 부속 딸림화음 (V7/ii …)
            target = _numeral((nxt.root - key.tonic) % 12, nxt.quality, key).rstrip("7").replace("maj", "").replace("ø", "").replace("°", "")
            c.roman = f"V7/{target}"
            c.function = "부속"


# ---------- 코드 진행으로 키 다시 정하기 ----------

# 조의 음계 화음: 으뜸음에서의 거리 → 종류 ("maj" | "min" | "dim", 여러 개면 모두 맞음)
DIATONIC = {
    "major": {0: {"maj"}, 2: {"min"}, 4: {"min"}, 5: {"maj"}, 7: {"maj"}, 9: {"min"}, 11: {"dim"}},
    "minor": {0: {"min"}, 2: {"dim"}, 3: {"maj"}, 5: {"min"}, 7: {"min", "maj"}, 8: {"maj"}, 10: {"maj"}, 11: {"dim"}},
}


def family(quality: str) -> str | None:
    if quality.startswith("dim") or quality == "m7b5":
        return "dim"
    if quality.startswith("m") and not quality.startswith("maj"):
        return "min"
    if quality in ("", "aug") or quality[0].isdigit() or quality.startswith(("maj", "add", "6")):
        return "maj"
    return None  # sus · 5 (3음 없음)


# 으뜸화음으로 끝나는 곡(종지)과 으뜸화음으로 시작하는 루프(샘플팩 MIDI) 둘 다 있어서 첫 · 마지막 코드를 비슷하게 본다
LAST_BONUS = 0.2
FIRST_BONUS = 0.3


def chord_fit(spans: list["ChordSpan"], tonic: int, mode: str) -> float:
    """코드들이 그 조의 음계 화음과 얼마나 맞나 (0~1, 길이 가중) + 마지막 · 첫 코드가 으뜸화음이면 더함."""
    table = DIATONIC[mode]
    want_tonic = "maj" if mode == "major" else "min"
    total = fit = 0.0
    for c in spans:
        if c.root is None:
            continue
        d = c.end - c.start
        total += d
        allowed = table.get((c.root - tonic) % 12)
        fam = family(c.quality)
        if allowed is None:
            continue
        fit += d * (1.0 if fam in allowed else 0.75 if fam is None else 0.5)
    score = fit / total if total else 0.0
    real = [c for c in spans if c.root is not None]
    if real:
        if real[-1].root == tonic and family(real[-1].quality) in (want_tonic, None):
            score += LAST_BONUS
        if real[0].root == tonic and family(real[0].quality) in (want_tonic, None):
            score += FIRST_BONUS
    return score


def decide_key(hist: list[float], spans: list["ChordSpan"]) -> KeyInfo:
    """음 분포 상관(Krumhansl–Kessler)이 높은 후보 6개 중에서 코드 진행이 가장 잘 맞는 조."""
    cands = []
    for tonic in range(12):
        rotated = [hist[(tonic + i) % 12] for i in range(12)]
        cands.append((_corr(rotated, KK_MAJOR), tonic, "major"))
        cands.append((_corr(rotated, KK_MINOR), tonic, "minor"))
    cands.sort(reverse=True)
    ranked = sorted(((kk + 0.6 * chord_fit(spans, t, m), t, m) for kk, t, m in cands[:6]), reverse=True)
    best, second = ranked[0], ranked[1]
    name, name_ko = _key_name(best[1], best[2])
    alts = [_key_name(t, m)[0] for _, t, m in ranked[1:3]]
    return KeyInfo(best[1], best[2], name, name_ko, round(best[0] - second[0], 3), alts)


# ---------- 분석 ----------

@dataclass
class HarmonyAnalysis:
    key: KeyInfo
    chords: list[ChordSpan]
    beats_per_bar: float

    def text(self) -> str:
        """에이전트 · 사람이 읽는 요약."""
        bars: list[str] = []
        for c in self.chords:
            bar = int(c.start // self.beats_per_bar) + 1
            where = f"{bar}마디" if abs(c.start % self.beats_per_bar) < 1e-6 else f"{bar}마디 {c.start % self.beats_per_bar + 1:g}박"
            bars.append(f"{where} {c.name}" + (f"({c.roman})" if c.roman else ""))
        alt = f" (다음 후보: {', '.join(self.key.alternatives)})" if self.key.alternatives else ""
        return f"조성: {self.key.name_ko} [확실도 {self.key.confidence}]{alt}\n코드: " + " · ".join(bars)


def _is_melody(track: Track, lowest: str | None) -> bool:
    """한 줄로만 움직이는(겹치는 음이 거의 없는) 트랙 중 가장 낮은 트랙(베이스)이 아닌 것."""
    if track.id == lowest or len(track.notes) < 2:
        return False
    notes = sorted(track.notes, key=lambda n: n.start)
    overlaps = sum(1 for a, b in zip(notes, notes[1:]) if b.start < a.start + a.duration - 1e-3)
    return overlaps / (len(notes) - 1) < 0.1


def _tones(project: Project) -> list[Tone]:
    pitched = [t for t in project.tracks if not t.is_drum and t.notes]
    lowest = min(pitched, key=lambda t: sum(n.pitch for n in t.notes) / len(t.notes)).id if pitched else None
    out: list[Tone] = []
    for t in pitched:
        weight = MELODY_WEIGHT if _is_melody(t, lowest) else 1.0
        out += [(n.pitch, n.start, n.duration, weight) for n in t.notes]
    return out


def analyze(project: Project, split_margin: float = 0.12) -> HarmonyAnalysis:
    """곡 전체를 분석한다. 드럼은 뺀다."""
    tones = _tones(project)
    bpb = project.beats_per_bar
    length = max((s + d for _, s, d, _ in tones), default=0.0)
    bars = max(1, math.ceil(length / bpb - 1e-9)) if tones else 0

    # 1) 키를 먼저 대략 정해야 #/b 이름을 고를 수 있다 → 음 분포로 한 번, 코드 진행까지 보고 다시
    hist = [0.0] * 12
    for pitch, _, dur, weight in tones:
        hist[pitch % 12] += dur * weight
    key = find_key(hist)
    flats = key.flats

    # 2) 마디마다 코드 (반으로 나눈 쪽이 확실히 낫고 근음이 다르면 두 개로)
    spans: list[ChordSpan] = []
    for b in range(bars):
        s, e = b * bpb, (b + 1) * bpb
        w, bass, wh = _weights(tones, s, e)
        root, name, q, score = name_chord(w, bass, flats, wh)
        half = bpb / 2 if bpb % 2 == 0 else None  # 3/4 같은 홀수 박자는 나누지 않는다
        parts = None
        if half and root is not None:
            halves = []
            for hs, he in ((s, s + half), (s + half, e)):
                hw, hb, hwh = _weights(tones, hs, he)
                halves.append((hs, he, hb, *name_chord(hw, hb, flats, hwh)))
            r1, r2 = halves[0][3], halves[1][3]
            if r1 is not None and r2 is not None and r1 != r2 and (halves[0][6] + halves[1][6]) / 2 > score + split_margin:
                parts = halves
        if parts:
            for hs, he, hb, r, nm, hq, sc in parts:
                spans.append(ChordSpan(hs, he, r, hb, nm, hq, "", "", sc))
        else:
            spans.append(ChordSpan(s, e, root, bass, name, q, "", "", score))

    # 3) 같은 코드가 이어지면 하나로 합친다
    merged: list[ChordSpan] = []
    for c in spans:
        if merged and merged[-1].name == c.name and abs(merged[-1].end - c.start) < 1e-6:
            merged[-1].end = c.end
        else:
            merged.append(c)

    # 4) 코드 진행까지 보고 키를 정하고, 그 키의 #/b로 이름을 다시 붙인 뒤 로마숫자 · 기능
    key = decide_key(hist, merged)
    for c in merged:
        if c.root is not None:
            c.name = pc_name(c.root, key.flats) + c.quality + (f"/{pc_name(c.bass, key.flats)}" if c.bass is not None and c.bass != c.root else "")
    label(merged, key)
    return HarmonyAnalysis(key, merged, bpb)
