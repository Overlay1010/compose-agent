"""화성 도구: analyze_harmony · suggest_reharmonization (읽기만) · apply_chords (편집).

- analyze_harmony: 조성 · 코드 · 로마숫자 · 화성 기능을 읽는다
- suggest_reharmonization: 색깔이 다른 대리코드 진행 3개 (멜로디와 센 부딪힘은 뺀 것)
- apply_chords: 그 제안대로 건반 · 패드 · 베이스 음을 바꾼다 (편집 도구 — 미리보기로)

계산은 app/harmony가 하고, 에이전트는 결과를 설명만 한다 (음 목록을 보고 코드를 짐작하지 않게).
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.harmony import ChordSpan, analyze
from app.harmony.reharm import Suggestion, suggest
from app.harmony.voicing import apply_progression
from app.models.project import Project
from app.tools.base import NOTHING_CHANGED, Bar, ToolError, ToolResult

FUNCTION_KO = {
    "T": "토닉",
    "S": "서브도미넌트",
    "D": "도미넌트",
    "부속": "부속 딸림화음",
    "차용": "차용 화음",
    "": "코드 없음",
}


class AnalyzeHarmonyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bars: tuple[Bar, Bar] | None = Field(
        default=None, description="이 마디 범위의 코드만 [시작, 끝] (끝 포함). 조성은 언제나 곡 전체로 정한다. 없으면 곡 전체"
    )
    beats: tuple[float, float] | None = Field(
        default=None, description="박 범위 [시작, 끝) — 화면에서 고른 부분처럼 마디 중간부터일 때. bars와 함께 쓰지 마"
    )

    @model_validator(mode="after")
    def _check(self) -> "AnalyzeHarmonyArgs":
        if self.bars and self.bars[0] > self.bars[1]:
            raise ValueError("bars는 [시작, 끝] 순서여야 해요 (시작 <= 끝).")
        if self.beats and (self.beats[0] < 0 or self.beats[0] >= self.beats[1]):
            raise ValueError("beats는 [시작, 끝) 순서여야 해요 (0 <= 시작 < 끝).")
        if self.bars and self.beats:
            raise ValueError("bars와 beats는 함께 쓸 수 없어요. 하나만 써요.")
        return self


def certainty(confidence: float) -> str:
    """1등과 2등 조성 점수 차 → 말. 낮으면 다음 후보도 함께 말하게 한다."""
    return "높음" if confidence >= 0.2 else "보통" if confidence >= 0.08 else "낮음"


NO_NOTES = "화음을 읽을 음이 없어요 (드럼만 있거나 음이 없음)."


def _range(args: AnalyzeHarmonyArgs, bpb: float, song_end: float) -> tuple[float, float]:
    if args.bars:
        return (args.bars[0] - 1) * bpb, args.bars[1] * bpb
    if args.beats:
        return args.beats
    return 0.0, song_end


def _where(beat: float, bpb: float) -> str:
    bar = int(beat // bpb) + 1
    rest = beat - (bar - 1) * bpb
    return f"{bar}마디" if abs(rest) < 1e-6 else f"{bar}마디 {rest + 1:g}박"


def analyze_harmony(project: Project, args: AnalyzeHarmonyArgs | None = None) -> ToolResult:
    args = args or AnalyzeHarmonyArgs()
    a = analyze(project)
    if not a.chords:
        return ToolResult(summary=NO_NOTES, data={"key": None, "chords": []})

    bpb = a.beats_per_bar
    start, end = _range(args, bpb, a.chords[-1].end)
    chords = [c for c in a.chords if c.end > start + 1e-6 and c.start < end - 1e-6]
    if not chords:
        raise ToolError(f"그 범위에는 음이 없어요. 곡은 {project.bar_count}마디예요.", code="empty_range")

    def where(beat: float) -> str:
        return _where(beat, bpb)

    rows = [
        f"{where(c.start)} {c.name}" + (f" ({c.roman}, {FUNCTION_KO[c.function]})" if c.roman else "")
        for c in chords
    ]
    k = a.key
    whole = len(chords) == len(a.chords)
    # 물어본 범위 이름: "9~12마디", "16마디", "5마디 3박~6마디"
    a0, a1 = max(start, chords[0].start), min(end, chords[-1].end)
    first, last = int(a0 // bpb) + 1, int((a1 - 1e-6) // bpb) + 1
    if whole:
        span = "곡 전체"
    elif abs(a0 % bpb) > 1e-6:
        span = f"{where(a0)}~{last}마디"
    else:
        span = f"{first}마디" if first == last else f"{first}~{last}마디"
    return ToolResult(
        summary=f"조성 {k.name} · {span} 코드 {len(chords)}개",
        data={
            "key": k.name,  # 답에도 이 이름 그대로 ("C 장조"로 바꾸지 않음)
            "key_certainty": certainty(k.confidence),
            "other_keys": k.alternatives,  # 확실도가 낮으면 함께 말할 후보
            "chords": rows,  # 같은 코드가 이어지면 하나로 합쳐 있다 (다음 코드 시작 전까지 계속)
            "progression": " → ".join(c.name for c in chords),
        },
    )


class SuggestReharmonizationArgs(AnalyzeHarmonyArgs):
    bars: tuple[Bar, Bar] | None = Field(default=None, description="이 마디 범위의 코드만 바꿔 [시작, 끝] (끝 포함). 없으면 곡 전체")


FEEL = {
    "가볍게": "같은 기능 코드 · 텐션만 더해 원래 느낌 그대로 조금 더 풍성하게",
    "재지하게": "다음 코드로 끌어당기는 딸림7을 끼우고, 으뜸화음 앞은 트라이톤 대리",
    "색다르게": "같은 으뜸음의 반대 조에서 빌려온 화음으로 분위기를 바꿈",
}
MAX_CHANGES = 8  # LLM에 보내는 바꾼 곳 목록 (긴 곡은 되풀이가 많다. 화면에는 모두)


def _chord_view(c: ChordSpan) -> dict:
    return {"start": c.start, "end": c.end, "name": c.name, "roman": c.roman, "function": c.function}


def _suggestions(project: Project, args: SuggestReharmonizationArgs):
    """(분석, 제안들, 범위 [start, end), 범위 이름). suggest_reharmonization · apply_chords가 같은 범위로 같은 제안을 계산한다."""
    bpb = project.beats_per_bar
    start, end = _range(args, bpb, float("inf"))
    a, sugs = suggest(project, start, None if end == float("inf") else end)
    if a.chords and not any(c.root is not None and start - 1e-6 <= c.start < end - 1e-6 for c in a.chords):
        raise ToolError(f"그 범위에서 시작하는 코드가 없어요. 곡은 {project.bar_count}마디예요.", code="empty_range")
    if args.bars:
        span = f"{args.bars[0]}마디" if args.bars[0] == args.bars[1] else f"{args.bars[0]}~{args.bars[1]}마디"
    elif args.beats:
        span = f"{_where(start, bpb)}부터"
    else:
        span = "곡 전체"
    return a, sugs, start, end, span


def _change_lines(s: Suggestion, bpb: float) -> list[str]:
    return [f"{_where(ch.start, bpb)} {ch.before} → {' · '.join(ch.after)} ({ch.kind})" for ch in s.changes]


def suggest_reharmonization(project: Project, args: SuggestReharmonizationArgs | None = None) -> ToolResult:
    args = args or SuggestReharmonizationArgs()
    bpb = project.beats_per_bar
    a, sugs, start, end, span = _suggestions(project, args)
    if not a.chords:
        return ToolResult(summary=NO_NOTES, data={"key": None, "suggestions": []})
    if not sugs:
        return ToolResult(
            summary=f"{span}에 바꿀 만한 대리코드가 없어요",
            data={"key": a.key.name, "suggestions": [], "why": "코드마다 대리코드가 멜로디와 세게 부딪히거나, 이미 텐션이 많은 코드예요"},
        )

    inside = lambda c: start - 1e-6 <= c.start < end - 1e-6  # noqa: E731
    items, views = [], []
    for no, s in enumerate(sugs, 1):
        changes = _change_lines(s, bpb)
        extra = [f"외 {len(changes) - MAX_CHANGES}곳"] if len(changes) > MAX_CHANGES else []
        item = {"no": no, "style": s.style, "feel": FEEL[s.style], "progression": " → ".join(c.name for c in s.chords if inside(c)),
                "changes": changes[:MAX_CHANGES] + extra}
        if s.rubs:
            item["rubs"] = s.rubs[:4]  # 약박에서 살짝 부딪히는 멜로디 음 (센 부딪힘은 이미 뺐다)
        items.append(item)
        views.append({"style": s.style, "feel": FEEL[s.style], "chords": [_chord_view(c) for c in s.chords],
                      "changes": changes, "rubs": s.rubs})
    # 카드의 "이걸로 바꾸기"가 같은 범위로 apply_chords를 부르게 마디 범위를 함께 보낸다 (고른 부분은 마디 단위로)
    bars = list(args.bars) if args.bars else [int(start // bpb) + 1, math.ceil(end / bpb - 1e-6)] if args.beats else None
    return ToolResult(
        summary=f"조성 {a.key.name} · {span} 리하모니 제안 {len(sugs)}개 ({' · '.join(s.style for s in sugs)})",
        data={"key": a.key.name, "suggestions": items},
        view={"reharm": {"base": [_chord_view(c) for c in a.chords], "suggestions": views, "bars": bars}},
    )


class ApplyChordsArgs(SuggestReharmonizationArgs):
    style: Literal["가볍게", "재지하게", "색다르게"] = Field(description="suggest_reharmonization 제안 이름")


def apply_chords(project: Project, args: ApplyChordsArgs) -> ToolResult:
    """제안을 같은 범위로 다시 계산해 그대로 음을 바꾼다 (LLM이 코드 목록을 옮겨 적지 않게)."""
    a, sugs, _, _, span = _suggestions(project, args)
    if not a.chords:
        raise ToolError(NO_NOTES, code="no_chords")
    s = next((s for s in sugs if s.style == args.style), None)
    if s is None:
        have = " · ".join(x.style for x in sugs) or "없음"
        raise ToolError(f"{span}에는 '{args.style}' 제안이 없어요 (바꿀 만한 대리코드가 없음). 있는 제안: {have}", code="no_suggestion")
    new, counts = apply_progression(project, a.chords, s.chords)
    total = sum(counts.values())
    if not total:
        return ToolResult(project=project, summary=NOTHING_CHANGED)
    lines = _change_lines(s, project.beats_per_bar)
    shown = ", ".join(lines[:3]) + (f" 외 {len(lines) - 3}곳" if len(lines) > 3 else "")
    return ToolResult(
        project=new,
        changed_notes=total,
        summary=f"{', '.join(counts)} 트랙 {total}개 음을 {args.style} 제안 코드로 바꿨어요 ({shown})",
        data={"changes": lines[:MAX_CHANGES], "tracks": counts},
    )
