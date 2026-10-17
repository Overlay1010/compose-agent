import * as Tone from 'tone'
import type { Project } from '../api/types'
import { createVoice, type Voice } from './instruments'

// Project를 Tone.js Transport에 올려 재생한다.
// 시간은 백엔드처럼 박 단위로 다루고, Transport의 틱(1박 = PPQ틱)으로 바꿔 예약한다.
// Tone을 처음 건드리는 순간 AudioContext가 만들어지므로, 모든 호출은 재생 버튼을 누른 뒤에 일어나게 한다.

interface Channel {
  name: string
  voice: Voice
  /** 트랙 볼륨(페이더) */
  fader: Tone.Volume
  panner: Tone.Panner
  /** 음소거 · 솔로 전용 (페이더 값과 섞이지 않게 따로 둔다) */
  volume: Tone.Volume
}

/** MIDI 볼륨(0~127) → 데시벨. 100이 0dB, GM 권장 곡선(40·log10) */
const faderDb = (volume: number) => (volume <= 0 ? -Infinity : 40 * Math.log10(volume / 100))
const panValue = (pan: number) => Math.max(-1, Math.min(1, pan / 64))

let master: Tone.Volume | null = null
let loaded: Project | null = null
let channels = new Map<string, Channel>()
let onEnd: (() => void) | null = null
let playRequest = 0 // 샘플을 불러오는 동안 정지를 누르면, 로딩이 끝나도 재생을 시작하지 않게

const transport = () => Tone.getTransport()
const ticks = (beats: number) => `${Math.round(beats * transport().PPQ)}i`

// Transport가 같은 틱의 이벤트를 부동소수 오차만큼 다른 시각으로 두 번 부를 때가 있다.
// 1ms 안에 다시 불리면 같은 이벤트로 보고 건너뛴다 (다음 재생에서는 시각이 크게 달라서 영향 없음).
function once(fn: (time: number) => void) {
  let last = -Infinity
  return (time: number) => {
    if (Math.abs(time - last) < 0.001) return
    last = time
    fn(time)
  }
}

function load(project: Project, muted: Record<string, boolean>) {
  const t = transport()
  t.stop()
  t.cancel()
  for (const c of channels.values()) {
    c.voice.dispose()
    c.fader.dispose()
    c.panner.dispose()
    c.volume.dispose()
  }
  channels = new Map()
  master ??= new Tone.Volume(-4).toDestination()

  t.bpm.value = project.tempo
  t.timeSignature = [project.time_signature[0], project.time_signature[1]]

  let end = 0
  for (const track of project.tracks) {
    const voice = createVoice(track)
    const volume = new Tone.Volume().connect(master)
    volume.mute = !!muted[track.id]
    const panner = new Tone.Panner(panValue(track.pan)).connect(volume)
    const fader = new Tone.Volume(faderDb(track.volume)).connect(panner)
    voice.output.connect(fader)
    channels.set(track.id, { name: track.name, voice, fader, panner, volume })

    for (const n of track.notes) {
      t.schedule(
        once((time) => voice.play(n.pitch, ticks(n.duration), time, n.velocity)),
        ticks(n.start),
      )
      end = Math.max(end, n.start + n.duration)
    }
  }

  // 마지막 음이 끝나고 반 박 뒤에 멈춘다 (화면 갱신은 소리와 맞춰 Draw로). 구간 반복 중에는 멈추지 않는다.
  t.schedule((time) => {
    if (t.loop) return
    Tone.getDraw().schedule(() => {
      stop()
      onEnd?.()
    }, time)
  }, ticks(end + 0.5))

  loaded = project
}

/**
 * 재생한다. 처음이면 악기 샘플을 다 불러온 뒤 시작한다. fromBeats부터 (바뀐 소리 ↔ 원래 소리 전환 때 그 자리에서 이어 듣기).
 * 돌려주는 값은 샘플을 못 불러와 신스 소리로 대신한 트랙 이름들.
 */
export async function play(project: Project, muted: Record<string, boolean>, fromBeats = 0): Promise<string[]> {
  const request = ++playRequest
  await Tone.start() // 브라우저는 사용자가 클릭한 뒤에만 소리를 허용한다
  if (project !== loaded) load(project, muted)
  await Promise.all([...channels.values()].map((c) => c.voice.ready))
  if (request !== playRequest) return [] // 기다리는 사이 정지했거나 다른 파일을 열었음
  transport().start(undefined, ticks(fromBeats))
  return [...channels.values()].filter((c) => c.voice.fallback).map((c) => c.name)
}

export function stop() {
  playRequest++
  if (!loaded) return
  transport().stop() // 위치도 처음으로 돌아간다
  for (const c of channels.values()) c.voice.releaseAll()
}

/** 구간 반복 (박). null이면 끈다. 재생 중에 바꿔도 바로 적용된다 */
export function setLoop(loop: { start: number; end: number } | null) {
  const t = transport()
  if (loop) t.setLoopPoints(ticks(loop.start), ticks(loop.end))
  t.loop = !!loop
}

export function setMuted(trackId: string, muted: boolean) {
  const c = channels.get(trackId)
  if (c) c.volume.mute = muted
}

/** 드럼 소리 하나의 크기를 바로 바꾼다 (저장 전 미리 듣기, 1 = 그대로) */
export function setLaneGain(trackId: string, pitch: number, gain: number) {
  channels.get(trackId)?.voice.setLaneGain?.(pitch, gain)
}

/** 트랙 볼륨 · 팬을 바로 바꾼다 (슬라이더를 끄는 동안 들으면서 맞추기) */
export function setMix(trackId: string, volume: number, pan: number) {
  const c = channels.get(trackId)
  if (!c) return
  c.fader.volume.rampTo(faderDb(volume), 0.05)
  c.panner.pan.rampTo(panValue(pan), 0.05)
}

// 볼륨 · 팬을 뺀 나머지(음 · 악기 · 템포)가 같은지 보는 열쇠
const soundKey = (p: Project) =>
  JSON.stringify({ ...p, id: 0, version: 0, name: '', warnings: [], tracks: p.tracks.map((t) => ({ ...t, volume: 0, pan: 0 })) })

/**
 * 불러 둔 곡과 볼륨 · 팬만 다른 새 버전이면, 다시 불러오지 않고 볼륨 · 팬만 바꾼 뒤 그 버전을 쓴다.
 * 재생 중에 끊기지 않게 하려는 것. 그렇게 했으면 true.
 */
export function adoptMix(project: Project): boolean {
  if (!loaded || loaded === project || soundKey(loaded) !== soundKey(project)) return false
  for (const t of project.tracks) setMix(t.id, t.volume, t.pan)
  loaded = project
  return true
}

/** 지금 들리고 있는 위치(박). 예약용 lookahead를 빼고 실제 소리 기준으로 계산한다. */
export function positionBeats(): number {
  const t = transport()
  return t.getTicksAtTime(Tone.immediate()) / t.PPQ
}

export function setOnEnd(cb: () => void) {
  onEnd = cb
}
