# バランス確認画面 UI改修指示

バランス確認ページ（`/balance`）について、**画面構成・表示項目・見た目**を改修する。
生成ロジックと能力のバランス調整はすでに完了しているため、今回の対象は**表示と集計の見せ方だけ**とする。

## 0. 作業の進め方

1. 対象コードを読み、下記「現状の構成」と食い違いがあれば最初に報告する。
2. フェーズ1から順に実装する。各フェーズの終わりに次の2つを行い、結果を報告してから次のフェーズへ進む。
   - `pytest` を実行する（特に `tests/test_ui_layout_helpers.py` と `tests/test_balance_history_loading.py`）
   - `streamlit run app.py` で `/balance` を開き、エラーがないこと、表示が崩れていないことを確認する
3. 改修前後で同じ画面のスクリーンショットを撮り、`docs/screenshots/balance/before_*.png` と `after_*.png` に保存する。
4. `AGENTS.md` の方針に従う（画面の文言は日本語、外部APIは使わない、main に直接 push しない）。

### 触ってはいけないもの
- 生成ロジック：`apply_*_balance` 系、`generate_*`、`generator/` 配下
- DBスキーマ：`players` テーブル（変更が必要になったら先に方針を提示して確認を取る）
- 選手生成ページ（`generation_page`）の見た目。**共通CSSを変更するときは、選手生成ページに影響が出ないようにバランス確認ページにスコープを限定する**（§4-1）

---

## 1. 現状の構成（改修前の確認用）

| 対象 | 場所 |
|---|---|
| ページ本体 | `app.py` `render_balance_check(master)`（約8220行目〜）。集計と表示が1つの関数に直列で書かれている |
| ページ入口 | `balance_page()` → `render_app_title()` → `render_balance_check()` |
| ナビゲーション | `main()` の `st.navigation(pages, position="top")` |
| 集計ヘルパー | `ability_average_table` / `special_ability_summary` / `ranked_special_distribution` / `special_count_distribution` / `grouped_special_count_distribution` / `classification_distribution_table` / `consistency_table` / `inconsistency_count` / `restricted_left_throwing_positions` / `breaking_balance_tables` / `sub_position_summary_tables` |
| 画面共通CSS | `app_chrome_css()`（`UI_COLORS` をCSS変数 `--ui-*` として展開） |
| 能力カードCSS | `inject_powerpro_ui_css()`（今回は原則触らない） |
| テーマ | `.streamlit/config.toml` |

### 見た目の問題の原因
- **背景のグラデーションとぼかし円**：`app_chrome_css()` の `.stApp {background: radial-gradient(...), linear-gradient(150deg,#effdff … #1fa6d6)}`
- **フィルターのチップが赤い**：`config.toml` の `primaryColor = "#E5333F"`（`UI_COLORS["accent"]` と同じ値）。`UI_COLORS["primary"]` は `#0B2A5B` なので、コメント「UI_COLORSと同じ値にそろえる」とも食い違っている
- **見出しに強弱がない**：`st.header` / `st.subheader` をそのまま使っている。既存の `render_section_heading()`（`.pp-section-heading`）は、バランス確認ページでは使われていない

---

## 2. フェーズ1：ページ構成の再編

### 2-1. 関数の分割
`render_balance_check` を次のように分割する。集計ロジックは移動するだけで、中身は変えない。

```
render_balance_check(master)
 ├─ render_balance_filters(df_all) -> df          # 絞り込み・件数・CSV出力
 ├─ collect_balance_checks(df, master) -> dict    # 整合性チェックの件数をまとめて算出
 ├─ st.tabs([...])
 │   ├─ render_balance_overview_tab(df, checks)
 │   ├─ render_balance_consistency_tab(df, master, checks)
 │   ├─ render_balance_profile_tab(df)
 │   ├─ render_balance_classification_tab(df)
 │   ├─ render_balance_ability_tab(df)
 │   ├─ render_balance_special_tab(df, master)
 │   ├─ render_balance_breaking_tab(df)
 │   └─ render_balance_defense_tab(df)
 └─ render_balance_danger_zone()                  # 全削除
```

### 2-2. タブ構成
`st.tabs(["概要", "整合性チェック", "人物属性", "新分類", "基礎能力", "特殊能力", "変化球", "守備・サブポジ"])`

| タブ | 含める内容（既存項目の移動先） |
|---|---|
| 概要 | 整合性チェックの要約（§3-4）、総件数、投手/野手×カテゴリのクロス表、野手ポジション別人数、投手役割別人数 |
| 整合性チェック | 生成品質チェックのメトリクス、名前・国籍・出身地チェックのメトリクス、国籍×名前種別、国籍×出身地種別、右投手/左投手別の不正球種、左投げ野手のサブポジ違反 |
| 人物属性 | 国籍別人数、年齢分布、プロ経歴分布（現在の expander の中身）、成長タイプ分布 |
| 新分類 | 選手格、アーキタイプ、ポジションスタイル、完成度、獲得目的、弱点プロファイル |
| 基礎能力 | 野手能力 平均値、投手能力 平均値（§5で拡張） |
| 特殊能力 | 種別別出現数、出現回数、ランク系、特殊能力数分布、選手タイプ別の平均数 |
| 変化球 | 変化球バランス、通常変化球数、総変化量、方向別、球種別、ストレート系第二種 |
| 守備・サブポジ | `sub_position_summary_tables` の各表 |

### 2-3. フィルターと危険操作
- 「絞り込み」（カテゴリ、投手/野手）、件数表示、CSV出力はタブの上に置き、全タブ共通にする。
- 件数は `st.caption` ではなく `st.metric` を2つ並べる（「表示中」と「全保存件数」）。
- 「履歴管理」（全削除）は `st.expander("⚠️ 危険な操作", expanded=False)` の中に入れ、**タブの下、ページの最下部**に移す。確認チェックボックスで押せるようにする仕組みと、`delete_all_players()`、`st.session_state.pop("latest_players")`、`st.rerun()` の流れはそのまま維持する。

---

## 3. フェーズ2：重複項目の統合・削除

| 現状 | 対応 |
|---|---|
| 「投手/野手別人数」「カテゴリ別人数」の単独表 | 削除する（投手/野手×カテゴリのクロス表に合計行・列があるため） |
| 「利き腕診断」の表（`restricted_left_throwing_positions`） | 表は削除し、メトリクス「左投げの捕手/内野手」だけ残す。1件以上ある場合だけ、内訳の表を expander で表示する |
| 「ランク系特殊能力の分布」と「主要ランク系特殊能力分布」 | 1つの表にまとめる。行＝グループ、列＝A〜G のピボット表にし、主要グループ（`RANKED_SPECIAL_DISPLAY_GROUPS`）を上に並べる |
| 特殊能力数分布（投手/野手別、カテゴリ別、投手/野手×カテゴリ別）の3表 | ピボット表1つにまとめる。行＝投手/野手×カテゴリ、列＝特殊能力数、合計列付き。上部のフィルターで絞れるので、単独の表は不要 |
| 「緑特の出現数」「個性系特殊能力の出現数」メトリクス | 削除し、種別別出現数の表に「個性系」の行を追加する。定義（`PERSONALITY_SPECIALS`）は `help` かキャプションで示す |
| 種別別出現数の0件の行（金特、中間ランク、不明） | 0件なら非表示。ただし「不明」が1件以上なら、整合性チェックに警告として出す |
| 「1人あたり平均特殊能力数」「6個以上の選手数」メトリクス | 特殊能力タブの先頭にメトリクスとして並べる |

### 3-4. 整合性チェックの要約（新規）
`collect_balance_checks()` で次の件数をまとめ、概要タブの先頭に表示する。

- seed重複数、完全重複選手数、不適切な特殊能力件数、利き腕/投打の不一致件数、左投げの捕手/内野手、国籍×名前の不整合、国籍×出身地の不整合、不正球種件数、左投げ野手のサブポジ違反、特殊能力の種別「不明」件数
- 表示例：すべて0なら `st.success("整合性チェック：全10項目 問題なし")`、1件以上あれば `st.warning("整合性チェック：10項目中2項目で要確認")` と、該当する項目名を一覧で出す
- 整合性チェックタブの各メトリクスは、0件なら「✅ 0」、1件以上なら「⚠️ n」と表示し、判定基準を `help=` で説明する

---

## 4. フェーズ3：デザイン基盤（背景・色・フォント・見出し）

### 4-1. スタイルのスコープ
- `render_balance_check` の全体を `st.container(key="balance_page")` で囲む。
- バランス確認ページ専用のCSSは `balance_page_css()` として新しく作り、セレクタを `div[class*="st-key-balance_page"]` 配下に限定する。
- ページ全体の背景は `.stApp:has(div[class*="st-key-balance_page"])` で上書きし、**選手生成ページの背景は変えない**。
- 色はすべて `UI_COLORS` の `--ui-*` 変数を使う。新しい色が必要なら `UI_COLORS` にキーを追加する（CSS内に色を直接書かない）。

### 4-2. 背景
- バランス確認ページの背景は、ぼかし円（radial-gradient）なしの単色 `#F4F8FC`（config の `backgroundColor`）か、ごく薄い縦グラデーションにする。
- 表、グラフ、メトリクスは白いカード（`st.container(border=True)`）に載せ、背景と区別する。

### 4-3. カラー
- 役割ごとの色：メイン＝`--ui-primary`（紺 `#0B2A5B`）、アクセント＝`--ui-accent`（赤）、状態色として `ok`（緑）、`warn`（黄）、`error`（赤）を `UI_COLORS` に追加する。
- **赤は、エラーと選手生成ボタンにだけ使う。** バランス確認ページのフィルターチップ（`[data-baseweb="tag"]`）は紺かグレー系にする。
- `config.toml` の `primaryColor` を変更すると選手生成ページのウィジェットの色も変わる。そのため今回は**変更せず、CSSで上書き**する。config とコメントの食い違い（§1）は報告だけにする。
- グラフの色も同じパレットを使う。投手と野手は能力カードのタブ色に合わせる（投手 `#d7193f` 系、野手 `#0876c9` 系）。

### 4-4. フォント
- バランス確認ページの本文は `"M PLUS Rounded 1c","Hiragino Maru Gothic ProN","Yu Gothic UI","Meiryo",sans-serif` にする（能力カードと同じ書体）。ただし、表の中は可読性を優先し、丸ゴシックで読みにくければ `"Yu Gothic UI","Meiryo",sans-serif` のままでよい。どちらにしたかと、その理由を報告すること。
- 数値（メトリクス、表の数値列）は `font-variant-numeric: tabular-nums` で桁をそろえる。
- 表の文字サイズは本文14px前後に上げ、ヘッダーは13px・太字にしてコントラストを上げる。`st.dataframe` の中身は Glide Data Grid でCSSが効きにくいので、効かない場合は報告する。

### 4-5. 見出しの階層
| 階層 | 用途 | 実装 |
|---|---|---|
| ページタイトル | 「バランス確認」 | §4-6 |
| タブ | 8タブ | `st.tabs`。文字を大きくし、選択中のタブに紺の下線を付ける |
| セクション見出し | タブ内の各ブロック | 既存の `render_section_heading()`（`.pp-section-heading`）を使う |
| 小見出し | 2カラム内の表タイトル | 太字15px程度。`st.subheader` より小さくする |
| 注記 | 定義や件数 | `st.caption` |

`st.header` / `st.subheader` の直接使用は、この階層に置き換える。

### 4-6. 画面上部とナビゲーション
- 現状はタイトルカード（`.pp-title`）と「バランス確認」の見出しと説明文が縦に3段並んでいる。バランス確認ページでは、これを**1段**にまとめる（例：「⚾ パワプロ風 架空選手生成 ／ バランス確認」＋右側に説明文を小さく）。`render_app_title()` に引数を追加して対応してよいが、選手生成ページの表示は変えないこと。
- 上部ナビゲーション（`st.navigation(position="top")`）の文字が小さく、現在のページが分かりにくい。CSSで文字を大きくし、選択中のページに下線か背景色を付ける。影響は両ページに出るので、変更前後を両方確認すること。

### 4-7. レイアウト
- 本文の最大幅は、現状の `.block-container {max-width:1680px}` を使う。2カラムの表は `st.columns(2, gap="large")` にする。
- 2カラムで左右の長さが大きく違う箇所（変化球、サブポジ、新分類）は、長い表を1カラムで全幅表示するか、組み合わせを入れ替える。
- ブラウザ幅980px以下で2カラムが崩れないか確認する。

---

## 5. フェーズ4：表・グラフの表示改善

### 5-1. 共通の表ヘルパー
`render_balance_table(df, *, height="auto", column_config=None)` を作り、ページ内の `st.dataframe` をすべてこれ経由にする。

- `hide_index=True` を基本にする（クロス表は行名を列に戻してから渡す）。
- 高さは行数に合わせて表内スクロールをなくす：`height = (行数 + 1) * 35 + 3`。25行を超える表は上限を `25行分` にする。
- 数値の書式は `st.column_config.NumberColumn` で統一する。
  - 人数・件数：`format="%d"`
  - 比率：小数1桁＋`%`（`format="%.1f%%"`）。`classification_distribution_table` などの `round(…, 2)` はヘルパー側で丸め直し、元の関数は変えない
  - 平均値：小数1桁（特殊能力の平均数は小数2桁）
- 数値と文字列が混ざっている表（`breaking_balance_tables()["metrics"]` の「値」列で、`2.6` と `"12.5%"` が混在）は、表示用に「値」と「単位」に分けるか、メトリクス表示に変える。
- 違反一覧が空のときは、空の表ではなく `st.success("違反なし")` を表示する。

### 5-2. 列名を日本語にする
現状、英語の列名が残っている箇所：
- 投手/野手×カテゴリのクロス表：`role` → 投手/野手
- 成長タイプのクロス表：`category` → カテゴリ、`role` → 投手/野手、`age` → 年齢帯
- `sub_position_summary_tables` の `main_has_rate`：`position` → ポジション
- `left_violation`：`name` / `position` / `batting_throwing` / `sub_positions` → 名前 / ポジション / 投打 / サブポジ（`sub_positions` はリストのまま出さず、「二塁手○、遊撃手△」のような文字列にする）
- `consistency_table` の「整合性」列：True/False のチェックボックス → `✅ 一致` / `⚠️ 不一致`

### 5-3. 並び順を固定する
`pd.Categorical` か `reindex` で固定する。

| 項目 | 順序 |
|---|---|
| 成長タイプ | 超早熟 → 早熟 → 普通 → 晩成 → 超晩成（`GROWTH_TYPE_LABELS` の順）。単独の表とクロス表の列、両方に適用する |
| 野手ポジション | 捕手 → 一塁手 → 二塁手 → 三塁手 → 遊撃手 → 外野手（`SUB_POSITION_LABELS` の順） |
| 投手役割 | 先発 → 中継ぎ → 抑え |
| カテゴリ | `CATEGORIES` の順 |
| 年齢帯 | 若い順（`age_band` の区分順） |
| 選手格 | 格の高い順。コード内の定義（`PLAYER_CLASS_WEIGHTS` など）から順序を取り、無ければ報告する |
| サブポジ評価 | ◎ → ○ → △ |
| 特殊能力種別 | `SPECIAL_KIND_ORDER` |
| 国籍 | 人数の多い順（現状どおり） |

### 5-4. グラフ化
グラフには新しいライブラリを追加せず、Streamlit に同梱されている Altair（`st.altair_chart`）か `st.bar_chart` を使う。表は各グラフの下の `st.expander("表で見る")` に残す。

| 項目 | 表示方法 |
|---|---|
| 国籍別人数 | 横棒グラフ |
| 野手ポジション別人数、投手役割別人数 | 横棒グラフ（§5-3の順序） |
| 年齢分布 | 1歳刻みの縦棒グラフ（投手/野手で色分けか積み上げ） |
| 成長タイプ×カテゴリ／投手/野手／年齢帯 | ヒートマップ。pandas Styler の `background_gradient` で `st.dataframe` に表示してよい。各行に n（人数）列を追加する |
| 新分類（選手格、アーキタイプなど） | 項目ごとに横棒グラフ。カテゴリで色分けするか、カテゴリごとに分ける。カテゴリ列を毎行繰り返す表示はやめる |
| ランク系特殊能力 | グループ×ランクのヒートマップ。D（標準）のセルは薄い色にし、「D を除外」のトグルを付ける |
| 特殊能力数分布 | 縦棒グラフ |
| 総変化量分布、通常変化球数分布 | 縦棒グラフ |
| 方向別出現数、球種別出現数 | 横棒グラフ |
| サブポジ数分布、評価分布 | 横棒グラフ |

`ProgressColumn` を使う場合は、人数列の最大値を `max_value` にする。

---

## 6. フェーズ5：整合性チェックの修正（国籍×名前）

### 現象
「国籍×名前 不整合」が97件あり、日本以外の国籍の選手は全員「名前種別：不明」と判定されている。

### 原因（コードから推定。Claude Code側で確認すること）
- 外国人の名前は `generator.foreign_names.generate_foreign_profile()` で生成され、`name_group_id` / `name_group_name` が保存されている。
- 一方、チェック側の `name_matches_nationality()` / `classify_name_type()` は、`data/names.json`（`master.names`）の姓・名リストだけで判定している。
- そのため、新しい外国人名の生成方式に判定が追いついていない。

### 対応
- 判定を「`name_group_id > 0` の選手は、`generator/foreign_names.py` 側の名前グループと国籍の対応で判定する」ように修正する。既存の `names.json` による判定は、日本人と旧データ用に残す。
- `consistency_table` の「名前種別」は、外国人名なら `name_group_name` を表示する。
- **`generator/foreign_names.py` の生成処理は変更しない。** 判定に必要な対応表が外部から参照できない場合は、読み取り専用の関数を追加するだけにする。
- 修正後、現在のDBで不整合件数がどう変わるかを報告する。0にならない場合は、残った内訳（国籍、名前、名前グループ）を一覧で報告する。
- テストを追加する：外国人選手1人分のフィクスチャで、`name_matches_nationality` が True になること。

---

## 7. フェーズ6：項目の追加（表示のみ）

| 追加項目 | タブ | 内容 |
|---|---|---|
| 投打の分布 | 人物属性 | 右投右打、右投左打、右投両打、左投左打など。投手/野手別 |
| 右投手/左投手の比率 | 変化球 | 投手の投げ腕の比率 |
| 能力の分布 | 基礎能力 | 平均値だけでなく、中央値・最小・最大を追加する。能力ごとに箱ひげ図か、ランク（S〜G）別の人数を出す |
| カテゴリ別の能力平均 | 基礎能力 | 行＝能力、列＝カテゴリの表（ドラフト候補、架空球団、助っ人外国人の比較） |
| 役割別の球速分布 | 基礎能力 | 先発・中継ぎ・抑えごとの球速の分布 |
| 特殊能力数の細分化 | 特殊能力 | 「6個以上」を 6 / 7 / 8 / 9個以上 に分ける。`special_count_bucket` は他で使われている可能性があるので、表示用に別の関数を作る |

---

## 8. 完了条件

- `pytest` が全件通る
- `/balance` がタブ構成になり、概要タブの先頭に整合性チェックの要約が出ている
- 全削除操作がページ最下部の expander の中にある
- フィルターチップが赤ではない
- 背景のぼかし円がなく、表とグラフが白いカードに載っている
- 表の中でスクロールが発生していない（25行を超える表を除く）
- 英語の列名が残っていない
- 成長タイプ、ポジション、役割などの並び順が §5-3 のとおりになっている
- 国籍×名前 不整合の判定が外国人名に対応している
- **選手生成ページの見た目が変わっていない**（上部ナビゲーションの調整分を除く。前後のスクリーンショットで確認する）

## 9. 完了時の報告
- 変更したファイルと関数の一覧
- 削除・統合した項目と、それぞれの移動先
- フォントの選択とその理由（§4-4）
- 国籍×名前の判定修正の結果（修正前97件 → 修正後n件）
- CSSが効かなかった箇所と、その代替案
- 未対応の項目と、その理由
