import type { Project } from './api/types'
import { DRUM_NAMES } from './audio/instruments'

/**
 * 화면에서 고른 부분 (피아노롤 · 전체 구성에서 드래그). 채팅 메시지와 함께 보내 "여기 한 옥타브 올려줘"를 그 부분에만 적용한다.
 * 멜로디 트랙은 시간 구간만 고른다 (음높이는 안 고름) — "올려줘 → 아니 내려줘"처럼 이어 말해도 같은 부분을 가리키게.
 * 드럼은 레인(소리)이 곧 악기라서 고른 레인도 함께 보낸다.
 */
export interface Selection {
  trackIds: string[] | null // null = 모든 트랙
  beats: [number, number] // [시작, 끝) 박
  pitches: number[] | null // 드럼 레인만
}

const bpbOf = (p: Project) => (p.time_signature[0] * 4) / p.time_signature[1]

function beatText(beat: number, bpb: number): string {
  const bar = Math.floor(beat / bpb + 1e-9) + 1
  const rest = beat - (bar - 1) * bpb
  return rest < 1e-6 ? `${bar}마디` : `${bar}마디 ${+(rest + 1).toFixed(2)}박`
}

/** "5~6마디", "5마디 2박 ~ 6마디 끝" (백엔드 app/agent/prompt.py selection_text와 같은 읽기) */
export function rangeText(project: Project, [start, end]: [number, number]): string {
  const bpb = bpbOf(project)
  const aligned = (b: number) => Math.abs(b / bpb - Math.round(b / bpb)) < 1e-6
  if (aligned(start) && aligned(end)) {
    const a = Math.round(start / bpb) + 1
    const b = Math.round(end / bpb)
    return a === b ? `${a}마디` : `${a}~${b}마디`
  }
  const endText = aligned(end) ? `${Math.round(end / bpb)}마디 끝` : `${beatText(end, bpb)} 전`
  return `${beatText(start, bpb)} ~ ${endText}`
}

/** 화면 · 채팅에 보일 설명: "Rhodes · 5~6마디", "Drums Closed Hat · 1~4마디", "모든 트랙 · 9~12마디" */
export function selectionLabel(project: Project, sel: Selection): string {
  const names = sel.trackIds ? sel.trackIds.map((id) => project.tracks.find((t) => t.id === id)?.name ?? id).join(', ') : '모든 트랙'
  const sounds = sel.pitches?.length ? ` ${sel.pitches.map((p) => DRUM_NAMES[p] ?? p).join('·')}` : ''
  return `${names}${sounds} · ${rangeText(project, sel.beats)}`
}
