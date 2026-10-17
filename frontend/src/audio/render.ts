import * as Tone from 'tone'
import type { Project } from '../api/types'
import { createVoice } from './instruments'

// 음원 내보내기: 재생과 같은 악기 · 볼륨 · 팬 · 효과로 곡을 오프라인(실시간보다 빠르게)으로 녹음한다.
// 결과는 WAV. 다른 형식(MP3 등)은 이 WAV를 서버에서 ffmpeg로 바꾼다 (api/client.ts convertAudio).

const SAMPLE_RATE = 44100
const TAIL_SECONDS = 2.5 // 마지막 음 뒤 울림(잔향 · 릴리스)까지

const faderDb = (volume: number) => (volume <= 0 ? -Infinity : 40 * Math.log10(volume / 100))

/** silenced: 음소거 · 솔로로 안 들리는 트랙 (들리는 그대로 내보낸다) */
export async function renderMix(project: Project, silenced: Record<string, boolean> = {}): Promise<AudioBuffer> {
  const tracks = project.tracks.filter((t) => !silenced[t.id] && t.notes.length)
  if (!tracks.length) throw new Error('들리는 트랙이 없어요. 음소거 · 솔로를 확인해 주세요.')
  const endBeats = Math.max(...tracks.flatMap((t) => t.notes.map((n) => n.start + n.duration)))
  const seconds = (endBeats * 60) / project.tempo + TAIL_SECONDS

  const rendered = await Tone.Offline(async ({ transport }) => {
    transport.bpm.value = project.tempo
    transport.timeSignature = [project.time_signature[0], project.time_signature[1]]
    const ticks = (beats: number) => `${Math.round(beats * transport.PPQ)}i`
    const master = new Tone.Volume(-4).toDestination()
    const voices = tracks.map((track) => {
      const voice = createVoice(track)
      const panner = new Tone.Panner(Math.max(-1, Math.min(1, track.pan / 64))).connect(master)
      const fader = new Tone.Volume(faderDb(track.volume)).connect(panner)
      voice.output.connect(fader)
      for (const n of track.notes) {
        transport.schedule((time) => voice.play(n.pitch, ticks(n.duration), time, n.velocity), ticks(n.start))
      }
      return voice
    })
    // 샘플 · 잔향을 다 불러온 뒤 시작 (Offline은 이 함수가 끝날 때까지 기다린다)
    await Promise.all(voices.map((v) => v.ready))
    transport.start(0)
  }, seconds, 2, SAMPLE_RATE)

  const buffer = rendered.get()
  if (!buffer) throw new Error('음원을 만들지 못했어요.')
  return buffer
}

/** AudioBuffer → 16비트 PCM WAV */
export function toWav(buffer: AudioBuffer): Blob {
  const channels = buffer.numberOfChannels
  const frames = buffer.length
  const dataBytes = frames * channels * 2
  const view = new DataView(new ArrayBuffer(44 + dataBytes))
  const text = (at: number, s: string) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)))
  text(0, 'RIFF')
  view.setUint32(4, 36 + dataBytes, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 크기
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, channels, true)
  view.setUint32(24, buffer.sampleRate, true)
  view.setUint32(28, buffer.sampleRate * channels * 2, true)
  view.setUint16(32, channels * 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, dataBytes, true)
  const data = Array.from({ length: channels }, (_, c) => buffer.getChannelData(c))
  let at = 44
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < channels; c++) {
      const s = Math.max(-1, Math.min(1, data[c][i])) // 넘치는 소리는 자른다
      view.setInt16(at, s < 0 ? s * 0x8000 : s * 0x7fff, true)
      at += 2
    }
  }
  return new Blob([view], { type: 'audio/wav' })
}

/** 가장 큰 소리 (0~1). 1에 닿으면 소리가 깨졌을 수 있다 */
export function peakOf(buffer: AudioBuffer): number {
  let peak = 0
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const d = buffer.getChannelData(c)
    for (let i = 0; i < d.length; i++) peak = Math.max(peak, Math.abs(d[i]))
  }
  return peak
}
