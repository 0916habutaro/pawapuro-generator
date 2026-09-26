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

from app import (  # noqa: E402
    USAGE_SPECIAL_NAMES,
    ability_numeric_value,
    generate_player,
    load_master_data,
    pitch_movement,
    pitcher_speed_value,
)
from scripts.recheck_current_balance import flatten_generated, safe_json  # noqa: E402


BASELINE_DIR = ROOT / "reports" / "real_vs_generated_current_recheck"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第1次バランス調整の軽量検証")
    parser.add_argument("--count", type=int, default=3_000, help="投手・野手それぞれの人数")
    parser.add_argument("--seed", type=int, default=202607150001)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "first_balance_adjustment_smoke")
    return parser.parse_args()


def pct(mask: pd.Series) -> float:
    return float(mask.mean() * 100) if len(mask) else math.nan


def normal_special_names() -> set[str]:
    master = pd.read_csv(ROOT / "data" / "special_abilities.csv")
    return set(master.loc[master["kind"].isin(["blue", "red", "green", "mixed", "normal"]), "name"].astype(str)) - set(USAGE_SPECIAL_NAMES)


def flatten_player(player: dict[str, Any], run: str, normal_names: set[str]) -> dict[str, Any]:
    row = flatten_generated(player, run)
    row.update({key: player.get(key, "") for key in ["archetype", "position_style", "development_stage", "acquisition_role", "weakness_profile"]})
    specials = [str(name) for name in player.get("special_abilities", []) if str(name) in normal_names]
    row["normal_special_count"] = len(specials)
    row["has_release"] = "リリース○" in specials
    row["breaking_balls"] = json.dumps(player.get("breaking_balls", []) or [], ensure_ascii=False)
    row["pro_years_valid"] = player.get("pro_years") == player.get("age") - player.get("pro_entry_age") + 1
    row["left_sub_invalid"] = str(player.get("batting_throwing", "")).startswith("左投") and any(
        item.get("position") in {"二塁手", "三塁手", "遊撃手"} for item in player.get("sub_positions", []) or []
    )
    return row


def generate_sample(count: int, seed: int) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    master = load_master_data()
    normal_names = normal_special_names()
    rows: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    offset = 0
    for role in ["投手", "野手"]:
        print(f"軽量検証生成中: {role} {count:,}人", flush=True)
        for _ in range(count):
            player = generate_player(role, "架空球団用", master, seed + offset)
            raw.append(player)
            rows.append(flatten_player(player, "after_smoke", normal_names))
            offset += 1
    return pd.DataFrame(rows), raw


def load_baseline() -> pd.DataFrame:
    generated = pd.read_csv(BASELINE_DIR / "generated_players.csv")
    details = pd.read_csv(BASELINE_DIR / "supplemental_generated_detail_cache.csv")
    generated = generated.merge(details, on="player_id", how="left", suffixes=("", "_detail"))
    generated["archetype"] = generated["archetype"].fillna("")
    generated["position_style"] = generated["position_style"].fillna("")
    normal_names = normal_special_names()
    generated["normal_special_count"] = generated["special_names"].map(lambda raw: sum(str(name) in normal_names for name in safe_json(raw, [])))
    generated["has_release"] = generated["special_names"].map(lambda raw: "リリース○" in safe_json(raw, []))
    return generated


def add_metric(rows: list[dict[str, Any]], dataset: str, domain: str, target: str, metric: str, value: Any, n: int) -> None:
    rows.append({"dataset": dataset, "domain": domain, "target": target, "metric": metric, "value": value, "n": n})


def collect_metrics(frame: pd.DataFrame, dataset: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    fielders = frame[frame["role"].eq("野手")]
    for position in ["二塁手", "外野手"]:
        subset = fielders[fielders["position"].eq(position)].copy()
        for ability in ["走力", "肩力", "守備力", "捕球"]:
            subset[ability] = pd.to_numeric(subset[ability], errors="coerce")
        if position == "二塁手":
            values = subset["守備力"].dropna()
            for label, value in [("守備平均", values.mean()), ("守備P10", values.quantile(.10)), ("守備P25", values.quantile(.25)), ("守備P50", values.median())]:
                add_metric(rows, dataset, "二塁手守備", position, label, value, len(values))
            for threshold in [50, 60, 70, 80]:
                add_metric(rows, dataset, "二塁手守備", position, f"守備{threshold}以上率", pct(values.ge(threshold)), len(values))
            add_metric(rows, dataset, "二塁手守備", position, "走力70＋守備60以上率", pct(subset["走力"].ge(70) & subset["守備力"].ge(60)), len(subset))
            add_metric(rows, dataset, "二塁手守備", position, "走力×守備相関", subset["走力"].corr(subset["守備力"]), len(subset))
        else:
            add_metric(rows, dataset, "外野手走守", position, "走力×守備相関", subset["走力"].corr(subset["守備力"]), len(subset))
            add_metric(rows, dataset, "外野手走守", position, "走力×肩力相関", subset["走力"].corr(subset["肩力"]), len(subset))
            add_metric(rows, dataset, "外野手走守", position, "守備×捕球相関", subset["守備力"].corr(subset["捕球"]), len(subset))
            add_metric(rows, dataset, "外野手走守", position, "走70＋肩65＋守50以上率", pct(subset["走力"].ge(70) & subset["肩力"].ge(65) & subset["守備力"].ge(50)), len(subset))
            catch = subset["捕球"].dropna()
            for label, value in [("捕球P10", catch.quantile(.10)), ("捕球P25", catch.quantile(.25)), ("捕球P50", catch.median()), ("捕球39以下率", pct(catch.le(39))), ("捕球50以上率", pct(catch.ge(50)))]:
                add_metric(rows, dataset, "外野捕球", position, label, value, len(catch))
        trajectory = pd.to_numeric(subset["弾道"], errors="coerce").dropna()
        for value in [3, 4]:
            add_metric(rows, dataset, "弾道", position, f"弾道{value}率", pct(trajectory.eq(value)), len(trajectory))

    for role in ["投手", "野手"]:
        subset = frame[frame["role"].eq(role)]
        counts = pd.to_numeric(subset["normal_special_count"], errors="coerce")
        for label, value in [("5個以上率", pct(counts.ge(5))), ("8個以上率", pct(counts.ge(8))), ("P75", counts.quantile(.75)), ("P90", counts.quantile(.90)), ("mean", counts.mean()), ("median", counts.median())]:
            add_metric(rows, dataset, "特殊能力", role, label, value, len(counts))
        for player_class in ["スター級", "一軍主力級", "ベテラン型", "一軍控え級", "若手素材型", "二軍級"]:
            class_counts = pd.to_numeric(subset.loc[subset["player_class"].eq(player_class), "normal_special_count"], errors="coerce")
            add_metric(rows, dataset, "特殊能力選手格", f"{role}/{player_class}", "5個以上率", pct(class_counts.ge(5)), len(class_counts))
            add_metric(rows, dataset, "特殊能力選手格", f"{role}/{player_class}", "8個以上率", pct(class_counts.ge(8)), len(class_counts))

    pitchers = frame[frame["role"].eq("投手")].copy()
    closers = pitchers[pitchers["pitcher_role"].eq("抑え")]
    stamina = pd.to_numeric(closers["スタミナ"], errors="coerce").dropna()
    for label, value in [("平均", stamina.mean()), ("P10", stamina.quantile(.10)), ("P25", stamina.quantile(.25)), ("P50", stamina.median()), ("P90", stamina.quantile(.90))]:
        add_metric(rows, dataset, "抑え", "スタミナ", label, value, len(stamina))
    direction2 = closers["breaking_balls"].map(lambda raw: any(str(ball.get("direction_code")) == "2" and ball.get("kind", "breaking") == "breaking" for ball in safe_json(raw, [])))
    direction2_primary = closers["breaking_balls"].map(lambda raw: any(str(ball.get("direction_code")) == "2" and ball.get("kind", "breaking") == "breaking" and not ball.get("is_second_pitch") for ball in safe_json(raw, [])))
    direction2_second = closers["breaking_balls"].map(lambda raw: any(str(ball.get("direction_code")) == "2" and ball.get("kind", "breaking") == "breaking" and ball.get("is_second_pitch") for ball in safe_json(raw, [])))
    add_metric(rows, dataset, "抑え", "球種", "方向2保有率", pct(direction2), len(closers))
    add_metric(rows, dataset, "抑え", "球種", "方向2第一球種保有率", pct(direction2_primary), len(closers))
    add_metric(rows, dataset, "抑え", "球種", "方向2第二球種保有率", pct(direction2_second), len(closers))
    add_metric(rows, dataset, "投手", "特殊能力", "リリース○保有率", pct(pitchers["has_release"].astype(bool)), len(pitchers))
    return pd.DataFrame(rows)


def audit_sample(frame: pd.DataFrame, raw: list[dict[str, Any]]) -> pd.DataFrame:
    fielders = frame[frame["role"].eq("野手")]
    fielder_values = fielders[["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]].apply(pd.to_numeric, errors="coerce")
    second_invalid = 0
    for player in raw:
        balls = player.get("breaking_balls", []) or []
        primary_directions = {str(ball.get("direction_code")) for ball in balls if ball.get("kind", "breaking") == "breaking" and not ball.get("is_second_pitch")}
        second_invalid += sum(str(ball.get("direction_code")) not in primary_directions for ball in balls if ball.get("kind", "breaking") == "breaking" and ball.get("is_second_pitch"))
    rows = [
        {"audit": "人数", "warning_count": int(len(frame) != len(raw))},
        {"audit": "年齢範囲", "warning_count": int((~pd.to_numeric(frame["age"], errors="coerce").between(18, 46)).sum())},
        {"audit": "プロ年数整合", "warning_count": int((~frame["pro_years_valid"].astype(bool)).sum())},
        {"audit": "左投げ内野サブポジ", "warning_count": int(frame["left_sub_invalid"].astype(bool).sum())},
        {"audit": "野手最低1弱点", "warning_count": int(fielder_values.min(axis=1).ge(70).sum())},
        {"audit": "第二球種方向整合", "warning_count": int(second_invalid)},
    ]
    return pd.DataFrame(rows)


def reproducibility_check(seed: int) -> int:
    master = load_master_data()
    mismatches = 0
    for offset, role in enumerate(["投手"] * 10 + ["野手"] * 10):
        first = generate_player(role, "架空球団用", master, seed + offset)
        second = generate_player(role, "架空球団用", master, seed + offset)
        mismatches += int(first != second)
    return mismatches


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = load_baseline()
    after, raw = generate_sample(args.count, args.seed)
    before_metrics = collect_metrics(baseline, "before_60000")
    after_metrics = collect_metrics(after, "after_smoke")
    metrics = pd.concat([before_metrics, after_metrics], ignore_index=True)
    key = ["domain", "target", "metric"]
    before_map = before_metrics.set_index(key)["value"]
    metrics["before_value"] = [before_map.get((row.domain, row.target, row.metric), math.nan) for row in metrics.itertuples()]
    metrics["after_minus_before"] = metrics["value"] - metrics["before_value"]
    audits = audit_sample(after, raw)
    audits = pd.concat([audits, pd.DataFrame([{"audit": "seed再現性", "warning_count": reproducibility_check(args.seed)}])], ignore_index=True)
    metrics.to_csv(args.output_dir / "target_metrics.csv", index=False, encoding="utf-8-sig")
    audits.to_csv(args.output_dir / "audit_warnings.csv", index=False, encoding="utf-8-sig")
    after.to_csv(args.output_dir / "generated_players.csv", index=False, encoding="utf-8-sig")
    focus = metrics[metrics["dataset"].eq("after_smoke") & metrics["domain"].isin(["二塁手守備", "外野手走守", "外野捕球", "弾道", "特殊能力", "抑え", "投手"])]
    print(focus[["domain", "target", "metric", "before_value", "value", "after_minus_before", "n"]].to_string(index=False))
    print("\n監査")
    print(audits.to_string(index=False))
    return int(audits["warning_count"].sum() > 0)


if __name__ == "__main__":
    raise SystemExit(main())
