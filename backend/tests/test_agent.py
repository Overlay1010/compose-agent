"""에이전트 루프와 채팅 API. 진짜 LLM 대신 정해진 답을 차례로 돌려주는 FakeLLM을 쓴다."""

import json
import sys
from pathlib import Path

import pytest

from app.agent import LLMReply, LLMUnavailable, ToolCall, get_llm, run_agent
from app.agent.loop import TOO_MANY_STEPS, in_english, track_names
from app.agent.prompt import system_prompt
from app.main import app
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Project, Track
from app.store.memory import PreviewConflict, ProjectNotFound, ProjectStore

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
    assert "t2 Bass" in p and "t1 Drums (드럼 · 킷 스탠다드)" in p
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
    from app.store.memory import short

    labels = [v["label"] for v in client.get(f"/api/v1/projects/{pid}/versions").json()]
    assert labels[2:] == ['"원본 업로드" 상태로 되돌림', f'"{short(labels[1])}" 상태로 되돌림']
    versions = client.get(f"/api/v1/projects/{pid}/versions").json()
    assert all(v["created_at"] for v in versions)  # 화면의 "3분 전"
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


def test_chat_stream_sends_progress_then_done(client, use_llm):
    pid = upload_lofi(client)
    use_llm(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."))
    with client.stream("POST", f"/api/v1/projects/{pid}/chat/stream", json={"message": "베이스 2키 올려줘"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    events = [(b.split("\n")[0].removeprefix("event: "), json.loads(b.split("\n")[1].removeprefix("data: ")))
              for b in text.strip().split("\n\n")]
    kinds = [k for k, _ in events]
    assert kinds == ["thinking", "tool_start", "tool_done", "thinking", "done"]
    assert events[1][1] == {"name": "transpose", "args": {"track_ids": ["t2"], "semitones": 2}}
    assert events[2][1]["changed_notes"] == 61
    done = events[-1][1]
    assert done["reply"] == "올렸어요." and done["preview"] is not None


def test_chat_stream_reports_llm_error_as_event(client):
    from app.agent import LLMError

    class Broken(FakeLLM):
        def complete(self, messages, tools):
            raise LLMError("LLM 호출에 실패했어요: 테스트")

    app.dependency_overrides[get_llm] = lambda: Broken()
    try:
        pid = upload_lofi(client)
        with client.stream("POST", f"/api/v1/projects/{pid}/chat/stream", json={"message": "올려줘"}) as r:
            text = "".join(r.iter_text())
        assert "event: error" in text and "llm_error" in text
    finally:
        app.dependency_overrides.clear()


# ---------- 저장 (SQLite) ----------

def test_store_survives_restart(tmp_path, lofi):
    from app.store.memory import ProjectStore

    db = tmp_path / "compose.db"
    s = ProjectStore(db)
    s.create(lofi)
    edited = lofi.model_copy(update={"tempo": 100.0})
    s.add_version(edited, "템포 100")
    s.set_preview(lofi.id, edited.model_copy(update={"tempo": 110.0}), "템포 110")
    s.add_chat(lofi.id, {"role": "user", "content": "템포 110"})
    s.add_log(lofi.id, {"role": "user", "text": "템포 110"})

    again = ProjectStore(db)  # 서버를 다시 켠 것처럼
    assert again.current(lofi.id).version == 2 and again.current(lofi.id).tempo == 100
    assert [v.label for v in again.versions(lofi.id)] == ["원본 업로드", "템포 100"]
    pending = again.preview(lofi.id)
    assert pending.base_version == 2 and pending.project.tempo == 110 and pending.labels == ["템포 110"]
    assert again.chat_history(lofi.id) == [{"role": "user", "content": "템포 110"}]
    assert again.log(lofi.id) == [{"role": "user", "text": "템포 110"}]

    again.apply_preview(lofi.id)
    third = ProjectStore(db)
    assert third.current(lofi.id).version == 3 and third.preview(lofi.id) is None
    with pytest.raises(ProjectNotFound):
        third.current("없는id")


def test_store_keeps_only_recent_versions_on_disk(tmp_path, lofi):
    from app.store.memory import MAX_VERSIONS, ProjectStore

    db = tmp_path / "compose.db"
    s = ProjectStore(db)
    s.create(lofi)
    for i in range(MAX_VERSIONS + 5):
        s.add_version(lofi, f"편집 {i}")
    again = ProjectStore(db)
    versions = again.versions(lofi.id)
    assert len(versions) == MAX_VERSIONS and versions[-1].version == MAX_VERSIONS + 6


def test_session_endpoint_restores_log(client, use_llm):
    pid = upload_lofi(client)
    use_llm(calls(("transpose", {"track_ids": ["t2"], "semitones": 2})), say("올렸어요."))
    client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 2키 올려줘"})
    s = client.get(f"/api/v1/projects/{pid}/session").json()
    assert s["preview"] is not None and s["base_version"] == 1
    user, agent = s["log"]
    assert user == {"role": "user", "text": "베이스 2키 올려줘"}
    assert agent["text"] == "올렸어요." and agent["made_preview"] and agent["steps"][0]["name"] == "transpose"
    client.post(f"/api/v1/projects/{pid}/preview/apply")
    client.post(f"/api/v1/projects/{pid}/undo")
    notes = [e["text"] for e in client.get(f"/api/v1/projects/{pid}/session").json()["log"][2:]]
    assert notes == ["적용했어요", "바로 전 상태로 되돌렸어요"]
    assert client.get("/api/v1/projects/nope/session").status_code == 404


def test_recent_projects(tmp_path, lofi):
    from app.store.memory import ProjectStore

    db = tmp_path / "compose.db"
    s = ProjectStore(db)
    s.create(lofi)
    other = lofi.model_copy(update={"id": "other", "name": "두 번째"})
    s.create(other)
    s.add_version(lofi, "편집")  # lofi가 더 최근에 바뀜 (같은 초면 순서는 보장 안 되므로 이름 · 버전만 확인)
    rows = {r.id: (r.name, r.version) for r in ProjectStore(db).recent()}
    assert rows == {lofi.id: (lofi.name, 2), "other": ("두 번째", 1)}


def test_old_database_without_times_still_opens(tmp_path, lofi):
    import sqlite3

    from app.store.memory import ProjectStore

    db = tmp_path / "old.db"
    old = sqlite3.connect(db)  # 시각 칸이 없던 예전 형식
    old.execute("CREATE TABLE versions (project_id TEXT NOT NULL, version INTEGER NOT NULL, label TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (project_id, version))")
    old.execute("INSERT INTO versions VALUES (?, 1, '원본 업로드', ?)", (lofi.id, lofi.model_dump_json()))
    old.commit()
    old.close()
    s = ProjectStore(db)
    assert s.versions(lofi.id)[0].created_at == ""  # 예전 기록은 시각 없음
    s.add_version(lofi, "편집")
    assert ProjectStore(db).versions(lofi.id)[1].created_at  # 새 기록은 시각이 남는다


# ---------- Claude (Anthropic) 형식 ----------

def test_to_anthropic_converts_openai_messages():
    from app.agent.llm import to_anthropic

    messages = [
        {"role": "system", "content": "규칙들\n\n현재 프로젝트\n- t1 Drums"},
        {"role": "user", "content": "베이스 올려줘"},
        {"role": "assistant", "content": "올렸어요."},
        {"role": "system", "content": "사용자가 미리보기를 적용했어."},
        {"role": "user", "content": "드럼 약하게"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "adjust_velocity", "arguments": '{"value": 0.7}'}},
            {"id": "c2", "type": "function", "function": {"name": "swing", "arguments": "깨진 JSON"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'},
        {"role": "tool", "tool_call_id": "c2", "content": '{"ok": false}'},
    ]
    system, msgs = to_anthropic(messages)
    assert [b["text"] for b in system] == ["규칙들\n", "\n현재 프로젝트\n- t1 Drums"]  # 규칙만 따로 (캐시)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert [b["text"] for b in msgs[2]["content"]] == ["(알림) 사용자가 미리보기를 적용했어.", "드럼 약하게"]  # 중간 system → 알림 글
    uses = msgs[3]["content"]
    assert [(b["type"], b["id"], b["input"]) for b in uses] == [("tool_use", "c1", {"value": 0.7}), ("tool_use", "c2", {})]
    assert [(b["type"], b["tool_use_id"]) for b in msgs[4]["content"]] == [("tool_result", "c1"), ("tool_result", "c2")]


def test_anthropic_chat_reply_and_cache(monkeypatch):
    from types import SimpleNamespace

    from app.agent.llm import AnthropicChat

    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="올렸어요."),
                         SimpleNamespace(type="tool_use", id="tu1", name="transpose", input={"track_ids": ["t2"], "semitones": 2})],
                usage=SimpleNamespace(input_tokens=100, cache_read_input_tokens=9000, cache_creation_input_tokens=0, output_tokens=40),
            )

    llm = AnthropicChat("claude-test", "key")
    monkeypatch.setattr(llm, "_client", SimpleNamespace(messages=FakeMessages()))
    tools = [{"name": "transpose", "description": "d", "input_schema": {"type": "object"}},
             {"name": "swing", "description": "d", "input_schema": {"type": "object"}}]
    r = llm.complete([{"role": "system", "content": "규칙\n현재 프로젝트\n요약"}, {"role": "user", "content": "올려"}], tools)
    assert r.text == "올렸어요." and r.tool_calls[0].name == "transpose"
    assert json.loads(r.tool_calls[0].arguments) == {"track_ids": ["t2"], "semitones": 2}
    assert (r.input_tokens, r.cached_tokens, r.output_tokens) == (9100, 9000, 40)
    assert seen["tools"][-1]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in seen["tools"][0]
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in seen["system"][1]
    assert seen["model"] == "claude-test"


def test_make_llm_picks_provider(monkeypatch):
    from app import config
    from app.agent import llm as llm_mod

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    with pytest.raises(llm_mod.LLMUnavailable, match="ANTHROPIC_API_KEY"):
        llm_mod.make_llm("claude-sonnet-5-5")
    with pytest.raises(llm_mod.LLMUnavailable, match="OPENAI_API_KEY"):
        llm_mod.make_llm("gpt-6-luna")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    assert isinstance(llm_mod.make_llm("claude-haiku-5-5"), llm_mod.AnthropicChat)


def test_reply_markdown_is_stripped():
    from app.agent.loop import plain

    assert plain("고른 부분 코드는 **A7**이에요.") == "고른 부분 코드는 A7이에요."
    assert plain("## 결과\n- 1마디 C\n- 2마디 G") == "결과\n- 1마디 C\n- 2마디 G"  # 목록 기호는 글자로 읽혀서 둔다
    assert plain("Cmaj7 · V7/ii · 2-5-1") == "Cmaj7 · V7/ii · 2-5-1"
    # 조성은 "C major"로만 (화면 · 분석과 같은 표기)
    assert plain("이 곡은 C major(다장조)예요. 다음 후보는 A minor(가단조)") == "이 곡은 C major예요. 다음 후보는 A minor"
    assert plain("G 장조이고 E단조와 헷갈려요. Bb 장조도") == "G major이고 E minor와 헷갈려요. Bb major도"
    assert plain("장조 느낌이 밝아요") == "장조 느낌이 밝아요"  # 조성 이름이 아니면 그대로


def test_english_message_gets_an_answer_in_english_note():
    assert in_english("what key is this song in?") and in_english("make the chords jazzier")
    assert not in_english("베이스 2키 올려줘") and not in_english("Rhodes 음 길게") and not in_english("120")


def test_reply_names_tracks_instead_of_ids():
    # t1 · 89는 도구 인자에만 쓰는 번호라 답에서는 트랙 이름 · 악기 이름으로
    p = Project(id="p", tracks=[Track(id="t1", name="Piano", notes=[]), Track(id="t10", name="Pad", notes=[])])
    assert track_names("Piano(t1) 하나뿐이에요", p) == "Piano 하나뿐이에요"
    assert track_names("t1 Piano · t10 Pad", p) == "Piano · Pad"
    assert track_names("t1의 악기를 따뜻한 패드(89번)로", p) == "Piano의 악기를 따뜻한 패드로"
    assert track_names("Fmaj9 (IVmaj7) · 2마디(2박)", p) == "Fmaj9 (IVmaj7) · 2마디(2박)"


def test_claimed_edit_without_a_tool_is_asked_again(lofi):
    # 도구를 안 부르고 "올렸어요"라고 하면 한 번 더 묻는다 — 곡은 그대로인데 사용자는 바뀐 줄 알게 된다
    llm = FakeLLM(
        say("베이스를 2반음 올렸어요."),
        calls(("transpose", {"track_ids": ["t2"], "semitones": 2})),
        say("베이스를 2반음 올렸어요."),
    )
    r = run_agent(lofi, "베이스 2키 올려줘", llm)
    assert [s.name for s in r.steps] == ["transpose"] and r.draft is not None and r.llm_calls == 3
    assert "도구를 하나도 부르지 않아서" in llm.calls[1][-1]["content"]


def test_claimed_edit_is_asked_only_once(lofi):
    llm = FakeLLM(say("올렸어요."), say("어떤 트랙을 올릴까요?"))
    r = run_agent(lofi, "올려줘", llm)
    assert r.reply == "어떤 트랙을 올릴까요?" and r.llm_calls == 2 and r.draft is None
