from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.midi_io.convert import MidiParseError, midi_bytes_to_project, project_to_midi_bytes
from app.models.project import Project, ProjectSummary
from app.agent.prompt import DRUM_NAMES, note_name
from app.agent.session import note
from app.tools.instrument import display_name, kit_name
from app.tools.mix import pan_text
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


class RecentOut(BaseModel):
    id: str
    name: str
    version: int
    updated_at: str


@router.get("", response_model=list[RecentOut])
def recent_projects() -> list[RecentOut]:
    """최근 프로젝트 (처음 화면에서 이어서 하기).

    지금은 혼자 쓰는 로컬 앱이라 모든 프로젝트를 보여 준다. 배포할 때는 사용자별로 나눠야 한다 (로드맵 v1.0).
    """
    return [RecentOut(**vars(r)) for r in store.recent()]


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
        restored = store.restore(project_id, version)
    except KeyError:
        raise _error(404, "version_not_found", f"v{version}을(를) 찾을 수 없어요. 오래된 버전은 최근 50개만 남아요.")
    store.add_log(project_id, note(f"v{version} 상태로 되돌렸어요 (v{restored.version}로 저장)"))
    return restored


class InstrumentIn(BaseModel):
    program: int = Field(ge=0, le=127)


class MixIn(BaseModel):
    volume: int | None = Field(default=None, ge=0, le=127)
    pan: int | None = Field(default=None, ge=-64, le=63)


class TrackChangeOut(BaseModel):
    project: Project
    preview: Project | None = None
    note: str | None = Field(default=None, description="대화에 남길 알림 한 줄 (바뀐 게 없으면 None)")


def _change_text(before: Project, after: Project, track_id: str) -> str:
    """화면에서 바꾼 트랙 설정을 사람 말로 (대화 기록 · 화면 알림에 같은 문장을 쓴다)."""
    old = next(t for t in before.tracks if t.id == track_id)
    new = next(t for t in after.tracks if t.id == track_id)
    if old.notes != new.notes:
        # 소리(레인)별 세기: 바뀐 음의 번호로 소리 이름을 찾고 평균 세기를 비교한다
        changed = {a.pitch for a, b in zip(old.notes, new.notes) if a != b}
        pitch = min(changed) if changed else 0
        avg = lambda t: round(sum(n.velocity for n in t.notes if n.pitch == pitch) / max(1, sum(n.pitch == pitch for n in t.notes)))  # noqa: E731
        name = DRUM_NAMES.get(pitch, note_name(pitch)) if new.is_drum else note_name(pitch)
        return f"{new.name} {name} 세기 {avg(old)} → {avg(new)}"
    if old.program != new.program or old.program_set != new.program_set:
        if new.is_drum:
            return f"{new.name} 드럼 킷을 {kit_name(new.program)}(으)로 바꿨어요"
        return f"{new.name} 악기를 {display_name(new.program)}(으)로 바꿨어요"
    parts = []
    if old.volume != new.volume:
        parts.append(f"볼륨 {old.volume} → {new.volume}")
    if old.pan != new.pan:
        parts.append(f"팬 {pan_text(old.pan)} → {pan_text(new.pan)}")
    return f"{new.name} {' · '.join(parts)}"


def _change_track(project_id: str, tool: str, args: dict) -> TrackChangeOut:
    """화면에서 트랙 설정(악기 · 볼륨 · 팬)을 바꾸면 바로 새 버전으로 올린다 (되돌리기 가능).
    미리보기가 있으면 거기에도 같은 설정을 넣어 미리보기를 잃지 않게 한다."""
    current = _get(project_id)
    try:
        result = run_tool(current, tool, args)
    except ToolError as e:
        raise _error(400, e.code, e.message)
    pending = store.preview(project_id)
    if not (result.changed_settings or result.changed_notes) or result.project is None:
        return TrackChangeOut(project=current, preview=pending.project if pending else None)
    text = f"{_change_text(current, result.project, args['track_ids'][0])} (v{current.version + 1}로 저장)"
    new = store.add_version(result.project, result.summary)
    store.add_log(project_id, note(text))
    if pending is not None:
        pending = store.rebase_preview(project_id, run_tool(pending.project, tool, args).project or pending.project)
    return TrackChangeOut(project=new, preview=pending.project if pending else None, note=text)


@router.post("/{project_id}/tracks/{track_id}/instrument", response_model=TrackChangeOut)
def set_track_instrument(project_id: str, track_id: str, body: InstrumentIn) -> TrackChangeOut:
    return _change_track(project_id, "set_instrument", {"track_ids": [track_id], "program": body.program})


@router.post("/{project_id}/tracks/{track_id}/mix", response_model=TrackChangeOut)
def set_track_mix(project_id: str, track_id: str, body: MixIn) -> TrackChangeOut:
    if body.volume is None and body.pan is None:
        raise _error(400, "invalid_args", "volume이나 pan 중 하나는 있어야 해요.")
    return _change_track(project_id, "set_mix", {"track_ids": [track_id], **body.model_dump(exclude_none=True)})


class VelocityChange(BaseModel):
    index: int = Field(ge=0, description="트랙 안 음의 순서 (base_version 기준)")
    velocity: int = Field(ge=1, le=127)


class VelocitiesIn(BaseModel):
    base_version: int = Field(description="화면이 보고 있던 버전. 그사이 바뀌었으면 고치지 않는다")
    changes: list[VelocityChange] = Field(min_length=1, max_length=5000)


@router.post("/{project_id}/tracks/{track_id}/velocities", response_model=TrackChangeOut)
def set_velocities(project_id: str, track_id: str, body: VelocitiesIn) -> TrackChangeOut:
    """벨로시티 편집창: 음 하나하나의 세기를 직접 바꾼다. 바로 새 버전 (되돌리기 가능).

    음을 순서(index)로 가리키므로, 화면이 본 버전과 지금 버전이 다르면 엉뚱한 음을 고치지 않게 409로 거절한다.
    미리보기가 있으면 음 순서가 미리보기와 어긋날 수 있어 화면에서 편집을 막는다 (여기서도 거절).
    """
    current = _get(project_id)
    if body.base_version != current.version:
        raise _error(409, "version_changed", "그사이 버전이 바뀌었어요. 화면을 다시 불러온 뒤 편집해 주세요.")
    if store.preview(project_id) is not None:
        raise _error(409, "preview_pending", "적용하지 않은 미리보기가 있어요. 적용하거나 취소한 뒤 세기를 편집해 주세요.")
    track = next((t for t in current.tracks if t.id == track_id), None)
    if track is None:
        raise _error(404, "unknown_track", f"없는 트랙이에요: {track_id}")
    if any(c.index >= len(track.notes) for c in body.changes):
        raise _error(400, "invalid_args", f"음 순서가 범위를 벗어나요 (이 트랙은 음 {len(track.notes)}개).")

    notes = list(track.notes)
    changed = 0
    for c in body.changes:
        if notes[c.index].velocity != c.velocity:
            notes[c.index] = notes[c.index].model_copy(update={"velocity": c.velocity})
            changed += 1
    if not changed:
        return TrackChangeOut(project=current, preview=None)
    edited = current.model_copy(
        update={"tracks": [t.model_copy(update={"notes": notes}) if t.id == track_id else t for t in current.tracks]}
    )
    text = f"{track.name} 음 {changed}개의 세기를 직접 바꿨어요"
    new = store.add_version(edited, text)
    text += f" (v{new.version}로 저장)"
    store.add_log(project_id, note(text))
    return TrackChangeOut(project=new, preview=None, note=text)


class LaneIn(BaseModel):
    pitch: int = Field(ge=0, le=127, description="드럼 소리(음 번호)")
    scale: float = Field(ge=0.1, le=4, description="그 소리 음들의 세기에 곱할 값")


@router.post("/{project_id}/tracks/{track_id}/lane", response_model=TrackChangeOut)
def set_lane_level(project_id: str, track_id: str, body: LaneIn) -> TrackChangeOut:
    """드럼 소리(레인)별 크기. 따로 저장하는 값이 아니라 그 소리 음들의 세기를 바꿔서 MIDI에도 그대로 남는다."""
    args = {"track_ids": [track_id], "pitches": [body.pitch], "mode": "scale", "value": body.scale}
    return _change_track(project_id, "adjust_velocity", args)


@router.post("/{project_id}/undo", response_model=Project)
def undo(project_id: str) -> Project:
    _get(project_id)
    history = store.versions(project_id)
    restored = store.undo(project_id)
    if len(history) >= 2:  # 버전이 하나뿐이면 되돌릴 게 없음
        store.add_log(project_id, note(f"v{history[-2].version} 상태로 되돌렸어요 (v{restored.version}로 저장)"))
    return restored
