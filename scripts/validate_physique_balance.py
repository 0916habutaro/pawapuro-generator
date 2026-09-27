from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CATEGORIES,
    POSITION_PHYSIQUE,
    ability_numeric_value,
    generate_player,
    load_master_data,
    pitcher_speed_value,
)

DEFAULT_SEEDS = [202607090000, 202707090000, 202807090000]
FIELDER_KEYS = ["弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
PITCHER_KEYS = ["球速", "コントロール", "スタミナ"]
QUANTILES = [(0.05, "P5"), (0.25, "P25"), (0.50, "P50"), (0.75, "P75"), (0.95, "P95")]
REAL_SD = {
    "投手": (6.41, 8.92), "捕手": (4.36, 6.78), "一塁手": (6.61, 11.37),
    "二塁手": (5.41, 8.38), "三塁手": (5.37, 10.98), "遊撃手": (5.39, 7.28), "外野手": (6.01, 10.06),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="体格生成と能力補正を60,000人で検証します。")
    parser.add_argument("--count-per-role", type=int, default=10_000, help="各seed・役割の生成数")
    parser.add_argument("--seeds", nargs=3, type=int, default=DEFAULT_SEEDS, help="カテゴリごとの開始seed 3件")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "physique_balance")
    return parser.parse_args()


def ability_value(player: dict, key: str) -> int | float | None:
    return pitcher_speed_value(player["abilities"]) if key == "球速" else ability_numeric_value(player["abilities"], key)


def flatten_pair(player: dict, baseline: dict, seed_group: int) -> dict:
    position = "投手" if player["role"] == "投手" else player["position"]
    row = {
        "seed_group": seed_group, "seed": player["seed"], "category": player["category"],
        "role": player["role"], "position": position, "height_cm": player["height_cm"], "weight_kg": player["weight_kg"],
    }
    row["BMI"] = player["weight_kg"] / (player["height_cm"] / 100) ** 2
    keys = PITCHER_KEYS if player["role"] == "投手" else FIELDER_KEYS
    for key in keys:
        row[f"after_{key}"] = ability_value(player, key)
        row[f"before_{key}"] = ability_value(baseline, key)
    return row


def generate_validation_rows(count: int, seeds: list[int]) -> pd.DataFrame:
    master = load_master_data()
    rows: list[dict] = []
    for seed_group, (base_seed, category) in enumerate(zip(seeds, CATEGORIES), start=1):
        for role_offset, role in enumerate(("投手", "野手")):
            print(f"seed {seed_group} / {category} / {role}: {count:,}人", flush=True)
            start = base_seed + role_offset * count
            for index in range(count):
                seed = start + index
                player = generate_player(role, category, master, seed=seed, include_physique_baseline=True)
                baseline = {"abilities": player["_baseline_abilities"]}
                rows.append(flatten_pair(player, baseline, seed_group))
    return pd.DataFrame(rows)


def physique_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for position, group in df.groupby("position", sort=False):
        rows.append({
            "position": position, "count": len(group),
            "height_mean": group["height_cm"].mean(), "height_sd": group["height_cm"].std(ddof=0),
            "height_min": group["height_cm"].min(), "height_max": group["height_cm"].max(),
            "weight_mean": group["weight_kg"].mean(), "weight_sd": group["weight_kg"].std(ddof=0),
            "weight_min": group["weight_kg"].min(), "weight_max": group["weight_kg"].max(),
            "bmi_mean": group["BMI"].mean(),
        })
    return pd.DataFrame(rows).round(3)


def ability_comparison(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role, keys in (("野手", FIELDER_KEYS), ("投手", PITCHER_KEYS)):
        target = df[df["role"] == role]
        for key in keys:
            for phase in ("before", "after"):
                values = pd.to_numeric(target[f"{phase}_{key}"], errors="coerce").dropna()
                row = {"role": role, "ability": key, "phase": phase, "mean": values.mean(), "sd": values.std(ddof=0)}
                row.update({label: values.quantile(q) for q, label in QUANTILES})
                rows.append(row)
    return pd.DataFrame(rows).round(3)


def correlations(df: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("野手", "weight_kg", "after_パワー"), ("野手", "weight_kg", "after_走力"),
        ("野手", "weight_kg", "after_守備力"), ("投手", "height_cm", "after_球速"),
        ("投手", "weight_kg", "after_球速"),
    ]
    rows = []
    for role, left, right in specs:
        target = df[df["role"] == role]
        rows.append({"role": role, "pair": f"{left} × {right.removeprefix('after_')}", "correlation": target[left].corr(target[right])})
    return pd.DataFrame(rows).round(4)


def seed_summary(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["seed_group", "role"], as_index=False).agg(
        count=("seed", "size"), height_mean=("height_cm", "mean"), weight_mean=("weight_kg", "mean")
    ).round(3)


def warnings_table(physique: pd.DataFrame, corr: pd.DataFrame, abilities: pd.DataFrame) -> pd.DataFrame:
    warnings: list[dict[str, str]] = []
    for row in physique.to_dict("records"):
        params = POSITION_PHYSIQUE[row["position"]]
        real_height_sd, real_weight_sd = REAL_SD[row["position"]]
        checks = [
            (abs(row["height_mean"] - params["height_mean"]) > 1.0, "平均身長差 > 1.0cm"),
            (abs(row["weight_mean"] - params["weight_mean"]) > 1.5, "平均体重差 > 1.5kg"),
            (abs(row["height_sd"] - real_height_sd) / real_height_sd > 0.20, "身長SD差 > 20%"),
            (abs(row["weight_sd"] - real_weight_sd) / real_weight_sd > 0.20, "体重SD差 > 20%"),
        ]
        warnings.extend({"scope": row["position"], "warning": message} for failed, message in checks if failed)
    expected_sign = [1, -1, -1, 1, 1]
    for row, sign in zip(corr.to_dict("records"), expected_sign):
        value = row["correlation"]
        if value * sign <= 0:
            warnings.append({"scope": row["pair"], "warning": "相関方向が期待と逆"})
        if abs(value) > 0.65:
            warnings.append({"scope": row["pair"], "warning": "相関が強すぎる可能性"})
    pivot = abilities.pivot(index=["role", "ability"], columns="phase", values="mean")
    for (role, ability), row in pivot.iterrows():
        if ability in {"ミート", "スタミナ"} and abs(row["after"] - row["before"]) > 0.05:
            warnings.append({"scope": f"{role}/{ability}", "warning": "非補正能力の平均差 > 0.05"})
    return pd.DataFrame(warnings, columns=["scope", "warning"])


def main() -> None:
    args = parse_args()
    df = generate_validation_rows(args.count_per_role, args.seeds)
    physique = physique_summary(df)
    abilities = ability_comparison(df)
    corr = correlations(df)
    seeds = seed_summary(df)
    warnings = warnings_table(physique, corr, abilities)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in {
        "physique_summary.csv": physique, "ability_before_after.csv": abilities,
        "physique_correlations.csv": corr, "seed_summary.csv": seeds, "warnings.csv": warnings,
    }.items():
        table.to_csv(args.output_dir / name, index=False, encoding="utf-8-sig")
    print(f"完了: {len(df):,}人 / warning {len(warnings)}件 / 出力先 {args.output_dir}")
    print(corr.to_string(index=False))


if __name__ == "__main__":
    main()
