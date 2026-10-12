import { useEffect, useRef } from 'react'
import { DRUM_NAMES } from '../audio/instruments'
import { positionBeats } from '../audio/player'
import { usePlayer } from '../store/player'
import { useProject } from '../store/project'

const BEAT_PX = 24 // 1박의 가로 길이
const ROW_PX = 8 // 반음 1칸의 세로 길이
const KEY_PX = 40 // 왼쪽 음 이름 영역
// 드럼 트랙은 DAW 드럼 에디터처럼 쓰인 소리만 이름 붙은 레인으로 보여 준다
const DRUM_ROW_PX = 16
const DRUM_KEY_PX = 84
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

const noteName = (pitch: number) => `${NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`

export function PianoRoll() {
  const { project, selectedTrackId } = useProject()
  const playing = usePlayer((s) => s.playing)
  const canvas = useRef<HTMLCanvasElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const head = useRef<HTMLDivElement>(null)
  const track = project?.tracks.find((t) => t.id === selectedTrackId)

  useEffect(() => {
    const el = canvas.current
    if (!el || !project || !track || track.notes.length === 0) return

    const beatsPerBar = (project.time_signature[0] * 4) / project.time_signature[1]
    const pitches = track.notes.map((n) => n.pitch)
    // 위에서부터 그릴 줄(음 번호) 목록. 멜로디는 음역 전체(위아래 2칸 여유), 드럼은 쓰인 음만.
    const rows = track.is_drum
      ? [...new Set(pitches)].sort((a, b) => b - a)
      : Array.from({ length: Math.max(...pitches) - Math.min(...pitches) + 5 }, (_, i) => Math.max(...pitches) + 2 - i)
    const rowPx = track.is_drum ? DRUM_ROW_PX : ROW_PX
    const keyPx = track.is_drum ? DRUM_KEY_PX : KEY_PX
    const rowIndex = new Map(rows.map((p, i) => [p, i]))
    const lengthBeats = Math.ceil(Math.max(...track.notes.map((n) => n.start + n.duration)) / beatsPerBar) * beatsPerBar

    const width = keyPx + lengthBeats * BEAT_PX
    const height = rows.length * rowPx + 20
    const dpr = window.devicePixelRatio || 1
    el.width = width * dpr
    el.height = height * dpr
    el.style.width = `${width}px`
    el.style.height = `${height}px`

    const ctx = el.getContext('2d')!
    ctx.scale(dpr, dpr)
    const css = getComputedStyle(document.documentElement)
    const color = (v: string) => css.getPropertyValue(v).trim()

    ctx.fillStyle = color('--surface')
    ctx.fillRect(0, 0, width, height)

    const y = (pitch: number) => 20 + rowIndex.get(pitch)! * rowPx
    ctx.font = '10px system-ui'

    for (const [i, p] of rows.entries()) {
      if (track.is_drum) {
        // 레인 줄무늬 + 소리 이름 (GM 목록에 없으면 음 이름)
        if (i % 2 === 1) {
          ctx.fillStyle = color('--row-dark')
          ctx.fillRect(0, y(p), width, rowPx)
        }
        ctx.fillStyle = color('--text-quiet')
        ctx.fillText(DRUM_NAMES[p] ?? noteName(p), 6, y(p) + rowPx - 4)
      } else {
        // 검은 건반 줄 + 음 이름 (C만 표시)
        if ([1, 3, 6, 8, 10].includes(p % 12)) {
          ctx.fillStyle = color('--row-dark')
          ctx.fillRect(keyPx, y(p), width - keyPx, rowPx)
        }
        if (p % 12 === 0) {
          ctx.fillStyle = color('--text-quiet')
          ctx.fillText(noteName(p), 4, y(p) + rowPx - 1)
        }
      }
    }

    // 마디·박 세로선 + 마디 번호
    for (let b = 0; b <= lengthBeats; b++) {
      const x = keyPx + b * BEAT_PX
      const isBar = b % beatsPerBar === 0
      ctx.strokeStyle = color(isBar ? '--grid-strong' : '--grid')
      ctx.beginPath()
      ctx.moveTo(x + 0.5, 20)
      ctx.lineTo(x + 0.5, height)
      ctx.stroke()
      if (isBar && b < lengthBeats) {
        ctx.fillStyle = color('--text-quiet')
        ctx.font = '10px system-ui'
        ctx.fillText(String(b / beatsPerBar + 1), x + 3, 13)
      }
    }

    // 음표 (세기가 셀수록 진하게). 드럼은 길이보다 치는 순간이 중요해서 짧게 그린다.
    for (const n of track.notes) {
      ctx.globalAlpha = 0.45 + (n.velocity / 127) * 0.55
      ctx.fillStyle = color('--accent')
      const w = track.is_drum ? 6 : Math.max(n.duration * BEAT_PX - 2, 2)
      const inset = track.is_drum ? 3 : 1
      ctx.fillRect(keyPx + n.start * BEAT_PX + 1, y(n.pitch) + inset, w, rowPx - inset * 2)
    }
    ctx.globalAlpha = 1
  }, [project, track])

  // 재생선: 매 프레임 지금 들리는 위치로 옮기고, 화면 밖으로 나가면 따라가며 스크롤한다.
  useEffect(() => {
    const el = head.current
    const box = scroller.current
    if (!el || !box) return
    if (!playing) {
      el.style.display = 'none'
      return
    }
    el.style.display = 'block'
    const keyPx = track?.is_drum ? DRUM_KEY_PX : KEY_PX
    let raf = 0
    const frame = () => {
      const x = keyPx + positionBeats() * BEAT_PX
      el.style.transform = `translateX(${x}px)`
      if (x > box.scrollLeft + box.clientWidth - 40 || x < box.scrollLeft + keyPx) {
        box.scrollLeft = x - keyPx
      }
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => cancelAnimationFrame(raf)
  }, [playing, track])

  if (!project) {
    return (
      <section className="empty">
        <p>FL Studio에서 내보낸 MIDI 파일을 열어 보세요.</p>
        <p className="hint">File → Export → MIDI file… 로 내보낼 수 있어요.</p>
      </section>
    )
  }
  if (!track) return <section className="empty">트랙을 선택해 주세요.</section>

  return (
    <section className="roll">
      <h2>
        {track.name}{' '}
        <span className="info">
          {track.is_drum ? '드럼 레인 · 진할수록 세게' : '마디 번호 기준 · 진할수록 세게'}
        </span>
      </h2>
      <div className="roll-scroll" ref={scroller}>
        <div className="roll-canvas">
          <canvas ref={canvas} />
          <div className="playhead" ref={head} />
        </div>
      </div>
    </section>
  )
}
