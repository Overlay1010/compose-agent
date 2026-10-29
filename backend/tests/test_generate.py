import pytest

from app.generate.chords import pad_notes, pad_program
from app.harmony import analyze
from app.harmony.reharm import INTERVALS
from app.models.project import Note, Project, Track
from app.tools import ToolError, run_tool

from tests.test_harmony import song
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
