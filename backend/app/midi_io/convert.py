"""MIDI 파일 <-> Project 변환.

v0.1은 고정 템포만 지원한다. 템포 변화나 박자 변화가 있으면
첫 값을 쓰고 warnings에 남긴다.

드럼 찾기 (DAW마다 내보내는 방식이 달라서 세 가지로 본다):
1. 10번 채널(is_drum). Cubase · Logic의 GM 드럼은 대부분 여기서 잡힌다.
2. 트랙 이름(looks_like_drum). FL Studio는 드럼을 10번 채널로 보내지 않는 경우가 많고
   (FPC), Ableton은 "Drum Rack" · "Kit-Core 909", Cubase는 "Groove Agent SE" 같은 이름이 붙는다.
3. 음 패턴(looks_like_drum_notes). Logic Drummer 트랙은 이름이 드러머 이름("SoCal (Kyle)")이라
   이름으로는 못 찾는다. GM 드럼 번호에 짧은 음이 몰려 있고, 킥 · 스네어 · 하이햇 중 두 가지 이상이
   있으며, 여러 소리가 같은 순간에 자주 겹치면 드럼으로 본다. 베이스는 한 번에 한 음이라 걸리지 않는다.

"808"은 키워드에 넣지 않는다. FL Studio에서 "808"은 보통 음정이 있는 808 베이스라서다.
808 킥 · 스네어는 "808 Kick"처럼 kick/snare가 같이 붙으므로 그대로 드럼으로 잡힌다.
"""

from __future__ import annotations

import io
import re
import statistics
import uuid
from collections import Counter

import pretty_midi

from app.models.project import Note, Project, Track

DRUM_KEYWORDS = (
    "drum", "kick", "snare", "hihat", "openhat", "closedhat", "clap", "perc", "cymbal",
    "fpc",  # FL Studio
    "groove agent",  # Cubase
    "beat machine", "drummer",  # Logic
    "battery", "ezdrummer", "superior drummer", "addictive drums",  # 자주 쓰는 드럼 플러그인
    "드럼", "킥", "스네어", "하이햇",
)

# 짧은 단어는 다른 단어 안에 들어 있을 수 있어서("Custom", "Toolkit") 단어 단위로만 찾는다.
# kit = Ableton 드럼 랙 기본 키트 이름 ("Kit-Core 909")
DRUM_WORDS = re.compile(r"(?<![a-z])(hats?|toms?|kit)(?![a-z])")

# General MIDI 드럼 번호. 킷의 주요 소리(킥 ~ 심벌)는 27~59에 있고, 60 이상은 콩가 · 셰이커 같은 타악기
GM_KIT_RANGE = range(27, 60)
KICKS, SNARES, HATS = {35, 36}, {37, 38, 39, 40}, {42, 44, 46}
STACK_TOLERANCE = 0.1  # 박. 사람이 친 드럼은 킥과 하이햇이 정확히 같은 틱이 아니어서 이 안이면 "같이 침"

EXPORT_RESOLUTION = 480  # 내보낼 때의 PPQ (1박을 몇 틱으로 나눌지)


class MidiParseError(ValueError):
    pass


def looks_like_drum(name: str) -> bool:
    lowered = name.lower()
    return any(k in lowered for k in DRUM_KEYWORDS) or bool(DRUM_WORDS.search(lowered))


def looks_like_drum_notes(notes: list[Note]) -> bool:
    """이름 · 채널 없이 음 패턴만으로 드럼 트랙인지 본다.

    샘플팩 루프 37개와 직접 만든 샘플로 맞춘 기준: 낮은 음역에 코드가 깔린 멜로디 루프가
    "GM 번호 범위 + 겹침"만으로는 드럼처럼 보여서, 음이 몇 개 소리에 몰려 있는지도 같이 본다.
    """
    if len(notes) < 8:
        return False
    pitches = [n.pitch for n in notes]
    if sum(p in GM_KIT_RANGE for p in pitches) / len(pitches) < 0.85:
        return False
    used = set(pitches)
    if sum(bool(used & group) for group in (KICKS, SNARES, HATS)) < 2:
        return False
    if statistics.median(n.duration for n in notes) > 0.5:
        return False
    # 드럼은 킥 · 스네어 · 하이햇 몇 개 소리가 대부분이다. 멜로디 · 코드는 음이 퍼져 있다
    top3 = sum(c for _, c in Counter(pitches).most_common(3)) / len(pitches)
    if top3 < 0.6:
        return False
    # 같은 순간에 두 소리 이상(예: 킥 + 하이햇)이 겹치는 비율. 베이스는 한 번에 한 음이라 거의 0
    groups, last = [], None
    for start in sorted(n.start for n in notes):
        if last is not None and start - last <= STACK_TOLERANCE:
            groups[-1] += 1
        else:
            groups.append(1)
            last = start
    return sum(1 for g in groups if g >= 2) / len(groups) >= 0.15


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
        is_drum = inst.is_drum or looks_like_drum(track_name) or looks_like_drum_notes(notes)
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
