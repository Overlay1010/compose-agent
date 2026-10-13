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


def test_registry_has_seven_tools_with_schemas():
    assert set(TOOLS) == {"transpose", "shift_octave", "quantize", "adjust_velocity", "swing", "get_project_info", "set_tempo"}
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
