import { useEffect, useMemo, useRef, useState } from 'react'
import type { Project } from '../api/types'
import { positionBeats } from '../audio/player'
import { diffNotes } from '../diff'
import { silenced, usePlayer } from '../store/player'
import { useProject } from '../store/project'
import { trackColor } from '../theme'

const ROW = 16
const LABEL = 72

/** 곡 전체를 트랙마다 한 줄로 작게 보여 준다. 누르면 그 위치로 옮긴다. */
export function Overview() {
  const { project, preview, hearPreview, selectedTrackId, selectTrack } = useProject()
  const { playing, cursor, seek, muted, solo } = usePlayer()
  const canvas = useRef<HTMLCanvasElement>(null)
  const area = useRef<HTMLDivElement>(null)
  const head = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  const shown: Project | null = hearPreview && preview ? preview : project
  const lengthBeats = useMemo(() => {
    if (!shown) return 0
    const bpb = (shown.time_signature[0] * 4) / shown.time_signature[1]
    const end = Math.max(1, ...shown.tracks.flatMap((t) => t.notes.map((n) => n.start + n.duration)))
    return Math.ceil(end / bpb) * bpb
  }, [shown])

  // 폭이 바뀌면 다시 그린다
  useEffect(() => {
    const el = area.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const el = canvas.current
    if (!el || !project || !shown || !width) return
    const tracks = shown.tracks
    const height = tracks.length * ROW
    const dpr = window.devicePixelRatio || 1
    el.width = width * dpr
    el.height = height * dpr
    el.style.width = `${width}px`
    el.style.height = `${height}px`
    const ctx = el.getContext('2d')!
    ctx.scale(dpr, dpr)
    const css = getComputedStyle(document.documentElement)
    const color = (v: string) => css.getPropertyValue(v).trim()
    const x = (beats: number) => (beats / lengthBeats) * width
    const bpb = (shown.time_signature[0] * 4) / shown.time_signature[1]
    const off = silenced(project, muted, solo)

    ctx.fillStyle = color('--surface-2')
    ctx.fillRect(0, 0, width, height)
    for (let b = bpb; b < lengthBeats; b += bpb) {
      ctx.fillStyle = (b / bpb) % 4 === 0 ? color('--grid-strong') : color('--grid')
      ctx.fillRect(Math.round(x(b)), 0, 1, height)
    }

    tracks.forEach((t, i) => {
      const top = i * ROW
      if (t.id === selectedTrackId) {
        ctx.fillStyle = color('--surface-3')
        ctx.fillRect(0, top, width, ROW)
      }
      // 미리보기로 바뀐 음은 라임, 나머지는 트랙 색
      const original = project.tracks.find((o) => o.id === t.id)
      const changed = new Set(original && shown !== project ? diffNotes(original.notes, t.notes).added : [])
      const pitches = t.notes.map((n) => n.pitch)
      const lo = Math.min(...pitches)
      const hi = Math.max(...pitches)
      ctx.globalAlpha = off[t.id] ? 0.25 : 0.9
      for (const n of t.notes) {
        const y = top + 2 + (hi === lo ? (ROW - 6) / 2 : ((hi - n.pitch) / (hi - lo)) * (ROW - 6))
        ctx.fillStyle = changed.has(n) ? color('--change') : trackColor(project, t.id)
        ctx.fillRect(x(n.start), y, Math.max(1.5, x(n.duration)), 2)
      }
      ctx.globalAlpha = 1
    })
  }, [project, shown, width, lengthBeats, selectedTrackId, muted, solo])

  // 재생선 (멈춰 있으면 시작 위치)
  useEffect(() => {
    const el = head.current
    if (!el || !lengthBeats || !width) return
    const place = (beats: number) => {
      el.style.transform = `translateX(${(Math.min(beats, lengthBeats) / lengthBeats) * width}px)`
    }
    if (!playing) {
      place(cursor)
      return
    }
    let raf = 0
    const frame = () => {
      place(positionBeats())
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => cancelAnimationFrame(raf)
  }, [playing, cursor, lengthBeats, width])

  if (!project || !shown) return null
  const bpb = (shown.time_signature[0] * 4) / shown.time_signature[1]
  const bars = Math.round(lengthBeats / bpb)

  return (
    <section className="overview" aria-label="전체 구성">
      <div className="overview-head">
        <h2>전체 구성</h2>
        <span className="hint">누르면 그 위치부터 재생해요 · {bars}마디</span>
      </div>
      <div className="overview-grid" style={{ gridTemplateColumns: `${LABEL}px minmax(0, 1fr)` }}>
        <div className="overview-labels">
          {shown.tracks.map((t) => (
            <button
              key={t.id}
              className={t.id === selectedTrackId ? 'on' : undefined}
              style={{ height: ROW }}
              onClick={() => selectTrack(t.id)}
              aria-label={`${t.name} 피아노롤 보기`}
            >
              <i style={{ background: trackColor(project, t.id) }} aria-hidden="true" />
              {t.name}
            </button>
          ))}
        </div>
        <div
          className="overview-area"
          ref={area}
          role="slider"
          tabIndex={0}
          aria-label="재생 위치"
          aria-valuemin={1}
          aria-valuemax={bars}
          aria-valuenow={Math.floor(cursor / bpb) + 1}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect()
            seek(Math.round(((e.clientX - r.left) / r.width) * lengthBeats * 4) / 4) // 16분음표 단위로
          }}
          onKeyDown={(e) => {
            // 키보드로도 마디 단위 이동
            if (e.key === 'ArrowRight') seek(Math.min(lengthBeats - bpb, (Math.floor(cursor / bpb) + 1) * bpb))
            if (e.key === 'ArrowLeft') seek(Math.max(0, (Math.ceil(cursor / bpb) - 1) * bpb))
            if (e.key === 'Home') seek(0)
          }}
        >
          <canvas ref={canvas} />
          <div className="overview-head-line" ref={head} />
        </div>
      </div>
    </section>
  )
}
