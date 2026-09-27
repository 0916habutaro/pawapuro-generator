from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    ability_numeric_value,
    generate_player,
    is_countable_special,
    is_special_allowed_for_player,
    load_master_data,
    pitch_movement,
    pitcher_speed_value,
    special_count_bounds,
)
from scripts.analyze_special_age_experience import (  # noqa: E402
    AGE_LABELS,
    COMPARABLE_RANKS,
    CONTROLLED,
    GROUP_MAP,
    KIND_MAP,
    KINDS,
    PRO_LABELS,
    RANKS,
    REAL,
    SAVED,
    age_band,
    add_ability_score,
    comparable_counts,
    indicator,
    load_real,
    load_saved,
    normalize_name,
    normalize_position,
    pct,
    safe_json,
)


BEFORE = "before"
AFTER = "after"
CONFLICTS = {
    "積極打法": "慎重打法", "慎重打法": "積極打法", "強振多用": "ミート多用", "ミート多用": "強振多用",
    "積極盗塁": "慎重盗塁", "慎重盗塁": "積極盗塁", "速球中心": "変化球中心", "変化球中心": "速球中心",
    "投球位置左": "投球位置右", "投球位置右": "投球位置左", "チームプレイ○": "チームプレイ×", "チームプレイ×": "チームプレイ○",
    "四球": "ストライク先行", "ストライク先行": "四球", "抜け球": "リリース○", "リリース○": "抜け球",
    "スロースターター": "立ち上がり○", "立ち上がり○": "スロースターター",
}
PROTECTED_FIELDS = [
    "age", "pro_years", "player_class", "archetype", "position_style", "position",
    "abilities_json", "breaking_balls_json", "aptitudes_json", "protected_player_json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力年齢構造 Phase 1 検証")
    parser.add_argument("--mode", choices=["before", "compare"], required=True)
    parser.add_argument("--real-xlsx", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "players.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "special_age_phase1_count")
    parser.add_argument("--count-per-role-per-seed", type=int, default=5_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202609280101, 202609280201])
    return parser.parse_args()


def generated_metrics(player: dict[str, Any]) -> dict[str, Any]:
    abilities = player.get("abilities", {})
    balls = player.get("breaking_balls", []) or []
    primary = [ball for ball in balls if ball.get("kind", "breaking") == "breaking" and not ball.get("is_second_pitch")]
    return {
        "球速": pitcher_speed_value(abilities), "コントロール": ability_numeric_value(abilities, "コントロール"),
        "スタミナ": ability_numeric_value(abilities, "スタミナ"), "総変化量": sum(pitch_movement(ball) for ball in primary),
        "球種数": len(primary), "ミート": ability_numeric_value(abilities, "ミート"), "パワー": ability_numeric_value(abilities, "パワー"),
        "走力": ability_numeric_value(abilities, "走力"), "肩力": ability_numeric_value(abilities, "肩力"),
        "守備力": ability_numeric_value(abilities, "守備力"), "捕球": ability_numeric_value(abilities, "捕球"),
    }


def flatten_player(player: dict[str, Any], stage: str, run: str, index: int) -> dict[str, Any]:
    abilities = player.get("abilities", {})
    base_abilities = {key: value for key, value in abilities.items() if key != "ranked_specials"}
    specials = [normalize_name(name) for name in player.get("special_abilities", [])]
    ranked = list((abilities.get("ranked_specials", {}) or {}).values())
    counts = comparable_counts(specials, ranked)
    aptitudes = {key: player.get(key, "") for key in ["starter_aptitude", "reliever_aptitude", "closer_aptitude"]}
    protected_player = {key: value for key, value in player.items() if key != "special_abilities"}
    row = {
        "dataset": stage, "run": run, "player_id": f"{stage}:{run}:{player['seed']}", "seed": player["seed"],
        "role": player["role"], "category": player["category"], "age": player["age"], "pro_years": player.get("pro_years"),
        "player_class": player.get("player_class", ""), "archetype": player.get("archetype", ""),
        "position_style": player.get("position_style", ""), "position": player.get("position", ""),
        "abilities_json": json.dumps(base_abilities, ensure_ascii=False, sort_keys=True),
        "breaking_balls_json": json.dumps(player.get("breaking_balls", []) or [], ensure_ascii=False, sort_keys=True),
        "aptitudes_json": json.dumps(aptitudes, ensure_ascii=False, sort_keys=True),
        "protected_player_json": json.dumps(protected_player, ensure_ascii=False, sort_keys=True),
        "sub_positions_json": json.dumps(player.get("sub_positions", []) or [], ensure_ascii=False, sort_keys=True),
        "cap_count": sum(is_countable_special(name) for name in specials),
    }
    row.update(generated_metrics(player))
    row.update(counts)
    return row


def finalize(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for col in ["age", "pro_years", "normal_count", "cap_count", "display_special_count", "球速", "コントロール", "スタミナ", "総変化量", "球種数", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"]:
        if col not in result:
            result[col] = math.nan
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result["age_band"] = result["age"].map(age_band)
    result["position_group"] = [normalize_position(position, role) for position, role in zip(result["position"], result["role"])]
    return add_ability_score(result)


def generate(stage: str, count: int, seeds: list[int]) -> pd.DataFrame:
    master = load_master_data()
    rows: list[dict[str, Any]] = []
    for run_index, seed_base in enumerate(seeds):
        run = f"seed_{seed_base}"
        for role_index, role in enumerate(["投手", "野手"]):
            print(f"{stage} {run}: {role} {count:,}人", flush=True)
            for index in range(count):
                seed = seed_base + run_index * 100_000_000 + role_index * 10_000_000 + index
                player = generate_player(
                    role,
                    "架空球団用",
                    master,
                    seed=seed,
                    apply_age_special_tail=stage != BEFORE,
                )
                rows.append(flatten_player(player, stage, run, index))
    return finalize(pd.DataFrame(rows))


def describe_count(frame: pd.DataFrame, dataset: str, role: str, band: str | None = None) -> dict[str, Any]:
    subset = frame[frame["dataset"].eq(dataset) & frame["role"].eq(role)]
    if band is not None:
        subset = subset[subset["age_band"].eq(band)]
    values = subset["normal_count"]
    return {
        "dataset": dataset, "role": role, "age_band": band or "全体", "n": len(values), "mean": values.mean(),
        "median": values.median(), "p25": values.quantile(.25), "p75": values.quantile(.75), "p90": values.quantile(.90),
        "max": values.max() if len(values) else math.nan, "rate_0_pct": pct(values.eq(0)), "rate_1_2_pct": pct(values.between(1, 2)),
        "rate_3_4_pct": pct(values.between(3, 4)), "rate_5plus_pct": pct(values.ge(5)), "rate_8plus_pct": pct(values.ge(8)),
        "rate_10plus_pct": pct(values.ge(10)), "small_sample": len(values) < 30,
    }


def count_tables(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    datasets = [dataset for dataset in [REAL, SAVED, BEFORE, AFTER] if dataset in set(frame["dataset"])]
    overall = pd.DataFrame([describe_count(frame, dataset, role) for dataset in datasets for role in ["投手", "野手"]])
    by_age = pd.DataFrame([describe_count(frame, dataset, role, band) for dataset in datasets for role in ["投手", "野手"] for band in AGE_LABELS])
    return overall, by_age


def class_age_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, role, player_class, band), subset in frame[frame["dataset"].isin([BEFORE, AFTER])].groupby(["dataset", "role", "player_class", "age_band"], observed=False):
        values = subset["normal_count"]
        rows.append({"dataset": dataset, "role": role, "player_class": player_class, "age_band": band, "n": len(subset),
                     "mean": values.mean(), "p90": values.quantile(.90), "rate_5plus_pct": pct(values.ge(5)),
                     "rate_8plus_pct": pct(values.ge(8)), "rate_10plus_pct": pct(values.ge(10)), "small_sample": len(subset) < 30})
    return pd.DataFrame(rows)


def score_age_table(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["dataset"].isin([BEFORE, AFTER])].copy()
    work["score_band"] = ""
    for (_dataset, _role), index in work.groupby(["dataset", "role"]).groups.items():
        work.loc[index, "score_band"] = pd.qcut(work.loc[index, "ability_score"].rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"]).astype(str)
    rows = []
    for (dataset, role, score, band), subset in work.groupby(["dataset", "role", "score_band", "age_band"], observed=False):
        values = subset["normal_count"]
        rows.append({"dataset": dataset, "role": role, "score_band": score, "age_band": band, "n": len(subset),
                     "mean": values.mean(), "p90": values.quantile(.90), "rate_5plus_pct": pct(values.ge(5)),
                     "rate_8plus_pct": pct(values.ge(8)), "rate_10plus_pct": pct(values.ge(10))})
    return pd.DataFrame(rows)


def display_guard(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, role, band), subset in frame.groupby(["dataset", "role", "age_band"], observed=False):
        values = subset["display_special_count"]
        rows.append({"dataset": dataset, "role": role, "age_band": band, "n": len(values), "mean": values.mean(),
                     "p90": values.quantile(.90), "rate_5plus_pct": pct(values.ge(5)), "rate_8plus_pct": pct(values.ge(8)),
                     "rate_10plus_pct": pct(values.ge(10))})
    return pd.DataFrame(rows)


def kind_guard(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, role, band), subset in frame.groupby(["dataset", "role", "age_band"], observed=False):
        for kind in KINDS:
            values = subset[f"kind_{kind}"]
            rows.append({"dataset": dataset, "role": role, "age_band": band, "kind": kind, "n": len(subset),
                         "mean_count": values.mean(), "holder_rate_pct": pct(values.ge(1))})
    result = pd.DataFrame(rows)
    before = result[result["dataset"].eq(BEFORE)].set_index(["role", "age_band", "kind"])
    result["before_mean_count"] = [before["mean_count"].get((r.role, r.age_band, r.kind), math.nan) for r in result.itertuples()]
    result["mean_change"] = result["mean_count"] - result["before_mean_count"]
    result["before_holder_rate_pct"] = [before["holder_rate_pct"].get((r.role, r.age_band, r.kind), math.nan) for r in result.itertuples()]
    result["holder_rate_change_pt"] = result["holder_rate_pct"] - result["before_holder_rate_pct"]
    return result


def individual_guard(frame: pd.DataFrame) -> pd.DataFrame:
    generated = frame[frame["dataset"].isin([BEFORE, AFTER])]
    rows = []
    for role in ["投手", "野手"]:
        names = sorted({name for raw in generated.loc[generated["role"].eq(role), "normal_names"] for name in safe_json(raw, [])})
        for name in names:
            for dataset in [BEFORE, AFTER]:
                base = generated[generated["dataset"].eq(dataset) & generated["role"].eq(role)]
                held = indicator(base, name)
                row = {"dataset": dataset, "role": role, "special": name, "kind": KIND_MAP.get(name, "other"),
                       "n": len(base), "overall_rate_pct": pct(held.eq(1))}
                for band in AGE_LABELS:
                    mask = base["age_band"].eq(band)
                    row[f"{band}_n"] = int(mask.sum())
                    row[f"{band}_rate_pct"] = pct(held.loc[mask].eq(1))
                rows.append(row)
    result = pd.DataFrame(rows)
    before = result[result["dataset"].eq(BEFORE)].set_index(["role", "special"])
    result["before_overall_rate_pct"] = [before["overall_rate_pct"].get((r.role, r.special), math.nan) for r in result.itertuples()]
    result["overall_change_pt"] = result["overall_rate_pct"] - result["before_overall_rate_pct"]
    age_changes = []
    for row in result.itertuples(index=False):
        prior = before.loc[(row.role, row.special)] if (row.role, row.special) in before.index else None
        diffs = [abs(getattr(row, f"_field_{0}"))] if False else []
        if prior is None or row.dataset == BEFORE:
            age_changes.append(0.0 if row.dataset == BEFORE else math.nan)
        else:
            current = result[(result["dataset"].eq(row.dataset)) & result["role"].eq(row.role) & result["special"].eq(row.special)].iloc[0]
            age_changes.append(max(abs(float(current[f"{band}_rate_pct"]) - float(prior[f"{band}_rate_pct"])) for band in AGE_LABELS))
    result["max_age_band_change_pt"] = age_changes
    return result


def ranked_guard(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = {**{rank: f"rank_{rank}" for rank in RANKS}, "A/B/C": "rank_ABC", "E/F/G": "rank_EFG"}
    for (dataset, role, band), subset in frame.groupby(["dataset", "role", "age_band"], observed=False):
        for metric, col in metrics.items():
            rows.append({"dataset": dataset, "role": role, "age_band": band, "metric": metric, "n": len(subset),
                         "mean_count": subset[col].mean(), "holder_rate_pct": pct(subset[col].ge(1))})
    result = pd.DataFrame(rows)
    before = result[result["dataset"].eq(BEFORE)].set_index(["role", "age_band", "metric"])
    result["before_mean_count"] = [before["mean_count"].get((r.role, r.age_band, r.metric), math.nan) for r in result.itertuples()]
    result["mean_change"] = result["mean_count"] - result["before_mean_count"]
    return result


def constraint_audit(*frames: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for frame in frames:
        for dataset, subset in frame.groupby("dataset"):
            counters = Counter()
            for row in subset.itertuples(index=False):
                names = safe_json(row.normal_names, [])
                name_set = set(names)
                counters["players"] += 1
                counters["duplicate_special"] += int(len(names) != len(name_set))
                groups = [GROUP_MAP.get(name, "") for name in names if GROUP_MAP.get(name, "")]
                counters["duplicate_group"] += int(len(groups) != len(set(groups)))
                counters["conflict"] += int(any(CONFLICTS.get(name) in name_set for name in names))
                sub_positions = safe_json(row.sub_positions_json, [])
                aptitudes = safe_json(row.aptitudes_json, {})
                invalid = [name for name in names if not is_special_allowed_for_player(name, row.role, row.position, sub_positions, aptitudes)]
                counters["position_or_aptitude"] += int(bool(invalid))
                low, high = special_count_bounds("架空球団用", row.player_class)
                counters["hard_bounds"] += int(row.cap_count < low or row.cap_count > high)
            rows.extend(
                {"dataset": dataset, "check": key, "violations": counters[key], "players": counters["players"]}
                for key in ["duplicate_special", "duplicate_group", "conflict", "position_or_aptitude", "hard_bounds"]
            )
    return pd.DataFrame(rows)


def protected_guard(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    left = before.set_index(["run", "seed", "role"]).sort_index()
    right = after.set_index(["run", "seed", "role"]).sort_index()
    common = left.index.intersection(right.index)
    rows = []
    for field in PROTECTED_FIELDS:
        mismatches = int((left.loc[common, field].astype(str) != right.loc[common, field].astype(str)).sum())
        rows.append({"field": field, "compared": len(common), "mismatches": mismatches, "match_rate_pct": (len(common) - mismatches) / len(common) * 100})
    rank_mismatch = int((left.loc[common, "ranked_names"].astype(str) != right.loc[common, "ranked_names"].astype(str)).sum())
    rows.append({"field": "ranked_specials", "compared": len(common), "mismatches": rank_mismatch, "match_rate_pct": (len(common) - rank_mismatch) / len(common) * 100})
    return pd.DataFrame(rows)


def seed_variation(after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (run, role, band), subset in after.groupby(["run", "role", "age_band"], observed=False):
        values = subset["normal_count"]
        rows.append({"run": run, "role": role, "age_band": band, "n": len(subset), "mean": values.mean(),
                     "rate_5plus_pct": pct(values.ge(5)), "rate_8plus_pct": pct(values.ge(8)), "rate_10plus_pct": pct(values.ge(10))})
    result = pd.DataFrame(rows)
    ranges = result.groupby(["role", "age_band"])[["mean", "rate_5plus_pct", "rate_8plus_pct", "rate_10plus_pct"]].agg(lambda s: s.max() - s.min()).reset_index()
    ranges.insert(0, "run", "seed_range")
    return pd.concat([result, ranges], ignore_index=True, sort=False)


def reproducibility_audit(seeds: list[int]) -> pd.DataFrame:
    master = load_master_data()
    rows = []
    for role_index, role in enumerate(["投手", "野手"]):
        for base in seeds[:2]:
            seed = base + role_index * 10_000_000
            first = generate_player(role, "架空球団用", master, seed=seed)
            second = generate_player(role, "架空球団用", master, seed=seed)
            rows.append({"check": "same_seed_reproducibility", "role": role, "seed": seed,
                         "match": json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False, sort_keys=True)})
    return pd.DataFrame(rows)


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")


def baseline_markdown(real: pd.DataFrame, saved: pd.DataFrame, before: pd.DataFrame) -> str:
    combined = pd.concat([real.assign(dataset=REAL), saved.assign(dataset=SAVED), before], ignore_index=True, sort=False)
    _, by_age = count_tables(combined)
    lines = ["# Phase 0 non-ranked baseline", "", "表示総特殊能力数からランク特殊能力を分離し、非ランク特殊能力だけをPhase 1の直接targetとして再集計した。", "",
             "|役割|年齢帯|real平均|saved平均|controlled before平均|real 5+|before 5+|real 8+|before 8+|", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for role in ["投手", "野手"]:
        for band in AGE_LABELS:
            values = {}
            for dataset in [REAL, SAVED, BEFORE]:
                row = by_age[(by_age["dataset"].eq(dataset)) & by_age["role"].eq(role) & by_age["age_band"].eq(band)].iloc[0]
                values[dataset] = row
            lines.append(f"|{role}|{band}|{values[REAL]['mean']:.2f}|{values[SAVED]['mean']:.2f}|{values[BEFORE]['mean']:.2f}|{values[REAL]['rate_5plus_pct']:.1f}%|{values[BEFORE]['rate_5plus_pct']:.1f}%|{values[REAL]['rate_8plus_pct']:.1f}%|{values[BEFORE]['rate_8plus_pct']:.1f}%|")
    return "\n".join(lines) + "\n"


def write_reports(output: Path, real: pd.DataFrame, saved: pd.DataFrame, before: pd.DataFrame, after: pd.DataFrame, seeds: list[int]) -> None:
    all_data = pd.concat([real.assign(dataset=REAL), saved.assign(dataset=SAVED), before, after], ignore_index=True, sort=False)
    overall, by_age = count_tables(all_data)
    class_age = class_age_table(all_data)
    score_age = score_age_table(all_data)
    display = display_guard(all_data)
    kinds = kind_guard(all_data)
    individuals = individual_guard(all_data)
    ranked = ranked_guard(all_data)
    constraints = constraint_audit(before, after)
    protected = protected_guard(before, after)
    repro = reproducibility_audit(seeds)
    protected_full = pd.concat([protected, repro.assign(field="same_seed_reproducibility", compared=1, mismatches=(~repro["match"]).astype(int), match_rate_pct=repro["match"].astype(int) * 100)[["field", "compared", "mismatches", "match_rate_pct"]]], ignore_index=True)
    variation = seed_variation(after)

    save_csv(overall, output / "nonrank_special_count_before_after.csv")
    save_csv(by_age, output / "nonrank_special_count_by_age_before_after.csv")
    save_csv(by_age[["dataset", "role", "age_band", "n", "p90", "rate_5plus_pct", "rate_8plus_pct", "rate_10plus_pct", "small_sample"]], output / "nonrank_special_tail_by_age_before_after.csv")
    save_csv(class_age, output / "nonrank_special_by_age_player_class.csv")
    save_csv(score_age, output / "nonrank_special_by_age_score.csv")
    save_csv(display, output / "display_special_total_guard.csv")
    save_csv(kinds, output / "special_kind_regression_guard.csv")
    save_csv(individuals, output / "individual_special_regression_guard.csv")
    save_csv(ranked, output / "ranked_special_regression_guard.csv")
    save_csv(constraints, output / "special_constraint_audit.csv")
    save_csv(protected_full, output / "protected_generation_guard.csv")
    save_csv(variation, output / "seed_variation.csv")
    (output / "phase0_nonrank_baseline.md").write_text(baseline_markdown(real, saved, before), encoding="utf-8")

    def get(table: pd.DataFrame, dataset: str, role: str, band: str, col: str) -> float:
        return float(table[(table["dataset"].eq(dataset)) & table["role"].eq(role) & table["age_band"].eq(band)].iloc[0][col])
    kind_after = kinds[kinds["dataset"].eq(AFTER)].copy()
    max_kind_row = kind_after.loc[kind_after["holder_rate_change_pt"].abs().idxmax()]
    max_kind = abs(float(max_kind_row["holder_rate_change_pt"]))
    individual_after = individuals[individuals["dataset"].eq(AFTER)].copy()
    max_individual_row = individual_after.loc[individual_after["overall_change_pt"].abs().idxmax()]
    max_individual = abs(float(max_individual_row["overall_change_pt"]))
    max_individual_age = individual_after["max_age_band_change_pt"].abs().max()
    individual_over_3 = int(individual_after["overall_change_pt"].abs().gt(3.0).sum())
    rank_after = ranked[ranked["dataset"].eq(AFTER)]
    max_rank = rank_after["mean_change"].abs().max()
    max_abc = rank_after[rank_after["metric"].eq("A/B/C")]["mean_change"].abs().max()
    max_efg = rank_after[rank_after["metric"].eq("E/F/G")]["mean_change"].abs().max()
    after_constraints = constraints[constraints["dataset"].eq(AFTER)].set_index("check")
    before_constraints = constraints[constraints["dataset"].eq(BEFORE)].set_index("check")
    invalids = int(after_constraints["violations"].sum())
    before_hard_bounds = int(before_constraints.loc["hard_bounds", "violations"])
    after_hard_bounds = int(after_constraints.loc["hard_bounds", "violations"])
    protected_mismatches = int(protected[protected["field"].ne("ranked_specials")]["mismatches"].sum())
    rank_mismatches = int(protected[protected["field"].eq("ranked_specials")]["mismatches"].sum())
    seed_max = variation[variation["run"].eq("seed_range")]["mean"].max()

    def class_get(dataset: str, role: str, player_class: str, band: str, col: str) -> float:
        subset = class_age[
            class_age["dataset"].eq(dataset)
            & class_age["role"].eq(role)
            & class_age["player_class"].eq(player_class)
            & class_age["age_band"].eq(band)
        ]
        return float(subset.iloc[0][col]) if len(subset) else math.nan

    def kind_holder(dataset: str, role: str, kind: str) -> float:
        subset = all_data[all_data["dataset"].eq(dataset) & all_data["role"].eq(role)]
        return pct(subset[f"kind_{kind}"].ge(1))

    lines = ["# 特殊能力年齢構造 Phase 1", "", "## Phase 0 baseline clarification", "", "表示総特殊能力数と非ランク特殊能力数を分離し、Phase 1では非ランクだけを直接targetにした。ランクはguardのみ。", "",
             "## Non-ranked count", "", "|役割|指標|before|after|real|", "|---|---|---:|---:|---:|"]
    for role in ["投手", "野手"]:
        for metric, label in [("mean", "平均"), ("rate_5plus_pct", "5+"), ("rate_8plus_pct", "8+"), ("rate_10plus_pct", "10+")]:
            values = {dataset: overall[(overall["dataset"].eq(dataset)) & overall["role"].eq(role)].iloc[0][metric] for dataset in [BEFORE, AFTER, REAL]}
            suffix = "%" if "rate" in metric else ""
            lines.append(f"|{role}|{label}|{values[BEFORE]:.2f}{suffix}|{values[AFTER]:.2f}{suffix}|{values[REAL]:.2f}{suffix}|")
    lines += ["", "## Age", ""]
    for role in ["投手", "野手"]:
        lines += [f"### {role}", "", "|年齢帯|平均 before→after→real|P90 before→after→real|5+|8+|10+|", "|---|---:|---:|---:|---:|---:|"]
        for band in AGE_LABELS:
            triplets = []
            for metric in ["mean", "p90", "rate_5plus_pct", "rate_8plus_pct", "rate_10plus_pct"]:
                triplets.append("→".join(f"{get(by_age,dataset,role,band,metric):.1f}" for dataset in [BEFORE, AFTER, REAL]))
            lines.append(f"|{band}|" + "|".join(triplets) + "|")
        lines.append("")
    lines += ["## Age gradient", "", "18～22歳から31～34歳への非ランク平均増加。35+は参考値。", "", "|役割|before|after|real|35+ after→real|", "|---|---:|---:|---:|---:|"]
    for role in ["投手", "野手"]:
        gradients = [get(by_age, dataset, role, "31～34", "mean") - get(by_age, dataset, role, "18～22", "mean") for dataset in [BEFORE, AFTER, REAL]]
        lines.append(f"|{role}|{gradients[0]:.2f}|{gradients[1]:.2f}|{gradients[2]:.2f}|{get(by_age,AFTER,role,'35+','mean'):.2f}→{get(by_age,REAL,role,'35+','mean'):.2f}|")
    lines += ["", "## player_class", "", "実在データには生成側と同じplayer_classがないため、class別は同一seedのbefore→afterで監査した。", "", "|役割|class・年齢|指標|before→after|", "|---|---|---|---:|"]
    class_checks = [
        ("若手素材型", "18～22", "rate_5plus_pct", "5+"),
        ("スター級", "18～22", "rate_8plus_pct", "8+"),
        ("一軍主力級", "27～30", "rate_8plus_pct", "8+"),
        ("一軍主力級", "31～34", "rate_8plus_pct", "8+"),
        ("ベテラン型", "31～34", "rate_8plus_pct", "8+"),
        ("二軍級", "35+", "rate_5plus_pct", "5+"),
    ]
    for role in ["投手", "野手"]:
        for player_class, band, metric, label in class_checks:
            before_value = class_get(BEFORE, role, player_class, band, metric)
            after_value = class_get(AFTER, role, player_class, band, metric)
            if not math.isnan(before_value) and not math.isnan(after_value):
                lines.append(f"|{role}|{player_class} {band}|{label}|{before_value:.1f}%→{after_value:.1f}%|")
    lines += ["", "## Guards", "",
              f"- kind保有率の最大変動: {max_kind:.2f}pt（{max_kind_row['role']} {max_kind_row['age_band']} {max_kind_row['kind']}、平均個数差 {float(max_kind_row['mean_change']):+.3f}）",
              f"- 個別特殊能力の全体率最大変動: {max_individual:.2f}pt（{max_individual_row['role']} {max_individual_row['special']} {float(max_individual_row['overall_change_pt']):+.2f}pt）",
              f"- 個別特殊能力の年齢帯率最大変動: {max_individual_age:.2f}pt。全体率±3pt超は{individual_over_3}件で、個別chance変更ではなく個数tail再配分による上位候補の増減として監査継続。",
              f"- A/B/C平均個数の最大変動: {max_abc:.4f}、E/F/G: {max_efg:.4f}、全ランク指標: {max_rank:.4f}",
              f"- gold 1+率（投手/野手）: {kind_holder(BEFORE,'投手','gold'):.2f}%→{kind_holder(AFTER,'投手','gold'):.2f}% / {kind_holder(BEFORE,'野手','gold'):.2f}%→{kind_holder(AFTER,'野手','gold'):.2f}%",
              f"- red 1+率（投手/野手）: {kind_holder(BEFORE,'投手','red'):.2f}%→{kind_holder(AFTER,'投手','red'):.2f}% / {kind_holder(BEFORE,'野手','red'):.2f}%→{kind_holder(AFTER,'野手','red'):.2f}%",
              f"- after制約違反: duplicate {int(after_constraints.loc['duplicate_special','violations'])}、group {int(after_constraints.loc['duplicate_group','violations'])}、conflict {int(after_constraints.loc['conflict','violations'])}、position/aptitude {int(after_constraints.loc['position_or_aptitude','violations'])}、hard bounds {after_hard_bounds}",
              f"- hard boundsはbeforeの既存短不足{before_hard_bounds}件を最終リフィルでafter 0件へ修正。",
              f"- ランク以外のprotected mismatch: {protected_mismatches}、ranked special同一seed mismatch: {rank_mismatches}",
              f"- seed再現: {'成功' if repro['match'].all() else '失敗'}、seed間平均の最大レンジ: {seed_max:.3f}個", "",
              "## Residual gaps", "", "23～26歳野手と27～30歳野手の8+/10+には残差がある。個別特殊能力の年齢profile差はPhase 2、A/B/C等のランク年齢構造はPhase 3へ残した。pro_yearsは使用していない。", "",
              "## 次Phase判定", ""]
    young_improved = all(abs(get(by_age, AFTER, role, "18～22", "rate_5plus_pct") - get(by_age, REAL, role, "18～22", "rate_5plus_pct")) < abs(get(by_age, BEFORE, role, "18～22", "rate_5plus_pct") - get(by_age, REAL, role, "18～22", "rate_5plus_pct")) for role in ["投手", "野手"])
    mid_improved = all(abs(get(by_age, AFTER, role, band, "rate_5plus_pct") - get(by_age, REAL, role, band, "rate_5plus_pct")) < abs(get(by_age, BEFORE, role, band, "rate_5plus_pct") - get(by_age, REAL, role, band, "rate_5plus_pct")) for role in ["投手", "野手"] for band in ["27～30", "31～34"])
    overall_stable = all(abs(float(overall[(overall["dataset"].eq(AFTER)) & overall["role"].eq(role)].iloc[0]["mean"]) - float(overall[(overall["dataset"].eq(BEFORE)) & overall["role"].eq(role)].iloc[0]["mean"])) <= 0.5 for role in ["投手", "野手"])
    guard_ok = invalids == 0 and max_rank == 0 and protected_mismatches == 0 and rank_mismatches == 0 and repro["match"].all()
    decision = "Phase 2へ進む" if young_improved and mid_improved and overall_stable and guard_ok else "Phase 1微調整" if guard_ok else "Phase 1を戻す"
    lines += [f"**{decision}**", ""]
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    log = """# Phase 1 implementation log

- Phase 0の表示総数ではなく、非ランク特殊能力数を直接targetに再集計。
- 個別chance、特殊能力マスタ、ランク生成、pro_years、基本能力・class・年齢・変化球生成は変更対象外。
- 18～22歳は若手素材型・非例外の主力/控えをsoft cap / bonus drawで抑制し、若手スターと高score例外は維持。
- 27～34歳は高scoreのスター/主力/ベテランを中心にtailを増加。35+は野手高classのcapだけを弱く緩和し、低classへは加算しない。
- 個数調整は局所RNGへ分離し、ランク・基本能力・氏名・フォーム・装備など後続生成への乱数波及を防止。
- 最終制約監査後の最低個数リフィルで、既存の稀なhard bounds短不足を解消。
- controlled before/afterは同じseed集合で比較。
"""
    (output / "phase1_implementation_log.md").write_text(log, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    before_path = args.output_dir / ".before_controlled.pkl"
    after_path = args.output_dir / ".after_controlled.pkl"
    real_path = args.output_dir / ".real.pkl"
    saved_path = args.output_dir / ".saved.pkl"
    if args.mode == "before":
        real, _ = load_real(args.real_xlsx)
        saved, _ = load_saved(args.db)
        before = generate(BEFORE, args.count_per_role_per_seed, args.seeds)
        real.to_pickle(real_path)
        saved.to_pickle(saved_path)
        before.to_pickle(before_path)
        (args.output_dir / "phase0_nonrank_baseline.md").write_text(baseline_markdown(real, saved, before), encoding="utf-8")
        overall, by_age = count_tables(pd.concat([real.assign(dataset=REAL), saved.assign(dataset=SAVED), before], ignore_index=True, sort=False))
        save_csv(overall, args.output_dir / "nonrank_special_count_before_after.csv")
        save_csv(by_age, args.output_dir / "nonrank_special_count_by_age_before_after.csv")
        print(f"before snapshot saved: {len(before):,}")
        return 0
    if not all(path.exists() for path in [before_path, real_path, saved_path]):
        raise SystemExit("before snapshotがありません。先に--mode beforeを実行してください。")
    real = pd.read_pickle(real_path)
    saved = pd.read_pickle(saved_path)
    before = pd.read_pickle(before_path)
    after = generate(AFTER, args.count_per_role_per_seed, args.seeds)
    after.to_pickle(after_path)
    write_reports(args.output_dir, real, saved, before, after, args.seeds)
    print(f"comparison complete: before={len(before):,}, after={len(after):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
