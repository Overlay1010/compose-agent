import type { Track } from '../api/types'

// 악기 · 드럼 소리 목록과 킷 정의 (Tone.js가 필요 없는 데이터).
// 화면은 여기서만 가져와서, 소리 라이브러리(Tone.js)는 처음 재생할 때 따로 불러온다 (audio/engine.ts).

// General MIDI 악기 번호 순서 (FluidR3 GM 파일 이름)
export const GM_NAMES = [
  'acoustic_grand_piano', 'bright_acoustic_piano', 'electric_grand_piano', 'honkytonk_piano', 'electric_piano_1', 'electric_piano_2', 'harpsichord', 'clavinet',
  'celesta', 'glockenspiel', 'music_box', 'vibraphone', 'marimba', 'xylophone', 'tubular_bells', 'dulcimer',
  'drawbar_organ', 'percussive_organ', 'rock_organ', 'church_organ', 'reed_organ', 'accordion', 'harmonica', 'tango_accordion',
  'acoustic_guitar_nylon', 'acoustic_guitar_steel', 'electric_guitar_jazz', 'electric_guitar_clean', 'electric_guitar_muted', 'overdriven_guitar', 'distortion_guitar', 'guitar_harmonics',
  'acoustic_bass', 'electric_bass_finger', 'electric_bass_pick', 'fretless_bass', 'slap_bass_1', 'slap_bass_2', 'synth_bass_1', 'synth_bass_2',
  'violin', 'viola', 'cello', 'contrabass', 'tremolo_strings', 'pizzicato_strings', 'orchestral_harp', 'timpani',
  'string_ensemble_1', 'string_ensemble_2', 'synth_strings_1', 'synth_strings_2', 'choir_aahs', 'voice_oohs', 'synth_choir', 'orchestra_hit',
  'trumpet', 'trombone', 'tuba', 'muted_trumpet', 'french_horn', 'brass_section', 'synth_brass_1', 'synth_brass_2',
  'soprano_sax', 'alto_sax', 'tenor_sax', 'baritone_sax', 'oboe', 'english_horn', 'bassoon', 'clarinet',
  'piccolo', 'flute', 'recorder', 'pan_flute', 'blown_bottle', 'shakuhachi', 'whistle', 'ocarina',
  'lead_1_square', 'lead_2_sawtooth', 'lead_3_calliope', 'lead_4_chiff', 'lead_5_charang', 'lead_6_voice', 'lead_7_fifths', 'lead_8_bass__lead',
  'pad_1_new_age', 'pad_2_warm', 'pad_3_polysynth', 'pad_4_choir', 'pad_5_bowed', 'pad_6_metallic', 'pad_7_halo', 'pad_8_sweep',
  'fx_1_rain', 'fx_2_soundtrack', 'fx_3_crystal', 'fx_4_atmosphere', 'fx_5_brightness', 'fx_6_goblins', 'fx_7_echoes', 'fx_8_scifi',
  'sitar', 'banjo', 'shamisen', 'koto', 'kalimba', 'bagpipe', 'fiddle', 'shanai',
  'tinkle_bell', 'agogo', 'steel_drums', 'woodblock', 'taiko_drum', 'melodic_tom', 'synth_drum', 'reverse_cymbal',
  'guitar_fret_noise', 'breath_noise', 'seashore', 'bird_tweet', 'telephone_ring', 'helicopter', 'applause', 'gunshot',
]

// FL Studio에서 내보낸 파일은 악기 번호가 전부 0인 경우가 많아서, 0이면 트랙 이름으로 악기를 고른다.
const NAME_HINTS: [RegExp, number][] = [
  [/808/, 38], // 808 베이스 → synth_bass_1
  [/sub|bass|베이스/, 33],
  [/rhodes|e\.?\s?piano|\bep\b|wurli|keys|건반/, 4],
  [/organ|오르간/, 16],
  [/pluck|guitar|gtr|기타/, 27],
  [/string|violin|cello|현악/, 48],
  [/choir|vox|voice|코러스/, 52],
  [/brass|horn|trumpet/, 61],
  [/flute|플룻/, 73],
  [/bell|glock|chime/, 9],
  [/pad|패드|atmo/, 89],
  [/lead|synth|리드/, 81],
]

export function gmProgramOf(track: Track): number {
  if (track.program !== 0 || track.program_set) return track.program
  const name = track.name.toLowerCase()
  return NAME_HINTS.find(([re]) => re.test(name))?.[1] ?? 0
}

// ---------- 드럼 ----------

// 피아노롤 드럼 레인에 보여 줄 이름 (General MIDI 기준)
export const DRUM_NAMES: Record<number, string> = {
  35: 'Kick 2', 36: 'Kick', 37: 'Side Stick', 38: 'Snare', 39: 'Clap', 40: 'Snare 2',
  41: 'Floor Tom 2', 42: 'Closed Hat', 43: 'Floor Tom', 44: 'Pedal Hat', 45: 'Low Tom',
  46: 'Open Hat', 47: 'Low-Mid Tom', 48: 'Hi-Mid Tom', 49: 'Crash', 50: 'High Tom',
  51: 'Ride', 52: 'China', 53: 'Ride Bell', 54: 'Tambourine', 55: 'Splash', 56: 'Cowbell',
  57: 'Crash 2', 59: 'Ride 2',
}

// [샘플 파일, 재생 속도, 크기(기본 1)]
export type DrumSample = [file: string, rate: number, gain?: number]

export type DrumRole = 'kick' | 'snare' | 'clap' | 'hat' | 'openhat' | 'tom' | 'crash' | 'ride'

// GM 드럼 번호 → 역할 (백엔드 app/tools/drums.py ROLES와 같음). 같은 역할끼리만 소리를 바꿀 수 있다
export const DRUM_ROLES: Record<number, DrumRole> = {
  35: 'kick', 36: 'kick', 37: 'snare', 38: 'snare', 40: 'snare', 39: 'clap',
  42: 'hat', 44: 'hat', 46: 'openhat',
  41: 'tom', 43: 'tom', 45: 'tom', 47: 'tom', 48: 'tom', 50: 'tom',
  49: 'crash', 52: 'crash', 55: 'crash', 57: 'crash', 51: 'ride', 53: 'ride', 59: 'ride',
}

const TOMS = [41, 43, 45, 47, 48, 50] // 낮은 탐 → 높은 탐
// 탐 소리는 탐 6개(TOMS 순서)에 각각 샘플 · 속도를 둬서 높낮이를 나눈다
const toms = (file: string, rates: number[], gain = 1): DrumSample[] => rates.map((r) => [file, r, gain])

/**
 * 드럼 소리 목록 (백엔드 app/tools/drums.py DRUM_SOUNDS와 같은 id · 이름, 테스트가 확인).
 * 샘플은 모두 Sonic Pi CC0. 고른 기준: 길이 · 밝기(스펙트럼 중심) · 저역 비율을 재서 비교 (docs/devlog.md v0.1-16 · 19).
 */
export const DRUM_SOUNDS: Record<string, { name: string; role: DrumRole; sample: DrumSample | DrumSample[] }> = {
  kick_acoustic: { name: '어쿠스틱 킥', role: 'kick', sample: ['drum_heavy_kick', 1] },
  kick_soft: { name: '부드러운 킥', role: 'kick', sample: ['drum_bass_soft', 1] },
  kick_punch: { name: '펀치 킥', role: 'kick', sample: ['bd_klub', 1, 0.7] },
  kick_808: { name: '808 킥', role: 'kick', sample: ['bd_808', 1] },
  kick_house: { name: '하우스 킥', role: 'kick', sample: ['bd_haus', 1, 0.7] },
  kick_lofi: { name: '둥근 로파이 킥', role: 'kick', sample: ['bd_gas', 1] },
  kick_boombap: { name: '붐뱁 킥', role: 'kick', sample: ['bd_fat', 1, 1.6] },
  kick_electro: { name: '일렉 킥', role: 'kick', sample: ['elec_soft_kick', 1, 0.7] },
  snare_acoustic: { name: '어쿠스틱 스네어', role: 'snare', sample: ['drum_snare_hard', 1] },
  snare_soft: { name: '부드러운 스네어', role: 'snare', sample: ['drum_snare_soft', 1] },
  snare_big: { name: '큰 스네어', role: 'snare', sample: ['sn_dolf', 1, 0.7] },
  snare_lofi: { name: '먹먹한 스네어', role: 'snare', sample: ['sn_dub', 0.95, 0.7] },
  snare_909: { name: '909 스네어', role: 'snare', sample: ['sn_generic', 1, 0.8] },
  snare_boombap: { name: '붐뱁 스네어', role: 'snare', sample: ['sn_zome', 1, 0.75] },
  snare_electro: { name: '일렉 스네어', role: 'snare', sample: ['elec_snare', 1] },
  snare_808: { name: '808 스네어', role: 'snare', sample: ['elec_hi_snare', 1] },
  clap: { name: '클랩', role: 'clap', sample: ['perc_snap', 1] },
  clap_909: { name: '909 클랩', role: 'clap', sample: ['perc_snap2', 1, 0.7] },
  hat_acoustic: { name: '어쿠스틱 하이햇', role: 'hat', sample: ['drum_cymbal_closed', 1] },
  hat_808: { name: '808 하이햇', role: 'hat', sample: ['hat_bdu', 1] },
  hat_909: { name: '909 하이햇', role: 'hat', sample: ['hat_raw', 1] },
  hat_soft: { name: '작고 부드러운 하이햇', role: 'hat', sample: ['hat_tap', 1, 2.5] },
  hat_crisp: { name: '또렷한 하이햇', role: 'hat', sample: ['hat_zild', 1] },
  hat_electro: { name: '일렉 하이햇', role: 'hat', sample: ['hat_sci', 1] },
  openhat_acoustic: { name: '어쿠스틱 오픈햇', role: 'openhat', sample: ['drum_cymbal_open', 1] },
  openhat_808: { name: '808 오픈햇', role: 'openhat', sample: ['hat_len', 1] },
  openhat_909: { name: '909 오픈햇', role: 'openhat', sample: ['hat_gump', 1, 0.8] },
  openhat_soft: { name: '부드러운 오픈햇', role: 'openhat', sample: ['hat_cats', 1, 1.5] },
  openhat_electro: { name: '일렉 오픈햇', role: 'openhat', sample: ['hat_noiz', 1] },
  tom_acoustic: {
    name: '어쿠스틱 탐', role: 'tom',
    sample: [['drum_tom_lo_hard', 0.9], ['drum_tom_lo_hard', 1], ['drum_tom_mid_hard', 0.95], ['drum_tom_mid_hard', 1.05], ['drum_tom_hi_hard', 0.95], ['drum_tom_hi_hard', 1.05]],
  },
  tom_deep: {
    name: '낮고 큰 탐', role: 'tom',
    sample: [['drum_tom_lo_hard', 0.82], ['drum_tom_lo_hard', 0.9], ['drum_tom_mid_hard', 0.82], ['drum_tom_mid_hard', 0.9], ['drum_tom_hi_hard', 0.82], ['drum_tom_hi_hard', 0.9]],
  },
  // 둥글고 낮은 킥(bd_gas)을 높여서 쓰는 부드러운 탐
  tom_round: { name: '둥근 로파이 탐', role: 'tom', sample: toms('bd_gas', [1.5, 1.7, 1.9, 2.15, 2.4, 2.7]) },
  tom_808: { name: '808 탐', role: 'tom', sample: toms('bd_pure', [1.6, 1.9, 2.2, 2.5, 2.8, 3.1]) },
  tom_electro: { name: '일렉 탐', role: 'tom', sample: toms('elec_fuzz_tom', [0.75, 0.85, 0.95, 1.05, 1.15, 1.25], 0.8) },
  crash_acoustic: { name: '어쿠스틱 크래시', role: 'crash', sample: ['drum_cymbal_hard', 1] },
  crash_splash: { name: '스플래시', role: 'crash', sample: ['drum_splash_hard', 1] },
  crash_electro: { name: '일렉 심벌', role: 'crash', sample: ['elec_cymbal', 1] },
  ride_acoustic: { name: '어쿠스틱 라이드', role: 'ride', sample: ['drum_cymbal_soft', 1] },
  ride_jazz: { name: '재즈 라이드', role: 'ride', sample: ['ride_via', 1, 1.5] },
  ride_bright: { name: '밝은 라이드', role: 'ride', sample: ['ride_tri', 1, 1.3] },
}

/** 고를 수 있는 드럼 킷 (GM 드럼 킷 번호, 백엔드 app/tools/instrument.py DRUM_KITS와 같은 목록).
 *  8 · 32는 GM2 표준 번호, 26~28은 이 앱 전용 (DAW에서는 각 DAW 드럼 소리로 열림) */
export const DRUM_KITS: { program: number; name: string }[] = [
  { program: 0, name: '스탠다드' },
  { program: 8, name: '룸' },
  { program: 16, name: '파워' },
  { program: 24, name: '일렉트로닉' },
  { program: 25, name: 'TR-808' },
  { program: 26, name: '하우스 (909)' },
  { program: 27, name: '로파이' },
  { program: 28, name: '붐뱁' },
  { program: 32, name: '재즈' },
]

export const kitName = (program: number) => DRUM_KITS.find((k) => k.program === program)?.name ?? '스탠다드'
export const kitOf = (program: number) => (DRUM_KITS.some((k) => k.program === program) ? program : 0)

// 킷 = 역할마다 어떤 소리를 쓸지. 모든 킷이 8가지 역할을 다 채운다
type Kit = Record<DrumRole, string>
const STANDARD: Kit = {
  kick: 'kick_acoustic', snare: 'snare_acoustic', clap: 'clap', hat: 'hat_acoustic', openhat: 'openhat_acoustic',
  tom: 'tom_acoustic', crash: 'crash_acoustic', ride: 'ride_acoustic',
}
const KITS: Record<number, Kit> = {
  0: STANDARD,
  8: STANDARD, // 룸: 같은 소리 + 방 울림 (KIT_FX)
  16: { ...STANDARD, kick: 'kick_punch', snare: 'snare_big', tom: 'tom_deep' },
  24: {
    kick: 'kick_electro', snare: 'snare_electro', clap: 'clap_909', hat: 'hat_electro', openhat: 'openhat_electro',
    tom: 'tom_electro', crash: 'crash_electro', ride: 'ride_bright',
  },
  25: {
    kick: 'kick_808', snare: 'snare_808', clap: 'clap', hat: 'hat_808', openhat: 'openhat_808',
    tom: 'tom_808', crash: 'crash_electro', ride: 'ride_bright',
  },
  26: {
    kick: 'kick_house', snare: 'snare_909', clap: 'clap_909', hat: 'hat_909', openhat: 'openhat_909',
    tom: 'tom_808', crash: 'crash_electro', ride: 'ride_bright',
  },
  27: {
    kick: 'kick_lofi', snare: 'snare_lofi', clap: 'clap', hat: 'hat_soft', openhat: 'openhat_soft',
    tom: 'tom_round', crash: 'crash_splash', ride: 'ride_jazz',
  },
  28: { ...STANDARD, kick: 'kick_boombap', snare: 'snare_boombap', hat: 'hat_crisp', tom: 'tom_deep' },
  32: { ...STANDARD, kick: 'kick_soft', snare: 'snare_soft', crash: 'crash_splash', ride: 'ride_jazz' },
}

/** 레인(음 번호)에서 지금 나는 소리 id: 따로 고른 소리, 없으면 킷 소리 */
export function drumSoundOf(program: number, pitch: number, picked: Record<string, string> = {}): string | null {
  const role = DRUM_ROLES[pitch]
  if (!role) return null
  return picked[pitch] ?? KITS[kitOf(program)][role]
}

// 같은 역할 안에서 번호마다 살짝 다르게 (Kick 2는 조금 낮게, 사이드 스틱은 작고 높게 …)
const PITCH_TWEAK: Record<number, [rate: number, gain: number]> = {
  35: [0.95, 1], 37: [1.1, 0.6], 40: [1.05, 1], 44: [0.9, 0.9], 52: [0.9, 1], 55: [1.15, 0.8], 57: [1.05, 1], 53: [1.2, 1], 59: [0.95, 1],
}
export const DRUM_DEFAULT: DrumSample = ['drum_cymbal_closed', 1] // 역할이 없는 번호 (탬버린 · 카우벨 등)

export function drumSample(program: number, pitch: number, picked: Record<string, string>): DrumSample {
  const id = drumSoundOf(program, pitch, picked)
  const sound = id ? DRUM_SOUNDS[id] : undefined
  if (!sound) return DRUM_DEFAULT
  if (sound.role === 'tom') {
    const set = sound.sample as DrumSample[]
    return set[Math.max(0, TOMS.indexOf(pitch))]
  }
  const [file, rate, gain = 1] = sound.sample as DrumSample
  const [r, g] = PITCH_TWEAK[pitch] ?? [1, 1]
  return [file, rate * r, gain * g]
}
