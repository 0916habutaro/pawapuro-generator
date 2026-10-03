"""実在球団（2022〜2026年版パワプロ）のデータの読み込みと、査定用の変換。

- 球団単位の集計 data/reference/real_team_stats_2022_2026.csv（コミットする。アプリの実在比較はこれだけで動く）
- 選手単位のデータ local_data/real_players_2022_2026.csv（コミットしない。あれば分布図に使う）

どちらも scripts/build_real_team_reference.py で作る。Streamlit には依存しない。
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

APP_DIR = Path(__file__).resolve().parents[1]
REAL_TEAM_STATS_PATH = APP_DIR / "data" / "reference" / "real_team_stats_2022_2026.csv"
REAL_PLAYERS_PATH = APP_DIR / "local_data" / "real_players_2022_2026.csv"
REAL_SEASONS = (2022, 2023, 2024, 2025, 2026)
# 比較の既定の年版。2022・2023年版はミートの基準が違う（約37。2024年版以降は約42）ため外す
DEFAULT_SEASONS = (2024, 2025, 2026)
DEFAULT_SEASONS_NOTE = "既定は2024〜2026年版（2022・2023年版はミートの基準が違うため）"
# 年齢・プロ年数・入団経路が分かるのは2026年版だけ
AGE_SEASON = 2026
# 集計ファイルのうち、球団ではなく実在の全選手から求めた値（査定帯の境界など）の行の season
GLOBAL_SEASON = 0

# 変化球のうち査定・球種数に数える行（scripts/compare_real_and_generated_balance.py と同じ条件）
USABLE_BREAKING_STATUS = ("ok", "corrected_by_direction_filter")


def usable_breaking_rows(breaking: pd.DataFrame) -> pd.DataFrame:
    """査定に使う変化球の行（通常の変化球は方向の判定が取れたものだけ、第二ストレートは全部）。"""
    kind = breaking["kind"].fillna("breaking").astype(str)
    status = breaking["status"].fillna("ok").astype(str)
    return breaking[(kind.eq("breaking") & status.isin(list(USABLE_BREAKING_STATUS))) | kind.eq("second_fastball")]


def attach_real_details(players: pd.DataFrame, specials: pd.DataFrame, breaking: pd.DataFrame) -> list[dict[str, Any]]:
    """1つの年版の選手に、特殊能力（(名前, 種類) の並び）と変化球（kind・movement・slot）を付けて dict の並びにする。

    球団＋登録名で結び付けるので、年版ごとに呼ぶ。
    """
    special_map: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in specials.itertuples():
        special_map[(row.team, row.name)].append((str(row.special), str(row.special_kind)))
    ball_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in usable_breaking_rows(breaking).itertuples():
        movement = pd.to_numeric(row.movement, errors="coerce")
        slot = pd.to_numeric(getattr(row, "slot", 1), errors="coerce")
        ball_map[(row.team, row.name)].append({
            "kind": str(row.kind),
            "movement": 0 if pd.isna(movement) else int(movement),
            "slot": 1 if pd.isna(slot) else int(slot),
        })
    rows = []
    for row in players.to_dict("records"):
        key = (row["team"], row["name"])
        rows.append({**row, "specials": special_map.get(key, []), "breaking_balls": ball_map.get(key, [])})
    return rows


def real_player_to_rating_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    """実在選手の1行（attach_real_details の結果）を、generator/rating.py の player_rating で査定できる dict にする。

    ランク付きの特殊能力（special_kind == "rank"）は ranked_specials に、それ以外（通常・緑・起用法）は
    special_abilities に入れる（validate_team_mode.py の従来の変換と同じ）。
    """
    ranked: dict[str, str] = {}
    normal: list[str] = []
    for name, special_kind in row.get("specials") or []:
        if special_kind == "rank":
            ranked[name[:-1]] = name
        else:
            normal.append(name)
    balls = [{"kind": ball["kind"], "movement": ball["movement"]} for ball in row.get("breaking_balls") or []]
    if row.get("role") == "投手":
        roles = str(row.get("pitcher_roles") or "")
        marks = {label: ("◎" if index == 0 else "○") for index, label in enumerate(roles)}
        abilities = {"球速": row.get("top_speed"), "コントロール": {"value": row.get("control")}, "スタミナ": {"value": row.get("stamina")}, "ranked_specials": ranked}
        return {
            "role": "投手", "abilities": abilities, "special_abilities": normal, "breaking_balls": balls,
            "starter_aptitude": marks.get("先", "-"), "reliever_aptitude": marks.get("中", "-"), "closer_aptitude": marks.get("抑", "-"),
            "sub_positions": [{"position": p, "aptitude": "○"} for p in str(row.get("sub_positions")).split(";") if p and p != "nan"],
        }
    abilities = {"弾道": row.get("trajectory"), "ranked_specials": ranked}
    for label, column in (("ミート", "contact"), ("パワー", "power"), ("走力", "run_speed"), ("肩力", "arm_strength"), ("守備力", "fielding"), ("捕球", "catching")):
        abilities[label] = {"value": row.get(column)}
    return {"role": "野手", "abilities": abilities, "special_abilities": normal}


# ---------------------------------------------------------------------------
# 構築済みファイルの読み込み
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _read_team_stats(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"team": str, "axis": str, "group": str, "metric": str})
    frame["season"] = frame["season"].astype(int)
    return frame


def load_real_team_stats(seasons: tuple[int, ...] | None = None, path: str | Path = REAL_TEAM_STATS_PATH) -> pd.DataFrame:
    """球団単位の集計（縦持ち: season, team, axis, group, metric, value, n）。seasons を渡すとその年版だけ。

    実在の全選手から求めた行（season == 0。査定帯の境界など）は含めない。それは rating_cut_rows で読む。
    """
    frame = _read_team_stats(str(path))
    frame = frame[frame["season"] != GLOBAL_SEASON]
    if seasons:
        frame = frame[frame["season"].isin([int(s) for s in seasons])]
    return frame.copy()


def load_global_stats(path: str | Path = REAL_TEAM_STATS_PATH) -> pd.DataFrame:
    frame = _read_team_stats(str(path))
    return frame[frame["season"] == GLOBAL_SEASON].copy()


@lru_cache(maxsize=4)
def _read_players(path: str, modified_ns: int) -> pd.DataFrame | None:
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"uniform_number": str, "name": str, "team": str})
    frame["uniform_number"] = frame["uniform_number"].fillna("").astype(str)
    frame["is_foreign"] = frame["is_foreign"].astype(str).str.lower().isin(["true", "1"])
    return frame


def load_real_players(seasons: Iterable[int] | None = None, path: str | Path = REAL_PLAYERS_PATH) -> pd.DataFrame | None:
    """選手単位の実在データ（正規化済み）。ファイルが無ければ None。"""
    path = Path(path)
    if not path.exists():
        return None
    frame = _read_players(str(path), path.stat().st_mtime_ns)
    if frame is None:
        return None
    if seasons:
        frame = frame[frame["season"].isin([int(s) for s in seasons])]
    return frame.copy()
