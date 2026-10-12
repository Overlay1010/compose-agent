"""samples/ 의 테스트용 MIDI를 코드로 만든다.

음표는 모두 직접 쓴 것이라 저작권 걱정이 없고, 다시 돌리면 똑같은 파일이 나온다.

    backend\\compose_venv\\Scripts\\python scripts\\make_samples.py

만드는 파일
- lofi_groove.mid      메인 데모. 16마디, 트랙 5개 (드럼 · 베이스 · 건반 · 패드 · 멜로디)
- fl_style_loose.mid   FL Studio식: 드럼이 10번 채널이 아니고 이름이 FPC, 악기 번호 전부 0,
                       타이밍·세기가 조금씩 흔들림 (퀀타이즈·세기 조절 도구 시험용)
- waltz_3_4.mid        3/4 박자 (마디선·재생선 확인용)
- tempo_change.mid     5마디부터 템포가 100 -> 130 으로 바뀜 (경고 문구 확인용)
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import mido
import pretty_midi

OUT = Path(__file__).resolve().parent.parent / "samples"

# General MIDI 드럼 번호
KICK, SNARE, CLAP, HAT, OPEN_HAT, CRASH = 36, 38, 39, 42, 46, 49
TOM_HI, TOM_MID, TOM_LOW, TOM_FLOOR = 50, 48, 45, 43


def n(name: str) -> int:
    return pretty_midi.note_name_to_number(name)


class Song:
    """박 단위로 음표를 넣으면 pretty_midi 초 단위로 바꿔 주는 도우미."""

    def __init__(self, tempo: float, time_signature: tuple[int, int] = (4, 4)):
        self.pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
        self.pm.time_signature_changes.append(pretty_midi.TimeSignature(*time_signature, 0.0))
        self.spb = 60.0 / tempo
        self.beats_per_bar = time_signature[0] * 4 / time_signature[1]

    def track(self, name: str, program: int = 0, is_drum: bool = False) -> pretty_midi.Instrument:
        inst = pretty_midi.Instrument(program=program, is_drum=is_drum, name=name)
        self.pm.instruments.append(inst)
        return inst

    def note(self, inst: pretty_midi.Instrument, pitch: int, bar: int, beat: float, length: float, vel: int = 90) -> None:
        start = (bar * self.beats_per_bar + beat) * self.spb
        inst.notes.append(pretty_midi.Note(vel, pitch, max(start, 0.0), start + length * self.spb))

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.pm.write(buf)
        return buf.getvalue()


# ---------- 1. lofi_groove ----------

def lofi_groove() -> bytes:
    s = Song(tempo=84)
    drums = s.track("Drums", is_drum=True)
    bass = s.track("Bass", program=33)
    keys = s.track("Rhodes", program=4)
    pad = s.track("Pad", program=89)
    lead = s.track("Lead", program=80)

    # 마디별 (건반 보이싱, 베이스 루트). A: Fmaj9 Em9 Dm9 Cmaj9 x2 / B: Dm9 G13 Cmaj9 A7 · Dm9 G13 Cmaj9 Cmaj9
    fmaj9, em9, dm9, cmaj9 = [57, 60, 64, 67], [55, 59, 62, 66], [53, 57, 60, 64], [52, 55, 59, 62]
    g13, a7 = [53, 57, 59, 64], [55, 57, 61, 64]
    a_part = [(fmaj9, n("F2")), (em9, n("E2")), (dm9, n("D2")), (cmaj9, n("C2"))] * 2
    b_part = [(dm9, n("D2")), (g13, n("G2")), (cmaj9, n("C2")), (a7, n("A2")),
              (dm9, n("D2")), (g13, n("G2")), (cmaj9, n("C2")), (cmaj9, n("C2"))]
    form = a_part + b_part

    for bar, (voicing, root) in enumerate(form):
        last = bar == len(form) - 1
        # 건반: A는 길게, B는 두 번 끊어 친다
        if last:
            for p in voicing:
                s.note(keys, p, bar, 0, 4, 70)
        elif bar < 8:
            for p in voicing:
                s.note(keys, p, bar, 0, 3.5, 68)
        else:
            for p in voicing:
                s.note(keys, p, bar, 0, 1.5, 72)
                s.note(keys, p, bar, 1.5, 2.25, 60)

        # 베이스
        if last:
            s.note(bass, root, bar, 0, 4, 95)
        else:
            s.note(bass, root, bar, 0, 1.25, 100)
            s.note(bass, root, bar, 1.5, 0.5, 80)
            s.note(bass, root + 7, bar, 2.5, 1, 90)
            s.note(bass, root + 12, bar, 3.5, 0.5, 75)

        # 패드는 B에서만 (편곡 변화)
        if bar >= 8:
            for p in (root + 12, root + 19, voicing[-1]):
                s.note(pad, p, bar, 0, 4, 55)

        # 드럼
        if last:
            s.note(drums, KICK, bar, 0, 0.25, 110)
            s.note(drums, CRASH, bar, 0, 2, 100)
            continue
        if bar in (0, 8):
            s.note(drums, CRASH, bar, 0, 2, 100)
        s.note(drums, KICK, bar, 0, 0.25, 110)
        s.note(drums, KICK, bar, 2.5, 0.25, 95)
        if bar % 2 == 1:
            s.note(drums, KICK, bar, 1.75, 0.25, 80)
        s.note(drums, SNARE, bar, 1, 0.25, 100)
        fill = bar in (7, 14)
        if not fill:
            s.note(drums, SNARE, bar, 3, 0.25, 104)
        for i in range(8):
            beat = i * 0.5
            if fill and beat >= 3:
                continue
            if beat == 3.5 and bar % 4 == 3:
                s.note(drums, OPEN_HAT, bar, beat, 0.5, 85)
            else:
                s.note(drums, HAT, bar, beat, 0.25, 82 if i % 2 == 0 else 55)
        if fill:  # 4박째 탐 필인 (16분음표)
            for i, tom in enumerate((TOM_HI, TOM_MID, TOM_LOW, TOM_FLOOR)):
                s.note(drums, tom, bar, 3 + i * 0.25, 0.25, 90 + i * 5)
            s.note(drums, CLAP, bar, 3.75, 0.25, 100)

    # 멜로디: (마디, 박, 길이, 음)
    melody = [
        (0, 0, 1, "E5"), (0, 1, .5, "G5"), (0, 1.5, 1.5, "A5"), (0, 3, .5, "G5"), (0, 3.5, .5, "E5"),
        (1, 0, 1.5, "D5"), (1, 1.5, .5, "B4"), (1, 2, 1, "D5"), (1, 3, 1, "E5"),
        (2, 0, 1, "F5"), (2, 1, .5, "E5"), (2, 1.5, .5, "D5"), (2, 2, 1.5, "C5"), (2, 3.5, .5, "A4"),
        (3, 0, 1, "B4"), (3, 1, 1, "C5"), (3, 2, 2, "G4"),
        (4, 0, 1, "E5"), (4, 1, .5, "G5"), (4, 1.5, 1.5, "A5"), (4, 3, .5, "G5"), (4, 3.5, .5, "E5"),
        (5, 0, 1.5, "D5"), (5, 1.5, .5, "B4"), (5, 2, .5, "D5"), (5, 2.5, .5, "E5"), (5, 3, 1, "G5"),
        (6, 0, 1, "A5"), (6, 1, .5, "G5"), (6, 1.5, .5, "F5"), (6, 2, 1, "E5"), (6, 3, 1, "D5"),
        (7, 0, .5, "D5"), (7, .5, .5, "C5"), (7, 1, 1, "B4"), (7, 2, 2, "C5"),
        # B: 9~12마디는 쉬고 13마디부터
        (12, 0, 2, "A5"), (12, 2, 1, "G5"), (12, 3, 1, "F5"),
        (13, 0, 1.5, "E5"), (13, 1.5, .5, "D5"), (13, 2, 2, "E5"),
        (14, 0, 1, "G5"), (14, 1, 1, "E5"), (14, 2, 1, "D5"), (14, 3, 1, "B4"),
        (15, 0, 4, "C5"),
    ]
    for bar, beat, length, name in melody:
        s.note(lead, n(name), bar, beat, length, 92 if beat == 0 else 84)

    return s.to_bytes()


# ---------- 2. fl_style_loose ----------

def fl_style_loose() -> bytes:
    rng = random.Random(7)  # 고정 시드: 매번 같은 "흔들림"
    s = Song(tempo=120)
    # FL Studio처럼: 악기 번호 전부 0, 드럼도 일반 채널, 이름으로만 구분
    fpc = s.track("FPC")
    chords = s.track("Chords")
    bass = s.track("Bass")
    melody = s.track("Melody")

    def loose(inst, pitch, bar, beat, length, vel):
        jitter = rng.uniform(-0.04, 0.04)  # 120 BPM에서 약 ±20ms
        s.note(inst, pitch, bar, beat + jitter, length * rng.uniform(0.85, 1.0), max(1, min(127, vel + rng.randint(-18, 18))))

    # C - G - Am - F, 2번
    prog = [([60, 64, 67], n("C2")), ([59, 62, 67], n("G1")), ([60, 64, 69], n("A1")), ([60, 65, 69], n("F1"))] * 2
    for bar, (triad, root) in enumerate(prog):
        for beat in (0, 1.5, 3):  # 3-3-2 리듬
            for p in triad:
                loose(chords, p, bar, beat, 1.25 if beat < 3 else 0.75, 85)
        for i in range(8):
            loose(bass, root + (12 if i % 4 == 3 else 0), bar, i * 0.5, 0.45, 95)
        for beat in (0, 2.5):
            loose(fpc, KICK, bar, beat, 0.25, 110)
        for beat in (1, 3):
            loose(fpc, CLAP, bar, beat, 0.25, 105)
        for i in range(16):
            loose(fpc, HAT, bar, i * 0.25, 0.2, 90 if i % 4 == 0 else 65)

    tune = ["E5", "D5", "C5", "D5", "E5", "E5", "E5", None,
            "D5", "D5", "D5", None, "E5", "G5", "G5", None]
    for i, name in enumerate(tune * 2):
        if name:
            loose(melody, n(name), i // 4, (i % 4), 0.9, 95)

    return s.to_bytes()


# ---------- 3. waltz_3_4 ----------

def waltz_3_4() -> bytes:
    s = Song(tempo=150, time_signature=(3, 4))
    rh = s.track("Piano RH", program=0)
    lh = s.track("Piano LH", program=0)

    # G | C | D7 | G | Em | Am | D7 | G   (왼손: 쿵-짝-짝)
    prog = [("G2", [59, 62, 67]), ("C3", [60, 64, 67]), ("D3", [60, 66, 69]), ("G2", [59, 62, 67]),
            ("E2", [59, 64, 67]), ("A2", [60, 64, 69]), ("D3", [60, 66, 69]), ("G2", [59, 62, 67])]
    for bar, (root, chord) in enumerate(prog):
        s.note(lh, n(root), bar, 0, 1, 90)
        if bar < len(prog) - 1:
            for beat in (1, 2):
                for p in chord:
                    s.note(lh, p - 12, bar, beat, 0.8, 62)

    melody = [
        (0, 0, 2, "B4"), (0, 2, 1, "D5"),
        (1, 0, 2, "E5"), (1, 2, 1, "C5"),
        (2, 0, 1, "A4"), (2, 1, 1, "B4"), (2, 2, 1, "C5"),
        (3, 0, 3, "B4"),
        (4, 0, 2, "G4"), (4, 2, 1, "B4"),
        (5, 0, 1, "C5"), (5, 1, 1, "E5"), (5, 2, 1, "C5"),
        (6, 0, 1, "A4"), (6, 1, 1, "F#4"), (6, 2, 1, "A4"),
        (7, 0, 3, "G4"),
    ]
    for bar, beat, length, name in melody:
        s.note(rh, n(name), bar, beat, length, 88 if beat == 0 else 76)

    return s.to_bytes()


# ---------- 4. tempo_change ----------

def tempo_change() -> bytes:
    s = Song(tempo=100)
    piano = s.track("Piano", program=0)
    drums = s.track("Drums", is_drum=True)
    for bar, chord in enumerate([[60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62]] * 2):
        for p in chord:
            s.note(piano, p, bar, 0, 4, 80)
        for beat in range(4):
            s.note(drums, KICK if beat % 2 == 0 else SNARE, bar, beat, 0.25, 105)
            s.note(drums, HAT, bar, beat + 0.5, 0.25, 60)

    # pretty_midi는 템포를 하나만 쓰므로 mido로 5마디(16박)에 템포 이벤트를 끼워 넣는다.
    # 음표는 틱 위치 그대로라 박 위치는 바뀌지 않는다.
    mid = mido.MidiFile(file=io.BytesIO(s.to_bytes()))
    return _insert_tempo(mid, at_tick=mid.ticks_per_beat * 16, bpm=130)


def _insert_tempo(mid: mido.MidiFile, at_tick: int, bpm: float) -> bytes:
    track = mid.tracks[0]
    events, now = [], 0
    for msg in track:
        now += msg.time
        if msg.type != "end_of_track":
            events.append((now, msg))
    events.append((at_tick, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))))
    events.sort(key=lambda e: e[0])

    new, prev = mido.MidiTrack(), 0
    for tick, msg in events:
        new.append(msg.copy(time=tick - prev))
        prev = tick
    new.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks[0] = new

    out = io.BytesIO()
    mid.save(file=out)
    return out.getvalue()


SAMPLES = {
    "lofi_groove.mid": lofi_groove,
    "fl_style_loose.mid": fl_style_loose,
    "waltz_3_4.mid": waltz_3_4,
    "tempo_change.mid": tempo_change,
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for filename, build in SAMPLES.items():
        (OUT / filename).write_bytes(build())
        print(f"samples/{filename}")
