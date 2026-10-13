import { create } from 'zustand'
import { uploadMidi } from '../api/client'
import type { Project } from '../api/types'

interface ProjectState {
  project: Project | null
  /** 에이전트가 만든 적용 전 미리보기와 그 출발 버전 (피아노롤 표시 · 적용은 다음 단계) */
  preview: Project | null
  baseVersion: number | null
  selectedTrackId: string | null
  loading: boolean
  error: string | null
  upload: (file: File) => Promise<void>
  selectTrack: (id: string) => void
  setPreview: (preview: Project | null, baseVersion: number | null) => void
}

export const useProject = create<ProjectState>((set) => ({
  project: null,
  preview: null,
  baseVersion: null,
  selectedTrackId: null,
  loading: false,
  error: null,

  upload: async (file) => {
    set({ loading: true, error: null })
    try {
      const project = await uploadMidi(file)
      set({ project, preview: null, baseVersion: null, selectedTrackId: project.tracks[0]?.id ?? null })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ loading: false })
    }
  },

  selectTrack: (id) => set({ selectedTrackId: id }),
  setPreview: (preview, baseVersion) => set({ preview, baseVersion }),
}))
