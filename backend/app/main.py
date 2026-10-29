import importlib
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app import config
from app.agent import LLMError, LLMUnavailable
from app.api import audio, chat, projects
from app.tools import ToolError


@asynccontextmanager
async def lifespan(_: FastAPI):
    # LLM SDK는 불러오는 데만 10초 넘게 걸린다 (anthropic: 쓰지 않는 타입 모듈까지 한꺼번에 읽음).
    # 서버가 켜질 때 뒤에서 미리 불러 두어 첫 명령이 그 시간을 기다리지 않게 한다
    sdk = "anthropic" if config.LLM_PROVIDER == "anthropic" else "openai"
    threading.Thread(target=importlib.import_module, args=(sdk,), daemon=True).start()
    yield


app = FastAPI(title="Compose Agent", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def error_format(_: Request, exc: HTTPException) -> JSONResponse:
    """오류 응답을 {"error": {"code", "message"}} 형식으로 통일한다."""
    detail = exc.detail
    if not isinstance(detail, dict):
        detail = {"code": "error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(ToolError)
async def tool_error_format(_: Request, exc: ToolError) -> JSONResponse:
    """편집 도구 오류(없는 트랙, 범위 초과, 잘못된 인자)도 같은 형식으로."""
    return JSONResponse(status_code=400, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(LLMUnavailable)
async def llm_unavailable_format(_: Request, exc: LLMUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": {"code": "llm_unavailable", "message": str(exc)}})


@app.exception_handler(LLMError)
async def llm_error_format(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"error": {"code": "llm_error", "message": str(exc)}})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(projects.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(audio.router, prefix="/api/v1")
