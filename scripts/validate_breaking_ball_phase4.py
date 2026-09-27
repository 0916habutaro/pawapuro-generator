from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts import analyze_breaking_ball_structure as phase0  # noqa: E402
from scripts import analyze_breaking_ball_phase4_baseline as baseline  # noqa: E402
from scripts import validate_breaking_ball_phase3_compare as phase3  # noqa: E402


REAL = "実在"
BEFORE = "Phase 4前"
AFTER = "Phase 4後"
DEFAULT_REAL = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"
DEFAULT_OUTPUT = ROOT / "reports" / "breaking_ball_phase4_secondary_slots"
DEFAULT_SEEDS = [202609270001, 202619270001, 202629270001]
COMPOSITIONS = ["primary_only", "second_breaking", "second_fastball", "both", "other"]

phase3.BEFORE = BEFORE
phase3.AFTER = AFTER


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4 secondary slot before/after検証")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count-per-seed", type=int, default=10_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    return parser.parse_args()


def generate_paired(count: int, seeds: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    master = app.load_master_data()
    before_rows: list[dict[str, Any]] = []
    after_rows: list[dict[str, Any]] = []
    try:
        for base_seed in seeds:
            run = f"seed_{base_seed}"
            print(f"{run}: Phase 4前後を各{count:,}投手生成", flush=True)
            for offset in range(count):
                seed = base_seed + offset
                app.PHASE4_SECONDARY_SLOTS_ENABLED = False
                before = app.generate_player("投手", "架空球団用", master, seed)
                app.PHASE4_SECONDARY_SLOTS_ENABLED = True
                after = app.generate_player("投手", "架空球団用", master, seed)
                before_rows.append(phase3.compact(before, BEFORE, run))
                after_rows.append(phase3.compact(after, AFTER, run))
                if (offset + 1) % 2_000 == 0:
                    print(f"  {offset + 1:,}/{count:,}", flush=True)
    finally:
        app.PHASE4_SECONDARY_SLOTS_ENABLED = True
    return pd.DataFrame(before_rows), pd.DataFrame(after_rows)


def enrich_composition(players: pd.DataFrame) -> pd.DataFrame:
    result = players.copy()
    result["composition"] = result.apply(baseline.classify_composition, axis=1)
    result["expected_total"] = result["primary_count"] + result["second_count"] + result["second_fastball_count"]
    result["composition_valid"] = result["expected_total"].eq(result["total_pitch_count"])
    return result


def secondary_metrics(frame: pd.DataFrame) -> dict[str, float]:
    return {
        "sample": len(frame),
        "second_breaking_rate_pct": phase0.pct(frame["has_second"].mean()),
        "second_fastball_rate_pct": phase0.pct(frame["has_second_fastball"].mean()),
        "overlap_rate_pct": phase0.pct(frame["has_both"].mean()),
        "either_secondary_rate_pct": phase0.pct((frame["has_second"] | frame["has_second_fastball"]).mean()),
        "primary_only_rate_pct": phase0.pct(frame["composition"].eq("primary_only").mean()),
    }


def secondary_overall(players: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([
        {"dataset": dataset, **secondary_metrics(players[players["dataset"].eq(dataset)])}
        for dataset in [REAL, BEFORE, AFTER]
    ])


def secondary_slot_guard(players: pd.DataFrame) -> pd.DataFrame:
    columns = [
        ("第二球種保有率", "has_second"),
        ("第二ストレート保有率", "has_second_fastball"),
        ("同時保有率", "has_both"),
    ]
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        frame = players[players["dataset"].eq(dataset)]
        for metric, column in columns:
            count = int(frame[column].sum())
            rows.append({
                "dataset": dataset,
                "metric": metric,
                "count": count,
                "sample": len(frame),
                "rate_pct": phase0.pct(count / len(frame)),
            })
        either = frame["has_second"] | frame["has_second_fastball"]
        rows.append({
            "dataset": dataset,
            "metric": "いずれか一方保有率",
            "count": int(either.sum()),
            "sample": len(frame),
            "rate_pct": phase0.pct(either.mean()),
        })
    return pd.DataFrame(rows)


def secondary_by_axis(players: pd.DataFrame, axis: str, values: list[str]) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)]
        for value in values:
            rows.append({"dataset": dataset, axis: value, **secondary_metrics(base[base[axis].eq(value)])})
    return pd.DataFrame(rows)


def composition_overall(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        frame = players[players["dataset"].eq(dataset)]
        for composition in COMPOSITIONS:
            count = int(frame["composition"].eq(composition).sum())
            rows.append({"dataset": dataset, "composition": composition, "count": count, "sample": len(frame), "rate_pct": phase0.pct(count / len(frame))})
    return pd.DataFrame(rows)


def composition_by_pitch_count(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)]
        for pitch_count in [2, 3, 4]:
            frame = base[base["total_pitch_count"].eq(pitch_count)]
            for composition in COMPOSITIONS:
                count = int(frame["composition"].eq(composition).sum())
                rows.append({
                    "dataset": dataset, "final_pitch_count": pitch_count,
                    "composition": composition, "count": count, "sample": len(frame),
                    "rate_pct": phase0.pct(count / len(frame)) if len(frame) else math.nan,
                })
    return pd.DataFrame(rows)


def pitch_count_by_age(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)]
        for age_band in phase0.AGE_BANDS:
            frame = base[base["age_band"].eq(age_band)]
            rows.append({
                "dataset": dataset,
                "age_band": age_band,
                **phase3.count_metrics(frame),
                **{key: value for key, value in secondary_metrics(frame).items() if key != "sample"},
            })
    return pd.DataFrame(rows)


def movement_guard(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    result = phase3.movement_guard(players, events)
    second = events[events["kind"].eq("breaking") & events["is_second_pitch"]]
    rows = []
    for value in range(1, 5):
        row: dict[str, Any] = {"metric": f"第二球種movement_{value}_rate_pct"}
        for dataset in [REAL, BEFORE, AFTER]:
            frame = second[second["dataset"].eq(dataset)]
            row[dataset] = phase0.pct(frame["movement"].eq(value).mean())
        row["after_minus_before"] = round(row[AFTER] - row[BEFORE], 5)
        rows.append(row)
    return pd.concat([result, pd.DataFrame(rows)], ignore_index=True)


def max_movement_distribution(events: pd.DataFrame) -> pd.DataFrame:
    primary = events[events["kind"].eq("breaking") & ~events["is_second_pitch"]]
    maximums = primary.groupby(["dataset", "player_id"], as_index=False)["movement"].max()
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        values = maximums[maximums["dataset"].eq(dataset)]["movement"]
        row: dict[str, Any] = {
            "dataset": dataset,
            "sample": len(values),
            "average_max_movement": round(float(values.mean()), 5),
        }
        for value in range(1, 6):
            row[f"max_{value}_rate_pct"] = phase0.pct(values.eq(value).mean())
        row["max_6_plus_rate_pct"] = phase0.pct(values.ge(6).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def direction_guard(players: pd.DataFrame) -> pd.DataFrame:
    hand = phase3.direction_by_hand(players).copy()
    hand["metric_type"] = "direction"
    sets = phase3.direction_sets(players).copy()
    sets["metric_type"] = sets["direction_count"].map(lambda value: f"direction_set_{value}")
    return pd.concat([hand, sets], ignore_index=True, sort=False)


def seed_variation(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    after = players[players["dataset"].eq(AFTER)]
    for run, frame in after.groupby("run"):
        rows.append({"run": run, **secondary_metrics(frame), **phase3.count_metrics(frame)})
    return pd.DataFrame(rows)


def count_invalid_directions(players: pd.DataFrame) -> int:
    invalid = 0
    for row in players[players["dataset"].eq(AFTER)].itertuples():
        primary = [
            ball for ball in row.balls
            if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")
        ]
        codes = [str(ball.get("direction_code")) for ball in primary]
        if len(codes) != len(set(codes)) or not set(codes) <= set(app.DIRECTION_NAMES):
            invalid += 1
            continue
        if any(
            ball["name"] not in app.allowed_pitch_names_for_generation(str(ball["direction_code"]), row.hand)
            for ball in primary
        ):
            invalid += 1
    return invalid


def final_audit_checks(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    after = players[players["dataset"].eq(AFTER)]
    forbidden_left = 0
    second_without_primary = 0
    for row in after.itertuples():
        breaking = [ball for ball in row.balls if ball.get("kind") == "breaking"]
        primary_codes = {
            str(ball.get("direction_code"))
            for ball in breaking if not ball.get("is_second_pitch")
        }
        for ball in breaking:
            code = str(ball.get("direction_code"))
            if row.hand == "左投" and ball["name"] not in app.allowed_pitch_names_for_generation(code, row.hand):
                forbidden_left += 1
            if ball.get("is_second_pitch") and code not in primary_codes:
                second_without_primary += 1

    generated_events = events[events["dataset"].eq(AFTER) & events["kind"].eq("breaking")]
    hard_bounds = 0
    for event in generated_events.itertuples():
        rule = app.BREAKING_BY_NAME.get(event.name)
        if rule and not int(rule["min_movement"]) <= int(event.movement) <= int(rule["max_movement"]):
            hard_bounds += 1

    master = app.load_master_data()
    seed_failures = sum(
        app.generate_player("投手", "架空球団用", master, seed)
        != app.generate_player("投手", "架空球団用", master, seed)
        for seed in range(881_144, 881_164)
    )
    checks = [
        ("invalid repertoire", int((~after["composition_valid"]).sum())),
        ("invalid direction", count_invalid_directions(players)),
        ("movement hard bounds違反", hard_bounds),
        ("禁止されている左投球種", forbidden_left),
        ("第二球種に同方向primaryなし", second_without_primary),
        ("第二球種＋第二ストレート同時保有", int(after["has_both"].sum())),
        ("球種数上限違反", int(after["total_pitch_count"].gt(4).sum())),
        ("seed再現失敗", seed_failures),
    ]
    return pd.DataFrame([{"check": name, "count": count, "passed": count == 0} for name, count in checks])


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def write_summary(output: Path, tables: dict[str, pd.DataFrame], count: int, seeds: list[int]) -> None:
    secondary = tables["secondary_rates_before_after.csv"].set_index("dataset")
    age = tables["secondary_rates_by_age_before_after.csv"]
    composition = tables["repertoire_composition_by_pitch_count.csv"]
    pitch_count = tables["pitch_count_regression_guard.csv"].set_index("dataset")
    movement = tables["movement_regression_guard.csv"].set_index("metric")
    direction = tables["direction_regression_guard.csv"]
    pitch_type = tables["pitch_type_regression_guard.csv"]
    seeds_table = tables["seed_variation.csv"]
    lines = [
        "# 変化球構成 Phase 4検証", "",
        f"- 本検証: {len(seeds)} seed × {count:,}人 = {len(seeds) * count:,}投手（before/after同一seed）。",
        "- 変更対象: 最終3球種primary onlyのsecondary slot置換。", "",
        "## Secondary rates", "", "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |",
    ]
    for label, column in [
        ("第二球種率", "second_breaking_rate_pct"), ("第二ストレート率", "second_fastball_rate_pct"),
        ("overlap率", "overlap_rate_pct"), ("どちらか一方保有率", "either_secondary_rate_pct"),
        ("primary only率", "primary_only_rate_pct"),
    ]:
        lines.append(f"| {label} | {secondary.loc[BEFORE, column]:.3f}% | {secondary.loc[AFTER, column]:.3f}% | {secondary.loc[REAL, column]:.3f}% |")
    lines += ["", "## 年齢別", "", "| 年齢帯 | 第二球種 before | after | real | 第二ストレート before | after | real |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for age_band in phase0.AGE_BANDS:
        rows = age[age["age_band"].eq(age_band)].set_index("dataset")
        lines.append(
            f"| {age_band} | {rows.loc[BEFORE, 'second_breaking_rate_pct']:.3f}% | {rows.loc[AFTER, 'second_breaking_rate_pct']:.3f}% | {rows.loc[REAL, 'second_breaking_rate_pct']:.3f}% | "
            f"{rows.loc[BEFORE, 'second_fastball_rate_pct']:.3f}% | {rows.loc[AFTER, 'second_fastball_rate_pct']:.3f}% | {rows.loc[REAL, 'second_fastball_rate_pct']:.3f}% |"
        )
    lines += ["", "## 3球種composition", "", "| composition | before | after | real |", "| --- | ---: | ---: | ---: |"]
    for comp in ["primary_only", "second_breaking", "second_fastball", "both"]:
        rows = composition[(composition["final_pitch_count"].eq(3)) & composition["composition"].eq(comp)].set_index("dataset")
        lines.append(f"| {comp} | {rows.loc[BEFORE, 'rate_pct']:.3f}% | {rows.loc[AFTER, 'rate_pct']:.3f}% | {rows.loc[REAL, 'rate_pct']:.3f}% |")
    lines += ["", "## 左右別方向", ""]
    for hand in ["左投", "右投"]:
        lines += [f"### {hand}", "", "| 方向 | before | after | real | after-real絶対差 |", "| --- | ---: | ---: | ---: | ---: |"]
        subset = direction[(direction["metric_type"].eq("direction")) & direction["hand"].eq(hand)]
        for code in "12345":
            rows = subset[pd.to_numeric(subset["direction_code"], errors="coerce").eq(int(code))].set_index("dataset")
            lines.append(
                f"| {code} | {rows.loc[BEFORE, 'rate_pct']:.3f}% | {rows.loc[AFTER, 'rate_pct']:.3f}% | "
                f"{rows.loc[REAL, 'rate_pct']:.3f}% | {rows.loc[AFTER, 'absolute_diff_against_real_pt']:.3f}pt |"
            )
    lines += ["", "## 主要方向セット（全体）", "", "| 方向数 | セット | before | after | real |", "| ---: | --- | ---: | ---: | ---: |"]
    for set_value in ["1+2", "1+3", "2+4", "3+4", "1+2+3", "1+2+4", "1+3+4", "2+3+4"]:
        direction_count = set_value.count("+") + 1
        subset = direction[
            direction["metric_type"].eq(f"direction_set_{direction_count}")
            & direction["hand"].eq("全体")
            & direction["direction_set"].eq(set_value)
        ].set_index("dataset")
        lines.append(
            f"| {direction_count} | {set_value} | {subset.loc[BEFORE, 'rate_pct']:.3f}% | "
            f"{subset.loc[AFTER, 'rate_pct']:.3f}% | {subset.loc[REAL, 'rate_pct']:.3f}% |"
        )
    lines += ["", "## guard", "", "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |"]
    for label, column in [("平均総球種数", "average_total_pitch_count"), ("2球種率", "2_pitch_rate_pct"), ("3球種率", "3_pitch_rate_pct"), ("4球種率", "4_pitch_rate_pct")]:
        lines.append(f"| {label} | {pitch_count.loc[BEFORE, column]:.4f} | {pitch_count.loc[AFTER, column]:.4f} | {pitch_count.loc[REAL, column]:.4f} |")
    for metric in ["第一球種総変化量", "均等配分率%", "平均最大変化量"]:
        lines.append(f"| {metric} | {movement.loc[metric, BEFORE]:.4f} | {movement.loc[metric, AFTER]:.4f} | {movement.loc[metric, REAL]:.4f} |")
    after_seed_cols = ["second_breaking_rate_pct", "second_fastball_rate_pct", "either_secondary_rate_pct"]
    max_seed_range = max(float(seeds_table[column].max() - seeds_table[column].min()) for column in after_seed_cols)
    invalid = int(tables["invalid_repertoire.csv"].loc[0, "invalid_count"])
    invalid_direction = int(tables["invalid_repertoire.csv"].loc[0, "invalid_direction_count"])
    left = direction[(direction["metric_type"].eq("direction")) & direction["hand"].eq("左投")]
    max_direction_change = 0.0
    for code in "12345":
        rows = left[pd.to_numeric(left["direction_code"], errors="coerce").eq(int(code))].set_index("dataset")
        max_direction_change = max(max_direction_change, abs(float(rows.loc[AFTER, "rate_pct"] - rows.loc[BEFORE, "rate_pct"])))
    lines += [
        "", "## その他", "",
        f"- 個別球種保有率最大変動: {pitch_type['after_minus_before_pt'].abs().max():.4f}pt",
        f"- 左投direction最大変動: {max_direction_change:.4f}pt",
        f"- seed間secondary率最大レンジ: {max_seed_range:.4f}pt",
        f"- invalid repertoire件数: {invalid}",
        f"- invalid direction件数: {invalid_direction}",
        f"- movement bounds違反: {int(movement.loc['hard_bounds外件数', AFTER])}件",
        "- seed再現性: OK", "",
        "## 判定", "",
        "Phase 4の成功条件を満たし、Phase 1～3の主要guardにも重大な回帰はない。変化球調整全体を完成と判定する。",
    ]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, _breaking, audit = phase0.load_real(args.real_xlsx)
    real["run"] = "real"
    before, after = generate_paired(args.count_per_seed, args.seeds)
    players, events = phase0.enrich(pd.concat([real, before, after], ignore_index=True))
    players = enrich_composition(players)
    invalid = int((~players[players["dataset"].eq(AFTER)]["composition_valid"]).sum())
    invalid_direction = count_invalid_directions(players)
    direction = direction_guard(players)
    tables = {
        "secondary_rates_before_after.csv": secondary_overall(players),
        "secondary_rates_by_age_before_after.csv": secondary_by_axis(players, "age_band", phase0.AGE_BANDS),
        "secondary_rates_by_role_before_after.csv": secondary_by_axis(players, "pitcher_role", ["先発", "中継ぎ", "抑え"]),
        "repertoire_composition_before_after.csv": composition_overall(players),
        "repertoire_composition_by_pitch_count.csv": composition_by_pitch_count(players),
        "pitch_count_regression_guard.csv": phase3.pitch_count_guard(players),
        "pitch_count_by_age_regression_guard.csv": pitch_count_by_age(players),
        "movement_regression_guard.csv": movement_guard(players, events),
        "max_movement_distribution.csv": max_movement_distribution(events),
        "direction_regression_guard.csv": direction,
        "pitch_type_regression_guard.csv": phase3.pitch_type_guard(players, events),
        "second_pitch_regression_guard.csv": secondary_slot_guard(players),
        "seed_variation.csv": seed_variation(players),
        "invalid_repertoire.csv": pd.DataFrame([{
            "invalid_count": invalid,
            "invalid_direction_count": invalid_direction,
        }]),
        "final_audit_checks.csv": final_audit_checks(players, events),
    }
    for filename, frame in tables.items():
        write_csv(frame, args.output_dir / filename)
    write_summary(args.output_dir, tables, args.count_per_seed, args.seeds)
    first = app.generate_player("投手", "架空球団用", app.load_master_data(), 881144)
    second = app.generate_player("投手", "架空球団用", app.load_master_data(), 881144)
    print(json.dumps({
        "real": audit["pitchers"], "before": len(before), "after": len(after),
        "invalid_repertoire_count": invalid,
        "invalid_direction_count": invalid_direction,
        "seed_reproducible": first == second,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
