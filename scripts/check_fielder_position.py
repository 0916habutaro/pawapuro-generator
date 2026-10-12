#!/usr/bin/env python3
"""
架空球団用（日本人）野手の22歳以上の、ポジションごとの能力の型を、球団生成で判定する（`野手のポジション別の型_改修指示.md`）。

使い方:
    python scripts/check_fielder_position.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_fielder_position.py --teams 60      # 途中確認用
    python scripts/check_fielder_position.py --single-csv reports/checks/samples/fictional_fielders.csv   # 個別生成の参考表も出す

- 球団生成で作った球団の日本人野手のうち22歳以上を、実在（2024〜2026年版の日本人野手。21歳以下を除く1,000人）と比べる。
  実在の年齢は、2026年版は age、2022〜2025年版は逆算年齢（age_backcalc。わからない選手は21歳以下に数えない）。
- 判定する項目（指示書2-1）: ポジション×能力（ミート・パワー・肩力・守備力・捕球）の平均と標準偏差の比（生成÷実在）、
  ポジションごとの弾道の平均と割合（弾道1〜4）、ポジションごとの査定の平均。
  指示書1-4の表で直した能力の平均は、範囲を狭く（±1.0）する。
- 捕手のキャッチャー（`野手のランク特能_改修指示.md` 2-1）: メインが捕手の野手（全年齢）のランクの割合（A〜G、実在±5ポイント）と
  ランク点（実在±0.4）。実在の値は data/config/fielder_ranked_real.json（check_fielder_batting.py --build-real で作る）。
- 捕手の特能（`捕手の特能_改修指示.md` 2-1）: 日本人野手（全年齢）の、捕手の選球眼・固め打ち・三振の保有率（実在±4ポイント）、
  ポジションのまとまり（捕手／二塁手・遊撃手／一塁手・三塁手・外野手）ごとの三振の保有率（実在±6ポイント）、
  捕手の緑特・赤特の数（実在±0.15）、日本人野手全体の三振・選球眼の保有率（実在±3ポイント。誤差なし）。
  実在は2024〜2026年版の日本人野手1,103人（ポジションはメイン）。同じ選手が複数の年版に入っているので、
  実在側の誤差は異なる選手の数（捕手98人、二塁手・遊撃手135人、一塁手・三塁手・外野手226人）で見積もる。
- ランク特能の形（`ランク特能の形_改修指示.md` 2-1）: ケガしにくさ（捕手・遊撃手／ほか）とチャンス（野手全体）のランクの割合
  （B・C・E・F は実在±4ポイント、D は実在±6ポイント）とランク点（実在±0.3）。全年齢。共通部分は rank_shape.py。
- 能力とランク特能の結びつき（`能力とランク特能の結びつき_改修指示.md` 2-1）: 回復（野手全体。ミート・守備力・捕球）、送球（野手全体。
  捕球・守備力）、キャッチャー（メインが捕手。捕球・守備力）の、ランクの点と能力の合成値の相関（実在±0.12）とランクの割合
  （B〜F、実在±4ポイント）。全年齢。実在の値は data/config/rank_ability_real.json、共通部分は rank_ability.py。
- 21歳以下・走力・打席の左右差は check_age_profile.py・check_fielder_speed.py・check_fielder_batting.py が受け持つ。
- 個別生成（架空球団用・野手）は同じ表を参考として出す（合否には使わない。査定は求めない）。
- 判定の種類・誤差・合否の付け方は checklib.py。誤差は、生成側は球団、実在側は実在の野手を再抽出して見積もる。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import checklib  # noqa: E402
import rank_ability  # noqa: E402
import rank_shape  # noqa: E402
from check_fielder_batting import (  # noqa: E402
    LETTERS, RANK_COLUMNS, SPECIAL_FLAG_COLUMNS, collect, mean_se, real_japanese_fielders, real_rank_reference, share_se, single_fielders,
)
from checklib import Checks  # noqa: E402

SCRIPT = "check_fielder_position"
SHAPE_KEYS = rank_shape.SCRIPT_SHAPES[SCRIPT]
SHAPE_COLUMNS = ("rk_ケガしにくさ", "rk_チャンス")
ABILITY_KEYS = rank_ability.SCRIPT_PARTS[SCRIPT]
ABILITY_RANK_COLUMNS = ("rk_回復", "rk_送球")  # rk_キャッチャー は RANK_COLUMNS にある
POSITIONS = ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")
ABILITIES = ("ミート", "パワー", "肩力", "守備力", "捕球")
YOUNG_MAX_AGE = 21
# 実在（2024〜2026年版の日本人野手のうち21歳以下を除く1,000人）。判定の目標。
REAL_MEAN = {  # ポジション: (ミート, パワー, 肩力, 守備力, 捕球)
    "捕手": (37.83, 50.64, 72.57, 50.06, 47.29),
    "一塁手": (47.52, 61.93, 57.92, 47.48, 50.92),
    "二塁手": (46.17, 49.52, 59.69, 58.52, 53.32),
    "三塁手": (44.94, 58.80, 63.97, 49.66, 48.52),
    "遊撃手": (41.38, 45.89, 66.15, 58.15, 51.91),
    "外野手": (44.25, 55.61, 65.92, 53.06, 48.82),
}
REAL_SD = {
    "捕手": (10.79, 9.34, 9.34, 9.09, 10.05),
    "一塁手": (7.93, 9.23, 10.78, 10.17, 12.25),
    "二塁手": (8.69, 11.35, 10.46, 10.42, 11.29),
    "三塁手": (9.47, 10.42, 9.53, 10.08, 10.76),
    "遊撃手": (8.92, 9.44, 9.59, 11.56, 11.62),
    "外野手": (11.18, 11.00, 11.32, 11.64, 9.60),
}
REAL_TRAJECTORY = {  # ポジション: (弾道の平均, 弾道1〜4の割合（%）, 査定の平均)
    "捕手": (2.53, (0.9, 49.5, 45.5, 4.1), 225.8),
    "一塁手": (3.26, (0.0, 6.6, 60.7, 32.8), 259.8),
    "二塁手": (2.39, (4.9, 54.1, 37.7, 3.3), 264.4),
    "三塁手": (3.01, (0.0, 24.0, 51.0, 25.0), 261.7),
    "遊撃手": (2.16, (9.9, 65.1, 24.3, 0.7), 253.5),
    "外野手": (2.63, (1.4, 43.8, 45.5, 9.3), 274.4),
}
# 改修前（球団生成 seed 1〜300、PR #114 の main、22歳以上）の値。表示用
BEFORE = {  # ポジション: (ミート, パワー, 肩力, 守備力, 捕球, 弾道の平均, 査定の平均)
    "捕手": (39.30, 53.27, 71.08, 51.65, 52.32, 2.68, 242.4),
    "一塁手": (44.12, 57.82, 58.38, 47.66, 48.16, 2.90, 236.6),
    "二塁手": (47.16, 51.46, 58.05, 60.70, 54.17, 2.62, 272.4),
    "三塁手": (43.55, 57.94, 63.87, 47.86, 43.67, 2.88, 249.6),
    "遊撃手": (40.59, 49.26, 66.79, 56.73, 50.89, 2.51, 259.3),
    "外野手": (45.24, 54.21, 66.87, 53.22, 49.09, 2.73, 276.9),
}
# 指示書1-4の表で直した能力（平均を狭い範囲で判定する）
FIXED_PAIRS = {
    "捕手": ("パワー", "捕球", "肩力"),
    "一塁手": ("パワー", "ミート", "捕球", "守備力"),
    "二塁手": ("肩力", "パワー", "捕球"),
    "三塁手": ("捕球", "パワー", "守備力"),
    "遊撃手": ("パワー", "ミート"),
    "外野手": ("パワー", "守備力", "肩力", "捕球"),
}
# 合格の範囲（指示書2-1）
TOL_MEAN, TOL_MEAN_FIXED, SD_RATIO_RANGE, TOL_TRAJECTORY_MEAN, TOL_SHARE, TOL_RATING = 1.5, 1.0, (0.85, 1.20), 0.15, 6.0, 8.0
TOL_CATCHER_SHARE, TOL_CATCHER_POINTS = 5.0, 0.4
# 改修前（球団生成 seed 1〜300、PR #122 をマージした main 1e6eda4）の捕手のキャッチャー。表示用
BEFORE_CATCHER = {"割合": (0.1, 0.9, 5.9, 80.0, 11.2, 1.7, 0.1), "ランク点": -0.27}
# 捕手の特能（`捕手の特能_改修指示.md` 2-1）。実在は2024〜2026年版の日本人野手1,103人（全年齢。ポジションはメイン）。
# 保有率は%、緑特・赤特の数は球団分析と同じ数え方で（平均, 標準偏差）。人数は異なる選手の数（誤差に使う）。
SPECIAL_GROUPS = {"捕手": ("捕手",), "二遊": ("二塁手", "遊撃手"), "一三外": ("一塁手", "三塁手", "外野手")}
SPECIAL_GROUP_LABELS = {"捕手": "捕手", "二遊": "二塁手・遊撃手", "一三外": "一塁手・三塁手・外野手", "全体": "日本人野手"}
REAL_SPECIALS = {
    "捕手": {"人数": 98, "選球眼": 8.20, "固め打ち": 3.28, "三振": 22.54, "広角打法": 1.64, "ホーム死守": 15.16,
             "緑特の数": (0.570, 0.851), "赤特の数": (0.520, 0.694)},
    "二遊": {"人数": 135, "選球眼": 18.83, "固め打ち": 15.91, "三振": 26.30},
    "一三外": {"人数": 226, "選球眼": 23.59, "固め打ち": 22.32, "三振": 39.75},
    "全体": {"選球眼": 18.86, "三振": 32.18},
}
CATCHER_SPECIALS = ("選球眼", "固め打ち", "三振")
TOL_CATCHER_SPECIAL, TOL_STRIKEOUT, TOL_CATCHER_COUNT, TOL_OVERALL_SPECIAL = 4.0, 6.0, 0.15, 3.0
# 改修前（球団生成 seed 1〜300、PR #125 をマージした main 2aee83c、PC で PYTHONHASHSEED=0、全年齢）の値。表示用
BEFORE_SPECIALS = {
    "捕手": {"選球眼": 19.7, "固め打ち": 12.5, "三振": 34.1, "広角打法": 4.6, "ホーム死守": 7.7, "緑特の数": 0.77, "赤特の数": 0.65},
    "二遊": {"選球眼": 22.5, "固め打ち": 17.1, "三振": 31.7}, "一三外": {"選球眼": 23.0, "固め打ち": 21.3, "三振": 31.5},
    "全体": {"選球眼": 22.2, "三振": 32.1},
}
SECTIONS = {
    "mean": "ポジション×能力の平均（実在は2024〜2026年版の日本人野手・22歳以上）",
    "sd": "ポジション×能力の標準偏差の比（生成÷実在）",
    "traj_mean": "ポジションごとの弾道の平均",
    "traj_share": "ポジションごとの弾道の割合（%）",
    "rating": "ポジションごとの査定の平均",
    "catcher_rank": "捕手のキャッチャー（メインが捕手。全年齢。割合は%で実在±5ポイント、ランク点は実在±0.4）",
    "catcher_special": "捕手の選球眼・固め打ち・三振の保有率（%。全年齢。実在±4ポイント）",
    "strikeout": "ポジションのまとまりごとの三振の保有率（%。全年齢。実在±6ポイント）",
    "catcher_count": "捕手の緑特・赤特の数（全年齢。球団分析と同じ数え方。実在±0.15）",
    "overall_special": "日本人野手全体の三振・選球眼の保有率（%。全年齢。実在±3ポイント）",
}


def adults(frame: pd.DataFrame) -> pd.DataFrame:
    """判定の対象。実在は2024〜2026年版の22歳以上（年齢がわからない選手を含む）、生成は22歳以上。"""
    if "season" in frame.columns:
        age = frame["age"].where(frame["season"] == 2026, frame["age_backcalc"])
        return frame[(frame["season"] >= 2024) & ~(age <= YOUNG_MAX_AGE)]
    return frame[frame["age"] > YOUNG_MAX_AGE]


def evaluate(frame: pd.DataFrame, prefix: str = SCRIPT, info: bool = False) -> Checks:
    """frame: 日本人野手（列 position, age, 弾道, ミート〜捕球, rating, team_key）。実在のときは season・age_backcalc もある。
    info=True ならすべて参考（個別生成。査定の列が無ければ査定は出さない）。"""
    main = adults(frame)
    checks = Checks(prefix)
    kind = checklib.KIND_INFO if info else checklib.KIND_REAL

    def add(section: str, key: str, label: str, value: float, low: float, high: float, real: str, fmt: str = "{:.2f}") -> None:
        checks.add(f"{prefix}.{section}.{key}", kind, label, value, low, high, section=SECTIONS[section],
                   shown=fmt.format(value), target=f"{fmt.format(low)}〜{fmt.format(high)}", real=real)

    for position in POSITIONS:
        d = main[main["position"] == position]
        for index, name in enumerate(ABILITIES):
            real = REAL_MEAN[position][index]
            tol = TOL_MEAN_FIXED if name in FIXED_PAIRS[position] else TOL_MEAN
            add("mean", f"{position}_{name}", f"{position} {name} 平均", d[name].mean(), real - tol, real + tol, f"{real:.2f}")
        for index, name in enumerate(ABILITIES):
            add("sd", f"{position}_{name}", f"{position} {name} 標準偏差の比", d[name].std() / REAL_SD[position][index],
                SD_RATIO_RANGE[0], SD_RATIO_RANGE[1], f"1.00（標準偏差 {REAL_SD[position][index]:.2f}）")
        real_mean, real_shares, real_rating = REAL_TRAJECTORY[position]
        add("traj_mean", position, f"{position} 弾道 平均", d["弾道"].mean(), real_mean - TOL_TRAJECTORY_MEAN, real_mean + TOL_TRAJECTORY_MEAN, f"{real_mean:.2f}")
        for trajectory, real in enumerate(real_shares, start=1):
            add("traj_share", f"{position}_{trajectory}", f"{position} 弾道{trajectory}の割合", float((d["弾道"] == trajectory).mean() * 100),
                real - TOL_SHARE, real + TOL_SHARE, f"{real:.1f}", "{:.1f}")
        if d["rating"].notna().any():
            add("rating", position, f"{position} 査定 平均", d["rating"].mean(), real_rating - TOL_RATING, real_rating + TOL_RATING, f"{real_rating:.1f}", "{:.1f}")
    if "rk_キャッチャー" in frame.columns:  # 実在の選手単位データ（local_data）にはランク特能の列が無い。実在の値は fielder_ranked_real.json
        catcher_rank_checks(checks, frame, prefix, kind)
    if "sp_三振" in frame.columns:  # 実在の選手単位データには特能の有無の列が無い。実在の値は REAL_SPECIALS
        catcher_special_checks(checks, frame, prefix, kind)
    if "rk_ケガしにくさ" in frame.columns:  # ランク特能の形（全年齢）。実在の値は rank_shape_real.json
        rank_shape.shape_checks(checks, frame, prefix, kind, SHAPE_KEYS)
    if "rk_回復" in frame.columns:  # 能力とランク特能の結びつき（全年齢）。実在の値は rank_ability_real.json
        rank_ability.ability_checks(checks, frame, prefix, kind, ABILITY_KEYS)
    return checks


def special_group(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    return frame if group == "全体" else frame[frame["position"].isin(SPECIAL_GROUPS[group])]


def catcher_special_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """捕手の特能（全年齢）。frame は列 sp_特能名・n_red・n_green を持つ。"""
    def add(section: str, key: str, label: str, value: float, real: float, tol: float, fmt: str = "{:.1f}") -> None:
        low, high = real - tol, real + tol
        checks.add(f"{prefix}.{section}.{key}", kind, label, value, low, high, section=SECTIONS[section],
                   shown=fmt.format(value), target=f"{fmt.format(low)}〜{fmt.format(high)}", real=fmt.format(real))

    catchers = special_group(frame, "捕手")
    for name in CATCHER_SPECIALS:
        add("catcher_special", name, f"捕手 {name}の保有率", float(catchers[f"sp_{name}"].mean() * 100), REAL_SPECIALS["捕手"][name], TOL_CATCHER_SPECIAL)
    for group in SPECIAL_GROUPS:
        part = special_group(frame, group)
        add("strikeout", group, f"{SPECIAL_GROUP_LABELS[group]} 三振の保有率", float(part["sp_三振"].mean() * 100), REAL_SPECIALS[group]["三振"], TOL_STRIKEOUT)
    for column, name in (("n_green", "緑特の数"), ("n_red", "赤特の数")):
        add("catcher_count", column, f"捕手 {name}", float(catchers[column].mean()), REAL_SPECIALS["捕手"][name][0], TOL_CATCHER_COUNT, "{:.2f}")
    for name in ("三振", "選球眼"):
        add("overall_special", name, f"日本人野手 {name}の保有率", float(frame[f"sp_{name}"].mean() * 100), REAL_SPECIALS["全体"][name], TOL_OVERALL_SPECIAL)


def catcher_rank_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """メインが捕手の野手（全年齢）のキャッチャーのランクの割合とランク点。"""
    real = real_rank_reference()["捕手"]
    catchers = frame[frame["position"] == "捕手"]
    for letter in LETTERS:
        value, r = float((catchers["rk_キャッチャー"] == letter).mean() * 100), real["キャッチャー_ランク"][letter]
        low, high = r - TOL_CATCHER_SHARE, r + TOL_CATCHER_SHARE
        checks.add(f"{prefix}.catcher_rank.{letter}", kind, f"捕手 キャッチャー {letter}の割合", value, low, high, section=SECTIONS["catcher_rank"],
                   shown=f"{value:.1f}", target=f"{low:.1f}〜{high:.1f}", real=f"{r:.1f}")
    value, r = float(catchers["pt_キャッチャー"].mean()), real["キャッチャー"][0]
    low, high = r - TOL_CATCHER_POINTS, r + TOL_CATCHER_POINTS
    checks.add(f"{prefix}.catcher_rank.points", kind, "捕手 キャッチャーのランク点", value, low, high, section=SECTIONS["catcher_rank"],
               shown=f"{value:+.2f}", target=f"{low:+.2f}〜{high:+.2f}", real=f"{r:+.2f}")


def real_catcher_errors(prefix: str = SCRIPT) -> dict[str, float]:
    """捕手のキャッチャーの判定の実在側の誤差。"""
    real = real_rank_reference()["捕手"]
    se = {f"{prefix}.catcher_rank.{letter}": share_se(real["キャッチャー_ランク"][letter], real["人数"]) for letter in LETTERS}
    se[f"{prefix}.catcher_rank.points"] = mean_se(real["キャッチャー"])
    return se


def real_special_errors(prefix: str = SCRIPT) -> dict[str, float]:
    """捕手の特能の判定の実在側の誤差。人数は異なる選手の数。全体の保有率（実在±3ポイント）は誤差を付けない。"""
    catcher = REAL_SPECIALS["捕手"]
    se = {f"{prefix}.catcher_special.{name}": share_se(catcher[name], catcher["人数"]) for name in CATCHER_SPECIALS}
    for group in SPECIAL_GROUPS:
        se[f"{prefix}.strikeout.{group}"] = share_se(REAL_SPECIALS[group]["三振"], REAL_SPECIALS[group]["人数"])
    for column, name in (("n_green", "緑特の数"), ("n_red", "赤特の数")):
        se[f"{prefix}.catcher_count.{column}"] = mean_se([*catcher[name], catcher["人数"]])
    return se


def grade_all(frame: pd.DataFrame, boot: int, quick: bool = False) -> list[checklib.Check]:
    """球団を単位に生成側の誤差を、実在の野手を単位に実在側の誤差を求めて合否を付ける。"""
    evaluate_checks = lambda f: evaluate(f)  # noqa: E731
    checks = evaluate_checks(frame)
    se_gen = checklib.bootstrap_se(evaluate_checks, frame, lambda f, rng: checklib.resample_frame(f, rng, "team_key"), n=boot) if boot else {}
    real = real_japanese_fielders() if boot else None
    se_real = checklib.bootstrap_se(evaluate_checks, real, checklib.resample_frame, n=boot) if real is not None else {}
    if boot:
        se_real.update(real_catcher_errors())
        se_real.update(real_special_errors())
        se_real.update(rank_shape.real_errors(SCRIPT, SHAPE_KEYS))
        se_real.update(rank_ability.real_errors(SCRIPT, ABILITY_KEYS))
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


def team_fielders(frame: pd.DataFrame) -> pd.DataFrame:
    fielders = frame[(frame["role"] == "野手") & (~frame["is_foreign"])]
    columns = ["team_key", "position", "age", "弾道", "rating", "n_red", "n_green", *ABILITIES, *RANK_COLUMNS, *SHAPE_COLUMNS, *ABILITY_RANK_COLUMNS, *SPECIAL_FLAG_COLUMNS]
    return fielders[columns].reset_index(drop=True)


def single_adults(path: Path) -> pd.DataFrame:
    """個別生成のサンプルCSVの日本人野手（査定の列は無い）。"""
    frame = single_fielders(path)
    frame["rating"] = np.nan
    return frame


def print_reference(generated: pd.DataFrame) -> None:
    main = adults(generated)
    rows = []
    for position in POSITIONS:
        d = main[main["position"] == position]
        row = {"ポジション": position, "人数": len(d)}
        for index, name in enumerate(ABILITIES):
            row[f"{name} 改修前→今回（実在）"] = f"{BEFORE[position][index]:.1f}→{d[name].mean():.1f}（{REAL_MEAN[position][index]:.1f}）"
        row["弾道 改修前→今回（実在）"] = f"{BEFORE[position][5]:.2f}→{d['弾道'].mean():.2f}（{REAL_TRAJECTORY[position][0]:.2f}）"
        row["査定 改修前→今回（実在）"] = f"{BEFORE[position][6]:.1f}→{d['rating'].mean():.1f}（{REAL_TRAJECTORY[position][2]:.1f}）"
        rows.append(row)
    print("\n[ポジション別の平均（改修前・今回・実在。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))
    young = generated[generated["age"] <= YOUNG_MAX_AGE]
    print(f"\n[21歳以下（参考。今回は変えていない）] {len(young)}人。パワー平均 {young['パワー'].mean():.2f}（改修前 46.13）")
    print_catcher_reference(generated)
    print_special_reference(generated)
    rank_shape.print_shape_reference(generated, SHAPE_KEYS)
    rank_ability.print_ability_reference(generated, ABILITY_KEYS)


def print_special_reference(generated: pd.DataFrame, before: bool = True) -> None:
    """捕手の特能（ミートの帯ごとの保有率、まとまりごとの三振。改修前・今回・実在。参考）。"""
    bands = pd.cut(generated["ミート"], [0, 30, 40, 50, 200], labels=["〜30", "31〜40", "41〜50", "51〜"])
    rows = []
    for group in (*SPECIAL_GROUPS, "全体"):
        part = special_group(generated, group)
        names = {"捕手": ("選球眼", "固め打ち", "三振", "広角打法", "ホーム死守"), "全体": ("選球眼", "三振")}.get(group, ("選球眼", "固め打ち", "三振"))
        for name in names:
            rates = part.groupby(bands.loc[part.index], observed=False)[f"sp_{name}"].mean() * 100
            old = BEFORE_SPECIALS.get(group, {}).get(name)
            rows.append({"まとまり": SPECIAL_GROUP_LABELS[group], "特能": name, **{str(k): round(float(v), 1) for k, v in rates.items()},
                         "全体": round(float(part[f"sp_{name}"].mean() * 100), 1), "改修前": old if before and old is not None else "",
                         "実在": REAL_SPECIALS[group].get(name, "")})
    print(f"\n[特能の保有率（%。全年齢、ミートの帯ごと。参考）] 捕手 {len(special_group(generated, '捕手'))}人")
    print(pd.DataFrame(rows).to_string(index=False))
    catchers = special_group(generated, "捕手")
    old = f"改修前 {BEFORE_SPECIALS['捕手']['緑特の数']:.2f}・{BEFORE_SPECIALS['捕手']['赤特の数']:.2f}、" if before else ""
    print(f"[捕手の緑特・赤特の数（参考）] 緑 {catchers['n_green'].mean():.2f}・赤 {catchers['n_red'].mean():.2f}（{old}実在 0.57・0.52）")


def print_catcher_reference(generated: pd.DataFrame, before: bool = True) -> None:
    """捕手のキャッチャーのランクの割合・ランク点（改修前・今回・実在。参考）。"""
    real = real_rank_reference()
    catchers = generated[generated["position"] == "捕手"]
    rows = [{"": "改修前", **dict(zip(LETTERS, BEFORE_CATCHER["割合"])), "ランク点": BEFORE_CATCHER["ランク点"]}] if before else []
    rows.append({"": "今回", **{x: round(float((catchers["rk_キャッチャー"] == x).mean() * 100), 1) for x in LETTERS},
                 "ランク点": round(float(catchers["pt_キャッチャー"].mean()), 2)})
    rows.append({"": "実在", **{x: round(v, 1) for x, v in real["捕手"]["キャッチャー_ランク"].items()}, "ランク点": round(real["捕手"]["キャッチャー"][0], 2)})
    print(f"\n[捕手のキャッチャーのランクの割合（%）・ランク点（参考）] 捕手 {len(catchers)}人")
    print(pd.DataFrame(rows).to_string(index=False))
    sub = generated[(generated["position"] != "捕手") & (generated["rk_キャッチャー"] != "D")]
    if "rating" in catchers and catchers["rating"].notna().any():
        print(f"[捕手の査定の平均（全年齢。参考）] {catchers['rating'].mean():.1f}（改修前 223.5、実在 222.7）")
    print(f"[サブポジ捕手でキャッチャーがD以外（今の重みのまま。参考）] {len(sub)}人")


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）野手の22歳以上のポジション別の型を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--single-csv", type=Path, default=None, help="個別生成（架空球団用・野手）のサンプルCSV。あれば同じ表を参考として出す")
    checklib.add_common_args(parser)
    args = parser.parse_args()

    frame = collect(args.teams, args.start, args.workers)
    generated = team_fielders(frame)
    title = f"球団生成 {args.teams}球団（seed {args.start}〜{args.start + args.teams - 1}） 日本人野手 {len(generated)}人（22歳以上 {len(adults(generated))}人）"
    graded = grade_all(generated, args.boot, args.quick)
    checklib.print_checks(graded, title)
    print_reference(generated)
    if args.single_csv is not None and args.single_csv.exists():
        single = single_adults(args.single_csv)
        reference = list(checklib.grade(evaluate(single, f"{SCRIPT}.single", info=True), all_info=True))
        checklib.print_checks(reference, f"個別生成（架空球団用・日本人野手 {len(single)}人。参考）")
        print_catcher_reference(single, before=False)
        print_special_reference(single, before=False)
        rank_shape.print_shape_reference(single, SHAPE_KEYS, before=False)
        rank_ability.print_ability_reference(single, ABILITY_KEYS, before=False)
        graded += reference
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    main()
