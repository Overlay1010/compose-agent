import * as Tone from 'tone'
import type { Track } from '../api/types'
import { DRUM_DEFAULT, GM_NAMES, drumSample, gmProgramOf, kitOf } from './catalog'

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
  if (track.is_drum) return new SampledDrumVoice(track)
  return sustains(gmProgramOf(track)) ? new LoopedVoice(track) : new SampledVoice(track)
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

// ---------- 계속 울리는 악기: 녹음 가운데를 되풀이 ----------

// FluidR3 녹음은 모든 음이 3.13초이고, 소리가 줄지 않은 채 거기서 잘려 있다. 피아노 · 기타처럼 저절로 줄어드는 악기는
// 괜찮지만 오르간 · 스트링 · 패드는 3.13초보다 긴 음이 뚝 끊긴다. Tone.Sampler는 되풀이를 못 해서 직접 튼다.
// 오르간 16~23 · 바이올린~트레몰로 40~44 · 앙상블 · 합창 48~55 · 금관 · 리드 · 플룻 56~79 · 신스 리드 · 패드 80~95
const sustains = (program: number) => (program >= 16 && program <= 23) || (program >= 40 && program <= 44) || (program >= 48 && program <= 95)
const LOOP_FROM = 1.0 // 초. 어택(패드는 0.4초쯤)이 끝나고 소리가 안정된 곳부터 되풀이
const RECORDED = 3.1 // 초. 녹음 끝(3.13초) 조금 앞까지만 쓴다
const XFADE = 0.15 // 초. 되풀이 조각끼리 이만큼 겹쳐 서서히 바꾼다
const RELEASE = 0.8 // 음이 끝난 뒤 줄어드는 시간 (SampledVoice와 같게)

class LoopedVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  private buffers: Tone.ToneAudioBuffers | null = null
  private bases: number[]
  private sources = new Set<Tone.ToneBufferSource>()
  private synth: SynthVoice | null = null

  constructor(track: Track) {
    const program = gmProgramOf(track)
    const urls = sampleUrls(track)
    this.bases = Object.keys(urls).map(Number)
    this.ready = waitLoad((done, fail) => {
      this.buffers = new Tone.ToneAudioBuffers({ urls, baseUrl: `${FLUID_URL}${GM_NAMES[program]}-mp3/`, onload: done, onerror: fail })
    }).then((ok) => {
      if (ok) return
      this.buffers?.dispose()
      this.buffers = null
      this.synth = new SynthVoice(presetOf(program))
      this.synth.output.connect(this.output)
      this.fallback = true
    })
  }

  play(pitch: number, duration: string, time: number, velocity: number) {
    if (!this.buffers?.loaded) {
      this.synth?.play(pitch, duration, time, velocity)
      return
    }
    // 가장 가까운 녹음을 재생 속도로 옮겨 낸다 (Tone.Sampler와 같음)
    const base = this.bases.reduce((a, b) => (Math.abs(b - pitch) < Math.abs(a - pitch) ? b : a))
    const rate = 2 ** ((pitch - base) / 12)
    const buffer = this.buffers.get(base)
    const end = time + this.output.toSeconds(duration)
    // 녹음의 LOOP_FROM ~ handover를 조각으로 이어 붙인다. 이음매를 바로 이으면(주기를 맞춰도) 오르간 · 스트링에서 1초마다
    // 딸깍 소리가 나서 조각끼리 XFADE만큼 겹친다. 어느 순간 음이 끝나도 줄어드는 소리(RELEASE)가 녹음 안에 들도록 일찍 넘긴다
    const handover = Math.max(LOOP_FROM + 0.5, RECORDED - (RELEASE + XFADE) * rate)
    let offset = 0
    let at = time
    for (;;) {
      const next = at + (handover - offset) / rate
      const last = next >= end
      const source = new Tone.ToneBufferSource({
        context: this.output.context,
        url: buffer,
        playbackRate: rate,
        fadeIn: offset > 0 ? XFADE : 0,
        fadeOut: last ? RELEASE : XFADE,
        curve: 'linear', // 겹친 두 조각의 합이 일정하게
      }).connect(this.output)
      // 끝난 소리는 목록에서만 뺀다 (정리는 Tone.js가 실시간 재생에서만 한다 — 여기서 dispose하면 음원 녹음 때 소리가 나기 전에 지워진다)
      source.onended = () => this.sources.delete(source)
      this.sources.add(source)
      source.start(at, offset, undefined, velocity / 127)
      source.stop(last ? end : next)
      if (last) break
      offset = LOOP_FROM
      at = next
    }
  }

  releaseAll() {
    for (const s of this.sources) s.stop()
    this.synth?.releaseAll()
  }

  dispose() {
    for (const s of this.sources) s.dispose()
    this.sources.clear()
    this.buffers?.dispose()
    this.synth?.dispose()
    this.output.dispose()
  }
}

// ---------- 드럼 (Sonic Pi 샘플, CC0 · public/samples/drums) ----------

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
