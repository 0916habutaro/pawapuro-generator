\# AGENTS.md



\## Project



This is a Streamlit + SQLite app for generating fictional Pawapuro-style baseball players for pennant mode.



\## Language



\- Use Python.

\- UI text should be Japanese.

\- Comments may be Japanese or English, but user-facing text must be Japanese.



\## Commands



Install dependencies:



pip install -r requirements.txt



Run app:



streamlit run app.py



\## Development policy



\- Keep the app simple and local-first.

\- Do not require external APIs.

\- Do not require a web server other than Streamlit.

\- Use SQLite for saved generated players.

\- Use CSV or JSON files under data/ for master data.

\- Do not commit generated SQLite DB files.

\- Do not commit exported CSV or Excel files.

\- Prioritize working MVP over perfect balancing.

- 乱数を引きながら順番に回す集まりは、集合（set・frozenset）にしない。リスト・タプルか `sorted(...)` にする（集合の並びは文字列のハッシュで起動のたびに変わり、同じseedでも結果が変わる）。確認は `tests/test_hash_independence.py`。



\## Requirements



The user should only select:



\- 投手 / 野手

\- カテゴリ

\- 生成人数



The category options are:



\- 架空球団用

\- ドラフト候補用

\- 助っ人外国人用



All other player properties should be generated internally by weighted random logic.



Generated properties include:



\- 年齢

\- 国籍

\- 出身地

\- 名前

\- 利き腕

\- 投打

\- ポジション

\- 選手タイプ

\- 身長

\- 体重

\- 能力

\- 特殊能力

\- 変化球 for pitchers



\## Output



Display generated players in a Pawapuro-like ability card.



Also save generated players into SQLite and allow CSV export.



\## Verification

- 改修の完了報告には、`scripts/run_checks.py` の正式な結果（`--quick` なし）を使う。
- `--quick` の結果で合否を話さない（簡易版はすべての合否が「参考」で、規模が小さいため誤差が大きい）。
- 前回の正式な結果（data/config/check_snapshot.csv）より悪化した項目は不合格になる。意図した変更なら `--update-snapshot --reason "理由"` で更新し、PRの説明に「更新した項目と理由」を載せる。
- 検証の判定の種類・誤差・基準値・受け入れ記録の使い方は README.md の「検証スクリプト」を参照。
  意図して改修前の値を変えたときは `--update-baselines --reason "理由"` で `data/config/check_baselines.json` を更新する。

## Git



\- commit・push の前に現在のブランチを確認し、main には直接 push しない。

