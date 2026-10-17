import { useState } from 'react'
import type { Track } from '../api/types'
import * as player from '../audio/player'
import { changedTrackIds, panLabel } from '../diff'
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
  // 미리보기에서 새로 생기는 트랙 (트랙 복제 등). 적용하기 전에는 목록 끝에 따로 보인다
  const added = preview ? preview.tracks.filter((t) => !project.tracks.some((o) => o.id === t.id)) : []
  const isNew = (id: string) => added.some((t) => t.id === id)

  const changeInstrument = async (trackId: string, name: string, program: number) => {
    const changed = await setInstrument(trackId, program)
    if (changed?.note) note(changed.note, true)
  }

  return (
    <nav className="tracks" aria-label="트랙">
      <div className="tracks-head">
        <h2>
          트랙 {project.tracks.length}
          {added.length > 0 && <span className="new-count"> + 새 {added.length}</span>}
        </h2>
        <span className="hint">M 음소거 · S 솔로</span>
      </div>
      <ul>
        {[...project.tracks, ...added].map((t) => (
          <li
            key={t.id}
            className={[
              t.id === selectedTrackId ? 'selected' : '',
              off[t.id] || (isNew(t.id) && !hearPreview) ? 'silent' : '',
              isNew(t.id) ? 'new' : '',
            ].join(' ')}
          >
            <button className="track" onClick={() => selectTrack(t.id)} aria-pressed={t.id === selectedTrackId}>
              <span className="stripe" aria-hidden="true" style={{ background: trackColor(project, t.id) }} />
              <span className="body">
                <span className="name">
                  <span className="label">{t.name}</span>
                  {isNew(t.id) ? (
                    <span className="badge">새 트랙</span>
                  ) : (
                    changed.has(t.id) && <span className="badge">미리보기</span>
                  )}
                </span>
                <span className="info">
                  음 {t.notes.length}개
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
            {isNew(t.id) ? (
              // 아직 없는 트랙이라 악기 · 볼륨은 적용한 뒤에 바꿀 수 있다
              <span className="instrument drum">{t.is_drum ? '드럼 킷 (General MIDI)' : programName(gmProgramOf(t))}</span>
            ) : t.is_drum ? (
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
            {!isNew(t.id) && <MixControls key={`${t.id}:${t.volume}:${t.pan}`} track={t} />}
          </li>
        ))}
      </ul>
    </nav>
  )
}

/**
 * 볼륨 · 팬 슬라이더. 끄는 동안은 소리만 바로 바꾸고(새 버전 X), 손을 떼면 한 번만 새 버전으로 저장한다.
 * key에 볼륨 · 팬을 넣어 두어, 되돌리기 등으로 값이 바뀌면 끄던 값이 초기화된다.
 */
function MixControls({ track }: { track: Track }) {
  const { busy, setMix } = useProject()
  const { sending, note } = useChat()
  const [volume, setVolume] = useState(track.volume)
  const [pan, setPan] = useState(track.pan)

  const commit = async (v = volume, p = pan) => {
    if (v === track.volume && p === track.pan) return
    const changed = await setMix(track.id, { volume: v, pan: p })
    if (changed?.note) {
      note(changed.note, true)
    } else {
      // 저장이 안 됐으면 소리와 슬라이더를 원래대로
      player.setMix(track.id, track.volume, track.pan)
      setVolume(track.volume)
      setPan(track.pan)
    }
  }
  const disabled = busy || sending
  const live = { onPointerUp: () => void commit(), onKeyUp: () => void commit() }

  return (
    <div className="mix">
      <label title="트랙 볼륨 (0~127, 기본 100). 손을 떼면 새 버전으로 저장">
        <span>볼륨</span>
        <input
          type="range"
          min={0}
          max={127}
          value={volume}
          disabled={disabled}
          aria-label={`${track.name} 볼륨`}
          onChange={(e) => {
            setVolume(Number(e.target.value))
            player.setMix(track.id, Number(e.target.value), pan)
          }}
          {...live}
        />
        <output>{volume}</output>
      </label>
      <label title="좌우 위치. 두 번 누르면 가운데로">
        <span>팬</span>
        <input
          type="range"
          min={-64}
          max={63}
          value={pan}
          disabled={disabled}
          aria-label={`${track.name} 팬`}
          aria-valuetext={panLabel(pan)}
          onChange={(e) => {
            setPan(Number(e.target.value))
            player.setMix(track.id, volume, Number(e.target.value))
          }}
          onDoubleClick={() => {
            setPan(0)
            player.setMix(track.id, volume, 0)
            void commit(volume, 0)
          }}
          {...live}
        />
        <output>{pan === 0 ? 'C' : `${pan < 0 ? 'L' : 'R'}${Math.abs(pan)}`}</output>
      </label>
    </div>
  )
}
