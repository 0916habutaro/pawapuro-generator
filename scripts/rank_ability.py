"""
能力とランク特能の結びつきの判定の共通部分（`能力とランク特能の結びつき_改修指示.md` 2-1）。

- 架空球団用の日本人の、回復（先発・救援・野手）、打たれ強さ（先発・救援）、送球（野手）、キャッチャー（メインが捕手）の
  7区分について、ランクの点と能力の合成値の相関、ランクの割合（B〜F）を実在と比べる。
- 投手の4区分は check_pitcher_rank_pitches.py、野手の3区分は check_fielder_position.py が、この module の
  ability_checks で節を足す。
- ランクの点は A=3、B=2、C=1、D=0、E=−1、F=−2、G=−3（査定のランク点ではない）。ランク特能を持たない項目は D。
- 能力の合成値 = 平均((能力 − 実在の平均) ÷ 実在のSD)。平均・SD は実在の、投手は先発・救援ごと、野手は野手全体、
  キャッチャーは捕手だけの値（app.py の FICTIONAL_ABILITY_RANK_STATS と同じ値を、実在から作り直して持つ）。
- 実在は2024〜2026年版の日本人（ポジションはメイン、役割は起用の最初の文字が「先」なら先発）。
  data/config/rank_ability_real.json（`python scripts/rank_ability.py --build-real` で実在の元データ data/raw/ から作る）。
- 同じ選手が複数の年版に入っているので、実在側の誤差は異なる選手の数（名前で数える）で見積もる。
  相関は (1−r²)/√(人数−1)、割合は √(p(1−p)/人数)。
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from checklib import Checks  # noqa: E402

REAL_PATH = APP_DIR / "data" / "config" / "rank_ability_real.json"
REAL_SEASONS = (2024, 2025, 2026)
LETTERS = ("A", "B", "C", "D", "E", "F", "G")
CHECKED_LETTERS = ("B", "C", "D", "E", "F")
SCORES = {"A": 3, "B": 2, "C": 1, "D": 0, "E": -1, "F": -2, "G": -3}
GROUPS = {"投手": ("回復", "打たれ強さ"), "野手": ("回復", "送球", "キャッチャー")}
ABILITIES = {"投手": ("コントロール", "スタミナ"), "野手": ("ミート", "守備力", "捕球")}
# 平均・SDの表: 鍵 → (投手/野手, 役割（投手）またはポジション（野手）の一覧。None は全員)
STATS_PARTS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "投手_先発": ("投手", ("先発",)), "投手_救援": ("投手", ("救援",)), "野手": ("野手", None), "捕手": ("野手", ("捕手",)),
}
# 区分: 鍵 → (表示名, 投手/野手, ランク特能, 役割またはポジションの一覧, 能力, 平均・SDの表の鍵)
PARTS: dict[str, tuple[str, str, str, tuple[str, ...] | None, tuple[str, ...], str]] = {
    "回復_先発": ("回復 先発", "投手", "回復", ("先発",), ("コントロール", "スタミナ"), "投手_先発"),
    "回復_救援": ("回復 救援", "投手", "回復", ("救援",), ("コントロール", "スタミナ"), "投手_救援"),
    "打たれ強さ_先発": ("打たれ強さ 先発", "投手", "打たれ強さ", ("先発",), ("コントロール", "スタミナ"), "投手_先発"),
    "打たれ強さ_救援": ("打たれ強さ 救援", "投手", "打たれ強さ", ("救援",), ("コントロール", "スタミナ"), "投手_救援"),
    "回復_野手": ("回復 野手", "野手", "回復", None, ("ミート", "守備力", "捕球"), "野手"),
    "送球_野手": ("送球 野手", "野手", "送球", None, ("捕球", "守備力"), "野手"),
    "キャッチャー_捕手": ("キャッチャー 捕手", "野手", "キャッチャー", ("捕手",), ("捕球", "守備力"), "捕手"),
}
SCRIPT_PARTS = {
    "check_pitcher_rank_pitches": [k for k, v in PARTS.items() if v[1] == "投手"],
    "check_fielder_position": [k for k, v in PARTS.items() if v[1] == "野手"],
}
# 合格の範囲（指示書2-1）
TOL_CORR, TOL_SHARE = 0.12, 4.0
# 改修前（球団生成 seed 1〜300、PYTHONHASHSEED=0、main cdf0b2d。PC で測った）の値。表示用。(割合（%、A〜G）, 相関)
BEFORE: dict[str, tuple[tuple[float, ...], float]] = {
    "回復_先発": ((0.2, 6.8, 13.4, 33.4, 33.6, 12.4, 0.1), 0.12),
    "回復_救援": ((0.2, 9.8, 23.0, 38.2, 24.2, 4.2, 0.4), 0.11),
    "打たれ強さ_先発": ((0.3, 9.6, 21.6, 50.6, 13.9, 3.8, 0.1), 0.13),
    "打たれ強さ_救援": ((0.2, 9.8, 21.4, 51.2, 14.1, 3.1, 0.2), 0.14),
    "回復_野手": ((0.2, 2.8, 10.6, 24.9, 47.9, 13.2, 0.4), 0.07),
    "送球_野手": ((0.3, 6.3, 18.7, 38.4, 30.2, 6.0, 0.2), 0.07),
    "キャッチャー_捕手": ((0.1, 1.8, 7.7, 42.8, 32.9, 14.6, 0.1), 0.05),
}
SECTION = "能力とランク特能の結びつき（相関は能力の合成値とランクの点。実在±0.12。ランクの割合は%で実在±4ポイント。実在は2024〜2026年版の日本人）"


def letter_of(ranked: dict[str, str], group: str) -> str:
    letter = str((ranked or {}).get(group) or "D")[-1:]
    return letter if letter in LETTERS else "D"


def letter_columns(ranked: dict[str, str], role: str) -> dict[str, str]:
    """1人分のランクの文字の列（rk_項目）。持たない項目は D。"""
    return {f"rk_{group}": letter_of(ranked, group) for group in GROUPS[role]}


def part_rows(frame: pd.DataFrame, role: str, members: tuple[str, ...] | None) -> pd.DataFrame:
    """区分の選手。野手は列 position、投手は列 prole（先発・救援）で分ける。"""
    if members is None:
        return frame
    return frame[frame["prole" if role == "投手" else "position"].isin(members)]


def composite(part: pd.DataFrame, abilities: tuple[str, ...], stats: dict[str, list[float]]) -> pd.Series:
    """能力の合成値（実在の平均・SDで標準化した値の平均）。"""
    z = [(part[name].astype(float) - stats[name][0]) / stats[name][1] for name in abilities]
    return sum(z) / len(z)


def correlation(x: pd.Series, y: pd.Series) -> float:
    ok = x.notna() & y.notna()
    x, y = x[ok].astype(float).to_numpy(), y[ok].astype(float).to_numpy()
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return math.nan
    return float(np.corrcoef(x, y)[0, 1])


def part_statistics(frame: pd.DataFrame, key: str, stats: dict[str, dict[str, list[float]]]) -> dict[str, Any]:
    """区分のランクの割合（%）と、ランクの点と能力の合成値の相関。"""
    _label, role, group, members, abilities, stats_key = PARTS[key]
    part = part_rows(frame, role, members)
    letters = part[f"rk_{group}"]
    scores = letters.map(SCORES).astype(float)
    return {
        "割合": {letter: round(float((letters == letter).mean() * 100), 2) for letter in LETTERS},
        "相関": round(correlation(scores, composite(part, abilities, stats[stats_key])), 4),
        "人数": int(len(part)),
    }


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
REAL_ABILITY_COLUMNS = {"コントロール": "control", "スタミナ": "stamina", "ミート": "contact", "守備力": "fielding", "捕球": "catching"}


def load_real_rows() -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人。元データ（data/raw/ の zip と 2026年版のフォルダ）から読む。"""
    import build_real_team_reference as ref
    from generator import real_data

    foreign_keys = ref.foreign_list_keys(ref.DEFAULT_FOREIGN_LIST)
    entry = ref.load_entry_route(ref.DEFAULT_ENTRY_ROUTE)
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        folders = ref.extract_seasons(ref.DEFAULT_ZIP, Path(temp))
        folders[real_data.AGE_SEASON] = ref.DEFAULT_RAW_2026
        for season, folder in sorted(folders.items()):
            if season not in REAL_SEASONS:
                continue
            tables, _ = ref.parse_directory(folder)
            players = ref.decorate_season(tables["players"], season, foreign_keys, entry)
            for row in real_data.attach_real_details(players, tables["specials"], tables["breaking"]):
                if row.get("is_foreign"):
                    continue
                ranked = {name[:-1]: name for name, kind in row.get("specials") or [] if kind == "rank"}
                role = "投手" if row.get("role") == "投手" else "野手"
                rows.append({
                    "season": season, "name": "".join(str(row.get("name") or "").split()), "role": role,
                    "position": str(row.get("main_position") or ""),
                    "prole": "先発" if str(row.get("pitcher_roles") or "")[:1] == "先" else "救援",
                    **{name: pd.to_numeric(row.get(REAL_ABILITY_COLUMNS[name]), errors="coerce") for name in ABILITIES[role]},
                    **letter_columns(ranked, role),
                })
    return pd.DataFrame(rows)


def real_ability_stats(rows: pd.DataFrame) -> dict[str, dict[str, list[float]]]:
    """平均・SDの表（実在）。鍵ごとに {能力: [平均, SD]}。"""
    out: dict[str, dict[str, list[float]]] = {}
    for key, (role, members) in STATS_PARTS.items():
        part = part_rows(rows[rows["role"] == role], role, members)
        names = sorted({name for k, v in PARTS.items() if v[5] == key for name in v[4]}, key=ABILITIES[role].index)
        out[key] = {name: [round(float(part[name].mean()), 4), round(float(part[name].std()), 4)] for name in names}
    return out


def build_real() -> None:
    rows = load_real_rows()
    stats = real_ability_stats(rows)
    parts = {}
    for key, (_label, role, _group, members, _abilities, _stats_key) in PARTS.items():
        part = part_rows(rows[rows["role"] == role], role, members)
        parts[key] = {**part_statistics(part, key, stats), "異なる選手の数": int(part["name"].nunique())}
    data = {
        "作り方": "python scripts/rank_ability.py --build-real。実在（2024〜2026年版）の日本人（外国人を除く）。ポジションはメイン、"
                 "投手の役割は起用の最初の文字が「先」なら先発（ほかは救援）。ランクの点は A=3〜G=−3（持たない項目はD）。"
                 "能力の合成値は「平均・SD」で標準化した能力の平均。割合は%。異なる選手の数は名前で数えた（誤差に使う）",
        "平均・SD": stats,
        "実在": parts,
    }
    REAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_PATH}（{len(rows)}人）")


def _real() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))


def real_reference() -> dict[str, Any]:
    return _real()["実在"]


def ability_stats() -> dict[str, dict[str, list[float]]]:
    return _real()["平均・SD"]


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def ability_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str, keys: list[str]) -> None:
    """区分ごとの相関と B〜F の割合。frame は rk_項目・能力の列と、position（野手）または prole（投手）を持つ。"""
    real, stats = real_reference(), ability_stats()
    for key in keys:
        label = PARTS[key][0]
        now, r = part_statistics(frame, key, stats), real[key]
        value, rv = now["相関"], r["相関"]
        checks.add(f"{prefix}.rank_ability.{key}_corr", kind, f"{label} 能力との相関", value, rv - TOL_CORR, rv + TOL_CORR, section=SECTION,
                   shown="nan" if math.isnan(value) else f"{value:+.2f}", target=f"{rv - TOL_CORR:+.2f}〜{rv + TOL_CORR:+.2f}",
                   real=f"{rv:+.2f}（{r['異なる選手の数']}人）")
        for letter in CHECKED_LETTERS:
            value, rv = now["割合"][letter], r["割合"][letter]
            low, high = rv - TOL_SHARE, rv + TOL_SHARE
            checks.add(f"{prefix}.rank_ability.{key}_{letter}", kind, f"{label} {letter}の割合", value, low, high, section=SECTION,
                       shown=f"{value:.1f}", target=f"{low:.1f}〜{high:.1f}", real=f"{rv:.1f}")


def share_se(share: float, n: int) -> float:
    p = share / 100
    return math.sqrt(p * (1 - p) / n) * 100 if n > 1 else math.nan


def real_errors(prefix: str, keys: list[str]) -> dict[str, float]:
    """実在側の誤差。人数は異なる選手の数。"""
    real = real_reference()
    se: dict[str, float] = {}
    for key in keys:
        r, n = real[key], real[key]["異なる選手の数"]
        se[f"{prefix}.rank_ability.{key}_corr"] = (1 - r["相関"] ** 2) / math.sqrt(n - 1) if n > 1 else math.nan
        for letter in CHECKED_LETTERS:
            se[f"{prefix}.rank_ability.{key}_{letter}"] = share_se(r["割合"][letter], n)
    return se


def print_ability_reference(frame: pd.DataFrame, keys: list[str], before: bool = True) -> None:
    """区分ごとの相関とランクの割合（%）（改修前・今回・実在。参考）。"""
    real, stats = real_reference(), ability_stats()
    rows = []
    for key in keys:
        now = part_statistics(frame, key, stats)
        lines = [("改修前", BEFORE[key][0], BEFORE[key][1])] if before and key in BEFORE else []
        lines += [("今回", [now["割合"][x] for x in LETTERS], now["相関"]),
                  ("実在", [real[key]["割合"][x] for x in LETTERS], real[key]["相関"])]
        for name, shares, corr in lines:
            rows.append({"区分": PARTS[key][0], "": name, "相関": round(float(corr), 2), **{x: round(float(v), 1) for x, v in zip(LETTERS, shares)}})
    print("\n[能力とランク特能の結びつき（相関は能力の合成値とランクの点。割合は%。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    if "--build-real" in sys.argv[1:]:
        build_real()
    else:
        print("使い方: python scripts/rank_ability.py --build-real   # data/config/rank_ability_real.json を作り直す")
