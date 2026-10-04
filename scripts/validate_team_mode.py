"""球団生成モードの検証。

固定seedで球団を生成し、実在データ（data/reference/ と 2026年版実在12球団の選手データ）と比べて
reports/team_mode/ にレポートを出す。

    python scripts/validate_team_mode.py                 # 既定: 構成・背番号500球団、戦力600球団、カラー7×200球団
    python scripts/validate_team_mode.py --teams 50 --strength-teams 100 --color-teams 30 --quick   # 簡易版（合否は「参考」になる）

合否の付け方・誤差は checklib.py（判定の整理_改修指示.md）。判定の一覧は reports/checks/validate_team_mode.csv。
終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。

出力:
    summary.md                    合否と主な表
    composition_compare.csv       構成項目の実在と生成の比較
    strength_metrics.csv          戦力レベル別の査定指標
    strength_teams.csv            戦力確認用の球団ごとの値
    strength_scatter.html         戦力指数と査定指標の散布図
    color_effects.csv             チームカラー別の効果（t=1.0固定）
    color_intensity.csv           効き具合 t と効果の大きさ（通常抽選の球団）
    uniform_number_usage.csv      番号ごとの使用率・区分比率（実在と生成）
    uniform_number_bands.csv      番号帯ごとの査定百分位・年齢
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import pandas as pd  # noqa: E402

from generator import team as team_lib  # noqa: E402
from generator.rating import player_rating  # noqa: E402
from generator.real_data import attach_real_details, real_player_to_rating_dict  # noqa: E402

import check_age_profile  # noqa: E402
import checklib  # noqa: E402
from checklib import Checks  # noqa: E402

SCRIPT = "validate_team_mode"

OUTPUT_DIR = APP_DIR / "reports" / "team_mode"
REAL_PLAYERS_DIR = APP_DIR / "reports" / "real_powerpro_players_12teams"
BASE_SEED = 20261001
STRENGTH_BASE_SEED = 30000000
COLOR_BASE_SEED = 40000000
# 投手指標と野手指標の相関の目標。実在は 2026年版12球団 0.37、2024〜2026年版36球団 0.21、2022〜2026年版60球団 0.27。
# 以前は12球団の値から 0.25〜0.60 にしていた。球団ごとの散らばり_改修指示.md で戦力レベルの倍率を弱めると
# 共通の戦力指数の効きが小さくなり相関が下がるため、36・60球団の値を含む 0.10〜0.45 にした
CORRELATION_RANGE = (0.10, 0.45)
# (e) の「強豪の中央値 > 中位の〇%点」。総合力・全員平均は上位25%（75%点）のまま、投手力・野手力は60%点。
# 球団ごとの散らばりを実在に合わせると、投手・野手の上位の平均は選手ごとのばらつきが大きく、強豪と中位の差が埋もれやすいため
STRENGTH_E_MID_QUANTILE = {"metric_pitcher_top": 0.60, "metric_fielder_top": 0.60}
COLOR_CHECKS = {
    "投手王国": [("pitcher_top_pct", 4.0, 10.0, "投手の査定の上位の平均（%）")],
    "強力打線": [("power", 2.0, 5.0, "野手のパワーの平均"), ("contact_power", 3.0, 7.0, "ミート＋パワー")],
    "機動力": [("speed", 3.0, 6.0, "野手の走力の平均")],
    "守備重視": [("fielding", 2.0, 5.0, "野手の守備力の平均"), ("arm", 1.0, 4.0, "野手の肩力の平均")],
    "若手育成": [("age", -2.5, -1.0, "平均年齢")],
    "ベテラン重視": [("age", 1.0, 2.5, "平均年齢")],
}
# 強力打線は「パワー +2〜+5 または ミート＋パワー +3〜+7」、守備重視は両方
COLOR_ANY_OF = {"強力打線"}

_MASTER = None


# ---------------------------------------------------------------------------
# 生成（ワーカー）
# ---------------------------------------------------------------------------
def _init_worker() -> None:
    logging.disable(logging.WARNING)
    global _MASTER
    import app  # noqa: F401

    _MASTER = app.load_master_data()


def _value(abilities: dict[str, Any], key: str) -> float:
    item = abilities.get(key)
    if isinstance(item, dict):
        item = item.get("value")
    try:
        return float(str(item).split()[0])
    except (TypeError, ValueError, IndexError):
        return math.nan


def _team_record(team: dict[str, Any]) -> dict[str, Any]:
    players = team["players"]
    profile = team["profile"]
    domestic = [p for p in players if p.get("roster_origin") != "foreign_import"]
    domestic_fielders = [p for p in domestic if p.get("role") == "野手"]
    domestic_pitchers = [p for p in domestic if p.get("role") == "投手"]
    metrics = team_lib.team_rating_metrics(players)
    percentiles = team_lib.role_percentiles(players)
    mean = lambda values: float(statistics.fmean(values)) if values else math.nan  # noqa: E731
    fielder_values = {key: mean([_value(p["abilities"], key) for p in domestic_fielders]) for key in ("ミート", "パワー", "走力", "守備力", "肩力")}
    numbers = [str(p.get("uniform_number", "")) for p in players]
    return {
        "team_seed": team["team_seed"],
        "strength": profile.strength,
        "s": profile.strength_index,
        "s_pitcher": profile.strength_index_pitcher,
        "s_fielder": profile.strength_index_fielder,
        "color": profile.color,
        "color_intensity": profile.color_intensity,
        "sub_color": profile.sub_color,
        "sub_color_intensity": profile.sub_color_intensity,
        "template": f"{team['template']['season']} {team['template']['team']}",
        "elapsed": team["elapsed_seconds"],
        **{f"relaxed_{key}": value for key, value in team["relaxed"].items()},
        "relaxed_total": sum(team["relaxed"].values()),
        "targets_match": all(team["targets"][key] == team["actual"][key] for key in team["targets"]),
        **{f"metric_{key}": value for key, value in metrics.items()},
        "dom_pitcher_top": team_lib._top_mean([player_rating(p) for p in domestic_pitchers], team_lib.TOP_PITCHER_COUNT),
        "dom_contact": fielder_values["ミート"],
        "dom_power": fielder_values["パワー"],
        "dom_speed": fielder_values["走力"],
        "dom_fielding": fielder_values["守備力"],
        "dom_arm": fielder_values["肩力"],
        "dom_age": mean([int(p.get("age") or 0) for p in domestic]),
        "avg_age": team_lib.average_age(players),
        **{f"comp_{key}": value for key, value in team["actual"].items()},
        "name_duplicates": len(players) - len({p["name"] for p in players}),
        "number_duplicates": len(numbers) - len(set(numbers)),
        "number_missing": sum(not number for number in numbers),
        "retired_used": len(set(numbers) & set(team["retired_numbers"])),
        "retired_numbers": ",".join(team["retired_numbers"]),
        "retired_count": len(team["retired_numbers"]),
        "age_rows": [{**check_age_profile.player_metrics(p, "球団"), "team": team["team_seed"]} for p in players if check_age_profile.is_target(p)],
        "uniform_rows": [
            {
                "number": str(p.get("uniform_number")),
                "role": "投手" if p.get("role") == "投手" else "野手",
                "group": team_lib.uniform_player_group(p),
                "foreign": p.get("roster_origin") == "foreign_import",
                "percentile": percentiles[i],
                "age": int(p.get("age") or 0),
            }
            for i, p in enumerate(players)
        ],
    }


def _generate(job: tuple[int, dict[str, Any] | None]) -> dict[str, Any]:
    import app

    seed, profile_kwargs = job
    profile = team_lib.build_team_profile(seed, **profile_kwargs) if profile_kwargs else None
    team = app.generate_team(seed, master=_MASTER, profile=profile)
    return _team_record(team)


def run_jobs(jobs: list[tuple[int, dict[str, Any] | None]], workers: int, label: str) -> list[dict[str, Any]]:
    print(f"[{label}] {len(jobs)}球団を生成します（{workers}並列）", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        records = list(pool.map(_generate, jobs, chunksize=4))
    print(f"[{label}] 完了", flush=True)
    return records


# ---------------------------------------------------------------------------
# 球団ごとの散らばり（球団ごとの散らばり_改修指示.md §3-1）
# ---------------------------------------------------------------------------
SPREAD_BASE_SEED = 1
SPREAD_SEASONS = (2024, 2025, 2026)
# (表示名, 軸, グループ, 指標)。指標の計算は generator/team_analysis.py の関数を使う（外国人を含む）
SPREAD_RATING_ITEMS = (
    ("総合力", "主要指標", "球団", "総合力"),
    ("投手力", "主要指標", "球団", "投手力"),
    ("野手力", "主要指標", "球団", "野手力"),
    ("全員平均", "主要指標", "球団", "全員平均"),
    ("投手の査定の平均", "投手/野手", "投手", "査定_平均"),
    ("野手の査定の平均", "投手/野手", "野手", "査定_平均"),
)
SPREAD_ABILITY_ITEMS = (
    *((f"{group}の{metric}", "投手役割", group, metric) for group in ("先発", "救援") for metric in ("球速", "コントロール", "スタミナ")),
    *((f"野手の{metric}", "投手/野手", "野手", metric) for metric in ("弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球")),
)
SPREAD_ITEMS = SPREAD_RATING_ITEMS + SPREAD_ABILITY_ITEMS
# 合格の範囲
SPREAD_RATING_SD_RATIO = (0.85, 1.20)
SPREAD_RATING_TAIL_SD = 0.5
SPREAD_ABILITY_SD_RATIO_MAX = 1.25
SPREAD_TOP28_MEDIAN_RATE = 0.02
SPREAD_RELIEVER_CONTROL_P90_MARGIN = 1.0
# 能力の SD比の判定から除くチームカラー（その能力を動かすカラー。メイン・サブどちらでも除く）。
# 年齢帯の判定で若手育成・ベテラン重視を除くのと同じ扱い。カラーの目安（機動力で走力+3以上など）を満たすと、
# その分だけ球団ごとの散らばりが実在より大きくなるため（散らばりの表には除く前の値も出す）
SPREAD_COLOR_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "機動力": ("野手の走力",),
    "守備重視": ("野手の守備力", "野手の肩力"),
    "強力打線": ("野手のミート", "野手のパワー"),
    "投手王国": tuple(f"{group}の{metric}" for group in ("先発", "救援") for metric in ("球速", "コントロール", "スタミナ")),
}


def spread_excluded_colors(label: str) -> set[str]:
    return {color for color, labels in SPREAD_COLOR_EXCLUSIONS.items() if label in labels}
# 選手格の人数の表に出す選手格（国内選手）
SPREAD_CLASS_ROWS = (("投手", "スター級"), ("投手", "一軍主力級"), ("投手", "一軍控え級"), ("投手", "二軍級"), ("投手", "若手素材型"), ("投手", "ベテラン型"),
                     ("野手", "スター級"), ("野手", "一軍主力級"), ("野手", "一軍控え級"), ("野手", "二軍級"), ("野手", "若手素材型"), ("野手", "ベテラン型"))
# 改修前・途中の段階の値（同じ seed 1〜300 で計測した値）。各項目は (10%, 中央, 90%, SD)。
# 表の「改修前」「ステップ1後」などの列に出す。最終の列は、この検証の実行結果。
SPREAD_HISTORY: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "改修前": {
        "総合力": (313.67, 330.77, 344.86, 12.52),
        "投手力": (327.69, 346.42, 365.25, 14.86),
        "野手力": (283.27, 304.93, 325.02, 15.69),
        "全員平均": (259.64, 273.65, 286.2, 10.42),
        "投手の査定の平均": (273.0, 291.66, 311.67, 14.42),
        "野手の査定の平均": (238.77, 254.09, 268.83, 11.99),
        "先発の球速": (149.59, 151.13, 152.63, 1.14),
        "先発のコントロール": (49.73, 55.28, 60.07, 3.94),
        "先発のスタミナ": (54.53, 58.43, 62.11, 2.9),
        "救援の球速": (151.27, 152.64, 154.0, 1.12),
        "救援のコントロール": (43.73, 48.16, 52.44, 3.19),
        "救援のスタミナ": (44.65, 47.9, 50.92, 2.37),
        "野手の弾道": (2.55, 2.69, 2.86, 0.12),
        "野手のミート": (37.35, 40.22, 43.2, 2.17),
        "野手のパワー": (51.16, 54.37, 57.31, 2.35),
        "野手の走力": (60.06, 63.34, 68.38, 3.07),
        "野手の肩力": (63.97, 66.71, 69.01, 1.93),
        "野手の守備力": (48.44, 51.41, 55.0, 2.54),
        "野手の捕球": (44.72, 48.06, 51.37, 2.48),
    },
    "ステップ1後": {
        "総合力": (314.24, 330.36, 346.93, 12.77),
        "投手力": (330.22, 346.92, 365.41, 13.9),
        "野手力": (282.93, 302.47, 320.67, 14.96),
        "全員平均": (259.8, 273.34, 286.25, 10.35),
        "投手の査定の平均": (276.91, 291.83, 312.54, 13.69),
        "野手の査定の平均": (237.95, 251.57, 265.61, 10.62),
        "先発の球速": (149.64, 151.17, 152.44, 1.05),
        "先発のコントロール": (50.74, 55.18, 60.13, 3.63),
        "先発のスタミナ": (55.52, 58.7, 62.84, 2.91),
        "救援の球速": (151.12, 152.67, 154.07, 1.19),
        "救援のコントロール": (44.56, 48.08, 52.3, 3.0),
        "救援のスタミナ": (44.86, 47.91, 51.01, 2.26),
        "野手の弾道": (2.53, 2.69, 2.86, 0.13),
        "野手のミート": (37.39, 39.79, 42.4, 1.99),
        "野手のパワー": (51.12, 53.93, 57.33, 2.39),
        "野手の走力": (60.22, 63.69, 67.65, 2.9),
        "野手の肩力": (64.08, 66.64, 68.97, 1.9),
        "野手の守備力": (48.02, 50.97, 54.22, 2.52),
        "野手の捕球": (44.87, 47.54, 50.94, 2.36),
    },
    "ステップ2後": {
        "総合力": (315.28, 330.2, 345.59, 11.87),
        "投手力": (330.53, 346.73, 366.42, 13.95),
        "野手力": (284.57, 302.03, 320.14, 13.55),
        "全員平均": (260.7, 273.27, 284.91, 9.8),
        "投手の査定の平均": (277.64, 292.16, 311.67, 13.31),
        "野手の査定の平均": (238.57, 252.1, 263.84, 10.11),
        "先発の球速": (149.81, 151.13, 152.53, 1.06),
        "先発のコントロール": (51.0, 54.94, 59.02, 3.17),
        "先発のスタミナ": (55.41, 58.56, 62.49, 2.77),
        "救援の球速": (151.52, 152.71, 154.0, 1.06),
        "救援のコントロール": (44.2, 48.06, 51.8, 3.03),
        "救援のスタミナ": (45.31, 48.0, 50.71, 2.1),
        "野手の弾道": (2.56, 2.69, 2.85, 0.12),
        "野手のミート": (37.71, 39.92, 42.18, 1.82),
        "野手のパワー": (51.38, 53.89, 56.66, 2.15),
        "野手の走力": (61.03, 63.66, 67.22, 2.58),
        "野手の肩力": (64.33, 66.67, 68.73, 1.74),
        "野手の守備力": (48.38, 50.93, 53.72, 2.11),
        "野手の捕球": (45.39, 47.59, 49.88, 1.94),
    },
}
# 改修前の選手格の人数（国内選手、1球団あたり）。(平均, SD, 最小, 最大)
SPREAD_CLASS_HISTORY: dict[tuple[str, str], tuple[float, float, int, int]] = {
    ("投手", "スター級"): (2.35, 2.28, 0, 14),
    ("投手", "一軍主力級"): (10.73, 4.8, 2, 25),
    ("投手", "一軍控え級"): (6.21, 2.76, 0, 16),
    ("投手", "二軍級"): (6.32, 3.41, 0, 18),
    ("投手", "若手素材型"): (2.72, 2.09, 0, 9),
    ("投手", "ベテラン型"): (3.13, 2.24, 0, 14),
    ("野手", "スター級"): (1.29, 1.24, 0, 5),
    ("野手", "一軍主力級"): (7.77, 3.31, 1, 16),
    ("野手", "一軍控え級"): (7.01, 2.5, 1, 16),
    ("野手", "二軍級"): (8.5, 2.82, 3, 17),
    ("野手", "若手素材型"): (2.77, 1.78, 0, 10),
    ("野手", "ベテラン型"): (3.61, 2.18, 0, 11),
}


def _spread_record(team: dict[str, Any]) -> dict[str, Any]:
    import app
    from generator import real_data
    from generator import team_analysis as ta

    players = team["players"]
    key = f"gen:{team['team_seed']}"
    frame = ta.players_frame(players, key, key, app.team_pitcher_role)
    frame = ta.assign_categories(frame, ta.rating_cuts_from_stats(real_data.load_global_stats()))
    long = pd.concat([ta.team_headline(frame), ta.group_stats(frame, ta.AXIS_ROLE), ta.group_stats(frame, ta.AXIS_PITCHER_ROLE)], ignore_index=True)
    lookup = {(row.axis, row.group, row.metric): float(row.value) for row in long.itertuples()}
    domestic = [p for p in players if p.get("roster_origin") != "foreign_import"]
    counts = Counter((("投手" if p.get("role") == "投手" else "野手"), str(p.get("player_class", ""))) for p in domestic)
    archetypes = Counter((("投手" if p.get("role") == "投手" else "野手"), str(p.get("archetype", ""))) for p in domestic)
    styles = Counter((("投手" if p.get("role") == "投手" else "野手"), str(p.get("position_style", ""))) for p in domestic)
    return {
        "team_seed": team["team_seed"],
        "strength": team["profile"].strength,
        "color": team["profile"].color,
        "sub_color": team["profile"].sub_color,
        "elapsed": team["elapsed_seconds"],
        "relaxed": dict(team["relaxed"]),
        "values": {label: lookup.get((axis, group, metric), math.nan) for label, axis, group, metric in SPREAD_ITEMS},
        "class_counts": {f"{role}|{label}": counts.get((role, label), 0) for role, label in SPREAD_CLASS_ROWS},
        "archetype_counts": {f"{role}|{label}": count for (role, label), count in archetypes.items()},
        "style_counts": {f"{role}|{label}": count for (role, label), count in styles.items()},
    }


def _generate_spread(seed: int) -> dict[str, Any]:
    import app

    return _spread_record(app.generate_team(seed, master=_MASTER))


def run_spread_jobs(teams: int, workers: int) -> list[dict[str, Any]]:
    seeds = [SPREAD_BASE_SEED + i for i in range(teams)]
    print(f"[散らばり] {len(seeds)}球団を生成します（{workers}並列）", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        records = list(pool.map(_generate_spread, seeds, chunksize=4))
    print("[散らばり] 完了", flush=True)
    return records


def real_spread_frame() -> pd.DataFrame:
    """実在（2024〜2026年版の36チーム、外国人を含む）の、球団（行）×項目（列）の値。実在側の誤差を球団の再抽出で見るために、球団をそろえて持つ。"""
    from generator import real_data

    stats = real_data.load_real_team_stats(SPREAD_SEASONS)
    stats = stats.assign(team_id=stats["season"].astype(str) + "|" + stats["team"].astype(str))
    columns = {}
    for label, axis, group, metric in SPREAD_ITEMS:
        rows = stats[(stats["axis"] == axis) & (stats["group"] == group) & (stats["metric"] == metric)]
        columns[label] = rows.set_index("team_id")["value"].astype(float)
    return pd.DataFrame(columns)


def real_spread_values() -> dict[str, list[float]]:
    frame = real_spread_frame()
    return {label: frame[label].dropna().tolist() for label in frame.columns}


def spread_summary(values: list[float]) -> tuple[float, float, float, float]:
    series = pd.Series(values, dtype=float).dropna()
    return (float(series.quantile(0.1)), float(series.median()), float(series.quantile(0.9)), float(series.std()))


def _fmt_spread(item: tuple[float, float, float, float]) -> str:
    return f"{item[0]:.1f}／{item[1]:.1f}／{item[2]:.1f}（SD {item[3]:.2f}）"


def spread_tables(records: list[dict[str, Any]], real_values: dict[str, list[float]]) -> tuple[pd.DataFrame, pd.DataFrame, Checks]:
    rating_labels = {label for label, *_rest in SPREAD_RATING_ITEMS}
    rows = []
    C = Checks(SCRIPT)
    sec = "球団ごとの散らばり"
    for label, *_rest in SPREAD_ITEMS:
        real = spread_summary(real_values[label])
        gen = spread_summary([record["values"][label] for record in records])
        ratio = gen[3] / real[3] if real[3] else math.nan
        # 能力の SD比は、その能力を動かすチームカラーの球団（メイン・サブどちらでも）を除いて判定する
        judged = [record for record in records if not ({record["color"], record.get("sub_color", "")} & spread_excluded_colors(label))]
        gen_judged = spread_summary([record["values"][label] for record in judged]) if len(judged) < len(records) else gen
        ratio_judged = gen_judged[3] / real[3] if real[3] else math.nan
        key = f"{SCRIPT}.spread.{label}"
        shown = f"生成 {_fmt_spread(gen)}、実在 {_fmt_spread(real)}"
        checks = []
        if label in rating_labels:
            low, high = SPREAD_RATING_SD_RATIO
            checks.append((f"SD比 {low}〜{high}", C.add(f"{key}.sd_ratio", "実在", f"散らばり: {label} のSD比 {low}〜{high}", ratio, low, high, section=sec, shown=f"{ratio:.2f}", real=shown)))
            margin = real[3] * SPREAD_RATING_TAIL_SD
            checks.append((f"10%が実在±{margin:.2f}", C.add(f"{key}.p10", "実在", f"散らばり: {label} の10%が実在±{margin:.2f}", gen[0], real[0] - margin, real[0] + margin,
                                                       section=sec, shown=f"{gen[0]:.1f}", real=shown)))
            checks.append((f"90%が実在±{margin:.2f}", C.add(f"{key}.p90", "実在", f"散らばり: {label} の90%が実在±{margin:.2f}", gen[2], real[2] - margin, real[2] + margin,
                                                       section=sec, shown=f"{gen[2]:.1f}", real=shown)))
        else:
            excluded = "・".join(sorted(spread_excluded_colors(label)))
            note = f"（{excluded}の球団を除く{len(judged)}球団で {ratio_judged:.2f}、除く前 {ratio:.2f}）" if excluded else ""
            checks.append((f"SD比 {SPREAD_ABILITY_SD_RATIO_MAX}以下{note}", C.add(f"{key}.sd_ratio", "実在", f"散らばり: {label} のSD比 {SPREAD_ABILITY_SD_RATIO_MAX}以下{note}", ratio_judged,
                                                                          None, SPREAD_ABILITY_SD_RATIO_MAX, section=sec, shown=f"{ratio_judged:.2f}", real=shown)))
        if label == "総合力":
            rate = gen[1] / real[1] - 1
            checks.append((f"中央が実在±{SPREAD_TOP28_MEDIAN_RATE * 100:.0f}%（{rate * 100:+.1f}%）",
                           C.add(f"{key}.median", "実在", f"散らばり: {label} の中央が実在±{SPREAD_TOP28_MEDIAN_RATE * 100:.0f}%", rate, -SPREAD_TOP28_MEDIAN_RATE, SPREAD_TOP28_MEDIAN_RATE,
                                 section=sec, shown=f"{rate * 100:+.1f}%", real=shown)))
        if label == "救援のコントロール":
            checks.append((f"90%が実在＋{SPREAD_RELIEVER_CONTROL_P90_MARGIN}以内",
                           C.add(f"{key}.p90_margin", "実在", f"散らばり: {label} の90%が実在＋{SPREAD_RELIEVER_CONTROL_P90_MARGIN}以内", gen[2], None, real[2] + SPREAD_RELIEVER_CONTROL_P90_MARGIN,
                                 section=sec, shown=f"{gen[2]:.2f}", real=shown)))
        row = {"項目": label, "実在 10%／中央／90%": f"{real[0]:.1f}／{real[1]:.1f}／{real[2]:.1f}", "実在SD": round(real[3], 2)}
        for stage, history in SPREAD_HISTORY.items():
            past = history.get(label)
            row[f"{stage} SD比"] = round(past[3] / real[3], 2) if past else math.nan
        ok = all(item.low is None and item.high is None or checklib.distance_outside(item.value, item.low, item.high) == 0 for _text, item in checks)
        row.update({"今回 10%／中央／90%": f"{gen[0]:.1f}／{gen[1]:.1f}／{gen[2]:.1f}", "今回SD": round(gen[3], 2), "今回SD比": round(ratio, 2),
                    "カラーを除いたSD比": round(ratio_judged, 2) if len(judged) < len(records) else math.nan,
                    "除いた球団数": len(records) - len(judged),
                    "合否": "OK" if ok else "NG", "判定": "、".join(text for text, _item in checks)})
        rows.append(row)
    table = pd.DataFrame(rows)

    class_rows = []
    for role, label in SPREAD_CLASS_ROWS:
        values = pd.Series([record["class_counts"][f"{role}|{label}"] for record in records], dtype=float)
        row = {"役割": role, "選手格": label}
        past = SPREAD_CLASS_HISTORY.get((role, label))
        if past:
            row.update({"改修前 平均": past[0], "改修前 SD": past[1], "改修前 最小〜最大": f"{past[2]}〜{past[3]}"})
        row.update({"今回 平均": round(values.mean(), 2), "今回 SD": round(values.std(), 2), "今回 最小〜最大": f"{int(values.min())}〜{int(values.max())}"})
        class_rows.append(row)
    return table, pd.DataFrame(class_rows), C


def spread_history_entry(records: list[dict[str, Any]]) -> tuple[dict[str, tuple[float, ...]], dict[tuple[str, str], tuple[float, ...]]]:
    """SPREAD_HISTORY・SPREAD_CLASS_HISTORY に貼る値（段階ごとの記録用）。"""
    values = {label: tuple(round(v, 2) for v in spread_summary([r["values"][label] for r in records])) for label, *_rest in SPREAD_ITEMS}
    classes = {}
    for role, label in SPREAD_CLASS_ROWS:
        series = pd.Series([r["class_counts"][f"{role}|{label}"] for r in records], dtype=float)
        classes[(role, label)] = (round(series.mean(), 2), round(series.std(), 2), int(series.min()), int(series.max()))
    return values, classes


# ---------------------------------------------------------------------------
# 実在データ
# ---------------------------------------------------------------------------
def load_real_players() -> pd.DataFrame:
    """2026年版実在12球団の選手を、generator/rating.py で査定する（変換は generator/real_data.py）。"""
    players = pd.read_csv(REAL_PLAYERS_DIR / "players.csv")
    specials = pd.read_csv(REAL_PLAYERS_DIR / "special_abilities.csv")
    breaking = pd.read_csv(REAL_PLAYERS_DIR / "breaking_balls.csv")
    rows = []
    for row in attach_real_details(players, specials, breaking):
        rows.append({"team": row["team"], "role": row["role"], "rating": player_rating(real_player_to_rating_dict(row))})
    return pd.DataFrame(rows)


def real_team_metrics() -> pd.DataFrame:
    real = load_real_players()
    records = []
    for team, group in real.groupby("team"):
        ratings = group["rating"].tolist()
        records.append({
            "team": team,
            "metric_top28": team_lib._top_mean(ratings, team_lib.TOP_TEAM_COUNT),
            "metric_all": float(statistics.fmean(ratings)),
            "metric_pitcher_top": team_lib._top_mean(group.loc[group.role == "投手", "rating"].tolist(), team_lib.TOP_PITCHER_COUNT),
            "metric_fielder_top": team_lib._top_mean(group.loc[group.role != "投手", "rating"].tolist(), team_lib.TOP_FIELDER_COUNT),
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------
def describe(values: list[float]) -> dict[str, float]:
    series = pd.Series(values, dtype=float).dropna()
    if series.empty:
        return {key: math.nan for key in ("平均", "最小", "10%", "中央", "90%", "最大")}
    return {
        "平均": round(float(series.mean()), 2), "最小": round(float(series.min()), 2), "10%": round(float(series.quantile(0.1)), 2),
        "中央": round(float(series.median()), 2), "90%": round(float(series.quantile(0.9)), 2), "最大": round(float(series.max()), 2),
    }


# 年齢帯の判定から除くチームカラー（年齢構成を動かすカラーなので、実在の範囲から少しはみ出してよい。背番号補正_改修指示.md §6）
AGE_COLORS = {"若手育成", "ベテラン重視"}


def composition_compare(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, Checks]:
    age_columns = {band for band, _low, _high in team_lib.AGE_BANDS}
    age_records = [r for r in records if r["color"] not in AGE_COLORS and r["sub_color"] not in AGE_COLORS]
    rows = []
    C = Checks(SCRIPT)
    for column, label in team_lib.COMPOSITION_ITEMS:
        real = describe(team_lib.real_composition_values(column))
        targets = age_records if column in age_columns else records
        gen = describe([record[f"comp_{column}"] for record in targets])
        ok = gen["10%"] >= real["最小"] and gen["90%"] <= real["最大"]
        note = f"若手育成・ベテラン重視を除く{len(targets)}球団" if column in age_columns else ""
        rows.append({"項目": label, "列": column, **{f"実在{k}": v for k, v in real.items()}, **{f"生成{k}": v for k, v in gen.items()}, "合否": "OK" if ok else "NG", "備考": note})
        # 実在の最小〜最大（60チームの両端）なので、実在側の誤差は見ない
        C.add(f"{SCRIPT}.composition.{column}.p10", "実在", f"構成：{label}の10%が実在の最小以上", gen["10%"], real["最小"], None, section="構成", real=f"実在の最小 {real['最小']}")
        C.add(f"{SCRIPT}.composition.{column}.p90", "実在", f"構成：{label}の90%が実在の最大以下", gen["90%"], None, real["最大"], section="構成", real=f"実在の最大 {real['最大']}")
    return pd.DataFrame(rows), C


METRICS = (("metric_top28", "上位28人平均"), ("metric_all", "全員平均"), ("metric_pitcher_top", f"投手上位{team_lib.TOP_PITCHER_COUNT}人平均"), ("metric_fielder_top", f"野手上位{team_lib.TOP_FIELDER_COUNT}人平均"))


def strength_tables(records: list[dict[str, Any]], real: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], Checks]:
    frame = pd.DataFrame(records)
    rows = []
    for column, label in METRICS:
        real_values = real[column]
        rows.append({"指標": label, "区分": "実在12球団", "球団数": len(real_values), **describe(real_values.tolist()), "標準偏差": round(real_values.std(), 2)})
        for level in (*team_lib.STRENGTH_LABELS, "全体"):
            values = frame[column] if level == "全体" else frame.loc[frame.strength == level, column]
            rows.append({"指標": label, "区分": level, "球団数": len(values), **describe(values.tolist()), "標準偏差": round(values.std(), 2)})
    table = pd.DataFrame(rows)

    checks = []
    C = Checks(SCRIPT)
    sec = "戦力レベル"
    for column, label in METRICS:
        key = f"{SCRIPT}.strength.{column.removeprefix('metric_')}"
        by_level = {level: frame.loc[frame.strength == level, column] for level in team_lib.STRENGTH_LABELS}
        strong, mid, weak = by_level["強豪"], by_level["中位"], by_level["弱小"]
        real_mean, real_min, real_max = real[column].mean(), real[column].min(), real[column].max()
        gap = strong.mean() - mid.mean()
        e_q = STRENGTH_E_MID_QUANTILE.get(column, 0.75)
        overall = frame[column]
        p10, p90 = overall.quantile(0.1), overall.quantile(0.9)
        checks += [
            {"指標": label, "確認": "(a) 強豪 > 中位 > 弱小", "値": f"{strong.mean():.1f} > {mid.mean():.1f} > {weak.mean():.1f}", "合否": strong.mean() > mid.mean() > weak.mean()},
            {"指標": label, "確認": "(b) 中位の平均が実在平均±3%", "値": f"中位 {mid.mean():.1f} / 実在 {real_mean:.1f}（{(mid.mean() / real_mean - 1) * 100:+.1f}%）", "合否": abs(mid.mean() / real_mean - 1) <= 0.03},
            {"指標": label, "確認": "(c) 全体の10〜90%が実在の最小〜最大から大きく外れない（±3%）", "値": f"生成 {p10:.1f}〜{p90:.1f} / 実在 {real_min:.1f}〜{real_max:.1f}", "合否": p10 >= real_min * 0.97 and p90 <= real_max * 1.03},
            {"指標": label, "確認": "(d) レベル内の標準偏差 ≥ 強豪と中位の差の30%", "値": f"強豪 {strong.std():.1f} / 中位 {mid.std():.1f} / 弱小 {weak.std():.1f}（差 {gap:.1f} の30% = {gap * 0.3:.1f}）", "合否": min(strong.std(), mid.std(), weak.std()) >= gap * 0.3},
            {"指標": label, "確認": f"(e) 強豪の下位10% < 中位の上位10%、強豪の中央値 > 中位の{e_q * 100:.0f}%点", "値": f"強豪10% {strong.quantile(0.1):.1f} < 中位90% {mid.quantile(0.9):.1f}、強豪中央 {strong.median():.1f} > 中位{e_q * 100:.0f}% {mid.quantile(e_q):.1f}", "合否": strong.quantile(0.1) < mid.quantile(0.9) and strong.median() > mid.quantile(e_q)},
        ]
        # (a)(d)(e)(f) は設計、(b)(c) は実在（12球団の平均・最小・最大に合わせる）
        C.add(f"{key}.a", "設計", f"{label} (a) 強豪 > 中位 > 弱小（隣のレベルとの差の最小が正）", min(strong.mean() - mid.mean(), mid.mean() - weak.mean()), 1e-9, None,
              section=sec, shown=f"{strong.mean():.1f} > {mid.mean():.1f} > {weak.mean():.1f}", target="差が正")
        C.add(f"{key}.b", "実在", f"{label} (b) 中位の平均が実在平均±3%", mid.mean() / real_mean - 1, -0.03, 0.03, section=sec,
              shown=f"{(mid.mean() / real_mean - 1) * 100:+.1f}%", real=f"実在平均 {real_mean:.1f}")
        C.add(f"{key}.c_p10", "実在", f"{label} (c) 全体の10%が実在の最小の97%以上", p10 / real_min, 0.97, None, section=sec, shown=f"{p10:.1f}", real=f"実在の最小 {real_min:.1f}")
        C.add(f"{key}.c_p90", "実在", f"{label} (c) 全体の90%が実在の最大の103%以下", p90 / real_max, None, 1.03, section=sec, shown=f"{p90:.1f}", real=f"実在の最大 {real_max:.1f}")
        C.add(f"{key}.d", "設計", f"{label} (d) レベル内の標準偏差 ≥ 強豪と中位の差の30%（余り）", min(strong.std(), mid.std(), weak.std()) - gap * 0.3, 0.0, None, section=sec,
              shown=f"強豪 {strong.std():.1f} / 中位 {mid.std():.1f} / 弱小 {weak.std():.1f}（差の30% = {gap * 0.3:.1f}）", target="0以上")
        C.add(f"{key}.e_tail", "設計", f"{label} (e) 強豪の下位10% < 中位の上位10%（差）", strong.quantile(0.1) - mid.quantile(0.9), None, 0.0, section=sec,
              shown=f"強豪10% {strong.quantile(0.1):.1f} / 中位90% {mid.quantile(0.9):.1f}", target="0以下")
        C.add(f"{key}.e_median", "設計", f"{label} (e) 強豪の中央値 > 中位の{e_q * 100:.0f}%点（差）", strong.median() - mid.quantile(e_q), 1e-9, None, section=sec,
              shown=f"強豪中央 {strong.median():.1f} / 中位{e_q * 100:.0f}% {mid.quantile(e_q):.1f}", target="差が正")
    corr = frame["metric_pitcher_top"].corr(frame["metric_fielder_top"])
    z_p = (frame["metric_pitcher_top"] - frame["metric_pitcher_top"].mean()) / frame["metric_pitcher_top"].std()
    z_f = (frame["metric_fielder_top"] - frame["metric_fielder_top"].mean()) / frame["metric_fielder_top"].std()
    gap = z_p - z_f
    checks.append({
        "指標": "投手上位・野手上位", "確認": f"(f) 投手指標と野手指標の相関 {CORRELATION_RANGE[0]}〜{CORRELATION_RANGE[1]}",
        "値": f"相関 {corr:.2f}（投高打低 {int((gap > 1).sum())}球団・打高投低 {int((gap < -1).sum())}球団・偏りなし {int((gap.abs() <= 1).sum())}球団、zの差±1で区分）",
        "合否": CORRELATION_RANGE[0] <= corr <= CORRELATION_RANGE[1],
    })
    C.add(f"{SCRIPT}.strength.corr_pitcher_fielder", "設計", f"投手指標と野手指標の相関 {CORRELATION_RANGE[0]}〜{CORRELATION_RANGE[1]}", corr, *CORRELATION_RANGE, section=sec, shown=f"{corr:.2f}")
    return table, checks, C


def color_tables(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]], Checks]:
    frame = pd.DataFrame(records)
    base = frame[frame.color == team_lib.NO_COLOR]
    base_means = {
        "pitcher_top": base["dom_pitcher_top"].mean(), "power": base["dom_power"].mean(),
        "contact_power": (base["dom_contact"] + base["dom_power"]).mean(), "speed": base["dom_speed"].mean(),
        "fielding": base["dom_fielding"].mean(), "arm": base["dom_arm"].mean(), "age": base["dom_age"].mean(),
    }
    rows, checks = [], []
    C = Checks(SCRIPT)
    for color, _weight in team_lib.COLOR_WEIGHTS:
        sub = frame[frame.color == color]
        if sub.empty:
            continue
        diffs = {
            "pitcher_top_pct": (sub["dom_pitcher_top"].mean() / base_means["pitcher_top"] - 1) * 100,
            "power": sub["dom_power"].mean() - base_means["power"],
            "contact_power": (sub["dom_contact"] + sub["dom_power"]).mean() - base_means["contact_power"],
            "speed": sub["dom_speed"].mean() - base_means["speed"],
            "fielding": sub["dom_fielding"].mean() - base_means["fielding"],
            "arm": sub["dom_arm"].mean() - base_means["arm"],
            "age": sub["dom_age"].mean() - base_means["age"],
        }
        rows.append({"カラー": color, "球団数": len(sub), **{key: round(value, 2) for key, value in diffs.items()}})
        if color in COLOR_CHECKS:
            results = [(label, diffs[key], low, high, low <= diffs[key] <= high) for key, low, high, label in COLOR_CHECKS[color]]
            ok = any(r[-1] for r in results) if color in COLOR_ANY_OF else all(r[-1] for r in results)
            text = "、".join(f"{label} {value:+.2f}（目安 {low:+g}〜{high:+g}）" for label, value, low, high, _ok in results)
            checks.append({"カラー": color, "結果": text, "合否": ok})
            # チームカラーの目安は設計。「どちらか」のカラーは、範囲の外へのはみ出しの最小を値にして 0 以下を合格にする
            outside = [(0.0 if low <= v <= high else (low - v if v < low else v - high)) for _label, v, low, high, _ok in results]
            if color in COLOR_ANY_OF:
                C.add(f"{SCRIPT}.color.{color}.any", "設計", f"{color}：{'、'.join(r[0] for r in results)}のどちらかが目安内（はみ出しの最小）", min(outside), None, 0.0,
                      section="チームカラー", shown=text, target="0（目安内）")
            else:
                for (label, v, low, high, _ok), (key, *_rest), gap in zip(results, COLOR_CHECKS[color], outside):
                    C.add(f"{SCRIPT}.color.{color}.{key}", "設計", f"{color}：{label}が目安内", v, low, high, section="チームカラー", shown=f"{v:+.2f}", target=f"{low:+g}〜{high:+g}")
    table = pd.DataFrame(rows).rename(columns={
        "pitcher_top_pct": f"投手上位{team_lib.TOP_PITCHER_COUNT}人査定(%)", "power": "パワー", "contact_power": "ミート+パワー",
        "speed": "走力", "fielding": "守備力", "arm": "肩力", "age": "平均年齢",
    })
    return table, checks, C


def color_intensity_table(records: list[dict[str, Any]]) -> pd.DataFrame:
    """通常抽選の球団で、効き具合 t の低い半分と高い半分の効果を比べる（サブカラーなしの球団のみ）。"""
    frame = pd.DataFrame(records)
    frame = frame[frame.sub_color == ""]
    base = frame[frame.color == team_lib.NO_COLOR]
    keys = {"投手王国": ("dom_pitcher_top", True), "強力打線": ("dom_power", False), "機動力": ("dom_speed", False), "守備重視": ("dom_fielding", False), "若手育成": ("dom_age", False), "ベテラン重視": ("dom_age", False)}
    rows = []
    for color, (column, pct) in keys.items():
        sub = frame[frame.color == color]
        for label, part in (("t<1.0", sub[sub.color_intensity < 1.0]), ("t≥1.0", sub[sub.color_intensity >= 1.0])):
            if part.empty:
                continue
            diff = part[column].mean() / base[column].mean() * 100 - 100 if pct else part[column].mean() - base[column].mean()
            rows.append({"カラー": color, "効き具合": label, "球団数": len(part), "t平均": round(part.color_intensity.mean(), 2), "指標": column, "特色なしとの差": round(diff, 2)})
    return pd.DataFrame(rows)


def uniform_tables(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    stats = team_lib.load_uniform_number_stats()
    teams = len(records)
    counts: dict[str, Counter] = defaultdict(Counter)
    band_rows: dict[str, list[tuple[float, int]]] = defaultdict(list)
    empty_low, high_used = [], []
    low_numbers = {n for n in team_lib.UNIFORM_NUMBERS if n == "00" or int(n) <= 69}
    for record in records:
        used = set()
        for row in record["uniform_rows"]:
            counts[row["number"]][row["group"]] += 1
            counts[row["number"]]["foreign"] += int(row["foreign"])
            counts[row["number"]]["teams"] += 1
            band_rows[team_lib.uniform_number_band(row["number"])].append((row["percentile"], row["age"]))
            used.add(row["number"])
        empty_low.append(len(low_numbers - used))
        high_used.append(sum(1 for n in used if n != "00" and 70 <= int(n) <= 98))
    rows = []
    for number in team_lib.UNIFORM_NUMBERS:
        real = stats.get(number, {})
        real_total = sum(real.get(k, 0) for k in ("pitcher", "catcher", "infielder", "outfielder"))
        gen = counts[number]
        gen_total = sum(gen[k] for k in ("pitcher", "catcher", "infielder", "outfielder"))
        ratio = lambda part, total: round(part / total, 3) if total else math.nan  # noqa: E731
        rows.append({
            "番号": number, "実在使用率": real.get("use_rate", 0.0), "生成使用率": round(gen["teams"] / teams, 3),
            "実在投手率": ratio(real.get("pitcher", 0), real_total), "生成投手率": ratio(gen["pitcher"], gen_total),
            "実在捕手率": ratio(real.get("catcher", 0), real_total), "生成捕手率": ratio(gen["catcher"], gen_total),
            "実在内野率": ratio(real.get("infielder", 0), real_total), "生成内野率": ratio(gen["infielder"], gen_total),
            "実在外野率": ratio(real.get("outfielder", 0), real_total), "生成外野率": ratio(gen["outfielder"], gen_total),
            "実在外国人率": ratio(real.get("foreign", 0), real_total), "生成外国人率": ratio(gen["foreign"], gen_total),
        })
    usage = pd.DataFrame(rows)
    bands = pd.DataFrame([
        {"番号帯": band, "人数": len(band_rows[band]),
         "査定百分位の平均": round(statistics.fmean(p for p, _a in band_rows[band]), 3) if band_rows[band] else math.nan,
         "年齢の平均": round(statistics.fmean(a for _p, a in band_rows[band]), 2) if band_rows[band] else math.nan,
         "実在の平均年齢（2026）": round(statistics.fmean(stats[n]["avg_age_2026"] for n in team_lib.UNIFORM_NUMBERS if team_lib.uniform_number_band(n) == band and stats.get(n, {}).get("avg_age_2026")), 2) if any(stats.get(n, {}).get("avg_age_2026") for n in team_lib.UNIFORM_NUMBERS if team_lib.uniform_number_band(n) == band) else math.nan}
        for band in team_lib.UNIFORM_BANDS
    ])
    gen_p_11_21 = sum(counts[str(n)]["pitcher"] for n in range(11, 22)) / max(1, sum(sum(counts[str(n)][k] for k in ("pitcher", "catcher", "infielder", "outfielder")) for n in range(11, 22)))
    catcher_rate = {n: usage.loc[usage["番号"] == n, "生成捕手率"].iloc[0] for n in ("2", "27")}
    summary = {
        "empty_low": describe(empty_low),
        "high_used": describe(high_used),
        "rate_99": round(counts["99"]["teams"] / teams, 3),
        "pitcher_rate_11_21": round(gen_p_11_21, 3),
        "catcher_rate": catcher_rate,
    }
    return usage, bands, summary


def uniform_checks(summary: dict[str, Any]) -> Checks:
    """背番号の確認項目のうち、uniform_tables の集計から決まるもの。"""
    C = Checks(SCRIPT)
    sec = "背番号"
    key = f"{SCRIPT}.uniform"
    empty, high_used = summary["empty_low"], summary["high_used"]
    C.add(f"{key}.empty_low.p10", "実在", "0〜69と00の空き番号の10%が3以上", empty["10%"], 3, None, section=sec, real="実在 3〜13（平均7.7）")
    C.add(f"{key}.empty_low.p90", "実在", "0〜69と00の空き番号の90%が13以下", empty["90%"], None, 13, section=sec, real="実在 3〜13（平均7.7）")
    C.add(f"{key}.high_used.mean", "実在", "70〜98の使用数の平均が5.2±2", high_used["平均"], 3.2, 7.2, section=sec, real="実在 平均5.2")
    C.add(f"{key}.rate_99", "実在", "99の使用率が80%±15%", summary["rate_99"], 0.65, 0.95, section=sec, shown=f"{summary['rate_99'] * 100:.1f}%", real="実在 80%")
    C.add(f"{key}.pitcher_rate_11_21", "設計", "11〜21番の投手率90%以上", summary["pitcher_rate_11_21"], 0.90, None, section=sec, shown=f"{summary['pitcher_rate_11_21'] * 100:.1f}%")
    for number, rate in summary["catcher_rate"].items():
        C.add(f"{key}.catcher_rate.{number}", "設計", f"{number}番の捕手率30%以上", rate, 0.30, None, section=sec, shown=f"{rate * 100:.1f}%")
    return C


# 背番号補正_改修指示.md §1・§3 の実在の値と目標（実在は日本人・外国人を分けた集計、年齢は2026年版の日本人）
UNIFORM_FOREIGN_RATE_TARGETS = {
    # 番号: (実在の外国人の割合, 下限, 上限)。下限・上限が None の番号は表に出すだけ
    "99": (0.48, 0.38, 0.58), "42": (0.76, 0.65, 0.85), "91": (0.38, 0.20, 0.50), "95": (0.31, 0.20, 0.45),
    "98": (0.35, 0.20, 0.50), "96": (0.20, 0.10, 0.30), "97": (0.10, None, None),
    "1": (0.0, None, 0.03), "17": (0.0, None, 0.03), "18": (0.0, None, 0.03), "19": (0.0, None, 0.03),
    "0": (0.06, None, None), "00": (0.11, None, None),
}
UNIFORM_FOREIGN_RANGE_REAL = {"0-10": 0.111, "11-21": 0.056, "22-30": 0.127, "31-69": 0.515, "70-89": 0.029, "90-99": 0.162}
UNIFORM_FOREIGN_RANGE_TARGETS = {"11-21": (None, 0.08), "90-99": (0.12, 0.20)}
UNIFORM_AGE_TARGETS = {
    # (役割, 番号の範囲): (実在の平均年齢, 実在の23歳以下の割合, 実在の31歳以上の割合)。目標は平均年齢±1.0
    ("野手", "0-10"): (29.3, 0.11, 0.41), ("野手", "22-30"): (29.5, None, None), ("野手", "31-69"): (25.6, 0.31, 0.11),
    ("投手", "11-21"): (28.5, 0.00, 0.32), ("投手", "22-30"): (27.7, None, None), ("投手", "31-69"): (26.1, 0.28, 0.15),
}
UNIFORM_HIGH_PERCENTILE_REAL = 0.365

def _range_text(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "今のまま（表示のみ）"
    if low is None:
        return f"{high}以下"
    return f"{low}〜{high}"


def uniform_detail_tables(records: list[dict[str, Any]]) -> tuple[dict[str, pd.DataFrame], Checks]:
    """背番号補正_改修指示.md §3 の確認項目（外国人の番号、年齢、70〜98番、使用率の相関）。"""
    stats = team_lib.load_uniform_number_stats()
    by_number: dict[str, Counter] = defaultdict(Counter)
    teams_used: Counter = Counter()
    foreign_by_band: Counter = Counter()
    ages: dict[tuple[str, str], list[int]] = defaultdict(list)
    high_percentiles: list[float] = []
    for record in records:
        used = set()
        for row in record["uniform_rows"]:
            number = row["number"]
            used.add(number)
            by_number[number]["all"] += 1
            by_number[number]["foreign"] += int(row["foreign"])
            band = team_lib.uniform_number_band(number)
            if row["foreign"]:
                foreign_by_band[band] += 1
            else:
                ages[(row["role"], band)].append(row["age"])
            if number != "00" and 70 <= int(number) <= 98:
                high_percentiles.append(row["percentile"])
        teams_used.update(used)
    C = Checks(SCRIPT)
    sec = "背番号（外国人・年齢・70〜98番）"
    key = f"{SCRIPT}.uniform"

    rows = []
    for number, (real, low, high) in UNIFORM_FOREIGN_RATE_TARGETS.items():
        rate = by_number[number]["foreign"] / by_number[number]["all"] if by_number[number]["all"] else 0.0
        ok = (low is None or rate >= low) and (high is None or rate <= high)
        target = _range_text(low, high)
        rows.append({"番号": number, "実在": real, "生成": round(rate, 3), "目標": target, "合否": "OK" if ok else "NG"})
        if low is not None or high is not None:
            C.add(f"{key}.foreign_rate.{number}", "実在", f"{number}番の外国人の割合 {target}", rate, low, high, section=sec, shown=f"{rate:.3f}", target=target, real=f"実在 {real}")
    foreign_rate = pd.DataFrame(rows)

    total_foreign = sum(foreign_by_band.values()) or 1
    rows = []
    for band in team_lib.UNIFORM_BANDS:
        share = foreign_by_band[band] / total_foreign
        low, high = UNIFORM_FOREIGN_RANGE_TARGETS.get(band, (None, None))
        ok = (low is None or share >= low) and (high is None or share <= high)
        target = _range_text(low, high) if band in UNIFORM_FOREIGN_RANGE_TARGETS else ""
        rows.append({"番号の範囲": band, "実在": UNIFORM_FOREIGN_RANGE_REAL[band], "生成": round(share, 3), "目標": target, "合否": "OK" if ok else "NG"})
        if band in UNIFORM_FOREIGN_RANGE_TARGETS:
            C.add(f"{key}.foreign_range.{band}", "実在", f"外国人のうち {band} 番の割合 {target}", share, low, high, section=sec, shown=f"{share:.3f}", target=target,
                  real=f"実在 {UNIFORM_FOREIGN_RANGE_REAL[band]}")
    foreign_range = pd.DataFrame(rows)

    rows = []
    for (role, band), (real_mean, real_u23, real_o31) in UNIFORM_AGE_TARGETS.items():
        values = ages[(role, band)]
        mean = statistics.fmean(values)
        u23 = sum(a <= 23 for a in values) / len(values)
        o31 = sum(a >= 31 for a in values) / len(values)
        ok = abs(mean - real_mean) <= 1.0
        rows.append({"区分": role, "番号の範囲": band, "人数": len(values), "平均年齢 実在": real_mean, "平均年齢 生成": round(mean, 2),
                     "23歳以下 実在": real_u23, "23歳以下 生成": round(u23, 3), "31歳以上 実在": real_o31, "31歳以上 生成": round(o31, 3),
                     "合否": "OK" if ok else "NG"})
        role_key = {"野手": "fielder", "投手": "pitcher"}[role]
        C.add(f"{key}.age.{role_key}.{band}.mean", "実在", f"日本人{role}の{band}番の平均年齢 {real_mean - 1:.1f}〜{real_mean + 1:.1f}", mean, real_mean - 1.0, real_mean + 1.0,
              section=sec, shown=f"{mean:.2f}", real=f"実在 {real_mean}")
        if (role, band) == ("野手", "31-69"):
            C.add(f"{key}.age.fielder.31-69.over31", "実在", "日本人野手の31〜69番で31歳以上が16%以下", o31, None, 0.16, section=sec, shown=f"{o31 * 100:.1f}%", real=f"実在 {real_o31}")
        if (role, band) == ("野手", "0-10"):
            C.add(f"{key}.age.fielder.0-10.over31", "実在", "日本人野手の0〜10番で31歳以上が33%以上", o31, 0.33, None, section=sec, shown=f"{o31 * 100:.1f}%", real=f"実在 {real_o31}")
    age_table = pd.DataFrame(rows)

    high_mean = statistics.fmean(high_percentiles) if high_percentiles else math.nan
    high_count = len(high_percentiles) / len(records)
    C.add(f"{key}.high_percentile", "実在", "70〜98番の査定の百分位の平均 0.30〜0.45", high_mean, 0.30, 0.45, section=sec, shown=f"{high_mean:.3f}", real=f"実在 {UNIFORM_HIGH_PERCENTILE_REAL}")
    C.add(f"{key}.high_count", "実在", "70〜98番の使用数 1球団あたり4.2〜6.2個", high_count, 4.2, 6.2, section=sec, shown=f"{high_count:.2f}", real="実在 5.2")
    real_rates = [stats[n]["use_rate"] for n in team_lib.UNIFORM_NUMBERS]
    gen_rates = [teams_used[n] / len(records) for n in team_lib.UNIFORM_NUMBERS]
    corr = float(pd.Series(real_rates).corr(pd.Series(gen_rates)))
    # 番号ごとの使用率と実在の相関の下限。PR #102 第2版の背番号の重みでは0.9857、選手の査定・年齢が変わると少し動くため固定の下限にした（data/config/check_baselines.json）
    C.fixed(f"{key}.use_rate_corr", "番号ごとの使用率と実在の相関が下限以上", corr, 0.0, section=sec, shown=f"{corr:.4f}")
    high = pd.DataFrame([
        {"項目": "70〜98番の査定の百分位の平均", "実在": UNIFORM_HIGH_PERCENTILE_REAL, "生成": round(high_mean, 3)},
        {"項目": "70〜98番の使用数（1球団あたり）", "実在": 5.2, "生成": round(high_count, 2)},
        {"項目": "番号ごとの使用率と実在の相関", "実在": "固定の下限（基準値ファイル）", "生成": round(corr, 4)},
    ])
    return {"foreign_rate": foreign_rate, "foreign_range": foreign_range, "age": age_table, "high": high}, C


def spread_section(records: list[dict[str, Any]], output: Path, real_values: dict[str, list[float]]) -> tuple[list[str], Checks]:
    table, class_table, C = spread_tables(records, real_values)
    table.to_csv(output / "spread_metrics.csv", index=False, encoding="utf-8-sig")
    class_table.to_csv(output / "spread_class_counts.csv", index=False, encoding="utf-8-sig")
    history, class_history = spread_history_entry(records)
    (output / "spread_history.txt").write_text(f"{history!r}\n\n{class_history!r}\n", encoding="utf-8")
    frame = pd.DataFrame(records)
    relaxed: Counter = Counter()
    for record in records:
        relaxed.update(record["relaxed"])
    lines = [
        f"## 球団ごとの散らばり（球団生成 seed {SPREAD_BASE_SEED}〜{SPREAD_BASE_SEED + len(records) - 1}、実在は{SPREAD_SEASONS[0]}〜{SPREAD_SEASONS[-1]}年版の36チーム・外国人を含む）", "",
        f"- 1球団あたりの生成時間: 平均 {frame['elapsed'].mean():.2f}秒 / 中央 {frame['elapsed'].median():.2f}秒 / 最大 {frame['elapsed'].max():.2f}秒（並列実行中の計測）",
        *[f"- {label}をゆるめた人数: 合計 {count}人" for label, count in relaxed.items()],
        "",
        "SD比 = 生成の球団ごとの値の標準偏差 ÷ 実在の標準偏差。査定の6指標は SD比 0.85〜1.20 と 10%・90% が実在±(実在SD×0.5)、能力は SD比 1.25 以下（その能力を動かすチームカラーの球団を除いて判定。機動力→走力、守備重視→守備力・肩力、強力打線→ミート・パワー、投手王国→投手の球速・コントロール・スタミナ）。", "",
        to_markdown(table), "",
        "### 選手格の人数（国内選手、1球団あたり）", "",
        to_markdown(class_table), "",
    ]
    return lines, C


def svg_scatter(frame: pd.DataFrame, x: str, y: str, title: str, width: int = 520, height: int = 360) -> str:
    colors = {"強豪": "#d9480f", "中位": "#1971c2", "弱小": "#5c940d"}
    pad = 46
    xs, ys = frame[x].astype(float), frame[y].astype(float)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    sx = lambda v: pad + (v - x0) / ((x1 - x0) or 1) * (width - pad * 1.5)  # noqa: E731
    sy = lambda v: height - pad - (v - y0) / ((y1 - y0) or 1) * (height - pad * 1.5)  # noqa: E731
    dots = "".join(
        f'<circle cx="{sx(a):.1f}" cy="{sy(b):.1f}" r="2.6" fill="{colors.get(level, "#868e96")}" fill-opacity="0.65"/>'
        for a, b, level in zip(xs, ys, frame["strength"])
    )
    axes = (
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad / 2}" y2="{height - pad}" stroke="#adb5bd"/>'
        f'<line x1="{pad}" y1="{pad / 2}" x2="{pad}" y2="{height - pad}" stroke="#adb5bd"/>'
        f'<text x="{width / 2}" y="{height - 10}" text-anchor="middle" font-size="12">{x}（{x0:.2f}〜{x1:.2f}）</text>'
        f'<text x="12" y="{height / 2}" font-size="12" transform="rotate(-90 12 {height / 2})" text-anchor="middle">{y}（{y0:.0f}〜{y1:.0f}）</text>'
        f'<text x="{width / 2}" y="16" text-anchor="middle" font-size="13" font-weight="700">{title}</text>'
    )
    return f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">{axes}{dots}</svg>'


def to_markdown(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(map(str, columns)) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join("" if (isinstance(v, float) and math.isnan(v)) else str(v) for v in row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 判定（誤差・合否）
# ---------------------------------------------------------------------------
def real_metrics_frame() -> pd.DataFrame:
    return real_team_metrics()


def slim(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """誤差の計算で使い回す球団の記録（年齢帯の判定用の行は check_age_profile.py で扱うので除く）。"""
    return [{key: value for key, value in record.items() if key != "age_rows"} for record in records]


def build(data: dict[str, list[dict[str, Any]]], real: dict[str, Any]) -> tuple[Checks, dict[str, Any]]:
    """球団生成の記録から、判定（Checks）と、レポートに載せる表（tables）を作る。"""
    C = Checks(SCRIPT)
    tables: dict[str, Any] = {}
    main_records = data["main"]
    frame = pd.DataFrame(main_records)
    # --- 構成
    tables["comp"], comp_checks = composition_compare(main_records)
    C.extend(comp_checks)
    design = f"{SCRIPT}.design"
    sec = "構成・名前・背番号の基本条件"
    C.add(f"{design}.total_max70", "設計", "総数が70を超えない（超えた球団数）", int((frame["comp_total"] > 70).sum()), None, 0, section=sec, shown=f"{int((frame['comp_total'] > 70).sum())}球団")
    bad = int(((frame["comp_pos_C"] < 5) | (frame["comp_pos_SS"] < 2)).sum())
    C.add(f"{design}.catcher_ss", "設計", "捕手5人以上・遊撃手2人以上（満たさない球団数）", bad, None, 0, section=sec, shown=f"{bad}球団")
    bad = int((frame["comp_closer_aptitude"] < 2).sum())
    C.add(f"{design}.closer_aptitude", "設計", "抑え適性ありが2人以上（満たさない球団数）", bad, None, 0, section=sec, shown=f"{bad}球団")
    bad = int(frame["name_duplicates"].sum())
    C.add(f"{design}.name_duplicates", "設計", "名前の重複が0件", bad, None, 0, section=sec, shown=f"{bad}件")
    bad = int(frame["number_duplicates"].sum() + frame["retired_used"].sum() + frame["number_missing"].sum())
    C.add(f"{design}.number_conflicts", "設計", "背番号の重複が0件・欠番を使っていない・全員に背番号", bad, None, 0, section=sec, shown=f"{bad}件")
    bad = int((~frame.loc[frame.relaxed_total == 0, "targets_match"]).sum())
    C.add(f"{design}.targets_match", "設計", "目標の人数と実際の人数が一致（条件をゆるめた球団を除く。外れた球団数）", bad, None, 0, section=sec, shown=f"{bad}球団")
    # --- 背番号
    tables["usage"], tables["bands"], uni = uniform_tables(main_records)
    C.extend(uniform_checks(uni))
    tables["uni"] = uni
    tables["uniform_detail"], detail_checks = uniform_detail_tables(main_records)
    C.extend(detail_checks)
    # --- 戦力
    if data.get("strength"):
        tables["strength"], tables["strength_checks"], strength = strength_tables(data["strength"], real["metrics"])
        C.extend(strength)
    # --- カラー
    if data.get("color"):
        tables["color"], tables["color_checks"], colors = color_tables(data["color"])
        C.extend(colors)
    # --- 散らばり
    if data.get("spread"):
        spread_table, class_table, spread = spread_tables(data["spread"], real["spread_values"])
        tables["spread"], tables["spread_class"] = spread_table, class_table
        C.extend(spread)
    return C, tables


_REAL: dict[str, Any] = {}


def real_context() -> dict[str, Any]:
    """実在側のデータ（読み込みは1回）。"""
    if not _REAL:
        spread_frame = real_spread_frame()
        _REAL.update({"spread_frame": spread_frame, "spread_values": {label: spread_frame[label].dropna().tolist() for label in spread_frame.columns}, "metrics": real_metrics_frame()})
    return _REAL


def evaluate_data(data: dict[str, list[dict[str, Any]]]) -> Checks:
    return build(data, real_context())[0]


def resample_data(data: dict[str, list[dict[str, Any]]], rng: Any) -> dict[str, list[dict[str, Any]]]:
    """球団を単位に、球団の記録の集まりごとに引き直す。"""
    return {key: checklib.resample_list(records, rng) if records else records for key, records in data.items()}


def real_se_map(data: dict[str, list[dict[str, Any]]], boot: int) -> dict[str, float]:
    """実在側の誤差。実在の36チーム（散らばり）・12チーム（戦力）を球団単位で引き直し、背番号の実在の割合・年齢は件数から求める。"""
    if not boot:
        return {}
    real = real_context()
    out: dict[str, float] = {}
    if data.get("spread"):
        spread_records = data["spread"]

        def spread_checks(frame: pd.DataFrame) -> Checks:
            values = {label: frame[label].dropna().tolist() for label in frame.columns}
            return spread_tables(spread_records, values)[2]

        out.update(checklib.bootstrap_se(spread_checks, real["spread_frame"], lambda f, rng: checklib.resample_frame(f, rng), n=boot, offset=True))
    if data.get("strength"):
        strength_records = data["strength"]
        out.update(checklib.bootstrap_se(lambda metrics: strength_tables(strength_records, metrics)[2], real["metrics"], lambda f, rng: checklib.resample_frame(f, rng), n=boot, offset=True))
    out.update(uniform_real_se())
    return out


def uniform_real_se() -> dict[str, float]:
    """背番号の実在側の誤差。割合は件数（二項分布）、年齢は選手のばらつき（標準偏差÷√人数）から求める。"""
    stats = team_lib.load_uniform_number_stats()
    out: dict[str, float] = {}
    key = f"{SCRIPT}.uniform"
    for number, (real, low, high) in UNIFORM_FOREIGN_RATE_TARGETS.items():
        counts = stats.get(number, {})
        n = sum(counts.get(k, 0) for k in ("pitcher", "catcher", "infielder", "outfielder"))
        if n and (low is not None or high is not None):
            out[f"{key}.foreign_rate.{number}"] = math.sqrt(real * (1 - real) / n)
    total_foreign = sum(stats.get(n, {}).get("foreign", 0) for n in team_lib.UNIFORM_NUMBERS)
    for band in UNIFORM_FOREIGN_RANGE_TARGETS:
        share = UNIFORM_FOREIGN_RANGE_REAL[band]
        if total_foreign:
            out[f"{key}.foreign_range.{band}"] = math.sqrt(share * (1 - share) / total_foreign)
    from generator import real_data

    players = real_data.load_real_players((real_data.AGE_SEASON,))
    if players is not None:
        players = players[~players["is_foreign"]].assign(band=lambda f: f["uniform_number"].map(team_lib.uniform_number_band))
        for (role, band), (_mean, _u23, _o31) in UNIFORM_AGE_TARGETS.items():
            part = players[(players["role"] == role) & (players["band"] == band)]["age"].dropna()
            role_key = {"野手": "fielder", "投手": "pitcher"}[role]
            if len(part) > 1:
                out[f"{key}.age.{role_key}.{band}.mean"] = float(part.std() / math.sqrt(len(part)))
    return out


def grade_data(data: dict[str, list[dict[str, Any]]], boot: int, workers: int, quick: bool = False) -> tuple[list[checklib.Check], dict[str, Any]]:
    slimmed = {key: slim(records) for key, records in data.items()}
    checks, tables = build(slimmed, real_context())
    se_gen = checklib.bootstrap_se(evaluate_data, slimmed, resample_data, n=boot, workers=workers) if boot else {}
    se_real = real_se_map(slimmed, boot)
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick), tables


def sort_key(check: checklib.Check) -> tuple[int, str]:
    order = {checklib.FAIL: 0, checklib.WARN: 1, checklib.ACCEPTED: 2, checklib.PASS: 3, checklib.INFO: 4}
    return order[check.status], check.id


def checks_section(graded: list[checklib.Check]) -> list[str]:
    """summary.md の「合否」の節。合格以外を先に、合格はまとめて数える。"""
    c = checklib.counts(graded)
    lines = ["## 合否", "", checklib.summary_line(graded), "",
             "種類: 実在＝実在に合わせる（範囲の外でも境界から誤差の2倍以内は要注意）／固定＝改修前から変わっていない／設計＝実在とは別の条件（範囲の内側なら合格）／参考＝合否なし。", ""]
    others = [check for check in sorted(graded, key=sort_key) if check.status not in (checklib.PASS, checklib.INFO)]
    if others:
        lines += checklib.markdown_rows(others) + [""]
    lines += [f"合格 {c[checklib.PASS]} 件は reports/checks/validate_team_mode.csv に一覧。", ""]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="球団生成モードの検証レポートを作ります。")
    parser.add_argument("--teams", type=int, default=500, help="構成・背番号の確認に使う球団数")
    parser.add_argument("--strength-teams", type=int, default=600, help="戦力レベルの確認に使う球団数")
    parser.add_argument("--color-teams", type=int, default=200, help="チームカラーの確認に使う、カラーごとの球団数（t=1.0固定）")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--skip-color", action="store_true")
    parser.add_argument("--skip-strength", action="store_true")
    parser.add_argument("--spread-teams", type=int, default=300, help="球団ごとの散らばりの確認に使う球団数（seed 1〜）")
    parser.add_argument("--skip-spread", action="store_true")
    parser.add_argument("--spread-only", action="store_true", help="球団ごとの散らばりの節だけを作る（spread_summary.md）")
    checklib.add_common_args(parser)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.disable(logging.WARNING)

    if args.spread_only:
        spread_records = run_spread_jobs(args.spread_teams, args.workers)
        spread_lines, _spread = spread_section(spread_records, args.output, real_context()["spread_values"])
        spread_checks = grade_spread_only(spread_records, args.boot, args.quick)
        lines = ["# 球団生成モード 検証レポート（球団ごとの散らばりのみ）", ""] + checks_section(spread_checks) + spread_lines
        (args.output / "spread_summary.md").write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        sys.exit(checklib.finish(SCRIPT + "_spread", spread_checks, args))

    main_records = run_jobs([(BASE_SEED + i, None) for i in range(args.teams)], args.workers, "構成・背番号")
    strength_records = []
    if not args.skip_strength:
        extra = max(0, args.strength_teams - args.teams)
        strength_records = main_records + run_jobs([(STRENGTH_BASE_SEED + i, None) for i in range(extra)], args.workers, "戦力")
    color_records = []
    if not args.skip_color:
        jobs = [(COLOR_BASE_SEED + i, {"color": color, "color_intensity": 1.0, "sub_color": ""}) for color, _w in team_lib.COLOR_WEIGHTS for i in range(args.color_teams)]
        color_records = run_jobs(jobs, args.workers, "カラー")
    spread_records = [] if args.skip_spread else run_spread_jobs(args.spread_teams, args.workers)

    data = {"main": main_records, "strength": strength_records, "color": color_records, "spread": spread_records}
    graded, tables = grade_data(data, args.boot, args.workers, args.quick)
    # 年齢帯別の特能・ランク（check_age_profile.py と同じ判定。日本人）。誤差は check_age_profile.py と同じ方法で求める
    age_frame = pd.DataFrame([row for record in main_records for row in record["age_rows"]])
    age_graded = check_age_profile.grade_frame(age_frame, args.boot, args.workers, args.quick)
    graded += age_graded

    frame = pd.DataFrame(slim(main_records))
    comp, usage, bands, uni, uniform_detail = tables["comp"], tables["usage"], tables["bands"], tables["uni"], tables["uniform_detail"]
    comp.to_csv(args.output / "composition_compare.csv", index=False, encoding="utf-8-sig")
    usage.to_csv(args.output / "uniform_number_usage.csv", index=False, encoding="utf-8-sig")
    bands.to_csv(args.output / "uniform_number_bands.csv", index=False, encoding="utf-8-sig")
    age_lines = check_age_profile.report(age_frame, age_graded)

    elapsed = frame["elapsed"]
    relaxed_cols = [c for c in frame.columns if c.startswith("relaxed_") and c != "relaxed_total"]
    lines = ["# 球団生成モード 検証レポート", ""]
    lines += ["簡易版（合否には使わない）", ""] if args.quick else []
    lines += checks_section(graded)
    lines += [
        "## 生成時間と条件をゆるめた件数", "",
        f"- 球団数: {len(frame)}（seed {BASE_SEED}〜）、並列数 {args.workers}",
        f"- 1球団あたりの生成時間: 平均 {elapsed.mean():.2f}秒 / 中央 {elapsed.median():.2f}秒 / 最大 {elapsed.max():.2f}秒（並列実行中の計測）",
        *[f"- {c.removeprefix('relaxed_')}をゆるめた人数: 合計 {int(frame[c].sum())}人（{int((frame[c] > 0).sum())}球団）" for c in relaxed_cols],
        "",
        "## 構成（実在60チームと生成）", "",
        to_markdown(comp.drop(columns=["列"])), "",
        "## 年齢帯別の特能・ランク（特能ランク年齢補正_改修指示.md、日本人）", "",
        *age_lines,
    ]

    # --- 戦力
    if strength_records:
        real = real_context()["metrics"]
        strength_table, strength_checks = tables["strength"], tables["strength_checks"]
        strength_table.to_csv(args.output / "strength_metrics.csv", index=False, encoding="utf-8-sig")
        sframe = pd.DataFrame(strength_records).drop(columns=["uniform_rows", "age_rows"])
        sframe.to_csv(args.output / "strength_teams.csv", index=False, encoding="utf-8-sig")
        html = ["<!doctype html><meta charset='utf-8'><title>戦力指数と査定指標</title><body style='font-family:sans-serif'>",
                "<p>色: <span style='color:#d9480f'>強豪</span> / <span style='color:#1971c2'>中位</span> / <span style='color:#5c940d'>弱小</span></p><div style='display:flex;flex-wrap:wrap;gap:12px'>"]
        html.append(svg_scatter(sframe, "s", "metric_top28", "戦力指数 s と 上位28人平均"))
        html.append(svg_scatter(sframe, "s_pitcher", "metric_pitcher_top", "投手の戦力指数と投手上位平均"))
        html.append(svg_scatter(sframe, "s_fielder", "metric_fielder_top", "野手の戦力指数と野手上位平均"))
        html.append(svg_scatter(sframe, "metric_pitcher_top", "metric_fielder_top", "投手上位平均と野手上位平均"))
        html.append("</div></body>")
        (args.output / "strength_scatter.html").write_text("".join(html), encoding="utf-8")
        lines += [f"## 戦力レベル（{len(strength_records)}球団）", "", to_markdown(strength_table), "",
                  to_markdown(pd.DataFrame(strength_checks).assign(合否=lambda d: d["合否"].map({True: "OK", False: "NG"}))), "",
                  "実在12球団の各球団の値:", "", to_markdown(real.round(1)), ""]
        lines += ["散布図: strength_scatter.html", ""]

    # --- カラー
    if color_records:
        color_table, color_checks = tables["color"], tables["color_checks"]
        color_table.to_csv(args.output / "color_effects.csv", index=False, encoding="utf-8-sig")
        lines += [f"## チームカラー（各カラー{args.color_teams}球団、t=1.0・サブカラーなしに固定。国内選手の平均の、特色なしとの差）", "",
                  to_markdown(color_table), "",
                  to_markdown(pd.DataFrame(color_checks).assign(合否=lambda d: d["合否"].map({True: "OK", False: "NG"}))), ""]
    if strength_records:
        intensity = color_intensity_table(strength_records)
        intensity.to_csv(args.output / "color_intensity.csv", index=False, encoding="utf-8-sig")
        lines += ["### 効き具合 t と効果の大きさ（通常抽選の球団、サブカラーなし）", "", to_markdown(intensity), ""]

    # --- 背番号
    focus = usage[usage["番号"].isin(["0", "00", "1", "2", "7", "11", "18", "22", "27", "42", "51", "70", "71", "90", "95", "99"])]
    lines += [
        "## 背番号（実在60チームと生成）", "",
        f"- 0〜69と00の空き番号（欠番を含む）: 実在 平均7.7（3〜13） / 生成 " + "、".join(f"{k} {v}" for k, v in uni["empty_low"].items()),
        f"- 70〜98の使用数: 実在 平均5.2（2〜9） / 生成 " + "、".join(f"{k} {v}" for k, v in uni["high_used"].items()),
        f"- 99の使用率: 実在 80% / 生成 {uni['rate_99'] * 100:.1f}%",
        f"- 欠番の個数: 生成 平均 {frame['retired_count'].mean():.2f}（実在 2.75）",
        "",
        "主な番号:", "", to_markdown(focus), "",
        "番号帯ごとの査定百分位と年齢:", "", to_markdown(bands), "",
        "### 外国人の番号（背番号補正_改修指示.md §1-1）", "",
        "番号ごとの、その番号を使った選手のうち外国人の割合:", "", to_markdown(uniform_detail["foreign_rate"]), "",
        "外国人全体のうち、その範囲の番号を持つ割合:", "", to_markdown(uniform_detail["foreign_range"]), "",
        "### 年齢と背番号（日本人、§1-2）", "", to_markdown(uniform_detail["age"]), "",
        "### 70〜98番（§1-3）", "", to_markdown(uniform_detail["high"]), "",
        "全番号の表: uniform_number_usage.csv", "",
    ]
    if spread_records:
        spread_lines, _spread = spread_section(spread_records, args.output, real_context()["spread_values"])
        lines += spread_lines
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"レポート: {args.output / 'summary.md'}")
    sys.exit(checklib.finish(SCRIPT, graded, args))


def grade_spread_only(spread_records: list[dict[str, Any]], boot: int, quick: bool) -> list[checklib.Check]:
    """球団ごとの散らばりだけの判定（--spread-only）。"""
    data = {"main": [], "spread": slim(spread_records)}
    real = real_context()
    checks = spread_tables(data["spread"], real["spread_values"])[2]
    evaluate = lambda d: spread_tables(d, real["spread_values"])[2]  # noqa: E731
    se_gen = checklib.bootstrap_se(evaluate, data["spread"], checklib.resample_list, n=boot) if boot else {}
    se_real = real_se_map({"spread": data["spread"]}, boot)
    se_real = {key: value for key, value in se_real.items() if key.startswith(f"{SCRIPT}.spread.")}
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


if __name__ == "__main__":
    main()
