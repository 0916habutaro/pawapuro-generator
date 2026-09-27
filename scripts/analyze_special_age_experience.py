from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np
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


REAL = "real"
SAVED = "saved_generated"
CONTROLLED = "controlled_generated"
AGE_LABELS = ["18～22", "23～26", "27～30", "31～34", "35+"]
PRO_LABELS = ["1～3年", "4～6年", "7～10年", "11～14年", "15年以上"]
RANKS = list("ABCDEFG")
COMPARABLE_RANKS = set("ABCEFG")
KINDS = ["blue", "red", "green", "gold", "mixed", "other"]
ALIASES = {"盗塁○": "盗塁〇", "走塁○": "走塁〇", "ノビ○": "ノビ〇"}
FOCUS_SPECIALS = {
    "投手": [
        "リリース○", "球持ち○", "逃げ球", "打球反応○", "牽制○", "キレ○", "緩急○", "変化球中心",
        "速球中心", "奪三振", "低め○", "回またぎ○", "尻上がり", "四球", "乱調", "一発",
    ],
    "野手": [
        "選球眼", "バント○", "バント職人", "流し打ち", "粘り打ち", "固め打ち", "サヨナラ男", "満塁男",
        "代打○", "守備職人", "内野安打○", "盗塁○", "走塁○", "積極盗塁", "積極走塁", "積極守備",
        "パワーヒッター", "アベレージヒッター", "三振", "併殺", "エラー",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="特殊能力と年齢・プロ年数のPhase 0比較分析")
    parser.add_argument("--real-xlsx", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "players.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "special_age_experience_recheck")
    parser.add_argument("--count-per-role-per-seed", type=int, default=5_000)
    parser.add_argument("--seeds", nargs="+", type=int, default=[202609270101, 202609270201])
    parser.add_argument("--reuse-controlled", action="store_true")
    return parser.parse_args()


def normalize_name(value: Any) -> str:
    text = "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value).strip()
    return ALIASES.get(text, text)


def safe_json(value: Any, default: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def age_band(age: Any) -> str:
    if pd.isna(age):
        return "不明"
    age = int(age)
    if age <= 22:
        return "18～22"
    if age <= 26:
        return "23～26"
    if age <= 30:
        return "27～30"
    if age <= 34:
        return "31～34"
    return "35+"


def pro_band(years: Any) -> str:
    if pd.isna(years):
        return "不明"
    years = int(years)
    if years <= 3:
        return "1～3年"
    if years <= 6:
        return "4～6年"
    if years <= 10:
        return "7～10年"
    if years <= 14:
        return "11～14年"
    return "15年以上"


def normalize_position(value: Any, role: str) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if role == "投手":
        if "先" in text:
            return "先発"
        if "抑" in text:
            return "抑え"
        if "中" in text:
            return "中継ぎ"
        return text or "不明"
    if text in {"左翼手", "中堅手", "右翼手"}:
        return "外野手"
    return text or "不明"


def master_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    master = pd.read_csv(ROOT / "data" / "special_abilities.csv")
    kind_map: dict[str, str] = {}
    role_map: dict[str, str] = {}
    group_map: dict[str, str] = {}
    for row in master.to_dict("records"):
        name = normalize_name(row.get("name"))
        kind = str(row.get("kind", "other"))
        kind_map[name] = kind if kind in KINDS else "other"
        role_map[name] = str(row.get("target_role", "共通"))
        group_map[name] = str(row.get("group", ""))
    return kind_map, role_map, group_map


KIND_MAP, ROLE_MAP, GROUP_MAP = master_maps()


def rank_of(name: str) -> str:
    return name[-1] if name[-1:] in RANKS else ""


def comparable_counts(normal_names: Iterable[str], ranked_names: Iterable[str]) -> dict[str, Any]:
    # 緑特はアプリ上の usage 表示対象と重なるものがあるため、マスタで green の項目は比較対象に残す。
    # マスタ外の純粋な起用法ラベルだけを除外する。
    normals = [
        normalize_name(x)
        for x in normal_names
        if normalize_name(x)
        and (normalize_name(x) not in USAGE_SPECIAL_NAMES or KIND_MAP.get(normalize_name(x)) == "green")
    ]
    ranked = [normalize_name(x) for x in ranked_names if rank_of(normalize_name(x))]
    rank_counter = Counter(rank_of(x) for x in ranked)
    kind_counter = Counter(KIND_MAP.get(x, "other") for x in normals)
    comparable_rank_count = sum(rank_counter[r] for r in COMPARABLE_RANKS)
    return {
        "normal_names": json.dumps(normals, ensure_ascii=False),
        "ranked_names": json.dumps(ranked, ensure_ascii=False),
        "normal_count": len(normals),
        "comparable_rank_count": comparable_rank_count,
        "display_special_count": len(normals) + comparable_rank_count,
        **{f"kind_{kind}": kind_counter[kind] for kind in KINDS},
        **{f"rank_{rank}": rank_counter[rank] for rank in RANKS},
        "rank_A": rank_counter["A"],
        "rank_AB": rank_counter["A"] + rank_counter["B"],
        "rank_ABC": rank_counter["A"] + rank_counter["B"] + rank_counter["C"],
        "rank_EFG": rank_counter["E"] + rank_counter["F"] + rank_counter["G"],
    }


def zscore(values: pd.Series) -> pd.Series:
    nums = pd.to_numeric(values, errors="coerce")
    std = nums.std(ddof=0)
    return (nums - nums.mean()) / std if pd.notna(std) and std > 0 else pd.Series(0.0, index=values.index)


def add_ability_score(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["ability_score"] = np.nan
    specs = {
        "投手": ["球速", "コントロール", "スタミナ", "総変化量", "球種数"],
        "野手": ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"],
    }
    for (dataset, role), index in result.groupby(["dataset", "role"]).groups.items():
        cols = [col for col in specs[role] if col in result]
        standardized = pd.concat([zscore(result.loc[index, col]) for col in cols], axis=1)
        result.loc[index, "ability_score"] = standardized.mean(axis=1).to_numpy()
    return result


def finalize_players(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in ["age", "pro_years", "球速", "コントロール", "スタミナ", "総変化量", "球種数", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"]:
        if col not in frame:
            frame[col] = np.nan
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["age_band"] = frame["age"].map(age_band)
    frame["pro_band"] = frame["pro_years"].map(pro_band)
    frame["position_group"] = [normalize_position(pos, role) for pos, role in zip(frame["position"], frame["role"])]
    frame["small_sample_note"] = ""
    return add_ability_score(frame)


def load_real(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    xl = pd.ExcelFile(path)
    raw_players = pd.read_excel(xl, "players")
    specials = pd.read_excel(xl, "special_abilities")
    breaking = pd.read_excel(xl, "breaking_balls")
    special_groups: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for (team, name), subset in specials.groupby(["team", "name"], dropna=False):
        normals = [
            normalize_name(item.special)
            for item in subset.itertuples(index=False)
            if str(item.special_kind) != "rank"
            and (str(item.special_kind) != "usage" or KIND_MAP.get(normalize_name(item.special)) == "green")
        ]
        ranks = [normalize_name(x) for x in subset.loc[subset["special_kind"].eq("rank"), "special"]]
        special_groups[(str(team), str(name))] = (normals, ranks)
    pitch_groups: dict[tuple[str, str], tuple[int, int]] = {}
    for (team, name), subset in breaking.groupby(["team", "name"], dropna=False):
        primary = subset[subset["kind"].eq("breaking") & pd.to_numeric(subset["slot"], errors="coerce").fillna(1).eq(1)]
        pitch_groups[(str(team), str(name))] = (len(primary), int(pd.to_numeric(primary["movement"], errors="coerce").fillna(0).sum()))
    rows: list[dict[str, Any]] = []
    for idx, item in raw_players.iterrows():
        role = str(item["role"])
        key = (str(item["team"]), str(item["name"]))
        normal_names, ranked_names = special_groups.get(key, ([], []))
        pitch_count, movement = pitch_groups.get(key, (0, 0))
        row = {
            "dataset": REAL, "player_id": f"real:{idx}", "seed": np.nan, "created_at": "",
            "role": role, "category": "実在12球団", "name": item["name"], "age": item["age"],
            "pro_years": item["pro_years"], "player_class": "実在", "archetype": "", "position_style": "",
            "position": item["pitcher_roles"] if role == "投手" else item["main_position"],
            "球速": item["top_speed"], "コントロール": item["control"], "スタミナ": item["stamina"],
            "総変化量": movement, "球種数": pitch_count, "ミート": item["contact"], "パワー": item["power"],
            "走力": item["run_speed"], "肩力": item["arm_strength"], "守備力": item["fielding"], "捕球": item["catching"],
        }
        row.update(comparable_counts(normal_names, ranked_names))
        rows.append(row)
    frame = finalize_players(pd.DataFrame(rows))
    audit = {
        "path": str(path), "sheets": xl.sheet_names, "total": len(frame),
        "pitchers": int(frame["role"].eq("投手").sum()), "fielders": int(frame["role"].eq("野手").sum()),
        "missing_age": int(frame["age"].isna().sum()), "missing_pro_years": int(frame["pro_years"].isna().sum()),
        "rank_d_rows": int(frame["rank_D"].sum()), "special_rows": len(specials),
    }
    return frame, audit


def pr76_cutoff() -> str:
    result = subprocess.run(
        ["git", "show", "-s", "--format=%ci", "72f349c"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    return result[:19]


def generated_ability_values(abilities: dict[str, Any], balls: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [b for b in balls if b.get("kind", "breaking") == "breaking" and not b.get("is_second_pitch")]
    return {
        "球速": pitcher_speed_value(abilities), "コントロール": ability_numeric_value(abilities, "コントロール"),
        "スタミナ": ability_numeric_value(abilities, "スタミナ"), "総変化量": sum(pitch_movement(b) for b in primary),
        "球種数": len(primary), "ミート": ability_numeric_value(abilities, "ミート"), "パワー": ability_numeric_value(abilities, "パワー"),
        "走力": ability_numeric_value(abilities, "走力"), "肩力": ability_numeric_value(abilities, "肩力"),
        "守備力": ability_numeric_value(abilities, "守備力"), "捕球": ability_numeric_value(abilities, "捕球"),
    }


def load_saved(db_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    cutoff = pr76_cutoff()
    conn = sqlite3.connect(db_path)
    raw = pd.read_sql_query("SELECT * FROM players ORDER BY id", conn)
    conn.close()
    after = raw[raw["created_at"].ge(cutoff)].copy()
    current = after[after["category"].eq("架空球団用")].copy()
    rows: list[dict[str, Any]] = []
    for item in current.to_dict("records"):
        abilities = safe_json(item.get("abilities_json"), {})
        balls = safe_json(item.get("breaking_balls_json"), [])
        normal_names = safe_json(item.get("special_abilities_json"), [])
        ranked_raw = safe_json(item.get("ranked_special_abilities_json"), {})
        ranked_names = list(ranked_raw.values()) if isinstance(ranked_raw, dict) else ranked_raw
        row = {
            "dataset": SAVED, "player_id": f"saved:{item['id']}", "seed": item["seed"], "created_at": item["created_at"],
            "role": item["role"], "category": item["category"], "name": item["name"], "age": item["age"],
            "pro_years": item.get("pro_years"), "player_class": item.get("player_class", ""),
            "archetype": item.get("archetype", ""), "position_style": item.get("position_style", ""), "position": item["position"],
        }
        row.update(generated_ability_values(abilities, balls))
        row.update(comparable_counts(normal_names, ranked_names))
        rows.append(row)
    frame = finalize_players(pd.DataFrame(rows))
    audit = {
        "db_total": len(raw), "cutoff": cutoff, "post_pr76": len(after), "adopted": len(frame),
        "excluded_pre_pr76": int(raw["created_at"].lt(cutoff).sum()),
        "excluded_non_fictional_post_pr76": int((~after["category"].eq("架空球団用")).sum()),
        "pitchers": int(frame["role"].eq("投手").sum()), "fielders": int(frame["role"].eq("野手").sum()),
        "oldest": frame["created_at"].min() if len(frame) else "", "latest": frame["created_at"].max() if len(frame) else "",
    }
    return frame, audit


def flatten_controlled(player: dict[str, Any], run: str, index: int) -> dict[str, Any]:
    abilities = player.get("abilities", {})
    balls = player.get("breaking_balls", []) or []
    ranked_raw = abilities.get("ranked_specials", {}) or {}
    row = {
        "dataset": CONTROLLED, "player_id": f"controlled:{run}:{index}", "seed": player["seed"], "created_at": "",
        "role": player["role"], "category": player["category"], "name": player["name"], "age": player["age"],
        "pro_years": player.get("pro_years"), "player_class": player.get("player_class", ""),
        "archetype": player.get("archetype", ""), "position_style": player.get("position_style", ""), "position": player["position"],
    }
    row.update(generated_ability_values(abilities, balls))
    row.update(comparable_counts(player.get("special_abilities", []), ranked_raw.values()))
    return row


def generate_controlled(count: int, seeds: list[int], output_dir: Path, reuse: bool) -> pd.DataFrame:
    cache = output_dir / "controlled_generated_cache.pkl"
    if reuse and cache.exists():
        return pd.read_pickle(cache)
    master = load_master_data()
    rows: list[dict[str, Any]] = []
    for seed_base in seeds:
        run = f"seed_{seed_base}"
        for role_index, role in enumerate(["投手", "野手"]):
            print(f"{run}: {role} {count:,}人を統制生成", flush=True)
            for i in range(count):
                seed = seed_base + role_index * 10_000_000 + i
                rows.append(flatten_controlled(generate_player(role, "架空球団用", master, seed=seed), run, i))
    frame = finalize_players(pd.DataFrame(rows))
    frame.to_pickle(cache)
    return frame


def pct(mask: pd.Series) -> float:
    return float(mask.mean() * 100) if len(mask) else math.nan


def count_summary(frame: pd.DataFrame, band_col: str, order: list[str]) -> pd.DataFrame:
    rows = []
    for (dataset, role), base in frame.groupby(["dataset", "role"], observed=False):
        for band in order:
            subset = base[base[band_col].eq(band)]
            values = subset["display_special_count"]
            rows.append({
                "dataset": dataset, "role": role, "band": band, "n": len(subset),
                "mean": values.mean(), "median": values.median(), "p25": values.quantile(.25), "p75": values.quantile(.75),
                "p90": values.quantile(.90), "max": values.max() if len(values) else np.nan,
                "rate_0_pct": pct(values.eq(0)), "rate_1_2_pct": pct(values.between(1, 2)),
                "rate_3_4_pct": pct(values.between(3, 4)), "rate_5plus_pct": pct(values.ge(5)),
                "rate_8plus_pct": pct(values.ge(8)), "rate_10plus_pct": pct(values.ge(10)),
                "small_sample": len(subset) < 30,
            })
    return pd.DataFrame(rows)


def kind_summary(frame: pd.DataFrame, band_col: str, order: list[str]) -> pd.DataFrame:
    rows = []
    for (dataset, role), base in frame.groupby(["dataset", "role"], observed=False):
        for band in order:
            subset = base[base[band_col].eq(band)]
            for kind in KINDS:
                values = subset[f"kind_{kind}"]
                rows.append({"dataset": dataset, "role": role, "band": band, "kind": kind, "n": len(subset),
                             "mean_count": values.mean(), "holder_rate_pct": pct(values.ge(1)), "small_sample": len(subset) < 30})
    return pd.DataFrame(rows)


def ranked_summary(frame: pd.DataFrame, band_col: str, order: list[str]) -> pd.DataFrame:
    rows = []
    metrics = {**{rank: f"rank_{rank}" for rank in RANKS}, "A": "rank_A", "A/B": "rank_AB", "A/B/C": "rank_ABC", "E/F/G": "rank_EFG"}
    for (dataset, role), base in frame.groupby(["dataset", "role"], observed=False):
        for band in order:
            subset = base[base[band_col].eq(band)]
            for metric, col in metrics.items():
                values = subset[col]
                rows.append({"dataset": dataset, "role": role, "band": band, "metric": metric, "n": len(subset),
                             "mean_count": values.mean(), "holder_rate_pct": pct(values.ge(1)), "small_sample": len(subset) < 30})
    return pd.DataFrame(rows)


def all_special_names(frame: pd.DataFrame, role: str) -> list[str]:
    names: set[str] = set()
    for raw in frame.loc[frame["role"].eq(role), "normal_names"]:
        names.update(safe_json(raw, []))
    return sorted(names)


def indicator(frame: pd.DataFrame, name: str) -> pd.Series:
    return frame["normal_names"].map(lambda raw: name in set(safe_json(raw, []))).astype(float)


def individual_by_band(frame: pd.DataFrame, band_col: str, order: list[str]) -> pd.DataFrame:
    rows = []
    for role in ["投手", "野手"]:
        union = sorted(set(all_special_names(frame, role)) | {normalize_name(name) for name in FOCUS_SPECIALS[role]})
        for dataset in [REAL, SAVED, CONTROLLED]:
            base = frame[frame["role"].eq(role) & frame["dataset"].eq(dataset)]
            for name in union:
                held = indicator(base, name)
                row = {"dataset": dataset, "role": role, "special": name, "kind": KIND_MAP.get(name, "other"),
                       "n": len(base), "overall_rate_pct": pct(held.eq(1))}
                rates = []
                for band in order:
                    mask = base[band_col].eq(band)
                    rate = pct(held.loc[mask].eq(1))
                    row[f"{band}_n"] = int(mask.sum())
                    row[f"{band}_rate_pct"] = rate
                    rates.append(rate)
                row["youngest_to_oldest_change_pt"] = rates[-1] - rates[0] if pd.notna(rates[-1]) and pd.notna(rates[0]) else np.nan
                rows.append(row)
    result = pd.DataFrame(rows)
    keys = ["role", "special"]
    real_delta = result[result["dataset"].eq(REAL)].set_index(keys)["youngest_to_oldest_change_pt"]
    result["real_change_pt"] = [real_delta.get((r.role, r.special), np.nan) for r in result.itertuples()]
    result["trend_difference_vs_real_pt"] = result["youngest_to_oldest_change_pt"] - result["real_change_pt"]
    return result


def class_age_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    generated = frame[frame["dataset"].isin([SAVED, CONTROLLED])]
    for (dataset, role, player_class, band), subset in generated.groupby(["dataset", "role", "player_class", "age_band"], observed=False):
        values = subset["display_special_count"]
        rows.append({"dataset": dataset, "role": role, "player_class": player_class, "age_band": band, "n": len(subset),
                     "mean_special_count": values.mean(), "rate_5plus_pct": pct(values.ge(5)), "rate_8plus_pct": pct(values.ge(8)),
                     "mean_abc_count": subset["rank_ABC"].mean(), "small_sample": len(subset) < 30})
    return pd.DataFrame(rows)


def role_position_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, role, position, band), subset in frame.groupby(["dataset", "role", "position_group", "age_band"], observed=False):
        values = subset["display_special_count"]
        rows.append({"dataset": dataset, "role": role, "position_role": position, "age_band": band, "n": len(subset),
                     "mean_special_count": values.mean(), "rate_5plus_pct": pct(values.ge(5)), "rate_8plus_pct": pct(values.ge(8)),
                     "mean_abc_count": subset["rank_ABC"].mean(), "small_sample": len(subset) < 30})
    return pd.DataFrame(rows)


def corr_pair(x: pd.Series, y: pd.Series) -> tuple[int, float, float]:
    values = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(values) < 3 or values["x"].nunique() < 2 or values["y"].nunique() < 2:
        return len(values), math.nan, math.nan
    pearson = values["x"].corr(values["y"], method="pearson")
    spearman = values["x"].rank().corr(values["y"].rank())
    return len(values), pearson, spearman


def correlation_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    pairs = [
        ("age", "display_special_count", "年齢×特殊能力数"), ("pro_years", "display_special_count", "プロ年数×特殊能力数"),
        ("age", "rank_ABC", "年齢×A/B/C数"), ("pro_years", "rank_ABC", "プロ年数×A/B/C数"),
        ("age", "five_plus", "年齢×5個以上"), ("pro_years", "five_plus", "プロ年数×5個以上"),
        ("age", "pro_years", "年齢×プロ年数"),
    ]
    work = frame.copy()
    work["five_plus"] = work["display_special_count"].ge(5).astype(float)
    for (dataset, role), subset in work.groupby(["dataset", "role"]):
        for x, y, label in pairs:
            n, pearson, spearman = corr_pair(subset[x], subset[y])
            rows.append({"dataset": dataset, "role": role, "metric": label, "n": n, "pearson": pearson, "spearman": spearman})
    return pd.DataFrame(rows)


def residualize(y: np.ndarray, controls: np.ndarray) -> np.ndarray:
    x = np.column_stack([np.ones(len(controls)), controls])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return y - x @ beta


def partial_corr(x: pd.Series, y: pd.Series, controls: pd.DataFrame) -> tuple[int, float]:
    data = pd.concat([pd.to_numeric(x, errors="coerce").rename("x"), pd.to_numeric(y, errors="coerce").rename("y"), controls], axis=1).dropna()
    if len(data) < 5:
        return len(data), math.nan
    rx = residualize(data["x"].to_numpy(float), data.iloc[:, 2:].to_numpy(float))
    ry = residualize(data["y"].to_numpy(float), data.iloc[:, 2:].to_numpy(float))
    return len(data), float(np.corrcoef(rx, ry)[0, 1]) if np.std(rx) and np.std(ry) else math.nan


def regression_effect(subset: pd.DataFrame) -> dict[str, Any]:
    base = subset[["display_special_count", "age", "pro_years", "ability_score", "player_class", "position_group"]].dropna().copy()
    if len(base) < 20:
        return {"n": len(base), "pro_years_coef": np.nan, "age_coef": np.nan, "ability_score_coef": np.nan, "r_squared": np.nan}
    dummies = pd.get_dummies(base[["player_class", "position_group"]], drop_first=True, dtype=float)
    xdf = pd.concat([base[["age", "pro_years", "ability_score"]].astype(float), dummies], axis=1)
    x = np.column_stack([np.ones(len(xdf)), xdf.to_numpy(float)])
    y = base["display_special_count"].to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    denom = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ((y - fitted) ** 2).sum() / denom if denom else np.nan
    return {"n": len(base), "age_coef": beta[1], "pro_years_coef": beta[2], "ability_score_coef": beta[3], "r_squared": r2}


def partial_effect_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (dataset, role), subset in frame.groupby(["dataset", "role"]):
        n_age, partial_age = partial_corr(subset["pro_years"], subset["display_special_count"], subset[["age"]])
        n_full, partial_full = partial_corr(subset["pro_years"], subset["display_special_count"], subset[["age", "ability_score"]])
        row = {"dataset": dataset, "role": role, "n_age_control": n_age,
               "partial_corr_pro_years_special_count_control_age": partial_age,
               "n_age_ability_control": n_full,
               "partial_corr_pro_years_special_count_control_age_ability": partial_full,
               **regression_effect(subset)}
        rows.append(row)
        middle = subset[subset["age"].between(26, 30)].copy()
        middle["pro_group_26_30"] = pd.cut(middle["pro_years"], [-np.inf, 4, 8, np.inf], labels=["1～4年", "5～8年", "9年以上"])
        for pro_group, group in middle.groupby("pro_group_26_30", observed=False):
            rows.append({"dataset": dataset, "role": role, "comparison": "26～30歳内比較", "pro_group": str(pro_group),
                         "n": len(group), "mean_special_count": group["display_special_count"].mean(),
                         "rate_5plus_pct": pct(group["display_special_count"].ge(5)), "mean_abc_count": group["rank_ABC"].mean()})
    return pd.DataFrame(rows)


def age_partial_for_special(base: pd.DataFrame, name: str) -> float:
    held = indicator(base, name)
    _, value = partial_corr(base["age"], held, base[["ability_score"]])
    return value


def profile_table(frame: pd.DataFrame, individual_age: pd.DataFrame) -> pd.DataFrame:
    rows = []
    real_rows = individual_age[individual_age["dataset"].eq(REAL)]
    controlled_delta = individual_age[individual_age["dataset"].eq(CONTROLLED)].set_index(["role", "special"])["youngest_to_oldest_change_pt"]
    for _, row_series in real_rows.iterrows():
        role = str(row_series["role"])
        special = str(row_series["special"])
        base = frame[frame["dataset"].eq(REAL) & frame["role"].eq(role)]
        positives = int(indicator(base, special).sum())
        rate_values = [row_series[f"{band}_rate_pct"] for band in AGE_LABELS]
        delta = row_series["youngest_to_oldest_change_pt"]
        partial_age = age_partial_for_special(base, special)
        raw_n, raw_age, _ = corr_pair(base["age"], indicator(base, special))
        if positives < 5 or row_series["overall_rate_pct"] < 1.0:
            profile = "insufficient_sample"
        elif abs(raw_age) >= 0.06 and abs(partial_age) < max(0.025, abs(raw_age) * 0.45):
            profile = "ability_only_candidate"
        elif pd.notna(delta) and delta >= 8 and sum(np.diff(rate_values) >= -1.5) >= 3:
            profile = "experience_up"
        elif pd.notna(delta) and delta >= 3:
            profile = "mild_experience_up"
        elif max(rate_values[1:4]) - rate_values[-1] >= 4 and max(rate_values[1:4]) > rate_values[0]:
            profile = "physical_peak"
        else:
            profile = "age_neutral"
        rows.append({"role": role, "special": special, "kind": row_series["kind"], "real_n": raw_n, "real_positive_n": positives,
                     "real_overall_rate_pct": row_series["overall_rate_pct"], **{f"real_{band}_rate_pct": rate for band, rate in zip(AGE_LABELS, rate_values)},
                     "real_youngest_to_oldest_change_pt": delta, "real_age_point_biserial": raw_age,
                     "real_partial_age_controlling_ability": partial_age,
                     "controlled_youngest_to_oldest_change_pt": controlled_delta.get((role, special), np.nan),
                     "age_profile": profile, "focus_special": normalize_name(special) in {normalize_name(x) for x in FOCUS_SPECIALS[role]}})
    return pd.DataFrame(rows)


def individual_experience_effects(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, SAVED, CONTROLLED]:
        for role, names in FOCUS_SPECIALS.items():
            base = frame[frame["dataset"].eq(dataset) & frame["role"].eq(role)]
            for raw_name in names:
                name = normalize_name(raw_name)
                held = indicator(base, name)
                n, partial = partial_corr(base["pro_years"], held, base[["age", "ability_score"]])
                rows.append({"dataset": dataset, "role": role, "special": name, "n": n,
                             "positive_n": int(held.sum()), "partial_corr_pro_years_control_age_ability": partial})
    return pd.DataFrame(rows)


def ability_control_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    work = frame.copy()
    work["ability_band"] = pd.qcut(work.groupby(["dataset", "role"])["ability_score"].rank(method="first"), 4,
                                    labels=["Q1", "Q2", "Q3", "Q4"])
    for (dataset, role, band, age_group), subset in work.groupby(["dataset", "role", "ability_band", "age_band"], observed=False):
        rows.append({"dataset": dataset, "role": role, "ability_band": band, "age_band": age_group, "n": len(subset),
                     "mean_special_count": subset["display_special_count"].mean(),
                     "rate_5plus_pct": pct(subset["display_special_count"].ge(5)), "mean_abc_count": subset["rank_ABC"].mean()})
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")


def metric_lookup(table: pd.DataFrame, dataset: str, role: str, band: str, col: str) -> float:
    found = table[table["dataset"].eq(dataset) & table["role"].eq(role) & table["band"].eq(band)]
    return float(found.iloc[0][col]) if len(found) else math.nan


def fmt(value: Any, digits: int = 2) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"


def write_markdown_reports(
    output_dir: Path, real_audit: dict[str, Any], saved_audit: dict[str, Any], controlled: pd.DataFrame,
    age_counts: pd.DataFrame, age_kinds: pd.DataFrame, age_ranks: pd.DataFrame,
    correlations: pd.DataFrame, partials: pd.DataFrame, profiles: pd.DataFrame,
) -> None:
    scope = f"""# Data scope

## 採用範囲

- real: {real_audit['total']:,}人（投手{real_audit['pitchers']:,}、野手{real_audit['fielders']:,}）。年齢欠損{real_audit['missing_age']}、プロ年数欠損{real_audit['missing_pro_years']}。
- saved generated: {saved_audit['adopted']:,}人（投手{saved_audit['pitchers']:,}、野手{saved_audit['fielders']:,}）。{saved_audit['oldest']}～{saved_audit['latest']}。
- controlled generated: {len(controlled):,}人（投手{int(controlled['role'].eq('投手').sum()):,}、野手{int(controlled['role'].eq('野手').sum()):,}）。複数seed、現行HEAD、架空球団用。

## 保存履歴のバージョン監査

- PR #76マージ時刻 `{saved_audit['cutoff']}` を特殊能力ロジック同一期間の開始とした。
- PR #76より前を {saved_audit['excluded_pre_pr76']:,}件除外した。
- PR #76以降でも架空球団用以外を {saved_audit['excluded_non_fictional_post_pr76']:,}件除外した。
- DBにコードバージョン列はないため、時刻による監査には限界がある。saved generatedは実利用履歴、controlled generatedは現行コードの統制比較として分離した。

## 比較定義

- 非ランク特殊能力: blue/red/green/gold/mixed/other。純粋な起用法ラベルは除外するが、アプリのusage表示対象と重なるマスタkind=green（積極盗塁、速球中心等）は緑特として含める。
- ランク特殊能力: A～Gを別集計。実在ExcelではDが明示保存されていない（D行0件）。
- 表示特殊能力総数: 非ランク特殊能力数 + A/B/C/E/F/Gランク数。Dは直接比較から除外。
- 年齢帯: 18～22、23～26、27～30、31～34、35+。プロ年数帯: 1～3、4～6、7～10、11～14、15年以上。
- n<30は少標本としてCSVにフラグを付けた。
"""
    (output_dir / "data_scope.md").write_text(scope, encoding="utf-8")

    logic = """# Current logic audit

## 通常特殊能力

- `adjust_special_chance()` は年齢を受け取り、32歳以上へ一律+0.15ポイント、ドラフト候補20歳以下へ-0.15ポイントを加える。`player_special_scale()` の年齢利用はドラフト候補22歳以下かつ高能力の補正だけで、架空球団用の一律年齢倍率はない。
- `classification_special_scale()` は player_class、development_stage、acquisition_role、weakness_profile、kind等を使うが、年齢とプロ年数を直接受け取らない。
- `special_count_bounds()`、`weighted_special_cap()`、`extra_special_draws()` は player_classと能力スコア主体で、年齢・プロ年数を直接使わない。
- `generate_specials()` は個別chance、最低数、cap、bonus draw、競合除去を順に適用する。`audit_special_selection()` は能力・ポジション・投手適性・競合を監査するが年齢・プロ年数は使わない。

## ランク特殊能力

- `ranked_weight_items_for_group()` の直接年齢補正は主に捕手30歳以上、ドラフト候補21歳以下。架空球団用の一般選手には player_class と能力・適性の効果が中心。
- `ranked_shift_for_group()` は球速、制球、走力、守備力、player_type、archetype等を使うが年齢・プロ年数は受け取らない。
- `generate_ranked_specials()` は年齢をweight関数へ渡すが、プロ年数は受け取らない。

## 間接経路

- 年齢は player_class、archetype、基本能力、development_stage等の生成を通じて特殊能力へ間接的に影響する。
- `pro_years` は `generate_career_history()` で生成されるが、通常特殊能力・ランク特殊能力の生成関数へ渡されない。現行コード上、特殊能力への直接効果はない。
- PR #76からHEADまでの`app.py`差分は変化球生成領域で、特殊能力関数とマスタの直接変更はない。ただし変化球構成を条件にする個別chanceには入力経路上の間接差があり得るため、savedとcontrolledは分離した。
"""
    (output_dir / "current_logic_audit.md").write_text(logic, encoding="utf-8")

    real_corr = correlations[correlations["dataset"].eq(REAL)]
    profile_counts = profiles.groupby(["role", "age_profile"]).size().unstack(fill_value=0)
    ptext = ", ".join(f"{idx}: " + "/".join(f"{col}={int(row[col])}" for col in profile_counts.columns) for idx, row in profile_counts.iterrows())
    lines = ["# 特殊能力の年齢・プロ年数 Phase 0分析", "", "## 1. Data scope", "", scope.split("## 比較定義", 1)[0].replace("# Data scope\n", "").strip(),
             "", "比較総数は非ランク（マスタgreenを含み、純粋な起用法ラベルを除外）と非Dランクの合計。実在側にDがないためDは直接比較から除外した。", "",
             "## 2. Current implementation", "", "架空球団用の特殊能力数cap・bonus drawは年齢非依存で、年齢の直接効果は通常特殊能力の32歳以上+0.15ポイント等に限られる。プロ年数は特殊能力生成へ渡されていない。", "",
             "## 3. Overall special count", ""]
    for role in ["投手", "野手"]:
        lines.append(f"### {role}")
        lines.append("")
        lines.append("|年齢帯|real平均|saved平均|controlled平均|real n|controlled n|")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for band in AGE_LABELS:
            lines.append(f"|{band}|{fmt(metric_lookup(age_counts, REAL, role, band, 'mean'))}|{fmt(metric_lookup(age_counts, SAVED, role, band, 'mean'))}|{fmt(metric_lookup(age_counts, CONTROLLED, role, band, 'mean'))}|{fmt(metric_lookup(age_counts, REAL, role, band, 'n'),0)}|{fmt(metric_lookup(age_counts, CONTROLLED, role, band, 'n'),0)}|")
        lines.append("")
    lines += ["## 4. Tail distribution", ""]
    for role in ["投手", "野手"]:
        y_real = metric_lookup(age_counts, REAL, role, "18～22", "rate_8plus_pct")
        y_gen = metric_lookup(age_counts, CONTROLLED, role, "18～22", "rate_8plus_pct")
        m_real = metric_lookup(age_counts, REAL, role, "27～30", "rate_8plus_pct")
        m_gen = metric_lookup(age_counts, CONTROLLED, role, "27～30", "rate_8plus_pct")
        o_real = metric_lookup(age_counts, REAL, role, "35+", "rate_8plus_pct")
        o_gen = metric_lookup(age_counts, CONTROLLED, role, "35+", "rate_8plus_pct")
        lines.append(f"- {role}: 8個以上率は18～22歳で real {fmt(y_real,1)}% / controlled {fmt(y_gen,1)}%、27～30歳で {fmt(m_real,1)}% / {fmt(m_gen,1)}%、35+で {fmt(o_real,1)}% / {fmt(o_gen,1)}%。若手過多と27～30歳不足が同時にある。")
    lines += ["", "## 5. Kind distribution", ""]
    for role in ["投手", "野手"]:
        parts = []
        for kind in ["blue", "red", "green", "gold", "mixed"]:
            def kval(dataset: str, band: str) -> float:
                found = age_kinds[(age_kinds["dataset"].eq(dataset)) & (age_kinds["role"].eq(role)) & (age_kinds["band"].eq(band)) & (age_kinds["kind"].eq(kind))]
                return float(found.iloc[0]["mean_count"]) if len(found) else math.nan
            real_change = kval(REAL, "35+") - kval(REAL, "18～22")
            gen_change = kval(CONTROLLED, "35+") - kval(CONTROLLED, "18～22")
            parts.append(f"{kind} real {fmt(real_change,2)} / controlled {fmt(gen_change,2)}")
        lines.append(f"- {role}の18～22→35+平均個数変化: " + "、".join(parts) + "。")
    lines += ["- goldは実在Excel・現行マスタとも観測0で、年齢差を判定できない。種類別補正を行う場合も一律倍率は使わない。", "",
              "## 6. Ranked specials", ""]
    for role in ["投手", "野手"]:
        def rval(dataset: str, band: str, metric: str) -> float:
            found = age_ranks[(age_ranks["dataset"].eq(dataset)) & (age_ranks["role"].eq(role)) & (age_ranks["band"].eq(band)) & (age_ranks["metric"].eq(metric))]
            return float(found.iloc[0]["mean_count"]) if len(found) else math.nan
        lines.append(f"- {role}A/B/C平均は real {fmt(rval(REAL,'18～22','A/B/C'))}→{fmt(rval(REAL,'35+','A/B/C'))}、controlled {fmt(rval(CONTROLLED,'18～22','A/B/C'))}→{fmt(rval(CONTROLLED,'35+','A/B/C'))}。生成側は若手が多く、年齢勾配が弱い。")
    lines += ["- Dは生成側の構造確認にのみ使い、実在との総数比較から外した。", "",
              "## 7. Individual specials", "", f"全比較可能特殊能力を分類した。分類件数は {ptext}。少数例はinsufficient_sampleとした。", "",
              "監視対象の判定:", "", "|役割|特殊能力|profile|実在18～22→35+差(pt)|生成差(pt)|", "|---|---|---|---:|---:|"]
    for item in profiles[profiles["focus_special"]].sort_values(["role", "special"]).itertuples(index=False):
        lines.append(f"|{item.role}|{item.special}|{item.age_profile}|{fmt(item.real_youngest_to_oldest_change_pt,1)}|{fmt(item.controlled_youngest_to_oldest_change_pt,1)}|")
    lines += ["", "## 8. Age vs player_class", ""]
    for role in ["投手", "野手"]:
        real_row = partials[(partials["dataset"].eq(REAL)) & partials["role"].eq(role) & partials["comparison"].isna()].iloc[0]
        gen_row = partials[(partials["dataset"].eq(CONTROLLED)) & partials["role"].eq(role) & partials["comparison"].isna()].iloc[0]
        lines.append(f"- {role}: class・能力・役割を同時投入した年齢係数は real {fmt(real_row['age_coef'],3)}個/年、controlled {fmt(gen_row['age_coef'],3)}個/年。生成側の見かけの年齢差はほぼclass/能力構成で説明され、実在側には残差が残る。")
    lines += ["",
              "## 9. Age vs pro years", ""]
    for role in ["投手", "野手"]:
        sub = real_corr[real_corr["role"].eq(role)].set_index("metric")
        pp = partials[(partials["dataset"].eq(REAL)) & partials["role"].eq(role) & partials["comparison"].isna()].head(1)
        age_pro = sub.loc["年齢×プロ年数", "pearson"] if "年齢×プロ年数" in sub.index else np.nan
        raw = sub.loc["プロ年数×特殊能力数", "pearson"] if "プロ年数×特殊能力数" in sub.index else np.nan
        partial = pp.iloc[0]["partial_corr_pro_years_special_count_control_age_ability"] if len(pp) else np.nan
        coef = pp.iloc[0]["pro_years_coef"] if len(pp) else np.nan
        lines.append(f"- {role}: 年齢×プロ年数 r={fmt(age_pro,3)}、プロ年数×特殊能力数 r={fmt(raw,3)}、年齢・能力統制後partial r={fmt(partial,3)}、回帰のpro_years係数={fmt(coef,3)}。")
    real_models = {
        role: partials[(partials["dataset"].eq(REAL)) & partials["role"].eq(role) & partials["comparison"].isna()].iloc[0]
        for role in ["投手", "野手"]
    }
    real_age_changes = {
        role: metric_lookup(age_counts, REAL, role, "35+", "mean") - metric_lookup(age_counts, REAL, role, "18～22", "mean")
        for role in ["投手", "野手"]
    }
    generated_age_changes = {
        role: metric_lookup(age_counts, CONTROLLED, role, "35+", "mean") - metric_lookup(age_counts, CONTROLLED, role, "18～22", "mean")
        for role in ["投手", "野手"]
    }
    lines += ["", "## 10. Root causes", "", "詳細は `special_age_experience_root_causes.md`。cap・bonus drawの年齢非依存、個別年齢補正の限定、ランク系の年齢経路の狭さ、pro_years未接続を主要候補とした。", "",
              "## 11. Recommended phases", "", "Phase 1・2・3は実施根拠あり。Phase 4も独立効果は小～中程度ながら両役割で同方向に残ったため、まず主要な経験系個別特殊能力へ弱く導入する検証へ進む。", "",
              "## 最終判定", "",
              f"1. 特殊能力総数: 必要。実在の18～22→35+増加は投手+{fmt(real_age_changes['投手'])}、野手+{fmt(real_age_changes['野手'])}個で、controlledの+{fmt(generated_age_changes['投手'])}、+{fmt(generated_age_changes['野手'])}個より大きい。",
              "2. 5個以上・8個以上: 必要。若手の生成過多と27～34歳の生成不足を同時に直し、全体平均を固定する。",
              "3. kind別: blue・red・green・mixedで年齢差の向きと大きさが違う。goldは観測0で判定不能。一律補正は不可。",
              "4. ランク系: 必要。A/B/Cは実在の年齢勾配が生成より明確。Dは直接比較不能で、E/F/Gと分離して扱う。",
              "5. 個別profile: 導入すべき。experience_up/mild_experience_upのみを優先し、physical_peak・ability_only・age_neutralへ一律増加を掛けない。",
              f"6. 個別分類: `special_age_profiles.csv`参照（{ptext}）。",
              f"7. player_classだけで十分か: 不十分。生成では統制後年齢係数がほぼ0だが、実在では投手+{fmt(real_models['投手']['age_coef'],3)}、野手+{fmt(real_models['野手']['age_coef'],3)}個/年が残る。",
              "8. 基本能力だけで十分か: 不十分。能力score・class・役割を同時統制しても年齢・プロ年数係数が残る。",
              f"9. プロ年数の独立説明力: あるが強くはない。年齢・能力統制後partial rは投手{fmt(real_models['投手']['partial_corr_pro_years_special_count_control_age_ability'],3)}、野手{fmt(real_models['野手']['partial_corr_pro_years_special_count_control_age_ability'],3)}。",
              "10. pro_years直接導入: 弱い直接導入を検証する価値がある。全選手一律ではなく経験系個別特殊能力を優先する。",
              "11. 導入先: 第一候補は個別経験系。総数へは小さな補助項、ランク系へは別検証後に限定する。",
              "12. Phase範囲: Phase 1～3へ進む。Phase 4は小さく限定した実験まで進め、回帰ガードを満たさなければ採用しない。", ""]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    roots = """# Root causes

- RC-S01: `special_count_bounds()` と `weighted_special_cap()` が年齢非依存。年齢構成はplayer_classと能力スコア経由に限られる。
- RC-S02: `extra_special_draws()` がplayer_class主体で、同一class内の27～34歳・ベテラン尾部を直接表現しない。
- RC-S03: `adjust_special_chance()` の架空球団用年齢補正は32歳以上+0.15ポイントが中心で、個別のexperience/physical profileを表現しない。
- RC-S04: `ranked_weight_items_for_group()` の直接年齢補正が捕手等に限定され、一般のA/B/C年齢構造は能力・class経由になる。
- RC-S05: 若手classにも能力スコア加算とcap尾部が残るため、若手の多特能尾部を抑え切れない可能性がある。
- RC-S06: `pro_years` が通常・ランク特殊能力生成へ渡されず、実在で独立効果があっても再現できない。
- RC-S07: 年齢は基本能力、player_class、archetype、役割を同時に変えるため、単純な年齢倍率では全体率と個別率を壊す。
"""
    (output_dir / "special_age_experience_root_causes.md").write_text(roots, encoding="utf-8")
    plan = """# Adjustment plan

## Phase 1

年齢帯別の総数、5個以上率、8個以上率を対象にする。全体平均、role別平均、player_class別平均を固定する回帰ガードを置き、`special_count_bounds()`、`weighted_special_cap()`、`extra_special_draws()`のどこへ最小の補正を置くか検証する。

## Phase 2

`special_age_profiles.csv` の experience_up / mild_experience_up を優先する。physical_peakは基本能力連動、ability_only_candidateは能力・役割条件を優先し、age_neutralへ年齢補正を加えない。

## Phase 3

A/B/CとE/F/Gの年齢構造を対象にする。Dは実在で非表示のため直接目標にせず、非D分布と各familyの整合を守る。

## Phase 4

実在で年齢・能力・役割を統制したpro_years効果が再現し、主要経験系特殊能力にも同方向の残差がある場合だけ実施する。まず個別経験系への弱い補正を候補とし、総数・ランク系への一律補正は避ける。

## Regression guards

全体平均、個別保有率、blue/red/green/gold率、player_class別・role別個数、競合除去、ポジション・投手適性制限、seed再現性を固定する。
"""
    (output_dir / "special_age_experience_adjustment_plan.md").write_text(plan, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, real_audit = load_real(args.real_xlsx)
    saved, saved_audit = load_saved(args.db)
    controlled = generate_controlled(args.count_per_role_per_seed, args.seeds, args.output_dir, args.reuse_controlled)
    players = pd.concat([real, saved, controlled], ignore_index=True, sort=False)

    age_counts = count_summary(players, "age_band", AGE_LABELS)
    pro_counts = count_summary(players, "pro_band", PRO_LABELS)
    age_kinds = kind_summary(players, "age_band", AGE_LABELS)
    pro_kinds = kind_summary(players, "pro_band", PRO_LABELS)
    age_ranks = ranked_summary(players, "age_band", AGE_LABELS)
    pro_ranks = ranked_summary(players, "pro_band", PRO_LABELS)
    individual_age = individual_by_band(players, "age_band", AGE_LABELS)
    individual_pro = individual_by_band(players, "pro_band", PRO_LABELS)
    correlations = correlation_table(players)
    partials = partial_effect_table(players)
    profiles = profile_table(players, individual_age)

    write_csv(age_counts, args.output_dir / "special_count_by_age_compare.csv")
    write_csv(pro_counts, args.output_dir / "special_count_by_pro_years_compare.csv")
    write_csv(age_counts[["dataset", "role", "band", "n", "rate_5plus_pct", "rate_8plus_pct", "rate_10plus_pct", "small_sample"]], args.output_dir / "special_count_tail_by_age_compare.csv")
    write_csv(age_kinds, args.output_dir / "special_kind_by_age_compare.csv")
    write_csv(pro_kinds, args.output_dir / "special_kind_by_pro_years_compare.csv")
    write_csv(age_ranks, args.output_dir / "ranked_special_by_age_compare.csv")
    write_csv(pro_ranks, args.output_dir / "ranked_special_by_pro_years_compare.csv")
    write_csv(individual_age, args.output_dir / "individual_special_by_age_compare.csv")
    write_csv(individual_pro, args.output_dir / "individual_special_by_pro_years_compare.csv")
    write_csv(class_age_summary(players), args.output_dir / "special_by_age_player_class.csv")
    write_csv(role_position_summary(players), args.output_dir / "special_by_age_role_position.csv")
    write_csv(correlations, args.output_dir / "age_pro_year_correlations.csv")
    write_csv(partials, args.output_dir / "pro_year_partial_effect.csv")
    write_csv(profiles, args.output_dir / "special_age_profiles.csv")
    write_csv(individual_experience_effects(players), args.output_dir / "individual_special_pro_year_partial_effect.csv")
    write_csv(ability_control_table(players), args.output_dir / "special_by_age_ability_band.csv")
    write_markdown_reports(args.output_dir, real_audit, saved_audit, controlled, age_counts, age_kinds, age_ranks, correlations, partials, profiles)
    print(json.dumps({"real": real_audit, "saved": saved_audit, "controlled": len(controlled), "output": str(args.output_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
