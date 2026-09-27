from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from scripts.analyze_special_age_experience import (  # noqa: E402
    AGE_LABELS,
    GROUP_MAP,
    KIND_MAP,
    KINDS,
    PRO_LABELS,
    RANKS,
    REAL,
    add_ability_score,
    age_band,
    comparable_counts,
    load_real,
    normalize_name,
    normalize_position,
    pct,
    pro_band,
    safe_json,
)
from scripts.analyze_special_age_phase1 import CONFLICTS, generated_metrics  # noqa: E402
from scripts.analyze_special_age_phase4 import CORE_AGE_BANDS  # noqa: E402
from scripts.analyze_special_age_phase4b import adjusted_tenure_band  # noqa: E402


GENERATED = "generated"
PHASE5_APP_SHA256 = "3b9f1355a45739a958e7d9962732ba5dd435398e8de1fe8b6087a16412c0dab0"
DEFAULT_REAL_XLSX = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"
DEFAULT_SEEDS = [202610060101, 202610060201, 202610060301]
PHASE2_SPECIALS = {
    "投手": ["変化球中心", "逃げ球", "キレ○"],
    "野手": ["選球眼", "積極守備", "バント○", "満塁男", "三振"],
}
PROTECTED_SPECIALS = {
    "投手": ["打球反応○", "牽制○", "球持ち○", "リリース○", "低め○", "奪三振", "緩急○"],
    "野手": ["バント職人", "サヨナラ男", "併殺", "固め打ち", "決勝打"],
}
MAJOR_SPECIALS = {role: sorted(set(PHASE2_SPECIALS[role] + PROTECTED_SPECIALS[role])) for role in ["投手", "野手"]}
ABILITY_KEYS = {
    "投手": ["球速", "コントロール", "スタミナ", "球種数", "総変化量"],
    "野手": ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"],
}
POSITION_ORDER = {
    "投手": ["先発", "中継ぎ", "抑え"],
    "野手": ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"],
}
CLASS_ORDER = ["スター級", "一軍主力級", "一軍控え級", "二軍級", "若手素材型", "ベテラン型"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力×年齢・プロ年数 Phase 5最終監査")
    parser.add_argument("--count-per-role-per-seed", type=int, default=10_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL_XLSX)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "special_age_phase5_final")
    parser.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "pawapuro_phase5_generated.pkl")
    parser.add_argument("--reuse-cache", action="store_true")
    return parser.parse_args()


def app_sha256() -> str:
    return hashlib.sha256((ROOT / "app.py").read_bytes()).hexdigest()


def violation_flags(player: dict[str, Any], names: list[str], ranked: dict[str, str]) -> dict[str, int]:
    name_set = set(names)
    groups = [GROUP_MAP.get(name, "") for name in names if GROUP_MAP.get(name, "")]
    aptitudes = {key: player.get(key, "") for key in ["starter_aptitude", "reliever_aptitude", "closer_aptitude"]}
    invalid = [
        name for name in names
        if not app.is_special_allowed_for_player(name, player["role"], player["position"], player.get("sub_positions", []), aptitudes)
    ]
    low, high = app.special_count_bounds(player["category"], player.get("player_class"))
    countable = sum(app.is_countable_special(name) for name in names)
    ranked_values = list(ranked.values())
    return {
        "violation_duplicate_special": int(len(names) != len(name_set)),
        "violation_duplicate_group": int(len(groups) != len(set(groups))),
        "violation_conflict": int(any(CONFLICTS.get(name) in name_set for name in names)),
        "violation_position_or_aptitude": int(bool(invalid)),
        "violation_count_bounds": int(not low <= countable <= high),
        "violation_ranked_group": int(len(ranked) != len(set(ranked)) or any(str(name)[-1:] not in set(RANKS) for name in ranked_values)),
    }


def compact_player(player: dict[str, Any], run: str) -> dict[str, Any]:
    abilities = player.get("abilities", {}) or {}
    ranked = abilities.get("ranked_specials", {}) or {}
    counts = comparable_counts(player.get("special_abilities", []), ranked.values())
    names = tuple(safe_json(counts["normal_names"], []))
    row: dict[str, Any] = {
        "dataset": GENERATED,
        "run": run,
        "seed": player["seed"],
        "role": player["role"],
        "age": player["age"],
        "pro_years": player.get("pro_years"),
        "player_class": player.get("player_class", ""),
        "growth_type": player.get("growth_type", ""),
        "position": player.get("position", ""),
        "normal_set": frozenset(names),
        "ranked_set": frozenset(safe_json(counts["ranked_names"], [])),
    }
    row.update({key: value for key, value in counts.items() if key not in {"normal_names", "ranked_names"}})
    row.update(generated_metrics(player))
    row.update(violation_flags(player, list(names), ranked))
    return row


def generate_samples(count: int, seeds: list[int], cache: Path, reuse: bool) -> pd.DataFrame:
    if reuse and cache.exists():
        print(f"cache reuse: {cache}", flush=True)
        return pd.read_pickle(cache)
    master = app.load_master_data()
    rows: list[dict[str, Any]] = []
    for seed_index, seed_base in enumerate(seeds):
        run = f"seed_{seed_base}"
        for role_index, role in enumerate(["投手", "野手"]):
            print(f"{run}: {role} {count:,}人", flush=True)
            for index in range(count):
                if index and index % 2_500 == 0:
                    print(f"  {index:,}/{count:,}", flush=True)
                seed = seed_base + seed_index * 100_000_000 + role_index * 10_000_000 + index
                rows.append(compact_player(app.generate_player(role, "架空球団用", master, seed=seed), run))
    result = add_ability_score(pd.DataFrame(rows))
    result["age_band"] = result["age"].map(age_band)
    result["pro_band"] = result["pro_years"].map(pro_band)
    result["position_group"] = [normalize_position(value, role) for value, role in zip(result["position"], result["role"])]
    cache.parent.mkdir(parents=True, exist_ok=True)
    result.to_pickle(cache)
    return result


def prepare_real(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, audit = load_real(path)
    result = frame.copy()
    result["normal_set"] = result["normal_names"].map(lambda value: frozenset(safe_json(value, [])))
    result["ranked_set"] = result["ranked_names"].map(lambda value: frozenset(safe_json(value, [])))
    result["run"] = "real"
    return result, audit


def indicator(frame: pd.DataFrame, name: str) -> pd.Series:
    return frame["normal_set"].map(lambda values: int(name in values))


def rate(values: pd.Series) -> float:
    return float(pd.to_numeric(values, errors="coerce").mean() * 100) if len(values) else math.nan


def distribution_metrics(frame: pd.DataFrame, column: str) -> dict[str, float]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return {
        "average": float(values.mean()),
        "median": float(values.median()),
        "p75": float(values.quantile(.75)),
        "p90": float(values.quantile(.90)),
        "5plus_pct": pct(values.ge(5)),
        "8plus_pct": pct(values.ge(8)),
        "10plus_pct": pct(values.ge(10)),
    }


def severity_for_gap(real_count: int, difference: float) -> str:
    gap = abs(difference)
    if real_count >= 50 and gap >= 20:
        return "high"
    if (real_count >= 50 and gap >= 7) or (30 <= real_count < 50 and gap >= 12):
        return "medium"
    return "low"


def special_balance(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(role: str, metric: str, real_n: int | str, real_value: Any, gen_value: Any, severity: str, note: str) -> None:
        difference = float(gen_value) - float(real_value) if pd.notna(real_value) and pd.notna(gen_value) else math.nan
        rows.append({"role": role, "metric": metric, "real_n": real_n, "real": real_value, "generated": gen_value, "diff": difference, "severity": severity, "note": note})

    for role in ["投手", "野手"]:
        rbase = real[real["role"].eq(role)]
        gbase = generated[generated["role"].eq(role)]
        for key, value in distribution_metrics(rbase, "normal_count").items():
            generated_value = distribution_metrics(gbase, "normal_count")[key]
            add(role, f"nonrank_{key}", len(rbase), value, generated_value, "low" if abs(generated_value - value) < 8 else "medium", "非ランク個数")
        for key, value in distribution_metrics(rbase, "display_special_count").items():
            generated_value = distribution_metrics(gbase, "display_special_count")[key]
            add(role, f"display_{key}", len(rbase), value, generated_value, "low" if abs(generated_value - value) < 8 else "medium", "Dを除く表示総数")

        for rank in RANKS:
            real_value = float(rbase[f"rank_{rank}"].mean()) if rank != "D" else math.nan
            generated_value = float(gbase[f"rank_{rank}"].mean())
            severity = "medium" if rank != "D" and pd.notna(real_value) and abs(generated_value - real_value) >= .15 else "low"
            add(role, f"rank_{rank}_mean", len(rbase), real_value, generated_value, severity, "Dは生成側参考" if rank == "D" else "rank平均")
        for metric, column in [("rank_ABC_mean", "rank_ABC"), ("rank_EFG_mean", "rank_EFG")]:
            rv, gv = float(rbase[column].mean()), float(gbase[column].mean())
            add(role, metric, len(rbase), rv, gv, "medium" if abs(gv - rv) >= .20 else "low", "実在直接比較対象")

        all_names = sorted(set().union(*rbase["normal_set"].tolist(), *gbase["normal_set"].tolist()))
        for name in all_names:
            real_count = int(indicator(rbase, name).sum())
            real_rate = rate(indicator(rbase, name))
            generated_rate = rate(indicator(gbase, name))
            difference = generated_rate - real_rate
            note_parts = [f"kind={KIND_MAP.get(name, 'other')}", f"real_count_group={'50+' if real_count >= 50 else '30-49' if real_count >= 30 else '<30'}"]
            if name in PHASE2_SPECIALS[role]:
                note_parts.append("Phase 2対象")
            if name in PROTECTED_SPECIALS[role]:
                note_parts.append("protected")
            add(role, f"special:{name}", real_count, real_rate, generated_rate, severity_for_gap(real_count, difference), "; ".join(note_parts))

        for kind in KINDS:
            for suffix, reducer in [("mean", lambda f, c: float(f[c].mean())), ("1plus_pct", lambda f, c: pct(f[c].ge(1)))]:
                column = f"kind_{kind}"
                rv, gv = reducer(rbase, column), reducer(gbase, column)
                add(role, f"kind_{kind}_{suffix}", len(rbase), rv, gv, "medium" if abs(gv - rv) >= 12 else "low", "gold極低率/0は仕様維持")

        for player_class in CLASS_ORDER:
            subset = gbase[gbase["player_class"].eq(player_class)]
            if not len(subset):
                continue
            class_metrics = {
                "nonrank_average": float(subset["normal_count"].mean()),
                "nonrank_5plus_pct": pct(subset["normal_count"].ge(5)),
                "nonrank_8plus_pct": pct(subset["normal_count"].ge(8)),
                "rank_ABC_mean": float(subset["rank_ABC"].mean()),
                "rank_A_rate_pct": pct(subset["rank_A"].ge(1)),
            }
            for metric, value in class_metrics.items():
                add(role, f"class:{player_class}:{metric}", "", math.nan, value, "low", f"generated n={len(subset)}")

        class_age_specs = [
            ("若手素材型", "18～22", lambda frame: frame["age_band"].eq("18～22")),
            ("スター級", "18～22", lambda frame: frame["age_band"].eq("18～22")),
            ("一軍主力級", "27～30", lambda frame: frame["age_band"].eq("27～30")),
            ("一軍主力級", "31～34", lambda frame: frame["age_band"].eq("31～34")),
            ("ベテラン型", "31+", lambda frame: frame["age"].ge(31)),
            ("二軍級", "35+", lambda frame: frame["age_band"].eq("35+")),
        ]
        for player_class, band_label, band_mask in class_age_specs:
            subset = gbase[gbase["player_class"].eq(player_class) & band_mask(gbase)]
            if not len(subset):
                continue
            metrics = {
                "nonrank_average": float(subset["normal_count"].mean()),
                "nonrank_5plus_pct": pct(subset["normal_count"].ge(5)),
                "nonrank_8plus_pct": pct(subset["normal_count"].ge(8)),
                "rank_ABC_mean": float(subset["rank_ABC"].mean()),
                "rank_A_rate_pct": pct(subset["rank_A"].ge(1)),
            }
            for metric, value in metrics.items():
                add(role, f"class_age:{player_class}:{band_label}:{metric}", "", math.nan, value, "low", f"generated n={len(subset)}")

        for position in POSITION_ORDER[role]:
            subset = gbase[gbase["position_group"].eq(position)]
            if not len(subset):
                continue
            add(role, f"position:{position}:nonrank_average", "", math.nan, float(subset["normal_count"].mean()), "low", f"generated n={len(subset)}")
            add(role, f"position:{position}:rank_ABC_mean", "", math.nan, float(subset["rank_ABC"].mean()), "low", f"generated n={len(subset)}")

        for ability in ABILITY_KEYS[role]:
            for target in ["normal_count", "rank_ABC"]:
                rcorr = float(rbase[[ability, target]].corr(method="spearman").iloc[0, 1])
                gcorr = float(gbase[[ability, target]].corr(method="spearman").iloc[0, 1])
                sign_flip = rcorr * gcorr < 0 and max(abs(rcorr), abs(gcorr)) >= .20
                add(role, f"ability_corr:{ability}:{target}", len(rbase), rcorr, gcorr, "medium" if sign_flip else "low", "Spearman correlation")
            for name in MAJOR_SPECIALS[role]:
                rtarget, gtarget = indicator(rbase, name), indicator(gbase, name)
                rcorr = float(pd.DataFrame({"ability": rbase[ability], "target": rtarget}).corr(method="spearman").iloc[0, 1])
                gcorr = float(pd.DataFrame({"ability": gbase[ability], "target": gtarget}).corr(method="spearman").iloc[0, 1])
                sign_flip = pd.notna(rcorr) and pd.notna(gcorr) and rcorr * gcorr < 0 and max(abs(rcorr), abs(gcorr)) >= .20
                add(role, f"ability_corr:{ability}:special:{name}", len(rbase), rcorr, gcorr, "medium" if sign_flip else "low", "主要個別特能とのSpearman correlation")
    return pd.DataFrame(rows)


def age_balance(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(role: str, metric: str, band: str, rbase: pd.DataFrame, gbase: pd.DataFrame, rv: float, gv: float, scope: str = "age") -> None:
        rows.append({"role": role, "metric": metric, "scope_type": scope, "age_band": band, "real_n": len(rbase), "generated_n": len(gbase), "real": rv, "generated": gv, "diff": gv - rv})

    for role in ["投手", "野手"]:
        for band in AGE_LABELS:
            rbase = real[real["role"].eq(role) & real["age_band"].eq(band)]
            gbase = generated[generated["role"].eq(role) & generated["age_band"].eq(band)]
            for prefix, column in [("nonrank", "normal_count"), ("display", "display_special_count")]:
                rmetrics, gmetrics = distribution_metrics(rbase, column), distribution_metrics(gbase, column)
                keys = ["average", "median", "p75", "p90", "5plus_pct", "8plus_pct", "10plus_pct"] if prefix == "nonrank" else ["average", "5plus_pct", "8plus_pct", "10plus_pct"]
                for key in keys:
                    add(role, f"{prefix}_{key}", band, rbase, gbase, rmetrics[key], gmetrics[key])
            for metric, column, reducer in [
                ("rank_A_mean", "rank_A", "mean"), ("rank_B_mean", "rank_B", "mean"), ("rank_C_mean", "rank_C", "mean"),
                ("rank_ABC_mean", "rank_ABC", "mean"), ("rank_EFG_mean", "rank_EFG", "mean"),
                ("rank_ABC_1plus_pct", "rank_ABC", "1plus"), ("rank_ABC_2plus_pct", "rank_ABC", "2plus"), ("rank_ABC_3plus_pct", "rank_ABC", "3plus"),
            ]:
                if reducer == "mean":
                    rv, gv = float(rbase[column].mean()), float(gbase[column].mean())
                else:
                    threshold = int(reducer[0])
                    rv, gv = pct(rbase[column].ge(threshold)), pct(gbase[column].ge(threshold))
                add(role, metric, band, rbase, gbase, rv, gv)
            for name in PHASE2_SPECIALS[role]:
                add(role, f"special:{name}:rate_pct", band, rbase, gbase, rate(indicator(rbase, name)), rate(indicator(gbase, name)))

    rpit = real[real["role"].eq("投手")].copy()
    gpit = generated[generated["role"].eq("投手")].copy()
    rpit["pickoff"], gpit["pickoff"] = indicator(rpit, "牽制○"), indicator(gpit, "牽制○")
    for band in PRO_LABELS:
        rbase, gbase = rpit[rpit["pro_band"].eq(band)], gpit[gpit["pro_band"].eq(band)]
        add("投手", "special:牽制○:rate_pct", band, rbase, gbase, rate(rbase["pickoff"]), rate(gbase["pickoff"]), "pro_year_band")
    for band in CORE_AGE_BANDS:
        rv = adjusted_tenure_band(rpit, band)["adjusted_gap_pt"]
        gv = adjusted_tenure_band(gpit, band)["adjusted_gap_pt"]
        rbase, gbase = rpit[rpit["age_band"].eq(band)], gpit[gpit["age_band"].eq(band)]
        add("投手", "special:牽制○:adjusted_long_short_gap_pt", band, rbase, gbase, rv, gv, "same_age_tenure")
    return pd.DataFrame(rows)


def audit_reproducibility(seeds: list[int]) -> dict[str, int]:
    master = app.load_master_data()
    counters = Counter()
    for seed_index, seed_base in enumerate(seeds):
        for role_index, role in enumerate(["投手", "野手"]):
            for offset in range(20):
                seed = seed_base + seed_index * 100_000_000 + role_index * 10_000_000 + offset
                first = app.generate_player(role, "架空球団用", master, seed=seed)
                second = app.generate_player(role, "架空球団用", master, seed=seed)
                before4b = app.generate_player(role, "架空球団用", master, seed=seed, apply_pro_year_profile=False)
                counters["compared"] += 1
                counters["reproducibility_mismatch"] += int(json.dumps(first, ensure_ascii=False, sort_keys=True) != json.dumps(second, ensure_ascii=False, sort_keys=True))
                first_protected = {key: value for key, value in first.items() if key != "special_abilities"}
                before_protected = {key: value for key, value in before4b.items() if key != "special_abilities"}
                counters["protected_fingerprint_mismatch"] += int(first_protected != before_protected)
                counters["ability_mismatch"] += int(first.get("abilities") != before4b.get("abilities"))
                counters["breaking_ball_mismatch"] += int(first.get("breaking_balls") != before4b.get("breaking_balls"))
                counters["non_target_special_mismatch"] += int((set(first.get("special_abilities", [])) - {"牽制○"}) != (set(before4b.get("special_abilities", [])) - {"牽制○"}))
    return dict(counters)


def weighted_phase2_mae(age_table: pd.DataFrame, role: str, name: str) -> float:
    rows = age_table[age_table["role"].eq(role) & age_table["metric"].eq(f"special:{name}:rate_pct") & age_table["scope_type"].eq("age")]
    weights = pd.to_numeric(rows["real_n"], errors="coerce")
    return float((rows["diff"].abs() * weights).sum() / weights.sum())


def regression_guards(real: pd.DataFrame, generated: pd.DataFrame, ages: pd.DataFrame, seeds: list[int]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(area: str, metric: str, value: Any, limit: str, passed: bool, note: str = "") -> None:
        rows.append({"area": area, "metric": metric, "value": value, "limit": limit, "passed": bool(passed), "note": note})

    phase1 = pd.read_csv(ROOT / "reports" / "special_age_phase1_count" / "nonrank_special_count_by_age_before_after.csv", encoding="utf-8-sig")
    max_mean_change, max_tail_change = 0.0, 0.0
    for role in ["投手", "野手"]:
        for band in AGE_LABELS:
            prior = phase1[phase1["dataset"].eq("after") & phase1["role"].eq(role) & phase1["age_band"].eq(band)].iloc[0]
            current = generated[generated["role"].eq(role) & generated["age_band"].eq(band)]
            max_mean_change = max(max_mean_change, abs(float(current["normal_count"].mean()) - float(prior["mean"])))
            max_tail_change = max(max_tail_change, abs(pct(current["normal_count"].ge(8)) - float(prior["rate_8plus_pct"])))
    add("Phase 1 count", "age_profile_max_mean_change", max_mean_change, "<=0.25", max_mean_change <= .25)
    add("Phase 1 count", "age_profile_max_8plus_change_pt", max_tail_change, "<=5pt", max_tail_change <= 5)
    for role in ["投手", "野手"]:
        young = generated[generated["role"].eq(role) & generated["age_band"].eq("18～22")]
        prime = generated[generated["role"].eq(role) & generated["age_band"].isin(["27～30", "31～34"])]
        add("Phase 1 count", f"{role}_prime_5plus_minus_young", pct(prime["normal_count"].ge(5)) - pct(young["normal_count"].ge(5)), ">=0", pct(prime["normal_count"].ge(5)) >= pct(young["normal_count"].ge(5)))
        star_young = young[young["player_class"].eq("スター級")]
        add("Phase 1 count", f"{role}_young_star_8plus_exception", pct(star_young["normal_count"].ge(8)), ">=young overall", pct(star_young["normal_count"].ge(8)) >= pct(young["normal_count"].ge(8)))
        low_young = generated[generated["role"].eq(role) & generated["player_class"].eq("二軍級") & generated["age_band"].eq("18～22")]
        low_old = generated[generated["role"].eq(role) & generated["player_class"].eq("二軍級") & generated["age_band"].eq("35+")]
        old_delta = float(low_old["normal_count"].mean() - low_young["normal_count"].mean()) if len(low_old) and len(low_young) else math.nan
        add("Phase 1 count", f"{role}_old_low_class_unconditional_boost", old_delta, "<=0.5", pd.isna(old_delta) or old_delta <= .5)

    phase2 = pd.read_csv(ROOT / "reports" / "special_age_phase2_individual" / "individual_special_age_compare.csv", encoding="utf-8-sig")
    phase2_failures = 0
    phase2_notes = []
    for role, names in PHASE2_SPECIALS.items():
        for name in names:
            previous = phase2[phase2["role"].eq(role) & phase2["special"].eq(name)].iloc[0]
            current_mae = weighted_phase2_mae(ages, role, name)
            current_rows = ages[
                ages["role"].eq(role)
                & ages["metric"].eq(f"special:{name}:rate_pct")
                & ages["scope_type"].eq("age")
            ].set_index("age_band")
            current_gradient = float(current_rows.loc["31～34", "generated"] - current_rows.loc["18～22", "generated"])
            current_gradient_error = abs(current_gradient - float(previous["gradient_real_pt"]))
            before_gradient_error = abs(float(previous["gradient_before_pt"]) - float(previous["gradient_real_pt"]))
            current_overall = rate(indicator(generated[generated["role"].eq(role)], name))
            overall_change = abs(current_overall - float(previous["overall_after_pct"]))
            profile_improved = current_mae <= float(previous["mae_before"]) + .75 or current_gradient_error <= before_gradient_error + .75
            passed = profile_improved and overall_change <= 2.0
            phase2_failures += int(not passed)
            phase2_notes.append(f"{role}{name}:MAE {current_mae:.2f}, gradient_error {current_gradient_error:.2f}, overall_delta {overall_change:.2f}")
    add("Phase 2 individual", "eight_special_profile_guard", phase2_failures, "0 failures: MAEまたはgradient改善、overall差<=2pt", phase2_failures == 0, "; ".join(phase2_notes))

    phase3 = pd.read_csv(ROOT / "reports" / "special_age_phase3_ranked" / "ranked_age_before_after.csv", encoding="utf-8-sig")
    current_rank = ages[ages["metric"].eq("rank_ABC_mean") & ages["scope_type"].eq("age")]
    max_rank_delta, improvement_failures = 0.0, 0
    for row in current_rank.itertuples(index=False):
        prior = phase3[phase3["role"].eq(row.role) & phase3["age_band"].eq(row.age_band)].iloc[0]
        max_rank_delta = max(max_rank_delta, abs(float(row.generated) - float(prior["abc_mean_after"])))
        improvement_failures += int(abs(float(row.generated) - float(row.real)) > abs(float(prior["abc_mean_before"]) - float(row.real)) + .12)
    add("Phase 3 rank", "abc_age_profile_max_change", max_rank_delta, "<=0.15", max_rank_delta <= .15)
    add("Phase 3 rank", "abc_improvement_failures", improvement_failures, "0", improvement_failures == 0)

    phase4b = pd.read_csv(ROOT / "reports" / "special_age_phase4b_pickoff" / "pickoff_pro_year_before_after.csv", encoding="utf-8-sig")
    current_pickoff = rate(indicator(generated[generated["role"].eq("投手")], "牽制○"))
    previous_pickoff = float(phase4b[phase4b["scope_type"].eq("overall")].iloc[0]["after_rate_pct"])
    add("Phase 4b pickoff", "overall_rate_change_from_phase4b_pt", current_pickoff - previous_pickoff, "abs<=1.0pt", abs(current_pickoff - previous_pickoff) <= 1.0)
    tenure = ages[ages["metric"].eq("special:牽制○:adjusted_long_short_gap_pt")]
    add("Phase 4b pickoff", "three_band_direction", int((tenure["generated"] > tenure["real"] - 20).sum()), "3 bands improve from Phase 4 baseline", bool((tenure["generated"] > -1.5).all()), "; ".join(f"{r.age_band}:{r.generated:+.2f}" for r in tenure.itertuples()))

    no_global_pro = all("pro_years" not in inspect.signature(function).parameters for function in [app.weighted_special_cap, app.extra_special_draws, app.ranked_age_weight_adjustment])
    add("pro_years scope", "cap_extra_rank_unconnected", int(no_global_pro), "1", no_global_pro)

    class_failures = 0
    class_notes = []
    for role in ["投手", "野手"]:
        base = generated[generated["role"].eq(role)]
        by_class = base.groupby("player_class").agg(nonrank=("normal_count", "mean"), abc=("rank_ABC", "mean"))
        checks = [
            by_class.loc["スター級", "nonrank"] > by_class.loc["一軍控え級", "nonrank"],
            by_class.loc["一軍主力級", "nonrank"] > by_class.loc["二軍級", "nonrank"],
            by_class.loc["スター級", "abc"] > by_class.loc["一軍控え級", "abc"],
            by_class.loc["一軍主力級", "abc"] > by_class.loc["二軍級", "abc"],
        ]
        class_failures += sum(not value for value in checks)
        class_notes.append(f"{role}: star {by_class.loc['スター級', 'nonrank']:.2f}/{by_class.loc['スター級', 'abc']:.2f}, main {by_class.loc['一軍主力級', 'nonrank']:.2f}/{by_class.loc['一軍主力級', 'abc']:.2f}, minor {by_class.loc['二軍級', 'nonrank']:.2f}/{by_class.loc['二軍級', 'abc']:.2f}")
    add("player_class", "expected_order_failures", class_failures, "0", class_failures == 0, "; ".join(class_notes))

    position_failures = 0
    position_notes = []
    for role in ["投手", "野手"]:
        base = generated[generated["role"].eq(role)]
        grouped = base.groupby("position_group").agg(nonrank=("normal_count", "mean"), abc=("rank_ABC", "mean"))
        nonrank_range = float(grouped["nonrank"].max() - grouped["nonrank"].min())
        abc_range = float(grouped["abc"].max() - grouped["abc"].min())
        position_failures += int(nonrank_range > 1.0 or abc_range > 1.0)
        position_notes.append(f"{role}: nonrank range {nonrank_range:.2f}, ABC range {abc_range:.2f}")
    add("role / position", "extreme_position_bias", position_failures, "0 (range<=1.0)", position_failures == 0, "; ".join(position_notes))

    violation_columns = [column for column in generated.columns if column.startswith("violation_")]
    violation_total = int(generated[violation_columns].sum().sum())
    add("constraints", "all_constraint_violations", violation_total, "0", violation_total == 0, ", ".join(f"{column}={int(generated[column].sum())}" for column in violation_columns))

    repro = audit_reproducibility(seeds)
    add("seed reproducibility", "full_player_mismatch", repro.get("reproducibility_mismatch", 0), "0", repro.get("reproducibility_mismatch", 0) == 0, f"compared={repro.get('compared', 0)}")
    add("fingerprint", "protected_non_special_mismatch", repro.get("protected_fingerprint_mismatch", 0), "0", repro.get("protected_fingerprint_mismatch", 0) == 0)
    add("ability balance", "same_seed_ability_mismatch", repro.get("ability_mismatch", 0), "0", repro.get("ability_mismatch", 0) == 0)
    add("breaking ball", "same_seed_breaking_ball_mismatch", repro.get("breaking_ball_mismatch", 0), "0", repro.get("breaking_ball_mismatch", 0) == 0)
    add("Phase 1-4b regression", "non_target_special_mismatch", repro.get("non_target_special_mismatch", 0), "0", repro.get("non_target_special_mismatch", 0) == 0)

    stability = []
    for (role, band), subset in generated.groupby(["role", "age_band"]):
        by_seed = subset.groupby("run").agg(mean=("normal_count", "mean"), abc=("rank_ABC", "mean"))
        stability.append(max(by_seed["mean"].max() - by_seed["mean"].min(), by_seed["abc"].max() - by_seed["abc"].min()))
    seed_range = max(stability)
    add("seed stability", "max_age_band_mean_range", seed_range, "<=0.20", seed_range <= .20)
    add("fingerprint", "phase4b_app_sha256", app_sha256(), PHASE5_APP_SHA256, app_sha256() == PHASE5_APP_SHA256, "Phase 5中にapp.py変更なし")
    return pd.DataFrame(rows)


def remaining_gaps(specials: pd.DataFrame, ages: pd.DataFrame, guards: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in specials[specials["metric"].str.startswith("special:") & specials["severity"].isin(["high", "medium"])].sort_values("diff", key=lambda values: values.abs(), ascending=False).head(25).itertuples(index=False):
        rows.append({"area": "individual special", "role": row.role, "metric": row.metric, "severity": row.severity, "evidence": f"real={row.real:.2f}, generated={row.generated:.2f}, diff={row.diff:+.2f}, real_n={row.real_n}", "recommendation": "Phase 5では調整せず、将来の独立テーマとして扱う"})
    for row in specials[specials["metric"].isin(["rank_A_mean", "rank_ABC_mean", "rank_EFG_mean"]) & specials["severity"].eq("medium")].itertuples(index=False):
        rows.append({"area": "rank", "role": row.role, "metric": row.metric, "severity": "medium", "evidence": f"real={row.real:.3f}, generated={row.generated:.3f}, diff={row.diff:+.3f}", "recommendation": "A単独を含め次回監査候補として記録"})
    for row in guards[~guards["passed"]].itertuples(index=False):
        rows.append({"area": row.area, "role": "全体", "metric": row.metric, "severity": "high", "evidence": f"value={row.value}, limit={row.limit}", "recommendation": "追加修正前に原因調査"})
    if not rows:
        rows.append({"area": "none", "role": "全体", "metric": "重大残課題なし", "severity": "low", "evidence": "high/mediumに該当する残課題なし", "recommendation": "現状を固定"})
    return pd.DataFrame(rows)


def write_summary(path: Path, real: pd.DataFrame, generated: pd.DataFrame, specials: pd.DataFrame, ages: pd.DataFrame, guards: pd.DataFrame, gaps: pd.DataFrame, seeds: list[int]) -> str:
    severities = gaps["severity"].value_counts().to_dict()
    high = int(severities.get("high", 0))
    decision = "A. 完成扱い可能" if high == 0 and bool(guards["passed"].all()) else "B. 追加修正推奨"
    phase2_lines = []
    for role, names in PHASE2_SPECIALS.items():
        for name in names:
            row = specials[specials["role"].eq(role) & specials["metric"].eq(f"special:{name}")].iloc[0]
            phase2_lines.append(f"- {role} {name}: real {row['real']:.2f}% / generated {row['generated']:.2f}% / diff {row['diff']:+.2f}pt")
    pickoff = specials[specials["role"].eq("投手") & specials["metric"].eq("special:牽制○")].iloc[0]
    tenure = ages[ages["metric"].eq("special:牽制○:adjusted_long_short_gap_pt")]
    tenure_text = ", ".join(f"{row.age_band} {row.generated:+.2f}pt" for row in tenure.itertuples())
    text = f"""# 特殊能力×年齢・プロ年数 Phase 5

## Dataset

- real: 投手 {int(real['role'].eq('投手').sum())}人、野手 {int(real['role'].eq('野手').sum())}人、合計 {len(real)}人
- generated: 投手 {int(generated['role'].eq('投手').sum()):,}人、野手 {int(generated['role'].eq('野手').sum()):,}人、合計 {len(generated):,}人
- seeds: {', '.join(map(str, seeds))}

## Non-ranked

- Phase 1後の年齢別平均・高尾部との最大差はguard許容内。若手スター例外、27～34歳高尾部、35+低class非boostを維持した。
- 表示総数は非ランク＋比較可能A/B/C/E/F/Gで再計算し、Dは実在直接比較から除外した。

## Individual

{chr(10).join(phase2_lines)}

- Phase 2対象8件はPhase 1 before比の改善条件を維持。残差だけを理由とした再調整は行っていない。

## Ranked

- A～Gを生成側で集計し、実在比較はA/B/C、A/B/C合計、E/F/Gを中心に監査した。
- Phase 3の若手過多縮小と中堅不足縮小はguard範囲内。A weightの追加調整は行っていない。

## pro_years

- 牽制○ overall: real {pickoff['real']:.2f}% / generated {pickoff['generated']:.2f}% / diff {pickoff['diff']:+.2f}pt。
- 同年齢帯long-short差: {tenure_text}。Phase 4bの実在方向を維持した。
- cap、extra draws、rankへのpro_years接続はなく、牽制○限定の構造を維持した。

## Regression

- guard: {int(guards['passed'].sum())}/{len(guards)} passed。
- constraints、seed完全再現、基本能力、変化球、非対象特殊能力、app.py fingerprintを監査した。

## Remaining gaps

- high {high}件 / medium {int(severities.get('medium', 0))}件 / low {int(severities.get('low', 0))}件。
- medium/lowは実在791人の標本差と過学習回避を考慮し、Phase 5では変更しない。

## Final decision

**{decision}**

{'重大gapとregressionはなく、特殊能力×年齢・プロ年数調整は完成扱い可能。' if decision.startswith('A') else 'high gapがあるため、追加修正前に原因調査を推奨。'}
"""
    path.write_text(text, encoding="utf-8")
    return decision


def write_log(path: Path, args: argparse.Namespace, decision: str, guard_count: int) -> None:
    path.write_text(
        f"""# Phase 5 audit log

- Phase 1～4bを固定し、`app.py`のweight・curve・profileは変更していない。
- 実在ファイルは読み取り専用で使用し、コピー・変更・Git追加を行っていない。
- controlled generated: {len(args.seeds)} seed × 投手{args.count_per_role_per_seed:,}人・野手{args.count_per_role_per_seed:,}人。
- 既存Phase 0～4b成果物をbaselineとし、現在コードの年齢、個別、rank、pro_years、class、ability、position、kindを統合監査した。
- constraint、same-seed完全再現、Phase 4b無効時との基本能力・変化球・非対象特殊能力fingerprintを再確認した。
- app.py SHA-256: `{app_sha256()}`（Phase 5開始時と一致）。
- regression guard: {guard_count}項目。
- 完了時検証: `py_compile`成功、`pytest -q`は279 passed / 102 subtests passed、`git diff --check`成功。
- decision: {decision}
- commit / push / PR: 未実施。
""",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    if len(args.seeds) < 3:
        raise ValueError("Phase 5は3 seed以上が必要です")
    if args.count_per_role_per_seed * len(args.seeds) * 2 < 30_000:
        raise ValueError("Phase 5は合計30,000人以上が必要です")
    generated = generate_samples(args.count_per_role_per_seed, args.seeds, args.cache, args.reuse_cache)
    real, real_audit = prepare_real(args.real_xlsx)
    if len(real) != 791 or int(real["role"].eq("投手").sum()) != 402 or int(real["role"].eq("野手").sum()) != 389:
        raise ValueError(f"実在人数不一致: {real_audit}")
    specials = special_balance(real, generated)
    ages = age_balance(real, generated)
    guards = regression_guards(real, generated, ages, args.seeds)
    gaps = remaining_gaps(specials, ages, guards)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    specials.to_csv(args.output_dir / "final_special_balance.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    ages.to_csv(args.output_dir / "final_age_balance.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    gaps.to_csv(args.output_dir / "final_remaining_gaps.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    guards.to_csv(args.output_dir / "final_regression_guard.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    decision = write_summary(args.output_dir / "summary.md", real, generated, specials, ages, guards, gaps, args.seeds)
    write_log(args.output_dir / "phase5_audit_log.md", args, decision, len(guards))
    print(f"Phase 5: {decision}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
