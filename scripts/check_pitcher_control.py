#!/usr/bin/env python3
"""
架空球団用（日本人）投手のコントロールの役割・左右を、球団生成で判定する（`救援投手コントロール_改修指示.md`）。

使い方:
    python scripts/check_pitcher_control.py                 # 正式: 球団生成300球団（seed 1〜300）
    python scripts/check_pitcher_control.py --teams 60      # 途中確認用

- 球団生成で作った球団の日本人投手を、実在（2024〜2026年版の日本人投手1,126人）と比べる。
  役割の区分は、position が「先発」なら先発、「中継ぎ」「抑え」は救援。`batting_throwing` の先頭が「左」なら左。
- 判定する項目（指示書3-1）: 4区分（先発・救援×右・左）の平均、左右差、救援−先発、救援の標準偏差と10%・中央・90%、
  救援で60以上・70以上の割合、日本人全体の平均、4区分のスタミナの平均（改修前から動いていないこと）。
- 参考表示（判定しない）: 球団ごとの平均（救援・先発、外国人を含む。球団分析と同じ集計）の分布、
  年齢帯×役割のコントロール（実在は2026年版の12球団だけ）。
  球団ごとの散らばりは戦力レベルによる選手格の構成で決まるため、今回の調整の対象外（指示書 0-4）。
- 個別生成の判定（下限）と、コントロール20未満・相関などの既存項目は check_fictional_balance.py（個別生成5000人）。
- 終了コード: 全項目合格なら 0、不合格があれば 1。
"""
from __future__ import annotations

import argparse
import logging
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

from check_fictional_balance import Result, control_hand_rows, num, ok_range  # noqa: E402
from generator import team as team_lib  # noqa: E402
from generator import team_analysis  # noqa: E402

# 改修前（球団生成 seed 1〜300）の日本人投手のスタミナの平均。救援のコントロールの調整で変わっていないことの確認用。
STAMINA_BEFORE = {
    ("先発", "右"): 58.42, ("先発", "左"): 58.59,
    ("救援", "右"): 47.82, ("救援", "左"): 47.83,
}
# 実在（2024〜2026年版の36チーム、外国人を含む）の球団ごとのコントロールの平均の分布（最小, 10%, 中央, 90%, 最大）
REAL_TEAM_MEANS = {
    "救援": (43.67, 44.46, 47.97, 50.77, 53.88),
    "先発": (51.59, 52.40, 55.07, 58.32, 61.06),
}
# 改修前（球団生成 seed 1〜300）の同じ分布
BEFORE_TEAM_MEANS = {
    "救援": (41.47, 45.00, 50.17, 55.19, 60.13),
    "先発": (43.23, 49.79, 55.28, 60.00, 64.11),
}
# 実在（2026年版の日本人投手）の年齢帯×役割のコントロールの平均（人数）
REAL_AGE_BAND_2026 = {
    ("先発", "〜22歳"): (45.92, 39), ("先発", "23〜25歳"): (54.15, 54), ("先発", "26〜29歳"): (57.76, 51),
    ("先発", "30〜33歳"): (65.81, 21), ("先発", "34歳〜"): (70.62, 21),
    ("救援", "〜22歳"): (40.50, 18), ("救援", "23〜25歳"): (44.19, 32), ("救援", "26〜29歳"): (48.45, 85),
    ("救援", "30〜33歳"): (51.25, 24), ("救援", "34歳〜"): (57.29, 17),
}
QUANTILES = (0.0, 0.1, 0.5, 0.9, 1.0)
QUANTILE_LABELS = ("最小", "10%", "中央", "90%", "最大")

_MASTER = None


def _init_worker() -> None:
    logging.disable(logging.WARNING)
    global _MASTER
    import app

    _MASTER = app.load_master_data()


def _team(team_seed: int) -> pd.DataFrame:
    import app

    team = app.generate_team(team_seed, master=_MASTER)
    return team_analysis.players_frame(team["players"], f"gen:{team_seed}", str(team_seed))


def collect(teams: int, start: int, workers: int) -> pd.DataFrame:
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        frames = list(pool.map(_team, range(start, start + teams), chunksize=4))
    return pd.concat(frames, ignore_index=True)


def team_mean_table(pitchers: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group in ("救援", "先発"):
        means = pitchers[pitchers["pitcher_role"] == group].groupby("team_key")["コントロール"].mean()
        generated = means.quantile(list(QUANTILES)).tolist()
        for label, values in (("改修前", BEFORE_TEAM_MEANS[group]), ("生成", generated), ("実在", REAL_TEAM_MEANS[group])):
            rows.append({"役割": group, "": label, **{q: round(v, 2) for q, v in zip(QUANTILE_LABELS, values)}})
    return pd.DataFrame(rows)


def age_band_table(japanese: pd.DataFrame) -> pd.DataFrame:
    labels = japanese["age"].map(lambda age: team_lib.AGE_BAND_LABELS[team_lib.age_band_of(int(age))])
    rows = []
    for (group, band), (real, real_n) in REAL_AGE_BAND_2026.items():
        x = japanese.loc[(japanese["pitcher_role"] == group) & (labels == band), "コントロール"]
        rows.append({"役割": group, "年齢帯": band, "生成": round(x.mean(), 2), "生成の人数": len(x), "実在2026": real, "実在の人数": real_n})
    return pd.DataFrame(rows)


def evaluate(frame: pd.DataFrame) -> Result:
    pitchers = frame[frame["role"] == "投手"]
    japanese = pitchers[~pitchers["is_foreign"]]
    group, hand = japanese["pitcher_role"].to_numpy(), np.where(japanese["throws"] == "左", "左", "右")
    R = Result()
    s = "コントロールの役割・左右（実在は2024〜2026年版）"
    control_hand_rows(R, s, group, hand, japanese["コントロール"], formal=True)
    for (g, h), before in STAMINA_BEFORE.items():
        v = japanese.loc[(group == g) & (hand == h), "スタミナ"].mean()
        R.add(s, f"{g}・{h} スタミナ平均", num(v), ok_range(v, before - 0.3, before + 0.3), f"改修前{before:.2f}±0.3", "")
    s = "相関（参考。判定は check_fictional_balance.py の個別生成5000人）"
    ct = japanese["コントロール"]
    R.add(s, "球速×コントロール相関", num(japanese["球速"].corr(ct), 3), True, "−0.40〜−0.15", "−0.274", info=True)
    R.add(s, "コントロール×スタミナ相関", num(ct.corr(japanese["スタミナ"]), 3), True, "+0.38〜+0.58", "+0.491", info=True)
    s = "球団ごとの救援の平均（参考。外国人を含む）"
    means = pitchers[pitchers["pitcher_role"] == "救援"].groupby("team_key")["コントロール"].mean()
    real = REAL_TEAM_MEANS["救援"]
    for label, q, rq in (("10%", 0.1, real[1]), ("90%", 0.9, real[3])):
        v = means.quantile(q)
        R.add(s, label, num(v), ok_range(v, rq - 1.0, rq + 1.0), f"{rq - 1.0:.2f}〜{rq + 1.0:.2f}（目安）", num(rq), info=True)
    return R


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用（日本人）投手のコントロールの役割・左右を、球団生成で判定します。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式な判定は300）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = parser.parse_args()

    frame = collect(args.teams, args.start, args.workers)
    pitchers = frame[frame["role"] == "投手"]
    japanese = pitchers[~pitchers["is_foreign"]]
    title = f"球団生成 {args.teams}球団（seed {args.start}〜{args.start + args.teams - 1}） 日本人投手 {len(japanese)}人"
    ng = evaluate(frame).show(title)
    print("\n[球団ごとのコントロールの平均の分布（参考。外国人を含む。改修前は seed 1〜300）]")
    print(team_mean_table(pitchers).to_string(index=False))
    print("\n[年齢帯×役割のコントロールの平均（参考。日本人。実在は2026年版のみ）]")
    print(age_band_table(japanese).to_string(index=False))
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
