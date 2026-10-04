"""球団生成モードのうち、選手生成に依存しない部分。

- 実在データ（data/reference/）の読み込み
- 構成テンプレートの抽選と揺らぎ
- 戦力レベル・チームカラー（TeamProfile）
- 背番号の割り当て
- 球団単位の集計（構成・査定指標）

選手を作る処理（generate_player を呼ぶ部分）は app.py の generate_team にある。
倍率の基準値・範囲・揺らぎ幅はこのファイルの定数にまとめてある（手で調整しやすくするため）。
"""
from __future__ import annotations

import csv
import hashlib
import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from generator.rating import player_rating

APP_DIR = Path(__file__).resolve().parents[1]
REFERENCE_DIR = APP_DIR / "data" / "reference"
TEAM_COMPOSITION_PATH = REFERENCE_DIR / "real_team_composition_2022_2026.csv"
UNIFORM_NUMBER_PATH = REFERENCE_DIR / "real_uniform_numbers_2022_2026.csv"

FIELDER_POSITIONS = ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")
INFIELD_POSITIONS = ("一塁手", "二塁手", "三塁手", "遊撃手")
POSITION_COLUMNS = {"捕手": "pos_C", "一塁手": "pos_1B", "二塁手": "pos_2B", "三塁手": "pos_3B", "遊撃手": "pos_SS", "外野手": "pos_OF"}
PITCHER_ROLE_ORDER = ("先発", "中継ぎ", "抑え")

# ---------------------------------------------------------------------------
# 構成テンプレート（セクション2）
# ---------------------------------------------------------------------------
TEMPLATE_NAMESPACE = "team_mode_template_v1"
# 2026年版はシーズン前の名簿で総数が少ないため重みを下げる
TEMPLATE_SEASON_WEIGHTS = {2026: 0.5}
PITCHER_COUNT_RANGE = (30, 39)
FIELDER_COUNT_RANGE = (28, 38)
TOTAL_COUNT_RANGE = (63, 70)  # 上限70は支配下の上限
COUNT_JITTER_RATE = 0.30
POSITION_SWAP_RATE = 0.40
# 実在の最小〜最大に加えて守る下限
POSITION_FLOORS = {"捕手": 5, "遊撃手": 2, "外野手": 8}
# 野手数を合わせるときに増減するポジションの順
FIELDER_ADJUST_ORDER = ("外野手", "三塁手", "一塁手")
STARTER_RATIO_RANGE = (0.37, 0.65)
LEFT_PITCHER_RANGE = (5, 15)

# 年齢帯（実在CSVの age_* 列と同じ区切り）
AGE_BANDS = (("age_u22", 0, 22), ("age_23_25", 23, 25), ("age_26_29", 26, 29), ("age_30_33", 30, 33), ("age_34p", 34, 200))
AGE_BAND_LABELS = {"age_u22": "〜22歳", "age_23_25": "23〜25歳", "age_26_29": "26〜29歳", "age_30_33": "30〜33歳", "age_34p": "34歳〜"}
# 年齢帯の目標人数を、隣の年齢帯と1人入れ替える確率
AGE_BAND_SWAP_RATE = 0.5
# 選手格の目標人数（国内選手、投手・野手別）の端数の配り方に使う乱数
CLASS_TARGET_NAMESPACE = "team_mode_class_targets_v1"
# 型の目標人数（国内の野手全員・国内の先発）の端数の配り方に使う乱数
TYPE_TARGET_NAMESPACE = "team_mode_type_targets_v1"

# ---------------------------------------------------------------------------
# 戦力レベル（3-3）
# ---------------------------------------------------------------------------
STRENGTH_NAMESPACE = "team_mode_strength_v2"
# 球団ごとの散らばり_改修指示.md で調整し直した（選手格の人数を球団ごとに割り当てるようにしたうえで、
# 球団ごとの査定・能力の平均の散らばりを実在36チームに合わせた）。
# ・各レベルの範囲を狭め（中位 ±0.35 → ±0.25 など）、倍率の効きを弱めた（STRENGTH_REFERENCE_INDEX 0.7 → 1.1）。
#   その分、強豪の野手の倍率を強めて、強豪と中位の差（戦力レベルの判定 (e)）を保つ
STRENGTH_LEVELS = (
    ("強豪", 25, (0.55, 0.95)),
    ("中位", 50, (-0.25, 0.25)),
    ("弱小", 25, (-0.95, -0.50)),
)
STRENGTH_LABELS = tuple(label for label, _weight, _range in STRENGTH_LEVELS)
# 投手・野手の戦力指数 = s + N(0, STRENGTH_ROLE_SD)。±STRENGTH_ROLE_CLAMP に収める。
# 0 にした（倍率を弱めた分、投手指標と野手指標の相関が下がるため。投高打低・打高投低は選手の顔ぶれの偶然で出る）
STRENGTH_ROLE_SD = 0.0
STRENGTH_ROLE_CLAMP = 1.2
# 基準倍率は s = ±STRENGTH_REFERENCE_INDEX のときの値
STRENGTH_REFERENCE_INDEX = 1.1
PLAYER_CLASSES = ("スター級", "一軍主力級", "一軍控え級", "二軍級", "若手素材型", "ベテラン型")
STRONG_CLASS_BASE = {"スター級": 2.6, "一軍主力級": 1.55, "一軍控え級": 1.0, "二軍級": 1.0, "若手素材型": 1.0, "ベテラン型": 1.0}
# 役割ごとの強豪側の基準の上書き（書いていない選手格は STRONG_CLASS_BASE）。
# 投手の上位13人平均は選手ごとのばらつきが大きく、強豪と中位の差が埋もれやすいため、投手だけ強める
STRONG_CLASS_BASE_BY_ROLE: dict[str, dict[str, float]] = {"投手": {"スター級": 3.4, "一軍主力級": 1.8}}
# 弱小の二軍級・若手素材型の倍率は 1.0 にした（全員平均・投手の査定の平均だけが大きく動き、散らばりが実在より大きくなるため）
WEAK_CLASS_BASE = {"スター級": 0.3, "一軍主力級": 0.54, "一軍控え級": 1.0, "二軍級": 1.0, "若手素材型": 1.0, "ベテラン型": 1.0}
# 倍率1つずつにかける揺らぎ（球団ごとに1回）
CLASS_MULTIPLIER_JITTER = (0.9, 1.1)
# 全球団の国内選手にかける基準の倍率。個別生成（架空球団用）は1人ずつの分布を実在に合わせてあるが、
# 上位の選手が実在より少なく、球団の上位28人の査定が実在12球団より低くなるため、上位の選手格を少し増やす。
# 投手は、投手の査定の平均が実在（2024〜2026年版）より高かったため 一軍主力級 1.45 → 1.15 に下げた。
# 二軍級は 0.85 → 0.7（一軍主力級を減らすと日本人投手のコントロールが実在より約1低くなるため、二軍級を減らして戻す。
# check_pitcher_control.py の先発・左の平均、先発の左右差、日本人全体の平均。試した 0.6・0.8 ではどれかが外れた）
TEAM_BASE_CLASS_MULTIPLIERS: dict[str, dict[str, float]] = {
    "投手": {"スター級": 1.8, "一軍主力級": 1.15, "二軍級": 0.7},
    "野手": {"スター級": 1.3, "一軍主力級": 1.15},
}

# ---------------------------------------------------------------------------
# チームカラー（3-4）
# ---------------------------------------------------------------------------
COLOR_NAMESPACE = "team_mode_color_v2"
NO_COLOR = "特色なし"
COLOR_WEIGHTS = (
    (NO_COLOR, 30),
    ("投手王国", 12),
    ("強力打線", 12),
    ("機動力", 12),
    ("守備重視", 12),
    ("若手育成", 11),
    ("ベテラン重視", 11),
)
COLOR_LABELS = tuple(label for label, _weight in COLOR_WEIGHTS)
# 効き具合 t = 1.0 のときの倍率。倍率は 1 + (基準 − 1) × t で効かせる。
# class: 選手格、archetype: 選手の型、age_slope: 年齢の重みに exp(age_slope × t × (年齢 − AGE_PIVOT)) をかける。
# 球団ごとの散らばり_改修指示.md で、各カラーの目安（validate_team_mode.py）を満たす範囲で弱めた。
# ・投手王国: 二軍級・若手素材型 0.3 をやめ、スター級を中心にした（投手の上位の平均を上げつつ、投手の査定の平均を上げすぎない）。
#   一軍控え級を減らして二軍級を少し増やし、上位の層だけを厚くする
# ・若手育成・ベテラン重視: 選手格の倍率をやめ、年齢の傾きだけにした（若手育成の球団の査定が全体に約10下がっていたため）
COLOR_EFFECTS: dict[str, dict[str, Any]] = {
    NO_COLOR: {},
    "投手王国": {"class": {"投手": {"スター級": 6.0, "一軍主力級": 2.0, "一軍控え級": 0.7, "二軍級": 1.3}}},
    "強力打線": {"archetype": {"野手": {"長打": 2.6, "巧打": 1.6}}, "class": {"野手": {"一軍主力級": 1.15}}},
    "機動力": {"archetype": {"野手": {"俊足": 2.7, "長打": 0.7}}},
    "守備重視": {"archetype": {"野手": {"守備": 3.0, "強肩": 2.2}}},
    "若手育成": {"age_slope": -0.065},
    "ベテラン重視": {"age_slope": 0.05},
}
AGE_PIVOT = 27
COLOR_INTENSITY_RANGE = (0.5, 1.5)
SUB_COLOR_RATE = 0.25
SUB_COLOR_INTENSITY_RANGE = (0.3, 0.7)
OPPOSITE_COLORS = (frozenset({"若手育成", "ベテラン重視"}),)

# ---------------------------------------------------------------------------
# 背番号（3-7）
# ---------------------------------------------------------------------------
UNIFORM_NUMBER_NAMESPACE = "team_mode_uniform_number_v1"
UNIFORM_NUMBERS = ("0", "00", *(str(n) for n in range(1, 100)))
# 欠番の個数（実在12球団の分布）
RETIRED_COUNT_WEIGHTS = ((0, 1), (1, 3), (2, 2), (3, 2), (4, 1), (5, 2), (6, 1))
RETIRED_YOUNG_WEIGHT = 1.0   # 0、00、1〜30
RETIRED_OTHER_WEIGHT = 0.1   # 31〜69
UNIFORM_ORDER_JITTER = (0.85, 1.15)
UNIFORM_TOP_PERCENTILE = 0.75
UNIFORM_BOTTOM_PERCENTILE = 0.35
UNIFORM_BANDS = ("0-10", "11-21", "22-30", "31-69", "70-89", "90-99")
UNIFORM_TIER_MULTIPLIERS = {
    ("投手", "上位"): {"0-10": 1.0, "11-21": 3.0, "22-30": 1.2, "31-69": 0.6, "70-89": 1.0, "90-99": 0.5},
    ("投手", "中位"): {"70-89": 2.5, "90-99": 2.5},
    ("投手", "下位"): {"0-10": 1.0, "11-21": 0.25, "22-30": 1.0, "31-69": 1.3, "70-89": 0.5, "90-99": 0.5},
    ("野手", "上位"): {"0-10": 3.0, "11-21": 1.0, "22-30": 1.5, "31-69": 0.6, "70-89": 1.0, "90-99": 0.6},
    ("野手", "中位"): {"70-89": 2.5, "90-99": 2.5},
    ("野手", "下位"): {"0-10": 0.25, "11-21": 0.5, "22-30": 1.0, "31-69": 1.3, "70-89": 0.5, "90-99": 0.5},
}
# ↑ 書いていない番号の範囲は1.0。
# ・野手・下位の11〜21番は指示書の1.0から0.5に下げた（後半に残った12・13番などを野手が取り、11〜21番の投手率が90%を割るため）
# ・70〜98番は、実在では査定の百分位が平均0.37の選手（中位）が使う。下位の倍率（指示書では1.3・1.2）を1.0にしても
#   最下位の選手に偏ったまま（百分位0.25）だったため、中位を2.5、下位を0.5にした（背番号補正_改修指示.md §2-3）
UNIFORM_USAGE_PRIOR = 0.5
# 国内選手：実在の外国人率が高い番号を避ける（1 − ペナルティ × 外国人率、下限 UNIFORM_DOMESTIC_MIN_FACTOR）。
# 42番は外国人のいない球団でも国内選手が使えるよう弱め、99番は外国人の割合を上げるため強めにする
UNIFORM_DOMESTIC_PENALTY = 1.0
UNIFORM_DOMESTIC_PENALTY_BY_NUMBER: dict[str, float] = {"42": 0.8, "99": 1.2}
UNIFORM_DOMESTIC_MIN_FACTOR = 0.05
# 外国人：実在の「外国人の使用数」（CSVの foreign 列）を重みの基準にする。
# 重み ∝ (foreign + UNIFORM_FOREIGN_PRIOR) × その番号を使った選手のうち自分の区分（投手・捕手・内野手・外野手）の割合。
# foreign が0の番号（1・17・18・19番など、実在で外国人がいない番号）は UNIFORM_FOREIGN_ABSENT_MULTIPLIER をかけて大きく下げる。
UNIFORM_FOREIGN_PRIOR = 0.3
UNIFORM_FOREIGN_ABSENT_MULTIPLIER = 0.1
# 外国人の番号別の倍率。42番は実在で外国人の76%が付けるため、1球団約6人の外国人のだれかが取りやすくする
# 2.5 → 2.0（球団ごとの散らばり_改修指示.md。選手格の構成が変わり、42番の外国人の割合が 0.88 と実在 0.76 より高くなったため）
UNIFORM_FOREIGN_NUMBER_MULTIPLIERS: dict[str, float] = {"42": 2.0}
# 外国人には査定の順位の倍率（UNIFORM_TIER_MULTIPLIERS）をかけない。実在の外国人の使用数に能力の傾向が含まれていて、
# かけると外国人が11〜21番・0〜10番に寄りすぎる
UNIFORM_FOREIGN_USE_TIER = False
# 年齢の連続な倍率 exp(γ × (年齢 − UNIFORM_AGE_PIVOT) / 5)。γ は番号の範囲ごと、27歳より若い側と上の側で別の値
# （27歳で1.0になり、段差はない）。若手は小さい番号を避けて31〜69番へ、ベテランは小さい番号へ寄る。
# 例: 23歳は 0〜10番 ×0.62、31〜69番 ×1.32。32歳は 0〜10番 ×2.01、11〜21番 ×1.82、31〜69番 ×0.67。
# 0〜10番の上側 0.5 → 0.7、11〜21番の上側 0.5 → 0.6、22〜30番 (0.3, 0.4) → (0.45, 0.55)（球団ごとの散らばり_改修指示.md。若手育成・ベテラン重視の年齢の傾きを
# 弱めたなどで、日本人野手の0〜10番の31歳以上の割合と22〜30番の平均年齢が実在を下回ったため。22〜30番を上げると
# 日本人投手の22〜30番の平均年齢が上限を超えるので、11〜21番の上側も上げてベテランの投手を11〜21番へ寄せる）
UNIFORM_AGE_PIVOT = 27
UNIFORM_AGE_GAMMA: dict[str, tuple[float, float]] = {
    # 番号の範囲: (27歳より若い側の γ, 27歳より上の側の γ)
    "0-10": (0.6, 0.7),
    "11-21": (0.6, 0.6),
    "22-30": (0.45, 0.55),
    "31-69": (-0.35, -0.4),
    "70-89": (0.0, 0.0),
    "90-99": (0.0, 0.0),
}
# 70〜98番の国内選手の倍率。CSVの使用数だけだと、後半に割り当てる選手が空いている0〜69番より
# 70〜98番を選びやすく、70〜98番の使用数が実在（平均5.2個）より多くなるため下げる（99番は対象外）。
UNIFORM_HIGH_NUMBER_MULTIPLIER = 0.35
# 外国人の70〜98番の倍率（外国人の重みは実在の外国人の使用数なので、国内選手より弱めにかける）
UNIFORM_HIGH_NUMBER_FOREIGN_MULTIPLIER = 0.6

# 査定指標（3-3(4)）。上位28人は一軍登録の人数の目安
TOP_TEAM_COUNT = 28
TOP_PITCHER_COUNT = 13
TOP_FIELDER_COUNT = 15


def make_sub_rng(seed: int, namespace: str) -> random.Random:
    """app.make_sub_rng と同じ方式（呼び出し側の乱数を消費しない名前空間付きの乱数）。"""
    payload = f"{int(seed)}:{namespace}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _weighted(rng: random.Random, items: Any) -> Any:
    items = list(items)
    return rng.choices([item[0] for item in items], weights=[item[1] for item in items], k=1)[0]


# ---------------------------------------------------------------------------
# 実在データ
# ---------------------------------------------------------------------------
def _to_number(value: str) -> int | float | None:
    value = (value or "").strip()
    if not value:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


@lru_cache(maxsize=1)
def load_team_templates(path: str = str(TEAM_COMPOSITION_PATH)) -> tuple[dict[str, Any], ...]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append({key: (value if key == "team" else _to_number(value)) for key, value in row.items()})
    return tuple(rows)


@lru_cache(maxsize=1)
def load_uniform_number_stats(path: str = str(UNIFORM_NUMBER_PATH)) -> dict[str, dict[str, float]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        stats = {}
        for row in csv.DictReader(f):
            number = str(row["number"]).strip()
            stats[number] = {key: float(value) if value not in ("", None) else 0.0 for key, value in row.items() if key != "number"}
    return stats


def real_composition_values(column: str) -> list[float]:
    """構成項目の実在の値。抑え・先発の適性は2022〜2025年版、年齢帯は2026年版だけを使う。"""
    rows = load_team_templates()
    if column in ("closer_aptitude", "starter_aptitude"):
        rows = tuple(row for row in rows if row["season"] != 2026)
    return [float(row[column]) for row in rows if row.get(column) is not None]


def real_composition_range(column: str) -> tuple[float, float]:
    values = real_composition_values(column)
    return (min(values), max(values)) if values else (0.0, 0.0)


# ---------------------------------------------------------------------------
# 構成テンプレートと揺らぎ
# ---------------------------------------------------------------------------
def choose_template(rng: random.Random) -> dict[str, Any]:
    templates = load_team_templates()
    return _weighted(rng, [(row, TEMPLATE_SEASON_WEIGHTS.get(int(row["season"]), 1.0)) for row in templates])


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _jitter_count(rng: random.Random, value: int) -> int:
    if rng.random() < COUNT_JITTER_RATE:
        return value + rng.choice((-1, 1))
    return value


def position_bounds() -> dict[str, tuple[int, int]]:
    bounds = {}
    for position, column in POSITION_COLUMNS.items():
        low, high = real_composition_range(column)
        bounds[position] = (max(int(low), POSITION_FLOORS.get(position, 0)), int(high))
    return bounds


def fit_fielder_positions(positions: dict[str, int], total: int, bounds: dict[str, tuple[int, int]]) -> dict[str, int]:
    """ポジション別人数の合計を野手数に合わせる。外野手 → 三塁手 → 一塁手の順に増減する。"""
    positions = dict(positions)
    order = list(FIELDER_ADJUST_ORDER) + [position for position in FIELDER_POSITIONS if position not in FIELDER_ADJUST_ORDER]
    while sum(positions.values()) < total:
        target = next((p for p in order if positions[p] < bounds[p][1]), order[0])
        positions[target] += 1
    while sum(positions.values()) > total:
        target = next((p for p in order if positions[p] > bounds[p][0]), None)
        if target is None:
            target = next(p for p in order if positions[p] > 0)
        positions[target] -= 1
    return positions


def build_team_targets(team_seed: int) -> dict[str, Any]:
    """実在60チームから1つをテンプレートとして選び、少し揺らして目標の人数を作る。"""
    rng = make_sub_rng(team_seed, TEMPLATE_NAMESPACE)
    template = choose_template(rng)
    pitchers = int(_clamp(_jitter_count(rng, int(template["pitchers"])), *PITCHER_COUNT_RANGE))
    fielders = int(_clamp(_jitter_count(rng, int(template["fielders"])), *FIELDER_COUNT_RANGE))
    while pitchers + fielders > TOTAL_COUNT_RANGE[1]:
        if fielders > FIELDER_COUNT_RANGE[0] and (fielders >= pitchers or pitchers <= PITCHER_COUNT_RANGE[0]):
            fielders -= 1
        else:
            pitchers -= 1
    while pitchers + fielders < TOTAL_COUNT_RANGE[0]:
        if fielders < pitchers and fielders < FIELDER_COUNT_RANGE[1]:
            fielders += 1
        else:
            pitchers += 1

    bounds = position_bounds()
    positions = {position: int(template[column]) for position, column in POSITION_COLUMNS.items()}
    positions = fit_fielder_positions(positions, fielders, bounds)
    if rng.random() < POSITION_SWAP_RATE:
        donors = [p for p in FIELDER_POSITIONS if positions[p] - 1 >= bounds[p][0]]
        if donors:
            donor = rng.choice(donors)
            receivers = [p for p in FIELDER_POSITIONS if p != donor and positions[p] + 1 <= bounds[p][1]]
            if receivers:
                receiver = rng.choice(receivers)
                positions[donor] -= 1
                positions[receiver] += 1

    ratio = _clamp(float(template["main_starter"]) / float(template["pitchers"]), *STARTER_RATIO_RANGE)
    starters = round(pitchers * ratio) + rng.choice((-1, 0, 1))
    starters = int(_clamp(starters, 1, pitchers - 1))
    left = int(_clamp(int(template["left_pitchers"]) + rng.choice((-1, 0, 1)), *LEFT_PITCHER_RANGE))
    left = min(left, pitchers)
    foreign = {"投手": min(int(template["foreign_pitchers"]), pitchers), "野手": min(int(template["foreign_fielders"]), fielders)}
    return {
        "template": {"season": int(template["season"]), "team": str(template["team"])},
        "total": pitchers + fielders,
        "pitchers": pitchers,
        "fielders": fielders,
        "pitcher_targets": {"先発": starters, "救援": pitchers - starters, "左投": left},
        "fielder_targets": positions,
        "foreign_targets": foreign,
    }


def age_band_of(age: int) -> str:
    for band, low, high in AGE_BANDS:
        if low <= int(age) <= high:
            return band
    return AGE_BANDS[-1][0]


def real_age_band_shares() -> dict[str, float]:
    """実在（2026年版12球団）の年齢帯ごとの人数の割合。"""
    means = {band: statistics.fmean(real_composition_values(band)) for band, _low, _high in AGE_BANDS}
    total = sum(means.values())
    return {band: value / total for band, value in means.items()}


def age_band_tilts(base_items: list[tuple[int, float]], tilted_items: list[tuple[int, float]]) -> dict[str, float]:
    """年齢の重みを傾けたとき（若手育成・ベテラン重視）の、年齢帯ごとの重みの増減の比。"""
    base = {band: 0.0 for band, _low, _high in AGE_BANDS}
    tilted = dict(base)
    for (age, weight), (_age, tilted_weight) in zip(base_items, tilted_items):
        base[age_band_of(age)] += weight
        tilted[age_band_of(age)] += tilted_weight
    return {band: (tilted[band] / base[band]) if base[band] else 1.0 for band in base}


def age_band_targets(
    domestic_count: int,
    foreign_counts: dict[str, int],
    base_age_items: list[tuple[int, float]],
    tilted_age_items: list[tuple[int, float]],
    rng: random.Random,
) -> dict[str, int]:
    """国内選手の年齢帯ごとの目標人数を作る。

    球団全体（外国人を含む）の年齢帯の割合を実在に合わせ、そこから先に作った外国人の分を引く。
    若手育成・ベテラン重視の傾きは、年齢帯の割合にかける。最後に隣の年齢帯と1人入れ替えて揺らす。
    """
    shares = real_age_band_shares()
    tilts = age_band_tilts(base_age_items, tilted_age_items)
    weighted = {band: shares[band] * tilts[band] for band in shares}
    whole = sum(weighted.values()) or 1.0
    total = domestic_count + sum(foreign_counts.get(band, 0) for band in shares)
    expected = {band: max(0.0, total * weighted[band] / whole - foreign_counts.get(band, 0)) for band in shares}
    scale = domestic_count / (sum(expected.values()) or 1.0)
    expected = {band: value * scale for band, value in expected.items()}
    targets = {band: int(math.floor(value)) for band, value in expected.items()}
    remainder = sorted(expected, key=lambda band: expected[band] - targets[band], reverse=True)
    for band in remainder[: domestic_count - sum(targets.values())]:
        targets[band] += 1
    if domestic_count > 0 and rng.random() < AGE_BAND_SWAP_RATE:
        bands = [band for band, _low, _high in AGE_BANDS]
        index = rng.randrange(len(bands) - 1)
        donor, receiver = (bands[index], bands[index + 1]) if rng.random() < 0.5 else (bands[index + 1], bands[index])
        if targets[donor] > 0:
            targets[donor] -= 1
            targets[receiver] += 1
    return targets


def round_expected_counts(expected: dict[str, float], total: int, rng: random.Random) -> dict[str, int]:
    """期待値を合計 total の整数に丸める（最大剰余法。切り捨てた後の残りを、端数に比例する確率で配る）。

    端数は系統抽出で配る（端数を並べた数直線に、乱数で決めた始点から間隔1で印を付ける）。
    各項目が切り上げになる確率はちょうど端数と同じなので、平均の人数は期待値のまま変わらない。
    """
    whole = sum(expected.values())
    scaled = {key: (value * total / whole if whole > 0 else 0.0) for key, value in expected.items()}
    targets = {key: int(math.floor(value)) for key, value in scaled.items()}
    rest = total - sum(targets.values())
    position = rng.random()
    cumulative = 0.0
    for key in scaled:
        if rest <= 0:
            break
        cumulative += scaled[key] - targets[key]
        if cumulative > position:
            targets[key] += 1
            position += 1.0
            rest -= 1
    # 浮動小数の誤差で配り切れなかった分は、端数の大きい順に足す
    for key in sorted(scaled, key=lambda k: scaled[k] - math.floor(scaled[k]), reverse=True)[:max(0, rest)]:
        targets[key] += 1
    return targets


def class_targets(expected_by_role: dict[str, dict[str, float]], counts_by_role: dict[str, int], rng: random.Random) -> dict[str, dict[str, int]]:
    """国内選手の選手格ごとの目標人数（役割 → 選手格 → 人数）。期待値の計算は app.team_class_expected。"""
    return {role: round_expected_counts(expected_by_role[role], counts_by_role[role], rng) for role in ("投手", "野手")}


def class_band_shares(age_items: list[tuple[int, float]], class_items_by_age: dict[int, list[tuple[str, int]]]) -> dict[str, dict[str, float]]:
    """年齢帯 → 選手格 → その年齢帯の中で、その選手格になる確率。"""
    shares: dict[str, dict[str, float]] = {}
    for band, _low, _high in AGE_BANDS:
        items = [(age, weight) for age, weight in age_items if age_band_of(age) == band and weight > 0]
        band_weight = sum(weight for _age, weight in items)
        bucket = shares.setdefault(band, {})
        for age, weight in items:
            labels = class_items_by_age.get(age, [])
            class_total = sum(value for _label, value in labels)
            for label, value in labels:
                bucket[label] = bucket.get(label, 0.0) + (weight / band_weight) * (value / class_total)
    return shares


def assignment_feasible(demands: dict[Any, int], capacities: dict[str, int], allowed: dict[Any, set[str]]) -> bool:
    """残りの人数（demands: 選手格などの区分 → 人数）を、残りの年齢帯の枠（capacities）に、
    allowed（区分 → 入れてよい年齢帯）を守って全部割り当てられるか（最大流）。"""
    need = {key: count for key, count in demands.items() if count > 0}
    total = sum(need.values())
    if total == 0:
        return True
    capacity = {band: max(0, count) for band, count in capacities.items()}
    if total > sum(capacity.values()):
        return False
    # 区分 → 年齢帯の流量
    flow: dict[tuple[Any, str], int] = {}
    sent = {key: 0 for key in need}
    used = {band: 0 for band in capacity}

    def augment() -> bool:
        # 区分（まだ送り切っていない）から、空きのある年齢帯までの増加路を幅優先で探す
        parents: dict[Any, Any] = {}
        queue = [("k", key) for key in need if sent[key] < need[key]]
        seen = set(queue)
        while queue:
            node = queue.pop(0)
            kind, name = node
            if kind == "k":
                for band in allowed.get(name, ()):
                    nxt = ("b", band)
                    if band in capacity and nxt not in seen:
                        seen.add(nxt)
                        parents[nxt] = node
                        if used[band] < capacity[band]:
                            # 増加路が見つかった
                            cur = nxt
                            while cur in parents:
                                prev = parents[cur]
                                if prev[0] == "k":
                                    flow[(prev[1], cur[1])] = flow.get((prev[1], cur[1]), 0) + 1
                                else:
                                    flow[(cur[1], prev[1])] -= 1
                                cur = prev
                            sent[cur[1]] += 1
                            used[band] += 1
                            return True
                        queue.append(nxt)
            else:
                # 年齢帯から、そこへ流している区分へ戻る（流量の付け替え）
                for (key, band), amount in flow.items():
                    nxt = ("k", key)
                    if band == name and amount > 0 and nxt not in seen:
                        seen.add(nxt)
                        parents[nxt] = node
                        queue.append(nxt)
        return False

    for _ in range(total):
        if not augment():
            return False
    return True


# ---------------------------------------------------------------------------
# 戦力レベルとチームカラー
# ---------------------------------------------------------------------------
@dataclass
class TeamProfile:
    strength: str
    strength_index: float
    strength_index_pitcher: float
    strength_index_fielder: float
    color: str
    color_intensity: float
    sub_color: str
    sub_color_intensity: float
    # 合成済みの最終的な倍率（役割 → 選手格／型 → 倍率）
    player_class_multipliers: dict[str, dict[str, float]] = field(default_factory=dict)
    archetype_multipliers: dict[str, dict[str, float]] = field(default_factory=dict)
    # 年齢の重みの傾き（若手育成・ベテラン重視）。0なら年齢分布は変えない
    age_slope: float = 0.0

    def age_weight_items(self, items: list[tuple[int, float]]) -> list[tuple[int, float]]:
        if not self.age_slope:
            return list(items)
        return [(age, weight * math.exp(self.age_slope * (age - AGE_PIVOT))) for age, weight in items]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TeamProfile":
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})

    @property
    def color_display(self) -> str:
        return f"{self.color}＋{self.sub_color}" if self.sub_color else self.color


def strength_class_multiplier(player_class: str, index: float, role: str = "") -> float:
    if index >= 0:
        base = {**STRONG_CLASS_BASE, **STRONG_CLASS_BASE_BY_ROLE.get(role, {})}
        return base.get(player_class, 1.0) ** (index / STRENGTH_REFERENCE_INDEX)
    return WEAK_CLASS_BASE.get(player_class, 1.0) ** (-index / STRENGTH_REFERENCE_INDEX)


def scaled_multiplier(base: float, intensity: float) -> float:
    return 1.0 + (base - 1.0) * intensity


def color_multipliers(color: str, intensity: float, kind: str) -> dict[str, dict[str, float]]:
    effects = COLOR_EFFECTS.get(color, {}).get(kind, {})
    return {role: {label: scaled_multiplier(base, intensity) for label, base in values.items()} for role, values in effects.items()}


def _merge_multipliers(target: dict[str, dict[str, float]], extra: dict[str, dict[str, float]]) -> None:
    for role, values in extra.items():
        bucket = target.setdefault(role, {})
        for label, value in values.items():
            bucket[label] = bucket.get(label, 1.0) * value


def build_team_profile(
    team_seed: int,
    *,
    strength: str | None = None,
    strength_index: float | None = None,
    color: str | None = None,
    color_intensity: float | None = None,
    sub_color: str | None = None,
    sub_color_intensity: float | None = None,
) -> TeamProfile:
    """team_seed から戦力とカラーを決める。キーワード引数は検証スクリプトでの固定用（画面からは使わない）。

    上書きの有無に関係なく乱数は同じ順に全部引くので、上書きしなかった項目は通常と同じ値になる。
    """
    rng = make_sub_rng(team_seed, STRENGTH_NAMESPACE)
    drawn_level = _weighted(rng, [(label, weight) for label, weight, _range in STRENGTH_LEVELS])
    level_range = dict((label, value_range) for label, _weight, value_range in STRENGTH_LEVELS)[drawn_level]
    drawn_index = rng.uniform(*level_range)
    pitcher_noise = rng.gauss(0.0, STRENGTH_ROLE_SD)
    fielder_noise = rng.gauss(0.0, STRENGTH_ROLE_SD)
    jitter = {role: {label: rng.uniform(*CLASS_MULTIPLIER_JITTER) for label in PLAYER_CLASSES} for role in ("投手", "野手")}
    level = strength or drawn_level
    if strength_index is not None:
        index = float(strength_index)
    elif strength and strength != drawn_level:
        # レベルだけ固定したときは、そのレベルの範囲で同じ位置の値にする
        low, high = dict((label, value_range) for label, _weight, value_range in STRENGTH_LEVELS)[strength]
        old_low, old_high = level_range
        index = low + (drawn_index - old_low) / (old_high - old_low) * (high - low)
    else:
        index = drawn_index
    index_pitcher = _clamp(index + pitcher_noise, -STRENGTH_ROLE_CLAMP, STRENGTH_ROLE_CLAMP)
    index_fielder = _clamp(index + fielder_noise, -STRENGTH_ROLE_CLAMP, STRENGTH_ROLE_CLAMP)

    color_rng = make_sub_rng(team_seed, COLOR_NAMESPACE)
    drawn_color = _weighted(color_rng, COLOR_WEIGHTS)
    drawn_intensity = color_rng.uniform(*COLOR_INTENSITY_RANGE)
    has_sub = color_rng.random() < SUB_COLOR_RATE
    sub_draw = color_rng.random()
    drawn_sub_intensity = color_rng.uniform(*SUB_COLOR_INTENSITY_RANGE)
    main_color = color or drawn_color
    intensity = drawn_intensity if color_intensity is None else float(color_intensity)
    if sub_color is not None:
        chosen_sub = sub_color
    elif main_color != NO_COLOR and has_sub:
        candidates = [
            (label, weight) for label, weight in COLOR_WEIGHTS
            if label not in (NO_COLOR, main_color) and frozenset({label, main_color}) not in OPPOSITE_COLORS
        ]
        total = sum(weight for _label, weight in candidates)
        cumulative = 0.0
        chosen_sub = candidates[-1][0]
        for label, weight in candidates:
            cumulative += weight / total
            if sub_draw < cumulative:
                chosen_sub = label
                break
    else:
        chosen_sub = ""
    sub_intensity = (drawn_sub_intensity if sub_color_intensity is None else float(sub_color_intensity)) if chosen_sub else 0.0

    class_multipliers: dict[str, dict[str, float]] = {}
    for role, role_index in (("投手", index_pitcher), ("野手", index_fielder)):
        base = TEAM_BASE_CLASS_MULTIPLIERS.get(role, {})
        class_multipliers[role] = {
            label: base.get(label, 1.0) * strength_class_multiplier(label, role_index, role) * jitter[role][label] for label in PLAYER_CLASSES
        }
    archetype_multipliers: dict[str, dict[str, float]] = {}
    age_slope = 0.0
    for name, value in ((main_color, intensity), (chosen_sub, sub_intensity)):
        if not name:
            continue
        _merge_multipliers(class_multipliers, color_multipliers(name, value, "class"))
        _merge_multipliers(archetype_multipliers, color_multipliers(name, value, "archetype"))
        age_slope += COLOR_EFFECTS.get(name, {}).get("age_slope", 0.0) * value
    return TeamProfile(
        strength=level,
        strength_index=round(index, 4),
        strength_index_pitcher=round(index_pitcher, 4),
        strength_index_fielder=round(index_fielder, 4),
        color=main_color,
        color_intensity=round(intensity, 4),
        sub_color=chosen_sub,
        sub_color_intensity=round(sub_intensity, 4),
        player_class_multipliers={role: {k: round(v, 4) for k, v in values.items()} for role, values in class_multipliers.items()},
        archetype_multipliers={role: {k: round(v, 4) for k, v in values.items()} for role, values in archetype_multipliers.items()},
        age_slope=round(age_slope, 5),
    )


# ---------------------------------------------------------------------------
# 背番号
# ---------------------------------------------------------------------------
def uniform_number_sort_key(number: Any) -> tuple[int, int]:
    """0 → 00 → 1 → 2 … → 99 の順。番号でない値は最後。"""
    text = str(number if number is not None else "").strip()
    if not text.isdigit():
        return (10_000, 0)
    return (int(text), len(text))


def uniform_number_band(number: str) -> str:
    value = int(number)
    if number == "00" or value <= 10:
        return "0-10"
    if value <= 21:
        return "11-21"
    if value <= 30:
        return "22-30"
    if value <= 69:
        return "31-69"
    if value <= 89:
        return "70-89"
    return "90-99"


def uniform_player_group(player: dict[str, Any]) -> str:
    """実在CSVの列（pitcher / catcher / infielder / outfielder）。"""
    if player.get("role") == "投手":
        return "pitcher"
    position = str(player.get("position", ""))
    if position == "捕手":
        return "catcher"
    if position in INFIELD_POSITIONS:
        return "infielder"
    return "outfielder"


def choose_retired_numbers(rng: random.Random) -> list[str]:
    count = _weighted(rng, RETIRED_COUNT_WEIGHTS)
    candidates = [(number, RETIRED_YOUNG_WEIGHT if number == "00" or int(number) <= 30 else RETIRED_OTHER_WEIGHT)
                  for number in UNIFORM_NUMBERS if number == "00" or int(number) <= 69]
    chosen: list[str] = []
    for _ in range(count):
        number = _weighted(rng, candidates)
        chosen.append(number)
        candidates = [(n, w) for n, w in candidates if n != number]
    return sorted(chosen, key=uniform_number_sort_key)


def role_percentiles(players: list[dict[str, Any]]) -> list[float]:
    """投手同士・野手同士の査定の百分位（0が最下位、1が最上位）。"""
    percentiles = [0.5] * len(players)
    for role in ("投手", "野手"):
        indexes = [i for i, player in enumerate(players) if (player.get("role") == "投手") == (role == "投手")]
        ordered = sorted(indexes, key=lambda i: (player_rating(players[i]), -i))
        for rank, index in enumerate(ordered):
            percentiles[index] = rank / (len(ordered) - 1) if len(ordered) > 1 else 0.5
    return percentiles


def uniform_age_multiplier(band: str, age: int) -> float:
    young_gamma, old_gamma = UNIFORM_AGE_GAMMA.get(band, (0.0, 0.0))
    gamma = young_gamma if age < UNIFORM_AGE_PIVOT else old_gamma
    return math.exp(gamma * (age - UNIFORM_AGE_PIVOT) / 5)


def uniform_number_weight(number: str, player: dict[str, Any], percentile: float, stats: dict[str, dict[str, float]]) -> float:
    row = stats.get(number, {})
    group = uniform_player_group(player)
    used = sum(row.get(key, 0.0) for key in ("pitcher", "catcher", "infielder", "outfielder"))
    ratio = row.get("foreign", 0.0) / used if used else 0.0
    if player.get("roster_origin") == "foreign_import":
        foreign = row.get("foreign", 0.0)
        group_share = (row.get(group, 0.0) + UNIFORM_USAGE_PRIOR) / (used + 4 * UNIFORM_USAGE_PRIOR)
        weight = (foreign + UNIFORM_FOREIGN_PRIOR) * group_share * UNIFORM_FOREIGN_NUMBER_MULTIPLIERS.get(number, 1.0)
        if foreign <= 0:
            weight *= UNIFORM_FOREIGN_ABSENT_MULTIPLIER
    else:
        weight = row.get(group, 0.0) + UNIFORM_USAGE_PRIOR
        weight *= max(UNIFORM_DOMESTIC_MIN_FACTOR, 1 - UNIFORM_DOMESTIC_PENALTY_BY_NUMBER.get(number, UNIFORM_DOMESTIC_PENALTY) * ratio)
    role = "投手" if player.get("role") == "投手" else "野手"
    tier = "上位" if percentile >= UNIFORM_TOP_PERCENTILE else "下位" if percentile < UNIFORM_BOTTOM_PERCENTILE else "中位"
    band = uniform_number_band(number)
    if UNIFORM_FOREIGN_USE_TIER or player.get("roster_origin") != "foreign_import":
        weight *= UNIFORM_TIER_MULTIPLIERS.get((role, tier), {}).get(band, 1.0)
    if number != "00" and 70 <= int(number) <= 98:
        weight *= UNIFORM_HIGH_NUMBER_FOREIGN_MULTIPLIER if player.get("roster_origin") == "foreign_import" else UNIFORM_HIGH_NUMBER_MULTIPLIER
    weight *= uniform_age_multiplier(band, int(player.get("age") or UNIFORM_AGE_PIVOT))
    return max(weight, 1e-9)


def assign_uniform_numbers(players: list[dict[str, Any]], team_seed: int) -> list[str]:
    """全員に背番号（文字列）を付け、欠番の一覧を返す。"""
    stats = load_uniform_number_stats()
    rng = make_sub_rng(team_seed, UNIFORM_NUMBER_NAMESPACE)
    retired = choose_retired_numbers(rng)
    available = [number for number in UNIFORM_NUMBERS if number not in set(retired)]
    if len(players) > len(available):
        raise ValueError("背番号が足りません。")
    percentiles = role_percentiles(players)
    order_keys = [percentiles[i] * rng.uniform(*UNIFORM_ORDER_JITTER) for i in range(len(players))]
    order = sorted(range(len(players)), key=lambda i: (-order_keys[i], i))
    for index in order:
        player = players[index]
        weights = [(number, uniform_number_weight(number, player, percentiles[index], stats)) for number in available]
        number = _weighted(rng, weights)
        player["uniform_number"] = number
        available.remove(number)
    return retired


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------
COMPOSITION_ITEMS = (
    ("total", "総数"),
    ("pitchers", "投手"),
    ("fielders", "野手"),
    ("pos_C", "捕手"),
    ("pos_1B", "一塁手"),
    ("pos_2B", "二塁手"),
    ("pos_3B", "三塁手"),
    ("pos_SS", "遊撃手"),
    ("pos_OF", "外野手"),
    ("main_starter", "先発"),
    ("main_reliever", "救援"),
    ("left_pitchers", "左投手"),
    ("foreign", "外国人"),
    ("foreign_pitchers", "外国人投手"),
    ("foreign_fielders", "外国人野手"),
    ("closer_aptitude", "抑え適性あり"),
    ("starter_aptitude", "先発適性あり"),
    ("fielder_bat_left", "野手 左打"),
    ("fielder_bat_switch", "野手 両打"),
    ("fielder_RL", "野手 右投左打"),
    ("fielder_throw_left", "野手 左投"),
    *((band, f"年齢 {AGE_BAND_LABELS[band]}") for band, _low, _high in AGE_BANDS),
)


def is_foreign_import(player: dict[str, Any]) -> bool:
    return player.get("roster_origin") == "foreign_import"


def team_composition_counts(players: list[dict[str, Any]]) -> dict[str, int]:
    pitchers = [p for p in players if p.get("role") == "投手"]
    fielders = [p for p in players if p.get("role") != "投手"]
    counts = {
        "total": len(players),
        "pitchers": len(pitchers),
        "fielders": len(fielders),
        "foreign": sum(is_foreign_import(p) for p in players),
        "foreign_pitchers": sum(is_foreign_import(p) for p in pitchers),
        "foreign_fielders": sum(is_foreign_import(p) for p in fielders),
        "left_pitchers": sum(str(p.get("batting_throwing", "")).startswith("左投") for p in pitchers),
        "main_starter": sum(p.get("position") == "先発" for p in pitchers),
        "main_reliever": sum(p.get("position") != "先発" for p in pitchers),
        "closer_aptitude": sum(str(p.get("closer_aptitude", "-")) in ("◎", "○") for p in pitchers),
        "starter_aptitude": sum(str(p.get("starter_aptitude", "-")) in ("◎", "○") for p in pitchers),
        "fielder_bat_left": sum(str(p.get("batting_throwing", "")).endswith("左打") for p in fielders),
        "fielder_bat_switch": sum(str(p.get("batting_throwing", "")).endswith("両打") for p in fielders),
        "fielder_RL": sum(str(p.get("batting_throwing", "")) == "右投左打" for p in fielders),
        "fielder_throw_left": sum(str(p.get("batting_throwing", "")).startswith("左投") for p in fielders),
    }
    for position, column in POSITION_COLUMNS.items():
        counts[column] = sum(p.get("position") == position for p in fielders)
    for band, _low, _high in AGE_BANDS:
        counts[band] = sum(age_band_of(int(p.get("age") or 0)) == band for p in players)
    return counts


def _top_mean(values: list[int], count: int) -> float:
    top = sorted(values, reverse=True)[:count]
    return float(statistics.fmean(top)) if top else 0.0


def team_rating_metrics(players: list[dict[str, Any]]) -> dict[str, float]:
    ratings = [player_rating(p) for p in players]
    pitcher_ratings = [r for r, p in zip(ratings, players) if p.get("role") == "投手"]
    fielder_ratings = [r for r, p in zip(ratings, players) if p.get("role") != "投手"]
    return {
        "top28": _top_mean(ratings, TOP_TEAM_COUNT),
        "all": float(statistics.fmean(ratings)) if ratings else 0.0,
        "pitcher_top": _top_mean(pitcher_ratings, TOP_PITCHER_COUNT),
        "fielder_top": _top_mean(fielder_ratings, TOP_FIELDER_COUNT),
    }


def average_age(players: list[dict[str, Any]]) -> float:
    ages = [int(p.get("age") or 0) for p in players]
    return float(statistics.fmean(ages)) if ages else 0.0
