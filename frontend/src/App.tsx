import { useEffect } from 'react'
import { PianoRoll } from './components/PianoRoll'
import { TopBar } from './components/TopBar'
import { TrackList } from './components/TrackList'
import { usePlayer } from './store/player'
import { useProject } from './store/project'

export default function App() {
  const { project, error } = useProject()
  const notice = usePlayer((s) => s.notice)

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
    <div className="app">
      <TopBar />
      {error && <div className="banner error">{error}</div>}
      {notice && <div className="banner warn">{notice}</div>}
      {project?.warnings.map((w) => (
        <div key={w} className="banner warn">
          {w}
        </div>
      ))}
      <main>
        <TrackList />
        <PianoRoll />
        {/* 다음 단계: 채팅 패널 (POST /projects/{id}/chat) */}
      </main>
    </div>
  )
}
