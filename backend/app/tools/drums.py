"""드럼 소리 고르기: set_drum_sound.

드럼 킷은 소리 묶음이고, 여기서는 레인(음 번호) 하나의 소리만 따로 바꾼다 (FL Studio FPC · Ableton Drum Rack처럼).
어떤 샘플을 쓸지는 MIDI에 담을 표준이 없어서 이 앱의 프로젝트에만 남는다 (내보낸 .mid는 음 번호 그대로).

소리 목록은 frontend/src/audio/instruments.ts DRUM_SOUNDS와 같아야 한다 (tests/test_tools.py가 확인).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import Project
from app.tools.base import ToolError, ToolResult

# GM 드럼 번호 → 역할. 같은 역할의 소리끼리만 바꿀 수 있다 (킥 레인에 하이햇 소리 X)
ROLES = {
    35: "kick", 36: "kick",
    37: "snare", 38: "snare", 40: "snare",
    39: "clap",
    42: "hat", 44: "hat",
    46: "openhat",
    41: "tom", 43: "tom", 45: "tom", 47: "tom", 48: "tom", 50: "tom",
    49: "crash", 52: "crash", 55: "crash", 57: "crash",
    51: "ride", 53: "ride", 59: "ride",
}
ROLE_NAMES = {
    "kick": "킥", "snare": "스네어", "clap": "클랩", "hat": "닫힌 하이햇", "openhat": "열린 하이햇",
    "tom": "탐", "crash": "크래시", "ride": "라이드",
}

# 소리 id → (화면 이름, 역할)
DRUM_SOUNDS: dict[str, tuple[str, str]] = {
    "kick_acoustic": ("어쿠스틱 킥", "kick"),
    "kick_soft": ("부드러운 킥", "kick"),
    "kick_punch": ("펀치 킥", "kick"),
    "kick_808": ("808 킥", "kick"),
    "kick_house": ("하우스 킥", "kick"),
    "kick_lofi": ("둥근 로파이 킥", "kick"),
    "kick_boombap": ("붐뱁 킥", "kick"),
    "kick_electro": ("일렉 킥", "kick"),
    "snare_acoustic": ("어쿠스틱 스네어", "snare"),
    "snare_soft": ("부드러운 스네어", "snare"),
    "snare_big": ("큰 스네어", "snare"),
    "snare_lofi": ("먹먹한 스네어", "snare"),
    "snare_909": ("909 스네어", "snare"),
    "snare_boombap": ("붐뱁 스네어", "snare"),
    "snare_electro": ("일렉 스네어", "snare"),
    "snare_808": ("808 스네어", "snare"),
    "clap": ("클랩", "clap"),
    "clap_909": ("909 클랩", "clap"),
    "hat_acoustic": ("어쿠스틱 하이햇", "hat"),
    "hat_808": ("808 하이햇", "hat"),
    "hat_909": ("909 하이햇", "hat"),
    "hat_soft": ("작고 부드러운 하이햇", "hat"),
    "hat_crisp": ("또렷한 하이햇", "hat"),
    "hat_electro": ("일렉 하이햇", "hat"),
    "openhat_acoustic": ("어쿠스틱 오픈햇", "openhat"),
    "openhat_808": ("808 오픈햇", "openhat"),
    "openhat_909": ("909 오픈햇", "openhat"),
    "openhat_soft": ("부드러운 오픈햇", "openhat"),
    "openhat_electro": ("일렉 오픈햇", "openhat"),
    "tom_acoustic": ("어쿠스틱 탐", "tom"),
    "tom_deep": ("낮고 큰 탐", "tom"),
    "tom_round": ("둥근 로파이 탐", "tom"),
    "tom_808": ("808 탐", "tom"),
    "tom_electro": ("일렉 탐", "tom"),
    "crash_acoustic": ("어쿠스틱 크래시", "crash"),
    "crash_splash": ("스플래시", "crash"),
    "crash_electro": ("일렉 심벌", "crash"),
    "ride_acoustic": ("어쿠스틱 라이드", "ride"),
    "ride_jazz": ("재즈 라이드", "ride"),
    "ride_bright": ("밝은 라이드", "ride"),
}

DEFAULT = "default"  # 킷 기본 소리로 되돌리기


def sound_name(sound: str) -> str:
    return "킷 기본 소리" if sound == DEFAULT else DRUM_SOUNDS[sound][0]


def sounds_for(role: str) -> str:
    return ", ".join(f"{sid} {name}" for sid, (name, r) in DRUM_SOUNDS.items() if r == role)


class SetDrumSoundArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(description='드럼 트랙 id (예: "t1")')
    pitches: list[int] = Field(min_length=1, description="바꿀 소리의 음 번호들 (예: 탐 [41, 43, 45, 47, 48, 50])")
    sound: str = Field(description='소리 id (예: "tom_808") 또는 "default"(킷 기본 소리로). 같은 역할(탐 → tom_*)만 된다')


def set_drum_sound(project: Project, args: SetDrumSoundArgs) -> ToolResult:
    track = next((t for t in project.tracks if t.id == args.track_id), None)
    if track is None:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {args.track_id}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    if not track.is_drum:
        raise ToolError("드럼 트랙이 아니에요. 멜로디 트랙의 소리는 set_instrument로 바꿔요.", code="not_drum")
    if args.sound != DEFAULT and args.sound not in DRUM_SOUNDS:
        raise ToolError(f"없는 소리 id예요: {args.sound}. 소리 id는 드럼 역할별 목록에서 골라요.", code="unknown_sound")

    used = {n.pitch for n in track.notes}
    pitches = [p for p in dict.fromkeys(args.pitches) if p in used]
    if not pitches:
        raise ToolError(f"이 트랙에 그 소리가 없어요. 쓰인 소리 번호: {sorted(used)}", code="unknown_pitch")
    if args.sound != DEFAULT:
        role = DRUM_SOUNDS[args.sound][1]
        wrong = [p for p in pitches if ROLES.get(p) != role]
        if wrong:
            hints = "; ".join(
                f"{p}({ROLE_NAMES[ROLES[p]]}): {sounds_for(ROLES[p])}" if p in ROLES else f"{p}: 바꿀 수 있는 소리가 없음"
                for p in wrong
            )
            raise ToolError(
                f"{sound_name(args.sound)}은(는) {ROLE_NAMES[role]} 소리라 다른 역할의 레인에는 못 넣어요. 쓸 수 있는 소리 — {hints}",
                code="wrong_role",
            )

    sounds = dict(track.drum_sounds)
    for p in pitches:
        if args.sound == DEFAULT:
            sounds.pop(p, None)
        else:
            sounds[p] = args.sound
    if sounds == track.drum_sounds:
        return ToolResult(project=project, summary=f"이미 {sound_name(args.sound)}이라 바뀐 게 없어요.")
    roles = sorted({ROLE_NAMES.get(ROLES.get(p, ""), str(p)) for p in pitches})
    return ToolResult(
        project=project.model_copy(
            update={"tracks": [t.model_copy(update={"drum_sounds": sounds}) if t.id == track.id else t for t in project.tracks]}
        ),
        changed_settings=True,
        summary=f"{track.name} {' · '.join(roles)} 소리를 {sound_name(args.sound)}(으)로 바꿨어요. 음은 그대로예요.",
    )
