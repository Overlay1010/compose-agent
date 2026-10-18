import { useChat } from '../store/chat'
import { useProject } from '../store/project'
import { shortLabel, timeAgo } from '../time'

/** 히스토리: 지금까지 저장된 상태 목록. 예전 상태로 되돌려도 지우지 않고 새 기록으로 남긴다 */
export function VersionPanel() {
  const { project, versions, historyOpen, setHistoryOpen, restore, busy } = useProject()
  const note = useChat((s) => s.note)
  if (!project || !historyOpen) return null

  const onRestore = async (version: number, label: string) => {
    const next = await restore(version)
    if (next) note(`"${shortLabel(label || '편집')}" 상태로 되돌렸어요`, true)
  }

  return (
    <>
      <button className="scrim" aria-label="히스토리 닫기" onClick={() => setHistoryOpen(false)} />
      <aside className="history" role="dialog" aria-label="히스토리">
        <div className="history-head">
          <div>
            <h2>히스토리</h2>
            <span className="hint">되돌려도 기록은 지워지지 않아요</span>
          </div>
          <button aria-label="닫기" onClick={() => setHistoryOpen(false)}>
            닫기
          </button>
        </div>
        <ol>
          {[...versions].reverse().map((v) => (
            <li key={v.version} className={v.current ? 'current' : undefined}>
              <span className="tag">{v.version}</span>
              <span className="label" title={v.label}>
                <span className="what">{v.label || '편집'}</span>
                {v.created_at && <span className="when">{timeAgo(v.created_at)}</span>}
              </span>
              {v.current ? (
                <span className="badge">지금</span>
              ) : (
                <button onClick={() => onRestore(v.version, v.label)} disabled={busy}>
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
