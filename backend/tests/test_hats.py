"""vary_hats: 깔린 하이햇을 군데군데 비우기 · 열린 햇 늘리기 · 줄이기."""

import pytest

from app.models.project import Note, Project, Track
from app.tools.base import ToolError
from app.tools.registry import run_tool


def hat_song(bars: int = 8, roll_bar: int | None = 2) -> Project:
    """8분 닫힌 햇 + 킥, roll_bar 마디의 4박에 32분 롤"""
    notes: list[Note] = []
    for bar in range(bars):
        for i in range(8):
            pos = bar * 4 + i * 0.5
            if roll_bar is not None and bar == roll_bar - 1 and i >= 6:
                continue
            notes.append(Note(pitch=42, start=pos, duration=0.1, velocity=90))
        notes.append(Note(pitch=36, start=bar * 4, duration=0.2, velocity=110))
    if roll_bar is not None:
        notes += [Note(pitch=42, start=(roll_bar - 1) * 4 + 3 + j * 0.125, duration=0.1, velocity=50 + j * 10) for j in range(8)]
    return Project(id="p", tracks=[
        Track(id="t1", name="Hats", is_drum=True, notes=sorted(notes, key=lambda n: (n.start, n.pitch))),
        Track(id="t2", name="Bass", program=33, notes=[Note(pitch=40, start=0, duration=4, velocity=90)]),
    ])


def hats(p: Project, pitch: int = 42) -> list[float]:
    return [n.start for n in p.tracks[0].notes if n.pitch == pitch]


def test_space_leaves_holes_in_different_places_and_keeps_downbeats_rolls():
    p = hat_song()
    r = run_tool(p, "vary_hats", {"space": "little"})
    before, after = set(hats(p)), set(hats(r.project))
    gone = sorted(before - after)
    assert 3 <= len(gone) <= 16, gone  # 조금만 (64타 중)
    assert not after - before
    assert all(b % 4 > 1e-6 for b in gone)  # 마디 첫 박은 그대로
    assert all(b not in gone for b in [7 + j * 0.125 for j in range(8)])  # 롤은 그대로
    slots = [b % 4 for b in gone]
    assert len(set(slots)) > 1  # 마디마다 같은 자리가 비면 또 규칙처럼 들린다
    # 한 마디에 한 박 넘게 비지 않는다
    for bar in range(8):
        starts = sorted([bar * 4.0, *[b for b in after if bar * 4 <= b < bar * 4 + 4], bar * 4 + 4.0])
        assert max(b - a for a, b in zip(starts, starts[1:])) <= 1.0 + 1e-6
    assert [n for n in r.project.tracks[0].notes if n.pitch == 36] == [n for n in p.tracks[0].notes if n.pitch == 36]
    assert "군데군데 비웠어요" in r.summary


def test_more_space_removes_more_than_little():
    p = hat_song(16, None)
    little = len(hats(p)) - len(hats(run_tool(p, "vary_hats", {"space": "little"}).project))
    more = len(hats(p)) - len(hats(run_tool(p, "vary_hats", {"space": "more"}).project))
    assert more > little > 0


def test_open_more_adds_open_hats_and_keeps_every_closed_hat():
    p = hat_song()
    r = run_tool(p, "vary_hats", {"open_hats": "more"})
    assert hats(r.project) == hats(p)  # 닫힌 햇은 하나도 안 바뀜
    opened = hats(r.project, 46)
    assert len(opened) >= 4 and all((b % 4) in (0.5, 1.5, 2.5, 3.5) for b in opened)
    assert not any(6.8 < b < 8.0 for b in opened)  # 2마디 4박의 롤 안에는 안 넣음
    assert "닫힌 햇은 그대로" in r.summary
    # 비운 자리가 있으면 빈 뒷박을 먼저 채운다
    spaced = run_tool(p, "vary_hats", {"space": "more"}).project
    filled = run_tool(spaced, "vary_hats", {"open_hats": "more"})
    assert hats(filled.project) == hats(spaced)
    assert "빈 뒷박" in filled.summary


def test_open_swap_turns_offbeats_into_open_hats_and_lets_them_ring():
    p = hat_song()
    r = run_tool(p, "vary_hats", {"open_hats": "swap"})
    opened = hats(r.project, 46)
    assert len(opened) >= 4
    assert all((b % 4) in (0.5, 1.5, 2.5, 3.5) for b in opened)
    assert all(n.velocity >= 80 for n in r.project.tracks[0].notes if n.pitch == 46)
    closed = hats(r.project)
    assert not any(b < c < b + 0.3 for b in opened for c in closed)  # 바로 뒤 햇이 열린 햇을 끊지 않게
    assert len(hats(p)) - len(closed) == len(opened)  # 비우기는 안 했다 (8분이라 뒤 16분 햇은 없음)


def test_open_fewer_and_version_and_bars():
    p = run_tool(hat_song(), "vary_hats", {"open_hats": "swap"}).project
    fewer = run_tool(p, "vary_hats", {"open_hats": "fewer"})
    assert 0 < len(hats(fewer.project, 46)) < len(hats(p, 46))
    a = run_tool(hat_song(), "vary_hats", {"space": "little", "version": 1}).project
    b = run_tool(hat_song(), "vary_hats", {"space": "little", "version": 2}).project
    assert hats(a) != hats(b)
    ranged = run_tool(hat_song(), "vary_hats", {"space": "more", "bars": [3, 4]})
    assert {int(x // 4) + 1 for x in set(hats(hat_song())) - set(hats(ranged.project))} <= {3, 4}
    assert "3~4마디" in ranged.summary


def test_errors():
    p = hat_song()
    with pytest.raises(ToolError):
        run_tool(p, "vary_hats", {"space": "little", "track_ids": ["t2"]})
    with pytest.raises(ToolError):
        run_tool(p, "vary_hats", {})  # 아무것도 안 바꿈
    no_hats = p.model_copy(update={"tracks": [p.tracks[1]]})
    with pytest.raises(ToolError):
        run_tool(no_hats, "vary_hats", {"space": "little"})
