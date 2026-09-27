# Phase 2 implementation log

- Phase 0の実在profileとPhase 1後の個別率CSVを再利用し、候補20件だけを差分分析。実在Excelは再走査していない。
- 個別base weight、Phase 1個数ロジック、ランク、pro_years、UI、SQLite schemaは変更していない。
- 年齢補正は決定論的なexperience_up / mild_experience_up / flatten_age_biasの3曲線だけを使用。
- Phase 2対象外の親RNGをPhase 1 baselineで消費し、後続生成fingerprintを保護。

## Mapping

- 投手 変化球中心: experience_up
- 投手 逃げ球: mild_experience_up
- 投手 キレ○: mild_experience_up
- 野手 選球眼: experience_up
- 野手 積極守備: experience_up
- 野手 バント○: experience_up
- 野手 満塁男: flatten_age_bias
- 野手 三振: flatten_age_bias
