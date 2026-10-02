# パワプロ風 架空選手生成

## 概要

パワプロ風 架空選手生成は、Python + Streamlit + SQLiteで動作する個人利用専用のローカル用ツールです。外部公開・配布を前提としません。パワプロのペナント向けに、実在選手ではなく架空選手をランダム生成することを目的としています。

主な設計方針は次のとおりです。

- 投手・野手を選択して生成できます。
- カテゴリは「架空球団用」「ドラフト候補用」「助っ人外国人用」から選択できます。
- ユーザーが細かな能力値を指定せず、年齢・国籍・名前・能力・特殊能力などを内部ロジックで自動生成します。
- 生成結果をローカルSQLiteへ保存できます。
- 保存済み選手の履歴とバランスを確認できます。
- 画面からCSV・Excelへ出力できます。
- 基本機能はインターネット接続なしで利用できます。

このツールは実在選手を完全再現するものではありません。ペナント用の架空選手データを手軽に作るためのローカルアプリです。

## 主な機能

- 投手・野手の架空選手生成
- 3カテゴリ別の生成
- 国籍・地域別の名前生成
- パワプロ風の能力カード表示
- 数値能力とA〜Gランク表示
- 投手の球速、コントロール、スタミナ、変化球、第二球種、ストレート系第二種
- 野手の弾道、ミート、パワー、走力、肩力、守備力、捕球、サブポジション
- 特殊能力とランク系特殊能力
- 1球団分（支配下ロスター）をまとめて作る「球団生成」
- SQLiteへの保存
- 過去生成選手の履歴表示
- バランス確認画面での集計
- CSV・Excel出力
- 検証スクリプトによる生成結果レビュー

## 動作環境

- 主対象OS: Windows 10 / 11
- Python: 3.11で動作確認済み
  - このリポジトリの最終確認はPython 3.11.8で実施しています。
  - 未確認のPythonバージョンでの動作は断定しません。
- 必要な空き容量: 最低200MB程度
  - 大量生成、SQLite履歴、検証レポートを多く残す場合は1GB以上の余裕を推奨します。
- ブラウザ: Microsoft Edge、Google Chromeなどの一般的なモダンブラウザ
- SQLite: Python標準ライブラリの`sqlite3`を利用します。別途SQLiteをインストールする必要はありません。
- Microsoft Excel: Excelファイルを閲覧する場合のみ必要です。出力自体はPythonパッケージ`openpyxl`で行います。

## セットアップ

Windows PowerShellでの例です。

```powershell
git clone <repository>
cd pawapuro-generator

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

必ず仮想環境を有効化した状態で`pip install -r requirements.txt`を実行してください。

PowerShellの実行ポリシーで仮想環境を有効化できない場合は、現在のPowerShellプロセスだけ一時的に許可してから有効化します。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

## 起動方法

通常起動:

```powershell
streamlit run app.py
```

ポート指定例:

```powershell
streamlit run app.py --server.port 8501
```

起動後にブラウザが自動で開かない場合は、次のURLへアクセスしてください。

```text
http://localhost:8501
```

終了方法:

```text
ターミナルで Ctrl + C
```

## 基本的な使い方

1. サイドバーの「表示する画面」で「選手生成」を開きます。
2. 「投手 / 野手」で「投手」または「野手」を選びます。
3. 「カテゴリ」で「架空球団用」「ドラフト候補用」「助っ人外国人用」のいずれかを選びます。
4. 「生成人数」を指定します。
5. 「生成する」ボタンを押します。
6. 生成結果の能力カードを確認します。
7. 生成された選手はSQLiteへ自動保存されます。
8. 「過去生成選手」で履歴を確認します。
9. 必要に応じて「CSV出力」「Excel出力」を使います。
10. サイドバーの「表示する画面」で「バランス確認」を開き、保存済み選手の分布を確認します。

## 選手カテゴリ

### 架空球団用

- 実在12球団の能力分布を主な参考にした標準カテゴリです。
- 弱い選手から主力級まで幅広く生成します。
- 年齢・タイプ・ポジションに応じた能力差があります。

### ドラフト候補用

- 架空球団用より全体的に未完成な選手を生成します。
- 若手中心です。
- 特殊能力や完成度は控えめです。
- 低確率で即戦力・上位候補も生成されます。

### 助っ人外国人用

- 外国籍中心です。
- 能力や特殊能力が尖りやすいカテゴリです。
- 当たり選手だけでなく外れ選手も生成されます。
- 架空球団用より特殊能力数が多い傾向があります。

## 生成されるデータ

### 共通

- 名前
- 国籍
- 出身地域
- 年齢
- 投打
- 選手タイプ
- カテゴリ
- 身長
- 体重
- 特殊能力
- ランク系特殊能力

### 野手

- メインポジション
- サブポジション
- 弾道
- ミート
- パワー
- 走力
- 肩力
- 守備力
- 捕球

### 投手

- 球速
- コントロール
- スタミナ
- 投手適正
- 変化球
- 第二球種
- ストレート系第二種

## 球団生成

上部ナビゲーションの「球団生成」で、実在NPB球団に近い人数構成の1球団分（支配下ロスター、63〜70人）をまとめて作ります。ペナント開始時に1球団を作る用途向けです。

### 使い方

1. 左のサイドバーで、球団名（任意）と球団seed（任意）を入力します。
   - 球団名が空欄なら「架空球団{番号}」になります（番号は次に保存する球団のID）。
   - 球団seedが空欄ならランダムです。同じseedなら、構成・選手・名前・能力・背番号まで同じ球団になります。
2. 「球団を生成」を押します（1球団あたり数秒かかります）。
3. 概要・構成チェック表・投手一覧・野手一覧を確認します。表の行を選ぶと、その選手の能力カードが表の下に出ます。
4. 気に入ったら「この球団を保存」を押します。**生成しただけでは保存されません**。作り直した球団はDBに残りません。

### 人数構成は実在データが基準

`data/reference/real_team_composition_2022_2026.csv`（2022〜2026年版パワプロ、12球団×5年＝60チーム）から1チームを「構成テンプレート」として選び、少しだけ揺らしてから、その人数に合わせて選手を作ります。

- 投手数・野手数、ポジション別の野手数、先発・救援の人数、左投手数、外国人の投手数・野手数
- 年齢帯ごとの人数（2026年版の割合に合わせ、先に作った外国人の分を引いて国内選手を作る）
- 外国人は「助っ人外国人用」、国内の選手は「架空球団用」の生成処理をそのまま使い、条件（ポジション・役割・左右・年齢帯）に合う選手が出るまで作り直します（棄却サンプリング）。どうしても出ないときは、左右 → 年齢帯 → 役割・ポジションの順に条件をゆるめ、その人数を警告として表示します。

### 戦力レベルとチームカラーはランダム

- 戦力レベル（強豪・中位・弱小）と、球団ごとの戦力指数（同じ強豪でも強さに幅がある）。投手と野手で戦力指数を少しずらすため、「投手は強いが打線が弱い」球団もできます。
- チームカラー（特色なし・投手王国・強力打線・機動力・守備重視・若手育成・ベテラン重視）と効き具合。25%の球団は2つ目のカラー（サブカラー）を持ちます。
- どちらも国内の選手の「選手格」「型」「年齢」の出やすさを変えるだけで、能力の作り方そのものは個別の選手生成と同じです。外国人には効きません。
- 倍率の基準値・範囲・揺らぎ幅は `generator/team.py` の定数にまとめてあります。
- 戦力指数・効き具合・最終的な倍率は、画面の「球団の内部パラメータ」で確認できます。

### 背番号

球団生成でだけ、全員に背番号（0〜99と00）を付けます。`data/reference/real_uniform_numbers_2022_2026.csv` の番号ごとの使われ方（投手・捕手・内野手・外野手・外国人）と、球団内の査定の順位・年齢をもとに割り当てます。欠番（永久欠番など）も球団ごとに0〜6個決まり、その番号は誰も使いません。

- 外国人は、実在で外国人が使った番号（42・99・90番台など）に付きやすく、実在で外国人がいない番号（1・17・18・19番など）にはほとんど付きません。
- 若手ほど大きい番号（31〜69番）、ベテランほど小さい番号（0〜30番）に付きやすくなります（年齢に対して連続に変わる倍率）。
- 背番号は文字列で保存します（"0" と "00" は別の番号）。並びは 0 → 00 → 1 → … → 99。
- 個別の選手生成では背番号を付けません（カードには従来どおりの表示用の番号が出ます）。

### 保存と出力

- 「この球団を保存」で、`teams` テーブルに球団を1行、`players` テーブルに所属選手を `team_id` 付きで保存します（1つのトランザクション）。保存後はボタンが押せなくなり「保存済み（球団ID: n）」と表示されます。
- 保存した選手のカテゴリは「架空球団用」「助っ人外国人用」のままなので、「過去生成選手」やバランス確認にもそのまま出ます。
- 「CSVで保存」「Excelで保存」は保存前でも使えます。
  - CSV: 全選手を1ファイル（UTF-8 BOM）。
  - Excel: シート「概要」「投手」「野手」。
  - 列は「過去生成選手」の「全データを出力」と同じ構成に、`team_name`（球団名）を足したものです。`roster_index`（登録順）と `uniform_number`（背番号、文字列）も入ります。
  - ファイル名は `players_team_{球団名}_{日時}.csv`／`.xlsx` です。

## 選手履歴

「選手生成」画面の下部に「過去生成選手」が表示されます。ここにはSQLiteに保存済みの選手が一覧表示されます。

履歴には、生成日時、seed、投手/野手、カテゴリ、名前、年齢、国籍、地域、ポジション、選手タイプ、投打、身長、体重、能力、特殊能力、変化球、投手適正、サブポジションなどが含まれます。

## バランス確認

サイドバーの「表示する画面」で「バランス確認」を選ぶと、保存済み選手をSQLiteから読み込み、生成結果の偏りを確認できます。

確認できる主な内容:

- 投手/野手別人数
- カテゴリ別人数
- 投手/野手×カテゴリ別人数
- 年齢分布
- 野手能力平均
- 投手能力平均
- 特殊能力の出現回数
- ランク系特殊能力の分布
- 野手ポジション別人数
- 投手役割別人数
- 変化球バランス

保存済み選手がない場合は、空DBとして案内メッセージが表示されます。

## CSV・Excel出力

### UIから利用できる出力

「選手生成」画面の「過去生成選手」で、保存済み履歴を出力できます。

- 「CSV出力」
  - ファイル名: `pawapuro_players.csv`
  - 文字コード: UTF-8 with BOM（`utf-8-sig`）
  - Excelで日本語列名を文字化けしにくい形式です。
  - Excelで開く場合は、通常のダブルクリックまたはExcelの「データ」タブからCSVを読み込んでください。
- 「Excel出力」
  - ファイル名: `pawapuro_players.xlsx`
  - シート: `players`
  - 数式には依存しません。
  - 能力ランクはPython側で生成済みの値が出力されます。

「バランス確認」画面では、フィルター適用後の保存済み選手を「フィルター後CSV出力」で出力できます。

### 開発者向け検証機能の出力

検証スクリプトもCSVやExcelを出力できます。これらは開発者向け検証機能であり、UIボタンとは別です。詳細は「検証スクリプト」を参照してください。

## データベース

- DBファイル名: `players.sqlite3`
- 保存場所: リポジトリ直下（`app.py`と同じディレクトリ）
- 初回起動時に自動作成されます。
- アプリ更新時に不足列がある場合は自動追加されます。
- 球団生成で保存した球団は `teams` テーブルに入ります。所属選手は `players.team_id`（球団に属さない選手は0）、`roster_index`、`uniform_number`（背番号、文字列）を持ちます。
- 既存レコードを保持したままマイグレーションします。
- 生成履歴の本体なので、DBファイルを直接編集しないことを推奨します。
- `players.sqlite3`はgitignore対象であり、通常はGitへコミットしません。

## バックアップと復元

### バックアップ

個人利用では、公開作業よりDB保護を優先してください。最も簡単な方法は、アプリ停止中にDBファイルをコピーすることです。

```text
1. StreamlitをCtrl+Cで終了
2. 更新前・マスタ変更前は必ずplayers.sqlite3を別フォルダへコピー
3. 日付を付けて保存
4. DBファイルをGitへコミットしない
```

バックアップ名例:

```text
players_backup_2026-07-10.db
```

### 復元

```text
1. アプリを終了
2. 現在のplayers.sqlite3を別名で退避
3. バックアップDBをplayers.sqlite3という名前でリポジトリ直下へ戻す
4. アプリを起動
```

上書き前に必ず現在のDBを退避してください。DBは生成履歴そのものなので、削除すると同じ履歴は復元できません。`reports/`配下は再生成可能ですが、SQLite DBは生成履歴を含むため再生成できません。

## マスタデータ

存在する主なマスタファイルは次のとおりです。

- `data/names.json`: 国籍別の姓・名マスター
- `data/places.json`: 国籍別の地域マスター
- `data/special_abilities.csv`: 特殊能力マスター
- `data/config/ootp_name_config.json`: OOTP由来の外国人名・国籍・肌色生成設定

### OOTP外国人名データ

助っ人外国人の名前、実国籍、名前グループ、肌色は、変換済みSQLiteがある場合にOOTP形式データ由来の候補を使います。

- 変換済みDB: `data/imported/foreign_names.sqlite`
- 元XML配置先: `data/external/ootp/names.xml`, `data/external/ootp/world_default.xml`
- 変換スクリプト: `python scripts/import_ootp_name_data.py`

`foreign_names.sqlite`と元XMLはサイズが大きいためGit管理対象外です。配布時はGitHub Release Assetなどで`foreign_names.sqlite`を提供し、利用者はダウンロードしたファイルを`data/imported/foreign_names.sqlite`へ配置してください。DBがない、壊れている、旧スキーマ、または対象候補が不足している場合でも、アプリは既存の`data/names.json`による外国人名生成へフォールバックします。

注意事項:

- CSV/JSONはUTF-8で保存してください。
- 列名やキー名を変更するとアプリが動かなくなる可能性があります。
- 編集前に必ずバックアップを取ってください。
- 重複・空欄に注意してください。
- `De La Cruz`などの複合姓を分割しないでください。
- 単独の`De`、`La`を姓として登録しないでください。
- このリポジトリには変化球専用マスタファイルはありません。変化球定義は現行コード内のロジックで扱っています。

## 検証スクリプト

レポート出力先の`reports/`配下はgitignore対象です。5000件規模の実行は時間と容量を使います。

### `scripts/validate_team_mode.py`

球団生成モードの検証です。固定seedで球団を作り、実在データと比べて `reports/team_mode/` にレポート（`summary.md` と各CSV、散布図のHTML）を出します。

```powershell
python scripts/validate_team_mode.py
```

- 既定では、構成・背番号の確認に200球団、戦力レベルの確認に600球団、チームカラーの確認にカラーごと200球団（効き具合 t=1.0・サブカラーなしに固定）を作ります。並列で数分〜十数分かかります。
- `--teams`、`--strength-teams`、`--color-teams`、`--workers` で球団数と並列数を変えられます。`--skip-color`、`--skip-strength` で一部を省けます。
- 戦力レベルの比較には、2026年版実在12球団の選手データ（`reports/real_powerpro_players_12teams/`）を `generator/rating.py` で査定した値を使います。

### `scripts/validate_ability_balance.py`

生成選手の能力バランスをカテゴリ別・投手/野手別に確認します。

主な引数:

- `--count`: 投手/野手×カテゴリごとの生成人数
- `--seed`: 検証用の開始seed
- `--output-dir`: CSV出力先
- `--excel`: Excelも出力

実行例:

```bash
python scripts/validate_ability_balance.py --count 1000 --output-dir reports/ability_balance --excel
```

主な出力:

- `generated_players.csv`
- `overall_summary.csv`
- `fielder_ability_summary.csv`
- `pitcher_ability_summary.csv`
- `special_kind_stats.csv`
- `ranked_special_stats.csv`
- `ability_balance_report.xlsx`（`--excel`指定時）

### `scripts/compare_real_and_generated_balance.py`

実在データ取り込み結果と生成データ検証結果を比較します。

主な引数:

- `--real-dir`: 実在データ取り込み結果ディレクトリ
- `--generated-dir`: 生成データ検証結果ディレクトリ
- `--output-dir`: CSV/Markdown出力先
- `--excel`: Excelも出力

実行例:

```bash
python scripts/compare_real_and_generated_balance.py --generated-dir reports/ability_balance --output-dir reports/real_vs_generated_balance --excel
```

### `scripts/validate_identity_and_subpositions.py`

名前・国籍・地域・投打・サブポジションの整合性を確認します。

主な引数:

- `--count`: 投手/野手×カテゴリごとの生成人数
- `--seed`: 検証用seed
- `--output-dir`: CSV/Markdown出力先

実行例:

```bash
python scripts/validate_identity_and_subpositions.py --count 1000 --output-dir reports/identity_subpositions
```

### `scripts/validate_storage_and_ui_integration.py`

SQLite保存、履歴読込、CSV/Excel出力、旧DBマイグレーション、画面表示用データの統合経路を確認します。

主な引数:

- `--output-dir`: 検証レポート出力先

実行例:

```bash
python scripts/validate_storage_and_ui_integration.py --output-dir reports/storage_ui_integration_local
```

主な出力:

- `players_export.csv`
- `players_export.xlsx`
- `sqlite_schema_audit.csv`
- `roundtrip_mismatches.csv`
- `ability_rank_boundary_audit.csv`
- `storage_ui_integration_review.md`


## Version 1.0.0の完成確認

Version 1.0.0は外部公開版ではなく、個人利用上の完成版です。ローカルWindowsでは次の範囲を確認できれば完成扱いです。

```powershell
git checkout main
git pull origin main

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m py_compile `
  app.py `
  scripts/validate_ability_balance.py `
  scripts/compare_real_and_generated_balance.py `
  scripts/validate_identity_and_subpositions.py `
  scripts/validate_storage_and_ui_integration.py

python scripts/validate_storage_and_ui_integration.py `
  --output-dir reports/storage_ui_integration_local

streamlit run app.py
```

確認事項:

- アプリが起動する
- 投手・野手を生成できる
- 3カテゴリを選択できる
- 保存できる
- 再起動後も履歴が残る
- バランス確認画面が開く
- Version 1.0.0が表示される
- DBバックアップを作成済みである

Gitタグは任意です。個人用の区切りとして残したい場合だけ、ローカルタグを作成してください。GitHubへのpushは不要です。

```powershell
git tag -a v1.0.0 -m "Personal stable version 1.0.0"
```

## トラブルシューティング

### `streamlit`が見つからない

- 仮想環境が有効か確認してください。
- 仮想環境内で次を実行してください。

```powershell
pip install -r requirements.txt
```

### モジュールが見つからない

- 作業ディレクトリがリポジトリ直下（`app.py`がある場所）か確認してください。
- 仮想環境が有効か確認してください。
- `pip install -r requirements.txt`を再実行してください。

### DBエラー

- アプリを停止してください。
- `players.sqlite3`をバックアップしてください。
- ファイル権限を確認してください。
- DBファイルやフォルダが読取専用になっていないか確認してください。

### Excel出力エラー

- `openpyxl`が入っているか確認してください。
- 出力先ファイルをExcelで開いたままにしていないか確認してください。
- 出力先フォルダの権限を確認してください。

### PowerShellで仮想環境を有効化できない

現在のPowerShellプロセスだけ実行ポリシーを一時変更します。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

### ポートが使用中

別ポートを指定して起動してください。

```powershell
streamlit run app.py --server.port 8510
```

## 既知の仕様

- 金特は実在比較データに合わせて生成対象外です。
- usageは別枠情報のため生成対象外です。
- 実在選手の完全再現を目的としません。
- 同一名前が低確率で重複する可能性があります。
- ランダム生成のため少数サンプルでは分布が偏ります。
- バランス評価は5000件規模で確認する想定です。
- 助っ人外国人用は特殊能力が多めです。
- ドラフト候補用は能力・特殊能力が低めです。
- レポート類は通常gitignore対象です。

## 開発者向け情報

### 能力ランク

数値能力は1〜99に丸めたうえで、次のA〜Gランクを表示します。

| ランク | 数値 |
| --- | --- |
| A | 80以上 |
| B | 70〜79 |
| C | 60〜69 |
| D | 50〜59 |
| E | 40〜49 |
| F | 30〜39 |
| G | 29以下 |

この境界値は`app.py`の`rank()`関数の現行仕様です。

### データ保護

- アプリ停止中にDBをコピーしてください。
- アプリ更新前に必ずDBをバックアップしてください。
- マスタ変更前にも必ずDBと対象ファイルをバックアップしてください。
- SQLite DBは生成履歴を含むため再生成できません。
- `reports/`フォルダは再生成可能です。
- `players.sqlite3`などのDBファイルをGitへコミットしないでください。
- Git操作でDBを削除しないよう注意してください。
- 不要なDB削除操作をしないでください。

### 開発時の基本チェック

```bash
python -m py_compile app.py scripts/validate_ability_balance.py scripts/compare_real_and_generated_balance.py scripts/validate_identity_and_subpositions.py scripts/validate_storage_and_ui_integration.py
git diff --check
```
