import { useEffect, useRef, useState } from 'react'
import { downloadMidi } from '../api/client'
import { positionBeats } from '../audio/player'
import { useShortcutHelp } from '../shortcuts'
import { usePlayer } from '../store/player'
import { useProject } from '../store/project'

function PlayIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
    </svg>
  )
}

/** 반복 구간을 마디로: "3~4마디" */
function loopText(loop: { start: number; end: number }, p: { time_signature: [number, number] }) {
  const bpb = (p.time_signature[0] * 4) / p.time_signature[1]
  const first = Math.round(loop.start / bpb) + 1
  const last = Math.round(loop.end / bpb)
  return first === last ? `${first}마디` : `${first}~${last}마디`
}

/** 마디 · 박 · 16분 위치와 시간. 재생 중에는 매 프레임 갱신한다. */
function TransportDisplay({ bpm, beatsPerBar }: { bpm: number; beatsPerBar: number }) {
  const playing = usePlayer((s) => s.playing)
  const cursor = usePlayer((s) => s.cursor)
  const [beats, setBeats] = useState(0)

  useEffect(() => {
    if (!playing) {
      setBeats(cursor) // 멈춰 있으면 시작 위치
      return
    }
    let raf = 0
    const frame = () => {
      setBeats(positionBeats())
      raf = requestAnimationFrame(frame)
    }
    frame()
    return () => cancelAnimationFrame(raf)
  }, [playing, cursor])

  const bar = Math.floor(beats / beatsPerBar) + 1
  const beat = Math.floor(beats % beatsPerBar) + 1
  const sixteenth = Math.floor((beats % 1) * 4) + 1
  const secs = (beats * 60) / bpm
  const time = `${Math.floor(secs / 60)}:${(secs % 60).toFixed(1).padStart(4, '0')}`

  return (
    <div className="lcd" aria-label="재생 위치">
      <span className="cell">
        <span className="cap">마디 · 박 · 16분</span>
        <span className="pos">
          {bar} . {beat} . {sixteenth}
        </span>
      </span>
      <span className="cell">
        <span className="cap">시간</span>
        <span className="val">{time}</span>
      </span>
    </div>
  )
}

export function TopBar() {
  const { project, preview, hearPreview, loading, upload, setHistoryOpen } = useProject()
  const { playing, loadingSounds, toggle, restart, loop, looping, toggleLoop } = usePlayer()
  const input = useRef<HTMLInputElement>(null)
  const heard = preview && hearPreview ? preview : project
  const tempoText =
    project && preview && hearPreview && preview.tempo !== project.tempo
      ? `${project.tempo.toFixed(0)} → ${preview.tempo.toFixed(0)}`
      : project?.tempo.toFixed(0)

  return (
    <header className="topbar">
      <button
        className="brand"
        onClick={() => useProject.getState().close()}
        disabled={!project}
        title="처음 화면으로 (작업은 저장돼 있어요)"
      >
        <span className="logo" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 18V5l11-2v13" />
            <circle cx="6" cy="18" r="3" />
            <circle cx="17" cy="16" r="3" />
          </svg>
        </span>
        <span>Compose Agent</span>
      </button>

      {project && heard && (
        <>
          <div className="project">
            <strong>{project.name}</strong>
            <span className="sub">{preview ? `적용 전 미리보기 있음 · v${project.version}` : `저장됨 · v${project.version}`}</span>
          </div>

          <div className="transport">
            <div className="buttons">
              <button className="icon" onClick={restart} aria-label="처음으로" title="처음으로">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M19 20 9 12l10-8v16Z" />
                  <path d="M5 19V5" />
                </svg>
              </button>
              <button
                className="play"
                onClick={toggle}
                aria-label={playing ? '정지' : '재생'}
                title={loadingSounds ? '악기 불러오는 중…' : '스페이스바로도 재생 · 정지할 수 있어요'}
              >
                {loadingSounds ? <span className="spinner" aria-hidden="true" /> : playing ? <StopIcon /> : <PlayIcon />}
              </button>
              <button
                className={looping ? 'icon loop on' : 'icon loop'}
                onClick={toggleLoop}
                aria-pressed={looping}
                aria-label="구간 반복"
                title={loop ? `구간 반복 · ${loopText(loop, heard)}` : '구간 반복 (전체 구성에서 끌어서 구간을 고를 수 있어요)'}
              >
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="m17 2 4 4-4 4" />
                  <path d="M3 11v-1a4 4 0 0 1 4-4h14" />
                  <path d="m7 22-4-4 4-4" />
                  <path d="M21 13v1a4 4 0 0 1-4 4H3" />
                </svg>
              </button>
              {looping && loop && <span className="loop-range">{loopText(loop, heard)}</span>}
            </div>
            <TransportDisplay bpm={heard.tempo} beatsPerBar={(heard.time_signature[0] * 4) / heard.time_signature[1]} />
            <div className="lcd">
              <span className="cell">
                <span className="cap">템포 · 박자</span>
                <span className="val">
                  {tempoText} BPM · {project.time_signature[0]}/{project.time_signature[1]}
                </span>
              </span>
            </div>
          </div>
        </>
      )}

      <div className="actions">
        <button className="keys" onClick={() => useShortcutHelp.getState().setOpen(true)} title="단축키 목록 (?)" aria-label="단축키 목록">
          ?
        </button>
        {project && (
          <button className="version" onClick={() => setHistoryOpen(true)} title="버전 기록 보기">
            버전 기록 <span className="pill">v{project.version}</span>
          </button>
        )}
        <input
          ref={input}
          type="file"
          accept=".mid,.midi"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) upload(file)
            e.target.value = ''
          }}
        />
        <button onClick={() => input.current?.click()} disabled={loading}>
          {loading ? '읽는 중…' : 'MIDI 열기'}
        </button>
        {project && (
          <button
            className="primary"
            onClick={() =>
              downloadMidi(project.id).catch((e) =>
                useProject.setState({ error: `.mid로 내보내지 못했어요: ${e instanceof Error ? e.message : String(e)}` }),
              )
            }
          >
            .mid 내보내기
          </button>
        )}
      </div>
    </header>
  )
}
