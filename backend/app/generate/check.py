"""만든 음 검사. 생성기는 규칙으로 음을 고르지만, 실수가 섞이면 사용자가 바로 듣고 실망한다.

도구가 결과를 돌려주기 전에 여기서 한 번 더 보고, 걸린 것은 ToolResult.checks에 적는다 (평가는 하나라도 있으면 실패).
- 코드 밖: 그 자리 코드의 구성음이 아님 (패드 · 반주처럼 코드를 그대로 치는 생성기)
- 음계 밖: 곡 조성의 음계에도, 그 자리 코드에도 없음 (멜로디 · 베이스처럼 지나가는 음이 있는 생성기)
- 박 어긋남: 격자(16분음표)나 범위 시작에 맞지 않게 시작
- 음역 밖: 그 악기로 낼 수 없는 높이
- 겹침: 같은 높이 음이 같은 트랙에서 겹쳐 울림
"""

from __future__ import annotations

from app.harmony import ChordSpan
from app.harmony.analyze import KeyInfo
from app.harmony.reharm import INTERVALS
from app.models.project import Note

GRID = 0.25  # 박 (16분음표)
EPS = 1e-3
SCALES = {"major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10, 11)}  # 단조는 화성단음계 이끔음까지

# 악기 종류(General MIDI 8개씩)마다 낼 수 있는 음역. 실제 악기보다 조금 넉넉히 (신스 · 샘플은 더 넓게 난다)
FAMILY_RANGES = [
    (21, 108), (36, 108), (24, 108), (40, 88), (24, 67), (28, 103), (28, 103), (34, 84),
    (44, 92), (55, 108), (36, 96), (36, 96), (24, 108), (36, 96), (36, 96), (24, 108),
]
PROGRAM_RANGES = {40: (55, 103), 41: (48, 91), 42: (36, 76), 43: (28, 67), 52: (40, 84), 53: (40, 84)}  # 바이올린 · 비올라 · 첼로 · 콘트라베이스 · 합창


def playable(program: int) -> tuple[int, int]:
    return PROGRAM_RANGES.get(program, FAMILY_RANGES[program // 8])


def _name(pitch: int) -> str:
    return f"{['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][pitch % 12]}{pitch // 12 - 1}"


def _where(note: Note) -> str:
    return f"{_name(note.pitch)}@{note.start:g}박"


def _tones(chord: ChordSpan) -> set[int]:
    return {(chord.root + i) % 12 for i in INTERVALS.get(chord.quality, (0, 4, 7))} if chord.root is not None else set()


def _chord_at(chords: list[ChordSpan], beat: float) -> ChordSpan | None:
    return next((c for c in chords if c.start - EPS <= beat < c.end - EPS), None)


def check(
    notes: list[Note],
    program: int,
    chords: list[ChordSpan] | None = None,
    key: KeyInfo | None = None,
    starts: tuple[float, ...] = (),
) -> list[str]:
    """notes(한 트랙에 새로 넣은 음)에서 걸린 것들. chords를 주면 코드 밖 검사, key를 주면 음계 밖 검사 (key만이면 코드 음도 허용).
    starts: 격자에 안 맞아도 되는 시작 (화면에서 고른 범위의 시작처럼)."""
    problems: list[str] = []
    low, high = playable(program)
    scale = {(key.tonic + i) % 12 for i in SCALES[key.mode]} if key else None
    for n in notes:
        chord = _chord_at(chords, n.start) if chords is not None else None
        if chords is not None and key is None and (chord is None or n.pitch % 12 not in _tones(chord)):
            problems.append(f"코드 밖 {_where(n)}" + (f" ({chord.name})" if chord else " (코드 없음)"))
        if scale is not None and n.pitch % 12 not in scale and not (chord and n.pitch % 12 in _tones(chord)):
            problems.append(f"음계 밖 {_where(n)} ({key.name})")
        off = n.start / GRID - round(n.start / GRID)
        if abs(off) * GRID > EPS and not any(abs(n.start - s) < EPS for s in starts):
            problems.append(f"박 어긋남 {_where(n)}")
        if not low <= n.pitch <= high:
            problems.append(f"음역 밖 {_where(n)} (이 악기 {_name(low)}~{_name(high)})")
    by_pitch: dict[int, list[Note]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    for same in by_pitch.values():
        same.sort(key=lambda n: n.start)
        problems += [f"겹침 {_where(b)}" for a, b in zip(same, same[1:]) if b.start < a.start + a.duration - EPS]
    return problems
