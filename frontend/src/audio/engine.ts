import type { Project } from '../api/types'

// 재생기(audio/player.ts)를 처음 재생할 때 불러오는 연결부.
// player.ts는 Tone.js(소리 라이브러리)를 쓰는데 크기가 커서, 첫 화면에서는 불러오지 않는다.
// 불러오기 전에는 위치 · 볼륨 같은 즉시 함수가 아무 일도 하지 않는다 (재생 중인 소리가 없으니 맞는 동작).

type Player = typeof import('./player')

let mod: Player | null = null
let loading: Promise<Player> | null = null
let onEnd: (() => void) | null = null
let loop: { start: number; end: number } | null = null

async function load(): Promise<Player> {
  loading ??= import('./player').then((m) => {
    mod = m
    if (onEnd) m.setOnEnd(onEnd)
    m.setLoop(loop)
    return m
  })
  return loading
}

export async function play(project: Project, muted: Record<string, boolean>, fromBeats = 0): Promise<string[]> {
  return (await load()).play(project, muted, fromBeats)
}

export const stop = () => mod?.stop()
export const positionBeats = () => mod?.positionBeats() ?? 0
export const setMuted = (trackId: string, muted: boolean) => mod?.setMuted(trackId, muted)
export const setMix = (trackId: string, volume: number, pan: number) => mod?.setMix(trackId, volume, pan)
export const setLaneGain = (trackId: string, pitch: number, gain: number) => mod?.setLaneGain(trackId, pitch, gain)
export const adoptMix = (project: Project) => mod?.adoptMix(project) ?? false

export function setLoop(next: { start: number; end: number } | null) {
  loop = next // 불러오기 전이면 기억했다가 불러올 때 건다
  mod?.setLoop(next)
}

export function setOnEnd(cb: () => void) {
  onEnd = cb
  mod?.setOnEnd(cb)
}
