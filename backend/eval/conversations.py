"""이어지는 대화 · 스스로 고치기 평가.

한 명령만 보는 cases.py와 달리 여러 턴을 실제 서버와 같은 흐름(app/agent/session.py)으로 돌리고,
**마지막 상태**가 정답과 같은지 본다. 정답으로 가는 길이 여러 개라서(예: "아니 내려줘" = −2옥타브 한 번,
또는 −1을 두 번) 도구 호출이 아니라 결과로 채점한다.

정답은 실제로 실행할 도구 호출 목록이고, 어디에 적용할지를 base로 정한다.
- "original": 처음 올린 곡에 적용한 결과와 같아야 한다 ("방금 거 반대로" → 원래대로)
- "before_last": 마지막 명령 직전 상태에 적용한 결과와 같아야 한다 (앞 턴의 세기처럼 정답이 범위인 경우)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

APPLY, CANCEL = "<적용>", "<취소>"


@dataclass(frozen=True)
class Conversation:
    id: str
    category: str
    sample: str
    turns: tuple[str, ...]  # 사용자 명령, 또는 APPLY · CANCEL (화면에서 누르는 버튼)
    expect: tuple[tuple[str, dict], ...] = ()  # (도구, 인자) — 비우면 "바뀌면 안 됨"
    base: Literal["original", "before_last"] = "original"
    note: str = ""
    command: str = field(default="", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", " → ".join(self.turns))


CONVERSATIONS: list[Conversation] = [
    # ---------- 이어지는 대화 ----------
    Conversation("D01", "이어지는 대화", "lofi_groove", ("베이스 2키 올려줘", APPLY, "한 키 더 올려줘"),
                 (("transpose", {"track_ids": ["t2"], "semitones": 3}),), note="적용한 뒤 이어서 +1 → 처음보다 +3"),
    Conversation("D02", "이어지는 대화", "lofi_groove", ("베이스 2키 올려줘", "멜로디도 똑같이"),
                 (("transpose", {"track_ids": ["t2"], "semitones": 2}), ("transpose", {"track_ids": ["t5"], "semitones": 2})),
                 note="미리보기에 이어서 쌓임"),
    Conversation("D03", "이어지는 대화", "lofi_groove", ("9마디부터 패드 약하게", APPLY, "그 부분 패드 한 옥타브 올려줘"),
                 (("shift_octave", {"track_ids": ["t4"], "octaves": 1, "bars": [9, 16]}),), base="before_last",
                 note="'그 부분' = 앞에서 말한 9마디부터"),
    Conversation("D04", "이어지는 대화", "lofi_groove", ("리드 7키 내려", APPLY, "방금 거 반대로"), (),
                 note="+7 해서 처음과 같아져야 함"),
    Conversation("D05", "이어지는 대화", "lofi_groove", ("하이햇 좀 약하게", CANCEL, "그럼 스네어를 20만큼 세게"),
                 (("adjust_velocity", {"track_ids": ["t1"], "pitches": [38], "mode": "offset", "value": 20}),),
                 note="취소한 하이햇은 다시 건드리지 않음"),
    Conversation("D06", "이어지는 대화", "lofi_groove", ("패드 한 옥타브 올려줘", "아니 내려줘"),
                 (("shift_octave", {"track_ids": ["t4"], "octaves": -1}),),
                 note="미리보기(+1) 위에서 −2를 해야 처음보다 −1"),
    # ---------- 스스로 고치기 (도구 오류가 나게 만든 명령) ----------
    Conversation("R01", "스스로 고치기", "lofi_groove", ("베이스 30반음 올려줘",),
                 (("transpose", {"track_ids": ["t2"], "semitones": 24}), ("transpose", {"track_ids": ["t2"], "semitones": 6})),
                 note="한 번에 최대 24반음 → 나눠서 올려야 함"),
    Conversation("R02", "스스로 고치기", "lofi_groove", ("리드를 4옥타브 올려줘",), (),
                 note="MIDI 범위(127)를 넘어 불가능 → 편집하지 않고 설명"),
    Conversation("R03", "스스로 고치기", "lofi_groove", ("20마디부터 베이스 약하게",), (),
                 note="곡은 16마디 → 바뀐 게 없다고 알려 줌"),
]

assert len({c.id for c in CONVERSATIONS}) == len(CONVERSATIONS)
