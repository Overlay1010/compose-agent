"""실제 에이전트에게 샘플팩 루프의 조성을 묻는다 (앱과 같은 run_agent 흐름). python -m eval.harmony_agent

eval.harmony_llm은 엔진 결과를 직접 붙여 준 실험이고, 이쪽은 에이전트가 스스로 analyze_harmony를 불러 답하는지 본다.
샘플팩은 트랙 · 프로젝트 이름에 키가 들어 있어서("… MIDI - E Min") 둘 다 가린다. API 키가 필요하다 (backend/.env).
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from app import config
from app.agent.llm import LLMUnavailable, make_llm
from app.agent.loop import run_agent
from app.harmony import analyze
from app.midi_io.convert import midi_bytes_to_project
from eval.harmony import MIREX, PRIVATE, key_from_filename, key_relation
from eval.harmony_llm import parse_key


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=config.ANTHROPIC_MODEL if config.LLM_PROVIDER == "anthropic" else config.OPENAI_MODEL)
    ap.add_argument("--question", default="이 곡 조성이 뭐야?")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    try:
        llm = make_llm(args.model)
    except LLMUnavailable as e:
        sys.exit(str(e))

    songs = []
    for f in sorted(PRIVATE.glob("*.mid")) if PRIVATE.exists() else []:
        if k := key_from_filename(f.name):
            p = midi_bytes_to_project(f.read_bytes(), "loop")
            for i, t in enumerate(p.tracks):
                t.name = f"Track {i + 1}"
            songs.append((f.stem.replace("Cymatics - ", "").replace(" MIDI", ""), p, k))
    if not songs:
        sys.exit(f"{PRIVATE}에 샘플팩 MIDI가 없어요.")

    def ask(song):
        _, p, _ = song
        r = run_agent(p, args.question, llm, base=p)
        m = re.search(r"([A-G][#b]?)\s*(major|minor)", r.reply)  # 답에서 처음 나온 조성
        return r, parse_key(m[0]) if m else None

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        answers = list(pool.map(ask, songs))

    ok = eng_ok = same = called = 0
    mirex = 0.0
    for (_, p, k), (r, got) in zip(songs, answers):
        rel = key_relation(got, k) if got else "틀림"
        eng = parse_key(analyze(p).key.name)
        ok += rel == "정답"
        eng_ok += key_relation(eng, k) == "정답"
        same += got == eng
        mirex += MIREX[rel]
        called += any(s.name == "analyze_harmony" for s in r.steps)
    n = len(songs)
    print(f"## 에이전트에게 조성 묻기 ({args.model}) · \"{args.question}\"\n")
    print(f"- 정답 {ok}/{n} · MIREX {mirex / n:.2f} (엔진만 {eng_ok}/{n})")
    print(f"- analyze_harmony를 부른 곡 {called}/{n} · 엔진과 같은 조성을 답한 곡 {same}/{n}")
    print(f"- 토큰 (곡당 평균) 입력 {sum(r.input_tokens for r, _ in answers) // n} · 출력 {sum(r.output_tokens for r, _ in answers) // n}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
