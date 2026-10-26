"""읽기 도구: analyze_harmony. 조성 · 코드 · 로마숫자 · 화성 기능을 읽는다 (프로젝트는 바꾸지 않음).

계산은 app/harmony가 하고, 에이전트는 결과를 설명만 한다 (음 목록을 보고 코드를 짐작하지 않게).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.harmony import analyze
from app.models.project import Project
from app.tools.base import Bar, ToolError, ToolResult

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


def analyze_harmony(project: Project, args: AnalyzeHarmonyArgs | None = None) -> ToolResult:
    args = args or AnalyzeHarmonyArgs()
    a = analyze(project)
    if not a.chords:
        return ToolResult(summary="화음을 읽을 음이 없어요 (드럼만 있거나 음이 없음).", data={"key": None, "chords": []})

    bpb = a.beats_per_bar
    start, end = 0.0, a.chords[-1].end
    if args.bars:
        start, end = (args.bars[0] - 1) * bpb, args.bars[1] * bpb
    elif args.beats:
        start, end = args.beats
    chords = [c for c in a.chords if c.end > start + 1e-6 and c.start < end - 1e-6]
    if not chords:
        raise ToolError(f"그 범위에는 음이 없어요. 곡은 {project.bar_count}마디예요.", code="empty_range")

    def where(beat: float) -> str:
        bar = int(beat // bpb) + 1
        rest = beat - (bar - 1) * bpb
        return f"{bar}마디" if abs(rest) < 1e-6 else f"{bar}마디 {rest + 1:g}박"

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
