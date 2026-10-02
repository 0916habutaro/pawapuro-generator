#!/usr/bin/env python3
"""架空球団用（日本人）の特殊能力の数・ランク特能・査定値の年齢帯別チェッカー。

基準は `特能ランク年齢補正_改修指示.md` §1・§3。実在は data/reference/real_age_profile_2022_2026.csv
（特能の数は2022〜2026の5年まとめ、ランクは2026のみ）を、単調に変わるように平滑化した値。
目標値を変えたときは、このファイルの TARGETS も合わせて直すこと。

使い方:
    python scripts/check_age_profile.py                       # 個別生成 投手・野手 各5000人 ＋ 球団生成 500球団
    python scripts/check_age_profile.py --players 1000 --teams 0   # 簡易版（途中確認用）
    python scripts/check_age_profile.py --save before.csv     # 選手ごとの値を保存（修正前後の比較用）
    python scripts/check_age_profile.py --compare before.csv  # 保存した値と並べて表示

- 個別生成は seed 1〜N、球団生成は validate_team_mode.py と同じ seed（20261001〜）を使う。
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
        "player_class": player.get("player_class"),
        "n_pos": n_pos,
        "n_neg": n_neg,
        "n_green": n_green,
        "n_total": n_pos + n_neg + n_green,
        "rk_pts": sum(rank_points(group, letter, role) for group, letter in letters.items()),
        "rk_hi": sum(letter in {"S", "A", "B"} for letter in letters.values()),
        "rk_a": int(any(letter == "A" for letter in letters.values())),
        "rk_g": int(any(letter == "G" for letter in letters.values())),
        "rating": player_rating(player),
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
    return [player_metrics(player, "球団") for player in team["players"] if is_target(player)]


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


def to_markdown(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    sep = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, sep, *body])


def report(frame: pd.DataFrame, title: str = "") -> tuple[list[str], int]:
    """年齢帯別の表と判定を Markdown の行で返す。(行, 不合格数)"""
    lines: list[str] = []
    failures = 0
    for source in ("個別", "球団"):
        for role in ("野手", "投手"):
            part = frame[(frame.source == source) & (frame.role == role)]
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
    parser.add_argument("--players", type=int, default=5000, help="個別生成の人数（投手・野手それぞれ）")
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
    if args.compare:
        lines += ["## 修正前との比較", ""] + compare_lines(pd.read_csv(args.compare, encoding="utf-8-sig"), frame)
    print("\n".join(lines))
    print(f"不合格 {failures} 項目")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
