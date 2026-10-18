"""대화 한 턴 · 미리보기 적용 · 취소를 저장소와 함께 처리한다.

API(app/api/chat.py)와 평가(eval/)가 같은 코드를 쓰게 하려고 따로 뺐다. 그래야 평가가
실제 서버와 똑같이 "이전 대화 + 쌓인 미리보기" 위에서 명령을 처리한다.
"""

from __future__ import annotations

import time

from app.agent.llm import LLM
from app.agent.loop import AgentResult, OnEvent, run_agent
from app.models.project import Project
from app.store.memory import Preview, ProjectStore


def chat_turn(
    store: ProjectStore,
    project_id: str,
    message: str,
    llm: LLM,
    on_event: OnEvent | None = None,
    selection: dict | None = None,
) -> tuple[AgentResult, Preview | None]:
    """selection: 화면에서 고른 부분 {track_ids, beats, pitches, label} ("여기 한 옥타브 올려줘")."""
    """명령 하나를 처리하고 (에이전트 결과, 지금 쌓여 있는 미리보기)를 돌려준다."""
    pending = store.preview(project_id)
    started = time.perf_counter()
    result = run_agent(
        store.working_copy(project_id),
        message,
        llm,
        history=store.chat_history(project_id),
        pending=pending.labels if pending else None,
        base=store.current(project_id),
        on_event=on_event,
        selection=selection,
    )
    if result.started_over_at is not None:
        # "아니 내려줘"처럼 미리보기를 고친 경우: 쌓인 미리보기를 버리고 이번 결과만 새 미리보기로
        store.cancel_preview(project_id)
        pending = None
    if result.draft is not None:
        pending = store.set_preview(project_id, result.draft, result.label)

    # 다음 명령에서 "그거 취소하고…"처럼 이어 말할 수 있게 대화를 남긴다 (도구 기록은 요약만)
    done = "; ".join(s.summary for s in result.steps if s.ok)
    store.add_chat(
        project_id,
        {"role": "user", "content": message},
        {"role": "assistant", "content": result.reply + (f"\n(실행한 편집: {done})" if done else "")},
    )
    # 새로고침해도 화면에 다시 그릴 수 있게 (실행 단계까지)
    store.add_log(
        project_id,
        {"role": "user", "text": message, **({"selection": selection["label"]} if selection and selection.get("label") else {})},
        {
            "role": "agent",
            "text": result.reply,
            "steps": [s.model_dump() for s in result.steps],
            "meta": f"{result.model} · LLM {result.llm_calls}회 · {time.perf_counter() - started:.1f}초",
            "made_preview": any(s.ok and s.changed for s in result.steps),
        },
    )
    return result, pending


def apply_preview(store: ProjectStore, project_id: str) -> Project:
    """미리보기를 새 버전으로 저장. NoPreview · PreviewConflict는 그대로 올려 보낸다."""
    project = store.apply_preview(project_id)
    store.add_chat(project_id, {"role": "system", "content": f"사용자가 미리보기를 적용했어. 지금은 v{project.version}이야."})
    store.add_log(project_id, note("적용했어요"))
    return project


def cancel_preview(store: ProjectStore, project_id: str) -> None:
    if store.preview(project_id) is not None:
        store.cancel_preview(project_id)
        store.add_chat(project_id, {"role": "system", "content": "사용자가 미리보기를 취소했어. 편집은 반영되지 않았어."})
        store.add_log(project_id, note("미리보기를 취소했어요. 곡은 그대로예요."))


def note(text: str) -> dict:
    """화면 기록의 알림 한 줄 (적용 · 취소 · 되돌리기 · 악기 바꾸기 …)."""
    return {"role": "note", "text": text}
