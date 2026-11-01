import { create } from 'zustand'

/** 내 샘플팩 창 (components/SamplePack.tsx)이 열려 있는지 */
export const useSamplePack = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}))
