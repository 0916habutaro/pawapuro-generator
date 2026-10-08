#!/usr/bin/env python3
"""
架空球団用（日本人）投手のランク特能の役割の差と、救援の球種数を、球団生成で判定する（`投手のランク特能と救援の球種数_改修指示.md` 2-1）。

使い方:
    python scripts/check_pitcher_rank_pitches.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_pitcher_rank_pitches.py --teams 60      # 途中確認用
    python scripts/check_pitcher_rank_pitches.py --single-csv reports/checks/samples/fictional_pitchers.csv   # 個別生成の参考表も出す
    python scripts/check_pitcher_rank_pitches.py --build-real    # 実在の集計（data/config/pitcher_rank_pitches_real.json）を作り直す

- 球団生成で作った球団の日本人投手を、実在（2024〜2026年版の日本人投手）と比べる。役割は position が「先発」なら先発、
  「中継ぎ」「抑え」は救援（実在は起用の最初の文字が「先」なら先発。球団分析と同じ）。
- ランク点は査定のランク点（D=0。generator/rating.py の ranked_points と同じ表）。ランク特能を持たない項目は D として数える。
- 変化球数・総変化量は、第一球種の変化球だけを数える（ストレート系第二球種・第二球種は数えない。球団分析と同じ）。
- 判定する項目（指示書2-1）:
    ランク点の合計（先発・救援）            実在（2024〜2026）と実在（2026年版）の間 ±0.4
    ノビ・回復・対左打者のランク点（先発・救援） 実在±0.3
    救援の変化球数の平均                    実在±0.05
    救援の1球種の割合                       2〜6%
    救援の変化球数（球速の帯ごと）           実在±0.10
    救援の総変化量の平均                    実在±0.15
- 実在の値は data/config/pitcher_rank_pitches_real.json（--build-real で、実在の元データ data/raw/ から作る）。
  実在側の誤差は、平均は 標準偏差/√人数、割合は √(p(1−p)/人数) で見積もる。生成側の誤差は球団を単位に再抽出して求める。
- 個別生成（架空球団用・日本人投手）は同じ表を参考として出す（合否には使わない）。
- 判定の種類・誤差・合否の付け方は checklib.py（判定の整理_改修指示.md）。
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

import logging  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import checklib  # noqa: E402
from checklib import Checks  # noqa: E402
from generator import team_analysis as ta  # noqa: E402
from generator.rating import load_table, ranked_points  # noqa: E402

SCRIPT = "check_pitcher_rank_pitches"
REAL_PATH = APP_DIR / "data" / "config" / "pitcher_rank_pitches_real.json"
ROLES = ("先発", "救援")
RANK_GROUPS = ("ノビ", "回復", "対左打者")
LETTERS = ("A", "B", "C", "D", "E", "F", "G")
REAL_ALL, REAL_2026 = "2024〜2026", "2026"
REAL_SEASONS = {REAL_ALL: (2024, 2025, 2026), REAL_2026: (2026,)}
# 救援の球速の帯（app.py の FICTIONAL_RELIEVER_SPEED_BANDS と同じ区切り）
SPEED_BANDS = (("〜147", 0, 147), ("148〜151", 148, 151), ("152〜155", 152, 155), ("156〜", 156, 999))
# 合格の範囲（指示書2-1）
TOL_RANK_TOTAL = 0.4
TOL_RANK_GROUP = 0.3
TOL_PITCH_COUNT = 0.05
ONE_PITCH_RANGE = (0.02, 0.06)
TOL_PITCH_BAND = 0.10
TOL_MOVEMENT = 0.15
SECTIONS = {
    "rank_total": "ランク点の合計（D=0。実在は2024〜2026年版と2026年版の間±0.4）",
    "rank_group": "ノビ・回復・対左打者のランク点（実在は2024〜2026年版の日本人。±0.3）",
    "reliever_pitches": "救援の変化球数・総変化量（第一球種の変化球。実在は2024〜2026年版の日本人）",
    "reliever_band": "救援の変化球数（球速の帯ごと。実在±0.10）",
    "reference": "参考（判定しない）",
}


def band_of(speed: float) -> str | None:
    if speed is None or (isinstance(speed, float) and math.isnan(speed)):
        return None
    return next(label for label, low, high in SPEED_BANDS if low <= speed <= high)


def rank_point_table() -> dict[str, dict[str, int]]:
    """ランク特能ごとの、ランクの文字 → 査定のランク点（投手）。"""
    t = load_table()
    out = {}
    for group in RANK_GROUPS:
        table = t["rank_table_major"] if group in t["ranked_major"]["投手"] else t["rank_table_minor"]
        out[group] = {letter: int(table.get(letter, 0)) for letter in LETTERS}
    return out


def pitcher_row(role: str, throws: str | None, speed: float, ranked: dict[str, str], balls: list[Any], *, real: bool) -> dict[str, Any]:
    """1人分の行。ranked は {項目: ランク特能の名前（末尾がランクの文字）}。"""
    points = rank_point_table()
    primary = ta._primary_breaking(balls, real=real)
    row: dict[str, Any] = {
        "prole": role, "throws": "左" if throws == "左" else "右", "球速": speed,
        "変化球数": float(len(primary)), "総変化量": float(sum(ta._movement(ball) for ball in primary)),
        "rank_points": float(ranked_points(ranked, "投手")),
    }
    for group in RANK_GROUPS:
        letter = str(ranked.get(group) or "D")[-1:]
        row[f"rk_{group}"] = letter if letter in LETTERS else "D"
        row[f"pt_{group}"] = float(points[group].get(row[f"rk_{group}"], 0))
    return row


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
def load_real_rows() -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人投手。元データ（data/raw/ の zip と 2026年版のフォルダ）から読む。"""
    import build_real_team_reference as ref
    from generator import real_data

    foreign_keys = ref.foreign_list_keys(ref.DEFAULT_FOREIGN_LIST)
    entry = ref.load_entry_route(ref.DEFAULT_ENTRY_ROUTE)
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        folders = ref.extract_seasons(ref.DEFAULT_ZIP, Path(temp))
        folders[real_data.AGE_SEASON] = ref.DEFAULT_RAW_2026
        for season, folder in sorted(folders.items()):
            if season not in REAL_SEASONS[REAL_ALL]:
                continue
            tables, _ = ref.parse_directory(folder)
            players = ref.decorate_season(tables["players"], season, foreign_keys, entry)
            for row in real_data.attach_real_details(players, tables["specials"], tables["breaking"]):
                if row.get("is_foreign") or row.get("role") != "投手":
                    continue
                ranked = {name[:-1]: name for name, kind in row.get("specials") or [] if kind == "rank"}
                throws, _bats = ta._hand_parts(row.get("throws_bats"))
                role = "先発" if str(row.get("pitcher_roles") or "")[:1] == "先" else "救援"
                speed = float(row["top_speed"]) if not pd.isna(row.get("top_speed")) else math.nan
                rows.append({"season": season, **pitcher_row(role, throws, speed, ranked, row.get("breaking_balls") or [], real=True)})
    return pd.DataFrame(rows)


def _stat(x: pd.Series) -> list[float]:
    x = pd.Series(x, dtype=float).dropna()
    return [round(float(x.mean()), 4), round(float(x.std()), 4), int(len(x))]


def real_statistics(rows: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, seasons in REAL_SEASONS.items():
        part = rows[rows["season"].isin(seasons)]
        by_role: dict[str, Any] = {}
        for role in ROLES:
            r = part[part["prole"] == role]
            item: dict[str, Any] = {"人数": int(len(r)), "rank_points": _stat(r["rank_points"])}
            for group in RANK_GROUPS:
                item[group] = _stat(r[f"pt_{group}"])
                item[f"{group}_ランク"] = {letter: round(float((r[f"rk_{group}"] == letter).mean() * 100), 1) for letter in LETTERS}
            for hand in ("右", "左"):
                h = r[r["throws"] == hand]
                item[f"対左打者_ランク_{hand}投"] = {letter: round(float((h["rk_対左打者"] == letter).mean() * 100), 1) for letter in LETTERS}
            item["変化球数"] = _stat(r["変化球数"])
            item["総変化量"] = _stat(r["総変化量"])
            item["球種数の割合"] = {str(k): round(float((r["変化球数"] == k).mean()), 4) for k in (1, 2, 3, 4)}
            item["1球種の総変化量"] = _stat(r.loc[r["変化球数"] == 1, "総変化量"])
            bands = r["球速"].map(band_of)
            item["球速の帯"] = {band: _stat(r.loc[bands == band, "変化球数"]) for band, _low, _high in SPEED_BANDS}
            by_role[role] = item
        out[label] = by_role
    return out


def build_real() -> None:
    rows = load_real_rows()
    data = {
        "作り方": "scripts/check_pitcher_rank_pitches.py --build-real。実在の日本人投手（外国人を除く）。役割は起用の最初の文字が「先」なら先発。"
                 "ランク点は査定のランク点（D=0、持たない項目はD）。変化球数・総変化量は第一球種の変化球。[平均, 標準偏差, 人数]",
        "実在": real_statistics(rows),
    }
    REAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_PATH}（{len(rows)}人）")


def real_reference() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))["実在"]


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
_MASTER = None


def _init_worker() -> None:
    logging.disable(logging.WARNING)
    global _MASTER
    import app

    _MASTER = app.load_master_data()


def generated_row(player: dict[str, Any]) -> dict[str, Any]:
    abilities = player.get("abilities") if isinstance(player.get("abilities"), dict) else {}
    throws, _bats = ta._hand_parts(player.get("batting_throwing"))
    role = "先発" if player.get("position") == "先発" else "救援"
    return pitcher_row(role, throws, ta._number(abilities.get("球速")), abilities.get("ranked_specials") or {}, player.get("breaking_balls") or [], real=False)


def _team(team_seed: int) -> list[dict[str, Any]]:
    import app

    team = app.generate_team(team_seed, master=_MASTER)
    return [
        {"team_key": str(team_seed), **generated_row(p)}
        for p in team["players"] if p.get("role") == "投手" and p.get("roster_origin") != "foreign_import"
    ]


def collect(teams: int, start: int, workers: int) -> pd.DataFrame:
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        rows = [row for part in pool.map(_team, range(start, start + teams), chunksize=4) for row in part]
    return pd.DataFrame(rows)


def single_pitchers(path: Path) -> pd.DataFrame:
    """個別生成のサンプルCSV（generate_fictional_balance_sample.py の投手）から、日本人投手を取り出す。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df[(df["category"] == "架空球団用") & (df["roster_origin"] == "domestic") & (df["role"] == "投手")]
    rows = []
    for record in df.to_dict("records"):
        player = {
            "position": record["position"], "batting_throwing": record["batting_throwing"],
            "abilities": json.loads(record["abilities_json"]), "breaking_balls": json.loads(record["breaking_balls_json"]),
        }
        rows.append({"team_key": str(record.get("seed", len(rows))), **generated_row(player)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def evaluate(frame: pd.DataFrame, prefix: str = SCRIPT, info: bool = False) -> Checks:
    real = real_reference()
    checks = Checks(prefix)
    kind = checklib.KIND_INFO if info else checklib.KIND_REAL

    def add(section: str, key: str, label: str, value: float, low: float, high: float, real_text: str, fmt: str = "{:+.2f}") -> None:
        checks.add(f"{prefix}.{section}.{key}", kind, label, value, low, high, section=SECTIONS[section],
                   shown="nan" if math.isnan(value) else fmt.format(value), target=f"{fmt.format(low)}〜{fmt.format(high)}", real=real_text)

    for role in ROLES:
        part = frame[frame["prole"] == role]
        a, b = real[REAL_ALL][role]["rank_points"][0], real[REAL_2026][role]["rank_points"][0]
        add("rank_total", role, f"{role} ランク点の合計", part["rank_points"].mean(), min(a, b) - TOL_RANK_TOTAL, max(a, b) + TOL_RANK_TOTAL,
            f"{a:+.2f}（2026年版 {b:+.2f}）")
        for group in RANK_GROUPS:
            r = real[REAL_ALL][role][group][0]
            add("rank_group", f"{group}.{role}", f"{role} {group}のランク点", part[f"pt_{group}"].mean(), r - TOL_RANK_GROUP, r + TOL_RANK_GROUP, f"{r:+.2f}")

    relief = frame[frame["prole"] == "救援"]
    rr = real[REAL_ALL]["救援"]
    r = rr["変化球数"][0]
    add("reliever_pitches", "count", "救援の変化球数の平均", relief["変化球数"].mean(), r - TOL_PITCH_COUNT, r + TOL_PITCH_COUNT, f"{r:.2f}", "{:.2f}")
    r = rr["球種数の割合"]["1"]
    checks.add(f"{prefix}.reliever_pitches.one", kind, "救援の1球種の割合", float((relief["変化球数"] == 1).mean()), *ONE_PITCH_RANGE,
               section=SECTIONS["reliever_pitches"], shown=f"{(relief['変化球数'] == 1).mean():.1%}",
               target=f"{ONE_PITCH_RANGE[0]:.0%}〜{ONE_PITCH_RANGE[1]:.0%}", real=f"{r:.1%}")
    r = rr["総変化量"][0]
    add("reliever_pitches", "movement", "救援の総変化量の平均", relief["総変化量"].mean(), r - TOL_MOVEMENT, r + TOL_MOVEMENT, f"{r:.2f}", "{:.2f}")
    bands = relief["球速"].map(band_of)
    for band, _low, _high in SPEED_BANDS:
        r = rr["球速の帯"][band][0]
        x = relief.loc[bands == band, "変化球数"]
        add("reliever_band", band, f"救援 球速{band}の変化球数", x.mean() if len(x) else math.nan, r - TOL_PITCH_BAND, r + TOL_PITCH_BAND, f"{r:.2f}", "{:.2f}")

    # 参考: 球種数の割合（2・3球種）、先発の変化球数・総変化量
    for k in (2, 3):
        r = rr["球種数の割合"][str(k)]
        v = float((relief["変化球数"] == k).mean())
        checks.info(f"{prefix}.reference.reliever_share{k}", f"救援の{k}球種の割合", v, section=SECTIONS["reference"], shown=f"{v:.1%}", real=f"{r:.1%}")
    starter = frame[frame["prole"] == "先発"]
    rs = real[REAL_ALL]["先発"]
    for column, key in (("変化球数", "starter_count"), ("総変化量", "starter_movement")):
        v = starter[column].mean()
        checks.info(f"{prefix}.reference.{key}", f"先発の{column}の平均", v, section=SECTIONS["reference"], shown=f"{v:.2f}", real=f"{rs[column][0]:.2f}")
    return checks


def real_errors(prefix: str = SCRIPT) -> dict[str, float]:
    """実在側の誤差（平均は 標準偏差/√人数、割合は √(p(1−p)/人数)）。"""
    real = real_reference()[REAL_ALL]
    se: dict[str, float] = {}
    mean_se = lambda stat: stat[1] / math.sqrt(stat[2]) if stat[2] > 1 else math.nan  # noqa: E731
    for role in ROLES:
        se[f"{prefix}.rank_total.{role}"] = mean_se(real[role]["rank_points"])
        for group in RANK_GROUPS:
            se[f"{prefix}.rank_group.{group}.{role}"] = mean_se(real[role][group])
    se[f"{prefix}.reliever_pitches.count"] = mean_se(real["救援"]["変化球数"])
    se[f"{prefix}.reliever_pitches.movement"] = mean_se(real["救援"]["総変化量"])
    for band, _low, _high in SPEED_BANDS:
        se[f"{prefix}.reliever_band.{band}"] = mean_se(real["救援"]["球速の帯"][band])
    return se


def grade_all(frame: pd.DataFrame, boot: int, quick: bool = False) -> list[checklib.Check]:
    """球団を単位に生成側の誤差を求めて合否を付ける。1球種の割合は範囲が実在から決まらないので、生成側の誤差だけ。"""
    checks = evaluate(frame)
    se_gen = checklib.bootstrap_se(evaluate, frame, lambda f, rng: checklib.resample_frame(f, rng, "team_key"), n=boot) if boot else {}
    return checklib.grade(checks, se_gen=se_gen, se_real=real_errors() if boot else {}, all_info=quick)


def rank_table(frame: pd.DataFrame) -> pd.DataFrame:
    """ランクの割合（%、A〜G）。生成と実在（2024〜2026年版）。"""
    real = real_reference()[REAL_ALL]
    rows = []
    for group in RANK_GROUPS:
        if group == "対左打者":
            keys = [(f"{group} {hand}投", frame["throws"] == hand, real["先発"], real["救援"], hand) for hand in ("右", "左")]
            for label, mask, _rs, _rr, hand in keys:
                # 実在は役割ごとに持っているので、人数で重みを付けて合わせる
                n_s, n_r = real["先発"]["人数"], real["救援"]["人数"]
                ref = {x: (real["先発"][f"対左打者_ランク_{hand}投"][x] * n_s + real["救援"][f"対左打者_ランク_{hand}投"][x] * n_r) / (n_s + n_r) for x in LETTERS}
                gen = frame.loc[mask, f"rk_{group}"]
                rows.append({"項目": label, "": "生成", **{x: round(float((gen == x).mean() * 100), 1) for x in LETTERS}})
                rows.append({"項目": label, "": "実在", **{x: round(ref[x], 1) for x in LETTERS}})
            continue
        for role in ROLES:
            gen = frame.loc[frame["prole"] == role, f"rk_{group}"]
            rows.append({"項目": f"{group} {role}", "": "生成", **{x: round(float((gen == x).mean() * 100), 1) for x in LETTERS}})
            rows.append({"項目": f"{group} {role}", "": "実在", **real[role][f"{group}_ランク"]})
    return pd.DataFrame(rows)


def print_reference(frame: pd.DataFrame) -> None:
    print("\n[ランクの割合（%）。参考]")
    print(rank_table(frame).to_string(index=False))
    relief = frame[frame["prole"] == "救援"]
    real = real_reference()[REAL_ALL]["救援"]
    print(f"\n[救援の1球種の総変化量の平均（参考）] {relief.loc[relief['変化球数'] == 1, '総変化量'].mean():.2f}（実在 {real['1球種の総変化量'][0]:.2f}）")
    bands = relief["球速"].map(band_of)
    print("[救援の球速の帯ごとの人数（参考）] " + " ／ ".join(f"{band} {int((bands == band).sum())}人（実在 {real['球速の帯'][band][2]}人）" for band, _l, _h in SPEED_BANDS))


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）投手のランク特能の役割の差と救援の球種数を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--single-csv", type=Path, default=None, help="個別生成（架空球団用・投手）のサンプルCSV。あれば同じ表を参考として出す")
    parser.add_argument("--build-real", action="store_true", help="実在の集計（data/config/pitcher_rank_pitches_real.json）を作り直して終わる")
    checklib.add_common_args(parser)
    args = parser.parse_args()
    if args.build_real:
        build_real()
        return

    frame = collect(args.teams, args.start, args.workers)
    title = f"球団生成 {args.teams}球団（seed {args.start}〜{args.start + args.teams - 1}） 日本人投手 {len(frame)}人"
    graded = grade_all(frame, args.boot, args.quick)
    checklib.print_checks(graded, title)
    print_reference(frame)
    if args.single_csv is not None and args.single_csv.exists():
        single = single_pitchers(args.single_csv)
        reference = list(checklib.grade(evaluate(single, f"{SCRIPT}.single", info=True), all_info=True))
        checklib.print_checks(reference, f"個別生成（架空球団用・日本人投手 {len(single)}人。参考）")
        print_reference(single)
        graded += reference
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    main()
