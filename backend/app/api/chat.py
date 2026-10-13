"""에이전트 채팅과 미리보기 적용 · 취소."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agent import LLM, ToolStep, get_llm, session
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
    result, pending = session.chat_turn(store, project_id, body.message, llm)
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
        return session.apply_preview(store, project_id)
    except NoPreview:
        raise _error(409, "no_preview", "적용할 미리보기가 없어요.")
    except PreviewConflict:
        raise _error(409, "preview_conflict", "미리보기를 만든 뒤 버전이 바뀌어서 적용하지 않았어요. 다시 명령해 주세요.")


@router.post("/{project_id}/preview/cancel", status_code=204)
def cancel_preview(project_id: str) -> None:
    _check(project_id)
    session.cancel_preview(store, project_id)
