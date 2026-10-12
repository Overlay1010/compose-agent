from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import projects

app = FastAPI(title="Compose Agent", version="0.1.0")


@app.exception_handler(HTTPException)
async def error_format(_: Request, exc: HTTPException) -> JSONResponse:
    """오류 응답을 {"error": {"code", "message"}} 형식으로 통일한다."""
    detail = exc.detail
    if not isinstance(detail, dict):
        detail = {"code": "error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(projects.router, prefix="/api/v1")
