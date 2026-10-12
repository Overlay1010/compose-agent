"""공통 데이터 형식: Project / Track / Note.

시간 단위는 모두 박(beat)이다. 4/4 박자에서 1마디 = 4박.
도구는 Project를 받아 새 Project를 돌려준다 (원본은 고치지 않는다).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field


class Note(BaseModel):
    pitch: int = Field(ge=0, le=127, description="MIDI 음 번호 (60 = C4)")
    start: float = Field(ge=0, description="시작 박")
    duration: float = Field(gt=0, description="길이(박)")
    velocity: int = Field(default=80, ge=1, le=127)


class Track(BaseModel):
    id: str
    name: str
    program: int = Field(default=0, ge=0, le=127, description="General MIDI 악기 번호")
    is_drum: bool = False
    notes: list[Note] = Field(default_factory=list)

    @property
    def pitch_range(self) -> tuple[int, int] | None:
        if not self.notes:
            return None
        pitches = [n.pitch for n in self.notes]
        return min(pitches), max(pitches)


class Project(BaseModel):
    id: str
    version: int = 1
    name: str = "Untitled"
    tempo: float = Field(default=120.0, gt=0, description="BPM")
    time_signature: tuple[int, int] = (4, 4)
    tracks: list[Track] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="변환 중 단순화한 부분 안내")

    @property
    def beats_per_bar(self) -> float:
        num, den = self.time_signature
        return num * 4 / den

    @property
    def length_beats(self) -> float:
        ends = [n.start + n.duration for t in self.tracks for n in t.notes]
        return max(ends, default=0.0)

    @property
    def bar_count(self) -> int:
        return math.ceil(self.length_beats / self.beats_per_bar) if self.length_beats else 0


class TrackSummary(BaseModel):
    id: str
    name: str
    program: int
    is_drum: bool
    note_count: int
    pitch_range: tuple[int, int] | None


class ProjectSummary(BaseModel):
    """에이전트에게 넘길 요약 (get_project_info 도구의 기반)."""

    id: str
    version: int
    name: str
    tempo: float
    time_signature: tuple[int, int]
    bar_count: int
    tracks: list[TrackSummary]
    warnings: list[str]

    @classmethod
    def of(cls, p: Project) -> "ProjectSummary":
        return cls(
            id=p.id,
            version=p.version,
            name=p.name,
            tempo=p.tempo,
            time_signature=p.time_signature,
            bar_count=p.bar_count,
            tracks=[
                TrackSummary(
                    id=t.id,
                    name=t.name,
                    program=t.program,
                    is_drum=t.is_drum,
                    note_count=len(t.notes),
                    pitch_range=t.pitch_range,
                )
                for t in p.tracks
            ],
            warnings=p.warnings,
        )
