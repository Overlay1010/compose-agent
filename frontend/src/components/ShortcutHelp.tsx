import { SHORTCUTS, useShortcutHelp } from '../shortcuts'

/** ? 키나 상단 버튼으로 여는 단축키 목록 */
export function ShortcutHelp() {
  const { open, setOpen } = useShortcutHelp()
  if (!open) return null
  return (
    <>
      <button className="scrim" aria-label="단축키 목록 닫기" onClick={() => setOpen(false)} />
      <div className="shortcut-help" role="dialog" aria-label="단축키">
        <div className="history-head">
          <div>
            <h2>단축키</h2>
            <span className="hint">채팅 입력칸 · 슬라이더에 있을 때는 동작하지 않아요</span>
          </div>
          <button onClick={() => setOpen(false)}>닫기</button>
        </div>
        <dl>
          {SHORTCUTS.map((s) => (
            <div key={s.label}>
              <dt>
                {s.keys.map((k) => (
                  <kbd key={k}>{k}</kbd>
                ))}
              </dt>
              <dd>{s.label}</dd>
            </div>
          ))}
        </dl>
      </div>
    </>
  )
}
