// 내 샘플(원샷 WAV) 하나를 읽어 이름표를 만든다: 종류 · 기준음 · 길이 · 밝기 · 크기 보정.
// 순수 함수만 둔다 (브라우저 API 없이 Node에서도 돌려 볼 수 있게 — 다른 파일을 import하지 않는다).
//
// 순서: 파일 · 폴더 이름을 먼저 보고(시판 샘플팩은 거의 "Pluck_C3", "808 - F#"처럼 이름이 붙어 있다),
// 이름으로 모르는 것만 소리 모양으로 정한다. 음 높이는 이름의 음 이름(C, F# …)을 믿고 옥타브는 소리에서 찾는다 —
// 옥타브 숫자는 DAW마다 달라서(Ableton · Logic은 가운데 C = C3, FL은 C5) 이름만으로는 한 옥타브씩 틀린다.

export type SampleKind = 'bass' | 'keys' | 'pluck' | 'pad' | 'lead' | 'bell' | 'chord' | 'loop' | 'drum' | 'other'

/** 드럼 원샷의 역할 (backend app/tools/drums.py ROLES와 같은 이름 + 퍼커션) */
export type DrumRole = 'kick' | 'snare' | 'clap' | 'hat' | 'openhat' | 'tom' | 'crash' | 'ride' | 'perc'

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
  /** 샘플끼리 크기를 맞추려고 곱할 값 (멜로디 악기용 — 어택 뒤 0.3초 크기 기준) */
  gain: number
  /** 가장 큰 소리 (0~1). 드럼은 짧아서 평균 대신 이걸로 크기를 맞춘다 */
  peak: number
  /** 드럼 원샷이면 역할, 아니면 null */
  drum: DrumRole | null
  /** 분석 규칙 버전. ANALYSIS_VERSION과 다르면 다시 분석한다 (samples/library.ts) */
  v: number
  /** 루프만: 녹음된 리듬 (치는 자리 · 세기 · 열림). 하이햇 트랙으로 옮길 때 쓴다 (backend groove_from_loop) */
  groove?: Groove | null
  /** 기준음 · 종류를 어디서 알았는지 (화면 표시 · 사용자가 고쳤는지) */
  rootFrom: 'name' | 'audio' | 'user' | null
  kindFrom: 'name' | 'audio' | 'user'
}

export const KIND_NAMES: Record<SampleKind, string> = {
  bass: '베이스', keys: '건반', pluck: '플럭', pad: '패드', lead: '리드', bell: '벨',
  chord: '코드 원샷', loop: '루프', drum: '드럼', other: '기타 소리',
}

export const DRUM_ROLE_NAMES: Record<DrumRole, string> = {
  kick: '킥', snare: '스네어', clap: '클랩', hat: '닫힌 햇', openhat: '열린 햇', tom: '탐', crash: '크래시', ride: '라이드', perc: '퍼커션',
}

/** 음 하나를 높이고 낮춰 악기로 쓸 수 있는 종류 (코드 원샷 · 루프는 음이 겹쳐 들린다) */
export const PLAYABLE: SampleKind[] = ['bass', 'keys', 'pluck', 'pad', 'lead', 'bell']

/** 분석 규칙을 바꾸면 올린다 → 이미 넣은 샘플도 다음에 열 때 다시 분석 (2: 드럼 역할 · 최대 크기, 3: 루프를 드럼보다 먼저) */
export const ANALYSIS_VERSION = 7 // 4: 루프의 리듬(groove), 5: 1마디짜리 짧은 루프도 루프로, 6: 드럼 루프에서 하이햇만 · 자르는 자리 따로, 7: 킥과 같이 친 하이햇도

/** 루프에 녹음된 리듬 — 격자에 맞추지 않은 그대로.
 * hits: 하이햇 타격 [루프 안 박, 세기 1~127, 열림(오래 울림) 1 · 아님 0]. cuts: 모든 타격의 박 (오디오로 깔 때 자르는 자리) */
export interface Groove {
  bpm: number
  beats: number
  hits: [beat: number, velocity: number, open: 0 | 1][]
  cuts?: number[]
}

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
export const noteName = (pitch: number) => `${NOTE_NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`

// ---------- 이름 ----------

// 앞에 있을수록 먼저 (루프 · 드럼 · 코드를 먼저 걸러야 "Bass Loop"가 베이스 원샷이 되지 않는다).
// 루프가 드럼보다 먼저: "Hi Hat Loop 140"을 하이햇 원샷으로 보면 칠 때마다 몇 초짜리 패턴이 통째로 겹쳐 울렸다
const KIND_WORDS: [SampleKind, RegExp][] = [
  ['loop', /loop|\bmelod(y|ic)\b|\briff\b|phrase|\b\d{2,3} ?bpm\b|\bbpm ?\d{2,3}\b/],
  ['drum', /kick|snare|clap|bass ?drum|\bdrums?\b|hi ?hats?|\bhats?\b|open ?hh|\bhh\b|\boh\b|cymbal|crash|\bride\b|\bperc|\btoms?\b|\brim\b|shaker|\bsnap\b|\bkck\b|\bsd\b|\bbd\b/],
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

// 열린 햇을 닫힌 햇보다 먼저 ("Open Hat"이 "hat"에 걸리지 않게)
const DRUM_WORDS: [DrumRole, RegExp][] = [
  ['openhat', /open ?(hi ?)?hats?|\boh\b|open ?hh/],
  ['hat', /hi ?hats?|\bhh\b|\bch\b|closed|\bhats?\b/],
  ['kick', /kick|\bkck\b|\bbd\b|bass ?drum/],
  ['snare', /snare|\bsd\b|\brim/],
  ['clap', /clap|\bsnap/],
  ['crash', /crash|cymbal|splash|china/],
  ['ride', /\bride/],
  ['tom', /\btoms?\b/],
  ['perc', /perc|shaker|tamb|conga|bongo|cowbell|wood ?block|clave|triangle/],
]

/** 이름에서 드럼 역할. 못 찾으면 null */
export function drumFromName(text: string): DrumRole | null {
  const t = text.toLowerCase().replace(/[_\-.()[\]]+/g, ' ')
  return DRUM_WORDS.find(([, re]) => re.test(t))?.[0] ?? null
}

/** 이름으로 모르는 드럼 원샷: 어두우면 킥, 밝으면 짧으면 햇 · 길면 크래시, 그 사이는 스네어 */
function drumFromSound(brightness: number, length: number): DrumRole {
  if (brightness < 0.2) return 'kick'
  if (brightness > 0.75) return length > 0.8 ? 'crash' : 'hat'
  return 'snare'
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
const GROOVE_HOP_S = 0.005
const MAX_HITS = 128

/** 이름의 템포: "140 BPM" · "BPM140" · 맨 숫자 60~200 ("Hat Loop 140") */
export function bpmFromName(name: string): number | null {
  const t = name.toLowerCase()
  const m = t.match(/(\d{2,3}) ?bpm|bpm ?(\d{2,3})/)
  const n = Number(m?.[1] ?? m?.[2] ?? t.split(/[^0-9]+/).find((x) => Number(x) >= 60 && Number(x) <= 200))
  return n >= 60 && n <= 200 ? n : null
}

// 2차 필터 (RBJ 쿡북) — 소리를 대역으로 나눠 하이햇을 킥 · 스네어와 가른다
function biquad(x: Float32Array, rate: number, type: 'highpass' | 'bandpass', freq: number, q = 0.707): Float32Array {
  const w = (2 * Math.PI * freq) / rate
  const cos = Math.cos(w)
  const alpha = Math.sin(w) / (2 * q)
  const [b0, b1, b2] = type === 'highpass' ? [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2] : [alpha, 0, -alpha]
  const [a0, a1, a2] = [1 + alpha, -2 * cos, 1 - alpha]
  const y = new Float32Array(x.length)
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0
  for (let i = 0; i < x.length; i++) {
    const v = (b0 * x[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0
    x2 = x1
    x1 = x[i]
    y2 = y1
    y1 = v
    y[i] = v
  }
  return y
}

function envelope(x: Float32Array, hop: number): Float32Array {
  const env = new Float32Array(Math.ceil(x.length / hop))
  for (let f = 0; f < env.length; f++) {
    let sum = 0
    const end = Math.min(x.length, (f + 1) * hop)
    for (let i = f * hop; i < end; i++) sum += x[i] * x[i]
    env[f] = Math.sqrt(sum / Math.max(1, end - f * hop))
  }
  return env
}

const HOLD_DECAY = 0.9 // 5ms마다. 방금 친 소리의 크기 기억이 50ms에 1/3쯤으로 준다
const MIN_GAP = 8 // 프레임(40ms). 이보다 붙은 타격은 하나로

/** 타격 시작 프레임: 방금 친 소리 크기(천천히 줄어드는 기억)보다 1.5배 넘게 커질 때만. 직전 4프레임과만 비교했더니
 * 킥 · 스네어의 울림 꼬리가 흔들릴 때마다 새 타격으로 잡혀 0 · 0.12 · 0.26박처럼 다닥다닥 붙었다 */
function hitsIn(env: Float32Array, floor: number): number[] {
  const out: number[] = []
  let held = 0
  for (let f = 0; f < env.length; f++) {
    if (env[f] >= floor && env[f] > held * 1.5 + 1e-6 && (!out.length || f - out[out.length - 1] >= MIN_GAP)) out.push(f)
    held = Math.max(env[f], held * HOLD_DECAY)
  }
  return out
}

const energy = (env: Float32Array, f: number, n = 6) => {
  let s = 0
  for (let j = f; j < Math.min(env.length, f + n); j++) s = Math.max(s, env[j])
  return s
}

const HAT_HIGH = 7000 // Hz. 하이햇은 이 위가 대부분
const UPPER_MID = 3000 // Hz. 스네어의 쇳소리는 여기가 세다
const HAT_RATIO = 1.2 // 높은 대역 / 중고역이 이보다 크면 하이햇
const WITH_SNARE = 0.65 // 킥 · 스네어와 같은 순간이어도 높은 대역이 다른 하이햇의 이만큼이면 하이햇도 함께 친 것 (0.8은 킥과 같이 친 하이햇을 놓쳤다)

/**
 * 루프의 리듬 읽기. 드럼 루프에는 킥 · 스네어 · 하이햇이 섞여 있어서(처음에는 그걸 다 하이햇으로 옮겼다) 대역을 나눈다:
 * - 하이햇: 7kHz 위 대역에서 커지는 곳. 그 순간 중고역(3kHz 근처)이 더 세면 스네어로 보고 빼되, 높은 대역이 다른 하이햇만큼 세면
 *   하이햇도 같이 친 것 (2 · 4박의 스네어 + 하이햇).
 * - cuts: 대역을 가리지 않은 모든 타격 — 오디오로 깔 때 이 자리마다 자른다 (킥 · 스네어 자리에서도 끊기지 않게).
 * 세기는 그 하이햇의 높은 대역 크기, 열림은 높은 대역이 150ms 넘게 울림. 템포는 이름에서, 없으면 파일 길이가 1 · 2 · 4 · 8 · 16마디라고
 * 보고 85~170 BPM에 드는 것으로 (한 옥타브라 하나로 정해진다).
 */
export function grooveOf(data: Float32Array, rate: number, name: string): Groove | null {
  const hop = Math.max(1, Math.round(rate * GROOVE_HOP_S))
  const full = envelope(data, hop)
  let peak = 0
  for (const v of full) peak = Math.max(peak, v)
  if (peak < 1e-4) return null
  const seconds = data.length / rate
  const named = bpmFromName(name)
  const bars = [1, 2, 4, 8, 16].find((b) => (b * 240) / seconds >= 85 && (b * 240) / seconds < 170)
  const bpm = named ?? (bars ? Math.round(((bars * 240) / seconds) * 10) / 10 : null)
  if (!bpm) return null
  let beats = (seconds * bpm) / 60
  if (Math.abs(beats / 4 - Math.round(beats / 4)) < 0.05) beats = Math.round(beats / 4) * 4 // 마디 단위로 잘린 루프
  const beatOf = (f: number) => round((f * hop * bpm) / 60 / rate, 3)

  const cuts = hitsIn(full, peak * 0.06).map(beatOf).filter((b) => b < beats - 1e-3).slice(0, MAX_HITS)
  if (cuts.length < 2) return null

  const high = envelope(biquad(biquad(data, rate, 'highpass', HAT_HIGH), rate, 'highpass', HAT_HIGH), hop)
  const mid = envelope(biquad(data, rate, 'bandpass', UPPER_MID, 0.9), hop)
  let highPeak = 0
  for (const v of high) highPeak = Math.max(highPeak, v)
  const candidates = highPeak > peak * 0.01 ? hitsIn(high, highPeak * 0.1) : []
  const ratio = (f: number) => energy(high, f) / Math.max(energy(mid, f), 1e-9)
  const clear = candidates.filter((f) => ratio(f) >= HAT_RATIO)
  const typical = clear.map((f) => energy(high, f)).sort((a, b) => a - b)[Math.floor(clear.length / 2)] ?? Infinity
  const hats = candidates.filter((f) => ratio(f) >= HAT_RATIO || energy(high, f) >= typical * WITH_SNARE)
  let hatPeak = 0
  for (const f of hats) hatPeak = Math.max(hatPeak, energy(high, f))
  const hits: Groove['hits'] = hats.slice(0, MAX_HITS).map((f, k) => {
    const next = hats[k + 1] ?? high.length
    const top = energy(high, f)
    let ring = f
    while (ring < next && high[ring] > top * 0.3) ring++
    const open: 0 | 1 = (ring - f) * GROOVE_HOP_S > 0.15 ? 1 : 0
    return [beatOf(f), Math.max(1, Math.min(127, Math.round(30 + 97 * (top / hatPeak)))), open]
  })
  return { bpm, beats: round(beats, 3), hits: hits.filter(([b]) => b < beats - 1e-3), cuts }
}

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
  let top = 0
  for (let i = 0; i < data.length; i++) top = Math.max(top, Math.abs(data[i]))
  const base = { id, name, folder, gain: 1, peak: round(top, 3), v: ANALYSIS_VERSION, rootFrom: null, kindFrom: 'audio' } as const
  if (peak < 1e-4) return { ...base, kind: 'other', root: null, length: 0, sustained: false, brightness: 0, drum: null }

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
  // 소리가 여러 번 새로 시작하는 긴 파일은 패턴이 녹음된 루프 (이름에 loop · bpm이 없어도 — 예: Drums 폴더의 "Hat 03")
  // 1초: 140 BPM 1마디 하이햇 루프(1.7초)가 2초 기준에 걸리지 않아 원샷으로 남았고, 레인에서 칠 때마다 앞부분만 잘려 쪼개진 소리가 났다
  const phrase = length > 1 && onsets(env, peak) >= 4
  if (kind === 'drum' && phrase) {
    kind = 'loop'
    kindFrom = 'audio'
  }
  if (!kind) {
    kindFrom = 'audio'
    if (phrase && (root === null || length > 3)) kind = 'loop' // 음이 있는 소리는 더 길 때만 (떨림이 있는 패드를 루프로 보지 않게)
    else if (root === null) kind = length < 1 ? 'drum' : 'other'
    else if (root < 48 && length < 0.6) kind = 'drum' // 낮고 짧게 끝나는 소리는 베이스 원샷보다 킥 (808 · 베이스는 꼬리가 길다)
    else if (root < 48) kind = 'bass'
    else if (sustained) kind = 'pad'
    else if (length < 0.8) kind = 'pluck'
    else if (brightness > 0.65 && length > 1.5) kind = 'bell'
    else kind = 'keys'
  }
  const drum = kind === 'drum' ? (drumFromName(name) ?? drumFromName(folder) ?? drumFromSound(brightness, length)) : null
  const groove = kind === 'loop' ? grooveOf(data, rate, name) : null
  return { ...base, kind, kindFrom, root, rootFrom, length: round(length), sustained, brightness, gain, drum, groove }
}
