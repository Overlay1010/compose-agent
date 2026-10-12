"""테스트용 MIDI를 코드로 만든다 (저작권 걱정 없는 합성 데이터).

FL Studio에서 내보낸 파일과 비슷하게:
- 드럼 트랙이 10번 채널이 아니고(is_drum=False) 이름만 'Drums'
- 트랙마다 이름이 있음
"""

from __future__ import annotations

import io

import pretty_midi
import pytest
from fastapi.testclient import TestClient

from app.main import app


def build_midi(tempo: float = 100.0, extra_tempo: float | None = None) -> bytes:
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    spb = 60.0 / tempo

    def add(inst: pretty_midi.Instrument, pitch: int, beat: float, length: float, vel: int = 90) -> None:
        inst.notes.append(pretty_midi.Note(vel, pitch, beat * spb, (beat + length) * spb))

    piano = pretty_midi.Instrument(program=0, name="Piano")
    # C - Am - F - G, 마디당 하나
    for bar, chord in enumerate([(60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]):
        for p in chord:
            add(piano, p, bar * 4, 4)

    bass = pretty_midi.Instrument(program=33, name="Bass")
    for bar, root in enumerate([36, 33, 29, 31]):
        add(bass, root, bar * 4, 2)
        add(bass, root, bar * 4 + 2, 2)

    drums = pretty_midi.Instrument(program=0, is_drum=False, name="Drums")
    for beat in range(16):
        add(drums, 36 if beat % 2 == 0 else 38, beat, 0.25, 110)

    empty = pretty_midi.Instrument(program=0, name="Empty")

    pm.instruments.extend([piano, bass, drums, empty])

    if extra_tempo is not None:
        # 2마디 뒤에 템포 변경 이벤트 추가 (mido 수준에서 삽입)
        buf = io.BytesIO()
        pm.write(buf)
        import mido

        mid = mido.MidiFile(file=io.BytesIO(buf.getvalue()))
        mid.tracks[0].append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(extra_tempo), time=pm.resolution * 8))
        out = io.BytesIO()
        mid.save(file=out)
        return out.getvalue()

    buf = io.BytesIO()
    pm.write(buf)
    return buf.getvalue()


@pytest.fixture
def midi_bytes() -> bytes:
    return build_midi()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
