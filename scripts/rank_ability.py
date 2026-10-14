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
- 助っ人外国人用（`能力との結びつき_外国人_改修指示.md` 2-1）: 回復・打たれ強さ（先発・救援）、回復・送球（野手）の6区分の相関、
  全ランク特能（投手7・野手8）の B〜F の割合・A と G の割合、ランク点を、実在の外国人（2024〜2026年版）と比べる。
  能力は外国人の実在の平均・SD（投手は先発・救援ごと、野手は全体）で標準化する（app.py の FICTIONAL_ABILITY_RANK_STATS の「外国人_」）。
  外国人の実在は1区分37〜58人と少ないので、相関の目標は日本人の実在と外国人の実在の平均にする（誤差は両方の誤差を合わせて半分）。
  check_foreign_balance.py が球団生成の外国人で foreign_checks を呼ぶ。実在の値は rank_ability_real.json の「外国人」。
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

# 助っ人外国人用（`能力との結びつき_外国人_改修指示.md` 2-1）
FOREIGN_GROUPS = {
    "投手": ("クイック", "回復", "ノビ", "打たれ強さ", "対ピンチ", "対左打者", "ケガしにくさ"),
    "野手": ("走塁", "送球", "盗塁", "対左投手", "チャンス", "ケガしにくさ", "回復", "キャッチャー"),
}
FOREIGN_STATS_PARTS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "外国人_投手_先発": ("投手", ("先発",)), "外国人_投手_救援": ("投手", ("救援",)), "外国人_野手": ("野手", None),
}
# 区分: 鍵 → (表示名, 投手/野手, ランク特能, 役割の一覧, 能力, 平均・SDの表の鍵, 目標に平均する日本人の区分)
FOREIGN_PARTS: dict[str, tuple[str, str, str, tuple[str, ...] | None, tuple[str, ...], str, str]] = {
    "回復_先発": ("回復 先発", "投手", "回復", ("先発",), ("コントロール", "スタミナ"), "外国人_投手_先発", "回復_先発"),
    "回復_救援": ("回復 救援", "投手", "回復", ("救援",), ("コントロール", "スタミナ"), "外国人_投手_救援", "回復_救援"),
    "打たれ強さ_先発": ("打たれ強さ 先発", "投手", "打たれ強さ", ("先発",), ("コントロール", "スタミナ"), "外国人_投手_先発", "打たれ強さ_先発"),
    "打たれ強さ_救援": ("打たれ強さ 救援", "投手", "打たれ強さ", ("救援",), ("コントロール", "スタミナ"), "外国人_投手_救援", "打たれ強さ_救援"),
    "回復_野手": ("回復 野手", "野手", "回復", None, ("ミート", "守備力", "捕球"), "外国人_野手", "回復_野手"),
    "送球_野手": ("送球 野手", "野手", "送球", None, ("捕球", "守備力"), "外国人_野手", "送球_野手"),
}
# 合格の範囲（外国人の指示書2-1）
FOREIGN_TOL_CORR, FOREIGN_TOL_SHARE, FOREIGN_MAX_EDGE, FOREIGN_TOL_POINTS = 0.15, 5.0, 1.5, 0.4
# 改修前（球団生成 seed 1〜300、PYTHONHASHSEED=0、main 014b31a。PC で測った）の値。表示用。
FOREIGN_BEFORE: dict[str, Any] = {
    "投手": {
        "相関": {"回復_先発": 0.03, "回復_救援": 0.05, "打たれ強さ_先発": -0.06, "打たれ強さ_救援": 0.06},
        "割合": {
            "クイック": {"A": 0.4, "B": 0.6, "C": 1.6, "D": 34.9, "E": 48.0, "F": 10.7, "G": 3.8},
            "回復": {"A": 5.6, "B": 14.0, "C": 26.0, "D": 44.0, "E": 8.6, "F": 1.3, "G": 0.6},
            "ノビ": {"A": 3.2, "B": 13.2, "C": 27.1, "D": 28.5, "E": 17.7, "F": 7.1, "G": 3.1},
            "打たれ強さ": {"A": 0.6, "B": 4.8, "C": 20.4, "D": 62.7, "E": 10.3, "F": 0.9, "G": 0.3},
            "対ピンチ": {"A": 0.4, "B": 1.9, "C": 14.8, "D": 58.4, "E": 20.5, "F": 3.6, "G": 0.4},
            "対左打者": {"A": 0.9, "B": 3.5, "C": 15.1, "D": 43.6, "E": 27.2, "F": 8.0, "G": 1.8},
            "ケガしにくさ": {"A": 1.5, "B": 3.6, "C": 11.9, "D": 48.4, "E": 22.5, "F": 10.2, "G": 2.0},
        },
        "ランク点": -1.02,
    },
    "野手": {
        "相関": {"回復_野手": 0.04, "送球_野手": -0.01},
        "割合": {
            "走塁": {"A": 1.0, "B": 6.0, "C": 17.3, "D": 71.8, "E": 2.9, "F": 0.6, "G": 0.3},
            "送球": {"A": 0.3, "B": 0.5, "C": 5.2, "D": 34.9, "E": 43.0, "F": 13.6, "G": 2.5},
            "盗塁": {"A": 0.3, "B": 1.9, "C": 7.3, "D": 55.7, "E": 23.5, "F": 8.6, "G": 2.6},
            "対左投手": {"A": 4.0, "B": 10.0, "C": 20.3, "D": 31.6, "E": 22.1, "F": 9.0, "G": 2.9},
            "チャンス": {"A": 2.7, "B": 6.4, "C": 18.2, "D": 48.8, "E": 16.0, "F": 5.7, "G": 2.1},
            "ケガしにくさ": {"A": 0.1, "B": 1.0, "C": 8.7, "D": 51.7, "E": 26.4, "F": 7.5, "G": 4.6},
            "回復": {"A": 1.9, "B": 8.4, "C": 15.9, "D": 47.1, "E": 19.6, "F": 5.4, "G": 1.7},
            "キャッチャー": {"A": 0.1, "B": 0.2, "C": 1.0, "D": 97.9, "E": 0.6, "F": 0.2, "G": 0.0},
        },
        "ランク点": -3.37,
    },
}
FOREIGN_SECTIONS = {
    "corr": "能力とランク特能の結びつき（外国人）: 能力の合成値とランクの点の相関（目標は日本人と外国人の実在の平均±0.15）",
    "share": "能力とランク特能の結びつき（外国人）: ランクの割合（%。B〜F は実在の外国人±5ポイント、A・G は各1.5%以下）",
    "points": "能力とランク特能の結びつき（外国人）: ランク点の平均（実在の外国人±0.4）",
}


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


def load_real_rows(foreign: bool = False) -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人（foreign=True なら外国人）。元データ（data/raw/ の zip と 2026年版のフォルダ）から読む。
    外国人はランク特能を全部（FOREIGN_GROUPS）の列にし、ランク点（generator.rating.ranked_points）も持つ。"""
    import build_real_team_reference as ref
    from generator import real_data
    from generator.rating import ranked_points

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
                if bool(row.get("is_foreign")) != foreign:
                    continue
                ranked = {name[:-1]: name for name, kind in row.get("specials") or [] if kind == "rank"}
                role = "投手" if row.get("role") == "投手" else "野手"
                rows.append({
                    "season": season, "name": "".join(str(row.get("name") or "").split()), "role": role,
                    "position": str(row.get("main_position") or ""),
                    "prole": "先発" if str(row.get("pitcher_roles") or "")[:1] == "先" else "救援",
                    **{name: pd.to_numeric(row.get(REAL_ABILITY_COLUMNS[name]), errors="coerce") for name in ABILITIES[role]},
                    **(foreign_letter_columns(ranked, role) if foreign else letter_columns(ranked, role)),
                    **({"rank_points": ranked_points(ranked, role)} if foreign else {}),
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
                 "能力の合成値は「平均・SD」で標準化した能力の平均。割合は%。異なる選手の数は名前で数えた（誤差に使う）。"
                 "「外国人」は実在の外国人（2024〜2026年版）で、平均・SDは投手は先発・救援ごと、野手は全体。割合は全ランク特能、"
                 "ランク点は generator.rating.ranked_points の平均",
        "平均・SD": stats,
        "実在": parts,
        "外国人": build_foreign_real(),
    }
    REAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_PATH}（{len(rows)}人）")


def _real() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 助っ人外国人用
# ---------------------------------------------------------------------------
def foreign_letter_columns(ranked: dict[str, str], role: str) -> dict[str, str]:
    """1人分の全ランク特能の文字の列（rk_項目）。持たない項目は D。"""
    return {f"rk_{group}": letter_of(ranked, group) for group in FOREIGN_GROUPS[role]}


def foreign_part_statistics(frame: pd.DataFrame, key: str, stats: dict[str, dict[str, list[float]]]) -> dict[str, Any]:
    """外国人の区分のランクの割合（%）と、ランクの点と能力の合成値の相関。"""
    _label, role, group, members, abilities, stats_key, _jp = FOREIGN_PARTS[key]
    part = part_rows(frame[frame["role"] == role], role, members)
    scores = part[f"rk_{group}"].map(SCORES).astype(float)
    return {"相関": round(correlation(scores, composite(part, abilities, stats[stats_key])), 4), "人数": int(len(part))}


def foreign_shares(frame: pd.DataFrame, role: str) -> dict[str, dict[str, float]]:
    """役割の全ランク特能の割合（%。A〜G）。"""
    part = frame[frame["role"] == role]
    return {group: {letter: round(float((part[f"rk_{group}"] == letter).mean() * 100), 2) for letter in LETTERS} for group in FOREIGN_GROUPS[role]}


def build_foreign_real() -> dict[str, Any]:
    rows = load_real_rows(foreign=True)
    stats: dict[str, dict[str, list[float]]] = {}
    for key, (role, members) in FOREIGN_STATS_PARTS.items():
        part = part_rows(rows[rows["role"] == role], role, members)
        stats[key] = {name: [round(float(part[name].mean()), 4), round(float(part[name].std()), 4)] for name in ABILITIES[role]}
    parts = {}
    for key, (_label, role, _group, members, _abilities, _stats_key, _jp) in FOREIGN_PARTS.items():
        part = part_rows(rows[rows["role"] == role], role, members)
        parts[key] = {**foreign_part_statistics(part, key, stats), "異なる選手の数": int(part["name"].nunique())}
    out: dict[str, Any] = {"平均・SD": stats, "実在": parts, "割合": {}, "ランク点": {}}
    for role in ("投手", "野手"):
        part = rows[rows["role"] == role]
        out["割合"][role] = {**foreign_shares(rows, role), "異なる選手の数": int(part["name"].nunique())}
        out["ランク点"][role] = {"平均": round(float(part["rank_points"].mean()), 4), "SD": round(float(part["rank_points"].std()), 4),
                               "人数": int(len(part)), "異なる選手の数": int(part["name"].nunique())}
    return out


def foreign_real_reference() -> dict[str, Any]:
    return _real()["外国人"]


def foreign_corr_target(key: str) -> tuple[float, float]:
    """相関の目標（日本人の実在と外国人の実在の平均）と、その誤差（両方の誤差を合わせて半分）。"""
    real, foreign = real_reference(), foreign_real_reference()["実在"]
    jp, fr = real[FOREIGN_PARTS[key][6]], foreign[key]
    se = lambda r: (1 - r["相関"] ** 2) / math.sqrt(r["異なる選手の数"] - 1)  # noqa: E731
    return (jp["相関"] + fr["相関"]) / 2, math.hypot(se(jp), se(fr)) / 2


def foreign_statistics(frame: pd.DataFrame, role: str) -> dict[str, Any]:
    """生成の外国人の、区分ごとの相関、全ランク特能の割合、ランク点の平均。frame は rk_項目・能力・rank_points・prole の列を持つ。"""
    stats = foreign_real_reference()["平均・SD"]
    corr = {key: foreign_part_statistics(frame, key, stats)["相関"] for key, v in FOREIGN_PARTS.items() if v[1] == role}
    part = frame[frame["role"] == role]
    return {"相関": corr, "割合": foreign_shares(frame, role), "ランク点": float(part["rank_points"].mean())}


def foreign_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str, role: str) -> None:
    """外国人の相関（6区分のうち role の分）、ランクの割合（B〜F・A・G）、ランク点。"""
    from checklib import KIND_DESIGN, KIND_INFO

    real, now = foreign_real_reference(), foreign_statistics(frame, role)
    for key, value in now["相関"].items():
        target, _se = foreign_corr_target(key)
        fr = real["実在"][key]
        checks.add(f"{prefix}.rank_ability.{key}_corr", kind, f"{FOREIGN_PARTS[key][0]} 能力との相関", value,
                   round(target - FOREIGN_TOL_CORR, 4), round(target + FOREIGN_TOL_CORR, 4), section=FOREIGN_SECTIONS["corr"],
                   shown="nan" if math.isnan(value) else f"{value:+.2f}",
                   target=f"{target - FOREIGN_TOL_CORR:+.2f}〜{target + FOREIGN_TOL_CORR:+.2f}",
                   real=f"{target:+.2f}（外国人 {fr['相関']:+.2f}・{fr['異なる選手の数']}人、日本人 {real_reference()[FOREIGN_PARTS[key][6]]['相関']:+.2f}）")
    for group, shares in now["割合"].items():
        for letter in LETTERS:
            value, rv = shares[letter], real["割合"][role][group][letter]
            if letter in CHECKED_LETTERS:
                low, high = round(rv - FOREIGN_TOL_SHARE, 2), round(rv + FOREIGN_TOL_SHARE, 2)
                checks.add(f"{prefix}.rank_ability.share_{group}_{letter}", kind, f"{group} {letter}の割合", value, low, high,
                           section=FOREIGN_SECTIONS["share"], shown=f"{value:.1f}", target=f"{low:.1f}〜{high:.1f}", real=f"{rv:.1f}")
            else:
                checks.add(f"{prefix}.rank_ability.share_{group}_{letter}", KIND_INFO if kind == KIND_INFO else KIND_DESIGN,
                           f"{group} {letter}の割合", value, None, FOREIGN_MAX_EDGE, section=FOREIGN_SECTIONS["share"],
                           shown=f"{value:.1f}", target=f"{FOREIGN_MAX_EDGE:g}以下", real=f"{rv:.1f}")
    value, rv = now["ランク点"], real["ランク点"][role]["平均"]
    checks.add(f"{prefix}.rank_ability.rank_points", kind, "ランク点の平均", value, round(rv - FOREIGN_TOL_POINTS, 4), round(rv + FOREIGN_TOL_POINTS, 4),
               section=FOREIGN_SECTIONS["points"], shown=f"{value:+.2f}", target=f"{rv - FOREIGN_TOL_POINTS:+.2f}〜{rv + FOREIGN_TOL_POINTS:+.2f}", real=f"{rv:+.2f}")


def foreign_real_errors(prefix: str, role: str) -> dict[str, float]:
    """外国人の判定の実在側の誤差。人数は異なる選手の数。相関は日本人と外国人の誤差を合わせて半分。"""
    real = foreign_real_reference()
    se: dict[str, float] = {}
    for key, v in FOREIGN_PARTS.items():
        if v[1] == role:
            se[f"{prefix}.rank_ability.{key}_corr"] = foreign_corr_target(key)[1]
    n = real["割合"][role]["異なる選手の数"]
    for group in FOREIGN_GROUPS[role]:
        for letter in CHECKED_LETTERS:
            se[f"{prefix}.rank_ability.share_{group}_{letter}"] = share_se(real["割合"][role][group][letter], n)
    points = real["ランク点"][role]
    se[f"{prefix}.rank_ability.rank_points"] = points["SD"] / math.sqrt(points["異なる選手の数"])
    return se


def foreign_frame(players: list[dict[str, Any]]) -> pd.DataFrame:
    """生成の外国人（dict）を、foreign_checks に渡す表にする。"""
    from generator import team_analysis as ta
    from generator.rating import ranked_points

    rows = []
    for player in players:
        role = "投手" if player.get("role") == "投手" else "野手"
        abilities = player.get("abilities") if isinstance(player.get("abilities"), dict) else {}
        ranked = abilities.get("ranked_specials") or {}
        rows.append({
            "role": role, "position": str(player.get("position") or ""),
            "prole": "先発" if str(player.get("position") or "") == "先発" else "救援",
            **{name: ta._number(abilities.get(name)) for name in ABILITIES[role]},
            **foreign_letter_columns(ranked, role), "rank_points": ranked_points(ranked, role),
        })
    return pd.DataFrame(rows)


def print_foreign_reference(frame: pd.DataFrame, role: str) -> None:
    """外国人の相関・ランクの割合・ランク点（改修前・今回・実在。参考）。"""
    real, now = foreign_real_reference(), foreign_statistics(frame, role)
    before = FOREIGN_BEFORE.get(role, {})
    rows = [{"区分": FOREIGN_PARTS[key][0], "改修前": before.get("相関", {}).get(key), "今回": round(value, 2),
             "目標": round(foreign_corr_target(key)[0], 2), "外国人の実在": round(real["実在"][key]["相関"], 2)}
            for key, value in now["相関"].items()]
    print(f"\n[能力とランク特能の結びつき 外国人{role}（相関。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))
    rows = []
    for group, shares in now["割合"].items():
        for name, values in [("改修前", before.get("割合", {}).get(group)), ("今回", shares), ("実在", real["割合"][role][group])]:
            if values:
                rows.append({"ランク特能": group, "": name, **{x: round(float(values[x]), 1) for x in LETTERS}})
    print(f"[外国人{role}のランクの割合（%。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"[外国人{role}のランク点] 今回 {now['ランク点']:+.2f}（改修前 {before.get('ランク点', math.nan):+.2f}、実在 {real['ランク点'][role]['平均']:+.2f}）")


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
