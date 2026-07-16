import csv
import hashlib
import json
import random
import re
import sqlite3
import math
from functools import lru_cache
from html import escape
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from generator.foreign_names import generate_foreign_profile

APP_VERSION = "1.0.0"
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = APP_DIR / "players.sqlite3"
JAPANESE_SURNAME_PATH = DATA_DIR / "japan_surname.csv"
CATEGORIES = ["架空球団用", "ドラフト候補用", "助っ人外国人用"]
GROWTH_TYPE_LABELS = {
    "very_early": "超早熟",
    "early": "早熟",
    "normal": "普通",
    "late": "晩成",
    "very_late": "超晩成",
}
VALID_GROWTH_TYPES = set(GROWTH_TYPE_LABELS)
GROWTH_TYPE_BASE_WEIGHTS = {
    "架空球団用": {"very_early": 8, "early": 20, "normal": 44, "late": 21, "very_late": 7},
    "ドラフト候補用": {"very_early": 10, "early": 23, "normal": 40, "late": 21, "very_late": 6},
    "助っ人外国人用": {"very_early": 8, "early": 26, "normal": 46, "late": 16, "very_late": 4},
}
GROWTH_TYPE_MULTIPLIERS = {
    "young_project": {"very_early": 0.65, "early": 0.80, "normal": 1.00, "late": 1.45, "very_late": 1.70},
    "young_regular": {"very_early": 1.55, "early": 1.35, "normal": 1.00, "late": 0.75, "very_late": 0.55},
    "draft_ready": {"very_early": 1.40, "early": 1.35, "normal": 1.10, "late": 0.70, "very_late": 0.45},
    "high_school_project": {"very_early": 0.75, "early": 0.85, "normal": 1.00, "late": 1.35, "very_late": 1.50},
    "college_ready": {"very_early": 1.15, "early": 1.30, "normal": 1.15, "late": 0.75, "very_late": 0.50},
    "foreign_ready": {"very_early": 1.05, "early": 1.30, "normal": 1.20, "late": 0.75, "very_late": 0.50},
}
POSITIONS = {
    "投手": ["先発", "中継ぎ", "抑え"],
    "野手": ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"],
}
JAPANESE_PREFECTURE_WEIGHTS = {
    "北海道": 32,
    "青森県": 10,
    "岩手県": 8,
    "宮城県": 12,
    "秋田県": 13,
    "山形県": 8,
    "福島県": 7,
    "茨城県": 15,
    "栃木県": 13,
    "群馬県": 16,
    "埼玉県": 31,
    "千葉県": 51,
    "東京都": 54,
    "神奈川県": 54,
    "新潟県": 12,
    "富山県": 7,
    "石川県": 18,
    "福井県": 7,
    "山梨県": 3,
    "長野県": 8,
    "岐阜県": 12,
    "静岡県": 20,
    "愛知県": 45,
    "三重県": 13,
    "滋賀県": 14,
    "京都府": 23,
    "大阪府": 76,
    "兵庫県": 55,
    "奈良県": 16,
    "和歌山県": 19,
    "鳥取県": 5,
    "島根県": 5,
    "岡山県": 17,
    "広島県": 30,
    "山口県": 4,
    "徳島県": 9,
    "香川県": 9,
    "愛媛県": 6,
    "高知県": 6,
    "福岡県": 49,
    "佐賀県": 13,
    "長崎県": 7,
    "熊本県": 17,
    "大分県": 17,
    "宮崎県": 11,
    "鹿児島県": 11,
    "沖縄県": 31,
}
JAPANESE_PREFECTURE_EXPECTED_RATES = {
    prefecture: weight / 919
    for prefecture, weight in JAPANESE_PREFECTURE_WEIGHTS.items()
}
JAPANESE_PREFECTURE_ALIASES = {
    **{prefecture: prefecture for prefecture in JAPANESE_PREFECTURE_WEIGHTS},
    **{prefecture.removesuffix("県"): prefecture for prefecture in JAPANESE_PREFECTURE_WEIGHTS if prefecture.endswith("県")},
    "東京": "東京都",
    "京都": "京都府",
    "大阪": "大阪府",
}
TYPE_WEIGHTS = {
    "投手": [("本格派", 28), ("技巧派", 24), ("速球派", 18), ("変化球派", 18), ("スタミナ型", 12)],
    "野手": [("バランス型", 24), ("巧打型", 20), ("長距離砲", 16), ("俊足型", 16), ("守備職人", 14), ("強肩型", 10)],
}
CLASSIFICATION_COLUMNS = ["player_class", "archetype", "position_style", "development_stage", "acquisition_role", "weakness_profile"]
CLASSIFICATION_LABELS = {
    "player_class": "選手格",
    "archetype": "アーキタイプ",
    "position_style": "ポジションスタイル",
    "development_stage": "完成度",
    "acquisition_role": "獲得目的",
    "weakness_profile": "弱点プロファイル",
}
PLAYER_CLASS_WEIGHTS = {
    "架空球団用": [("スター級", 3), ("一軍主力級", 20), ("一軍控え級", 22), ("二軍級", 26), ("若手素材型", 17), ("ベテラン型", 12)],
    "ドラフト候補用": [("超上位候補", 2), ("上位候補", 10), ("中位候補", 28), ("下位候補", 40), ("育成候補", 20)],
    "助っ人外国人用": [("大物実績者", 5), ("主力期待級", 40), ("レギュラー競争級", 25), ("保険・バックアップ級", 12), ("育成素材型", 10), ("再生候補", 8)],
}
ARCHETYPE_WEIGHTS = {
    "投手": [("総合", 28), ("制球", 24), ("速球", 18), ("変化球", 18), ("スタミナ", 12)],
    "野手": [("バランス", 24), ("巧打", 20), ("長打", 16), ("俊足", 16), ("守備", 14), ("強肩", 10)],
}
FOREIGN_ARCHETYPE_WEIGHTS = {
    "投手": [("総合", 34), ("制球", 18), ("速球", 26), ("変化球", 14), ("スタミナ", 8)],
    "野手": [("バランス", 16), ("巧打", 16), ("長打", 28), ("俊足", 8), ("守備", 12), ("強肩", 20)],
}
DRAFT_DEVELOPMENT_WEIGHTS = {
    "18-19": [("素材型", 75), ("標準型", 23), ("即戦力型", 2)],
    "20-21": [("素材型", 50), ("標準型", 42), ("即戦力型", 8)],
    "22-23": [("素材型", 20), ("標準型", 50), ("即戦力型", 30)],
}
LEGACY_PLAYER_TYPE_BY_ARCHETYPE = {
    "野手": {"巧打": "巧打型", "長打": "長距離砲", "俊足": "俊足型", "守備": "守備職人", "強肩": "強肩型", "バランス": "バランス型"},
    "投手": {"総合": "本格派", "制球": "技巧派", "速球": "速球派", "変化球": "変化球派", "スタミナ": "スタミナ型"},
}
LEGACY_ROSTER_TIER_BY_PLAYER_CLASS = {
    "スター級": "一軍級",
    "一軍主力級": "一軍級",
    "一軍控え級": "控え級",
    "二軍級": "二軍級",
    "若手素材型": "若手",
    "ベテラン型": "ベテラン",
}
FIELDER_POSITION_STYLE_WEIGHTS = {
    "捕手": {
        "守備": [("守備型捕手", 80), ("平均型捕手", 20)],
        "強肩": [("守備型捕手", 70), ("平均型捕手", 30)],
        "長打": [("打撃型捕手", 75), ("平均型捕手", 25)],
        "巧打": [("打撃型捕手", 60), ("平均型捕手", 40)],
        "俊足": [("平均型捕手", 100)],
        "バランス": [("平均型捕手", 70), ("守備型捕手", 20), ("打撃型捕手", 10)],
    },
    "一塁手": {
        "長打": [("強打一塁手", 85), ("平均型一塁手", 15)],
        "守備": [("守備型一塁手", 80), ("平均型一塁手", 20)],
        "巧打": [("平均型一塁手", 70), ("強打一塁手", 20), ("守備型一塁手", 10)],
        "俊足": [("平均型一塁手", 100)],
        "強肩": [("平均型一塁手", 70), ("守備型一塁手", 30)],
        "バランス": [("平均型一塁手", 70), ("強打一塁手", 15), ("守備型一塁手", 15)],
    },
    "二塁手": {
        "俊足": [("守備走塁二塁手", 80), ("平均型二塁手", 20)],
        "守備": [("守備走塁二塁手", 80), ("平均型二塁手", 20)],
        "巧打": [("打撃型二塁手", 60), ("平均型二塁手", 40)],
        "長打": [("打撃型二塁手", 50), ("平均型二塁手", 50)],
        "強肩": [("守備走塁二塁手", 50), ("平均型二塁手", 50)],
        "バランス": [("平均型二塁手", 60), ("守備走塁二塁手", 25), ("打撃型二塁手", 15)],
    },
    "三塁手": {
        "長打": [("強打三塁手", 80), ("平均型三塁手", 20)],
        "強肩": [("強打三塁手", 45), ("守備型三塁手", 35), ("平均型三塁手", 20)],
        "守備": [("守備型三塁手", 75), ("平均型三塁手", 25)],
        "巧打": [("平均型三塁手", 70), ("強打三塁手", 20), ("守備型三塁手", 10)],
        "俊足": [("平均型三塁手", 100)],
        "バランス": [("平均型三塁手", 60), ("強打三塁手", 20), ("守備型三塁手", 20)],
    },
    "遊撃手": {
        "守備": [("守備走塁遊撃手", 80), ("平均型遊撃手", 20)],
        "俊足": [("守備走塁遊撃手", 75), ("平均型遊撃手", 25)],
        "巧打": [("巧打遊撃手", 65), ("平均型遊撃手", 35)],
        "長打": [("強打遊撃手", 55), ("平均型遊撃手", 45)],
        "強肩": [("守備走塁遊撃手", 60), ("平均型遊撃手", 40)],
        "バランス": [("平均型遊撃手", 60), ("守備走塁遊撃手", 20), ("巧打遊撃手", 12), ("強打遊撃手", 8)],
    },
    "外野手": {
        "俊足": [("俊足外野手", 75), ("走攻守外野手", 15), ("守備外野手", 10)],
        "守備": [("守備外野手", 70), ("俊足外野手", 20), ("走攻守外野手", 10)],
        "長打": [("強打外野手", 80), ("走攻守外野手", 10), ("守備外野手", 10)],
        "強肩": [("守備外野手", 60), ("走攻守外野手", 25), ("強打外野手", 15)],
        "巧打": [("走攻守外野手", 35), ("俊足外野手", 30), ("強打外野手", 20), ("守備外野手", 15)],
        "バランス": [("走攻守外野手", 45), ("俊足外野手", 20), ("強打外野手", 20), ("守備外野手", 15)],
    },
}
PITCHER_POSITION_STYLE_BY_ROLE = {
    "先発": {"総合": "総合型先発", "制球": "制球型先発", "速球": "速球型先発", "変化球": "変化球型先発", "スタミナ": "スタミナ型先発"},
    "中継ぎ": {"総合": "総合型中継ぎ", "制球": "制球型中継ぎ", "速球": "剛腕中継ぎ", "変化球": "変化球型中継ぎ", "スタミナ": "ロングリリーフ型"},
    "抑え": {"総合": "総合型クローザー", "制球": "制球型クローザー", "速球": "剛腕クローザー", "変化球": "変化球型クローザー", "スタミナ": "総合型クローザー"},
}
FIELDER_ACQUISITION_ROLES_BY_POSITION = {
    "捕手": ["中軸候補", "保険要員"],
    "一塁手": ["主砲候補", "中軸候補", "保険要員"],
    "二塁手": ["中軸候補", "内野守備補強", "ユーティリティ", "保険要員"],
    "三塁手": ["主砲候補", "中軸候補", "内野守備補強", "保険要員"],
    "遊撃手": ["内野守備補強", "ユーティリティ", "保険要員"],
    "外野手": ["主砲候補", "中軸候補", "外野補強", "ユーティリティ", "若手育成", "保険要員"],
}
PITCHER_ACQUISITION_ROLE_WEIGHTS = {
    "先発候補": 24,
    "勝ちパターン候補": 22,
    "クローザー候補": 14,
    "ロングリリーフ": 16,
    "左腕補強": 10,
    "若手育成": 8,
    "再生候補": 6,
}
FIELDER_WEAKNESS_PROFILES = ["低ミート", "低走力", "低守備", "低捕球", "送球不安", "明確な弱点なし"]
PITCHER_WEAKNESS_PROFILES = ["低制球", "球種不足", "スタミナ不足", "球速不足", "変化量不足", "安定性不安", "明確な弱点なし"]
RANK_COLORS = {"S": "#ff5da2", "A": "#ff5a5a", "B": "#ff9f43", "C": "#ffd166", "D": "#6ee7b7", "E": "#60a5fa", "F": "#a78bfa", "G": "#cbd5e1"}
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
PITCH_GAUGE_GEOMETRY = {
    "1": {"origin": (169, 66), "angle": 0, "paired_lane_offset": (0, 9)},
    "2": {"origin": (158, 83), "angle": 45, "paired_lane_offset": (6.364, -6.364)},
    "3": {"origin": (140, 89), "angle": 90, "paired_lane_offset": (9, 0)},
    "4": {"origin": (122, 83), "angle": 135, "paired_lane_offset": (-6.364, -6.364)},
    "5": {"origin": (111, 66), "angle": 180, "paired_lane_offset": (0, 9)},
}
PITCH_CHART_LABEL_GEOMETRY = {
    "1": ((255, 96, "end"), (255, 116, "end")),
    "2": ((242, 160, "end"), (242, 180, "end")),
    "3": ((134, 200, "end"), (146, 200, "start")),
    "4": ((38, 160, "start"), (38, 180, "start")),
    "5": ((25, 96, "start"), (25, 116, "start")),
}
PITCH_GAUGE_SEGMENT_LENGTH = 12
PITCH_GAUGE_SEGMENT_THICKNESS = 9
PITCH_GAUGE_SEGMENT_GAP = 1
PITCH_GAUGE_STEP = PITCH_GAUGE_SEGMENT_LENGTH + PITCH_GAUGE_SEGMENT_GAP
PITCH_GAUGE_SEGMENT_COUNT = 7
PITCH_GAUGE_INACTIVE = ("#35b5ef", "#128bc7", "#87d8fa")
PITCH_GAUGE_ACTIVE = ("#ff8b25", "#dd5f12", "#ffd06a")
PAIRED_SEGMENT_WIDTH = 10
PAIRED_SEGMENT_HEIGHT = 7
PAIRED_SEGMENT_GAP = 1
PAIRED_STEP = PAIRED_SEGMENT_WIDTH + PAIRED_SEGMENT_GAP
PAIRED_SEGMENT_COUNT = 7
PAIRED_LANE_GAP = 2
PAIRED_ARROW_POINTS = "-5,-3.5 1.5,-3.5 6,0 1.5,3.5 -5,3.5"
PITCH_DISPLAY_NAMES = {
    "ツーシームファスト": "ツーシーム",
    "ムービングファスト": "ムービング",
    "超スローボール": "超スロー",
    "シンキングツーシーム": "Sツーシーム",
    "シンキングファスト": "Sファスト",
    "ドロップカーブ": "Dカーブ",
    "ナックルカーブ": "Nカーブ",
    "パワーカーブ": "Pカーブ",
    "サークルチェンジ": "Cチェンジ",
    "シンキングスプリット": "Sスプリット",
    "ファストチェンジ": "Fチェンジ",
}
TAB_LABELS = ["投手能力", "野手能力", "守備・起用", "プロフィール"]
TAB_COLORS = {"投手能力": "#d7193f", "野手能力": "#0876c9", "守備・起用": "#d49a00", "プロフィール": "#087d23"}
NAMEPLATE_COLOR_STYLES = {
    "starter": {"top": "#ff8a7c", "bottom": "#ff6d61", "border": "#e23d35"},
    "relief": {"top": "#ffa3cf", "bottom": "#f97fb7", "border": "#df3f86"},
    "catcher": {"top": "#62f5ff", "bottom": "#1fd0dd", "border": "#13a9c6"},
    "infield": {"top": "#ffe84a", "bottom": "#ffc31e", "border": "#eea30b"},
    "outfield": {"top": "#76f36d", "bottom": "#4bdc55", "border": "#20a93b"},
}
POSITION_COLOR_GROUPS = {
    "捕手": "catcher",
    "一塁手": "infield",
    "二塁手": "infield",
    "三塁手": "infield",
    "遊撃手": "infield",
    "外野手": "outfield",
}
NAMEPLATE_GROUP_PRIORITY = {"catcher": 0, "infield": 1, "outfield": 2}


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
                actual_nationality TEXT NOT NULL DEFAULT '',
                nationality_code TEXT NOT NULL DEFAULT '',
                name_group_id INTEGER NOT NULL DEFAULT 0,
                name_group_name TEXT NOT NULL DEFAULT '',
                skin_color INTEGER NOT NULL DEFAULT 0,
                birthplace TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL DEFAULT '',
                player_type TEXT NOT NULL DEFAULT '',
                player_class TEXT NOT NULL DEFAULT '',
                growth_type TEXT NOT NULL DEFAULT 'normal',
                archetype TEXT NOT NULL DEFAULT '',
                position_style TEXT NOT NULL DEFAULT '',
                development_stage TEXT NOT NULL DEFAULT '',
                acquisition_role TEXT NOT NULL DEFAULT '',
                weakness_profile TEXT NOT NULL DEFAULT '',
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
            "actual_nationality": "TEXT NOT NULL DEFAULT ''",
            "nationality_code": "TEXT NOT NULL DEFAULT ''",
            "name_group_id": "INTEGER NOT NULL DEFAULT 0",
            "name_group_name": "TEXT NOT NULL DEFAULT ''",
            "skin_color": "INTEGER NOT NULL DEFAULT 0",
            "birthplace": "TEXT NOT NULL DEFAULT ''",
            "region": "TEXT NOT NULL DEFAULT ''",
            "position": "TEXT NOT NULL DEFAULT ''",
            "player_type": "TEXT NOT NULL DEFAULT ''",
            "player_class": "TEXT NOT NULL DEFAULT ''",
            "growth_type": "TEXT NOT NULL DEFAULT 'normal'",
            "archetype": "TEXT NOT NULL DEFAULT ''",
            "position_style": "TEXT NOT NULL DEFAULT ''",
            "development_stage": "TEXT NOT NULL DEFAULT ''",
            "acquisition_role": "TEXT NOT NULL DEFAULT ''",
            "weakness_profile": "TEXT NOT NULL DEFAULT ''",
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
            "birth_month": "INTEGER NOT NULL DEFAULT 0",
            "birth_day": "INTEGER NOT NULL DEFAULT 0",
            "pitching_form_type": "TEXT NOT NULL DEFAULT ''",
            "pitching_form_number": "INTEGER NOT NULL DEFAULT 0",
            "pitching_form_is_generic": "INTEGER NOT NULL DEFAULT 1",
            "batting_form_type": "TEXT NOT NULL DEFAULT ''",
            "batting_form_number": "INTEGER NOT NULL DEFAULT 0",
            "batting_form_is_generic": "INTEGER NOT NULL DEFAULT 1",
            "bat_color": "TEXT NOT NULL DEFAULT ''",
            "glove_color": "TEXT NOT NULL DEFAULT ''",
            "wristband_left_enabled": "INTEGER NOT NULL DEFAULT 0",
            "wristband_left_color": "TEXT NOT NULL DEFAULT ''",
            "wristband_right_enabled": "INTEGER NOT NULL DEFAULT 0",
            "wristband_right_color": "TEXT NOT NULL DEFAULT ''",
            "draft_source_type": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE players ADD COLUMN {column} {definition}")
        conn.execute("UPDATE players SET region = birthplace WHERE (region IS NULL OR region = '') AND birthplace IS NOT NULL")
        conn.execute("UPDATE players SET growth_type = 'normal' WHERE growth_type IS NULL OR growth_type = ''")


def weighted_choice(rng: random.Random, items: list[tuple[Any, int]]) -> Any:
    return rng.choices([i[0] for i in items], weights=[i[1] for i in items], k=1)[0]


def positive_weight_items(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return [(label, int(weight)) for label, weight in items if int(weight) > 0]

def scaled_weight_items(items: list[tuple[Any, float]]) -> list[tuple[Any, int]]:
    return [(label, max(1, int(round(float(weight) * 10)))) for label, weight in items if float(weight) > 0]

DRAFT_SOURCE_WEIGHTS = [("高校生", 35), ("大学生", 40), ("社会人", 15), ("独立・クラブ", 8), ("その他", 2)]
DRAFT_SOURCE_AGE_WEIGHTS = {
    "高校生": [(17, 3), (18, 89), (19, 8)],
    "大学生": [(21, 25), (22, 68), (23, 7)],
    "社会人": scaled_weight_items([(22, 8), (23, 37), (24, 27), (25, 15), (26, 8), (27, 3), (28, 1.5), (29, 0.5)]),
    "独立・クラブ": scaled_weight_items([(19, 7.5), (20, 7.5), (21, 15), (22, 15), (23, 16), (24, 16), (25, 7.5), (26, 7.5), (27, 2), (28, 2), (29, 2), (30, 2)]),
    "その他": [(19, 3), (20, 8), (21, 16), (22, 28), (23, 24), (24, 13), (25, 6), (26, 2)],
}
PITCHING_FORM_RANGES = {"オーバースロー": (195, 34), "スリークォーター": (180, 39), "サイドスロー": (106, 66), "アンダースロー": (40, 33)}
BATTING_FORM_RANGES = {"スタンダード": (210, 25), "オープン": (141, 24), "クラウチング": (12, 8)}
PITCHING_FORM_TYPE_WEIGHTS = [("オーバースロー", 55), ("スリークォーター", 34), ("サイドスロー", 9), ("アンダースロー", 2)]
BATTING_FORM_TYPE_WEIGHTS = [("スタンダード", 72), ("オープン", 25), ("クラウチング", 3)]
PITCHER_BATTING_FORM_TYPE_WEIGHTS = [("スタンダード", 94), ("オープン", 5), ("クラウチング", 1)]
PITCHING_FORM_GENERIC_RATE = {"架空球団用": 0.92, "ドラフト候補用": 0.97, "助っ人外国人用": 0.85}
BATTING_FORM_GENERIC_RATE = {"架空球団用": 0.90, "ドラフト候補用": 0.96, "助っ人外国人用": 0.80}
BAT_COLOR_WEIGHTS = [("木", 32), ("黒", 25), ("黒/木", 17), ("木/黒", 8), ("茶", 7), ("黒/茶", 4), ("黒/赤", 3), ("赤", 2), ("黄/木", 2)]
GLOVE_COLOR_WEIGHTS = scaled_weight_items([("オレンジ", 24), ("黒", 20), ("革", 17), ("茶", 14), ("ブロンド", 9), ("赤", 5), ("青", 4), ("黄", 3), ("緑", 1.5), ("水色", 1.5), ("シルバー", 1)])
WRISTBAND_PATTERN_WEIGHTS = [("none", 50), ("left_only", 15), ("right_only", 10), ("both_same", 20), ("both_different", 5)]
PITCHER_WRISTBAND_PATTERN_WEIGHTS = [("none", 72), ("left_only", 8), ("right_only", 6), ("both_same", 12), ("both_different", 2)]
WRISTBAND_COLOR_WEIGHTS = scaled_weight_items([("黒", 35), ("白", 22), ("赤", 10), ("青", 9), ("グレー", 7), ("オレンジ", 5), ("黄", 4), ("緑", 3), ("水色", 2), ("ピンク", 1.5), ("紫", 1.5)])



def normalize_growth_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in VALID_GROWTH_TYPES else "normal"


def growth_type_label(value: Any) -> str:
    return GROWTH_TYPE_LABELS[normalize_growth_type(value)]


def create_growth_rng(seed: int, role: str, category: str) -> random.Random:
    digest = hashlib.sha256(f"{int(seed)}:growth_type:{role}:{category}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def growth_type_weight_map(category: str, age: int, player_class: str | None = None, development_stage: str | None = None, acquisition_role: str | None = None) -> dict[str, int]:
    weights = dict(GROWTH_TYPE_BASE_WEIGHTS.get(category, GROWTH_TYPE_BASE_WEIGHTS["架空球団用"]))
    multipliers = {key: 1.0 for key in GROWTH_TYPE_LABELS}

    def apply(name: str) -> None:
        for key, value in GROWTH_TYPE_MULTIPLIERS[name].items():
            multipliers[key] *= value

    labels = {str(player_class or ""), str(development_stage or ""), str(acquisition_role or "")}
    if labels & {"若手素材型", "育成候補", "育成素材型", "素材型", "若手育成"}:
        apply("young_project")
    if age <= 26 and (player_class in {"スター級", "一軍主力級", "超上位候補", "上位候補", "主力期待級"} or development_stage == "即戦力型"):
        apply("young_regular")
    if category == "ドラフト候補用" and (development_stage == "即戦力型" or str(acquisition_role or "").endswith("即戦力")):
        apply("draft_ready")
    if category == "ドラフト候補用" and age <= 19 and development_stage == "素材型":
        apply("high_school_project")
    if category == "ドラフト候補用" and 22 <= age <= 25 and development_stage == "即戦力型":
        apply("college_ready")
    if category == "助っ人外国人用" and player_class in {"大物実績者", "主力期待級", "レギュラー競争級"}:
        apply("foreign_ready")
    return {key: max(1, round(weights[key] * max(0.25, min(multipliers[key], 3.0)))) for key in GROWTH_TYPE_LABELS}


def choose_growth_type(*, category: str, age: int, player_class: str | None, development_stage: str | None, acquisition_role: str | None, rng: random.Random) -> str:
    weights = growth_type_weight_map(category, age, player_class, development_stage, acquisition_role)
    return weighted_choice(rng, list(weights.items()))


def choose_player_class(rng: random.Random, category: str, age: int) -> str:
    items = list(PLAYER_CLASS_WEIGHTS.get(category, []))
    adjusted: list[tuple[str, int]] = []
    for label, weight in items:
        if category == "架空球団用":
            if 18 <= age <= 22 and label == "ベテラン型":
                continue
            if 30 <= age and label == "若手素材型":
                continue
            if 18 <= age <= 19 and label == "スター級":
                weight = max(1, round(weight * 0.25))
            if age >= 35 and label == "ベテラン型":
                weight *= 3
        elif category == "助っ人外国人用":
            if age <= 23 and label in {"大物実績者", "再生候補"}:
                continue
            if age >= 26 and label == "育成素材型":
                continue
            if age >= 32 and label in {"大物実績者", "再生候補"}:
                weight *= 2
            if age >= 32 and label == "主力期待級":
                weight = max(1, round(weight * 0.5))
        adjusted.append((label, weight))
    return weighted_choice(rng, positive_weight_items(adjusted))


def choose_development_stage(rng: random.Random, category: str, age: int, player_class: str, draft_source_type: str = "") -> str:
    if category != "ドラフト候補用":
        return ""
    if draft_source_type == "高校生":
        items = [("素材型", 78), ("標準型", 20), ("即戦力型", 2)]
    elif draft_source_type == "大学生":
        items = [("素材型", 18), ("標準型", 58), ("即戦力型", 24)]
    elif draft_source_type == "社会人":
        items = [("素材型", 5), ("標準型", 50), ("即戦力型", 45)]
    elif draft_source_type == "独立・クラブ":
        items = [("素材型", 24), ("標準型", 56), ("即戦力型", 20)]
    elif draft_source_type == "その他":
        items = [("素材型", 30), ("標準型", 45), ("即戦力型", 25)]
    elif age <= 19:
        items = list(DRAFT_DEVELOPMENT_WEIGHTS["18-19"])
    elif age <= 21:
        items = list(DRAFT_DEVELOPMENT_WEIGHTS["20-21"])
    else:
        items = list(DRAFT_DEVELOPMENT_WEIGHTS["22-23"])
    if player_class == "育成候補":
        items = [(label, weight) for label, weight in items if label != "即戦力型"]
    return weighted_choice(rng, positive_weight_items(items))


def choose_archetype(rng: random.Random, role: str, category: str) -> str:
    weights = FOREIGN_ARCHETYPE_WEIGHTS[role] if category == "助っ人外国人用" else ARCHETYPE_WEIGHTS[role]
    return weighted_choice(rng, weights)


def pitcher_acquisition_candidates(aptitudes: dict[str, str], batting_throwing: str) -> list[str]:
    starter = aptitudes.get("starter_aptitude", "-")
    reliever = aptitudes.get("reliever_aptitude", "-")
    closer = aptitudes.get("closer_aptitude", "-")
    candidates: set[str] = set()
    if starter == "◎":
        candidates.update({"先発候補", "ロングリリーフ", "若手育成", "再生候補"})
    if reliever == "◎" and closer == "-":
        candidates.update({"勝ちパターン候補", "ロングリリーフ", "若手育成", "再生候補"})
    if closer == "◎":
        candidates.update({"クローザー候補", "勝ちパターン候補", "再生候補"})
    if batting_throwing.startswith("左投"):
        candidates.add("左腕補強")
    if not candidates:
        candidates.update({"勝ちパターン候補", "ロングリリーフ", "再生候補"})
    return sorted(candidates, key=list(PITCHER_ACQUISITION_ROLE_WEIGHTS).index)


def choose_acquisition_role(rng: random.Random, category: str, role: str, player_class: str, position: str, aptitudes: dict[str, str] | None = None, batting_throwing: str = "") -> str:
    if category != "助っ人外国人用":
        return ""
    if role == "野手":
        candidates = list(FIELDER_ACQUISITION_ROLES_BY_POSITION.get(position, ["保険要員"]))
        if player_class == "育成素材型" and "若手育成" not in candidates:
            candidates.append("若手育成")
        items = [(label, 20) for label in candidates]
        if player_class == "保険・バックアップ級":
            items = [(label, weight * 2 if label == "保険要員" else weight) for label, weight in items]
        return weighted_choice(rng, positive_weight_items(items))
    candidates = pitcher_acquisition_candidates(aptitudes or {}, batting_throwing)
    if player_class == "育成素材型" and "若手育成" not in candidates:
        candidates.append("若手育成")
    items = [(label, PITCHER_ACQUISITION_ROLE_WEIGHTS.get(label, 10)) for label in candidates]
    if player_class == "再生候補":
        items = [(label, weight * 2 if label == "再生候補" else weight) for label, weight in items]
    return weighted_choice(rng, positive_weight_items(items))


def choose_position_style(rng: random.Random, role: str, position: str, archetype: str) -> str:
    if role == "投手":
        return PITCHER_POSITION_STYLE_BY_ROLE.get(position, {}).get(archetype, "")
    weights = FIELDER_POSITION_STYLE_WEIGHTS.get(position, {}).get(archetype)
    return weighted_choice(rng, weights) if weights else ""


def choose_weakness_profile(rng: random.Random, category: str, role: str, player_class: str) -> str:
    if category != "助っ人外国人用":
        return ""
    profiles = PITCHER_WEAKNESS_PROFILES if role == "投手" else FIELDER_WEAKNESS_PROFILES
    if player_class == "大物実績者":
        items = [(label, 40 if label == "明確な弱点なし" else 10) for label in profiles]
    elif player_class == "主力期待級":
        items = [(label, 20 if label == "明確な弱点なし" else 16) for label in profiles]
    else:
        items = [(label, 5 if label == "明確な弱点なし" else 19) for label in profiles]
    if player_class in {"育成素材型", "再生候補"}:
        items = [(label, weight) for label, weight in items if label != "明確な弱点なし"]
    return weighted_choice(rng, positive_weight_items(items))


def legacy_player_type_from_archetype(role: str, archetype: str) -> str:
    return LEGACY_PLAYER_TYPE_BY_ARCHETYPE.get(role, {}).get(archetype, "")


def legacy_roster_tier_from_player_class(player_class: str) -> str:
    return LEGACY_ROSTER_TIER_BY_PLAYER_CLASS.get(player_class, "")


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


def special_constraint_violations(player: dict[str, Any] | pd.Series) -> list[dict[str, str]]:
    get = player.get
    role = str(get("role", ""))
    position = str(get("position", ""))
    abilities = get("abilities", {}) or {}
    sub_positions = get("sub_positions", get("サブポジ", []))
    pitcher_aptitudes = {key: get(key) for key in PITCHER_APTITUDE_KEYS}
    if isinstance(abilities, dict):
        for key in PITCHER_APTITUDE_KEYS:
            pitcher_aptitudes[key] = pitcher_aptitudes.get(key) or abilities.get(key)
    normal = list(get("special_abilities", []) or [])
    ranked = get("ranked_specials", None)
    if ranked is None and isinstance(abilities, dict):
        ranked = abilities.get("ranked_specials", {})
    ranked_names = list((ranked or {}).values()) if isinstance(ranked, dict) else []
    rows: list[dict[str, str]] = []
    for name in [*normal, *ranked_names]:
        special_name = str(name)
        reason = ""
        if role == "野手" and special_name in POSITION_RESTRICTED_SPECIALS and not has_position_aptitude(position, sub_positions, POSITION_RESTRICTED_SPECIALS[special_name]):
            reason = f"{','.join(sorted(POSITION_RESTRICTED_SPECIALS[special_name]))}適性なし"
        elif role == "野手" and special_name.startswith("キャッチャー") and not has_position_aptitude(position, sub_positions, {"捕手"}):
            reason = "捕手適性なし"
        elif role == "投手" and special_name in RELIEF_REQUIRED_SPECIALS and not has_pitcher_aptitude(pitcher_aptitudes, {"reliever_aptitude", "closer_aptitude"}):
            reason = "救援適性なし"
        if reason:
            rows.append({"special": special_name, "reason": reason})
    return rows

def inappropriate_special_count(df: pd.DataFrame, master: MasterData) -> int:
    allowed = {role: role_allowed_specials(master, role) for role in ("投手", "野手")}
    normal_invalid = df.apply(lambda row: sum(name not in allowed.get(row["role"], set()) for name in row["special_abilities"]), axis=1).sum()
    ranked_invalid = df.apply(lambda row: sum(name not in allowed.get(row["role"], set()) for name in (row.get("ranked_specials") or {}).values()), axis=1).sum() if "ranked_specials" in df.columns else 0
    constraint_invalid = df.apply(lambda row: len(special_constraint_violations(row)), axis=1).sum()
    return int(normal_invalid + ranked_invalid + constraint_invalid)


def rank(value: int) -> str:
    if value >= 90: return "S"
    if value >= 80: return "A"
    if value >= 70: return "B"
    if value >= 60: return "C"
    if value >= 50: return "D"
    if value >= 40: return "E"
    if value >= 20: return "F"
    return "G"


def ability(value: int) -> dict[str, Any]:
    value = max(0, min(100, value))
    return {"value": value, "rank": rank(value)}


FIELDER_ABILITY_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
TECHNICAL_FIELDER_KEYS = {"ミート", "守備力", "捕球"}
PHYSICAL_FIELDER_KEYS = {"パワー", "走力", "肩力"}
FIELDER_STYLE_DEFAULTS = {
    "捕手": "平均型捕手",
    "一塁手": "平均型一塁手",
    "二塁手": "平均型二塁手",
    "三塁手": "平均型三塁手",
    "遊撃手": "平均型遊撃手",
    "外野手": "走攻守外野手",
}
FOREIGN_FIELDER_POSITION_WEIGHTS = [("捕手", 1), ("一塁手", 25), ("二塁手", 5), ("三塁手", 20), ("遊撃手", 3), ("外野手", 46)]
FOREIGN_ALLROUNDER_STYLES = {"走攻守外野手", "平均型一塁手", "平均型三塁手", "平均型二塁手"}
FOREIGN_ALLROUNDER_FINAL_CHANCE = 1.00
CAP_RANGES = {
    89: (80, 89),
    79: (65, 79),
    78: (65, 78),
    74: (58, 74),
    69: (58, 69),
    64: (50, 64),
    59: (50, 59),
    54: (45, 54),
}
MIN_RANGES = {
    36: (36, 41),
    38: (38, 43),
    40: (40, 45),
    42: (42, 47),
    45: (45, 50),
    48: (48, 53),
    50: (50, 55),
    52: (52, 57),
    55: (55, 60),
    58: (58, 63),
}
FOREIGN_PLAYER_CLASS_AGE_WEIGHTS = {
    "大物実績者": [(27, 5), (28, 8), (29, 14), (30, 17), (31, 18), (32, 17), (33, 13), (34, 6), (35, 2)],
    "主力期待級": [(24, 4), (25, 8), (26, 14), (27, 16), (28, 17), (29, 16), (30, 13), (31, 8), (32, 3), (33, 1)],
    "レギュラー競争級": [(23, 4), (24, 8), (25, 14), (26, 16), (27, 16), (28, 14), (29, 12), (30, 8), (31, 5), (32, 3)],
    "保険・バックアップ級": [(25, 3), (26, 5), (27, 8), (28, 13), (29, 15), (30, 16), (31, 15), (32, 12), (33, 8), (34, 4), (35, 1)],
    "育成素材型": [(19, 5), (20, 10), (21, 20), (22, 24), (23, 22), (24, 14), (25, 5)],
    "再生候補": [(28, 3), (29, 6), (30, 12), (31, 16), (32, 18), (33, 17), (34, 13), (35, 9), (36, 6)],
}


def clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def reroll_under_cap(rng: random.Random, cap: int) -> int:
    low, high = CAP_RANGES.get(cap, (max(0, cap - 14), cap))
    return rng.randint(low, high)


def reroll_over_minimum(rng: random.Random, minimum: int) -> int:
    default_high = min(100, minimum + 5) if minimum <= 100 else minimum + 5
    low, high = MIN_RANGES.get(minimum, (minimum, default_high))
    return rng.randint(low, high)


def cap_value(rng: random.Random, value: int, cap: int) -> int:
    return value if value <= cap else reroll_under_cap(rng, cap)


def floor_value(rng: random.Random, value: int, minimum: int) -> int:
    return value if value >= minimum else reroll_over_minimum(rng, minimum)


def add_mod(values: dict[str, int], mods: dict[str, int]) -> None:
    for key, delta in mods.items():
        if key in values:
            values[key] += delta


def ability_values(values: dict[str, int]) -> dict[str, Any]:
    return {key: ability(value) for key, value in values.items()}


def legacy_archetype_from_player_type(role: str, player_type: str) -> str:
    mapping = LEGACY_PLAYER_TYPE_BY_ARCHETYPE.get(role, {})
    return next((archetype for archetype, legacy in mapping.items() if legacy == player_type), "")


def player_class_from_legacy_roster_tier(roster_tier: str) -> str:
    mapping = {
        "一軍級": "一軍主力級",
        "控え級": "一軍控え級",
        "二軍級": "二軍級",
        "若手": "若手素材型",
        "ベテラン": "ベテラン型",
    }
    return mapping.get(roster_tier, "")


def curve_delta(age: int, points: list[tuple[int, int]]) -> int:
    if age <= points[0][0]:
        return points[0][1]
    for (left_age, left_value), (right_age, right_value) in zip(points, points[1:], strict=False):
        if left_age <= age <= right_age:
            span = max(1, right_age - left_age)
            return round(left_value + (right_value - left_value) * ((age - left_age) / span))
    return points[-1][1]


def choose_foreign_age_for_class(rng: random.Random, player_class: str) -> int:
    return weighted_choice(rng, FOREIGN_PLAYER_CLASS_AGE_WEIGHTS.get(player_class, FOREIGN_PLAYER_CLASS_AGE_WEIGHTS["主力期待級"]))


def choose_draft_source_type(rng: random.Random) -> str:
    return weighted_choice(rng, DRAFT_SOURCE_WEIGHTS)


def age_for(rng: random.Random, category: str, draft_source_type: str = "") -> int:
    if category == "ドラフト候補用":
        source = draft_source_type or choose_draft_source_type(rng)
        return weighted_choice(rng, DRAFT_SOURCE_AGE_WEIGHTS[source])
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
PITCHER_REALISTIC_SPECIAL_BOOSTS = {
    "球速安定": 1.35, "リリース○": 3.25, "奪三振": 3.35, "四球": 3.05, "抜け球": 2.60,
    "球持ち○": 1.75, "逃げ球": 1.55, "内角攻め": 2.55, "キレ○": 2.65, "荒れ球": 1.90,
    "スロースターター": 1.55, "緩急○": 2.45, "低め○": 1.75, "クロスファイヤー": 1.55, "対強打者○": 1.55,
    "一発": 1.25, "ゴロピッチャー": 1.65, "フライボールピッチャー": 1.70,
}
PITCHER_REALISTIC_SPECIAL_SUPPRESSIONS = {
    "勝ち運": 0.45, "ストライク先行": 0.70, "乱調": 0.75, "尻上がり": 0.75, "寸前": 0.80, "要所○": 0.70,
}
FIELDER_REALISTIC_SPECIAL_BOOSTS = {
    "三振": 3.25, "サヨナラ男": 1.85, "内野安打○": 0.82, "固め打ち": 1.85,
    "満塁男": 1.85, "流し打ち": 1.95, "決勝打": 2.05, "バント○": 1.20,
    "死球集中": 1.05, "併殺": 0.82, "広角打法": 1.80, "ヘッドスライディング": 1.85,
    "カット打ち": 1.85, "レーザービーム": 1.70, "アベレージヒッター": 1.55, "パワーヒッター": 1.50, "守備職人": 1.40,
}
FIELDER_REALISTIC_SPECIAL_SUPPRESSIONS = {
    "代打○": 0.50, "プレッシャーラン": 0.65, "高速チャージ": 0.70, "ダメ押し": 0.70,
    "チャンスメーカー": 0.70, "対変化球○": 0.70, "いぶし銀": 0.70, "ローボールヒッター": 0.65,
    "かく乱": 0.70, "国際大会×": 0.18, "窮地○": 0.70, "ささやき破り": 0.65,
    "リベンジ": 0.70, "帳尻合わせ": 0.70,
}


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


def classification_special_scale(category: str | None, player_class: str | None, archetype: str | None, position_style: str | None, development_stage: str | None, acquisition_role: str | None, weakness_profile: str | None, kind: str, power: str, name: str) -> float:
    scale = 1.0
    if player_class in {"スター級", "大物実績者"}: scale *= 1.18 if kind == "blue" else 0.82 if kind == "red" else 1.04
    elif player_class in {"一軍主力級", "主力期待級", "超上位候補", "上位候補"}: scale *= 1.08 if kind == "blue" else 0.94
    elif player_class in {"二軍級", "育成候補", "育成素材型"}: scale *= 0.70 if kind == "blue" else 1.20 if kind == "red" else 1.04
    elif player_class in {"一軍控え級", "レギュラー競争級", "保険・バックアップ級"}: scale *= 1.08 if kind in {"green", "red"} else 0.95
    elif player_class == "ベテラン型": scale *= 1.08 if kind in {"blue", "green"} else 1.05
    if category == "ドラフト候補用" and development_stage == "素材型" and (power == "strong" or name in STRONG_SPECIALS): scale *= 0.35
    if category == "ドラフト候補用" and development_stage == "即戦力型" and kind == "blue": scale *= 1.12
    if category == "助っ人外国人用" and acquisition_role in {"主砲候補", "中軸候補", "勝ちパターン候補", "クローザー候補"} and kind == "blue": scale *= 1.12
    if acquisition_role in {"ユーティリティ", "保険要員", "内野守備補強", "外野補強"} and kind == "green": scale *= 1.18
    if weakness_profile and weakness_profile != "明確な弱点なし":
        if kind == "red": scale *= 1.35
        weak_suppressed = {"低ミート": {"アベレージヒッター", "流し打ち", "粘り打ち"}, "低走力": {"盗塁〇", "走塁〇", "積極盗塁", "積極走塁", "内野安打○"}, "低守備": {"守備職人", "積極守備"}, "低捕球": {"守備職人"}, "送球不安": {"送球〇", "送球◎", "レーザービーム"}, "低制球": {"低め○", "ストライク先行", "逃げ球", "球持ち○"}, "球種不足": {"キレ○", "緩急○", "変化球中心"}, "スタミナ不足": {"尻上がり", "回またぎ○", "根性"}, "球速不足": {"ノビ〇", "ノビ◎", "重い球", "奪三振"}, "変化量不足": {"キレ○", "変化球中心"}}
        if name in weak_suppressed.get(weakness_profile, set()): scale *= 0.35
    if power == "gold" or kind == "gold":
        scale *= 0.18 if player_class in {"二軍級", "育成候補", "育成素材型"} else 0.55
    return max(0.05, min(1.8, scale))



POSITION_RESTRICTED_SPECIALS: dict[str, set[str]] = {
    "レーザービーム": {"外野手"},
    "高速チャージ": {"一塁手", "三塁手"},
    "フレーミング○": {"捕手"},
    "フレーミング◎": {"捕手"},
    "ホーム死守": {"捕手"},
    "ブロッキング": {"捕手"},
}
RELIEF_REQUIRED_SPECIALS: set[str] = {"火消し", "緊急登板○", "投手存在感", "回またぎ○"}
PITCHER_APTITUDE_ALLOWED = {"◎", "○"}
CATCHER_CONTEXT_SPECIALS: set[str] = {"フレーミング○", "フレーミング◎", "ホーム死守", "ブロッキング"}
STARTER_CONTEXT_SPECIALS: set[str] = {"尻上がり", "スロースターター", "立ち上がり○", "根性", "要所○", "投打躍動"}

def player_position_aptitudes(main_position: str | None, sub_positions: Any = None) -> set[str]:
    positions = {str(main_position)} if main_position else set()
    positions.update(item["position"] for item in normalize_sub_positions(sub_positions))
    positions.discard("")
    return positions

def has_position_aptitude(main_position: str | None, sub_positions: Any, target_positions: set[str]) -> bool:
    return bool(player_position_aptitudes(main_position, sub_positions) & target_positions)

def position_aptitude_level(main_position: str | None, sub_positions: Any, target_position: str) -> str:
    if main_position == target_position:
        return "main"
    best = "none"
    rank = {"◎": 3, "○": 2, "△": 1, "none": 0}
    for item in normalize_sub_positions(sub_positions):
        if item.get("position") != target_position:
            continue
        aptitude = str(item.get("aptitude") or "none")
        if rank.get(aptitude, 0) > rank[best]:
            best = aptitude
    return best

def pitcher_aptitude_value(pitcher_aptitudes: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(pitcher_aptitudes, dict):
        return None
    value = pitcher_aptitudes.get(key)
    if value is None and isinstance(pitcher_aptitudes.get("abilities"), dict):
        value = pitcher_aptitudes["abilities"].get(key)
    return str(value) if value is not None else None

def has_pitcher_aptitude(pitcher_aptitudes: dict[str, Any] | None, aptitude_keys: set[str]) -> bool:
    return any(pitcher_aptitude_value(pitcher_aptitudes, key) in PITCHER_APTITUDE_ALLOWED for key in aptitude_keys)

def pitcher_aptitude_level(pitcher_aptitudes: dict[str, Any] | None, aptitude_key: str) -> str:
    value = pitcher_aptitude_value(pitcher_aptitudes, aptitude_key)
    return value if value in PITCHER_APTITUDE_ALLOWED else "-"

def is_special_position_allowed(special_name: str, main_position: str | None, sub_positions: Any = None) -> bool:
    required = POSITION_RESTRICTED_SPECIALS.get(special_name)
    if special_name in {"レーザービーム", "高速チャージ"}:
        return True if not required else main_position in required
    return True if not required else has_position_aptitude(main_position, sub_positions, required)

def is_special_pitcher_aptitude_allowed(special_name: str, pitcher_aptitudes: dict[str, Any] | None = None) -> bool:
    if special_name not in RELIEF_REQUIRED_SPECIALS:
        return True
    return has_pitcher_aptitude(pitcher_aptitudes, {"reliever_aptitude", "closer_aptitude"})

def is_special_allowed_for_player(special_name: str, role: str, main_position: str | None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None) -> bool:
    if role == "野手" and not is_special_position_allowed(special_name, main_position, sub_positions):
        return False
    if role == "投手" and not is_special_pitcher_aptitude_allowed(special_name, pitcher_aptitudes):
        return False
    return True

def catcher_context_multiplier(special_name: str, main_position: str | None, sub_positions: Any, abilities: dict[str, Any]) -> float:
    if special_name not in CATCHER_CONTEXT_SPECIALS:
        return 1.0
    level = position_aptitude_level(main_position, sub_positions, "捕手")
    if special_name == "フレーミング◎":
        multiplier = {"main": 1.0, "◎": 0.50, "○": 0.25, "△": 0.10, "none": 0.0}[level]
    else:
        multiplier = {"main": 1.0, "◎": 0.70, "○": 0.45, "△": 0.20, "none": 0.0}[level]
    if level != "main" and multiplier > 0:
        fielding = ability_numeric_value(abilities, "守備力")
        catching = ability_numeric_value(abilities, "捕球")
        arm = ability_numeric_value(abilities, "肩力")
        defensive_values = [v for v in (fielding, catching, arm) if isinstance(v, int | float)]
        if defensive_values:
            defensive_average = sum(defensive_values) / len(defensive_values)
            if defensive_average < 55:
                multiplier *= 0.75
            elif defensive_average >= 70 and special_name != "フレーミング◎":
                multiplier *= 1.05
    return multiplier

def starter_context_multiplier(special_name: str, pitcher_aptitudes: dict[str, Any] | None, abilities: dict[str, Any]) -> float:
    starter = pitcher_aptitude_level(pitcher_aptitudes, "starter_aptitude")
    reliever = pitcher_aptitude_level(pitcher_aptitudes, "reliever_aptitude")
    closer = pitcher_aptitude_level(pitcher_aptitudes, "closer_aptitude")
    stamina = ability_numeric_value(abilities, "スタミナ")
    closer_only = starter == "-" and reliever == "-" and closer in PITCHER_APTITUDE_ALLOWED
    if special_name == "尻上がり":
        multiplier = {"◎": 1.0, "○": 0.55, "-": 0.05}[starter]
    elif special_name == "スロースターター":
        multiplier = {"◎": 1.0, "○": 0.50, "-": 0.05}[starter]
    elif special_name == "立ち上がり○":
        multiplier = {"◎": 1.0, "○": 0.75, "-": 0.45}[starter]
    elif special_name == "根性":
        if starter == "◎":
            multiplier = 1.0
        elif starter == "○":
            multiplier = 0.75
        elif reliever == "◎" and isinstance(stamina, int | float) and stamina >= 65:
            multiplier = 0.70
        elif closer_only:
            multiplier = 0.15
        else:
            multiplier = 0.35
        if isinstance(stamina, int | float) and stamina < 45:
            multiplier *= 0.70
    elif special_name == "要所○":
        if starter == "◎":
            multiplier = 1.0
        elif starter == "○":
            multiplier = 0.80
        elif reliever == "◎":
            multiplier = 0.60
        elif closer_only:
            multiplier = 0.35
        else:
            multiplier = 0.45
    elif special_name == "投打躍動":
        multiplier = {"◎": 1.0, "○": 0.50, "-": 0.05}[starter]
        batting_values = [ability_numeric_value(abilities, key) for key in ("ミート", "パワー", "弾道", "走力")]
        batting_values = [v for v in batting_values if isinstance(v, int | float)]
        if batting_values:
            batting_score = sum(batting_values) / len(batting_values)
            if batting_score < 45:
                multiplier *= 0.45
            elif batting_score >= 65:
                multiplier *= 1.10
    else:
        multiplier = 1.0
    return multiplier

def relief_context_multiplier(special_name: str, pitcher_aptitudes: dict[str, Any] | None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, acquisition_role: str | None = None) -> float:
    reliever = pitcher_aptitude_level(pitcher_aptitudes, "reliever_aptitude")
    closer = pitcher_aptitude_level(pitcher_aptitudes, "closer_aptitude")
    has_reliever = reliever in PITCHER_APTITUDE_ALLOWED
    closer_only = not has_reliever and closer in PITCHER_APTITUDE_ALLOWED
    if special_name == "火消し":
        if reliever == "◎":
            multiplier = 1.0
        elif closer == "◎" and has_reliever:
            multiplier = 0.75
        elif reliever == "○":
            multiplier = 0.65
        elif closer_only:
            multiplier = 0.45
        else:
            multiplier = 0.55
    elif special_name == "緊急登板○":
        if reliever == "◎":
            multiplier = 1.0
        elif reliever == "○":
            multiplier = 0.70
        elif closer == "◎":
            multiplier = 0.65
        elif closer == "○":
            multiplier = 0.45
        else:
            multiplier = 0.50
    elif special_name == "投手存在感":
        if closer == "◎":
            multiplier = 1.05
        elif closer == "○":
            multiplier = 0.85
        elif reliever == "◎":
            multiplier = 0.75
        elif reliever == "○":
            multiplier = 0.55
        else:
            multiplier = 0.45
        if acquisition_role in {"勝ちパターン候補", "クローザー候補"}:
            multiplier *= 1.20
        if position_style in {"剛腕クローザー", "剛腕中継ぎ"} or archetype in {"速球", "制球"}:
            multiplier *= 1.08
        if player_class in {"スター級", "大物実績者", "一軍主力級", "主力期待級"}:
            multiplier *= 1.05
    elif special_name == "回またぎ○":
        if reliever == "◎":
            multiplier = 1.0
        elif reliever == "○":
            multiplier = 0.70
        elif closer_only:
            multiplier = 0.25
        else:
            multiplier = 0.45
        if position_style == "ロングリリーフ型":
            multiplier *= 1.15
    else:
        multiplier = 1.0
    return multiplier

def special_context_multiplier(special_name: str, role: str, main_position: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None, abilities: dict[str, Any] | None = None, player_type: str | None = None, position_style: str | None = None, acquisition_role: str | None = None, player_class: str | None = None, archetype: str | None = None) -> float:
    abilities = abilities or {}
    multiplier = 1.0
    if role == "野手":
        multiplier *= catcher_context_multiplier(special_name, main_position, sub_positions, abilities)
    elif role == "投手":
        if special_name in STARTER_CONTEXT_SPECIALS:
            multiplier *= starter_context_multiplier(special_name, pitcher_aptitudes, abilities)
        if special_name in RELIEF_REQUIRED_SPECIALS:
            multiplier *= relief_context_multiplier(special_name, pitcher_aptitudes, player_class, archetype, position_style, acquisition_role)
    return max(0.0, min(1.8, float(multiplier)))

def adjust_special_chance(row: dict[str, Any], base_chance: int, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, development_stage: str | None = None, acquisition_role: str | None = None, weakness_profile: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None) -> float:
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
            if role == "野手" and category == "架空球団用":
                chance *= 1.16
        elif kind == "red":
            chance *= 0.98 if role == "投手" else (0.92 if category == "架空球団用" else 1.18)
        elif kind == "green" and role == "投手":
            chance *= 0.90
    if power == "strong" or name in STRONG_SPECIALS:
        chance *= 0.70
        if role == "野手" and category == "架空球団用" and power == "strong":
            chance *= 1.22
    if kind == "red":
        chance *= (0.86 if role == "野手" and category == "架空球団用" else 1.34 if role == "野手" else 1.08)
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

    chance *= classification_special_scale(category, player_class, archetype, position_style, development_stage, acquisition_role, weakness_profile, kind, power, name)

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
        if not is_special_position_allowed(name, position, sub_positions):
            return 0
        if category == "架空球団用":
            chance *= FIELDER_REALISTIC_SPECIAL_BOOSTS.get(name, 1.0)
            chance *= FIELDER_REALISTIC_SPECIAL_SUPPRESSIONS.get(name, 1.0)
        if name == "国際大会×" and category == "架空球団用":
            chance *= 0.35
        if name in POSITION_RESTRICTED_SPECIALS and has_position_aptitude(position, sub_positions, POSITION_RESTRICTED_SPECIALS[name]): chance += 2
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
            if name == "内野安打○" and isinstance(speed, int | float):
                if speed >= 80:
                    chance += 3.5
                elif speed >= 70:
                    chance += 2.2
                elif speed >= 60:
                    chance += 0.8
                else:
                    chance -= 3.5
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
                if category == "架空球団用":
                    if meet < 35:
                        chance += 12.0
                    elif meet < 45:
                        chance += 6.8
                    elif meet < 55:
                        chance += 2.2
                    elif meet < 65:
                        chance += 0.2
                    elif meet < 75:
                        chance -= 3.2
                    else:
                        chance = min(chance, 1.0)
                    if isinstance(power_v, int | float) and power_v >= 80:
                        chance += 1.0
                    elif isinstance(power_v, int | float) and power_v >= 70:
                        chance += 0.4
                    if player_type == "長距離砲" or archetype == "長打" or position_style in {"強打一塁手", "強打三塁手", "強打外野手"}:
                        chance += 0.8
                    if player_class == "一軍主力級":
                        if meet >= 55:
                            chance *= 0.62
                        elif meet >= 45:
                            chance *= 0.78
                        elif meet < 35:
                            chance += 2.0
                    if (player_type == "長距離砲" or archetype == "長打" or position_style in {"強打一塁手", "強打三塁手", "強打外野手"}) and meet >= 55:
                        chance *= 0.74
                else:
                    if meet < 40:
                        chance += 5
                    elif meet < 50:
                        chance += 4
                    elif meet < 58:
                        chance += 1.8
                    elif meet >= 75:
                        chance -= 6
                    elif meet >= 65:
                        chance -= 4
                    if isinstance(power_v, int | float) and power_v >= 80:
                        chance += 3
                    elif isinstance(power_v, int | float) and power_v >= 70:
                        chance += 1.5
                    if player_type == "長距離砲" or archetype == "長打" or position_style in {"強打一塁手", "強打三塁手", "強打外野手"}:
                        chance += 2.5
            if name in {"サヨナラ男", "満塁男"}:
                if player_class in {"スター級", "一軍主力級", "ベテラン型"}:
                    chance += 2.4
                if acquisition_role in {"中軸候補", "主砲候補"} or position_style in {"強打一塁手", "強打三塁手", "強打外野手", "打撃型捕手"}:
                    chance += 1.2
                if player_class in {"二軍級", "若手素材型"}:
                    chance -= 2.2
            if name == "固め打ち":
                if isinstance(meet, int | float) and meet >= 60:
                    chance += 2.0
                if player_class in {"スター級", "一軍主力級", "ベテラン型"}:
                    chance += 1.4
                if isinstance(meet, int | float) and meet < 45:
                    chance -= 2.8
            if name == "エラー":
                if (isinstance(field, int | float) and field < 45) or (isinstance(catch, int | float) and catch < 45): chance += 4
                elif (isinstance(field, int | float) and field < 55) or (isinstance(catch, int | float) and catch < 55): chance += 2
                if (isinstance(field, int | float) and field >= 70) and (isinstance(catch, int | float) and catch >= 70): chance -= 4
            if name == "併殺":
                if isinstance(speed, int | float) and speed < 40:
                    chance += 4
                elif isinstance(speed, int | float) and speed < 60:
                    chance += 1.5
                elif isinstance(speed, int | float) and speed < 70:
                    chance -= 2.0
                elif isinstance(speed, int | float) and speed < 80:
                    chance -= 6.0
                elif isinstance(speed, int | float):
                    chance = 0
                if isinstance(power_v, int | float) and power_v >= 75 and isinstance(meet, int | float) and meet < 55 and isinstance(speed, int | float) and 70 <= speed < 80:
                    chance += 1.2
            chance -= 0.05
        if kind == "green" or name in PERSONALITY_SPECIALS:
            chance *= 2.08 if category == "架空球団用" and player_class in {"スター級", "一軍主力級", "ベテラン型", "一軍控え級"} else 1.75
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
        if name == "代打○":
            if player_class in {"一軍控え級", "ベテラン型"} or acquisition_role == "代打要員":
                chance += 2.5
            if player_class in {"スター級", "一軍主力級", "若手素材型"}:
                chance -= 2.5
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
        if not is_special_pitcher_aptitude_allowed(name, pitcher_aptitudes):
            return 0
        if category == "架空球団用":
            chance *= PITCHER_REALISTIC_SPECIAL_BOOSTS.get(name, 1.0)
            chance *= PITCHER_REALISTIC_SPECIAL_SUPPRESSIONS.get(name, 1.0)
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
        if category == "架空球団用" and name == "キレ○":
            if total_break >= 9:
                chance += 4.0
            elif total_break >= 7:
                chance += 2.4
            if ball_count >= 3:
                chance += 1.8
            if archetype == "変化球":
                chance += 2.2
            if player_class in {"スター級", "一軍主力級"}:
                chance += 1.4
        if category == "架空球団用" and name == "緩急○":
            if isinstance(speed_v, int) and speed_v >= 148 and total_break >= 6:
                chance += 2.0
            if position == "先発" or archetype in {"制球", "変化球"}:
                chance += 1.5
        if category == "架空球団用" and name == "低め○" and isinstance(control, int | float):
            if control >= 65:
                chance += 2.8
            elif control >= 58:
                chance += 1.5
            elif control < 48:
                chance -= 1.8
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
        if name == "奪三振":
            if isinstance(speed_v, int) and speed_v >= 150:
                chance += 2.8
            elif isinstance(speed_v, int) and speed_v >= 147:
                chance += 1.2
            if total_break >= 9 or ball_count >= 3:
                chance += 2.0
            elif total_break >= 7:
                chance += 0.8
            if archetype == "変化球":
                chance += 1.2
            if position == "抑え":
                chance += 1.2
            if isinstance(speed_v, int) and speed_v < 142 and total_break < 7:
                chance -= 2.2
        if name in {"球持ち○", "リリース○"} and archetype in {"制球", "変化球"}:
            chance += 1.8
        if name in {"球持ち○", "リリース○"}:
            if isinstance(control, int | float) and control >= 60:
                chance += 1.1
            if isinstance(age, int) and age >= 27:
                chance += 0.9
            if player_class in {"スター級", "一軍主力級", "ベテラン型"}:
                chance += 0.8
            if isinstance(control, int | float) and control < 42 and isinstance(age, int) and age <= 23:
                chance -= 1.6
        if name == "球速安定" and isinstance(speed_v, int):
            chance += 2.4 if speed_v >= 150 else 0.9 if speed_v >= 147 else -1.2 if speed_v < 145 else 0
            if player_class in {"スター級", "一軍主力級"}:
                chance += 1.0
            if position in {"中継ぎ", "抑え"}:
                chance += 0.7
            if isinstance(control, int | float) and control < 42:
                chance -= 1.4
        if name == "内角攻め":
            if isinstance(control, int | float) and control >= 65:
                chance += 1.5
            elif isinstance(control, int | float) and control >= 55:
                chance += 0.8
            elif isinstance(control, int | float) and control < 45:
                chance -= 1.8
            if isinstance(speed_v, int) and speed_v >= 148:
                chance += 0.9
            if player_class in {"スター級", "一軍主力級", "ベテラン型"}:
                chance += 0.8
        if category == "架空球団用" and name in {"クロスファイヤー", "対強打者○"}:
            if player_class in {"スター級", "一軍主力級"}:
                chance += 1.6
            if isinstance(speed_v, int) and speed_v >= 150:
                chance += 1.2
            if isinstance(control, int | float) and control >= 58:
                chance += 1.0
        if name == "四球" and isinstance(control, int | float):
            if control < 35:
                chance += 5.5
            elif control < 45:
                chance += 3.8
            elif control < 55:
                chance += 1.4
            elif control >= 65:
                chance = 0
            else:
                chance *= 0.35
        if name == "抜け球" and isinstance(control, int | float):
            if control < 35:
                chance += 5.2
            elif control < 45:
                chance += 3.5
            elif control < 55:
                chance += 1.2
            elif control >= 60:
                chance = 0
            else:
                chance *= 0.35
            if isinstance(age, int) and age <= 24 and control < 55:
                chance += 1.2
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

    chance *= special_context_multiplier(
        name,
        role,
        main_position=position,
        sub_positions=sub_positions,
        pitcher_aptitudes=pitcher_aptitudes,
        abilities=abilities,
        player_type=player_type,
        position_style=position_style,
        acquisition_role=acquisition_role,
        player_class=player_class,
        archetype=archetype,
    )
    if role == "投手" and name in {"リリース○", "奪三振", "球持ち○", "内角攻め", "キレ○", "緩急○", "低め○", "クロスファイヤー", "対強打者○"}:
        max_chance = 18.0
    else:
        max_chance = 8.0 if power == "strong" or name in STRONG_SPECIALS else 25.0
    return max(0.0, min(max_chance, float(chance)))


def is_countable_special(name: str) -> bool:
    return name not in USAGE_SPECIAL_NAMES


def special_count_bounds(category: str | None, player_class: str | None) -> tuple[int, int]:
    if category == "架空球団用":
        return {
            "スター級": (4, 12),
            "一軍主力級": (2, 11),
            "ベテラン型": (2, 10),
            "一軍控え級": (0, 7),
            "二軍級": (0, 5),
            "若手素材型": (0, 6),
        }.get(player_class or "", (0, 7))
    if category == "助っ人外国人用":
        return (2, 11) if player_class in {"大物実績者", "主力期待級"} else (0, 7)
    if category == "ドラフト候補用":
        return (1, 8) if player_class in {"超上位候補", "上位候補"} else (0, 6)
    return (0, 7)


def weighted_special_cap(rng: random.Random, category: str | None, player_class: str | None, player_score: float) -> int:
    low, high = special_count_bounds(category, player_class)
    if high <= low:
        return high
    if player_class == "スター級":
        base = weighted_choice(rng, [(5, 14), (6, 20), (7, 23), (8, 18), (9, 11), (10, 7), (11, 4), (12, 3)])
    elif player_class in {"一軍主力級", "ベテラン型", "大物実績者", "主力期待級"}:
        base = weighted_choice(rng, [(3, 16), (4, 24), (5, 22), (6, 17), (7, 10), (8, 6), (9, 3), (10, 2)])
    elif player_class in {"一軍控え級", "レギュラー競争級"}:
        base = weighted_choice(rng, [(1, 28), (2, 28), (3, 20), (4, 12), (5, 7), (6, 3), (7, 2)])
    elif player_class in {"二軍級", "若手素材型", "育成候補", "育成素材型", "保険・バックアップ級"}:
        base = weighted_choice(rng, [(0, 26), (1, 28), (2, 22), (3, 14), (4, 7), (5, 3)])
    else:
        base = weighted_choice(rng, [(1, 25), (2, 27), (3, 22), (4, 14), (5, 8), (6, 4)])
    if player_score >= 68 and rng.random() < 0.45:
        base += 1
    elif player_score < 45 and rng.random() < 0.35:
        base -= 1
    return max(low, min(high, base))


def extra_special_draws(rng: random.Random, category: str | None, player_class: str | None, player_score: float) -> int:
    if category != "架空球団用":
        return 0
    draws = 0
    if player_class == "スター級":
        draws = 1
        draws += int(rng.random() < 0.85)
        draws += int(rng.random() < 0.45)
    elif player_class in {"一軍主力級", "ベテラン型"}:
        draws = 1
        draws += int(rng.random() < 0.85)
        draws += int(rng.random() < 0.15)
    elif player_class == "一軍控え級":
        draws = int(rng.random() < 0.58)
    elif player_class == "若手素材型":
        draws = int(player_score >= 58 and rng.random() < 0.32)
    elif player_class == "二軍級":
        draws = int(player_score >= 60 and rng.random() < 0.18)
    return draws


def audit_special_selection(
    rng: random.Random,
    selected: list[str],
    role: str,
    position: str | None,
    abilities: dict[str, Any] | None,
    sub_positions: Any = None,
    pitcher_aptitudes: dict[str, Any] | None = None,
) -> list[str]:
    abilities = abilities or {}
    audited: list[str] = []
    seen: set[str] = set()
    for name in selected:
        if name in seen:
            continue
        if not is_special_allowed_for_player(name, role, position, sub_positions, pitcher_aptitudes):
            continue
        if role == "投手":
            control = ability_numeric_value(abilities, "コントロール")
            if name == "四球" and isinstance(control, int | float) and control >= 60:
                continue
            if name == "抜け球" and isinstance(control, int | float) and control >= 60:
                continue
        else:
            speed = ability_numeric_value(abilities, "走力")
            power_v = ability_numeric_value(abilities, "パワー")
            meet = ability_numeric_value(abilities, "ミート")
            if name == "併殺" and isinstance(speed, int | float):
                if speed >= 80:
                    continue
                if speed >= 70 and not (isinstance(power_v, int | float) and power_v >= 75 and isinstance(meet, int | float) and meet < 55):
                    continue
                if speed >= 70 and rng.random() < 0.75:
                    continue
        conflict = {
            "四球": {"ストライク先行"},
            "ストライク先行": {"四球"},
            "抜け球": {"リリース○"},
            "リリース○": {"抜け球"},
            "スロースターター": {"立ち上がり○"},
            "立ち上がり○": {"スロースターター"},
            "三振": {"粘り打ち"},
            "粘り打ち": {"三振"},
            "併殺": {"積極走塁", "積極盗塁", "走塁〇", "盗塁〇"},
            "走塁〇": {"併殺"},
            "盗塁〇": {"併殺"},
            "積極走塁": {"併殺"},
            "積極盗塁": {"併殺"},
        }.get(name, set())
        if conflict & seen:
            continue
        audited.append(name)
        seen.add(name)
    return audited


def rebuild_special_generation_state(selected: list[str], row_by_name: dict[str, dict[str, Any]]) -> tuple[set[str], set[str]]:
    selected_names = set(selected)
    used_groups: set[str] = set()
    for name in selected:
        group = str(row_by_name.get(name, {}).get("group", "") or "").strip()
        if group:
            used_groups.add(group)
    return selected_names, used_groups


def generate_specials(rng: random.Random, master: MasterData, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, development_stage: str | None = None, acquisition_role: str | None = None, weakness_profile: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None) -> list[str]:
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
    chance_by_name: dict[str, float] = {}
    row_by_name: dict[str, dict[str, Any]] = {}
    for row in candidates:
        group = str(row.get("group", "") or "").strip()
        if group and group in used_groups:
            continue
        name = row["name"]
        if not is_special_allowed_for_player(name, role, position, sub_positions, pitcher_aptitudes):
            continue
        chance = adjust_special_chance(row, int(row.get("weight", 0) or 0), role, player_type, position, age, abilities, breaking_balls, category, player_class, archetype, position_style, development_stage, acquisition_role, weakness_profile, sub_positions, pitcher_aptitudes)
        chance_by_name[name] = chance
        row_by_name[name] = row
        if name in selected_names:
            continue
        if rng.random() < chance / 100 and conflicts.get(name) not in selected_names:
            selected.append(name)
            selected_names.add(name)
            if group:
                used_groups.add(group)
    selected = audit_special_selection(rng, selected, role, position, abilities, sub_positions, pitcher_aptitudes)
    selected_names, used_groups = rebuild_special_generation_state(selected, row_by_name)
    if role == "投手":
        score_values = [pitcher_speed_value(abilities or {}), ability_numeric_value(abilities or {}, "コントロール"), ability_numeric_value(abilities or {}, "スタミナ")]
    else:
        score_values = [ability_numeric_value(abilities or {}, key) for key in ("ミート", "パワー", "走力", "肩力", "守備力", "捕球")]
    numeric_scores = [value for value in score_values if isinstance(value, int | float)]
    player_score = sum(numeric_scores) / max(1, len(numeric_scores))
    if category == "架空球団用":
        min_count, _max_count = special_count_bounds(category, player_class)
        cap = weighted_special_cap(rng, category, player_class, player_score)
    else:
        min_count = 0
        cap = 6 if category == "助っ人外国人用" else 5
        if category == "助っ人外国人用" and player_score >= 68:
            cap += 1
    countable = [name for name in selected if is_countable_special(name)]
    if len(countable) < min_count:
        fill_candidates = sorted(
            [name for name, chance in chance_by_name.items() if is_countable_special(name) and name not in selected_names and chance > 0],
            key=lambda item: chance_by_name[item] * (0.55 if category == "架空球団用" and role == "野手" and (str(row_by_name.get(item, {}).get("kind", "")) == "green" or item in PERSONALITY_SPECIALS) else 1.0),
            reverse=True,
        )
        for name in fill_candidates:
            row = row_by_name[name]
            group = str(row.get("group", "") or "").strip()
            if group and group in used_groups:
                continue
            if conflicts.get(name) in selected_names:
                continue
            selected.append(name)
            selected_names.add(name)
            if group:
                used_groups.add(group)
            countable.append(name)
            if len(countable) >= min_count:
                break
    bonus_draws = extra_special_draws(rng, category, player_class, player_score)
    if bonus_draws > 0 and len(countable) < cap:
        extra_candidates = sorted(
            [name for name, chance in chance_by_name.items() if is_countable_special(name) and name not in selected_names and chance > 0],
            key=lambda item: (chance_by_name[item] * (0.55 if category == "架空球団用" and role == "野手" and (str(row_by_name.get(item, {}).get("kind", "")) == "green" or item in PERSONALITY_SPECIALS) else 1.0), rng.random()),
            reverse=True,
        )
        for name in extra_candidates:
            row = row_by_name[name]
            group = str(row.get("group", "") or "").strip()
            if group and group in used_groups:
                continue
            if conflicts.get(name) in selected_names:
                continue
            if rng.random() >= min(0.82, chance_by_name[name] / 12):
                continue
            trial = audit_special_selection(rng, selected + [name], role, position, abilities, sub_positions, pitcher_aptitudes)
            if len(trial) == len(selected):
                continue
            selected = trial
            selected_names, used_groups = rebuild_special_generation_state(selected, row_by_name)
            countable = [item for item in selected if is_countable_special(item)]
            bonus_draws -= 1
            if bonus_draws <= 0 or len(countable) >= cap:
                break
    if len(countable) > cap:
        usage = [name for name in selected if not is_countable_special(name)]
        keep = set(countable)
        sorted_countable = sorted(countable, key=lambda item: (chance_by_name.get(item, 0), rng.random()), reverse=True)
        keep = set(sorted_countable[:cap])
        selected = usage + [name for name in selected if name in keep]
    selected = audit_special_selection(rng, selected, role, position, abilities, sub_positions, pitcher_aptitudes)
    return selected



def ranked_shift_for_group(rng: random.Random, group_name: str, role: str, position: str, player_type: str, abilities: dict[str, Any], archetype: str | None = None, position_style: str | None = None, weakness_profile: str | None = None) -> int:
    shift = 0
    if role == "投手":
        speed = pitcher_speed_value(abilities)
        if group_name == "ノビ":
            if isinstance(speed, int) and speed >= 152 and rng.random() < 0.55:
                shift += 1
            elif isinstance(speed, int) and speed < 140 and rng.random() < 0.75:
                shift -= 1
        if (player_type == "速球派" or archetype == "速球" or position_style in {"剛腕中継ぎ", "剛腕クローザー", "速球型先発"}) and group_name == "ノビ":
            shift += 1
        if (player_type == "技巧派" or archetype in {"制球", "総合"}) and group_name in ("対ピンチ", "対左打者"):
            shift += 1
        control = ability_numeric_value(abilities, "コントロール")
        if isinstance(control, int | float) and control >= 70 and group_name == "対ピンチ":
            shift += 1
    else:
        if player_type == "長距離砲" and group_name == "チャンス" and rng.random() < 0.5:
            shift += rng.choice([-1, 1])
        if (player_type == "俊足型" or archetype == "俊足") and group_name in ("盗塁", "走塁"):
            shift += 1
        if (player_type == "守備職人" or archetype in {"守備", "強肩"}) and group_name == "送球":
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


def ranked_weight_items_for_group(group_name: str, role: str, position: str, player_type: str, abilities: dict[str, Any], age: int | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, sub_positions: Any = None) -> list[tuple[str, int]]:
    weights = RANKED_SPECIAL_BASE_WEIGHTS.copy()
    if role == "投手" and group_name == "クイック":
        control = ability_numeric_value(abilities, "コントロール")
        if player_type == "技巧派":
            weights.update({"B": weights["B"] + 2, "C": weights["C"] + 4, "D": weights["D"] - 4, "E": weights["E"] - 2})
        if isinstance(control, int | float) and control >= 70:
            weights.update({"B": weights["B"] + 1, "C": weights["C"] + 3, "D": weights["D"] - 3, "E": weights["E"] - 1})
    elif role == "野手" and group_name == "キャッチャー":
        catcher_level = position_aptitude_level(position, sub_positions, "捕手")
        if catcher_level == "main":
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
        elif catcher_level == "◎":
            weights.update({"A": 1, "B": 2, "C": 12, "D": 62, "E": 17, "F": 5, "G": 1})
        elif catcher_level == "○":
            weights.update({"A": 1, "B": 1, "C": 6, "D": 54, "E": 27, "F": 9, "G": 2})
        elif catcher_level == "△":
            weights.update({"A": 1, "B": 1, "C": 3, "D": 45, "E": 30, "F": 16, "G": 4})
    if category == "ドラフト候補用" and isinstance(age, int) and age <= 21:
        weights.update({"A": max(1, weights["A"] - 1), "B": max(1, weights["B"] - 2), "D": weights["D"] + 2})
    if category == "架空球団用" and role == "投手" and player_class not in {"スター級"}:
        if player_class in {"一軍主力級", "ベテラン型"}:
            weights.update({"B": max(1, weights["B"] - 1), "C": max(1, weights["C"] - 1), "D": weights["D"] + 5, "E": max(1, weights["E"] - 1)})
        else:
            weights.update({"B": max(1, weights["B"] - 2), "C": max(1, weights["C"] - 2), "D": weights["D"] + 8, "E": max(1, weights["E"] - 2)})
    if player_class in {"スター級", "大物実績者"}:
        weights.update({"B": weights["B"] + 1, "C": weights["C"] + 2, "D": max(1, weights["D"] - 2)})
    elif player_class in {"二軍級", "育成候補", "育成素材型"}:
        weights.update({"E": weights["E"] + 2, "F": weights["F"] + 1, "D": max(1, weights["D"] - 2)})
    if category == "架空球団用" and player_class in {"二軍級", "若手素材型"}:
        weights.update({
            "A": max(1, weights["A"] - 3),
            "B": max(1, weights["B"] - 5),
            "C": max(1, weights["C"] - 4),
            "D": weights["D"] + 22,
            "E": weights["E"] + 7,
            "F": max(1, weights["F"] - 1),
            "G": max(1, weights["G"] - 4),
        })
    elif category == "架空球団用" and role == "投手" and player_class == "一軍控え級":
        weights.update({
            "C": max(1, weights["C"] - 2),
            "D": weights["D"] + 12,
            "E": weights["E"] + 2,
            "F": max(1, weights["F"] - 2),
        })
    return [(rank_name, max(1, weight)) for rank_name, weight in weights.items()]


def generate_ranked_specials(rng: random.Random, master: MasterData, role: str, position: str, player_type: str, abilities: dict[str, Any], age: int | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, weakness_profile: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None) -> dict[str, str]:
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
        if group_name == "キャッチャー" and not has_position_aptitude(position, sub_positions, {"捕手"}):
            continue
        rank_value = weighted_choice(rng, ranked_weight_items_for_group(group_name, role, position, player_type, abilities, age, category, player_class, archetype, position_style, sub_positions))
        if category == "架空球団用" and player_class in {"二軍級", "若手素材型"} and rank_value in {"A", "B", "G"} and rng.random() < 0.78:
            rank_value = weighted_choice(rng, [("C", 8), ("D", 58), ("E", 28), ("F", 6)])
        if group_name == "チャンス" and player_type == "長距離砲" and rng.random() < 0.35:
            rank_value = weighted_choice(rng, [("A", 4), ("B", 12), ("C", 20), ("D", 28), ("E", 20), ("F", 12), ("G", 4)])
        rank_value = shifted_rank(rank_value, ranked_shift_for_group(rng, group_name, role, position, player_type, abilities, archetype, position_style, weakness_profile))
        selected[group_name] = names_by_rank[rank_value]
    return selected

def fielder_age_mods(age: int, archetype: str, player_class: str) -> dict[str, int]:
    mods = {
        "ミート": curve_delta(age, [(18, -9), (24, 0), (25, 3), (30, 5), (34, 1), (36, -3)]),
        "パワー": curve_delta(age, [(18, -8), (21, -3), (25, 3), (31, 5), (34, 1), (36, -3)]),
        "走力": curve_delta(age, [(18, 4), (23, 8), (27, 6), (31, -1), (34, -7), (36, -12)]),
        "肩力": curve_delta(age, [(18, 1), (22, 4), (28, 5), (33, 1), (36, -4)]),
        "守備力": curve_delta(age, [(18, -8), (22, -4), (28, 4), (33, 5), (36, 0)]),
        "捕球": curve_delta(age, [(18, -8), (22, -4), (28, 4), (33, 5), (36, 0)]),
    }
    if age >= 34 and archetype in {"巧打", "守備", "バランス"}:
        for key in ("ミート", "守備力", "捕球"):
            mods[key] += 3
    if age >= 34 and player_class == "ベテラン型":
        mods["走力"] -= 2
        for key in ("ミート", "パワー", "守備力", "捕球"):
            mods[key] += 2
    return mods


def growth_age_delta(age: int, growth_type: str) -> int:
    gt = normalize_growth_type(growth_type)
    points = {
        "very_early": [(18, 4), (22, 4), (27, 1), (30, -3), (35, -8), (38, -11), (42, -14)],
        "early": [(18, 2), (22, 3), (28, 2), (31, -1), (35, -6), (38, -9), (42, -12)],
        "normal": [(18, 0), (24, 0), (29, 1), (33, 0), (35, -4), (38, -7), (42, -10)],
        "late": [(18, -2), (24, -2), (29, -1), (33, 2), (35, -2), (38, -5), (42, -8)],
        "very_late": [(18, -3), (24, -3), (29, -2), (34, 3), (35, 1), (38, -3), (42, -6)],
    }
    return curve_delta(age, points[gt])


def apply_fielder_growth_mods(values: dict[str, int], age: int, growth_type: str, archetype: str, position_style: str) -> None:
    base = growth_age_delta(age, growth_type)
    if base >= 0:
        weights = {"ミート": 0.8, "パワー": 0.8, "走力": 0.8, "肩力": 0.7, "守備力": 0.8, "捕球": 0.8}
        if archetype in {"巧打", "長打"} or "打撃" in position_style or "強打" in position_style:
            weights["ミート"] += 0.25; weights["パワー"] += 0.25
        if archetype == "守備" or "守備" in position_style:
            weights["守備力"] += 0.25; weights["捕球"] += 0.25
        if archetype == "俊足" or "走塁" in position_style:
            weights["走力"] += 0.25
    else:
        weights = {"ミート": 0.45, "パワー": 0.50, "走力": 1.0, "肩力": 0.85, "守備力": 0.70, "捕球": 0.60}
    for key, weight in weights.items():
        values[key] += round(base * weight)


def apply_fielder_player_class_mods(values: dict[str, int], category: str, player_class: str) -> None:
    if category == "架空球団用":
        class_mods = {
            "スター級": {"ミート": 6, "パワー": 8, "走力": 6, "肩力": 7, "守備力": 4, "捕球": 3},
            "一軍主力級": {"ミート": 1, "パワー": 5, "走力": 5, "肩力": 6, "守備力": 0, "捕球": -1},
            "一軍控え級": {"ミート": -5, "パワー": 1, "走力": 5, "肩力": 5, "守備力": -5, "捕球": -6},
            "二軍級": {"ミート": -14, "パワー": -4, "走力": 2, "肩力": 4, "守備力": -13, "捕球": -14},
            "若手素材型": {"ミート": -17, "パワー": -3, "走力": 8, "肩力": 8, "守備力": -15, "捕球": -16},
            "ベテラン型": {"ミート": -3, "パワー": 1, "走力": -7, "肩力": 0, "守備力": -3, "捕球": -2},
        }
        add_mod(values, class_mods.get(player_class, {}))
    else:
        class_mods = {
            "ドラフト候補用": {
                "超上位候補": 7, "上位候補": 3, "中位候補": -2, "下位候補": -7, "育成候補": -11,
            },
            "助っ人外国人用": {
                "大物実績者": 10, "主力期待級": 5, "レギュラー競争級": 0, "保険・バックアップ級": -8, "育成素材型": -7, "再生候補": -4,
            },
        }
        mod = class_mods.get(category, {}).get(player_class, 0)
        for key in values:
            values[key] += mod
    if player_class in {"若手素材型", "育成候補", "育成素材型"}:
        for key in TECHNICAL_FIELDER_KEYS:
            values[key] -= 3
    if player_class in {"ベテラン型", "再生候補"}:
        values["走力"] -= 4

def apply_fielder_archetype_mods(rng: random.Random, values: dict[str, int], archetype: str, category: str = "") -> None:
    if category != "架空球団用":
        if archetype == "巧打":
            add_mod(values, {"ミート": rng.randint(10, 14), "パワー": -rng.randint(2, 5), "走力": rng.randint(0, 3), "守備力": rng.randint(0, 2)})
        elif archetype == "長打":
            add_mod(values, {"パワー": rng.randint(13, 18), "ミート": -rng.randint(2, 5), "走力": -rng.randint(3, 7), "守備力": -rng.randint(1, 4)})
        elif archetype == "俊足":
            add_mod(values, {"走力": rng.randint(12, 17), "守備力": rng.randint(2, 5), "パワー": -rng.randint(4, 7)})
        elif archetype == "守備":
            add_mod(values, {"守備力": rng.randint(10, 15), "捕球": rng.randint(8, 12), rng.choice(["ミート", "パワー"]): -rng.randint(1, 4)})
        elif archetype == "強肩":
            add_mod(values, {"肩力": rng.randint(12, 17), "守備力": rng.randint(1, 4)})
        elif archetype == "バランス":
            avg = sum(values.values()) / len(values)
            for key in values:
                values[key] += rng.randint(0, 2)
                values[key] = round(values[key] + (avg - values[key]) * rng.uniform(0.15, 0.25))
                if values[key] < 30:
                    values[key] += rng.randint(2, 5)
        return
    if archetype == "巧打":
        add_mod(values, {"ミート": rng.randint(8, 12), "パワー": -rng.randint(3, 7), rng.choice(["肩力", "守備力"]): -rng.randint(2, 5)})
    elif archetype == "長打":
        add_mod(values, {"パワー": rng.randint(12, 17), "ミート": -rng.randint(5, 10), "走力": -rng.randint(2, 5), rng.choice(["守備力", "捕球"]): -rng.randint(4, 8)})
    elif archetype == "俊足":
        add_mod(values, {"走力": rng.randint(13, 18), "パワー": -rng.randint(4, 8), rng.choice(["ミート", "捕球"]): -rng.randint(4, 8)})
    elif archetype == "守備":
        main = rng.choice(["守備力", "捕球"])
        other = "捕球" if main == "守備力" else "守備力"
        add_mod(values, {main: rng.randint(10, 15), other: rng.randint(2, 6), "ミート": -rng.randint(4, 8), "パワー": -rng.randint(5, 9)})
    elif archetype == "強肩":
        add_mod(values, {"肩力": rng.randint(13, 18), rng.choice(["ミート", "捕球"]): -rng.randint(4, 8), "守備力": rng.randint(0, 3)})
    elif archetype == "バランス":
        avg = sum(values.values()) / len(values)
        for key in values:
            values[key] = round(values[key] + (avg - values[key]) * rng.uniform(0.08, 0.16))
        weak = rng.choice(["ミート", "パワー", "守備力", "捕球"])
        values[weak] -= rng.randint(3, 7)

def apply_fielder_position_mods(values: dict[str, int], position: str, position_style: str) -> None:
    position_mods = {
        "捕手": {"ミート": -5, "走力": -7, "肩力": 8, "守備力": 3, "捕球": 3},
        "一塁手": {"パワー": 7, "走力": -5, "肩力": -1, "守備力": -2},
        "二塁手": {"パワー": -3, "走力": 7, "守備力": 5, "捕球": 4},
        "三塁手": {"パワー": 5, "走力": -2, "肩力": 6, "守備力": -1},
        "遊撃手": {"パワー": -5, "走力": 7, "肩力": 6, "守備力": 6, "捕球": 3},
        "外野手": {"走力": 6, "肩力": 5, "守備力": -1},
    }
    style_mods = {
        "守備型捕手": {"肩力": 6, "守備力": 6, "捕球": 6, "走力": -3, "ミート": -3},
        "打撃型捕手": {"ミート": 6, "パワー": 6, "守備力": -2},
        "平均型捕手": {"肩力": 3, "守備力": 2, "捕球": 3},
        "強打一塁手": {"パワー": 6, "走力": -2, "守備力": -2},
        "守備型一塁手": {"守備力": 6, "捕球": 5, "パワー": -1},
        "守備走塁二塁手": {"走力": 5, "守備力": 5, "捕球": 4, "パワー": -2},
        "打撃型二塁手": {"ミート": 5, "パワー": 5, "守備力": -2},
        "強打三塁手": {"パワー": 6, "肩力": 4, "走力": -2},
        "守備型三塁手": {"肩力": 4, "守備力": 6, "捕球": 4},
        "守備走塁遊撃手": {"走力": 4, "肩力": 5, "守備力": 5, "捕球": 4, "パワー": -2},
        "強打遊撃手": {"パワー": 7, "守備力": -3, "走力": -2},
        "巧打遊撃手": {"ミート": 6, "パワー": 2, "守備力": -1},
        "走攻守外野手": {"ミート": 2, "パワー": 2, "走力": 3, "肩力": 3, "守備力": 2},
        "俊足外野手": {"走力": 6, "守備力": 2, "パワー": -3},
        "強打外野手": {"パワー": 7, "走力": -2, "守備力": -2},
        "守備外野手": {"肩力": 5, "守備力": 5, "捕球": 3, "ミート": -2},
    }
    add_mod(values, position_mods.get(position, {}))
    add_mod(values, style_mods.get(position_style, {}))


def apply_fielder_development_mods(rng: random.Random, values: dict[str, int], development_stage: str) -> None:
    if development_stage == "素材型":
        values[rng.choice(["パワー", "走力", "肩力"])] += rng.randint(6, 11)
        for key in TECHNICAL_FIELDER_KEYS:
            values[key] -= rng.randint(3, 7)
    elif development_stage == "即戦力型":
        for key in TECHNICAL_FIELDER_KEYS:
            values[key] += rng.randint(3, 6)
        values["走力"] -= rng.randint(0, 3)


def apply_fielder_acquisition_role_mods(values: dict[str, int], archetype: str, position_style: str, acquisition_role: str) -> None:
    if not acquisition_role:
        return
    power_roles = {"主砲候補", "中軸候補"}
    power_styles = {"強打一塁手", "強打三塁手", "強打外野手"}
    if archetype == "長打" or acquisition_role in power_roles or position_style in power_styles:
        values["パワー"] += 5 if acquisition_role == "主砲候補" else 3
    if acquisition_role in {"内野守備補強", "ユーティリティ"}:
        values["守備力"] += 4
        values["捕球"] += 3
        values["パワー"] -= 2
    if acquisition_role == "外野補強":
        values["肩力"] += 3
        values["走力"] += 2
    if acquisition_role == "保険要員":
        values["守備力"] += 2
        values["捕球"] += 2
    if acquisition_role == "若手育成":
        for key in TECHNICAL_FIELDER_KEYS:
            values[key] -= 3


def apply_fielder_weakness_profile(rng: random.Random, values: dict[str, int], weakness_profile: str) -> None:
    if weakness_profile == "低ミート":
        values["ミート"] -= rng.randint(8, 14)
    elif weakness_profile == "低走力":
        values["走力"] -= rng.randint(8, 15)
    elif weakness_profile == "低守備":
        values["守備力"] -= rng.randint(8, 14)
    elif weakness_profile == "低捕球":
        values["捕球"] -= rng.randint(8, 14)
    elif weakness_profile == "送球不安":
        values["肩力"] -= rng.randint(4, 8)
        values[rng.choice(["捕球", "守備力"])] -= rng.randint(2, 5)


def apply_fielder_variance(rng: random.Random, values: dict[str, int], category: str, development_stage: str) -> None:
    spread = 12 if category in {"ドラフト候補用", "助っ人外国人用"} else 10
    if development_stage == "素材型":
        spread += 4
    elif development_stage == "即戦力型":
        spread = max(6, spread - 4)
    for key in values:
        values[key] += rng.randint(-spread, spread)


def enforce_fielder_position_constraints(rng: random.Random, values: dict[str, int], position: str, position_style: str) -> None:
    minimums = {
        "捕手": {"肩力": 45, "守備力": 42, "捕球": 40},
        "遊撃手": {"肩力": 50, "守備力": 45, "捕球": 38},
        "二塁手": {"肩力": 40, "守備力": 42, "捕球": 40},
        "三塁手": {"肩力": 48},
        "一塁手": {"捕球": 36},
    }
    if position_style == "守備型捕手":
        minimums["捕手"] = {"肩力": 58, "守備力": 50, "捕球": 50}
    if position_style == "守備走塁遊撃手":
        minimums["遊撃手"] = {"肩力": 58, "守備力": 52, "捕球": 45}
    for key, minimum in minimums.get(position, {}).items():
        values[key] = floor_value(rng, values[key], minimum)
    if position == "捕手" and position_style != "打撃型捕手":
        values["ミート"] = cap_value(rng, values["ミート"], 62)
    if position == "遊撃手" and position_style != "強打遊撃手":
        values["パワー"] = cap_value(rng, values["パワー"], 66)


def preferred_fielder_keys(archetype: str, position_style: str) -> list[str]:
    keys_by_archetype = {
        "巧打": ["ミート"],
        "長打": ["パワー"],
        "俊足": ["走力"],
        "守備": ["守備力", "捕球"],
        "強肩": ["肩力"],
        "バランス": [],
    }
    keys = list(keys_by_archetype.get(archetype, []))
    style_keys = {
        "打撃型捕手": ["ミート", "パワー"],
        "強打一塁手": ["パワー"],
        "強打三塁手": ["パワー", "肩力"],
        "強打外野手": ["パワー"],
        "俊足外野手": ["走力"],
        "守備外野手": ["肩力", "守備力"],
        "守備走塁二塁手": ["走力", "守備力", "捕球"],
        "守備走塁遊撃手": ["走力", "肩力", "守備力"],
    }
    for key in style_keys.get(position_style, []):
        if key not in keys:
            keys.append(key)
    return keys


def fielder_high_rank_caps(category: str, age: int, player_class: str) -> tuple[int, int]:
    if category == "ドラフト候補用":
        if age <= 19:
            return (0, 2 if player_class == "超上位候補" else 1)
        if age <= 21:
            return (1, 2 if player_class in {"超上位候補", "上位候補"} else 1)
        return (1, 2 if player_class in {"超上位候補", "上位候補"} else 1)
    if category == "助っ人外国人用":
        return {
            "大物実績者": (2, 4),
            "主力期待級": (1, 2),
            "レギュラー競争級": (0, 1),
            "保険・バックアップ級": (0, 0),
            "育成素材型": (0, 1),
            "再生候補": (0, 1),
        }.get(player_class, (0, 1))
    if age <= 19:
        return (1, 2 if player_class == "スター級" else 1)
    if age <= 22:
        return (1, 2 if player_class in {"スター級", "一軍主力級"} else 1)
    return {
        "スター級": (2, 4),
        "一軍主力級": (1, 2),
        "一軍控え級": (0, 1),
        "二軍級": (0, 0),
        "若手素材型": (1, 1),
        "ベテラン型": (1, 2),
    }.get(player_class, (0, 1))


def enforce_fielder_high_rank_limits(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    player_class: str,
    archetype: str,
    position_style: str,
    allow_foreign_allrounder: bool = False,
) -> None:
    if age <= 19:
        for key in ("ミート", "守備力", "捕球"):
            values[key] = cap_value(rng, values[key], 79)
        for key in FIELDER_ABILITY_KEYS:
            if key not in {"走力", "肩力"}:
                values[key] = cap_value(rng, values[key], 89)
        if category == "架空球団用":
            for key in FIELDER_ABILITY_KEYS:
                if values[key] >= 90 and not (player_class == "スター級" and key in {"走力", "肩力"} and rng.random() < 0.35):
                    values[key] = rng.randint(80, 89)
            young_a_reduce = 0.20 if player_class == "一軍主力級" else 0.55
            if player_class != "スター級" and any(values[key] >= 80 for key in FIELDER_ABILITY_KEYS) and rng.random() < young_a_reduce:
                for key in FIELDER_ABILITY_KEYS:
                    values[key] = cap_value(rng, values[key], rng.randint(75, 79))
    if age >= 35:
        values["走力"] = cap_value(rng, values["走力"], 78)
        values["肩力"] = cap_value(rng, values["肩力"], 89)
    if player_class == "二軍級":
        for key in FIELDER_ABILITY_KEYS:
            values[key] = cap_value(rng, values[key], 79)
    if player_class == "保険・バックアップ級":
        for key in FIELDER_ABILITY_KEYS:
            values[key] = cap_value(rng, values[key], 79)
    if category == "助っ人外国人用" and player_class not in {"大物実績者", "主力期待級"} and values.get("パワー", 0) >= 90 and rng.random() < 0.7:
        values["パワー"] = rng.randint(80, 89)
    if category == "助っ人外国人用" and player_class == "主力期待級" and values.get("パワー", 0) >= 90 and rng.random() < 0.3:
        values["パワー"] = rng.randint(84, 89)
    preferred = preferred_fielder_keys(archetype, position_style)
    max_s, max_a = fielder_high_rank_caps(category, age, player_class)
    if allow_foreign_allrounder:
        max_a += 1
    s_keys = sorted([key for key in FIELDER_ABILITY_KEYS if values[key] >= 90], key=lambda key: (key not in preferred, values[key]))
    trim_s_keys = s_keys[:-max_s] if max_s else s_keys
    for key in trim_s_keys:
        values[key] = rng.randint(80, 89) if max_a > 0 and key in preferred else rng.randint(70, 79)
    a_keys = sorted([key for key in FIELDER_ABILITY_KEYS if values[key] >= 80], key=lambda key: (key not in preferred, values[key]))
    while len(a_keys) > max_a:
        key = next((candidate for candidate in a_keys if candidate not in preferred), a_keys[0])
        values[key] = rng.randint(65, 79)
        a_keys = sorted([candidate for candidate in FIELDER_ABILITY_KEYS if values[candidate] >= 80], key=lambda candidate: (candidate not in preferred, values[candidate]))


def restrict_foreign_all_rounder(
    rng: random.Random,
    values: dict[str, int],
    player_class: str,
    archetype: str,
    position_style: str,
    age: int,
    allow_foreign_allrounder: bool = False,
) -> None:
    def is_allrounder() -> bool:
        return all(values[key] >= 70 for key in ("ミート", "パワー", "走力", "守備力")) or sum(values[key] >= 70 for key in FIELDER_ABILITY_KEYS) >= 4

    if allow_foreign_allrounder or not is_allrounder():
        return
    protected = set(preferred_fielder_keys(archetype, position_style))
    candidates = [key for key in FIELDER_ABILITY_KEYS if key not in protected and values[key] >= 70]
    rng.shuffle(candidates)
    while is_allrounder():
        if not candidates:
            candidates = [key for key in FIELDER_ABILITY_KEYS if values[key] >= 70]
            rng.shuffle(candidates)
        if not candidates:
            break
        key = candidates.pop()
        values[key] = rng.randint(65, 69)


def is_foreign_allrounder_allowed(category: str, player_class: str, age: int, archetype: str, position_style: str) -> bool:
    return (
        category == "助っ人外国人用"
        and player_class in {"大物実績者", "主力期待級"}
        and 25 <= age <= 31
        and archetype == "バランス"
        and position_style in FOREIGN_ALLROUNDER_STYLES
    )


def choose_foreign_allrounder_candidate(rng: random.Random, category: str, player_class: str, age: int, archetype: str, position_style: str) -> bool:
    return is_foreign_allrounder_allowed(category, player_class, age, archetype, position_style) and rng.random() < FOREIGN_ALLROUNDER_FINAL_CHANCE


POWER_FIELDER_STYLES = {"強打一塁手", "強打三塁手", "強打外野手", "打撃型捕手", "強打遊撃手"}
DEFENSIVE_FIELDER_STYLES = {"守備型捕手", "守備型一塁手", "守備走塁二塁手", "守備型三塁手", "守備走塁遊撃手", "守備外野手"}


def fictional_fielder_total_cap(rng: random.Random, player_class: str) -> int:
    if player_class == "スター級":
        return 420 if rng.random() < 0.05 else 405
    if player_class == "一軍主力級":
        return 392 if rng.random() < 0.04 else 382
    if player_class == "ベテラン型":
        return 366
    if player_class == "一軍控え級":
        return 356
    if player_class == "若手素材型":
        return 346
    if player_class == "二軍級":
        return 332
    return 400


def reduce_fielder_total(
    rng: random.Random,
    values: dict[str, int],
    cap: int,
    protected: set[str],
    hard_floor: int = 35,
) -> None:
    attempts = 0
    while sum(values[key] for key in FIELDER_ABILITY_KEYS) > cap and attempts < 120:
        candidates = [key for key in FIELDER_ABILITY_KEYS if key not in protected and values[key] > hard_floor]
        if not candidates:
            candidates = [key for key in FIELDER_ABILITY_KEYS if values[key] > hard_floor]
        if not candidates:
            break
        key = max(candidates, key=lambda item: values[item])
        over = sum(values[item] for item in FIELDER_ABILITY_KEYS) - cap
        values[key] -= min(rng.randint(2, 5), over, values[key] - hard_floor)
        attempts += 1


def apply_fictional_fielder_realism_audit(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    position: str,
    player_class: str,
    archetype: str,
    position_style: str,
) -> None:
    if category != "架空球団用":
        return

    preferred = set(preferred_fielder_keys(archetype, position_style))
    is_power_profile = archetype == "長打" or position_style in POWER_FIELDER_STYLES
    is_defensive_profile = archetype == "守備" or position_style in DEFENSIVE_FIELDER_STYLES or position in {"捕手", "二塁手", "遊撃手"}

    power_s_exception = (
        (player_class == "スター級" and is_power_profile and rng.random() < 0.65)
        or (player_class == "一軍主力級" and is_power_profile and rng.random() < 0.08)
    )
    if values["パワー"] >= 90 and not power_s_exception:
        values["パワー"] = rng.randint(84, 89) if is_power_profile and player_class in {"スター級", "一軍主力級"} else rng.randint(74, 82)
    elif values["パワー"] >= 80:
        if is_power_profile:
            suppress = 0.10 if player_class == "スター級" else 0.25 if player_class == "一軍主力級" else 0.45
            if rng.random() < suppress:
                values["パワー"] = rng.randint(74, 79)
        elif player_class != "スター級" and rng.random() < 0.60:
            values["パワー"] = rng.randint(72, 79)

    meet_a_exception = player_class == "スター級" and archetype == "巧打" and rng.random() < 0.45
    if values["ミート"] >= 90 and not meet_a_exception:
        values["ミート"] = rng.randint(78, 86) if archetype == "巧打" else rng.randint(70, 79)
    elif values["ミート"] >= 80 and not meet_a_exception and rng.random() < 0.55:
        values["ミート"] = rng.randint(72, 79)

    if 22 <= age <= 24 and values["走力"] >= 90 and rng.random() < 0.42:
        values["走力"] = rng.randint(82, 89)

    for key in ("守備力", "捕球"):
        allow_upper = is_defensive_profile and player_class in {"スター級", "一軍主力級", "ベテラン型"}
        if values[key] >= 90 and not allow_upper:
            values[key] = rng.randint(78, 86)
        elif values[key] >= 80 and not allow_upper and rng.random() < 0.60:
            values[key] = rng.randint(72, 79)


    if player_class in {"一軍主力級", "一軍控え級", "二軍級", "若手素材型", "ベテラン型"}:
        for key, cap in {"ミート": 58, "守備力": 62, "捕球": 58}.items():
            if values[key] > cap and key not in preferred:
                values[key] = cap_value(rng, values[key], rng.randint(cap - 6, cap))
    if player_class in {"二軍級", "若手素材型"}:
        values["肩力"] = floor_value(rng, values["肩力"], 55)
        if archetype in {"俊足", "強肩", "長打"}:
            values["走力" if archetype == "俊足" else "肩力" if archetype == "強肩" else "パワー"] = floor_value(rng, values["走力" if archetype == "俊足" else "肩力" if archetype == "強肩" else "パワー"], 62)
        for key, cap in {"ミート": 48, "守備力": 54, "捕球": 52}.items():
            if values[key] > cap:
                values[key] = cap_value(rng, values[key], rng.randint(cap - 8, cap))

    cap = fictional_fielder_total_cap(rng, player_class)
    protected = set(preferred)
    if position == "捕手":
        protected.update({"肩力", "守備力", "捕球"})
    elif position == "遊撃手":
        protected.update({"走力", "肩力", "守備力"})
    elif position == "二塁手":
        protected.update({"走力", "守備力", "捕球"})
    reduce_fielder_total(rng, values, cap, protected)

    if min(values[key] for key in FIELDER_ABILITY_KEYS) >= 70:
        candidates = [key for key in FIELDER_ABILITY_KEYS if key not in protected and values[key] >= 70]
        if not candidates:
            candidates = [key for key in FIELDER_ABILITY_KEYS if values[key] >= 70]
        if candidates:
            key = rng.choice(candidates)
            values[key] = rng.randint(62, 69)


def encourage_foreign_allrounder(rng: random.Random, values: dict[str, int], allow_foreign_allrounder: bool) -> None:
    if not allow_foreign_allrounder:
        return
    core = ["ミート", "パワー", "走力", "守備力", "肩力", "捕球"]
    current_high = [key for key in core if values[key] >= 70]
    needed = max(0, 4 - len(current_high))
    candidates = [key for key in core if key not in current_high]
    rng.shuffle(candidates)
    for key in candidates[:needed]:
        values[key] = max(values[key], rng.randint(70, 76))
    # すでに万能型に近い候補は、一律化せず周辺能力を少しだけ底上げする。
    for key in rng.sample(core, k=rng.randint(1, 2)):
        if 62 <= values[key] < 70:
            values[key] = rng.randint(68, 73)


def finalize_fielder_values(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    position: str,
    player_class: str,
    archetype: str,
    position_style: str,
    allow_foreign_allrounder: bool = False,
) -> None:
    minimum_by_archetype = {
        "長打": ("パワー", 50),
        "俊足": ("走力", 55),
        "守備": ("守備力", 50),
        "強肩": ("肩力", 55),
    }
    if archetype in minimum_by_archetype:
        key, minimum = minimum_by_archetype[archetype]
        values[key] = floor_value(rng, values[key], minimum)
    if archetype == "守備":
        values["捕球"] = floor_value(rng, values["捕球"], 50)
    enforce_fielder_position_constraints(rng, values, position, position_style)
    encourage_foreign_allrounder(rng, values, allow_foreign_allrounder)
    if category == "助っ人外国人用":
        restrict_foreign_all_rounder(rng, values, player_class, archetype, position_style, age, allow_foreign_allrounder)
    enforce_fielder_high_rank_limits(rng, values, category, age, player_class, archetype, position_style, allow_foreign_allrounder)
    if category == "助っ人外国人用":
        restrict_foreign_all_rounder(rng, values, player_class, archetype, position_style, age, allow_foreign_allrounder)
    apply_fictional_fielder_realism_audit(rng, values, category, age, position, player_class, archetype, position_style)
    if age >= 35:
        values["走力"] = cap_value(rng, values["走力"], 78)
    for key in values:
        values[key] = clamp(values[key])


def determine_trajectory(power: int, archetype: str, position: str, position_style: str) -> int:
    trajectory = 4 if power >= 80 else 3 if power >= 58 else 2 if power >= 38 else 1
    if (archetype == "長打" or position_style in {"強打一塁手", "強打三塁手", "強打外野手"}) and power >= 55:
        trajectory = min(4, trajectory + 1)
    if position in {"一塁手", "三塁手"} and power >= 52:
        trajectory = max(trajectory, 3)
    if position == "遊撃手":
        trajectory = max(trajectory, 2)
    return trajectory


def audit_fielder_values(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    position: str,
    player_class: str,
    archetype: str,
    position_style: str,
    allow_foreign_allrounder: bool = False,
) -> None:
    finalize_fielder_values(rng, values, category, age, position, player_class, archetype, position_style, allow_foreign_allrounder)


def generate_fielder_abilities(
    rng: random.Random,
    age: int,
    position: str,
    player_type: str,
    category: str,
    position_style: str = "",
    roster_tier: str = "",
    *,
    player_class: str = "",
    archetype: str = "",
    development_stage: str = "",
    acquisition_role: str = "",
    weakness_profile: str = "",
    allow_foreign_allrounder: bool = False,
    growth_type: str = "normal",
) -> dict[str, Any]:
    archetype = archetype or legacy_archetype_from_player_type("野手", player_type) or "バランス"
    player_class = player_class or player_class_from_legacy_roster_tier(roster_tier) or "一軍控え級"
    position_style = position_style or FIELDER_STYLE_DEFAULTS.get(position, "平均型")
    values = {key: 48 for key in FIELDER_ABILITY_KEYS}
    add_mod(values, fielder_age_mods(age, archetype, player_class))
    apply_fielder_player_class_mods(values, category, player_class)
    if category == "架空球団用":
        if 23 <= age <= 29:
            values["走力"] += 3
            values["肩力"] += 3
            values["パワー"] += 1
        elif 30 <= age <= 34:
            values["ミート"] += 1
            values["パワー"] += 1
            values["肩力"] += 1
        values["走力"] += 2 if age < 35 else 0
        values["肩力"] += 2
    apply_fielder_archetype_mods(rng, values, archetype, category)
    apply_fielder_position_mods(values, position, position_style)
    apply_fielder_development_mods(rng, values, development_stage)
    apply_fielder_acquisition_role_mods(values, archetype, position_style, acquisition_role)
    apply_fielder_weakness_profile(rng, values, weakness_profile)
    apply_fielder_variance(rng, values, category, development_stage)
    apply_fielder_growth_mods(values, age, growth_type, archetype, position_style)
    finalize_fielder_values(rng, values, category, age, position, player_class, archetype, position_style, allow_foreign_allrounder)
    result = ability_values(values)
    result["弾道"] = determine_trajectory(values["パワー"], archetype, position, position_style)
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


def pitcher_age_mods(age: int, archetype: str, player_class: str) -> dict[str, int]:
    mods = {
        "球速": curve_delta(age, [(18, 0), (22, 2), (28, 4), (34, 0), (36, -2), (39, -5)]),
        "コントロール": curve_delta(age, [(18, -8), (21, -4), (29, 4), (35, 6), (36, 3)]),
        "スタミナ": curve_delta(age, [(18, -5), (23, 0), (30, 5), (34, 0), (36, -5)]),
    }
    if player_class == "ベテラン型" or (age >= 34 and archetype in {"制球", "変化球"}):
        mods["球速"] -= 2
        mods["コントロール"] += 3
    return mods


def apply_pitcher_growth_mods(values: dict[str, int], age: int, growth_type: str, archetype: str) -> None:
    base = growth_age_delta(age, growth_type)
    if base >= 0:
        weights = {"球速": 0.35, "コントロール": 0.8, "スタミナ": 0.9}
        if archetype == "速球":
            weights["球速"] += 0.15
        if archetype == "制球":
            weights["コントロール"] += 0.25
        if archetype == "スタミナ":
            weights["スタミナ"] += 0.25
    else:
        weights = {"球速": 0.28, "コントロール": 0.55, "スタミナ": 0.9}
    values["球速"] += round(base * weights["球速"])
    values["コントロール"] += round(base * weights["コントロール"])
    values["スタミナ"] += round(base * weights["スタミナ"])


def apply_pitcher_player_class_mods(values: dict[str, int], category: str, player_class: str) -> None:
    mods = {
        "架空球団用": {
            "スター級": {"球速": 4, "コントロール": 10, "スタミナ": 8},
            "一軍主力級": {"球速": 2, "コントロール": 5, "スタミナ": 4},
            "一軍控え級": {"球速": 0, "コントロール": 0, "スタミナ": 0},
            "二軍級": {"球速": -2, "コントロール": -12, "スタミナ": -8},
            "若手素材型": {"球速": 4, "コントロール": -13, "スタミナ": -6},
            "ベテラン型": {"球速": -4, "コントロール": 2, "スタミナ": -3},
        },
        "ドラフト候補用": {
            "超上位候補": {"球速": 4, "コントロール": 4, "スタミナ": 3},
            "上位候補": {"球速": 2, "コントロール": 1, "スタミナ": 1},
            "中位候補": {"球速": 0, "コントロール": -3, "スタミナ": -2},
            "下位候補": {"球速": -2, "コントロール": -7, "スタミナ": -5},
            "育成候補": {"球速": -1, "コントロール": -10, "スタミナ": -7},
        },
        "助っ人外国人用": {
            "大物実績者": {"球速": 3, "コントロール": 8, "スタミナ": 5},
            "主力期待級": {"球速": 2, "コントロール": 4, "スタミナ": 2},
            "レギュラー競争級": {"球速": 1, "コントロール": -1, "スタミナ": -1},
            "保険・バックアップ級": {"球速": -2, "コントロール": -7, "スタミナ": -5},
            "育成素材型": {"球速": 1, "コントロール": -10, "スタミナ": -8},
            "再生候補": {"球速": -4, "コントロール": 0, "スタミナ": -4},
        },
    }
    add_mod(values, mods.get(category, {}).get(player_class, {}))


def apply_pitcher_archetype_mods(rng: random.Random, values: dict[str, int], archetype: str, role: str) -> None:
    if archetype == "総合":
        add_mod(values, {"球速": rng.randint(0, 2), "コントロール": rng.randint(2, 5), "スタミナ": rng.randint(1, 4)})
    elif archetype == "制球":
        add_mod(values, {"球速": -rng.randint(1, 4), "コントロール": rng.randint(8, 14)})
    elif archetype == "速球":
        add_mod(values, {"球速": rng.randint(4, 8), "コントロール": -rng.randint(3, 8)})
    elif archetype == "変化球":
        add_mod(values, {"球速": -rng.randint(1, 4), "コントロール": rng.randint(0, 3)})
    elif archetype == "スタミナ" and role != "抑え":
        add_mod(values, {"スタミナ": rng.randint(10, 16)})


def apply_pitcher_role_mods(values: dict[str, int], role: str, position_style: str) -> None:
    if role == "先発":
        add_mod(values, {"球速": -1, "コントロール": 2, "スタミナ": 11})
    elif role == "中継ぎ":
        add_mod(values, {"球速": 2, "コントロール": -2, "スタミナ": -8})
    elif role == "抑え":
        add_mod(values, {"球速": 3, "コントロール": -1, "スタミナ": -14})
    if position_style == "ロングリリーフ型":
        add_mod(values, {"球速": -1, "コントロール": 2, "スタミナ": 7})


def apply_pitcher_development_mods(rng: random.Random, values: dict[str, int], development_stage: str, archetype: str) -> None:
    if development_stage == "素材型":
        if archetype == "変化球":
            values["球速"] -= rng.randint(1, 3)
        else:
            values["球速"] += rng.randint(1, 4)
        values["コントロール"] -= rng.randint(5, 10)
        values["スタミナ"] -= rng.randint(1, 4)
    elif development_stage == "即戦力型":
        values["コントロール"] += rng.randint(4, 8)
        values["スタミナ"] += rng.randint(2, 5)
        values["球速"] -= rng.randint(0, 2)


def apply_pitcher_acquisition_role_mods(values: dict[str, int], acquisition_role: str) -> None:
    if acquisition_role == "先発候補":
        add_mod(values, {"コントロール": 3, "スタミナ": 5})
    elif acquisition_role == "勝ちパターン候補":
        add_mod(values, {"球速": 2, "コントロール": 1, "スタミナ": -4})
    elif acquisition_role == "クローザー候補":
        add_mod(values, {"球速": 3, "スタミナ": -8})
    elif acquisition_role == "ロングリリーフ":
        add_mod(values, {"コントロール": 2, "スタミナ": 7})
    elif acquisition_role == "若手育成":
        add_mod(values, {"球速": 1, "コントロール": -5, "スタミナ": -3})
    elif acquisition_role == "再生候補":
        add_mod(values, {"球速": -3, "コントロール": 1, "スタミナ": -4})


def apply_pitcher_weakness_profile(rng: random.Random, values: dict[str, int], weakness_profile: str) -> None:
    if weakness_profile == "低制球":
        values["コントロール"] -= rng.randint(10, 18)
    elif weakness_profile == "スタミナ不足":
        values["スタミナ"] -= rng.randint(10, 18)
    elif weakness_profile == "球速不足":
        values["球速"] -= rng.randint(4, 8)
    elif weakness_profile == "安定性不安":
        values["コントロール"] -= rng.randint(3, 7)


def apply_pitcher_variance(rng: random.Random, values: dict[str, int], category: str, development_stage: str, weakness_profile: str) -> None:
    speed_spread = 3 if category != "助っ人外国人用" else 4
    ability_spread = 10 if category != "架空球団用" else 8
    if development_stage == "素材型" or weakness_profile == "安定性不安":
        ability_spread += 4
    elif development_stage == "即戦力型":
        ability_spread = max(6, ability_spread - 3)
    values["球速"] += rng.randint(-speed_spread, speed_spread)
    values["コントロール"] += rng.randint(-ability_spread, ability_spread)
    values["スタミナ"] += rng.randint(-ability_spread, ability_spread)


def pitcher_fastball_allowed(category: str, age: int, player_class: str, archetype: str, position_style: str, weakness_profile: str) -> bool:
    return (
        player_class in {"スター級", "一軍主力級", "超上位候補", "大物実績者", "主力期待級"}
        and archetype == "速球"
        and (position_style in {"剛腕中継ぎ", "剛腕クローザー", "速球型先発"} or category != "架空球団用")
        and weakness_profile != "球速不足"
        and player_class not in {"二軍級", "ベテラン型"}
        and age < 35
    )


def finalize_pitcher_values(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    player_class: str,
    archetype: str,
    position_style: str,
    role: str,
    weakness_profile: str,
) -> None:
    if archetype == "速球":
        values["球速"] = floor_value(rng, values["球速"], 145)
    elif archetype == "制球":
        values["コントロール"] = floor_value(rng, values["コントロール"], 50)
    elif archetype == "スタミナ" and role != "抑え":
        values["スタミナ"] = floor_value(rng, values["スタミナ"], 55)
    if role == "抑え":
        values["スタミナ"] = cap_value(rng, values["スタミナ"], 69)
    if player_class in {"二軍級", "保険・バックアップ級"}:
        values["球速"] = cap_value(rng, values["球速"], 154)
        values["コントロール"] = cap_value(rng, values["コントロール"], 79)
        values["スタミナ"] = cap_value(rng, values["スタミナ"], 79)
    if player_class == "二軍級":
        values["スタミナ"] = cap_value(rng, values["スタミナ"], 74)
    if category == "ドラフト候補用" and age <= 19:
        if player_class == "超上位候補" and archetype == "速球" and rng.random() < 0.05:
            values["球速"] = cap_value(rng, values["球速"], rng.randint(155, 158))
        else:
            values["球速"] = cap_value(rng, values["球速"], 154)
        values["コントロール"] = cap_value(rng, values["コントロール"], 79)
        values["スタミナ"] = cap_value(rng, values["スタミナ"], 79)
    if values["球速"] >= 160 and not pitcher_fastball_allowed(category, age, player_class, archetype, position_style, weakness_profile):
        values["球速"] = cap_value(rng, values["球速"], rng.randint(154, 159) if archetype == "速球" and player_class not in {"二軍級", "ベテラン型"} else rng.randint(149, 154))
    if category == "助っ人外国人用" and values["球速"] >= 160 and rng.random() < 0.35:
        values["球速"] = rng.randint(156, 159)
    if category == "架空球団用" and values["球速"] >= 160 and rng.random() < 0.45:
        values["球速"] = rng.randint(157, 159)
    if archetype in {"制球", "変化球", "スタミナ"} or player_class == "ベテラン型" or age >= 35:
        values["球速"] = cap_value(rng, values["球速"], 159)
    if age >= 35:
        values["球速"] = cap_value(rng, values["球速"], 156)
        values["スタミナ"] -= rng.randint(0, 3)
    if values["球速"] >= 155 and values["コントロール"] >= 70:
        values["コントロール"] = rng.randint(60, 69) if archetype != "制球" else values["コントロール"]
    values["球速"] = clamp(values["球速"], 125, 165)
    values["コントロール"] = clamp(values["コントロール"])
    values["スタミナ"] = clamp(values["スタミナ"])


def audit_pitcher_values(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    player_class: str,
    archetype: str,
    position_style: str,
    role: str,
    weakness_profile: str,
) -> None:
    finalize_pitcher_values(rng, values, category, age, player_class, archetype, position_style, role, weakness_profile)


def shape_pitcher_speed_distribution(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    player_class: str,
    archetype: str,
    position_style: str,
    weakness_profile: str,
) -> None:
    if category != "架空球団用" or values["球速"] < 155:
        return
    if values["球速"] >= 160:
        return
    if not pitcher_fastball_allowed(category, age, player_class, archetype, position_style, weakness_profile):
        if rng.random() < 0.65:
            values["球速"] = rng.randint(149, 154)
        return
    if archetype != "速球" and rng.random() < 0.35:
        values["球速"] = rng.randint(151, 154)


def apply_fictional_pitcher_age_speed_shape(
    rng: random.Random,
    values: dict[str, int],
    category: str,
    age: int,
    player_class: str,
    archetype: str,
    position_style: str,
    weakness_profile: str,
) -> None:
    if category != "架空球団用":
        return
    fastball_allowed = pitcher_fastball_allowed(category, age, player_class, archetype, position_style, weakness_profile)
    if age <= 21:
        if fastball_allowed:
            values["球速"] -= rng.choice([0, 0, 1])
        elif archetype == "速球":
            values["球速"] -= rng.randint(1, 2)
        elif player_class in {"二軍級", "若手素材型"}:
            values["球速"] -= rng.choice([0, 1, 2]) if archetype == "速球" else rng.randint(1, 3)
        elif archetype in {"制球", "変化球", "スタミナ"}:
            values["球速"] -= rng.randint(2, 4)
        else:
            values["球速"] -= rng.randint(2, 4)
    elif age >= 35:
        if player_class in {"スター級", "一軍主力級"} or archetype == "速球":
            values["球速"] += weighted_choice(rng, [(0, 35), (1, 35), (2, 22), (3, 8)])
        elif archetype in {"制球", "変化球"}:
            values["球速"] += weighted_choice(rng, [(0, 45), (1, 40), (2, 15)])
        if age >= 39:
            values["球速"] -= rng.randint(1, 3)


def generate_pitcher_abilities(
    rng: random.Random,
    age: int,
    player_type: str,
    category: str,
    aptitudes: dict[str, str],
    *,
    player_class: str = "",
    archetype: str = "",
    position_style: str = "",
    development_stage: str = "",
    acquisition_role: str = "",
    weakness_profile: str = "",
    growth_type: str = "normal",
) -> dict[str, Any]:
    archetype = archetype or legacy_archetype_from_player_type("投手", player_type) or "総合"
    player_class = player_class or "一軍控え級"
    role = primary_pitcher_role(aptitudes)
    position_style = position_style or PITCHER_POSITION_STYLE_BY_ROLE.get(role, {}).get(archetype, "")
    values = {"球速": 145, "コントロール": 48, "スタミナ": 48}
    add_mod(values, pitcher_age_mods(age, archetype, player_class))
    apply_pitcher_player_class_mods(values, category, player_class)
    if category == "架空球団用":
        values["球速"] += 8
        if player_class in {"スター級", "一軍主力級"}:
            values["コントロール"] += 1
        elif player_class in {"二軍級", "若手素材型"}:
            values["コントロール"] -= 2
    apply_pitcher_archetype_mods(rng, values, archetype, role)
    apply_pitcher_role_mods(values, role, position_style)
    apply_pitcher_development_mods(rng, values, development_stage, archetype)
    apply_pitcher_acquisition_role_mods(values, acquisition_role)
    apply_pitcher_weakness_profile(rng, values, weakness_profile)
    apply_pitcher_variance(rng, values, category, development_stage, weakness_profile)
    apply_pitcher_growth_mods(values, age, growth_type, archetype)
    apply_fictional_pitcher_age_speed_shape(rng, values, category, age, player_class, archetype, position_style, weakness_profile)
    shape_pitcher_speed_distribution(rng, values, category, age, player_class, archetype, position_style, weakness_profile)
    finalize_pitcher_values(rng, values, category, age, player_class, archetype, position_style, role, weakness_profile)
    return {"球速": f"{values['球速']} km/h", "コントロール": ability(values["コントロール"]), "スタミナ": ability(values["スタミナ"]), **aptitudes}


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

def second_pitch_chance(
    player_type: str,
    category: str,
    aptitudes: dict[str, str],
    *,
    age: int | None = None,
    player_class: str = "",
    archetype: str = "",
    development_stage: str = "",
    acquisition_role: str = "",
) -> float:
    archetype = archetype or legacy_archetype_from_player_type("投手", player_type)
    if category == "ドラフト候補用":
        chance = 0.10
    elif category == "助っ人外国人用":
        chance = 0.42
    else:
        chance = 0.28
    if aptitudes.get("starter_aptitude") == "◎":
        chance += 0.03
    if aptitudes.get("closer_aptitude") == "◎":
        chance -= 0.04
    if archetype in {"変化球", "制球"}:
        chance += 0.08
    if player_class in {"スター級", "一軍主力級", "大物実績者"}:
        chance += 0.04
    if player_class in {"二軍級", "育成候補"}:
        chance -= 0.08
    if development_stage == "素材型":
        chance -= 0.08
    elif development_stage == "即戦力型":
        chance += 0.05
    if acquisition_role in {"先発候補", "再生候補"}:
        chance += 0.03
    if age is not None and age <= 19:
        chance -= 0.08
    return max(0.02, min(0.58, chance))


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


def pitch_count_weights(
    player_type: str,
    category: str,
    aptitudes: dict[str, str],
    *,
    age: int | None = None,
    player_class: str = "",
    archetype: str = "",
    development_stage: str = "",
    weakness_profile: str = "",
) -> list[tuple[int, int]]:
    archetype = archetype or legacy_archetype_from_player_type("投手", player_type)
    role = primary_pitcher_role(aptitudes)
    if category == "ドラフト候補用":
        if age is not None and age <= 19:
            weights = {2: 70, 3: 30, 4: 0}
        elif age is not None and age <= 21:
            weights = {2: 55, 3: 44, 4: 1}
        else:
            weights = {2: 38, 3: 58, 4: 4}
    elif category == "助っ人外国人用":
        weights = {2: 36, 3: 57, 4: 7}
    else:
        if age is not None and age <= 19:
            weights = {2: 70, 3: 29, 4: 1}
        elif age is not None and age <= 22:
            weights = {2: 55, 3: 44, 4: 1}
        elif age is not None and age <= 29:
            weights = {2: 42, 3: 55, 4: 3}
        else:
            weights = {2: 49, 3: 49, 4: 2}
    if role == "先発":
        if category == "架空球団用":
            weights[2] -= 6; weights[3] += 4; weights[4] += 2
        else:
            weights[2] -= 8; weights[3] += 6; weights[4] += 2
    elif role in {"中継ぎ", "抑え"}:
        if category == "架空球団用":
            weights[2] += 9; weights[3] -= 6; weights[4] -= 3
        else:
            weights[2] += 8; weights[3] -= 6; weights[4] -= 2
    if archetype == "変化球":
        if category == "架空球団用":
            weights[2] -= 8; weights[3] += 7; weights[4] += 1
        else:
            weights[2] -= 10; weights[3] += 7; weights[4] += 3
    elif archetype == "速球":
        weights[2] += 8; weights[3] -= 6; weights[4] -= 2
    if development_stage == "素材型":
        weights[2] += 10; weights[3] -= 8; weights[4] -= 2
    elif development_stage == "即戦力型":
        weights[2] -= 5; weights[3] += 4; weights[4] += 1
    if weakness_profile == "球種不足":
        weights = {2: 100, 3: 0, 4: 0}
    if player_class in {"スター級", "大物実績者"} and role == "先発":
        weights[4] += 1 if category == "架空球団用" else 2
    return [(count, max(0, weight)) for count, weight in weights.items() if weight > 0]


def movement_weights(player_type: str, category: str, aptitudes: dict[str, str], count: int, *, archetype: str = "", weakness_profile: str = "") -> list[tuple[int, int]]:
    archetype = archetype or legacy_archetype_from_player_type("投手", player_type)
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
    if archetype == "変化球":
        weights[1] -= 3; weights[2] -= 2; weights[4] += 3; weights[5] += 2
    if weakness_profile in {"変化量不足", "球種不足"}:
        weights[1] += 6; weights[2] += 5; weights[4] -= 5; weights[5] -= 3
    return [(level, max(1, weight)) for level, weight in weights.items()]


def weighted_direction_sample(rng: random.Random, direction_codes: list[str], count: int) -> list[str]:
    remaining = list(direction_codes)
    selected: list[str] = []
    for _ in range(min(count, len(remaining))):
        code = weighted_choice(rng, [(code, DIRECTION_SELECTION_WEIGHTS.get(code, 1)) for code in remaining])
        selected.append(code)
        remaining.remove(code)
    return selected


def target_total_movement(rng: random.Random, category: str, age: int | None, role: str, player_class: str, archetype: str, development_stage: str, acquisition_role: str, weakness_profile: str, count: int) -> int:
    if category == "ドラフト候補用":
        if age is not None and age <= 19:
            low, high = 3, 6
        elif age is not None and age <= 21:
            low, high = 4, 8
        else:
            low, high = 5, 9
    elif category == "助っ人外国人用":
        if role == "先発":
            low, high = (8, 11) if archetype == "変化球" else (6, 10)
        elif role == "抑え":
            low, high = 4, 8
        else:
            low, high = 5, 8
        if player_class == "育成素材型":
            low, high = 3, 6
    else:
        if age is not None and age <= 19:
            low, high = 4, 6
            if player_class in {"スター級", "一軍主力級"} or archetype == "変化球":
                high = 8
        elif age is not None and age <= 22:
            low, high = 4, 7
        elif age is not None and age <= 29:
            low, high = 5, 9
        else:
            low, high = 5, 9
    if archetype == "変化球":
        low += 1; high += 2
    elif archetype == "速球":
        high -= 1
    if category == "架空球団用" and player_class in {"二軍級", "若手素材型"}:
        high -= 1
    if development_stage == "素材型":
        high -= 1
    elif development_stage == "即戦力型":
        low += 1
    if weakness_profile in {"変化量不足", "球種不足"}:
        low -= 2; high -= 3
    target = rng.randint(max(count, low), max(count, high))
    if category == "ドラフト候補用" and age is not None and age <= 19:
        target = min(target, 7)
    return max(count, target)


def normalize_primary_movements(rng: random.Random, balls: list[dict[str, Any]], target: int) -> None:
    primary = [ball for ball in balls if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")]
    if not primary:
        return
    target = max(len(primary), target)
    for ball in primary:
        ball["movement"] = ball["level"] = max(1, min(int(BREAKING_BY_NAME[ball["name"]].get("max_movement", 5)), target // len(primary)))
    attempts = 0
    while sum(pitch_movement(ball) for ball in primary) < target and attempts < 40:
        ball = rng.choice(primary)
        max_mv = int(BREAKING_BY_NAME[ball["name"]].get("max_movement", 5))
        if ball["movement"] < max_mv:
            ball["movement"] += 1
            ball["level"] = ball["movement"]
        attempts += 1
    while sum(pitch_movement(ball) for ball in primary) > target and attempts < 80:
        ball = rng.choice(primary)
        min_mv = int(BREAKING_BY_NAME[ball["name"]].get("min_movement", 1))
        if ball["movement"] > min_mv:
            ball["movement"] -= 1
            ball["level"] = ball["movement"]
        attempts += 1


def generate_breaking_balls(
    rng: random.Random,
    player_type: str,
    category: str,
    aptitudes: dict[str, str],
    batting_throwing: str,
    *,
    age: int | None = None,
    player_class: str = "",
    archetype: str = "",
    position_style: str = "",
    development_stage: str = "",
    acquisition_role: str = "",
    weakness_profile: str = "",
) -> list[dict[str, Any]]:
    archetype = archetype or legacy_archetype_from_player_type("投手", player_type)
    role = primary_pitcher_role(aptitudes)
    count = weighted_choice(rng, pitch_count_weights(player_type, category, aptitudes, age=age, player_class=player_class, archetype=archetype, development_stage=development_stage, weakness_profile=weakness_profile))
    if category == "ドラフト候補用" and age is not None and age <= 19:
        count = min(count, 3)
    if category == "架空球団用" and age is not None and age <= 19 and count == 4 and rng.random() < 0.65:
        count = 3
    if category == "架空球団用" and count == 4:
        if role in {"中継ぎ", "抑え"} and rng.random() < 0.88:
            count = 3
        elif not (role == "先発" and player_class == "スター級") and rng.random() < 0.55:
            count = 3
    if weakness_profile == "球種不足":
        count = min(count, 2)
    direction_codes = [code for code in DIRECTION_NAMES if any(ball["direction_code"] == code and ball["name"] in allowed_pitch_names_for_generation(code, batting_throwing) for ball in BREAKING_BALL_MASTER)]
    primary_codes = weighted_direction_sample(rng, direction_codes, count)
    balls: list[dict[str, Any]] = []
    for direction_code in primary_codes:
        name = weighted_breaking_names(rng, direction_code, player_type, category, batting_throwing)
        movement = weighted_choice(rng, movement_weights(player_type, category, aptitudes, count, archetype=archetype, weakness_profile=weakness_profile))
        balls.append(make_breaking_ball(name, movement, False, 1))
    target = target_total_movement(rng, category, age, role, player_class, archetype, development_stage, acquisition_role, weakness_profile, count)
    normalize_primary_movements(rng, balls, target)
    chance = second_pitch_chance(player_type, category, aptitudes, age=age, player_class=player_class, archetype=archetype, development_stage=development_stage, acquisition_role=acquisition_role)
    if category == "助っ人外国人用" and len(balls) == 3:
        chance = min(chance, 0.07)
    elif category == "架空球団用" and len(balls) == 3:
        if role in {"中継ぎ", "抑え"}:
            chance = min(chance, 0.020)
        else:
            chance = min(chance, 0.035)
    elif len(balls) >= 4:
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
    if second_fastball and category == "架空球団用" and len(primary_breaking_balls(balls)) >= 3:
        has_second_breaking = any(ball.get("kind") == "breaking" and ball.get("is_second_pitch") for ball in balls)
        if role in {"中継ぎ", "抑え"} and (has_second_breaking or rng.random() < 0.90):
            second_fastball = None
        elif role == "先発" and rng.random() < (0.72 if has_second_breaking else 0.58):
            second_fastball = None
        elif has_second_breaking and rng.random() < 0.80:
            second_fastball = None
    if second_fastball:
        balls.append(second_fastball)
    return balls


def primary_breaking_balls(breaking_balls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ball for ball in breaking_balls if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")]


def primary_total_movement(breaking_balls: list[dict[str, Any]]) -> int:
    return sum(pitch_movement(ball) for ball in primary_breaking_balls(breaking_balls))


def reduce_primary_total_movement(rng: random.Random, breaking_balls: list[dict[str, Any]], maximum: int) -> None:
    primary = primary_breaking_balls(breaking_balls)
    attempts = 0
    while sum(pitch_movement(ball) for ball in primary) > maximum and attempts < 80:
        candidates = [ball for ball in primary if pitch_movement(ball) > int(BREAKING_BY_NAME[ball["name"]].get("min_movement", 1))]
        if not candidates:
            break
        ball = rng.choice(candidates)
        ball["movement"] -= 1
        ball["level"] = ball["movement"]
        attempts += 1


def remove_extra_primary_pitches(breaking_balls: list[dict[str, Any]], maximum_count: int) -> None:
    while len(primary_breaking_balls(breaking_balls)) > maximum_count:
        primary = primary_breaking_balls(breaking_balls)
        removable = min(primary, key=lambda ball: (pitch_movement(ball), str(ball.get("direction_code", ""))))
        breaking_balls[:] = [ball for ball in breaking_balls if ball is not removable and not (ball.get("is_second_pitch") and ball.get("direction_code") == removable.get("direction_code"))]


def set_pitcher_speed(abilities: dict[str, Any], speed: int) -> None:
    abilities["球速"] = f"{clamp(speed, 125, 165)} km/h"


def audit_generated_player(
    rng: random.Random,
    role: str,
    category: str,
    age: int,
    position: str,
    player_class: str,
    archetype: str,
    position_style: str,
    development_stage: str,
    acquisition_role: str,
    weakness_profile: str,
    abilities: dict[str, Any],
    breaking_balls: list[dict[str, Any]],
    allow_foreign_allrounder: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if role == "野手":
        values = {key: int(ability_numeric_value(abilities, key) or 0) for key in FIELDER_ABILITY_KEYS}
        audit_fielder_values(rng, values, category, age, position, player_class, archetype, position_style, allow_foreign_allrounder)
        audited = ability_values(values)
        audited["弾道"] = determine_trajectory(values["パワー"], archetype, position, position_style)
        return {**abilities, **audited}, breaking_balls

    speed = pitcher_speed_value(abilities) or 145
    control = int(ability_numeric_value(abilities, "コントロール") or 0)
    stamina = int(ability_numeric_value(abilities, "スタミナ") or 0)
    role_name = primary_pitcher_role({key: abilities.get(key) for key in PITCHER_APTITUDE_KEYS})
    if archetype == "スタミナ" and role_name == "抑え":
        stamina = min(stamina, 64)
    if archetype == "速球" and speed < 145:
        speed = 145 + rng.randint(0, 3)
    if archetype == "制球" and control < 50:
        control = 50 + rng.randint(0, 5)
    if archetype == "変化球" and primary_total_movement(breaking_balls) < 5:
        normalize_primary_movements(rng, breaking_balls, 5)
    if archetype == "スタミナ" and role_name != "抑え" and stamina < 55:
        stamina = 55 + rng.randint(0, 6)
    if weakness_profile == "球種不足":
        remove_extra_primary_pitches(breaking_balls, 2)
        reduce_primary_total_movement(rng, breaking_balls, 5)
    if category == "ドラフト候補用" and age <= 19:
        remove_extra_primary_pitches(breaking_balls, 3)
        reduce_primary_total_movement(rng, breaking_balls, 7)
        speed = min(speed, 158 if player_class == "超上位候補" and archetype == "速球" else 154)
    if player_class == "二軍級":
        speed = min(speed, 154)
        reduce_primary_total_movement(rng, breaking_balls, 8)
    if player_class == "保険・バックアップ級":
        control = min(control, 79)
        stamina = min(stamina, 79)
    if role_name == "抑え":
        stamina = min(stamina, 69)
    if not pitcher_fastball_allowed(category, age, player_class, archetype, position_style, weakness_profile):
        speed = min(speed, 159)
    if archetype in {"変化球", "制球", "スタミナ"} or player_class == "ベテラン型" or age >= 35:
        speed = min(speed, 159)
    total = primary_total_movement(breaking_balls)
    if speed >= 155 and control >= 70 and total >= 9:
        if archetype == "制球":
            speed = rng.randint(149, 154)
        else:
            control = rng.randint(60, 69)
    set_pitcher_speed(abilities, speed)
    abilities["コントロール"] = ability(control)
    abilities["スタミナ"] = ability(stamina)
    return abilities, breaking_balls

FOREIGN_NATIONS = ["アメリカ", "ドミニカ共和国", "ベネズエラ", "キューバ", "メキシコ", "韓国", "台湾"]


def normalize_japanese_prefecture_name(value: Any) -> str:
    text = str(value or "").strip()
    return JAPANESE_PREFECTURE_ALIASES.get(text, text)


@lru_cache(maxsize=1)
def load_japanese_surname_master(csv_path: str | None = None) -> dict[str, dict[str, tuple[Any, ...]]]:
    path = Path(csv_path) if csv_path else JAPANESE_SURNAME_PATH
    if not path.exists():
        raise FileNotFoundError(f"苗字CSVが見つかりません: {path}")

    required_columns = ["place", "surname", "number"]
    header = pd.read_csv(path, encoding="utf-8-sig", nrows=0)
    if list(header.columns) != required_columns:
        raise ValueError(f"苗字CSVの列が不正です: {list(header.columns)}")

    df = pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype={"place": "string", "surname": "string"},
    )
    df["place"] = df["place"].astype("string").str.strip()
    df["surname"] = df["surname"].astype("string").str.strip()
    df["number"] = pd.to_numeric(df["number"], errors="coerce")

    if df["place"].isna().any() or df["place"].eq("").any():
        raise ValueError("placeに欠損値があります")
    if df["surname"].isna().any() or df["surname"].eq("").any():
        raise ValueError("surnameに欠損値があります")
    if df["number"].isna().any():
        raise ValueError("numberに欠損値があります")
    if (df["number"] <= 0).any():
        raise ValueError("numberに0以下の値があります")
    if (df["number"] % 1 != 0).any():
        raise ValueError("numberに整数ではない値があります")

    invalid_patterns = ["?", "？", "※希望により削除"]
    for pattern in invalid_patterns:
        if df["surname"].str.contains(pattern, regex=False).any():
            raise ValueError(f"使用できない苗字表記が含まれています: {pattern}")

    expected_prefectures = set(JAPANESE_PREFECTURE_WEIGHTS)
    csv_prefectures = set(df["place"].astype(str))
    missing_prefectures = sorted(expected_prefectures - csv_prefectures)
    unknown_prefectures = sorted(csv_prefectures - expected_prefectures)
    if missing_prefectures:
        raise ValueError(f"苗字CSVに存在しない都道府県があります: {', '.join(missing_prefectures)}")
    if unknown_prefectures:
        raise ValueError(f"苗字CSVに想定外の都道府県表記があります: {', '.join(unknown_prefectures)}")

    df["number"] = df["number"].astype(int)
    master: dict[str, dict[str, tuple[Any, ...]]] = {}
    for prefecture, group in df.groupby("place", sort=False, observed=True):
        if group.empty:
            raise ValueError(f"都道府県内に有効な苗字がありません: {prefecture}")
        master[str(prefecture)] = {
            "surnames": tuple(group["surname"].astype(str)),
            "weights": tuple(group["number"].astype(int)),
        }

    empty_prefectures = [prefecture for prefecture in JAPANESE_PREFECTURE_WEIGHTS if not master.get(prefecture, {}).get("surnames")]
    if empty_prefectures:
        raise ValueError(f"都道府県内に有効な苗字がありません: {', '.join(empty_prefectures)}")
    return master


def choose_japanese_prefecture(rng: random.Random) -> str:
    prefectures = list(JAPANESE_PREFECTURE_WEIGHTS)
    weights = [JAPANESE_PREFECTURE_WEIGHTS[prefecture] for prefecture in prefectures]
    return rng.choices(prefectures, weights=weights, k=1)[0]


def choose_japanese_surname(prefecture: str, rng: random.Random, surname_master: dict[str, dict[str, tuple[Any, ...]]] | None = None) -> str:
    normalized_prefecture = normalize_japanese_prefecture_name(prefecture)
    master = surname_master if surname_master is not None else load_japanese_surname_master()
    prefecture_data = master.get(normalized_prefecture)
    if not prefecture_data:
        raise KeyError(f"苗字マスタに都道府県がありません: {normalized_prefecture}")
    return str(rng.choices(prefecture_data["surnames"], weights=prefecture_data["weights"], k=1)[0])


def choose_japanese_name(rng: random.Random, names: dict[str, Any], prefecture: str, surname_master: dict[str, dict[str, tuple[Any, ...]]] | None = None) -> str:
    entry = names.get("日本")
    if not isinstance(entry, dict) or not entry.get("名"):
        raise ValueError("日本人名マスタに名がありません")
    surname = choose_japanese_surname(prefecture, rng, surname_master)
    given_name = str(rng.choice(entry["名"]))
    return f"{surname} {given_name}"


def choose_japanese_identity(rng: random.Random, names: dict[str, Any], surname_master: dict[str, dict[str, tuple[Any, ...]]] | None = None) -> tuple[str, str]:
    prefecture = choose_japanese_prefecture(rng)
    return choose_japanese_name(rng, names, prefecture, surname_master), prefecture


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
    if nationality == "日本":
        return choose_japanese_prefecture(rng)
    return rng.choice(places.get(nationality) or places["日本"])


def choose_profile_birthplace(rng: random.Random, places: dict[str, list[str]], nationality: str, actual_nationality: str = "") -> str:
    candidates = places.get(nationality)
    if candidates:
        return rng.choice(candidates)
    if nationality and nationality != "その他":
        return nationality
    return actual_nationality or nationality or rng.choice(places["日本"])


def fallback_skin_color(seed: int, nationality: str, name: str) -> int:
    skin_rng = random.Random(f"skin:{seed}:{nationality}:{name}")
    if nationality in FOREIGN_NATIONS:
        weights = [(1, 24), (2, 30), (3, 28), (4, 13), (5, 4), (6, 1)]
    else:
        weights = [(1, 8), (2, 28), (3, 42), (4, 17), (5, 4), (6, 1)]
    return int(weighted_choice(skin_rng, weights))


def name_matches_entry(name: str, entry: Any) -> bool:
    if isinstance(entry, dict):
        surnames = entry.get("姓", [])
        given_names = entry.get("名", [])
        return any(name.startswith(f"{surname} ") for surname in surnames) and any(name.endswith(f" {given}") for given in given_names)
    if isinstance(entry, list):
        return name in entry
    return False


def japanese_name_matches_surname_master(name: str, master: MasterData, birthplace: str | None = None) -> bool:
    entry = master.names.get("日本")
    if not isinstance(entry, dict):
        return False
    parts = str(name or "").split()
    if len(parts) != 2 or parts[1] not in entry.get("名", []):
        return False

    surname = parts[0]
    surname_master = load_japanese_surname_master()
    if birthplace:
        prefecture = normalize_japanese_prefecture_name(birthplace)
        prefecture_data = surname_master.get(prefecture)
        return bool(prefecture_data and surname in prefecture_data["surnames"])
    return any(surname in prefecture_data["surnames"] for prefecture_data in surname_master.values())


def classify_name_type(name: str, master: MasterData, nationality: str | None = None, birthplace: str | None = None) -> str:
    if nationality and name_matches_entry(name, master.names.get(nationality)):
        return nationality
    if nationality == "日本" and japanese_name_matches_surname_master(name, master, birthplace):
        return "日本"

    matched_nations = [nation for nation, entry in master.names.items() if name_matches_entry(name, entry)]
    if not matched_nations:
        return "不明"
    if len(matched_nations) > 1:
        return "複数国該当"
    return matched_nations[0]


def classify_birthplace_type(birthplace: str, master: MasterData) -> str:
    normalized_birthplace = normalize_japanese_prefecture_name(birthplace)
    for nation, places in master.places.items():
        if birthplace in places or normalized_birthplace in places:
            return nation
    return "不明"


SUB_POSITION_LABELS = ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"]
SUB_POSITION_FIELDING_RATES = {"◎": 1.00, "○": 0.80, "△": 0.70}
SUB_POSITION_APTITUDE_SYMBOLS = {3: "◎", 2: "○", 1: "△", "3": "◎", "2": "○", "1": "△"}
UTILITY_TYPES = {"守備職人", "俊足型", "バランス型", "強肩型"}

def normalize_sub_position_aptitude(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return SUB_POSITION_APTITUDE_SYMBOLS.get(max(1, min(3, int(value))), "△")
    text = str(value or "").strip().replace("〇", "○")
    return SUB_POSITION_APTITUDE_SYMBOLS.get(text, text if text in SUB_POSITION_FIELDING_RATES else "△")


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
            parts = [part.strip() for part in re.split(r"[/、,;；]", text) if part.strip()]
            return [{"position": (m.group(1).strip() if (m := re.match(r"(.+?)([◎○△])?$", part)) else part), "aptitude": normalize_sub_position_aptitude(m.group(2) if m and m.group(2) else "△")} for part in parts]
    if isinstance(value, dict):
        pos = str(value.get("position", "")).strip(); apt = normalize_sub_position_aptitude(value.get("aptitude", "△"))
        return [{"position": pos, "aptitude": apt}] if pos else []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                pos = str(item.get("position", "")).strip(); apt = normalize_sub_position_aptitude(item.get("aptitude", "△"))
                if pos in SUB_POSITION_LABELS: out.append({"position": pos, "aptitude": apt})
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

def normalize_aptitude_level(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, min(2, int(value)))
    text = str(value or "").strip().replace("－", "-")
    return {"◎": 2, "○": 1, "〇": 1, "2": 2, "1": 1, "0": 0, "-": 0, "": 0, "－－": 0}.get(text, 0)

normalize_pitcher_aptitude_level = normalize_aptitude_level

def normalize_fielding_aptitude_level(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, min(3, int(value)))
    text = str(value or "").strip().replace("－", "-")
    return {"◎": 3, "○": 2, "〇": 2, "△": 1, "3": 3, "2": 2, "1": 1, "0": 0, "-": 0, "": 0, "－－": 0}.get(text, 0)

def get_position_color_group(position: str) -> str | None:
    return POSITION_COLOR_GROUPS.get(str(position or "").strip())

def append_unique_limited(values: list[str], value: str | None, limit: int = 3) -> None:
    if value and value not in values and len(values) < limit:
        values.append(value)

def get_grouped_fielding_levels(player: dict[str, Any]) -> dict[str, int]:
    levels = {"catcher": 0, "infield": 0, "outfield": 0}
    if player.get("role") == "野手":
        main_group = get_position_color_group(str(player.get("position", "")))
        if main_group:
            levels[main_group] = max(levels[main_group], 3)
    for item in normalize_sub_positions(player.get("sub_positions")):
        group = get_position_color_group(item.get("position", ""))
        if group:
            levels[group] = max(levels[group], normalize_fielding_aptitude_level(item.get("aptitude")))
    return levels

def get_fielder_nameplate_colors(player: dict[str, Any]) -> list[str]:
    colors: list[str] = []
    main_group = get_position_color_group(str(player.get("position", "")))
    if not main_group:
        return colors
    append_unique_limited(colors, main_group)
    grouped_levels = get_grouped_fielding_levels(player)
    sub_groups = [
        (group, level)
        for group, level in grouped_levels.items()
        if group != main_group and level > 0
    ]
    sub_groups.sort(key=lambda item: (-item[1], NAMEPLATE_GROUP_PRIORITY[item[0]]))
    for group, _level in sub_groups:
        append_unique_limited(colors, group)
    return colors[:3]

def pitcher_aptitude_values(player: dict[str, Any]) -> dict[str, Any]:
    abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    values = {key: player.get(key) or abilities.get(key) for key in PITCHER_APTITUDE_KEYS}
    if not any(normalize_aptitude_level(value) for value in values.values()):
        pos = str(player.get("position", ""))
        values = {"starter_aptitude": "◎" if pos == "先発" else "-", "reliever_aptitude": "◎" if pos == "中継ぎ" else "-", "closer_aptitude": "◎" if pos == "抑え" else "-"}
    return values

def get_pitcher_nameplate_colors(player: dict[str, Any]) -> list[str]:
    colors: list[str] = []
    values = pitcher_aptitude_values(player)
    starter_level = normalize_aptitude_level(values.get("starter_aptitude"))
    relief_level = max(normalize_aptitude_level(values.get("reliever_aptitude")), normalize_aptitude_level(values.get("closer_aptitude")))
    if starter_level > 0 and relief_level > 0:
        colors.extend(["starter", "relief"] if starter_level >= relief_level else ["relief", "starter"])
    elif starter_level > 0:
        colors.append("starter")
    elif relief_level > 0:
        colors.append("relief")
    grouped_levels = get_grouped_fielding_levels(player)
    fielding_groups = [(group, level) for group, level in grouped_levels.items() if level > 0]
    if fielding_groups:
        fielding_groups.sort(key=lambda item: (-item[1], NAMEPLATE_GROUP_PRIORITY[item[0]]))
        append_unique_limited(colors, fielding_groups[0][0])
    return colors[:3]

def get_player_nameplate_colors(player: dict[str, Any]) -> list[str]:
    colors = get_pitcher_nameplate_colors(player) if player.get("role") == "投手" else get_fielder_nameplate_colors(player)
    deduped: list[str] = []
    for color in colors:
        append_unique_limited(deduped, color)
    return deduped[:3]

def nameplate_background_css(color_groups: list[str]) -> str:
    styles = [NAMEPLATE_COLOR_STYLES[group] for group in color_groups if group in NAMEPLATE_COLOR_STYLES]
    if not styles:
        return ""
    if len(styles) == 1:
        style = styles[0]
        return f"background:linear-gradient({style['top']},{style['bottom']});border-color:{style['border']};"
    count = len(styles)
    segment_width = 100 / count
    layers = []
    for index, style in enumerate(styles):
        position = 0 if index == 0 else 100 if index == count - 1 else 50
        layers.append(
            f"linear-gradient(180deg,{style['top']} 0%,{style['bottom']} 100%) "
            f"{position:.4f}% 0% / {segment_width:.4f}% 100% no-repeat"
        )
    border = styles[0]["border"]
    return f"background:{','.join(layers)};border-color:{border};"

def generate_sub_positions(rng: random.Random, role: str, position: str, player_type: str, category: str, age: int, batting_throwing: str, abilities: dict[str, Any], player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, acquisition_role: str | None = None) -> list[dict[str, str]]:
    if role != "野手": return []
    speed = ability_numeric_value(abilities, "走力") or 0; arm = ability_numeric_value(abilities, "肩力") or 0; field = ability_numeric_value(abilities, "守備力") or 0; catch = ability_numeric_value(abilities, "捕球") or 0; power = ability_numeric_value(abilities, "パワー") or 0
    has_rate = {"捕手": .50, "一塁手": .88, "二塁手": .94, "三塁手": .95, "遊撃手": .94, "外野手": .38}.get(position, .65)
    if category == "ドラフト候補用": has_rate -= .14
    if category == "助っ人外国人用": has_rate -= .24
    if player_type in {"守備職人", "俊足型", "バランス型"} or archetype in {"守備", "俊足", "バランス"}: has_rate += .08
    if player_class in {"一軍控え級", "レギュラー競争級", "保険・バックアップ級"}: has_rate += .08
    if acquisition_role in {"ユーティリティ", "保険要員", "内野守備補強", "外野補強"}: has_rate += .14
    if player_class in {"スター級", "大物実績者"}: has_rate -= .04
    if player_type == "長距離砲" and position in {"一塁手", "外野手"} or acquisition_role == "主砲候補": has_rate -= .10
    if rng.random() > max(.05, min(.98, has_rate)): return []
    weights = [(1, 30), (2, 62 if player_type in {"守備職人", "俊足型", "バランス型"} or age <= 23 else 52), (3, 25 if player_type in {"守備職人", "俊足型", "バランス型"} or age <= 23 else 16), (4, 5 if category == "架空球団用" else 1)]
    if category == "ドラフト候補用": weights = [(1, 56), (2, 34), (3, 8), (4, 2)]
    if category == "助っ人外国人用": weights = [(1, 64), (2, 30), (3, 5), (4, 1)]
    if position == "外野手" and player_type != "守備職人": weights = [(1, 70), (2, 27), (3, 3), (4, 1)]
    target = weighted_choice(rng, weights)
    # 3個以上は控え・ユーティリティ・若手経験者に寄せ、強打専任型の万能化を抑える。
    utility_condition = player_type in UTILITY_TYPES or acquisition_role == "ユーティリティ" or position_style in {"走攻守外野手", "守備走塁遊撃手", "守備走塁二塁手"}
    if target >= 3 and not utility_condition:
        target = 2
    if category == "ドラフト候補用" and age <= 19 and target >= 3:
        target = 2
    base = {"捕手": {"一塁手": 58, "外野手": 28, "三塁手": 14, "二塁手": 2}, "一塁手": {"三塁手": 42, "外野手": 40, "二塁手": 14, "捕手": 2}, "二塁手": {"三塁手": 34, "遊撃手": 28, "一塁手": 22, "外野手": 16, "捕手": 1}, "三塁手": {"一塁手": 38, "外野手": 30, "二塁手": 22, "遊撃手": 10}, "遊撃手": {"二塁手": 38, "三塁手": 36, "外野手": 18, "一塁手": 8}, "外野手": {"一塁手": 60, "三塁手": 22, "二塁手": 10, "捕手": 2, "遊撃手": 1}}.get(position, {})
    if category == "助っ人外国人用": base = {k: (v * 2 if k in {"一塁手", "三塁手", "外野手"} else max(1, v // 3)) for k, v in base.items()}
    def allowed(pos: str) -> bool:
        if pos == position: return False
        if batting_throwing.startswith("左投") and pos in {"二塁手", "三塁手", "遊撃手", "捕手"}: return False
        if pos == "遊撃手": return speed >= 55 and arm >= 55 and field >= 50 and catch >= 45 and (player_type in UTILITY_TYPES or acquisition_role == "ユーティリティ" or position_style in {"守備走塁二塁手", "守備型三塁手"})
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


def truncated_normal_int(rng: random.Random, mean: float, sd: float, minimum: int, maximum: int) -> int:
    for _ in range(80):
        value = int(round(rng.gauss(mean, sd)))
        if minimum <= value <= maximum:
            return value
    return clamp(rng.gauss(mean, sd), minimum, maximum)


def generate_birthday(rng: random.Random) -> tuple[int, int]:
    days = {1:31, 2:28, 3:31, 4:30, 5:31, 6:30, 7:31, 8:31, 9:30, 10:31, 11:30, 12:31}
    month = rng.randint(1, 12)
    day = 29 if month == 2 and rng.random() < 1 / 1461 else rng.randint(1, days[month])
    return month, day


def adjust_weights(base: list[tuple[str, int]], boosts: dict[str, float]) -> list[tuple[str, int]]:
    return [(k, max(1, int(round(w * boosts.get(k, 1.0))))) for k, w in base]


def generate_form(rng: random.Random, ranges: dict[str, tuple[int, int]], type_weights: list[tuple[str, int]], generic_rate: float, boosts: dict[str, float] | None = None) -> tuple[str, int, int]:
    form_type = weighted_choice(rng, adjust_weights(type_weights, boosts or {}))
    total_max, generic_max = ranges[form_type]
    is_generic = rng.random() < generic_rate or generic_max >= total_max
    if is_generic:
        number = rng.randint(1, generic_max)
    else:
        number = rng.randint(generic_max + 1, total_max)
    return form_type, number, int(is_generic)


def generate_pitching_form(rng: random.Random, category: str, archetype: str, position: str) -> tuple[str, int, int]:
    boosts: dict[str, float] = {}
    if archetype == "速球": boosts["オーバースロー"] = 1.18
    if archetype in {"総合", "変化球"}: boosts["スリークォーター"] = 1.12
    if position in {"中継ぎ", "抑え"}: boosts["サイドスロー"] = 1.15
    return generate_form(rng, PITCHING_FORM_RANGES, PITCHING_FORM_TYPE_WEIGHTS, PITCHING_FORM_GENERIC_RATE.get(category, 0.92), boosts)


def generate_batting_form(rng: random.Random, role: str, category: str, archetype: str, height: int) -> tuple[str, int, int]:
    base = PITCHER_BATTING_FORM_TYPE_WEIGHTS if role == "投手" else BATTING_FORM_TYPE_WEIGHTS
    rate = 0.98 if role == "投手" else BATTING_FORM_GENERIC_RATE.get(category, 0.9)
    boosts: dict[str, float] = {}
    if archetype in {"長打", "強打"}: boosts["オープン"] = 1.25
    if archetype in {"巧打", "ミート"}: boosts["スタンダード"] = 1.12
    if archetype == "俊足" or height <= 172: boosts["クラウチング"] = 1.25
    if category == "助っ人外国人用": boosts["オープン"] = boosts.get("オープン", 1.0) * 1.15
    return generate_form(rng, BATTING_FORM_RANGES, base, rate, boosts)


def generate_pitcher_batting_abilities(rng: random.Random, age: int, weight: int, pitch_speed: int) -> dict[str, Any]:
    contact_band = weighted_choice(rng, [("low", 765), ("mid", 185), ("high", 40), ("rare", 10)])
    contact = rng.randint(*{"low": (5, 10), "mid": (11, 15), "high": (16, 19), "rare": (20, 31)}[contact_band])
    if contact_band == "low" and rng.random() < 0.01: contact = 4
    power_band = weighted_choice(rng, [("low", 700), ("mid", 235), ("high", 60), ("rare", 5)])
    power = rng.randint(*{"low": (6, 11), "mid": (12, 18), "high": (20, 39), "rare": (40, 44)}[power_band])
    if contact >= 20 and power <= 8: power = max(power, rng.randint(9, 18))
    if power >= 30 and contact <= 6: contact = max(contact, rng.randint(7, 14))
    if power >= 40: contact = max(contact, rng.randint(10, 18))
    speed = truncated_normal_int(rng, 46.3, 8.6, 28, 69)
    if rng.random() < 0.007: speed = rng.randint(70, 77)
    if 18 <= age <= 22: speed += rng.randint(0, 2)
    elif 30 <= age <= 34: speed -= rng.randint(1, 3)
    elif age >= 35: speed -= rng.randint(3, 7)
    if weight >= 100: speed -= rng.randint(2, 5)
    elif weight >= 90: speed -= rng.randint(0, 2)
    speed = clamp(speed, 28, 77)
    arm = clamp(pitch_speed - 81 + weighted_choice(rng, [(-1, 15), (0, 35), (1, 35), (2, 15)]), 49, 82)
    fielding = truncated_normal_int(rng, 47, 9, 28, 78)
    if weight >= 100: fielding -= rng.randint(1, 3)
    fielding = clamp(fielding, 28, 78)
    catching = clamp(round(45.6 + 0.55 * (fielding - 47) + rng.gauss(0, 4.5)), 25, 75)
    trajectory = weighted_choice(rng, [(1, 910), (2, 85), (3, 5)])
    if power >= 30: trajectory = max(trajectory, 2)
    if power >= 40: trajectory = weighted_choice(rng, [(2, 70), (3, 30)])
    return {"弾道": trajectory, "ミート": ability(contact), "パワー": ability(power), "走力": ability(speed), "肩力": ability(arm), "守備力": ability(fielding), "捕球": ability(catching)}


def generate_equipment(rng: random.Random, role: str, category: str, archetype: str, position: str) -> dict[str, Any]:
    bat_boosts: dict[str, float] = {}
    if role == "投手": bat_boosts.update({"木": 1.25, "黒": 1.15, "黒/木": 1.15})
    if archetype in {"長打", "強打"}: bat_boosts.update({"黒": 1.15, "黒/赤": 1.35, "茶": 1.2})
    if archetype in {"巧打", "ミート"}: bat_boosts.update({"木": 1.15, "木/黒": 1.2})
    if category == "助っ人外国人用": bat_boosts.update({"黒": 1.15, "黒/木": 1.15, "黒/赤": 1.25})
    if category == "ドラフト候補用": bat_boosts.update({"木": 1.2, "黒": 1.1, "赤": 0.45, "黄/木": 0.55, "黒/赤": 0.65})
    glove_boosts: dict[str, float] = {}
    if role == "投手": glove_boosts.update({"黒": 1.2, "革": 1.15, "茶": 1.1, "オレンジ": 1.1, "ブロンド": 1.1})
    elif position == "捕手": glove_boosts.update({"黒": 1.25, "革": 1.2, "茶": 1.15})
    elif position in {"二塁手", "三塁手", "遊撃手"}: glove_boosts.update({"オレンジ": 1.2, "革": 1.15, "ブロンド": 1.12})
    elif position == "外野手": glove_boosts.update({"黒": 1.12, "茶": 1.12, "赤": 1.12, "青": 1.12})
    if category == "助っ人外国人用": glove_boosts.update({"赤": 1.25, "青": 1.25, "黄": 1.15})
    glove_items = adjust_weights(GLOVE_COLOR_WEIGHTS, glove_boosts)
    if role == "投手": glove_items = [(c, w) for c, w in glove_items if c != "シルバー"]
    pattern = weighted_choice(rng, PITCHER_WRISTBAND_PATTERN_WEIGHTS if role == "投手" else WRISTBAND_PATTERN_WEIGHTS)
    def wc(): return weighted_choice(rng, WRISTBAND_COLOR_WEIGHTS)
    left = right = ""
    le = re = 0
    if pattern == "left_only": le, left = 1, wc()
    elif pattern == "right_only": re, right = 1, wc()
    elif pattern == "both_same": le = re = 1; left = right = wc()
    elif pattern == "both_different":
        le = re = 1
        if rng.random() < 0.55:
            left = weighted_choice(rng, [("黒", 60), ("白", 40)]); right = wc()
        else:
            left, right = wc(), wc()
        while right == left: right = wc()
    return {"bat_color": weighted_choice(rng, adjust_weights(BAT_COLOR_WEIGHTS, bat_boosts)), "glove_color": weighted_choice(rng, glove_items), "wristband_left_enabled": le, "wristband_left_color": left, "wristband_right_enabled": re, "wristband_right_color": right}


def form_display(player: dict[str, Any], prefix: str) -> str:
    t, n = player.get(f"{prefix}_form_type", ""), int(player.get(f"{prefix}_form_number") or 0)
    return f"{t} {n}" if t and n else ""


def birthday_display(player: dict[str, Any]) -> str:
    m, d = int(player.get("birth_month") or 0), int(player.get("birth_day") or 0)
    return f"{m}月{d}日" if m and d else ""

def generate_player(role: str, category: str, master: MasterData, seed: int | None = None, used_names: set[str] | None = None) -> dict[str, Any]:
    seed = seed if seed is not None else random.SystemRandom().randrange(SEED_MAX)
    rng = random.Random(seed)
    draft_source_type = choose_draft_source_type(rng) if category == "ドラフト候補用" else ""
    if category == "助っ人外国人用":
        player_class = weighted_choice(rng, PLAYER_CLASS_WEIGHTS[category])
        age = choose_foreign_age_for_class(rng, player_class)
    else:
        age = age_for(rng, category, draft_source_type)
        player_class = choose_player_class(rng, category, age)
    foreign_profile = None
    if category == "助っ人外国人用":
        foreign_profile = generate_foreign_profile(rng, category, used_names=used_names)
        nationality = foreign_profile.nationality if foreign_profile else choose_nationality(rng, category)
    else:
        nationality = choose_nationality(rng, category)
        if nationality != "日本":
            foreign_profile = generate_foreign_profile(rng, category, display_nationality=nationality, used_names=used_names)
    development_stage = choose_development_stage(rng, category, age, player_class, draft_source_type)
    pitcher_aptitudes: dict[str, str] = {}
    if role == "投手":
        pitcher_aptitudes = choose_pitcher_aptitudes(rng, category)
        position = primary_pitcher_role(pitcher_aptitudes)
    else:
        position_weights = FOREIGN_FIELDER_POSITION_WEIGHTS if category == "助っ人外国人用" else [("捕手", 12), ("一塁手", 14), ("二塁手", 14), ("三塁手", 14), ("遊撃手", 16), ("外野手", 30)]
        position = weighted_choice(rng, position_weights)
    batting_throwing = generate_batting_throwing(rng, role, position)
    acquisition_role = choose_acquisition_role(rng, category, role, player_class, position, pitcher_aptitudes, batting_throwing)
    archetype = choose_archetype(rng, role, category)
    if role == "投手" and position == "抑え" and archetype == "スタミナ":
        for _ in range(4):
            archetype = choose_archetype(rng, role, category)
            if archetype != "スタミナ":
                break
        if archetype == "スタミナ":
            archetype = "総合"
    position_style = choose_position_style(rng, role, position, archetype)
    weakness_profile = choose_weakness_profile(rng, category, role, player_class)
    growth_type = choose_growth_type(
        category=category, age=age, player_class=player_class, development_stage=development_stage,
        acquisition_role=acquisition_role, rng=create_growth_rng(seed, role, category),
    )
    allow_foreign_allrounder = choose_foreign_allrounder_candidate(rng, category, player_class, age, archetype, position_style) if role == "野手" else False
    player_type = legacy_player_type_from_archetype(role, archetype)
    roster_tier = legacy_roster_tier_from_player_class(player_class)
    height = rng.randint(168, 196) + (3 if role == "投手" else 0)
    weight = rng.randint(68, 105)
    if role == "投手":
        abilities = generate_pitcher_abilities(
            rng, age, player_type, category, pitcher_aptitudes,
            player_class=player_class, archetype=archetype, position_style=position_style,
            development_stage=development_stage, acquisition_role=acquisition_role,
            weakness_profile=weakness_profile, growth_type=growth_type,
        )
        abilities.update(generate_pitcher_batting_abilities(rng, age, weight, pitcher_speed_value(abilities) or 145))
        breaking_balls = generate_breaking_balls(
            rng, player_type, category, pitcher_aptitudes, batting_throwing,
            age=age, player_class=player_class, archetype=archetype, position_style=position_style,
            development_stage=development_stage, acquisition_role=acquisition_role,
            weakness_profile=weakness_profile,
        )
    else:
        abilities = generate_fielder_abilities(
            rng, age, position, player_type, category, position_style, roster_tier,
            player_class=player_class, archetype=archetype, development_stage=development_stage,
            acquisition_role=acquisition_role, weakness_profile=weakness_profile,
            allow_foreign_allrounder=allow_foreign_allrounder, growth_type=growth_type,
        )
        breaking_balls = []
    abilities, breaking_balls = audit_generated_player(
        rng, role, category, age, position, player_class, archetype, position_style,
        development_stage, acquisition_role, weakness_profile, abilities, breaking_balls,
        allow_foreign_allrounder=allow_foreign_allrounder,
    )
    if role == "投手":
        abilities["肩力"] = ability(clamp((pitcher_speed_value(abilities) or 145) - 81 + weighted_choice(rng, [(-1, 15), (0, 35), (1, 35), (2, 15)]), 49, 82))
    sub_positions = generate_sub_positions(rng, role, position, player_type, category, age, batting_throwing, abilities, player_class, archetype, position_style, acquisition_role)
    special_abilities = generate_specials(rng, master, role, player_type, position, age, abilities, breaking_balls, category, player_class, archetype, position_style, development_stage, acquisition_role, weakness_profile, sub_positions, pitcher_aptitudes)
    birth_month, birth_day = generate_birthday(rng)
    if role == "投手":
        pitching_form_type, pitching_form_number, pitching_form_is_generic = generate_pitching_form(rng, category, archetype, position)
    else:
        pitching_form_type, pitching_form_number, pitching_form_is_generic = "", 0, 1
    batting_form_type, batting_form_number, batting_form_is_generic = generate_batting_form(rng, role, category, archetype, height)
    equipment = generate_equipment(rng, role, category, archetype, position)
    if foreign_profile:
        name = foreign_profile.name
        birthplace = choose_profile_birthplace(rng, master.places, nationality, foreign_profile.actual_nationality)
    elif nationality == "日本":
        name, birthplace = choose_japanese_identity(rng, master.names)
    else:
        name = choose_name(rng, master.names, nationality)
        birthplace = choose_birthplace(rng, master.places, nationality)
    actual_nationality = foreign_profile.actual_nationality if foreign_profile else (nationality if nationality != "日本" else "")
    return {
        "seed": seed, "role": role, "category": category, "name": name, "age": age,
        "nationality": nationality, "actual_nationality": actual_nationality,
        "nationality_code": foreign_profile.nationality_code if foreign_profile else "",
        "name_group_id": foreign_profile.name_group_id if foreign_profile else 0,
        "name_group_name": foreign_profile.name_group_name if foreign_profile else "",
        "skin_color": foreign_profile.skin_color if foreign_profile else fallback_skin_color(seed, nationality, name),
        "name_generation_fallback": foreign_profile is None and nationality != "日本",
        "birthplace": birthplace, "position": position, "player_type": player_type,
        "player_class": player_class, "archetype": archetype, "position_style": position_style,
        "growth_type": growth_type, "growth_type_label": growth_type_label(growth_type),
        "development_stage": development_stage, "acquisition_role": acquisition_role, "weakness_profile": weakness_profile,
        "handedness": handedness_from_batting_throwing(batting_throwing),
        "batting_throwing": batting_throwing,
        "height": height, "weight": weight,
        "birth_month": birth_month, "birth_day": birth_day,
        "pitching_form_type": pitching_form_type, "pitching_form_number": pitching_form_number, "pitching_form_is_generic": pitching_form_is_generic,
        "batting_form_type": batting_form_type, "batting_form_number": batting_form_number, "batting_form_is_generic": batting_form_is_generic,
        "draft_source_type": draft_source_type,
        **equipment,
        "abilities": {**abilities, "ranked_specials": generate_ranked_specials(rng, master, role, position, player_type, abilities, age, category, player_class, archetype, position_style, weakness_profile, sub_positions, pitcher_aptitudes)}, "special_abilities": special_abilities,
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
            birthplace = p.get("birthplace") or p.get("region") or ""
            region = p.get("region") or birthplace
            if p.get("nationality") == "日本":
                birthplace = normalize_japanese_prefecture_name(birthplace)
                region = normalize_japanese_prefecture_name(region)
            conn.execute("""INSERT INTO players (created_at, seed, role, category, name, age, nationality, actual_nationality, nationality_code, name_group_id, name_group_name, skin_color, birthplace, region, position, player_type, player_class, growth_type, archetype, position_style, development_stage, acquisition_role, weakness_profile, handedness, batting_throwing, height, weight, abilities_json, special_abilities_json, ranked_special_abilities_json, breaking_balls_json, pitcher_aptitudes_json, sub_positions_json, birth_month, birth_day, pitching_form_type, pitching_form_number, pitching_form_is_generic, batting_form_type, batting_form_number, batting_form_is_generic, bat_color, glove_color, wristband_left_enabled, wristband_left_color, wristband_right_enabled, wristband_right_color, draft_source_type)
                          VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (p.get("seed", 0), p.get("role", ""), p.get("category", ""), p.get("name", ""), p.get("age", 0), p.get("nationality", ""), p.get("actual_nationality", ""), p.get("nationality_code", ""), p.get("name_group_id", 0), p.get("name_group_name", ""), p.get("skin_color", 0), birthplace, region, p.get("position", ""), p.get("player_type", ""), p.get("player_class", ""), normalize_growth_type(p.get("growth_type")), p.get("archetype", ""), p.get("position_style", ""), p.get("development_stage", ""), p.get("acquisition_role", ""), p.get("weakness_profile", ""), p.get("handedness", ""), p.get("batting_throwing", ""), p.get("height", 0), p.get("weight", 0), json.dumps(abilities, ensure_ascii=False), json.dumps(p.get("special_abilities", []), ensure_ascii=False), json.dumps(ranked_specials, ensure_ascii=False), json.dumps(p.get("breaking_balls", []), ensure_ascii=False), json.dumps(pitcher_aptitudes, ensure_ascii=False), json.dumps(normalize_sub_positions(p.get("sub_positions", [])), ensure_ascii=False), p.get("birth_month", 0), p.get("birth_day", 0), p.get("pitching_form_type", ""), p.get("pitching_form_number", 0), p.get("pitching_form_is_generic", 1), p.get("batting_form_type", ""), p.get("batting_form_number", 0), p.get("batting_form_is_generic", 1), p.get("bat_color", ""), p.get("glove_color", ""), p.get("wristband_left_enabled", 0), p.get("wristband_left_color", ""), p.get("wristband_right_enabled", 0), p.get("wristband_right_color", ""), p.get("draft_source_type", "")))
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
        wanted = ["id", "created_at", "seed", "role", "category", "name", "age", "nationality", "actual_nationality", "nationality_code", "name_group_id", "name_group_name", "skin_color", "birthplace", "region", "position", "player_type", "growth_type", *CLASSIFICATION_COLUMNS, "handedness", "batting_throwing", "height", "weight", "abilities_json", "special_abilities_json", "ranked_special_abilities_json", "breaking_balls_json", "pitcher_aptitudes_json", "sub_positions_json", "birth_month", "birth_day", "pitching_form_type", "pitching_form_number", "pitching_form_is_generic", "batting_form_type", "batting_form_number", "batting_form_is_generic", "bat_color", "glove_color", "wristband_left_enabled", "wristband_left_color", "wristband_right_enabled", "wristband_right_color", "draft_source_type"]
        selected = [column for column in wanted if column in columns]
        history = pd.read_sql_query(f"SELECT {', '.join(selected)} FROM players ORDER BY id DESC", conn)
    if not history.empty:
        if "region" not in history.columns:
            history["region"] = history.get("birthplace", "")
        if "nationality" in history.columns:
            japanese_rows = history["nationality"].eq("日本")
            for place_column in ("birthplace", "region"):
                if place_column in history.columns:
                    history.loc[japanese_rows, place_column] = history.loc[japanese_rows, place_column].apply(normalize_japanese_prefecture_name)
        for column in CLASSIFICATION_COLUMNS:
            if column not in history.columns:
                history[column] = ""
            history[column] = history[column].fillna("").astype(str)
            history[CLASSIFICATION_LABELS[column]] = history[column]
        if "growth_type" not in history.columns:
            history["growth_type"] = "normal"
        history["growth_type"] = history["growth_type"].apply(normalize_growth_type)
        history["成長タイプ"] = history["growth_type"].apply(growth_type_label)
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
        for column in ["birth_month", "birth_day", "pitching_form_number", "pitching_form_is_generic", "batting_form_number", "batting_form_is_generic", "wristband_left_enabled", "wristband_right_enabled"]:
            if column in history.columns:
                history[column] = pd.to_numeric(history[column], errors="coerce").fillna(0).astype(int)
        history["誕生日"] = history.apply(lambda row: f"{int(row.get('birth_month') or 0)}月{int(row.get('birth_day') or 0)}日" if int(row.get('birth_month') or 0) and int(row.get('birth_day') or 0) else "", axis=1)
        history["投球フォーム"] = history.apply(lambda row: f"{row.get('pitching_form_type', '')} {int(row.get('pitching_form_number') or 0)}" if row.get('pitching_form_type') and int(row.get('pitching_form_number') or 0) else "", axis=1)
        history["打撃フォーム"] = history.apply(lambda row: f"{row.get('batting_form_type', '')} {int(row.get('batting_form_number') or 0)}" if row.get('batting_form_type') and int(row.get('batting_form_number') or 0) else "", axis=1)
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
    keys = ["role", "category", "name", "age", "nationality", "actual_nationality", "nationality_code", "name_group_id", "name_group_name", "skin_color", "birthplace", "position", "player_type", *CLASSIFICATION_COLUMNS, "handedness", "batting_throwing", "height", "weight", "abilities_json", "special_abilities_json", "breaking_balls_json", "birth_month", "birth_day", "pitching_form_type", "pitching_form_number", "pitching_form_is_generic", "batting_form_type", "batting_form_number", "batting_form_is_generic", "bat_color", "glove_color", "wristband_left_enabled", "wristband_left_color", "wristband_right_enabled", "wristband_right_color", "draft_source_type"]
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


def classification_distribution_table(df: pd.DataFrame, group_columns: list[str], value_column: str) -> pd.DataFrame:
    columns = [*group_columns, CLASSIFICATION_LABELS.get(value_column, value_column), "人数", "構成比%"]
    if df.empty or value_column not in df.columns:
        return pd.DataFrame(columns=columns)
    work = df.copy()
    work[value_column] = work[value_column].fillna("").astype(str)
    work = work[work[value_column] != ""]
    if work.empty:
        return pd.DataFrame(columns=columns)
    counts = work.groupby([*group_columns, value_column]).size().reset_index(name="人数")
    totals = counts.groupby(group_columns)["人数"].transform("sum") if group_columns else counts["人数"].sum()
    counts["構成比%"] = (counts["人数"] / totals * 100).round(2)
    return counts.rename(columns={value_column: CLASSIFICATION_LABELS.get(value_column, value_column)})


def handedness_batting_mismatch_count(df: pd.DataFrame) -> int:
    derived = df["batting_throwing"].apply(handedness_from_batting_throwing)
    return int((df["handedness"] != derived).sum())


def restricted_left_throwing_positions(df: pd.DataFrame) -> pd.DataFrame:
    positions = ["捕手", "二塁手", "三塁手", "遊撃手"]
    target = df[(df["position"].isin(positions)) & (df["handedness"] == "左投")]
    counts = target["position"].value_counts().rename_axis("ポジション").reset_index(name="人数")
    base = pd.DataFrame({"ポジション": positions})
    return base.merge(counts, on="ポジション", how="left").fillna({"人数": 0}).astype({"人数": int})




def name_matches_nationality(name: str, nationality: str, master: MasterData, birthplace: str | None = None) -> bool:
    if name_matches_entry(name, master.names.get(nationality)):
        return True
    return nationality == "日本" and japanese_name_matches_surname_master(name, master, birthplace)


def birthplace_matches_nationality(birthplace: str, nationality: str, master: MasterData) -> bool:
    candidates = master.places.get(nationality, [])
    return birthplace in candidates or normalize_japanese_prefecture_name(birthplace) in candidates

def consistency_table(df: pd.DataFrame, master: MasterData, kind: str) -> pd.DataFrame:
    work = df.copy()
    type_column = "名前種別" if kind == "name" else "出身地種別"
    if kind == "name":
        work[type_column] = work.apply(lambda row: classify_name_type(row["name"], master, row["nationality"], row.get("birthplace")), axis=1)
    else:
        work[type_column] = work["birthplace"].apply(lambda value: classify_birthplace_type(value, master))
    if kind == "name":
        work["整合性"] = work.apply(lambda row: name_matches_nationality(row["name"], row["nationality"], master, row.get("birthplace")), axis=1)
    else:
        work["整合性"] = work.apply(lambda row: birthplace_matches_nationality(row["birthplace"], row["nationality"], master), axis=1)
    return work.groupby(["nationality", type_column, "整合性"]).size().reset_index(name="人数").rename(columns={"nationality": "国籍"})


def inconsistency_count(df: pd.DataFrame, master: MasterData, kind: str) -> int:
    if kind == "name":
        matches = df.apply(lambda row: name_matches_nationality(row["name"], row["nationality"], master, row.get("birthplace")), axis=1)
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
    render_page_description("保存済み選手をSQLiteから読み込み、生成結果の偏りを確認します。")
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
        render_success_message(f"保存済み選手を{deleted_count}件削除しました。")
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

    st.subheader("新分類分布")
    class_col1, class_col2 = st.columns(2)
    with class_col1:
        st.dataframe(classification_distribution_table(df, ["category"], "player_class").rename(columns={"category": "カテゴリ"}), use_container_width=True, hide_index=True)
        st.dataframe(classification_distribution_table(df, ["position"], "position_style").rename(columns={"position": "ポジション"}), use_container_width=True, hide_index=True)
        st.dataframe(classification_distribution_table(df[df["category"].eq("助っ人外国人用")], ["category"], "weakness_profile").rename(columns={"category": "カテゴリ"}), use_container_width=True, hide_index=True)
    with class_col2:
        st.dataframe(classification_distribution_table(df, ["category"], "archetype").rename(columns={"category": "カテゴリ"}), use_container_width=True, hide_index=True)
        st.dataframe(classification_distribution_table(df[df["category"].eq("ドラフト候補用")], ["category"], "development_stage").rename(columns={"category": "カテゴリ"}), use_container_width=True, hide_index=True)
        st.dataframe(classification_distribution_table(df[df["category"].eq("助っ人外国人用")], ["category"], "acquisition_role").rename(columns={"category": "カテゴリ"}), use_container_width=True, hide_index=True)

    st.subheader("成長タイプ分布")
    growth_df = df.copy()
    growth_df["成長タイプ"] = growth_df["growth_type"].apply(growth_type_label)
    growth_total = growth_df["成長タイプ"].value_counts().reindex(GROWTH_TYPE_LABELS.values(), fill_value=0).rename_axis("成長タイプ").reset_index(name="人数")
    growth_total["割合"] = (growth_total["人数"] / len(growth_df) * 100).round(2)
    gcol1, gcol2 = st.columns(2)
    with gcol1:
        st.dataframe(growth_total, use_container_width=True, hide_index=True)
        st.dataframe(pd.crosstab(growth_df["category"], growth_df["成長タイプ"], normalize="index").mul(100).round(1), use_container_width=True)
    with gcol2:
        st.dataframe(pd.crosstab(growth_df["role"], growth_df["成長タイプ"], normalize="index").mul(100).round(1), use_container_width=True)
        st.dataframe(pd.crosstab(growth_df["age"].apply(lambda age: age_band(int(age))), growth_df["成長タイプ"], normalize="index").mul(100).round(1), use_container_width=True)

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


def page_description_html(text: str) -> str:
    return f'<p class="pp-page-description">{e(text)}</p>'


def render_page_description(text: str) -> None:
    st.markdown(page_description_html(text), unsafe_allow_html=True)


def success_message_html(text: str) -> str:
    return f'<div class="pp-success-message">{e(text)}</div>'


def render_success_message(text: str) -> None:
    st.markdown(success_message_html(text), unsafe_allow_html=True)


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
    .pp-header {display:grid; grid-template-columns:minmax(330px, 1.2fr) 126px minmax(400px, 1.45fr); gap:7px; align-items:stretch; min-height:126px; margin-bottom:0; min-width:0;}
    .pp-name {background:linear-gradient(#ffbbb5,#ff6e68); border:3px solid #e82e42; border-radius:8px; font-size:28px; font-weight:900; text-align:center; padding:4px 7px; min-height:44px; color:#022d55; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; position:relative; display:flex; align-items:center; justify-content:center; min-width:0;}
    .pp-number-box {background:#fff; color:#075fbd; border:3px solid #c8e7ff; border-radius:5px; font-size:28px; line-height:1.38; font-weight:950; text-align:center; align-self:stretch; min-height:44px; display:flex; align-items:center; justify-content:center; min-width:0; height:100%;}
    .pp-category-mark {background:linear-gradient(#fff,#e9f9ff); border:3px solid #c8e7ff; border-radius:5px; color:#075fbd; display:flex; align-items:center; justify-content:center; font-size:17px; font-weight:950; min-height:44px; min-width:0; height:100%;}
    .pp-face {background:#f7fbff; border:2px solid #c8e7ff; border-radius:10px; display:flex; align-items:center; justify-content:center; min-height:126px; overflow:hidden; width:126px; min-width:126px; height:126px;}
    .pp-face svg {width:72px; height:72px; flex:0 0 auto;}
    .pp-info {display:grid; grid-template-columns:minmax(170px, 1.3fr) minmax(130px, 1fr) minmax(100px, .72fr); gap:5px; align-content:stretch; min-width:0;}
    .pp-chip {background:#f7fbff; border:2px solid #d5edff; border-radius:9px; padding:5px 8px; color:#0a69b0; font-weight:800; font-size:17px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .pp-chip-wide {font-size:14px; letter-spacing:-.03em;}
    .pp-score {background:#0368b8; color:white; border-radius:7px; padding:1px 8px; display:inline-block; font-weight:900;}
    .pp-body {display:grid; grid-template-columns:33% 67%; gap:9px; background:#edf9fc; border:0; border-top:3px solid var(--pp-tab-color,#0876c9); border-radius:0 0 10px 10px; padding:9px; overflow:hidden; align-items:start; margin-top:0;}
    .pp-body-pitcher {grid-template-columns:35% 65%; min-height:430px; overflow:visible;}
    .pp-mini-label {font-size:12px; opacity:.75; display:block; margin-bottom:3px;}
    .pp-ability-row {display:grid; grid-template-columns:minmax(102px,38%) 50px 1fr; align-items:center; margin:3px 0; background:#fff; border:2px solid #cfe9ff; border-radius:7px; min-height:42px; height:42px; overflow:hidden; box-shadow:inset 0 1px rgba(255,255,255,.72);}
    .pp-label {font-size:17px; background:#fff; border-radius:7px; margin-left:6px; padding:2px 7px; color:#126bb0; font-weight:900; text-align:center; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
    .pp-rank {font-size:26px; font-weight:950; text-align:center; -webkit-text-stroke:.45px rgba(255,255,255,.75); text-shadow:0 1px rgba(255,255,255,.42); line-height:1; width:42px;}
    .pp-value {font-size:24px; color:#0b72bd; font-weight:950; text-align:right; padding-right:12px; overflow-wrap:anywhere;}
    .pp-special-grid {display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:3px;}
    .pp-special {height:42px; min-width:0; border-radius:7px; border:2px solid #3fb5cb; background:linear-gradient(180deg,#f0fdff 0%,#b8eef4 58%,#83dce7 100%); color:#075f94; font-weight:850; display:grid; grid-template-columns:minmax(0,1fr); place-items:center; padding:0 6px; font-size:17px; box-shadow:inset 0 1px rgba(255,255,255,.72),0 1px 1px rgba(7,95,148,.14);}
    .pp-special-name {overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; max-width:100%; text-align:center;}
    .pp-special-ranked {display:grid; grid-template-columns:minmax(0,1fr) 26px; padding:0; overflow:hidden; gap:0; align-items:stretch;}
    .pp-special-ranked .pp-special-name {display:flex; align-items:center; justify-content:center; padding:0 4px; min-width:0;}
    .pp-special-rank-badge {display:flex; align-items:center; justify-content:center; align-self:stretch; width:26px; color:#fff; font-size:19px; line-height:1; font-weight:950; text-align:center; text-shadow:0 1px rgba(0,42,70,.32);}
    .pp-special.long .pp-special-name {font-size:15px; letter-spacing:-.065em;}
    .pp-special.xlong .pp-special-name {font-size:13px; letter-spacing:-.085em;}
    .pp-special.red {background:linear-gradient(#fff8f8,#ffe0e0); border-color:#f29a9a; color:#bd1624;}
    .pp-special.green {background:linear-gradient(180deg,#effff2 0%,#bcebc7 100%); border-color:#36aa5b; color:#086b30;}
    .pp-special.neutral {background:linear-gradient(180deg,#f9fdff 0%,#e0f2f6 100%); border-color:#82bdca; color:#285e75;}
    .pp-special.gold {background:linear-gradient(#fffdf1,#fff0ad); border-color:#e0be3c; color:#836200;}
    .pp-special.mixed {background:linear-gradient(to right,#b8eef4 0%,#83dce7 50%,#ffe0e0 50%,#ffadad 100%); border-color:#3fb5cb; color:#073f68; text-shadow:0 1px rgba(255,255,255,.68);}
    .pp-special-ranked.rank-ab {background:linear-gradient(180deg,#eefcff 0%,#ade8ef 58%,#78d3df 100%); border-color:#39afc4; color:#075f94;}
    .pp-special-ranked.rank-ab .pp-special-rank-badge {background:linear-gradient(180deg,#38c9dc 0%,#1595b5 100%); color:#fff;}
    .pp-special-ranked.rank-cde {background:linear-gradient(180deg,#fbfdff 0%,#e3f1f5 55%,#c9e5eb 100%); border-color:#78b5c2; color:#285e75;}
    .pp-special-ranked.rank-cde .pp-special-rank-badge {background:linear-gradient(180deg,#72c5d2 0%,#388fa3 100%); color:#fff;}
    .pp-special-ranked.rank-fg {background:linear-gradient(180deg,#fff5f5 0%,#ffd3d3 55%,#ffadad 100%); border-color:#ef6c72; color:#c71c24;}
    .pp-special-ranked.rank-fg .pp-special-rank-badge {background:linear-gradient(180deg,#ed5a60 0%,#c8212b 100%); color:#fff;}
    .pp-special.empty {height:42px; background:linear-gradient(180deg,#ffffff 0%,#fbfdfe 58%,#f5fafb 100%); border-color:#dcebef; color:transparent; box-shadow:none;}
    .pp-section-title {color:#075f9e; font-weight:900; font-size:17px; margin:2px 0 7px;}
    .pp-help {position:static; background:#062247; color:#f7fbff; padding:12px 18px; font-size:17px; line-height:1.55; font-weight:800; border-top:4px solid #0b4f8c; border-radius:8px; margin:16px 0; overflow-wrap:anywhere;}
    .pp-list-note {color:#073f68; font-weight:900; background:rgba(255,255,255,.78); border-left:5px solid #0b78bd; padding:7px 10px; border-radius:5px; margin-bottom:8px;}
    .pp-page-description {color:#073f68; font-size:16px; line-height:1.6; font-weight:650; margin:0 0 14px;}
    .pp-success-message {color:#075f3b; background:rgba(133,225,177,.38); border:1px solid rgba(18,143,84,.38); border-left:5px solid #168a54; border-radius:8px; padding:12px 14px; font-size:16px; line-height:1.5; font-weight:800; margin:8px 0 14px;}
    .pp-player-row {width:100%; text-align:left; margin-bottom:4px;}
    .stApp [data-testid="stCaptionContainer"] {font-weight:650;}
    .stApp [data-testid="stSelectbox"] {min-width:0;}
    .stApp [data-testid="stSidebar"] {color:#eef7ff;}
    .stApp [data-testid="stSidebar"] p, .stApp [data-testid="stSidebar"] label, .stApp [data-testid="stSidebar"] span, .stApp [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {color:#d8ecf7;}
    .stApp [data-testid="stSidebar"] h1, .stApp [data-testid="stSidebar"] h2, .stApp [data-testid="stSidebar"] h3 {color:#f4fbff;}
    .stApp [data-testid="stSidebar"] [data-baseweb="select"] * {color:#f4fbff;}
    .stApp [data-testid="stHeadingWithActionElements"] h1, .stApp [data-testid="stHeadingWithActionElements"] h2, .stApp [data-testid="stHeadingWithActionElements"] h3 {color:#073f68; text-shadow:none;}
    .stApp [data-testid="stExpander"] summary, .stApp [data-testid="stExpander"] summary * {color:#f4fbff!important;}
    div[data-testid="stButton"] > button {min-height:2.2rem; opacity:1!important;}
    div[data-testid="stButton"] > button:not(:disabled), div[data-testid="stButton"] > button:not(:disabled) *, div[data-testid="stDownloadButton"] > button, div[data-testid="stDownloadButton"] > button * {color:#ffffff!important;}
    button[kind="primary"], button[kind="primary"] * {color:#ffffff!important;}
    div[class*="st-key-latest_prev"] button, div[class*="st-key-latest_next"] button, div[class*="st-key-history_prev"] button, div[class*="st-key-history_next"] button {min-height:38px; height:38px; white-space:nowrap;}
    div[class*="st-key-latest_prev"] button:disabled, div[class*="st-key-latest_next"] button:disabled, div[class*="st-key-history_prev"] button:disabled, div[class*="st-key-history_next"] button:disabled {opacity:1!important; color:#5f7484!important; background:#e5edf2!important; border-color:#b7c7d2!important; cursor:not-allowed;}
    div[class*="st-key-latest_prev"] button:disabled *, div[class*="st-key-latest_next"] button:disabled *, div[class*="st-key-history_prev"] button:disabled *, div[class*="st-key-history_next"] button:disabled * {color:#5f7484!important;}
    @media (max-width: 980px) {
      .pp-header {grid-template-columns:1fr;}
      .pp-face {width:100%;}
      .pp-profile-table {grid-template-columns:88px minmax(0, 1fr);}
      .pp-profile-span-3 {grid-column:span 1;}
      .pp-info {grid-template-columns:1fr;}
      .pp-body,.pp-body-pitcher {grid-template-columns:1fr; min-height:0;}
      .pp-special-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
      .pp-usage-grid {grid-template-columns:repeat(4,minmax(0,1fr));}
      .pp-help {font-size:15px; padding:10px 12px;}
      .pp-defense-compact {width:100%;}
      div[class*="st-key-latest_prev"] button, div[class*="st-key-latest_next"] button, div[class*="st-key-history_prev"] button, div[class*="st-key-history_next"] button {font-size:14px; padding-left:6px; padding-right:6px;}
    }
    .pp-aptitude-line {background:#f9fdff; border:2px solid #cfe9ff; border-radius:9px; color:#0a69b0; font-weight:900; padding:5px 9px; margin-bottom:6px; white-space:nowrap; font-size:15px;}
    .pp-pitcher-usage-row,.pp-pitcher-defense-row {display:grid; grid-template-columns:40% 1fr; align-items:center; margin:4px 0; background:#fff; border:2px solid #cfe9ff; border-radius:9px; min-height:39px; overflow:hidden; box-shadow:inset 0 2px rgba(255,255,255,.8);}
    .pp-pitcher-usage-values {display:flex; gap:14px; align-items:center; justify-content:space-around; min-width:0; white-space:nowrap; color:#0b72bd; font-weight:950; font-size:18px;}
    .pp-pitcher-usage-item {white-space:nowrap; display:inline-flex; gap:2px; align-items:baseline;}
    .pp-pitcher-defense-values {display:flex; gap:10px; align-items:baseline; justify-content:flex-end; padding-right:12px; white-space:nowrap; color:#0b72bd; font-weight:950;}
    @media (max-width: 980px) {.pp-pitcher-usage-values {font-size:15px; gap:8px;}}
    .pp-chart-wrap {height:286px; min-height:286px; max-height:286px; margin-top:6px; overflow:hidden;}
    .pp-trajectory-row {overflow:hidden;}
    .pp-trajectory-icon {display:flex; align-items:center; justify-content:center; width:50px; height:100%; overflow:visible;}
    .pp-trajectory-icon svg {overflow:visible;}
    .pp-trajectory-icon.trajectory-1 svg {transform:rotate(0deg); transform-origin:6px 25px;}
    .pp-trajectory-icon.trajectory-2 svg {transform:rotate(-18deg); transform-origin:6px 25px;}
    .pp-trajectory-icon.trajectory-3 svg {transform:rotate(-34deg); transform-origin:6px 25px;}
    .pp-trajectory-icon.trajectory-4 svg {transform:rotate(-58deg); transform-origin:6px 25px;}
    .pp-trajectory-value {color:#0b72bd;}
    .pp-defense-grid,.pp-profile-grid {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px;}
    .pp-defense-compact {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:2px; margin:5px 0; border:2px solid #a9d4e8; border-radius:9px; overflow:hidden; background:#a9d4e8;}
    .pp-defense-pos {display:grid; grid-template-columns:34px 34px minmax(0,1fr); align-items:center; gap:4px; background:#f7fbfd; border:0; border-radius:0; padding:8px; color:#28617f; font-weight:850; min-height:42px; min-width:0;}
    .pp-defense-short {text-align:left; color:#245c78;}
    .pp-defense-rank {text-align:center; font-size:18px; font-weight:950;}
    .pp-defense-num {text-align:right; color:#0b629d; font-variant-numeric:tabular-nums;}
    .pp-defense-empty {grid-column:2 / 4; text-align:center; color:#aec5d1; font-weight:800;}
    .pp-defense-pos.main {background:#dff3ff; box-shadow:inset 4px 0 0 #0b8fe0; color:#063f68; font-weight:950;}
    .pp-usage-grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:3px;}
    .pp-usage-cell {min-height:46px; border:2px solid #bde7f0; border-radius:7px; display:flex; align-items:center; justify-content:center; padding:0 6px; font-weight:900; color:#0b72bd; background:rgba(235,250,253,.46); min-width:0; text-align:center;}
    .pp-usage-label {background:linear-gradient(180deg,#fff 0%,#e9f9fd 100%); color:#126bb0;}
    .pp-usage-value {background:linear-gradient(180deg,#f3fff5 0%,#c9f2d2 100%); border-color:#56c978; color:#13783a;}
    .pp-usage-empty {color:transparent; background:linear-gradient(180deg,#fbfeff 0%,#f2fbfd 58%,#e3f5f8 100%); border-color:#c7e5eb; box-shadow:none;}
    .pp-header-main {display:grid; grid-template-rows:76px 43px; gap:5px; min-width:0;}
    .pp-name-line {display:grid; grid-template-columns:minmax(0, 1fr) 48px 62px; gap:5px; min-width:0;}
    .pp-posline {background:#f7fbff; border:2px solid #d5edff; border-radius:9px; padding:5px 8px; color:#0a69b0; font-weight:900; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; height:43px; min-height:43px;}
    .pp-profile-table {display:grid; grid-template-columns:92px minmax(0, 1fr) 92px minmax(0, 1fr); border:2px solid #c4e3ec; border-radius:7px; overflow:hidden; background:#ffffff;}
    .pp-profile-label {min-height:44px; display:flex; align-items:center; padding:0 9px; background:#f5fbfd; border-right:1px solid #cfe8ee; border-bottom:1px solid #cfe8ee; color:#1973a5; font-size:14px; font-weight:850;}
    .pp-profile-value {min-height:44px; display:flex; align-items:center; padding:0 10px; background:#ffffff; border-right:1px solid #cfe8ee; border-bottom:1px solid #cfe8ee; color:#123f61; font-size:17px; font-weight:800; min-width:0; overflow-wrap:anywhere;}
    .pp-profile-span-3 {grid-column:span 3;}
    @media (max-width: 980px) {
      .pp-profile-table {grid-template-columns:88px minmax(0,1fr);}
      .pp-profile-span-3 {grid-column:span 1;}
    }
    .pp-generation-grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px;}
    .pp-generation-card {background:#f8fcff; border:2px solid #cce8ff; border-radius:9px; padding:7px; color:#0a69b0; font-weight:900; min-height:50px;}
    div[class*="st-key-latest_tab_"], div[class*="st-key-history_tab_"] {margin-bottom:-2px;}
    div[class*="st-key-latest_tab_"] button, div[class*="st-key-history_tab_"] button {background:#06396f!important; color:white!important; border-color:#052e5a!important; font-weight:900; border-radius:11px 11px 0 0!important; margin-right:0!important; min-height:3rem;}
    div[class*="st-key-latest_tab_"] button *, div[class*="st-key-history_tab_"] button * {color:#ffffff!important;}
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
    player["growth_type"] = normalize_growth_type(player.get("growth_type"))
    player["growth_type_label"] = growth_type_label(player["growth_type"])
    if player.get("nationality") == "日本":
        player["birthplace"] = normalize_japanese_prefecture_name(player.get("birthplace"))
        player["region"] = normalize_japanese_prefecture_name(player.get("region") or player.get("birthplace"))
    if isinstance(row.get("pitcher_aptitudes_json"), str):
        player.update(parse_json_column(row.get("pitcher_aptitudes_json"), {}))
    for column in CLASSIFICATION_COLUMNS:
        value = player.get(column, "")
        player[column] = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
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
        "S": "#ff5da2",
        "A": "#ff3bbd",
        "B": "#ff315d",
        "C": "#ff9d00",
        "D": "#d7c900",
        "E": "#20a84a",
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


def render_trajectory_row_html(value: Any) -> str:
    try:
        trajectory = int(value)
    except (TypeError, ValueError):
        trajectory = 1
    trajectory = max(1, min(4, trajectory))
    colors = {1: "#d8c900", 2: "#ef8200", 3: "#f03662", 4: "#df32d7"}
    color = colors[trajectory]
    return (
        '<div class="pp-ability-row pp-trajectory-row">'
        '<div class="pp-label">弾道</div>'
        f'<div class="pp-trajectory-icon trajectory-{trajectory}">'
        '<svg viewBox="0 0 52 32" width="52" height="32" aria-hidden="true">'
        '<g filter="drop-shadow(0 1px 1px rgba(0,0,0,.28))">'
        '<line x1="6" y1="25" x2="41" y2="25" stroke="#ffffff" stroke-width="10" stroke-linecap="round"/>'
        '<polygon points="44,25 33,15 33,35" fill="#ffffff" stroke="#ffffff" stroke-linejoin="round"/>'
        f'<line x1="6" y1="25" x2="41" y2="25" stroke="{color}" stroke-width="7" stroke-linecap="round"/>'
        f'<polygon points="44,25 34,17 34,33" fill="{color}" stroke="{color}" stroke-linejoin="round"/>'
        '</g>'
        '</svg></div>'
        f'<div class="pp-value pp-trajectory-value">{trajectory}</div></div>'
    )


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
    cls = "gold" if kind == "gold" else "red" if kind == "red" else "green" if kind == "green" else "neutral" if kind == "neutral" else "mixed" if kind == "mixed" else ""
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
    return PITCH_DISPLAY_NAMES.get(text, text if len(text) <= 8 else text[:7] + "…")


def normalize_pitch_movement(ball: dict[str, Any]) -> int:
    try:
        movement = int(ball.get("movement", ball.get("level", 0)) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(7, max(0, movement))


@dataclass(frozen=True)
class PitchChartLane:
    direction_code: str
    lane_index: int
    pitch_name: str
    display_name: str
    movement: int
    is_left: bool


def build_pitch_chart_lanes(
    breaking_balls: list[dict[str, Any]], is_left: bool,
) -> list[PitchChartLane]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ball in breaking_balls:
        code = str(ball.get("direction_code"))
        if ball.get("kind") == "breaking" and code in PITCH_GAUGE_GEOMETRY:
            grouped.setdefault(code, []).append(ball)
    lanes = []
    for code in PITCH_GAUGE_GEOMETRY:
        direction_balls = sorted(
            grouped.get(code, []),
            key=lambda ball: (bool(ball.get("is_second_pitch")), int(ball.get("slot", 1) or 1)),
        )[:2]
        for lane_index, ball in enumerate(direction_balls):
            name = str(ball.get("name") or "")
            lanes.append(PitchChartLane(
                direction_code=code,
                lane_index=lane_index,
                pitch_name=name,
                display_name=pitch_display_name(name),
                movement=normalize_pitch_movement(ball),
                is_left=is_left,
            ))
    return lanes


def pitch_gauge_segment_positions(
    direction_code: str, lane_index: int, is_left: bool, paired: bool = False,
) -> list[tuple[float, float, float]]:
    geometry = PITCH_GAUGE_GEOMETRY[direction_code]
    origin_x, origin_y = geometry["origin"]
    offset_x, offset_y = geometry["paired_lane_offset"]
    angle = float(geometry["angle"])
    if paired:
        pair_factor = -0.5 if lane_index <= 0 else 0.5
        origin_x += offset_x * pair_factor
        origin_y += offset_y * pair_factor
    step = PAIRED_STEP if paired else PITCH_GAUGE_STEP
    radians = math.radians(angle)
    positions = [
        (origin_x + math.cos(radians) * step * index,
         origin_y + math.sin(radians) * step * index,
         angle)
        for index in range(PAIRED_SEGMENT_COUNT if paired else PITCH_GAUGE_SEGMENT_COUNT)
    ]
    if is_left and direction_code != "3":
        return [(280 - x, y, (180 - segment_angle) % 360) for x, y, segment_angle in positions]
    return positions


def pitch_gauge_label_geometry(
    direction_code: str, lane_index: int, is_left: bool, direction_three_split: bool = False,
) -> tuple[float, float, str]:
    if direction_code == "3" and lane_index <= 0 and not direction_three_split:
        return 140, 200, "middle"
    x, y, anchor = PITCH_CHART_LABEL_GEOMETRY[direction_code][0 if lane_index <= 0 else 1]
    if is_left and direction_code != "3":
        return 280 - x, y, {"start": "end", "end": "start"}.get(anchor, anchor)
    return x, y, anchor


def pitch_gauge_colors(active: bool) -> tuple[str, str, str]:
    return PITCH_GAUGE_ACTIVE if active else PITCH_GAUGE_INACTIVE


def render_pitch_gauge_segment_svg(
    x: float, y: float, angle: float, active: bool, direction_code: str, lane_index: int, segment_index: int,
) -> str:
    fill, stroke, highlight = pitch_gauge_colors(active)
    return (
        f'<g class="pitch-gauge-segment" data-direction="{direction_code}" data-lane="{lane_index}" '
        f'data-index="{segment_index}" data-active="{str(active).lower()}" transform="translate({x:.1f} {y:.1f}) rotate({angle:.1f})">'
        f'<rect x="{-PITCH_GAUGE_SEGMENT_LENGTH / 2:.1f}" y="{-PITCH_GAUGE_SEGMENT_THICKNESS / 2:.1f}" '
        f'width="{PITCH_GAUGE_SEGMENT_LENGTH}" height="{PITCH_GAUGE_SEGMENT_THICKNESS}" rx="1" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        f'<line x1="{-PITCH_GAUGE_SEGMENT_LENGTH / 2 + 1:.1f}" y1="{-PITCH_GAUGE_SEGMENT_THICKNESS / 2 + 1.5:.1f}" '
        f'x2="{PITCH_GAUGE_SEGMENT_LENGTH / 2 - 1:.1f}" y2="{-PITCH_GAUGE_SEGMENT_THICKNESS / 2 + 1.5:.1f}" stroke="{highlight}" stroke-width="1"/></g>'
    )


def render_paired_pitch_gauge_segment_svg(
    x: float, y: float, angle: float, active: bool, direction_code: str, lane_index: int, segment_index: int,
) -> str:
    fill, stroke, highlight = pitch_gauge_colors(active)
    return (
        f'<g class="paired-pitch-segment" data-direction="{direction_code}" data-lane="{lane_index}" '
        f'data-index="{segment_index}" data-active="{str(active).lower()}" transform="translate({x:.1f} {y:.1f}) rotate({angle:.1f})">'
        f'<rect x="{-PAIRED_SEGMENT_WIDTH / 2:.1f}" y="{-PAIRED_SEGMENT_HEIGHT / 2:.1f}" '
        f'width="{PAIRED_SEGMENT_WIDTH}" height="{PAIRED_SEGMENT_HEIGHT}" rx="1" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        f'<line x1="{-PAIRED_SEGMENT_WIDTH / 2 + 1:.1f}" y1="{-PAIRED_SEGMENT_HEIGHT / 2 + 1.5:.1f}" '
        f'x2="{PAIRED_SEGMENT_WIDTH / 2 - 1:.1f}" y2="{-PAIRED_SEGMENT_HEIGHT / 2 + 1.5:.1f}" stroke="{highlight}" stroke-width="1"/></g>'
    )


def render_paired_pitch_gauge_tip_svg(
    x: float, y: float, angle: float, active: bool, direction_code: str, lane_index: int,
) -> str:
    fill, stroke, highlight = pitch_gauge_colors(active)
    return (
        f'<g class="paired-pitch-tip" data-direction="{direction_code}" data-lane="{lane_index}" data-index="6" '
        f'data-active="{str(active).lower()}" transform="translate({x:.1f} {y:.1f}) rotate({angle:.1f})">'
        f'<polygon points="{PAIRED_ARROW_POINTS}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        f'<line x1="-3.5" y1="-2" x2="1" y2="-2" stroke="{highlight}" stroke-width="1"/></g>'
    )


def render_pitch_gauge_tip_svg(
    x: float, y: float, angle: float, active: bool, direction_code: str, lane_index: int,
) -> str:
    fill, stroke, highlight = pitch_gauge_colors(active)
    return (
        f'<g class="pitch-gauge-tip" data-direction="{direction_code}" data-lane="{lane_index}" data-index="6" '
        f'data-active="{str(active).lower()}" transform="translate({x:.1f} {y:.1f}) rotate({angle:.1f})">'
        f'<polygon points="-6,-4.5 2,-4.5 7,0 2,4.5 -6,4.5" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
        f'<line x1="-4.5" y1="-3" x2="1.5" y2="-3" stroke="{highlight}" stroke-width="1"/></g>'
    )


def render_pitch_direction_gauge_svg(
    direction_code: str, movement: int, is_left: bool, lane_index: int = 0, paired: bool = False,
) -> list[str]:
    movement = min(7, max(0, movement))
    positions = pitch_gauge_segment_positions(direction_code, lane_index, is_left, paired)
    if paired:
        lines = [
            render_paired_pitch_gauge_segment_svg(x, y, angle, index < movement, direction_code, lane_index, index)
            for index, (x, y, angle) in enumerate(positions[:6])
        ]
        x, y, angle = positions[6]
        lines.append(render_paired_pitch_gauge_tip_svg(x, y, angle, movement == 7, direction_code, lane_index))
        return lines
    lines = [
        render_pitch_gauge_segment_svg(x, y, angle, index < movement, direction_code, lane_index, index)
        for index, (x, y, angle) in enumerate(positions[:6])
    ]
    x, y, angle = positions[6]
    lines.append(render_pitch_gauge_tip_svg(x, y, angle, movement == 7, direction_code, lane_index))
    return lines


def render_straight_markers_svg(second_fastballs: list[dict[str, Any]]) -> list[str]:
    lines = ['<g class="pitch-straight-area">']
    if second_fastballs:
        pitches = [("ストレート", "straight", 133, 132, "end"),
                   (pitch_display_name(second_fastballs[0].get("name")), "second", 147, 148, "start")]
    else:
        pitches = [("ストレート", "straight", 140, 140, "middle")]
    for name, kind, marker_x, label_x, anchor in pitches:
        lines.append(
            f'<text class="straight-label" data-kind="{kind}" x="{label_x}" y="40" '
            f'text-anchor="{anchor}" fill="#126bb0" font-size="12" font-weight="900">{e(name)}</text>'
        )
        lines.append(
            f'<g class="straight-marker" data-kind="{kind}" data-center-x="{marker_x}" data-center-y="49">'
            f'<polygon points="{marker_x - 4},52 {marker_x},46 {marker_x + 4},52" fill="#ff8b25" stroke="#dd5f12" stroke-width="1"/>'
            f'<line x1="{marker_x - 2.5}" y1="50.5" x2="{marker_x + 2.5}" y2="50.5" stroke="#ffd06a" stroke-width="1"/></g>'
        )
    lines.append("</g>")
    return lines


def render_pitch_chart_svg(balls: list[dict[str, Any]] | None, batting_throwing: str = "") -> str:
    is_left = str(batting_throwing).startswith("左投")
    second_fastballs: list[dict[str, Any]] = []
    for ball in balls or []:
        if ball.get("kind") == "second_fastball":
            second_fastballs.append(ball)
    lanes = build_pitch_chart_lanes(balls or [], is_left)

    lines = [
        '<svg viewBox="0 0 280 210" width="100%" height="100%" role="img" aria-label="変化球方向図">',
        '<rect x="5" y="5" width="270" height="200" rx="7" fill="#f7fcff" stroke="#cce8ff" stroke-width="3"/>',
    ]
    lines.extend(render_straight_markers_svg(second_fastballs))
    primary_lanes = {lane.direction_code: lane for lane in lanes if lane.lane_index == 0}
    secondary_lanes = [lane for lane in lanes if lane.lane_index == 1]
    paired_directions = {lane.direction_code for lane in secondary_lanes}
    gauge_lines: list[str] = []
    for direction_code in PITCH_GAUGE_GEOMETRY:
        primary = primary_lanes.get(direction_code)
        gauge_lines.extend(render_pitch_direction_gauge_svg(
            direction_code, primary.movement if primary else 0, is_left, 0,
            direction_code in paired_directions,
        ))
    for lane in secondary_lanes:
        gauge_lines.extend(render_pitch_direction_gauge_svg(
            lane.direction_code, lane.movement, is_left, 1, True,
        ))
    lines.extend(gauge_lines)
    lines.extend([
        '<g class="pitch-center-ball">',
        '<circle cx="140" cy="66" r="12" fill="#ffffff" stroke="#1597d4" stroke-width="3"/>',
        '<path d="M135 57 C131 61 131 71 135 75" fill="none" stroke="#e64d4d" stroke-width="1.5"/>',
        '<path d="M145 57 C149 61 149 71 145 75" fill="none" stroke="#e64d4d" stroke-width="1.5"/>',
        '</g>',
    ])

    label_lines: list[str] = []
    for lane in lanes:
        name_x, name_y, anchor = pitch_gauge_label_geometry(
            lane.direction_code, lane.lane_index, is_left,
            lane.direction_code in paired_directions,
        )
        label_lines.append(
            f'<text class="pitch-label" data-direction="{lane.direction_code}" data-lane="{lane.lane_index}" '
            f'x="{name_x}" y="{name_y}" text-anchor="{anchor}" fill="#126bb0" '
            f'font-size="12" font-weight="900">{e(lane.display_name)}</text>'
        )
    return "".join(lines + label_lines) + "</svg>"


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
    abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
    if player.get("role") == "野手":
        return abilities
    required = {"弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"}
    if required.issubset(abilities.keys()):
        return {key: abilities[key] for key in required}
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



def calculate_sub_position_fielding(fielding: int | float | str | None, aptitude: Any) -> int | None:
    mark = normalize_sub_position_aptitude(aptitude)
    rate = SUB_POSITION_FIELDING_RATES.get(mark)
    if rate is None:
        return None
    try:
        value = float(fielding)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(1, min(99, int(value * rate)))


def display_position_defense_value(player: dict[str, Any], full_position: str, mark: str, base_fielding: int | float | None) -> int | None:
    if mark == "－－" or not isinstance(base_fielding, int | float):
        return None
    if player.get("position") == full_position:
        return max(1, min(99, int(base_fielding)))
    return calculate_sub_position_fielding(base_fielding, mark)



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
            value_html = f'<span class="pp-defense-rank" style="color:{ui_rank_color(pos_rank)};">{e(pos_rank)}</span><span class="pp-defense-num">{e(mark)} {e(value)}</span>'
        else:
            value_html = '<span class="pp-defense-empty">－－</span>'
        cells.append(f'<div class="pp-defense-pos{main_cls}"><span class="pp-defense-short">{short}</span>{value_html}</div>')
    return render_ability_rows([("走力", f.get("走力")), ("肩力", f.get("肩力"))]) + '<div class="pp-defense-compact">' + ''.join(cells) + '</div>' + render_ability_rows([("守備力", f.get("守備力")), ("捕球", f.get("捕球"))])

def render_profile_right(player: dict[str, Any]) -> str:
    display_name = player.get("back_name") or player.get("name")
    items = [
        ("氏名", player.get("name"), " pp-profile-span-3"),
        ("年齢", f"{player.get('age')}歳", ""),
        ("誕生日", birthday_display(player), ""),
        ("投打", player.get("batting_throwing"), ""),
        ("国籍", player.get("nationality"), ""),
        ("実国籍", player.get("actual_nationality"), ""),
        ("肌色", player.get("skin_color") or "", ""),
        ("出身地", player.get("birthplace"), ""),
        ("身長", f"{player.get('height')}cm", ""),
        ("体重", f"{player.get('weight')}kg", ""),
        ("投球フォーム", form_display(player, "pitching") if player.get("role") == "投手" else "", ""),
        ("打撃フォーム", form_display(player, "batting"), ""),
        ("バット", player.get("bat_color"), ""),
        ("グラブ", player.get("glove_color"), ""),
        ("左リストバンド", (player.get("wristband_left_color") if int(player.get("wristband_left_enabled") or 0) else "なし") if "wristband_left_enabled" in player else "", ""),
        ("右リストバンド", (player.get("wristband_right_color") if int(player.get("wristband_right_enabled") or 0) else "なし") if "wristband_right_enabled" in player else "", ""),
        ("ドラフト所属区分", player.get("draft_source_type") if player.get("category") == "ドラフト候補用" else "", ""),
        ("表示名", display_name, " pp-profile-span-3"),
    ]
    items = [(label, value, span_class) for label, value, span_class in items if value not in (None, "")]
    cells = ''.join(
        f'<div class="pp-profile-label">{e(label)}</div><div class="pp-profile-value{span_class}">{e(value)}</div>'
        for label, value, span_class in items
    )
    return '<div class="pp-profile-table">' + cells + '</div>'


def render_generation_info_html(player: dict[str, Any]) -> str:
    items = [
        ("カテゴリ", player.get("category")),
        ("タイプ", player.get("player_type")),
        ("選手格", player.get("player_class")),
        ("アーキタイプ", player.get("archetype")),
        ("ポジションスタイル", player.get("position_style")),
        ("完成度", player.get("development_stage")),
        ("獲得目的", player.get("acquisition_role")),
        ("弱点プロファイル", player.get("weakness_profile")),
        ("seed", player.get("seed")),
    ]
    items = [(label, value) for label, value in items if value not in (None, "")]
    cards = ''.join(f'<div class="pp-generation-card"><span class="pp-mini-label">{e(label)}</span>{e(value)}</div>' for label, value in items)
    return '<details class="pp-generation-info"><summary>生成情報</summary><div class="pp-generation-grid">' + cards + '</div></details>'


def player_uniform_number(player: dict[str, Any]) -> int:
    return random.Random(f"number:{player.get('seed', 0)}:{player.get('name', '')}").randint(0, 99)


def role_stats_placeholder(player: dict[str, Any]) -> str:
    if player.get("role") == "投手":
        return "防 ----　--勝 --敗 --HP --S"
    return "率 .---　--本 --点 --盗"


def role_form_placeholder(player: dict[str, Any]) -> str:
    if player.get("role") == "投手":
        return form_display(player, "pitching") or "－"
    return form_display(player, "batting") or "－"


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
    growth_html = special_cell_html(growth_type_label(player.get("growth_type")), "green")
    if not categories:
        cells.extend([
            '<div class="pp-usage-cell pp-usage-label">起用法</div>',
            f'<div class="pp-usage-cell pp-usage-value">{growth_html}</div>',
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
        cells.extend([
            '<div class="pp-usage-cell pp-usage-label"></div>',
            f'<div class="pp-usage-cell pp-usage-value">{growth_html}</div>',
            '<div class="pp-usage-cell pp-usage-empty"></div>',
            '<div class="pp-usage-cell pp-usage-empty"></div>',
        ])
    target_count = special_grid_cell_count(32, 0, len(cells))
    while len(cells) < target_count:
        cells.append('<div class="pp-usage-cell pp-usage-empty"></div>')
    return '<div class="pp-usage-grid">' + ''.join(cells) + '</div>'

def set_selected_tab(tab_key: str, label: str) -> None:
    st.session_state[tab_key] = label


def render_header_html(p: dict[str, Any]) -> str:
    category_mark = {"架空球団用": "架", "ドラフト候補用": "候", "助っ人外国人用": "外"}.get(str(p.get("category", "")), "球")
    escaped_name = e(p.get("name"))
    nameplate_style = nameplate_background_css(get_player_nameplate_colors(p))
    style_attr = f' style="{e(nameplate_style)}"' if nameplate_style else ""
    return f"""
      <div class="pp-header">
        <div class="pp-header-main">
          <div class="pp-name-line">
            <div class="pp-name" title="{escaped_name}"{style_attr}>{escaped_name}</div>
            <div class="pp-category-mark" title="{e(p.get('category'))}">{e(category_mark)}</div>
            <div class="pp-number-box">{player_uniform_number(p)}</div>
          </div>
          <div class="pp-posline">{e(header_position_text(p))}</div>
        </div>
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
        left = render_ability_rows([("守備位置", pos)]) + render_trajectory_row_html(fa.get("弾道")) + render_ability_rows([("ミート", fa.get("ミート")), ("パワー", fa.get("パワー")), ("走力", fa.get("走力")), ("肩力", fa.get("肩力")), ("守備力", fa.get("守備力")), ("捕球", fa.get("捕球"))])
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
            left = render_trajectory_row_html(fa.get("弾道")) + render_ability_rows([("ミート", fa.get("ミート")), ("パワー", fa.get("パワー")), ("走力", fa.get("走力")), ("肩力", fa.get("肩力")), ("守備力", fa.get("守備力")), ("捕球", fa.get("捕球"))])
        right = render_profile_right(p) + render_generation_info_html(p)
    body_class = "pp-body pp-body-pitcher" if effective_tab == "投手能力" else "pp-body"
    return f'<div class="{body_class}"><div>{left}</div><div>{right}</div></div>'

def player_unique_id(player: dict[str, Any], index: int) -> str:
    db_id = player.get("id")
    if db_id not in (None, ""):
        return f"db:{db_id}"
    return f"latest:{player.get('seed', '')}:{player.get('name', '')}:{player.get('position', '')}:{index}"


def player_label(player: dict[str, Any], index: int) -> str:
    return f"{index + 1}. {player.get('name')}｜{player.get('position')}｜{player.get('player_type')}｜{player.get('age')}歳｜{player.get('batting_throwing')}"


def relative_player_id(player_ids: list[str], current_id: str | None, offset: int) -> str | None:
    if not player_ids:
        return None
    if current_id not in player_ids:
        return player_ids[0]
    current_index = player_ids.index(current_id)
    next_index = max(0, min(len(player_ids) - 1, current_index + offset))
    return player_ids[next_index]


def select_relative_player(*, player_ids: list[str], selected_key: str, offset: int) -> None:
    st.session_state[selected_key] = relative_player_id(player_ids, st.session_state.get(selected_key), offset)


def render_player_browser(players: list[dict[str, Any]], master: MasterData, key_prefix: str) -> None:
    if not players:
        st.info("表示する選手がまだありません。左の条件で生成してください。")
        return
    selected_player_id_key = f"{key_prefix}_selected_player_id"
    player_ids = [player_unique_id(player, index) for index, player in enumerate(players)]
    if st.session_state.get(selected_player_id_key) not in player_ids:
        st.session_state[selected_player_id_key] = player_ids[0]
    player_by_id = dict(zip(player_ids, players, strict=True))
    label_by_id = {player_id: player_label(player, index) for index, (player_id, player) in enumerate(zip(player_ids, players, strict=True))}
    selected_player_id = st.session_state[selected_player_id_key]
    current_index = player_ids.index(selected_player_id)
    st.markdown('<div class="pp-list-note">選手一覧から詳細表示する選手を選択</div>', unsafe_allow_html=True)
    previous_col, select_col, next_col = st.columns(
        [0.16, 0.68, 0.16],
        gap="small",
    )
    with previous_col:
        st.button("前の選手", use_container_width=True, disabled=current_index <= 0, key=f"{key_prefix}_prev", on_click=select_relative_player, kwargs={"player_ids": player_ids, "selected_key": selected_player_id_key, "offset": -1})
    with select_col:
        selected_player_id = st.selectbox("選手一覧", player_ids, format_func=lambda player_id: label_by_id[player_id], key=selected_player_id_key, label_visibility="collapsed")
    current_index = player_ids.index(selected_player_id)
    with next_col:
        st.button("次の選手", use_container_width=True, disabled=current_index >= len(players) - 1, key=f"{key_prefix}_next", on_click=select_relative_player, kwargs={"player_ids": player_ids, "selected_key": selected_player_id_key, "offset": 1})
    render_detail_panel(player_by_id[selected_player_id], master, key_prefix)

def main() -> None:
    st.set_page_config(page_title="パワプロ風 架空選手生成", page_icon="⚾", layout="wide")
    init_db()
    master = load_master_data()
    inject_powerpro_ui_css()
    st.markdown('<div class="pp-title">⚾ 選手能力詳細ジェネレーター</div>', unsafe_allow_html=True)
    render_page_description("投手/野手、カテゴリ、生成人数だけを選ぶと、ゲーム風の能力詳細画面で確認できます。")
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
        used_names: set[str] = set()
        seeds = generate_batch_seeds(total_count)
        for index, seed in enumerate(seeds):
            players.append(generate_player(role, category, master, seed=seed, used_names=used_names))
            progress.progress((index + 1) / total_count, text=f"選手を生成中です... {index + 1}/{total_count}")
        saved_count = save_players(players)
        progress.empty()
        st.session_state["latest_players"] = players
        st.session_state["latest_selected_player_id"] = player_unique_id(players[0], 0) if players else None
        st.session_state["latest_selected_player_tab"] = "投手能力" if role == "投手" else "野手能力"
        render_success_message(f"{len(players)}人の選手を生成し、SQLiteに{saved_count}件保存しました。")
    render_player_browser(st.session_state.get("latest_players", []), master, "latest")
    latest_players = st.session_state.get("latest_players", [])
    latest_ids = [player_unique_id(player, index) for index, player in enumerate(latest_players)]
    latest_selected_id = relative_player_id(latest_ids, st.session_state.get("latest_selected_player_id"), 0)
    latest_player_by_id = dict(zip(latest_ids, latest_players, strict=True)) if latest_players else {}
    latest_role = latest_player_by_id[latest_selected_id].get("role") if latest_selected_id in latest_player_by_id else "投手"
    latest_tab = normalize_selected_tab_value({"role": latest_role}, st.session_state.get("latest_selected_player_tab"))
    role_help = "球速、制球、スタミナ、変化球と投手特殊能力を確認します。" if latest_role == "投手" else "打撃、走塁、守備の基礎能力と野手特殊能力を確認します。"
    help_messages = {
        "投手能力": "球速、制球、スタミナ、変化球と投手特殊能力を確認します。",
        "野手能力": "打撃、走塁、守備の基礎能力と野手特殊能力を確認します。",
        "守備・起用": "メインポジション、サブポジション、起用適性を確認します。",
        "プロフィール": "氏名、年齢、投打、国籍、出身地、体格を確認します。生成条件は「生成情報」から確認できます。",
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
