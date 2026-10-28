"""화성 분석 엔진 평가 (LLM 없이, API 키 필요 없음): python -m eval.harmony

1. 코드 — 정답을 아는 진행을 코드로 만든다 (12개 조 × 장 · 단조 진행 × 보이싱 6가지).
   정답이 생성기에서 나오므로 사람이 단 정답보다 넓고 흔들리지 않는다. 박마다 비교해 근음 · 종류 · 이름이 맞는 비율.
2. 조성 — 위 생성 곡들, 그리고 샘플팩 루프(samples/private, 파일 이름에 정답 키가 있다).
   샘플팩은 공개 저장소에 없어서 있을 때만. 엔진 숫자를 이 곡들에 맞춰 고치지 않는다 (시험지로 남긴다).
   MIREX 방식 점수도 함께: 정답 1 · 5도 관계 0.5 · 나란한조 0.3 · 같은 으뜸음조 0.2 · 그 밖 0.
"""

from __future__ import annotations

import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.harmony import analyze
from app.harmony.analyze import SHARP, family
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Note, Project, Track

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "samples" / "private"

# ---------- 정답을 아는 진행 ----------

# 코드 종류 → 근음에서의 음정 (생성용)
SHAPES = {
    "": [0, 4, 7], "m": [0, 3, 7], "dim": [0, 3, 6], "sus4": [0, 5, 7],
    "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10], "m7b5": [0, 3, 6, 10],
    "9": [0, 4, 7, 10, 14], "maj9": [0, 4, 7, 11, 14], "m9": [0, 3, 7, 10, 14],
}

# (으뜸음에서의 거리, 종류) — 실제 곡에 흔한 진행
PROGRESSIONS = {
    "major": {
        "I–V–vi–IV": [(0, ""), (7, ""), (9, "m"), (5, "")],
        "I–vi–ii–V7": [(0, "maj7"), (9, "m7"), (2, "m7"), (7, "7")],
        "ii9–V9–Imaj9–VI7": [(2, "m9"), (7, "9"), (0, "maj9"), (9, "7")],
        "I–IV–V7sus–V7": [(0, ""), (5, "maj7"), (7, "sus4"), (7, "7")],
    },
    "minor": {
        "i–VI–III–VII": [(0, "m"), (8, ""), (3, ""), (10, "")],
        # i7–iv7–VII7–IIImaj7(Am7–Dm7–G7–Cmaj7)은 C major의 vi–ii–V–I로 듣는 게 자연스러워 정답이 모호 → 쓰지 않음
        "i–VII–VI–V7": [(0, "m"), (10, ""), (8, ""), (7, "7")],
        "i–iiø7–V7–i": [(0, "m"), (2, "m7b5"), (7, "7"), (0, "m")],
        "i9–VImaj7–iv7–V7": [(0, "m9"), (8, "maj7"), (5, "m7"), (7, "7")],
    },
}

SCALE = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10]}


def _close(root: int, shape: list[int], low: int = 55) -> list[int]:
    """근음 기준 음정을 low 위 한 옥타브 안에 모은 건반 보이싱."""
    pcs = sorted({(root + i) % 12 for i in shape})
    return sorted(low + (pc - low) % 12 for pc in pcs)


def _voice(style: str, root: int, quality: str, start: float, bar: float, rng: random.Random) -> dict[str, list[Note]]:
    """한 코드를 보이싱 방식대로 음표로. 반환: 트랙 이름 → 음표."""
    shape = SHAPES[quality]
    bass = [Note(pitch=36 + root % 12, start=start, duration=bar, velocity=90)]
    keys = _close(root, shape)
    if style == "블록":  # 베이스 + 건반 화음
        return {"keys": [Note(pitch=p, start=start, duration=bar) for p in keys], "bass": bass}
    if style == "자리바꿈":  # 베이스 없이 건반만, 3음이 맨 아래 (C/E)
        third = (root + shape[1]) % 12
        inv = _close(root, shape, low=48 + (third - 48) % 12)
        return {"keys": [Note(pitch=p, start=start, duration=bar) for p in inv]}
    if style == "근음 없는 건반":  # 재즈 건반: 근음을 빼고 3 · 5 · 7(· 9), 근음은 베이스만
        rootless = [p for p in keys if p % 12 != root % 12] if len(shape) >= 4 else keys
        return {"keys": [Note(pitch=p, start=start, duration=bar) for p in rootless], "bass": bass}
    if style == "펼침화음":  # 8분음표로 한 음씩
        seq = keys + keys[-2:0:-1]
        notes = [Note(pitch=seq[i % len(seq)], start=start + i * 0.5, duration=0.5) for i in range(int(bar * 2))]
        return {"keys": notes, "bass": bass}
    if style == "멜로디 위":  # 블록 + 위에 음계 멜로디 (박마다, 코드 밖 음이 섞임)
        return {"keys": [Note(pitch=p, start=start, duration=bar) for p in keys], "bass": bass}
    if style == "반 마디씩":  # 블록인데 코드가 반 마디마다 바뀜 (start · bar를 반으로 받아 온다)
        return {"keys": [Note(pitch=p, start=start, duration=bar) for p in keys], "bass": bass}
    raise ValueError(style)


STYLES = ["블록", "자리바꿈", "근음 없는 건반", "펼침화음", "멜로디 위", "반 마디씩"]


@dataclass
class Truth:
    start: float
    end: float
    root: int
    quality: str


def make_song(tonic: int, mode: str, prog: list[tuple[int, str]], style: str, rng: random.Random) -> tuple[Project, list[Truth]]:
    """진행을 두 번 반복한 곡 (루프처럼). 마지막에 으뜸화음 한 마디를 붙이지 않는다 — 샘플팩 루프처럼 끝난다."""
    span = 2.0 if style == "반 마디씩" else 4.0
    tracks: dict[str, list[Note]] = {"keys": [], "bass": [], "lead": []}
    truth: list[Truth] = []
    t = 0.0
    for _ in range(2):
        for interval, quality in prog:
            root = (tonic + interval) % 12
            for name, notes in _voice(style, root, quality, t, span, rng).items():
                tracks[name] += notes
            truth.append(Truth(t, t + span, root, quality))
            t += span
    if style == "멜로디 위":
        # 음계를 따라 3/4은 한 칸씩(나머지는 3도 · 4도 도약) 움직이는 멜로디 (실제 멜로디처럼 순차 진행이 대부분). 박마다 한 음이라 코드 밖 음도 자주 짚는다
        scale = [72 + (tonic + s - 72) % 12 for s in SCALE[mode]]
        scale = sorted(scale + [p + 12 for p in scale])
        i = rng.randrange(7)
        for b in range(int(t)):
            tracks["lead"].append(Note(pitch=scale[i], start=float(b), duration=0.9))
            i = min(max(i + rng.choice([-1, -1, -1, 1, 1, 1, -2, 3]), 0), len(scale) - 1)
    project = Project(
        id="eval", name=f"{SHARP[tonic]} {mode} {style}",
        tracks=[Track(id=k, name=k, program=33 if k == "bass" else 0, notes=v) for k, v in tracks.items() if v],
    )
    return project, truth


# ---------- 채점 ----------

def seventh_class(quality: str) -> str:
    """종류 비교 단위: 3화음 계열 + 7음 (9 · 11 · 13은 7화음으로 묶음). 예: maj9 → maj7, 13 → 7, m9 → m7."""
    fam = family(quality)
    if quality in ("m7b5",):
        return "m7b5"
    if quality.startswith("dim"):
        return quality
    if fam is None:  # sus · 5
        return "7sus4" if quality == "7sus4" else quality
    if quality.startswith("maj") or quality == "m(maj7)":
        return {"maj": "maj7", "min": "m(maj7)"}[fam]
    sevenths = ("7", "9", "11", "13")
    has7 = any(quality.endswith(s) for s in sevenths) and not quality.startswith(("6", "add"))
    if fam == "min":
        return "m7" if has7 else "m"
    return "7" if has7 else ""


# 엔진이 붙이는 종류 → 구성음 (근음에서의 음정). "같은 구성음" 채점용
TONES = {
    **SHAPES, "aug": [0, 4, 8], "dim7": [0, 3, 6, 9], "m(maj7)": [0, 3, 7, 11], "6": [0, 4, 7, 9], "m6": [0, 3, 7, 9],
    "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14], "6/9": [0, 4, 7, 9, 14], "13": [0, 4, 7, 10, 9],
    "maj13": [0, 4, 7, 11, 14, 9], "m11": [0, 3, 7, 10, 14, 5], "7sus4": [0, 5, 7, 10], "sus2": [0, 2, 7], "5": [0, 7],
}


def same_tones(got_root: int, got_q: str, tr: Truth) -> bool:
    """이름은 달라도 같은 음들인가 (Am/C = C6, Bø7/D = Dm6). 엔진 이름의 5음은 실제로 안 울려도 된다."""
    if got_q not in TONES:
        return False
    want = {(tr.root + i) % 12 for i in SHAPES[tr.quality]}
    got = {(got_root + i) % 12 for i in TONES[got_q]}
    return want <= got and got <= want | {(got_root + 7) % 12}


@dataclass
class ChordScore:
    beats: int = 0
    root: int = 0
    triad: int = 0  # 근음 + 장 · 단 · 감
    seventh: int = 0  # 근음 + 7화음까지 (maj7 / 7 / m7 / m7b5 …)
    exact: int = 0  # 근음 + 종류 이름 그대로 (9음까지)
    tones: int = 0  # 7화음 기준으로 맞거나, 이름은 달라도 같은 음들 (Am/C를 C6로)

    def add(self, other: "ChordScore") -> None:
        for f in ("beats", "root", "triad", "seventh", "exact", "tones"):
            setattr(self, f, getattr(self, f) + getattr(other, f))

    def pct(self, f: str) -> str:
        return f"{100 * getattr(self, f) / self.beats:.0f}%" if self.beats else "-"


def score_chords(project: Project, truth: list[Truth]) -> tuple[ChordScore, list[str]]:
    a = analyze(project)
    s = ChordScore()
    misses: list[str] = []
    for tr in truth:
        b = tr.start
        while b < tr.end - 1e-6:
            got = next((c for c in a.chords if c.start <= b + 0.5 < c.end), None)
            s.beats += 1
            ok7 = bool(got and got.root == tr.root and seventh_class(got.quality) == seventh_class(tr.quality))
            if ok7 or (got and got.root is not None and same_tones(got.root, got.quality, tr)):
                s.tones += 1
            if got and got.root == tr.root:
                s.root += 1
                if family(got.quality) == family(tr.quality):
                    s.triad += 1
                if seventh_class(got.quality) == seventh_class(tr.quality):
                    s.seventh += 1
                if got.quality == tr.quality:
                    s.exact += 1
            if b == tr.start and not ok7:
                misses.append(_miss(tr, got))
            b += 1
    return s, misses


INTERVAL = ["1", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7", "7"]


def _miss(tr: Truth, got) -> str:
    """틀린 모양을 조와 상관없이 묶을 수 있게: "m7 → 근음 b3 위 maj" (정답 근음에서 엔진 근음까지의 음정)."""
    want = tr.quality or "maj"
    if got is None or got.root is None:
        return f"{want} → 코드 없음"
    q = got.quality or "maj"
    if got.root == tr.root:
        return f"{want} → {q}"
    return f"{want} → 근음 {INTERVAL[(got.root - tr.root) % 12]} 위 {q}"


# ---------- 조성 ----------

def key_relation(got: tuple[int, str], want: tuple[int, str]) -> str:
    (gt, gm), (wt, wm) = got, want
    if got == want:
        return "정답"
    if gm == wm and (gt - wt) % 12 in (5, 7):
        return "5도 관계"
    if gm != wm and (gt - wt) % 12 == (3 if wm == "minor" else 9):
        return "나란한조"
    if gm != wm and gt == wt:
        return "같은 으뜸음조"
    return "틀림"


MIREX = {"정답": 1.0, "5도 관계": 0.5, "나란한조": 0.3, "같은 으뜸음조": 0.2, "틀림": 0.0}
_FILE_KEY = re.compile(r"- ([A-G])([#b]?) (Maj|Min)\.mid$", re.IGNORECASE)


def key_from_filename(name: str) -> tuple[int, str] | None:
    m = _FILE_KEY.search(name)
    if not m:
        return None
    pc = SHARP.index(m[1]) + (1 if m[2] == "#" else -1 if m[2] == "b" else 0)
    return pc % 12, "major" if m[3].lower() == "maj" else "minor"


def _key_text(k: tuple[int, str]) -> str:
    return f"{SHARP[k[0]]} {k[1]}"


def main() -> None:
    rng = random.Random(0)
    print("## 화성 분석 엔진 평가\n")

    # 1) 코드 + 생성 곡의 조성
    by_style: dict[str, ChordScore] = {st: ChordScore() for st in STYLES}
    total = ChordScore()
    misses: Counter[str] = Counter()
    gen_keys: Counter[str] = Counter()
    key_by_prog: dict[str, Counter[str]] = {}
    for mode, progs in PROGRESSIONS.items():
        for prog_name, prog in progs.items():
            key_by_prog[prog_name] = Counter()
            for tonic in range(12):
                for style in STYLES:
                    project, truth = make_song(tonic, mode, prog, style, rng)
                    s, ms = score_chords(project, truth)
                    by_style[style].add(s)
                    total.add(s)
                    misses.update(f"[{style}] {m}" for m in ms)
                    k = analyze(project).key
                    rel = key_relation((k.tonic, k.mode), (tonic, mode))
                    gen_keys[rel] += 1
                    key_by_prog[prog_name][rel] += 1
    songs = sum(gen_keys.values())
    print(f"### 코드 (생성한 곡 {songs}개 · {total.beats}박)\n")
    print("| 보이싱 | 근음 | 3화음 | 7화음 | 이름 그대로 | 7화음 또는 같은 구성음 |\n|---|---|---|---|---|---|")
    for st, s in [*by_style.items(), ("전체", total)]:
        print(f"| {st} | {s.pct('root')} | {s.pct('triad')} | {s.pct('seventh')} | {s.pct('exact')} | {s.pct('tones')} |")
    print("\n자주 틀린 모양 (7화음 기준 · 코드가 바뀌는 첫 박 · 12개 조를 묶어서):")
    for m, n in misses.most_common(10):
        print(f"- {m} ×{n}")
    print(f"\n### 조성 — 생성한 곡 {songs}개: 정답 {gen_keys['정답']}/{songs}\n")
    print("| 진행 | 정답 | 틀린 종류 |\n|---|---|---|")
    for name, c in key_by_prog.items():
        wrong = " · ".join(f"{r} {n}" for r, n in c.most_common() if r != "정답") or "-"
        print(f"| {name} | {c['정답']}/{sum(c.values())} | {wrong} |")

    # 2) 샘플팩 루프의 조성
    files = sorted(PRIVATE.glob("*.mid")) if PRIVATE.exists() else []
    labeled = [(f, key_from_filename(f.name)) for f in files]
    labeled = [(f, k) for f, k in labeled if k]
    if not labeled:
        print("\n(samples/private에 키가 적힌 MIDI가 없어 샘플팩 조성 평가는 건너뜀)")
        return
    rel: Counter[str] = Counter()
    top3 = 0
    wrong: list[str] = []
    for f, want in labeled:
        a = analyze(midi_bytes_to_project(f.read_bytes(), f.stem))
        got = (a.key.tonic, a.key.mode)
        r = key_relation(got, want)
        rel[r] += 1
        alts = [a.key.name, *a.key.alternatives]
        names = {_key_text(want), _key_text(want).replace("#", "b")}
        top3 += any(_alias(n) in {_alias(x) for x in names} for n in alts)
        if r != "정답":
            wrong.append(f"- {f.stem.replace('Cymatics - ', '').replace(' MIDI', '')}: {a.key.name} ({r})")
    n = len(labeled)
    mirex = sum(MIREX[r] * c for r, c in rel.items()) / n
    print(f"\n### 조성 — 샘플팩 루프 {n}곡 (파일 이름이 정답)\n")
    print(f"정답 {rel['정답']}/{n} · 후보 3개 안 {top3}/{n} · MIREX 점수 {mirex:.2f}")
    print("틀린 종류: " + " · ".join(f"{r} {c}" for r, c in rel.most_common() if r != "정답"))
    print("\n".join(wrong))


_ENHARMONIC = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def _alias(name: str) -> str:
    tonic, mode = name.split(" ")
    return f"{_ENHARMONIC.get(tonic, tonic)} {mode}"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
