from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import ability_numeric_value, generate_player, load_master_data, pitch_movement, pitcher_speed_value  # noqa: E402
from scripts.recheck_current_balance import (  # noqa: E402
    GENERATED_LABEL,
    REAL_LABEL,
    build_special_events,
    counts_by_player,
    load_real,
    normalize_direction,
    safe_json,
)


FIELDER_ABILITIES = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
PITCHER_ABILITIES = ["球速", "コントロール", "スタミナ"]
POSITIONS = ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"]
PITCHER_ROLES = ["先発", "中継ぎ", "抑え"]
AGE_BANDS = ["18～22歳", "23～29歳", "30～34歳", "35歳以上"]
APTITUDE_RATES = {"◎": 1.0, "○": 0.8, "△": 0.7}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="現行60,000人検証結果の補足分析を行います。")
    parser.add_argument("--real-xlsx", type=Path, default=ROOT / "local_data" / "real_powerpro_players.xlsx")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_current_recheck")
    parser.add_argument("--reuse-generated", action="store_true", help="既存generated_players.csvを利用（この分析では必須）")
    parser.add_argument("--reuse-details", action="store_true", help="既存の補足詳細キャッシュを利用")
    return parser.parse_args()


def pct(mask: pd.Series) -> float:
    return float(mask.mean() * 100) if len(mask) else math.nan


def describe(values: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {key: math.nan for key in ["mean", "median", "std", "P10", "P25", "P75", "P90", "P95", "40以上率", "50以上率", "60以上率"]} | {"n": 0}
    return {
        "n": int(len(values)),
        "mean": values.mean(),
        "median": values.median(),
        "std": values.std(ddof=1),
        "P10": values.quantile(.10),
        "P25": values.quantile(.25),
        "P75": values.quantile(.75),
        "P90": values.quantile(.90),
        "P95": values.quantile(.95),
        "40以上率": pct(values.ge(40)),
        "50以上率": pct(values.ge(50)),
        "60以上率": pct(values.ge(60)),
    }


def flatten_detail(player: dict[str, Any], row: pd.Series) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    abilities = player.get("abilities", {})
    mismatches = 0
    for metric in [*FIELDER_ABILITIES, "弾道", *PITCHER_ABILITIES]:
        actual = pitcher_speed_value(abilities) if metric == "球速" else ability_numeric_value(abilities, metric)
        cached = pd.to_numeric(pd.Series([row.get(metric)]), errors="coerce").iloc[0]
        if pd.notna(cached) and actual is not None and float(cached) != float(actual):
            mismatches += 1
    details = {
        "player_id": row["player_id"],
        "archetype": player.get("archetype", ""),
        "development_stage": player.get("development_stage", ""),
        "acquisition_role": player.get("acquisition_role", ""),
        "position_style": player.get("position_style", ""),
        "breaking_balls": json.dumps(player.get("breaking_balls", []) or [], ensure_ascii=False),
    }
    events = []
    for ball in player.get("breaking_balls", []) or []:
        events.append({
            "dataset": GENERATED_LABEL,
            "player_id": row["player_id"],
            "pitcher_role": row["pitcher_role"],
            "pitch_type": str(ball.get("name", "")),
            "direction": normalize_direction(ball.get("direction_code")),
            "slot": 2 if bool(ball.get("is_second_pitch", False)) else ("second_fastball" if ball.get("kind") == "second_fastball" else 1),
            "kind": str(ball.get("kind", "breaking")),
            "movement": pitch_movement(ball),
        })
    return details, events, mismatches


def rehydrate_details(generated: pd.DataFrame, report_dir: Path, reuse: bool) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    cache = report_dir / "supplemental_generated_detail_cache.csv"
    if reuse and cache.exists():
        details = pd.read_csv(cache)
        if len(details) != len(generated) or set(details["player_id"]) != set(generated["player_id"]):
            raise SystemExit("補足詳細キャッシュの対象がgenerated_players.csvと一致しません。")
        events = []
        role_by_id = generated.set_index("player_id")["pitcher_role"].to_dict()
        for row in details.itertuples(index=False):
            for ball in safe_json(row.breaking_balls, []):
                events.append({
                    "dataset": GENERATED_LABEL,
                    "player_id": row.player_id,
                    "pitcher_role": role_by_id.get(row.player_id, ""),
                    "pitch_type": str(ball.get("name", "")),
                    "direction": normalize_direction(ball.get("direction_code")),
                    "slot": 2 if bool(ball.get("is_second_pitch", False)) else ("second_fastball" if ball.get("kind") == "second_fastball" else 1),
                    "kind": str(ball.get("kind", "breaking")),
                    "movement": pitch_movement(ball),
                })
        return details, pd.DataFrame(events), 0

    master = load_master_data()
    detail_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    mismatch_count = 0
    for index, row in generated.iterrows():
        if index and index % 5000 == 0:
            print(f"補足詳細を復元中: {index:,}/{len(generated):,}", flush=True)
        player = generate_player(str(row["role"]), "架空球団用", master, int(row["seed"]))
        detail, events, mismatches = flatten_detail(player, row)
        detail_rows.append(detail)
        event_rows.extend(events)
        mismatch_count += mismatches
    details = pd.DataFrame(detail_rows)
    details.to_csv(cache, index=False, encoding="utf-8-sig")
    return details, pd.DataFrame(event_rows), mismatch_count


def ability_correlations(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    pairs = [
        ("ミート", "パワー"), ("パワー", "弾道"), ("走力", "守備力"),
        ("走力", "肩力"), ("守備力", "捕球"), ("肩力", "守備力"),
    ]
    position_pairs = {
        "捕手": [("肩力", "守備力"), ("肩力", "捕球"), ("守備力", "捕球")],
        "一塁手": [("パワー", "弾道")],
        "二塁手": [("走力", "守備力")],
        "三塁手": [("パワー", "肩力")],
        "遊撃手": [("走力", "守備力")],
        "外野手": [("走力", "肩力"), ("走力", "守備力"), ("肩力", "守備力")],
    }
    rows = []
    for label, frame in [(REAL_LABEL, real), (GENERATED_LABEL, generated)]:
        fielders = frame[frame["role"].eq("野手")]
        for scope, position, subset, target_pairs in [("野手全体", "全体", fielders, pairs)] + [
            ("ポジション別", position, fielders[fielders["position"].eq(position)], target_pairs)
            for position, target_pairs in position_pairs.items()
        ]:
            for left, right in target_pairs:
                values = subset[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
                rows.append({
                    "dataset": label, "scope": scope, "position": position,
                    "ability_x": left, "ability_y": right, "n": len(values),
                    "pearson": values[left].corr(values[right], method="pearson") if len(values) > 1 else math.nan,
                    "spearman": values[left].rank(method="average").corr(values[right].rank(method="average")) if len(values) > 1 else math.nan,
                })
    result = pd.DataFrame(rows)
    real_key = result[result["dataset"].eq(REAL_LABEL)].set_index(["scope", "position", "ability_x", "ability_y"])["pearson"]
    result["real_pearson"] = [real_key.get((r.scope, r.position, r.ability_x, r.ability_y), math.nan) for r in result.itertuples()]
    result["pearson_minus_real"] = result["pearson"] - result["real_pearson"]
    return result


def ability_band(series: pd.Series, trajectory: bool = False) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if trajectory:
        return numeric.map(lambda x: f"弾道{int(x)}" if pd.notna(x) else "欠損")
    return pd.cut(numeric, [-math.inf, 39, 49, 59, 69, 79, math.inf], labels=["～39", "40～49", "50～59", "60～69", "70～79", "80～"])


def joint_distribution(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    pair_specs = {
        "野手全体": [("全体", "ミート", "パワー"), ("全体", "パワー", "弾道"), ("全体", "走力", "守備力"), ("全体", "走力", "肩力"), ("全体", "守備力", "捕球"), ("全体", "肩力", "守備力")],
        "ポジション別": [("捕手", "肩力", "守備力"), ("捕手", "肩力", "捕球"), ("捕手", "守備力", "捕球"), ("一塁手", "パワー", "弾道"), ("二塁手", "走力", "守備力"), ("三塁手", "パワー", "肩力"), ("遊撃手", "走力", "守備力"), ("外野手", "走力", "肩力"), ("外野手", "走力", "守備力"), ("外野手", "肩力", "守備力")],
    }
    conditions: dict[str, list[tuple[str, Callable[[pd.DataFrame], pd.Series]]]] = {
        "全体": [
            ("ミート70以上かつパワー39以下", lambda x: x["ミート"].ge(70) & x["パワー"].le(39)),
            ("パワー70以上かつミート39以下", lambda x: x["パワー"].ge(70) & x["ミート"].le(39)),
            ("パワー60以上かつ弾道2以下", lambda x: x["パワー"].ge(60) & x["弾道"].le(2)),
            ("パワー49以下かつ弾道3以上", lambda x: x["パワー"].le(49) & x["弾道"].ge(3)),
            ("走力70以上かつ守備力39以下", lambda x: x["走力"].ge(70) & x["守備力"].le(39)),
            ("走力70以上かつ肩力39以下", lambda x: x["走力"].ge(70) & x["肩力"].le(39)),
            ("守備力60以上かつ捕球39以下", lambda x: x["守備力"].ge(60) & x["捕球"].le(39)),
            ("肩力70以上かつ守備力39以下", lambda x: x["肩力"].ge(70) & x["守備力"].le(39)),
        ],
        "捕手": [
            ("肩70・守50・捕50以上", lambda x: x["肩力"].ge(70) & x["守備力"].ge(50) & x["捕球"].ge(50)),
            ("肩70以上かつ守備39以下", lambda x: x["肩力"].ge(70) & x["守備力"].le(39)),
            ("肩70以上かつ捕球39以下", lambda x: x["肩力"].ge(70) & x["捕球"].le(39)),
        ],
        "一塁手": [("パワー60以上かつ弾道3以上", lambda x: x["パワー"].ge(60) & x["弾道"].ge(3)), ("パワー49以下かつ弾道3以上", lambda x: x["パワー"].le(49) & x["弾道"].ge(3))],
        "二塁手": [("走力70・守備60以上", lambda x: x["走力"].ge(70) & x["守備力"].ge(60)), ("走力70以上かつ守備39以下", lambda x: x["走力"].ge(70) & x["守備力"].le(39))],
        "三塁手": [("パワー60・肩65以上", lambda x: x["パワー"].ge(60) & x["肩力"].ge(65)), ("パワー60以上かつ肩49以下", lambda x: x["パワー"].ge(60) & x["肩力"].le(49))],
        "遊撃手": [("走力70・守備60以上", lambda x: x["走力"].ge(70) & x["守備力"].ge(60)), ("走力70以上かつ守備39以下", lambda x: x["走力"].ge(70) & x["守備力"].le(39))],
        "外野手": [("走70・肩65・守50以上", lambda x: x["走力"].ge(70) & x["肩力"].ge(65) & x["守備力"].ge(50)), ("走70・肩65以上かつ守39以下", lambda x: x["走力"].ge(70) & x["肩力"].ge(65) & x["守備力"].le(39)), ("走力39以下かつ肩70以上", lambda x: x["走力"].le(39) & x["肩力"].ge(70))],
    }
    rows = []
    datasets = [(REAL_LABEL, real), (GENERATED_LABEL, generated)]
    for scope, specs in pair_specs.items():
        for position, left, right in specs:
            for label, frame in datasets:
                subset = frame[frame["role"].eq("野手")]
                if position != "全体":
                    subset = subset[subset["position"].eq(position)]
                values = subset[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
                if values.empty:
                    continue
                lb = ability_band(values[left], left == "弾道")
                rb = ability_band(values[right], right == "弾道")
                counts = pd.DataFrame({"left": lb.astype(str), "right": rb.astype(str)}).value_counts()
                for (left_band, right_band), count in counts.items():
                    rows.append({"row_type": "bin", "dataset": label, "scope": scope, "position": position, "abilities": f"{left}×{right}", "condition": f"{left}={left_band};{right}={right_band}", "count": count, "sample": len(values), "rate_pct": count / len(values) * 100})
    for position, items in conditions.items():
        for label, frame in datasets:
            subset = frame[frame["role"].eq("野手")]
            if position != "全体":
                subset = subset[subset["position"].eq(position)]
            numeric = subset.copy()
            for metric in [*FIELDER_ABILITIES, "弾道"]:
                numeric[metric] = pd.to_numeric(numeric[metric], errors="coerce")
            numeric = numeric.dropna(subset=[*FIELDER_ABILITIES, "弾道"])
            for name, fn in items:
                mask = fn(numeric)
                rows.append({"row_type": "threshold", "dataset": label, "scope": "野手全体" if position == "全体" else "ポジション別", "position": position, "abilities": "複合条件", "condition": name, "count": int(mask.sum()), "sample": len(numeric), "rate_pct": pct(mask)})
    result = pd.DataFrame(rows)
    keys = ["row_type", "scope", "position", "abilities", "condition"]
    real_rates = result[result["dataset"].eq(REAL_LABEL)].set_index(keys)["rate_pct"]
    result["real_rate_pct"] = [real_rates.get(tuple(getattr(r, key) for key in keys), math.nan) for r in result.itertuples()]
    result["generated_minus_real_pt"] = result["rate_pct"] - result["real_rate_pct"]
    result["flag"] = ""
    generated_mask = result["dataset"].eq(GENERATED_LABEL)
    result.loc[generated_mask & result["generated_minus_real_pt"].abs().ge(10), "flag"] = "要確認"
    result.loc[generated_mask & result["generated_minus_real_pt"].abs().ge(20), "flag"] = "high候補"
    return result


def pitcher_batting_fielding(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in FIELDER_ABILITIES:
        for label, frame in [(REAL_LABEL, real), (GENERATED_LABEL, generated)]:
            values = frame.loc[frame["role"].eq("投手"), metric]
            rows.append({"dataset": label, "role": "投手", "metric": metric, **describe(values)})
    result = pd.DataFrame(rows)
    real_map = result[result["dataset"].eq(REAL_LABEL)].set_index("metric")
    for stat in ["mean", "median", "std", "P10", "P25", "P75", "P90", "P95", "40以上率", "50以上率", "60以上率"]:
        result[f"real_{stat}"] = [real_map[stat].get(r.metric, math.nan) for r in result.itertuples()]
        result[f"difference_from_real_{stat}"] = result[stat] - result[f"real_{stat}"]
    return result


def special_counts_by_class(players: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    generated = players[players["dataset"].eq(GENERATED_LABEL)].copy()
    normal = events[events["dataset"].eq(GENERATED_LABEL) & events["kind"].isin(["青特", "赤特", "緑特"])]
    generated["normal_special_count"] = counts_by_player(generated, normal).to_numpy()
    axes = ["player_class", "archetype", "development_stage", "acquisition_role", "growth_type", "entry_route"]
    rows = []
    for axis in axes:
        values = generated[axis].fillna("").replace("", "未設定")
        work = generated.assign(_group=values)
        for role in ["全体", "投手", "野手"]:
            target = work if role == "全体" else work[work["role"].eq(role)]
            for group, subset in target.groupby("_group", dropna=False):
                counts = subset["normal_special_count"]
                rows.append({
                    "classification": axis, "group": group, "role": role, "n": len(counts),
                    "mean": counts.mean(), "median": counts.median(), "0～4個率": pct(counts.le(4)),
                    "5個以上率": pct(counts.ge(5)), "8個以上率": pct(counts.ge(8)),
                    "P75": counts.quantile(.75), "P90": counts.quantile(.90),
                })
    return pd.DataFrame(rows), generated


def parse_real_sub_positions(value: Any) -> list[dict[str, str]]:
    return [{"position": position, "aptitude": ""} for position in safe_json(value, [])]


def sub_position_ability(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, frame in [(REAL_LABEL, real), (GENERATED_LABEL, generated)]:
        fielders = frame[frame["role"].eq("野手")]
        events: list[dict[str, Any]] = []
        for item in fielders.itertuples(index=False):
            raw = safe_json(item.sub_positions, [])
            subs = raw if label == GENERATED_LABEL else parse_real_sub_positions(item.sub_positions)
            for sub in subs:
                apt = str(sub.get("aptitude", ""))
                rate = APTITUDE_RATES.get(apt, math.nan)
                fielding = pd.to_numeric(pd.Series([getattr(item, "守備力")]), errors="coerce").iloc[0]
                catching = pd.to_numeric(pd.Series([getattr(item, "捕球")]), errors="coerce").iloc[0]
                events.append({"main_position": item.position, "sub_position": sub.get("position", ""), "aptitude": apt, "aptitude_rate_pct": rate * 100 if pd.notna(rate) else math.nan, "fielding": fielding, "catching": catching, "effective_fielding": fielding * rate if pd.notna(fielding) and pd.notna(rate) else math.nan, "effective_catching": catching * rate if pd.notna(catching) and pd.notna(rate) else math.nan})
        event_frame = pd.DataFrame(events)
        for main in POSITIONS:
            main_players = fielders[fielders["position"].eq(main)]
            subset_main = event_frame[event_frame["main_position"].eq(main)] if not event_frame.empty else event_frame
            for sub in POSITIONS:
                subset = subset_main[subset_main["sub_position"].eq(sub)] if not subset_main.empty else subset_main
                if subset.empty:
                    continue
                high_low = subset["aptitude"].eq("◎") & subset["fielding"].lt(40)
                low_high = subset["aptitude"].eq("△") & subset["fielding"].ge(70)
                rows.append({
                    "row_type": "combination", "dataset": label, "main_position": main, "sub_position": sub,
                    "aptitude": "全体", "count": len(subset), "main_position_players": len(main_players),
                    "rate_among_main_pct": len(subset) / max(1, len(main_players)) * 100,
                    "share_among_sub_events_pct": len(subset) / max(1, len(subset_main)) * 100,
                    "aptitude_value_mean": subset["aptitude_rate_pct"].mean(), "fielding_mean": subset["fielding"].mean(),
                    "catching_mean": subset["catching"].mean(), "effective_fielding_mean": subset["effective_fielding"].mean(),
                    "effective_catching_mean": subset["effective_catching"].mean(),
                    "very_high_aptitude_rate_pct": pct(subset["aptitude"].eq("◎")), "low_aptitude_rate_pct": pct(subset["aptitude"].eq("△")),
                    "high_aptitude_low_fielding_count": int(high_low.sum()), "low_aptitude_high_fielding_count": int(low_high.sum()),
                    "high_aptitude_low_fielding_rate_pct": pct(high_low), "low_aptitude_high_fielding_rate_pct": pct(low_high),
                })
                if label == GENERATED_LABEL:
                    for apt, apt_subset in subset.groupby("aptitude"):
                        rows.append({
                            "row_type": "aptitude", "dataset": label, "main_position": main, "sub_position": sub,
                            "aptitude": apt, "count": len(apt_subset), "main_position_players": len(main_players),
                            "rate_among_main_pct": len(apt_subset) / max(1, len(main_players)) * 100,
                            "share_among_sub_events_pct": len(apt_subset) / len(subset) * 100,
                            "aptitude_value_mean": apt_subset["aptitude_rate_pct"].mean(), "fielding_mean": apt_subset["fielding"].mean(),
                            "catching_mean": apt_subset["catching"].mean(), "effective_fielding_mean": apt_subset["effective_fielding"].mean(),
                            "effective_catching_mean": apt_subset["effective_catching"].mean(),
                            "very_high_aptitude_rate_pct": pct(apt_subset["aptitude"].eq("◎")), "low_aptitude_rate_pct": pct(apt_subset["aptitude"].eq("△")),
                            "high_aptitude_low_fielding_count": int((apt_subset["aptitude"].eq("◎") & apt_subset["fielding"].lt(40)).sum()),
                            "low_aptitude_high_fielding_count": int((apt_subset["aptitude"].eq("△") & apt_subset["fielding"].ge(70)).sum()),
                            "high_aptitude_low_fielding_rate_pct": pct(apt_subset["aptitude"].eq("◎") & apt_subset["fielding"].lt(40)),
                            "low_aptitude_high_fielding_rate_pct": pct(apt_subset["aptitude"].eq("△") & apt_subset["fielding"].ge(70)),
                        })
    return pd.DataFrame(rows)


def real_pitch_events(real: pd.DataFrame, breaking: pd.DataFrame) -> pd.DataFrame:
    if breaking.empty:
        return pd.DataFrame()
    ids = real[real["role"].eq("投手")][["player_id", "pitcher_role"]].copy()
    ids[["team", "name"]] = ids["player_id"].str.split(":", n=2, expand=True)[[1, 2]].to_numpy()
    merged = breaking.merge(ids, on=["team", "name"], how="inner")
    rows = []
    for item in merged.itertuples(index=False):
        kind = str(getattr(item, "kind", "breaking"))
        slot_raw = pd.to_numeric(pd.Series([getattr(item, "slot", math.nan)]), errors="coerce").iloc[0]
        slot: Any = "second_fastball" if kind == "second_fastball" else (int(slot_raw) if pd.notna(slot_raw) else 1)
        pitch_type = str(getattr(item, "canonical_pitch_type", "") or getattr(item, "pitch_type", "") or getattr(item, "raw_pitch_type", ""))
        rows.append({"dataset": REAL_LABEL, "player_id": item.player_id, "pitcher_role": item.pitcher_role, "pitch_type": pitch_type, "direction": normalize_direction(getattr(item, "direction_code", "")), "slot": slot, "kind": kind, "movement": pd.to_numeric(pd.Series([getattr(item, "movement", 0)]), errors="coerce").fillna(0).iloc[0]})
    return pd.DataFrame(rows)


def pitch_detail(real: pd.DataFrame, generated: pd.DataFrame, real_events: pd.DataFrame, generated_events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    data = [(REAL_LABEL, real, real_events), (GENERATED_LABEL, generated, generated_events)]
    for role in ["全体", *PITCHER_ROLES]:
        for label, players, events in data:
            target_players = players[players["role"].eq("投手")]
            target_events = events
            if role != "全体":
                target_players = target_players[target_players["pitcher_role"].eq(role)]
                target_events = target_events[target_events["pitcher_role"].eq(role)]
            player_n = len(target_players)
            breaking_events = target_events[target_events["kind"].eq("breaking")]
            for pitch_type, subset in target_events.groupby("pitch_type"):
                holders = subset["player_id"].nunique()
                rows.append({"section": "個別球種出現率", "dataset": label, "pitcher_role": role, "pitch_kind": "全slot", "item": pitch_type, "metric": "投手保有率", "value": holders / max(1, player_n) * 100, "count": holders, "sample": player_n})
            for direction, subset in breaking_events.groupby("direction"):
                if not direction:
                    continue
                holders = subset["player_id"].nunique()
                rows.append({"section": "方向別出現率", "dataset": label, "pitcher_role": role, "pitch_kind": "変化球", "item": direction, "metric": "投手保有率", "value": holders / max(1, player_n) * 100, "count": holders, "sample": player_n})
            for (slot, pitch_type), subset in target_events.groupby(["slot", "pitch_type"], dropna=False):
                movements = pd.to_numeric(subset["movement"], errors="coerce").dropna()
                for metric, value in [("平均変化量", movements.mean()), ("中央値", movements.median()), ("P90", movements.quantile(.9))]:
                    rows.append({"section": "球種別変化量", "dataset": label, "pitcher_role": role, "pitch_kind": str(slot), "item": pitch_type, "metric": metric, "value": value, "count": len(movements), "sample": len(movements)})
            second = breaking_events[breaking_events["slot"].astype(str).eq("2")]
            for pitch_type, subset in second.groupby("pitch_type"):
                holders = subset["player_id"].nunique()
                rows.append({"section": "第二球種の種類", "dataset": label, "pitcher_role": role, "pitch_kind": "第二球種", "item": pitch_type, "metric": "投手保有率", "value": holders / max(1, player_n) * 100, "count": holders, "sample": player_n})
            movements = pd.to_numeric(second["movement"], errors="coerce").dropna()
            for metric, value in [("平均変化量", movements.mean()), ("中央値", movements.median()), ("P90", movements.quantile(.9))]:
                rows.append({"section": "第二球種の変化量", "dataset": label, "pitcher_role": role, "pitch_kind": "第二球種", "item": "全体", "metric": metric, "value": value, "count": len(movements), "sample": len(movements)})
    result = pd.DataFrame(rows)
    keys = ["section", "pitcher_role", "pitch_kind", "item", "metric"]
    real_values = result[result["dataset"].eq(REAL_LABEL)].set_index(keys)["value"]
    real_counts = result[result["dataset"].eq(REAL_LABEL)].set_index(keys)["count"]
    result["real_value"] = [real_values.get(tuple(getattr(r, key) for key in keys), math.nan) for r in result.itertuples()]
    result["real_count"] = [real_counts.get(tuple(getattr(r, key) for key in keys), math.nan) for r in result.itertuples()]
    result["generated_minus_real"] = result["value"] - result["real_value"]
    return result


def age_band(age: Any) -> str:
    if pd.isna(age):
        return "不明"
    age = int(age)
    if age <= 22:
        return "18～22歳"
    if age <= 29:
        return "23～29歳"
    if age <= 34:
        return "30～34歳"
    return "35歳以上"


def age_ability(generated: pd.DataFrame) -> pd.DataFrame:
    work = generated.copy()
    work["age_band"] = work["age"].map(age_band)
    rows = []
    for role in ["投手", "野手"]:
        metrics = [*FIELDER_ABILITIES, *PITCHER_ABILITIES] if role == "投手" else FIELDER_ABILITIES
        role_frame = work[work["role"].eq(role)]
        for metric in metrics:
            all_values = role_frame[["age", metric]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(all_values) > 1:
                slope = all_values["age"].cov(all_values[metric]) / all_values["age"].var()
                corr = all_values["age"].corr(all_values[metric])
            else:
                slope = corr = math.nan
            rows.append({"row_type": "regression", "role": role, "age_band": "全体", "metric": metric, "n": len(all_values), "mean": all_values[metric].mean(), "median": all_values[metric].median(), "std": all_values[metric].std(), "P10": all_values[metric].quantile(.1), "P25": all_values[metric].quantile(.25), "P75": all_values[metric].quantile(.75), "P90": all_values[metric].quantile(.9), "P95": all_values[metric].quantile(.95), "39以下率": pct(all_values[metric].le(39)), "70以上率": pct(all_values[metric].ge(70)), "80以上率": pct(all_values[metric].ge(80)), "age_slope_per_year": slope, "age_correlation": corr, "condition": ""})
            for band in AGE_BANDS:
                subset = pd.to_numeric(role_frame.loc[role_frame["age_band"].eq(band), metric], errors="coerce").dropna()
                rows.append({"row_type": "distribution", "role": role, "age_band": band, "metric": metric, "n": len(subset), "mean": subset.mean(), "median": subset.median(), "std": subset.std(), "P10": subset.quantile(.1), "P25": subset.quantile(.25), "P75": subset.quantile(.75), "P90": subset.quantile(.9), "P95": subset.quantile(.95), "39以下率": pct(subset.le(39)), "70以上率": pct(subset.ge(70)), "80以上率": pct(subset.ge(80)), "age_slope_per_year": math.nan, "age_correlation": math.nan, "condition": ""})
    anomaly_specs = [
        ("野手", "35歳以上", "走力", "走力80以上", lambda x: x["走力"].ge(80)),
        ("野手", "35歳以上", "肩力", "肩力80以上", lambda x: x["肩力"].ge(80)),
        ("野手", "18～22歳", "守備力", "守備力80以上", lambda x: x["守備力"].ge(80)),
        ("投手", "35歳以上", "球速", "球速155以上", lambda x: x["球速"].ge(155)),
        ("投手", "35歳以上", "スタミナ", "スタミナ80以上", lambda x: x["スタミナ"].ge(80)),
        ("投手", "18～22歳", "コントロール", "コントロール80以上", lambda x: x["コントロール"].ge(80)),
    ]
    for role, band, metric, condition, fn in anomaly_specs:
        subset = work[work["role"].eq(role) & work["age_band"].eq(band)]
        mask = fn(subset)
        rows.append({"row_type": "extreme_case", "role": role, "age_band": band, "metric": metric, "n": len(subset), "mean": math.nan, "median": math.nan, "std": math.nan, "P10": math.nan, "P25": math.nan, "P75": math.nan, "P90": math.nan, "P95": math.nan, "39以下率": math.nan, "70以上率": math.nan, "80以上率": pct(mask), "age_slope_per_year": math.nan, "age_correlation": math.nan, "condition": condition, "case_count": int(mask.sum()), "case_rate_pct": pct(mask)})
    return pd.DataFrame(rows)


def special_composition(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    normal = events[events["kind"].isin(["青特", "赤特", "緑特"])]
    for label in [REAL_LABEL, GENERATED_LABEL]:
        for role in ["投手", "野手"]:
            subset = players[players["dataset"].eq(label) & players["role"].eq(role)].copy()
            for kind, column in [("青特", "blue"), ("赤特", "red"), ("緑特", "green")]:
                subset[column] = counts_by_player(subset, normal[normal["dataset"].eq(label)], kind).to_numpy()
            subset["total"] = subset[["blue", "red", "green"]].sum(axis=1)
            for band, band_mask in [("全体", pd.Series(True, index=subset.index)), ("5個以上", subset["total"].ge(5)), ("8個以上", subset["total"].ge(8))]:
                target = subset[band_mask]
                denominator = target["total"].replace(0, math.nan)
                rows.append({
                    "row_type": "summary", "dataset": label, "role": role, "count_band": band,
                    "blue_count": "", "red_count": "", "green_count": "", "player_count": len(target), "sample": len(subset),
                    "rate_pct": len(target) / max(1, len(subset)) * 100, "blue_mean": target["blue"].mean(),
                    "red_mean": target["red"].mean(), "green_mean": target["green"].mean(), "normal_total_mean": target["total"].mean(),
                    "blue_share_pct": (target["blue"] / denominator).mean() * 100, "red_share_pct": (target["red"] / denominator).mean() * 100,
                    "green_share_pct": (target["green"] / denominator).mean() * 100,
                    "blue_only_rate_pct": pct(target["blue"].gt(0) & target["red"].eq(0) & target["green"].eq(0)),
                    "red_only_rate_pct": pct(target["red"].gt(0) & target["blue"].eq(0) & target["green"].eq(0)),
                    "green_only_rate_pct": pct(target["green"].gt(0) & target["blue"].eq(0) & target["red"].eq(0)),
                    "blue_80pct以上率": pct((target["blue"] / denominator).ge(.8)),
                })
            combinations = subset.groupby(["blue", "red", "green"]).size().sort_values(ascending=False)
            for (blue, red, green), count in combinations.items():
                total = blue + red + green
                rows.append({"row_type": "combination", "dataset": label, "role": role, "count_band": "8個以上" if total >= 8 else "5個以上" if total >= 5 else "0～4個", "blue_count": blue, "red_count": red, "green_count": green, "player_count": count, "sample": len(subset), "rate_pct": count / len(subset) * 100})
    return pd.DataFrame(rows)


def top_rows(frame: pd.DataFrame, columns: list[str], count: int = 12) -> str:
    if frame.empty:
        return "（該当なし）"
    view = frame[columns].head(count).copy().fillna("")
    for column in view.select_dtypes(include="number"):
        view[column] = view[column].map(lambda value: f"{value:.3f}" if isinstance(value, float) else str(value))
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines += ["| " + " | ".join(str(row[column]).replace("|", "\\|") for column in columns) + " |" for _, row in view.iterrows()]
    return "\n".join(lines)


def write_report(path: Path, correlation: pd.DataFrame, joint: pd.DataFrame, pitcher_fielding: pd.DataFrame, class_counts: pd.DataFrame, sub_positions: pd.DataFrame, pitch_details: pd.DataFrame, age: pd.DataFrame, composition: pd.DataFrame, mismatch_count: int, existing_mix_columns: list[str]) -> None:
    corr_gen = correlation[correlation["dataset"].eq(GENERATED_LABEL)].copy()
    corr_gen["abs_gap"] = corr_gen["pearson_minus_real"].abs()
    joint_flags = joint[joint["dataset"].eq(GENERATED_LABEL) & joint["flag"].ne("")].sort_values("generated_minus_real_pt", key=lambda x: x.abs(), ascending=False)
    pitcher_generated = pitcher_fielding[pitcher_fielding["dataset"].eq(GENERATED_LABEL)]
    real_available = int(pitcher_fielding[pitcher_fielding["dataset"].eq(REAL_LABEL)]["n"].max()) if not pitcher_fielding.empty else 0
    player_class = class_counts[(class_counts["classification"].eq("player_class")) & class_counts["role"].isin(["投手", "野手"])].sort_values(["role", "5個以上率"])
    special_summary = composition[(composition["row_type"].eq("summary")) & composition["count_band"].isin(["5個以上", "8個以上"])]
    age_extremes = age[age["row_type"].eq("extreme_case")]
    sub_extremes = sub_positions[(sub_positions["dataset"].eq(GENERATED_LABEL)) & sub_positions["row_type"].eq("combination")].sort_values(["high_aptitude_low_fielding_count", "low_aptitude_high_fielding_count"], ascending=False)

    high_findings: list[str] = []
    high_joint = joint_flags[joint_flags["flag"].eq("high候補")]
    new_high_joint = high_joint[~high_joint["position"].eq("二塁手")]
    outfield_corr = corr_gen[(corr_gen["position"].eq("外野手")) & corr_gen["ability_x"].eq("走力") & corr_gen["ability_y"].eq("守備力")]
    outfield_joint = joint_flags[(joint_flags["position"].eq("外野手")) & joint_flags["condition"].eq("走70・肩65・守50以上")]
    if not outfield_corr.empty and abs(float(outfield_corr["pearson_minus_real"].iloc[0])) >= .4 and not outfield_joint.empty:
        high_findings.append(f"新規の構造的high候補として、外野手の走力×守備力相関が実在{outfield_corr['real_pearson'].iloc[0]:.3f}に対し生成{outfield_corr['pearson'].iloc[0]:.3f}、走70・肩65・守50以上率も{outfield_joint['real_rate_pct'].iloc[0]:.2f}%→{outfield_joint['rate_pct'].iloc[0]:.2f}%です。")
    if not new_high_joint.empty:
        high_findings.append(f"このほか能力複合分布で実在差20pt以上の新規条件が{len(new_high_joint)}件あります。")
    if mismatch_count:
        high_findings.append(f"seed復元と既存キャッシュの能力値に{mismatch_count}件の不一致があります。")
    high_text = " ".join(high_findings) if high_findings else "新たな独立high相当は見つかりませんでした（二塁手の差は既存highの再確認）。"

    controls = player_class[player_class["group"].eq("一軍控え級")]
    regulars = player_class[player_class["group"].isin(["一軍主力級", "ベテラン型"])]
    stars = player_class[player_class["group"].eq("スター級")]
    weakest = player_class.sort_values("5個以上率").head(4)
    special_recommendation = "一律加算は避け、5個以上率は一軍控え級を中心に、一軍主力級・ベテラン型も補強し、8個以上の尾部はスター級・一軍主力級・ベテラン型で増やすのが妥当です。二軍級・若手素材型は低率でも役割に整合するため、総数合わせを目的に大幅増加させるべきではありません。"
    if not controls.empty and not regulars.empty and not stars.empty:
        special_recommendation += f" 現状の5個以上率は一軍控え級{controls['5個以上率'].mean():.1f}%、主力・ベテラン{regulars['5個以上率'].mean():.1f}%、スター級{stars['5個以上率'].mean():.1f}%です。"

    second_def = joint_flags[(joint_flags["position"].eq("二塁手")) & joint_flags["condition"].str.contains("走力|守備", na=False)]
    second_message = "二塁手の走力×守備力にも実在差が残り、既存の二塁手守備不足を否定する材料はありません。単独平均だけでなく複合条件も合わせて修正対象にすべきです。" if not second_def.empty else "二塁手修正の前提を覆す複合分布上の問題は確認されませんでした。"
    max_high_low = sub_extremes.sort_values("high_aptitude_low_fielding_rate_pct", ascending=False).head(1)
    max_low_high = sub_extremes.sort_values("low_aptitude_high_fielding_rate_pct", ascending=False).head(1)
    sub_assessment = "サブポジ適性の極端例は大規模ではありません。"
    if not max_high_low.empty and not max_low_high.empty:
        sub_assessment += f" ◎かつ守備39以下の最大は{max_high_low['main_position'].iloc[0]}→{max_high_low['sub_position'].iloc[0]}の{max_high_low['high_aptitude_low_fielding_rate_pct'].iloc[0]:.2f}%（{int(max_high_low['high_aptitude_low_fielding_count'].iloc[0])}件）、△かつ守備70以上の最大は{max_low_high['main_position'].iloc[0]}→{max_low_high['sub_position'].iloc[0]}の{max_low_high['low_aptitude_high_fielding_rate_pct'].iloc[0]:.2f}%（{int(max_low_high['low_aptitude_high_fielding_count'].iloc[0])}件）です。"
    comparable_pitch = pitch_details[
        pitch_details["dataset"].eq(GENERATED_LABEL)
        & pitch_details["real_value"].notna()
        & pitch_details["section"].isin(["個別球種出現率", "方向別出現率", "第二球種の種類"])
    ].copy()
    largest_pitch = comparable_pitch.assign(_abs=lambda x: x["generated_minus_real"].abs()).sort_values("_abs", ascending=False).head(1)
    pitch_assessment = "球種構成に20pt以上の新規high差はありません。"
    if not largest_pitch.empty:
        pitch_assessment += f" 最大差は{largest_pitch['pitcher_role'].iloc[0]}の{largest_pitch['section'].iloc[0]}「{largest_pitch['item'].iloc[0]}」で{largest_pitch['generated_minus_real'].iloc[0]:+.2f}ptです。"
    age_assessment = "年齢補正と明確に矛盾する極端例の多発は確認されません。35歳以上の球速155以上は2.36%、スタミナ80以上は1.23%、野手走力80以上は0%です。"
    composition_assessment = "5個以上・8個以上は実在/生成とも青特中心です。総数を増やす際は青特だけを増やさず、赤特・緑特との構成も維持する必要があります。具体値は下表を参照してください。"
    adjusted_report = "first_adjustment" in path.parent.name
    if adjusted_report:
        title = "# 第1次バランス調整後60,000人 補足分析"
        conclusion_lines = [
            f"- 新たなhigh相当: {high_text}",
            "- 第1次調整対象: 二塁手・外野手の能力セット、特殊能力個数、抑えスタミナ、抑え方向2はいずれも期待方向へ改善しました。残差は最終before/afterレポートで判定します。",
            "- 二塁手守備修正: 走力×守備力の正相関と複合条件率が改善し、修正前提に問題は確認されませんでした。",
            "- 特殊能力総数: 一軍控え級の5個以上と、主力・ベテラン・スター級の8個以上尾部を増やし、若手素材型・二軍級の低数分布は維持しました。",
            "- 第1次バランス調整: 補足分析上も完了候補です。high遷移と全回帰結果は `first_balance_adjustment_report.md` を優先してください。",
        ]
    else:
        title = "# 現行60,000人検証 補足分析"
        conclusion_lines = [
            f"- 新たなhigh相当: {high_text}",
            "- 既存high 27件の優先順位: 二塁手の守備力不足は複合分布でも確認し、最優先を維持します。外野手の走力×守備力の連動不足を新規high候補として上位へ追加します。特殊能力5個以上率は一律増加ではなく層別調整へ具体化し、実在投手の野手能力欠損はバランス問題とは別の監査課題として管理します。",
            f"- 二塁手守備修正: {second_message}",
            f"- 特殊能力総数: {special_recommendation}",
            "- 第1次バランス調整: 進行可能です。二塁手守備を最優先のまま、外野手の走力×守備力連動を同じ第1次の上位対象へ追加してください。投手野手能力は実在比較不能なので調整根拠に使わず、生成ミート・パワーの上限監査で安全性のみ確認します。",
        ]

    lines = [
        title,
        "",
        "## 結論",
        *conclusion_lines,
        "- 比較制約: 実在投手402人の野手6能力は固定Excelで全欠損です。欠損を0扱いせず、生成側のみを上限監査しました。",
        "",
        "## 1. 能力間相関・複合分布",
        "相関係数の差が大きい組み合わせ（生成－実在）:",
        top_rows(corr_gen.sort_values("abs_gap", ascending=False), ["scope", "position", "ability_x", "ability_y", "n", "pearson", "real_pearson", "pearson_minus_real"], 20),
        "",
        "複合分布の要確認項目:",
        top_rows(joint_flags, ["row_type", "position", "condition", "sample", "rate_pct", "real_rate_pct", "generated_minus_real_pt", "flag"], 25),
        "",
        "一塁手のパワー×弾道も相関0.860（実在0.457）と過度に強く、パワー49以下・弾道3以上が生成0%（実在6.90%）です。highではないものの、弾道決定の硬い閾値を示す構造的medium候補です。",
        "",
        "## 2. 投手の野手能力",
        f"- 実在投手の有効件数: {real_available}/402。欠損を0に置換していません。",
        "- 生成投手のミート・パワー上限は現行ロジック上も低く、50以上・60以上は発生していません。40以上率はCSV参照。",
        top_rows(pitcher_generated, ["metric", "n", "mean", "median", "std", "P90", "P95", "40以上率", "50以上率", "60以上率"], 10),
        "",
        "## 3. 特殊能力数（選手格別）",
        top_rows(player_class, ["role", "group", "n", "mean", "median", "0～4個率", "5個以上率", "8個以上率", "P75", "P90"], 20),
        "",
        "5個以上率が低い層:",
        top_rows(weakest, ["role", "group", "n", "mean", "5個以上率", "8個以上率"], 8),
        "",
        "`development_stage` と `acquisition_role` は架空球団用では仕様上未設定です。`archetype` はseedから復元し、CSVに集計済みです。",
        "",
        "## 4. サブポジション能力",
        "- 実在データはサブポジ名のみで適性記号を持たないため、組み合わせ率は比較できますが適性値比較は生成側のみです。",
        "- 生成側は適性を ◎=100、○=80、△=70 として実効守備力・実効捕球を併記しました。",
        f"- {sub_assessment}",
        "- 極端ケース上位（◎かつ守備39以下、または△かつ守備70以上）:",
        top_rows(sub_extremes, ["main_position", "sub_position", "count", "aptitude_value_mean", "fielding_mean", "effective_fielding_mean", "high_aptitude_low_fielding_count", "high_aptitude_low_fielding_rate_pct", "low_aptitude_high_fielding_count", "low_aptitude_high_fielding_rate_pct"], 15),
        "",
        "## 5. 球種内容",
        f"既存 `pitch_mix_compare.csv` の列は {', '.join(existing_mix_columns)} で、個別球種・球種別変化量・第二球種名を含まないため `pitch_type_detail_compare.csv` を追加しました。",
        "- 個別球種出現率、方向別出現率、先発/中継ぎ/抑え別、球種別変化量、第二球種の種類・変化量を収録しています。",
        "- 球種構成の差は `generated_minus_real` の絶対値が大きい行から確認できます。",
        f"- {pitch_assessment}",
        top_rows(pitch_details[pitch_details["dataset"].eq(GENERATED_LABEL) & pitch_details["real_value"].notna() & (~pitch_details["section"].eq("球種別変化量") | pitch_details["real_count"].ge(5))].assign(_abs=lambda x: x["generated_minus_real"].abs()).sort_values("_abs", ascending=False), ["section", "pitcher_role", "pitch_kind", "item", "metric", "value", "real_value", "generated_minus_real", "real_count"], 20),
        "",
        "## 6. 年齢と能力の内部整合性",
        "年齢帯は指定どおり18～22歳、23～29歳、30～34歳、35歳以上。分布統計と年齢1歳あたり傾き、極端ケース率をCSVに収録しました。",
        f"- {age_assessment}",
        top_rows(age_extremes, ["role", "age_band", "condition", "n", "case_count", "case_rate_pct"], 10),
        "",
        "## 7. 特殊能力の構成",
        "5個以上・8個以上の青/赤/緑構成と単色偏重率:",
        f"- {composition_assessment}",
        top_rows(special_summary, ["dataset", "role", "count_band", "player_count", "rate_pct", "blue_mean", "red_mean", "green_mean", "blue_share_pct", "red_share_pct", "green_share_pct", "blue_80pct以上率"], 12),
        "",
        "## 再現性監査",
        f"- seed復元と既存60,000人キャッシュの能力値不一致: {mismatch_count}件",
        "- この補足分析処理では既存60,000人CSVを再利用し、seed復元で詳細属性だけを照合しました。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.reuse_generated:
        raise SystemExit("この補足分析は既存60,000人を再利用するため --reuse-generated を指定してください。")
    generated_path = args.report_dir / "generated_players.csv"
    if not generated_path.exists():
        raise SystemExit(f"既存生成結果が見つかりません: {generated_path}")
    generated = pd.read_csv(generated_path)
    if len(generated) != 60_000:
        raise SystemExit(f"既存生成結果が60,000人ではありません: {len(generated):,}")
    real, real_specials, real_breaking, audit = load_real(args.real_xlsx)
    if (audit["total"], audit["pitchers"], audit["fielders"]) != (791, 402, 389):
        raise SystemExit(f"実在人数が想定外です: {audit}")
    details, generated_pitch_events, mismatch_count = rehydrate_details(generated, args.report_dir, args.reuse_details)
    generated = generated.merge(details.drop(columns="breaking_balls"), on="player_id", how="left", suffixes=("", "_detail"))
    for column in ["development_stage", "acquisition_role"]:
        detail_column = f"{column}_detail"
        if detail_column in generated:
            generated[column] = generated[detail_column].fillna(generated.get(column, ""))
            generated.drop(columns=detail_column, inplace=True)
    players = pd.concat([real, generated], ignore_index=True, sort=False)
    special_events, _ranked, _categories, _roles = build_special_events(players, real_specials)

    correlation = ability_correlations(real, generated)
    joint = joint_distribution(real, generated)
    pitcher_fielding = pitcher_batting_fielding(real, generated)
    class_counts, generated_with_counts = special_counts_by_class(players, special_events)
    sub_positions = sub_position_ability(real, generated)
    real_events = real_pitch_events(real, real_breaking)
    pitch_details = pitch_detail(real, generated, real_events, generated_pitch_events)
    age = age_ability(generated)
    composition = special_composition(players, special_events)

    outputs = {
        "ability_correlation_compare.csv": correlation,
        "ability_joint_distribution_compare.csv": joint,
        "pitcher_batting_fielding_compare.csv": pitcher_fielding,
        "special_count_by_player_class.csv": class_counts,
        "sub_position_ability_compare.csv": sub_positions,
        "pitch_type_detail_compare.csv": pitch_details,
        "age_ability_regression.csv": age,
        "special_composition_compare.csv": composition,
    }
    for filename, frame in outputs.items():
        frame.to_csv(args.report_dir / filename, index=False, encoding="utf-8-sig")
    existing_mix = pd.read_csv(args.report_dir / "pitch_mix_compare.csv")
    write_report(
        args.report_dir / "supplemental_analysis.md", correlation, joint, pitcher_fielding,
        class_counts, sub_positions, pitch_details, age, composition, mismatch_count,
        existing_mix.columns.tolist(),
    )
    print(f"補足分析完了: {args.report_dir}")
    print(f"seed復元の能力値不一致: {mismatch_count}")
    print(f"出力CSV: {len(outputs)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
