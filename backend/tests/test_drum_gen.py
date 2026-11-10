import pytest

from app.generate.drums import CLAP, CRASH, HAT, KICK, PALETTES, PARTS, SNARE, TOMS, auto_style
from app.models.project import Note, Project, Track
from app.tools import ToolError, run_tool
from app.tools.drums import DRUM_SOUNDS

from tests.test_harmony import make_samples, song
from tests.test_reharm import AM, C, F, G, project


def drums_of(p, **args):
    """한 트랙으로 (패턴 테스트용). 나누기는 split 테스트에서 따로 본다."""
    args.setdefault("split", False)
    r = run_tool(p, "generate_drums", args)
    return r, r.project.tracks[-1]


def eight_bars():
    return song(C, AM, F, G, C, AM, F, G)


def steps(track, lane, bar):
    """그 마디에서 그 레인을 친 16분음표 칸 (스윙으로 늦춘 칸도 제자리로)."""
    return sorted({round((n.start - bar * 4) * 4 - 0.4) for n in track.notes if n.pitch == lane and bar * 4 <= n.start < bar * 4 + 4})


def test_house_is_four_on_the_floor_with_claps_and_open_hats():
    r, drums = drums_of(eight_bars(), style="house")
    assert r.checks == [] and drums.is_drum and drums.name == "Drums" and drums.program == 26  # 909 킷
    assert steps(drums, KICK, 0) == [0, 4, 8, 12] and steps(drums, CLAP, 0) == [4, 12] and steps(drums, 46, 0) == [2, 6, 10, 14]


def test_fill_every_four_bars_and_crash_after_it():
    _, drums = drums_of(eight_bars(), style="pop", real_groove=False)
    for bar in (3, 7):  # 4 · 8마디: 마지막 박에 탐 넷 (높은 탐 → 낮은 탐), 그 자리 스네어 · 햇은 비움
        assert [steps(drums, t, bar) for t in TOMS] == [[12], [13], [14], [15]]
        assert all(s < 12 for s in steps(drums, HAT, bar) + steps(drums, SNARE, bar))
    assert steps(drums, CRASH, 4) == [0] and steps(drums, CRASH, 0) == []  # 필인 뒤 첫 박에만
    _, plain = drums_of(eight_bars(), style="pop", fills=False, real_groove=False)
    assert not {n.pitch for n in plain.notes} & {*TOMS, CRASH}


def test_density_changes_the_hats():
    p = eight_bars()
    low, mid, high = (steps(drums_of(p, style="pop", density=d, real_groove=False)[1], HAT, 0) for d in ("low", "mid", "high"))
    assert low == [0, 4, 8, 12] and mid == list(range(0, 16, 2)) and high == list(range(16))


def test_lofi_swings_the_off_sixteenths_and_passes_the_grid_check():
    r, drums = drums_of(eight_bars(), style="lofi", real_groove=False)
    assert r.checks == [] and "스윙 57%" in r.summary
    late = (57 / 100 * 2 - 1) * 0.5  # 8분음표 스윙: 뒷 8분음표만 늦게
    offs = {round(n.start % 1, 4) for n in drums.notes if n.pitch == HAT and n.start % 4 < 3}  # 필인 박 빼고
    assert offs == {0.0, round(0.5 + late, 4)}
    # 16분 햇이 붙은 패턴(로파이 B)에 스윙을 세게 줘도 같은 햇끼리 겹치지 않는다
    r, strong = drums_of(eight_bars(), style="lofi", version=2, swing=70, real_groove=False)
    assert r.checks == []


def test_other_versions_change_pattern_then_sound_palette():
    p = eight_bars()
    made, v1 = drums_of(p, style="trap")
    _, v2 = drums_of(made.project, style="trap", track_id=v1.id, version=2)
    r3, v3 = drums_of(made.project, style="trap", track_id=v1.id, version=3)
    assert steps(v1, KICK, 0) != steps(v2, KICK, 0) and v1.drum_sounds == v2.drum_sounds  # 2: 패턴 B, 같은 소리
    assert v3.drum_sounds != v1.drum_sounds and "버전 3" in r3.summary  # 3: 소리 조합이 바뀐다
    assert len(r3.project.tracks) == len(made.project.tracks)  # 같은 트랙을 다시


def test_modern_pop_palette_moves_the_backbeat_to_a_clap():
    _, drums = drums_of(eight_bars(), style="pop", version=3, real_groove=False)  # 팔레트 2: 일렉 킷 + 클랩 뒷박
    assert drums.program == 24 and steps(drums, CLAP, 0) == [4, 12] and steps(drums, SNARE, 0) == []
    _, played = drums_of(eight_bars(), style="pop", version=3)  # 실제 연주도 스네어를 클랩으로
    assert played.program == 24 and CLAP in {n.pitch for n in played.notes} and SNARE not in {n.pitch for n in played.notes}


def test_three_four_gets_a_three_beat_pattern():
    r, drums = drums_of(song(C, AM, F, G, beats=3, ts=(3, 4)))
    assert r.checks == [] and "3/4 기본 패턴" in r.summary
    assert {round(n.start % 3, 2) for n in drums.notes if n.pitch == KICK} == {0}
    assert all(n.start % 3 < 3 for n in drums.notes)
    made, first = drums_of(song(C, AM, F, G, beats=3, ts=(3, 4)))
    r, again = drums_of(made.project, track_id=first.id, version=2)
    assert "버전 2" in r.summary and "패턴 2" in r.summary  # 3박에도 패턴이 둘이라 버전 2를 건너뛰지 않는다
    # 3/4는 필인이 없어서 크래시도 없다 — fills 값이 결과를 바꾸지 않는다 (평가 N05: 다시 만들 때 fills false를 넣었다)
    plain = drums_of(song(C, AM, F, G, beats=3, ts=(3, 4)), fills=False)[1]
    assert CRASH not in {n.pitch for n in first.notes} and plain.notes == first.notes


def test_auto_style_follows_kit_then_tempo_and_band():
    def band(tempo, *programs, kit=None):
        tracks = [Track(id=f"t{i}", name="x", program=p, program_set=True, notes=[Note(pitch=60, start=0, duration=1)])
                  for i, p in enumerate(programs, 1)]
        if kit is not None:
            tracks.append(Track(id="d", name="Drums", is_drum=True, program=kit))
        return Project(id="p", tempo=tempo, tracks=tracks)

    assert auto_style(band(120, 0, kit=27)) == "lofi"  # 이미 로파이 킷이면 그 스타일
    assert auto_style(band(80, 4)) == "lofi" and auto_style(band(88, 33, 40)) == "boombap"
    assert auto_style(band(140, 81)) == "trap" and auto_style(band(124, 81)) == "house"
    assert auto_style(band(110, 0)) == "pop"


def test_palettes_only_use_known_sounds():
    assert all(s in DRUM_SOUNDS for ps in PALETTES.values() for p in ps for s in p.sounds.values())


def test_redo_rejects_a_pitched_track():
    with pytest.raises(ToolError) as e:
        run_tool(eight_bars(), "generate_drums", {"track_id": "t1", "version": 2})
    assert e.value.code == "unknown_track"


@pytest.mark.parametrize("style", [None, "lofi", "boombap", "house", "trap", "pop", "rock", "funk", "soul", "jazz", "latin"])
@pytest.mark.parametrize("name", [n.removesuffix(".mid") for n in make_samples.SAMPLES])
def test_drums_on_every_sample_pass_the_checks(name, style):
    r, _ = drums_of(project(name), **({"style": style} if style else {}))
    assert r.checks == [], r.checks[:5]


# ---------- 소리별 트랙으로 나누기 (기본) ----------

def new_drums(r, before):
    return [t for t in r.project.tracks if t.id not in {x.id for x in before.tracks}]


def test_default_splits_into_one_track_per_part():
    p = eight_bars()
    r = run_tool(p, "generate_drums", {"style": "trap", "version": 3})
    made = new_drums(r, p)
    assert [t.name for t in made] == ["Kick", "Snare", "Hats", "Drum FX"] and all(t.is_drum for t in made) and r.checks == []
    for t, part in zip(made, ("kick", "snare", "hats", "fx")):
        assert {n.pitch for n in t.notes} <= PARTS[part] and set(t.drum_sounds) <= PARTS[part]  # 그 부분의 음 · 소리만
    whole = drums_of(p, style="trap", version=3)[1]
    assert sorted((n.pitch, n.start) for t in made for n in t.notes) == sorted((n.pitch, n.start) for n in whole.notes)


def test_only_the_parts_asked_for():
    p = eight_bars()
    made = new_drums(run_tool(p, "generate_drums", {"parts": ["kick"]}), p)
    assert [t.name for t in made] == ["Kick"] and {n.pitch for n in made[0].notes} == {KICK}


def test_redo_one_part_leaves_the_others():
    p = eight_bars()
    r = run_tool(p, "generate_drums", {"style": "trap"})
    made = {t.name: t for t in new_drums(r, p)}
    again = run_tool(r.project, "generate_drums", {"track_id": made["Hats"].id, "density": "high"})
    after = {t.id: t for t in again.project.tracks}
    assert sorted(n.start for n in after[made["Hats"].id].notes if n.start < 4) == [i * 0.25 for i in range(16)]  # 촘촘하게
    assert all(after[t.id].notes == t.notes for name, t in made.items() if name != "Hats")
    assert after[made["Hats"].id].program == 25  # 스타일 말이 없어도 그 트랙 킷(808)에서 트랩으로


def test_redo_all_parts_uses_one_version_and_kit():
    # 3/4는 햇 패턴이 두 버전에서 같다 — 트랙마다 따로 정하면 햇만 다음 소리 조합(다른 킷)으로 넘어갔다
    p = song(C, AM, F, G, beats=3, ts=(3, 4))
    r = run_tool(p, "generate_drums", {})
    made = new_drums(r, p)
    assert [t.name for t in made] == ["Kick", "Snare", "Hats"]  # 3/4는 필인 · 크래시가 없어 Drum FX를 만들지 않는다
    again = run_tool(r.project, "generate_drums", {"track_ids": [t.id for t in made], "version": 2})
    redone = [t for t in again.project.tracks if t.id in {m.id for m in made}]
    assert len({t.program for t in redone}) == 1 and again.summary.count("버전 2") == 3


def test_each_part_track_can_take_its_own_kit():
    p = eight_bars()
    r = run_tool(p, "generate_drums", {"style": "pop"})
    hats = next(t for t in new_drums(r, p) if t.name == "Hats")
    changed = run_tool(r.project, "set_instrument", {"track_ids": [hats.id], "program": 26})
    programs = {t.name: t.program for t in changed.project.tracks if t.is_drum}
    assert programs["Hats"] == 26 and programs["Kick"] == 0  # 햇만 909 킷


# ---------- 하이햇 변주 · 롤 ----------

def hat_positions(track, bar):
    return sorted(round(n.start - bar * 4, 4) for n in track.notes if n.pitch == HAT and bar * 4 <= n.start < bar * 4 + 4)


def test_trap_hats_roll_and_vary_but_keep_the_first_bar_of_each_phrase():
    r, drums = drums_of(eight_bars(), style="trap")
    assert r.checks == [] and "하이햇 마디마다 변주 · 롤" in r.summary
    plain = [i * 0.5 for i in range(8)]
    assert hat_positions(drums, 0) == plain and hat_positions(drums, 4) == plain  # 4마디 묶음의 첫 마디는 무늬 그대로
    for bar in (1, 2, 3, 5, 6, 7):  # 나머지 마디는 32분 · 셋잇단 롤이 하나씩
        fine = [p for p in hat_positions(drums, bar) if abs(p * 4 - round(p * 4)) > 1e-3]
        assert fine, bar
    rolled = [n for n in drums.notes if n.pitch == HAT and abs(n.start * 4 - round(n.start * 4)) > 1e-3]
    assert max(n.velocity for n in rolled) - min(n.velocity for n in rolled) > 30  # 점점 세게


def test_rolls_can_be_turned_off_or_on_for_other_styles():
    _, no_rolls = drums_of(eight_bars(), style="trap", rolls=False)
    assert all(abs(n.start * 4 - round(n.start * 4)) < 1e-3 for n in no_rolls.notes)
    r, pop = drums_of(eight_bars(), style="pop", rolls=True)
    assert r.checks == [] and any(abs(n.start * 4 - round(n.start * 4)) > 1e-3 for n in pop.notes if n.pitch == HAT)
    _, simple = drums_of(eight_bars(), style="trap", density="low")  # 단순하게는 롤 없이
    assert all(abs(n.start * 4 - round(n.start * 4)) < 1e-3 for n in simple.notes)


def test_variation_changes_bars_and_can_be_turned_off():
    _, pop = drums_of(eight_bars(), style="pop", real_groove=False)
    bars = [hat_positions(pop, b) for b in range(3)]
    opens = {round(n.start % 4, 4) for n in pop.notes if n.pitch == 46}
    assert bars[1] != bars[0] or bars[2] != bars[0] or opens == {3.5}  # 16분 끼우기나 짝수 마디 끝 열린 햇
    _, same = drums_of(eight_bars(), style="pop", variation=False)
    assert all(hat_positions(same, b) == hat_positions(same, 0) for b in (1, 2, 5, 6)) and 46 not in {n.pitch for n in same.notes}


# ---------- 실제 드러머 연주 (Groove MIDI) ----------

from app.generate.grooves import DATA, GROOVE_STYLES, library  # noqa: E402


def at(p, tempo, pid="p"):
    return p.model_copy(update={"tempo": tempo, "id": pid})


def test_groove_library_is_attributed_and_uses_gm_lanes():
    import json
    data = json.loads(DATA.read_text(encoding="utf-8"))
    assert "Groove MIDI" in data["source"] and "CC BY 4.0" in data["license"] and data["changes"]
    lanes = {h[1] for g in library() for h in (*g.hits, *(g.fill or ()))}
    assert lanes <= set(range(35, 82)) and not lanes & {22, 26, 58}  # GM에 없는 번호는 옮겼다
    for style in GROOVE_STYLES:
        assert sum(style in g.styles for g in library()) >= 20, style


def test_funk_plays_a_real_loop_with_human_timing_and_its_own_fills():
    r, drums = drums_of(eight_bars(), style="funk")
    assert r.checks == [] and "실제 드러머 연주" in r.summary and "Groove MIDI" in r.summary
    off = [n for n in drums.notes if abs(n.start * 4 - round(n.start * 4)) > 0.02]
    assert len(off) > len(drums.notes) / 3  # 격자에 맞추지 않은 연주 그대로
    assert any(n.pitch == CRASH and abs(n.start - 16) < 1e-6 for n in drums.notes)  # 필인 뒤 첫 박 크래시
    assert all(n.start >= 0 and n.start < 32 for n in drums.notes)
    again = drums_of(eight_bars(), style="funk")[1]
    assert again.notes == drums.notes  # 같은 곡 · 같은 버전이면 늘 같다


def test_groove_follows_the_song_tempo():
    for tempo, style in ((80, "lofi"), (92, "boombap"), (120, "rock"), (100, "funk")):
        r, _ = drums_of(at(eight_bars(), tempo), style=style)
        bpm = int(r.summary.split("원래 ")[1].split("bpm")[0])
        assert abs(bpm - tempo) / tempo <= 0.15, (style, tempo, bpm)


def test_other_versions_pick_other_performances_and_songs_differ():
    p = at(eight_bars(), 100)
    made, v1 = drums_of(p, style="funk")
    r2, v2 = drums_of(made.project, style="funk", track_id=v1.id, version=2)
    assert v2.notes != v1.notes and "버전 2" in r2.summary and len(r2.project.tracks) == len(made.project.tracks)
    firsts = {drums_of(at(eight_bars(), 100, f"song{i}"), style="funk")[0].summary.split("(Groove MIDI의 ")[1].split(")")[0]
              for i in range(8)}
    assert len(firsts) > 1  # 비슷하게 맞는 연주는 곡마다 다르게


def test_density_picks_busier_or_sparser_performances():
    from app.generate.grooves import candidates
    low = candidates("rock", 110, "low", seed="p")[0].features["time_per_bar"]
    high = candidates("rock", 110, "high", seed="p")[0].features["time_per_bar"]
    assert low < high
    _, sparse = drums_of(eight_bars(), style="soul", density="low")
    assert all(n.velocity >= 40 for n in sparse.notes)  # 고스트 노트를 뺀다


def test_jazz_prefers_a_swinging_performance():
    from app.generate.grooves import candidates
    assert candidates("jazz", 120, seed="p")[0].features["swing"] >= 56


def test_hand_patterns_stay_for_house_trap_three_four_rolls_and_machine_feel():
    for args in ({"style": "house"}, {"style": "trap"}, {"style": "rock", "rolls": True}, {"style": "funk", "real_groove": False}):
        r, _ = drums_of(eight_bars(), **args)
        assert "실제 드러머 연주" not in r.summary and "패턴" in r.summary and r.checks == [], args
    r, _ = drums_of(song(C, AM, F, G, beats=3, ts=(3, 4)), style="funk")
    assert "3/4 기본 패턴" in r.summary
