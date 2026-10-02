"""球団生成モードの検証。

固定seedで球団を生成し、実在データ（data/reference/ と 2026年版実在12球団の選手データ）と比べて
reports/team_mode/ にレポートを出す。

    python scripts/validate_team_mode.py                 # 既定: 構成・背番号500球団、戦力600球団、カラー7×200球団
    python scripts/validate_team_mode.py --teams 50 --strength-teams 100 --color-teams 30   # 簡易版

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

import check_age_profile  # noqa: E402

OUTPUT_DIR = APP_DIR / "reports" / "team_mode"
REAL_PLAYERS_DIR = APP_DIR / "reports" / "real_powerpro_players_12teams"
BASE_SEED = 20261001
STRENGTH_BASE_SEED = 30000000
COLOR_BASE_SEED = 40000000
# 投手指標と野手指標の相関の目標。実在12球団は0.37（12球団だけでは誤差が大きい）
CORRELATION_RANGE = (0.25, 0.60)
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
        "age_rows": [check_age_profile.player_metrics(p, "球団") for p in players if check_age_profile.is_target(p)],
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
# 実在データ
# ---------------------------------------------------------------------------
def load_real_players() -> pd.DataFrame:
    """2026年版実在12球団の選手を、generator/rating.py で査定できる形にする。"""
    players = pd.read_csv(REAL_PLAYERS_DIR / "players.csv")
    specials = pd.read_csv(REAL_PLAYERS_DIR / "special_abilities.csv")
    breaking = pd.read_csv(REAL_PLAYERS_DIR / "breaking_balls.csv")
    special_map: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in specials.itertuples():
        special_map[(row.team, row.name)].append((str(row.special), str(row.special_kind)))
    ball_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    kind = breaking["kind"].fillna("breaking").astype(str)
    status = breaking["status"].fillna("ok").astype(str)
    usable = breaking[(kind.eq("breaking") & status.isin(["ok", "corrected_by_direction_filter"])) | kind.eq("second_fastball")]
    for row in usable.itertuples():
        movement = pd.to_numeric(row.movement, errors="coerce")
        ball_map[(row.team, row.name)].append({"kind": str(row.kind), "movement": 0 if pd.isna(movement) else int(movement)})
    rows = []
    for row in players.itertuples():
        key = (row.team, row.name)
        ranked = {}
        normal = []
        for name, special_kind in special_map.get(key, []):
            if special_kind == "rank":
                ranked[name[:-1]] = name
            else:
                normal.append(name)
        if row.role == "投手":
            roles = str(row.pitcher_roles or "")
            marks = {label: ("◎" if index == 0 else "○") for index, label in enumerate(roles)}
            abilities = {"球速": row.top_speed, "コントロール": {"value": row.control}, "スタミナ": {"value": row.stamina}, "ranked_specials": ranked}
            player = {
                "role": "投手", "abilities": abilities, "special_abilities": normal, "breaking_balls": ball_map.get(key, []),
                "starter_aptitude": marks.get("先", "-"), "reliever_aptitude": marks.get("中", "-"), "closer_aptitude": marks.get("抑", "-"),
                "sub_positions": [{"position": p, "aptitude": "○"} for p in str(row.sub_positions).split(";") if p and p != "nan"],
            }
        else:
            abilities = {"弾道": row.trajectory, "ranked_specials": ranked}
            for label, column in (("ミート", "contact"), ("パワー", "power"), ("走力", "run_speed"), ("肩力", "arm_strength"), ("守備力", "fielding"), ("捕球", "catching")):
                abilities[label] = {"value": getattr(row, column)}
            player = {"role": "野手", "abilities": abilities, "special_abilities": normal}
        rows.append({"team": row.team, "role": row.role, "rating": player_rating(player)})
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


def composition_compare(records: list[dict[str, Any]]) -> pd.DataFrame:
    age_columns = {band for band, _low, _high in team_lib.AGE_BANDS}
    age_records = [r for r in records if r["color"] not in AGE_COLORS and r["sub_color"] not in AGE_COLORS]
    rows = []
    for column, label in team_lib.COMPOSITION_ITEMS:
        real = describe(team_lib.real_composition_values(column))
        targets = age_records if column in age_columns else records
        gen = describe([record[f"comp_{column}"] for record in targets])
        ok = gen["10%"] >= real["最小"] and gen["90%"] <= real["最大"]
        note = f"若手育成・ベテラン重視を除く{len(targets)}球団" if column in age_columns else ""
        rows.append({"項目": label, "列": column, **{f"実在{k}": v for k, v in real.items()}, **{f"生成{k}": v for k, v in gen.items()}, "合否": "OK" if ok else "NG", "備考": note})
    return pd.DataFrame(rows)


METRICS = (("metric_top28", "上位28人平均"), ("metric_all", "全員平均"), ("metric_pitcher_top", f"投手上位{team_lib.TOP_PITCHER_COUNT}人平均"), ("metric_fielder_top", f"野手上位{team_lib.TOP_FIELDER_COUNT}人平均"))


def strength_tables(records: list[dict[str, Any]], real: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
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
    for column, label in METRICS:
        by_level = {level: frame.loc[frame.strength == level, column] for level in team_lib.STRENGTH_LABELS}
        strong, mid, weak = by_level["強豪"], by_level["中位"], by_level["弱小"]
        real_mean, real_min, real_max = real[column].mean(), real[column].min(), real[column].max()
        gap = strong.mean() - mid.mean()
        overall = frame[column]
        p10, p90 = overall.quantile(0.1), overall.quantile(0.9)
        checks += [
            {"指標": label, "確認": "(a) 強豪 > 中位 > 弱小", "値": f"{strong.mean():.1f} > {mid.mean():.1f} > {weak.mean():.1f}", "合否": strong.mean() > mid.mean() > weak.mean()},
            {"指標": label, "確認": "(b) 中位の平均が実在平均±3%", "値": f"中位 {mid.mean():.1f} / 実在 {real_mean:.1f}（{(mid.mean() / real_mean - 1) * 100:+.1f}%）", "合否": abs(mid.mean() / real_mean - 1) <= 0.03},
            {"指標": label, "確認": "(c) 全体の10〜90%が実在の最小〜最大から大きく外れない（±3%）", "値": f"生成 {p10:.1f}〜{p90:.1f} / 実在 {real_min:.1f}〜{real_max:.1f}", "合否": p10 >= real_min * 0.97 and p90 <= real_max * 1.03},
            {"指標": label, "確認": "(d) レベル内の標準偏差 ≥ 強豪と中位の差の30%", "値": f"強豪 {strong.std():.1f} / 中位 {mid.std():.1f} / 弱小 {weak.std():.1f}（差 {gap:.1f} の30% = {gap * 0.3:.1f}）", "合否": min(strong.std(), mid.std(), weak.std()) >= gap * 0.3},
            {"指標": label, "確認": "(e) 強豪の下位10% < 中位の上位10%、強豪の中央値 > 中位の上位25%", "値": f"強豪10% {strong.quantile(0.1):.1f} < 中位90% {mid.quantile(0.9):.1f}、強豪中央 {strong.median():.1f} > 中位75% {mid.quantile(0.75):.1f}", "合否": strong.quantile(0.1) < mid.quantile(0.9) and strong.median() > mid.quantile(0.75)},
        ]
    corr = frame["metric_pitcher_top"].corr(frame["metric_fielder_top"])
    z_p = (frame["metric_pitcher_top"] - frame["metric_pitcher_top"].mean()) / frame["metric_pitcher_top"].std()
    z_f = (frame["metric_fielder_top"] - frame["metric_fielder_top"].mean()) / frame["metric_fielder_top"].std()
    gap = z_p - z_f
    checks.append({
        "指標": "投手上位・野手上位", "確認": f"(f) 投手指標と野手指標の相関 {CORRELATION_RANGE[0]}〜{CORRELATION_RANGE[1]}",
        "値": f"相関 {corr:.2f}（投高打低 {int((gap > 1).sum())}球団・打高投低 {int((gap < -1).sum())}球団・偏りなし {int((gap.abs() <= 1).sum())}球団、zの差±1で区分）",
        "合否": CORRELATION_RANGE[0] <= corr <= CORRELATION_RANGE[1],
    })
    return table, checks


def color_tables(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frame = pd.DataFrame(records)
    base = frame[frame.color == team_lib.NO_COLOR]
    base_means = {
        "pitcher_top": base["dom_pitcher_top"].mean(), "power": base["dom_power"].mean(),
        "contact_power": (base["dom_contact"] + base["dom_power"]).mean(), "speed": base["dom_speed"].mean(),
        "fielding": base["dom_fielding"].mean(), "arm": base["dom_arm"].mean(), "age": base["dom_age"].mean(),
    }
    rows, checks = [], []
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
    table = pd.DataFrame(rows).rename(columns={
        "pitcher_top_pct": f"投手上位{team_lib.TOP_PITCHER_COUNT}人査定(%)", "power": "パワー", "contact_power": "ミート+パワー",
        "speed": "走力", "fielding": "守備力", "arm": "肩力", "age": "平均年齢",
    })
    return table, checks


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
# 修正前（PR #102 第2版の背番号の重み）で520球団を生成したときの、番号ごとの使用率と実在の相関。これより悪化しないこと
UNIFORM_USE_RATE_CORR_BEFORE = 0.9857


def _range_text(low: float | None, high: float | None) -> str:
    if low is None and high is None:
        return "今のまま（表示のみ）"
    if low is None:
        return f"{high}以下"
    return f"{low}〜{high}"


def uniform_detail_tables(records: list[dict[str, Any]]) -> tuple[dict[str, pd.DataFrame], list[tuple[str, bool]]]:
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
    passes: list[tuple[str, bool]] = []

    rows = []
    for number, (real, low, high) in UNIFORM_FOREIGN_RATE_TARGETS.items():
        rate = by_number[number]["foreign"] / by_number[number]["all"] if by_number[number]["all"] else 0.0
        ok = (low is None or rate >= low) and (high is None or rate <= high)
        target = _range_text(low, high)
        rows.append({"番号": number, "実在": real, "生成": round(rate, 3), "目標": target, "合否": "OK" if ok else "NG"})
        if low is not None or high is not None:
            passes.append((f"{number}番の外国人の割合 {target}（生成 {rate:.3f}）", ok))
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
            passes.append((f"外国人のうち {band} 番の割合 {target}（生成 {share:.3f}）", ok))
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
        passes.append((f"日本人{role}の{band}番の平均年齢 {real_mean - 1:.1f}〜{real_mean + 1:.1f}（生成 {mean:.2f}）", ok))
        if (role, band) == ("野手", "31-69"):
            passes.append((f"日本人野手の31〜69番で31歳以上が16%以下（生成 {o31 * 100:.1f}%）", o31 <= 0.16))
        if (role, band) == ("野手", "0-10"):
            passes.append((f"日本人野手の0〜10番で31歳以上が33%以上（生成 {o31 * 100:.1f}%）", o31 >= 0.33))
    age_table = pd.DataFrame(rows)

    high_mean = statistics.fmean(high_percentiles) if high_percentiles else math.nan
    high_count = len(high_percentiles) / len(records)
    passes.append((f"70〜98番の査定の百分位の平均 0.30〜0.45（生成 {high_mean:.3f}、実在 {UNIFORM_HIGH_PERCENTILE_REAL}）", 0.30 <= high_mean <= 0.45))
    passes.append((f"70〜98番の使用数 1球団あたり4.2〜6.2個（生成 {high_count:.2f}）", 4.2 <= high_count <= 6.2))
    real_rates = [stats[n]["use_rate"] for n in team_lib.UNIFORM_NUMBERS]
    gen_rates = [teams_used[n] / len(records) for n in team_lib.UNIFORM_NUMBERS]
    corr = float(pd.Series(real_rates).corr(pd.Series(gen_rates)))
    passes.append((f"番号ごとの使用率と実在の相関が修正前（{UNIFORM_USE_RATE_CORR_BEFORE}）から悪化しない（生成 {corr:.4f}）", corr >= UNIFORM_USE_RATE_CORR_BEFORE))
    high = pd.DataFrame([
        {"項目": "70〜98番の査定の百分位の平均", "実在": UNIFORM_HIGH_PERCENTILE_REAL, "生成": round(high_mean, 3)},
        {"項目": "70〜98番の使用数（1球団あたり）", "実在": 5.2, "生成": round(high_count, 2)},
        {"項目": "番号ごとの使用率と実在の相関", "実在": f"修正前 {UNIFORM_USE_RATE_CORR_BEFORE}", "生成": round(corr, 4)},
    ])
    return {"foreign_rate": foreign_rate, "foreign_range": foreign_range, "age": age_table, "high": high}, passes


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


def main() -> None:
    parser = argparse.ArgumentParser(description="球団生成モードの検証レポートを作ります。")
    parser.add_argument("--teams", type=int, default=500, help="構成・背番号の確認に使う球団数")
    parser.add_argument("--strength-teams", type=int, default=600, help="戦力レベルの確認に使う球団数")
    parser.add_argument("--color-teams", type=int, default=200, help="チームカラーの確認に使う、カラーごとの球団数（t=1.0固定）")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--skip-color", action="store_true")
    parser.add_argument("--skip-strength", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    logging.disable(logging.WARNING)

    main_records = run_jobs([(BASE_SEED + i, None) for i in range(args.teams)], args.workers, "構成・背番号")
    strength_records = []
    if not args.skip_strength:
        extra = max(0, args.strength_teams - args.teams)
        strength_records = main_records + run_jobs([(STRENGTH_BASE_SEED + i, None) for i in range(extra)], args.workers, "戦力")
    color_records = []
    if not args.skip_color:
        jobs = [(COLOR_BASE_SEED + i, {"color": color, "color_intensity": 1.0, "sub_color": ""}) for color, _w in team_lib.COLOR_WEIGHTS for i in range(args.color_teams)]
        color_records = run_jobs(jobs, args.workers, "カラー")

    lines = ["# 球団生成モード 検証レポート", ""]
    passes: list[tuple[str, bool]] = []

    # --- 構成 ---
    comp = composition_compare(main_records)
    comp.to_csv(args.output / "composition_compare.csv", index=False, encoding="utf-8-sig")
    frame = pd.DataFrame(main_records)
    passes.append(("全項目の10〜90%が実在の最小〜最大に収まる", bool((comp["合否"] == "OK").all())))
    passes.append(("総数が70を超えない", bool((frame["comp_total"] <= 70).all())))
    passes.append(("捕手5人以上・遊撃手2人以上", bool((frame["comp_pos_C"] >= 5).all() and (frame["comp_pos_SS"] >= 2).all())))
    passes.append(("抑え適性ありが2人以上", bool((frame["comp_closer_aptitude"] >= 2).all())))
    passes.append(("名前の重複が0件", int(frame["name_duplicates"].sum()) == 0))
    passes.append(("背番号の重複が0件・欠番を使っていない・全員に背番号", int(frame["number_duplicates"].sum() + frame["retired_used"].sum() + frame["number_missing"].sum()) == 0))
    passes.append(("目標の人数と実際の人数が一致（条件をゆるめた球団を除く）", bool(frame.loc[frame.relaxed_total == 0, "targets_match"].all())))

    usage, bands, uni = uniform_tables(main_records)
    usage.to_csv(args.output / "uniform_number_usage.csv", index=False, encoding="utf-8-sig")
    bands.to_csv(args.output / "uniform_number_bands.csv", index=False, encoding="utf-8-sig")
    passes.append((f"0〜69と00の空き番号の10〜90%が3〜13（生成 {uni['empty_low']['10%']}〜{uni['empty_low']['90%']}）", 3 <= uni["empty_low"]["10%"] and uni["empty_low"]["90%"] <= 13))
    passes.append((f"70〜98の使用数の平均が5.2±2（生成 {uni['high_used']['平均']}）", abs(uni["high_used"]["平均"] - 5.2) <= 2))
    passes.append((f"99の使用率が80%±15%（生成 {uni['rate_99'] * 100:.1f}%）", abs(uni["rate_99"] - 0.80) <= 0.15))
    passes.append((f"11〜21番の投手率90%以上（生成 {uni['pitcher_rate_11_21'] * 100:.1f}%）", uni["pitcher_rate_11_21"] >= 0.90))
    uniform_detail, uniform_detail_passes = uniform_detail_tables(main_records)
    passes += uniform_detail_passes
    age_lines, age_failures = check_age_profile.report(pd.DataFrame([row for record in main_records for row in record["age_rows"]]))
    passes.append((f"年齢帯別の特能・ランク（check_age_profile.py、日本人）の不合格が0（不合格 {age_failures}）", age_failures == 0))
    passes.append((f"2・27番の捕手率30%以上（生成 2番 {uni['catcher_rate']['2'] * 100:.1f}%・27番 {uni['catcher_rate']['27'] * 100:.1f}%）", min(uni["catcher_rate"].values()) >= 0.30))

    elapsed = frame["elapsed"]
    relaxed_cols = [c for c in frame.columns if c.startswith("relaxed_") and c != "relaxed_total"]
    lines += ["## 合否", ""] + [f"- {'✅' if ok else '❌'} {label}" for label, ok in passes] + [""]
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

    # --- 戦力 ---
    if strength_records:
        real = real_team_metrics()
        strength_table, strength_checks = strength_tables(strength_records, real)
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

    # --- カラー ---
    if color_records:
        color_table, color_checks = color_tables(color_records)
        color_table.to_csv(args.output / "color_effects.csv", index=False, encoding="utf-8-sig")
        lines += [f"## チームカラー（各カラー{args.color_teams}球団、t=1.0・サブカラーなしに固定。国内選手の平均の、特色なしとの差）", "",
                  to_markdown(color_table), "",
                  to_markdown(pd.DataFrame(color_checks).assign(合否=lambda d: d["合否"].map({True: "OK", False: "NG"}))), ""]
    if strength_records:
        intensity = color_intensity_table(strength_records)
        intensity.to_csv(args.output / "color_intensity.csv", index=False, encoding="utf-8-sig")
        lines += ["### 効き具合 t と効果の大きさ（通常抽選の球団、サブカラーなし）", "", to_markdown(intensity), ""]

    # --- 背番号 ---
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
    (args.output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"レポート: {args.output / 'summary.md'}")


if __name__ == "__main__":
    main()
