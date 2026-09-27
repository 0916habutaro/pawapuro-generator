# 特殊能力×年齢・プロ年数 Phase 5

## Dataset

- real: 投手 402人、野手 389人、合計 791人
- generated: 投手 30,000人、野手 30,000人、合計 60,000人
- seeds: 202610060101, 202610060201, 202610060301

## Non-ranked

- Phase 1後の年齢別平均・高尾部との最大差はguard許容内。若手スター例外、27～34歳高尾部、35+低class非boostを維持した。
- 表示総数は非ランク＋比較可能A/B/C/E/F/Gで再計算し、Dは実在直接比較から除外した。

## Individual

- 投手 変化球中心: real 12.44% / generated 7.33% / diff -5.11pt
- 投手 逃げ球: real 21.89% / generated 19.49% / diff -2.40pt
- 投手 キレ○: real 14.68% / generated 22.36% / diff +7.68pt
- 野手 選球眼: real 18.25% / generated 8.36% / diff -9.90pt
- 野手 積極守備: real 15.17% / generated 10.63% / diff -4.54pt
- 野手 バント○: real 13.62% / generated 9.94% / diff -3.68pt
- 野手 満塁男: real 17.22% / generated 14.68% / diff -2.54pt
- 野手 三振: real 34.70% / generated 37.81% / diff +3.11pt

- Phase 2対象8件はPhase 1 before比の改善条件を維持。残差だけを理由とした再調整は行っていない。

## Ranked

- A～Gを生成側で集計し、実在比較はA/B/C、A/B/C合計、E/F/Gを中心に監査した。
- Phase 3の若手過多縮小と中堅不足縮小はguard範囲内。A weightの追加調整は行っていない。

## pro_years

- 牽制○ overall: real 13.93% / generated 10.10% / diff -3.83pt。
- 同年齢帯long-short差: 23～26 +2.42pt, 27～30 +2.58pt, 31～34 +0.92pt。Phase 4bの実在方向を維持した。
- cap、extra draws、rankへのpro_years接続はなく、牽制○限定の構造を維持した。

## Regression

- guard: 24/24 passed。
- constraints、seed完全再現、基本能力、変化球、非対象特殊能力、app.py fingerprintを監査した。

## Remaining gaps

- high 0件 / medium 7件 / low 0件。
- medium/lowは実在791人の標本差と過学習回避を考慮し、Phase 5では変更しない。

## Final decision

**A. 完成扱い可能**

重大gapとregressionはなく、特殊能力×年齢・プロ年数調整は完成扱い可能。
