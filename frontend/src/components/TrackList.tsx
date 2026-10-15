import { changedTrackIds } from '../diff'
import { silenced, usePlayer } from '../store/player'
import { useProject } from '../store/project'
import { instrumentLabel, trackColor } from '../theme'
import { Meter } from './Meter'

export function TrackList() {
  const { project, preview, hearPreview, selectedTrackId, selectTrack } = useProject()
  const { muted, solo, toggleMute, toggleSolo, playing } = usePlayer()
  if (!project) return null
  const changed = changedTrackIds(project, preview)
  const off = silenced(project, muted, solo)
  const heard = hearPreview && preview ? preview : project

  return (
    <nav className="tracks" aria-label="트랙">
      <div className="tracks-head">
        <h2>트랙 {project.tracks.length}</h2>
        <span className="hint">M 음소거 · S 솔로</span>
      </div>
      <ul>
        {project.tracks.map((t) => (
          <li key={t.id} className={[t.id === selectedTrackId ? 'selected' : '', off[t.id] ? 'silent' : ''].join(' ')}>
            <button className="track" onClick={() => selectTrack(t.id)} aria-pressed={t.id === selectedTrackId}>
              <span className="stripe" aria-hidden="true" style={{ background: trackColor(project, t.id) }} />
              <span className="body">
                <span className="name">
                  {t.name}
                  {changed.has(t.id) && <span className="badge">미리보기</span>}
                </span>
                <span className="info">
                  {instrumentLabel(t)} · 음 {t.notes.length}개
                </span>
                <Meter
                  notes={heard.tracks.find((h) => h.id === t.id)?.notes ?? t.notes}
                  color={trackColor(project, t.id)}
                  active={playing && !off[t.id]}
                />
              </span>
            </button>
            <button
              className={muted[t.id] ? 'ms mute on' : 'ms mute'}
              onClick={() => toggleMute(t.id)}
              aria-pressed={!!muted[t.id]}
              aria-label={`${t.name} ${muted[t.id] ? '음소거 해제' : '음소거'}`}
            >
              M
            </button>
            <button
              className={solo[t.id] ? 'ms solo on' : 'ms solo'}
              onClick={() => toggleSolo(t.id)}
              aria-pressed={!!solo[t.id]}
              aria-label={`${t.name} ${solo[t.id] ? '솔로 해제' : '솔로'}`}
            >
              S
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}
