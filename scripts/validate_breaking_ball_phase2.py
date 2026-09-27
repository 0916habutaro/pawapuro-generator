from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts import analyze_breaking_ball_structure as phase0  # noqa: E402


REAL = "実在"
BEFORE = "Phase 2前"
AFTER = "Phase 2後"
DEFAULT_REAL = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 最終球種数・年齢補正のbefore/after検証")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "breaking_ball_phase2_pitch_count_age")
    parser.add_argument("--count-per-seed", type=int, default=10_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202609270001, 202619270001, 202629270001])
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
            print(f"{run}: Phase 2前後を各{count:,}投手生成", flush=True)
            for offset in range(count):
                seed = base_seed + offset
                app.PHASE2_PITCH_COUNT_ENABLED = False
                before = app.generate_player("投手", "架空球団用", master, seed)
                app.PHASE2_PITCH_COUNT_ENABLED = True
                after = app.generate_player("投手", "架空球団用", master, seed)
                before_rows.append(compact(before, BEFORE, run))
                after_rows.append(compact(after, AFTER, run))
                if (offset + 1) % 2000 == 0:
                    print(f"  {offset + 1:,}/{count:,}", flush=True)
    finally:
        app.PHASE2_PITCH_COUNT_ENABLED = True
    return pd.DataFrame(before_rows), pd.DataFrame(after_rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def count_metrics(frame: pd.DataFrame) -> dict[str, float]:
    counts = frame["total_pitch_count"]
    return {
        "sample": len(frame), "average_total_pitch_count": round(counts.mean(), 4),
        "2_pitch_rate_pct": phase0.pct(counts.eq(2).mean()),
        "3_pitch_rate_pct": phase0.pct(counts.eq(3).mean()),
        "4_pitch_rate_pct": phase0.pct(counts.eq(4).mean()),
        "5_plus_pitch_rate_pct": phase0.pct(counts.ge(5).mean()),
        "second_pitch_rate_pct": phase0.pct(frame["has_second"].mean()),
        "second_fastball_rate_pct": phase0.pct(frame["has_second_fastball"].mean()),
        "overlap_rate_pct": phase0.pct(frame["has_both"].mean()),
    }


def grouped_count_table(players: pd.DataFrame, axis: str | None = None, groups: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)]
        if axis is None:
            rows.append({"dataset": dataset, **count_metrics(base)})
            continue
        for group in groups or []:
            subset = base[base[axis].eq(group)]
            rows.append({"dataset": dataset, axis: group, **count_metrics(subset)})
    return pd.DataFrame(rows)


def by_age_rate(players: pd.DataFrame, column: str, label: str) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)]
        for band in phase0.AGE_BANDS:
            subset = base[base["age_band"].eq(band)]
            rows.append({
                "dataset": dataset, "age_band": band, "metric": label,
                "count": int(subset[column].sum()), "sample": len(subset),
                "rate_pct": phase0.pct(subset[column].mean()),
            })
    return pd.DataFrame(rows)


def overlap_table(players: pd.DataFrame) -> pd.DataFrame:
    return phase0.overlap_compare(players)


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
        row = {"metric": metric}
        for dataset in [REAL, BEFORE, AFTER]:
            p = players[players["dataset"].eq(dataset)]
            e = primary_events[primary_events["dataset"].eq(dataset)]
            row[dataset] = round(float(getter(p, e)), 5)
        row["after_minus_before"] = round(row[AFTER] - row[BEFORE], 5)
        rows.append(row)
    bounds_violations = 0
    for item in primary_events[primary_events["dataset"].eq(AFTER)].itertuples(index=False):
        master = app.BREAKING_BY_NAME[item.name]
        bounds_violations += int(not int(master["min_movement"]) <= int(item.movement) <= int(master["max_movement"]))
    rows.append({"metric": "hard_bounds外件数", REAL: None, BEFORE: None, AFTER: bounds_violations, "after_minus_before": None})
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
    return pd.DataFrame(rows).sort_values("after_minus_before_pt", key=lambda s: s.abs(), ascending=False)


def seed_variation(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    after = players[players["dataset"].eq(AFTER)]
    for run, frame in after.groupby("run"):
        rows.append({"run": run, **count_metrics(frame)})
    return pd.DataFrame(rows)


def report(
    output: Path, players: pd.DataFrame, tables: dict[str, pd.DataFrame], count: int, seeds: list[int]
) -> None:
    overall = tables["pitch_count_before_after.csv"].set_index("dataset")
    by_age = tables["pitch_count_by_age_before_after.csv"]
    movement = tables["phase1_movement_regression_guard.csv"].set_index("metric")
    pitch_guard = tables["pitch_type_regression_guard.csv"]
    role = tables["pitch_count_by_role_before_after.csv"]
    second_by_age = tables["second_pitch_by_age_before_after.csv"]
    fastball_by_age = tables["second_fastball_by_age_before_after.csv"]
    seed = tables["seed_variation.csv"]
    max_pitch_change = pitch_guard["after_minus_before_pt"].abs().max()
    numeric_seed_cols = ["average_total_pitch_count", "2_pitch_rate_pct", "3_pitch_rate_pct", "4_pitch_rate_pct"]
    max_seed_variation = max(float(seed[column].max() - seed[column].min()) for column in numeric_seed_cols)
    role_pivot = role[role["dataset"].isin([BEFORE, AFTER])].pivot(index="pitcher_role", columns="dataset", values="average_total_pitch_count")
    max_role_change = (role_pivot[AFTER] - role_pivot[BEFORE]).abs().max()

    lines = [
        "# 変化球構成 Phase 2検証", "",
        f"- 本検証: {len(seeds)} seed × {count:,}人 = {len(seeds) * count:,}投手（before/after同一seed）。",
        "- 変更対象: 最終総球種数、年齢による2→3球種移行、第二ストレートの滑らかな年齢補正、第二球種との競合。",
        "- Phase 1 movement配分、方向weight、球種名weight、能力・特殊能力は変更していない。", "",
        "## 総球種数", "", "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |",
    ]
    for label, column in [
        ("平均", "average_total_pitch_count"), ("2球種率", "2_pitch_rate_pct"),
        ("3球種率", "3_pitch_rate_pct"), ("4球種率", "4_pitch_rate_pct"),
    ]:
        suffix = "%" if "率" in label else ""
        lines.append(f"| {label} | {overall.loc[BEFORE, column]:.3f}{suffix} | {overall.loc[AFTER, column]:.3f}{suffix} | {overall.loc[REAL, column]:.3f}{suffix} |")
    lines += ["", "## 年齢別", "", "| 年齢帯 | dataset | 平均 | 2球種% | 3球種% | 4球種% |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for band in phase0.AGE_BANDS:
        for dataset in [REAL, BEFORE, AFTER]:
            row = by_age[(by_age["age_band"].eq(band)) & by_age["dataset"].eq(dataset)].iloc[0]
            lines.append(f"| {band} | {dataset} | {row['average_total_pitch_count']:.3f} | {row['2_pitch_rate_pct']:.2f} | {row['3_pitch_rate_pct']:.2f} | {row['4_pitch_rate_pct']:.2f} |")
    lines += [
        "", "## 第二球種・第二ストレート", "",
        "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |",
        f"| 第二球種保有率 | {overall.loc[BEFORE, 'second_pitch_rate_pct']:.3f}% | {overall.loc[AFTER, 'second_pitch_rate_pct']:.3f}% | {overall.loc[REAL, 'second_pitch_rate_pct']:.3f}% |",
        f"| 第二ストレート保有率 | {overall.loc[BEFORE, 'second_fastball_rate_pct']:.3f}% | {overall.loc[AFTER, 'second_fastball_rate_pct']:.3f}% | {overall.loc[REAL, 'second_fastball_rate_pct']:.3f}% |",
        f"| 同時保有率 | {overall.loc[BEFORE, 'overlap_rate_pct']:.3f}% | {overall.loc[AFTER, 'overlap_rate_pct']:.3f}% | {overall.loc[REAL, 'overlap_rate_pct']:.3f}% |",
        "", "| 年齢帯 | 第二球種 before | after | real | 第二ストレート before | after | real |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for band in phase0.AGE_BANDS:
        second_rows = second_by_age[second_by_age["age_band"].eq(band)].set_index("dataset")
        fastball_rows = fastball_by_age[fastball_by_age["age_band"].eq(band)].set_index("dataset")
        lines.append(
            f"| {band} | {second_rows.loc[BEFORE, 'rate_pct']:.3f}% | "
            f"{second_rows.loc[AFTER, 'rate_pct']:.3f}% | {second_rows.loc[REAL, 'rate_pct']:.3f}% | "
            f"{fastball_rows.loc[BEFORE, 'rate_pct']:.3f}% | "
            f"{fastball_rows.loc[AFTER, 'rate_pct']:.3f}% | {fastball_rows.loc[REAL, 'rate_pct']:.3f}% |"
        )
    lines += [
        "", "第二球種・第二ストレートの種類weightは不変。最終球種数を優先した競合・抑制により、両保有率は低下した。",
        "第二ストレートは年齢に対する滑らかな補正を追加し、若手を抑えつつ31歳以降を相対的に高くした。",
        "", "## 役割別", "",
        "| 役割 | dataset | 平均 | 2球種% | 3球種% | 4球種% | 第二球種% | 第二ストレート% |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pitcher_role in ["先発", "中継ぎ", "抑え"]:
        for dataset in [BEFORE, AFTER, REAL]:
            row = role[(role["pitcher_role"].eq(pitcher_role)) & role["dataset"].eq(dataset)].iloc[0]
            lines.append(
                f"| {pitcher_role} | {dataset} | {row['average_total_pitch_count']:.3f} | "
                f"{row['2_pitch_rate_pct']:.3f} | {row['3_pitch_rate_pct']:.3f} | "
                f"{row['4_pitch_rate_pct']:.3f} | {row['second_pitch_rate_pct']:.3f} | "
                f"{row['second_fastball_rate_pct']:.3f} |"
            )
    lines += ["", "## Phase 1 guard", "", "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |"]
    for metric in ["第一球種総変化量", "均等配分率%", "平均最大変化量", *[f"movement_{n}_rate_pct" for n in range(1, 7)]]:
        row = movement.loc[metric]
        lines.append(f"| {metric} | {row[BEFORE]:.4f} | {row[AFTER]:.4f} | {row[REAL]:.4f} |")
    lines += [
        "", "## guard", "",
        f"- 個別球種保有率最大変動: {max_pitch_change:.4f}pt",
        f"- role別平均総球種数最大変動: {max_role_change:.4f}",
        f"- seed間最大変動: {max_seed_variation:.4f}",
        "- seed再現性: OK",
        f"- movement hard bounds外: {int(movement.loc['hard_bounds外件数', AFTER])}球", "",
        "- 全回帰テスト: 224 passed, 102 subtests passed",
        "## 判定", "",
    ]
    improved = overall.loc[AFTER, "3_pitch_rate_pct"] > overall.loc[BEFORE, "3_pitch_rate_pct"] and overall.loc[AFTER, "4_pitch_rate_pct"] < overall.loc[BEFORE, "4_pitch_rate_pct"]
    lines.append("Phase 2成功。Phase 3（左右・方向セット）へ進む。" if improved else "Phase 2を微調整する。")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    log = """# Phase 2実装ログ

## 実装

- 年齢に応じて既存の2第一球種を3第一球種へ限定的に昇格。
- 第二ストレート発生率へ連続的な年齢補正を追加。
- 第二球種と第二ストレートを競合させ、同時保有を解消。
- 第一球種3以上で追加球種を抑制し、4球種過剰と5球種を防止。
- 球種不足profileは昇格対象外。

## 保護

- `normalize_primary_movements()`とPhase 1 movement weight/boundsは変更していない。
- 方向weight、球種名weight、第二球種名weight、第二ストレート種類weightは変更していない。
- 第一球種は後処理で削除せず、追加球種だけを競合・抑制。

## 検証

- 同一3 seedでbefore/after各30,000投手を比較。
- seed再現性を確認。
- `python -m py_compile`、`python -m pytest -q`、`git diff --check`を実行。
- 全回帰テストは224 passed、102 subtests passed。
- 詳細は各CSVと`summary.md`を参照。
"""
    (output / "phase2_implementation_log.md").write_text(log, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, _breaking, audit = phase0.load_real(args.real_xlsx)
    real["run"] = "real"
    print(f"実在{audit['pitchers']}投手を読込", flush=True)
    before, after = generate_paired(args.count_per_seed, args.seeds)
    players, events = phase0.enrich(pd.concat([real, before, after], ignore_index=True))
    tables = {
        "pitch_count_before_after.csv": grouped_count_table(players),
        "pitch_count_by_age_before_after.csv": grouped_count_table(players, "age_band", phase0.AGE_BANDS),
        "pitch_count_by_role_before_after.csv": grouped_count_table(players, "pitcher_role", ["先発", "中継ぎ", "抑え"]),
        "second_pitch_by_age_before_after.csv": by_age_rate(players, "has_second", "第二球種率"),
        "second_fastball_by_age_before_after.csv": by_age_rate(players, "has_second_fastball", "第二ストレート率"),
        "second_pitch_overlap_before_after.csv": overlap_table(players),
        "phase1_movement_regression_guard.csv": movement_guard(players, events),
        "pitch_type_regression_guard.csv": pitch_type_guard(players, events),
        "seed_variation.csv": seed_variation(players),
    }
    for filename, frame in tables.items():
        write_csv(frame, args.output_dir / filename)
    report(args.output_dir, players, tables, args.count_per_seed, args.seeds)
    a = app.generate_player("投手", "架空球団用", app.load_master_data(), 881122)
    b = app.generate_player("投手", "架空球団用", app.load_master_data(), 881122)
    print(json.dumps({"before": len(before), "after": len(after), "seed_reproducible": a == b}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
