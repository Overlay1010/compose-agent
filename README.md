# Compose Agent

말로 작곡 작업을 시키는 웹 서비스. LLM 에이전트가 MIDI 편집, 샘플 검색, 허밍 변환, 가사 맞추기 같은 도구를 골라 실행한다.

> 현재 단계: **v0.1 진행 중** — MIDI 업로드 · 트랙 보기 · 재생 · 내보내기 · 편집 도구 · LLM 에이전트 · 채팅 화면(미리보기 → 적용 · 되돌리기)까지 완료. 다음은 평가와 화면 다듬기. 배포는 개발을 다 마친 뒤(v1.0)에 한다.

## 구조

```
compose-agent/
├── backend/            FastAPI
│   ├── app/
│   │   ├── main.py         앱, 오류 형식 통일
│   │   ├── api/            REST 엔드포인트
│   │   ├── models/         Project · Track · Note (시간 단위 = 박)
│   │   ├── midi_io/        MIDI 파일 <-> Project 변환
│   │   ├── store/          버전 저장소 (메모리)
│   │   ├── tools/          편집 도구 6개 (Project -> 새 Project 순수 함수, 인자 검증 · JSON Schema)
│   │   └── agent/          LLM 에이전트: 도구 호출 루프 · 시스템 프롬프트 · LLM 연결(OpenAI 호환)
│   └── tests/
├── frontend/           React + TypeScript + Vite
│   └── src/
│       ├── api/            백엔드 호출, 타입
│       ├── audio/          Tone.js 재생 (악기 소리 · Transport 예약)
│       ├── store/          상태 (zustand)
│       └── components/     TopBar · TrackList · PianoRoll
├── samples/            테스트용 MIDI (scripts/make_samples.py로 생성)
├── scripts/            샘플 생성 등 개발용 스크립트
└── docs/               설계 문서, 개발 기록
```

## 실행 방법 (Windows)

필요한 것: Python 3.11 이상, Node.js 20 이상

선택: [ffmpeg](https://ffmpeg.org/download.html) — PATH에 있으면 음원을 MP3 · FLAC · OGG · M4A · MP4로도 내보낸다. 없으면 WAV만 (WAV는 브라우저에서 바로 만든다).

**1. 백엔드** (터미널 1)

```powershell
cd backend
python -m venv compose_venv
compose_venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env    # 그다음 .env에 OPENAI_API_KEY 넣기
uvicorn app.main:app --reload --port 8100
```

에이전트(채팅)를 쓰려면 `backend/.env`에 `OPENAI_API_KEY`가 있어야 한다. 모델은 `OPENAI_MODEL`로 바꾸고, Ollama 같은 OpenAI 호환 서버는 `OPENAI_BASE_URL`로 붙인다. 키가 없어도 나머지 기능은 동작하고, 채팅만 503 `llm_unavailable`을 돌려준다.

`http://localhost:8100/docs` 에서 API 문서를 볼 수 있다.

**2. 프론트엔드** (터미널 2)

```powershell
cd frontend
npm install
npm run dev
```

`http://localhost:5173` 을 열고 **MIDI 열기**로 파일을 올린다. 처음에는 `samples/lofi_groove.mid`로 확인해 보면 된다.
**재생** 버튼이나 스페이스바로 들어 볼 수 있고, 트랙 옆 **M** 버튼으로 음소거한다.

> 5173 포트를 다른 프로젝트가 쓰고 있으면 Vite가 5174 같은 다음 포트로 띄운다. 터미널에 나온 주소를 열면 된다.

**테스트**

```powershell
cd backend
pytest
```

## 샘플 MIDI

`samples/`의 파일은 전부 코드로 만든 것이라 저작권 걱정 없이 시연·테스트에 쓸 수 있다.

| 파일 | 내용 | 확인할 것 |
| --- | --- | --- |
| `lofi_groove.mid` | 84 BPM, 16마디, 트랙 5개 (드럼 · 베이스 · Rhodes · 패드 · 멜로디) | 메인 데모. 탐 필인·크래시·오픈 하이햇까지 들어 있음 |
| `fl_style_loose.mid` | 120 BPM, 8마디. 드럼 이름이 `FPC`이고 10번 채널이 아님, 악기 번호 전부 0, 타이밍·세기가 흔들림 | FL Studio식 드럼 인식, 나중에 퀀타이즈·세기 조절 도구 |
| `waltz_3_4.mid` | 150 BPM, 3/4 박자, 8마디 | 마디선·재생선이 3박마다 맞는지 |
| `tempo_change.mid` | 5마디부터 100 → 130 BPM | 경고 문구, 박 위치 유지 |
| `demo.mid` | 4마디, 트랙 3개 | 처음 만든 최소 샘플 |

다시 만들기 (같은 파일이 나온다):

```powershell
backend\compose_venv\Scripts\python scripts\make_samples.py
```

## DAW에서 MIDI 내보내기

| DAW | 내보내기 |
| --- | --- |
| FL Studio | **File → Export → MIDI file…** |
| Logic Pro | 트랙(리전)을 고르고 **File → Export → Selection as MIDI File…** |
| Cubase | **File → Export → MIDI File…** |
| Ableton Live | MIDI 클립 우클릭 → **Export MIDI Clip…** (트랙마다 하나씩, 여러 개 올리려면 앱에서 합치기 예정) |

트랙마다 이름을 붙여 두면 앱에서도 그 이름으로 보인다.

드럼은 세 가지로 찾는다 (`backend/app/midi_io/convert.py`):

1. **10번 채널**: Cubase · Logic의 GM 드럼은 대부분 여기서 잡힌다
2. **트랙 이름**: FL Studio `FPC`, Ableton `Drum Rack` · `Kit-Core 909`, Cubase `Groove Agent SE`, `Drum` · `Kick` · `Hat` 같은 단어
3. **음 패턴**: Logic Drummer처럼 트랙 이름이 드러머 이름(`SoCal (Kyle)`)이어도, GM 드럼 번호(27~59)에 짧은 음이 몰려 있고 킥 · 스네어 · 하이햇이 같이 치면 드럼으로 본다. 샘플팩 멜로디 루프 37개에서 잘못 잡힌 것 0개

v0.1의 제한: 템포·박자 변화가 있으면 첫 값만 사용한다 (화면에 안내가 뜬다).

## API (v0.1)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/v1/health` | 상태 확인 |
| POST | `/api/v1/projects` | MIDI 업로드 → Project |
| GET | `/api/v1/projects/{id}` | 현재 버전 |
| GET | `/api/v1/projects/{id}/summary` | 트랙 요약 (에이전트용) |
| GET | `/api/v1/projects/{id}/export` | `.mid` 다운로드 |
| POST | `/api/v1/projects/{id}/chat` | 말로 편집 → 미리보기 (`{"message": "베이스 2키 올려줘"}`). 적용 전까지 명령이 미리보기에 쌓인다 |
| POST | `/api/v1/projects/{id}/preview/apply` | 미리보기를 새 버전으로 저장 |
| POST | `/api/v1/projects/{id}/preview/cancel` | 미리보기 버리기 |
| GET | `/api/v1/projects/{id}/versions` | 버전 기록 (무엇을 바꿨는지 한 줄씩) |
| POST | `/api/v1/projects/{id}/versions/{n}/restore` | 예전 버전을 새 버전으로 되살리기 |
| POST | `/api/v1/projects/{id}/undo` | 바로 전 버전으로 (지우지 않고 새 버전으로 남김) |

오류는 `{"error": {"code": "...", "message": "..."}}` 형식으로 돌려준다.

## 다음 할 일

전체 계획(화성 분석 · 말로 만들기 · 멜로디에 편곡 깔기 · 허밍 · 샘플 · 가사 → v1.0)은 [docs/roadmap.md](docs/roadmap.md)에 있다.


- [x] 레포 생성, FastAPI·React 기본 세팅
- [x] MIDI 업로드 → 내부 데이터 형식으로 변환
- [x] 트랙별 피아노롤 화면
- [x] Tone.js 재생 (재생선 · 트랙 음소거 · 스페이스바) — 편집 결과를 귀로 확인하려고 앞당김
- [x] 편집 도구 6개를 순수 함수로 구현하고 단위 테스트 작성 (조옮김 · 옥타브 · 퀀타이즈 · 세기 · 스윙 · 프로젝트 정보)
- [x] LLM 에이전트 (`POST /chat`): 도구를 여러 번 부르고, 오류를 보고 스스로 고침. 결과는 미리보기로만
- [x] 미리보기·적용·취소·되돌리기 API (버전 기록 포함)
- [x] 채팅 화면 · 미리보기(바뀔 음 표시) · 바뀐 소리/원래 소리 비교 · 적용 · 취소 · 되돌리기 · 버전 기록 화면 → **MVP 흐름 완성**
- [ ] 화면 다듬기 (목업의 어두운 테마 · 라임 · 레벨 미터 · 전체 구성) · 홈 화면
- [x] 재생 소리를 실제 악기 샘플로 교체 (멜로디 FluidR3 GM · 드럼 Sonic Pi, 못 불러오면 신스로 대체)
- [x] 정답 있는 명령 30개로 첫 평가 · 모델 비교 ([docs/eval.md](docs/eval.md))
- [ ] 평가를 모델마다 3회 이상 돌려 평균 · 범위로 보고

## 소리 출처

| 쓰는 곳 | 샘플 | 라이선스 |
| --- | --- | --- |
| 멜로디 악기 (General MIDI 128개) | [FluidR3 GM](https://github.com/gleitz/midi-js-soundfonts) by Frank Wen, 재생할 때 gleitz.github.io에서 불러옴 | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| 드럼 | [Sonic Pi](https://github.com/sonic-pi-net/sonic-pi/tree/dev/etc/samples) 드럼 샘플 (원본 freesound.org), `frontend/public/samples/drums/`에 포함 | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

샘플을 못 불러오면(오프라인 등) 해당 트랙만 Tone.js 신스 소리로 재생하고 화면에 알려 준다.
