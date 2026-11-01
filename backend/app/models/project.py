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


class SampleRef(BaseModel):
    """사용자가 넣은 샘플(원샷) 하나. 소리 파일은 그 사람 브라우저에만 있고, 여기에는 이름표만 남긴다."""

    id: str = Field(min_length=1, max_length=64, description="파일 내용으로 만든 id (같은 파일이면 같은 id)")
    name: str = Field(max_length=120, description="파일 이름 (확장자 뺀 것)")


class AudioClip(BaseModel):
    """오디오 트랙의 루프 하나: 내 샘플(루프 파일)을 start ~ end 박에 되풀이한다. 곡 템포에 맞춰 재생 속도를 바꾼다."""

    sample: SampleRef
    bpm: float = Field(gt=0, le=400, description="루프의 원래 템포")
    beats: float = Field(gt=0, le=256, description="루프 한 번의 길이(그 템포의 박)")
    start: float = Field(ge=0, description="곡에서 시작 박")
    end: float = Field(gt=0, description="곡에서 끝 박")


class Track(BaseModel):
    id: str
    name: str
    program: int = Field(default=0, ge=0, le=127, description="General MIDI 악기 번호")
    program_set: bool = Field(
        default=False, description="사용자가 악기를 직접 골랐음. 0(피아노)이어도 트랙 이름으로 악기를 짐작하지 않는다"
    )
    is_drum: bool = False
    volume: int = Field(default=100, ge=0, le=127, description="트랙 볼륨 (MIDI CC7). 100이 기본")
    pan: int = Field(default=0, ge=-64, le=63, description="좌우 위치 (MIDI CC10 - 64). -64 왼쪽, 0 가운데, 63 오른쪽")
    drum_sounds: dict[int, str] = Field(
        default_factory=dict,
        description="드럼만: 레인(음 번호)별로 킷 대신 고른 소리 id (app/tools/drums.py). MIDI에는 담기지 않는다",
    )
    drum_samples: dict[int, SampleRef] = Field(
        default_factory=dict,
        description="드럼만: 레인(음 번호)별로 킷 · drum_sounds 대신 쓰는 내 샘플. 샘플이 없는 곳에서는 킷 소리로 들린다",
    )
    audio: AudioClip | None = Field(
        default=None, description="오디오 트랙: 음표 대신 루프 파일을 그대로 깐다 (MIDI 내보내기에는 담기지 않음, 음원에는 담김)",
    )
    sample: SampleRef | None = Field(
        default=None,
        description="멜로디 트랙만: 악기 대신 쓰는 내 샘플. 샘플이 없는 곳(다른 브라우저 · MIDI 내보내기)에서는 program 악기로 들린다",
    )
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
        ends = [n.start + n.duration for t in self.tracks for n in t.notes] + [t.audio.end for t in self.tracks if t.audio]
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
    sample: str | None = None


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
                    sample=t.sample.name if t.sample else None,
                )
                for t in p.tracks
            ],
            warnings=p.warnings,
        )
