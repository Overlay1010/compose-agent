import { useRef, useState } from 'react'
import { DRUM_ROLE_NAMES, KIND_NAMES, PLAYABLE, noteName, type DrumRole, type SampleKind, type SampleMeta } from '../samples/analyze'
import { sampleBuffer, useSamples, type ImportResult } from '../samples/library'
import { useSamplePack } from '../store/samplePack'
import { useChat } from '../store/chat'
import { useProject } from '../store/project'

// 내 샘플팩 창: 원샷 폴더 · 파일 넣기, 자동 분석 결과(종류 · 기준음) 보기 · 고치기 · 들어 보기.
// 파일은 이 브라우저에만 저장된다 (samples/library.ts).

const KINDS = Object.keys(KIND_NAMES) as SampleKind[]
const NOTE = /^([A-Ga-g])([#b]?)(-?\d)$/
const PC: Record<string, number> = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 }

/** "F#2" → MIDI 번호 (가운데 C = C4 = 60). 못 읽으면 null */
function parseNote(text: string): number | null {
  const m = text.trim().match(NOTE)
  if (!m) return null
  const pitch = PC[m[1].toLowerCase()] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0) + (Number(m[3]) + 1) * 12
  return pitch >= 0 && pitch <= 127 ? pitch : null
}

const brightWord = (b: number) => (b < 0.35 ? '어두움' : b > 0.65 ? '밝음' : '중간')

// 끌어다 놓은 폴더 안의 파일까지 모은다 (끌어다 놓은 파일에는 폴더 경로가 없어서 webkitRelativePath를 직접 붙인다)
async function filesOf(items: DataTransferItemList): Promise<File[]> {
  const out: File[] = []
  const walk = async (entry: FileSystemEntry, path: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail))
      if (path) Object.defineProperty(file, 'webkitRelativePath', { value: `${path}/${file.name}` })
      out.push(file)
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((ok, fail) => reader.readEntries(ok, fail))
        if (!batch.length) break
        for (const e of batch) await walk(e, path ? `${path}/${entry.name}` : entry.name)
      }
    }
  }
  const entries = [...items].map((i) => i.webkitGetAsEntry()).filter((e): e is FileSystemEntry => !!e)
  for (const e of entries) await walk(e, '')
  return out
}

let preview: { ctx: AudioContext; source: AudioBufferSourceNode | null } | null = null

async function listen(meta: SampleMeta) {
  preview ??= { ctx: new AudioContext(), source: null }
  preview.source?.stop()
  const buffer = await sampleBuffer(meta.id)
  if (!buffer) return
  const source = preview.ctx.createBufferSource()
  const gain = preview.ctx.createGain()
  gain.gain.value = meta.gain * 0.6
  source.buffer = buffer
  source.connect(gain).connect(preview.ctx.destination)
  source.start()
  preview.source = source
}

function resultText(r: ImportResult): string {
  const parts = [`${r.added}개를 넣었어요`]
  if (r.same) parts.push(`이미 있던 ${r.same}개는 건너뛰었어요`)
  if (r.skipped.length) parts.push(`${r.skipped.length}개는 못 읽었어요 (WAV · MP3 · OGG · FLAC만, 30MB까지)`)
  return parts.join(' · ')
}

export function SamplePack() {
  const { open, setOpen } = useSamplePack()
  const { samples, importing, add, update, remove, clear } = useSamples()
  const [message, setMessage] = useState('')
  const [over, setOver] = useState(false)
  const folder = useRef<HTMLInputElement>(null)
  const files = useRef<HTMLInputElement>(null)
  if (!open) return null

  const put = async (list: File[]) => {
    if (!list.length) return
    setMessage(resultText(await add(list)))
  }
  const counts = KINDS.map((k) => [k, samples.filter((s) => s.kind === k).length] as const).filter(([, n]) => n)
  const usable = samples.filter((s) => PLAYABLE.includes(s.kind) && s.root !== null).length

  return (
    <>
      <button className="scrim" aria-label="내 샘플팩 닫기" onClick={() => setOpen(false)} />
      <div className="sample-pack" role="dialog" aria-label="내 샘플팩">
        <div className="history-head">
          <div>
            <h2>내 샘플팩</h2>
            <span className="hint">파일은 이 브라우저에만 저장돼요 (서버에 올리지 않아요). 곡에는 샘플 이름만 남아요.</span>
          </div>
          <button onClick={() => setOpen(false)}>닫기</button>
        </div>

        <div
          className={over ? 'drop on' : 'drop'}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            void filesOf(e.dataTransfer.items).then(put)
          }}
        >
          <p>
            원샷 WAV 폴더를 여기에 끌어다 놓거나
            <button onClick={() => folder.current?.click()} disabled={!!importing}>폴더 고르기</button>
            <button onClick={() => files.current?.click()} disabled={!!importing}>파일 고르기</button>
          </p>
          <p className="hint">
            이름과 소리로 종류(베이스 · 패드 · 건반 · 플럭 · 리드 · 벨)와 기준음을 알아내요. 틀리면 아래에서 고칠 수 있어요.
            드럼 원샷은 역할(킥 · 스네어 · 햇 …)을 알아내 드럼 레인 소리로 써요. 코드 원샷 · 루프는 아직 악기로 못 써요.
          </p>
          <input ref={folder} type="file" hidden multiple {...{ webkitdirectory: '' }} onChange={(e) => void put([...(e.target.files ?? [])]).then(() => (e.target.value = ''))} />
          <input ref={files} type="file" hidden multiple accept=".wav,.mp3,.ogg,.flac,.m4a,audio/*" onChange={(e) => void put([...(e.target.files ?? [])]).then(() => (e.target.value = ''))} />
        </div>

        {importing && (
          <p className="sample-status">
            <span className="spinner" aria-hidden="true" /> 분석하는 중… {importing.done} / {importing.total}
          </p>
        )}
        {message && !importing && <p className="sample-status">{message}</p>}

        {samples.length > 0 && (
          <>
            <div className="sample-summary">
              <span>
                {samples.length}개 · 악기로 쓸 수 있는 것 {usable}개
                {counts.length > 0 && ` — ${counts.map(([k, n]) => `${KIND_NAMES[k]} ${n}`).join(' · ')}`}
              </span>
              <button
                className="danger"
                onClick={() => {
                  if (confirm('이 브라우저에 넣은 샘플을 모두 지울까요? 곡에서 쓰던 샘플은 원래 악기 소리로 들려요.')) void clear()
                }}
              >
                모두 지우기
              </button>
            </div>
            <div className="sample-list" role="table" aria-label="샘플 목록">
              {samples.map((s) => (
                <SampleRow key={s.id} meta={s} onChange={(patch) => void update(s.id, patch)} onRemove={() => void remove(s.id)} />
              ))}
            </div>
          </>
        )}
      </div>
    </>
  )
}

function SampleRow({
  meta,
  onChange,
  onRemove,
}: {
  meta: SampleMeta
  onChange: (patch: Partial<Pick<SampleMeta, 'kind' | 'root' | 'drum'>>) => void
  onRemove: () => void
}) {
  const [rootText, setRootText] = useState(meta.root === null ? '' : noteName(meta.root))
  const playable = (PLAYABLE.includes(meta.kind) && meta.root !== null) || (meta.kind === 'drum' && !!meta.drum)
  const from = (f: SampleMeta['rootFrom'] | SampleMeta['kindFrom']) => (f === 'name' ? '이름에서' : f === 'audio' ? '소리에서' : f === 'user' ? '직접 고침' : '')
  return (
    <div className={playable ? 'sample-row' : 'sample-row unusable'} role="row">
      <button className="icon" onClick={() => void listen(meta)} aria-label={`${meta.name} 들어 보기`} title="들어 보기">
        ▶
      </button>
      <span className="sample-name" title={meta.folder ? `${meta.folder}/${meta.name}` : meta.name}>
        {meta.name}
      </span>
      <select value={meta.kind} onChange={(e) => onChange({ kind: e.target.value as SampleKind })} aria-label={`${meta.name} 종류`} title={`종류 (${from(meta.kindFrom)})`}>
        {KINDS.map((k) => (
          <option key={k} value={k}>
            {KIND_NAMES[k]}
          </option>
        ))}
      </select>
      {meta.kind === 'drum' ? (
        <select value={meta.drum ?? 'perc'} onChange={(e) => onChange({ drum: e.target.value as DrumRole })} aria-label={`${meta.name} 드럼 역할`} title="드럼 레인 중 어디에 쓸지">
          {(Object.keys(DRUM_ROLE_NAMES) as DrumRole[]).map((r) => (
            <option key={r} value={r}>
              {DRUM_ROLE_NAMES[r]}
            </option>
          ))}
        </select>
      ) : (
      <input
        className="sample-root"
        value={rootText}
        placeholder="음 없음"
        aria-label={`${meta.name} 기준음`}
        title={`기준음 — 이 음 높이로 녹음됨 (${from(meta.rootFrom) || '못 찾음'}). 가운데 C = C4`}
        onChange={(e) => setRootText(e.target.value)}
        onBlur={() => {
          const pitch = rootText.trim() ? parseNote(rootText) : null
          if (rootText.trim() && pitch === null) {
            setRootText(meta.root === null ? '' : noteName(meta.root)) // 못 읽으면 원래대로
          } else if (pitch !== meta.root) {
            onChange({ root: pitch })
            setRootText(pitch === null ? '' : noteName(pitch))
          }
        }}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
      )}
      <span className="sample-meta">
        {meta.kind === 'loop' && meta.groove ? (
          <button
            className="groove"
            onClick={() => {
              useSamplePack.getState().setOpen(false)
              void useChat.getState().send(`'${meta.name}' 루프 리듬으로 하이햇 깔아줘`, false)
            }}
            disabled={!useProject.getState().project}
            title={`이 루프의 치는 자리 · 세기를 그대로 하이햇 MIDI로 (${meta.groove.bpm} BPM · ${meta.groove.hits.length}타)`}
          >
            이 리듬으로 하이햇
          </button>
        ) : (
          <>
            {meta.length.toFixed(1)}초 · {brightWord(meta.brightness)}
            {meta.sustained ? ' · 길게 끌림' : ''}
          </>
        )}
      </span>
      <button className="icon" onClick={onRemove} aria-label={`${meta.name} 지우기`} title="지우기">
        ×
      </button>
    </div>
  )
}
