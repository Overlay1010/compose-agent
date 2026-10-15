import { useEffect, useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { PianoRoll } from './components/PianoRoll'
import { TopBar } from './components/TopBar'
import { TrackList } from './components/TrackList'
import { VersionPanel } from './components/VersionPanel'
import { usePlayer } from './store/player'
import { useProject } from './store/project'

const isMidi = (f: File) => /\.midi?$/i.test(f.name)

export default function App() {
  const { project, error } = useProject()
  const notice = usePlayer((s) => s.notice)
  const [dragging, setDragging] = useState(false)

  // 스페이스바 = 재생·정지 (DAW와 같은 습관). 글자를 입력하는 칸에서는 무시한다.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat || !useProject.getState().project) return
      if ((e.target as HTMLElement).closest('input, textarea, [contenteditable]')) return
      e.preventDefault()
      usePlayer.getState().toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div
      className="app"
      // 창 어디에든 .mid를 끌어다 놓으면 연다
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes('Files')) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target || !e.relatedTarget) setDragging(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        const file = [...e.dataTransfer.files].find(isMidi)
        if (file) void useProject.getState().upload(file)
        else if (e.dataTransfer.files.length) useProject.setState({ error: '.mid 또는 .midi 파일만 열 수 있어요.' })
      }}
    >
      <TopBar />
      {error && <div className="banner error">{error}</div>}
      {notice && <div className="banner warn">{notice}</div>}
      {project?.warnings.map((w) => (
        <div key={w} className="banner warn">
          {w}
        </div>
      ))}
      <main className={project ? undefined : 'no-project'}>
        <TrackList />
        <PianoRoll />
        <ChatPanel />
      </main>
      <VersionPanel />
      {dragging && (
        <div className="drop-overlay" aria-hidden="true">
          <span>여기에 놓으면 열어요</span>
        </div>
      )}
    </div>
  )
}
