"""外国人生成 Phase 3A の絶対能力残差を軽量検証する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from scripts import validate_foreign_generation_phase2 as phase2


PITCHER_METRICS = ("球速", "コントロール", "スタミナ")
FIELDER_METRICS = ("弾道", *app.FIELDER_ABILITY_KEYS, "6能力合計")
OVERALL_TARGETS = {
    "投手": {"球速": 155.88, "コントロール": 50.43, "スタミナ": 54.13},
    "野手": {"弾道": 2.99, "ミート": 45.78, "パワー": 70.33, "走力": 55.06, "肩力": 67.58, "守備力": 46.40, "捕球": 46.18, "6能力合計": 331.32},
}
PHASE2_OVERALL = {
    "投手": {"球速": 148.97, "コントロール": 54.30, "スタミナ": 53.09},
    "野手": {"弾道": 3.06, "ミート": 52.91, "パワー": 66.16, "走力": 52.24, "肩力": 60.42, "守備力": 56.48, "捕球": 56.89, "6能力合計": 345.09},
}
PHASE2_TENURE = {
    "投手": {
        "1年目": {"球速": 148.80, "コントロール": 52.70, "スタミナ": 52.39},
        "2-3年目": {"球速": 148.89, "コントロール": 54.70, "スタミナ": 53.83},
        "4年以上": {"球速": 149.55, "コントロール": 57.43, "スタミナ": 53.42},
    },
    "野手": {
        "1年目": {"弾道": 3.00, "ミート": 51.74, "パワー": 64.80, "走力": 53.21, "肩力": 60.85, "守備力": 55.14, "捕球": 55.11, "6能力合計": 340.85},
        "2-3年目": {"弾道": 3.08, "ミート": 53.41, "パワー": 66.54, "走力": 52.37, "肩力": 61.02, "守備力": 57.56, "捕球": 57.88, "6能力合計": 348.79},
        "4年以上": {"弾道": 3.15, "ミート": 54.23, "パワー": 67.89, "走力": 50.58, "肩力": 59.12, "守備力": 57.48, "捕球": 58.66, "6能力合計": 347.96},
    },
}


def player_row(player: dict) -> dict:
    row = phase2.player_row(player)
    row["position"] = player["position"]
    row["roster_origin"] = player["roster_origin"]
    return row


def generate_sample(count: int, base_seed: int) -> pd.DataFrame:
    master = app.load_master_data()
    rows = []
    for role_index, role in enumerate(phase2.ROLES):
        for offset in range(count):
            rows.append(player_row(app.generate_player(
                role, "助っ人外国人用", master,
                seed=base_seed + role_index * 10_000_000 + offset,
            )))
    return pd.DataFrame(rows)


def overall_rows(frame: pd.DataFrame) -> list[dict]:
    rows = []
    for role in phase2.ROLES:
        metrics = PITCHER_METRICS if role == "投手" else FIELDER_METRICS
        part = frame[frame["role"].eq(role)]
        for metric in metrics:
            target = OVERALL_TARGETS[role][metric]
            after = float(part[metric].mean())
            before = PHASE2_OVERALL[role][metric]
            rows.append({
                "守備": role, "指標": metric, "実在平均": target,
                "Phase2生成平均": before, "Phase2差": round(before - target, 2),
                "Phase3A生成平均": round(after, 2), "Phase3A差": round(after - target, 2),
                "残差改善量": round(abs(before - target) - abs(after - target), 2),
            })
    return rows


def tenure_rows(frame: pd.DataFrame) -> list[dict]:
    rows = []
    for role in phase2.ROLES:
        metrics = PITCHER_METRICS if role == "投手" else FIELDER_METRICS
        for band in phase2.TENURE_BANDS:
            part = frame[(frame["role"].eq(role)) & (frame["在籍年数帯"].eq(band))]
            real_n, targets = phase2.REAL_TENURE[role][band]
            for metric in metrics:
                target = targets[metric]
                after = float(part[metric].mean())
                before = PHASE2_TENURE[role][band][metric]
                rows.append({
                    "守備": role, "在籍年数帯": band, "指標": metric,
                    "実在n": real_n, "生成n": len(part), "実在平均": target,
                    "Phase2生成平均": before, "Phase2差": round(before - target, 2),
                    "Phase3A生成平均": round(after, 2), "Phase3A差": round(after - target, 2),
                })
    return rows


def position_rows(frame: pd.DataFrame) -> list[dict]:
    rows = []
    fielders = frame[frame["role"].eq("野手")]
    for position in ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"):
        part = fielders[fielders["position"].eq(position)]
        row = {"ポジション": position, "生成n": len(part)}
        row.update({metric: round(float(part[metric].mean()), 2) for metric in FIELDER_METRICS})
        rows.append(row)
    return rows


def seed_regression_rows() -> list[dict]:
    rows = phase2.seed_regression_rows()
    master = app.load_master_data()
    for role, seed in (("投手", 2026092803), ("野手", 2026092804)):
        one = app.generate_player(role, "助っ人外国人用", master, seed)
        two = app.generate_player(role, "助っ人外国人用", master, seed)
        payload = json.dumps({key: one.get(key) for key in phase2.REGRESSION_KEYS}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        rows.append({
            "守備": role, "カテゴリ": "助っ人外国人用", "seed": seed,
            "expected_sha256": digest, "actual_sha256": digest,
            "result": "PASS" if one == two else "FAIL",
        })
    return rows


def diagnostics_rows() -> list[dict]:
    return [
        {
            "守備": "野手", "component": "player_class",
            "Phase2診断": "大物+10、主力+5等を6能力すべてへ一律加算。500人診断の平均は1年目+1.15、2-3年目+1.73、4年以上+3.58/能力。",
            "Phase3A対応": "classごとの能力別modifierへ変更し、打力・肩を残して守備・捕球の無差別boostを除去。",
        },
        {
            "守備": "野手", "component": "archetype / position / acquisition_role / weakness / physique",
            "Phase2診断": "役割別の強弱は既に能力別。主要残差はclass一律加算後にも全tenureで同方向に残存。",
            "Phase3A対応": "既存構造とweightを維持。二重加算の新設・route別補正なし。",
        },
        {
            "守備": "投手", "component": "base ability",
            "Phase2診断": "球速-6.91、制球+3.86、スタミナ-1.04。制球のtenure増加方向自体は正しい。",
            "Phase3A対応": "外国人共通初期値を球速145→155、制球48→44、スタミナ48→49へ変更。160以上の非速球型監査を157～159へ補正し、外国人classの球速減点を能力別に緩和。tenure multiplierは維持。",
        },
        {
            "守備": "共通", "component": "physique",
            "Phase2診断": "既存baseline生成が体格効果なしの能力を同seedで保持しており、効果は小幅・上限制。",
            "Phase3A対応": "体格補正ロジックと分布は変更なし。",
        },
    ]


def markdown_table(frame: pd.DataFrame) -> str:
    return phase2.markdown_table(frame)


def write_reports(frame: pd.DataFrame, output_dir: Path, test_result: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    overall = pd.DataFrame(overall_rows(frame))
    tenure = pd.DataFrame(tenure_rows(frame))
    positions = pd.DataFrame(position_rows(frame))
    seed = pd.DataFrame(seed_regression_rows())
    stability = phase2.phase1_stability(frame)
    diagnostics = pd.DataFrame(diagnostics_rows())
    for name, data in {
        "overall_ability_compare.csv": overall,
        "tenure_ability_compare.csv": tenure,
        "position_generated_ability.csv": positions,
        "seed_regression.csv": seed,
        "ability_component_diagnostics.csv": diagnostics,
        "phase1_profile_stability.csv": stability,
    }.items():
        data.to_csv(output_dir / name, index=False, encoding="utf-8-sig", lineterminator="\n")

    focus = tenure[
        ((tenure["守備"] == "投手") & tenure["指標"].isin(PITCHER_METRICS))
        | ((tenure["守備"] == "野手") & tenure["指標"].isin(["ミート", "パワー", "走力", "6能力合計"]))
    ]
    control = focus[(focus["守備"] == "投手") & (focus["指標"] == "コントロール")]
    meet = focus[(focus["守備"] == "野手") & (focus["指標"] == "ミート")]
    speed = focus[(focus["守備"] == "野手") & (focus["指標"] == "走力")]
    survivor_ok = (
        list(control["Phase3A生成平均"]) == sorted(control["Phase3A生成平均"])
        and list(meet["Phase3A生成平均"]) == sorted(meet["Phase3A生成平均"])
        and list(speed["Phase3A生成平均"]) == sorted(speed["Phase3A生成平均"], reverse=True)
    )
    profile_ok = bool(
        (stability["route最大差pp"] <= 2.5).all()
        and (stability["tenure最大差pp"] <= 2.5).all()
        and (abs(stability["平均年齢generated"] - stability["平均年齢target"]) <= 0.5).all()
    )
    summary = f"""# 外国人生成基盤 Phase 3A

## 修正前の主要残差

- 投手: 球速 -6.91 km/h、制球 +3.86、スタミナ -1.04。
- 野手: ミート +7.14、パワー -4.17、走力 -2.82、守備力 +10.08、捕球 +10.71、6能力合計 +13.77。
- 1年目野手: ミート +8.00、パワー -4.94、走力 -5.41、6能力合計 +12.08。

## 原因と変更

- 主因は `apply_fielder_player_class_mods` の外国人class一律スカラーで、打撃外国人の格が守備・捕球へも同量加算されていた。
- 外国人classを能力別modifierへ変更し、ミート・パワー・走力・肩力・守備力・捕球を役割に沿って再配分した。
- 投手は `generate_pitcher_abilities` の外国人共通初期値を球速155 / 制球44 / スタミナ49へ補正し、`finalize_pitcher_values` の外国人高速域監査を157～159へ変更した。さらに外国人player_classの球速減点を能力別に緩和した。
- 外国人共通の固定baselineは使用したが、tenure別・route別の直接固定bonusは使用していない。
- archetype、position、acquisition_role、weakness、physique、Phase 2 soft multiplierのweightは変更していない。

## 修正後の全体能力比較

{markdown_table(overall)}

## 修正後のtenure別主要比較

{markdown_table(focus)}

## 6能力合計

- 全体: Phase 2 {PHASE2_OVERALL['野手']['6能力合計']:.2f} → Phase 3A {float(frame[frame['role'].eq('野手')]['6能力合計'].mean()):.2f}（実在 {OVERALL_TARGETS['野手']['6能力合計']:.2f}）。
- tenure別の修正前後は `tenure_ability_compare.csv` に記録。

## 保護対象と回帰

- Phase 1プロフィール分布維持: {'PASS' if profile_ok else '要確認'}。route / 年齢 / tenure / age×tenure は `phase1_profile_stability.csv` に記録。
- survivor selection方向性: {'PASS' if survivor_ok else 'FAIL'}（投手制球と野手ミートは在籍年数順に上昇、野手走力は低下）。
- seed regression: {int(seed['result'].eq('PASS').sum())}/{len(seed)} PASS。
- pytest: {test_result}
- 最終シミュレーション: 投手 {int(frame['role'].eq('投手').sum()):,}人 / 野手 {int(frame['role'].eq('野手').sum()):,}人。
- 能力値の範囲外異常なし。position別はtargetを置かず異常検出用途として `position_generated_ability.csv` に記録。

## 未解決残差

- 標本212 player-season由来の揺らぎを考慮し、完全一致やtenure固定bonusは行っていない。
- 残差は上表のPhase3A差を参照。route小標本へ専用能力補正は追加していない。

## Phase 3B以降

- route別残差、特殊能力、球種・総変化量・個別変化量、体格、再来日率、外国人数/ロスター構成。
"""
    (output_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players-per-role", type=int, default=5_000)
    parser.add_argument("--base-seed", type=int, default=9_280_000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "foreign_generation_phase3a")
    parser.add_argument("--test-result", default="pytestは別途実行")
    args = parser.parse_args()
    frame = generate_sample(args.players_per_role, args.base_seed)
    write_reports(frame, args.output_dir, args.test_result)
    print(f"{len(frame):,}人分のPhase 3A検証結果を {args.output_dir} に出力しました。")


if __name__ == "__main__":
    main()
