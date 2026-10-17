#!/usr/bin/env python3
"""
投手の球速の分布の形の、表づくりと判定の共通部分（`投手の球速の形_改修指示.md`）。

使い方:
    python scripts/pitcher_speed_shape.py --build          # 表を作り直し、試作表（data/config の表）との差を出す
    python scripts/pitcher_speed_shape.py --build --write-table   # 作り直した表で data/config/fictional_pitcher_speed_shape.json を上書きする
    python scripts/pitcher_speed_shape.py --build-real     # 判定に使う実在の値（data/config/pitcher_speed_shape_real.json）を書き出す
    python scripts/pitcher_speed_shape.py --report         # 写さない場合（改修前）と写した場合（改修後）と実在の、3km刻み・平均・標準偏差を並べる

- 対象は架空球団用の日本人投手の22歳以上（app.apply_fictional_pitcher_balance）。四捨五入の前の球速を、役割×投げ手
  （先発|右、先発|左、救援|右、救援|左）ごとに、分位の対応表で実在の分布へ写す（順位を保つ。範囲の外は傾き1で延ばす）。
- 表（指示書1-2）: 分位 p（0.002、0.005、0.01〜0.99 を0.01刻み、0.995、0.998 の103点）での from・to。
    from … 写さない状態で球団生成（seed 1〜300）を流して集めた、四捨五入の前の値に −0.5〜0.5 の一様乱数を足したもの
            （app の副乱数 fictional_pitcher_speed_shape_v1 と同じ値）の分位。22歳以上だけ。
    to   … 実在（2024〜2026年版の日本人投手で、22歳以上か年齢が分からない投手）の球速の分位。各値を整数の幅（±0.5）に広げ、
            標準偏差1.0の正規分布で均した分布から作る（実在の人数の揺れを写さないため）。
  **from は生成から作るので、球速より前の処理（役割のずらし・shape_speed・投げ手のずらし・裾、元の能力の生成など）を変えたら作り直す。**
  作り直した表と data/config の表の差が各点で0.3km以内なら、data/config の表のままでよい。
- 判定（指示書2-1。check_pitcher_control.py が shape_checks で「球速の形」の節を足す）: 役割×投げ手の4区分ごとに、
  3km刻みの割合（145〜147、148〜150、151〜153、154〜156。実在±（誤差の2倍、最低±4ポイント））、1km刻みの全変動距離
  （実在の揺れ以下）、先発右の148kmの割合（7%以上）。実在は2024〜2026年版の日本人投手1,126人（全年齢）。
  誤差は異なる選手の数（名前で数える）で出す。実在の揺れは、異なる選手を無作為に半分ずつに分け（200回、種は固定）、
  2つの半分どうしの全変動距離の中央値を2で割った値。
"""
from __future__ import annotations

import argparse
import json
import logging
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

import checklib  # noqa: E402
from checklib import Checks  # noqa: E402

TABLE_PATH = APP_DIR / "data" / "config" / "fictional_pitcher_speed_shape.json"
REAL_PATH = APP_DIR / "data" / "config" / "pitcher_speed_shape_real.json"
REBUILT_PATH = APP_DIR / "reports" / "pitcher_speed_shape" / "fictional_pitcher_speed_shape_rebuilt.json"
GROUPS = (("先発", "右"), ("先発", "左"), ("救援", "右"), ("救援", "左"))
PROBS = [0.002, 0.005] + [round(i / 100, 2) for i in range(1, 100)] + [0.995, 0.998]
YOUNG_MAX_AGE = 21
SMOOTH_SD = 1.0
TABLE_TOLERANCE = 0.3
# 判定（指示書2-1）
BANDS = (("〜144", 0, 144), ("145〜147", 145, 147), ("148〜150", 148, 150), ("151〜153", 151, 153), ("154〜156", 154, 156), ("157〜", 157, 999))
CHECKED_BANDS = ("145〜147", "148〜150", "151〜153", "154〜156")
TOL_BAND_MIN = 4.0
STARTER_RIGHT_148_MIN = 7.0
SPLIT_REPEATS, SPLIT_SEED = 200, 20261017
SECTION = "球速の形（実在は2024〜2026年版の日本人投手。誤差は異なる選手の数。投手の球速の形_改修指示.md）"
# 改修前（球団生成 seed 1〜300、main 5477d4a）の値（指示書0）。表示用
BEFORE = {
    "先発|右": {"〜144": 6.5, "145〜147": 8.7, "148〜150": 18.2, "151〜153": 30.4, "154〜156": 29.1, "157〜": 7.8, "tvd": 0.162},
    "先発|左": {"〜144": 8.1, "145〜147": 24.3, "148〜150": 30.4, "151〜153": 31.6, "154〜156": 5.9, "157〜": 0.0, "tvd": 0.237},
    "救援|右": {"〜144": 0.1, "145〜147": 5.7, "148〜150": 18.6, "151〜153": 21.9, "154〜156": 35.6, "157〜": 18.1, "tvd": 0.252},
    "救援|左": {"〜144": 9.5, "145〜147": 16.1, "148〜150": 25.1, "151〜153": 36.3, "154〜156": 12.8, "157〜": 0.1, "tvd": 0.178},
}


def group_key(role: str, hand: str) -> str:
    return f"{role}|{hand}"


# ---------------------------------------------------------------------------
# 分布の集計（実在・生成で共通）
# ---------------------------------------------------------------------------
def histogram(speeds: Any) -> dict[int, float]:
    """1km刻みの割合（合計1）。"""
    x = pd.Series(np.asarray(speeds, dtype=float)).dropna().round().astype(int)
    return {int(k): float(v) for k, v in x.value_counts(normalize=True).sort_index().items()} if len(x) else {}


def total_variation(a: dict[int, float], b: dict[int, float]) -> float:
    """全変動距離（2つの分布の割合の差の合計の半分）。"""
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in sorted(set(a) | set(b)))


def band_shares(speeds: Any) -> dict[str, float]:
    """3km刻みの割合（%）。"""
    x = pd.Series(np.asarray(speeds, dtype=float)).dropna().round()
    return {label: float(((x >= low) & (x <= high)).mean() * 100) if len(x) else math.nan for label, low, high in BANDS}


def split_half_noise(frame: pd.DataFrame, repeats: int = SPLIT_REPEATS, seed: int = SPLIT_SEED) -> float:
    """実在の揺れ: 異なる選手を無作為に半分ずつに分け、2つの半分どうしの全変動距離の中央値を2で割った値。"""
    rng = np.random.default_rng(seed)
    names = np.array(sorted(frame["name"].unique()))
    values = []
    for _ in range(repeats):
        half = set(rng.permutation(names)[: len(names) // 2].tolist())
        mask = frame["name"].isin(half)
        values.append(total_variation(histogram(frame.loc[mask, "球速"]), histogram(frame.loc[~mask, "球速"])))
    return float(np.median(values) / 2)


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
def real_rows() -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人投手。列は name・role（先発／救援）・hand（右／左）・球速・age。"""
    import pitch_type_speed

    rows, _ = pitch_type_speed.load_real_rows()
    return pd.DataFrame({"name": rows["name"], "role": rows["prole"], "hand": np.where(rows["hand"] == "左投", "左", "右"),
                         "球速": rows["球速"].astype(float), "age": rows["age"]})


def smoothed_quantiles(speeds: Any, probs: list[float] = PROBS, sd: float = SMOOTH_SD) -> list[float]:
    """各値を整数の幅（±0.5）の一様分布に広げ、標準偏差 sd の正規分布で均した分布の分位。"""
    v = np.asarray(speeds, dtype=float)

    def g(z: np.ndarray) -> np.ndarray:  # ∫Φ(z)dz = zΦ(z) + φ(z)
        return z * _phi_cdf(z) + np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)

    def cdf(y: float) -> float:
        return float(np.mean(sd * (g((y - v + 0.5) / sd) - g((y - v - 0.5) / sd))))

    out = []
    for p in probs:
        low, high = float(v.min()) - 10 * sd - 1, float(v.max()) + 10 * sd + 1
        for _ in range(80):
            mid = (low + high) / 2
            low, high = (mid, high) if cdf(mid) < p else (low, mid)
        out.append(round((low + high) / 2, 3))
    return out


def _phi_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def build_real() -> dict[str, Any]:
    """判定に使う実在の値（全年齢）。1km刻みの割合・3km刻みの割合・異なる選手の数・実在の揺れ。"""
    rows = real_rows()
    out: dict[str, Any] = {
        "説明": "実在（2024〜2026年版の日本人投手、全年齢）の球速の分布。1km刻みの割合（合計1）、3km刻みの割合（%）、"
                "異なる選手の数（名前で数える。誤差に使う）、実在の揺れ（異なる選手を半分ずつに分けて200回比べた全変動距離の中央値÷2。"
                f"種 {SPLIT_SEED}）。scripts/pitcher_speed_shape.py --build-real で作る。",
        "人数": int(len(rows)), "異なる選手の数": int(rows["name"].nunique()),
    }
    for role, hand in GROUPS:
        g = rows[(rows["role"] == role) & (rows["hand"] == hand)]
        out[group_key(role, hand)] = {
            "人数": int(len(g)), "異なる選手の数": int(g["name"].nunique()),
            "平均": round(float(g["球速"].mean()), 3), "標準偏差": round(float(g["球速"].std()), 3),
            "1km刻み": {str(k): round(v, 6) for k, v in histogram(g["球速"]).items()},
            "3km刻み": {k: round(v, 3) for k, v in band_shares(g["球速"]).items()},
            "実在の揺れ": round(split_half_noise(g), 4),
        }
    return out


def real_reference() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 生成（表を作る・比べる）
# ---------------------------------------------------------------------------
_MASTER = None


def _init_worker(use_table: bool, trace: bool) -> None:
    logging.disable(logging.WARNING)
    global _MASTER
    import app

    _MASTER = app.load_master_data()
    app.FICTIONAL_PITCHER_SPEED_SHAPE_OVERRIDE = None if use_table else {}
    app.FICTIONAL_PITCHER_SPEED_SHAPE_TRACE = [] if trace else None


def _team(team_seed: int) -> tuple[list[tuple[str, float]], list[dict[str, Any]]]:
    import app

    if app.FICTIONAL_PITCHER_SPEED_SHAPE_TRACE is not None:
        app.FICTIONAL_PITCHER_SPEED_SHAPE_TRACE.clear()
    team = app.generate_team(team_seed, master=_MASTER)
    trace = list(app.FICTIONAL_PITCHER_SPEED_SHAPE_TRACE or [])
    pitchers = []
    for p in team["players"]:
        if p.get("role") != "投手" or p.get("roster_origin") == "foreign_import":
            continue
        pitchers.append({"role": "先発" if p.get("position") == "先発" else "救援",
                         "hand": "左" if str(p.get("batting_throwing", "")).startswith("左投") else "右",
                         "球速": float(app.pitcher_speed_value(p.get("abilities", {})) or math.nan), "age": int(p.get("age") or 0)})
    return trace, pitchers


def collect(teams: int, start: int, workers: int, *, use_table: bool, trace: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """球団生成の (写す前の値の一覧, 日本人投手の一覧)。"""
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(use_table, trace)) as pool:
        results = list(pool.map(_team, range(start, start + teams), chunksize=4))
    traces = pd.DataFrame([row for t, _ in results for row in t], columns=["key", "x"])
    pitchers = pd.DataFrame([row for _, p in results for row in p])
    return traces, pitchers


def build_table(traces: pd.DataFrame, real: pd.DataFrame) -> dict[str, Any]:
    real = real[(real["age"].isna()) | (real["age"] > YOUNG_MAX_AGE)]
    table: dict[str, Any] = {
        "説明": "22歳以上の架空球団用の日本人投手の球速（四捨五入の前）を、役割×投げ手ごとに、生成の分位（from）から実在の均した分位（to）へ"
                "写す表。分位の点は p に並べた。範囲の外は傾き1で延ばす。from は四捨五入前の値に −0.5〜0.5 の一様乱数を足したものの分位。"
                "to は2024〜2026年版の日本人投手（22歳以上か年齢不明）の球速を、整数の幅（±0.5）と標準偏差1.0の正規分布で均した分布の分位。",
        "p": PROBS,
    }
    for role, hand in GROUPS:
        key = group_key(role, hand)
        x = traces.loc[traces["key"] == key, "x"].to_numpy()
        speeds = real.loc[(real["role"] == role) & (real["hand"] == hand), "球速"].to_numpy()
        table[key] = {"from": [round(float(v), 3) for v in np.quantile(x, PROBS)], "to": smoothed_quantiles(speeds)}
    return table


def table_difference(new: dict[str, Any], old: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for role, hand in GROUPS:
        key = group_key(role, hand)
        for part in ("from", "to"):
            diff = np.abs(np.asarray(new[key][part]) - np.asarray(old[key][part]))
            worst = int(diff.argmax())
            rows.append({"区分": key, "": part, "最大の差": round(float(diff.max()), 3), "その分位": PROBS[worst],
                         "0.3km超の点": int((diff > TABLE_TOLERANCE).sum()), "平均の差": round(float(diff.mean()), 3)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 判定（check_pitcher_control.py から使う）
# ---------------------------------------------------------------------------
def share_se(share: float, n: int) -> float:
    p = share / 100
    return math.sqrt(p * (1 - p) / n) * 100 if n > 1 else math.nan


def statistics(role: Any, hand: Any, speed: Any) -> dict[str, dict[str, Any]]:
    role, hand, speed = np.asarray(role), np.asarray(hand), np.asarray(speed, dtype=float)
    real = real_reference()
    out = {}
    for r, h in GROUPS:
        key = group_key(r, h)
        x = speed[(role == r) & (hand == h)]
        hist = histogram(x)
        real_hist = {int(k): v for k, v in real[key]["1km刻み"].items()}
        out[key] = {"bands": band_shares(x), "tvd": total_variation(hist, real_hist), "148": hist.get(148, 0.0) * 100,
                    "mean": float(np.mean(x)) if len(x) else math.nan, "sd": float(np.std(x, ddof=1)) if len(x) > 1 else math.nan, "n": int(len(x))}
    return out


def shape_checks(checks: Checks, role: Any, hand: Any, speed: Any, prefix: str) -> None:
    """指示書2-1 の判定。role は先発／救援、hand は右／左。"""
    real, now = real_reference(), statistics(role, hand, speed)
    for r, h in GROUPS:
        key = group_key(r, h)
        rr, nn = real[key], now[key]
        n = rr["異なる選手の数"]
        for band in CHECKED_BANDS:
            rv = rr["3km刻み"][band]
            tol = max(TOL_BAND_MIN, 2 * share_se(rv, n))
            value = nn["bands"][band]
            low, high = max(0.0, rv - tol), rv + tol
            checks.add(f"{prefix}.speed_shape.band.{key}.{band}", checklib.KIND_REAL, f"{r}{h} {band}の割合", value, low, high,
                       section=SECTION, shown=f"{value:.1f}%", target=f"{low:.1f}〜{high:.1f}%", real=f"{rv:.1f}%（{n}人）")
        noise = rr["実在の揺れ"]
        checks.add(f"{prefix}.speed_shape.tvd.{key}", checklib.KIND_REAL, f"{r}{h} 1km刻みの全変動距離", nn["tvd"], None, noise,
                   section=SECTION, shown=f"{nn['tvd']:.3f}", target=f"{noise:.3f}以下（実在の揺れ）", real=f"揺れ {noise:.3f}")
    value = now["先発|右"]["148"]
    real148 = float(real["先発|右"]["1km刻み"].get("148", 0.0)) * 100
    checks.add(f"{prefix}.speed_shape.starter_right_148", checklib.KIND_DESIGN, "先発右 148kmの割合", value, STARTER_RIGHT_148_MIN, None,
               section=SECTION, shown=f"{value:.1f}%", target=f"{STARTER_RIGHT_148_MIN:.0f}%以上", real=f"{real148:.1f}%")


def shape_real_errors(prefix: str) -> dict[str, float]:
    """実在側の誤差（割合は √(p(1−p)/異なる選手の数)）。全変動距離・148kmの割合は範囲に実在の揺れを入れたので、生成側の誤差だけ。"""
    real = real_reference()
    se = {}
    for r, h in GROUPS:
        key = group_key(r, h)
        for band in CHECKED_BANDS:
            se[f"{prefix}.speed_shape.band.{key}.{band}"] = share_se(real[key]["3km刻み"][band], real[key]["異なる選手の数"])
    return se


def shape_ids(prefix: str) -> list[str]:
    ids = [f"{prefix}.speed_shape.tvd.{group_key(r, h)}" for r, h in GROUPS]
    return ids + [f"{prefix}.speed_shape.starter_right_148"]


# ---------------------------------------------------------------------------
# 比べる表（--report）
# ---------------------------------------------------------------------------
def report_table(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    real = real_reference()
    b = statistics(before["role"], before["hand"], before["球速"])
    a = statistics(after["role"], after["hand"], after["球速"])
    rows = []
    for r, h in GROUPS:
        key = group_key(r, h)
        rr = real[key]
        for label, s in (("改修前", b[key]), ("改修後", a[key])):
            rows.append({"区分": key, "": label, **{band: round(s["bands"][band], 1) for band, *_ in BANDS},
                         "全変動距離": round(s["tvd"], 3), "平均": round(s["mean"], 2), "標準偏差": round(s["sd"], 2), "人数": s["n"]})
        rows.append({"区分": key, "": "実在", **{band: rr["3km刻み"][band] for band, *_ in BANDS},
                     "全変動距離": f"揺れ {rr['実在の揺れ']:.3f}", "平均": rr["平均"], "標準偏差": rr["標準偏差"], "人数": rr["人数"]})
    return pd.DataFrame(rows)


def one_km_table(before: pd.DataFrame, after: pd.DataFrame, key: str = "先発|右") -> pd.DataFrame:
    real = {int(k): v for k, v in real_reference()[key]["1km刻み"].items()}
    r, h = key.split("|")
    hb = histogram(before.loc[(before["role"] == r) & (before["hand"] == h), "球速"])
    ha = histogram(after.loc[(after["role"] == r) & (after["hand"] == h), "球速"])
    return pd.DataFrame([{"球速": k, "改修前": round(hb.get(k, 0) * 100, 1), "改修後": round(ha.get(k, 0) * 100, 1), "実在": round(real.get(k, 0) * 100, 1)}
                         for k in range(140, 163)])


def main() -> None:
    parser = argparse.ArgumentParser(description="投手の球速の分布の形を写す表を作り直します（投手の球速の形_改修指示.md）。")
    parser.add_argument("--build", action="store_true", help="写さない状態で球団生成を流して表を作り直し、data/config の表との差を出す")
    parser.add_argument("--write-table", action="store_true", help="作り直した表で data/config/fictional_pitcher_speed_shape.json を上書きする")
    parser.add_argument("--build-real", action="store_true", help="判定に使う実在の値（data/config/pitcher_speed_shape_real.json）を書き出す")
    parser.add_argument("--report", action="store_true", help="写さない場合・写した場合・実在を並べる")
    parser.add_argument("--teams", type=int, default=300)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()
    if not (args.build or args.build_real or args.report):
        parser.print_help()
        return
    if args.build_real:
        real = build_real()
        REAL_PATH.write_text(json.dumps(real, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"書き出しました: {REAL_PATH}（{real['人数']}人、異なる選手 {real['異なる選手の数']}人）")
        for r, h in GROUPS:
            rr = real[group_key(r, h)]
            print(f"  {r}{h}: {rr['人数']}人（異なる選手 {rr['異なる選手の数']}人） 実在の揺れ {rr['実在の揺れ']:.4f}")
    if args.build:
        traces, _ = collect(args.teams, args.start, args.workers, use_table=False, trace=True)
        table = build_table(traces, real_rows())
        REBUILT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REBUILT_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"書き出しました: {REBUILT_PATH}（写す前の値 {len(traces)}件）")
        if TABLE_PATH.exists():
            diff = table_difference(table, json.loads(TABLE_PATH.read_text(encoding="utf-8")))
            print(f"\n[作り直した表と data/config の表の差（km）。各点で{TABLE_TOLERANCE}km以内なら data/config の表のままでよい]")
            print(diff.to_string(index=False))
        if args.write_table:
            TABLE_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"上書きしました: {TABLE_PATH}")
    if args.report:
        _, before = collect(args.teams, args.start, args.workers, use_table=False, trace=False)
        _, after = collect(args.teams, args.start, args.workers, use_table=True, trace=False)
        print(f"[3km刻みの割合（%）・1km刻みの全変動距離・平均・標準偏差（球団生成 {args.teams}球団、日本人投手）]")
        print(report_table(before, after).to_string(index=False))
        print("\n[先発右の1km刻み（%）]")
        print(one_km_table(before, after).to_string(index=False))


if __name__ == "__main__":
    main()
