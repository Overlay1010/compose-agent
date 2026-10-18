import { create } from 'zustand'
import * as api from '../api/client'
import type { LogEntry, Project, VersionInfo } from '../api/types'
import type { Selection } from '../selection'

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
  /** 화면에서 고른 부분 ("여기 한 옥타브 올려줘"에 쓰임) */
  selection: Selection | null
  setSelection: (selection: Selection | null) => void
  loading: boolean
  /** 적용 · 취소 · 되돌리기 요청 중 */
  busy: boolean
  error: string | null
  upload: (file: File) => Promise<void>
  /** 저장된 프로젝트를 다시 연다. 화면에 그릴 대화 기록을 돌려준다 (실패하면 null) */
  open: (projectId: string) => Promise<LogEntry[] | null>
  /** 프로젝트를 닫고 처음 화면으로 (저장돼 있어서 다시 열 수 있다) */
  close: () => void
  selectTrack: (id: string) => void
  setPreview: (preview: Project | null, baseVersion: number | null) => void
  setHearPreview: (on: boolean) => void
  applyPreview: () => Promise<Project | null>
  cancelPreview: () => Promise<void>
  restore: (version: number) => Promise<Project | null>
  undo: () => Promise<Project | null>
  /** 트랙 악기 바꾸기 (미리보기는 그대로 둔다). 성공하면 새 버전 */
  setInstrument: (trackId: string, program: number) => Promise<api.TrackChange | null>
  /** 트랙 볼륨 · 팬 바꾸기 (미리보기는 그대로 둔다). 성공하면 새 버전 */
  setMix: (trackId: string, mix: { volume?: number; pan?: number }) => Promise<api.TrackChange | null>
  /** 드럼 소리별 크기 (그 소리 음들의 세기 × scale) */
  setLane: (trackId: string, pitch: number, scale: number) => Promise<api.TrackChange | null>
  /** 드럼 레인 하나의 소리 고르기 */
  setDrumSound: (trackId: string, pitch: number, sound: string) => Promise<api.TrackChange | null>
  /** 벨로시티 편집창: 음 하나하나의 세기 */
  setVelocities: (trackId: string, changes: { index: number; velocity: number }[]) => Promise<api.TrackChange | null>
  loadVersions: () => Promise<void>
  setHistoryOpen: (open: boolean) => void
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export const useProject = create<ProjectState>((set, get) => {
  /** 보고 있던 트랙이 이 버전에 없으면(미리보기의 새 트랙 등) 첫 트랙을 고른다 */
  const keepSelection = (p: Project) => {
    const id = get().selectedTrackId
    return p.tracks.some((t) => t.id === id) ? id : (p.tracks[0]?.id ?? null)
  }

  /** 트랙 설정(악기 · 볼륨 · 팬)을 바꾸는 요청. 미리보기는 서버가 같이 고쳐서 돌려준다 */
  const changeTrack = async (request: (id: string) => Promise<api.TrackChange>): Promise<api.TrackChange | null> => {
    const { project, busy } = get()
    if (!project || busy) return null
    set({ busy: true, error: null })
    try {
      const r = await request(project.id)
      if (r.project.version === project.version) return null // 이미 그 값
      set({ project: r.project, preview: r.preview, baseVersion: r.preview ? r.project.version : null })
      void get().loadVersions()
      return r
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
      set({ project: next, preview: null, baseVersion: null, hearPreview: true, selectedTrackId: keepSelection(next) })
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
    selection: null,
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

    open: async (projectId) => {
      set({ loading: true, error: null })
      try {
        const s = await api.getSession(projectId)
        set({
          project: s.project,
          preview: s.preview,
          baseVersion: s.base_version,
          hearPreview: true,
          versions: [],
          selectedTrackId: s.project.tracks[0]?.id ?? null,
        })
        void get().loadVersions()
        return s.log
      } catch (e) {
        set({ error: e instanceof api.ApiError && e.code === 'project_not_found' ? '저장된 프로젝트를 찾을 수 없어요. 새로 열어 주세요.' : message(e) })
        return null
      } finally {
        set({ loading: false })
      }
    },

    close: () =>
      set({ project: null, preview: null, baseVersion: null, versions: [], historyOpen: false, selectedTrackId: null, error: null }),

    selectTrack: (id) => set({ selectedTrackId: id }),
    setSelection: (selection) => set({ selection }),
    setPreview: (preview, baseVersion) => set({ preview, baseVersion, hearPreview: true }),
    setHearPreview: (on) => set({ hearPreview: on }),

    applyPreview: () => changeVersion(api.applyPreview),
    restore: (version) => changeVersion((id) => api.restoreVersion(id, version)),
    undo: () => changeVersion(api.undo),

    setInstrument: (trackId, program) => changeTrack((id) => api.setInstrument(id, trackId, program)),
    setMix: (trackId, mix) => changeTrack((id) => api.setMix(id, trackId, mix)),
    setLane: (trackId, pitch, scale) => changeTrack((id) => api.setLane(id, trackId, pitch, scale)),
    setDrumSound: (trackId, pitch, sound) => changeTrack((id) => api.setDrumSound(id, trackId, pitch, sound)),
    setVelocities: (trackId, changes) =>
      changeTrack((id) => api.setVelocities(id, trackId, get().project!.version, changes)),

    cancelPreview: async () => {
      const { project, busy } = get()
      if (!project || busy) return
      set({ busy: true, error: null })
      try {
        await api.cancelPreview(project.id)
        // 미리보기의 새 트랙을 보고 있었으면 그 트랙이 없어지므로 첫 트랙으로
        set({ preview: null, baseVersion: null, hearPreview: true, selectedTrackId: keepSelection(project) })
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

// 주소에 프로젝트 id(#id)를 남겨, 새로고침하면 같은 프로젝트를 다시 연다 (App.tsx)
useProject.subscribe((state, prev) => {
  if (state.project?.id === prev.project?.id) return
  const hash = state.project ? `#${state.project.id}` : ''
  if (location.hash !== hash) history.replaceState(null, '', hash || location.pathname)
})

// 다른 프로젝트를 열면 고른 부분을 푼다
useProject.subscribe((state, prev) => {
  if (state.project?.id !== prev.project?.id && state.selection) useProject.setState({ selection: null })
})
