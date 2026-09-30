import csv
import copy
import hashlib
import itertools
import json
import random
import re
import sqlite3
import math
import unicodedata
from functools import lru_cache, partial
from html import escape
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from generator.foreign_names import generate_foreign_profile

APP_VERSION = "1.0.0"
APP_NAME = "パワプロ風 架空選手生成"
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
    # 高齢まで現役に残る選手は、標準～晩成型へ緩やかに寄せる。
    "active_veteran": {"very_early": 0.20, "early": 0.35, "normal": 1.20, "late": 1.80, "very_late": 2.20},
    "veteran_survivor": {"very_early": 0.50, "early": 0.70, "normal": 1.10, "late": 1.10, "very_late": 1.20},
}
FICTIONAL_ROSTER_AGE_WEIGHTS = [
    (18, 18), (19, 18),
    (20, 34), (21, 35), (22, 39),
    (23, 75), (24, 82), (25, 88), (26, 85),
    (27, 82), (28, 80), (29, 75), (30, 63),
    (31, 46), (32, 42), (33, 35), (34, 27),
    (35, 25), (36, 19),
    (37, 12), (38, 8), (39, 5),
    (40, 2), (41, 2), (42, 1), (43, 1), (44, 1), (45, 1), (46, 1),
]
# 架空球団（日本人）野手のポジション比率。実在12球団（2022〜2026）の日本人野手に合わせる。
# 捕手は1球団7人前後、一塁手は他ポジションからのサブポジで賄うため少ない。
FICTIONAL_FIELDER_POSITION_WEIGHTS = [("捕手", 21.5), ("一塁手", 5.5), ("二塁手", 10.5), ("三塁手", 11.5), ("遊撃手", 17.5), ("外野手", 33.5)]
POSITIONS = {
    "投手": ["先発", "中継ぎ", "抑え"],
    "野手": ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"],
}
POSITION_PHYSIQUE = {
    "投手": {"height_mean": 182.44, "height_sd": 6.41, "height_min": 167, "height_max": 213, "weight_mean": 88.22, "weight_per_cm": 0.930, "weight_resid_sd": 6.63, "weight_min": 67, "weight_max": 122},
    "捕手": {"height_mean": 178.00, "height_sd": 4.36, "height_min": 170, "height_max": 190, "weight_mean": 87.16, "weight_per_cm": 0.803, "weight_resid_sd": 5.81, "weight_min": 73, "weight_max": 112},
    "一塁手": {"height_mean": 184.00, "height_sd": 6.61, "height_min": 173, "height_max": 201, "weight_mean": 97.07, "weight_per_cm": 1.055, "weight_resid_sd": 8.98, "weight_min": 76, "weight_max": 117},
    "二塁手": {"height_mean": 175.88, "height_sd": 5.41, "height_min": 163, "height_max": 186, "weight_mean": 79.98, "weight_per_cm": 0.976, "weight_resid_sd": 6.51, "weight_min": 66, "weight_max": 97},
    "三塁手": {"height_mean": 181.40, "height_sd": 5.37, "height_min": 170, "height_max": 196, "weight_mean": 91.05, "weight_per_cm": 1.626, "weight_resid_sd": 6.66, "weight_min": 73, "weight_max": 126},
    "遊撃手": {"height_mean": 177.66, "height_sd": 5.39, "height_min": 164, "height_max": 189, "weight_mean": 79.99, "weight_per_cm": 0.968, "weight_resid_sd": 5.09, "weight_min": 65, "weight_max": 95},
    "外野手": {"height_mean": 180.98, "height_sd": 6.01, "height_min": 170, "height_max": 203, "weight_mean": 87.21, "weight_per_cm": 1.212, "weight_resid_sd": 6.93, "weight_min": 67, "weight_max": 139},
}
FIELDER_PHYSIQUE_EFFECTS = {
    "power": {"height": 4.16, "build": 4.83, "cap": 13.0},
    "speed": {"height": -2.67, "build": -4.40, "cap": 11.0},
    "fielding": {"height": -2.62, "build": -2.40, "cap": 8.0},
    "catching": {"height": -1.40, "build": -1.23, "cap": 4.0},
    "arm": {"height": 1.16, "build": 0.0, "cap": 3.0},
}
PITCHER_PHYSIQUE_EFFECTS = {
    "velocity": {"height": 1.42, "build": 0.37, "cap": 3.5},
    "control": {"height": -1.5, "build": 0.0, "cap": 4.0},
}
FIELDER_PHYSIQUE_ABILITY_KEYS = {"power": "パワー", "speed": "走力", "fielding": "守備力", "catching": "捕球", "arm": "肩力"}
PITCHER_PHYSIQUE_ABILITY_KEYS = {"velocity": "球速", "control": "コントロール"}
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
FOREIGN_PLAYER_CLASS_TENURE_MULTIPLIERS = {
    "1": {"大物実績者": 0.85, "主力期待級": 1.00, "レギュラー競争級": 1.15, "保険・バックアップ級": 1.20, "育成素材型": 1.20, "再生候補": 1.15},
    "2-3": {"大物実績者": 1.10, "主力期待級": 1.25, "レギュラー競争級": 1.10, "保険・バックアップ級": 0.70, "育成素材型": 0.55, "再生候補": 0.75},
    "4+": {"大物実績者": 1.60, "主力期待級": 1.70, "レギュラー競争級": 1.10, "保険・バックアップ級": 0.25, "育成素材型": 0.12, "再生候補": 0.35},
}
FOREIGN_PLAYER_CLASS_ROUTE_MULTIPLIERS = {
    "north_america_pro": {"大物実績者": 1.05, "主力期待級": 1.04},
    "cuba_domestic": {"主力期待級": 1.08, "レギュラー競争級": 1.05},
    "development_direct": {"レギュラー競争級": 1.08, "育成素材型": 1.18},
    "asian_pro": {"大物実績者": 1.08, "主力期待級": 1.08},
}
FOREIGN_WEAKNESS_TENURE_MULTIPLIERS = {
    "投手": {
        "1": {},
        "2-3": {"低制球": 0.72, "球種不足": 0.88, "変化量不足": 0.88, "安定性不安": 0.80, "明確な弱点なし": 1.30},
        "4+": {"低制球": 0.22, "球種不足": 0.55, "変化量不足": 0.60, "安定性不安": 0.40, "明確な弱点なし": 2.20},
    },
    "野手": {
        "1": {},
        "2-3": {"低ミート": 0.75, "低守備": 0.82, "低捕球": 0.82, "明確な弱点なし": 1.30},
        "4+": {"低ミート": 0.30, "低走力": 1.05, "低守備": 0.50, "低捕球": 0.50, "送球不安": 0.75, "明確な弱点なし": 2.20},
    },
}
FOREIGN_ARCHETYPE_TENURE_MULTIPLIERS = {
    "投手": {
        "1": {}, "2-3": {"総合": 1.06, "制球": 1.12, "速球": 0.96},
        "4+": {"総合": 1.15, "制球": 1.30, "速球": 0.90},
    },
    "野手": {
        "1": {}, "2-3": {"バランス": 1.06, "巧打": 1.08, "俊足": 0.90},
        "4+": {"バランス": 1.18, "巧打": 1.25, "長打": 1.08, "俊足": 0.58},
    },
}
FOREIGN_ARCHETYPE_ROUTE_MULTIPLIERS = {
    "north_america_pro": {"投手": {"速球": 1.04}, "野手": {"長打": 1.04}},
    "cuba_domestic": {"投手": {"速球": 1.04}, "野手": {"長打": 1.10, "強肩": 1.06}},
    "development_direct": {"投手": {"速球": 1.06}, "野手": {"俊足": 1.08, "強肩": 1.05}},
    "asian_pro": {"投手": {"総合": 1.06, "制球": 1.08}, "野手": {"バランス": 1.06, "巧打": 1.08}},
}
FOREIGN_ACQUISITION_TENURE_MULTIPLIERS = {
    "1": {"保険要員": 1.12, "若手育成": 1.12, "再生候補": 1.12},
    "2-3": {"先発候補": 1.06, "勝ちパターン候補": 1.08, "主砲候補": 1.08, "中軸候補": 1.08, "保険要員": 0.82, "若手育成": 0.78, "再生候補": 0.82},
    "4+": {"先発候補": 1.12, "勝ちパターン候補": 1.16, "クローザー候補": 1.10, "主砲候補": 1.15, "中軸候補": 1.15, "保険要員": 0.45, "若手育成": 0.30, "再生候補": 0.40},
}
FOREIGN_ACQUISITION_ROUTE_MULTIPLIERS = {
    "north_america_pro": {"先発候補": 1.03, "勝ちパターン候補": 1.03, "主砲候補": 1.04, "中軸候補": 1.03},
    "cuba_domestic": {"主砲候補": 1.08, "中軸候補": 1.06},
    "development_direct": {"若手育成": 1.12, "保険要員": 1.05},
    "asian_pro": {"先発候補": 1.06, "中軸候補": 1.05, "内野守備補強": 1.05},
}
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
    "フル出場", "人気者", "ミート多用", "強振多用", "積極打法", "慎重打法",
    "積極盗塁", "慎重盗塁", "積極走塁", "積極守備", "チームプレイ○", "チームプレイ×",
    "速球中心", "変化球中心", "投球位置左", "投球位置右", "テンポ○",
}
# 非ランク系特殊能力の表示順（同じ表示場所の中だけで並べ替える。区分コメントは読みやすさのためだけのもの）。
# マスターデータの定義順は生成ロジックに影響するため変えず、表示直前にこの順で安定ソートする。
SPECIAL_ABILITY_DISPLAY_ORDER = [
    # --- 投手系 ---
    "重い球", "低め○", "内角攻め", "クロスファイヤー", "荒れ球", "ジャイロボール",
    "真っスラ", "ナチュラルシュート", "緩急○", "リリース○", "キレ○", "球持ち○",
    "球速安定", "牽制○", "打球反応○", "ストライク先行", "奪三振", "安全圏○",
    "対ランナー", "要所○", "立ち上がり○", "尻上がり", "緊急登板○", "火消し",
    "回またぎ○", "勝ち運", "逃げ球", "根性", "力配分", "全開", "闘志",
    "ポーカーフェイス", "対強打者○", "投手存在感", "フライボールピッチャー",
    "ゴロピッチャー", "投打躍動",
    # --- 投手系（赤特）---
    "軽い球", "抜け球", "ボール先行", "四球", "対ランナー×", "寸前",
    "スロースターター", "乱調", "負け運", "一発", "短気",
    # --- 捕手・守備系 ---
    "ささやき破り", "ホーム死守", "ブロッキング", "フレーミング○", "フレーミング◎",
    # --- 打撃系 ---
    "パワーヒッター", "ラインドライブ", "アベレージヒッター", "プルヒッター",
    "広角打法", "流し打ち", "悪球打ち", "対ストレート○", "対変化球○",
    "ハイボールヒッター", "ローボールヒッター", "インコースヒッター",
    "アウトコースヒッター", "バント○", "バント職人", "初球○", "窮地○", "粘り打ち",
    "カット打ち", "固め打ち", "マルチ弾", "リベンジ", "帳尻合わせ", "ダメ押し",
    "逆境○", "チャンスメーカー", "満塁男", "代打○", "サヨナラ男", "決勝打",
    "意外性", "いぶし銀", "内野安打○",
    # --- 走塁・守備系 ---
    "プレッシャーラン", "ヘッドスライディング", "ホーム突入", "かく乱",
    "守備職人", "レーザービーム", "高速チャージ",
    # --- その他 ---
    "対エース○", "野手存在感", "死球集中", "ムード○", "国際大会○",
    # --- 野手系（赤特）---
    "三振", "併殺", "エラー", "ムード×", "国際大会×",
    "人気者",
    # --- 作戦・起用系 ---
    "強振多用", "ミート多用", "選球眼", "積極打法", "慎重打法", "積極盗塁",
    "慎重盗塁", "積極走塁", "積極守備", "チームプレイ○", "チームプレイ×",
    "投手調子安定", "投手調子極端", "野手調子安定", "野手調子極端",
    "速球中心", "変化球中心", "テンポ○",
    "投球位置左", "投球位置右", "フル出場",
]
SPECIAL_ABILITY_DISPLAY_INDEX = {name: index for index, name in enumerate(SPECIAL_ABILITY_DISPLAY_ORDER)}
PITCHER_USAGE_ORDER = ["フル出場", "速球中心", "変化球中心", "投球位置左", "投球位置右", "テンポ○", "人気者"]
FIELDER_USAGE_ORDER = ["フル出場", "ミート多用", "強振多用", "積極打法", "慎重打法", "積極盗塁", "慎重盗塁", "積極走塁", "積極守備", "チームプレイ○", "チームプレイ×", "人気者"]
# 変化球チャート（実機の能力画面準拠）。寸法はすべてセル間隔 u を基準にした比率で持つ。
# 右投げ基準で定義し、左投げは描画時に x → PITCH_CHART_WIDTH - x で左右反転する。
# ただしフォーク方向の2列（1球種目が左、2球種目が右）とストレート表示は左投げでも反転しない。
# 球種名は略さず正式名で表示する（実機準拠）。
PITCH_CHART_WIDTH = 280
PITCH_CHART_HEIGHT = 210
PITCH_CHART_UNIT = 10.0           # 実機のチャート幅 ≈ 28u に合わせる
PITCH_CHART_CENTER = (140.0, 72.0)
_DIAG = math.sqrt(0.5)
# axis: 中心から先端へ向かう単位ベクトル / lane_side: 2球種時に1球種目の列を置く側（上・中心寄り）
PITCH_GAUGE_GEOMETRY = {
    "1": {"kind": "side", "axis": (1.0, 0.0), "lane_side": (0.0, -1.0)},
    "2": {"kind": "diagonal", "axis": (_DIAG, _DIAG), "lane_side": (_DIAG, -_DIAG)},
    "3": {"kind": "down", "axis": (0.0, 1.0), "lane_side": (-1.0, 0.0)},
    "4": {"kind": "diagonal", "axis": (-_DIAG, _DIAG), "lane_side": (-_DIAG, -_DIAG)},
    "5": {"kind": "side", "axis": (-1.0, 0.0), "lane_side": (0.0, -1.0)},
}
PITCH_GAUGE_SEGMENT_COUNT = 7
PITCH_BAR_LENGTH = 7.5            # バー全長（u）
PITCH_BAR_START = 1.05 + 0.75     # ボール外周半径 + 隙間（u）
PITCH_CELL_PITCH = 1.0            # セル間隔（u）
PITCH_CELL_LENGTH = 0.75          # セル内寸（u）
PITCH_CELL_DIVIDER = 0.25         # 仕切り（u）
PITCH_SINGLE_THICKNESS = 1.375    # 単体バー太さ（u）
PITCH_SINGLE_BORDER = 0.25
PITCH_PAIRED_THICKNESS = 1.8      # 2列バーのフレーム全体の太さ（u）
PITCH_PAIRED_BORDER = 0.2
PITCH_BAR_CLEARANCE = 0.09      # 隣のバーとの最小すき間（u）。全方向単体時のすき間（約0.099u）を超えない値
PITCH_FRAME_COLOR = "#008FF5"
PITCH_CELL_EMPTY_START = "#0A96FF"
PITCH_CELL_EMPTY_END = "#42B5FF"
PITCH_CELL_ACTIVE_COLORS = ("#FF7E00", "#FFC800", "#FFDA00", "#FFA700", "#FF5C00", "#FF1D00", "#FF3100")
PITCH_STRAIGHT_FILL = "#FF7E00"
PITCH_LABEL_COLOR = "#2177C0"
PITCH_LABEL_FONT_SIZE = 1.2       # u
PITCH_LABEL_MAX_WIDTH = 11.0      # u（これを超える球種名は横方向に圧縮）
PITCH_SIDE_LABEL_CENTER = 7.2     # 横方向ラベルの中心（ボール中心からの距離, u）
PITCH_DIAGONAL_LABEL_CENTER = 7.4 # 斜め方向ラベルの中心（ボール中心からの横距離, u）
PITCH_DOWN_LABEL_OFFSET = 1.2     # フォーク方向2球種のラベル端（ボール中心からの横距離, u）
PITCH_CHART_BACKGROUND = "#EDF5F6"
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
                roster_origin TEXT NOT NULL DEFAULT '',
                foreign_route TEXT NOT NULL DEFAULT '',
                entry_route TEXT NOT NULL DEFAULT '',
                pro_entry_age INTEGER NOT NULL DEFAULT 0,
                pro_years INTEGER NOT NULL DEFAULT 0,
                npb_years INTEGER NOT NULL DEFAULT 0,
                npb_first_entry_year INTEGER NOT NULL DEFAULT 0,
                npb_stint_start_year INTEGER NOT NULL DEFAULT 0,
                is_returnee INTEGER NOT NULL DEFAULT 0,
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
                height_cm INTEGER,
                weight_kg INTEGER,
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
            "roster_origin": "TEXT NOT NULL DEFAULT ''",
            "foreign_route": "TEXT NOT NULL DEFAULT ''",
            "entry_route": "TEXT NOT NULL DEFAULT ''",
            "pro_entry_age": "INTEGER NOT NULL DEFAULT 0",
            "pro_years": "INTEGER NOT NULL DEFAULT 0",
            "npb_years": "INTEGER NOT NULL DEFAULT 0",
            "npb_first_entry_year": "INTEGER NOT NULL DEFAULT 0",
            "npb_stint_start_year": "INTEGER NOT NULL DEFAULT 0",
            "is_returnee": "INTEGER NOT NULL DEFAULT 0",
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
            "height_cm": "INTEGER",
            "weight_kg": "INTEGER",
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


def weighted_choice(rng: random.Random, items: list[tuple[Any, int | float]]) -> Any:
    return rng.choices([i[0] for i in items], weights=[i[1] for i in items], k=1)[0]


def make_sub_rng(seed: int, namespace: str) -> random.Random:
    """Return a stable namespaced RNG without consuming the caller's RNG."""
    payload = f"{int(seed)}:{namespace}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def clone_rng(rng: random.Random) -> random.Random:
    cloned = random.Random()
    cloned.setstate(rng.getstate())
    return cloned


def sample_truncated_normal(
    rng: random.Random,
    mean: float,
    sd: float,
    low: float,
    high: float,
    max_attempts: int = 100,
) -> float:
    for _ in range(max_attempts):
        value = rng.gauss(mean, sd)
        if low <= value <= high:
            return value
    return min(high, max(low, mean))


def physique_position(role: str, position: str) -> str:
    return "投手" if role == "投手" else position


def generate_height(position: str, rng: random.Random) -> int:
    params = POSITION_PHYSIQUE[position]
    return int(round(sample_truncated_normal(
        rng, params["height_mean"], params["height_sd"], params["height_min"], params["height_max"]
    )))


def expected_weight_for_height(position: str, height_cm: int) -> float:
    params = POSITION_PHYSIQUE[position]
    return params["weight_mean"] + params["weight_per_cm"] * (height_cm - params["height_mean"])


def generate_weight(position: str, height_cm: int, rng: random.Random) -> int:
    params = POSITION_PHYSIQUE[position]
    expected_weight = expected_weight_for_height(position, height_cm)
    return int(round(sample_truncated_normal(
        rng, expected_weight, params["weight_resid_sd"], params["weight_min"], params["weight_max"]
    )))


def generate_physique(seed: int, role: str, position: str) -> tuple[int, int]:
    key = physique_position(role, position)
    rng = make_sub_rng(seed, "physique_v1")
    height_cm = generate_height(key, rng)
    return height_cm, generate_weight(key, height_cm, rng)


def physique_indices(position: str, height_cm: int, weight_kg: int) -> tuple[float, float]:
    params = POSITION_PHYSIQUE[position]
    z_height = (height_cm - params["height_mean"]) / params["height_sd"]
    z_build = (weight_kg - expected_weight_for_height(position, height_cm)) / params["weight_resid_sd"]
    return max(-2.5, min(2.5, z_height)), max(-2.5, min(2.5, z_build))


def physique_effect_deltas(effects: dict[str, dict[str, float]], z_height: float, z_build: float) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for key, effect in effects.items():
        raw = effect["height"] * z_height + effect["build"] * z_build
        deltas[key] = max(-effect["cap"], min(effect["cap"], raw))
    return deltas


def apply_fielder_physique_effects(values: dict[str, int], z_height: float, z_build: float) -> dict[str, float]:
    deltas = physique_effect_deltas(FIELDER_PHYSIQUE_EFFECTS, z_height, z_build)
    for key, delta in deltas.items():
        values[FIELDER_PHYSIQUE_ABILITY_KEYS[key]] += round(delta)
    return deltas


def apply_pitcher_physique_effects(values: dict[str, int], z_height: float, z_build: float) -> dict[str, float]:
    deltas = physique_effect_deltas(PITCHER_PHYSIQUE_EFFECTS, z_height, z_build)
    for key, delta in deltas.items():
        values[PITCHER_PHYSIQUE_ABILITY_KEYS[key]] += round(delta)
    return deltas


def trajectory_physique_adjustment(z_height: float, z_build: float) -> float:
    return max(-0.54, min(0.54, 0.155 * z_height + 0.210 * z_build))


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
# 架空球団（日本人）の入団経路とプロ入り年齢。実在（2026）の「年齢 − プロ年数」に合わせ、
# 経路ごとのプロ入り年齢を 高卒18〜19・大卒22〜23・社会人24〜27・独立・クラブ20〜22 に収める。
# 「その他」は実在1%強なので少なくする。
FICTIONAL_ENTRY_ROUTE_WEIGHTS = [("高卒", 31), ("大卒", 45), ("社会人", 17), ("独立・クラブ", 3), ("その他", 1.5)]
FICTIONAL_ENTRY_ROUTE_AGE_WEIGHTS = {
    "20-21": [("高卒", 94), ("独立・クラブ", 5), ("その他", 1)],
    22: [("高卒", 59), ("大卒", 38), ("社会人", 1), ("独立・クラブ", 1), ("その他", 1)],
    23: [("高卒", 43), ("大卒", 54), ("社会人", 1), ("独立・クラブ", 1), ("その他", 1)],
    "24-25": [("高卒", 36), ("大卒", 54), ("社会人", 8), ("独立・クラブ", 1), ("その他", 1)],
    "27-30": [("高卒", 28), ("大卒", 46), ("社会人", 21), ("独立・クラブ", 3), ("その他", 1.5)],
    "31-34": [("高卒", 22), ("大卒", 46), ("社会人", 27), ("独立・クラブ", 3), ("その他", 1.5)],
}
# 高卒・大卒の2つの年齢の比は実在の同じ経路の中の比率（高卒 17：18 ＝ 31：69、大卒 21：22 ＝ 46：54）。
FICTIONAL_ENTRY_AGE_WEIGHTS = {
    "高卒": [(18, 31), (19, 69)],
    "大卒": [(22, 46), (23, 54)],
    "社会人": [(23, 2), (24, 40), (25, 42), (26, 10), (27, 6)],
    "独立・クラブ": [(20, 30), (21, 45), (22, 25)],
    # 実在にもごく少数いる遅いプロ入り（年齢 − プロ年数が27以上は0.3%）は「その他」に残す。
    "その他": [(19, 2), (20, 4), (21, 8), (22, 14), (23, 14), (24, 10), (25, 6), (26, 2), (27, 3), (28, 2), (30, 2), (32, 1)],
}
# 若手素材型の上限（プロ6年目以内・26歳以下）
FICTIONAL_YOUNG_MATERIAL_MAX_AGE = 26
FICTIONAL_YOUNG_MATERIAL_MAX_PRO_YEARS = 6
NPB_CURRENT_YEAR = 2026
FICTIONAL_FOREIGN_DOMESTIC_ROUTE_RATE = 0.04
FOREIGN_RETURNEE_RATE = 0.035
# 2025決定版の12球団スナップショットで観測した外国人補強の投手数・野手数。
# 個別選手生成の出現率とは分離し、ロスター層でのみ使用する。
FOREIGN_TEAM_IMPORT_COMPOSITION_WEIGHTS = [
    ((6, 1), 1),
    ((2, 2), 1),
    ((4, 3), 2),
    ((3, 2), 2),
    ((4, 4), 1),
    ((3, 3), 2),
    ((4, 1), 1),
    ((2, 3), 1),
    ((4, 2), 1),
]
# 2026実在12球団の静的ロスターで観測した投手数・野手数の組。
# 支配下・育成の区分は元データにないため、全掲載選手のスナップショットとして扱う。
TEAM_ROSTER_COMPOSITION_WEIGHTS = [
    ((37, 28), 1),
    ((32, 34), 2),
    ((33, 34), 1),
    ((35, 31), 2),
    ((31, 36), 1),
    ((34, 32), 2),
    ((35, 34), 1),
    ((32, 31), 1),
    ((32, 32), 1),
]
# 2024→2025の同球団残留32人 / 2024外国人73人。
# role別・tenure別の差は補正に使えるほど安定していないため、単一率のみを使う。
FOREIGN_TEAM_RETENTION_RATE = 32 / 73
TEAM_ROSTER_DOMESTIC_MAX_ATTEMPTS = 1000
# 2026実在12球団で1人以上いたpositionの観測最小値。
# 実在最小が0だった三塁手には保証を設けない。
TEAM_ROSTER_POSITION_MINIMUMS = {
    "捕手": 6,
    "一塁手": 1,
    "二塁手": 1,
    "遊撃手": 3,
    "外野手": 9,
}
FOREIGN_ROUTES = {
    "north_america_pro",
    "cuba_domestic",
    "latin_development",
    "korea_pro",
    "taiwan_pro",
    "taiwan_amateur_direct",
    "north_america_amateur_direct",
    "other_foreign_pro",
}
FOREIGN_ROUTE_LABELS = {
    "north_america_pro": "北米プロ",
    "cuba_domestic": "キューバ国内リーグ",
    "latin_development": "中南米育成",
    "korea_pro": "韓国プロ",
    "taiwan_pro": "台湾プロ",
    "taiwan_amateur_direct": "台湾アマ直接",
    "north_america_amateur_direct": "北米アマ直接",
    "other_foreign_pro": "その他海外プロ",
}
FOREIGN_ROUTE_WEIGHTS = {
    "投手": [
        ("north_america_pro", 795), ("cuba_domestic", 55), ("latin_development", 47),
        ("korea_pro", 39), ("taiwan_pro", 8), ("taiwan_amateur_direct", 24),
        ("north_america_amateur_direct", 24), ("other_foreign_pro", 8),
    ],
    "野手": [
        ("north_america_pro", 820), ("cuba_domestic", 82), ("latin_development", 35),
        ("korea_pro", 12), ("taiwan_pro", 12), ("taiwan_amateur_direct", 2),
        ("north_america_amateur_direct", 2), ("other_foreign_pro", 35),
    ],
}
FOREIGN_AGE_WEIGHTS = {
    "投手": [
        (19, 1), (20, 1), (21, 2), (22, 3), (23, 4), (24, 5),
        (25, 30), (26, 47), (27, 65), (28, 130), (29, 160), (30, 175),
        (31, 115), (32, 103), (33, 81), (34, 29), (35, 20), (36, 12),
        (37, 7), (38, 5), (39, 3), (40, 2), (41, 1),
    ],
    "野手": [
        (19, 2), (20, 3), (21, 5), (22, 8), (23, 12), (24, 17),
        (25, 30), (26, 44), (27, 55), (28, 90), (29, 105), (30, 123),
        (31, 110), (32, 110), (33, 98), (34, 58), (35, 43), (36, 31),
        (37, 22), (38, 15), (39, 9), (40, 5), (41, 3), (42, 2),
    ],
}
FOREIGN_NPB_TENURE_WEIGHTS = {
    "投手": [(1, 457), (2, 190), (3, 164), (4, 70), (5, 45), (6, 30), (7, 20), (8, 12), (9, 7), (10, 5)],
    "野手": [(1, 459), (2, 145), (3, 126), (4, 75), (5, 60), (6, 45), (7, 35), (8, 25), (9, 15), (10, 10), (11, 5)],
}
FOREIGN_ROUTE_NATIONALITY_WEIGHTS = {
    "north_america_pro": [("アメリカ", 38), ("ドミニカ共和国", 24), ("ベネズエラ", 15), ("キューバ", 8), ("メキシコ", 7), ("韓国", 4), ("台湾", 4)],
    "cuba_domestic": [("キューバ", 97), ("ドミニカ共和国", 2), ("ベネズエラ", 1)],
    "latin_development": [("ドミニカ共和国", 40), ("ベネズエラ", 30), ("メキシコ", 15), ("キューバ", 10), ("アメリカ", 5)],
    "korea_pro": [("韓国", 82), ("アメリカ", 10), ("ドミニカ共和国", 4), ("ベネズエラ", 4)],
    "taiwan_pro": [("台湾", 82), ("アメリカ", 8), ("ドミニカ共和国", 5), ("ベネズエラ", 5)],
    "taiwan_amateur_direct": [("台湾", 100)],
    "north_america_amateur_direct": [("アメリカ", 85), ("メキシコ", 8), ("ドミニカ共和国", 4), ("ベネズエラ", 3)],
    "other_foreign_pro": [("メキシコ", 35), ("韓国", 20), ("台湾", 15), ("アメリカ", 12), ("ドミニカ共和国", 8), ("ベネズエラ", 6), ("キューバ", 4)],
}
PITCHING_FORM_RANGES = {"オーバースロー": (195, 34), "スリークォーター": (180, 39), "サイドスロー": (106, 66), "アンダースロー": (40, 33)}
BATTING_FORM_RANGES = {"スタンダード": (210, 25), "オープン": (141, 24), "クラウチング": (12, 8)}
PITCHING_FORM_TYPE_WEIGHTS = [("オーバースロー", 55), ("スリークォーター", 34), ("サイドスロー", 9), ("アンダースロー", 2)]
# 架空球団（日本人）は実在（2022〜2025）に合わせてスリークォーターを最多にする。
FICTIONAL_PITCHING_FORM_TYPE_WEIGHTS = [("オーバースロー", 87), ("スリークォーター", 97), ("サイドスロー", 11), ("アンダースロー", 2)]
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
    if category == "架空球団用" and age >= 35:
        apply("active_veteran")
        if player_class == "ベテラン型":
            apply("veteran_survivor")
    return {key: max(1, round(weights[key] * max(0.25, min(multipliers[key], 3.0)))) for key in GROWTH_TYPE_LABELS}


def choose_growth_type(*, category: str, age: int, player_class: str | None, development_stage: str | None, acquisition_role: str | None, rng: random.Random) -> str:
    weights = growth_type_weight_map(category, age, player_class, development_stage, acquisition_role)
    return weighted_choice(rng, list(weights.items()))


def foreign_tenure_band(npb_years: int) -> str:
    return "1" if npb_years <= 1 else "2-3" if npb_years <= 3 else "4+"


def foreign_route_group(route: str) -> str:
    if route in {"latin_development", "north_america_amateur_direct", "taiwan_amateur_direct"}:
        return "development_direct"
    if route in {"korea_pro", "taiwan_pro"}:
        return "asian_pro"
    return route if route in {"north_america_pro", "cuba_domestic"} else "other"


def multiply_weight_items(items: list[tuple[str, int | float]], multipliers: dict[str, float]) -> list[tuple[str, int]]:
    return [(label, max(1, round(weight * multipliers.get(label, 1.0)))) for label, weight in items]


def choose_player_class(rng: random.Random, category: str, age: int, npb_years: int = 0, foreign_route: str = "") -> str:
    items = list(PLAYER_CLASS_WEIGHTS.get(category, []))
    adjusted: list[tuple[str, int]] = []
    for label, weight in items:
        if category == "架空球団用":
            if 18 <= age <= 24 and label == "ベテラン型":
                continue
            if age > FICTIONAL_YOUNG_MATERIAL_MAX_AGE and label == "若手素材型":
                continue
            if 18 <= age <= 19 and label == "スター級":
                weight = max(1, round(weight * 0.25))
            if age >= 35:
                if label == "一軍主力級":
                    weight *= 2
                elif label == "一軍控え級":
                    weight = max(1, round(weight * 0.45))
                elif label == "二軍級":
                    weight = max(1, round(weight * 0.15))
                elif label == "ベテラン型":
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
    if category == "助っ人外国人用" and npb_years:
        adjusted = multiply_weight_items(adjusted, FOREIGN_PLAYER_CLASS_TENURE_MULTIPLIERS[foreign_tenure_band(npb_years)])
        adjusted = multiply_weight_items(adjusted, FOREIGN_PLAYER_CLASS_ROUTE_MULTIPLIERS.get(foreign_route_group(foreign_route), {}))
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


def choose_archetype(rng: random.Random, role: str, category: str, age: int | None = None, player_class: str = "", npb_years: int = 0, foreign_route: str = "") -> str:
    weights = list(FOREIGN_ARCHETYPE_WEIGHTS[role] if category == "助っ人外国人用" else ARCHETYPE_WEIGHTS[role])
    if category == "助っ人外国人用" and npb_years:
        weights = multiply_weight_items(weights, FOREIGN_ARCHETYPE_TENURE_MULTIPLIERS[role][foreign_tenure_band(npb_years)])
        route_multipliers = FOREIGN_ARCHETYPE_ROUTE_MULTIPLIERS.get(foreign_route_group(foreign_route), {}).get(role, {})
        weights = multiply_weight_items(weights, route_multipliers)
    if category == "架空球団用" and role == "投手" and age is not None and age >= 35:
        veteran_multipliers = {"総合": 1.0, "制球": 1.50, "速球": 0.45, "変化球": 1.50, "スタミナ": 1.10}
        weights = [(label, max(1, round(weight * veteran_multipliers[label]))) for label, weight in weights]
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


def choose_acquisition_role(rng: random.Random, category: str, role: str, player_class: str, position: str, aptitudes: dict[str, str] | None = None, batting_throwing: str = "", npb_years: int = 0, foreign_route: str = "") -> str:
    if category != "助っ人外国人用":
        return ""
    if role == "野手":
        candidates = list(FIELDER_ACQUISITION_ROLES_BY_POSITION.get(position, ["保険要員"]))
        if player_class == "育成素材型" and "若手育成" not in candidates:
            candidates.append("若手育成")
        items = [(label, 20) for label in candidates]
        if player_class == "保険・バックアップ級":
            items = [(label, weight * 2 if label == "保険要員" else weight) for label, weight in items]
        if npb_years:
            items = multiply_weight_items(items, FOREIGN_ACQUISITION_TENURE_MULTIPLIERS[foreign_tenure_band(npb_years)])
            items = multiply_weight_items(items, FOREIGN_ACQUISITION_ROUTE_MULTIPLIERS.get(foreign_route_group(foreign_route), {}))
        return weighted_choice(rng, positive_weight_items(items))
    candidates = pitcher_acquisition_candidates(aptitudes or {}, batting_throwing)
    if player_class == "育成素材型" and "若手育成" not in candidates:
        candidates.append("若手育成")
    items = [(label, PITCHER_ACQUISITION_ROLE_WEIGHTS.get(label, 10)) for label in candidates]
    if player_class == "再生候補":
        items = [(label, weight * 2 if label == "再生候補" else weight) for label, weight in items]
    if npb_years:
        items = multiply_weight_items(items, FOREIGN_ACQUISITION_TENURE_MULTIPLIERS[foreign_tenure_band(npb_years)])
        items = multiply_weight_items(items, FOREIGN_ACQUISITION_ROUTE_MULTIPLIERS.get(foreign_route_group(foreign_route), {}))
    return weighted_choice(rng, positive_weight_items(items))


def choose_position_style(rng: random.Random, role: str, position: str, archetype: str) -> str:
    if role == "投手":
        return PITCHER_POSITION_STYLE_BY_ROLE.get(position, {}).get(archetype, "")
    weights = FIELDER_POSITION_STYLE_WEIGHTS.get(position, {}).get(archetype)
    return weighted_choice(rng, weights) if weights else ""


def choose_weakness_profile(rng: random.Random, category: str, role: str, player_class: str, npb_years: int = 0) -> str:
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
    if npb_years:
        items = multiply_weight_items(items, FOREIGN_WEAKNESS_TENURE_MULTIPLIERS[role][foreign_tenure_band(npb_years)])
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


def generate_batting_throwing(rng: random.Random, role: str, position: str, category: str = "") -> str:
    if category == "架空球団用":
        return generate_fictional_batting_throwing(rng, role, position)
    if category == "ドラフト候補用":
        return generate_fictional_batting_throwing(rng, role, position, DRAFT_PITCHER_LEFT_THROW_RATE, DRAFT_FIELDER_LEFT_THROW_RATE)
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


# 架空球団（日本人）の投打。実在12球団（2022〜2026）では利き腕ごとに打席がほぼ決まっている。
# 左投げは一塁手・外野手だけ。右投げ野手の左打ちの割合はポジションで大きく違う。
FICTIONAL_PITCHER_LEFT_THROW_RATE = 0.31
FICTIONAL_FIELDER_LEFT_THROW_RATE = 0.145
FICTIONAL_BAT_SIDE_WEIGHTS = {
    "投手_右投": [("右打", 80), ("左打", 19), ("両打", 1)],
    "投手_左投": [("左打", 98), ("右打", 2)],
    "野手_左投": [("左打", 100)],
    "捕手": [("右打", 71), ("左打", 28), ("両打", 1)],
    "一塁手": [("右打", 82), ("左打", 17), ("両打", 1)],
    "二塁手": [("右打", 43), ("左打", 55), ("両打", 2)],
    "三塁手": [("右打", 59), ("左打", 40), ("両打", 1)],
    "遊撃手": [("右打", 44), ("左打", 54), ("両打", 2)],
    "外野手": [("右打", 48), ("左打", 50), ("両打", 2)],
}
# ドラフト候補（実在のプロ1年目 2022〜2026）も同じ打席の決め方にする。
# 左投げは投手29%、野手7%（一塁手・外野手のうち約19%）。
DRAFT_PITCHER_LEFT_THROW_RATE = 0.295
DRAFT_FIELDER_LEFT_THROW_RATE = 0.185


def generate_fictional_batting_throwing(
    rng: random.Random,
    role: str,
    position: str,
    pitcher_left_rate: float = FICTIONAL_PITCHER_LEFT_THROW_RATE,
    fielder_left_rate: float = FICTIONAL_FIELDER_LEFT_THROW_RATE,
) -> str:
    # 既存seedの後続系列を保つため、従来どおり乱数を2回だけ使う。
    if role == "投手":
        throwing = weighted_choice(rng, [("右投", 1 - pitcher_left_rate), ("左投", pitcher_left_rate)])
        key = f"投手_{throwing}"
    else:
        left_rate = fielder_left_rate if position in ("一塁手", "外野手") else 0.0
        throwing = weighted_choice(rng, [("右投", 1 - left_rate), ("左投", left_rate)])
        key = "野手_左投" if throwing == "左投" else position
    bat_side = weighted_choice(rng, FICTIONAL_BAT_SIDE_WEIGHTS.get(key, FICTIONAL_BAT_SIDE_WEIGHTS["三塁手"]))
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
    return weighted_choice(rng, FICTIONAL_ROSTER_AGE_WEIGHTS)


def create_career_rng(seed: int, role: str, category: str) -> random.Random:
    """Keep career generation from consuming the established ability RNG stream."""
    digest = hashlib.sha256(f"{int(seed)}:career:{role}:{category}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def fictional_entry_route_weights_for_age(age: int) -> list[tuple[str, int]]:
    if 20 <= age <= 21:
        return FICTIONAL_ENTRY_ROUTE_AGE_WEIGHTS["20-21"]
    if age in {22, 23}:
        return FICTIONAL_ENTRY_ROUTE_AGE_WEIGHTS[age]
    if 24 <= age <= 25:
        return FICTIONAL_ENTRY_ROUTE_AGE_WEIGHTS["24-25"]
    if 27 <= age <= 30:
        return FICTIONAL_ENTRY_ROUTE_AGE_WEIGHTS["27-30"]
    if 31 <= age <= 34:
        return FICTIONAL_ENTRY_ROUTE_AGE_WEIGHTS["31-34"]
    return FICTIONAL_ENTRY_ROUTE_WEIGHTS


def determine_roster_origin(category: str, nationality: str, seed: int) -> str:
    """Classify roster origin independently from nationality."""
    if category == "助っ人外国人用":
        return "foreign_import"
    if category != "架空球団用" or nationality == "日本":
        return "domestic"
    rng = make_sub_rng(seed, "roster_origin_v1")
    return "domestic" if rng.random() < FICTIONAL_FOREIGN_DOMESTIC_ROUTE_RATE else "foreign_import"


def foreign_route_age_multiplier(route: str, age: int) -> float:
    if route in {"taiwan_amateur_direct", "north_america_amateur_direct"}:
        return 1.8 if age <= 24 else 1.25 if age <= 27 else 0.7 if age <= 30 else 0.35
    if route == "latin_development":
        return 1.45 if age <= 24 else 1.15 if age <= 27 else 1.0 if age <= 30 else 0.75
    if route in {"korea_pro", "taiwan_pro"}:
        return 0.65 if age <= 27 else 1.0 if age <= 30 else 1.15
    if route == "other_foreign_pro":
        return 0.8 if age <= 27 else 1.0 if age <= 30 else 1.2
    return 1.0


def foreign_tenure_age_multiplier(role: str, age: int, years: int) -> float:
    if role != "野手":
        return 1.0
    band = "first" if years == 1 else "middle" if years <= 3 else "long"
    if age <= 24:
        multiplier = {"first": 3.70, "middle": 0.96, "long": 0.15}[band]
    elif age <= 27:
        multiplier = {"first": 2.00, "middle": 1.00, "long": 0.27}[band]
    elif age <= 30:
        multiplier = {"first": 1.34, "middle": 1.00, "long": 0.07}[band]
    elif age <= 33:
        multiplier = {"first": 0.43, "middle": 1.00, "long": 1.31}[band]
    else:
        multiplier = {"first": 0.48, "middle": 1.00, "long": 2.74}[band]
    # 帯の中でも、高齢の長期在籍者ほど年数が伸びるように緩やかに連続化する。
    band_balance = {"first": 1.00, "middle": 1.17, "long": 0.94}[band]
    return multiplier * band_balance * math.exp(0.023 * (age - 30) * (years - 3))


def foreign_route_tenure_multiplier(route: str, years: int) -> float:
    if route in {"taiwan_amateur_direct", "north_america_amateur_direct"}:
        return 1.25 if years == 1 else 0.70 if years >= 4 else 1.0
    if route == "latin_development":
        return 1.10 if years == 1 else 0.85 if years >= 4 else 1.0
    if route in {"korea_pro", "taiwan_pro"}:
        return 0.90 if years == 1 else 1.15 if years >= 4 else 1.0
    return 1.0


def choose_foreign_tenure(rng: random.Random, role: str, age: int, route: str) -> int:
    max_years = max(1, age - 17)
    eligible = []
    for years, weight in FOREIGN_NPB_TENURE_WEIGHTS[role]:
        if years <= max_years:
            multiplier = foreign_tenure_age_multiplier(role, age, years)
            multiplier *= foreign_route_tenure_multiplier(route, years)
            eligible.append((years, weight * multiplier))
    return int(weighted_choice(rng, eligible))


def generate_foreign_context(seed: int, role: str, current_year: int = NPB_CURRENT_YEAR) -> dict[str, Any]:
    """Generate the shared route, age, nationality, and NPB-stint context."""
    rng = make_sub_rng(seed, "foreign_context_v1")
    route = str(weighted_choice(rng, FOREIGN_ROUTE_WEIGHTS[role]))
    age_weights = [
        (age, weight * foreign_route_age_multiplier(route, age))
        for age, weight in FOREIGN_AGE_WEIGHTS[role]
    ]
    age = int(weighted_choice(rng, age_weights))
    nationality = str(weighted_choice(rng, FOREIGN_ROUTE_NATIONALITY_WEIGHTS[route]))
    npb_years = choose_foreign_tenure(rng, role, age, route)
    stint_start = current_year - npb_years + 1
    returnee_eligible = age >= 28 and route not in {"taiwan_amateur_direct", "north_america_amateur_direct"}
    is_returnee = bool(returnee_eligible and rng.random() < FOREIGN_RETURNEE_RATE)
    first_entry = stint_start
    if is_returnee:
        first_entry = max(current_year - age + 18, stint_start - rng.randint(2, 6))
        if first_entry >= stint_start:
            is_returnee = False
            first_entry = stint_start
    return {
        "roster_origin": "foreign_import",
        "foreign_route": route,
        "age": age,
        "nationality": nationality,
        "npb_years": npb_years,
        "npb_first_entry_year": first_entry,
        "npb_stint_start_year": stint_start,
        "is_returnee": is_returnee,
    }


def foreign_career_history(context: dict[str, Any]) -> dict[str, Any]:
    first_entry_year = int(context["npb_first_entry_year"])
    age = int(context["age"])
    return {
        "entry_route": "海外プロ経由",
        "pro_entry_age": max(18, age - (NPB_CURRENT_YEAR - first_entry_year)),
        "pro_years": int(context["npb_years"]),
        "npb_years": int(context["npb_years"]),
        "npb_first_entry_year": first_entry_year,
        "npb_stint_start_year": int(context["npb_stint_start_year"]),
        "is_returnee": bool(context["is_returnee"]),
    }


def domestic_roster_context(career_history: dict[str, Any]) -> dict[str, Any]:
    npb_years = int(career_history.get("pro_years") or 0)
    entry_year = NPB_CURRENT_YEAR - npb_years + 1 if npb_years else 0
    return {
        "roster_origin": "domestic",
        "foreign_route": "",
        "npb_years": npb_years,
        "npb_first_entry_year": entry_year,
        "npb_stint_start_year": entry_year,
        "is_returnee": False,
    }


def generate_career_history(
    *,
    category: str,
    age: int,
    seed: int,
    role: str,
    draft_source_type: str = "",
    player_class: str = "",
) -> dict[str, Any]:
    """Generate profile-only career history without changing player abilities."""
    rng = create_career_rng(seed, role, category)
    if category == "ドラフト候補用":
        route_map = {"高校生": "高卒", "大学生": "大卒", "社会人": "社会人", "独立・クラブ": "独立・クラブ", "その他": "その他"}
        return {"entry_route": route_map.get(draft_source_type, ""), "pro_entry_age": 0, "pro_years": 0}
    if category == "助っ人外国人用":
        eligible = [(years, weight) for years, weight in FOREIGN_NPB_TENURE_WEIGHTS[role] if years <= max(1, age - 17)]
        pro_years = int(weighted_choice(rng, eligible))
        return {"entry_route": "海外プロ経由", "pro_entry_age": age - pro_years + 1, "pro_years": pro_years}

    # 若手素材型はプロ6年目以内（プロ入り年齢が age − 5 以上）にする。
    min_entry_age = age - FICTIONAL_YOUNG_MATERIAL_MAX_PRO_YEARS + 1 if player_class == "若手素材型" else 0

    def entry_ages(route: str) -> list[tuple[int, float]]:
        return [(entry_age, weight) for entry_age, weight in FICTIONAL_ENTRY_AGE_WEIGHTS[route] if min_entry_age <= entry_age <= age]

    route_candidates = [(route, weight) for route, weight in fictional_entry_route_weights_for_age(age) if entry_ages(route)]
    if not route_candidates:
        min_entry_age = 0
        route_candidates = [(route, weight) for route, weight in fictional_entry_route_weights_for_age(age) if entry_ages(route)]
    entry_route = weighted_choice(rng, route_candidates)
    entry_age_candidates = entry_ages(entry_route)
    pro_entry_age = int(weighted_choice(rng, entry_age_candidates))
    return {"entry_route": entry_route, "pro_entry_age": pro_entry_age, "pro_years": age - pro_entry_age + 1}


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
    "球持ち○": 2.80, "逃げ球": 1.55, "内角攻め": 2.55, "キレ○": 2.65, "荒れ球": 1.90,
    "スロースターター": 1.55, "緩急○": 2.45, "低め○": 1.75, "クロスファイヤー": 1.55, "対強打者○": 1.55,
    "一発": 1.25, "ゴロピッチャー": 1.65, "フライボールピッチャー": 1.70,
}
PITCHER_REALISTIC_SPECIAL_SUPPRESSIONS = {
    "勝ち運": 0.45, "ストライク先行": 0.70, "乱調": 0.75, "尻上がり": 0.75, "寸前": 0.80, "要所○": 0.70,
}
FIELDER_REALISTIC_SPECIAL_BOOSTS = {
    "三振": 3.25, "サヨナラ男": 1.85, "内野安打○": 1.45, "固め打ち": 1.85,
    "満塁男": 1.85, "流し打ち": 1.95, "決勝打": 2.05, "バント○": 1.20,
    "死球集中": 1.05, "併殺": 3.00, "広角打法": 1.80, "ヘッドスライディング": 1.85,
    "カット打ち": 1.85, "レーザービーム": 1.70, "アベレージヒッター": 1.55, "パワーヒッター": 1.50, "守備職人": 1.40,
}
FIELDER_REALISTIC_SPECIAL_SUPPRESSIONS = {
    "代打○": 0.50, "プレッシャーラン": 0.65, "高速チャージ": 0.70, "ダメ押し": 0.70,
    "チャンスメーカー": 0.70, "対変化球○": 0.70, "いぶし銀": 0.70, "ローボールヒッター": 0.65,
    "かく乱": 0.70, "国際大会×": 0.18, "窮地○": 0.70, "ささやき破り": 0.65,
    "リベンジ": 0.70, "帳尻合わせ": 0.70,
}

INDIVIDUAL_SPECIAL_AGE_PROFILES = {
    ("投手", "変化球中心"): "experience_up",
    ("投手", "逃げ球"): "mild_experience_up",
    ("投手", "キレ○"): "mild_experience_up",
    ("野手", "選球眼"): "experience_up",
    ("野手", "積極守備"): "experience_up",
    ("野手", "バント○"): "experience_up",
    ("野手", "満塁男"): "flatten_age_bias",
    ("野手", "三振"): "flatten_age_bias",
}

INDIVIDUAL_SPECIAL_AGE_CURVES = {
    "experience_up": [(18, 0.85), (22, 0.90), (26, 0.97), (30, 1.08), (34, 1.18), (38, 1.15), (42, 1.07)],
    "mild_experience_up": [(18, 0.70), (22, 0.88), (26, 0.98), (30, 1.04), (34, 1.08), (38, 1.08), (42, 1.04)],
    "flatten_age_bias": [(18, 1.025), (22, 1.015), (26, 1.00), (30, 0.98), (34, 0.94), (38, 0.95), (42, 0.98)],
}


def special_age_multiplier(name: str, role: str, age: int | None) -> float:
    """Phase 2: 対象特能だけを滑らかに年齢再配分する決定論的倍率。"""
    if not isinstance(age, int):
        return 1.0
    profile = INDIVIDUAL_SPECIAL_AGE_PROFILES.get((role, name))
    points = INDIVIDUAL_SPECIAL_AGE_CURVES.get(profile or "")
    if not points:
        return 1.0
    if age <= points[0][0]:
        return float(points[0][1])
    for (left_age, left_value), (right_age, right_value) in zip(points, points[1:]):
        if age <= right_age:
            ratio = (age - left_age) / (right_age - left_age)
            return float(left_value + (right_value - left_value) * ratio)
    return float(points[-1][1])


PICKOFF_PRO_YEAR_CURVE = [
    (1, 1.00),
    (2, 1.00),
    (4, 1.08),
    (6, 1.16),
    (8, 1.22),
    (10, 1.26),
    (12, 1.28),
    (15, 1.30),
    (20, 1.30),
]


def pro_year_special_multiplier(name: str, role: str, pro_years: int | None) -> float:
    """Phase 4b: 投手「牽制○」だけをプロ年数でごく弱く再配分する決定論的倍率。"""
    if name != "牽制○" or role != "投手" or not isinstance(pro_years, int):
        return 1.0
    if pro_years <= PICKOFF_PRO_YEAR_CURVE[0][0]:
        return float(PICKOFF_PRO_YEAR_CURVE[0][1])
    for (left_year, left_value), (right_year, right_value) in zip(PICKOFF_PRO_YEAR_CURVE, PICKOFF_PRO_YEAR_CURVE[1:]):
        if pro_years <= right_year:
            ratio = (pro_years - left_year) / (right_year - left_year)
            return float(left_value + (right_value - left_value) * ratio)
    return float(PICKOFF_PRO_YEAR_CURVE[-1][1])


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

def adjust_special_chance(row: dict[str, Any], base_chance: int, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, development_stage: str | None = None, acquisition_role: str | None = None, weakness_profile: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None, apply_age_profile: bool = True, pro_years: int | None = None, apply_pro_year_profile: bool = True) -> float:
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
                    chance += 4.0
                elif speed >= 70:
                    chance += 2.8
                elif speed >= 60:
                    chance += 1.0
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
                    chance += 6
                elif isinstance(speed, int | float) and speed < 60:
                    chance += 3.5
                elif isinstance(speed, int | float) and speed < 70:
                    chance += 0.0
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
        if name == "球持ち○":
            if archetype in {"制球", "変化球"}:
                chance += 2.4
            if isinstance(control, int | float) and control >= 60:
                chance += 1.5
            if player_class in {"スター級", "一軍主力級", "ベテラン型"}:
                chance += 1.0
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
    if category == "架空球団用" and apply_age_profile:
        chance *= special_age_multiplier(name, role, age)
    if category == "架空球団用" and apply_pro_year_profile:
        chance *= pro_year_special_multiplier(name, role, pro_years)
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


def special_age_tail_adjustment(
    role: str | None,
    age: int | None,
    player_class: str | None,
    player_score: float,
) -> tuple[int, int]:
    """Phase 1: 個別chanceを変えず、非ランク個数のsoft tailだけを年齢で調整します。"""
    if role not in {"投手", "野手"} or not isinstance(age, int):
        return 0, 0
    cls = player_class or ""
    cap_delta = 0
    draw_delta = 0
    if role == "投手":
        young_main_exception_score = 95
        young_control_exception_score = 90
        young_material_exception_score = 84
        prime_score = 82
        control_prime_score = 85
    else:
        young_main_exception_score = 66
        young_control_exception_score = 60
        young_material_exception_score = 55
        prime_score = 52
        control_prime_score = 52
    if age <= 22:
        if cls == "一軍主力級" and player_score < young_main_exception_score:
            cap_delta = -2 if role == "野手" else -1
            draw_delta = -2 if role == "野手" else -1
        elif cls == "一軍控え級" and player_score < young_control_exception_score:
            cap_delta = -2 if role == "野手" else -1
            draw_delta = -2 if role == "野手" else -1
        elif cls == "若手素材型" and player_score < young_material_exception_score:
            cap_delta = -1
            draw_delta = -1
        elif cls == "ベテラン型" and player_score < young_main_exception_score:
            cap_delta = -1
            draw_delta = -1
    elif 27 <= age <= 30:
        if cls in {"スター級", "一軍主力級", "ベテラン型"} and player_score >= prime_score:
            cap_delta = 2 if role == "野手" else 1
            draw_delta = 1
        elif cls == "一軍控え級" and player_score >= control_prime_score:
            cap_delta = 1
            draw_delta = 1
    elif 31 <= age <= 34:
        if cls in {"スター級", "一軍主力級", "ベテラン型"} and player_score >= prime_score:
            cap_delta = 3 if role == "野手" else 1
            draw_delta = 2 if role == "野手" else 1
        elif cls == "一軍控え級" and player_score >= control_prime_score:
            cap_delta = 2 if role == "野手" else 1
            draw_delta = 2 if role == "野手" else 1
    elif age >= 35:
        if role == "野手" and cls in {"スター級", "一軍主力級", "ベテラン型"} and player_score >= prime_score:
            cap_delta = 1
        elif role == "野手" and cls == "一軍控え級" and player_score >= control_prime_score:
            cap_delta = 1
    return cap_delta, draw_delta


def weighted_special_cap(
    rng: random.Random,
    category: str | None,
    player_class: str | None,
    player_score: float,
    role: str | None = None,
    age: int | None = None,
) -> int:
    low, high = special_count_bounds(category, player_class)
    if high <= low:
        return high
    if player_class == "スター級":
        base = weighted_choice(rng, [(5, 14), (6, 20), (7, 23), (8, 18), (9, 11), (10, 7), (11, 4), (12, 3)])
    elif player_class in {"一軍主力級", "ベテラン型", "大物実績者", "主力期待級"}:
        base = weighted_choice(rng, [(3, 16), (4, 24), (5, 22), (6, 17), (7, 10), (8, 6), (9, 3), (10, 2)])
    elif category == "架空球団用" and player_class == "一軍控え級":
        base = weighted_choice(rng, [(1, 18), (2, 22), (3, 22), (4, 18), (5, 12), (6, 5), (7, 3)])
    elif player_class == "レギュラー競争級":
        base = weighted_choice(rng, [(1, 28), (2, 28), (3, 20), (4, 12), (5, 7), (6, 3), (7, 2)])
    elif player_class in {"二軍級", "若手素材型", "育成候補", "育成素材型", "保険・バックアップ級"}:
        base = weighted_choice(rng, [(0, 26), (1, 28), (2, 22), (3, 14), (4, 7), (5, 3)])
    else:
        base = weighted_choice(rng, [(1, 25), (2, 27), (3, 22), (4, 14), (5, 8), (6, 4)])
    if player_score >= 68 and rng.random() < 0.45:
        base += 1
    elif player_score < 45 and rng.random() < 0.35:
        base -= 1
    if category == "架空球団用":
        cap_delta, _draw_delta = special_age_tail_adjustment(role, age, player_class, player_score)
        base += cap_delta
    return max(low, min(high, base))


def extra_special_draws(
    rng: random.Random,
    category: str | None,
    player_class: str | None,
    player_score: float,
    role: str | None = None,
    age: int | None = None,
) -> int:
    if category != "架空球団用":
        return 0
    draws = 0
    if player_class == "スター級":
        draws = 2
        draws += int(rng.random() < 0.90)
        draws += int(rng.random() < 0.60)
    elif player_class in {"一軍主力級", "ベテラン型"}:
        draws = 3
        draws += int(rng.random() < 0.85)
        draws += int(rng.random() < 0.35)
    elif player_class == "一軍控え級":
        draws = 2
        draws += int(rng.random() < 0.75)
        draws += int(player_score >= 55 and rng.random() < 0.25)
    elif player_class == "若手素材型":
        draws = int(player_score >= 58 and rng.random() < 0.32)
    elif player_class == "二軍級":
        draws = int(player_score >= 60 and rng.random() < 0.18)
    _cap_delta, draw_delta = special_age_tail_adjustment(role, age, player_class, player_score)
    return max(0, draws + draw_delta)


SPECIAL_COUNT_BONUS_EXCLUSIONS = {"流し打ち"}


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


def special_player_score(role: str, abilities: dict[str, Any] | None) -> float:
    if role == "投手":
        values = [
            pitcher_speed_value(abilities or {}),
            ability_numeric_value(abilities or {}, "コントロール"),
            ability_numeric_value(abilities or {}, "スタミナ"),
        ]
    else:
        values = [ability_numeric_value(abilities or {}, key) for key in ("ミート", "パワー", "走力", "肩力", "守備力", "捕球")]
    numeric_values = [value for value in values if isinstance(value, int | float)]
    return sum(numeric_values) / max(1, len(numeric_values))


def generate_specials(rng: random.Random, master: MasterData, role: str, player_type: str, position: str | None = None, age: int | None = None, abilities: dict[str, Any] | None = None, breaking_balls: list[dict[str, Any]] | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, development_stage: str | None = None, acquisition_role: str | None = None, weakness_profile: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None, apply_age_tail: bool = True, apply_age_profile: bool = True, pro_years: int | None = None, apply_pro_year_profile: bool = True) -> list[str]:
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
    pickoff_draw: float | None = None
    pickoff_base_chance: float | None = None
    pickoff_adjusted_chance: float | None = None
    for row in candidates:
        group = str(row.get("group", "") or "").strip()
        if group and group in used_groups:
            continue
        name = row["name"]
        if not is_special_allowed_for_player(name, role, position, sub_positions, pitcher_aptitudes):
            continue
        chance = adjust_special_chance(row, int(row.get("weight", 0) or 0), role, player_type, position, age, abilities, breaking_balls, category, player_class, archetype, position_style, development_stage, acquisition_role, weakness_profile, sub_positions, pitcher_aptitudes, apply_age_profile, pro_years, False)
        if name == "牽制○" and role == "投手" and category == "架空球団用" and apply_pro_year_profile:
            pickoff_base_chance = chance
            pickoff_adjusted_chance = adjust_special_chance(row, int(row.get("weight", 0) or 0), role, player_type, position, age, abilities, breaking_balls, category, player_class, archetype, position_style, development_stage, acquisition_role, weakness_profile, sub_positions, pitcher_aptitudes, apply_age_profile, pro_years, True)
        chance_by_name[name] = chance
        row_by_name[name] = row
        if name in selected_names:
            continue
        draw = rng.random()
        if name == "牽制○" and role == "投手" and category == "架空球団用" and apply_pro_year_profile:
            pickoff_draw = draw
        if draw < chance / 100 and conflicts.get(name) not in selected_names:
            selected.append(name)
            selected_names.add(name)
            if group:
                used_groups.add(group)
    selected = audit_special_selection(rng, selected, role, position, abilities, sub_positions, pitcher_aptitudes)
    selected_names, used_groups = rebuild_special_generation_state(selected, row_by_name)
    player_score = special_player_score(role, abilities)
    if category == "架空球団用":
        min_count, max_count = special_count_bounds(category, player_class)
        cap = weighted_special_cap(
            rng,
            category,
            player_class,
            player_score,
            role=role if apply_age_tail else None,
            age=age if apply_age_tail else None,
        )
    else:
        min_count = 0
        cap = 6 if category == "助っ人外国人用" else 5
        if category == "助っ人外国人用" and player_score >= 68:
            cap += 1
        max_count = cap
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
    bonus_draws = extra_special_draws(
        rng,
        category,
        player_class,
        player_score,
        role=role if apply_age_tail else None,
        age=age if apply_age_tail else None,
    )
    if bonus_draws > 0 and len(countable) < cap:
        extra_candidates = sorted(
            [
                name
                for name, chance in chance_by_name.items()
                if is_countable_special(name)
                and name not in selected_names
                and name not in SPECIAL_COUNT_BONUS_EXCLUSIONS
                and chance > 0
            ],
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
    if apply_age_tail and category == "架空球団用":
        countable = [name for name in selected if is_countable_special(name)]
        if len(countable) < min_count:
            selected_names, used_groups = rebuild_special_generation_state(selected, row_by_name)
            refill_candidates = sorted(
                [
                    name
                    for name, chance in chance_by_name.items()
                    if is_countable_special(name) and name not in selected_names and chance > 0
                ],
                key=lambda item: chance_by_name[item],
                reverse=True,
            )
            for name in refill_candidates:
                row = row_by_name[name]
                group = str(row.get("group", "") or "").strip()
                if group and group in used_groups:
                    continue
                if conflicts.get(name) in selected_names:
                    continue
                trial = audit_special_selection(rng, selected + [name], role, position, abilities, sub_positions, pitcher_aptitudes)
                if len(trial) == len(selected):
                    continue
                selected = trial
                selected_names, used_groups = rebuild_special_generation_state(selected, row_by_name)
                countable = [item for item in selected if is_countable_special(item)]
                if len(countable) >= min_count:
                    break
    if pickoff_draw is not None and pickoff_base_chance is not None and pickoff_adjusted_chance is not None:
        countable = [name for name in selected if is_countable_special(name)]
        has_pickoff = "牽制○" in selected
        crossed_by_profile = pickoff_base_chance / 100 <= pickoff_draw < pickoff_adjusted_chance / 100
        if not has_pickoff and crossed_by_profile and len(countable) < max_count:
            selected.append("牽制○")
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
        if (
            (player_type == "技巧派" or archetype in {"制球", "総合"})
            and group_name in ("対ピンチ", "対左打者")
            and rng.random() < 0.20
        ):
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


RANKED_SPECIAL_AGE_CURVE = [
    (18, -1.00), (22, -0.90), (26, -0.18), (30, 0.55), (34, 1.15), (38, 1.00), (42, 0.70),
]


def ranked_related_ability_score(group_name: str, role: str, abilities: dict[str, Any]) -> float:
    """Rank groupに関連する既存能力だけを0～100へ正規化する。"""
    def value(key: str) -> float | None:
        item = abilities.get(key)
        if isinstance(item, dict):
            item = item.get("value")
        return float(item) if isinstance(item, int | float) else None

    def average(keys: list[str]) -> float:
        values = [value(key) for key in keys]
        present = [item for item in values if item is not None]
        return sum(present) / len(present) if present else 50.0

    if role == "投手":
        speed = pitcher_speed_value(abilities)
        speed_score = max(0.0, min(100.0, ((float(speed) - 125.0) / 35.0) * 100.0)) if isinstance(speed, int | float) else 50.0
        control = value("コントロール")
        stamina = value("スタミナ")
        if group_name == "ノビ":
            score = speed_score
        elif group_name == "クイック":
            score = control if control is not None else 50.0
        else:
            candidates = [control, stamina, speed_score]
            score = sum(item for item in candidates if item is not None) / max(1, sum(item is not None for item in candidates))
    elif group_name in {"盗塁", "走塁"}:
        score = average(["走力"])
    elif group_name == "送球":
        score = average(["肩力", "守備力"])
    elif group_name == "キャッチャー":
        score = average(["肩力", "守備力", "捕球"])
    elif group_name in {"チャンス", "対左投手"}:
        score = average(["ミート", "パワー"])
    else:
        score = average(["ミート", "パワー", "走力", "肩力", "守備力", "捕球"])
    return max(0.0, min(100.0, float(score)))


def ranked_age_weight_adjustment(group_name: str, role: str, age: int | None, player_class: str | None, abilities: dict[str, Any]) -> dict[str, float]:
    """Phase 3: class・関連能力を守りながらgood rankを年齢間で再配分する決定論的倍率。"""
    neutral = {rank: 1.0 for rank in RANKED_SPECIAL_RANKS}
    if not isinstance(age, int):
        return neutral
    if age <= RANKED_SPECIAL_AGE_CURVE[0][0]:
        age_signal = RANKED_SPECIAL_AGE_CURVE[0][1]
    else:
        age_signal = RANKED_SPECIAL_AGE_CURVE[-1][1]
        for (left_age, left_value), (right_age, right_value) in zip(RANKED_SPECIAL_AGE_CURVE, RANKED_SPECIAL_AGE_CURVE[1:]):
            if age <= right_age:
                ratio = (age - left_age) / (right_age - left_age)
                age_signal = left_value + (right_value - left_value) * ratio
                break

    related = ranked_related_ability_score(group_name, role, abilities)
    ability_gate = max(0.0, min(1.0, (related - 48.0) / 27.0))
    if age_signal < 0:
        class_factor = {
            "スター級": 0.22, "一軍主力級": 0.55, "ベテラン型": 0.40,
            "一軍控え級": 0.78, "二軍級": 1.00, "若手素材型": 1.08,
        }.get(player_class or "", 0.75)
        role_factor = 0.78 if role == "投手" else 1.15
        strength = min(1.0, -age_signal) * class_factor * role_factor * (1.0 - 0.55 * ability_gate)
        neutral.update({
            "A": max(0.18, 1.0 - 0.90 * strength),
            "B": max(0.35, 1.0 - 0.75 * strength),
            "C": max(0.55, 1.0 - 0.50 * strength),
        })
        return neutral

    class_factor = {
        "スター級": 1.00, "一軍主力級": 1.00, "ベテラン型": 0.92,
        "一軍控え級": 0.28, "二軍級": 0.0, "若手素材型": 0.0,
    }.get(player_class or "", 0.20)
    role_factor = 1.05 if role == "投手" else 1.30
    strength = age_signal * class_factor * ability_gate * role_factor
    neutral.update({
        "A": 1.0,
        "B": 1.0 + 0.48 * strength,
        "C": 1.0 + 1.25 * strength,
    })
    return neutral


def ranked_weight_items_for_group(group_name: str, role: str, position: str, player_type: str, abilities: dict[str, Any], age: int | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, sub_positions: Any = None, apply_age_profile: bool = True) -> list[tuple[str, float]]:
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
            if isinstance(age, int) and age >= 30 and not apply_age_profile:
                # Phase 2 baselineの捕手年齢補正。Phase 3有効時は共通profileへ統合する。
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
    if category == "架空球団用" and group_name == "回復":
        transfer = min(24, max(0, weights["D"] - 1))
        weights.update({"D": weights["D"] - transfer, "E": weights["E"] + transfer})
    if category == "架空球団用" and apply_age_profile:
        multipliers = ranked_age_weight_adjustment(group_name, role, age, player_class, abilities)
        prior_good = sum(float(weights[rank]) for rank in ("A", "B", "C"))
        for rank in ("A", "B", "C"):
            weights[rank] = max(0.1, float(weights[rank]) * multipliers[rank])
        good_delta = sum(float(weights[rank]) for rank in ("A", "B", "C")) - prior_good
        weights["D"] = max(0.25, float(weights["D"]) - good_delta)
    return [(rank_name, max(0.1, float(weight))) for rank_name, weight in weights.items()]


def generate_ranked_specials(rng: random.Random, master: MasterData, role: str, position: str, player_type: str, abilities: dict[str, Any], age: int | None = None, category: str | None = None, player_class: str | None = None, archetype: str | None = None, position_style: str | None = None, weakness_profile: str | None = None, sub_positions: Any = None, pitcher_aptitudes: dict[str, Any] | None = None, apply_age_profile: bool = True) -> dict[str, str]:
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
        rank_value = weighted_choice(rng, ranked_weight_items_for_group(group_name, role, position, player_type, abilities, age, category, player_class, archetype, position_style, sub_positions, apply_age_profile))
        if category == "架空球団用" and player_class in {"二軍級", "若手素材型"} and rank_value in {"A", "B", "G"} and rng.random() < 0.78:
            rank_value = weighted_choice(rng, [("C", 8), ("D", 58), ("E", 28), ("F", 6)])
        if group_name == "チャンス" and player_type == "長距離砲" and rng.random() < 0.35:
            rank_value = weighted_choice(rng, [("A", 4), ("B", 12), ("C", 20), ("D", 28), ("E", 20), ("F", 12), ("G", 4)])
        rank_value = shifted_rank(rank_value, ranked_shift_for_group(rng, group_name, role, position, player_type, abilities, archetype, position_style, weakness_profile))
        selected[group_name] = names_by_rank[rank_value]
    return selected

def fielder_age_mods(age: int, archetype: str, player_class: str) -> dict[str, int]:
    mods = {
        "ミート": curve_delta(age, [(18, -9), (24, 0), (25, 3), (30, 5), (34, 3), (36, -2), (39, -4), (42, -6), (46, -9)]),
        "パワー": curve_delta(age, [(18, -8), (21, -3), (25, 3), (31, 9), (34, 7), (36, 4), (39, 1), (42, -1), (46, -4)]),
        "走力": curve_delta(age, [(18, 4), (23, 8), (27, 6), (31, 2), (34, 2), (36, 1), (39, -2), (42, -5), (46, -9)]),
        "肩力": curve_delta(age, [(18, 1), (22, 4), (28, 5), (33, 2), (34, 1), (36, -1), (39, -4), (42, -7), (46, -11)]),
        "守備力": curve_delta(age, [(18, -8), (22, -4), (28, 4), (31, 9), (34, 7), (36, 0), (39, -3), (42, -5), (46, -8)]),
        "捕球": curve_delta(age, [(18, -8), (22, -4), (28, 4), (31, 9), (34, 8), (36, 1), (39, -2), (42, -4), (46, -7)]),
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
        "very_early": [(18, 4), (22, 4), (27, 1), (30, -2), (35, -4), (38, -6), (42, -8)],
        "early": [(18, 2), (22, 3), (28, 2), (31, -1), (35, -3), (38, -4), (42, -6)],
        "normal": [(18, 0), (24, 0), (29, 1), (33, 0), (35, 0), (42, 0)],
        "late": [(18, -2), (24, -2), (29, -1), (33, 2), (35, 1), (38, 0), (42, -2)],
        "very_late": [(18, -3), (24, -3), (29, -2), (34, 3), (35, 3), (38, 2), (42, 0)],
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
    elif category == "ドラフト候補用":
        class_mods = {
            "超上位候補": 7, "上位候補": 3, "中位候補": -2, "下位候補": -7, "育成候補": -11,
        }
        mod = class_mods.get(player_class, 0)
        for key in values:
            values[key] += mod
    elif category == "助っ人外国人用":
        # 外国人野手は打力中心の評価であり、選手格を守備・捕球へ同量加算しない。
        # 低い格ほど走力を残しやすくし、長期在籍で強い格が増えても既存の
        # survivor selectionを壊さず能力配分だけが変わるようにする。
        class_mods = {
            "大物実績者": {"ミート": 7, "パワー": 15, "走力": 7, "肩力": 19, "守備力": 0, "捕球": -1},
            "主力期待級": {"ミート": -1, "パワー": 10, "走力": 5, "肩力": 13, "守備力": -5, "捕球": -6},
            "レギュラー競争級": {"ミート": -8, "パワー": 5, "走力": 5, "肩力": 7, "守備力": -10, "捕球": -11},
            "保険・バックアップ級": {"ミート": -16, "パワー": -3, "走力": -2, "肩力": 0, "守備力": -16, "捕球": -17},
            "育成素材型": {"ミート": -15, "パワー": -2, "走力": 0, "肩力": 2, "守備力": -16, "捕球": -17},
            "再生候補": {"ミート": -12, "パワー": 1, "走力": -1, "肩力": 3, "守備力": -13, "捕球": -14},
        }
        add_mod(values, class_mods.get(player_class, {}))
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
        "俊足外野手": ["走力", "守備力", "捕球"],
        "守備外野手": ["走力", "肩力", "守備力", "捕球"],
        "走攻守外野手": ["走力", "肩力", "守備力", "捕球"],
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
    weakness_profile: str = "",
    apply_second_adjustment: bool = True,
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

    apply_fictional_position_profile_guards(values, position, player_class, archetype, position_style)

    cap = fictional_fielder_total_cap(rng, player_class)
    if position == "外野手" and position_style in {"俊足外野手", "守備外野手", "走攻守外野手"}:
        # 複合守備プロファイルの底上げ分を、既存打力の削減だけで相殺しない。
        cap += 10
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

    if apply_second_adjustment:
        apply_second_adjustment_fielder_distribution_guards(
            rng, values, position, player_class, position_style, weakness_profile
        )
    # 総合値capの縮小後も、ポジション別の最低ラインを最終値で保証する。
    enforce_fielder_position_constraints(rng, values, position, position_style)


def apply_fictional_position_profile_guards(
    values: dict[str, int],
    position: str,
    player_class: str,
    archetype: str,
    position_style: str,
) -> None:
    """独立分散後に、守備型の能力セットだけを再形成する。"""
    established = player_class in {"スター級", "一軍主力級", "ベテラン型"}
    low_tier = player_class in {"二軍級", "若手素材型"}
    if position == "二塁手":
        if position_style == "守備走塁二塁手":
            if established:
                minimums = {"走力": 72, "守備力": 62, "捕球": 53}
            elif player_class == "一軍控え級":
                minimums = {"走力": 70, "守備力": 60, "捕球": 50}
            else:
                minimums = {"走力": 67, "守備力": 55, "捕球": 47}
        elif position_style == "平均型二塁手":
            if established:
                minimums = {"走力": 68, "守備力": 56, "捕球": 49}
            elif player_class == "一軍控え級":
                minimums = {"走力": 64, "守備力": 53, "捕球": 46}
            else:
                minimums = {"走力": 61, "守備力": 50, "捕球": 44}
        elif position_style == "打撃型二塁手":
            minimums = {"走力": 58, "守備力": 50 if established else 46, "捕球": 44 if established else 41}
        else:
            minimums = {}
        for key, minimum in minimums.items():
            values[key] = max(values[key], minimum)
        return

    if position != "外野手":
        return
    if position_style == "走攻守外野手":
        minimums = {"走力": 69 if established else 64, "肩力": 65 if established else 60, "守備力": 54 if established else 50, "捕球": 48 if established else 44}
    elif position_style == "俊足外野手":
        minimums = {"走力": 71 if established else 67, "守備力": 51 if established else 47, "捕球": 45 if established else 42}
    elif position_style == "守備外野手":
        minimums = {"走力": 65 if established else 61, "肩力": 66 if established else 62, "守備力": 57 if established else 52, "捕球": 52 if established else 47}
    else:
        # 強打外野手は守備難を含む既存分布を残す。
        minimums = {}
    if low_tier:
        minimums = {key: value - (2 if key in {"守備力", "捕球"} else 1) for key, value in minimums.items()}
    for key, minimum in minimums.items():
        values[key] = max(values[key], minimum)


def apply_second_adjustment_fielder_distribution_guards(
    rng: random.Random,
    values: dict[str, int],
    position: str,
    player_class: str,
    position_style: str,
    weakness_profile: str,
) -> None:
    """第2次調整対象の分布だけを、最終値で局所的に整形する。"""
    low_tier = player_class in {"二軍級", "若手素材型"}
    if position == "二塁手":
        if (
            position_style == "守備走塁二塁手"
            and low_tier
            and weakness_profile != "低守備"
            and rng.random() < 0.68
        ):
            values["走力"] = max(values["走力"], 70)
            values["守備力"] = max(values["守備力"], rng.randint(60, 63))
            values["捕球"] = max(values["捕球"], 49)
        if low_tier and weakness_profile != "低ミート" and values["ミート"] <= 39 and rng.random() < 0.65:
            values["ミート"] = rng.randint(40, 45)
        return

    if position == "三塁手":
        reduction = rng.randint(3, 5) if position_style == "平均型三塁手" else rng.randint(1, 3)
        values["肩力"] = max(48, values["肩力"] - reduction)
        return

    if position == "捕手" and position_style != "守備型捕手":
        tail_chance = 0.90 if weakness_profile == "低捕球" else 0.72 if low_tier else 0.0
        if tail_chance and rng.random() < tail_chance:
            values["捕球"] = rng.randint(30, 39)


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
    weakness_profile: str = "",
    apply_second_adjustment: bool = True,
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
    apply_fictional_fielder_realism_audit(
        rng,
        values,
        category,
        age,
        position,
        player_class,
        archetype,
        position_style,
        weakness_profile,
        apply_second_adjustment,
    )
    if age >= 35:
        values["走力"] = cap_value(rng, values["走力"], 78)
    for key in values:
        values[key] = clamp(values[key])


def determine_trajectory(power: int, archetype: str, position: str, position_style: str, contact: int | None = None, player_class: str = "", physique_score: float = 0.0) -> int:
    power_score = power + max(-0.54, min(0.54, physique_score))
    trajectory = 4 if power_score >= 80 else 3 if power_score >= 58 else 2 if power_score >= 38 else 1
    power_profile = archetype == "長打" or position_style in {"強打一塁手", "強打三塁手", "強打外野手"}
    if position in {"二塁手", "外野手"}:
        if power_profile and 55 <= power_score < 58:
            trajectory = 3
        elif power_profile and 72 <= power_score < 80 and player_class in {"スター級", "一軍主力級", "大物実績者", "主力期待級"}:
            trajectory = 4
    elif power_profile and power_score >= 55:
        # 今回の弾道調整対象外は従来挙動を維持する。
        trajectory = min(4, trajectory + 1)
    if position in {"一塁手", "三塁手"} and power_score >= 52:
        trajectory = max(trajectory, 3)
    established = player_class in {"スター級", "一軍主力級", "ベテラン型"}
    contact = int(contact or 0)
    if position == "二塁手" and trajectory < 3:
        middle_profile = position_style == "打撃型二塁手" or archetype in {"巧打", "長打", "バランス"}
        if power_score >= 50 and (middle_profile or established) and (contact >= 42 or power_score >= 55):
            trajectory = 3
    if position == "外野手" and trajectory < 3:
        middle_profile = position_style in {"走攻守外野手", "強打外野手"} or archetype in {"巧打", "長打", "バランス"}
        if power_score >= 50 and (middle_profile or established) and (contact >= 42 or power_score >= 55):
            trajectory = 3
    if position == "捕手":
        top_class = player_class in {"スター級", "一軍主力級"}
        if trajectory == 4 and not (top_class and power_score >= 85):
            trajectory = 3
        if trajectory == 2:
            middle_profile = (
                (position_style == "打撃型捕手" and power_score >= 50 and contact >= 38)
                or (position_style == "平均型捕手" and power_score >= 52 and contact >= 42)
                or (position_style == "守備型捕手" and established and power_score >= 54 and contact >= 40)
            )
            if middle_profile:
                trajectory = 3
    if position == "遊撃手":
        if trajectory == 4 and not (player_class == "スター級" and power_score >= 88):
            trajectory = 3
        if trajectory == 2 and position_style != "守備走塁遊撃手":
            middle_profile = (
                (position_style == "強打遊撃手" and power_score >= 55)
                or (
                    position_style in {"巧打遊撃手", "平均型遊撃手"}
                    and established
                    and power_score >= 48
                    and contact >= 45
                )
            )
            if middle_profile:
                trajectory = 3
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
    weakness_profile: str = "",
) -> None:
    finalize_fielder_values(rng, values, category, age, position, player_class, archetype, position_style, allow_foreign_allrounder, weakness_profile)


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
    physique_z_height: float = 0.0,
    physique_z_build: float = 0.0,
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
        values["走力"] += 2 if age <= 34 else 1 if age <= 36 else 0
        values["肩力"] += 2
    apply_fielder_archetype_mods(rng, values, archetype, category)
    apply_fielder_position_mods(values, position, position_style)
    apply_fielder_development_mods(rng, values, development_stage)
    apply_fielder_acquisition_role_mods(values, archetype, position_style, acquisition_role)
    apply_fielder_weakness_profile(rng, values, weakness_profile)
    apply_fielder_variance(rng, values, category, development_stage)
    apply_fielder_growth_mods(values, age, growth_type, archetype, position_style)
    apply_fielder_physique_effects(values, physique_z_height, physique_z_build)
    finalize_fielder_values(
        rng,
        values,
        category,
        age,
        position,
        player_class,
        archetype,
        position_style,
        allow_foreign_allrounder,
        weakness_profile,
        False,
    )
    result = ability_values(values)
    result["弾道"] = determine_trajectory(
        values["パワー"], archetype, position, position_style, values["ミート"], player_class,
        trajectory_physique_adjustment(physique_z_height, physique_z_build),
    )
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
    elif category == "架空球団用":
        patterns = [
            ({"starter_aptitude": starter, "reliever_aptitude": reliever, "closer_aptitude": closer}, weight)
            for (starter, reliever, closer), weight in FICTIONAL_PITCHER_APTITUDE_PATTERNS
        ]
    return weighted_choice(rng, patterns).copy()


# 架空球団（日本人）の起用適性（先, 中, 抑）。実在は ◎（主）と ○（副）に分かれ、約3割が「先中◎」。
FICTIONAL_PITCHER_APTITUDE_PATTERNS = [
    (("◎", "-", "-"), 10.0), (("◎", "○", "-"), 11.2), (("◎", "-", "○"), 1.6),
    (("◎", "◎", "-"), 23.5), (("◎", "◎", "○"), 2.9),
    (("◎", "◎", "◎"), 2.4),
    (("-", "◎", "-"), 7.5), (("○", "◎", "-"), 11.6), (("○", "◎", "○"), 6.1), (("-", "◎", "○"), 8.9),
    (("-", "◎", "◎"), 10.3), (("○", "◎", "◎"), 4.0),
]
# 抑え◎の投手のうち、ポジションを「抑え」（守護神格）にする割合。残りは中継ぎ。
# 実在の守護神は1球団1人（全投手の3%前後）。
FICTIONAL_CLOSER_POSITION_RATE = 0.22


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
        "球速": curve_delta(age, [(18, 0), (22, 2), (28, 4), (34, 0), (35, -2), (36, -3), (39, -6), (42, -9), (46, -12)]),
        "コントロール": curve_delta(age, [(18, -8), (21, -4), (29, 4), (34, 5), (36, 4), (39, 3), (42, 1), (46, -1)]),
        "スタミナ": curve_delta(age, [(18, -5), (23, 0), (30, 5), (34, 0), (35, -1), (36, -2), (39, -4), (42, -6), (46, -8)]),
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


def apply_young_pitcher_stamina_mods(
    values: dict[str, int],
    age: int,
    category: str,
    aptitudes: dict[str, str],
    player_class: str,
    archetype: str,
    development_stage: str,
) -> None:
    if age > 19:
        return
    reduction = 5
    if player_class in {"若手素材型", "育成候補"} or development_stage == "素材型":
        reduction += 2
    if aptitudes.get("starter_aptitude") == "◎":
        reduction -= 2
    if player_class in {"スター級", "超上位候補"} and aptitudes.get("starter_aptitude") == "◎":
        reduction -= 2
    if archetype == "スタミナ" and aptitudes.get("starter_aptitude") in {"◎", "○"}:
        reduction -= 2
    values["スタミナ"] -= max(2, reduction)


def apply_veteran_pitcher_role_mods(values: dict[str, int], age: int, aptitudes: dict[str, str], player_class: str, archetype: str) -> None:
    if age < 35:
        return
    starter = aptitudes.get("starter_aptitude", "-")
    survivor = player_class == "ベテラン型" or archetype == "スタミナ"
    if starter == "◎":
        values["スタミナ"] += 5 if survivor else 3
    elif starter == "○":
        values["スタミナ"] += 3 if survivor else 2


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
            "大物実績者": {"球速": 4, "コントロール": 8, "スタミナ": 5},
            "主力期待級": {"球速": 3, "コントロール": 4, "スタミナ": 2},
            "レギュラー競争級": {"球速": 4, "コントロール": -1, "スタミナ": -1},
            "保険・バックアップ級": {"球速": 1, "コントロール": -7, "スタミナ": -5},
            "育成素材型": {"球速": 4, "コントロール": -10, "スタミナ": -8},
            "再生候補": {"球速": -1, "コントロール": 0, "スタミナ": -4},
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
        add_mod(values, {"球速": 3, "コントロール": -1, "スタミナ": -3})
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
        if category == "助っ人外国人用":
            values["球速"] = rng.randint(157, 159)
        else:
            values["球速"] = cap_value(rng, values["球速"], rng.randint(154, 159) if archetype == "速球" and player_class not in {"二軍級", "ベテラン型"} else rng.randint(149, 154))
    if category == "助っ人外国人用" and values["球速"] >= 160 and rng.random() < 0.35:
        values["球速"] = rng.randint(156, 159)
    if category == "架空球団用" and values["球速"] >= 160 and rng.random() < 0.45:
        values["球速"] = rng.randint(157, 159)
    if archetype in {"制球", "変化球", "スタミナ"} or player_class == "ベテラン型" or age >= 35:
        values["球速"] = cap_value(rng, values["球速"], 159)
    if age >= 35:
        values["球速"] = cap_value(rng, values["球速"], 156)
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


def pitcher_base_values(category: str) -> dict[str, int]:
    if category == "助っ人外国人用":
        return {"球速": 155, "コントロール": 44, "スタミナ": 49}
    return {"球速": 145, "コントロール": 48, "スタミナ": 48}


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
    physique_z_height: float = 0.0,
    physique_z_build: float = 0.0,
) -> dict[str, Any]:
    archetype = archetype or legacy_archetype_from_player_type("投手", player_type) or "総合"
    player_class = player_class or "一軍控え級"
    role = primary_pitcher_role(aptitudes)
    position_style = position_style or PITCHER_POSITION_STYLE_BY_ROLE.get(role, {}).get(archetype, "")
    values = pitcher_base_values(category)
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
    apply_young_pitcher_stamina_mods(values, age, category, aptitudes, player_class, archetype, development_stage)
    apply_veteran_pitcher_role_mods(values, age, aptitudes, player_class, archetype)
    apply_fictional_pitcher_age_speed_shape(rng, values, category, age, player_class, archetype, position_style, weakness_profile)
    shape_pitcher_speed_distribution(rng, values, category, age, player_class, archetype, position_style, weakness_profile)
    apply_pitcher_physique_effects(values, physique_z_height, physique_z_build)
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
    _ball("スライダー", "1", 127, 23, 1, 6), _ball("Hスライダー", "1", 65, 9, 1, 5), _ball("カットボール", "1", 135, 26, 1, 6),
    _ball("カーブ", "2", 66, 10, 1, 5), _ball("スローカーブ", "2", 30, 4, 1, 3), _ball("ドロップカーブ", "2", 42, 6, 1, 5), _ball("スラーブ", "2", 73, 12, 1, 6), _ball("ナックルカーブ", "2", 30, 4, 1, 5), _ball("パワーカーブ", "2", 13, 4, 1, 5, {"速球派": 3, "助っ人外国人用": 8}), _ball("Dスライダー", "2", 3, 1, 1, 5),
    _ball("フォーク", "3", 96, 18, 1, 6), _ball("パーム", "3", 4, 1, 1, 3), _ball("チェンジアップ", "3", 34, 6, 1, 5), _ball("Vスライダー", "3", 59, 10, 1, 6), _ball("SFF", "3", 102, 22, 1, 6, {"助っ人外国人用": 10}), _ball("ナックル", "3", 1, 0, 1, 5),
    _ball("シンカー", "4", 10, 2, 1, 3), _ball("Hシンカー", "4", 34, 3, 1, 5), _ball("スクリュー", "4", 10, 2, 1, 3), _ball("サークルチェンジ", "4", 65, 4, 1, 6), _ball("シンキングスプリット", "4", 44, 4, 1, 5, {"助っ人外国人用": 8}), _ball("ファストチェンジ", "4", 10, 1, 1, 4),
    _ball("シュート", "5", 3, 1, 1, 2), _ball("Hシュート", "5", 15, 1, 1, 4), _ball("シンキングツーシーム", "5", 27, 1, 1, 4),
]
BREAKING_BY_NAME = {ball["name"]: ball for ball in BREAKING_BALL_MASTER}
DIRECTION_SELECTION_WEIGHTS = {"1": 32, "2": 24, "3": 28, "4": 13, "5": 4}
# Phase 3: 実在402投手の左右別方向セット件数へ全候補1件の疑似カウントを加えたsoft weight。
# 少標本の左投手や未観測セットを固定・排除せず、方向セット相関だけを表現する。
DIRECTION_SET_WEIGHTS_BY_HAND = {
    "右投": {
        2: {
            ("1", "2"): 8, ("1", "3"): 47, ("1", "4"): 19, ("1", "5"): 2,
            ("2", "3"): 27, ("2", "4"): 8, ("2", "5"): 1, ("3", "4"): 10,
            ("3", "5"): 1, ("4", "5"): 1,
        },
        3: {
            ("1", "2", "3"): 72, ("1", "2", "4"): 35, ("1", "2", "5"): 7,
            ("1", "3", "4"): 21, ("1", "3", "5"): 5, ("1", "4", "5"): 4,
            ("2", "3", "4"): 6, ("2", "3", "5"): 4, ("2", "4", "5"): 4,
            ("3", "4", "5"): 1,
        },
    },
    "左投": {
        2: {
            ("1", "2"): 6, ("1", "3"): 24, ("1", "4"): 10, ("1", "5"): 2,
            ("2", "3"): 14, ("2", "4"): 12, ("2", "5"): 2, ("3", "4"): 2,
            ("3", "5"): 1, ("4", "5"): 1,
        },
        3: {
            ("1", "2", "3"): 23, ("1", "2", "4"): 32, ("1", "2", "5"): 6,
            ("1", "3", "4"): 9, ("1", "3", "5"): 6, ("1", "4", "5"): 1,
            ("2", "3", "4"): 9, ("2", "3", "5"): 1, ("2", "4", "5"): 2,
            ("3", "4", "5"): 1,
        },
    },
}
SECOND_PITCH_DIRECTION_WEIGHTS = {"1": 23, "2": 12, "3": 34, "4": 3, "5": 1}

# Phase 0の実在402投手を基準にしたsoft分布。30件未満の球種は全体分布へ縮約する。
MOVEMENT_GLOBAL_WEIGHTS = {1: 24, 2: 27, 3: 30, 4: 13, 5: 4, 6: 2}
MOVEMENT_PREFERENCE_WEIGHTS = {
    "スライダー": {1: 16, 2: 32, 3: 32, 4: 15, 5: 2, 6: 2},
    "Hスライダー": {1: 28, 2: 35, 3: 31, 4: 3, 5: 3},
    "カットボール": {1: 32, 2: 21, 3: 33, 4: 10, 5: 2, 6: 1},
    "カーブ": {1: 52, 2: 30, 3: 14, 4: 2, 5: 3},
    "スラーブ": {1: 19, 2: 15, 3: 33, 4: 26, 5: 4, 6: 3},
    "Vスライダー": {1: 7, 2: 32, 3: 41, 4: 17, 5: 2, 6: 2},
    "フォーク": {1: 11, 2: 22, 3: 29, 4: 23, 5: 7, 6: 7},
    "SFF": {1: 13, 2: 25, 3: 35, 4: 18, 5: 7, 6: 3},
    "チェンジアップ": {1: 15, 2: 9, 3: 44, 4: 29, 5: 3},
    "サークルチェンジ": {1: 22, 2: 37, 3: 28, 4: 9, 5: 1, 6: 4},
    "Hシンカー": {1: 21, 2: 29, 3: 32, 4: 15, 5: 3},
}
MOVEMENT_STYLE_WEIGHTS_BY_TOTAL = {
    5: {"balanced": 47, "primary_pitch": 1, "finisher": 53},
    6: {"balanced": 30, "primary_pitch": 46, "finisher": 25},
    7: {"balanced": 37, "primary_pitch": 54, "finisher": 9},
    8: {"balanced": 35, "primary_pitch": 33, "finisher": 32},
    9: {"balanced": 21, "primary_pitch": 36, "finisher": 44},
    10: {"balanced": 40, "primary_pitch": 25, "finisher": 35},
}
SECOND_PITCH_MOVEMENT_WEIGHTS = {1: 40, 2: 30, 3: 27, 4: 15}
PHASE2_PITCH_COUNT_ENABLED = True
PHASE3_DIRECTION_SETS_ENABLED = True
PHASE4_SECONDARY_SLOTS_ENABLED = True
LEGACY_MOVEMENT_BOUNDS = {
    "スライダー": (2, 4), "Hスライダー": (1, 3), "カットボール": (1, 3),
    "カーブ": (1, 3), "スローカーブ": (1, 2), "ドロップカーブ": (1, 3),
    "スラーブ": (2, 4), "ナックルカーブ": (2, 3), "パワーカーブ": (2, 4), "Dスライダー": (3, 5),
    "フォーク": (2, 4), "パーム": (1, 3), "チェンジアップ": (2, 4), "Vスライダー": (2, 4),
    "SFF": (2, 4), "ナックル": (2, 5), "シンカー": (1, 3), "Hシンカー": (2, 3),
    "スクリュー": (1, 3), "サークルチェンジ": (2, 3), "シンキングスプリット": (2, 4),
    "ファストチェンジ": (2, 3), "シュート": (1, 2), "Hシュート": (1, 2),
    "シンキングツーシーム": (1, 3),
}


def allowed_pitch_names_for_generation(direction_code: str, batting_throwing: str) -> set[str]:
    if str(batting_throwing).startswith("左投"):
        return ALLOWED_PITCHES_BY_DIRECTION_LEFT[direction_code]
    return ALLOWED_PITCHES_BY_DIRECTION_RIGHT[direction_code]


def is_pitch_allowed_for_generation(direction_code: str, pitch_name: str, batting_throwing: str) -> bool:
    return pitch_name in allowed_pitch_names_for_generation(direction_code, batting_throwing)


def weighted_breaking_names(
    rng: random.Random,
    direction_code: str,
    player_type: str,
    category: str,
    batting_throwing: str,
    *,
    second_pitch: bool = False,
    exclude: set[str] | None = None,
    max_min_movement: int | None = None,
) -> str:
    choices = []
    allowed = allowed_pitch_names_for_generation(direction_code, batting_throwing)
    exclude = exclude or set()
    for ball in BREAKING_BALL_MASTER:
        if ball["direction_code"] != direction_code or ball["name"] not in allowed or ball["name"] in exclude:
            continue
        weight_key = "second_pitch_weight" if second_pitch else "base_weight"
        weight = int(ball.get(weight_key, 0) or 0)
        if second_pitch and not ball.get("second_pitch_allowed", False):
            continue
        if max_min_movement is not None and int(ball.get("min_movement", 1)) > max_min_movement:
            continue
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


def second_fastball_age_adjustment(age: int | None) -> float:
    if age is None:
        return 0.0
    return max(-0.07, min(0.15, (age - 24) * 0.018))


def generate_second_fastball(rng: random.Random, player_type: str, category: str, aptitudes: dict[str, str], age: int | None = None) -> dict[str, Any] | None:
    chance = 0.115
    if player_type in {"技巧派", "変化球派"}:
        chance += 0.015
    if category == "助っ人外国人用":
        chance += 0.055
    if category == "ドラフト候補用":
        chance -= 0.045
    if aptitudes.get("closer_aptitude") == "◎":
        chance += 0.01
    if PHASE2_PITCH_COUNT_ENABLED:
        chance += second_fastball_age_adjustment(age)
    if rng.random() >= max(0.01 if PHASE2_PITCH_COUNT_ENABLED else 0.04, min(0.30, chance)):
        return None
    return select_second_fastball_type(rng)


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


def phase2_primary_count_promotion_chance(age: int | None) -> float:
    if age is None:
        return 0.0
    if age <= 22:
        return 0.12
    if age <= 26:
        return 0.08 + (age - 23) * 0.01
    if age <= 30:
        return 0.28 + (age - 27) * 0.03
    if age <= 34:
        return 0.20 + (age - 31) * 0.02
    return 0.28


def phase2_adjust_primary_pitch_count(rng: random.Random, count: int, age: int | None) -> int:
    if not PHASE2_PITCH_COUNT_ENABLED or count != 2:
        return count
    return 3 if rng.random() < phase2_primary_count_promotion_chance(age) else count


def phase2_four_pitch_retention_chance(age: int | None) -> float:
    if age is None:
        return 0.10
    if age <= 22:
        return 0.04
    if age <= 26:
        return 0.07
    if age <= 30:
        return 0.12
    if age <= 34:
        return 0.18
    return 0.20


def phase2_limit_final_pitch_count(
    rng: random.Random, balls: list[dict[str, Any]], age: int | None
) -> list[dict[str, Any]]:
    if not PHASE2_PITCH_COUNT_ENABLED:
        return balls
    primary = primary_breaking_balls(balls)
    second = [ball for ball in balls if ball.get("kind") == "breaking" and ball.get("is_second_pitch")]
    fastballs = [ball for ball in balls if ball.get("kind") == "second_fastball"]

    # 実在では同時保有がほぼない。年齢が高いほど第二ストレートを残しやすくする。
    if second and fastballs:
        keep_fastball_chance = max(0.35, min(0.75, 0.45 + ((age or 26) - 26) * 0.025))
        if rng.random() < keep_fastball_chance:
            balls = [ball for ball in balls if ball not in second]
        else:
            balls = [ball for ball in balls if ball not in fastballs]

    primary_count = len(primary_breaking_balls(balls))
    display_count = sum(1 for ball in balls if ball.get("kind") in {"breaking", "second_fastball"})
    if primary_count >= 4:
        return [ball for ball in balls if not ball.get("is_second_pitch") and ball.get("kind") != "second_fastball"]
    if primary_count == 3 and display_count >= 4:
        if rng.random() >= phase2_four_pitch_retention_chance(age):
            return [ball for ball in balls if not ball.get("is_second_pitch") and ball.get("kind") != "second_fastball"]
    return balls


def interpolate_age_chance(age: int | None, anchors: list[tuple[int, float]]) -> float:
    if age is None:
        return 0.0
    if age <= anchors[0][0]:
        return anchors[0][1]
    for (low_age, low_value), (high_age, high_value) in zip(anchors, anchors[1:], strict=False):
        if age <= high_age:
            span = high_age - low_age
            ratio = (age - low_age) / span if span else 0.0
            return low_value + (high_value - low_value) * ratio
    return anchors[-1][1]


def phase4_composition_chances(age: int | None, role: str) -> tuple[float, float]:
    second_breaking = interpolate_age_chance(
        age,
        [(18, 0.0), (21, 0.0), (23, 0.05), (26, 0.14), (30, 0.14), (34, 0.08), (40, 0.03)],
    )
    second_fastball = interpolate_age_chance(
        age,
        [(18, 0.0), (22, 0.0), (24, 0.01), (26, 0.03), (30, 0.20), (34, 0.22), (36, 0.14), (40, 0.08)],
    )
    breaking_role_multiplier = {"先発": 0.85, "中継ぎ": 1.15, "抑え": 1.20}.get(role, 1.0)
    fastball_role_multiplier = {"先発": 0.95, "中継ぎ": 1.05, "抑え": 1.10}.get(role, 1.0)
    return second_breaking * breaking_role_multiplier, second_fastball * fastball_role_multiplier


def choose_repertoire_composition(
    rng: random.Random,
    balls: list[dict[str, Any]],
    age: int | None,
    role: str,
    category: str,
    weakness_profile: str,
) -> str:
    if not PHASE4_SECONDARY_SLOTS_ENABLED or category != "架空球団用":
        return "primary_only"
    if weakness_profile == "球種不足":
        return "primary_only"
    display = [ball for ball in balls if ball.get("kind") in {"breaking", "second_fastball"}]
    primary = primary_breaking_balls(balls)
    if len(display) != 3 or len(primary) != 3:
        return "primary_only"
    if any(ball.get("is_second_pitch") or ball.get("kind") == "second_fastball" for ball in balls):
        return "primary_only"
    second_breaking, second_fastball = phase4_composition_chances(age, role)
    value = rng.random()
    if value < second_breaking:
        return "second_breaking"
    if value < second_breaking + second_fastball:
        return "second_fastball"
    return "primary_only"


def select_second_fastball_type(rng: random.Random) -> dict[str, Any]:
    name = weighted_choice(rng, [("ツーシームファスト", 43), ("ムービングファスト", 3), ("超スローボール", 1)])
    return {"name": name, "direction_code": None, "direction": "ストレート系第二種", "movement": 0, "level": 0, "is_second_pitch": False, "slot": None, "kind": "second_fastball"}


def apply_phase4_repertoire_composition(
    rng: random.Random,
    balls: list[dict[str, Any]],
    player_type: str,
    category: str,
    aptitudes: dict[str, str],
    batting_throwing: str,
    *,
    age: int | None,
    role: str,
    archetype: str,
    weakness_profile: str,
) -> list[dict[str, Any]]:
    composition_rng = random.Random()
    composition_rng.setstate(rng.getstate())
    composition = choose_repertoire_composition(
        composition_rng, balls, age, role, category, weakness_profile
    )
    if composition == "primary_only":
        return balls

    original_total = primary_total_movement(balls)
    direction_codes = [
        code for code in DIRECTION_NAMES
        if any(
            ball["direction_code"] == code
            and ball["name"] in allowed_pitch_names_for_generation(code, batting_throwing)
            for ball in BREAKING_BALL_MASTER
        )
    ]
    primary_codes = weighted_direction_sample(
        composition_rng, direction_codes, 2, role, batting_throwing
    )
    replacement: list[dict[str, Any]] = []
    for direction_code in primary_codes:
        name = weighted_breaking_names(
            composition_rng, direction_code, player_type, category, batting_throwing
        )
        movement = weighted_choice(
            composition_rng,
            movement_weights(
                player_type, category, aptitudes, 2,
                archetype=archetype, weakness_profile=weakness_profile,
            ),
        )
        replacement.append(make_breaking_ball(name, movement, False, 1))
    normalize_primary_movements(composition_rng, replacement, original_total)

    if composition == "second_fastball":
        replacement.append(select_second_fastball_type(composition_rng))
        return replacement

    candidates = []
    for ball in replacement:
        names = allowed_pitch_names_for_generation(
            str(ball["direction_code"]), batting_throwing
        ) - {ball["name"]}
        if any(
            BREAKING_BY_NAME[name].get("second_pitch_allowed", False)
            and int(BREAKING_BY_NAME[name].get("min_movement", 1)) <= pitch_movement(ball)
            for name in names
        ):
            candidates.append(ball)
    if not candidates:
        return balls
    base = weighted_choice(
        composition_rng,
        [(ball, SECOND_PITCH_DIRECTION_WEIGHTS.get(str(ball["direction_code"]), 1)) for ball in candidates],
    )
    direction_code = str(base["direction_code"])
    second_name = weighted_breaking_names(
        composition_rng, direction_code, player_type, category, batting_throwing,
        second_pitch=True, exclude={base["name"]},
        max_min_movement=pitch_movement(base),
    )
    second_movement = select_second_pitch_movement(composition_rng, base, second_name)
    replacement.append(make_breaking_ball(second_name, second_movement, True, 2))
    return replacement


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


def direction_set_weights(
    count: int,
    batting_throwing: str,
    role: str = "",
) -> list[tuple[tuple[str, ...], int]]:
    hand = "左投" if str(batting_throwing).startswith("左投") else "右投"
    source = DIRECTION_SET_WEIGHTS_BY_HAND.get(hand, {}).get(count, {})
    items = []
    for direction_set, base_weight in source.items():
        weight = float(base_weight)
        if role == "抑え" and "2" in direction_set:
            # 既存の抑え方向2補正（24→15相当）をセット抽選でも維持する。
            weight *= 0.625
        items.append((direction_set, max(1, round(weight * 8))))
    return items


def legacy_weighted_direction_sample(
    rng: random.Random,
    direction_codes: list[str],
    count: int,
    role: str = "",
) -> list[str]:
    remaining = list(direction_codes)
    selected: list[str] = []
    weights = dict(DIRECTION_SELECTION_WEIGHTS)
    if role == "抑え":
        weights["2"] = 15
    for _ in range(min(count, len(remaining))):
        code = weighted_choice(rng, [(code, weights.get(code, 1)) for code in remaining])
        selected.append(code)
        remaining.remove(code)
    return selected


def weighted_direction_sample(
    rng: random.Random,
    direction_codes: list[str],
    count: int,
    role: str = "",
    batting_throwing: str = "右投",
) -> list[str]:
    available = set(direction_codes)
    if PHASE3_DIRECTION_SETS_ENABLED and count in {2, 3}:
        choices = [
            (direction_set, weight)
            for direction_set, weight in direction_set_weights(count, batting_throwing, role)
            if set(direction_set).issubset(available)
        ]
        if choices:
            selected = list(weighted_choice(rng, choices))
            # 旧非復元抽選と同じ乱数消費数にし、後続の球種数・能力生成への波及を抑える。
            for _ in range(count - 1):
                rng.random()
            return selected
    return legacy_weighted_direction_sample(rng, direction_codes, count, role)


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


def movement_partitions(total: int, count: int, maximum: int = 6) -> list[tuple[int, ...]]:
    """正の整数を降順に並べた、順序を無視するmovement分割を返す。"""
    if count <= 0 or total < count:
        return []

    def build(remaining: int, slots: int, upper: int) -> list[tuple[int, ...]]:
        if slots == 0:
            return [()] if remaining == 0 else []
        minimum_remaining = slots - 1
        largest = min(upper, maximum, remaining - minimum_remaining)
        rows: list[tuple[int, ...]] = []
        for value in range(largest, 0, -1):
            if remaining - value < minimum_remaining:
                continue
            for tail in build(remaining - value, slots - 1, value):
                rows.append((value, *tail))
        return rows

    return build(total, count, maximum)


def movement_pattern_style(values: tuple[int, ...]) -> str:
    if not values:
        return "balanced"
    if max(values) - min(values) <= 1:
        return "balanced"
    total = sum(values)
    if max(values) >= 5 or max(values) / total >= 0.60:
        return "finisher"
    return "primary_pitch"


def movement_preference_weight(name: str, value: int) -> int:
    weights = MOVEMENT_PREFERENCE_WEIGHTS.get(name, MOVEMENT_GLOBAL_WEIGHTS)
    return max(1, int(weights.get(value, 1)))


def movement_assignment_candidates(
    balls: list[dict[str, Any]], partition: tuple[int, ...]
) -> list[tuple[tuple[int, ...], int]]:
    candidates: list[tuple[tuple[int, ...], int]] = []
    for assignment in sorted(set(itertools.permutations(partition)), reverse=True):
        weight = 1
        valid = True
        for ball, value in zip(balls, assignment, strict=True):
            master = BREAKING_BY_NAME[ball["name"]]
            minimum = int(master.get("min_movement", 1))
            maximum = int(master.get("max_movement", 6))
            if not minimum <= value <= maximum:
                valid = False
                break
            weight *= movement_preference_weight(ball["name"], value)
        if valid:
            candidates.append((assignment, weight))
    return candidates


def select_primary_movement_assignment(
    rng: random.Random, balls: list[dict[str, Any]], target: int
) -> tuple[int, ...]:
    partitions = movement_partitions(target, len(balls))
    by_style: dict[str, list[tuple[tuple[int, ...], list[tuple[tuple[int, ...], int]], int]]] = {
        "balanced": [], "primary_pitch": [], "finisher": [],
    }
    for partition in partitions:
        assignments = movement_assignment_candidates(balls, partition)
        if assignments:
            by_style[movement_pattern_style(partition)].append(
                (partition, assignments, sum(weight for _, weight in assignments))
            )

    available_styles = [style for style, candidates in by_style.items() if candidates]
    if available_styles:
        style_weights = MOVEMENT_STYLE_WEIGHTS_BY_TOTAL.get(
            min(10, target), {"balanced": 35, "primary_pitch": 40, "finisher": 25}
        )
        style = weighted_choice(rng, [(name, style_weights[name]) for name in available_styles])
        _partition, assignments, _ = weighted_choice(
            rng, [(candidate, candidate[2]) for candidate in by_style[style]]
        )
        return weighted_choice(rng, assignments)

    # 稀なhard bounds非充足時は範囲内の最近傍総量を使う。無制限clampはしない。
    ranges = [
        range(
            int(BREAKING_BY_NAME[ball["name"]].get("min_movement", 1)),
            int(BREAKING_BY_NAME[ball["name"]].get("max_movement", 6)) + 1,
        )
        for ball in balls
    ]
    feasible = list(itertools.product(*ranges))
    nearest_distance = min(abs(sum(values) - target) for values in feasible)
    nearest = [values for values in feasible if abs(sum(values) - target) == nearest_distance]
    return weighted_choice(
        rng,
        [
            (values, math.prod(movement_preference_weight(ball["name"], value) for ball, value in zip(balls, values, strict=True)))
            for values in nearest
        ],
    )


def consume_legacy_primary_normalization_rng(
    rng: random.Random, balls: list[dict[str, Any]], target: int
) -> int:
    """Phase 1対象外の後続抽選率を維持するため、旧処理と同じ乱数だけ消費する。"""
    values = []
    for ball in balls:
        _minimum, maximum = LEGACY_MOVEMENT_BOUNDS[ball["name"]]
        values.append(max(1, min(maximum, target // len(balls))))
    attempts = 0
    while sum(values) < target and attempts < 40:
        index = rng.randrange(len(balls))
        _minimum, maximum = LEGACY_MOVEMENT_BOUNDS[balls[index]["name"]]
        if values[index] < maximum:
            values[index] += 1
        attempts += 1
    while sum(values) > target and attempts < 80:
        index = rng.randrange(len(balls))
        minimum, _maximum = LEGACY_MOVEMENT_BOUNDS[balls[index]["name"]]
        if values[index] > minimum:
            values[index] -= 1
        attempts += 1
    return sum(values)


def normalize_primary_movements(rng: random.Random, balls: list[dict[str, Any]], target: int) -> None:
    primary = [ball for ball in balls if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")]
    if not primary:
        return
    target = max(len(primary), target)
    movement_rng = random.Random()
    movement_rng.setstate(rng.getstate())
    effective_target = consume_legacy_primary_normalization_rng(rng, primary, target)
    assignment = select_primary_movement_assignment(movement_rng, primary, effective_target)
    for ball, value in zip(primary, assignment, strict=True):
        ball["movement"] = ball["level"] = value


def select_second_pitch_movement(rng: random.Random, first_ball: dict[str, Any], second_name: str) -> int:
    master = BREAKING_BY_NAME[second_name]
    minimum = int(master.get("min_movement", 1))
    maximum = min(
        4,
        pitch_movement(first_ball),
        int(master.get("max_movement", 4)),
    )
    maximum = max(minimum, maximum)
    choices = []
    for value in range(minimum, maximum + 1):
        weight = SECOND_PITCH_MOVEMENT_WEIGHTS.get(value, 1)
        weight *= movement_preference_weight(second_name, value)
        if value == pitch_movement(first_ball):
            weight = max(1, round(weight * 0.7))
        choices.append((value, weight))
    movement_rng = random.Random()
    movement_rng.setstate(rng.getstate())
    value = int(weighted_choice(movement_rng, choices))
    # 旧処理のrandom判定＋weighted_choiceと同じ2回分を消費し、後続の発生率を固定する。
    rng.random()
    weighted_choice(rng, [(1, 38), (2, 38), (3, 19), (4, 5)])
    return value


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
    else:
        count = phase2_adjust_primary_pitch_count(rng, count, age)
    direction_codes = [code for code in DIRECTION_NAMES if any(ball["direction_code"] == code and ball["name"] in allowed_pitch_names_for_generation(code, batting_throwing) for ball in BREAKING_BALL_MASTER)]
    direction_start_state = rng.getstate()
    primary_codes = weighted_direction_sample(rng, direction_codes, count, role, batting_throwing)
    balls: list[dict[str, Any]] = []
    for direction_code in primary_codes:
        name = weighted_breaking_names(rng, direction_code, player_type, category, batting_throwing)
        movement = weighted_choice(rng, movement_weights(player_type, category, aptitudes, count, archetype=archetype, weakness_profile=weakness_profile))
        balls.append(make_breaking_ball(name, movement, False, 1))
    target = target_total_movement(rng, category, age, role, player_class, archetype, development_stage, acquisition_role, weakness_profile, count)
    normalize_primary_movements(rng, balls, target)
    if PHASE3_DIRECTION_SETS_ENABLED and count in {2, 3}:
        # 方向変更が第二球種・第二ストレート・総球種数の抽選列を変えないよう、
        # Phase 2方式で第一球種を生成した場合の乱数状態へ戻して後続処理を開始する。
        legacy_rng = random.Random()
        legacy_rng.setstate(direction_start_state)
        legacy_codes = legacy_weighted_direction_sample(legacy_rng, direction_codes, count, role)
        legacy_balls: list[dict[str, Any]] = []
        for direction_code in legacy_codes:
            legacy_name = weighted_breaking_names(
                legacy_rng, direction_code, player_type, category, batting_throwing
            )
            legacy_movement = weighted_choice(
                legacy_rng,
                movement_weights(
                    player_type, category, aptitudes, count,
                    archetype=archetype, weakness_profile=weakness_profile,
                ),
            )
            legacy_balls.append(make_breaking_ball(legacy_name, legacy_movement, False, 1))
        legacy_target = target_total_movement(
            legacy_rng, category, age, role, player_class, archetype,
            development_stage, acquisition_role, weakness_profile, count,
        )
        normalize_primary_movements(legacy_rng, legacy_balls, legacy_target)
        rng.setstate(legacy_rng.getstate())
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
            if any(
                BREAKING_BY_NAME[name].get("second_pitch_allowed", False)
                and int(BREAKING_BY_NAME[name].get("min_movement", 1)) <= pitch_movement(ball)
                for name in names
            ):
                candidates.append(ball)
        if candidates:
            base = weighted_choice(rng, [(ball, SECOND_PITCH_DIRECTION_WEIGHTS.get(str(ball["direction_code"]), 1)) for ball in candidates])
            direction_code = str(base["direction_code"])
            second_name = weighted_breaking_names(
                rng, direction_code, player_type, category, batting_throwing,
                second_pitch=True, exclude={base["name"]},
                max_min_movement=pitch_movement(base),
            )
            second_movement = select_second_pitch_movement(rng, base, second_name)
            balls.append(make_breaking_ball(second_name, second_movement, True, 2))
    second_fastball = generate_second_fastball(rng, player_type, category, aptitudes, age)
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
    balls = phase2_limit_final_pitch_count(rng, balls, age)
    return apply_phase4_repertoire_composition(
        rng, balls, player_type, category, aptitudes, batting_throwing,
        age=age, role=role, archetype=archetype, weakness_profile=weakness_profile,
    )


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


def enforce_second_pitch_movement_order(breaking_balls: list[dict[str, Any]]) -> None:
    """Keep each second pitch at or below its same-direction primary pitch."""
    primary_by_direction = {
        str(ball.get("direction_code", "")): ball
        for ball in primary_breaking_balls(breaking_balls)
    }
    audited: list[dict[str, Any]] = []
    for ball in breaking_balls:
        if ball.get("kind") != "breaking" or not ball.get("is_second_pitch"):
            audited.append(ball)
            continue
        primary = primary_by_direction.get(str(ball.get("direction_code", "")))
        if primary is None:
            continue
        maximum = pitch_movement(primary)
        minimum = int(BREAKING_BY_NAME[str(ball["name"])].get("min_movement", 1))
        if minimum > maximum:
            continue
        if pitch_movement(ball) > maximum:
            ball["movement"] = ball["level"] = maximum
        audited.append(ball)
    breaking_balls[:] = audited


def shape_second_adjustment_middle_reliever_stamina(
    stamina: int,
    category: str,
    role_name: str,
    position_style: str,
) -> int:
    """中継ぎだけを中心へ寄せ、先発・抑えとロング型の幅は保護する。"""
    if category != "架空球団用" or role_name != "中継ぎ":
        return stamina
    factor = 0.70 if position_style == "ロングリリーフ型" else 0.62
    return clamp(round(49 + (stamina - 49) * factor))


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
        audit_fielder_values(rng, values, category, age, position, player_class, archetype, position_style, allow_foreign_allrounder, weakness_profile)
        audited = ability_values(values)
        audited["弾道"] = determine_trajectory(values["パワー"], archetype, position, position_style, values["ミート"], player_class)
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
    stamina = shape_second_adjustment_middle_reliever_stamina(
        stamina, category, role_name, position_style
    )
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
    enforce_second_pitch_movement_order(breaking_balls)
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
    type_weights = FICTIONAL_PITCHING_FORM_TYPE_WEIGHTS if category == "架空球団用" else PITCHING_FORM_TYPE_WEIGHTS
    return generate_form(rng, PITCHING_FORM_RANGES, type_weights, PITCHING_FORM_GENERIC_RATE.get(category, 0.92), boosts)


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


# ---------------------------------------------------------------------------
# 助っ人外国人投手の実在準拠バランス
# 基準: パワプロ2022〜2026 デフォルト選手データの外国人投手（延べ214人）。
# 既存処理で作った選手を名前空間付きサブRNGで再調整する。主RNGは消費しないため、
# 日本人選手や野手の既存seedの生成結果は変わらない。
# ---------------------------------------------------------------------------
FOREIGN_PITCHER_BALANCE_NAMESPACE = "foreign_pitcher_balance_v1"
FOREIGN_PITCHER_SPEED_MEANS = {"先発": 154.4, "中継ぎ": 157.5, "抑え": 158.3}
FOREIGN_PITCHER_SPEED_ARCHETYPE = {"速球": 2.0, "総合": 0.3, "制球": -2.0, "変化球": -1.2, "スタミナ": -1.0}
FOREIGN_PITCHER_CONTROL_MEANS = {"先発": 54.0, "中継ぎ": 45.5, "抑え": 49.0}
FOREIGN_PITCHER_CONTROL_ARCHETYPE = {"速球": -5.0, "総合": 0.0, "制球": 8.0, "変化球": 2.0, "スタミナ": 1.0}
FOREIGN_PITCHER_STAMINA_MEANS = {"先発": 59.5, "中継ぎ": 47.5, "抑え": 47.5}
FOREIGN_PITCHER_HEIGHT_BY_NATIONALITY = {
    "アメリカ": 193.0, "ドミニカ共和国": 189.5, "ベネズエラ": 189.0, "キューバ": 190.0,
    "メキシコ": 188.0, "韓国": 185.0, "台湾": 184.0,
}
FOREIGN_PITCHING_FORM_WEIGHTS = [("オーバースロー", 67), ("スリークォーター", 30), ("サイドスロー", 3)]
FOREIGN_PITCHER_LEFT_TO_RIGHT_RATE = 0.20
# 1投手あたりの出現率（実在）を重みの目安にする。2026新球種は2026のみの値。
FOREIGN_PITCH_WEIGHTS = {
    "スライダー": 36, "サークルチェンジ": 27, "カットボール": 23, "ナックルカーブ": 22, "SFF": 19,
    "Hシンカー": 32, "Hスライダー": 17, "ファストチェンジ": 17, "Vスライダー": 15, "パワーカーブ": 13,
    "スラーブ": 13, "チェンジアップ": 12, "シンキングスプリット": 10, "ドロップカーブ": 8, "フォーク": 5,
    "カーブ": 5, "シンキングツーシーム": 5, "スクリュー": 4, "シンカー": 0.5, "Hシュート": 1,
    "Dスライダー": 1, "スローカーブ": 0.3, "パーム": 0.2, "シュート": 0.2,
}
FOREIGN_SAME_DIRECTION_FACTOR = 0.25
# 決め球になりやすさ（実在の1球種あたり変化量が大きい球種ほど高い）
FOREIGN_FINISHER_AFFINITY = {
    "Vスライダー": 3.0, "パワーカーブ": 3.0, "ドロップカーブ": 3.0, "SFF": 2.5, "スラーブ": 2.5, "フォーク": 2.5,
    "ナックルカーブ": 2.0, "スライダー": 2.0, "サークルチェンジ": 2.0, "チェンジアップ": 2.0,
    "Hシンカー": 1.8, "シンキングスプリット": 1.8, "Hスライダー": 1.5, "カットボール": 1.0,
    "ファストチェンジ": 0.8, "シンキングツーシーム": 0.5,
}
FOREIGN_FINISHER_MOVEMENT_WEIGHTS = {
    "先発": [(3, 32), (4, 43), (5, 20), (6, 5)],
    "中継ぎ": [(3, 30), (4, 42), (5, 22), (6, 6)],
    "抑え": [(4, 55), (5, 35), (6, 10)],
}
FOREIGN_SUB_PITCH_MOVEMENT_WEIGHTS = [(1, 25), (2, 45), (3, 30)]
FOREIGN_TWO_SEAM_RATES = {"先発": 0.27, "中継ぎ": 0.46, "抑え": 0.53}
# 第二球種（ツーシーム等）を持たない投手が変化球2球種になる確率。
# 第二球種は変化球1つ分の枠を使うので、第二球種を持つ投手は常に変化球2球種。
FOREIGN_TWO_PITCH_RATES_WITHOUT_SECOND_FASTBALL = {"先発": 0.02, "中継ぎ": 0.26, "抑え": 0.29}
# 選手格ごとの特能補正（青特能の出やすさ, 赤特能の出やすさ, ランク特能を良くする確率, 悪くする確率）
# 外国人の投手・野手で共通。
FOREIGN_CLASS_SPECIAL_SCALES = {
    "大物実績者": (1.40, 0.65, 0.35, 0.00),
    "主力期待級": (1.08, 0.90, 0.12, 0.05),
    "レギュラー競争級": (1.00, 1.00, 0.05, 0.08),
    "保険・バックアップ級": (0.80, 1.15, 0.00, 0.25),
    "育成素材型": (0.80, 1.20, 0.00, 0.20),
    "再生候補": (0.88, 1.15, 0.03, 0.22),
}
# 獲得目的「若手育成」を付けられる上限年齢（投手・野手共通）
FOREIGN_YOUNG_DEVELOPMENT_MAX_AGE = 27
# 実在の外国人選手に1人もいない特能は、大物実績者にだけまれに付ける（特能名, 確率）。
FOREIGN_STAR_ONLY_SPECIALS = {
    "投手": [("対強打者○", 0.10), ("闘志", 0.05), ("重い球", 0.05)],
    "野手": [("対エース○", 0.08), ("野手存在感", 0.05)],
}
# 実在データで同時に持たない組み合わせ
FOREIGN_PITCHER_SPECIAL_CONFLICTS = [
    ("安全圏○", "寸前"), ("根性", "短気"), ("要所○", "寸前"), ("球持ち○", "抜け球"),
    ("乱調", "投手調子安定"), ("尻上がり", "寸前"), ("逃げ球", "寸前"), ("荒れ球", "ストライク先行"),
    ("キレ○", "抜け球"), ("勝ち運", "負け運"), ("ストライク先行", "ボール先行"),
    ("対ランナー", "対ランナー×"), ("投手調子安定", "投手調子極端"),
]
# ランク特能の重み（A〜G）。2026寄りの実在外国人投手の分布に合わせる。
FOREIGN_PITCHER_RANKED_WEIGHTS = {
    "クイック": {"A": 0.2, "B": 0.5, "C": 1.3, "D": 36, "E": 46, "F": 12.5, "G": 3.5},
    "回復": {"A": 4, "B": 14, "C": 24, "D": 51, "E": 5, "F": 1.5, "G": 0.5},
    "ノビ": {"A": 3, "B": 14, "C": 30, "D": 29, "E": 17, "F": 6, "G": 1},
    "打たれ強さ": {"A": 2, "B": 8, "C": 17, "D": 67.7, "E": 4, "F": 1, "G": 0.3},
    "対ピンチ": {"A": 1, "B": 4, "C": 10, "D": 68, "E": 12, "F": 4, "G": 1},
    "対左打者": {"A": 1, "B": 5, "C": 13, "D": 46, "E": 25, "F": 8, "G": 2},
    "対左打者_左投": {"A": 2, "B": 6, "C": 14, "D": 56, "E": 15, "F": 6, "G": 1},
    "ケガしにくさ": {"A": 1, "B": 3, "C": 8, "D": 53, "E": 24, "F": 9, "G": 2},
}
FOREIGN_PITCHER_STARTER_ACQUISITIONS = {"先発候補", "再生候補", "左腕補強", "若手育成"}


def foreign_pitcher_role_name(position: str) -> str:
    return position if position in FOREIGN_PITCHER_SPEED_MEANS else "中継ぎ"


def foreign_pitcher_speed(rng: random.Random, position: str, archetype: str, player_class: str, age: int, weakness_profile: str) -> int:
    """上限で打ち切らず、上側の裾がなだらかに細くなる球速分布。"""
    mean = FOREIGN_PITCHER_SPEED_MEANS[position] + FOREIGN_PITCHER_SPEED_ARCHETYPE.get(archetype, 0.0)
    if player_class == "大物実績者":
        mean += 0.6
    elif player_class in {"保険・バックアップ級", "再生候補"}:
        mean -= 0.8
    if age >= 34:
        mean -= 1.5
    elif age <= 24:
        mean -= 0.5
    if weakness_profile == "球速不足":
        mean -= 2.0
    top = 164 if archetype == "速球" or position == "抑え" else 162
    # 一様な揺らぎを足して、1つの値に集中しない平らな山にする。
    mean += rng.uniform(-2.2, 2.2)
    for _ in range(100):
        z = rng.gauss(0.0, 1.0)
        value = int(round(mean + z * (2.1 if z < 0 else 2.6)))
        # 163km/h以上は実在でも1〜2%なので、さらに間引く。
        if 146 <= value <= top and (value <= 162 or rng.random() < 0.6):
            return value
    return clamp(mean, 146, top)


def foreign_pitcher_control(rng: random.Random, position: str, archetype: str, player_class: str, age: int, weakness_profile: str, speed: int) -> int:
    expected_speed = FOREIGN_PITCHER_SPEED_MEANS[position] + FOREIGN_PITCHER_SPEED_ARCHETYPE.get(archetype, 0.0)
    mean = FOREIGN_PITCHER_CONTROL_MEANS[position] + FOREIGN_PITCHER_CONTROL_ARCHETYPE.get(archetype, 0.0)
    mean += (expected_speed - speed) * 0.25
    mean += {"大物実績者": 3.0, "保険・バックアップ級": -2.0, "再生候補": -1.0}.get(player_class, 0.0)
    if age >= 32:
        mean += 2.0
    if weakness_profile == "低制球":
        mean -= 7.0
    for _ in range(100):
        value = int(round(rng.gauss(mean, 8.5)))
        if 22 <= value <= 85:
            return value
    return clamp(mean, 22, 85)


def foreign_pitcher_stamina(rng: random.Random, position: str, archetype: str, age: int, weakness_profile: str, speed: int, control: int) -> int:
    expected_control = FOREIGN_PITCHER_CONTROL_MEANS[position]
    mean = FOREIGN_PITCHER_STAMINA_MEANS[position]
    mean += (control - expected_control) * 0.08
    if archetype == "スタミナ":
        mean += 5.0 if position == "先発" else 0.0
    if age >= 34:
        mean -= 1.5
    if weakness_profile == "スタミナ不足":
        mean -= 4.0
    if position == "先発":
        low, high, sd_low, sd_high = 44, 80, 5.8, 5.8
    elif position == "中継ぎ" and archetype == "スタミナ":
        # ロングリリーフ枠
        mean, low, high, sd_low, sd_high = 59.0, 55, 63, 2.5, 2.5
    else:
        # 実在の救援は最低38。40未満はごくまれにする。
        low, high, sd_low, sd_high = 38, 60 if position == "中継ぎ" else 58, 3.4, 5.2
    for _ in range(100):
        z = rng.gauss(0.0, 1.0)
        value = int(round(mean + z * (sd_low if z < 0 else sd_high)))
        if low <= value <= high:
            return value
    return clamp(mean, low, high)


def foreign_physique(rng: random.Random, height_mean: float, height_sd: float, height_low: int, height_high: int, bmi_mean: float, bmi_sd: float, bmi_low: float, bmi_high: float) -> tuple[int, int]:
    """外国人の身長と、BMIに連動した体重（投手・野手共通）。"""
    height = truncated_normal_int(rng, height_mean, height_sd, height_low, height_high)
    bmi = max(bmi_low, min(bmi_high, rng.gauss(bmi_mean, bmi_sd)))
    return height, int(round(bmi * (height / 100) ** 2))


def foreign_pitcher_physique(rng: random.Random, nationality: str) -> tuple[int, int]:
    return foreign_physique(rng, FOREIGN_PITCHER_HEIGHT_BY_NATIONALITY.get(nationality, 190.0), 6.5, 178, 210, 27.3, 1.2, 24.5, 30.5)


def foreign_growth_type(rng: random.Random, age: int) -> str:
    """年齢と整合する成長タイプ（外国人の投手・野手共通）。超晩成は26歳以下だけ。"""
    if age <= 24:
        weights = {"very_early": 10, "early": 22, "normal": 40, "late": 20, "very_late": 8}
    elif age <= 26:
        weights = {"very_early": 8, "early": 25, "normal": 45, "late": 17, "very_late": 5}
    elif age <= 29:
        weights = {"very_early": 3, "early": 30, "normal": 49, "late": 18, "very_late": 0}
    else:
        weights = {"very_early": 2, "early": 38, "normal": 52, "late": 8, "very_late": 0}
    return weighted_choice(rng, positive_weight_items(list(weights.items())))


def foreign_pitcher_acquisition_role(rng: random.Random, current: str, position: str, player_class: str, age: int, batting_throwing: str) -> str:
    is_left = batting_throwing.startswith("左投")
    invalid = (
        (position == "先発" and current not in FOREIGN_PITCHER_STARTER_ACQUISITIONS)
        or (current == "若手育成" and age > FOREIGN_YOUNG_DEVELOPMENT_MAX_AGE)
        or (current == "左腕補強" and not is_left)
    )
    if not invalid:
        return current
    if position == "先発":
        candidates = ["先発候補", "再生候補"]
    elif position == "抑え":
        candidates = ["クローザー候補", "勝ちパターン候補", "再生候補"]
    else:
        candidates = ["勝ちパターン候補", "ロングリリーフ", "再生候補"]
    if is_left:
        candidates.append("左腕補強")
    if age <= FOREIGN_YOUNG_DEVELOPMENT_MAX_AGE:
        candidates.append("若手育成")
    items = [(label, PITCHER_ACQUISITION_ROLE_WEIGHTS.get(label, 10) * (2 if player_class == "再生候補" and label == "再生候補" else 1)) for label in candidates]
    return weighted_choice(rng, items)


def foreign_pitcher_breaking_balls(rng: random.Random, position: str, archetype: str, weakness_profile: str, batting_throwing: str) -> list[dict[str, Any]]:
    """外国人らしい「持ち球が少なく、決め球が鋭い」球種構成（2〜3球種）。"""
    # 実在の外国人投手に「変化球3球種＋ストレート系第二球種」はいない（214人中0人）。
    # 第二球種の有無を先に決め、持つ投手は変化球2球種にする。
    two_seam_rate = FOREIGN_TWO_SEAM_RATES[position] + (0.03 if archetype == "制球" else 0.0)
    has_two_seam = rng.random() < two_seam_rate
    two_rate = FOREIGN_TWO_PITCH_RATES_WITHOUT_SECOND_FASTBALL[position] + {"変化球": -0.10, "速球": 0.08, "制球": -0.03}.get(archetype, 0.0)
    count = 2 if has_two_seam or weakness_profile == "球種不足" or rng.random() < max(0.0, two_rate) else 3
    # 既存ルールどおり、ツーシームと同方向の第二球種は同時に持たせない。
    same_direction_factor = 0.0 if has_two_seam else FOREIGN_SAME_DIRECTION_FACTOR
    allowed = {code: allowed_pitch_names_for_generation(code, batting_throwing) for code in DIRECTION_NAMES}
    picked: list[str] = []
    used_codes: set[str] = set()
    for _ in range(count):
        items = []
        for name, weight in FOREIGN_PITCH_WEIGHTS.items():
            code = str(BREAKING_BY_NAME[name]["direction_code"])
            if name in picked or name not in allowed[code]:
                continue
            weight *= same_direction_factor if code in used_codes else 1.0
            if weight > 0:
                items.append((name, weight))
        name = weighted_choice(rng, items)
        picked.append(name)
        used_codes.add(str(BREAKING_BY_NAME[name]["direction_code"]))

    # 方向ごとに最初の球種を主球種、同じ方向の2つ目を第二球種にする。
    primary_names: list[str] = []
    second_names: list[str] = []
    seen_codes: set[str] = set()
    for name in picked:
        code = str(BREAKING_BY_NAME[name]["direction_code"])
        (second_names if code in seen_codes else primary_names).append(name)
        seen_codes.add(code)

    # 変化量3以上を出せない球種（シュートなど）は決め球にしない。
    finisher_names = [name for name in primary_names if int(BREAKING_BY_NAME[name].get("max_movement", 7)) >= 3] or primary_names
    finisher = weighted_choice(rng, [(name, FOREIGN_FINISHER_AFFINITY.get(name, 1.0)) for name in finisher_names])
    finisher_movement = weighted_choice(rng, FOREIGN_FINISHER_MOVEMENT_WEIGHTS[position])
    if archetype == "変化球" and rng.random() < 0.35:
        finisher_movement += 1
    if weakness_profile == "変化量不足" and rng.random() < 0.6:
        finisher_movement -= 1
    finisher_movement = max(3, min(7, finisher_movement))
    balls: list[dict[str, Any]] = []
    for name in primary_names:
        movement = finisher_movement if name == finisher else min(finisher_movement, weighted_choice(rng, FOREIGN_SUB_PITCH_MOVEMENT_WEIGHTS))
        balls.append(make_breaking_ball(name, movement, False, 1))
    primary_by_code = {str(ball["direction_code"]): ball for ball in balls}
    for name in second_names:
        base = primary_by_code[str(BREAKING_BY_NAME[name]["direction_code"])]
        minimum = int(BREAKING_BY_NAME[name].get("min_movement", 1))
        movement = min(pitch_movement(base), weighted_choice(rng, FOREIGN_SUB_PITCH_MOVEMENT_WEIGHTS))
        if minimum <= pitch_movement(base):
            balls.append(make_breaking_ball(name, max(minimum, movement), True, 2))

    if has_two_seam:
        fastball = select_second_fastball_type(rng)
        fastball["name"] = "ムービングファスト" if rng.random() < 0.015 else "ツーシームファスト"
        balls.append(fastball)
    return balls


def foreign_pitcher_special_abilities(
    rng: random.Random,
    master: MasterData,
    position: str,
    archetype: str,
    player_class: str,
    weakness_profile: str,
    speed: int,
    control: int,
    batting_throwing: str,
    pitcher_aptitudes: dict[str, str],
    breaking_balls: list[dict[str, Any]],
) -> list[str]:
    """型・能力と連動した通常特能。実在の外国人投手にない特能はほぼ出さない。"""
    names = {str(ball.get("name")) for ball in breaking_balls}
    directions = {str(ball.get("direction_code")) for ball in breaking_balls if ball.get("kind") == "breaking"}
    has_two_seam = "ツーシームファスト" in names
    is_left = batting_throwing.startswith("左投")
    can_start = pitcher_aptitudes.get("starter_aptitude") in PITCHER_APTITUDE_ALLOWED
    can_relieve = has_pitcher_aptitude(pitcher_aptitudes, {"reliever_aptitude", "closer_aptitude"})

    if speed <= 151:
        strikeout = 0.08
    elif speed <= 153:
        strikeout = 0.18
    elif speed <= 156:
        strikeout = 0.50
    elif speed <= 159:
        strikeout = 0.60
    else:
        strikeout = 0.76
    if control <= 35:
        walk = 0.90
    elif control <= 40:
        walk = 0.82
    elif control <= 50:
        walk = 0.50
    elif control <= 60:
        walk = 0.20
    else:
        walk = 0.08
    # (特能名, 確率, 選手格補正を掛けるか)
    candidates: list[tuple[str, float, bool]] = [
        ("奪三振", strikeout + (0.05 if archetype == "速球" else 0.0), False),
        ("四球", walk, False),
        ("球速安定", 0.40, True),
        ("逃げ球", 0.26, True),
        ("一発", 0.15, True),
        ("荒れ球", 0.28 if control <= 45 else 0.11, False),
        ("キレ○", 0.15, True),
        ("抜け球", 0.16, True),
        ("真っスラ", 0.15, True),
        ("ナチュラルシュート", 0.03, True),
        ("フライボールピッチャー", 0.20 if speed >= 157 and not has_two_seam else 0.10, False),
        ("ゴロピッチャー", 0.18 if has_two_seam or "4" in directions else 0.05, False),
        ("対ランナー", 0.15, True),
        ("緩急○", 0.14 if "2" in directions or names & {"チェンジアップ", "サークルチェンジ"} else 0.05, True),
        ("速球中心", 0.16 if speed >= 158 else 0.08, False),
        ("変化球中心", 0.27 if archetype == "変化球" else 0.13, False),
        ("投手調子極端", 0.15 if weakness_profile == "安定性不安" else 0.065, False),
        ("投手調子安定", 0.02, False),
        ("投球位置左", 0.002, False),
        ("投球位置右", 0.002, False),
        ("リリース○", 0.13, True),
        ("球持ち○", 0.08, True),
        ("低め○", 0.10, True),
        ("クロスファイヤー", 0.12 if is_left else 0.0, True),
        ("牽制○", 0.10, True),
        ("打球反応○", 0.10, True),
        ("テンポ○", 0.09, False),
        ("スロースターター", 0.10 if can_start else 0.0, True),
        ("力配分", 0.06 if can_start else 0.0, True),
        ("回またぎ○", 0.08 if can_relieve else 0.0, True),
        ("負け運", 0.04, True),
        ("内角攻め", 0.015, True),
        ("乱調", 0.015, True),
        ("寸前", 0.015, True),
        ("要所○", 0.012, True),
        ("緊急登板○", 0.015 if can_relieve else 0.0, True),
        ("ストライク先行", 0.007, True),
        ("火消し", 0.007 if can_relieve else 0.0, True),
    ]
    return select_foreign_specials(
        rng, master, "投手", player_class, candidates, FOREIGN_PITCHER_SPECIAL_CONFLICTS,
        ("球速安定", "キレ○", "対ランナー", "リリース○", "低め○"),
    )


def select_foreign_specials(
    rng: random.Random,
    master: MasterData,
    role: str,
    player_class: str,
    candidates: list[tuple[str, float, bool]],
    conflicts: list[tuple[str, str]],
    fillers: tuple[str, ...],
    is_allowed: Any = None,
) -> list[str]:
    """外国人の通常特能を候補（特能名, 確率, 選手格補正を掛けるか）から抽選する（投手・野手共通）。

    実在の外国人選手にいない特能は候補に入れず、大物実績者にだけ FOREIGN_STAR_ONLY_SPECIALS を足す。
    同じグループ（g始まり）の特能と矛盾ペアは同時に持たせない。
    """
    blue_scale, red_scale, _, _ = FOREIGN_CLASS_SPECIAL_SCALES.get(player_class, (1.0, 1.0, 0.0, 0.0))
    allowed = role_allowed_specials(master, role)
    group_of = {str(row["name"]): str(row.get("group", "")) for row in master.abilities}
    kind_of = {str(row["name"]): str(row.get("kind", "")) for row in master.abilities}
    candidates = list(candidates)
    if player_class == "大物実績者":
        candidates += [(name, chance, False) for name, chance in FOREIGN_STAR_ONLY_SPECIALS.get(role, [])]

    selected: list[str] = []
    used_groups: set[str] = set()
    for name, chance, scaled in candidates:
        if name not in allowed or chance <= 0 or (is_allowed is not None and not is_allowed(name)):
            continue
        if scaled:
            chance *= red_scale if kind_of.get(name) == "red" else blue_scale
        if rng.random() >= min(0.95, chance):
            continue
        group = group_of.get(name, name)
        if group.startswith("g") and group in used_groups:
            continue
        if any((name == a and b in selected) or (name == b and a in selected) for a, b in conflicts):
            continue
        selected.append(name)
        used_groups.add(group)

    # 既存の選手格ごとの特能数の上下限に収める（候補の後ろほど出現率の低い特能なので後ろから削る）。
    low, high = special_count_bounds("助っ人外国人用", player_class)
    while sum(is_countable_special(name) for name in selected) > high:
        drop = next(name for name in reversed(selected) if is_countable_special(name))
        selected.remove(drop)
    for name in fillers:
        if sum(is_countable_special(item) for item in selected) >= low:
            break
        group = group_of.get(name, name)
        if name in allowed and name not in selected and not (group.startswith("g") and group in used_groups):
            if is_allowed is None or is_allowed(name):
                selected.append(name)
                used_groups.add(group)
    return selected


def foreign_class_rank_shift(rng: random.Random, player_class: str) -> int:
    """選手格によるランク特能の補正（+1で1段良く、-1で1段悪く）。投手・野手共通。"""
    _, _, up_rate, down_rate = FOREIGN_CLASS_SPECIAL_SCALES.get(player_class, (1.0, 1.0, 0.0, 0.0))
    shift = 0
    if rng.random() < up_rate:
        shift += 1
    if rng.random() < down_rate:
        shift -= 1
    return shift


def ranked_special_names_by_group(master: MasterData) -> dict[str, dict[str, str]]:
    names_by_group: dict[str, dict[str, str]] = {}
    for row in master.abilities:
        name = str(row.get("name", ""))
        if re.search(r"[A-G]$", name):
            names_by_group.setdefault(ranked_special_base_name(name), {})[name[-1]] = name
    return names_by_group


def foreign_pitcher_ranked_specials(
    rng: random.Random,
    master: MasterData,
    current: dict[str, str],
    player_class: str,
    speed: int,
    batting_throwing: str,
) -> dict[str, str]:
    names_by_group = ranked_special_names_by_group(master)
    result = dict(current)
    for group in current:
        key = f"{group}_左投" if group == "対左打者" and batting_throwing.startswith("左投") else group
        weights = FOREIGN_PITCHER_RANKED_WEIGHTS.get(key)
        names = names_by_group.get(group, {})
        if not weights or not set(RANKED_SPECIAL_RANKS).issubset(names):
            continue
        rank_value = weighted_choice(rng, list(weights.items()))
        shift = foreign_class_rank_shift(rng, player_class) if group != "クイック" else 0
        if group == "ノビ":
            if speed >= 159 and rng.random() < 0.4:
                shift += 1
            elif speed <= 151 and rng.random() < 0.4:
                shift -= 1
        result[group] = names[shifted_rank(rank_value, shift)]
    return result


def apply_foreign_pitcher_balance(player: dict[str, Any], seed: int, master: MasterData) -> dict[str, Any]:
    """助っ人外国人投手を実在の外国人投手の傾向（能力・体格・球種・特能）に合わせて再調整する。"""
    rng = make_sub_rng(seed, FOREIGN_PITCHER_BALANCE_NAMESPACE)
    position = foreign_pitcher_role_name(str(player.get("position", "")))
    archetype = str(player.get("archetype", "")) or "総合"
    player_class = str(player.get("player_class", ""))
    weakness_profile = str(player.get("weakness_profile", ""))
    age = int(player.get("age", 28))
    pitcher_aptitudes = {key: str(player.get(key, "-")) for key in PITCHER_APTITUDE_KEYS}

    batting_throwing = str(player.get("batting_throwing", ""))
    if batting_throwing.startswith("左投") and rng.random() < FOREIGN_PITCHER_LEFT_TO_RIGHT_RATE:
        batting_throwing = "右投" + batting_throwing[2:]
    player["batting_throwing"] = batting_throwing
    player["handedness"] = handedness_from_batting_throwing(batting_throwing)

    speed = foreign_pitcher_speed(rng, position, archetype, player_class, age, weakness_profile)
    control = foreign_pitcher_control(rng, position, archetype, player_class, age, weakness_profile, speed)
    stamina = foreign_pitcher_stamina(rng, position, archetype, age, weakness_profile, speed, control)
    abilities = dict(player.get("abilities", {}))
    set_pitcher_speed(abilities, speed)
    abilities["コントロール"] = ability(control)
    abilities["スタミナ"] = ability(stamina)
    abilities["肩力"] = ability(clamp(speed - 81 + weighted_choice(rng, [(-1, 15), (0, 35), (1, 35), (2, 15)]), 49, 82))

    height, weight = foreign_pitcher_physique(rng, str(player.get("nationality", "")))
    player.update({"height": height, "weight": weight, "height_cm": height, "weight_kg": weight})
    form_type, form_number, form_generic = generate_form(rng, PITCHING_FORM_RANGES, FOREIGN_PITCHING_FORM_WEIGHTS, PITCHING_FORM_GENERIC_RATE["助っ人外国人用"])
    player.update({"pitching_form_type": form_type, "pitching_form_number": form_number, "pitching_form_is_generic": form_generic})

    breaking_balls = foreign_pitcher_breaking_balls(rng, position, archetype, weakness_profile, batting_throwing)
    player["breaking_balls"] = breaking_balls
    player["special_abilities"] = foreign_pitcher_special_abilities(
        rng, master, position, archetype, player_class, weakness_profile, speed, control,
        batting_throwing, pitcher_aptitudes, breaking_balls,
    )
    abilities["ranked_specials"] = foreign_pitcher_ranked_specials(
        rng, master, dict(abilities.get("ranked_specials", {}) or {}), player_class, speed, batting_throwing,
    )
    player["abilities"] = abilities

    player["acquisition_role"] = foreign_pitcher_acquisition_role(rng, str(player.get("acquisition_role", "")), position, player_class, age, batting_throwing)
    growth_type = foreign_growth_type(rng, age)
    player["growth_type"] = growth_type
    player["growth_type_label"] = growth_type_label(growth_type)
    return player


# ---------------------------------------------------------------------------
# 助っ人外国人野手の実在準拠バランス
# 基準: パワプロ2022〜2026 デフォルト選手データの外国人野手（延べ151人）。
# 投手と同じく、既存処理で作った選手を名前空間付きサブRNGで再調整する。
# 若手育成の年齢・成長タイプ・選手格の補正・実在にない特能の扱いは投手と共通の仕組みを使う。
# ---------------------------------------------------------------------------
FOREIGN_FIELDER_BALANCE_NAMESPACE = "foreign_fielder_balance_v1"
# ポジションの割合（実在5年）
FOREIGN_FIELDER_POSITION_TARGETS = {"外野手": 42.0, "一塁手": 28.0, "三塁手": 11.5, "遊撃手": 9.5, "二塁手": 5.0, "捕手": 3.0}
# アーキタイプごとのポジションの向き不向き（全体の割合は FOREIGN_FIELDER_POSITION_TARGETS に合わせる）
FOREIGN_FIELDER_POSITION_AFFINITY = {
    "長打": {"外野手": 1.0, "一塁手": 1.35, "三塁手": 1.1, "遊撃手": 0.3, "二塁手": 0.5, "捕手": 0.9},
    "巧打": {"外野手": 1.0, "一塁手": 1.0, "三塁手": 1.0, "遊撃手": 1.0, "二塁手": 1.2, "捕手": 1.0},
    "俊足": {"外野手": 1.3, "一塁手": 0.3, "三塁手": 0.7, "遊撃手": 1.8, "二塁手": 1.8, "捕手": 0.3},
    "守備": {"外野手": 0.8, "一塁手": 0.6, "三塁手": 1.3, "遊撃手": 2.2, "二塁手": 1.8, "捕手": 1.8},
    "強肩": {"外野手": 1.1, "一塁手": 0.5, "三塁手": 1.3, "遊撃手": 1.4, "二塁手": 0.8, "捕手": 1.8},
    "バランス": {"外野手": 1.0, "一塁手": 1.0, "三塁手": 1.0, "遊撃手": 1.0, "二塁手": 1.0, "捕手": 1.0},
}
# ポジション別の基準値（ミート, パワー, 走力, 肩力, 守備力）。実在外国人野手の平均を元に、
# アーキタイプの偏り（遊撃手・二塁手は守備型が多い）を差し引いて、生成後の平均が実在に近づく値にしている。
FOREIGN_FIELDER_POSITION_PROFILES = {
    "一塁手": (45.5, 71.5, 42.0, 64.0, 47.0),
    "三塁手": (41.0, 70.0, 52.0, 70.0, 49.0),
    "二塁手": (42.0, 66.0, 70.0, 68.0, 49.0),
    "遊撃手": (38.0, 56.0, 72.0, 77.0, 52.5),
    "外野手": (45.0, 71.0, 61.0, 66.0, 42.0),
    "捕手": (45.0, 67.0, 46.0, 79.0, 44.0),
}
# アーキタイプごとの補正（ミート, パワー, 走力, 肩力, 守備力）
FOREIGN_FIELDER_ARCHETYPE_SHIFTS = {
    "長打": (0.0, 4.0, -2.0, 0.0, -1.0),
    "巧打": (5.0, -1.5, 0.0, 0.0, 0.0),
    "俊足": (0.0, -3.0, 8.0, 0.0, 1.0),
    "守備": (-1.5, -2.5, 1.0, 1.0, 5.0),
    "強肩": (0.0, 0.0, 0.0, 7.0, 1.0),
    "バランス": (0.0, 0.0, 0.0, 0.0, 0.0),
}
# 選手格ごとの打撃（ミート・パワー）の補正。守備・走力・肩にはほとんど掛けない。
FOREIGN_FIELDER_CLASS_BATTING = {
    "大物実績者": 6.0, "主力期待級": 2.0, "レギュラー競争級": 0.0,
    "保険・バックアップ級": -4.0, "育成素材型": -4.0, "再生候補": -2.5,
}
FOREIGN_FIELDER_CLASS_DEFENSE = {
    "大物実績者": 1.0, "主力期待級": 0.5, "レギュラー競争級": 0.0,
    "保険・バックアップ級": -1.0, "育成素材型": -1.0, "再生候補": -1.0,
}
FOREIGN_FIELDER_HEIGHT_BY_NATIONALITY = {
    "アメリカ": 189.5, "ドミニカ共和国": 187.5, "ベネズエラ": 186.0, "キューバ": 187.5,
    "メキシコ": 185.0, "韓国": 183.0, "台湾": 181.0,
}
FOREIGN_FIELDER_HEIGHT_BY_POSITION = {"一塁手": 1.5, "三塁手": 0.0, "外野手": 0.0, "捕手": -1.0, "二塁手": -4.0, "遊撃手": -3.0}
# 投打（左投げは一塁手・外野手だけ。全体で約8%）
FOREIGN_FIELDER_LEFT_THROW_RATE = 0.115
FOREIGN_FIELDER_BAT_SIDE_WEIGHTS = {
    "右投": [("右打", 77.5), ("左打", 13.0), ("両打", 9.5)],
    "左投": [("左打", 90.0), ("右打", 10.0)],
}
# サブポジの数（ポジション別）と組み合わせ（実在の件数）
FOREIGN_FIELDER_SUB_POSITION_COUNT_WEIGHTS = {
    "外野手": [(0, 62), (1, 26), (2, 12)],
    "一塁手": [(0, 28), (1, 37), (2, 35)],
    "三塁手": [(0, 10), (1, 24), (2, 66)],
    "遊撃手": [(0, 4), (1, 12), (2, 84)],
    "二塁手": [(0, 3), (1, 7), (2, 90)],
    "捕手": [(0, 10), (1, 20), (2, 70)],
}
FOREIGN_FIELDER_SUB_POSITION_WEIGHTS = {
    "一塁手": {"外野手": 23, "三塁手": 18, "二塁手": 6},
    "三塁手": {"一塁手": 15, "外野手": 10},
    "外野手": {"一塁手": 25, "三塁手": 7},
    "遊撃手": {"二塁手": 12, "三塁手": 10, "外野手": 5},
    "二塁手": {"三塁手": 6, "外野手": 5, "遊撃手": 3},
    "捕手": {"一塁手": 4, "外野手": 4},
}
# 実在データで同時に持たない組み合わせ（同じグループの特能は別途除外される）
FOREIGN_FIELDER_SPECIAL_CONFLICTS = [
    ("野手調子安定", "野手調子極端"), ("積極打法", "慎重打法"), ("積極盗塁", "慎重盗塁"),
    ("パワーヒッター", "ラインドライブ"), ("プルヒッター", "広角打法"), ("三振", "粘り打ち"),
]
# ランク特能の重み（A〜G）。実在外国人野手（回復・盗塁は2026寄り）の分布に合わせる。
FOREIGN_FIELDER_RANKED_WEIGHTS = {
    "走塁": {"A": 1, "B": 5, "C": 16, "D": 74, "E": 3, "F": 0.8, "G": 0.2},
    "送球": {"A": 0.2, "B": 1.3, "C": 5.5, "D": 39, "E": 45, "F": 8, "G": 1},
    "盗塁": {"A": 0.3, "B": 1.5, "C": 4.2, "D": 62, "E": 23, "F": 7, "G": 2},
    "対左投手": {"A": 3, "B": 9, "C": 22, "D": 33, "E": 22, "F": 9, "G": 2},
    "チャンス": {"A": 1.5, "B": 6, "C": 16, "D": 59, "E": 11, "F": 5, "G": 1.5},
    "ケガしにくさ": {"A": 0.2, "B": 0.8, "C": 2.5, "D": 64, "E": 22, "F": 8, "G": 2.5},
    "回復": {"A": 1.5, "B": 6.5, "C": 15, "D": 57, "E": 14, "F": 5, "G": 1},
    "キャッチャー": {"A": 1, "B": 4, "C": 20, "D": 50, "E": 20, "F": 4, "G": 1},
}
# 選手格の補正を掛けないランク特能（走力・肩で決まる項目）
FOREIGN_FIELDER_PHYSICAL_RANKED = {"走塁", "送球", "盗塁"}


@lru_cache(maxsize=1)
def foreign_fielder_position_weights_by_archetype() -> dict[str, list[tuple[str, float]]]:
    """アーキタイプ別のポジション重み。全体の割合が目標どおりになるよう反復で補正する。"""
    archetype_share = dict(FOREIGN_ARCHETYPE_WEIGHTS["野手"])
    total = sum(archetype_share.values())
    archetype_share = {key: value / total for key, value in archetype_share.items()}
    target_total = sum(FOREIGN_FIELDER_POSITION_TARGETS.values())
    targets = {pos: value / target_total for pos, value in FOREIGN_FIELDER_POSITION_TARGETS.items()}
    factors = {pos: 1.0 for pos in targets}

    def conditional(archetype: str) -> dict[str, float]:
        raw = {pos: targets[pos] * factors[pos] * FOREIGN_FIELDER_POSITION_AFFINITY[archetype][pos] for pos in targets}
        norm = sum(raw.values())
        return {pos: value / norm for pos, value in raw.items()}

    for _ in range(200):
        marginal = {pos: 0.0 for pos in targets}
        for archetype, share in archetype_share.items():
            for pos, value in conditional(archetype).items():
                marginal[pos] += share * value
        for pos in targets:
            factors[pos] *= targets[pos] / marginal[pos]
    return {archetype: list(conditional(archetype).items()) for archetype in archetype_share}


def foreign_fielder_split_normal(rng: random.Random, mean: float, sd_low: float, sd_high: float, low: int, high: int) -> int:
    """下側と上側でばらつきの違う正規分布を、範囲外は引き直して整数で返す。"""
    for _ in range(100):
        z = rng.gauss(0.0, 1.0)
        value = int(round(mean + z * (sd_low if z < 0 else sd_high)))
        if low <= value <= high:
            return value
    return clamp(mean, low, high)


def foreign_fielder_batting_throwing(rng: random.Random, position: str) -> str:
    throwing = "左投" if position in {"一塁手", "外野手"} and rng.random() < FOREIGN_FIELDER_LEFT_THROW_RATE else "右投"
    return throwing + weighted_choice(rng, FOREIGN_FIELDER_BAT_SIDE_WEIGHTS[throwing])


def foreign_fielder_abilities(
    rng: random.Random,
    position: str,
    archetype: str,
    player_class: str,
    weakness_profile: str,
    age: int,
    height: int,
) -> dict[str, Any]:
    """ポジション別の平均を中心に、実在並みの幅に収めた基本能力と弾道。"""
    base_contact, base_power, base_speed, base_arm, base_fielding = FOREIGN_FIELDER_POSITION_PROFILES[position]
    shift_contact, shift_power, shift_speed, shift_arm, shift_fielding = FOREIGN_FIELDER_ARCHETYPE_SHIFTS.get(archetype, (0.0,) * 5)
    batting = FOREIGN_FIELDER_CLASS_BATTING.get(player_class, 0.0)
    defense = FOREIGN_FIELDER_CLASS_DEFENSE.get(player_class, 0.0)
    # 「打てる外国人はミートもパワーもある」ように、打撃の共通因子を両方に入れる。
    hitting = rng.gauss(0.0, 1.0)

    power_mean = base_power + shift_power + batting * 0.8 + hitting * 3.4 + (height - 187.5) * 0.12
    if age <= 24:
        power_mean -= 2.0
    power = foreign_fielder_split_normal(rng, power_mean, 6.4, 4.4, 38, 88)
    # 走力・肩・守備は、ミートと共通の打撃因子を除いたパワーの高さで下げる（ミートと守備・肩は無相関に近い）。
    power_dev = power - base_power - batting * 0.8 - hitting * 3.4

    contact_mean = base_contact + shift_contact + batting + hitting * 4.2
    if weakness_profile == "低ミート":
        contact_mean -= 6.0
    contact = foreign_fielder_split_normal(rng, contact_mean, 7.5, 8.2, 20, 70)

    speed_mean = base_speed + shift_speed - 0.35 * power_dev
    if weakness_profile == "低走力":
        speed_mean -= 8.0
    if age >= 33:
        speed_mean -= 4.0
    elif age <= 25:
        speed_mean += 2.0
    speed = foreign_fielder_split_normal(rng, speed_mean, 9.0, 10.5, 25, 90)

    arm = foreign_fielder_split_normal(rng, base_arm + shift_arm - 0.18 * power_dev, 11.0, 7.5, 35, 95)

    fielding_mean = base_fielding + 1.5 + shift_fielding + defense - 0.22 * power_dev
    if weakness_profile == "低守備":
        fielding_mean -= 6.0
    if age >= 34:
        fielding_mean -= 2.0
    # 守備職人でも守備力は55〜60程度まで。60以上はごく一部。
    fielding = foreign_fielder_split_normal(rng, fielding_mean, 8.0, 3.4, 25, 65)

    catching_mean = 46.5 + 0.6 * (fielding - 47) + defense
    if weakness_profile == "低捕球":
        catching_mean -= 7.0
    catching = foreign_fielder_split_normal(rng, catching_mean, 6.5, 7.0, 25, 70)

    # 弾道はパワーを基準にしつつ、確率で上下にずれる（パワー87で弾道2の実在例もある）。
    trajectory_score = power + {"長打": 3.0, "巧打": -3.0}.get(archetype, 0.0) + rng.gauss(0.0, 16.0)
    trajectory = 2 if trajectory_score < 59.5 else 3 if trajectory_score < 83.2 else 4
    return {
        "弾道": trajectory, "ミート": ability(contact), "パワー": ability(power), "走力": ability(speed),
        "肩力": ability(arm), "守備力": ability(fielding), "捕球": ability(catching),
    }


def foreign_fielder_sub_positions(rng: random.Random, position: str, batting_throwing: str, fielding: int) -> list[dict[str, str]]:
    """実在の組み合わせに沿ったサブポジ（最大2つ）。左投げは一塁手・外野手だけ。"""
    count = weighted_choice(rng, FOREIGN_FIELDER_SUB_POSITION_COUNT_WEIGHTS[position])
    candidates = [
        (pos, weight) for pos, weight in FOREIGN_FIELDER_SUB_POSITION_WEIGHTS[position].items()
        if not (batting_throwing.startswith("左投") and pos not in {"一塁手", "外野手"})
    ]
    selected: list[dict[str, str]] = []
    while candidates and len(selected) < count:
        pos = weighted_choice(rng, candidates)
        candidates = [(p, w) for p, w in candidates if p != pos]
        if pos == "一塁手":
            aptitude = weighted_choice(rng, [("◎", 5), ("○", 55), ("△", 40)])
        else:
            aptitude = weighted_choice(rng, [("◎", 3 if fielding >= 55 else 0), ("○", 35), ("△", 62)])
        selected.append({"position": pos, "aptitude": aptitude})
    return selected


def foreign_fielder_acquisition_role(rng: random.Random, current: str, position: str, player_class: str, age: int) -> str:
    candidates = list(FIELDER_ACQUISITION_ROLES_BY_POSITION.get(position, ["保険要員"]))
    if player_class == "育成素材型" and "若手育成" not in candidates:
        candidates.append("若手育成")
    if age > FOREIGN_YOUNG_DEVELOPMENT_MAX_AGE:
        candidates = [label for label in candidates if label != "若手育成"]
    if current in candidates:
        return current
    items = [(label, 40 if player_class == "保険・バックアップ級" and label == "保険要員" else 20) for label in candidates]
    return weighted_choice(rng, items)


def foreign_fielder_special_abilities(
    rng: random.Random,
    master: MasterData,
    position: str,
    archetype: str,
    player_class: str,
    weakness_profile: str,
    abilities: dict[str, Any],
    sub_positions: list[dict[str, str]],
) -> list[str]:
    """外国人野手らしい特能（三振・積極打法・併殺・満塁男など）。実在にない特能はほぼ出さない。"""
    contact = ability_numeric_value(abilities, "ミート") or 0
    power = ability_numeric_value(abilities, "パワー") or 0
    speed = ability_numeric_value(abilities, "走力") or 0
    arm = ability_numeric_value(abilities, "肩力") or 0
    fielding = ability_numeric_value(abilities, "守備力") or 0
    # 三振はほぼ全員に付く前提で、ミートが高い選手だけ少し外す。
    strikeout = 0.90 if contact <= 35 else 0.76 if contact <= 45 else 0.62 if contact <= 55 else 0.50
    slugger = power >= 76
    candidates: list[tuple[str, float, bool]] = [
        ("三振", strikeout, False),
        ("積極打法", 0.44, False),
        ("慎重打法", 0.27, False),
        ("併殺", 0.48 if speed <= 45 else 0.33 if speed <= 60 else 0.18, False),
        ("満塁男", 0.34, True),
        ("強振多用", 0.33 if power >= 70 else 0.22, False),
        ("サヨナラ男", 0.27, True),
        ("固め打ち", 0.31, True),
        ("広角打法", 0.30 if archetype == "巧打" or contact >= 55 else 0.15, True),
        ("プルヒッター", 0.26, True),
        ("選球眼", 0.21, False),
        ("決勝打", 0.22, True),
        ("積極走塁", 0.32 if speed >= 60 else 0.14, False),
        ("積極守備", 0.17, False),
        ("死球集中", 0.16, False),
        ("エラー", 0.32 if fielding <= 40 else 0.17 if fielding <= 50 else 0.08, False),
        ("初球○", 0.16, True),
        ("マルチ弾", 0.42 if slugger else 0.075, True),
        # 実在のパワーヒッターは3.3%（マルチ弾15%）なので、パワー連動は残して重みを1/4にする。
        ("パワーヒッター", 0.105 if slugger else 0.019, True),
        ("アベレージヒッター", 0.15 if contact >= 55 else 0.03, True),
        ("ラインドライブ", 0.05, True),
        ("流し打ち", 0.06, True),
        ("悪球打ち", 0.05, False),
        ("カット打ち", 0.03, True),
        ("ダメ押し", 0.05, True),
        ("逆境○", 0.04, True),
        ("意外性", 0.04, True),
        ("対ストレート○", 0.06, True),
        ("対変化球○", 0.05, True),
        ("ハイボールヒッター", 0.05, True),
        ("ローボールヒッター", 0.04, True),
        ("インコースヒッター", 0.05, True),
        ("アウトコースヒッター", 0.04, True),
        ("内野安打○", 0.08 if speed >= 70 else 0.01, True),
        ("ヘッドスライディング", 0.02, True),
        ("守備職人", 0.10 if fielding >= 55 else 0.0, True),
        ("レーザービーム", 0.20 if arm >= 75 else 0.03, True),
        ("高速チャージ", 0.05, True),
        ("ブロッキング", 0.10, True),
        ("ホーム死守", 0.05, True),
        ("フレーミング○", 0.08, True),
        ("積極盗塁", 0.10 if speed >= 70 else 0.02, False),
        ("慎重盗塁", 0.02, False),
        ("粘り打ち", 0.05, True),
        ("バント○", 0.01, True),
        ("野手調子極端", 0.12 if weakness_profile == "明確な弱点なし" and player_class == "再生候補" else 0.05, False),
        # 実在の外国人野手に調子安定は5年間で0人。
        ("野手調子安定", 0.004, False),
    ]
    return select_foreign_specials(
        rng, master, "野手", player_class, candidates, FOREIGN_FIELDER_SPECIAL_CONFLICTS,
        ("選球眼", "初球○", "固め打ち", "満塁男"),
        is_allowed=lambda name: is_special_allowed_for_player(name, "野手", position, sub_positions),
    )


def foreign_fielder_ranked_specials(
    rng: random.Random,
    master: MasterData,
    current: dict[str, str],
    position: str,
    player_class: str,
    weakness_profile: str,
    abilities: dict[str, Any],
    sub_positions: list[dict[str, str]],
) -> dict[str, str]:
    names_by_group = ranked_special_names_by_group(master)
    speed = ability_numeric_value(abilities, "走力") or 0
    arm = ability_numeric_value(abilities, "肩力") or 0
    groups = [group for group in current if group != "キャッチャー"]
    if has_position_aptitude(position, sub_positions, {"捕手"}):
        groups.append("キャッチャー")
    result: dict[str, str] = {}
    for group in groups:
        weights = FOREIGN_FIELDER_RANKED_WEIGHTS.get(group)
        names = names_by_group.get(group, {})
        if not weights or not set(RANKED_SPECIAL_RANKS).issubset(names):
            if group in current:
                result[group] = current[group]
            continue
        rank_value = weighted_choice(rng, list(weights.items()))
        shift = 0 if group in FOREIGN_FIELDER_PHYSICAL_RANKED else foreign_class_rank_shift(rng, player_class)
        if group == "走塁" and speed >= 75 and rng.random() < 0.30:
            shift += 1
        elif group == "盗塁":
            if speed >= 75 and rng.random() < 0.35:
                shift += 1
            elif speed <= 45 and rng.random() < 0.35:
                shift -= 1
        elif group == "送球":
            if weakness_profile == "送球不安":
                shift -= 1
            elif arm >= 85 and rng.random() < 0.25:
                shift += 1
        result[group] = names[shifted_rank(rank_value, shift)]
    return result


def apply_foreign_fielder_balance(player: dict[str, Any], seed: int, master: MasterData) -> dict[str, Any]:
    """助っ人外国人野手を実在の外国人野手の傾向（能力の幅・弾道・ポジション・投打・体格・特能）に合わせて再調整する。"""
    rng = make_sub_rng(seed, FOREIGN_FIELDER_BALANCE_NAMESPACE)
    archetype = str(player.get("archetype", "")) or "バランス"
    player_class = str(player.get("player_class", ""))
    weakness_profile = str(player.get("weakness_profile", ""))
    age = int(player.get("age", 28))

    weights = dict(foreign_fielder_position_weights_by_archetype()).get(archetype) or list(FOREIGN_FIELDER_POSITION_TARGETS.items())
    position = weighted_choice(rng, weights)
    if position != player.get("position"):
        player["position"] = position
        player["position_style"] = choose_position_style(rng, "野手", position, archetype) or FIELDER_STYLE_DEFAULTS.get(position, "")
    batting_throwing = foreign_fielder_batting_throwing(rng, position)
    player["batting_throwing"] = batting_throwing
    player["handedness"] = handedness_from_batting_throwing(batting_throwing)
    player["acquisition_role"] = foreign_fielder_acquisition_role(rng, str(player.get("acquisition_role", "")), position, player_class, age)

    height_mean = FOREIGN_FIELDER_HEIGHT_BY_NATIONALITY.get(str(player.get("nationality", "")), 187.5) + FOREIGN_FIELDER_HEIGHT_BY_POSITION.get(position, 0.0)
    height, weight = foreign_physique(rng, height_mean, 6.0, 172, 205, 28.5, 1.6, 25.0, 32.5)
    player.update({"height": height, "weight": weight, "height_cm": height, "weight_kg": weight})

    old_abilities = dict(player.get("abilities", {}))
    abilities = {**old_abilities, **foreign_fielder_abilities(rng, position, archetype, player_class, weakness_profile, age, height)}
    sub_positions = foreign_fielder_sub_positions(rng, position, batting_throwing, ability_numeric_value(abilities, "守備力") or 0)
    player["sub_positions"] = sub_positions
    player["special_abilities"] = foreign_fielder_special_abilities(
        rng, master, position, archetype, player_class, weakness_profile, abilities, sub_positions,
    )
    abilities["ranked_specials"] = foreign_fielder_ranked_specials(
        rng, master, dict(old_abilities.get("ranked_specials", {}) or {}), position, player_class, weakness_profile, abilities, sub_positions,
    )
    player["abilities"] = abilities

    growth_type = foreign_growth_type(rng, age)
    player["growth_type"] = growth_type
    player["growth_type_label"] = growth_type_label(growth_type)
    return player


# ---------------------------------------------------------------------------
# 架空球団（日本人）の実在準拠バランス
# 基準: パワプロ2022〜2026 デフォルト選手データの日本人（延べ 投手1878人／野手1867人）。
# 平均値はほぼ実在どおりなので、既存処理で作った選手を名前空間付きサブRNGで部分的に直す。
# （能力の裾と相関・抑え・チェンジアップ系・特能と能力の連動・ランク特能・サブポジ・体格）
# ---------------------------------------------------------------------------
FICTIONAL_PITCHER_BALANCE_NAMESPACE = "fictional_pitcher_balance_v1"
FICTIONAL_FIELDER_BALANCE_NAMESPACE = "fictional_fielder_balance_v1"
# 投手の役割ごとの補正（球速, コントロール, スタミナ）。抑えは守護神格なので球速を上げる。
FICTIONAL_PITCHER_ROLE_SHIFTS = {
    "先発": (0.0, 1.5, -3.5),
    "中継ぎ": (0.3, 0.0, 2.0),
    "中継ぎ_抑え◎": (2.5, 0.0, 2.0),
    "抑え": (4.5, 0.0, 0.0),
}
FICTIONAL_PITCHER_SPEED_CENTER = 151.0
FICTIONAL_PITCHER_CONTROL_CENTER = 50.0
# 速球派ほど制球が荒い（球速1km/hあたりのコントロール）、制球の良い投手ほどスタミナがある。
FICTIONAL_CONTROL_PER_SPEED = -0.75
FICTIONAL_STAMINA_PER_CONTROL = 0.12
FICTIONAL_STAMINA_PER_SPEED = -0.06
# 抑え（守護神格）の決め球の変化量
FICTIONAL_CLOSER_FINISHER_MOVEMENT_WEIGHTS = [(4, 50), (5, 38), (6, 12)]
# チェンジアップ系は左投手の球種。右投手は同じ方向の別球種に替える（名前, 確率, 替える先の候補）。
FICTIONAL_RIGHT_PITCH_SWAPS = [
    ("サークルチェンジ", 0.42, [("Hシンカー", 1)]),
    ("チェンジアップ", 0.55, [("フォーク", 1), ("SFF", 1)]),
    ("ファストチェンジ", 0.70, [("Hシンカー", 1)]),
    ("ナックル", 1.00, [("フォーク", 1)]),
]
FICTIONAL_LEFT_PITCH_SWAPS = [
    ("ファストチェンジ", 0.85, [("サークルチェンジ", 1)]),
    ("シンキングスプリット", 0.35, [("サークルチェンジ", 6), ("スクリュー", 4)]),
    ("シュート", 0.80, [("シンキングツーシーム", 1)]),
    ("Hシュート", 0.70, [("シンキングツーシーム", 1)]),
    ("ナックル", 1.00, [("フォーク", 1)]),
]
# チェンジアップ系を持たない左投手は、フォーク方向の球種をチェンジアップに替える。
FICTIONAL_LEFT_CHANGEUP_FROM = {"フォーク": 0.35, "SFF": 0.35, "Vスライダー": 0.25, "パーム": 0.5}
FICTIONAL_CHANGEUP_NAMES = {"サークルチェンジ", "チェンジアップ"}
# 球種数を少し3球種寄りに（実在の2球種は27%）、ストレート系第二球種を8%前後にする。
FICTIONAL_SECOND_FASTBALL_DROP_RATE = 0.28
FICTIONAL_THIRD_PITCH_ADD_RATE = 0.19
FICTIONAL_ADDED_PITCH_MOVEMENT_WEIGHTS = [(1, 30), (2, 40), (3, 30)]
# 3球種目を足すときの球種の重み補正（左右でチェンジアップ系の出やすさが違う）
FICTIONAL_ADDED_PITCH_HAND_FACTORS = {
    "右投": {"サークルチェンジ": 0.4, "チェンジアップ": 0.4, "ファストチェンジ": 0.2, "シンキングスプリット": 0.6, "ナックル": 0.0},
    "左投": {"サークルチェンジ": 2.0, "チェンジアップ": 2.0, "シンキングツーシーム": 2.0, "スクリュー": 1.5, "ファストチェンジ": 0.2, "ナックル": 0.0},
}

# 実在の日本人（2022〜2026）に1人もいない特能。出さない。
FICTIONAL_NOT_REAL_SPECIALS = {
    "投手": {"安全圏○", "重い球", "立ち上がり○", "闘志", "対強打者○", "ボール先行", "人気者", "対ランナー×", "短気", "根性"},
    # フル出場は実在では起用法の欄にだけ出る項目なので、特殊能力としては出さない。
    "野手": {"人気者", "窮地○", "チームプレイ×", "ムード○", "帳尻合わせ", "リベンジ", "ささやき破り", "フル出場"},
}
# 能力と連動させる特能: (特能名, 能力, 帯の上限のリスト, 帯ごとの保有率)。
# 実在（5年）の保有率。既存の抽選結果は使わず、この確率で付け直す。
FICTIONAL_LINKED_SPECIALS = {
    "投手": [
        ("奪三振", "球速", [147, 151, 155], [0.09, 0.18, 0.30, 0.60]),
        ("四球", "コントロール", [40, 50, 60], [0.60, 0.35, 0.22, 0.12]),
        ("荒れ球", "コントロール", [40, 50, 60], [0.25, 0.12, 0.02, 0.02]),
        ("球速安定", "球速", [147, 151, 155], [0.26, 0.22, 0.30, 0.33]),
        ("キレ○", "コントロール", [40, 50, 60], [0.07, 0.14, 0.13, 0.24]),
    ],
    "野手": [
        # 特能数の上限で削られる分（約2ポイント）を見込んで、ミート30以下は実在（32%）より少し高くする。
        ("三振", "ミート", [30, 40, 50], [0.34, 0.38, 0.37, 0.16]),
        ("固め打ち", "ミート", [30, 40, 50], [0.01, 0.05, 0.18, 0.51]),
        ("選球眼", "ミート", [30, 40, 50], [0.09, 0.13, 0.26, 0.33]),
        ("広角打法", "ミート", [40, 50], [0.01, 0.07, 0.12]),
        ("積極盗塁", "走力", [60, 70, 80], [0.01, 0.08, 0.24, 0.41]),
        ("内野安打○", "走力", [70, 80], [0.05, 0.31, 0.63]),
        ("併殺", "走力", [50, 60, 70], [0.30, 0.19, 0.15, 0.07]),
        ("パワーヒッター", "パワー", [70, 80], [0.003, 0.04, 0.53]),
        ("エラー", "守備力", [40, 50, 60], [0.06, 0.12, 0.15, 0.15]),
    ],
}
# 出現率を実在に寄せる特能: (特能名, 既存処理での保有率, 目標の保有率)。
# 既存処理の保有率は架空球団の日本人3000人ずつで測った値。
FICTIONAL_SPECIAL_RATE_TARGETS = {
    "投手": [
        ("一発", 0.035, 0.121), ("変化球中心", 0.068, 0.141), ("フライボールピッチャー", 0.021, 0.071),
        ("ゴロピッチャー", 0.029, 0.060), ("スロースターター", 0.049, 0.109), ("緊急登板○", 0.065, 0.093),
        ("回またぎ○", 0.087, 0.097), ("力配分", 0.009, 0.042), ("ポーカーフェイス", 0.012, 0.050),
        ("低め○", 0.085, 0.020), ("緩急○", 0.176, 0.147), ("火消し", 0.036, 0.003),
        ("ジャイロボール", 0.021, 0.002), ("国際大会○", 0.018, 0.003), ("抜け球", 0.172, 0.27),
        ("投手調子極端", 0.012, 0.095), ("投手調子安定", 0.030, 0.036),
        ("投球位置左", 0.030, 0.006), ("投球位置右", 0.029, 0.016),
    ],
    "野手": [
        ("死球集中", 0.014, 0.080), ("バント○", 0.106, 0.147), ("積極走塁", 0.119, 0.169),
        ("積極打法", 0.109, 0.171), ("積極守備", 0.109, 0.163), ("プルヒッター", 0.041, 0.071),
        ("悪球打ち", 0.013, 0.041), ("ホーム死守", 0.012, 0.034), ("決勝打", 0.220, 0.099),
        ("ヘッドスライディング", 0.191, 0.097), ("カット打ち", 0.152, 0.078), ("国際大会○", 0.051, 0.007),
        ("ミート多用", 0.104, 0.080), ("野手調子安定", 0.090, 0.003),
    ],
}
# 実在データで同時に持たない組み合わせ（同じグループの特能は別途除外される）
FICTIONAL_SPECIAL_CONFLICTS = [("荒れ球", "ストライク先行"), ("キレ○", "抜け球"), ("球持ち○", "抜け球")]
# ランク特能の重み（A〜G）。実在（5年）の良い側・悪い側の割合に合わせ、A と G はごく少なくする。
FICTIONAL_PITCHER_RANKED_WEIGHTS = {
    "回復": {"A": 0.3, "B": 6, "C": 20.7, "D": 35, "E": 31, "F": 6.5, "G": 0.5},
    "打たれ強さ": {"A": 0.4, "B": 7, "C": 22.6, "D": 55, "E": 12, "F": 2.8, "G": 0.2},
    "対左打者": {"A": 0.2, "B": 3, "C": 11.8, "D": 45, "E": 32, "F": 7.7, "G": 0.3},
    "対左打者_左投": {"A": 0.5, "B": 6, "C": 21.5, "D": 51, "E": 17, "F": 3.8, "G": 0.2},
    "ケガしにくさ": {"A": 0.1, "B": 1.4, "C": 5.5, "D": 56, "E": 30, "F": 6.7, "G": 0.3},
    "対ピンチ": {"A": 0.3, "B": 3.2, "C": 11.5, "D": 67, "E": 14.5, "F": 3.3, "G": 0.2},
    "クイック": {"A": 0.3, "B": 3.2, "C": 12.5, "D": 68, "E": 13, "F": 2.8, "G": 0.2},
    "ノビ": {"A": 0.5, "B": 8, "C": 26.5, "D": 44, "E": 17, "F": 3.8, "G": 0.2},
    "送球": {"A": 0.1, "B": 1.5, "C": 6.4, "D": 48, "E": 39, "F": 4.8, "G": 0.2},
}
FICTIONAL_FIELDER_RANKED_WEIGHTS = {
    "走塁": {"A": 1.0, "B": 10, "C": 32, "D": 55, "E": 1.6, "F": 0.3, "G": 0.1},
    "盗塁": {"A": 0.3, "B": 3, "C": 11.7, "D": 62, "E": 18, "F": 4.8, "G": 0.2},
    "チャンス": {"A": 0.5, "B": 5, "C": 17.5, "D": 61, "E": 12.5, "F": 3.3, "G": 0.2},
    "送球": {"A": 0.4, "B": 5.5, "C": 20, "D": 37, "E": 30, "F": 6.9, "G": 0.2},
    "回復": {"A": 0.2, "B": 2.5, "C": 10.3, "D": 24, "E": 52, "F": 10.7, "G": 0.3},
    "対左投手": {"A": 0.4, "B": 5, "C": 17.6, "D": 49, "E": 22, "F": 5.8, "G": 0.2},
    "ケガしにくさ": {"A": 0.1, "B": 1.5, "C": 6.4, "D": 65, "E": 22, "F": 4.8, "G": 0.2},
    "キャッチャー": {"A": 0.1, "B": 0.5, "C": 1.4, "D": 88, "E": 8.5, "F": 1.4, "G": 0.1},
}
# 選手格によるランク特能の補正（1段良くする確率, 1段悪くする確率）。能力で決まる項目には掛けない。
FICTIONAL_CLASS_RANK_SHIFTS = {
    "スター級": (0.30, 0.0), "一軍主力級": (0.12, 0.02), "一軍控え級": (0.03, 0.05),
    "二軍級": (0.0, 0.10), "若手素材型": (0.0, 0.10), "ベテラン型": (0.08, 0.05),
}
FICTIONAL_PHYSICAL_RANKED = {"走塁", "盗塁", "送球", "クイック", "ノビ"}

# 野手の基本能力（ミート, パワー, 走力, 肩力, 守備力, 捕球）。
# 既存処理の平均・標準偏差（架空球団の日本人3000人で測定）を、実在（5年）の平均・標準偏差と相関に写す。
FICTIONAL_FIELDER_ABILITY_KEYS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
FICTIONAL_FIELDER_CURRENT_MEANS = (41.3, 52.8, 64.1, 67.1, 50.2, 47.6)
FICTIONAL_FIELDER_CURRENT_SDS = (12.2, 13.8, 13.0, 9.0, 9.7, 8.7)
FICTIONAL_FIELDER_TARGET_MEANS = (40.5, 52.6, 64.2, 66.0, 51.0, 48.7)
FICTIONAL_FIELDER_TARGET_SDS = (11.0, 11.2, 14.3, 10.9, 11.8, 11.2)
# 相関の変換行列（標準化した値に掛ける）。R_target^(1/2) · R_current^(-1/2) で求めた。
# 目標の相関: ミート×パワー +0.35、ミート×走力 +0.18、パワー×走力 −0.22、パワー×守備力 −0.05、
# 走力×守備力 +0.34、ミート×肩力 −0.13（ほかは既存のまま）。
FICTIONAL_FIELDER_CORRELATION_TRANSFORM = (
    (0.963, 0.112, 0.093, -0.023, -0.011, 0.020),
    (0.082, 1.018, 0.078, 0.000, 0.080, -0.064),
    (0.051, 0.091, 1.003, -0.003, 0.122, -0.076),
    (-0.018, 0.003, 0.002, 0.998, -0.001, 0.005),
    (-0.025, 0.093, 0.108, -0.008, 0.985, 0.016),
    (0.012, -0.028, -0.030, 0.004, 0.008, 0.990),
)
# ポジションごとの補正（ミート, パワー, 走力, 肩力, 守備力, 捕球）
FICTIONAL_FIELDER_POSITION_SHIFTS = {
    "外野手": (0.0, 0.0, 0.0, 0.0, 0.5, 0.0),
    "一塁手": (0.0, 0.0, 0.0, 0.0, 3.0, 0.0),
    "三塁手": (0.0, 0.0, 0.0, 0.0, 3.0, 0.0),
    "遊撃手": (-4.5, 0.0, 0.0, 0.0, 0.0, 0.0),
}
# 弾道はパワーに揺らぎを足したスコアで決める（実在の弾道×パワー相関0.72、弾道1は2%強、弾道4は9%強）。
FICTIONAL_TRAJECTORY_NOISE_SD = 8.0
FICTIONAL_TRAJECTORY_THRESHOLDS = (26.0, 49.8, 71.2)
FICTIONAL_TRAJECTORY_ONE_MAX_POWER = 38
# サブポジの保有率（メイン → サブ）。実在（2022〜2025）の守備力表から数えた値。
FICTIONAL_SUB_POSITION_RATES = {
    "遊撃手": {"二塁手": 0.91, "三塁手": 0.90, "一塁手": 0.40, "外野手": 0.37},
    "二塁手": {"三塁手": 0.84, "遊撃手": 0.78, "外野手": 0.63, "一塁手": 0.59},
    "三塁手": {"一塁手": 0.87, "外野手": 0.57, "二塁手": 0.54, "遊撃手": 0.36},
    "一塁手": {"三塁手": 0.80, "外野手": 0.58, "二塁手": 0.37, "遊撃手": 0.13, "捕手": 0.10},
    "捕手": {"一塁手": 0.39, "外野手": 0.21, "三塁手": 0.17, "二塁手": 0.05, "遊撃手": 0.02},
    "外野手": {"一塁手": 0.29, "三塁手": 0.14, "二塁手": 0.10, "遊撃手": 0.05},
}
# サブポジの適性（◎, ○, △）の重み。サクセス新規作成と同じく ◎100%・○80%・△70% の守備力になる。
FICTIONAL_SUB_POSITION_APTITUDE_WEIGHTS = {
    ("遊撃手", "二塁手"): (57, 25, 18), ("遊撃手", "三塁手"): (44, 26, 30), ("遊撃手", "一塁手"): (45, 20, 35),
    ("二塁手", "三塁手"): (39, 26, 35), ("二塁手", "遊撃手"): (30, 30, 40), ("二塁手", "一塁手"): (45, 20, 35),
    ("三塁手", "一塁手"): (60, 15, 25), ("三塁手", "二塁手"): (41, 24, 35), ("三塁手", "遊撃手"): (20, 30, 50),
    ("一塁手", "三塁手"): (30, 25, 45), ("一塁手", "二塁手"): (15, 25, 60), ("一塁手", "遊撃手"): (10, 20, 70),
    ("一塁手", "外野手"): (35, 20, 45),
    ("外野手", "一塁手"): (20, 18, 62), ("外野手", "三塁手"): (8, 16, 76), ("外野手", "二塁手"): (8, 16, 76),
    ("外野手", "遊撃手"): (5, 15, 80),
    ("捕手", "一塁手"): (20, 17, 63), ("捕手", "外野手"): (15, 20, 65), ("捕手", "三塁手"): (8, 16, 76),
    ("捕手", "二塁手"): (5, 15, 80), ("捕手", "遊撃手"): (5, 15, 80),
}
FICTIONAL_SUB_TO_OUTFIELD_APTITUDE_WEIGHTS = (31, 20, 49)
FICTIONAL_SUB_TO_CATCHER_APTITUDE_WEIGHTS = (3, 12, 85)
FICTIONAL_SUB_INFIELD_APTITUDE_WEIGHTS = (40, 25, 35)


def fictional_band_rate(value: float, limits: list[int], rates: list[float]) -> float:
    for limit, rate in zip(limits, rates):
        if value <= limit:
            return rate
    return rates[-1]


def compress_tail(value: float, pivot: float, factor: float, upper: bool) -> float:
    """pivot より外側（upper=True なら上側）の値を pivot から factor 倍の距離にする（1未満で縮め、1超で伸ばす）。"""
    if (value > pivot) if upper else (value < pivot):
        return pivot + (value - pivot) * factor
    return value


def fictional_set_special(selected: list[str], name: str, present: bool, group_of: dict[str, str], force: bool, is_allowed: Any) -> None:
    """特能の有無を切り替える。force=True なら同じグループ・矛盾ペアの特能を外してでも付ける。"""
    if not present:
        if name in selected:
            selected.remove(name)
        return
    if name in selected or not is_allowed(name):
        return
    group = group_of.get(name, name)
    rivals = [
        item for item in selected
        if (group.startswith("g") and group_of.get(item) == group)
        or any({item, name} == {a, b} for a, b in FICTIONAL_SPECIAL_CONFLICTS)
    ]
    if rivals and not force:
        return
    for item in rivals:
        selected.remove(item)
    selected.append(name)


# 選手格ごとの特能数の下限に届かないときに足す特能（実在で多い順）
FICTIONAL_SPECIAL_FILLERS = {
    "投手": ("球速安定", "リリース○", "球持ち○", "キレ○", "逃げ球"),
    "野手": ("選球眼", "サヨナラ男", "満塁男", "流し打ち", "初球○"),
}


def fictional_adjust_specials(rng: random.Random, master: MasterData, role: str, player_class: str, specials: list[str], values: dict[str, float], is_allowed: Any) -> list[str]:
    """実在にない特能を外し、能力と連動する特能を付け直し、出現率を実在に寄せる（投手・野手共通）。"""
    allowed_names = role_allowed_specials(master, role)
    group_of = {str(row["name"]): str(row.get("group", "")) for row in master.abilities}
    selected = [name for name in specials if name not in FICTIONAL_NOT_REAL_SPECIALS[role]]
    check = lambda name: name in allowed_names and is_allowed(name)
    for name, key, limits, rates in FICTIONAL_LINKED_SPECIALS[role]:
        present = rng.random() < fictional_band_rate(values.get(key, 0), limits, rates)
        fictional_set_special(selected, name, present, group_of, True, check)
    for name, current, target in FICTIONAL_SPECIAL_RATE_TARGETS[role]:
        if name in selected:
            if target < current and rng.random() >= target / current:
                selected.remove(name)
        elif target > current and rng.random() < (target - current) / (1.0 - current):
            fictional_set_special(selected, name, True, group_of, False, check)
    # サブポジの付け替えなどで位置・起用の条件を満たさなくなった特能を外す。
    selected = [name for name in selected if is_allowed(name)]
    # 既存の選手格ごとの特能数の上下限に収める。能力と連動する特能は残し、後ろ（後から足した特能）から削る。
    low, high = special_count_bounds("架空球団用", player_class)
    linked = {name for name, *_ in FICTIONAL_LINKED_SPECIALS[role]}
    countable = lambda: sum(is_countable_special(name) for name in selected)
    while countable() > high:
        removable = [name for name in selected if is_countable_special(name)]
        selected.remove(next((name for name in reversed(removable) if name not in linked), removable[-1]))
    for name in FICTIONAL_SPECIAL_FILLERS[role]:
        if countable() >= low:
            break
        fictional_set_special(selected, name, True, group_of, False, check)
    return selected


def fictional_ranked_specials(
    rng: random.Random,
    master: MasterData,
    groups: list[str],
    weights_by_group: dict[str, dict[str, float]],
    player_class: str,
    current: dict[str, str],
    link_shift: Any,
    weights_key: Any = None,
) -> dict[str, str]:
    """ランク特能を実在の分布から引き直す。能力・選手格による補正では A・G を新たに作らない。"""
    names_by_group = ranked_special_names_by_group(master)
    up_rate, down_rate = FICTIONAL_CLASS_RANK_SHIFTS.get(player_class, (0.0, 0.0))
    result: dict[str, str] = {}
    for group in groups:
        weights = weights_by_group.get(weights_key(group) if weights_key else group) or weights_by_group.get(group)
        names = names_by_group.get(group, {})
        if not weights or not set(RANKED_SPECIAL_RANKS).issubset(names):
            if group in current:
                result[group] = current[group]
            continue
        base = weighted_choice(rng, list(weights.items()))
        shift = link_shift(group)
        if group not in FICTIONAL_PHYSICAL_RANKED:
            shift += int(rng.random() < up_rate) - int(rng.random() < down_rate)
        value = shifted_rank(base, shift)
        if base not in {"A", "G"}:
            value = {"A": "B", "G": "F"}.get(value, value)
        result[group] = names[value]
    return result


def fictional_pitcher_breaking_balls(rng: random.Random, breaking_balls: list[dict[str, Any]], batting_throwing: str, position: str) -> list[dict[str, Any]]:
    """チェンジアップ系を左投手に寄せ、抑え（守護神格）の決め球を鋭くする。方向の構成は変えない。"""
    balls = [dict(ball) for ball in breaking_balls]
    is_left = batting_throwing.startswith("左投")
    if any(ball.get("kind") == "second_fastball" for ball in balls) and rng.random() < FICTIONAL_SECOND_FASTBALL_DROP_RATE:
        balls = [ball for ball in balls if ball.get("kind") != "second_fastball"]
    breaking = [ball for ball in balls if ball.get("kind") == "breaking"]
    if len(breaking) == 2 and rng.random() < FICTIONAL_THIRD_PITCH_ADD_RATE:
        used_codes = {str(ball.get("direction_code")) for ball in breaking}
        code = weighted_choice(rng, [(code, weight) for code, weight in DIRECTION_SELECTION_WEIGHTS.items() if code not in used_codes])
        factors = FICTIONAL_ADDED_PITCH_HAND_FACTORS["左投" if is_left else "右投"]
        items = [
            (name, BREAKING_BY_NAME[name]["base_weight"] * factors.get(name, 1.0))
            for name in sorted(allowed_pitch_names_for_generation(code, batting_throwing))
        ]
        name = weighted_choice(rng, [(name, weight) for name, weight in items if weight > 0])
        top = max(int(ball.get("movement") or 1) for ball in breaking)
        movement = min(top, weighted_choice(rng, FICTIONAL_ADDED_PITCH_MOVEMENT_WEIGHTS))
        balls.insert(len(breaking), make_breaking_ball(name, movement, False, 1))

    def rename(ball: dict[str, Any], new_name: str) -> None:
        if any(other.get("name") == new_name for other in balls):
            return
        master = BREAKING_BY_NAME[new_name]
        ball["name"] = new_name
        movement = max(int(master.get("min_movement", 1)), min(int(master.get("max_movement", 7)), int(ball.get("movement") or 1)))
        ball["movement"] = ball["level"] = movement

    for name, chance, targets in (FICTIONAL_LEFT_PITCH_SWAPS if is_left else FICTIONAL_RIGHT_PITCH_SWAPS):
        for ball in balls:
            if ball.get("kind") == "breaking" and ball.get("name") == name and rng.random() < chance:
                rename(ball, weighted_choice(rng, targets))
    if is_left and not any(ball.get("name") in FICTIONAL_CHANGEUP_NAMES for ball in balls):
        for ball in balls:
            chance = FICTIONAL_LEFT_CHANGEUP_FROM.get(str(ball.get("name")), 0.0)
            if ball.get("kind") == "breaking" and rng.random() < chance:
                rename(ball, "チェンジアップ")
                break

    if position == "抑え":
        primaries = [
            ball for ball in balls
            if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")
            and int(BREAKING_BY_NAME[str(ball["name"])].get("max_movement", 7)) >= 4
        ]
        if primaries:
            finisher = max(primaries, key=lambda ball: int(ball.get("movement") or 0))
            target = min(weighted_choice(rng, FICTIONAL_CLOSER_FINISHER_MOVEMENT_WEIGHTS), int(BREAKING_BY_NAME[str(finisher["name"])].get("max_movement", 7)))
            if target > int(finisher.get("movement") or 0):
                finisher["movement"] = finisher["level"] = target
    enforce_second_pitch_movement_order(balls)
    return balls


def fictional_adjust_physique(rng: random.Random, player: dict[str, Any], role: str) -> None:
    """日本人の身長を実在に合わせて1〜2cm下げ、体重も連動して下げる（平均 投手181・野手179）。"""
    height_drop = (2 if rng.random() < 0.7 else 1) if role == "投手" else 1
    weight_drop = 2 if rng.random() < 0.5 else 1
    height = int(player.get("height_cm") or player.get("height") or 0) - height_drop
    weight = int(player.get("weight_kg") or player.get("weight") or 0) - weight_drop
    player.update({"height": height, "weight": weight, "height_cm": height, "weight_kg": weight})


def apply_fictional_pitcher_balance(player: dict[str, Any], seed: int, master: MasterData) -> dict[str, Any]:
    """架空球団の日本人投手を、実在12球団の日本人投手の傾向に合わせて部分的に直す。"""
    rng = make_sub_rng(seed, FICTIONAL_PITCHER_BALANCE_NAMESPACE)
    position = str(player.get("position", ""))
    pitcher_aptitudes = {key: str(player.get(key, "-")) for key in PITCHER_APTITUDE_KEYS}
    batting_throwing = str(player.get("batting_throwing", ""))
    abilities = dict(player.get("abilities", {}))

    role_key = "中継ぎ_抑え◎" if position == "中継ぎ" and pitcher_aptitudes.get("closer_aptitude") == "◎" else position
    speed_shift, control_shift, stamina_shift = FICTIONAL_PITCHER_ROLE_SHIFTS.get(role_key, (0.0, 0.0, 0.0))
    speed = float(pitcher_speed_value(abilities) or 150) + speed_shift
    # 球速の裾（145以下・162以上）を細くする。既存処理は165km/hに張り付いた投手が多いので上側を強めに縮める。
    speed = round(compress_tail(compress_tail(speed, 148.0, 0.6, upper=False), 155.0, 0.5, upper=True))
    control = float(ability_numeric_value(abilities, "コントロール") or 50) + control_shift
    control += FICTIONAL_CONTROL_PER_SPEED * (speed - FICTIONAL_PITCHER_SPEED_CENTER)
    control = clamp(round(compress_tail(control, 35.0, 0.7, upper=False)), 15, 95)
    stamina = float(ability_numeric_value(abilities, "スタミナ") or 50) + stamina_shift
    stamina += FICTIONAL_STAMINA_PER_CONTROL * (control - FICTIONAL_PITCHER_CONTROL_CENTER)
    stamina += FICTIONAL_STAMINA_PER_SPEED * (speed - FICTIONAL_PITCHER_SPEED_CENTER)
    stamina = clamp(round(stamina), 15, 100)
    set_pitcher_speed(abilities, speed)
    abilities["コントロール"] = ability(control)
    abilities["スタミナ"] = ability(stamina)
    abilities["肩力"] = ability(clamp(speed - 81 + weighted_choice(rng, [(-1, 15), (0, 35), (1, 35), (2, 15)]), 49, 82))

    player["breaking_balls"] = fictional_pitcher_breaking_balls(rng, list(player.get("breaking_balls", [])), batting_throwing, position)
    player["special_abilities"] = fictional_adjust_specials(
        rng, master, "投手", str(player.get("player_class", "")), list(player.get("special_abilities", [])),
        {"球速": speed, "コントロール": control},
        lambda name: is_special_allowed_for_player(name, "投手", position, [], pitcher_aptitudes),
    )

    def link_shift(group: str) -> int:
        if group == "ノビ":
            return int(speed >= 155 and rng.random() < 0.35) - int(speed <= 146 and rng.random() < 0.35)
        return 0

    current = dict(abilities.get("ranked_specials", {}) or {})
    abilities["ranked_specials"] = fictional_ranked_specials(
        rng, master, list(current), FICTIONAL_PITCHER_RANKED_WEIGHTS, str(player.get("player_class", "")), current, link_shift,
        weights_key=lambda group: f"{group}_左投" if group == "対左打者" and batting_throwing.startswith("左投") else group,
    )
    player["abilities"] = abilities
    fictional_adjust_physique(rng, player, "投手")
    return player


def fictional_fielder_abilities(rng: random.Random, abilities: dict[str, Any], position: str) -> dict[str, Any]:
    """能力の平均・幅・相関を実在に写し、弾道をパワーから確率的に決め直す。"""
    z = [
        ((ability_numeric_value(abilities, key) or mean) - mean) / sd
        for key, mean, sd in zip(FICTIONAL_FIELDER_ABILITY_KEYS, FICTIONAL_FIELDER_CURRENT_MEANS, FICTIONAL_FIELDER_CURRENT_SDS)
    ]
    shifts = FICTIONAL_FIELDER_POSITION_SHIFTS.get(position, (0.0,) * 6)
    values: dict[str, float] = {}
    for key, row, mean, sd, shift in zip(FICTIONAL_FIELDER_ABILITY_KEYS, FICTIONAL_FIELDER_CORRELATION_TRANSFORM, FICTIONAL_FIELDER_TARGET_MEANS, FICTIONAL_FIELDER_TARGET_SDS, shifts):
        values[key] = mean + sd * sum(weight * item for weight, item in zip(row, z)) + shift
    # 実在は走力・守備力の上側が厚く、守備力の下側が薄い。
    values["走力"] = compress_tail(values["走力"], 70.0, 1.25, upper=True)
    values["守備力"] = compress_tail(compress_tail(values["守備力"], 55.0, 1.15, upper=True), 34.0, 0.5, upper=False)
    result = dict(abilities)
    for key in FICTIONAL_FIELDER_ABILITY_KEYS:
        result[key] = ability(clamp(round(values[key]), 1, 100))
    power = result["パワー"]["value"]
    score = power + rng.gauss(0.0, FICTIONAL_TRAJECTORY_NOISE_SD)
    trajectory = 1 + sum(score >= threshold for threshold in FICTIONAL_TRAJECTORY_THRESHOLDS)
    if trajectory == 1 and power > FICTIONAL_TRAJECTORY_ONE_MAX_POWER:
        trajectory = 2
    result["弾道"] = trajectory
    return result


def fictional_fielder_sub_positions(rng: random.Random, position: str, batting_throwing: str) -> list[dict[str, str]]:
    """実在の組み合わせごとの保有率でサブポジを決める（二遊間・三塁手は3つ持ちが普通）。"""
    selected: list[dict[str, str]] = []
    for sub, rate in FICTIONAL_SUB_POSITION_RATES.get(position, {}).items():
        if batting_throwing.startswith("左投") and sub not in {"一塁手", "外野手"}:
            continue
        if rng.random() >= rate:
            continue
        if sub == "外野手":
            weights = FICTIONAL_SUB_POSITION_APTITUDE_WEIGHTS.get((position, sub), FICTIONAL_SUB_TO_OUTFIELD_APTITUDE_WEIGHTS)
        elif sub == "捕手":
            weights = FICTIONAL_SUB_TO_CATCHER_APTITUDE_WEIGHTS
        else:
            weights = FICTIONAL_SUB_POSITION_APTITUDE_WEIGHTS.get((position, sub), FICTIONAL_SUB_INFIELD_APTITUDE_WEIGHTS)
        selected.append({"position": sub, "aptitude": weighted_choice(rng, list(zip(("◎", "○", "△"), weights)))})
    return selected


def apply_fictional_fielder_balance(player: dict[str, Any], seed: int, master: MasterData) -> dict[str, Any]:
    """架空球団の日本人野手を、実在12球団の日本人野手の傾向に合わせて部分的に直す。"""
    rng = make_sub_rng(seed, FICTIONAL_FIELDER_BALANCE_NAMESPACE)
    position = str(player.get("position", ""))
    batting_throwing = str(player.get("batting_throwing", ""))
    old_abilities = dict(player.get("abilities", {}))
    abilities = fictional_fielder_abilities(rng, old_abilities, position)
    sub_positions = fictional_fielder_sub_positions(rng, position, batting_throwing)
    player["sub_positions"] = sub_positions
    values = {key: float(abilities[key]["value"]) for key in FICTIONAL_FIELDER_ABILITY_KEYS}
    player["special_abilities"] = fictional_adjust_specials(
        rng, master, "野手", str(player.get("player_class", "")), list(player.get("special_abilities", [])), values,
        lambda name: is_special_allowed_for_player(name, "野手", position, sub_positions),
    )
    speed, arm = values["走力"], values["肩力"]

    def link_shift(group: str) -> int:
        if group == "走塁":
            return int(speed >= 80 and rng.random() < 0.5) - int(speed <= 50 and rng.random() < 0.4)
        if group == "盗塁":
            return int(speed >= 80 and rng.random() < 0.6) - int(speed <= 50 and rng.random() < 0.5)
        if group == "送球":
            return int(arm >= 80 and rng.random() < 0.4) - int(arm <= 55 and rng.random() < 0.4)
        return 0

    current = dict(old_abilities.get("ranked_specials", {}) or {})
    groups = [group for group in current if group != "キャッチャー"]
    if has_position_aptitude(position, sub_positions, {"捕手"}):
        groups.append("キャッチャー")
    abilities["ranked_specials"] = fictional_ranked_specials(
        rng, master, groups, FICTIONAL_FIELDER_RANKED_WEIGHTS, str(player.get("player_class", "")), current, link_shift,
    )
    player["abilities"] = abilities
    fictional_adjust_physique(rng, player, "野手")
    return player


# ---------------------------------------------------------------------------
# ドラフト候補の実在準拠バランス
# 基準: パワプロ2022〜2026 の実在選手のプロ1年目（支配下指名の日本人 投手167人／野手139人）。
# 既存処理で作った候補を名前空間付きサブRNGで部分的に直す。入団経路ごとに平均と幅を写し、
# 既存の値の大小（選手格による差）はそのまま残す。育成候補にも同じ変換をかける。
# ---------------------------------------------------------------------------
DRAFT_PITCHER_BALANCE_NAMESPACE = "draft_pitcher_balance_v1"
DRAFT_FIELDER_BALANCE_NAMESPACE = "draft_fielder_balance_v1"
# アマチュアは遊撃手が多い（プロで他の内野にまわる）。一塁手は少ない。
DRAFT_FIELDER_POSITION_WEIGHTS = [("捕手", 14), ("一塁手", 7), ("二塁手", 9), ("三塁手", 13), ("遊撃手", 26), ("外野手", 31)]


def draft_route_group(route: str) -> str:
    """独立・クラブ／その他は実在の人数が少ないので、大卒と社会人の中間として扱う。"""
    return route if route in {"高卒", "大卒", "社会人"} else "その他"


# 投手の能力の写し方: 経路ごとに（既存処理の平均, 目標の平均, 幅の倍率）。
# 既存処理の平均は育成候補を除くドラフト候補（投手1617人）で測った値。
DRAFT_PITCHER_SPEED_MAPS = {
    "高卒": (145.8, 150.5, 0.62), "大卒": (147.5, 152.9, 0.80),
    "社会人": (147.8, 152.3, 0.90), "その他": (147.4, 152.5, 0.85),
}
# 選手格ごとの球速の補正。既存処理は中位・下位・育成候補の差が小さいので広げる
# （大卒の目安: 超上位155、上位154、中位153、下位151、育成候補147〜148）。
DRAFT_PITCHER_CLASS_SPEED_SHIFTS = {"中位候補": -0.3, "下位候補": -0.9, "育成候補": -4.5}
DRAFT_PITCHER_CONTROL_MAPS = {
    "高卒": (35.7, 41.0, 0.72), "大卒": (45.0, 47.5, 1.05),
    "社会人": (48.9, 50.5, 1.05), "その他": (45.0, 48.5, 1.05),
}
# スタミナは幅を大きく絞る（高卒の実在は10〜90%タイルで34〜45、大卒・社会人の最高は68）。4つ目は上限。
DRAFT_PITCHER_STAMINA_MAPS = {
    "高卒": (37.5, 40.0, 0.42, 56), "大卒": (50.1, 51.0, 0.60, 70),
    "社会人": (52.5, 52.0, 0.60, 70), "その他": (50.8, 51.5, 0.60, 70),
}
# 変化球: 2球種の投手に3球種目を足す確率（高卒は3球種60%前後、全体は2球種28%前後）
DRAFT_THIRD_PITCH_ADD_RATES = {"高卒": 0.40, "大卒": 0.35, "社会人": 0.15, "その他": 0.10}
DRAFT_ADDED_PITCH_MOVEMENT_WEIGHTS = {
    "高卒": [(1, 50), (2, 42), (3, 8)],
    "その他": [(1, 30), (2, 45), (3, 25)],
}
# 高卒の変化量の上限（実在の1年目の高卒は最大変化量4以上が0%）
DRAFT_HIGH_SCHOOL_MAX_MOVEMENT = 3
# 大卒・社会人は決め球を1段階下げる。変化量4の球は一部だけ下げる（最大変化量4以上を20〜25%に）。
DRAFT_MOVEMENT4_DROP_RATE = 0.84
# 大卒・社会人の決め球以外の球（変化量2以上）も一部下げる（総変化量の平均を実在の6.1前後に）。
DRAFT_SUB_MOVEMENT_DROP_RATE = 0.4

# 実在データの特殊能力欄にない項目（緑特能・起用法）。特能の数を数えるときに除く。
DRAFT_UNCOUNTED_SPECIALS = {
    "積極打法", "積極走塁", "選球眼", "積極守備", "変化球中心", "慎重打法", "積極盗塁", "速球中心",
    "強振多用", "ミート多用", "チームプレイ○", "テンポ○",
    "おまかせ", "調子次第", "慎重盗塁", "ビハインドでも", "代打要員", "スタミナ限界", "接戦時",
    "リード時", "中継ぎエース", "代走要員", "勝利投手", "守備要員", "守護神", "完投",
    "左のワンポイント", "フル出場", "セーブ狙い",
}
# 実在の1年目でほとんど見ない特能の残す確率
DRAFT_SPECIAL_KEEP_RATES = {
    "投手": {"真っスラ": 0.45, "要所○": 0.45, "乱調": 0.45, "安全圏○": 0.40, "重い球": 0.40, "立ち上がり○": 0.40, "勝ち運": 0.40},
    "野手": {},
}
# 能力と連動させる特能: (特能名, 能力, 帯の上限のリスト, 帯ごとの保有率)。既存の抽選結果は使わず付け直す。
DRAFT_LINKED_SPECIALS = {
    "投手": [
        ("四球", "コントロール", [35, 45, 55], [0.55, 0.35, 0.22, 0.10]),
        ("荒れ球", "コントロール", [35, 45, 55], [0.25, 0.12, 0.05, 0.02]),
        ("奪三振", "球速", [149, 152, 155], [0.06, 0.12, 0.22, 0.40]),
    ],
    "野手": [
        ("三振", "ミート", [30, 40, 50], [0.30, 0.20, 0.12, 0.06]),
        ("内野安打○", "走力", [60, 70, 80], [0.02, 0.12, 0.30, 0.50]),
        ("エラー", "守備力", [35, 45, 55], [0.08, 0.05, 0.03, 0.02]),
        ("併殺", "走力", [50, 60, 70], [0.10, 0.04, 0.02, 0.01]),
    ],
}
# 出現率を上げる特能: (特能名, 既存処理での保有率, 目標の保有率)
DRAFT_SPECIAL_RATE_TARGETS = {
    "投手": [
        ("抜け球", 0.107, 0.25), ("リリース○", 0.041, 0.12), ("球持ち○", 0.045, 0.12),
        ("球速安定", 0.107, 0.16), ("内角攻め", 0.038, 0.10), ("緩急○", 0.053, 0.10),
    ],
    "野手": [("流し打ち", 0.050, 0.15)],
}
# 上の特能以外の（数える）特能を残す確率。通常特能の数を 投手 高卒2.1／大卒・社会人3.0、
# 野手 高卒1.0／大卒・社会人1.7 前後にする。
DRAFT_OTHER_SPECIAL_KEEP_RATES = {
    "投手": {"高卒": 0.42, "大卒": 0.80, "社会人": 0.80, "その他": 0.80},
    "野手": {"高卒": 0.20, "大卒": 0.56, "社会人": 0.56, "その他": 0.56},
}

# 野手の基本能力（ミート, パワー, 走力, 肩力, 守備力, 捕球）。
# 既存処理の経路別平均・守備位置ごとのずれ・残りの標準偏差（育成候補を除く野手1617人で測定）を、
# 実在の1年目の値に写す。
DRAFT_FIELDER_CURRENT_ROUTE_MEANS = {
    "高卒": (33.9, 40.9, 55.1, 55.6, 42.9, 41.9), "大卒": (43.6, 45.5, 56.4, 57.5, 49.3, 47.6),
    "社会人": (48.0, 47.6, 56.3, 56.6, 51.4, 49.9), "その他": (43.7, 47.1, 57.0, 55.4, 49.1, 46.7),
}
DRAFT_FIELDER_CURRENT_POSITION_DEVS = {
    "捕手": (-5.3, -0.7, -10.3, 5.9, 4.1, 5.4), "一塁手": (0.3, 5.3, -7.7, -7.3, -4.7, -1.1),
    "二塁手": (0.6, -3.9, 5.3, -6.2, 4.0, 3.6), "三塁手": (1.1, 5.5, -5.7, 2.1, -4.4, -3.7),
    "遊撃手": (1.6, -4.8, 5.7, 4.4, 7.4, 3.5), "外野手": (0.3, 0.1, 3.9, 0.6, -3.5, -3.6),
}
DRAFT_FIELDER_CURRENT_SDS = {
    "高卒": (12.0, 14.5, 12.6, 10.7, 10.4, 9.8), "大卒": (10.9, 13.8, 12.7, 9.5, 10.5, 9.2),
    "社会人": (10.7, 12.5, 10.8, 9.1, 9.4, 8.4), "その他": (10.7, 15.0, 12.4, 9.1, 10.6, 9.8),
}
DRAFT_FIELDER_TARGET_ROUTE_MEANS = {
    "高卒": (31.0, 45.0, 61.0, 67.5, 38.0, 37.0), "大卒": (38.0, 50.0, 66.5, 65.0, 49.0, 45.0),
    "社会人": (40.0, 49.0, 66.5, 64.0, 50.0, 45.0), "その他": (39.0, 49.5, 66.5, 64.5, 49.5, 45.0),
}
DRAFT_FIELDER_TARGET_SDS = {
    "高卒": (7.5, 8.5, 9.5, 8.0, 7.5, 7.0), "大卒": (8.5, 9.0, 10.5, 9.5, 7.5, 7.0),
    "社会人": (7.0, 9.5, 10.5, 8.5, 7.5, 7.0), "その他": (8.0, 9.0, 10.5, 9.5, 7.5, 7.0),
}
# 実在の1年目の守備位置ごとのずれ。捕手は肩、二遊間・外野は足、一塁・三塁はパワー。
DRAFT_FIELDER_TARGET_POSITION_DEVS = {
    "捕手": (-4.0, 0.0, -7.5, 9.0, -5.0, -6.0), "一塁手": (0.0, 10.0, -17.5, -4.0, -7.0, -4.0),
    "二塁手": (0.0, -4.0, 8.5, -7.0, 9.0, 6.0), "三塁手": (0.0, 8.0, -7.5, 0.0, -7.0, -5.0),
    "遊撃手": (0.0, -4.0, 4.5, 0.0, 6.0, 4.0), "外野手": (0.0, 0.0, 5.5, 0.0, 0.0, 0.0),
}
# 選手格ごとの補正（超上位候補は既存処理で上位候補と差がないので、打撃を少し上げる）
DRAFT_FIELDER_CLASS_SHIFTS = {"超上位候補": (3.0, 3.0, 0.0, 0.0, 1.0, 1.0)}
# ミート・パワーの上限。超えてよいのは超上位候補だけ（超えた分も縮める）。
DRAFT_FIELDER_CAPS = {
    "高卒": {"ミート": 55, "パワー": 70}, "大卒": {"ミート": 65, "パワー": 78},
    "社会人": {"ミート": 60, "パワー": 75}, "その他": {"ミート": 62, "パワー": 76},
}
DRAFT_ARM_LOW_TAIL_PIVOT = 60.0
DRAFT_ARM_LOW_TAIL_STRETCH = 1.4
# 弾道はパワーに揺らぎを足したスコアで決める（実在の1年目: 弾道1 2%、2 47%、3 45%、4 6%）。
DRAFT_TRAJECTORY_NOISE_SD = 8.0
DRAFT_TRAJECTORY_THRESHOLDS = (21.0, 50.0, 68.0)
DRAFT_TRAJECTORY_ONE_MAX_POWER = 29
# 高卒は実在で弾道1が0%、弾道4が10%（パワーのわりに弾道が高い）。
DRAFT_TRAJECTORY_ROUTE_BONUS = {"高卒": 4.0}
# サブポジの数の重み（0, 1, 2個）。実在は0個37%・1個15%・2個48%で、内野手は2つ持ちが普通。
DRAFT_SUB_POSITION_COUNT_WEIGHTS = {
    "遊撃手": (10, 15, 75), "二塁手": (15, 20, 65), "三塁手": (15, 25, 60),
    "一塁手": (35, 30, 35), "捕手": (60, 25, 15), "外野手": (60, 25, 15),
}


def draft_map_value(value: float, current_mean: float, target_mean: float, scale: float) -> float:
    return target_mean + (value - current_mean) * scale


def draft_pitcher_breaking_balls(rng: random.Random, breaking_balls: list[dict[str, Any]], batting_throwing: str, route: str) -> list[dict[str, Any]]:
    """4球種以上をなくし、高卒は3球種を増やして変化量を小さく、大卒・社会人は決め球を1段階下げる。"""
    balls = [dict(ball) for ball in breaking_balls]
    breaking = [ball for ball in balls if ball.get("kind") == "breaking"]
    while len(breaking) > 3:
        # 同じ方向の第二球種 → 変化量の小さい球種の順に外す
        drop = min(breaking, key=lambda ball: (not ball.get("is_second_pitch"), pitch_movement(ball)))
        breaking.remove(drop)
        balls.remove(drop)
    if len(breaking) == 2 and rng.random() < DRAFT_THIRD_PITCH_ADD_RATES.get(route, 0.0):
        used_codes = {str(ball.get("direction_code")) for ball in breaking}
        code = weighted_choice(rng, [(code, weight) for code, weight in DIRECTION_SELECTION_WEIGHTS.items() if code not in used_codes])
        factors = FICTIONAL_ADDED_PITCH_HAND_FACTORS["左投" if batting_throwing.startswith("左投") else "右投"]
        items = [
            (name, BREAKING_BY_NAME[name]["base_weight"] * factors.get(name, 1.0))
            for name in sorted(allowed_pitch_names_for_generation(code, batting_throwing))
        ]
        name = weighted_choice(rng, [(name, weight) for name, weight in items if weight > 0])
        top = max(pitch_movement(ball) for ball in breaking)
        weights = DRAFT_ADDED_PITCH_MOVEMENT_WEIGHTS["高卒" if route == "高卒" else "その他"]
        balls.insert(len(breaking), make_breaking_ball(name, min(top, weighted_choice(rng, weights)), False, 1))
    finisher = max((ball for ball in balls if ball.get("kind") == "breaking"), key=pitch_movement, default=None)
    for ball in balls:
        if ball.get("kind") != "breaking":
            continue
        movement = pitch_movement(ball)
        if route == "高卒":
            movement = min(movement, DRAFT_HIGH_SCHOOL_MAX_MOVEMENT)
        elif movement >= 5 or (movement == 4 and rng.random() < DRAFT_MOVEMENT4_DROP_RATE):
            movement -= 1
        elif ball is not finisher and movement >= 2 and rng.random() < DRAFT_SUB_MOVEMENT_DROP_RATE:
            movement -= 1
        movement = max(int(BREAKING_BY_NAME[str(ball["name"])].get("min_movement", 1)), movement)
        ball["movement"] = ball["level"] = movement
    enforce_second_pitch_movement_order(balls)
    return balls


def draft_adjust_specials(
    rng: random.Random,
    master: MasterData,
    role: str,
    route: str,
    player_class: str,
    specials: list[str],
    values: dict[str, float],
    is_allowed: Any,
) -> list[str]:
    """実在の1年目で多い特能を増やし、少ない特能を減らし、通常特能の数を経路ごとの実在並みにする。"""
    allowed_names = role_allowed_specials(master, role)
    group_of = {str(row["name"]): str(row.get("group", "")) for row in master.abilities}
    check = lambda name: name in allowed_names and is_allowed(name)
    selected = list(specials)
    for name, keep in DRAFT_SPECIAL_KEEP_RATES[role].items():
        if name in selected and rng.random() >= keep:
            selected.remove(name)
    protected: set[str] = set()
    for name, key, limits, rates in DRAFT_LINKED_SPECIALS[role]:
        present = rng.random() < fictional_band_rate(values.get(key, 0), limits, rates)
        fictional_set_special(selected, name, present, group_of, True, check)
        protected.add(name)
    for name, current, target in DRAFT_SPECIAL_RATE_TARGETS[role]:
        if name not in selected and rng.random() < (target - current) / (1.0 - current):
            fictional_set_special(selected, name, True, group_of, False, check)
        protected.add(name)
    keep_rate = DRAFT_OTHER_SPECIAL_KEEP_RATES[role][route]
    selected = [
        name for name in selected
        if name in protected or name in DRAFT_UNCOUNTED_SPECIALS or not is_countable_special(name) or rng.random() < keep_rate
    ]
    # サブポジの付け替えなどで位置・起用の条件を満たさなくなった特能を外す。
    selected = [name for name in selected if is_allowed(name)]
    low, high = special_count_bounds("ドラフト候補用", player_class)
    countable = lambda: sum(is_countable_special(name) for name in selected)
    while countable() > high:
        removable = [name for name in selected if is_countable_special(name)]
        selected.remove(next((name for name in reversed(removable) if name not in protected), removable[-1]))
    for name in FICTIONAL_SPECIAL_FILLERS[role]:
        if countable() >= low:
            break
        fictional_set_special(selected, name, True, group_of, False, check)
    return selected


def apply_draft_pitcher_balance(player: dict[str, Any], seed: int, master: MasterData) -> dict[str, Any]:
    """ドラフト候補の投手を、実在のプロ1年目の投手の傾向に合わせて部分的に直す。"""
    rng = make_sub_rng(seed, DRAFT_PITCHER_BALANCE_NAMESPACE)
    route = draft_route_group(str(player.get("entry_route", "")))
    position = str(player.get("position", ""))
    pitcher_aptitudes = {key: str(player.get(key, "-")) for key in PITCHER_APTITUDE_KEYS}
    abilities = dict(player.get("abilities", {}))

    # 球速: 全体を4〜5km/h上げ、下側の裾を細くする（144以下を5%以下に）。
    speed_mean, speed_target, speed_scale = DRAFT_PITCHER_SPEED_MAPS[route]
    speed = draft_map_value(float(pitcher_speed_value(abilities) or 145), speed_mean, speed_target, speed_scale)
    speed += DRAFT_PITCHER_CLASS_SPEED_SHIFTS.get(str(player.get("player_class", "")), 0.0)
    speed = compress_tail(speed, speed_target - 3.5, 0.6, upper=False)
    # 158以上は全体の3〜5%程度に抑える（実在の最高は161）。
    speed = round(compress_tail(speed, speed_target + 3.5, 0.35, upper=True))
    control_mean, control_target, control_scale = DRAFT_PITCHER_CONTROL_MAPS[route]
    control = draft_map_value(float(ability_numeric_value(abilities, "コントロール") or 45), control_mean, control_target, control_scale)
    control = clamp(round(compress_tail(control, 30.0, 0.5, upper=False)), 15, 95)
    stamina_mean, stamina_target, stamina_scale, stamina_cap = DRAFT_PITCHER_STAMINA_MAPS[route]
    stamina = draft_map_value(float(ability_numeric_value(abilities, "スタミナ") or 45), stamina_mean, stamina_target, stamina_scale)
    stamina = clamp(round(compress_tail(stamina, stamina_cap - 8, 0.5, upper=True)), 15, stamina_cap)
    set_pitcher_speed(abilities, speed)
    abilities["コントロール"] = ability(control)
    abilities["スタミナ"] = ability(stamina)
    abilities["肩力"] = ability(clamp(speed - 81 + weighted_choice(rng, [(-1, 15), (0, 35), (1, 35), (2, 15)]), 49, 82))
    player["abilities"] = abilities

    player["breaking_balls"] = draft_pitcher_breaking_balls(rng, list(player.get("breaking_balls", [])), str(player.get("batting_throwing", "")), route)
    player["special_abilities"] = draft_adjust_specials(
        rng, master, "投手", route, str(player.get("player_class", "")), list(player.get("special_abilities", [])),
        {"球速": speed, "コントロール": control},
        lambda name: is_special_allowed_for_player(name, "投手", position, [], pitcher_aptitudes),
    )
    return player


def draft_fielder_abilities(rng: random.Random, abilities: dict[str, Any], position: str, route: str, player_class: str) -> dict[str, Any]:
    """経路・守備位置ごとの平均と幅を実在の1年目に写し、弾道をパワーから確率的に決め直す。"""
    current_devs = DRAFT_FIELDER_CURRENT_POSITION_DEVS.get(position, (0.0,) * 6)
    target_devs = DRAFT_FIELDER_TARGET_POSITION_DEVS.get(position, (0.0,) * 6)
    class_shifts = DRAFT_FIELDER_CLASS_SHIFTS.get(player_class, (0.0,) * 6)
    result = dict(abilities)
    values: dict[str, float] = {}
    for index, key in enumerate(FICTIONAL_FIELDER_ABILITY_KEYS):
        current_mean = DRAFT_FIELDER_CURRENT_ROUTE_MEANS[route][index]
        z = ((ability_numeric_value(abilities, key) or current_mean) - current_mean - current_devs[index]) / DRAFT_FIELDER_CURRENT_SDS[route][index]
        values[key] = DRAFT_FIELDER_TARGET_ROUTE_MEANS[route][index] + target_devs[index] + class_shifts[index] + DRAFT_FIELDER_TARGET_SDS[route][index] * z
    # 実在は肩力の下側（50未満が7%）が正規分布より厚い。
    values["肩力"] = compress_tail(values["肩力"], DRAFT_ARM_LOW_TAIL_PIVOT, DRAFT_ARM_LOW_TAIL_STRETCH, upper=False)
    for key, cap in DRAFT_FIELDER_CAPS[route].items():
        values[key] = compress_tail(values[key], cap, 0.4, upper=True) if player_class == "超上位候補" else min(values[key], cap)
    for key in FICTIONAL_FIELDER_ABILITY_KEYS:
        result[key] = ability(clamp(round(values[key]), 1, 100))
    power = result["パワー"]["value"]
    score = power + DRAFT_TRAJECTORY_ROUTE_BONUS.get(route, 0.0) + rng.gauss(0.0, DRAFT_TRAJECTORY_NOISE_SD)
    trajectory = 1 + sum(score >= threshold for threshold in DRAFT_TRAJECTORY_THRESHOLDS)
    if trajectory == 1 and power > DRAFT_TRAJECTORY_ONE_MAX_POWER:
        trajectory = 2
    result["弾道"] = trajectory
    return result


def draft_fielder_sub_positions(rng: random.Random, position: str, batting_throwing: str) -> list[dict[str, str]]:
    """サブポジの数を守備位置ごとに決め、組み合わせは実在の保有率の重みで選ぶ。"""
    count = weighted_choice(rng, list(zip((0, 1, 2), DRAFT_SUB_POSITION_COUNT_WEIGHTS.get(position, (60, 25, 15)))))
    candidates = [
        (sub, rate) for sub, rate in FICTIONAL_SUB_POSITION_RATES.get(position, {}).items()
        if not batting_throwing.startswith("左投") or sub in {"一塁手", "外野手"}
    ]
    selected: list[dict[str, str]] = []
    while candidates and len(selected) < count:
        sub = weighted_choice(rng, candidates)
        candidates = [(name, rate) for name, rate in candidates if name != sub]
        if sub == "外野手":
            weights = FICTIONAL_SUB_POSITION_APTITUDE_WEIGHTS.get((position, sub), FICTIONAL_SUB_TO_OUTFIELD_APTITUDE_WEIGHTS)
        elif sub == "捕手":
            weights = FICTIONAL_SUB_TO_CATCHER_APTITUDE_WEIGHTS
        else:
            weights = FICTIONAL_SUB_POSITION_APTITUDE_WEIGHTS.get((position, sub), FICTIONAL_SUB_INFIELD_APTITUDE_WEIGHTS)
        selected.append({"position": sub, "aptitude": weighted_choice(rng, list(zip(("◎", "○", "△"), weights)))})
    return selected


def apply_draft_fielder_balance(player: dict[str, Any], seed: int, master: MasterData) -> dict[str, Any]:
    """ドラフト候補の野手を、実在のプロ1年目の野手の傾向に合わせて部分的に直す。"""
    rng = make_sub_rng(seed, DRAFT_FIELDER_BALANCE_NAMESPACE)
    route = draft_route_group(str(player.get("entry_route", "")))
    position = str(player.get("position", ""))
    player_class = str(player.get("player_class", ""))
    batting_throwing = str(player.get("batting_throwing", ""))
    abilities = draft_fielder_abilities(rng, dict(player.get("abilities", {})), position, route, player_class)
    sub_positions = draft_fielder_sub_positions(rng, position, batting_throwing)
    player["sub_positions"] = sub_positions
    values = {key: float(abilities[key]["value"]) for key in FICTIONAL_FIELDER_ABILITY_KEYS}
    player["special_abilities"] = draft_adjust_specials(
        rng, master, "野手", route, player_class, list(player.get("special_abilities", [])), values,
        lambda name: is_special_allowed_for_player(name, "野手", position, sub_positions),
    )
    # サブポジを付け替えたので、キャッチャーのランク特能を捕手適性の有無に合わせる。
    ranked = dict(abilities.get("ranked_specials", {}) or {})
    if has_position_aptitude(position, sub_positions, {"捕手"}):
        ranked.setdefault("キャッチャー", ranked_special_names_by_group(master).get("キャッチャー", {}).get("D", "キャッチャーD"))
    else:
        ranked.pop("キャッチャー", None)
    abilities["ranked_specials"] = ranked
    player["abilities"] = abilities
    return player


def generate_player(role: str, category: str, master: MasterData, seed: int | None = None, used_names: set[str] | None = None, apply_age_special_tail: bool = True, apply_individual_age_profile: bool = True, apply_ranked_age_profile: bool = True, apply_pro_year_profile: bool = True, apply_physique: bool = True, include_physique_baseline: bool = False) -> dict[str, Any]:
    seed = seed if seed is not None else random.SystemRandom().randrange(SEED_MAX)
    rng = random.Random(seed)
    draft_source_type = choose_draft_source_type(rng) if category == "ドラフト候補用" else ""
    if category == "助っ人外国人用":
        foreign_context = generate_foreign_context(seed, role)
        age = int(foreign_context["age"])
        player_class = choose_player_class(make_sub_rng(seed, f"foreign_player_class_v2:{role}"), "助っ人外国人用", age, int(foreign_context["npb_years"]), str(foreign_context["foreign_route"]))
        career_history = foreign_career_history(foreign_context)
        roster_context = {key: foreign_context[key] for key in ("roster_origin", "foreign_route", "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee")}
        nationality = str(foreign_context["nationality"])
        model_category = "助っ人外国人用"
        foreign_profile = generate_foreign_profile(rng, category, display_nationality=nationality, used_names=used_names)
    else:
        age = age_for(rng, category, draft_source_type)
        player_class = choose_player_class(rng, category, age)
        career_history = generate_career_history(
            category=category,
            age=age,
            seed=seed,
            role=role,
            draft_source_type=draft_source_type,
            player_class=player_class,
        )
        nationality = choose_nationality(rng, category)
        roster_origin = determine_roster_origin(category, nationality, seed)
        foreign_profile = None
        model_category = category
        if roster_origin == "foreign_import":
            foreign_context = generate_foreign_context(seed, role)
            age = int(foreign_context["age"])
            player_class = choose_player_class(make_sub_rng(seed, f"foreign_player_class_v2:{role}"), "助っ人外国人用", age, int(foreign_context["npb_years"]), str(foreign_context["foreign_route"]))
            career_history = foreign_career_history(foreign_context)
            roster_context = {key: foreign_context[key] for key in ("roster_origin", "foreign_route", "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee")}
            nationality = str(foreign_context["nationality"])
            model_category = "助っ人外国人用"
            foreign_profile = generate_foreign_profile(rng, category, display_nationality=nationality, used_names=used_names)
        else:
            roster_context = domestic_roster_context(career_history)
            if nationality != "日本":
                foreign_profile = generate_foreign_profile(rng, category, display_nationality=nationality, used_names=used_names)
    development_stage = choose_development_stage(rng, model_category, age, player_class, draft_source_type)
    pitcher_aptitudes: dict[str, str] = {}
    if role == "投手":
        pitcher_aptitudes = choose_pitcher_aptitudes(rng, model_category)
        position = primary_pitcher_role(pitcher_aptitudes)
        if model_category == "架空球団用" and position == "抑え" and make_sub_rng(seed, "fictional_closer_position_v1").random() >= FICTIONAL_CLOSER_POSITION_RATE:
            position = "中継ぎ"
    else:
        if model_category == "助っ人外国人用":
            position_weights = FOREIGN_FIELDER_POSITION_WEIGHTS
        elif model_category == "架空球団用":
            position_weights = FICTIONAL_FIELDER_POSITION_WEIGHTS
        elif model_category == "ドラフト候補用":
            position_weights = DRAFT_FIELDER_POSITION_WEIGHTS
        else:
            position_weights = [("捕手", 12), ("一塁手", 14), ("二塁手", 14), ("三塁手", 14), ("遊撃手", 16), ("外野手", 30)]
        position = weighted_choice(rng, position_weights)
    batting_throwing = generate_batting_throwing(rng, role, position, model_category)
    foreign_npby = int(roster_context.get("npb_years", 0)) if roster_context.get("roster_origin") == "foreign_import" else 0
    foreign_route = str(roster_context.get("foreign_route", ""))
    acquisition_role = choose_acquisition_role(rng, model_category, role, player_class, position, pitcher_aptitudes, batting_throwing, foreign_npby, foreign_route)
    archetype = choose_archetype(rng, role, model_category, age=age, player_class=player_class, npb_years=foreign_npby, foreign_route=foreign_route)
    if role == "投手" and position == "抑え" and archetype == "スタミナ":
        for _ in range(4):
            archetype = choose_archetype(rng, role, model_category, age=age, player_class=player_class, npb_years=foreign_npby, foreign_route=foreign_route)
            if archetype != "スタミナ":
                break
        if archetype == "スタミナ":
            archetype = "総合"
    position_style = choose_position_style(rng, role, position, archetype)
    weakness_profile = choose_weakness_profile(rng, model_category, role, player_class, foreign_npby)
    growth_type = choose_growth_type(
        category=model_category, age=age, player_class=player_class, development_stage=development_stage,
        acquisition_role=acquisition_role, rng=create_growth_rng(seed, role, model_category),
    )
    allow_foreign_allrounder = choose_foreign_allrounder_candidate(rng, model_category, player_class, age, archetype, position_style) if role == "野手" else False
    player_type = legacy_player_type_from_archetype(role, archetype)
    roster_tier = legacy_roster_tier_from_player_class(player_class)
    # Keep the legacy draws in place so every downstream main-RNG draw remains
    # identical for an existing seed.  The displayed physique uses a stable,
    # namespaced sub-RNG instead.
    legacy_height = rng.randint(168, 196) + (3 if role == "投手" else 0)
    legacy_weight = rng.randint(68, 105)
    height_cm, weight_kg = generate_physique(seed, role, position)
    z_height, z_build = physique_indices(physique_position(role, position), height_cm, weight_kg)
    effect_z_height, effect_z_build = (z_height, z_build) if apply_physique else (0.0, 0.0)
    if role == "投手":
        physique_ability_rng = clone_rng(rng)
        abilities = generate_pitcher_abilities(
            physique_ability_rng, age, player_type, model_category, pitcher_aptitudes,
            player_class=player_class, archetype=archetype, position_style=position_style,
            development_stage=development_stage, acquisition_role=acquisition_role,
            weakness_profile=weakness_profile, growth_type=growth_type,
            physique_z_height=effect_z_height, physique_z_build=effect_z_build,
        )
        abilities.update(generate_pitcher_batting_abilities(physique_ability_rng, age, legacy_weight, pitcher_speed_value(abilities) or 145))
        baseline_abilities = generate_pitcher_abilities(
            rng, age, player_type, model_category, pitcher_aptitudes,
            player_class=player_class, archetype=archetype, position_style=position_style,
            development_stage=development_stage, acquisition_role=acquisition_role,
            weakness_profile=weakness_profile, growth_type=growth_type,
        )
        baseline_abilities.update(generate_pitcher_batting_abilities(rng, age, legacy_weight, pitcher_speed_value(baseline_abilities) or 145))
        breaking_balls = generate_breaking_balls(
            rng, player_type, model_category, pitcher_aptitudes, batting_throwing,
            age=age, player_class=player_class, archetype=archetype, position_style=position_style,
            development_stage=development_stage, acquisition_role=acquisition_role,
            weakness_profile=weakness_profile,
        )
    else:
        physique_ability_rng = clone_rng(rng)
        abilities = generate_fielder_abilities(
            physique_ability_rng, age, position, player_type, model_category, position_style, roster_tier,
            player_class=player_class, archetype=archetype, development_stage=development_stage,
            acquisition_role=acquisition_role, weakness_profile=weakness_profile,
            allow_foreign_allrounder=allow_foreign_allrounder, growth_type=growth_type,
            physique_z_height=effect_z_height, physique_z_build=effect_z_build,
        )
        baseline_abilities = generate_fielder_abilities(
            rng, age, position, player_type, model_category, position_style, roster_tier,
            player_class=player_class, archetype=archetype, development_stage=development_stage,
            acquisition_role=acquisition_role, weakness_profile=weakness_profile,
            allow_foreign_allrounder=allow_foreign_allrounder, growth_type=growth_type,
        )
        breaking_balls = []
    baseline_breaking_balls = copy.deepcopy(breaking_balls)
    physique_audit_rng = clone_rng(rng)
    abilities, breaking_balls = audit_generated_player(
        physique_audit_rng, role, model_category, age, position, player_class, archetype, position_style,
        development_stage, acquisition_role, weakness_profile, abilities, breaking_balls,
        allow_foreign_allrounder=allow_foreign_allrounder,
    )
    baseline_abilities, _ = audit_generated_player(
        rng, role, model_category, age, position, player_class, archetype, position_style,
        development_stage, acquisition_role, weakness_profile, baseline_abilities, baseline_breaking_balls,
        allow_foreign_allrounder=allow_foreign_allrounder,
    )
    if role == "投手":
        shoulder_delta = weighted_choice(rng, [(-1, 15), (0, 35), (1, 35), (2, 15)])
        abilities["肩力"] = ability(clamp((pitcher_speed_value(abilities) or 145) - 81 + shoulder_delta, 49, 82))
        baseline_abilities["肩力"] = ability(clamp((pitcher_speed_value(baseline_abilities) or 145) - 81 + shoulder_delta, 49, 82))
    physique_sub_rng = clone_rng(rng)
    sub_positions = generate_sub_positions(physique_sub_rng, role, position, player_type, model_category, age, batting_throwing, abilities, player_class, archetype, position_style, acquisition_role)
    baseline_sub_positions = generate_sub_positions(rng, role, position, player_type, model_category, age, batting_throwing, baseline_abilities, player_class, archetype, position_style, acquisition_role)
    def generate_player_specials(
        target_rng: random.Random,
        target_abilities: dict[str, Any],
        target_breaking_balls: list[dict[str, Any]],
        target_sub_positions: list[dict[str, str]],
    ) -> list[str]:
        special_args = (
            master, role, player_type, position, age, target_abilities, target_breaking_balls, model_category,
            player_class, archetype, position_style, development_stage, acquisition_role,
            weakness_profile, target_sub_positions, pitcher_aptitudes,
        )
        if model_category == "架空球団用" and (apply_age_special_tail or apply_individual_age_profile or apply_pro_year_profile):
            # 補正後の結果とメインRNG消費を分離し、既存seedの後続系列を維持する。
            special_rng = clone_rng(target_rng)
            result = generate_specials(
                special_rng, *special_args,
                apply_age_tail=apply_age_special_tail,
                apply_age_profile=apply_individual_age_profile,
                pro_years=career_history.get("pro_years"),
                apply_pro_year_profile=apply_pro_year_profile,
            )
            generate_specials(
                target_rng, *special_args, apply_age_tail=False, apply_age_profile=False,
                pro_years=career_history.get("pro_years"), apply_pro_year_profile=False,
            )
            return result
        return generate_specials(
            target_rng, *special_args,
            apply_age_tail=apply_age_special_tail,
            apply_age_profile=apply_individual_age_profile,
            pro_years=career_history.get("pro_years"),
            apply_pro_year_profile=apply_pro_year_profile,
        )

    physique_special_rng = clone_rng(rng)
    special_abilities = generate_player_specials(physique_special_rng, abilities, breaking_balls, sub_positions)
    generate_player_specials(rng, baseline_abilities, baseline_breaking_balls, baseline_sub_positions)
    birth_month, birth_day = generate_birthday(rng)
    if role == "投手":
        pitching_form_type, pitching_form_number, pitching_form_is_generic = generate_pitching_form(rng, model_category, archetype, position)
    else:
        pitching_form_type, pitching_form_number, pitching_form_is_generic = "", 0, 1
    batting_form_type, batting_form_number, batting_form_is_generic = generate_batting_form(rng, role, model_category, archetype, legacy_height)
    equipment = generate_equipment(rng, role, model_category, archetype, position)
    if foreign_profile:
        name = foreign_profile.name
        birthplace = choose_profile_birthplace(rng, master.places, nationality, foreign_profile.actual_nationality)
    elif nationality == "日本":
        name, birthplace = choose_japanese_identity(rng, master.names)
    else:
        name = choose_name(rng, master.names, nationality)
        birthplace = choose_birthplace(rng, master.places, nationality)
    actual_nationality = foreign_profile.actual_nationality if foreign_profile else (nationality if nationality != "日本" else "")
    player = {
        "seed": seed, "role": role, "category": category, "name": name, "age": age,
        **career_history,
        **roster_context,
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
        "height": height_cm, "weight": weight_kg,
        "height_cm": height_cm, "weight_kg": weight_kg,
        "birth_month": birth_month, "birth_day": birth_day,
        "pitching_form_type": pitching_form_type, "pitching_form_number": pitching_form_number, "pitching_form_is_generic": pitching_form_is_generic,
        "batting_form_type": batting_form_type, "batting_form_number": batting_form_number, "batting_form_is_generic": batting_form_is_generic,
        "draft_source_type": draft_source_type,
        **equipment,
        "abilities": {**abilities, "ranked_specials": generate_ranked_specials(rng, master, role, position, player_type, abilities, age, model_category, player_class, archetype, position_style, weakness_profile, sub_positions, pitcher_aptitudes, apply_ranked_age_profile)}, "special_abilities": special_abilities,
        "breaking_balls": breaking_balls,
        "sub_positions": sub_positions,
        **({"_baseline_abilities": baseline_abilities} if include_physique_baseline else {}),
        **pitcher_aptitudes,
    }
    if role == "投手" and model_category == "助っ人外国人用":
        apply_foreign_pitcher_balance(player, seed, master)
    elif role == "野手" and model_category == "助っ人外国人用":
        apply_foreign_fielder_balance(player, seed, master)
    elif role == "投手" and model_category == "架空球団用":
        apply_fictional_pitcher_balance(player, seed, master)
    elif role == "野手" and model_category == "架空球団用":
        apply_fictional_fielder_balance(player, seed, master)
    elif role == "投手" and model_category == "ドラフト候補用":
        apply_draft_pitcher_balance(player, seed, master)
    elif role == "野手" and model_category == "ドラフト候補用":
        apply_draft_fielder_balance(player, seed, master)
    return player


def choose_foreign_team_composition(seed: int) -> dict[str, int]:
    """Choose the foreign-import role mix for one fictional NPB team."""
    rng = make_sub_rng(seed, "foreign_phase3c_roster_composition_v1")
    pitcher_count, fielder_count = weighted_choice(rng, FOREIGN_TEAM_IMPORT_COMPOSITION_WEIGHTS)
    return {"投手": int(pitcher_count), "野手": int(fielder_count)}


def foreign_import_role_counts(players: list[dict[str, Any]]) -> dict[str, int]:
    """Count foreign imports by role without treating all foreign nationals as imports."""
    counts = {"投手": 0, "野手": 0}
    for player in players:
        role = str(player.get("role", ""))
        if player.get("roster_origin") == "foreign_import" and role in counts:
            counts[role] += 1
    return counts


def generate_foreign_import_roster(
    seed: int,
    master: MasterData | None = None,
    used_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate only the foreign-import portion of one fictional NPB team roster."""
    master = master or load_master_data()
    composition = choose_foreign_team_composition(seed)
    seed_rng = make_sub_rng(seed, "foreign_phase3c_roster_players_v1")
    used_names = used_names if used_names is not None else set()
    players: list[dict[str, Any]] = []
    for role in ("投手", "野手"):
        for _ in range(composition[role]):
            for _attempt in range(TEAM_ROSTER_DOMESTIC_MAX_ATTEMPTS):
                player = generate_player(
                    role,
                    "助っ人外国人用",
                    master,
                    seed=seed_rng.randrange(SEED_MAX),
                    used_names=set(used_names),
                )
                if str(player["name"]) not in used_names:
                    break
            else:
                raise RuntimeError(f"名前が重複しない外国人{role}を生成できませんでした。")
            used_names.add(str(player["name"]))
            players.append(player)
    return players


def choose_team_roster_composition(seed: int) -> dict[str, int]:
    """Choose the total role mix for one fictional NPB team."""
    rng = make_sub_rng(seed, "team_roster_composition_v1")
    pitcher_count, fielder_count = weighted_choice(rng, TEAM_ROSTER_COMPOSITION_WEIGHTS)
    return {"投手": int(pitcher_count), "野手": int(fielder_count)}


def generate_team_roster(seed: int, master: MasterData | None = None) -> list[dict[str, Any]]:
    """Generate one complete static team roster above the individual player layer."""
    master = master or load_master_data()
    team_composition = choose_team_roster_composition(seed)
    foreign_composition = choose_foreign_team_composition(seed)
    domestic_seed_rng = make_sub_rng(seed, "team_roster_domestic_players_v1")
    used_names: set[str] = set()
    players: list[dict[str, Any]] = []
    foreign_players = generate_foreign_import_roster(seed, master, used_names=used_names)
    position_counts = {
        position: sum(1 for player in foreign_players if player.get("position") == position)
        for position in TEAM_ROSTER_POSITION_MINIMUMS
    }

    for role in ("投手", "野手"):
        domestic_slots = team_composition[role] - foreign_composition[role]
        if domestic_slots < 0:
            raise ValueError(f"外国人{role}数が球団の{role}枠を超えています。")
        for _ in range(domestic_slots):
            for _attempt in range(TEAM_ROSTER_DOMESTIC_MAX_ATTEMPTS):
                player = generate_player(
                    role,
                    "架空球団用",
                    master,
                    seed=domestic_seed_rng.randrange(SEED_MAX),
                    used_names=set(used_names),
                )
                valid_origin_and_name = (
                    player.get("roster_origin") == "domestic"
                    and str(player["name"]) not in used_names
                )
                if not valid_origin_and_name:
                    continue
                if role == "野手":
                    remaining_slots = domestic_slots - sum(1 for item in players if item["role"] == "野手") - 1
                    projected = dict(position_counts)
                    if player.get("position") in projected:
                        projected[str(player["position"])] += 1
                    required_slots = sum(
                        max(0, minimum - projected[position])
                        for position, minimum in TEAM_ROSTER_POSITION_MINIMUMS.items()
                    )
                    if required_slots > remaining_slots:
                        continue
                if valid_origin_and_name:
                    break
            else:
                raise RuntimeError(f"国内枠の{role}を生成できませんでした。")
            used_names.add(str(player["name"]))
            players.append(player)
            if role == "野手" and player.get("position") in position_counts:
                position_counts[str(player["position"])] += 1

    players.extend(foreign_players)
    for roster_index, player in enumerate(players, start=1):
        player["team_seed"] = seed
        player["roster_index"] = roster_index
        player["roster_group"] = str(player["roster_origin"])
        player["roster_year"] = NPB_CURRENT_YEAR
    return players


def advance_foreign_import_roster_year(
    players: list[dict[str, Any]],
    seed: int,
    master: MasterData | None = None,
    used_names: set[str] | None = None,
    from_year: int = NPB_CURRENT_YEAR,
) -> list[dict[str, Any]]:
    """Advance one team's foreign-import roster by one contract year.

    The next-year composition is a recruitment floor. Retained players are not
    released merely because their count exceeds the newly sampled target.
    """
    if any(player.get("roster_origin") != "foreign_import" for player in players):
        raise ValueError("年度遷移にはforeign_import選手だけを渡してください。")

    master = master or load_master_data()
    next_year = int(from_year) + 1
    retention_rng = make_sub_rng(seed, "foreign_phase3d_retention_v1")
    next_players: list[dict[str, Any]] = []
    shared_names = used_names if used_names is not None else set()

    for previous in players:
        if retention_rng.random() >= FOREIGN_TEAM_RETENTION_RATE:
            continue
        retained = copy.deepcopy(previous)
        retained["age"] = int(previous.get("age", 0)) + 1
        retained["npb_years"] = int(previous.get("npb_years", 0)) + 1
        retained["pro_years"] = int(previous.get("pro_years", previous.get("npb_years", 0))) + 1
        retained["roster_group"] = "foreign_import"
        retained["roster_year"] = next_year
        retained["transition_status"] = "retained"
        shared_names.add(str(retained["name"]))
        next_players.append(retained)

    target = choose_foreign_team_composition(seed)
    retained_counts = foreign_import_role_counts(next_players)
    newcomer_rng = make_sub_rng(seed, "foreign_phase3d_new_players_v1")
    generated_year_shift = next_year - NPB_CURRENT_YEAR
    for role in ("投手", "野手"):
        for _ in range(max(0, target[role] - retained_counts[role])):
            for _attempt in range(TEAM_ROSTER_DOMESTIC_MAX_ATTEMPTS):
                newcomer = generate_player(
                    role,
                    "助っ人外国人用",
                    master,
                    seed=newcomer_rng.randrange(SEED_MAX),
                    used_names=set(shared_names),
                )
                if str(newcomer["name"]) not in shared_names:
                    break
            else:
                raise RuntimeError(f"名前が重複しない新規外国人{role}を生成できませんでした。")
            if generated_year_shift:
                for key in ("npb_first_entry_year", "npb_stint_start_year"):
                    if int(newcomer.get(key, 0)):
                        newcomer[key] = int(newcomer[key]) + generated_year_shift
            newcomer["roster_group"] = "foreign_import"
            newcomer["roster_year"] = next_year
            newcomer["transition_status"] = "new_joiner"
            shared_names.add(str(newcomer["name"]))
            next_players.append(newcomer)

    for roster_index, player in enumerate(next_players, start=1):
        player["roster_index"] = roster_index
    return next_players


def save_players(players: list[dict[str, Any]], saved_ids: list[int] | None = None) -> int:
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
            cursor = conn.execute("""INSERT INTO players (created_at, seed, role, category, name, age, roster_origin, foreign_route, entry_route, pro_entry_age, pro_years, npb_years, npb_first_entry_year, npb_stint_start_year, is_returnee, nationality, actual_nationality, nationality_code, name_group_id, name_group_name, skin_color, birthplace, region, position, player_type, player_class, growth_type, archetype, position_style, development_stage, acquisition_role, weakness_profile, handedness, batting_throwing, height, weight, height_cm, weight_kg, abilities_json, special_abilities_json, ranked_special_abilities_json, breaking_balls_json, pitcher_aptitudes_json, sub_positions_json, birth_month, birth_day, pitching_form_type, pitching_form_number, pitching_form_is_generic, batting_form_type, batting_form_number, batting_form_is_generic, bat_color, glove_color, wristband_left_enabled, wristband_left_color, wristband_right_enabled, wristband_right_color, draft_source_type)
                          VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (p.get("seed", 0), p.get("role", ""), p.get("category", ""), p.get("name", ""), p.get("age", 0), p.get("roster_origin", ""), p.get("foreign_route", ""), p.get("entry_route", ""), p.get("pro_entry_age", 0), p.get("pro_years", 0), p.get("npb_years", p.get("pro_years", 0)), p.get("npb_first_entry_year", 0), p.get("npb_stint_start_year", 0), int(bool(p.get("is_returnee", False))), p.get("nationality", ""), p.get("actual_nationality", ""), p.get("nationality_code", ""), p.get("name_group_id", 0), p.get("name_group_name", ""), p.get("skin_color", 0), birthplace, region, p.get("position", ""), p.get("player_type", ""), p.get("player_class", ""), normalize_growth_type(p.get("growth_type")), p.get("archetype", ""), p.get("position_style", ""), p.get("development_stage", ""), p.get("acquisition_role", ""), p.get("weakness_profile", ""), p.get("handedness", ""), p.get("batting_throwing", ""), p.get("height", 0), p.get("weight", 0), p.get("height_cm"), p.get("weight_kg"), json.dumps(abilities, ensure_ascii=False), json.dumps(p.get("special_abilities", []), ensure_ascii=False), json.dumps(ranked_specials, ensure_ascii=False), json.dumps(p.get("breaking_balls", []), ensure_ascii=False), json.dumps(pitcher_aptitudes, ensure_ascii=False), json.dumps(normalize_sub_positions(p.get("sub_positions", [])), ensure_ascii=False), p.get("birth_month", 0), p.get("birth_day", 0), p.get("pitching_form_type", ""), p.get("pitching_form_number", 0), p.get("pitching_form_is_generic", 1), p.get("batting_form_type", ""), p.get("batting_form_number", 0), p.get("batting_form_is_generic", 1), p.get("bat_color", ""), p.get("glove_color", ""), p.get("wristband_left_enabled", 0), p.get("wristband_left_color", ""), p.get("wristband_right_enabled", 0), p.get("wristband_right_color", ""), p.get("draft_source_type", "")))
            if saved_ids is not None:
                saved_ids.append(int(cursor.lastrowid))
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
        wanted = ["id", "created_at", "seed", "role", "category", "name", "age", "roster_origin", "foreign_route", "entry_route", "pro_entry_age", "pro_years", "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee", "nationality", "actual_nationality", "nationality_code", "name_group_id", "name_group_name", "skin_color", "birthplace", "region", "position", "player_type", "growth_type", *CLASSIFICATION_COLUMNS, "handedness", "batting_throwing", "height", "weight", "height_cm", "weight_kg", "abilities_json", "special_abilities_json", "ranked_special_abilities_json", "breaking_balls_json", "pitcher_aptitudes_json", "sub_positions_json", "birth_month", "birth_day", "pitching_form_type", "pitching_form_number", "pitching_form_is_generic", "batting_form_type", "batting_form_number", "batting_form_is_generic", "bat_color", "glove_color", "wristband_left_enabled", "wristband_left_color", "wristband_right_enabled", "wristband_right_color", "draft_source_type"]
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
        for column in ["pro_entry_age", "pro_years", "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee", "birth_month", "birth_day", "pitching_form_number", "pitching_form_is_generic", "batting_form_number", "batting_form_is_generic", "wristband_left_enabled", "wristband_right_enabled"]:
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
    keys = ["role", "category", "name", "age", "roster_origin", "foreign_route", "entry_route", "pro_entry_age", "pro_years", "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee", "nationality", "actual_nationality", "nationality_code", "name_group_id", "name_group_name", "skin_color", "birthplace", "position", "player_type", *CLASSIFICATION_COLUMNS, "handedness", "batting_throwing", "height", "weight", "height_cm", "weight_kg", "abilities_json", "special_abilities_json", "breaking_balls_json", "birth_month", "birth_day", "pitching_form_type", "pitching_form_number", "pitching_form_is_generic", "batting_form_type", "batting_form_number", "batting_form_is_generic", "bat_color", "glove_color", "wristband_left_enabled", "wristband_left_color", "wristband_right_enabled", "wristband_right_color", "draft_source_type"]
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


CAREER_AGE_BAND_ORDER = ["18～19歳", "20～22歳", "23～26歳", "27～30歳", "31～34歳", "35～39歳", "40歳以上"]


def career_age_band(age: Any) -> str:
    value = int(age)
    if value <= 19: return "18～19歳"
    if value <= 22: return "20～22歳"
    if value <= 26: return "23～26歳"
    if value <= 30: return "27～30歳"
    if value <= 34: return "31～34歳"
    if value <= 39: return "35～39歳"
    return "40歳以上"


def age_band(age: int) -> str:
    """成長タイプ分布用の年齢帯。scripts/validate_ability_balance.py の AGE_BINS / AGE_LABELS と同じ区分。"""
    if age <= 19: return "18-19歳"
    if age <= 22: return "20-22歳"
    if age <= 26: return "23-26歳"
    if age <= 30: return "27-30歳"
    if age <= 34: return "31-34歳"
    return "35歳以上"


def pro_years_age_band_stats(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["年齢帯", "人数", "平均", "中央値", "最小", "最大"])
    work = df.copy()
    work["年齢帯"] = pd.Categorical(work["age"].apply(career_age_band), categories=CAREER_AGE_BAND_ORDER, ordered=True)
    stats = work.groupby("年齢帯", observed=False)["pro_years"].agg(["count", "mean", "median", "min", "max"]).reset_index()
    stats["mean"] = stats["mean"].round(2)
    return stats.rename(columns={"count": "人数", "mean": "平均", "median": "中央値", "min": "最小", "max": "最大"})


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

    career_df = df[df["entry_route"].fillna("").ne("")].copy()
    with st.expander("プロ経歴分布", expanded=False):
        if career_df.empty:
            st.info("経歴情報を持つ保存済み選手がありません。")
        else:
            career_df["年齢帯"] = pd.Categorical(career_df["age"].apply(career_age_band), categories=CAREER_AGE_BAND_ORDER, ordered=True)
            st.subheader("プロ年数分布")
            st.dataframe(career_df["pro_years"].value_counts().sort_index().rename_axis("プロ年数").reset_index(name="人数"), use_container_width=True, hide_index=True)
            st.subheader("年齢帯 × プロ年数")
            st.dataframe(pd.crosstab(career_df["年齢帯"], career_df["pro_years"]), use_container_width=True)
            career_col1, career_col2 = st.columns(2)
            with career_col1:
                st.subheader("年齢帯別プロ年数")
                st.dataframe(pro_years_age_band_stats(career_df), use_container_width=True, hide_index=True)
            with career_col2:
                st.subheader("入団経路分布")
                route_dist = career_df["entry_route"].value_counts().rename_axis("入団経路").reset_index(name="人数")
                route_dist["構成比%"] = (route_dist["人数"] / len(career_df) * 100).round(2)
                st.dataframe(route_dist, use_container_width=True, hide_index=True)
            st.subheader("入団経路 × 年齢帯")
            st.dataframe(pd.crosstab(career_df["entry_route"], career_df["年齢帯"]), use_container_width=True)

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


def inject_powerpro_ui_css() -> None:
    st.markdown("""
    <style>
    @import url("https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@700;800;900&family=Barlow+Condensed:wght@700;800&display=swap");
    .block-container {max-width:1680px; padding-top:3.5rem; padding-bottom:2rem;}
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
    div[data-testid="stButton"] > button {min-height:2.2rem;}
    button[kind="primary"], button[kind="primary"] * {color:#ffffff!important;}
    @media (max-width: 980px) {
      .pp-header {grid-template-columns:1fr;}
      .pp-face {width:100%;}
      .pp-profile-table {grid-template-columns:88px minmax(0, 1fr);}
      .pp-profile-span-3 {grid-column:span 1;}
      .pp-info {grid-template-columns:1fr;}
      .pp-body,.pp-body-pitcher {grid-template-columns:1fr; min-height:0;}
      .pp-special-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
      .pp-usage-grid {grid-template-columns:repeat(4,minmax(0,1fr));}
      .pp-defense-compact {width:100%;}
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
    /* ===== ゲーム画面寄せ（見た目のみの上書き。上の既存ルールより後に置くことで優先されます） ===== */
    div[class*="st-key-latest_detail_shell"], div[class*="st-key-history_detail_shell"] {font-family:"M PLUS Rounded 1c","Hiragino Maru Gothic ProN","Yu Gothic UI","Meiryo","Noto Sans CJK JP",sans-serif; background:#f4fbfd; border-width:5px; box-shadow:0 8px 0 rgba(0,70,120,.16), inset 0 0 0 4px #ffffff;}
    div[class*="st-key-latest_detail_shell"] .pp-value, div[class*="st-key-history_detail_shell"] .pp-value, .pp-number-box, .pp-defense-num {font-family:"Barlow Condensed","Roboto Condensed","Arial Narrow","M PLUS Rounded 1c","Noto Sans CJK JP",sans-serif;}
    /* ラベル：白いピル型 */
    .pp-label {background:linear-gradient(180deg,#ffffff 0%,#f1f5f8 100%); border:2px solid #d4dde4; border-radius:12px; box-shadow:0 2px 0 #c6d1da; color:#2a6aa9; font-weight:800; letter-spacing:.18em; margin:0 6px; padding:3px 6px;}
    /* 基礎能力行 */
    .pp-trajectory-value {color:#163b6e;}
    /* ランク文字のグラデーション（S〜G）：ゲーム画面の文字色を上・中・下で採色した値 */
    .gr-S,.gr-A,.gr-B,.gr-C,.gr-D,.gr-E,.gr-F,.gr-G {-webkit-background-clip:text; background-clip:text; color:transparent!important;}
    .gr-S {background-image:linear-gradient(180deg,#ffb3d2 0%,#ff7cb1 42%,#ff5c9f 100%);}
    .gr-A {background-image:linear-gradient(180deg,#f9a8ef 0%,#f157de 40%,#e414c9 100%);}
    .gr-B {background-image:linear-gradient(180deg,#ffa3b6 0%,#f5587b 40%,#e81236 100%);}
    .gr-C {background-image:linear-gradient(180deg,#f9c870 0%,#f19e1d 40%,#e67b16 100%);}
    .gr-D {background-image:linear-gradient(180deg,#ecec5a 0%,#cfc81a 40%,#b9a40a 100%);}
    .gr-E {background-image:linear-gradient(180deg,#95ea66 0%,#5ad814 40%,#30bb08 100%);}
    .gr-F {background-image:linear-gradient(180deg,#78d4ff 0%,#2eb0ff 40%,#1a90f5 100%);}
    .gr-G {background-image:linear-gradient(180deg,#d2d2d2 0%,#a0a0a0 40%,#818181 100%);}
    /* ヘッダー：名前プレート・背番号・顔・成績欄 */
    .pp-header {min-height:132px; gap:8px;}
    .pp-header-main {grid-template-rows:80px 44px; gap:6px;}
    .pp-name {font-size:34px; font-weight:900; color:#161616; letter-spacing:.18em; padding:0 10px 0 calc(10px + .18em); border-width:3px; box-shadow:inset 0 2px 0 rgba(255,255,255,.55), 0 2px 0 rgba(0,0,0,.18);}
    .pp-number-box {font-size:42px; font-weight:800; color:#163b6e; background:linear-gradient(180deg,#ffffff,#eef6fb); border-color:#d4e4ee;}
    .pp-category-mark {font-size:20px; color:#163b6e; border-color:#d4e4ee;}
    .pp-posline {display:flex; align-items:center; font-size:20px; color:#1b5f9e; background:linear-gradient(180deg,#ffffff,#f3f8fb); border-color:#dbe7ee; letter-spacing:.04em;}
    .pp-face {width:132px; min-width:132px; height:132px; min-height:132px; background:linear-gradient(180deg,#ffffff,#f1f8fc); border:3px solid #d4e4ee;}
    .pp-face svg {width:112px; height:112px;}
    .pp-info {grid-template-columns:minmax(0,1.35fr) minmax(0,1fr); grid-template-rows:1fr 1fr; gap:6px;}
    .pp-info .pp-chip:first-child {grid-column:1 / -1;}
    .pp-chip {display:flex; align-items:center; gap:10px; background:linear-gradient(180deg,#ffffff,#f3f8fb); border-color:#dbe7ee; color:#163b6e; font-size:24px; font-weight:900; padding:4px 8px;}
    .pp-chip.pp-chip-wide {font-size:19px; letter-spacing:-.02em;}
    .pp-chip .pp-mini-label {flex:0 0 auto; display:inline-block; margin:0; opacity:1; font-size:16px; font-weight:800; color:#2a6aa9; letter-spacing:.2em; background:linear-gradient(180deg,#ffffff 0%,#eef3f7 100%); border:2px solid #d4dde4; border-radius:11px; box-shadow:0 2px 0 #c6d1da; padding:3px 10px;}
    /* 特殊能力グリッド */
    .pp-special-grid {gap:4px;}
    .pp-special.red {background:linear-gradient(180deg,#fff2f2 0%,#ffc2c2 55%,#ff9a9a 100%); border-color:#ef6c72; color:#c8141f;}
    .pp-special.green {background:linear-gradient(180deg,#f0fff2 0%,#c6f1cf 55%,#98e0a9 100%); border-color:#47b867; color:#0b6d2f;}
    .pp-special.gold {background:linear-gradient(180deg,#fffbe0 0%,#ffe680 55%,#ffcd3a 100%); border-color:#d9a514; color:#7a5200;}
    /* 標準〜低めのランク（C〜E）は、ゲームと同じく薄く表示 */
    .pp-special-ranked.rank-cde {background:linear-gradient(180deg,#f5fcff 0%,#dcf1f8 100%); border-color:#c4e2ec; color:#6fa9c4;}
    .pp-special.empty {height:50px; background:linear-gradient(180deg,#f3fbfe 0%,#e6f6fb 100%); border-color:#d3ebf2;}
    .pp-usage-cell {min-height:50px; font-size:20px;}
    .pp-usage-label {background:linear-gradient(180deg,#ffffff 0%,#f1f5f8 100%); border-color:#d4dde4; color:#2a6aa9; box-shadow:0 2px 0 #c6d1da;}
    .pp-usage-empty {background:linear-gradient(180deg,#f3fbfe 0%,#e6f6fb 100%); border-color:#d3ebf2;}
    /* 守備・起用：守備力の枠（ラベル＋投捕一二三遊外の2列） */
    .pp-defense-compact {background:#ffffff; border:2px solid #dfe9ef; gap:0; border-radius:8px;}
    .pp-defense-label {display:flex; align-items:center; background:#ffffff; min-height:50px; border-bottom:1px solid #e3edf2;}
    .pp-defense-label .pp-label {flex:1; margin:0 8px;}
    .pp-defense-pos {grid-template-columns:34px 40px minmax(0,1fr); background:#ffffff; border-bottom:1px solid #e3edf2; min-height:50px; font-size:22px; color:#b9cbd6;}
    .pp-defense-pos:nth-child(even) {border-left:1px solid #e3edf2;}
    .pp-defense-pos.main {background:#e6f5ff; color:#163b6e;}
    .pp-defense-rank {font-size:30px; font-weight:900; filter:drop-shadow(1px 0 0 #fff) drop-shadow(-1px 0 0 #fff) drop-shadow(0 1px 0 #fff) drop-shadow(0 1px 1px rgba(0,40,80,.35));}
    .pp-defense-num {font-size:28px; font-weight:800; color:#163b6e;}
    .pp-defense-empty {color:#c3d3dc;}
    /* タブ：非選択もタブごとの暗い色にする */
    div[class*="st-key-latest_tab_"] button[kind="secondary"], div[class*="st-key-history_tab_"] button[kind="secondary"] {font-size:20px;}
    div[class*="st-key-latest_tab_"] button, div[class*="st-key-history_tab_"] button {font-size:20px; letter-spacing:.06em;}
    div[class*="st-key-latest_tab_pitcher"] button[kind="secondary"], div[class*="st-key-history_tab_pitcher"] button[kind="secondary"] {background:#6f1024!important; border-color:#560b1b!important;}
    div[class*="st-key-latest_tab_fielder"] button[kind="secondary"], div[class*="st-key-history_tab_fielder"] button[kind="secondary"] {background:#0b3a78!important; border-color:#082c5c!important;}
    div[class*="st-key-latest_tab_usage"] button[kind="secondary"], div[class*="st-key-history_tab_usage"] button[kind="secondary"] {background:#6b4a06!important; border-color:#553a03!important;}
    div[class*="st-key-latest_tab_profile"] button[kind="secondary"], div[class*="st-key-history_tab_profile"] button[kind="secondary"] {background:#0c4d1c!important; border-color:#083a14!important;}
    div[class*="st-key-latest_tab_"] button[kind="secondary"] *, div[class*="st-key-history_tab_"] button[kind="secondary"] * {color:rgba(255,255,255,.6)!important;}
    /* プロフィール表：ラベル折り返し防止、全幅項目は必ず行頭から、文字サイズを他の欄に合わせる */
    .pp-profile-table {border-color:#dfe9ef; border-radius:8px;}
    @media (min-width: 981px) {.pp-profile-table {grid-template-columns:130px minmax(0,1fr) 130px minmax(0,1fr);}}
    .pp-profile-label {white-space:nowrap; font-size:16px; letter-spacing:.02em; color:#2a6aa9; min-height:48px;}
    .pp-profile-label:has(+ .pp-profile-span-3) {grid-column-start:1;}
    .pp-profile-value {font-size:20px; color:#163b6e; min-height:48px;}
    .pp-generation-info summary {color:#1b5f9e; font-weight:800; cursor:pointer; margin-top:8px;}
    /* 基礎能力行：ランクと数値を枠の縦中央にそろえる */
    .pp-ability-row {height:50px; min-height:50px; grid-template-columns:minmax(110px,40%) 58px 1fr; background:linear-gradient(180deg,#ffffff 0%,#f6fafc 100%); border:2px solid #dfe9ef; border-radius:8px; margin:4px 0;}
    .pp-ability-row > div {align-self:stretch; display:flex; align-items:center; min-height:0;}
    .pp-ability-row > .pp-label {align-self:center; display:block;}
    .pp-rank {justify-content:center; font-size:34px; line-height:1; font-weight:900; width:52px; -webkit-text-stroke:0; text-shadow:none; filter:drop-shadow(1.5px 0 0 #fff) drop-shadow(-1.5px 0 0 #fff) drop-shadow(0 1.5px 0 #fff) drop-shadow(0 -1.5px 0 #fff) drop-shadow(0 2px 1px rgba(0,40,80,.35));}
    .pp-value {justify-content:flex-end; font-size:36px; line-height:1; font-weight:800; color:#163b6e; letter-spacing:.01em; font-variant-numeric:tabular-nums;}
    /* 特殊能力：セル幅÷文字数で文字を大きく表示（ゲームと同じくセルいっぱいに文字が並ぶ） */
    .pp-special {container-type:inline-size; height:50px; padding:0 4px; font-weight:800; color:#1276bd; border-radius:6px; background:linear-gradient(180deg,#f2feff 0%,#bff1f7 55%,#8fe0ec 100%);}
    .pp-special .pp-special-name, .pp-special.long .pp-special-name, .pp-special.xlong .pp-special-name {display:block; width:100%; text-align:center; white-space:nowrap; overflow:visible; line-height:1; letter-spacing:0; text-indent:0; padding:0; font-size:min(30px, calc((100cqw - 4px) / var(--n, 4)));}
    .pp-special.sp2 .pp-special-name {letter-spacing:.9em; text-indent:.9em;}
    .pp-special.sp3 .pp-special-name {letter-spacing:.45em; text-indent:.45em;}
    .pp-special-ranked {grid-template-columns:minmax(0,1fr) 32px; padding:0 2px 0 4px;}
    .pp-special-ranked .pp-special-name, .pp-special-ranked.long .pp-special-name, .pp-special-ranked.xlong .pp-special-name {align-self:center; font-size:min(30px, calc((100cqw - 40px) / var(--n, 4)));}
    /* ランク文字：C〜Eは白フチ付きの縁取り文字、A・Bは青、F・Gは赤の四角に白文字 */
    .pp-special-rank-badge {width:32px; height:40px; margin:0; align-self:center; font-size:34px; line-height:1; font-weight:900; border-radius:5px; background:transparent; text-shadow:none;}
    .pp-special-ranked.rank-cde .pp-special-rank-badge {background:transparent; color:#8cc3db; filter:drop-shadow(1.5px 0 0 #fff) drop-shadow(-1.5px 0 0 #fff) drop-shadow(0 1.5px 0 #fff) drop-shadow(0 -1.5px 0 #fff) drop-shadow(0 0 1px #5d9dbb);}
    .pp-special-ranked.rank-ab .pp-special-rank-badge {background:linear-gradient(180deg,#2f8fe0 0%,#1057b0 100%); color:#fff; font-size:26px; height:38px; width:30px;}
    .pp-special-ranked.rank-fg .pp-special-rank-badge {background:linear-gradient(180deg,#ff5a60 0%,#c8161f 100%); color:#fff; font-size:26px; height:38px; width:30px;}
    /* タブ文字・起用適性行 */
    div[class*="st-key-latest_tab_"] button p, div[class*="st-key-history_tab_"] button p {font-size:22px!important; font-weight:900!important; letter-spacing:.08em;}
    .pp-pitcher-usage-row {min-height:50px;}
    .pp-pitcher-usage-values {font-size:24px; color:#163b6e;}
    /* フォント統一：Streamlitのmarkdown既定フォント（Source Sans）に上書きされないよう、詳細パネル内は!importantで指定 */
    div[class*="st-key-latest_detail_shell"], div[class*="st-key-history_detail_shell"] {--pp-font:"M PLUS Rounded 1c","Hiragino Maru Gothic ProN","Yu Gothic UI","Meiryo","Noto Sans CJK JP",sans-serif; --pp-num-font:"Barlow Condensed","Roboto Condensed","Arial Narrow","M PLUS Rounded 1c","Noto Sans CJK JP",sans-serif;}
    div[class*="st-key-latest_detail_shell"] :is(div,span,p,summary,button,text), div[class*="st-key-history_detail_shell"] :is(div,span,p,summary,button,text) {font-family:var(--pp-font)!important;}
    div[class*="st-key-latest_detail_shell"] :is(.pp-value,.pp-value *,.pp-number-box,.pp-defense-num,.pp-chip), div[class*="st-key-history_detail_shell"] :is(.pp-value,.pp-value *,.pp-number-box,.pp-defense-num,.pp-chip) {font-family:var(--pp-num-font)!important;}
    div[class*="st-key-latest_detail_shell"] .pp-chip .pp-mini-label, div[class*="st-key-history_detail_shell"] .pp-chip .pp-mini-label {font-family:var(--pp-font)!important;}
    /* ===== 実画面（M PLUS Rounded 1c）での表示バランス調整 ===== */
    /* 基礎能力行：ラベル・ランク・数値をゲームと同じ比率で大きく（ランクは行の中央寄り、数値は右端から少し内側） */
    .pp-ability-row {height:54px; min-height:54px; grid-template-columns:minmax(0,43%) minmax(0,17%) 1fr;}
    .pp-ability-row .pp-label {font-size:21px; letter-spacing:.2em; padding:4px 4px 4px calc(4px + .2em); margin:0 8px;}
    .pp-rank {width:auto; font-size:44px;}
    .pp-value {font-size:46px; padding-right:14%;}
    .pp-speed-row {grid-template-columns:minmax(0,43%) 0 1fr;}
    .pp-speed-row .pp-value {justify-content:flex-start; align-items:baseline; padding:0 0 0 6%; gap:6px; line-height:54px;}
    .pp-speed-row .pp-unit {font-size:24px;}
    .pp-trajectory-icon svg {width:60px; height:38px;}
    /* ヘッダー：守備位置・適性をラベルピル＋大きな値に */
    .pp-posline {gap:14px; padding:4px 8px; overflow:visible;}
    .pp-posline .pp-mini-label {flex:0 0 auto; display:inline-block; margin:0; opacity:1; font-size:16px; font-weight:800; color:#2a6aa9; letter-spacing:.2em; background:linear-gradient(180deg,#ffffff 0%,#eef3f7 100%); border:2px solid #d4dde4; border-radius:11px; box-shadow:0 2px 0 #c6d1da; padding:3px 10px;}
    .pp-pos-values {display:inline-flex; align-items:baseline; gap:10px; color:#1b5f9e; font-weight:900;}
    .pp-pos-item.main, .pp-pos-item.lv3 {font-size:30px;}
    .pp-pos-item.lv2 {font-size:24px;}
    .pp-pos-item.sub, .pp-pos-item.lv1 {font-size:20px;}
    .pp-chip {font-size:30px;}
    .pp-chip.pp-chip-wide {font-size:24px;}
    /* 特殊能力：文字をさらに大きく（上限36px）、薄い表示は水色＋縁取り */
    .pp-special .pp-special-name, .pp-special.long .pp-special-name, .pp-special.xlong .pp-special-name {font-size:min(36px, calc((100cqw - 4px) / var(--n, 4)));}
    .pp-special-ranked .pp-special-name, .pp-special-ranked.long .pp-special-name, .pp-special-ranked.xlong .pp-special-name {font-size:min(36px, calc((100cqw - 44px) / var(--n, 4)));}
    .pp-special, .pp-special.empty {height:54px;}
    .pp-special-ranked.rank-cde {color:#7dbde2;}
    .pp-special-ranked.rank-cde .pp-special-name {filter:drop-shadow(1px 0 0 #fff) drop-shadow(-1px 0 0 #fff) drop-shadow(0 1px 0 #fff) drop-shadow(0 -1px 0 #fff);}
    .pp-special-rank-badge {font-size:38px;}
    .pp-special-ranked.rank-cde .pp-special-rank-badge {color:#a9d8f0; filter:drop-shadow(1.5px 0 0 #fff) drop-shadow(-1.5px 0 0 #fff) drop-shadow(0 1.5px 0 #fff) drop-shadow(0 -1.5px 0 #fff) drop-shadow(1px 0 0 #2f6f98) drop-shadow(-1px 0 0 #2f6f98) drop-shadow(0 1px 0 #2f6f98) drop-shadow(0 -1px 0 #2f6f98);}
    .pp-special-ranked.rank-ab .pp-special-rank-badge, .pp-special-ranked.rank-fg .pp-special-rank-badge {font-size:30px; height:42px;}
    /* 守備・起用：守備力の枠と起用欄も同じ文字サイズ感に */
    .pp-defense-label, .pp-defense-pos {min-height:56px;}
    .pp-defense-pos {font-size:26px;}
    .pp-defense-rank {font-size:38px; line-height:1;}
    .pp-defense-num {font-size:36px; line-height:1;}
    .pp-usage-cell {min-height:54px; font-size:24px;}
    /* 守れないポジションは位置の文字も薄く（ゲームと同じ）、守れるポジションだけ濃く */
    .pp-defense-pos .pp-defense-short {color:#c3d3dc;}
    .pp-defense-pos:has(.pp-defense-rank) .pp-defense-short {color:#163b6e;}
    /* 変化球の図：ゲームと同じく左列の幅いっぱいに表示 */
    .pp-chart-wrap {width:100%; height:auto; min-height:0; max-height:none; aspect-ratio:280 / 210; margin-top:6px;}
    .pp-chart-wrap svg {display:block; width:100%; height:100%;}
    /* ===== ランク付き特殊能力：右側の帯（上下につながる）＋白抜きのランク文字 ===== */
    .pp-special-ranked {--strip:#a8dcf2; background:var(--strip); border:0; border-radius:6px; padding:3px 0 3px 3px; grid-template-columns:minmax(0,1fr) 34px; box-shadow:none; color:#86c9ec;}
    .pp-special-ranked.rank-ab {--strip:#14a0cf;}
    .pp-special-ranked.rank-fg {--strip:#e4575e;}
    .pp-special-ranked .pp-special-name, .pp-special-ranked.long .pp-special-name, .pp-special-ranked.xlong .pp-special-name {height:100%; line-height:48px; border-radius:5px; background:linear-gradient(180deg,#f5fcff 0%,#e3f5fc 48%,#d3eef9 52%,#e6f6fc 100%); box-shadow:inset 0 0 0 1px rgba(255,255,255,.9); filter:none; font-size:min(36px, calc((100cqw - 44px) / var(--n, 4)));}
    .pp-special-ranked.rank-cde .pp-special-name {color:#86c9ec; filter:none;}
    .pp-special-ranked.rank-ab .pp-special-name {color:#0d4f9e; background:linear-gradient(180deg,#effdff 0%,#c3f2fd 48%,#a4e9fb 52%,#c9f4fd 100%);}
    .pp-special-ranked.rank-fg .pp-special-name {color:#d0121b; background:linear-gradient(180deg,#fff4f4 0%,#ffd6d6 48%,#ffc2c2 52%,#ffd9d9 100%);}
    .pp-special-rank-badge, .pp-special-ranked.rank-cde .pp-special-rank-badge, .pp-special-ranked.rank-ab .pp-special-rank-badge, .pp-special-ranked.rank-fg .pp-special-rank-badge {width:34px; height:100%; margin:0; border-radius:0; background:transparent; color:#ffffff; font-size:36px; line-height:1; font-weight:900; align-self:stretch; display:flex; align-items:center; justify-content:center;}
    .pp-special-ranked.rank-cde .pp-special-rank-badge {filter:drop-shadow(1.5px 0 0 #3f7690) drop-shadow(-1.5px 0 0 #3f7690) drop-shadow(0 1.5px 0 #3f7690) drop-shadow(0 -1.5px 0 #3f7690);}
    .pp-special-ranked.rank-ab .pp-special-rank-badge {filter:drop-shadow(1.5px 0 0 #0a3f63) drop-shadow(-1.5px 0 0 #0a3f63) drop-shadow(0 1.5px 0 #0a3f63) drop-shadow(0 -1.5px 0 #0a3f63);}
    .pp-special-ranked.rank-fg .pp-special-rank-badge {filter:drop-shadow(1.5px 0 0 #8c0f17) drop-shadow(-1.5px 0 0 #8c0f17) drop-shadow(0 1.5px 0 #8c0f17) drop-shadow(0 -1.5px 0 #8c0f17);}
    .pp-special.pp-special-ranked.rank-cde, .pp-special.pp-special-ranked.rank-ab, .pp-special.pp-special-ranked.rank-fg {background:var(--strip); border:0; border-color:transparent;}
    /* 1段目と2段目の帯を、間のすき間ごと上下につなげる */
    .pp-special-grid > .pp-special-ranked:nth-child(-n+4) {border-bottom-left-radius:0; border-bottom-right-radius:0; box-shadow:0 4px 0 0 var(--strip);}
    .pp-special-grid > .pp-special-ranked:nth-child(n+5):nth-child(-n+8) {border-top-left-radius:0; border-top-right-radius:0;}
    /* 弾道の矢印：ランク文字と同じ列の中央に、行の高さ内で回転 */
    .pp-trajectory-row .pp-trajectory-icon {width:auto; justify-content:center; overflow:visible;}
    .pp-trajectory-icon svg, .pp-trajectory-icon.trajectory-1 svg, .pp-trajectory-icon.trajectory-2 svg, .pp-trajectory-icon.trajectory-3 svg, .pp-trajectory-icon.trajectory-4 svg {width:42px; height:42px; transform-origin:50% 50%;}
    .pp-trajectory-icon.trajectory-1 svg {transform:rotate(0deg);}
    .pp-trajectory-icon.trajectory-2 svg {transform:rotate(-22deg);}
    .pp-trajectory-icon.trajectory-3 svg {transform:rotate(-45deg);}
    .pp-trajectory-icon.trajectory-4 svg {transform:rotate(-65deg);}
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

def ui_rank_class(rank_text: str) -> str:
    # ゲーム風グラデーション文字用のクラス。色の定義はCSS側（.gr-S〜.gr-G）にあります。
    return f"gr-{rank_text}" if rank_text in {"S", "A", "B", "C", "D", "E", "F", "G"} else ""


def render_ability_rows(items: list[tuple[str, Any]]) -> str:
    rows = []
    for label, item in items:
        if isinstance(item, dict):
            rank_text = e(item.get("rank", "-"))
            value = e(item.get("value", "-"))
            color = ui_rank_color(str(item.get("rank", "")))
            rank_cls = ui_rank_class(str(item.get("rank", "")))
        else:
            rank_text = ""
            value = e(item)
            color = "#cbd5e1"
            rank_cls = ""
        rank_class_attr = f"pp-rank {rank_cls}".strip()
        row_class = "pp-ability-row"
        speed_match = re.fullmatch(r"(\d+)\s*km/h", str(item)) if not isinstance(item, dict) else None
        if speed_match:
            # 球速はゲームと同じく数字を大きく、km/h を小さく、ラベルのすぐ右に表示します。
            row_class += " pp-speed-row"
            value = f'{e(speed_match.group(1))}<span class="pp-unit">km/h</span>'
        rows.append(f'<div class="{row_class}"><div class="pp-label">{e(label)}</div><div class="{rank_class_attr}" style="color:{color}">{rank_text}</div><div class="pp-value">{value}</div></div>')
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
        '<svg viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">'
        '<g filter="drop-shadow(0 1px 1px rgba(0,0,0,.3))">'
        # ゲームと同じ太いブロック矢印。白フチ→色の順に重ね、回転はCSSで中心を軸に行います。
        '<polygon points="5,14 19,14 19,6 36,20 19,34 19,26 5,26" fill="#ffffff" stroke="#ffffff" stroke-width="5" stroke-linejoin="round"/>'
        f'<polygon points="5,14 19,14 19,6 36,20 19,34 19,26 5,26" fill="{color}" stroke="{color}" stroke-width="1" stroke-linejoin="round"/>'
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
    # ゲームでは文字がセル幅いっぱいに大きく表示され、2〜3文字の能力（盗塁・逆境○など）だけ字間が空きます。
    # 文字数を --n としてCSSに渡し、セル幅÷文字数で文字サイズを決めます。
    char_count = max(1, len(base_name))
    spread_cls = "sp2" if char_count <= 2 else "sp3" if char_count == 3 else ""
    if rank_text:
        classes = " ".join(part for part in ["pp-special", "pp-special-ranked", special_rank_class(rank_text), length_cls, spread_cls] if part)
        return f'<div class="{classes}" title="{e(name)}"><span class="pp-special-name" style="--n:{char_count}">{e(base_name)}</span><span class="pp-special-rank-badge">{e(rank_text)}</span></div>'
    cls = "gold" if kind == "gold" else "red" if kind == "red" else "green" if kind == "green" else "neutral" if kind == "neutral" else "mixed" if kind == "mixed" else ""
    classes = " ".join(part for part in ["pp-special", cls, length_cls, spread_cls] if part)
    return f'<div class="{classes}" title="{e(name)}"><span class="pp-special-name" style="--n:{char_count}">{e(base_name)}</span></div>'


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
    # 表示順リストにない能力はリストの後ろに置き、その中では従来の順序を保つ。
    if mode == "usage":
        entries.sort(key=lambda item: (usage_priority.get(item[0], 99), item[0]))
    else:
        entries.sort(key=lambda item: order.get(item[1], 9))
    unlisted = len(SPECIAL_ABILITY_DISPLAY_ORDER)
    return sorted(entries, key=lambda item: SPECIAL_ABILITY_DISPLAY_INDEX.get(item[0], unlisted))


def special_grid_cell_count(base_cell_count: int, fixed_slot_count: int, normal_count: int) -> int:
    required = fixed_slot_count + normal_count
    return max(base_cell_count, math.ceil(required / 4) * 4)


def render_special_grid_html(p: dict[str, Any], master: MasterData, mode: str = "fielder", cell_count: int | None = None) -> str:
    base_cell_count = cell_count or (16 if mode == "usage" else 32)
    fixed_slots = fixed_rank_slots(p, mode) if mode in ("pitcher", "fielder") else []
    display_entries = collect_special_entries(p, master, mode)
    actual_cell_count = special_grid_cell_count(base_cell_count, len(fixed_slots), len(display_entries))
    # ランク付き特殊能力の固定枠は、空き枠でも右側の帯が上下につながるよう専用の空セルにします。
    empty_ranked = '<div class="pp-special pp-special-ranked rank-cde rank-empty"><span class="pp-special-name"></span><span class="pp-special-rank-badge"></span></div>'
    cells: list[str] = [special_cell_html(name) if name else empty_ranked for name in fixed_slots]
    cells.extend(special_cell_html(name, kind) for name, kind in display_entries)
    while len(cells) < actual_cell_count:
        cells.append(special_cell_html(None))
    return '<div class="pp-special-grid">' + "".join(cells) + "</div>"

def pitch_display_name(name: Any) -> str:
    return str(name or "")


def pitch_label_text(name: Any) -> str:
    # 英数字は全角にして字間を空ける（例：SFF → ＳＦＦ）。長い名前は省略せず描画時に横圧縮する。
    return "".join(
        chr(ord(ch) + 0xFEE0) if ch.isascii() and ch.isalnum() else ch
        for ch in pitch_display_name(name)
    )


def estimate_pitch_label_width(text: str, font_size: float) -> float:
    return sum(
        font_size if unicodedata.east_asian_width(ch) in {"W", "F", "A"} else font_size * 0.55
        for ch in text
    )


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
                display_name=pitch_label_text(name),
                movement=normalize_pitch_movement(ball),
                is_left=is_left,
            ))
    return lanes


PitchPoint = tuple[float, float]


@dataclass(frozen=True)
class PitchBarShape:
    direction_code: str
    lane_index: int
    paired: bool
    movement: int
    frame: tuple[PitchPoint, ...]
    cells: tuple[tuple[PitchPoint, ...], ...]


@dataclass(frozen=True)
class PitchChartLabel:
    kind: str  # "pitch" / "straight" / "second"
    text: str
    x: float
    y: float  # ベースライン
    anchor: str
    width: float
    natural_width: float
    direction_code: str = ""
    lane_index: int = 0

    @property
    def compressed(self) -> bool:
        return self.width < self.natural_width - 0.01

    def rect(self) -> tuple[float, float, float, float]:
        return pitch_label_rect(self.x, self.y, self.anchor, self.width)


@dataclass(frozen=True)
class PitchChartLayout:
    is_left: bool
    bars: tuple[PitchBarShape, ...]
    straight_frame: tuple[PitchPoint, ...]
    straight_fills: tuple[tuple[PitchPoint, ...], ...]
    labels: tuple[PitchChartLabel, ...]


def _pitch_font_metrics() -> tuple[float, float, float]:
    font_size = PITCH_LABEL_FONT_SIZE * PITCH_CHART_UNIT
    return font_size, font_size * 0.88, font_size * 0.12


def pitch_label_rect(x: float, baseline: float, anchor: str, width: float) -> tuple[float, float, float, float]:
    _font_size, ascent, descent = _pitch_font_metrics()
    left = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
    return left, baseline - ascent, left + width, baseline + descent


def _mirror_pitch_points(points: tuple[PitchPoint, ...]) -> tuple[PitchPoint, ...]:
    return tuple((PITCH_CHART_WIDTH - x, y) for x, y in points)


def _mix_hex(start: str, end: str, t: float) -> str:
    a = [int(start[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(end[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def pitch_cell_color(index: int, active: bool) -> str:
    if active:
        return PITCH_CELL_ACTIVE_COLORS[index]
    return _mix_hex(PITCH_CELL_EMPTY_START, PITCH_CELL_EMPTY_END, index / (PITCH_GAUGE_SEGMENT_COUNT - 1))


def pitch_bar_half_width(paired: bool) -> float:
    """バー（2列なら2列合わせたフレーム）の半幅（u）。"""
    return (PITCH_PAIRED_THICKNESS if paired else PITCH_SINGLE_THICKNESS) / 2


def diagonal_bar_start(direction_code: str, paired_directions: set[str] | frozenset[str] = frozenset()) -> float:
    """斜めバーの根元の位置（ボール中心からの距離, u）。2列時は両方の列が同じ位置から始まる。
    根元の角が隣の横バー・フォークバーに食い込まないよう、自分と隣の太さに応じて外へ下げる。"""
    geometry = PITCH_GAUGE_GEOMETRY[direction_code]
    if geometry["kind"] != "diagonal":
        return PITCH_BAR_START
    side_code = "1" if geometry["axis"][0] > 0 else "5"
    paired = direction_code in paired_directions
    own = pitch_bar_half_width(paired)
    side_half = pitch_bar_half_width(side_code in paired_directions)
    fork_half = pitch_bar_half_width("3" in paired_directions)
    sin45 = math.sqrt(0.5)
    # 根元の角は軸から own だけ横バー側・フォーク側へ張り出す
    need_side = own + (side_half + PITCH_BAR_CLEARANCE) / sin45
    need_fork = own + (fork_half + PITCH_BAR_CLEARANCE) / sin45
    return max(PITCH_BAR_START, need_side, need_fork)


def pitch_bar_shape(
    direction_code: str, lane_index: int = 0, paired: bool = False, movement: int = 0, flip_side: bool = False,
    start_u: float | None = None,
) -> PitchBarShape:
    """右投げ基準の座標でバー1列（フレーム＋7セル）を作る。2列時は列ごとに呼ぶ。
    flip_side は2列の並び順を入れ替える（左投げのフォーク方向を、反転後も1球種目が左になるようにする）。"""
    u = PITCH_CHART_UNIT
    geometry = PITCH_GAUGE_GEOMETRY[direction_code]
    ax, ay = geometry["axis"]
    nx, ny = geometry["lane_side"]
    if flip_side:
        nx, ny = -nx, -ny
    cx, cy = PITCH_CHART_CENTER
    if paired:
        border = PITCH_PAIRED_BORDER * u
        # 2列は中央の仕切りを共有するので、列フレーム2本を仕切り1本分重ねる
        half = (PITCH_PAIRED_THICKNESS * u + border) / 4
        cross_center = PITCH_PAIRED_THICKNESS * u / 2 - half
        if lane_index >= 1:
            cross_center = -cross_center
    else:
        border = PITCH_SINGLE_BORDER * u
        half = PITCH_SINGLE_THICKNESS * u / 2
        cross_center = 0.0
    start = (PITCH_BAR_START if start_u is None else start_u) * u

    def point(along: float, cross: float) -> PitchPoint:
        a = start + along
        c = cross_center + cross
        return (round(cx + ax * a + nx * c, 2), round(cy + ay * a + ny * c, 2))

    length = PITCH_BAR_LENGTH * u
    frame = tuple(point(a, c) for a, c in (
        (0, -half), (length - half, -half), (length, 0), (length - half, half), (0, half),
    ))
    inner = half - border
    cells = []
    for index in range(PITCH_GAUGE_SEGMENT_COUNT):
        a0 = PITCH_CELL_DIVIDER * u + index * PITCH_CELL_PITCH * u
        if index < PITCH_GAUGE_SEGMENT_COUNT - 1:
            a1 = a0 + PITCH_CELL_LENGTH * u
            local = ((a0, -inner), (a1, -inner), (a1, inner), (a0, inner))
        else:
            # 最外セルは矢じりの中に収まる五角形
            apex = length - border * math.sqrt(2)
            flat = apex - inner
            local = ((a0, -inner), (flat, -inner), (apex, 0), (flat, inner), (a0, inner))
        cells.append(tuple(point(a, c) for a, c in local))
    return PitchBarShape(direction_code, lane_index, paired, movement, frame, tuple(cells))


def _pitch_straight_shapes(count: int) -> tuple[tuple[PitchPoint, ...], tuple[tuple[PitchPoint, ...], ...]]:
    u = PITCH_CHART_UNIT
    cx, cy = PITCH_CHART_CENTER
    bottom = cy - 1.05 * u - 0.25 * u
    top = bottom - 1.55 * u
    if count <= 1:
        half = 0.625 * u
        frame = ((cx, top), (cx + half, top + half), (cx + half, bottom), (cx - half, bottom), (cx - half, top + half))
        inset = 0.18 * u
        fill_half = half - inset
        apex = top + 0.25 * u
        fills = (((cx, apex), (cx + fill_half, apex + fill_half), (cx + fill_half, bottom - inset),
                  (cx - fill_half, bottom - inset), (cx - fill_half, apex + fill_half)),)
    else:
        # ストレート系2球種：五角形2つを横に連結した形
        half = 0.9 * u
        peak = 0.45 * u
        frame = ((cx - half, bottom), (cx - half, top + peak), (cx - peak, top), (cx, top + peak),
                 (cx + peak, top), (cx + half, top + peak), (cx + half, bottom))
        fill_half = 0.33 * u
        apex = top + 0.2 * u
        fills = tuple(
            ((px, apex), (px + fill_half, apex + fill_half), (px + fill_half, bottom - 0.15 * u),
             (px - fill_half, bottom - 0.15 * u), (px - fill_half, apex + fill_half))
            for px in (cx - peak, cx + peak)
        )
    return tuple((round(x, 2), round(y, 2)) for x, y in frame), tuple(
        tuple((round(x, 2), round(y, 2)) for x, y in fill) for fill in fills
    )


def _convex_polygons_overlap(first: tuple[PitchPoint, ...], second: tuple[PitchPoint, ...]) -> bool:
    # 分離軸判定（凸多角形同士）
    for polygon in (first, second):
        count = len(polygon)
        for index in range(count):
            x1, y1 = polygon[index]
            x2, y2 = polygon[(index + 1) % count]
            nx, ny = y1 - y2, x2 - x1
            if nx == 0 and ny == 0:
                continue
            p1 = [nx * x + ny * y for x, y in first]
            p2 = [nx * x + ny * y for x, y in second]
            if max(p1) <= min(p2) or max(p2) <= min(p1):
                return False
    return True


def _rect_polygon(rect: tuple[float, float, float, float], pad: float = 0.0) -> tuple[PitchPoint, ...]:
    x0, y0, x1, y1 = rect
    return ((x0 - pad, y0 - pad), (x1 + pad, y0 - pad), (x1 + pad, y1 + pad), (x0 - pad, y1 + pad))


def _fit_pitch_label_width(
    x: float, baseline: float, anchor: str, target: float, obstacles: list[tuple[PitchPoint, ...]],
) -> float:
    margin = 6.0
    _font_size, ascent, descent = _pitch_font_metrics()
    if baseline - ascent < margin or baseline + descent > PITCH_CHART_HEIGHT - margin:
        return 0.0
    right_room = PITCH_CHART_WIDTH - margin - x
    left_room = x - margin
    bound = left_room if anchor == "end" else right_room if anchor == "start" else 2 * min(left_room, right_room)
    upper = min(target, bound)
    if upper <= 0:
        return 0.0

    def fits(width: float) -> bool:
        polygon = _rect_polygon(pitch_label_rect(x, baseline, anchor, width), 1.5)
        return not any(_convex_polygons_overlap(polygon, obstacle) for obstacle in obstacles)

    if fits(upper):
        return upper
    if not fits(0.0):
        return 0.0
    lower = 0.0
    for _ in range(18):
        middle = (lower + upper) / 2
        if fits(middle):
            lower = middle
        else:
            upper = middle
    return lower


def _pitch_label_candidates(bar: PitchBarShape) -> list[tuple[float, float, str, float]]:
    """ラベル候補を優先順に返す（右投げ基準）。(x, ベースライン, text-anchor, 最大幅)"""
    u = PITCH_CHART_UNIT
    pad = 0.25 * u
    font_size, ascent, descent = _pitch_font_metrics()
    line = font_size * 1.1
    max_width = PITCH_LABEL_MAX_WIDTH * u
    geometry = PITCH_GAUGE_GEOMETRY[bar.direction_code]
    kind = geometry["kind"]
    outward = 1 if geometry["axis"][0] > 0 else -1
    xs = [x for x, _y in bar.frame]
    ys = [y for _x, y in bar.frame]
    cx = PITCH_CHART_CENTER[0]
    below = max(ys) + pad + ascent
    if kind == "side":
        # 横方向：1球種目はバーの上、2球種目はバーの下。バー外寄りの位置に中央揃え。
        # 混んでいるときは内側へずらし、それでも無理なら1段外へ逃がす
        center_x = cx + outward * PITCH_SIDE_LABEL_CENTER * u
        if bar.lane_index == 0:
            rows = [min(ys) - pad - descent, min(ys) - pad - descent - line]
        else:
            rows = [below, below + line]
        return [
            (center_x - outward * shift * u, row, "middle", max_width)
            for row in rows for shift in (0, 1, 2, 3)
        ]
    if kind == "down":
        if not bar.paired:
            return [(cx, below, "middle", max_width)]
        # 2球種：先端の左下／右下（列の位置に合わせる）
        lane_x = sum(xs) / len(xs)
        if lane_x < cx:
            return [(cx - PITCH_DOWN_LABEL_OFFSET * u, below, "end", max_width)]
        return [(cx + PITCH_DOWN_LABEL_OFFSET * u, below, "start", max_width)]
    # 斜め方向：先端の下に中央揃え。フォーク側と重なるときは外側へずらす
    center_x = cx + outward * PITCH_DIAGONAL_LABEL_CENTER * u
    below_candidates = [
        (center_x + outward * shift * u, row, "middle", max_width)
        for row in (below, below + line) for shift in (0, 1, 2, 3, 4)
    ]
    if not (bar.paired and bar.lane_index == 0):
        return below_candidates
    # 2球種時の1球種目：バーの外側・中ほど。混んでいる場合は先端側へずらす
    ax, ay = geometry["axis"]
    nx, ny = geometry["lane_side"]
    frame_start_x = (bar.frame[0][0] + bar.frame[4][0]) / 2
    frame_start_y = (bar.frame[0][1] + bar.frame[4][1]) / 2
    half = math.dist(bar.frame[0], bar.frame[4]) / 2
    side_anchor = "start" if outward > 0 else "end"
    candidates = []
    # 先端の下は2球種目の場所なので使わない
    for along in (3.75, 4.75, 5.75, 2.75):
        mx = frame_start_x + ax * along * u + nx * (half + pad)
        my = frame_start_y + ay * along * u + ny * (half + pad)
        candidates.append((mx, my - descent, side_anchor, max_width))
    return candidates


def _place_pitch_label(
    lane: PitchChartLane, bar: PitchBarShape, obstacles: list[tuple[PitchPoint, ...]],
) -> PitchChartLabel:
    font_size, _ascent, _descent = _pitch_font_metrics()
    natural = estimate_pitch_label_width(lane.display_name, font_size)
    best: tuple[float, tuple[float, float, str, float], float] | None = None
    for candidate in _pitch_label_candidates(bar):
        x, baseline, anchor, max_width = candidate
        target = min(natural, max_width)
        if anchor == "middle":
            # 中央揃えのラベルは、はみ出す分だけ内側へ寄せる（見切れ防止）
            margin = 6.0
            x = min(max(x, margin + target / 2), PITCH_CHART_WIDTH - margin - target / 2)
            candidate = (x, baseline, anchor, max_width)
        width = _fit_pitch_label_width(x, baseline, anchor, target, obstacles)
        # 優先位置で9割以上収まるなら、そこで少し圧縮して使う
        if width >= target * 0.9 - 0.01:
            best = (1.0, candidate, width)
            break
        ratio = width / target if target else 0.0
        if best is None or ratio > best[0]:
            best = (ratio, candidate, width)
    assert best is not None
    _ratio, (x, baseline, anchor, _max_width), width = best
    return PitchChartLabel(
        "pitch", lane.display_name, round(x, 2), round(baseline, 2), anchor, round(width, 2), round(natural, 2),
        lane.direction_code, lane.lane_index,
    )


def _straight_labels(second_fastballs: list[dict[str, Any]], straight_top: float) -> list[PitchChartLabel]:
    u = PITCH_CHART_UNIT
    font_size, _ascent, descent = _pitch_font_metrics()
    cx = PITCH_CHART_CENTER[0]
    baseline = round(straight_top - 0.25 * u - descent, 2)
    first = "ストレート"
    if not second_fastballs:
        width = estimate_pitch_label_width(first, font_size)
        return [PitchChartLabel("straight", first, cx, baseline, "middle", width, width)]
    second = pitch_label_text(second_fastballs[0].get("name"))
    labels = []
    # 実機：「ストレート」は五角形の左上、2球種目は右上
    for kind, text, x, anchor in (("straight", first, cx - 1.5 * u, "end"), ("second", second, cx + 0.9 * u, "start")):
        natural = estimate_pitch_label_width(text, font_size)
        width = min(natural, PITCH_LABEL_MAX_WIDTH * u)
        labels.append(PitchChartLabel(kind, text, round(x, 2), baseline, anchor, round(width, 2), round(natural, 2)))
    return labels


def _mirror_pitch_label(label: PitchChartLabel) -> PitchChartLabel:
    anchor = {"start": "end", "end": "start"}.get(label.anchor, label.anchor)
    return PitchChartLabel(
        label.kind, label.text, round(PITCH_CHART_WIDTH - label.x, 2), label.y, anchor,
        label.width, label.natural_width, label.direction_code, label.lane_index,
    )


def layout_pitch_chart(balls: list[dict[str, Any]] | None, batting_throwing: str = "") -> PitchChartLayout:
    is_left = str(batting_throwing).startswith("左投")
    balls = balls or []
    second_fastballs = [ball for ball in balls if ball.get("kind") == "second_fastball"]
    lanes = build_pitch_chart_lanes(balls, is_left)
    paired_directions = {lane.direction_code for lane in lanes if lane.lane_index == 1}
    lane_by_key = {(lane.direction_code, lane.lane_index): lane for lane in lanes}

    bars: list[PitchBarShape] = []
    for code in PITCH_GAUGE_GEOMETRY:
        paired = code in paired_directions
        for lane_index in ((0, 1) if paired else (0,)):
            lane = lane_by_key.get((code, lane_index))
            # フォーク方向の2列は左投げでも1球種目が左（反転後に左へ来るよう、判定座標では右に置く）
            flip_side = is_left and PITCH_GAUGE_GEOMETRY[code]["kind"] == "down"
            bars.append(pitch_bar_shape(code, lane_index, paired, lane.movement if lane else 0, flip_side, diagonal_bar_start(code, paired_directions)))
    bar_by_key = {(bar.direction_code, bar.lane_index): bar for bar in bars}

    straight_frame, straight_fills = _pitch_straight_shapes(2 if second_fastballs else 1)
    straight_labels = _straight_labels(second_fastballs, min(y for _x, y in straight_frame))

    # 衝突判定は右投げ基準の座標で行う。ストレート表示は反転しないので、左投げでは判定用に反転させておく
    u = PITCH_CHART_UNIT
    cx, cy = PITCH_CHART_CENTER
    radius = 1.05 * u / math.cos(math.pi / 8)
    obstacles: list[tuple[PitchPoint, ...]] = [bar.frame for bar in bars]
    obstacles.append(tuple(
        (cx + radius * math.cos(math.pi / 8 + i * math.pi / 4), cy + radius * math.sin(math.pi / 8 + i * math.pi / 4))
        for i in range(8)
    ))
    obstacles.append(straight_frame)
    for label in straight_labels:
        obstacle_label = _mirror_pitch_label(label) if is_left else label
        obstacles.append(_rect_polygon(obstacle_label.rect()))

    pitch_labels: list[PitchChartLabel] = []
    # 横 → 下 → 斜め の順に置く（斜めは候補位置が多いので後回し）
    for code in ("1", "5", "3", "2", "4"):
        for lane_index in (0, 1):
            lane = lane_by_key.get((code, lane_index))
            if lane is None:
                continue
            label = _place_pitch_label(lane, bar_by_key[(code, lane_index)], obstacles)
            pitch_labels.append(label)
            obstacles.append(_rect_polygon(label.rect()))

    if is_left:
        bars = [
            PitchBarShape(bar.direction_code, bar.lane_index, bar.paired, bar.movement,
                          _mirror_pitch_points(bar.frame), tuple(_mirror_pitch_points(cell) for cell in bar.cells))
            for bar in bars
        ]
        pitch_labels = [_mirror_pitch_label(label) for label in pitch_labels]
    return PitchChartLayout(is_left, tuple(bars), straight_frame, straight_fills, tuple(straight_labels + pitch_labels))


def _svg_points(points: tuple[PitchPoint, ...]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def render_pitch_label_svg(label: PitchChartLabel) -> str:
    font_size, _ascent, _descent = _pitch_font_metrics()
    if label.kind == "pitch":
        attrs = f'class="pitch-label" data-direction="{label.direction_code}" data-lane="{label.lane_index}"'
    else:
        attrs = f'class="straight-label" data-kind="{label.kind}"'
    squeeze = f' textLength="{label.width:.2f}" lengthAdjust="spacingAndGlyphs"' if label.compressed else ""
    return (
        f'<text {attrs} x="{label.x:.2f}" y="{label.y:.2f}" text-anchor="{label.anchor}" '
        f'fill="{PITCH_LABEL_COLOR}" font-size="{font_size:.1f}" font-weight="400"{squeeze}>{e(label.text)}</text>'
    )


def render_pitch_chart_svg(balls: list[dict[str, Any]] | None, batting_throwing: str = "") -> str:
    layout = layout_pitch_chart(balls, batting_throwing)
    u = PITCH_CHART_UNIT
    cx, cy = PITCH_CHART_CENTER
    lines = [
        f'<svg viewBox="0 0 {PITCH_CHART_WIDTH} {PITCH_CHART_HEIGHT}" width="100%" height="100%" role="img" aria-label="変化球方向図">',
        f'<rect x="5" y="5" width="270" height="200" rx="7" fill="{PITCH_CHART_BACKGROUND}" stroke="#ffffff" stroke-width="3"/>',
        f'<g class="pitch-straight-area" data-count="{len(layout.straight_fills)}">',
        f'<polygon class="straight-marker-frame" points="{_svg_points(layout.straight_frame)}" fill="{PITCH_FRAME_COLOR}"/>',
    ]
    for index, fill in enumerate(layout.straight_fills):
        lines.append(f'<polygon class="straight-marker" data-index="{index}" points="{_svg_points(fill)}" fill="{PITCH_STRAIGHT_FILL}"/>')
    lines.append("</g>")
    # フレームを先に全部描き、その上にセルを並べる（2列バーが1つのフレームに見えるように）
    for bar in layout.bars:
        lines.append(
            f'<polygon class="pitch-lane-frame" data-direction="{bar.direction_code}" data-lane="{bar.lane_index}" '
            f'data-paired="{str(bar.paired).lower()}" points="{_svg_points(bar.frame)}" fill="{PITCH_FRAME_COLOR}"/>'
        )
    for bar in layout.bars:
        for index, cell in enumerate(bar.cells):
            active = index < bar.movement
            lines.append(
                f'<polygon class="pitch-cell" data-direction="{bar.direction_code}" data-lane="{bar.lane_index}" '
                f'data-index="{index}" data-active="{str(active).lower()}" points="{_svg_points(cell)}" '
                f'fill="{pitch_cell_color(index, active)}"/>'
            )
    ring = 0.25 * u
    radius = 1.05 * u - ring / 2
    lines.extend([
        '<g class="pitch-center-ball">',
        f'<circle cx="{cx:g}" cy="{cy:g}" r="{radius:.2f}" fill="#ffffff" stroke="{PITCH_FRAME_COLOR}" stroke-width="{ring:.2f}"/>',
        *(
            f'<path d="M{cx + side * 0.35 * u:.2f} {cy - 0.62 * u:.2f} C{cx + side * 0.66 * u:.2f} {cy - 0.3 * u:.2f} '
            f'{cx + side * 0.66 * u:.2f} {cy + 0.3 * u:.2f} {cx + side * 0.35 * u:.2f} {cy + 0.62 * u:.2f}" '
            f'fill="none" stroke="#e64d4d" stroke-width="{0.11 * u:.2f}"/>'
            for side in (-1, 1)
        ),
        '</g>',
    ])
    lines.extend(render_pitch_label_svg(label) for label in layout.labels)
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
    is_pitcher = player.get("role") == "投手"
    sub = {i["position"]: i["aptitude"] for i in normalize_sub_positions(player.get("sub_positions"))}
    pos_labels = [("投", "投手"), ("捕", "捕手"), ("一", "一塁手"), ("二", "二塁手"), ("三", "三塁手"), ("遊", "遊撃手"), ("外", "外野手")]
    main_position = "投手" if is_pitcher else player.get("position")
    base_fielding = ability_numeric_value(f, "守備力")
    # ゲーム画面と同じく、守備力の枠の先頭セルにラベルを置き、投〜外の7ポジションを2列で並べます。
    cells = ['<div class="pp-defense-label"><span class="pp-label">守備力</span></div>']
    for short, full in pos_labels:
        is_main = main_position == full
        mark = "◎" if is_main else sub.get(full, "－－")
        if is_main and isinstance(base_fielding, int | float):
            value = max(1, min(99, int(base_fielding)))
        else:
            value = calculate_sub_position_fielding(base_fielding, mark) if mark != "－－" else None
        main_cls = " main" if is_main else ""
        if isinstance(value, int):
            pos_rank = rank(value)
            value_html = f'<span class="pp-defense-rank {ui_rank_class(pos_rank)}" style="color:{ui_rank_color(pos_rank)};">{e(pos_rank)}</span><span class="pp-defense-num">{e(mark)} {e(value)}</span>'
        else:
            value_html = '<span class="pp-defense-empty">－－</span>'
        cells.append(f'<div class="pp-defense-pos{main_cls}"><span class="pp-defense-short">{short}</span>{value_html}</div>')
    grid = '<div class="pp-defense-compact">' + ''.join(cells) + '</div>'
    html = render_ability_rows([("走力", f.get("走力")), ("肩力", f.get("肩力"))]) + grid + render_ability_rows([("捕球", f.get("捕球"))])
    if is_pitcher:
        html += pitcher_usage_row_html(player)
    return html

def profile_physique_text(player: dict[str, Any], key: str, legacy_key: str, unit: str) -> str:
    value = player.get(key) if key in player else player.get(legacy_key)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    return f"{int(value)}{unit}"


def render_profile_right(player: dict[str, Any]) -> str:
    display_name = player.get("back_name") or player.get("name")
    pro_years = int(player.get("pro_years") or 0)
    pro_years_text = "" if "pro_years" not in player else ("不明" if not player.get("entry_route") else ("未経験" if pro_years == 0 else f"{pro_years}年目"))
    roster_origin_text = {"foreign_import": "外国人補強", "domestic": "国内経由"}.get(str(player.get("roster_origin") or ""), "")
    foreign_route_text = FOREIGN_ROUTE_LABELS.get(str(player.get("foreign_route") or ""), "")
    npb_years = int(player.get("npb_years") or 0)
    npb_years_text = f"{npb_years}年目" if player.get("roster_origin") == "foreign_import" and npb_years else ""
    items = [
        ("氏名", player.get("name"), " pp-profile-span-3"),
        ("年齢", f"{player.get('age')}歳", ""),
        ("プロ", pro_years_text, ""),
        ("加入区分", roster_origin_text, ""),
        ("経由", foreign_route_text, ""),
        ("NPB在籍", npb_years_text, ""),
        ("再来日", "あり" if player.get("is_returnee") else "", ""),
        ("誕生日", birthday_display(player), ""),
        ("投打", player.get("batting_throwing"), ""),
        ("国籍", player.get("nationality"), ""),
        ("実国籍", player.get("actual_nationality"), ""),
        ("肌色", player.get("skin_color") or "", ""),
        ("出身地", player.get("birthplace"), ""),
        ("身長", profile_physique_text(player, "height_cm", "height", "cm"), ""),
        ("体重", profile_physique_text(player, "weight_kg", "weight", "kg"), ""),
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


def header_position_html(player: dict[str, Any]) -> str:
    # ゲームと同じく「守備位置」「適性」をラベルのピルにし、値は大きな文字で表示します。
    # 野手：メインポジションを大きく、サブポジションを小さく並べます（例：遊 三 外）。
    # 投手：先・中・抑を適性の高さに応じた大きさで並べ、適性なし（－）は表示しません。
    if player.get("role") == "投手":
        abilities = player.get("abilities", {}) if isinstance(player.get("abilities"), dict) else {}
        values = {key: player.get(key) or abilities.get(key) for key in PITCHER_APTITUDE_KEYS}
        if not any(values.values()):
            pos = str(player.get("position", ""))
            values = {"starter_aptitude": "◎" if pos == "先発" else "－", "reliever_aptitude": "◎" if pos == "中継ぎ" else "－", "closer_aptitude": "◎" if pos == "抑え" else "－"}
        level_class = {"◎": "lv3", "○": "lv2", "△": "lv1"}
        items = []
        for key, label in [("starter_aptitude", "先"), ("reliever_aptitude", "中"), ("closer_aptitude", "抑")]:
            mark = str(values.get(key) or "－")
            if mark in level_class:
                items.append(f'<span class="pp-pos-item {level_class[mark]}" title="{e(label + mark)}">{label}</span>')
        value_html = "".join(items) or '<span class="pp-pos-item lv1">－</span>'
        return f'<div class="pp-posline"><span class="pp-mini-label">適性</span><span class="pp-pos-values">{value_html}</span></div>'
    short_positions = {"捕手": "捕", "一塁手": "一", "二塁手": "二", "三塁手": "三", "遊撃手": "遊", "外野手": "外"}
    main = str(player.get("position", ""))
    main_short = short_positions.get(main, main or "－")
    subs = {item["position"] for item in normalize_sub_positions(player.get("sub_positions"))}
    sub_html = "".join(f'<span class="pp-pos-item sub">{short}</span>' for full, short in short_positions.items() if full in subs and full != main)
    return f'<div class="pp-posline"><span class="pp-mini-label">守備位置</span><span class="pp-pos-values"><span class="pp-pos-item main">{e(main_short)}</span>{sub_html}</span></div>'


def normalize_selected_tab_value(player: dict[str, Any], value: Any) -> str:
    if value == "選手能力" or value not in TAB_LABELS:
        return "投手能力" if player.get("role") == "投手" else "野手能力"
    return str(value)


def usage_special_categories(player: dict[str, Any], master: MasterData) -> dict[str, list[str]]:
    entries = [name for name, _kind in collect_special_entries(player, master, "usage")]
    if player.get("role") == "投手":
        mapping = {
            "投球方針": {"速球中心", "変化球中心", "投球位置左", "投球位置右", "テンポ○"},
            "起用法": {"フル出場"},
            "その他": {"人気者"},
        }
    else:
        mapping = {
            "打撃方針": {"ミート多用", "強振多用", "積極打法", "慎重打法", "チームプレイ○", "チームプレイ×"},
            "走塁方針": {"積極盗塁", "慎重盗塁", "積極走塁"},
            "守備方針": {"積極守備"},
            "起用法": {"フル出場"},
            "その他": {"人気者"},
        }
    return {label: [name for name in entries if name in names] for label, names in mapping.items() if any(name in names for name in entries)}


def render_usage_categories_html(player: dict[str, Any], master: MasterData) -> str:
    cells: list[str] = []
    categories = usage_special_categories(player, master)
    growth_html = e(growth_type_label(player.get("growth_type")))
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
          {header_position_html(p)}
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
        left = render_trajectory_row_html(fa.get("弾道")) + render_ability_rows([("ミート", fa.get("ミート")), ("パワー", fa.get("パワー")), ("走力", fa.get("走力")), ("肩力", fa.get("肩力")), ("守備力", fa.get("守備力")), ("捕球", fa.get("捕球"))])
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

# ===== 能力カード以外の画面部品 =====
# 配色トークン。.streamlit/config.toml のテーマと同じ値にそろえる。
UI_COLORS = {
    "primary": "#0B2A5B",
    "accent": "#E5333F",
    "accent-dark": "#A91F2A",
    "text": "#1A2B45",
    "muted": "#4A5B75",
    "surface": "#FFFFFF",
    "border": "#C9D6E8",
    "sidebar-bg": "#0B2A5B",
    "sidebar-text": "#FFFFFF",
    "sidebar-muted": "#C9D6E8",
}
# 能力カードのCSSは st-key-latest_* を前提にしているため、キー接頭辞は "latest" のまま使う。
DETAIL_KEY_PREFIX = "latest"
# 改修前のコミット（main 8e7e784）を1920px幅で表示したときのカード幅の実測値
CARD_MAX_WIDTH_PX = 1460
PLAYER_AREA_KEY = "player_area"
PLAYER_SELECT_KEY = "selected_player_id"
PLAYER_OPTION_LIMIT = 300
HISTORY_TABLE_NONCE_KEY = "history_table_nonce"
HISTORY_TABLE_IDS_KEY = "history_table_ids"
HISTORY_DEFAULT_COLUMNS = ["name", "category", "position", "player_type", "age", "batting_throwing", "entry_route", "created_at"]
# 詳細列でも出さない列（日本語の派生列と重複するもの、表に向かない入れ子の値）
HISTORY_HIDDEN_COLUMNS = {*CLASSIFICATION_COLUMNS, "growth_type", "sub_positions"}
HISTORY_COLUMN_LABELS = {
    "id": "ID",
    "created_at": "生成日時",
    "seed": "seed",
    "role": "投手/野手",
    "category": "カテゴリ",
    "name": "名前",
    "age": "年齢",
    "roster_origin": "所属区分",
    "foreign_route": "来日経路",
    "entry_route": "入団経路",
    "pro_entry_age": "入団年齢",
    "pro_years": "プロ年数",
    "npb_years": "NPB在籍年数",
    "npb_first_entry_year": "NPB初入団年",
    "npb_stint_start_year": "現所属開始年",
    "is_returnee": "再来日",
    "nationality": "国籍",
    "actual_nationality": "実際の国籍",
    "nationality_code": "国籍コード",
    "name_group_id": "名前グループID",
    "name_group_name": "名前グループ",
    "skin_color": "肌の色",
    "birthplace": "出身地",
    "region": "地域",
    "position": "起用",
    "player_type": "タイプ",
    "handedness": "利き腕",
    "batting_throwing": "投打",
    "height": "身長",
    "weight": "体重",
    "height_cm": "身長(cm)",
    "weight_kg": "体重(kg)",
    "abilities_json": "能力(JSON)",
    "special_abilities_json": "特殊能力(JSON)",
    "ranked_special_abilities_json": "ランク特殊能力(JSON)",
    "breaking_balls_json": "変化球(JSON)",
    "pitcher_aptitudes_json": "投手適性(JSON)",
    "sub_positions_json": "サブポジ(JSON)",
    "birth_month": "誕生月",
    "birth_day": "誕生日(日)",
    "pitching_form_type": "投球フォーム種別",
    "pitching_form_number": "投球フォーム番号",
    "pitching_form_is_generic": "投球フォーム汎用",
    "batting_form_type": "打撃フォーム種別",
    "batting_form_number": "打撃フォーム番号",
    "batting_form_is_generic": "打撃フォーム汎用",
    "bat_color": "バット色",
    "glove_color": "グラブ色",
    "wristband_left_enabled": "リストバンド(左)",
    "wristband_left_color": "リストバンド色(左)",
    "wristband_right_enabled": "リストバンド(右)",
    "wristband_right_color": "リストバンド色(右)",
    "draft_source_type": "ドラフト出身区分",
    "starter_aptitude": "先発適性",
    "reliever_aptitude": "中継ぎ適性",
    "closer_aptitude": "抑え適性",
}
# 表示用の値の変換表（DBの値は変えない）。表に無い値は元の値をそのまま表示する。
HISTORY_VALUE_LABELS = {
    "roster_origin": {"domestic": "国内", "foreign_import": "外国人補強"},
    "foreign_route": FOREIGN_ROUTE_LABELS,
    "is_returnee": {0: "いいえ", 1: "はい"},
    "pitching_form_is_generic": {0: "固有", 1: "汎用"},
    "batting_form_is_generic": {0: "固有", 1: "汎用"},
    "wristband_left_enabled": {0: "なし", 1: "あり"},
    "wristband_right_enabled": {0: "なし", 1: "あり"},
}


def app_chrome_css() -> str:
    tokens = "".join(f"--ui-{name}:{value};" for name, value in UI_COLORS.items())
    css = """
    <style>
    :root {/*TOKENS*/}
    .stApp {color:var(--ui-text); background: radial-gradient(circle at 12% 18%, rgba(255,255,255,.28) 0 7%, transparent 8%), radial-gradient(circle at 88% 70%, rgba(255,255,255,.18) 0 10%, transparent 11%), linear-gradient(150deg,#effdff 0%,#b5f3e6 38%,#5fd6e3 72%,#1fa6d6 100%);}
    [data-testid="stHeader"] {background:rgba(244,248,252,.94); backdrop-filter:blur(6px); box-shadow:0 1px 0 var(--ui-border);}
    @media (max-width: 1439px) {.block-container {padding-left:24px; padding-right:24px;}}
    .pp-title {background:var(--ui-surface); border-left:8px solid var(--ui-accent); border-bottom:3px solid var(--ui-primary); padding:12px 20px; border-radius:4px 16px 16px 4px; color:var(--ui-primary); font-weight:900; font-size:28px; margin-bottom:10px; box-shadow:0 2px 8px rgba(11,42,91,.10);}
    .pp-page-description {color:var(--ui-text); font-size:16px; line-height:1.6; font-weight:650; margin:0 0 14px;}
    .pp-section-heading {color:var(--ui-primary); background:var(--ui-surface); border-left:5px solid var(--ui-accent); border-radius:4px; padding:7px 12px; font-size:17px; font-weight:900; margin:18px 0 10px;}
    div[class*="st-key-player_area"] {max-width:/*CARD_MAX_WIDTH*/; width:100%; margin-left:auto; margin-right:auto;}
    .pp-table-count {text-align:right; color:var(--ui-muted); font-size:14px; font-weight:700;}
    .pp-player-count {display:flex; align-items:center; justify-content:center; height:40px; color:var(--ui-muted); font-size:15px; font-weight:800; white-space:nowrap; font-variant-numeric:tabular-nums;}
    /* サイドバー：紺地に白文字。入力欄は白地に本文色 */
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] label, [data-testid="stSidebar"] label p {color:var(--ui-sidebar-text);}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {color:var(--ui-sidebar-muted);}
    [data-testid="stSidebar"] input {background:var(--ui-surface); color:var(--ui-text); -webkit-text-fill-color:var(--ui-text);}
    [data-testid="stSidebar"] input:disabled {background:#DCE5F0; color:var(--ui-muted); -webkit-text-fill-color:var(--ui-muted); cursor:not-allowed;}
    [data-testid="stSidebar"] [data-testid="stSelectbox"] div:has(> input), [data-testid="stSidebar"] [data-testid="stSelectbox"] button, [data-testid="stSidebar"] [data-testid="stSelectbox"] svg {color:var(--ui-text);}
    /* 選択肢リストは body 直下に出るが、サイドバーのテーマ（白文字）を引き継いで白地に白文字になるため本文色にする */
    [data-testid="stSelectboxVirtualDropdown"] [role="option"] {color:var(--ui-text);}
    [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] {height:40px;}
    [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] input {height:100%;}
    [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] button {background:#EEF3FA; color:var(--ui-text); height:100%; min-width:40px;}
    [data-testid="stSidebar"] [data-testid="stNumberInputContainer"] button svg {fill:var(--ui-text);}
    div[class*="st-key-generate_button"] button {background:var(--ui-accent); border:2px solid #FFFFFF; min-height:46px; box-shadow:0 3px 0 var(--ui-accent-dark);}
    div[class*="st-key-generate_button"] button p {font-size:17px; font-weight:900; letter-spacing:.08em;}
    div[class*="st-key-generate_button"] button:hover {background:#F04A55; border-color:#FFFFFF;}
    /* 前／次の選手 */
    div[class*="st-key-player_prev"] button, div[class*="st-key-player_next"] button {min-height:40px; height:40px; white-space:nowrap; background:var(--ui-primary); border:1px solid var(--ui-primary); color:#FFFFFF;}
    div[class*="st-key-player_prev"] button p, div[class*="st-key-player_next"] button p {color:#FFFFFF; font-weight:800;}
    div[class*="st-key-player_prev"] button:hover, div[class*="st-key-player_next"] button:hover {background:#16407F; border-color:#16407F; color:#FFFFFF;}
    div[class*="st-key-player_prev"] button:disabled, div[class*="st-key-player_next"] button:disabled {background:transparent; border:1px dashed var(--ui-border); cursor:not-allowed;}
    div[class*="st-key-player_prev"] button:disabled p, div[class*="st-key-player_next"] button:disabled p {color:var(--ui-muted); opacity:.6; font-weight:700;}
    /* 出力ボタン */
    div[data-testid="stDownloadButton"] button {background:var(--ui-surface); border:1.5px solid var(--ui-primary); color:var(--ui-primary);}
    div[data-testid="stDownloadButton"] button p {color:var(--ui-primary); font-weight:800;}
    div[data-testid="stDownloadButton"] button:hover {background:#EEF3FA; border-color:var(--ui-primary);}
    div[class*="st-key-export_all_"] button {border-width:1px; border-color:var(--ui-border); min-height:2rem;}
    div[class*="st-key-export_all_"] button p {color:var(--ui-muted); font-weight:600; font-size:13px;}
    </style>
    """
    return css.replace("/*TOKENS*/", tokens).replace("/*CARD_MAX_WIDTH*/", f"{CARD_MAX_WIDTH_PX}px")


def inject_app_chrome_css() -> None:
    st.markdown(app_chrome_css(), unsafe_allow_html=True)


def render_section_heading(text: str) -> None:
    st.markdown(f'<div class="pp-section-heading">{e(text)}</div>', unsafe_allow_html=True)


def player_unique_id(player: dict[str, Any], index: int) -> str:
    db_id = player.get("id")
    if db_id not in (None, ""):
        return f"db:{db_id}"
    return f"latest:{player.get('seed', '')}:{player.get('name', '')}:{player.get('position', '')}:{index}"


def player_label(player: dict[str, Any], is_new: bool = False) -> str:
    prefix = "【NEW】" if is_new else ""
    return f"{prefix}{player.get('name')}｜{player.get('position')}｜{player.get('player_type')}｜{player.get('age')}歳｜{player.get('batting_throwing')}"


def relative_player_id(player_ids: list[str], current_id: str | None, offset: int) -> str | None:
    if not player_ids:
        return None
    if current_id not in player_ids:
        return player_ids[0]
    current_index = player_ids.index(current_id)
    next_index = max(0, min(len(player_ids) - 1, current_index + offset))
    return player_ids[next_index]


def player_choice_ids(history_ids: list[str], latest_ids: list[str], selected_id: str | None, limit: int = PLAYER_OPTION_LIMIT) -> list[str]:
    """選択欄の並び（生成日時の新しい順）。保存できなかった今回分を先頭に置き、上限外でも選択中の選手は残す。"""
    history_id_set = set(history_ids)
    unsaved = [player_id for player_id in latest_ids if player_id not in history_id_set]
    included = set(history_ids[:limit])
    if selected_id in history_id_set:
        included.add(selected_id)
    return unsaved + [player_id for player_id in history_ids if player_id in included]


def reset_history_table_selection() -> None:
    # 表の行選択は外から書き換えられないため、キーを変えて選択を解除する
    st.session_state[HISTORY_TABLE_NONCE_KEY] = st.session_state.get(HISTORY_TABLE_NONCE_KEY, 0) + 1


def select_relative_player(*, player_ids: list[str], selected_key: str, offset: int) -> None:
    st.session_state[selected_key] = relative_player_id(player_ids, st.session_state.get(selected_key), offset)
    reset_history_table_selection()


def select_player_from_history_table(table_key: str) -> None:
    rows = st.session_state[table_key].selection.rows
    row_ids = st.session_state.get(HISTORY_TABLE_IDS_KEY, [])
    if rows and rows[0] < len(row_ids):
        st.session_state[PLAYER_SELECT_KEY] = row_ids[rows[0]]


def history_ids_from_frame(history: pd.DataFrame) -> list[str]:
    if history.empty or "id" not in history.columns:
        return []
    return [f"db:{int(value)}" for value in history["id"]]


def format_created_at(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    return parsed.strftime("%Y/%m/%d %H:%M")


def history_display_frame(history: pd.DataFrame, show_details: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """表示用の表と列順を返す。DBの値は変えず、表示用に値を日本語へ置き換えたコピーを作る。"""
    display = history.copy()
    for column, labels in HISTORY_VALUE_LABELS.items():
        if column in display.columns:
            display[column] = display[column].map(lambda value, labels=labels: labels.get(value, value))
    if "created_at" in display.columns:
        display["created_at"] = display["created_at"].map(format_created_at)
    if show_details:
        columns = [column for column in HISTORY_DEFAULT_COLUMNS if column in display.columns]
        columns += [column for column in display.columns if column not in columns and column not in HISTORY_HIDDEN_COLUMNS]
    else:
        columns = [column for column in HISTORY_DEFAULT_COLUMNS if column in display.columns]
    return display, columns


def history_column_config(columns: list[str]) -> dict[str, Any]:
    return {column: st.column_config.Column(HISTORY_COLUMN_LABELS.get(column, column)) for column in columns}


def history_row_label(row: pd.Series) -> str:
    return player_label({key: row.get(key) for key in ("name", "position", "player_type", "age", "batting_throwing")})


def render_player_section(history: pd.DataFrame, master: MasterData) -> None:
    latest_players = st.session_state.get("latest_players", [])
    latest_by_id = {player_unique_id(player, index): player for index, player in enumerate(latest_players)}
    history_ids = history_ids_from_frame(history)
    player_ids = player_choice_ids(history_ids, list(latest_by_id), st.session_state.get(PLAYER_SELECT_KEY))
    if not player_ids:
        st.info("表示する選手がまだありません。左の条件で生成してください。")
        return
    if st.session_state.get(PLAYER_SELECT_KEY) not in player_ids:
        st.session_state[PLAYER_SELECT_KEY] = player_ids[0]
    row_position_by_id = {player_id: position for position, player_id in enumerate(history_ids)}
    label_by_id = {}
    for player_id in player_ids:
        if player_id in latest_by_id:
            label_by_id[player_id] = player_label(latest_by_id[player_id], is_new=True)
        else:
            label_by_id[player_id] = history_row_label(history.iloc[row_position_by_id[player_id]])
    current_index = player_ids.index(st.session_state[PLAYER_SELECT_KEY])
    # 選手選択欄とカードは改修前のカード幅にそろえて中央に置く（表や出力ボタンは全幅のまま）
    with st.container(key=PLAYER_AREA_KEY):
        render_section_heading("選手を選択")
        previous_col, select_col, count_col, next_col = st.columns([0.15, 0.6, 0.1, 0.15], gap="small", vertical_alignment="center")
        with previous_col:
            st.button("◀ 前の選手", use_container_width=True, disabled=current_index <= 0, key="player_prev", on_click=select_relative_player, kwargs={"player_ids": player_ids, "selected_key": PLAYER_SELECT_KEY, "offset": -1})
        with select_col:
            selected_player_id = st.selectbox("選手一覧", player_ids, format_func=lambda player_id: label_by_id[player_id], key=PLAYER_SELECT_KEY, label_visibility="collapsed", on_change=reset_history_table_selection)
        current_index = player_ids.index(selected_player_id)
        with count_col:
            st.markdown(f'<div class="pp-player-count">{current_index + 1} / {len(player_ids)}</div>', unsafe_allow_html=True)
        with next_col:
            st.button("次の選手 ▶", use_container_width=True, disabled=current_index >= len(player_ids) - 1, key="player_next", on_click=select_relative_player, kwargs={"player_ids": player_ids, "selected_key": PLAYER_SELECT_KEY, "offset": 1})
        if selected_player_id in latest_by_id:
            player = latest_by_id[selected_player_id]
        else:
            player = player_from_history_row(history.iloc[row_position_by_id[selected_player_id]])
        render_seed_copy(player)
        render_detail_panel(player, master, DETAIL_KEY_PREFIX)


def seed_copy_text(player: dict[str, Any]) -> str:
    """「seedをコピー」でコピーする再現用の文字列（<投手|野手>/<カテゴリ>/<seed>）。"""
    return f"{player.get('role', '')}{SEED_SPEC_SEPARATOR}{player.get('category', '')}{SEED_SPEC_SEPARATOR}{player.get('seed', '')}"


def seed_copy_html(copy_text: str) -> str:
    # スクリプト内に埋め込むため、"</script>" で閉じられないよう "<" もエスケープする
    copy_json = json.dumps(str(copy_text)).replace("<", "\\u003c")
    return f"""
    <div style="display:flex;align-items:center;justify-content:flex-end;gap:10px;font-family:'Source Sans Pro',sans-serif;font-size:14px;color:{UI_COLORS['muted']};">
      <span>再生成用: <b style="color:{UI_COLORS['text']};">{e(copy_text)}</b></span>
      <button id="copy" style="cursor:pointer;border:1.5px solid {UI_COLORS['primary']};background:#fff;color:{UI_COLORS['primary']};border-radius:8px;padding:4px 12px;font-size:14px;font-weight:700;">seedをコピー</button>
      <span id="msg" aria-live="polite"></span>
    </div>
    <script>
    const copyText = {copy_json};
    document.getElementById("copy").addEventListener("click", async () => {{
      const msg = document.getElementById("msg");
      try {{
        await navigator.clipboard.writeText(copyText);
      }} catch (error) {{
        const area = document.createElement("textarea");
        area.value = copyText;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }}
      msg.textContent = "コピーしました";
      setTimeout(() => {{ msg.textContent = ""; }}, 2000);
    }});
    </script>
    """


def render_seed_copy(player: dict[str, Any]) -> None:
    if player.get("seed") in (None, ""):
        return
    components.html(seed_copy_html(seed_copy_text(player)), height=40)


def history_excel_bytes(history: pd.DataFrame, sheet_name: str = "players") -> bytes:
    excel_buffer = BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        history.to_excel(writer, sheet_name=sheet_name, index=False)
    return excel_buffer.getvalue()


def history_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def history_view_export_frame(display: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """「表示中の内容」の出力用。表と同じ行・列・日本語の列名にする。"""
    labels: list[str] = []
    for column in columns:
        label = HISTORY_COLUMN_LABELS.get(column, column)
        # 日本語名が既存の列名と重なる場合は内部名を添えて区別する
        labels.append(label if label not in labels else f"{label}（{column}）")
    exported = display[columns].copy()
    exported.columns = labels
    return exported


def export_file_name(kind: str, extension: str, now: Any = None) -> str:
    stamp = pd.Timestamp(now if now is not None else pd.Timestamp.now()).strftime("%Y%m%d_%H%M")
    return f"players_{kind}_{stamp}.{extension}"


HISTORY_PERIOD_OPTIONS = ["すべて", "今日", "7日以内"]
HISTORY_TABLE_HEIGHT = 420
EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SEED_INPUT_KEY = "seed_input"
ROLE_INPUT_KEY = "role_input"
CATEGORY_INPUT_KEY = "category_input"
PENDING_CONDITIONS_KEY = "pending_generation_conditions"
SEED_SPEC_SEPARATOR = "/"
SQLITE_INTEGER_MAX = 2**63 - 1


def filter_history_table(history: pd.DataFrame, categories: list[str], positions: list[str], period: str, name_query: str, today: Any = None) -> pd.DataFrame:
    """過去生成選手の表の絞り込み。選択肢が空の項目は絞り込まない。"""
    filtered = history
    if categories:
        filtered = filtered[filtered["category"].isin(categories)]
    if positions:
        filtered = filtered[filtered["position"].isin(positions)]
    if period in ("今日", "7日以内"):
        today = pd.Timestamp(today if today is not None else pd.Timestamp.now()).normalize()
        start = today if period == "今日" else today - pd.Timedelta(days=6)
        created = pd.to_datetime(filtered["created_at"], errors="coerce")
        filtered = filtered[created >= start]
    query = name_query.strip()
    if query:
        filtered = filtered[filtered["name"].astype(str).str.contains(query, case=False, regex=False)]
    return filtered


def history_position_options(history: pd.DataFrame) -> list[str]:
    order = POSITIONS["投手"] + POSITIONS["野手"]
    present = set(history["position"].dropna().astype(str)) if "position" in history.columns else set()
    return [position for position in order if position in present] + sorted(present - set(order))


def render_history_section(history: pd.DataFrame) -> None:
    render_section_heading("過去生成選手")
    if history.empty:
        st.caption("保存済みの選手はまだありません。")
        return
    category_col, position_col, period_col, name_col = st.columns([0.28, 0.28, 0.2, 0.24], gap="small")
    with category_col:
        categories = st.multiselect("カテゴリ", CATEGORIES, key="history_filter_categories", placeholder="すべて")
    with position_col:
        positions = st.multiselect("起用", history_position_options(history), key="history_filter_positions", placeholder="すべて")
    with period_col:
        period = st.segmented_control("生成日", HISTORY_PERIOD_OPTIONS, default="すべて", key="history_filter_period") or "すべて"
    with name_col:
        name_query = st.text_input("名前で検索", key="history_filter_name", placeholder="名前の一部")
    filtered = filter_history_table(history, categories, positions, period, name_query)
    detail_col, count_col = st.columns([0.5, 0.5], vertical_alignment="center")
    with detail_col:
        show_details = st.toggle("詳細列を表示", key="history_show_details")
    with count_col:
        st.markdown(f'<div class="pp-table-count">{len(filtered)}件を表示（全{len(history)}件）</div>', unsafe_allow_html=True)
    display, columns = history_display_frame(filtered, show_details)
    st.session_state[HISTORY_TABLE_IDS_KEY] = history_ids_from_frame(filtered)
    table_key = f"history_table_{st.session_state.get(HISTORY_TABLE_NONCE_KEY, 0)}"
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=HISTORY_TABLE_HEIGHT if len(display) > 10 else "auto",
        column_order=columns,
        column_config=history_column_config(columns),
        on_select=partial(select_player_from_history_table, table_key),
        selection_mode="single-row",
        key=table_key,
    )
    render_history_exports(history, history_view_export_frame(display, columns))


def render_history_exports(history: pd.DataFrame, view: pd.DataFrame) -> None:
    now = pd.Timestamp.now()
    csv_col, excel_col, _spacer = st.columns([0.22, 0.22, 0.56], gap="small")
    with csv_col:
        st.download_button(f"CSVで保存（表示中 {len(view)}件）", data=history_csv_bytes(view), file_name=export_file_name("view", "csv", now), mime="text/csv", use_container_width=True, key="export_view_csv")
    with excel_col:
        st.download_button(f"Excelで保存（表示中 {len(view)}件）", data=history_excel_bytes(view, sheet_name="表示中"), file_name=export_file_name("view", "xlsx", now), mime=EXCEL_MIME, use_container_width=True, key="export_view_excel")
    with st.expander("全データを出力（内部の列名・値のまま）"):
        st.caption("絞り込みや表示列に関係なく、保存済みの全選手・全列を出力します。")
        all_csv_col, all_excel_col, _all_spacer = st.columns([0.26, 0.26, 0.48], gap="small")
        with all_csv_col:
            st.download_button(f"全データをCSVで保存（全 {len(history)}件）", data=history_csv_bytes(history), file_name=export_file_name("all", "csv", now), mime="text/csv", use_container_width=True, key="export_all_csv")
        with all_excel_col:
            st.download_button(f"全データをExcelで保存（全 {len(history)}件）", data=history_excel_bytes(history), file_name=export_file_name("all", "xlsx", now), mime=EXCEL_MIME, use_container_width=True, key="export_all_excel")


class SeedSpecError(ValueError):
    """seed入力欄の値を読み取れないときのエラー。メッセージは画面にそのまま出す。"""


@dataclass(frozen=True)
class SeedSpec:
    seed: int
    role: str | None = None
    category: str | None = None


def parse_seed_int(text: str) -> int:
    try:
        seed = int(text.strip())
    except ValueError:
        raise SeedSpecError(f"seed「{text.strip()}」を整数として読み取れません。0以上の整数を入力してください。") from None
    if not 0 <= seed <= SQLITE_INTEGER_MAX:
        raise SeedSpecError(f"seed「{text.strip()}」は範囲外です。0以上の整数を入力してください。")
    return seed


def parse_seed_spec(text: str) -> SeedSpec | None:
    """seed入力欄の値を読む。空欄は None。数字だけならseedのみ、「投手/カテゴリ/seed」なら条件も返す。"""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not value:
        return None
    if SEED_SPEC_SEPARATOR not in value:
        return SeedSpec(seed=parse_seed_int(value))
    parts = [part.strip() for part in value.split(SEED_SPEC_SEPARATOR)]
    if len(parts) != 3 or not all(parts):
        raise SeedSpecError(f"「{value}」は形式が合いません。「投手/助っ人外国人用/5821876419」の形式か、数字だけを入力してください。")
    role, category, seed_text = parts
    if role not in POSITIONS:
        raise SeedSpecError(f"「{role}」は投手/野手の名前として見つかりません。「投手」か「野手」を指定してください。")
    if category not in CATEGORIES:
        raise SeedSpecError(f"カテゴリ「{category}」が見つかりません。{('、'.join(CATEGORIES))}のいずれかを指定してください。")
    return SeedSpec(seed=parse_seed_int(seed_text), role=role, category=category)


def generate_and_save_players(role: str, category: str, count: int, master: MasterData, seed: int | None = None) -> None:
    players = []
    with st.spinner("選手を生成中です..."):
        if seed is not None:
            players.append(generate_player(role, category, master, seed=seed, used_names=set()))
        else:
            progress = st.progress(0, text="選手を生成中です...")
            used_names: set[str] = set()
            for index, batch_seed in enumerate(generate_batch_seeds(count)):
                players.append(generate_player(role, category, master, seed=batch_seed, used_names=used_names))
                progress.progress((index + 1) / count, text=f"選手を生成中です... {index + 1}/{count}")
            progress.empty()
        saved_ids: list[int] = []
        try:
            # 新しい順（id降順）で並べたときに生成順になるよう、末尾から保存する
            save_players(players[::-1], saved_ids)
            saved_ids.reverse()
        except sqlite3.Error as error:
            st.session_state["save_error"] = f"選手の保存に失敗しました（{error}）。生成した選手は画面にだけ表示しています。"
            saved_ids = []
        else:
            st.session_state.pop("save_error", None)
    if len(saved_ids) == len(players):
        players = [{**player, "id": player_id} for player, player_id in zip(players, saved_ids)]
    st.session_state["latest_players"] = players
    st.session_state[PLAYER_SELECT_KEY] = player_unique_id(players[0], 0) if players else None
    st.session_state[f"{DETAIL_KEY_PREFIX}_selected_player_tab"] = "投手能力" if role == "投手" else "野手能力"
    reset_history_table_selection()
    st.session_state["pending_toast"] = f"{len(players)}人の選手を生成しました"


def start_generation() -> None:
    st.session_state["generating"] = True


def render_generation_sidebar() -> tuple[str, str, int, str]:
    # 貼り付けた「投手/カテゴリ/seed」の条件は、ウィジェットを描く前に反映する
    pending = st.session_state.pop(PENDING_CONDITIONS_KEY, None)
    if pending:
        st.session_state[ROLE_INPUT_KEY], st.session_state[CATEGORY_INPUT_KEY] = pending
    seed_text = str(st.session_state.get(SEED_INPUT_KEY, "") or "")
    seed_given = bool(seed_text.strip())
    with st.sidebar:
        st.header("生成条件")
        role = st.radio("投手 / 野手", ["投手", "野手"], horizontal=True, key=ROLE_INPUT_KEY)
        category = st.selectbox("カテゴリ", CATEGORIES, key=CATEGORY_INPUT_KEY)
        count = st.number_input("生成人数", min_value=1, max_value=1000, value=3, step=1, disabled=seed_given)
        if seed_given:
            st.caption("seed指定時は1人だけ生成します")
        st.text_input(
            "seed（任意）",
            key=SEED_INPUT_KEY,
            placeholder="空欄ならランダム",
            help="外国人選手は、一度に生成した中で名前の重複を避けるために名前が変わっていた場合、seedから再生成しても同じ名前にはなりません。",
        )
        st.caption("『seedをコピー』で得た文字列を貼ると、同じ条件で再生成します")
        st.button("生成する", type="primary", use_container_width=True, key="generate_button", disabled=bool(st.session_state.get("generating")), on_click=start_generation)
        st.caption(f"Version {APP_VERSION}")
    return role, category, int(count), seed_text


def render_app_title() -> None:
    st.markdown(f'<div class="pp-title">⚾ {e(APP_NAME)}</div>', unsafe_allow_html=True)


def generation_page() -> None:
    master = load_master_data()
    render_app_title()
    render_page_description("投手/野手、カテゴリ、生成人数だけを選ぶと、ゲーム風の能力詳細画面で確認できます。")
    role, category, count, seed_text = render_generation_sidebar()
    if st.session_state.get("generating"):
        try:
            spec = parse_seed_spec(seed_text)
        except SeedSpecError as error:
            st.session_state["seed_error"] = str(error)
        else:
            st.session_state.pop("seed_error", None)
            if spec and spec.role and spec.category:
                role, category = spec.role, spec.category
                st.session_state[PENDING_CONDITIONS_KEY] = (role, category)
            generate_and_save_players(role, category, count, master, spec.seed if spec else None)
        st.session_state["generating"] = False
        st.rerun()
    if st.session_state.get("pending_toast"):
        st.toast(st.session_state.pop("pending_toast"), icon="✅")
    if st.session_state.get("seed_error"):
        st.error(st.session_state["seed_error"])
    if st.session_state.get("save_error"):
        st.error(st.session_state["save_error"])
    history = load_history()
    render_player_section(history, master)
    st.divider()
    render_history_section(history)


def balance_page() -> None:
    render_app_title()
    render_balance_check(load_master_data())


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="⚾", layout="wide")
    init_db()
    inject_powerpro_ui_css()
    inject_app_chrome_css()
    pages = [
        st.Page(generation_page, title="選手生成", icon="⚾", url_path="generate", default=True),
        st.Page(balance_page, title="バランス確認", icon="📊", url_path="balance"),
    ]
    st.navigation(pages, position="top").run()


if __name__ == "__main__":
    main()
