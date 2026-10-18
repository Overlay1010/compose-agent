import { create } from 'zustand'
import { applyWithNote, cancelWithNote, undoWithNote } from './actions'
import { usePlayer } from './store/player'
import { useProject } from './store/project'

// DAW와 비슷한 키보드 단축키. 글자를 입력하는 칸(채팅 · 슬라이더 · 선택 상자)에 있을 때는 동작하지 않는다.

export const SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ['Space'], label: '재생 · 정지' },
  { keys: ['B'], label: '바뀐 소리 ↔ 원래 소리' },
  { keys: ['Enter'], label: '미리보기 적용' },
  { keys: ['Esc'], label: '고른 부분 풀기 · 미리보기 취소 · 창 닫기' },
  { keys: ['Ctrl', 'Z'], label: '바로 전 상태로 되돌리기' },
  { keys: ['←', '→'], label: '한 마디 앞 · 뒤로' },
  { keys: ['Home'], label: '처음으로' },
  { keys: ['L'], label: '구간 반복 켜기 · 끄기' },
  { keys: ['↑', '↓'], label: '위 · 아래 트랙 고르기 (음을 고르지 않았을 때)' },
  { keys: ['M'], label: '고른 트랙 음소거' },
  { keys: ['S'], label: '고른 트랙 솔로' },
  { keys: ['Delete'], label: '고른 음 지우기 (피아노롤)' },
  { keys: ['↑', '↓'], label: '고른 음 반음 올리기 · 내리기 (Shift = 옥타브)' },
  { keys: ['Ctrl', 'A'], label: '그 트랙 음 모두 고르기' },
  { keys: ['/'], label: '채팅 입력칸으로' },
  { keys: ['?'], label: '단축키 목록' },
]

export const useShortcutHelp = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}))

// 피아노롤에서 음을 골랐을 때 Delete · ↑↓ · Ctrl+A 같은 키를 먼저 받는 곳 (components/PianoRoll.tsx가 등록)
let noteKeys: ((e: KeyboardEvent) => boolean) | null = null
export function setNoteKeys(handler: ((e: KeyboardEvent) => boolean) | null) {
  noteKeys = handler
}

const typing = (target: EventTarget | null) =>
  target instanceof HTMLElement && !!target.closest('input, textarea, select, [contenteditable]')

/** keydown 하나를 처리했으면 true (기본 동작은 막는다) */
export function handleShortcut(e: KeyboardEvent): boolean {
  if (e.repeat && e.code !== 'ArrowLeft' && e.code !== 'ArrowRight') return false
  if (typing(e.target)) return false
  if (noteKeys?.(e)) return true

  const help = useShortcutHelp.getState()
  const project = useProject.getState()
  const player = usePlayer.getState()

  if (e.key === '?') {
    help.setOpen(!help.open)
    return true
  }
  if (e.key === 'Escape') {
    if (help.open) help.setOpen(false)
    else if (project.selection) project.setSelection(null)
    else if (project.historyOpen) project.setHistoryOpen(false)
    else if (project.preview && !project.busy) void cancelWithNote()
    else return false
    return true
  }
  if (!project.project || help.open) return false

  // Ctrl+Z (맥은 Cmd+Z). 다른 조합키는 브라우저 기능이라 건드리지 않는다
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.code === 'KeyZ') {
    if (project.busy) return true
    void undoWithNote()
    return true
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return false

  const p = project.project
  const bpb = (p.time_signature[0] * 4) / p.time_signature[1]
  // 목록 순서 그대로 (미리보기에만 있는 새 트랙은 끝에)
  const tracks = [...p.tracks, ...(project.preview?.tracks.filter((t) => !p.tracks.some((o) => o.id === t.id)) ?? [])]
  const selected = project.selectedTrackId

  switch (e.code) {
    case 'Space':
      player.toggle()
      return true
    case 'KeyB':
      if (!project.preview) return false
      project.setHearPreview(!project.hearPreview)
      return true
    case 'Enter':
    case 'NumpadEnter':
      // 버튼에 초점이 있으면 Enter는 그 버튼을 누르는 것이라 양보한다
      if (e.target instanceof HTMLElement && e.target.closest('button, a')) return false
      if (!project.preview || project.busy) return false
      void applyWithNote()
      return true
    case 'ArrowLeft':
      player.seek(Math.max(0, (Math.ceil(player.cursor / bpb - 1e-6) - 1) * bpb))
      return true
    case 'ArrowRight': {
      // 마지막 마디 처음까지만
      const end = Math.max(0, ...tracks.flatMap((t) => t.notes.map((n) => n.start + n.duration)))
      const lastBar = Math.max(0, Math.ceil(end / bpb) - 1) * bpb
      player.seek(Math.min(lastBar, (Math.floor(player.cursor / bpb + 1e-6) + 1) * bpb))
      return true
    }
    case 'Home':
      player.restart()
      return true
    case 'KeyL':
      player.toggleLoop()
      return true
    case 'ArrowUp':
    case 'ArrowDown': {
      const i = tracks.findIndex((t) => t.id === selected)
      const next = tracks[Math.min(tracks.length - 1, Math.max(0, i + (e.code === 'ArrowUp' ? -1 : 1)))]
      if (next) project.selectTrack(next.id)
      return true
    }
    case 'KeyM':
      if (selected) player.toggleMute(selected)
      return true
    case 'KeyS':
      if (selected) player.toggleSolo(selected)
      return true
    case 'Slash':
      document.getElementById('chat-input')?.focus()
      return true
  }
  return false
}
