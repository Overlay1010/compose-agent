import type { ChatResponse, Project, RecentProject, SessionData, ToolStep, VersionInfo } from './types'

const BASE = '/api/v1'

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>
  let code = 'http_error'
  let message = `서버 오류 (${res.status})`
  try {
    const body = await res.json()
    code = body.error?.code ?? code
    message = body.error?.message ?? message
  } catch {
    // 서버가 꺼져 있으면 JSON이 아닌 응답이 온다
    if (res.status === 500 || res.status === 502 || res.status === 504) {
      message = '백엔드 서버에 연결할 수 없습니다. uvicorn이 실행 중인지 확인해 주세요.'
    }
  }
  throw new ApiError(code, message)
}

export async function uploadMidi(file: File): Promise<Project> {
  const form = new FormData()
  form.append('file', file)
  return parse<Project>(await fetch(`${BASE}/projects`, { method: 'POST', body: form }))
}

export type StreamEvent =
  | { kind: 'thinking'; round: number }
  | { kind: 'tool_start'; name: string; args: Record<string, unknown> }
  | { kind: 'tool_done'; step: ToolStep }

/**
 * /chat/stream: 에이전트 진행 상황(Server-Sent Events)을 onEvent로 넘기고, 끝나면 ChatResponse를 돌려준다.
 * 스트림 도중 오류는 event: error로 오고, 시작 전 오류(503 등)는 일반 HTTP 오류로 온다.
 */
export async function chatStream(
  projectId: string,
  message: string,
  onEvent: (e: StreamEvent) => void,
): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/projects/${projectId}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
  if (!res.ok || !res.body) return parse<ChatResponse>(res)

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      const kind = /^event: (.*)$/m.exec(block)?.[1]
      const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? 'null')
      if (kind === 'done') return data as ChatResponse
      if (kind === 'error') throw new ApiError(data.code, data.message)
      if (kind === 'thinking') onEvent({ kind, round: data.round })
      if (kind === 'tool_start') onEvent({ kind, name: data.name, args: data.args })
      if (kind === 'tool_done') onEvent({ kind, step: data as ToolStep })
    }
  }
  throw new ApiError('stream_closed', '서버 연결이 중간에 끊겼어요. 다시 보내 주세요.')
}

export async function chat(projectId: string, message: string): Promise<ChatResponse> {
  return parse<ChatResponse>(
    await fetch(`${BASE}/projects/${projectId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    }),
  )
}

const post = (path: string) => fetch(`${BASE}${path}`, { method: 'POST' })

export async function applyPreview(projectId: string): Promise<Project> {
  return parse<Project>(await post(`/projects/${projectId}/preview/apply`))
}

export async function cancelPreview(projectId: string): Promise<void> {
  const res = await post(`/projects/${projectId}/preview/cancel`)
  if (!res.ok) await parse(res)
}

export async function listVersions(projectId: string): Promise<VersionInfo[]> {
  return parse<VersionInfo[]>(await fetch(`${BASE}/projects/${projectId}/versions`))
}

export async function restoreVersion(projectId: string, version: number): Promise<Project> {
  return parse<Project>(await post(`/projects/${projectId}/versions/${version}/restore`))
}

/** 트랙 설정 바꾸기 결과. note는 대화에 남길 한 줄 (서버 기록과 같은 문장) */
export interface TrackChange {
  project: Project
  preview: Project | null
  note: string | null
}

/** 화면에서 악기를 바꾼다. 바로 새 버전이 되고, 미리보기가 있으면 미리보기에도 들어간다. */
export async function setInstrument(
  projectId: string,
  trackId: string,
  program: number,
): Promise<TrackChange> {
  return parse(
    await fetch(`${BASE}/projects/${projectId}/tracks/${trackId}/instrument`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ program }),
    }),
  )
}

/** 화면에서 트랙 볼륨 · 팬을 바꾼다. 악기 바꾸기와 같이 바로 새 버전이 된다. */
export async function setMix(
  projectId: string,
  trackId: string,
  mix: { volume?: number; pan?: number },
): Promise<TrackChange> {
  return parse(
    await fetch(`${BASE}/projects/${projectId}/tracks/${trackId}/mix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mix),
    }),
  )
}

/** 벨로시티 편집창: 음 순서(index)로 세기를 직접 바꾼다. baseVersion이 지금 버전과 다르면 409 */
export async function setVelocities(
  projectId: string,
  trackId: string,
  baseVersion: number,
  changes: { index: number; velocity: number }[],
): Promise<TrackChange> {
  return parse(
    await fetch(`${BASE}/projects/${projectId}/tracks/${trackId}/velocities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_version: baseVersion, changes }),
    }),
  )
}

/** 드럼 레인 하나의 소리 고르기 (sound = 소리 id 또는 "default") */
export async function setDrumSound(projectId: string, trackId: string, pitch: number, sound: string): Promise<TrackChange> {
  return parse(
    await fetch(`${BASE}/projects/${projectId}/tracks/${trackId}/drum-sound`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pitch, sound }),
    }),
  )
}

/** 드럼 소리(레인)별 크기: 그 소리 음들의 세기에 scale을 곱한다 (MIDI에 그대로 남음) */
export async function setLane(projectId: string, trackId: string, pitch: number, scale: number): Promise<TrackChange> {
  return parse(
    await fetch(`${BASE}/projects/${projectId}/tracks/${trackId}/lane`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pitch, scale }),
    }),
  )
}

export async function undo(projectId: string): Promise<Project> {
  return parse<Project>(await post(`/projects/${projectId}/undo`))
}

/** 저장된 프로젝트 다시 열기: 현재 버전 · 미리보기 · 대화 기록 */
export async function getSession(projectId: string): Promise<SessionData> {
  return parse<SessionData>(await fetch(`${BASE}/projects/${projectId}/session`))
}

/** 최근 프로젝트 (처음 화면의 이어서 하기) */
export async function recentProjects(): Promise<RecentProject[]> {
  return parse<RecentProject[]>(await fetch(`${BASE}/projects`))
}

export function exportUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/export`
}
