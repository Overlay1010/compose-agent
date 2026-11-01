"""내 샘플(원샷) — 트랙 역할 · 추천 · use_sample 도구 · 화면 API · 채팅에 샘플팩 넘기기."""

import pytest

from app.agent import get_llm
from app.agent.prompt import system_prompt
from app.main import app
from app.models.project import Note, SampleRef, Track
from app.tools import ToolError, run_tool
from app.tools.samples import SampleInfo, library, recommend, role_of

from tests.test_agent import FakeLLM, calls, lofi, say, upload_lofi  # noqa: F401 (lofi는 fixture)


def info(name, kind, root, length=1.0, sustained=False, brightness=0.5, drum=None):
    return SampleInfo(id=name.lower().replace(" ", "-"), name=name, kind=kind, root=root, length=length,
                      sustained=sustained, brightness=brightness, drum=drum)


PACK = [
    info("Dark 808 C1", "bass", 24, length=2.5, brightness=0.1),
    info("Sub Bass F2", "bass", 41, length=1.5, brightness=0.2),
    info("Warm Pad C3", "pad", 48, length=6, sustained=True, brightness=0.3),
    info("Glass Pad C5", "pad", 72, length=6, sustained=True, brightness=0.9),
    info("Short Pad A3", "pad", 57, length=0.8, brightness=0.5),
    info("Dusty Keys C4", "keys", 60, length=2.0, brightness=0.25),
    info("Bright Keys C4", "keys", 60, length=2.0, brightness=0.85),
    info("Pluck E4", "pluck", 64, length=0.6, brightness=0.6),
    info("Bell A5", "bell", 81, length=3.0, brightness=0.9),
    info("Keys Chord Cmin", "chord", 60, length=2.0),
    info("Melody Loop 140 Am", "loop", 57, length=6.9),
    info("Kick 01", "drum", None, length=0.4, brightness=0.1, drum="kick"),
    info("Kick Punchy", "drum", None, length=0.3, brightness=0.3, drum="kick"),
    info("Clap 02", "drum", None, length=0.3, brightness=0.7, drum="clap"),
    info("Closed Hat", "drum", None, length=0.1, brightness=0.9, drum="hat"),
]


def track(lofi, name):
    return next(t for t in lofi.tracks if t.name == name)


def test_track_roles_in_lofi(lofi):
    assert [role_of(t) for t in lofi.tracks] == [None, "bass", "keys", "pad", "lead"]


def test_roles_from_note_shape_when_name_and_program_say_nothing():
    chords = [Note(pitch=p, start=b * 4, duration=4) for b in range(4) for p in (60, 64, 67)]
    arp = [Note(pitch=60 + (i % 4) * 4, start=i * 0.25, duration=0.25) for i in range(32)]
    assert role_of(Track(id="a", name="Track 1", notes=chords)) == "pad"
    assert role_of(Track(id="b", name="Track 2", notes=arp)) == "pluck"


def test_recommend_matches_role_and_range(lofi):
    tempo = lofi.tempo
    assert recommend(track(lofi, "Bass"), tempo, PACK)[0].sample.kind == "bass"
    pad = recommend(track(lofi, "Pad"), tempo, PACK)
    assert pad[0].sample.name == "Warm Pad C3"  # 길게 끄는 패드 · 음역이 가까움 (Glass Pad는 두 옥타브 위)
    assert pad.index(next(p for p in pad if p.sample.name == "Short Pad A3")) > 0  # 짧은 패드는 뒤로
    keys = recommend(track(lofi, "Rhodes"), tempo, PACK)
    assert keys[0].sample.kind == "keys"
    # 코드 원샷 · 루프 · 드럼은 음 하나짜리 악기가 아니라 어느 역할에도 안 고른다
    for t in lofi.tracks:
        assert not {p.sample.kind for p in recommend(t, tempo, PACK)} & {"chord", "loop", "drum"}


def test_prefer_darker_or_brighter_reorders(lofi):
    rhodes = track(lofi, "Rhodes")
    assert recommend(rhodes, lofi.tempo, PACK, "darker")[0].sample.name == "Dusty Keys C4"
    assert recommend(rhodes, lofi.tempo, PACK, "brighter")[0].sample.name == "Bright Keys C4"


def test_use_sample_without_a_pack_says_how_to_add_one(lofi):
    with pytest.raises(ToolError) as e:
        run_tool(lofi, "use_sample", {"track_ids": ["t2"]})
    assert e.value.code == "no_samples" and "내 샘플팩" in e.value.message


def test_use_sample_picks_explains_and_keeps_notes(lofi):
    with library(PACK):
        r = run_tool(lofi, "use_sample", {"track_ids": ["t4"]})  # Pad
    pad = track(r.project, "Pad")
    assert pad.sample == SampleRef(id="warm-pad-c3", name="Warm Pad C3") and pad.notes == track(lofi, "Pad").notes
    assert pad.program == track(lofi, "Pad").program  # 샘플이 없는 곳에서 들릴 악기는 그대로
    assert r.changed_settings and "Warm Pad C3" in r.summary and "다른 후보" in r.summary


def test_different_by_name_and_none(lofi):
    with library(PACK):
        first = run_tool(lofi, "use_sample", {"track_ids": ["t3"], "prefer": "darker"}).project
        other = run_tool(first, "use_sample", {"track_ids": ["t3"], "different": True}).project
        named = run_tool(lofi, "use_sample", {"track_ids": ["t3"], "sample": "bright keys"}).project
        removed = run_tool(first, "use_sample", {"track_ids": ["t3"], "sample": "none"})
    assert track(first, "Rhodes").sample.name == "Dusty Keys C4"
    assert track(other, "Rhodes").sample.name not in ("Dusty Keys C4", None)
    assert track(named, "Rhodes").sample.name == "Bright Keys C4"
    assert track(removed.project, "Rhodes").sample is None and "돌렸어요" in removed.summary


def test_use_sample_rejects_unknown_names_and_unfitting_packs(lofi):
    with library(PACK):
        with pytest.raises(ToolError) as e:
            run_tool(lofi, "use_sample", {"track_ids": ["t2"], "sample": "violin"})
        assert e.value.code == "unknown_sample"
    with library([s for s in PACK if s.kind != "bass"]), pytest.raises(ToolError) as e:
        run_tool(lofi, "use_sample", {"track_ids": ["t2"]})
    assert e.value.code == "no_fitting_sample"


def test_set_instrument_takes_the_sample_off(lofi):
    with library(PACK):
        sampled = run_tool(lofi, "use_sample", {"track_ids": ["t3"]}).project
    r = run_tool(sampled, "set_instrument", {"track_ids": ["t3"], "program": track(sampled, "Rhodes").program})
    assert track(r.project, "Rhodes").sample is None and r.changed_settings  # 같은 번호여도 샘플을 뺐으니 바뀜


def test_prompt_shows_the_pack_and_the_track_sample(lofi):
    with library(PACK):
        sampled = run_tool(lofi, "use_sample", {"track_ids": ["t4"]}).project
        text = system_prompt(sampled)
    assert "원샷 15개" in text and "(드럼: 킥 2 · 클랩 1 · 닫힌 하이햇 1)" in text and "Warm Pad C3(패드)" in text and "내 샘플 'Warm Pad C3'" in text
    assert "사용자가 넣은 샘플팩" not in system_prompt(lofi)  # 샘플팩이 없으면 그 부분이 없다


# ---------- API ----------

def as_json(samples):
    return [s.model_dump() for s in samples]


def test_track_sample_endpoint_and_history_text(client):
    pid = upload_lofi(client)
    pad = PACK[2].model_dump()
    r = client.post(f"/api/v1/projects/{pid}/tracks/t4/sample", json={"sample": pad})
    assert r.status_code == 200 and r.json()["note"] == "Pad 소리를 내 샘플 'Warm Pad C3'(으)로 바꿨어요"
    assert next(t for t in r.json()["project"]["tracks"] if t["id"] == "t4")["sample"]["name"] == "Warm Pad C3"
    r = client.post(f"/api/v1/projects/{pid}/tracks/t4/sample", json={"sample": None})
    assert r.json()["note"].startswith("Pad에서 내 샘플을 빼고")


def test_recommend_endpoint_lists_melodic_tracks(client):
    pid = upload_lofi(client)
    r = client.post(f"/api/v1/projects/{pid}/samples/recommend", json={"samples": as_json(PACK)})
    picks = r.json()
    assert set(picks) == {"t2", "t3", "t4", "t5"}  # 드럼 빼고
    assert picks["t4"][0]["name"] == "Warm Pad C3" and picks["t4"][0]["reason"]


def test_chat_passes_the_pack_to_the_tools(client):
    llm = FakeLLM(calls(("use_sample", {"track_ids": ["t2"]})), say("베이스를 내 샘플로 바꿨어요."))
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        pid = upload_lofi(client)
        r = client.post(f"/api/v1/projects/{pid}/chat", json={"message": "베이스 내 샘플로", "samples": as_json(PACK)})
    finally:
        app.dependency_overrides.clear()
    body = r.json()
    assert body["steps"][0]["ok"], body["steps"]
    assert next(t for t in body["preview"]["tracks"] if t["id"] == "t2")["sample"]["name"] in ("Dark 808 C1", "Sub Bass F2")
    assert "사용자가 넣은 샘플팩" in llm.calls[0][0]["content"]


# ---------- 드럼 레인 ----------

def test_drums_get_a_sample_per_lane_and_keep_the_kit_elsewhere(lofi):
    # lofi 드럼: 36 킥 · 38 스네어 · 39 클랩 · 42 닫힌 햇 · 46 열린 햇 · 탐 · 49 크래시
    with library(PACK):
        r = run_tool(lofi, "use_sample", {"track_ids": ["t1"]})
    drums = track(r.project, "Drums")
    picked = {p: s.name for p, s in drums.drum_samples.items()}
    assert picked[36] == "Kick 01" and picked[39] == "Clap 02" and picked[42] == "Closed Hat"
    assert picked[38] == "Clap 02"  # 스네어 샘플이 없으면 클랩으로 대신
    assert not {46, 43, 45, 48, 49, 50} & set(picked)  # 맞는 샘플이 없는 레인은 킷 소리 그대로
    assert drums.notes == track(lofi, "Drums").notes and drums.program == track(lofi, "Drums").program
    assert "킥 'Kick 01'" in r.summary and "킷 소리 그대로" in r.summary


def test_only_the_lanes_asked_for_then_another_then_off(lofi):
    with library(PACK):
        kick = run_tool(lofi, "use_sample", {"track_ids": ["t1"], "pitches": [35, 36]}).project
        other = run_tool(kick, "use_sample", {"track_ids": ["t1"], "pitches": [36], "different": True}).project
        off = run_tool(other, "use_sample", {"track_ids": ["t1"], "sample": "none"})
    assert {p: s.name for p, s in track(kick, "Drums").drum_samples.items()} == {36: "Kick 01"}
    assert track(other, "Drums").drum_samples[36].name == "Kick Punchy"
    assert track(off.project, "Drums").drum_samples == {} and "킷 소리로 돌렸어요" in off.summary


def test_kit_or_builtin_sound_replaces_the_lane_sample(lofi):
    with library(PACK):
        sampled = run_tool(lofi, "use_sample", {"track_ids": ["t1"]}).project
    lane = run_tool(sampled, "set_drum_sound", {"track_id": "t1", "pitches": [36], "sound": "default"})
    assert 36 not in track(lane.project, "Drums").drum_samples and lane.changed_settings  # 고른 소리가 같아도 샘플을 뺐으니 바뀜
    kit = run_tool(sampled, "set_instrument", {"track_ids": ["t1"], "program": 25})
    assert track(kit.project, "Drums").drum_samples == {}


def test_drum_pack_without_fitting_roles_is_an_error_but_other_tracks_still_change(lofi):
    hats_only = [s for s in PACK if s.drum == "hat" or s.kind == "pad"]
    with library(hats_only):
        with pytest.raises(ToolError) as e:
            run_tool(lofi, "use_sample", {"track_ids": ["t1"], "pitches": [36]})
        assert e.value.code == "no_fitting_sample" and "닫힌 하이햇 1" in e.value.message
        r = run_tool(lofi, "use_sample", {"track_ids": ["t1", "t4"], "pitches": [36]})  # 패드는 바뀌고 킥은 못 바꿨다고 알림
    assert track(r.project, "Pad").sample is not None and "맞는 드럼 샘플이 없어요" in r.summary


def test_drum_sample_endpoint(client):
    pid = upload_lofi(client)
    kick = next(s for s in PACK if s.name == "Kick 01").model_dump()
    r = client.post(f"/api/v1/projects/{pid}/tracks/t1/drum-sample", json={"pitch": 36, "sample": kick})
    assert r.status_code == 200 and r.json()["note"] == "Drums 킥 소리를 내 샘플 'Kick 01'(으)로 바꿨어요"
    assert next(t for t in r.json()["project"]["tracks"] if t["id"] == "t1")["drum_samples"] == {"36": {"id": "kick-01", "name": "Kick 01"}}
    r = client.post(f"/api/v1/projects/{pid}/tracks/t1/drum-sample", json={"pitch": 36, "sample": None})
    assert r.json()["note"] == "Drums 킥에서 내 샘플을 빼고 킷 소리로 돌렸어요"
