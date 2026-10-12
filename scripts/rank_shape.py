"""
ランク特能の形（ランクの散らばり方）の判定の共通部分（`ランク特能の形_改修指示.md` 2-1）。

- 架空球団用の日本人の、走塁・盗塁（捕手／一塁手・三塁手／二塁手・遊撃手・外野手）、ケガしにくさ（捕手・遊撃手／ほか）、
  チャンス（野手全体）、対ピンチ（先発・救援）の11区分について、ランクの割合（B〜F）とランク点を実在と比べる。
- 走塁・盗塁は check_fielder_speed.py、ケガしにくさ・チャンスは check_fielder_position.py、対ピンチは
  check_pitcher_rank_pitches.py が、この module の shape_checks で節を足す。
- 実在は2024〜2026年版の日本人（ポジションはメイン、役割は起用の最初の文字が「先」なら先発）。
  data/config/rank_shape_real.json（`python scripts/rank_shape.py --build-real` で実在の元データ data/raw/ から作る）。
- 同じ選手が複数の年版に入っているので、実在側の誤差は異なる選手の数（名前で数える）で見積もる。
  割合は √(p(1−p)/人数)、ランク点は 標準偏差/√人数。
- ランク特能を持たない項目は D として数える。ランク点は査定のランク点（D=0。generator/rating.py と同じ表）。
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

import pandas as pd  # noqa: E402

import checklib  # noqa: E402
from checklib import Checks  # noqa: E402
from generator.rating import load_table  # noqa: E402

REAL_PATH = APP_DIR / "data" / "config" / "rank_shape_real.json"
REAL_SEASONS = (2024, 2025, 2026)
LETTERS = ("A", "B", "C", "D", "E", "F", "G")
CHECKED_LETTERS = ("B", "C", "D", "E", "F")
FIELDER_GROUPS = ("走塁", "盗塁", "ケガしにくさ", "チャンス")
PITCHER_GROUPS = ("対ピンチ",)
RUN_PARTS = {"捕手": ("捕手",), "一三": ("一塁手", "三塁手"), "二遊外": ("二塁手", "遊撃手", "外野手")}
INJURY_PARTS = {"捕遊": ("捕手", "遊撃手"), "他": ("一塁手", "二塁手", "三塁手", "外野手")}
# 区分: 鍵 → (表示名, 投手/野手, ランク特能, ポジション（野手）または役割（投手）の一覧。None は全員)
SHAPES: dict[str, tuple[str, str, str, tuple[str, ...] | None]] = {
    **{f"走塁_{k}": (f"走塁 {label}", "野手", "走塁", RUN_PARTS[k]) for k, label in (("捕手", "捕手"), ("一三", "一塁手・三塁手"), ("二遊外", "二塁手・遊撃手・外野手"))},
    **{f"盗塁_{k}": (f"盗塁 {label}", "野手", "盗塁", RUN_PARTS[k]) for k, label in (("捕手", "捕手"), ("一三", "一塁手・三塁手"), ("二遊外", "二塁手・遊撃手・外野手"))},
    "ケガしにくさ_捕遊": ("ケガしにくさ 捕手・遊撃手", "野手", "ケガしにくさ", INJURY_PARTS["捕遊"]),
    "ケガしにくさ_他": ("ケガしにくさ ほか", "野手", "ケガしにくさ", INJURY_PARTS["他"]),
    "チャンス": ("チャンス（野手）", "野手", "チャンス", None),
    "対ピンチ_先発": ("対ピンチ 先発", "投手", "対ピンチ", ("先発",)),
    "対ピンチ_救援": ("対ピンチ 救援", "投手", "対ピンチ", ("救援",)),
}
SCRIPT_SHAPES = {
    "check_fielder_speed": [k for k in SHAPES if k.startswith(("走塁", "盗塁"))],
    "check_fielder_position": [k for k in SHAPES if k.startswith(("ケガしにくさ", "チャンス"))],
    "check_pitcher_rank_pitches": [k for k in SHAPES if k.startswith("対ピンチ")],
}
# 合格の範囲（指示書2-1）
TOL_SHARE, TOL_SHARE_D, TOL_POINTS = 4.0, 6.0, 0.3
# 改修前（球団生成 seed 1〜300、PYTHONHASHSEED=0、main b29bb39）の値（指示書0章）。表示用
BEFORE = {
    "走塁_捕手": ((0.9, 7.3, 27.0, 55.6, 8.6, 0.6, 0.0), 0.95),
    "走塁_一三": ((0.4, 9.8, 24.4, 57.8, 6.8, 0.7, 0.1), 1.01),
    "走塁_二遊外": ((0.6, 16.8, 38.6, 41.2, 2.4, 0.3, 0.1), 1.95),
    "盗塁_捕手": ((0.2, 3.1, 10.6, 61.9, 19.9, 4.1, 0.2), -0.44),
    "盗塁_一三": ((0.2, 3.0, 11.2, 58.3, 22.3, 5.1, 0.0), -0.57),
    "盗塁_二遊外": ((0.2, 3.9, 15.5, 57.3, 18.7, 4.2, 0.1), -0.13),
    "ケガしにくさ_捕遊": ((0.1, 2.0, 9.2, 57.9, 25.2, 5.5, 0.1), -0.66),
    "ケガしにくさ_他": ((0.0, 1.9, 9.5, 59.7, 23.0, 5.7, 0.1), -0.61),
    "チャンス": ((0.3, 5.9, 19.2, 56.5, 14.6, 3.6, 0.1), 0.37),
    "対ピンチ_先発": ((0.2, 4.3, 14.6, 60.4, 16.7, 3.6, 0.1), -0.03),
    "対ピンチ_救援": ((0.2, 4.5, 15.1, 60.8, 16.1, 3.2, 0.1), 0.06),
}
SECTION = "ランク特能の形（ランクの割合は%。B・C・E・Fは実在±4ポイント、Dは実在±6ポイント。ランク点は実在±0.3。実在は2024〜2026年版の日本人）"
SHAPE_COLUMNS = tuple(f"rk_{group}" for group in (*FIELDER_GROUPS, *PITCHER_GROUPS))


def letter_of(ranked: dict[str, str], group: str) -> str:
    letter = str((ranked or {}).get(group) or "D")[-1:]
    return letter if letter in LETTERS else "D"


def letter_columns(ranked: dict[str, str], role: str) -> dict[str, str]:
    """1人分のランクの文字の列（rk_項目）。持たない項目は D。"""
    groups = PITCHER_GROUPS if role == "投手" else FIELDER_GROUPS
    return {f"rk_{group}": letter_of(ranked, group) for group in groups}


def point_table(role: str) -> dict[str, dict[str, int]]:
    """ランク特能ごとの、ランクの文字 → 査定のランク点。"""
    t = load_table()
    out = {}
    for group in (PITCHER_GROUPS if role == "投手" else FIELDER_GROUPS):
        table = t["rank_table_major"] if group in t["ranked_major"][role] else t["rank_table_minor"]
        out[group] = {letter: int(table.get(letter, 0)) for letter in LETTERS}
    return out


def shape_part(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    """区分の選手。野手は列 position、投手は列 prole（先発・救援）で分ける。"""
    _label, role, _group, members = SHAPES[key]
    if members is None:
        return frame
    return frame[frame["prole" if role == "投手" else "position"].isin(members)]


def shape_statistics(frame: pd.DataFrame, key: str) -> dict[str, Any]:
    """区分のランクの割合（%）とランク点の [平均, 標準偏差, 人数]。"""
    _label, role, group, _members = SHAPES[key]
    part = shape_part(frame, key)
    letters = part[f"rk_{group}"]
    points = letters.map(point_table(role)[group]).astype(float)
    return {
        "割合": {letter: round(float((letters == letter).mean() * 100), 2) for letter in LETTERS},
        "ランク点": [round(float(points.mean()), 4), round(float(points.std()), 4), int(len(points))],
    }


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
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
                    **letter_columns(ranked, role),
                })
    return pd.DataFrame(rows)


def real_statistics(rows: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, (_label, role, _group, _members) in SHAPES.items():
        part = shape_part(rows[rows["role"] == role], key)
        out[key] = {**shape_statistics(part, key), "異なる選手の数": int(part["name"].nunique())}
    return out


def build_real() -> None:
    rows = load_real_rows()
    data = {
        "作り方": "python scripts/rank_shape.py --build-real。実在（2024〜2026年版）の日本人（外国人を除く）。ポジションはメイン、"
                 "投手の役割は起用の最初の文字が「先」なら先発（ほかは救援）。ランク点は査定のランク点（D=0、持たない項目はD）。"
                 "割合は%。ランク点は [平均, 標準偏差, 人数（延べ）]。異なる選手の数は名前で数えた（誤差に使う）",
        "実在": real_statistics(rows),
    }
    REAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_PATH}（{len(rows)}人）")


def real_reference() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))["実在"]


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def shape_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str, keys: list[str]) -> None:
    """区分ごとの B〜F の割合とランク点。frame は rk_項目 と position（野手）または prole（投手）を持つ。"""
    real = real_reference()
    for key in keys:
        label = SHAPES[key][0]
        now, r = shape_statistics(frame, key), real[key]
        for letter in CHECKED_LETTERS:
            value, rv = now["割合"][letter], r["割合"][letter]
            tol = TOL_SHARE_D if letter == "D" else TOL_SHARE
            low, high = rv - tol, rv + tol
            checks.add(f"{prefix}.rank_shape.{key}_{letter}", kind, f"{label} {letter}の割合", value, low, high, section=SECTION,
                       shown=f"{value:.1f}", target=f"{low:.1f}〜{high:.1f}", real=f"{rv:.1f}")
        value, rv = now["ランク点"][0], r["ランク点"][0]
        low, high = rv - TOL_POINTS, rv + TOL_POINTS
        checks.add(f"{prefix}.rank_shape.{key}_points", kind, f"{label} ランク点", value, low, high, section=SECTION,
                   shown=f"{value:+.2f}", target=f"{low:+.2f}〜{high:+.2f}", real=f"{rv:+.2f}（{r['異なる選手の数']}人）")


def share_se(share: float, n: int) -> float:
    p = share / 100
    return math.sqrt(p * (1 - p) / n) * 100 if n > 1 else math.nan


def real_errors(prefix: str, keys: list[str]) -> dict[str, float]:
    """実在側の誤差。人数は異なる選手の数。"""
    real = real_reference()
    se: dict[str, float] = {}
    for key in keys:
        r, n = real[key], real[key]["異なる選手の数"]
        for letter in CHECKED_LETTERS:
            se[f"{prefix}.rank_shape.{key}_{letter}"] = share_se(r["割合"][letter], n)
        se[f"{prefix}.rank_shape.{key}_points"] = r["ランク点"][1] / math.sqrt(n) if n > 1 else math.nan
    return se


def print_shape_reference(frame: pd.DataFrame, keys: list[str], before: bool = True) -> None:
    """区分ごとのランクの割合（%）とランク点（改修前・今回・実在。参考）。"""
    real = real_reference()
    rows = []
    for key in keys:
        now = shape_statistics(frame, key)
        lines = [("改修前", BEFORE[key][0], BEFORE[key][1])] if before else []
        lines += [("今回", [now["割合"][x] for x in LETTERS], now["ランク点"][0]),
                  ("実在", [real[key]["割合"][x] for x in LETTERS], real[key]["ランク点"][0])]
        for name, shares, points in lines:
            rows.append({"区分": SHAPES[key][0], "": name, **{x: round(float(v), 1) for x, v in zip(LETTERS, shares)}, "ランク点": round(float(points), 2)})
    print("\n[ランク特能の形（ランクの割合は%。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    if "--build-real" in sys.argv[1:]:
        build_real()
    else:
        print("使い方: python scripts/rank_shape.py --build-real   # data/config/rank_shape_real.json を作り直す")
