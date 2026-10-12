import { create } from 'zustand'
import { uploadMidi } from '../api/client'
import type { Project } from '../api/types'

interface ProjectState {
  project: Project | null
  selectedTrackId: string | null
  loading: boolean
  error: string | null
  upload: (file: File) => Promise<void>
  selectTrack: (id: string) => void
}

export const useProject = create<ProjectState>((set) => ({
  project: null,
  selectedTrackId: null,
  loading: false,
  error: null,

  upload: async (file) => {
    set({ loading: true, error: null })
    try {
      const project = await uploadMidi(file)
      set({ project, selectedTrackId: project.tracks[0]?.id ?? null })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ loading: false })
    }
  },

  selectTrack: (id) => set({ selectedTrackId: id }),
}))
