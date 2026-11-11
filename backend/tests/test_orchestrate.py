"""편곡 한 번에(arrange) · 트랙끼리 점검(app/arrange/review.py)."""

import json
import pytest

from app.arrange.review import clashes, lifts, overlaps, review
from app.generate.drums import PARTS
from app.midi_io.convert import midi_bytes_to_project
from app.models.project import Note, Project, Track
from app.tools import ToolError, run_tool
from tests.test_harmony import make_samples


def lofi(*keep: str) -> Project:
    """lofi_groove(16마디)에서 고른 트랙만."""
    p = midi_bytes_to_project(make_samples.SAMPLES["lofi_groove.mid"](), name="lofi")
    return p.model_copy(update={"tracks": [t for t in p.tracks if t.name in keep]})


def notes(*specs) -> list[Note]:
    return [Note(pitch=p, start=s, duration=d, velocity=90) for p, s, d in specs]


def added(before: Project, after: Project) -> list[Track]:
    old = {t.id for t in before.tracks}
    return [t for t in after.tracks if t.id not in old]


def by_name(p: Project, name: str) -> Track:
    return next(t for t in p.tracks if t.name == name)


def detail(r) -> str:
    """파트마다 생성기가 쓴 결과 (LLM에게는 data.parts로 간다)."""
    return " / ".join(p["summary"] for p in r.data["parts"])


# ---------- 점검 ----------


def test_clash_counts_minor_second_not_major_seventh():
    """단2 · 단9는 부딪힘, 장7(C 위의 B — maj7 화음 음)은 아님. 원래 곡끼리는 세지 않는다."""
    lead = Track(id="t1", name="Lead", program=80, notes=notes((72, 0, 2), (71, 4, 2)))  # C5 · B4
    old_pad = Track(id="t2", name="Old", program=89, notes=notes((71, 0, 2)))  # B4 — C5와 단2지만 원래 곡끼리
    new = Track(id="t3", name="New", program=89, notes=notes((59, 0, 2), (60, 4, 2)))  # B3(C5와 단9) · C4(B4와 장7)
    found = clashes(Project(id="c", tracks=[lead, old_pad, new]), {"t3"})
    assert [(c.low, c.high, c.beats) for c in found] == [(59, 72, 2.0)]


def test_short_overlap_is_passing_tone():
    lead = Track(id="t1", name="Lead", program=80, notes=notes((72, 0, 0.25)))
    new = Track(id="t2", name="New", program=89, notes=notes((71, 0, 4)))
    assert clashes(Project(id="c", tracks=[lead, new]), {"t2"}) == []


def test_overlap_between_new_and_existing_harmony():
    """같은 성격(길게 + 길게)끼리 같은 높이면 겹침. 길게 끄는 패드 위의 짧은 아르페지오는 흔한 편곡이라 치지 않는다."""
    pad = Track(id="t1", name="Pad", program=89, notes=notes(*[(p, 0, 4) for p in (48, 52, 55, 60, 64)]))
    strings = Track(id="t2", name="Strings", program=48, notes=notes(*[(p, 0, 4) for p in (50, 53, 57, 62, 65)]))
    arp = Track(id="t3", name="Arp", program=46, notes=notes(*[(50 + i, i * 0.5, 0.5) for i in range(20)]))
    high = Track(id="t4", name="High", program=89, notes=notes(*[(76 + i % 5, 0, 4) for i in range(5)]))
    p = Project(id="o", tracks=[pad, strings, arp, high])
    assert len(overlaps(p, {"t2"})) == 1 and "Strings" in overlaps(p, {"t2"})[0]
    assert overlaps(p, {"t3"}) == [] and overlaps(p, {"t4"}) == []


def test_lift_check_compares_with_the_rest():
    """에너지(치는 트랙 비율 · 새로 치는 횟수)로 비교한다."""
    busy = Track(id="t1", name="Hats", program=0, is_drum=True,
                 notes=notes(*[(42, i * 0.5, 0.1) for i in range(32)]) + notes(*[(42, 16 + i * 0.25, 0.1) for i in range(64)]))
    p = Project(id="l", tracks=[busy])
    ok, = lifts(p, [((5, 8), "higher")])
    assert ok.ok and ok.inside > ok.outside
    bad, = lifts(p, [((1, 4), "higher")])
    assert not bad.ok
    quiet, = lifts(p, [((1, 4), "lower")])
    assert quiet.ok


# ---------- arrange ----------


def test_runs_drums_before_bass_whatever_the_order():
    """계획에 베이스를 먼저 적어도 드럼 → 베이스 순서로 — 베이스가 킥에 맞는다 (기준선에서 순서가 틀려 '킥 없음'이 됐다)."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"parts": [{"role": "bass"}, {"role": "pad"}, {"role": "drums"}]})
    names = [t.name for t in added(song, r.project)]
    assert names.index("Kick") < names.index("Bass") < names.index("Pad")
    assert "킥에 맞춤" in detail(r) and r.data["review"]["kick_lock"] > 0.6
    assert r.summary.startswith("계획대로 깔았어요: 드럼(전체) → 베이스(전체) → 패드(전체)")


def test_parts_keep_their_bars_and_existing_tracks_stay():
    song = lofi("Lead", "Drums")
    r = run_tool(song, "arrange", {"parts": [{"role": "pad"}, {"role": "bass", "bars": [5, 16]}]})
    assert by_name(r.project, "Drums") == by_name(song, "Drums") and by_name(r.project, "Lead") == by_name(song, "Lead")
    bass = by_name(r.project, "Bass")
    assert min(n.start for n in bass.notes) >= 16 - 1e-6
    assert min(n.start for n in by_name(r.project, "Pad").notes) < 4
    assert len(added(song, r.project)) == 2


def test_genre_picks_bass_and_keys_sounds():
    """신스 리드 곡이라도 '재즈풍'이면 어쿠스틱 워킹 베이스 · 피아노 컴핑 (기준선 L4는 신스 베이스)."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "jazz", "parts": [{"role": "drums"}, {"role": "bass"}, {"role": "keys"}]})
    assert by_name(r.project, "Bass").program == 32 and "워킹" in detail(r)
    assert by_name(r.project, "Chords").program == 0
    assert "kick_lock" not in r.data["review"]  # 워킹은 킥을 따르지 않으니 비율을 내지 않는다
    assert by_name(r.project, "Kick").program == 32  # 재즈 킷


def test_said_sound_wins_over_genre():
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "jazz", "parts": [{"role": "bass", "program": 33, "bass_style": "root"}]})
    assert by_name(r.project, "Bass").program == 33 and "워킹" not in detail(r)


def test_stacked_harmony_splits_heights():
    """있는 패드 위에 아르페지오 → 아르페지오는 위(high)로 — 높이를 말하지 않아도."""
    song = lofi("Lead", "Pad")
    plain = run_tool(song, "generate_chords", {"pattern": "arpeggio"})
    stacked = run_tool(song, "arrange", {"parts": [{"role": "arp"}]})
    low = lambda p: sorted(n.pitch for n in added(song, p)[0].notes)[len(added(song, p)[0].notes) // 10]  # noqa: E731
    assert low(stacked.project) > low(plain.project)  # 멜로디가 G4부터라 위로는 여유가 없어 아래쪽이 올라간다


def test_lift_makes_hats_busier_in_that_range():
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "rock", "parts": [{"role": "drums"}], "lift": [{"bars": [9, 16], "energy": "higher"}]})
    hats = by_name(r.project, "Hats")
    per_bar = lambda a, b: sum(1 for n in hats.notes if (a - 1) * 4 <= n.start < b * 4) / (b - a + 1)  # noqa: E731
    assert per_bar(9, 16) > per_bar(1, 8)
    assert "9~16마디는 하이햇 촘촘하게" in detail(r)
    assert [t.name for t in added(song, r.project)].count("Hats") == 1  # 다시 깔아도 트랙은 한 벌
    assert r.data["review"]["lifts"][0]["bars"] == [9, 16]


def test_lift_that_drums_cannot_fill_gets_a_layer():
    """하이햇만 촘촘하게 해서는 안 차면 코드가 그 구간에만 반주를 더한다. 이 곡은 멜로디가 9~12마디에서 쉬어 읽을 코드가 없어
    화음 · 베이스가 다 비고 드럼만 남는다 — 그래도 꽉 찼다고 하지 않고, 왜 안 찼는지(드럼만 있는 마디)를 적는다."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "lofi", "parts": [{"role": "drums"}, {"role": "bass"}, {"role": "pad"}],
                                   "lift": [{"bars": [9, 16], "energy": "higher"}]})
    auto = [p for p in r.view["arrange"]["parts"] if p.get("auto")]
    assert [p["role"] for p in auto] == ["keys"] and auto[0]["bars"] == "9~16마디"
    keys = by_name(r.project, auto[0]["tracks"][0])
    assert min(n.start for n in keys.notes) >= 32 - 1e-6
    assert "그 구간에만 반주를 더했어요" in r.summary
    lift = r.data["review"]["lifts"][0]
    assert not lift["ok"] and lift["drum_only_bars"] == [9, 10, 11, 12]
    assert "9~12마디는 드럼 말고 아무것도 안 울려요" in r.summary


def test_lift_passes_when_the_range_really_gets_fuller():
    """멜로디가 쉬지 않는 구간(13~16마디)이면 반주를 더해 실제로 꽉 찬다."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "lofi", "parts": [{"role": "drums"}, {"role": "bass"}, {"role": "pad"}],
                                   "lift": [{"bars": [13, 16], "energy": "higher"}]})
    assert r.data["review"]["lifts"][0]["ok"]


def test_problems_are_reported_in_summary_and_card():
    """말한 진행이 멜로디와 안 맞으면 점검에 걸리고, 결과 · 화면 카드에 그대로 나온다."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"progression": ["Am", "F", "C", "G"], "parts": [{"role": "pad"}, {"role": "bass"}]})
    assert "점검에서 걸린 것: 반음으로 부딪히는 음이" in r.summary
    assert r.view["arrange"]["problems"] and r.data["review"]["clash_beats"] > 2
    json.dumps(r.data)
    json.dumps(r.view)


def test_one_failing_part_does_not_stop_the_rest():
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"parts": [{"role": "drums"}, {"role": "pad"}], "progression": ["Xyz"]})
    assert "못 깐 파트: 패드" in r.summary
    assert [p["ok"] for p in r.view["arrange"]["parts"]] == [True, False]
    with pytest.raises(ToolError, match="하나도 깔지 못했어요"):
        run_tool(song, "arrange", {"parts": [{"role": "pad"}], "progression": ["Xyz"]})


def test_part_level_drum_style_is_accepted():
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"parts": [{"role": "drums", "style": "jazz"}]})
    assert "재즈 드럼" in detail(r)


def test_single_generate_also_checks_against_other_tracks():
    """트랙 하나만 만들어도 다른 트랙과 겹치면 결과에 적는다 (기준선 L6)."""
    pad = Track(id="t1", name="Pad", program=89, notes=notes(*[(p, b * 4.0, 4.0) for b in range(4) for p in (48, 52, 55, 60, 64)]))
    song = Project(id="s", tracks=[pad])
    r = run_tool(song, "generate_chords", {"pattern": "pad", "progression": ["C"]})
    assert "점검에서 걸린 것" in r.summary and "Pad" in r.summary


def test_review_of_clean_song_has_no_problems():
    lead = Track(id="t1", name="Lead", program=80, notes=notes((76, 0, 4)))
    bass = Track(id="t2", name="Bass", program=33, notes=notes((36, 0, 4)))
    kick = Track(id="t3", name="Kick", program=0, is_drum=True, notes=notes((min(PARTS["kick"]), 0, 0.2)))
    r = review(Project(id="r", tracks=[lead, bass, kick]), {"t2"})
    assert r.problems == [] and r.kick_lock == 1.0
