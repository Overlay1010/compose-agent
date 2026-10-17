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
}

export function createVoice(track: Track): Voice {
  return track.is_drum ? new SampledDrumVoice() : new SampledVoice(track)
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
  const pitches = track.notes.map((n) => n.pitch)
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

// GM 드럼 번호 → [샘플 파일, 재생 속도]. 탐은 같은 샘플을 속도만 바꿔 높낮이를 나눈다.
const DRUM_SAMPLES: Record<number, [string, number]> = {
  35: ['drum_bass_hard', 1], 36: ['drum_heavy_kick', 1],
  37: ['drum_snare_soft', 1.1], 38: ['drum_snare_hard', 1], 39: ['perc_snap', 1], 40: ['drum_snare_hard', 1.05],
  42: ['drum_cymbal_closed', 1], 44: ['drum_cymbal_pedal', 1], 46: ['drum_cymbal_open', 1],
  41: ['drum_tom_lo_hard', 0.9], 43: ['drum_tom_lo_hard', 1], 45: ['drum_tom_mid_hard', 0.95],
  47: ['drum_tom_mid_hard', 1.05], 48: ['drum_tom_hi_hard', 0.95], 50: ['drum_tom_hi_hard', 1.05],
  49: ['drum_cymbal_hard', 1], 52: ['drum_cymbal_hard', 0.9], 55: ['drum_splash_hard', 1], 57: ['drum_cymbal_hard', 1.05],
  51: ['drum_cymbal_soft', 1], 53: ['drum_cymbal_soft', 1.2], 59: ['drum_cymbal_soft', 0.95],
}
const DRUM_DEFAULT: [string, number] = ['drum_cymbal_closed', 1] // 목록에 없는 번호
const CLOSED_HATS = new Set([42, 44])
const OPEN_HAT = 46

class SampledDrumVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  private buffers: Tone.ToneAudioBuffers | null = null
  private synth: SynthDrumVoice | null = null
  private openHat: Tone.ToneBufferSource | null = null

  constructor() {
    const files = new Set([...Object.values(DRUM_SAMPLES), DRUM_DEFAULT].map(([f]) => f))
    const urls = Object.fromEntries([...files].map((f) => [f, `${f}.flac`]))
    this.ready = waitLoad((done, fail) => {
      this.buffers = new Tone.ToneAudioBuffers({ urls, baseUrl: '/samples/drums/', onload: done, onerror: fail })
    }).then((ok) => {
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

    const [file, rate] = DRUM_SAMPLES[pitch] ?? DRUM_DEFAULT
    // 닫힌 하이햇이 울리면 열린 하이햇 소리를 끊는다 (실제 하이햇처럼)
    if (CLOSED_HATS.has(pitch) && this.openHat) {
      this.openHat.stop(time)
      this.openHat = null
    }
    // 한 번 치고 버리는 소스라서 같은 시각에 겹쳐 울려도 문제없다
    const src = new Tone.ToneBufferSource(this.buffers.get(file)).connect(this.output)
    src.playbackRate.value = rate
    src.onended = () => {
      if (this.openHat === src) this.openHat = null
      src.dispose()
    }
    src.start(time, 0, undefined, Math.pow(velocity / 127, 1.5))
    if (pitch === OPEN_HAT) this.openHat = src
  }

  releaseAll() {
    this.openHat = null
    this.synth?.releaseAll()
  }

  dispose() {
    this.buffers?.dispose()
    this.synth?.dispose()
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
