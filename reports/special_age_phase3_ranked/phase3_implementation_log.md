# Phase 3 implementation log

- Phase 0 ranked CSVをbaselineとし、A/B/C 2+/3+だけ実在Excelのplayers・special_abilities必要列から補完した。全Excel再分析は行っていない。
- Phase 1個数ロジックとPhase 2個別profileは変更していない。
- 共通の滑らかな年齢curve、player_class、group関連能力だけでA/B/C weightを決定論的に再配分した。
- 若手はsoft suppression。スター級・高関連能力では抑制を弱め、hard banは設けていない。
- 27歳以降は一軍主力級・スター級・ベテラン型を中心にD→C、一部C→Bを許可し、A weightは増やしていない。
- 二軍級・若手素材型は年齢だけではboostしない。pro_yearsと新規random drawは追加していない。
- 捕手30歳以上の旧年齢補正はPhase 3有効時に共通profileへ統合し、二重適用を防いだ。
