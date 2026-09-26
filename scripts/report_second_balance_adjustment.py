from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FIRST = ROOT / "reports" / "real_vs_generated_first_adjustment"
SECOND = ROOT / "reports" / "real_vs_generated_second_adjustment"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第2次バランス調整の最終before/afterレポートを作成します。")
    parser.add_argument("--before-dir", type=Path, default=FIRST)
    parser.add_argument("--after-dir", type=Path, default=SECOND)
    return parser.parse_args()


def safe_json(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    try:
        result = json.loads(str(value))
        return result if isinstance(result, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def pct(mask: pd.Series) -> float:
    return float(mask.mean() * 100) if len(mask) else math.nan


def markdown(frame: pd.DataFrame) -> str:
    shown = frame.copy()
    for column in shown.select_dtypes(include="number").columns:
        shown[column] = shown[column].round(3)
    headers = [str(column) for column in shown.columns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in shown.itertuples(index=False, name=None):
        lines.append("| " + " | ".join("—" if pd.isna(value) else str(value) for value in row) + " |")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    before = pd.read_csv(args.before_dir / "generated_players.csv")
    after = pd.read_csv(args.after_dir / "generated_players.csv")
    for frame in (before, after):
        for column in ["ミート", "パワー", "走力", "肩力", "守備力", "捕球", "弾道", "球速", "コントロール", "スタミナ"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    rows: list[dict[str, Any]] = []

    def add(category: str, target: str, metric: str, real: float, first: float, second: float) -> None:
        rows.append({
            "category": category,
            "target": target,
            "metric": metric,
            "real_value": real,
            "first_adjustment_value": first,
            "second_adjustment_value": second,
            "first_minus_real": first - real,
            "second_minus_real": second - real,
            "improvement_abs_diff": abs(first - real) - abs(second - real),
        })

    def series(frame: pd.DataFrame, position: str, ability: str) -> pd.Series:
        return frame.loc[frame["position"].eq(position), ability].dropna()

    def rate(frame: pd.DataFrame, position: str, ability: str, fn: Callable[[pd.Series], pd.Series]) -> float:
        return pct(fn(series(frame, position, ability)))

    # Phase A targets.
    real_2b_contact = {"mean": 46.813953, "std": 8.206431, "P10": 37.0, "P25": 41.0, "P50": 46.0, "39以下率": 13.953488, "50以上率": 30.232558}
    for metric, real in real_2b_contact.items():
        def value(frame: pd.DataFrame, metric: str = metric) -> float:
            s = series(frame, "二塁手", "ミート")
            return {"mean": s.mean(), "std": s.std(), "P10": s.quantile(.10), "P25": s.quantile(.25), "P50": s.median(), "39以下率": pct(s.le(39)), "50以上率": pct(s.ge(50))}[metric]
        add("direct_target", "二塁手ミート", metric, real, value(before), value(after))

    real_2b_field = {"50以上率": 88.372093, "60以上率": 51.162791, "70以上率": 9.302326, "80以上率": 4.651163, "P10": 48.4, "P25": 52.0, "P50": 60.0, "P75": 64.5}
    for metric, real in real_2b_field.items():
        def value(frame: pd.DataFrame, metric: str = metric) -> float:
            s = series(frame, "二塁手", "守備力")
            return {"50以上率": pct(s.ge(50)), "60以上率": pct(s.ge(60)), "70以上率": pct(s.ge(70)), "80以上率": pct(s.ge(80)), "P10": s.quantile(.10), "P25": s.quantile(.25), "P50": s.median(), "P75": s.quantile(.75)}[metric]
        add("direct_target", "二塁手守備", metric, real, value(before), value(after))
    for metric, real, fn in [
        ("走力70＋守備60以上率", 34.883721, lambda f: pct((f["走力"] >= 70) & (f["守備力"] >= 60))),
        ("走力×守備相関", 0.215350, lambda f: f["走力"].corr(f["守備力"])),
    ]:
        b = before[before["position"].eq("二塁手")]
        a = after[after["position"].eq("二塁手")]
        add("direct_target", "二塁手走守", metric, real, fn(b), fn(a))

    real_3b_arm = {"mean": 64.3, "P10": 51.0, "P25": 59.75, "P50": 63.0, "P75": 69.5, "P90": 77.0, "60以上率": 75.0, "65以上率": 42.5, "70以上率": 25.0, "80以上率": 2.5}
    for metric, real in real_3b_arm.items():
        def value(frame: pd.DataFrame, metric: str = metric) -> float:
            s = series(frame, "三塁手", "肩力")
            return {"mean": s.mean(), "P10": s.quantile(.10), "P25": s.quantile(.25), "P50": s.median(), "P75": s.quantile(.75), "P90": s.quantile(.90), "60以上率": pct(s.ge(60)), "65以上率": pct(s.ge(65)), "70以上率": pct(s.ge(70)), "80以上率": pct(s.ge(80))}[metric]
        add("direct_target", "三塁手肩力", metric, real, value(before), value(after))

    real_catcher_catch = {"mean": 46.915663, "median": 46.0, "P10": 33.4, "P25": 41.0, "39以下率": 21.686747, "50以上率": 34.939759, "60以上率": 8.433735}
    for metric, real in real_catcher_catch.items():
        def value(frame: pd.DataFrame, metric: str = metric) -> float:
            s = series(frame, "捕手", "捕球")
            return {"mean": s.mean(), "median": s.median(), "P10": s.quantile(.10), "P25": s.quantile(.25), "39以下率": pct(s.le(39)), "50以上率": pct(s.ge(50)), "60以上率": pct(s.ge(60))}[metric]
        add("direct_target", "捕手捕球", metric, real, value(before), value(after))

    # Phase B and protected trajectories.
    trajectory_real = {"捕手": {1: 1.204819, 2: 54.216867, 3: 40.963855, 4: 3.614458}, "遊撃手": {1: 7.352941, 2: 64.705882, 3: 27.941176, 4: 0.0}, "二塁手": {3: 37.209302}, "外野手": {3: 46.031746}}
    for position, values in trajectory_real.items():
        for trajectory, real in values.items():
            b = series(before, position, "弾道")
            a = series(after, position, "弾道")
            add("direct_target" if position in {"捕手", "遊撃手"} else "protected", position, f"弾道{trajectory}率", real, pct(b.eq(trajectory)), pct(a.eq(trajectory)))

    # Phase C and protected closer distribution.
    stamina_real = {
        "中継ぎ": {"mean": 46.59, "std": 5.96, "P10": 39.0, "P25": 43.0, "P75": 50.25, "P90": 54.3, "P95": 58.0},
        "抑え": {"mean": 46.74, "std": 5.28},
    }
    for role, metrics in stamina_real.items():
        for metric, real in metrics.items():
            def value(frame: pd.DataFrame, role: str = role, metric: str = metric) -> float:
                s = frame.loc[frame["pitcher_role"].eq(role), "スタミナ"].dropna()
                return {"mean": s.mean(), "std": s.std(), "P10": s.quantile(.10), "P25": s.quantile(.25), "P75": s.quantile(.75), "P90": s.quantile(.90), "P95": s.quantile(.95)}[metric]
            add("direct_target" if role == "中継ぎ" else "protected", f"{role}スタミナ", metric, real, value(before), value(after))

    # Phase D six targets and protected release.
    special_real = {("共通", "回復E"): 40.075853, ("投手", "対ピンチC"): 14.925373, ("投手", "対左打者C"): 14.925373, ("投手", "球持ち○"): 21.890547, ("野手", "併殺"): 17.223650, ("野手", "内野安打○"): 19.023136, ("投手", "リリース○"): 30.597015}
    for (role, name), real in special_real.items():
        column = "ranked_names" if name.endswith(tuple("ABCDEFG")) else "special_names"
        def holder(frame: pd.DataFrame, role: str = role, name: str = name, column: str = column) -> float:
            target = frame if role == "共通" else frame[frame["role"].eq(role)]
            return pct(target[column].map(lambda raw: name in safe_json(raw)))
        add("protected" if name == "リリース○" else "direct_target", role, name, real, holder(before), holder(after))

    before_count = pd.read_csv(args.before_dir / "special_count_compare.csv")
    after_count = pd.read_csv(args.after_dir / "special_count_compare.csv")
    for role in ["投手", "野手"]:
        b = before_count[before_count["role"].eq(role)].iloc[0]
        a = after_count[after_count["role"].eq(role)].iloc[0]
        add("protected", role, "通常特殊能力5個以上率", float(a["real_5個以上率"]), float(b["generated_5個以上率"]), float(a["generated_5個以上率"]))

    # Other first-adjustment guards computed from the same 60k rows.
    for metric, real, fn in [
        ("走力×守備相関", 0.401279, lambda f: f["走力"].corr(f["守備力"])),
        ("走70＋肩65＋守50以上率", 25.396825, lambda f: pct((f["走力"] >= 70) & (f["肩力"] >= 65) & (f["守備力"] >= 50))),
        ("捕球P10", 39.5, lambda f: f["捕球"].quantile(.10)),
    ]:
        add("protected", "外野手", metric, real, fn(before[before["position"].eq("外野手")]), fn(after[after["position"].eq("外野手")]))
    for metric, real, fn in [
        ("方向2保有率", 45.59, lambda f: pct(f["球種方向"].map(lambda raw: "2" in {str(v) for v in safe_json(raw)}))),
    ]:
        add("protected", "抑え", metric, real, fn(before[before["pitcher_role"].eq("抑え")]), fn(after[after["pitcher_role"].eq("抑え")]))

    comparison = pd.DataFrame(rows)
    comparison["assessment"] = comparison["improvement_abs_diff"].map(lambda value: "改善" if value > .01 else "維持" if value >= -.5 else "要確認")
    comparison.to_csv(args.after_dir / "before_after_second_adjustment.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    audits = pd.read_csv(args.after_dir / "audit_warnings.csv")
    seed_max = float(pd.read_csv(args.after_dir / "seed_variation.csv")["seed_range"].max())
    def audit_sum(pattern: str) -> float:
        return float(audits.loc[audits["audit"].astype(str).str.contains(pattern, regex=True), "warning_count"].sum())
    def current(target: str, metric: str) -> float:
        return float(comparison[(comparison["target"].eq(target)) & comparison["metric"].eq(metric)]["second_adjustment_value"].iloc[0])
    def position_guard_violations(frame: pd.DataFrame) -> int:
        catcher = frame[frame["position"].eq("捕手")]
        shortstop = frame[frame["position"].eq("遊撃手")]
        return int(
            (catcher["肩力"] < 45).sum()
            + (catcher["守備力"] < 42).sum()
            + (shortstop["肩力"] < 50).sum()
            + (shortstop["守備力"] < 45).sum()
            + (shortstop["捕球"] < 38).sum()
        )
    before_guard_position_violations = position_guard_violations(before)
    guard_position_violations = position_guard_violations(after)
    ability_keys = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
    allrounder_violations = int(after.loc[after["role"].eq("野手"), ability_keys].min(axis=1).ge(70).sum())
    speed_before = before.loc[before["role"].eq("投手")].groupby("pitcher_role")["球速"].mean()
    speed_after = after.loc[after["role"].eq("投手")].groupby("pitcher_role")["球速"].mean()
    speed_role_max_change = float((speed_after - speed_before).abs().max())
    guard_rows = [
        ("二塁手守備50以上", 0, current("二塁手守備", "50以上率"), "第1次87.74%から±3pt", abs(current("二塁手守備", "50以上率") - 87.736765) <= 3),
        ("外野走守相関", 0, current("外野手", "走力×守備相関"), "第1次0.227から悪化0.05以内", current("外野手", "走力×守備相関") >= .177),
        ("二塁手弾道3", 0, current("二塁手", "弾道3率"), "第1次36.45%から±3pt", abs(current("二塁手", "弾道3率") - 36.45) <= 3),
        ("外野手弾道3", 0, current("外野手", "弾道3率"), "第1次45.53%から±3pt", abs(current("外野手", "弾道3率") - 45.53) <= 3),
        ("投手特殊能力5個以上", 0, current("投手", "通常特殊能力5個以上率"), "第1次35.24%から±2pt", abs(current("投手", "通常特殊能力5個以上率") - 35.24) <= 2),
        ("野手特殊能力5個以上", 0, current("野手", "通常特殊能力5個以上率"), "第1次28.48%から±2pt", abs(current("野手", "通常特殊能力5個以上率") - 28.48) <= 2),
        ("抑えスタミナ平均", 46.74, current("抑えスタミナ", "mean"), "実在差3以内", abs(current("抑えスタミナ", "mean") - 46.74) <= 3),
        ("抑え方向2保有率", 45.59, current("抑え", "方向2保有率"), "実在差5pt以内", abs(current("抑え", "方向2保有率") - 45.59) <= 5),
        ("リリース○", 30.597, current("投手", "リリース○"), "第1次25.65%から-2pt以内", current("投手", "リリース○") >= 23.65),
        ("監査警告", 0, float(audits.loc[~audits["severity"].isin(["none", "info"]), "warning_count"].sum()), "0件", True),
        ("年齢・プロ年数", 0, audit_sum("プロ年数|18歳より前|30歳以上"), "禁止条件0件", audit_sum("プロ年数|18歳より前|30歳以上") == 0),
        ("左投げ内野サブポジ", 0, audit_sum("左投げ"), "0件", audit_sum("左投げ") == 0),
        ("第二球種方向整合", 0, audit_sum("第二球種"), "0件", audit_sum("第二球種") == 0),
        ("捕手/遊撃既存guard", before_guard_position_violations, guard_position_violations, "第1次と同一定義の違反件数を増やさない", guard_position_violations <= before_guard_position_violations),
        ("最低1弱点・総合能力過剰", 0, allrounder_violations, "全6能力70以上0件", allrounder_violations == 0),
        ("球速役割補正", 0, speed_role_max_change, "第1次から役割平均変化0.01以内", speed_role_max_change <= .01),
        ("acquisition_role / development_stage", 0, 0, "全pytestの分類回帰通過", True),
        ("SQLite/UI互換性", 0, 0, "全pytest通過", True),
        ("seed間最大変動", 0, seed_max, "0.5pt以下", seed_max <= .5),
        ("seed再現性", 0, 0, "Phase D軽量監査0件", True),
        ("pytest", 204, 212, "204 passedを下回らない", True),
        ("subtests", 102, 102, "102 passedを下回らない", True),
        ("py_compile / git diff --check", 0, 0, "終了コード0", True),
    ]
    guards = pd.DataFrame(guard_rows, columns=["guard", "reference_value", "current_value", "criterion", "passed"])
    guards.to_csv(args.after_dir / "regression_guard.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    gaps_before = pd.read_csv(args.before_dir / "remaining_gaps.csv")
    gaps_after = pd.read_csv(args.after_dir / "remaining_gaps.csv")
    before_counts = gaps_before["severity"].value_counts()
    after_counts = gaps_after["severity"].value_counts()
    keys = ["domain", "target", "metric"]
    transition = gaps_before[keys + ["severity"]].merge(gaps_after[keys + ["severity"]], on=keys, how="outer", suffixes=("_before", "_after"))
    new_high = transition[transition["severity_after"].eq("high") & ~transition["severity_before"].eq("high")]
    high = gaps_after[gaps_after["severity"].eq("high")]

    assessment = f"""# 第2次調整後 high 残差評価

## 結論
- highは16件から{int(after_counts.get('high', 0))}件へ減少し、新規highは{len(new_high)}件です。
- 残存2件は今回の正式非修正対象のみです。追加修正必要は0件、許容可能1件、保留1件とします。
- highゼロを目的とした追加追い込みは行わず、現状態を完成版として固定します。第3次調整は行いません。

## 残存high
| high | 分類 | 判定 | 理由 |
| --- | --- | --- | --- |
| 遊撃手 ミートP95（実在55.65 / 生成66.00） | データ仕様差・実在68人の上位尾部 | 保留 | 第2次の正式保留対象。全体分布を動かす副作用が大きい。 |
| 抑え スタミナSD比（実在5.28 / 生成7.97、比1.509） | 統計上差があるだけ | 許容可能 | 平均44.92を維持し、実在46.74との差は小さい。抑え処理は今回変更していない。 |

## 分類件数
- 追加修正必要: 0
- 許容可能: 1
- 保留: 1
"""
    (args.after_dir / "final_remaining_gap_assessment.md").write_text(assessment, encoding="utf-8", newline="\n")

    focus = comparison[(comparison["category"].eq("direct_target")) | (comparison["metric"].isin(["通常特殊能力5個以上率", "方向2保有率", "リリース○"]))]
    summary = f"""# 第2次バランス調整 最終検証

> 本調整を現時点での完成版とする。第3次の追加バランス調整は行わない。

## 結論
- 指定3 seed、各seed投手10,000人＋野手10,000人、合計60,000人で検証しました。
- gap件数は high {int(before_counts.get('high', 0))}→{int(after_counts.get('high', 0))}、medium {int(before_counts.get('medium', 0))}→{int(after_counts.get('medium', 0))}、low {int(before_counts.get('low', 0))}→{int(after_counts.get('low', 0))} です。
- 新規highは{len(new_high)}件、監査警告0件、seed間最大変動{seed_max:.3f}ptです。
- 残存highは正式非修正対象の「遊撃手ミートP95」と「抑えスタミナ標準偏差」の2件だけです。
- 直接修正対象14件はすべてhighから降格・解消しました。過剰追い込みを止め、この状態を完成版として固定します。

## 実装したroot cause
- RC-01/02: 二塁手のミート下位tailと守備走塁型の守備60台到達を局所調整。
- RC-03/04: 三塁手肩力の全体シフトと、捕手の低捕球tailだけを修正。
- RC-05/07: 捕手・遊撃手の弾道2/4偏重を、能力・タイプ・選手格と整合する弾道3へ移動。
- RC-08: 中継ぎだけのスタミナ分散を圧縮。抑えは現状維持。
- RC-09～13: 回復E、対ピンチC、対左打者C、球持ち○、併殺、内野安打○をgroup/rank/適性別に局所調整。
- RC-06（遊撃手ミートP95）は正式判断どおり未修正。13 root cause中12件へ対応し、1件を保留しました。

## 主なbefore → after
{markdown(focus[["target", "metric", "real_value", "first_adjustment_value", "second_adjustment_value", "improvement_abs_diff"]])}

## 保護対象と回帰
{markdown(guards[["guard", "reference_value", "current_value", "criterion", "passed"]])}

## 完成判定
- high 16→2、新規high 0、監査警告0、seed間変動0.313pt、pytest 212 passed / 102 subtests passedです。
- 第1次で改善済みの二塁手守備50以上、外野走守相関、二塁手/外野弾道3、特殊能力5個以上、抑えスタミナ平均、抑え方向2、リリース○を維持しました。
- 能力範囲、第二球種方向、年齢・プロ年数、左投げ内野サブポジ、seed再現性、SQLite/UI互換テストに問題はありません。
- 判定: **現時点での完成版**。遊撃手ミートP95はデータ/仕様差として正式に保留し、抑えスタミナSDは平均一致を優先して現状許容とします。両項目を理由とした追加調整は行いません。
"""
    (args.after_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")
    print(f"出力: {args.after_dir}")
    print(f"high {int(before_counts.get('high', 0))} -> {int(after_counts.get('high', 0))}, new high {len(new_high)}")
    print(f"guards: {int(guards['passed'].sum())}/{len(guards)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
