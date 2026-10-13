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
  is_drum: boolean
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
