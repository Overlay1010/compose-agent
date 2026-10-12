import { usePlayer } from '../store/player'
import { useProject } from '../store/project'

export function TrackList() {
  const { project, selectedTrackId, selectTrack } = useProject()
  const { muted, toggleMute } = usePlayer()
  if (!project) return null

  return (
    <nav className="tracks">
      <h2>트랙</h2>
      <ul>
        {project.tracks.map((t) => (
          <li key={t.id} className={muted[t.id] ? 'muted' : undefined}>
            <button
              className={t.id === selectedTrackId ? 'track selected' : 'track'}
              onClick={() => selectTrack(t.id)}
            >
              <span className="name">{t.name}</span>
              <span className="info">
                {t.is_drum ? '드럼' : `악기 ${t.program}`} · 음 {t.notes.length}개
              </span>
            </button>
            <button
              className={muted[t.id] ? 'mute on' : 'mute'}
              onClick={() => toggleMute(t.id)}
              aria-pressed={!!muted[t.id]}
              title={muted[t.id] ? '음소거 해제' : '음소거'}
            >
              M
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
