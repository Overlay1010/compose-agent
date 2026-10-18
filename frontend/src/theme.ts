import type { Track } from './api/types'
import { gmProgramOf, kitName } from './audio/catalog'

// 트랙 구분 색. 대표 색(라임)은 "바뀔 음"에만 쓰니 트랙 색에는 넣지 않는다.
const TRACK_COLORS = ['#8ea4ff', '#4fd1b8', '#b79cff', '#6fb3e0', '#ff8fbf', '#ff9f43', '#e6e3dc', '#f2d36b']

export function trackColor(project: { tracks: Track[] }, trackId: string): string {
  // 미리보기에만 있는 새 트랙(t6 …)은 목록에 없으니 id 번호로 색을 고른다
  const found = project.tracks.findIndex((t) => t.id === trackId)
  const i = found >= 0 ? found : Math.max(0, Number(trackId.replace(/\D/g, '')) - 1 || 0)
  return TRACK_COLORS[i % TRACK_COLORS.length]
}

// General MIDI 악기 번호 8개씩 = 악기 종류 (백엔드 app/agent/prompt.py와 같은 목록)
const GM_FAMILIES = [
  '피아노', '벨 · 말렛', '오르간', '기타', '베이스', '현악기', '스트링 앙상블', '금관',
  '리드 목관', '플룻 · 피리', '신스 리드', '신스 패드', '신스 효과음', '민속 악기', '타악기', '효과음',
]
const GM_NAMES: Record<number, string> = {
  0: '그랜드 피아노', 4: '전자 피아노', 5: '전자 피아노 (FM)', 24: '나일론 기타', 25: '스틸 기타',
  27: '클린 일렉 기타', 32: '어쿠스틱 베이스', 33: '핑거 베이스', 34: '피크 베이스', 38: '신스 베이스',
  48: '스트링 앙상블', 52: '합창', 61: '브라스 섹션', 73: '플룻', 80: '사각파 리드', 81: '톱니파 리드',
  88: '뉴에이지 패드', 89: '따뜻한 패드', 9: '글로켄슈필',
}

// General MIDI 악기 이름 (번호 = 목록 위치). 한국어 이름이 없는 악기는 이 이름을 보여 준다.
const GM_EN = [
  'Acoustic Grand Piano', 'Bright Acoustic Piano', 'Electric Grand Piano', 'Honky-tonk Piano', 'Electric Piano 1', 'Electric Piano 2', 'Harpsichord', 'Clavinet',
  'Celesta', 'Glockenspiel', 'Music Box', 'Vibraphone', 'Marimba', 'Xylophone', 'Tubular Bells', 'Dulcimer',
  'Drawbar Organ', 'Percussive Organ', 'Rock Organ', 'Church Organ', 'Reed Organ', 'Accordion', 'Harmonica', 'Tango Accordion',
  'Nylon Guitar', 'Steel Guitar', 'Jazz Guitar', 'Clean Guitar', 'Muted Guitar', 'Overdriven Guitar', 'Distortion Guitar', 'Guitar Harmonics',
  'Acoustic Bass', 'Finger Bass', 'Pick Bass', 'Fretless Bass', 'Slap Bass 1', 'Slap Bass 2', 'Synth Bass 1', 'Synth Bass 2',
  'Violin', 'Viola', 'Cello', 'Contrabass', 'Tremolo Strings', 'Pizzicato Strings', 'Orchestral Harp', 'Timpani',
  'String Ensemble 1', 'String Ensemble 2', 'Synth Strings 1', 'Synth Strings 2', 'Choir Aahs', 'Voice Oohs', 'Synth Choir', 'Orchestra Hit',
  'Trumpet', 'Trombone', 'Tuba', 'Muted Trumpet', 'French Horn', 'Brass Section', 'Synth Brass 1', 'Synth Brass 2',
  'Soprano Sax', 'Alto Sax', 'Tenor Sax', 'Baritone Sax', 'Oboe', 'English Horn', 'Bassoon', 'Clarinet',
  'Piccolo', 'Flute', 'Recorder', 'Pan Flute', 'Blown Bottle', 'Shakuhachi', 'Whistle', 'Ocarina',
  'Square Lead', 'Saw Lead', 'Calliope Lead', 'Chiff Lead', 'Charang Lead', 'Voice Lead', 'Fifths Lead', 'Bass + Lead',
  'New Age Pad', 'Warm Pad', 'Polysynth Pad', 'Choir Pad', 'Bowed Pad', 'Metallic Pad', 'Halo Pad', 'Sweep Pad',
  'Rain', 'Soundtrack', 'Crystal', 'Atmosphere', 'Brightness', 'Goblins', 'Echoes', 'Sci-fi',
  'Sitar', 'Banjo', 'Shamisen', 'Koto', 'Kalimba', 'Bagpipe', 'Fiddle', 'Shanai',
  'Tinkle Bell', 'Agogo', 'Steel Drums', 'Woodblock', 'Taiko Drum', 'Melodic Tom', 'Synth Drum', 'Reverse Cymbal',
  'Guitar Fret Noise', 'Breath Noise', 'Seashore', 'Bird Tweet', 'Telephone Ring', 'Helicopter', 'Applause', 'Gunshot',
]

/** 악기 번호 하나의 이름 (한국어가 있으면 한국어) */
export function programName(program: number): string {
  return GM_NAMES[program] ?? GM_EN[program]
}

/** 트랙 소리 이름: 드럼이면 킷 이름, 아니면 악기 이름 */
export function soundName(track: Track): string {
  return track.is_drum ? `드럼 킷 ${kitName(track.program)}` : programName(gmProgramOf(track))
}

/** 악기 고르기 목록: 종류별 8개씩 */
export const GM_GROUPS = GM_FAMILIES.map((family, f) => ({
  family,
  programs: Array.from({ length: 8 }, (_, i) => f * 8 + i),
}))

/** 화면에 보일 악기 이름. FL Studio처럼 번호가 0이면 트랙 이름으로 고른 악기(재생에 쓰는 것)를 보여 준다. */
export function instrumentLabel(track: Track): string {
  if (track.is_drum) return '드럼'
  return programName(gmProgramOf(track))
}
