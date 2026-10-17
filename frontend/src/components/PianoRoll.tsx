import { useEffect, useMemo, useRef, useState } from 'react'
import type { Note, Track } from '../api/types'
import { DRUM_NAMES } from '../audio/instruments'
import * as player from '../audio/player'
import { positionBeats } from '../audio/player'
import { useChat } from '../store/chat'
import { usePlayer } from '../store/player'
import { diffNotes } from '../diff'
import { useProject } from '../store/project'
import { trackColor } from '../theme'
import { EmptyState } from './EmptyState'
import { Overview } from './Overview'

const BEAT_PX = 24 // 1박의 가로 길이
const ROW_PX = 12 // 반음 1칸의 세로 길이
const KEY_PX = 48 // 왼쪽 건반 영역
// 드럼 트랙은 DAW 드럼 에디터처럼 쓰인 소리만 이름 붙은 레인으로 보여 준다
const DRUM_ROW_PX = 18
const DRUM_KEY_PX = 92
const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

const noteName = (pitch: number) => `${NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`

export function PianoRoll() {
  const { project, preview, hearPreview, selectedTrackId } = useProject()
  const playing = usePlayer((s) => s.playing)
  const cursor = usePlayer((s) => s.cursor)
  const canvas = useRef<HTMLCanvasElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const head = useRef<HTMLDivElement>(null)
  const realTrack = project?.tracks.find((t) => t.id === selectedTrackId)
  const previewTrack = preview?.tracks.find((t) => t.id === selectedTrackId)
  // 미리보기에만 있는 새 트랙은 "원래 음이 없는 트랙"으로 보고 음 전부를 바뀔 음으로 그린다
  const isNew = !realTrack && !!previewTrack
  const track = useMemo(() => realTrack ?? (previewTrack ? { ...previewTrack, notes: [] } : undefined), [realTrack, previewTrack])
  const diff = useMemo(() => (track && previewTrack ? diffNotes(track.notes, previewTrack.notes) : null), [track, previewTrack])
  const changed = !!diff && (diff.added.length > 0 || diff.removed.length > 0)
  // 미리보기에서 바뀐 트랙이고 "바뀐 소리"를 듣는 중이면 바뀔 음 · 원래 위치를 같이 그린다
  const showDiff = changed && hearPreview

  useEffect(() => {
    const el = canvas.current
    if (!el || !project || !track) return

    const beatsPerBar = (project.time_signature[0] * 4) / project.time_signature[1]
    // 줄과 길이는 원래 음 + 바뀐 음을 모두 담게 잡는다 (조옮김으로 음역이 넓어질 수 있음)
    const all: Note[] = showDiff && diff ? [...track.notes, ...diff.added] : track.notes
    if (all.length === 0) {
      // 음이 하나도 없는 트랙 (다 지웠거나, 원래 소리로 보는 새 트랙)
      el.width = 0
      el.height = 0
      el.style.width = '0px'
      el.style.height = '0px'
      return
    }
    const pitches = all.map((n) => n.pitch)
    // 위에서부터 그릴 줄(음 번호) 목록. 멜로디는 음역 전체(위아래 2칸 여유), 드럼은 쓰인 음만.
    const rows = track.is_drum
      ? [...new Set(pitches)].sort((a, b) => b - a)
      : Array.from({ length: Math.max(...pitches) - Math.min(...pitches) + 5 }, (_, i) => Math.max(...pitches) + 2 - i)
    const rowPx = track.is_drum ? DRUM_ROW_PX : ROW_PX
    const keyPx = track.is_drum ? DRUM_KEY_PX : KEY_PX
    const rowIndex = new Map(rows.map((p, i) => [p, i]))
    const lengthBeats = Math.ceil(Math.max(...all.map((n) => n.start + n.duration)) / beatsPerBar) * beatsPerBar

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
        ctx.fillStyle = color('--surface-2')
        ctx.fillRect(0, y(p), keyPx, rowPx)
        ctx.fillStyle = color('--text-2')
        ctx.fillText(DRUM_NAMES[p] ?? noteName(p), 8, y(p) + rowPx - 4)
      } else {
        // 왼쪽 건반 (흰건반 · 검은건반) + 검은 건반 줄 + C마다 음 이름
        const black = [1, 3, 6, 8, 10].includes(p % 12)
        if (black) {
          ctx.fillStyle = color('--row-dark')
          ctx.fillRect(keyPx, y(p), width - keyPx, rowPx)
        }
        ctx.fillStyle = black ? color('--key-black') : color('--key-white')
        ctx.fillRect(0, y(p), keyPx - 1, rowPx)
        if (!black) {
          ctx.fillStyle = color('--key-line')
          ctx.fillRect(0, y(p) + rowPx - 1, keyPx - 1, 1)
        }
        if (p % 12 === 0) {
          ctx.fillStyle = color('--key-label')
          ctx.fillText(noteName(p), 4, y(p) + rowPx - 1)
          // 옥타브 경계선
          ctx.fillStyle = color('--grid-strong')
          ctx.fillRect(keyPx, y(p) + rowPx - 1, width - keyPx, 1)
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
    const box = (n: Note) => {
      const w = track.is_drum ? 6 : Math.max(n.duration * BEAT_PX - 2, 2)
      const inset = track.is_drum ? 3 : 1
      return [keyPx + n.start * BEAT_PX + 1, y(n.pitch) + inset, w, rowPx - inset * 2] as const
    }
    const plain = showDiff && diff ? diff.same : track.notes
    const noteColor = trackColor(project, track.id)
    for (const n of plain) {
      ctx.globalAlpha = 0.45 + (n.velocity / 127) * 0.55
      ctx.fillStyle = noteColor
      ctx.fillRect(...box(n))
    }
    ctx.globalAlpha = 1
    if (showDiff && diff) {
      // 원래 위치: 점선 테두리
      ctx.setLineDash([3, 2])
      ctx.strokeStyle = color('--text-quiet')
      ctx.lineWidth = 1
      for (const n of diff.removed) {
        const [x, by, w, h] = box(n)
        ctx.strokeRect(x + 0.5, by + 0.5, w - 1, h - 1)
      }
      ctx.setLineDash([])
      // 바뀔 음: 라임 + 진한 테두리 (세기는 진하기로)
      for (const n of diff.added) {
        const [x, by, w, h] = box(n)
        ctx.globalAlpha = 0.6 + (n.velocity / 127) * 0.4
        ctx.fillStyle = color('--change')
        ctx.fillRect(x, by, w, h)
        ctx.globalAlpha = 1
        ctx.strokeStyle = color('--change-line')
        ctx.strokeRect(x + 0.5, by + 0.5, w - 1, h - 1)
      }
    }
  }, [project, track, diff, showDiff])

  // 재생선: 매 프레임 지금 들리는 위치로 옮기고, 화면 밖으로 나가면 따라가며 스크롤한다.
  useEffect(() => {
    const el = head.current
    const box = scroller.current
    if (!el || !box) return
    const keyPx = track?.is_drum ? DRUM_KEY_PX : KEY_PX
    if (!playing) {
      // 멈춰 있을 때는 시작 위치에 재생선을 두고, 화면 밖이면 그쪽으로 스크롤
      el.style.display = cursor > 0 ? 'block' : 'none'
      const x = keyPx + cursor * BEAT_PX
      el.style.transform = `translateX(${x}px)`
      if (cursor > 0 && (x > box.scrollLeft + box.clientWidth - 40 || x < box.scrollLeft + keyPx)) box.scrollLeft = x - keyPx - 40
      return
    }
    el.style.display = 'block'
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
  }, [playing, track, cursor])

  if (!project) return <EmptyState />
  if (!track) return <section className="empty">트랙을 선택해 주세요.</section>

  return (
    <section className="roll">
      <Overview />
      <h2>
        {track.name}{' '}
        <span className="info">
          {track.is_drum ? '드럼 레인 · 진할수록 세게' : '마디 번호 기준 · 진할수록 세게'}
        </span>
      </h2>
      {showDiff && diff && (
        <p className="legend">
          <strong>미리보기 중</strong>
          {isNew ? (
            <span>
              <i className="swatch change" aria-hidden="true" />
              새 트랙 · 음 {diff.added.length}개 (적용하면 생겨요)
            </span>
          ) : (
            <>
              {diff.added.length > 0 && (
                <span>
                  <i className="swatch change" aria-hidden="true" />
                  바뀔 음 {diff.added.length}개
                </span>
              )}
              <span>
                <i className="swatch ghost" aria-hidden="true" />
                {/* 지우기만 한 편집이면 점선 음은 "사라질 음"이다 */}
                {diff.added.length > 0 ? '원래 위치' : `지울 음 ${diff.removed.length}개`}
              </span>
            </>
          )}
        </p>
      )}
      {changed && !hearPreview && (
        <p className="legend">
          {isNew ? '원래 소리에는 없는 새 트랙이에요. "바뀐 소리"를 고르면 보여요.' : '원래 소리를 듣는 중이에요 (미리보기 적용 전 상태)'}
        </p>
      )}
      {!changed && track.notes.length === 0 && <p className="legend">이 트랙에는 음이 없어요.</p>}
      <div className="roll-scroll" ref={scroller}>
        <div className="roll-canvas">
          <canvas ref={canvas} />
          <div className="playhead" ref={head} />
        </div>
      </div>
      {realTrack?.is_drum && realTrack.notes.length > 0 && <DrumLanes track={realTrack} />}
    </section>
  )
}

const average = (notes: Note[]) => Math.round(notes.reduce((s, n) => s + n.velocity, 0) / notes.length)

/**
 * 드럼 소리(레인)별 크기. 슬라이더는 그 소리의 평균 세기(1~127)를 보여 주고,
 * 끄는 동안은 소리만 바로 바꾸고(저장 X), 손을 떼면 그 소리 음들의 세기를 같은 비율로 바꿔 새 버전으로 저장한다.
 */
function DrumLanes({ track }: { track: Track }) {
  const lanes = useMemo(() => {
    const byPitch = new Map<number, Note[]>()
    for (const n of track.notes) byPitch.set(n.pitch, [...(byPitch.get(n.pitch) ?? []), n])
    return [...byPitch.entries()].sort((a, b) => a[0] - b[0]).map(([pitch, notes]) => ({ pitch, level: average(notes) }))
  }, [track])

  return (
    <div className="lanes">
      <h3>
        소리별 크기 <span className="info">손을 떼면 그 소리 음들의 세기를 바꿔 저장해요 (MIDI에도 남아요)</span>
      </h3>
      <div className="lane-grid">
        {lanes.map((l) => (
          <LaneSlider key={`${track.id}:${l.pitch}:${l.level}`} trackId={track.id} pitch={l.pitch} level={l.level} />
        ))}
      </div>
    </div>
  )
}

function LaneSlider({ trackId, pitch, level }: { trackId: string; pitch: number; level: number }) {
  const { busy, setLane } = useProject()
  const { sending, note } = useChat()
  const [value, setValue] = useState(level)
  const name = DRUM_NAMES[pitch] ?? noteName(pitch)

  const commit = async () => {
    if (value === level) return
    const changed = await setLane(trackId, pitch, Math.min(4, Math.max(0.1, value / level)))
    if (changed?.note) {
      note(changed.note, true)
    } else {
      player.setLaneGain(trackId, pitch, 1)
      setValue(level)
    }
  }

  return (
    <label title={`${name} 평균 세기 (1~127)`}>
      <span className="lane-name">{name}</span>
      <input
        type="range"
        min={Math.max(1, Math.round(level * 0.1))}
        max={127}
        value={value}
        disabled={busy || sending}
        aria-label={`${name} 크기`}
        onChange={(e) => {
          setValue(Number(e.target.value))
          player.setLaneGain(trackId, pitch, Number(e.target.value) / level)
        }}
        onPointerUp={() => void commit()}
        onKeyUp={() => void commit()}
      />
      <output>{value}</output>
    </label>
  )
}
