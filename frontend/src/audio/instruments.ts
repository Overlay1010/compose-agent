import * as Tone from 'tone'
import type { Track } from '../api/types'

// 트랙 하나의 소리를 내는 단위.
// 지금은 Tone.js 신스로 소리를 만들고, 나중에 사운드폰트(실제 악기 샘플)로 바꿀 때는
// 이 인터페이스만 맞춰 createVoice에서 갈아 끼우면 된다.
export interface Voice {
  output: Tone.ToneAudioNode
  /** duration은 Tone.js 시간 문자열 (예: "96i" = 96틱) */
  play(pitch: number, duration: string, time: number, velocity: number): void
  releaseAll(): void
  dispose(): void
}

export function createVoice(track: Track): Voice {
  return track.is_drum ? new DrumVoice() : new MelodicVoice(presetOf(track))
}

// ---------- 멜로디 악기 ----------

type Preset = 'keys' | 'bass' | 'pad' | 'lead'

// FL Studio에서 내보낸 파일은 악기 번호가 전부 0인 경우가 많아서 트랙 이름도 같이 본다.
function presetOf(track: Track): Preset {
  const name = track.name.toLowerCase()
  const p = track.program
  if (/bass|808/.test(name) || (p >= 32 && p <= 39)) return 'bass'
  if (/pad|string|choir/.test(name) || (p >= 40 && p <= 55) || (p >= 88 && p <= 95)) return 'pad'
  if (/lead|synth/.test(name) || (p >= 80 && p <= 87)) return 'lead'
  return 'keys'
}

class MelodicVoice implements Voice {
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

// ---------- 드럼 ----------

type DrumPart = 'kick' | 'snare' | 'hat' | 'openHat' | 'tom' | 'cymbal'

// General MIDI 드럼 번호 기준. 목록에 없는 번호는 하이햇 소리로 낸다.
const DRUM_MAP: Record<number, DrumPart> = {
  35: 'kick', 36: 'kick',
  37: 'snare', 38: 'snare', 39: 'snare', 40: 'snare',
  42: 'hat', 44: 'hat', 46: 'openHat',
  41: 'tom', 43: 'tom', 45: 'tom', 47: 'tom', 48: 'tom', 50: 'tom',
  49: 'cymbal', 51: 'cymbal', 52: 'cymbal', 53: 'cymbal', 55: 'cymbal', 57: 'cymbal', 59: 'cymbal',
}

// 피아노롤 드럼 레인에 보여 줄 이름 (General MIDI 기준)
export const DRUM_NAMES: Record<number, string> = {
  35: 'Kick 2', 36: 'Kick', 37: 'Side Stick', 38: 'Snare', 39: 'Clap', 40: 'Snare 2',
  41: 'Floor Tom 2', 42: 'Closed Hat', 43: 'Floor Tom', 44: 'Pedal Hat', 45: 'Low Tom',
  46: 'Open Hat', 47: 'Low-Mid Tom', 48: 'Hi-Mid Tom', 49: 'Crash', 50: 'High Tom',
  51: 'Ride', 52: 'China', 53: 'Ride Bell', 54: 'Tambourine', 55: 'Splash', 56: 'Cowbell',
  57: 'Crash 2', 59: 'Ride 2',
}

class DrumVoice implements Voice {
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
    const part = DRUM_MAP[pitch] ?? 'hat'
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
