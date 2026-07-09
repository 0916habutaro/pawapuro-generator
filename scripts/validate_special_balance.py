from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CATEGORIES,
    PERSONALITY_SPECIALS,
    SPECIAL_KIND_LABELS,
    STRONG_SPECIALS,
    ability_numeric_value,
    generate_player,
    inappropriate_special_count,
    is_ranked_special,
    load_master_data,
    pitcher_speed_value,
    special_count_bucket,
    special_target_role,
)

SAMPLE_PER_ROLE = 5000


def kind_label_by_name(master):
    return {row["name"]: SPECIAL_KIND_LABELS.get(row.get("kind"), "不明") for row in master.abilities if not is_ranked_special(row)}


def generate_samples(master):
    players = []
    seed = 202607080000
    for role in ("投手", "野手"):
        for i in range(SAMPLE_PER_ROLE):
            category = CATEGORIES[i % len(CATEGORIES)]
            players.append(generate_player(role, category, master, seed + len(players)))
    return players


def distribution(players):
    counts = Counter(special_count_bucket(p["special_abilities"]) for p in players)
    return {label: counts.get(label, 0) for label in ["0個", "1個", "2個", "3個", "4個", "5個", "6個以上"]}


def grouped_distribution(players, key):
    result = {}
    for value in sorted({key(p) for p in players}):
        result[value] = distribution([p for p in players if key(p) == value])
    return result


def grouped_average(players, key):
    return {value: round(sum(len(p["special_abilities"]) for p in subset) / len(subset), 3) for value in sorted({key(p) for p in players}) if (subset := [p for p in players if key(p) == value])}


def special_rate(players, label, predicate, special_name):
    subset = [p for p in players if predicate(p)]
    hits = sum(1 for p in subset if special_name in p["special_abilities"])
    rate = hits / len(subset) * 100 if subset else 0.0
    return {"label": label, "players": len(subset), "hits": hits, "rate": rate}


def targeted_special_rates(players):
    return [
        special_rate(players, "ミート55未満", lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "ミート") or 99) < 55, "三振"),
        special_rate(players, "ミート65以上", lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "ミート") or 0) >= 65, "三振"),
        special_rate(players, "コントロール45未満", lambda p: p["role"] == "投手" and (ability_numeric_value(p["abilities"], "コントロール") or 99) < 45, "荒れ球"),
        special_rate(players, "コントロール60以上", lambda p: p["role"] == "投手" and (ability_numeric_value(p["abilities"], "コントロール") or 0) >= 60, "荒れ球"),
    ]


def main():
    master = load_master_data()
    players = generate_samples(master)
    normal_counts = Counter(name for p in players for name in p["special_abilities"])
    kind_by_name = kind_label_by_name(master)
    kind_counts = Counter(kind_by_name.get(name, "不明") for p in players for name in p["special_abilities"])
    total_specials = sum(kind_counts.values()) or 1
    ranked_names = {row["name"] for row in master.abilities if is_ranked_special(row)}
    role_by_name = {row["name"]: special_target_role(row) for row in master.abilities}
    group_by_name = {row["name"]: row["group"] for row in master.abilities}
    ranked_mix = sum(1 for p in players for name in p["special_abilities"] if name in ranked_names)
    role_mix = sum(1 for p in players for name in p["special_abilities"] if role_by_name.get(name) not in (p["role"], "共通"))
    group_dup = 0
    for p in players:
        groups = [group_by_name.get(name) for name in p["special_abilities"]]
        group_dup += len(groups) - len(set(groups))

    normal_avg = sum(len(p["special_abilities"]) for p in players) / len(players)
    ranked_avg = sum(len(p["abilities"].get("ranked_specials", {})) for p in players) / len(players)
    ranked_values = [name for p in players for name in p["abilities"].get("ranked_specials", {}).values()]
    ranked_non_d_avg = sum(1 for name in ranked_values if not str(name).endswith("D")) / len(players)
    ranked_non_d_distribution = Counter(str(name)[-1] for name in ranked_values if str(name)[-1] in {"A", "B", "C", "E", "F", "G"})
    max_normal = max(len(p["special_abilities"]) for p in players)
    six_plus = sum(1 for p in players if len(p["special_abilities"]) >= 6)
    strong_count = sum(normal_counts.get(name, 0) for name in STRONG_SPECIALS)
    strong_counts = {name: normal_counts.get(name, 0) for name in sorted(STRONG_SPECIALS)}
    red_top = Counter(name for p in players for name in p["special_abilities"] if kind_by_name.get(name) == "赤特")
    green_top = Counter(name for p in players for name in p["special_abilities"] if kind_by_name.get(name) == "緑特")
    personality_count = sum(normal_counts.get(name, 0) for name in PERSONALITY_SPECIALS)

    print(f"players={len(players)} pitchers={SAMPLE_PER_ROLE} fielders={SAMPLE_PER_ROLE}")
    print(f"normal_avg={normal_avg:.3f}")
    print(f"ranked_avg={ranked_avg:.3f}")
    print(f"ranked_non_d_avg={ranked_non_d_avg:.3f}")
    print(f"ranked_non_d_distribution={dict(sorted(ranked_non_d_distribution.items()))}")
    print(f"normal_distribution={distribution(players)}")
    print(f"six_plus_players={six_plus}")
    print(f"max_normal_count={max_normal}")
    print(f"category_avg={grouped_average(players, lambda p: p['category'])}")
    print(f"category_distribution={grouped_distribution(players, lambda p: p['category'])}")
    print(f"role_distribution={grouped_distribution(players, lambda p: p['role'])}")
    print(f"type_avg={grouped_average(players, lambda p: f'{p['role']}:{p['player_type']}')}")
    kind_rates = {k: round(v / total_specials * 100, 2) for k, v in kind_counts.items()}
    red_rate = kind_rates.get("赤特", 0.0)
    mixed_rate = kind_rates.get("青赤特", 0.0)
    green_rate = kind_rates.get("緑特", 0.0)
    print(f"kind_rate={kind_rates} counts={dict(kind_counts)}")
    print(f"top30={normal_counts.most_common(30)}")
    print(f"red_top={red_top.most_common(20)}")
    print(f"green_top={green_top.most_common(20)}")
    print(f"personality_count={personality_count}")
    print(f"strong_count={strong_count} counts={strong_counts}")
    print("target_rates=")
    for values in targeted_special_rates(players):
        print(f"  {values['label']}: {values['hits']}/{values['players']} ({values['rate']:.2f}%)")
    print(f"ranked_mix={ranked_mix}")
    print(f"role_mix={role_mix}")
    print(f"group_dup={group_dup}")
    print(f"inappropriate_count={inappropriate_special_count(pd.DataFrame(players), master)}")
    ok = (
        2.0 <= normal_avg <= 2.3
        and 12.0 <= red_rate <= 16.0
        and 5.0 <= mixed_rate <= 7.0
        and 8.0 <= green_rate <= 13.0
        and 3.2 <= ranked_non_d_avg <= 3.8
        and ranked_mix == 0
        and role_mix == 0
        and group_dup == 0
        and max_normal <= 12
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
