from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    FIELDER_ABILITY_KEYS,
    PITCHER_APTITUDE_KEYS,
    SECOND_FASTBALL_TYPES,
    USAGE_SPECIAL_NAMES,
    ability_numeric_value,
    generate_player,
    load_master_data,
    pitch_movement,
    pitcher_speed_value,
)

DATASET_REAL = "実在12球団"
DATASET_BEFORE = "修正前架空"
DATASET_CURRENT = "現在架空"
DATASET_AFTER = "追加調整後架空"

FIELDER_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
PITCHER_KEYS = ["球速", "コントロール", "スタミナ"]
SUMMARY_STATS = ["平均", "中央値", "P25", "P50", "P75", "P90", "P95", "P99", "最小", "最大", "標準偏差"]
AGE_BINS = [0, 21, 24, 29, 34, 99]
AGE_LABELS = ["18-21歳", "22-24歳", "25-29歳", "30-34歳", "35歳以上"]
SPECIAL_FOCUS_PITCHER = [
    "球速安定", "リリース○", "奪三振", "四球", "抜け球", "球持ち○", "逃げ球", "内角攻め", "キレ○",
    "荒れ球", "スロースターター", "緩急○", "一発", "勝ち運", "ストライク先行", "乱調", "尻上がり", "寸前", "要所○",
]
SPECIAL_FOCUS_FIELDER = [
    "三振", "サヨナラ男", "内野安打○", "固め打ち", "満塁男", "流し打ち", "決勝打", "バント○",
    "死球集中", "併殺", "広角打法", "ヘッドスライディング", "代打○", "プレッシャーラン", "高速チャージ",
    "ダメ押し", "チャンスメーカー", "対変化球○", "いぶし銀", "国際大会×",
]
USAGE_NAMES = set(USAGE_SPECIAL_NAMES) | {
    "おまかせ", "調子次第", "スタミナ限界", "接戦時", "リード時", "ビハインドでも", "勝利投手", "セーブ狙い",
}
SPECIAL_ALIASES = {
    "盗塁○": "盗塁〇",
    "走塁○": "走塁〇",
    "ノビ○": "ノビ〇",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="実在12球団・修正前架空・現在架空・追加調整後架空の直接比較レポートを作成します。")
    parser.add_argument("--real-xlsx", type=Path, default=ROOT / "local_data" / "real_powerpro_players.xlsx")
    parser.add_argument("--before-csv", type=Path, default=ROOT / "local_data" / "pawapuro_players_filtered_9.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_direct_balance")
    parser.add_argument("--count", type=int, default=10000, help="修正後の投手/野手ごとの生成人数")
    parser.add_argument("--seeds", nargs="+", type=int, default=[202607090000], help="修正後生成の開始seed。複数指定で複数runを集計します。")
    parser.add_argument("--skip-after-generation", action="store_true", help="追加調整後生成をスキップし、既存のafter_normalized_players.csvを再利用します。")
    return parser.parse_args()


def safe_json(value: Any, default: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        try:
            return ast.literal_eval(text)
        except Exception:
            return default


def normalize_special_name(name: Any) -> str:
    text = str(name or "").strip()
    return SPECIAL_ALIASES.get(text, text)


def split_specials(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = safe_json(value, None)
        if raw is None:
            raw = re.split(r"[,、/]", str(value or ""))
    return [normalize_special_name(name) for name in raw if normalize_special_name(name)]


def non_usage_specials(names: list[str]) -> list[str]:
    return [name for name in names if name and name not in USAGE_NAMES]


def rank_is_non_d(name: str) -> bool:
    return bool(name) and str(name)[-1:] in set("ABCEFG")


def ranked_values(value: Any) -> list[str]:
    data = safe_json(value, {})
    if isinstance(data, dict):
        return [str(v) for v in data.values() if str(v)]
    if isinstance(data, list):
        return [str(v) for v in data if str(v)]
    return split_specials(value)


def age_band(age: Any) -> str:
    if pd.isna(age):
        return "年齢不明"
    return str(pd.cut(pd.Series([int(age)]), bins=AGE_BINS, labels=AGE_LABELS, right=True, include_lowest=True).iloc[0])


def pitcher_role_from_aptitudes(values: dict[str, Any]) -> str:
    if values.get("starter_aptitude") == "◎":
        return "先発"
    if values.get("reliever_aptitude") == "◎":
        return "中継ぎ"
    if values.get("closer_aptitude") == "◎":
        return "抑え"
    if values.get("starter_aptitude") == "○":
        return "先発"
    if values.get("reliever_aptitude") == "○":
        return "中継ぎ"
    if values.get("closer_aptitude") == "○":
        return "抑え"
    return "不明"


def real_pitcher_role(text: Any) -> str:
    value = str(text or "")
    if "先" in value:
        return "先発"
    if "中" in value:
        return "中継ぎ"
    if "抑" in value:
        return "抑え"
    return "不明"


def generated_pitch_metrics(balls: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [ball for ball in balls if ball.get("kind", "breaking") == "breaking" and not bool(ball.get("is_second_pitch", False))]
    second = [ball for ball in balls if ball.get("kind", "breaking") == "breaking" and bool(ball.get("is_second_pitch", False))]
    straight = [ball for ball in balls if ball.get("kind") == "second_fastball"]
    return {
        "通常球種数": len(primary),
        "表示球種数": len(primary) + len(second) + len(straight),
        "第二球種あり": bool(second),
        "ストレート系第二種あり": bool(straight),
        "第二球種+ストレート系第二種あり": bool(second) and bool(straight),
        "総変化量": sum(pitch_movement(ball) for ball in primary),
    }


def normalize_generated_player(player: dict[str, Any], dataset: str, run: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    abilities = player.get("abilities", {})
    role = player.get("role", "")
    balls = player.get("breaking_balls", []) or []
    specials = non_usage_specials([normalize_special_name(name) for name in player.get("special_abilities", [])])
    ranked = [normalize_special_name(name) for name in (abilities.get("ranked_specials") or {}).values()]
    row: dict[str, Any] = {
        "dataset": dataset,
        "run": run,
        "player_id": f"{dataset}:{run}:{player.get('seed')}",
        "role": role,
        "category": player.get("category", ""),
        "name": player.get("name", ""),
        "age": player.get("age"),
        "age_band": age_band(player.get("age")),
        "position": player.get("position", ""),
        "pitcher_role": player.get("position", "") if role == "投手" else "",
        "player_class": player.get("player_class", ""),
        "archetype": player.get("archetype", ""),
        "position_style": player.get("position_style", ""),
        "special_count": len(specials),
        "ranked_non_d_count": sum(1 for name in ranked if rank_is_non_d(name)),
        "special_names": "、".join(specials),
        "ranked_special_names": "、".join(ranked),
    }
    for key in FIELDER_KEYS:
        row[key] = ability_numeric_value(abilities, key)
    row["野手6能力合計"] = sum(row[key] for key in FIELDER_KEYS if pd.notna(row.get(key))) if role == "野手" else None
    row["A以上能力数"] = sum(1 for key in FIELDER_KEYS if isinstance(row.get(key), (int, float)) and row[key] >= 80) if role == "野手" else None
    row["最低能力"] = min([row[key] for key in FIELDER_KEYS if pd.notna(row.get(key))], default=None) if role == "野手" else None
    row["球速"] = pitcher_speed_value(abilities)
    row["コントロール"] = ability_numeric_value(abilities, "コントロール")
    row["スタミナ"] = ability_numeric_value(abilities, "スタミナ")
    row.update(generated_pitch_metrics(balls))
    events = [{"dataset": dataset, "run": run, "player_id": row["player_id"], "role": role, "special": name, "event_type": "normal"} for name in specials]
    events.extend({"dataset": dataset, "run": run, "player_id": row["player_id"], "role": role, "special": name, "event_type": "ranked", "non_d": rank_is_non_d(name)} for name in ranked)
    return row, events


def load_before_csv(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = pd.read_csv(path)
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for _, item in source.iterrows():
        abilities = safe_json(item.get("abilities_json"), {})
        balls = safe_json(item.get("breaking_balls_json"), [])
        specials = non_usage_specials(split_specials(item.get("special_abilities_json")))
        ranked = ranked_values(item.get("ranked_special_abilities_json"))
        role = str(item.get("role", ""))
        row = {
            "dataset": DATASET_BEFORE,
            "run": "before_csv",
            "player_id": f"{DATASET_BEFORE}:{item.get('seed', item.name)}",
            "role": role,
            "category": item.get("category", ""),
            "name": item.get("name", ""),
            "age": item.get("age"),
            "age_band": age_band(item.get("age")) if pd.notna(item.get("age")) else "年齢不明",
            "position": item.get("position", ""),
            "pitcher_role": item.get("position", "") if role == "投手" else "",
            "player_class": item.get("player_class", item.get("選手格", "")),
            "archetype": item.get("archetype", item.get("アーキタイプ", "")),
            "position_style": item.get("position_style", item.get("ポジションスタイル", "")),
            "special_count": len(specials),
            "ranked_non_d_count": sum(1 for name in ranked if rank_is_non_d(name)),
            "special_names": "、".join(specials),
            "ranked_special_names": "、".join(ranked),
        }
        for key in FIELDER_KEYS:
            row[key] = ability_numeric_value(abilities, key)
        row["野手6能力合計"] = sum(row[key] for key in FIELDER_KEYS if pd.notna(row.get(key))) if role == "野手" else None
        row["A以上能力数"] = sum(1 for key in FIELDER_KEYS if isinstance(row.get(key), (int, float)) and row[key] >= 80) if role == "野手" else None
        row["最低能力"] = min([row[key] for key in FIELDER_KEYS if pd.notna(row.get(key))], default=None) if role == "野手" else None
        row["球速"] = pitcher_speed_value(abilities)
        row["コントロール"] = ability_numeric_value(abilities, "コントロール")
        row["スタミナ"] = ability_numeric_value(abilities, "スタミナ")
        row.update(generated_pitch_metrics(balls if isinstance(balls, list) else []))
        rows.append(row)
        events.extend({"dataset": DATASET_BEFORE, "run": "before_csv", "player_id": row["player_id"], "role": role, "special": name, "event_type": "normal"} for name in specials)
        events.extend({"dataset": DATASET_BEFORE, "run": "before_csv", "player_id": row["player_id"], "role": role, "special": name, "event_type": "ranked", "non_d": rank_is_non_d(name)} for name in ranked)
    return pd.DataFrame(rows), pd.DataFrame(events)


def load_real_xlsx(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    xl = pd.ExcelFile(path)
    players = pd.read_excel(xl, "players")
    breaking = pd.read_excel(xl, "breaking_balls") if "breaking_balls" in xl.sheet_names else pd.DataFrame()
    specials = pd.read_excel(xl, "special_abilities") if "special_abilities" in xl.sheet_names else pd.DataFrame()

    key_cols = ["team", "name"]
    pitch_rows = []
    if not breaking.empty:
        b = breaking.copy()
        b["slot"] = pd.to_numeric(b.get("slot"), errors="coerce")
        b["movement"] = pd.to_numeric(b.get("movement"), errors="coerce").fillna(0)
        grouped = b.groupby(key_cols, dropna=False)
        for key, sub in grouped:
            primary = sub[sub["kind"].eq("breaking") & sub["slot"].fillna(1).eq(1)]
            second = sub[sub["kind"].eq("breaking") & sub["slot"].eq(2)]
            straight = sub[sub["kind"].eq("second_fastball")]
            pitch_rows.append({
                "team": key[0],
                "name": key[1],
                "通常球種数": int(len(primary)),
                "表示球種数": int(len(primary) + len(second) + len(straight)),
                "第二球種あり": bool(len(second)),
                "ストレート系第二種あり": bool(len(straight)),
                "第二球種+ストレート系第二種あり": bool(len(second) and len(straight)),
                "総変化量": float(primary["movement"].sum()),
            })
    pitch = pd.DataFrame(pitch_rows)
    merged = players.merge(pitch, on=key_cols, how="left")

    events: list[dict[str, Any]] = []
    if not specials.empty:
        for _, item in specials.iterrows():
            name = normalize_special_name(item.get("special"))
            if not name or name in USAGE_NAMES:
                continue
            role_match = players[(players["team"].eq(item.get("team"))) & (players["name"].eq(item.get("name")))]
            role = str(role_match["role"].iloc[0]) if not role_match.empty else ""
            kind = str(item.get("special_kind", "normal"))
            events.append({
                "dataset": DATASET_REAL,
                "run": "real",
                "player_id": f"{DATASET_REAL}:{item.get('team')}:{item.get('name')}",
                "role": role,
                "special": name,
                "event_type": "ranked" if kind == "rank" else "normal",
                "non_d": rank_is_non_d(name) if kind == "rank" else False,
            })
    event_df = pd.DataFrame(events)
    non_d = event_df[event_df.get("event_type", pd.Series(dtype=str)).eq("ranked") & event_df.get("non_d", pd.Series(dtype=bool)).eq(True)].groupby("player_id").size()
    normal_counts = event_df[event_df.get("event_type", pd.Series(dtype=str)).ne("ranked")].groupby("player_id").size()

    rows: list[dict[str, Any]] = []
    for _, item in merged.iterrows():
        role = str(item.get("role", ""))
        player_id = f"{DATASET_REAL}:{item.get('team')}:{item.get('name')}"
        row = {
            "dataset": DATASET_REAL,
            "run": "real",
            "player_id": player_id,
            "role": role,
            "category": "実在12球団",
            "name": item.get("name", ""),
            "age": None,
            "age_band": "年齢不明",
            "position": item.get("main_position", ""),
            "pitcher_role": real_pitcher_role(item.get("pitcher_roles")) if role == "投手" else "",
            "player_class": "実在",
            "archetype": "",
            "position_style": "",
            "ミート": item.get("contact"),
            "パワー": item.get("power"),
            "走力": item.get("run_speed"),
            "肩力": item.get("arm_strength"),
            "守備力": item.get("fielding"),
            "捕球": item.get("catching"),
            "球速": item.get("top_speed"),
            "コントロール": item.get("control"),
            "スタミナ": item.get("stamina"),
            "通常球種数": item.get("通常球種数", 0) if role == "投手" else None,
            "表示球種数": item.get("表示球種数", 0) if role == "投手" else None,
            "第二球種あり": bool(item.get("第二球種あり", False)) if role == "投手" else False,
            "ストレート系第二種あり": bool(item.get("ストレート系第二種あり", False)) if role == "投手" else False,
            "第二球種+ストレート系第二種あり": bool(item.get("第二球種+ストレート系第二種あり", False)) if role == "投手" else False,
            "総変化量": item.get("総変化量", 0) if role == "投手" else None,
            "special_count": int(normal_counts.get(player_id, 0)),
            "ranked_non_d_count": int(non_d.get(player_id, 0)),
        }
        row["野手6能力合計"] = sum(pd.to_numeric(pd.Series([row[k] for k in FIELDER_KEYS]), errors="coerce").dropna()) if role == "野手" else None
        row["A以上能力数"] = sum(1 for key in FIELDER_KEYS if pd.notna(row.get(key)) and float(row[key]) >= 80) if role == "野手" else None
        vals = [float(row[key]) for key in FIELDER_KEYS if pd.notna(row.get(key))]
        row["最低能力"] = min(vals) if role == "野手" and vals else None
        rows.append(row)
    return pd.DataFrame(rows), event_df


def generate_after(count: int, seeds: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    master = load_master_data()
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for run_index, seed_start in enumerate(seeds, start=1):
        run = f"after_seed_{seed_start}"
        offset = 0
        for role in ("投手", "野手"):
            print(f"{run}: {role} {count}人生成中", flush=True)
            for _ in range(count):
                player = generate_player(role, "架空球団用", master, seed_start + offset)
                row, event = normalize_generated_player(player, DATASET_AFTER, run)
                rows.append(row)
                events.extend(event)
                offset += 1
    return pd.DataFrame(rows), pd.DataFrame(events)


def describe(values: pd.Series) -> dict[str, Any]:
    nums = pd.to_numeric(values, errors="coerce").dropna()
    if nums.empty:
        return {key: None for key in SUMMARY_STATS} | {"人数": 0}
    return {
        "人数": int(len(nums)),
        "平均": round(float(nums.mean()), 3),
        "中央値": round(float(nums.median()), 3),
        "P25": round(float(nums.quantile(0.25)), 3),
        "P50": round(float(nums.quantile(0.50)), 3),
        "P75": round(float(nums.quantile(0.75)), 3),
        "P90": round(float(nums.quantile(0.90)), 3),
        "P95": round(float(nums.quantile(0.95)), 3),
        "P99": round(float(nums.quantile(0.99)), 3),
        "最小": round(float(nums.min()), 3),
        "最大": round(float(nums.max()), 3),
        "標準偏差": round(float(nums.std()), 3) if len(nums) > 1 else 0,
    }


def grouped_stats(df: pd.DataFrame, role: str, value_cols: list[str], group_cols: list[list[str]]) -> pd.DataFrame:
    rows = []
    base = df[df["role"].eq(role)].copy()
    for groups in [[]] + group_cols:
        grouped = base.groupby(groups, dropna=False) if groups else [((), base)]
        for group_value, subset in grouped:
            if not isinstance(group_value, tuple):
                group_value = (group_value,)
            group_label = "+".join(groups) if groups else "全体"
            group_text = " / ".join(f"{key}={value}" for key, value in zip(groups, group_value, strict=False)) if groups else "全体"
            for col in value_cols:
                rows.append({"集計軸": group_label, "集計値": group_text, "対象": role, "指標": col, **describe(subset[col])})
    return pd.DataFrame(rows)


def fielder_total_table(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    f = players[players["role"].eq("野手")]
    groups = [[], ["dataset"], ["dataset", "run"], ["dataset", "player_class"], ["dataset", "age_band"], ["dataset", "position"]]
    for group_cols in groups:
        grouped = f.groupby(group_cols, dropna=False) if group_cols else [((), f)]
        for group_value, subset in grouped:
            if not isinstance(group_value, tuple):
                group_value = (group_value,)
            row = {
                "集計軸": "+".join(group_cols) if group_cols else "全体",
                "集計値": " / ".join(f"{key}={value}" for key, value in zip(group_cols, group_value, strict=False)) if group_cols else "全体",
                **describe(subset["野手6能力合計"]),
            }
            row.update({
                "A以上0個率%": round((subset["A以上能力数"].eq(0)).mean() * 100, 3) if len(subset) else None,
                "A以上1個率%": round((subset["A以上能力数"].eq(1)).mean() * 100, 3) if len(subset) else None,
                "A以上2個率%": round((subset["A以上能力数"].eq(2)).mean() * 100, 3) if len(subset) else None,
                "A以上3個率%": round((subset["A以上能力数"].eq(3)).mean() * 100, 3) if len(subset) else None,
                "A以上4個以上率%": round((subset["A以上能力数"].ge(4)).mean() * 100, 3) if len(subset) else None,
                "最低能力70以上人数": int(subset["最低能力"].ge(70).sum()),
                "420以上人数": int(subset["野手6能力合計"].ge(420).sum()),
                "430以上人数": int(subset["野手6能力合計"].ge(430).sum()),
                "450以上人数": int(subset["野手6能力合計"].ge(450).sum()),
                "一軍主力級430以上人数": int((subset["player_class"].eq("一軍主力級") & subset["野手6能力合計"].ge(430)).sum()),
                "スター級以外A3個以上人数": int((~subset["player_class"].eq("スター級") & subset["A以上能力数"].ge(3)).sum()),
            })
            rows.append(row)
    return pd.DataFrame(rows)


def rate_rows(players: pd.DataFrame, group_sets: list[list[str]], value: str, thresholds: dict[str, float], role: str = "野手") -> pd.DataFrame:
    rows = []
    base = players[players["role"].eq(role)].copy()
    for groups in group_sets:
        grouped = base.groupby(groups, dropna=False) if groups else [((), base)]
        for group_value, subset in grouped:
            if not isinstance(group_value, tuple):
                group_value = (group_value,)
            row = {
                "集計軸": "+".join(groups) if groups else "全体",
                "集計値": " / ".join(f"{key}={value_}" for key, value_ in zip(groups, group_value, strict=False)) if groups else "全体",
                "人数": int(len(subset)),
                "指標": value,
            }
            nums = pd.to_numeric(subset[value], errors="coerce")
            for label, threshold in thresholds.items():
                row[f"{label}率%"] = round(nums.ge(threshold).mean() * 100, 3) if len(subset) else None
            row.update({"中央値": round(nums.median(), 3) if nums.notna().any() else None, "P90": round(nums.quantile(0.90), 3) if nums.notna().any() else None, "最大": nums.max() if nums.notna().any() else None})
            rows.append(row)
    return pd.DataFrame(rows)


def pitch_count_table(players: pd.DataFrame) -> pd.DataFrame:
    p = players[players["role"].eq("投手")].copy()
    rows = []
    groups = [[], ["dataset"], ["dataset", "run"], ["dataset", "pitcher_role"], ["dataset", "age_band"], ["dataset", "player_class"]]
    for group_cols in groups:
        grouped = p.groupby(group_cols, dropna=False) if group_cols else [((), p)]
        for group_value, subset in grouped:
            if not isinstance(group_value, tuple):
                group_value = (group_value,)
            total = max(1, len(subset))
            for count_col in ["通常球種数", "表示球種数"]:
                nums = pd.to_numeric(subset[count_col], errors="coerce").fillna(0)
                row = {
                    "集計軸": "+".join(group_cols) if group_cols else "全体",
                    "集計値": " / ".join(f"{key}={value}" for key, value in zip(group_cols, group_value, strict=False)) if group_cols else "全体",
                    "球種数定義": count_col,
                    "人数": int(len(subset)),
                    "平均": round(nums.mean(), 3),
                    "中央値": round(nums.median(), 3),
                    "4以上率%": round(nums.ge(4).sum() / total * 100, 3),
                    "5以上率%": round(nums.ge(5).sum() / total * 100, 3),
                }
                for count in range(0, 5):
                    row[f"{count}球種率%"] = round(nums.eq(count).sum() / total * 100, 3)
                rows.append(row)
            movement = pd.to_numeric(subset["総変化量"], errors="coerce")
            rows.append({
                "集計軸": "+".join(group_cols) if group_cols else "全体",
                "集計値": " / ".join(f"{key}={value}" for key, value in zip(group_cols, group_value, strict=False)) if group_cols else "全体",
                "球種数定義": "総変化量",
                "人数": int(len(subset)),
                "平均": round(movement.mean(), 3),
                "中央値": round(movement.median(), 3),
                "P90": round(movement.quantile(0.90), 3),
                "P95": round(movement.quantile(0.95), 3),
                "第二球種率%": round(subset["第二球種あり"].mean() * 100, 3),
                "ストレート系第二種率%": round(subset["ストレート系第二種あり"].mean() * 100, 3),
                "同時保有率%": round(subset["第二球種+ストレート系第二種あり"].mean() * 100, 3),
            })
    return pd.DataFrame(rows)


def special_count_table(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    groups = [[], ["dataset"], ["dataset", "run"], ["dataset", "role"], ["dataset", "player_class"], ["dataset", "age_band"], ["dataset", "position"], ["dataset", "pitcher_role"]]
    for group_cols in groups:
        grouped = players.groupby(group_cols, dropna=False) if group_cols else [((), players)]
        for group_value, subset in grouped:
            if not isinstance(group_value, tuple):
                group_value = (group_value,)
            nums = pd.to_numeric(subset["special_count"], errors="coerce").fillna(0)
            total = max(1, len(subset))
            rows.append({
                "集計軸": "+".join(group_cols) if group_cols else "全体",
                "集計値": " / ".join(f"{key}={value}" for key, value in zip(group_cols, group_value, strict=False)) if group_cols else "全体",
                "人数": int(len(subset)),
                "平均": round(nums.mean(), 3),
                "中央値": round(nums.median(), 3),
                "最小": int(nums.min()) if len(nums) else None,
                "最大": int(nums.max()) if len(nums) else None,
                "P90": round(nums.quantile(0.90), 3),
                "P95": round(nums.quantile(0.95), 3),
                "P99": round(nums.quantile(0.99), 3),
                "0個率%": round(nums.eq(0).sum() / total * 100, 3),
                "1個率%": round(nums.eq(1).sum() / total * 100, 3),
                "2-4個率%": round(nums.between(2, 4).sum() / total * 100, 3),
                "5-7個率%": round(nums.between(5, 7).sum() / total * 100, 3),
                "8個以上率%": round(nums.ge(8).sum() / total * 100, 3),
                "10個以上率%": round(nums.ge(10).sum() / total * 100, 3),
            })
    return pd.DataFrame(rows)


def candidate_mask_for_special(players: pd.DataFrame, role: str, special: str) -> pd.Series:
    mask = players["role"].eq(role)
    if role == "投手":
        speed = pd.to_numeric(players["球速"], errors="coerce")
        control = pd.to_numeric(players["コントロール"], errors="coerce")
        movement = pd.to_numeric(players["総変化量"], errors="coerce")
        top_class = players["player_class"].isin(["スター級", "一軍主力級", "ベテラン型"])
        if special == "球速安定":
            return mask & (speed.ge(147) | top_class | players["pitcher_role"].isin(["中継ぎ", "抑え"]))
        if special == "リリース○":
            return mask & (control.ge(55) | players["archetype"].isin(["制球", "変化球"]) | top_class)
        if special == "奪三振":
            return mask & (speed.ge(148) | movement.ge(8) | players["pitcher_role"].eq("抑え") | players["archetype"].isin(["速球", "変化球"]))
        if special == "四球":
            return mask & control.lt(55)
        if special == "抜け球":
            return mask & (control.lt(55) | players["age_band"].isin(["18-21歳", "22-24歳"]))
        if special == "球持ち○":
            return mask & (control.ge(55) | players["archetype"].isin(["制球", "変化球"]) | top_class)
        if special == "内角攻め":
            return mask & (control.ge(55) | speed.ge(148) | top_class)
        return mask
    speed = pd.to_numeric(players["走力"], errors="coerce")
    power = pd.to_numeric(players["パワー"], errors="coerce")
    meet = pd.to_numeric(players["ミート"], errors="coerce")
    top_class = players["player_class"].isin(["スター級", "一軍主力級", "ベテラン型"])
    slug_style = players["position_style"].isin(["強打一塁手", "強打三塁手", "強打外野手", "打撃型捕手"])
    if special == "三振":
        return mask & (meet.lt(58) | power.ge(70) | players["archetype"].eq("長打") | slug_style)
    if special in {"サヨナラ男", "満塁男"}:
        return mask & (top_class | power.ge(65) | slug_style)
    if special == "内野安打○":
        return mask & speed.ge(60)
    if special == "固め打ち":
        return mask & (meet.ge(55) | top_class)
    return mask


def special_rate_table(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if events.empty:
        return pd.DataFrame()
    focus = {"投手": SPECIAL_FOCUS_PITCHER, "野手": SPECIAL_FOCUS_FIELDER}
    for dataset, dplayers in players.groupby("dataset", dropna=False):
        for role, names in focus.items():
            denom = int(dplayers["role"].eq(role).sum())
            ev = events[events["dataset"].eq(dataset) & events["role"].eq(role) & events["special"].isin(names)]
            counts = ev.groupby("special")["player_id"].nunique()
            for name in names:
                candidate_mask = candidate_mask_for_special(dplayers, role, name)
                candidate_ids = set(dplayers.loc[candidate_mask, "player_id"])
                holder_ids = set(ev[ev["special"].eq(name)]["player_id"])
                candidate_count = len(candidate_ids)
                rows.append({
                    "dataset": dataset,
                    "role": role,
                    "特殊能力": name,
                    "対象人数": denom,
                    "保有人数": int(counts.get(name, 0)),
                    "保有率%": round(counts.get(name, 0) / max(1, denom) * 100, 3),
                    "候補者数": candidate_count,
                    "候補者内保有人数": len(candidate_ids & holder_ids),
                    "候補者内保有率%": round(len(candidate_ids & holder_ids) / max(1, candidate_count) * 100, 3),
                })
    table = pd.DataFrame(rows)
    if not table.empty and DATASET_REAL in set(table["dataset"]):
        real_rates = table[table["dataset"].eq(DATASET_REAL)][["role", "特殊能力", "保有率%"]].rename(columns={"保有率%": "実在保有率%"})
        table = table.merge(real_rates, on=["role", "特殊能力"], how="left")
        table["実在差分pt"] = (table["保有率%"] - table["実在保有率%"]).round(3)
    return table


def ranked_table(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    groups = [[], ["dataset"], ["dataset", "role"], ["dataset", "player_class"]]
    for group_cols in groups:
        grouped = players.groupby(group_cols, dropna=False) if group_cols else [((), players)]
        for group_value, subset in grouped:
            if not isinstance(group_value, tuple):
                group_value = (group_value,)
            rows.append({
                "集計軸": "+".join(group_cols) if group_cols else "全体",
                "集計値": " / ".join(f"{key}={value}" for key, value in zip(group_cols, group_value, strict=False)) if group_cols else "全体",
                **describe(subset["ranked_non_d_count"]),
            })
    return pd.DataFrame(rows)


def age_special_table(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    merged = players[["dataset", "player_id", "age_band", "role", "special_count", "ranked_non_d_count"]].copy()
    normal_events = events[events.get("event_type", pd.Series(dtype=str)).ne("ranked")].copy() if not events.empty else pd.DataFrame()
    for (dataset, age), subset in merged.groupby(["dataset", "age_band"], dropna=False):
        ev = normal_events[normal_events["player_id"].isin(subset["player_id"])] if not normal_events.empty else pd.DataFrame()
        rows.append({
            "dataset": dataset,
            "年齢帯": age,
            "人数": int(len(subset)),
            "特殊能力数平均": round(subset["special_count"].mean(), 3),
            "非Dランク数平均": round(subset["ranked_non_d_count"].mean(), 3),
            **{f"{name}率%": round(ev[ev["special"].eq(name)]["player_id"].nunique() / max(1, len(subset)) * 100, 3) if not ev.empty else 0 for name in ["三振", "四球", "抜け球", "荒れ球", "リリース○", "緩急○", "代打○"]},
        })
    return pd.DataFrame(rows)


def consistency_warnings(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []

    def add(dataset: str, name: str, condition: pd.Series, total_mask: pd.Series) -> None:
        total = int(total_mask.sum())
        bad = condition[condition].index.tolist()
        rows.append({"dataset": dataset, "チェック": name, "対象人数": total, "矛盾人数": len(bad), "矛盾率%": round(len(bad) / max(1, total) * 100, 3), "例player_id": "、".join(map(str, bad[:8]))})

    normal_events = events[events["event_type"].ne("ranked")].copy()
    for dataset, subset in players.groupby("dataset", dropna=False):
        p = subset.set_index("player_id")
        idx = p.index
        holder = normal_events[normal_events["dataset"].eq(dataset)].groupby("special")["player_id"].apply(set).to_dict()

        def has(name: str) -> pd.Series:
            return pd.Series(idx.isin(holder.get(name, set())), index=idx)

        def both(left: str, right: str) -> pd.Series:
            return has(left) & has(right)

        add(dataset, "四球とコントロール60以上", has("四球") & p["コントロール"].ge(60), has("四球"))
        add(dataset, "抜け球とコントロール60以上", has("抜け球") & p["コントロール"].ge(60), has("抜け球"))
        add(dataset, "荒れ球とコントロール60以上", has("荒れ球") & p["コントロール"].ge(60), has("荒れ球"))
        add(dataset, "奪三振と低球速低変化量", has("奪三振") & p["球速"].lt(145) & p["総変化量"].lt(7), has("奪三振"))
        add(dataset, "球速安定と球速145未満", has("球速安定") & p["球速"].lt(145), has("球速安定"))
        add(dataset, "スロースターターと非先発", has("スロースターター") & ~p["pitcher_role"].eq("先発"), has("スロースターター"))
        add(dataset, "三振と高ミート", has("三振") & p["ミート"].ge(70), has("三振"))
        add(dataset, "併殺と高走力", has("併殺") & p["走力"].ge(70), has("併殺"))
        add(dataset, "内野安打○と低走力", has("内野安打○") & p["走力"].lt(55), has("内野安打○"))
        add(dataset, "代打○とスター/若手素材型", has("代打○") & p["player_class"].isin(["スター級", "若手素材型"]), has("代打○"))
        add(dataset, "高速チャージと一三塁以外", has("高速チャージ") & ~p["position"].isin(["一塁手", "三塁手"]), has("高速チャージ"))
        add(dataset, "レーザービームと外野以外", has("レーザービーム") & ~p["position"].eq("外野手"), has("レーザービーム"))
        add(dataset, "四球とストライク先行", both("四球", "ストライク先行"), has("四球") | has("ストライク先行"))
        add(dataset, "抜け球とリリース○", both("抜け球", "リリース○"), has("抜け球") | has("リリース○"))
        add(dataset, "三振と粘り打ち", both("三振", "粘り打ち"), has("三振") | has("粘り打ち"))
        add(dataset, "併殺と走塁/盗塁系", has("併殺") & (has("走塁〇") | has("盗塁〇") | has("積極走塁") | has("積極盗塁")), has("併殺") | has("走塁〇") | has("盗塁〇") | has("積極走塁") | has("積極盗塁"))
    return pd.DataFrame(rows)


def build_warnings(players: pd.DataFrame, special_rates: pd.DataFrame, pitch_counts: pd.DataFrame, consistency: pd.DataFrame) -> pd.DataFrame:
    rows = []
    after = players[players["dataset"].eq(DATASET_AFTER)]
    f = after[after["role"].eq("野手")]
    rows.extend([
        {"警告": "野手6能力合計450以上", "件数": int(f["野手6能力合計"].ge(450).sum()), "severity": "high"},
        {"警告": "最低能力70以上万能型", "件数": int(f["最低能力"].ge(70).sum()), "severity": "high"},
        {"警告": "一軍主力級430以上", "件数": int((f["player_class"].eq("一軍主力級") & f["野手6能力合計"].ge(430)).sum()), "severity": "medium"},
        {"警告": "A以上4項目以上", "件数": int(f["A以上能力数"].ge(4).sum()), "severity": "medium"},
    ])
    rates = special_rates[special_rates["dataset"].eq(DATASET_AFTER) & special_rates["実在差分pt"].abs().ge(10)] if not special_rates.empty and "実在差分pt" in special_rates else pd.DataFrame()
    for _, row in rates.iterrows():
        rows.append({"警告": f"特殊能力差分±10pt以上: {row['role']} {row['特殊能力']}", "件数": "", "severity": "medium", "差分pt": row["実在差分pt"]})
    pc = pitch_counts[pitch_counts["集計値"].astype(str).str.contains(f"dataset={DATASET_AFTER} / pitcher_role=先発", regex=False) & pitch_counts["球種数定義"].eq("表示球種数")]
    if not pc.empty and float(pc["4以上率%"].iloc[0]) > 8:
        rows.append({"警告": "先発の表示4球種以上率が8%超", "件数": float(pc["4以上率%"].iloc[0]), "severity": "low"})
    if not consistency.empty:
        after_consistency = consistency[consistency["dataset"].eq(DATASET_AFTER)] if "dataset" in consistency else consistency
        for _, row in after_consistency[after_consistency["矛盾率%"].ge(20)].iterrows():
            rows.append({"警告": f"整合性矛盾率20%以上: {row['チェック']}", "件数": row["矛盾人数"], "severity": "medium", "差分pt": row["矛盾率%"]})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "（なし）"
    data = df.head(max_rows).fillna("").astype(str)
    lines = ["| " + " | ".join(data.columns) + " |", "| " + " | ".join("---" for _ in data.columns) + " |"]
    for _, row in data.iterrows():
        lines.append("| " + " | ".join(str(row[col]).replace("|", "\\|") for col in data.columns) + " |")
    return "\n".join(lines)


def write_summary(path: Path, tables: dict[str, pd.DataFrame], files: dict[str, str], seeds: list[int], count: int) -> None:
    overview = tables["Overview"]
    fielder = tables["Fielder Total Ability"]
    pitch = tables["Pitch Count Distribution"]
    special = tables["Special Count Distribution"]
    warnings = tables["Warnings"]
    lines = [
        "# 実在12球団・修正前/現在/追加調整後 直接比較サマリー",
        "",
        "## 使用ファイル",
        *[f"- {key}: `{value}`" for key, value in files.items()],
        f"- 追加調整後生成: 投手{count}人 + 野手{count}人 × {len(seeds)} seed ({', '.join(map(str, seeds))})",
        "",
        "## Overview",
        markdown_table(overview, 30),
        "",
        "## 野手6能力合計",
        markdown_table(fielder[fielder["集計軸"].isin(["dataset", "dataset+run"])], 30),
        "",
        "## 球種数",
        markdown_table(pitch[pitch["集計軸"].isin(["dataset", "dataset+pitcher_role"])], 40),
        "",
        "## 特殊能力数",
        markdown_table(special[special["集計軸"].isin(["dataset", "dataset+role", "dataset+player_class"])], 50),
        "",
        "## Warnings",
        markdown_table(warnings, 80),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(output_dir: Path, tables: dict[str, pd.DataFrame], players: pd.DataFrame, events: pd.DataFrame, files: dict[str, str], seeds: list[int], count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    workbook_tables: dict[str, list[dict[str, Any]]] = {}
    for name, table in tables.items():
        table.to_csv(output_dir / f"{name.replace(' ', '_').replace('/', '_')}.csv", index=False, encoding="utf-8-sig")
        cleaned = table.replace({pd.NA: None}).where(pd.notna(table), None)
        workbook_tables[name] = cleaned.to_dict(orient="records")
    players.to_csv(output_dir / "normalized_players.csv", index=False, encoding="utf-8-sig")
    events.to_csv(output_dir / "normalized_special_events.csv", index=False, encoding="utf-8-sig")
    tables["Warnings"].to_csv(output_dir / "warnings.csv", index=False, encoding="utf-8-sig")
    (output_dir / "workbook_tables.json").write_text(json.dumps(workbook_tables, ensure_ascii=False), encoding="utf-8")
    write_summary(output_dir / "summary.md", tables, files, seeds, count)


def require_existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} が見つかりません: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} がファイルではありません: {path}")


def main() -> int:
    args = parse_args()
    require_existing_file(args.real_xlsx, "実在Excel")
    require_existing_file(args.before_csv, "修正前CSV")
    print("実在Excel読み込み中", flush=True)
    real_players, real_events = load_real_xlsx(args.real_xlsx)
    print("修正前CSV読み込み中", flush=True)
    before_players, before_events = load_before_csv(args.before_csv)
    current_cache = args.output_dir / "current_normalized_players.csv"
    current_events_cache = args.output_dir / "current_normalized_special_events.csv"
    if current_cache.exists() and current_events_cache.exists():
        print("現在架空スナップショット読み込み中", flush=True)
        current_players = pd.read_csv(current_cache)
        current_events = pd.read_csv(current_events_cache)
        current_players["dataset"] = DATASET_CURRENT
        current_events["dataset"] = DATASET_CURRENT
        current_players["run"] = current_players["run"].astype(str).str.replace("after_seed_", "current_seed_", regex=False)
        current_events["run"] = current_events["run"].astype(str).str.replace("after_seed_", "current_seed_", regex=False)
    else:
        current_players = pd.DataFrame()
        current_events = pd.DataFrame()
    after_cache = args.output_dir / "after_normalized_players.csv"
    after_events_cache = args.output_dir / "after_normalized_special_events.csv"
    if args.skip_after_generation and after_cache.exists() and after_events_cache.exists():
        after_players = pd.read_csv(after_cache)
        after_events = pd.read_csv(after_events_cache)
        after_players["dataset"] = DATASET_AFTER
        after_events["dataset"] = DATASET_AFTER
    else:
        after_players, after_events = generate_after(args.count, args.seeds)
    players = pd.concat([real_players, before_players, current_players, after_players], ignore_index=True, sort=False)
    events = pd.concat([real_events, before_events, current_events, after_events], ignore_index=True, sort=False)

    overview = players.groupby(["dataset", "run", "role"], dropna=False).size().reset_index(name="人数")
    fielder_abilities = grouped_stats(players, "野手", FIELDER_KEYS, [["dataset"], ["dataset", "run"], ["dataset", "player_class"], ["dataset", "age_band"], ["dataset", "position"]])
    pitcher_abilities = grouped_stats(players, "投手", PITCHER_KEYS, [["dataset"], ["dataset", "run"], ["dataset", "age_band"], ["dataset", "pitcher_role"]])
    rank_distribution = pd.concat([
        rate_rows(players, [[], ["dataset"], ["dataset", "player_class"], ["dataset", "age_band"], ["dataset", "position"], ["dataset", "position_style"]], "パワー", {"A以上": 80, "S": 90}, "野手"),
        rate_rows(players, [[], ["dataset"], ["dataset", "player_class"], ["dataset", "age_band"], ["dataset", "position"], ["dataset", "position_style"]], "ミート", {"A以上": 80, "S": 90}, "野手"),
    ], ignore_index=True)
    fielder_total = fielder_total_table(players)
    pitch_counts = pitch_count_table(players)
    special_counts = special_count_table(players)
    special_rates = special_rate_table(players, events)
    ranked = ranked_table(players)
    by_class = grouped_stats(players, "野手", ["野手6能力合計", *FIELDER_KEYS], [["dataset", "player_class"]])
    by_age = pd.concat([
        grouped_stats(players, "野手", ["野手6能力合計", *FIELDER_KEYS], [["dataset", "age_band"]]),
        grouped_stats(players, "投手", ["球速", "コントロール", "スタミナ"], [["dataset", "age_band"]]),
        age_special_table(players, events),
    ], ignore_index=True, sort=False)
    by_position = grouped_stats(players, "野手", ["野手6能力合計", *FIELDER_KEYS], [["dataset", "position"]])
    by_pitcher_role = grouped_stats(players, "投手", ["球速", "通常球種数", "表示球種数", "総変化量"], [["dataset", "pitcher_role"]])
    consistency = consistency_warnings(players, events)
    warnings = build_warnings(players, special_rates, pitch_counts, consistency)

    tables = {
        "Overview": overview,
        "Fielder Abilities": fielder_abilities,
        "Pitcher Abilities": pitcher_abilities,
        "Ability Rank Distribution": rank_distribution,
        "Fielder Total Ability": fielder_total,
        "Pitch Count Distribution": pitch_counts,
        "Special Count Distribution": special_counts,
        "Special Ability Rates": special_rates,
        "Ranked Specials": ranked,
        "By Player Class": by_class,
        "By Age": by_age,
        "By Position": by_position,
        "By Pitcher Role": by_pitcher_role,
        "Consistency Warnings": consistency,
        "Warnings": warnings,
    }
    files = {"real_xlsx": str(args.real_xlsx), "before_csv": str(args.before_csv)}
    if not current_players.empty:
        files["current_snapshot"] = str(current_cache)
    write_outputs(args.output_dir, tables, players, events, files, args.seeds, args.count)
    after_players.to_csv(args.output_dir / "after_normalized_players.csv", index=False, encoding="utf-8-sig")
    after_events.to_csv(args.output_dir / "after_normalized_special_events.csv", index=False, encoding="utf-8-sig")
    print(f"完了: {args.output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
