"""악기 도구: set_instrument.

트랙의 General MIDI 악기 번호(program)를 바꾼다. 음표는 그대로고 소리만 달라진다.
MIDI로 내보낼 때 이 번호가 프로그램 체인지로 들어가 DAW에서도 같은 악기 번호로 열린다.
드럼 트랙은 음 번호가 곧 드럼 소리라 악기 번호가 없다 (건너뛴다).
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


def gm_name(program: int) -> str:
    return f"{program} {GM_NAMES[program]}"


class SetInstrumentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_ids: list[str] = Field(min_length=1, description='바꿀 트랙 id 목록 (예: ["t2"])')
    program: int = Field(ge=0, le=127, description="General MIDI 악기 번호 0~127 (예: 0 피아노, 33 핑거 베이스, 38 신스 베이스)")


def set_instrument(project: Project, args: SetInstrumentArgs) -> ToolResult:
    by_id = {t.id: t for t in project.tracks}
    unknown = [i for i in args.track_ids if i not in by_id]
    if unknown:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    targets = [by_id[i] for i in args.track_ids]
    if all(t.is_drum for t in targets):
        raise ToolError(
            "드럼 트랙은 음 번호가 곧 드럼 소리라 악기 번호를 바꿀 수 없어요. 사용자에게 그렇게 알려 주세요.",
            code="drum_track",
        )

    changed: list[str] = []
    same: list[str] = []
    tracks = []
    for t in project.tracks:
        if t.id in args.track_ids and not t.is_drum:
            if t.program == args.program and t.program_set:
                same.append(t.name)
            else:
                changed.append(f"{t.name}({GM_NAMES[t.program] if t.program_set or t.program else '지정 안 됨'})")
                t = t.model_copy(update={"program": args.program, "program_set": True})
        tracks.append(t)

    if not changed:
        return ToolResult(project=project, summary=f"{', '.join(same)} 트랙은 이미 {gm_name(args.program)}이라 바뀐 게 없어요.")
    skipped = [t.name for t in targets if t.is_drum]
    note = f" 드럼 트랙({', '.join(skipped)})은 건너뛰었어요." if skipped else ""
    return ToolResult(
        project=project.model_copy(update={"tracks": tracks}),
        changed_settings=True,
        summary=f"{', '.join(changed)} 악기를 {gm_name(args.program)}(으)로 바꿨어요. 음은 그대로예요.{note}",
    )
