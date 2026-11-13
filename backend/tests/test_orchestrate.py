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
    """하이햇만 촘촘하게 해서는 안 차면 코드가 그 구간에만 반주를 더한다. 이 곡은 멜로디가 9~12마디에서 쉬는데,
    예전엔 읽을 코드가 없어 화음 · 베이스가 비고 드럼만 남았다 — 이제 13~16마디 진행을 되풀이해 채워서 실제로 꽉 찬다."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "lofi", "parts": [{"role": "drums"}, {"role": "bass"}, {"role": "pad"}],
                                   "lift": [{"bars": [9, 16], "energy": "higher"}]})
    auto = [p for p in r.view["arrange"]["parts"] if p.get("auto")]
    assert [p["role"] for p in auto] == ["keys"] and auto[0]["bars"] == "9~16마디"
    keys = by_name(r.project, auto[0]["tracks"][0])
    assert min(n.start for n in keys.notes) >= 32 - 1e-6
    assert "그 구간에만 반주를 더했어요" in r.summary
    lift = r.data["review"]["lifts"][0]
    assert lift["ok"] and "drum_only_bars" not in lift
    pad = by_name(r.project, "Pad")
    assert any(32 <= n.start < 48 for n in pad.notes)  # 9~12마디에도 패드가 있다
    assert "9~12마디는 멜로디가 쉬어 코드를 못 읽어 13~16마디 진행을 되풀이해 채웠어요" in detail(r)


def test_rest_fill_copies_phrase_and_keeps_song_edges_and_long_breaks():
    """멜로디가 쉬어 못 읽은 곡 중간 마디는 같은 8마디 묶음의 다른 4마디 → 8마디 앞뒤 진행으로, 옮길 게 없으면 앞 코드를 이어 끈다.
    곡 앞뒤(멜로디가 아직 안 나옴 · 끝난 뒤)와 8마디보다 긴 빈 곳(일부러 비운 브레이크일 수 있음)은 채우지 않는다."""
    from app.generate.chords import fill_rests
    from app.harmony import ChordSpan

    def span(bar: int, name: str | None, bars: int = 1) -> ChordSpan:
        root = None if name is None else {"C": 0, "D": 2, "F": 5, "G": 7, "A": 9}[name[0]]
        return ChordSpan(bar * 4.0, (bar + bars) * 4.0, root, root, name or "N.C.", "", "", "", 1.0)

    # 0~7마디 진행 C F G A | C F G A, 8~11마디 N.C., 12~15마디 D G C F → 8~11마디는 같은 묶음의 12~15마디로
    song = [span(b, n) for b, n in enumerate("CFGACFGA")] + [span(8, None, 4)] + [span(12 + i, n) for i, n in enumerate("DGCF")]
    out, filled = fill_rests(song, 4.0)
    assert [c.name for c in out if 32 <= c.start < 48] == ["D", "G", "C", "F"] and filled == [(9, 12, 4)]
    # 같은 묶음이 통째로 비면 8마디 앞 같은 자리 (9~16마디 = 1~8마디)
    song = [span(b, n) for b, n in enumerate("CFGACFGA")] + [span(8, None, 8)] + [span(16, "D", 1)]
    out, filled = fill_rests(song, 4.0)
    assert [c.name for c in out if 32 <= c.start < 64] == list("CFGACFGA") and filled == [(9, 16, -8)]
    # 곡 앞뒤 N.C.는 그대로, 9마디 넘게 빈 곳도 그대로
    edges = [span(0, None, 2), span(2, "C"), span(3, "F"), span(4, None, 2)]
    assert fill_rests(edges, 4.0) == ([edges[1], edges[2]], [])
    long = [span(0, "C"), span(1, None, 9), span(10, "F")]
    assert fill_rests(long, 4.0)[1] == []
    # 옮길 진행이 없으면(짧은 곡) 앞 코드를 이어 끈다
    short = [span(0, "C"), span(1, "F"), span(2, None, 1), span(3, "G")]
    out, filled = fill_rests(short, 4.0)
    assert [c.name for c in out] == ["C", "F", "F", "G"] and filled == [(3, 3, None)]


def test_lift_passes_when_the_range_really_gets_fuller():
    """멜로디가 쉬지 않는 구간(13~16마디)이면 반주를 더해 실제로 꽉 찬다."""
    song = lofi("Lead")
    r = run_tool(song, "arrange", {"style": "lofi", "parts": [{"role": "drums"}, {"role": "bass"}, {"role": "pad"}],
                                   "lift": [{"bars": [13, 16], "energy": "higher"}]})
    assert r.data["review"]["lifts"][0]["ok"]


def test_problems_are_reported_in_summary_and_card():
    """피할 수 없는 부딪힘(멜로디가 C#을 계속 끄는데 진행은 C — 베이스 근음 C)은 점검에 걸리고, 결과 · 화면 카드에 그대로 나온다.
    (예전엔 Am-F-C-G 진행으로 걸렸는데, 이제 화음 · 베이스가 피해서 안 걸린다)"""
    lead = Track(id="t1", name="Lead", program=80, notes=notes(*[(73, b * 4.0, 4.0) for b in range(4)]))
    song = Project(id="s", tracks=[lead])
    r = run_tool(song, "arrange", {"progression": ["C"], "parts": [{"role": "pad"}, {"role": "bass"}]})
    assert "점검에서 걸린 것: 반음으로 부딪히는 음이" in r.summary and "Bass C" in r.summary
    assert r.view["arrange"]["problems"] and r.data["review"]["clash_beats"] > 2
    assert not any(c.a == "Pad" or c.b == "Pad" for c in clashes(r.project, {t.id for t in added(song, r.project)}))
    json.dumps(r.data)
    json.dumps(r.view)


# ---------- 부딪힘 피하기 (생성기) ----------


def melody(pitch: int, bars: int = 4, beats: float = 4.0) -> Project:
    return Project(id="m", tracks=[Track(id="t1", name="Lead", program=80,
                                         notes=notes(*[(pitch, b * 4.0, beats) for b in range(bars)]))])


def test_pad_turns_major_chord_into_sus4_under_held_fourth():
    """G 코드 위에서 멜로디가 C를 끌면 패드의 B(3음)가 단9로 부딪힌다 → B 대신 C로 Gsus4. 계획 · 결과에도 sus4로."""
    song = melody(72)  # C5
    r = run_tool(song, "generate_chords", {"progression": ["G"]})
    pad = added(song, r.project)[0]
    pcs = {n.pitch % 12 for n in pad.notes}
    assert 11 not in pcs and 0 in pcs and {7, 2} <= pcs
    assert "sus4로 바꾼 코드 4개" in r.summary and r.checks == []  # 4음 C를 코드 밖으로 보지 않는다
    assert "점검에서 걸린 것" not in r.summary


def test_pad_drops_root_or_fifth_before_the_third():
    """근음 · 5음은 베이스가 받치니 조금만 부딪혀도 뺀다. Am 위 멜로디 F(5음 E와 단9) → E를 빼고 A · C는 둔다."""
    song = melody(77)  # F5
    r = run_tool(song, "generate_chords", {"progression": ["Am"]})
    pcs = {n.pitch % 12 for n in added(song, r.project)[0].notes}
    assert 4 not in pcs and {9, 0} <= pcs
    assert "sus4" not in r.summary and r.checks == []


def test_short_passing_note_keeps_the_third():
    """멜로디가 반 박만 지나가면(0.5박) 3음을 빼지 않는다 — 점검도 0.5박 넘게 겹쳐야 센다."""
    song = melody(72, beats=0.25)
    pcs = {n.pitch % 12 for n in added(song, run_tool(song, "generate_chords", {"progression": ["G"]}).project)[0].notes}
    assert {7, 11, 2} <= pcs


def test_bass_approach_avoids_note_under_current_chord_tone():
    """Am → C로 이어 줄 때 반음 아래 B는 지금 코드(Am)의 C와 단9로 부딪힌다 → 위에서 내려오는 D로."""
    song = melody(76)
    r = run_tool(song, "generate_bassline", {"progression": ["Am", "C"], "version": 2})  # 4분음표 리듬 (마지막 음이 1박)
    bass = added(song, r.project)[0]
    last_of_am = max((n for n in bass.notes if n.start < 4), key=lambda n: n.start)
    assert last_of_am.pitch % 12 == 2
    assert r.checks == []


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
