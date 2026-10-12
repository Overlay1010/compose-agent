import * as Tone from 'tone'
import type { Project } from '../api/types'
import { createVoice, type Voice } from './instruments'

// Project를 Tone.js Transport에 올려 재생한다.
// 시간은 백엔드처럼 박 단위로 다루고, Transport의 틱(1박 = PPQ틱)으로 바꿔 예약한다.
// Tone을 처음 건드리는 순간 AudioContext가 만들어지므로, 모든 호출은 재생 버튼을 누른 뒤에 일어나게 한다.

interface Channel {
  name: string
  voice: Voice
  volume: Tone.Volume
}

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
    voice.output.connect(volume)
    channels.set(track.id, { name: track.name, voice, volume })

    for (const n of track.notes) {
      t.schedule(
        once((time) => voice.play(n.pitch, ticks(n.duration), time, n.velocity)),
        ticks(n.start),
      )
      end = Math.max(end, n.start + n.duration)
    }
  }

  // 마지막 음이 끝나고 반 박 뒤에 멈춘다 (화면 갱신은 소리와 맞춰 Draw로).
  t.schedule((time) => {
    Tone.getDraw().schedule(() => {
      stop()
      onEnd?.()
    }, time)
  }, ticks(end + 0.5))

  loaded = project
}

/**
 * 재생한다. 처음이면 악기 샘플을 다 불러온 뒤 시작한다.
 * 돌려주는 값은 샘플을 못 불러와 신스 소리로 대신한 트랙 이름들.
 */
export async function play(project: Project, muted: Record<string, boolean>): Promise<string[]> {
  const request = ++playRequest
  await Tone.start() // 브라우저는 사용자가 클릭한 뒤에만 소리를 허용한다
  if (project !== loaded) load(project, muted)
  await Promise.all([...channels.values()].map((c) => c.voice.ready))
  if (request !== playRequest) return [] // 기다리는 사이 정지했거나 다른 파일을 열었음
  transport().start()
  return [...channels.values()].filter((c) => c.voice.fallback).map((c) => c.name)
}

export function stop() {
  playRequest++
  if (!loaded) return
  transport().stop() // 위치도 처음으로 돌아간다
  for (const c of channels.values()) c.voice.releaseAll()
}

export function setMuted(trackId: string, muted: boolean) {
  const c = channels.get(trackId)
  if (c) c.volume.mute = muted
}

/** 지금 들리고 있는 위치(박). 예약용 lookahead를 빼고 실제 소리 기준으로 계산한다. */
export function positionBeats(): number {
  const t = transport()
  return t.getTicksAtTime(Tone.immediate()) / t.PPQ
}

export function setOnEnd(cb: () => void) {
  onEnd = cb
}
