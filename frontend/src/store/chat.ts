import { create } from 'zustand'
import { chat } from '../api/client'
import type { ToolStep } from '../api/types'
import { changedTrackIds } from '../diff'
import { useProject } from './project'

export interface ChatMessage {
  id: number
  role: 'user' | 'agent' | 'error' | 'note'
  text: string
  steps?: ToolStep[]
  /** 모델 · LLM 호출 수 · 걸린 시간 (평가 때 참고) */
  meta?: string
  madePreview?: boolean
  /** 'note'에 되돌리기 버튼을 붙일지 */
  canUndo?: boolean
}

interface ChatState {
  messages: ChatMessage[]
  sending: boolean
  send: (text: string) => Promise<void>
  /** 적용 · 취소 · 되돌리기 같은 일을 대화에 한 줄로 남긴다 */
  note: (text: string, canUndo?: boolean) => void
}

let nextId = 1

export const useChat = create<ChatState>((set, get) => ({
  messages: [],
  sending: false,

  note: (text, canUndo = false) =>
    set({ messages: [...get().messages.map((m) => ({ ...m, canUndo: false })), { id: nextId++, role: 'note', text, canUndo }] }),

  send: async (raw) => {
    const text = raw.trim()
    const { project } = useProject.getState()
    if (!text || !project || get().sending) return

    const add = (m: Omit<ChatMessage, 'id'>) => set({ messages: [...get().messages, { id: nextId++, ...m }] })
    add({ role: 'user', text })
    set({ sending: true })
    const startedAt = performance.now()
    try {
      const r = await chat(project.id, text)
      const secs = ((performance.now() - startedAt) / 1000).toFixed(1)
      add({
        role: 'agent',
        text: r.reply,
        steps: r.steps,
        meta: `${r.model} · LLM ${r.llm_calls}회 · ${secs}초`,
        madePreview: r.steps.some((s) => s.ok && (s.changed_notes > 0 || s.changed_settings)),
      })
      const store = useProject.getState()
      store.setPreview(r.preview, r.base_version)
      // 지금 보고 있는 트랙이 안 바뀌었으면 바뀐 트랙으로 옮겨서 바로 보이게
      const changed = changedTrackIds(store.project!, r.preview)
      if (changed.size && !changed.has(store.selectedTrackId ?? '')) store.selectTrack([...changed][0])
    } catch (e) {
      add({ role: 'error', text: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ sending: false })
    }
  },
}))

// 새 파일을 열면 대화를 비운다 (백엔드도 프로젝트마다 대화가 따로다).
useProject.subscribe((state, prev) => {
  if (state.project?.id !== prev.project?.id) useChat.setState({ messages: [], sending: false })
})
