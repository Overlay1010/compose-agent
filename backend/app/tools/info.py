"""읽기 도구: get_project_info. 프로젝트를 바꾸지 않는다.

곡 구간 · 프레이즈 · 멜로디가 쉬는 곳(곡 읽기, app/arrange/sections.py)도 여기서 알려 준다. 처음에는 늘 보이는 '현재 프로젝트'
설명에 넣었더니, 구간을 말하지 않은 "1~2마디를 16마디까지 반복"에서 에이전트가 "리드는 후렴에서 들어오니 빼겠다"고 혼자 판단했다
(14번 중 2번, 넣기 전에는 8/8). 그래서 구간을 말할 때만 이 도구로 꺼내 보게 했다.
"""

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
    from app.arrange import read_song  # 늦게 (돌고 도는 import)
    from app.arrange.sections import describe

    structure = read_song(project).structure
    if structure and structure.sections:
        if len(structure.sections) == 1:
            summary += f"\n- 구간: 한 구간짜리 루프 (편성 · 세기가 바뀌는 곳이 없음). 프레이즈 {structure.phrase}마디"
        else:
            summary += "\n" + "\n".join(describe(structure, project.beats_per_bar))
    return ToolResult(summary=summary, data=info.model_dump(mode="json"))
