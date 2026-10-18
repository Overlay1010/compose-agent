import { useEffect, useRef, useState } from 'react'
import { audioFormats, convertAudio, downloadMidi, downloadTracksZip, saveBlob } from '../api/client'
import { peakOf, renderMix, toWav } from '../audio/render'
import { positionBeats } from '../audio/player'
import { useShortcutHelp } from '../shortcuts'
import { silenced, usePlayer } from '../store/player'
import { timeAgo } from '../time'
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

/** 내보내기 메뉴: 전체 곡 하나 · 트랙별 .zip · 트랙 하나만. 현재 버전 기준 (적용 전 미리보기는 빠짐) */
const AUDIO_LABELS: Record<string, string> = { wav: 'WAV · 무손실', mp3: 'MP3', flac: 'FLAC · 무손실', ogg: 'OGG', m4a: 'M4A · AAC', mp4: 'MP4 · 소리만' }

function ExportMenu() {
  const { project, preview } = useProject()
  const [open, setOpen] = useState(false)
  const [formats, setFormats] = useState<string[]>(['wav'])
  const [working, setWorking] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  // 서버에 ffmpeg가 있으면 MP3 등도 보여 준다
  useEffect(() => {
    audioFormats()
      .then((f) => setFormats(['wav', ...f]))
      .catch(() => setFormats(['wav']))
  }, [])

  /** 들리는 그대로(음소거 · 솔로 반영) 녹음 → 형식 변환 → 저장 */
  const exportAudio = async (format: string) => {
    if (!project) return
    setWorking(`${format.toUpperCase()} 만드는 중… (악기를 불러와 녹음해요)`)
    usePlayer.getState().stop() // 녹음하는 동안은 Tone.js 전역 오디오가 녹음용으로 바뀌어서 재생을 멈춘다
    try {
      const { muted, solo } = usePlayer.getState()
      const buffer = await renderMix(project, silenced(project, muted, solo))
      const wav = toWav(buffer)
      const name = `${project.name}_v${project.version}`
      if (format === 'wav') saveBlob(wav, `${name}.wav`)
      else {
        setWorking(`${format.toUpperCase()}로 바꾸는 중…`)
        saveBlob(await convertAudio(wav, format, name), `${name}.${format}`)
      }
      setOpen(false)
      if (peakOf(buffer) >= 0.999) {
        useProject.setState({ error: '음원은 만들었지만 소리가 너무 커서 일부가 깨졌을 수 있어요. 트랙 볼륨을 조금 줄여 보세요.' })
      }
    } catch (e) {
      useProject.setState({ error: `음원으로 내보내지 못했어요: ${e instanceof Error ? e.message : String(e)}` })
    } finally {
      setWorking(null)
    }
  }

  // 메뉴 밖을 누르거나 Esc면 닫는다
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [open])

  if (!project) return null
  const run = (job: Promise<void>) => {
    setOpen(false)
    job.catch((e) => useProject.setState({ error: `내보내지 못했어요: ${e instanceof Error ? e.message : String(e)}` }))
  }

  return (
    <div className="export" ref={box}>
      <button className="primary" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu">
        내보내기 ▾
      </button>
      {open && (
        <div className="export-menu" role="menu">
          <p className="export-sep">MIDI</p>
          <button role="menuitem" onClick={() => run(downloadMidi(project.id))}>
            <strong>전체 곡 · 파일 하나</strong>
            <span>모든 트랙이 든 .mid</span>
          </button>
          <button role="menuitem" onClick={() => run(downloadTracksZip(project.id))}>
            <strong>트랙별로 한 번에</strong>
            <span>트랙마다 .mid + 전체 곡 .mid를 .zip으로</span>
          </button>
          <p className="export-sep">음원 (들리는 그대로 · 음소거 · 솔로 반영)</p>
          <div className="export-formats">
            {formats.map((f) => (
              <button key={f} role="menuitem" className="fmt" disabled={!!working} onClick={() => void exportAudio(f)}>
                {AUDIO_LABELS[f] ?? f.toUpperCase()}
              </button>
            ))}
          </div>
          {working && (
            <p className="export-working" aria-live="polite">
              <span className="spinner small" aria-hidden="true" /> {working}
            </p>
          )}
          <p className="export-sep">트랙 하나만 (MIDI)</p>
          {project.tracks.map((t) => (
            <button key={t.id} role="menuitem" className="one" onClick={() => run(downloadMidi(project.id, t.id))}>
              {t.name}
              <span>.mid</span>
            </button>
          ))}
          <p className="export-note">
            지금 저장된 상태 기준{preview ? ' · 적용 전 미리보기는 들어가지 않아요' : ''} · 드럼 소리 선택은 MIDI에는 안 담기고 음원에는 담겨요
          </p>
        </div>
      )}
    </div>
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
  // 지금 상태가 저장된 시각 ("저장됨 · 3분 전"). 시간이 흐르게 30초마다 다시 그린다
  const savedAt = useProject((s) => s.versions.find((v) => v.current)?.created_at ?? '')
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 30000)
    return () => clearInterval(id)
  }, [])
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
            <span className="sub">{preview ? '적용 전 미리보기 있음' : `저장됨${savedAt ? ` · ${timeAgo(savedAt)}` : ''}`}</span>
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
          <button className="version" onClick={() => setHistoryOpen(true)} title="지금까지 저장된 상태 · 예전으로 되돌리기">
            히스토리
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
          <ExportMenu />
        )}
      </div>
    </header>
  )
}
