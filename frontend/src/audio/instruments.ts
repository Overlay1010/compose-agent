import * as Tone from 'tone'
import type { AudioClip, Note, Track } from '../api/types'
import { DRUM_DEFAULT, GM_NAMES, drumSample, gmProgramOf, kitOf } from './catalog'
import { levelGain, noteSource } from './soundset'
import { sampleBuffer, sampleMeta } from '../samples/library'
import type { SampleMeta } from '../samples/analyze'

// 트랙 하나의 소리를 내는 단위.
// 기본은 실제 악기 샘플(멜로디: 고른 소리 세트 — 기본 고음질 세트, audio/soundset.ts · 드럼: Sonic Pi 샘플)이고,
// 샘플을 못 불러오면 예전 Tone.js 신스 소리로 대신한다.
export interface Voice {
  output: Tone.ToneAudioNode
  /** 샘플 준비가 끝나면 끝난다. 실패해도 reject하지 않고 신스로 바꾼 뒤 끝난다. */
  ready: Promise<void>
  /** 샘플을 못 불러와 신스로 대신하는 중인지 */
  fallback: boolean
  /** duration은 Tone.js 시간 문자열 (예: "96i" = 96틱). beat는 그 음의 곡 안 시작 박 (오디오 루프가 루프의 어디부터 틀지 정할 때) */
  play(pitch: number, duration: string, time: number, velocity: number, beat?: number): void
  releaseAll(): void
  dispose(): void
  /** 드럼만: 이 소리(음 번호)를 잠깐 키우거나 줄인다 (레인 슬라이더를 끄는 동안 들으며 맞추기) */
  setLaneGain?(pitch: number, gain: number): void
}

export function createVoice(track: Track, tempo = 120): Voice {
  if (track.audio) return new AudioLoopVoice(track.audio, tempo)
  if (track.is_drum) return new SampledDrumVoice(track)
  const mine = track.sample ? sampleMeta(track.sample.id) : undefined
  const usable = mine && mine.root !== null ? mine : undefined
  // 내 샘플이 이 브라우저에 없으면(다른 브라우저 · 지운 샘플) 트랙 악기로
  const voice = usable ? new UserSampleVoice(track, usable) : gmVoice(track)
  const bass = usable ? usable.kind === 'bass' : isBassProgram(gmProgramOf(track))
  if (bass && voice.output instanceof Tone.Gain) voice.output.gain.value = BASS_GAIN
  return voice
}

/**
 * 베이스 트랙은 6dB 키운다. 악기 크기는 음 하나 기준으로 맞췄는데(GM 베이스 7종 · 다른 악기 8종이 첫 1초 RMS · K-가중 모두 1dB 안),
 * 곡에서는 베이스만 한 음씩 치고 패드 · 건반은 3~4음을 겹쳐 쳐서(4음이면 +6dB) 베이스가 묻혔다 — 낮은 음은 귀에도 작게 들린다.
 * GM 핑거 베이스 · 내 베이스 샘플 모두 "약하게 들린다"는 말로 찾았다. 마스터가 -4dB라 키워도 넘치지 않는다.
 */
const BASS_GAIN = Math.pow(10, 6 / 20)
const isBassProgram = (program: number) => program >= 32 && program <= 39

function gmVoice(track: Track): Voice {
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

// ---------- 멜로디 악기 (소리 세트: audio/soundset.ts) ----------

/**
 * 트랙 음역(위아래 3반음 여유)에 쓸 녹음 음들. 사이 음은 가까운 녹음의 음높이를 바꿔 낸다.
 * GM 세트는 모든 음이 녹음돼 있어 3반음마다 하나씩만, 고음질 세트는 녹음된 음 중 음역 안 + 바로 바깥 하나씩
 */
function pickNotes(track: Track, notes: number[]): number[] {
  const pitches = track.notes.length ? track.notes.map((n) => n.pitch) : [60] // 음을 다 지운 트랙
  const low = Math.max(21, Math.min(...pitches) - 3)
  const high = Math.min(108, Math.max(...pitches) + 3)
  if (notes.length >= 88) {
    const out: number[] = []
    for (let p = low; p <= high; p += 3) out.push(p)
    if (out[out.length - 1] !== high) out.push(high)
    return out
  }
  const below = notes.filter((p) => p < low).pop()
  const above = notes.find((p) => p > high)
  return [...(below === undefined ? [] : [below]), ...notes.filter((p) => p >= low && p <= high), ...(above === undefined ? [] : [above])]
}

const ONSET = 0.05 // 최대 크기의 이만큼을 넘는 곳이 소리의 시작
const PREROLL = 0.01 // 초. 시작 조금 앞부터 남긴다 (어택 맨 앞이 잘리지 않게)

/** 앞 무음을 잘라 낸 녹음. 관악기 녹음 몇은 소리가 60~90ms 늦게 시작해서 박보다 늦게 들렸다 (FluidR3는 18ms쯤) */
function trimStart(buffer: Tone.ToneAudioBuffer): Tone.ToneAudioBuffer {
  const data = buffer.getChannelData(0)
  let peak = 0
  for (let i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i]))
  const first = data.findIndex((v) => Math.abs(v) > peak * ONSET)
  return buffer.slice(Math.max(0, first / buffer.sampleRate - PREROLL))
}

/** 이 트랙 악기의 녹음들을 불러와 앞 무음을 자른다 (음 번호 → 녹음). 못 불러오면 null */
function loadRecordings(track: Track): Promise<Map<number, Tone.ToneAudioBuffer> | null> {
  const program = gmProgramOf(track)
  const source = noteSource(program, GM_NAMES[program])
  const notes = pickNotes(track, source.notes)
  const urls = Object.fromEntries(notes.map((p) => [p, source.file(p)]))
  let buffers: Tone.ToneAudioBuffers | null = null
  return waitLoad((done, fail) => {
    buffers = new Tone.ToneAudioBuffers({ urls, baseUrl: source.baseUrl, onload: done, onerror: fail })
  }).then((ok) => {
    const loaded = ok && buffers ? new Map(notes.map((p) => [p, trimStart(buffers!.get(p))])) : null
    buffers?.dispose() // 잘라 낸 사본만 남긴다
    return loaded
  })
}

class SampledVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  private sampler: Tone.Sampler | null = null
  private synth: SynthVoice | null = null
  private level: Tone.Gain
  private disposed = false

  constructor(track: Track) {
    const program = gmProgramOf(track)
    this.level = new Tone.Gain(levelGain(program)).connect(this.output) // 세트마다 다른 악기 크기를 FluidR3에 맞춤
    this.ready = loadRecordings(track).then((recordings) => {
      if (this.disposed) return recordings?.forEach((b) => b.dispose()) // 불러오는 사이에 트랙이 바뀌었다
      if (recordings) {
        this.sampler = new Tone.Sampler({ urls: Object.fromEntries(recordings), release: 0.8 }).connect(this.level)
        return
      }
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
    this.disposed = true
    this.sampler?.dispose()
    this.synth?.dispose()
    this.level.dispose()
    this.output.dispose()
  }
}

// ---------- 계속 울리는 악기: 녹음 가운데를 되풀이 ----------

// FluidR3 녹음은 모든 음이 3.13초이고, 소리가 줄지 않은 채 거기서 잘려 있다. 피아노 · 기타처럼 저절로 줄어드는 악기는
// 괜찮지만 오르간 · 스트링 · 패드는 3.13초보다 긴 음이 뚝 끊긴다. Tone.Sampler는 되풀이를 못 해서 직접 튼다.
// 고음질 세트 녹음은 3~12초로 길지만 끝에 소리가 줄어드는 부분이 있어서, 녹음마다 소리가 일정한 끝(steadyEnd)까지만 쓴다.
// 오르간 16~23 · 바이올린~트레몰로 40~44 · 앙상블 · 합창 48~55 · 금관 · 리드 · 플룻 56~79 · 신스 리드 · 패드 80~95
const sustains = (program: number) => (program >= 16 && program <= 23) || (program >= 40 && program <= 44) || (program >= 48 && program <= 95)
const LOOP_FROM = 1.0 // 초. 어택(패드는 0.4초쯤)이 끝나고 소리가 안정된 곳부터 되풀이
const TAIL_MARGIN = 0.03 // 초. 녹음 맨 끝(FluidR3는 3.13초)에서 이만큼 앞까지만 쓴다
const XFADE = 0.15 // 초. 되풀이 조각끼리 이만큼 겹쳐 서서히 바꾼다
const RELEASE = 0.8 // 음이 끝난 뒤 줄어드는 시간 (SampledVoice와 같게)
const WINDOW = 0.05 // 초. 소리 크기를 잴 조각

/**
 * 녹음에서 소리가 일정하게 울리는 끝 (초). LOOP_FROM 뒤 50ms 조각들의 크기 가운데값보다 6dB 넘게 작아지는 첫 곳.
 * FluidR3는 소리가 줄지 않은 채 잘려 있어 녹음 끝이 되고, 따로 녹음한 샘플은 연주자가 소리를 거두기 시작하는 곳이 된다
 * (바순 7.8초 녹음이면 6.4초쯤). 그 뒤까지 되풀이하면 소리가 1초마다 줄었다 커졌다 한다
 */
function steadyEnd(buffer: Tone.ToneAudioBuffer): number {
  const data = buffer.getChannelData(0)
  const w = Math.round(buffer.sampleRate * WINDOW)
  const rms: number[] = []
  for (let i = 0; i + w <= data.length; i += w) {
    let sum = 0
    for (let j = i; j < i + w; j++) sum += data[j] * data[j]
    rms.push(Math.sqrt(sum / w))
  }
  const from = Math.ceil(LOOP_FROM / WINDOW)
  const tail = buffer.duration - TAIL_MARGIN
  if (rms.length <= from + 2) return tail
  const sorted = rms.slice(from).sort((a, b) => a - b)
  const floor = sorted[Math.floor(sorted.length / 2)] / 2
  const drop = rms.findIndex((v, i) => i > from && v < floor)
  return drop < 0 ? tail : Math.min(tail, drop * WINDOW)
}

class LoopedVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  /** 음 번호 → 녹음과 소리가 일정한 끝 (초) */
  private recordings: Map<number, { buffer: Tone.ToneAudioBuffer; end: number }> | null = null
  private sources = new Set<Tone.ToneBufferSource>()
  private synth: SynthVoice | null = null
  private level: Tone.Gain
  private disposed = false

  constructor(track: Track) {
    const program = gmProgramOf(track)
    this.level = new Tone.Gain(levelGain(program)).connect(this.output) // 세트마다 다른 악기 크기를 FluidR3에 맞춤
    this.ready = loadRecordings(track).then((recordings) => {
      if (this.disposed) return recordings?.forEach((b) => b.dispose())
      if (recordings) {
        this.recordings = new Map([...recordings].map(([p, buffer]) => [p, { buffer, end: steadyEnd(buffer) }]))
        return
      }
      this.synth = new SynthVoice(presetOf(program))
      this.synth.output.connect(this.output)
      this.fallback = true
    })
  }

  play(pitch: number, duration: string, time: number, velocity: number) {
    if (!this.recordings) {
      this.synth?.play(pitch, duration, time, velocity)
      return
    }
    // 가장 가까운 녹음을 재생 속도로 옮겨 낸다 (Tone.Sampler와 같음)
    const base = [...this.recordings.keys()].reduce((a, b) => (Math.abs(b - pitch) < Math.abs(a - pitch) ? b : a))
    const rate = 2 ** ((pitch - base) / 12)
    const { buffer, end: steady } = this.recordings.get(base)!
    const end = time + this.output.toSeconds(duration)
    // 녹음의 LOOP_FROM ~ handover를 조각으로 이어 붙인다. 이음매를 바로 이으면(주기를 맞춰도) 오르간 · 스트링에서 1초마다
    // 딸깍 소리가 나서 조각끼리 XFADE만큼 겹친다. 어느 순간 음이 끝나도 줄어드는 소리(RELEASE)가 녹음 안에 들도록 일찍 넘긴다
    const handover = Math.max(LOOP_FROM + 0.5, steady - (RELEASE + XFADE) * rate)
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
      }).connect(this.level)
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
    this.disposed = true
    for (const s of this.sources) s.dispose()
    this.sources.clear()
    this.recordings?.forEach((r) => r.buffer.dispose())
    this.synth?.dispose()
    this.level.dispose()
    this.output.dispose()
  }
}

// ---------- 내 샘플 (사용자가 넣은 원샷, samples/library.ts) ----------

// 녹음된 음(root) 하나를 재생 속도로 높이고 낮춰 낸다. 속도가 바뀌면 길이도 바뀐다 (한 옥타브 위 = 절반 길이).
// 음이 끝나면 짧게 줄이고, 원샷이 음보다 짧으면 녹음 끝에서 저절로 끝난다 (되풀이하지 않음 — 원샷에는 되풀이할 구간 정보가 없다).
const SAMPLE_RELEASE = 0.12 // 초

class UserSampleVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  private buffer: Tone.ToneAudioBuffer | null = null
  private inner: Voice | null = null
  private sources = new Set<Tone.ToneBufferSource>()
  private level: Tone.Gain
  private root: number

  constructor(track: Track, meta: SampleMeta) {
    this.root = meta.root ?? 60
    this.level = new Tone.Gain(meta.gain).connect(this.output) // 샘플끼리 크기 맞춤 (분석할 때 잰 값)
    this.ready = sampleBuffer(meta.id).then((raw) => {
      if (raw) {
        this.buffer = new Tone.ToneAudioBuffer(raw)
        return
      }
      // 이름표는 있는데 파일을 못 읽음 → 트랙 악기로
      this.inner = gmVoice(track)
      this.inner.output.connect(this.output)
      return this.inner.ready.then(() => {
        this.fallback = this.inner?.fallback ?? false
      })
    })
  }

  play(pitch: number, duration: string, time: number, velocity: number) {
    if (this.inner) return this.inner.play(pitch, duration, time, velocity)
    if (!this.buffer) return
    const source = new Tone.ToneBufferSource({
      context: this.output.context, // 음원 내보내기(Tone.Offline)에서도 같은 오디오 공간에 (드럼과 같은 이유)
      url: this.buffer,
      playbackRate: 2 ** ((pitch - this.root) / 12),
      fadeOut: SAMPLE_RELEASE,
    }).connect(this.level)
    source.onended = () => this.sources.delete(source)
    this.sources.add(source)
    source.start(time, 0, undefined, velocity / 127)
    source.stop(time + this.output.toSeconds(duration))
  }

  releaseAll() {
    for (const s of this.sources) s.stop()
    this.inner?.releaseAll()
  }

  dispose() {
    for (const s of this.sources) s.dispose()
    this.sources.clear()
    this.inner?.dispose()
    this.level.dispose()
    this.output.dispose()
  }
}

// ---------- 오디오 루프 (내 샘플의 루프 파일을 그대로) ----------

/** 타격마다 잘라 놓을 루프인가: 음 높이가 없는 리듬 루프(하이햇 · 드럼)이고 리듬을 읽었으면 자를 자리(박)들.
 * 모든 대역의 타격(cuts)으로 자른다 — 하이햇 자리로만 자르면 드럼 루프의 킥 · 스네어가 앞 조각에 묻혀 곡 박과 어긋난다 */
function sliceHits(clip: AudioClip): number[] | null {
  const meta = sampleMeta(clip.sample.id)
  if (!meta || meta.root !== null || !meta.groove) return null
  const cuts = meta.groove.cuts ?? meta.groove.hits.map(([b]) => b)
  return cuts.length ? cuts : null
}

/**
 * 오디오 트랙을 재생할 조각들. 두 가지:
 * - 리듬 루프(음 높이 없음): 타격마다 잘라 원래 속도로 곡 템포 자리에 (ReCycle처럼). 재생 속도를 바꾸면 140 BPM 하이햇 루프를
 *   84 BPM 곡에 맞출 때 음높이가 8.8반음 내려가 둔하게 들렸다. pitch에 타격 번호를 담는다.
 * - 그 밖: 마디마다 · 루프가 다시 시작하는 곳마다 자른다 — 중간부터 재생해도(구간 반복 · 바뀐 소리 ↔ 원래 소리) 다음 마디부터 바로 들리게.
 */
export function playEvents(track: Track, beatsPerBar: number): Note[] {
  const clip = track.audio
  if (!clip) return track.notes
  const out: Note[] = []
  const hits = sliceHits(clip)
  if (hits) {
    for (let s = clip.start; s < clip.end - 1e-6; s += clip.beats) {
      hits.forEach((beat, k) => {
        const t = s + beat
        const next = Math.min(s + (hits[k + 1] ?? clip.beats), clip.end)
        if (t < clip.end - 1e-6 && next > t) out.push({ pitch: k, start: t, duration: next - t, velocity: 100 })
      })
    }
    return out
  }
  let t = clip.start
  while (t < clip.end - 1e-6) {
    const nextBar = (Math.floor(t / beatsPerBar + 1e-9) + 1) * beatsPerBar
    const intoLoop = (t - clip.start) % clip.beats
    const nextLoop = t + (clip.beats - intoLoop)
    const next = Math.min(nextBar, nextLoop, clip.end)
    out.push({ pitch: 60, start: t, duration: next - t, velocity: 100 })
    t = next
  }
  return out
}

const LOOP_PEAK = 0.6 // 루프의 최대 크기를 이만큼으로 (드럼 · 악기와 섞였을 때 비슷하게)
const LOOP_EDGE = 0.004 // 초. 조각 이음매의 딸깍 소리를 막는 아주 짧은 페이드
const LOOP_PREROLL = 0.003 // 초

class AudioLoopVoice implements Voice {
  output = new Tone.Gain()
  ready: Promise<void>
  fallback = false
  private buffer: Tone.ToneAudioBuffer | null = null
  private sources = new Set<Tone.ToneBufferSource>()
  private level: Tone.Gain
  private clip: AudioClip
  private tempo: number
  private hits: number[] | null

  constructor(clip: AudioClip, tempo: number) {
    this.clip = clip
    this.tempo = tempo
    this.hits = sliceHits(clip)
    const meta = sampleMeta(clip.sample.id)
    this.level = new Tone.Gain(LOOP_PEAK / Math.max(meta?.peak ?? 1, 0.05)).connect(this.output)
    // 이 브라우저에 없는 루프는 소리 없이 (트랙 목록에 표시)
    this.ready = (meta ? sampleBuffer(clip.sample.id) : Promise.resolve(null)).then((raw) => {
      if (raw) this.buffer = new Tone.ToneAudioBuffer(raw)
    })
  }

  play(pitch: number, duration: string, time: number, _velocity: number, beat = this.clip.start) {
    if (!this.buffer) return
    const spb = 60 / this.clip.bpm // 루프 파일의 한 박(초)
    let offset: number
    let rate: number
    let length = this.output.toSeconds(duration)
    if (this.hits) {
      // 타격 하나: 원래 속도로 그 조각만 (곡이 느리면 조각 뒤는 조용히, 빠르면 다음 타격에서 끊김)
      const from = this.hits[pitch]
      const to = this.hits[pitch + 1] ?? this.clip.beats
      offset = Math.max(0, from * spb - LOOP_PREROLL) // 타격 시작은 5ms 단위로 찾아서 어택 맨 앞이 잘리지 않게 조금 앞부터
      rate = 1
      length = Math.min(length, (to - from) * spb)
    } else {
      // 곡 템포에 맞춰 재생 속도를 바꾼다 (음높이도 같이 바뀜 — 백엔드 add_loop 결과에 알린다)
      const intoLoop = (((beat - this.clip.start) % this.clip.beats) + this.clip.beats) % this.clip.beats
      offset = intoLoop * spb
      rate = this.tempo / this.clip.bpm
    }
    const source = new Tone.ToneBufferSource({
      context: this.output.context,
      url: this.buffer,
      playbackRate: rate,
      fadeIn: LOOP_EDGE,
      fadeOut: LOOP_EDGE,
    }).connect(this.level)
    source.onended = () => this.sources.delete(source) // 지우지는 않는다 (음원 내보내기에서 소리가 나기 전에 지워짐 — 드럼 끊기와 같은 이유)
    this.sources.add(source)
    source.start(time, offset)
    source.stop(time + length)
  }

  releaseAll() {
    for (const s of this.sources) s.stop()
    this.sources.clear()
  }

  dispose() {
    for (const s of this.sources) s.dispose()
    this.sources.clear()
    this.level.dispose()
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
// 내 드럼 샘플: 최대 크기를 이만큼으로 맞춘다 (내장 Sonic Pi 킷과 비슷한 크기 — 솔로로 내보내 잼)
const MY_DRUM_PEAK = 0.9
// 탐 샘플 하나로 탐 레인 여섯을 낮은 탐 → 높은 탐으로 (내장 탐처럼 재생 속도로)
const MY_TOM_RATES: Record<number, number> = { 41: 0.8, 43: 0.87, 45: 0.94, 47: 1, 48: 1.07, 50: 1.15 }
const MY_DRUM_CUT = 0.02 // 초. 같은 레인을 다시 쳐서 앞 소리를 끊을 때 딸깍 소리가 나지 않게 줄이는 시간

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
  /** 레인(음 번호) → 내 샘플 소리 · 크기 · 속도 */
  private mine = new Map<number, { buffer: Tone.ToneAudioBuffer; gain: number; rate: number }>()
  /** 레인 → 지금 울리는 내 샘플 소리 (같은 레인을 다시 치면 끊는다) */
  private ringing = new Map<number, Tone.ToneBufferSource>()

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
    // 내 샘플을 고른 레인. 이 브라우저에 없거나 드럼 원샷이 아닌 샘플(다시 분석해 루프로 바뀐 것)은 킷 소리 그대로
    const mineReady = Promise.all(
      Object.entries(track.drum_samples ?? {}).map(async ([lane, ref]) => {
        const meta = sampleMeta(ref.id)
        const raw = meta?.kind === 'drum' ? await sampleBuffer(ref.id) : null
        if (!meta || !raw) return
        const pitch = Number(lane)
        this.mine.set(pitch, { buffer: new Tone.ToneAudioBuffer(raw), gain: MY_DRUM_PEAK / Math.max(meta.peak ?? 1, 0.05), rate: MY_TOM_RATES[pitch] ?? 1 })
      }),
    )
    this.ready = waitLoad((done, fail) => {
      this.buffers = new Tone.ToneAudioBuffers({ urls, baseUrl: '/samples/drums/', onload: done, onerror: fail })
    }).then(async (ok) => {
      await fxReady
      await mineReady
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

    const mine = this.mine.get(pitch)
    const [file, rate, gain = 1] = mine ? ['', mine.rate, mine.gain] : drumSample(this.kit, pitch, this.picked)
    // 닫힌 하이햇이 울리면 열린 하이햇 소리를 끊는다 (실제 하이햇처럼)
    if (CLOSED_HATS.has(pitch) && this.openHat) {
      this.openHat.stop(time)
      this.openHat = null
    }
    // 한 번 치고 버리는 소스라서 같은 시각에 겹쳐 울려도 문제없다
    // 이 드럼과 같은 오디오 공간(context)에 만든다. 음원 내보내기(Tone.Offline)는 녹음 중에 전역 context를
    // 원래대로 되돌리므로, 전역 기본값으로 만들면 녹음용 노드에 연결하지 못한다
    const src = new Tone.ToneBufferSource({
      url: mine ? mine.buffer : this.buffers.get(file),
      context: this.bus.context,
      fadeOut: mine ? MY_DRUM_CUT : 0,
    }).connect(this.bus)
    src.playbackRate.value = rate
    // 내 샘플은 같은 레인을 다시 치면 앞 소리를 끊는다 (FPC "cut itself"처럼). 내장 소리는 짧아서 괜찮지만
    // 내 샘플은 길 수 있다 — 하이햇 루프를 원샷으로 넣었을 때 칠 때마다 몇 초짜리 패턴이 겹쳐 계속 울렸다
    if (mine) {
      this.ringing.get(pitch)?.stop(time)
      this.ringing.set(pitch, src)
    }
    src.onended = () => {
      if (this.openHat === src) this.openHat = null
      if (this.ringing.get(pitch) === src) this.ringing.delete(pitch)
      // 끊은 소리(stop)는 지우지 않는다: 음원 내보내기(Tone.Offline)에서는 stop의 타이머가 녹음보다 먼저 돌아,
      // 여기서 dispose하면 소리가 나기 전에 지워졌다 (끊는 레인이 통째로 무음). 실시간 재생에서는 Tone.js가 정리한다
      if (!mine) src.dispose()
    }
    src.start(time, 0, undefined, Math.pow(velocity / 127, 1.5) * gain * (this.laneGain.get(pitch) ?? 1))
    if (pitch === OPEN_HAT) this.openHat = src
  }

  releaseAll() {
    this.openHat = null
    for (const s of this.ringing.values()) s.stop()
    this.ringing.clear()
    this.synth?.releaseAll()
  }

  setLaneGain(pitch: number, gain: number) {
    // 세기 비율 → 소리 크기는 velocity^1.5로 계산하므로 같은 곡선을 쓴다
    this.laneGain.set(pitch, Math.pow(gain, 1.5))
  }

  dispose() {
    this.buffers?.dispose()
    this.synth?.dispose()
    for (const m of this.mine.values()) m.buffer.dispose()
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
