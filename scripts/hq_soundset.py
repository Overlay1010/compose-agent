"""고음질 소리 세트 표 만들기: python scripts/hq_soundset.py (ffmpeg 필요, 받는 데 1~2분)

GM 사운드폰트(FluidR3 등)는 128개 악기를 한 세트로 녹음한 것이라 악기 하나하나가 얇고, 모든 음이 3.13초에서 잘려 있다.
자주 쓰는 악기만 따로 녹음한 샘플로 바꾼다 (없는 악기는 FluidR3 그대로):
- 피아노: Salamander Grand Piano (Alexander Holm, CC BY 3.0) — Tone.js가 올려 둔 것
- 기타 · 베이스 · 현악 · 관악 · 하프 · 오르간 등: tonejs-instruments (Nicholaus Brosowsky, CC BY 3.0 —
  원래 녹음은 VSCO 2 CE · Karoryfer · Freesound · 아이오와 대학)

이 스크립트가 frontend/src/audio/hqset.ts에 적는 것: 악기마다 녹음된 음 목록과, FluidR3와 같은 크기가 되도록 더할 dB
(녹음된 음마다 FluidR3의 같은 음과 첫 1초 RMS를 비교한 가운데값 — 앞 무음을 뺀 뒤. scripts/soundset_levels.py와 같은 잣대).
"""

from __future__ import annotations

import array
import json
import math
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TONEJS_COMMIT = "622c2f1c32c8cfce4158ddc3eb26e518ddef37e5"  # 2022-05-07 — 주소가 바뀌지 않게 커밋에 고정
TONEJS = f"https://cdn.jsdelivr.net/gh/nbrosowsky/tonejs-instruments@{TONEJS_COMMIT}/samples/"
SALAMANDER = "https://tonejs.github.io/audio/salamander/"
FLUID = "https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM/"
OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "audio" / "hqset.ts"
LIMIT = 30.0  # FluidR3 녹음이 원래 작아서(바이올린 첫 1초 -30dB, 이 샘플들은 -10 ~ -20dB) 12dB 한계로는 모자랐다

SHARP = ["C", "Cs", "D", "Ds", "E", "F", "Fs", "G", "Gs", "A", "As", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# GM 악기 번호 → 샘플 (FluidR3 이름은 크기를 맞출 기준)
PROGRAMS = {
    0: "salamander", 1: "salamander", 2: "salamander",  # 그랜드 · 브라이트 · 일렉트릭 그랜드
    13: "xylophone",
    19: "organ",  # 처치 오르간 (파이프 오르간 녹음 — 해먼드 계열 16~18은 FluidR3 그대로)
    20: "harmonium",  # 리드 오르간
    24: "guitar-nylon", 25: "guitar-acoustic", 26: "guitar-electric", 27: "guitar-electric",
    33: "bass-electric", 34: "bass-electric",  # 핑거 · 피크 베이스 (어쿠스틱 베이스 32는 콘트라베이스가 활로 켠 녹음이라 FluidR3)
    40: "violin", 42: "cello", 43: "contrabass", 46: "harp",
    56: "trumpet", 57: "trombone", 58: "tuba", 60: "french-horn",
    65: "saxophone", 66: "saxophone",  # 알토 · 테너
    70: "bassoon", 71: "clarinet", 73: "flute",
}


def name_of(pitch: int, names=SHARP) -> str:
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


def pitch_of(name: str) -> int:
    m = re.fullmatch(r"([A-G]s?)(\d)", name)
    return (int(m.group(2)) + 1) * 12 + SHARP.index(m.group(1))


def tonejs_notes() -> dict[str, list[int]]:
    """Tonejs-Instruments.js의 악기별 음 목록. 음 이름과 파일 이름이 다른 항목은 뺀다 (guitar-nylon G5 → G3 파일)."""
    url = f"https://raw.githubusercontent.com/nbrosowsky/tonejs-instruments/{TONEJS_COMMIT}/Tonejs-Instruments.js"
    with urllib.request.urlopen(url, timeout=30) as r:
        src = r.read().decode("utf-8")
    out = {}
    for m in re.finditer(r"'([a-z-]+)'\s*:\s*\{(.*?)\n\s*\}", src, re.S):
        pairs = re.findall(r"'([A-G]#?\d)'\s*:\s*'([A-Za-z0-9]+)\.", m.group(2))
        notes = sorted({pitch_of(f) for n, f in pairs if f == n.replace("#", "s")})
        if notes:
            out[m.group(1)] = notes
    return out


def salamander_notes() -> list[int]:
    return [p for p in range(21, 109) if p % 3 == 0]  # A0(21)부터 3반음마다: A · C · D# · F# … C8(108)


def decode(url: str) -> array.array | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            mp3 = r.read()
    except OSError:
        return None
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-f", "s16le", "-ac", "1", "-ar", "22050", "-"],
                         input=mp3, capture_output=True).stdout
    return array.array("h", raw)


def level(url: str) -> float | None:
    """앞 무음(최대의 5% 아래)을 뺀 첫 1초 RMS — 브라우저에서도 같은 자리부터 튼다."""
    x = decode(url)
    if not x:
        return None
    peak = max(abs(v) for v in x) or 1
    onset = next((i for i, v in enumerate(x) if abs(v) > peak * 0.05), 0)
    seg = x[max(0, onset - 220):][:22050]
    value = math.sqrt(sum(v * v for v in seg) / len(seg)) / 32768 if seg else 0.0
    return value if value > 1e-4 else None


def url_of(source: str, pitch: int) -> str:
    base = SALAMANDER if source == "salamander" else f"{TONEJS}{source}/"
    return f"{base}{name_of(pitch)}.mp3"


def diff(program: int, source: str, pitch: int, gm: list[str]) -> float | None:
    """이 음에서 FluidR3와 같은 크기가 되도록 더할 dB."""
    ref = level(f"{FLUID}{gm[program]}-mp3/{name_of(pitch, FLAT)}.mp3")
    got = level(url_of(source, pitch))
    return 20 * math.log10(ref / got) if ref and got else None


def offset(program: int, source: str, notes: list[int], gm: list[str], pool: ThreadPoolExecutor) -> float:
    """녹음된 음 전부를 FluidR3의 같은 음과 비교한 가운데값 (0.5 단위).
    처음엔 두 음(C3 · C4)만 쟀는데 음마다 차이가 들쭉날쭉해서(트롬본 -4 ~ -18dB) 콘트라베이스 D2가 FluidR3보다 15dB 작게 나왔다"""
    diffs = sorted(d for d in pool.map(lambda p: diff(program, source, p, gm), notes) if d is not None)
    if not diffs:
        return 0.0
    return round(max(-LIMIT, min(LIMIT, diffs[len(diffs) // 2])) * 2) / 2


def main() -> None:
    with urllib.request.urlopen(f"{FLUID}names.json", timeout=30) as r:
        gm = json.load(r)
    notes = {"salamander": salamander_notes(), **tonejs_notes()}
    missing = {s for s in PROGRAMS.values() if s not in notes}
    if missing:
        sys.exit(f"음 목록이 없는 샘플: {missing}")
    with ThreadPoolExecutor(12) as pool:
        dbs = {p: offset(p, s, notes[s], gm, pool) for p, s in PROGRAMS.items()}
    for program, source in PROGRAMS.items():
        print(f"{program:3} {gm[program]:28} {source:16} {dbs[program]:+5.1f} dB", file=sys.stderr)
    used = sorted(set(PROGRAMS.values()))
    lines = [
        "// 고음질 소리 세트: 악기마다 따로 녹음한 샘플 (없는 악기는 FluidR3). scripts/hq_soundset.py가 만든 파일이라 손으로 고치지 않는다.",
        "// 피아노 Salamander Grand Piano (Alexander Holm, CC BY 3.0) · 그 밖 tonejs-instruments (Nicholaus Brosowsky, CC BY 3.0)",
        "",
        "export const SALAMANDER_URL = '" + SALAMANDER + "'",
        "export const TONEJS_URL = '" + TONEJS + "'",
        "",
        "/** 샘플 이름 → 녹음된 음 (MIDI 번호, 파일 이름은 샵 표기: Cs4.mp3) */",
        "export const HQ_NOTES: Record<string, number[]> = {",
        *[f"  '{s}': [{', '.join(map(str, notes[s]))}]," for s in used],
        "}",
        "",
        "/** GM 악기 번호 → 샘플 이름과 FluidR3 크기에 맞출 dB */",
        "export const HQ_PROGRAMS: Record<number, { source: string; db: number }> = {",
        *[f"  {p}: {{ source: '{s}', db: {dbs[p]:g} }}," for p, s in PROGRAMS.items()],
        "}",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT} 에 적었어요", file=sys.stderr)


if __name__ == "__main__":
    main()
