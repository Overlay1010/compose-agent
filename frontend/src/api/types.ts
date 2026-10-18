// 백엔드 app/models/project.py 와 같은 모양을 유지한다.

export interface Note {
  pitch: number // MIDI 음 번호 (60 = C4)
  start: number // 시작 박
  duration: number // 길이(박)
  velocity: number
}

export interface Track {
  id: string
  name: string
  program: number
  /** 사용자가 악기를 직접 골랐음 (0이어도 트랙 이름으로 짐작하지 않음) */
  program_set: boolean
  is_drum: boolean
  volume: number // 트랙 볼륨 0~127 (MIDI CC7, 기본 100)
  pan: number // 좌우 -64(왼쪽) ~ 63(오른쪽), 0 가운데
  /** 드럼만: 레인(음 번호)별로 킷 대신 고른 소리 id. 이 앱에만 저장 (MIDI에는 없음) */
  drum_sounds: Record<string, string>
  notes: Note[]
}

export interface Project {
  id: string
  version: number
  name: string
  tempo: number
  time_signature: [number, number]
  tracks: Track[]
  warnings: string[]
}

// 백엔드 app/agent/loop.py · app/api/chat.py

export interface ToolStep {
  name: string
  args: Record<string, unknown>
  ok: boolean
  summary: string // 도구 결과 요약 또는 오류 메시지
  changed_notes: number
  changed_settings: boolean // 템포처럼 음표 말고 곡 설정이 바뀜
}

export interface ChatResponse {
  reply: string
  steps: ToolStep[]
  preview: Project | null // 적용 전 미리보기 (이번 명령까지 쌓인 것)
  base_version: number
  model: string
  llm_calls: number
  input_tokens: number
  output_tokens: number
}

// 백엔드 app/api/projects.py VersionOut
export interface VersionInfo {
  version: number
  label: string // 무엇을 바꿨는지 한 줄
  current: boolean
  created_at: string // ISO 시각 (예전 기록은 빈 문자열)
}

// 백엔드 app/api/chat.py SessionOut · app/agent/session.py 화면 기록

export interface LogEntry {
  role: 'user' | 'agent' | 'note'
  text: string
  steps?: ToolStep[]
  meta?: string
  made_preview?: boolean
}

export interface SessionData {
  project: Project
  preview: Project | null
  base_version: number | null
  log: LogEntry[]
}

// 백엔드 app/api/projects.py RecentOut
export interface RecentProject {
  id: string
  name: string
  version: number
  updated_at: string // ISO 시각, 메모리 저장소면 빈 문자열
}
