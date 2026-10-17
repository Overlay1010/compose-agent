"""에이전트 채팅과 미리보기 적용 · 취소."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from queue import Queue

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent import LLM, LLMError, ToolStep, get_llm, session
from app.models.project import Project
from app.agent.loop import AgentResult
from app.store.memory import NoPreview, PreviewConflict, Preview, ProjectNotFound, store

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


def _response(project_id: str, result: AgentResult, pending: Preview | None) -> ChatResponse:
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


@router.post("/{project_id}/chat", response_model=ChatResponse)
def chat(project_id: str, body: ChatRequest, llm: LLM = Depends(get_llm)) -> ChatResponse:
    _check(project_id)
    result, pending = session.chat_turn(store, project_id, body.message, llm)
    return _response(project_id, result, pending)


@router.post("/{project_id}/chat/stream")
def chat_stream(project_id: str, body: ChatRequest, llm: LLM = Depends(get_llm)) -> StreamingResponse:
    """/chat과 같지만 진행 상황을 Server-Sent Events로 흘려보낸다.

    event: thinking | tool_start | tool_done | done(ChatResponse) | error({code, message})
    """
    _check(project_id)
    events: Queue[tuple[str, dict] | None] = Queue()

    def work() -> None:
        try:
            result, pending = session.chat_turn(store, project_id, body.message, llm, on_event=lambda k, d: events.put((k, d)))
            events.put(("done", _response(project_id, result, pending).model_dump(mode="json")))
        except LLMError as e:
            events.put(("error", {"code": "llm_error", "message": str(e)}))
        except Exception as e:  # 스트림 중간에는 HTTP 오류 코드를 바꿀 수 없어 이벤트로 알린다
            events.put(("error", {"code": "internal_error", "message": f"처리 중 오류가 났어요: {e}"}))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream() -> Iterator[str]:
        while (item := events.get()) is not None:
            kind, data = item
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class SessionOut(BaseModel):
    project: Project
    preview: Project | None
    base_version: int | None
    log: list[dict] = Field(description="화면에 다시 그릴 대화 기록 (role: user · agent · note)")


@router.get("/{project_id}/session", response_model=SessionOut)
def get_session(project_id: str) -> SessionOut:
    """새로고침 · 다시 열기: 현재 버전 · 쌓인 미리보기 · 대화 기록을 한 번에."""
    _check(project_id)
    pending = store.preview(project_id)
    return SessionOut(
        project=store.current(project_id),
        preview=pending.project if pending else None,
        base_version=pending.base_version if pending else None,
        log=store.log(project_id),
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
