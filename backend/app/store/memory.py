"""프로젝트 버전 저장소 (메모리).

프로젝트마다 버전 목록을 보관하고, 최근 MAX_VERSIONS개만 남긴다.
서버를 재시작하면 사라진다. 저장이 필요해지면 SQLite로 옮긴다.

에이전트 편집은 바로 버전이 되지 않고 미리보기(Preview)로 쌓인다.
사용자가 적용하면 그때 새 버전이 된다. 미리보기가 있는 동안 보낸 명령은 그 위에 이어서 쌓인다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.project import Project

MAX_VERSIONS = 50
MAX_CHAT_MESSAGES = 20  # LLM에 다시 넘길 대화 (최근 것만)


class ProjectNotFound(KeyError):
    pass


class NoPreview(LookupError):
    pass


class PreviewConflict(RuntimeError):
    """미리보기를 만든 뒤 다른 경로로 버전이 바뀌었을 때."""


@dataclass
class VersionInfo:
    version: int
    label: str


@dataclass
class Preview:
    base_version: int
    project: Project
    labels: list[str] = field(default_factory=list)


class ProjectStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[Project]] = {}
        self._labels: dict[str, list[str]] = {}
        self._previews: dict[str, Preview] = {}
        self._chat: dict[str, list[dict[str, Any]]] = {}

    def create(self, project: Project) -> Project:
        self._versions[project.id] = [project]
        self._labels[project.id] = ["원본 업로드"]
        self._chat[project.id] = []
        return project

    def _history(self, project_id: str) -> list[Project]:
        try:
            return self._versions[project_id]
        except KeyError as e:
            raise ProjectNotFound(project_id) from e

    def current(self, project_id: str) -> Project:
        return self._history(project_id)[-1]

    def add_version(self, project: Project, label: str = "") -> Project:
        history = self._history(project.id)
        labels = self._labels[project.id]
        new = project.model_copy(update={"version": history[-1].version + 1})
        history.append(new)
        labels.append(label)
        del history[:-MAX_VERSIONS]
        del labels[:-MAX_VERSIONS]
        return new

    def versions(self, project_id: str) -> list[VersionInfo]:
        history = self._history(project_id)
        return [VersionInfo(p.version, label) for p, label in zip(history, self._labels[project_id])]

    def restore(self, project_id: str, version: int) -> Project:
        """예전 버전을 새 버전으로 다시 올린다. 지우지 않으니 되돌린 것도 되돌릴 수 있다."""
        target = next((p for p in self._history(project_id) if p.version == version), None)
        if target is None:
            raise KeyError(version)
        self._previews.pop(project_id, None)
        return self.add_version(target, f"v{version}(으)로 되돌림")

    def undo(self, project_id: str) -> Project:
        """바로 전 버전으로 되돌린다 (새 버전으로 남음). 버전이 하나뿐이면 그대로."""
        history = self._history(project_id)
        if len(history) < 2:
            return history[-1]
        return self.restore(project_id, history[-2].version)

    # ---------- 미리보기 ----------

    def preview(self, project_id: str) -> Preview | None:
        self._history(project_id)
        return self._previews.get(project_id)

    def working_copy(self, project_id: str) -> Project:
        """다음 명령을 적용할 대상: 미리보기가 있으면 그것, 없으면 현재 버전."""
        pending = self.preview(project_id)
        return pending.project if pending else self.current(project_id)

    def set_preview(self, project_id: str, project: Project, label: str) -> Preview:
        pending = self.preview(project_id)
        if pending is None:
            pending = Preview(base_version=self.current(project_id).version, project=project)
            self._previews[project_id] = pending
        pending.project = project
        pending.labels.append(label)
        return pending

    def apply_preview(self, project_id: str) -> Project:
        pending = self.preview(project_id)
        if pending is None:
            raise NoPreview(project_id)
        if pending.base_version != self.current(project_id).version:
            self._previews.pop(project_id)
            raise PreviewConflict(project_id)
        del self._previews[project_id]
        return self.add_version(pending.project, " · ".join(pending.labels))

    def rebase_preview(self, project_id: str, project: Project) -> Preview | None:
        """미리보기를 그대로 둔 채 그 아래 버전만 바뀌었을 때 (예: 화면에서 악기만 바꿈).
        project는 새 현재 버전 위에서 다시 만든 미리보기 상태."""
        pending = self.preview(project_id)
        if pending is not None:
            pending.project = project
            pending.base_version = self.current(project_id).version
        return pending

    def cancel_preview(self, project_id: str) -> None:
        self.preview(project_id)
        self._previews.pop(project_id, None)

    # ---------- 대화 ----------

    def chat_history(self, project_id: str) -> list[dict[str, Any]]:
        self._history(project_id)
        return list(self._chat[project_id])

    def add_chat(self, project_id: str, *messages: dict[str, Any]) -> None:
        chat = self._chat[project_id]
        chat.extend(messages)
        del chat[:-MAX_CHAT_MESSAGES]


store = ProjectStore()
