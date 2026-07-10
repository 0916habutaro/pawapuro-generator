# 実在12球団 vs 生成選手 バランス比較サマリー

## 重視カテゴリ
- 架空球団用を実在12球団との主比較対象として扱います。
- ドラフト候補用は低め、助っ人外国人用は尖りを許容して警告を解釈してください。

## 使用データ
- 実在データ: `reports/real_powerpro_players_12teams`
- 生成データ: `reports/ability_balance_5000_pitcher_after`

## 読み込み状況

### 実在側で読み込んだ任意ファイル
- `position_ability_average.csv`
- `team_fielder_ability_average.csv`
- `team_pitcher_ability_average.csv`
- `pitcher_role_ability_average.csv`
- `pitcher_role_summary.csv`
- `breaking_ball_count_distribution.csv`
- `total_movement_distribution.csv`
- `second_pitch_summary.csv`
- `fielder_sub_position_summary.csv`
- `special_kind_summary.csv`
- `normal_special_summary.csv`
- `ranked_special_summary.csv`
### 生成側で読み込んだ任意ファイル
- `position_balance_summary.csv`
- `position_balance_warnings.csv`
- `position_high_ability_rates.csv`
- `position_distribution_diagnostics.csv`
- `position_extreme_examples.csv`
- `warnings.csv`
- `pitcher_aptitude_summary.csv`
- `second_pitch_summary.csv`
- `breaking_pitch_summary.csv`
- `breaking_direction_summary.csv`
- `pitch_count_distribution.csv`
- `total_movement_distribution.csv`
- `sub_position_summary.csv`
### 読み込めなかった任意ファイル
- なし

## 架空球団用と実在12球団の主要差分

- 野手 ミート: 実在平均 42.483 / 生成平均 43.581 / 差分 1.098
- 野手 パワー: 実在平均 54.075 / 生成平均 54.845 / 差分 0.77
- 野手 走力: 実在平均 64.237 / 生成平均 64.109 / 差分 -0.128
- 野手 肩力: 実在平均 66.668 / 生成平均 66.285 / 差分 -0.383
- 野手 守備力: 実在平均 51.267 / 生成平均 53.085 / 差分 1.818
- 野手 捕球: 実在平均 47.853 / 生成平均 49.627 / 差分 1.774
- 野手 弾道: 実在平均 2.612 / 生成平均 2.596 / 差分 -0.016
- 投手 球速: 実在平均 152.117 / 生成平均 151.089 / 差分 -1.028
- 投手 コントロール: 実在平均 52.109 / 生成平均 51.513 / 差分 -0.596
- 投手 スタミナ: 実在平均 52.01 / 生成平均 52.533 / 差分 0.523
- 投手 球種数: 実在平均 2.821 / 生成平均 2.854 / 差分 0.033
- 投手 総変化量: 実在平均 6.818 / 生成平均 6.945 / 差分 0.127
- 投手 第二球種数: 実在平均 0.182 / 生成平均 0.217 / 差分 0.035

## 弾道分布の要約

- 一塁手: 弾道3以上 実在 93.1% / 架空 83.8%、弾道4 実在 27.59% / 架空 53.35%
- 三塁手: 弾道3以上 実在 87.5% / 架空 75.0%、弾道4 実在 32.5% / 架空 39.04%
- 外野手: 弾道3以上 実在 58.73% / 架空 53.41%、弾道4 実在 11.11% / 架空 24.41%
- 捕手: 弾道3以上 実在 44.58% / 架空 32.43%、弾道4 実在 3.61% / 架空 5.09%
- 二塁手: 弾道3以上 実在 41.86% / 架空 21.04%、弾道4 実在 2.33% / 架空 2.09%
- 遊撃手: 弾道3以上 実在 27.94% / 架空 22.65%、弾道4 実在 0.0% / 架空 2.77%

## ポジション別上位割合の要約

- 捕手 ミート60以上: 4.07%
- 一塁手 パワー70以上: 42.32% / 三塁手 パワー70以上: 29.63%
- 二塁手 走力70以上: 69.1% / 遊撃手 走力70以上: 54.46% / 外野手 走力70以上: 62.91%
- 二塁手 守備力70以上: 34.33% / 遊撃手 守備力70以上: 16.99%
- 三塁手 肩力70以上: 36.52% / 外野手 肩力70以上: 48.55%

## severity 別 warning 件数

- medium: 100件
- low: 16件
- high: 1件
- high警告タイプ: 捕手 走力
- high代表例: {'警告タイプ': '捕手 走力', 'severity': 'high', 'seed': nan, 'カテゴリ': nan, 'ポジション': '捕手', '年齢': nan, 'タイプ': nan, '能力': '走力', 'source_file': 'position_balance_warnings.csv', '平均': 41.547, '実在平均': 51.86, '差分': -10.313, '条件': '<43', '警告': '警告', '警告表示名': '捕手 走力'}

## 第二球種・変化球分布の要約

- 実在12球団  第二球種あり投手: 18.16%
- 生成 全体 第二球種あり: 19.83%
- 生成 先発適正 -: 19.77%
- 生成 先発適正 ○: 19.8%
- 生成 先発適正 ◎: 19.89%
- 生成 中継ぎ適正 -: 19.9%
- 生成 中継ぎ適正 ○: 19.89%
- 生成 中継ぎ適正 ◎: 19.78%

## サブポジ比較の要約

- 実在12球団  サブポジあり野手: 66.32%
- 生成 全体 サブポジ保有率: 58.39%
- 生成 サブポジ数分布 0個: 41.61%
- 生成 サブポジ数分布 1個: 32.75%
- 生成 サブポジ数分布 2個: 22.48%
- 生成 サブポジ数分布 3個以上: 3.17%
- 生成 メインポジション別保有率 一塁手: 64.38%
- 生成 メインポジション別保有率 三塁手: 82.43%
- 生成 メインポジション別保有率 二塁手: 84.96%
- 生成 メインポジション別保有率 外野手: 26.66%
- 生成 メインポジション別保有率 捕手: 41.78%
- 生成 メインポジション別保有率 遊撃手: 84.98%
- 左投げ野手の二三遊サブ警告あり: 生成 0人

## 警告

- 野手ポジション別の能力差が±8以上: 捕手 走力: -10.308
- 赤特出現率が実在より大幅に高い/低い: 実在=74.68% 生成=44.68%
- 緑特出現率が実在より大幅に高い/低い: 実在=83.67% 生成=47.10%

## 残課題
- 任意CSVが欠けている項目は従来の players / breaking_balls / special_abilities 由来の比較、またはスキップで後方互換運用しています。
- 実在側に生成側と同じ粒度の詳細診断がない項目は参考比較として扱ってください。

## 出力CSV

- `overall_compare.csv`
- `fielder_ability_compare.csv`
- `pitcher_ability_compare.csv`
- `position_compare.csv`
- `pitcher_role_compare.csv`
- `breaking_ball_compare.csv`
- `special_ability_category_compare.csv`
- `special_ability_name_compare.csv`
- `rank_ability_compare.csv`
- `percentile_compare.csv`
- `trajectory_distribution_compare.csv`
- `position_rate_compare.csv`
- `generated_warning_severity_summary.csv`
- `generated_high_warnings.csv`
- `sub_position_compare.csv`
- `pitcher_aptitude_compare.csv`
- `second_pitch_compare.csv`
- `pitch_count_distribution_compare.csv`
- `total_movement_distribution_compare.csv`
- `warnings.csv`
