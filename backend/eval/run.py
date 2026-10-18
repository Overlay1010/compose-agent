"""에이전트 평가: 정답 있는 명령 30개 + 이어지는 대화 · 스스로 고치기 9개를 모델별로 돌려 채점한다.

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
from app.agent import session
from app.agent.llm import LLMError, OpenAIChat
from app.agent.loop import ToolStep, run_agent
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Project
from app.store.memory import NoPreview, PreviewConflict, ProjectStore
from app.tools import run_tool
from eval.cases import CASES
from eval.conversations import APPLY, CANCEL, CONVERSATIONS, Conversation
from eval.spec import Case, score

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


def run_case(llm: OpenAIChat, case: Case) -> dict:
    project = midi_bytes_to_project(make_samples.SAMPLES[f"{case.sample}.mid"](), name=case.sample)
    melodic = {t.id for t in project.tracks if not t.is_drum}
    started = time.perf_counter()
    try:
        r = run_agent(project, case.command, llm, base=project, selection=case.selection)  # 서버와 같게 start_over를 준다
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


def notes_of(project: Project) -> dict[str, list[tuple]]:
    """트랙별 음 목록 (순서 무관 비교용)."""
    return {t.id: sorted((n.pitch, round(n.start, 3), round(n.duration, 3), n.velocity) for n in t.notes) for t in project.tracks}


def expected_state(base: Project, calls: tuple[tuple[str, dict], ...]) -> Project:
    for tool, args in calls:
        base = run_tool(base, tool, args).project or base
    return base


def run_conversation(llm: OpenAIChat, conv: Conversation) -> dict:
    """여러 턴을 실제 서버와 같은 흐름으로 돌리고 마지막 상태를 정답과 비교한다."""
    store = ProjectStore()
    original = store.create(midi_bytes_to_project(make_samples.SAMPLES[f"{conv.sample}.mid"](), name=conv.sample))
    pid = original.id
    started = time.perf_counter()
    steps: list[ToolStep] = []
    replies: list[str] = []
    calls = tokens_in = tokens_out = 0
    before_last = original
    try:
        for i, turn in enumerate(conv.turns):
            if turn == APPLY:
                session.apply_preview(store, pid)
                continue
            if turn == CANCEL:
                session.cancel_preview(store, pid)
                continue
            if i == len(conv.turns) - 1:
                before_last = store.working_copy(pid)
            result, _ = session.chat_turn(store, pid, turn, llm)
            steps += result.steps
            replies.append(result.reply)
            calls += result.llm_calls
            tokens_in += result.input_tokens
            tokens_out += result.output_tokens
    except (LLMError, NoPreview, PreviewConflict) as e:
        return {"id": conv.id, "category": conv.category, "command": conv.command, "passed": False,
                "tools_ok": False, "reason": f"{type(e).__name__}: {e}", "seconds": time.perf_counter() - started}

    final = store.working_copy(pid)
    want = expected_state(original if conv.base == "original" else before_last, conv.expect)
    passed = notes_of(final) == notes_of(want)
    if passed:
        reason = "정답 (마지막 상태가 같음)"
    else:
        diff = [tid for tid, notes in notes_of(final).items() if notes != notes_of(want).get(tid)]
        reason = "마지막 상태가 다름: " + ", ".join(diff) + " · 실행: " + "; ".join(
            f"{s.name}{s.args}{'' if s.ok else '(실패)'}" for s in steps)
    return {
        "id": conv.id, "category": conv.category, "command": conv.command,
        "passed": passed, "tools_ok": passed, "reason": reason,
        "steps": [st.model_dump() for st in steps], "reply": " / ".join(replies),
        "seconds": round(time.perf_counter() - started, 2), "llm_calls": calls,
        "input_tokens": round(tokens_in / max(1, len(replies))), "output_tokens": round(tokens_out / max(1, len(replies))),
        "recovered": any(not a.ok and b.ok for a, b in zip(steps, steps[1:])),
    }


def evaluate(model: str, workers: int) -> dict:
    llm = OpenAIChat(model, config.OPENAI_API_KEY or "", config.OPENAI_BASE_URL, config.OPENAI_REASONING_EFFORT)
    jobs = [lambda c=c: run_case(llm, c) for c in CASES] + [lambda c=c: run_conversation(llm, c) for c in CONVERSATIONS]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda job: job(), jobs))
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
    ap.add_argument("--repeat", type=int, default=1, help="모델마다 몇 번 돌릴지 (LLM은 매번 답이 조금씩 달라서 3번 이상 권장)")
    args = ap.parse_args()
    if not config.OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY가 없어요. backend/.env를 확인해 주세요.")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        runs = []
        for i in range(args.repeat):
            result = evaluate(model, args.workers)
            suffix = f"_r{i + 1}" if args.repeat > 1 else ""
            out = RESULTS / f"{stamp}_{model}{suffix}.json"
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            runs.append(result)
            if args.repeat == 1:
                print_report(result)
                print(f"  → {out.relative_to(RESULTS.parent.parent)}")
        if args.repeat > 1:
            print_repeat_report(model, runs)


def print_repeat_report(model: str, runs: list[dict]) -> None:
    """여러 번 돌린 결과: 평균 · 범위, 그리고 회차마다 결과가 달라진 (불안정한) 명령."""
    scores = [r["summary"]["passed"] for r in runs]
    n = runs[0]["summary"]["cases"]
    secs = [r["summary"]["median_seconds"] for r in runs]
    print(f"\n## {model} · {len(runs)}회 · 평균 {mean(scores):.1f}/{n} (최저 {min(scores)} · 최고 {max(scores)})")
    print(f"회차별 {' · '.join(map(str, scores))} · 응답 시간 중앙값 평균 {mean(secs):.2f}초")
    per_case: dict[str, list[bool]] = defaultdict(list)
    commands: dict[str, str] = {}
    reasons: dict[str, list[str]] = defaultdict(list)
    for r in runs:
        for row in r["rows"]:
            per_case[row["id"]].append(row["passed"])
            commands[row["id"]] = row["command"]
            if not row["passed"]:
                reasons[row["id"]].append(row["reason"])
    shaky = {k: v for k, v in per_case.items() if not all(v)}
    if not shaky:
        print("  모든 명령이 매번 정답")
    for case_id, results in sorted(shaky.items()):
        print(f"  {'✗' if not any(results) else '△'} {case_id} {commands[case_id]} · {sum(results)}/{len(results)}회 정답 → {reasons[case_id][0]}")


if __name__ == "__main__":
    main()
