import csv
import json
import random
import re
import sqlite3
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, seed INTEGER NOT NULL,
                role TEXT NOT NULL, category TEXT NOT NULL, name TEXT NOT NULL, age INTEGER NOT NULL,
                nationality TEXT NOT NULL, birthplace TEXT NOT NULL, position TEXT NOT NULL, player_type TEXT NOT NULL,
                handedness TEXT NOT NULL, batting_throwing TEXT NOT NULL, height INTEGER NOT NULL, weight INTEGER NOT NULL,
                abilities_json TEXT NOT NULL, special_abilities_json TEXT NOT NULL, breaking_balls_json TEXT NOT NULL,
                sub_positions_json TEXT NOT NULL DEFAULT '[]'
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
        if "sub_positions_json" not in columns:
            conn.execute("ALTER TABLE players ADD COLUMN sub_positions_json TEXT NOT NULL DEFAULT '[]'")


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


def adjust_special_chance(row: dict[str, Any], base_chance: int, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None) -> float:
    abilities = abilities or {}
    name = str(row.get("name", ""))
    kind = str(row.get("kind", ""))
    power = str(row.get("power", "normal"))
    base_scale = 0.98 if kind == "green" or name in PERSONALITY_SPECIALS else 0.70
    chance = 0.35 if power == "gold" or kind == "gold" else float(base_chance) * base_scale
    if power == "strong" or name in STRONG_SPECIALS:
        chance *= 0.70
    if kind == "red":
        chance *= 1.28
    if kind == "mixed":
        chance *= 0.90

    if category == "ドラフト候補用":
        chance *= 0.86
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 1.20
    elif category == "助っ人外国人用":
        chance *= 1.18
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 1.18
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
        if name in contact:
            if player_type == "巧打型": chance += 2
            chance += meet_dev * 0.35
            if isinstance(meet, int | float): chance += 0.5 if meet >= 70 else -1.8 if meet < 45 and name == "アベレージヒッター" else 0
        if name in run:
            if player_type == "俊足型": chance += 2
            chance += speed_dev * 0.45
            if isinstance(speed, int | float): chance += 0.8 if speed >= 70 else -1.8 if speed < 45 else 0
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
            chance += 0.7
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
                if player_type == "速球派": chance -= 1
            if name in {"寸前", "負け運", "スロースターター"}:
                if isinstance(control, int | float) and control < 55: chance += 1
                if isinstance(stamina, int | float) and stamina < 50: chance += 1
            if name == "スロースターター" and position == "先発" and isinstance(stamina, int | float) and stamina < 45: chance += 1
            chance -= 0.05

    max_chance = 8.0 if power == "strong" or name in STRONG_SPECIALS else 25.0
    return max(0.0, min(max_chance, float(chance)))


def generate_specials(rng: random.Random, master: MasterData, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None) -> list[str]:
    selected, used_groups = [], set()
    candidates = [row for row in master.abilities if special_target_role(row) in (role, "共通") and not is_ranked_special(row)]
    rng.shuffle(candidates)
    for row in candidates:
        group = str(row.get("group", ""))
        if group in used_groups:
            continue
        chance = adjust_special_chance(row, int(row.get("weight", 0) or 0), role, player_type, position, age, abilities, breaking_balls, category)
        if rng.random() < chance / 100:
            selected.append(row["name"])
            used_groups.add(group)
    return selected



def ranked_shift_for_group(rng: random.Random, group_name: str, role: str, position: str, player_type: str, abilities: dict[str, Any]) -> int:
    shift = 0
    if role == "投手":
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
    veteran_keep = age >= 35 and (player_type == "巧打型" or rng.random() < 0.12)
    base = 48 + (8 if 24 <= age <= 31 else 0) - (4 if age <= 19 else 0) - (5 if age >= 35 and not veteran_keep else 1 if age >= 35 else 0)
    mods = {"ミート": 0, "パワー": 0, "走力": 0, "肩力": 0, "守備力": 0, "捕球": 0}
    for key in mods:
        mods[key] += rng.randint(-14, 16)
    type_mods = {
        "巧打型": {"ミート": 16, "パワー": -4}, "長距離砲": {"パワー": 20, "走力": -8, "ミート": -4},
        "俊足型": {"走力": 20, "守備力": 6, "パワー": -8}, "守備職人": {"守備力": 18, "捕球": 14, "ミート": -3},
        "強肩型": {"肩力": 20, "守備力": 5}, "バランス型": {"ミート": 5, "パワー": 5, "走力": 5, "肩力": 5, "守備力": 5, "捕球": 5},
    }
    pos_mods = {
        "捕手": {"ミート": -8, "肩力": 12, "守備力": -1, "捕球": -2, "走力": -8},
        "遊撃手": {"ミート": -8, "パワー": -9, "走力": 16, "肩力": 8, "守備力": 9, "捕球": 1},
        "二塁手": {"パワー": -5, "走力": 17, "肩力": 2, "守備力": 9, "捕球": 5},
        "三塁手": {"パワー": 6, "走力": -1, "肩力": 7, "守備力": -3, "捕球": -3},
        "一塁手": {"パワー": 13, "走力": -9, "肩力": 0, "守備力": -6, "捕球": -2},
        "外野手": {"パワー": 3, "走力": 14, "肩力": 9, "守備力": -1, "捕球": -3},
    }
    for d in (type_mods.get(player_type, {}), pos_mods.get(position, {})):
        for k, v in d.items(): mods[k] += v
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
        if player_type in ("巧打型", "守備職人"):
            mods["パワー"] -= 3
    if age >= 35:
        decline = rng.randint(3, 8) if not veteran_keep else rng.randint(0, 3)
        mods["走力"] -= decline + 2
        mods["守備力"] -= decline
        mods["捕球"] -= max(1, decline - 1)
        if player_type == "巧打型":
            mods["ミート"] += 4
        mods["パワー"] += 2
    category_tune = {
        "架空球団用": {"ミート": -5, "パワー": 0, "走力": 4, "肩力": 3, "守備力": -4, "捕球": -4},
        "ドラフト候補用": {"ミート": -5, "パワー": 0, "走力": 5, "肩力": 2, "守備力": -5, "捕球": -3},
        "助っ人外国人用": {"ミート": -6, "パワー": 0, "走力": 5, "肩力": 3, "守備力": -5, "捕球": -3},
    }
    position_tune = {
        "捕手": {"ミート": -3, "守備力": -4, "捕球": -2, "走力": -1},
        "二塁手": {"ミート": -1, "パワー": -1, "走力": 1, "守備力": 1, "捕球": 1},
        "遊撃手": {"ミート": -3, "パワー": -2, "走力": 2, "守備力": -2, "捕球": -2},
        "外野手": {"ミート": -2, "パワー": 1, "走力": 3, "肩力": 2},
        "一塁手": {"ミート": -2, "パワー": 4, "走力": -1},
        "三塁手": {"ミート": -5, "パワー": 6, "守備力": -2, "捕球": -2},
    }
    for tune in (category_tune.get(category, {}), position_tune.get(position, {})):
        for k, v in tune.items():
            mods[k] += v
    result = {k: ability(base + v) for k, v in mods.items()}
    if position == "捕手":
        result["肩力"] = ability(max(result["肩力"]["value"], 45))
        result["守備力"] = ability(max(result["守備力"]["value"], 40))
        result["捕球"] = ability(max(result["捕球"]["value"], 36))
    elif position == "遊撃手":
        result["守備力"] = ability(max(result["守備力"]["value"], 40))
        result["捕球"] = ability(max(result["捕球"]["value"], 36))
    if position == "捕手":
        if player_type == "巧打型":
            meet_cap = 64 if 24 <= age <= 31 and result["パワー"]["value"] >= 55 else 59
            result["ミート"] = ability(min(result["ミート"]["value"], meet_cap))
        elif player_type in {"守備職人", "強肩型", "俊足型"} or age <= 22:
            result["ミート"] = ability(min(result["ミート"]["value"], 49))
        elif player_type == "長距離砲":
            result["ミート"] = ability(min(result["ミート"]["value"], 49))
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
    prime = 1 if 24 <= age <= 32 else -1 if age <= 19 or (age >= 35 and not veteran_keep) else 0
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
        speed -= rng.randint(2, 5) if not veteran_keep else rng.randint(0, 2)
        stamina -= rng.randint(4, 9) if not veteran_keep else rng.randint(0, 3)
        if player_type == "技巧派":
            control += 5
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
        if pos == "捕手": return arm >= 60 and catch >= 45 and player_type in {"守備職人", "強肩型", "バランス型"} and category != "助っ人外国人用"
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
    with sqlite3.connect(DB_PATH) as conn:
        for p in players:
            conn.execute("""INSERT INTO players (created_at, seed, role, category, name, age, nationality, birthplace, position, player_type, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, breaking_balls_json, sub_positions_json)
                          VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (p["seed"], p["role"], p["category"], p["name"], p["age"], p["nationality"], p["birthplace"], p["position"], p["player_type"], p["handedness"], p["batting_throwing"], p["height"], p["weight"], json.dumps(p["abilities"], ensure_ascii=False), json.dumps(p["special_abilities"], ensure_ascii=False), json.dumps(p["breaking_balls"], ensure_ascii=False), json.dumps(normalize_sub_positions(p.get("sub_positions", [])), ensure_ascii=False)))
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
        history = pd.read_sql_query("SELECT id, created_at, seed, role, category, name, age, nationality, birthplace, position, player_type, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, breaking_balls_json, sub_positions_json FROM players ORDER BY id DESC", conn)
    if not history.empty:
        abilities = history["abilities_json"].apply(lambda value: parse_json_column(value, {}))
        for key in PITCHER_APTITUDE_KEYS:
            history[key] = abilities.apply(lambda item: item.get(key) if isinstance(item, dict) else None)
        history["sub_positions"] = history["sub_positions_json"].apply(normalize_sub_positions)
        history["サブポジ数"] = history["sub_positions"].apply(len)
        history["サブポジ"] = history["sub_positions"].apply(format_sub_positions)
        history["サブポジ一覧"] = history["sub_positions"].apply(lambda values: " / ".join(item["position"] for item in values))
        history["サブポジ評価一覧"] = history["sub_positions"].apply(lambda values: " / ".join(item["aptitude"] for item in values))
    return history


def parse_json_column(value: Any, fallback: Any) -> Any:
    if pd.isna(value):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def load_history_for_balance() -> pd.DataFrame:
    history = load_history()
    if history.empty:
        return history
    df = history.copy()
    df["abilities"] = df["abilities_json"].apply(lambda value: parse_json_column(value, {}))
    df["special_abilities"] = df["special_abilities_json"].apply(lambda value: parse_json_column(value, []))
    df["ranked_specials"] = df["abilities"].apply(lambda value: value.get("ranked_specials", {}) if isinstance(value, dict) else {})
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

def render_ability_item(label: str, item: Any) -> None:
    if isinstance(item, dict):
        st.markdown(f"<span style='background:{RANK_COLORS[item['rank']]};color:#111;border-radius:999px;padding:0.15rem 0.55rem;font-weight:700'>{item['rank']}</span> **{label}** {item['value']}", unsafe_allow_html=True)
    else:
        st.markdown(f"**{label}** {item}")


def render_card(p: dict[str, Any]) -> None:
    with st.container(border=True):
        st.subheader(f"{p['name']}（{p['position']} / {p['player_type']}）")
        st.caption(f"seed: {p['seed']} / {p['category']} / {p['nationality']}・{p['birthplace']} / {p['age']}歳 / {p['height']}cm {p['weight']}kg")
        cols = st.columns(3)
        cols[0].metric("利き腕", p["handedness"])
        cols[1].metric("投打", p["batting_throwing"])
        cols[2].metric("種別", p["role"])
        if p["role"] == "投手":
            st.markdown(f"**投手適正** {pitcher_aptitude_text(p)}")
        else:
            st.markdown(f"**サブポジ** {format_sub_positions(p.get('sub_positions', []))}")
        st.markdown("#### 能力")
        for k, v in p["abilities"].items():
            if k != "ranked_specials":
                render_ability_item(k, v)
        if p["breaking_balls"]:
            st.markdown("#### 変化球")
            st.write(" / ".join(f"{'第2 ' if b.get('is_second_pitch') else ''}{b['name']}({b.get('direction', b['name'])}) {pitch_movement(b)}" for b in p["breaking_balls"]))
        ranked_specials = p.get("abilities", {}).get("ranked_specials", {})
        st.markdown("#### ランク系特殊能力")
        st.write("、".join(ranked_specials.values()) if ranked_specials else "なし")
        st.markdown("#### 通常特殊能力")
        st.write("、".join(p["special_abilities"]) if p["special_abilities"] else "なし")


def main() -> None:
    st.set_page_config(page_title="パワプロ風 架空選手生成", page_icon="⚾", layout="wide")
    init_db()
    master = load_master_data()
    st.title("⚾ パワプロ風 架空選手生成ツール")
    st.write("投手/野手、カテゴリ、生成人数だけを選ぶMVPです。その他の項目は重み付きランダムで自動生成します。")
    with st.sidebar:
        st.header("画面")
        page = st.radio("表示する画面", ["選手生成", "バランス確認"], label_visibility="collapsed")
        st.header("生成条件")
        role = st.radio("投手 / 野手", ["投手", "野手"], horizontal=True)
        category = st.selectbox("カテゴリ", CATEGORIES)
        count = st.number_input("生成人数", min_value=1, max_value=1000, value=3, step=1)
        generate = st.button("生成する", type="primary", use_container_width=True)
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
        st.success(f"{len(players)}人の選手を生成し、SQLiteに{saved_count}件保存しました。")
    for player in st.session_state.get("latest_players", []):
        render_card(player)
    st.divider()
    st.header("過去生成選手")
    history = load_history()
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
