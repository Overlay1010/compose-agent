import { useEffect, useState } from 'react'
import { recentProjects } from '../api/client'
import type { RecentProject } from '../api/types'
import { reopen } from '../store/chat'
import { useProject } from '../store/project'

const when = (iso: string) =>
  iso ? new Date(iso).toLocaleString('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

// frontend/public/demo/ 에 들어 있는 샘플 (scripts/make_samples.py가 만든다)
const SAMPLES = [
  { file: 'lofi_groove.mid', meta: '84 BPM · 16마디 · 트랙 5', desc: '드럼 · 베이스 · Rhodes · 패드 · 멜로디' },
  { file: 'fl_style_loose.mid', meta: '120 BPM · 8마디 · 트랙 4', desc: 'FL Studio식 · 박자와 세기가 조금씩 흔들림' },
  { file: 'waltz_3_4.mid', meta: '150 BPM · 3/4 · 8마디', desc: '왼손 쿵-짝-짝 · 오른손 멜로디' },
]

const EXAMPLES = ['베이스 2키 올려줘', '하이햇 좀 약하게 하고 살짝 스윙', '박자 맞춰줘, 너무 딱딱하진 않게', '템포 100으로 바꿔줘']

export function EmptyState() {
  const { upload, loading } = useProject()
  const [opening, setOpening] = useState<string | null>(null)
  const [recent, setRecent] = useState<RecentProject[]>([])

  useEffect(() => {
    recentProjects()
      .then(setRecent)
      .catch(() => setRecent([])) // 목록을 못 받아도 처음 화면은 그대로 쓸 수 있다
  }, [])

  const openSample = async (file: string) => {
    setOpening(file)
    try {
      const blob = await (await fetch(`/demo/${file}`)).blob()
      await upload(new File([blob], file, { type: 'audio/midi' }))
    } finally {
      setOpening(null)
    }
  }

  return (
    <section className="empty-state">
      <div className="hero">
        <h1>MIDI를 열고, 말로 고치세요</h1>
        <p>
          FL Studio · Logic Pro · Cubase · Ableton Live에서 내보낸 .mid를 이 창에 끌어다 놓거나 위의 <strong>MIDI 열기</strong>를
          누르세요. 바꾸고 싶은 걸 말하면 적용하기 전에 바뀐 소리를 먼저 들려 드려요.
        </p>
      </div>

      <div className="drop" aria-hidden="true">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 15V3" />
          <path d="m7 8 5-5 5 5" />
          <path d="M20 15v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4" />
        </svg>
        <span>.mid 파일을 여기에 끌어다 놓기 · 최대 5MB</span>
      </div>

      {recent.length > 0 && (
        <div className="samples">
          <h2>이어서 하기</h2>
          <div className="sample-grid">
            {recent.map((r) => (
              <button key={r.id} className="sample" onClick={() => void reopen(r.id)} disabled={loading}>
                <span className="file">{r.name}</span>
                <span className="meta">
                  v{r.version}
                  {r.updated_at && ` · ${when(r.updated_at)}`}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="samples">
        <h2>샘플로 바로 시작</h2>
        <div className="sample-grid">
          {SAMPLES.map((s) => (
            <button key={s.file} className="sample" onClick={() => openSample(s.file)} disabled={loading}>
              <span className="file">{opening === s.file ? '여는 중…' : s.file}</span>
              <span className="meta">{s.meta}</span>
              <span className="desc">{s.desc}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="examples">
        <h2>이렇게 말해 보세요</h2>
        <ul>
          {EXAMPLES.map((e) => (
            <li key={e}>“{e}”</li>
          ))}
        </ul>
      </div>
    </section>
  )
}
