from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CATEGORIES,
    CLASSIFICATION_COLUMNS,
    SPECIAL_KIND_LABELS,
    SPECIAL_KIND_ORDER,
    ability_numeric_value,
    generate_player,
    is_ranked_special,
    load_master_data,
    pitch_movement,
    pitcher_speed_value,
)

ROLES = ["投手", "野手"]
FIELDING_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球", "弾道"]
PITCHING_KEYS = ["球速", "コントロール", "スタミナ", "総変化量", "変化球数_第一球種のみ", "second_pitch_count"]
AGE_BINS = [0, 19, 22, 26, 30, 34, 99]
AGE_LABELS = ["18-19歳", "20-22歳", "23-26歳", "27-30歳", "31-34歳", "35歳以上"]
REPORT_FILENAMES = {
    "players": "generated_players.csv",
    "ability_stats": "ability_stats.csv",
    "special_kind_stats": "special_kind_stats.csv",
    "special_name_stats": "special_name_stats.csv",
    "ranked_special_stats": "ranked_special_stats.csv",
    "anomalies": "anomalies.csv",
    "pitcher_aptitude_summary": "pitcher_aptitude_summary.csv",
    "second_pitch_summary": "second_pitch_summary.csv",
    "breaking_pitch_summary": "breaking_pitch_summary.csv",
    "breaking_direction_summary": "breaking_direction_summary.csv",
    "pitch_count_distribution": "pitch_count_distribution.csv",
    "total_movement_distribution": "total_movement_distribution.csv",
    "sub_position_summary": "sub_position_summary.csv",
    "position_balance_summary": "position_balance_summary.csv",
    "position_balance_warnings": "position_balance_warnings.csv",
    "position_high_ability_rates": "position_high_ability_rates.csv",
    "position_distribution_diagnostics": "position_distribution_diagnostics.csv",
    "position_extreme_examples": "position_extreme_examples.csv",
    "combination_warnings": "warnings.csv",
}

REAL_POSITION_AVERAGES = {
    "捕手": {"弾道": 2.47, "ミート": 38.06, "パワー": 50.51, "走力": 51.86, "肩力": 72.72, "守備力": 48.87, "捕球": 46.92},
    "一塁手": {"弾道": 3.21, "ミート": 45.97, "パワー": 62.55, "走力": 48.55, "肩力": 60.14, "守備力": 45.83, "捕球": 48.00},
    "二塁手": {"弾道": 2.37, "ミート": 46.81, "パワー": 50.40, "走力": 71.98, "肩力": 60.16, "守備力": 59.07, "捕球": 54.05},
    "三塁手": {"弾道": 3.20, "ミート": 42.38, "パワー": 61.23, "走力": 57.88, "肩力": 64.30, "守備力": 46.40, "捕球": 45.48},
    "遊撃手": {"弾道": 2.21, "ミート": 39.79, "パワー": 45.79, "走力": 71.21, "肩力": 66.78, "守備力": 54.69, "捕球": 47.44},
    "外野手": {"弾道": 2.68, "ミート": 44.60, "パワー": 57.93, "走力": 71.62, "肩力": 67.10, "守備力": 51.13, "捕球": 47.30},
}

POSITION_WARNING_RULES = {
    "捕手": [("ミート", ">", 44), ("守備力", ">", 55), ("肩力", "<", 66), ("肩力", ">", 80), ("走力", "<", 43), ("走力", ">", 60)],
    "一塁手": [("パワー", "<", 55), ("パワー", ">", 71), ("走力", ">", 60), ("守備力", ">", 55)],
    "二塁手": [("走力", "<", 64), ("守備力", "<", 51), ("パワー", ">", 59), ("肩力", "<", 54)],
    "三塁手": [("パワー", "<", 55), ("パワー", ">", 70), ("肩力", ">", 72), ("走力", ">", 68), ("守備力", ">", 56)],
    "遊撃手": [("ミート", "<", 32), ("ミート", ">", 47), ("パワー", "<", 35), ("パワー", ">", 55), ("走力", "<", 64), ("守備力", "<", 49), ("守備力", ">", 64)],
    "外野手": [("走力", "<", 63), ("パワー", "<", 50), ("肩力", "<", 58)],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成選手の能力バランス検証レポートを作成します。")
    parser.add_argument("--count", type=int, default=1000, help="投手/野手 × カテゴリごとの生成人数（1000以上推奨）")
    parser.add_argument("--seed", type=int, default=202607090000, help="検証用の開始seed")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "ability_balance", help="CSV出力先ディレクトリ")
    parser.add_argument("--excel", action="store_true", help="CSVに加えてExcelファイルも出力します")
    return parser.parse_args()


def age_band(age: int) -> str:
    return pd.cut(pd.Series([age]), bins=AGE_BINS, labels=AGE_LABELS, right=True, include_lowest=True).iloc[0]


def generate_samples(count: int, base_seed: int) -> list[dict[str, Any]]:
    if count < 1000:
        print("警告: --count は1000未満です。要件確認では1000以上を指定してください。")
    master = load_master_data()
    players: list[dict[str, Any]] = []
    offset = 0
    for role in ROLES:
        for category in CATEGORIES:
            print(f"{role} / {category} 生成中", flush=True)
            for _ in range(count):
                players.append(generate_player(role, category, master, base_seed + offset))
                offset += 1
    return players


def player_power_score(row: pd.Series) -> float:
    if row["role"] == "投手":
        return sum(row[key] for key in ["球速偏差用", "コントロール", "スタミナ", "総変化量偏差用"] if pd.notna(row[key]))
    return sum(row[key] for key in FIELDING_KEYS if pd.notna(row[key]))


def flatten_players(players: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for player in players:
        abilities = player["abilities"]
        breaking_balls = player["breaking_balls"]
        primary_breaking = [ball for ball in breaking_balls if ball.get("kind", "breaking") == "breaking" and not bool(ball.get("is_second_pitch", False))]
        all_breaking = [ball for ball in breaking_balls if ball.get("kind", "breaking") == "breaking"]
        break_levels = [pitch_movement(ball) for ball in primary_breaking]
        second_balls = [ball for ball in all_breaking if bool(ball.get("is_second_pitch", False))]
        row = {key: player[key] for key in ["seed", "role", "category", "name", "age", "nationality", "birthplace", "position", "player_type", "handedness", "batting_throwing", "height", "weight"]}
        for key in CLASSIFICATION_COLUMNS:
            row[key] = player.get(key, "")
        for key in ["starter_aptitude", "reliever_aptitude", "closer_aptitude"]:
            row[key] = player.get(key) or abilities.get(key)
        row["年齢帯"] = age_band(player["age"])
        for key in FIELDING_KEYS:
            row[key] = ability_numeric_value(abilities, key)
        row["球速"] = pitcher_speed_value(abilities)
        row["球速偏差用"] = ((row["球速"] or 145) - 125) / 40 * 99 if row["球速"] else None
        row["コントロール"] = ability_numeric_value(abilities, "コントロール")
        row["スタミナ"] = ability_numeric_value(abilities, "スタミナ")
        row["総変化量"] = sum(break_levels)
        row["総変化量_第二球種込み"] = sum(pitch_movement(ball) for ball in all_breaking)
        row["総変化量_第一球種のみ"] = row["総変化量"]
        row["normal_pitch_direction_count"] = len({str(ball.get("direction", "")) for ball in primary_breaking if str(ball.get("direction", ""))})
        row["normal_pitch_count_primary_only"] = len(primary_breaking)
        row["normal_pitch_count_including_second"] = len(all_breaking)
        row["total_movement_primary_only"] = row["総変化量_第一球種のみ"]
        row["total_movement_including_second"] = row["総変化量_第二球種込み"]
        row["総変化量偏差用"] = row["総変化量"] * 8
        row["変化球数"] = len(all_breaking)
        row["変化球数_第一球種のみ"] = len(primary_breaking)
        row["pitch_type_count_including_second"] = row["変化球数"]
        row["second_pitch_count"] = len(second_balls)
        row["straight_secondary_count"] = sum(1 for ball in breaking_balls if ball.get("kind") == "second_fastball")
        row["has_second_pitch"] = bool(second_balls)
        row["second_pitch_directions"] = ",".join(str(ball.get("direction", "")) for ball in second_balls)
        row["second_pitch_movements"] = ",".join(str(pitch_movement(ball)) for ball in second_balls)
        row["breaking_ball_names"] = ",".join(str(ball.get("name", "")) for ball in breaking_balls)
        row["breaking_ball_directions"] = ",".join(str(ball.get("direction", "")) for ball in breaking_balls)
        row["breaking_ball_movements"] = ",".join(str(pitch_movement(ball)) for ball in breaking_balls)
        row["first_pitch_directions"] = ",".join(str(ball.get("direction", "")) for ball in breaking_balls if not bool(ball.get("is_second_pitch", False)))
        row["first_pitch_names"] = ",".join(str(ball.get("name", "")) for ball in breaking_balls if not bool(ball.get("is_second_pitch", False)))
        row["変化球方向"] = ",".join(f"{ball.get('direction', ball.get('name', ''))}:{ball.get('name', '')}{'(第2)' if ball.get('is_second_pitch') else ''}" for ball in breaking_balls)
        subs = player.get("sub_positions", [])
        row["サブポジ数"] = len(subs)
        row["サブポジ"] = " / ".join(f"{item['position']}{item['aptitude']}" for item in subs)
        row["サブポジ一覧"] = " / ".join(item["position"] for item in subs)
        row["サブポジ評価一覧"] = " / ".join(item["aptitude"] for item in subs)
        row["サブポジJSON"] = str(subs)
        row["特殊能力"] = ",".join(player["special_abilities"])
        row["ランク系特殊能力"] = ",".join(player["abilities"].get("ranked_specials", {}).values())
        row["特殊能力数"] = len(player["special_abilities"])
        row["金特数"] = 0
        row["赤特数"] = 0
        rows.append(row)
    df = pd.DataFrame(rows)
    df["総合スコア"] = df.apply(player_power_score, axis=1)
    return df


def ability_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_sets = [
        [], ["role"], ["category"], ["年齢帯"], ["position"], ["player_class"], ["archetype"],
        ["position_style"], ["development_stage"], ["acquisition_role"], ["weakness_profile"],
        ["role", "category"], ["category", "年齢帯"], ["category", "position"], ["category", "player_class"],
        ["category", "archetype"], ["category", "position_style"],
    ]
    for role, keys in [("野手", FIELDING_KEYS), ("投手", PITCHING_KEYS)]:
        role_df = df[df["role"] == role].copy()
        for groups in group_sets:
            if groups:
                grouped = role_df.groupby(groups, dropna=False)
            else:
                grouped = [((), role_df)]
            for group_value, subset in grouped:
                if not isinstance(group_value, tuple):
                    group_value = (group_value,)
                group_labels = {column: value for column, value in zip(groups, group_value, strict=False)}
                for key in keys:
                    values = pd.to_numeric(subset[key], errors="coerce").dropna()
                    rows.append({
                        "対象": role,
                        "集計軸": "+".join(groups) if groups else "全体",
                        "集計値": " / ".join(f"{k}={v}" for k, v in group_labels.items()) if group_labels else "全体",
                        "能力": key,
                        "人数": int(values.count()),
                        "平均": round(values.mean(), 3) if not values.empty else None,
                        "中央値": round(values.median(), 3) if not values.empty else None,
                        "標準偏差": round(values.std(), 3) if len(values) > 1 else 0,
                        "P10": round(values.quantile(0.10), 3) if not values.empty else None,
                        "P25": round(values.quantile(0.25), 3) if not values.empty else None,
                        "P50": round(values.quantile(0.50), 3) if not values.empty else None,
                        "P75": round(values.quantile(0.75), 3) if not values.empty else None,
                        "P90": round(values.quantile(0.90), 3) if not values.empty else None,
                        "P95": round(values.quantile(0.95), 3) if not values.empty else None,
                        "最大": values.max() if not values.empty else None,
                        "最小": values.min() if not values.empty else None,
                        "S率%": round((values >= 90).mean() * 100, 3) if not values.empty else None,
                        "A以上率%": round((values >= 80).mean() * 100, 3) if not values.empty else None,
                        "G率%": round((values < 20).mean() * 100, 3) if not values.empty else None,
                    })
    return pd.DataFrame(rows)


def special_stats(players: list[dict[str, Any]], df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    master = load_master_data()
    kind_by_name = {row["name"]: SPECIAL_KIND_LABELS.get(row.get("kind"), "不明") for row in master.abilities if not is_ranked_special(row)}
    for i, player in enumerate(players):
        df.loc[i, "金特数"] = sum(1 for name in player["special_abilities"] if kind_by_name.get(name) == "金特")
        df.loc[i, "赤特数"] = sum(1 for name in player["special_abilities"] if kind_by_name.get(name) == "赤特")
    rows = []
    name_rows = []
    ranked_rows = []
    scopes = [("全体", df.index), *[(f"投手/野手={v}", df[df["role"] == v].index) for v in ROLES], *[(f"カテゴリ={v}", df[df["category"] == v].index) for v in CATEGORIES]]
    for label, index in scopes:
        subset_players = [players[i] for i in index]
        total_players = len(subset_players) or 1
        kind_counts = Counter(kind_by_name.get(name, "不明") for p in subset_players for name in p["special_abilities"])
        ranked_count = sum(len(p["abilities"].get("ranked_specials", {})) for p in subset_players)
        for kind in SPECIAL_KIND_ORDER:
            rows.append({"集計軸": label, "種別": kind, "出現数": kind_counts.get(kind, 0), "出現率%": round(kind_counts.get(kind, 0) / total_players * 100, 2)})
        rows.append({"集計軸": label, "種別": "ランク系", "出現数": ranked_count, "出現率%": round(ranked_count / total_players * 100, 2)})
        name_counts = Counter(name for p in subset_players for name in p["special_abilities"])
        for name, count in name_counts.items():
            name_rows.append({"集計軸": label, "特殊能力": name, "種別": kind_by_name.get(name, "不明"), "出現数": count, "出現率%": round(count / total_players * 100, 2)})
        ranked_counts = Counter(name for p in subset_players for name in p["abilities"].get("ranked_specials", {}).values())
        for name, count in ranked_counts.items():
            ranked_rows.append({"集計軸": label, "ランク系特殊能力": name, "ランク": name[-1:], "出現数": count, "出現率%": round(count / total_players * 100, 2)})
    return pd.DataFrame(rows), pd.DataFrame(name_rows), pd.DataFrame(ranked_rows)



def aptitude_pattern(row: pd.Series) -> str:
    return f"先発{row.get('starter_aptitude', '-') or '-'} / 中継ぎ{row.get('reliever_aptitude', '-') or '-'} / 抑え{row.get('closer_aptitude', '-') or '-'}"


def pitcher_aptitude_summary(df: pd.DataFrame) -> pd.DataFrame:
    pitchers = df[df["role"] == "投手"].copy()
    if pitchers.empty:
        return pd.DataFrame()
    pitchers["適正パターン"] = pitchers.apply(aptitude_pattern, axis=1)
    rows = [
        {"集計軸": "先発◎人数", "値": "◎", "人数": int((pitchers["starter_aptitude"] == "◎").sum())},
        {"集計軸": "中継ぎ◎人数", "値": "◎", "人数": int((pitchers["reliever_aptitude"] == "◎").sum())},
        {"集計軸": "抑え◎人数", "値": "◎", "人数": int((pitchers["closer_aptitude"] == "◎").sum())},
        {"集計軸": "先発○人数", "値": "○", "人数": int((pitchers["starter_aptitude"] == "○").sum())},
        {"集計軸": "中継ぎ○人数", "値": "○", "人数": int((pitchers["reliever_aptitude"] == "○").sum())},
        {"集計軸": "抑え○人数", "値": "○", "人数": int((pitchers["closer_aptitude"] == "○").sum())},
    ]
    for pattern, subset in pitchers.groupby("適正パターン", dropna=False):
        rows.append({
            "集計軸": "適正パターン別", "値": pattern, "人数": int(len(subset)),
            "平均球速": round(pd.to_numeric(subset["球速"], errors="coerce").mean(), 3),
            "平均コントロール": round(pd.to_numeric(subset["コントロール"], errors="coerce").mean(), 3),
            "平均スタミナ": round(pd.to_numeric(subset["スタミナ"], errors="coerce").mean(), 3),
            "平均球種数": round(pd.to_numeric(subset["pitch_type_count_including_second"], errors="coerce").mean(), 3),
            "平均総変化量": round(pd.to_numeric(subset["total_movement_including_second"], errors="coerce").mean(), 3),
            "第二球種率%": round(subset["has_second_pitch"].mean() * 100, 2),
        })
    return pd.DataFrame(rows)


def second_pitch_summary(df: pd.DataFrame) -> pd.DataFrame:
    pitchers = df[df["role"] == "投手"].copy()
    if pitchers.empty:
        return pd.DataFrame()
    rows = [{"集計軸": "全体", "値": "第二球種あり", "人数": int(pitchers["has_second_pitch"].sum()), "割合%": round(pitchers["has_second_pitch"].mean() * 100, 2)}]
    for col, label in [("starter_aptitude", "先発適正"), ("reliever_aptitude", "中継ぎ適正"), ("closer_aptitude", "抑え適正"), ("category", "カテゴリ")]:
        for value, subset in pitchers.groupby(col, dropna=False):
            rows.append({"集計軸": label, "値": value, "人数": int(subset["has_second_pitch"].sum()), "割合%": round(subset["has_second_pitch"].mean() * 100, 2)})
    directions = pitchers["second_pitch_directions"].fillna("").astype(str).str.split(",").explode()
    directions = directions[directions.ne("")]
    for direction, count in directions.value_counts().items():
        rows.append({"集計軸": "第二球種方向", "値": direction, "人数": int(count), "割合%": None})
    movements = pd.to_numeric(pitchers["second_pitch_movements"].fillna("").astype(str).str.split(",").explode(), errors="coerce").dropna().astype(int)
    for movement, count in movements.value_counts().sort_index().items():
        rows.append({"集計軸": "第二球種変化量", "値": movement, "人数": int(count), "割合%": None})
    return pd.DataFrame(rows)


def aptitude_groups(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    pitchers = df[df["role"] == "投手"].copy()
    groups: list[tuple[str, pd.DataFrame]] = [("全体", pitchers)]
    for category, subset in pitchers.groupby("category", dropna=False):
        groups.append((f"カテゴリ={category}", subset))
    for key, label in [("starter_aptitude", "先発"), ("reliever_aptitude", "中継ぎ"), ("closer_aptitude", "抑え")]:
        for value, subset in pitchers.groupby(key, dropna=False):
            groups.append((f"{label}適正={value}", subset))
    for (category, pattern), subset in pitchers.assign(適正パターン=pitchers.apply(aptitude_pattern, axis=1)).groupby(["category", "適正パターン"], dropna=False):
        groups.append((f"カテゴリ={category} / {pattern}", subset))
    return groups


def breaking_pitch_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, subset in aptitude_groups(df):
        total_players = max(1, len(subset))
        names = subset["breaking_ball_names"].fillna("").astype(str).str.split(",").explode().str.strip()
        names = names[names.ne("")]
        for name, count in names.value_counts().items():
            rows.append({"集計軸": label, "球種": name, "出現数": int(count), "投手あたり出現率%": round(count / total_players * 100, 2)})
    return pd.DataFrame(rows)


def breaking_direction_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, subset in aptitude_groups(df):
        total_players = max(1, len(subset))
        for kind, column in [("第一球種", "first_pitch_directions"), ("第二球種", "second_pitch_directions")]:
            directions = subset[column].fillna("").astype(str).str.split(",").explode().str.strip()
            directions = directions[directions.ne("")]
            for direction, count in directions.value_counts().items():
                rows.append({"集計軸": label, "種別": kind, "方向": direction, "出現数": int(count), "投手あたり出現率%": round(count / total_players * 100, 2)})
    return pd.DataFrame(rows)


def distribution_summary(df: pd.DataFrame, column: str, label: str) -> pd.DataFrame:
    rows = []
    for group_label, subset in aptitude_groups(df):
        values = pd.to_numeric(subset[column], errors="coerce")
        total = max(1, values.notna().sum())
        for value, count in values.value_counts(dropna=False).sort_index().items():
            rows.append({"集計軸": group_label, "分布": label, "値": value, "人数": int(count), "割合%": round(count / total * 100, 2)})
        rows.append({"集計軸": group_label, "分布": f"{label}サマリー", "値": "平均", "人数": int(total), "割合%": round(values.mean(), 3) if total else None})
    return pd.DataFrame(rows)


def sub_position_summary(df: pd.DataFrame) -> pd.DataFrame:
    f = df[df["role"] == "野手"].copy()
    rows = []
    if f.empty:
        return pd.DataFrame(rows)
    total = len(f)
    rows.append({"集計軸": "全体", "値": "サブポジ保有率", "人数": int((f["サブポジ数"] > 0).sum()), "割合%": round((f["サブポジ数"] > 0).mean() * 100, 2)})
    for label, count in f["サブポジ数"].clip(upper=3).map({0:"0個",1:"1個",2:"2個",3:"3個以上"}).value_counts().items():
        rows.append({"集計軸": "サブポジ数分布", "値": label, "人数": int(count), "割合%": round(count / total * 100, 2)})
    for pos, sub in f.groupby("position"):
        rows.append({"集計軸": "メインポジション別保有率", "値": pos, "人数": int((sub["サブポジ数"] > 0).sum()), "割合%": round((sub["サブポジ数"] > 0).mean() * 100, 2)})
    items = []
    for _, row in f.iterrows():
        for part, apt in zip(str(row["サブポジ一覧"]).split(" / ") if row["サブポジ一覧"] else [], str(row["サブポジ評価一覧"]).split(" / ") if row["サブポジ評価一覧"] else [], strict=False):
            if part: items.append((row["position"], part, apt))
    for subpos, count in Counter(p for _, p, _ in items).items():
        rows.append({"集計軸": "サブポジ別出現数", "値": subpos, "人数": int(count), "割合%": round(count / total * 100, 2)})
    for apt, count in Counter(a for _, _, a in items).items():
        rows.append({"集計軸": "適性評価別出現数", "値": apt, "人数": int(count), "割合%": round(count / max(1, len(items)) * 100, 2)})
    left_bad = f[f["batting_throwing"].str.startswith("左投") & f["サブポジ一覧"].str.contains("二塁手|三塁手|遊撃手", regex=True, na=False)]
    rows.append({"集計軸": "警告チェック", "値": "左投げ野手の二三遊サブ", "人数": int(len(left_bad)), "割合%": round(len(left_bad) / total * 100, 2)})
    catcher_sub = f["サブポジ一覧"].str.contains("捕手", na=False).sum()
    rows.append({"集計軸": "警告チェック", "値": "捕手サブ出現率", "人数": int(catcher_sub), "割合%": round(catcher_sub / total * 100, 2)})
    return pd.DataFrame(rows)


def position_balance_summary(df: pd.DataFrame) -> pd.DataFrame:
    f = df[(df["role"] == "野手") & (df["category"] == "架空球団用")].copy()
    rows = []
    for position, subset in f.groupby("position"):
        for key in ["弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"]:
            actual = pd.to_numeric(subset[key], errors="coerce").mean()
            real = REAL_POSITION_AVERAGES.get(position, {}).get(key)
            rows.append({
                "カテゴリ": "架空球団用",
                "ポジション": position,
                "能力": key,
                "人数": int(len(subset)),
                "生成平均": round(actual, 3),
                "実在平均": real,
                "差分": round(actual - real, 3) if real is not None else None,
            })
    return pd.DataFrame(rows)


def warning_severity(diff: float | None, threshold_gap: float) -> str:
    if diff is None:
        return "info"
    abs_diff = abs(diff)
    if abs_diff >= 8 or threshold_gap >= 4:
        return "high"
    if abs_diff >= 5 or threshold_gap >= 2:
        return "medium"
    return "low"


def position_balance_warnings(df: pd.DataFrame) -> pd.DataFrame:
    summary = position_balance_summary(df)
    rows = []
    for position, rules in POSITION_WARNING_RULES.items():
        for ability_name, op, threshold in rules:
            match = summary[(summary["ポジション"] == position) & (summary["能力"] == ability_name)]
            if match.empty:
                continue
            item = match.iloc[0]
            avg = float(item["生成平均"])
            triggered = avg > threshold if op == ">" else avg < threshold
            if triggered:
                gap = avg - threshold if op == ">" else threshold - avg
                diff = item.get("差分")
                rows.append({"ポジション": position, "能力": ability_name, "平均": avg, "実在平均": item.get("実在平均"), "差分": diff, "条件": f"{op}{threshold}", "severity": warning_severity(float(diff) if pd.notna(diff) else None, float(gap)), "警告": "警告"})
    return pd.DataFrame(rows, columns=["ポジション", "能力", "平均", "実在平均", "差分", "条件", "severity", "警告"])


def position_high_ability_rates(df: pd.DataFrame) -> pd.DataFrame:
    f = df[(df["role"] == "野手") & (df["category"] == "架空球団用")].copy()
    checks = {
        "捕手": [("ミート50以上", "ミート", 50), ("ミート60以上", "ミート", 60), ("守備力55以上", "守備力", 55), ("守備力65以上", "守備力", 65)],
        "二塁手": [("走力60以上", "走力", 60), ("走力70以上", "走力", 70)],
        "遊撃手": [("走力60以上", "走力", 60), ("走力70以上", "走力", 70), ("パワー60以上", "パワー", 60), ("パワー65以上", "パワー", 65)],
        "一塁手": [("パワー65以上", "パワー", 65)],
        "三塁手": [("パワー65以上", "パワー", 65)],
        "外野手": [("パワー65以上", "パワー", 65)],
    }
    rows = []
    for position, items in checks.items():
        subset = f[f["position"] == position]
        total = max(1, len(subset))
        for label, key, threshold in items:
            count = int((pd.to_numeric(subset[key], errors="coerce") >= threshold).sum())
            rows.append({"ポジション": position, "指標": label, "人数": count, "対象人数": int(len(subset)), "割合%": round(count / total * 100, 2)})
    return pd.DataFrame(rows)


def position_distribution_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    f = df[df["role"] == "野手"].copy()
    rows = []
    for (category, position), subset in f.groupby(["category", "position"], dropna=False):
        total = max(1, len(subset))
        for key in FIELDING_KEYS:
            values = pd.to_numeric(subset[key], errors="coerce").dropna()
            if values.empty:
                continue
            row = {
                "カテゴリ": category,
                "ポジション": position,
                "能力": key,
                "人数": int(len(values)),
                "平均": round(values.mean(), 3),
                "標準偏差": round(values.std(), 3) if len(values) > 1 else 0,
            }
            if key == "弾道":
                for trajectory in [1, 2, 3, 4]:
                    row[f"弾道{trajectory}割合%"] = round((values == trajectory).sum() / total * 100, 2)
            else:
                row.update({
                    "下位割合_39以下%": round((values <= 39).sum() / total * 100, 2),
                    "上位割合_70以上%": round((values >= 70).sum() / total * 100, 2),
                    "極上位割合_80以上%": round((values >= 80).sum() / total * 100, 2),
                })
            rows.append(row)
    return pd.DataFrame(rows)


def position_extreme_examples(df: pd.DataFrame) -> pd.DataFrame:
    f = df[df["role"] == "野手"].copy()
    rows = []
    for position, subset in f.groupby("position", dropna=False):
        for label, order in [("総合上位", False), ("総合下位", True)]:
            for _, row in subset.sort_values("総合スコア", ascending=order).head(3).iterrows():
                rows.append({
                    "ポジション": position,
                    "例種別": label,
                    "seed": row["seed"],
                    "カテゴリ": row["category"],
                    "年齢": row["age"],
                    "タイプ": row["player_type"],
                    "総合スコア": round(row["総合スコア"], 1),
                    "能力": " / ".join(f"{key}{int(row[key])}" for key in FIELDING_KEYS if pd.notna(row[key])),
                })
    return pd.DataFrame(rows)


def combination_warnings(df: pd.DataFrame) -> pd.DataFrame:
    f = df[df["role"] == "野手"].copy()
    strict = f["category"].eq("架空球団用")
    loose = f["category"].ne("架空球団用")
    rules = [
        ("捕手の打撃過多", (f["position"].eq("捕手")) & (f["ミート"] >= 65) & (f["パワー"] >= 70) & (f["守備力"] < 50)),
        ("捕手の守備不足", (f["position"].eq("捕手")) & (((strict) & ((f["肩力"] < 50) | (f["守備力"] < 42) | (f["捕球"] < 40))) | ((loose) & ((f["肩力"] < 46) | (f["守備力"] < 38) | (f["捕球"] < 35))))),
        ("一塁手の非力すぎ", (f["position"].eq("一塁手")) & (f["パワー"] < 42) & (f[["ミート", "守備力", "捕球"]].max(axis=1) < 50) & strict),
        ("二塁手の守備走力不足", (f["position"].eq("二塁手")) & (((f["走力"] < 46) | (f["守備力"] < 44) | (f["肩力"] < 40)) & (f["パワー"] < 58)) & strict),
        ("三塁手の肩不足", (f["position"].eq("三塁手")) & (f["肩力"] < 48) & (f["パワー"] < 65) & strict),
        ("遊撃手の守備不足", (f["position"].eq("遊撃手")) & (((f["守備力"] < 44) | (f["肩力"] < 48) | (f["走力"] < 48)) & strict)),
        ("外野手の走肩守不足", (f["position"].eq("外野手")) & (f[["走力", "肩力", "守備力"]].max(axis=1) < 53) & (f["パワー"] < 65) & strict),
        ("高齢選手の走守肩過多", (f["age"] >= 35) & (f["走力"] >= 75) & (f["守備力"] >= 70) & (f["肩力"] >= 75)),
        ("若手の完成度過多", (f["age"] <= 22) & (f["総合スコア"] >= 455) & ~(f["category"].eq("ドラフト候補用") & (f[["パワー", "走力", "肩力"]].max(axis=1) >= 85))),
    ]
    rows = []
    for name, mask in rules:
        subset = f[mask]
        for _, row in subset.head(30).iterrows():
            rows.append({
                "警告タイプ": name,
                "severity": "medium" if row["category"] == "架空球団用" else "low",
                "seed": row["seed"],
                "カテゴリ": row["category"],
                "ポジション": row["position"],
                "年齢": row["age"],
                "タイプ": row["player_type"],
                "能力": " / ".join(f"{key}{int(row[key])}" for key in FIELDING_KEYS if pd.notna(row[key])),
            })
    return pd.DataFrame(rows)

def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    pitchers = df[df["role"] == "投手"]
    checks = [
        ("中継ぎ- / 抑え◎", pitchers[(pitchers["reliever_aptitude"] == "-") & (pitchers["closer_aptitude"] == "◎")]),
        ("中継ぎ- / 抑え○", pitchers[(pitchers["reliever_aptitude"] == "-") & (pitchers["closer_aptitude"] == "○")]),
        ("先発◎ / 中継ぎ- / 抑え◎", pitchers[(pitchers["starter_aptitude"] == "◎") & (pitchers["reliever_aptitude"] == "-") & (pitchers["closer_aptitude"] == "◎")]),
        ("全部-", pitchers[(pitchers["starter_aptitude"] == "-") & (pitchers["reliever_aptitude"] == "-") & (pitchers["closer_aptitude"] == "-")]),
        ("◎が1つもない投手", pitchers[(pitchers[["starter_aptitude", "reliever_aptitude", "closer_aptitude"]] == "◎").sum(axis=1) == 0]),
        ("投手の球種が極端に少ない", df[(df["role"] == "投手") & (df["変化球数"] <= 1)]),
        ("投手の総変化量が極端に低い", df[(df["role"] == "投手") & (df["総変化量"] <= 2)]),
        ("投手の球種数が極端に多い", df[(df["role"] == "投手") & (df["変化球数"] >= 5)]),
        ("第二球種あり投手の総変化量が極端に高い", df[(df["role"] == "投手") & (df["has_second_pitch"]) & (df["total_movement_including_second"] >= 13)]),
        ("遊撃手なのに守備・捕球が極端に低い", df[(df["position"] == "遊撃手") & ((df["守備力"] < 40) | (df["捕球"] < 35))]),
        ("捕手なのに肩力・守備・捕球が極端に低い", df[(df["position"] == "捕手") & ((df["肩力"] < 45) | (df["守備力"] < 40) | (df["捕球"] < 35))]),
        ("高卒新人で完成されすぎた能力", df[(df["category"] == "ドラフト候補用") & (df["age"] <= 18) & (df["総合スコア"] >= 410)]),
        ("35歳以上で能力が高すぎる", df[(df["age"] >= 35) & (df["総合スコア"] >= 430)]),
        ("金特が出すぎる可能性", df[df["金特数"] >= 1]),
        ("赤特が強い選手に付きすぎる", df[(df["赤特数"] >= 1) & (df["総合スコア"] >= 430)]),
    ]
    direction = df[df["role"] == "投手"]["変化球方向"].str.split(",").explode().value_counts(normalize=True)
    rows = []
    for name, subset in checks:
        rows.append({"異常タイプ": name, "件数": len(subset), "割合%": round(len(subset) / len(df) * 100, 2), "例seed": ",".join(map(str, subset["seed"].head(10).tolist()))})
    if not direction.empty and direction.iloc[0] >= 0.35:
        rows.append({"異常タイプ": f"投手の球種方向が偏りすぎ: {direction.index[0]}", "件数": int(direction.iloc[0] * len(df[df['role'] == '投手'])), "割合%": round(direction.iloc[0] * 100, 2), "例seed": ""})
    try:
        from app import BREAKING_BY_NAME, BREAKING_DIRECTIONS
        known_names = set(BREAKING_BY_NAME)
        known_directions = set(BREAKING_DIRECTIONS)
    except Exception:
        known_names, known_directions = set(), set()
    unknown_names = df[df["role"].eq("投手")]["breaking_ball_names"].fillna("").astype(str).str.split(",").explode().str.strip()
    unknown_names = unknown_names[unknown_names.ne("") & ~unknown_names.isin(known_names)]
    if not unknown_names.empty:
        rows.append({"異常タイプ": "未登録球種", "件数": int(len(unknown_names)), "割合%": None, "例seed": ",".join(unknown_names.head(10).tolist())})
    unknown_dirs = df[df["role"].eq("投手")]["breaking_ball_directions"].fillna("").astype(str).str.split(",").explode().str.strip()
    unknown_dirs = unknown_dirs[unknown_dirs.ne("") & ~unknown_dirs.isin(known_directions)]
    if not unknown_dirs.empty:
        rows.append({"異常タイプ": "不明方向", "件数": int(len(unknown_dirs)), "割合%": None, "例seed": ",".join(unknown_dirs.head(10).tolist())})

    def split_values(row: pd.Series, column: str) -> list[str]:
        return [value for value in str(row.get(column, "") or "").split(",") if value]

    second_alone_seeds = []
    three_same_direction_seeds = []
    second_excess_seeds = []
    for _, row in pitchers.iterrows():
        first_dirs = split_values(row, "first_pitch_directions")
        second_dirs = split_values(row, "second_pitch_directions")
        all_dirs = split_values(row, "breaking_ball_directions")
        if any(direction not in first_dirs for direction in second_dirs):
            second_alone_seeds.append(row["seed"])
        if any(count >= 3 for count in Counter(all_dirs).values()):
            three_same_direction_seeds.append(row["seed"])
        first_max = Counter()
        for direction, movement in zip(first_dirs, split_values(row, "breaking_ball_movements")[:len(first_dirs)], strict=False):
            first_max[direction] = max(first_max[direction], int(movement or 0))
        second_movements = split_values(row, "second_pitch_movements")
        for direction, movement in zip(second_dirs, second_movements, strict=False):
            if int(movement or 0) > first_max.get(direction, 0) + 1:
                second_excess_seeds.append(row["seed"])
                break
    for anomaly_name, seeds in [("第二球種単独", second_alone_seeds), ("同一方向3球種以上", three_same_direction_seeds), ("第二球種変化量過大", second_excess_seeds)]:
        rows.append({"異常タイプ": anomaly_name, "件数": len(seeds), "割合%": round(len(seeds) / max(1, len(df)) * 100, 2), "例seed": ",".join(map(str, seeds[:10]))})

    bad_movements = pitchers[pitchers["breaking_ball_movements"].fillna("").astype(str).str.contains(r"(?:^|,)(?:0|8|9|10)(?:,|$)", regex=True)]
    rows.append({"異常タイプ": "不明変化量", "件数": int(len(bad_movements)), "割合%": round(len(bad_movements) / max(1, len(df)) * 100, 2), "例seed": ",".join(map(str, bad_movements["seed"].head(10).tolist()))})
    return pd.DataFrame(rows)


def write_reports(tables: dict[str, pd.DataFrame], output_dir: Path, excel: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    print("CSV出力中", flush=True)
    for key, table in tables.items():
        table.to_csv(output_dir / REPORT_FILENAMES[key], index=False, encoding="utf-8-sig")
    if excel:
        print("Excel出力中", flush=True)
        with pd.ExcelWriter(output_dir / "ability_balance_report.xlsx") as writer:
            for key, table in tables.items():
                table.to_excel(writer, sheet_name=key[:31], index=False)
    write_markdown_summary(tables, output_dir / "summary.md")


def write_markdown_summary(tables: dict[str, pd.DataFrame], path: Path) -> None:
    position_summary = tables["position_balance_summary"]
    pivot = position_summary.pivot(index="ポジション", columns="能力", values="生成平均").reset_index()
    diff = position_summary.pivot(index="ポジション", columns="能力", values="差分").reset_index()
    warnings = tables["position_balance_warnings"]
    rates = tables["position_high_ability_rates"]
    sub_warnings = tables["sub_position_summary"][tables["sub_position_summary"]["集計軸"].eq("警告チェック")]
    age_stats = tables["ability_stats"][tables["ability_stats"]["集計軸"].eq("年齢帯") & tables["ability_stats"]["対象"].isin(["野手", "投手"])]
    category_stats = tables["ability_stats"][tables["ability_stats"]["集計軸"].eq("category") & tables["ability_stats"]["対象"].isin(["野手", "投手"])]
    distributions = tables["position_distribution_diagnostics"]
    extremes = tables["position_extreme_examples"]
    combo_warnings = tables["combination_warnings"]

    def markdown_table(table: pd.DataFrame) -> str:
        if table.empty:
            return "（なし）"
        text = table.fillna("").astype(str)
        columns = list(text.columns)
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for _, row in text.iterrows():
            lines.append("| " + " | ".join(str(row[col]).replace("|", "\\|") for col in columns) + " |")
        return "\n".join(lines)

    lines = [
        "# 能力バランス検証サマリー",
        "",
        "## 架空球団用1000人のポジション別能力平均",
        "",
        markdown_table(pivot),
        "",
        "## 実在データとの差分（生成平均 - 実在平均）",
        "",
        markdown_table(diff),
        "",
        "## ポジション別の警告一覧",
        "",
        "警告なし" if warnings.empty else markdown_table(warnings),
        "",
        "## 高能力者割合",
        "",
        markdown_table(rates),
        "",
        "## 年齢帯別の能力平均",
        "",
        markdown_table(age_stats[["対象", "集計値", "能力", "人数", "平均"]].head(80)),
        "",
        "## カテゴリ別の能力平均",
        "",
        markdown_table(category_stats[["対象", "集計値", "能力", "人数", "平均"]].head(80)),
        "",
        "## ポジション別の能力分布・上位割合・下位割合",
        "",
        markdown_table(distributions[distributions["カテゴリ"].eq("架空球団用")].head(80)),
        "",
        "## ポジション別の極端な選手例",
        "",
        markdown_table(extremes.head(60)),
        "",
        "## 能力の組み合わせが不自然な選手の警告",
        "",
        "警告なし" if combo_warnings.empty else markdown_table(combo_warnings.head(80)),
        "",
        "## サブポジ警告",
        "",
        markdown_table(sub_warnings),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def print_console_summary(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    print("=== 能力バランス検証サマリー ===")
    print(f"出力先: {output_dir}")
    print("\n[能力統計: 全体]")
    print(tables["ability_stats"][tables["ability_stats"]["集計軸"] == "全体"].to_string(index=False))
    print("\n[特殊能力種別: 全体]")
    print(tables["special_kind_stats"][tables["special_kind_stats"]["集計軸"] == "全体"].to_string(index=False))
    print("\n[投手適正サマリー]")
    print(tables["pitcher_aptitude_summary"].to_string(index=False))
    print("\n[サブポジ集計]")
    print(tables["sub_position_summary"].to_string(index=False))
    print("\n[ポジション別能力警告]")
    if tables["position_balance_warnings"].empty:
        print("警告なし")
    else:
        print(tables["position_balance_warnings"].to_string(index=False))
    print("\n[異常値検出]")
    print(tables["anomalies"].to_string(index=False))


def main() -> None:
    args = parse_args()
    players = generate_samples(args.count, args.seed)
    df = flatten_players(players)
    special_kind, special_name, ranked_special = special_stats(players, df)
    tables = {
        "players": df,
        "ability_stats": ability_stats(df),
        "special_kind_stats": special_kind,
        "special_name_stats": special_name,
        "ranked_special_stats": ranked_special,
        "anomalies": detect_anomalies(df),
        "pitcher_aptitude_summary": pitcher_aptitude_summary(df),
        "second_pitch_summary": second_pitch_summary(df),
        "breaking_pitch_summary": breaking_pitch_summary(df),
        "breaking_direction_summary": breaking_direction_summary(df),
        "pitch_count_distribution": distribution_summary(df, "normal_pitch_count_primary_only", "通常球種数_第一球種のみ"),
        "total_movement_distribution": distribution_summary(df, "total_movement_primary_only", "総変化量_第一球種のみ"),
        "sub_position_summary": sub_position_summary(df),
        "position_balance_summary": position_balance_summary(df),
        "position_balance_warnings": position_balance_warnings(df),
        "position_high_ability_rates": position_high_ability_rates(df),
        "position_distribution_diagnostics": position_distribution_diagnostics(df),
        "position_extreme_examples": position_extreme_examples(df),
        "combination_warnings": combination_warnings(df),
    }
    write_reports(tables, args.output_dir, args.excel)
    print_console_summary(tables, args.output_dir)
    print("完了", flush=True)


if __name__ == "__main__":
    main()
