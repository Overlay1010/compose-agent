import pytest

from app.generate.check import check, playable
from app.generate.chords import pad_notes, pad_program
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
