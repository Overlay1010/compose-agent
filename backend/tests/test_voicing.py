from app.harmony import ChordSpan, analyze
from app.harmony.reharm import suggest
from app.harmony.voicing import apply_progression, bass_note, fill_tone, revoice, untangle
from app.models.project import Note, Project, Track

from tests.test_harmony import song
from tests.test_reharm import AM, C, F, G, project, with_melody


def chord(name: str, root: int, quality: str, start: float = 0, end: float = 4) -> ChordSpan:
    return ChordSpan(start, end, root, root, name, quality, "", "", 0.0)


def applied(p, style: str):
    a, ss = suggest(p)
    s = next(s for s in ss if s.style == style)
    new, counts = apply_progression(p, a.chords, s.chords)
    return s, new, counts


def test_every_style_reads_back_as_the_suggestion():
    # 바꾼 곡을 분석 엔진으로 다시 읽으면 제안한 코드가 나온다 (건반 3음 + 베이스)
    for style in ("가볍게", "재지하게", "색다르게"):
        s, new, _ = applied(song(C, AM, F, G), style)
        assert [c.name for c in analyze(new).chords] == [c.name for c in s.chords], style


def test_keys_drop_the_root_to_fit_the_ninth():
    # 베이스가 근음을 치니 건반 3음은 3 · 7 · 9음 (Cmaj9 = E B D) — 근음 · 5음부터 넣으면 9음이 빠져 Cmaj7로 들린다
    assert sorted(p % 12 for p in revoice([60, 64, 67], chord("Cmaj9", 0, "maj9"))) == [2, 4, 11]
    # 덜 움직이게: 원래 음 가까이 (C E G → D E B, 한 음씩 2반음 이내)
    assert all(abs(a - b) <= 4 for a, b in zip([60, 64, 67], revoice([60, 64, 67], chord("Cmaj9", 0, "maj9"))))


def test_inserted_dominant_splits_held_notes():
    # 재지하게: C 한 마디의 뒤 반 마디에 E7(V7/vi)을 끼우면, 한 마디 내내 누른 건반 · 베이스를 2박에서 나눈다
    _, new, _ = applied(song(C, AM, F, G), "재지하게")
    keys, bass = new.tracks[0], new.tracks[1]
    assert sorted(n.pitch for n in keys.notes if n.start == 0) and all(n.duration == 2 for n in keys.notes if n.start == 0)
    assert {n.pitch % 12 for n in keys.notes if n.start == 2} >= {8, 2}  # E7의 3음 G# · 7음 D
    assert [(n.pitch, n.start, n.duration) for n in bass.notes if n.start < 4] == [(48, 0, 2), (52, 2, 2)]  # C → E


def test_melody_and_drums_stay():
    p = with_melody(song(C, AM, F, G, drums=True), (79, 0, 4), (81, 4, 4), (77, 8, 4), (79, 12, 4))
    _, new, counts = applied(p, "재지하게")
    by_id = {t.id: t for t in new.tracks}
    assert by_id["m"].notes == next(t for t in p.tracks if t.id == "m").notes
    assert by_id["t3"].notes == next(t for t in p.tracks if t.id == "t3").notes
    assert set(counts) == {"Keys", "Bass"}


def test_bass_moves_with_the_root_and_keeps_chord_degrees():
    # 근음 차이만큼 가까운 쪽으로 (G → Db = −6), 지나가는 음 모양은 그대로
    g7, db7 = chord("G7", 7, "7"), chord("Db7", 1, "7")
    assert [bass_note(p, g7, db7) for p in (43, 45, 47)] == [37, 39, 41]
    # 원래 코드 음이었으면 새 코드의 같은 자리로: Dm9 → Dm7b5에서 5음 A는 b5 Ab로 (그대로 두면 Ab과 부딪힌다)
    assert bass_note(45, chord("Dm9", 2, "m9"), chord("Dm7b5", 2, "m7b5")) == 44


def test_keys_only_track_puts_the_new_root_at_the_bottom():
    # 베이스 트랙 없이 건반이 F A C(기본 자리)를 치면, Dm9로 바꿀 때 맨 아래도 D로 — 그대로 두면 F A C E = Fmaj7로 들린다
    keys = [Note(pitch=p, start=i * 4, duration=4) for i, ch in enumerate([[48, 52, 55], [53, 57, 60], [55, 59, 62], [48, 52, 55]]) for p in ch]
    p = Project(id="p", tracks=[Track(id="t1", name="Keys", notes=keys)])
    a, ss = suggest(p)
    light = next(s for s in ss if s.style == "가볍게")
    new, _ = apply_progression(p, a.chords, light.chords)
    assert min(n.pitch for n in new.tracks[0].notes if n.start == 4) % 12 == 2  # D
    # 세 음뿐이라 근음 D + 3음 · 7음까지 담고, 빠진 9음 E는 같은 박 · 길이로 한 음 더한다 (음이 하나 늘어남)
    at4 = [n for n in new.tracks[0].notes if n.start == 4]
    assert len(at4) == 4 and all(n.duration == 4 for n in at4) and 4 in {n.pitch % 12 for n in at4}
    assert [c.name for c in analyze(new).chords][1] == "Dm9"


def test_fill_tone_adds_one_missing_color_tone():
    # 근음 없는 3음(E G B)에 Cmaj9: 9음 D를 묶음 위에 (안쪽엔 반음으로 붙지 않는 자리가 없다)
    assert fill_tone([64, 67, 71], chord("Cmaj9", 0, "maj9")) == 74
    # 빠진 게 없으면 더하지 않는다 (근음 · 5음은 베이스 · 다른 음이 채운다)
    assert fill_tone([64, 71, 74], chord("Cmaj9", 0, "maj9")) is None
    # 3 · 7음이 먼저: 3화음 모양(C E G)에 C7이면 7음 Bb
    assert fill_tone([60, 64, 67], chord("C7", 0, "7")) % 12 == 10
    # 한 음뿐(윗선율 · 펼친 음)이면 그 아래에 — 선율 위로 올라가지 않게
    assert fill_tone([79], chord("Cmaj9", 0, "maj9"), have={0, 4, 7, 11}) < 79


def test_waltz_reads_back_with_tritone_sub():
    # 베이스 트랙 없는 왈츠 왼손("쿵-짝-짝", 짝 화음이 쿵보다 낮을 때도 있다): 쿵을 근음으로 옮긴다
    p = project("waltz_3_4")
    s, new, _ = applied(p, "재지하게")
    back = analyze(new).chords
    assert [c.name for c in back if c.name.startswith("Ab")] == ["Ab7", "Ab7"]
    assert [c.start for c in back] == [c.start for c in s.chords]


def test_anticipated_chord_is_not_cut_at_the_bar_line():
    # 1박 먼저 친 화음(3박에 쳐서 3박 누름)은 마디선에서 자르지 않고 처음부터 새 코드 음으로 — 자르면 같은 음을 다시 치거나
    # 누르던 음이 중간에 바뀐다 (Astroworld의 Eb). 음높이가 그대로인 음은 한 음으로 남는다
    eb = [Note(pitch=p, start=3, duration=3) for p in (39, 51, 63)]
    dm = [Note(pitch=p, start=0, duration=3) for p in (38, 50, 62)] + [Note(pitch=p, start=6, duration=2) for p in (38, 50, 62)]
    p = Project(id="p", tracks=[Track(id="t1", name="Keys", notes=dm + eb)])
    old, new = chord("Eb", 3, "", 4, 6), chord("Ebmaj7", 3, "maj7", 4, 6)
    out, _ = apply_progression(p, [chord("Dm", 2, "m", 0, 4), old, chord("Dm", 2, "m", 6, 8)], [chord("Dm", 2, "m", 0, 4), new, chord("Dm", 2, "m", 6, 8)])
    moved = sorted((n.pitch, n.start, n.duration) for n in out.tracks[0].notes if n.start == 3)
    assert len(moved) >= 3 and all(d == 3 for _, _, d in moved)  # 자르지 않음 (빠진 7음을 더한 음도 같은 박 · 길이)
    assert not [n for n in out.tracks[0].notes if n.start == 4]  # 마디선에서 다시 치지 않음


def test_melody_line_in_a_chord_track_keeps_its_passing_tones():
    # 한 트랙에 섞인 윗선율의 짧은 지나가는 음(96 C · 93 A)은 그대로 — 가까운 코드 음으로 몰면 같은 음 되풀이가 된다
    keys = [Note(pitch=p, start=0, duration=4) for p in (39, 51, 63)] + [
        Note(pitch=q, start=i * 0.5, duration=0.5) for i, q in enumerate((98, 96, 94, 93))
    ]
    p = Project(id="p", tracks=[Track(id="t1", name="Keys", notes=keys)])
    out, _ = apply_progression(p, [chord("Eb", 3, "", 0, 4)], [chord("Ebmaj9", 3, "maj9", 0, 4)])
    assert [n.pitch for n in sorted(out.tracks[0].notes, key=lambda n: n.start) if n.pitch > 90] == [98, 96, 94, 93]


def test_moved_notes_never_overlap_the_same_pitch():
    # 길게 누른 E3 위에서 펼친 음이 E3로 옮겨지면 앞 음을 그 자리에서 끊는다 (MIDI에서 앞 음의 끝이 뒤 음을 끊지 않게)
    held, moved = Note(pitch=52, start=0, duration=4), Note(pitch=52, start=0.5, duration=0.5)
    out = untangle([held, moved], before={(52, 0, 4)})
    assert [(n.start, n.duration) for n in out] == [(0, 0.5), (0.5, 0.5)]
    # 시작도 같으면 짧은 쪽을 버리고, 원래 곡에 있던 겹침은 그대로
    assert len(untangle([held, Note(pitch=52, start=0, duration=1)], before={(52, 0, 4)})) == 1
    assert len(untangle([held, moved], before={(52, 0, 4), (52, 0.5, 0.5)})) == 2


def test_passing_note_moved_onto_a_held_tone_does_not_overlap_it():
    # Em(E G B를 누름) 위로 반 박 지나가는 F4를 Cmaj7로 바꾸면 F가 E와 반음으로 부딪혀 E4로 옮겨진다 → 누르던 E4는 거기서 끊는다
    keys = [Note(pitch=p, start=0, duration=4) for p in (40, 64, 67, 71)] + [Note(pitch=65, start=0.5, duration=0.5)]
    p = Project(id="p", tracks=[Track(id="t1", name="Keys", notes=keys)])
    out, _ = apply_progression(p, [chord("Em", 4, "m")], [chord("Cmaj7", 0, "maj7")])
    e4 = sorted((n.start, n.duration) for n in out.tracks[0].notes if n.pitch == 64)
    assert e4 == [(0, 0.5), (0.5, 0.5)]
