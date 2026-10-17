"""악기 도구: set_instrument.

트랙의 General MIDI 악기 번호(program)를 바꾼다. 음표는 그대로고 소리만 달라진다.
MIDI로 내보낼 때 이 번호가 프로그램 체인지로 들어가 DAW에서도 같은 악기 번호로 열린다.
드럼 트랙은 음 번호가 곧 드럼 소리라, 악기 대신 드럼 킷 번호(GM 드럼 킷)만 받는다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import Project
from app.tools.base import ToolError, ToolResult

# General MIDI 1 악기 이름 (번호 = 목록 위치)
GM_NAMES = [
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano", "Honky-tonk Piano",
    "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet",
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone", "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ", "Reed Organ", "Accordion", "Harmonica",
    "Tango Accordion",
    "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)", "Electric Guitar (jazz)", "Electric Guitar (clean)",
    "Electric Guitar (muted)", "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)", "Fretless Bass", "Slap Bass 1", "Slap Bass 2",
    "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2", "Choir Aahs", "Voice Oohs",
    "Synth Choir", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)", "Lead 4 (chiff)", "Lead 5 (charang)",
    "Lead 6 (voice)", "Lead 7 (fifths)", "Lead 8 (bass + lead)",
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)", "Pad 4 (choir)", "Pad 5 (bowed)", "Pad 6 (metallic)",
    "Pad 7 (halo)", "Pad 8 (sweep)",
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)", "FX 4 (atmosphere)", "FX 5 (brightness)",
    "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)",
    "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet", "Telephone Ring", "Helicopter", "Applause",
    "Gunshot",
]
assert len(GM_NAMES) == 128


# 화면에 보일 한국어 이름 (frontend/src/theme.ts GM_NAMES와 같은 목록). 없으면 영어 이름
GM_NAMES_KO = {
    0: "그랜드 피아노", 4: "전자 피아노", 5: "전자 피아노 (FM)", 9: "글로켄슈필", 24: "나일론 기타", 25: "스틸 기타",
    27: "클린 일렉 기타", 32: "어쿠스틱 베이스", 33: "핑거 베이스", 34: "피크 베이스", 38: "신스 베이스",
    48: "스트링 앙상블", 52: "합창", 61: "브라스 섹션", 73: "플룻", 80: "사각파 리드", 81: "톱니파 리드",
    88: "뉴에이지 패드", 89: "따뜻한 패드",
}


# General MIDI 드럼 킷 (드럼 채널의 프로그램 번호). 화면에서 소리가 실제로 다른 킷만 둔다
# (frontend/src/audio/instruments.ts DRUM_KITS와 같은 목록)
# 8 · 32는 GM2 표준 번호, 26~28은 이 앱 전용 (DAW에서는 각 DAW 드럼 소리로 열림)
DRUM_KITS = {
    0: "스탠다드", 8: "룸", 16: "파워", 24: "일렉트로닉", 25: "TR-808",
    26: "하우스 (909)", 27: "로파이", 28: "붐뱁", 32: "재즈",
}


def kit_name(program: int) -> str:
    return DRUM_KITS.get(program, f"킷 {program}")


def display_name(program: int) -> str:
    return GM_NAMES_KO.get(program, GM_NAMES[program])


def gm_name(program: int) -> str:
    return f"{program} {GM_NAMES[program]}"


class SetInstrumentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_ids: list[str] = Field(min_length=1, description='바꿀 트랙 id 목록 (예: ["t2"])')
    program: int = Field(
        ge=0, le=127,
        description="General MIDI 악기 번호 0~127 (예: 0 피아노, 33 핑거 베이스, 38 신스 베이스). "
        "드럼 트랙이면 드럼 킷 번호: 0 스탠다드, 8 룸, 16 파워, 24 일렉트로닉, 25 TR-808, 26 하우스, 27 로파이, 28 붐뱁, 32 재즈",
    )


def set_instrument(project: Project, args: SetInstrumentArgs) -> ToolResult:
    by_id = {t.id: t for t in project.tracks}
    unknown = [i for i in args.track_ids if i not in by_id]
    if unknown:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    targets = [by_id[i] for i in args.track_ids]
    kit = args.program in DRUM_KITS
    if all(t.is_drum for t in targets) and not kit:
        kits = ", ".join(f"{p} {n}" for p, n in DRUM_KITS.items())
        raise ToolError(
            f"드럼 트랙은 음 번호가 곧 드럼 소리라 다른 악기로 바꿀 수 없어요. 드럼 킷만 고를 수 있어요: {kits}. "
            "사용자가 킷을 말한 게 아니면 그렇게 알려 주세요.",
            code="drum_track",
        )

    changed: list[str] = []
    kits_changed: list[str] = []
    same: list[str] = []
    tracks = []
    for t in project.tracks:
        if t.id in args.track_ids and t.is_drum and kit:
            # 드럼은 이름으로 악기를 짐작하지 않으니 번호만 비교한다
            if t.program == args.program:
                same.append(t.name)
            else:
                kits_changed.append(t.name)
                # 킷을 바꾸면 레인별로 따로 고른 소리도 새 킷 소리로 돌아간다 (DAW 드럼 킷과 같게)
                t = t.model_copy(update={"program": args.program, "program_set": True, "drum_sounds": {}})
        elif t.id in args.track_ids and not t.is_drum:
            if t.program == args.program and t.program_set:
                same.append(t.name)
            else:
                changed.append(f"{t.name}({GM_NAMES[t.program] if t.program_set or t.program else '지정 안 됨'})")
                t = t.model_copy(update={"program": args.program, "program_set": True})
        tracks.append(t)

    if not changed and not kits_changed:
        what = kit_name(args.program) if all(t.is_drum for t in targets) else gm_name(args.program)
        return ToolResult(project=project, summary=f"{', '.join(same)} 트랙은 이미 {what}이라 바뀐 게 없어요.")
    parts = []
    if changed:
        parts.append(f"{', '.join(changed)} 악기를 {gm_name(args.program)}(으)로 바꿨어요.")
    if kits_changed:
        parts.append(f"{', '.join(kits_changed)} 드럼 킷을 {kit_name(args.program)}({args.program})(으)로 바꿨어요.")
    skipped = [t.name for t in targets if t.is_drum and not kit]
    if skipped:
        parts.append(f"드럼 트랙({', '.join(skipped)})은 건너뛰었어요.")
    return ToolResult(
        project=project.model_copy(update={"tracks": tracks}),
        changed_settings=True,
        summary=" ".join(parts) + " 음은 그대로예요.",
    )
