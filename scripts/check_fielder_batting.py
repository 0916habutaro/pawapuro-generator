#!/usr/bin/env python3
"""
架空球団用（日本人）野手の打席ごとの能力（ミートの左右差ほか）を、球団生成で判定する（`野手の打席の型_改修指示.md`）。

使い方:
    python scripts/check_fielder_batting.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_fielder_batting.py --teams 60      # 途中確認用
    python scripts/check_fielder_batting.py --single-csv reports/checks/samples/fictional_fielders.csv   # 個別生成の参考表も出す

- 球団生成で作った球団の日本人野手を、実在（2024〜2026年版の日本人野手1,103人）と比べる。
- 判定する項目（指示書2-1）: ミート・パワー・守備力・肩力・捕球の右打・左打それぞれの平均と左−右、ミートの全体の平均、
  ミートの左打の10%・中央・90%、弾道の左−右、21歳以下のミートの左−右。走力は check_fielder_speed.py が受け持つ。
- 両打は人数が少ない（実在14人）ので判定しない。
- 個別生成（架空球団用・野手）は同じ表を参考として出す（合否には使わない）。
- 判定の種類・誤差・合否の付け方は checklib.py。誤差は、生成側は球団、実在側は実在の野手を再抽出して見積もる。
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

SCRIPT = "check_fielder_batting"
ABILITIES = ("ミート", "パワー", "守備力", "肩力", "捕球")
# 実在（2024〜2026年版の日本人野手1,103人）の打席ごとの平均。判定の目標。
REAL_BATS = {
    "ミート": {"右": 39.45, "左": 45.15}, "パワー": {"右": 53.80, "左": 51.28}, "守備力": {"右": 50.39, "左": 53.50},
    "肩力": {"右": 66.95, "左": 65.22}, "捕球": {"右": 47.98, "左": 49.22},
}
REAL_CONTACT_MEAN = 42.11
REAL_CONTACT_LEFT_QUANTILES = {"10%": 33.0, "中央": 44.0, "90%": 60.0}
REAL_TRAJECTORY_GAP = -0.18
REAL_YOUNG_CONTACT_GAP = (2.5, 5.5)  # 21歳以下のミートの左−右（実在は +3.5〜+4.1）。範囲で判定する
# 合格の範囲（指示書2-1）
TOL_MEAN, TOL_GAP, TOL_CONTACT_MEAN, TOL_QUANTILE, TOL_TRAJECTORY_GAP = 1.0, 1.0, 0.8, 3.0, 0.12
# 改修前（球団生成 seed 1〜300、PR #113 の main）の値。表示用
BEFORE = {
    "ミート": {"右": 39.61, "左": 39.77}, "パワー": {"右": 52.87, "左": 52.60}, "守備力": {"右": 51.48, "左": 52.29},
    "肩力": {"右": 66.77, "左": 66.38}, "捕球": {"右": 48.23, "左": 48.11},
}
SECTIONS = {
    "bats": "打席ごとの平均（実在は2024〜2026年版の日本人野手）",
    "gap": "左−右（左打の平均 − 右打の平均）",
    "contact": "ミートの分布",
    "young": "21歳以下",
}


def mean_by(frame: pd.DataFrame, key: str, bats: str) -> float:
    return float(frame.loc[frame["bats"] == bats, key].mean())


def evaluate(frame: pd.DataFrame, prefix: str = SCRIPT, info: bool = False) -> Checks:
    """frame: 日本人野手（列 bats, ミート〜捕球, 弾道, age, team_key）。実在のときは season もある（2024〜2026年版）。
    21歳以下は、実在は全年版（2026年版は age、2022〜2025年版は逆算年齢）を使う。info=True ならすべて参考（個別生成）。"""
    is_real = "season" in frame.columns
    main = frame[frame["season"] >= 2024] if is_real else frame
    checks = Checks(prefix)
    kind = checklib.KIND_INFO if info else checklib.KIND_REAL

    def add(section: str, key: str, label: str, value: float, real: float, tol: float, fmt: str = "{:.2f}") -> None:
        low, high = real - tol, real + tol
        checks.add(f"{prefix}.{section}.{key}", kind, label, value, low, high, section=SECTIONS[section],
                   shown=fmt.format(value), target=f"{low:.2f}〜{high:.2f}", real=fmt.format(real))

    for name in ABILITIES:
        for bats in ("右", "左"):
            add("bats", f"{name}_{bats}", f"{name} {bats}打 平均", mean_by(main, name, bats), REAL_BATS[name][bats], TOL_MEAN)
    for name in ABILITIES:
        real = REAL_BATS[name]["左"] - REAL_BATS[name]["右"]
        add("gap", name, f"{name} 左−右", mean_by(main, name, "左") - mean_by(main, name, "右"), real, TOL_GAP, "{:+.2f}")
    add("gap", "弾道", "弾道 左−右", mean_by(main, "弾道", "左") - mean_by(main, "弾道", "右"), REAL_TRAJECTORY_GAP, TOL_TRAJECTORY_GAP, "{:+.2f}")
    add("contact", "mean", "ミート 日本人全体の平均", float(main["ミート"].mean()), REAL_CONTACT_MEAN, TOL_CONTACT_MEAN)
    left_contact = main.loc[main["bats"] == "左", "ミート"]
    for label, q in zip(REAL_CONTACT_LEFT_QUANTILES, left_contact.quantile([0.1, 0.5, 0.9])):
        add("contact", f"left_{label}", f"ミート 左打の{label}", float(q), REAL_CONTACT_LEFT_QUANTILES[label], TOL_QUANTILE, "{:.0f}")
    if is_real:
        age = frame["age"].where(frame["season"] == 2026, frame["age_backcalc"])
        young = frame[age <= 21]
    else:
        young = frame[frame["age"] <= 21]
    gap = mean_by(young, "ミート", "左") - mean_by(young, "ミート", "右")
    low, high = REAL_YOUNG_CONTACT_GAP
    checks.add(f"{prefix}.young.contact_gap", kind, "21歳以下 ミート 左−右", gap, low, high, section=SECTIONS["young"],
               shown=f"{gap:+.2f}", target=f"{low:+.2f}〜{high:+.2f}", real="+3.5〜+4.1")
    return checks


def real_japanese_fielders() -> pd.DataFrame | None:
    """実在（2022〜2026年版の日本人野手）。選手データ（local_data）が無いときは None。"""
    from generator import real_data

    players = real_data.load_real_players((2022, 2023, 2024, 2025, 2026))
    if players is None:
        return None
    return players[(players["role"] == "野手") & (~players["is_foreign"])].reset_index(drop=True)


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
    return fielders[["team_key", "position", "bats", "age", "弾道", *ABILITIES]].reset_index(drop=True)


def single_fielders(path: Path) -> pd.DataFrame:
    """個別生成のサンプルCSV（generate_fictional_balance_sample.py の野手）から、日本人野手を取り出す。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df[(df["category"] == "架空球団用") & (df["roster_origin"] == "domestic") & (df["role"] == "野手")]
    parsed = df["abilities_json"].map(json.loads)

    def value(key: str) -> list[float]:
        out = []
        for abilities in parsed:
            item = abilities.get(key)
            out.append(float(item["value"] if isinstance(item, dict) else item) if item is not None else np.nan)
        return out

    frame = pd.DataFrame({"position": df["position"].to_numpy(), "bats": df["batting_throwing"].fillna("").map(lambda text: text[2:3]).to_numpy(),
                          "age": df["age"].to_numpy(dtype=float), "弾道": value("弾道"), **{name: value(name) for name in ABILITIES}})
    frame["team_key"] = "single"
    return frame


def print_reference(generated: pd.DataFrame) -> None:
    rows = []
    for name in ABILITIES:
        for bats in ("右", "左"):
            rows.append({"能力": name, "打席": bats, "改修前": BEFORE[name][bats], "今回": round(mean_by(generated, name, bats), 2), "実在": REAL_BATS[name][bats]})
    print("\n[打席ごとの平均（改修前・今回・実在。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))
    both = generated[generated["bats"] == "両"]
    print(f"\n[両打（ずらしなし。参考）] {len(both)}人 / {len(generated)}人。ミート平均 {both['ミート'].mean():.2f}（実在 36.29）")
    young = generated[generated["age"] <= 21]
    print(f"[21歳以下のミート平均（参考）] {young['ミート'].mean():.2f}（{len(young)}人。改修前 32.47）")


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）野手の打席ごとの能力を、球団生成で判定します。")
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
