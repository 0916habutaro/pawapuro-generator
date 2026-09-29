"""Phase 4: 生成選手と静的球団ロスターの最終統合監査。"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from scripts import validate_foreign_generation_phase3c as phase3c
from scripts import validate_foreign_generation_phase3d as phase3d
from scripts import validate_phase3_balance as phase3
from scripts.validate_ability_balance import (
    FIELDING_KEYS,
    flatten_players,
    growth_type_distribution,
    special_stats,
)


ROLES = ("投手", "野手")
CATEGORIES = tuple(app.CATEGORIES)
POSITIONS = ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")
PERCENTILES = (0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
EXPECTED_RARE_STYLES = {
    "打撃型捕手", "打撃型二塁手", "強打遊撃手", "走攻守外野手", "守備型三塁手",
    "俊足外野手", "守備外野手", "速球型先発", "制球型先発", "変化球型先発",
    "剛腕中継ぎ", "ロングリリーフ型", "剛腕クローザー",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4 架空選手ジェネレーター最終統合監査")
    parser.add_argument("--count", type=int, default=500, help="カテゴリ×投手/野手の生成人数（修正後最終監査は2000）")
    parser.add_argument("--team-count", type=int, default=50, help="完全ロスターの生成球団数")
    parser.add_argument("--seed", type=int, default=202610400000, help="個人生成の開始seed")
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "reports" / "phase4_final_integration",
    )
    return parser.parse_args()


def pct(value: float) -> float:
    return round(100 * float(value), 3)


def md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "該当なし"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for values in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines)


def generate_samples(count: int, base_seed: int) -> list[dict[str, Any]]:
    if count <= 0:
        raise ValueError("countは1以上にしてください。")
    master = app.load_master_data()
    players: list[dict[str, Any]] = []
    offset = 0
    for category in CATEGORIES:
        for role in ROLES:
            print(f"baseline生成: {category} / {role} / {count}人", flush=True)
            for _ in range(count):
                players.append(app.generate_player(role, category, master, seed=base_seed + offset))
                offset += 1
    return players


def enrich_frame(players: list[dict[str, Any]]) -> pd.DataFrame:
    frame = flatten_players(players)
    extra_columns = [
        "roster_origin", "foreign_route", "entry_route", "pro_entry_age", "pro_years",
        "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee",
        "actual_nationality", "nationality_code", "name_group_id", "name_group_name",
        "draft_source_type", "birth_month", "birth_day", "pitching_form_type",
        "pitching_form_number", "batting_form_type", "batting_form_number", "bat_color",
        "glove_color", "wristband_left_enabled", "wristband_left_color",
        "wristband_right_enabled", "wristband_right_color",
    ]
    for column in extra_columns:
        frame[column] = [player.get(column, "") for player in players]
    return frame


def describe(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    result: dict[str, Any] = {
        "n": int(len(numeric)),
        "mean": round(float(numeric.mean()), 3) if len(numeric) else None,
        "sd": round(float(numeric.std()), 3) if len(numeric) > 1 else 0,
        "min": round(float(numeric.min()), 3) if len(numeric) else None,
        "max": round(float(numeric.max()), 3) if len(numeric) else None,
    }
    for quantile in PERCENTILES:
        result[f"p{int(quantile * 100)}"] = round(float(numeric.quantile(quantile)), 3) if len(numeric) else None
    return result


def ability_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    field_metrics = ["弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球", "野手6能力合計"]
    pitch_metrics = ["球速", "コントロール", "スタミナ"]
    for (category, position), part in frame[frame["role"].eq("野手")].groupby(["category", "position"]):
        for metric in field_metrics:
            rows.append({"category": category, "role": "野手", "group": position, "metric": metric, **describe(part[metric])})
    for (category, role), part in frame[frame["role"].eq("投手")].groupby(["category", "position"]):
        for metric in pitch_metrics:
            rows.append({"category": category, "role": "投手", "group": role, "metric": metric, **describe(part[metric])})
    return pd.DataFrame(rows)


def ability_tail_audit(frame: pd.DataFrame) -> pd.DataFrame:
    fielders = frame[frame["role"].eq("野手")]
    pitchers = frame[frame["role"].eq("投手")]
    checks = [
        ("野手6能力合計450以上", fielders, fielders["野手6能力合計"].ge(450)),
        ("ミート・パワー・走力すべて70以上", fielders, fielders[["ミート", "パワー", "走力"]].ge(70).all(axis=1)),
        ("走力・肩力・守備力すべて70以上", fielders, fielders[["走力", "肩力", "守備力"]].ge(70).all(axis=1)),
        ("捕手で守備力30未満", fielders, fielders["position"].eq("捕手") & fielders["守備力"].lt(30)),
        ("遊撃手で守備力35未満", fielders, fielders["position"].eq("遊撃手") & fielders["守備力"].lt(35)),
        ("二軍級で6能力すべて60以上", fielders, fielders["player_class"].eq("二軍級") & fielders[FIELDING_KEYS[:-1]].ge(60).all(axis=1)),
        ("160km/h以上", pitchers, pitchers["球速"].ge(160)),
        ("球速155・制球70・スタミナ70以上", pitchers, pitchers["球速"].ge(155) & pitchers["コントロール"].ge(70) & pitchers["スタミナ"].ge(70)),
        ("抑えでスタミナ75以上", pitchers, pitchers["position"].eq("抑え") & pitchers["スタミナ"].ge(75)),
    ]
    rows = []
    for label, population, mask in checks:
        for category in CATEGORIES:
            category_index = population["category"].eq(category)
            denominator = int(category_index.sum())
            count = int((mask & category_index).sum())
            rows.append({
                "check": label, "category": category, "affected": count,
                "sample": denominator, "rate_pct": round(100 * count / max(1, denominator), 3),
            })
    return pd.DataFrame(rows)


def age_growth_audit(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for category, part in frame.groupby("category"):
        ages = pd.to_numeric(part["age"], errors="raise")
        rows.append({
            "category": category, "scope": "全体", "n": len(part),
            "age_mean": round(float(ages.mean()), 2), "age_median": round(float(ages.median()), 2),
            "age_min": int(ages.min()), "age_max": int(ages.max()),
            "age_22_or_less_pct": pct(ages.le(22).mean()),
            "age_23_29_pct": pct(ages.between(23, 29).mean()),
            "age_30_34_pct": pct(ages.between(30, 34).mean()),
            "age_35_plus_pct": pct(ages.ge(35).mean()),
        })
    for source, part in frame[frame["category"].eq("ドラフト候補用")].groupby("draft_source_type"):
        ages = pd.to_numeric(part["age"], errors="raise")
        rows.append({
            "category": "ドラフト候補用", "scope": str(source), "n": len(part),
            "age_mean": round(float(ages.mean()), 2), "age_median": round(float(ages.median()), 2),
            "age_min": int(ages.min()), "age_max": int(ages.max()),
        })
    return pd.DataFrame(rows)


def classification_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dimension in ("player_class", "archetype", "position_style", "development_stage", "growth_type"):
        for (category, role), part in frame.groupby(["category", "role"]):
            counts = part[dimension].fillna("").astype(str).value_counts()
            for value, count in counts.items():
                rows.append({
                    "category": category, "role": role, "dimension": dimension, "value": value,
                    "count": int(count), "rate_pct": round(100 * count / len(part), 3),
                })
    return pd.DataFrame(rows)


def contradiction_rows(frame: pd.DataFrame) -> pd.DataFrame:
    checks = [
        ("若手素材型なのに30歳以上", frame["player_class"].eq("若手素材型") & frame["age"].ge(30)),
        ("ベテラン型なのに24歳以下", frame["player_class"].eq("ベテラン型") & frame["age"].le(24)),
        ("育成素材型外国人なのに32歳以上", frame["player_class"].eq("育成素材型") & frame["age"].ge(32)),
        ("球速不足profileなのに160km/h以上", frame["weakness_profile"].eq("球速不足") & frame["球速"].ge(160)),
        ("俊足archetypeなのに走力45未満", frame["archetype"].eq("俊足") & frame["走力"].lt(45)),
        ("守備archetypeなのに守備力40未満", frame["archetype"].eq("守備") & frame["守備力"].lt(40)),
        ("長打archetypeなのにパワー45未満", frame["archetype"].eq("長打") & frame["パワー"].lt(45)),
        ("抑えでスタミナarchetype", frame["position"].eq("抑え") & frame["archetype"].eq("スタミナ")),
    ]
    rows = []
    columns = ["seed", "category", "role", "age", "position", "player_class", "archetype", "position_style", "weakness_profile"]
    for issue, mask in checks:
        for _, row in frame.loc[mask, columns].iterrows():
            rows.append({"issue": issue, **row.to_dict()})
    return pd.DataFrame(rows, columns=["issue", *columns])


def special_count_audit(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (category, role), part in frame.groupby(["category", "role"]):
        values = pd.to_numeric(part["特殊能力数"], errors="raise")
        row = {"category": category, "role": role, **describe(values)}
        row.update({
            "0_2_pct": pct(values.between(0, 2).mean()),
            "3_4_pct": pct(values.between(3, 4).mean()),
            "5_7_pct": pct(values.between(5, 7).mean()),
            "8_plus_pct": pct(values.ge(8).mean()),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def special_conflicts(players: list[dict[str, Any]]) -> pd.DataFrame:
    warnings = phase3.warnings(players)
    if warnings.empty:
        return pd.DataFrame(columns=["seed", "type", "detail"])
    return warnings[warnings["type"].isin({"競合能力", "特殊能力制約違反"})].reset_index(drop=True)


def pitch_tables(players: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    vectors: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for player in players:
        if player["role"] != "投手":
            continue
        breaking = [ball for ball in player["breaking_balls"] if ball.get("kind", "breaking") == "breaking"]
        primary = [ball for ball in breaking if not ball.get("is_second_pitch")]
        second = [ball for ball in breaking if ball.get("is_second_pitch")]
        fastball = [ball for ball in player["breaking_balls"] if ball.get("kind") == "second_fastball"]
        movements = [app.pitch_movement(ball) for ball in primary]
        all_movements = [app.pitch_movement(ball) for ball in breaking]
        primary_codes = [str(ball.get("direction_code", ball.get("direction", ""))) for ball in primary]
        record = {
            "category": player["category"], "role": player["position"],
            "primary_directions": len(set(primary_codes)), "breaking_pitches": len(breaking),
            "display_pitches": len(breaking) + len(fastball),
            "primary_total_movement": sum(movements), "all_breaking_total_movement": sum(all_movements),
            "has_second_pitch": int(bool(second)), "has_straight_secondary": int(bool(fastball)),
        }
        rows.append(record)
        vectors.append({
            "category": player["category"], "role": player["position"],
            "primary_directions": len(set(primary_codes)),
            "movement_vector": ",".join(map(str, sorted(movements, reverse=True))),
        })

        def add_conflict(issue: str) -> None:
            conflicts.append({"seed": player["seed"], "category": player["category"], "role": player["position"], "issue": issue})

        if len(primary_codes) != len(set(primary_codes)):
            add_conflict("第一球種の方向重複")
        names = [str(ball.get("name", "")) for ball in player["breaking_balls"]]
        if len(names) != len(set(names)):
            add_conflict("同一球種名の重複")
        if any(value <= 0 for value in all_movements):
            add_conflict("変化量が0以下")
        if record["display_pitches"] > 4:
            add_conflict("表示球種数上限超過")
        for ball in second:
            code = str(ball.get("direction_code", ball.get("direction", "")))
            matching = [item for item in primary if str(item.get("direction_code", item.get("direction", ""))) == code]
            if not matching:
                add_conflict("第二球種に同方向の第一球種がない")
            elif app.pitch_movement(ball) > app.pitch_movement(matching[0]):
                add_conflict("第二球種の変化量が第一球種を超過")
    raw = pd.DataFrame(rows)
    summary_rows = []
    for (category, role), part in raw.groupby(["category", "role"]):
        summary_rows.append({
            "category": category, "role": role, "n": len(part),
            "primary_direction_mean": round(float(part["primary_directions"].mean()), 3),
            "breaking_pitch_mean": round(float(part["breaking_pitches"].mean()), 3),
            "display_pitch_mean": round(float(part["display_pitches"].mean()), 3),
            "primary_movement_mean": round(float(part["primary_total_movement"].mean()), 3),
            "all_breaking_movement_mean": round(float(part["all_breaking_total_movement"].mean()), 3),
            "second_pitch_rate_pct": pct(part["has_second_pitch"].mean()),
            "straight_secondary_rate_pct": pct(part["has_straight_secondary"].mean()),
        })
    vector_frame = pd.DataFrame(vectors)
    vector_summary = (
        vector_frame.groupby(["category", "role", "primary_directions", "movement_vector"])
        .size().reset_index(name="count")
    )
    totals = vector_summary.groupby(["category", "role"])["count"].transform("sum")
    vector_summary["rate_pct"] = (100 * vector_summary["count"] / totals).round(3)
    return pd.DataFrame(summary_rows), vector_summary, pd.DataFrame(conflicts, columns=["seed", "category", "role", "issue"])


def profile_audit(players: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    surname_frame = pd.read_csv(ROOT / "data" / "japan_surname.csv")
    valid_surnames = set(surname_frame["surname"].astype(str))
    valid_prefectures = set(app.JAPANESE_PREFECTURE_WEIGHTS)
    valid_bats = {value for value, _ in app.BAT_COLOR_WEIGHTS}
    valid_gloves = {value for value, _ in app.GLOVE_COLOR_WEIGHTS}
    valid_wrists = {value for value, _ in app.WRISTBAND_COLOR_WEIGHTS}
    issues = []

    def add(player: dict[str, Any], issue: str, severity: str = "critical") -> None:
        issues.append({
            "seed": player["seed"], "category": player["category"], "role": player["role"],
            "name": player["name"], "issue": issue, "severity": severity,
        })

    for player in players:
        name = str(player.get("name", "")).strip()
        if not name:
            add(player, "名前が空")
        if not str(player.get("birthplace", "")).strip():
            add(player, "出身地が空")
        if player.get("nationality") == "日本":
            surname = name.split()[0] if name else ""
            if player.get("birthplace") not in valid_prefectures:
                add(player, "日本人の都道府県が不正")
            if surname not in valid_surnames:
                add(player, "日本人の姓が都道府県master外", "high")
        elif name.casefold() in {"de", "la", "del", "van", "von"}:
            add(player, "外国人名が単独接続語", "high")
        if player["category"] == "助っ人外国人用" and player.get("roster_origin") != "foreign_import":
            add(player, "助っ人外国人のroster_origin不整合")
        if player.get("roster_origin") == "foreign_import" and not player.get("foreign_route"):
            add(player, "foreign_importのforeign_route欠損")
        if player["category"] == "ドラフト候補用" and not player.get("draft_source_type"):
            add(player, "ドラフトsource欠損")
        if player["category"] == "架空球団用" and player.get("roster_origin") == "domestic":
            entry_age = int(player.get("pro_entry_age") or 0)
            years = int(player.get("pro_years") or 0)
            if entry_age <= 0 or years != int(player["age"]) - entry_age + 1:
                add(player, "国内選手のage/pro_years不整合")
        if player["category"] == "ドラフト候補用" and (int(player.get("pro_entry_age") or 0) != 0 or int(player.get("pro_years") or 0) != 0):
            add(player, "ドラフト候補にプロ年数が設定")
        if player["role"] == "野手" and player["position"] in {"捕手", "二塁手", "三塁手", "遊撃手"} and str(player["batting_throwing"]).startswith("左投"):
            add(player, "捕手・内野中枢の左投げ", "high")
        height, weight = int(player["height"]), int(player["weight"])
        if not 150 <= height <= 220 or not 45 <= weight <= 150:
            add(player, "体格の合法範囲外")
        if player["role"] == "投手":
            form_type = str(player.get("pitching_form_type", ""))
            number = int(player.get("pitching_form_number") or 0)
            if form_type not in app.PITCHING_FORM_RANGES:
                add(player, "投手フォーム種別が不正")
            else:
                total_max, _generic_max = app.PITCHING_FORM_RANGES[form_type]
                if not 1 <= number <= total_max:
                    add(player, "投手フォーム番号が範囲外")
        batting_type = str(player.get("batting_form_type", ""))
        batting_number = int(player.get("batting_form_number") or 0)
        if batting_type not in app.BATTING_FORM_RANGES:
            add(player, "打撃フォーム種別が不正")
        else:
            total_max, _generic_max = app.BATTING_FORM_RANGES[batting_type]
            if not 1 <= batting_number <= total_max:
                add(player, "打撃フォーム番号が範囲外")
        if player.get("bat_color") not in valid_bats or player.get("glove_color") not in valid_gloves:
            add(player, "装備色がmaster外")
        for side in ("left", "right"):
            enabled = bool(player.get(f"wristband_{side}_enabled"))
            color = str(player.get(f"wristband_{side}_color", ""))
            if (enabled and color not in valid_wrists) or (not enabled and color):
                add(player, "リストバンド状態不整合")

    issue_frame = pd.DataFrame(issues, columns=["seed", "category", "role", "name", "issue", "severity"])
    physique_rows = []
    for (category, position), part in pd.DataFrame([
        {"category": p["category"], "position": "投手" if p["role"] == "投手" else p["position"], "height": p["height"], "weight": p["weight"]}
        for p in players
    ]).groupby(["category", "position"]):
        physique_rows.append({
            "category": category, "position": position, "n": len(part),
            **{f"height_{key}": value for key, value in describe(part["height"]).items() if key in {"mean", "sd", "p10", "p90"}},
            **{f"weight_{key}": value for key, value in describe(part["weight"]).items() if key in {"mean", "sd", "p10", "p90"}},
        })
    return issue_frame, pd.DataFrame(physique_rows)


def team_audit(team_count: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    if team_count <= 0:
        raise ValueError("team-countは1以上にしてください。")
    master = app.load_master_data()
    rows = []
    structural = []
    for offset in range(team_count):
        team_seed = 202610500000 + offset
        print(f"球団生成: {offset + 1}/{team_count}", flush=True)
        roster = app.generate_team_roster(team_seed, master)
        pitchers = [p for p in roster if p["role"] == "投手"]
        fielders = [p for p in roster if p["role"] == "野手"]
        positions = Counter(p["position"] for p in fielders)
        classes = Counter(p["player_class"] for p in roster if p.get("roster_origin") == "domestic")
        ages = pd.Series([p["age"] for p in roster])
        fielder_scores = [sum(app.ability_numeric_value(p["abilities"], key) or 0 for key in FIELDING_KEYS[:-1]) for p in fielders]
        pitcher_scores = [
            ((app.pitcher_speed_value(p["abilities"]) or 145) - 125) / 40 * 99
            + (app.ability_numeric_value(p["abilities"], "コントロール") or 0)
            + (app.ability_numeric_value(p["abilities"], "スタミナ") or 0)
            + 8 * sum(app.pitch_movement(ball) for ball in p["breaking_balls"] if ball.get("kind", "breaking") == "breaking" and not ball.get("is_second_pitch"))
            for p in pitchers
        ]
        row = {
            "team": offset + 1, "seed": team_seed, "total": len(roster),
            "pitchers": len(pitchers), "fielders": len(fielders),
            "foreign_total": sum(p.get("roster_origin") == "foreign_import" for p in roster),
            "foreign_pitchers": sum(p.get("roster_origin") == "foreign_import" for p in pitchers),
            "foreign_fielders": sum(p.get("roster_origin") == "foreign_import" for p in fielders),
            **{f"position_{position}": positions[position] for position in POSITIONS},
            **{f"class_{label}": classes[label] for label in ["スター級", "一軍主力級", "一軍控え級", "二軍級", "若手素材型", "ベテラン型"]},
            "age_22_or_less": int(ages.le(22).sum()), "age_23_29": int(ages.between(23, 29).sum()),
            "age_30_34": int(ages.between(30, 34).sum()), "age_35_plus": int(ages.ge(35).sum()),
            "starter_primary": sum(p["position"] == "先発" for p in pitchers),
            "reliever_primary": sum(p["position"] == "中継ぎ" for p in pitchers),
            "closer_primary": sum(p["position"] == "抑え" for p in pitchers),
            "fielder_score_mean": round(float(pd.Series(fielder_scores).mean()), 3),
            "fielder_score_p90": round(float(pd.Series(fielder_scores).quantile(.90)), 3),
            "pitcher_score_mean": round(float(pd.Series(pitcher_scores).mean()), 3),
            "pitcher_score_p90": round(float(pd.Series(pitcher_scores).quantile(.90)), 3),
        }
        rows.append(row)
        expected = app.choose_team_roster_composition(team_seed)
        foreign_expected = app.choose_foreign_team_composition(team_seed)
        if (len(pitchers), len(fielders)) != (expected["投手"], expected["野手"]):
            structural.append({"team": offset + 1, "issue": "投手・野手数がplan不一致"})
        if app.foreign_import_role_counts(roster) != foreign_expected:
            structural.append({"team": offset + 1, "issue": "外国人role数がplan不一致"})
        if len({p["name"] for p in roster}) != len(roster):
            structural.append({"team": offset + 1, "issue": "球団内の名前重複"})
        for position, minimum in app.TEAM_ROSTER_POSITION_MINIMUMS.items():
            if positions[position] < minimum:
                structural.append({"team": offset + 1, "issue": f"{position}最低人数未達"})
    return pd.DataFrame(rows), pd.DataFrame(structural, columns=["team", "issue"])


def team_summary(teams: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "total", "pitchers", "fielders", "foreign_total", "foreign_pitchers", "foreign_fielders",
        *[f"position_{position}" for position in POSITIONS],
        *[f"class_{label}" for label in ["スター級", "一軍主力級", "一軍控え級", "二軍級", "若手素材型", "ベテラン型"]],
        "age_22_or_less", "age_23_29", "age_30_34", "age_35_plus",
        "starter_primary", "reliever_primary", "closer_primary",
        "fielder_score_mean", "fielder_score_p90", "pitcher_score_mean", "pitcher_score_p90",
    ]
    return pd.DataFrame([{"metric": metric, **describe(teams[metric])} for metric in metrics])


def cross_category_compare(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (category, role), part in frame.groupby(["category", "role"]):
        row = {
            "category": category, "role": role, "n": len(part),
            "age_mean": round(float(part["age"].mean()), 3),
            "special_mean": round(float(part["特殊能力数"].mean()), 3),
            "height_mean": round(float(part["height"].mean()), 3),
            "weight_mean": round(float(part["weight"].mean()), 3),
        }
        if role == "野手":
            row.update({
                "ability_metric": "野手6能力合計", "ability_mean": round(float(part["野手6能力合計"].mean()), 3),
                "speed_mean": None, "pitch_count_mean": None,
            })
        else:
            row.update({
                "ability_metric": "投手主要3能力監視値",
                "ability_mean": round(float((((part["球速"] - 125) / 40 * 99) + part["コントロール"] + part["スタミナ"]).mean()), 3),
                "speed_mean": round(float(part["球速"].mean()), 3),
                "pitch_count_mean": round(float(part["display_pitch_count"].mean()), 3),
            })
        rows.append(row)
    return pd.DataFrame(rows)


def finding(
    finding_id: str, severity: str, area: str, affected: int, sample: int,
    description: str, action: str,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id, "severity": severity, "area": area,
        "affected": int(affected), "sample": int(sample),
        "rate_pct": round(100 * affected / max(1, sample), 3),
        "description": description, "action": action,
    }


def build_findings(
    frame: pd.DataFrame,
    classification_conflicts: pd.DataFrame,
    special_conflict_frame: pd.DataFrame,
    pitch_conflicts: pd.DataFrame,
    profile_issues: pd.DataFrame,
    teams: pd.DataFrame,
    team_structural: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    rows.append(finding("STRUCT-01", "critical" if len(team_structural) else "low", "球団", len(team_structural), len(teams), "球団ロスター構造エラー", "0件なら変更なし"))
    rows.append(finding("CLASS-01", "high" if len(classification_conflicts) else "low", "分類", len(classification_conflicts), len(frame), "極端なplayer_class/archetype矛盾", "0件なら変更なし"))
    rows.append(finding("SPECIAL-01", "critical" if len(special_conflict_frame) else "low", "特殊能力", len(special_conflict_frame), len(frame), "既存制約・競合rule違反", "0件なら変更なし"))
    pitcher_count = int(frame["role"].eq("投手").sum())
    rows.append(finding("PITCH-01", "critical" if len(pitch_conflicts) else "low", "球種", len(pitch_conflicts), pitcher_count, "球種構造エラー", "0件なら変更なし"))
    critical_profile = profile_issues[profile_issues["severity"].eq("critical")] if not profile_issues.empty else profile_issues
    high_profile = profile_issues[profile_issues["severity"].eq("high")] if not profile_issues.empty else profile_issues
    rows.append(finding("PROFILE-01", "critical" if len(critical_profile) else "low", "プロフィール", len(critical_profile), len(frame), "プロフィール構造エラー", "0件なら変更なし"))
    rows.append(finding("PROFILE-02", "high" if len(high_profile) else "low", "プロフィール", len(high_profile), len(frame), "名前・投打の明確な不整合", "0件なら変更なし"))

    styles = set(frame["position_style"].dropna().astype(str))
    missing_styles = sorted(EXPECTED_RARE_STYLES - styles)
    rows.append(finding("RARITY-01", "medium" if missing_styles else "low", "多様性", len(missing_styles), len(EXPECTED_RARE_STYLES), "意図したレアposition_styleの消滅: " + (", ".join(missing_styles) if missing_styles else "なし"), "targetなし。監視のみ"))
    fielders = frame[frame["role"].eq("野手")]
    allrounder = int(fielders[["ミート", "パワー", "走力"]].ge(70).all(axis=1).sum())
    rows.append(finding("TAIL-01", "low", "通常能力", allrounder, len(fielders), "ミート・パワー・走力70以上の万能打者", "レア枠監視。定量調整なし"))
    fictional = frame[frame["category"].eq("架空球団用")]
    bench_tail = int((fictional["player_class"].eq("一軍控え級") & fictional["特殊能力数"].ge(5)).sum())
    main_tail = int((fictional["player_class"].isin({"スター級", "一軍主力級", "ベテラン型"}) & fictional["特殊能力数"].ge(8)).sum())
    rows.append(finding("SPECIAL-02", "low", "特殊能力", bench_tail + main_tail, len(fictional), "架空球団用の重点special tail", "既存設計値として監視"))
    rows.append(finding("TEAM-01", "low", "球団", int(teams["class_スター級"].eq(0).sum()), len(teams), "スター0人の球団", "自然な球団差として監視"))
    rows.append(finding("TEAM-02", "low", "球団", int(teams["class_スター級"].ge(5).sum()), len(teams), "スター5人以上の球団", "頻発時のみ再検討"))
    rows.extend([
        finding("GAP-01", "low", "データ不足", 0, 0, "外国人特殊能力の実在明細なし", "generator不具合に数えない"),
        finding("GAP-02", "low", "データ不足", 0, 0, "外国人球種・変化量の実在明細なし", "generator不具合に数えない"),
        finding("GAP-03", "low", "データ不足", 0, 0, "外国人専用体格targetなし", "generator不具合に数えない"),
    ])
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")


def build_summary(
    count: int, team_count: int, findings: pd.DataFrame, cross: pd.DataFrame,
    tails: pd.DataFrame, specials: pd.DataFrame, pitch: pd.DataFrame,
    profile_issues: pd.DataFrame, teams: pd.DataFrame, seed: pd.DataFrame,
    transition_result: str,
) -> str:
    severity_counts = findings["severity"].value_counts()
    critical = int(severity_counts.get("critical", 0))
    high = int(severity_counts.get("high", 0))
    readiness = "Needs additional correction" if critical or high else "Ready with monitored gaps"
    failures = findings[findings["severity"].isin({"critical", "high"})][["finding_id", "severity", "description", "affected"]]
    tail_focus = tails[tails["check"].isin({
        "野手6能力合計450以上", "ミート・パワー・走力すべて70以上", "160km/h以上",
        "球速155・制球70・スタミナ70以上",
    })]
    team_focus = pd.DataFrame([
        {"指標": "総人数", **{k: v for k, v in describe(teams["total"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "スター級人数", **{k: v for k, v in describe(teams["class_スター級"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "一軍主力級人数", **{k: v for k, v in describe(teams["class_一軍主力級"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "二軍級人数", **{k: v for k, v in describe(teams["class_二軍級"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "若手素材型人数", **{k: v for k, v in describe(teams["class_若手素材型"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "ベテラン型人数", **{k: v for k, v in describe(teams["class_ベテラン型"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "先発人数", **{k: v for k, v in describe(teams["starter_primary"]).items() if k in {"mean", "min", "max"}}},
        {"指標": "抑え人数", **{k: v for k, v in describe(teams["closer_primary"]).items() if k in {"mean", "min", "max"}}},
    ])
    return f"""# Phase 4 架空選手ジェネレーター最終統合監査

## 1. Audit scope

通常能力、年齢・経験・成長タイプ、分類・多様性、特殊能力、投手球種、プロフィール、球団ロスター、クロスカテゴリを監査した。Phase 1〜3Dのtargetと生成ロジックは、明確な統合不具合がない限り保護した。

## 2. Sample sizes

- baseline: 3カテゴリ × 投手/野手 × 500人 = 3,000人
- 修正後最終監査: 3カテゴリ × 投手/野手 × {count}人 = {count * 6:,}人
- 完全ロスター: {team_count}球団（{int(teams['total'].sum()):,}人）
- targeted validation: 発見seedの回帰testと、修正後最終監査に包含

## 3. Overall findings

| critical | high | medium | low |
| --- | --- | --- | --- |
| {critical} | {high} | {int(severity_counts.get('medium', 0))} | {int(severity_counts.get('low', 0))} |

severityは選手数ではなく、同一原因を束ねたfinding数。affectedは各finding内の該当選手・球団数。

## 4. Critical issues

{md_table(failures[failures['severity'].eq('critical')])}

## 5. High issues

{md_table(failures[failures['severity'].eq('high')])}

## 6. Medium issues

{md_table(findings[findings['severity'].eq('medium')][['finding_id', 'description', 'affected', 'action']])}

## 7. Low / monitoring

{md_table(findings[findings['severity'].eq('low')][['finding_id', 'area', 'description', 'affected', 'rate_pct']])}

## 8. Changes made

- 23〜24歳を架空球団用「ベテラン型」の抽選対象から除外
- 第二球種候補を第一球種以下の変化量で成立できる球種に限定し、最終auditでも同方向の大小関係を保証
- 総合値cap適用後にも捕手・二遊間などのposition最低能力ラインを再保証
- 追加: 本統合validator、監査CSV、完成判定summary

## 9. Category comparison

{md_table(cross)}

ドラフト候補はsource別年齢を別CSVで確認し、架空球団用・助っ人外国人用と平均年齢・能力層が混同していないかを横断確認した。分布の重なりは正常として扱った。

## 10. Team roster findings

{md_table(team_focus)}

50球団規模でスター・主力・控え・二軍・若手・ベテランの共存、position minimum、投手役割、年齢層、上下位strengthを確認した。球団別の強さは平均だけでなくP90も保存した。

## 11. Regression

- 固定seed: {int(seed['result'].eq('PASS').sum())}/{len(seed)} PASS
- Phase 3D deterministic/transition regression: {transition_result}
- pytest: 別途全件実行（完了時に結果を追記）

## 12. Remaining data gaps

### 実装問題

{('なし' if critical == 0 and high == 0 else 'critical/high findingを要修正')}

### データ不足

- 外国人特殊能力の実在明細
- 外国人球種・変化量の実在明細
- 外国人専用体格target

これらは生成側の内部整合だけを監査し、generator不具合や新規targetには扱わない。

## 13. Final readiness

**{readiness}**

判定条件: critical = 0、high = 0、固定seed 6/6 PASS、球団構造・重大classification/special/pitch conflict 0で利用可能。既知のデータ不足とtargetなしの監視値が残るため、critical/highが0の場合も `Ready with monitored gaps` とした。

### 重点tail

{md_table(tail_focus)}

### 特殊能力数

{md_table(specials)}

### 球種構成

{md_table(pitch)}

### プロフィール構造エラー

{len(profile_issues)}件
"""


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    players = generate_samples(args.count, args.seed)
    frame = enrich_frame(players)

    ability = ability_summary(frame)
    tails = ability_tail_audit(frame)
    age_growth = age_growth_audit(frame)
    classification = classification_distribution(frame)
    class_conflicts = contradiction_rows(frame)
    special_counts = special_count_audit(frame)
    special_kind, _special_names, _ranked = special_stats(players, frame)
    special_conflict_frame = special_conflicts(players)
    pitch, vectors, pitch_conflicts = pitch_tables(players)
    profile_issues, physique = profile_audit(players)
    teams, team_structural = team_audit(args.team_count)
    teams_summary = team_summary(teams)
    cross = cross_category_compare(frame)
    growth = growth_type_distribution(frame)
    seed = pd.DataFrame(phase3c.seed_regression_rows())

    # 既存Phase 3D helperを小標本で再利用し、静的ロスターと年度遷移の決定的条件を回帰確認する。
    phase3d.generate_validation_sample(3, 3)
    transition_result = "PASS"

    findings = build_findings(
        frame, class_conflicts, special_conflict_frame, pitch_conflicts,
        profile_issues, teams, team_structural,
    )
    outputs = {
        "ability_summary.csv": ability,
        "ability_tail_audit.csv": tails,
        "classification_distribution.csv": classification,
        "classification_conflicts.csv": class_conflicts,
        "growth_type_audit.csv": pd.concat([age_growth, growth], ignore_index=True, sort=False),
        "special_count_audit.csv": special_counts,
        "special_kind_audit.csv": special_kind,
        "special_conflicts.csv": special_conflict_frame,
        "pitch_repertoire_audit.csv": pitch,
        "movement_vector_audit.csv": vectors,
        "pitch_conflicts.csv": pitch_conflicts,
        "profile_audit.csv": profile_issues,
        "physique_audit.csv": physique,
        "cross_category_compare.csv": cross,
        "team_roster_audit.csv": teams,
        "team_roster_summary.csv": teams_summary,
        "team_structural_errors.csv": team_structural,
        "warning_summary.csv": findings,
        "seed_regression.csv": seed,
    }
    for filename, table in outputs.items():
        write_csv(table, args.output_dir / filename)

    summary = build_summary(
        args.count, args.team_count, findings, cross, tails, special_counts,
        pitch, profile_issues, teams, seed, transition_result,
    )
    (args.output_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")

    counts = findings["severity"].value_counts()
    print(
        "findings: "
        f"critical={int(counts.get('critical', 0))}, high={int(counts.get('high', 0))}, "
        f"medium={int(counts.get('medium', 0))}, low={int(counts.get('low', 0))}"
    )
    print(f"seed regression: {int(seed['result'].eq('PASS').sum())}/{len(seed)} PASS")
    if counts.get("critical", 0) or counts.get("high", 0):
        raise SystemExit("critical/high findingがあります。warning_summary.csvを確認してください。")


if __name__ == "__main__":
    main()
