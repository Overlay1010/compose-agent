"""프로젝트 버전 저장소 (메모리).

프로젝트마다 버전 목록을 보관하고, 최근 MAX_VERSIONS개만 남긴다.
서버를 재시작하면 사라진다. 저장이 필요해지면 SQLite로 옮긴다.
"""

from __future__ import annotations

from app.models.project import Project

MAX_VERSIONS = 50


class ProjectNotFound(KeyError):
    pass


class ProjectStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[Project]] = {}

    def create(self, project: Project) -> Project:
        self._versions[project.id] = [project]
        return project

    def current(self, project_id: str) -> Project:
        try:
            return self._versions[project_id][-1]
        except KeyError as e:
            raise ProjectNotFound(project_id) from e

    def add_version(self, project: Project) -> Project:
        """편집 결과를 새 버전으로 저장한다 (편집 도구 단계에서 사용)."""
        history = self._versions.get(project.id)
        if history is None:
            raise ProjectNotFound(project.id)
        new = project.model_copy(update={"version": history[-1].version + 1})
        history.append(new)
        del history[:-MAX_VERSIONS]
        return new

    def undo(self, project_id: str) -> Project:
        history = self._versions.get(project_id)
        if history is None:
            raise ProjectNotFound(project_id)
        if len(history) > 1:
            history.pop()
        return history[-1]


store = ProjectStore()
