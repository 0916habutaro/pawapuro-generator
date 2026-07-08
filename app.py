import csv
import json
import random
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


@dataclass
class MasterData:
    names: dict[str, list[str]]
    places: dict[str, list[str]]
    abilities: list[dict[str, Any]]


def ensure_master_files() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    names_path = DATA_DIR / "names.json"
    places_path = DATA_DIR / "places.json"
    abilities_path = DATA_DIR / "special_abilities.csv"
    if not names_path.exists():
        names_path.write_text(json.dumps({
            "日本": ["佐藤 蓮", "鈴木 大和", "高橋 翔", "田中 悠真", "伊藤 蒼", "山本 隼人", "中村 匠", "小林 海斗"],
            "外国": ["ジョンソン", "ロドリゲス", "スミス", "ガルシア", "ブラウン", "ミラー", "マルティネス", "ウィルソン"]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    if not places_path.exists():
        places_path.write_text(json.dumps({
            "日本": ["北海道", "宮城", "東京", "神奈川", "愛知", "大阪", "広島", "福岡", "沖縄"],
            "外国": ["アメリカ", "ドミニカ共和国", "ベネズエラ", "キューバ", "メキシコ", "韓国", "台湾"]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    if not abilities_path.exists():
        rows = [
            ["name", "kind", "group", "power", "weight", "target_role"],
            ["チャンス〇", "blue", "chance", "normal", 18, "野手"], ["チャンス◎", "blue", "chance", "strong", 4, "野手"], ["チャンス×", "red", "chance", "red", 7, "野手"],
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
    if "target_role" not in abilities.columns:
        abilities["target_role"] = abilities["group"].apply(infer_special_target_role)
    return MasterData(
        names=json.loads((DATA_DIR / "names.json").read_text(encoding="utf-8")),
        places=json.loads((DATA_DIR / "places.json").read_text(encoding="utf-8")),
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


def role_allowed_specials(master: MasterData, role: str) -> set[str]:
    return {row["name"] for row in master.abilities if special_target_role(row) in (role, "共通")}


def inappropriate_special_count(df: pd.DataFrame, master: MasterData) -> int:
    allowed = {role: role_allowed_specials(master, role) for role in ("投手", "野手")}
    return int(df.apply(lambda row: sum(name not in allowed.get(row["role"], set()) for name in row["special_abilities"]), axis=1).sum())


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
    candidates = [row for row in master.abilities if special_target_role(row) in (role, "共通")]
    rng.shuffle(candidates)
    for row in candidates:
        if len(selected) >= count:
            break
        if row["group"] in used_groups:
            continue
        chance = int(row["weight"])
        if row["power"] == "gold": chance = 1
        if row["power"] == "red": chance += 2
        if player_type in ("長距離砲", "速球派") and row["power"] == "strong": chance += 2
        if rng.randint(1, 100) <= chance:
            selected.append(row["name"])
            used_groups.add(row["group"])
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


def generate_player(role: str, category: str, master: MasterData, seed: int | None = None) -> dict[str, Any]:
    seed = seed if seed is not None else random.SystemRandom().randrange(SEED_MAX)
    rng = random.Random(seed)
    age = age_for(rng, category)
    foreign = category == "助っ人外国人用" or (category == "架空球団用" and rng.random() < 0.08)
    nation_key = "外国" if foreign else "日本"
    nationality = weighted_choice(rng, [("日本", 92), ("アメリカ", 3), ("ドミニカ共和国", 2), ("韓国", 1), ("台湾", 1), ("キューバ", 1)]) if not foreign else weighted_choice(rng, [("アメリカ", 32), ("ドミニカ共和国", 24), ("ベネズエラ", 16), ("キューバ", 10), ("メキシコ", 8), ("韓国", 5), ("台湾", 5)])
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
        "seed": seed, "role": role, "category": category, "name": rng.choice(master.names[nation_key]), "age": age,
        "nationality": nationality, "birthplace": rng.choice(master.places[nation_key]), "position": position, "player_type": player_type,
        "handedness": handedness_from_batting_throwing(batting_throwing),
        "batting_throwing": batting_throwing,
        "height": rng.randint(168, 196) + (3 if role == "投手" else 0), "weight": rng.randint(68, 105),
        "abilities": abilities, "special_abilities": generate_specials(rng, master, role, player_type),
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
        kind_counts = pd.DataFrame({"種別": ["金特", "青特", "赤特"], "出現数": [0, 0, 0]})
        return counts, kind_counts
    counts = exploded["special_abilities"].value_counts().rename_axis("特殊能力").reset_index(name="出現回数")
    counts["種別"] = counts["特殊能力"].map(ability_kinds).map({"gold": "金特", "blue": "青特", "red": "赤特"}).fillna("不明")
    kind_counts = counts.groupby("種別", as_index=False)["出現回数"].sum().rename(columns={"出現回数": "出現数"})
    kind_counts = pd.DataFrame({"種別": ["金特", "青特", "赤特"]}).merge(kind_counts, on="種別", how="left").fillna({"出現数": 0})
    kind_counts["出現数"] = kind_counts["出現数"].astype(int)
    return counts, kind_counts


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
    st.subheader("生成品質チェック")
    metric_cols = st.columns(7)
    metric_cols[0].metric("総件数", len(df))
    metric_cols[1].metric("ユニークseed数", unique_seed_count)
    metric_cols[2].metric("seed重複数", seed_duplicate_count)
    metric_cols[3].metric("完全重複選手数", complete_duplicate_count)
    metric_cols[4].metric("不適切な特殊能力件数", invalid_special_count)
    metric_cols[5].metric("利き腕/投打 不一致件数", handedness_mismatch_count)
    metric_cols[6].metric("左投げの捕手/内野手", restricted_left_count)

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

    special_counts, kind_counts = special_ability_summary(df, master)
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("特殊能力 出現回数")
        st.dataframe(special_counts, use_container_width=True, hide_index=True)
    with col4:
        st.subheader("金特・青特・赤特 出現数")
        st.dataframe(kind_counts, use_container_width=True, hide_index=True)
        st.metric("1人あたり平均特殊能力数", avg_special_count)

    st.subheader("特殊能力数分布")
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
            render_ability_item(k, v)
        if p["breaking_balls"]:
            st.markdown("#### 変化球")
            st.write(" / ".join(f"{b['name']} {b['level']}" for b in p["breaking_balls"]))
        st.markdown("#### 特殊能力")
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
