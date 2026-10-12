import { useRef } from 'react'
import { exportUrl } from '../api/client'
import { usePlayer } from '../store/player'
import { useProject } from '../store/project'

export function TopBar() {
  const { project, loading, upload } = useProject()
  const { playing, toggle } = usePlayer()
  const input = useRef<HTMLInputElement>(null)

  return (
    <header className="topbar">
      <div className="brand">
        Compose Agent <span className="ver">v0.1</span>
      </div>

      {project && (
        <div className="meta">
          <strong>{project.name}</strong>
          <span>{project.tempo.toFixed(0)} BPM</span>
          <span>
            {project.time_signature[0]}/{project.time_signature[1]}
          </span>
          <span>버전 {project.version}</span>
        </div>
      )}

      <div className="actions">
        {project && (
          <button className="play" onClick={toggle} title="스페이스바로도 재생·정지할 수 있어요">
            {playing ? '■ 정지' : '▶ 재생'}
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
          <a className="button primary" href={exportUrl(project.id)} download>
            .mid 내보내기
          </a>
        )}
      </div>
    </header>
  )
}
