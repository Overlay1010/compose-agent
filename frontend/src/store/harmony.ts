import { useEffect, useState } from 'react'
import { getHarmony } from '../api/client'
import type { Harmony } from '../api/types'
import { useProject } from './project'

interface Analyses {
  projectId: string
  current: Harmony | null
  /** 미리보기가 있을 때만 */
  preview: Harmony | null
}

/**
 * 지금 버전과 미리보기의 화성 분석 (코드 띠 · 조성 표시).
 * 버전이나 미리보기가 바뀔 때마다 다시 받는다 (분석은 서버에서 금방 끝남).
 * 다시 받는 동안은 이전 결과를 그대로 보여 줘서 띠가 깜빡이지 않게 한다.
 */
export function useHarmony(): Omit<Analyses, 'projectId'> {
  const id = useProject((s) => s.project?.id)
  const version = useProject((s) => s.project?.version)
  const preview = useProject((s) => s.preview)
  const [state, setState] = useState<Analyses | null>(null)

  useEffect(() => {
    if (!id) return
    let alive = true
    Promise.all([getHarmony(id), preview ? getHarmony(id, true) : Promise.resolve(null)])
      .then(([current, next]) => alive && setState({ projectId: id, current, preview: next }))
      // 분석이 실패해도 편집은 되니 띠만 숨긴다
      .catch(() => alive && setState({ projectId: id, current: null, preview: null }))
    return () => {
      alive = false
    }
  }, [id, version, preview])

  if (!state || state.projectId !== id) return { current: null, preview: null }
  return { current: state.current, preview: preview ? state.preview : null }
}
