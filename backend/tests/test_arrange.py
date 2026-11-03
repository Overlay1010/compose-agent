"""곡 읽기(read_song) · 악기 추천(suggest_instruments) · 다른 트랙을 보는 내 샘플 추천."""

from app.arrange import read_song
from app.arrange.read import MUD
from app.arrange.suggest import suggest
from app.models.project import Note, Project, SampleRef, Track
from app.tools.registry import run_tool
from app.tools.samples import SampleInfo, library, recommend


def notes(*specs) -> list[Note]:
    return [Note(pitch=p, start=s, duration=d, velocity=90) for p, s, d in specs]


def piano_duo() -> Project:
    """왈츠처럼 피아노 두 손뿐: 오른손 C5~E5 길게, 왼손 B2~A3 짧게 (베이스 없음)"""
    rh = Track(id="t1", name="Piano RH", program=0, program_set=True,
               notes=notes(*[(72 + (i % 3) * 2, i * 3.0, 2.5) for i in range(8)]))
    lh = Track(id="t2", name="Piano LH", program=0, program_set=True,
               notes=notes(*[(47 + (i % 4) * 3, i * 1.0, 0.4) for i in range(24)]))
    return Project(id="duo", tracks=[rh, lh])


def band() -> Project:
    """베이스 · 패드(길게) · 리드가 있고 C6 위가 빈 곡"""
    bass = Track(id="t1", name="Bass", program=33, notes=notes(*[(36 + (i % 2) * 7, i * 1.0, 0.9) for i in range(16)]))
    pad = Track(id="t2", name="Pad", program=89, notes=notes(*[(p, b * 4.0, 4.0) for b in range(4) for p in (55, 60, 64)]))
    lead = Track(id="t3", name="Lead", program=80, notes=notes(*[(72 + (i % 5), i * 1.0, 1.5) for i in range(16)]))
    return Project(id="band", tracks=[bass, pad, lead])


def test_read_song_finds_roles_character_gaps_and_missing():
    song = read_song(piano_duo())
    assert [t.role for t in song.melodic] == ["keys", "keys"]
    assert [t.character for t in song.melodic] == ["long", "short"]
    assert "bass" in song.missing and "lead" not in song.missing  # 오른손이 C5 위까지 올라가 위 선율은 있음
    assert all(a >= MUD for a, _ in song.gaps)  # 베이스 바로 위 낮은 곳은 채울 자리로 보지 않음
    band_song = read_song(band())
    assert band_song.missing == [] and band_song.flavor == "electronic"
    assert band_song.gaps and band_song.gaps[-1][1] == 96  # 맨 위가 빔
    assert all(a > 36 for a, _ in band_song.gaps)  # 베이스 아래는 빈 높이가 아님
    assert "베이스" in band_song.summary() and "빈 높이" in band_song.summary()


def test_suggest_puts_missing_bass_first_and_skips_used_or_unplayable():
    p = piano_duo()
    slots = suggest(read_song(p), p.id)
    assert slots[0].role == "bass" and "베이스가 없어요" in slots[0].reason
    assert all(c.program not in (0,) for s in slots for c in s.candidates)  # 이미 쓰는 피아노는 안 권함
    assert all(32 <= c.program <= 39 for c in slots[0].candidates)
    for s in slots:
        assert s.low >= 28 and (s.role == "bass" or s.low >= MUD)


def test_suggest_varies_with_version_but_is_stable_per_version():
    p = band()
    one = [[c.program for c in s.candidates] for s in suggest(read_song(p), p.id, version=1)]
    again = [[c.program for c in s.candidates] for s in suggest(read_song(p), p.id, version=1)]
    assert one == again  # 같은 곡 · 같은 버전이면 같다
    versions = {tuple(tuple(x) for x in ([[c.program for c in s.candidates] for s in suggest(read_song(p), p.id, version=v)]))
                for v in range(1, 6)}
    assert len(versions) > 1  # "다른 추천"이면 비슷한 후보의 순서가 바뀐다


def test_suggest_tool_is_read_only_and_says_how_to_make():
    p = piano_duo()
    r = run_tool(p, "suggest_instruments", {})
    assert r.project is None and r.data["slots"][0]["role"] == "bass"
    assert "generate_bassline" in r.summary and "추천 버전 1" in r.summary
    only = run_tool(p, "suggest_instruments", {"role": "pad"})
    assert [s["role"] for s in only.data["slots"]] == ["pad"]


def info(name, kind, root, length=2.0, sustained=False, brightness=0.5) -> SampleInfo:
    return SampleInfo(id=name.lower().replace(" ", "-"), name=name, kind=kind, root=root, length=length, sustained=sustained,
                      brightness=brightness)


PACK = [
    info("Warm Pad C4", "pad", 60, 6, True, 0.3), info("Glass Pad C4", "pad", 60, 6, True, 0.9),
    info("Short Pad C4", "pad", 60, 0.8, False, 0.5), info("Pluck C5", "pluck", 72, 0.6, brightness=0.7),
]


def test_sample_recommend_looks_at_other_tracks():
    p = band()
    pad = p.tracks[1]
    alone = recommend(pad, p.tempo, PACK)
    assert alone[0].sample.name in ("Warm Pad C4", "Glass Pad C4") and alone[-1].sample.name != "Warm Pad C4"
    # 다른 트랙이 이미 쓰는 샘플은 뒤로
    taken = p.model_copy(update={"tracks": [p.tracks[0], pad, p.tracks[2].model_copy(update={"sample": SampleRef(id="glass-pad-c4", name="Glass Pad C4")})]})
    picks = recommend(pad, p.tempo, PACK, project=taken)
    glass = next(x for x in picks if x.sample.name == "Glass Pad C4")
    assert "Lead 트랙이 이미 씀" in glass.reason and picks[0].sample.name != "Glass Pad C4"
    # 짧은 패드는 길게 끄는 패드를 이기지 못한다 (섞기는 점수가 거의 같은 후보끼리만)
    assert all(x.sample.name != "Short Pad C4" for x in recommend(pad, p.tempo, PACK, project=p)[:2])


def test_suggest_lists_my_samples_for_the_slot():
    p = piano_duo()
    with library(PACK):
        r = run_tool(p, "suggest_instruments", {"role": "pad"})
    assert r.data["slots"][0]["my_samples"] and r.data["slots"][0]["my_samples"][0]["name"].endswith("Pad C4")


def test_generators_avoid_the_same_family_at_the_same_height_and_vary_by_song():
    from app.generate.bass import bass_program
    from app.generate.chords import comp_program

    piano = Track(id="t1", name="Piano", program=0, program_set=True, notes=notes(*[(60 + i % 7, i * 1.0, 1.0) for i in range(16)]))
    picks = {comp_program(Project(id=i, tracks=[piano]), "stab") for i in "abcdefghij"}
    assert picks and all(p // 8 != 0 for p in picks)  # 피아노 곡의 반주에 전자 피아노 · 피아노(같은 건반 계열)는 안 고름
    assert len(picks) > 1  # 곡마다 다르게
    # 베이스는 스타일마다 정한 소리를 지킨다 (옥타브 → 슬랩, 워킹 → 콘트라베이스)
    assert bass_program(Project(id="x", tracks=[piano]), "octave") == 36
    assert bass_program(Project(id="x", tracks=[piano]), "walking") == 32
    # 베이스를 하나 더 깔 때 같은 소리는 겹치지 않게
    finger = Track(id="t2", name="Bass", program=33, program_set=True, notes=notes((36, 0, 1)))
    assert bass_program(Project(id="x", tracks=[piano, finger])) != 33
