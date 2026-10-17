"""음을 지우거나 · 길이를 바꾸거나 · 마디를 복사하는 도구: delete_notes, set_length, copy_bars.

모두 (Project, Args) -> ToolResult 순수 함수. 시간은 박 단위.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.models.project import Note, Project
from app.tools.base import Bar, Selection, ToolError, ToolResult, edit_notes, result, round_beat

MIN_LENGTH = 0.0625  # 64분음표. 이보다 짧으면 소리가 거의 안 난다
MAX_BARS = 512  # 복사로 곡이 끝없이 길어지지 않게


def _bar_text(bars: tuple[int, int] | None) -> str:
    if bars is None:
        return ""
    return f"{bars[0]}마디" if bars[0] == bars[1] else f"{bars[0]}~{bars[1]}마디"


# ---------- delete_notes ----------


class DeleteNotesArgs(Selection):
    @model_validator(mode="after")
    def _not_everything(self) -> "DeleteNotesArgs":
        if self.track_ids is None and self.bars is None and self.pitches is None:
            raise ValueError("곡 전체를 지울 수는 없어요. track_ids · bars · pitches 중 하나 이상으로 범위를 정해 주세요.")
        return self


def delete_notes(project: Project, args: DeleteNotesArgs) -> ToolResult:
    ids = {t.id for t in args.tracks(project)}
    bpb = project.beats_per_bar
    new = project.model_copy(deep=True)
    counts: list[tuple[str, int]] = []
    for track in new.tracks:
        if track.id not in ids:
            continue
        kept = [n for n in track.notes if not args.has(n, bpb)]
        if len(kept) != len(track.notes):
            counts.append((track.name, len(track.notes) - len(kept)))
            track.notes = kept
    where = f" ({_bar_text(args.bars)})" if args.bars else ""
    return result(new, counts, f"을 지웠어요{where}.", "선택한 범위에 지울 음이 없어요.")


# ---------- set_length ----------

LENGTH_LIMITS = {"scale": (0.1, 4.0), "set": (MIN_LENGTH, 16.0)}


class SetLengthArgs(Selection):
    mode: Literal["scale", "set", "legato"] = Field(
        description="scale = 길이에 곱하기 (0.5면 절반 = 스타카토), set = 모두 같은 길이(박), "
        "legato = 다음 음이 시작할 때까지 늘려 음 사이 빈틈을 없앤다 (짧아지지는 않음)"
    )
    value: float | None = Field(default=None, description="scale: 0.1~4, set: 0.0625~16박 (1 = 4분음표). legato에는 안 씀")

    @model_validator(mode="after")
    def _check_value(self) -> "SetLengthArgs":
        if self.mode == "legato":
            return self
        if self.value is None:
            raise ValueError(f"{self.mode} 모드에는 value가 필요해요.")
        lo, hi = LENGTH_LIMITS[self.mode]
        if not lo <= self.value <= hi:
            raise ValueError(f"{self.mode} 모드의 value는 {lo:g}~{hi:g} 사이여야 해요.")
        return self


def set_length(project: Project, args: SetLengthArgs) -> ToolResult:
    # 드럼 샘플은 길이와 상관없이 끝까지 울리므로 길이를 바꿔도 소리가 같다. 그래서 건너뛴다.
    if args.mode == "legato":
        # 트랙마다 "다음 음 시작" 위치를 미리 구한다 (화음이면 같은 시작의 음들은 함께 다음 화음까지)
        onsets = {t.id: sorted({n.start for n in t.notes}) for t in project.tracks}

    def change(track_id: str):
        def fn(note: Note) -> Note:
            if args.mode == "scale":
                length = note.duration * (args.value or 1)
            elif args.mode == "set":
                length = args.value or note.duration
            else:
                later = [s for s in onsets[track_id] if s > note.start + 1e-6]
                if not later:
                    return note  # 마지막 음은 그대로
                length = max(note.duration, later[0] - note.start)
            return note.model_copy(update={"duration": round_beat(max(MIN_LENGTH, length))})

        return fn

    new = project
    counts: list[tuple[str, int]] = []
    for track in args.tracks(project):
        if track.is_drum:
            continue
        one = args.model_copy(update={"track_ids": [track.id]})
        new, c = edit_notes(new, one, change(track.id))
        counts += c

    if args.mode == "scale":
        how = f"{args.value * 100:.0f}%로 {'줄였어요' if args.value < 1 else '늘렸어요'}"
    elif args.mode == "set":
        how = f"모두 {args.value:g}박으로 맞췄어요"
    else:
        how = "다음 음까지 이어지게 늘렸어요"
    res = result(new, counts, f"의 길이를 {how}.", "선택한 음의 길이가 이미 그래서 바뀐 게 없어요.")
    drums = [t.name for t in args.tracks(project) if t.is_drum]
    if args.track_ids and drums:
        res.summary += f" 드럼 트랙({', '.join(drums)})은 길이가 소리에 영향이 없어 건너뛰었어요."
    return res


# ---------- copy_bars ----------


class CopyBarsArgs(Selection):
    bars: tuple[Bar, Bar] = Field(description="복사할 마디 범위 [시작, 끝]. 1부터 세고 끝 마디도 포함")
    to_bar: Bar = Field(description="붙여 넣을 첫 마디")
    times: int = Field(default=1, ge=1, le=16, description="몇 번 이어 붙일지. 2면 to_bar부터 두 번 연달아")
    overwrite: bool = Field(default=True, description="붙여 넣을 자리에 있던 음을 지울지 (기본). false면 겹쳐 넣는다")


def copy_bars(project: Project, args: CopyBarsArgs) -> ToolResult:
    first, last = args.bars
    span = last - first + 1
    target = (args.to_bar, args.to_bar + span * args.times - 1)
    if target[0] <= last and target[1] >= first:
        raise ToolError(
            f"붙여 넣을 자리({_bar_text(target)})가 복사할 마디({_bar_text(args.bars)})와 겹쳐요. "
            f"반복하려면 to_bar를 {last + 1}로 두고 times로 횟수를 정해요.",
            code="overlap",
        )
    if target[1] > MAX_BARS:
        raise ToolError(f"곡이 {MAX_BARS}마디를 넘게 돼요 (붙여 넣으면 {target[1]}마디까지).", code="out_of_range")

    bpb = project.beats_per_bar
    shift = (args.to_bar - first) * bpb
    clear = args.model_copy(update={"bars": target})
    ids = {t.id for t in args.tracks(project)}
    new = project.model_copy(deep=True)
    copied = removed = 0
    names: list[str] = []
    for track in new.tracks:
        if track.id not in ids:
            continue
        source = [n for n in track.notes if args.has(n, bpb)]
        if not source:
            continue
        kept = [n for n in track.notes if not (args.overwrite and clear.has(n, bpb))]
        removed += len(track.notes) - len(kept)
        pasted = [
            n.model_copy(update={"start": round_beat(n.start + shift + k * span * bpb)})
            for k in range(args.times)
            for n in source
        ]
        track.notes = sorted(kept + pasted, key=lambda n: (n.start, n.pitch))
        copied += len(pasted)
        names.append(track.name)

    if not copied:
        return ToolResult(project=project, summary=f"{_bar_text(args.bars)}에 복사할 음이 없어요.")
    times = f" {args.times}번" if args.times > 1 else ""
    gone = f" 그 자리에 있던 음 {removed}개는 지웠어요." if removed else ""
    return ToolResult(
        project=new,
        changed_notes=copied + removed,
        summary=f"{', '.join(names)} 트랙 {_bar_text(args.bars)}를 {_bar_text(target)}에{times} 복사했어요 (음 {copied}개).{gone}",
    )
