import { create } from 'zustand'
import * as api from '../api/client'
import type { Project, VersionInfo } from '../api/types'

interface ProjectState {
  project: Project | null
  /** 에이전트가 만든 적용 전 미리보기와 그 출발 버전 */
  preview: Project | null
  baseVersion: number | null
  /** 미리보기가 있을 때 바뀐 소리(true)를 들을지 원래 소리(false)를 들을지 */
  hearPreview: boolean
  versions: VersionInfo[]
  historyOpen: boolean
  selectedTrackId: string | null
  loading: boolean
  /** 적용 · 취소 · 되돌리기 요청 중 */
  busy: boolean
  error: string | null
  upload: (file: File) => Promise<void>
  selectTrack: (id: string) => void
  setPreview: (preview: Project | null, baseVersion: number | null) => void
  setHearPreview: (on: boolean) => void
  applyPreview: () => Promise<Project | null>
  cancelPreview: () => Promise<void>
  restore: (version: number) => Promise<Project | null>
  undo: () => Promise<Project | null>
  /** 트랙 악기 바꾸기 (미리보기는 그대로 둔다). 성공하면 새 버전 */
  setInstrument: (trackId: string, program: number) => Promise<Project | null>
  /** 트랙 볼륨 · 팬 바꾸기 (미리보기는 그대로 둔다). 성공하면 새 버전 */
  setMix: (trackId: string, mix: { volume?: number; pan?: number }) => Promise<Project | null>
  loadVersions: () => Promise<void>
  setHistoryOpen: (open: boolean) => void
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export const useProject = create<ProjectState>((set, get) => {
  /** 트랙 설정(악기 · 볼륨 · 팬)을 바꾸는 요청. 미리보기는 서버가 같이 고쳐서 돌려준다 */
  const changeTrack = async (
    request: (id: string) => Promise<{ project: Project; preview: Project | null }>,
  ): Promise<Project | null> => {
    const { project, busy } = get()
    if (!project || busy) return null
    set({ busy: true, error: null })
    try {
      const r = await request(project.id)
      if (r.project.version === project.version) return null // 이미 그 값
      set({ project: r.project, preview: r.preview, baseVersion: r.preview ? r.project.version : null })
      void get().loadVersions()
      return r.project
    } catch (e) {
      set({ error: message(e) })
      return null
    } finally {
      set({ busy: false })
    }
  }

  /** 새 버전이 생기는 요청(적용 · 되돌리기)을 같은 방식으로 처리한다 */
  const changeVersion = async (request: (id: string) => Promise<Project>): Promise<Project | null> => {
    const { project, busy } = get()
    if (!project || busy) return null
    set({ busy: true, error: null })
    try {
      const next = await request(project.id)
      set({ project: next, preview: null, baseVersion: null, hearPreview: true })
      void get().loadVersions()
      return next
    } catch (e) {
      set({ error: message(e) })
      // 충돌 등으로 실패하면 서버 쪽 미리보기도 없어졌을 수 있어 화면도 맞춘다
      if (e instanceof api.ApiError && e.code === 'preview_conflict') set({ preview: null, baseVersion: null })
      return null
    } finally {
      set({ busy: false })
    }
  }

  return {
    project: null,
    preview: null,
    baseVersion: null,
    hearPreview: true,
    versions: [],
    historyOpen: false,
    selectedTrackId: null,
    loading: false,
    busy: false,
    error: null,

    upload: async (file) => {
      set({ loading: true, error: null })
      try {
        const project = await api.uploadMidi(file)
        set({
          project,
          preview: null,
          baseVersion: null,
          hearPreview: true,
          versions: [],
          selectedTrackId: project.tracks[0]?.id ?? null,
        })
        void get().loadVersions()
      } catch (e) {
        set({ error: message(e) })
      } finally {
        set({ loading: false })
      }
    },

    selectTrack: (id) => set({ selectedTrackId: id }),
    setPreview: (preview, baseVersion) => set({ preview, baseVersion, hearPreview: true }),
    setHearPreview: (on) => set({ hearPreview: on }),

    applyPreview: () => changeVersion(api.applyPreview),
    restore: (version) => changeVersion((id) => api.restoreVersion(id, version)),
    undo: () => changeVersion(api.undo),

    setInstrument: (trackId, program) => changeTrack((id) => api.setInstrument(id, trackId, program)),
    setMix: (trackId, mix) => changeTrack((id) => api.setMix(id, trackId, mix)),

    cancelPreview: async () => {
      const { project, busy } = get()
      if (!project || busy) return
      set({ busy: true, error: null })
      try {
        await api.cancelPreview(project.id)
        set({ preview: null, baseVersion: null, hearPreview: true })
      } catch (e) {
        set({ error: message(e) })
      } finally {
        set({ busy: false })
      }
    },

    loadVersions: async () => {
      const { project } = get()
      if (!project) return
      try {
        set({ versions: await api.listVersions(project.id) })
      } catch (e) {
        set({ error: message(e) })
      }
    },

    setHistoryOpen: (open) => {
      set({ historyOpen: open })
      if (open) void get().loadVersions()
    },
  }
})
