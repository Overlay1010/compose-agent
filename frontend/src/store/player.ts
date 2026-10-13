import { create } from 'zustand'
import * as player from '../audio/player'
import { useProject } from './project'

interface PlayerState {
  playing: boolean
  /** 처음 재생할 때 악기 샘플을 불러오는 중 */
  loadingSounds: boolean
  /** 샘플을 못 불러와 신스로 대신한 경우의 안내 */
  notice: string | null
  muted: Record<string, boolean>
  play: () => Promise<void>
  stop: () => void
  toggle: () => void
  toggleMute: (trackId: string) => void
}

/** 지금 들려줄 버전: 미리보기가 있고 "바뀐 소리"를 고른 상태면 미리보기, 아니면 현재 버전 */
function listened() {
  const { project, preview, hearPreview } = useProject.getState()
  return hearPreview && preview ? preview : project
}

export const usePlayer = create<PlayerState>((set, get) => ({
  playing: false,
  loadingSounds: false,
  notice: null,
  muted: {},

  play: async () => {
    const project = listened()
    if (!project || get().playing) return
    set({ playing: true, loadingSounds: true })
    try {
      const fallback = await player.play(project, get().muted)
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

  toggleMute: (trackId) => {
    const muted = { ...get().muted, [trackId]: !get().muted[trackId] }
    player.setMuted(trackId, muted[trackId])
    set({ muted })
  },
}))

player.setOnEnd(() => usePlayer.setState({ playing: false }))

useProject.subscribe((state, prev) => {
  if (state.project?.id !== prev.project?.id) {
    // 새 파일을 열면 재생을 멈추고 음소거를 초기화한다.
    player.stop()
    usePlayer.setState({ playing: false, loadingSounds: false, notice: null, muted: {} })
    return
  }
  const source = (s: typeof state) => (s.hearPreview && s.preview ? s.preview : s.project)
  const { playing, loadingSounds, muted } = usePlayer.getState()
  if (source(state) !== source(prev) && playing && !loadingSounds) {
    // 바뀐 소리 ↔ 원래 소리, 새 미리보기, 적용 등으로 들을 버전이 바뀌면 같은 자리에서 이어 재생
    const at = player.positionBeats()
    player.stop()
    void player.play(source(state)!, muted, at)
  }
})
