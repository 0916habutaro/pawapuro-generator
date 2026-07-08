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

