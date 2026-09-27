# Phase 1 implementation log

- Phase 0の表示総数ではなく、非ランク特殊能力数を直接targetに再集計。
- 個別chance、特殊能力マスタ、ランク生成、pro_years、基本能力・class・年齢・変化球生成は変更対象外。
- 18～22歳は若手素材型・非例外の主力/控えをsoft cap / bonus drawで抑制し、若手スターと高score例外は維持。
- 27～34歳は高scoreのスター/主力/ベテランを中心にtailを増加。35+は野手高classのcapだけを弱く緩和し、低classへは加算しない。
- 個数調整は局所RNGへ分離し、ランク・基本能力・氏名・フォーム・装備など後続生成への乱数波及を防止。
- 最終制約監査後の最低個数リフィルで、既存の稀なhard bounds短不足を解消。
- controlled before/afterは同じseed集合で比較。
