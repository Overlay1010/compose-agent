"""평가 정답 표현과 채점.

정답은 "이 도구를 이런 인자로 불러야 한다"로 적는다. 정도를 말하는 명령("살짝", "좀")은 정답이
하나가 아니라서 범위(Range)로, 같은 결과를 내는 다른 방법(한 옥타브 = 12반음)은 alt로 받는다.
묻기만 하는 명령("무슨 키야?")은 편집이 없어야 하고, 읽기 도구를 불렀는지(reads)와 답에 정답이 들어 있는지(reply_has)를 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.loop import ToolStep


@dataclass(frozen=True)
class Range:
    low: float
    high: float
    default: float | None = None  # LLM이 인자를 비워 두면 도구가 쓰는 기본값 (예: strength 1)

    def ok(self, value: Any) -> bool:
        if value is None and self.default is not None:
            value = self.default
        return isinstance(value, (int, float)) and self.low <= value <= self.high

    def __str__(self) -> str:
        return f"{self.low}~{self.high}"


@dataclass(frozen=True)
class Pitches:
    """고른 음 번호: allowed 안에서만, must는 꼭 포함 (예: 하이햇 = {42,44,46} 안, 42는 꼭)."""

    allowed: frozenset[int]
    must: frozenset[int] = frozenset()

    def ok(self, value: Any) -> bool:
        if not isinstance(value, list) or not value:
            return False
        got = set(value)
        return got <= self.allowed and self.must <= got

    def __str__(self) -> str:
        return f"{sorted(self.must)}⊆고른 음⊆{sorted(self.allowed)}"


@dataclass(frozen=True)
class OneOf:
    """여러 값 중 하나면 정답 (예: 탐 소리 = 어쿠스틱 말고 아무 탐)."""

    values: frozenset[Any]

    def ok(self, value: Any) -> bool:
        return value in self.values

    def __str__(self) -> str:
        return "|".join(sorted(map(str, self.values)))


ALL = "ALL"  # track_ids를 비우거나(전체), 해당 트랙을 전부 고른 경우


@dataclass(frozen=True)
class Call:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)

    def matches(self, step: ToolStep, melodic: set[str]) -> bool:
        if step.name != self.tool:
            return False
        for key, want in self.args.items():
            got = step.args.get(key)
            if key == "track_ids":
                if want == ALL:
                    # 비워 두거나(전체), 드럼 말고 모든 트랙을 고르면 "전체"로 본다
                    if got and not set(got) >= melodic:  # 빈 목록도 전체 (도구가 그렇게 받는다)
                        return False
                elif got is None or set(got) != set(want):
                    return False
            elif isinstance(want, (Range, Pitches, OneOf)):
                if not want.ok(got):
                    return False
            elif key in ("bars", "beats"):
                if want is None:  # 범위 없이 전체여야 함
                    if got is not None:
                        return False
                elif got is None or len(got) != 2 or any(abs(a - b) > 1e-6 for a, b in zip(got, want)):
                    return False
            elif isinstance(want, float) and isinstance(got, (int, float)):
                if abs(got - want) > 1e-6:
                    return False
            elif got != want:
                return False
        return True

    def __str__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.tool}({args})"


HANGUL = re.compile("[가-힣]")
CARD_NAMES = re.compile("가볍게|재지하게|색다르게")


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    sample: str  # scripts/make_samples.py의 샘플 이름
    command: str
    expect: tuple[Call, ...] = ()
    alt: tuple[tuple[Call, ...], ...] = ()  # 다른 정답 묶음
    note: str = ""
    selection: dict | None = None  # 화면에서 고른 부분 {track_ids, beats, pitches}
    reads: tuple[str, ...] = ()  # 꼭 불러야 하는 읽기 도구 (예: analyze_harmony)
    reply_has: tuple[str | tuple[str, ...], ...] = ()  # 답에 들어 있어야 할 말 (묶음이면 그중 하나, 대소문자 무시)
    reply_lacks: tuple[str, ...] = ()  # 답에 있으면 안 되는 말 (예: 조성을 "C 장조"로 바꿔 말함)
    english: bool = False  # 영어로 물었으니 답에 한글이 없어야 함 (화면 카드 이름 가볍게 · 재지하게 · 색다르게는 그대로 써도 됨)

    @property
    def expects_no_edit(self) -> bool:
        return not self.expect


@dataclass
class Score:
    passed: bool
    tools_ok: bool  # 편집 도구 종류를 맞게 골랐나
    reason: str


def edit_steps(steps: list[ToolStep]) -> list[ToolStep]:
    """실제로 곡을 바꾼 편집만 (정보 조회 · 실패 · 바뀐 게 없는 호출은 뺀다). 템포처럼 음표 말고 설정이 바뀐 것도 포함."""
    return [s for s in steps if s.changed]


def score(case: Case, steps: list[ToolStep], melodic: set[str], reply: str = "") -> Score:
    """melodic = 드럼이 아닌 트랙 id들 ("전체" 판정에 쓴다). reply = 에이전트의 마지막 답."""
    s = _score_edits(case, steps, melodic)
    if not s.passed:
        return s
    unread = [t for t in case.reads if not any(st.name == t and st.ok for st in steps)]
    if unread:
        return Score(False, False, "불러야 할 도구를 안 부름: " + ", ".join(unread))
    text = reply.lower()
    missing = [w for w in case.reply_has if not any(x.lower() in text for x in ((w,) if isinstance(w, str) else w))]
    if missing:
        return Score(False, True, "답에 빠진 말: " + ", ".join(w if isinstance(w, str) else "|".join(w) for w in missing))
    banned = [w for w in case.reply_lacks if w.lower() in text]
    if banned:
        return Score(False, True, "답에 쓰면 안 되는 말: " + ", ".join(banned))
    if case.english and HANGUL.search(CARD_NAMES.sub("", reply)):
        return Score(False, True, "영어로 물었는데 한국어로 답함")
    return s


def _score_edits(case: Case, steps: list[ToolStep], melodic: set[str]) -> Score:
    edits = edit_steps(steps)
    if case.expects_no_edit:
        if edits:
            return Score(False, False, "편집하면 안 되는데 함: " + ", ".join(s.name for s in edits))
        return Score(True, True, "편집 없음 (정답)")

    best: Score | None = None
    for expected in (case.expect, *case.alt):
        want_tools = sorted(c.tool for c in expected)
        got_tools = sorted(s.name for s in edits)
        tools_ok = want_tools == got_tools
        unused = list(edits)
        missing = []
        for call in expected:
            hit = next((s for s in unused if call.matches(s, melodic)), None)
            if hit is None:
                missing.append(call)
            else:
                unused.remove(hit)
        if not missing and not unused:
            return Score(True, True, "정답")
        reason = []
        if missing:
            reason.append("빠졌거나 인자 틀림: " + "; ".join(map(str, missing)))
        if unused:
            reason.append("시키지 않은 편집: " + "; ".join(f"{s.name}{s.args}" for s in unused))
        cand = Score(False, tools_ok, " / ".join(reason))
        if best is None or (cand.tools_ok and not best.tools_ok):
            best = cand
    assert best is not None
    return best
