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
  return track.is_drum ? new SampledDrumVoice(track.program) : new SampledVoice(track)
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

// [샘플 파일, 재생 속도, 크기(기본 1)]. 탐은 같은 샘플을 속도만 바꿔 높낮이를 나눈다.
type DrumSample = [file: string, rate: number, gain?: number]

// GM 드럼 번호 → 스탠다드 킷 샘플
const DRUM_SAMPLES: Record<number, DrumSample> = {
  35: ['drum_bass_hard', 1], 36: ['drum_heavy_kick', 1],
  37: ['drum_snare_soft', 1.1], 38: ['drum_snare_hard', 1], 39: ['perc_snap', 1], 40: ['drum_snare_hard', 1.05],
  42: ['drum_cymbal_closed', 1], 44: ['drum_cymbal_pedal', 1], 46: ['drum_cymbal_open', 1],
  41: ['drum_tom_lo_hard', 0.9], 43: ['drum_tom_lo_hard', 1], 45: ['drum_tom_mid_hard', 0.95],
  47: ['drum_tom_mid_hard', 1.05], 48: ['drum_tom_hi_hard', 0.95], 50: ['drum_tom_hi_hard', 1.05],
  49: ['drum_cymbal_hard', 1], 52: ['drum_cymbal_hard', 0.9], 55: ['drum_splash_hard', 1], 57: ['drum_cymbal_hard', 1.05],
  51: ['drum_cymbal_soft', 1], 53: ['drum_cymbal_soft', 1.2], 59: ['drum_cymbal_soft', 0.95],
}
const DRUM_DEFAULT: DrumSample = ['drum_cymbal_closed', 1] // 목록에 없는 번호

/** 고를 수 있는 드럼 킷 (GM 드럼 킷 번호, 백엔드 app/tools/instrument.py DRUM_KITS와 같은 목록) */
// 8 · 32는 GM2 표준 번호, 26~28은 이 앱 전용 (DAW에서는 각 DAW 드럼 소리로 열림)
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

// 킷마다 스탠다드와 다른 소리만 적는다 (샘플 고른 기준: 길이 · 밝기 · 저역 비율을 재서 비교).
// 크기가 큰 샘플(최대값 1.4)은 gain을 낮춰 다른 소리와 맞춘다.
const TOMS = [41, 43, 45, 47, 48, 50]
const KIT_SAMPLES: Record<number, Record<number, DrumSample>> = {
  // 파워: 묵직한 킥 · 큰 스네어 · 낮게 튠한 탐
  16: {
    35: ['bd_klub', 0.95, 0.7], 36: ['bd_klub', 1, 0.7], 38: ['sn_dolf', 1, 0.7], 40: ['sn_dolf', 1.05, 0.7],
    ...Object.fromEntries(TOMS.map((p, i): [number, DrumSample] => [p, [['drum_tom_lo_hard', 'drum_tom_mid_hard', 'drum_tom_hi_hard'][Math.floor(i / 2)], 0.82 + (i % 2) * 0.08]])),
  },
  // 일렉트로닉: 짧은 킥 · 전자 스네어 · 짧은 하이햇 · 퍼즈 탐
  24: {
    35: ['elec_hollow_kick', 1, 0.7], 36: ['elec_soft_kick', 1, 0.7], 37: ['elec_hi_snare', 1.1], 38: ['elec_snare', 1], 40: ['elec_lo_snare', 1],
    42: ['hat_sci', 1], 44: ['hat_sci', 0.9], 46: ['hat_noiz', 1],
    ...Object.fromEntries(TOMS.map((p, i): [number, DrumSample] => [p, ['elec_fuzz_tom', 0.75 + i * 0.1, 0.8]])),
    49: ['elec_cymbal', 1], 57: ['elec_cymbal', 0.95],
  },
  // TR-808: 길게 울리는 808 킥 · 짧은 하이햇 · 낮은 음의 탐(킥 샘플을 높여서)
  25: {
    35: ['bd_808', 0.95], 36: ['bd_808', 1], 38: ['elec_hi_snare', 1], 40: ['elec_hi_snare', 0.95],
    42: ['hat_bdu', 1], 44: ['hat_bdu', 0.9], 46: ['hat_len', 1],
    ...Object.fromEntries(TOMS.map((p, i): [number, DrumSample] => [p, ['bd_pure', 1.6 + i * 0.3]])),
  },
  // 하우스 (909): 짧고 단단한 킥 · 909식 클랩 · 밝은 하이햇
  26: {
    35: ['bd_haus', 0.95, 0.7], 36: ['bd_haus', 1, 0.7], 38: ['sn_generic', 1, 0.8], 40: ['sn_generic', 1.05, 0.8],
    39: ['perc_snap2', 1, 0.7], 42: ['hat_raw', 1], 44: ['hat_raw', 0.9], 46: ['hat_gump', 1, 0.8],
  },
  // 로파이: 둥글고 낮은 킥 · 먹먹한 스네어 · 작은 하이햇 (필터는 KIT_FX)
  27: {
    35: ['bd_gas', 0.95], 36: ['bd_gas', 1], 38: ['sn_dub', 0.95, 0.7], 40: ['sn_dub', 1, 0.7],
    42: ['hat_tap', 1, 2.5], 44: ['hat_tap', 0.9, 2.5], 46: ['hat_cats', 1, 1.5],
  },
  // 붐뱁: 굵은 킥 · 큰 스네어
  28: {
    35: ['bd_fat', 0.95, 1.6], 36: ['bd_fat', 1, 1.6], 38: ['sn_zome', 1, 0.75], 40: ['sn_zome', 1.05, 0.75],
    42: ['hat_zild', 1], 44: ['hat_zild', 0.9],
  },
  // 재즈: 부드러운 킥 · 스네어, 길게 울리는 라이드 (잔향은 KIT_FX)
  32: {
    35: ['drum_bass_soft', 0.95], 36: ['drum_bass_soft', 1], 38: ['drum_snare_soft', 1], 40: ['drum_snare_soft', 1.05],
    51: ['ride_via', 1, 1.5], 59: ['ride_tri', 1, 1.3], 53: ['ride_tri', 1.2, 1.3],
  },
}

// 킷 소리 뒤에 거는 효과 (룸 · 재즈 = 방 울림, 로파이 = 고음을 깎아 먹먹하게)
const KIT_FX: Record<number, () => Tone.ToneAudioNode[]> = {
  8: () => [new Tone.Reverb({ decay: 1.4, wet: 0.3 })],
  27: () => [new Tone.Filter({ frequency: 2600, type: 'lowpass', rolloff: -24 })],
  32: () => [new Tone.Reverb({ decay: 1.8, wet: 0.18 })],
}

const drumSample = (kit: number, pitch: number): DrumSample => KIT_SAMPLES[kit]?.[pitch] ?? DRUM_SAMPLES[pitch] ?? DRUM_DEFAULT
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
  private laneGain = new Map<number, number>()

  constructor(program: number) {
    this.kit = DRUM_KITS.some((k) => k.program === program) ? program : 0
    const pitches = [...new Set([...Object.keys(DRUM_SAMPLES), ...Object.keys(KIT_SAMPLES[this.kit] ?? {})].map(Number))]
    const files = new Set([...pitches.map((p) => drumSample(this.kit, p)), DRUM_DEFAULT].map(([f]) => f))
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

    const [file, rate, gain = 1] = drumSample(this.kit, pitch)
    // 닫힌 하이햇이 울리면 열린 하이햇 소리를 끊는다 (실제 하이햇처럼)
    if (CLOSED_HATS.has(pitch) && this.openHat) {
      this.openHat.stop(time)
      this.openHat = null
    }
    // 한 번 치고 버리는 소스라서 같은 시각에 겹쳐 울려도 문제없다
    const src = new Tone.ToneBufferSource(this.buffers.get(file)).connect(this.bus)
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
