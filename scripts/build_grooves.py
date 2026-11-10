"""Groove MIDI Dataset에서 드럼 루프를 골라 backend/app/generate/grooves.json으로 만든다.

실제 드러머 연주에서 2 · 4마디 루프를 잘라, 우리 스타일(록 · 붐뱁 · 로파이 · 팝 · 펑크 · 소울 · 재즈 · 라틴)마다
서로 다른 연주를 고른다. 위치는 격자에 맞추지 않고 연주 그대로 둔다 (사람의 밀고 당김).

    backend\\compose_venv\\Scripts\\python scripts\\build_grooves.py <압축을 푼 groove 폴더>

데이터: Groove MIDI Dataset (Google LLC, Magenta) — https://magenta.tensorflow.org/datasets/groove
라이선스: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). 루프를 잘라 고르고 드럼 번호를 GM으로 바꿨다.
받기: https://storage.googleapis.com/magentadata/datasets/groove/groove-v1.0.0-midionly.zip
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import mido

OUT = Path(__file__).resolve().parent.parent / "backend" / "app" / "generate" / "grooves.json"

# Groove MIDI(Roland TD-11) 번호 → GM. GM에 없는 22 · 26 · 58, 소리가 다른 52 · 55 · 57은 옮긴다
LANES = {
    36: 36, 38: 38, 40: 38, 37: 37,  # 킥 · 스네어(림샷은 스네어로) · 사이드 스틱
    42: 42, 22: 42, 46: 46, 26: 46, 44: 44,  # 닫힌 햇(보우 · 엣지) · 열린 햇 · 페달 햇
    48: 48, 50: 50, 45: 45, 47: 47, 43: 43, 58: 43,  # 탐
    49: 49, 55: 49, 57: 49, 52: 49,  # 크래시
    51: 51, 59: 51, 53: 53,  # 라이드 · 라이드 벨
}
KICK, SNARES, HATS, RIDES = {36}, {37, 38}, {42, 46}, {51, 53}
TOMS, CRASH = {43, 45, 47, 48, 50}, {49}
BACKBEAT = {"rock", "pop", "funk", "soul", "hiphop"}  # 2 · 4박 스네어가 기본인 장르 (마디선이 어긋난 파일 거르기)
PER_STYLE = 36  # 스타일마다 루프 수
PER_FILE = 2  # 한 연주에서 가져갈 루프 수 (여러 연주가 섞이게)
GHOST = 45  # 이보다 약하면 고스트 노트 (패턴 비교에서 뺀다)


def styles_of(primary: str, bpm: int) -> list[str]:
    """Groove MIDI 장르 → 우리 스타일들 (하나가 여럿에 들어갈 수 있다). 로파이는 이름이 없어 느린 힙합 · 소울 · 펑크로."""
    out = []
    if primary == "rock":
        out.append("rock")
        if 90 <= bpm <= 130:
            out.append("pop")
    if primary == "pop":
        out.append("pop")
    if primary == "hiphop":
        if bpm <= 86:
            out.append("lofi")
        if 80 <= bpm <= 100:
            out.append("boombap")
    if primary == "soul":
        out.append("soul")
        if bpm <= 86:
            out.append("lofi")
        if 90 <= bpm <= 130:
            out.append("pop")
    if primary == "funk":
        out.append("funk")
        if bpm <= 86:
            out.append("lofi")
    if primary == "jazz":
        out.append("jazz")
    if primary in ("latin", "afrocuban"):
        out.append("latin")
    return out


def read_hits(path: Path) -> list[tuple[float, int, int]]:
    """[(박, GM 레인, 세기)]. 파일마다 480틱 = 1박."""
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat
    hits, tick = [], 0
    for msg in mido.merge_tracks(mid.tracks):
        tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.note in LANES:
            hits.append((tick / tpb, LANES[msg.note], msg.velocity))
    return sorted(hits)


def bar_of(beat: float) -> tuple[int, int]:
    """(마디, 16분 칸) — 가장 가까운 16분 칸으로 (조금 일찍 친 첫 박도 그 마디에)."""
    step = round(beat * 4)
    return step // 16, step % 16


def shape(bar_hits: list[tuple[float, int, int]]) -> set[tuple[str, int]]:
    """패턴 비교용: 고스트를 뺀 (레인 묶음, 16분 칸)."""
    out = set()
    for beat, lane, vel in bar_hits:
        if vel < GHOST:
            continue
        group = "k" if lane in KICK else "s" if lane in SNARES else "h" if lane in HATS else "r" if lane in RIDES else None
        if group:
            out.add((group, bar_of(beat)[1]))
    return out


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def features(bars: list[list[tuple[float, int, int]]], start_bar: int) -> dict:
    hits = [h for b in bars for h in b]
    n = len(bars)
    time = [h for h in hits if h[1] in HATS | RIDES]
    ks = [h for h in hits if (h[1] in KICK or h[1] in SNARES) and h[2] >= GHOST]
    off = [h for h in ks if bar_of(h[0])[1] % 4 != 0]
    fracs = sorted((h[0] % 1) for h in time if 0.4 <= h[0] % 1 <= 0.8)
    swing = round(fracs[len(fracs) // 2] * 100) if len(fracs) >= 8 else 50
    snares = [h for h in hits if h[1] in SNARES]
    return {
        "hits_per_bar": round(len(hits) / n, 1),
        "time_per_bar": round(len(time) / n, 1),  # 햇 · 라이드 (4 = 4분, 8 = 8분, 16 = 16분)
        "syncopation": round(len(off) / len(ks), 2) if ks else 0.0,
        "swing": max(50, min(75, swing)),
        "ghosts": round(sum(h[2] < GHOST for h in snares) / len(snares), 2) if snares else 0.0,
        "open_hat": sum(h[1] == 46 for h in hits),
        "ride": len([h for h in time if h[1] in RIDES]) > len([h for h in time if h[1] in HATS]),
        "energy": round(sum(h[2] for h in ks) / len(ks)) if ks else 0,
    }


def rel(bar_hits: list[tuple[float, int, int]], origin_bar: int) -> list[list]:
    return [[round(b - origin_bar * 4, 3), lane, vel] for b, lane, vel in bar_hits]


def windows(row: dict, root: Path) -> list[dict]:
    bpm = int(row["bpm"])
    primary = row["style"].split("/")[0]
    styles = styles_of(primary, bpm)
    if not styles:
        return []
    hits = read_hits(root / row["midi_filename"])
    if not hits:
        return []
    nbars = bar_of(hits[-1][0])[0] + 1
    bars: list[list[tuple[float, int, int]]] = [[] for _ in range(nbars)]
    for h in hits:
        bars[bar_of(h[0])[0]].append(h)
    snare_main = [h for h in hits if h[1] in SNARES and h[2] >= 60]
    if primary in BACKBEAT and snare_main:
        back = sum(bar_of(h[0])[1] in (3, 4, 5, 11, 12, 13) for h in snare_main) / len(snare_main)
        if back < 0.5:  # 2 · 4박에 스네어가 반도 없으면 마디선이 어긋난 연주로 본다
            return []
    snare_counts = sorted(sum(h[1] in SNARES for h in b) for b in bars)
    snare_med = snare_counts[len(snare_counts) // 2] if snare_counts else 0

    def is_fill(b: list) -> bool:
        toms = sum(h[1] in TOMS for h in b)
        snares = sum(h[1] in SNARES and h[2] >= GHOST for h in b)
        return toms >= 2 or snares >= max(6, 2 * snare_med + 1)

    def plain(i: int) -> bool:
        b = bars[i]
        if len(b) < 6 or is_fill(b) or any(h[1] in TOMS for h in b):
            return False
        return not any(h[1] in CRASH and bar_of(h[0])[1] != 0 for h in b)  # 크래시는 첫 박만

    fills = [i for i in range(nbars) if is_fill(bars[i]) and len(bars[i]) >= 6]
    threshold = 0.35 if primary in ("jazz", "latin", "afrocuban") else 0.5
    cands = []
    for size in (4, 2):
        for b in range(0, nbars - size + 1):
            if not all(plain(i) for i in range(b, b + size)):
                continue
            if not any(bar_of(h[0])[1] == 0 for h in bars[b]):  # 첫 박에 치는 음이 있어야 루프 시작으로 들린다
                continue
            shapes = [shape(bars[i]) for i in range(b, b + size)]
            pairs = [(0, 2), (1, 3)] if size == 4 else [(0, 1)]
            sim = sum(jaccard(shapes[x], shapes[y]) for x, y in pairs) / len(pairs)
            if sim < threshold:
                continue
            cands.append((sim + (0.1 if size == 4 else 0), b, size, shapes))
        if cands:
            break  # 4마디가 있으면 2마디는 보지 않는다
    picked, used = [], set()
    for score, b, size, shapes in sorted(cands, key=lambda c: -c[0]):
        if any(i in used for i in range(b, b + size)):
            continue
        used.update(range(b, b + size))
        body = [h for i in range(b, b + size) for h in bars[i] if not (h[1] in CRASH)]  # 첫 박 크래시는 뺀다 (필인 뒤에 따로 넣음)
        after = b + size
        fill_bar = after if after in fills else min(fills, key=lambda f: abs(f - after)) if fills else None
        fill = rel([h for h in bars[fill_bar] if h[1] not in CRASH], fill_bar) if fill_bar is not None else None
        session = row["session"].split("/")[-1]
        picked.append({
            "id": f"{row['drummer']}-{session}-{row['id'].split('/')[-1]}-b{b + 1}",
            "styles": styles,
            "label": row["style"],
            "bpm": bpm,
            "drummer": row["drummer"],
            "bars": size,
            "score": round(score, 3),
            "shape": sorted(s for sh in shapes for s in sh),
            "features": features([bars[i] for i in range(b, b + size)], b),
            "hits": rel(body, b),
            "fill": fill,
        })
        if len(picked) >= PER_FILE:
            break
    return picked


def choose(pool: list[dict], style: str) -> list[dict]:
    """점수 순으로, 이미 고른 것과 너무 비슷한 루프 · 한 드러머가 너무 많은 것은 건너뛴다."""
    out: list[dict] = []
    drummers: Counter = Counter()
    for g in sorted(pool, key=lambda g: (-g["score"], g["id"])):
        if drummers[g["drummer"]] >= max(6, math.ceil(PER_STYLE * 0.4)):
            continue
        shape = set(map(tuple, g["shape"]))
        if any(jaccard(shape, set(map(tuple, o["shape"]))) > 0.85 for o in out):
            continue
        out.append(g)
        drummers[g["drummer"]] += 1
        if len(out) >= PER_STYLE:
            break
    return out


def main() -> None:
    root = Path(sys.argv[1])
    rows = list(csv.DictReader(open(root / "info.csv", encoding="utf-8")))
    rows = [r for r in rows if r["beat_type"] == "beat" and r["time_signature"] == "4-4"]
    every = [w for r in rows for w in windows(r, root)]
    chosen: dict[str, dict] = {}
    counts = {}
    for style in ("rock", "boombap", "lofi", "pop", "funk", "soul", "jazz", "latin"):
        picked = choose([g for g in every if style in g["styles"]], style)
        counts[style] = len(picked)
        for g in picked:
            chosen.setdefault(g["id"], g)
    grooves = []
    for g in sorted(chosen.values(), key=lambda g: g["id"]):
        g = {k: v for k, v in g.items() if k not in ("score", "shape")}
        grooves.append(g)
    data = {
        "source": "Groove MIDI Dataset (Google LLC, Magenta) — https://magenta.tensorflow.org/datasets/groove",
        "license": "CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/",
        "changes": "2 · 4마디 루프를 잘라 고르고, 드럼 번호를 General MIDI로 바꿨다 (scripts/build_grooves.py)",
        "citation": "Jon Gillick, Adam Roberts, Jesse Engel, Douglas Eck, David Bamman. "
        "Learning to Groove with Inverse Sequence Transformations. ICML 2019.",
        "grooves": grooves,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(grooves)} grooves, {OUT.stat().st_size / 1024:.0f} KB ->", OUT)
    print(counts)
    print(Counter(g["drummer"] for g in grooves))


if __name__ == "__main__":
    main()
