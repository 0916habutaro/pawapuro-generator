from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402


DEFAULT_OUTPUT = ROOT / "reports" / "breaking_ball_final"
DEFAULT_SEEDS = [202609270001, 202619270001, 202629270001]
PROTECTED_FIELDS = [
    "age", "pro_years", "growth_type", "player_class", "archetype",
    "weakness_profile", "position", "batting_throwing",
    "starter_aptitude", "reliever_aptitude", "closer_aptitude",
]
FOCUS_SPECIALS = ["球持ち○", "リリース○", "奪三振", "四球", "キレ○"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="変化球Phase 1～4の保護対象能力を同一seedで監査")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count-per-seed", type=int, default=1_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    return parser.parse_args()


def ability_value(player: dict[str, Any], key: str) -> int:
    if key == "球速":
        return int(app.pitcher_speed_value(player["abilities"]) or 0)
    return int(app.ability_numeric_value(player["abilities"], key) or 0)


def generate_pair(master: app.MasterData, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    original = (
        app.PHASE2_PITCH_COUNT_ENABLED,
        app.PHASE3_DIRECTION_SETS_ENABLED,
        app.PHASE4_SECONDARY_SLOTS_ENABLED,
    )
    try:
        app.PHASE2_PITCH_COUNT_ENABLED = False
        app.PHASE3_DIRECTION_SETS_ENABLED = False
        app.PHASE4_SECONDARY_SLOTS_ENABLED = False
        protected = app.generate_player("投手", "架空球団用", master, seed)
        app.PHASE2_PITCH_COUNT_ENABLED = True
        app.PHASE3_DIRECTION_SETS_ENABLED = True
        app.PHASE4_SECONDARY_SLOTS_ENABLED = True
        final = app.generate_player("投手", "架空球団用", master, seed)
        return protected, final
    finally:
        (
            app.PHASE2_PITCH_COUNT_ENABLED,
            app.PHASE3_DIRECTION_SETS_ENABLED,
            app.PHASE4_SECONDARY_SLOTS_ENABLED,
        ) = original


def summarize_specials(players: list[dict[str, Any]], dataset: str) -> dict[str, Any]:
    counts = pd.Series([len(player["special_abilities"]) for player in players], dtype=float)
    row: dict[str, Any] = {
        "dataset": dataset,
        "sample": len(players),
        "average_special_count": round(float(counts.mean()), 5),
        "five_plus_rate_pct": round(float(counts.ge(5).mean() * 100), 5),
    }
    for name in FOCUS_SPECIALS:
        row[f"{name}_rate_pct"] = round(
            sum(name in player["special_abilities"] for player in players) / len(players) * 100,
            5,
        )
    return row


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    master = app.load_master_data()
    protected_players: list[dict[str, Any]] = []
    final_players: list[dict[str, Any]] = []
    mismatch_counts = Counter()
    for base_seed in args.seeds:
        print(f"seed_{base_seed}: 保護対象ペア監査 {args.count_per_seed:,}投手", flush=True)
        for offset in range(args.count_per_seed):
            protected, final = generate_pair(master, base_seed + offset)
            protected_players.append(protected)
            final_players.append(final)
            for field in PROTECTED_FIELDS:
                if protected.get(field) != final.get(field):
                    mismatch_counts[field] += 1
            for ability in ["球速", "コントロール", "スタミナ"]:
                if ability_value(protected, ability) != ability_value(final, ability):
                    mismatch_counts[ability] += 1

    sample = len(final_players)
    mismatch = pd.DataFrame([
        {
            "metric": field,
            "mismatch_count": mismatch_counts[field],
            "sample": sample,
            "mismatch_rate_pct": round(mismatch_counts[field] / sample * 100, 5),
            "passed": mismatch_counts[field] == 0,
        }
        for field in PROTECTED_FIELDS
    ])

    ability_rows = []
    for ability in ["球速", "コントロール", "スタミナ"]:
        protected_values = pd.Series([ability_value(player, ability) for player in protected_players], dtype=float)
        final_values = pd.Series([ability_value(player, ability) for player in final_players], dtype=float)
        mean_change = float(final_values.mean() - protected_values.mean())
        ability_rows.append({
            "metric": ability,
            "protected_mean": round(float(protected_values.mean()), 5),
            "final_mean": round(float(final_values.mean()), 5),
            "mean_change": round(mean_change, 5),
            "mismatch_count": mismatch_counts[ability],
            "mismatch_rate_pct": round(mismatch_counts[ability] / sample * 100, 5),
            "tolerance_mean": 0.10,
            "passed": abs(mean_change) <= 0.10,
        })
    ability_guard = pd.DataFrame(ability_rows)

    distribution_rows = []
    for field in ["age", "growth_type", "player_class", "archetype", "weakness_profile", "position"]:
        protected_counts = Counter(str(player.get(field, "")) for player in protected_players)
        final_counts = Counter(str(player.get(field, "")) for player in final_players)
        for value in sorted(set(protected_counts) | set(final_counts)):
            before_rate = protected_counts[value] / sample * 100
            after_rate = final_counts[value] / sample * 100
            distribution_rows.append({
                "metric": field,
                "value": value,
                "protected_rate_pct": round(before_rate, 5),
                "final_rate_pct": round(after_rate, 5),
                "absolute_change_pt": round(abs(after_rate - before_rate), 5),
            })
    distributions = pd.DataFrame(distribution_rows)

    special = pd.DataFrame([
        summarize_specials(protected_players, "PR #76保護対照"),
        summarize_specials(final_players, "Phase 4最終"),
    ])
    before = special.iloc[0]
    after = special.iloc[1]
    guard_rows = []
    for column in ["average_special_count", "five_plus_rate_pct", *[f"{name}_rate_pct" for name in FOCUS_SPECIALS]]:
        tolerance = 0.10 if column == "average_special_count" else 2.0
        change = float(after[column] - before[column])
        guard_rows.append({
            "metric": column,
            "protected": before[column],
            "final": after[column],
            "change": round(change, 5),
            "tolerance": tolerance,
            "passed": abs(change) <= tolerance,
        })
    guards = pd.DataFrame(guard_rows)

    csv_options = {"index": False, "encoding": "utf-8-sig", "lineterminator": "\n"}
    mismatch.to_csv(args.output_dir / "protected_attribute_mismatches.csv", **csv_options)
    ability_guard.to_csv(args.output_dir / "protected_ability_guard.csv", **csv_options)
    distributions.to_csv(args.output_dir / "protected_distribution_guard.csv", **csv_options)
    special.to_csv(args.output_dir / "protected_special_metrics.csv", **csv_options)
    guards.to_csv(args.output_dir / "protected_special_guard.csv", **csv_options)
    print({
        "sample": sample,
        "attribute_mismatches": int(mismatch["mismatch_count"].sum()),
        "ability_guards": f"{int(ability_guard['passed'].sum())}/{len(ability_guard)}",
        "max_distribution_change_pt": float(distributions["absolute_change_pt"].max()),
        "special_guards": f"{int(guards['passed'].sum())}/{len(guards)}",
    })
    return 0 if mismatch["passed"].all() and ability_guard["passed"].all() and guards["passed"].all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
