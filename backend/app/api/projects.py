from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.midi_io.convert import MidiParseError, midi_bytes_to_project, project_to_midi_bytes
from app.models.project import Project, ProjectSummary
from app.store.memory import ProjectNotFound, store
from app.tools.base import ToolError
from app.tools.registry import run_tool

router = APIRouter(prefix="/projects", tags=["projects"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = {".mid", ".midi"}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _get(project_id: str) -> Project:
    try:
        return store.current(project_id)
    except ProjectNotFound:
        raise _error(404, "project_not_found", "프로젝트를 찾을 수 없습니다.")


@router.post("", response_model=Project)
async def upload_midi(file: UploadFile = File(...)) -> Project:
    filename = file.filename or "untitled.mid"
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise _error(400, "invalid_file_type", ".mid 또는 .midi 파일만 올릴 수 있습니다.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise _error(413, "file_too_large", "파일은 5MB 이하만 올릴 수 있습니다.")

    try:
        project = midi_bytes_to_project(data, name=Path(filename).stem)
    except MidiParseError as e:
        raise _error(400, "midi_parse_failed", str(e))

    return store.create(project)


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    return _get(project_id)


@router.get("/{project_id}/summary", response_model=ProjectSummary)
def get_summary(project_id: str) -> ProjectSummary:
    return ProjectSummary.of(_get(project_id))


@router.get("/{project_id}/export")
def export_midi(project_id: str) -> Response:
    project = _get(project_id)
    filename = f"{project.name}_v{project.version}.mid"
    return Response(
        content=project_to_midi_bytes(project),
        media_type="audio/midi",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )



class VersionOut(BaseModel):
    version: int
    label: str
    current: bool


@router.get("/{project_id}/versions", response_model=list[VersionOut])
def list_versions(project_id: str) -> list[VersionOut]:
    current = _get(project_id).version
    return [VersionOut(version=v.version, label=v.label, current=v.version == current) for v in store.versions(project_id)]


@router.post("/{project_id}/versions/{version}/restore", response_model=Project)
def restore_version(project_id: str, version: int) -> Project:
    _get(project_id)
    try:
        return store.restore(project_id, version)
    except KeyError:
        raise _error(404, "version_not_found", f"v{version}을(를) 찾을 수 없어요. 오래된 버전은 최근 50개만 남아요.")


class InstrumentIn(BaseModel):
    program: int = Field(ge=0, le=127)


class InstrumentOut(BaseModel):
    project: Project
    preview: Project | None = None


@router.post("/{project_id}/tracks/{track_id}/instrument", response_model=InstrumentOut)
def set_track_instrument(project_id: str, track_id: str, body: InstrumentIn) -> InstrumentOut:
    """화면에서 악기를 고르면 바로 새 버전으로 올린다 (되돌리기 가능).
    미리보기가 있으면 거기에도 같은 악기를 넣어 미리보기를 잃지 않게 한다."""
    current = _get(project_id)
    args = {"track_ids": [track_id], "program": body.program}
    try:
        result = run_tool(current, "set_instrument", args)
    except ToolError as e:
        raise _error(400, e.code, e.message)
    pending = store.preview(project_id)
    if not result.changed_settings or result.project is None:
        return InstrumentOut(project=current, preview=pending.project if pending else None)
    new = store.add_version(result.project, result.summary)
    if pending is not None:
        pending = store.rebase_preview(project_id, run_tool(pending.project, "set_instrument", args).project or pending.project)
    return InstrumentOut(project=new, preview=pending.project if pending else None)


@router.post("/{project_id}/undo", response_model=Project)
def undo(project_id: str) -> Project:
    _get(project_id)
    return store.undo(project_id)
