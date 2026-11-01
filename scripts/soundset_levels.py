"""소리 세트별 악기 크기 보정표 만들기: python scripts/soundset_levels.py (ffmpeg 필요, 받는 데 몇 분 걸림)

Musyng Kite · FatBoy는 같은 악기라도 FluidR3보다 크거나 작다 (가운데값 -2 · -4dB, 악기마다 -12 ~ +6dB).
세트를 바꾸면 믹스 밸런스가 달라지지 않게, 악기마다 FluidR3와 같은 크기가 되도록 더할 dB를 재서
frontend/src/audio/levels.ts에 적는다. 잰 값: 두 음(베이스 계열은 C2 · C3, 그 밖은 C3 · C4)의 첫 1초 RMS.
"""

from __future__ import annotations

import array
import json
import math
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://gleitz.github.io/midi-js-soundfonts"
SETS = {"musyng": "MusyngKite", "fatboy": "FatBoy"}
REFERENCE = "FluidR3_GM"
LIMIT = 12.0  # dB. 이보다 크게는 보정하지 않는다 (잘못 잰 값이 소리를 터뜨리지 않게)
OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "audio" / "levels.ts"


def names() -> list[str]:
    with urllib.request.urlopen(f"{BASE}/{REFERENCE}/names.json") as r:
        return json.load(r)


def level(folder: str, name: str, note: str) -> float | None:
    """첫 1초 RMS (0~1). 못 받거나 무음이면 None."""
    try:
        with urllib.request.urlopen(f"{BASE}/{folder}/{name}-mp3/{note}.mp3", timeout=30) as r:
            mp3 = r.read()
    except OSError:
        return None
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-f", "s16le", "-ac", "1", "-ar", "22050", "-"],
                         input=mp3, capture_output=True).stdout
    x = array.array("h", raw)[:22050]
    value = math.sqrt(sum(v * v for v in x) / len(x)) / 32768 if x else 0.0
    return value if value > 1e-4 else None


def offset(folder: str, program: int, name: str) -> float:
    """FluidR3와 같은 크기가 되도록 더할 dB (0.5 단위)."""
    notes = ("C2", "C3") if 32 <= program <= 39 else ("C3", "C4")
    diffs = []
    for note in notes:
        ref, got = level(REFERENCE, name, note), level(folder, name, note)
        if ref and got:
            diffs.append(20 * math.log10(ref / got))
    if not diffs:
        return 0.0
    return round(max(-LIMIT, min(LIMIT, sum(diffs) / len(diffs))) * 2) / 2


def main() -> None:
    gm = names()
    table: dict[str, list[float]] = {}
    with ThreadPoolExecutor(8) as pool:
        for key, folder in SETS.items():
            table[key] = list(pool.map(lambda pn: offset(folder, *pn), enumerate(gm)))
            print(key, "가운데값", sorted(table[key])[64], "dB", file=sys.stderr)
    lines = [
        "// 소리 세트별 악기 크기 보정 (dB, GM 악기 번호 순서). FluidR3와 같은 크기가 되도록 더한다.",
        "// scripts/soundset_levels.py가 만든 파일이라 손으로 고치지 않는다.",
        "export const LEVELS: Record<string, number[]> = {",
    ]
    for key, values in table.items():
        lines.append(f"  {key}: [")
        for i in range(0, 128, 16):
            lines.append("    " + ", ".join(f"{v:g}" for v in values[i:i + 16]) + ",")
        lines.append("  ],")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT} 에 적었어요", file=sys.stderr)


if __name__ == "__main__":
    main()
