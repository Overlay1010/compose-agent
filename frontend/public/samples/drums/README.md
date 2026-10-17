# 드럼 샘플

[Sonic Pi](https://github.com/sonic-pi-net/sonic-pi/tree/dev/etc/samples)의 드럼 샘플 (원본: freesound.org).
라이선스: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) — 출처 표기 없이 자유롭게 쓰고 배포할 수 있다.

General MIDI 드럼 번호와의 대응은 `src/audio/instruments.ts`의 `DRUM_SAMPLES`(스탠다드 킷)와 `KIT_SAMPLES`(파워 · 일렉트로닉 · TR-808 킷)에 있다.

| 킷 | 쓰는 샘플 (스탠다드와 다른 것만) |
| --- | --- |
| 스탠다드 (0) | `drum_*`, `perc_snap` |
| 파워 (16) | `bd_klub`, `sn_dolf`, 탐은 `drum_tom_*`을 낮게 |
| 일렉트로닉 (24) | `elec_soft_kick`, `elec_hollow_kick`, `elec_snare`, `elec_hi_snare`, `elec_lo_snare`, `hat_sci`, `hat_noiz`, `elec_fuzz_tom`, `elec_cymbal` |
| TR-808 (25) | `bd_808`, `elec_hi_snare`, `hat_bdu`, `hat_len`, 탐은 `bd_pure`를 높여서 |

각 샘플의 원본 freesound 주소는 Sonic Pi [samples README](https://github.com/sonic-pi-net/sonic-pi/blob/dev/etc/samples/README.md)에 있다.
