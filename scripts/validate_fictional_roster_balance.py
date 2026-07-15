#!/usr/bin/env python3
"""架空球団用ロスターの能力・特殊能力バランスを検証する簡易スクリプト。"""
from __future__ import annotations

import argparse, collections, statistics
from typing import Any
import app

FIELDER_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]

def ability_value(abilities: dict[str, Any], key: str) -> int:
    value = abilities[key]
    if isinstance(value, dict):
        return int(value.get("value", 0))
    return int(str(value).split()[0])

def total_movement(player: dict[str, Any]) -> int:
    return sum(int(b.get("movement", 0) or 0) for b in player.get("breaking_balls", []) if b.get("kind") == "breaking" and not b.get("is_second_pitch"))

def pitcher_total(player: dict[str, Any]) -> int:
    balls = player.get("breaking_balls", [])
    primary = [b for b in balls if b.get("kind") == "breaking" and not b.get("is_second_pitch")]
    secondary = [b for b in balls if b.get("is_second_pitch")]
    second_fastball = [b for b in balls if b.get("kind") == "second_fastball"]
    abilities = player["abilities"]
    return ((ability_value(abilities, "球速") - 120) * 2 + ability_value(abilities, "コントロール") + ability_value(abilities, "スタミナ") + total_movement(player) * 8 + max(0, len(primary) - 1) * 4 + len(secondary) * 3 + len(second_fastball) * 2)

def fielder_total(player: dict[str, Any]) -> int:
    return sum(ability_value(player["abilities"], key) for key in FIELDER_KEYS)

def describe(values: list[float]) -> dict[str, float]:
    values = sorted(values)
    if not values:
        return {}
    return {"人数": len(values), "平均": round(statistics.mean(values), 3), "中央値": round(statistics.median(values), 3), "標準偏差": round(statistics.pstdev(values), 3), "最小": values[0], "最大": values[-1], "下位25%": values[len(values)//4], "上位25%": values[(len(values)*3)//4]}

def special_kind_counts(players: list[dict[str, Any]], master: app.MasterData) -> dict[str, float]:
    by_name = {str(r["name"]): r for r in master.abilities}
    out = collections.Counter()
    ranked_non_d = ranked_with_d = 0
    for p in players:
        for name in p.get("special_abilities", []):
            row = by_name.get(name, {})
            kind, power = row.get("kind"), row.get("power", "normal")
            if kind == "blue" and power == "strong": out["強青"] += 1
            elif kind == "blue": out["通常青"] += 1
            elif kind == "red": out["赤"] += 1
            elif kind == "mixed": out["混合"] += 1
            elif kind == "green" or name in app.PERSONALITY_SPECIALS: out["緑"] += 1
            elif kind == "gold": out["金"] += 1
        for name in (p.get("abilities", {}).get("ranked_specials", {}) or {}).values():
            ranked_with_d += 1
            if not str(name).endswith("D"):
                ranked_non_d += 1
    denom = max(1, len(players))
    return {**{k: round(v / denom, 3) for k, v in out.items()}, "ランク非D": round(ranked_non_d / denom, 3), "ランクD込み": round(ranked_with_d / denom, 3)}

def split_rosters(players: list[dict[str, Any]], role: str, roster_size: int) -> list[tuple[str, dict[str, Any], int]]:
    scored = []
    top_n = 16 if role == "野手" else 13
    key = fielder_total if role == "野手" else pitcher_total
    for roster_no, start in enumerate(range(0, len(players), roster_size), 1):
        roster = players[start:start + roster_size]
        sorted_roster = sorted(roster, key=key, reverse=True)
        first = set(id(p) for p in sorted_roster[:top_n])
        scored.extend(("一軍相当" if id(p) in first else "二軍相当", p, roster_no) for p in roster)
    return scored

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=10000)
    parser.add_argument("--rosters", type=int, default=100)
    parser.add_argument("--roster-size", type=int, default=70)
    args = parser.parse_args()
    master = app.load_master_data()
    for role, offset in [("投手", 1000000), ("野手", 2000000)]:
        players = [app.generate_player(role, "架空球団用", master, seed=offset + i) for i in range(args.players)]
        print(f"\n## {role} 大量生成 {len(players)}人")
        print("選手格", dict(collections.Counter(p["player_class"] for p in players)))
        scored = split_rosters(players[:args.rosters * args.roster_size], role, args.roster_size)
        for tier in ["一軍相当", "二軍相当"]:
            subset = [p for t, p, _ in scored if t == tier]
            total_key = fielder_total if role == "野手" else pitcher_total
            print(tier, describe([total_key(p) for p in subset]))
            if role == "野手":
                print({k: describe([ability_value(p["abilities"], k) for p in subset]) for k in FIELDER_KEYS})
                print("三振率", round(sum("三振" in p.get("special_abilities", []) for p in subset) / max(1, len(subset)), 3))
            else:
                print({k: describe([ability_value(p["abilities"], k) for p in subset]) for k in ["球速", "コントロール", "スタミナ"]})
                print("総変化量", describe([total_movement(p) for p in subset]))
                print("四球・荒れ球率", round(sum(any(n in p.get("special_abilities", []) for n in ["四球", "荒れ球"]) for p in subset) / max(1, len(subset)), 3))
            print("特殊能力分類", special_kind_counts(subset, master))
        roster_class_counts = [collections.Counter(p["player_class"] for p in players[i:i+args.roster_size]) for i in range(0, args.rosters * args.roster_size, args.roster_size)]
        print("球団別選手格最小最大", {klass: (min(c.get(klass, 0) for c in roster_class_counts), max(c.get(klass, 0) for c in roster_class_counts)) for klass, _ in app.PLAYER_CLASS_WEIGHTS["架空球団用"]})

if __name__ == "__main__":
    main()
