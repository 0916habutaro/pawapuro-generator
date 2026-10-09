#!/usr/bin/env python3
"""架空球団用の日本人の青特の型の目標の表を作る（`青特の型_改修指示.md` 1-6）。

使い方:
    python scripts/build_fictional_special_profile.py                 # 球団生成300球団（seed 1〜300）で作って data/config/ に書く
    python scripts/build_fictional_special_profile.py --teams 60      # 途中確認用（書き込まない。--write を付ければ書く）
    python scripts/build_fictional_special_profile.py --no-correct     # 最後の1回の直しをしない
    python scripts/build_fictional_special_profile.py --green          # 緑特の型の表を作る（data/config/fictional_green_profile.json）
    python scripts/build_fictional_special_profile.py --pitchers-only --start-table docs/投手の役割と特能_試作表.json
        # 投手の表だけ作り直す（野手の表は data/config のまま）。直す前の目標 t は試作表から取る（c は今の生成で測る）

出力: data/config/fictional_special_profile.json
    "表"   {役割: {特能: {区分: [c, t]}}}  アプリ（app.py の fictional_special_profile_adjust）が読む。
           c = 青特の型の補正の前の保有率、t = 目標の保有率。区分は、投手は「左・右|先発・救援」（`投手の役割と特能_改修指示.md` 1-1）、
           野手は 「ポジション|左・右」（両打は右打）。
    "実在" 判定（scripts/check_special_profile.py）が使う、実在（2024〜2026年版の日本人）の青特の数・帯ごとの保有率。
           「役割」は、投手の先発・救援ごとの青特・赤特の数、特能の査定点、役割の差を見る特能の保有率、連動特能の帯 × 役割ごとの保有率。
    "作り方" 作ったときの条件（球団の範囲、実在の年版、縮め方の定数）。
出力（--green）: data/config/fictional_green_profile.json（緑特の型。`緑特の型_改修指示.md` 1-2）
    "表"   {役割: {特能: {区分: [c, t]}}}  アプリ（app.py の fictional_green_profile_adjust）が読む。
           区分は、投手は「左・右|先発・救援」、野手は「ポジション|左・右」。c は緑特の型の補正の前（青特の型の補正の後）の保有率。
    "実在" 判定（scripts/check_special_profile.py）が使う、実在の緑特の数と、対象の特能の役割・ポジションごとの保有率。

作り方（指示書 1-6）:
 1. 実在（2024〜2026年版の日本人）から、特能ごとに全体の保有率 r_all と区分ごとの保有率を出す。
 2. 区分ごとの倍率を人数で縮める: m = 1 + w × (r_区分 / r_all − 1)、w = n / (n + 60)。
    投手は 投げ手の倍率 × 役割（先発・救援）の倍率、野手は ポジションの倍率 × 打席の倍率。
 3. 目標 = 水準 × 倍率。生成の区分の人数の割合で平均したとき水準と同じになるようにそろえる。
    水準は、ふつうは生成の今の全体の保有率。投手の対ランナー（青）、野手のお祭り男・春男・夏男・秋男・プレッシャーランは実在の保有率。
    投手の赤の対ランナー×も水準を実在の保有率にする（区分が投げ手だけのときは、実在の投げ手ごとの保有率をそのまま目標にしていた）。
 4. 対象は青特（マスターの kind が red・green・gold 以外）で、ランク特能・起用法でないもの。実在で10人以上が持つもの。
    投手は赤特（kind が red）も対象にする（`投手の役割と特能_改修指示.md` 1-1。水準は生成の今の全体の保有率なので、赤特の数は変わらない）。
    FICTIONAL_LINKED_SPECIALS の特能（投手の四球・荒れ球など）と「実在にない特能」、○○キラーは除く。
 5. c は、青特の型の補正の前の生成（球団生成）で測る（補正を空にして流す）。
 6. 一度表を入れて流し、区分ごとの結果が目標からずれた分を目標に足し戻して1回だけ直す（t' = t + (t − 結果)、0〜1に収める）。

緑特の型の作り方（--green。`緑特の型_改修指示.md` 1-2）: 上の 1〜6 と同じ。違うのは次の点。
 - 対象は GREEN_SPECIALS の特能（投手: 変化球中心・速球中心・テンポ○、野手: 積極打法など7種）。
 - 区分の倍率は、投手は 投げ手の倍率 × 役割（先発・救援）の倍率、野手は ポジションの倍率 × 打席の倍率。
 - 水準は実在の全体の保有率（全体の水準も実在に寄せる）。
 - c は、緑特の型の補正を空にして（青特の型の補正は入れて）流した生成で測る。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

PROFILE_PATH = APP_DIR / "data" / "config" / "fictional_special_profile.json"
GREEN_PROFILE_PATH = APP_DIR / "data" / "config" / "fictional_green_profile.json"
# 緑特の型の表の対象（指示書 1-2）。選球眼・積極盗塁（能力と連動）、慎重盗塁・調子・投球位置（実在では起用法）は対象にしない。
GREEN_SPECIALS = {
    "投手": ("変化球中心", "速球中心", "テンポ○"),
    "野手": ("積極打法", "慎重打法", "強振多用", "ミート多用", "チームプレイ○", "積極走塁", "積極守備"),
}
PITCHER_ROLES = ("先発", "救援")
REAL_SEASONS = (2024, 2025, 2026)
SHRINK_N = 60  # w = n / (n + SHRINK_N)
MIN_REAL_HOLDERS = 10
# 水準を実在の保有率にする特能
# 投手の対ランナー×（赤）は、区分が投げ手だけのときは実在の投げ手ごとの保有率をそのまま目標にしていた。区分を「投げ手|役割」に
# 分けたので（`投手の役割と特能_改修指示.md` 1-1）、人数の少ない区分の振れを抑えるため、対ランナーと同じく水準を実在にして倍率を縮める。
REAL_LEVEL = {"投手": ("対ランナー", "対ランナー×"), "野手": ("お祭り男", "春男", "夏男", "秋男", "プレッシャーラン")}
# 実在の区分ごとの保有率をそのまま目標にする特能（今は無し）
REAL_DIRECT: dict[str, tuple[str, ...]] = {"投手": (), "野手": ()}
# 帯ごとの保有率を判定する、能力と連動させる特能: (役割, 特能, 能力の列, 帯の上限)
LINKED_BANDS = (("投手", "奪三振", "球速", (147, 151, 155)), ("野手", "内野安打○", "走力", (70, 80)), ("野手", "広角打法", "ミート", (40, 50)))
# 役割（先発・救援）ごとの帯の保有率を判定する、投手の連動特能（`投手の役割と特能_改修指示.md` 2-1）: (特能, 能力の列, 帯の上限)
ROLE_LINKED_BANDS = (("奪三振", "球速", (147, 151, 155)), ("球速安定", "球速", (147, 151, 155)))
# 役割ごとの保有率を判定する投手の特能（指示書 0-2 の表）
ROLE_SPECIALS = ("緊急登板○", "牽制○", "内角攻め", "スロースターター", "負け運", "緩急○", "ナチュラルシュート")
POSITIONS = ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")


def band_index(value: float, limits: tuple[int, ...]) -> int:
    for index, limit in enumerate(limits):
        if value <= limit:
            return index
    return len(limits)


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
def load_real_players() -> list[dict[str, Any]]:
    """実在（2024〜2026年版）の日本人の、区分・特能（青特と赤特。ランク特能・起用法・緑特・○○キラーを除く）・能力。"""
    import pandas as pd

    import build_real_team_reference as ref
    from generator import real_data
    from generator import team_analysis as ta

    kinds = ta.special_kind_map()
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
                role = "投手" if row["role"] == "投手" else "野手"
                throws, bats = ta._hand_parts(row.get("throws_bats"))
                specials, greens = [], []
                for name, special_kind in row.get("specials") or []:
                    if special_kind == "green":
                        greens.append(name)
                    if special_kind in ("rank", "usage", "green"):
                        continue
                    if name not in kinds and name.endswith("キラー"):
                        continue
                    specials.append(name)
                number = lambda key: None if pd.isna(row.get(key)) else float(row[key])  # noqa: E731
                hand = throws if role == "投手" else bats
                rows.append({
                    "role": role,
                    "hand": "左" if hand == "左" else "右",
                    "position": "投手" if role == "投手" else str(row.get("main_position") or ""),
                    "specials": specials, "球速": number("top_speed"), "走力": number("run_speed"), "ミート": number("contact"),
                    # 緑特（実在の special_kind が green の12種）と、投手の役割（球団分析と同じ。起用の最初の文字が「先」なら先発）
                    "greens": greens, "prole": ("先発" if str(row.get("pitcher_roles") or "")[:1] == "先" else "救援") if role == "投手" else None,
                    # 投手の特能の査定点（実在の特能すべて。○○キラーも含む）
                    "special_points": special_points([name for name, _kind in row.get("specials") or []]) if role == "投手" else None,
                })
    return rows


def special_points(names: list[str]) -> float:
    """投手の特能の査定点（generator.rating の特能の点。ランク特能は別に数えるので入らない）。"""
    from generator import rating

    return float(rating.special_points(names, "投手"))


def eligible_specials(role: str) -> list[str]:
    """表の対象にする特能（指示書 1-6 の 4）の候補。実在の人数の条件は別に見る。"""
    import app

    master = app.load_master_data()
    linked = {name for name, *_ in app.FICTIONAL_LINKED_SPECIALS[role]}
    banned = set(app.FICTIONAL_NOT_REAL_SPECIALS[role]) | set(app.USAGE_SPECIAL_NAMES) | linked
    names = []
    # 投手は赤特も対象にする（`投手の役割と特能_改修指示.md` 1-1）
    excluded_kinds = ("green", "gold") if role == "投手" else ("red", "green", "gold")
    for row in master.abilities:
        name = str(row["name"])
        if row["kind"] in excluded_kinds or name in banned or app.is_ranked_special(row):
            continue
        if app.special_target_role(row) in (role, "共通"):
            names.append(name)
    return names


def real_statistics(real: list[dict[str, Any]]) -> dict[str, Any]:
    """判定に使う実在の値（青特の数、赤特の数、帯ごとの保有率）。"""
    from generator import team_analysis as ta

    def counts(row: dict[str, Any]) -> tuple[int, int]:
        c = ta.special_counts(row["specials"])
        return c["n_blue"], c["n_red"]

    def mean_n(rows: list[dict[str, Any]], index: int = 0) -> dict[str, float]:
        values = [counts(r)[index] for r in rows]
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
        return {"平均": round(mean, 4), "標準偏差": round(sd, 4), "人数": len(values)}

    pitchers = [r for r in real if r["role"] == "投手"]
    fielders = [r for r in real if r["role"] == "野手"]
    stats: dict[str, Any] = {
        "投手": {hand: mean_n([r for r in pitchers if r["hand"] == hand]) for hand in ("左", "右")},
        "投手_赤": mean_n(pitchers, 1),
        "野手": {"全体": mean_n(fielders), **{hand: mean_n([r for r in fielders if r["hand"] == hand]) for hand in ("左", "右")}},
        "ポジション": {pos: mean_n([r for r in fielders if r["position"] == pos]) for pos in POSITIONS},
        "帯": {},
    }
    for role, name, key, limits in LINKED_BANDS:
        rows = pitchers if role == "投手" else fielders
        out = {}
        for hand in ("右", "左"):
            for band in range(len(limits) + 1):
                group = [r for r in rows if r["hand"] == hand and r[key] is not None and band_index(r[key], limits) == band]
                out[f"{hand}|{band}"] = {"保有率": round(sum(name in r["specials"] for r in group) / len(group), 4) if group else None, "人数": len(group)}
        stats["帯"][name] = out
    stats["役割"] = real_role_statistics(pitchers)
    return stats


def real_role_statistics(pitchers: list[dict[str, Any]]) -> dict[str, Any]:
    """投手の役割（先発・救援）ごとの実在の値（`投手の役割と特能_改修指示.md` 2-1）。"""
    from generator import team_analysis as ta

    def summary(values: list[float]) -> dict[str, float]:
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
        return {"平均": round(mean, 4), "標準偏差": round(sd, 4), "人数": len(values)}

    out: dict[str, Any] = {"青特の数": {}, "赤特の数": {}, "特能の査定点": {}, "保有率": {}, "帯": {}}
    for prole in PITCHER_ROLES:
        rows = [r for r in pitchers if r["prole"] == prole]
        counts = [ta.special_counts(r["specials"]) for r in rows]
        out["青特の数"][prole] = summary([c["n_blue"] for c in counts])
        out["赤特の数"][prole] = summary([c["n_red"] for c in counts])
        out["特能の査定点"][prole] = summary([r["special_points"] for r in rows])
        for name in ROLE_SPECIALS:
            out["保有率"].setdefault(name, {})[prole] = {"保有率": round(sum(name in r["specials"] for r in rows) / len(rows), 4), "人数": len(rows)}
        for name, key, limits in ROLE_LINKED_BANDS:
            for band in range(len(limits) + 1):
                group = [r for r in rows if r[key] is not None and band_index(r[key], limits) == band]
                out["帯"].setdefault(name, {})[f"{prole}|{band}"] = {
                    "保有率": round(sum(name in r["specials"] for r in group) / len(group), 4) if group else None, "人数": len(group),
                }
    return out


# ---------------------------------------------------------------------------
# 生成（球団生成）
# ---------------------------------------------------------------------------
_MASTER = None


def _init_worker(override: dict[str, Any] | None, green_override: dict[str, Any] | None = None) -> None:
    logging.disable(logging.WARNING)
    global _MASTER
    import app

    _MASTER = app.load_master_data()
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = override
    app.FICTIONAL_GREEN_PROFILE_OVERRIDE = green_override


def _team_players(team_seed: int) -> list[dict[str, Any]]:
    import app
    from generator import team_analysis as ta

    rows = []
    for p in app.generate_team(team_seed, master=_MASTER)["players"]:
        if p.get("roster_origin") == "foreign_import":
            continue
        role = "投手" if p.get("role") == "投手" else "野手"
        throws, bats = ta._hand_parts(p.get("batting_throwing"))
        hand = throws if role == "投手" else bats
        abilities = p.get("abilities") or {}
        rows.append({
            "team": team_seed, "role": role, "hand": "左" if hand == "左" else "右", "age": p.get("age"),
            "position": "投手" if role == "投手" else str(p.get("position", "")), "player_class": p.get("player_class"),
            "prole": ("先発" if p.get("position") == "先発" else "救援") if role == "投手" else None,
            "specials": [str(n) for n in p.get("special_abilities") or []],
            "球速": ta._number(abilities.get("球速")), "走力": ta._number(abilities.get("走力")), "ミート": ta._number(abilities.get("ミート")),
        })
    return rows


def collect_players(
    teams: int, start: int = 1, workers: int | None = None, override: dict[str, Any] | None = None, green_override: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """球団生成の日本人の選手。override が None なら data/config の表、{} なら青特の型の補正なし、辞書ならその表を使う。
    green_override は緑特の型の表で、使い方は同じ。"""
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(override, green_override)) as pool:
        chunks = list(pool.map(_team_players, range(start, start + teams), chunksize=4))
    return [row for chunk in chunks for row in chunk]


def segment_of(row: dict[str, Any]) -> str:
    """青特の型の区分。投手は「左・右|先発・救援」、野手は「ポジション|左・右」。"""
    return f"{row['hand']}|{row['prole']}" if row["role"] == "投手" else f"{row['position']}|{row['hand']}"


def green_segment_of(row: dict[str, Any]) -> str:
    """緑特の型の区分（青特の型と同じ）。"""
    return segment_of(row)


def holding_rates(players: list[dict[str, Any]], names: list[str], segment: Any = segment_of) -> dict[str, dict[str, dict[str, float]]]:
    """{役割: {特能: {区分: 保有率}}} と区分の人数 {役割: {"": {区分: 割合}}}。"""
    count: dict[str, Counter] = {"投手": Counter(), "野手": Counter()}
    held: dict[str, dict[str, Counter]] = {"投手": defaultdict(Counter), "野手": defaultdict(Counter)}
    for p in players:
        seg = segment(p)
        count[p["role"]][seg] += 1
        for name in p["specials"]:
            held[p["role"]][name][seg] += 1
    result: dict[str, dict[str, dict[str, float]]] = {}
    for role in count:
        result[role] = {name: {seg: held[role][name][seg] / n for seg, n in count[role].items()} for name in names}
        result[role][""] = {seg: n / sum(count[role].values()) for seg, n in count[role].items()}
    return result


# ---------------------------------------------------------------------------
# 表を作る
# ---------------------------------------------------------------------------
def shrunk_multiplier(rate: float, overall: float, n: int) -> float:
    if overall <= 0:
        return 1.0
    w = n / (n + SHRINK_N)
    return 1.0 + w * (rate / overall - 1.0)


def build_table(real: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    """実在と、補正なしの生成（baseline）から、{役割: {特能: {区分: [c, t]}}} を作る。"""
    table: dict[str, Any] = {}
    for role in ("投手", "野手"):
        real_role = [r for r in real if r["role"] == role]
        names = sorted(set(eligible_specials(role)) | set(REAL_LEVEL[role]) | set(REAL_DIRECT[role]))
        rates = holding_rates(baseline, names)[role]
        fractions = rates[""]
        generated_overall = {name: sum(fractions[seg] * rates[name].get(seg, 0.0) for seg in fractions) for name in names}
        n_real = len(real_role)
        by_hand = Counter(r["hand"] for r in real_role)
        by_position = Counter(r["position"] for r in real_role)
        by_prole = Counter(r["prole"] for r in real_role)
        table[role] = {}
        for name in names:
            holders = [r for r in real_role if name in r["specials"]]
            if len(holders) < MIN_REAL_HOLDERS and name not in REAL_LEVEL[role] and name not in REAL_DIRECT[role]:
                continue
            r_all = len(holders) / n_real
            hand_rate = {h: sum(name in r["specials"] for r in real_role if r["hand"] == h) / by_hand[h] for h in by_hand}
            entry: dict[str, list[float]] = {}
            if name in REAL_DIRECT[role]:
                # 実在の区分（投手は 投げ手 × 役割）ごとの保有率をそのまま目標にする
                for seg in fractions:
                    group = [r for r in real_role if segment_of(r) == seg]
                    entry[seg] = [round(rates[name].get(seg, 0.0), 4), round(sum(name in r["specials"] for r in group) / len(group), 4)]
                table[role][name] = entry
                continue
            level = r_all if name in REAL_LEVEL[role] else generated_overall[name]
            raw: dict[str, float] = {}
            for seg in fractions:
                if role == "投手":
                    hand, prole = seg.split("|")
                    prole_rate = sum(name in r["specials"] for r in real_role if r["prole"] == prole) / by_prole[prole]
                    raw[seg] = shrunk_multiplier(hand_rate[hand], r_all, by_hand[hand]) * shrunk_multiplier(prole_rate, r_all, by_prole[prole])
                else:
                    position, hand = seg.split("|")
                    pos_rate = sum(name in r["specials"] for r in real_role if r["position"] == position) / by_position[position]
                    m_pos = shrunk_multiplier(pos_rate, r_all, by_position[position])
                    m_hand = shrunk_multiplier(hand_rate[hand], r_all, by_hand[hand])
                    raw[seg] = m_pos * m_hand
            scale = 1.0 / sum(fractions[seg] * raw[seg] for seg in fractions)
            for seg in fractions:
                entry[seg] = [round(rates[name].get(seg, 0.0), 4), round(min(1.0, level * raw[seg] * scale), 4)]
            table[role][name] = entry
    return table


def correct_table(table: dict[str, Any], result: list[dict[str, Any]], segment: Any = segment_of) -> dict[str, Any]:
    """表を入れて流した結果が目標からずれた分を、目標に足し戻す（t' = t + (t − 結果)、0〜1に収める）。"""
    corrected: dict[str, Any] = {}
    for role, specials in table.items():
        rates = holding_rates(result, sorted(specials), segment)[role]
        corrected[role] = {}
        for name, segments in specials.items():
            corrected[role][name] = {
                seg: [c, round(min(1.0, max(0.0, t + (t - rates[name].get(seg, 0.0)))), 4)] for seg, (c, t) in segments.items()
            }
    return corrected


def build_green_table(real: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    """緑特の型の表 {役割: {特能: {区分: [c, t]}}}。水準は実在の全体の保有率。倍率は 投げ手×役割（投手）、ポジション×打席（野手）。"""
    table: dict[str, Any] = {}
    for role in ("投手", "野手"):
        real_role = [r for r in real if r["role"] == role]
        names = list(GREEN_SPECIALS[role])
        rates = holding_rates(baseline, names, green_segment_of)[role]
        fractions = rates[""]
        table[role] = {}
        for name in names:
            r_all = sum(name in r["greens"] for r in real_role) / len(real_role)

            def multiplier(key: str, value: str, name: str = name, r_all: float = r_all) -> float:
                group = [r for r in real_role if r[key] == value]
                return shrunk_multiplier(sum(name in r["greens"] for r in group) / len(group), r_all, len(group))

            raw: dict[str, float] = {}
            for seg in fractions:
                first, second = seg.split("|")
                raw[seg] = multiplier("hand", first) * multiplier("prole", second) if role == "投手" else multiplier("position", first) * multiplier("hand", second)
            scale = 1.0 / sum(fractions[seg] * raw[seg] for seg in fractions)
            table[role][name] = {seg: [round(rates[name].get(seg, 0.0), 4), round(min(1.0, r_all * raw[seg] * scale), 4)] for seg in fractions}
    return table


def real_green_statistics(real: list[dict[str, Any]]) -> dict[str, Any]:
    """判定に使う実在の値（緑特の数、緑特の型の対象の特能の、役割・ポジションごとの保有率）。"""
    stats: dict[str, Any] = {"緑特の数": {}, "保有率": {}}
    for role in ("投手", "野手"):
        rows = [r for r in real if r["role"] == role]
        values = [len(r["greens"]) for r in rows]
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
        stats["緑特の数"][role] = {"平均": round(mean, 4), "標準偏差": round(sd, 4), "人数": len(values)}
        key, groups = ("prole", PITCHER_ROLES) if role == "投手" else ("position", POSITIONS)
        stats["保有率"][role] = {}
        for name in GREEN_SPECIALS[role]:
            out = {"全体": {"保有率": round(sum(name in r["greens"] for r in rows) / len(rows), 4), "人数": len(rows)}}
            for group in groups:
                members = [r for r in rows if r[key] == group]
                out[group] = {"保有率": round(sum(name in r["greens"] for r in members) / len(members), 4), "人数": len(members)}
            stats["保有率"][role][name] = out
    return stats


def build_green(args: argparse.Namespace, real: list[dict[str, Any]]) -> None:
    """緑特の型の表を作る（--green）。c は緑特の型の補正を空にして流した生成（青特の型の補正は data/config の表）で測る。"""
    cache = args.cache_dir
    baseline_path = cache / "green_baseline.json" if cache else None
    if baseline_path and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    else:
        baseline = collect_players(args.teams, args.start, args.workers, green_override={})
        if baseline_path:
            cache.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    print(f"緑特の型の補正なしの生成: {len(baseline)}人（{args.teams}球団）", flush=True)
    table = build_green_table(real, baseline)
    if cache:
        (cache / "green_table_before_correction.json").write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if not args.no_correct:
        result = collect_players(args.teams, args.start, args.workers, green_override=table)
        if cache:
            (cache / "green_result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        table = correct_table(table, result, green_segment_of)
    meta = {
        "作った日": date.today().isoformat(), "球団生成": f"seed {args.start}〜{args.start + args.teams - 1}（{args.teams}球団）",
        "実在の年版": list(REAL_SEASONS), "縮め方 n/(n+k) の k": SHRINK_N, "水準": "実在の全体の保有率",
        "最後の直し": not args.no_correct, "作り方": "scripts/build_fictional_special_profile.py --green",
    }
    output = {"作り方": meta, "実在": real_green_statistics(real), "表": table}
    if args.teams == 300 or args.write:
        GREEN_PROFILE_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"書き込みました: {GREEN_PROFILE_PATH.relative_to(APP_DIR)}")
    else:
        print("球団数が300でないので書き込みません（--write で書く）。")


def apply_start_table(table: dict[str, Any], start: dict[str, Any], role: str = "投手") -> dict[str, Any]:
    """直す前の目標 t を、出発点の表（{特能: {区分: [c, t]}}。試作表）から取る。c は今の生成で測った値のまま。
    出発点の表にない特能は作った表のまま。"""
    for name, segments in table[role].items():
        for seg, pair in segments.items():
            if seg in start.get(name, {}):
                pair[1] = start[name][seg][1]
    return table


def forced_zero(table: dict[str, Any]) -> dict[str, Any]:
    """右投手のクロスファイヤーの目標は 0 のまま（直しても動かさない）。"""
    for seg, pair in table["投手"].get("クロスファイヤー", {}).items():
        if seg.split("|")[0] == "右":
            pair[1] = 0.0
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="架空球団用の日本人の青特の型の目標の表を作ります。")
    parser.add_argument("--teams", type=int, default=300, help="球団数（正式は300）")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--no-correct", action="store_true", help="最後の1回の直しをしない")
    parser.add_argument("--write", action="store_true", help="球団数が300でなくても書き込む")
    parser.add_argument("--cache-dir", type=Path, default=None, help="途中の結果（補正なしの生成・表を入れた生成）を置く場所。調整の確認用")
    parser.add_argument("--green", action="store_true", help="緑特の型の表（data/config/fictional_green_profile.json）を作る")
    parser.add_argument("--pitchers-only", action="store_true", help="投手の表だけ作り直す（野手の表・野手の実在の値は data/config のまま）")
    parser.add_argument("--start-table", type=Path, default=None, help="直す前の投手の目標 t を取る表（{特能: {区分: [c, t]}}。試作表）")
    args = parser.parse_args()

    real = load_real_players()
    print(f"実在（{REAL_SEASONS[0]}〜{REAL_SEASONS[-1]}年版の日本人）: 投手 {sum(r['role'] == '投手' for r in real)}人／野手 {sum(r['role'] == '野手' for r in real)}人", flush=True)
    if args.green:
        build_green(args, real)
        return
    cache = args.cache_dir
    baseline_path = cache / "baseline.json" if cache else None
    if baseline_path and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    else:
        baseline = collect_players(args.teams, args.start, args.workers, override={})
        if baseline_path:
            cache.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    print(f"補正なしの生成: {len(baseline)}人（{args.teams}球団）", flush=True)
    table = build_table(real, baseline)
    current = json.loads(PROFILE_PATH.read_text(encoding="utf-8")) if args.pitchers_only else None
    if current is not None:
        table["野手"] = current["表"]["野手"]
    if args.start_table:
        table = apply_start_table(table, json.loads(args.start_table.read_text(encoding="utf-8")))
    if cache:
        (cache / "table_before_correction.json").write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if not args.no_correct:
        result = collect_players(args.teams, args.start, args.workers, override=table)
        if cache:
            (cache / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        corrected = forced_zero(correct_table(table, result))
        if current is not None:
            corrected["野手"] = table["野手"]
        table = corrected
    meta = {
        "作った日": date.today().isoformat(), "球団生成": f"seed {args.start}〜{args.start + args.teams - 1}（{args.teams}球団）",
        "実在の年版": list(REAL_SEASONS), "縮め方 n/(n+k) の k": SHRINK_N, "対象の実在の最低人数": MIN_REAL_HOLDERS,
        "最後の直し": not args.no_correct, "作り方": "scripts/build_fictional_special_profile.py",
    }
    if args.start_table:
        meta["直す前の投手の目標"] = args.start_table.as_posix()
    if current is not None:
        meta = {**current["作り方"], "投手の表": meta}
    output = {"作り方": meta, "実在": real_statistics(real), "表": table}
    for role in table:
        print(f"{role}: 特能 {len(table[role])}種")
    if args.teams == 300 or args.write:
        PROFILE_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"書き込みました: {PROFILE_PATH.relative_to(APP_DIR)}")
    else:
        print("球団数が300でないので書き込みません（--write で書く）。")


if __name__ == "__main__":
    main()
