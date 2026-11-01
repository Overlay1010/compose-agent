// 내 샘플(원샷 WAV) 하나를 읽어 이름표를 만든다: 종류 · 기준음 · 길이 · 밝기 · 크기 보정.
// 순수 함수만 둔다 (브라우저 API 없이 Node에서도 돌려 볼 수 있게 — 다른 파일을 import하지 않는다).
//
// 순서: 파일 · 폴더 이름을 먼저 보고(시판 샘플팩은 거의 "Pluck_C3", "808 - F#"처럼 이름이 붙어 있다),
// 이름으로 모르는 것만 소리 모양으로 정한다. 음 높이는 이름의 음 이름(C, F# …)을 믿고 옥타브는 소리에서 찾는다 —
// 옥타브 숫자는 DAW마다 달라서(Ableton · Logic은 가운데 C = C3, FL은 C5) 이름만으로는 한 옥타브씩 틀린다.

export type SampleKind = 'bass' | 'keys' | 'pluck' | 'pad' | 'lead' | 'bell' | 'chord' | 'loop' | 'drum' | 'other'

export interface SampleMeta {
  id: string
  name: string
  folder: string
  kind: SampleKind
  /** 녹음된 음 (MIDI). 음 높이가 없는 소리면 null */
  root: number | null
  /** 들리는 길이(초): 가장 큰 곳보다 40dB 작아질 때까지 */
  length: number
  /** 1초 뒤에도 크게(-6dB 안쪽) 남아 있음 — 패드처럼 길게 끌 수 있는 소리 */
  sustained: boolean
  /** 0 어두움 ~ 1 밝음 (스펙트럼 중심 200Hz ~ 5kHz를 로그로) */
  brightness: number
  /** 샘플끼리 크기를 맞추려고 곱할 값 */
  gain: number
  /** 기준음 · 종류를 어디서 알았는지 (화면 표시 · 사용자가 고쳤는지) */
  rootFrom: 'name' | 'audio' | 'user' | null
  kindFrom: 'name' | 'audio' | 'user'
}

export const KIND_NAMES: Record<SampleKind, string> = {
  bass: '베이스', keys: '건반', pluck: '플럭', pad: '패드', lead: '리드', bell: '벨',
  chord: '코드 원샷', loop: '멜로디 루프', drum: '드럼', other: '기타 소리',
}

/** 음 하나를 높이고 낮춰 악기로 쓸 수 있는 종류 (코드 원샷 · 루프는 음이 겹쳐 들린다) */
export const PLAYABLE: SampleKind[] = ['bass', 'keys', 'pluck', 'pad', 'lead', 'bell']

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
export const noteName = (pitch: number) => `${NOTE_NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`

// ---------- 이름 ----------

// 앞에 있을수록 먼저 (드럼 · 루프 · 코드를 먼저 걸러야 "Bass Loop"가 베이스 원샷이 되지 않는다)
const KIND_WORDS: [SampleKind, RegExp][] = [
  ['drum', /kick|snare|clap|hi ?hats?|\bhh\b|\boh\b|cymbal|crash|\bride\b|\bperc|\btoms?\b|\brim\b|shaker|\bsnap\b|\bkck\b|\bsd\b|\bbd\b/],
  ['loop', /loop|\bmelod(y|ic)\b|\briff\b|phrase|\b\d{2,3} ?bpm\b|\bbpm ?\d{2,3}\b/],
  ['chord', /chord|\b[a-g](#|b)?(maj|min|m7|maj7|dim|sus\d?|add9|m9|7)\b|\b(maj|min|minor|major)\b/],
  ['bass', /808|bass|\bsub\b|reese/],
  ['pad', /\bpad|atmo|ambien|drone|string|choir|texture|swell/],
  ['bell', /bell|glock|chime|music ?box|celest|mallet|marimba|vibra|kalimba/],
  ['pluck', /pluck|guitar|\bgtr\b|harp|pizz|koto|\bstab\b/],
  ['keys', /\bkeys?\b|piano|rhodes|\bep\b|e-?piano|organ|wurli/],
  ['lead', /lead|\bmelod|synth|\bsaw\b|\bvox\b|vocal|flute|brass|horn|\bsax\b|whistle/],
]

/** 이름(폴더 포함)에서 종류. "One Shot"이 붙으면 루프 · 멜로디가 아니다 */
export function kindFromName(text: string): SampleKind | null {
  const t = text.toLowerCase().replace(/[_\-.()[\]]+/g, ' ')
  const oneShot = /one ?shot|\bos\b/.test(t)
  for (const [kind, re] of KIND_WORDS) {
    if (kind === 'loop' && oneShot) continue
    if (re.test(t)) return kind
  }
  return null
}

const ACCIDENTAL: Record<string, number> = { '#': 1, '♯': 1, s: 1, sharp: 1, b: -1, '♭': -1, flat: -1 }
const LETTER: Record<string, number> = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 }

/**
 * 파일 이름에서 음 이름 (피치 클래스 0~11 + 이름에 적힌 옥타브). 못 찾으면 null.
 * "Pluck_C3" · "808 - F#" · "Keys (Bb2)" · "Bass A#1" · "Sub_G" 를 읽는다. 단어 하나짜리 "B" · "A"는 맨 끝일 때만
 * (예: "Pad B"는 변형 번호일 수도 있지만 원샷 이름 끝의 글자 하나는 대부분 음 이름).
 */
export function noteFromName(file: string): { pc: number; octave: number | null } | null {
  const t = file.replace(/\.[a-z0-9]+$/i, '')
  const tokens = t.split(/[\s_\-.,()[\]]+/).filter(Boolean)
  const withOctave = /^([A-Ga-g])(#|♯|b|♭|s|sharp|flat)?(-?[0-8])$/
  const plain = /^([A-G])(#|♯|b|♭|sharp|flat)?(m|min|maj)?$/
  const at = (letter: string, acc?: string) => (LETTER[letter.toLowerCase()] + (acc ? ACCIDENTAL[acc] : 0) + 12) % 12
  for (let i = tokens.length - 1; i >= 0; i--) {
    const m = tokens[i].match(withOctave)
    if (m && !/^\d/.test(tokens[i])) return { pc: at(m[1], m[2]), octave: Number(m[3]) }
  }
  const last = tokens[tokens.length - 1]?.match(plain)
  if (last) return { pc: at(last[1], last[2]), octave: null }
  // "C# Pluck"처럼 앞에 붙인 음 이름 (대문자 + 임시표가 있을 때만 — 그냥 "A"는 관사일 수 있다)
  const first = tokens[0]?.match(/^([A-G])(#|♯|b|♭)$/)
  if (first) return { pc: at(first[1], first[2]), octave: null }
  return null
}

// ---------- 소리 ----------

const FRAME_S = 0.01

function rmsFrames(x: Float32Array, rate: number): Float32Array {
  const size = Math.max(1, Math.round(rate * FRAME_S))
  const out = new Float32Array(Math.ceil(x.length / size))
  for (let f = 0; f < out.length; f++) {
    let sum = 0
    const end = Math.min(x.length, (f + 1) * size)
    for (let i = f * size; i < end; i++) sum += x[i] * x[i]
    out[f] = Math.sqrt(sum / Math.max(1, end - f * size))
  }
  return out
}

/** YIN 음 높이 찾기. 주파수(Hz)와 믿을 만한 정도(0~1)를, 주기가 안 보이면 null */
export function yin(x: Float32Array, start: number, rate: number, minHz = 30, maxHz = 2000): { hz: number; clarity: number } | null {
  const tauMax = Math.floor(rate / minHz)
  const tauMin = Math.max(2, Math.floor(rate / maxHz))
  const w = Math.min(Math.floor(rate * 0.05), x.length - start - tauMax) // 50ms 창
  if (w < tauMax / 2) return null
  const d = new Float32Array(tauMax + 1)
  for (let tau = 1; tau <= tauMax; tau++) {
    let sum = 0
    for (let j = 0; j < w; j++) {
      const diff = x[start + j] - x[start + j + tau]
      sum += diff * diff
    }
    d[tau] = sum
  }
  // 누적 평균으로 나눈 차이 (CMNDF)
  const c = new Float32Array(tauMax + 1)
  c[0] = 1
  let running = 0
  for (let tau = 1; tau <= tauMax; tau++) {
    running += d[tau]
    c[tau] = running > 0 ? (d[tau] * tau) / running : 1
  }
  let best = -1
  for (let tau = tauMin; tau <= tauMax; tau++) {
    if (c[tau] < 0.15) {
      while (tau + 1 <= tauMax && c[tau + 1] < c[tau]) tau++
      best = tau
      break
    }
  }
  if (best < 0) {
    best = tauMin
    for (let tau = tauMin; tau <= tauMax; tau++) if (c[tau] < c[best]) best = tau
    if (c[best] > 0.35) return null
  }
  // 이웃 셋으로 꼭짓점을 다듬는다
  const a = c[best - 1] ?? c[best]
  const b = c[best]
  const z = c[best + 1] ?? c[best]
  const shift = a + z - 2 * b !== 0 ? (a - z) / (2 * (a + z - 2 * b)) : 0
  return { hz: rate / (best + shift), clarity: 1 - b }
}

const toMidi = (hz: number) => 69 + 12 * Math.log2(hz / 440)

/** 소리에서 찾은 음 (MIDI, 소수). 어택 뒤 몇 군데를 재서 가운데 값 — 808처럼 처음에 음이 내려오는 소리도 맞게 */
export function pitchOf(x: Float32Array, rate: number, peakAt: number, audible: number): number | null {
  const found: number[] = []
  for (const after of [0.06, 0.15, 0.3, 0.5, 0.8]) {
    const start = peakAt + Math.round(after * rate)
    if (start > audible) break
    const r = yin(x, start, rate)
    if (r && r.clarity > 0.7) found.push(toMidi(r.hz))
  }
  if (!found.length) return null
  found.sort((p, q) => p - q)
  return found[Math.floor(found.length / 2)]
}

/** 스펙트럼 중심(Hz) — 어택 뒤 0.3초를 몇 조각으로 나눠 평균 (직접 짠 작은 FFT) */
export function centroidOf(x: Float32Array, rate: number, peakAt: number): number {
  const n = 2048
  let weighted = 0
  let total = 0
  for (let k = 0; k < 4; k++) {
    const start = peakAt + k * n
    if (start + n > x.length) break
    const re = new Float32Array(n)
    const im = new Float32Array(n)
    for (let i = 0; i < n; i++) re[i] = x[start + i] * (0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)))
    fft(re, im)
    for (let i = 1; i < n / 2; i++) {
      const mag = Math.hypot(re[i], im[i])
      weighted += mag * ((i * rate) / n)
      total += mag
    }
  }
  return total > 0 ? weighted / total : 0
}

function fft(re: Float32Array, im: Float32Array) {
  const n = re.length
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1
    for (; j & bit; bit >>= 1) j ^= bit
    j ^= bit
    if (i < j) {
      ;[re[i], re[j]] = [re[j], re[i]]
      ;[im[i], im[j]] = [im[j], im[i]]
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len
    for (let i = 0; i < n; i += len) {
      for (let k = 0; k < len / 2; k++) {
        const wr = Math.cos(ang * k)
        const wi = Math.sin(ang * k)
        const ar = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi
        const ai = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr
        re[i + k + len / 2] = re[i + k] - ar
        im[i + k + len / 2] = im[i + k] - ai
        re[i + k] += ar
        im[i + k] += ai
      }
    }
  }
}

/** 소리가 새로 시작하는 곳 수 (50ms 안에 두 배 넘게 커짐) — 프레이즈가 녹음된 루프를 원샷과 가른다 */
function onsets(env: Float32Array, peak: number): number {
  let count = 0
  let lastAt = -100
  for (let f = 5; f < env.length; f++) {
    if (env[f] > peak * 0.1 && env[f] > 2 * env[f - 5] && f - lastAt > 10) {
      count++
      lastAt = f
    }
  }
  return count
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const round = (v: number, digits = 2) => Math.round(v * 10 ** digits) / 10 ** digits

/** 샘플 하나 분석. data는 모노(채널 평균) */
export function analyze(id: string, file: string, folder: string, data: Float32Array, rate: number): SampleMeta {
  const name = file.replace(/\.[a-z0-9]+$/i, '').slice(0, 120)
  const env = rmsFrames(data, rate)
  let peakFrame = 0
  for (let f = 0; f < env.length; f++) if (env[f] > env[peakFrame]) peakFrame = f
  const peak = env[peakFrame]
  const base = { id, name, folder, gain: 1, rootFrom: null, kindFrom: 'audio' } as const
  if (peak < 1e-4) return { ...base, kind: 'other', root: null, length: 0, sustained: false, brightness: 0 }

  let lastFrame = peakFrame
  for (let f = env.length - 1; f > peakFrame; f--) {
    if (env[f] > peak * 0.01) {
      lastFrame = f
      break
    }
  }
  const length = (lastFrame + 1) * FRAME_S
  const oneSecond = peakFrame + Math.round(1 / FRAME_S)
  const sustained = length >= 1.5 && oneSecond < env.length && env[oneSecond] >= peak * 0.5
  // 어택 뒤 0.3초 크기를 GM 악기(FluidR3) 크기쯤으로 맞춘다. 0.18로 두었더니 같은 트랙의 GM 악기보다 7~16dB 컸고,
  // 0.05면 합성 테스트 팩에서 -4 ~ +5dB (길게 끌리는 패드가 조금 크다)
  let loud = 0
  const until = Math.min(env.length, peakFrame + 30)
  for (let f = peakFrame; f < until; f++) loud += env[f] * env[f]
  const rms = Math.sqrt(loud / Math.max(1, until - peakFrame))
  const gain = round(clamp(0.05 / rms, 0.02, 4), 3)

  const peakAt = peakFrame * Math.round(rate * FRAME_S)
  const centroid = centroidOf(data, rate, peakAt)
  const brightness = round(clamp((Math.log2(Math.max(centroid, 1)) - Math.log2(200)) / (Math.log2(5000) - Math.log2(200)), 0, 1))

  const heard = pitchOf(data, rate, peakAt, (lastFrame + 1) * Math.round(rate * FRAME_S))
  const named = noteFromName(file)
  let root: number | null = null
  let rootFrom: SampleMeta['rootFrom'] = null
  if (named && heard !== null) {
    // 이름의 음 이름에 가장 가까운, 소리의 옥타브
    root = Math.round(heard) + ((((named.pc - Math.round(heard)) % 12) + 18) % 12) - 6
    rootFrom = 'name'
  } else if (named && named.octave !== null) {
    root = clamp(named.pc + (named.octave + 1) * 12, 0, 127)
    rootFrom = 'name'
  } else if (heard !== null) {
    root = clamp(Math.round(heard), 0, 127)
    rootFrom = 'audio'
  }

  // 파일 이름이 폴더보다 구체적이다 ("One Shots" 폴더 안의 "Melody Loop"는 루프)
  let kind = kindFromName(name) ?? kindFromName(folder)
  let kindFrom: SampleMeta['kindFrom'] = 'name'
  if (!kind) {
    kindFrom = 'audio'
    if (root === null) kind = length < 1 ? 'drum' : 'other'
    else if (length > 3 && onsets(env, peak) >= 4) kind = 'loop'
    else if (root < 48) kind = 'bass'
    else if (sustained) kind = 'pad'
    else if (length < 0.8) kind = 'pluck'
    else if (brightness > 0.65 && length > 1.5) kind = 'bell'
    else kind = 'keys'
  }
  return { ...base, kind, kindFrom, root, rootFrom, length: round(length), sustained, brightness, gain }
}
