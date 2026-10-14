"""
能力と特能の結びつきの判定の共通部分（`能力と特能の結びつき_改修指示.md` 2-1）。

- 架空球団用の日本人の、能力による特能の付け替え（app.py の fictional_ability_special_link）の対象の40特能について、
  能力の合成値 z で見た「持つ選手と持たない選手の差」、役割全体の保有率、能力の総合と特能の数（青・赤・緑）の相関を実在と比べる。
  check_special_profile.py が ability_checks で節を足す。
- 能力の標準化は rank_ability.py と同じ考え方で、実在の平均・SD を使う。ただし区分は、野手はメインのポジションごと、
  投手は先発・救援ごと（ポジションの差を二重に数えないため。指示書 0）。
  z = Σ w × (能力 − 平均) ÷ SD ÷ √(Σ w²)。重み w は app の表（data/config/fictional_ability_special_link.json）から読む。
  能力の総合 q は、投手は球速・コントロール・スタミナ・総変化量、野手はミート・パワー・走力・肩力・守備力・捕球の標準化した値の平均。
  投手の変化球数・総変化量は第一球種だけ数える（team_analysis._primary_breaking。check_pitcher_rank_pitches.py と同じ）。
- 実在は2024〜2026年版の日本人（ポジションはメイン、投手の役割は起用の最初の文字が「先」なら先発）。
  data/config/special_ability_link_real.json（`python scripts/special_ability_link.py --build-real` で実在の元データ data/raw/ から作る）。
  特能はランク特能・起用法・○○キラーを除く。
- 同じ選手が複数の年版に入っているので、実在側の誤差は異なる選手の数（名前で数える）で見積もる。
  差は √(SD持つ²/人数持つ + SD持たない²/人数持たない)、保有率は √(p(1−p)/人数)、相関は (1−r²)/√(人数−1)。
- 日本人の奪三振は、重みを総変化量だけにした（球速は帯の保有率で結びつけている。`能力との結びつき_外国人_改修指示.md` 1-5）。
  差の範囲は実在±0.2（TOL_DIFF_BY_NAME）。
- 助っ人外国人用（`能力との結びつき_外国人_改修指示.md` 2-1）: 表の区分「助っ人外国人用」の25特能について、差（目標±0.4）と
  役割全体の保有率（改修前±2ポイント）を、球団生成の外国人で判定する（check_foreign_balance.py が foreign_checks を呼ぶ）。
  能力は外国人の実在の平均・SD（投手は先発・救援ごと、野手は全ポジション同じ外国人の野手全体の値）で標準化する。
  目標は日本人の実在と外国人の実在の差の平均（外国人で持つ選手が異なる選手 FOREIGN_MIN_HOLDERS 人未満の特能は日本人の実在）。
  実在の外国人は special_ability_link_real.json の「外国人」（--build-real で一緒に作る）。
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from checklib import Checks  # noqa: E402

REAL_PATH = APP_DIR / "data" / "config" / "special_ability_link_real.json"
LINK_PATH = APP_DIR / "data" / "config" / "fictional_ability_special_link.json"
# app の表のうち、判定が使う区分（架空球団用の日本人）
LINK_PART = "架空球団用_日本人"
# 助っ人外国人用の区分
FOREIGN_PART = "助っ人外国人用"
# ドラフト候補用の区分
DRAFT_PART = "ドラフト候補用"
REAL_SEASONS = (2024, 2025, 2026)
ROLES = ("投手", "野手")
SEGMENTS = {"投手": ("先発", "救援"), "野手": ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")}
ABILITIES = {
    "投手": ("球速", "コントロール", "スタミナ", "変化球数", "総変化量"),
    "野手": ("弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"),
}
COLORS = (("n_blue", "青特"), ("n_red", "赤特"), ("n_green", "緑特"))
# 合格の範囲（指示書2-1）
TOL_DIFF, TOL_RATE_BEFORE, TOL_RATE_REAL, TOL_CORR = 0.4, 1.0, 3.0, 0.08
# 特能ごとの差の範囲（日本人の奪三振は総変化量だけの差で実在±0.2。`能力との結びつき_外国人_改修指示.md` 2-1）
TOL_DIFF_BY_NAME = {("投手", "奪三振"): 0.2}
# 外国人の合格の範囲（外国人の指示書2-1）と、目標に外国人の実在を使う最少の人数（持つ選手の異なる選手の数）
FOREIGN_TOL_DIFF, FOREIGN_TOL_RATE_BEFORE, FOREIGN_MIN_HOLDERS = 0.4, 2.0, 8
SECTIONS = {
    "diff": "能力と特能の結びつき: 能力の合成値 z で見た、持つ選手と持たない選手の差（実在±0.4。実在は2024〜2026年版の日本人）",
    "rate": "能力と特能の結びつき: 対象の特能の保有率（役割全体、%。改修前±1.0ポイント かつ 実在±3ポイント）",
    "corr": "能力と特能の結びつき: 能力の総合と特能の数の相関（実在±0.08）",
}
# 改修前（球団生成 seed 1〜300、PYTHONHASHSEED=0、main 88dfc00。PC で測った）の値。
# 保有率（%）は判定の範囲（改修前±1.0ポイント）に使う。差・相関は表示用。
# 奪三振の差は、重みを総変化量だけにしたので、PR #130 の後（main 014b31a）の生成を新しい重みで測った値（表示用）。
BEFORE: dict[str, Any] = {
    "差": {
        "投手": {"キレ○": 0.42, "ゴロピッチャー": 0.18, "テンポ○": 0.24, "ポーカーフェイス": 0.27, "乱調": 0.23, "力配分": 0.23, "変化球中心": 0.22, "奪三振": 0.12, "寸前": 0.34, "打球反応○": 0.28, "緊急登板○": 0.09, "緩急○": 0.45, "要所○": 0.62, "負け運": 0.22, "逃げ球": 0.88, "速球中心": -0.03},
        "野手": {"お祭り男": 0.22, "カット打ち": 0.69, "チームプレイ○": 0.21, "ハイボールヒッター": 0.44, "プルヒッター": 0.4, "ホーム死守": 0.38, "ホーム突入": 0.59, "マルチ弾": 0.72, "ミート多用": -0.02, "レーザービーム": 0.14, "三振": 0.09, "併殺": 0.32, "内野安打○": 0.95, "守備職人": 0.72, "対ストレート○": 0.4, "広角打法": 0.64, "強振多用": 0.12, "悪球打ち": 0.26, "意外性": 0.17, "決勝打": 0.61, "積極守備": 0.35, "積極盗塁": 0.83, "積極走塁": 0.3, "逆境○": 0.21},
    },
    "保有率": {
        "投手": {"キレ○": 14.1, "ゴロピッチャー": 5.7, "テンポ○": 7.3, "ポーカーフェイス": 5.6, "乱調": 3.6, "力配分": 4.4, "変化球中心": 13.6, "奪三振": 25.7, "寸前": 4.0, "打球反応○": 6.7, "緊急登板○": 8.1, "緩急○": 17.0, "要所○": 3.8, "負け運": 5.2, "逃げ球": 22.0, "速球中心": 12.1},
        "野手": {"お祭り男": 4.0, "カット打ち": 7.9, "チームプレイ○": 8.2, "ハイボールヒッター": 4.0, "プルヒッター": 6.6, "ホーム死守": 2.6, "ホーム突入": 3.8, "マルチ弾": 4.6, "ミート多用": 9.0, "レーザービーム": 1.5, "三振": 32.1, "併殺": 14.9, "内野安打○": 18.9, "守備職人": 2.3, "対ストレート○": 6.5, "広角打法": 4.8, "強振多用": 9.3, "悪球打ち": 4.3, "意外性": 4.0, "決勝打": 10.3, "積極守備": 16.2, "積極盗塁": 12.0, "積極走塁": 16.7, "逆境○": 5.9},
    },
    "相関": {
        "投手": {"n_blue": 0.45, "n_red": -0.1, "n_green": 0.09},
        "野手": {"n_blue": 0.5, "n_red": -0.03, "n_green": 0.23},
    },
}


@lru_cache(maxsize=4)
def link_table(part: str = LINK_PART) -> dict[str, Any]:
    """app の表（既定は区分 LINK_PART）。"""
    return json.loads(LINK_PATH.read_text(encoding="utf-8"))["区分"][part]


def segment_column(role: str) -> str:
    return "prole" if role == "投手" else "position"


# ---------------------------------------------------------------------------
# 1人分の能力の列
# ---------------------------------------------------------------------------
def pitch_columns(balls: Any, *, real: bool) -> dict[str, float]:
    from generator import team_analysis as ta

    primary = ta._primary_breaking(balls or [], real=real)
    return {"変化球数": float(len(primary)), "総変化量": float(sum(ta._movement(ball) for ball in primary))}


def generated_ability_columns(player: dict[str, Any]) -> dict[str, float]:
    """生成選手（dict）の能力の列（投手は球速・コントロール・スタミナ・変化球数・総変化量、野手は弾道と6能力）。"""
    from generator import team_analysis as ta

    abilities = player.get("abilities") if isinstance(player.get("abilities"), dict) else {}
    if player.get("role") == "投手":
        return {**{name: ta._number(abilities.get(name)) for name in ("球速", "コントロール", "スタミナ")},
                **pitch_columns(player.get("breaking_balls"), real=False)}
    return {name: ta._number(abilities.get(name)) for name in ABILITIES["野手"]}


def flag_columns(names: list[str], part: str = LINK_PART) -> dict[str, bool]:
    """対象の特能を持つかどうかの列（列名は特能の名前）。"""
    held = set(names)
    return {name: name in held for role in ROLES for name in link_table(part)["特能"][role]}


# ---------------------------------------------------------------------------
# 合成値・統計
# ---------------------------------------------------------------------------
def standardized(frame: pd.DataFrame, role: str, stats: dict[str, dict[str, list[float]]]) -> pd.DataFrame:
    """区分（野手はポジション、投手は先発・救援）ごとの実在の平均・SDで標準化した能力。区分の外の選手は NaN。"""
    column = segment_column(role)
    out = pd.DataFrame(index=frame.index, columns=list(ABILITIES[role]), dtype=float)
    for segment, table in stats.items():
        rows = frame[column] == segment
        for name, (mean, sd) in table.items():
            out.loc[rows, name] = (frame.loc[rows, name].astype(float) - mean) / sd
    return out


def composite(std: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    norm = math.sqrt(sum(w * w for w in weights.values()))
    return sum(w * std[name] for name, w in weights.items()) / norm


def quality(std: pd.DataFrame, names: list[str]) -> pd.Series:
    return std[list(names)].mean(axis=1, skipna=False)


def correlation(x: pd.Series, y: pd.Series) -> float:
    ok = x.notna() & y.notna()
    x, y = x[ok].astype(float).to_numpy(), y[ok].astype(float).to_numpy()
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return math.nan
    return float(np.corrcoef(x, y)[0, 1])


def role_statistics(frame: pd.DataFrame, role: str, stats: dict[str, dict[str, list[float]]], table: dict[str, Any],
                    names: pd.Series | None = None) -> dict[str, Any]:
    """役割の、特能ごとの差・保有率と、能力の総合と特能の数の相関。names（選手の名前）を渡すと異なる選手の数も数える。"""
    rows = frame[frame["role"] == role]
    std = standardized(rows, role, stats)
    out: dict[str, Any] = {"特能": {}, "相関": {}}
    for name, entry in table["特能"][role].items():
        z = composite(std, entry["w"])
        held = rows[name].astype(bool)
        ok = z.notna()
        z1, z0 = z[ok & held], z[ok & ~held]
        item = {
            "差": round(float(z1.mean() - z0.mean()), 4) if len(z1) and len(z0) else math.nan,
            "保有率": round(float(held.mean() * 100), 3), "人数": int(len(rows)),
            "SD持つ": round(float(z1.std()), 4) if len(z1) > 1 else math.nan, "SD持たない": round(float(z0.std()), 4) if len(z0) > 1 else math.nan,
        }
        if names is not None:
            item.update({"異なる選手の数": int(names[rows.index].nunique()),
                         "持つ（異なる選手の数）": int(names[z1.index].nunique()), "持たない（異なる選手の数）": int(names[z0.index].nunique())})
        out["特能"][name] = item
    q = quality(std, table["総合"][role])
    for column, _label in COLORS:
        out["相関"][column] = {"相関": round(correlation(q, rows[column]), 4)}
        if names is not None:
            out["相関"][column]["異なる選手の数"] = int(names[rows.index[q.notna()]].nunique())
    return out


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
REAL_ABILITY_COLUMNS = {
    "球速": "top_speed", "コントロール": "control", "スタミナ": "stamina",
    "弾道": "trajectory", "ミート": "contact", "パワー": "power", "走力": "run_speed", "肩力": "arm_strength", "守備力": "fielding", "捕球": "catching",
}


def load_real_rows(foreign: bool = False, rookie: bool = False) -> pd.DataFrame:
    """実在（2024〜2026年版）の日本人（foreign=True なら外国人）。元データ（data/raw/ の zip と 2026年版のフォルダ）から読む。
    rookie=True なら、2024〜2026年版で初めて出てきた日本人（プロ1年目。rank_ability.rookie_rows と同じ）だけにし、
    特能の列はドラフト候補用の表の特能にする。"""
    import rank_ability
    import build_real_team_reference as ref
    from generator import real_data
    from generator import team_analysis as ta

    kinds = ta.special_kind_map()
    foreign_keys = ref.foreign_list_keys(ref.DEFAULT_FOREIGN_LIST)
    entry = ref.load_entry_route(ref.DEFAULT_ENTRY_ROUTE)
    rows, seen = [], []
    with tempfile.TemporaryDirectory() as temp:
        folders = ref.extract_seasons(ref.DEFAULT_ZIP, Path(temp))
        folders[real_data.AGE_SEASON] = ref.DEFAULT_RAW_2026
        for season, folder in sorted(folders.items()):
            if season not in REAL_SEASONS and not (rookie and season >= rank_ability.ROOKIE_FIRST_SEASON):
                continue
            tables, _ = ref.parse_directory(folder)
            players = ref.decorate_season(tables["players"], season, foreign_keys, entry)
            for row in real_data.attach_real_details(players, tables["specials"], tables["breaking"]):
                seen.append((season, "".join(str(row.get("name") or "").split())))
                if bool(row.get("is_foreign")) != foreign or season not in REAL_SEASONS:
                    continue
                role = "投手" if row.get("role") == "投手" else "野手"
                specials = [name for name, kind in row.get("specials") or []
                            if kind not in ("rank", "usage") and not (name not in kinds and name.endswith("キラー"))]
                values = {name: pd.to_numeric(row.get(REAL_ABILITY_COLUMNS[name]), errors="coerce") for name in ABILITIES[role] if name in REAL_ABILITY_COLUMNS}
                if role == "投手":
                    values.update(pitch_columns(row.get("breaking_balls"), real=True))
                rows.append({
                    "season": season, "name": "".join(str(row.get("name") or "").split()), "role": role,
                    "position": str(row.get("main_position") or "") if role == "野手" else "投手",
                    "prole": ("先発" if str(row.get("pitcher_roles") or "")[:1] == "先" else "救援") if role == "投手" else None,
                    **values, **ta.special_counts(specials), **flag_columns(specials, DRAFT_PART if rookie else LINK_PART),
                })
    frame = pd.DataFrame(rows)
    return rank_ability.rookie_rows(frame, seen) if rookie else frame


def real_ability_stats(rows: pd.DataFrame) -> dict[str, dict[str, dict[str, list[float]]]]:
    """平均・SDの表（実在）。{役割: {区分: {能力: [平均, SD]}}}。"""
    out: dict[str, Any] = {}
    for role in ROLES:
        part = rows[rows["role"] == role]
        column = segment_column(role)
        out[role] = {
            segment: {name: [round(float(d[name].mean()), 4), round(float(d[name].std()), 4)] for name in ABILITIES[role]}
            for segment in SEGMENTS[role] for d in [part[part[column] == segment]]
        }
    return out


def foreign_real_ability_stats(rows: pd.DataFrame) -> dict[str, dict[str, dict[str, list[float]]]]:
    """外国人の平均・SDの表（実在）。投手は先発・救援ごと、野手は全体の値を全ポジションに置く。"""
    out: dict[str, Any] = {}
    for role in ROLES:
        part = rows[rows["role"] == role]
        if role == "投手":
            out[role] = {segment: {name: [round(float(d[name].mean()), 4), round(float(d[name].std()), 4)] for name in ABILITIES[role]}
                         for segment in SEGMENTS[role] for d in [part[part["prole"] == segment]]}
        else:
            whole = {name: [round(float(part[name].mean()), 4), round(float(part[name].std()), 4)] for name in ABILITIES[role]}
            out[role] = {segment: whole for segment in SEGMENTS[role]}
    return out


def build_real() -> None:
    rows = load_real_rows()
    stats = real_ability_stats(rows)
    table = link_table()
    foreign_rows = load_real_rows(foreign=True)
    foreign_stats = foreign_real_ability_stats(foreign_rows)
    foreign_table = link_table(FOREIGN_PART)
    rookie_rows = load_real_rows(rookie=True)
    draft_table = link_table(DRAFT_PART)
    data = {
        "作り方": "python scripts/special_ability_link.py --build-real。実在（2024〜2026年版）の日本人（外国人を除く）。ポジションはメイン、"
                 "投手の役割は起用の最初の文字が「先」なら先発（ほかは救援）。能力は区分（野手はポジション、投手は先発・救援）ごとの"
                 "「平均・SD」で標準化し、合成値 z は app の表（fictional_ability_special_link.json）の重みで作る。"
                 "特能はランク特能・起用法・○○キラーを除く。保有率は%。異なる選手の数は名前で数えた（誤差に使う）。"
                 "「外国人」は実在の外国人（2024〜2026年版）で、平均・SDは投手は先発・救援ごと、野手は全体（全ポジション同じ値）。"
                 "合成値 z は表の区分「助っ人外国人用」の重みで作る。「ドラフト候補」は実在のプロ1年目（2024〜2026年版で初めて出てきた日本人。"
                 "2022年版以降の名簿に同じ名前がない選手）を、表の区分「ドラフト候補用」の重みと平均・SD（ドラフト候補の生成の値）で見た参考の値"
                 "（判定の目標は日本人の実在）",
        "平均・SD": stats,
        "実在": {role: role_statistics(rows, role, stats[role], table, rows["name"]) for role in ROLES},
        "外国人": {
            "平均・SD": foreign_stats,
            "実在": {role: role_statistics(foreign_rows, role, foreign_stats[role], foreign_table, foreign_rows["name"]) for role in ROLES},
        },
        "ドラフト候補": {
            "実在": {role: role_statistics(rookie_rows, role, draft_table["平均・SD"][role], draft_table, rookie_rows["name"]) for role in ROLES},
        },
    }
    REAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_PATH}（{len(rows)}人）")


def _real() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))


def real_reference() -> dict[str, Any]:
    return _real()["実在"]


def ability_stats() -> dict[str, Any]:
    return _real()["平均・SD"]


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def statistics(frame: pd.DataFrame) -> dict[str, Any]:
    stats, table = ability_stats(), link_table()
    return {role: role_statistics(frame, role, stats[role], table) for role in ROLES}


def ability_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """特能ごとの差・保有率と、能力の総合と特能の数の相関。frame は能力・特能の列と、role・position・prole・n_blue などを持つ。"""
    from checklib import KIND_DESIGN, KIND_INFO

    real, now = real_reference(), statistics(frame)
    for role in ROLES:
        for name, item in now[role]["特能"].items():
            r = real[role]["特能"][name]
            value, rv = item["差"], r["差"]
            tol = TOL_DIFF_BY_NAME.get((role, name), TOL_DIFF)
            checks.add(f"{prefix}.ability_link.{role}_{name}_diff", kind, f"{role} {name} 持つ−持たない（z）", value, rv - tol, rv + tol,
                       section=SECTIONS["diff"], shown="nan" if math.isnan(value) else f"{value:+.2f}",
                       target=f"{rv - tol:+.2f}〜{rv + tol:+.2f}", real=f"{rv:+.2f}", direction="")
        for name, item in now[role]["特能"].items():
            r = real[role]["特能"][name]
            value, rv = item["保有率"], r["保有率"]
            low, high = max(0.0, rv - TOL_RATE_REAL), rv + TOL_RATE_REAL
            checks.add(f"{prefix}.ability_link.{role}_{name}_rate", kind, f"{role} {name} 保有率（実在±3）", value, low, high,
                       section=SECTIONS["rate"], shown=f"{value:.1f}", target=f"{low:.1f}〜{high:.1f}", real=f"{rv:.1f}")
            before = BEFORE.get("保有率", {}).get(role, {}).get(name)
            if before is not None:
                low, high = before - TOL_RATE_BEFORE, before + TOL_RATE_BEFORE
                checks.add(f"{prefix}.ability_link.{role}_{name}_rate_before", KIND_INFO if kind == KIND_INFO else KIND_DESIGN,
                           f"{role} {name} 保有率（改修前±1.0）", value, low, high, section=SECTIONS["rate"], shown=f"{value:.1f}",
                           target=f"{low:.1f}〜{high:.1f}（改修前 {before:.1f}）", real=f"{rv:.1f}")
        for column, label in COLORS:
            value, rv = now[role]["相関"][column]["相関"], real[role]["相関"][column]["相関"]
            checks.add(f"{prefix}.ability_link.corr_{role}_{column}", kind, f"{role} 能力の総合と{label}の数の相関", value, rv - TOL_CORR, rv + TOL_CORR,
                       section=SECTIONS["corr"], shown="nan" if math.isnan(value) else f"{value:+.2f}",
                       target=f"{rv - TOL_CORR:+.2f}〜{rv + TOL_CORR:+.2f}", real=f"{rv:+.2f}")


def share_se(share: float, n: int) -> float:
    p = share / 100
    return math.sqrt(max(p * (1 - p), 1e-6) / n) * 100 if n > 1 else math.nan


def real_errors(prefix: str) -> dict[str, float]:
    """実在側の誤差。人数は異なる選手の数。"""
    real = real_reference()
    se: dict[str, float] = {}
    for role in ROLES:
        for name, r in real[role]["特能"].items():
            n1, n0 = r["持つ（異なる選手の数）"], r["持たない（異なる選手の数）"]
            se[f"{prefix}.ability_link.{role}_{name}_diff"] = (math.sqrt(r["SD持つ"] ** 2 / n1 + r["SD持たない"] ** 2 / n0)
                                                               if n1 > 1 and n0 > 1 else math.nan)
            se[f"{prefix}.ability_link.{role}_{name}_rate"] = share_se(r["保有率"], r["異なる選手の数"])
        for column, _label in COLORS:
            r = real[role]["相関"][column]
            se[f"{prefix}.ability_link.corr_{role}_{column}"] = (1 - r["相関"] ** 2) / math.sqrt(r["異なる選手の数"] - 1)
    return se


def print_reference(frame: pd.DataFrame, before: bool = True) -> None:
    """特能ごとの差・保有率と相関（改修前・今回・実在。参考）。"""
    real, now = real_reference(), statistics(frame)
    for role in ROLES:
        rows = []
        for name, item in now[role]["特能"].items():
            r = real[role]["特能"][name]
            row = {"特能": name}
            if before and BEFORE:
                row["差 改修前"] = BEFORE.get("差", {}).get(role, {}).get(name)
            row.update({"差 今回": round(item["差"], 2), "差 実在": round(r["差"], 2)})
            if before and BEFORE:
                row["保有率 改修前"] = BEFORE.get("保有率", {}).get(role, {}).get(name)
            row.update({"保有率 今回": round(item["保有率"], 1), "保有率 実在": round(r["保有率"], 1)})
            rows.append(row)
        print(f"\n[能力と特能の結びつき {role}（差は能力の合成値 z の持つ−持たない、保有率は%。参考）]")
        print(pd.DataFrame(rows).to_string(index=False))
        corr = {label: f"{now[role]['相関'][c]['相関']:+.2f}（実在 {real[role]['相関'][c]['相関']:+.2f}"
                + (f"、改修前 {BEFORE['相関'][role][c]:+.2f}" if before and BEFORE.get("相関") else "") + "）" for c, label in COLORS}
        print(f"[{role} 能力の総合と特能の数の相関] " + "　".join(f"{k} {v}" for k, v in corr.items()))


# ---------------------------------------------------------------------------
# 助っ人外国人用
# ---------------------------------------------------------------------------
FOREIGN_SECTIONS = {
    "diff": "能力と特能の結びつき（外国人）: 能力の合成値 z で見た、持つ選手と持たない選手の差（目標±0.4。目標は日本人と外国人の実在の平均）",
    "rate": "能力と特能の結びつき（外国人）: 対象の特能の保有率（役割全体、%。改修前±2ポイント）",
}
# 改修前（球団生成 seed 1〜300、PYTHONHASHSEED=0、main 014b31a。PC で測った）の外国人の値。保有率（%）は判定の範囲に使う。差は表示用。
FOREIGN_BEFORE: dict[str, Any] = {
    "差": {
        "投手": {"キレ○": 0.0, "ゴロピッチャー": -0.01, "力配分": -0.17, "変化球中心": -0.13, "奪三振": 0.15, "打球反応○": 0.22, "負け運": -0.09, "逃げ球": -0.12, "速球中心": 0.33, "緩急○": -0.12},
        "野手": {"ハイボールヒッター": 0.13, "プルヒッター": -0.07, "マルチ弾": 0.95, "レーザービーム": 0.55, "三振": -0.0, "併殺": 0.39, "内野安打○": 0.8, "対ストレート○": 0.15, "広角打法": 0.1, "強振多用": 0.4, "決勝打": -0.06, "積極守備": -0.09, "積極盗塁": 1.06, "積極走塁": 0.42, "逆境○": 0.02},
    },
    "保有率": {
        "投手": {"キレ○": 14.4, "ゴロピッチャー": 14.1, "力配分": 3.8, "変化球中心": 13.2, "奪三振": 50.8, "打球反応○": 9.2, "負け運": 3.4, "逃げ球": 36.0, "速球中心": 11.4, "緩急○": 10.7},
        "野手": {"ハイボールヒッター": 5.0, "プルヒッター": 22.3, "マルチ弾": 18.5, "レーザービーム": 2.4, "三振": 70.6, "併殺": 30.3, "内野安打○": 3.6, "対ストレート○": 5.2, "広角打法": 19.3, "強振多用": 25.7, "決勝打": 23.3, "積極守備": 16.6, "積極盗塁": 3.5, "積極走塁": 22.3, "逆境○": 4.7},
    },
}


def foreign_real() -> dict[str, Any]:
    return _real()["外国人"]


def foreign_target(role: str, name: str) -> tuple[float, float, str]:
    """外国人の差の目標・その誤差・説明。外国人で持つ選手が FOREIGN_MIN_HOLDERS 人以上なら日本人と外国人の実在の平均
    （誤差は両方を合わせて半分）、それより少なければ日本人の実在。"""
    jp, fr = real_reference()[role]["特能"][name], foreign_real()["実在"][role]["特能"][name]

    def se(r: dict[str, Any]) -> float:
        n1, n0 = r["持つ（異なる選手の数）"], r["持たない（異なる選手の数）"]
        return math.sqrt(r["SD持つ"] ** 2 / n1 + r["SD持たない"] ** 2 / n0) if n1 > 1 and n0 > 1 else math.nan

    if fr["持つ（異なる選手の数）"] >= FOREIGN_MIN_HOLDERS:
        return (jp["差"] + fr["差"]) / 2, math.hypot(se(jp), se(fr)) / 2, f"外国人 {fr['差']:+.2f}・日本人 {jp['差']:+.2f} の平均"
    return jp["差"], se(jp), f"日本人 {jp['差']:+.2f}（外国人は持つ選手 {fr['持つ（異なる選手の数）']}人）"


def foreign_statistics(frame: pd.DataFrame, roles: tuple[str, ...] = ROLES) -> dict[str, Any]:
    stats, table = foreign_real()["平均・SD"], link_table(FOREIGN_PART)
    return {role: role_statistics(frame, role, stats[role], table) for role in roles}


def foreign_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str, role: str) -> None:
    """外国人の特能ごとの差（目標±0.4）と保有率（改修前±2ポイント）。frame は能力・特能の列と role・position・prole を持つ。"""
    from checklib import KIND_DESIGN, KIND_INFO

    now = foreign_statistics(frame, (role,))[role]
    for name, item in now["特能"].items():
        target, _se, text = foreign_target(role, name)
        value = item["差"]
        checks.add(f"{prefix}.ability_link.{name}_diff", kind, f"{name} 持つ−持たない（z）", value,
                   round(target - FOREIGN_TOL_DIFF, 4), round(target + FOREIGN_TOL_DIFF, 4), section=FOREIGN_SECTIONS["diff"],
                   shown="nan" if math.isnan(value) else f"{value:+.2f}",
                   target=f"{target - FOREIGN_TOL_DIFF:+.2f}〜{target + FOREIGN_TOL_DIFF:+.2f}", real=f"{target:+.2f}（{text}）")
    for name, item in now["特能"].items():
        before = FOREIGN_BEFORE.get("保有率", {}).get(role, {}).get(name)
        if before is None:
            continue
        value, low, high = item["保有率"], round(before - FOREIGN_TOL_RATE_BEFORE, 3), round(before + FOREIGN_TOL_RATE_BEFORE, 3)
        checks.add(f"{prefix}.ability_link.{name}_rate_before", KIND_INFO if kind == KIND_INFO else KIND_DESIGN,
                   f"{name} 保有率（改修前±2）", value, low, high, section=FOREIGN_SECTIONS["rate"], shown=f"{value:.1f}",
                   target=f"{low:.1f}〜{high:.1f}（改修前 {before:.1f}）",
                   real=f"{foreign_real()['実在'][role]['特能'][name]['保有率']:.1f}")


def foreign_real_errors(prefix: str, role: str) -> dict[str, float]:
    """外国人の差の目標の誤差（実在側）。"""
    return {f"{prefix}.ability_link.{name}_diff": foreign_target(role, name)[1] for name in link_table(FOREIGN_PART)["特能"][role]}


def foreign_frame(players: list[dict[str, Any]]) -> pd.DataFrame:
    """生成の外国人（dict）を、foreign_checks に渡す表にする。"""
    from generator import team_analysis as ta

    rows = []
    for player in players:
        role = "投手" if player.get("role") == "投手" else "野手"
        position = str(player.get("position") or "")
        names = [str(name) for name in player.get("special_abilities") or []]
        rows.append({
            "role": role, "position": position if role == "野手" else "投手",
            "prole": ("先発" if position == "先発" else "救援") if role == "投手" else None,
            **generated_ability_columns({**player, "role": role}), **flag_columns(names, FOREIGN_PART), **ta.special_counts(names),
        })
    return pd.DataFrame(rows)


def print_foreign_reference(frame: pd.DataFrame, role: str) -> None:
    """外国人の特能ごとの差・保有率（改修前・今回・目標・実在。参考）。"""
    now = foreign_statistics(frame, (role,))[role]
    rows = []
    for name, item in now["特能"].items():
        fr = foreign_real()["実在"][role]["特能"][name]
        rows.append({"特能": name, "差 改修前": FOREIGN_BEFORE.get("差", {}).get(role, {}).get(name), "差 今回": round(item["差"], 2),
                     "差 目標": round(foreign_target(role, name)[0], 2), "差 外国人の実在": round(fr["差"], 2),
                     "保有率 改修前": FOREIGN_BEFORE.get("保有率", {}).get(role, {}).get(name), "保有率 今回": round(item["保有率"], 1),
                     "保有率 外国人の実在": round(fr["保有率"], 1)})
    print(f"\n[能力と特能の結びつき 外国人{role}（差は能力の合成値 z の持つ−持たない、保有率は%。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))


# ---------------------------------------------------------------------------
# ドラフト候補用（`能力との結びつき_ドラフト_改修指示.md` 2-1）
# ---------------------------------------------------------------------------
DRAFT_SECTIONS = {
    "diff": "能力と特能の結びつき（ドラフト候補）: 能力の合成値 z で見た、持つ選手と持たない選手の差（日本人の実在±0.4。能力はドラフト候補の生成の平均・SDで標準化）",
    "rate": "能力と特能の結びつき（ドラフト候補）: 対象の特能の保有率（役割全体、%。改修前±1.5ポイント）",
}
DRAFT_TOL_DIFF, DRAFT_TOL_RATE_BEFORE = 0.4, 1.5
# 改修前（ドラフト候補 投手・野手 各5000人（seed 1〜5000）のうち育成候補を除く選手、PYTHONHASHSEED=0、main 17a94b5。PC で測った）の値。
# 保有率（%）は判定の範囲に使う。差は表示用。
DRAFT_BEFORE: dict[str, Any] = {
    "差": {
        "投手": {"キレ○": 0.42, "乱調": 0.25, "変化球中心": 0.07, "奪三振": 0.08, "寸前": 0.04, "打球反応○": 0.19, "緊急登板○": -0.27, "緩急○": 0.15, "負け運": 0.16, "逃げ球": 0.4, "速球中心": 0.06, "テンポ○": 0.14},
        "野手": {"チームプレイ○": 0.23, "ミート多用": -0.04, "三振": 0.24, "併殺": 0.11, "内野安打○": 0.98, "強振多用": 0.06, "積極守備": 0.34, "積極盗塁": 0.74, "積極走塁": 0.63},
    },
    "保有率": {
        "投手": {"キレ○": 3.2, "乱調": 2.5, "変化球中心": 6.0, "奪三振": 15.6, "寸前": 4.1, "打球反応○": 5.7, "緊急登板○": 4.2, "緩急○": 9.9, "負け運": 3.9, "逃げ球": 5.0, "速球中心": 6.7, "テンポ○": 6.8},
        "野手": {"チームプレイ○": 4.8, "ミート多用": 8.0, "三振": 20.9, "併殺": 3.4, "内野安打○": 16.0, "強振多用": 7.6, "積極守備": 8.2, "積極盗塁": 7.2, "積極走塁": 8.0},
    },
}


def draft_statistics(frame: pd.DataFrame, roles: tuple[str, ...] = ROLES) -> dict[str, Any]:
    table = link_table(DRAFT_PART)
    return {role: role_statistics(frame, role, table["平均・SD"][role], table) for role in roles}


def draft_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str, role: str) -> None:
    """ドラフト候補の特能ごとの差（日本人の実在±0.4）と保有率（改修前±1.5ポイント）。frame は能力・特能の列と role・position・prole を持つ。"""
    from checklib import KIND_DESIGN, KIND_INFO

    real, now = real_reference(), draft_statistics(frame, (role,))[role]
    for name, item in now["特能"].items():
        value, rv = item["差"], real[role]["特能"][name]["差"]
        checks.add(f"{prefix}.ability_link.{name}_diff", kind, f"{name} 持つ−持たない（z）", value,
                   round(rv - DRAFT_TOL_DIFF, 4), round(rv + DRAFT_TOL_DIFF, 4), section=DRAFT_SECTIONS["diff"],
                   shown="nan" if math.isnan(value) else f"{value:+.2f}",
                   target=f"{rv - DRAFT_TOL_DIFF:+.2f}〜{rv + DRAFT_TOL_DIFF:+.2f}", real=f"{rv:+.2f}（日本人）")
    for name, item in now["特能"].items():
        before = DRAFT_BEFORE.get("保有率", {}).get(role, {}).get(name)
        if before is None:
            continue
        value, low, high = item["保有率"], round(before - DRAFT_TOL_RATE_BEFORE, 3), round(before + DRAFT_TOL_RATE_BEFORE, 3)
        checks.add(f"{prefix}.ability_link.{name}_rate_before", KIND_INFO if kind == KIND_INFO else KIND_DESIGN,
                   f"{name} 保有率（改修前±1.5）", value, low, high, section=DRAFT_SECTIONS["rate"], shown=f"{value:.1f}",
                   target=f"{low:.1f}〜{high:.1f}（改修前 {before:.1f}）", real=f"{real[role]['特能'][name]['保有率']:.1f}（日本人）")


def draft_real_errors(prefix: str, role: str) -> dict[str, float]:
    """ドラフト候補の差の目標（日本人の実在）の誤差。"""
    se = real_errors(prefix)
    return {f"{prefix}.ability_link.{name}_diff": se[f"{prefix}.ability_link.{role}_{name}_diff"] for name in link_table(DRAFT_PART)["特能"][role]}


def draft_columns(player: dict[str, Any]) -> dict[str, Any]:
    """生成のドラフト候補（dict）1人分の、draft_checks に使う列（能力・対象の特能を持つかどうか）。"""
    names = [str(name) for name in player.get("special_abilities") or []]
    held = set(names)
    role = "投手" if player.get("role") == "投手" else "野手"
    from generator import team_analysis as ta

    return {**generated_ability_columns({**player, "role": role}),
            **{name: name in held for r in ROLES for name in link_table(DRAFT_PART)["特能"][r]}, **ta.special_counts(names)}


def print_draft_reference(frame: pd.DataFrame, role: str) -> None:
    """ドラフト候補の特能ごとの差・保有率（改修前・今回・目標。参考）。"""
    real, now = real_reference(), draft_statistics(frame, (role,))[role]
    rows = [{"特能": name, "差 改修前": DRAFT_BEFORE.get("差", {}).get(role, {}).get(name), "差 今回": round(item["差"], 2),
             "差 目標（日本人の実在）": round(real[role]["特能"][name]["差"], 2),
             "保有率 改修前": DRAFT_BEFORE.get("保有率", {}).get(role, {}).get(name), "保有率 今回": round(item["保有率"], 1)}
            for name, item in now["特能"].items()]
    print(f"\n[能力と特能の結びつき ドラフト候補{role}（差は能力の合成値 z の持つ−持たない、保有率は%。参考）]")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    if "--build-real" in sys.argv[1:]:
        build_real()
    else:
        print("使い方: python scripts/special_ability_link.py --build-real   # data/config/special_ability_link_real.json を作り直す")
