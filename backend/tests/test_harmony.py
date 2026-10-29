import sys
from pathlib import Path

import pytest

from app.harmony import analyze
from app.harmony.analyze import name_chord
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Note, Project, Track

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402


def sample(name: str):
    return analyze(midi_bytes_to_project(make_samples.SAMPLES[f"{name}.mid"]()))


def song(*chords: tuple[list[int], int], beats: float = 4, ts=(4, 4), drums=False) -> Project:
    """(건반 음들, 베이스 음) 마디마다 한 코드."""
    keys, bass, tracks = [], [], []
    for i, (pitches, root) in enumerate(chords):
        keys += [Note(pitch=p, start=i * beats, duration=beats) for p in pitches]
        bass.append(Note(pitch=root, start=i * beats, duration=beats))
    tracks = [Track(id="t1", name="Keys", notes=keys), Track(id="t2", name="Bass", notes=bass)]
    if drums:
        tracks.append(Track(id="t3", name="Drums", is_drum=True, notes=[Note(pitch=36 + i % 10, start=i, duration=0.25) for i in range(16)]))
    return Project(id="p", time_signature=ts, tracks=tracks)


# ---------- 샘플 곡 (정답 = scripts/make_samples.py에 적힌 진행) ----------

def test_lofi_groove_rootless_voicings_and_secondary_dominant():
    a = sample("lofi_groove")
    assert a.key.name == "C major"
    names = [c.name for c in a.chords]
    # 건반은 근음 없이 치고(Fmaj9 = A C E G) 베이스가 근음을 친다 → 베이스까지 봐야 맞게 읽힌다
    assert names == ["Fmaj9", "Em9", "Dm9", "Cmaj9"] * 2 + ["Dm9", "G13", "Cmaj9", "A7", "Dm9", "G13", "Cmaj9"]
    romans = [c.roman for c in a.chords]
    assert romans[:4] == ["IVmaj7", "iii7", "ii7", "Imaj7"]
    assert romans[9:12] == ["V7", "Imaj7", "V7/ii"]  # A7 → Dm9 = ii로 가는 부속 딸림화음
    assert a.chords[11].function == "부속" and a.chords[9].function == "D"
    assert a.chords[-1].end == 64  # 마지막 Cmaj9 두 마디는 하나로 합친다


def test_loose_timing_and_repeated_bass():
    a = sample("fl_style_loose")  # 박자 · 세기가 흔들리고 베이스가 짧게 반복된다
    assert a.key.name == "C major"
    assert [c.name for c in a.chords] == ["C", "G", "Am", "F"] * 2
    assert [c.roman for c in a.chords[:4]] == ["I", "V", "vi", "IV"]
    assert [c.function for c in a.chords[:4]] == ["T", "D", "T", "S"]


def test_waltz_bass_is_the_downbeat_note():
    a = sample("waltz_3_4")  # 왼손 "쿵-짝-짝": 짝 화음(C3)이 쿵(D3)보다 낮아도 첫 박 음이 베이스
    assert a.key.name == "G major"
    assert [c.name for c in a.chords] == ["G", "C", "D7", "G", "Em", "Am", "D7", "G"]
    assert [c.roman for c in a.chords] == ["I", "IV", "V7", "I", "vi", "ii", "V7", "I"]


def test_melody_passing_tones_are_not_extensions():
    # fl_style · waltz의 멜로디 음(6 · 9 · 13)이 코드 이름에 붙지 않는다 (위 두 테스트가 C · D7로 확인)
    a = sample("waltz_3_4")
    assert all(not c.quality.startswith(("6", "9", "13", "add")) for c in a.chords)


# ---------- 코드 이름 ----------

def w(*pcs_weights: tuple[int, float]) -> list[float]:
    out = [0.0] * 12
    for pc, x in pcs_weights:
        out[pc] += x
    return out


def test_chord_names():
    cases = [
        (w((0, 1), (4, 1), (7, 1), (11, 1)), 0, "Cmaj7"),
        (w((11, 1), (2, 1), (5, 1), (9, 1)), 11, "Bm7b5"),
        (w((11, 1), (2, 1), (5, 1), (8, 1)), 11, "Bdim7"),
        (w((7, 1), (0, 1), (2, 1)), 7, "Gsus4"),
        (w((0, 1), (4, 1), (8, 1)), 0, "Caug"),
        (w((0, 1), (4, 1), (7, 1)), 4, "C/E"),  # 베이스가 3음 → 슬래시 코드
        (w((9, 1), (0, 1), (4, 1), (7, 1)), 9, "Am7"),
        (w((7, 1), (11, 1), (2, 1), (5, 1)), 7, "G7"),
    ]
    for weights, bass, want in cases:
        assert name_chord(weights, bass, flats=False)[1] == want, want
    assert name_chord([0.0] * 12, None, flats=False)[1] == "N.C."
    assert name_chord(w((10, 1), (2, 1), (5, 1)), 10, flats=True)[1] == "Bb"  # 플랫 조에서는 Bb


# ---------- 단조 · 한 마디에 두 코드 · 드럼 ----------

def test_minor_key_with_harmonic_dominant():
    a = analyze(song(([57, 60, 64], 45), ([57, 62, 65], 50), ([56, 59, 62, 64], 52), ([57, 60, 64], 45), drums=True))
    assert a.key.name == "A minor"
    assert [c.name for c in a.chords] == ["Am", "Dm", "E7", "Am"]
    assert [c.roman for c in a.chords] == ["i", "iv", "V7", "i"]
    assert [c.function for c in a.chords] == ["T", "S", "D", "T"]


II_V_I_LOOP = [([65, 69, 72, 76], 50), ([65, 69, 71, 74], 43), ([64, 67, 71, 74], 48), ([61, 64, 67, 69], 45)]  # Dm9 G9 Cmaj9 A7


@pytest.mark.parametrize("times", [1, 2])
def test_loop_starting_on_ii_is_read_from_its_cadence(times):
    # 첫 코드가 Dm9라도 ii–V7–I가 있는 C major. 두 번 돌면 A7 → Dm9(V7 → i)도 생기지만 그 앞이 버금딸림이 아니다
    a = analyze(song(*II_V_I_LOOP * times))
    assert a.key.name == "C major"
    assert [c.name for c in a.chords] == ["Dm9", "G9", "Cmaj9", "A7"] * times


def test_cadence_needs_predominant_and_dominant_seventh():
    from app.harmony.analyze import cadences

    def spans(*names):
        return analyze(song(*[{"Dm": ([62, 65, 69], 50), "G": ([62, 67, 71], 43), "G7": ([65, 67, 71], 43),
                                "C": ([64, 67, 72], 48), "Am": ([64, 69, 72], 45)}[n] for n in names])).chords

    assert cadences(spans("Dm", "G7", "C"), 0, "major") == 0.5  # 바뀜 2번 중 ii–V7–I 하나
    assert cadences(spans("Dm", "G", "C"), 0, "major") == 0  # 7음 없는 V
    assert cadences(spans("Am", "G7", "C"), 0, "major") == 0  # V7 앞이 버금딸림이 아님


def test_two_chords_in_one_bar():
    keys = [Note(pitch=p, start=0, duration=2) for p in (60, 64, 67)] + [Note(pitch=p, start=2, duration=2) for p in (59, 62, 67)]
    keys += [Note(pitch=p, start=4, duration=4) for p in (60, 64, 67)]
    bass = [Note(pitch=48, start=0, duration=2), Note(pitch=43, start=2, duration=2), Note(pitch=48, start=4, duration=4)]
    a = analyze(Project(id="p", tracks=[Track(id="t1", name="Keys", notes=keys), Track(id="t2", name="Bass", notes=bass)]))
    assert [(c.name, c.start, c.end) for c in a.chords] == [("C", 0, 2), ("G", 2, 4), ("C", 4, 8)]


def test_empty_and_drum_only():
    assert analyze(Project(id="p", tracks=[])).chords == []
    drums = Track(id="t1", name="Drums", is_drum=True, notes=[Note(pitch=36, start=0, duration=1)])
    assert analyze(Project(id="p", tracks=[drums])).chords == []


def test_harmony_endpoint(client):
    from app.store.memory import store
    from app.tools import run_tool
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    r = client.get(f"/api/v1/projects/{pid}/harmony").json()
    assert r["key"]["name"] == "C major" and "name_ko" not in r["key"]
    assert r["chords"][0] == {"start": 0.0, "end": 4.0, "name": "Fmaj9", "roman": "IVmaj7", "function": "S"}
    # 미리보기(모든 트랙 2반음 위)를 분석하면 D major
    store.set_preview(pid, run_tool(store.current(pid), "transpose", {"semitones": 2}).project, "올림")
    assert client.get(f"/api/v1/projects/{pid}/harmony", params={"preview": True}).json()["key"]["name"] == "D major"
    assert client.get(f"/api/v1/projects/{pid}/harmony").json()["key"]["name"] == "C major"
    assert client.get("/api/v1/projects/nope/harmony").status_code == 404


# ---------- analyze_harmony 도구 ----------

def test_analyze_harmony_tool():
    from app.tools import ToolError, run_tool

    lofi = midi_bytes_to_project(make_samples.SAMPLES["lofi_groove.mid"]())
    r = run_tool(lofi, "analyze_harmony")
    assert r.project is None and r.changed_notes == 0  # 읽기만
    assert r.summary == "조성 C major · 곡 전체 코드 15개"
    assert r.data["key"] == "C major" and r.data["other_keys"]
    assert r.data["chords"][0] == "1마디 Fmaj9 (IVmaj7, 서브도미넌트)"
    assert r.data["chords"][11] == "12마디 A7 (V7/ii, 부속 딸림화음)"

    # 마디 범위: 9~12마디 코드만 (조성은 곡 전체로)
    part = run_tool(lofi, "analyze_harmony", {"bars": [9, 12]})
    assert part.data["progression"] == "Dm9 → G13 → Cmaj9 → A7" and part.data["key"] == "C major"
    assert part.summary == "조성 C major · 9~12마디 코드 4개"
    # 박 범위 (화면에서 고른 부분): 마지막 Cmaj9는 15~16마디 하나로 합쳐 있어 16마디만 골라도 나온다
    assert run_tool(lofi, "analyze_harmony", {"beats": [60, 64]}).data["progression"] == "Cmaj9"

    with pytest.raises(ToolError, match="16마디"):
        run_tool(lofi, "analyze_harmony", {"bars": [20, 24]})
    with pytest.raises(ToolError):
        run_tool(lofi, "analyze_harmony", {"bars": [1, 2], "beats": [0, 4]})
    with pytest.raises(ToolError):  # 화성은 모든 트랙을 함께 보므로 트랙을 고르지 않는다
        run_tool(lofi, "analyze_harmony", {"track_ids": ["t2"]})

    drums = Project(id="p", tracks=[Track(id="t1", name="Drums", is_drum=True, notes=[Note(pitch=36, start=0, duration=1)])])
    assert run_tool(drums, "analyze_harmony").data == {"key": None, "chords": []}


def test_agent_answers_from_analysis():
    from app.agent.loop import run_agent
    from tests.test_agent import FakeLLM, calls, say

    lofi = midi_bytes_to_project(make_samples.SAMPLES["lofi_groove.mid"]())
    llm = FakeLLM(calls(("analyze_harmony", {})), say("C major예요."))
    r = run_agent(lofi, "무슨 키야?", llm)
    assert r.draft is None and r.steps[0].ok  # 미리보기를 만들지 않는다
    assert r.steps[0].summary.startswith("조성 C major")


# ---------- 펼침화음 · 자리바꿈 (eval/harmony.py에서 찾은 약점) ----------

def test_arpeggio_is_harmony_not_melody():
    # 한 줄로 8분음표만 짚는 펼침화음 G-Bb-C-E…: 멜로디로 보면 Bb · E가 빠져 C로 읽혔다
    seq = [55, 58, 60, 64, 60, 58, 55, 58]
    keys = [Note(pitch=p, start=i * 0.5, duration=0.5) for i, p in enumerate(seq)]
    bass = [Note(pitch=36, start=0, duration=4)]
    a = analyze(Project(id="p", tracks=[Track(id="t1", name="Keys", notes=keys), Track(id="t2", name="Bass", notes=bass)]))
    assert [c.name for c in a.chords] == ["C7"]


def test_leaping_melody_with_varied_rhythm_stays_melody():
    # 코드음을 따라 뛰어도 리듬이 들쭉날쭉하면 멜로디 → 지나가는 음(A = 6음)이 이름에 붙지 않는다
    lead = [Note(pitch=p, start=s, duration=d) for p, s, d in [(72, 0, 1.5), (76, 1.5, 0.5), (69, 2, 1), (79, 3, 1)]]
    a = analyze(Project(id="p", tracks=[
        Track(id="t1", name="Keys", notes=[Note(pitch=p, start=0, duration=4) for p in (60, 64, 67)]),
        Track(id="t2", name="Bass", notes=[Note(pitch=36, start=0, duration=4)]),
        Track(id="t3", name="Lead", notes=lead),
    ]))
    assert [c.name for c in a.chords] == ["C"]


def test_major_seventh_first_inversion():
    # E-G-B-C: 베이스 E를 근음으로 보면 C가 b6 → Cmaj7/E로 읽는다 (예전에는 Em)
    a = analyze(Project(id="p", tracks=[Track(id="t1", name="Keys", notes=[Note(pitch=p, start=0, duration=4) for p in (52, 55, 59, 60)])]))
    assert a.chords[0].name == "Cmaj7/E"
