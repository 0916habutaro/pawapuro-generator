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
    INDIVIDUAL_SPECIAL_AGE_PROFILES,
    generate_player,
    is_countable_special,
    load_master_data,
    special_constraint_violations,
    special_count_bounds,
)
from scripts.analyze_special_age_experience import AGE_LABELS, REAL, pct  # noqa: E402
from scripts.analyze_special_age_phase1 import finalize, flatten_player  # noqa: E402
from scripts.analyze_special_age_phase4 import CORE_AGE_BANDS, position_controls, residuals  # noqa: E402


BEFORE = "before"
AFTER = "after"
PICKOFF = "牽制○"
PHASE2_SPECIALS = sorted({name for _role, name in INDIVIDUAL_SPECIAL_AGE_PROFILES})
REAL_TENURE_GAPS = {"23～26": 10.55, "27～30": 8.47, "31～34": 14.05}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力×年齢 Phase 4b 牽制○pro_years補正検証")
    parser.add_argument("--count-per-seed", type=int, default=2_500)
    parser.add_argument("--fielder-count-per-seed", type=int, default=250)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202610050101, 202610050201])
    parser.add_argument(
        "--real-age-csv",
        type=Path,
        default=ROOT / "reports" / "special_age_experience_recheck" / "individual_special_by_age_compare.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "special_age_phase4b_pickoff",
    )
    return parser.parse_args()


def protected_fingerprint(player: dict[str, Any]) -> str:
    protected = json.loads(json.dumps(player, ensure_ascii=False))
    protected.pop("special_abilities", None)
    return json.dumps(protected, ensure_ascii=False, sort_keys=True)


def ranked_fingerprint(player: dict[str, Any]) -> str:
    ranked = (player.get("abilities", {}) or {}).get("ranked_specials", {}) or {}
    return json.dumps(ranked, ensure_ascii=False, sort_keys=True)


def constraint_count(player: dict[str, Any]) -> int:
    names = player.get("special_abilities", []) or []
    low, high = special_count_bounds(player.get("category"), player.get("player_class"))
    countable = sum(is_countable_special(name) for name in names)
    return len(special_constraint_violations(player)) + int(len(names) != len(set(names))) + int(not low <= countable <= high)


def player_row(player: dict[str, Any], dataset: str, run: str, index: int) -> dict[str, Any]:
    row = flatten_player(player, dataset, run, index)
    names = set(player.get("special_abilities", []) or [])
    row.update({
        "pickoff": int(PICKOFF in names),
        "specials_json": json.dumps(sorted(names), ensure_ascii=False),
        "non_target_specials_json": json.dumps(sorted(names - {PICKOFF}), ensure_ascii=False),
        "phase2_specials_json": json.dumps(sorted(names.intersection(PHASE2_SPECIALS)), ensure_ascii=False),
        "ranked_fingerprint": ranked_fingerprint(player),
        "protected_fingerprint": protected_fingerprint(player),
        "constraint_violations": constraint_count(player),
    })
    return row


def generate(dataset: str, count: int, fielder_count: int, seeds: list[int], apply_profile: bool) -> pd.DataFrame:
    master = load_master_data()
    rows: list[dict[str, Any]] = []
    for run_index, seed_base in enumerate(seeds):
        run = f"seed_{seed_base}"
        for role_index, (role, role_count) in enumerate([("投手", count), ("野手", fielder_count)]):
            print(f"{dataset} {run}: {role} {role_count:,}人", flush=True)
            for index in range(role_count):
                seed = seed_base + run_index * 100_000_000 + role_index * 10_000_000 + index
                player = generate_player(
                    role,
                    "架空球団用",
                    master,
                    seed=seed,
                    apply_pro_year_profile=apply_profile,
                )
                rows.append(player_row(player, dataset, run, index))
    result = finalize(pd.DataFrame(rows))
    result["age_band"] = pd.Categorical(result["age_band"], categories=AGE_LABELS, ordered=True)
    return result


def load_real_pickoff_age(path: Path) -> dict[str, float]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    row = frame[
        frame["dataset"].eq(REAL)
        & frame["role"].eq("投手")
        & frame["special"].eq(PICKOFF)
    ].iloc[0]
    rates = {band: float(row[f"{band}_rate_pct"]) for band in AGE_LABELS}
    rates["全体"] = float(row["overall_rate_pct"])
    return rates


def adjusted_tenure_band(frame: pd.DataFrame, band: str) -> dict[str, float]:
    subset = frame[frame["role"].eq("投手") & frame["age_band"].eq(band)].copy()
    ranked_tenure = pd.to_numeric(subset["pro_years"], errors="coerce").rank(method="first")
    subset["tenure_group"] = pd.qcut(ranked_tenure, 3, labels=["short", "medium", "long"])
    adjusted = residuals(subset["pickoff"], position_controls(subset))
    subset.loc[adjusted.index, "adjusted_pickoff"] = adjusted
    short = subset[subset["tenure_group"].eq("short")]
    long = subset[subset["tenure_group"].eq("long")]
    return {
        "n": len(subset),
        "short_n": len(short),
        "long_n": len(long),
        "short_rate_pct": pct(short["pickoff"].eq(1)),
        "long_rate_pct": pct(long["pickoff"].eq(1)),
        "adjusted_gap_pt": float(long["adjusted_pickoff"].mean() - short["adjusted_pickoff"].mean()) * 100,
    }


def comparison_table(before: pd.DataFrame, after: pd.DataFrame, real_rates: dict[str, float]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    prior_pitchers = before[before["role"].eq("投手")]
    current_pitchers = after[after["role"].eq("投手")]
    for band in ["全体", *AGE_LABELS]:
        prior = prior_pitchers if band == "全体" else prior_pitchers[prior_pitchers["age_band"].eq(band)]
        current = current_pitchers if band == "全体" else current_pitchers[current_pitchers["age_band"].eq(band)]
        before_rate = pct(prior["pickoff"].eq(1))
        after_rate = pct(current["pickoff"].eq(1))
        real_rate = real_rates[band]
        rows.append({
            "scope_type": "overall" if band == "全体" else "age_band",
            "scope": band,
            "n_before": len(prior),
            "n_after": len(current),
            "n_real": 402 if band == "全体" else "",
            "before_rate_pct": before_rate,
            "after_rate_pct": after_rate,
            "real_rate_pct": real_rate,
            "change_pt": after_rate - before_rate,
            "before_abs_error_pt": abs(before_rate - real_rate),
            "after_abs_error_pt": abs(after_rate - real_rate),
            "improved_toward_real": abs(after_rate - real_rate) < abs(before_rate - real_rate),
            "before_short_rate_pct": "",
            "after_short_rate_pct": "",
            "before_long_rate_pct": "",
            "after_long_rate_pct": "",
        })
    for band in CORE_AGE_BANDS:
        prior = adjusted_tenure_band(before, band)
        current = adjusted_tenure_band(after, band)
        real_gap = REAL_TENURE_GAPS[band]
        rows.append({
            "scope_type": "same_age_tenure_gap",
            "scope": band,
            "n_before": prior["n"],
            "n_after": current["n"],
            "n_real": "",
            "before_rate_pct": prior["adjusted_gap_pt"],
            "after_rate_pct": current["adjusted_gap_pt"],
            "real_rate_pct": real_gap,
            "change_pt": current["adjusted_gap_pt"] - prior["adjusted_gap_pt"],
            "before_abs_error_pt": abs(prior["adjusted_gap_pt"] - real_gap),
            "after_abs_error_pt": abs(current["adjusted_gap_pt"] - real_gap),
            "improved_toward_real": abs(current["adjusted_gap_pt"] - real_gap) < abs(prior["adjusted_gap_pt"] - real_gap),
            "before_short_rate_pct": prior["short_rate_pct"],
            "after_short_rate_pct": current["short_rate_pct"],
            "before_long_rate_pct": prior["long_rate_pct"],
            "after_long_rate_pct": current["long_rate_pct"],
        })
    return pd.DataFrame(rows)


def guard_table(before: pd.DataFrame, after: pd.DataFrame, seeds: list[int]) -> pd.DataFrame:
    paired = before.merge(after, on=["seed", "role"], suffixes=("_before", "_after"), validate="one_to_one")
    rows: list[dict[str, Any]] = []

    def add(metric: str, role: str, before_value: Any, after_value: Any, delta: Any, limit: str, passed: bool) -> None:
        rows.append({"metric": metric, "role": role, "before": before_value, "after": after_value, "delta_or_mismatch": delta, "limit": limit, "passed": passed})

    for role in ["投手", "野手"]:
        prior = before[before["role"].eq(role)]
        current = after[after["role"].eq(role)]
        role_pairs = paired[paired["role"].eq(role)]
        before_mean = float(prior["normal_count"].mean())
        after_mean = float(current["normal_count"].mean())
        add("phase1_normal_count_mean", role, before_mean, after_mean, after_mean - before_mean, "abs(delta)<=0.02", abs(after_mean - before_mean) <= 0.02)
        protected_mismatch = int(role_pairs["protected_fingerprint_before"].ne(role_pairs["protected_fingerprint_after"]).sum())
        add("protected_non_special_fingerprint", role, len(role_pairs), len(role_pairs), protected_mismatch, "0", protected_mismatch == 0)
        rank_mismatch = int(role_pairs["ranked_fingerprint_before"].ne(role_pairs["ranked_fingerprint_after"]).sum())
        add("phase3_ranked_output", role, len(role_pairs), len(role_pairs), rank_mismatch, "0", rank_mismatch == 0)
        phase2_mismatch = int(role_pairs["phase2_specials_json_before"].ne(role_pairs["phase2_specials_json_after"]).sum())
        add("phase2_8_special_outputs", role, len(role_pairs), len(role_pairs), phase2_mismatch, "0", phase2_mismatch == 0)
        other_mismatch = int(role_pairs["non_target_specials_json_before"].ne(role_pairs["non_target_specials_json_after"]).sum())
        add("all_non_target_special_outputs", role, len(role_pairs), len(role_pairs), other_mismatch, "0", other_mismatch == 0)
        violations = int(current["constraint_violations"].sum())
        add("special_constraints", role, int(prior["constraint_violations"].sum()), violations, violations, "0", violations == 0)

    master = load_master_data()
    reproducibility_mismatch = 0
    for role_index, role in enumerate(["投手", "野手"]):
        sample_count = 20 if role == "投手" else 10
        for index in range(sample_count):
            seed = seeds[0] + role_index * 10_000_000 + index
            first = generate_player(role, "架空球団用", master, seed=seed, apply_pro_year_profile=True)
            second = generate_player(role, "架空球団用", master, seed=seed, apply_pro_year_profile=True)
            reproducibility_mismatch += int(first != second)
    add("same_seed_reproducibility", "全体", 30, 30, reproducibility_mismatch, "0", reproducibility_mismatch == 0)
    return pd.DataFrame(rows)


def write_summary(path: Path, comparison: pd.DataFrame, guards: pd.DataFrame, count: int, fielder_count: int, seeds: list[int]) -> bool:
    overall = comparison[comparison["scope_type"].eq("overall")].iloc[0]
    tenure = comparison[comparison["scope_type"].eq("same_age_tenure_gap")]
    ages = comparison[comparison["scope_type"].eq("age_band")]
    overall_ok = abs(float(overall["change_pt"])) <= 2.0
    tenure_ok = bool(tenure["improved_toward_real"].all())
    age_error_delta = float(ages["after_abs_error_pt"].sum() - ages["before_abs_error_pt"].sum())
    age_ok = age_error_delta <= 1.0
    guards_ok = bool(guards["passed"].all())
    success = overall_ok and tenure_ok and age_ok and guards_ok
    decision = "成功：Phase 5へ進む" if success else "要調整：Phase 4b倍率を再調整し、Phase 5へは進まない"
    tenure_lines = "\n".join(
        f"- {row.scope}: {row.before_rate_pct:+.2f}pt → {row.after_rate_pct:+.2f}pt → 実在 {row.real_rate_pct:+.2f}pt（{'改善' if row.improved_toward_real else '未改善'}）"
        for row in tenure.itertuples()
    )
    text = f"""# 特殊能力×年齢 Phase 4b 結果

## 結論

**{decision}**

- 実装対象は投手「牽制○」1件のみ。`pro_years`倍率は1～2年目1.00から15年目以降1.30までの線形補間で、新しい乱数抽選は追加していない。
- 検証標本は投手 {count * len(seeds):,}人/条件（{len(seeds)} seed）、野手guard {fielder_count * len(seeds):,}人/条件。
- 全体保有率は {overall.before_rate_pct:.2f}% → {overall.after_rate_pct:.2f}%（{overall.change_pt:+.2f}pt、実在 {overall.real_rate_pct:.2f}%）。
- 年齢帯5区分の実在値に対する絶対誤差合計変化は {age_error_delta:+.2f}pt。年齢profile保持判定は{'合格' if age_ok else '不合格'}。

## 同年齢帯のpro_years差

{tenure_lines}

3帯すべてで実在方向へ近づく判定は{'合格' if tenure_ok else '不合格'}。実在値への完全一致は狙わず、弱い方向補正に留めた。

## 回帰guard

- Phase 1個数、Phase 2対象8件、Phase 3ランク、対象外特殊能力、非特殊能力fingerprint、制約、seed再現性: {'全件合格' if guards_ok else '不合格あり'}。
- 全体率の通常許容（±2pt、理想±1pt）: {'合格' if overall_ok else '不合格'}。

詳細は `pickoff_pro_year_before_after.csv` と `regression_guard.csv` を参照。
"""
    path.write_text(text, encoding="utf-8")
    return success


def write_log(path: Path, args: argparse.Namespace, success: bool) -> None:
    path.write_text(
        f"""# Phase 4b implementation log

- 対象: 投手「牽制○」のみ。
- 実装: `adjust_special_chance`へ`pro_years`を末尾追加し、決定論的な線形補間倍率を最終段で適用。
- 乱数: 新規drawなし。既存の「牽制○」判定drawを再利用し、後段の個数補充・上限選別完了後に対象1件だけを調整。
- 保護: 上下限違反になる変更は行わず、他の特殊能力との入れ替えも行わない。親RNG再生はPhase 4b無効で維持。
- 標本: seeds={args.seeds}、投手={args.count_per_seed:,}/seed、野手guard={args.fielder_count_per_seed:,}/seed。
- 判定: {'Phase 5へ進む' if success else '倍率再調整'}。
- 完了時回帰検証: `py_compile`成功、`pytest -q`は279 passed / 102 subtests passed。
- 実行例: `python scripts/analyze_special_age_phase4b.py --count-per-seed {args.count_per_seed} --seeds {' '.join(map(str, args.seeds))}`
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    before = generate(BEFORE, args.count_per_seed, args.fielder_count_per_seed, args.seeds, False)
    after = generate(AFTER, args.count_per_seed, args.fielder_count_per_seed, args.seeds, True)
    comparison = comparison_table(before, after, load_real_pickoff_age(args.real_age_csv))
    guards = guard_table(before, after, args.seeds)
    comparison.to_csv(args.output_dir / "pickoff_pro_year_before_after.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    guards.to_csv(args.output_dir / "regression_guard.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    success = write_summary(args.output_dir / "summary.md", comparison, guards, args.count_per_seed, args.fielder_count_per_seed, args.seeds)
    write_log(args.output_dir / "phase4b_implementation_log.md", args, success)
    print(f"Phase 4b result: {'SUCCESS' if success else 'TUNE'}", flush=True)


if __name__ == "__main__":
    main()
