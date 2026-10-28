"""LLM 단독 vs LLM + 분석 엔진: 같은 곡의 조성 · 코드를 세 가지로 읽어 비교한다. python -m eval.harmony_llm

- 엔진만: app/harmony 결과 그대로 (LLM 없음)
- LLM만: 음 목록(트랙 · 마디별 음이름 · 박 · 길이)만 주고 조성 · 마디별 코드를 JSON으로 답하게
- LLM + 엔진: 같은 음 목록에 엔진 결과를 참고로 덧붙여 (엔진이 틀릴 수 있다고 알려 줌)

곡: eval/harmony.py의 생성 곡 일부(정답 = 생성기, 조성 · 코드) + 샘플팩 루프(samples/private, 정답 = 파일 이름, 조성만).
API 키가 필요하다 (backend/.env). Haiku로 곡당 두 번, 100곡 남짓이면 몇 분 · 적은 비용.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app import config
from app.agent.llm import LLMError, LLMUnavailable, make_llm
from app.harmony import analyze
from app.harmony.analyze import SHARP
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Project
from eval.harmony import PRIVATE, PROGRESSIONS, MIREX, Truth, key_from_filename, key_relation, make_song, seventh_class

SYSTEM = (
    "너는 화성 분석가다. MIDI 음 목록을 보고 곡의 조성과 마디별 코드를 판단한다.\n"
    "JSON 하나만 답한다 (설명 없이): {\"key\": \"A minor\", \"chords\": [\"Am7\", \"Dm7\", ...]}\n"
    "- key: \"C major\" · \"F# minor\"처럼 영어로\n"
    "- chords: 1마디부터 마디마다 하나 (그 마디의 첫 박에 울리는 코드). 코드 이름은 Cmaj7 · Am7 · G7 · Bm7b5 · C/E처럼"
)

FLATS = {"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10, "Cb": 11, "Fb": 4, "E#": 5, "B#": 0}


def note_name(pitch: int) -> str:
    return f"{SHARP[pitch % 12]}{pitch // 12 - 1}"


def note_list(p: Project) -> str:
    """LLM에게 줄 음 목록: 트랙마다, 마디마다 "음이름@박/길이".

    트랙 이름은 "트랙 1"로 가린다 — 샘플팩은 트랙 이름이 파일 이름("… MIDI - E Min")이라 정답이 새어 나간다.
    """
    bpb = p.beats_per_bar
    lines = [f"박자 {p.time_signature[0]}/{p.time_signature[1]} · {p.bar_count}마디 (박은 마디 안에서 1부터)"]
    for i, t in enumerate(t for t in p.tracks if not t.is_drum and t.notes):
        lines.append(f"[트랙 {i + 1}]")
        by_bar: dict[int, list[str]] = {}
        for n in sorted(t.notes, key=lambda n: (n.start, n.pitch)):
            bar = int(n.start // bpb)
            by_bar.setdefault(bar, []).append(f"{note_name(n.pitch)}@{n.start - bar * bpb + 1:g}/{n.duration:g}")
        lines += [f"{b + 1}마디: " + " ".join(v) for b, v in sorted(by_bar.items())]
    return "\n".join(lines)


def parse_key(text: str) -> tuple[int, str] | None:
    m = re.match(r"\s*([A-G][#b]?)\s*(major|minor)", text or "", re.IGNORECASE)
    if not m:
        return None
    t = m[1][0].upper() + m[1][1:]
    pc = FLATS.get(t, SHARP.index(t) if t in SHARP else None)
    return (pc, m[2].lower()) if pc is not None else None


def parse_chord(name: str) -> tuple[int, str] | None:
    """LLM이 쓴 코드 이름 → (근음, 엔진 표기의 종류). 흔한 다른 표기(min7 · M7 · Δ · ø · ° · (add9))를 맞춰 준다."""
    m = re.match(r"\s*([A-G][#b]?)([^/\s]*)", name or "")
    if not m:
        return None
    root = FLATS.get(m[1], SHARP.index(m[1]) if m[1] in SHARP else None)
    if root is None:
        return None
    q = m[2].replace("(", "").replace(")", "")
    for a, b in (("min", "m"), ("Maj", "maj"), ("M7", "maj7"), ("M9", "maj9"), ("Δ7", "maj7"), ("Δ", "maj7"),
                 ("ø7", "m7b5"), ("ø", "m7b5"), ("°7", "dim7"), ("°", "dim"), ("-7", "m7"), ("dom", "")):
        q = q.replace(a, b)
    if q == "maj":
        q = ""
    return root, q


@dataclass
class Song:
    name: str
    project: Project
    key: tuple[int, str]
    bars: list[Truth] = field(default_factory=list)  # 마디마다 정답 코드 (샘플팩은 비어 있음 = 조성만 채점)


def songs() -> list[Song]:
    rng = random.Random(1)
    out = []
    for mode, progs in PROGRESSIONS.items():
        for prog_name, prog in progs.items():
            for tonic in (2, 5, 10):  # D · F · Bb — 샵 · 플랫 조를 섞어서
                for style in ("블록", "펼침화음", "멜로디 위"):
                    p, truth = make_song(tonic, mode, prog, style, rng)
                    out.append(Song(f"{SHARP[tonic]} {mode} {prog_name} {style}", p, (tonic, mode), truth))
    for f in sorted(PRIVATE.glob("*.mid")) if PRIVATE.exists() else []:
        k = key_from_filename(f.name)
        if k:
            out.append(Song(f.stem, midi_bytes_to_project(f.read_bytes(), f.stem), k))
    return out


def ask(llm, song: Song, with_engine: bool) -> dict:
    user = note_list(song.project)
    if with_engine:
        user += "\n\n참고 — 분석 엔진의 결과 (엔진도 틀릴 수 있다. 음을 보고 최종 판단한다):\n" + analyze(song.project).text()
    try:
        r = llm.complete([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], [])
    except LLMError as e:
        return {"error": str(e)}
    m = re.search(r"\{.*\}", r.text, re.DOTALL)
    try:
        data = json.loads(m[0]) if m else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data.get("key"):
        return {"error": f"JSON 답 없음 (출력 {r.output_tokens}토큰)", "tokens": r.input_tokens + r.output_tokens}
    return {"key": data.get("key", ""), "chords": data.get("chords", []) if isinstance(data.get("chords"), list) else [],
            "tokens": r.input_tokens + r.output_tokens}


def engine(song: Song) -> dict:
    a = analyze(song.project)
    bpb = song.project.beats_per_bar
    chords = [next((c.name for c in a.chords if c.start <= b * bpb + 0.5 < c.end), "") for b in range(song.project.bar_count)]
    return {"key": a.key.name, "chords": chords, "tokens": 0}


@dataclass
class Tally:
    keys: int = 0
    key_ok: int = 0
    mirex: float = 0.0
    bars: int = 0
    root_ok: int = 0
    seventh_ok: int = 0
    tokens: int = 0
    failed: int = 0

    def add(self, song: Song, ans: dict) -> None:
        if "error" in ans:
            self.failed += 1
        self.tokens += ans.get("tokens", 0)
        got = parse_key(ans.get("key", ""))
        rel = key_relation(got, song.key) if got else "틀림"
        self.keys += 1
        self.key_ok += rel == "정답"
        self.mirex += MIREX[rel]
        chords = ans.get("chords", [])
        for tr in song.bars:  # 생성 곡은 한 마디에 한 코드
            bar = int(tr.start // song.project.beats_per_bar)
            self.bars += 1
            c = parse_chord(chords[bar]) if bar < len(chords) and isinstance(chords[bar], str) else None
            if c and c[0] == tr.root:
                self.root_ok += 1
                self.seventh_ok += seventh_class(c[1]) == seventh_class(tr.quality)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=config.ANTHROPIC_MODEL if config.LLM_PROVIDER == "anthropic" else config.OPENAI_MODEL)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="생성 곡 · 샘플팩에서 앞의 몇 곡씩만 (시험 삼아 돌릴 때)")
    args = ap.parse_args()
    try:
        llm = make_llm(args.model)
    except LLMUnavailable as e:
        sys.exit(str(e))
    # 음 목록을 읽고 따지느라 생각(추론)이 길어진다 — 에이전트 기본 한도(2048)면 답을 쓰기 전에 끊긴다
    llm.MAX_TOKENS = 8000

    all_songs = songs()
    if args.limit:
        all_songs = [s for s in all_songs if s.bars][: args.limit] + [s for s in all_songs if not s.bars][: args.limit]
    jobs = [(s, w) for s in all_songs for w in (False, True)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        answers = list(pool.map(lambda j: ask(llm, *j), jobs))

    arms = {"엔진만": {}, "LLM만": {}, "LLM + 엔진": {}}
    groups = {"생성한 곡": lambda s: bool(s.bars), "샘플팩 루프": lambda s: not s.bars}
    for g in groups:
        for arm in arms:
            arms[arm][g] = Tally()
    misses: list[str] = []
    for (s, w), ans in zip(jobs, answers):
        g = next(g for g, f in groups.items() if f(s))
        arms["LLM + 엔진" if w else "LLM만"][g].add(s, ans)
        if not w:
            arms["엔진만"][g].add(s, engine(s))
        if w and not s.bars:
            e = engine(s)["key"]
            if parse_key(ans.get("key", "")) != parse_key(e):
                misses.append(f"- {s.name.replace('Cymatics - ', '').replace(' MIDI', '')}: 엔진 {e} → LLM + 엔진 {ans.get('key')}")

    print(f"## LLM 단독 vs LLM + 분석 엔진 ({args.model})\n")
    for g in groups:
        t0 = arms["엔진만"][g]
        if not t0.keys:
            continue
        print(f"### {g} {t0.keys}곡\n")
        head = "| | 조성 정답 | MIREX |" + (" 코드 근음 | 코드 7화음 |" if t0.bars else "") + " 토큰(곡당) | 답 못 받음 |"
        print(head + "\n" + "|---" * (head.count("|") - 1) + "|")
        for arm, by_g in arms.items():
            t = by_g[g]
            row = f"| {arm} | {t.key_ok}/{t.keys} | {t.mirex / t.keys:.2f} |"
            if t0.bars:
                row += f" {100 * t.root_ok / t.bars:.0f}% | {100 * t.seventh_ok / t.bars:.0f}% |"
            print(row + f" {t.tokens // t.keys} | {t.failed} |")
        print()
    if misses:
        print("샘플팩에서 LLM + 엔진이 엔진과 다르게 답한 곡:")
        print("\n".join(misses))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
