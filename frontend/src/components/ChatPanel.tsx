import { useEffect, useRef, useState } from 'react'
import { useChat } from '../store/chat'
import { useProject } from '../store/project'

const SUGGESTIONS = [
  '지금 무슨 트랙 있어?',
  '하이햇 좀 약하게 하고 살짝 스윙 넣어줘',
  '박자 맞춰줘, 너무 딱딱하진 않게',
  '멜로디 한 옥타브 내려줘',
]

export function ChatPanel() {
  const { project, preview, baseVersion, hearPreview, setHearPreview, applyPreview, cancelPreview, undo, busy } = useProject()
  const { messages, sending, send, note } = useChat()
  const [input, setInput] = useState('')
  const list = useRef<HTMLDivElement>(null)

  // 새 메시지가 오면 맨 아래로
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [messages, sending])

  if (!project) return null

  const apply = async () => {
    const next = await applyPreview()
    if (next) note(`v${next.version}로 적용했어요`, true)
  }
  const cancel = async () => {
    await cancelPreview()
    if (!useProject.getState().preview) note('미리보기를 취소했어요. 곡은 그대로예요.')
  }
  const revert = async () => {
    const before = project.version
    const next = await undo()
    if (next) note(`v${before - 1} 상태로 되돌렸어요 (v${next.version}로 저장)`, true)
  }

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
            <p key={m.id} className="msg user">
              {m.text}
            </p>
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
                    <li key={i} className={s.running ? 'step running' : s.ok ? 'step' : 'step failed'} title={JSON.stringify(s.args)}>
                      <span className="mark" aria-hidden="true">
                        {s.running ? <span className="spinner small" /> : s.ok ? '✓' : '!'}
                      </span>
                      <span className="tool">{s.name}</span>
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
            <strong>미리보기</strong> · v{baseVersion} 기준 · 다음 명령도 이 위에 이어서 쌓여요
          </p>
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
          placeholder="무엇을 바꿀까요? 예: 2마디부터 4마디까지 베이스 한 옥타브 내려줘"
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
      <span className="hint">Enter 보내기 · Shift+Enter 줄바꿈</span>
    </aside>
  )
}
