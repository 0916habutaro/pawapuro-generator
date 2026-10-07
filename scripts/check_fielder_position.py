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
from check_fielder_batting import real_japanese_fielders, single_fielders  # noqa: E402
from check_pitcher_control import collect  # noqa: E402
from checklib import Checks  # noqa: E402

SCRIPT = "check_fielder_position"
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
SECTIONS = {
    "mean": "ポジション×能力の平均（実在は2024〜2026年版の日本人野手・22歳以上）",
    "sd": "ポジション×能力の標準偏差の比（生成÷実在）",
    "traj_mean": "ポジションごとの弾道の平均",
    "traj_share": "ポジションごとの弾道の割合（%）",
    "rating": "ポジションごとの査定の平均",
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
    return checks


def grade_all(frame: pd.DataFrame, boot: int, quick: bool = False) -> list[checklib.Check]:
    """球団を単位に生成側の誤差を、実在の野手を単位に実在側の誤差を求めて合否を付ける。"""
    evaluate_checks = lambda f: evaluate(f)  # noqa: E731
    checks = evaluate_checks(frame)
    se_gen = checklib.bootstrap_se(evaluate_checks, frame, lambda f, rng: checklib.resample_frame(f, rng, "team_key"), n=boot) if boot else {}
    real = real_japanese_fielders() if boot else None
    se_real = checklib.bootstrap_se(evaluate_checks, real, checklib.resample_frame, n=boot) if real is not None else {}
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


def team_fielders(frame: pd.DataFrame) -> pd.DataFrame:
    fielders = frame[(frame["role"] == "野手") & (~frame["is_foreign"])]
    return fielders[["team_key", "position", "age", "弾道", "rating", *ABILITIES]].reset_index(drop=True)


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
        graded += reference
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    main()
