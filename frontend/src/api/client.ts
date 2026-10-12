import type { Project } from './types'

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

export function exportUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/export`
}
