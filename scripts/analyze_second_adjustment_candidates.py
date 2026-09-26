from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.recheck_current_balance import load_real  # noqa: E402


ABILITIES = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第2次調整候補のroot cause用証拠表を作成します。")
    parser.add_argument("--real-xlsx", type=Path, default=ROOT / "local_data" / "real_powerpro_players.xlsx")
    parser.add_argument("--before-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_current_recheck")
    parser.add_argument("--after-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_first_adjustment")
    return parser.parse_args()


def load_generated(report_dir: Path) -> pd.DataFrame:
    players = pd.read_csv(report_dir / "generated_players.csv")
    details = pd.read_csv(report_dir / "supplemental_generated_detail_cache.csv")
    players = players.merge(details.drop(columns=[column for column in ["development_stage"] if column in details and column in players]), on="player_id", how="left", suffixes=("", "_detail"))
    for column in [*ABILITIES, "弾道", "スタミナ"]:
        players[column] = pd.to_numeric(players[column], errors="coerce")
    return players


def describe(values: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": values.mean(),
        "std": values.std(ddof=1),
        "P10": values.quantile(.10),
        "P25": values.quantile(.25),
        "P50": values.quantile(.50),
        "P75": values.quantile(.75),
        "P90": values.quantile(.90),
        "P95": values.quantile(.95),
        "39以下率": values.le(39).mean() * 100,
        "50以上率": values.ge(50).mean() * 100,
        "60以上率": values.ge(60).mean() * 100,
        "65以上率": values.ge(65).mean() * 100,
        "70以上率": values.ge(70).mean() * 100,
        "80以上率": values.ge(80).mean() * 100,
    }


def add_distribution(rows: list[dict[str, Any]], topic: str, dataset: str, frame: pd.DataFrame, ability: str, group_by: str = "全体", group: str = "全体") -> None:
    rows.append({"topic": topic, "dataset": dataset, "group_by": group_by, "group": group, "ability": ability, **describe(frame[ability])})


def add_position_evidence(rows: list[dict[str, Any]], dataset: str, frame: pd.DataFrame, include_groups: bool) -> None:
    specs = [
        ("二塁手ミート下位尾部", "二塁手", "ミート"),
        ("二塁手守備上位層", "二塁手", "守備力"),
        ("三塁手肩力", "三塁手", "肩力"),
        ("捕手捕球下位層", "捕手", "捕球"),
        ("遊撃手ミート上位尾部", "遊撃手", "ミート"),
    ]
    for topic, position, ability in specs:
        subset = frame[(frame["role"].eq("野手")) & frame["position"].eq(position)]
        add_distribution(rows, topic, dataset, subset, ability)
        if not include_groups:
            continue
        for group_by in ["position_style", "player_class"]:
            for group, grouped in subset.groupby(group_by, dropna=False):
                add_distribution(rows, topic, dataset, grouped, ability, group_by, str(group or "未設定"))


def add_second_base_joint(rows: list[dict[str, Any]], dataset: str, frame: pd.DataFrame, include_groups: bool) -> None:
    subset = frame[(frame["role"].eq("野手")) & frame["position"].eq("二塁手")]
    group_specs = [("全体", "全体", subset)]
    if include_groups:
        for group_by in ["position_style", "player_class"]:
            group_specs.extend((group_by, str(group or "未設定"), grouped) for group, grouped in subset.groupby(group_by, dropna=False))
    for group_by, group, grouped in group_specs:
        rows.append({
            "topic": "二塁手走守複合",
            "dataset": dataset,
            "group_by": group_by,
            "group": group,
            "ability": "走力×守備力",
            "n": len(grouped),
            "mean": grouped["守備力"].mean(),
            "P50": grouped["守備力"].median(),
            "50以上率": grouped["守備力"].ge(50).mean() * 100,
            "60以上率": grouped["守備力"].ge(60).mean() * 100,
            "70以上率": grouped["守備力"].ge(70).mean() * 100,
            "走70守60率": (grouped["走力"].ge(70) & grouped["守備力"].ge(60)).mean() * 100,
            "走守相関": grouped["走力"].corr(grouped["守備力"]),
        })


def add_trajectory(rows: list[dict[str, Any]], dataset: str, frame: pd.DataFrame, include_groups: bool) -> None:
    for position in ["捕手", "遊撃手"]:
        subset = frame[(frame["role"].eq("野手")) & frame["position"].eq(position)]
        group_specs = [("全体", "全体", subset)]
        if include_groups:
            for group_by in ["position_style", "player_class"]:
                group_specs.extend((group_by, str(group or "未設定"), grouped) for group, grouped in subset.groupby(group_by, dropna=False))
        for group_by, group, grouped in group_specs:
            rows.append({
                "topic": f"{position}弾道",
                "dataset": dataset,
                "group_by": group_by,
                "group": group,
                "ability": "弾道",
                "n": len(grouped),
                "mean": grouped["弾道"].mean(),
                "P50": grouped["弾道"].median(),
                "弾道1率": grouped["弾道"].eq(1).mean() * 100,
                "弾道2率": grouped["弾道"].eq(2).mean() * 100,
                "弾道3率": grouped["弾道"].eq(3).mean() * 100,
                "弾道4率": grouped["弾道"].eq(4).mean() * 100,
                "パワー平均": grouped["パワー"].mean(),
                "ミート平均": grouped["ミート"].mean(),
            })


def stamina_evidence(before_dir: Path, after_dir: Path) -> pd.DataFrame:
    columns = ["平均", "標準偏差", "P10", "P25", "P50", "P75", "P90", "P95"]
    rows: list[dict[str, Any]] = []
    for phase, report_dir in [("before", before_dir), ("after", after_dir)]:
        table = pd.read_csv(report_dir / "pitcher_role_compare.csv")
        for role in ["中継ぎ", "抑え"]:
            item = table[(table["pitcher_role"].eq(role)) & table["metric"].eq("スタミナ")].iloc[0]
            for metric in columns:
                rows.append({
                    "pitcher_role": role,
                    "metric": metric,
                    "real": item[f"real_{metric}"],
                    "phase": phase,
                    "generated": item[f"generated_{metric}"],
                    "generated_minus_real": item[f"generated_{metric}"] - item[f"real_{metric}"],
                })
    return pd.DataFrame(rows)


def special_evidence(before_dir: Path, after_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    before_ranked = pd.read_csv(before_dir / "ranked_special_compare.csv")
    after_ranked = pd.read_csv(after_dir / "ranked_special_compare.csv")
    for family, rank, role in [("回復", "E", "共通"), ("対ピンチ", "C", "投手"), ("対左打者", "C", "投手")]:
        before = before_ranked[(before_ranked["family"].eq(family)) & before_ranked["rank"].eq(rank) & before_ranked["target_role"].eq(role)].iloc[0]
        after = after_ranked[(after_ranked["family"].eq(family)) & after_ranked["rank"].eq(rank) & after_ranked["target_role"].eq(role)].iloc[0]
        real = after["real_explicit_target_player_rate_pct"]
        before_value = before["generated_target_player_rate_pct"]
        after_value = after["generated_target_player_rate_pct"]
        rows.append({"type": "ranked", "role": role, "name": f"{family}{rank}", "real_rate": real, "before_rate": before_value, "after_rate": after_value, "before_diff": before_value - real, "after_diff": after_value - real, "after_minus_before": after_value - before_value})

    before_names = pd.read_csv(before_dir / "special_name_compare.csv")
    after_names = pd.read_csv(after_dir / "special_name_compare.csv")
    for role, name in [("投手", "球持ち○"), ("野手", "併殺"), ("野手", "内野安打○")]:
        before = before_names[(before_names["role"].eq(role)) & before_names["special"].eq(name)].iloc[0]
        after = after_names[(after_names["role"].eq(role)) & after_names["special"].eq(name)].iloc[0]
        real = after["real_holder_rate_pct"]
        before_value = before["generated_holder_rate_pct"]
        after_value = after["generated_holder_rate_pct"]
        rows.append({"type": "normal", "role": role, "name": name, "real_rate": real, "before_rate": before_value, "after_rate": after_value, "before_diff": before_value - real, "after_diff": after_value - real, "after_minus_before": after_value - before_value})
    return pd.DataFrame(rows)


def main() -> int:
    args = parse_args()
    before = load_generated(args.before_dir)
    after = load_generated(args.after_dir)
    real, _, _, audit = load_real(args.real_xlsx)
    if (audit["total"], audit["pitchers"], audit["fielders"]) != (791, 402, 389):
        raise SystemExit(f"実在人数が想定外です: {audit}")
    for column in [*ABILITIES, "弾道", "スタミナ"]:
        real[column] = pd.to_numeric(real[column], errors="coerce")

    rows: list[dict[str, Any]] = []
    add_position_evidence(rows, "実在", real, False)
    add_position_evidence(rows, "before", before, False)
    add_position_evidence(rows, "after", after, True)
    add_second_base_joint(rows, "実在", real, False)
    add_second_base_joint(rows, "before", before, False)
    add_second_base_joint(rows, "after", after, True)
    add_trajectory(rows, "実在", real, False)
    add_trajectory(rows, "before", before, False)
    add_trajectory(rows, "after", after, True)

    evidence = pd.DataFrame(rows)
    evidence.to_csv(args.after_dir / "second_adjustment_distribution_evidence.csv", index=False, encoding="utf-8-sig")
    stamina_evidence(args.before_dir, args.after_dir).to_csv(args.after_dir / "second_adjustment_stamina_evidence.csv", index=False, encoding="utf-8-sig")
    special_evidence(args.before_dir, args.after_dir).to_csv(args.after_dir / "second_adjustment_special_evidence.csv", index=False, encoding="utf-8-sig")
    print(f"分布証拠: {len(evidence)}行")
    print("スタミナ証拠: 32行")
    print("特殊能力証拠: 6行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
