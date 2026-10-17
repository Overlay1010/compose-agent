import { useEffect, useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { PianoRoll } from './components/PianoRoll'
import { ShortcutHelp } from './components/ShortcutHelp'
import { TopBar } from './components/TopBar'
import { TrackList } from './components/TrackList'
import { VersionPanel } from './components/VersionPanel'
import { reopen } from './store/chat'
import { usePlayer } from './store/player'
import { useProject } from './store/project'
import { handleShortcut } from './shortcuts'

const isMidi = (f: File) => /\.midi?$/i.test(f.name)

export default function App() {
  const { project, error } = useProject()
  const notice = usePlayer((s) => s.notice)
  const [dragging, setDragging] = useState(false)

  // 주소에 프로젝트 id가 있으면(새로고침) 저장된 프로젝트를 다시 연다
  // 주소창에서 #id만 바꿔도(페이지는 다시 안 불러옴) 그 프로젝트로 옮긴다
  useEffect(() => {
    const openFromHash = () => {
      const id = decodeURIComponent(location.hash.slice(1))
      if (id && id !== useProject.getState().project?.id) void reopen(id)
    }
    openFromHash()
    window.addEventListener('hashchange', openFromHash)
    return () => window.removeEventListener('hashchange', openFromHash)
  }, [])

  // 단축키 (shortcuts.ts). 글자를 입력하는 칸에서는 무시한다.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (handleShortcut(e)) e.preventDefault()
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
      <ShortcutHelp />
      {dragging && (
        <div className="drop-overlay" aria-hidden="true">
          <span>여기에 놓으면 열어요</span>
        </div>
      )}
    </div>
  )
}
