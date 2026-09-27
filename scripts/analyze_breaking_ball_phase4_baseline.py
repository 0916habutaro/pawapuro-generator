from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts import analyze_breaking_ball_structure as phase0  # noqa: E402


REAL = "実在"
BEFORE = "Phase 4前"
DEFAULT_REAL = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"
DEFAULT_OUTPUT = ROOT / "reports" / "breaking_ball_phase4_secondary_slots"
DEFAULT_SEEDS = [202609270001, 202619270001, 202629270001]
COMPOSITIONS = ["primary_only", "second_breaking", "second_fastball", "both", "other"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4変更前のrepertoire composition再集計")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count-per-seed", type=int, default=10_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    return parser.parse_args()


def compact(player: dict[str, Any], dataset: str, run: str) -> dict[str, Any]:
    return {
        "dataset": dataset, "run": run,
        "player_id": f"{dataset}:{run}:{player['seed']}", "name": player["name"],
        "age": player["age"], "pro_years": player.get("pro_years"),
        "pitcher_role": player["position"], "hand": phase0.hand(player["batting_throwing"]),
        "balls": player["breaking_balls"],
    }


def generate_current(count: int, seeds: list[int]) -> pd.DataFrame:
    master = app.load_master_data()
    rows: list[dict[str, Any]] = []
    for base_seed in seeds:
        run = f"seed_{base_seed}"
        print(f"{run}: Phase 3完成状態を{count:,}投手生成", flush=True)
        for offset in range(count):
            player = app.generate_player("投手", "架空球団用", master, base_seed + offset)
            rows.append(compact(player, BEFORE, run))
            if (offset + 1) % 2_000 == 0:
                print(f"  {offset + 1:,}/{count:,}", flush=True)
    return pd.DataFrame(rows)


def classify_composition(row: pd.Series) -> str:
    if row["has_second"] and row["has_second_fastball"]:
        return "both"
    if row["has_second"]:
        return "second_breaking"
    if row["has_second_fastball"]:
        return "second_fastball"
    if row["second_count"] == 0 and row["second_fastball_count"] == 0:
        return "primary_only"
    return "other"


def enrich_composition(players: pd.DataFrame) -> pd.DataFrame:
    result = players.copy()
    result["composition"] = result.apply(classify_composition, axis=1)
    result["expected_total"] = result["primary_count"] + result["second_count"] + result["second_fastball_count"]
    result["composition_valid"] = result["expected_total"].eq(result["total_pitch_count"])
    return result


def composition_overall(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE]:
        frame = players[players["dataset"].eq(dataset)]
        for composition in COMPOSITIONS:
            count = int(frame["composition"].eq(composition).sum())
            rows.append({"dataset": dataset, "composition": composition, "count": count, "sample": len(frame), "rate_pct": phase0.pct(count / len(frame))})
    return pd.DataFrame(rows)


def composition_by_pitch_count(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE]:
        base = players[players["dataset"].eq(dataset)]
        for pitch_count in [2, 3, 4]:
            frame = base[base["total_pitch_count"].eq(pitch_count)]
            for composition in COMPOSITIONS:
                count = int(frame["composition"].eq(composition).sum())
                rows.append({
                    "dataset": dataset, "final_pitch_count": pitch_count,
                    "composition": composition, "count": count, "sample": len(frame),
                    "rate_pct": phase0.pct(count / len(frame)) if len(frame) else float("nan"),
                })
    return pd.DataFrame(rows)


def rates_by_axis(players: pd.DataFrame, axis: str, values: list[str]) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE]:
        base = players[players["dataset"].eq(dataset)]
        for value in values:
            frame = base[base[axis].eq(value)]
            rows.append({
                "dataset": dataset, axis: value, "sample": len(frame),
                "second_breaking_rate_pct": phase0.pct(frame["has_second"].mean()),
                "second_fastball_rate_pct": phase0.pct(frame["has_second_fastball"].mean()),
                "overlap_rate_pct": phase0.pct(frame["has_both"].mean()),
            })
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, _breaking, audit = phase0.load_real(args.real_xlsx)
    real["run"] = "real"
    before = generate_current(args.count_per_seed, args.seeds)
    players, _events = phase0.enrich(pd.concat([real, before], ignore_index=True))
    players = enrich_composition(players)
    write_csv(composition_overall(players), args.output_dir / "baseline_repertoire_composition.csv")
    write_csv(composition_by_pitch_count(players), args.output_dir / "baseline_repertoire_composition_by_pitch_count.csv")
    write_csv(rates_by_axis(players, "age_band", phase0.AGE_BANDS), args.output_dir / "baseline_secondary_rates_by_age.csv")
    write_csv(rates_by_axis(players, "pitcher_role", ["先発", "中継ぎ", "抑え"]), args.output_dir / "baseline_secondary_rates_by_role.csv")
    metadata = {
        "status": "baseline_complete", "real_pitchers": audit["pitchers"],
        "generated_pitchers": len(before), "seeds": args.seeds,
        "count_per_seed": args.count_per_seed,
        "invalid_composition_count": int((~players["composition_valid"]).sum()),
        "production_logic_changed_before_baseline": False,
    }
    (args.output_dir / "baseline_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
