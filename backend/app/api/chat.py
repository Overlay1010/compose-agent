"""에이전트 채팅과 미리보기 적용 · 취소."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agent import LLM, ToolStep, get_llm, run_agent
from app.models.project import Project
from app.store.memory import NoPreview, PreviewConflict, ProjectNotFound, store

router = APIRouter(prefix="/projects", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    reply: str
    steps: list[ToolStep]
    preview: Project | None = Field(description="적용 전 미리보기 (이번 명령까지 쌓인 것). 바뀐 게 없으면 None")
    base_version: int = Field(description="미리보기가 출발한 버전")
    model: str
    llm_calls: int
    input_tokens: int
    output_tokens: int


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _check(project_id: str) -> None:
    try:
        store.current(project_id)
    except ProjectNotFound:
        raise _error(404, "project_not_found", "프로젝트를 찾을 수 없습니다.")


@router.post("/{project_id}/chat", response_model=ChatResponse)
def chat(project_id: str, body: ChatRequest, llm: LLM = Depends(get_llm)) -> ChatResponse:
    _check(project_id)
    pending = store.preview(project_id)
    result = run_agent(
        store.working_copy(project_id),
        body.message,
        llm,
        history=store.chat_history(project_id),
        pending=pending.labels if pending else None,
    )

    if result.draft is not None:
        pending = store.set_preview(project_id, result.draft, result.label)

    # 다음 명령에서 "그거 취소하고…"처럼 이어 말할 수 있게 대화를 남긴다 (도구 기록은 요약만)
    done = "; ".join(s.summary for s in result.steps if s.ok)
    store.add_chat(
        project_id,
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": result.reply + (f"\n(실행한 편집: {done})" if done else "")},
    )

    return ChatResponse(
        reply=result.reply,
        steps=result.steps,
        preview=pending.project if pending else None,
        base_version=pending.base_version if pending else store.current(project_id).version,
        model=result.model,
        llm_calls=result.llm_calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


@router.post("/{project_id}/preview/apply", response_model=Project)
def apply_preview(project_id: str) -> Project:
    _check(project_id)
    try:
        project = store.apply_preview(project_id)
    except NoPreview:
        raise _error(409, "no_preview", "적용할 미리보기가 없어요.")
    except PreviewConflict:
        raise _error(409, "preview_conflict", "미리보기를 만든 뒤 버전이 바뀌어서 적용하지 않았어요. 다시 명령해 주세요.")
    store.add_chat(project_id, {"role": "system", "content": f"사용자가 미리보기를 적용했어. 지금은 v{project.version}이야."})
    return project


@router.post("/{project_id}/preview/cancel", status_code=204)
def cancel_preview(project_id: str) -> None:
    _check(project_id)
    if store.preview(project_id) is not None:
        store.cancel_preview(project_id)
        store.add_chat(project_id, {"role": "system", "content": "사용자가 미리보기를 취소했어. 편집은 반영되지 않았어."})
