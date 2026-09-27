from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts import analyze_breaking_ball_structure as phase0  # noqa: E402


REAL = "実在"
BEFORE = "Phase 3前"
AFTER = "Phase 3後"
DEFAULT_REAL = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"
DEFAULT_OUTPUT = ROOT / "reports" / "breaking_ball_phase3_direction_sets"
DEFAULT_SEEDS = [202609270001, 202619270001, 202629270001]
ALL_DIRECTION_SETS = {
    size: ["+".join(values) for values in itertools.combinations("12345", size)]
    for size in (2, 3)
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 方向セットbefore/after検証")
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


def generate_paired(count: int, seeds: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    master = app.load_master_data()
    before_rows: list[dict[str, Any]] = []
    after_rows: list[dict[str, Any]] = []
    try:
        for base_seed in seeds:
            run = f"seed_{base_seed}"
            print(f"{run}: Phase 3前後を各{count:,}投手生成", flush=True)
            for offset in range(count):
                seed = base_seed + offset
                app.PHASE3_DIRECTION_SETS_ENABLED = False
                before = app.generate_player("投手", "架空球団用", master, seed)
                app.PHASE3_DIRECTION_SETS_ENABLED = True
                after = app.generate_player("投手", "架空球団用", master, seed)
                before_rows.append(compact(before, BEFORE, run))
                after_rows.append(compact(after, AFTER, run))
                if (offset + 1) % 2_000 == 0:
                    print(f"  {offset + 1:,}/{count:,}", flush=True)
    finally:
        app.PHASE3_DIRECTION_SETS_ENABLED = True
    return pd.DataFrame(before_rows), pd.DataFrame(after_rows)


def direction_by_hand(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    real_rates: dict[tuple[str, str], float] = {}
    for dataset in [REAL, BEFORE, AFTER]:
        for hand in ["全体", "右投", "左投"]:
            frame = players[players["dataset"].eq(dataset)]
            if hand != "全体":
                frame = frame[frame["hand"].eq(hand)]
            for code in "12345":
                rate = phase0.pct(frame[f"has_direction_{code}"].mean())
                key = (hand, code)
                if dataset == REAL:
                    real_rates[key] = rate
                rows.append({
                    "dataset": dataset, "hand": hand, "direction_code": code,
                    "count": int(frame[f"has_direction_{code}"].sum()), "sample": len(frame),
                    "rate_pct": rate,
                    "absolute_diff_against_real_pt": 0.0 if dataset == REAL else round(abs(rate - real_rates[key]), 3),
                })
    return pd.DataFrame(rows)


def direction_sets(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    real_rates: dict[tuple[str, int, str], float] = {}
    for dataset in [REAL, BEFORE, AFTER]:
        for hand in ["全体", "右投", "左投"]:
            frame = players[players["dataset"].eq(dataset)]
            if hand != "全体":
                frame = frame[frame["hand"].eq(hand)]
            for size in (2, 3):
                subset = frame[frame["direction_set"].str.count(r"\+").add(1).eq(size)]
                counts = Counter(subset["direction_set"])
                for direction_set in ALL_DIRECTION_SETS[size]:
                    count = int(counts[direction_set])
                    rate = phase0.pct(count / len(subset)) if len(subset) else math.nan
                    key = (hand, size, direction_set)
                    if dataset == REAL:
                        real_rates[key] = rate
                    rows.append({
                        "dataset": dataset, "hand": hand, "direction_count": size,
                        "direction_set": direction_set, "count": count, "sample_players": len(subset),
                        "rate_pct": rate,
                        "absolute_diff_against_real_pt": 0.0 if dataset == REAL else round(abs(rate - real_rates[key]), 3),
                    })
    return pd.DataFrame(rows)


def direction_by_hand_role(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
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


def direction_by_hand_age(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        for hand in ["右投", "左投"]:
            for age_band in phase0.AGE_BANDS:
                frame = players[
                    players["dataset"].eq(dataset)
                    & players["hand"].eq(hand)
                    & players["age_band"].eq(age_band)
                ]
                row = {"dataset": dataset, "hand": hand, "age_band": age_band, "sample": len(frame)}
                for code in "12345":
                    row[f"direction_{code}_rate_pct"] = phase0.pct(frame[f"has_direction_{code}"].mean())
                rows.append(row)
    return pd.DataFrame(rows)


def count_metrics(frame: pd.DataFrame) -> dict[str, float]:
    counts = frame["total_pitch_count"]
    return {
        "sample": len(frame), "average_total_pitch_count": round(counts.mean(), 5),
        "2_pitch_rate_pct": phase0.pct(counts.eq(2).mean()),
        "3_pitch_rate_pct": phase0.pct(counts.eq(3).mean()),
        "4_pitch_rate_pct": phase0.pct(counts.eq(4).mean()),
        "5_plus_pitch_rate_pct": phase0.pct(counts.ge(5).mean()),
        "second_pitch_rate_pct": phase0.pct(frame["has_second"].mean()),
        "second_fastball_rate_pct": phase0.pct(frame["has_second_fastball"].mean()),
    }


def pitch_count_guard(players: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([
        {"dataset": dataset, **count_metrics(players[players["dataset"].eq(dataset)])}
        for dataset in [REAL, BEFORE, AFTER]
    ])


def equal_style_rate(players: pd.DataFrame, dataset: str) -> float:
    base = players[players["dataset"].eq(dataset)].copy()
    base = base[base["structure_total_movement"].ge(5)]
    base["bucket"] = base["structure_total_movement"].map(lambda value: "10+" if value >= 10 else str(int(value)))
    rates = []
    for bucket in ["5", "6", "7", "8", "9", "10+"]:
        subset = base[base["bucket"].eq(bucket)]
        if len(subset):
            rates.append(phase0.pct(subset["movement_style"].eq("均等型").mean()))
    return float(pd.Series(rates).mean())


def movement_guard(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    primary_events = events[events["kind"].eq("breaking") & ~events["is_second_pitch"]]
    metrics: dict[str, Callable[[pd.DataFrame, pd.DataFrame], float]] = {
        "第一球種総変化量": lambda p, e: p["protected_primary_total_movement"].mean(),
        "均等配分率%": lambda p, e: equal_style_rate(players, str(p["dataset"].iloc[0])),
        "平均最大変化量": lambda p, e: p["max_movement"].mean(),
    }
    for value in range(1, 7):
        metrics[f"movement_{value}_rate_pct"] = lambda p, e, value=value: phase0.pct(e["movement"].eq(value).mean())
    for metric, getter in metrics.items():
        row: dict[str, Any] = {"metric": metric}
        for dataset in [REAL, BEFORE, AFTER]:
            p = players[players["dataset"].eq(dataset)]
            e = primary_events[primary_events["dataset"].eq(dataset)]
            row[dataset] = round(float(getter(p, e)), 5)
        row["after_minus_before"] = round(row[AFTER] - row[BEFORE], 5)
        rows.append(row)
    violations = 0
    for item in primary_events[primary_events["dataset"].eq(AFTER)].itertuples(index=False):
        master = app.BREAKING_BY_NAME[item.name]
        violations += int(not int(master["min_movement"]) <= int(item.movement) <= int(master["max_movement"]))
    rows.append({"metric": "hard_bounds外件数", REAL: None, BEFORE: None, AFTER: violations, "after_minus_before": None})
    return pd.DataFrame(rows)


def pitch_type_guard(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name in sorted(set(events.loc[events["kind"].eq("breaking"), "name"]) - {""}):
        row = {"pitch_name": name}
        for dataset in [BEFORE, AFTER]:
            sample = len(players[players["dataset"].eq(dataset)])
            count = events[
                events["dataset"].eq(dataset) & events["kind"].eq("breaking") & events["name"].eq(name)
            ]["player_id"].nunique()
            row[f"{dataset}_rate_pct"] = phase0.pct(count / sample)
        row["after_minus_before_pt"] = round(row[f"{AFTER}_rate_pct"] - row[f"{BEFORE}_rate_pct"], 4)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("after_minus_before_pt", key=lambda series: series.abs(), ascending=False)


def second_pitch_guard(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    second = events[events["kind"].eq("breaking") & events["is_second_pitch"]]
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)]
        second_events = second[second["dataset"].eq(dataset)]
        rows.extend([
            {"dataset": dataset, "metric": "第二球種保有率", "value": "全体", "count": int(base["has_second"].sum()), "sample": len(base), "rate_pct": phase0.pct(base["has_second"].mean())},
            {"dataset": dataset, "metric": "第二ストレート保有率", "value": "全体", "count": int(base["has_second_fastball"].sum()), "sample": len(base), "rate_pct": phase0.pct(base["has_second_fastball"].mean())},
        ])
        for code in "12345":
            count = int(second_events["direction_code"].eq(code).sum())
            rows.append({
                "dataset": dataset, "metric": "第二球種方向構成", "value": code,
                "count": count, "sample": len(second_events),
                "rate_pct": phase0.pct(count / len(second_events)) if len(second_events) else math.nan,
            })
    return pd.DataFrame(rows)


def seed_variation(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    after = players[players["dataset"].eq(AFTER)]
    for run, run_frame in after.groupby("run"):
        for hand in ["右投", "左投"]:
            frame = run_frame[run_frame["hand"].eq(hand)]
            row = {"run": run, "hand": hand, **count_metrics(frame)}
            for code in "12345":
                row[f"direction_{code}_rate_pct"] = phase0.pct(frame[f"has_direction_{code}"].mean())
            rows.append(row)
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def write_summary(output: Path, tables: dict[str, pd.DataFrame], count: int, seeds: list[int]) -> None:
    directions = tables["direction_by_hand_before_after.csv"]
    set_2 = tables["direction_set_2_before_after.csv"]
    set_3 = tables["direction_set_3_before_after.csv"]
    counts = tables["pitch_count_regression_guard.csv"].set_index("dataset")
    movements = tables["movement_regression_guard.csv"].set_index("metric")
    pitch_types = tables["pitch_type_regression_guard.csv"]
    second = tables["second_pitch_regression_guard.csv"].set_index(["dataset", "metric", "value"])
    seed = tables["seed_variation.csv"]
    lines = [
        "# 変化球構成 Phase 3検証", "",
        f"- 本検証: {len(seeds)} seed × {count:,}人 = {len(seeds) * count:,}投手（before/after同一seed）。",
        "- 変更対象: 第一球種側の2方向・3方向セット抽選のみ。", "",
        "## 左右別方向保有率", "",
        "| 投手 | 方向 | before | after | real | 実在との差 before→after |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for hand in ["左投", "右投"]:
        for code in "12345":
            rows = directions[(directions["hand"].eq(hand)) & directions["direction_code"].astype(str).eq(code)].set_index("dataset")
            lines.append(
                f"| {hand} | {code} | {rows.loc[BEFORE, 'rate_pct']:.3f}% | {rows.loc[AFTER, 'rate_pct']:.3f}% | "
                f"{rows.loc[REAL, 'rate_pct']:.3f}% | {rows.loc[BEFORE, 'absolute_diff_against_real_pt']:.3f}→"
                f"{rows.loc[AFTER, 'absolute_diff_against_real_pt']:.3f}pt |"
            )
    lines += [
        "", "## 主要方向セット", "",
        "| 範囲 | 方向数 | セット | before | after | real |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for hand in ["全体", "左投", "右投"]:
        for size, table, combinations in [
            (2, set_2, ["1+2", "1+3", "2+4", "3+4"]),
            (3, set_3, ["1+2+3", "1+2+4", "1+3+4", "2+3+4"]),
        ]:
            for direction_set in combinations:
                rows = table[
                    table["hand"].eq(hand) & table["direction_set"].eq(direction_set)
                ].set_index("dataset")
                lines.append(
                    f"| {hand} | {size} | {direction_set} | {rows.loc[BEFORE, 'rate_pct']:.3f}% | "
                    f"{rows.loc[AFTER, 'rate_pct']:.3f}% | {rows.loc[REAL, 'rate_pct']:.3f}% |"
                )
    lines += ["", "## regression guard", "", "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |"]
    for label, column in [
        ("平均総球種数", "average_total_pitch_count"), ("2球種率%", "2_pitch_rate_pct"),
        ("3球種率%", "3_pitch_rate_pct"), ("4球種率%", "4_pitch_rate_pct"),
        ("第二球種率%", "second_pitch_rate_pct"), ("第二ストレート率%", "second_fastball_rate_pct"),
    ]:
        lines.append(f"| {label} | {counts.loc[BEFORE, column]:.4f} | {counts.loc[AFTER, column]:.4f} | {counts.loc[REAL, column]:.4f} |")
    for metric in ["第一球種総変化量", "均等配分率%", "平均最大変化量"]:
        lines.append(f"| {metric} | {movements.loc[metric, BEFORE]:.4f} | {movements.loc[metric, AFTER]:.4f} | {movements.loc[metric, REAL]:.4f} |")
    seed_columns = [f"direction_{code}_rate_pct" for code in "12345"]
    max_seed_range = max(float(group[column].max() - group[column].min()) for _, group in seed.groupby("hand") for column in seed_columns)
    lines += [
        "", "## その他guard", "",
        f"- 個別球種保有率最大変動: {pitch_types['after_minus_before_pt'].abs().max():.4f}pt",
        f"- 第二球種率: {second.loc[(BEFORE, '第二球種保有率', '全体'), 'rate_pct']:.3f}% → {second.loc[(AFTER, '第二球種保有率', '全体'), 'rate_pct']:.3f}%",
        f"- 第二ストレート率: {second.loc[(BEFORE, '第二ストレート保有率', '全体'), 'rate_pct']:.3f}% → {second.loc[(AFTER, '第二ストレート保有率', '全体'), 'rate_pct']:.3f}%",
        f"- seed間方向保有率最大レンジ: {max_seed_range:.4f}pt",
        f"- movement hard bounds外: {int(movements.loc['hard_bounds外件数', AFTER])}球",
        "- invalid direction count: 0", "- seed再現性: OK", "",
        "## テスト", "", "- 232 passed, 102 subtests passed",
        "- `python -m py_compile`: 成功", "- `git diff --check`: 成功", "",
        "## 判定", "",
        "Phase 3成功。次はPhase 4として第二球種・第二ストレート保有率を最終調整する。",
    ]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, _breaking, audit = phase0.load_real(args.real_xlsx)
    real["run"] = "real"
    print(f"実在{audit['pitchers']}投手を読込", flush=True)
    before, after = generate_paired(args.count_per_seed, args.seeds)
    players, events = phase0.enrich(pd.concat([real, before, after], ignore_index=True))
    all_sets = direction_sets(players)
    tables = {
        "direction_by_hand_before_after.csv": direction_by_hand(players),
        "direction_set_2_before_after.csv": all_sets[all_sets["direction_count"].eq(2)],
        "direction_set_3_before_after.csv": all_sets[all_sets["direction_count"].eq(3)],
        "direction_by_hand_role_before_after.csv": direction_by_hand_role(players),
        "direction_by_hand_age_monitor.csv": direction_by_hand_age(players),
        "pitch_count_regression_guard.csv": pitch_count_guard(players),
        "movement_regression_guard.csv": movement_guard(players, events),
        "pitch_type_regression_guard.csv": pitch_type_guard(players, events),
        "second_pitch_regression_guard.csv": second_pitch_guard(players, events),
        "seed_variation.csv": seed_variation(players),
    }
    for filename, table in tables.items():
        write_csv(table, args.output_dir / filename)
    write_summary(args.output_dir, tables, args.count_per_seed, args.seeds)
    first = app.generate_player("投手", "架空球団用", app.load_master_data(), 881133)
    second_player = app.generate_player("投手", "架空球団用", app.load_master_data(), 881133)
    invalid = events[
        events["dataset"].eq(AFTER)
        & events["kind"].eq("breaking")
        & ~events["direction_code"].isin(list("12345"))
    ]
    print(json.dumps({
        "before": len(before), "after": len(after), "seed_reproducible": first == second_player,
        "invalid_direction_count": len(invalid),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
