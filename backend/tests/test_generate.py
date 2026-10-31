import pytest

from app.generate.check import check, playable
from app.generate.chords import comp_program, pad_notes, pad_program, parse_chord
from app.harmony import analyze
from app.harmony.reharm import INTERVALS
from app.models.project import Note, Project, Track
from app.tools import ToolError, run_tool

from tests.test_harmony import make_samples, song
from tests.test_reharm import AM, C, F, G, project, with_melody


def pad_of(p, **args):
    r = run_tool(p, "generate_chords", args)
    return r, r.project.tracks[-1]


def by_start(track):
    groups = {}
    for n in track.notes:
        groups.setdefault(n.start, []).append(n)
    return [sorted(g, key=lambda n: n.pitch) for _, g in sorted(groups.items())]


def test_pad_follows_the_song_chords_on_a_new_track():
    p = song(C, AM, F, G)
    r, pad = pad_of(p)
    assert pad.id == "t3" and pad.name == "Pad" and pad.program_set and r.changed_notes == 16
    chords = analyze(p).chords
    for chord, group in zip(chords, by_start(pad)):
        # 코드마다 4음을 그 코드 길이만큼 누르고, 모두 그 코드의 음
        tones = {(chord.root + i) % 12 for i in INTERVALS[chord.quality]}
        assert len(group) == 4 and {n.pitch % 12 for n in group} <= tones
        assert all(n.start == chord.start and n.duration == chord.end - chord.start for n in group)
    assert len(p.tracks) == 2  # 원래 곡은 그대로 (새 프로젝트에만 트랙이 생김)


def test_pad_sits_between_bass_and_melody():
    p = with_melody(song(C, AM, F, G), (76, 0, 4), (77, 4, 4), (79, 8, 4), (77, 12, 4))
    _, pad = pad_of(p)
    bass_top = max(n.pitch for n in p.tracks[1].notes)
    assert all(bass_top < n.pitch < 76 for n in pad.notes)


def test_pad_moves_little_between_chords():
    # 앞 코드에서 가장 덜 움직이게 잇는다: C → Am → F → G에서 코드마다 네 음이 합쳐 8반음 넘게 움직이지 않는다
    _, pad = pad_of(song(C, AM, F, G))
    groups = [[n.pitch for n in g] for g in by_start(pad)]
    assert all(sum(abs(a - b) for a, b in zip(x, y)) <= 8 for x, y in zip(groups, groups[1:]))


def test_pad_sound_fits_the_band():
    def band(*tracks):
        return Project(id="p", tracks=[Track(id=f"t{i}", name=n, program=prog, program_set=True) for i, (n, prog) in enumerate(tracks, 1)])

    assert pad_program(band(("Keys", 4), ("Bass", 33))) == 89  # 건반 · 로파이 → 따뜻한 패드
    assert pad_program(band(("Violin", 40), ("Cello", 42))) == 48  # 현악 편성 → 스트링 앙상블
    assert pad_program(band(("Lead", 81), ("Bass", 38))) == 90  # 신스 → 폴리신스 패드
    assert pad_program(band(("Keys", 4), ("Pad", 89))) == 90  # 이미 따뜻한 패드가 있으면 다른 패드


def test_pad_respects_the_range():
    _, pad = pad_of(song(C, AM, F, G), bars=[3, 4])
    assert {n.start for n in pad.notes} == {8, 12}


def test_height_moves_the_pad():
    p = song(C, AM, F, G)
    low = [n.pitch for n in pad_of(p, height="low")[1].notes]
    high = [n.pitch for n in pad_of(p, height="high")[1].notes]
    assert sum(low) / len(low) + 6 < sum(high) / len(high)


def test_existing_pad_name_is_not_reused():
    p = song(C, AM, F, G)
    p.tracks.append(Track(id="t3", name="Pad", program=89, notes=[Note(pitch=60, start=0, duration=4)]))
    _, pad = pad_of(p)
    assert (pad.id, pad.name) == ("t4", "Pad 2")


def test_no_chords_no_pad():
    drums = Project(id="p", tracks=[Track(id="t1", name="Drums", is_drum=True, notes=[Note(pitch=36, start=0, duration=0.25)])])
    with pytest.raises(ToolError):
        run_tool(drums, "generate_chords", {})
    assert pad_notes(drums)[0] == []


def test_pad_on_samples_stays_in_its_window():
    # 샘플 곡: 베이스 트랙이 있으면 그 위쪽에서 시작한다
    p = project("lofi_groove")
    _, pad = pad_of(p)
    bass = next(t for t in p.tracks if t.name == "Bass")
    top = sorted(n.pitch for n in bass.notes)[int(0.9 * len(bass.notes))]
    assert min(n.pitch for n in pad.notes) > top - 12 and pad.program == 90  # 이미 Pad(따뜻한 패드)가 있어 폴리신스


@pytest.mark.parametrize("name", [n.removesuffix(".mid") for n in make_samples.SAMPLES])
def test_pad_on_every_sample_passes_the_checks(name):
    p = project(name)
    try:
        r, pad = pad_of(p)
    except ToolError:  # 코드가 없는 곡 (드럼만)
        return
    assert r.checks == [] and not check(pad.notes, pad.program, chords=analyze(p).chords)


def test_check_finds_each_kind_of_mistake():
    chords = analyze(song(C, AM, F, G)).chords  # 4박마다 C · Am · F · G
    good = [Note(pitch=p, start=0, duration=4) for p in (60, 64, 67)]
    assert check(good, 89, chords=chords) == []
    bad = [
        Note(pitch=61, start=0, duration=4),  # C 코드에 C#
        Note(pitch=64, start=0.1, duration=1),  # 16분음표 격자에 안 맞음
        Note(pitch=20, start=4, duration=4),  # Am에 G#, 패드로 못 내는 높이 (G#0)
        Note(pitch=69, start=4, duration=4), Note(pitch=69, start=6, duration=2),  # 같은 음이 겹침
    ]
    kinds = sorted(x.split()[0] for x in check(bad, 89, chords=chords))
    assert kinds == ["겹침", "박", "음역", "코드", "코드"]
    assert any(x.startswith("코드 밖 C#4") for x in check(bad, 89, chords=chords))
    assert check(bad[1:2], 89, chords=chords, starts=(0.1,)) == []  # 고른 범위 시작이면 격자에 안 맞아도 된다


def test_scale_check_allows_chord_tones():
    a = analyze(song(C, AM, F, G))
    assert check([Note(pitch=62, start=0, duration=1)], 0, key=a.key) == []  # D: C major 음계
    assert check([Note(pitch=63, start=0, duration=1)], 0, key=a.key)  # Eb: 음계에도 C 코드에도 없음


def test_other_versions_voice_differently_on_the_same_track():
    p = song(C, AM, F, G)
    r, pad = pad_of(p)
    seen = [tuple(n.pitch for n in pad.notes)]
    for version in range(2, 8):  # "다른 버전"을 여러 번
        r, redone = pad_of(r.project, track_id=pad.id, version=version)
        assert len(r.project.tracks) == 3 and redone.id == pad.id and redone.name == "Pad"
        assert r.checks == [] and "버전" in r.summary
        seen.append(tuple(n.pitch for n in redone.notes))
    assert all(a != b for a, b in zip(seen, seen[1:]))  # 매번 바로 앞 버전과 다르다
    assert len(set(seen[:4])) == 4  # 첫 네 버전은 모양이 모두 다르다


def test_redo_keeps_notes_outside_the_range_and_the_sound():
    p = song(C, AM, F, G)
    r, pad = pad_of(p, program=48)
    again, redone = pad_of(r.project, track_id=pad.id, version=2, bars=[3, 4])
    assert redone.program == 48
    assert [n for n in redone.notes if n.start < 8] == [n for n in pad.notes if n.start < 8]
    assert [n for n in redone.notes if n.start >= 8] != [n for n in pad.notes if n.start >= 8]


def test_redo_rejects_unknown_or_drum_tracks():
    p = project("lofi_groove")
    with pytest.raises(ToolError):
        run_tool(p, "generate_chords", {"track_id": "t99", "version": 2})
    drum = next(t for t in p.tracks if t.is_drum)
    with pytest.raises(ToolError):
        run_tool(p, "generate_chords", {"track_id": drum.id, "version": 2})


def test_pad_stays_in_the_chosen_instrument_range():
    # 바이올린(G3~)으로 깔면 창이 낮아도 바이올린이 낼 수 있는 높이에서만
    r, pad = pad_of(song(C, AM, F, G), program=40, height="low")
    low, high = playable(40)
    assert r.checks == [] and all(low <= n.pitch <= high for n in pad.notes)


def test_add_track_makes_an_empty_track():
    p = song(C, AM, F, G)
    r = run_tool(p, "add_track", {})
    t = r.project.tracks[-1]
    assert (t.id, t.name, t.notes, t.is_drum, t.program_set) == ("t3", "Track", [], False, False) and r.changed_settings
    r = run_tool(r.project, "add_track", {"drums": True, "program": 25})
    t = r.project.tracks[-1]
    assert (t.id, t.name, t.is_drum, t.program) == ("t4", "Drums", True, 25) and "TR-808" in r.summary
    r = run_tool(r.project, "add_track", {"program": 73})
    assert r.project.tracks[-1].name == "Track 2" and "플룻" in r.summary


def test_existing_pad_is_not_taken_for_the_bass():
    # 베이스 없이 패드만 있는 곡에 "낮은 패드"를 더 깔면 기존 패드 위가 아니라 그 아래쪽에 (기존 패드를 베이스로 보던 버그)
    p = song(C, AM, F, G)
    p = p.model_copy(update={"tracks": [p.tracks[0]]})  # 건반만
    first = pad_of(p)[1]
    r, low = pad_of(pad_of(p)[0].project, height="low")
    assert sum(n.pitch for n in low.notes) / len(low.notes) < sum(n.pitch for n in first.notes) / len(first.notes)


# ---------- 끊어 치기 · 아르페지오 · 말한 진행 ----------

DRUMS_ONLY = Project(id="p", tracks=[Track(id="t1", name="Drums", is_drum=True, notes=[Note(pitch=36, start=i, duration=0.25) for i in range(16)])])


def chord_tones(chord):
    return {(chord.root + i) % 12 for i in INTERVALS[chord.quality]}


def test_stab_strikes_the_chord_in_a_rhythm():
    p = song(C, AM, F, G)
    r, stab = pad_of(p, pattern="stab")
    assert (stab.name, stab.program) == ("Chords", 0) and r.checks == []  # 건반 편성 → 전자 피아노인데 Keys가 이미 Rhodes라 피아노
    groups = by_start(stab)
    assert [g[0].start for g in groups[:4]] == [0, 1, 2, 3] and all(n.duration == 0.5 for n in stab.notes)  # 버전 1: 박마다
    assert groups[0][0].velocity > groups[1][0].velocity  # 마디 첫 박을 세게
    for chord in analyze(p).chords:
        hits = [g for g in groups if chord.start <= g[0].start < chord.end]
        assert len(hits) == 4 and all({n.pitch % 12 for n in g} <= chord_tones(chord) for g in hits)


def test_stab_versions_change_the_rhythm_and_fit_three_four():
    p = song(C, AM, F, G)
    _, offbeat = pad_of(p, pattern="stab", version=2)
    assert {n.start % 4 for n in offbeat.notes} == {0.5, 1.5, 2.5, 3.5}  # 뒷박
    waltz = song(C, AM, F, G, beats=3, ts=(3, 4))
    _, stab = pad_of(waltz, pattern="stab")
    assert {n.start % 3 for n in stab.notes} == {0, 1, 2}  # 3/4는 마디 안에 드는 박만


def test_arpeggio_plays_one_chord_tone_at_a_time():
    p = song(C, AM, F, G)
    r, arp = pad_of(p, pattern="arpeggio")
    assert arp.name == "Arp" and r.checks == []
    starts = [n.start for n in arp.notes]
    assert starts == [i * 0.5 for i in range(32)]  # 8분음표로 한 음씩, 겹치지 않게
    for chord in analyze(p).chords:
        mine = [n for n in arp.notes if chord.start <= n.start < chord.end]
        assert {n.pitch % 12 for n in mine} <= chord_tones(chord)
        assert [n.pitch for n in mine[:4]] == sorted(n.pitch for n in mine[:4])  # 버전 1: 아래에서 위로
    _, updown = pad_of(p, pattern="arpeggio", version=2)
    first = [n.pitch for n in updown.notes if n.start < 4]
    assert first[:6] == first[:4] + first[2:0:-1]  # 버전 2: 오르내리기


def test_progression_on_a_drum_loop_gets_a_root_underneath():
    # 드럼만 있는 루프에 "C – Am7 – Fmaj7 – G7": 한 마디씩, 곡 길이(4마디)만큼. 베이스가 없으니 맨 아래에 근음
    r, pad = pad_of(DRUMS_ONLY, progression=["C", "Am7", "Fmaj7", "G7"])
    assert r.checks == [] and "C – Am7 – Fmaj7 – G7" in r.summary
    for g, root in zip(by_start(pad), (0, 9, 5, 7)):
        assert g[0].pitch % 12 == root
    # 반 마디씩이면 곡 길이 안에서 되풀이
    r, stab = pad_of(DRUMS_ONLY, pattern="stab", progression=["Dm7", "G7"], bars_per_chord=0.5)
    lowest = {g[0].start: g[0].pitch % 12 for g in by_start(stab)}
    assert [s for s, pc in sorted(lowest.items()) if pc == 2] == [0, 1, 4, 5, 8, 9, 12, 13]  # 박마다, Dm7은 반 마디씩 되풀이


def test_progression_overrides_the_song_chords_in_the_range():
    r, pad = pad_of(song(C, AM, F, G), progression=["Dm7", "G7", "Cmaj7", "A7"], bars=[2, 3])
    assert {n.start for n in pad.notes} == {4, 8} and r.checks == []
    assert {n.pitch % 12 for n in pad.notes if n.start == 4} <= {2, 5, 9, 0}  # 2마디부터 Dm7


def test_progression_rejects_unknown_chord_names():
    with pytest.raises(ToolError) as e:
        run_tool(DRUMS_ONLY, "generate_chords", {"progression": ["C", "Hm"]})
    assert e.value.code == "unknown_chord"
    with pytest.raises(ToolError):
        run_tool(DRUMS_ONLY, "generate_chords", {})  # 진행도 코드도 없으면 진행을 말해 달라고


@pytest.mark.parametrize("text,want", [
    ("C", (0, "", None)), ("Am7", (9, "m7", None)), ("F#m7b5", (6, "m7b5", None)), ("Bbmaj7", (10, "maj7", None)),
    ("C/E", (0, "", 4)), ("Ebm", (3, "m", None)), ("CM7", (0, "maj7", None)), ("Bø", (11, "m7b5", None)), ("G7sus4", (7, "7sus4", None)),
])
def test_parse_chord(text, want):
    assert parse_chord(text) == want


def test_comp_sound_fits_the_band():
    def band(*programs, kit=None):
        tracks = [Track(id=f"t{i}", name="x", program=prog, program_set=True) for i, prog in enumerate(programs, 1)]
        if kit is not None:
            tracks.append(Track(id="d", name="Drums", is_drum=True, program=kit))
        return Project(id="p", tracks=tracks)

    assert comp_program(band(0, 33), "stab") == 4 and comp_program(band(0, 33), "arpeggio") == 4  # 건반 → 전자 피아노
    assert comp_program(band(4, 38), "arpeggio") == 11  # 로파이(Rhodes 있음, 신스 베이스만) → 비브라폰, 톱니파 리드 아님
    assert comp_program(band(80, 38, kit=25), "arpeggio") == 81  # 신스 리드 · 808 킷 → 톱니파 리드
    assert comp_program(band(81, 38), "arpeggio") == 4  # 톱니파 리드가 이미 있으면 다음 후보
    assert comp_program(band(40, 42), "stab") == 0 and comp_program(band(40, 42), "arpeggio") == 46  # 현악 → 피아노 · 하프


@pytest.mark.parametrize("pattern", ["stab", "arpeggio"])
@pytest.mark.parametrize("name", [n.removesuffix(".mid") for n in make_samples.SAMPLES])
def test_comp_on_every_sample_passes_the_checks(name, pattern):
    try:
        r, track = pad_of(project(name), pattern=pattern)
    except ToolError:
        return
    assert r.checks == [], r.checks[:5]


def test_redo_keeps_the_pattern_and_moves_to_the_next_rhythm():
    r, stab = pad_of(song(C, AM, F, G), pattern="stab")
    again, redone = pad_of(r.project, pattern="stab", track_id=stab.id, version=2)
    assert redone.id == stab.id and len(again.project.tracks) == 3
    assert {n.start % 1 for n in redone.notes} == {0.5}
