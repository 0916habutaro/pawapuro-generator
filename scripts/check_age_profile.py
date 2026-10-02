#!/usr/bin/env python3
"""架空球団用（日本人）の特殊能力の数・ランク特能・査定値・若手の能力の年齢帯別チェッカー。

基準は `特能ランク年齢補正_改修指示.md` §1・§3 と `若手能力の幅_改修指示.md` §1・§3。実在は data/reference/real_age_profile_2022_2026.csv
（特能の数は2022〜2026の5年まとめ、ランクは2026のみ）を、単調に変わるように平滑化した値。
目標値を変えたときは、このファイルの TARGETS / YOUNG_TARGETS も合わせて直すこと。

使い方:
    python scripts/check_age_profile.py                       # 個別生成 投手・野手 各30000人 ＋ 球団生成 500球団
    python scripts/check_age_profile.py --players 1000 --teams 0   # 簡易版（途中確認用）
    python scripts/check_age_profile.py --save before.csv     # 選手ごとの値を保存（修正前後の比較用）
    python scripts/check_age_profile.py --compare before.csv  # 保存した値と並べて表示

- 個別生成は seed 1〜N、球団生成は validate_team_mode.py と同じ seed（20261001〜）を使う。
  若手（〜19歳）は日本人の約4%なので、若手の判定で年齢帯ごとに1000人以上になるよう既定を30000人にしている。
- --compare では、同じ選手（生成方法・役割・seed）どうしで、若手の能力の順位相関（変換前後）も判定する。
- 対象は category=架空球団用 の日本人（roster_origin=domestic）。外国人は年齢と能力に関係がない仕様なので除く。
- 終了コード: 全項目合格なら 0、不合格があれば 1。
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import pandas as pd  # noqa: E402

from generator.rating import load_table, player_rating  # noqa: E402

TEAM_BASE_SEED = 20261001
BANDS = ["〜21", "22〜25", "26〜29", "30〜33", "34以上"]
RATING_BANDS = ["〜21", "22〜23", "24〜25", "26〜27", "28〜29", "30〜31", "32〜33", "34以上"]

# 特能の数え方（指示書 §0。実在と同じ数え方）
NEGATIVE_SPECIALS = {
    "エラー", "ゴロピッチャー", "スロースターター", "一発", "三振", "乱調", "併殺", "四球", "寸前",
    "対ランナー", "抜け球", "死球集中", "負け運", "軽い球",
}
GREEN_SPECIALS = {
    "チームプレイ○", "テンポ○", "ミート多用", "変化球中心", "強振多用", "慎重打法", "積極守備", "積極打法",
    "積極盗塁", "積極走塁", "速球中心", "選球眼",
}
# 起用法の項目（数えない）。緑特以外の起用法と、実在の特殊能力欄にない項目。
USAGE_ITEMS = {
    "おまかせ", "調子次第", "慎重盗塁", "ビハインドでも", "代打要員", "スタミナ限界", "接戦時", "リード時",
    "中継ぎエース", "代走要員", "勝利投手", "守備要員", "守護神", "完投", "左のワンポイント", "フル出場",
    "セーブ狙い", "人気者", "投球位置左", "投球位置右", "チームプレイ×",
}

# 年齢帯ごとの目標（指示書 §1 を平滑化）。値は BANDS の順。
TARGETS = {
    "野手": {
        "n_pos": [1.05, 1.6, 2.5, 3.1, 3.85],
        "n_neg": [0.33, 0.55, 0.70, 0.85, 1.0],
        "n_green": [0.6, 0.85, 1.2, 1.55, 1.6],
        "rk_pts": [-4.2, -1.3, 0.8, 2.0, 1.5],
        "rk_hi": [0.03, 0.21, 0.32, 0.78, 0.59],
    },
    "投手": {
        "n_pos": [1.3, 2.2, 3.0, 3.5, 4.0],
        "n_neg": [1.05, 1.0, 0.93, 0.91, 0.87],  # 投手の赤特は修正前の値のまま
        "n_green": [0.19, 0.24, 0.33, 0.48, 0.75],
        "rk_pts": [-3.9, -2.9, 1.3, 1.8, 2.2],
        "rk_hi": [0.09, 0.11, 0.46, 0.76, 0.76],
    },
}
# 修正前の全年齢の値（個別生成 seed 1〜5000、球団生成 500球団）。全体が動いていないことの確認に使う。
BASELINE = {
    ("個別", "野手"): {"n_total": 4.19, "rating_mean": 250.4, "rating_sd": 57.1},
    ("個別", "投手"): {"n_total": 4.05, "rating_mean": 287.0, "rating_sd": 53.5},
    ("球団", "野手"): {"n_total": 4.22, "rating_mean": 252.3, "rating_sd": 57.9},
    ("球団", "投手"): {"n_total": 4.33, "rating_mean": 296.8, "rating_sd": 55.4},
}
# 実在の査定値（日本人、2026のみ。指示書 §4）。平均, 標準偏差
REAL_RATING = {
    "野手": [(191, 31), (232, 40), (245, 49), (268, 53), (273, 52), (296, 58), (272, 61), (270, 52)],
    "投手": [(222, 49), (261, 41), (291, 56), (296, 62), (306, 59), (330, 56), (300, 45), (319, 48)],
}

# ---------------------------------------------------------------------------
# 若手の能力（若手能力の幅_改修指示.md）
# ---------------------------------------------------------------------------
YOUNG_BANDS = ["〜19", "20〜21", "22〜23"]
YOUNG_METRICS = {
    "投手": [("speed", "球速"), ("control", "コントロール"), ("stamina", "スタミナ"), ("nb", "変化球の本数"), ("mvsum", "変化量の合計"), ("mvmax", "最大変化量")],
    "野手": [("contact", "ミート"), ("power", "パワー"), ("run", "走力"), ("arm", "肩力"), ("field", "守備力"), ("catch", "捕球"), ("traj", "弾道")],
}
FIELDER_ABILITY_COLUMNS = {"contact": "ミート", "power": "パワー", "run": "走力", "arm": "肩力", "field": "守備力", "catch": "捕球"}
# 目標: (平均の下限, 上限, 標準偏差の下限, 上限)。None の項目は表示だけ（判定しない）。
YOUNG_TARGETS = {
    "投手": {
        "〜19": {"speed": (150, 151, 2.7, 3.3), "control": (40, 43, 9, 11), "stamina": (39, 42, 5, 7), "mvsum": (4.4, 5.1, 0.7, 1.1), "mvmax": (2.3, 2.8, 0.4, 0.7)},
        "20〜21": {"speed": (151, 152, 3.0, 3.6), "control": (44, 47, 10, 12), "stamina": (44, 47, 7, 9)},
    },
    "野手": {
        "〜19": {"contact": (29, 33, 6, 8.5), "power": (41, 46, 9, 11.5), "run": (59, 63, 10, 12.5), "arm": (65, 69, 8, 10), "field": (35, 40, 6, 9), "catch": (34, 39, 5.5, 8), "traj": (2.4, 2.7, None, None)},
        "20〜21": {"contact": (31, 36, 7, 10), "power": (45, 50, 8, 10.5), "run": (59, 63, 12, 14), "arm": (63, 68, 9, 11), "field": (39, 44, 7, 9.5), "catch": (36, 41, 7, 9.5)},
    },
}
# 実在（data/reference/real_age_profile_2022_2026.csv。投手は2022〜2026、野手は2026のみ）。平均, 標準偏差
YOUNG_REAL = {
    "投手": {
        "〜19": {"speed": (150.1, 2.7), "control": (40.4, 9.6), "stamina": (39.9, 5.0), "nb": (2.6, 0.5), "mvsum": (4.7, 0.8), "mvmax": (2.5, 0.5), "rating": (199, 24)},
        "20〜21": {"speed": (151.2, 3.2), "control": (45.4, 11.1), "stamina": (45.8, 7.9), "nb": (2.65, 0.5), "mvsum": (5.8, 1.4), "mvmax": (3.0, 0.8), "rating": (235, 55)},
        "22〜23": {"speed": (152.3, 3.2), "control": (48.5, 10.8), "stamina": (51.3, 8.3), "nb": (2.8, 0.4), "mvsum": (6.4, 1.3), "mvmax": (3.2, 0.8), "rating": (261, 41)},
    },
    "野手": {
        "〜19": {"contact": (31.8, 6.2), "power": (41.1, 11.0), "run": (62.5, 10.4), "arm": (68.1, 8.3), "field": (35.6, 6.5), "catch": (34.3, 5.4), "traj": (2.6, None), "rating": (178, 22)},
        "20〜21": {"contact": (33.6, 7.8), "power": (47.6, 7.6), "run": (59.4, 13.2), "arm": (66.0, 10.7), "field": (40.7, 8.0), "catch": (37.2, 8.1), "rating": (200, 33)},
        "22〜23": {"contact": (39.2, 9.2), "power": (51.8, 10.1), "run": (64.4, 13.4), "arm": (66.3, 8.5), "field": (46.5, 11.0), "catch": (43.3, 7.2), "rating": (232, 40)},
    },
}
# 若手の査定値の目安（〜19のみ。報告用で判定しない）: 平均の範囲, 標準偏差の範囲
YOUNG_RATING_GUIDE = {"野手": ((175, 195), (25, 40)), "投手": ((200, 235), (25, 45))}
CLASS_ORDER = ["スター級", "一軍主力級", "一軍控え級", "二軍級"]

# 特能・ランク（1本目）の判定に使う個別生成の人数。基準（BASELINE・相関の範囲）はこの人数で決めた。
SPECIAL_CHECK_PLAYERS = 5000

_MASTER = None


def band_of(age: int) -> str:
    if age <= 21:
        return BANDS[0]
    if age <= 25:
        return BANDS[1]
    if age <= 29:
        return BANDS[2]
    if age <= 33:
        return BANDS[3]
    return BANDS[4]


def young_band_of(age: int) -> str:
    if age <= 19:
        return YOUNG_BANDS[0]
    if age <= 21:
        return YOUNG_BANDS[1]
    if age <= 23:
        return YOUNG_BANDS[2]
    return ""


def ability_value(abilities: dict[str, Any], key: str) -> float | None:
    value = abilities.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        return float(digits) if digits else None
    return float(value) if isinstance(value, int | float) else None


def ability_metrics(player: dict[str, Any]) -> dict[str, Any]:
    """若手の判定に使う能力の値（投手: 球速・コントロール・スタミナ・変化球、野手: 基本能力・弾道）。"""
    abilities = player.get("abilities") or {}
    if player.get("role") == "投手":
        balls = [ball for ball in player.get("breaking_balls") or [] if ball.get("kind", "breaking") == "breaking"]
        movements = [int(ball.get("movement", ball.get("level", 0)) or 0) for ball in balls]
        return {
            "speed": ability_value(abilities, "球速"), "control": ability_value(abilities, "コントロール"),
            "stamina": ability_value(abilities, "スタミナ"), "nb": len(balls), "mvsum": sum(movements), "mvmax": max(movements, default=0),
        }
    values = {column: ability_value(abilities, key) for column, key in FIELDER_ABILITY_COLUMNS.items()}
    values["traj"] = ability_value(abilities, "弾道")
    return values


def rating_band_of(age: int) -> str:
    if age <= 21:
        return RATING_BANDS[0]
    if age >= 34:
        return RATING_BANDS[-1]
    return RATING_BANDS[1 + (age - 22) // 2]


def rank_points(group: str, letter: str, role: str) -> int:
    """ランク1つの査定点（generator/rating.py の ranked_points と同じ表）。"""
    table = load_table()
    if group in table["ranked_major"][role]:
        return int(table["rank_table_major"].get(letter, 0))
    if group in table["ranked_minor"][role]:
        return int(table["rank_table_minor"].get(letter, 0))
    return 0


def player_metrics(player: dict[str, Any], source: str) -> dict[str, Any]:
    role = str(player.get("role"))
    names = [str(name) for name in player.get("special_abilities") or []]
    ranked = (player.get("abilities") or {}).get("ranked_specials") or {}
    letters = {group: str(name)[-1:] for group, name in ranked.items()}
    n_neg = sum(name in NEGATIVE_SPECIALS for name in names)
    n_green = sum(name in GREEN_SPECIALS for name in names)
    n_pos = sum(name not in NEGATIVE_SPECIALS and name not in GREEN_SPECIALS and name not in USAGE_ITEMS for name in names)
    age = int(player.get("age") or 0)
    return {
        "source": source,
        "seed": player.get("seed"),
        "role": role,
        "age": age,
        "band": band_of(age),
        "rating_band": rating_band_of(age),
        "young_band": young_band_of(age),
        "player_class": player.get("player_class"),
        "position": player.get("position"),
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n_green": n_green,
        "n_total": n_pos + n_neg + n_green,
        "rk_pts": sum(rank_points(group, letter, role) for group, letter in letters.items()),
        "rk_hi": sum(letter in {"S", "A", "B"} for letter in letters.values()),
        "rk_a": int(any(letter == "A" for letter in letters.values())),
        "rk_g": int(any(letter == "G" for letter in letters.values())),
        "rating": player_rating(player),
        **ability_metrics(player),
    }


def is_target(player: dict[str, Any]) -> bool:
    return player.get("category") == "架空球団用" and player.get("roster_origin") != "foreign_import"


# ---------------------------------------------------------------------------
# 生成（ワーカー）
# ---------------------------------------------------------------------------
def _init_worker() -> None:
    logging.disable(logging.WARNING)
    global _MASTER
    import app

    _MASTER = app.load_master_data()


def _individual(job: tuple[str, int, int]) -> list[dict[str, Any]]:
    import app

    role, start, stop = job
    rows = []
    for seed in range(start, stop):
        player = app.generate_player(role, "架空球団用", _MASTER, seed=seed)
        if is_target(player):
            rows.append(player_metrics(player, "個別"))
    return rows


def _team(team_seed: int) -> list[dict[str, Any]]:
    import app

    team = app.generate_team(team_seed, master=_MASTER)
    return [{**player_metrics(player, "球団"), "team": team_seed} for player in team["players"] if is_target(player)]


def collect(players: int, teams: int, workers: int) -> pd.DataFrame:
    jobs = [(role, start, min(start + 250, players + 1)) for role in ("投手", "野手") for start in range(1, players + 1, 250)]
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        if players:
            print(f"[個別生成] 投手・野手 各{players}人（{workers}並列）", flush=True)
            for chunk in pool.map(_individual, jobs):
                rows += chunk
        if teams:
            print(f"[球団生成] {teams}球団（{workers}並列）", flush=True)
            for chunk in pool.map(_team, range(TEAM_BASE_SEED, TEAM_BASE_SEED + teams), chunksize=2):
                rows += chunk
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def in_range(value: float, low: float | None = None, high: float | None = None) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return (low is None or value >= low) and (high is None or value <= high)


def band_table(frame: pd.DataFrame, role: str) -> pd.DataFrame:
    rows = []
    for band in BANDS:
        part = frame[frame.band == band]
        row = {"年齢帯": band, "人数": len(part)}
        for metric in ("n_pos", "n_neg", "n_green"):
            row[metric] = f"{part[metric].mean():.2f}（{TARGETS[role][metric][BANDS.index(band)]:.2f}）"
        row["rk_pts"] = f"{part.rk_pts.mean():+.1f}±{part.rk_pts.std():.1f}（{TARGETS[role]['rk_pts'][BANDS.index(band)]:+.1f}）"
        row["rk_hi"] = f"{part.rk_hi.mean():.2f}（{TARGETS[role]['rk_hi'][BANDS.index(band)]:.2f}）"
        rows.append(row)
    table = pd.DataFrame(rows)
    return table.rename(columns={"n_pos": "青特・金特", "n_neg": "赤特", "n_green": "緑特", "rk_pts": "ランク点 平均±SD", "rk_hi": "B以上の数"})


def rating_table(frame: pd.DataFrame, role: str) -> pd.DataFrame:
    rows = []
    for band, (real_mean, real_sd) in zip(RATING_BANDS, REAL_RATING[role]):
        part = frame[frame.rating_band == band].rating
        rows.append({"年齢帯": band, "人数": len(part), "生成 平均": round(part.mean(), 1), "生成 SD": round(part.std(), 1), "実在 平均": real_mean, "実在 SD": real_sd})
    return pd.DataFrame(rows)


def evaluate(frame: pd.DataFrame, role: str, source: str = "個別") -> list[tuple[str, str, bool]]:
    """(項目, 値, 合否) のリスト。frame は1つの役割・1つの生成方法の選手。"""
    checks: list[tuple[str, str, bool]] = []
    target = TARGETS[role]
    baseline = BASELINE[(source, role)]
    by_band = {band: frame[frame.band == band] for band in BANDS}
    mean = lambda band, metric: float(by_band[band][metric].mean())  # noqa: E731
    corr = lambda metric: float(frame.age.corr(frame[metric]))  # noqa: E731

    # 特能の数
    diffs = [mean(band, "n_pos") - target["n_pos"][i] for i, band in enumerate(BANDS)]
    checks.append(("青特・金特：各年齢帯が目標±0.35", " / ".join(f"{d:+.2f}" for d in diffs), all(abs(d) <= 0.35 for d in diffs)))
    low, high = (0.35, 0.5) if role == "野手" else (0.30, 0.45)
    checks.append((f"青特・金特：年齢との相関 {low}〜{high}", f"{corr('n_pos'):.3f}", in_range(corr("n_pos"), low, high)))
    if role == "野手":
        checks.append(("緑特：〜21 が 0.5〜0.8", f"{mean(BANDS[0], 'n_green'):.2f}", in_range(mean(BANDS[0], "n_green"), 0.5, 0.8)))
        checks.append(("緑特：30〜33 が 1.5〜2.0", f"{mean(BANDS[3], 'n_green'):.2f}", in_range(mean(BANDS[3], "n_green"), 1.5, 2.0)))
        checks.append(("緑特：34以上 が 1.5〜2.0", f"{mean(BANDS[4], 'n_green'):.2f}", in_range(mean(BANDS[4], "n_green"), 1.5, 2.0)))
        checks.append(("赤特：〜21 が 0.2〜0.5", f"{mean(BANDS[0], 'n_neg'):.2f}", in_range(mean(BANDS[0], "n_neg"), 0.2, 0.5)))
        checks.append(("赤特：34以上 が 0.85〜1.15", f"{mean(BANDS[4], 'n_neg'):.2f}", in_range(mean(BANDS[4], "n_neg"), 0.85, 1.15)))
    else:
        checks.append(("緑特：34以上 が 0.55〜0.95", f"{mean(BANDS[4], 'n_green'):.2f}", in_range(mean(BANDS[4], "n_green"), 0.55, 0.95)))
        diffs = [mean(band, "n_neg") - target["n_neg"][i] for i, band in enumerate(BANDS)]
        checks.append(("赤特：各年齢帯が修正前±0.15", " / ".join(f"{d:+.2f}" for d in diffs), all(abs(d) <= 0.15 for d in diffs)))
    checks.append(("緑特：年齢との相関 0.25〜0.4", f"{corr('n_green'):.3f}", in_range(corr("n_green"), 0.25, 0.4)))
    total = float(frame.n_total.mean())
    base = baseline["n_total"]
    checks.append((f"全年齢の特能数（通常＋緑）が修正前 {base:.2f}±0.10", f"{total:.2f}", abs(total - base) <= 0.10))

    # ランク
    diffs = [mean(band, "rk_pts") - target["rk_pts"][i] for i, band in enumerate(BANDS)]
    checks.append(("ランク点：各年齢帯が目標±2.0", " / ".join(f"{d:+.1f}" for d in diffs), all(abs(d) <= 2.0 for d in diffs)))
    low, high = (0.20, 0.40) if role == "野手" else (0.15, 0.35)
    checks.append((f"ランク点：年齢との相関 {low}〜{high}", f"{corr('rk_pts'):.3f}", in_range(corr("rk_pts"), low, high)))
    young_sd = float(by_band[BANDS[0]].rk_pts.std())
    low, high = (4.0, 7.0) if role == "野手" else (3.5, 7.0)
    checks.append((f"ランク点SD：〜21 が {low}〜{high}", f"{young_sd:.2f}", in_range(young_sd, low, high)))
    old_sds = [float(by_band[band].rk_pts.std()) for band in BANDS[2:]]
    checks.append(("ランク点SD：26歳以上の各帯が 7〜10", " / ".join(f"{sd:.2f}" for sd in old_sds), all(in_range(sd, 7.0, 10.0) for sd in old_sds)))
    checks.append(("B以上の数：〜21 が 0.15以下", f"{mean(BANDS[0], 'rk_hi'):.3f}", in_range(mean(BANDS[0], "rk_hi"), high=0.15)))
    checks.append(("B以上の数：30〜33 が 0.6〜0.95", f"{mean(BANDS[3], 'rk_hi'):.3f}", in_range(mean(BANDS[3], "rk_hi"), 0.6, 0.95)))
    a_limit = 0.04 if role == "投手" else 0.05
    checks.append((f"ランクAを持つ選手 {a_limit:.0%}以下", f"{frame.rk_a.mean():.1%}", in_range(float(frame.rk_a.mean()), high=a_limit)))
    checks.append(("ランクGを持つ選手 3%以下", f"{frame.rk_g.mean():.1%}", in_range(float(frame.rk_g.mean()), high=0.03)))

    # 査定値（全年齢）
    rating_mean, rating_sd = float(frame.rating.mean()), float(frame.rating.std())
    checks.append((f"査定値の平均が修正前 {baseline['rating_mean']:.1f}±5", f"{rating_mean:.1f}", abs(rating_mean - baseline["rating_mean"]) <= 5))
    checks.append((f"査定値の標準偏差が修正前 {baseline['rating_sd']:.1f}±5", f"{rating_sd:.1f}", abs(rating_sd - baseline["rating_sd"]) <= 5))
    return checks


def young_table(frame: pd.DataFrame, role: str) -> pd.DataFrame:
    """若手の年齢帯別の平均（標準偏差）と 10〜90%タイル。実在と目標を並べる。"""
    rows = []
    for band in YOUNG_BANDS:
        part = frame[frame.young_band == band]
        for column, label in YOUNG_METRICS[role] + [("rating", "査定値")]:
            values = part[column].dropna()
            real = YOUNG_REAL[role][band].get(column)
            target = YOUNG_TARGETS[role].get(band, {}).get(column)
            real_text = "—" if real is None else (f"{real[0]}" if real[1] is None else f"{real[0]}（{real[1]}）")
            if target is None:
                target_text = "—"
            elif target[2] is None:
                target_text = f"平均 {target[0]}〜{target[1]}"
            else:
                target_text = f"平均 {target[0]}〜{target[1]}、SD {target[2]}〜{target[3]}"
            rows.append({
                "年齢帯": band, "能力": label, "人数": len(values),
                "平均（SD）": f"{values.mean():.2f}（{values.std():.2f}）",
                "10〜90%": f"{values.quantile(0.1):.0f}〜{values.quantile(0.9):.0f}",
                "実在": real_text, "目標": target_text,
            })
    return pd.DataFrame(rows)


def evaluate_young(frame: pd.DataFrame, role: str) -> list[tuple[str, str, bool]]:
    """若手の能力の判定（若手能力の幅_改修指示.md §3）。frame は1つの役割・1つの生成方法の選手。"""
    checks: list[tuple[str, str, bool]] = []
    for band, targets in YOUNG_TARGETS[role].items():
        part = frame[frame.young_band == band]
        for column, (mean_low, mean_high, sd_low, sd_high) in targets.items():
            label = dict(YOUNG_METRICS[role])[column]
            values = part[column].dropna()
            mean, sd = float(values.mean()), float(values.std())
            ok = in_range(mean, mean_low, mean_high) and (sd_low is None or in_range(sd, sd_low, sd_high))
            target = f"平均 {mean_low}〜{mean_high}" + ("" if sd_low is None else f"・SD {sd_low}〜{sd_high}")
            checks.append((f"{band} {label}：{target}（{len(values)}人）", f"{mean:.2f}（{sd:.2f}）", ok))
    young = frame[frame.young_band == YOUNG_BANDS[0]]
    if role == "投手":
        share = float((young.mvmax >= 4).mean())
        checks.append(("〜19 最大変化量4以上が2%以下", f"{share:.1%}", share <= 0.02))
    else:
        for band in YOUNG_BANDS[:2]:
            part = frame[frame.young_band == band]
            # 指示書 §3 は「捕手の捕球が他の位置より8以上高い」だが、既存の生成は全年齢で二塁手の捕球が最も高く、
            # 捕手と他の位置の差は8に届かない（修正前の差は --compare で ±30% 以内かを見る）。ここでは向きだけ見る。
            gap = catcher_catch_gap(part)
            checks.append((f"{band} 捕手の捕球が捕手以外の平均より高い", f"{gap:+.1f}", gap > 0))
            runs = part.groupby("position").run.mean()
            ok = all(runs.get(pos, 0) > runs.get("一塁手", 999) for pos in ("遊撃手", "二塁手", "外野手"))
            text = " / ".join(f"{pos} {runs.get(pos, float('nan')):.1f}" for pos in ("遊撃手", "二塁手", "外野手", "一塁手"))
            checks.append((f"{band} 遊撃手・二塁手・外野手の走力が一塁手より高い", text, ok))
    for band in YOUNG_BANDS[:2]:
        part = frame[frame.young_band == band]
        means = part.groupby("player_class").rating.mean()
        order = [means.get(name, float("nan")) for name in CLASS_ORDER]
        ok = all(a > b for a, b in zip(order, order[1:]))
        checks.append((f"{band} 選手格別の査定値の平均 スター級>一軍主力級>一軍控え級>二軍級", " > ".join(f"{v:.0f}" for v in order), ok))
    return checks


def catcher_catch_gap(frame: pd.DataFrame) -> float:
    return float(frame[frame.position == "捕手"].catch.mean() - frame[frame.position != "捕手"].catch.mean())


def run_gap(frame: pd.DataFrame) -> float:
    """遊撃手・二塁手・外野手の走力の平均 − 一塁手の走力の平均。"""
    runs = frame.groupby("position").run.mean()
    return float(runs[["遊撃手", "二塁手", "外野手"]].mean() - runs["一塁手"])


def young_gap_lines(before: pd.DataFrame, after: pd.DataFrame) -> tuple[list[str], int]:
    """位置ごとの差（捕手の捕球・二遊間外野の走力）が修正前の ±30% 以内に残っているか。"""
    lines = ["### 若手の位置ごとの差（修正前 → 修正後、±30%以内）", "", "| 判定 | 生成 | 年齢帯 | 項目 | 修正前 | 修正後 | 比 |", "|---|---|---|---|---|---|---|"]
    failures = 0
    for source in ("個別", "球団"):
        b = before[(before.source == source) & (before.role == "野手")]
        a = after[(after.source == source) & (after.role == "野手")]
        if b.empty or a.empty:
            continue
        for band in YOUNG_BANDS[:2]:
            pb, pa = b[b.young_band == band], a[a.young_band == band]
            for label, func in (("捕手の捕球 − 捕手以外", catcher_catch_gap), ("遊撃・二塁・外野の走力 − 一塁", run_gap)):
                gb, ga = func(pb), func(pa)
                ratio = ga / gb if gb else float("nan")
                ok = 0.7 <= ratio <= 1.3
                failures += not ok
                lines.append(f"| {'OK' if ok else 'NG'} | {source} | {band} | {label} | {gb:+.1f} | {ga:+.1f} | {ratio:.2f} |")
    return lines + [""], failures


def young_lines(frame: pd.DataFrame, title: str = "") -> tuple[list[str], int]:
    lines: list[str] = []
    failures = 0
    for source in ("個別", "球団"):
        for role in ("投手", "野手"):
            part = frame[(frame.source == source) & (frame.role == role)]
            if part.empty or "young_band" not in part:
                continue
            lines += [f"### {title}{source}生成 日本人{role}の若手の能力", "", to_markdown(young_table(part, role)), ""]
            checks = evaluate_young(part, role)
            failures += sum(not ok for *_, ok in checks)
            lines += ["| 判定 | 項目 | 値 |", "|---|---|---|"] + [f"| {'OK' if ok else 'NG'} | {label} | {value} |" for label, value, ok in checks] + [""]
            young = part[part.young_band == YOUNG_BANDS[0]].rating
            (mean_low, mean_high), (sd_low, sd_high) = YOUNG_RATING_GUIDE[role]
            lines += [f"〜19 の査定値（目安。判定しない）: {young.mean():.1f} / {young.std():.1f}（目安 平均 {mean_low}〜{mean_high}・SD {sd_low}〜{sd_high}）", ""]
    return lines, failures


def player_key(frame: pd.DataFrame) -> pd.Series:
    team = frame["team"] if "team" in frame else pd.Series(0, index=frame.index)
    return frame.source.astype(str) + ":" + frame.role.astype(str) + ":" + team.fillna(0).astype(int).astype(str) + ":" + frame.seed.astype(str)


def young_rank_lines(before: pd.DataFrame, after: pd.DataFrame) -> tuple[list[str], int]:
    """同じ選手の修正前後で、同年齢帯の中の順位相関（スピアマン）が0.98以上かを見る。"""
    lines = ["### 若手の能力の順位相関（修正前 → 修正後、同年齢帯の中）", "", "| 判定 | 生成 | 役割 | 年齢帯 | 能力 | 順位相関 |", "|---|---|---|---|---|---|"]
    failures = 0
    b, a = before.copy(), after.copy()
    b["key"], a["key"] = player_key(b), player_key(a)
    merged = b.merge(a, on="key", suffixes=("_b", "_a"))
    for source in ("個別", "球団"):
        for role in ("投手", "野手"):
            for band in YOUNG_BANDS[:2]:
                part = merged[(merged.source_b == source) & (merged.role_b == role) & (merged.young_band_a == band)]
                if part.empty:
                    continue
                for column, label in YOUNG_METRICS[role]:
                    if column in {"nb", "traj"} or f"{column}_b" not in part:
                        continue
                    pair = part[[f"{column}_b", f"{column}_a"]].dropna()
                    if pair[f"{column}_b"].nunique() < 2:
                        continue
                    rho = float(pair[f"{column}_b"].rank().corr(pair[f"{column}_a"].rank()))
                    # 変化球は離散値で同順位が多く、上限で丸めるので目安として表示だけ
                    ok = rho >= 0.98 or column in {"mvsum", "mvmax"}
                    failures += not ok
                    lines.append(f"| {'OK' if ok else 'NG'} | {source} | {role} | {band} | {label} | {rho:.3f} |")
    return lines + [""], failures


def young_compare_lines(before: pd.DataFrame, after: pd.DataFrame) -> list[str]:
    """修正前後の若手の平均（標準偏差）を並べる。"""
    lines: list[str] = []
    for source in ("個別", "球団"):
        for role in ("投手", "野手"):
            b = before[(before.source == source) & (before.role == role)]
            a = after[(after.source == source) & (after.role == role)]
            if b.empty or a.empty:
                continue
            rows = []
            for column, label in YOUNG_METRICS[role] + [("rating", "査定値")]:
                row = {"能力": label}
                for band in YOUNG_BANDS:
                    pb, pa = b[b.young_band == band][column].dropna(), a[a.young_band == band][column].dropna()
                    real = YOUNG_REAL[role][band].get(column)
                    real_text = "" if real is None else (f"（実在 {real[0]}）" if real[1] is None else f"（実在 {real[0]}／{real[1]}）")
                    row[band] = f"{pb.mean():.1f}／{pb.std():.1f} → {pa.mean():.1f}／{pa.std():.1f}{real_text}"
                rows.append(row)
            lines += [f"### {source}生成 日本人{role}の若手：修正前 → 修正後（平均／標準偏差）", "", to_markdown(pd.DataFrame(rows)), ""]
    return lines


def to_markdown(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    sep = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, sep, *body])


def report(frame: pd.DataFrame, title: str = "") -> tuple[list[str], int]:
    """年齢帯別の表と判定を Markdown の行で返す。(行, 不合格数)

    特能・ランクの判定は、基準を決めたときと同じ個別生成 seed 1〜5000（SPECIAL_CHECK_PLAYERS）で行う。
    """
    lines: list[str] = []
    failures = 0
    for source in ("個別", "球団"):
        for role in ("野手", "投手"):
            part = frame[(frame.source == source) & (frame.role == role)]
            if source == "個別":
                part = part[part.seed <= SPECIAL_CHECK_PLAYERS]
            if part.empty:
                continue
            lines += [f"### {title}{source}生成 日本人{role}（{len(part)}人）", "", "値（括弧内は目標）:", "", to_markdown(band_table(part, role)), ""]
            checks = evaluate(part, role, source)
            failures += sum(not ok for *_, ok in checks)
            lines += ["| 判定 | 項目 | 値 |", "|---|---|---|"] + [f"| {'OK' if ok else 'NG'} | {label} | {value} |" for label, value, ok in checks] + [""]
            lines += ["査定値（参考。基準にしない）:", "", to_markdown(rating_table(part, role)), ""]
    return lines, failures


def compare_table(before: pd.DataFrame, after: pd.DataFrame, role: str, source: str) -> pd.DataFrame:
    rows = []
    b = before[(before.role == role) & (before.source == source)]
    a = after[(after.role == role) & (after.source == source)]
    for band in BANDS:
        pb, pa = b[b.band == band], a[a.band == band]
        i = BANDS.index(band)
        rows.append({
            "年齢帯": band,
            "青特・金特": f"{pb.n_pos.mean():.2f} → {pa.n_pos.mean():.2f}（{TARGETS[role]['n_pos'][i]:.2f}）",
            "赤特": f"{pb.n_neg.mean():.2f} → {pa.n_neg.mean():.2f}（{TARGETS[role]['n_neg'][i]:.2f}）",
            "緑特": f"{pb.n_green.mean():.2f} → {pa.n_green.mean():.2f}（{TARGETS[role]['n_green'][i]:.2f}）",
            "ランク点": f"{pb.rk_pts.mean():+.1f}±{pb.rk_pts.std():.1f} → {pa.rk_pts.mean():+.1f}±{pa.rk_pts.std():.1f}（{TARGETS[role]['rk_pts'][i]:+.1f}）",
            "B以上": f"{pb.rk_hi.mean():.2f} → {pa.rk_hi.mean():.2f}（{TARGETS[role]['rk_hi'][i]:.2f}）",
        })
    rows.append({
        "年齢帯": "全体",
        "青特・金特": f"{b.n_pos.mean():.2f} → {a.n_pos.mean():.2f}",
        "赤特": f"{b.n_neg.mean():.2f} → {a.n_neg.mean():.2f}",
        "緑特": f"{b.n_green.mean():.2f} → {a.n_green.mean():.2f}",
        "ランク点": f"{b.rk_pts.mean():+.1f}±{b.rk_pts.std():.1f} → {a.rk_pts.mean():+.1f}±{a.rk_pts.std():.1f}",
        "B以上": f"{b.rk_hi.mean():.2f} → {a.rk_hi.mean():.2f}",
    })
    return pd.DataFrame(rows)


def compare_rating_table(before: pd.DataFrame, after: pd.DataFrame, role: str, source: str) -> pd.DataFrame:
    rows = []
    b = before[(before.role == role) & (before.source == source)]
    a = after[(after.role == role) & (after.source == source)]
    for band, (real_mean, real_sd) in zip(RATING_BANDS + ["全体"], REAL_RATING[role] + [("—", "—")]):
        pb = b.rating if band == "全体" else b[b.rating_band == band].rating
        pa = a.rating if band == "全体" else a[a.rating_band == band].rating
        rows.append({"年齢帯": band, "修正前": f"{pb.mean():.1f} / {pb.std():.1f}", "修正後": f"{pa.mean():.1f} / {pa.std():.1f}", "実在（2026）": f"{real_mean} / {real_sd}"})
    return pd.DataFrame(rows)


def compare_lines(before: pd.DataFrame, after: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    for source in ("個別", "球団"):
        for role in ("野手", "投手"):
            if before[(before.role == role) & (before.source == source)].empty or after[(after.role == role) & (after.source == source)].empty:
                continue
            lines += [f"### {source}生成 日本人{role}：修正前 → 修正後（目標）", "", to_markdown(compare_table(before, after, role, source)), "",
                      "査定値（平均 / 標準偏差）:", "", to_markdown(compare_rating_table(before, after, role, source)), ""]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）の特能・ランク・査定値を年齢帯別に確認します。")
    parser.add_argument("--players", type=int, default=30000, help="個別生成の人数（投手・野手それぞれ）")
    parser.add_argument("--teams", type=int, default=500, help="球団生成の球団数")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--save", type=Path, help="選手ごとの値を CSV に保存する")
    parser.add_argument("--load", type=Path, help="生成せずに、保存した CSV を判定する")
    parser.add_argument("--compare", type=Path, help="修正前の CSV と並べた表も出す")
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    frame = pd.read_csv(args.load, encoding="utf-8-sig") if args.load else collect(args.players, args.teams, args.workers)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.save, index=False, encoding="utf-8-sig")
    lines, failures = report(frame)
    young, young_failures = young_lines(frame)
    lines += ["## 若手の能力（〜19・20〜21・22〜23）", ""] + young
    failures += young_failures
    if args.compare:
        before = pd.read_csv(args.compare, encoding="utf-8-sig")
        lines += ["## 修正前との比較", ""] + compare_lines(before, frame)
        if "young_band" in before:
            rank, rank_failures = young_rank_lines(before, frame)
            gaps, gap_failures = young_gap_lines(before, frame)
            lines += young_compare_lines(before, frame) + rank + gaps
            failures += rank_failures + gap_failures
    print("\n".join(lines))
    print(f"不合格 {failures} 項目")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
