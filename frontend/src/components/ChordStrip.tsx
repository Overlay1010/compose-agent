import { useEffect, useMemo, useRef } from 'react'
import type { ChordFunction, ChordSpan, Harmony } from '../api/types'
import { positionBeats } from '../audio/engine'
import { usePlayer } from '../store/player'

const FUNCTION_NAMES: Record<ChordFunction, string> = {
  T: '토닉 (안정)',
  S: '서브도미넌트 (나아감)',
  D: '도미넌트 (긴장 → 으뜸화음으로)',
  부속: '부속 딸림화음 (다음 코드로 끌어당김)',
  차용: '차용 화음 (다른 조에서 빌림)',
  '': '코드 없음',
}
const FN_CLASS: Record<ChordFunction, string> = { T: 't', S: 's', D: 'd', 부속: 'sec', 차용: 'bor', '': 'nc' }
const fnClass = (f: ChordFunction) => `fn-${FN_CLASS[f]}`

const same = (a: ChordSpan, b: ChordSpan) => a.start === b.start && a.end === b.end && a.name === b.name

/**
 * 피아노롤 위 코드 띠: 구간마다 코드 이름 · 로마숫자, 배경색 = 화성 기능.
 * 피아노롤과 같은 가로 배율로 그려서 같이 스크롤되고, 세로로 스크롤해도 위에 붙어 있다.
 * 누르면 그 코드 구간(모든 트랙)을 고르고 재생 위치를 옮긴다 → "여기 코드 바꿔줘"처럼 말할 수 있다.
 * base가 있으면(미리보기를 듣는 중) 원래와 달라진 코드를 라임 테두리로 표시한다.
 */
export function ChordStrip({
  harmony,
  base,
  keyPx,
  beatPx,
  lengthBeats,
  onPick,
}: {
  harmony: Harmony
  base: Harmony | null
  keyPx: number
  beatPx: number
  lengthBeats: number
  onPick: (chord: ChordSpan) => void
}) {
  const playing = usePlayer((s) => s.playing)
  const cursor = usePlayer((s) => s.cursor)
  const cells = useRef<(HTMLButtonElement | null)[]>([])
  const chords = useMemo(() => harmony.chords.filter((c) => c.start < lengthBeats), [harmony, lengthBeats])

  // 지금 울리는 코드를 밝게 (재생 중에는 매 프레임, 멈췄을 때는 재생 시작 위치 기준)
  useEffect(() => {
    const els = cells.current
    let raf = 0
    let lit = -1
    const mark = (beat: number) => {
      const i = chords.findIndex((c) => beat >= c.start && beat < c.end)
      if (i === lit) return
      els[lit]?.classList.remove('now')
      els[i]?.classList.add('now')
      lit = i
    }
    if (!playing) {
      if (cursor > 0) mark(cursor)
      return () => els[lit]?.classList.remove('now')
    }
    const frame = () => {
      mark(positionBeats())
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => {
      cancelAnimationFrame(raf)
      els[lit]?.classList.remove('now')
    }
  }, [playing, cursor, chords])

  return (
    <div className="chord-strip" style={{ width: keyPx + lengthBeats * beatPx }}>
      <span className="chord-label" style={{ width: keyPx }}>
        코드
      </span>
      {chords.map((c, i) => {
        const changed = !!base && !base.chords.some((b) => same(b, c))
        return (
          <button
            key={`${c.start}-${c.name}`}
            ref={(el) => {
              cells.current[i] = el
            }}
            className={`chord ${fnClass(c.function)}${changed ? ' changed' : ''}`}
            style={{ left: keyPx + c.start * beatPx, width: (Math.min(c.end, lengthBeats) - c.start) * beatPx }}
            title={`${c.name} · ${c.roman || '-'} · ${FUNCTION_NAMES[c.function]}${changed ? ' · 미리보기에서 바뀜' : ''}\n누르면 이 구간을 골라요`}
            onClick={() => onPick(c)}
          >
            <b>{c.name}</b>
            {c.roman && <span>{c.roman}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** 조성 표시: "C major", 미리보기에서 조가 바뀌면 "C major → D major" */
export function KeyBadge({ current, preview, hearPreview }: { current: Harmony | null; preview: Harmony | null; hearPreview: boolean }) {
  const now = current?.key
  const next = preview?.key
  if (!now && !next) return null
  const moved = !!next && !!now && next.name !== now.name
  const shown = hearPreview && next ? next : now!
  const used = new Set((hearPreview && preview ? preview : current)?.chords.map((c) => c.function))
  return (
    <span className="harmony-info">
      <span
        className={moved ? 'key-badge moved' : 'key-badge'}
        title={`분석한 조성${shown.alternatives.length ? ` · 다음 후보: ${shown.alternatives.join(', ')}` : ''}`}
      >
        {moved ? (
          <>
            {now!.name} <span aria-label="에서">→</span> {next!.name}
          </>
        ) : (
          shown.name
        )}
      </span>
      <span className="fn-legend" aria-label="화성 기능 색">
        {(['T', 'S', 'D', '부속', '차용'] as const)
          .filter((f) => f === 'T' || f === 'S' || f === 'D' || used.has(f))
          .map((f) => (
            <span key={f} title={FUNCTION_NAMES[f]}>
              <i className={fnClass(f)} aria-hidden="true" />
              {f}
            </span>
          ))}
      </span>
    </span>
  )
}
