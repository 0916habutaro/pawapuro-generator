"""実在の「対ランナー」の読み直し（PR #116）を、実在の年齢別データとその目標値に反映する。

実在の年齢別データ data/reference/real_age_profile_2022_2026.csv を作った元のスクリプトはリポジトリにない。
そのため全体は作り直さず、読み直しで変わる分だけを、旧い読み方と新しい読み方の差から求めて足す。

- 旧い読み方: 実在のHTMLの赤特「対ランナー」を青の名前「対ランナー」のまま、青特「対ランナー○」を「対ランナー○」のまま
- 新しい読み方: 赤特を「対ランナー×」、青特を「対ランナー」（import_real_powerpro_players.py）
- 特能の数（n_pos・n_neg・n_green）: 実在側は名前の一覧で数える（赤特の一覧に旧い読み方では「対ランナー」、新しい読み方では
  「対ランナー×」が入っている）ので、読み方が変わっても数は変わらないはず。差が0であることを確かめて表示する（0でなければ止める）。
- 投手の査定（rating。2026年版のみ）の平均とSDは、赤特の「対ランナー」が +6 から −5 になるので変わる。この差だけを足す。

足すのは次の3か所。二重に足さないよう、印（CSV の source 列の末尾と、check_age_profile.py のコメント）がある場合は何もしない。
- data/reference/real_age_profile_2022_2026.csv の 投手の rating 行（平均・SD）
- scripts/check_age_profile.py の REAL_RATING["投手"]
- scripts/check_age_profile.py の YOUNG_REAL["投手"] の "rating"

    python scripts/update_real_age_profile.py            # 前・後を表示して書き込む
    python scripts/update_real_age_profile.py --dry-run  # 表示だけ
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import pandas as pd  # noqa: E402

import build_real_team_reference as ref  # noqa: E402
import check_age_profile as cap  # noqa: E402
from generator import real_data  # noqa: E402
from generator.rating import player_rating  # noqa: E402

CSV_PATH = APP_DIR / "data" / "reference" / "real_age_profile_2022_2026.csv"
CHECK_PATH = APP_DIR / "scripts" / "check_age_profile.py"
MARK = " + 対ランナー読み直し済み"
CODE_MARK = "# 実在の投手の査定は、対ランナーの読み直し（scripts/update_real_age_profile.py）で直し済み。"
CSV_BANDS = [("18-19", 0, 19), ("20-21", 20, 21), ("22-23", 22, 23), ("24-25", 24, 25), ("26-27", 26, 27),
             ("28-29", 28, 29), ("30-31", 30, 31), ("32-33", 32, 33), ("34-35", 34, 35), ("36+", 36, 99)]
# check_age_profile.py の REAL_RATING の帯（RATING_BANDS の順）と YOUNG_REAL の帯
RATING_RANGES = [(0, 21), (22, 23), (24, 25), (26, 27), (28, 29), (30, 31), (32, 33), (34, 99)]
YOUNG_RANGES = {"〜19": (0, 19), "20〜21": (20, 21), "22〜23": (22, 23)}


def to_legacy(specials: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """新しい読み方の特能を、旧い読み方の名前に戻す（読み替えの逆）。"""
    renamed = {"対ランナー×": "対ランナー", "対ランナー": "対ランナー○"}
    return [(renamed.get(name, name), kind) for name, kind in specials]


def load_pitchers() -> list[dict]:
    """日本人の投手を、年版・逆算した年齢・新旧それぞれの読み方での査定値と特能の数にして返す。"""
    foreign_keys = ref.foreign_list_keys(ref.DEFAULT_FOREIGN_LIST)
    entry = ref.load_entry_route(ref.DEFAULT_ENTRY_ROUTE)
    legacy_negative = (set(cap.NEGATIVE_SPECIALS) - {"対ランナー×"}) | {"対ランナー"}
    out = []
    with tempfile.TemporaryDirectory() as temp:
        folders = ref.extract_seasons(ref.DEFAULT_ZIP, Path(temp))
        folders[real_data.AGE_SEASON] = ref.DEFAULT_RAW_2026
        for season, folder in folders.items():
            tables, _ = ref.parse_directory(folder)
            players = ref.decorate_season(tables["players"], season, foreign_keys, entry)
            for row in real_data.attach_real_details(players, tables["specials"], tables["breaking"]):
                if row["role"] != "投手" or row.get("is_foreign") or pd.isna(row.get("age_backcalc")):
                    continue
                item = {"season": season, "age": int(row["age_backcalc"])}
                for label, specials, negative in (("new", row["specials"], set(cap.NEGATIVE_SPECIALS)),
                                                  ("old", to_legacy(row["specials"]), legacy_negative)):
                    rating_dict = real_data.real_player_to_rating_dict({**row, "specials": specials})
                    names = rating_dict["special_abilities"]
                    item[label] = {
                        "rating": player_rating(rating_dict),
                        "n_neg": sum(name in negative for name in names),
                        "n_green": sum(name in cap.GREEN_SPECIALS for name in names),
                        "n_pos": sum(name not in negative and name not in cap.GREEN_SPECIALS and name not in cap.USAGE_ITEMS for name in names),
                    }
                out.append(item)
    return out


def mean_sd(values: list[float]) -> tuple[float, float]:
    series = pd.Series(values, dtype=float)
    return float(series.mean()), float(series.std(ddof=1))


def members(pitchers: list[dict], low: int, high: int, only_latest: bool) -> list[dict]:
    return [p for p in pitchers if low <= p["age"] <= high and (not only_latest or p["season"] == real_data.AGE_SEASON)]


def check_counts_unchanged(pitchers: list[dict]) -> None:
    print("特能の数（投手、2022〜2026、帯ごとの平均の 新 − 旧）")
    worst = 0.0
    for band, low, high in CSV_BANDS:
        group = members(pitchers, low, high, False)
        diffs = {m: sum(p["new"][m] - p["old"][m] for p in group) / len(group) for m in ("n_pos", "n_neg", "n_green")}
        worst = max(worst, *(abs(v) for v in diffs.values()))
        print(f"  {band:>5}  n={len(group):>3}  n_pos {diffs['n_pos']:+.4f}  n_neg {diffs['n_neg']:+.4f}  n_green {diffs['n_green']:+.4f}")
    if worst > 1e-12:
        raise SystemExit(f"特能の数が読み方で変わっています（最大 {worst:.4f}）。足さずに止めます。")
    print("  → すべて 0。特能の数には足さない。")


def rating_delta(pitchers: list[dict], low: int, high: int) -> dict[str, float]:
    group = members(pitchers, low, high, True)
    old_mean, old_sd = mean_sd([p["old"]["rating"] for p in group])
    new_mean, new_sd = mean_sd([p["new"]["rating"] for p in group])
    return {"n": len(group), "d_mean": new_mean - old_mean, "d_sd": new_sd - old_sd}


def update_csv(pitchers: list[dict], write: bool) -> None:
    frame = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    print("\nreal_age_profile_2022_2026.csv の投手の rating（2026年版）  平均・SD  前 → 後")
    for band, low, high in CSV_BANDS:
        mask = (frame["group"] == "rating") & (frame["role"] == "投手") & (frame["band"] == band)
        delta = rating_delta(pitchers, low, high)
        row = frame[mask].iloc[0]
        assert int(row["n"]) == delta["n"], f"{band}: 人数が合わない（CSV {row['n']} / 取り込み {delta['n']}）"
        new_mean, new_sd = round(row["mean"] + delta["d_mean"], 2), round(row["sd"] + delta["d_sd"], 2)
        print(f"  {band:>5}  n={delta['n']:>3}  平均 {row['mean']:.2f} → {new_mean:.2f} ({delta['d_mean']:+.2f})  SD {row['sd']:.2f} → {new_sd:.2f} ({delta['d_sd']:+.2f})")
        frame.loc[mask, ["mean", "sd"]] = [new_mean, new_sd]
        frame.loc[mask, "source"] = row["source"] + MARK
    if write:
        frame.to_csv(CSV_PATH, index=False, encoding="utf-8-sig", lineterminator="
")


def rounded(value: float) -> int:
    return int(math.floor(value + 0.5))


def update_check_script(pitchers: list[dict], write: bool) -> None:
    text = CHECK_PATH.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    # REAL_RATING["投手"]
    match = re.search(r'("投手": \[)((?:\(\d+, \d+\)(?:, )?)+)(\],)', text[text.index("REAL_RATING"):])
    start = text.index("REAL_RATING") + match.start(2)
    end = text.index("REAL_RATING") + match.end(2)
    old_pairs = [tuple(int(x) for x in pair) for pair in re.findall(r"\((\d+), (\d+)\)", match.group(2))]
    assert len(old_pairs) == len(RATING_RANGES)
    new_pairs = []
    print("\ncheck_age_profile.py の REAL_RATING['投手']（平均, SD）  前 → 後")
    for (low, high), (mean, sd) in zip(RATING_RANGES, old_pairs):
        delta = rating_delta(pitchers, low, high)
        pair = (rounded(mean + delta["d_mean"]), rounded(sd + delta["d_sd"]))
        new_pairs.append(pair)
        print(f"  {low}〜{high}: {(mean, sd)} → {pair}")
    text = text[:start] + ", ".join(f"({m}, {s})" for m, s in new_pairs) + text[end:]
    # YOUNG_REAL["投手"] の "rating"
    print("\ncheck_age_profile.py の YOUNG_REAL['投手'] の rating（平均, SD）  前 → 後")
    block_start = text.index("YOUNG_REAL")
    for band, (low, high) in YOUNG_RANGES.items():
        line_start = text.index(f'"{band}": {{"speed"', block_start)
        line_end = text.index(newline, line_start)
        line = text[line_start:line_end]
        found = re.search(r'"rating": \((\d+), (\d+)\)', line)
        mean, sd = int(found.group(1)), int(found.group(2))
        delta = rating_delta(pitchers, low, high)
        pair = (rounded(mean + delta["d_mean"]), rounded(sd + delta["d_sd"]))
        print(f"  {band}: {(mean, sd)} → {pair}")
        line = line[:found.start()] + f'"rating": ({pair[0]}, {pair[1]})' + line[found.end():]
        text = text[:line_start] + line + text[line_end:]
    text = text.replace("REAL_RATING = {", CODE_MARK + newline + "REAL_RATING = {", 1)
    if write:
        CHECK_PATH.write_bytes(text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="実在の対ランナーの読み直しを、実在の年齢別データとその目標値に反映します。")
    parser.add_argument("--dry-run", action="store_true", help="表示だけで書き込まない")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    if pd.read_csv(CSV_PATH, encoding="utf-8-sig")["source"].str.contains(MARK, regex=False).any() or CODE_MARK in CHECK_PATH.read_text(encoding="utf-8"):
        print("すでに反映済みです（印があります）。何もしません。")
        return 0
    pitchers = load_pitchers()
    check_counts_unchanged(pitchers)
    update_csv(pitchers, write=not args.dry_run)
    update_check_script(pitchers, write=not args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
