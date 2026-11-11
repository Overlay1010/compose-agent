// 고음질 소리 세트: 악기마다 따로 녹음한 샘플 (없는 악기는 FluidR3). scripts/hq_soundset.py가 만든 파일이라 손으로 고치지 않는다.
// 피아노 Salamander Grand Piano (Alexander Holm, CC BY 3.0) · 그 밖 tonejs-instruments (Nicholaus Brosowsky, CC BY 3.0)

export const SALAMANDER_URL = 'https://tonejs.github.io/audio/salamander/'
export const TONEJS_URL = 'https://cdn.jsdelivr.net/gh/nbrosowsky/tonejs-instruments@622c2f1c32c8cfce4158ddc3eb26e518ddef37e5/samples/'

/** 샘플 이름 → 녹음된 음 (MIDI 번호, 파일 이름은 샵 표기: Cs4.mp3) */
export const HQ_NOTES: Record<string, number[]> = {
  'bass-electric': [25, 28, 31, 34, 37, 40, 43, 46, 49, 52, 55, 58, 61, 64, 67, 70],
  'bassoon': [43, 45, 48, 55, 57, 60, 64, 67, 69, 72],
  'cello': [36, 38, 39, 40, 41, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 72],
  'clarinet': [50, 53, 58, 62, 65, 70, 74, 77, 82, 86, 90],
  'contrabass': [30, 31, 34, 36, 38, 40, 42, 44, 45, 49, 52, 56, 59],
  'flute': [60, 64, 69, 72, 76, 81, 84, 88, 93, 96],
  'french-horn': [33, 36, 39, 43, 50, 53, 57, 60, 74, 77],
  'guitar-acoustic': [38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74],
  'guitar-electric': [37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84],
  'guitar-nylon': [35, 38, 40, 42, 44, 45, 47, 49, 50, 52, 54, 55, 57, 59, 61, 63, 64, 66, 68, 69, 71, 73, 74, 76, 78, 80, 81, 82],
  'harmonium': [36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 60, 61, 62, 63, 64, 65, 67, 68, 69, 70, 72, 73, 74],
  'harp': [28, 31, 35, 38, 41, 45, 48, 52, 55, 59, 62, 65, 69, 72, 76, 79, 83, 86, 89, 93, 95, 98, 101],
  'organ': [24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84],
  'salamander': [21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84, 87, 90, 93, 96, 99, 102, 105, 108],
  'saxophone': [49, 50, 51, 52, 53, 54, 55, 56, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81],
  'trombone': [34, 37, 39, 41, 44, 46, 48, 50, 51, 53, 56, 58, 60, 61, 62, 63, 65],
  'trumpet': [53, 57, 60, 63, 65, 67, 70, 74, 77, 81, 84],
  'tuba': [29, 34, 39, 41, 46, 50, 53, 58, 62],
  'violin': [57, 60, 64, 67, 69, 72, 76, 79, 81, 84, 88, 91, 93, 96],
  'xylophone': [67, 72, 79, 84, 91, 96, 103, 108],
}

/** GM 악기 번호 → 샘플 이름과 FluidR3 크기에 맞출 dB */
export const HQ_PROGRAMS: Record<number, { source: string; db: number }> = {
  0: { source: 'salamander', db: -12 },
  1: { source: 'salamander', db: -12.5 },
  2: { source: 'salamander', db: -4.5 },
  13: { source: 'xylophone', db: -23.5 },
  19: { source: 'organ', db: -14 },
  20: { source: 'harmonium', db: -14 },
  24: { source: 'guitar-nylon', db: -14.5 },
  25: { source: 'guitar-acoustic', db: -16 },
  26: { source: 'guitar-electric', db: -10.5 },
  27: { source: 'guitar-electric', db: -13 },
  33: { source: 'bass-electric', db: -15 },
  34: { source: 'bass-electric', db: -15 },
  40: { source: 'violin', db: -15.5 },
  42: { source: 'cello', db: -19.5 },
  43: { source: 'contrabass', db: -17 },
  46: { source: 'harp', db: -22.5 },
  56: { source: 'trumpet', db: -18.5 },
  57: { source: 'trombone', db: -13.5 },
  58: { source: 'tuba', db: -15 },
  60: { source: 'french-horn', db: -17 },
  65: { source: 'saxophone', db: -16 },
  66: { source: 'saxophone', db: -17.5 },
  70: { source: 'bassoon', db: -16.5 },
  71: { source: 'clarinet', db: -16 },
  73: { source: 'flute', db: -16 },
}
