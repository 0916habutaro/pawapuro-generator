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

from app import INDIVIDUAL_SPECIAL_AGE_PROFILES, generate_player, load_master_data  # noqa: E402
from scripts.analyze_special_age_experience import AGE_LABELS, REAL, indicator, pct, safe_json  # noqa: E402
from scripts.analyze_special_age_phase1 import (  # noqa: E402
    AFTER,
    BEFORE,
    constraint_audit,
    finalize,
    flatten_player,
    protected_guard,
)


PROFILE_ACTION = {
    "experience_up": "increase",
    "mild_experience_up": "mild_increase",
    "flatten_age_bias": "flatten",
}
PROTECTED_REASONS = {
    ("投手", "打球反応○"): "実在保有33人で境界的。31～34歳差も小さくprotect",
    ("投手", "牽制○"): "35+差が中心で、18～22→31～34では不足なし",
    ("投手", "球持ち○"): "Phase 1後も生成年齢差が実在より強いが能力依存が大きい",
    ("投手", "リリース○"): "ability-driven。個別年齢補正を追加しない",
    ("投手", "低め○"): "実在保有14人かつ制球依存",
    ("投手", "奪三振"): "球速・変化量依存。生成年齢差は既に十分",
    ("投手", "緩急○"): "31～34歳はflattenで近づくが、35+を含むweighted MAEが悪化",
    ("野手", "バント職人"): "実在保有7人で少標本",
    ("野手", "サヨナラ男"): "Phase 1で全体率が+3.36pt変化し、年齢勾配も実在に近い",
    ("野手", "併殺"): "若手・全体率も実在より高く、単純flattenでは改善しない",
    ("野手", "固め打ち"): "ability-driven。Phase 1で全体率が+4pt変化済み",
    ("野手", "決勝打"): "Phase 1で全体率が+4.32pt変化済み。base率課題として保護",
}
FOCUS_SPECIALS = list(INDIVIDUAL_SPECIAL_AGE_PROFILES) + list(PROTECTED_REASONS)
PHASE1_TARGETS = {
    "投手": {"mean": 4.10, "rate_5plus_pct": 42.09, "rate_8plus_pct": 9.97, "rate_10plus_pct": 1.65},
    "野手": {"mean": 4.73, "rate_5plus_pct": 48.82, "rate_8plus_pct": 19.66, "rate_10plus_pct": 6.79},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力年齢構造 Phase 2差分分析")
    parser.add_argument("--count-per-role-per-seed", type=int, default=2_500)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202609280101, 202609280201])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "special_age_phase2_individual")
    parser.add_argument(
        "--real-individual-csv",
        type=Path,
        default=ROOT / "reports" / "special_age_experience_recheck" / "individual_special_by_age_compare.csv",
    )
    return parser.parse_args()


def generate(dataset: str, count: int, seeds: list[int], apply_profile: bool) -> pd.DataFrame:
    master = load_master_data()
    rows: list[dict[str, Any]] = []
    for run_index, seed_base in enumerate(seeds):
        run = f"seed_{seed_base}"
        for role_index, role in enumerate(["投手", "野手"]):
            print(f"{dataset} {run}: {role} {count:,}人", flush=True)
            for index in range(count):
                seed = seed_base + run_index * 100_000_000 + role_index * 10_000_000 + index
                player = generate_player(
                    role,
                    "架空球団用",
                    master,
                    seed=seed,
                    apply_age_special_tail=True,
                    apply_individual_age_profile=apply_profile,
                )
                rows.append(flatten_player(player, dataset, run, index))
    frame = finalize(pd.DataFrame(rows))
    frame["age_band"] = pd.Categorical(frame["age_band"], categories=AGE_LABELS, ordered=True)
    return frame


def rate(frame: pd.DataFrame, name: str, band: str | None = None) -> float:
    subset = frame if band is None else frame[frame["age_band"].eq(band)]
    return pct(indicator(subset, name).eq(1))


def weighted_mae(row: pd.Series, prefix: str) -> float:
    errors = []
    weights = []
    for band in AGE_LABELS:
        errors.append(abs(float(row[f"{band}_{prefix}_pct"]) - float(row[f"{band}_real_pct"])))
        weights.append(float(row[f"{band}_real_n"]))
    return float(sum(error * weight for error, weight in zip(errors, weights)) / sum(weights))


def individual_age_compare(before: pd.DataFrame, after: pd.DataFrame, real_csv: Path) -> pd.DataFrame:
    real = pd.read_csv(real_csv, encoding="utf-8-sig")
    real = real[real["dataset"].eq(REAL)].set_index(["role", "special"])
    rows = []
    for role, name in FOCUS_SPECIALS:
        key = (role, name)
        if key not in real.index:
            continue
        real_row = real.loc[key]
        if isinstance(real_row, pd.DataFrame):
            real_row = real_row.iloc[0]
        before_role = before[before["role"].eq(role)]
        after_role = after[after["role"].eq(role)]
        profile = INDIVIDUAL_SPECIAL_AGE_PROFILES.get(key, "protect")
        row: dict[str, Any] = {
            "role": role,
            "special": name,
            "action": PROFILE_ACTION.get(profile, "protect"),
            "profile": profile,
            "reason": PROTECTED_REASONS.get(key, "Phase 1後にも実在profileとの差が残る"),
            "real_count": int(real_row["n"] * real_row["overall_rate_pct"] / 100 + 0.5),
            "overall_before_pct": rate(before_role, name),
            "overall_after_pct": rate(after_role, name),
            "overall_real_pct": float(real_row["overall_rate_pct"]),
        }
        for band in AGE_LABELS:
            row[f"{band}_before_pct"] = rate(before_role, name, band)
            row[f"{band}_after_pct"] = rate(after_role, name, band)
            row[f"{band}_real_pct"] = float(real_row[f"{band}_rate_pct"])
            row[f"{band}_real_n"] = int(real_row[f"{band}_n"])
        row["gradient_before_pt"] = row["31～34_before_pct"] - row["18～22_before_pct"]
        row["gradient_after_pt"] = row["31～34_after_pct"] - row["18～22_after_pct"]
        row["gradient_real_pt"] = row["31～34_real_pct"] - row["18～22_real_pct"]
        row["mae_before"] = weighted_mae(pd.Series(row), "before")
        row["mae_after"] = weighted_mae(pd.Series(row), "after")
        rows.append(row)
    return pd.DataFrame(rows)


def overall_guard(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ["投手", "野手"]:
        role_before = before[before["role"].eq(role)]
        role_after = after[after["role"].eq(role)]
        names = sorted(
            {name for raw in pd.concat([role_before["normal_names"], role_after["normal_names"]]) for name in safe_json(raw, [])}
        )
        for name in names:
            before_rate = rate(role_before, name)
            after_rate = rate(role_after, name)
            profile = INDIVIDUAL_SPECIAL_AGE_PROFILES.get((role, name), "protect")
            rows.append(
                {
                    "role": role,
                    "special": name,
                    "action": PROFILE_ACTION.get(profile, "protect"),
                    "overall_before_pct": before_rate,
                    "overall_after_pct": after_rate,
                    "change_pt": after_rate - before_rate,
                    "focus": (role, name) in FOCUS_SPECIALS,
                }
            )
    return pd.DataFrame(rows)


def count_stats(frame: pd.DataFrame, role: str, band: str | None) -> dict[str, float]:
    subset = frame[frame["role"].eq(role)]
    if band is not None:
        subset = subset[subset["age_band"].eq(band)]
    values = subset["normal_count"]
    return {
        "n": len(values),
        "mean": float(values.mean()),
        "rate_5plus_pct": pct(values.ge(5)),
        "rate_8plus_pct": pct(values.ge(8)),
        "rate_10plus_pct": pct(values.ge(10)),
    }


def count_guard(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ["投手", "野手"]:
        for band in [None, *AGE_LABELS]:
            prior = count_stats(before, role, band)
            current = count_stats(after, role, band)
            row: dict[str, Any] = {"role": role, "age_band": band or "全体", "n": current["n"]}
            for metric in ["mean", "rate_5plus_pct", "rate_8plus_pct", "rate_10plus_pct"]:
                row[f"{metric}_before"] = prior[metric]
                row[f"{metric}_after"] = current[metric]
                row[f"{metric}_change"] = current[metric] - prior[metric]
                row[f"{metric}_phase1_target"] = PHASE1_TARGETS[role].get(metric, math.nan) if band is None else math.nan
            rows.append(row)
    return pd.DataFrame(rows)


def kind_guard(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ["投手", "野手"]:
        for kind in ["blue", "red", "green", "mixed"]:
            prior = before[before["role"].eq(role)][f"kind_{kind}"]
            current = after[after["role"].eq(role)][f"kind_{kind}"]
            before_rate = pct(prior.ge(1))
            after_rate = pct(current.ge(1))
            rows.append({"role": role, "kind": kind, "before_pct": before_rate, "after_pct": after_rate, "change_pt": after_rate - before_rate})
    return pd.DataFrame(rows)


def seed_count_range(after: pd.DataFrame) -> float:
    rows = []
    for (_run, _role), subset in after.groupby(["run", "role"]):
        rows.append({"run": _run, "role": _role, "mean": subset["normal_count"].mean()})
    table = pd.DataFrame(rows)
    return float(table.groupby("role")["mean"].agg(lambda values: values.max() - values.min()).max())


def write_reports(output: Path, before: pd.DataFrame, after: pd.DataFrame, real_csv: Path, seeds: list[int]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    compare = individual_age_compare(before, after, real_csv)
    overall = overall_guard(before, after)
    counts = count_guard(before, after)
    kinds = kind_guard(before, after)
    protected = protected_guard(before, after)
    constraints = constraint_audit(after)

    compare.to_csv(output / "individual_special_age_compare.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    overall.to_csv(output / "individual_special_overall_guard.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    counts.to_csv(output / "phase1_count_guard.csv", index=False, encoding="utf-8-sig", float_format="%.6f")

    adjusted = compare[compare["action"].ne("protect")]
    protected_rows = compare[compare["action"].eq("protect")]
    max_overall = float(overall["change_pt"].abs().max())
    max_overall_row = overall.loc[overall["change_pt"].abs().idxmax()]
    max_kind = float(kinds["change_pt"].abs().max())
    max_kind_row = kinds.loc[kinds["change_pt"].abs().idxmax()]
    ranked_mismatch = int(protected[protected["field"].eq("ranked_specials")]["mismatches"].sum())
    protected_mismatch = int(protected[protected["field"].ne("ranked_specials")]["mismatches"].sum())
    invalids = int(constraints[constraints["dataset"].eq(AFTER)]["violations"].sum())
    seed_range = seed_count_range(after)
    repro_ok = True
    master = load_master_data()
    for role_index, role in enumerate(["投手", "野手"]):
        for base in seeds:
            seed = base + role_index * 10_000_000
            first = generate_player(role, "架空球団用", master, seed=seed)
            second = generate_player(role, "架空球団用", master, seed=seed)
            repro_ok &= json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False, sort_keys=True)

    lines = ["# 特殊能力年齢構造 Phase 2", "", "## Adjusted", ""]
    for row in adjusted.itertuples(index=False):
        lines.append(f"- {row.role} {row.special}: {row.action}。MAE {row.mae_before:.2f}→{row.mae_after:.2f}")
    lines += ["", "## Protected", ""]
    for row in protected_rows.itertuples(index=False):
        lines.append(f"- {row.role} {row.special}: {row.reason}")
    lines += ["", "## Key results", "", "|役割|特殊能力|action|overall before→after→real|18～22→31～34勾配 before→after→real|MAE before→after|", "|---|---|---|---:|---:|---:|"]
    for row in compare.itertuples(index=False):
        if row.action == "protect" and row.special not in {"球持ち○", "奪三振", "固め打ち", "決勝打"}:
            continue
        lines.append(
            f"|{row.role}|{row.special}|{row.action}|{row.overall_before_pct:.1f}→{row.overall_after_pct:.1f}→{row.overall_real_pct:.1f}|"
            f"{row.gradient_before_pt:.1f}→{row.gradient_after_pt:.1f}→{row.gradient_real_pt:.1f}|{row.mae_before:.2f}→{row.mae_after:.2f}|"
        )
    mean_before = float(adjusted["mae_before"].mean())
    mean_after = float(adjusted["mae_after"].mean())
    lines += ["", "## MAE", "", f"調整対象{len(adjusted)}件の平均weighted MAE: {mean_before:.2f}→{mean_after:.2f}", "", "## Guards", ""]
    for role in ["投手", "野手"]:
        row = counts[counts["role"].eq(role) & counts["age_band"].eq("全体")].iloc[0]
        lines.append(
            f"- {role} Phase 1 count: 平均 {row['mean_before']:.2f}→{row['mean_after']:.2f}、"
            f"5+ {row['rate_5plus_pct_before']:.2f}%→{row['rate_5plus_pct_after']:.2f}%、"
            f"8+ {row['rate_8plus_pct_before']:.2f}%→{row['rate_8plus_pct_after']:.2f}%、"
            f"10+ {row['rate_10plus_pct_before']:.2f}%→{row['rate_10plus_pct_after']:.2f}%"
        )
    lines += [
        f"- individual overall最大変動: {max_overall:.2f}pt（{max_overall_row['role']} {max_overall_row['special']} {float(max_overall_row['change_pt']):+.2f}pt）",
        f"- kind最大変動: {max_kind:.2f}pt（{max_kind_row['role']} {max_kind_row['kind']}）",
        f"- ranked mismatch: {ranked_mismatch}、protected mismatch: {protected_mismatch}",
        f"- constraints違反: {invalids}、seed再現: {'成功' if repro_ok else '失敗'}、seed間count平均最大レンジ: {seed_range:.3f}個",
        "",
        "## Decision",
        "",
    ]
    all_improved = bool((adjusted["mae_after"] < adjusted["mae_before"]).all())
    count_stable = bool(counts[counts["age_band"].eq("全体")]["mean_change"].abs().max() <= 0.10)
    guard_ok = max_overall <= 2.0 and max_kind <= 2.0 and ranked_mismatch == 0 and protected_mismatch == 0 and invalids == 0 and repro_ok
    decision = "Phase 3へ進む" if all_improved and count_stable and guard_ok else "Phase 2微調整" if ranked_mismatch == 0 and protected_mismatch == 0 and invalids == 0 else "Phase 2一部rollback"
    lines += [f"**{decision}**", ""]
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    log_lines = [
        "# Phase 2 implementation log",
        "",
        "- Phase 0の実在profileとPhase 1後の個別率CSVを再利用し、候補20件だけを差分分析。実在Excelは再走査していない。",
        "- 個別base weight、Phase 1個数ロジック、ランク、pro_years、UI、SQLite schemaは変更していない。",
        "- 年齢補正は決定論的なexperience_up / mild_experience_up / flatten_age_biasの3曲線だけを使用。",
        "- Phase 2対象外の親RNGをPhase 1 baselineで消費し、後続生成fingerprintを保護。",
        "",
        "## Mapping",
        "",
    ]
    for (role, name), profile in INDIVIDUAL_SPECIAL_AGE_PROFILES.items():
        log_lines.append(f"- {role} {name}: {profile}")
    (output / "phase2_implementation_log.md").write_text("\n".join(log_lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    before = generate(BEFORE, args.count_per_role_per_seed, args.seeds, apply_profile=False)
    after = generate(AFTER, args.count_per_role_per_seed, args.seeds, apply_profile=True)
    write_reports(args.output_dir, before, after, args.real_individual_csv, args.seeds)
    print(f"Phase 2 comparison complete: before={len(before):,}, after={len(after):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
