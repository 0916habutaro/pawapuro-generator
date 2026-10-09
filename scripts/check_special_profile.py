#!/usr/bin/env python3
"""
架空球団用（日本人）の青特の型（投手の左右・野手の打席とポジション）と緑特の型（投手の役割・野手のポジション）を、
球団生成で判定する（`青特の型_改修指示.md` 2-1、`緑特の型_改修指示.md` 2-1）。

使い方:
    python scripts/check_special_profile.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_special_profile.py --teams 60      # 途中確認用
    python scripts/check_special_profile.py --single-csv reports/checks/samples/fictional_all.csv   # 個別生成の参考表も出す

- 球団生成で作った球団の日本人を、実在（2024〜2026年版の日本人。投手1,126人／野手1,103人）と比べる。
  青特の数は、球団分析と同じ数え方（マスターの kind が red・green・gold 以外。ランク特能・起用法は数えない）で、
  実在の「○○キラー」（球団名の付く特能。架空球団では出せない）は数えない。実在の値は data/config/fictional_special_profile.json の
  「実在」（scripts/build_fictional_special_profile.py が実在のデータから作る）。
- 区分: 投手は投げ手（左・右）、野手は打席（左・右。両打は右打と同じ）とポジション。
- 判定する項目（指示書2-1）: 投手の青特の数（左・右）と左右差、野手の青特の数（全体・左打・右打）と左右差、
  ポジションごとの青特の数、投手の赤特の数、右投手のクロスファイヤー（0人）、
  奪三振・内野安打○・広角打法の、能力の帯 × 投打ごとの保有率。
- 緑特の型の項目（緑特の型_改修指示.md 2-1）: 緑特の数（球団分析と同じ数え方。調子・投球位置・慎重盗塁・フル出場は数えない）、
  緑特の型の対象の特能の、役割（投手は先発・救援）・ポジション（野手）ごとの保有率、速球中心の救援−先発、テンポ○の先発−救援。
  実在の値は data/config/fictional_green_profile.json の「実在」。
- 投手の役割の項目（`投手の役割と特能_改修指示.md` 2-1）: 先発・救援ごとの青特の数（実在は○○キラーを数えない）・赤特の数、
  役割で差の大きい特能（緊急登板○・牽制○・内角攻め・スロースターター・負け運・緩急○・ナチュラルシュート）の役割ごとの保有率、
  奪三振・球速安定の、球速の帯 × 役割ごとの保有率、特能の査定点の先発−救援。実在の値は fictional_special_profile.json の「実在」の「役割」。
- 個別生成（架空球団用・投手と野手 各5000人）は同じ表を参考として出す（合否には使わない）。
- 判定の種類・誤差・合否の付け方は checklib.py。誤差は、生成側は球団、実在側は実在の人数から見積もる（平均の標準誤差、保有率は二項分布）。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import checklib  # noqa: E402
from build_fictional_special_profile import (  # noqa: E402
    GREEN_PROFILE_PATH, GREEN_SPECIALS, LINKED_BANDS, PITCHER_ROLES, POSITIONS, PROFILE_PATH, ROLE_LINKED_BANDS, ROLE_SPECIALS, band_index,
    collect_players, special_points,
)
from checklib import Checks  # noqa: E402

SCRIPT = "check_special_profile"
# 合格の範囲（指示書2-1）
TOL_PITCHER, TOL_PITCHER_DIFF, TOL_FIELDER, TOL_FIELDER_DIFF, TOL_POSITION, TOL_RED, TOL_BAND = 0.25, 0.30, 0.20, 0.25, 0.30, 0.10, 0.08
# 緑特の型（緑特の型_改修指示.md 2-1）: 緑特の数 投手・野手、区分ごとの保有率、速球中心・テンポ○の役割の差
TOL_GREEN = {"投手": 0.05, "野手": 0.10}
TOL_GREEN_RATE, TOL_GREEN_DIFF = 0.06, 0.05
# 役割の差を判定する特能: (特能, 引かれる側, 引く側)
GREEN_ROLE_DIFFS = (("速球中心", "救援", "先発"), ("テンポ○", "先発", "救援"))
# 投手の役割（投手の役割と特能_改修指示.md 2-1）: 青特の数、赤特の数、特能の保有率、連動特能の帯の保有率、特能の査定点の先発−救援
TOL_ROLE_BLUE, TOL_ROLE_RED, TOL_ROLE_RATE, TOL_ROLE_BAND, TOL_ROLE_POINTS = 0.20, 0.12, 0.05, 0.08, 1.5
SECTIONS = {
    "pitcher_blue": "投手の青特の数（実在は2024〜2026年版の日本人。○○キラーを数えない）",
    "pitcher_diff": "投手の青特の左右差（左−右）",
    "pitcher_red": "投手の赤特の数",
    "crossfire": "右投手のクロスファイヤー",
    "fielder_blue": "野手の青特の数（打席）",
    "fielder_diff": "野手の青特の左右差（左打−右打）",
    "position_blue": "ポジションごとの青特の数",
    "linked": "能力と連動する特能の、帯 × 投打ごとの保有率（奪三振＝球速、内野安打○＝走力、広角打法＝ミート）",
    "green_count": "緑特の数（球団分析と同じ数え方。調子・投球位置・慎重盗塁・フル出場は起用法として数えない）",
    "green_rate": "緑特の型の対象の特能の保有率（投手は役割、野手はポジションごと）",
    "green_diff": "緑特の役割の差（速球中心は救援−先発、テンポ○は先発−救援）",
    "role_count": "投手の役割ごとの青特・赤特の数（実在は○○キラーを数えない）",
    "role_rate": "投手の役割で差の大きい特能の、役割ごとの保有率",
    "role_linked": "奪三振・球速安定の、球速の帯 × 役割ごとの保有率",
    "role_points": "投手の特能の査定点の先発−救援",
}
# 改修前（球団生成 seed 1〜300、PR #116 の main 06bb1c7）の値は、そのコミットで同じスクリプトを流して表示用に出す（コードには持たない）。


def real_reference() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["実在"]


def real_green_reference() -> dict:
    return json.loads(GREEN_PROFILE_PATH.read_text(encoding="utf-8"))["実在"]


def green_group_column(role: str) -> str:
    """緑特の型の判定の区分の列（投手は役割、野手はポジション）。"""
    return "prole" if role == "投手" else "position"


def players_frame(rows: list[dict]) -> pd.DataFrame:
    """build_fictional_special_profile.collect_players の結果を、判定用の表にする。"""
    from generator import team_analysis as ta

    frame = pd.DataFrame(rows)
    counts = frame["specials"].map(ta.special_counts)
    frame["n_blue"] = counts.map(lambda c: c["n_blue"]).astype(float)
    frame["n_red"] = counts.map(lambda c: c["n_red"]).astype(float)
    frame["n_green"] = counts.map(lambda c: c["n_green"]).astype(float)
    for name in sorted({name for names in GREEN_SPECIALS.values() for name in names}):
        frame[name] = frame["specials"].map(lambda names, name=name: name in names)
    frame["クロスファイヤー"] = frame["specials"].map(lambda names: "クロスファイヤー" in names)
    for name in sorted({name for _role, name, _key, _limits in LINKED_BANDS} | {name for name, *_ in ROLE_LINKED_BANDS} | set(ROLE_SPECIALS)):
        frame[name] = frame["specials"].map(lambda names, name=name: name in names)
    frame["special_points"] = frame["specials"].map(special_points).astype(float)
    frame["team_key"] = frame["team"] if "team" in frame.columns else "single"
    return frame.drop(columns=["specials"])


def single_frame(path: Path) -> pd.DataFrame:
    """個別生成のサンプルCSV（generate_fictional_balance_sample.py。投手と野手を1つにまとめたもの）の日本人。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df[(df["category"] == "架空球団用") & (df["roster_origin"] == "domestic")].reset_index(drop=True)
    rows = []
    for record in df.to_dict("records"):
        role = record["role"]
        text = str(record.get("batting_throwing") or "")
        abilities = json.loads(record["abilities_json"])
        value = lambda key: _number(abilities.get(key))  # noqa: E731
        rows.append({
            "team": "single", "role": role, "hand": "左" if (text.startswith("左投") if role == "投手" else text[2:3] == "左") else "右",
            "position": "投手" if role == "投手" else str(record["position"]),
            "prole": ("先発" if record["position"] == "先発" else "救援") if role == "投手" else None,
            "specials": json.loads(record["special_abilities_json"]), "球速": value("球速"), "走力": value("走力"), "ミート": value("ミート"),
        })
    return players_frame(rows)


def _number(item) -> float:
    import re

    if isinstance(item, dict):
        item = item.get("value")
    if item is None:
        return math.nan
    found = re.findall(r"\d+(?:\.\d+)?", str(item))
    return float(found[0]) if found else math.nan


def rate_se(rate: float, n: int) -> float:
    return math.sqrt(max(rate * (1.0 - rate), 1e-4) / n) if n else math.nan


def evaluate(frame: pd.DataFrame, prefix: str = SCRIPT, info: bool = False) -> Checks:
    """frame: 日本人の選手（列 role, hand, position, n_blue, n_red, クロスファイヤー, 球速, 走力, ミート, 奪三振, 内野安打○, 広角打法）。
    info=True ならすべて参考（個別生成）。"""
    real = real_reference()
    pitchers, fielders = frame[frame["role"] == "投手"], frame[frame["role"] == "野手"]
    checks = Checks(prefix)
    kind = checklib.KIND_INFO if info else checklib.KIND_REAL

    def add(section: str, key: str, label: str, value: float, low: float, high: float, real_text: str, fmt: str = "{:.2f}", kind_: str | None = None) -> None:
        checks.add(f"{prefix}.{section}.{key}", kind_ or kind, label, value, low, high, section=SECTIONS[section],
                   shown=fmt.format(value), target=f"{fmt.format(low)}〜{fmt.format(high)}", real=real_text)

    def around(section: str, key: str, label: str, value: float, center: float, tol: float) -> None:
        add(section, key, label, value, center - tol, center + tol, f"{center:.2f}")

    mean = lambda d: d["n_blue"].mean()  # noqa: E731
    for hand in ("左", "右"):
        around("pitcher_blue", hand, f"投手 {hand}投 青特の数", mean(pitchers[pitchers["hand"] == hand]), real["投手"][hand]["平均"], TOL_PITCHER)
    diff = mean(pitchers[pitchers["hand"] == "左"]) - mean(pitchers[pitchers["hand"] == "右"])
    around("pitcher_diff", "diff", "投手 青特の左右差（左−右）", diff, real["投手"]["左"]["平均"] - real["投手"]["右"]["平均"], TOL_PITCHER_DIFF)
    around("pitcher_red", "red", "投手 赤特の数", pitchers["n_red"].mean(), real["投手_赤"]["平均"], TOL_RED)
    # 右投手のクロスファイヤーは必ず外す（実在の日本人投手には1人もいない）。設計の判定（範囲は 0）。
    n_cross = float(((pitchers["hand"] == "右") & pitchers["クロスファイヤー"]).sum())
    checks.add(f"{prefix}.crossfire.right", checklib.KIND_INFO if info else checklib.KIND_DESIGN, "右投手のクロスファイヤー（人数）", n_cross, 0.0, 0.0,
               section=SECTIONS["crossfire"], shown=f"{int(n_cross)}", target="0人（仕様）", real="0人")
    around("fielder_blue", "all", "野手 青特の数 全体", mean(fielders), real["野手"]["全体"]["平均"], TOL_FIELDER)
    for hand in ("左", "右"):
        around("fielder_blue", hand, f"野手 {hand}打 青特の数", mean(fielders[fielders["hand"] == hand]), real["野手"][hand]["平均"], TOL_FIELDER)
    diff = mean(fielders[fielders["hand"] == "左"]) - mean(fielders[fielders["hand"] == "右"])
    around("fielder_diff", "diff", "野手 青特の左右差（左打−右打）", diff, real["野手"]["左"]["平均"] - real["野手"]["右"]["平均"], TOL_FIELDER_DIFF)
    for position in POSITIONS:
        around("position_blue", position, f"{position} 青特の数", mean(fielders[fielders["position"] == position]), real["ポジション"][position]["平均"], TOL_POSITION)
    for role, name, key, limits in LINKED_BANDS:
        rows = pitchers if role == "投手" else fielders
        for hand in ("右", "左"):
            for band in range(len(limits) + 1):
                reference = real["帯"][name][f"{hand}|{band}"]["保有率"]
                if reference is None:
                    continue
                d = rows[(rows["hand"] == hand) & rows[key].map(lambda v: not math.isnan(v) and band_index(v, limits) == band)]
                if d.empty:
                    continue
                label = f"{name} {hand}{'投' if role == '投手' else '打'} {key}{band_text(limits, band)}"
                add("linked", f"{name}_{hand}_{band}", label, float(d[name].mean()), max(0.0, reference - TOL_BAND), min(1.0, reference + TOL_BAND), f"{reference:.3f}", "{:.3f}")
    green = real_green_reference()
    for role, rows in (("投手", pitchers), ("野手", fielders)):
        around("green_count", role, f"{role} 緑特の数", float(rows["n_green"].mean()), green["緑特の数"][role]["平均"], TOL_GREEN[role])
    for role, rows in (("投手", pitchers), ("野手", fielders)):
        column, groups = green_group_column(role), (PITCHER_ROLES if role == "投手" else POSITIONS)
        for name in GREEN_SPECIALS[role]:
            for group in groups:
                reference = green["保有率"][role][name][group]["保有率"]
                value = float(rows[rows[column] == group][name].mean())
                add("green_rate", f"{name}_{group}", f"{name} {group}", value, max(0.0, reference - TOL_GREEN_RATE), min(1.0, reference + TOL_GREEN_RATE), f"{reference:.3f}", "{:.3f}")
    for name, plus, minus in GREEN_ROLE_DIFFS:
        rate = lambda group, name=name: float(pitchers[pitchers["prole"] == group][name].mean())  # noqa: E731
        reference = green["保有率"]["投手"][name][plus]["保有率"] - green["保有率"]["投手"][name][minus]["保有率"]
        add("green_diff", name, f"{name} {plus}−{minus}", rate(plus) - rate(minus), reference - TOL_GREEN_DIFF, reference + TOL_GREEN_DIFF, f"{reference:.3f}", "{:.3f}")
    evaluate_roles(pitchers, real["役割"], add, around)
    return checks


def evaluate_roles(pitchers: pd.DataFrame, real: dict, add, around) -> None:
    """投手の役割（先発・救援）ごとの項目（投手の役割と特能_改修指示.md 2-1）。real は「実在」の「役割」。"""
    by_role = {prole: pitchers[pitchers["prole"] == prole] for prole in PITCHER_ROLES}
    for prole, rows in by_role.items():
        around("role_count", f"blue_{prole}", f"投手 {prole} 青特の数", float(rows["n_blue"].mean()), real["青特の数"][prole]["平均"], TOL_ROLE_BLUE)
        around("role_count", f"red_{prole}", f"投手 {prole} 赤特の数", float(rows["n_red"].mean()), real["赤特の数"][prole]["平均"], TOL_ROLE_RED)
    for name in ROLE_SPECIALS:
        for prole, rows in by_role.items():
            reference = real["保有率"][name][prole]["保有率"]
            add("role_rate", f"{name}_{prole}", f"{name} {prole}", float(rows[name].mean()),
                max(0.0, reference - TOL_ROLE_RATE), min(1.0, reference + TOL_ROLE_RATE), f"{reference:.3f}", "{:.3f}")
    for name, key, limits in ROLE_LINKED_BANDS:
        for prole, rows in by_role.items():
            for band in range(len(limits) + 1):
                reference = real["帯"][name][f"{prole}|{band}"]["保有率"]
                d = rows[rows[key].map(lambda v: not math.isnan(v) and band_index(v, limits) == band)]
                if reference is None or d.empty:
                    continue
                add("role_linked", f"{name}_{prole}_{band}", f"{name} {prole} {key}{band_text(limits, band)}", float(d[name].mean()),
                    max(0.0, reference - TOL_ROLE_BAND), min(1.0, reference + TOL_ROLE_BAND), f"{reference:.3f}", "{:.3f}")
    points = {prole: float(rows["special_points"].mean()) for prole, rows in by_role.items()}
    reference = real["特能の査定点"]["先発"]["平均"] - real["特能の査定点"]["救援"]["平均"]
    around("role_points", "diff", "特能の査定点 先発−救援", points["先発"] - points["救援"], reference, TOL_ROLE_POINTS)


def band_text(limits: tuple[int, ...], band: int) -> str:
    if band == 0:
        return f"〜{limits[0]}"
    if band == len(limits):
        return f"{limits[-1] + 1}〜"
    return f"{limits[band - 1] + 1}〜{limits[band]}"


def real_errors(prefix: str = SCRIPT) -> dict[str, float]:
    """実在側の誤差（平均は標準偏差÷√人数、保有率は二項分布）。ブートストラップできる実在の特能のデータが手元に無いため解析的に見積もる。"""
    real = real_reference()
    se: dict[str, float] = {}

    def mean_se(entry: dict) -> float:
        return entry["標準偏差"] / math.sqrt(entry["人数"])

    for hand in ("左", "右"):
        se[f"{prefix}.pitcher_blue.{hand}"] = mean_se(real["投手"][hand])
        se[f"{prefix}.fielder_blue.{hand}"] = mean_se(real["野手"][hand])
    se[f"{prefix}.pitcher_diff.diff"] = math.hypot(se[f"{prefix}.pitcher_blue.左"], se[f"{prefix}.pitcher_blue.右"])
    se[f"{prefix}.fielder_diff.diff"] = math.hypot(se[f"{prefix}.fielder_blue.左"], se[f"{prefix}.fielder_blue.右"])
    se[f"{prefix}.pitcher_red.red"] = mean_se(real["投手_赤"])
    se[f"{prefix}.fielder_blue.all"] = mean_se(real["野手"]["全体"])
    for position in POSITIONS:
        se[f"{prefix}.position_blue.{position}"] = mean_se(real["ポジション"][position])
    for name, bands in real["帯"].items():
        for key, entry in bands.items():
            if entry["保有率"] is not None:
                hand, band = key.split("|")
                se[f"{prefix}.linked.{name}_{hand}_{band}"] = rate_se(entry["保有率"], entry["人数"])
    green = real_green_reference()
    for role, entry in green["緑特の数"].items():
        se[f"{prefix}.green_count.{role}"] = mean_se(entry)
    for role, specials in green["保有率"].items():
        for name, groups in specials.items():
            for group, entry in groups.items():
                if group != "全体":
                    se[f"{prefix}.green_rate.{name}_{group}"] = rate_se(entry["保有率"], entry["人数"])
    for name, plus, minus in GREEN_ROLE_DIFFS:
        se[f"{prefix}.green_diff.{name}"] = math.hypot(se[f"{prefix}.green_rate.{name}_{plus}"], se[f"{prefix}.green_rate.{name}_{minus}"])
    roles = real["役割"]
    for prole in PITCHER_ROLES:
        se[f"{prefix}.role_count.blue_{prole}"] = mean_se(roles["青特の数"][prole])
        se[f"{prefix}.role_count.red_{prole}"] = mean_se(roles["赤特の数"][prole])
        for name in ROLE_SPECIALS:
            entry = roles["保有率"][name][prole]
            se[f"{prefix}.role_rate.{name}_{prole}"] = rate_se(entry["保有率"], entry["人数"])
    for name, bands in roles["帯"].items():
        for key, entry in bands.items():
            if entry["保有率"] is not None:
                prole, band = key.split("|")
                se[f"{prefix}.role_linked.{name}_{prole}_{band}"] = rate_se(entry["保有率"], entry["人数"])
    se[f"{prefix}.role_points.diff"] = math.hypot(mean_se(roles["特能の査定点"]["先発"]), mean_se(roles["特能の査定点"]["救援"]))
    return se


def grade_all(frame: pd.DataFrame, boot: int, quick: bool = False) -> list[checklib.Check]:
    """球団を単位に生成側の誤差を求め、実在側の誤差は人数から見積もって、合否を付ける。"""
    checks = evaluate(frame)
    se_gen = checklib.bootstrap_se(evaluate, frame, lambda f, rng: checklib.resample_frame(f, rng, "team_key"), n=boot) if boot else {}
    return checklib.grade(checks, se_gen=se_gen, se_real=real_errors() if boot else {}, all_info=quick)


def print_reference(frame: pd.DataFrame) -> None:
    real = real_reference()
    rows = []
    for position in POSITIONS:
        d = frame[(frame["role"] == "野手") & (frame["position"] == position)]
        row = {"ポジション": position, "人数": len(d), "青特の数": round(d["n_blue"].mean(), 2), "実在": real["ポジション"][position]["平均"]}
        for hand in ("左", "右"):
            row[f"{hand}打"] = round(d[d["hand"] == hand]["n_blue"].mean(), 2)
        rows.append(row)
    print("\n[ポジションごとの青特の数（参考）]")
    print(pd.DataFrame(rows).to_string(index=False))
    ages = frame.assign(age=pd.to_numeric(frame.get("age"), errors="coerce")) if "age" in frame.columns else None
    if ages is not None and ages["age"].notna().any():
        bands = pd.cut(ages["age"], [0, 21, 25, 29, 33, 99], labels=["〜21", "22〜25", "26〜29", "30〜33", "34〜"])
        print("\n[年齢帯ごとの青特の数（参考。実在 投手 1.83／2.39／3.33／3.71／4.11（22〜25は2.39）、野手 1.09／1.85／2.94／3.28／4.36）]")
        print(ages.groupby(["role", bands], observed=True)["n_blue"].mean().round(2).unstack().to_string())
        print("\n[年齢帯ごとの緑特の数（参考。実在 投手 0.17／0.16／0.32／0.36／0.74、野手 0.57／0.95／1.29／1.80／1.69）]")
        print(ages.groupby(["role", bands], observed=True)["n_green"].mean().round(2).unstack().to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）の青特の型を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--single-csv", type=Path, default=None, help="個別生成（架空球団用・投手と野手）のサンプルCSV。あれば同じ表を参考として出す")
    checklib.add_common_args(parser)
    args = parser.parse_args()

    rows = collect_players(args.teams, args.start, args.workers)
    frame = players_frame(rows)
    title = f"球団生成 {args.teams}球団（seed {args.start}〜{args.start + args.teams - 1}） 日本人 投手{(frame['role'] == '投手').sum()}人／野手{(frame['role'] == '野手').sum()}人"
    graded = grade_all(frame, args.boot, args.quick)
    checklib.print_checks(graded, title)
    print_reference(frame)
    if args.single_csv is not None and args.single_csv.exists():
        single = single_frame(args.single_csv)
        reference = list(checklib.grade(evaluate(single, f"{SCRIPT}.single", info=True), all_info=True))
        checklib.print_checks(reference, f"個別生成（架空球団用・日本人 投手{(single['role'] == '投手').sum()}人／野手{(single['role'] == '野手').sum()}人。参考）")
        graded += reference
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    main()
