"""리하모니 제안: 지금 코드 진행에서 색깔이 다른 대리코드 진행 3개(가볍게 · 재지하게 · 색다르게)를 계산한다.

- 가볍게: 같은 기능 코드로 바꾸기(IV ↔ ii, 단조는 iv ↔ iiø) + 음계 안의 텐션(7 · 9음) 더하기
- 재지하게: 다음 코드로 끌어당기는 딸림7을 끼워 넣기(부속 딸림 · ii–V). 으뜸화음으로 가는 딸림은 트라이톤 대리(V7 → bII7)
- 색다르게: 같은 으뜸음의 반대 조에서 빌려온 화음 (장조: iv · iiø · bVII7, 없으면 bVI / 단조: IV7 · ii · V7 · 마지막 I)

바꿀 때마다 멜로디와 부딪히는지 본다. 멜로디 음이 새 코드 음의 반음 위(b9 — C 코드의 E 위 F)인데 센박이거나
한 박 넘게 울리면 그 바꾸기는 하지 않고 다음 후보로(끝까지 안 되면 원래 코드), 약박의 짧은 음이면 바꾸되 "살짝 부딪혀요"로
알린다. 딸림7의 b9 · b13(G7 위 Ab · Eb)은 재즈에서 쓰는 텐션이라 세지 않고, 원래 코드에서도 부딪히던 음도 세지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.harmony.analyze import FLAT_DEGREES, ChordSpan, HarmonyAnalysis, analyze, family, label, melody_ids, pc_name, spell
from app.models.project import Project

# 코드 종류 → 근음에서의 음정 (analyze._quality가 붙이는 이름 전부)
INTERVALS: dict[str, tuple[int, ...]] = {
    "": (0, 4, 7), "m": (0, 3, 7), "5": (0, 7), "aug": (0, 4, 8), "dim": (0, 3, 6), "dim7": (0, 3, 6, 9),
    "m7b5": (0, 3, 6, 10), "6": (0, 4, 7, 9), "6/9": (0, 4, 7, 9, 2), "m6": (0, 3, 7, 9),
    "add9": (0, 4, 7, 2), "madd9": (0, 3, 7, 2),
    "maj7": (0, 4, 7, 11), "maj9": (0, 4, 7, 11, 2), "maj13": (0, 4, 7, 11, 2, 9),
    "7": (0, 4, 7, 10), "9": (0, 4, 7, 10, 2), "13": (0, 4, 7, 10, 2, 9),
    "m7": (0, 3, 7, 10), "m9": (0, 3, 7, 10, 2), "m11": (0, 3, 7, 10, 2, 5), "m(maj7)": (0, 3, 7, 11),
    "sus2": (0, 2, 7), "sus4": (0, 5, 7), "7sus4": (0, 5, 7, 10),
}
DOMINANT = ("7", "9", "13")
STYLES = ("가볍게", "재지하게", "색다르게")

# 음계 화음에 더할 텐션 (으뜸음에서 반음 수 → 종류). 음계 밖 음이 생기지 않는 것만 (장조 iii은 b9가 생겨 m7까지)
TENSION = {
    "major": {0: "maj9", 2: "m9", 4: "m7", 5: "maj9", 7: "9", 9: "m9", 11: "m7b5"},
    "minor": {0: "m9", 2: "m7b5", 3: "maj9", 5: "m9", 7: "7", 8: "maj9", 10: "9"},
}
PLAIN = {"", "m", "maj7", "m7", "7", "add9", "madd9"}  # 텐션을 더할 단순한 코드 (이미 9 · 11 · 13 · sus면 그대로)
EPS = 1e-6

# 한 구간을 바꿀 조각: (시작, 끝, 근음, 베이스, 종류, 바꾼 까닭). 까닭 ""은 원래 코드를 그대로 둔 조각
Piece = tuple[float, float, int, int, str, str]


@dataclass
class Change:
    start: float
    before: str  # "F"
    after: list[str]  # ["Dm9"] · 반 마디씩 나누면 ["C", "D7"]
    kind: str  # "같은 기능" · "텐션" · "부속 딸림" · "ii–V" · "딸림 끼워 넣기" · "트라이톤 대리" · "빌려온 화음"


@dataclass
class Suggestion:
    style: str  # STYLES 중 하나
    chords: list[ChordSpan]  # 곡 전체 (범위 밖은 원래 코드 그대로)
    changes: list[Change]
    rubs: list[str] = field(default_factory=list)  # 약박에서 살짝 부딪히는 멜로디 음


def _tones(root: int, quality: str) -> set[int]:
    return {(root + i) % 12 for i in INTERVALS.get(quality, (0,))}


def rubs(pc: int, root: int, quality: str) -> bool:
    """멜로디 음 pc가 코드 음의 반음 위인가 (딸림7의 b9 · b13은 텐션이라 아님)."""
    tones = _tones(root, quality)
    below = (pc - 1) % 12
    if pc in tones or below not in tones:
        return False
    return not (quality in DOMINANT and below in (root, (root + 7) % 12))


def _accented(start: float, bpb: float) -> bool:
    """센박: 4/4의 1 · 3박처럼 마디를 반으로 나눈 자리 (홀수 박자는 첫 박만). 사람이 친 흔들림 0.1박까지."""
    unit = bpb / 2 if bpb % 2 == 0 else bpb
    pos = start % unit
    return min(pos, unit - pos) < 0.1


class _Builder:
    def __init__(self, a: HarmonyAnalysis, melody: list[tuple[int, float, float]], start: float, end: float) -> None:
        self.a, self.key, self.bpb = a, a.key, a.beats_per_bar
        self.melody, self.start, self.end = melody, start, end
        self.want = "maj" if self.key.mode == "major" else "min"
        real = [c for c in a.chords if c.root is not None]
        self.real = real
        # 루프(으뜸화음으로 끝나지 않음)는 마지막 코드 다음이 첫 코드다 — 되풀이할 때 그 이음새가 가장 중요한 진행
        self.loops = bool(real) and not self._is_tonic(real[-1])

    # ---------- 도움 ----------

    def _iv(self, c: ChordSpan) -> int:
        return (c.root - self.key.tonic) % 12

    def _is_tonic(self, c: ChordSpan) -> bool:
        return c.root == self.key.tonic and family(c.quality) in (self.want, None)

    def _next(self, c: ChordSpan) -> ChordSpan | None:
        later = [r for r in self.real if r.start > c.start + EPS]
        if later:
            return later[0]
        return self.real[0] if self.loops and self.real[0] is not c else None

    def _spell(self, root: int) -> str:
        """새 코드 근음 이름: 분석과 같은 규칙(A# 말고 Bb)에 bV도 b로 — 트라이톤 대리 subV7/IV는 C major에서 Gb7."""
        return pc_name(root, self.key.flats or (root - self.key.tonic) % 12 in FLAT_DEGREES[self.key.mode] | {6})

    def _tritone_ahead(self, c: ChordSpan) -> bool:
        """c가 으뜸화음으로 가는 딸림이라 재지하게에서 트라이톤 대리(bII7)로 바뀔 자리인가."""
        nxt = self._next(c)
        return nxt is not None and self._is_tonic(nxt) and (c.root - nxt.root) % 12 == 7 and family(c.quality) == "maj"

    def _inside(self, c: ChordSpan) -> bool:
        return c.root is not None and self.start - EPS <= c.start < self.end - EPS

    def _tension(self, c: ChordSpan, dominant: str | None = None) -> str | None:
        """같은 종류(장 · 단 · 감)를 지키며 음계 안의 텐션을 더한 종류. 더할 게 없으면 None."""
        if c.quality not in PLAIN:
            return None
        t = TENSION[self.key.mode].get(self._iv(c))
        if t is None or family(t) != family(c.quality):
            return None
        if dominant and t in DOMINANT:
            t = dominant
        return None if t == c.quality else t

    def name(self, root: int, bass: int, quality: str, kept: bool) -> str:
        """근음을 그대로 둔 코드는 분석과 같은 표기, 새 근음은 _spell."""
        name = (lambda pc: spell(pc, self.key)) if kept else self._spell
        return name(root) + quality + (f"/{name(bass)}" if bass != root else "")

    def _keep(self, c: ChordSpan, quality: str, kind: str) -> Piece:
        """근음은 그대로 두고 종류만 바꾼 조각. 자리바꿈 베이스는 새 코드 음이면 그대로 (C/E → Cmaj9/E)."""
        bass = c.bass if c.bass is not None and c.bass % 12 in _tones(c.root, quality) else c.root
        return (c.start, c.end, c.root, bass, quality, kind)

    def _split_at(self, c: ChordSpan) -> float | None:
        """딸림7을 끼워 넣을 자리: 두 마디 이상이면 마지막 마디, 한 마디 이상이면 마지막 반 마디 (홀수 박자는 안 나눔)."""
        length = c.end - c.start
        if length >= 2 * self.bpb - EPS:
            return c.end - self.bpb
        if length >= self.bpb - EPS and self.bpb % 2 == 0:
            return c.end - self.bpb / 2
        return None

    # ---------- 스타일마다 후보 (앞에서부터 시도, 부딪히면 다음) ----------

    def plan(self, style: str) -> None:
        """범위 전체를 보고 정하는 것: 가볍게는 어떤 같은 기능 바꾸기를, 색다르게는 bVI까지 쓸지."""
        cs = [c for c in self.real if self._inside(c)]
        has = lambda iv, fam: any(self._iv(c) == iv and family(c.quality) == fam for c in cs)  # noqa: E731
        self.swap = None
        if style == "가볍게":
            if self.key.mode == "major":
                self.swap = (5, "maj", 2, "m9") if has(5, "maj") else (2, "min", 5, "maj9") if has(2, "min") else None
            else:
                self.swap = (5, "min", 2, "m7b5") if has(5, "min") else (2, "dim", 5, "m9") if has(2, "dim") else None
        self.flat_six = style == "색다르게" and not any(self._borrow(c) for c in cs)

    def options(self, style: str, c: ChordSpan) -> list[list[Piece]]:
        return {"가볍게": self._light, "재지하게": self._jazzy, "색다르게": self._colorful}[style](c)

    def _light(self, c: ChordSpan) -> list[list[Piece]]:
        out = []
        if self.swap and self._iv(c) == self.swap[0] and family(c.quality) == self.swap[1]:
            root = (self.key.tonic + self.swap[2]) % 12
            out.append([(c.start, c.end, root, root, self.swap[3], "같은 기능")])
        if t := self._tension(c):
            out.append([self._keep(c, t, "텐션")])
        return out

    def _jazzy(self, c: ChordSpan) -> list[list[Piece]]:
        out: list[list[Piece]] = []
        nxt = self._next(c)
        t = self._tension(c, dominant="13")
        here = self._keep(c, t or c.quality, "텐션" if t else "")
        if nxt is not None and family(nxt.quality) in ("maj", "min") and nxt.root != c.root:
            target = nxt.root
            to_tonic = self._is_tonic(nxt)
            if (c.root - target) % 12 == 7:
                # 이미 다음 코드의 딸림 자리: 으뜸화음으로 가면 트라이톤 대리 (G7 → C를 Db7 → C로, 베이스가 반음으로 내려감)
                if self._tritone_ahead(c):
                    sub = (target + 1) % 12
                    out.append([(c.start, c.end, sub, sub, "7", "트라이톤 대리")])
            elif self._inside(nxt) and self._tritone_ahead(nxt):
                pass  # 다음 코드가 Db7로 바뀌는데 그 앞에 D7(V7/V)을 넣으면 D7이 갈 곳(G)이 없어진다: F → Db7 → C 그대로
            elif (at := self._split_at(c)) is not None:
                dom = (target + 7) % 12
                first = (c.start, at, *here[2:])
                if at - c.start >= self.bpb - EPS and self.bpb % 2 == 0:
                    # 두 마디 이상: 마지막 마디를 다음 코드의 ii–V로
                    ii = (target + 2) % 12
                    half = at + self.bpb / 2
                    out.append([first, (at, half, ii, ii, "m7" if family(nxt.quality) == "maj" else "m7b5", "ii–V"),
                                (half, c.end, dom, dom, "7", "ii–V")])
                if to_tonic:
                    sub = (target + 1) % 12
                    out.append([first, (at, c.end, sub, sub, "7", "트라이톤 대리")])
                kind = "ii–V" if (c.root - target) % 12 == 2 else "딸림 끼워 넣기" if to_tonic else "부속 딸림"
                out.append([first, (at, c.end, dom, dom, "7", kind)])
        if t:
            out.append([self._keep(c, t, "텐션")])
        return out

    def _borrow(self, c: ChordSpan) -> list[tuple[int, str]]:
        """빌려온 화음 후보 [(으뜸음에서 반음 수, 종류)]."""
        iv, fam = self._iv(c), family(c.quality)
        nxt = self._next(c)
        if self.key.mode == "major":
            if iv == 5 and fam == "maj":
                return [(5, "m6"), (5, "m7")]  # IV → iv (Fm6: 서브도미넌트 마이너)
            if iv == 2 and fam == "min":
                return [(2, "m7b5")]  # ii → iiø
            if iv == 7 and fam == "maj":
                # V → bVII: 으뜸화음으로 가면 bVII7 (Bb7 → C, "뒷문" 딸림)
                return [(10, "7"), (10, "")] if nxt is not None and self._is_tonic(nxt) else [(10, "")]
            return []
        if iv == 5 and fam == "min":
            return [(5, "7")]  # iv → IV7 (도리안)
        if iv == 2 and fam == "dim":
            return [(2, "m7")]  # iiø → ii
        if iv == 7 and fam == "min":
            return [(7, "7")]  # v → V7
        if self._is_tonic(c) and c is self.real[-1] and not self.loops:
            return [(0, "")]  # 끝 코드 i → I (피카르디 3도)
        return []

    def _colorful(self, c: ChordSpan) -> list[list[Piece]]:
        cands = self._borrow(c)
        if not cands and self.flat_six and self.key.mode == "major" and self._iv(c) == 9 and family(c.quality) == "min":
            cands = [(8, "maj7")]  # 위 화음이 하나도 없을 때만 vi → bVI
        out = []
        for iv, q in cands:
            root = (self.key.tonic + iv) % 12
            out.append([(c.start, c.end, root, root, q, "빌려온 화음")])
        return out

    # ---------- 멜로디 검사 ----------

    def check(self, piece: Piece, c: ChordSpan) -> tuple[bool, list[str]]:
        """(센 부딪힘이 있나, 약한 부딪힘 설명)."""
        s, e, root, _, q, kind = piece
        if not kind:
            return False, []
        weak = []
        for pitch, ns, nd in self.melody:
            overlap = min(e, ns + nd) - max(s, ns)
            if overlap <= EPS:
                continue
            pc = pitch % 12
            if not rubs(pc, root, q) or rubs(pc, c.root, c.quality):
                continue
            if (ns >= s - 0.1 and _accented(ns, self.bpb)) or overlap >= 1 - EPS:
                return True, []
            weak.append(f"{self.where(ns)} 멜로디 {spell(pc, self.key)} ↔ {self.name(root, root, q, kept=root == c.root)} (반음)")
        return False, weak

    def where(self, beat: float) -> str:
        bar = int(beat // self.bpb) + 1
        rest = beat - (bar - 1) * self.bpb
        return f"{bar}마디" if abs(rest) < 0.05 else f"{bar}마디 {round(rest + 1, 2):g}박"

    # ---------- 진행 만들기 ----------

    def build(self, style: str) -> Suggestion:
        self.plan(style)
        chords: list[ChordSpan] = []
        kinds: list[str] = []
        changes: list[Change] = []
        rubs: list[str] = []
        for c in self.a.chords:
            chosen = None
            if self._inside(c):
                for pieces in self.options(style, c):
                    found = [self.check(p, c) for p in pieces]
                    if not any(strong for strong, _ in found):
                        chosen = pieces
                        rubs += [w for _, ws in found for w in ws]
                        break
            if chosen is None:
                chords.append(replace(c))
                kinds.append("")
                continue
            names = []
            for s, e, root, bass, q, kind in chosen:
                name = self.name(root, bass, q, kept=root == c.root)
                chords.append(ChordSpan(s, e, root, bass, name, q, "", "", 0.0))
                kinds.append(kind)
                names.append(name)
            # 까닭은 마지막 조각의 것 (C → Cmaj9 · D7이면 "부속 딸림", 앞 조각의 텐션보다 큰 바꾸기)
            changes.append(Change(c.start, c.name, names, [k for *_, k in chosen if k][-1]))
        # 바꾼 뒤 같은 코드가 이어지면 하나로 (Cmadd9 · Cm7 → C7 · C7은 C7 두 마디)
        merged: list[ChordSpan] = []
        merged_kinds: list[str] = []
        for c, kind in zip(chords, kinds):
            if merged and merged[-1].name == c.name and abs(merged[-1].end - c.start) < EPS:
                merged[-1].end = c.end
                merged_kinds[-1] = merged_kinds[-1] or kind
            else:
                merged.append(c)
                merged_kinds.append(kind)
        chords, kinds = merged, merged_kinds
        label(chords, self.key)
        self._name_borrowed(chords, kinds)
        return Suggestion(style, chords, changes, rubs)

    def _name_borrowed(self, chords: list[ChordSpan], kinds: list[str]) -> None:
        """label()이 모르는 것: 트라이톤 대리는 subV7(다음 코드의 대리 딸림), 빌려온 화음은 기능을 '차용'으로."""
        real = [c for c in chords if c.root is not None]
        for c, kind in zip(chords, kinds):
            if kind == "빌려온 화음":
                c.function = "차용"
            elif kind == "트라이톤 대리":
                later = [r for r in real if r.start > c.start + EPS] or real[:1]
                target = later[0]
                if target.root == self.key.tonic:
                    c.roman, c.function = "subV7", "D"
                else:
                    c.roman, c.function = f"subV7/{target.roman.rstrip('7').replace('maj', '')}", "부속"


def suggest(project: Project, start: float = 0.0, end: float | None = None) -> tuple[HarmonyAnalysis, list[Suggestion]]:
    """(지금 분석, 제안 최대 3개). [start, end) 박 안에서 시작하는 코드만 바꾼다. 바꿀 게 없는 스타일은 빠진다."""
    a = analyze(project)
    if not a.chords:
        return a, []
    ids = melody_ids(project)
    melody = [(n.pitch, n.start, n.duration) for t in project.tracks if t.id in ids for n in t.notes]
    b = _Builder(a, melody, start, a.chords[-1].end if end is None else end)
    out: list[Suggestion] = []
    for style in STYLES:
        s = b.build(style)
        if s.changes and all([c.name for c in s.chords] != [c.name for c in o.chords] for o in out):
            out.append(s)
    return a, out
