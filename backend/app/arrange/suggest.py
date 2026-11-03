"""악기 추천: 곡 읽기(read_song)를 보고 "무엇이 비었나 → 그 자리에 어떤 악기"를 고른다.

1. 빈자리 찾기 (방향 2 — 트랙끼리 보기): 없는 역할(베이스 · 화음 · 위 선율) → 소리 성격 대비(짧은 소리뿐이면 긴 소리,
   긴 소리뿐이면 리듬이 사는 소리) → 가운데 빈 높이 → 맨 위 빈 높이 순.
2. 그 자리의 악기 후보: 곡 분위기(어쿠스틱 · 전자 · 그 밖)마다 어울리는 순서로 둔 후보 묶음에서, 이미 쓴 악기 · 그 높이를
   못 내는 악기는 빼고, 같은 높이에 비슷한 계열이 있으면 깎고, 원하는 소리 성격이면 더한다.
3. 점수가 비슷한 후보(1등과 12점 안)는 곡 · 버전마다 순서를 바꾼다 — 늘 같은 것만 추천하던 것("추천이 맨날 같다")을 막되,
   같은 곡 · 같은 버전이면 결과가 같다 ("다른 추천" = 버전 + 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from app.arrange.read import (
    CEILING, CHARACTER_KO, FAMILY_BRIGHTNESS, LONG_FAMILIES, ROLE_KO, Character, Role, SongMap, TrackProfile, fits, note_name,
)

# 역할 · 분위기마다 어울리는 순서 (GM 번호)
POOLS: dict[Role, dict[str, list[int]]] = {
    "bass": {"acoustic": [32, 35, 33, 34], "electronic": [38, 39, 33, 87], "neutral": [33, 34, 35, 32, 36, 38]},
    "pad": {"acoustic": [48, 49, 52, 89, 92], "electronic": [90, 94, 88, 95, 89, 91], "neutral": [89, 88, 92, 94, 48, 49]},
    "keys": {"acoustic": [0, 4, 11, 46], "electronic": [5, 4, 11, 90], "neutral": [4, 0, 5, 11, 12]},
    "pluck": {"acoustic": [46, 24, 45, 25], "electronic": [98, 11, 24, 84], "neutral": [24, 11, 46, 25, 12]},
    "lead": {"acoustic": [73, 40, 71, 68, 9], "electronic": [80, 81, 98, 9, 84], "neutral": [9, 73, 11, 14, 80, 71]},
}
# 역할마다 기본 높이 (빈 높이가 없을 때)
REGISTER: dict[Role, tuple[int, int]] = {"bass": (28, 52), "pad": (48, 72), "keys": (52, 76), "pluck": (55, 79), "lead": (64, 88)}
# 역할마다 바라는 소리 성격
WANT: dict[Role, Character] = {"bass": "mixed", "pad": "long", "keys": "mixed", "pluck": "short", "lead": "mixed"}
CLOSE = 12  # 점 — 1등과 이만큼 안이면 순서를 섞는다
# 역할마다 만드는 도구 (리드는 멜로디 생성기가 아직 없어서 화음에서 탑노트를 뽑아 그 악기로)
HOW: dict[Role, str] = {
    "bass": "generate_bassline(program=…)", "pad": "generate_chords(pattern=\"pad\", program=…)",
    "keys": "generate_chords(pattern=\"stab\", program=…)", "pluck": "generate_chords(pattern=\"arpeggio\", program=…)",
    "lead": "멜로디 생성기는 아직 없음 — duplicate_track(화음 트랙, voice=\"top\", program=…)로 탑노트를 그 악기로",
}


@dataclass
class Candidate:
    program: int
    score: float
    why: list[str]


@dataclass
class SamplePick:
    id: str
    name: str
    score: float
    why: list[str]


@dataclass
class Slot:
    role: Role
    low: int
    high: int
    reason: str
    candidates: list[Candidate] = field(default_factory=list)
    samples: list[SamplePick] = field(default_factory=list)


def _overlapping(song: SongMap, low: int, high: int) -> list[TrackProfile]:
    return [t for t in song.melodic if t.low is not None and t.high is not None and t.low <= high and low <= t.high]


def _gap_for(song: SongMap, role: Role) -> tuple[int, int] | None:
    """역할 기본 높이와 가장 많이 겹치는 빈 높이 (베이스는 늘 베이스 자리)"""
    if role == "bass":
        return None
    lo, hi = REGISTER[role]
    best, size = None, 0
    for a, b in song.gaps:
        overlap = min(b, hi) - max(a, lo)
        if overlap > size:
            best, size = (max(a, lo), min(b, hi)), overlap
    return best if size >= 5 else None


def needs(song: SongMap) -> list[tuple[Role, tuple[int, int], str]]:
    """빈자리 (역할, 높이, 이유) — 중요한 순"""
    out: list[tuple[Role, tuple[int, int], str]] = []
    reasons = {"bass": "베이스가 없어요 (아래를 받쳐 줄 소리)", "pad": "화음을 깔아 줄 트랙이 없어요", "lead": "위에서 들리는 선율이 없어요"}
    for role in song.missing:
        out.append((role, _gap_for(song, role) or REGISTER[role], reasons[role]))
    others = [t for t in song.melodic if t.role != "bass"]
    if others and all(t.character == "short" for t in others):
        out.append(("pad", _gap_for(song, "pad") or REGISTER["pad"], "지금은 짧게 끊기는 소리뿐이라, 길게 끄는 소리가 공간을 채워요"))
    if others and all(t.character == "long" for t in others):
        role: Role = "keys" if any(t.busy for t in others) else "pluck"  # 다 느리면 아르페지오로 리듬을
        out.append((role, _gap_for(song, role) or REGISTER[role], "지금은 길게 끄는 소리뿐이라, 리듬이 사는 소리가 있으면 덜 뭉개져요"))
    for a, b in song.gaps:
        if b == CEILING:
            out.append(("lead", (max(a, 72), min(b, 96)), f"{note_name(a)} 위쪽이 비어 반짝이는 소리(벨 · 글로켄 · 리드)를 얹을 자리예요"))
        else:
            middle = (a + b) // 2
            role = "keys" if middle >= 52 else "pad"
            out.append((role, (a, b), f"{note_name(a)}~{note_name(b)}가 비어 있어요 (그 높이를 채우면 소리가 두꺼워져요)"))
    # 같은 역할이 두 번 나오면 앞의 것(더 중요한 이유)만
    seen: set[Role] = set()
    unique = []
    for role, register, reason in out:
        if role not in seen:
            seen.add(role)
            unique.append((role, register, reason))
    return unique


def _candidates(song: SongMap, role: Role, low: int, high: int, seed: str) -> list[Candidate]:
    used = {t.program for t in song.melodic if t.sample is None}
    near = _overlapping(song, low, high)
    pool = POOLS[role][song.flavor]
    out: list[Candidate] = []
    for i, program in enumerate(pool):
        if program in used or not fits(program, low, high):
            continue
        family = program // 8
        score = 100 - 6 * i
        why = [f"{'어쿠스틱' if song.flavor == 'acoustic' else '전자음' if song.flavor == 'electronic' else '지금'} 편성에 어울림"]
        twins = [t.name for t in near if t.family == family and t.sample is None]
        if twins:
            score -= 25
            why.append(f"같은 높이의 {twins[0]}와 비슷한 계열")
        long_sound = family in LONG_FAMILIES
        if WANT[role] == "long" and long_sound or WANT[role] == "short" and not long_sound:
            score += 10
            why.append(CHARACTER_KO[WANT[role]])
        if near:
            around = sum(t.brightness for t in near) / len(near)
            mine = FAMILY_BRIGHTNESS[family]
            if abs(mine - around) >= 0.25:
                score += 5
                why.append("옆 트랙과 소리 빛깔이 달라 잘 들림")
        out.append(Candidate(program, score, why))
    return _vary(sorted(out, key=lambda c: -c.score), seed)


def _vary(items: list, seed: str) -> list:
    """1등과 CLOSE점 안의 후보는 seed로 순서를 섞는다 (곡 · 버전마다 다르게, 같으면 같게)"""
    if not items:
        return items
    top = items[0].score
    close = [c for c in items if top - c.score <= CLOSE]
    rest = items[len(close):]
    Random(seed).shuffle(close)
    return close + rest


def _samples(song: SongMap, role: Role, low: int, high: int, library: list | tuple | None, used: set[str], seed: str) -> list[SamplePick]:
    from app.tools.samples import FIT, KIND_KO, STRETCH_MAX, STRETCH_OK  # 늦게 (돌고 도는 import)

    near = _overlapping(song, low, high)
    around = sum(t.brightness for t in near) / len(near) if near else None
    middle = (low + high) // 2
    out: list[SamplePick] = []
    for s in library or []:
        fit = FIT[role].get(s.kind, 0.0)
        if not fit or s.root is None or s.id in used:
            continue
        score = 100 * fit
        why = [f"{KIND_KO[s.kind]} 샘플"]
        stretch = abs(middle - s.root)
        score -= 3 * max(0, stretch - STRETCH_OK) + 6 * max(0, stretch - STRETCH_MAX)
        if stretch <= STRETCH_OK:
            why.append("녹음된 음이 그 높이에 가까움")
        if around is not None and abs(s.brightness - around) >= 0.25:
            score += 5
            why.append("옆 트랙과 빛깔이 다름")
        out.append(SamplePick(s.id, s.name, round(score, 1), why))
    return _vary(sorted(out, key=lambda p: (-p.score, p.name)), seed)


def suggest(song: SongMap, project_id: str, role: Role | None = None, count: int = 3, version: int = 1,
            library: list | tuple | None = None, used_samples: set[str] | None = None) -> list[Slot]:
    if role is not None:
        found = next((n for n in needs(song) if n[0] == role), None)
        slots = [found or (role, _gap_for(song, role) or REGISTER[role], f"{ROLE_KO[role]}로 어울리는 것")]
    else:
        slots = needs(song)[:count]
        if not slots:  # 빈 데가 없으면 색깔을 더하는 쪽 (위 선율 악기를 하나 더)
            slots = [("lead", _gap_for(song, "lead") or REGISTER["lead"], "역할 · 높이가 다 차 있어요. 색깔을 더한다면 위쪽 선율 악기예요")]
    out = []
    for r, (low, high), reason in slots:
        seed = f"{project_id}:{r}:{version}"
        slot = Slot(r, low, high, reason, _candidates(song, r, low, high, seed)[:3])
        slot.samples = _samples(song, r, low, high, library, used_samples or set(), seed)[:2]
        out.append(slot)
    return out


# 생성기가 스스로 소리를 고를 때 같은 높이의 같은 계열을 피하는 역할 (패드 · 베이스는 사용자가 그 악기를 원한 거라 계열을 바꾸지 않는다)
AVOID_TWINS: set[Role] = {"keys", "pluck"}
# 곡마다 다르게 고를 후보 수. 베이스는 스타일마다 정한 소리(옥타브 → 슬랩, 워킹 → 콘트라베이스)가 기능이라 섞지 않는다
CHOICES: dict[Role, int] = {"pad": 3, "keys": 3, "pluck": 3, "lead": 3, "bass": 1}


def choose_program(project, role: Role, head: list[int], flavor: str | None = None) -> int:
    """생성기 소리. 생성기 규칙이 먼저 고른 소리(head[0]) 뒤에 분위기별 후보 묶음을 잇고, 이미 쓴 악기 · 그 높이를 못 내는 악기는
    건너뛰고, 건반 · 플럭은 같은 높이에 같은 계열(예: 피아노 곡의 전자 피아노 반주)을 피한다. 남은 좋은 후보 몇 개 중에서
    곡마다 다르게 고른다 — 곡 읽기만으로는 샘플팩 37곡(모두 피아노 한 트랙)에서 반주가 37곡 모두 같은 소리였다.
    같은 곡이면 늘 같다 (다시 만들기 · 다른 버전은 트랙 소리를 그대로 쓴다).
    flavor: 생성기가 따로 정한 분위기 (반주는 신스 베이스만으로는 전자로 보지 않는다 — 로파이 아르페지오가 톱니파 리드로 나왔다)."""
    from app.arrange.read import read_song  # 생성기가 이 모듈을 불러서 늦게

    song = read_song(project)
    low, high = REGISTER[role]
    used = {t.program for t in song.melodic}
    near = _overlapping(song, low, high)
    order = list(dict.fromkeys([head[0], *POOLS[role][flavor or song.flavor], *head[1:]]))
    playable = [p for p in order if fits(p, low, high)] or order
    free = [p for p in playable if p not in used] or playable
    if role in AVOID_TWINS:
        free = [p for p in free if not any(t.family == p // 8 for t in near)] or free
    picks = free[:CHOICES[role]]
    return picks[Random(f"{project.id}:{role}").randrange(len(picks))]
