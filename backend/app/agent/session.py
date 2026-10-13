"""대화 한 턴 · 미리보기 적용 · 취소를 저장소와 함께 처리한다.

API(app/api/chat.py)와 평가(eval/)가 같은 코드를 쓰게 하려고 따로 뺐다. 그래야 평가가
실제 서버와 똑같이 "이전 대화 + 쌓인 미리보기" 위에서 명령을 처리한다.
"""

from __future__ import annotations

from app.agent.llm import LLM
from app.agent.loop import AgentResult, run_agent
from app.models.project import Project
from app.store.memory import Preview, ProjectStore


def chat_turn(store: ProjectStore, project_id: str, message: str, llm: LLM) -> tuple[AgentResult, Preview | None]:
    """명령 하나를 처리하고 (에이전트 결과, 지금 쌓여 있는 미리보기)를 돌려준다."""
    pending = store.preview(project_id)
    result = run_agent(
        store.working_copy(project_id),
        message,
        llm,
        history=store.chat_history(project_id),
        pending=pending.labels if pending else None,
        base=store.current(project_id),
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
    return result, pending


def apply_preview(store: ProjectStore, project_id: str) -> Project:
    """미리보기를 새 버전으로 저장. NoPreview · PreviewConflict는 그대로 올려 보낸다."""
    project = store.apply_preview(project_id)
    store.add_chat(project_id, {"role": "system", "content": f"사용자가 미리보기를 적용했어. 지금은 v{project.version}이야."})
    return project


def cancel_preview(store: ProjectStore, project_id: str) -> None:
    if store.preview(project_id) is not None:
        store.cancel_preview(project_id)
        store.add_chat(project_id, {"role": "system", "content": "사용자가 미리보기를 취소했어. 편집은 반영되지 않았어."})
