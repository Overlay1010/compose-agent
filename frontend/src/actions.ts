import { useChat } from './store/chat'
import { useProject } from './store/project'

// 버튼과 단축키가 같은 동작(알림 한 줄 포함)을 하도록 한곳에 둔다.

/** 미리보기 적용 → 새 버전 */
export async function applyWithNote() {
  const next = await useProject.getState().applyPreview()
  if (next) useChat.getState().note(`v${next.version}로 적용했어요`, true)
}

/** 미리보기 취소 (곡은 그대로) */
export async function cancelWithNote() {
  await useProject.getState().cancelPreview()
  if (!useProject.getState().preview) useChat.getState().note('미리보기를 취소했어요. 곡은 그대로예요.')
}

/** 바로 전 버전으로 되돌리기 (새 버전으로 남음) */
export async function undoWithNote() {
  const before = useProject.getState().project?.version
  if (!before || before < 2) return
  const next = await useProject.getState().undo()
  if (next) useChat.getState().note(`v${before - 1} 상태로 되돌렸어요 (v${next.version}로 저장)`, true)
}
