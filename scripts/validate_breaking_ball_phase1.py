from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts import analyze_breaking_ball_structure as phase0  # noqa: E402


REAL = "実在"
BEFORE = "Phase 1前"
AFTER = "Phase 1後"
DEFAULT_REAL = (
    ROOT.parent
    / "real_powerpro_players_12teams_final"
    / "pawapuro_players_entry_route_2026.xlsx"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 1 movement配分のbefore/after検証")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "breaking_ball_phase1_movement")
    parser.add_argument("--count-per-seed", type=int, default=10_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202609270001, 202619270001, 202629270001])
    return parser.parse_args()


def load_baseline_app() -> types.ModuleType:
    source = subprocess.check_output(
        ["git", "show", "HEAD:app.py"], cwd=ROOT, text=True, encoding="utf-8"
    )
    module = types.ModuleType("phase1_baseline_app")
    module.__file__ = str(ROOT / "app.py")
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def compact_player(player: dict[str, Any], dataset: str, run: str) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "player_id": f"{dataset}:{run}:{player['seed']}",
        "name": player["name"],
        "age": player["age"],
        "pro_years": player.get("pro_years"),
        "pitcher_role": player["position"],
        "hand": phase0.hand(player["batting_throwing"]),
        "balls": player["breaking_balls"],
    }


def generate_paired(count: int, seeds: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline_app = load_baseline_app()
    before_master = baseline_app.load_master_data()
    after_master = app.load_master_data()
    before_rows: list[dict[str, Any]] = []
    after_rows: list[dict[str, Any]] = []
    for base_seed in seeds:
        run = f"seed_{base_seed}"
        print(f"{run}: before/after 各{count:,}投手を生成", flush=True)
        for offset in range(count):
            seed = base_seed + offset
            before = baseline_app.generate_player("投手", "架空球団用", before_master, seed)
            after = app.generate_player("投手", "架空球団用", after_master, seed)
            before_rows.append(compact_player(before, BEFORE, run))
            after_rows.append(compact_player(after, AFTER, run))
            if (offset + 1) % 2000 == 0:
                print(f"  {offset + 1:,}/{count:,}", flush=True)
    return pd.DataFrame(before_rows), pd.DataFrame(after_rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def distribution_table(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = events[events["kind"].eq("breaking") & events["movement"].gt(0)]
    for dataset in [REAL, BEFORE, AFTER]:
        dataset_events = base[base["dataset"].eq(dataset)]
        for scope, frame in [
            ("全変化球", dataset_events),
            ("第一球種", dataset_events[~dataset_events["is_second_pitch"]]),
            ("第二球種", dataset_events[dataset_events["is_second_pitch"]]),
        ]:
            values = frame["movement"]
            row = {
                "dataset": dataset, "scope": scope, "sample": len(values),
                "mean": round(values.mean(), 4), "median": round(values.median(), 4),
                "p75": round(values.quantile(.75), 4), "p90": round(values.quantile(.90), 4),
                "max": int(values.max()) if len(values) else None,
            }
            for value in range(1, 7):
                row[f"movement_{value}_rate_pct"] = phase0.pct(values.eq(value).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def pattern_table(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        base = players[players["dataset"].eq(dataset)].copy()
        base["total_bucket"] = base["structure_total_movement"].map(
            lambda value: "10以上" if value >= 10 else str(int(value))
        )
        for total in ["5", "6", "7", "8", "9", "10以上"]:
            subset = base[base["total_bucket"].eq(total)]
            patterns = Counter(subset["movement_pattern"])
            styles = Counter(subset["movement_style"])
            for rank, (pattern, count) in enumerate(patterns.most_common(12), 1):
                rows.append({
                    "dataset": dataset, "total_movement": total, "row_type": "pattern",
                    "rank": rank, "pattern_or_style": pattern, "count": count,
                    "rate_pct": phase0.pct(count / len(subset)) if len(subset) else None,
                    "sample_players": len(subset),
                })
            for style in ["均等型", "主力球型", "決め球特化型"]:
                rows.append({
                    "dataset": dataset, "total_movement": total, "row_type": "style",
                    "rank": "", "pattern_or_style": style, "count": styles[style],
                    "rate_pct": phase0.pct(styles[style] / len(subset)) if len(subset) else None,
                    "sample_players": len(subset),
                })
    return pd.DataFrame(rows)


def max_table(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, BEFORE, AFTER]:
        values = players.loc[players["dataset"].eq(dataset), "max_movement"]
        row = {"dataset": dataset, "sample": len(values), "average_max_movement": round(values.mean(), 4)}
        for value in range(1, 6):
            row[f"max_{value}_rate_pct"] = phase0.pct(values.eq(value).mean())
        row["max_6_plus_rate_pct"] = phase0.pct(values.ge(6).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def pitch_name_table(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = events[events["kind"].eq("breaking") & events["movement"].gt(0)]
    real_counts = base[base["dataset"].eq(REAL)]["name"].value_counts()
    names = sorted(name for name, count in real_counts.items() if count >= 10)
    for name in names:
        for dataset in [REAL, BEFORE, AFTER]:
            values = base[(base["dataset"].eq(dataset)) & base["name"].eq(name)]["movement"]
            rows.append({
                "pitch_name": name, "dataset": dataset, "sample": len(values),
                "mean": round(values.mean(), 4) if len(values) else None,
                "p90": round(values.quantile(.90), 4) if len(values) else None,
                "max": int(values.max()) if len(values) else None,
            })
    return pd.DataFrame(rows)


def second_pitch_table(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base = events[events["kind"].eq("breaking") & events["is_second_pitch"]]
    for dataset in [REAL, BEFORE, AFTER]:
        values = base.loc[base["dataset"].eq(dataset), "movement"]
        row = {"dataset": dataset, "sample": len(values), "mean": round(values.mean(), 4)}
        for value in range(1, 5):
            row[f"movement_{value}_rate_pct"] = phase0.pct(values.eq(value).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def bounds_table(events: pd.DataFrame) -> pd.DataFrame:
    phase0_audit = pd.read_csv(ROOT / "reports" / "breaking_ball_structure_recheck" / "movement_master_audit.csv")
    real = phase0_audit[phase0_audit["dataset"].eq(REAL)].set_index("pitch_name")
    after_events = events[(events["dataset"].eq(AFTER)) & events["kind"].eq("breaking")]
    rows = []
    for ball in app.BREAKING_BALL_MASTER:
        name = ball["name"]
        values = after_events.loc[after_events["name"].eq(name), "movement"]
        legacy_min, legacy_max = app.LEGACY_MOVEMENT_BOUNDS[name]
        rows.append({
            "pitch_name": name,
            "real_sample": int(real.loc[name, "sample"]) if name in real.index else 0,
            "real_min": real.loc[name, "observed_min"] if name in real.index else None,
            "real_p5": real.loc[name, "observed_p5"] if name in real.index else None,
            "real_p95": real.loc[name, "observed_p95"] if name in real.index else None,
            "real_max": real.loc[name, "observed_max"] if name in real.index else None,
            "before_hard_min": legacy_min, "before_hard_max": legacy_max,
            "after_hard_min": int(ball["min_movement"]), "after_hard_max": int(ball["max_movement"]),
            "after_sample": len(values),
            "after_below_min_count": int(values.lt(ball["min_movement"]).sum()),
            "after_above_max_count": int(values.gt(ball["max_movement"]).sum()),
        })
    return pd.DataFrame(rows)


def possession(players: pd.DataFrame, events: pd.DataFrame, dataset: str) -> pd.Series:
    sample = len(players[players["dataset"].eq(dataset)])
    base = events[(events["dataset"].eq(dataset)) & events["kind"].eq("breaking")]
    return base.groupby("name")["player_id"].nunique().div(sample).mul(100)


def regression_table(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    before = players[players["dataset"].eq(BEFORE)]
    after = players[players["dataset"].eq(AFTER)]

    def add(metric: str, before_value: float, after_value: float, tolerance: float) -> None:
        delta = after_value - before_value
        rows.append({
            "axis": "全体", "group": "全体", "metric": metric,
            "before": round(before_value, 5), "after": round(after_value, 5),
            "delta": round(delta, 5), "tolerance": tolerance,
            "result": "OK" if abs(delta) <= tolerance else "要確認",
        })

    add("平均第一球種総変化量", before["protected_primary_total_movement"].mean(), after["protected_primary_total_movement"].mean(), .03)
    add("平均総球種数", before["total_pitch_count"].mean(), after["total_pitch_count"].mean(), .03)
    add("平均第一球種数", before["primary_count"].mean(), after["primary_count"].mean(), .03)
    add("第二球種率%", phase0.pct(before["has_second"].mean()), phase0.pct(after["has_second"].mean()), .5)
    add("ストレート系第二種率%", phase0.pct(before["has_second_fastball"].mean()), phase0.pct(after["has_second_fastball"].mean()), .5)

    before_possession = possession(players, events, BEFORE)
    after_possession = possession(players, events, AFTER)
    for name in sorted(set(before_possession.index) | set(after_possession.index)):
        b = float(before_possession.get(name, 0))
        a = float(after_possession.get(name, 0))
        rows.append({
            "axis": "個別球種保有率", "group": name, "metric": "保有率%",
            "before": round(b, 5), "after": round(a, 5), "delta": round(a - b, 5),
            "tolerance": .35, "result": "OK" if abs(a - b) <= .35 else "要確認",
        })
    for axis, column, groups in [
        ("役割", "pitcher_role", ["先発", "中継ぎ", "抑え"]),
        ("年齢帯", "age_band", phase0.AGE_BANDS),
    ]:
        for group in groups:
            b = before.loc[before[column].eq(group), "protected_primary_total_movement"].mean()
            a = after.loc[after[column].eq(group), "protected_primary_total_movement"].mean()
            rows.append({
                "axis": axis, "group": group, "metric": "平均第一球種総変化量",
                "before": round(b, 5), "after": round(a, 5), "delta": round(a - b, 5),
                "tolerance": .08, "result": "OK" if abs(a - b) <= .08 else "要確認",
            })
    return pd.DataFrame(rows)


def equal_style_average(patterns: pd.DataFrame, dataset: str) -> float:
    values = patterns[
        patterns["dataset"].eq(dataset)
        & patterns["row_type"].eq("style")
        & patterns["pattern_or_style"].eq("均等型")
    ]["rate_pct"]
    return float(values.mean())


def write_reports(
    output: Path,
    players: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    count: int,
    seeds: list[int],
) -> None:
    distribution = tables["movement_distribution_before_after.csv"]
    patterns = tables["movement_pattern_before_after.csv"]
    maximum = tables["max_movement_before_after.csv"]
    second = tables["second_pitch_movement_before_after.csv"]
    guards = tables["regression_guard.csv"]
    bounds = tables["movement_bounds_before_after.csv"]

    primary_total = {
        dataset: players.loc[players["dataset"].eq(dataset), "protected_primary_total_movement"].mean()
        for dataset in [REAL, BEFORE, AFTER]
    }
    equal = {dataset: equal_style_average(patterns, dataset) for dataset in [REAL, BEFORE, AFTER]}
    max_mean = {
        dataset: float(maximum.loc[maximum["dataset"].eq(dataset), "average_max_movement"].iloc[0])
        for dataset in [REAL, BEFORE, AFTER]
    }
    first_dist = distribution[distribution["scope"].eq("第一球種")].set_index("dataset")
    second_dist = second.set_index("dataset")
    max_possession_change = guards[guards["axis"].eq("個別球種保有率")]["delta"].abs().max()
    guard_lookup = guards[(guards["axis"].eq("全体")) & guards["group"].eq("全体")].set_index("metric")
    out_of_bounds = int(bounds["after_below_min_count"].sum() + bounds["after_above_max_count"].sum())

    lines = [
        "# 変化球movement Phase 1検証", "",
        f"- 本検証: {len(seeds)} seed × {count:,}人 = {len(seeds) * count:,}投手（before/after同一seed）。",
        "- 変更対象: 第一球種movement配分、球種別hard bounds/soft preference、第二球種movementのみ。",
        "- 球種数・発生率・方向・球種名weight・能力・年齢ロジックは変更していない。", "",
        "## before → after → real", "",
        "| 指標 | before | after | real |", "| --- | ---: | ---: | ---: |",
        f"| 第一球種総変化量 | {primary_total[BEFORE]:.4f} | {primary_total[AFTER]:.4f} | {primary_total[REAL]:.4f} |",
        f"| 均等配分率（総量5～10以上の単純平均） | {equal[BEFORE]:.2f}% | {equal[AFTER]:.2f}% | {equal[REAL]:.2f}% |",
        f"| 平均最大変化量 | {max_mean[BEFORE]:.4f} | {max_mean[AFTER]:.4f} | {max_mean[REAL]:.4f} |", "",
        "### 第一球種movement割合", "",
        "| movement | before | after | real |", "| --- | ---: | ---: | ---: |",
    ]
    for value in range(1, 7):
        column = f"movement_{value}_rate_pct"
        lines.append(f"| {value} | {first_dist.loc[BEFORE, column]:.2f}% | {first_dist.loc[AFTER, column]:.2f}% | {first_dist.loc[REAL, column]:.2f}% |")
    lines += ["", "### 第二球種movement割合", "", "| movement | before | after | real |", "| --- | ---: | ---: | ---: |"]
    for value in range(1, 5):
        column = f"movement_{value}_rate_pct"
        lines.append(f"| {value} | {second_dist.loc[BEFORE, column]:.2f}% | {second_dist.loc[AFTER, column]:.2f}% | {second_dist.loc[REAL, column]:.2f}% |")
    lines += [
        "", "## regression guard", "",
        f"- 個別球種保有率最大変動: {max_possession_change:.4f}pt",
        f"- 総球種数変動: {guard_lookup.loc['平均総球種数', 'delta']:.5f}",
        f"- 第二球種率変動: {guard_lookup.loc['第二球種率%', 'delta']:.5f}pt",
        f"- ストレート系第二種率変動: {guard_lookup.loc['ストレート系第二種率%', 'delta']:.5f}pt",
        f"- hard bounds外movement: {out_of_bounds}球", "",
        "## 判定", "",
    ]
    improved = equal[AFTER] < equal[BEFORE] and max_mean[AFTER] > max_mean[BEFORE] and out_of_bounds == 0
    lines.append(
        "Phase 1成功。Phase 2（総球種数・年齢）へ進める。" if improved else "Phase 1を微調整する。詳細CSVの残差を確認する。"
    )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    log = """# Phase 1実装ログ

## 実装

- `target_total_movement()`は変更せず、正の整数分割を列挙する方式へ変更。
- balanced / primary_pitch / finisherの配分型を、Phase 0実在比率から総変化量帯別に抽選。
- 配分型内では球種別soft movement preferenceにより値と球種の割当を抽選。
- 実在30件未満の球種は全体movement分布へ縮約。
- hard boundsは実在min/max・P5/P95・標本数を分離して再設定。
- 第二球種movementは第一球種以下かつ第二球種hard bounds内で、実在1～4分布をsoft weight化。
- movement抽選は複製RNGを使い、親RNGは旧処理と同じ回数だけ進めることで、Phase 1対象外の後続発生率を保護。

## 非変更

- `target_total_movement()`、`pitch_count_weights()`、`second_pitch_chance()`、`generate_second_fastball()`。
- 方向weight、球種名weight、第二球種名weight。
- 投手能力、特殊能力、年齢、プロ年数。

## hard bounds判断

- 実在でmovement 1が確認された球種はhard minimumを1へ変更。
- P95が高く、上限超過が複数ある球種は5～6を許可。
- 少標本の単発最大値はそのまま全球種へ展開せず、球種別または同系統の保守的上限に留めた。
- 詳細は`movement_bounds_before_after.csv`に記録。
"""
    (output / "phase1_implementation_log.md").write_text(log, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, _breaking, audit = phase0.load_real(args.real_xlsx)
    print(f"実在{audit['pitchers']}投手を読込", flush=True)
    before, after = generate_paired(args.count_per_seed, args.seeds)
    players, events = phase0.enrich(pd.concat([real, before, after], ignore_index=True))
    tables = {
        "movement_distribution_before_after.csv": distribution_table(events),
        "movement_pattern_before_after.csv": pattern_table(players),
        "max_movement_before_after.csv": max_table(players),
        "pitch_movement_by_name_before_after.csv": pitch_name_table(events),
        "second_pitch_movement_before_after.csv": second_pitch_table(events),
        "movement_bounds_before_after.csv": bounds_table(events),
        "regression_guard.csv": regression_table(players, events),
    }
    for filename, frame in tables.items():
        write_csv(frame, args.output_dir / filename)
    write_reports(args.output_dir, players, tables, args.count_per_seed, args.seeds)

    reproducible_a = app.generate_player("投手", "架空球団用", app.load_master_data(), 9918273)
    reproducible_b = app.generate_player("投手", "架空球団用", app.load_master_data(), 9918273)
    print(json.dumps({
        "before": len(before), "after": len(after),
        "seed_reproducible": reproducible_a == reproducible_b,
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
