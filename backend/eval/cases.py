"""정답 있는 명령 34개.

샘플 트랙 id
- lofi_groove: t1 Drums(36 Kick · 38 Snare · 42 Closed Hat · 46 Open Hat …) · t2 Bass · t3 Rhodes · t4 Pad · t5 Lead (16마디)
- fl_style_loose: t1 FPC(36 Kick · 39 Clap · 42 Hat) · t2 Chords · t3 Bass · t4 Melody (박자 · 세기가 흔들림)
"""

from __future__ import annotations

from eval.spec import ALL, Call, Case, Pitches, Range

HATS = Pitches(frozenset({42, 44, 46}), frozenset({42}))
SOFTER = Range(0.5, 0.85)  # "좀 약하게"
SOFTER_OFFSET = Range(-40, -8)
LOUDER = Range(1.1, 1.8)
LOUDER_OFFSET = Range(5, 40)
FULL = Range(0.95, 1.0, default=1.0)  # 퀀타이즈 "맞춰" = 끝까지
EIGHTH = Range(0.5, 0.5, default=0.5)
SIXTEENTH = Range(0.25, 0.25, default=0.25)


# 정답 묶음: (기본 정답, 다른 정답들)
Answer = tuple[tuple[Call, ...], tuple[tuple[Call, ...], ...]]


def velocity(track: str, scale: Range, offset: Range, **extra) -> Answer:
    """세기는 곱하기(scale)와 더하기(offset) 둘 다 정답으로 본다."""
    main = (Call("adjust_velocity", {"track_ids": [track], "mode": "scale", "value": scale, **extra}),)
    alt = ((Call("adjust_velocity", {"track_ids": [track], "mode": "offset", "value": offset, **extra}),),)
    return main, alt


def octave(track: str, n: int, **extra) -> Answer:
    """옥타브는 shift_octave n과 transpose 12n 둘 다 정답."""
    main = (Call("shift_octave", {"track_ids": [track], "octaves": n, **extra}),)
    alt = ((Call("transpose", {"track_ids": [track], "semitones": 12 * n, **extra}),),)
    return main, alt


def case(id, category, sample, command, spec: list[Call] | Answer = (), alt=(), note="") -> Case:
    """spec은 정답 호출 목록(list)이나, velocity() · octave()가 만든 (정답, 다른 정답들) 묶음(tuple)."""
    if isinstance(spec, tuple) and spec:
        spec, alt = spec
    return Case(id, category, sample, command, tuple(spec), tuple(alt), note)


V_HATS = velocity("t1", SOFTER, SOFTER_OFFSET, pitches=HATS)
O_LEAD_DOWN = octave("t5", -1)

CASES: list[Case] = [
    # ---------- 조옮김 · 옥타브 ----------
    case("T01", "조옮김", "lofi_groove", "베이스 2키 올려줘", [Call("transpose", {"track_ids": ["t2"], "semitones": 2})]),
    case("T02", "조옮김", "lofi_groove", "멜로디 한 옥타브 내려줘", O_LEAD_DOWN),
    case("T03", "조옮김", "lofi_groove", "전체를 반음 내려줘", [Call("transpose", {"track_ids": ALL, "semitones": -1})]),
    case("T04", "조옮김", "lofi_groove", "건반 5반음 올려줘", [Call("transpose", {"track_ids": ["t3"], "semitones": 5})]),
    case("T05", "조옮김", "lofi_groove", "2마디부터 4마디까지 베이스 한 옥타브 올려줘", octave("t2", 1, bars=[2, 4])),
    case("T06", "조옮김", "lofi_groove", "패드를 두 옥타브 위로", octave("t4", 2)),
    case("T07", "조옮김", "lofi_groove", "리드 7키 내려", [Call("transpose", {"track_ids": ["t5"], "semitones": -7})]),
    # ---------- 퀀타이즈 ----------
    case("Q01", "퀀타이즈", "fl_style_loose", "코드 박자 맞춰줘", [Call("quantize", {"track_ids": ["t2"], "strength": FULL})]),
    case("Q02", "퀀타이즈", "fl_style_loose", "코드 박자 정리해줘, 너무 딱딱하진 않게",
         [Call("quantize", {"track_ids": ["t2"], "strength": Range(0.5, 0.85)})]),
    case("Q03", "퀀타이즈", "fl_style_loose", "전부 16분음표로 퀀타이즈해줘",
         [Call("quantize", {"track_ids": ALL, "grid": SIXTEENTH, "strength": FULL})],
         alt=[(Call("quantize", {"track_ids": ["t2", "t3", "t4"], "grid": SIXTEENTH, "strength": FULL}),
               Call("quantize", {"track_ids": ["t1"], "grid": SIXTEENTH, "strength": FULL}))],
         note="드럼까지 포함해도, 빼도 정답. 멜로디 트랙과 드럼을 나눠 두 번 불러도 결과가 같아 정답"),
    case("Q04", "퀀타이즈", "fl_style_loose", "드럼만 8분음표 격자로 맞춰", [Call("quantize", {"track_ids": ["t1"], "grid": EIGHTH})]),
    case("Q05", "퀀타이즈", "fl_style_loose", "베이스 박자를 50%만 당겨줘",
         [Call("quantize", {"track_ids": ["t3"], "strength": Range(0.45, 0.55)})]),
    # ---------- 세기 ----------
    case("V01", "세기", "lofi_groove", "하이햇 좀 약하게", V_HATS),
    case("V02", "세기", "lofi_groove", "킥만 세게", velocity("t1", LOUDER, LOUDER_OFFSET, pitches=Pitches(frozenset({35, 36}), frozenset({36})))),
    case("V03", "세기", "lofi_groove", "9마디부터 패드 약하게", velocity("t4", SOFTER, SOFTER_OFFSET, bars=[9, 16])),
    case("V04", "세기", "lofi_groove", "멜로디 세기를 전부 100으로 맞춰",
         [Call("adjust_velocity", {"track_ids": ["t5"], "mode": "set", "value": 100})]),
    case("V05", "세기", "lofi_groove", "베이스 볼륨 20 줄여줘",
         [Call("adjust_velocity", {"track_ids": ["t2"], "mode": "offset", "value": -20})]),
    case("V06", "세기", "lofi_groove", "스네어 조금 더 세게",
         velocity("t1", Range(1.05, 1.5), Range(5, 30), pitches=Pitches(frozenset({37, 38, 40}), frozenset({38})))),
    # ---------- 스윙 ----------
    case("S01", "스윙", "lofi_groove", "하이햇에 살짝 스윙 넣어줘",
         [Call("swing", {"track_ids": ["t1"], "pitches": HATS, "percent": Range(53, 60), "grid": EIGHTH})]),
    case("S02", "스윙", "lofi_groove", "드럼에 스윙 넣어줘", [Call("swing", {"track_ids": ["t1"], "percent": Range(55, 66)})]),
    case("S03", "스윙", "lofi_groove", "16분음표 스윙 60%로 넣어줘", [Call("swing", {"grid": 0.25, "percent": 60.0})],
         note="트랙은 정하지 않음 (전체든 드럼이든 정답)"),
    case("S04", "스윙", "lofi_groove", "베이스에 셔플 느낌 강하게", [Call("swing", {"track_ids": ["t2"], "percent": Range(62, 72)})]),
    # ---------- 여러 도구 ----------
    case("M01", "여러 도구", "lofi_groove", "하이햇 좀 약하게 하고 살짝 스윙 넣어줘",
         [V_HATS[0][0], Call("swing", {"track_ids": ["t1"], "pitches": HATS, "percent": Range(53, 60)})],
         alt=[(V_HATS[1][0][0], Call("swing", {"track_ids": ["t1"], "pitches": HATS, "percent": Range(53, 60)}))]),
    case("M02", "여러 도구", "lofi_groove", "베이스 2키 올리고 멜로디는 한 옥타브 내려줘",
         [Call("transpose", {"track_ids": ["t2"], "semitones": 2}), O_LEAD_DOWN[0][0]],
         alt=[(Call("transpose", {"track_ids": ["t2"], "semitones": 2}), O_LEAD_DOWN[1][0][0])]),
    case("M03", "여러 도구", "fl_style_loose", "드럼 박자 맞추고 하이햇은 약하게",
         [Call("quantize", {"track_ids": ["t1"], "strength": FULL}),
          Call("adjust_velocity", {"track_ids": ["t1"], "pitches": HATS, "mode": "scale", "value": SOFTER})],
         alt=[(Call("quantize", {"track_ids": ["t1"], "strength": FULL}),
               Call("adjust_velocity", {"track_ids": ["t1"], "pitches": HATS, "mode": "offset", "value": SOFTER_OFFSET}))]),
    case("M04", "여러 도구", "lofi_groove", "9마디부터 패드 약하게 하고 베이스 2키 올려줘",
         [velocity("t4", SOFTER, SOFTER_OFFSET, bars=[9, 16])[0][0], Call("transpose", {"track_ids": ["t2"], "semitones": 2, "bars": None})],
         alt=[(velocity("t4", SOFTER, SOFTER_OFFSET, bars=[9, 16])[1][0][0], Call("transpose", {"track_ids": ["t2"], "semitones": 2, "bars": None}))],
         note="'9마디부터'는 패드에만. 베이스는 곡 전체"),
    # ---------- 템포 ----------
    case("P01", "템포", "lofi_groove", "템포 100으로 바꿔줘", [Call("set_tempo", {"mode": "set", "value": 100.0})]),
    case("P02", "템포", "lofi_groove", "BPM 10 올려줘", [Call("set_tempo", {"mode": "offset", "value": 10.0})],
         alt=[(Call("set_tempo", {"mode": "set", "value": 94.0}),)]),
    case("P03", "템포", "lofi_groove", "조금만 빠르게",
         [Call("set_tempo", {"mode": "scale", "value": Range(1.03, 1.15)})],
         alt=[(Call("set_tempo", {"mode": "offset", "value": Range(3, 12)}),), (Call("set_tempo", {"mode": "set", "value": Range(87, 96)}),)],
         note="84 BPM에서 3~12 BPM 정도"),
    # ---------- 편집하면 안 되는 명령 ----------
    case("C01", "되묻기 · 정보", "lofi_groove", "지금 무슨 트랙 있어?", note="정보만 답하고 편집하지 않음"),
    case("C02", "되묻기 · 정보", "lofi_groove", "좀 더 좋게 해줘", note="막연함 → 되묻기"),
    case("C03", "되묻기 · 정보", "lofi_groove", "느낌 있게 바꿔줘", note="막연함 → 되묻기"),
    case("C04", "되묻기 · 정보", "lofi_groove", "드럼 2키 올려줘", note="드럼은 조옮김 대상이 아님 → 바뀐 음 0개"),
    case("C05", "되묻기 · 정보", "lofi_groove", "스트링 트랙 한 옥타브 올려줘", note="없는 트랙 → 편집하지 않고 알려 줌"),
]

assert len(CASES) == 34 and len({c.id for c in CASES}) == 34
