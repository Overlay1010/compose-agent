import type { Track } from './api/types'
import { gmProgramOf } from './audio/instruments'

// 트랙 구분 색. 대표 색(라임)은 "바뀔 음"에만 쓰니 트랙 색에는 넣지 않는다.
const TRACK_COLORS = ['#8ea4ff', '#4fd1b8', '#b79cff', '#6fb3e0', '#ff8fbf', '#ff9f43', '#e6e3dc', '#f2d36b']

export function trackColor(project: { tracks: Track[] }, trackId: string): string {
  const i = Math.max(0, project.tracks.findIndex((t) => t.id === trackId))
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

/** 화면에 보일 악기 이름. FL Studio처럼 번호가 0이면 트랙 이름으로 고른 악기(재생에 쓰는 것)를 보여 준다. */
export function instrumentLabel(track: Track): string {
  if (track.is_drum) return '드럼'
  const program = gmProgramOf(track)
  return GM_NAMES[program] ?? GM_FAMILIES[Math.floor(program / 8)]
}
