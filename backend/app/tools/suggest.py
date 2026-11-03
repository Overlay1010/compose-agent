"""읽기 도구: suggest_instruments — "어떤 악기를 더 넣으면 좋을까?"

곡을 한 번 읽어(app/arrange/read.py) 비어 있는 자리(역할 · 높이 · 소리 성격)를 찾고, 자리마다 어울리는 악기 후보 · 내 샘플을
이유와 함께 돌려준다 (app/arrange/suggest.py). 곡은 바꾸지 않는다 — 고르면 만들기 도구로 깐다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.arrange import read_song
from app.arrange.read import ROLE_KO, note_name
from app.arrange.suggest import HOW, suggest
from app.models.project import Project
from app.tools.base import ToolResult
from app.tools.instrument import display_name
from app.tools.samples import current_library


class SuggestInstrumentsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["bass", "pad", "keys", "pluck", "lead"] | None = Field(
        default=None, description="이 역할 악기만 (\"베이스로 뭐가 어울려?\" = bass). 없으면 곡에서 비어 있는 자리를 찾는다"
    )
    count: int = Field(default=3, ge=1, le=3, description="자리 몇 개까지")
    version: int = Field(default=1, ge=1, le=99, description="\"다른 추천\"이면 + 1 (비슷하게 어울리는 후보의 순서가 바뀐다)")


def suggest_instruments(project: Project, args: SuggestInstrumentsArgs) -> ToolResult:
    library = current_library()
    song = read_song(project, library)
    used = {t.sample.id for t in project.tracks if t.sample}
    slots = suggest(song, project.id, args.role, args.count, args.version, library, used)
    lines = []
    for k, s in enumerate(slots, 1):
        names = " · ".join(f"{display_name(c.program)}({c.program})" for c in s.candidates) or "어울리는 GM 악기 없음"
        mine = f" · 내 샘플: {', '.join(p.name for p in s.samples)}" if s.samples else ""
        lines.append(f"{k}. {ROLE_KO[s.role]} {note_name(s.low)}~{note_name(s.high)} — {s.reason}. 후보: {names}{mine}. 만들기: {HOW[s.role]}")
    return ToolResult(
        summary="\n".join(lines) + f"\n(추천 버전 {args.version})",
        data={
            "song": song.summary(),
            "slots": [
                {
                    "role": s.role, "register": [note_name(s.low), note_name(s.high)], "reason": s.reason, "how": HOW[s.role],
                    "candidates": [{"program": c.program, "name": display_name(c.program), "why": " · ".join(c.why)} for c in s.candidates],
                    "my_samples": [{"name": p.name, "why": " · ".join(p.why)} for p in s.samples],
                }
                for s in slots
            ],
            "version": args.version,
        },
    )
