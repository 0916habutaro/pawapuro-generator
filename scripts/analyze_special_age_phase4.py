from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_special_age_experience import (  # noqa: E402
    KIND_MAP,
    REAL,
    age_band,
    finalize_players,
    normalize_name,
    normalize_position,
    partial_corr,
)


DEFAULT_REAL_XLSX = ROOT.parent / "real_powerpro_players_12teams_final" / "pawapuro_players_entry_route_2026.xlsx"
CORE_AGE_BANDS = ["23～26", "27～30", "31～34"]
CANDIDATES = {
    "投手": ["牽制○", "リリース○", "球持ち○", "逃げ球", "打球反応○"],
    "野手": ["選球眼", "バント○", "流し打ち", "粘り打ち", "守備職人"],
}
PHASE2_ADJUSTED = {("投手", "逃げ球"), ("野手", "選球眼"), ("野手", "バント○")}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力年齢構造 Phase 4 pro_years限定分析")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL_XLSX)
    parser.add_argument(
        "--phase0-partial-csv",
        type=Path,
        default=ROOT / "reports" / "special_age_experience_recheck" / "pro_year_partial_effect.csv",
    )
    parser.add_argument(
        "--phase0-individual-partial-csv",
        type=Path,
        default=ROOT / "reports" / "special_age_experience_recheck" / "individual_special_pro_year_partial_effect.csv",
    )
    parser.add_argument(
        "--phase0-pro-band-csv",
        type=Path,
        default=ROOT / "reports" / "special_age_experience_recheck" / "individual_special_by_pro_years_compare.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "special_age_phase4_pro_years",
    )
    return parser.parse_args()


def targeted_real_frame(path: Path) -> pd.DataFrame:
    player_columns = [
        "team", "name", "role", "age", "pro_years", "pitcher_roles", "main_position",
        "top_speed", "control", "stamina", "contact", "power", "run_speed",
        "arm_strength", "fielding", "catching",
    ]
    special_columns = ["team", "name", "special_kind", "special"]
    breaking_columns = ["team", "name", "kind", "slot", "movement"]
    players = pd.read_excel(path, sheet_name="players", usecols=player_columns)
    specials = pd.read_excel(path, sheet_name="special_abilities", usecols=special_columns)
    breaking = pd.read_excel(path, sheet_name="breaking_balls", usecols=breaking_columns)

    specials["special"] = specials["special"].map(normalize_name)
    normals = specials[
        specials["special_kind"].ne("rank")
        & (specials["special_kind"].ne("usage") | specials["special"].map(KIND_MAP).eq("green"))
    ].copy()
    normal_groups = normals.groupby(["team", "name"], dropna=False)["special"].agg(list).to_dict()

    primary = breaking[
        breaking["kind"].eq("breaking")
        & pd.to_numeric(breaking["slot"], errors="coerce").fillna(1).eq(1)
    ].copy()
    pitch_groups = primary.groupby(["team", "name"], dropna=False).agg(
        球種数=("movement", "size"),
        総変化量=("movement", lambda values: pd.to_numeric(values, errors="coerce").fillna(0).sum()),
    ).to_dict("index")

    candidate_union = {name for names in CANDIDATES.values() for name in names}
    rows: list[dict[str, Any]] = []
    for index, item in players.iterrows():
        role = str(item["role"])
        key = (item["team"], item["name"])
        normal_names = normal_groups.get(key, [])
        pitch = pitch_groups.get(key, {"球種数": 0, "総変化量": 0})
        row: dict[str, Any] = {
            "dataset": REAL,
            "player_id": f"real:{index}",
            "role": role,
            "age": item["age"],
            "pro_years": item["pro_years"],
            "player_class": "実在",
            "position": item["pitcher_roles"] if role == "投手" else item["main_position"],
            "球速": item["top_speed"],
            "コントロール": item["control"],
            "スタミナ": item["stamina"],
            "総変化量": pitch["総変化量"],
            "球種数": pitch["球種数"],
            "ミート": item["contact"],
            "パワー": item["power"],
            "走力": item["run_speed"],
            "肩力": item["arm_strength"],
            "守備力": item["fielding"],
            "捕球": item["catching"],
            "nonrank_special_count": len(normal_names),
        }
        held = set(normal_names)
        for name in candidate_union:
            row[f"special::{name}"] = int(name in held)
        rows.append(row)
    frame = finalize_players(pd.DataFrame(rows))
    frame["age_band"] = frame["age"].map(age_band)
    frame["position_group"] = [normalize_position(position, role) for position, role in zip(frame["position"], frame["role"])]
    return frame


def position_controls(base: pd.DataFrame) -> pd.DataFrame:
    dummies = pd.get_dummies(base["position_group"], prefix="position", drop_first=True, dtype=float)
    return pd.concat(
        [
            pd.to_numeric(base["age"], errors="coerce").rename("age"),
            pd.to_numeric(base["ability_score"], errors="coerce").rename("ability_score"),
            dummies,
        ],
        axis=1,
    )


def simple_corr(x: pd.Series, y: pd.Series) -> float:
    values = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(values) < 5 or values["x"].nunique() < 2 or values["y"].nunique() < 2:
        return math.nan
    return float(values["x"].corr(values["y"]))


def residuals(y: pd.Series, controls: pd.DataFrame) -> pd.Series:
    data = pd.concat([pd.to_numeric(y, errors="coerce").rename("y"), controls], axis=1).dropna()
    if len(data) < 5:
        return pd.Series(dtype=float)
    x = np.column_stack([np.ones(len(data)), data.iloc[:, 1:].to_numpy(float)])
    values = data["y"].to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, values, rcond=None)
    return pd.Series(values - x @ beta, index=data.index)


def same_age_tenure_effect(base: pd.DataFrame, target_col: str, binary: bool) -> tuple[float, str, int]:
    band_results: list[tuple[str, float, int, int]] = []
    for band in CORE_AGE_BANDS:
        subset = base[base["age_band"].eq(band)].copy()
        if len(subset) < 30 or subset["pro_years"].nunique() < 3:
            continue
        ranked_tenure = pd.to_numeric(subset["pro_years"], errors="coerce").rank(method="first")
        subset["tenure_group"] = pd.qcut(ranked_tenure, 3, labels=["short", "medium", "long"])
        adjusted = residuals(subset[target_col], position_controls(subset))
        subset.loc[adjusted.index, "adjusted_target"] = adjusted
        short = subset[subset["tenure_group"].eq("short")]["adjusted_target"].dropna()
        long = subset[subset["tenure_group"].eq("long")]["adjusted_target"].dropna()
        if not len(short) or not len(long):
            continue
        difference = float(long.mean() - short.mean()) * (100.0 if binary else 1.0)
        band_results.append((band, difference, len(short), len(long)))
    if not band_results:
        return math.nan, "0/0", 0
    weights = [short_n + long_n for _, _, short_n, long_n in band_results]
    weighted = float(np.average([difference for _, difference, _, _ in band_results], weights=weights))
    expected_sign = 1 if weighted >= 0 else -1
    consistent = sum((difference >= 0) == (expected_sign > 0) for _, difference, _, _ in band_results)
    unit = "pt" if binary else "個"
    details = "; ".join(f"{band}:{difference:+.2f}{unit}" for band, difference, _, _ in band_results)
    return weighted, f"{consistent}/{len(band_results)}同方向（{details}）", sum(weights)


def phase0_overall_effect(table: pd.DataFrame, role: str) -> float:
    found = table[
        table["dataset"].eq(REAL)
        & table["role"].eq(role)
        & table["partial_corr_pro_years_special_count_control_age_ability"].notna()
    ]
    return float(found.iloc[0]["partial_corr_pro_years_special_count_control_age_ability"]) if len(found) else math.nan


def phase0_individual_effect(table: pd.DataFrame, role: str, name: str) -> float:
    found = table[table["dataset"].eq(REAL) & table["role"].eq(role) & table["special"].eq(name)]
    return float(found.iloc[0]["partial_corr_pro_years_control_age_ability"]) if len(found) else math.nan


def effect_strength(value: float) -> str:
    magnitude = abs(value)
    if magnitude < 0.05:
        return "ほぼ無視"
    if magnitude < 0.10:
        return "非常に弱い"
    if magnitude < 0.20:
        return "弱い"
    return "検討価値あり"


def result_table(frame: pd.DataFrame, phase0: pd.DataFrame, phase0_individual: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for role in ["投手", "野手"]:
        base = frame[frame["role"].eq(role)].copy()
        target_col = "nonrank_special_count"
        _, controlled = partial_corr(base["pro_years"], base[target_col], position_controls(base))
        same_age, consistency, same_age_n = same_age_tenure_effect(base, target_col, binary=False)
        simple = simple_corr(base["pro_years"], base[target_col])
        age_effect = simple_corr(base["age"], base[target_col])
        phase0_value = phase0_overall_effect(phase0, role)
        candidate = bool(abs(controlled) >= 0.20 and abs(same_age) >= 0.25 and consistency.startswith("3/3"))
        reason = (
            f"Phase 0表示総数partial r={phase0_value:.3f}に対し、非ランク再計算は{controlled:.3f}（{effect_strength(controlled)}）。"
            f"同年齢帯の調整済みlong-short差は{same_age:+.2f}個で{consistency.split('（', 1)[0]}。"
            + ("全体個数へ直接入れる根拠として十分。" if candidate else "全体個数へpro_yearsを追加する根拠として弱い。")
        )
        rows.append({
            "role": role,
            "target": "nonrank_special_count",
            "real_n": len(base),
            "positive_n": "",
            "effect_type": "count_partial_corr_and_adjusted_long_short",
            "simple_effect": simple,
            "age_effect": age_effect,
            "phase0_age_controlled_effect": phase0_value,
            "age_controlled_effect": controlled,
            "same_age_effect": same_age,
            "same_age_n": same_age_n,
            "consistency": consistency,
            "implementation_candidate": candidate,
            "reason": reason,
        })

        for name in CANDIDATES[role]:
            target_col = f"special::{name}"
            positives = int(base[target_col].sum())
            _, controlled = partial_corr(base["pro_years"], base[target_col], position_controls(base))
            same_age, consistency, same_age_n = same_age_tenure_effect(base, target_col, binary=True)
            simple = simple_corr(base["pro_years"], base[target_col])
            _, age_controlled = partial_corr(base["age"], base[target_col], pd.concat([base[["ability_score"]], pd.get_dummies(base["position_group"], drop_first=True, dtype=float)], axis=1))
            phase0_value = phase0_individual_effect(phase0_individual, role, name)
            consistent_count = int(consistency.split("/", 1)[0]) if "/" in consistency else 0
            same_direction = not math.isnan(same_age) and ((controlled >= 0 and same_age >= 0) or (controlled < 0 and same_age < 0))
            sample_ok = positives >= 40
            effect_ok = abs(controlled) >= 0.10 and abs(same_age) >= 3.0
            consistency_ok = consistent_count >= 2 and same_direction
            phase2_extra_guard = (role, name) not in PHASE2_ADJUSTED or (abs(controlled) >= 0.12 and abs(same_age) >= 4.0 and consistent_count == 3)
            candidate = bool(sample_ok and effect_ok and consistency_ok and phase2_extra_guard)
            limitations = []
            if not sample_ok:
                limitations.append(f"保有{positives}人で少標本")
            if abs(controlled) < 0.10:
                limitations.append(f"partial r={controlled:.3f}で弱い")
            if abs(same_age) < 3.0:
                limitations.append(f"同年齢差{same_age:+.2f}pt")
            if not consistency_ok:
                limitations.append("帯別方向が不安定")
            if (role, name) in PHASE2_ADJUSTED and not phase2_extra_guard:
                limitations.append("Phase 2年齢profile後に追加する根拠不足")
            reason = (
                f"保有{positives}人、Phase 0 partial r={phase0_value:.3f}、位置も統制した再計算={controlled:.3f}。"
                f"同年齢帯long-short差={same_age:+.2f}pt、{consistency}。"
                + ("Phase 4b候補条件を満たす。" if candidate else "、".join(limitations) + "。")
            )
            rows.append({
                "role": role,
                "target": name,
                "real_n": len(base),
                "positive_n": positives,
                "effect_type": "binary_partial_corr_and_adjusted_rate_difference",
                "simple_effect": simple,
                "age_effect": age_controlled,
                "phase0_age_controlled_effect": phase0_value,
                "age_controlled_effect": controlled,
                "same_age_effect": same_age,
                "same_age_n": same_age_n,
                "consistency": consistency,
                "implementation_candidate": candidate,
                "reason": reason,
            })
    return pd.DataFrame(rows)


def write_reports(output: Path, results: pd.DataFrame, frame: pd.DataFrame, source_path: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    results.to_csv(output / "pro_year_residual_effect.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    candidates = results[results["implementation_candidate"].eq(True)]
    count_rows = results[results["target"].eq("nonrank_special_count")]
    individual = results[results["target"].ne("nonrank_special_count")]

    lines = [
        "# 特殊能力年齢構造 Phase 4", "",
        "## 1. 非ランク特殊能力数への独立効果", "",
        "|役割|N|Phase 0表示総数 partial r|Phase 4非ランク partial r|同年齢帯 long-short|判定|",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in count_rows.itertuples(index=False):
        lines.append(
            f"|{row.role}|{row.real_n}|{row.phase0_age_controlled_effect:.3f}|{row.age_controlled_effect:.3f}|"
            f"{row.same_age_effect:+.2f}個|{effect_strength(row.age_controlled_effect)}|"
        )
    lines += [
        "", "Phase 1～3後の判断材料として非ランクだけを分離すると、pro_yearsの残差は全体個数へ直接変数を追加するほど強くない。",
        "", "## 2. 全体個数ロジック", "",
        "`weighted_special_cap()` と `extra_special_draws()` へpro_yearsを追加しない。年齢・能力・役割を統制した効果量と同年齢帯差が、全体ロジック変更に必要な強さへ達していない。",
        "", "## 3. 個別候補", "",
        "|役割|特殊能力|保有数|partial r|同年齢帯 long-short|一貫性|候補|",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for row in individual.itertuples(index=False):
        lines.append(
            f"|{row.role}|{row.target}|{row.positive_n}|{row.age_controlled_effect:.3f}|"
            f"{row.same_age_effect:+.2f}pt|{row.consistency.split('（', 1)[0]}|{'yes' if row.implementation_candidate else 'no'}|"
        )
    lines += ["", "## 4. Phase 4b", ""]
    if len(candidates):
        names = "、".join(f"{row.role} {row.target}" for row in candidates.itertuples(index=False) if row.target != "nonrank_special_count")
        lines.append(f"限定候補は{names or '非ランク個数'}。ただし今回は実装しない。")
    else:
        lines.append("個別候補もsample・効果量・帯別一貫性・Phase 2との重複条件を同時には満たさないため、Phase 4bを行う価値は低い。")
    lines += [
        "", "## 5. Decision", "",
        f"**{'Phase 4b限定実装' if len(candidates) else '実装なしで終了'}**", "",
        "rankはPhase 3残差があるため参考扱いとし、今回のpro_years判断には使用していない。",
    ]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    log = [
        "# Phase 4 analysis log", "",
        "- app.py、Phase 1個数ロジック、Phase 2個別profile、Phase 3 ranked profileは変更していない。",
        "- Phase 0のpartial effect・個別pro_years CSVを比較基準として再利用した。",
        "- Phase 0 CSVにない非ランクplayer-level件数と同年齢帯tenure差だけを補完した。",
        "- 実在Excelはplayers、special_abilities、breaking_ballsの必要列だけを読み取り、非ランク件数と指定10特能に限定した。",
        "- real player_class proxyは新設せず、Phase 0と同じく年齢・能力score・position/pitcher roleを統制した。",
        "- 23～26、27～30、31～34歳内でpro_yearsを3群化し、年齢・能力・position調整後のlong-short差を算出した。",
        "- 18～22と35+、rank、controlled generatedは主要判定から除外した。",
        f"- 対象実在選手: 投手{int(frame['role'].eq('投手').sum())}人、野手{int(frame['role'].eq('野手').sum())}人。",
        f"- 読取元: {source_path.name}（読み取り専用）。",
    ]
    (output / "phase4_analysis_log.md").write_text("\n".join(log) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    phase0 = pd.read_csv(args.phase0_partial_csv, encoding="utf-8-sig")
    phase0_individual = pd.read_csv(args.phase0_individual_partial_csv, encoding="utf-8-sig")
    # Read for source/audit continuity even though the player-level same-age calculation is performed below.
    pd.read_csv(args.phase0_pro_band_csv, encoding="utf-8-sig", nrows=1)
    frame = targeted_real_frame(args.real_xlsx)
    results = result_table(frame, phase0, phase0_individual)
    write_reports(args.output_dir, results, frame, args.real_xlsx)
    print(f"Phase 4 analysis complete: real={len(frame):,}, targets={len(results):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
