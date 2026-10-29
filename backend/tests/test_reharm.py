import json

import pytest

from app.agent.loop import _run_call
from app.harmony.reharm import suggest
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Note, Track
from app.tools import ToolError, run_tool

from tests.test_harmony import make_samples, song


def project(name: str):
    return midi_bytes_to_project(make_samples.SAMPLES[f"{name}.mid"]())

C, AM, F, G = ([60, 64, 67], 48), ([57, 60, 64], 45), ([53, 57, 60], 41), ([55, 59, 62], 43)


def by_style(project, **kw):
    a, ss = suggest(project, **kw)
    return a, {s.style: s for s in ss}


def names(s):
    return [c.name for c in s.chords]


def with_melody(project, *notes: tuple[int, float, float]):
    project.tracks.append(Track(id="m", name="Lead", notes=[Note(pitch=p, start=s, duration=d) for p, s, d in notes]))
    return project


def test_three_styles_on_a_pop_loop():
    a, ss = by_style(song(C, AM, F, G))
    assert a.key.name == "C major" and list(ss) == ["가볍게", "재지하게", "색다르게"]
    # 가볍게: IV → ii(같은 기능) + 음계 안의 9음
    assert names(ss["가볍게"]) == ["Cmaj9", "Am9", "Dm9", "G9"]
    assert [c.kind for c in ss["가볍게"].changes] == ["텐션", "텐션", "같은 기능", "텐션"]
    # 재지하게: 다음 코드로 가는 딸림7을 반 마디 끼우고, 으뜸화음으로 돌아가는 G(루프 이음새)는 트라이톤 대리 Db7.
    # F 뒤에는 D7(V7/V)을 넣지 않는다 — G가 Db7로 바뀌어 D7이 갈 곳이 없어지므로
    jazzy = ss["재지하게"]
    assert names(jazzy) == ["Cmaj9", "E7", "Am9", "C7", "Fmaj9", "Db7"]
    assert [(c.start, c.end) for c in jazzy.chords[:2]] == [(0, 2), (2, 4)]
    assert [c.roman for c in jazzy.chords] == ["Imaj7", "V7/vi", "vi7", "V7/IV", "IVmaj7", "subV7"]
    # 색다르게: 같은 으뜸음 단조에서 빌려온 iv · bVII7 (C major에서도 A# 말고 Bb)
    colorful = ss["색다르게"]
    assert names(colorful) == ["C", "Am", "Fm6", "Bb7"]
    assert [c.function for c in colorful.chords] == ["T", "T", "차용", "차용"]


def test_suggest_does_not_touch_the_analysis():
    a, _ = suggest(song(C, AM, F, G))
    assert [c.name for c in a.chords] == ["C", "Am", "F", "G"]


def test_only_chords_in_the_range_change():
    _, ss = by_style(song(C, AM, F, G), start=8, end=12)
    assert names(ss["가볍게"]) == ["C", "Am", "Dm9", "G"]
    assert [c.start for c in ss["가볍게"].changes] == [8]


def test_strong_melody_clash_drops_that_change():
    # 3마디 첫 박에 멜로디 A를 두 박: F 코드 음이지만 Fm6 · Fm7의 Ab 반음 위 → 빌려온 iv는 쓰지 않는다
    p = with_melody(song(C, AM, F, G), (79, 0, 4), (81, 4, 4), (81, 8, 2), (79, 12, 4))
    _, ss = by_style(p)
    assert names(ss["색다르게"]) == ["C", "Am", "F", "Bb7"]
    assert not ss["색다르게"].rubs


def test_weak_melody_clash_is_kept_with_a_note():
    # 같은 A라도 2박의 8분음표(약박 · 짧음)면 바꾸고 "살짝 부딪힘"으로 알린다
    p = with_melody(song(C, AM, F, G), (79, 0, 4), (81, 4, 4), (81, 9, 0.5), (79, 12, 4))
    _, ss = by_style(p)
    assert names(ss["색다르게"]) == ["C", "Am", "Fm6", "Bb7"]
    assert ss["색다르게"].rubs == ["3마디 2박 멜로디 A ↔ Fm6 (반음)"]


def test_clash_already_in_the_song_is_not_counted():
    # 1마디 C 위 멜로디 F(E의 반음 위)는 원래도 부딪힌다 → Cmaj9로 바꿔도 막지 않는다
    p = with_melody(song(C, AM, F, G), (77, 0, 4), (76, 4, 4), (77, 8, 4), (79, 12, 4))
    _, ss = by_style(p)
    assert names(ss["가볍게"])[0] == "Cmaj9"


def test_minor_key_borrows_from_major():
    am, dm, em = ([57, 60, 64], 45), ([50, 53, 57], 38), ([52, 55, 59], 40)
    _, ss = by_style(song(am, dm, em, am))
    # iv → IV7(도리안), v → V7, 곡이 i로 끝나면 마지막을 I로(피카르디 3도)
    assert names(ss["색다르게"]) == ["Am", "D7", "E7", "A"]


def test_waltz_keeps_bar_lines():
    # 3/4는 반 마디로 나누지 않는다: 재지하게도 코드 경계가 원래와 같다
    a, ss = by_style(project("waltz_3_4"))
    jazzy = ss["재지하게"]
    assert [c.start for c in jazzy.chords] == [c.start for c in a.chords]
    assert "Ab7" in names(jazzy)  # D7 → G는 트라이톤 대리 (G major에서도 G#7 말고 Ab7)


# ---------- 도구 ----------

def test_tool_sends_short_text_to_llm_and_chords_to_screen():
    p = song(C, AM, F, G)
    _, step, content = _run_call(p, "suggest_reharmonization", json.dumps({"bars": [3, 4]}))
    assert step.ok and step.changed_notes == 0 and step.summary == "조성 C major · 3~4마디 리하모니 제안 3개 (가볍게 · 재지하게 · 색다르게)"
    light = content["data"]["suggestions"][0]
    assert light["progression"] == "Dm9 → G9" and light["changes"] == ["3마디 F → Dm9 (같은 기능)", "4마디 G → G9 (텐션)"]
    assert "view" not in content  # LLM에는 코드 목록을 보내지 않는다 (화면 카드용)
    cards = step.view["reharm"]
    assert [c["name"] for c in cards["base"]] == ["C", "Am", "F", "G"]
    assert [c["name"] for c in cards["suggestions"][0]["chords"]] == ["C", "Am", "Dm9", "G9"]
    assert cards["bars"] == [3, 4]  # 카드의 "이걸로 바꾸기"가 같은 범위로 바꾸게


def test_apply_chords_changes_keys_and_bass_as_a_preview():
    p = song(C, AM, F, G)
    r = run_tool(p, "apply_chords", {"style": "가볍게", "bars": [3, 4]})
    # 실제로 음높이 · 길이가 바뀐 음만 센다 (Dm9로 바꿔도 F · A · C는 그대로)
    assert r.changed_notes == 4 and r.summary.startswith("Keys, Bass 트랙 4개 음을 가볍게 제안 코드로 바꿨어요")
    assert [c.name for c in suggest(r.project)[0].chords] == ["C", "Am", "Dm9", "G9"]
    assert [n.pitch for n in p.tracks[1].notes] == [48, 45, 41, 43]  # 원래 곡은 그대로


def test_apply_chords_without_that_suggestion_says_what_exists():
    # 3/4 왈츠에 "색다르게"가 없는 범위: 1마디(G, 으뜸화음)만 고르면 빌려올 화음이 없다
    with pytest.raises(ToolError, match="있는 제안"):
        run_tool(project("waltz_3_4"), "apply_chords", {"style": "색다르게", "bars": [1, 1]})


def test_tool_rejects_a_range_without_chords():
    with pytest.raises(ToolError):
        run_tool(song(C, AM, F, G), "suggest_reharmonization", {"bars": [9, 10]})
