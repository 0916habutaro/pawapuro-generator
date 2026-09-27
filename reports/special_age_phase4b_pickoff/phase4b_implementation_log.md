# Phase 4b implementation log

- 対象: 投手「牽制○」のみ。
- 実装: `adjust_special_chance`へ`pro_years`を末尾追加し、決定論的な線形補間倍率を最終段で適用。
- 乱数: 新規drawなし。既存の「牽制○」判定drawを再利用し、後段の個数補充・上限選別完了後に対象1件だけを調整。
- 保護: 上下限違反になる変更は行わず、他の特殊能力との入れ替えも行わない。親RNG再生はPhase 4b無効で維持。
- 標本: seeds=[202610050101, 202610050201]、投手=2,500/seed、野手guard=250/seed。
- 判定: Phase 5へ進む。
- 完了時回帰検証: `py_compile`成功、`pytest -q`は279 passed / 102 subtests passed。
- 実行例: `python scripts/analyze_special_age_phase4b.py --count-per-seed 2500 --seeds 202610050101 202610050201`
