"""드럼 패턴 만들기 (generate_drums). 코드는 따르지 않고, 곡의 박자 · 템포 · 편성에 맞춰 장르 패턴을 깐다.

- 스타일: 로파이 · 붐뱁 · 하우스 · 트랩 · 팝 · 록. 스타일마다 패턴 둘(A · B)과 소리 조합(팔레트) 셋.
  팔레트 = 드럼 킷 + 레인별로 섞은 소리 (트랩: 808 킷에 909 클랩 · 일렉 킥 …). 요즘 힙합 · 팝은 어쿠스틱 킷 하나보다
  전자 드럼과 여러 샘플을 섞어 써서 ("드럼도 전자 드럼이 있고 여러 샘플을 쓴다"는 말을 들었다)
- 다른 버전: 패턴 A → B, 그다음 팔레트를 바꾼다 (버전 1 A+팔레트1, 2 B+팔레트1, 3 A+팔레트2 …)
- 밀도: 하이햇을 4분(낮음) · 그대로(보통) · 16분(높음)으로
- 필인: 4마디마다(곡이 8마디 이상이면) 마지막 박을 탐 · 스네어 필인으로, 다음 마디 첫 박에 크래시
- 스윙: 로파이 57% · 붐뱁 54% (8분음표 — DAW처럼 뒷 8분음표만 늦춘다. 16분으로 했더니 8분 햇에는 스윙이 안 걸렸다).
  사람 느낌은 세기만 조금 흔든다 (타이밍은 격자 그대로 — 더 흔들려면 humanize)
- 3/4처럼 4박이 아닌 박자는 마디 첫 박 킥 + 나머지 박 스네어(약하게) + 8분 햇
- 실제 연주 (2026-11-11): 록 · 붐뱁 · 로파이 · 팝 · 펑크 · 소울 · 재즈 · 라틴은 위 패턴 대신 실제 드러머 연주 루프를 찾아 쓴다
  (app/generate/grooves.py, Groove MIDI Dataset · CC BY 4.0). 하우스 · 트랩 · 4박이 아닌 박자 · 하이햇 롤 · "마디마다 똑같이"는 위 패턴
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random

from app.generate.grooves import GROOVE_STYLES, Groove, candidates, groove_notes, has_style
from app.models.project import Note, Project
from app.tools.instrument import heard_program

KICK, RIM, SNARE, CLAP, HAT, PEDAL, OPEN, CRASH, RIDE = 36, 37, 38, 39, 42, 44, 46, 49, 51
TOMS = (50, 48, 45, 43)  # 높은 탐 → 낮은 탐 (필인)
LEVELS = {"X": 112, "x": 92, "o": 66, "g": 42}  # 패턴 글자 → 세기 (강세 · 보통 · 약하게 · 고스트)
JITTER = 6  # 세기를 이만큼 흔든다 (사람이 친 느낌)
HIT = 0.2  # 박. 한 방 치는 소리의 길이 (16분음표보다 짧게 — 스윙으로 늦춘 햇이 다음 햇과 겹치지 않게)
PHRASE = 4  # 마디. 필인 · 크래시 단위

# 한 마디 16칸 (16분음표). 레인 → 글자 (. = 안 침)
PATTERNS: dict[str, list[dict[int, str]]] = {
    "lofi": [
        {KICK: "X......x..x.....", SNARE: "....X.......X...", HAT: "x.o.x.o.x.o.x.o."},
        {KICK: "X.........X..o..", SNARE: "....X.......X..g", HAT: "x.oox.o.x.oox.o."},
    ],
    "boombap": [
        {KICK: "X......X..X.....", SNARE: "....X.......X...", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X.x.......X..x..", SNARE: "....X..g....X...", HAT: "x.x.x.x.x.x.x.x."},
    ],
    "house": [
        {KICK: "X...X...X...X...", CLAP: "....X.......X...", OPEN: "..x...x...x...x.", HAT: "o...o...o...o..."},
        {KICK: "X...X...X...X...", CLAP: "....X.......X...", OPEN: "..o...o...o...o.", HAT: "x.g.x.g.x.g.x.g."},
    ],
    "trap": [
        {KICK: "X.....x...x.....", CLAP: "........X.......", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X..x......X..x..", CLAP: "........X.......", HAT: "x.x.x.xxx.x.x.x."},
    ],
    "pop": [
        {KICK: "X.......X.x.....", SNARE: "....X.......X...", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X..x....X.......", SNARE: "....X.......X...", HAT: "x.o.x.o.x.o.x.o."},
    ],
    "rock": [
        {KICK: "X.....x.X.......", SNARE: "....X.......X...", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X.x.....X.x.....", SNARE: "....X.......X...", HAT: "x.x.x.x.x.x.x.x."},
    ],
    # 아래 넷은 보통 실제 연주를 쓰고, 이 패턴은 롤 · "마디마다 똑같이"일 때만
    "funk": [
        {KICK: "X.x....x..x..x..", SNARE: "....X..g.g..X..g", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X..x..x...X.....", SNARE: "....X.g.....X.g.", HAT: "xxxxxxxxxxxxxxxx"},
    ],
    "soul": [
        {KICK: "X.......X.x.....", SNARE: "....X.......X...", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X..x....X.......", SNARE: "....X.......X..g", HAT: "x.o.x.o.x.o.x.o."},
    ],
    "jazz": [
        {RIDE: "x...x..xx...x..x", PEDAL: "....x.......x...", KICK: "X..............."},
        {RIDE: "x...x..xx...x..x", PEDAL: "....x.......x...", SNARE: "......g.......g."},
    ],
    "latin": [
        {KICK: "X..x....X..x....", RIM: "..x..x....x..x..", HAT: "x.x.x.x.x.x.x.x."},
        {KICK: "X..x..x.X..x..x.", RIM: "...x..x...x..x..", HAT: "x.x.x.x.x.x.x.x."},
    ],
}


@dataclass(frozen=True)
class Palette:
    kit: int  # GM 드럼 킷 번호 (app/tools/instrument.py DRUM_KITS)
    sounds: dict[int, str] = field(default_factory=dict)  # 레인 → 소리 id (app/tools/drums.py DRUM_SOUNDS)
    back: int | None = None  # 뒷박을 이 레인으로 (스네어 대신 클랩 등). None = 패턴 그대로


PALETTES: dict[str, list[Palette]] = {
    "lofi": [
        Palette(27),
        Palette(27, {KICK: "kick_soft", SNARE: "snare_soft", HAT: "hat_soft"}),
        Palette(27, {KICK: "kick_lofi", SNARE: "snare_boombap", HAT: "hat_crisp"}),
    ],
    "boombap": [
        Palette(28),
        Palette(28, {KICK: "kick_punch", SNARE: "snare_big", HAT: "hat_acoustic"}),
        Palette(28, {KICK: "kick_lofi", SNARE: "snare_lofi", HAT: "hat_soft"}),
    ],
    "house": [
        Palette(26),
        Palette(26, {KICK: "kick_house", CLAP: "clap", HAT: "hat_electro", OPEN: "openhat_electro"}),
        Palette(24, {KICK: "kick_electro", CLAP: "clap_909", HAT: "hat_909", OPEN: "openhat_909"}),
    ],
    "trap": [
        Palette(25),
        Palette(25, {KICK: "kick_electro", CLAP: "clap", HAT: "hat_808"}),
        Palette(25, {KICK: "kick_808", CLAP: "clap_909", HAT: "hat_crisp"}),
    ],
    "pop": [
        Palette(0),
        Palette(24, back=CLAP),  # 일렉 킷에 클랩 뒷박 (요즘 팝)
        Palette(0, {KICK: "kick_punch", CLAP: "clap", HAT: "hat_crisp"}, back=CLAP),
    ],
    "rock": [Palette(16), Palette(0), Palette(8)],
    "funk": [Palette(0), Palette(8), Palette(0, {KICK: "kick_punch", SNARE: "snare_big", HAT: "hat_crisp"})],
    "soul": [Palette(8), Palette(0, {KICK: "kick_soft", SNARE: "snare_soft", HAT: "hat_acoustic"}), Palette(27)],
    "jazz": [Palette(32), Palette(32, {RIDE: "ride_jazz", KICK: "kick_soft"}), Palette(8, {RIDE: "ride_jazz"})],
    "latin": [Palette(0), Palette(8), Palette(32)],
}

# 드럼을 소리별 트랙으로 나눌 때의 묶음 (레인 = GM 음 번호). 킷마다 소리가 달라서, 나누면 트랙마다 다른 킷을 고를 수 있다
# (킥은 808, 스네어는 붐뱁, 햇은 909 …). "드럼을 한 트랙씩"이라는 요청
PARTS: dict[str, set[int]] = {
    "kick": {35, 36},
    "snare": {37, 38, 39, 40},  # 스네어 · 림 · 클랩
    "hats": {42, 44, 46, 51, 53, 59},  # 닫힌 · 페달 · 열린 햇, 라이드
    "fx": {41, 43, 45, 47, 48, 50, 49, 52, 55, 57},  # 탐 (필인) · 크래시
}
PART_NAMES = {"kick": "Kick", "snare": "Snare", "hats": "Hats", "fx": "Drum FX"}


def part_of(pitch: int) -> str | None:
    return next((p for p, lanes in PARTS.items() if pitch in lanes), None)


def track_part(notes: list[Note]) -> str | None:
    """트랙 음이 한 묶음에만 있으면 그 묶음 (나눠 만든 트랙), 여러 묶음이면 None (드럼 전체)."""
    parts = {part_of(n.pitch) for n in notes}
    return next(iter(parts)) if len(parts) == 1 and None not in parts else None


SWING = {"lofi": 57.0, "boombap": 54.0, "jazz": 62.0}  # 8분음표 스윙 퍼센트 (나머지는 정박). 실제 연주는 연주의 스윙 그대로

# 하이햇 롤: 말이 없으면 넣는 스타일, 그리고 롤 모양 (마디 안 시작 박, 한 칸 길이(박), 칸 수) — 32분 4개 · 16분 셋잇단 6개
ROLL_STYLES = {"trap"}
ROLLS = [(3.5, 0.125, 4), (3.0, 1 / 6, 6), (2.5, 0.125, 4), (1.5, 0.125, 4), (2.0, 1 / 6, 6), (1.0, 1 / 6, 6)]
HAT_JITTER = 9  # 햇 세기는 조금 더 흔든다 (같은 세기로 계속 치면 기계처럼 들림)
SWING_GRID = 0.5  # 박. 8분음표
ELECTRONIC_KITS = {24, 25, 26}
KIT_STYLES = {27: "lofi", 28: "boombap", 26: "house", 25: "trap", 16: "rock", 32: "jazz"}


def auto_style(project: Project) -> str:
    """스타일을 말하지 않았을 때: 이미 있는 드럼 킷 → 템포 · 편성 순으로."""
    for t in project.tracks:
        if t.is_drum and t.program in KIT_STYLES:
            return KIT_STYLES[t.program]
    heard = [heard_program(t) for t in project.tracks if not t.is_drum]
    kits = {t.program for t in project.tracks if t.is_drum}
    electronic = any(80 <= p <= 87 or p in (38, 39) for p in heard) or bool(kits & ELECTRONIC_KITS)
    tempo = project.tempo
    if electronic and tempo >= 130:
        return "trap"
    if electronic and tempo >= 115:
        return "house"
    if tempo < 95:
        return "lofi" if any(p <= 7 for p in heard) else "boombap"
    return "pop"


@dataclass
class DrumPlan:
    style: str
    palette: Palette
    swing: float  # 퍼센트 (50 = 정박)
    fills: int  # 넣은 필인 수
    density: str
    pattern: int = 1  # 패턴 1 · 2 (결과 요약에 — LLM이 무엇이 바뀌었는지 짐작해 말하지 않게)
    rolls: bool = False  # 하이햇 롤을 넣었나 (32분 · 셋잇단 — 검사가 그 자리를 박 어긋남으로 보지 않게)
    variation: bool = False  # 하이햇을 마디마다 바꿨나
    groove: Groove | None = None  # 실제 연주를 썼으면 그 루프 (위치가 연주 그대로라 박 검사를 하지 않는다)


def _groove_plan(project: Project, start: float, end: float, style: str, density: str, fills: bool,
                 swing: float | None, version: int) -> tuple[list[Note], DrumPlan] | None:
    """실제 연주 루프로. 맞는 루프가 없으면 None (손으로 쓴 패턴으로)."""
    cands = candidates(style, project.tempo, density if density != "mid" else None, swing, seed=project.id)
    if not cands:
        return None
    groove = cands[(version - 1) % len(cands)]
    palettes = PALETTES[style]
    palette = palettes[((version - 1) // 2) % len(palettes)]
    notes, filled = groove_notes(groove, start, end, fills=fills, density=density, crash=CRASH, toms=TOMS, phrase=PHRASE)
    if palette.back is not None:  # 뒷박을 클랩으로 (팝 소리 조합)
        notes = [n.model_copy(update={"pitch": palette.back}) if n.pitch == SNARE else n for n in notes]
    return _untangle(notes), DrumPlan(style, palette, 50.0, filled, density, (version - 1) % len(cands) + 1, groove=groove)


def _bar_pattern(style: str, variant: int, bpb: float) -> dict[int, str]:
    if abs(bpb - 4) < 1e-6:
        return dict(PATTERNS[style][variant % len(PATTERNS[style])])
    # 4박이 아닌 박자 — 패턴 1: 첫 박 킥, 나머지 박 스네어(약하게), 8분 햇 / 패턴 2: 첫 박 · 마지막 박 킥, 둘째 박 스네어
    # (하나뿐이면 "다른 버전"이 패턴 2를 건너뛰고 소리 조합부터 바뀌었다)
    steps = int(round(bpb * 4))
    hat = "".join("x" if i % 2 == 0 else "." for i in range(steps))
    if variant % 2 == 0:
        kick = "X" + "." * (steps - 1)
        snare = "".join("o" if i % 4 == 0 and i else "." for i in range(steps))
    else:
        kick = "".join("X" if i == 0 else "x" if i == steps - 4 and steps > 8 else "." for i in range(steps))
        snare = "".join("x" if i == 4 else "." for i in range(steps))
    return {KICK: kick, SNARE: snare, HAT: hat}


def _thin(pattern: dict[int, str], density: str) -> dict[int, str]:
    """밀도: 낮음은 햇을 4분음표로 · 고스트 빼기, 높음은 비어 있는 16분 칸을 약한 햇으로 (열린 햇 자리는 비움)."""
    out = dict(pattern)
    if HAT not in out:
        return out
    if density == "low":
        out[HAT] = "".join(c if i % 4 == 0 else "." for i, c in enumerate(out[HAT]))
        out = {lane: s.replace("g", ".") for lane, s in out.items()}
    elif density == "high":
        opens = out.get(OPEN, "")
        out[HAT] = "".join(c if c != "." else ("." if i < len(opens) and opens[i] != "." else "g") for i, c in enumerate(out[HAT]))
    return out


def _hat_bar(row: str, k: int, rng: Random, *, rolls: bool, variation: bool, swung: bool, opens: bool,
             fill: bool) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    """한 마디의 닫힌 햇 · 덧붙인 열린 햇 [(마디 안 박, 세기)]. 4마디 묶음의 첫 마디는 무늬 그대로 (곡의 기준이 들리게),
    나머지 마디는 조금씩 바꾼다 — 1마디 무늬를 똑같이 되풀이했더니 "루프처럼 안 나오고 규칙처럼만 나온다"는 말이 나왔다."""
    hats = [(i * 0.25, LEVELS[c]) for i, c in enumerate(row) if c != "."]
    added_open: list[tuple[float, int]] = []
    if k % PHRASE == 0 or len(row) != 16:
        return hats, added_open
    taken = lambda pos: any(abs(p - pos) < 1e-6 for p, _ in hats)  # noqa: E731
    if variation:
        # 다음 박 앞 16분 하나 (스윙 스타일은 빼고 — 뒷 8분을 늦추는 느낌이 흐려진다)
        if not swung and rng.random() < 0.6:
            pos = rng.choice([0.75, 1.75, 2.75]) if not fill else rng.choice([0.75, 1.75])
            if not taken(pos):
                hats.append((pos, LEVELS["g"]))
        # 짝수 마디 끝(4박 뒤 8분)에 열린 햇 (열린 햇이 이미 도는 무늬 · 필인 마디는 빼고)
        if not opens and not fill and k % 2 == 1 and rng.random() < 0.7:
            hats = [(p, v) for p, v in hats if abs(p - 3.5) > 1e-6]
            added_open.append((3.5, LEVELS["x"]))
    if rolls:
        # 필인 마디의 4박은 탐 · 클랩 자리라 롤은 그 앞에
        start, step, count = rng.choice([r for r in ROLLS if not (fill and r[0] + r[1] * r[2] > 3.0 + 1e-6)])
        end = start + step * count
        hats = [(p, v) for p, v in hats if not start - 1e-6 <= p < end - 1e-6]
        added_open = [(p, v) for p, v in added_open if not start - 1e-6 <= p < end - 1e-6]
        hats += [(round(start + j * step, 4), round(48 + (100 - 48) * j / (count - 1))) for j in range(count)]  # 점점 세게
    return sorted(hats), added_open


def drum_notes(
    project: Project, start: float, end: float, style: str | None = None, density: str | None = None,
    fills: bool = True, swing: float | None = None, version: int = 1, rolls: bool | None = None, variation: bool = True,
    real: bool = True,
) -> tuple[list[Note], DrumPlan]:
    """[start, end) 박에 드럼. 마디 단위로 깐다 (범위가 마디 중간에서 시작하면 그 마디의 남은 칸부터).
    real: 실제 연주가 있는 스타일이면 실제 연주로 (False = 손으로 쓴 격자 패턴)."""
    style = style or auto_style(project)
    density = density or "mid"
    if (real and style in GROOVE_STYLES and has_style(style) and abs(project.beats_per_bar - 4) < 1e-6
            and rolls is not True and variation):
        made = _groove_plan(project, start, end, style, density, fills, swing, version)
        if made is not None:
            return made
    variant = (version - 1) % 2
    palettes = PALETTES[style]
    palette = palettes[((version - 1) // 2) % len(palettes)]
    pct = SWING.get(style, 50.0) if swing is None else swing
    rolls = (style in ROLL_STYLES) if rolls is None else rolls
    rolls = rolls and density != "low" and abs(project.beats_per_bar - 4) < 1e-6  # 단순하게 · 4박이 아닌 박자는 롤 없이
    variation = variation and abs(project.beats_per_bar - 4) < 1e-6
    late = (pct / 100 * 2 - 1) * SWING_GRID
    bpb = project.beats_per_bar
    steps = int(round(bpb * 4))
    rng = Random(version * 7919 + int(start))
    pattern = _thin(_bar_pattern(style, variant, bpb), density)
    if palette.back is not None and SNARE in pattern and palette.back not in pattern:
        pattern[palette.back] = pattern.pop(SNARE)  # 뒷박을 클랩으로
    first_bar, last_bar = int(start // bpb), math.ceil(end / bpb - 1e-9) - 1
    bars = last_bar - first_bar + 1
    fill_every = PHRASE if bars >= 2 * PHRASE else (bars if bars >= 2 else 0)
    notes: list[Note] = []
    filled = 0
    after_fill = False  # 바로 앞 마디에 필인을 넣었나 (크래시는 필인 뒤 첫 박에만 — 3/4처럼 필인이 없으면 크래시도 없다)
    for bar in range(first_bar, last_bar + 1):
        k = bar - first_bar
        fill = fills and fill_every and (k + 1) % fill_every == 0 and abs(bpb - 4) < 1e-6
        lanes = dict(pattern)
        if fill:  # 마지막 박(13~16칸): 원래 음을 비우고 탐 넷 (트랩 · 하우스는 뒷박 소리를 16분으로 점점 세게)
            lanes = {lane: s[:12] + "...." for lane, s in lanes.items()}
            roll = CLAP if style in ("trap", "house") else None
            if roll is not None:
                lanes[roll] = lanes.get(roll, "." * 16)[:12] + "goxX"
            else:
                for i, tom in enumerate(TOMS):
                    lanes[tom] = "." * (12 + i) + "x" + "." * (3 - i)
            filled += 1
        if after_fill:  # 필인 뒤 첫 박에 크래시
            lanes[CRASH] = "X" + "." * (steps - 1)
        after_fill = bool(fill)
        events: dict[int, list[tuple[float, int]]] = {
            lane: [(i * 0.25, LEVELS[c]) for i, c in enumerate(row[:steps]) if c != "."] for lane, row in lanes.items() if lane != HAT
        }
        if HAT in lanes:
            hats, opens = _hat_bar(lanes[HAT][:steps], k, rng, rolls=rolls, variation=variation, swung=pct != 50,
                                   opens=OPEN in pattern, fill=bool(fill))
            events[HAT] = hats
            if opens:
                events[OPEN] = events.get(OPEN, []) + opens
        for lane, hits in events.items():
            jitter = HAT_JITTER if lane == HAT else JITTER
            for pos, level in hits:
                on_eighth = abs(pos % 1 - 0.5) < 1e-6
                t = bar * bpb + pos + (late if on_eighth else 0.0)  # 뒷 8분음표만
                if not start - 1e-6 <= t < end - 1e-6:
                    continue
                vel = max(1, min(127, level + rng.randint(-jitter, jitter)))
                length = 1.0 if lane in (CRASH, OPEN) else HIT
                notes.append(Note(pitch=lane, start=round(t, 4), duration=round(min(length, end - t), 4), velocity=vel))
    return _untangle(notes), DrumPlan(style, palette, pct, filled, density, variant + 1, rolls, variation)


def _untangle(notes: list[Note]) -> list[Note]:
    """같은 레인에서 늦춘 음(스윙)이 다음 음에 닿으면 길이를 줄이고, 같은 자리에 겹치면 하나만 둔다."""
    out: list[Note] = []
    for n in sorted(notes, key=lambda n: (n.pitch, n.start)):
        prev = out[-1] if out and out[-1].pitch == n.pitch else None
        if prev is not None and n.start - prev.start < 1e-3:
            continue
        if prev is not None and prev.start + prev.duration > n.start:
            out[-1] = prev.model_copy(update={"duration": round(n.start - prev.start, 4)})
        out.append(n)
    return sorted(out, key=lambda n: (n.start, n.pitch))
