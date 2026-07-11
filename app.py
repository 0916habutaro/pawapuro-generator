import csv
import json
import random
import re
import sqlite3
import math
from html import escape
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

APP_VERSION = "1.0.0"
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = APP_DIR / "players.sqlite3"
CATEGORIES = ["架空球団用", "ドラフト候補用", "助っ人外国人用"]
POSITIONS = {
    "投手": ["先発", "中継ぎ", "抑え"],
    "野手": ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"],
}
TYPE_WEIGHTS = {
    "投手": [("本格派", 28), ("技巧派", 24), ("速球派", 18), ("変化球派", 18), ("スタミナ型", 12)],
    "野手": [("バランス型", 24), ("巧打型", 20), ("長距離砲", 16), ("俊足型", 16), ("守備職人", 14), ("強肩型", 10)],
}
RANK_COLORS = {"A": "#ff5a5a", "B": "#ff9f43", "C": "#ffd166", "D": "#6ee7b7", "E": "#60a5fa", "F": "#a78bfa", "G": "#cbd5e1"}
SEED_MAX = 10_000_000_000
SPECIAL_ROLE_FALLBACKS = {
    "投手": {"nobi", "kire", "strikeout", "walk", "pinch"},
    "野手": {"chance", "left", "hit_style", "direction", "run", "steal", "field"},
    "共通": {"injury"},
}
SPECIAL_KIND_LABELS = {
    "gold": "金特",
    "blue": "青特",
    "red": "赤特",
    "green": "緑特",
    "mixed": "青赤特",
    "neutral": "中間ランク",
}
SPECIAL_KIND_ORDER = ["金特", "青特", "赤特", "緑特", "青赤特", "中間ランク", "不明"]
SPECIAL_ABILITY_COLUMNS = ["name", "kind", "group", "power", "weight", "target_role"]
RANKED_SPECIAL_RANKS = ["A", "B", "C", "D", "E", "F", "G"]
RANKED_SPECIAL_BASE_WEIGHTS = {"A": 1, "B": 5, "C": 13, "D": 56, "E": 17, "F": 6, "G": 2}
RANKED_SPECIAL_DISPLAY_GROUPS = ["対ピンチ", "ノビ", "チャンス", "盗塁", "キャッチャー"]

USAGE_SPECIAL_NAMES = {
    "フル出場", "調子次第", "人気者", "ミート多用", "強振多用", "積極打法", "慎重打法",
    "積極盗塁", "慎重盗塁", "積極走塁", "積極守備", "チームプレイ○", "チームプレイ×",
    "速球中心", "変化球中心", "投球位置左", "投球位置右", "テンポ○",
}
PITCHER_USAGE_ORDER = ["フル出場", "調子次第", "速球中心", "変化球中心", "投球位置左", "投球位置右", "テンポ○", "人気者"]
FIELDER_USAGE_ORDER = ["フル出場", "調子次第", "ミート多用", "強振多用", "積極打法", "慎重打法", "積極盗塁", "慎重盗塁", "積極走塁", "積極守備", "チームプレイ○", "チームプレイ×", "人気者"]
LABEL_LANE_OFFSETS = {
    "1": [(8, -18), (-8, 12)],
    "2": [(-14, -10), (10, 13)],
    "3": [(-34, -2), (34, 10)],
    "4": [(-16, -12), (12, 12)],
    "5": [(16, -12), (-12, 12)],
}
TAB_LABELS = ["投手能力", "野手能力", "守備・起用", "プロフィール"]
TAB_COLORS = {"投手能力": "#d7193f", "野手能力": "#0876c9", "守備・起用": "#d49a00", "プロフィール": "#087d23"}


@dataclass
class MasterData:
    names: dict[str, Any]
    places: dict[str, list[str]]
    abilities: list[dict[str, Any]]


def ensure_master_files() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    names_path = DATA_DIR / "names.json"
    places_path = DATA_DIR / "places.json"
    abilities_path = DATA_DIR / "special_abilities.csv"
    if not names_path.exists():
        names_path.write_text(json.dumps({
            "日本": {"姓": ["佐藤", "鈴木", "高橋", "田中"], "名": ["蓮", "大和", "翔", "悠真"]},
            "アメリカ": {"姓": ["Smith", "Johnson"], "名": ["John", "Michael"]},
            "ドミニカ共和国": {"姓": ["Rodriguez", "Martinez"], "名": ["Juan", "Carlos"]},
            "ベネズエラ": {"姓": ["Gonzalez", "Garcia"], "名": ["Jose", "Luis"]},
            "キューバ": {"姓": ["Gurriel", "Cespedes"], "名": ["Yulieski", "Yoenis"]},
            "メキシコ": {"姓": ["Garcia", "Hernandez"], "名": ["Alejandro", "Javier"]},
            "韓国": {"姓": ["キム", "李"], "名": ["ミンジュン", "ソジュン"]},
            "台湾": {"姓": ["陳", "林"], "名": ["チェンウェイ", "ジアハオ"]}
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    if not places_path.exists():
        places_path.write_text(json.dumps({
            "日本": ["北海道", "東京都", "大阪府", "福岡県"],
            "アメリカ": ["カリフォルニア州", "テキサス州"],
            "ドミニカ共和国": ["サントドミンゴ", "サンペドロ・デ・マコリス"],
            "ベネズエラ": ["カラカス", "マラカイボ"],
            "キューバ": ["ハバナ", "サンティアゴ・デ・クーバ"],
            "メキシコ": ["メキシコシティ", "ソノラ州"],
            "韓国": ["ソウル", "釜山"],
            "台湾": ["台北", "台中"]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    if not abilities_path.exists():
        rows = [
            SPECIAL_ABILITY_COLUMNS,
            ["チャンス〇", "blue", "chance", "normal", 18, "野手"], ["チャンス◎", "blue", "chance", "strong", 4, "野手"], ["チャンス×", "red", "chance", "red", 7, "野手"],
            ["チャンス△", "neutral", "chance", "neutral", 10, "野手"], ["ムード〇", "green", "mood", "green", 8, "共通"], ["対左投手△", "mixed", "left", "mixed", 6, "野手"],
            ["対左投手〇", "blue", "left", "normal", 14, "野手"], ["対左投手×", "red", "left", "red", 6, "野手"], ["アベレージヒッター", "blue", "hit_style", "strong", 4, "野手"],
            ["パワーヒッター", "blue", "hit_style", "strong", 4, "野手"], ["広角打法", "blue", "direction", "strong", 5, "野手"], ["走塁〇", "blue", "run", "normal", 12, "野手"],
            ["盗塁〇", "blue", "steal", "normal", 12, "野手"], ["盗塁×", "red", "steal", "red", 5, "野手"], ["守備職人", "blue", "field", "strong", 5, "野手"],
            ["ケガしにくさ〇", "blue", "injury", "normal", 10, "共通"], ["ケガしにくさ×", "red", "injury", "red", 6, "共通"], ["勝負師", "gold", "chance", "gold", 1, "野手"],
            ["ノビ〇", "blue", "nobi", "normal", 14, "投手"], ["ノビ◎", "blue", "nobi", "strong", 3, "投手"], ["ノビ×", "red", "nobi", "red", 5, "投手"],
            ["キレ〇", "blue", "kire", "normal", 12, "投手"], ["奪三振", "blue", "strikeout", "strong", 5, "投手"], ["四球", "red", "walk", "red", 7, "投手"],
            ["対ピンチ〇", "blue", "pinch", "normal", 12, "投手"], ["対ピンチ×", "red", "pinch", "red", 6, "投手"], ["怪物球威", "gold", "nobi", "gold", 1, "投手"],
        ]
        with abilities_path.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)


def load_master_data() -> MasterData:
    ensure_master_files()
    abilities = pd.read_csv(DATA_DIR / "special_abilities.csv")
    missing_columns = [column for column in SPECIAL_ABILITY_COLUMNS if column != "target_role" and column not in abilities.columns]
    if missing_columns:
        raise ValueError(f"特殊能力CSVに必要な列がありません: {', '.join(missing_columns)}")
    if "target_role" not in abilities.columns:
        abilities["target_role"] = abilities["group"].apply(infer_special_target_role)
    abilities["target_role"] = abilities.apply(
        lambda row: row["target_role"] if row["target_role"] in ("投手", "野手", "共通") else infer_special_target_role(str(row["group"])),
        axis=1,
    )
    abilities["kind"] = abilities["kind"].fillna("unknown").astype(str)
    abilities["power"] = abilities["power"].fillna("normal").astype(str)
    abilities["weight"] = pd.to_numeric(abilities["weight"], errors="coerce").fillna(0).astype(int)
    global _CURRENT_ABILITIES_FOR_RANK_CHECK
    _CURRENT_ABILITIES_FOR_RANK_CHECK = abilities.to_dict("records")
    return MasterData(
        names=normalize_name_master(json.loads((DATA_DIR / "names.json").read_text(encoding="utf-8"))),
        places=normalize_place_master(json.loads((DATA_DIR / "places.json").read_text(encoding="utf-8"))),
        abilities=abilities.to_dict("records"),
    )


def init_db() -> None:
    """Create and migrate the local player history database.

    The app started with most nested values inside abilities_json.  Current
    storage keeps backward compatible copies in dedicated JSON columns so
    history, CSV/Excel export, and audit scripts can read old and new DBs.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                seed INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                age INTEGER NOT NULL DEFAULT 0,
                nationality TEXT NOT NULL DEFAULT '',
                birthplace TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL DEFAULT '',
                player_type TEXT NOT NULL DEFAULT '',
                handedness TEXT NOT NULL DEFAULT '',
                batting_throwing TEXT NOT NULL DEFAULT '',
                height INTEGER NOT NULL DEFAULT 0,
                weight INTEGER NOT NULL DEFAULT 0,
                abilities_json TEXT NOT NULL DEFAULT '{}',
                special_abilities_json TEXT NOT NULL DEFAULT '[]',
                ranked_special_abilities_json TEXT NOT NULL DEFAULT '{}',
                breaking_balls_json TEXT NOT NULL DEFAULT '[]',
                pitcher_aptitudes_json TEXT NOT NULL DEFAULT '{}',
                sub_positions_json TEXT NOT NULL DEFAULT '[]'
            )
        """)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
        migrations = {
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "seed": "INTEGER NOT NULL DEFAULT 0",
            "role": "TEXT NOT NULL DEFAULT ''",
            "category": "TEXT NOT NULL DEFAULT ''",
            "name": "TEXT NOT NULL DEFAULT ''",
            "age": "INTEGER NOT NULL DEFAULT 0",
            "nationality": "TEXT NOT NULL DEFAULT ''",
            "birthplace": "TEXT NOT NULL DEFAULT ''",
            "region": "TEXT NOT NULL DEFAULT ''",
            "position": "TEXT NOT NULL DEFAULT ''",
            "player_type": "TEXT NOT NULL DEFAULT ''",
            "handedness": "TEXT NOT NULL DEFAULT ''",
            "batting_throwing": "TEXT NOT NULL DEFAULT ''",
            "height": "INTEGER NOT NULL DEFAULT 0",
            "weight": "INTEGER NOT NULL DEFAULT 0",
            "abilities_json": "TEXT NOT NULL DEFAULT '{}'",
            "special_abilities_json": "TEXT NOT NULL DEFAULT '[]'",
            "ranked_special_abilities_json": "TEXT NOT NULL DEFAULT '{}'",
            "breaking_balls_json": "TEXT NOT NULL DEFAULT '[]'",
            "pitcher_aptitudes_json": "TEXT NOT NULL DEFAULT '{}'",
            "sub_positions_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE players ADD COLUMN {column} {definition}")
        conn.execute("UPDATE players SET region = birthplace WHERE (region IS NULL OR region = '') AND birthplace IS NOT NULL")


def weighted_choice(rng: random.Random, items: list[tuple[Any, int]]) -> Any:
    return rng.choices([i[0] for i in items], weights=[i[1] for i in items], k=1)[0]


def infer_special_target_role(group: str) -> str:
    if group in SPECIAL_ROLE_FALLBACKS["投手"]:
        return "投手"
    if group in SPECIAL_ROLE_FALLBACKS["野手"]:
        return "野手"
    return "共通"


def handedness_from_batting_throwing(batting_throwing: str) -> str:
    if batting_throwing.startswith("左投"):
        return "左投"
    return "右投"


def generate_batting_throwing(rng: random.Random, role: str, position: str) -> str:
    if role == "投手":
        throw_weights = [("右投", 68), ("左投", 32)]
    elif position in ("一塁手", "外野手"):
        throw_weights = [("右投", 75), ("左投", 25)]
    elif position in ("捕手", "二塁手", "三塁手", "遊撃手"):
        throw_weights = [("右投", 100)]
    else:
        throw_weights = [("右投", 83), ("左投", 17)]

    throwing = weighted_choice(rng, throw_weights)
    bat_side = weighted_choice(rng, [("右打", 58), ("左打", 32), ("両打", 10)])
    return f"{throwing}{bat_side}"

def seed_batch_rng() -> random.Random:
    return random.Random(random.SystemRandom().randrange(SEED_MAX))


def generate_batch_seeds(count: int, rng: random.Random | None = None) -> list[int]:
    rng = rng or seed_batch_rng()
    seeds: list[int] = []
    used: set[int] = set()
    while len(seeds) < count:
        seed = rng.randrange(SEED_MAX)
        if seed not in used:
            used.add(seed)
            seeds.append(seed)
    return seeds


def special_target_role(row: dict[str, Any]) -> str:
    role = row.get("target_role")
    if isinstance(role, str) and role in ("投手", "野手", "共通"):
        return role
    return infer_special_target_role(str(row.get("group", "")))


def is_ranked_special(row: dict[str, Any]) -> bool:
    name = str(row.get("name", ""))
    if not re.search(r"[A-G]$", name):
        return False
    group = str(row.get("group", ""))
    group_rows = [candidate for candidate in _CURRENT_ABILITIES_FOR_RANK_CHECK if str(candidate.get("group", "")) == group]
    ranks = {str(candidate.get("name", ""))[-1] for candidate in group_rows if re.search(r"[A-G]$", str(candidate.get("name", "")))}
    return set(RANKED_SPECIAL_RANKS).issubset(ranks)


_CURRENT_ABILITIES_FOR_RANK_CHECK: list[dict[str, Any]] = []


def ranked_special_base_name(name: str) -> str:
    return re.sub(r"[A-G]$", "", name)


def role_allowed_specials(master: MasterData, role: str) -> set[str]:
    return {row["name"] for row in master.abilities if special_target_role(row) in (role, "共通")}


def inappropriate_special_count(df: pd.DataFrame, master: MasterData) -> int:
    allowed = {role: role_allowed_specials(master, role) for role in ("投手", "野手")}
    normal_invalid = df.apply(lambda row: sum(name not in allowed.get(row["role"], set()) for name in row["special_abilities"]), axis=1).sum()
    ranked_invalid = df.apply(lambda row: sum(name not in allowed.get(row["role"], set()) for name in (row.get("ranked_specials") or {}).values()), axis=1).sum() if "ranked_specials" in df.columns else 0
    return int(normal_invalid + ranked_invalid)


def rank(value: int) -> str:
    if value >= 80: return "A"
    if value >= 70: return "B"
    if value >= 60: return "C"
    if value >= 50: return "D"
    if value >= 40: return "E"
    if value >= 30: return "F"
    return "G"


def ability(value: int) -> dict[str, Any]:
    value = max(1, min(99, value))
    return {"value": value, "rank": rank(value)}


def age_for(rng: random.Random, category: str) -> int:
    if category == "ドラフト候補用": return weighted_choice(rng, [(18, 35), (19, 12), (20, 10), (21, 16), (22, 22), (23, 5)])
    if category == "助っ人外国人用": return rng.randint(24, 34)
    return rng.randint(18, 36)


def pitcher_speed_value(abilities: dict[str, Any]) -> int | None:
    speed = abilities.get("球速")
    if isinstance(speed, str):
        match = re.search(r"\d+", speed)
        return int(match.group()) if match else None
    return int(speed) if isinstance(speed, int | float) else None


def pitch_movement(ball: dict[str, Any]) -> int:
    return int(ball.get("movement", ball.get("level", 0)) or 0)


def breaking_ball_summary(breaking_balls: list[dict[str, Any]] | None) -> tuple[int, int]:
    balls = [ball for ball in (breaking_balls or []) if ball.get("kind", "breaking") == "breaking"]
    total = sum(pitch_movement(ball) for ball in balls)
    return len(balls), total


PERSONALITY_SPECIALS = {
    "人気者", "ムード○", "ムード×", "国際大会○", "国際大会×", "チームプレイ○", "チームプレイ×",
    "投球位置左", "投球位置右", "速球中心", "変化球中心", "積極打法", "慎重打法", "積極盗塁",
    "慎重盗塁", "積極走塁", "積極守備",
}
STRONG_SPECIALS = {"パワーヒッター", "アベレージヒッター", "広角打法", "奪三振", "低め○", "守備職人", "ジャイロボール", "緩急○", "球持ち○", "レーザービーム"}


def special_deviation(value: int | float | None, average: int | float, step: float = 10.0) -> float:
    if not isinstance(value, int | float):
        return 0.0
    return max(-2.0, min(2.0, (float(value) - float(average)) / step))


def player_special_scale(role: str, player_type: str, category: str | None, abilities: dict[str, Any], age: int | None = None) -> float:
    """選手格に応じた通常特殊能力の基礎スケール。基本能力そのものは変更しません。"""
    if role == "投手":
        values = [pitcher_speed_value(abilities), ability_numeric_value(abilities, "コントロール"), ability_numeric_value(abilities, "スタミナ")]
        score = sum(v for v in values if isinstance(v, int | float)) / max(1, sum(isinstance(v, int | float) for v in values))
        scale = 1.18 + special_deviation(score, 55, 14) * 0.18
        if player_type in {"速球派", "技巧派", "変化球派", "スタミナ型"}:
            scale += 0.08
    else:
        keys = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
        values = [ability_numeric_value(abilities, key) for key in keys]
        score = sum(v for v in values if isinstance(v, int | float)) / max(1, sum(isinstance(v, int | float) for v in values))
        scale = 1.10 + special_deviation(score, 55, 14) * 0.15
        if player_type in {"巧打型", "長距離砲", "俊足型", "守備職人", "強肩型"}:
            scale += 0.06
    if category == "ドラフト候補用":
        scale *= 0.86
        if isinstance(age, int) and age <= 22 and score >= 60:
            scale *= 1.08
    elif category == "助っ人外国人用":
        scale *= 1.08
    return max(0.78, min(1.55, scale))


def adjust_special_chance(row: dict[str, Any], base_chance: int, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None) -> float:
    abilities = abilities or {}
    name = str(row.get("name", ""))
    kind = str(row.get("kind", ""))
    power = str(row.get("power", "normal"))
    base_scale = 0.98 if kind == "green" or name in PERSONALITY_SPECIALS else 0.70
    chance = 0.35 if power == "gold" or kind == "gold" else float(base_chance) * base_scale
    if kind in {"blue", "red", "green"}:
        chance *= player_special_scale(role, player_type, category, abilities, age)
        if kind == "blue":
            chance *= 1.32 if role == "投手" else 1.22
        elif kind == "red":
            chance *= 0.98 if role == "投手" else 1.18
        elif kind == "green" and role == "投手":
            chance *= 0.90
    if power == "strong" or name in STRONG_SPECIALS:
        chance *= 0.70
    if kind == "red":
        chance *= 1.34 if role == "野手" else 1.08
    if kind == "mixed":
        chance *= 0.90

    if category == "ドラフト候補用":
        chance *= 0.90
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 1.20
    elif category == "助っ人外国人用":
        chance *= 0.82
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 1.05
        if role == "投手" and kind == "red":
            chance *= 0.86

    if isinstance(age, int):
        if age >= 32:
            chance += 0.15
        elif age <= 20 and category == "ドラフト候補用":
            chance -= 0.15

    generic_low = {"国際大会○", "国際大会×", "人気者", "ムード○", "ムード×", "チームプレイ○", "チームプレイ×", "投手調子極端", "野手調子極端", "投球位置左", "投球位置右"}
    if name in generic_low:
        chance -= 1
    if name in {"国際大会○", "国際大会×"} and category == "助っ人外国人用":
        chance += 2
    if name == "人気者":
        top_values = [ability_numeric_value(abilities, key) for key in ("ミート", "パワー", "走力", "守備力", "球速", "コントロール")]
        if any(isinstance(v, int | float) and v >= 75 for v in top_values) or player_type in ("長距離砲", "速球派"):
            chance += 1
    if name in {"ムード○", "ムード×"}:
        chance -= 1

    if role == "野手":
        meet = ability_numeric_value(abilities, "ミート")
        power_v = ability_numeric_value(abilities, "パワー")
        speed = ability_numeric_value(abilities, "走力")
        arm = ability_numeric_value(abilities, "肩力")
        field = ability_numeric_value(abilities, "守備力")
        catch = ability_numeric_value(abilities, "捕球")
        meet_dev = special_deviation(meet, 55)
        power_dev = special_deviation(power_v, 55)
        speed_dev = special_deviation(speed, 55)
        arm_dev = special_deviation(arm, 55)
        defense_dev = (special_deviation(field, 55) + special_deviation(catch, 55)) / 2
        slug = {"パワーヒッター", "広角打法", "プルヒッター", "満塁男", "サヨナラ男", "初球○", "マルチ弾", "野手存在感"}
        contact = {"アベレージヒッター", "流し打ち", "固め打ち", "粘り打ち", "初球○", "チャンスメーカー", "カット打ち", "選球眼"}
        run = {"内野安打○", "かく乱", "積極盗塁", "積極走塁", "盗塁〇", "走塁〇", "プレッシャーラン", "ヘッドスライディング"}
        defense = {"守備職人", "積極守備", "高速チャージ", "ホーム死守", "ブロッキング", "フレーミング○", "フレーミング◎"}
        arm_names = {"レーザービーム", "送球〇", "送球◎"}
        catcher_only = {"フレーミング○", "フレーミング◎", "ささやき破り", "ホーム死守", "ブロッキング"}
        if name in catcher_only and position != "捕手":
            return 0
        if name in catcher_only and position == "捕手": chance += 2
        if name in slug:
            if player_type == "長距離砲": chance += 2
            chance += power_dev * 0.45
            if isinstance(power_v, int | float): chance += 1.1 if power_v >= 80 else 0.5 if power_v >= 70 else -1.8 if power_v < 45 else 0
            if isinstance(power_v, int | float) and power_v < 55 and name == "パワーヒッター":
                chance -= 2.5
        if name in contact:
            if player_type == "巧打型": chance += 2
            chance += meet_dev * 0.35
            if isinstance(meet, int | float): chance += 0.5 if meet >= 70 else -1.8 if meet < 45 and name == "アベレージヒッター" else 0
            if isinstance(meet, int | float) and meet < 55 and name == "アベレージヒッター":
                chance -= 2.0
        if name in run:
            if player_type == "俊足型": chance += 2
            chance += speed_dev * 0.45
            if isinstance(speed, int | float): chance += 0.8 if speed >= 70 else -1.8 if speed < 45 else 0
            if isinstance(speed, int | float) and speed < 55 and name in {"盗塁〇", "走塁〇", "積極盗塁", "積極走塁"}:
                chance -= 1.6
        if name in defense:
            if player_type == "守備職人": chance += 2
            chance += defense_dev * 0.4
            if (isinstance(field, int | float) and field >= 70) or (isinstance(catch, int | float) and catch >= 70): chance += 0.6
            if name == "守備職人" and ((isinstance(field, int | float) and field < 50) or (isinstance(catch, int | float) and catch < 50)): chance -= 3
        if name in arm_names:
            if player_type == "強肩型": chance += 2
            chance += arm_dev * 0.4
            if isinstance(arm, int | float): chance += 0.6 if arm >= 70 else -1.8 if arm < 45 else 0
        if kind == "red":
            chance *= 1.72
            if name == "三振" and isinstance(meet, int | float):
                if meet < 40:
                    chance += 4
                elif meet < 50:
                    chance += 3
                elif meet < 58:
                    chance += 1
                elif meet >= 75:
                    chance -= 6
                elif meet >= 65:
                    chance -= 4
            if name == "エラー":
                if (isinstance(field, int | float) and field < 45) or (isinstance(catch, int | float) and catch < 45): chance += 4
                elif (isinstance(field, int | float) and field < 55) or (isinstance(catch, int | float) and catch < 55): chance += 2
                if (isinstance(field, int | float) and field >= 70) and (isinstance(catch, int | float) and catch >= 70): chance -= 4
            if name == "併殺":
                if isinstance(speed, int | float) and speed < 45: chance += 3
                elif isinstance(speed, int | float) and speed < 55: chance += 1.5
                if isinstance(power_v, int | float) and power_v >= 75: chance -= 1
            chance -= 0.05
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 1.75
            if name in {"積極盗塁", "慎重盗塁"} and isinstance(speed, int | float):
                chance += 1.4 if speed >= 70 else -1.2 if speed < 45 else 0
            if name == "積極走塁" and isinstance(speed, int | float):
                chance += 1.2 if speed >= 65 else -0.8 if speed < 45 else 0
            if name == "積極守備" and (isinstance(field, int | float) or isinstance(catch, int | float)):
                chance += 1.2 if max(field or 0, catch or 0) >= 65 else -0.7
            if name == "選球眼" and isinstance(meet, int | float):
                chance += 1.0 if meet >= 60 else -0.5
            if name == "強振多用" and isinstance(power_v, int | float):
                chance += 1.0 if power_v >= 65 or player_type == "長距離砲" else -0.5
            if name == "ミート多用" and isinstance(meet, int | float):
                chance += 1.0 if meet >= 60 or player_type == "巧打型" else -0.5
    else:
        speed_v = pitcher_speed_value(abilities)
        control = ability_numeric_value(abilities, "コントロール")
        stamina = ability_numeric_value(abilities, "スタミナ")
        ball_count, total_break = breaking_ball_summary(breaking_balls)
        speed_dev = special_deviation(speed_v, 145)
        control_dev = special_deviation(control, 55)
        stamina_dev = special_deviation(stamina, 55)
        breaking_dev = max(special_deviation(ball_count, 2, 1.0), special_deviation(total_break, 7, 3.0))
        fast = {"奪三振", "重い球", "球速安定", "速球中心", "ジャイロボール", "ノビ〇", "ノビ◎"}
        command = {"低め○", "牽制○", "球持ち○", "緩急○", "ポーカーフェイス", "ストライク先行", "リリース○", "逃げ球", "内角攻め"}
        breaking = {"キレ○", "奪三振", "緩急○", "変化球中心", "ナチュラルシュート", "真っスラ"}
        stamina_names = {"尻上がり", "回またぎ○", "要所○", "根性", "立ち上がり○"}
        real_pitcher_blue = {"球速安定", "奪三振", "リリース○", "逃げ球", "球持ち○", "内角攻め", "緩急○", "キレ○", "牽制○", "ナチュラルシュート", "ゴロピッチャー", "回またぎ○", "真っスラ"}
        if name in real_pitcher_blue:
            chance += 1.5
        if name in fast:
            if player_type == "速球派": chance += 2
            chance += speed_dev * 0.45
            if isinstance(speed_v, int): chance += 1.0 if speed_v >= 150 else -1.2 if speed_v < 140 and name in {"奪三振", "重い球", "ジャイロボール"} else 0
        if name in command:
            if player_type == "技巧派": chance += 2
            chance += control_dev * 0.45
            if isinstance(control, int | float): chance += 0.8 if control >= 70 else -0.8 if control < 45 and name in {"低め○", "球持ち○", "ストライク先行"} else 0
        if name in breaking:
            if player_type == "変化球派": chance += 2
            chance += breaking_dev * 0.35
            if ball_count >= 3 or total_break >= 10: chance += 0.6
            if name == "変化球中心" and ball_count <= 1: chance -= 3
        if name in stamina_names:
            chance += stamina_dev * 0.3
            if position == "先発" or player_type == "スタミナ型": chance += 2
            if position == "抑え" and name in {"回またぎ○", "根性", "尻上がり"}: chance -= 3
        if name == "緊急登板○" and position in ("中継ぎ", "抑え"): chance += 1
        if name in {"四球", "抜け球", "乱調", "荒れ球"} and isinstance(control, int | float):
            if control < 35:
                chance += 4
            elif control < 45:
                chance += 3
            elif control < 55:
                chance += 1
            elif control >= 70:
                chance -= 4
        if name == "荒れ球" and isinstance(control, int | float):
            if control < 35:
                chance += 5
            elif control < 45:
                chance += 4
            elif control >= 70:
                chance -= 12
            elif control >= 60:
                chance -= 8
        if kind == "red":
            if name in {"四球", "乱調", "ボール先行", "抜け球"} and isinstance(control, int | float):
                chance += 2 if control < 45 else -3 if control >= 70 else 0
            if name in {"一発", "軽い球"}:
                if isinstance(speed_v, int) and speed_v < 140: chance += 2
                if isinstance(speed_v, int) and speed_v >= 150: chance -= 2
                if total_break >= 9: chance -= 1.5
                if player_type == "速球派": chance -= 1
            if name in {"寸前", "負け運", "スロースターター"}:
                if isinstance(control, int | float) and control < 55: chance += 1
                if isinstance(stamina, int | float) and stamina < 50: chance += 1
            if name == "スロースターター" and position == "先発" and isinstance(stamina, int | float) and stamina < 45: chance += 1
            chance -= 0.05
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 0.95

    max_chance = 8.0 if power == "strong" or name in STRONG_SPECIALS else 25.0
    return max(0.0, min(max_chance, float(chance)))


def generate_specials(rng: random.Random, master: MasterData, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None) -> list[str]:
    selected, selected_names, used_groups = [], set(), set()
    conflicts = {
        "積極打法": "慎重打法", "慎重打法": "積極打法",
        "強振多用": "ミート多用", "ミート多用": "強振多用",
        "積極盗塁": "慎重盗塁", "慎重盗塁": "積極盗塁",
        "速球中心": "変化球中心", "変化球中心": "速球中心",
        "投球位置左": "投球位置右", "投球位置右": "投球位置左",
        "チームプレイ○": "チームプレイ×", "チームプレイ×": "チームプレイ○",
    }
    candidates = [row for row in master.abilities if special_target_role(row) in (role, "共通") and not is_ranked_special(row)]
    rng.shuffle(candidates)
    for row in candidates:
        group = str(row.get("group", "") or "").strip()
        if group and group in used_groups:
            continue
        chance = adjust_special_chance(row, int(row.get("weight", 0) or 0), role, player_type, position, age, abilities, breaking_balls, category)
        name = row["name"]
        if name in selected_names:
            continue
        if rng.random() < chance / 100 and conflicts.get(name) not in selected_names:
            selected.append(name)
            selected_names.add(name)
            if group:
                used_groups.add(group)
    cap = 6 if category == "助っ人外国人用" else 5
    if role == "投手" and category == "架空球団用":
        cap = 6
    if role == "投手":
        score_values = [pitcher_speed_value(abilities or {}), ability_numeric_value(abilities or {}, "コントロール"), ability_numeric_value(abilities or {}, "スタミナ")]
    else:
        score_values = [ability_numeric_value(abilities or {}, key) for key in ("ミート", "パワー", "走力", "肩力", "守備力", "捕球")]
    numeric_scores = [value for value in score_values if isinstance(value, int | float)]
    player_score = sum(numeric_scores) / max(1, len(numeric_scores))
    if category == "架空球団用" and player_score >= 62:
        cap += 1
    if category == "助っ人外国人用" and player_score >= 68:
        cap += 1
    if len(selected) > cap:
        rng.shuffle(selected)
        selected = selected[:cap]
    return selected



def ranked_shift_for_group(rng: random.Random, group_name: str, role: str, position: str, player_type: str, abilities: dict[str, Any]) -> int:
    shift = 0
    if role == "投手":
        speed = pitcher_speed_value(abilities)
        if group_name == "ノビ":
            if isinstance(speed, int) and speed >= 152 and rng.random() < 0.55:
                shift += 1
            elif isinstance(speed, int) and speed < 140 and rng.random() < 0.75:
                shift -= 1
        if player_type == "速球派" and group_name == "ノビ":
            shift += 1
        if player_type == "技巧派" and group_name in ("対ピンチ", "対左打者"):
            shift += 1
        control = ability_numeric_value(abilities, "コントロール")
        if isinstance(control, int | float) and control >= 70 and group_name == "対ピンチ":
            shift += 1
    else:
        if player_type == "長距離砲" and group_name == "チャンス" and rng.random() < 0.5:
            shift += rng.choice([-1, 1])
        if player_type == "俊足型" and group_name in ("盗塁", "走塁"):
            shift += 1
        if player_type == "守備職人" and group_name == "送球":
            shift += 1
        speed = ability_numeric_value(abilities, "走力")
        fielding = ability_numeric_value(abilities, "守備力")
        if isinstance(speed, int | float) and speed >= 70 and group_name in ("盗塁", "走塁"):
            shift += 1
        if isinstance(speed, int | float) and speed < 50 and group_name in ("盗塁", "走塁"):
            shift -= 1
        if isinstance(fielding, int | float) and fielding >= 70 and group_name == "送球":
            shift += 1
    return max(-2, min(2, shift))


def shifted_rank(rank_value: str, shift: int) -> str:
    index = RANKED_SPECIAL_RANKS.index(rank_value)
    return RANKED_SPECIAL_RANKS[max(0, min(len(RANKED_SPECIAL_RANKS) - 1, index - shift))]


def ranked_weight_items_for_group(group_name: str, role: str, position: str, player_type: str, abilities: dict[str, Any], age: int | None = None) -> list[tuple[str, int]]:
    weights = RANKED_SPECIAL_BASE_WEIGHTS.copy()
    if role == "投手" and group_name == "クイック":
        control = ability_numeric_value(abilities, "コントロール")
        if player_type == "技巧派":
            weights.update({"B": weights["B"] + 2, "C": weights["C"] + 4, "D": weights["D"] - 4, "E": weights["E"] - 2})
        if isinstance(control, int | float) and control >= 70:
            weights.update({"B": weights["B"] + 1, "C": weights["C"] + 3, "D": weights["D"] - 3, "E": weights["E"] - 1})
    elif role == "野手" and group_name == "キャッチャー" and position == "捕手":
        fielding = ability_numeric_value(abilities, "守備力")
        catching = ability_numeric_value(abilities, "捕球")
        if player_type == "守備職人":
            weights.update({"B": weights["B"] + 1, "C": weights["C"] + 3, "D": weights["D"] - 3, "E": weights["E"] - 1})
        if isinstance(age, int) and age >= 30:
            weights.update({"B": weights["B"] + 1, "C": weights["C"] + 2, "D": weights["D"] - 2, "E": weights["E"] - 1})
        if isinstance(fielding, int | float) and fielding >= 70:
            weights.update({"B": weights["B"] + 1, "C": weights["C"] + 2, "D": weights["D"] - 2, "E": weights["E"] - 1})
        if isinstance(catching, int | float) and catching >= 70:
            weights.update({"B": weights["B"] + 1, "C": weights["C"] + 2, "D": weights["D"] - 2, "E": weights["E"] - 1})
    return [(rank_name, max(1, weight)) for rank_name, weight in weights.items()]


def generate_ranked_specials(rng: random.Random, master: MasterData, role: str, position: str, player_type: str, abilities: dict[str, Any], age: int | None = None) -> dict[str, str]:
    ranked_rows = [row for row in master.abilities if special_target_role(row) in (role, "共通") and is_ranked_special(row)]
    rows_by_group: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_rows:
        rows_by_group.setdefault(str(row.get("group", "")), []).append(row)
    selected: dict[str, str] = {}
    for rows in rows_by_group.values():
        names_by_rank = {str(row["name"])[-1]: str(row["name"]) for row in rows if str(row.get("name", ""))[-1:] in RANKED_SPECIAL_RANKS}
        if not set(RANKED_SPECIAL_RANKS).issubset(names_by_rank):
            continue
        group_name = ranked_special_base_name(names_by_rank["D"])
        if group_name == "キャッチャー" and position != "捕手":
            continue
        rank_value = weighted_choice(rng, ranked_weight_items_for_group(group_name, role, position, player_type, abilities, age))
        if group_name == "チャンス" and player_type == "長距離砲" and rng.random() < 0.35:
            rank_value = weighted_choice(rng, [("A", 4), ("B", 12), ("C", 20), ("D", 28), ("E", 20), ("F", 12), ("G", 4)])
        rank_value = shifted_rank(rank_value, ranked_shift_for_group(rng, group_name, role, position, player_type, abilities))
        selected[group_name] = names_by_rank[rank_value]
    return selected

def generate_fielder_abilities(rng: random.Random, age: int, position: str, player_type: str, category: str) -> dict[str, Any]:
    veteran_keep = age >= 35 and (player_type == "巧打型" or rng.random() < 0.18)
    base = 47 + (7 if 23 <= age <= 29 else 3 if 30 <= age <= 34 else 0) - (6 if age <= 19 else 3 if age <= 22 else 0) - (2 if age >= 35 and not veteran_keep else 0)
    mods = {"ミート": 0, "パワー": 0, "走力": 0, "肩力": 0, "守備力": 0, "捕球": 0}
    for key in mods:
        spread = 18 if category in {"ドラフト候補用", "助っ人外国人用"} else 15
        mods[key] += rng.randint(-spread, spread)
    position_styles = {
        "捕手": [("守備型捕手", 58), ("打撃型捕手", 13), ("平均型捕手", 29)],
        "一塁手": [("強打一塁手", 54), ("守備型一塁手", 23), ("平均型一塁手", 23)],
        "二塁手": [("守備走塁二塁手", 62), ("打撃型二塁手", 10), ("平均型二塁手", 28)],
        "三塁手": [("強打三塁手", 40), ("守備型三塁手", 31), ("平均型三塁手", 29)],
        "遊撃手": [("守備走塁遊撃手", 58), ("強打遊撃手", 8), ("巧打遊撃手", 10), ("平均型遊撃手", 24)],
        "外野手": [("走攻守外野手", 26), ("俊足外野手", 25), ("強打外野手", 25), ("守備外野手", 24)],
    }
    style = weighted_choice(rng, position_styles.get(position, [("平均型", 1)]))
    type_mods = {
        "巧打型": {"ミート": 16, "パワー": -4}, "長距離砲": {"パワー": 20, "走力": -8, "ミート": -4},
        "俊足型": {"走力": 20, "守備力": 6, "パワー": -8}, "守備職人": {"守備力": 18, "捕球": 14, "ミート": -3},
        "強肩型": {"肩力": 20, "守備力": 5}, "バランス型": {"ミート": 5, "パワー": 5, "走力": 5, "肩力": 5, "守備力": 5, "捕球": 5},
    }
    pos_mods = {
        "捕手": {"ミート": -8, "肩力": 12, "守備力": -1, "捕球": -2, "走力": -8},
        "遊撃手": {"ミート": -5, "パワー": -6, "走力": 14, "肩力": 8, "守備力": 7, "捕球": 1},
        "二塁手": {"パワー": -5, "走力": 17, "肩力": 2, "守備力": 9, "捕球": 5},
        "三塁手": {"パワー": 4, "走力": -1, "肩力": 7, "守備力": -2, "捕球": -2},
        "一塁手": {"パワー": 10, "走力": -6, "肩力": 2, "守備力": -3, "捕球": 0},
        "外野手": {"パワー": 3, "走力": 14, "肩力": 9, "守備力": -1, "捕球": -3},
    }
    for d in (type_mods.get(player_type, {}), pos_mods.get(position, {})):
        for k, v in d.items(): mods[k] += v
    style_mods = {
        "守備型捕手": {"肩力": 9, "守備力": 8, "捕球": 9, "走力": -5, "ミート": -5, "パワー": -4},
        "打撃型捕手": {"ミート": 11, "パワー": 10, "肩力": 2, "守備力": -1, "捕球": 1},
        "平均型捕手": {"肩力": 5, "捕球": 4, "守備力": 3, "走力": -3},
        "強打一塁手": {"パワー": 8, "弾道": 1, "走力": -2, "肩力": 2, "守備力": -2},
        "守備型一塁手": {"守備力": 10, "捕球": 9, "肩力": 4, "パワー": 1},
        "守備走塁二塁手": {"走力": 8, "守備力": 8, "捕球": 6, "パワー": -3},
        "打撃型二塁手": {"ミート": 7, "パワー": 8, "守備力": -3},
        "強打三塁手": {"パワー": 7, "肩力": 5, "守備力": -1},
        "守備型三塁手": {"肩力": 7, "守備力": 8, "捕球": 6, "パワー": 1},
        "守備走塁遊撃手": {"走力": 6, "肩力": 7, "守備力": 7, "捕球": 5, "パワー": -3, "ミート": -2},
        "強打遊撃手": {"パワー": 13, "ミート": 5, "守備力": -2},
        "巧打遊撃手": {"ミート": 11, "パワー": 4, "走力": -2, "守備力": -1},
        "走攻守外野手": {"ミート": 4, "パワー": 4, "走力": 5, "肩力": 4, "守備力": 3},
        "俊足外野手": {"走力": 12, "守備力": 4, "パワー": -5},
        "強打外野手": {"パワー": 12, "弾道": 1, "走力": -3, "守備力": -3},
        "守備外野手": {"肩力": 8, "守備力": 8, "捕球": 5, "ミート": -2},
    }
    for k, v in style_mods.get(style, {}).items():
        if k in mods:
            mods[k] += v
    if position == "三塁手":
        if player_type == "長距離砲":
            mods["パワー"] += 4
            mods["守備力"] -= 2
            mods["捕球"] -= 1
        elif player_type == "強肩型":
            mods["肩力"] += 4
            mods["パワー"] += 1
        elif player_type == "守備職人":
            mods["守備力"] += 4
            mods["捕球"] += 3
            mods["肩力"] += 1
    if category == "助っ人外国人用":
        mods["パワー"] += 8
        mods["ミート"] -= 2
        if rng.random() < 0.35:
            mods["守備力"] -= rng.randint(4, 9)
            mods["捕球"] -= rng.randint(3, 8)
        if player_type in ("巧打型", "守備職人"):
            mods["パワー"] -= 3
    elif category == "ドラフト候補用":
        for k in ("ミート", "守備力", "捕球"):
            mods[k] -= 2
        if rng.random() < 0.16:
            mods[rng.choice(["パワー", "走力", "肩力"])] += rng.randint(10, 18)
    elif category == "架空球団用":
        roster_tier = weighted_choice(rng, [("一軍級", 35), ("控え級", 25), ("二軍級", 18), ("若手", 12), ("ベテラン", 10)])
        tier_mod = {"一軍級": 5, "控え級": 0, "二軍級": -7, "若手": -4, "ベテラン": 1}[roster_tier]
        for k in mods:
            mods[k] += tier_mod
    if age >= 35:
        decline = rng.randint(5, 10) if not veteran_keep else rng.randint(2, 5)
        mods["走力"] -= decline + 3
        mods["守備力"] -= decline
        mods["肩力"] -= max(1, decline - 2)
        mods["捕球"] -= max(0, decline - 3)
        if player_type == "巧打型":
            mods["ミート"] += 4
        mods["パワー"] += 2
    elif 30 <= age <= 34:
        mods["走力"] -= rng.randint(2, 5)
        mods["守備力"] -= rng.randint(1, 4)
    elif age <= 22 and not (category == "ドラフト候補用" and rng.random() < 0.10):
        for k in ("ミート", "パワー", "守備力", "捕球"):
            mods[k] -= 2
    category_tune = {
        "架空球団用": {"ミート": -5, "パワー": 0, "走力": 4, "肩力": 3, "守備力": -4, "捕球": -4},
        "ドラフト候補用": {"ミート": -5, "パワー": 0, "走力": 5, "肩力": 2, "守備力": -5, "捕球": -3},
        "助っ人外国人用": {"ミート": -6, "パワー": 0, "走力": 5, "肩力": 3, "守備力": -5, "捕球": -3},
    }
    position_tune = {
        "捕手": {"ミート": -3, "守備力": -4, "捕球": -2, "走力": -1},
        "二塁手": {"ミート": -1, "パワー": -1, "走力": 1, "守備力": 1, "捕球": 1},
        "遊撃手": {"ミート": -1, "パワー": 0, "走力": 0, "守備力": -3, "捕球": -2},
        "外野手": {"ミート": -2, "パワー": 1, "走力": 3, "肩力": 2},
        "一塁手": {"ミート": -1, "パワー": 1, "走力": 1, "肩力": 1, "守備力": 1},
        "三塁手": {"ミート": -4, "パワー": 3, "守備力": -1, "捕球": -1},
    }
    for tune in (category_tune.get(category, {}), position_tune.get(position, {})):
        for k, v in tune.items():
            mods[k] += v
    result = {k: ability(base + v) for k, v in mods.items()}
    if position == "捕手":
        result["肩力"] = ability(max(result["肩力"]["value"], 45))
        result["守備力"] = ability(max(result["守備力"]["value"], 42))
        result["捕球"] = ability(max(result["捕球"]["value"], 40))
        if result["肩力"]["value"] >= 65:
            result["守備力"] = ability(max(result["守備力"]["value"], 44))
            result["捕球"] = ability(max(result["捕球"]["value"], 42))
    elif position == "遊撃手":
        result["肩力"] = ability(max(result["肩力"]["value"], 48))
        result["守備力"] = ability(max(result["守備力"]["value"], 42))
        result["捕球"] = ability(max(result["捕球"]["value"], 36))
    elif position == "二塁手":
        result["肩力"] = ability(max(result["肩力"]["value"], 42))
    elif position == "三塁手":
        result["肩力"] = ability(max(result["肩力"]["value"], 48))
    elif position == "一塁手":
        if result["パワー"]["value"] >= 62:
            result["走力"] = ability(max(result["走力"]["value"], 38))
            result["肩力"] = ability(max(result["肩力"]["value"], 45))
            result["守備力"] = ability(max(result["守備力"]["value"], 36))
        elif result["パワー"]["value"] < 42:
            result["ミート"] = ability(max(result["ミート"]["value"], 45 if player_type in {"巧打型", "バランス型"} else result["ミート"]["value"]))
            result["守備力"] = ability(max(result["守備力"]["value"], 48 if player_type in {"守備職人", "バランス型"} else 40))
            result["捕球"] = ability(max(result["捕球"]["value"], 45))
    if position == "捕手":
        if player_type == "巧打型":
            meet_cap = 66 if 24 <= age <= 31 and (result["パワー"]["value"] >= 52 or style == "打撃型捕手") else 60
            result["ミート"] = ability(min(result["ミート"]["value"], meet_cap))
        elif player_type in {"守備職人", "強肩型", "俊足型"} or age <= 22:
            result["ミート"] = ability(min(result["ミート"]["value"], 49))
        elif player_type == "長距離砲":
            result["ミート"] = ability(min(result["ミート"]["value"], 56 if style == "打撃型捕手" else 49))
        else:
            result["ミート"] = ability(min(result["ミート"]["value"], 56))
    if position == "捕手" and player_type != "守備職人":
        result["守備力"] = ability(min(result["守備力"]["value"], 64))
    if position == "遊撃手" and player_type not in {"長距離砲", "バランス型"}:
        result["パワー"] = ability(min(result["パワー"]["value"], 62))
    if position == "遊撃手" and player_type != "巧打型":
        result["ミート"] = ability(min(result["ミート"]["value"], 58))
    power = result["パワー"]["value"]
    result["弾道"] = 4 if power >= 76 else 3 if power >= 57 else 2 if power >= 38 else 1
    if style in {"強打一塁手", "強打三塁手", "強打外野手"} and power >= 55:
        result["弾道"] = min(4, result["弾道"] + 1)
    if position in {"一塁手", "三塁手"} and power >= 52:
        result["弾道"] = max(result["弾道"], 3)
    elif position == "遊撃手":
        result["弾道"] = max(result["弾道"], 2)
    return result


PITCHER_APTITUDE_KEYS = ["starter_aptitude", "reliever_aptitude", "closer_aptitude"]
PITCHER_APTITUDE_LABELS = {"starter_aptitude": "先発", "reliever_aptitude": "中継ぎ", "closer_aptitude": "抑え"}


def choose_pitcher_aptitudes(rng: random.Random, category: str) -> dict[str, str]:
    patterns = [
        ({"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"}, 27),
        ({"starter_aptitude": "◎", "reliever_aptitude": "○", "closer_aptitude": "-"}, 22),
        ({"starter_aptitude": "○", "reliever_aptitude": "◎", "closer_aptitude": "-"}, 16),
        ({"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "-"}, 16),
        ({"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "○"}, 8),
        ({"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "◎"}, 7),
        ({"starter_aptitude": "○", "reliever_aptitude": "◎", "closer_aptitude": "◎"}, 2),
        ({"starter_aptitude": "○", "reliever_aptitude": "◎", "closer_aptitude": "-"}, 2),
    ]
    if category == "助っ人外国人用":
        patterns = [(pattern, weight + (5 if pattern["closer_aptitude"] == "◎" else 0)) for pattern, weight in patterns]
    return weighted_choice(rng, patterns).copy()


def primary_pitcher_role(aptitudes: dict[str, str]) -> str:
    for key in ("closer_aptitude", "starter_aptitude", "reliever_aptitude"):
        if aptitudes.get(key) == "◎":
            return PITCHER_APTITUDE_LABELS[key]
    for key in ("starter_aptitude", "reliever_aptitude", "closer_aptitude"):
        if aptitudes.get(key) == "○":
            return PITCHER_APTITUDE_LABELS[key]
    return "中継ぎ"


def pitcher_aptitude_text(player: dict[str, Any]) -> str:
    abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    values = {key: player.get(key) or abilities.get(key) for key in PITCHER_APTITUDE_KEYS}
    if not any(values.values()):
        pos = str(player.get("position", ""))
        values = {"starter_aptitude": "◎" if pos == "先発" else "-", "reliever_aptitude": "◎" if pos == "中継ぎ" else "-", "closer_aptitude": "◎" if pos == "抑え" else "-"}
    return " / ".join(f"{PITCHER_APTITUDE_LABELS[key]}{values.get(key, '-') or '-'}" for key in PITCHER_APTITUDE_KEYS)


def generate_pitcher_abilities(rng: random.Random, age: int, player_type: str, category: str, aptitudes: dict[str, str]) -> dict[str, Any]:
    veteran_keep = age >= 35 and (player_type == "技巧派" or rng.random() < 0.12)
    prime = 2 if 23 <= age <= 29 else 1 if 30 <= age <= 34 else -2 if age <= 19 else -1 if age <= 22 or (age >= 35 and not veteran_keep) else 0
    speed = rng.randint(138, 149) + prime * 2 + (6 if player_type == "速球派" else 0) - (3 if player_type == "技巧派" else 0)
    speed += {"架空球団用": 4, "ドラフト候補用": 3, "助っ人外国人用": 6}.get(category, 0)
    reliever = aptitudes.get("reliever_aptitude", "-")
    closer = aptitudes.get("closer_aptitude", "-")
    starter = aptitudes.get("starter_aptitude", "-")
    speed += 1 if reliever == "◎" else 0
    speed += 2 if closer == "◎" else 1 if closer == "○" else 0
    speed += 1 if reliever == "○" or starter == "○" else 0
    control = 48 + rng.randint(-14, 16) + (16 if player_type == "技巧派" else 0) + (2 if closer == "◎" else 1 if closer == "○" else 0)
    stamina = 48 + rng.randint(-14, 16) + (18 if player_type == "スタミナ型" else 0)
    stamina += 12 if starter == "◎" else 5 if starter == "○" else 0
    stamina -= 5 if closer == "◎" else 2 if closer == "○" else 0
    if age >= 35:
        speed -= rng.randint(3, 6) if not veteran_keep else rng.randint(1, 3)
        stamina -= rng.randint(4, 9) if not veteran_keep else rng.randint(0, 3)
        if player_type == "技巧派":
            control += 5
    elif 30 <= age <= 34:
        speed -= rng.randint(0, 2)
        stamina -= rng.randint(1, 4)
    elif age <= 22 and not (category == "ドラフト候補用" and rng.random() < 0.12):
        control -= rng.randint(2, 6)
        stamina -= rng.randint(1, 4)

    role = primary_pitcher_role(aptitudes)
    if category == "架空球団用":
        if role == "先発":
            speed += 2 if player_type == "速球派" else 1
            control += 4 if player_type == "技巧派" else 3 if player_type in {"本格派", "変化球派"} else 2
            stamina -= 2 if player_type == "スタミナ型" else 4
            if starter == "○":
                speed -= 1
                control -= 1
                stamina -= 1
        elif role == "中継ぎ":
            speed += 3 if player_type == "速球派" else 2 if player_type in {"本格派", "変化球派"} else 1
            control -= 2 if player_type == "技巧派" else 4 if player_type == "変化球派" else 6
            stamina -= 2 if starter == "○" or player_type == "スタミナ型" else 4
        elif role == "抑え":
            speed += 4 if player_type == "速球派" else 3 if player_type == "本格派" else 2
            control -= 1 if player_type == "技巧派" else 2 if player_type == "変化球派" else 3
    elif category == "ドラフト候補用":
        if role == "抑え":
            speed += 3 if player_type == "速球派" else 1 if player_type == "本格派" else 0
        elif role in {"先発", "中継ぎ"} and player_type == "速球派" and age >= 22:
            speed += 1
        if role == "中継ぎ" and player_type != "スタミナ型" and starter != "○":
            stamina -= 2
        elif role == "先発" and player_type != "スタミナ型":
            stamina -= 1
    elif category == "助っ人外国人用":
        if role == "先発":
            control += 3 if player_type == "技巧派" else 2
            stamina -= 2 if player_type != "スタミナ型" else 1
        elif role == "中継ぎ":
            control -= 2 if player_type == "技巧派" else 4
            stamina -= 2 if starter == "○" or player_type == "スタミナ型" else 4
        elif role == "抑え":
            control -= 1 if player_type == "技巧派" else 2

    return {"球速": f"{max(125, min(165, speed))} km/h", "コントロール": ability(control), "スタミナ": ability(stamina), **aptitudes}


DIRECTION_NAMES = {
    "1": "スライダー方向",
    "2": "カーブ方向",
    "3": "フォーク方向",
    "4": "シンカー方向",
    "5": "シュート方向",
}
BREAKING_DIRECTIONS = ["スライダー方向", "カーブ方向", "フォーク方向", "シンカー方向", "シュート方向"]
ALLOWED_PITCHES_BY_DIRECTION_RIGHT = {
    "1": {"スライダー", "Hスライダー", "カットボール"},
    "2": {"カーブ", "スローカーブ", "ドロップカーブ", "スラーブ", "ナックルカーブ", "パワーカーブ", "Dスライダー"},
    "3": {"フォーク", "パーム", "チェンジアップ", "Vスライダー", "SFF", "ナックル"},
    "4": {"シンカー", "Hシンカー", "サークルチェンジ", "シンキングスプリット", "ファストチェンジ"},
    "5": {"シュート", "Hシュート", "シンキングツーシーム"},
}
ALLOWED_PITCHES_BY_DIRECTION_LEFT = {
    "1": {"スライダー", "Hスライダー", "カットボール"},
    "2": {"カーブ", "スローカーブ", "ドロップカーブ", "スラーブ", "ナックルカーブ", "パワーカーブ", "Dスライダー"},
    "3": {"フォーク", "パーム", "チェンジアップ", "Vスライダー", "SFF", "ナックル"},
    "4": {"スクリュー", "サークルチェンジ", "シンキングスプリット", "ファストチェンジ"},
    "5": {"シュート", "Hシュート", "シンキングツーシーム"},
}
SECOND_FASTBALL_TYPES = ["ツーシームファスト", "ムービングファスト", "超スローボール"]
CANONICAL_PITCH_TYPES = {"スクリュー": "シンカー"}

def _ball(name: str, code: str, weight: int, second_weight: int | None = None, min_mv: int = 1, max_mv: int = 5, bias: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "direction_code": code,
        "direction": DIRECTION_NAMES[code],
        "kind": "breaking",
        "base_weight": weight,
        "second_pitch_allowed": (second_weight or 0) > 0,
        "second_pitch_weight": second_weight if second_weight is not None else max(1, weight // 2),
        "min_movement": min_mv,
        "max_movement": max_mv,
        "pitcher_type_bias": bias or {},
    }

BREAKING_BALL_MASTER = [
    _ball("スライダー", "1", 127, 23, 2, 4), _ball("Hスライダー", "1", 65, 9, 1, 3), _ball("カットボール", "1", 135, 26, 1, 3),
    _ball("カーブ", "2", 66, 10, 1, 3), _ball("スローカーブ", "2", 30, 4, 1, 2), _ball("ドロップカーブ", "2", 42, 6, 1, 3), _ball("スラーブ", "2", 73, 12, 2, 4), _ball("ナックルカーブ", "2", 30, 4, 2, 3), _ball("パワーカーブ", "2", 13, 4, 2, 4, {"速球派": 3, "助っ人外国人用": 8}), _ball("Dスライダー", "2", 3, 1, 3, 5),
    _ball("フォーク", "3", 96, 18, 2, 4), _ball("パーム", "3", 4, 1, 1, 3), _ball("チェンジアップ", "3", 34, 6, 2, 4), _ball("Vスライダー", "3", 59, 10, 2, 4), _ball("SFF", "3", 102, 22, 2, 4, {"助っ人外国人用": 10}), _ball("ナックル", "3", 1, 0, 2, 5),
    _ball("シンカー", "4", 10, 2, 1, 3), _ball("Hシンカー", "4", 34, 3, 2, 3), _ball("スクリュー", "4", 10, 2, 1, 3), _ball("サークルチェンジ", "4", 65, 4, 2, 3), _ball("シンキングスプリット", "4", 44, 4, 2, 4, {"助っ人外国人用": 8}), _ball("ファストチェンジ", "4", 10, 1, 2, 3),
    _ball("シュート", "5", 3, 1, 1, 2), _ball("Hシュート", "5", 15, 1, 1, 2), _ball("シンキングツーシーム", "5", 27, 1, 1, 3),
]
BREAKING_BY_NAME = {ball["name"]: ball for ball in BREAKING_BALL_MASTER}
DIRECTION_SELECTION_WEIGHTS = {"1": 32, "2": 24, "3": 28, "4": 13, "5": 4}
SECOND_PITCH_DIRECTION_WEIGHTS = {"1": 23, "2": 12, "3": 34, "4": 3, "5": 1}


def allowed_pitch_names_for_generation(direction_code: str, batting_throwing: str) -> set[str]:
    if str(batting_throwing).startswith("左投"):
        return ALLOWED_PITCHES_BY_DIRECTION_LEFT[direction_code]
    return ALLOWED_PITCHES_BY_DIRECTION_RIGHT[direction_code]


def is_pitch_allowed_for_generation(direction_code: str, pitch_name: str, batting_throwing: str) -> bool:
    return pitch_name in allowed_pitch_names_for_generation(direction_code, batting_throwing)


def weighted_breaking_names(rng: random.Random, direction_code: str, player_type: str, category: str, batting_throwing: str, *, second_pitch: bool = False, exclude: set[str] | None = None) -> str:
    choices = []
    allowed = allowed_pitch_names_for_generation(direction_code, batting_throwing)
    exclude = exclude or set()
    for ball in BREAKING_BALL_MASTER:
        if ball["direction_code"] != direction_code or ball["name"] not in allowed or ball["name"] in exclude:
            continue
        weight_key = "second_pitch_weight" if second_pitch else "base_weight"
        weight = int(ball.get(weight_key, 0) or 0)
        if second_pitch and not ball.get("second_pitch_allowed", False):
            weight = 0
        bias = ball.get("pitcher_type_bias", {})
        weight += int(bias.get(player_type, 0) or 0) + int(bias.get(category, 0) or 0)
        if weight > 0:
            choices.append((ball["name"], weight))
    return weighted_choice(rng, choices)

def second_pitch_chance(player_type: str, category: str, aptitudes: dict[str, str]) -> float:
    if category == "ドラフト候補用":
        chance = 0.17
    elif category == "助っ人外国人用":
        chance = 0.74
    else:
        chance = 0.44
    if aptitudes.get("starter_aptitude") == "◎":
        chance += 0.025
    if aptitudes.get("closer_aptitude") == "◎":
        chance -= 0.025
    if player_type in {"変化球派", "技巧派"}:
        chance += 0.015
    return max(0.05, min(0.85, chance))


def make_breaking_ball(name: str, movement: int, is_second_pitch: bool, slot: int) -> dict[str, Any]:
    master = BREAKING_BY_NAME[name]
    movement = max(int(master.get("min_movement", 1)), min(int(master.get("max_movement", 7)), movement))
    return {
        "name": name,
        "direction_code": master["direction_code"],
        "direction": master["direction"],
        "movement": movement,
        "level": movement,
        "is_second_pitch": is_second_pitch,
        "slot": slot,
        "kind": "breaking",
    }


def generate_second_fastball(rng: random.Random, player_type: str, category: str, aptitudes: dict[str, str]) -> dict[str, Any] | None:
    chance = 0.115
    if player_type in {"技巧派", "変化球派"}:
        chance += 0.015
    if category == "助っ人外国人用":
        chance += 0.055
    if category == "ドラフト候補用":
        chance -= 0.045
    if aptitudes.get("closer_aptitude") == "◎":
        chance += 0.01
    if rng.random() >= max(0.04, min(0.24, chance)):
        return None
    name = weighted_choice(rng, [("ツーシームファスト", 43), ("ムービングファスト", 3), ("超スローボール", 1)])
    return {"name": name, "direction_code": None, "direction": "ストレート系第二種", "movement": 0, "level": 0, "is_second_pitch": False, "slot": None, "kind": "second_fastball"}


def pitch_count_weights(player_type: str, category: str, aptitudes: dict[str, str]) -> list[tuple[int, int]]:
    if category == "ドラフト候補用":
        weights = {1: 14, 2: 56, 3: 29, 4: 1}
    elif category == "助っ人外国人用":
        weights = {1: 3, 2: 24, 3: 63, 4: 10}
    else:
        weights = {1: 2, 2: 45, 3: 52, 4: 1}
    if aptitudes.get("starter_aptitude") == "◎":
        weights[1] -= 4; weights[2] += 2; weights[3] += 2
    if aptitudes.get("reliever_aptitude") == "◎" and aptitudes.get("starter_aptitude") != "◎":
        weights[1] += 2; weights[3] -= 2
    if aptitudes.get("closer_aptitude") == "◎" and aptitudes.get("starter_aptitude") != "◎":
        weights[1] -= 2; weights[2] += 5; weights[3] -= 3
    if player_type == "変化球派":
        weights[1] -= 4; weights[2] -= 1; weights[3] += 4; weights[4] += 1
    return [(count, max(1, weight)) for count, weight in weights.items()]


def movement_weights(player_type: str, category: str, aptitudes: dict[str, str], count: int) -> list[tuple[int, int]]:
    weights = {1: 12, 2: 36, 3: 34, 4: 15, 5: 3, 6: 0}
    if count == 1:
        weights[1] += 4; weights[2] += 4; weights[4] += 4; weights[5] += 2
    if aptitudes.get("starter_aptitude") == "◎":
        weights[1] -= 2; weights[2] -= 1; weights[4] += 2; weights[5] += 1
    if aptitudes.get("closer_aptitude") == "◎":
        weights[1] -= 2; weights[2] -= 1; weights[4] += 2; weights[5] += 1
    if category == "ドラフト候補用":
        weights[1] += 6; weights[2] += 5; weights[4] -= 4; weights[5] -= 2
    elif category == "助っ人外国人用":
        weights[1] -= 3; weights[2] -= 3; weights[4] += 5; weights[5] += 2
    if player_type == "変化球派":
        weights[1] -= 3; weights[2] -= 2; weights[4] += 3; weights[5] += 2
    return [(level, max(1, weight)) for level, weight in weights.items()]


def weighted_direction_sample(rng: random.Random, direction_codes: list[str], count: int) -> list[str]:
    remaining = list(direction_codes)
    selected: list[str] = []
    for _ in range(min(count, len(remaining))):
        code = weighted_choice(rng, [(code, DIRECTION_SELECTION_WEIGHTS.get(code, 1)) for code in remaining])
        selected.append(code)
        remaining.remove(code)
    return selected


def generate_breaking_balls(rng: random.Random, player_type: str, category: str, aptitudes: dict[str, str], batting_throwing: str) -> list[dict[str, Any]]:
    count = weighted_choice(rng, pitch_count_weights(player_type, category, aptitudes))
    direction_codes = [code for code in DIRECTION_NAMES if any(ball["direction_code"] == code and ball["name"] in allowed_pitch_names_for_generation(code, batting_throwing) for ball in BREAKING_BALL_MASTER)]
    primary_codes = weighted_direction_sample(rng, direction_codes, count)
    balls: list[dict[str, Any]] = []
    for direction_code in primary_codes:
        name = weighted_breaking_names(rng, direction_code, player_type, category, batting_throwing)
        movement = weighted_choice(rng, movement_weights(player_type, category, aptitudes, count))
        balls.append(make_breaking_ball(name, movement, False, 1))
    chance = second_pitch_chance(player_type, category, aptitudes)
    if category == "助っ人外国人用" and len(balls) == 3:
        chance = min(chance, 0.07)
    elif len(balls) >= 3:
        chance = 0
    if balls and rng.random() < chance:
        candidates = []
        for ball in balls:
            names = allowed_pitch_names_for_generation(str(ball["direction_code"]), batting_throwing) - {ball["name"]}
            if any(BREAKING_BY_NAME[name].get("second_pitch_allowed", False) for name in names):
                candidates.append(ball)
        if candidates:
            base = weighted_choice(rng, [(ball, SECOND_PITCH_DIRECTION_WEIGHTS.get(str(ball["direction_code"]), 1)) for ball in candidates])
            direction_code = str(base["direction_code"])
            second_name = weighted_breaking_names(rng, direction_code, player_type, category, batting_throwing, second_pitch=True, exclude={base["name"]})
            second_movement = min(base["movement"] + (1 if rng.random() < 0.08 else 0), weighted_choice(rng, [(1, 38), (2, 38), (3, 19), (4, 5)]))
            balls.append(make_breaking_ball(second_name, second_movement, True, 2))
    second_fastball = generate_second_fastball(rng, player_type, category, aptitudes)
    if second_fastball:
        balls.append(second_fastball)
    return balls

FOREIGN_NATIONS = ["アメリカ", "ドミニカ共和国", "ベネズエラ", "キューバ", "メキシコ", "韓国", "台湾"]


def normalize_name_master(names: dict[str, Any]) -> dict[str, Any]:
    if "外国" not in names:
        return names
    # 旧形式のマスターを読み込んだ場合も最低限動かせるようにする。
    old_foreign_names = names.get("外国", [])
    normalized = {key: value for key, value in names.items() if key != "外国"}
    for nation in FOREIGN_NATIONS:
        normalized.setdefault(nation, old_foreign_names)
    return normalized


def normalize_place_master(places: dict[str, Any]) -> dict[str, list[str]]:
    if "外国" not in places:
        return places
    old_foreign_places = places.get("外国", [])
    normalized = {key: value for key, value in places.items() if key != "外国"}
    for nation in FOREIGN_NATIONS:
        normalized.setdefault(nation, [nation] if nation in old_foreign_places else old_foreign_places)
    return normalized


def choose_nationality(rng: random.Random, category: str) -> str:
    if category == "助っ人外国人用":
        return weighted_choice(rng, [("アメリカ", 30), ("ドミニカ共和国", 24), ("ベネズエラ", 16), ("キューバ", 10), ("メキシコ", 8), ("韓国", 6), ("台湾", 6)])
    if category == "ドラフト候補用":
        # ドラフト候補は原則日本国籍。まれな外国籍候補は留学生・日系選手想定として国籍に合う名前と出身地を使う。
        return weighted_choice(rng, [("日本", 98), ("韓国", 1), ("台湾", 1)])
    return weighted_choice(rng, [("日本", 92), ("アメリカ", 3), ("ドミニカ共和国", 2), ("ベネズエラ", 1), ("キューバ", 1), ("韓国", 1), ("台湾", 1), ("メキシコ", 1)])


def choose_name(rng: random.Random, names: dict[str, Any], nationality: str) -> str:
    entry = names.get(nationality) or names["日本"]
    if isinstance(entry, dict):
        return f"{rng.choice(entry['姓'])} {rng.choice(entry['名'])}"
    return rng.choice(entry)


def choose_birthplace(rng: random.Random, places: dict[str, list[str]], nationality: str) -> str:
    return rng.choice(places.get(nationality) or places["日本"])


def name_matches_entry(name: str, entry: Any) -> bool:
    if isinstance(entry, dict):
        surnames = entry.get("姓", [])
        given_names = entry.get("名", [])
        return any(name.startswith(f"{surname} ") for surname in surnames) and any(name.endswith(f" {given}") for given in given_names)
    if isinstance(entry, list):
        return name in entry
    return False


def classify_name_type(name: str, master: MasterData, nationality: str | None = None) -> str:
    if nationality and name_matches_entry(name, master.names.get(nationality)):
        return nationality

    matched_nations = [nation for nation, entry in master.names.items() if name_matches_entry(name, entry)]
    if not matched_nations:
        return "不明"
    if len(matched_nations) > 1:
        return "複数国該当"
    return matched_nations[0]


def classify_birthplace_type(birthplace: str, master: MasterData) -> str:
    for nation, places in master.places.items():
        if birthplace in places:
            return nation
    return "不明"


SUB_POSITION_LABELS = ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"]
UTILITY_TYPES = {"守備職人", "俊足型", "バランス型", "強肩型"}

def normalize_sub_positions(value: Any) -> list[dict[str, str]]:
    if value is None or (not isinstance(value, (list, dict, str)) and pd.isna(value)):
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            return normalize_sub_positions(json.loads(text))
        except json.JSONDecodeError:
            parts = [part.strip() for part in re.split(r"[/、,]", text) if part.strip()]
            return [{"position": (m.group(1).strip() if (m := re.match(r"(.+?)([◎○△])?$", part)) else part), "aptitude": (m.group(2) if m and m.group(2) else "△")} for part in parts]
    if isinstance(value, dict):
        pos = str(value.get("position", "")).strip(); apt = str(value.get("aptitude", "△")).strip() or "△"
        return [{"position": pos, "aptitude": apt if apt in "◎○△" else "△"}] if pos else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                pos = str(item.get("position", "")).strip(); apt = str(item.get("aptitude", "△")).strip() or "△"
                if pos in SUB_POSITION_LABELS: out.append({"position": pos, "aptitude": apt if apt in "◎○△" else "△"})
            else:
                out.extend(normalize_sub_positions(str(item)))
        dedup=[]; seen=set()
        for item in out:
            if item["position"] not in seen: dedup.append(item); seen.add(item["position"])
        return dedup
    return []

def format_sub_positions(sub_positions: Any) -> str:
    items = normalize_sub_positions(sub_positions)
    return " / ".join(f"{item['position']}{item['aptitude']}" for item in items) if items else "なし"

def generate_sub_positions(rng: random.Random, role: str, position: str, player_type: str, category: str, age: int, batting_throwing: str, abilities: dict[str, Any]) -> list[dict[str, str]]:
    if role != "野手": return []
    speed = ability_numeric_value(abilities, "走力") or 0; arm = ability_numeric_value(abilities, "肩力") or 0; field = ability_numeric_value(abilities, "守備力") or 0; catch = ability_numeric_value(abilities, "捕球") or 0; power = ability_numeric_value(abilities, "パワー") or 0
    has_rate = {"捕手": .50, "一塁手": .88, "二塁手": .94, "三塁手": .95, "遊撃手": .94, "外野手": .38}.get(position, .65)
    if category == "ドラフト候補用": has_rate -= .14
    if category == "助っ人外国人用": has_rate -= .24
    if player_type in {"守備職人", "俊足型", "バランス型"}: has_rate += .08
    if player_type == "長距離砲" and position in {"一塁手", "外野手"}: has_rate -= .10
    if rng.random() > max(.05, min(.98, has_rate)): return []
    weights = [(1, 30), (2, 62 if player_type in {"守備職人", "俊足型", "バランス型"} or age <= 23 else 52), (3, 25 if player_type in {"守備職人", "俊足型", "バランス型"} or age <= 23 else 16), (4, 5 if category == "架空球団用" else 1)]
    if category == "ドラフト候補用": weights = [(1, 56), (2, 34), (3, 8), (4, 2)]
    if category == "助っ人外国人用": weights = [(1, 64), (2, 30), (3, 5), (4, 1)]
    if position == "外野手" and player_type != "守備職人": weights = [(1, 70), (2, 27), (3, 3), (4, 1)]
    target = weighted_choice(rng, weights)
    # 3個以上は控え・ユーティリティ・若手経験者に寄せ、強打専任型の万能化を抑える。
    if target >= 3 and player_type not in UTILITY_TYPES and age > 23:
        target = 2
    base = {"捕手": {"一塁手": 58, "外野手": 28, "三塁手": 14, "二塁手": 2}, "一塁手": {"三塁手": 42, "外野手": 40, "二塁手": 14, "捕手": 2}, "二塁手": {"三塁手": 34, "遊撃手": 28, "一塁手": 22, "外野手": 16, "捕手": 1}, "三塁手": {"一塁手": 38, "外野手": 30, "二塁手": 22, "遊撃手": 10}, "遊撃手": {"二塁手": 38, "三塁手": 36, "外野手": 18, "一塁手": 8}, "外野手": {"一塁手": 60, "三塁手": 22, "二塁手": 10, "捕手": 2, "遊撃手": 1}}.get(position, {})
    if category == "助っ人外国人用": base = {k: (v * 2 if k in {"一塁手", "三塁手", "外野手"} else max(1, v // 3)) for k, v in base.items()}
    def allowed(pos: str) -> bool:
        if pos == position: return False
        if batting_throwing.startswith("左投") and pos in {"二塁手", "三塁手", "遊撃手", "捕手"}: return False
        if pos == "遊撃手": return speed >= 55 and arm >= 55 and field >= 50 and catch >= 45 and player_type in UTILITY_TYPES
        if pos == "二塁手": return speed >= 50 and field >= 45 and catch >= 45
        if pos == "三塁手": return arm >= 55
        if pos == "外野手": return speed >= 50 or arm >= 50
        if pos == "捕手": return arm >= 60 and field >= 40 and catch >= 45 and player_type in {"守備職人", "強肩型", "バランス型"} and category != "助っ人外国人用"
        return True
    def aptitude(pos: str) -> str:
        if pos == "捕手": return "○" if rng.random() < .08 and arm >= 70 and catch >= 60 else "△"
        score = (2 if {position, pos} <= {"二塁手", "遊撃手", "三塁手"} else 0) + (2 + int(power >= 60) if pos == "一塁手" else 0) + (int(field >= 60) + int(catch >= 60) + int(arm >= 60) + int(speed >= 60)) + int(player_type in {"守備職人", "俊足型"}) - int(category == "助っ人外国人用")
        if score >= 6 and rng.random() < .45: return "◎"
        if score >= 5 and rng.random() < .18: return "◎"
        if score >= 3 and rng.random() < .82: return "○"
        if pos == "一塁手" and rng.random() < .42: return "○"
        if score >= 2 and rng.random() < .28: return "○"
        return "△"
    candidates = [(pos, w) for pos, w in base.items() if allowed(pos)]
    selected=[]
    while candidates and len(selected) < target:
        pos = weighted_choice(rng, candidates); selected.append({"position": pos, "aptitude": aptitude(pos)}); candidates = [(p, w) for p, w in candidates if p != pos]
    return selected

def generate_player(role: str, category: str, master: MasterData, seed: int | None = None) -> dict[str, Any]:
    seed = seed if seed is not None else random.SystemRandom().randrange(SEED_MAX)
    rng = random.Random(seed)
    age = age_for(rng, category)
    nationality = choose_nationality(rng, category)
    pitcher_aptitudes: dict[str, str] = {}
    if role == "投手":
        pitcher_aptitudes = choose_pitcher_aptitudes(rng, category)
        position = primary_pitcher_role(pitcher_aptitudes)
        type_weights = [("本格派", 34), ("技巧派", 18), ("速球派", 26), ("変化球派", 14), ("スタミナ型", 8)] if category == "助っ人外国人用" else TYPE_WEIGHTS[role]
    else:
        position_weights = [("捕手", 8), ("一塁手", 20), ("二塁手", 9), ("三塁手", 18), ("遊撃手", 10), ("外野手", 35)] if category == "助っ人外国人用" else [("捕手", 12), ("一塁手", 14), ("二塁手", 14), ("三塁手", 14), ("遊撃手", 16), ("外野手", 30)]
        position = weighted_choice(rng, position_weights)
        type_weights = [("バランス型", 16), ("巧打型", 16), ("長距離砲", 28), ("俊足型", 8), ("守備職人", 12), ("強肩型", 20)] if category == "助っ人外国人用" else TYPE_WEIGHTS[role]
    player_type = weighted_choice(rng, type_weights)
    abilities = generate_pitcher_abilities(rng, age, player_type, category, pitcher_aptitudes) if role == "投手" else generate_fielder_abilities(rng, age, position, player_type, category)
    batting_throwing = generate_batting_throwing(rng, role, position)
    breaking_balls = generate_breaking_balls(rng, player_type, category, pitcher_aptitudes, batting_throwing) if role == "投手" else []
    sub_positions = generate_sub_positions(rng, role, position, player_type, category, age, batting_throwing, abilities)
    special_abilities = generate_specials(rng, master, role, player_type, position, age, abilities, breaking_balls, category)
    return {
        "seed": seed, "role": role, "category": category, "name": choose_name(rng, master.names, nationality), "age": age,
        "nationality": nationality, "birthplace": choose_birthplace(rng, master.places, nationality), "position": position, "player_type": player_type,
        "handedness": handedness_from_batting_throwing(batting_throwing),
        "batting_throwing": batting_throwing,
        "height": rng.randint(168, 196) + (3 if role == "投手" else 0), "weight": rng.randint(68, 105),
        "abilities": {**abilities, "ranked_specials": generate_ranked_specials(rng, master, role, position, player_type, abilities, age)}, "special_abilities": special_abilities,
        "breaking_balls": breaking_balls,
        "sub_positions": sub_positions,
        **pitcher_aptitudes,
    }


def save_players(players: list[dict[str, Any]]) -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        for p in players:
            abilities = dict(p.get("abilities", {}))
            ranked_specials = abilities.get("ranked_specials", {}) if isinstance(abilities, dict) else {}
            pitcher_aptitudes = {key: p.get(key) for key in PITCHER_APTITUDE_KEYS if p.get(key) is not None}
            region = p.get("region") or p.get("birthplace") or ""
            conn.execute("""INSERT INTO players (created_at, seed, role, category, name, age, nationality, birthplace, region, position, player_type, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, ranked_special_abilities_json, breaking_balls_json, pitcher_aptitudes_json, sub_positions_json)
                          VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (p.get("seed", 0), p.get("role", ""), p.get("category", ""), p.get("name", ""), p.get("age", 0), p.get("nationality", ""), p.get("birthplace", region), region, p.get("position", ""), p.get("player_type", ""), p.get("handedness", ""), p.get("batting_throwing", ""), p.get("height", 0), p.get("weight", 0), json.dumps(abilities, ensure_ascii=False), json.dumps(p.get("special_abilities", []), ensure_ascii=False), json.dumps(ranked_specials, ensure_ascii=False), json.dumps(p.get("breaking_balls", []), ensure_ascii=False), json.dumps(pitcher_aptitudes, ensure_ascii=False), json.dumps(normalize_sub_positions(p.get("sub_positions", [])), ensure_ascii=False)))
        return len(players)


def delete_all_players() -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        deleted_count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        conn.execute("DELETE FROM players")
        return int(deleted_count)


def apply_history_filters(df: pd.DataFrame, categories: list[str], roles: list[str]) -> pd.DataFrame:
    filtered = df.copy()
    if categories:
        filtered = filtered[filtered["category"].isin(categories)]
    if roles:
        filtered = filtered[filtered["role"].isin(roles)]
    return filtered


def load_history() -> pd.DataFrame:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
        wanted = ["id", "created_at", "seed", "role", "category", "name", "age", "nationality", "birthplace", "region", "position", "player_type", "handedness", "batting_throwing", "height", "weight", "abilities_json", "special_abilities_json", "ranked_special_abilities_json", "breaking_balls_json", "pitcher_aptitudes_json", "sub_positions_json"]
        selected = [column for column in wanted if column in columns]
        history = pd.read_sql_query(f"SELECT {', '.join(selected)} FROM players ORDER BY id DESC", conn)
    if not history.empty:
        if "region" not in history.columns:
            history["region"] = history.get("birthplace", "")
        abilities = history["abilities_json"].apply(lambda value: parse_json_column(value, {}))
        pitcher_aptitudes = history["pitcher_aptitudes_json"].apply(lambda value: parse_json_column(value, {})) if "pitcher_aptitudes_json" in history.columns else pd.Series([{}] * len(history))
        for key in PITCHER_APTITUDE_KEYS:
            history[key] = pitcher_aptitudes.apply(lambda item: item.get(key) if isinstance(item, dict) else None)
            history[key] = history[key].where(history[key].notna(), abilities.apply(lambda item: item.get(key) if isinstance(item, dict) else None))
        history["sub_positions"] = history["sub_positions_json"].apply(normalize_sub_positions)
        history["サブポジ数"] = history["sub_positions"].apply(len)
        history["サブポジ"] = history["sub_positions"].apply(format_sub_positions)
        history["サブポジ一覧"] = history["sub_positions"].apply(lambda values: " / ".join(item["position"] for item in values))
        history["サブポジ評価一覧"] = history["sub_positions"].apply(lambda values: " / ".join(item["aptitude"] for item in values))
    return history


def parse_json_column(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, float) and pd.isna(value):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return fallback
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if isinstance(fallback, list):
                return [part.strip() for part in text.split(",") if part.strip()]
            return fallback
    return fallback


def load_history_for_balance() -> pd.DataFrame:
    history = load_history()
    if history.empty:
        return history
    df = history.copy()
    df["abilities"] = df["abilities_json"].apply(lambda value: parse_json_column(value, {}))
    df["special_abilities"] = df["special_abilities_json"].apply(lambda value: parse_json_column(value, []))
    from_abilities = df["abilities"].apply(lambda value: value.get("ranked_specials", {}) if isinstance(value, dict) else {})
    if "ranked_special_abilities_json" in df.columns:
        df["ranked_specials"] = df["ranked_special_abilities_json"].apply(lambda value: parse_json_column(value, {}))
        df["ranked_specials"] = df["ranked_specials"].where(df["ranked_specials"].apply(bool), from_abilities)
    else:
        df["ranked_specials"] = from_abilities
    df["breaking_balls"] = df["breaking_balls_json"].apply(lambda value: parse_json_column(value, []))
    df["sub_positions"] = df["sub_positions_json"].apply(normalize_sub_positions) if "sub_positions_json" in df.columns else [[] for _ in range(len(df))]
    return df


def ability_numeric_value(abilities: dict[str, Any], key: str) -> int | float | None:
    item = abilities.get(key)
    if isinstance(item, dict):
        return item.get("value")
    if key == "球速" and isinstance(item, str):
        return pd.to_numeric(item.replace(" km/h", ""), errors="coerce")
    return item if isinstance(item, int | float) else None


def ability_average_table(df: pd.DataFrame, role: str, keys: list[str]) -> pd.DataFrame:
    target = df[df["role"] == role].copy()
    if target.empty:
        return pd.DataFrame(columns=["能力", "平均値"])
    rows = []
    for key in keys:
        values = target["abilities"].apply(lambda abilities: ability_numeric_value(abilities, key))
        numeric_values = pd.to_numeric(values, errors="coerce").dropna()
        rows.append({"能力": key, "平均値": round(numeric_values.mean(), 1) if not numeric_values.empty else None})
    return pd.DataFrame(rows)


def special_ability_summary(df: pd.DataFrame, master: MasterData) -> tuple[pd.DataFrame, pd.DataFrame]:
    ability_kinds = {row["name"]: row["kind"] for row in master.abilities}
    exploded = df[["special_abilities"]].explode("special_abilities").dropna()
    exploded = exploded[exploded["special_abilities"] != ""]
    if exploded.empty:
        counts = pd.DataFrame(columns=["特殊能力", "出現回数", "種別"])
        kind_counts = pd.DataFrame({"種別": SPECIAL_KIND_ORDER, "出現数": [0] * len(SPECIAL_KIND_ORDER)})
        return counts, kind_counts
    counts = exploded["special_abilities"].value_counts().rename_axis("特殊能力").reset_index(name="出現回数")
    counts["種別"] = counts["特殊能力"].map(ability_kinds).map(SPECIAL_KIND_LABELS).fillna("不明")
    kind_counts = counts.groupby("種別", as_index=False)["出現回数"].sum().rename(columns={"出現回数": "出現数"})
    kind_counts = pd.DataFrame({"種別": SPECIAL_KIND_ORDER}).merge(kind_counts, on="種別", how="left").fillna({"出現数": 0})
    kind_counts["出現数"] = kind_counts["出現数"].astype(int)
    return counts, kind_counts



def ranked_special_distribution(df: pd.DataFrame, group_names: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for ranked_specials in df.get("ranked_specials", pd.Series(dtype=object)):
        if not isinstance(ranked_specials, dict):
            continue
        for group_name, special_name in ranked_specials.items():
            if group_names and group_name not in group_names:
                continue
            rows.append({"グループ": group_name, "ランク": str(special_name)[-1]})
    base_groups = group_names or sorted({row["グループ"] for row in rows})
    base = pd.MultiIndex.from_product([base_groups, RANKED_SPECIAL_RANKS], names=["グループ", "ランク"]).to_frame(index=False)
    if not rows:
        base["人数"] = 0
        return base
    counts = pd.DataFrame(rows).groupby(["グループ", "ランク"]).size().reset_index(name="人数")
    return base.merge(counts, on=["グループ", "ランク"], how="left").fillna({"人数": 0}).astype({"人数": int})

def player_fingerprint(row: pd.Series) -> str:
    keys = ["role", "category", "name", "age", "nationality", "birthplace", "position", "player_type", "handedness", "batting_throwing", "height", "weight", "abilities_json", "special_abilities_json", "breaking_balls_json"]
    return json.dumps({key: row.get(key) for key in keys}, ensure_ascii=False, sort_keys=True)


def special_count_bucket(values: list[str]) -> str:
    count = len(values)
    return "6個以上" if count >= 6 else f"{count}個"


def special_count_distribution(df: pd.DataFrame) -> pd.DataFrame:
    buckets = df["special_abilities"].apply(special_count_bucket)
    order = pd.DataFrame({"特殊能力数": ["0個", "1個", "2個", "3個", "4個", "5個", "6個以上"]})
    counts = buckets.value_counts().rename_axis("特殊能力数").reset_index(name="人数")
    return order.merge(counts, on="特殊能力数", how="left").fillna({"人数": 0}).astype({"人数": int})


def grouped_special_count_distribution(df: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*group_columns, "特殊能力数", "人数"])
    work = df.copy()
    work["特殊能力数"] = work["special_abilities"].apply(special_count_bucket)
    return work.groupby([*group_columns, "特殊能力数"]).size().reset_index(name="人数")


def handedness_batting_mismatch_count(df: pd.DataFrame) -> int:
    derived = df["batting_throwing"].apply(handedness_from_batting_throwing)
    return int((df["handedness"] != derived).sum())


def restricted_left_throwing_positions(df: pd.DataFrame) -> pd.DataFrame:
    positions = ["捕手", "二塁手", "三塁手", "遊撃手"]
    target = df[(df["position"].isin(positions)) & (df["handedness"] == "左投")]
    counts = target["position"].value_counts().rename_axis("ポジション").reset_index(name="人数")
    base = pd.DataFrame({"ポジション": positions})
    return base.merge(counts, on="ポジション", how="left").fillna({"人数": 0}).astype({"人数": int})




def name_matches_nationality(name: str, nationality: str, master: MasterData) -> bool:
    return name_matches_entry(name, master.names.get(nationality))


def birthplace_matches_nationality(birthplace: str, nationality: str, master: MasterData) -> bool:
    return birthplace in master.places.get(nationality, [])

def consistency_table(df: pd.DataFrame, master: MasterData, kind: str) -> pd.DataFrame:
    work = df.copy()
    type_column = "名前種別" if kind == "name" else "出身地種別"
    if kind == "name":
        work[type_column] = work.apply(lambda row: classify_name_type(row["name"], master, row["nationality"]), axis=1)
    else:
        work[type_column] = work["birthplace"].apply(lambda value: classify_birthplace_type(value, master))
    if kind == "name":
        work["整合性"] = work.apply(lambda row: name_matches_nationality(row["name"], row["nationality"], master), axis=1)
    else:
        work["整合性"] = work.apply(lambda row: birthplace_matches_nationality(row["birthplace"], row["nationality"], master), axis=1)
    return work.groupby(["nationality", type_column, "整合性"]).size().reset_index(name="人数").rename(columns={"nationality": "国籍"})


def inconsistency_count(df: pd.DataFrame, master: MasterData, kind: str) -> int:
    if kind == "name":
        matches = df.apply(lambda row: name_matches_nationality(row["name"], row["nationality"], master), axis=1)
    else:
        matches = df.apply(lambda row: birthplace_matches_nationality(row["birthplace"], row["nationality"], master), axis=1)
    return int((~matches).sum())


def breaking_balance_tables(df: pd.DataFrame) -> dict[str, Any]:
    pitchers = df[df["role"] == "投手"].copy()
    rows = []
    invalid = []
    for _, player in pitchers.iterrows():
        second_fastball_count = 0
        for ball in player.get("breaking_balls", []) or []:
            row = {"選手名": player["name"], "投打": player["batting_throwing"], "球種": ball.get("name", ""), "方向コード": ball.get("direction_code"), "方向": ball.get("direction", ""), "変化量": pitch_movement(ball), "kind": ball.get("kind", "breaking"), "第二球種": bool(ball.get("is_second_pitch"))}
            rows.append(row)
            if row["kind"] == "breaking":
                code = str(row["方向コード"])
                name = str(row["球種"])
                reasons = []
                if player["batting_throwing"].startswith("右投") and name == "スクリュー":
                    reasons.append("右投手のスクリュー")
                if player["batting_throwing"].startswith("左投") and name in {"シンカー", "Hシンカー"}:
                    reasons.append("左投手のシンカー/Hシンカー")
                if code not in DIRECTION_NAMES or not is_pitch_allowed_for_generation(code, name, str(player["batting_throwing"])):
                    reasons.append("方向コードと球種の不一致")
                if name in {"ツーシーム", "ドロップ", "縦スライダー", "オリジナル変化球"}:
                    reasons.append("生成対象外の球種")
                if reasons:
                    invalid.append({**row, "理由": "、".join(reasons)})
            elif row["kind"] == "second_fastball":
                second_fastball_count += 1
        if second_fastball_count > 1:
            invalid.append({"選手名": player["name"], "投打": player["batting_throwing"], "球種": "ストレート系第二種", "方向コード": None, "方向": "ストレート系第二種", "変化量": 0, "kind": "second_fastball", "第二球種": False, "理由": "ストレート系第二種が2個以上"})
    balls = pd.DataFrame(rows)
    breaking = balls[balls["kind"].eq("breaking")] if not balls.empty else pd.DataFrame(columns=["選手名", "球種", "方向", "変化量", "第二球種"])
    second = balls[balls["kind"].eq("second_fastball")] if not balls.empty else pd.DataFrame(columns=["選手名", "球種"])
    per_pitcher = breaking.groupby("選手名", dropna=False).agg(通常変化球数=("球種", "count"), 総変化量=("変化量", "sum"), 第二球種あり=("第二球種", "any")).reset_index() if not breaking.empty else pd.DataFrame(columns=["選手名", "通常変化球数", "総変化量", "第二球種あり"])
    second_players = set(second["選手名"]) if not second.empty else set()
    metrics = pd.DataFrame([
        {"項目": "投手1人あたり平均通常変化球数", "値": round(len(breaking) / len(pitchers), 2) if len(pitchers) else 0},
        {"項目": "投手1人あたり平均総変化量", "値": round(breaking["変化量"].sum() / len(pitchers), 2) if len(pitchers) else 0},
        {"項目": "第二球種あり投手数", "値": int(per_pitcher["第二球種あり"].sum()) if not per_pitcher.empty else 0},
        {"項目": "第二球種あり投手割合", "値": f"{round((int(per_pitcher['第二球種あり'].sum()) if not per_pitcher.empty else 0) / len(pitchers) * 100, 2) if len(pitchers) else 0}%"},
        {"項目": "ストレート系第二種あり投手数", "値": len(second_players)},
        {"項目": "ストレート系第二種あり投手割合", "値": f"{round(len(second_players) / len(pitchers) * 100, 2) if len(pitchers) else 0}%"},
        {"項目": "不正球種件数", "値": len(invalid)},
    ])
    count_dist = per_pitcher["通常変化球数"].value_counts().sort_index().rename_axis("通常変化球数").reset_index(name="投手数") if not per_pitcher.empty else pd.DataFrame(columns=["通常変化球数", "投手数"])
    movement_dist = per_pitcher["総変化量"].value_counts().sort_index().rename_axis("総変化量").reset_index(name="投手数") if not per_pitcher.empty else pd.DataFrame(columns=["総変化量", "投手数"])
    return {"metrics": metrics, "count_dist": count_dist, "movement_dist": movement_dist, "direction": breaking["方向"].value_counts().rename_axis("方向").reset_index(name="出現数") if not breaking.empty else pd.DataFrame(columns=["方向", "出現数"]), "pitch": breaking["球種"].value_counts().rename_axis("球種").reset_index(name="出現数") if not breaking.empty else pd.DataFrame(columns=["球種", "出現数"]), "second_fastball": second["球種"].value_counts().rename_axis("球種").reset_index(name="出現数") if not second.empty else pd.DataFrame(columns=["球種", "出現数"]), "invalid": pd.DataFrame(invalid)}

def render_balance_check(master: MasterData) -> None:
    st.header("バランス確認")
    st.write("保存済み選手をSQLiteから読み込み、生成結果の偏りを確認します。")
    df = load_history_for_balance()
    total_saved_count = len(df)
    if df.empty:
        st.info("保存済み選手がまだありません。選手を生成すると集計できます。")
        return

    st.subheader("履歴管理")
    confirm_delete = st.checkbox("保存済み選手を全削除することを確認しました")
    if st.button("保存済み選手を全削除", type="secondary", disabled=not confirm_delete):
        deleted_count = delete_all_players()
        st.session_state.pop("latest_players", None)
        st.success(f"保存済み選手を{deleted_count}件削除しました。")
        st.rerun()

    st.subheader("絞り込み")
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        selected_categories = st.multiselect("カテゴリ", CATEGORIES, default=CATEGORIES)
    with filter_col2:
        selected_roles = st.multiselect("投手 / 野手", ["投手", "野手"], default=["投手", "野手"])
    df = apply_history_filters(df, selected_categories, selected_roles)
    st.caption(f"フィルター適用後: {len(df)}件 / 全保存件数: {total_saved_count}件")
    if df.empty:
        st.info("条件に一致する保存済み選手がありません。")
        return

    st.download_button("フィルター後CSV出力", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="pawapuro_players_filtered.csv", mime="text/csv")

    unique_seed_count = int(df["seed"].nunique())
    seed_duplicate_count = int(len(df) - unique_seed_count)
    complete_duplicate_count = int(len(df) - df.apply(player_fingerprint, axis=1).nunique())
    invalid_special_count = inappropriate_special_count(df, master)
    handedness_mismatch_count = handedness_batting_mismatch_count(df)
    restricted_table = restricted_left_throwing_positions(df)
    restricted_left_count = int(restricted_table["人数"].sum())
    special_lengths = df["special_abilities"].apply(len)
    avg_special_count = round(special_lengths.mean(), 2)
    six_plus_special_count = int((special_lengths >= 6).sum())
    unique_name_count = int(df["name"].nunique())
    name_duplicate_rate = round((len(df) - unique_name_count) / len(df) * 100, 2)
    name_inconsistency_count = inconsistency_count(df, master, "name")
    birthplace_inconsistency_count = inconsistency_count(df, master, "birthplace")
    st.subheader("生成品質チェック")
    metric_cols = st.columns(7)
    metric_cols[0].metric("総件数", len(df))
    metric_cols[1].metric("ユニークseed数", unique_seed_count)
    metric_cols[2].metric("seed重複数", seed_duplicate_count)
    metric_cols[3].metric("完全重複選手数", complete_duplicate_count)
    metric_cols[4].metric("不適切な特殊能力件数", invalid_special_count)
    metric_cols[5].metric("利き腕/投打 不一致件数", handedness_mismatch_count)
    metric_cols[6].metric("左投げの捕手/内野手", restricted_left_count)

    st.subheader("名前・国籍・出身地チェック")
    profile_cols = st.columns(5)
    profile_cols[0].metric("ユニーク名前数", unique_name_count)
    profile_cols[1].metric("名前重複率", f"{name_duplicate_rate}%")
    profile_cols[2].metric("国籍数", int(df["nationality"].nunique()))
    profile_cols[3].metric("国籍×名前 不整合", name_inconsistency_count)
    profile_cols[4].metric("国籍×出身地 不整合", birthplace_inconsistency_count)

    st.subheader("国籍別人数")
    st.dataframe(df["nationality"].value_counts().rename_axis("国籍").reset_index(name="人数"), use_container_width=True, hide_index=True)

    col_profile1, col_profile2 = st.columns(2)
    with col_profile1:
        st.subheader("国籍 × 名前種別の整合性")
        st.dataframe(consistency_table(df, master, "name"), use_container_width=True, hide_index=True)
    with col_profile2:
        st.subheader("国籍 × 出身地種別の整合性")
        st.dataframe(consistency_table(df, master, "birthplace"), use_container_width=True, hide_index=True)

    st.subheader("利き腕診断")
    st.dataframe(restricted_table, use_container_width=True, hide_index=True)

    st.subheader("投手/野手別人数")
    st.dataframe(df["role"].value_counts().rename_axis("投手/野手").reset_index(name="人数"), use_container_width=True, hide_index=True)

    st.subheader("カテゴリ別人数")
    st.dataframe(df["category"].value_counts().rename_axis("カテゴリ").reset_index(name="人数"), use_container_width=True, hide_index=True)

    st.subheader("投手/野手 × カテゴリ別人数")
    role_category = pd.crosstab(df["role"], df["category"], margins=True, margins_name="合計")
    st.dataframe(role_category, use_container_width=True)

    st.subheader("年齢分布")
    age_dist = df["age"].value_counts().sort_index().rename_axis("年齢").reset_index(name="人数")
    st.dataframe(age_dist, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("野手能力 平均値")
        st.dataframe(ability_average_table(df, "野手", ["弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"]), use_container_width=True, hide_index=True)
    with col2:
        st.subheader("投手能力 平均値")
        st.dataframe(ability_average_table(df, "投手", ["球速", "コントロール", "スタミナ"]), use_container_width=True, hide_index=True)

    ranked_dist = ranked_special_distribution(df)
    key_ranked_dist = ranked_special_distribution(df, RANKED_SPECIAL_DISPLAY_GROUPS)
    special_counts, kind_counts = special_ability_summary(df, master)
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("特殊能力 出現回数")
        st.dataframe(special_counts, use_container_width=True, hide_index=True)
    with col4:
        st.subheader("特殊能力 種別別出現数")
        st.dataframe(kind_counts, use_container_width=True, hide_index=True)
        st.metric("1人あたり平均特殊能力数", avg_special_count)
        st.metric("6個以上の選手数", six_plus_special_count)

    st.subheader("ランク系特殊能力の分布")
    st.dataframe(ranked_dist, use_container_width=True, hide_index=True)

    st.subheader("主要ランク系特殊能力分布")
    st.dataframe(key_ranked_dist, use_container_width=True, hide_index=True)

    st.subheader("通常特殊能力数の分布")
    st.dataframe(special_count_distribution(df), use_container_width=True, hide_index=True)

    col_special1, col_special2 = st.columns(2)
    with col_special1:
        st.subheader("特殊能力数分布（投手/野手別）")
        st.dataframe(grouped_special_count_distribution(df, ["role"]).rename(columns={"role": "投手/野手"}), use_container_width=True, hide_index=True)
    with col_special2:
        st.subheader("特殊能力数分布（カテゴリ別）")
        st.dataframe(grouped_special_count_distribution(df, ["category"]).rename(columns={"category": "カテゴリ"}), use_container_width=True, hide_index=True)

    st.subheader("特殊能力数分布（投手/野手 × カテゴリ別）")
    st.dataframe(grouped_special_count_distribution(df, ["role", "category"]).rename(columns={"role": "投手/野手", "category": "カテゴリ"}), use_container_width=True, hide_index=True)

    st.subheader("選手タイプ別 通常特殊能力平均数")
    type_avg = df.assign(通常特殊能力数=special_lengths).groupby(["role", "player_type"])["通常特殊能力数"].mean().round(2).reset_index().rename(columns={"role": "投手/野手", "player_type": "選手タイプ", "通常特殊能力数": "平均数"})
    st.dataframe(type_avg, use_container_width=True, hide_index=True)

    col_personality1, col_personality2 = st.columns(2)
    all_specials = [name for values in df["special_abilities"] for name in values]
    with col_personality1:
        st.metric("緑特の出現数", sum(1 for name in all_specials if any(row["name"] == name and row.get("kind") == "green" for row in master.abilities)))
    with col_personality2:
        st.metric("個性系特殊能力の出現数", sum(1 for name in all_specials if name in PERSONALITY_SPECIALS))

    breaking_tables = breaking_balance_tables(df)
    st.subheader("変化球バランス")
    st.dataframe(breaking_tables["metrics"], use_container_width=True, hide_index=True)
    bcol1, bcol2 = st.columns(2)
    with bcol1:
        st.subheader("通常変化球数分布")
        st.dataframe(breaking_tables["count_dist"], use_container_width=True, hide_index=True)
        st.subheader("方向別出現数")
        st.dataframe(breaking_tables["direction"], use_container_width=True, hide_index=True)
        st.subheader("ストレート系第二種 種類別出現数")
        st.dataframe(breaking_tables["second_fastball"], use_container_width=True, hide_index=True)
    with bcol2:
        st.subheader("総変化量分布")
        st.dataframe(breaking_tables["movement_dist"], use_container_width=True, hide_index=True)
        st.subheader("球種別出現数")
        st.dataframe(breaking_tables["pitch"], use_container_width=True, hide_index=True)
        st.subheader("右投手/左投手別 不正球種チェック")
        st.dataframe(breaking_tables["invalid"], use_container_width=True, hide_index=True)

    sub_tables = sub_position_summary_tables(df)
    if sub_tables:
        st.subheader("サブポジ集計")
        st.dataframe(sub_tables["metrics"], use_container_width=True, hide_index=True)
        scol1, scol2 = st.columns(2)
        with scol1:
            st.dataframe(sub_tables["count_dist"], use_container_width=True, hide_index=True)
            st.dataframe(sub_tables["main_has_rate"], use_container_width=True, hide_index=True)
            st.dataframe(sub_tables["sub_counts"], use_container_width=True, hide_index=True)
        with scol2:
            st.dataframe(sub_tables["main_candidate"], use_container_width=True, hide_index=True)
            st.dataframe(sub_tables["apt_counts"], use_container_width=True, hide_index=True)
            st.dataframe(sub_tables["pos_apt"], use_container_width=True, hide_index=True)
        st.subheader("左投げ野手サブポジ違反チェック")
        st.dataframe(sub_tables["left_violation"], use_container_width=True, hide_index=True)

    col5, col6 = st.columns(2)
    with col5:
        st.subheader("野手ポジション別人数")
        fielder_positions = df[df["role"] == "野手"]["position"].value_counts().rename_axis("ポジション").reset_index(name="人数")
        st.dataframe(fielder_positions, use_container_width=True, hide_index=True)
    with col6:
        st.subheader("投手役割別人数")
        pitcher_roles = df[df["role"] == "投手"]["position"].value_counts().rename_axis("役割").reset_index(name="人数")
        st.dataframe(pitcher_roles, use_container_width=True, hide_index=True)


def sub_position_summary_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    fielders = df[df["role"] == "野手"].copy()
    if fielders.empty:
        return {}
    fielders["sub_count"] = fielders["sub_positions"].apply(len)
    exploded_rows = []
    for _, row in fielders.iterrows():
        for item in normalize_sub_positions(row.get("sub_positions", [])):
            exploded_rows.append({"メインポジション": row["position"], "サブポジ": item["position"], "評価": item["aptitude"]})
    exploded = pd.DataFrame(exploded_rows)
    return {
        "metrics": pd.DataFrame([
            {"指標": "サブポジ保有率", "値": round((fielders["sub_count"] > 0).mean() * 100, 2)},
            {"指標": "3個以上保有者数", "値": int((fielders["sub_count"] >= 3).sum())},
            {"指標": "捕手サブ出現率", "値": round(sum(any(i["position"] == "捕手" for i in v) for v in fielders["sub_positions"]) / len(fielders) * 100, 2)},
            {"指標": "外野手専任率", "値": round(((fielders["position"] == "外野手") & (fielders["sub_count"] == 0)).sum() / max(1, (fielders["position"] == "外野手").sum()) * 100, 2)},
            {"指標": "ユーティリティ型割合", "値": round(fielders["player_type"].isin(UTILITY_TYPES).mean() * 100, 2)},
        ]),
        "count_dist": fielders["sub_count"].clip(upper=3).map({0:"0個",1:"1個",2:"2個",3:"3個以上"}).value_counts().rename_axis("サブポジ数").reset_index(name="人数"),
        "main_has_rate": fielders.groupby("position")["sub_count"].apply(lambda s: round((s > 0).mean() * 100, 2)).reset_index(name="保有率%"),
        "main_candidate": exploded.groupby(["メインポジション", "サブポジ"]).size().reset_index(name="出現数") if not exploded.empty else pd.DataFrame(),
        "sub_counts": exploded["サブポジ"].value_counts().rename_axis("サブポジ").reset_index(name="出現数") if not exploded.empty else pd.DataFrame(),
        "apt_counts": exploded["評価"].value_counts().rename_axis("評価").reset_index(name="出現数") if not exploded.empty else pd.DataFrame(),
        "pos_apt": exploded.groupby(["サブポジ", "評価"]).size().reset_index(name="出現数") if not exploded.empty else pd.DataFrame(),
        "left_violation": fielders[fielders["handedness"].eq("左投") & fielders["sub_positions"].apply(lambda values: any(item["position"] in {"二塁手", "三塁手", "遊撃手"} for item in values))][["name", "position", "batting_throwing", "サブポジ" if "サブポジ" in fielders.columns else "sub_positions"]],
    }



def e(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def inject_powerpro_ui_css() -> None:
    st.markdown("""
    <style>
    .stApp {background: radial-gradient(circle at 18% 22%, rgba(255,255,255,.48) 0 8%, transparent 9%), linear-gradient(135deg,#dff8f5 0%,#98ded8 42%,#087d91 100%);}
    .stApp:before {content:""; position:fixed; inset:0; pointer-events:none; background: repeating-linear-gradient(135deg,rgba(255,255,255,.16) 0 2px,transparent 2px 34px); opacity:.5;}
    .block-container {max-width:1680px; padding-top:3.5rem; padding-bottom:2rem;}
    div[data-testid="stVerticalBlockBorderWrapper"] {background:rgba(255,255,255,.72); border-color:#0e7fbd!important;}
    .pp-title {background:linear-gradient(90deg,rgba(255,255,255,.92),rgba(229,249,255,.55)); border-left:9px solid #e23d4f; border-bottom:3px solid #1b7fbd; padding:12px 20px; border-radius:4px 20px 20px 4px; color:#063d77; font-weight:900; font-size:29px; margin-bottom:10px;}
    .pp-panel {background:#fff;}
    div[class*="st-key-latest_detail_shell"], div[class*="st-key-history_detail_shell"] {max-width:1560px; margin:0 auto; background:#fff; border:4px solid var(--pp-tab-color,#0876c9); border-radius:16px; padding:8px; box-shadow:0 7px 0 rgba(0,76,130,.18), inset 0 0 0 5px #e8f8ff; font-family:"Arial Rounded MT Bold","Hiragino Maru Gothic ProN","Yu Gothic UI","Meiryo",sans-serif;}
    div[class*="st-key-latest_detail_shell"] > div, div[class*="st-key-history_detail_shell"] > div {font-family:inherit;}
    .pp-header {display:grid; grid-template-columns:minmax(230px,1.05fr) 52px 72px 112px minmax(450px,1.7fr); gap:7px; align-items:stretch; margin-bottom:0; min-width:0;}
    .pp-name {background:linear-gradient(#ffbbb5,#ff6e68); border:3px solid #e82e42; border-radius:8px; font-size:28px; font-weight:900; text-align:center; padding:4px 7px; min-height:44px; color:#022d55; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; position:relative;}
    .pp-name-row {position:relative; min-width:0;}
    .pp-number-box {background:#fff; color:#075fbd; border:3px solid #c8e7ff; border-radius:5px; font-size:28px; line-height:1.38; font-weight:950; text-align:center; align-self:stretch; min-height:44px; display:flex; align-items:center; justify-content:center;}
    .pp-category-mark {background:linear-gradient(#fff,#e9f9ff); border:3px solid #c8e7ff; border-radius:5px; color:#075fbd; display:flex; align-items:center; justify-content:center; font-size:17px; font-weight:950; min-height:44px;}
    .pp-face {background:#f7fbff; border:2px solid #c8e7ff; border-radius:10px; display:flex; align-items:center; justify-content:center; min-height:76px; overflow:hidden;}
    .pp-face svg {width:72px; height:72px; flex:0 0 auto;}
    .pp-info {display:grid; grid-template-columns:minmax(190px,1.45fr) minmax(160px,1fr) minmax(104px,.8fr); gap:6px; align-content:stretch; min-width:0;}
    .pp-chip {background:#f7fbff; border:2px solid #d5edff; border-radius:9px; padding:5px 8px; color:#0a69b0; font-weight:800; font-size:17px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .pp-chip-wide {font-size:14px; letter-spacing:-.03em;}
    .pp-score {background:#0368b8; color:white; border-radius:7px; padding:1px 8px; display:inline-block; font-weight:900;}
    .pp-body {display:grid; grid-template-columns:36% 64%; gap:9px; background:#edf9fc; border:0; border-top:3px solid var(--pp-tab-color,#0876c9); border-radius:0 0 10px 10px; padding:9px; overflow:hidden; align-items:start; margin-top:0;}
    .pp-body-pitcher {grid-template-columns:40% 60%; min-height:430px; overflow:visible;}
    .pp-mini-card {background:#f8fcff; border:2px solid #cce8ff; border-radius:9px; padding:7px; color:#0a69b0; font-weight:900; min-height:50px;}
    .pp-mini-label {font-size:12px; opacity:.75; display:block; margin-bottom:3px;}
    .pp-ability-row {display:grid; grid-template-columns:minmax(102px,38%) 50px 1fr; align-items:center; margin:5px 0; background:#fff; border:2px solid #cfe9ff; border-radius:9px; min-height:48px; overflow:hidden; box-shadow:inset 0 2px rgba(255,255,255,.8);}
    .pp-label {font-size:18px; background:#fff; border-radius:7px; margin-left:6px; padding:4px 8px; color:#126bb0; font-weight:900; text-align:center; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .pp-rank {font-size:28px; font-weight:950; text-align:center; -webkit-text-stroke:.45px rgba(255,255,255,.75); text-shadow:0 1px rgba(255,255,255,.42); line-height:1; width:42px;}
    .pp-value {font-size:26px; color:#0b72bd; font-weight:950; text-align:right; padding-right:12px; overflow-wrap:anywhere;}
    .pp-special-grid {display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:3px;}
    .pp-special {height:42px; min-width:0; border-radius:7px; border:2px solid #65c6d6; background:linear-gradient(180deg,#f0fdff 0%,#b8eef4 58%,#83dce7 100%); color:#0871ad; font-weight:800; display:grid; grid-template-columns:minmax(0,1fr); place-items:center; padding:0 6px; font-size:17px; box-shadow:inset 0 1px rgba(255,255,255,.64), inset 0 -1px rgba(83,202,232,.08);}
    .pp-special-name {overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; max-width:100%; text-align:center;}
    .pp-special-ranked {display:grid; grid-template-columns:minmax(0,1fr) 26px; padding:0; overflow:hidden; gap:0; align-items:stretch;}
    .pp-special-ranked .pp-special-name {display:flex; align-items:center; justify-content:center; padding:0 4px; min-width:0;}
    .pp-special-rank-badge {display:flex; align-items:center; justify-content:center; align-self:stretch; width:26px; color:#fff; font-size:19px; line-height:1; font-weight:950; text-align:center; text-shadow:0 1px rgba(0,42,70,.32);}
    .pp-special.long .pp-special-name {font-size:15px; letter-spacing:-.065em;}
    .pp-special.xlong .pp-special-name {font-size:13px; letter-spacing:-.085em;}
    .pp-special.red {background:linear-gradient(#fff8f8,#ffe0e0); border-color:#f29a9a; color:#bd1624;}
    .pp-special.green {background:linear-gradient(180deg,#f3fff5 0%,#c9f2d2 100%); border-color:#56c978; color:#13783a;}
    .pp-special.neutral {background:linear-gradient(180deg,#fbffff 0%,#e4f8fb 100%); border-color:#9bdbe6; color:#0871ad;}
    .pp-special.gold {background:linear-gradient(#fffdf1,#fff0ad); border-color:#e0be3c; color:#836200;}
    .pp-special-ranked.rank-ab {background:linear-gradient(180deg,#f0fdff 0%,#b8eef4 58%,#83dce7 100%); border-color:#65c6d6; color:#0871ad;}
    .pp-special-ranked.rank-ab .pp-special-rank-badge {background:linear-gradient(180deg,#38c9dc 0%,#1595b5 100%); color:#fff;}
    .pp-special-ranked.rank-cde {background:linear-gradient(180deg,#fbffff 0%,#e8fbfe 55%,#cef4f9 100%); border-color:#83dceb; color:#0871ad;}
    .pp-special-ranked.rank-cde .pp-special-rank-badge {background:linear-gradient(180deg,#9be4ec 0%,#61bfd1 100%); color:#fff;}
    .pp-special-ranked.rank-fg {background:linear-gradient(180deg,#fff5f5 0%,#ffd3d3 55%,#ffadad 100%); border-color:#ef6c72; color:#c71c24;}
    .pp-special-ranked.rank-fg .pp-special-rank-badge {background:linear-gradient(180deg,#ed5a60 0%,#c8212b 100%); color:#fff;}
    .pp-special.empty {height:42px; background:linear-gradient(180deg,#e9fbff 0%,#b9eef7 55%,#83ddea 100%); border-color:#73cddd; color:transparent; box-shadow:inset 0 1px rgba(255,255,255,.75), inset 0 -2px rgba(48,178,212,.24);}
    .pp-section-title {color:#075f9e; font-weight:900; font-size:17px; margin:2px 0 7px;}
    .pp-help {position:static; background:#062247; color:white; padding:11px 18px; font-size:18px; font-weight:800; border-top:4px solid #0b4f8c; border-radius:8px; margin:16px 0;}
    .pp-list-note {color:#0a4773; font-weight:800; margin-bottom:8px;}
    .pp-player-row {width:100%; text-align:left; margin-bottom:4px;}
    div[data-testid="stButton"] > button {min-height:2.2rem; opacity:1!important;}
    div[data-testid="stButton"] > button:disabled {opacity:.45!important;}
    @media (max-width: 980px) {
      .pp-header {grid-template-columns:1fr;}
      .pp-info {grid-template-columns:1fr;}
      .pp-body,.pp-body-pitcher {grid-template-columns:1fr; min-height:0;}
      .pp-special-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
      .pp-usage-grid {grid-template-columns:repeat(4,minmax(0,1fr));}
    }
    .pp-aptitude-line {background:#f9fdff; border:2px solid #cfe9ff; border-radius:9px; color:#0a69b0; font-weight:900; padding:5px 9px; margin-bottom:6px; white-space:nowrap; font-size:15px;}
    .pp-pitcher-usage-row,.pp-pitcher-defense-row {display:grid; grid-template-columns:40% 1fr; align-items:center; margin:4px 0; background:#fff; border:2px solid #cfe9ff; border-radius:9px; min-height:39px; overflow:hidden; box-shadow:inset 0 2px rgba(255,255,255,.8);}
    .pp-pitcher-usage-values {display:flex; gap:14px; align-items:center; justify-content:space-around; min-width:0; white-space:nowrap; color:#0b72bd; font-weight:950; font-size:18px;}
    .pp-pitcher-usage-item {white-space:nowrap; display:inline-flex; gap:2px; align-items:baseline;}
    .pp-pitcher-defense-values {display:flex; gap:10px; align-items:baseline; justify-content:flex-end; padding-right:12px; white-space:nowrap; color:#0b72bd; font-weight:950;}
    @media (max-width: 980px) {.pp-pitcher-usage-values {font-size:15px; gap:8px;}}
    .pp-chart-wrap {height:346px; margin-top:6px; overflow:visible;}
    .pp-defense-grid,.pp-profile-grid {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px;}
    .pp-defense-compact {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; margin:5px 0; border:2px solid #cce8ff; border-radius:9px; overflow:hidden; background:#cce8ff;}
    .pp-defense-pos {display:grid; grid-template-columns:34px 34px 1fr; align-items:center; gap:4px; background:#f8fcff; border:0; border-radius:0; padding:8px 8px; color:#0a69b0; font-weight:900; min-height:42px;}
    .pp-defense-short {text-align:left;}
    .pp-defense-rank {text-align:center; font-size:18px; font-weight:950;}
    .pp-defense-num {text-align:right; color:#0b72bd;}
    .pp-defense-empty {grid-column:2 / 4; text-align:center; color:#b5d7f3; font-weight:950;}
    .pp-defense-pos.main {border-color:#0b8fe0; background:#eaf8ff;}
    .pp-usage-grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:3px;}
    .pp-usage-cell {min-height:46px; border:2px solid #bde7f0; border-radius:7px; display:flex; align-items:center; justify-content:center; padding:0 6px; font-weight:900; color:#0b72bd; background:rgba(235,250,253,.46); min-width:0; text-align:center;}
    .pp-usage-label {background:linear-gradient(180deg,#fff 0%,#e9f9fd 100%); color:#126bb0;}
    .pp-usage-value {background:linear-gradient(180deg,#f3fff5 0%,#c9f2d2 100%); border-color:#56c978; color:#13783a;}
    .pp-usage-empty {color:transparent; background:linear-gradient(180deg,#e9fbff 0%,#b9eef7 55%,#83ddea 100%); border-color:#73cddd;}
    .pp-header-left {display:grid; gap:5px; align-content:stretch; min-width:0;}
    .pp-posline {background:#f7fbff; border:2px solid #d5edff; border-radius:9px; padding:5px 8px; color:#0a69b0; font-weight:900; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .pp-profile-grid .wide {grid-column:1 / -1;}
    div[class*="st-key-latest_tab_"], div[class*="st-key-history_tab_"] {margin-bottom:-2px;}
    div[class*="st-key-latest_tab_"] button, div[class*="st-key-history_tab_"] button {background:#06396f!important; color:white!important; border-color:#052e5a!important; font-weight:900; border-radius:11px 11px 0 0!important; margin-right:0!important; min-height:3rem;}
    div[class*="st-key-latest_tab_"] button[kind="primary"], div[class*="st-key-history_tab_"] button[kind="primary"] {border-bottom-color:transparent!important;}
    div[class*="st-key-latest_tab_player"] button[kind="primary"], div[class*="st-key-history_tab_player"] button[kind="primary"] {background:#075fbd!important; border-color:#075fbd!important;}
    div[class*="st-key-latest_tab_pitcher"] button[kind="primary"], div[class*="st-key-history_tab_pitcher"] button[kind="primary"] {background:#d7193f!important; border-color:#d7193f!important;}
    div[class*="st-key-latest_tab_fielder"] button[kind="primary"], div[class*="st-key-history_tab_fielder"] button[kind="primary"] {background:#0876c9!important; border-color:#0876c9!important;}
    div[class*="st-key-latest_tab_usage"] button[kind="primary"], div[class*="st-key-history_tab_usage"] button[kind="primary"] {background:#d49a00!important; border-color:#d49a00!important;}
    div[class*="st-key-latest_tab_profile"] button[kind="primary"], div[class*="st-key-history_tab_profile"] button[kind="primary"] {background:#087d23!important; border-color:#087d23!important;}
    </style>
    """, unsafe_allow_html=True)


def player_from_history_row(row: pd.Series) -> dict[str, Any]:
    abilities = parse_json_column(row.get("abilities_json"), {})
    ranked = parse_json_column(row.get("ranked_special_abilities_json"), {})
    if ranked and isinstance(abilities, dict):
        abilities["ranked_specials"] = ranked
    player = row.to_dict()
    player.update({
        "abilities": abilities,
        "special_abilities": parse_json_column(row.get("special_abilities_json"), []),
        "breaking_balls": parse_json_column(row.get("breaking_balls_json"), []),
        "sub_positions": normalize_sub_positions(row.get("sub_positions_json", row.get("sub_positions", []))),
    })
    if isinstance(row.get("pitcher_aptitudes_json"), str):
        player.update(parse_json_column(row.get("pitcher_aptitudes_json"), {}))
    return player


def overall_score(p: dict[str, Any]) -> int:
    abilities = p.get("abilities", {}) if isinstance(p.get("abilities"), dict) else {}
    keys = ["コントロール", "スタミナ"] if p.get("role") == "投手" else ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
    values = [ability_numeric_value(abilities, key) for key in keys]
    speed = pitcher_speed_value(abilities)
    if p.get("role") == "投手" and speed:
        values.append(max(1, min(99, int((speed - 120) * 2))))
    numeric_values = [int(value) for value in values if isinstance(value, int | float)]
    return round(sum(numeric_values) / max(1, len(numeric_values)))


def render_player_icon_svg(p: dict[str, Any]) -> str:
    initial = e(str(p.get("name", "選"))[:1])
    cap = "#e83b4f" if p.get("role") == "投手" else "#0a76c9"
    return f'<svg width="96" height="96" viewBox="0 0 116 116" role="img" aria-label="選手アイコン"><circle cx="58" cy="62" r="34" fill="#ffd9b3" stroke="#8b5a32" stroke-width="3"/><path d="M20 54 Q58 12 96 54 Z" fill="{cap}" stroke="#fff" stroke-width="4"/><rect x="34" y="72" width="48" height="30" rx="8" fill="#fff" stroke="#b8d7ee"/><text x="58" y="47" text-anchor="middle" font-size="32" font-weight="900" fill="#fff">{initial}</text><circle cx="46" cy="62" r="4" fill="#073b6b"/><circle cx="70" cy="62" r="4" fill="#073b6b"/></svg>'



def ui_rank_color(rank_text: str) -> str:
    return {
        "S": "#f3b400",
        "A": "#ff3bbd",
        "B": "#ff315d",
        "C": "#ff9d00",
        "D": "#d7c900",
        "E": "#5fcbff",
        "F": "#63a4ff",
        "G": "#9aa4af",
    }.get(rank_text, "#cbd5e1")

def render_ability_rows(items: list[tuple[str, Any]]) -> str:
    rows = []
    for label, item in items:
        if isinstance(item, dict):
            rank_text = e(item.get("rank", "-"))
            value = e(item.get("value", "-"))
            color = ui_rank_color(str(item.get("rank", "")))
        else:
            rank_text = ""
            value = e(item)
            color = "#cbd5e1"
        rows.append(f'<div class="pp-ability-row"><div class="pp-label">{e(label)}</div><div class="pp-rank" style="color:{color}">{rank_text}</div><div class="pp-value">{value}</div></div>')
    return "".join(rows)


def special_kind(name: str, master: MasterData) -> str:
    return next((str(row.get("kind", "blue")) for row in master.abilities if row.get("name") == name), "blue")


def split_special_rank(name: str) -> tuple[str, str]:
    match = re.search(r"([A-G])$", name)
    if not match:
        return name, ""
    return name[: match.start()], match.group(1)


def special_rank_class(rank_text: str) -> str:
    if rank_text in {"A", "B"}:
        return "rank-ab"
    if rank_text in {"C", "D", "E"}:
        return "rank-cde"
    if rank_text in {"F", "G"}:
        return "rank-fg"
    return ""


def special_target_for_name(name: str, master: MasterData) -> str:
    return next((special_target_role(row) for row in master.abilities if row.get("name") == name), "共通")


def fixed_rank_slots(player: dict[str, Any], mode: str) -> list[str | None]:
    ranked = filtered_ranked_specials(player, mode)
    if mode == "pitcher":
        order = ["対ピンチ", "対左打者", "打たれ強さ", "ケガしにくさ", "ノビ", "クイック", None, "回復"]
    elif mode == "fielder":
        order = ["チャンス", "対左投手", "キャッチャー", "ケガしにくさ", "盗塁", "走塁", "送球", "回復"]
    else:
        return []
    return [ranked.get(name) if name else None for name in order]


def special_cell_html(name: str | None, kind: str = "blue") -> str:
    if not name:
        return '<div class="pp-special empty"><span></span></div>'
    base_name, rank_text = split_special_rank(name)
    length_cls = "xlong" if len(base_name) >= 11 else "long" if len(base_name) >= 8 else ""
    if rank_text:
        classes = " ".join(part for part in ["pp-special", "pp-special-ranked", special_rank_class(rank_text), length_cls] if part)
        return f'<div class="{classes}" title="{e(name)}"><span class="pp-special-name">{e(base_name)}</span><span class="pp-special-rank-badge">{e(rank_text)}</span></div>'
    cls = "gold" if kind == "gold" else "red" if kind == "red" else "green" if kind == "green" else "neutral" if kind == "neutral" else ""
    classes = " ".join(part for part in ["pp-special", cls, length_cls] if part)
    return f'<div class="{classes}" title="{e(name)}"><span class="pp-special-name">{e(base_name)}</span></div>'


def collect_special_entries(p: dict[str, Any], master: MasterData, mode: str) -> list[tuple[str, str]]:
    order = {"gold": 1, "blue": 2, "mixed": 2, "neutral": 2, "green": 3, "red": 4}
    usage_order = PITCHER_USAGE_ORDER if p.get("role") == "投手" else FIELDER_USAGE_ORDER
    usage_priority = {name: index for index, name in enumerate(usage_order)}
    entries: list[tuple[str, str]] = []
    for raw_name in p.get("special_abilities", []):
        name = str(raw_name)
        kind = special_kind(name, master)
        target = special_target_for_name(name, master)
        if mode == "pitcher" and (target not in ("投手", "共通") or name in USAGE_SPECIAL_NAMES):
            continue
        if mode == "fielder" and (target not in ("野手", "共通") or name in USAGE_SPECIAL_NAMES):
            continue
        if mode == "usage":
            player_role = "投手" if p.get("role") == "投手" else "野手"
            if name not in USAGE_SPECIAL_NAMES or target not in (player_role, "共通"):
                continue
        entries.append((name, kind))
    if mode == "usage":
        return sorted(entries, key=lambda item: (usage_priority.get(item[0], 99), item[0]))
    return sorted(entries, key=lambda item: order.get(item[1], 9))


def special_grid_cell_count(base_cell_count: int, fixed_slot_count: int, normal_count: int) -> int:
    required = fixed_slot_count + normal_count
    return max(base_cell_count, math.ceil(required / 4) * 4)


def render_special_grid_html(p: dict[str, Any], master: MasterData, mode: str = "fielder", cell_count: int | None = None) -> str:
    base_cell_count = cell_count or (16 if mode == "usage" else 32)
    fixed_slots = fixed_rank_slots(p, mode) if mode in ("pitcher", "fielder") else []
    display_entries = collect_special_entries(p, master, mode)
    actual_cell_count = special_grid_cell_count(base_cell_count, len(fixed_slots), len(display_entries))
    cells: list[str] = [special_cell_html(name) for name in fixed_slots]
    cells.extend(special_cell_html(name, kind) for name, kind in display_entries)
    while len(cells) < actual_cell_count:
        cells.append(special_cell_html(None))
    return '<div class="pp-special-grid">' + "".join(cells) + "</div>"

def pitch_display_name(name: Any) -> str:
    text = str(name or "")
    aliases = {
        "ツーシームファスト": "ツーシーム",
        "ムービングファスト": "ムービング",
        "シンキングツーシーム": "Sツーシーム",
        "ドロップカーブ": "Dカーブ",
        "ナックルカーブ": "Nカーブ",
        "サークルチェンジ": "Cチェンジ",
        "シンキングスプリット": "Sスプリット",
    }
    return aliases.get(text, text if len(text) <= 8 else text[:7] + "…")


def block_points(x1: int, y1: int, x2: int, y2: int, lane: int, movement: int) -> list[tuple[float, float, float]]:
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    nx, ny = -dy / length, dx / length
    points = []
    for step in range(1, min(7, max(0, movement)) + 1):
        t = 0.24 + step * 0.095
        points.append((x1 + dx * t + nx * lane * 8, y1 + dy * t + ny * lane * 8, length))
    return points


def render_pitch_chart_svg(balls: list[dict[str, Any]], batting_throwing: str = "") -> str:
    right_map = {"1": (205, 78), "2": (64, 150), "3": (120, 190), "4": (52, 185), "5": (188, 185)}
    directions = {code: (240 - x, y) for code, (x, y) in right_map.items()} if str(batting_throwing).startswith("左投") else right_map
    label_positions = {"1": (194, 58), "2": (49, 132), "3": (120, 204), "4": (50, 202), "5": (190, 202)}
    if str(batting_throwing).startswith("左投"):
        label_positions = {code: (240 - x, y) for code, (x, y) in label_positions.items()}
    grouped: dict[str, list[dict[str, Any]]] = {}
    second_fastballs = []
    for ball in balls or []:
        if ball.get("kind") == "breaking":
            grouped.setdefault(str(ball.get("direction_code")), []).append(ball)
        elif ball.get("kind") == "second_fastball":
            second_fastballs.append(ball)
    lines = [
        '<svg viewBox="0 0 240 218" width="100%" height="100%" role="img" aria-label="変化球方向図">',
        '<rect x="5" y="5" width="230" height="208" rx="12" fill="#f7fcff" stroke="#cce8ff" stroke-width="4"/>',
        '<text x="120" y="25" text-anchor="middle" fill="#126bb0" font-size="16" font-weight="900">ストレート</text>',
        '<rect x="34" y="62" width="72" height="9" rx="4" fill="#2ab8ff" stroke="#0788d0" stroke-width="2"/>',
        '<rect x="134" y="62" width="72" height="9" rx="4" fill="#2ab8ff" stroke="#0788d0" stroke-width="2"/>',
        '<circle cx="120" cy="72" r="14" fill="#fff" stroke="#118ee8" stroke-width="4"/>',
        '<text x="120" y="77" text-anchor="middle" fill="#ff4a2d" font-size="17" font-weight="900">⚾</text>',
    ]
    for code, (x2, y2) in directions.items():
        lines.append(f'<line x1="120" y1="72" x2="{x2}" y2="{y2}" stroke="#19a6ee" stroke-width="11" stroke-linecap="round" opacity=".38"/>')
        lines.append(f'<line x1="120" y1="72" x2="{x2}" y2="{y2}" stroke="#0b8fe0" stroke-width="3" stroke-linecap="round" opacity=".55"/>')
    if second_fastballs:
        names = " / ".join(e(pitch_display_name(ball.get("name"))) for ball in second_fastballs)
        lines.append(f'<text x="120" y="43" text-anchor="middle" fill="#126bb0" font-size="14" font-weight="900">{names}</text>')
        lines.append('<rect x="112" y="50" width="6" height="11" rx="2" fill="#ff9b19"/><rect x="122" y="50" width="6" height="11" rx="2" fill="#ff9b19"/>')
    placed_labels: list[tuple[float, float]] = []
    for code, balls_in_direction in grouped.items():
        x2, y2 = directions.get(code, (120, 190))
        lx, ly = label_positions.get(code, (x2, y2))
        for lane_index, ball in enumerate(balls_in_direction[:2]):
            lane = -1 if lane_index == 0 else 1
            color = "#0fa8f5" if lane_index == 0 else "#ff9518"
            stroke = "#0788d0" if lane_index == 0 else "#d67500"
            for bx, by, _ in block_points(120, 72, x2, y2, lane, pitch_movement(ball)):
                lines.append(f'<rect x="{bx - 5:.1f}" y="{by - 5:.1f}" width="10" height="10" rx="1.5" fill="{color}" stroke="{stroke}" stroke-width="1"/>')
            dx, dy = x2 - 120, y2 - 72
            length = max((dx * dx + dy * dy) ** 0.5, 1)
            nx, ny = -dy / length, dx / length
            offset = -10 if lane_index == 0 else 12
            extra_x, extra_y = LABEL_LANE_OFFSETS.get(code, [(0, -8), (0, 8)])[min(lane_index, 1)]
            raw_x = lx + nx * offset + extra_x
            raw_y = ly + ny * offset + extra_y
            anchor = "middle"
            if code == "3" and len(balls_in_direction) > 1:
                if lane_index == 0:
                    raw_x, anchor = 108, "end"
                else:
                    raw_x, anchor = 132, "start"
            name_x = min(215, max(25, raw_x))
            name_y = min(202, max(40, raw_y))
            if code != "3":
                for placed_x, placed_y in placed_labels:
                    if abs(name_x - placed_x) < 55 and abs(name_y - placed_y) < 18:
                        name_y += 8 if name_y >= placed_y else -8
                name_y = min(202, max(40, name_y))
                if name_x < 84:
                    anchor = "start"
                    name_x = max(25, name_x - 4)
                elif name_x > 156:
                    anchor = "end"
                    name_x = min(215, name_x + 4)
            else:
                name_x = min(215, max(25, name_x))
                name_y = min(202, max(40, name_y))
            placed_labels.append((name_x, name_y))
            lines.append(f'<text x="{name_x:.1f}" y="{name_y:.1f}" text-anchor="{anchor}" fill="#126bb0" font-size="15" font-weight="900">{e(pitch_display_name(ball.get("name")))}</text>')
    return "".join(lines) + "</svg>"


def compact_pitcher_aptitude_text(player: dict[str, Any]) -> str:
    abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    values = {key: player.get(key) or abilities.get(key) for key in PITCHER_APTITUDE_KEYS}
    if not any(values.values()):
        pos = str(player.get("position", ""))
        values = {"starter_aptitude": "◎" if pos == "先発" else "－", "reliever_aptitude": "◎" if pos == "中継ぎ" else "－", "closer_aptitude": "◎" if pos == "抑え" else "－"}
    labels = [("starter_aptitude", "先"), ("reliever_aptitude", "中"), ("closer_aptitude", "抑")]
    return " ".join(f"{label}{(values.get(key) or '－').replace('-', '－')}" for key, label in labels)



def pitcher_fallback_abilities() -> dict[str, Any]:
    return {"球速": "120 km/h", "コントロール": ability(1), "スタミナ": ability(1)}


def derive_pitcher_fielding_abilities(player: dict[str, Any]) -> dict[str, Any]:
    # 表示専用の野手補助能力です。バランス集計やCSVには含めず、SQLite保存形式も変更しません。
    # 同じseed（と選手名）から毎回同じ値を算出し、再描画やタブ移動で変化しないようにします。
    base = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    rng = random.Random(f"fielder-fallback:{player.get('seed', 0)}:{player.get('name', '')}")
    speed = pitcher_speed_value(base) or 135
    arm = max(45, min(85, int((speed - 120) * 1.15 + 45 + rng.randint(-4, 5))))
    return {
        "弾道": rng.choices([1, 2, 3], weights=[70, 27, 3], k=1)[0],
        "ミート": ability(rng.randint(10, 45)),
        "パワー": ability(rng.randint(10, 50)),
        "走力": ability(rng.randint(30, 65)),
        "肩力": ability(arm),
        "守備力": ability(rng.randint(35, 70)),
        "捕球": ability(rng.randint(30, 65)),
    }


def displayed_pitcher_abilities(player: dict[str, Any]) -> dict[str, Any]:
    if player.get("role") == "投手":
        return player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    return pitcher_fallback_abilities()


def displayed_fielder_abilities(player: dict[str, Any]) -> dict[str, Any]:
    if player.get("role") == "野手":
        return player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    return derive_pitcher_fielding_abilities(player)


def filtered_ranked_specials(player: dict[str, Any], mode: str) -> dict[str, str]:
    # 未設定ランクのD補完は画面表示用の標準値です。
    # 元のranked_specialsは変更せず、SQLite/CSV/Excel/バランス集計にも追加しません。
    abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    ranked = dict(abilities.get("ranked_specials", {}) or {})
    pitcher_names = {"対ピンチ", "対左打者", "打たれ強さ", "ノビ", "クイック"}
    fielder_names = {"チャンス", "対左投手", "盗塁", "走塁", "送球", "キャッチャー"}
    common_names = {"ケガしにくさ", "回復"}
    if mode == "pitcher":
        defaults = {name: f"{name}D" for name in ["対ピンチ", "対左打者", "打たれ強さ", "ケガしにくさ", "ノビ", "クイック", "回復"]}
        defaults.update({k: v for k, v in ranked.items() if k in common_names or k in pitcher_names})
        return {k: v for k, v in defaults.items() if k in pitcher_names or k in common_names}
    if mode == "fielder":
        defaults = {name: f"{name}D" for name in ["チャンス", "対左投手", "ケガしにくさ", "盗塁", "走塁", "送球", "回復"]}
        if player.get("position") == "捕手":
            defaults["キャッチャー"] = "キャッチャーD"
        defaults.update({k: v for k, v in ranked.items() if k in common_names or k in fielder_names})
        return {k: v for k, v in defaults.items() if k in fielder_names or k in common_names}
    return {}



def display_position_defense_value(player: dict[str, Any], full_position: str, mark: str, base_fielding: int | float | None) -> int | None:
    if mark == "－－" or not isinstance(base_fielding, int | float):
        return None
    if mark == "◎" and player.get("position") == full_position:
        rate_min, rate_max = 1.0, 1.0
    elif mark == "◎":
        rate_min, rate_max = 0.90, 1.0
    elif mark == "○":
        rate_min, rate_max = 0.75, 0.90
    else:
        rate_min, rate_max = 0.55, 0.75
    rng = random.Random(f"defense-table:{player.get('seed', 0)}:{full_position}:{mark}")
    value = int(round(base_fielding * rng.uniform(rate_min, rate_max)))
    return max(1, min(99, value))



def pitcher_usage_row_html(player: dict[str, Any]) -> str:
    abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    values = {key: player.get(key) or abilities.get(key) for key in PITCHER_APTITUDE_KEYS}
    if not any(values.values()):
        pos = str(player.get("position", ""))
        values = {"starter_aptitude": "◎" if pos == "先発" else "－", "reliever_aptitude": "◎" if pos == "中継ぎ" else "－", "closer_aptitude": "◎" if pos == "抑え" else "－"}
    items = [("starter_aptitude", "先"), ("reliever_aptitude", "中"), ("closer_aptitude", "抑")]
    value_html = "".join(f'<span class="pp-pitcher-usage-item"><span>{label}</span><span>{e((values.get(key) or "－").replace("-", "－"))}</span></span>' for key, label in items)
    return f'<div class="pp-pitcher-usage-row"><div class="pp-label">起用適性</div><div class="pp-pitcher-usage-values">{value_html}</div></div>'


def pitcher_defense_row_html(item: Any) -> str:
    if isinstance(item, dict):
        rank_text = str(item.get("rank", "－"))
        value = str(item.get("value", "－"))
    else:
        rank_text = "－"
        value = str(item if item is not None else "－")
    return f'<div class="pp-pitcher-defense-row"><div class="pp-label">守備力</div><div class="pp-pitcher-defense-values"><span>投</span><span style="color:{ui_rank_color(rank_text)};font-size:24px;text-shadow:1px 1px white;">{e(rank_text)}</span><span>{e(value)}</span></div></div>'

def render_defense_usage_left(player: dict[str, Any]) -> str:
    f = displayed_fielder_abilities(player)
    if player.get("role") == "投手":
        return render_ability_rows([
            ("走力", f.get("走力")),
            ("肩力", f.get("肩力")),
        ]) + pitcher_defense_row_html(f.get("守備力")) + render_ability_rows([
            ("捕球", f.get("捕球")),
        ]) + pitcher_usage_row_html(player)
    sub = {i["position"]: i["aptitude"] for i in normalize_sub_positions(player.get("sub_positions"))}
    pos_labels = [("捕", "捕手"), ("一", "一塁手"), ("二", "二塁手"), ("三", "三塁手"), ("遊", "遊撃手"), ("外", "外野手")]
    base_fielding = ability_numeric_value(f, "守備力")
    cells = []
    for short, full in pos_labels:
        mark = "◎" if player.get("position") == full else sub.get(full, "－－")
        value = display_position_defense_value(player, full, mark, base_fielding)
        main_cls = " main" if player.get("position") == full else ""
        if isinstance(value, int):
            pos_rank = rank(value)
            value_html = f'<span class="pp-defense-rank" style="color:{ui_rank_color(pos_rank)};">{e(pos_rank)}</span><span class="pp-defense-num">{e(value)}</span>'
        else:
            value_html = '<span class="pp-defense-empty">－－</span>'
        cells.append(f'<div class="pp-defense-pos{main_cls}"><span class="pp-defense-short">{short}</span>{value_html}</div>')
    return render_ability_rows([("走力", f.get("走力")), ("肩力", f.get("肩力"))]) + '<div class="pp-defense-compact">' + ''.join(cells) + '</div>' + render_ability_rows([("守備力", f.get("守備力")), ("捕球", f.get("捕球"))])

def render_profile_right(player: dict[str, Any]) -> str:
    display_name = player.get("back_name") or player.get("name")
    items = [("氏名", player.get("name"), "wide"), ("年齢", f"{player.get('age')}歳", ""), ("投打", player.get("batting_throwing"), ""), ("国籍", player.get("nationality"), ""), ("出身地", player.get("birthplace"), ""), ("身長", f"{player.get('height')}cm", ""), ("体重", f"{player.get('weight')}kg", ""), ("表示名", display_name, "wide")]
    cards = ''.join(f'<div class="pp-mini-card {cls}"><span class="pp-mini-label">{e(label)}</span>{e(value)}</div>' for label, value, cls in items)
    return '<div class="pp-profile-grid pp-game-profile">' + cards + '</div>'


def render_generation_info_html(player: dict[str, Any]) -> str:
    items = [("カテゴリ", player.get("category")), ("タイプ", player.get("player_type")), ("seed", player.get("seed"))]
    cards = ''.join(f'<div class="pp-mini-card"><span class="pp-mini-label">{e(label)}</span>{e(value)}</div>' for label, value in items)
    return '<details class="pp-generation-info"><summary>生成情報</summary><div class="pp-profile-grid">' + cards + '</div></details>'


def player_uniform_number(player: dict[str, Any]) -> int:
    return random.Random(f"number:{player.get('seed', 0)}:{player.get('name', '')}").randint(0, 99)


def role_stats_placeholder(player: dict[str, Any]) -> str:
    if player.get("role") == "投手":
        return "防 ----　--勝 --敗 --HP --S"
    return "率 .---　--本 --点 --盗"


def role_form_placeholder(player: dict[str, Any]) -> str:
    return "オーバースロー1" if player.get("role") == "投手" else "スタンダード1"


def header_position_text(player: dict[str, Any]) -> str:
    if player.get("role") == "投手":
        return f"適性　{compact_pitcher_aptitude_text(player)}"
    short_positions = {"捕手": "捕", "一塁手": "一", "二塁手": "二", "三塁手": "三", "遊撃手": "遊", "外野手": "外"}
    return f"守備位置　{short_positions.get(str(player.get('position', '')), player.get('position', '－'))}"


def normalize_selected_tab_value(player: dict[str, Any], value: Any) -> str:
    if value == "選手能力" or value not in TAB_LABELS:
        return "投手能力" if player.get("role") == "投手" else "野手能力"
    return str(value)


def usage_special_categories(player: dict[str, Any], master: MasterData) -> dict[str, list[str]]:
    entries = [name for name, _kind in collect_special_entries(player, master, "usage")]
    if player.get("role") == "投手":
        mapping = {
            "投球方針": {"速球中心", "変化球中心", "投球位置左", "投球位置右", "テンポ○"},
            "起用法": {"フル出場", "調子次第"},
            "その他": {"人気者"},
        }
    else:
        mapping = {
            "打撃方針": {"ミート多用", "強振多用", "積極打法", "慎重打法", "チームプレイ○", "チームプレイ×"},
            "走塁方針": {"積極盗塁", "慎重盗塁", "積極走塁"},
            "守備方針": {"積極守備"},
            "起用法": {"フル出場", "調子次第"},
            "その他": {"人気者"},
        }
    return {label: [name for name in entries if name in names] for label, names in mapping.items() if any(name in names for name in entries)}


def render_usage_categories_html(player: dict[str, Any], master: MasterData) -> str:
    cells: list[str] = []
    categories = usage_special_categories(player, master)
    if not categories:
        cells.extend([
            '<div class="pp-usage-cell pp-usage-label">起用法</div>',
            '<div class="pp-usage-cell pp-usage-empty"></div>',
            '<div class="pp-usage-cell pp-usage-empty"></div>',
            '<div class="pp-usage-cell pp-usage-empty"></div>',
        ])
    else:
        for label, names in categories.items():
            for offset in range(0, max(1, len(names)), 3):
                row_names = names[offset: offset + 3]
                row_label = label if offset == 0 else ''
                cells.append(f'<div class="pp-usage-cell pp-usage-label">{e(row_label)}</div>')
                for name in row_names:
                    cells.append(f'<div class="pp-usage-cell pp-usage-value">{e(name)}</div>')
                while len(cells) % 4 != 0:
                    cells.append('<div class="pp-usage-cell pp-usage-empty"></div>')
    target_count = special_grid_cell_count(32, 0, len(cells))
    while len(cells) < target_count:
        cells.append('<div class="pp-usage-cell pp-usage-empty"></div>')
    return '<div class="pp-usage-grid">' + ''.join(cells) + '</div>'

def set_selected_tab(tab_key: str, label: str) -> None:
    st.session_state[tab_key] = label


def render_header_html(p: dict[str, Any]) -> str:
    category_mark = {"架空球団用": "架", "ドラフト候補用": "候", "助っ人外国人用": "外"}.get(str(p.get("category", "")), "球")
    return f"""
      <div class="pp-header">
        <div class="pp-header-left">
          <div class="pp-name-row"><div class="pp-name">{e(p.get('name'))}</div></div>
          <div class="pp-posline">{e(header_position_text(p))}</div>
        </div>
        <div class="pp-category-mark" title="{e(p.get('category'))}">{e(category_mark)}</div>
        <div class="pp-number-box">{player_uniform_number(p)}</div>
        <div class="pp-face">{render_player_icon_svg(p)}</div>
        <div class="pp-info">
          <div class="pp-chip"><span class="pp-mini-label">成績</span>{e(role_stats_placeholder(p))}</div>
          <div class="pp-chip pp-chip-wide"><span class="pp-mini-label">フォーム</span>{e(role_form_placeholder(p))}</div>
          <div class="pp-chip"><span class="pp-mini-label">投打</span>{e(p.get('batting_throwing'))}</div>
        </div>
      </div>"""


def render_detail_panel(p: dict[str, Any], master: MasterData, key_prefix: str) -> None:
    tab_key = f"{key_prefix}_selected_player_tab"
    tab = normalize_selected_tab_value(p, st.session_state.get(tab_key))
    st.session_state[tab_key] = tab
    panel_color = TAB_COLORS.get(tab, "#0876c9")
    with st.container(key=f"{key_prefix}_detail_shell"):
        st.markdown(f'<style>div[class*="st-key-{key_prefix}_detail_shell"]{{--pp-tab-color:{panel_color};}}</style>', unsafe_allow_html=True)
        st.markdown(render_header_html(p), unsafe_allow_html=True)
        tabs = [(label, {"投手能力":"pitcher", "野手能力":"fielder", "守備・起用":"usage", "プロフィール":"profile"}[label], TAB_COLORS[label]) for label in TAB_LABELS]
        tab_cols = st.columns(len(tabs), gap="small")
        for col, (label, key_name, _color) in zip(tab_cols, tabs):
            with col:
                st.button(label, key=f"{key_prefix}_tab_{key_name}", use_container_width=True, type="primary" if tab == label else "secondary", on_click=set_selected_tab, args=(tab_key, label))
        st.markdown(render_detail_body_html(p, master, tab), unsafe_allow_html=True)


def render_detail_body_html(p: dict[str, Any], master: MasterData, effective_tab: str) -> str:
    if effective_tab == "投手能力":
        pa = displayed_pitcher_abilities(p)
        balls = p.get("breaking_balls", []) if p.get("role") == "投手" else []
        left = render_ability_rows([("球速", pa.get("球速")), ("コントロール", pa.get("コントロール")), ("スタミナ", pa.get("スタミナ"))]) + f'<div class="pp-chart-wrap">{render_pitch_chart_svg(balls, str(p.get("batting_throwing", "")))}</div>'
        right = render_special_grid_html(p, master, mode="pitcher")
    elif effective_tab == "野手能力":
        fa = displayed_fielder_abilities(p)
        pos = p.get("position") if p.get("role") == "野手" else "投"
        left = render_ability_rows([("守備位置", pos), ("弾道", fa.get("弾道")), ("ミート", fa.get("ミート")), ("パワー", fa.get("パワー")), ("走力", fa.get("走力")), ("肩力", fa.get("肩力")), ("守備力", fa.get("守備力")), ("捕球", fa.get("捕球"))])
        right = render_special_grid_html(p, master, mode="fielder")
    elif effective_tab == "守備・起用":
        left = render_defense_usage_left(p)
        right = render_usage_categories_html(p, master)
    else:
        if p.get("role") == "投手":
            pa = displayed_pitcher_abilities(p)
            left = render_ability_rows([("球速", pa.get("球速")), ("コントロール", pa.get("コントロール")), ("スタミナ", pa.get("スタミナ"))]) + f'<div class="pp-chart-wrap">{render_pitch_chart_svg(p.get("breaking_balls", []), str(p.get("batting_throwing", "")))}</div>'
        else:
            fa = displayed_fielder_abilities(p)
            left = render_ability_rows([("弾道", fa.get("弾道")), ("ミート", fa.get("ミート")), ("パワー", fa.get("パワー")), ("走力", fa.get("走力")), ("肩力", fa.get("肩力")), ("守備力", fa.get("守備力")), ("捕球", fa.get("捕球"))])
        right = render_profile_right(p) + render_generation_info_html(p)
    body_class = "pp-body pp-body-pitcher" if effective_tab == "投手能力" else "pp-body"
    return f'<div class="{body_class}"><div>{left}</div><div>{right}</div></div>'

def select_player(index_key: str, selected_index: int) -> None:
    st.session_state[index_key] = selected_index


def render_player_browser(players: list[dict[str, Any]], master: MasterData, key_prefix: str) -> None:
    if not players:
        st.info("表示する選手がまだありません。左の条件で生成してください。")
        return
    index_key = f"{key_prefix}_selected_index"
    st.session_state[index_key] = min(max(int(st.session_state.get(index_key, 0)), 0), len(players) - 1)
    st.markdown('<div class="pp-list-note">選手一覧から詳細表示する選手を選択</div>', unsafe_allow_html=True)
    options = list(range(len(players)))
    labels = {index: f"{index + 1}. {player.get('name')}｜{player.get('position')}｜{player.get('player_type')}｜{player.get('age')}歳｜{player.get('batting_throwing')}" for index, player in enumerate(players)}
    selected = st.selectbox("選手一覧", options, index=st.session_state[index_key], format_func=lambda index: labels[index], key=f"{key_prefix}_player_select", label_visibility="collapsed")
    st.session_state[index_key] = int(selected)
    nav_prev, nav_next = st.columns([1, 1])
    if nav_prev.button("前の選手", use_container_width=True, disabled=st.session_state[index_key] <= 0, key=f"{key_prefix}_prev"):
        st.session_state[index_key] -= 1
        st.rerun()
    if nav_next.button("次の選手", use_container_width=True, disabled=st.session_state[index_key] >= len(players) - 1, key=f"{key_prefix}_next"):
        st.session_state[index_key] += 1
        st.rerun()
    render_detail_panel(players[st.session_state[index_key]], master, key_prefix)

def main() -> None:
    st.set_page_config(page_title="パワプロ風 架空選手生成", page_icon="⚾", layout="wide")
    init_db()
    master = load_master_data()
    inject_powerpro_ui_css()
    st.markdown('<div class="pp-title">⚾ 選手能力詳細ジェネレーター</div>', unsafe_allow_html=True)
    st.write("投手/野手、カテゴリ、生成人数だけを選ぶと、ゲーム風の能力詳細画面で確認できます。")
    with st.sidebar:
        st.header("画面")
        page = st.radio("表示する画面", ["選手生成", "バランス確認"], label_visibility="collapsed")
        st.header("生成条件")
        role = st.radio("投手 / 野手", ["投手", "野手"], horizontal=True)
        category = st.selectbox("カテゴリ", CATEGORIES)
        count = st.number_input("生成人数", min_value=1, max_value=1000, value=3, step=1)
        generate = st.button("生成する", type="primary", use_container_width=True)
        st.caption(f"Version {APP_VERSION}")
    if page == "バランス確認":
        render_balance_check(master)
        return
    if generate:
        total_count = int(count)
        progress = st.progress(0, text="選手を生成中です...")
        players = []
        seeds = generate_batch_seeds(total_count)
        for index, seed in enumerate(seeds):
            players.append(generate_player(role, category, master, seed=seed))
            progress.progress((index + 1) / total_count, text=f"選手を生成中です... {index + 1}/{total_count}")
        saved_count = save_players(players)
        progress.empty()
        st.session_state["latest_players"] = players
        st.session_state["latest_selected_index"] = 0
        st.session_state["latest_selected_player_tab"] = "投手能力" if role == "投手" else "野手能力"
        st.success(f"{len(players)}人の選手を生成し、SQLiteに{saved_count}件保存しました。")
    render_player_browser(st.session_state.get("latest_players", []), master, "latest")
    latest_players = st.session_state.get("latest_players", [])
    latest_index = min(max(int(st.session_state.get("latest_selected_index", 0)), 0), max(0, len(latest_players) - 1)) if latest_players else 0
    latest_role = latest_players[latest_index].get("role") if latest_players else "投手"
    latest_tab = normalize_selected_tab_value({"role": latest_role}, st.session_state.get("latest_selected_player_tab"))
    role_help = "球速、制球、スタミナ、変化球と投手特殊能力を確認します。" if latest_role == "投手" else "打撃、走塁、守備の基礎能力と野手特殊能力を確認します。"
    help_messages = {
        "投手能力": "球速、制球、スタミナ、変化球と投手特殊能力を確認します。",
        "野手能力": "打撃、走塁、守備の基礎能力と野手特殊能力を確認します。",
        "守備・起用": "メインポジション、サブポジション、起用適性を確認します。",
        "プロフィール": "年齢、国籍、出身地、体格、生成カテゴリを確認します。",
    }
    st.markdown(f'<div class="pp-help">{e(help_messages.get(latest_tab, role_help))}</div>', unsafe_allow_html=True)
    st.divider()
    history = load_history()
    history_players = [player_from_history_row(row) for _, row in history.head(100).iterrows()] if not history.empty else []
    with st.expander("過去生成選手", expanded=False):
        render_player_browser(history_players, master, "history")
        st.dataframe(history, use_container_width=True, hide_index=True)
        if not history.empty:
            st.download_button("CSV出力", data=history.to_csv(index=False).encode("utf-8-sig"), file_name="pawapuro_players.csv", mime="text/csv")
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                history.to_excel(writer, sheet_name="players", index=False)
            st.download_button("Excel出力", data=excel_buffer.getvalue(), file_name="pawapuro_players.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            st.info("同じseedを使うことで、同条件の再生成に利用できるデータ構造です。")


if __name__ == "__main__":
    main()
