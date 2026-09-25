from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    ability_numeric_value,
    generate_player,
    load_master_data,
    pitch_movement,
    pitcher_speed_value,
)


AGE_DISTRIBUTION_BANDS = [
    ("18～19歳", 18, 19),
    ("20～22歳", 20, 22),
    ("23～26歳", 23, 26),
    ("27～30歳", 27, 30),
    ("31～34歳", 31, 34),
    ("35～36歳", 35, 36),
    ("37～39歳", 37, 39),
    ("40歳以上", 40, None),
]
ABILITY_AGE_BANDS = [
    ("18～19歳", 18, 19),
    ("20～22歳", 20, 22),
    ("23～26歳", 23, 26),
    ("27～30歳", 27, 30),
    ("31～34歳", 31, 34),
    ("35歳以上", 35, None),
]
FIELDER_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
PITCHER_KEYS = ["球速", "コントロール", "スタミナ", "総変化量", "球種数"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="架空球団用の年齢分布と年齢帯別能力を検証します。")
    parser.add_argument("--count", type=int, default=10_000, help="投手・野手それぞれの生成人数")
    parser.add_argument("--seed", type=int, default=202_609_250_000, help="検証用の開始seed")
    parser.add_argument("--output", type=Path, help="JSONの保存先（未指定時は標準出力のみ）")
    return parser.parse_args()


def age_band(age: int, bands: list[tuple[str, int, int | None]]) -> str:
    for label, low, high in bands:
        if age >= low and (high is None or age <= high):
            return label
    return "対象外"


def pitcher_metrics(player: dict[str, Any]) -> dict[str, float]:
    abilities = player["abilities"]
    primary = [
        ball
        for ball in player.get("breaking_balls", [])
        if ball.get("kind", "breaking") == "breaking" and not bool(ball.get("is_second_pitch", False))
    ]
    return {
        "球速": float(pitcher_speed_value(abilities) or 0),
        "コントロール": float(ability_numeric_value(abilities, "コントロール") or 0),
        "スタミナ": float(ability_numeric_value(abilities, "スタミナ") or 0),
        "総変化量": float(sum(pitch_movement(ball) for ball in primary)),
        "球種数": float(len(primary)),
    }


def fielder_metrics(player: dict[str, Any]) -> dict[str, float]:
    abilities = player["abilities"]
    return {key: float(ability_numeric_value(abilities, key) or 0) for key in FIELDER_KEYS}


def validate(count: int, base_seed: int) -> dict[str, Any]:
    if count < 10_000:
        print("警告: 依頼条件の大量生成検証では --count 10000 以上を指定してください。", file=sys.stderr)
    master = load_master_data()
    distribution: dict[str, Counter[str]] = {role: Counter() for role in ("投手", "野手")}
    ability_sums: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    ability_counts: Counter[tuple[str, str]] = Counter()
    growth_counts: dict[str, Counter[str]] = defaultdict(Counter)
    veteran_counts: dict[str, dict[str, Counter[str]]] = {
        key: defaultdict(Counter) for key in ("player_class", "archetype", "growth_type", "pitcher_role")
    }
    checks = Counter()

    for role_index, role in enumerate(("投手", "野手")):
        print(f"{role} / 架空球団用: {count:,}人生成中", flush=True)
        for offset in range(count):
            seed = base_seed + role_index * count + offset
            player = generate_player(role, "架空球団用", master, seed=seed)
            age = int(player["age"])
            distribution[role][age_band(age, AGE_DISTRIBUTION_BANDS)] += 1
            ability_label = age_band(age, ABILITY_AGE_BANDS)
            metrics = fielder_metrics(player) if role == "野手" else pitcher_metrics(player)
            ability_counts[(role, ability_label)] += 1
            for key, value in metrics.items():
                ability_sums[(role, ability_label)][key] += value
            growth_counts[ability_label][str(player.get("growth_type", "normal"))] += 1
            if age >= 35:
                veteran_counts["player_class"][role][str(player.get("player_class", ""))] += 1
                veteran_counts["archetype"][role][str(player.get("archetype", ""))] += 1
                veteran_counts["growth_type"][role][str(player.get("growth_type", "normal"))] += 1
                if role == "投手":
                    veteran_counts["pitcher_role"][role][str(player.get("position", ""))] += 1

            if role == "野手" and age <= 19:
                checks["18～19歳野手"] += 1
                if any(metrics[key] >= 80 for key in FIELDER_KEYS):
                    checks["18～19歳野手_A以上あり"] += 1
            if role == "野手" and age >= 35:
                checks["35歳以上野手"] += 1
                if metrics["走力"] >= 50:
                    checks["35歳以上野手_走力50以上"] += 1
                if player.get("player_class") == "ベテラン型" and metrics["ミート"] >= 50:
                    checks["35歳以上ベテラン野手_ミート50以上"] += 1
            if role == "投手" and metrics["球速"] >= 160:
                checks["投手160km_h以上"] += 1
            if role == "投手":
                checks["投手"] += 1

    distribution_rows = []
    for role in ("投手", "野手"):
        for label, _, _ in AGE_DISTRIBUTION_BANDS:
            people = distribution[role][label]
            distribution_rows.append({"対象": role, "年齢帯": label, "人数": people, "割合%": round(people / count * 100, 2)})

    ability_rows = []
    for role, keys in (("野手", FIELDER_KEYS), ("投手", PITCHER_KEYS)):
        for label, _, _ in ABILITY_AGE_BANDS:
            people = ability_counts[(role, label)]
            row: dict[str, Any] = {"対象": role, "年齢帯": label, "人数": people}
            for key in keys:
                row[key] = round(ability_sums[(role, label)][key] / people, 2) if people else None
            ability_rows.append(row)

    growth_rows = []
    for label, _, _ in ABILITY_AGE_BANDS:
        total = sum(growth_counts[label].values())
        row = {"年齢帯": label, "人数": total}
        for growth_type in ("very_early", "early", "normal", "late", "very_late"):
            row[growth_type] = round(growth_counts[label][growth_type] / total * 100, 2) if total else None
        growth_rows.append(row)

    check_rates = {
        "18～19歳野手_A以上能力所持率%": round(checks["18～19歳野手_A以上あり"] / max(1, checks["18～19歳野手"]) * 100, 2),
        "35歳以上野手_走力50以上率%": round(checks["35歳以上野手_走力50以上"] / max(1, checks["35歳以上野手"]) * 100, 2),
        "投手160km_h以上率%": round(checks["投手160km_h以上"] / max(1, checks["投手"]) * 100, 3),
    }

    veteran_distribution_rows: dict[str, list[dict[str, Any]]] = {}
    for dimension, role_counts in veteran_counts.items():
        rows = []
        for role, counts in role_counts.items():
            total = sum(counts.values())
            for label, people in sorted(counts.items()):
                rows.append({"対象": role, "分類": label, "人数": people, "割合%": round(people / max(1, total) * 100, 2)})
        veteran_distribution_rows[dimension] = rows
    return {
        "count_per_role": count,
        "base_seed": base_seed,
        "age_distribution": distribution_rows,
        "age_ability_averages": ability_rows,
        "growth_type_distribution": growth_rows,
        "veteran_distributions": veteran_distribution_rows,
        "regression_rates": check_rates,
    }


def main() -> None:
    args = parse_args()
    report = validate(args.count, args.seed)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"出力先: {args.output}")
    print(rendered)


if __name__ == "__main__":
    main()
