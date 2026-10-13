"""에이전트 루프와 채팅 API. 진짜 LLM 대신 정해진 답을 차례로 돌려주는 FakeLLM을 쓴다."""

import json
import sys
from pathlib import Path

import pytest

from app.agent import LLMReply, LLMUnavailable, ToolCall, get_llm, run_agent
from app.agent.loop import TOO_MANY_STEPS
from app.agent.prompt import system_prompt
from app.main import app
from app.midi_io.convert import midi_bytes_to_project
from app.store.memory import PreviewConflict, ProjectStore

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import make_samples  # noqa: E402


class FakeLLM:
    model = "fake"

    def __init__(self, *script: LLMReply):
        self.script = list(script)
        self.calls: list[list[dict]] = []  # 매번 받은 messages

    def complete(self, messages, tools):
        self.calls.append(list(messages))
        return self.script.pop(0)


def calls(*items: tuple[str, dict]) -> LLMReply:
    return LLMReply(text="", tool_calls=[ToolCall(f"c{i}", name, json.dumps(args)) for i, (name, args) in enumerate(items)])


def say(text: str) -> LLMReply:
    return LLMReply(text=text)


@pytest.fixture
def lofi():
    return midi_bytes_to_project(make_samples.lofi_groove(), name="lofi_groove")


# ---------- 루프 ----------

def test_single_edit_makes_draft_and_keeps_original(lofi):
    llm = FakeLLM(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("베이스를 2반음 올렸어요."))
    before = lofi.model_copy(deep=True)
    r = run_agent(lofi, "베이스 2키 올려줘", llm)

    assert r.reply == "베이스를 2반음 올렸어요."
    assert [s.name for s in r.steps] == ["transpose"] and r.steps[0].ok
    assert r.draft is not None
    assert [n.pitch for n in r.draft.tracks[1].notes] == [n.pitch + 2 for n in lofi.tracks[1].notes]
    assert lofi == before  # 원본은 그대로
    assert "2반음" in r.label


def test_multiple_tools_stack_on_the_draft(lofi):
    hats = {"track_ids": ["t1"], "pitches": [42, 46]}
    llm = FakeLLM(
        calls(("adjust_velocity", {**hats, "mode": "scale", "value": 0.7}), ("swing", {**hats, "percent": 58})),
        say("하이햇을 약하게 하고 스윙을 넣었어요."),
    )
    r = run_agent(lofi, "하이햇 좀 약하게 하고 살짝 스윙", llm)

    assert [s.name for s in r.steps] == ["adjust_velocity", "swing"]
    hat = [n for n in r.draft.tracks[0].notes if n.pitch == 42]
    assert max(n.velocity for n in hat) < 82  # 세기 줄어듦
    assert any(abs(n.start % 0.5 - 0.08) < 1e-3 for n in hat)  # 뒷박이 늦춰짐
    assert r.llm_calls == 2


def test_tool_error_goes_back_to_llm_and_it_retries(lofi):
    llm = FakeLLM(
        calls(("transpose", {"track_ids": ["bass"], "semitones": 2})),
        calls(("transpose", {"track_ids": ["t2"], "semitones": 2})),
        say("올렸어요."),
    )
    r = run_agent(lofi, "베이스 2키 올려줘", llm)

    assert [s.ok for s in r.steps] == [False, True]
    tool_msg = json.loads(llm.calls[1][-1]["content"])
    assert tool_msg["ok"] is False and "t2(Bass)" in tool_msg["error"]  # 고칠 수 있는 정보를 같이 준다
    assert r.draft is not None


def test_bad_json_args_are_reported_not_raised(lofi):
    bad = LLMReply(text="", tool_calls=[ToolCall("c0", "transpose", "{not json")])
    r = run_agent(lofi, "올려줘", FakeLLM(bad, say("다시 해 볼게요.")))
    assert r.steps[0].ok is False and "JSON" in r.steps[0].summary
    assert r.draft is None


def test_stops_after_max_steps_but_keeps_progress(lofi):
    step = calls(("adjust_velocity", {"track_ids": ["t2"], "mode": "offset", "value": -1}))
    r = run_agent(lofi, "계속 줄여", FakeLLM(*[step] * 3), max_steps=3)
    assert r.reply == TOO_MANY_STEPS
    assert len(r.steps) == 3 and r.draft is not None


def test_question_without_tools_has_no_draft(lofi):
    r = run_agent(lofi, "어떤 트랙을 바꿀까요?", FakeLLM(say("어느 트랙을 말씀하시는 건가요?")))
    assert r.steps == [] and r.draft is None


def test_info_only_has_no_draft(lofi):
    r = run_agent(lofi, "트랙 알려줘", FakeLLM(calls(("get_project_info", {})), say("트랙은 5개예요.")))
    assert r.steps[0].ok and r.draft is None


def test_system_prompt_lists_track_ids_and_drum_sounds(lofi):
    p = system_prompt(lofi, pending=["Bass 트랙 61개 음을 2반음 올렸어요."])
    assert "t2 Bass" in p and "t1 Drums (드럼)" in p
    assert "42 Closed Hat" in p and "36 Kick" in p
    assert "미리보기" in p and "2반음" in p


# ---------- 저장소 ----------

def test_store_preview_conflict(lofi):
    s = ProjectStore()
    s.create(lofi)
    s.set_preview(lofi.id, lofi, "편집")
    s.add_version(lofi, "다른 경로로 바뀜")
    with pytest.raises(PreviewConflict):
        s.apply_preview(lofi.id)
    assert s.preview(lofi.id) is None


# ---------- API ----------

@pytest.fixture
def use_llm():
    def install(*script):
        llm = FakeLLM(*script)
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    yield install
    app.dependency_overrides.clear()


def upload_lofi(client) -> str:
    r = client.post("/api/v1/projects", files={"file": ("lofi.mid", make_samples.lofi_groove(), "audio/midi")})
    return r.json()["id"]


def test_chat_preview_then_apply(client, use_llm):
    pid = upload_lofi(client)
    use_llm(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."))

    r = client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 2키 올려줘"})
    assert r.status_code == 200
    body = r.json()
    assert body["preview"] is not None and body["base_version"] == 1
    assert client.get(f"/api/v1/projects/{pid}").json()["version"] == 1  # 아직 적용 전

    applied = client.post(f"/api/v1/projects/{pid}/preview/apply").json()
    assert applied["version"] == 2
    versions = client.get(f"/api/v1/projects/{pid}/versions").json()
    assert [v["version"] for v in versions] == [1, 2]
    assert "2반음" in versions[1]["label"] and versions[1]["current"]


def test_commands_accumulate_until_applied(client, use_llm):
    pid = upload_lofi(client)
    llm = use_llm(
        calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."),
        calls(("shift_octave", {"track_ids": ["t5"], "octaves": -1})), say("내렸어요."),
    )
    client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 2키 올려줘"})
    second = client.post(f"/api/v1/projects/{pid}/chat", json={"message": "멜로디도 한 옥타브 내려줘"}).json()

    # 두 번째 명령은 첫 미리보기 위에서 시작하고, 이전 대화와 미리보기 내용을 LLM이 본다
    system = llm.calls[2][0]["content"]
    assert "아직 적용하지 않은 미리보기" in system
    assert any(m.get("content") == "베이스 2키 올려줘" for m in llm.calls[2])
    assert second["base_version"] == 1

    applied = client.post(f"/api/v1/projects/{pid}/preview/apply").json()
    original = midi_bytes_to_project(make_samples.lofi_groove())
    assert applied["tracks"][1]["notes"][0]["pitch"] == original.tracks[1].notes[0].pitch + 2
    assert applied["tracks"][4]["notes"][0]["pitch"] == original.tracks[4].notes[0].pitch - 12


def test_cancel_and_apply_without_preview(client, use_llm):
    pid = upload_lofi(client)
    use_llm(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."))
    client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 2키 올려줘"})

    assert client.post(f"/api/v1/projects/{pid}/preview/cancel").status_code == 204
    r = client.post(f"/api/v1/projects/{pid}/preview/apply")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_preview"
    assert client.get(f"/api/v1/projects/{pid}").json()["version"] == 1


def test_undo_and_restore_keep_history(client, use_llm):
    pid = upload_lofi(client)
    use_llm(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."))
    client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 2키 올려줘"})
    client.post(f"/api/v1/projects/{pid}/preview/apply")

    undone = client.post(f"/api/v1/projects/{pid}/undo").json()
    assert undone["version"] == 3  # 지우지 않고 v1 내용을 v3으로
    redo = client.post(f"/api/v1/projects/{pid}/versions/2/restore").json()
    assert redo["version"] == 4
    assert [v["label"] for v in client.get(f"/api/v1/projects/{pid}/versions").json()][2:] == [
        "v1(으)로 되돌림",
        "v2(으)로 되돌림",
    ]
    assert client.post(f"/api/v1/projects/{pid}/versions/99/restore").status_code == 404


def test_chat_without_api_key_is_503(client):
    def unavailable():
        raise LLMUnavailable("OPENAI_API_KEY가 없어요.")

    app.dependency_overrides[get_llm] = unavailable
    try:
        pid = upload_lofi(client)
        r = client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 올려줘"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"
    finally:
        app.dependency_overrides.clear()


def test_chat_validates_message(client, use_llm):
    pid = upload_lofi(client)
    use_llm()
    assert client.post(f"/api/v1/projects/{pid}/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/v1/projects/nope/chat", json={"message": "hi"}).status_code == 404


def test_reasoning_effort_fallback_survives_concurrent_requests():
    # 동시에 보낸 요청 중 다른 하나가 먼저 reasoning_effort를 'none'으로 바꿔 놓은 상황에서도,
    # 이번 요청은 'none' 없이 보냈으니 다시 시도해야 한다
    import httpx
    import openai

    from app.agent.llm import OpenAIChat

    llm = OpenAIChat("test-model", api_key="sk-test")
    sent: list[object] = []

    class Message:
        content = "ok"
        tool_calls = None

    class Response:
        choices = [type("Choice", (), {"message": Message()})()]
        usage = None

    def create(**kwargs):
        sent.append(kwargs.get("reasoning_effort"))
        if kwargs.get("reasoning_effort") != "none":
            llm.reasoning_effort = "none"  # 다른 요청이 먼저 바꿔 놓음
            raise openai.BadRequestError(
                "tools need reasoning_effort none",
                response=httpx.Response(400, request=httpx.Request("POST", "https://api.test")),
                body={"param": "reasoning_effort"},
            )
        return Response()

    llm._client.chat.completions.create = create  # type: ignore[method-assign]
    assert llm.complete([{"role": "user", "content": "hi"}], []).text == "ok"
    assert sent == [None, "none"]


def test_start_over_replaces_the_preview(lofi):
    # "패드 한 옥타브 올려줘" 미리보기(+1) 위에서 "아니 내려줘" → 미리보기를 버리고 처음보다 −1
    from app.agent import session
    from app.store.memory import ProjectStore

    s = ProjectStore()
    pid = s.create(lofi).id
    session.chat_turn(s, pid, "패드 한 옥타브 올려줘", FakeLLM(calls(("shift_octave", {"track_ids": ["t4"], "octaves": 1})), say("올렸어요.")))
    llm = FakeLLM(calls(("start_over", {})), calls(("shift_octave", {"track_ids": ["t4"], "octaves": -1})), say("내렸어요."))
    result, pending = session.chat_turn(s, pid, "아니 내려줘", llm)

    assert result.started_over_at == 0
    original = [n.pitch for n in lofi.tracks[3].notes]
    assert [n.pitch for n in pending.project.tracks[3].notes] == [p - 12 for p in original]
    assert pending.labels == ["Pad 트랙 24개 음을 1옥타브 내렸어요."]  # 버린 +1은 기록에 안 남음


def test_start_over_only_offered_with_base(lofi):
    seen = []

    class Spy(FakeLLM):
        def complete(self, messages, tools):
            seen.append([t["name"] for t in tools])
            return super().complete(messages, tools)

    run_agent(lofi, "안녕", Spy(say("안녕하세요")))
    run_agent(lofi, "아니", Spy(say("네")), base=lofi)
    assert "start_over" not in seen[0] and "start_over" in seen[1]


def test_range_error_suggests_splitting(lofi):
    from app.tools import ToolError, run_tool

    with pytest.raises(ToolError) as e:
        run_tool(lofi, "transpose", {"track_ids": ["t2"], "semitones": 30})
    assert "나눠서" in e.value.message


def test_start_over_rolls_back_half_done_edit(lofi):
    # 3옥타브는 됐는데 1옥타브 더가 실패 → start_over로 되돌리면 곡은 그대로
    llm = FakeLLM(
        calls(("shift_octave", {"track_ids": ["t5"], "octaves": 3})),
        calls(("shift_octave", {"track_ids": ["t5"], "octaves": 1})),
        calls(("start_over", {})),
        say("4옥타브는 범위를 넘어 올릴 수 없어요."),
    )
    r = run_agent(lofi, "리드를 4옥타브 올려줘", llm, base=lofi)
    assert [s.ok for s in r.steps] == [True, False, True]
    assert r.draft is None and r.label == ""
