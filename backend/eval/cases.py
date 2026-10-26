"""정답 있는 명령 76개.

샘플 트랙 id
- lofi_groove: t1 Drums(36 Kick · 38 Snare · 42 Closed Hat · 46 Open Hat …) · t2 Bass · t3 Rhodes · t4 Pad · t5 Lead (16마디)
- fl_style_loose: t1 FPC(36 Kick · 39 Clap · 42 Hat) · t2 Chords · t3 Bass · t4 Melody (박자 · 세기가 흔들림)
"""

from __future__ import annotations

from eval.spec import ALL, Call, Case, OneOf, Pitches, Range

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


def case(id, category, sample, command, spec: list[Call] | Answer = (), alt=(), note="", selection=None, reads=(), reply_has=(),
         reply_lacks=()) -> Case:
    """spec은 정답 호출 목록(list)이나, velocity() · octave()가 만든 (정답, 다른 정답들) 묶음(tuple)."""
    if isinstance(spec, tuple) and spec:
        spec, alt = spec
    return Case(id, category, sample, command, tuple(spec), tuple(alt), note, selection, tuple(reads), tuple(reply_has), tuple(reply_lacks))


NO_KO_KEY = ("장조", "단조")
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
               Call("quantize", {"track_ids": ["t1"], "grid": SIXTEENTH, "strength": FULL})),
              tuple(Call("quantize", {"track_ids": [t], "grid": SIXTEENTH, "strength": FULL}) for t in ("t1", "t2", "t3", "t4")),
              tuple(Call("quantize", {"track_ids": [t], "grid": SIXTEENTH, "strength": FULL}) for t in ("t2", "t3", "t4"))],
         note="드럼까지 포함해도, 빼도 정답. 트랙을 나눠 여러 번 불러도 결과가 같아 정답"),
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
         [Call("set_mix", {"track_ids": ["t2"], "volume_offset": -20})],
         alt=[(Call("adjust_velocity", {"track_ids": ["t2"], "mode": "offset", "value": -20}),)],
         note="트랙 볼륨(set_mix)이 생긴 뒤로는 볼륨이 정답. 예전처럼 세기를 20 낮춰도 들리는 결과가 비슷해 인정"),
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
    case("I01", "악기", "lofi_groove", "베이스를 신스 베이스로 바꿔줘",
         [Call("set_instrument", {"track_ids": ["t2"], "program": Range(38, 39)})]),
    case("I02", "악기", "lofi_groove", "Rhodes를 그랜드 피아노 소리로 바꿔줘",
         [Call("set_instrument", {"track_ids": ["t3"], "program": Range(0, 1)})]),
    case("I03", "악기", "lofi_groove", "멜로디를 바이올린으로 바꿔줘",
         [Call("set_instrument", {"track_ids": ["t5"], "program": 40})]),
    case("I04", "악기", "lofi_groove", "패드를 스트링으로 바꾸고 템포 90으로 해줘",
         [Call("set_instrument", {"track_ids": ["t4"], "program": Range(48, 51)}), Call("set_tempo", {"mode": "set", "value": 90.0})]),
    case("I06", "악기", "lofi_groove", "드럼을 808 킷으로 바꿔줘",
         [Call("set_instrument", {"track_ids": ["t1"], "program": 25})]),
    case("I07", "악기", "lofi_groove", "드럼 소리를 일렉트로닉으로 바꿔줘",
         [Call("set_instrument", {"track_ids": ["t1"], "program": 24})]),
    case("I08", "악기", "lofi_groove", "드럼을 좀 더 로파이한 킷으로 바꿔줘",
         [Call("set_instrument", {"track_ids": ["t1"], "program": 27})]),
    case("I09", "악기", "lofi_groove", "재즈 드럼 킷으로 해줘",
         [Call("set_instrument", {"track_ids": ["t1"], "program": 32})]),
    # lofi_groove 드럼에 쓰인 탐: 43 Floor Tom · 45 Low Tom · 48 Hi-Mid Tom · 50 High Tom (스탠다드 킷 = 어쿠스틱 탐)
    case("I10", "악기", "lofi_groove", "탐 소리가 너무 촌스러워",
         [Call("set_drum_sound", {"track_id": "t1", "pitches": Pitches(frozenset({41, 43, 45, 47, 48, 50}), frozenset({43, 45, 48, 50})),
                                  "sound": OneOf(frozenset({"tom_deep", "tom_round", "tom_808", "tom_electro"}))})],
         note="소리 하나가 별로라는 말 → 거절하지 말고 같은 역할의 다른 소리로"),
    case("I11", "악기", "lofi_groove", "킥만 808 킥으로 바꿔줘",
         [Call("set_drum_sound", {"track_id": "t1", "pitches": Pitches(frozenset({35, 36}), frozenset({36})), "sound": "kick_808"})]),
    case("I12", "악기", "lofi_groove", "하이햇을 부드러운 걸로 바꿔줘",
         [Call("set_drum_sound", {"track_id": "t1", "pitches": Pitches(frozenset({42, 44}), frozenset({42})), "sound": "hat_soft"})],
         alt=[(Call("set_drum_sound", {"track_id": "t1", "pitches": Pitches(frozenset({42, 44}), frozenset({42})), "sound": "hat_soft"}),
               Call("set_drum_sound", {"track_id": "t1", "pitches": [46], "sound": "openhat_soft"}))]),
    case("I05", "악기", "lofi_groove", "드럼을 피아노 소리로 바꿔줘", note="드럼 트랙은 악기 번호를 바꿀 수 없음 → 편집하지 않고 알려 줌"),
    case("E01", "음 · 마디", "lofi_groove", "8마디부터 드럼 빼줘",
         [Call("delete_notes", {"track_ids": ["t1"], "bars": [8, 16]})]),
    case("E02", "음 · 마디", "lofi_groove", "하이햇 전부 지워줘",
         [Call("delete_notes", {"track_ids": ["t1"], "pitches": HATS, "bars": None})]),
    case("E03", "음 · 마디", "lofi_groove", "베이스 짧게 끊어줘",
         [Call("set_length", {"track_ids": ["t2"], "mode": "scale", "value": Range(0.3, 0.6)})]),
    case("E04", "음 · 마디", "lofi_groove", "Rhodes 음 사이 빈틈 없이 이어지게 해줘",
         [Call("set_length", {"track_ids": ["t3"], "mode": "legato"})]),
    case("E05", "음 · 마디", "lofi_groove", "1~4마디 드럼을 5~8마디에 복사해줘",
         [Call("copy_bars", {"track_ids": ["t1"], "bars": [1, 4], "to_bar": 5})]),
    case("E06", "음 · 마디", "lofi_groove", "1~2마디를 16마디까지 계속 반복해줘",
         [Call("copy_bars", {"track_ids": ALL, "bars": [1, 2], "to_bar": 3, "times": 7})]),
    case("H01", "연주 느낌", "lofi_groove", "드럼을 사람이 친 것처럼 살짝 흔들어줘",
         [Call("humanize", {"track_ids": ["t1"], "timing": Range(0.005, 0.015, default=0.02), "velocity": Range(3, 8)})]),
    case("H02", "연주 느낌", "lofi_groove", "리드가 너무 기계 같아, 사람이 연주한 느낌으로 해줘",
         [Call("humanize", {"track_ids": ["t5"], "timing": Range(0.005, 0.05, default=0.02)})]),
    case("H03", "연주 느낌", "lofi_groove", "마지막 4마디 점점 작게 해줘",
         [Call("velocity_ramp", {"track_ids": ALL, "bars": [13, 16], "start": Range(0.9, 1.0), "end": Range(0.2, 0.6)})]),
    case("H04", "연주 느낌", "lofi_groove", "처음 4마디 Rhodes 점점 크게",
         [Call("velocity_ramp", {"track_ids": ["t3"], "bars": [1, 4], "start": Range(0.2, 0.7), "end": Range(0.95, 1.3)})]),
    case("X01", "믹스", "lofi_groove", "패드 볼륨 좀 줄여줘",
         [Call("set_mix", {"track_ids": ["t4"], "volume_offset": Range(-20, -8)})],
         alt=[(Call("set_mix", {"track_ids": ["t4"], "volume": Range(75, 92)}),)]),
    case("X02", "믹스", "lofi_groove", "리드를 왼쪽으로 조금 보내줘",
         [Call("set_mix", {"track_ids": ["t5"], "pan": Range(-30, -10)})]),
    case("X03", "믹스", "lofi_groove", "Rhodes는 오른쪽으로 보내고 볼륨은 80으로 해줘",
         [Call("set_mix", {"track_ids": ["t3"], "pan": Range(20, 63), "volume": 80})],
         alt=[(Call("set_mix", {"track_ids": ["t3"], "pan": Range(20, 63)}), Call("set_mix", {"track_ids": ["t3"], "volume": 80}))]),
    case("K01", "트랙", "lofi_groove", "멜로디를 스트링으로 한 옥타브 아래 겹쳐줘",
         [Call("duplicate_track", {"track_id": "t5", "octaves": -1, "program": Range(40, 51)})]),
    case("K02", "트랙", "lofi_groove", "베이스 트랙 하나 더 복사해줘",
         [Call("duplicate_track", {"track_id": "t2", "octaves": Range(0, 0, default=0)})]),
    case("K03", "트랙", "lofi_groove", "Rhodes 코드에 어울리는 탑노트 추가해줘",
         [Call("duplicate_track", {"track_id": "t3", "voice": "top", "octaves": Range(0, 1, default=0)})],
         note="탑노트 = 화음마다 맨 위 음. 코드 전체 복제(voice all)는 틀림"),
    case("K04", "트랙", "lofi_groove", "Rhodes 코드에서 베이스 라인 뽑아줘",
         [Call("duplicate_track", {"track_id": "t3", "voice": "bottom", "octaves": Range(-2, -1)})]),
    case("C06", "되묻기 · 정보", "lofi_groove", "새로운 멜로디 하나 만들어줘", note="새 음 작곡은 아직 못 함 → 흉내 내지 말고 안내"),
    case("C07", "되묻기 · 정보", "lofi_groove", "드럼 패턴 새로 짜줘", note="새 패턴 작곡은 아직 못 함"),
    # 화면에서 고른 부분 + "여기 · 이 부분 · 이거"
    case("G01", "고른 부분", "lofi_groove", "여기 한 옥타브 올려줘",
         [Call("shift_octave", {"track_ids": ["t3"], "octaves": 1, "beats": [16, 32]})],
         alt=[(Call("transpose", {"track_ids": ["t3"], "semitones": 12, "beats": [16, 32]}),),
              (Call("shift_octave", {"track_ids": ["t3"], "octaves": 1, "bars": [5, 8]}),),
              (Call("transpose", {"track_ids": ["t3"], "semitones": 12, "bars": [5, 8]}),)],
         selection={"track_ids": ["t3"], "beats": [16, 32]}),
    case("G02", "고른 부분", "lofi_groove", "이 부분 점점 작게 해줘",
         [Call("velocity_ramp", {"track_ids": ALL, "beats": [32, 48], "start": Range(0.9, 1.0), "end": Range(0.2, 0.6)})],
         alt=[(Call("velocity_ramp", {"track_ids": ALL, "bars": [9, 12], "start": Range(0.9, 1.0), "end": Range(0.2, 0.6)}),)],
         selection={"track_ids": None, "beats": [32, 48]}),
    case("G03", "고른 부분", "lofi_groove", "이거 좀 약하게",
         velocity("t1", SOFTER, SOFTER_OFFSET, pitches=Pitches(frozenset({42}), frozenset({42}))),
         selection={"track_ids": ["t1"], "beats": [0, 64], "pitches": [42]}),
    case("G04", "고른 부분", "fl_style_loose", "여기 박자 정리해줘",
         [Call("quantize", {"track_ids": ["t2"], "beats": [5, 12], "strength": FULL})],
         selection={"track_ids": ["t2"], "beats": [5, 12]}, note="마디 중간(2마디 2박)부터 고른 부분"),
    case("G05", "고른 부분", "lofi_groove", "베이스 2키 올려줘",
         [Call("transpose", {"track_ids": ["t2"], "semitones": 2, "bars": None, "beats": None})],
         selection={"track_ids": ["t3"], "beats": [17, 24]}, note="다른 트랙을 말하면 고른 부분은 무시"),
    case("C01", "되묻기 · 정보", "lofi_groove", "지금 무슨 트랙 있어?", note="정보만 답하고 편집하지 않음"),
    case("C02", "되묻기 · 정보", "lofi_groove", "좀 더 좋게 해줘", note="막연함 → 되묻기"),
    case("C03", "되묻기 · 정보", "lofi_groove", "느낌 있게 바꿔줘", note="막연함 → 되묻기"),
    case("C04", "되묻기 · 정보", "lofi_groove", "드럼 2키 올려줘", note="드럼은 조옮김 대상이 아님 → 바뀐 음 0개"),
    case("C05", "되묻기 · 정보", "lofi_groove", "스트링 트랙 한 옥타브 올려줘", note="없는 트랙 → 편집하지 않고 알려 줌"),
    # ---------- 화성 분석 (묻기만 함: 편집 없이 analyze_harmony 결과로 답) ----------
    # 조성은 "C major"처럼 영어 이름으로만 (사용자가 "C 장조 · 다장조" 표기를 원하지 않음)
    case("A01", "화성 분석", "lofi_groove", "이 곡 무슨 키야?", reads=["analyze_harmony"], reply_lacks=NO_KO_KEY, reply_has=["C major"]),
    case("A02", "화성 분석", "fl_style_loose", "코드 진행 알려줘", reads=["analyze_harmony"], reply_lacks=NO_KO_KEY, reply_has=["Am", "F", "G"],
         note="C G Am F 두 번"),
    case("A03", "화성 분석", "lofi_groove", "9마디부터 12마디까지 코드 뭐야?", reads=["analyze_harmony"], reply_lacks=NO_KO_KEY,
         reply_has=["Dm9", "G13", "Cmaj9", "A7"]),
    case("A04", "화성 분석", "waltz_3_4", "이 곡 화성 분석해줘", reads=["analyze_harmony"], reply_lacks=NO_KO_KEY, reply_has=["G major", "D7", "Em"]),
    case("A05", "화성 분석", "lofi_groove", "여기 코드 뭐야?", reads=["analyze_harmony"], reply_lacks=NO_KO_KEY, reply_has=["A7"],
         selection={"track_ids": None, "beats": [44, 48], "pitches": None}, note="고른 부분 = 12마디 (A7 → Dm9로 가는 V7/ii)"),
    case("A06", "화성 분석", "lofi_groove", "코드 진행을 좀 더 재즈스럽게 바꿔줘",
         note="리하모니는 아직 못 함 → 다른 도구로 흉내 내지 않고 알려 줌"),
]

assert len(CASES) == 76 and len({c.id for c in CASES}) == 76
