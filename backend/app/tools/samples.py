"""내 샘플(원샷 WAV) 도구: use_sample, 그리고 트랙에 어울리는 샘플 추천.

소리 파일은 사용자 브라우저에만 있다 (서버 · 저장소에 올리지 않음 — 남의 샘플 라이선스).
브라우저가 파일마다 분석한 이름표(SampleInfo: 종류 · 기준음 · 길이 · 밝기)만 명령과 함께 보내 오고,
여기서는 그 이름표로 트랙 역할에 맞는 샘플을 점수로 고른다. 고르는 규칙이 코드에 있어서 LLM은 결과만 전한다.

원샷은 기준음 하나를 재생 속도로 높이고 낮춰 연주한다 (frontend/src/audio/instruments.ts UserSampleVoice).
기준음에서 멀어질수록 소리가 어색해지고 길이도 변해서, 트랙 음역과 기준음이 가까운 샘플을 먼저 고른다.
"""

from __future__ import annotations

import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from random import Random
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import AudioClip, Note, Project, SampleRef, Track
from app.generate.chords import song_end
from app.generate.drums import HIT, _untangle
from app.tools.base import Bar, ToolError, ToolResult
from app.tools.drums import ROLE_NAMES, ROLES
from app.tools.instrument import display_name, heard_program
from app.tools.tracks import free_name, new_track_id

Kind = Literal["bass", "keys", "pluck", "pad", "lead", "bell", "chord", "loop", "drum", "other"]
KIND_KO = {
    "bass": "베이스", "keys": "건반", "pluck": "플럭", "pad": "패드", "lead": "리드", "bell": "벨",
    "chord": "코드 원샷", "loop": "루프", "drum": "드럼", "other": "기타 소리",
}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class Groove(BaseModel):
    """루프에 녹음된 리듬 (frontend/src/samples/analyze.ts grooveOf). hits: [루프 안 박, 세기, 열림 1 · 아님 0]."""

    bpm: float = Field(gt=0, le=400)
    beats: float = Field(gt=0, le=256)
    hits: list[tuple[float, int, int]] = Field(max_length=128)


class SampleInfo(BaseModel):
    """브라우저가 분석해 보내는 샘플 이름표 (frontend/src/samples/analyze.ts)."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=120)
    kind: Kind
    root: int | None = Field(default=None, ge=0, le=127, description="녹음된 음 (MIDI). 음 높이가 없는 소리면 None")
    length: float = Field(ge=0, le=600, description="들리는 길이(초)")
    sustained: bool = Field(default=False, description="1초 뒤에도 크게 남아 있음 (패드처럼 끌 수 있는 소리)")
    brightness: float = Field(ge=0, le=1, description="0 어두움 ~ 1 밝음")
    drum: Literal["kick", "snare", "clap", "hat", "openhat", "tom", "crash", "ride", "perc"] | None = Field(
        default=None, description="드럼 원샷이면 역할 (킥 · 스네어 · 클랩 · 닫힌 햇 · 열린 햇 · 탐 · 크래시 · 라이드 · 퍼커션)"
    )
    groove: Groove | None = Field(default=None, description="루프만: 녹음된 리듬")


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
    """트랙이 곡에서 맡은 역할. 이름 → 악기 → 음 모양 순서로 본다. 드럼 · 오디오 루프면 None."""
    if track.is_drum or track.audio is not None:
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


# 역할마다 어울리는 샘플 종류 (1 = 딱 맞음). 없는 종류(코드 원샷 · 루프 · 드럼 · 기타 소리)는 고르지 않는다
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
    bonus, said = _prefer(sample, prefer)
    return Pick(sample=sample, score=round(value + bonus, 1), reason=" · ".join([*why, *said]))


def _prefer(sample: SampleInfo, prefer: Prefer | None) -> tuple[float, list[str]]:
    """말로 고른 쪽(어둡게 · 밝게 · 짧게 · 길게)으로 더할 점수와 이유."""
    if prefer == "darker":
        bonus = 40 * (1 - sample.brightness)
    elif prefer == "brighter":
        bonus = 40 * sample.brightness
    elif prefer == "shorter":
        return -8 * min(sample.length, 5), []
    elif prefer == "longer":
        return 8 * min(sample.length, 5), []
    else:
        return 0.0, []
    return bonus, ["어두운 소리" if sample.brightness < 0.4 else "밝은 소리" if sample.brightness > 0.6 else "중간 밝기"]


CLOSE = 3  # 점 — 다른 트랙까지 본 점수가 1등과 이만큼 안이면 곡마다 순서를 바꾼다 (말로 고른 쪽이 있으면 안 섞음).
# 5로 두고 "빛깔이 비슷하면 -5"까지 했더니 lofi 패드 트랙에서 0.8초짜리 짧은 패드가 길게 끄는 패드와 동점이 돼 1등이 됐다


def _with_neighbors(pick: Pick, track: Track, project: Project, samples: dict[str, SampleInfo]) -> Pick:
    """다른 트랙 보기 (app/arrange): 다른 트랙이 이미 쓰는 샘플은 뒤로, 같은 높이 트랙과 빛깔이 다르면 앞으로."""
    from app.arrange.read import FAMILY_BRIGHTNESS  # 늦게 (돌고 도는 import)

    value, why = pick.score, [pick.reason]
    others = [t for t in project.tracks if t.id != track.id and not t.is_drum and t.audio is None]
    owner = next((t for t in others if t.sample and t.sample.id == pick.sample.id), None)
    if owner is not None:
        value -= 15
        why.append(f"{owner.name} 트랙이 이미 씀")
    mine = track.pitch_range
    near = [t for t in others if mine and t.pitch_range and t.pitch_range[0] <= mine[1] and mine[0] <= t.pitch_range[1]]
    if near:
        def bright(t: Track) -> float:
            info = samples.get(t.sample.id) if t.sample else None
            return info.brightness if info else FAMILY_BRIGHTNESS[heard_program(t) // 8]

        around = sum(bright(t) for t in near) / len(near)
        if abs(pick.sample.brightness - around) >= 0.25:
            value += 5
            why.append("같은 높이 트랙과 빛깔이 달라 잘 들림")
    return pick.model_copy(update={"score": round(value, 1), "reason": " · ".join(why)})


def recommend(track: Track, tempo: float, samples: tuple[SampleInfo, ...] | list[SampleInfo], prefer: Prefer | None = None,
              project: Project | None = None) -> list[Pick]:
    """이 트랙에 어울리는 순서. 같은 점수면 이름 순 (결과가 매번 같게).
    project를 주면 다른 트랙까지 보고, 점수가 비슷한 후보는 곡마다 순서를 바꾼다 (같은 곡이면 늘 같다)."""
    role = role_of(track)
    if role is None:
        return []
    picks = [p for s in samples if (p := score(s, role, track, tempo, prefer))]
    if project is not None:
        by_id = {s.id: s for s in samples}
        picks = [_with_neighbors(p, track, project, by_id) for p in picks]
    ordered = sorted(picks, key=lambda p: (-p.score, p.sample.name))
    if project is None or prefer is not None or not ordered:
        return ordered
    close = [p for p in ordered if ordered[0].score - p.score <= CLOSE]
    Random(f"{project.id}:{track.id}").shuffle(close)
    return close + ordered[len(close):]


# ---------- 드럼 레인 ----------

DRUM_KO = {**ROLE_NAMES, "perc": "퍼커션"}

# 레인 역할마다 쓸 수 있는 드럼 샘플 (1 = 딱 맞음). 스네어 ↔ 클랩, 크래시 ↔ 라이드는 없을 때 대신
DRUM_FIT: dict[str, dict[str, float]] = {
    "kick": {"kick": 1.0}, "snare": {"snare": 1.0, "clap": 0.5}, "clap": {"clap": 1.0, "snare": 0.5},
    "hat": {"hat": 1.0}, "openhat": {"openhat": 1.0}, "tom": {"tom": 1.0},
    "crash": {"crash": 1.0, "ride": 0.4}, "ride": {"ride": 1.0, "crash": 0.4},
}


def recommend_drum(pitch: int, samples: tuple[SampleInfo, ...] | list[SampleInfo], prefer: Prefer | None = None,
                   seed: str | None = None) -> list[Pick]:
    """드럼 레인(음 번호) 하나에 어울리는 내 드럼 샘플 순서. 같은 점수면 이름 순.
    seed를 주면 같은 점수끼리 그 값마다 순서를 바꾼다 (메뉴에 늘 이름이 앞선 샘플만 나오지 않게)."""
    role = ROLES.get(pitch)
    picks = []
    for s in samples:
        fit = DRUM_FIT.get(role or "", {}).get(s.drum or "", 0.0) if s.kind == "drum" else 0.0
        if fit:
            bonus, why = _prefer(s, prefer)
            picks.append(Pick(sample=s, score=round(100 * fit + bonus, 1), reason=" · ".join([f"{DRUM_KO[s.drum]} 샘플", *why])))
    ordered = sorted(picks, key=lambda p: p.sample.name)
    if seed is not None:
        Random(seed).shuffle(ordered)
    return sorted(ordered, key=lambda p: -p.score)  # 안정 정렬이라 같은 점수끼리는 위 순서 그대로


# ---------- 도구 ----------

class UseSampleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_ids: list[str] = Field(min_length=1, description='샘플로 바꿀 트랙 id 목록 (예: ["t2"]). 드럼 트랙이면 레인마다 맞는 드럼 샘플')
    sample: str | None = Field(
        default=None,
        description='사용자가 말한 샘플 이름 일부 또는 id. "none"이면 샘플을 빼고 원래 악기 · 킷 소리로. 없으면 트랙마다 어울리는 샘플을 고른다',
    )
    pitches: list[int] | None = Field(default=None, description="드럼 트랙만: 바꿀 레인 음 번호 (예: 킥만 [35, 36]). 없으면 쓰인 레인 모두")
    prefer: Prefer | None = Field(default=None, description='"더 어두운 · 밝은 · 짧은 · 긴 샘플로"')
    different: bool = Field(default=False, description='"다른 샘플로": 지금 쓰는 샘플 말고 다음으로 어울리는 것')


def _match(query: str, samples: tuple[SampleInfo, ...]) -> list[SampleInfo]:
    q = query.lower().strip()
    exact = [s for s in samples if s.id == query or s.name.lower() == q]
    if exact:
        return exact
    words = re.findall(r"\w+", q)
    return [s for s in samples if all(w in s.name.lower() for w in words)]


def _lanes(track: Track, pitches: list[int] | None) -> list[int]:
    """드럼 트랙에서 바꿀 레인: 쓰인 음 중 역할이 있는 것 (말한 음 번호가 있으면 그것만)."""
    used = sorted({n.pitch for n in track.notes if n.pitch in ROLES})
    return [p for p in used if pitches is None or p in pitches]


def _roles_text(pitches: list[int]) -> str:
    return " · ".join(dict.fromkeys(ROLE_NAMES[ROLES[p]] for p in pitches if p in ROLES))


def _remove(project: Project, targets: list[Track], pitches: list[int] | None) -> ToolResult:
    tracks = {t.id: t for t in project.tracks}
    lines: list[str] = []
    for t in targets:
        if t.is_drum:
            kept = {p: s for p, s in t.drum_samples.items() if pitches is not None and p not in pitches}
            if kept != t.drum_samples:
                gone = sorted(set(t.drum_samples) - set(kept))
                tracks[t.id] = t.model_copy(update={"drum_samples": kept})
                lines.append(f"{t.name} {_roles_text(gone)}에서 내 샘플을 빼고 킷 소리로 돌렸어요.")
        elif t.sample:
            tracks[t.id] = t.model_copy(update={"sample": None})
            lines.append(f"{t.name}에서 내 샘플 '{t.sample.name}'을 빼고 {display_name(heard_program(t))} 소리로 돌렸어요.")
    if not lines:
        return ToolResult(project=project, summary="내 샘플을 쓰는 트랙이 아니라 바뀐 게 없어요.")
    return ToolResult(project=project.model_copy(update={"tracks": list(tracks.values())}), changed_settings=True, summary=" ".join(lines))


def _use_on_drums(t: Track, args: UseSampleArgs, pool: tuple[SampleInfo, ...]) -> tuple[Track, str | None, str | None]:
    """드럼 트랙 하나: 레인마다 맞는 드럼 샘플. (새 트랙, 결과 한 줄, 못 했을 때 이유)."""
    lanes = _lanes(t, args.pitches)
    if not lanes:
        return t, None, f"{t.name}에 그 소리(레인)가 없어요. 쓰인 소리: {sorted({n.pitch for n in t.notes})}"
    chosen: dict[int, SampleRef] = {}
    shown: dict[str, str] = {}  # 역할 → 고른 샘플 이름 (탐 여러 레인은 한 번만)
    missing: list[int] = []
    for p in lanes:
        picks = recommend_drum(p, pool, args.prefer)
        if args.different and p in t.drum_samples:
            picks = [x for x in picks if x.sample.id != t.drum_samples[p].id] or picks
        if not picks:
            missing.append(p)
            continue
        best = picks[0].sample
        chosen[p] = SampleRef(id=best.id, name=best.name)
        shown.setdefault(ROLE_NAMES[ROLES[p]], best.name)
    if not chosen:
        have = drum_text(pool) or "없음"
        what = f"'{args.sample}'은(는) " if args.sample else ""
        return t, None, f"{t.name}({_roles_text(lanes)})에 {what}맞는 드럼 샘플이 없어요 (샘플팩의 드럼: {have})."
    samples = {**t.drum_samples, **chosen}
    if samples == t.drum_samples:
        return t, f"{t.name}는 이미 그 샘플들이에요.", None
    line = f"{t.name} 레인 소리를 내 샘플로 바꿨어요: " + ", ".join(f"{role} '{name}'" for role, name in shown.items()) + "."
    if missing:
        line += f" {_roles_text(missing)}은(는) 맞는 샘플이 없어 킷 소리 그대로예요."
    return t.model_copy(update={"drum_samples": samples}), line, None


def use_sample(project: Project, args: UseSampleArgs) -> ToolResult:
    by_id = {t.id: t for t in project.tracks}
    unknown = [i for i in args.track_ids if i not in by_id]
    if unknown:
        valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks)
        raise ToolError(f"없는 트랙 id예요: {', '.join(unknown)}. 쓸 수 있는 트랙: {valid}", code="unknown_track")
    targets = [by_id[i] for i in args.track_ids]
    if args.sample and args.sample.lower() == "none":
        return _remove(project, targets, args.pitches)

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

    tracks = {t.id: t for t in project.tracks}
    lines: list[str] = []
    errors: list[str] = []  # 여러 트랙 중 일부만 안 되면 나머지는 바꾸고 알린다 (모두 안 되면 오류)
    for t in targets:
        if t.is_drum:
            new, line, error = _use_on_drums(t, args, pool)
            if error:
                errors.append(error)
            else:
                tracks[t.id] = new
                lines.append(line or "")
            continue
        picks = recommend(t, project.tempo, pool, args.prefer, project)
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
            errors.append(
                f"{t.name}({ROLE_KO.get(role or '', '이 트랙')})에 어울리는 샘플이 샘플팩에 없어요 "
                f"(있는 종류: {kinds_text(samples)}). 음 하나짜리 원샷만 쓸 수 있어요 (코드 원샷 · 루프는 아직 못 써요)."
            )
            continue
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
    if not changed and errors:
        raise ToolError(" ".join(errors), code="no_fitting_sample")
    return ToolResult(
        project=project.model_copy(update={"tracks": list(tracks.values())}) if changed else project,
        changed_settings=changed,
        summary=" ".join([*lines, *errors]) + (" 음은 그대로예요." if changed else ""),
    )


def drum_text(samples: tuple[SampleInfo, ...] | list[SampleInfo]) -> str:
    counts: dict[str, int] = {}
    for s in samples:
        if s.kind == "drum":
            counts[s.drum or ""] = counts.get(s.drum or "", 0) + 1
    return " · ".join(f"{DRUM_KO.get(k, '역할 모름')} {n}" for k, n in counts.items())


def kinds_text(samples: tuple[SampleInfo, ...] | list[SampleInfo]) -> str:
    counts: dict[str, int] = {}
    for s in samples:
        counts[s.kind] = counts.get(s.kind, 0) + 1
    text = " · ".join(f"{KIND_KO[k]} {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1]))
    drums = drum_text(samples)
    return f"{text} (드럼: {drums})" if drums else text


def library_text(samples: tuple[SampleInfo, ...] | list[SampleInfo], limit: int = 40) -> str:
    """시스템 프롬프트에 넣을 샘플팩 한 줄 요약 + 이름 일부 (전부 넣으면 토큰이 너무 많다)."""
    def kind(s: SampleInfo) -> str:
        if s.kind == "drum":
            return DRUM_KO.get(s.drum or "", "드럼")
        return KIND_KO[s.kind] + (f" · 리듬 {s.groove.bpm:g} BPM" if s.groove else "")
    names = ", ".join(f"{s.name}({kind(s)})" for s in list(samples)[:limit])
    more = f" 외 {len(samples) - limit}개" if len(samples) > limit else ""
    return f"원샷 {len(samples)}개 — {kinds_text(samples)}\n- 이름: {names}{more}"


# ---------- 루프 리듬 → 하이햇 ----------

class GrooveFromLoopArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample: str | None = Field(default=None, description="루프 이름 일부 또는 id. 리듬이 있는 루프가 하나뿐이면 비워 둬도 된다")
    track_id: str | None = Field(
        default=None, description="이 드럼 트랙의 하이햇을 루프 리듬으로 바꾼다 (Hats 트랙 · 드럼 트랙). 없으면 새 Hats 트랙을 만든다",
    )
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")


HAT_LANES = {42, 44, 46}


def groove_from_loop(project: Project, args: GrooveFromLoopArgs) -> ToolResult:
    """루프에 녹음된 리듬(치는 자리 · 세기 · 열림)을 하이햇 MIDI로 옮겨 곡 길이만큼 되풀이한다.
    격자에 맞추지 않는다 — 루프의 밀고 당기는 맛이 그 어긋남에 있다 ("하이햇이 규칙처럼만 나온다"는 말에서)."""
    loops = [s for s in current_library() if s.kind == "loop" and s.groove and s.groove.hits]
    if not loops:
        raise ToolError(
            "리듬을 읽은 루프가 샘플팩에 없어요. 하이햇 · 드럼 루프 파일(이름에 Loop나 BPM이 있거나 여러 번 치는 소리)을 넣으면 쓸 수 있다고 알려 주세요.",
            code="no_loops",
        )
    pool = tuple(_match(args.sample, tuple(loops))) if args.sample else tuple(loops)
    if not pool:
        names = ", ".join(s.name for s in loops[:8])
        raise ToolError(f"'{args.sample}' 이름의 리듬 있는 루프가 없어요. 리듬을 읽은 루프: {names}", code="unknown_sample")
    if len(pool) > 1 and not args.sample:
        names = ", ".join(s.name for s in pool[:8])
        raise ToolError(f"리듬 있는 루프가 여럿이에요: {names}. 어느 루프로 할지 사용자에게 물어봐 주세요.", code="ambiguous_sample")
    loop = pool[0]
    groove = loop.groove
    assert groove is not None

    bpb = project.beats_per_bar
    target = None
    if args.track_id is not None:
        target = next((t for t in project.tracks if t.id == args.track_id), None)
        if target is None or not target.is_drum:
            valid = ", ".join(f"{t.id}({t.name})" for t in project.tracks if t.is_drum) or "없음"
            raise ToolError(f"하이햇을 바꿀 수 있는 드럼 트랙이 아니에요: {args.track_id}. 드럼 트랙: {valid}", code="unknown_track")
    if args.bars:
        start, end = (args.bars[0] - 1) * bpb, args.bars[1] * bpb
    else:
        start, end = 0.0, song_end(project) or groove.beats
    reps = 0
    notes: list[Note] = []
    at = start
    while at < end - 1e-6:
        for beat, velocity, open_ in groove.hits:
            t = round(at + beat, 4)
            if t < end - 1e-6:
                notes.append(Note(pitch=46 if open_ else 42, start=t, duration=round(min(1.0 if open_ else HIT, end - t), 4),
                                  velocity=max(1, min(127, velocity))))
        at += groove.beats
        reps += 1
    notes = _untangle(notes)
    if not notes:
        raise ToolError("그 범위에 하이햇을 깔 자리가 없어요.", code="empty_range")

    opens = sum(n.pitch == 46 for n in notes)
    vels = [n.velocity for n in notes]
    loop_bars = groove.beats / bpb
    detail = (f"'{loop.name}' 루프({groove.bpm:g} BPM · {loop_bars:g}마디)의 리듬 {len(groove.hits)}타를 {reps}번 되풀이 · "
              f"열린 햇 {opens}타 · 세기 {min(vels)}~{max(vels)} · 루프의 밀고 당기는 타이밍을 그대로 (격자에 맞추지 않음)")
    if target is not None:
        kept = [n for n in target.notes if not (n.pitch in HAT_LANES and start - 1e-6 <= n.start < end - 1e-6)]
        track = target.model_copy(update={"notes": sorted([*kept, *notes], key=lambda n: (n.start, n.pitch))})
        tracks = [track if t.id == target.id else t for t in project.tracks]
        return ToolResult(project=project.model_copy(update={"tracks": tracks}), changed_notes=len(notes),
                          summary=f"{target.name}({target.id}) 트랙의 하이햇을 {detail}.")
    kit = next((t.program for t in project.tracks if t.is_drum), 0)
    track = Track(id=new_track_id(project), name=free_name(project, "Hats"), is_drum=True, program=kit, program_set=True, notes=notes)
    return ToolResult(project=project.model_copy(update={"tracks": [*project.tracks, track]}), changed_notes=len(notes),
                      summary=f"새 드럼 트랙 {track.name}({track.id})에 {detail}. {SOUND_NOTE}")


# 리듬만 옮기고 소리는 킷이다 — "루프 소리 자체로 들으려면 '하이햇 내 샘플로'"라고 틀리게 안내해서 둘을 나눠 적는다
SOUND_NOTE = ("소리는 킷 하이햇이에요. 하이햇 원샷이 있으면 \"하이햇 내 샘플로\"로 원샷 소리로 바꿀 수 있지만, "
              "그건 루프 소리 자체가 아니에요 (루프에서 옮긴 건 리듬뿐).")


# ---------- 루프를 오디오로 ----------

class AddLoopArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample: str | None = Field(default=None, description="루프 이름 일부 또는 id. 템포를 아는 루프가 하나뿐이면 비워 둬도 된다")
    bars: tuple[Bar, Bar] | None = Field(default=None, description="[시작, 끝] 마디, 끝 포함. 없으면 곡 전체")
    name: str | None = Field(default=None, max_length=40, description="새 트랙 이름. 없으면 루프 이름")


def add_loop(project: Project, args: AddLoopArgs) -> ToolResult:
    """루프 파일을 오디오 트랙으로 그대로 깐다 (소리 그대로 — 음을 하나하나 고칠 수는 없음).
    곡 템포에 맞추려고 재생 속도를 바꾸므로 음높이도 같이 바뀐다 (드럼 루프는 괜찮고, 멜로디 루프는 키가 어긋날 수 있다)."""
    loops = [s for s in current_library() if s.kind == "loop" and s.groove]
    if not loops:
        raise ToolError(
            "템포를 읽은 루프가 샘플팩에 없어요. 루프 파일(이름에 Loop나 BPM이 있거나 여러 번 치는 소리)을 넣으면 쓸 수 있다고 알려 주세요.",
            code="no_loops",
        )
    pool = tuple(_match(args.sample, tuple(loops))) if args.sample else tuple(loops)
    if not pool:
        names = ", ".join(s.name for s in loops[:8])
        raise ToolError(f"'{args.sample}' 이름의 루프가 없어요. 템포를 읽은 루프: {names}", code="unknown_sample")
    if len(pool) > 1 and not args.sample:
        names = ", ".join(s.name for s in pool[:8])
        raise ToolError(f"루프가 여럿이에요: {names}. 어느 루프로 할지 사용자에게 물어봐 주세요.", code="ambiguous_sample")
    loop = pool[0]
    groove = loop.groove
    assert groove is not None
    bpb = project.beats_per_bar
    if args.bars:
        start, end = (args.bars[0] - 1) * bpb, args.bars[1] * bpb
    else:
        start, end = 0.0, song_end(project) or groove.beats
    clip = AudioClip(sample=SampleRef(id=loop.id, name=loop.name), bpm=groove.bpm, beats=groove.beats, start=start, end=end)
    name = args.name or free_name(project, loop.name[:40])
    track = Track(id=new_track_id(project), name=name, notes=[], audio=clip)
    ratio = project.tempo / groove.bpm
    shift = 12 * math.log2(ratio)
    warn = ""
    if abs(ratio - 1) < 0.005:
        speed = "원래 속도 그대로"
    elif loop.root is None:
        # 리듬 루프는 브라우저가 타격마다 잘라 원래 속도로 곡 템포 자리에 놓는다 (frontend instruments.ts playEvents)
        speed = (f"곡 템포 {round(project.tempo, 1):g}에 맞춰 타격마다 잘라 그 자리에 놓았어요 "
                 f"(소리 · 음높이는 그대로, 곡이 {'느려서 타격 사이가 조금 비어요' if ratio < 1 else '빨라서 타격 꼬리가 조금 짧아져요'})")
    else:
        speed = (f"곡 템포 {round(project.tempo, 1):g}에 맞춰 {abs(ratio - 1) * 100:.0f}% {'빠르게' if ratio > 1 else '느리게'} "
                 f"(음높이도 {abs(shift):.1f}반음 {'높게' if shift > 0 else '낮게'})")
        if abs(shift) >= 1:
            warn = " 음높이가 바뀌어 멜로디 루프라면 곡의 키와 어긋날 수 있어요."
    reps = (end - start) / groove.beats
    return ToolResult(
        project=project.model_copy(update={"tracks": [*project.tracks, track]}),
        changed_settings=True,
        summary=(f"새 오디오 트랙 {name}({track.id})에 '{loop.name}' 루프({groove.bpm:g} BPM · {groove.beats / bpb:g}마디)를 "
                 f"{start / bpb + 1:g}~{end / bpb:g}마디에 {reps:g}번 깔았어요 · {speed}.{warn} "
                 "소리 그대로라 음을 하나하나 고칠 수는 없고, MIDI로 내보내면 빠져요 (음원에는 담겨요). 볼륨 · 팬 · 음소거는 돼요."),
    )
