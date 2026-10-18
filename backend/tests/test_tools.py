"""편집 도구 단위 테스트. 샘플은 scripts/make_samples.py로 만든다 (파일에 의존하지 않음)."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Note, Project, Track
from app.tools import TOOLS, ToolError, run_tool, tool_specs
from app.tools.edits import (
    AdjustVelocityArgs,
    QuantizeArgs,
    ShiftOctaveArgs,
    SwingArgs,
    TransposeArgs,
    adjust_velocity,
    quantize,
    shift_octave,
    swing,
    transpose,
)
from app.tools.info import get_project_info

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402


@pytest.fixture(scope="module")
def lofi() -> Project:
    return midi_bytes_to_project(make_samples.lofi_groove())


@pytest.fixture(scope="module")
def loose() -> Project:
    return midi_bytes_to_project(make_samples.fl_style_loose())


def song(*tracks: Track, ts: tuple[int, int] = (4, 4)) -> Project:
    return Project(id="p", tracks=list(tracks), time_signature=ts)


def notes(*specs) -> list[Note]:
    """(pitch, start, duration, velocity) 튜플로 음 목록 만들기."""
    return [Note(pitch=p, start=s, duration=d, velocity=v) for p, s, d, v in specs]


def track(tid: str, *specs, name: str | None = None, drum: bool = False) -> Track:
    return Track(id=tid, name=name or tid, is_drum=drum, notes=notes(*specs))


def by_track(p: Project, tid: str) -> list[Note]:
    return next(t for t in p.tracks if t.id == tid).notes


# ---------- transpose / shift_octave ----------


def test_transpose_returns_new_project_and_keeps_input(lofi):
    before = lofi.model_dump()
    r = transpose(lofi, TransposeArgs(semitones=2, track_ids=["t2"]))
    assert lofi.model_dump() == before  # 원본 그대로
    assert r.project is not lofi and r.project.version == lofi.version  # 버전은 저장소가 올린다
    old, new = by_track(lofi, "t2"), by_track(r.project, "t2")
    assert [n.pitch + 2 for n in old] == [n.pitch for n in new]
    assert r.changed_notes == len(old)
    assert r.summary == f"Bass 트랙 {len(old)}개 음을 2반음 올렸어요."
    assert by_track(r.project, "t3") == by_track(lofi, "t3")  # 고르지 않은 트랙은 그대로


def test_transpose_skips_drums(lofi):
    r = transpose(lofi, TransposeArgs(semitones=-3))
    assert by_track(r.project, "t1") == by_track(lofi, "t1")
    assert "드럼" not in r.summary  # 전체를 고른 경우엔 조용히 건너뛴다

    r = transpose(lofi, TransposeArgs(semitones=2, track_ids=["t1", "t2"]))
    assert by_track(r.project, "t1") == by_track(lofi, "t1")
    assert r.changed_notes == len(by_track(lofi, "t2"))
    assert "드럼 트랙(Drums)" in r.summary and "건너뛰었어요" in r.summary


def test_transpose_only_drum_changes_nothing(lofi):
    r = transpose(lofi, TransposeArgs(semitones=5, track_ids=["t1"]))
    assert r.changed_notes == 0
    assert r.project == lofi
    assert "바뀐 음이 없어요" in r.summary and "드럼" in r.summary


def test_transpose_out_of_range_raises_without_change():
    p = song(track("t1", (60, 0, 1, 80), (120, 1, 1, 80)))
    before = p.model_dump()
    with pytest.raises(ToolError) as e:
        transpose(p, TransposeArgs(semitones=12))
    assert e.value.code == "out_of_range"
    assert "+7" in e.value.message  # 127 - 120 = 7반음까지 가능
    assert p.model_dump() == before
    # 높은 음을 빼고 고르면 된다
    r = transpose(p, TransposeArgs(semitones=12, pitches=[60]))
    assert [n.pitch for n in by_track(r.project, "t1")] == [72, 120]


def test_shift_octave(lofi):
    r = shift_octave(lofi, ShiftOctaveArgs(octaves=-1, track_ids=["t5"]))
    assert [n.pitch - 12 for n in by_track(lofi, "t5")] == [n.pitch for n in by_track(r.project, "t5")]
    assert "1옥타브 내렸어요" in r.summary
    with pytest.raises(ToolError):
        shift_octave(song(track("t1", (100, 0, 1, 80))), ShiftOctaveArgs(octaves=3))


# ---------- 선택 ----------


def test_selection_bars_and_pitches(lofi):
    # 2~3마디(4~12박)의 닫힌 하이햇만
    r = adjust_velocity(lofi, AdjustVelocityArgs(mode="set", value=1, track_ids=["t1"], bars=(2, 3), pitches=[42]))
    for old, new in zip(by_track(lofi, "t1"), by_track(r.project, "t1")):
        picked = old.pitch == 42 and 4 <= old.start < 12
        assert new.velocity == (1 if picked else old.velocity)
    assert r.changed_notes == sum(1 for n in by_track(lofi, "t1") if n.pitch == 42 and 4 <= n.start < 12)


def test_bars_follow_time_signature():
    # 3/4 박자: 2마디 = 3~6박
    p = song(track("t1", (60, 2.9, 1, 80), (60, 3, 1, 80), (60, 5.9, 1, 80), (60, 6, 1, 80)), ts=(3, 4))
    r = transpose(p, TransposeArgs(semitones=1, bars=(2, 2)))
    assert [n.pitch for n in by_track(r.project, "t1")] == [60, 61, 61, 60]


def test_empty_selection_is_not_an_error(lofi):
    r = transpose(lofi, TransposeArgs(semitones=2, bars=(50, 60)))
    assert r.changed_notes == 0 and r.project == lofi
    assert r.summary == "선택한 범위에서 바뀐 음이 없어요."


def test_unknown_track_lists_valid_ids(lofi):
    with pytest.raises(ToolError) as e:
        transpose(lofi, TransposeArgs(semitones=1, track_ids=["t9"]))
    assert e.value.code == "unknown_track"
    assert "t9" in e.value.message and "t2(Bass)" in e.value.message


# ---------- quantize ----------


def test_quantize_full_strength(loose):
    r = quantize(loose, QuantizeArgs(grid=0.25))
    starts = [n.start for t in r.project.tracks for n in t.notes]
    assert all(abs(s * 4 - round(s * 4)) < 1e-6 for s in starts)
    assert min(starts) >= 0
    # 길이는 그대로 (음 순서가 바뀔 수 있어 정렬해서 비교)
    for t_old, t_new in zip(loose.tracks, r.project.tracks):
        assert sorted(n.duration for n in t_old.notes) == sorted(n.duration for n in t_new.notes)
    assert "16분음표 격자" in r.summary


def test_quantize_partial_strength_halves_distance():
    p = song(track("t1", (60, 0.1, 0.5, 80), (60, 0.9, 0.5, 80)))
    r = quantize(p, QuantizeArgs(grid=0.5, strength=0.5))
    assert [n.start for n in by_track(r.project, "t1")] == pytest.approx([0.05, 0.95])
    assert "강도 50%" in r.summary


def test_quantize_triplet_grid():
    p = song(track("t1", (60, 0.3, 0.2, 80), (60, 0.7, 0.2, 80), (60, 1.02, 0.2, 80)))
    r = quantize(p, QuantizeArgs(grid=0.3333))  # 1/3에 가까운 값이면 셋잇단으로 받는다
    assert [n.start for n in by_track(r.project, "t1")] == pytest.approx([1 / 3, 2 / 3, 1], abs=1e-4)
    assert "8분음표 셋잇단" in r.summary


def test_quantize_ends_keeps_positive_duration():
    p = song(track("t1", (60, 0.02, 0.4, 80), (62, 1.01, 0.08, 80)))
    r = quantize(p, QuantizeArgs(grid=0.25, quantize_ends=True))
    a, b = by_track(r.project, "t1")
    assert (a.start, a.duration) == pytest.approx((0, 0.5))
    assert (b.start, b.duration) == pytest.approx((1, 0.25))  # 끝이 시작과 같은 칸이 되면 한 칸 길이


def test_quantize_already_on_grid_changes_nothing(lofi):
    r = quantize(lofi, QuantizeArgs(grid=0.25))
    assert r.changed_notes == 0 and r.project == lofi
    assert "이미 격자에 맞아" in r.summary


# ---------- adjust_velocity ----------


@pytest.mark.parametrize(
    "mode, value, expected",
    [
        ("scale", 0.5, [5, 50, 64]),  # 63.5는 올림
        ("scale", 2.0, [20, 127, 127]),  # 127에서 잘림
        ("scale", 0.1, [1, 10, 13]),  # 1 아래로 안 내려감
        ("offset", -20, [1, 80, 107]),
        ("offset", 50, [60, 127, 127]),
        ("set", 127, [127, 127, 127]),
        ("set", 1, [1, 1, 1]),
    ],
)
def test_velocity_modes_clamp(mode, value, expected):
    p = song(track("t1", (60, 0, 1, 10), (60, 1, 1, 100), (60, 2, 1, 127)))
    r = adjust_velocity(p, AdjustVelocityArgs(mode=mode, value=value))
    assert [n.velocity for n in by_track(r.project, "t1")] == expected
    assert [n.velocity for n in by_track(p, "t1")] == [10, 100, 127]


def test_velocity_summary(lofi):
    r = adjust_velocity(lofi, AdjustVelocityArgs(mode="scale", value=0.7, track_ids=["t2"]))
    assert r.summary.startswith("Bass 트랙") and "세기를 70%로 줄였어요" in r.summary


# ---------- swing ----------


def test_swing_moves_only_offbeats(lofi):
    r = swing(lofi, SwingArgs(percent=60, grid=0.5, track_ids=["t1"], pitches=[42]))
    delay = (0.6 * 2 - 1) * 0.5  # 0.1박
    old_hats = [n for n in by_track(lofi, "t1") if n.pitch == 42]
    new_hats = [n for n in by_track(r.project, "t1") if n.pitch == 42]
    for old, new in zip(old_hats, new_hats):
        offbeat = round(old.start / 0.5) % 2 == 1
        assert new.start == pytest.approx(old.start + (delay if offbeat else 0))
        assert new.duration == old.duration
    assert r.changed_notes == sum(1 for n in old_hats if round(n.start / 0.5) % 2 == 1) > 0
    # 킥 · 스네어(다른 음 번호)는 그대로
    assert [n for n in by_track(r.project, "t1") if n.pitch != 42] == [n for n in by_track(lofi, "t1") if n.pitch != 42]


def test_swing_16th_grid():
    p = song(track("t1", *[(42, i * 0.25, 0.2, 80) for i in range(8)]))
    r = swing(p, SwingArgs(percent=75, grid=0.25))
    assert [n.start for n in by_track(r.project, "t1")] == pytest.approx(
        [0, 0.375, 0.5, 0.875, 1, 1.375, 1.5, 1.875]
    )


def test_swing_tolerance():
    # 뒷박에서 0.02박 안쪽만 뒷박으로 본다
    p = song(track("t1", (42, 0.515, 0.2, 80), (42, 1.53, 0.2, 80)))
    r = swing(p, SwingArgs(percent=60))
    assert [n.start for n in by_track(r.project, "t1")] == pytest.approx([0.615, 1.53])


def test_swing_50_is_noop(lofi):
    r = swing(lofi, SwingArgs(percent=50))
    assert r.changed_notes == 0 and r.project == lofi
    assert "50%" in r.summary


# ---------- get_project_info ----------


def test_project_info(lofi):
    r = get_project_info(lofi)
    assert r.project is None and r.changed_notes == 0
    assert r.data["bar_count"] == 16
    assert r.data["tempo"] == pytest.approx(84, abs=0.01)
    assert r.data["time_signature"] == [4, 4]
    bass = next(t for t in r.data["tracks"] if t["name"] == "Bass")
    assert bass["pitch_range"] == [min(n.pitch for n in by_track(lofi, "t2")), max(n.pitch for n in by_track(lofi, "t2"))]
    assert "84 BPM" in r.summary and "16마디" in r.summary and "t1 Drums (드럼)" in r.summary
    json.dumps(r.data)  # LLM에 그대로 넘길 수 있어야 한다


# ---------- 등록 · run_tool ----------


def test_registry_has_all_tools_with_schemas():
    assert set(TOOLS) == {
        "transpose", "shift_octave", "quantize", "adjust_velocity", "swing", "get_project_info", "set_tempo", "set_instrument",
        "delete_notes", "set_length", "copy_bars", "humanize", "velocity_ramp", "set_mix", "duplicate_track", "set_drum_sound",
    }
    specs = tool_specs()
    for spec in specs:
        schema = spec["input_schema"]
        assert schema["type"] == "object" and spec["description"]
        json.dumps(schema)
    transpose_schema = next(s for s in specs if s["name"] == "transpose")["input_schema"]
    assert transpose_schema["properties"]["semitones"]["maximum"] == 24
    assert transpose_schema["required"] == ["semitones"]
    assert transpose_schema["additionalProperties"] is False


def test_run_tool_runs(lofi):
    r = run_tool(lofi, "shift_octave", {"octaves": 1, "track_ids": ["t2"], "bars": [1, 4]})
    assert r.changed_notes > 0 and "1옥타브 올렸어요" in r.summary


@pytest.mark.parametrize(
    "name, args, field",
    [
        ("transpose", {"semitones": 100}, "semitones"),
        ("transpose", {}, "semitones"),
        ("transpose", {"semitone": 2}, "semitone"),  # 오타는 무시하지 않고 오류
        ("quantize", {"grid": 0.3}, "grid"),
        ("quantize", {"strength": 1.5}, "strength"),
        ("swing", {"percent": 80}, "percent"),
        ("swing", {"percent": 60, "grid": 1}, "grid"),
        ("adjust_velocity", {"mode": "set", "value": 200}, "1~127"),
        ("adjust_velocity", {"mode": "louder", "value": 1}, "mode"),
        ("transpose", {"semitones": 1, "bars": [4, 2]}, "bars"),
        ("transpose", {"semitones": 1, "pitches": [200]}, "pitches"),
    ],
)
def test_run_tool_rejects_bad_args(lofi, name, args, field):
    with pytest.raises(ToolError) as e:
        run_tool(lofi, name, args)
    assert e.value.code == "invalid_args"
    assert name in e.value.message and field in e.value.message


def test_run_tool_unknown_tool(lofi):
    with pytest.raises(ToolError) as e:
        run_tool(lofi, "reverse", {})
    assert e.value.code == "unknown_tool" and "transpose" in e.value.message


def test_tool_error_api_format():
    from app.main import tool_error_format

    res = asyncio.run(tool_error_format(None, ToolError("없는 트랙 id예요: t9", code="unknown_track")))
    assert res.status_code == 400
    assert json.loads(res.body) == {"error": {"code": "unknown_track", "message": "없는 트랙 id예요: t9"}}


# ---------- set_tempo ----------

def test_set_tempo_modes_keep_notes():
    from app.tools import run_tool

    p = midi_bytes_to_project(make_samples.lofi_groove())
    for args, want in [({"mode": "set", "value": 100}, 100), ({"mode": "offset", "value": -4}, 80), ({"mode": "scale", "value": 1.5}, 126)]:
        r = run_tool(p, "set_tempo", args)
        assert r.project.tempo == pytest.approx(want, abs=0.01)
        assert r.changed_settings and r.changed_notes == 0
        assert r.project.tracks == p.tracks  # 음표(박 위치)는 그대로
    assert p.tempo == pytest.approx(84, abs=0.01)  # 원본은 그대로


def test_set_tempo_limits():
    from app.tools import ToolError, run_tool

    p = midi_bytes_to_project(make_samples.lofi_groove())
    with pytest.raises(ToolError) as e:
        run_tool(p, "set_tempo", {"mode": "scale", "value": 4})  # 84 x 4 = 336 > 300
    assert e.value.code == "out_of_range"
    with pytest.raises(ToolError):
        run_tool(p, "set_tempo", {"mode": "set", "value": 1000})
    same = run_tool(p, "set_tempo", {"mode": "offset", "value": 0})
    assert not same.changed_settings
    assert "84 → 100 BPM" in run_tool(p, "set_tempo", {"mode": "set", "value": 100}).summary  # 84.0001이 아니라 84


def test_tempo_only_change_makes_a_preview():
    from app.agent.llm import LLMReply, ToolCall
    from app.agent.loop import run_agent
    from tests.test_agent import FakeLLM

    p = midi_bytes_to_project(make_samples.lofi_groove())
    llm = FakeLLM(LLMReply(text="", tool_calls=[ToolCall("c0", "set_tempo", '{"mode": "set", "value": 100}')]), LLMReply(text="바꿨어요."))
    r = run_agent(p, "템포 100으로", llm)
    assert r.draft is not None and r.draft.tempo == 100 and "100 BPM" in r.label


# ---------- set_instrument ----------

def test_set_instrument_changes_program_only():
    p = song(track("t1", (60, 0, 1, 80), name="Keys"), track("t2", (36, 0, 1, 80), name="Drums", drum=True))
    r = run_tool(p, "set_instrument", {"track_ids": ["t1", "t2"], "program": 4})
    keys = r.project.tracks[0]
    assert (keys.program, keys.program_set) == (4, True)
    assert keys.notes == p.tracks[0].notes and r.changed_settings and r.changed_notes == 0
    assert r.project.tracks[1] == p.tracks[1]  # 드럼은 그대로
    assert "Electric Piano 1" in r.summary and "건너뛰었어요" in r.summary


def test_set_instrument_errors_and_noop():
    p = song(track("t1", (60, 0, 1, 80)), track("t2", (36, 0, 1, 80), drum=True))
    with pytest.raises(ToolError) as e:
        run_tool(p, "set_instrument", {"track_ids": ["t2"], "program": 4})
    assert e.value.code == "drum_track"
    with pytest.raises(ToolError) as e:
        run_tool(p, "set_instrument", {"track_ids": ["t9"], "program": 4})
    assert e.value.code == "unknown_track"
    with pytest.raises(ToolError):
        run_tool(p, "set_instrument", {"track_ids": ["t1"], "program": 128})
    # 지정 안 된 0을 피아노(0)로 고르면 바뀐 것 (이름으로 짐작하지 않게 표시)
    chosen = run_tool(p, "set_instrument", {"track_ids": ["t1"], "program": 0})
    assert chosen.changed_settings and chosen.project.tracks[0].program_set
    again = run_tool(chosen.project, "set_instrument", {"track_ids": ["t1"], "program": 0})
    assert not again.changed_settings and "바뀐 게 없어요" in again.summary


def test_set_instrument_survives_export(lofi):
    from app.midi_io.convert import project_to_midi_bytes

    r = run_tool(lofi, "set_instrument", {"track_ids": ["t2"], "program": 38})
    back = midi_bytes_to_project(project_to_midi_bytes(r.project))
    assert next(t for t in back.tracks if t.name == r.project.tracks[1].name).program == 38


def test_instrument_endpoint_makes_version_and_keeps_preview(client):
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    from app.store.memory import store

    edited = run_tool(store.current(pid), "transpose", {"track_ids": ["t2"], "semitones": 2}).project
    store.set_preview(pid, edited, "베이스 2키 올림")

    r = client.post(f"/api/v1/projects/{pid}/tracks/t2/instrument", json={"program": 38})
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["version"] == 2 and body["project"]["tracks"][1]["program"] == 38
    assert body["preview"]["tracks"][1]["program"] == 38  # 미리보기에도 들어감
    assert body["preview"]["tracks"][1]["notes"] == [n.model_dump() for n in edited.tracks[1].notes]
    applied = client.post(f"/api/v1/projects/{pid}/preview/apply")
    assert applied.status_code == 200 and applied.json()["tracks"][1]["program"] == 38  # 충돌 없이 적용

    assert client.post(f"/api/v1/projects/{pid}/tracks/t9/instrument", json={"program": 1}).status_code == 400


# ---------- delete_notes ----------

def test_delete_notes_by_bars_and_pitches():
    drums = track("t1", (36, 0, 0.5, 90), (42, 0, 0.5, 70), (42, 4, 0.5, 70), (38, 5, 0.5, 90), drum=True, name="Drums")
    p = song(drums, track("t2", (40, 0, 1, 80), (40, 4, 1, 80), name="Bass"))
    r = run_tool(p, "delete_notes", {"track_ids": ["t1"], "pitches": [42]})
    assert [n.pitch for n in by_track(r.project, "t1")] == [36, 38] and r.changed_notes == 2
    r = run_tool(p, "delete_notes", {"bars": [2, 2]})  # 2마디의 모든 트랙
    assert [n.start for n in by_track(r.project, "t1")] == [0, 0] and [n.start for n in by_track(r.project, "t2")] == [0]
    assert "2마디" in r.summary
    nothing = run_tool(p, "delete_notes", {"bars": [9, 9]})
    assert nothing.changed_notes == 0
    with pytest.raises(ToolError):
        run_tool(p, "delete_notes", {})  # 곡 전체는 막음


# ---------- set_length ----------

def test_set_length_modes():
    p = song(track("t1", (60, 0, 1, 80), (64, 0, 1, 80), (67, 2, 0.5, 80), (72, 3, 2, 80)), track("t2", (36, 0, 0.25, 90), drum=True))
    half = run_tool(p, "set_length", {"mode": "scale", "value": 0.5})
    assert [n.duration for n in by_track(half.project, "t1")] == [0.5, 0.5, 0.25, 1]
    assert by_track(half.project, "t2") == by_track(p, "t2")  # 드럼은 그대로
    legato = run_tool(p, "set_length", {"mode": "legato", "track_ids": ["t1"]})
    # 화음(0박) 두 음은 다음 음(2박)까지, 2박 음은 3박까지, 마지막 음은 그대로
    assert [n.duration for n in by_track(legato.project, "t1")] == [2, 2, 1, 2]
    fixed = run_tool(p, "set_length", {"mode": "set", "value": 0.25, "track_ids": ["t1"], "bars": [1, 1]})
    assert {n.duration for n in by_track(fixed.project, "t1")} == {0.25}
    with pytest.raises(ToolError):
        run_tool(p, "set_length", {"mode": "scale"})  # value 빠짐
    with pytest.raises(ToolError):
        run_tool(p, "set_length", {"mode": "set", "value": 0})


# ---------- copy_bars ----------

def test_copy_bars_repeat_and_overwrite():
    p = song(track("t1", (60, 0, 1, 80), (62, 4, 1, 80), (99, 8, 1, 80), (98, 13, 1, 80)), track("t2", (40, 0, 4, 80)))
    r = run_tool(p, "copy_bars", {"track_ids": ["t1"], "bars": [1, 2], "to_bar": 3, "times": 2})
    got = [(n.pitch, n.start) for n in by_track(r.project, "t1")]
    # 3~6마디(8~23박)에 있던 음(99, 98)은 지우고 1~2마디를 두 번 붙인다
    assert got == [(60, 0), (62, 4), (60, 8), (62, 12), (60, 16), (62, 20)]
    assert by_track(r.project, "t2") == by_track(p, "t2") and r.project.bar_count == 6
    merged = run_tool(p, "copy_bars", {"bars": [1, 1], "to_bar": 3, "overwrite": False})
    assert (99, 8) in [(n.pitch, n.start) for n in by_track(merged.project, "t1")]
    assert [n.start for n in by_track(merged.project, "t2")] == [0, 8]  # 트랙을 안 정하면 모든 트랙
    with pytest.raises(ToolError) as e:
        run_tool(p, "copy_bars", {"bars": [1, 4], "to_bar": 3})
    assert e.value.code == "overlap" and "to_bar를 5" in e.value.message
    with pytest.raises(ToolError):
        run_tool(p, "copy_bars", {"bars": [1, 1], "to_bar": 600})


def test_copy_bars_in_three_four():
    p = song(track("t1", (60, 0, 1, 80), (62, 2, 1, 80)), ts=(3, 4))
    r = run_tool(p, "copy_bars", {"bars": [1, 1], "to_bar": 2})
    assert [n.start for n in by_track(r.project, "t1")] == [0, 2, 3, 5]


# ---------- humanize ----------

def test_humanize_is_small_and_repeatable():
    p = song(track("t1", *[(60, i * 0.5, 0.5, 80) for i in range(32)]))
    a = run_tool(p, "humanize", {"timing": 0.02, "velocity": 10})
    b = run_tool(p, "humanize", {"timing": 0.02, "velocity": 10})
    assert a.project == b.project  # 같은 seed면 같은 결과
    moved = list(zip(by_track(p, "t1"), by_track(a.project, "t1")))
    assert all(abs(x.start - y.start) <= 0.02 + 1e-9 and abs(x.velocity - y.velocity) <= 10 for x, y in moved)
    assert a.changed_notes > 20
    other = run_tool(p, "humanize", {"timing": 0.02, "velocity": 10, "seed": 7})
    assert other.project != a.project
    assert run_tool(p, "humanize", {"timing": 0, "velocity": 0}).changed_notes == 0
    first = run_tool(song(track("t1", (60, 0, 1, 80))), "humanize", {"timing": 0.08, "seed": 3})
    assert by_track(first.project, "t1")[0].start >= 0  # 곡 앞으로 나가지 않음


# ---------- velocity_ramp ----------

def test_velocity_ramp_over_bars():
    p = song(track("t1", *[(60, b * 4, 1, 100) for b in range(4)]))  # 1~4마디 첫 박
    r = run_tool(p, "velocity_ramp", {"bars": [1, 4], "start": 1, "end": 0.5})
    # 범위는 0~16박: 0 → 100%, 4 → 87.5%, 8 → 75%, 12 → 62.5%
    assert [n.velocity for n in by_track(r.project, "t1")] == [100, 88, 75, 63]
    assert "점점 여리게" in r.summary
    up = run_tool(p, "velocity_ramp", {"start": 0.5, "end": 1})  # bars 없으면 첫 음 ~ 마지막 음
    assert [n.velocity for n in by_track(up.project, "t1")] == [50, 67, 83, 100]
    assert run_tool(p, "velocity_ramp", {"bars": [9, 9], "start": 1, "end": 0.5}).changed_notes == 0


# ---------- set_mix ----------

def test_set_mix_volume_and_pan():
    p = song(track("t1", (60, 0, 1, 80), name="Pad"), track("t2", (36, 0, 1, 80), drum=True, name="Drums"))
    r = run_tool(p, "set_mix", {"track_ids": ["t1"], "volume_offset": -20, "pan": -30})
    pad = r.project.tracks[0]
    assert (pad.volume, pad.pan) == (80, -30) and pad.notes == p.tracks[0].notes
    assert r.changed_settings and "볼륨 100 → 80" in r.summary and "왼쪽 30" in r.summary
    drums = run_tool(p, "set_mix", {"track_ids": ["t2"], "volume": 127})  # 드럼도 볼륨은 바꿀 수 있음
    assert drums.project.tracks[1].volume == 127
    clipped = run_tool(p, "set_mix", {"track_ids": ["t1"], "volume_offset": -127})
    assert clipped.project.tracks[0].volume == 0
    same = run_tool(p, "set_mix", {"track_ids": ["t1"], "volume": 100})
    assert not same.changed_settings
    for bad in ({"track_ids": ["t1"]}, {"track_ids": ["t1"], "volume": 90, "volume_offset": 5}, {"track_ids": ["t1"], "pan": 64}):
        with pytest.raises(ToolError):
            run_tool(p, "set_mix", bad)


def test_mix_survives_export():
    from app.midi_io.convert import project_to_midi_bytes

    p = song(track("t1", (60, 0, 1, 80), name="Pad"), track("t2", (40, 0, 1, 80), name="Bass"))
    mixed = run_tool(p, "set_mix", {"track_ids": ["t1"], "volume": 70, "pan": 40}).project
    back = midi_bytes_to_project(project_to_midi_bytes(mixed))
    assert [(t.volume, t.pan) for t in back.tracks] == [(70, 40), (100, 0)]


def test_mix_endpoint(client):
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    r = client.post(f"/api/v1/projects/{pid}/tracks/t4/mix", json={"volume": 60, "pan": -20})
    assert r.status_code == 200
    t4 = r.json()["project"]["tracks"][3]
    assert (t4["volume"], t4["pan"], r.json()["project"]["version"]) == (60, -20, 2)
    assert client.post(f"/api/v1/projects/{pid}/tracks/t4/mix", json={}).status_code == 400


# ---------- duplicate_track ----------

def test_duplicate_track_with_octave_and_instrument():
    p = song(track("t1", (60, 0, 1, 80), (67, 1, 1, 90), name="Lead"), track("t2", (36, 0, 1, 80), drum=True, name="Drums"))
    r = run_tool(p, "duplicate_track", {"track_id": "t1", "octaves": -1, "program": 48})
    new = r.project.tracks[-1]
    assert (new.id, new.name, new.program, new.program_set) == ("t3", "Lead 2", 48, True)
    assert [n.pitch for n in new.notes] == [48, 55] and r.changed_notes == 2
    assert r.project.tracks[:2] == p.tracks  # 원래 트랙은 그대로
    assert "t3" in r.summary and "String Ensemble 1" in r.summary
    again = run_tool(r.project, "duplicate_track", {"track_id": "t1"})
    assert again.project.tracks[-1].name == "Lead 3" and again.project.tracks[-1].id == "t4"
    named = run_tool(p, "duplicate_track", {"track_id": "t2", "name": "Drums Copy"})
    assert named.project.tracks[-1].is_drum and named.project.tracks[-1].name == "Drums Copy"


def test_duplicate_track_errors():
    p = song(track("t1", (120, 0, 1, 80)), track("t2", (36, 0, 1, 80), drum=True))
    for args, code in (
        ({"track_id": "t9"}, "unknown_track"),
        ({"track_id": "t2", "octaves": 1}, "drum_track"),
        ({"track_id": "t1", "octaves": 1}, "out_of_range"),
    ):
        with pytest.raises(ToolError) as e:
            run_tool(p, "duplicate_track", args)
        assert e.value.code == code


def test_duplicated_track_survives_export():
    from app.midi_io.convert import project_to_midi_bytes

    p = song(track("t1", (60, 0, 1, 80), name="Lead"))
    r = run_tool(p, "duplicate_track", {"track_id": "t1", "octaves": 1, "program": 40})
    back = midi_bytes_to_project(project_to_midi_bytes(r.project))
    assert [(t.name, t.program, t.notes[0].pitch) for t in back.tracks] == [("Lead", 0, 60), ("Lead 2", 40, 72)]


def test_set_instrument_drum_kits():
    p = song(track("t1", (60, 0, 1, 80), name="Keys"), track("t2", (36, 0, 1, 80), drum=True, name="Drums"))
    r = run_tool(p, "set_instrument", {"track_ids": ["t2"], "program": 25})
    assert r.project.tracks[1].program == 25 and r.changed_settings and "TR-808" in r.summary
    assert r.project.tracks[0] == p.tracks[0]
    same = run_tool(p, "set_instrument", {"track_ids": ["t2"], "program": 0})  # 이미 스탠다드(0)
    assert not same.changed_settings and "스탠다드" in same.summary
    with pytest.raises(ToolError) as e:
        run_tool(p, "set_instrument", {"track_ids": ["t2"], "program": 33})  # 드럼을 베이스로는 안 됨
    assert e.value.code == "drum_track" and "25 TR-808" in e.value.message


def test_drum_kit_survives_export():
    from app.midi_io.convert import project_to_midi_bytes

    p = song(track("t1", (36, 0, 1, 80), drum=True, name="Drums"))
    r = run_tool(p, "set_instrument", {"track_ids": ["t1"], "program": 24})
    back = midi_bytes_to_project(project_to_midi_bytes(r.project))
    assert back.tracks[0].is_drum and back.tracks[0].program == 24


def test_lane_level_endpoint_scales_one_drum_sound(client):
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    before = client.get(f"/api/v1/projects/{pid}").json()["tracks"][0]
    r = client.post(f"/api/v1/projects/{pid}/tracks/t1/lane", json={"pitch": 42, "scale": 0.5})
    assert r.status_code == 200
    after = r.json()["project"]["tracks"][0]
    for a, b in zip(before["notes"], after["notes"]):
        if a["pitch"] == 42:
            assert b["velocity"] == max(1, int(a["velocity"] * 0.5 + 0.5))
        else:
            assert a == b  # 다른 소리는 그대로
    assert r.json()["project"]["version"] == 2
    assert r.json()["note"].startswith("Drums Closed Hat 세기 ")
    nothing = client.post(f"/api/v1/projects/{pid}/tracks/t1/lane", json={"pitch": 99, "scale": 0.5})
    assert nothing.json()["note"] is None and nothing.json()["project"]["version"] == 2  # 그 소리가 없으면 그대로


def test_velocity_editor_endpoint(client):
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    lead = client.get(f"/api/v1/projects/{pid}").json()["tracks"][4]
    url = f"/api/v1/projects/{pid}/tracks/t5/velocities"
    r = client.post(url, json={"base_version": 1, "changes": [{"index": 0, "velocity": 30}, {"index": 2, "velocity": 120}]})
    assert r.status_code == 200
    got = r.json()["project"]["tracks"][4]["notes"]
    assert (got[0]["velocity"], got[2]["velocity"]) == (30, 120)
    assert got[1] == lead["notes"][1] and got[0]["pitch"] == lead["notes"][0]["pitch"]  # 다른 음 · 음높이는 그대로
    assert r.json()["project"]["version"] == 2 and r.json()["note"].startswith("Lead 음 2개의 세기")
    # 화면이 본 버전이 옛날 것이면 거절
    assert client.post(url, json={"base_version": 1, "changes": [{"index": 0, "velocity": 50}]}).status_code == 409
    assert client.post(url, json={"base_version": 2, "changes": [{"index": 9999, "velocity": 50}]}).status_code == 400
    assert client.post(url, json={"base_version": 2, "changes": [{"index": 0, "velocity": 0}]}).status_code == 422
    same = client.post(url, json={"base_version": 2, "changes": [{"index": 0, "velocity": 30}]})
    assert same.json()["note"] is None and same.json()["project"]["version"] == 2


# ---------- set_drum_sound ----------

def drum_song():
    return song(
        track("t1", (36, 0, 0.5, 90), (43, 1, 0.5, 80), (45, 2, 0.5, 80), (42, 3, 0.5, 70), drum=True, name="Drums"),
        track("t2", (40, 0, 1, 80), name="Bass"),
    )


def test_set_drum_sound_changes_one_lane():
    p = drum_song()
    r = run_tool(p, "set_drum_sound", {"track_id": "t1", "pitches": [41, 43, 45], "sound": "tom_808"})
    assert r.project.tracks[0].drum_sounds == {43: "tom_808", 45: "tom_808"}  # 안 쓰인 41은 뺀다
    assert r.project.tracks[0].notes == p.tracks[0].notes and r.changed_settings and "808 탐" in r.summary
    back = run_tool(r.project, "set_drum_sound", {"track_id": "t1", "pitches": [43], "sound": "default"})
    assert back.project.tracks[0].drum_sounds == {45: "tom_808"}
    same = run_tool(r.project, "set_drum_sound", {"track_id": "t1", "pitches": [43, 45], "sound": "tom_808"})
    assert not same.changed_settings


def test_set_drum_sound_errors():
    p = drum_song()
    for args, code in (
        ({"track_id": "t1", "pitches": [36], "sound": "hat_808"}, "wrong_role"),
        ({"track_id": "t1", "pitches": [36], "sound": "kick_nope"}, "unknown_sound"),
        ({"track_id": "t1", "pitches": [99], "sound": "kick_808"}, "unknown_pitch"),
        ({"track_id": "t2", "pitches": [40], "sound": "kick_808"}, "not_drum"),
    ):
        with pytest.raises(ToolError) as e:
            run_tool(p, "set_drum_sound", args)
        assert e.value.code == code
    with pytest.raises(ToolError) as e:
        run_tool(p, "set_drum_sound", {"track_id": "t1", "pitches": [36], "sound": "hat_808"})
    assert "kick_808" in e.value.message  # 킥 레인에 쓸 수 있는 소리를 알려 줌


def test_kit_change_resets_picked_sounds():
    p = run_tool(drum_song(), "set_drum_sound", {"track_id": "t1", "pitches": [43], "sound": "tom_round"}).project
    r = run_tool(p, "set_instrument", {"track_ids": ["t1"], "program": 25})
    assert r.project.tracks[0].drum_sounds == {}


def test_drum_sound_list_matches_frontend():
    import re
    from app.tools.drums import DRUM_SOUNDS

    ts = (Path(__file__).resolve().parents[2] / "frontend/src/audio/instruments.ts").read_text(encoding="utf-8")
    block = ts[ts.index("export const DRUM_SOUNDS") : ts.index("\n}", ts.index("export const DRUM_SOUNDS"))]
    assert set(re.findall(r"^  (\w+): ", block, re.M)) == set(DRUM_SOUNDS)


def test_drum_sound_endpoint(client):
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    r = client.post(f"/api/v1/projects/{pid}/tracks/t1/drum-sound", json={"pitch": 45, "sound": "tom_808"})
    assert r.status_code == 200
    assert r.json()["project"]["tracks"][0]["drum_sounds"] == {"45": "tom_808"}
    assert r.json()["note"] == "Drums Low Tom 소리를 808 탐(으)로 바꿨어요"
    assert client.post(f"/api/v1/projects/{pid}/tracks/t1/drum-sound", json={"pitch": 36, "sound": "hat_808"}).status_code == 400


def test_duplicate_track_top_and_bottom_voice():
    # C 코드(조금씩 어긋나게 친 것) → F 코드 → 한 음
    chords = track("t1", (60, 0, 2, 80), (64, 0.02, 2, 80), (67, 0.04, 2, 80),
                   (65, 2, 2, 80), (69, 2, 2, 80), (72, 2.01, 2, 80), (74, 4, 1, 90), name="Chords")
    p = song(chords)
    top = run_tool(p, "duplicate_track", {"track_id": "t1", "voice": "top", "program": 81})
    new = top.project.tracks[-1]
    assert [n.pitch for n in new.notes] == [67, 72, 74] and new.name == "Chords 탑노트"
    assert "맨 위 음만" in top.summary and "7개 중" in top.summary
    low = run_tool(p, "duplicate_track", {"track_id": "t1", "voice": "bottom", "octaves": -1})
    assert [n.pitch for n in low.project.tracks[-1].notes] == [48, 53, 62] and low.project.tracks[-1].name == "Chords 베이스"
    again = run_tool(top.project, "duplicate_track", {"track_id": "t1", "voice": "top"})
    assert again.project.tracks[-1].name == "Chords 탑노트 2"
    with pytest.raises(ToolError):
        run_tool(song(track("t1", (36, 0, 1, 80), drum=True)), "duplicate_track", {"track_id": "t1", "voice": "top"})


# ---------- 고른 부분 (beats) ----------

def test_selection_beats_range():
    p = song(track("t1", (60, 0, 1, 80), (62, 5, 1, 80), (64, 6.5, 1, 80), (65, 8, 1, 80)))
    r = run_tool(p, "transpose", {"track_ids": ["t1"], "beats": [5, 8], "semitones": 12})
    assert [n.pitch for n in by_track(r.project, "t1")] == [60, 74, 76, 65]  # 8박은 끝이라 빠짐
    for bad in ({"beats": [8, 5]}, {"beats": [-1, 2]}, {"beats": [0, 4], "bars": [1, 1]}):
        with pytest.raises(ToolError):
            run_tool(p, "transpose", {"semitones": 1, **bad})


def test_selection_goes_into_prompt():
    from app.agent.prompt import system_prompt

    p = midi_bytes_to_project(make_samples.lofi_groove())
    text = system_prompt(p, selection={"track_ids": ["t3"], "beats": [17.0, 24.0], "pitches": None})
    assert "t3(Rhodes)" in text and "5마디 2박 ~ 6마디 4박 3.25박" not in text
    assert "beats [17, 24]" in text and "'beats': [17.0, 24.0]" in text
    whole = system_prompt(p, selection={"track_ids": None, "beats": [32.0, 48.0]})
    assert "9~12마디" in whole and "bars [9, 12]" in whole and "모든 트랙" in whole


def test_empty_track_ids_means_all_tracks():
    p = song(track("t1", (60, 0, 1, 80)), track("t2", (40, 0, 1, 80)))
    r = run_tool(p, "adjust_velocity", {"track_ids": [], "mode": "set", "value": 50})
    assert r.changed_notes == 2  # 예전에는 0 (아무 트랙도 안 고른 것으로 처리)


def test_notes_endpoint_replaces_track_notes(client):
    from tests.test_agent import upload_lofi

    pid = upload_lofi(client)
    before = client.get(f"/api/v1/projects/{pid}").json()["tracks"][4]["notes"]
    edited = [dict(n) for n in before[1:]]  # 첫 음 지우고
    edited[0]["pitch"] += 12  # 하나 옮기고
    edited.append({"pitch": 90, "start": 0.5, "duration": 0.25, "velocity": 100})  # 하나 더하기
    url = f"/api/v1/projects/{pid}/tracks/t5/notes"
    r = client.post(url, json={"base_version": 1, "notes": edited, "label": "Lead 음 직접 편집 테스트"})
    assert r.status_code == 200
    got = r.json()["project"]["tracks"][4]["notes"]
    assert len(got) == len(before) and got[0]["pitch"] == 90  # 시작 순으로 정렬해 저장
    assert r.json()["note"] == "Lead 음 직접 편집 테스트" and r.json()["project"]["version"] == 2
    assert client.post(url, json={"base_version": 1, "notes": edited}).status_code == 409  # 옛 버전 기준
    same = client.post(url, json={"base_version": 2, "notes": got})
    assert same.json()["note"] is None and same.json()["project"]["version"] == 2
    bad = client.post(url, json={"base_version": 2, "notes": [{"pitch": 200, "start": 0, "duration": 1, "velocity": 80}]})
    assert bad.status_code == 422
