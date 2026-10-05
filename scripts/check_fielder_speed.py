#!/usr/bin/env python3
"""
架空球団用（日本人）野手の走力（年齢・ポジション・打席）を、球団生成で判定する（`野手の走力_改修指示.md`）。

使い方:
    python scripts/check_fielder_speed.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_fielder_speed.py --teams 60      # 途中確認用
    python scripts/check_fielder_speed.py --single-csv reports/checks/samples/fictional_fielders.csv   # 個別生成の参考表も出す

- 球団生成で作った球団の日本人野手を、実在（2024〜2026年版の日本人野手1,103人）と比べる。
- 判定する項目（指示書2-1）: 全体の平均、5%・25%・中央・75%・95%、ポジションごとの平均・標準偏差、打席ごとの平均（右打・左打）、
  同じポジションの中の左右差（一塁手・二塁手・外野手・捕手）、年齢帯ごとの差（22〜23歳から36歳〜まで。ポジションの平均を引いた値）。
- 年齢帯ごとの差の目標は、実在の2つのデータの平均。年齢がわかるのは2026年版だけ（12球団、人数が少ない）で、2022〜2025年版は
  2026年版の名簿から逆算した年齢（age_backcalc。2026年まで残った選手に偏る）を使うため、片方に強く合わせない。
  実在側の誤差には、2つのデータの差の半分を足す。
- 21歳以下は今回変えていない（若手の補正 `fictional_young_transform` の範囲）ので、参考表示にする。
- 個別生成（架空球団用・野手）は同じ表を参考として出す（合否には使わない）。
- 判定の種類・誤差・合否の付け方は checklib.py（判定の整理_改修指示.md）。誤差は、生成側は球団、実在側は実在の野手を再抽出して見積もる。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import checklib  # noqa: E402
from check_pitcher_control import collect  # noqa: E402
from checklib import Checks  # noqa: E402

SCRIPT = "check_fielder_speed"
POSITIONS = ("一塁手", "二塁手", "三塁手", "遊撃手", "外野手", "捕手")
# 実在（2024〜2026年版の日本人野手1,103人）の走力。判定の目標。
REAL_MEAN = 64.43
REAL_QUANTILES = {"5%": 39.0, "25%": 56.0, "中央": 64.0, "75%": 75.0, "95%": 87.0}
REAL_POSITION = {  # ポジション: (平均, 標準偏差)
    "一塁手": (50.30, 10.59), "二塁手": (72.49, 10.90), "三塁手": (58.12, 12.00),
    "遊撃手": (70.46, 9.52), "外野手": (71.72, 12.29), "捕手": (51.82, 11.03),
}
REAL_BATS = {"右": 59.91, "左": 68.99}  # 両打は人数が少ない（14人）ので判定しない
REAL_BATS_GAP = {"一塁手": 8.23, "二塁手": 7.33, "外野手": 4.10, "捕手": 4.85}  # 同じポジションの中の左打−右打
# 年齢帯ごとの差（ポジションの平均を引いた走力の平均）。(2026年版, 2022〜2025年版の逆算)
REAL_AGE_BANDS = {
    "〜21": (-1.93, -2.27), "22〜23": (-0.59, -0.39), "24〜25": (-0.32, 1.35), "26〜27": (1.16, 3.39), "28〜29": (2.25, 2.99),
    "30〜31": (4.83, -0.88), "32〜33": (-0.74, -2.43), "34〜35": (-1.75, -4.56), "36〜": (-6.81, -8.56),
}
AGE_BANDS = (
    ("〜21", 0, 21), ("22〜23", 22, 23), ("24〜25", 24, 25), ("26〜27", 26, 27), ("28〜29", 28, 29),
    ("30〜31", 30, 31), ("32〜33", 32, 33), ("34〜35", 34, 35), ("36〜", 36, 99),
)
# 合格の範囲（指示書2-1）
TOL_MEAN, TOL_QUANTILE, TOL_POSITION_MEAN, TOL_POSITION_SD, TOL_BATS, TOL_BATS_GAP, TOL_AGE = 0.6, 2.0, 1.5, 1.5, 1.5, 3.0, 2.5
# 改修前（球団生成 seed 1〜300、PR #112 の main）の値。表示用
BEFORE = {
    "mean": 64.81, "sd": 15.29, "age": {"〜21": -3.60, "22〜23": 3.12, "24〜25": 4.14, "26〜27": 3.04, "28〜29": 0.95, "30〜31": -3.76, "32〜33": -3.83, "34〜35": -5.83, "36〜": -11.10},
}


def age_band_of(age: float) -> str | None:
    if pd.isna(age):
        return None
    return next((label for label, low, high in AGE_BANDS if low <= age <= high), None)


def band_diffs(frame: pd.DataFrame, age_column: str) -> pd.Series:
    """年齢帯ごとの「走力 − そのポジションの平均」の平均（ポジションの平均は frame 全体で求める）。"""
    d = frame[frame[age_column].notna() & frame["走力"].notna()]
    diff = d["走力"] - d.groupby("position")["走力"].transform("mean")
    return diff.groupby(d[age_column].map(age_band_of)).mean().reindex([b[0] for b in AGE_BANDS])


def evaluate(frame: pd.DataFrame, prefix: str = SCRIPT, info: bool = False) -> Checks:
    """frame: 日本人野手（列 position, bats, 走力, age）。実在のときは season・age_backcalc もある
    （位置・打席・分布は2024〜2026年版、年齢帯は2026年版と逆算の平均）。info=True ならすべて参考（個別生成）。"""
    is_real = "season" in frame.columns
    main = frame[frame["season"] >= 2024] if is_real else frame
    checks = Checks(prefix)
    kind = checklib.KIND_INFO if info else checklib.KIND_REAL

    def add(section: str, key: str, label: str, value: float, real: float, tol: float, fmt: str = "{:.2f}") -> None:
        low, high = real - tol, real + tol
        checks.add(f"{prefix}.{section}.{key}", kind, label, value, low, high, section=SECTIONS[section],
                   shown=fmt.format(value), target=f"{low:.2f}〜{high:.2f}", real=fmt.format(real))

    speed = main["走力"]
    add("overall", "mean", "全体の平均", speed.mean(), REAL_MEAN, TOL_MEAN)
    for label, q in zip(REAL_QUANTILES, speed.quantile([0.05, 0.25, 0.5, 0.75, 0.95])):
        add("overall", f"q_{label}", f"全体の{label}", q, REAL_QUANTILES[label], TOL_QUANTILE, "{:.0f}")
    for position in POSITIONS:
        x = main.loc[main["position"] == position, "走力"]
        add("position", f"mean_{position}", f"{position} 平均", x.mean(), REAL_POSITION[position][0], TOL_POSITION_MEAN)
        add("position", f"sd_{position}", f"{position} 標準偏差", x.std(), REAL_POSITION[position][1], TOL_POSITION_SD)
    for bats, real in REAL_BATS.items():
        add("bats", f"mean_{bats}", f"{bats}打 平均", main.loc[main["bats"] == bats, "走力"].mean(), real, TOL_BATS)
    for position, real in REAL_BATS_GAP.items():
        d = main[main["position"] == position]
        gap = d.loc[d["bats"] == "左", "走力"].mean() - d.loc[d["bats"] == "右", "走力"].mean()
        add("bats_gap", position, f"{position} 左右差（左打−右打）", gap, real, TOL_BATS_GAP, "{:+.2f}")
    if is_real:  # 2つの実在データの平均（それぞれ、そのデータの中のポジションの平均を引く）
        a = band_diffs(frame[frame["season"] == 2026], "age")
        b = band_diffs(frame[frame["season"] <= 2025], "age_backcalc")
        diffs = (a + b) / 2
    else:
        diffs = band_diffs(frame, "age")
    for label, _low, _high in AGE_BANDS:
        real = float(np.mean(REAL_AGE_BANDS[label]))
        target_kind = checklib.KIND_INFO if label == "〜21" else kind
        value = float(diffs[label])
        low, high = real - TOL_AGE, real + TOL_AGE
        checks.add(f"{prefix}.age.{label}", target_kind, f"{label}歳 ポジションの平均との差", value, low, high, section=SECTIONS["age"],
                   shown=f"{value:+.2f}", target=f"{low:+.2f}〜{high:+.2f}", real=f"{real:+.2f}（2026 {REAL_AGE_BANDS[label][0]:+.2f}／逆算 {REAL_AGE_BANDS[label][1]:+.2f}）")
    return checks


SECTIONS = {
    "overall": "全体の分布（実在は2024〜2026年版の日本人野手）",
    "position": "ポジションごとの平均・標準偏差",
    "bats": "打席ごとの平均",
    "bats_gap": "同じポジションの中の左右差",
    "age": "年齢帯ごとの差（実在は2026年版と逆算の平均）",
}


def real_japanese_fielders() -> pd.DataFrame | None:
    """実在（2022〜2026年版の日本人野手）。選手データ（local_data）が無いときは None。"""
    from generator import real_data

    players = real_data.load_real_players((2022, 2023, 2024, 2025, 2026))
    if players is None:
        return None
    return players[(players["role"] == "野手") & (~players["is_foreign"])].reset_index(drop=True)


def real_age_gap_halves() -> dict[str, float]:
    """年齢帯ごとの、実在の2つのデータの差の半分。実在側の誤差に足す。"""
    return {f"{SCRIPT}.age.{label}": abs(a - b) / 2 for label, (a, b) in REAL_AGE_BANDS.items()}


def grade_all(frame: pd.DataFrame, boot: int, quick: bool = False) -> list[checklib.Check]:
    """球団を単位に生成側の誤差を、実在の野手を単位に実在側の誤差を求めて合否を付ける。"""
    evaluate_checks = lambda f: evaluate(f)  # noqa: E731
    checks = evaluate_checks(frame)
    se_gen = checklib.bootstrap_se(evaluate_checks, frame, lambda f, rng: checklib.resample_frame(f, rng, "team_key"), n=boot) if boot else {}
    real = real_japanese_fielders() if boot else None
    se_real = checklib.bootstrap_se(evaluate_checks, real, checklib.resample_frame, n=boot) if real is not None else {}
    for key, half in real_age_gap_halves().items():
        if key in se_real:
            se_real[key] += half
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


def team_fielders(frame: pd.DataFrame) -> pd.DataFrame:
    fielders = frame[(frame["role"] == "野手") & (~frame["is_foreign"])]
    return fielders[["team_key", "position", "bats", "走力", "age"]].reset_index(drop=True)


def single_fielders(path: Path) -> pd.DataFrame:
    """個別生成のサンプルCSV（generate_fictional_balance_sample.py の野手）から、日本人野手を取り出す。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df[(df["category"] == "架空球団用") & (df["roster_origin"] == "domestic") & (df["role"] == "野手")]
    speed = df["abilities_json"].map(lambda text: (json.loads(text).get("走力") or {}).get("value", np.nan))
    bats = df["batting_throwing"].fillna("").map(lambda text: text[2:3])
    return pd.DataFrame({"position": df["position"].to_numpy(), "bats": bats.to_numpy(), "走力": speed.to_numpy(dtype=float), "age": df["age"].to_numpy(dtype=float)})


def print_reference(generated: pd.DataFrame) -> None:
    diffs = band_diffs(generated, "age")
    print("\n[年齢帯ごとの差（改修前・今回・実在。参考。ポジションの平均を引いた値）]")
    rows = []
    for label, _low, _high in AGE_BANDS:
        a, b = REAL_AGE_BANDS[label]
        rows.append({"年齢帯": label, "改修前": BEFORE["age"].get(label, np.nan), "今回": round(float(diffs[label]), 2),
                     "実在2026": a, "逆算": b, "平均": round((a + b) / 2, 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    team_mean = generated.groupby("team_key")["走力"].mean()
    print(f"\n[球団ごとの走力の平均の標準偏差（参考）] {team_mean.std():.2f}（球団生成の日本人野手。実在の目安は 1.59。球団ごとの散らばりは validate_team_mode.py）")


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）野手の走力を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--single-csv", type=Path, default=None, help="個別生成（架空球団用・野手）のサンプルCSV。あれば同じ表を参考として出す")
    checklib.add_common_args(parser)
    args = parser.parse_args()

    frame = collect(args.teams, args.start, args.workers)
    generated = team_fielders(frame)
    title = f"球団生成 {args.teams}球団（seed {args.start}〜{args.start + args.teams - 1}） 日本人野手 {len(generated)}人"
    graded = grade_all(generated, args.boot, args.quick)
    checklib.print_checks(graded, title)
    print_reference(generated)
    if args.single_csv is not None and args.single_csv.exists():
        single = single_fielders(args.single_csv)
        reference = list(checklib.grade(evaluate(single, f"{SCRIPT}.single", info=True), all_info=True))
        checklib.print_checks(reference, f"個別生成（架空球団用・日本人野手 {len(single)}人。参考）")
        graded += reference
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    main()
