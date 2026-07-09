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
    SPECIAL_KIND_LABELS,
    SPECIAL_KIND_ORDER,
    ability_numeric_value,
    generate_player,
    is_ranked_special,
    load_master_data,
    pitcher_speed_value,
)

ROLES = ["投手", "野手"]
FIELDING_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球", "弾道"]
PITCHING_KEYS = ["球速", "コントロール", "スタミナ", "総変化量", "変化球数"]
AGE_BINS = [0, 19, 22, 26, 30, 34, 99]
AGE_LABELS = ["18-19歳", "20-22歳", "23-26歳", "27-30歳", "31-34歳", "35歳以上"]
REPORT_FILENAMES = {
    "players": "generated_players.csv",
    "ability_stats": "ability_stats.csv",
    "special_kind_stats": "special_kind_stats.csv",
    "special_name_stats": "special_name_stats.csv",
    "ranked_special_stats": "ranked_special_stats.csv",
    "anomalies": "anomalies.csv",
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
        break_levels = [int(ball.get("level", 0) or 0) for ball in breaking_balls]
        row = {key: player[key] for key in ["seed", "role", "category", "name", "age", "nationality", "birthplace", "position", "player_type", "handedness", "batting_throwing", "height", "weight"]}
        row["年齢帯"] = age_band(player["age"])
        for key in FIELDING_KEYS:
            row[key] = ability_numeric_value(abilities, key)
        row["球速"] = pitcher_speed_value(abilities)
        row["球速偏差用"] = ((row["球速"] or 145) - 125) / 40 * 99 if row["球速"] else None
        row["コントロール"] = ability_numeric_value(abilities, "コントロール")
        row["スタミナ"] = ability_numeric_value(abilities, "スタミナ")
        row["総変化量"] = sum(break_levels)
        row["総変化量偏差用"] = row["総変化量"] * 8
        row["変化球数"] = len(breaking_balls)
        row["変化球方向"] = ",".join(ball.get("name", "") for ball in breaking_balls)
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
    group_sets = [[], ["role"], ["category"], ["年齢帯"], ["position"], ["role", "category"], ["category", "年齢帯"], ["category", "position"]]
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
                        "最大": values.max() if not values.empty else None,
                        "最小": values.min() if not values.empty else None,
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


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    checks = [
        ("投手の球種が極端に少ない", df[(df["role"] == "投手") & (df["変化球数"] <= 1)]),
        ("投手の総変化量が極端に低い", df[(df["role"] == "投手") & (df["総変化量"] <= 2)]),
        ("投手の球種数が極端に多い", df[(df["role"] == "投手") & (df["変化球数"] >= 5)]),
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
    return pd.DataFrame(rows)


def write_reports(tables: dict[str, pd.DataFrame], output_dir: Path, excel: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, table in tables.items():
        table.to_csv(output_dir / REPORT_FILENAMES[key], index=False, encoding="utf-8-sig")
    if excel:
        with pd.ExcelWriter(output_dir / "ability_balance_report.xlsx") as writer:
            for key, table in tables.items():
                table.to_excel(writer, sheet_name=key[:31], index=False)


def print_console_summary(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    print("=== 能力バランス検証サマリー ===")
    print(f"出力先: {output_dir}")
    print("\n[能力統計: 全体]")
    print(tables["ability_stats"][tables["ability_stats"]["集計軸"] == "全体"].to_string(index=False))
    print("\n[特殊能力種別: 全体]")
    print(tables["special_kind_stats"][tables["special_kind_stats"]["集計軸"] == "全体"].to_string(index=False))
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
    }
    write_reports(tables, args.output_dir, args.excel)
    print_console_summary(tables, args.output_dir)


if __name__ == "__main__":
    main()
