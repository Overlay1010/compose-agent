import { create } from 'zustand'
import * as player from '../audio/player'
import type { Project } from '../api/types'
import { changedRange } from '../diff'
import { useProject } from './project'

interface PlayerState {
  playing: boolean
  /** 처음 재생할 때 악기 샘플을 불러오는 중 */
  loadingSounds: boolean
  /** 샘플을 못 불러와 신스로 대신한 경우의 안내 */
  notice: string | null
  muted: Record<string, boolean>
  /** 솔로: 하나라도 켜지면 솔로인 트랙만 들린다 */
  solo: Record<string, boolean>
  /** 재생을 시작할 위치(박). 전체 구성을 눌러 옮긴다 */
  cursor: number
  play: () => Promise<void>
  stop: () => void
  toggle: () => void
  /** 처음으로: 시작 위치를 0으로, 재생 중이면 처음부터 다시 */
  restart: () => void
  /** 이 위치(박)로 옮긴다. 재생 중이면 바로 거기서 이어 재생 */
  seek: (beats: number) => void
  toggleMute: (trackId: string) => void
  toggleSolo: (trackId: string) => void
  /** 반복할 구간(박, 마디 경계). 정해 두면 꺼도 남아 있다 */
  loop: LoopRegion | null
  looping: boolean
  /** 구간을 정하고 반복을 켠다 (전체 구성에서 끌어서 고를 때) */
  setLoop: (region: LoopRegion) => void
  /** 반복 켜기 · 끄기. 구간이 없으면 미리보기로 바뀐 마디, 그것도 없으면 지금 위치부터 4마디 */
  toggleLoop: () => void
}

export interface LoopRegion {
  start: number
  end: number
}

/** 지금 들려줄 버전: 미리보기가 있고 "바뀐 소리"를 고른 상태면 미리보기, 아니면 현재 버전 */
function listened(): Project | null {
  const { project, preview, hearPreview } = useProject.getState()
  return hearPreview && preview ? preview : project
}

/** 음소거 + 솔로를 합친 "실제로 안 들리는 트랙" */
export function silenced(project: Project | null, muted: Record<string, boolean>, solo: Record<string, boolean>) {
  const anySolo = Object.values(solo).some(Boolean)
  const out: Record<string, boolean> = {}
  for (const t of project?.tracks ?? []) out[t.id] = !!muted[t.id] || (anySolo && !solo[t.id])
  return out
}

export const usePlayer = create<PlayerState>((set, get) => {
  const applySilence = () => {
    const off = silenced(listened(), get().muted, get().solo)
    for (const [id, m] of Object.entries(off)) player.setMuted(id, m)
  }

  return {
    playing: false,
    loadingSounds: false,
    notice: null,
    muted: {},
    solo: {},
    cursor: 0,
    loop: null,
    looping: false,

    play: async () => {
      const project = listened()
      if (!project || get().playing) return
      set({ playing: true, loadingSounds: true })
      const { looping, loop, cursor } = get()
      player.setLoop(looping ? loop : null)
      // 반복 중인데 시작 위치가 구간 밖이면 구간 처음부터
      const from = looping && loop && (cursor < loop.start || cursor >= loop.end) ? loop.start : cursor
      try {
        const fallback = await player.play(project, silenced(project, get().muted, get().solo), from)
        set({
          loadingSounds: false,
          notice: fallback.length
            ? `악기 샘플을 불러오지 못해 ${fallback.join(', ')} 트랙은 기본 신스 소리로 재생해요. 인터넷 연결을 확인해 주세요.`
            : null,
        })
      } catch (e) {
        set({ playing: false, loadingSounds: false })
        useProject.setState({ error: `소리를 재생할 수 없습니다: ${e instanceof Error ? e.message : String(e)}` })
      }
    },

    stop: () => {
      player.stop()
      set({ playing: false, loadingSounds: false })
    },

    toggle: () => {
      if (get().playing) get().stop()
      else void get().play()
    },

    restart: () => get().seek(0),

    seek: (beats) => {
      const cursor = Math.max(0, beats)
      const { looping, loop } = get()
      // 반복 구간 밖으로 옮기면 반복을 끈다 (구간은 남겨 둔다)
      if (looping && loop && (cursor < loop.start || cursor >= loop.end)) {
        set({ looping: false })
        player.setLoop(null)
      }
      set({ cursor })
      const project = listened()
      if (!project || !get().playing || get().loadingSounds) return
      player.stop()
      void player.play(project, silenced(project, get().muted, get().solo), cursor)
    },

    toggleMute: (trackId) => {
      set({ muted: { ...get().muted, [trackId]: !get().muted[trackId] } })
      applySilence()
    },

    toggleSolo: (trackId) => {
      set({ solo: { ...get().solo, [trackId]: !get().solo[trackId] } })
      applySilence()
    },

    setLoop: (region) => {
      set({ loop: region, looping: true })
      player.setLoop(region)
      const { playing, cursor } = get()
      // 지금 위치가 새 구간 밖이면 구간 처음으로
      if (cursor < region.start || cursor >= region.end || playing) get().seek(region.start)
    },

    toggleLoop: () => {
      if (get().looping) {
        set({ looping: false })
        player.setLoop(null)
        return
      }
      const { project, preview } = useProject.getState()
      if (!project) return
      const bpb = (project.time_signature[0] * 4) / project.time_signature[1]
      const here = Math.floor(get().cursor / bpb) * bpb
      const region = get().loop ?? changedRange(project, preview) ?? { start: here, end: here + 4 * bpb }
      get().setLoop(region)
    },
  }
})

player.setOnEnd(() => usePlayer.setState({ playing: false, cursor: 0 }))

useProject.subscribe((state, prev) => {
  if (state.project?.id !== prev.project?.id) {
    // 새 파일을 열면 재생을 멈추고 음소거 · 솔로를 초기화한다.
    player.stop()
    player.setLoop(null)
    usePlayer.setState({ playing: false, loadingSounds: false, notice: null, muted: {}, solo: {}, cursor: 0, loop: null, looping: false })
    return
  }
  const source = (s: typeof state) => (s.hearPreview && s.preview ? s.preview : s.project)
  // 볼륨 · 팬만 바뀌었으면 다시 불러오지 않고 그 자리에서 바꾼다
  const next = source(state)
  if (next && next !== source(prev) && player.adoptMix(next)) return
  const { playing, loadingSounds, muted, solo } = usePlayer.getState()
  if (source(state) !== source(prev) && playing && !loadingSounds) {
    // 바뀐 소리 ↔ 원래 소리, 새 미리보기, 적용 등으로 들을 버전이 바뀌면 같은 자리에서 이어 재생
    const at = player.positionBeats()
    player.stop()
    void player.play(source(state)!, silenced(source(state), muted, solo), at)
  }
})
