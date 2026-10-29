import { create } from 'zustand'
import type { ChordSpan } from '../api/types'

interface ReharmState {
  /** 코드 띠에서 비교 중인 리하모니 제안 (어느 카드인지 + 제안 코드 · 제안을 계산한 원래 코드) */
  comparing: { id: string; chords: ChordSpan[]; base: ChordSpan[] } | null
  compare: (id: string, chords: ChordSpan[], base: ChordSpan[]) => void
  stop: () => void
}

/** 채팅의 제안 카드를 누르면 코드 띠가 그 제안을 보여 주고, 원래와 달라진 코드만 라임으로 표시한다. */
export const useReharm = create<ReharmState>((set) => ({
  comparing: null,
  compare: (id, chords, base) => set({ comparing: { id, chords, base } }),
  stop: () => set({ comparing: null }),
}))
