import { create } from 'zustand'
import { ANALYSIS_VERSION, KIND_NAMES, analyze, drumFromName, type SampleMeta } from './analyze'

// 내 샘플팩: 사용자가 넣은 원샷 파일과 분석한 이름표를 이 브라우저(IndexedDB)에만 저장한다.
// 서버 · 저장소에는 올리지 않는다 (남의 샘플이라 라이선스상 퍼뜨리면 안 되고, 크기도 크다).
// 서버에는 이름표(종류 · 기준음 · 길이 · 밝기)만 보내 추천 · 채팅에 쓰고, 곡에는 샘플 id와 이름만 남는다.

const DB = 'compose-agent-samples'
const STORE = 'samples'
const FORMATS = /\.(wav|mp3|ogg|flac|m4a)$/i // 브라우저가 풀 수 있는 형식 (AIFF는 Chrome이 못 푼다)
const MAX_BYTES = 30 * 1024 * 1024
export const MAX_SAMPLES = 3000

interface Stored {
  meta: SampleMeta
  blob: Blob
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'meta.id' })
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode)
    const req = run(t.objectStore(STORE))
    t.oncomplete = () => resolve(req ? req.result : undefined)
    t.onerror = () => reject(t.error)
  })
}

/** 파일 내용으로 만든 id — 같은 파일을 다시 넣거나 다른 브라우저에 넣어도 곡의 샘플과 이어진다 */
async function idOf(bytes: ArrayBuffer): Promise<string> {
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
  return [...hash.slice(0, 12)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** 압축을 풀어 소리 데이터로. 재생 · 분석이 같이 쓴다 (44.1kHz로 맞춤) */
async function decode(bytes: ArrayBuffer): Promise<AudioBuffer> {
  return new OfflineAudioContext(1, 1, 44100).decodeAudioData(bytes)
}

function mono(buffer: AudioBuffer): Float32Array {
  if (buffer.numberOfChannels === 1) return buffer.getChannelData(0)
  const out = new Float32Array(buffer.length)
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const d = buffer.getChannelData(c)
    for (let i = 0; i < d.length; i++) out[i] += d[i] / buffer.numberOfChannels
  }
  return out
}

export interface ImportResult {
  added: number
  same: number // 이미 있던 파일
  skipped: string[] // 형식 · 크기 · 풀기 실패
}

interface LibraryState {
  loaded: boolean
  samples: SampleMeta[]
  importing: { done: number; total: number } | null
  load: () => Promise<void>
  add: (files: File[]) => Promise<ImportResult>
  update: (id: string, patch: Partial<Pick<SampleMeta, 'kind' | 'root' | 'drum'>>) => Promise<void>
  remove: (id: string) => Promise<void>
  clear: () => Promise<void>
}

// 목록 순서: 악기로 쓸 수 있는 종류(베이스 → … → 벨)가 먼저, 그다음 코드 원샷 · 루프 · 드럼 · 기타 (KIND_NAMES 순서)
const KIND_ORDER = Object.keys(KIND_NAMES)
const byKindName = (a: SampleMeta, b: SampleMeta) =>
  KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || a.name.localeCompare(b.name)

let loading: Promise<void> | null = null
const buffers = new Map<string, Promise<AudioBuffer | null>>() // 풀어 둔 소리 (id → 재생용)

export const useSamples = create<LibraryState>((set, get) => ({
  loaded: false,
  samples: [],
  importing: null,

  load: () => {
    loading ??= tx<Stored[]>('readonly', (s) => s.getAll())
      .then(async (rows) => {
        set({ samples: (rows ?? []).map((r) => r.meta).sort(byKindName), loaded: true })
        await upgrade(rows ?? [])
      })
      .catch(() => set({ loaded: true })) // 사생활 보호 창 등에서 IndexedDB를 못 쓰면 빈 샘플팩
    return loading
  },

  add: async (files) => {
    const result: ImportResult = { added: 0, same: 0, skipped: [] }
    const known = new Set(get().samples.map((s) => s.id))
    const room = MAX_SAMPLES - known.size
    const usable = files.filter((f) => {
      const ok = FORMATS.test(f.name) && f.size <= MAX_BYTES
      if (!ok && !f.name.startsWith('.')) result.skipped.push(f.name)
      return ok
    })
    if (usable.length > room) result.skipped.push(...usable.splice(room).map((f) => f.name))
    set({ importing: { done: 0, total: usable.length } })
    const fresh: SampleMeta[] = []
    for (const [i, file] of usable.entries()) {
      try {
        const bytes = await file.arrayBuffer()
        const id = await idOf(bytes)
        if (known.has(id)) {
          result.same++
        } else {
          const buffer = await decode(bytes.slice(0)) // 풀기는 원본 버퍼를 넘겨받아 비워서 사본으로
          const folder = (file.webkitRelativePath || '').split('/').slice(0, -1).join('/')
          const meta = analyze(id, file.name, folder, mono(buffer), buffer.sampleRate)
          await tx('readwrite', (s) => s.put({ meta, blob: file } satisfies Stored))
          known.add(id)
          fresh.push(meta)
          result.added++
        }
      } catch {
        result.skipped.push(file.name)
      }
      set({ importing: { done: i + 1, total: usable.length } })
      // 몇 개마다 화면을 다시 그릴 틈을 준다 (큰 팩에서 멈춘 것처럼 보이지 않게)
      if (i % 8 === 7) await new Promise((r) => setTimeout(r, 0))
    }
    set({ samples: [...get().samples, ...fresh].sort(byKindName), importing: null })
    return result
  },

  update: async (id, patch) => {
    const row = await tx<Stored>('readonly', (s) => s.get(id))
    if (!row) return
    const meta: SampleMeta = {
      ...row.meta,
      ...patch,
      ...('kind' in patch || 'drum' in patch ? { kindFrom: 'user' as const } : {}), // 드럼 역할도 종류의 일부
      ...('root' in patch ? { rootFrom: 'user' as const } : {}),
    }
    // 드럼으로 바꿨는데 역할이 없으면 이름으로 짐작한 역할부터 (화면에서 바로 고칠 수 있게)
    if (meta.kind === 'drum' && !meta.drum) meta.drum = drumFromName(meta.name) ?? 'perc'
    if (meta.kind !== 'drum') meta.drum = null
    await tx('readwrite', (s) => s.put({ ...row, meta }))
    set({ samples: get().samples.map((s) => (s.id === id ? meta : s)).sort(byKindName) })
  },

  remove: async (id) => {
    await tx('readwrite', (s) => s.delete(id))
    buffers.delete(id)
    set({ samples: get().samples.filter((s) => s.id !== id) })
  },

  clear: async () => {
    await tx('readwrite', (s) => s.clear())
    buffers.clear()
    set({ samples: [] })
  },
}))

export const sampleMeta = (id: string) => useSamples.getState().samples.find((s) => s.id === id)

/** 서버에 보내는 이름표 (backend app/tools/samples.py SampleInfo) — 소리 파일은 보내지 않는다. 루프는 리듬(치는 자리 · 세기)도 */
export const sampleInfos = () =>
  useSamples.getState().samples.map(({ id, name, kind, root, length, sustained, brightness, drum, groove }) => ({
    id, name, kind, root, length, sustained, brightness, drum: drum ?? null,
    // 자르는 자리(cuts)는 브라우저 재생에만 쓰여 서버에는 보내지 않는다
    groove: kind === 'loop' && groove ? { bpm: groove.bpm, beats: groove.beats, hits: groove.hits } : null,
  }))

/** 예전 규칙으로 분석한 샘플(ANALYSIS_VERSION이 다름)을 다시 분석한다. 사용자가 고친 종류 · 드럼 역할 · 기준음은 그대로 */
async function upgrade(rows: Stored[]) {
  const old = rows.filter((r) => r.meta.v !== ANALYSIS_VERSION)
  for (const row of old) {
    try {
      const buffer = await decode(await row.blob.arrayBuffer())
      const fresh = analyze(row.meta.id, `${row.meta.name}.wav`, row.meta.folder, mono(buffer), buffer.sampleRate)
      const meta: SampleMeta = {
        ...fresh,
        ...(row.meta.kindFrom === 'user' ? { kind: row.meta.kind, drum: row.meta.drum ?? null, kindFrom: 'user' as const } : {}),
        ...(row.meta.rootFrom === 'user' ? { root: row.meta.root, rootFrom: 'user' as const } : {}),
      }
      if (meta.kind !== 'drum') meta.drum = null
      else meta.drum ??= 'perc'
      await tx('readwrite', (s) => s.put({ ...row, meta }))
      useSamples.setState((st) => ({ samples: st.samples.map((s) => (s.id === meta.id ? meta : s)).sort(byKindName) }))
    } catch {
      // 못 읽은 파일은 그대로 둔다 (재생할 때 트랙 악기 · 킷 소리로)
    }
  }
}

/** 재생용 소리. 이 브라우저에 없으면 null */
export function sampleBuffer(id: string): Promise<AudioBuffer | null> {
  let p = buffers.get(id)
  if (!p) {
    p = tx<Stored>('readonly', (s) => s.get(id))
      .then(async (row) => (row ? decode(await row.blob.arrayBuffer()) : null))
      .catch(() => null)
    buffers.set(id, p)
  }
  return p
}
