/** "방금 · 3분 전 · 2시간 전 · 10월 17일 오후 8:31" (시각이 없으면 빈 문자열) */
export function timeAgo(iso: string, now = Date.now()): string {
  if (!iso) return ''
  const at = new Date(iso).getTime()
  if (Number.isNaN(at)) return ''
  const sec = Math.max(0, (now - at) / 1000)
  if (sec < 60) return '방금'
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`
  return new Date(at).toLocaleString('ko-KR', { month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** 히스토리 · 알림에 넣을 짧은 설명 (백엔드 app/store/memory.py short와 같게) */
export function shortLabel(label: string, size = 24): string {
  const s = label.trim().replace(/\.$/, '')
  return s.length <= size ? s : `${s.slice(0, size - 1)}…`
}
