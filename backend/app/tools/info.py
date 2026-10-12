"""읽기 도구: get_project_info. 프로젝트를 바꾸지 않는다."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.project import Project, ProjectSummary
from app.tools.base import ToolResult


class ProjectInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def get_project_info(project: Project, args: ProjectInfoArgs | None = None) -> ToolResult:
    info = ProjectSummary.of(project)
    num, den = project.time_signature
    tracks = ", ".join(f"{t.id} {t.name}" + (" (드럼)" if t.is_drum else "") for t in project.tracks)
    summary = (
        f"{round(project.tempo, 1):g} BPM · {num}/{den}박자 · {project.bar_count}마디 · "
        f"트랙 {len(project.tracks)}개 ({tracks})"
    )
    return ToolResult(summary=summary, data=info.model_dump(mode="json"))
