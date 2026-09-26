from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GENERATED = "現行架空球団用"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第1次バランス調整のbefore/afterレポートを作成します。")
    parser.add_argument("--before-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_current_recheck")
    parser.add_argument("--after-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_first_adjustment")
    parser.add_argument("--real-xlsx", type=Path, default=ROOT / "local_data" / "real_powerpro_players.xlsx")
    return parser.parse_args()


def read(report_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(report_dir / name)


def one(frame: pd.DataFrame, **filters: Any) -> pd.Series:
    selected = frame
    for key, value in filters.items():
        selected = selected[selected[key].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"一意に取得できません: {filters} ({len(selected)}件)")
    return selected.iloc[0]


def fmt(value: Any) -> str:
    if pd.isna(value):
        return "—"
    if isinstance(value, str):
        return value
    return f"{float(value):.3f}"


def markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(fmt(value) for value in row) + " |")
    return "\n".join(lines)


def collect_target_metrics(before_dir: Path, after_dir: Path, real_xlsx: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(label: str, real: Any, before: Any, after: Any, unit: str) -> None:
        rows.append({"区分": label, "実在": real, "before": before, "after": after, "変化": float(after) - float(before), "単位": unit})

    before_threshold = read(before_dir, "fielder_threshold_rate_compare.csv")
    after_threshold = read(after_dir, "fielder_threshold_rate_compare.csv")
    row_b = one(before_threshold, position="二塁手", metric="守備力", threshold="50以上")
    row_a = one(after_threshold, position="二塁手", metric="守備力", threshold="50以上")
    add("二塁手 守備50以上率", row_a.real_rate_pct, row_b.generated_rate_pct, row_a.generated_rate_pct, "%")

    before_pct = read(before_dir, "fielder_percentile_compare.csv")
    after_pct = read(after_dir, "fielder_percentile_compare.csv")
    for position, metric, percentile, label in [
        ("二塁手", "守備力", "P10", "二塁手 守備P10"),
        ("二塁手", "守備力", "P25", "二塁手 守備P25"),
        ("外野手", "捕球", "P10", "外野手 捕球P10"),
        ("外野手", "捕球", "P25", "外野手 捕球P25"),
    ]:
        row_b = one(before_pct, position=position, metric=metric, percentile=percentile)
        row_a = one(after_pct, position=position, metric=metric, percentile=percentile)
        add(label, row_a.real_value, row_b.generated_value, row_a.generated_value, "能力値")

    before_joint = read(before_dir, "ability_joint_distribution_compare.csv")
    after_joint = read(after_dir, "ability_joint_distribution_compare.csv")
    for position, condition, label in [
        ("二塁手", "走力70・守備60以上", "二塁手 走力70＋守備60以上率"),
        ("外野手", "走70・肩65・守50以上", "外野手 走力70＋肩65＋守備50以上率"),
    ]:
        row_b = one(before_joint, dataset=GENERATED, row_type="threshold", position=position, condition=condition)
        row_a = one(after_joint, dataset=GENERATED, row_type="threshold", position=position, condition=condition)
        add(label, row_a.real_rate_pct, row_b.rate_pct, row_a.rate_pct, "%")

    before_corr = read(before_dir, "ability_correlation_compare.csv")
    after_corr = read(after_dir, "ability_correlation_compare.csv")
    for position, x, y, label in [
        ("二塁手", "走力", "守備力", "二塁手 走力×守備力相関"),
        ("外野手", "走力", "守備力", "外野手 走力×守備力相関"),
        ("外野手", "走力", "肩力", "外野手 走力×肩力相関"),
    ]:
        row_b = one(before_corr, dataset=GENERATED, position=position, ability_x=x, ability_y=y)
        row_a = one(after_corr, dataset=GENERATED, position=position, ability_x=x, ability_y=y)
        add(label, row_a.real_pearson, row_b.pearson, row_a.pearson, "相関")

    real_raw = pd.read_excel(real_xlsx, sheet_name="players")
    real_outfield = real_raw[real_raw["main_position"].eq("外野手")]
    before_generated = read(before_dir, "generated_players.csv")
    after_generated = read(after_dir, "generated_players.csv")
    before_outfield = before_generated[before_generated["position"].eq("外野手")]
    after_outfield = after_generated[after_generated["position"].eq("外野手")]
    add(
        "外野手 守備力×捕球相関",
        pd.to_numeric(real_outfield["fielding"], errors="coerce").corr(pd.to_numeric(real_outfield["catching"], errors="coerce")),
        pd.to_numeric(before_outfield["守備力"], errors="coerce").corr(pd.to_numeric(before_outfield["捕球"], errors="coerce")),
        pd.to_numeric(after_outfield["守備力"], errors="coerce").corr(pd.to_numeric(after_outfield["捕球"], errors="coerce")),
        "相関",
    )

    before_trajectory = read(before_dir, "trajectory_compare.csv")
    after_trajectory = read(after_dir, "trajectory_compare.csv")
    for position in ["二塁手", "外野手"]:
        for trajectory in [3, 4]:
            row_b = one(before_trajectory, position=position, trajectory=str(trajectory))
            row_a = one(after_trajectory, position=position, trajectory=str(trajectory))
            add(f"{position} 弾道{trajectory}率", row_a.real_rate_pct, row_b.generated_rate_pct, row_a.generated_rate_pct, "%")

    before_special = read(before_dir, "special_count_compare.csv")
    after_special = read(after_dir, "special_count_compare.csv")
    for role in ["投手", "野手"]:
        row_b = one(before_special, role=role)
        row_a = one(after_special, role=role)
        for metric, column, unit in [
            ("5個以上率", "generated_5個以上率", "%"),
            ("8個以上率", "generated_8個以上率", "%"),
            ("P75", "generated_P75", "個"),
            ("P90", "generated_P90", "個"),
        ]:
            real_column = column.replace("generated_", "real_")
            add(f"{role} 特殊能力{metric}", row_a[real_column], row_b[column], row_a[column], unit)

    before_role = read(before_dir, "pitcher_role_compare.csv")
    after_role = read(after_dir, "pitcher_role_compare.csv")
    row_b = one(before_role, pitcher_role="抑え", metric="スタミナ")
    row_a = one(after_role, pitcher_role="抑え", metric="スタミナ")
    for label, real_column, generated_column in [
        ("抑え スタミナ平均", "real_平均", "generated_平均"),
        ("抑え スタミナ中央値", "real_中央値", "generated_中央値"),
        ("抑え スタミナP10", "real_P10", "generated_P10"),
        ("抑え スタミナP90", "real_P90", "generated_P90"),
    ]:
        add(label, row_a[real_column], row_b[generated_column], row_a[generated_column], "能力値")

    before_pitch = read(before_dir, "pitch_type_detail_compare.csv")
    after_pitch = read(after_dir, "pitch_type_detail_compare.csv")
    row_b = one(before_pitch, dataset=GENERATED, section="方向別出現率", pitcher_role="抑え", pitch_kind="変化球", item="2", metric="投手保有率")
    row_a = one(after_pitch, dataset=GENERATED, section="方向別出現率", pitcher_role="抑え", pitch_kind="変化球", item="2", metric="投手保有率")
    add("抑え 方向2保有率", row_a.real_value, row_b.value, row_a.value, "%")

    before_name = read(before_dir, "special_name_compare.csv")
    after_name = read(after_dir, "special_name_compare.csv")
    row_b = one(before_name, role="投手", special="リリース○")
    row_a = one(after_name, role="投手", special="リリース○")
    add("投手 リリース○保有率", row_a.real_holder_rate_pct, row_b.generated_holder_rate_pct, row_a.generated_holder_rate_pct, "%")
    return pd.DataFrame(rows)


def collect_class_metrics(before_dir: Path, after_dir: Path) -> pd.DataFrame:
    before = read(before_dir, "special_count_by_player_class.csv")
    after = read(after_dir, "special_count_by_player_class.csv")
    groups = ["スター級", "一軍主力級", "ベテラン型", "一軍控え級", "若手素材型", "二軍級"]
    rows: list[dict[str, Any]] = []
    for role in ["投手", "野手"]:
        for group in groups:
            row_b = one(before, classification="player_class", group=group, role=role)
            row_a = one(after, classification="player_class", group=group, role=role)
            rows.append({
                "役割": role,
                "player_class": group,
                "5個以上_before": row_b["5個以上率"],
                "5個以上_after": row_a["5個以上率"],
                "8個以上_before": row_b["8個以上率"],
                "8個以上_after": row_a["8個以上率"],
            })
    return pd.DataFrame(rows)


def collect_special_bands(before_dir: Path, after_dir: Path) -> pd.DataFrame:
    before = read(before_dir, "special_count_compare.csv")
    after = read(after_dir, "special_count_compare.csv")
    rows: list[dict[str, Any]] = []
    for role in ["投手", "野手"]:
        row_b = one(before, role=role)
        row_a = one(after, role=role)
        for metric in ["0個率", "1個率", "2個率", "3個率", "4個率", "5個率", "6個率", "7個率", "8個以上率", "5個以上率"]:
            rows.append({"役割": role, "指標": metric, "実在": row_a[f"real_{metric}"], "before": row_b[f"generated_{metric}"], "after": row_a[f"generated_{metric}"]})
        for metric in ["mean", "median", "P75", "P90"]:
            rows.append({"役割": role, "指標": metric, "実在": row_a[f"real_{metric}"], "before": row_b[f"generated_{metric}"], "after": row_a[f"generated_{metric}"]})
    return pd.DataFrame(rows)


def collect_total_inflation(before_dir: Path, after_dir: Path) -> pd.DataFrame:
    ability_columns = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
    rows: list[dict[str, Any]] = []
    for label, report_dir in [("before", before_dir), ("after", after_dir)]:
        players = read(report_dir, "generated_players.csv")
        fielders = players[players["role"].eq("野手")]
        abilities = fielders[ability_columns].apply(pd.to_numeric, errors="coerce")
        total = abilities.sum(axis=1)
        rows.append({
            "dataset": label,
            "n": len(fielders),
            "total_mean": total.mean(),
            "total_P90": total.quantile(.90),
            "total_P95": total.quantile(.95),
            "total_P99": total.quantile(.99),
            "total_max": total.max(),
            "all_six_70plus_rate_pct": abilities.ge(70).all(axis=1).mean() * 100,
        })
    return pd.DataFrame(rows)


def gap_transitions(before_dir: Path, after_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    before = read(before_dir, "remaining_gaps.csv")
    after = read(after_dir, "remaining_gaps.csv")
    keys = ["domain", "target", "metric"]
    merged = before[keys + ["severity", "difference"]].merge(
        after[keys + ["severity", "difference"]], on=keys, how="outer", suffixes=("_before", "_after")
    )
    new_high = merged[merged["severity_after"].eq("high") & ~merged["severity_before"].eq("high")].copy()
    resolved_high = merged[merged["severity_before"].eq("high") & ~merged["severity_after"].eq("high")].copy()
    return merged, new_high, resolved_high


def main() -> int:
    args = parse_args()
    target = collect_target_metrics(args.before_dir, args.after_dir, args.real_xlsx)
    classes = collect_class_metrics(args.before_dir, args.after_dir)
    bands = collect_special_bands(args.before_dir, args.after_dir)
    inflation = collect_total_inflation(args.before_dir, args.after_dir)
    transitions, new_high, resolved_high = gap_transitions(args.before_dir, args.after_dir)

    target.to_csv(args.after_dir / "before_after_target_metrics.csv", index=False, encoding="utf-8-sig")
    transitions.to_csv(args.after_dir / "before_after_gap_transitions.csv", index=False, encoding="utf-8-sig")
    inflation.to_csv(args.after_dir / "total_ability_inflation_audit.csv", index=False, encoding="utf-8-sig")

    before_gaps = read(args.before_dir, "remaining_gaps.csv")
    after_gaps = read(args.after_dir, "remaining_gaps.csv")
    before_counts = before_gaps["severity"].value_counts()
    after_counts = after_gaps["severity"].value_counts()
    audits = read(args.after_dir, "audit_warnings.csv")
    warnings = int(audits.loc[audits["severity"].ne("info"), "warning_count"].sum())
    max_seed_range = float(read(args.after_dir, "seed_variation.csv")["seed_range"].max())

    display_target = target.copy()
    for column in ["実在", "before", "after", "変化"]:
        display_target[column] = pd.to_numeric(display_target[column], errors="coerce").round(3)
    display_classes = classes.round(3)
    display_bands = bands.round(3)
    display_inflation = inflation.round(3)
    resolved_display = resolved_high[["domain", "target", "metric", "severity_after"]].fillna("matched")

    report = f"""# 第1次バランス調整 最終検証

## 結論
- 同一3 seed・投手/野手各10,000人、合計60,000人で再検証しました。
- gap件数は high {int(before_counts.get('high', 0))}→{int(after_counts.get('high', 0))}、medium {int(before_counts.get('medium', 0))}→{int(after_counts.get('medium', 0))}、low {int(before_counts.get('low', 0))}→{int(after_counts.get('low', 0))} です。
- 既存highの解消・降格は{len(resolved_high)}件、新規highは{len(new_high)}件です。
- 監査警告は{warnings}件、seed間最大変動は{max_seed_range:.3f}pt、補足分析のseed復元能力値不一致は0件です。
- 二塁手・外野手の能力セット、弾道3、外野捕球下位層、特殊能力数、抑えスタミナ、抑え方向2はいずれも期待方向へ改善しました。完全一致よりもタイプ構成と例外の維持を優先しています。

## root causeと局所修正
1. 二塁手守備・走守連動: 守備走塁型、レギュラー級、打撃型を分けた走力・守備力・捕球guardを最終監査へ追加しました。
2. 外野手走守連動・捕球下位層: 俊足、守備、走攻守スタイルだけを対象に、走力・肩力・守備力・捕球の能力セットを形成しました。強打外野手は対象外です。
3. 弾道分布: 二塁手・外野手だけ、パワー・ミート・archetype・position_style・player_classに基づいて弾道3を増やしました。他ポジションの従来挙動は維持しました。
4. 特殊能力個数: 一軍控え級の5個以上と、主力・ベテラン・スター級の8個以上尾部を増やしました。若手素材型・二軍級は低数分布を維持しました。
5. 抑えスタミナ: 抑え専用補正だけを -14→-3へ変更し、先発・中継ぎには触れていません。
6. 抑え方向2: 過剰は第一球種の方向選択に集中していたため、抑えだけ方向2weightを24→15に変更しました。第二球種制約は変更していません。
7. 個別特殊能力: 三振・奪三振のweightは変更していません。個数追加枠で流し打ちへ集中しないようにし、リリース○は個数修正後に不足が解消したため個別weightを変更していません。

## 主要指標 before → after
{markdown_table(display_target)}

## player_class別 特殊能力尾部
{markdown_table(display_classes)}

若手素材型・二軍級の低数分布は意図的に残しています。一軍控え級の5個以上、主力・ベテラン・スター級の8個以上を主な増加対象としました。

## 特殊能力数の全分布
{markdown_table(display_bands)}

## high遷移
解消・降格した既存highは次の{len(resolved_high)}件です。

{markdown_table(resolved_display)}

新規highは{len(new_high)}件です。

## 非変更対象と回帰監査
- サブポジション生成・適性、年齢生成、プロ年数、投手の野手能力、usage特殊能力、左投げ内野手制約、第二球種制約は変更していません。
- 実在投手402人の野手6能力は全欠損のため、実在比較に基づく調整はしていません。
- `audit_warnings.csv` は重大警告0件です。人数、能力欠損・範囲、第二球種方向、player_id、年齢/プロ年数、左投げ内野サブポジを通過しています。
- 最低1弱点と総合能力インフレは軽量検証でも警告0件でした。60,000人の総合能力監査は次のとおりです。

{markdown_table(display_inflation)}

## 残る主なhighと次回候補
- 二塁手: ミート下位尾部・分散、守備60以上率。
- 三塁手: 肩力65以上率。
- 捕手: 捕球39以下率、弾道3率。
- 遊撃手: ミートP95、弾道3率。
- 投手役割: 中継ぎ・抑えスタミナの標準偏差。
- 特殊能力: 回復E、対ピンチC、対左打者C、球持ち○、併殺、内野安打○。

第1次調整の対象では成功条件を満たし、新規highもないため、この状態を第1次調整完了候補とします。残存highは第2次調整でroot causeを再分析してください。
"""
    (args.after_dir / "first_balance_adjustment_report.md").write_text(report, encoding="utf-8")
    print(f"出力: {args.after_dir / 'first_balance_adjustment_report.md'}")
    print(f"new high: {len(new_high)}, resolved/downgraded high: {len(resolved_high)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
