import pytest

from app.generate.bass import ROOT_LOW, bass_program, kick_hits
from app.generate.check import SCALES
from app.harmony import analyze
from app.models.project import Note, Project, Track
from app.tools import ToolError, run_tool

from tests.test_harmony import make_samples, song
from tests.test_reharm import AM, C, F, G, project


def bass_of(p, **args):
    r = run_tool(p, "generate_bassline", args)
    return r, r.project.tracks[-1]


def with_kicks(p: Project, beats: list[float], kit: int = 0) -> Project:
    drums = Track(id="d", name="Drums", is_drum=True, program=kit, notes=[Note(pitch=36, start=b, duration=0.25) for b in beats])
    return p.model_copy(update={"tracks": [*p.tracks, drums]})


def keys_only():
    p = song(C, AM, F, G)
    return p.model_copy(update={"tracks": [p.tracks[0]]})


def at(track, beat):
    return next(n for n in track.notes if abs(n.start - beat) < 1e-6)


@pytest.mark.parametrize("style", ["root", "root_fifth", "octave", "walking"])
def test_every_chord_starts_on_its_root_in_the_bass_register(style):
    p = keys_only()
    r, bass = bass_of(p, style=style)
    assert r.checks == [] and bass.name == "Bass"
    for chord in analyze(p).chords:
        first = at(bass, chord.start)
        assert first.pitch % 12 == chord.root and ROOT_LOW <= first.pitch <= 47
    assert all(n.pitch < 60 for n in bass.notes)


def test_root_style_sits_in_e1_to_d_sharp_2():
    _, bass = bass_of(keys_only())
    roots = [n.pitch for n in bass.notes if n.pitch % 12 in (0, 9, 5, 7)]
    assert roots and all(28 <= q <= 39 for q in roots)


def test_bass_locks_to_the_kick():
    # 킥 0 · 1.5 · 2.5 (마디마다): 베이스도 그 자리에 친다. 어긋난 킥(1.47)은 16분음표 격자로
    kicks = [b * 4 + o for b in range(4) for o in (0, 1.47, 2.5)]
    r, bass = bass_of(with_kicks(keys_only(), kicks))
    assert r.checks == [] and sorted({n.start % 4 for n in bass.notes}) == [0, 1.5, 2.5]
    assert all(n.duration <= 2 for n in bass.notes)


def test_other_version_leaves_the_kick_for_a_set_rhythm():
    p = with_kicks(keys_only(), [b * 4 for b in range(4)])
    made, first = bass_of(p)
    assert sorted({n.start % 4 for n in first.notes}) == [0]  # 버전 1: 킥(마디 첫 박)에
    r, redone = bass_of(made.project, track_id=first.id, version=2)
    assert redone.id == first.id and len(r.project.tracks) == len(made.project.tracks) and "버전 2" in r.summary and r.checks == []
    assert sorted({n.start % 4 for n in redone.notes}) == [0, 1.5, 2.5]  # 킥(마디 첫 박)이 아닌 "쿵 - 따 쿵"


def test_dense_kicks_fall_back_to_a_rhythm():
    p = with_kicks(keys_only(), [i * 0.25 for i in range(64)])  # 16분음표마다 킥
    assert kick_hits(p, 0, 16) == []


def test_short_last_note_leads_into_the_next_root():
    # 버전 4(당겨서): 마디 끝 4분음표(3박)가 다음 근음의 반음 · 온음 옆 음계 음
    p = keys_only()
    _, bass = bass_of(p, version=4)
    chords = analyze(p).chords
    scale = {(analyze(p).key.tonic + i) % 12 for i in SCALES[analyze(p).key.mode]}
    for c, nxt in zip(chords, chords[1:]):
        lead = at(bass, c.end - 1)
        assert 1 <= abs(lead.pitch - at(bass, nxt.start).pitch) <= 2 and lead.pitch % 12 in scale


def test_walking_walks_toward_the_next_root():
    p = project("fl_style_loose")
    r, bass = bass_of(p, style="walking")
    assert r.checks == [] and all(n.duration == 1 for n in bass.notes)
    leaps = [abs(a.pitch - b.pitch) for a, b in zip(bass.notes, bass.notes[1:])]
    assert max(leaps) <= 7 and 0 not in leaps  # 크게 뛰거나 같은 음을 되풀이하지 않는다


def test_slash_chord_plays_its_bass_note():
    drums = with_kicks(Project(id="p", tracks=[]), [b * 4 for b in range(4)])
    r, bass = bass_of(drums, progression=["C/E", "F", "G", "C"])
    assert at(bass, 0).pitch % 12 == 4 and at(bass, 4).pitch % 12 == 5 and r.checks == []


def test_bass_sound_fits_the_band():
    def band(*programs, kit=None):
        tracks = [Track(id=f"t{i}", name="x", program=prog, program_set=True) for i, prog in enumerate(programs, 1)]
        if kit is not None:
            tracks.append(Track(id="d", name="Drums", is_drum=True, program=kit))
        return Project(id="p", tracks=tracks)

    assert bass_program(band(0)) == 33  # 피아노 → 핑거 베이스
    assert bass_program(band(40, 42)) == 32  # 현악 → 어쿠스틱(콘트라) 베이스
    assert bass_program(band(81, kit=25)) == 38  # 신스 → 신스 베이스


def test_no_chords_no_bass():
    with pytest.raises(ToolError) as e:
        run_tool(with_kicks(Project(id="p", tracks=[]), [0, 4]), "generate_bassline", {})
    assert e.value.code == "no_chords"


@pytest.mark.parametrize("style", ["root", "root_fifth", "octave", "walking"])
@pytest.mark.parametrize("name", [n.removesuffix(".mid") for n in make_samples.SAMPLES])
def test_bass_on_every_sample_passes_the_checks(name, style):
    r, _ = bass_of(project(name), style=style)
    assert r.checks == [], r.checks[:5]
