"""편곡 점검: 새로 깐 트랙이 곡의 다른 트랙과 맞는지 — 오케스트레이션의 "점검" 단계 (app/tools/arrange.py).

생성 검사(app/generate/check.py)는 트랙 하나만 본다. 여기서는 트랙끼리 본다:
- 반음 부딪힘: 서로 다른 트랙의 두 음이 단2도 · 단9도(아래 음에서 반음 + 옥타브들)로 0.5박 넘게 같이 울린다.
  장7도(C 위의 B)는 maj7 화음의 정상 음이라 세지 않는다. 새 트랙이 낀 것만 센다 (원래 곡끼리 부딪히는 건 사용자의 음악)
- 음역 겹침: 새 화음 트랙(패드 · 반주 · 아르페지오)이 소리 성격이 같은 다른 트랙과 같은 높이를 7반음 넘게 같이 쓴다
- 구간 에너지: "9마디부터 더 꽉 차게"(lift)라고 했으면 그 구간이 나머지보다 실제로 꽉 찼는지 (구간 읽기와 같은 에너지 잣대)
- 베이스 · 킥: 베이스가 킥과 같이 치는 비율 (정보 — 문제로 치지 않음)
음을 고치지 않는 순수 함수. 문제는 사람이 읽는 말로 적는다 (LLM이 그대로 전하고 고칠 방법을 고르게).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from app.arrange.sections import bar_energy
from app.generate.drums import PARTS
from app.models.project import Note, Project, Track

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
OVERLAP = 0.5  # 박. 이보다 짧게 겹치면 지나가는 음으로 본다
CLASH_LIMIT = 2.0  # 박. 새 트랙이 낀 반음 부딪힘이 곡 전체에서 이보다 길면 문제
SHARED = 7  # 반음. 두 화음 트랙이 이만큼 넘게 같은 높이를 쓰면 문제
LIFT_GAP = 0.05  # 더 꽉 차게 한 구간은 나머지보다 에너지(0~1)가 이만큼은 높아야 (다른 구간으로 나누는 차이는 0.15)
LONG = 1.0  # 박. 음 길이 가운데값이 이보다 길면 길게 끄는 소리
KICK_NEAR = 0.06  # 박. 킥과 이만큼 안에서 치면 같이 친 것


def note_name(pitch: int) -> str:
    return f"{NAMES[pitch % 12]}{pitch // 12 - 1}"


@dataclass
class Clash:
    bar: int
    a: str  # 트랙 이름 (아래 음)
    b: str  # 트랙 이름 (위 음)
    low: int
    high: int
    beats: float


@dataclass
class Lift:
    bars: tuple[int, int]
    energy: str  # higher · lower
    inside: float  # 그 구간 에너지 (0~1)
    outside: float  # 나머지
    ok: bool
    drum_only: list[int] = field(default_factory=list)  # 그 구간에서 드럼 말고는 아무것도 안 울리는 마디


@dataclass
class Review:
    clash_beats: float  # 새 트랙이 낀 반음 부딪힘 (박)
    clashes: list[Clash]  # 많이 부딪힌 곳부터 (최대 5)
    overlaps: list[str]  # "Arp(D3~E5)가 Pad(C3~E4)와 9반음 겹쳐요"
    lifts: list[Lift]
    kick_lock: float | None  # 베이스가 킥과 같이 친 비율 (킥 · 베이스가 있을 때)
    problems: list[str] = field(default_factory=list)

    def data(self) -> dict:
        """LLM에게 보내는 점검 결과."""
        return {
            "problems": self.problems,
            "clash_beats": self.clash_beats,
            "clashes": [f"{c.bar}마디 {c.a} {note_name(c.low)} · {c.b} {note_name(c.high)} ({c.beats:g}박)" for c in self.clashes],
            "overlaps": self.overlaps,
            "lifts": [
                {"bars": list(lf.bars), "energy": lf.energy, "inside": lf.inside, "outside": lf.outside, "ok": lf.ok,
                 **({"drum_only_bars": lf.drum_only} if lf.drum_only else {})}
                for lf in self.lifts
            ],
            **({"kick_lock": round(self.kick_lock, 2)} if self.kick_lock is not None else {}),
        }


def _melodic(project: Project) -> list[Track]:
    return [t for t in project.tracks if not t.is_drum and t.notes]


def clashes(project: Project, new_ids: set[str]) -> list[Clash]:
    """새 트랙이 낀 반음 부딪힘. 같은 마디 · 같은 두 트랙 · 같은 두 음은 하나로 묶는다."""
    bpb = project.beats_per_bar
    tracks = _melodic(project)
    found: dict[tuple, Clash] = {}
    for i, ta in enumerate(tracks):
        for tb in tracks[i + 1:]:
            if ta.id not in new_ids and tb.id not in new_ids:
                continue
            for a in ta.notes:
                for b in tb.notes:
                    ov = min(a.start + a.duration, b.start + b.duration) - max(a.start, b.start)
                    if ov < OVERLAP:
                        continue
                    (lo_t, lo), (hi_t, hi) = sorted(((ta, a), (tb, b)), key=lambda x: x[1].pitch)
                    if (hi.pitch - lo.pitch) % 12 != 1:
                        continue
                    bar = int(max(a.start, b.start) // bpb) + 1
                    key = (bar, lo_t.id, hi_t.id, lo.pitch, hi.pitch)
                    if key in found:
                        found[key].beats = round(found[key].beats + ov, 2)
                    else:
                        found[key] = Clash(bar, lo_t.name, hi_t.name, lo.pitch, hi.pitch, round(ov, 2))
    return sorted(found.values(), key=lambda c: (-c.beats, c.bar))


def _span(notes: list[Note]) -> tuple[int, int]:
    """아래 · 위 10%를 뺀 음역 (튀는 음 하나에 끌려가지 않게)."""
    ps = sorted(n.pitch for n in notes)
    return ps[int(len(ps) * 0.1)], ps[min(len(ps) - 1, int(len(ps) * 0.9))]


def _is_bass(track: Track) -> bool:
    return 32 <= track.program <= 39 or (bool(track.notes) and _span(track.notes)[1] < 52)


def _long(track: Track) -> bool:
    return median(n.duration for n in track.notes) >= LONG


def overlaps(project: Project, new_ids: set[str]) -> list[str]:
    """새 화음 트랙(베이스 말고)이 소리 성격이 같은(길게 끄는 · 짧게 치는) 다른 트랙과 같은 높이를 SHARED반음 넘게 같이 쓰면.
    길게 끄는 패드 위에서 짧게 끊어 치는 반주가 같은 높이를 쓰는 건 흔한 편곡이라 치지 않는다 (음이 반음으로 부딪히면 clashes가 잡는다)."""
    tracks = [t for t in _melodic(project) if not _is_bass(t)]
    out = []
    for t in tracks:
        if t.id not in new_ids:
            continue
        lo, hi = _span(t.notes)
        for other in tracks:
            if other is t or (other.id in new_ids and other.id < t.id):  # 새 트랙끼리는 한 번만
                continue
            if _long(other) != _long(t):
                continue
            olo, ohi = _span(other.notes)
            shared = min(hi, ohi) - max(lo, olo)
            if shared > SHARED:
                out.append(f"{t.name}({note_name(lo)}~{note_name(hi)})가 {other.name}({note_name(olo)}~{note_name(ohi)})와 "
                           f"{shared}반음 겹쳐요")
    return out


def lifts(project: Project, wanted: list[tuple[tuple[int, int], str]]) -> list[Lift]:
    """구간 에너지(치는 트랙 비율 · 새로 치는 횟수 — 구간 읽기와 같은 잣대)를 나머지 마디와 비교한다.
    처음엔 박당 음 수로 쟀는데 16분 하이햇(박당 4개)에 끌려가, 그 구간에 반주를 한 겹 더해도 덜 찬 걸로 나왔다."""
    bpb = project.beats_per_bar
    end = max((n.start + n.duration for t in project.tracks for n in t.notes), default=0.0)
    bars = max(1, math.ceil(end / bpb - 1e-9))
    energy_by_bar = bar_energy(project, bars)
    out = []
    for (a, b), energy in wanted:
        inside_bars = [e for i, e in enumerate(energy_by_bar, 1) if a <= i <= b]
        rest = [e for i, e in enumerate(energy_by_bar, 1) if not a <= i <= b]
        inside = round(sum(inside_bars) / len(inside_bars), 2) if inside_bars else 0.0
        outside = round(sum(rest) / len(rest), 2) if rest else 0.0
        ok = (inside >= outside + LIFT_GAP) if energy == "higher" else (inside <= outside - LIFT_GAP)
        sounding = {bar for t in _melodic(project) for n in t.notes
                    for bar in range(int(n.start // bpb) + 1, int((n.start + n.duration - 1e-6) // bpb) + 2)}
        out.append(Lift((a, b), energy, inside, outside, ok or not rest or not inside_bars,
                        [bar for bar in range(a, min(b, bars) + 1) if bar not in sounding]))
    return out


def _bar_ranges(bars: list[int]) -> str:
    """[9, 10, 11, 12, 15] → "9~12 · 15마디"."""
    spans: list[list[int]] = []
    for b in bars:
        if spans and b == spans[-1][1] + 1:
            spans[-1][1] = b
        else:
            spans.append([b, b])
    return " · ".join(f"{s}~{e}" if s != e else f"{s}" for s, e in spans) + "마디"


def kick_lock(project: Project, new_ids: set[str]) -> float | None:
    kicks = sorted(n.start for t in project.tracks if t.is_drum for n in t.notes if n.pitch in PARTS["kick"])
    basses = [t for t in _melodic(project) if t.id in new_ids and _is_bass(t)]
    if not kicks or not basses:
        return None
    starts = [n.start for t in basses for n in t.notes]
    near = sum(1 for s in starts if any(abs(s - k) <= KICK_NEAR for k in kicks))
    return near / len(starts)


def review(project: Project, new_ids: set[str], wanted_lifts: list[tuple[tuple[int, int], str]] = ()) -> Review:
    found = clashes(project, new_ids)
    total = round(sum(c.beats for c in found), 1)
    over = overlaps(project, new_ids)
    lf = lifts(project, list(wanted_lifts))
    r = Review(clash_beats=total, clashes=found[:5], overlaps=over, lifts=lf, kick_lock=kick_lock(project, new_ids))
    if total > CLASH_LIMIT:
        worst = found[0]
        r.problems.append(
            f"반음으로 부딪히는 음이 {total:g}박 있어요 (가장 많은 곳: {worst.bar}마디 {worst.a} {note_name(worst.low)} · "
            f"{worst.b} {note_name(worst.high)})"
        )
    r.problems += over
    for x in lf:
        if not x.ok:
            word = "꽉 차게" if x.energy == "higher" else "덜어 내게"
            why = (f" — {_bar_ranges(x.drum_only)}는 드럼 말고 아무것도 안 울려요 (멜로디가 쉬어 읽을 코드가 없으면 화음 · 베이스도 비어요. "
                   f"그 마디의 코드 진행을 말해 주면 그대로 깔 수 있어요)" if x.drum_only else "")
            r.problems.append(
                f"{x.bars[0]}~{x.bars[1]}마디를 {word} 했는데 에너지(치는 트랙 수 · 촘촘함)가 {x.inside:g}로 나머지({x.outside:g})와 "
                f"{'비슷하거나 낮아요' if x.energy == 'higher' else '비슷하거나 높아요'}{why}"
            )
    return r
