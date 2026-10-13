from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.agent import LLMError, LLMUnavailable
from app.api import chat, projects
from app.tools import ToolError

app = FastAPI(title="Compose Agent", version="0.1.0")


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
