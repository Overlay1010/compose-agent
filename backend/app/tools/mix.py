"""믹스 도구: set_mix (트랙 볼륨 · 팬).

음 세기(velocity)는 음마다 다르게 치는 힘이고, 볼륨은 트랙 전체의 소리 크기(페이더)다.
MIDI로 내보낼 때 볼륨은 CC7, 팬은 CC10으로 들어간다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.project import Project
from app.tools.base import ToolError, ToolResult


def pan_text(pan: int) -> str:
    if pan == 0:
        return "가운데"
    return f"{'왼쪽' if pan < 0 else '오른쪽'} {abs(pan)}"


class SetMixArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_ids: list[str] = Field(min_length=1, description='바꿀 트랙 id 목록 (예: ["t4"])')
    volume: int | None = Field(default=None, ge=0, le=127, description="볼륨을 이 값으로 (0~127, 기본 100)")
    volume_offset: int | None = Field(
        default=None, ge=-127, le=127, description="지금 볼륨에 더하기 (줄이면 음수). 조금 = ±10~15, 많이 = ±25~35"
    )
    pan: int | None = Field(default=None, ge=-64, le=63, description="좌우 위치. -64 완전 왼쪽, 0 가운데, 63 완전 오른쪽")

    @model_validator(mode="after")
    def _check(self) -> "SetMixArgs":
        if self.volume is not None and self.volume_offset is not None:
            raise ValueError("volume과 volume_offset 중 하나만 써요.")
        if self.volume is None and self.volume_offset is None and self.pan is None:
            raise ValueError("volume · volume_offset · pan 중 하나는 있어야 해요.")
        return self


def set_mix(project: Project, args: SetMixArgs) -> ToolResult:
    by_id = {t.id: t for t in project.tracks}
    unknown = [i for i in args.track_ids if i not in by_id]
    if unknown:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track")

    parts: list[str] = []
    tracks = []
    for t in project.tracks:
        if t.id in args.track_ids:
            volume = t.volume
            if args.volume is not None:
                volume = args.volume
            elif args.volume_offset is not None:
                volume = max(0, min(127, t.volume + args.volume_offset))
            pan = t.pan if args.pan is None else args.pan
            changes = []
            if volume != t.volume:
                changes.append(f"볼륨 {t.volume} → {volume}")
            if pan != t.pan:
                changes.append(f"팬 {pan_text(t.pan)} → {pan_text(pan)}")
            if changes:
                parts.append(f"{t.name} {' · '.join(changes)}")
                t = t.model_copy(update={"volume": volume, "pan": pan})
        tracks.append(t)

    if not parts:
        return ToolResult(project=project, summary="볼륨 · 팬이 이미 그 값이라 바뀐 게 없어요.")
    return ToolResult(
        project=project.model_copy(update={"tracks": tracks}),
        changed_settings=True,
        summary=f"{' / '.join(parts)}(으)로 바꿨어요. 음 세기는 그대로예요.",
    )
