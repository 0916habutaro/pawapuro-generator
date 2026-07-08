import csv
import json
import random
import re
import sqlite3
from dataclasses import dataclass
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
RANKED_SPECIAL_BASE_WEIGHTS = {"A": 2, "B": 7, "C": 18, "D": 46, "E": 18, "F": 7, "G": 2}
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
                abilities_json TEXT NOT NULL, special_abilities_json TEXT NOT NULL, breaking_balls_json TEXT NOT NULL
            )
        """)


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


def generate_specials(rng: random.Random, master: MasterData, role: str, player_type: str) -> list[str]:
    selected, used_groups = [], set()
    count = weighted_choice(rng, [(0, 10), (1, 25), (2, 32), (3, 22), (4, 9), (5, 2)])
    candidates = [row for row in master.abilities if special_target_role(row) in (role, "共通") and not is_ranked_special(row)]
    rng.shuffle(candidates)
    for row in candidates:
        if len(selected) >= count:
            break
        group = str(row.get("group", ""))
        if group in used_groups:
            continue
        power = str(row.get("power", "normal"))
        chance = int(row.get("weight", 0) or 0)
        if power == "gold": chance = 1
        if power == "red": chance += 2
        if player_type in ("長距離砲", "速球派") and power == "strong": chance += 2
        if rng.randint(1, 100) <= chance:
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
    pos_mods = {"捕手": {"肩力": 10, "守備力": 8}, "遊撃手": {"守備力": 12, "肩力": 6}, "二塁手": {"守備力": 8, "走力": 4}, "一塁手": {"パワー": 8, "走力": -4}, "外野手": {"走力": 6, "肩力": 8}}
    for d in (type_mods.get(player_type, {}), pos_mods.get(position, {})):
        for k, v in d.items(): mods[k] += v
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
    result = {k: ability(base + v) for k, v in mods.items()}
    power = result["パワー"]["value"]
    result["弾道"] = 4 if power >= 78 else 3 if power >= 60 else 2 if power >= 42 else 1
    return result


def generate_pitcher_abilities(rng: random.Random, age: int, position: str, player_type: str) -> dict[str, Any]:
    veteran_keep = age >= 35 and (player_type == "技巧派" or rng.random() < 0.12)
    prime = 1 if 24 <= age <= 32 else -1 if age <= 19 or (age >= 35 and not veteran_keep) else 0
    speed = rng.randint(138, 149) + prime * 2 + (6 if player_type == "速球派" else 0) - (3 if player_type == "技巧派" else 0)
    control = 48 + rng.randint(-14, 16) + (16 if player_type == "技巧派" else 0) + (4 if position == "抑え" else 0)
    stamina = 48 + rng.randint(-14, 16) + (18 if position == "先発" or player_type == "スタミナ型" else -8 if position == "抑え" else 0)
    if age >= 35:
        speed -= rng.randint(2, 5) if not veteran_keep else rng.randint(0, 2)
        stamina -= rng.randint(4, 9) if not veteran_keep else rng.randint(0, 3)
        if player_type == "技巧派":
            control += 5
    return {"球速": f"{max(125, min(165, speed))} km/h", "コントロール": ability(control), "スタミナ": ability(stamina)}


def generate_breaking_balls(rng: random.Random, player_type: str) -> list[dict[str, Any]]:
    names = ["スライダー", "カーブ", "フォーク", "チェンジアップ", "シュート", "カットボール", "シンカー"]
    count = weighted_choice(rng, [(1, 35), (2, 45), (3, 18), (4, 2)]) + (1 if player_type == "変化球派" and rng.random() < 0.35 else 0)
    balls = rng.sample(names, min(count, len(names)))
    return [{"name": b, "level": rng.randint(1, 5) + (1 if player_type == "変化球派" and rng.random() < 0.4 else 0)} for b in balls]


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

def generate_player(role: str, category: str, master: MasterData, seed: int | None = None) -> dict[str, Any]:
    seed = seed if seed is not None else random.SystemRandom().randrange(SEED_MAX)
    rng = random.Random(seed)
    age = age_for(rng, category)
    nationality = choose_nationality(rng, category)
    if role == "投手":
        position_weights = [("先発", 40), ("中継ぎ", 52), ("抑え", 8)] if category == "架空球団用" else [("先発", 38), ("中継ぎ", 42), ("抑え", 20)]
        position = weighted_choice(rng, position_weights)
        type_weights = [("本格派", 34), ("技巧派", 18), ("速球派", 26), ("変化球派", 14), ("スタミナ型", 8)] if category == "助っ人外国人用" else TYPE_WEIGHTS[role]
    else:
        position_weights = [("捕手", 8), ("一塁手", 20), ("二塁手", 9), ("三塁手", 18), ("遊撃手", 10), ("外野手", 35)] if category == "助っ人外国人用" else [("捕手", 12), ("一塁手", 14), ("二塁手", 14), ("三塁手", 14), ("遊撃手", 16), ("外野手", 30)]
        position = weighted_choice(rng, position_weights)
        type_weights = [("バランス型", 16), ("巧打型", 16), ("長距離砲", 28), ("俊足型", 8), ("守備職人", 12), ("強肩型", 20)] if category == "助っ人外国人用" else TYPE_WEIGHTS[role]
    player_type = weighted_choice(rng, type_weights)
    abilities = generate_pitcher_abilities(rng, age, position, player_type) if role == "投手" else generate_fielder_abilities(rng, age, position, player_type, category)
    batting_throwing = generate_batting_throwing(rng, role, position)
    return {
        "seed": seed, "role": role, "category": category, "name": choose_name(rng, master.names, nationality), "age": age,
        "nationality": nationality, "birthplace": choose_birthplace(rng, master.places, nationality), "position": position, "player_type": player_type,
        "handedness": handedness_from_batting_throwing(batting_throwing),
        "batting_throwing": batting_throwing,
        "height": rng.randint(168, 196) + (3 if role == "投手" else 0), "weight": rng.randint(68, 105),
        "abilities": {**abilities, "ranked_specials": generate_ranked_specials(rng, master, role, position, player_type, abilities, age)}, "special_abilities": generate_specials(rng, master, role, player_type),
        "breaking_balls": generate_breaking_balls(rng, player_type) if role == "投手" else [],
    }


def save_players(players: list[dict[str, Any]]) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        for p in players:
            conn.execute("""INSERT INTO players (created_at, seed, role, category, name, age, nationality, birthplace, position, player_type, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, breaking_balls_json)
                          VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (p["seed"], p["role"], p["category"], p["name"], p["age"], p["nationality"], p["birthplace"], p["position"], p["player_type"], p["handedness"], p["batting_throwing"], p["height"], p["weight"], json.dumps(p["abilities"], ensure_ascii=False), json.dumps(p["special_abilities"], ensure_ascii=False), json.dumps(p["breaking_balls"], ensure_ascii=False)))
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
        return pd.read_sql_query("SELECT id, created_at, seed, role, category, name, age, nationality, birthplace, position, player_type, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, breaking_balls_json FROM players ORDER BY id DESC", conn)


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
    return "3個以上" if len(values) >= 3 else f"{len(values)}個"


def special_count_distribution(df: pd.DataFrame) -> pd.DataFrame:
    buckets = df["special_abilities"].apply(special_count_bucket)
    order = pd.DataFrame({"特殊能力数": ["0個", "1個", "2個", "3個以上"]})
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
    avg_special_count = round(df["special_abilities"].apply(len).mean(), 2)
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

    col5, col6 = st.columns(2)
    with col5:
        st.subheader("野手ポジション別人数")
        fielder_positions = df[df["role"] == "野手"]["position"].value_counts().rename_axis("ポジション").reset_index(name="人数")
        st.dataframe(fielder_positions, use_container_width=True, hide_index=True)
    with col6:
        st.subheader("投手役割別人数")
        pitcher_roles = df[df["role"] == "投手"]["position"].value_counts().rename_axis("役割").reset_index(name="人数")
        st.dataframe(pitcher_roles, use_container_width=True, hide_index=True)

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
        st.markdown("#### 能力")
        for k, v in p["abilities"].items():
            if k != "ranked_specials":
                render_ability_item(k, v)
        if p["breaking_balls"]:
            st.markdown("#### 変化球")
            st.write(" / ".join(f"{b['name']} {b['level']}" for b in p["breaking_balls"]))
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
        st.info("同じseedを使うことで、同条件の再生成に利用できるデータ構造です。")


if __name__ == "__main__":
    main()
