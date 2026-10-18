"""프로젝트 버전 저장소.

프로젝트마다 버전 목록을 보관하고, 최근 MAX_VERSIONS개만 남긴다.
메모리에 두고 쓰되, db_path를 주면 바뀔 때마다 SQLite 파일에도 써서(write-through)
서버를 다시 켜도 프로젝트 · 버전 · 미리보기 · 대화가 남는다. 다시 켠 뒤에는 처음 찾는 프로젝트를 파일에서 읽어 온다.
테스트 · 평가는 db_path 없이 메모리만 쓴다.

에이전트 편집은 바로 버전이 되지 않고 미리보기(Preview)로 쌓인다.
사용자가 적용하면 그때 새 버전이 된다. 미리보기가 있는 동안 보낸 명령은 그 위에 이어서 쌓인다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.project import Project

MAX_VERSIONS = 50
MAX_CHAT_MESSAGES = 20  # LLM에 다시 넘길 대화 (최근 것만)
MAX_LOG = 300  # 화면에 다시 그릴 대화 기록

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    project_id TEXT NOT NULL, version INTEGER NOT NULL, label TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (project_id, version)
);
CREATE TABLE IF NOT EXISTS previews (
    project_id TEXT PRIMARY KEY, base_version INTEGER NOT NULL, labels TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    project_id TEXT PRIMARY KEY, messages TEXT NOT NULL, log TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


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
    created_at: str = ""  # ISO 시각 (화면의 "3분 전")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def short(label: str, size: int = 24) -> str:
    """히스토리 · 알림에 넣을 짧은 설명."""
    label = label.strip().rstrip(".")
    return label if len(label) <= size else label[: size - 1] + "…"


@dataclass
class RecentProject:
    id: str
    name: str
    version: int
    updated_at: str


@dataclass
class Preview:
    base_version: int
    project: Project
    labels: list[str] = field(default_factory=list)


class ProjectStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._versions: dict[str, list[Project]] = {}
        self._labels: dict[str, list[str]] = {}
        self._times: dict[str, list[str]] = {}
        self._previews: dict[str, Preview] = {}
        self._chat: dict[str, list[dict[str, Any]]] = {}
        self._log: dict[str, list[dict[str, Any]]] = {}
        self._db: sqlite3.Connection | None = None
        # 채팅 스트리밍은 따로 스레드에서 돌아서, 연결 하나를 잠금으로 나눠 쓴다
        self._lock = threading.RLock()
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.executescript(SCHEMA)
            # 시각 칸이 없던 예전 저장 파일에 칸을 더한다
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(versions)")}
            if "created_at" not in columns:
                with self._db:
                    self._db.execute("ALTER TABLE versions ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")

    # ---------- 파일에 쓰기 · 읽기 ----------

    def _write(self, sql: str, *params: Any) -> None:
        if self._db is None:
            return
        with self._lock, self._db:  # with 연결 = 성공하면 커밋, 실패하면 롤백
            self._db.execute(sql, params)

    def _touch(self, project_id: str) -> None:
        """최근 프로젝트 목록용: 마지막으로 바뀐 시각."""
        name = self._versions[project_id][-1].name
        self._write(
            "INSERT OR REPLACE INTO projects VALUES (?, ?, ?)",
            project_id, name, datetime.now().isoformat(timespec="seconds"),
        )

    def _save_version(self, project: Project, label: str, created_at: str) -> None:
        self._write(
            "INSERT OR REPLACE INTO versions (project_id, version, label, data, created_at) VALUES (?, ?, ?, ?, ?)",
            project.id, project.version, label, project.model_dump_json(), created_at,
        )
        self._write(
            "DELETE FROM versions WHERE project_id = ? AND version <= ?",
            project.id, project.version - MAX_VERSIONS,
        )
        self._touch(project.id)

    def _save_preview(self, project_id: str) -> None:
        pending = self._previews.get(project_id)
        if pending is None:
            self._write("DELETE FROM previews WHERE project_id = ?", project_id)
        else:
            self._write(
                "INSERT OR REPLACE INTO previews VALUES (?, ?, ?, ?)",
                project_id, pending.base_version, json.dumps(pending.labels, ensure_ascii=False),
                pending.project.model_dump_json(),
            )
        self._touch(project_id)

    def _save_chat(self, project_id: str) -> None:
        self._write(
            "INSERT OR REPLACE INTO chats VALUES (?, ?, ?, ?)",
            project_id, json.dumps(self._chat[project_id], ensure_ascii=False),
            json.dumps(self._log[project_id], ensure_ascii=False), datetime.now().isoformat(timespec="seconds"),
        )

    def _load(self, project_id: str) -> bool:
        """파일에서 프로젝트를 읽어 메모리에 올린다. 없으면 False."""
        if self._db is None:
            return False
        with self._lock:
            rows = self._db.execute(
                "SELECT label, data, created_at FROM versions WHERE project_id = ? ORDER BY version", (project_id,)
            ).fetchall()
            if not rows:
                return False
            preview = self._db.execute(
                "SELECT base_version, labels, data FROM previews WHERE project_id = ?", (project_id,)
            ).fetchone()
            chat = self._db.execute("SELECT messages, log FROM chats WHERE project_id = ?", (project_id,)).fetchone()
        self._versions[project_id] = [Project.model_validate_json(data) for _, data, _ in rows]
        self._labels[project_id] = [label for label, _, _ in rows]
        self._times[project_id] = [at for _, _, at in rows]
        if preview:
            base, labels, data = preview
            self._previews[project_id] = Preview(base, Project.model_validate_json(data), json.loads(labels))
        self._chat[project_id] = json.loads(chat[0]) if chat else []
        self._log[project_id] = json.loads(chat[1]) if chat else []
        return True

    def recent(self, limit: int = 12) -> list[RecentProject]:
        """최근에 바뀐 프로젝트 (처음 화면의 "이어서 하기"). 메모리만 쓰면 지금 켜져 있는 동안 만든 것만."""
        if self._db is None:
            return [RecentProject(pid, h[-1].name, h[-1].version, "") for pid, h in reversed(self._versions.items())][:limit]
        with self._lock:
            rows = self._db.execute(
                """SELECT p.project_id, p.name, MAX(v.version), p.updated_at
                   FROM projects p JOIN versions v USING (project_id)
                   GROUP BY p.project_id ORDER BY p.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [RecentProject(pid, name, version, at) for pid, name, version, at in rows]

    # ---------- 버전 ----------

    def create(self, project: Project) -> Project:
        self._versions[project.id] = [project]
        self._labels[project.id] = ["원본 업로드"]
        self._times[project.id] = [now()]
        self._chat[project.id] = []
        self._log[project.id] = []
        self._save_version(project, "원본 업로드", self._times[project.id][0])
        self._save_chat(project.id)
        return project

    def _history(self, project_id: str) -> list[Project]:
        if project_id not in self._versions and not self._load(project_id):
            raise ProjectNotFound(project_id)
        return self._versions[project_id]

    def current(self, project_id: str) -> Project:
        return self._history(project_id)[-1]

    def add_version(self, project: Project, label: str = "") -> Project:
        history = self._history(project.id)
        labels = self._labels[project.id]
        times = self._times[project.id]
        new = project.model_copy(update={"version": history[-1].version + 1})
        history.append(new)
        labels.append(label)
        times.append(now())
        del history[:-MAX_VERSIONS]
        del labels[:-MAX_VERSIONS]
        del times[:-MAX_VERSIONS]
        self._save_version(new, label, times[-1])
        return new

    def versions(self, project_id: str) -> list[VersionInfo]:
        history = self._history(project_id)
        return [
            VersionInfo(p.version, label, at)
            for p, label, at in zip(history, self._labels[project_id], self._times[project_id])
        ]

    def restore(self, project_id: str, version: int) -> Project:
        """예전 버전을 새 버전으로 다시 올린다. 지우지 않으니 되돌린 것도 되돌릴 수 있다."""
        history = self._history(project_id)
        i = next((i for i, p in enumerate(history) if p.version == version), None)
        if i is None:
            raise KeyError(version)
        self._previews.pop(project_id, None)
        self._save_preview(project_id)
        return self.add_version(history[i], f"\"{short(self._labels[project_id][i])}\" 상태로 되돌림")

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
        self._save_preview(project_id)
        return pending

    def apply_preview(self, project_id: str) -> Project:
        pending = self.preview(project_id)
        if pending is None:
            raise NoPreview(project_id)
        if pending.base_version != self.current(project_id).version:
            self._previews.pop(project_id)
            self._save_preview(project_id)
            raise PreviewConflict(project_id)
        del self._previews[project_id]
        self._save_preview(project_id)
        return self.add_version(pending.project, " · ".join(pending.labels))

    def rebase_preview(self, project_id: str, project: Project) -> Preview | None:
        """미리보기를 그대로 둔 채 그 아래 버전만 바뀌었을 때 (예: 화면에서 악기만 바꿈).
        project는 새 현재 버전 위에서 다시 만든 미리보기 상태."""
        pending = self.preview(project_id)
        if pending is not None:
            pending.project = project
            pending.base_version = self.current(project_id).version
            self._save_preview(project_id)
        return pending

    def cancel_preview(self, project_id: str) -> None:
        self.preview(project_id)
        self._previews.pop(project_id, None)
        self._save_preview(project_id)

    # ---------- 대화 ----------

    def chat_history(self, project_id: str) -> list[dict[str, Any]]:
        """LLM에 다시 넘길 대화 (최근 MAX_CHAT_MESSAGES개)."""
        self._history(project_id)
        return list(self._chat[project_id][-MAX_CHAT_MESSAGES:])

    def add_chat(self, project_id: str, *messages: dict[str, Any]) -> None:
        self._history(project_id)
        chat = self._chat[project_id]
        chat.extend(messages)
        del chat[:-MAX_CHAT_MESSAGES]
        self._save_chat(project_id)

    def log(self, project_id: str) -> list[dict[str, Any]]:
        """화면에 다시 그릴 대화 기록 (사용자 말 · 에이전트 답과 실행 단계 · 알림)."""
        self._history(project_id)
        return list(self._log[project_id])

    def add_log(self, project_id: str, *entries: dict[str, Any]) -> None:
        self._history(project_id)
        log = self._log[project_id]
        log.extend(entries)
        del log[:-MAX_LOG]
        self._save_chat(project_id)


def _default_store() -> ProjectStore:
    from app import config

    return ProjectStore(config.DB_PATH)


store = _default_store()
