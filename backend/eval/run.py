"""에이전트 평가: 정답 있는 명령 30개를 모델별로 돌려 채점한다.

    cd backend
    compose_venv\\Scripts\\python -m eval.run                       # .env의 모델로
    compose_venv\\Scripts\\python -m eval.run --models gpt-6-luna,gpt-5.4-mini

결과는 eval/results/<날짜>_<모델>.json 에 남고, 요약 표를 화면에 찍는다.
실제 API를 부르므로 비용이 든다 (명령 하나에 입력 토큰 약 5,500개).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from statistics import mean, median

from app import config
from app.agent.llm import LLMError, OpenAIChat
from app.agent.loop import run_agent
from app.midi_io.convert import midi_bytes_to_project
from eval.cases import CASES
from eval.spec import Case, score

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


def run_case(llm: OpenAIChat, case: Case) -> dict:
    project = midi_bytes_to_project(make_samples.SAMPLES[f"{case.sample}.mid"](), name=case.sample)
    melodic = {t.id for t in project.tracks if not t.is_drum}
    started = time.perf_counter()
    try:
        r = run_agent(project, case.command, llm)
    except LLMError as e:
        return {"id": case.id, "category": case.category, "command": case.command, "passed": False,
                "tools_ok": False, "reason": f"LLM 오류: {e}", "seconds": time.perf_counter() - started}
    seconds = time.perf_counter() - started
    s = score(case, r.steps, melodic)
    recovered = any(not a.ok and b.ok for a, b in zip(r.steps, r.steps[1:]))
    return {
        "id": case.id, "category": case.category, "command": case.command,
        "passed": s.passed, "tools_ok": s.tools_ok, "reason": s.reason,
        "steps": [st.model_dump() for st in r.steps], "reply": r.reply,
        "seconds": round(seconds, 2), "llm_calls": r.llm_calls,
        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "recovered": recovered,
    }


def evaluate(model: str, workers: int) -> dict:
    llm = OpenAIChat(model, config.OPENAI_API_KEY or "", config.OPENAI_BASE_URL, config.OPENAI_REASONING_EFFORT)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda c: run_case(llm, c), CASES))
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_cat[row["category"]].append(row)
    ok_rows = [r for r in rows if "llm_calls" in r]
    summary = {
        "model": model,
        "date": datetime.now().isoformat(timespec="seconds"),
        "cases": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "tool_choice_ok": sum(r["tools_ok"] for r in rows),
        "median_seconds": round(median(r["seconds"] for r in rows), 2),
        "mean_llm_calls": round(mean(r["llm_calls"] for r in ok_rows), 2) if ok_rows else None,
        "mean_input_tokens": round(mean(r["input_tokens"] for r in ok_rows)) if ok_rows else None,
        "mean_output_tokens": round(mean(r["output_tokens"] for r in ok_rows)) if ok_rows else None,
        "recovered": sum(r.get("recovered", False) for r in rows),
        "by_category": {k: f"{sum(r['passed'] for r in v)}/{len(v)}" for k, v in by_cat.items()},
    }
    return {"summary": summary, "rows": rows}


def print_report(result: dict) -> None:
    s = result["summary"]
    print(f"\n## {s['model']} · {s['passed']}/{s['cases']} 정답")
    print(f"도구 선택 {s['tool_choice_ok']}/{s['cases']} · 응답 시간 중앙값 {s['median_seconds']}초 · "
          f"LLM 호출 평균 {s['mean_llm_calls']}회 · 토큰 평균 {s['mean_input_tokens']}+{s['mean_output_tokens']} · "
          f"오류 보고 스스로 고침 {s['recovered']}건")
    print("분야별: " + " · ".join(f"{k} {v}" for k, v in s["by_category"].items()))
    for r in result["rows"]:
        if not r["passed"]:
            print(f"  ✗ {r['id']} {r['command']} → {r['reason']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=config.OPENAI_MODEL, help="쉼표로 여러 개")
    ap.add_argument("--workers", type=int, default=4, help="동시에 보낼 명령 수")
    args = ap.parse_args()
    if not config.OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY가 없어요. backend/.env를 확인해 주세요.")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        result = evaluate(model, args.workers)
        out = RESULTS / f"{stamp}_{model}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print_report(result)
        print(f"  → {out.relative_to(RESULTS.parent.parent)}")


if __name__ == "__main__":
    main()
