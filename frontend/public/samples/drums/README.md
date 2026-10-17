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
| 룸 (8) | 스탠다드 샘플 + 방 울림 잔향 |
| 하우스 909 (26) | `bd_haus`, `sn_generic`, `perc_snap2`, `hat_raw`, `hat_gump` |
| 로파이 (27) | `bd_gas`, `sn_dub`, `hat_tap`, `hat_cats` + 고음을 깎는 필터 |
| 붐뱁 (28) | `bd_fat`, `sn_zome`, `hat_zild` |
| 재즈 (32) | `drum_bass_soft`, `drum_snare_soft`, `ride_via`, `ride_tri` + 가벼운 잔향 |

8 · 32는 GM2 표준 드럼 킷 번호, 26~28은 이 앱 전용 번호라 DAW에서 열면 각 DAW의 드럼 소리로 난다.

각 샘플의 원본 freesound 주소는 Sonic Pi [samples README](https://github.com/sonic-pi-net/sonic-pi/blob/dev/etc/samples/README.md)에 있다.
