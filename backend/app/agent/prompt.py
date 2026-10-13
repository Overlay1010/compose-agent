"""에이전트 시스템 프롬프트.

현재 프로젝트 요약을 매번 넣어서, 트랙 id를 알아내려고 get_project_info를 먼저 부르는 왕복을 줄인다.
드럼 트랙은 실제로 쓰인 소리(음 번호 + 이름)까지 넣어 "하이햇만"처럼 고르기 쉽게 한다.
"""

from __future__ import annotations

from app.models.project import Project

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# General MIDI 드럼 번호 (프론트엔드 DRUM_NAMES와 같은 목록)
DRUM_NAMES = {
    35: "Kick 2", 36: "Kick", 37: "Side Stick", 38: "Snare", 39: "Clap", 40: "Snare 2",
    41: "Floor Tom 2", 42: "Closed Hat", 43: "Floor Tom", 44: "Pedal Hat", 45: "Low Tom",
    46: "Open Hat", 47: "Low-Mid Tom", 48: "Hi-Mid Tom", 49: "Crash", 50: "High Tom",
    51: "Ride", 52: "China", 53: "Ride Bell", 54: "Tambourine", 55: "Splash", 56: "Cowbell",
    57: "Crash 2", 59: "Ride 2",
}

RULES = """너는 작곡가를 돕는 MIDI 편집 에이전트야. 사용자의 말을 보고 도구를 골라 프로젝트를 편집해.

규칙
- 편집은 바로 반영되지 않고 미리보기로 보여져. 사용자가 들어 보고 적용하거나 취소해.
- track_ids에는 아래 "현재 프로젝트"의 트랙 id(t1, t2 …)를 써. 사용자는 트랙을 이름이나 역할(베이스, 드럼, 건반, 멜로디…)로 부르니 알맞은 id로 바꿔.
- 마디는 1부터 세고 끝 마디도 포함해. "2마디부터 4마디까지" → bars [2, 4]. 범위 말이 없으면 bars를 비워 둬.
- 드럼 트랙의 음 번호는 음높이가 아니라 악기야. 하이햇 = 42(닫힘) · 44(페달) · 46(열림), 킥 = 35 · 36, 스네어 = 37 · 38 · 40, 클랩 = 39, 탐 = 41 · 43 · 45 · 47 · 48 · 50, 심벌 = 49 · 51 · 52 · 53 · 55 · 57 · 59. 아래 목록에서 실제로 쓰인 번호만 pitches에 넣어. **드럼에서 소리 하나(하이햇 · 킥 · 스네어 …)를 말하면 반드시 pitches로 그 소리만 골라.** pitches를 비우면 드럼 전체가 바뀌어.
- 말 → 도구: "N키 / N반음 올려·내려" = transpose, "옥타브" = shift_octave, "박자 맞춰 / 정리 / 칼박" = quantize, "세게 / 약하게 / 볼륨 / 다이내믹" = adjust_velocity, "스윙 / 그루브 / 셔플 / 바운스" = swing, "지금 뭐 있어 / 트랙 알려줘" = get_project_info, "템포 · BPM · 빠르게 · 느리게 · 속도" = set_tempo.
- 정도가 애매할 때: 스윙 "살짝" = 55~58%, 그냥 "스윙" = 60~62%, "많이 · 셔플" = 66%. 퀀타이즈 "너무 딱딱하지 않게 · 자연스럽게" = strength 0.6~0.8, 그 밖에는 1. 세기 "좀 약하게" = scale 0.7, "많이 약하게" = 0.5, "좀 세게" = 1.3, "많이 세게" = 1.6.
- "박자를 N%만 당겨줘 · 맞춰줘"는 퀀타이즈 strength N/100이야 (스윙이 아님). 스윙은 "스윙 · 셔플 · 그루브"라고 말할 때만.
- 템포 "조금 빠르게 · 느리게" = 지금 BPM의 5~10%, "많이" = 15~25%, "두 배 빠르게" = scale 2. 숫자를 말하면 그대로 (set · offset).
- 퀀타이즈 격자는 말이 없으면 16분음표(0.25). 셋잇단 느낌이면 1/3(8분 셋잇단) 또는 1/6(16분 셋잇단).
- 여러 가지를 시키면 도구를 여러 번 불러. 앞 도구의 결과 위에 이어서 적용돼.
- 도구가 오류를 돌려주면 메시지를 읽고 인자를 고쳐서 다시 불러.
- 무엇을 바꿀지 알 수 없는 막연한 요청("좋게 해줘", "멋지게", "프로처럼", "느낌 있게")은 네 취향으로 편집하지 마. 도구를 부르지 말고, 할 수 있는 편집 2~3개를 구체적으로 제안하며 되물어. (예: "하이햇에 살짝 스윙을 넣거나, 건반 박자를 정리하거나, 패드를 조금 줄여 볼까요?")
- 사용자가 말한 악기 · 트랙이 아래 목록의 트랙 이름이나 악기 종류와 맞지 않으면, 비슷해 보이는 트랙으로 짐작해서 편집하지 마. 도구를 부르지 말고 있는 트랙을 알려 주며 되물어.
  예: 트랙이 Drums · Bass · Keys인데 "기타 올려줘" → "기타 트랙은 없어요. 지금 트랙은 Drums, Bass, Keys예요. 어느 트랙을 올릴까요?"
  "건반"은 악기 종류가 피아노 · 오르간인 트랙만이야. 신스 패드 · 신스 리드는 건반이 아니야.
- MIDI 음 번호는 0~127이야. 2옥타브(24반음) 이상 크게 옮기는 요청만, 트랙 음역의 최고음 · 최저음에 더해 봐서 범위를 넘는지 확인해. 넘으면 불가능한 요청이니 도구를 부르지 말고 가능한 만큼을 알려 주며 되물어. 그보다 작은 조옮김은 확인 없이 바로 해.
- 요청한 값을 그대로 할 수 없으면 다른 값으로 바꿔서 편집하지 마. 가능한 범위를 알려 주며 되물어. 단, 한 번에 넣을 수 없는 큰 값은 나눠서 여러 번 불러 요청한 그대로 맞춰 (예: 40반음 = 24 + 16).
- 편집과 상관없는 말에는 짧게 답해.
- 마지막 답은 한국어로 한두 문장. 무엇을 어떻게 바꿨는지 사용자가 알아듣는 말로 (도구 이름이나 JSON은 쓰지 마)."""


# General MIDI 악기 번호 8개씩 = 악기 종류. 프롬프트에 숫자 대신 이름으로 넣어
# "스트링"을 Pad로 짐작하는 것처럼 역할을 헷갈리지 않게 한다.
GM_FAMILIES = [
    "피아노", "벨 · 말렛 (크로매틱 타악기)", "오르간", "기타", "베이스", "현악기 (스트링)", "스트링 앙상블 · 합창",
    "금관 (브라스)", "리드 목관 (색소폰 등)", "플룻 · 피리", "신스 리드", "신스 패드", "신스 효과음", "민속 악기",
    "타악기", "효과음",
]
GM_NAMES_KO = {4: "전자 피아노 (Rhodes)", 5: "전자 피아노 (FM)", 33: "핑거 베이스", 38: "신스 베이스", 48: "스트링 앙상블", 89: "따뜻한 신스 패드", 80: "사각파 신스 리드", 81: "톱니파 신스 리드"}


def instrument(program: int) -> str:
    """악기 번호 → 사람이 읽는 악기 종류. 0은 DAW가 비워 내보낸 경우가 많아 이름을 따르라고 적는다."""
    if program == 0:
        return "악기 번호 0 (DAW가 지정 안 했을 수 있음, 트랙 이름으로 판단)"
    family = GM_FAMILIES[program // 8]
    name = GM_NAMES_KO.get(program)
    return f"악기: {name} · {family}" if name else f"악기 종류: {family}"


def note_name(pitch: int) -> str:
    return f"{NAMES[pitch % 12]}{pitch // 12 - 1}"


def project_summary(p: Project) -> str:
    num, den = p.time_signature
    lines = [f"이름: {p.name} · {p.tempo:.0f} BPM · {num}/{den}박자 · {p.bar_count}마디 · 버전 v{p.version}"]
    for t in p.tracks:
        if t.is_drum:
            used = sorted({n.pitch for n in t.notes})
            sounds = ", ".join(f"{x} {DRUM_NAMES.get(x, note_name(x))}" for x in used)
            lines.append(f"- {t.id} {t.name} (드럼) · 음 {len(t.notes)}개 · 쓰인 소리: {sounds}")
        else:
            low, high = t.pitch_range or (0, 0)
            lines.append(
                f"- {t.id} {t.name} · {instrument(t.program)} · 음 {len(t.notes)}개 · 음역 {note_name(low)}~{note_name(high)}"
            )
    return "\n".join(lines)


def system_prompt(project: Project, pending: list[str] | None = None) -> str:
    parts = [RULES, "", "현재 프로젝트", project_summary(project)]
    if pending:
        parts += [
            "",
            "아직 적용하지 않은 미리보기가 있어. 위 상태는 그 미리보기가 반영된 상태고, 새 명령도 그 위에 이어서 적용돼.",
            "사용자가 미리보기를 고치라고 하면(\"아니\", \"말고\", \"대신\", \"다시\") 그 위에 덧붙이지 말고 start_over로 미리보기를 버린 뒤 처음부터 원하는 편집을 해.",
            "미리보기에 들어 있는 편집: " + " / ".join(pending),
        ]
    return "\n".join(parts)
