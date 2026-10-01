"""★査定値の計算（参考実装）。

パワプロ査定計算シート v1.3.0 の式を移植したもの。表は data/config/rating_table.json に置く。
保存データは変更せず、表示時に計算する。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
TABLE_PATH = APP_DIR / "data" / "config" / "rating_table.json"

# アプリの特殊能力名 → 査定表の名前
SPECIAL_ALIASES = {
    "対ランナー": "対ランナー○",
    "根性": "根性○",
    "投手存在感": "存在感",
    "野手存在感": "存在感",
    # アプリには種類（安打・本塁打・両方）がないため「両方」として扱う
    "満塁男": "満塁男(両方)",
    "サヨナラ男": "サヨナラ男(両方)",
    "野手調子安定": "調子安定",
    "野手調子極端": "調子極端",
    "投手調子安定": "調子安定",
    "投手調子極端": "調子極端",
    "投球位置左": "投手位置左",
    "投球位置右": "投手位置右",
}


@lru_cache(maxsize=1)
def load_table(path: str = str(TABLE_PATH)) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _value(item: Any) -> int | None:
    if isinstance(item, dict):
        item = item.get("value")
    if isinstance(item, (int, float)):
        return int(item)
    match = re.match(r"\s*(\d+)", str(item or ""))
    return int(match.group(1)) if match else None


def _abilities(player: dict[str, Any]) -> dict[str, Any]:
    a = player.get("abilities")
    return a if isinstance(a, dict) else {}


def ability_points(value: int, multiplier: float) -> int:
    """能力値 → 査定点。10刻みの表を線形補間し、切り捨ててから倍率をかけて切り捨てる。"""
    curve = load_table()["ability_curve"]
    value = max(0, min(100, int(value)))
    q, r = divmod(value, 10)
    raw = int((curve[q + 1] - curve[q]) / 10 * r + curve[q])
    return int(multiplier * raw)


def speed_points(speed: int) -> int:
    d = max(0, int(speed) - 120)
    q = d // 5
    return int(d * (2 + 0.6 * q) - 1.5 * q * (q + 1))


def ranked_points(ranked: dict[str, str], role: str) -> int:
    t = load_table()
    total = 0
    if not isinstance(ranked, dict):
        return 0
    for group, rank_name in ranked.items():
        rank_letter = str(rank_name)[-1:]
        if group in t["ranked_major"][role]:
            total += t["rank_table_major"].get(rank_letter, 0)
        elif group in t["ranked_minor"][role]:
            total += t["rank_table_minor"].get(rank_letter, 0)
    return total


def special_points(names: list[str], role: str) -> int:
    t = load_table()
    table = t["pitcher_specials"] if role == "投手" else t["fielder_specials"]
    return sum(table.get(SPECIAL_ALIASES.get(str(n), str(n)), 0) for n in names or [])


def breaking_ball_points(balls: list[dict[str, Any]]) -> int:
    """球種数と総変化量で表を引く。第二ストレートは変化量1の1球種として数える。"""
    count = total = 0
    for ball in balls or []:
        # 壊れたJSONの読み込み結果（文字列）などは数えない
        if not isinstance(ball, dict):
            continue
        if ball.get("kind") == "second_fastball":
            count += 1
            total += 1
        else:
            movement = int(ball.get("movement") or ball.get("level") or 0)
            if movement > 0:
                count += 1
                total += movement
    if total == 0:
        return 0
    return int(load_table()["breaking_ball_table"].get(str(count), {}).get(str(total), 0))


def fielder_rating(player: dict[str, Any]) -> int:
    t = load_table()
    a = _abilities(player)
    traj = max(0, min(4, int(_value(a.get("弾道")) or 0)))
    total = t["trajectory"][traj]
    for key, mult in t["fielder_multipliers"].items():
        v = _value(a.get(key))
        if v is not None:
            total += ability_points(v, mult)
    total += ranked_points(a.get("ranked_specials") or {}, "野手")
    total += special_points(player.get("special_abilities") or [], "野手")
    return total


def pitcher_rating(player: dict[str, Any]) -> int:
    t = load_table()
    a = _abilities(player)
    total = speed_points(_value(a.get("球速")) or 120)
    for key, mult in t["pitcher_multipliers"].items():
        v = _value(a.get(key))
        if v is not None:
            total += ability_points(v, mult)
    total += ranked_points(a.get("ranked_specials") or {}, "投手")
    for key in ("starter_aptitude", "reliever_aptitude", "closer_aptitude"):
        mark = str(player.get(key) or a.get(key) or "-")
        total += t["pitcher_aptitude"].get(mark, 0)
    total += breaking_ball_points(player.get("breaking_balls") or [])
    total += special_points(player.get("special_abilities") or [], "投手")
    return total


FIELDER_POSITIONS = {"捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"}


def two_way_factor(player: dict[str, Any]) -> float:
    """投手の野手サブポジションから二刀流の係数を決める（Excel：投手の野手サブポジ）。"""
    t = load_table()["two_way_factor"]
    subs = [s for s in player.get("sub_positions") or [] if isinstance(s, dict) and s.get("position") in FIELDER_POSITIONS]
    if not subs:
        return t["none"]
    if len(subs) >= 2:
        return t["sub2_or_more"]
    # アプリの △＝小、○＝中、◎＝大
    return t["sub1_small"] if str(subs[0].get("aptitude")) == "△" else t["sub1_mid_or_more"]


def player_rating(player: dict[str, Any]) -> int:
    if player.get("role") != "投手":
        return fielder_rating(player)
    pitcher = pitcher_rating(player)
    factor = two_way_factor(player)
    if factor == 0:
        return pitcher
    rate = load_table()["two_way_main_rate"]
    return int(pitcher * rate) + int(fielder_rating(player) * factor)
