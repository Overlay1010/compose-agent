import { useEffect, useMemo, useRef, useState } from 'react'
import type { Note, Track } from '../api/types'
import { DRUM_NAMES, DRUM_ROLES, DRUM_SOUNDS, drumSoundOf } from '../audio/instruments'
import * as player from '../audio/player'
import { positionBeats } from '../audio/player'
import { setNoteKeys } from '../shortcuts'
import { useChat } from '../store/chat'
import type { Selection } from '../selection'
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
const NO_PICK = new Set<number>()
const keyOf = (n: Note) => `${n.pitch}|${n.start}|${n.duration}|${n.velocity}`
const snap = (beat: number) => Math.round(beat * 4) / 4 // 16분음표

type Drag = {
  x: number
  y: number
  moved: boolean
  // range = 빈 곳 끌기(구간 · 음 고르기), move = 음 옮기기, resize = 음 길이
  mode: 'range' | 'move' | 'resize'
  picked?: Set<number>
  lastY?: number
}

export function PianoRoll() {
  const { project, preview, hearPreview, selectedTrackId, selection, setSelection, busy, setNotes } = useProject()
  const { sending, note } = useChat()
  // 그린 모양 (마우스 좌표 → 박 · 음 번호로 바꾸는 데 씀)
  const layout = useRef<{ keyPx: number; rowPx: number; rows: number[]; lengthBeats: number } | null>(null)
  const drag = useRef<Drag | null>(null)
  const lastLength = useRef(1) // 더블클릭으로 넣을 음 길이 (마지막으로 바꾼 길이)
  const [draft, setDraft] = useState<Selection | null>(null)
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
  // 드럼 레인 순서 (그리기와 같은 규칙: 쓰인 소리를 위에서부터 높은 번호 순). 고른 부분 띠를 그릴 때 쓴다
  const drumRows = useMemo(
    () =>
      track?.is_drum
        ? [...new Set([...track.notes, ...(showDiff && diff ? diff.added : [])].map((n) => n.pitch))].sort((a, b) => b - a)
        : [],
    [track, diff, showDiff],
  )

  // 음 직접 편집: 고른 음(지금 버전 트랙의 음 순서)과 끄는 동안 보여 줄 임시 음 목록.
  // 고른 음은 버전이 바뀌면 자동으로 풀린다 (저장 직후에는 옮긴 음을 새 버전에서 다시 찾아 고른다)
  const editKey = `${realTrack?.id}:${project?.version}`
  const [pickedState, setPickedState] = useState<{ key: string; set: Set<number> }>({ key: '', set: NO_PICK })
  const picked = pickedState.key === editKey ? pickedState.set : NO_PICK
  const setPicked = (set: Set<number>, key = editKey) => setPickedState({ key, set })
  const [editNotes, setEditNotes] = useState<Note[] | null>(null)
  // 미리보기가 이 트랙의 음을 바꾸고 있으면 음 순서가 어긋날 수 있어 직접 편집을 막는다.
  // 다른 트랙만 바꾸는 미리보기라면 고칠 수 있다 (저장할 때 미리보기에도 같이 들어감)
  const lockedByPreview = !!preview && (!previewTrack || changed)
  const editable = !!realTrack && !lockedByPreview && !busy && !sending
  // 잠긴 트랙에서 음을 누르면 안내를 잠깐 깜빡인다 (아무 반응이 없으면 고장처럼 보여서)
  const [nudge, setNudge] = useState(0)
  const poke = () => {
    if (!lockedByPreview) return
    setNudge(Date.now())
    setTimeout(() => setNudge(0), 1600)
  }

  /** 고친 음 목록을 저장하고, 옮긴 음들은 새 버전에서도 골라 둔다 */
  const commit = async (notes: Note[], label: string, keep: Note[]) => {
    if (!realTrack) return
    const changed = await setNotes(realTrack.id, notes, `${realTrack.name} ${label}`)
    setEditNotes(null)
    if (!changed?.note) return
    note(changed.note, true)
    const fresh = changed.project.tracks.find((t) => t.id === realTrack.id)
    const again = new Set<number>()
    for (const k of keep.map(keyOf)) {
      const i = fresh?.notes.findIndex((n, j) => !again.has(j) && keyOf(n) === k) ?? -1
      if (i >= 0) again.add(i)
    }
    setPicked(again, `${realTrack.id}:${changed.project.version}`)
  }

  /** 마우스 위치 계산: 어떤 음 위인지(끝 부분이면 길이 바꾸기), 몇 박 · 어떤 음 번호 줄인지 */
  const geom = () => {
    const L = layout.current
    if (!L || !realTrack) return null
    const rowIndex = new Map(L.rows.map((p, i) => [p, i]))
    const box = (n: Note) => {
      const w = realTrack.is_drum ? 6 : Math.max(n.duration * BEAT_PX - 2, 2)
      return { x: L.keyPx + n.start * BEAT_PX + 1, y: 20 + (rowIndex.get(n.pitch) ?? -99) * L.rowPx, w, h: L.rowPx }
    }
    const hit = (x: number, y: number) => {
      const notes = realTrack.notes
      for (let i = notes.length - 1; i >= 0; i--) {
        const b = box(notes[i])
        if (x >= b.x - 2 && x <= b.x + Math.max(b.w, 8) + 2 && y >= b.y && y < b.y + b.h) {
          return { i, edge: !realTrack.is_drum && b.w > 12 && x > b.x + b.w - 6 }
        }
      }
      return null
    }
    const rowAt = (y: number) => Math.min(L.rows.length - 1, Math.max(0, Math.floor((y - 20) / L.rowPx)))
    return { L, rowIndex, hit, rowAt, beatAt: (x: number) => Math.max(0, (x - L.keyPx) / BEAT_PX) }
  }

  // 음을 골랐을 때의 키 (Delete · ↑↓ · Ctrl+A · Esc). 단축키보다 먼저 받는다 (shortcuts.ts)
  useEffect(() => {
    if (!realTrack) return
    setNoteKeys((e) => {
      if (e.key === 'Escape' && picked.size) {
        setPicked(NO_PICK)
        return true
      }
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyA') {
        setPicked(new Set(realTrack.notes.map((_, i) => i)))
        return true
      }
      if (!picked.size || !editable) return false
      if (e.key === 'Delete' || e.key === 'Backspace') {
        void commit(realTrack.notes.filter((_, i) => !picked.has(i)), `음 ${picked.size}개 지움`, [])
        return true
      }
      if (!realTrack.is_drum && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const d = (e.key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 12 : 1)
        const moved = realTrack.notes.map((n, i) => (picked.has(i) ? { ...n, pitch: n.pitch + d } : n))
        if (moved.some((n) => n.pitch < 0 || n.pitch > 127)) return true // MIDI 음 범위 밖으로는 안 옮김
        const how = `${Math.abs(d) === 12 ? '한 옥타브' : '반음'} ${d > 0 ? '올림' : '내림'}`
        void commit(moved, `음 ${picked.size}개 ${how}`, moved.filter((_, i) => picked.has(i)))
        return true
      }
      return false
    })
    return () => setNoteKeys(null)
  })

  useEffect(() => {
    const el = canvas.current
    if (!el || !project || !track) return

    const beatsPerBar = (project.time_signature[0] * 4) / project.time_signature[1]
    // 줄과 길이는 원래 음 + 바뀐 음을 모두 담게 잡는다 (조옮김으로 음역이 넓어질 수 있음)
    const all: Note[] = showDiff && diff ? [...track.notes, ...diff.added] : track.notes
    // 끄는 동안은 임시 음 목록을 그린다 (줄 배치는 원래 음 기준으로 고정해 화면이 출렁이지 않게)
    const shown = !showDiff && editNotes ? editNotes : track.notes
    // 음을 다 지운 멜로디 트랙도 더블클릭으로 음을 넣을 수 있게 C3~C5 · 4마디 빈 칸을 보여 준다
    const basis: Note[] = all.length
      ? all
      : track.is_drum || showDiff
        ? []
        : [{ pitch: 48, start: 0, duration: beatsPerBar * 4, velocity: 1 }, { pitch: 72, start: 0, duration: 1, velocity: 1 }]
    if (basis.length === 0) {
      // 음이 하나도 없는 트랙 (다 지웠거나, 원래 소리로 보는 새 트랙)
      el.width = 0
      el.height = 0
      el.style.width = '0px'
      el.style.height = '0px'
      return
    }
    const pitches = basis.map((n) => n.pitch)
    // 위에서부터 그릴 줄(음 번호) 목록. 멜로디는 음역 전체(위아래 2칸 여유), 드럼은 쓰인 음만.
    const rows = track.is_drum
      ? [...new Set(pitches)].sort((a, b) => b - a)
      : Array.from({ length: Math.max(...pitches) - Math.min(...pitches) + 5 }, (_, i) => Math.max(...pitches) + 2 - i)
    const rowPx = track.is_drum ? DRUM_ROW_PX : ROW_PX
    const keyPx = track.is_drum ? DRUM_KEY_PX : KEY_PX
    const rowIndex = new Map(rows.map((p, i) => [p, i]))
    const lengthBeats = Math.ceil(Math.max(...[...basis, ...shown].map((n) => n.start + n.duration)) / beatsPerBar) * beatsPerBar

    const width = keyPx + lengthBeats * BEAT_PX
    const height = rows.length * rowPx + 20
    layout.current = { keyPx, rowPx, rows, lengthBeats }
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
    const plain = showDiff && diff ? diff.same : shown
    const noteColor = trackColor(project, track.id)
    for (const n of plain) {
      if (!rowIndex.has(n.pitch)) continue
      ctx.globalAlpha = 0.45 + (n.velocity / 127) * 0.55
      ctx.fillStyle = noteColor
      ctx.fillRect(...box(n))
    }
    ctx.globalAlpha = 1
    // 고른 음: 밝은 테두리
    if (!showDiff) {
      ctx.strokeStyle = color('--text')
      ctx.lineWidth = 1.5
      for (const i of picked) {
        const n = shown[i]
        if (!n || !rowIndex.has(n.pitch)) continue
        const [x, by, w, h] = box(n)
        ctx.strokeRect(x + 0.5, by + 0.5, w - 1, h - 1)
      }
      ctx.lineWidth = 1
    }
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
  }, [project, track, diff, showDiff, editNotes, picked])

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
      <p className={lockedByPreview ? (nudge ? 'roll-help locked nudge' : 'roll-help locked') : 'roll-help'} key={nudge}>
        {lockedByPreview
          ? '미리보기가 이 트랙의 음을 바꾸고 있어서 직접 고칠 수 없어요 — 채팅 아래 미리보기를 적용하거나 취소하면 돼요 · 빈 곳 끌기로 부분 고르기는 돼요'
          : '더블클릭 음 추가 · 음 끌기 옮기기 · 끝 끌기 길이 · 오른쪽 클릭 · Delete 지우기 · 빈 곳 끌기 고르기 (Shift 더하기)'}
      </p>
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
          <canvas
            ref={canvas}
            className="roll-grid"
            onContextMenu={(e) => e.preventDefault()}
            onPointerDown={(e) => {
              const g = geom()
              const r = e.currentTarget.getBoundingClientRect()
              const x = e.clientX - r.left
              const y = e.clientY - r.top
              if (!g || x < g.L.keyPx) return
              const hit = g.hit(x, y)
              if (e.button === 2) {
                // 오른쪽 클릭 = 그 음 지우기
                if (hit && editable) void commit(realTrack!.notes.filter((_, i) => i !== hit.i), '음 1개 지움', [])
                else if (hit) poke()
                return
              }
              if (e.button !== 0) return
              e.currentTarget.setPointerCapture(e.pointerId)
              if (hit && !editable) poke()
              if (hit && editable) {
                const next = picked.has(hit.i) ? picked : new Set(e.shiftKey ? [...picked, hit.i] : [hit.i])
                if (next !== picked) setPicked(next)
                drag.current = { x, y, moved: false, mode: hit.edge ? 'resize' : 'move', picked: next }
              } else {
                drag.current = { x, y, moved: false, mode: 'range' }
              }
            }}
            onPointerMove={(e) => {
              const d = drag.current
              const g = geom()
              const r = e.currentTarget.getBoundingClientRect()
              const x = e.clientX - r.left
              const y = e.clientY - r.top
              if (!d) {
                // 마우스만 올렸을 때: 음 위면 잡기 · 끝이면 길이 커서
                const hit = g && editable ? g.hit(x, y) : null
                e.currentTarget.style.cursor = hit ? (hit.edge ? 'ew-resize' : 'grab') : ''
                return
              }
              const L = layout.current
              if (!g || !L || !track) return
              if (!d.moved && Math.hypot(x - d.x, y - d.y) < 4) return // 살짝 움직인 건 클릭으로
              d.moved = true
              if (d.mode !== 'range') {
                const notes = realTrack!.notes
                const db = snap((x - d.x) / BEAT_PX)
                if (d.mode === 'resize') {
                  setEditNotes(notes.map((n, i) => (d.picked!.has(i) ? { ...n, duration: Math.max(0.25, snap(n.duration + db)) } : n)))
                } else {
                  const dr = Math.round((y - d.y) / L.rowPx)
                  setEditNotes(
                    notes.map((n, i) => {
                      if (!d.picked!.has(i)) return n
                      const row = Math.min(L.rows.length - 1, Math.max(0, (g.rowIndex.get(n.pitch) ?? 0) + dr))
                      return { ...n, start: Math.max(0, Math.round((n.start + db) * 10000) / 10000), pitch: L.rows[row] }
                    }),
                  )
                }
                return
              }
              d.lastY = y
              const toBeat = (px: number) => Math.min(L.lengthBeats, Math.max(0, (px - L.keyPx) / BEAT_PX))
              const start = Math.floor(Math.min(toBeat(d.x), toBeat(x)) * 4) / 4 // 16분음표 단위
              const end = Math.max(start + 0.25, Math.ceil(Math.max(toBeat(d.x), toBeat(x)) * 4) / 4)
              let pitches: number[] | null = null
              if (track.is_drum) {
                // 드럼은 위아래로 끈 레인(소리)까지 고른다
                const row = (py: number) => Math.min(L.rows.length - 1, Math.max(0, Math.floor((py - 20) / L.rowPx)))
                const [a, b] = [row(d.y), row(y)].sort((m, n) => m - n)
                pitches = L.rows.slice(a, b + 1).sort((m, n) => m - n)
              }
              setDraft({ trackIds: [track.id], beats: [start, end], pitches })
            }}
            onPointerUp={() => {
              const d = drag.current
              drag.current = null
              if (!d) return
              if (d.mode === 'range') {
                const L = layout.current
                if (d.moved && draft && L && realTrack) {
                  setSelection(draft)
                  // 끈 사각형 안의 음도 고른다 (직접 옮기기 · 지우기용)
                  const [a, b] = [d.y, d.lastY ?? d.y].map((v) => Math.min(L.rows.length - 1, Math.max(0, Math.floor((v - 20) / L.rowPx))))
                  const inRows = new Set(L.rows.slice(Math.min(a, b), Math.max(a, b) + 1))
                  const inside = realTrack.notes.flatMap((n, i) =>
                    n.start >= draft.beats[0] - 1e-6 && n.start < draft.beats[1] - 1e-6 && inRows.has(n.pitch) ? [i] : [],
                  )
                  setPicked(new Set(inside))
                } else {
                  // 그냥 누르면 고른 부분 · 고른 음을 푼다
                  setSelection(null)
                  setPicked(NO_PICK)
                }
                setDraft(null)
                return
              }
              if (!d.moved || !editNotes) {
                setEditNotes(null)
                return
              }
              const label = d.mode === 'resize' ? `음 ${d.picked!.size}개 길이 바꿈` : `음 ${d.picked!.size}개 옮김`
              if (d.mode === 'resize') lastLength.current = editNotes[[...d.picked!][0]]?.duration ?? lastLength.current
              void commit(editNotes, label, editNotes.filter((_, i) => d.picked!.has(i)))
            }}
            onPointerCancel={() => {
              drag.current = null
              setDraft(null)
              setEditNotes(null)
            }}
            onDoubleClick={(e) => {
              // 빈 곳 더블클릭 = 그 자리에 음 추가 (16분음표 격자, 길이는 마지막으로 바꾼 길이)
              const g = geom()
              const r = e.currentTarget.getBoundingClientRect()
              const x = e.clientX - r.left
              const y = e.clientY - r.top
              if (g && !editable && x >= g.L.keyPx) poke()
              if (!g || !editable || !realTrack || x < g.L.keyPx || g.hit(x, y)) return
              const notes = realTrack.notes
              const velocity = notes.length ? Math.round(notes.reduce((s, n) => s + n.velocity, 0) / notes.length) : 100
              const added: Note = {
                pitch: g.L.rows[g.rowAt(y)],
                start: Math.floor(g.beatAt(x) * 4) / 4,
                duration: realTrack.is_drum ? 0.25 : lastLength.current,
                velocity,
              }
              void commit([...notes, added], '음 1개 추가', [added])
            }}
          />
          <SelectionBox
            selection={draft ?? selection}
            trackId={track.id}
            layout={{ keyPx: track.is_drum ? DRUM_KEY_PX : KEY_PX, rowPx: track.is_drum ? DRUM_ROW_PX : ROW_PX, rows: drumRows }}
          />
          <div className="playhead" ref={head} />
        </div>
      </div>
      {realTrack && !realTrack.is_drum && realTrack.notes.length > 0 && (
        <VelocityLane
          track={realTrack}
          beatsPerBar={(project.time_signature[0] * 4) / project.time_signature[1]}
          scroller={scroller}
          locked={lockedByPreview}
        />
      )}
      {realTrack?.is_drum && realTrack.notes.length > 0 && <DrumLanes track={realTrack} />}
    </section>
  )
}

/** 고른 부분을 피아노롤 위에 띠로 그린다 (이 트랙이 포함될 때만) */
function SelectionBox({
  selection,
  trackId,
  layout,
}: {
  selection: Selection | null
  trackId: string
  layout: { keyPx: number; rowPx: number; rows: number[] } | null
}) {
  if (!selection || !layout || (selection.trackIds && !selection.trackIds.includes(trackId))) return null
  const left = layout.keyPx + selection.beats[0] * BEAT_PX
  const width = (selection.beats[1] - selection.beats[0]) * BEAT_PX
  let top = 20
  let height: number | undefined
  if (selection.pitches?.length) {
    const idx = selection.pitches.map((p) => layout.rows.indexOf(p)).filter((i) => i >= 0)
    if (idx.length) {
      top = 20 + Math.min(...idx) * layout.rowPx
      height = (Math.max(...idx) - Math.min(...idx) + 1) * layout.rowPx
    }
  }
  return <div className="roll-selection" style={{ left, width, top, height, bottom: height === undefined ? 0 : undefined }} aria-hidden="true" />
}

const VEL_PX = 72 // 벨로시티 편집창 높이 (세기 127 = 맨 위)
const BAR_PX = 4 // 막대 폭

/**
 * 벨로시티 편집창 (DAW의 벨로시티 레인). 음마다 막대 높이 = 세기.
 * 누르면 그 자리 음, 끌면 지나간 음들의 세기를 마우스 높이로 바꾸고, 손을 떼면 한 번만 새 버전으로 저장한다.
 * 같은 시각의 화음은 함께 바뀐다. 미리보기가 있으면 음 순서가 달라질 수 있어 편집을 막는다.
 */
function VelocityLane({
  track,
  beatsPerBar,
  scroller,
  locked,
}: {
  track: Track
  beatsPerBar: number
  scroller: React.RefObject<HTMLDivElement | null>
  locked: boolean // 미리보기가 이 트랙의 음을 바꾸고 있을 때
}) {
  const { project, busy, setVelocities } = useProject()
  const { sending, note } = useChat()
  const canvas = useRef<HTMLCanvasElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState<Map<number, number>>(new Map())
  const drag = useRef<{ lastX: number } | null>(null)
  const lengthBeats = Math.ceil(Math.max(...track.notes.map((n) => n.start + n.duration)) / beatsPerBar) * beatsPerBar
  const width = KEY_PX + lengthBeats * BEAT_PX
  const barX = (n: Note) => KEY_PX + n.start * BEAT_PX + 1

  // 피아노롤을 가로로 스크롤하면 같이 따라간다
  useEffect(() => {
    const roll = scroller.current
    if (!roll) return
    const follow = () => {
      if (box.current) box.current.scrollLeft = roll.scrollLeft
    }
    follow()
    roll.addEventListener('scroll', follow)
    return () => roll.removeEventListener('scroll', follow)
  }, [scroller])

  useEffect(() => {
    const el = canvas.current
    if (!el || !project) return
    const dpr = window.devicePixelRatio || 1
    el.width = width * dpr
    el.height = VEL_PX * dpr
    el.style.width = `${width}px`
    el.style.height = `${VEL_PX}px`
    const ctx = el.getContext('2d')!
    ctx.scale(dpr, dpr)
    const css = getComputedStyle(document.documentElement)
    const color = (v: string) => css.getPropertyValue(v).trim()
    ctx.fillStyle = color('--surface')
    ctx.fillRect(0, 0, width, VEL_PX)
    // 마디선 + 세기 64 · 127 기준선
    for (let b = 0; b <= lengthBeats; b += beatsPerBar) {
      ctx.fillStyle = color('--grid-strong')
      ctx.fillRect(KEY_PX + b * BEAT_PX, 0, 1, VEL_PX)
    }
    ctx.fillStyle = color('--grid')
    ctx.fillRect(KEY_PX, Math.round(VEL_PX / 2), width - KEY_PX, 1)
    ctx.fillStyle = color('--surface-2')
    ctx.fillRect(0, 0, KEY_PX - 1, VEL_PX)
    ctx.fillStyle = color('--text-quiet')
    ctx.font = '10px system-ui'
    ctx.fillText('세기', 8, 14)
    ctx.fillText('127', 8, 27) // 막대 맨 위 = 127
    ctx.fillText('1', 8, VEL_PX - 6)

    const noteColor = trackColor(project, track.id)
    track.notes.forEach((n, i) => {
      const v = draft.get(i) ?? n.velocity
      const h = Math.max(2, (v / 127) * (VEL_PX - 6))
      const x = barX(n)
      ctx.fillStyle = draft.has(i) ? color('--change') : noteColor
      ctx.globalAlpha = locked ? 0.35 : 0.9
      ctx.fillRect(x, VEL_PX - h, BAR_PX - 1, h)
      ctx.fillRect(x - 1, VEL_PX - h, BAR_PX + 1, 2) // 머리
    })
    ctx.globalAlpha = 1
  }, [project, track, draft, width, lengthBeats, beatsPerBar, locked])

  const velocityAt = (y: number) => Math.max(1, Math.min(127, Math.round((1 - (y - 3) / (VEL_PX - 6)) * 127)))

  /** x1~x2(캔버스 좌표) 사이 막대의 음들을 세기 v로 */
  const paint = (x1: number, x2: number, v: number) => {
    const lo = Math.min(x1, x2) - BAR_PX
    const hi = Math.max(x1, x2) + 1
    setDraft((prev) => {
      const next = new Map(prev)
      track.notes.forEach((n, i) => {
        const x = barX(n)
        if (x >= lo && x <= hi) next.set(i, v)
      })
      return next
    })
  }

  const commit = async () => {
    drag.current = null
    const changes = [...draft.entries()].map(([index, velocity]) => ({ index, velocity }))
    if (!changes.length) return
    const changed = await setVelocities(track.id, changes)
    setDraft(new Map())
    if (changed?.note) note(changed.note, true)
  }

  const disabled = locked || busy || sending
  return (
    <div className="vel-lane">
      <div className="vel-head">
        <h3>벨로시티</h3>
        <span className="info">
          {locked ? '미리보기가 이 트랙을 바꾸고 있어요 — 적용하거나 취소한 뒤 편집할 수 있어요' : '막대를 누르거나 끌어서 음마다 세기를 바꿔요 · 손을 떼면 저장 (MIDI에도 남아요)'}
        </span>
      </div>
      <div className="vel-scroll" ref={box}>
        <canvas
          ref={canvas}
          className={disabled ? 'locked' : undefined}
          aria-label={`${track.name} 벨로시티 편집`}
          onPointerDown={(e) => {
            if (disabled || e.button !== 0) return
            e.currentTarget.setPointerCapture(e.pointerId)
            const r = e.currentTarget.getBoundingClientRect()
            const x = e.clientX - r.left
            drag.current = { lastX: x }
            paint(x, x, velocityAt(e.clientY - r.top))
          }}
          onPointerMove={(e) => {
            if (!drag.current) return
            const r = e.currentTarget.getBoundingClientRect()
            const x = e.clientX - r.left
            paint(drag.current.lastX, x, velocityAt(e.clientY - r.top))
            drag.current.lastX = x
          }}
          onPointerUp={() => void commit()}
          onPointerCancel={() => {
            drag.current = null
            setDraft(new Map())
          }}
        />
      </div>
    </div>
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
        소리별 소리 · 크기{' '}
        <span className="info">소리는 이 앱에만 저장돼요 · 크기는 그 소리 음들의 세기를 바꿔 MIDI에도 남아요</span>
      </h3>
      <div className="lane-grid">
        {lanes.map((l) => (
          <div className="lane" key={l.pitch}>
            <span className="lane-name">{DRUM_NAMES[l.pitch] ?? noteName(l.pitch)}</span>
            <SoundPicker track={track} pitch={l.pitch} />
            <LaneSlider key={`${track.id}:${l.pitch}:${l.level}`} trackId={track.id} pitch={l.pitch} level={l.level} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** 레인 하나의 소리 고르기: 킷 기본 소리 + 같은 역할의 다른 소리 */
function SoundPicker({ track, pitch }: { track: Track; pitch: number }) {
  const { busy, setDrumSound } = useProject()
  const { sending, note } = useChat()
  const role = DRUM_ROLES[pitch]
  if (!role) return <span className="lane-sound none">바꿀 수 있는 소리 없음</span>
  const picked = track.drum_sounds?.[pitch]
  const kitSound = drumSoundOf(track.program, pitch)!
  return (
    <select
      className="lane-sound"
      value={picked ?? 'default'}
      disabled={busy || sending}
      aria-label={`${DRUM_NAMES[pitch] ?? pitch} 소리`}
      onChange={async (e) => {
        const changed = await setDrumSound(track.id, pitch, e.target.value)
        if (changed?.note) note(changed.note, true)
      }}
    >
      <option value="default">{DRUM_SOUNDS[kitSound].name} (킷 기본)</option>
      {Object.entries(DRUM_SOUNDS)
        .filter(([id, s]) => s.role === role && id !== kitSound)
        .map(([id, s]) => (
          <option key={id} value={id}>
            {s.name}
          </option>
        ))}
    </select>
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
    <label className="lane-level" title={`${name} 평균 세기 (1~127)`}>
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
