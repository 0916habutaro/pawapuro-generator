import csv
import json
import random
import sqlite3
import time
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
            ["name", "kind", "group", "power", "weight"],
            ["チャンス〇", "blue", "chance", "normal", 18], ["チャンス◎", "blue", "chance", "strong", 4], ["チャンス×", "red", "chance", "red", 7],
            ["対左投手〇", "blue", "left", "normal", 14], ["対左投手×", "red", "left", "red", 6], ["アベレージヒッター", "blue", "hit_style", "strong", 4],
            ["パワーヒッター", "blue", "hit_style", "strong", 4], ["広角打法", "blue", "direction", "strong", 5], ["走塁〇", "blue", "run", "normal", 12],
            ["盗塁〇", "blue", "steal", "normal", 12], ["盗塁×", "red", "steal", "red", 5], ["守備職人", "blue", "field", "strong", 5],
            ["ケガしにくさ〇", "blue", "injury", "normal", 10], ["ケガしにくさ×", "red", "injury", "red", 6], ["勝負師", "gold", "chance", "gold", 1],
            ["ノビ〇", "blue", "nobi", "normal", 14], ["ノビ◎", "blue", "nobi", "strong", 3], ["ノビ×", "red", "nobi", "red", 5],
            ["キレ〇", "blue", "kire", "normal", 12], ["奪三振", "blue", "strikeout", "strong", 5], ["四球", "red", "walk", "red", 7],
            ["対ピンチ〇", "blue", "pinch", "normal", 12], ["対ピンチ×", "red", "pinch", "red", 6], ["怪物球威", "gold", "nobi", "gold", 1],
        ]
        with abilities_path.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows)


def load_master_data() -> MasterData:
    ensure_master_files()
    return MasterData(
        names=json.loads((DATA_DIR / "names.json").read_text(encoding="utf-8")),
        places=json.loads((DATA_DIR / "places.json").read_text(encoding="utf-8")),
        abilities=pd.read_csv(DATA_DIR / "special_abilities.csv").to_dict("records"),
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
    candidates = master.abilities[:]
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


def generate_fielder_abilities(rng: random.Random, age: int, position: str, player_type: str) -> dict[str, Any]:
    base = 48 + (8 if 24 <= age <= 31 else 0) - (4 if age <= 19 else 0) - (3 if age >= 35 else 0)
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
    result = {k: ability(base + v) for k, v in mods.items()}
    power = result["パワー"]["value"]
    result["弾道"] = 4 if power >= 78 else 3 if power >= 60 else 2 if power >= 42 else 1
    return result


def generate_pitcher_abilities(rng: random.Random, age: int, position: str, player_type: str) -> dict[str, Any]:
    prime = 1 if 24 <= age <= 32 else -1 if age <= 19 or age >= 36 else 0
    speed = rng.randint(138, 149) + prime * 2 + (6 if player_type == "速球派" else 0) - (3 if player_type == "技巧派" else 0)
    control = 48 + rng.randint(-14, 16) + (16 if player_type == "技巧派" else 0) + (4 if position == "抑え" else 0)
    stamina = 48 + rng.randint(-14, 16) + (18 if position == "先発" or player_type == "スタミナ型" else -8 if position == "抑え" else 0)
    return {"球速": f"{max(125, min(165, speed))} km/h", "コントロール": ability(control), "スタミナ": ability(stamina)}


def generate_breaking_balls(rng: random.Random, player_type: str) -> list[dict[str, Any]]:
    names = ["スライダー", "カーブ", "フォーク", "チェンジアップ", "シュート", "カットボール", "シンカー"]
    count = weighted_choice(rng, [(1, 35), (2, 45), (3, 18), (4, 2)]) + (1 if player_type == "変化球派" and rng.random() < 0.35 else 0)
    balls = rng.sample(names, min(count, len(names)))
    return [{"name": b, "level": rng.randint(1, 5) + (1 if player_type == "変化球派" and rng.random() < 0.4 else 0)} for b in balls]


def generate_player(role: str, category: str, master: MasterData, seed: int | None = None) -> dict[str, Any]:
    seed = seed if seed is not None else time.time_ns() % 10_000_000_000
    rng = random.Random(seed)
    age = age_for(rng, category)
    foreign = category == "助っ人外国人用" or (category == "架空球団用" and rng.random() < 0.08)
    nation_key = "外国" if foreign else "日本"
    nationality = weighted_choice(rng, [("日本", 92), ("アメリカ", 3), ("ドミニカ共和国", 2), ("韓国", 1), ("台湾", 1), ("キューバ", 1)]) if not foreign else weighted_choice(rng, [("アメリカ", 32), ("ドミニカ共和国", 24), ("ベネズエラ", 16), ("キューバ", 10), ("メキシコ", 8), ("韓国", 5), ("台湾", 5)])
    position = weighted_choice(rng, [(p, 35 if p == "先発" else 25) for p in POSITIONS[role]]) if role == "投手" else weighted_choice(rng, [("捕手", 12), ("一塁手", 14), ("二塁手", 14), ("三塁手", 14), ("遊撃手", 16), ("外野手", 30)])
    player_type = weighted_choice(rng, TYPE_WEIGHTS[role])
    abilities = generate_pitcher_abilities(rng, age, position, player_type) if role == "投手" else generate_fielder_abilities(rng, age, position, player_type)
    return {
        "seed": seed, "role": role, "category": category, "name": rng.choice(master.names[nation_key]), "age": age,
        "nationality": nationality, "birthplace": rng.choice(master.places[nation_key]), "position": position, "player_type": player_type,
        "handedness": weighted_choice(rng, [("右投", 62), ("左投", 28), ("両投", 1), ("右投/左打", 9)]),
        "batting_throwing": weighted_choice(rng, [("右投右打", 48), ("右投左打", 24), ("左投左打", 18), ("左投右打", 5), ("右投両打", 5)]),
        "height": rng.randint(168, 196) + (3 if role == "投手" else 0), "weight": rng.randint(68, 105),
        "abilities": abilities, "special_abilities": generate_specials(rng, master, role, player_type),
        "breaking_balls": generate_breaking_balls(rng, player_type) if role == "投手" else [],
    }


def save_players(players: list[dict[str, Any]]) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        for p in players:
            conn.execute("""INSERT INTO players (created_at, seed, role, category, name, age, nationality, birthplace, position, player_type, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, breaking_balls_json)
                          VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (p["seed"], p["role"], p["category"], p["name"], p["age"], p["nationality"], p["birthplace"], p["position"], p["player_type"], p["handedness"], p["batting_throwing"], p["height"], p["weight"], json.dumps(p["abilities"], ensure_ascii=False), json.dumps(p["special_abilities"], ensure_ascii=False), json.dumps(p["breaking_balls"], ensure_ascii=False)))


def load_history() -> pd.DataFrame:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query("SELECT id, created_at, seed, role, category, name, age, nationality, birthplace, position, player_type, abilities_json, special_abilities_json, breaking_balls_json FROM players ORDER BY id DESC", conn)


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
        st.header("生成条件")
        role = st.radio("投手 / 野手", ["投手", "野手"], horizontal=True)
        category = st.selectbox("カテゴリ", CATEGORIES)
        count = st.number_input("生成人数", min_value=1, max_value=30, value=3, step=1)
        generate = st.button("生成する", type="primary", use_container_width=True)
    if generate:
        players = [generate_player(role, category, master) for _ in range(int(count))]
        save_players(players)
        st.session_state["latest_players"] = players
        st.success(f"{len(players)}人の選手を生成してSQLiteに保存しました。")
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
