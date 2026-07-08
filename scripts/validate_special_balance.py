from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CATEGORIES,
    SPECIAL_KIND_LABELS,
    ability_numeric_value,
    generate_player,
    inappropriate_special_count,
    is_ranked_special,
    load_master_data,
    pitcher_speed_value,
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


def top_by_type(players, limit=10):
    by_type = defaultdict(Counter)
    for p in players:
        for name in p["special_abilities"]:
            by_type[(p["role"], p["player_type"])][name] += 1
    return {k: v.most_common(limit) for k, v in sorted(by_type.items())}


def condition_counts(players):
    conditions = {
        "パワー70以上": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "パワー") or 0) >= 70,
        "パワー55未満": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "パワー") or 99) < 55,
        "ミート70以上": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "ミート") or 0) >= 70,
        "ミート55未満": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "ミート") or 99) < 55,
        "走力70以上": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "走力") or 0) >= 70,
        "走力55未満": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "走力") or 99) < 55,
        "守備力70以上": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "守備力") or 0) >= 70,
        "守備力55未満": lambda p: p["role"] == "野手" and (ability_numeric_value(p["abilities"], "守備力") or 99) < 55,
        "球速150以上": lambda p: p["role"] == "投手" and (pitcher_speed_value(p["abilities"]) or 0) >= 150,
        "球速145未満": lambda p: p["role"] == "投手" and (pitcher_speed_value(p["abilities"]) or 999) < 145,
        "コントロール70以上": lambda p: p["role"] == "投手" and (ability_numeric_value(p["abilities"], "コントロール") or 0) >= 70,
        "コントロール45未満": lambda p: p["role"] == "投手" and (ability_numeric_value(p["abilities"], "コントロール") or 99) < 45,
    }
    result = {}
    for label, pred in conditions.items():
        subset = [p for p in players if pred(p)]
        c = Counter(name for p in subset for name in p["special_abilities"])
        result[label] = {"players": len(subset), "top": c.most_common(10)}
    return result


def main():
    master = load_master_data()
    players = generate_samples(master)
    normal_counts = Counter(name for p in players for name in p["special_abilities"])
    kind_by_name = kind_label_by_name(master)
    kind_counts = Counter(kind_by_name.get(name, "不明") for p in players for name in p["special_abilities"])
    ranked_names = {row["name"] for row in master.abilities if is_ranked_special(row)}
    role_by_name = {row["name"]: special_target_role(row) for row in master.abilities}
    ranked_mix = sum(1 for p in players for name in p["special_abilities"] if name in ranked_names)
    role_mix = sum(1 for p in players for name in p["special_abilities"] if role_by_name.get(name) not in (p["role"], "共通"))
    group_by_name = {row["name"]: row["group"] for row in master.abilities}
    group_dup = 0
    for p in players:
        groups = [group_by_name.get(name) for name in p["special_abilities"]]
        group_dup += len(groups) - len(set(groups))

    print(f"players={len(players)} pitchers={SAMPLE_PER_ROLE} fielders={SAMPLE_PER_ROLE}")
    print(f"normal_avg={sum(len(p['special_abilities']) for p in players) / len(players):.3f}")
    print(f"ranked_avg={sum(len(p['abilities'].get('ranked_specials', {})) for p in players) / len(players):.3f}")
    print(f"kind_counts={dict(kind_counts)}")
    print(f"top30={normal_counts.most_common(30)}")
    print(f"bottom30={normal_counts.most_common()[:-31:-1]}")
    print(f"ranked_mix={ranked_mix}")
    print(f"role_mix={role_mix}")
    print(f"group_dup={group_dup}")
    print(f"inappropriate_count={inappropriate_special_count(__import__('pandas').DataFrame(players), master)}")
    print("type_top=")
    for key, values in top_by_type(players).items():
        print(f"  {key}: {values}")
    print("condition_top=")
    for key, values in condition_counts(players).items():
        print(f"  {key} ({values['players']}): {values['top']}")
    ok = 1.5 <= sum(len(p['special_abilities']) for p in players) / len(players) <= 2.2 and ranked_mix == 0 and role_mix == 0 and group_dup == 0
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
