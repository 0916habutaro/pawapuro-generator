# Phase 4 analysis log

- app.py、Phase 1個数ロジック、Phase 2個別profile、Phase 3 ranked profileは変更していない。
- Phase 0のpartial effect・個別pro_years CSVを比較基準として再利用した。
- Phase 0 CSVにない非ランクplayer-level件数と同年齢帯tenure差だけを補完した。
- 実在Excelはplayers、special_abilities、breaking_ballsの必要列だけを読み取り、非ランク件数と指定10特能に限定した。
- real player_class proxyは新設せず、Phase 0と同じく年齢・能力score・position/pitcher roleを統制した。
- 23～26、27～30、31～34歳内でpro_yearsを3群化し、年齢・能力・position調整後のlong-short差を算出した。
- 18～22と35+、rank、controlled generatedは主要判定から除外した。
- 対象実在選手: 投手402人、野手389人。
- 読取元: pawapuro_players_entry_route_2026.xlsx（読み取り専用）。
