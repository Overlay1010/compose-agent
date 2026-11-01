"""내 샘플(원샷 WAV) 도구: use_sample, 그리고 트랙에 어울리는 샘플 추천.

소리 파일은 사용자 브라우저에만 있다 (서버 · 저장소에 올리지 않음 — 남의 샘플 라이선스).
브라우저가 파일마다 분석한 이름표(SampleInfo: 종류 · 기준음 · 길이 · 밝기)만 명령과 함께 보내 오고,
여기서는 그 이름표로 트랙 역할에 맞는 샘플을 점수로 고른다. 고르는 규칙이 코드에 있어서 LLM은 결과만 전한다.

원샷은 기준음 하나를 재생 속도로 높이고 낮춰 연주한다 (frontend/src/audio/instruments.ts UserSampleVoice).
기준음에서 멀어질수록 소리가 어색해지고 길이도 변해서, 트랙 음역과 기준음이 가까운 샘플을 먼저 고른다.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import Project, SampleRef, Track
from app.tools.base import ToolError, ToolResult
from app.tools.instrument import display_name, heard_program

Kind = Literal["bass", "keys", "pluck", "pad", "lead", "bell", "chord", "loop", "drum", "other"]
KIND_KO = {
    "bass": "베이스", "keys": "건반", "pluck": "플럭", "pad": "패드", "lead": "리드", "bell": "벨",
    "chord": "코드 원샷", "loop": "멜로디 루프", "drum": "드럼", "other": "기타 소리",
}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class SampleInfo(BaseModel):
    """브라우저가 분석해 보내는 샘플 이름표 (frontend/src/samples/analyze.ts)."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=120)
    kind: Kind
    root: int | None = Field(default=None, ge=0, le=127, description="녹음된 음 (MIDI). 음 높이가 없는 소리면 None")
    length: float = Field(ge=0, le=600, description="들리는 길이(초)")
    sustained: bool = Field(default=False, description="1초 뒤에도 크게 남아 있음 (패드처럼 끌 수 있는 소리)")
    brightness: float = Field(ge=0, le=1, description="0 어두움 ~ 1 밝음")


# 명령 한 번 동안 쓰는 샘플 목록. 도구는 Project만 받으므로 따로 둔다 (app/agent/session.py가 채운다)
_LIBRARY: ContextVar[tuple[SampleInfo, ...]] = ContextVar("sample_library", default=())


@contextmanager
def library(samples: list[SampleInfo] | None) -> Iterator[None]:
    token = _LIBRARY.set(tuple(samples or ()))
    try:
        yield
    finally:
        _LIBRARY.reset(token)


def current_library() -> tuple[SampleInfo, ...]:
    return _LIBRARY.get()


def note_name(pitch: int) -> str:
    return f"{NAMES[pitch % 12]}{pitch // 12 - 1}"


# ---------- 트랙 역할 ----------

Role = Literal["bass", "pad", "keys", "pluck", "lead"]
ROLE_KO = {"bass": "베이스", "pad": "패드", "keys": "건반 반주", "pluck": "플럭 · 아르페지오", "lead": "멜로디"}

_ROLE_NAMES: list[tuple[str, Role]] = [
    (r"808|sub|bass|베이스", "bass"), (r"pad|패드|atmo|string|현악", "pad"), (r"arp|pluck|아르페", "pluck"),
    (r"lead|melody|멜로디|리드|vox|vocal", "lead"), (r"keys|piano|rhodes|comp|chord|건반|피아노|코드", "keys"),
]


def _overlap(track: Track) -> bool:
    """같은 순간에 두 음 이상이 울리는 곳이 음의 1/4 넘게 있으면 화음 트랙."""
    notes = sorted(track.notes, key=lambda n: n.start)
    stacked = sum(1 for a, b in zip(notes, notes[1:]) if b.start < a.start + a.duration - 1e-6)
    return stacked * 4 > len(notes)


def role_of(track: Track) -> Role | None:
    """트랙이 곡에서 맡은 역할. 이름 → 악기 → 음 모양 순서로 본다. 드럼이면 None."""
    if track.is_drum:
        return None
    program = heard_program(track)
    if 32 <= program <= 39:
        return "bass"
    if track.notes and max(n.pitch for n in track.notes) < 52 and not _overlap(track):
        return "bass"
    name = track.name.lower()
    for pattern, role in _ROLE_NAMES:
        if re.search(pattern, name):
            return role
    if program or track.program_set:  # 0이어도 사용자가 고른 피아노면 악기로 본다
        if 88 <= program <= 95 or 48 <= program <= 54:
            return "pad"
        if program <= 7 or 16 <= program <= 23:
            return "keys"
        if 24 <= program <= 31 or program in (45, 46, 104, 105, 106, 107, 108):
            return "pluck"
        if 8 <= program <= 15 or 56 <= program <= 87:
            return "lead"
    if not track.notes:
        return "keys"
    avg = sum(n.duration for n in track.notes) / len(track.notes)
    if _overlap(track):
        return "pad" if avg >= 1.5 else "keys"
    return "pluck" if avg < 0.5 else "lead"


# 역할마다 어울리는 샘플 종류 (1 = 딱 맞음). 없는 종류(코드 원샷 · 멜로디 루프 · 드럼 · 기타 소리)는 고르지 않는다
# (음 하나를 높이고 낮춰 연주하는 방식이라, 화음이나 프레이즈가 녹음된 샘플을 쓰면 음이 겹쳐 들린다)
FIT: dict[Role, dict[str, float]] = {
    "bass": {"bass": 1.0},
    "pad": {"pad": 1.0, "keys": 0.4, "lead": 0.3},
    "keys": {"keys": 1.0, "pluck": 0.6, "pad": 0.4, "bell": 0.4},
    "pluck": {"pluck": 1.0, "bell": 0.7, "keys": 0.6},
    "lead": {"lead": 1.0, "pluck": 0.6, "bell": 0.6, "keys": 0.4},
}
STRETCH_OK = 7  # 기준음에서 이 반음까지는 거의 그대로 들린다
STRETCH_MAX = 12  # 이보다 멀면 소리가 크게 바뀐다 (한 옥타브)

Prefer = Literal["darker", "brighter", "shorter", "longer"]


class Pick(BaseModel):
    sample: SampleInfo
    score: float
    reason: str


def _hold_seconds(track: Track, tempo: float) -> float:
    """트랙에서 긴 음(상위 1/4)의 길이(초)."""
    if not track.notes:
        return 0.0
    durations = sorted(n.duration for n in track.notes)
    return durations[len(durations) * 3 // 4] * 60 / tempo


def score(sample: SampleInfo, role: Role, track: Track, tempo: float, prefer: Prefer | None = None) -> Pick | None:
    fit = FIT[role].get(sample.kind, 0.0)
    if not fit or sample.root is None:
        return None
    value = 100 * fit
    why = [f"{KIND_KO[sample.kind]} 샘플"]
    if track.notes:
        low, high = track.pitch_range or (sample.root, sample.root)
        stretch = max(abs(low - sample.root), abs(high - sample.root))
        value -= 3 * max(0, stretch - STRETCH_OK) + 6 * max(0, stretch - STRETCH_MAX)
        # 음은 트랙 그대로 연주된다. 녹음된 음에서 멀리 옮길수록 소리 빛깔 · 길이가 달라질 뿐 (그때만 알린다 —
        # "기준음 A5"를 늘 적었더니 LLM이 "리드보다 높게 들릴 수 있어요"라고 틀리게 풀었다)
        if stretch > STRETCH_MAX:
            why.append(f"녹음된 음({note_name(sample.root)})에서 멀리 옮겨 연주해 음색 · 길이가 조금 달라질 수 있음 — 음 높이는 트랙 그대로")
        elif stretch <= STRETCH_OK:
            why.append("트랙 음역과 녹음된 음이 가까움")
    hold = _hold_seconds(track, tempo)
    if role == "pad" and not sample.sustained:
        value -= 30
    if hold > sample.length:
        value -= min(20, 10 * (hold - sample.length))
    why.append(f"길이 {sample.length:.1f}초")
    if prefer == "darker":
        value += 40 * (1 - sample.brightness)
    elif prefer == "brighter":
        value += 40 * sample.brightness
    elif prefer == "shorter":
        value -= 8 * min(sample.length, 5)
    elif prefer == "longer":
        value += 8 * min(sample.length, 5)
    if prefer in ("darker", "brighter"):
        why.append("어두운 소리" if sample.brightness < 0.4 else "밝은 소리" if sample.brightness > 0.6 else "중간 밝기")
    return Pick(sample=sample, score=round(value, 1), reason=" · ".join(why))


def recommend(track: Track, tempo: float, samples: tuple[SampleInfo, ...] | list[SampleInfo], prefer: Prefer | None = None) -> list[Pick]:
    """이 트랙에 어울리는 순서. 같은 점수면 이름 순 (결과가 매번 같게)."""
    role = role_of(track)
    if role is None:
        return []
    picks = [p for s in samples if (p := score(s, role, track, tempo, prefer))]
    return sorted(picks, key=lambda p: (-p.score, p.sample.name))


# ---------- 도구 ----------

class UseSampleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_ids: list[str] = Field(min_length=1, description='샘플로 바꿀 트랙 id 목록 (예: ["t2"]). 드럼 트랙은 안 됨')
    sample: str | None = Field(
        default=None,
        description='사용자가 말한 샘플 이름 일부 또는 id. "none"이면 샘플을 빼고 원래 악기로. 없으면 트랙마다 어울리는 샘플을 고른다',
    )
    prefer: Prefer | None = Field(default=None, description='"더 어두운 · 밝은 · 짧은 · 긴 샘플로"')
    different: bool = Field(default=False, description='"다른 샘플로": 지금 쓰는 샘플 말고 다음으로 어울리는 것')


def _match(query: str, samples: tuple[SampleInfo, ...]) -> list[SampleInfo]:
    q = query.lower().strip()
    exact = [s for s in samples if s.id == query or s.name.lower() == q]
    if exact:
        return exact
    words = re.findall(r"\w+", q)
    return [s for s in samples if all(w in s.name.lower() for w in words)]


def use_sample(project: Project, args: UseSampleArgs) -> ToolResult:
    by_id = {t.id: t for t in project.tracks}
    unknown = [i for i in args.track_ids if i not in by_id]
    if unknown:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    targets = [by_id[i] for i in args.track_ids]
    drums = [t.name for t in targets if t.is_drum]
    if drums and len(drums) == len(targets):
        raise ToolError("드럼 트랙에는 아직 내 샘플을 쓸 수 없어요 (멜로디 · 베이스 · 패드 트랙만). 드럼은 킷 · 소리 고르기를 써요.", code="drum_track")

    tracks = {t.id: t for t in project.tracks}
    lines: list[str] = []
    if args.sample and args.sample.lower() == "none":
        for t in targets:
            if t.sample and not t.is_drum:
                tracks[t.id] = t.model_copy(update={"sample": None})
                lines.append(f"{t.name}에서 내 샘플 '{t.sample.name}'을 빼고 {display_name(heard_program(t))} 소리로 돌렸어요.")
        if not lines:
            return ToolResult(project=project, summary="내 샘플을 쓰는 트랙이 아니라 바뀐 게 없어요.")
        return ToolResult(project=project.model_copy(update={"tracks": list(tracks.values())}), changed_settings=True, summary=" ".join(lines))

    samples = current_library()
    if not samples:
        raise ToolError(
            "사용자가 아직 샘플팩을 넣지 않았어요. 위쪽 '내 샘플팩' 버튼으로 원샷 WAV 폴더를 넣으면 쓸 수 있다고 알려 주세요.",
            code="no_samples",
        )
    pool = samples
    if args.sample:
        pool = tuple(_match(args.sample, samples))
        if not pool:
            close = ", ".join(s.name for s in samples[:8])
            raise ToolError(f"'{args.sample}' 이름의 샘플이 없어요. 샘플팩에 있는 것 (일부): {close}", code="unknown_sample")

    for t in targets:
        if t.is_drum:
            lines.append(f"드럼 트랙({t.name})은 건너뛰었어요.")
            continue
        picks = recommend(t, project.tempo, pool, args.prefer)
        if args.different and t.sample:
            picks = [p for p in picks if p.sample.id != t.sample.id]
        if args.sample and not picks:
            # 말한 샘플이 역할과 안 맞아도(예: 패드 트랙에 플럭) 사용자가 고른 거라 그대로 쓴다
            picks = [
                Pick(sample=s, score=0, reason=f"{KIND_KO[s.kind]} 샘플")
                for s in pool if s.root is not None and s.kind not in ("chord", "loop", "drum")
            ]
        if not picks:
            role = role_of(t)
            raise ToolError(
                f"{t.name}({ROLE_KO.get(role or '', '이 트랙')})에 어울리는 샘플이 샘플팩에 없어요 "
                f"(있는 종류: {kinds_text(samples)}). 음 하나짜리 원샷만 쓸 수 있어요 (코드 원샷 · 멜로디 루프는 아직 못 써요).",
                code="no_fitting_sample",
            )
        best = picks[0]
        if t.sample and t.sample.id == best.sample.id:
            lines.append(f"{t.name}는 이미 '{best.sample.name}' 샘플이에요.")
            continue
        tracks[t.id] = t.model_copy(update={"sample": SampleRef(id=best.sample.id, name=best.sample.name)})
        others = ", ".join(f"'{p.sample.name}'" for p in picks[1:3])
        lines.append(
            f"{t.name}({ROLE_KO[role_of(t) or 'keys']}) 소리를 내 샘플 '{best.sample.name}'(으)로 바꿨어요 ({best.reason})."
            + (f" 다른 후보: {others}." if others else "")
        )
    changed = any(tracks[t.id] is not t for t in targets)
    return ToolResult(
        project=project.model_copy(update={"tracks": list(tracks.values())}) if changed else project,
        changed_settings=changed,
        summary=" ".join(lines) + (" 음은 그대로예요." if changed else ""),
    )


def kinds_text(samples: tuple[SampleInfo, ...] | list[SampleInfo]) -> str:
    counts: dict[str, int] = {}
    for s in samples:
        counts[s.kind] = counts.get(s.kind, 0) + 1
    return " · ".join(f"{KIND_KO[k]} {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1]))


def library_text(samples: tuple[SampleInfo, ...] | list[SampleInfo], limit: int = 40) -> str:
    """시스템 프롬프트에 넣을 샘플팩 한 줄 요약 + 이름 일부 (전부 넣으면 토큰이 너무 많다)."""
    names = ", ".join(f"{s.name}({KIND_KO[s.kind]})" for s in list(samples)[:limit])
    more = f" 외 {len(samples) - limit}개" if len(samples) > limit else ""
    return f"원샷 {len(samples)}개 — {kinds_text(samples)}\n- 이름: {names}{more}"
