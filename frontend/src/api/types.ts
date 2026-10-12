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
