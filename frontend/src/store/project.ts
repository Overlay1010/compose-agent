import { create } from 'zustand'
import { uploadMidi } from '../api/client'
import type { Project } from '../api/types'

interface ProjectState {
  project: Project | null
  /** 에이전트가 만든 적용 전 미리보기와 그 출발 버전 (피아노롤 표시 · 적용은 다음 단계) */
  preview: Project | null
  baseVersion: number | null
  /** 미리보기가 있을 때 바뀐 소리(true)를 들을지 원래 소리(false)를 들을지 */
  hearPreview: boolean
  selectedTrackId: string | null
  loading: boolean
  error: string | null
  upload: (file: File) => Promise<void>
  selectTrack: (id: string) => void
  setPreview: (preview: Project | null, baseVersion: number | null) => void
  setHearPreview: (on: boolean) => void
}

export const useProject = create<ProjectState>((set) => ({
  project: null,
  preview: null,
  baseVersion: null,
  hearPreview: true,
  selectedTrackId: null,
  loading: false,
  error: null,

  upload: async (file) => {
    set({ loading: true, error: null })
    try {
      const project = await uploadMidi(file)
      set({ project, preview: null, baseVersion: null, hearPreview: true, selectedTrackId: project.tracks[0]?.id ?? null })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ loading: false })
    }
  },

  selectTrack: (id) => set({ selectedTrackId: id }),
  setPreview: (preview, baseVersion) => set({ preview, baseVersion, hearPreview: true }),
  setHearPreview: (on) => set({ hearPreview: on }),
}))
