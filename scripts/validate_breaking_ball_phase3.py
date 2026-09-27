from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts import analyze_breaking_ball_structure as phase0  # noqa: E402


REAL = "実在"
BEFORE = "Phase 3前"
DEFAULT_REAL = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"
DEFAULT_OUTPUT = ROOT / "reports" / "breaking_ball_phase3_direction_sets"
DEFAULT_SEEDS = [202609270001, 202619270001, 202629270001]
ALL_DIRECTION_SETS = {
    size: ["+".join(values) for values in __import__("itertools").combinations("12345", size)]
    for size in (2, 3)
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 方向セットのbaseline・before/after検証")
    parser.add_argument("--mode", choices=["baseline"], default="baseline")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count-per-seed", type=int, default=10_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    return parser.parse_args()


def compact(player: dict[str, Any], dataset: str, run: str) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "run": run,
        "player_id": f"{dataset}:{run}:{player['seed']}",
        "name": player["name"],
        "age": player["age"],
        "pro_years": player.get("pro_years"),
        "pitcher_role": player["position"],
        "hand": phase0.hand(player["batting_throwing"]),
        "balls": player["breaking_balls"],
    }


def generate_current(count: int, seeds: list[int]) -> pd.DataFrame:
    master = app.load_master_data()
    rows: list[dict[str, Any]] = []
    for base_seed in seeds:
        run = f"seed_{base_seed}"
        print(f"{run}: Phase 2完成状態を{count:,}投手生成", flush=True)
        for offset in range(count):
            player = app.generate_player("投手", "架空球団用", master, base_seed + offset)
            rows.append(compact(player, BEFORE, run))
            if (offset + 1) % 2_000 == 0:
                print(f"  {offset + 1:,}/{count:,}", flush=True)
    return pd.DataFrame(rows)


def direction_by_hand(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE]:
        for hand in ["全体", "右投", "左投"]:
            frame = players[players["dataset"].eq(dataset)]
            if hand != "全体":
                frame = frame[frame["hand"].eq(hand)]
            for code in "12345":
                rows.append({
                    "dataset": dataset,
                    "hand": hand,
                    "direction_code": code,
                    "count": int(frame[f"has_direction_{code}"].sum()),
                    "sample": len(frame),
                    "rate_pct": phase0.pct(frame[f"has_direction_{code}"].mean()),
                })
    return pd.DataFrame(rows)


def direction_sets(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE]:
        for hand in ["全体", "右投", "左投"]:
            frame = players[players["dataset"].eq(dataset)]
            if hand != "全体":
                frame = frame[frame["hand"].eq(hand)]
            for size in (2, 3):
                subset = frame[frame["direction_set"].str.count(r"\+").add(1).eq(size)]
                counts = Counter(subset["direction_set"])
                for direction_set in ALL_DIRECTION_SETS[size]:
                    count = int(counts[direction_set])
                    rows.append({
                        "dataset": dataset,
                        "hand": hand,
                        "direction_count": size,
                        "direction_set": direction_set,
                        "count": count,
                        "sample_players": len(subset),
                        "rate_pct": phase0.pct(count / len(subset)) if len(subset) else float("nan"),
                    })
    return pd.DataFrame(rows)


def direction_by_hand_role(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE]:
        for hand in ["右投", "左投"]:
            for role in ["先発", "中継ぎ", "抑え"]:
                frame = players[
                    players["dataset"].eq(dataset)
                    & players["hand"].eq(hand)
                    & players["pitcher_role"].eq(role)
                ]
                row = {"dataset": dataset, "hand": hand, "pitcher_role": role, "sample": len(frame)}
                for code in "12345":
                    row[f"direction_{code}_rate_pct"] = phase0.pct(frame[f"has_direction_{code}"].mean())
                rows.append(row)
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, _breaking, audit = phase0.load_real(args.real_xlsx)
    real["run"] = "real"
    print(f"実在{audit['pitchers']}投手を読込", flush=True)
    before = generate_current(args.count_per_seed, args.seeds)
    players, _events = phase0.enrich(pd.concat([real, before], ignore_index=True))
    write_csv(direction_by_hand(players), args.output_dir / "baseline_direction_by_hand.csv")
    write_csv(direction_sets(players), args.output_dir / "baseline_direction_sets.csv")
    write_csv(direction_by_hand_role(players), args.output_dir / "baseline_direction_by_hand_role.csv")
    metadata = {
        "status": "baseline_complete",
        "generated_pitchers": len(before),
        "real_pitchers": len(real),
        "count_per_seed": args.count_per_seed,
        "seeds": args.seeds,
        "production_logic_changed_before_baseline": False,
    }
    (args.output_dir / "baseline_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
