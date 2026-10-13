import { create } from 'zustand'
import { chat } from '../api/client'
import type { ToolStep } from '../api/types'
import { useProject } from './project'

export interface ChatMessage {
  id: number
  role: 'user' | 'agent' | 'error'
  text: string
  steps?: ToolStep[]
  /** 모델 · LLM 호출 수 · 걸린 시간 (평가 때 참고) */
  meta?: string
  madePreview?: boolean
}

interface ChatState {
  messages: ChatMessage[]
  sending: boolean
  send: (text: string) => Promise<void>
}

let nextId = 1

export const useChat = create<ChatState>((set, get) => ({
  messages: [],
  sending: false,

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
        madePreview: r.steps.some((s) => s.ok && s.changed_notes > 0),
      })
      useProject.getState().setPreview(r.preview, r.base_version)
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
