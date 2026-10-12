from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.midi_io.convert import MidiParseError, midi_bytes_to_project, project_to_midi_bytes
from app.models.project import Project, ProjectSummary
from app.store.memory import ProjectNotFound, store

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

