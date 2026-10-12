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
    ],
)
def test_looks_like_drum(name, expected):
    assert looks_like_drum(name) is expected


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
