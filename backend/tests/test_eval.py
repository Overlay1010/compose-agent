"""평가 채점이 맞는지, 그리고 정답 30개가 실제로 도구로 만들 수 있는 답인지 확인한다."""

import sys
from pathlib import Path

import pytest

from app.agent.loop import ToolStep
from app.midi_io.convert import midi_bytes_to_project
from app.tools import run_tool
from eval.cases import CASES
from eval.spec import ALL, Call, Case, OneOf, Pitches, Range, score

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402

MELODIC = {"t2", "t3", "t4", "t5"}


def concrete(call: Call) -> dict:
    """정답 표현(범위 · 음 집합 · 전체)을 실제로 넣을 수 있는 인자 하나로 바꾼다."""
    out = {}
    for k, v in call.args.items():
        if v == ALL:
            out[k] = None
        elif isinstance(v, Range):
            mid = (v.low + v.high) / 2
            out[k] = int(mid) if k in ("semitones", "octaves", "program", "velocity", "times", "volume", "volume_offset", "pan", "octaves") else mid
        elif isinstance(v, Pitches):
            out[k] = sorted(v.must)
        elif isinstance(v, OneOf):
            out[k] = sorted(v.values, key=lambda x: (x is not None, str(x)))[0]  # None(비워 둠)이 있으면 그것부터
        else:
            out[k] = v
    return {k: v for k, v in out.items() if v is not None}


def step(name, args, ok=True, changed=3):
    return ToolStep(name=name, args=args, ok=ok, summary="", changed_notes=changed)


@pytest.mark.parametrize("case", [c for c in CASES if not c.expects_no_edit], ids=lambda c: c.id)
def test_every_answer_is_reachable(case: Case):
    # 정답 호출을 실제로 실행하면 음이 바뀌고, 그 기록이 정답으로 채점돼야 한다
    project = midi_bytes_to_project(make_samples.SAMPLES[f"{case.sample}.mid"]())
    steps = []
    for call in case.expect:
        args = concrete(call)
        result = run_tool(project, call.tool, args)
        assert result.changed_notes > 0 or result.changed_settings, f"{case.id} {call} 은 바뀌는 게 없음"
        project = result.project
        steps.append(ToolStep(name=call.tool, args=args, ok=True, summary="",
                              changed_notes=result.changed_notes, changed_settings=result.changed_settings))
    assert score(case, steps, MELODIC).passed, case.id


def test_no_edit_case():
    case = Case("X", "되묻기", "lofi_groove", "좀 더 좋게")
    assert score(case, [step("get_project_info", {}, changed=0)], MELODIC).passed
    assert not score(case, [step("swing", {"percent": 57})], MELODIC).passed


def test_range_alt_and_extra_edit():
    case = Case("X", "세기", "lofi_groove", "하이햇 좀 약하게",
                expect=(Call("adjust_velocity", {"track_ids": ["t1"], "mode": "scale", "value": Range(0.5, 0.85)}),),
                alt=((Call("adjust_velocity", {"track_ids": ["t1"], "mode": "offset", "value": Range(-40, -8)}),),))
    ok = step("adjust_velocity", {"track_ids": ["t1"], "mode": "scale", "value": 0.7})
    assert score(case, [ok], MELODIC).passed
    assert score(case, [step("adjust_velocity", {"track_ids": ["t1"], "mode": "offset", "value": -20})], MELODIC).passed
    too_soft = score(case, [step("adjust_velocity", {"track_ids": ["t1"], "mode": "scale", "value": 0.2})], MELODIC)
    assert not too_soft.passed and too_soft.tools_ok  # 도구는 맞고 인자가 틀림
    extra = score(case, [ok, step("swing", {"percent": 57})], MELODIC)
    assert not extra.passed and "시키지 않은 편집" in extra.reason


def test_failed_and_zero_change_steps_are_ignored():
    case = Case("X", "조옮김", "lofi_groove", "베이스 2키", expect=(Call("transpose", {"track_ids": ["t2"], "semitones": 2}),))
    steps = [step("transpose", {"track_ids": ["bass"], "semitones": 2}, ok=False), step("transpose", {"track_ids": ["t2"], "semitones": 2})]
    assert score(case, steps, MELODIC).passed


def test_all_tracks_and_defaults():
    case = Case("X", "퀀타이즈", "fl_style_loose", "전부",
                expect=(Call("quantize", {"track_ids": ALL, "strength": Range(0.95, 1, default=1.0)}),))
    assert score(case, [step("quantize", {})], MELODIC).passed  # 비워 두면 전체 · 기본 강도 1
    assert score(case, [step("quantize", {"track_ids": ["t1", "t2", "t3", "t4", "t5"]})], MELODIC).passed
    assert not score(case, [step("quantize", {"track_ids": ["t2"]})], MELODIC).passed


# ---------- 이어지는 대화 ----------

from eval.conversations import CONVERSATIONS  # noqa: E402
from eval.run import expected_state, notes_of, run_conversation  # noqa: E402
from tests.test_agent import FakeLLM, calls, say  # noqa: E402


@pytest.mark.parametrize("conv", [c for c in CONVERSATIONS if c.expect], ids=lambda c: c.id)
def test_conversation_answers_change_something(conv):
    original = midi_bytes_to_project(make_samples.SAMPLES[f"{conv.sample}.mid"]())
    assert notes_of(expected_state(original, conv.expect)) != notes_of(original), conv.id


def test_conversation_scored_by_final_state():
    d01 = next(c for c in CONVERSATIONS if c.id == "D01")  # 베이스 2키 → 적용 → 한 키 더 (= 처음보다 +3)
    right = FakeLLM(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."),
                    calls(("transpose", {"track_ids": ["t2"], "semitones": 1})), say("한 키 더 올렸어요."))
    assert run_conversation(right, d01)["passed"]
    # 앞 대화를 잊고 처음부터 +1만 한 것처럼 끝나면 오답
    wrong = FakeLLM(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."),
                    calls(("transpose", {"track_ids": ["t2"], "semitones": -1})), say("내렸어요."))
    assert not run_conversation(wrong, d01)["passed"]


def test_no_change_conversation():
    r02 = next(c for c in CONVERSATIONS if c.id == "R02")  # 4옥타브는 불가능 → 바뀌면 안 됨
    tried = FakeLLM(calls(("shift_octave", {"track_ids": ["t5"], "octaves": 3})), say("3옥타브만 올렸어요."))
    assert not run_conversation(tried, r02)["passed"]
    refused = FakeLLM(calls(("shift_octave", {"track_ids": ["t5"], "octaves": 4})), say("범위를 넘어 못 올려요."))
    result = run_conversation(refused, r02)
    assert result["passed"]  # 인자 오류(최대 3)로 실패하고 설명만 했으니 곡은 그대로


def test_read_cases_need_the_tool_and_the_answer():
    case = Case("X", "화성 분석", "lofi_groove", "무슨 키야?", reads=("analyze_harmony",), reply_has=("C major", ("Fmaj9", "F major 7")))
    read = step("analyze_harmony", {}, changed=0)
    assert score(case, [read], MELODIC, "C Major예요. 첫 코드는 Fmaj9").passed  # 대소문자는 무시
    assert "안 부름" in score(case, [], MELODIC, "C major예요. Fmaj9").reason  # 짐작으로 답함
    assert "Fmaj9|F major 7" in score(case, [read], MELODIC, "C major예요.").reason
    assert not score(case, [read, step("transpose", {"semitones": 2})], MELODIC, "C major · Fmaj9").passed  # 묻기만 했는데 편집
    ko = Case("X", "화성 분석", "lofi_groove", "무슨 키야?", reply_lacks=("장조",))
    assert "장조" in score(ko, [read], MELODIC, "C major(다장조)예요.").reason


def test_harmony_eval_scoring():
    from eval.harmony import Truth, key_from_filename, key_relation, same_tones, seventh_class

    assert key_from_filename("Cymatics - Amber Eyes MIDI - C# Min.mid") == (1, "minor")
    assert key_from_filename("Cymatics - Making The Bed MIDI - D Maj.mid") == (2, "major")
    assert key_from_filename("loop.mid") is None
    a_minor = (9, "minor")
    assert key_relation((9, "minor"), a_minor) == "정답"
    assert key_relation((0, "major"), a_minor) == "나란한조"
    assert key_relation((2, "minor"), a_minor) == "5도 관계"
    assert key_relation((9, "major"), a_minor) == "같은 으뜸음조"
    assert key_relation((1, "major"), a_minor) == "틀림"
    assert [seventh_class(q) for q in ("maj9", "13", "m9", "m", "", "m7b5")] == ["maj7", "7", "m7", "m", "", "m7b5"]
    am7 = Truth(0, 4, 9, "m7")
    assert same_tones(0, "6", am7)  # Am7 = C6 (같은 음)
    assert not same_tones(0, "maj7", am7)
