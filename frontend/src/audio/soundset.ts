import { create } from 'zustand'
import { LEVELS } from './levels'

// 멜로디 악기 소리 세트. 셋 다 같은 GM 128개 악기를 mp3로 미리 녹음해 둔 것 (midi-js-soundfonts, 녹음 길이 3.13초로 같음).
// 드럼은 세트와 상관없이 Sonic Pi 샘플. 고른 세트는 이 브라우저에만 기억한다 (곡마다가 아니라 듣는 사람의 취향).
// Musyng Kite · FatBoy는 같은 악기라도 FluidR3보다 작거나 커서(악기마다 -12 ~ +6dB), levels.ts의 보정을 더해
// 세트를 바꿔도 믹스 밸런스가 그대로이게 한다.

export interface SoundSet {
  id: string
  name: string
  folder: string
  license: string
  /** CC BY-SA: 이 소리로 만든 음원을 배포하면 같은 라이선스 조건이 붙을 수 있다 */
  shareAlike: boolean
}

export const SOUND_SETS: SoundSet[] = [
  { id: 'fluid', name: 'FluidR3 (기본)', folder: 'FluidR3_GM', license: 'CC BY 3.0', shareAlike: false },
  { id: 'musyng', name: 'Musyng Kite (정교함)', folder: 'MusyngKite', license: 'CC BY-SA 3.0', shareAlike: true },
  { id: 'fatboy', name: 'FatBoy', folder: 'FatBoy', license: 'CC BY-SA 3.0', shareAlike: true },
]

const KEY = 'compose-agent:sound-set'
const BASE = 'https://gleitz.github.io/midi-js-soundfonts/'

function saved(): string {
  try {
    const id = localStorage.getItem(KEY)
    return SOUND_SETS.some((s) => s.id === id) ? (id as string) : 'fluid'
  } catch {
    return 'fluid' // 사생활 보호 창 등에서 저장소를 못 쓰면 기본
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

/** 이 악기(GM 번호) 녹음이 있는 폴더 주소 (끝에 / 포함). name은 FluidR3 파일 이름 (세 세트가 같다) */
export const fontUrl = (name: string) => `${BASE}${currentSet().folder}/${name}-mp3/`

/** FluidR3와 같은 크기가 되도록 이 악기에 곱할 소리 크기 (1 = 그대로) */
export function levelGain(program: number): number {
  const db = LEVELS[currentSet().id]?.[program] ?? 0
  return Math.pow(10, db / 20)
}
