import { changedTrackIds } from '../diff'
import { silenced, usePlayer } from '../store/player'
import { useProject } from '../store/project'
import { useChat } from '../store/chat'
import { GM_GROUPS, programName, trackColor } from '../theme'
import { gmProgramOf } from '../audio/instruments'
import { Meter } from './Meter'

export function TrackList() {
  const { project, preview, hearPreview, selectedTrackId, selectTrack, busy, setInstrument } = useProject()
  const { sending, note } = useChat()
  const { muted, solo, toggleMute, toggleSolo, playing } = usePlayer()
  if (!project) return null
  const changed = changedTrackIds(project, preview)
  const off = silenced(project, muted, solo)
  const heard = hearPreview && preview ? preview : project

  const changeInstrument = async (trackId: string, name: string, program: number) => {
    const next = await setInstrument(trackId, program)
    if (next) note(`${name} 악기를 ${programName(program)}(으)로 바꿨어요 (v${next.version}로 저장)`, true)
  }

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
                <span className="info">음 {t.notes.length}개</span>
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
            {t.is_drum ? (
              <span className="instrument drum">드럼 킷 (General MIDI)</span>
            ) : (
              <select
                className="instrument"
                value={gmProgramOf(t)}
                disabled={busy || sending}
                onChange={(e) => void changeInstrument(t.id, t.name, Number(e.target.value))}
                aria-label={`${t.name} 악기`}
                title="악기 바꾸기 (바로 새 버전으로 저장, 되돌리기 가능)"
              >
                {GM_GROUPS.map((g) => (
                  <optgroup key={g.family} label={g.family}>
                    {g.programs.map((p) => (
                      <option key={p} value={p}>
                        {programName(p)}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            )}
          </li>
        ))}
      </ul>
    </nav>
  )
}
