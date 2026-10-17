import type { Note, Project, Track } from './api/types'
import { gmProgramOf } from './audio/instruments'

export interface NoteDiff {
  same: Note[] // 그대로인 음
  removed: Note[] // 원래 위치 (미리보기에서 바뀌어 사라진 음)
  added: Note[] // 바뀐 뒤의 음
}

const key = (n: Note) => `${n.pitch}|${n.start}|${n.duration}|${n.velocity}`

/**
 * 같은 음끼리 먼저 짝지어 "그대로"로 빼고, 남는 것을 원래 위치 / 바뀐 음으로 나눈다.
 * 순서로 맞추면 스윙처럼 음 순서가 바뀌는 편집에서 엉뚱한 음이 바뀐 것처럼 보여서 이렇게 한다.
 */
export function diffNotes(before: Note[], after: Note[]): NoteDiff {
  const left = new Map<string, Note[]>()
  for (const n of before) {
    const k = key(n)
    left.set(k, [...(left.get(k) ?? []), n])
  }
  const same: Note[] = []
  const added: Note[] = []
  for (const n of after) {
    const bucket = left.get(key(n))
    if (bucket?.length) {
      same.push(bucket.pop()!)
    } else {
      added.push(n)
    }
  }
  const removed = [...left.values()].flat()
  return { same, removed, added }
}

/** 미리보기에서 음이 하나라도 바뀌었거나 악기 · 볼륨 · 팬이 바뀐 트랙 id */
export function changedTrackIds(project: Project, preview: Project | null): Set<string> {
  const ids = new Set<string>()
  if (!preview) return ids
  for (const t of preview.tracks) {
    const original = project.tracks.find((o) => o.id === t.id)
    if (!original || !sameNotes(original, t) || gmProgramOf(original) !== gmProgramOf(t) || !sameMix(original, t)) ids.add(t.id)
  }
  return ids
}

/** 미리보기로 바뀐 음이 걸친 마디 범위(박, 마디 경계로 맞춤). 바뀐 음이 없으면 null */
export function changedRange(project: Project, preview: Project | null): { start: number; end: number } | null {
  if (!preview) return null
  const bpb = (project.time_signature[0] * 4) / project.time_signature[1]
  const notes: Note[] = []
  for (const t of preview.tracks) {
    const original = project.tracks.find((o) => o.id === t.id)
    if (!original) notes.push(...t.notes)
    else {
      const d = diffNotes(original.notes, t.notes)
      notes.push(...d.added, ...d.removed)
    }
  }
  if (!notes.length) return null
  const start = Math.floor(Math.min(...notes.map((n) => n.start)) / bpb) * bpb
  const end = Math.ceil(Math.max(...notes.map((n) => n.start + n.duration)) / bpb) * bpb
  return { start, end: Math.max(end, start + bpb) }
}

export const sameMix = (a: Track, b: Track) => a.volume === b.volume && a.pan === b.pan

/** 화면용 팬 표시: 가운데 · 왼쪽 20 · 오른쪽 40 */
export const panLabel = (pan: number) => (pan === 0 ? '가운데' : `${pan < 0 ? '왼쪽' : '오른쪽'} ${Math.abs(pan)}`)

function sameNotes(a: Track, b: Track): boolean {
  if (a.notes.length !== b.notes.length) return false
  const d = diffNotes(a.notes, b.notes)
  return d.added.length === 0 && d.removed.length === 0
}
