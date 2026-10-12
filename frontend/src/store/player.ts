import { create } from 'zustand'
import * as player from '../audio/player'
import { useProject } from './project'

interface PlayerState {
  playing: boolean
  muted: Record<string, boolean>
  play: () => Promise<void>
  stop: () => void
  toggle: () => void
  toggleMute: (trackId: string) => void
}

export const usePlayer = create<PlayerState>((set, get) => ({
  playing: false,
  muted: {},

  play: async () => {
    const { project } = useProject.getState()
    if (!project || get().playing) return
    set({ playing: true })
    try {
      await player.play(project, get().muted)
    } catch (e) {
      set({ playing: false })
      useProject.setState({ error: `소리를 재생할 수 없습니다: ${e instanceof Error ? e.message : String(e)}` })
    }
  },

  stop: () => {
    player.stop()
    set({ playing: false })
  },

  toggle: () => {
    if (get().playing) get().stop()
    else void get().play()
  },

  toggleMute: (trackId) => {
    const muted = { ...get().muted, [trackId]: !get().muted[trackId] }
    player.setMuted(trackId, muted[trackId])
    set({ muted })
  },
}))

player.setOnEnd(() => usePlayer.setState({ playing: false }))

// 새 파일을 열면 재생을 멈추고 음소거를 초기화한다.
useProject.subscribe((state, prev) => {
  if (state.project !== prev.project) {
    player.stop()
    usePlayer.setState({ playing: false, muted: {} })
  }
})
