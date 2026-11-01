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


# ---------- 루프 리듬 → 하이햇 ----------

from app.tools.samples import Groove  # noqa: E402

# 140 BPM 2마디 하이햇 루프: 8분음표, 뒷박을 살짝 당겨 치고(0.49) 약하게, 마지막에 열린 햇
HAT_LOOP = info("Hat Loop 140", "loop", None, length=3.4).model_copy(update={"groove": Groove(
    bpm=140, beats=8, hits=[(round(i * 0.5 - (0.01 if i % 2 else 0), 3), 80 if i % 2 else 115, 1 if i == 15 else 0) for i in range(16)],
)})


def test_groove_from_loop_makes_a_hats_track_with_the_loop_feel(lofi):
    with library([*PACK, HAT_LOOP]):
        r = run_tool(lofi, "groove_from_loop", {"sample": "hat loop"})
    hats = r.project.tracks[-1]
    assert hats.is_drum and hats.name == "Hats" and r.changed_notes == len(hats.notes)
    starts = sorted(n.start for n in hats.notes)
    assert starts[:3] == [0.0, 0.49, 1.0] and len(hats.notes) == 16 * 8  # 16마디 곡 = 2마디 루프 8번, 당겨 친 0.49 그대로
    assert {n.velocity for n in hats.notes} == {80, 115} and sum(n.pitch == 46 for n in hats.notes) == 8
    assert "8번 되풀이" in r.summary and "격자에 맞추지 않음" in r.summary


def test_groove_into_an_existing_drum_track_replaces_only_the_hats(lofi):
    with library([HAT_LOOP]):
        r = run_tool(lofi, "groove_from_loop", {"track_id": "t1", "bars": [1, 4]})  # 리듬 있는 루프가 하나뿐이라 이름 없이
    before, after = track(lofi, "Drums"), track(r.project, "Drums")
    assert [n for n in after.notes if n.pitch not in (42, 44, 46)] == [n for n in before.notes if n.pitch not in (42, 44, 46)]
    assert sorted(n.start for n in after.notes if n.pitch in (42, 46) and n.start < 16)[:2] == [0.0, 0.49]
    assert [n for n in after.notes if n.start >= 16 and n.pitch in (42, 46)] == [n for n in before.notes if n.start >= 16 and n.pitch in (42, 46)]


def test_groove_needs_a_loop_and_asks_when_there_are_several(lofi):
    with library(PACK), pytest.raises(ToolError) as e:
        run_tool(lofi, "groove_from_loop", {})
    assert e.value.code == "no_loops"
    other = HAT_LOOP.model_copy(update={"id": "other", "name": "Shaker Loop 90"})
    with library([HAT_LOOP, other]), pytest.raises(ToolError) as e:
        run_tool(lofi, "groove_from_loop", {})
    assert e.value.code == "ambiguous_sample" and "Shaker Loop 90" in e.value.message
    with library([HAT_LOOP]):
        assert "Hat Loop 140(루프 · 리듬 140 BPM)" in system_prompt(lofi)


# ---------- 루프를 오디오로 ----------

def test_add_loop_makes_an_audio_track_that_fits_the_song_tempo(lofi):
    with library([*PACK, HAT_LOOP]):
        r = run_tool(lofi, "add_loop", {"sample": "hat loop"})
    loop = r.project.tracks[-1]
    assert loop.audio is not None and loop.notes == [] and not loop.is_drum and r.changed_settings
    assert (loop.audio.sample.name, loop.audio.bpm, loop.audio.beats, loop.audio.start, loop.audio.end) == ("Hat Loop 140", 140, 8, 0, 64)
    assert "타격마다 잘라" in r.summary and "음높이는 그대로" in r.summary and "MIDI로 내보내면 빠져요" in r.summary  # 리듬 루프(음 높이 없음)
    melodic = HAT_LOOP.model_copy(update={"id": "m", "name": "Keys Loop 140", "root": 60})
    with library([melodic]):
        m = run_tool(lofi, "add_loop", {})
    assert "40% 느리게" in m.summary and "8.8반음 낮게" in m.summary and "키와 어긋날" in m.summary
    assert role_of(loop) is None
    with library([HAT_LOOP]):
        assert "오디오 루프 'Hat Loop 140' · 140 BPM · 1~16마디 · 음표 없음" in system_prompt(r.project)


def test_audio_tracks_stay_out_of_midi_but_count_for_song_length(lofi):
    from app.midi_io.convert import midi_bytes_to_project, project_to_midi_bytes
    with library([HAT_LOOP]):
        r = run_tool(lofi, "add_loop", {"bars": [17, 20]})  # 곡(16마디) 뒤에 4마디
    assert r.project.bar_count == 20
    back = midi_bytes_to_project(project_to_midi_bytes(r.project))
    assert [t.name for t in back.tracks] == [t.name for t in lofi.tracks]  # 오디오 트랙은 MIDI에 없다


def test_add_loop_needs_a_loop_with_tempo(lofi):
    with library(PACK), pytest.raises(ToolError) as e:
        run_tool(lofi, "add_loop", {})
    assert e.value.code == "no_loops"
