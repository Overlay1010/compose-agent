import { useEffect, useState } from 'react'
import type { Track } from '../api/types'
import * as player from '../audio/engine'
import { changedTrackIds, panLabel } from '../diff'
import { silenced, usePlayer } from '../store/player'
import { useProject } from '../store/project'
import { useChat } from '../store/chat'
import { GM_GROUPS, soundName, programName, trackColor } from '../theme'
import { DRUM_KITS, DRUM_NAMES, gmProgramOf } from '../audio/catalog'
import { Meter } from './Meter'
import { recommendSamples, type SamplePick } from '../api/client'
import { sampleInfos, sampleMeta, useSamples } from '../samples/library'
import { useSamplePack } from '../store/samplePack'

export function TrackList() {
  const { project, preview, hearPreview, selectedTrackId, selectTrack, busy, setInstrument, setSample, setDrumSample, deleteTrack } = useProject()
  const { sending, note } = useChat()
  const { muted, solo, toggleMute, toggleSolo, playing } = usePlayer()
  const picks = useSamplePicks()
  if (!project) return null
  const changed = changedTrackIds(project, preview)
  const off = silenced(project, muted, solo)
  const heard = hearPreview && preview ? preview : project
  // 미리보기에서 새로 생기는 트랙 (트랙 복제 등). 적용하기 전에는 목록 끝에 따로 보인다
  const added = preview ? preview.tracks.filter((t) => !project.tracks.some((o) => o.id === t.id)) : []
  const isNew = (id: string) => added.some((t) => t.id === id)
  // 미리보기에서 지워지는 트랙 (delete_track). 적용하기 전에는 흐리게 남겨 둔다
  const isGone = (id: string) => !!preview && !preview.tracks.some((t) => t.id === id)

  const remove = async (trackId: string) => {
    const changed = await deleteTrack(trackId)
    if (changed?.note) note(changed.note, true)
  }
  const changeInstrument = async (trackId: string, program: number) => {
    const changed = await setInstrument(trackId, program)
    if (changed?.note) note(changed.note, true)
  }
  // 악기 메뉴 값: GM 번호 또는 "sample:<id>" (내 샘플)
  const changeSound = async (trackId: string, value: string) => {
    if (value === 'pack') return useSamplePack.getState().setOpen(true)
    if (!value.startsWith('sample:')) return changeInstrument(trackId, Number(value))
    const info = sampleInfos().find((s) => s.id === value.slice(7))
    if (!info) return
    const changed = await setSample(trackId, info)
    if (changed?.note) note(changed.note, true)
  }
  // 드럼 킷 메뉴 값: 킷 번호 또는 "sample:<레인>:<id>" (그 레인에 넣을 내 샘플)
  const changeDrumSound = async (trackId: string, value: string) => {
    if (value === 'pack') return useSamplePack.getState().setOpen(true)
    const sample = /^sample:(\d+):(.+)$/.exec(value)
    if (!sample) return changeInstrument(trackId, Number(value))
    const info = sampleInfos().find((s) => s.id === sample[2])
    if (!info) return
    const changed = await setDrumSample(trackId, Number(sample[1]), info)
    if (changed?.note) note(changed.note, true)
  }

  return (
    <nav className="tracks" aria-label="트랙">
      <div className="tracks-head">
        <h2>
          트랙 {project.tracks.length}
          {added.length > 0 && <span className="new-count"> + 새 {added.length}</span>}
        </h2>
        <span className="hint">M 음소거 · S 솔로 · × 지우기</span>
      </div>
      <ul>
        {[...project.tracks, ...added].map((t) => (
          <li
            key={t.id}
            className={[
              t.id === selectedTrackId ? 'selected' : '',
              off[t.id] || (isNew(t.id) && !hearPreview) || (isGone(t.id) && hearPreview) ? 'silent' : '',
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
                  ) : isGone(t.id) ? (
                    <span className="badge">지워짐</span>
                  ) : (
                    changed.has(t.id) && <span className="badge">미리보기</span>
                  )}
                </span>
                <span className="info">
                  {t.audio ? `오디오 루프 · ${t.audio.bpm} BPM` : `음 ${t.notes.length}개`}
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
            {!isNew(t.id) && project.tracks.length > 1 && (
              <button
                className="ms del"
                onClick={() => void remove(t.id)}
                disabled={busy || sending}
                aria-label={`${t.name} 트랙 지우기`}
                title="트랙 지우기 (바로 저장돼요 · 히스토리에서 되돌리기 가능)"
              >
                ×
              </button>
            )}
            {isNew(t.id) || t.audio ? (
              // 아직 없는 트랙이라 악기 · 볼륨은 적용한 뒤에 바꿀 수 있다. 오디오 루프는 고를 악기가 없다
              <span
                className={t.audio && !sampleMeta(t.audio.sample.id) ? 'instrument drum missing' : 'instrument drum'}
                title={t.audio ? (sampleMeta(t.audio.sample.id) ? `${t.audio.bpm} BPM 루프 · 곡 템포에 맞춰 재생` : '이 루프가 이 브라우저에 없어서 소리가 안 나요') : undefined}
              >
                {soundName(t)}
                {t.audio && !sampleMeta(t.audio.sample.id) ? ' (이 브라우저에 없음)' : ''}
              </span>
            ) : t.is_drum ? (
              <select
                className="instrument"
                value={usedDrumSamples(t).length ? 'mine' : DRUM_KITS.some((k) => k.program === t.program) ? t.program : 0}
                disabled={busy || sending}
                onChange={(e) => void changeDrumSound(t.id, e.target.value)}
                aria-label={`${t.name} 드럼 킷`}
                title="드럼 킷 · 내 샘플 바꾸기 (바로 저장돼요 · 히스토리에서 되돌리기 가능). 지금 킷을 다시 고르면 내 샘플을 빼요"
              >
                <DrumSampleOptions track={t} picks={picks[t.id] ?? []} />
                <optgroup label="드럼 킷">
                  {DRUM_KITS.map((k) => (
                    <option key={k.program} value={k.program}>
                      드럼 킷 · {k.name}
                    </option>
                  ))}
                </optgroup>
              </select>
            ) : (
              <select
                className={t.sample && !sampleMeta(t.sample.id) ? 'instrument missing' : 'instrument'}
                value={t.sample ? `sample:${t.sample.id}` : gmProgramOf(t)}
                disabled={busy || sending}
                onChange={(e) => void changeSound(t.id, e.target.value)}
                aria-label={`${t.name} 악기`}
                title={
                  t.sample && !sampleMeta(t.sample.id)
                    ? `내 샘플 '${t.sample.name}'이 이 브라우저에 없어서 ${programName(gmProgramOf(t))} 소리로 들려요`
                    : '악기 바꾸기 (바로 저장돼요 · 히스토리에서 되돌리기 가능)'
                }
              >
                <SampleOptions track={t} picks={picks[t.id] ?? []} />
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

/** 트랙마다 어울리는 내 샘플 (서버가 점수로 고른 순서). 샘플팩이나 곡이 바뀌면 다시 묻는다 */
function useSamplePicks(): Record<string, SamplePick[]> {
  const samples = useSamples((s) => s.samples)
  const project = useProject((s) => s.project)
  const [picks, setPicks] = useState<Record<string, SamplePick[]>>({})
  const key = project ? `${project.id}:${project.version}` : ''
  useEffect(() => {
    if (!project || !samples.length) {
      setPicks({})
      return
    }
    let live = true
    recommendSamples(project.id, sampleInfos())
      .then((r) => live && setPicks(r))
      .catch(() => live && setPicks({}))
    return () => {
      live = false
    }
    // 곡 내용이 같으면(버전이 같으면) 다시 묻지 않는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, samples])
  return picks
}

/** 악기 메뉴 맨 위: 지금 쓰는 내 샘플 · 어울리는 내 샘플 · 샘플팩 열기 */
function SampleOptions({ track, picks }: { track: Track; picks: SamplePick[] }) {
  const count = useSamples((s) => s.samples.length)
  const current = track.sample
  const listed = picks.filter((p) => p.id !== current?.id)
  return (
    <>
      {current && (
        <option value={`sample:${current.id}`}>
          내 샘플 · {current.name}
          {sampleMeta(current.id) ? '' : ' (이 브라우저에 없음)'}
        </option>
      )}
      {listed.length > 0 && (
        <optgroup label="내 샘플 (어울리는 순)">
          {listed.map((p) => (
            <option key={p.id} value={`sample:${p.id}`} title={p.reason}>
              {p.name}
            </option>
          ))}
        </optgroup>
      )}
      {!count && <option value="pack">내 샘플 넣기…</option>}
    </>
  )
}

/** 이 드럼 트랙에서 실제로 치는 레인에 넣은 내 샘플 */
function usedDrumSamples(track: Track) {
  const lanes = new Set(track.notes.map((n) => String(n.pitch)))
  return Object.entries(track.drum_samples ?? {}).filter(([pitch]) => lanes.has(pitch))
}

/** 드럼 킷 메뉴 맨 위: 지금 쓰는 내 샘플 · 레인마다 어울리는 내 샘플 · 샘플팩 열기 */
function DrumSampleOptions({ track, picks }: { track: Track; picks: SamplePick[] }) {
  const count = useSamples((s) => s.samples.length)
  const mine = usedDrumSamples(track).map(([, ref]) => ref)
  const lanes = [...new Set(picks.map((p) => p.pitch!))]
  const kit = DRUM_KITS.find((k) => k.program === track.program)?.name ?? DRUM_KITS[0].name
  return (
    <>
      {mine.length > 0 && (
        <option value="mine">
          {mine.length === 1 ? `내 샘플 · ${mine[0].name}` : `내 샘플 ${mine.length}개 · ${kit}`}
          {mine.some((s) => !sampleMeta(s.id)) ? ' (이 브라우저에 없음)' : ''}
        </option>
      )}
      {lanes.map((pitch) => {
        const listed = picks.filter((p) => p.pitch === pitch && p.id !== track.drum_samples?.[pitch]?.id)
        return (
          listed.length > 0 && (
            <optgroup key={pitch} label={`내 샘플 · ${DRUM_NAMES[pitch] ?? pitch}`}>
              {listed.map((p) => (
                <option key={p.id} value={`sample:${pitch}:${p.id}`} title={p.reason}>
                  {p.name}
                </option>
              ))}
            </optgroup>
          )
        )
      })}
      {!count && <option value="pack">내 샘플 넣기…</option>}
    </>
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
      <label title="트랙 볼륨 (0~127, 기본 100). 손을 떼면 저장돼요">
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
