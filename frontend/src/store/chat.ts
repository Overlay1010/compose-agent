import { create } from 'zustand'
import { chatStream } from '../api/client'
import type { ToolStep } from '../api/types'
import { changedTrackIds } from '../diff'
import { useProject } from './project'

export type LiveStep = ToolStep & { running?: boolean }

export interface ChatMessage {
  id: number
  role: 'user' | 'agent' | 'error' | 'note'
  text: string
  steps?: LiveStep[]
  /** 에이전트가 아직 일하는 중 (진행 상황을 실시간으로 채우는 메시지) */
  live?: boolean
  /** 지금 하는 일 한 줄 ("생각하는 중…", "세기 조절 중…") */
  status?: string
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

// 실행 중인 도구를 사람 말로 (진행 상황 표시용)
const TOOL_LABELS: Record<string, string> = {
  transpose: '조옮김',
  shift_octave: '옥타브 이동',
  quantize: '박자 정리',
  adjust_velocity: '세기 조절',
  swing: '스윙 넣기',
  set_tempo: '템포 바꾸기',
  set_instrument: '악기 바꾸기',
  delete_notes: '음 지우기',
  set_length: '음 길이 바꾸기',
  copy_bars: '마디 복사',
  humanize: '사람 느낌 넣기',
  velocity_ramp: '점점 세기 바꾸기',
  get_project_info: '트랙 확인',
  start_over: '미리보기 버리고 다시 시작',
}

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
    // 진행 상황을 채워 갈 에이전트 메시지
    const liveId = nextId++
    set({ sending: true, messages: [...get().messages, { id: liveId, role: 'agent', text: '', steps: [], live: true, status: '생각하는 중…' }] })
    const update = (fn: (m: ChatMessage) => ChatMessage) =>
      set({ messages: get().messages.map((m) => (m.id === liveId ? fn(m) : m)) })
    const trackName = (id: string) => project.tracks.find((t) => t.id === id)?.name ?? id
    const startedAt = performance.now()
    try {
      const r = await chatStream(project.id, text, (e) => {
        if (e.kind === 'thinking') {
          update((m) => ({ ...m, status: e.round === 1 ? '생각하는 중…' : '결과를 보고 다음 할 일을 정하는 중…' }))
        } else if (e.kind === 'tool_start') {
          const ids = Array.isArray(e.args.track_ids) ? (e.args.track_ids as string[]).map(trackName).join(', ') : ''
          const label = TOOL_LABELS[e.name] ?? e.name
          const running: LiveStep = { name: e.name, args: e.args, ok: true, summary: `${label} 중…${ids ? ` (${ids})` : ''}`, changed_notes: 0, changed_settings: false, running: true }
          update((m) => ({ ...m, status: `${label} 중…`, steps: [...(m.steps ?? []), running] }))
        } else {
          update((m) => {
            const steps = [...(m.steps ?? [])]
            const i = steps.findIndex((s) => s.running)
            if (i >= 0) steps[i] = e.step
            else steps.push(e.step)
            return { ...m, steps }
          })
        }
      })
      const secs = ((performance.now() - startedAt) / 1000).toFixed(1)
      update(() => ({
        id: liveId,
        role: 'agent',
        text: r.reply,
        steps: r.steps,
        meta: `${r.model} · LLM ${r.llm_calls}회 · ${secs}초`,
        madePreview: r.steps.some((s) => s.ok && (s.changed_notes > 0 || s.changed_settings)),
      }))
      const store = useProject.getState()
      store.setPreview(r.preview, r.base_version)
      // 지금 보고 있는 트랙이 안 바뀌었으면 바뀐 트랙으로 옮겨서 바로 보이게
      const changed = changedTrackIds(store.project!, r.preview)
      if (changed.size && !changed.has(store.selectedTrackId ?? '')) store.selectTrack([...changed][0])
    } catch (e) {
      // 진행 중이던 메시지는 지우고 오류로 바꾼다
      set({ messages: get().messages.filter((m) => m.id !== liveId) })
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
