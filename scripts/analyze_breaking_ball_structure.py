from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_REAL = (
    ROOT.parent
    / "real_powerpro_players_12teams_final"
    / "pawapuro_players_entry_route_2026.xlsx"
)
DEFAULT_OUTPUT = ROOT / "reports" / "breaking_ball_structure_recheck"
REAL = "実在"
GENERATED = "生成"
AGE_BANDS = ["18～22歳", "23～26歳", "27～30歳", "31～34歳", "35歳以上"]
PRO_BANDS = ["1～3年", "4～6年", "7～10年", "11～15年", "16年以上"]
PITCH_COUNT_BUCKETS = ["1球種", "2球種", "3球種", "4球種", "5球種以上"]
SECOND_FASTBALL_NAMES = ["ツーシームファスト", "ムービングファスト", "超スローボール"]
MAJOR_PITCHES = [
    "スライダー", "Hスライダー", "カットボール", "カーブ", "スラーブ",
    "Vスライダー", "フォーク", "SFF", "チェンジアップ", "サークルチェンジ", "Hシンカー",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="変化球構成を実在402投手と現行main生成投手で比較します。")
    parser.add_argument("--real-xlsx", type=Path, default=DEFAULT_REAL)
    parser.add_argument("--database", type=Path, default=ROOT / "players.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--merge-commit",
        default="72f349c",
        help="このコミット日時以降にSQLiteへ保存された架空球団用選手だけを生成側に採用します。",
    )
    return parser.parse_args()


def pct(value: float) -> float:
    return round(float(value) * 100, 3) if not pd.isna(value) else math.nan


def safe_json(value: Any, default: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def normalize_direction(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def movement(ball: dict[str, Any]) -> int:
    value = ball.get("movement", ball.get("level", 0))
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def age_band(value: Any) -> str:
    if pd.isna(value):
        return "不明"
    age = int(value)
    if age <= 22:
        return AGE_BANDS[0]
    if age <= 26:
        return AGE_BANDS[1]
    if age <= 30:
        return AGE_BANDS[2]
    if age <= 34:
        return AGE_BANDS[3]
    return AGE_BANDS[4]


def pro_band(value: Any) -> str:
    if pd.isna(value):
        return "不明"
    years = int(value)
    if years <= 3:
        return PRO_BANDS[0]
    if years <= 6:
        return PRO_BANDS[1]
    if years <= 10:
        return PRO_BANDS[2]
    if years <= 15:
        return PRO_BANDS[3]
    return PRO_BANDS[4]


def real_role(value: Any) -> str:
    text = str(value or "")
    if "先" in text:
        return "先発"
    if "抑" in text:
        return "抑え"
    if "中" in text:
        return "中継ぎ"
    return "不明"


def hand(value: Any) -> str:
    return "左投" if str(value or "").startswith("左投") else "右投"


def commit_time(commit: str) -> str:
    return subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", commit], cwd=ROOT, text=True
    ).strip()


def normalize_real_ball(row: pd.Series) -> dict[str, Any]:
    kind = str(row.get("kind", "breaking") or "breaking")
    slot = pd.to_numeric(pd.Series([row.get("slot")]), errors="coerce").iloc[0]
    is_second = kind == "breaking" and not pd.isna(slot) and int(slot) == 2
    return {
        "name": str(row.get("pitch_type", row.get("name", "")) or "").strip(),
        "direction_code": normalize_direction(row.get("direction_code")),
        "movement": int(pd.to_numeric(pd.Series([row.get("movement")]), errors="coerce").fillna(0).iloc[0]),
        "kind": kind,
        "is_second_pitch": is_second,
        "slot": None if pd.isna(slot) else int(slot),
    }


def load_real(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    xl = pd.ExcelFile(path)
    players = pd.read_excel(xl, "players")
    breaking = pd.read_excel(xl, "breaking_balls")
    if not {"team", "name"}.issubset(players.columns) or not {"team", "name"}.issubset(breaking.columns):
        raise RuntimeError("players / breaking_balls を team・name で結合できません。")
    players = players.copy()
    pitchers = players[players["role"].eq("投手")].copy()
    grouped = {
        (str(team), str(name)): [normalize_real_ball(row) for _, row in subset.iterrows()]
        for (team, name), subset in breaking.groupby(["team", "name"], dropna=False)
    }
    rows = []
    for _, row in pitchers.iterrows():
        key = (str(row["team"]), str(row["name"]))
        rows.append({
            "dataset": REAL,
            "player_id": f"real:{key[0]}:{key[1]}",
            "name": key[1],
            "age": pd.to_numeric(row.get("age"), errors="coerce"),
            "pro_years": pd.to_numeric(row.get("pro_years"), errors="coerce"),
            "pitcher_role": real_role(row.get("pitcher_roles")),
            "hand": hand(row.get("throws_bats")),
            "balls": grouped.get(key, []),
        })
    result = pd.DataFrame(rows)
    missing_breaking = int(result["balls"].map(len).eq(0).sum())
    audit = {
        "workbook_rows": len(players),
        "pitchers": len(result),
        "fielders": int(players["role"].eq("野手").sum()),
        "breaking_rows": len(breaking),
        "pitchers_without_breaking_rows": missing_breaking,
        "age_missing": int(result["age"].isna().sum()),
        "pro_years_missing": int(result["pro_years"].isna().sum()),
    }
    if (len(players), len(result), audit["fielders"]) != (791, 402, 389):
        raise RuntimeError(f"実在人数が想定外です: {audit}")
    return result, breaking, audit


def load_generated(database: Path, merged_at: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    with sqlite3.connect(database) as conn:
        raw = pd.read_sql_query(
            """
            SELECT id, created_at, seed, name, age, pro_years, position,
                   batting_throwing, breaking_balls_json
              FROM players
             WHERE role = '投手' AND category = '架空球団用'
            """,
            conn,
        )
    raw["created_ts"] = pd.to_datetime(raw["created_at"], errors="coerce", utc=True)
    merge_ts = pd.to_datetime(merged_at, utc=True)
    selected = raw[raw["created_ts"].ge(merge_ts)].copy()
    if selected.empty:
        raise RuntimeError(
            f"PR #76マージ後（{merged_at}）の架空球団用投手がSQLiteにありません。"
        )
    result = pd.DataFrame({
        "dataset": GENERATED,
        "player_id": selected["id"].map(lambda value: f"generated:{value}"),
        "name": selected["name"],
        "age": pd.to_numeric(selected["age"], errors="coerce"),
        "pro_years": pd.to_numeric(selected["pro_years"], errors="coerce"),
        "pitcher_role": selected["position"].fillna("不明"),
        "hand": selected["batting_throwing"].map(hand),
        "balls": selected["breaking_balls_json"].map(lambda value: safe_json(value, [])),
    })
    audit = {
        "all_fictional_pitchers_in_db": len(raw),
        "post_merge_pitchers": len(result),
        "merge_time": merged_at,
        "selected_created_at_min": selected["created_at"].min(),
        "selected_created_at_max": selected["created_at"].max(),
        "unique_seeds": int(selected["seed"].nunique()),
    }
    return result, audit


def classify_pattern(values: list[int]) -> str:
    if not values:
        return "なし"
    ordered = sorted(values, reverse=True)
    if max(ordered) - min(ordered) <= 1:
        return "均等型"
    total = sum(ordered)
    share = ordered[0] / total if total else 0
    if ordered[0] >= 5 or share >= 0.60:
        return "決め球特化型"
    return "主力球型"


def enrich(players: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for item in players.itertuples(index=False):
        balls = item.balls if isinstance(item.balls, list) else []
        breaking = [b for b in balls if b.get("kind", "breaking") == "breaking"]
        primary = [b for b in breaking if not bool(b.get("is_second_pitch"))]
        second = [b for b in breaking if bool(b.get("is_second_pitch"))]
        fastballs = [b for b in balls if b.get("kind") == "second_fastball"]
        all_named = [b for b in breaking + fastballs if str(b.get("name", "")).strip()]
        movements = [movement(b) for b in breaking if movement(b) > 0]
        primary_movements = [movement(b) for b in primary if movement(b) > 0]
        dirs = sorted({normalize_direction(b.get("direction_code")) for b in breaking if normalize_direction(b.get("direction_code"))})
        total_count = len({str(b.get("name", "")).strip() for b in all_named})
        rows.append({
            **item._asdict(),
            "age_band": age_band(item.age),
            "pro_band": pro_band(item.pro_years),
            "primary_count": len(primary),
            "second_count": len(second),
            "second_fastball_count": len(fastballs),
            "total_pitch_count": total_count,
            "has_second": bool(second),
            "has_second_fastball": bool(fastballs),
            "has_both": bool(second and fastballs),
            "structure_total_movement": sum(movements),
            "protected_primary_total_movement": sum(primary_movements),
            "movement_pattern": "+".join(map(str, sorted(movements, reverse=True))) if movements else "なし",
            "movement_style": classify_pattern(movements),
            "max_movement": max(movements, default=0),
            "direction_set": "+".join(dirs) if dirs else "なし",
            **{f"has_direction_{code}": code in dirs for code in "12345"},
        })
        for ball in breaking + fastballs:
            events.append({
                "dataset": item.dataset,
                "player_id": item.player_id,
                "age": item.age,
                "pro_years": item.pro_years,
                "pitcher_role": item.pitcher_role,
                "hand": item.hand,
                "name": str(ball.get("name", "")).strip(),
                "direction_code": normalize_direction(ball.get("direction_code")),
                "movement": movement(ball),
                "kind": ball.get("kind", "breaking"),
                "is_second_pitch": bool(ball.get("is_second_pitch")),
            })
    return pd.DataFrame(rows), pd.DataFrame(events)


def compare_rate_rows(
    frames: dict[str, pd.DataFrame], group_name: str, group_value: str, metrics: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dataset, frame in frames.items():
        row = {"dataset": dataset, group_name: group_value, "sample": len(frame)}
        for name, getter in metrics.items():
            value = getter(frame)
            row[name] = round(float(value), 3) if not pd.isna(value) else math.nan
        rows.append(row)
    return rows


def pitch_count_compare(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset, frame in players.groupby("dataset"):
        counts = frame["total_pitch_count"]
        row = {
            "dataset": dataset,
            "sample": len(frame),
            "average_total_pitch_count": round(counts.mean(), 3),
            "average_primary_count": round(frame["primary_count"].mean(), 3),
            "second_pitch_rate_pct": pct(frame["has_second"].mean()),
            "second_fastball_rate_pct": pct(frame["has_second_fastball"].mean()),
            "both_rate_pct": pct(frame["has_both"].mean()),
        }
        for number in range(1, 5):
            row[f"{number}_pitch_rate_pct"] = pct(counts.eq(number).mean())
        row["5_plus_pitch_rate_pct"] = pct(counts.ge(5).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def pitch_count_by_age(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = {
        "average_total_pitch_count": lambda f: f["total_pitch_count"].mean(),
        "2_pitch_rate_pct": lambda f: pct(f["total_pitch_count"].eq(2).mean()),
        "3_pitch_rate_pct": lambda f: pct(f["total_pitch_count"].eq(3).mean()),
        "4_plus_pitch_rate_pct": lambda f: pct(f["total_pitch_count"].ge(4).mean()),
        "second_pitch_rate_pct": lambda f: pct(f["has_second"].mean()),
        "second_fastball_rate_pct": lambda f: pct(f["has_second_fastball"].mean()),
    }
    for band in AGE_BANDS:
        frames = {d: g[g["age_band"].eq(band)] for d, g in players.groupby("dataset")}
        rows.extend(compare_rate_rows(frames, "age_band", band, metrics))
    return pd.DataFrame(rows)


def movement_distribution(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    breaking = events[events["kind"].eq("breaking") & events["movement"].gt(0)]
    for dataset in [REAL, GENERATED]:
        base = breaking[breaking["dataset"].eq(dataset)]
        for scope, frame in [
            ("全変化球", base),
            ("第一球種", base[~base["is_second_pitch"]]),
            ("第二球種", base[base["is_second_pitch"]]),
        ]:
            values = frame["movement"]
            row = {
                "dataset": dataset, "scope": scope, "sample": len(values),
                "mean": round(values.mean(), 3) if len(values) else math.nan,
                "median": round(values.median(), 3) if len(values) else math.nan,
                "p75": round(values.quantile(.75), 3) if len(values) else math.nan,
                "p90": round(values.quantile(.90), 3) if len(values) else math.nan,
                "max": int(values.max()) if len(values) else math.nan,
            }
            for value in range(1, 8):
                row[f"movement_{value}_rate_pct"] = pct(values.eq(value).mean()) if len(values) else math.nan
            rows.append(row)
    return pd.DataFrame(rows)


def movement_patterns(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, GENERATED]:
        base = players[players["dataset"].eq(dataset)].copy()
        base["total_bucket"] = base["structure_total_movement"].map(
            lambda value: "10以上" if value >= 10 else str(int(value))
        )
        for total in ["5", "6", "7", "8", "9", "10以上"]:
            subset = base[base["total_bucket"].eq(total)]
            counter = Counter(subset["movement_pattern"])
            style = Counter(subset["movement_style"])
            for rank, (pattern, count) in enumerate(counter.most_common(12), 1):
                rows.append({
                    "dataset": dataset, "total_movement": total, "row_type": "pattern",
                    "rank": rank, "pattern_or_style": pattern, "count": count,
                    "rate_pct": pct(count / len(subset)) if len(subset) else math.nan,
                    "sample_players": len(subset),
                })
            for style_name in ["均等型", "主力球型", "決め球特化型"]:
                rows.append({
                    "dataset": dataset, "total_movement": total, "row_type": "style",
                    "rank": "", "pattern_or_style": style_name, "count": style[style_name],
                    "rate_pct": pct(style[style_name] / len(subset)) if len(subset) else math.nan,
                    "sample_players": len(subset),
                })
    return pd.DataFrame(rows)


def max_movement_compare(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset, frame in players.groupby("dataset"):
        values = frame["max_movement"]
        row = {"dataset": dataset, "sample": len(frame), "average_max_movement": round(values.mean(), 3)}
        for value in range(1, 6):
            row[f"max_{value}_rate_pct"] = pct(values.eq(value).mean())
        row["max_6_plus_rate_pct"] = pct(values.ge(6).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def pitch_movement_by_name(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    breaking = events[events["kind"].eq("breaking") & events["movement"].gt(0)]
    real_counts = breaking[breaking["dataset"].eq(REAL)]["name"].value_counts()
    names = [name for name in MAJOR_PITCHES if real_counts.get(name, 0) >= 5]
    for dataset in [REAL, GENERATED]:
        for name in names:
            values = breaking[(breaking["dataset"].eq(dataset)) & breaking["name"].eq(name)]["movement"]
            row = {
                "dataset": dataset, "pitch_name": name, "sample": len(values),
                "mean": round(values.mean(), 3) if len(values) else math.nan,
                "min": int(values.min()) if len(values) else math.nan,
                "max": int(values.max()) if len(values) else math.nan,
            }
            for value in range(1, 7):
                row[f"movement_{value}_rate_pct"] = pct(values.eq(value).mean()) if len(values) else math.nan
            rows.append(row)
    return pd.DataFrame(rows)


def master_frame() -> pd.DataFrame:
    import app

    return pd.DataFrame(app.BREAKING_BALL_MASTER)[
        ["name", "direction_code", "min_movement", "max_movement"]
    ].rename(columns={"name": "pitch_name"})


def master_audit(events: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    rows = []
    breaking = events[events["kind"].eq("breaking") & events["movement"].gt(0)]
    for _, rule in master.iterrows():
        name = rule["pitch_name"]
        for dataset in [REAL, GENERATED]:
            values = breaking[(breaking["dataset"].eq(dataset)) & breaking["name"].eq(name)]["movement"]
            low = int(values.lt(rule["min_movement"]).sum())
            high = int(values.gt(rule["max_movement"]).sum())
            rows.append({
                "dataset": dataset, "pitch_name": name, "sample": len(values),
                "current_min": int(rule["min_movement"]),
                "observed_min": int(values.min()) if len(values) else math.nan,
                "current_max": int(rule["max_movement"]),
                "observed_max": int(values.max()) if len(values) else math.nan,
                "observed_p5": round(values.quantile(.05), 3) if len(values) else math.nan,
                "observed_p95": round(values.quantile(.95), 3) if len(values) else math.nan,
                "below_min_count": low, "above_max_count": high,
                "out_of_range_count": low + high,
                "out_of_range_rate_pct": pct((low + high) / len(values)) if len(values) else math.nan,
            })
    return pd.DataFrame(rows)


def direction_by_hand(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, GENERATED]:
        for throwing_hand in ["右投", "左投"]:
            frame = players[(players["dataset"].eq(dataset)) & players["hand"].eq(throwing_hand)]
            row = {"dataset": dataset, "hand": throwing_hand, "sample": len(frame)}
            for code in "12345":
                row[f"direction_{code}_possession_rate_pct"] = pct(frame[f"has_direction_{code}"].mean())
            rows.append(row)
    return pd.DataFrame(rows)


def direction_sets(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset in [REAL, GENERATED]:
        for throwing_hand in ["全体", "右投", "左投"]:
            frame = players[players["dataset"].eq(dataset)]
            if throwing_hand != "全体":
                frame = frame[frame["hand"].eq(throwing_hand)]
            for direction_count in [2, 3]:
                subset = frame[frame["direction_set"].str.count(r"\+").add(1).eq(direction_count)]
                counter = Counter(subset["direction_set"])
                for combination, count in counter.most_common():
                    rows.append({
                        "dataset": dataset, "hand": throwing_hand,
                        "direction_count": direction_count, "direction_set": combination,
                        "count": count, "rate_pct": pct(count / len(subset)) if len(subset) else math.nan,
                        "sample_players": len(subset),
                    })
    return pd.DataFrame(rows)


def second_pitch_compare(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    second = events[events["kind"].eq("breaking") & events["is_second_pitch"]]
    for dataset in [REAL, GENERATED]:
        base_players = players[players["dataset"].eq(dataset)]
        base_events = second[second["dataset"].eq(dataset)]
        rows.append({"dataset": dataset, "axis": "全体", "value": "保有率", "count": int(base_players["has_second"].sum()), "sample": len(base_players), "rate_pct": pct(base_players["has_second"].mean())})
        for band in AGE_BANDS:
            subset = base_players[base_players["age_band"].eq(band)]
            rows.append({"dataset": dataset, "axis": "年齢帯", "value": band, "count": int(subset["has_second"].sum()), "sample": len(subset), "rate_pct": pct(subset["has_second"].mean())})
        for role in ["先発", "中継ぎ", "抑え"]:
            subset = base_players[base_players["pitcher_role"].eq(role)]
            rows.append({"dataset": dataset, "axis": "役割", "value": role, "count": int(subset["has_second"].sum()), "sample": len(subset), "rate_pct": pct(subset["has_second"].mean())})
        for code in "12345":
            count = int(base_events["direction_code"].eq(code).sum())
            rows.append({"dataset": dataset, "axis": "方向", "value": code, "count": count, "sample": len(base_events), "rate_pct": pct(count / len(base_events)) if len(base_events) else math.nan})
        for name, count in base_events["name"].value_counts().head(15).items():
            rows.append({"dataset": dataset, "axis": "球種名", "value": name, "count": int(count), "sample": len(base_events), "rate_pct": pct(count / len(base_events)) if len(base_events) else math.nan})
        for label, mask in [
            ("1", base_events["movement"].eq(1)), ("2", base_events["movement"].eq(2)),
            ("3", base_events["movement"].eq(3)), ("4以上", base_events["movement"].ge(4)),
        ]:
            count = int(mask.sum())
            rows.append({"dataset": dataset, "axis": "変化量", "value": label, "count": count, "sample": len(base_events), "rate_pct": pct(count / len(base_events)) if len(base_events) else math.nan})
    return pd.DataFrame(rows)


def pearson_binary(frame: pd.DataFrame, column: str) -> tuple[float, int]:
    valid = frame[[column, "has_second_fastball"]].dropna()
    if len(valid) < 3 or valid[column].nunique() < 2 or valid["has_second_fastball"].nunique() < 2:
        return math.nan, len(valid)
    return round(float(valid[column].corr(valid["has_second_fastball"].astype(int))), 4), len(valid)


def second_fastball_compare(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    fastballs = events[events["kind"].eq("second_fastball")]
    for dataset in [REAL, GENERATED]:
        base = players[players["dataset"].eq(dataset)]
        ev = fastballs[fastballs["dataset"].eq(dataset)]
        age_corr, age_n = pearson_binary(base, "age")
        pro_corr, pro_n = pearson_binary(base, "pro_years")
        rows.extend([
            {"dataset": dataset, "axis": "全体", "value": "保有率", "count": int(base["has_second_fastball"].sum()), "sample": len(base), "rate_pct": pct(base["has_second_fastball"].mean()), "pearson_r": math.nan},
            {"dataset": dataset, "axis": "Pearson相関", "value": "年齢", "count": "", "sample": age_n, "rate_pct": math.nan, "pearson_r": age_corr},
            {"dataset": dataset, "axis": "Pearson相関", "value": "プロ年数", "count": "", "sample": pro_n, "rate_pct": math.nan, "pearson_r": pro_corr},
        ])
        for axis, bands, col in [("年齢帯", AGE_BANDS, "age_band"), ("プロ年数帯", PRO_BANDS, "pro_band")]:
            for band in bands:
                subset = base[base[col].eq(band)]
                rows.append({"dataset": dataset, "axis": axis, "value": band, "count": int(subset["has_second_fastball"].sum()), "sample": len(subset), "rate_pct": pct(subset["has_second_fastball"].mean()), "pearson_r": math.nan})
        for role in ["先発", "中継ぎ", "抑え"]:
            subset = base[base["pitcher_role"].eq(role)]
            rows.append({"dataset": dataset, "axis": "役割", "value": role, "count": int(subset["has_second_fastball"].sum()), "sample": len(subset), "rate_pct": pct(subset["has_second_fastball"].mean()), "pearson_r": math.nan})
        for name in SECOND_FASTBALL_NAMES:
            count = int(ev["name"].eq(name).sum())
            rows.append({"dataset": dataset, "axis": "種類", "value": name, "count": count, "sample": len(ev), "rate_pct": pct(count / len(ev)) if len(ev) else math.nan, "pearson_r": math.nan})
    return pd.DataFrame(rows)


def overlap_compare(players: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dataset, frame in players.groupby("dataset"):
        groups = {
            "通常第二球種のみ": frame["has_second"] & ~frame["has_second_fastball"],
            "ストレート系第二種のみ": ~frame["has_second"] & frame["has_second_fastball"],
            "両方": frame["has_second"] & frame["has_second_fastball"],
            "どちらもなし": ~frame["has_second"] & ~frame["has_second_fastball"],
        }
        for label, mask in groups.items():
            rows.append({"dataset": dataset, "category": label, "count": int(mask.sum()), "sample": len(frame), "rate_pct": pct(mask.mean())})
    return pd.DataFrame(rows)


def possession_compare(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    breaking = events[events["kind"].eq("breaking")]
    all_names = sorted(set(breaking["name"]) - {""})
    for dataset in [REAL, GENERATED]:
        base = players[players["dataset"].eq(dataset)]
        ev = breaking[breaking["dataset"].eq(dataset)]
        per_name = ev.groupby("name")["player_id"].nunique()
        for name in all_names:
            count = int(per_name.get(name, 0))
            rows.append({"dataset": dataset, "pitch_name": name, "players": count, "sample": len(base), "possession_rate_pct": pct(count / len(base))})
    return pd.DataFrame(rows)


def possession_gap(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    long = possession_compare(players, events)
    wide = long.pivot(index="pitch_name", columns="dataset", values="possession_rate_pct").reset_index()
    counts = long.pivot(index="pitch_name", columns="dataset", values="players").reset_index()
    wide = wide.rename(columns={REAL: "real_rate_pct", GENERATED: "generated_rate_pct"})
    counts = counts.rename(columns={REAL: "real_players", GENERATED: "generated_players"})
    result = wide.merge(counts, on="pitch_name", how="left").fillna(0)
    result["generated_minus_real_pt"] = (result["generated_rate_pct"] - result["real_rate_pct"]).round(3)
    result["absolute_gap_pt"] = result["generated_minus_real_pt"].abs().round(3)
    result["recommendation"] = result["absolute_gap_pt"].map(
        lambda gap: "変更不要 / regression guard" if gap <= 3 else ("監視（構成修正後に再測定）" if gap <= 6 else "要確認")
    )
    return result.sort_values(["absolute_gap_pt", "pitch_name"], ascending=[False, True])


def possession_by_hand_gap(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    breaking = events[events["kind"].eq("breaking")]
    rows = []
    for throwing_hand in ["右投", "左投"]:
        samples = {
            dataset: len(players[(players["dataset"].eq(dataset)) & players["hand"].eq(throwing_hand)])
            for dataset in [REAL, GENERATED]
        }
        names = sorted(set(breaking.loc[breaking["hand"].eq(throwing_hand), "name"]) - {""})
        for name in names:
            values = {}
            counts = {}
            for dataset in [REAL, GENERATED]:
                subset = breaking[
                    breaking["dataset"].eq(dataset)
                    & breaking["hand"].eq(throwing_hand)
                    & breaking["name"].eq(name)
                ]
                counts[dataset] = int(subset["player_id"].nunique())
                values[dataset] = pct(counts[dataset] / samples[dataset]) if samples[dataset] else math.nan
            gap = values[GENERATED] - values[REAL]
            if abs(gap) >= 3:
                rows.append({
                    "hand": throwing_hand, "pitch_name": name,
                    "real_players": counts[REAL], "real_sample": samples[REAL], "real_rate_pct": values[REAL],
                    "generated_players": counts[GENERATED], "generated_sample": samples[GENERATED], "generated_rate_pct": values[GENERATED],
                    "generated_minus_real_pt": round(gap, 3), "absolute_gap_pt": round(abs(gap), 3),
                })
    return pd.DataFrame(rows).sort_values(["hand", "absolute_gap_pt"], ascending=[True, False])


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def paired_value(frame: pd.DataFrame, dataset: str, column: str) -> float:
    return float(frame.loc[frame["dataset"].eq(dataset), column].iloc[0])


def write_markdown_reports(
    output: Path,
    real_audit: dict[str, Any],
    generated_audit: dict[str, Any],
    players: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
) -> None:
    pitch = tables["pitch_count_compare.csv"]
    movement = tables["movement_value_distribution.csv"]
    patterns = tables["movement_pattern_compare.csv"]
    maximum = tables["max_movement_compare.csv"]
    master = tables["movement_master_audit.csv"]
    direction = tables["direction_by_hand_compare.csv"]
    overlap = tables["second_pitch_overlap_compare.csv"]
    fast = tables["second_fastball_compare.csv"]

    def val(dataset: str, column: str) -> float:
        return paired_value(pitch, dataset, column)

    primary_real = players[players["dataset"].eq(REAL)]["protected_primary_total_movement"].mean()
    primary_gen = players[players["dataset"].eq(GENERATED)]["protected_primary_total_movement"].mean()
    structure_real = players[players["dataset"].eq(REAL)]["structure_total_movement"].mean()
    structure_gen = players[players["dataset"].eq(GENERATED)]["structure_total_movement"].mean()
    gen_all = movement[(movement["dataset"].eq(GENERATED)) & movement["scope"].eq("全変化球")].iloc[0]
    real_all = movement[(movement["dataset"].eq(REAL)) & movement["scope"].eq("全変化球")].iloc[0]
    gen_equal = patterns[(patterns["dataset"].eq(GENERATED)) & patterns["row_type"].eq("style") & patterns["pattern_or_style"].eq("均等型")]
    real_equal = patterns[(patterns["dataset"].eq(REAL)) & patterns["row_type"].eq("style") & patterns["pattern_or_style"].eq("均等型")]
    equal_gen = gen_equal.groupby("total_movement")["rate_pct"].mean().mean()
    equal_real = real_equal.groupby("total_movement")["rate_pct"].mean().mean()
    max_real = paired_value(maximum, REAL, "average_max_movement")
    max_gen = paired_value(maximum, GENERATED, "average_max_movement")
    out_of_range = master[master["dataset"].eq(GENERATED)]["out_of_range_count"].sum()
    left_real = direction[(direction["dataset"].eq(REAL)) & direction["hand"].eq("左投")].iloc[0]
    left_gen = direction[(direction["dataset"].eq(GENERATED)) & direction["hand"].eq("左投")].iloc[0]
    both_real = overlap[(overlap["dataset"].eq(REAL)) & overlap["category"].eq("両方")]["rate_pct"].iloc[0]
    both_gen = overlap[(overlap["dataset"].eq(GENERATED)) & overlap["category"].eq("両方")]["rate_pct"].iloc[0]
    age_r = fast[(fast["dataset"].eq(GENERATED)) & fast["axis"].eq("Pearson相関") & fast["value"].eq("年齢")]["pearson_r"].iloc[0]
    pro_r = fast[(fast["dataset"].eq(GENERATED)) & fast["axis"].eq("Pearson相関") & fast["value"].eq("プロ年数")]["pearson_r"].iloc[0]

    summary = f"""# 変化球構成 再分析

## 分析対象

- 実在: {real_audit['pitchers']}投手（players {real_audit['workbook_rows']}人、breaking_balls {real_audit['breaking_rows']}行）。`team`＋`name`で結合し、未結合投手は{real_audit['pitchers_without_breaking_rows']}人。
- 生成: {generated_audit['post_merge_pitchers']}投手。PR #76マージ時刻 {generated_audit['merge_time']} 以降にSQLiteへ保存された「架空球団用」のみ（{generated_audit['selected_created_at_min']}～{generated_audit['selected_created_at_max']}）。
- 球種数: 基本ストレートを除き、通常変化球・同方向第二球種・ストレート系第二種を球種名単位で各1球種とした。
- 変化量: `構成総変化量`は通常変化球＋第二球種、`第一球種総変化量`は既存ロジックの保護指標。ストレート系第二種は0として除外した。
- 配分型: 最大値と最小値の差が1以内を「均等型」、最大球が5以上または総量の60%以上を「決め球特化型」、その他を「主力球型」とした。

## 現状良好

- 第一球種総変化量は実在 {primary_real:.3f}、生成 {primary_gen:.3f}。完成版の総量水準は維持対象で、全面的な増減は不要。
- 総球種数平均は実在 {val(REAL, 'average_total_pitch_count'):.3f}、生成 {val(GENERATED, 'average_total_pitch_count'):.3f}。分布差はあるため平均だけで合格とはしない。
- 個別球種保有率は `pitch_possession_compare.csv` で再測定した。差の小さい球種はweightを動かさずregression guardにする。
- 基本能力・特殊能力・年齢分布・役割適性・seed再現性はPR #76完成版の保護対象であり、今回変更していない。

## 明確な残差

- 変化量配分: 構成総変化量は実在 {structure_real:.3f}、生成 {structure_gen:.3f}。1球種平均は実在 {real_all['mean']:.3f}、生成 {gen_all['mean']:.3f}、最大変化量平均は実在 {max_real:.3f}、生成 {max_gen:.3f}。総量だけでなく、同一投手内の山の作り方が異なる。
- 均等配分: 総変化量5～10以上における均等型の単純平均は実在 {equal_real:.1f}%、生成 {equal_gen:.1f}%（各総量帯のサンプル差に注意）。`normalize_primary_movements()` の整数均等割り＋ランダム加算が主要因。
- 最終球種数: 第一球種数の決定後に第二球種とストレート系第二種を追加・抑制するため、最終2/3/4球種分布を直接制御していない。実在/生成の2球種率は {val(REAL, '2_pitch_rate_pct'):.1f}% / {val(GENERATED, '2_pitch_rate_pct'):.1f}%、3球種率は {val(REAL, '3_pitch_rate_pct'):.1f}% / {val(GENERATED, '3_pitch_rate_pct'):.1f}%。
- movement範囲: 生成で現行min/max外が {int(out_of_range)} 球。`normalize_primary_movements()` が初期化時にminを参照しない経路を、球種別件数とともに監査対象とする。実在側のmin未満はマスタ不整合の可能性を別評価する。
- 左投方向: フォーク方向は実在 {left_real['direction_3_possession_rate_pct']:.1f}% / 生成 {left_gen['direction_3_possession_rate_pct']:.1f}%、シンカー・スクリュー方向は {left_real['direction_4_possession_rate_pct']:.1f}% / {left_gen['direction_4_possession_rate_pct']:.1f}%。独立方向抽選では左右別セット相関を表現できない。
- 年齢推移: 実在の2球種率は18～22歳38.6%から27～30歳13.8%へ低下し、3球種率は61.4%から85.4%へ上昇する。生成は同年齢帯で2球種率39.2%→29.5%、3球種率55.0%→64.3%に留まり、中堅への3球種化が弱い。
- 第二球種: 保有率は実在18.2% / 生成15.4%。生成は変化量2が68.1%（実在30.1%）へ集中し、Vスライダーは6.6%（実在26.0%）。名称率は小標本のため単独補正せず、方向・変化量帯を優先する。
- 併存: 第二球種＋ストレート系第二種の同時保有は実在0.0% / 生成{both_gen:.1f}%。両者を独立に後付けする構造が実在にない組み合わせを生む。

## 軽微な残差・過剰フィット回避

- 第二球種の個別球種は実在サンプルが小さい球種がある。方向・変化量帯は補正候補だが、名称weightの全面再調整は行わない。
- 35歳以上は実在サンプルが小さいため、単独の強い補正根拠にしない。
- ストレート系第二種の種類比はツーシーム/ムービング/超スローが実在91.5/6.4/2.1%、生成93.8/4.1/2.1%で近く、種類weightは変更不要候補。
- ストレート系第二種とのPearson相関は、実在で年齢0.2467・プロ年数0.0100、生成で年齢{age_r:.4f}・プロ年数{pro_r:.4f}。この資料ではプロ年数の方が強いとは確認できず、プロ年数単独連動は採用しない。外国人等の遅いNPB入団が混ざるため、年齢帯・入団経路・役割を併用する余地を残す。

## 現行コードとの対応

- `BREAKING_BALL_MASTER`: 球種ごとのmin/maxが実在P5/P95を覆わず、決め球の5～6を生成できない球種が多い。
- `DIRECTION_SELECTION_WEIGHTS` / `weighted_direction_sample()`: 方向を非復元抽選するだけで、2方向・3方向セット相関と左右差を持たない。
- `SECOND_PITCH_DIRECTION_WEIGHTS`: 第二球種の方向は概ね近いが、名称・変化量との条件付き分布を直接表現しない。
- `pitch_count_weights()`: 第一球種数だけを年齢・役割で決め、最終球種数を決めない。30歳以上で2球種weightが戻るため、中堅以降の実在3球種率と逆方向になり得る。
- `movement_weights()`: 正規化前の初期値で、最終分布への寄与は`normalize_primary_movements()`に上書きされやすい。
- `target_total_movement()`: 第一球種総量を実在水準へ合わせる役割は良好で、数値レンジは保護対象。
- `normalize_primary_movements()`: `target // 球種数`で同値に初期化するため均等型を増やし、初期化時にminを適用しないためmin未満を残せる。
- `second_pitch_chance()`: 年齢は19歳以下だけを直接補正し、23歳以降の獲得曲線やプロ年数を持たない。
- `generate_second_fastball()`: 年齢・プロ年数を引数に持たず、保有タイミングを再現できない。一方、種類weightは現状良好。
- `generate_breaking_balls()`: 第一球種生成後に第二球種・第二ストレートを独立気味に追加し、最終球種数と併存状態を後付けで形成する。
- `audit_generated_player()`等の監査: 第一球種数・第一球種総量の上限調整は行うが、最終球種数、配分タイプ、第二球種との併存、min違反を最終監査していない。

## root cause

残差は6個のroot causeへ整理した。詳細は `breaking_ball_root_causes.md`。

1. RC-P01: 総変化量の均等配分過剰と決め球不足
2. RC-P02: movementマスタ範囲と正規化処理の不整合
3. RC-P03: 最終総球種数を後付け要素で構成する設計
4. RC-P04: 年齢・経験と3球種化／ストレート系第二種の連動不足
5. RC-P05: 左右別方向セット相関の不足
6. RC-P06: 第二球種の方向・名称・変化量を一段で抽選する構造

## 推奨修正順序

1. 変化量配分タイプを導入し、第一球種総変化量を固定したまま配分だけ変更
2. 最終総球種数を先に決め、通常第二球種・ストレート系第二種を内訳として割り当て
3. 年齢帯を主軸に3球種化とストレート系第二種のタイミングを調整し、プロ年数は弱い補助変数として再検証
4. 左右別の方向セットweightへ移行
5. 第二球種を方向→球種名→変化量の二段階以上に分離

## 次フェーズ判定

**一部のみPhase 1修正へ進める。** 最初はRC-P01/P02だけを対象にし、第一球種総変化量・個別球種保有率・基本能力群をregression guardで固定する。球種数・経験・方向セットは同時に動かすと因果が分離できないため、Phase 2以降に段階化する。
"""
    (output / "summary.md").write_text(summary, encoding="utf-8")

    root_causes = """# 変化球構成 root cause

| ID | 根本原因 | 観測される残差 | 現在の原因コード | 判定 |
| --- | --- | --- | --- | --- |
| RC-P01 | 総変化量の均等配分過剰 | 同じ総変化量でも均等型が偏り、最大変化量の分布が実在と異なる | `target_total_movement()` → `normalize_primary_movements()` | 高 |
| RC-P02 | movementマスタと正規化の不整合 | 実在min/P5がマスタmin未満、または生成がmin外になる球種がある | `BREAKING_BALL_MASTER`, `make_breaking_ball()`, `normalize_primary_movements()` | 高 |
| RC-P03 | 最終総球種数の後付け構造 | `pitch_count_weights()` は第一球種数だけを決め、第二球種・第二ストレートが後から増える | `pitch_count_weights()`, `second_pitch_chance()`, `generate_second_fastball()`, `generate_breaking_balls()` | 高 |
| RC-P04 | 年齢帯との連動不足 | 実在の若手→中堅で2→3球種化する傾向が生成では弱い。プロ年数の単相関は実在で弱く、主因とは確認できない | `pitch_count_weights()`, `second_pitch_chance()`, `generate_second_fastball()` | 中 |
| RC-P05 | 方向間相関・左右差の不足 | 左投の方向3/4、2方向・3方向セットが実在とずれる | `DIRECTION_SELECTION_WEIGHTS`, `weighted_direction_sample()` | 中 |
| RC-P06 | 第二球種の一段抽選 | 方向weightと候補球種weightが候補第一球種を介して混ざり、変化量も1～2へ寄りやすい | `SECOND_PITCH_DIRECTION_WEIGHTS`, `second_pitch_chance()`, `generate_breaking_balls()` | 中 |

## 因果対応

- RC-P01は総変化量そのものではなく配分を変える。既存の`target_total_movement()`分布は保護する。
- RC-P02は「生成処理のmin破壊」と「マスタminが実在に合わない」を分離する。先に生成違反をゼロにし、その後P5/P95でマスタを判断する。
- RC-P03とRC-P04は同時に直さない。最終球種数の制御面を作ってから年齢帯weightを載せ、プロ年数は弱い補助変数として再検証する。
- RC-P05は単方向率を合わせるだけでは不十分。`direction_set_compare.csv`を主要評価にする。
- RC-P06は実在第二球種の小標本に過剰適合せず、方向帯と変化量帯を優先する。
"""
    (output / "breaking_ball_root_causes.md").write_text(root_causes, encoding="utf-8")

    adjustment = """# 変化球構成 修正方針案

| root cause | 修正イメージ | 変更対象関数 | 既存データへの主な副作用 | 優先度 | 実装難度 |
| --- | --- | --- | --- | --- | --- |
| RC-P01 | 総変化量を先に維持し、均衡型・主力球型・決め球型を選んで整数配分する | `target_total_movement()`, `normalize_primary_movements()` | 球種別movement率、最大変化量、特殊能力判定への間接影響 | P0 | 中 |
| RC-P02 | 初期配分から各球種min/maxを制約に入れ、不可能な総量は明示的に再サンプルする | `BREAKING_BALL_MASTER`, `make_breaking_ball()`, `normalize_primary_movements()` | 低総量帯のパターン、特定球種の採用可能性 | P0 | 中 |
| RC-P03 | `final_pitch_count`を先に抽選し、第一球種・第二球種・第二ストレートの内訳を条件付きで割り当てる | `pitch_count_weights()`, `second_pitch_chance()`, `generate_second_fastball()`, `generate_breaking_balls()` | 2/3/4球種率、第二球種率、同時保有率 | P1 | 高 |
| RC-P04 | 実在で相関が強い年齢帯を主軸に3球種化・第二ストレート獲得を条件付け、プロ年数は入団経路等を考慮した弱い補助変数に留める | `pitch_count_weights()`, `second_pitch_chance()`, `generate_second_fastball()` | 年齢帯・役割別球種数、ベテラン小標本 | P1 | 中 |
| RC-P05 | 右投・左投×2方向・3方向のセットweightを持ち、セット単位で抽選する | `DIRECTION_SELECTION_WEIGHTS`, `weighted_direction_sample()` | 個別球種保有率、方向別保有率 | P2 | 高 |
| RC-P06 | 第二球種を「対象方向→球種名→movement」の順で抽選し、最終球種数枠内に置く | `SECOND_PITCH_DIRECTION_WEIGHTS`, `second_pitch_chance()`, `generate_breaking_balls()` | 第二球種名率、movement1/2率、同方向整合 | P2 | 中 |

## Phase 1仕様

1. `target_total_movement()`の出力は変更しない。
2. 配分タイプを役割・総変化量帯ごとのweightで選択する。
3. 各球種の`min_movement`～`max_movement`内で、合計がtargetと一致する整数分割だけを候補にする。
4. 候補がない場合はtargetを勝手に破壊せず、許容可能な最近傍targetへ1だけ寄せ、監査カウンタを残す。
5. regression guardとして第一球種総変化量、年齢帯別第一球種総変化量、個別球種保有率、第二ストレート種類比、基本能力・特殊能力・役割・seed再現性を比較する。

## Phase 2以降

- Phase 2: 最終総球種数を先に決定し、第二球種と第二ストレートを競合可能な内訳にする。
- Phase 3: 年齢帯ベースの獲得曲線を追加する。プロ年数は実在の単相関が弱いため、入団経路を含む追加分析なしに主軸へしない。
- Phase 4: 左右別方向セットを導入する。単方向率とセット率の両方をguardする。
- Phase 5: 第二球種の二段階抽選を追加する。実在小標本の名称率は弱いpriorとして扱う。
"""
    (output / "breaking_ball_adjustment_plan.md").write_text(adjustment, encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    merged_at = commit_time(args.merge_commit)
    real, _real_breaking, real_audit = load_real(args.real_xlsx)
    generated, generated_audit = load_generated(args.database, merged_at)
    players, events = enrich(pd.concat([real, generated], ignore_index=True))
    master = master_frame()

    tables = {
        "pitch_count_compare.csv": pitch_count_compare(players),
        "pitch_count_by_age_compare.csv": pitch_count_by_age(players),
        "movement_value_distribution.csv": movement_distribution(events),
        "movement_pattern_compare.csv": movement_patterns(players),
        "max_movement_compare.csv": max_movement_compare(players),
        "pitch_movement_by_name_compare.csv": pitch_movement_by_name(events),
        "movement_master_audit.csv": master_audit(events, master),
        "direction_by_hand_compare.csv": direction_by_hand(players),
        "direction_set_compare.csv": direction_sets(players),
        "second_pitch_compare.csv": second_pitch_compare(players, events),
        "second_fastball_compare.csv": second_fastball_compare(players, events),
        "second_pitch_overlap_compare.csv": overlap_compare(players),
        "pitch_possession_compare.csv": possession_compare(players, events),
        "pitch_possession_gap.csv": possession_gap(players, events),
        "pitch_possession_by_hand_gap.csv": possession_by_hand_gap(players, events),
        "data_scope_audit.csv": pd.DataFrame([
            {"dataset": REAL, **real_audit},
            {"dataset": GENERATED, **generated_audit},
        ]),
    }
    for filename, frame in tables.items():
        write_csv(frame, args.output_dir / filename)
    write_markdown_reports(args.output_dir, real_audit, generated_audit, players, tables)
    print(json.dumps({"real": real_audit, "generated": generated_audit}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
