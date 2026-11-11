import { create } from 'zustand'
import { LEVELS } from './levels'
import { HQ_NOTES, HQ_PROGRAMS, SALAMANDER_URL, TONEJS_URL } from './hqset'

// 멜로디 악기 소리 세트. GM 세트 셋(FluidR3 · Musyng Kite · FatBoy)은 같은 GM 128개 악기를 mp3로 미리 녹음해 둔 것
// (midi-js-soundfonts, 녹음 길이 3.13초로 같음). 기본인 고음질 세트는 피아노 · 기타 · 베이스 · 현악 · 관악처럼 자주 쓰는
// 악기만 따로 녹음한 샘플로 바꾸고(hqset.ts), 없는 악기는 FluidR3를 쓴다.
// 드럼은 세트와 상관없이 Sonic Pi 샘플. 고른 세트는 이 브라우저에만 기억한다 (곡마다가 아니라 듣는 사람의 취향).
// 같은 악기라도 세트마다 크기가 달라서(FluidR3 대비 -26 ~ +6dB), 보정을 더해 세트를 바꿔도 믹스 밸런스가 그대로이게 한다.

export interface SoundSet {
  id: string
  name: string
  folder: string
  license: string
  /** CC BY-SA: 이 소리로 만든 음원을 배포하면 같은 라이선스 조건이 붙을 수 있다 */
  shareAlike: boolean
}

export const SOUND_SETS: SoundSet[] = [
  { id: 'hq', name: '고음질 (기본)', folder: 'FluidR3_GM', license: 'CC BY 3.0', shareAlike: false },
  { id: 'fluid', name: 'FluidR3', folder: 'FluidR3_GM', license: 'CC BY 3.0', shareAlike: false },
  { id: 'musyng', name: 'Musyng Kite (정교함)', folder: 'MusyngKite', license: 'CC BY-SA 3.0', shareAlike: true },
  { id: 'fatboy', name: 'FatBoy', folder: 'FatBoy', license: 'CC BY-SA 3.0', shareAlike: true },
]

// 고음질 세트를 기본으로 바꾸면서 키를 새로 했다 — 예전 키에는 기본이던 FluidR3가 남아 있을 수 있어서
const KEY = 'compose-agent:sound-set-v2'
const BASE = 'https://gleitz.github.io/midi-js-soundfonts/'
const DEFAULT = 'hq'

function saved(): string {
  try {
    const id = localStorage.getItem(KEY)
    return SOUND_SETS.some((s) => s.id === id) ? (id as string) : DEFAULT
  } catch {
    return DEFAULT // 사생활 보호 창 등에서 저장소를 못 쓰면 기본
  }
}

interface SoundSetState {
  id: string
  choose: (id: string) => void
}

export const useSoundSet = create<SoundSetState>((set) => ({
  id: saved(),
  choose: (id) => {
    try {
      localStorage.setItem(KEY, id)
    } catch {
      // 기억은 못 해도 이번에는 바꾼다
    }
    set({ id })
  },
}))

export const currentSet = (): SoundSet => SOUND_SETS.find((s) => s.id === useSoundSet.getState().id) ?? SOUND_SETS[0]

/** 이 악기(GM 번호)의 녹음: 폴더 주소(끝에 / 포함) · 녹음된 음들 · 음 번호 → 파일 이름 */
export interface NoteSource {
  baseUrl: string
  /** 녹음된 음 (MIDI 번호, 오름차순) */
  notes: number[]
  file: (pitch: number) => string
}

// GM 세트 파일은 플랫 이름 (Db4.mp3), 고음질 세트 파일은 샵 이름 (Cs4.mp3)
const FLAT_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
const SHARP_NAMES = ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B']
const GM_NOTES = Array.from({ length: 88 }, (_, i) => 21 + i) // A0(21) ~ C8(108) 모두

/** name은 FluidR3 파일 이름 (GM 세트 셋이 같다) */
export function noteSource(program: number, name: string): NoteSource {
  const set = currentSet()
  const hq = set.id === 'hq' ? HQ_PROGRAMS[program] : undefined
  if (hq) {
    return {
      baseUrl: hq.source === 'salamander' ? SALAMANDER_URL : `${TONEJS_URL}${hq.source}/`,
      notes: HQ_NOTES[hq.source],
      file: (p) => `${SHARP_NAMES[p % 12]}${Math.floor(p / 12) - 1}.mp3`,
    }
  }
  return {
    baseUrl: `${BASE}${set.folder}/${name}-mp3/`,
    notes: GM_NOTES,
    file: (p) => `${FLAT_NAMES[p % 12]}${Math.floor(p / 12) - 1}.mp3`,
  }
}

/** FluidR3와 같은 크기가 되도록 이 악기에 곱할 소리 크기 (1 = 그대로) */
export function levelGain(program: number): number {
  const id = currentSet().id
  const db = id === 'hq' ? (HQ_PROGRAMS[program]?.db ?? 0) : (LEVELS[id]?.[program] ?? 0)
  return Math.pow(10, db / 20)
}
