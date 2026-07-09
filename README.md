# Pawapuro Player Generator

パワプロのペナントモード向けに、架空球団・ドラフト候補・助っ人外国人の架空選手を生成する Streamlit + SQLite アプリです。

## 技術構成

- Python
- Streamlit
- SQLite
- pandas

## セットアップと起動方法

```bash
pip install -r requirements.txt
streamlit run app.py
```

## MVP機能

- `app.py` から Streamlit アプリを起動できます。
- ユーザーが選ぶ項目は「投手/野手」「カテゴリ」「生成人数」のみです。
- カテゴリは「架空球団用」「ドラフト候補用」「助っ人外国人用」です。
- 年齢、国籍、出身地、名前、利き腕、投打、ポジション、選手タイプ、身長、体重、能力、特殊能力、投手の変化球を内部ロジックで自動生成します。
- カテゴリ別・ポジション別・年齢別・選手タイプ別の簡易的な重み付きランダムを使っています。
- 野手能力はミート、パワー、走力、肩力、守備力、捕球、弾道を生成します。
- 投手能力は球速、コントロール、スタミナ、変化球を生成します。
- 能力はA〜Gランクと数値で表示します。
- 特殊能力は同系統の衝突を避け、金特・強力な特殊能力は低確率、赤特は一定確率で付与します。
- 生成結果をパワプロ能力画面風カードで表示します。
- 生成結果はローカル SQLite（`players.sqlite3`）に保存します。
- 過去生成選手を一覧表示し、CSVで出力できます。
- 検証用に選手生成画面から最大1000人まで一括生成でき、生成中は進捗バーを表示します。
- 生成完了後はSQLiteへ保存した件数を画面に表示します。
- 「バランス確認」画面で、SQLiteに保存済みの選手をpandasで集計し、Streamlit上の表として確認できます。
- バランス確認では、カテゴリと投手/野手で保存済み選手を絞り込み、フィルター適用後のデータで集計・CSV出力できます。
- バランス確認では、確認チェックボックスをオンにした場合のみ保存済み選手を全削除できます。
- バランス確認では、投手/野手別人数、カテゴリ別人数、投手/野手×カテゴリ別人数、年齢分布を表示します。
- バランス確認では、野手能力・投手能力の平均値、特殊能力の出現回数、金特・青特・赤特の出現数を表示します。
- バランス確認では、野手のポジション別人数と投手の役割別人数を表示します。
- seedを保存しているため、同じseedで再生成できる構造になっています。
- `data/` 配下の JSON/CSV を名前、出身地、特殊能力のマスターとして読み込みます。

## データファイル

- `data/names.json`: 名前マスター
- `data/places.json`: 出身地マスター
- `data/special_abilities.csv`: 特殊能力マスター

## 注意

- `players.sqlite3` は生成データのためコミット対象外です。
- CSV出力ファイルもコミット対象外です。
- まずは動くMVPを優先しているため、能力バランスや特殊能力の網羅性は簡易版です。

## 実在パワプロ選手データ取り込み（ローカル用）

`python scripts/import_real_powerpro_players.py` で、ローカルに配置したパワプロ2026-2027実在選手データのHTML/ZIPを読み込み、架空選手生成の能力バランス調整に使うCSV集計を作成できます。

### データ配置方針

- 12球団分のZIP本体や実データ全体はGitHubに含めません。
- ユーザー自身が入手したZIP/HTMLを `data/raw/powerpro_2026_2027/` 配下へローカル配置してください。
- ZIPにはHTML本体と `_files` 配下のCSS（特に `ball.css`）が含まれる想定です。
- MHTML/単体HTMLも読み込み対象ですが、変化球classと球種名の対応はHTML+CSS一式を含むZIP/HTMLを優先してください。
- `data/raw/powerpro_2026_2027/*.zip` と `reports/real_powerpro_players/` は `.gitignore` で除外しています。

### 実行例

```bash
python scripts/import_real_powerpro_players.py \
  --input-dir data/raw/powerpro_2026_2027 \
  --output-dir reports/real_powerpro_players \
  --excel
```

### 出力ファイル

`--output-dir` 配下に以下を出力します。

- `players.csv`: 選手単位（球団名、選手名、背番号、投手/野手、投打、ポジション、能力など）
- `breaking_balls.csv`: 変化球単位（方向コード、球種、変化量、第1/第2球種など）
- `special_abilities.csv`: 特殊能力単位
- `position_summary.csv`: ポジション別summary
- `pitcher_role_summary.csv`: 投手役割別summary
- `breaking_ball_summary.csv`: 変化球分布summary
- `team_roster_summary.csv`: 球団別の選手数、投手数、野手数
- `team_pitcher_ability_average.csv`: 球団別の投手能力平均
- `team_fielder_ability_average.csv`: 球団別の野手能力平均
- `position_ability_average.csv`: 野手ポジション別の能力平均
- `pitcher_role_ability_average.csv`: 投手起用別の球速、コントロール、スタミナ、球種数、総変化量平均
- `breaking_ball_count_distribution.csv`: 投手ごとの変化球数分布
- `second_pitch_summary.csv`: 第二球種あり投手の人数と割合
- `total_movement_distribution.csv`: 総変化量分布
- `fielder_sub_position_summary.csv`: サブポジあり野手の人数と割合
- `special_kind_summary.csv`: 特殊能力カテゴリ別出現数
- `normal_special_summary.csv`: 通常特殊能力名別出現数
- `ranked_special_summary.csv`: ランク系特殊能力別出現数
- `real_powerpro_players.xlsx`: `--excel` 指定時のみ作成

### 変化球classの扱い

HTML内の `v52`, `v133`, `v543` のようなclassを解析します。

- `vXY`: `X` を方向コード、`Y` を変化量として扱います。
- `vXYZ`: `X` を方向コード、`Y/Z` を同方向の第1球種/第2球種の変化量として扱います。
- 球種名が左右列にあり、中央列に変化量classがある表にも対応できるよう、同一行、親要素、隣接要素相当の周辺テキスト、`alt`/`title` 属性とclassを合わせて抽出します。
- CSSに定義がないclassや球種名が取れない場合はログへ出し、取得失敗箇所は `unknown` としてCSVへ残します。

### テスト用fixtureの作り方

最小fixtureは `tests/fixtures/powerpro_sample/` に置きます。現時点では実データではなく、構造確認用のsynthetic HTML/CSSのみを含めます。今後、実HTML/CSSの最小断片を追加する場合も、実データ全体や12球団ZIP本体はコミットしないでください。

fixture作成時の目安:

1. 実HTMLから選手1〜2名分だけを最小化して `tests/fixtures/powerpro_sample/` 配下へ置く。
2. 変化球検証に必要な `ball.css` の該当classだけを `*_files/ball.css` へ置く。
3. 個人情報や大量の実データを含めず、パーサー仕様の確認に必要な最小行だけにする。
4. 以下のようにfixtureを入力にしてCSV出力を確認する。

```bash
python scripts/import_real_powerpro_players.py \
  --input-dir tests/fixtures/powerpro_sample \
  --output-dir /tmp/powerpro_sample_report \
  --excel
```

### 実ZIPでのスモークテスト

ローカルに1球団分のZIPを置いた状態で、以下のコマンドを実行して取り込み結果を確認します。実データZIPはGitHubに含めず、必要な人だけがローカルで配置してください。

```bash
python scripts/import_real_powerpro_players.py \
  --input-dir data/raw/powerpro_2026_2027 \
  --output-dir reports/real_powerpro_players_hanshin \
  --excel
```

実行後、コンソールのサマリーで以下を確認してください。

- 入力HTML数
- 選手数
- 投手数
- 野手数
- 変化球数
- 特殊能力数
- 未解釈class数
- unknown変化球数
- 取得失敗/要確認選手数
- 出力先

あわせて、出力先に以下の確認用CSV/Excelが作成されていることを確認してください。

- `players.csv`
- `breaking_balls.csv`
- `special_abilities.csv`
- `position_summary.csv`
- `pitcher_role_summary.csv`
- `breaking_ball_summary.csv`
- `team_roster_summary.csv`
- `team_pitcher_ability_average.csv`
- `team_fielder_ability_average.csv`
- `position_ability_average.csv`
- `pitcher_role_ability_average.csv`
- `breaking_ball_count_distribution.csv`
- `second_pitch_summary.csv`
- `total_movement_distribution.csv`
- `fielder_sub_position_summary.csv`
- `special_kind_summary.csv`
- `normal_special_summary.csv`
- `ranked_special_summary.csv`
- `unknown_classes.csv`: `ball.css` 等に定義が見つからなかった `v52` などのclass一覧
- `unknown_breaking_balls.csv`: classは読めたが球種名を特定できなかった変化球一覧
- `failed_players.csv`: ZIP/HTML読み込み失敗、必須項目不足など、取得失敗または要確認の選手・HTML一覧
- `real_powerpro_players.xlsx`: `--excel` 指定時のみ作成

実ZIPで失敗した場合は、`unknown_classes.csv` / `unknown_breaking_balls.csv` / `failed_players.csv` の `source`、`team`、`name`、`source_class`、`detail` を確認してください。`source` には `ZIP名:HTMLファイル名` の形式で入力元が記録されるため、どのHTMLファイル・どの選手・どのclassで失敗したかを追跡できます。
