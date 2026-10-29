import { useEffect, useRef, useState } from 'react'
import { applyWithNote, cancelWithNote, undoWithNote } from '../actions'
import { toolLabel, useChat } from '../store/chat'
import { DRUM_NAMES, DRUM_SOUNDS, drumSoundOf, gmProgramOf } from '../audio/catalog'
import { useProject } from '../store/project'
import { useReharm } from '../store/reharm'
import type { ReharmView } from '../api/types'
import { panLabel, sameDrumSounds, sameMix } from '../diff'
import { selectionLabel } from '../selection'
import { soundName } from '../theme'

const SUGGESTIONS = [
  '지금 무슨 트랙 있어?',
  '베이스를 신스 베이스로 바꿔줘',
  '하이햇 좀 약하게 하고 살짝 스윙 넣어줘',
  '박자 맞춰줘, 너무 딱딱하진 않게',
  '멜로디 한 옥타브 내려줘',
]

export function ChatPanel() {
  const { project, preview, hearPreview, setHearPreview, busy, selection, setSelection } = useProject()
  const { messages, sending, send } = useChat()
  const [input, setInput] = useState('')
  const list = useRef<HTMLDivElement>(null)

  // 새 메시지가 오면 맨 아래로
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [messages, sending])

  if (!project) return null

  const apply = applyWithNote
  const cancel = cancelWithNote
  const revert = undoWithNote

  const submit = (text: string) => {
    if (!text.trim() || sending) return
    setInput('')
    void send(text)
  }

  return (
    <aside className="chat" aria-label="에이전트">
      <h2>에이전트</h2>

      <div className="chat-list" ref={list}>
        <p className="msg agent">
          {project.name}을(를) 열었어요. 트랙 {project.tracks.length}개 · {project.tempo.toFixed(0)} BPM이에요. 무엇을
          바꿔 볼까요?
        </p>

        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="msg-user">
              {m.selection && <span className="sel-chip small">고른 부분 · {m.selection}</span>}
              <p className="msg user">{m.text}</p>
            </div>
          ) : m.role === 'note' ? (
            <p key={m.id} className="msg note">
              <span aria-hidden="true">✓ </span>
              {m.text}
              {m.canUndo && (
                <button className="link" onClick={revert} disabled={busy}>
                  되돌리기
                </button>
              )}
            </p>
          ) : m.role === 'error' ? (
            <p key={m.id} className="msg error" role="alert">
              {m.text}
            </p>
          ) : (
            <div key={m.id} className="msg-group">
              {m.steps && m.steps.length > 0 && (
                <ol className="steps" aria-label="실행한 도구">
                  {m.steps.map((s, i) => (
                    <li key={i} className={s.running ? 'step running' : s.ok ? 'step' : 'step failed'} title={`${s.name} ${JSON.stringify(s.args)}`}>
                      <span className="mark" aria-hidden="true">
                        {s.running ? <span className="spinner small" /> : s.ok ? '✓' : '!'}
                      </span>
                      <span className="tool">{toolLabel(s.name)}</span>
                      <span className="summary">{s.summary}</span>
                    </li>
                  ))}
                </ol>
              )}
              {m.live ? (
                <p className="msg agent thinking" aria-live="polite">
                  <span className="spinner small" aria-hidden="true" />
                  {m.status}
                </p>
              ) : (
                <>
                  <p className="msg agent">{m.text}</p>
                  {m.steps?.map(
                    (s, i) => s.ok && s.view?.reharm && <ReharmCards key={i} id={`${m.id}-${i}`} view={s.view.reharm} />,
                  )}
                  <span className="meta">
                    {m.madePreview && <strong>미리보기 만들어짐 · </strong>}
                    {m.meta}
                  </span>
                </>
              )}
            </div>
          ),
        )}

      </div>

      {preview && (
        <div className="preview-card">
          <p>
            <strong>미리보기</strong> · 다음 명령도 이 위에 이어서 쌓여요
          </p>
          {preview.tracks
            .filter((t) => {
              const before = project.tracks.find((o) => o.id === t.id)
              return before && gmProgramOf(before) !== gmProgramOf(t)
            })
            .map((t) => (
              <p className="tempo-change" key={t.id}>
                {t.name} {soundName(project.tracks.find((o) => o.id === t.id)!)} →{' '}
                <strong>{soundName(t)}</strong>
              </p>
            ))}
          {preview.tracks.map((t) => {
            const before = project.tracks.find((o) => o.id === t.id)
            if (!before || sameDrumSounds(before, t) || before.program !== t.program) return null
            const changed = [...new Set([...Object.keys(before.drum_sounds ?? {}), ...Object.keys(t.drum_sounds ?? {})])]
              .filter((p) => before.drum_sounds?.[p] !== t.drum_sounds?.[p])
              .map(Number)
            return (
              <p className="tempo-change" key={`drum-${t.id}`}>
                {t.name}{' '}
                <strong>
                  {changed
                    .map((p) => `${DRUM_NAMES[p] ?? p} → ${DRUM_SOUNDS[drumSoundOf(t.program, p, t.drum_sounds)!]?.name ?? p}`)
                    .join(' · ')}
                </strong>
              </p>
            )
          })}
          {preview.tracks.map((t) => {
            const before = project.tracks.find((o) => o.id === t.id)
            if (!before || sameMix(before, t)) return null
            const parts = [
              before.volume !== t.volume && `볼륨 ${before.volume} → ${t.volume}`,
              before.pan !== t.pan && `팬 ${panLabel(before.pan)} → ${panLabel(t.pan)}`,
            ].filter(Boolean)
            return (
              <p className="tempo-change" key={`mix-${t.id}`}>
                {t.name} <strong>{parts.join(' · ')}</strong>
              </p>
            )
          })}
          {preview.tempo !== project.tempo && (
            <p className="tempo-change">
              템포 {project.tempo.toFixed(0)} → <strong>{preview.tempo.toFixed(0)} BPM</strong>
            </p>
          )}
          <div className="ab" role="group" aria-label="비교해서 듣기">
            <button aria-pressed={hearPreview} className={hearPreview ? 'on' : ''} onClick={() => setHearPreview(true)}>
              바뀐 소리
            </button>
            <button aria-pressed={!hearPreview} className={!hearPreview ? 'on' : ''} onClick={() => setHearPreview(false)}>
              원래 소리
            </button>
          </div>
          <div className="apply-row">
            <button className="apply" onClick={apply} disabled={busy || sending}>
              적용
            </button>
            <button onClick={cancel} disabled={busy || sending}>
              취소
            </button>
          </div>
        </div>
      )}

      {messages.length === 0 && (
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => submit(s)} disabled={sending}>
              {s}
            </button>
          ))}
        </div>
      )}

      {selection && (
        <div className="sel-chip" role="status">
          <span>
            <strong>고른 부분</strong> · {selectionLabel(project, selection)}
          </span>
          <button type="button" aria-label="고른 부분 풀기" title="풀기 (Esc)" onClick={() => setSelection(null)}>
            ✕
          </button>
        </div>
      )}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          submit(input)
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          에이전트에게 보낼 명령
        </label>
        <textarea
          id="chat-input"
          rows={2}
          value={input}
          maxLength={1000}
          placeholder={
            selection
              ? '고른 부분을 어떻게 바꿀까요? 예: 여기 한 옥타브 올려줘 · 이 부분 점점 작게'
              : '무엇을 바꿀까요? 예: 2마디부터 4마디까지 베이스 한 옥타브 내려줘 (피아노롤을 끌어 부분을 고를 수도 있어요)'
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // 한글 조합 중 Enter는 글자 확정이라 보내지 않는다
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit(input)
            }
          }}
        />
        <button type="submit" className="primary" disabled={sending || !input.trim()}>
          보내기
        </button>
      </form>
      <span className="hint">Enter 보내기 · Shift+Enter 줄바꿈 · 입력칸 밖에서 ? 누르면 단축키</span>
    </aside>
  )
}

const SHOWN_CHANGES = 3

/** 리하모니 제안 카드: 누르면 코드 띠가 그 제안을 보여 준다 (다시 누르면 원래 코드) */
function ReharmCards({ id, view }: { id: string; view: ReharmView }) {
  const comparing = useReharm((s) => s.comparing)
  const { compare, stop } = useReharm.getState()
  return (
    <div className="reharm-cards" role="group" aria-label="리하모니 제안">
      {view.suggestions.map((s, i) => {
        const key = `${id}-${i}`
        const on = comparing?.id === key
        return (
          <button
            key={key}
            className={on ? 'reharm-card on' : 'reharm-card'}
            aria-pressed={on}
            title={s.changes.join('\n')}
            onClick={() => (on ? stop() : compare(key, s.chords, view.base))}
          >
            <span className="reharm-head">
              <strong>{s.style}</strong>
              <span className="hint">{on ? '코드 띠에서 비교 중 · 누르면 원래대로' : '누르면 코드 띠에서 비교'}</span>
            </span>
            <span className="feel">{s.feel}</span>
            <span className="changes">
              {s.changes.slice(0, SHOWN_CHANGES).map((c) => (
                <span key={c}>{c}</span>
              ))}
              {s.changes.length > SHOWN_CHANGES && <span className="more">외 {s.changes.length - SHOWN_CHANGES}곳</span>}
            </span>
            {s.rubs.length > 0 && <span className="rub">멜로디와 살짝 부딪히는 곳 {s.rubs.length}곳 (약박의 짧은 음)</span>}
          </button>
        )
      })}
    </div>
  )
}
