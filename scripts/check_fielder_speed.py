#!/usr/bin/env python3
"""
架空球団用（日本人）野手の走力（年齢・ポジション・打席）を、球団生成で判定する（`野手の走力_改修指示.md`）。

使い方:
    python scripts/check_fielder_speed.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_fielder_speed.py --teams 60      # 途中確認用
    python scripts/check_fielder_speed.py --single-csv reports/checks/samples/fictional_fielders.csv   # 個別生成の参考表も出す
    python scripts/check_fielder_speed.py --build-real    # 実在の走塁・盗塁・送球のランクの集計（data/config/fielder_speed_rank_real.json）を作り直す

- 球団生成で作った球団の日本人野手を、実在（2024〜2026年版の日本人野手1,103人）と比べる。
- 判定する項目（指示書2-1）: 全体の平均、5%・25%・中央・75%・95%、ポジションごとの平均・標準偏差、打席ごとの平均（右打・左打）、
  同じポジションの中の左右差（一塁手・二塁手・外野手・捕手）、年齢帯ごとの差（22〜23歳から36歳〜まで。ポジションの平均を引いた値）。
- 年齢帯ごとの差の目標は、実在の2つのデータの平均。年齢がわかるのは2026年版だけ（12球団、人数が少ない）で、2022〜2025年版は
  2026年版の名簿から逆算した年齢（age_backcalc。2026年まで残った選手に偏る）を使うため、片方に強く合わせない。
  実在側の誤差には、2つのデータの差の半分を足す。
- 走塁・盗塁・送球のランク（`野手の走力肩力ランク_改修指示.md` 2-1）: 走塁・盗塁は走力の帯、送球は肩力の帯ごとのランク点（実在±0.5）、
  走塁・盗塁・送球のランク点の全体（実在±0.2）、ランク点の合計（全体・左打・右打。実在±0.4）。ランク点は査定のランク点
  （D=0。generator/rating.py の ranked_points と同じ表）。持たない項目は D として数える。実在の値は
  data/config/fielder_speed_rank_real.json（--build-real で、実在の元データ data/raw/ から作る）。実在側の誤差は 標準偏差/√人数。
- 21歳以下は今回変えていない（若手の補正 `fictional_young_transform` の範囲）ので、参考表示にする。
- 個別生成（架空球団用・野手）は同じ表を参考として出す（合否には使わない）。
- 判定の種類・誤差・合否の付け方は checklib.py（判定の整理_改修指示.md）。誤差は、生成側は球団、実在側は実在の野手を再抽出して見積もる。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import check_pitcher_control  # noqa: E402
import checklib  # noqa: E402
from checklib import Checks  # noqa: E402
from generator import team_analysis  # noqa: E402
from generator.rating import load_table, ranked_points  # noqa: E402

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
# 走塁・盗塁・送球のランク（野手の走力肩力ランク_改修指示.md 2-1）
REAL_RANK_PATH = APP_DIR / "data" / "config" / "fielder_speed_rank_real.json"
REAL_RANK_SEASONS = (2024, 2025, 2026)
LETTERS = ("A", "B", "C", "D", "E", "F", "G")
RANK_GROUPS = ("走塁", "盗塁", "送球")
RANK_ABILITY = {"走塁": "走力", "盗塁": "走力", "送球": "肩力"}
# 帯（ラベル, 下限）。走力・肩力がその下限以上で、次の帯の下限未満
RANK_BANDS = {
    "走力": (("〜49", -999), ("50〜59", 50), ("60〜69", 60), ("70〜79", 70), ("80〜", 80)),
    "肩力": (("〜54", -999), ("55〜64", 55), ("65〜74", 65), ("75〜79", 75), ("80〜", 80)),
}
RANK_TOTALS = {"全体": None, "左打": "左", "右打": "右"}
TOL_RANK_BAND, TOL_RANK_OVERALL, TOL_RANK_TOTAL = 0.5, 0.2, 0.4
# 改修前（球団生成 seed 1〜300、PR #123 をマージした main 62bd460）の値。表示用
BEFORE_RANK = {
    "band": {
        "走塁": (0.28, 1.30, 1.31, 1.41, 2.60), "盗塁": (-2.16, -0.44, -0.34, -0.18, 1.82), "送球": (-1.29, -0.45, -0.43, -0.34, 0.57),
    },
    "overall": {"走塁": 1.35, "盗塁": -0.30, "送球": -0.44},
    "total": {"全体": -0.22, "左打": -0.93, "右打": 0.38},
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
    if "pt_走塁" in frame.columns:  # 実在の選手単位データ（local_data）にはランク特能の列が無い。実在の値は fielder_speed_rank_real.json
        rank_checks(checks, main, prefix, kind)
    return checks


SECTIONS = {
    "overall": "全体の分布（実在は2024〜2026年版の日本人野手）",
    "position": "ポジションごとの平均・標準偏差",
    "bats": "打席ごとの平均",
    "bats_gap": "同じポジションの中の左右差",
    "age": "年齢帯ごとの差（実在は2026年版と逆算の平均）",
    "rank_band": "走塁・盗塁（走力の帯）・送球（肩力の帯）のランク点（D=0。実在は2024〜2026年版の日本人野手。±0.5）",
    "rank_overall": "走塁・盗塁・送球のランク点の全体（実在±0.2）",
    "rank_total": "ランク点の合計（全体・左打・右打。実在±0.4）",
}


# ---------------------------------------------------------------------------
# 走塁・盗塁・送球のランク。生成・実在で同じ数え方をする
# ---------------------------------------------------------------------------
def rank_band_of(ability: str, value: float) -> str | None:
    if pd.isna(value):
        return None
    label = None
    for name, low in RANK_BANDS[ability]:
        if value >= low:
            label = name
    return label


def rank_point_table() -> dict[str, dict[str, int]]:
    """ランク特能ごとの、ランクの文字 → 査定のランク点（野手）。"""
    t = load_table()
    out = {}
    for group in RANK_GROUPS:
        table = t["rank_table_major"] if group in t["ranked_major"]["野手"] else t["rank_table_minor"]
        out[group] = {letter: int(table.get(letter, 0)) for letter in LETTERS}
    return out


def rank_columns(ranked: dict[str, str]) -> dict[str, float]:
    """1人分のランク特能の列（rank_points と pt_走塁・pt_盗塁・pt_送球）。持たない項目は D。"""
    points = rank_point_table()
    row = {"rank_points": float(ranked_points(ranked, "野手"))}
    for group in RANK_GROUPS:
        letter = str(ranked.get(group) or "D")[-1:]
        row[f"pt_{group}"] = float(points[group].get(letter, 0))
    return row


def _stat(x: pd.Series) -> list[float]:
    x = pd.Series(x, dtype=float).dropna()
    return [round(float(x.mean()), 4), round(float(x.std()), 4), int(len(x))]


def rank_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    """frame（列 bats・走力・肩力・rank_points・pt_走塁〜pt_送球）の、帯ごと・全体・合計の [平均, 標準偏差, 人数]。"""
    out: dict[str, Any] = {"band": {}, "overall": {}, "total": {}}
    for group in RANK_GROUPS:
        ability = RANK_ABILITY[group]
        bands = frame[ability].map(lambda v: rank_band_of(ability, v))
        out["band"][group] = {label: _stat(frame.loc[bands == label, f"pt_{group}"]) for label, _low in RANK_BANDS[ability]}
        out["overall"][group] = _stat(frame[f"pt_{group}"])
    for label, bats in RANK_TOTALS.items():
        part = frame if bats is None else frame[frame["bats"] == bats]
        out["total"][label] = _stat(part["rank_points"])
    return out


def load_real_rank_rows() -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人野手。元データ（data/raw/ の zip と 2026年版のフォルダ）から読む。"""
    import tempfile

    import build_real_team_reference as ref
    from generator import real_data

    foreign_keys = ref.foreign_list_keys(ref.DEFAULT_FOREIGN_LIST)
    entry = ref.load_entry_route(ref.DEFAULT_ENTRY_ROUTE)
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        folders = ref.extract_seasons(ref.DEFAULT_ZIP, Path(temp))
        folders[real_data.AGE_SEASON] = ref.DEFAULT_RAW_2026
        for season, folder in sorted(folders.items()):
            if season not in REAL_RANK_SEASONS:
                continue
            tables, _ = ref.parse_directory(folder)
            players = ref.decorate_season(tables["players"], season, foreign_keys, entry)
            for row in real_data.attach_real_details(players, tables["specials"], tables["breaking"]):
                if row.get("is_foreign") or row.get("role") == "投手":
                    continue
                ranked = {name[:-1]: name for name, kind in row.get("specials") or [] if kind == "rank"}
                _throws, bats = team_analysis._hand_parts(row.get("throws_bats"))
                rows.append({"season": season, "bats": bats, "走力": float(row.get("run_speed")), "肩力": float(row.get("arm_strength")), **rank_columns(ranked)})
    return pd.DataFrame(rows)


def build_real() -> None:
    rows = load_real_rank_rows()
    data = {
        "作り方": "scripts/check_fielder_speed.py --build-real。実在（2024〜2026年版）の日本人野手（外国人を除く）。打席は投打の3文字目。"
                 "ランク点は査定のランク点（D=0、持たない項目はD）。帯は走塁・盗塁が走力、送球が肩力。[平均, 標準偏差, 人数]",
        "実在": rank_statistics(rows),
    }
    REAL_RANK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_RANK_PATH}（{len(rows)}人）")


def real_rank_reference() -> dict[str, Any]:
    return json.loads(REAL_RANK_PATH.read_text(encoding="utf-8"))["実在"]


def mean_se(stat: list[float]) -> float:
    return stat[1] / math.sqrt(stat[2]) if stat[2] > 1 else math.nan


def rank_items(prefix: str) -> list[tuple[str, str, str, list[float], float]]:
    """(id, 節, 表示名, 実在の [平均, 標準偏差, 人数], 範囲の幅) の一覧。"""
    real = real_rank_reference()
    items = []
    for group in RANK_GROUPS:
        ability = RANK_ABILITY[group]
        for label, _low in RANK_BANDS[ability]:
            items.append((f"{prefix}.rank_band.{group}_{label}", "rank_band", f"{group}（{ability} {label}）", real["band"][group][label], TOL_RANK_BAND))
    for group in RANK_GROUPS:
        items.append((f"{prefix}.rank_overall.{group}", "rank_overall", f"{group}のランク点 全体", real["overall"][group], TOL_RANK_OVERALL))
    for label in RANK_TOTALS:
        items.append((f"{prefix}.rank_total.{label}", "rank_total", f"ランク点の合計 {label}", real["total"][label], TOL_RANK_TOTAL))
    return items


def real_rank_errors(prefix: str = SCRIPT) -> dict[str, float]:
    return {key: mean_se(stat) for key, _section, _label, stat, _tol in rank_items(prefix)}


def rank_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """走塁・盗塁・送球のランク点（帯ごと・全体）とランク点の合計。"""
    stats = rank_statistics(frame)
    values = {f"{prefix}.rank_band.{g}_{label}": v[0] for g, bands in stats["band"].items() for label, v in bands.items()}
    values.update({f"{prefix}.rank_overall.{g}": v[0] for g, v in stats["overall"].items()})
    values.update({f"{prefix}.rank_total.{label}": v[0] for label, v in stats["total"].items()})
    for key, section, label, real, tol in rank_items(prefix):
        value, r = float(values[key]), real[0]
        low, high = r - tol, r + tol
        checks.add(key, kind, label, value, low, high, section=SECTIONS[section],
                   shown=f"{value:+.2f}", target=f"{low:+.2f}〜{high:+.2f}", real=f"{r:+.2f}（{real[2]}人）")


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
    if boot:
        se_real.update(real_rank_errors())
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


RANK_COLUMNS = ("rank_points", *(f"pt_{group}" for group in RANK_GROUPS))


def _team(team_seed: int) -> pd.DataFrame:
    """球団分析の表に、走塁・盗塁・送球のランク点の列を足したもの。"""
    import app

    team = app.generate_team(team_seed, master=check_pitcher_control._MASTER)
    frame = team_analysis.players_frame(team["players"], f"gen:{team_seed}", str(team_seed)).drop(columns=["rank_points"])
    ranks = pd.DataFrame([rank_columns((p.get("abilities") or {}).get("ranked_specials") or {}) for p in team["players"]])
    return pd.concat([frame.reset_index(drop=True), ranks], axis=1)


def collect(teams: int, start: int, workers: int) -> pd.DataFrame:
    with ProcessPoolExecutor(max_workers=workers, initializer=check_pitcher_control._init_worker) as pool:
        frames = list(pool.map(_team, range(start, start + teams), chunksize=4))
    return pd.concat(frames, ignore_index=True)


def team_fielders(frame: pd.DataFrame) -> pd.DataFrame:
    fielders = frame[(frame["role"] == "野手") & (~frame["is_foreign"])]
    return fielders[["team_key", "position", "bats", "走力", "肩力", "age", *RANK_COLUMNS]].reset_index(drop=True)


def single_fielders(path: Path) -> pd.DataFrame:
    """個別生成のサンプルCSV（generate_fictional_balance_sample.py の野手）から、日本人野手を取り出す。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df[(df["category"] == "架空球団用") & (df["roster_origin"] == "domestic") & (df["role"] == "野手")]
    parsed = df["abilities_json"].map(json.loads)
    speed = parsed.map(lambda a: (a.get("走力") or {}).get("value", np.nan))
    arm = parsed.map(lambda a: (a.get("肩力") or {}).get("value", np.nan))
    bats = df["batting_throwing"].fillna("").map(lambda text: text[2:3])
    frame = pd.DataFrame({"position": df["position"].to_numpy(), "bats": bats.to_numpy(), "走力": speed.to_numpy(dtype=float),
                          "肩力": arm.to_numpy(dtype=float), "age": df["age"].to_numpy(dtype=float)})
    ranks = pd.DataFrame([rank_columns(a.get("ranked_specials") or {}) for a in parsed])
    return pd.concat([frame, ranks], axis=1)


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
    print_rank_reference(generated)


def print_rank_reference(generated: pd.DataFrame, before: bool = True) -> None:
    """走塁・盗塁・送球のランク点（改修前・今回・実在。参考）。"""
    real, now = real_rank_reference(), rank_statistics(generated)
    rows = []
    for group in RANK_GROUPS:
        labels = [label for label, _low in RANK_BANDS[RANK_ABILITY[group]]]
        lines = [("改修前", list(BEFORE_RANK["band"][group]), BEFORE_RANK["overall"][group])] if before else []
        lines += [("今回", [now["band"][group][x][0] for x in labels], now["overall"][group][0]),
                  ("実在", [real["band"][group][x][0] for x in labels], real["overall"][group][0])]
        for name, values, overall in lines:
            rows.append({"項目": f"{group}（{RANK_ABILITY[group]}）", "": name, **{f"帯{i + 1}": round(float(v), 2) for i, v in enumerate(values)}, "全体": round(float(overall), 2)})
    print("\n[走塁・盗塁・送球のランク点（参考。帯1〜5は 走力 〜49／50〜59／60〜69／70〜79／80〜、肩力 〜54／55〜64／65〜74／75〜79／80〜）]")
    print(pd.DataFrame(rows).to_string(index=False))
    totals = [("改修前", BEFORE_RANK["total"])] if before else []
    totals += [("今回", {k: v[0] for k, v in now["total"].items()}), ("実在", {k: v[0] for k, v in real["total"].items()})]
    print("[ランク点の合計（参考）] " + " / ".join(f"{name} " + "・".join(f"{k} {float(v):+.2f}" for k, v in d.items()) for name, d in totals))


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）野手の走力を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--single-csv", type=Path, default=None, help="個別生成（架空球団用・野手）のサンプルCSV。あれば同じ表を参考として出す")
    parser.add_argument("--build-real", action="store_true", help="実在の走塁・盗塁・送球のランクの集計（data/config/fielder_speed_rank_real.json）を作り直して終わる")
    checklib.add_common_args(parser)
    args = parser.parse_args()
    if args.build_real:
        build_real()
        return

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
        print_rank_reference(single, before=False)
        graded += reference
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    main()
