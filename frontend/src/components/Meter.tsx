import { useEffect, useRef } from 'react'
import type { Note } from '../api/types'
import { positionBeats } from '../audio/player'

/**
 * 트랙 레벨 미터. 실제 오디오를 분석하지 않고, 지금 위치에서 울리고 있는 음의 세기를 더해 근사한다.
 * 매 프레임 React 렌더 없이 막대 폭만 바꾼다.
 */
export function Meter({ notes, color, active }: { notes: Note[]; color: string; active: boolean }) {
  const bar = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = bar.current
    if (!el) return
    if (!active) {
      el.style.width = '0%'
      return
    }
    let raf = 0
    let level = 0
    const frame = () => {
      const at = positionBeats()
      let sum = 0
      for (const n of notes) {
        // 드럼처럼 아주 짧은 음도 보이게 최소 0.2박은 울린다고 본다
        if (at >= n.start && at < n.start + Math.max(n.duration, 0.2)) sum += n.velocity / 127
      }
      // 올라갈 땐 바로, 내려갈 땐 천천히 (미터처럼)
      level = Math.max(Math.min(1, sum * 0.45), level * 0.88)
      el.style.width = `${Math.round(level * 100)}%`
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => cancelAnimationFrame(raf)
  }, [notes, active])

  return (
    <span className="meter" aria-hidden="true">
      <span ref={bar} style={{ background: color }} />
    </span>
  )
}
