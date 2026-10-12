"""MIDI 파일 <-> Project 변환.

v0.1은 고정 템포만 지원한다. 템포 변화나 박자 변화가 있으면
첫 값을 쓰고 warnings에 남긴다.

FL Studio 참고:
- 드럼을 10번 채널로 보내지 않는 경우가 많아서 is_drum 플래그만으로는 드럼을
  못 찾는다. 그래서 트랙 이름으로도 한 번 더 판단한다(looks_like_drum).
- "808"은 키워드에 넣지 않는다. FL Studio에서 "808"은 보통 음정이 있는 808 베이스라서다.
  808 킥·스네어는 "808 Kick"처럼 kick/snare가 같이 붙으므로 그대로 드럼으로 잡힌다.
"""

from __future__ import annotations

import io
import uuid

import pretty_midi

from app.models.project import Note, Project, Track

DRUM_KEYWORDS = (
    "drum", "kick", "snare", "hat", "hihat", "clap", "perc", "tom", "cymbal",
    "fpc", "드럼", "킥", "스네어", "하이햇",
)

EXPORT_RESOLUTION = 480  # 내보낼 때의 PPQ (1박을 몇 틱으로 나눌지)


class MidiParseError(ValueError):
    pass


def looks_like_drum(name: str) -> bool:
    lowered = name.lower()
    return any(k in lowered for k in DRUM_KEYWORDS)


def _round(x: float) -> float:
    return round(x, 4)


def midi_bytes_to_project(data: bytes, name: str = "Untitled") -> Project:
    try:
        pm = pretty_midi.PrettyMIDI(io.BytesIO(data))
    except Exception as e:  # pretty_midi/mido가 던지는 예외 종류가 다양함
        raise MidiParseError(f"MIDI 파일을 읽을 수 없습니다: {e}") from e

    warnings: list[str] = []

    _, tempi = pm.get_tempo_changes()
    tempo = float(tempi[0]) if len(tempi) else 120.0
    if len({round(t, 3) for t in tempi}) > 1:
        warnings.append(f"템포 변화가 {len(tempi)}번 있어 첫 템포({tempo:.1f} BPM)만 사용합니다.")

    ts = (4, 4)
    if pm.time_signature_changes:
        first = pm.time_signature_changes[0]
        ts = (first.numerator, first.denominator)
        # 같은 박자가 중복으로 들어 있는 파일이 흔하다 (예: Cymatics 루프는 4/4가 0틱에 두 번). 값이 다를 때만 경고.
        if len({(t.numerator, t.denominator) for t in pm.time_signature_changes}) > 1:
            warnings.append("박자 변화가 있어 첫 박자만 사용합니다.")

    # 초 -> 틱 -> 박 으로 바꾸면 템포가 바뀌는 파일에서도 박 위치가 정확하다.
    def to_beat(seconds: float) -> float:
        return pm.time_to_tick(seconds) / pm.resolution

    tracks: list[Track] = []
    for i, inst in enumerate(pm.instruments):
        notes = [
            Note(
                pitch=n.pitch,
                start=_round(to_beat(n.start)),
                duration=max(_round(to_beat(n.end) - to_beat(n.start)), 0.0001),
                velocity=max(1, n.velocity),
            )
            for n in sorted(inst.notes, key=lambda n: (n.start, n.pitch))
        ]
        if not notes:
            continue
        track_name = inst.name.strip() or f"Track {i + 1}"
        is_drum = inst.is_drum or looks_like_drum(track_name)
        tracks.append(
            Track(
                id=f"t{len(tracks) + 1}",
                name=track_name,
                program=inst.program,
                is_drum=is_drum,
                notes=notes,
            )
        )

    if not tracks:
        raise MidiParseError("음표가 있는 트랙이 없습니다. 노트가 들어 있는 패턴을 내보냈는지 확인해 주세요.")

    return Project(
        id=uuid.uuid4().hex[:12],
        name=name,
        tempo=_round(tempo),
        time_signature=ts,
        tracks=tracks,
        warnings=warnings,
    )


def project_to_midi_bytes(project: Project) -> bytes:
    pm = pretty_midi.PrettyMIDI(initial_tempo=project.tempo, resolution=EXPORT_RESOLUTION)
    num, den = project.time_signature
    pm.time_signature_changes.append(pretty_midi.TimeSignature(num, den, 0.0))

    sec_per_beat = 60.0 / project.tempo
    for track in project.tracks:
        inst = pretty_midi.Instrument(program=track.program, is_drum=track.is_drum, name=track.name)
        for n in track.notes:
            start = n.start * sec_per_beat
            inst.notes.append(
                pretty_midi.Note(
                    velocity=n.velocity,
                    pitch=n.pitch,
                    start=start,
                    end=start + n.duration * sec_per_beat,
                )
            )
        pm.instruments.append(inst)

    buf = io.BytesIO()
    pm.write(buf)
    return buf.getvalue()
