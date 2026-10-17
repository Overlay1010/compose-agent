import io

import pretty_midi
import pytest

from app.midi_io.convert import MidiParseError, looks_like_drum, midi_bytes_to_project, project_to_midi_bytes
from tests.conftest import build_midi


def test_reads_tracks_and_tempo(midi_bytes):
    p = midi_bytes_to_project(midi_bytes, name="demo")
    assert p.tempo == pytest.approx(100.0, abs=0.01)
    assert p.time_signature == (4, 4)
    assert [t.name for t in p.tracks] == ["Piano", "Bass", "Drums"]  # 빈 트랙은 제외
    assert p.bar_count == 4


def test_note_positions_in_beats(midi_bytes):
    p = midi_bytes_to_project(midi_bytes)
    bass = next(t for t in p.tracks if t.name == "Bass")
    assert [n.start for n in bass.notes] == pytest.approx([0, 2, 4, 6, 8, 10, 12, 14], abs=1e-3)
    assert all(n.duration == pytest.approx(2, abs=1e-3) for n in bass.notes)


def test_drum_detected_by_name(midi_bytes):
    p = midi_bytes_to_project(midi_bytes)
    drums = next(t for t in p.tracks if t.name == "Drums")
    piano = next(t for t in p.tracks if t.name == "Piano")
    assert drums.is_drum is True
    assert piano.is_drum is False


@pytest.mark.parametrize(
    "name, expected",
    [
        ("FPC", True),
        ("808 Kick", True),
        ("Bass Drum", True),  # 베이스 드럼 = 킥
        ("808", False),  # FL Studio에서 "808"은 보통 808 베이스
        ("808 Bass", False),
        ("Sub Bass", False),
        # DAW별로 흔한 드럼 트랙 이름
        ("Kit-Core 909", True),  # Ableton 드럼 랙
        ("Drum Rack", True),  # Ableton
        ("Groove Agent SE", True),  # Cubase
        ("Beat Machine", True),  # Logic Drum Machine Designer
        ("OpenHat", True),  # FL Studio 채널 이름
        ("Hi Hats", True),
        # 짧은 단어가 다른 단어 안에 들어 있는 경우는 드럼이 아님
        ("Custom Pad", False),
        ("Synth Toolkit", False),
        ("What Lead", False),
        ("SoCal (Kyle)", False),  # Logic Drummer: 이름으로는 못 찾고 음 패턴으로 찾는다
    ],
)
def test_looks_like_drum(name, expected):
    assert looks_like_drum(name) is expected


def _beats_to_midi(tracks: dict[str, list[tuple[int, float, float]]], tempo: float = 100.0) -> bytes:
    """{트랙 이름: [(음, 시작 박, 길이 박)]} → 10번 채널이 아닌 MIDI (이름 · 채널 힌트 없이 음 패턴만 남김)."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    spb = 60.0 / tempo
    for name, notes in tracks.items():
        inst = pretty_midi.Instrument(program=0, is_drum=False, name=name)
        for pitch, start, length in notes:
            inst.notes.append(pretty_midi.Note(90, pitch, start * spb, (start + length) * spb))
        pm.instruments.append(inst)
    buf = io.BytesIO()
    pm.write(buf)
    return buf.getvalue()


def _rock_beat(bars: int = 2) -> list[tuple[int, float, float]]:
    notes = []
    for bar in range(bars):
        for i in range(8):
            beat = bar * 4 + i * 0.5
            notes.append((42, beat, 0.25))  # 하이햇 8분
            if i in (0, 4):
                notes.append((36, beat, 0.25))  # 킥
            if i in (2, 6):
                notes.append((38, beat, 0.25))  # 스네어
    return notes


def test_logic_drummer_found_by_note_pattern():
    # 이름이 드러머 이름이고 10번 채널도 아니지만, 킥 · 스네어 · 하이햇이 겹쳐 치면 드럼
    p = midi_bytes_to_project(_beats_to_midi({"SoCal (Kyle)": _rock_beat()}))
    assert p.tracks[0].is_drum is True


def test_humanized_drums_found_by_note_pattern():
    # 사람이 친 것처럼 킥 · 하이햇 시작이 조금씩 어긋나도(±0.04박) 같이 친 것으로 본다
    jitter = [0.03, -0.04, 0.02, -0.01, 0.04, -0.03]
    loose = [(p, max(0.0, s + jitter[i % len(jitter)]), d) for i, (p, s, d) in enumerate(_rock_beat())]
    p = midi_bytes_to_project(_beats_to_midi({"Take 3": loose}))
    assert p.tracks[0].is_drum is True


def test_low_chord_loop_is_not_drum():
    # 샘플팩 루프처럼 낮은 음역 코드 + 위쪽 멜로디가 짧게 겹쳐도, 음이 퍼져 있으면 드럼이 아님
    notes = []
    for bar in range(4):
        root = [36, 41, 43, 38][bar]
        for i in range(8):
            beat = bar * 4 + i * 0.5
            notes += [(root, beat, 0.4), (root + 7, beat, 0.4), (root + 28 + i, beat, 0.4)]
    p = midi_bytes_to_project(_beats_to_midi({"Loop": notes}))
    assert p.tracks[0].is_drum is False


def test_bass_in_drum_range_is_not_drum():
    # E 단조 베이스(E2 · F#2 · G2 · A2 …)는 GM 드럼 번호와 겹치지만 한 번에 한 음이라 드럼이 아님
    line = [(p, i * 0.5, 0.4) for i, p in enumerate([40, 42, 43, 45, 47, 45, 43, 42] * 2)]
    p = midi_bytes_to_project(_beats_to_midi({"Line 1": line}))
    assert p.tracks[0].is_drum is False


def test_chords_are_not_drum():
    chords = [(p, bar * 4.0, 4.0) for bar in range(4) for p in (48, 52, 55, 59)]
    p = midi_bytes_to_project(_beats_to_midi({"Track 3": chords}))
    assert p.tracks[0].is_drum is False


def test_round_trip_keeps_notes(midi_bytes):
    p1 = midi_bytes_to_project(midi_bytes)
    p2 = midi_bytes_to_project(project_to_midi_bytes(p1))
    assert p2.tempo == pytest.approx(p1.tempo, abs=0.01)
    for t1, t2 in zip(p1.tracks, p2.tracks):
        assert t1.name == t2.name
        assert len(t1.notes) == len(t2.notes)
        for a, b in zip(t1.notes, t2.notes):
            assert (a.pitch, a.velocity) == (b.pitch, b.velocity)
            assert a.start == pytest.approx(b.start, abs=1e-2)
            assert a.duration == pytest.approx(b.duration, abs=1e-2)


def test_tempo_change_warns_but_keeps_beat_positions():
    p = midi_bytes_to_project(build_midi(tempo=100, extra_tempo=140))
    assert p.tempo == pytest.approx(100, abs=0.01)
    assert any("템포" in w for w in p.warnings)
    # 템포가 바뀐 3마디 이후 음도 박 위치는 그대로여야 한다
    bass = next(t for t in p.tracks if t.name == "Bass")
    assert bass.notes[-1].start == pytest.approx(14, abs=1e-2)


def _with_time_signatures(*sigs: tuple[int, int]) -> bytes:
    pm = pretty_midi.PrettyMIDI(io.BytesIO(build_midi()))
    pm.time_signature_changes = [pretty_midi.TimeSignature(n, d, i * 2.4) for i, (n, d) in enumerate(sigs)]
    buf = io.BytesIO()
    pm.write(buf)
    return buf.getvalue()


def test_duplicate_time_signature_is_not_a_change():
    # 같은 4/4가 두 번 들어 있는 파일(샘플팩에 흔함)은 경고하지 않는다
    p = midi_bytes_to_project(_with_time_signatures((4, 4), (4, 4)))
    assert p.time_signature == (4, 4)
    assert p.warnings == []


def test_real_time_signature_change_warns():
    p = midi_bytes_to_project(_with_time_signatures((4, 4), (3, 4)))
    assert p.time_signature == (4, 4)
    assert any("박자" in w for w in p.warnings)


def test_garbage_raises():
    with pytest.raises(MidiParseError):
        midi_bytes_to_project(b"not a midi file")


def test_korean_track_names_export_and_come_back():
    from app.midi_io.convert import project_to_midi_bytes
    from app.models.project import Note, Project, Track

    p = Project(id="p", tracks=[
        Track(id="t1", name="탑노트", notes=[Note(pitch=72, start=0, duration=1)]),
        Track(id="t2", name="Café 멜로디 #1", notes=[Note(pitch=60, start=0, duration=1)]),
    ])
    back = midi_bytes_to_project(project_to_midi_bytes(p))  # 예전에는 UnicodeEncodeError
    assert [t.name for t in back.tracks] == ["탑노트", "Café 멜로디 #1"]
