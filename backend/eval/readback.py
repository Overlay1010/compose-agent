"""제안대로 바꾼 곡 다시 읽기 (apply_chords, LLM 없이): python -m eval.readback

곡마다 리하모니 제안 3가지를 apply_progression으로 실제 음에 적용하고, 바꾼 곡을 분석 엔진으로 다시 읽어 박마다 제안 코드와 비교한다.
"제안한 코드로 들리게 바꿨나"를 재는 숫자 (슬래시 베이스 표기는 빼고). 이름이 다른 박은 원인별로 나눈다.
샘플 곡 4개, 그리고 samples/private의 샘플팩 루프(있을 때만).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import app.tools  # noqa: F401 — app.harmony를 먼저 부르면 순환 import
from app.harmony import ChordSpan, analyze
from app.harmony.reharm import INTERVALS, suggest
from app.harmony.voicing import apply_progression
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Project

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "samples" / "private"
sys.path.insert(0, str(ROOT / "scripts"))
import make_samples  # noqa: E402


def _tones(c: ChordSpan) -> set[int]:
    return {(c.root + i) % 12 for i in INTERVALS.get(c.quality, (0, 4, 7))}


def _at(chords: list[ChordSpan], beat: float) -> ChordSpan | None:
    return next((c for c in chords if c.start <= beat + 0.01 < c.end), None)


def why(want: ChordSpan, got: ChordSpan | None) -> str:
    """제안(want)과 다시 읽은 코드(got)의 이름이 다른 까닭."""
    if got is None or got.root is None:
        return "읽은 코드 없음"
    if _tones(got) == _tones(want):
        return "같은 음 다른 이름"
    if got.root == want.root:
        if _tones(got) < _tones(want):
            return "텐션 · 7음 빠짐"
        return "음이 더 있음" if _tones(got) > _tones(want) else "근음 같고 음 다름"
    return "근음 다름"


def score(songs: list[tuple[str, Project]]) -> tuple[int, int, int, int, int, Counter[str]]:
    """(박 수, 이름 같은 박, 구성음 맞는 박, 바뀐 박, 바뀐 박 중 근음 맞는 박, 이름이 다른 까닭)."""
    total = same = tones = changed = root_ok = 0
    causes: Counter[str] = Counter()
    for _, p in songs:
        a, suggestions = suggest(p)
        for s in suggestions:
            back = analyze(apply_progression(p, a.chords, s.chords)[0]).chords
            for b in range(int(s.chords[-1].end)):
                want, got, old = _at(s.chords, b), _at(back, b), _at(a.chords, b)
                if want is None:
                    continue
                total += 1
                ok_root = got is not None and got.root == want.root
                tones += ok_root and len(_tones(got) & _tones(want)) >= 3
                if old is not None and old.name != want.name:
                    changed += 1
                    root_ok += ok_root
                if got is not None and got.name.split("/")[0] == want.name.split("/")[0]:
                    same += 1
                else:
                    causes[why(want, got)] += 1
    return total, same, tones, changed, root_ok, causes


def report(title: str, songs: list[tuple[str, Project]]) -> None:
    total, same, tones, changed, root_ok, causes = score(songs)
    print(f"### {title} ({total}박)\n")
    print(f"이름 {same / total:.1%} · 구성음(근음 같고 3음 이상 겹침) {tones / total:.1%} · 바뀐 박의 근음 {root_ok / max(1, changed):.1%}")
    print("이름이 다른 까닭: " + (" · ".join(f"{k} {n / total:.1%}" for k, n in causes.most_common()) or "-") + "\n")


def main() -> None:
    names = ["fl_style_loose", "lofi_groove", "waltz_3_4"]
    from tests.test_harmony import song
    from tests.test_reharm import AM, C, F, G

    print("## 바꾼 곡 다시 읽기\n")
    report("샘플 곡 4개", [("song", song(C, AM, F, G))] + [(n, midi_bytes_to_project(make_samples.SAMPLES[n + ".mid"]())) for n in names])
    files = sorted(PRIVATE.glob("*.mid")) if PRIVATE.exists() else []
    if not files:
        print("(samples/private에 MIDI가 없어 샘플팩은 건너뜀)")
        return
    report(f"샘플팩 {len(files)}곡", [(f.stem, midi_bytes_to_project(f.read_bytes(), name="loop")) for f in files])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
