# Version 1.0.0 リリースチェックリスト

確認日: 2026-07-10
対象バージョン: 1.0.0

## mainブランチ確認

- [x] `APP_VERSION = "1.0.0"` を確認
- [x] READMEにVersion 1.0.0相当の利用手順があることを確認
- [x] CHANGELOGに `[1.0.0] - 2026-07-10` があることを確認
- [x] `docs/release_checklist.md` があることを確認
- [ ] `git checkout main` / `git pull origin main` は、このCodex環境に`main`ブランチと`origin`リモートが存在しないため未確認
- [x] ワーキングツリー状態を確認

## requirements.txt確認

- [x] `requirements.txt` は次の3パッケージのみであることを確認
  - `streamlit`
  - `pandas`
  - `openpyxl`
- [x] Pythonファイルのimportを確認し、外部依存は上記3パッケージのみであることを確認
- [ ] 新規仮想環境からのPyPIインストールはCodex環境では未実施

ローカルWindows環境で次を1回確認してください。

```powershell
python -m venv .venv-release
.venv-release\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

## 構文確認

- [x] `python -m py_compile app.py scripts/validate_ability_balance.py scripts/compare_real_and_generated_balance.py scripts/validate_identity_and_subpositions.py scripts/validate_storage_and_ui_integration.py` 成功

## 統合監査

- [x] `python scripts/validate_storage_and_ui_integration.py --output-dir reports/storage_ui_integration_v1_0_0` 成功
- [x] SQLite初期化
- [x] 保存・再読込
- [x] JSON復元
- [x] 旧DBマイグレーション
- [x] CSV出力
- [x] Excel出力
- [x] 能力ランク境界
- [x] 空DB集計
- [x] カード表示
- [x] Streamlit import
- [x] 必須assert

## 生成系スモークテスト

各組み合わせ10人、合計60人の生成・保存・再読込を確認しました。

- [x] 投手 × 架空球団用
- [x] 投手 × ドラフト候補用
- [x] 投手 × 助っ人外国人用
- [x] 野手 × 架空球団用
- [x] 野手 × ドラフト候補用
- [x] 野手 × 助っ人外国人用
- [x] 名前空欄なし
- [x] 能力欠落なし
- [x] 特殊能力の読込成功
- [x] 変化球の読込成功
- [x] 投手適正の読込成功
- [x] サブポジの読込成功
- [x] DB保存成功
- [x] 再読込成功

## Streamlit最終起動

- [x] `streamlit run app.py --server.headless true --server.port 8510` 起動成功
- [x] ローカルURL表示を確認
- [x] DB初期化エラーなし
- [x] Version 1.0.0表示コードを確認
- [x] 選手生成画面コードを確認
- [x] 履歴画面コードを確認
- [x] バランス確認画面コードを確認
- [ ] ブラウザでの手動視覚確認は未実施

## READMEと実装の一致確認

- [x] DBファイル名と保存場所
- [x] 画面名
- [x] ボタン名
- [x] 投手／野手の選択方法
- [x] 3カテゴリ名
- [x] CSV・Excel機能がUI機能か検証機能か
- [x] 能力ランク境界
- [x] usageが生成対象外
- [x] 金特が生成対象外
- [x] バックアップ方法
- [x] 検証スクリプト名
- [x] 起動コマンド

## CHANGELOG確認

- [x] Version 1.0.0に実装済み内容のみが記載されていることを確認

## タグ作成準備

このCodex作業ではタグ作成・pushは実施していません。リリース承認後に次を実行してください。

```bash
git tag -a v1.0.0 -m "Version 1.0.0"
git push origin v1.0.0
```

## リリース判定

リリース判定: 条件付き承認

条件: ローカルWindowsの新規仮想環境で requirements.txt のインストールとStreamlit起動を1回確認すること。
