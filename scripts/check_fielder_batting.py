#!/usr/bin/env python3
"""
架空球団用（日本人）野手の打席ごとの能力（ミートの左右差ほか）を、球団生成で判定する（`野手の打席の型_改修指示.md`）。

使い方:
    python scripts/check_fielder_batting.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_fielder_batting.py --teams 60      # 途中確認用
    python scripts/check_fielder_batting.py --single-csv reports/checks/samples/fictional_fielders.csv   # 個別生成の参考表も出す
    python scripts/check_fielder_batting.py --build-real    # 実在のランク特能の集計（data/config/fielder_ranked_real.json）を作り直す

- 球団生成で作った球団の日本人野手を、実在（2024〜2026年版の日本人野手1,103人）と比べる。
- 判定する項目（指示書2-1）: ミート・パワー・守備力・肩力・捕球の右打・左打それぞれの平均と左−右、ミートの全体の平均、
  ミートの左打の10%・中央・90%、弾道の左−右、21歳以下のミートの左−右。走力は check_fielder_speed.py が受け持つ。
- ランク特能（`野手のランク特能_改修指示.md` 2-1）: 対左投手のランクの割合（A〜G、実在±4ポイント）とランク点（実在±0.4）、
  ランク点の合計（実在±0.6）を、左打・右打それぞれで判定する。ランク点は査定のランク点（D=0。generator/rating.py の
  ranked_points と同じ表）。ランク特能を持たない項目は D として数える。
  実在の値は data/config/fielder_ranked_real.json（--build-real で、実在の元データ data/raw/ から作る）。実在側の誤差は、
  平均は 標準偏差/√人数、割合は √(p(1−p)/人数) で見積もる。捕手のキャッチャーは check_fielder_position.py が受け持つ。
- 両打は人数が少ない（実在14人）ので判定しない。
- 個別生成（架空球団用・野手）は同じ表を参考として出す（合否には使わない）。
- 判定の種類・誤差・合否の付け方は checklib.py。誤差は、生成側は球団、実在側は実在の野手を再抽出して見積もる。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
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
# ランク特能（野手のランク特能_改修指示.md 2-1）
REAL_RANK_PATH = APP_DIR / "data" / "config" / "fielder_ranked_real.json"
REAL_RANK_SEASONS = (2024, 2025, 2026)
LETTERS = ("A", "B", "C", "D", "E", "F", "G")
RANK_GROUPS = ("対左投手", "キャッチャー")
TOL_RANK_SHARE, TOL_RANK_POINTS, TOL_RANK_TOTAL = 4.0, 0.4, 0.6
# 改修前（球団生成 seed 1〜300、PR #122 をマージした main 1e6eda4）の値。表示用
BEFORE_RANK_LEFT = {
    "左": {"割合": (0.2, 6.6, 18.3, 47.9, 20.5, 6.2, 0.2), "ランク点": -0.05, "合計": 0.59},
    "右": {"割合": (0.1, 6.3, 17.6, 47.4, 21.9, 6.5, 0.2), "ランク点": -0.20, "合計": -0.36},
}
SECTIONS = {
    "bats": "打席ごとの平均（実在は2024〜2026年版の日本人野手）",
    "gap": "左−右（左打の平均 − 右打の平均）",
    "contact": "ミートの分布",
    "young": "21歳以下",
    "rank_left": "対左投手のランクの割合（%。実在は2024〜2026年版の日本人野手。±4ポイント）",
    "rank_points": "対左投手のランク点・ランク点の合計（D=0。対左投手は実在±0.4、合計は実在±0.6）",
}


def mean_by(frame: pd.DataFrame, key: str, bats: str) -> float:
    return float(frame.loc[frame["bats"] == bats, key].mean())


# ---------------------------------------------------------------------------
# ランク特能（対左投手・キャッチャー）の列。生成・実在で同じ数え方をする
# ---------------------------------------------------------------------------
def rank_point_table() -> dict[str, dict[str, int]]:
    """ランク特能ごとの、ランクの文字 → 査定のランク点（野手）。"""
    t = load_table()
    out = {}
    for group in RANK_GROUPS:
        table = t["rank_table_major"] if group in t["ranked_major"]["野手"] else t["rank_table_minor"]
        out[group] = {letter: int(table.get(letter, 0)) for letter in LETTERS}
    return out


def rank_columns(ranked: dict[str, str]) -> dict[str, Any]:
    """1人分のランク特能の列。ranked は {項目: ランク特能の名前（末尾がランクの文字）}。持たない項目は D。"""
    points = rank_point_table()
    row: dict[str, Any] = {"rank_points": float(ranked_points(ranked, "野手"))}
    for group in RANK_GROUPS:
        letter = str(ranked.get(group) or "D")[-1:]
        letter = letter if letter in LETTERS else "D"
        row[f"rk_{group}"] = letter
        row[f"pt_{group}"] = float(points[group][letter])
    return row


def _stat(x: pd.Series) -> list[float]:
    x = pd.Series(x, dtype=float).dropna()
    return [round(float(x.mean()), 4), round(float(x.std()), 4), int(len(x))]


def _shares(letters: pd.Series) -> dict[str, float]:
    return {letter: round(float((letters == letter).mean() * 100), 2) for letter in LETTERS}


def load_real_rank_rows() -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人野手。元データ（data/raw/ の zip と 2026年版のフォルダ）から読む。"""
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
                rows.append({"season": season, "bats": bats, "position": str(row.get("main_position") or ""), **rank_columns(ranked)})
    return pd.DataFrame(rows)


def real_rank_statistics(rows: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for bats in ("右", "左"):
        r = rows[rows["bats"] == bats]
        out[f"{bats}打"] = {"人数": int(len(r)), "対左投手_ランク": _shares(r["rk_対左投手"]), "対左投手": _stat(r["pt_対左投手"]), "rank_points": _stat(r["rank_points"])}
    catchers = rows[rows["position"] == "捕手"]
    out["捕手"] = {"人数": int(len(catchers)), "キャッチャー_ランク": _shares(catchers["rk_キャッチャー"]), "キャッチャー": _stat(catchers["pt_キャッチャー"])}
    out["捕手_年版"] = {
        str(season): {"人数": int((catchers["season"] == season).sum()), "キャッチャー_ランク": _shares(catchers.loc[catchers["season"] == season, "rk_キャッチャー"])}
        for season in REAL_RANK_SEASONS
    }
    return out


def build_real() -> None:
    rows = load_real_rank_rows()
    data = {
        "作り方": "scripts/check_fielder_batting.py --build-real。実在（2024〜2026年版）の日本人野手（外国人を除く）。打席は投打の3文字目、"
                 "捕手はメインのポジション。ランク点は査定のランク点（D=0、持たない項目はD）。割合は%。[平均, 標準偏差, 人数]",
        "実在": real_rank_statistics(rows),
    }
    REAL_RANK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_RANK_PATH}（{len(rows)}人）")


def real_rank_reference() -> dict[str, Any]:
    return json.loads(REAL_RANK_PATH.read_text(encoding="utf-8"))["実在"]


def share_se(share: float, n: int) -> float:
    """割合（%）の誤差（ポイント）。"""
    p = share / 100
    return math.sqrt(p * (1 - p) / n) * 100 if n > 1 else math.nan


def mean_se(stat: list[float]) -> float:
    return stat[1] / math.sqrt(stat[2]) if stat[2] > 1 else math.nan


def real_rank_errors(prefix: str = SCRIPT) -> dict[str, float]:
    """対左投手の判定の実在側の誤差。"""
    real = real_rank_reference()
    se: dict[str, float] = {}
    for bats in ("右", "左"):
        item = real[f"{bats}打"]
        for letter in LETTERS:
            se[f"{prefix}.rank_left.{bats}_{letter}"] = share_se(item["対左投手_ランク"][letter], item["人数"])
        se[f"{prefix}.rank_points.対左投手_{bats}"] = mean_se(item["対左投手"])
        se[f"{prefix}.rank_points.合計_{bats}"] = mean_se(item["rank_points"])
    return se


def rank_left_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """対左投手のランクの割合・ランク点と、ランク点の合計（左打・右打）。frame は列 bats・rk_対左投手・pt_対左投手・rank_points を持つ。"""
    real = real_rank_reference()
    for bats in ("右", "左"):
        part = frame[frame["bats"] == bats]
        item = real[f"{bats}打"]
        for letter in LETTERS:
            value, r = float((part["rk_対左投手"] == letter).mean() * 100), item["対左投手_ランク"][letter]
            low, high = r - TOL_RANK_SHARE, r + TOL_RANK_SHARE
            checks.add(f"{prefix}.rank_left.{bats}_{letter}", kind, f"対左投手 {bats}打 {letter}の割合", value, low, high, section=SECTIONS["rank_left"],
                       shown=f"{value:.1f}", target=f"{low:.1f}〜{high:.1f}", real=f"{r:.1f}")
        for key, column, real_value, tol, label in (
            (f"対左投手_{bats}", "pt_対左投手", item["対左投手"][0], TOL_RANK_POINTS, f"対左投手のランク点 {bats}打"),
            (f"合計_{bats}", "rank_points", item["rank_points"][0], TOL_RANK_TOTAL, f"ランク点の合計 {bats}打"),
        ):
            value = float(part[column].mean())
            low, high = real_value - tol, real_value + tol
            checks.add(f"{prefix}.rank_points.{key}", kind, label, value, low, high, section=SECTIONS["rank_points"],
                       shown=f"{value:+.2f}", target=f"{low:+.2f}〜{high:+.2f}", real=f"{real_value:+.2f}")


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
    if "rk_対左投手" in frame.columns:  # 実在の選手単位データ（local_data）にはランク特能の列が無い。実在の値は fielder_ranked_real.json
        rank_left_checks(checks, main, prefix, kind)
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
    if boot:
        se_real.update(real_rank_errors())
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


# ---------------------------------------------------------------------------
# 生成（球団生成）。球団分析の表にランク特能の列を足す
# ---------------------------------------------------------------------------
RANK_COLUMNS = ("rank_points", *(f"{kind}_{group}" for group in RANK_GROUPS for kind in ("rk", "pt")))


def _team(team_seed: int) -> pd.DataFrame:
    import app

    team = app.generate_team(team_seed, master=check_pitcher_control._MASTER)
    frame = team_analysis.players_frame(team["players"], f"gen:{team_seed}", str(team_seed)).drop(columns=["rank_points"])
    ranks = pd.DataFrame([rank_columns((p.get("abilities") or {}).get("ranked_specials") or {}) for p in team["players"]])
    return pd.concat([frame.reset_index(drop=True), ranks], axis=1)


def collect(teams: int, start: int, workers: int) -> pd.DataFrame:
    """球団生成の全選手（check_pitcher_control.collect と同じ表に、ランク特能の列 rk_・pt_ を足したもの）。"""
    with ProcessPoolExecutor(max_workers=workers, initializer=check_pitcher_control._init_worker) as pool:
        frames = list(pool.map(_team, range(start, start + teams), chunksize=4))
    return pd.concat(frames, ignore_index=True)


def team_fielders(frame: pd.DataFrame) -> pd.DataFrame:
    fielders = frame[(frame["role"] == "野手") & (~frame["is_foreign"])]
    return fielders[["team_key", "position", "bats", "age", "弾道", *ABILITIES, *RANK_COLUMNS]].reset_index(drop=True)


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
    ranks = pd.DataFrame([rank_columns(abilities.get("ranked_specials") or {}) for abilities in parsed])
    frame = pd.concat([frame, ranks], axis=1)
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
    print_rank_reference(generated)


def print_rank_reference(generated: pd.DataFrame, before: bool = True) -> None:
    """対左投手のランクの割合・ランク点（改修前・今回・実在。参考）。"""
    real = real_rank_reference()
    rows = []
    for bats in ("左", "右"):
        part = generated[generated["bats"] == bats]
        item = real[f"{bats}打"]
        labels = [("改修前", BEFORE_RANK_LEFT[bats]["割合"], BEFORE_RANK_LEFT[bats]["ランク点"], BEFORE_RANK_LEFT[bats]["合計"])] if before else []
        labels += [("今回", [(part["rk_対左投手"] == x).mean() * 100 for x in LETTERS], part["pt_対左投手"].mean(), part["rank_points"].mean()),
                   ("実在", [item["対左投手_ランク"][x] for x in LETTERS], item["対左投手"][0], item["rank_points"][0])]
        for label, shares, points, total in labels:
            rows.append({"打席": f"{bats}打", "": label, **{x: round(float(v), 1) for x, v in zip(LETTERS, shares)},
                         "対左投手のランク点": round(float(points), 2), "ランク点の合計": round(float(total), 2)})
    print("\n[対左投手のランクの割合（%）・ランク点（参考）]")
    print(pd.DataFrame(rows).to_string(index=False))
    both = generated[generated["bats"] == "両"]
    if len(both):
        print(f"[両打の対左投手（今の重みのまま。参考）] {len(both)}人。ランク点 {both['pt_対左投手'].mean():+.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）野手の打席ごとの能力を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--single-csv", type=Path, default=None, help="個別生成（架空球団用・野手）のサンプルCSV。あれば同じ表を参考として出す")
    parser.add_argument("--build-real", action="store_true", help="実在のランク特能の集計（data/config/fielder_ranked_real.json）を作り直して終わる")
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
