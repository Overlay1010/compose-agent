"""scripts/make_samples.py 가 만드는 샘플이 제대로 읽히는지 확인한다."""

import sys
from pathlib import Path

import pytest

from app.midi_io.convert import midi_bytes_to_project

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402


@pytest.mark.parametrize("filename", list(make_samples.SAMPLES))
def test_sample_parses(filename):
    p = midi_bytes_to_project(make_samples.SAMPLES[filename]())
    assert p.tracks and all(t.notes for t in p.tracks)


def test_lofi_groove_shape():
    p = midi_bytes_to_project(make_samples.lofi_groove())
    assert [t.name for t in p.tracks] == ["Drums", "Bass", "Rhodes", "Pad", "Lead"]
    assert p.bar_count == 16
    assert p.tempo == pytest.approx(84, abs=0.01)


def test_fl_style_drum_found_by_name_only():
    # FL Studio처럼 10번 채널도 아니고 악기 번호도 0이지만 이름(FPC)으로 드럼을 찾아야 한다
    p = midi_bytes_to_project(make_samples.fl_style_loose())
    fpc = next(t for t in p.tracks if t.name == "FPC")
    assert fpc.is_drum and fpc.program == 0
    assert not any(t.is_drum for t in p.tracks if t.name != "FPC")


def test_fl_style_is_off_grid():
    # 퀀타이즈 도구 시험용: 16분음표 격자에서 벗어난 음이 대부분이어야 한다
    p = midi_bytes_to_project(make_samples.fl_style_loose())
    starts = [n.start for t in p.tracks for n in t.notes]
    off = [s for s in starts if abs(s * 4 - round(s * 4)) > 0.01]
    assert len(off) / len(starts) > 0.8


def test_waltz_time_signature():
    p = midi_bytes_to_project(make_samples.waltz_3_4())
    assert p.time_signature == (3, 4)
    assert p.bar_count == 8


def test_tempo_change_warns_and_keeps_beats():
    p = midi_bytes_to_project(make_samples.tempo_change())
    assert p.tempo == pytest.approx(100, abs=0.01)
    assert any("템포" in w for w in p.warnings)
    drums = next(t for t in p.tracks if t.name == "Drums")
    kicks = [n.start for n in drums.notes if n.pitch == make_samples.KICK]
    assert kicks == pytest.approx([b * 4 + o for b in range(8) for o in (0, 2)], abs=1e-3)
