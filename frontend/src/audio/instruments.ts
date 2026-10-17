import * as Tone from 'tone'
import type { Track } from '../api/types'

// 트랙 하나의 소리를 내는 단위.
// 기본은 실제 악기 샘플(멜로디: FluidR3 GM, 드럼: Sonic Pi 샘플)이고,
// 샘플을 못 불러오면 예전 Tone.js 신스 소리로 대신한다.
export interface Voice {
  output: Tone.ToneAudioNode
  /** 샘플 준비가 끝나면 끝난다. 실패해도 reject하지 않고 신스로 바꾼 뒤 끝난다. */
  ready: Promise<void>
  /** 샘플을 못 불러와 신스로 대신하는 중인지 */
  fallback: boolean
  /** duration은 Tone.js 시간 문자열 (예: "96i" = 96틱) */
  play(pitch: number, duration: string, time: number, velocity: number): void
  releaseAll(): void
  dispose(): void
  /** 드럼만: 이 소리(음 번호)를 잠깐 키우거나 줄인다 (레인 슬라이더를 끄는 동안 들으며 맞추기) */
  setLaneGain?(pitch: number, gain: number): void
}

export function createVoice(track: Track): Voice {
  return track.is_drum ? new SampledDrumVoice(track) : new SampledVoice(track)
}

const LOAD_TIMEOUT_MS = 15000

/** 샘플 로딩을 기다린다. 실패하거나 너무 오래 걸리면 false. */
function waitLoad(start: (done: () => void, fail: () => void) => void): Promise<boolean> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), LOAD_TIMEOUT_MS)
    const finish = (ok: boolean) => {
      clearTimeout(timer)
      resolve(ok)
    }
    start(() => finish(true), () => finish(false))
  })
}

// ---------- 멜로디 악기 (FluidR3 GM, CC BY 3.0) ----------

const FLUID_URL = 'https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM/'

// General MIDI 악기 번호 순서 (FluidR3 GM 파일 이름)
const GM_NAMES = [
  'acoustic_grand_piano', 'bright_acoustic_piano', 'electric_grand_piano', 'honkytonk_piano', 'electric_piano_1', 'electric_piano_2', 'harpsichord', 'clavinet',
  'celesta', 'glockenspiel', 'music_box', 'vibraphone', 'marimba', 'xylophone', 'tubular_bells', 'dulcimer',
  'drawbar_organ', 'percussive_organ', 'rock_organ', 'church_organ', 'reed_organ', 'accordion', 'harmonica', 'tango_accordion',
  'acoustic_guitar_nylon', 'acoustic_guitar_steel', 'electric_guitar_jazz', 'electric_guitar_clean', 'electric_guitar_muted', 'overdriven_guitar', 'distortion_guitar', 'guitar_harmonics',
  'acoustic_bass', 'electric_bass_finger', 'electric_bass_pick', 'fretless_bass', 'slap_bass_1', 'slap_bass_2', 'synth_bass_1', 'synth_bass_2',
  'violin', 'viola', 'cello', 'contrabass', 'tremolo_strings', 'pizzicato_strings', 'orchestral_harp', 'timpani',
  'string_ensemble_1', 'string_ensemble_2', 'synth_strings_1', 'synth_strings_2', 'choir_aahs', 'voice_oohs', 'synth_choir', 'orchestra_hit',
  'trumpet', 'trombone', 'tuba', 'muted_trumpet', 'french_horn', 'brass_section', 'synth_brass_1', 'synth_brass_2',
  'soprano_sax', 'alto_sax', 'tenor_sax', 'baritone_sax', 'oboe', 'english_horn', 'bassoon', 'clarinet',
  'piccolo', 'flute', 'recorder', 'pan_flute', 'blown_bottle', 'shakuhachi', 'whistle', 'ocarina',
  'lead_1_square', 'lead_2_sawtooth', 'lead_3_calliope', 'lead_4_chiff', 'lead_5_charang', 'lead_6_voice', 'lead_7_fifths', 'lead_8_bass__lead',
  'pad_1_new_age', 'pad_2_warm', 'pad_3_polysynth', 'pad_4_choir', 'pad_5_bowed', 'pad_6_metallic', 'pad_7_halo', 'pad_8_sweep',
  'fx_1_rain', 'fx_2_soundtrack', 'fx_3_crystal', 'fx_4_atmosphere', 'fx_5_brightness', 'fx_6_goblins', 'fx_7_echoes', 'fx_8_scifi',
  'sitar', 'banjo', 'shamisen', 'koto', 'kalimba', 'bagpipe', 'fiddle', 'shanai',
  'tinkle_bell', 'agogo', 'steel_drums', 'woodblock', 'taiko_drum', 'melodic_tom', 'synth_drum', 'reverse_cymbal',
  'guitar_fret_noise', 'breath_noise', 'seashore', 'bird_tweet', 'telephone_ring', 'helicopter', 'applause', 'gunshot',
]

// FL Studio에서 내보낸 파일은 악기 번호가 전부 0인 경우가 많아서, 0이면 트랙 이름으로 악기를 고른다.
const NAME_HINTS: [RegExp, number][] = [
  [/808/, 38], // 808 베이스 → synth_bass_1
  [/sub|bass|베이스/, 33],
  [/rhodes|e\.?\s?piano|\bep\b|wurli|keys|건반/, 4],
  [/organ|오르간/, 16],
  [/pluck|guitar|gtr|기타/, 27],
  [/string|violin|cello|현악/, 48],
  [/choir|vox|voice|코러스/, 52],
  [/brass|horn|trumpet/, 61],
  [/flute|플룻/, 73],
  [/bell|glock|chime/, 9],
  [/pad|패드|atmo/, 89],
  [/lead|synth|리드/, 81],
]

export function gmProgramOf(track: Track): number {
  if (track.program !== 0 || track.program_set) return track.program
  const name = track.name.toLowerCase()
  return NAME_HINTS.find(([re]) => re.test(name))?.[1] ?? 0
}

// FluidR3 파일은 플랫 이름을 쓴다 (Db4.mp3, Eb4.mp3 …). A0(21) ~ C8(108)
const FLAT_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
const fileOf = (pitch: number) => `${FLAT_NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}.mp3`

/** 트랙 음역(위아래 3반음 여유)에서 3반음마다 하나씩만 불러온다. 사이 음은 Sampler가 가까운 샘플의 음높이를 바꿔 낸다. */
function sampleUrls(track: Track): Record<string, string> {
  const pitches = track.notes.length ? track.notes.map((n) => n.pitch) : [60] // 음을 다 지운 트랙
  const low = Math.max(21, Math.min(...pitches) - 3)
  const high = Math.min(108, Math.max(...pitches) + 3)
  const urls: Record<string, string> = {}
  for (let p = low; p <= high; p += 3) urls[p] = fileOf(p)
  urls[high] = fileOf(high)
  return urls
}

class SampledVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  private sampler: Tone.Sampler | null = null
  private synth: SynthVoice | null = null

  constructor(track: Track) {
    const program = gmProgramOf(track)
    this.ready = waitLoad((done, fail) => {
      this.sampler = new Tone.Sampler({
        urls: sampleUrls(track),
        baseUrl: `${FLUID_URL}${GM_NAMES[program]}-mp3/`,
        release: 0.8,
        onload: done,
        onerror: fail,
      }).connect(this.output)
    }).then((ok) => {
      if (ok) return
      this.sampler?.dispose()
      this.sampler = null
      this.synth = new SynthVoice(presetOf(program))
      this.synth.output.connect(this.output)
      this.fallback = true
    })
  }

  play(pitch: number, duration: string, time: number, velocity: number) {
    if (this.sampler?.loaded) {
      this.sampler.triggerAttackRelease(Tone.Frequency(pitch, 'midi').toFrequency(), duration, time, velocity / 127)
    } else {
      this.synth?.play(pitch, duration, time, velocity)
    }
  }

  releaseAll() {
    this.sampler?.releaseAll()
    this.synth?.releaseAll()
  }

  dispose() {
    this.sampler?.dispose()
    this.synth?.dispose()
    this.output.dispose()
  }
}

// ---------- 드럼 (Sonic Pi 샘플, CC0 · public/samples/drums) ----------

// 피아노롤 드럼 레인에 보여 줄 이름 (General MIDI 기준)
export const DRUM_NAMES: Record<number, string> = {
  35: 'Kick 2', 36: 'Kick', 37: 'Side Stick', 38: 'Snare', 39: 'Clap', 40: 'Snare 2',
  41: 'Floor Tom 2', 42: 'Closed Hat', 43: 'Floor Tom', 44: 'Pedal Hat', 45: 'Low Tom',
  46: 'Open Hat', 47: 'Low-Mid Tom', 48: 'Hi-Mid Tom', 49: 'Crash', 50: 'High Tom',
  51: 'Ride', 52: 'China', 53: 'Ride Bell', 54: 'Tambourine', 55: 'Splash', 56: 'Cowbell',
  57: 'Crash 2', 59: 'Ride 2',
}

// [샘플 파일, 재생 속도, 크기(기본 1)]
type DrumSample = [file: string, rate: number, gain?: number]

export type DrumRole = 'kick' | 'snare' | 'clap' | 'hat' | 'openhat' | 'tom' | 'crash' | 'ride'

// GM 드럼 번호 → 역할 (백엔드 app/tools/drums.py ROLES와 같음). 같은 역할끼리만 소리를 바꿀 수 있다
export const DRUM_ROLES: Record<number, DrumRole> = {
  35: 'kick', 36: 'kick', 37: 'snare', 38: 'snare', 40: 'snare', 39: 'clap',
  42: 'hat', 44: 'hat', 46: 'openhat',
  41: 'tom', 43: 'tom', 45: 'tom', 47: 'tom', 48: 'tom', 50: 'tom',
  49: 'crash', 52: 'crash', 55: 'crash', 57: 'crash', 51: 'ride', 53: 'ride', 59: 'ride',
}

const TOMS = [41, 43, 45, 47, 48, 50] // 낮은 탐 → 높은 탐
// 탐 소리는 탐 6개(TOMS 순서)에 각각 샘플 · 속도를 둬서 높낮이를 나눈다
const toms = (file: string, rates: number[], gain = 1): DrumSample[] => rates.map((r) => [file, r, gain])

/**
 * 드럼 소리 목록 (백엔드 app/tools/drums.py DRUM_SOUNDS와 같은 id · 이름, 테스트가 확인).
 * 샘플은 모두 Sonic Pi CC0. 고른 기준: 길이 · 밝기(스펙트럼 중심) · 저역 비율을 재서 비교 (docs/devlog.md v0.1-16 · 19).
 */
export const DRUM_SOUNDS: Record<string, { name: string; role: DrumRole; sample: DrumSample | DrumSample[] }> = {
  kick_acoustic: { name: '어쿠스틱 킥', role: 'kick', sample: ['drum_heavy_kick', 1] },
  kick_soft: { name: '부드러운 킥', role: 'kick', sample: ['drum_bass_soft', 1] },
  kick_punch: { name: '펀치 킥', role: 'kick', sample: ['bd_klub', 1, 0.7] },
  kick_808: { name: '808 킥', role: 'kick', sample: ['bd_808', 1] },
  kick_house: { name: '하우스 킥', role: 'kick', sample: ['bd_haus', 1, 0.7] },
  kick_lofi: { name: '둥근 로파이 킥', role: 'kick', sample: ['bd_gas', 1] },
  kick_boombap: { name: '붐뱁 킥', role: 'kick', sample: ['bd_fat', 1, 1.6] },
  kick_electro: { name: '일렉 킥', role: 'kick', sample: ['elec_soft_kick', 1, 0.7] },
  snare_acoustic: { name: '어쿠스틱 스네어', role: 'snare', sample: ['drum_snare_hard', 1] },
  snare_soft: { name: '부드러운 스네어', role: 'snare', sample: ['drum_snare_soft', 1] },
  snare_big: { name: '큰 스네어', role: 'snare', sample: ['sn_dolf', 1, 0.7] },
  snare_lofi: { name: '먹먹한 스네어', role: 'snare', sample: ['sn_dub', 0.95, 0.7] },
  snare_909: { name: '909 스네어', role: 'snare', sample: ['sn_generic', 1, 0.8] },
  snare_boombap: { name: '붐뱁 스네어', role: 'snare', sample: ['sn_zome', 1, 0.75] },
  snare_electro: { name: '일렉 스네어', role: 'snare', sample: ['elec_snare', 1] },
  snare_808: { name: '808 스네어', role: 'snare', sample: ['elec_hi_snare', 1] },
  clap: { name: '클랩', role: 'clap', sample: ['perc_snap', 1] },
  clap_909: { name: '909 클랩', role: 'clap', sample: ['perc_snap2', 1, 0.7] },
  hat_acoustic: { name: '어쿠스틱 하이햇', role: 'hat', sample: ['drum_cymbal_closed', 1] },
  hat_808: { name: '808 하이햇', role: 'hat', sample: ['hat_bdu', 1] },
  hat_909: { name: '909 하이햇', role: 'hat', sample: ['hat_raw', 1] },
  hat_soft: { name: '작고 부드러운 하이햇', role: 'hat', sample: ['hat_tap', 1, 2.5] },
  hat_crisp: { name: '또렷한 하이햇', role: 'hat', sample: ['hat_zild', 1] },
  hat_electro: { name: '일렉 하이햇', role: 'hat', sample: ['hat_sci', 1] },
  openhat_acoustic: { name: '어쿠스틱 오픈햇', role: 'openhat', sample: ['drum_cymbal_open', 1] },
  openhat_808: { name: '808 오픈햇', role: 'openhat', sample: ['hat_len', 1] },
  openhat_909: { name: '909 오픈햇', role: 'openhat', sample: ['hat_gump', 1, 0.8] },
  openhat_soft: { name: '부드러운 오픈햇', role: 'openhat', sample: ['hat_cats', 1, 1.5] },
  openhat_electro: { name: '일렉 오픈햇', role: 'openhat', sample: ['hat_noiz', 1] },
  tom_acoustic: {
    name: '어쿠스틱 탐', role: 'tom',
    sample: [['drum_tom_lo_hard', 0.9], ['drum_tom_lo_hard', 1], ['drum_tom_mid_hard', 0.95], ['drum_tom_mid_hard', 1.05], ['drum_tom_hi_hard', 0.95], ['drum_tom_hi_hard', 1.05]],
  },
  tom_deep: {
    name: '낮고 큰 탐', role: 'tom',
    sample: [['drum_tom_lo_hard', 0.82], ['drum_tom_lo_hard', 0.9], ['drum_tom_mid_hard', 0.82], ['drum_tom_mid_hard', 0.9], ['drum_tom_hi_hard', 0.82], ['drum_tom_hi_hard', 0.9]],
  },
  // 둥글고 낮은 킥(bd_gas)을 높여서 쓰는 부드러운 탐
  tom_round: { name: '둥근 로파이 탐', role: 'tom', sample: toms('bd_gas', [1.5, 1.7, 1.9, 2.15, 2.4, 2.7]) },
  tom_808: { name: '808 탐', role: 'tom', sample: toms('bd_pure', [1.6, 1.9, 2.2, 2.5, 2.8, 3.1]) },
  tom_electro: { name: '일렉 탐', role: 'tom', sample: toms('elec_fuzz_tom', [0.75, 0.85, 0.95, 1.05, 1.15, 1.25], 0.8) },
  crash_acoustic: { name: '어쿠스틱 크래시', role: 'crash', sample: ['drum_cymbal_hard', 1] },
  crash_splash: { name: '스플래시', role: 'crash', sample: ['drum_splash_hard', 1] },
  crash_electro: { name: '일렉 심벌', role: 'crash', sample: ['elec_cymbal', 1] },
  ride_acoustic: { name: '어쿠스틱 라이드', role: 'ride', sample: ['drum_cymbal_soft', 1] },
  ride_jazz: { name: '재즈 라이드', role: 'ride', sample: ['ride_via', 1, 1.5] },
  ride_bright: { name: '밝은 라이드', role: 'ride', sample: ['ride_tri', 1, 1.3] },
}

/** 고를 수 있는 드럼 킷 (GM 드럼 킷 번호, 백엔드 app/tools/instrument.py DRUM_KITS와 같은 목록).
 *  8 · 32는 GM2 표준 번호, 26~28은 이 앱 전용 (DAW에서는 각 DAW 드럼 소리로 열림) */
export const DRUM_KITS: { program: number; name: string }[] = [
  { program: 0, name: '스탠다드' },
  { program: 8, name: '룸' },
  { program: 16, name: '파워' },
  { program: 24, name: '일렉트로닉' },
  { program: 25, name: 'TR-808' },
  { program: 26, name: '하우스 (909)' },
  { program: 27, name: '로파이' },
  { program: 28, name: '붐뱁' },
  { program: 32, name: '재즈' },
]

export const kitName = (program: number) => DRUM_KITS.find((k) => k.program === program)?.name ?? '스탠다드'
export const kitOf = (program: number) => (DRUM_KITS.some((k) => k.program === program) ? program : 0)

// 킷 = 역할마다 어떤 소리를 쓸지. 모든 킷이 8가지 역할을 다 채운다
type Kit = Record<DrumRole, string>
const STANDARD: Kit = {
  kick: 'kick_acoustic', snare: 'snare_acoustic', clap: 'clap', hat: 'hat_acoustic', openhat: 'openhat_acoustic',
  tom: 'tom_acoustic', crash: 'crash_acoustic', ride: 'ride_acoustic',
}
const KITS: Record<number, Kit> = {
  0: STANDARD,
  8: STANDARD, // 룸: 같은 소리 + 방 울림 (KIT_FX)
  16: { ...STANDARD, kick: 'kick_punch', snare: 'snare_big', tom: 'tom_deep' },
  24: {
    kick: 'kick_electro', snare: 'snare_electro', clap: 'clap_909', hat: 'hat_electro', openhat: 'openhat_electro',
    tom: 'tom_electro', crash: 'crash_electro', ride: 'ride_bright',
  },
  25: {
    kick: 'kick_808', snare: 'snare_808', clap: 'clap', hat: 'hat_808', openhat: 'openhat_808',
    tom: 'tom_808', crash: 'crash_electro', ride: 'ride_bright',
  },
  26: {
    kick: 'kick_house', snare: 'snare_909', clap: 'clap_909', hat: 'hat_909', openhat: 'openhat_909',
    tom: 'tom_808', crash: 'crash_electro', ride: 'ride_bright',
  },
  27: {
    kick: 'kick_lofi', snare: 'snare_lofi', clap: 'clap', hat: 'hat_soft', openhat: 'openhat_soft',
    tom: 'tom_round', crash: 'crash_splash', ride: 'ride_jazz',
  },
  28: { ...STANDARD, kick: 'kick_boombap', snare: 'snare_boombap', hat: 'hat_crisp', tom: 'tom_deep' },
  32: { ...STANDARD, kick: 'kick_soft', snare: 'snare_soft', crash: 'crash_splash', ride: 'ride_jazz' },
}

/** 레인(음 번호)에서 지금 나는 소리 id: 따로 고른 소리, 없으면 킷 소리 */
export function drumSoundOf(program: number, pitch: number, picked: Record<string, string> = {}): string | null {
  const role = DRUM_ROLES[pitch]
  if (!role) return null
  return picked[pitch] ?? KITS[kitOf(program)][role]
}

// 같은 역할 안에서 번호마다 살짝 다르게 (Kick 2는 조금 낮게, 사이드 스틱은 작고 높게 …)
const PITCH_TWEAK: Record<number, [rate: number, gain: number]> = {
  35: [0.95, 1], 37: [1.1, 0.6], 40: [1.05, 1], 44: [0.9, 0.9], 52: [0.9, 1], 55: [1.15, 0.8], 57: [1.05, 1], 53: [1.2, 1], 59: [0.95, 1],
}
const DRUM_DEFAULT: DrumSample = ['drum_cymbal_closed', 1] // 역할이 없는 번호 (탬버린 · 카우벨 등)

function drumSample(program: number, pitch: number, picked: Record<string, string>): DrumSample {
  const id = drumSoundOf(program, pitch, picked)
  const sound = id ? DRUM_SOUNDS[id] : undefined
  if (!sound) return DRUM_DEFAULT
  if (sound.role === 'tom') {
    const set = sound.sample as DrumSample[]
    return set[Math.max(0, TOMS.indexOf(pitch))]
  }
  const [file, rate, gain = 1] = sound.sample as DrumSample
  const [r, g] = PITCH_TWEAK[pitch] ?? [1, 1]
  return [file, rate * r, gain * g]
}

// 킷 소리 뒤에 거는 효과 (룸 · 재즈 = 방 울림, 로파이 = 고음을 깎아 먹먹하게)
const KIT_FX: Record<number, () => Tone.ToneAudioNode[]> = {
  8: () => [new Tone.Reverb({ decay: 1.4, wet: 0.3 })],
  27: () => [new Tone.Filter({ frequency: 2600, type: 'lowpass', rolloff: -24 })],
  32: () => [new Tone.Reverb({ decay: 1.8, wet: 0.18 })],
}
const CLOSED_HATS = new Set([42, 44])
const OPEN_HAT = 46

class SampledDrumVoice implements Voice {
  output = new Tone.Gain()
  /** 샘플이 모이는 곳. 킷 효과를 거쳐 output으로 간다 */
  private bus = new Tone.Gain()
  private fx: Tone.ToneAudioNode[] = []
  ready: Promise<void>
  fallback = false
  private buffers: Tone.ToneAudioBuffers | null = null
  private synth: SynthDrumVoice | null = null
  private openHat: Tone.ToneBufferSource | null = null
  private kit: number
  private picked: Record<string, string>
  private laneGain = new Map<number, number>()

  constructor(track: Track) {
    this.kit = kitOf(track.program)
    this.picked = track.drum_sounds ?? {}
    // 이 트랙에 쓰인 소리의 샘플만 불러온다
    const pitches = [...new Set(track.notes.map((n) => n.pitch))]
    const files = new Set([...pitches.map((p) => drumSample(this.kit, p, this.picked)), DRUM_DEFAULT].map(([f]) => f))
    const urls = Object.fromEntries([...files].map((f) => [f, `${f}.flac`]))
    this.fx = KIT_FX[this.kit]?.() ?? []
    this.bus.chain(...this.fx, this.output)
    // 잔향은 울림(IR)을 만드는 데 시간이 걸려서 샘플과 함께 기다린다
    const fxReady = Promise.all(this.fx.map((n) => (n instanceof Tone.Reverb ? n.ready : null)))
    this.ready = waitLoad((done, fail) => {
      this.buffers = new Tone.ToneAudioBuffers({ urls, baseUrl: '/samples/drums/', onload: done, onerror: fail })
    }).then(async (ok) => {
      await fxReady
      if (ok) return
      this.buffers?.dispose()
      this.buffers = null
      this.synth = new SynthDrumVoice()
      this.synth.output.connect(this.output)
      this.fallback = true
    })
  }

  play(pitch: number, duration: string, time: number, velocity: number) {
    if (!this.buffers?.loaded) return this.synth?.play(pitch, duration, time, velocity)

    const [file, rate, gain = 1] = drumSample(this.kit, pitch, this.picked)
    // 닫힌 하이햇이 울리면 열린 하이햇 소리를 끊는다 (실제 하이햇처럼)
    if (CLOSED_HATS.has(pitch) && this.openHat) {
      this.openHat.stop(time)
      this.openHat = null
    }
    // 한 번 치고 버리는 소스라서 같은 시각에 겹쳐 울려도 문제없다
    // 이 드럼과 같은 오디오 공간(context)에 만든다. 음원 내보내기(Tone.Offline)는 녹음 중에 전역 context를
    // 원래대로 되돌리므로, 전역 기본값으로 만들면 녹음용 노드에 연결하지 못한다
    const src = new Tone.ToneBufferSource({ url: this.buffers.get(file), context: this.bus.context }).connect(this.bus)
    src.playbackRate.value = rate
    src.onended = () => {
      if (this.openHat === src) this.openHat = null
      src.dispose()
    }
    src.start(time, 0, undefined, Math.pow(velocity / 127, 1.5) * gain * (this.laneGain.get(pitch) ?? 1))
    if (pitch === OPEN_HAT) this.openHat = src
  }

  releaseAll() {
    this.openHat = null
    this.synth?.releaseAll()
  }

  setLaneGain(pitch: number, gain: number) {
    // 세기 비율 → 소리 크기는 velocity^1.5로 계산하므로 같은 곡선을 쓴다
    this.laneGain.set(pitch, Math.pow(gain, 1.5))
  }

  dispose() {
    this.buffers?.dispose()
    this.synth?.dispose()
    for (const n of this.fx) n.dispose()
    this.bus.dispose()
    this.output.dispose()
  }
}

// ---------- 대체용 신스 (샘플을 못 불러올 때) ----------

type Preset = 'keys' | 'bass' | 'pad' | 'lead'

function presetOf(program: number): Preset {
  if (program >= 32 && program <= 39) return 'bass'
  if ((program >= 40 && program <= 55) || (program >= 88 && program <= 95)) return 'pad'
  if (program >= 80 && program <= 87) return 'lead'
  return 'keys'
}

class SynthVoice {
  output: Tone.ToneAudioNode
  private synth: Tone.PolySynth

  constructor(preset: Preset) {
    switch (preset) {
      case 'bass':
        this.synth = new Tone.PolySynth(Tone.MonoSynth, {
          oscillator: { type: 'sawtooth' },
          filter: { type: 'lowpass', Q: 1 },
          filterEnvelope: { attack: 0.01, decay: 0.2, sustain: 0.3, release: 0.4, baseFrequency: 120, octaves: 2.5 },
          envelope: { attack: 0.005, decay: 0.3, sustain: 0.6, release: 0.3 },
          volume: -10,
        })
        break
      case 'pad':
        this.synth = new Tone.PolySynth(Tone.Synth, {
          oscillator: { type: 'sawtooth' },
          envelope: { attack: 0.15, decay: 0.3, sustain: 0.7, release: 1 },
          volume: -18,
        })
        break
      case 'lead':
        this.synth = new Tone.PolySynth(Tone.Synth, {
          oscillator: { type: 'square' },
          envelope: { attack: 0.01, decay: 0.2, sustain: 0.5, release: 0.3 },
          volume: -16,
        })
        break
      default:
        this.synth = new Tone.PolySynth(Tone.Synth, {
          oscillator: { type: 'triangle' },
          envelope: { attack: 0.005, decay: 0.4, sustain: 0.25, release: 0.6 },
          volume: -8,
        })
    }
    this.output = this.synth
  }

  play(pitch: number, duration: string, time: number, velocity: number) {
    this.synth.triggerAttackRelease(Tone.Frequency(pitch, 'midi').toFrequency(), duration, time, velocity / 127)
  }

  releaseAll() {
    this.synth.releaseAll()
  }

  dispose() {
    this.synth.dispose()
  }
}

type DrumPart = 'kick' | 'snare' | 'hat' | 'openHat' | 'tom' | 'cymbal'

const DRUM_PARTS: Record<number, DrumPart> = {
  35: 'kick', 36: 'kick',
  37: 'snare', 38: 'snare', 39: 'snare', 40: 'snare',
  42: 'hat', 44: 'hat', 46: 'openHat',
  41: 'tom', 43: 'tom', 45: 'tom', 47: 'tom', 48: 'tom', 50: 'tom',
  49: 'cymbal', 51: 'cymbal', 52: 'cymbal', 53: 'cymbal', 55: 'cymbal', 57: 'cymbal', 59: 'cymbal',
}

class SynthDrumVoice {
  output = new Tone.Gain()
  private kick = new Tone.MembraneSynth({
    pitchDecay: 0.05,
    octaves: 6,
    envelope: { attack: 0.001, decay: 0.35, sustain: 0, release: 0.1 },
  })
  private tom = new Tone.MembraneSynth({
    pitchDecay: 0.08,
    octaves: 3,
    envelope: { attack: 0.001, decay: 0.3, sustain: 0, release: 0.1 },
    volume: -6,
  })
  private snare = new Tone.NoiseSynth({
    noise: { type: 'white' },
    envelope: { attack: 0.001, decay: 0.15, sustain: 0 },
    volume: -10,
  })
  private hat = metal(0.05, -24)
  private openHat = metal(0.3, -24)
  private cymbal = metal(1.2, -26)
  // 단음 신스는 같은 시각에 두 번 울리면 오류가 나서, 부분마다 마지막 시각을 기억해 겹치면 건너뛴다.
  private last: Partial<Record<DrumPart, number>> = {}

  constructor() {
    for (const s of this.parts()) s.connect(this.output)
  }

  play(pitch: number, _duration: string, time: number, velocity: number) {
    const part = DRUM_PARTS[pitch] ?? 'hat'
    if (time <= (this.last[part] ?? -1) + 0.001) return
    this.last[part] = time
    const v = velocity / 127
    switch (part) {
      case 'kick':
        return this.kick.triggerAttackRelease('C1', '8n', time, v)
      case 'tom':
        return this.tom.triggerAttackRelease(Tone.Frequency(pitch, 'midi').toFrequency(), '8n', time, v)
      case 'snare':
        return this.snare.triggerAttackRelease('16n', time, v)
      default:
        return this[part].triggerAttackRelease(300, '32n', time, v)
    }
  }

  releaseAll() {
    // 드럼은 소리가 짧아서 따로 끊지 않는다.
  }

  dispose() {
    for (const s of this.parts()) s.dispose()
    this.output.dispose()
  }

  private parts() {
    return [this.kick, this.tom, this.snare, this.hat, this.openHat, this.cymbal]
  }
}

function metal(decay: number, volume: number) {
  return new Tone.MetalSynth({
    envelope: { attack: 0.001, decay, release: 0.01 },
    harmonicity: 5.1,
    modulationIndex: 32,
    resonance: 4000,
    octaves: 1.5,
    volume,
  })
}
