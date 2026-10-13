import { useChat } from '../store/chat'
import { useProject } from '../store/project'

export function VersionPanel() {
  const { project, versions, historyOpen, setHistoryOpen, restore, busy } = useProject()
  const note = useChat((s) => s.note)
  if (!project || !historyOpen) return null

  const onRestore = async (version: number) => {
    const next = await restore(version)
    if (next) note(`v${version} 상태로 되돌렸어요 (v${next.version}로 저장)`, true)
  }

  return (
    <>
      <button className="scrim" aria-label="버전 기록 닫기" onClick={() => setHistoryOpen(false)} />
      <aside className="history" role="dialog" aria-label="버전 기록">
        <div className="history-head">
          <div>
            <h2>버전 기록</h2>
            <span className="hint">되돌려도 기록은 지워지지 않아요</span>
          </div>
          <button aria-label="닫기" onClick={() => setHistoryOpen(false)}>
            닫기
          </button>
        </div>
        <ol>
          {[...versions].reverse().map((v) => (
            <li key={v.version} className={v.current ? 'current' : undefined}>
              <span className="tag">v{v.version}</span>
              <span className="label">{v.label || '편집'}</span>
              {v.current ? (
                <span className="badge">현재</span>
              ) : (
                <button onClick={() => onRestore(v.version)} disabled={busy}>
                  되돌리기
                </button>
              )}
            </li>
          ))}
        </ol>
      </aside>
    </>
  )
}
