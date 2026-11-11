"""편곡 한 번에 = 오케스트레이션: arrange(계획표) → 순서대로 실행 → 점검.

LLM은 계획표(어떤 파트를 어느 마디에, 장르 · 진행 · 더 꽉 차게 할 구간)만 쓰고, 순서 · 실행 · 점검은 코드가 한다.
한 번에 여러 파트를 LLM이 생성 도구를 하나씩 이어 부르던 때는 (평가 전 기준선, docs/devlog.md v0.3-9)
- 베이스를 드럼보다 먼저 만들어 킥에 못 맞추고, "5마디부터 드럼이랑 베이스도"에서 패드를 지우고,
- "9마디부터 더 꽉 차게"라고 해 놓고 실제로 더 촘촘한지 보지 않았고, 새 트랙이 멜로디 · 다른 트랙과 반음으로 부딪혀도 몰랐다.

실행 순서: 드럼 → 베이스(킥에 맞추려고 드럼 다음) → 패드 → 반주 → 아르페지오 (위 화음 트랙은 앞 트랙을 피해 높이를 고른다).
장르를 말하면 그 장르에 어울리는 베이스 무늬 · 악기와 반주 악기를 기본으로 (재즈 = 워킹 · 어쿠스틱 베이스 · 피아노).
화음 트랙이 둘 넘게 쌓이면 높이를 나눈다 (패드 아래 · 반주 가운데 · 아르페지오 위).
"더 꽉 차게 · 덜어 내게"(lift) 구간은 드럼 밀도를 한 단계 올리거나 내려 그 구간만 다시 깐다.
그래도 점검에서 "더 꽉 차게"가 안 찼으면 그 구간에만 반주(또는 아르페지오) 한 겹을 더한다 — 코드가 하는 첫 고치기.
점검은 app/arrange/review.py. 결과는 다른 편집처럼 미리보기 → 적용, 파트마다 "다른 버전"은 지금처럼 generate_* 도구로.
나중에 붙일 파트(멜로디 · 대선율 · 내 루프)는 ROLES · _run_part에 한 줄씩 더한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.project import Project
from app.tools.base import Bar, ToolError, ToolResult
from app.tools.generate import (
    DRUM_STYLES, GenerateBasslineArgs, GenerateChordsArgs, GenerateDrumsArgs, generate_bassline, generate_chords,
    generate_drums,
)

Role = Literal["drums", "bass", "pad", "keys", "arp"]
ROLES: tuple[Role, ...] = ("drums", "bass", "pad", "keys", "arp")  # 실행 순서
ROLE_KO = {"drums": "드럼", "bass": "베이스", "pad": "패드", "keys": "반주", "arp": "아르페지오"}
PATTERN = {"pad": "pad", "keys": "stab", "arp": "arpeggio"}
STACK = {"pad": "low", "keys": "mid", "arp": "high"}  # 화음 트랙이 둘 넘으면 이 높이로 나눈다
DensityLevel = Literal["low", "mid", "high"]
LEVELS: tuple[DensityLevel, ...] = ("low", "mid", "high")

# 장르마다 어울리는 기본값 (계획에 말이 없을 때만). 생성기는 곡 편성으로 소리를 고르는데, 신스 리드가 있는 곡에서 "재즈풍"이라고
# 해도 신스 베이스가 나왔다 (기준선 L4) — 장르를 말했으면 장르를 먼저 본다
GENRE_BASS_STYLE = {"jazz": "walking", "house": "octave"}
GENRE_BASS = {"jazz": 32, "soul": 33, "funk": 36, "rock": 34, "latin": 32, "house": 38, "trap": 38}  # 어쿠스틱 · 핑거 · 슬랩 · 피크 · 신스
GENRE_KEYS = {"jazz": 0, "soul": 4, "lofi": 4, "boombap": 4, "rock": 0, "latin": 0, "funk": 4}  # 피아노 · 전자 피아노


class PartPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role = Field(description="drums · bass · pad(길게 누르는 화음) · keys(끊어 치는 반주 · 컴핑) · arp(아르페지오)")
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    program: int | None = Field(default=None, ge=0, le=127, description="악기(GM). 말이 없으면 비워 둬")
    bass_style: Literal["root", "root_fifth", "octave", "walking"] | None = Field(
        default=None, description="bass만. 말이 없으면 비워 둬 (장르에 맞춰)")
    density: DensityLevel | None = Field(default=None, description="drums만. 하이햇 밀도. 말이 없으면 비워 둬")
    style: Literal["lofi", "boombap", "house", "trap", "pop", "rock", "funk", "soul", "jazz", "latin"] | None = Field(
        default=None, description="drums만. 드럼 장르가 전체 style과 다를 때만")  # 모델이 파트 안에 넣는 일이 있어 받아 준다 (기준선 L4)
    height: Literal["low", "mid", "high"] | None = Field(default=None, description="pad · keys · arp만. 말이 없으면 비워 둬")

    @model_validator(mode="after")
    def _check(self) -> "PartPlan":
        if self.bars and self.bars[0] > self.bars[1]:
            raise ValueError("bars는 [시작, 끝] 순서여야 해요 (시작 <= 끝).")
        return self


class LiftPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bars: tuple[Bar, Bar] = Field(description="[시작, 끝] 마디, 끝 포함")
    energy: Literal["higher", "lower"] = Field(description="higher = 더 꽉 차게 · 세게, lower = 덜어 내게 · 조용하게")


class ArrangeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[PartPlan] = Field(min_length=1, max_length=8, description="깔 파트들. 순서는 상관없다 (코드가 드럼 → 베이스 → 화음 순으로)")
    style: Literal["lofi", "boombap", "house", "trap", "pop", "rock", "funk", "soul", "jazz", "latin"] | None = Field(
        default=None, description="장르. 말이 없으면 비워 둬")
    progression: list[str] | None = Field(
        default=None, min_length=1, max_length=16, description='사용자가 말한 코드 진행. 없으면 비워 둬 — 곡의 코드를 따른다')
    bars_per_chord: Literal[0.5, 1, 2, 4] = Field(default=1, description="progression에서 한 코드의 마디 수")
    lift: list[LiftPlan] | None = Field(default=None, max_length=4, description="더 꽉 차게 · 덜어 내게 할 구간. 말이 없으면 비워 둬")


def review(project: Project, new_ids: set[str], wanted: list):  # noqa: ANN201
    # app.arrange는 app.tools를 불러서(악기 이름), 여기서 맨 위에 부르면 app.arrange를 먼저 부를 때 순환 import가 된다
    from app.arrange.review import review as run

    return run(project, new_ids, wanted)


def _new_ids(before: Project, after: Project) -> list[str]:
    old = {t.id for t in before.tracks}
    return [t.id for t in after.tracks if t.id not in old]


def _segments(bars: tuple[int, int], lifts: list[LiftPlan]) -> list[tuple[tuple[int, int], str | None]]:
    """파트 범위를 lift 구간으로 쪼갠다: [((시작, 끝), None | higher | lower)]."""
    cuts = sorted({bars[0], bars[1] + 1, *(b for lf in lifts for b in (lf.bars[0], lf.bars[1] + 1) if bars[0] < b <= bars[1])})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        energy = next((lf.energy for lf in lifts if lf.bars[0] <= a and b - 1 <= lf.bars[1]), None)
        out.append(((a, b - 1), energy))
    return out


def _shift(level: DensityLevel, energy: str | None) -> DensityLevel:
    i = LEVELS.index(level)
    return LEVELS[min(2, i + 1)] if energy == "higher" else LEVELS[max(0, i - 1)] if energy == "lower" else level


def _drums(project: Project, part: PartPlan, args: ArrangeArgs, song_bars: int) -> ToolResult:
    """드럼. lift 구간이 걸치면 처음엔 범위 전체를 깔고, lift 구간만 밀도를 바꿔 같은 트랙들에 다시 깐다."""
    bars = part.bars or (1, song_bars)
    style = part.style or args.style
    first = generate_drums(project, GenerateDrumsArgs(style=style, density=part.density, bars=part.bars))
    lifted = [(seg, e) for seg, e in _segments(bars, args.lift or []) if e]
    if not lifted:
        return first
    assert first.project is not None
    made = _new_ids(project, first.project)
    out, lines = first.project, [first.summary]
    for seg, energy in lifted:
        level = _shift(part.density or "mid", energy)
        again = generate_drums(out, GenerateDrumsArgs(style=style, density=level, bars=seg, track_ids=made))
        assert again.project is not None
        out = again.project
        lines.append(f"{seg[0]}~{seg[1]}마디는 하이햇 {'촘촘하게' if level == 'high' else '단순하게' if level == 'low' else '보통'}")
    return ToolResult(project=out, changed_notes=sum(len(t.notes) for t in out.tracks if t.id in made),
                      summary=" · ".join(lines), checks=first.checks)


def _run_part(project: Project, part: PartPlan, args: ArrangeArgs, song_bars: int, height: str | None) -> ToolResult:
    if part.role == "drums":
        return _drums(project, part, args, song_bars)
    if part.role == "bass":
        return generate_bassline(project, GenerateBasslineArgs(
            style=part.bass_style or GENRE_BASS_STYLE.get(args.style or "", "root"),
            program=part.program if part.program is not None else GENRE_BASS.get(args.style or ""),
            progression=args.progression, bars_per_chord=args.bars_per_chord, bars=part.bars,
        ))
    program = part.program
    if program is None and part.role == "keys":
        program = GENRE_KEYS.get(args.style or "")
    return generate_chords(project, GenerateChordsArgs(
        pattern=PATTERN[part.role], height=part.height or height, program=program,  # type: ignore[arg-type]
        progression=args.progression, bars_per_chord=args.bars_per_chord, bars=part.bars,
    ))


def _fill_lifts(project: Project, args: ArrangeArgs, parts: list[PartPlan], new_ids: set[str],
                wanted: list) -> tuple[Project, list[dict], list[str]]:
    """점검에서 "더 꽉 차게" 구간이 안 찼으면 그 구간에만 반주(없으면) · 아르페지오를 더한다. 이미 둘 다 있으면 그대로 (점검에 남음)."""
    rows: list[dict] = []
    made: list[str] = []
    used = {p.role for p in parts}
    for lf in review(project, new_ids, wanted).lifts:
        if lf.ok or lf.energy != "higher":
            continue
        role: Role | None = next((r for r in ("keys", "arp") if r not in used), None)
        if role is None:
            continue
        part = PartPlan(role=role, bars=lf.bars)
        try:
            res = _run_part(project, part, args, 0, STACK[role])
        except ToolError:
            continue
        assert res.project is not None
        ids = _new_ids(project, res.project)
        project = res.project
        made += ids
        new_ids |= set(ids)
        used.add(role)
        rows.append({"role": role, "bars": f"{lf.bars[0]}~{lf.bars[1]}마디", "ok": True, "auto": True,
                     "summary": f"{lf.bars[0]}~{lf.bars[1]}마디가 드럼만으로는 꽉 차지 않아 그 구간에만 더했어요 — {res.summary}",
                     "tracks": [t.name for t in project.tracks if t.id in ids]})
    return project, rows, made


def _bars_text(part: PartPlan, song_bars: int) -> str:
    a, b = part.bars or (1, song_bars)
    return "전체" if (a, b) == (1, song_bars) else f"{a}~{b}마디"


def arrange(project: Project, args: ArrangeArgs) -> ToolResult:
    from app.arrange.read import read_song  # 순환 import를 피해 여기서 (review와 같은 이유)

    song = read_song(project)
    song_bars = song.bars
    for lf in args.lift or []:
        if lf.bars[0] > lf.bars[1]:
            raise ToolError("lift의 bars는 [시작, 끝] 순서여야 해요.", code="invalid_args")
    parts = sorted(args.parts, key=lambda p: ROLES.index(p.role))
    # 화음 트랙이 곡에 이미 있는 것과 합쳐 둘 넘으면 높이를 나눈다 (있는 패드 위에 아르페지오 → 아르페지오는 위로)
    harmonic = sum(1 for t in song.melodic if t.role in ("pad", "keys", "pluck")) + sum(1 for p in parts if p.role in PATTERN)
    out = project
    new_ids: list[str] = []
    rows, checks, failed = [], [], []
    for part in parts:
        height = STACK.get(part.role) if harmonic >= 2 else None
        try:
            res = _run_part(out, part, args, song_bars, height)
        except ToolError as e:
            failed.append(f"{ROLE_KO[part.role]}: {e.message}")
            rows.append({"role": part.role, "bars": _bars_text(part, song_bars), "ok": False, "summary": e.message})
            continue
        assert res.project is not None
        made = _new_ids(out, res.project)
        out = res.project
        new_ids += made
        checks += res.checks
        rows.append({"role": part.role, "bars": _bars_text(part, song_bars), "ok": True, "summary": res.summary,
                     "tracks": [t.name for t in out.tracks if t.id in made]})
    if not new_ids:
        raise ToolError("계획한 파트를 하나도 깔지 못했어요 — " + " / ".join(failed), code="arrange_failed")
    wanted = [(tuple(lf.bars), lf.energy) for lf in args.lift or []]
    # 고치기 (코드가 하는 것): "더 꽉 차게"가 드럼 밀도만으로 안 됐으면 그 구간에만 화음 한 겹을 더한다.
    # 멜로디가 앞쪽에 몰린 곡은 9~16마디 하이햇을 촘촘하게 해도 박당 음 수가 앞보다 적었다 (브라우저 확인)
    out, extra_rows, extra_ids = _fill_lifts(out, args, parts, set(new_ids), wanted)
    rows += extra_rows
    new_ids += extra_ids
    report = review(out, set(new_ids), wanted)  # type: ignore[arg-type]
    walking = any(p.role == "bass" and (p.bass_style or GENRE_BASS_STYLE.get(args.style or "")) == "walking" for p in parts)
    if walking:  # 워킹 베이스는 킥을 따르지 않는다 (4분음표로 걸음) — 비율이 낮아도 문제처럼 읽히지 않게 뺀다
        report.kick_lock = None
    done = " → ".join(f"{ROLE_KO[r['role']]}({r['bars']})" for r in rows if r["ok"] and not r.get("auto"))
    head = f"계획대로 깔았어요: {done}" + (f" · 장르 {DRUM_STYLES[args.style]}" if args.style else "")
    for r in rows:
        if r.get("auto"):
            head += f" · {r['bars']}가 드럼만으로는 꽉 차지 않아 그 구간에만 {ROLE_KO[r['role']]}를 더했어요"
    if failed:
        head += " · 못 깐 파트: " + " / ".join(failed)
    tail = "점검: 트랙끼리 부딪히는 곳 · 겹치는 음역 없음" if not report.problems else "점검에서 걸린 것: " + " / ".join(report.problems)
    if report.kick_lock is not None:
        tail += f" · 베이스가 킥과 같이 친 비율 {report.kick_lock:.0%}"
    return ToolResult(
        project=out,
        changed_notes=sum(len(t.notes) for t in out.tracks if t.id in new_ids),
        changed_settings=True,
        summary=f"{head}. {tail}",
        data={"parts": [{k: v for k, v in r.items() if k != "tracks"} for r in rows], "review": report.data()},
        view={"arrange": {
            "style": DRUM_STYLES[args.style] if args.style else None, "progression": args.progression,
            "parts": rows, "lift": [{"bars": list(lf.bars), "energy": lf.energy} for lf in args.lift or []],
            "problems": report.problems, "kick_lock": report.kick_lock,
        }},
        checks=checks,
    )
