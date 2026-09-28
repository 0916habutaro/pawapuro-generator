# 外国人生成基盤 Phase 1

## 実装内容

- `roster_origin` で国内経由と外国人補強を分離し、架空球団用と助っ人外国人用の `foreign_import` を共通contextに統合。
- route条件付き国籍、守備別年齢、守備別NPB在籍年数、再来日フラグを追加。
- SQLite migration、履歴読み込み、CSV/Excel対象列、プロフィール表示を追加。routeによる能力補正は未実装。

## テスト結果

- pytest: 403 tests / failures 0 / errors 0 / skipped 0
- seed regression: 4/4 PASS

## 実在targetとの主要比較

| 守備 | 人数 | 平均年齢target | 平均年齢generated | age×tenure target | age×tenure generated |
| --- | --- | --- | --- | --- | --- |
| 投手 | 5000 | 29.83 | 29.92 | -0.03 | 0.005 |
| 野手 | 5000 | 30.58 | 30.59 | 0.53 | 0.531 |

### route

| 守備 | 区分 | target_pct | generated_pct | diff_pp |
| --- | --- | --- | --- | --- |
| 投手 | cuba_domestic | 5.5 | 5.82 | 0.32 |
| 投手 | korea_pro | 3.9 | 4.0 | 0.1 |
| 投手 | latin_development | 4.7 | 4.54 | -0.16 |
| 投手 | north_america_amateur_direct | 2.4 | 2.64 | 0.24 |
| 投手 | north_america_pro | 79.5 | 79.16 | -0.34 |
| 投手 | other_foreign_pro | 0.8 | 0.86 | 0.06 |
| 投手 | taiwan_amateur_direct | 2.4 | 2.16 | -0.24 |
| 投手 | taiwan_pro | 0.8 | 0.82 | 0.02 |
| 野手 | cuba_domestic | 8.2 | 7.8 | -0.4 |
| 野手 | korea_pro | 1.2 | 1.28 | 0.08 |
| 野手 | latin_development | 3.5 | 3.64 | 0.14 |
| 野手 | north_america_amateur_direct | 0.0 | 0.34 | 0.34 |
| 野手 | north_america_pro | 82.4 | 82.24 | -0.16 |
| 野手 | other_foreign_pro | 3.5 | 3.34 | -0.16 |
| 野手 | taiwan_amateur_direct | 0.0 | 0.16 | 0.16 |
| 野手 | taiwan_pro | 1.2 | 1.2 | 0.0 |

### age

| 守備 | 区分 | target_pct | generated_pct | diff_pp |
| --- | --- | --- | --- | --- |
| 投手 | 19-24 | 1.6 | 1.84 | 0.24 |
| 投手 | 25-27 | 14.2 | 14.06 | -0.14 |
| 投手 | 28-30 | 46.5 | 46.96 | 0.46 |
| 投手 | 31-33 | 29.9 | 29.16 | -0.74 |
| 投手 | 34+ | 7.9 | 7.98 | 0.08 |
| 野手 | 19-24 | 4.7 | 5.16 | 0.46 |
| 野手 | 25-27 | 12.9 | 12.84 | -0.06 |
| 野手 | 28-30 | 31.8 | 31.04 | -0.76 |
| 野手 | 31-33 | 31.8 | 32.14 | 0.34 |
| 野手 | 34+ | 18.8 | 18.82 | 0.02 |

### tenure

| 守備 | 区分 | target_pct | generated_pct | diff_pp |
| --- | --- | --- | --- | --- |
| 投手 | 1年目 | 45.7 | 45.8 | 0.1 |
| 投手 | 2-3年目 | 35.4 | 35.28 | -0.12 |
| 投手 | 4年以上 | 18.9 | 18.92 | 0.02 |
| 野手 | 1年目 | 45.9 | 43.62 | -2.28 |
| 野手 | 2-3年目 | 27.1 | 28.52 | 1.42 |
| 野手 | 4年以上 | 27.1 | 27.86 | 0.76 |

### 投手: route×age / route×tenure

| foreign_route | 人数 | 平均年齢 | 平均NPB在籍 |
| --- | --- | --- | --- |
| cuba_domestic | 291 | 29.97 | 2.41 |
| korea_pro | 200 | 30.3 | 2.5 |
| latin_development | 227 | 29.63 | 2.17 |
| north_america_amateur_direct | 132 | 28.91 | 2.28 |
| north_america_pro | 3958 | 29.98 | 2.38 |
| other_foreign_pro | 43 | 30.07 | 2.35 |
| taiwan_amateur_direct | 108 | 28.43 | 1.92 |
| taiwan_pro | 41 | 30.27 | 2.46 |
### 野手: route×age / route×tenure

| foreign_route | 人数 | 平均年齢 | 平均NPB在籍 |
| --- | --- | --- | --- |
| cuba_domestic | 390 | 30.43 | 2.87 |
| korea_pro | 64 | 31.25 | 3.2 |
| latin_development | 182 | 30.07 | 2.57 |
| north_america_amateur_direct | 17 | 28.65 | 1.94 |
| north_america_pro | 4112 | 30.61 | 2.89 |
| other_foreign_pro | 167 | 30.95 | 3.26 |
| taiwan_amateur_direct | 8 | 29.5 | 1.5 |
| taiwan_pro | 60 | 31.1 | 3.23 |

## 残課題 / Phase 2

- route別の直接能力補正、特殊能力、球種、体格の再調整はPhase 2以降。
- 少標本routeと再来日率は低確率eventとして残し、精密調整は行っていない。
- route×age / route×tenureに実在のセルtargetがないため、Phase 1ではソフトな条件付けと生成値の記録に留めた。
