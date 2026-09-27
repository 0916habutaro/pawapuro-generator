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

from app import generate_player, load_master_data  # noqa: E402
from scripts.analyze_special_age_experience import AGE_LABELS, REAL, age_band, pct  # noqa: E402
from scripts.analyze_special_age_phase1 import constraint_audit, finalize, flatten_player  # noqa: E402


BEFORE = "before"
AFTER = "after"
RANKS = list("ABCDEFG")
PHASE2_SPECIALS = [
    ("投手", "変化球中心"), ("投手", "逃げ球"), ("投手", "キレ○"),
    ("野手", "選球眼"), ("野手", "積極守備"), ("野手", "バント○"),
    ("野手", "満塁男"), ("野手", "三振"),
]
DEFAULT_REAL_XLSX = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力年齢構造 Phase 3 ranked差分分析")
    parser.add_argument("--count-per-role-per-seed", type=int, default=2_500)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202609280101, 202609280201])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "special_age_phase3_ranked")
    parser.add_argument(
        "--real-ranked-csv",
        type=Path,
        default=ROOT / "reports" / "special_age_experience_recheck" / "ranked_special_by_age_compare.csv",
    )
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL_XLSX)
    return parser.parse_args()


def protected_fingerprint(player: dict[str, Any]) -> str:
    protected = json.loads(json.dumps(player, ensure_ascii=False))
    abilities = protected.get("abilities", {})
    if isinstance(abilities, dict):
        abilities.pop("ranked_specials", None)
    return json.dumps(protected, ensure_ascii=False, sort_keys=True)


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
                    apply_individual_age_profile=True,
                    apply_ranked_age_profile=apply_profile,
                )
                row = flatten_player(player, dataset, run, index)
                row["protected_fingerprint"] = protected_fingerprint(player)
                row["phase2_specials_json"] = json.dumps(player.get("special_abilities", []), ensure_ascii=False, sort_keys=True)
                rows.append(row)
    frame = finalize(pd.DataFrame(rows))
    frame["age_band"] = pd.Categorical(frame["age_band"], categories=AGE_LABELS, ordered=True)
    return frame


def load_real_rank_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    return frame[frame["dataset"].eq(REAL)].copy()


def load_real_abc_tails(path: Path) -> pd.DataFrame:
    """Phase 0 CSVにないABC 2+/3+だけを2 sheet・必要列に限定して補完する。"""
    players = pd.read_excel(path, sheet_name="players", usecols=["team", "name", "role", "age"])
    specials = pd.read_excel(path, sheet_name="special_abilities", usecols=["team", "name", "special_kind", "special"])
    ranked = specials[specials["special_kind"].eq("rank")].copy()
    ranked["rank"] = ranked["special"].fillna("").astype(str).str[-1]
    ranked["abc"] = ranked["rank"].isin(["A", "B", "C"]).astype(int)
    counts = ranked.groupby(["team", "name"], dropna=False)["abc"].sum().rename("rank_ABC").reset_index()
    merged = players.merge(counts, on=["team", "name"], how="left")
    merged["rank_ABC"] = merged["rank_ABC"].fillna(0).astype(int)
    merged["age_band"] = pd.to_numeric(merged["age"], errors="coerce").map(age_band)
    return merged


def generated_stats(frame: pd.DataFrame) -> dict[str, float]:
    result = {rank: float(frame[f"rank_{rank}"].mean()) for rank in RANKS}
    result.update({
        "ABC": float(frame["rank_ABC"].mean()),
        "AB": float(frame["rank_AB"].mean()),
        "EFG": float(frame["rank_EFG"].mean()),
        "ABC_1plus_pct": pct(frame["rank_ABC"].ge(1)),
        "ABC_2plus_pct": pct(frame["rank_ABC"].ge(2)),
        "ABC_3plus_pct": pct(frame["rank_ABC"].ge(3)),
        "AB_1plus_pct": pct(frame["rank_AB"].ge(1)),
    })
    return result


def real_metric(real: pd.DataFrame, role: str, band: str, metric: str, field: str = "mean_count") -> float:
    found = real[real["role"].eq(role) & real["band"].eq(band) & real["metric"].eq(metric)]
    return float(found.iloc[0][field]) if len(found) else math.nan


def weighted_real_metric(real: pd.DataFrame, role: str, metric: str, field: str = "mean_count") -> float:
    rows = real[real["role"].eq(role) & real["metric"].eq(metric)].copy()
    weights = pd.to_numeric(rows["n"], errors="coerce")
    values = pd.to_numeric(rows[field], errors="coerce")
    return float((values * weights).sum() / weights.sum())


def real_tail_stats(real_tails: pd.DataFrame, role: str, band: str | None = None) -> dict[str, float]:
    subset = real_tails[real_tails["role"].eq(role)]
    if band is not None:
        subset = subset[subset["age_band"].eq(band)]
    return {
        "ABC_2plus_pct": pct(subset["rank_ABC"].ge(2)),
        "ABC_3plus_pct": pct(subset["rank_ABC"].ge(3)),
    }


def age_comparison(before: pd.DataFrame, after: pd.DataFrame, real: pd.DataFrame, real_tails: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for role in ["投手", "野手"]:
        for band in AGE_LABELS:
            prior = before[before["role"].eq(role) & before["age_band"].eq(band)]
            current = after[after["role"].eq(role) & after["age_band"].eq(band)]
            prior_stats = generated_stats(prior)
            current_stats = generated_stats(current)
            tail = real_tail_stats(real_tails, role, band)
            real_n_rows = real[real["role"].eq(role) & real["band"].eq(band)]
            row: dict[str, Any] = {
                "role": role,
                "age_band": band,
                "n_before": len(prior),
                "n_after": len(current),
                "n_real": int(real_n_rows.iloc[0]["n"]) if len(real_n_rows) else 0,
            }
            for metric in ["A", "B", "C", "ABC", "EFG"]:
                real_name = {"ABC": "A/B/C", "EFG": "E/F/G"}.get(metric, metric)
                row[f"{metric.lower()}_mean_before"] = prior_stats[metric]
                row[f"{metric.lower()}_mean_after"] = current_stats[metric]
                row[f"{metric.lower()}_mean_real"] = real_metric(real, role, band, real_name)
            for metric, real_name in [("ABC_1plus_pct", "A/B/C"), ("AB_1plus_pct", "A/B")]:
                key = metric.lower()
                row[f"{key}_before"] = prior_stats[metric]
                row[f"{key}_after"] = current_stats[metric]
                row[f"{key}_real"] = real_metric(real, role, band, real_name, "holder_rate_pct")
            for metric in ["ABC_2plus_pct", "ABC_3plus_pct"]:
                key = metric.lower()
                row[f"{key}_before"] = prior_stats[metric]
                row[f"{key}_after"] = current_stats[metric]
                row[f"{key}_real"] = tail[metric]
            row["d_mean_before"] = prior_stats["D"]
            row["d_mean_after"] = current_stats["D"]
            row["d_mean_change"] = current_stats["D"] - prior_stats["D"]
            rows.append(row)
    return pd.DataFrame(rows)


def overall_guard(before: pd.DataFrame, after: pd.DataFrame, real: pd.DataFrame, real_tails: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for role in ["投手", "野手"]:
        prior = generated_stats(before[before["role"].eq(role)])
        current = generated_stats(after[after["role"].eq(role)])
        tail = real_tail_stats(real_tails, role)
        row: dict[str, Any] = {"role": role, "n_before": int(before["role"].eq(role).sum()), "n_after": int(after["role"].eq(role).sum())}
        for metric in ["A", "B", "C", "ABC", "EFG"]:
            real_name = {"ABC": "A/B/C", "EFG": "E/F/G"}.get(metric, metric)
            key = metric.lower()
            row[f"{key}_mean_before"] = prior[metric]
            row[f"{key}_mean_after"] = current[metric]
            row[f"{key}_mean_real"] = weighted_real_metric(real, role, real_name)
            row[f"{key}_mean_change"] = current[metric] - prior[metric]
        for metric, real_name in [("ABC_1plus_pct", "A/B/C"), ("AB_1plus_pct", "A/B")]:
            key = metric.lower()
            row[f"{key}_before"] = prior[metric]
            row[f"{key}_after"] = current[metric]
            row[f"{key}_real"] = weighted_real_metric(real, role, real_name, "holder_rate_pct")
        for metric in ["ABC_2plus_pct", "ABC_3plus_pct"]:
            key = metric.lower()
            row[f"{key}_before"] = prior[metric]
            row[f"{key}_after"] = current[metric]
            row[f"{key}_real"] = tail[metric]
        row["d_mean_before"] = prior["D"]
        row["d_mean_after"] = current["D"]
        row["d_mean_change"] = current["D"] - prior["D"]
        rows.append(row)
    return pd.DataFrame(rows)


def count_stats(frame: pd.DataFrame, role: str) -> dict[str, float]:
    values = frame[frame["role"].eq(role)]["normal_count"]
    return {
        "mean": float(values.mean()),
        "rate_5plus_pct": pct(values.ge(5)),
        "rate_8plus_pct": pct(values.ge(8)),
        "rate_10plus_pct": pct(values.ge(10)),
    }


def regression_guard(before: pd.DataFrame, after: pd.DataFrame, seeds: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for role in ["投手", "野手"]:
        prior = count_stats(before, role)
        current = count_stats(after, role)
        for metric in prior:
            rows.append({"guard": "phase1_count", "role": role, "item": metric, "before": prior[metric], "after": current[metric], "change": current[metric] - prior[metric], "compared": "", "mismatches": 0, "status": "ok"})
    for role, name in PHASE2_SPECIALS:
        before_role = before[before["role"].eq(role)]
        after_role = after[after["role"].eq(role)]
        before_rate = pct(before_role["normal_names"].str.contains(f'"{name}"', regex=False))
        after_rate = pct(after_role["normal_names"].str.contains(f'"{name}"', regex=False))
        rows.append({"guard": "phase2_individual", "role": role, "item": name, "before": before_rate, "after": after_rate, "change": after_rate - before_rate, "compared": len(before_role), "mismatches": 0, "status": "ok" if before_rate == after_rate else "ng"})

    left = before.set_index(["run", "seed", "role"]).sort_index()
    right = after.set_index(["run", "seed", "role"]).sort_index()
    common = left.index.intersection(right.index)
    for field, label in [("protected_fingerprint", "protected_fingerprint"), ("phase2_specials_json", "phase2_special_list")]:
        mismatches = int((left.loc[common, field].astype(str) != right.loc[common, field].astype(str)).sum())
        rows.append({"guard": "protected", "role": "全体", "item": label, "before": "", "after": "", "change": "", "compared": len(common), "mismatches": mismatches, "status": "ok" if mismatches == 0 else "ng"})

    constraints = constraint_audit(after)
    for item in constraints.itertuples(index=False):
        rows.append({"guard": "constraints", "role": "全体", "item": item.check, "before": "", "after": item.violations, "change": "", "compared": item.players, "mismatches": item.violations, "status": "ok" if item.violations == 0 else "ng"})

    master = load_master_data()
    reproducible = True
    for role_index, role in enumerate(["投手", "野手"]):
        for base in seeds:
            seed = base + role_index * 10_000_000
            first = generate_player(role, "架空球団用", master, seed=seed)
            second = generate_player(role, "架空球団用", master, seed=seed)
            reproducible &= json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False, sort_keys=True)
    rows.append({"guard": "seed", "role": "全体", "item": "same_seed_reproducibility", "before": "", "after": "", "change": "", "compared": len(seeds) * 2, "mismatches": 0 if reproducible else 1, "status": "ok" if reproducible else "ng"})
    return pd.DataFrame(rows)


def class_summary(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ["投手", "野手"]:
        for player_class in ["スター級", "一軍主力級", "ベテラン型", "一軍控え級", "二軍級"]:
            prior = before[before["role"].eq(role) & before["player_class"].eq(player_class)]
            current = after[after["role"].eq(role) & after["player_class"].eq(player_class)]
            rows.append({"role": role, "player_class": player_class, "n": len(current), "abc_before": prior["rank_ABC"].mean(), "abc_after": current["rank_ABC"].mean()})
    return pd.DataFrame(rows)


def seed_ranges(after: pd.DataFrame) -> tuple[float, float]:
    grouped = after.groupby(["run", "role", "age_band"], observed=False)["rank_ABC"].mean().reset_index()
    ranges = grouped.groupby(["role", "age_band"], observed=False)["rank_ABC"].agg(lambda values: values.max() - values.min()).reset_index(name="range")
    all_bands = float(ranges["range"].max())
    main_bands = float(ranges[ranges["age_band"].isin(AGE_LABELS[:4])]["range"].max())
    return main_bands, all_bands


def write_reports(output: Path, before: pd.DataFrame, after: pd.DataFrame, real: pd.DataFrame, real_tails: pd.DataFrame, seeds: list[int]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    ages = age_comparison(before, after, real, real_tails)
    overall = overall_guard(before, after, real, real_tails)
    guards = regression_guard(before, after, seeds)
    classes = class_summary(before, after)
    variation_main, variation_all = seed_ranges(after)

    ages.to_csv(output / "ranked_age_before_after.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    overall.to_csv(output / "ranked_overall_guard.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    guards.to_csv(output / "phase12_regression_guard.csv", index=False, encoding="utf-8-sig", float_format="%.6f")

    lines = ["# 特殊能力年齢構造 Phase 3", "", "## Overall", "", "|役割|指標|before|after|real|", "|---|---|---:|---:|---:|"]
    for row in overall.itertuples(index=False):
        for metric, label in [("a", "A"), ("b", "B"), ("c", "C"), ("abc", "A/B/C"), ("efg", "E/F/G")]:
            lines.append(f"|{row.role}|{label}|{getattr(row, metric + '_mean_before'):.3f}|{getattr(row, metric + '_mean_after'):.3f}|{getattr(row, metric + '_mean_real'):.3f}|")
    lines += ["", "## Age", "", "|役割|年齢帯|A/B/C before|after|real|", "|---|---|---:|---:|---:|"]
    for row in ages.itertuples(index=False):
        lines.append(f"|{row.role}|{row.age_band}|{row.abc_mean_before:.3f}|{row.abc_mean_after:.3f}|{row.abc_mean_real:.3f}|")
    lines += ["", "## Gradient", "", "|役割|18～22→31～34 before|after|real|", "|---|---:|---:|---:|"]
    for role in ["投手", "野手"]:
        role_rows = ages[ages["role"].eq(role)].set_index("age_band")
        before_gradient = role_rows.loc["31～34", "abc_mean_before"] - role_rows.loc["18～22", "abc_mean_before"]
        after_gradient = role_rows.loc["31～34", "abc_mean_after"] - role_rows.loc["18～22", "abc_mean_after"]
        real_gradient = role_rows.loc["31～34", "abc_mean_real"] - role_rows.loc["18～22", "abc_mean_real"]
        lines.append(f"|{role}|{before_gradient:.3f}|{after_gradient:.3f}|{real_gradient:.3f}|")
    lines += ["", "## player_class", "", "|役割|class|N|A/B/C before|after|", "|---|---|---:|---:|---:|"]
    for row in classes.itertuples(index=False):
        lines.append(f"|{row.role}|{row.player_class}|{row.n}|{row.abc_before:.3f}|{row.abc_after:.3f}|")

    max_count_change = float(pd.to_numeric(guards[guards["guard"].eq("phase1_count")]["change"]).abs().max())
    max_phase2_change = float(pd.to_numeric(guards[guards["guard"].eq("phase2_individual")]["change"]).abs().max())
    protected_mismatch = int(guards[guards["item"].eq("protected_fingerprint")]["mismatches"].sum())
    constraint_violations = int(guards[guards["guard"].eq("constraints")]["mismatches"].sum())
    repro_ok = bool((guards[guards["guard"].eq("seed")]["status"] == "ok").all())
    lines += [
        "", "## Guards", "",
        f"- Phase 1 count最大変動: {max_count_change:.6f}",
        f"- Phase 2対象8件最大変動: {max_phase2_change:.6f}pt",
        f"- protected fingerprint mismatch: {protected_mismatch}",
        f"- constraints違反: {constraint_violations}",
        f"- seed再現: {'成功' if repro_ok else '失敗'}",
        f"- seed間A/B/C平均最大レンジ（主要4帯）: {variation_main:.3f}",
        f"- seed間A/B/C平均最大レンジ（35+参考を含む）: {variation_all:.3f}",
        "", "## Decision", "",
    ]
    directions_ok = True
    for role in ["投手", "野手"]:
        role_rows = ages[ages["role"].eq(role)].set_index("age_band")
        directions_ok &= role_rows.loc["18～22", "abc_mean_after"] < role_rows.loc["18～22", "abc_mean_before"]
        directions_ok &= role_rows.loc["27～30", "abc_mean_after"] > role_rows.loc["27～30", "abc_mean_before"]
        directions_ok &= role_rows.loc["31～34", "abc_mean_after"] > role_rows.loc["31～34", "abc_mean_before"]
    overall_stable = bool(overall["abc_mean_change"].abs().max() <= 0.10 and overall["efg_mean_change"].abs().max() <= 0.05)
    guards_ok = max_count_change == 0 and max_phase2_change == 0 and protected_mismatch == 0 and constraint_violations == 0 and repro_ok
    decision = "Phase 4限定検証" if directions_ok and overall_stable and guards_ok else "Phase 3微調整"
    lines += [f"**{decision}**", ""]
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    log = [
        "# Phase 3 implementation log", "",
        "- Phase 0 ranked CSVをbaselineとし、A/B/C 2+/3+だけ実在Excelのplayers・special_abilities必要列から補完した。全Excel再分析は行っていない。",
        "- Phase 1個数ロジックとPhase 2個別profileは変更していない。",
        "- 共通の滑らかな年齢curve、player_class、group関連能力だけでA/B/C weightを決定論的に再配分した。",
        "- 若手はsoft suppression。スター級・高関連能力では抑制を弱め、hard banは設けていない。",
        "- 27歳以降は一軍主力級・スター級・ベテラン型を中心にD→C、一部C→Bを許可し、A weightは増やしていない。",
        "- 二軍級・若手素材型は年齢だけではboostしない。pro_yearsと新規random drawは追加していない。",
        "- 捕手30歳以上の旧年齢補正はPhase 3有効時に共通profileへ統合し、二重適用を防いだ。",
    ]
    (output / "phase3_implementation_log.md").write_text("\n".join(log) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    before = generate(BEFORE, args.count_per_role_per_seed, args.seeds, apply_profile=False)
    after = generate(AFTER, args.count_per_role_per_seed, args.seeds, apply_profile=True)
    real = load_real_rank_table(args.real_ranked_csv)
    real_tails = load_real_abc_tails(args.real_xlsx)
    write_reports(args.output_dir, before, after, real, real_tails, args.seeds)
    print(f"Phase 3 comparison complete: before={len(before):,}, after={len(after):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
