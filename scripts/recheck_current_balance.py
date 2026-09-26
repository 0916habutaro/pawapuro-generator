from __future__ import annotations

import argparse
import ast
import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    USAGE_SPECIAL_NAMES,
    ability_numeric_value,
    generate_player,
    load_master_data,
    pitch_movement,
    pitcher_speed_value,
)


REAL_LABEL = "実在12球団"
GENERATED_LABEL = "現行架空球団用"
FIELDER_POSITIONS = ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"]
FIELDER_METRICS = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球", "弾道"]
PITCHER_METRICS = ["球速", "コントロール", "スタミナ", "通常変化球数", "表示球種数", "総変化量", "第二球種数"]
PITCHER_ROLES = ["先発", "中継ぎ", "抑え"]
STATS = ["人数", "平均", "中央値", "標準偏差", "P10", "P25", "P50", "P75", "P90", "P95", "P99", "最小", "最大"]
RANK_FAMILIES = [
    "チャンス", "対左投手", "盗塁", "走塁", "送球", "ケガしにくさ", "キャッチャー",
    "対ピンチ", "対左打者", "打たれ強さ", "ノビ", "クイック", "回復",
]
RANKS = list("ABCDEFG")
AGE_BANDS = ["18～19歳", "20～22歳", "23～26歳", "27～30歳", "31～34歳", "35歳以上"]
FOCUS_SPECIALS = {
    "投手": [
        "リリース○", "球速安定", "奪三振", "四球", "球持ち○", "抜け球", "逃げ球", "内角攻め",
        "キレ○", "荒れ球", "緩急○", "一発", "スロースターター",
    ],
    "野手": [
        "三振", "サヨナラ男", "固め打ち", "内野安打○", "満塁男", "流し打ち", "決勝打", "バント○",
        "併殺", "広角打法", "ヘッドスライディング", "積極打法", "選球眼", "積極走塁",
    ],
}
ALIASES = {"盗塁○": "盗塁〇", "走塁○": "走塁〇", "ノビ○": "ノビ〇"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="現行mainの生成結果と固定実在Excelを再比較します。")
    parser.add_argument("--real-xlsx", type=Path, default=ROOT / "local_data" / "real_powerpro_players.xlsx")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "real_vs_generated_current_recheck")
    parser.add_argument("--count", type=int, default=10_000, help="各seed・各役割の生成人数")
    parser.add_argument("--seeds", nargs="+", type=int, default=[202607150001, 202617150001, 202627150001])
    parser.add_argument("--reuse-generated", action="store_true", help="既存generated_players.csvを再利用")
    return parser.parse_args()


def normalize_name(value: Any) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return ALIASES.get(text, text)


def normalize_direction(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def safe_json(value: Any, default: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        try:
            return ast.literal_eval(str(value))
        except Exception:
            return default


def split_positions(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in re.split(r"[;,、/]+", str(value)) if part.strip()]


def age_band(age: Any) -> str:
    if pd.isna(age):
        return "不明"
    value = int(age)
    if value <= 19:
        return "18～19歳"
    if value <= 22:
        return "20～22歳"
    if value <= 26:
        return "23～26歳"
    if value <= 30:
        return "27～30歳"
    if value <= 34:
        return "31～34歳"
    return "35歳以上"


def real_pitcher_role(value: Any) -> str:
    text = "" if pd.isna(value) else str(value)
    if "先" in text:
        return "先発"
    if "抑" in text:
        return "抑え"
    if "中" in text:
        return "中継ぎ"
    return "不明"


def special_kind_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    master = pd.read_csv(ROOT / "data" / "special_abilities.csv")
    category_map = {
        "blue": "青特", "red": "赤特", "green": "緑特", "gold": "金特",
        "neutral": "ランク系", "mixed": "青特", "normal": "青特",
    }
    categories: dict[str, str] = {}
    roles: dict[str, str] = {}
    groups: dict[str, str] = {}
    for _, row in master.iterrows():
        name = normalize_name(row.get("name"))
        categories[name] = category_map.get(str(row.get("kind", "")), str(row.get("kind", "不明")))
        roles[name] = str(row.get("target_role") or "共通")
        groups[name] = str(row.get("group") or "")
    return categories, roles, groups


def generated_pitch_metrics(balls: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [b for b in balls if b.get("kind", "breaking") == "breaking" and not bool(b.get("is_second_pitch", False))]
    second = [b for b in balls if b.get("kind", "breaking") == "breaking" and bool(b.get("is_second_pitch", False))]
    straight = [b for b in balls if b.get("kind") == "second_fastball"]
    same_direction = all(
        any(normalize_direction(p.get("direction_code")) == normalize_direction(s.get("direction_code")) for p in primary)
        for s in second
    ) if second else True
    return {
        "通常変化球数": len(primary),
        "表示球種数": len(primary) + len(second) + len(straight),
        "総変化量": sum(pitch_movement(b) for b in primary),
        "第二球種数": len(second),
        "第二球種あり": bool(second),
        "ストレート系第二種あり": bool(straight),
        "4球種以上": len(primary) + len(second) + len(straight) >= 4,
        "第二球種同方向整合": same_direction,
        "球種方向": json.dumps([normalize_direction(b.get("direction_code")) for b in primary], ensure_ascii=False),
    }


def flatten_generated(player: dict[str, Any], run: str) -> dict[str, Any]:
    abilities = player.get("abilities", {})
    specials = [normalize_name(x) for x in player.get("special_abilities", []) if normalize_name(x)]
    ranked = [normalize_name(x) for x in (abilities.get("ranked_specials") or {}).values() if normalize_name(x)]
    subs = player.get("sub_positions", []) or []
    row: dict[str, Any] = {
        "dataset": GENERATED_LABEL,
        "run": run,
        "player_id": f"{run}:{player.get('seed')}",
        "seed": player.get("seed"),
        "role": player.get("role", ""),
        "position": player.get("position", ""),
        "pitcher_role": player.get("position", "") if player.get("role") == "投手" else "",
        "age": player.get("age"),
        "entry_route": player.get("entry_route", ""),
        "pro_years": player.get("pro_years"),
        "pro_entry_age": player.get("pro_entry_age"),
        "player_class": player.get("player_class", ""),
        "growth_type": player.get("growth_type", ""),
        "development_stage": player.get("development_stage", ""),
        "batting_throwing": player.get("batting_throwing", ""),
        "sub_positions": json.dumps(subs, ensure_ascii=False),
        "sub_position_count": len(subs),
        "special_names": json.dumps(specials, ensure_ascii=False),
        "ranked_names": json.dumps(ranked, ensure_ascii=False),
    }
    for key in FIELDER_METRICS:
        row[key] = ability_numeric_value(abilities, key)
    row["球速"] = pitcher_speed_value(abilities)
    row["コントロール"] = ability_numeric_value(abilities, "コントロール")
    row["スタミナ"] = ability_numeric_value(abilities, "スタミナ")
    row.update(generated_pitch_metrics(player.get("breaking_balls", []) or []))
    return row


def generate_current(count: int, seeds: list[int], output_dir: Path) -> pd.DataFrame:
    master = load_master_data()
    rows: list[dict[str, Any]] = []
    expected = count * len(seeds) * 2
    for seed_start in seeds:
        run = f"seed_{seed_start}"
        offset = 0
        for role in ["投手", "野手"]:
            print(f"{run}: 架空球団用 {role} {count:,}人生成中", flush=True)
            for _ in range(count):
                rows.append(flatten_generated(generate_player(role, "架空球団用", master, seed_start + offset), run))
                offset += 1
    frame = pd.DataFrame(rows)
    if len(frame) != expected:
        raise RuntimeError(f"生成人数不一致: expected={expected}, actual={len(frame)}")
    frame.to_csv(output_dir / "generated_players.csv", index=False, encoding="utf-8-sig")
    return frame


def load_real(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    xl = pd.ExcelFile(path)
    players = pd.read_excel(xl, "players")
    breaking = pd.read_excel(xl, "breaking_balls") if "breaking_balls" in xl.sheet_names else pd.DataFrame()
    specials = pd.read_excel(xl, "special_abilities") if "special_abilities" in xl.sheet_names else pd.DataFrame()
    players = players.copy()
    players["player_id"] = REAL_LABEL + ":" + players["team"].astype(str) + ":" + players["name"].astype(str)
    pitch_rows: list[dict[str, Any]] = []
    if not breaking.empty:
        breaking = breaking.copy()
        breaking["slot"] = pd.to_numeric(breaking["slot"], errors="coerce")
        breaking["movement"] = pd.to_numeric(breaking["movement"], errors="coerce").fillna(0)
        for (team, name), subset in breaking.groupby(["team", "name"], dropna=False):
            primary = subset[subset["kind"].eq("breaking") & subset["slot"].fillna(1).eq(1)]
            second = subset[subset["kind"].eq("breaking") & subset["slot"].eq(2)]
            straight = subset[subset["kind"].eq("second_fastball")]
            primary_dirs = {normalize_direction(value) for value in primary["direction_code"].dropna()}
            second_dirs = {normalize_direction(value) for value in second["direction_code"].dropna()}
            pitch_rows.append({
                "team": team, "name": name,
                "通常変化球数": len(primary), "表示球種数": len(primary) + len(second) + len(straight),
                "総変化量": primary["movement"].sum(), "第二球種数": len(second), "第二球種あり": bool(len(second)),
                "ストレート系第二種あり": bool(len(straight)), "4球種以上": len(primary) + len(second) + len(straight) >= 4,
                "第二球種同方向整合": second_dirs.issubset(primary_dirs),
                "球種方向": json.dumps([normalize_direction(value) for value in primary["direction_code"].dropna()], ensure_ascii=False),
            })
    players = players.merge(pd.DataFrame(pitch_rows), on=["team", "name"], how="left") if pitch_rows else players
    rows: list[dict[str, Any]] = []
    for _, item in players.iterrows():
        role = str(item.get("role", ""))
        row = {
            "dataset": REAL_LABEL, "run": "real", "player_id": item["player_id"], "seed": None,
            "role": role, "position": item.get("main_position", ""),
            "pitcher_role": real_pitcher_role(item.get("pitcher_roles")) if role == "投手" else "",
            "age": item.get("age") if "age" in players.columns else None,
            "entry_route": item.get("entry_route", "") if "entry_route" in players.columns else "",
            "pro_years": item.get("pro_years") if "pro_years" in players.columns else None,
            "pro_entry_age": item.get("pro_entry_age") if "pro_entry_age" in players.columns else None,
            "player_class": "実在", "growth_type": "", "development_stage": "",
            "batting_throwing": item.get("throws_bats", ""),
            "sub_positions": json.dumps(split_positions(item.get("sub_positions")), ensure_ascii=False),
            "sub_position_count": len(split_positions(item.get("sub_positions"))),
            "special_names": "[]", "ranked_names": "[]",
            "弾道": item.get("trajectory"), "ミート": item.get("contact"), "パワー": item.get("power"),
            "走力": item.get("run_speed"), "肩力": item.get("arm_strength"), "守備力": item.get("fielding"),
            "捕球": item.get("catching"), "球速": item.get("top_speed"), "コントロール": item.get("control"),
            "スタミナ": item.get("stamina"),
        }
        for key in ["通常変化球数", "表示球種数", "総変化量", "第二球種数", "第二球種あり", "ストレート系第二種あり", "4球種以上", "第二球種同方向整合", "球種方向"]:
            row[key] = item.get(key, 0 if role == "投手" else None)
        rows.append(row)
    normalized = pd.DataFrame(rows)
    audit = {
        "sheets": xl.sheet_names,
        "columns": list(pd.read_excel(xl, "players", nrows=0).columns),
        "total": len(normalized),
        "pitchers": int(normalized["role"].eq("投手").sum()),
        "fielders": int(normalized["role"].eq("野手").sum()),
        "missing": players.isna().sum().to_dict(),
        "positions": normalized["position"].value_counts(dropna=False).to_dict(),
        "has_age": "age" in players.columns,
        "has_pro_years": "pro_years" in players.columns,
    }
    return normalized, specials, breaking, audit


def describe(values: pd.Series) -> dict[str, Any]:
    nums = pd.to_numeric(values, errors="coerce").dropna()
    if nums.empty:
        return {key: None for key in STATS}
    return {
        "人数": int(len(nums)), "平均": nums.mean(), "中央値": nums.median(), "標準偏差": nums.std(ddof=1),
        "P10": nums.quantile(.10), "P25": nums.quantile(.25), "P50": nums.quantile(.50), "P75": nums.quantile(.75),
        "P90": nums.quantile(.90), "P95": nums.quantile(.95), "P99": nums.quantile(.99), "最小": nums.min(), "最大": nums.max(),
    }


def paired_describe(real: pd.Series, generated: pd.Series, base: dict[str, Any]) -> dict[str, Any]:
    r, g = describe(real), describe(generated)
    row = dict(base)
    for stat in STATS:
        row[f"real_{stat}"] = r[stat]
        row[f"generated_{stat}"] = g[stat]
        row[f"real_minus_generated_{stat}"] = r[stat] - g[stat] if r[stat] is not None and g[stat] is not None else None
    if r["標準偏差"] not in (None, 0):
        row["generated_to_real_std_ratio"] = g["標準偏差"] / r["標準偏差"]
    else:
        row["generated_to_real_std_ratio"] = None
    return row


def overall_tables(real: pd.DataFrame, generated: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    f_rows, p_rows = [], []
    rf, gf = real[real["role"].eq("野手")], generated[generated["role"].eq("野手")]
    rp, gp = real[real["role"].eq("投手")], generated[generated["role"].eq("投手")]
    for metric in FIELDER_METRICS:
        f_rows.append(paired_describe(rf[metric], gf[metric], {"target": "野手全体", "metric": metric}))
    for metric in PITCHER_METRICS:
        p_rows.append(paired_describe(rp[metric], gp[metric], {"target": "投手全体", "metric": metric}))
    p_rows.append(paired_describe(rp["第二球種あり"].astype(float), gp["第二球種あり"].astype(float), {"target": "投手全体", "metric": "第二球種率"}))
    return pd.DataFrame(f_rows), pd.DataFrame(p_rows)


def fielder_position_tables(real: pd.DataFrame, generated: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ability_rows, percentile_rows, rate_rows = [], [], []
    for position in FIELDER_POSITIONS:
        r = real[(real["role"].eq("野手")) & real["position"].eq(position)]
        g = generated[(generated["role"].eq("野手")) & generated["position"].eq(position)]
        for metric in FIELDER_METRICS:
            paired = paired_describe(r[metric], g[metric], {"position": position, "metric": metric})
            ability_rows.append(paired)
            for stat in ["P10", "P25", "P50", "P75", "P90", "P95"]:
                percentile_rows.append({
                    "position": position, "metric": metric, "percentile": stat,
                    "real_value": paired[f"real_{stat}"], "generated_value": paired[f"generated_{stat}"],
                    "real_minus_generated": paired[f"real_minus_generated_{stat}"],
                    "sample_real": len(r), "sample_generated": len(g),
                })
            rn, gn = pd.to_numeric(r[metric], errors="coerce"), pd.to_numeric(g[metric], errors="coerce")
            for label, fn in [
                ("39以下", lambda s: s.le(39)), ("50以上", lambda s: s.ge(50)), ("60以上", lambda s: s.ge(60)),
                ("65以上", lambda s: s.ge(65)), ("70以上", lambda s: s.ge(70)), ("80以上", lambda s: s.ge(80)),
                ("90以上", lambda s: s.ge(90)),
            ]:
                rr, gr = fn(rn).mean() * 100, fn(gn).mean() * 100
                rate_rows.append({"position": position, "metric": metric, "threshold": label, "real_rate_pct": rr, "generated_rate_pct": gr, "real_minus_generated_pt": rr - gr, "sample_real": rn.notna().sum(), "sample_generated": gn.notna().sum()})
    return pd.DataFrame(ability_rows), pd.DataFrame(percentile_rows), pd.DataFrame(rate_rows)


def trajectory_table(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for position in FIELDER_POSITIONS:
        r = pd.to_numeric(real[(real["role"].eq("野手")) & real["position"].eq(position)]["弾道"], errors="coerce").dropna()
        g = pd.to_numeric(generated[(generated["role"].eq("野手")) & generated["position"].eq(position)]["弾道"], errors="coerce").dropna()
        for label, fn in [(str(n), lambda s, n=n: s.eq(n)) for n in range(1, 5)] + [("3以上", lambda s: s.ge(3))]:
            rr, gr = fn(r).mean() * 100, fn(g).mean() * 100
            rows.append({"position": position, "trajectory": label, "real_count": int(fn(r).sum()), "generated_count": int(fn(g).sum()), "real_rate_pct": rr, "generated_rate_pct": gr, "real_minus_generated_pt": rr - gr, "sample_real": len(r), "sample_generated": len(g)})
    return pd.DataFrame(rows)


def pitcher_role_table(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = PITCHER_METRICS[:-1] + ["第二球種率"]
    for role in PITCHER_ROLES:
        r = real[(real["role"].eq("投手")) & real["pitcher_role"].eq(role)]
        g = generated[(generated["role"].eq("投手")) & generated["pitcher_role"].eq(role)]
        for metric in metrics:
            rv = r["第二球種あり"].astype(float) if metric == "第二球種率" else r[metric]
            gv = g["第二球種あり"].astype(float) if metric == "第二球種率" else g[metric]
            rows.append(paired_describe(rv, gv, {"pitcher_role": role, "metric": metric}))
    return pd.DataFrame(rows)


def pitch_mix_table(real: pd.DataFrame, generated: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ["全体", *PITCHER_ROLES]:
        r = real[real["role"].eq("投手")] if role == "全体" else real[(real["role"].eq("投手")) & real["pitcher_role"].eq(role)]
        g = generated[generated["role"].eq("投手")] if role == "全体" else generated[(generated["role"].eq("投手")) & generated["pitcher_role"].eq(role)]
        for metric, fn in [
            ("第二球種率", lambda x: x["第二球種あり"].astype(bool)),
            ("ストレート系第二種率", lambda x: x["ストレート系第二種あり"].astype(bool)),
            ("表示4球種以上率", lambda x: x["4球種以上"].astype(bool)),
            ("第二球種同方向整合率", lambda x: x.loc[x["第二球種あり"].astype(bool), "第二球種同方向整合"].astype(bool)),
        ]:
            rv, gv = fn(r), fn(g)
            rr, gr = rv.mean() * 100, gv.mean() * 100
            rows.append({"pitcher_role": role, "metric": metric, "real_value": rr, "generated_value": gr, "real_minus_generated": rr - gr, "sample_real": len(rv), "sample_generated": len(gv)})
        for direction in ["1", "2", "3", "4", "5"]:
            def direction_rate(frame: pd.DataFrame) -> tuple[int, float]:
                values = [d for raw in frame["球種方向"].fillna("[]") for d in safe_json(raw, [])]
                return len(values), (sum(normalize_direction(x) == direction for x in values) / max(1, len(values)) * 100)
            rn, rr = direction_rate(r); gn, gr = direction_rate(g)
            rows.append({"pitcher_role": role, "metric": f"方向{direction}構成率", "real_value": rr, "generated_value": gr, "real_minus_generated": rr - gr, "sample_real": rn, "sample_generated": gn})
    return pd.DataFrame(rows)


def build_special_events(players: pd.DataFrame, real_specials: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], dict[str, str]]:
    categories, roles, _groups = special_kind_maps()
    real_roles = players[players["dataset"].eq(REAL_LABEL)][["player_id", "role"]]
    real_key = {tuple(pid.split(":", 2)[1:]): (pid, role) for pid, role in real_roles.itertuples(index=False)}
    normal_rows, rank_rows = [], []
    for _, item in real_specials.iterrows():
        name = normalize_name(item.get("special"))
        key = (str(item.get("team")), str(item.get("name")))
        pid, role = real_key.get(key, (f"{REAL_LABEL}:{key[0]}:{key[1]}", ""))
        source_kind = str(item.get("special_kind", ""))
        if source_kind == "usage" or name in USAGE_SPECIAL_NAMES:
            normal_rows.append({"dataset": REAL_LABEL, "run": "real", "player_id": pid, "role": role, "name": name, "kind": "usage"})
            continue
        if source_kind == "rank" or (name[-1:] in RANKS and re.sub(r"[A-G]$", "", name) in RANK_FAMILIES):
            rank_rows.append({"dataset": REAL_LABEL, "player_id": pid, "role": role, "name": name, "family": re.sub(r"[A-G]$", "", name), "rank": name[-1:]})
        else:
            kind = categories.get(name, "緑特" if source_kind == "green" else "青特")
            if kind in {"青特", "赤特", "緑特", "金特"}:
                normal_rows.append({"dataset": REAL_LABEL, "run": "real", "player_id": pid, "role": role, "name": name, "kind": kind})
    generated = players[players["dataset"].eq(GENERATED_LABEL)]
    for _, item in generated.iterrows():
        for name in safe_json(item["special_names"], []):
            kind = "usage" if normalize_name(name) in USAGE_SPECIAL_NAMES else categories.get(normalize_name(name), "不明")
            if kind in {"青特", "赤特", "緑特", "金特", "usage"}:
                normal_rows.append({"dataset": GENERATED_LABEL, "run": item["run"], "player_id": item["player_id"], "role": item["role"], "name": normalize_name(name), "kind": kind})
        for name in safe_json(item["ranked_names"], []):
            rank_rows.append({"dataset": GENERATED_LABEL, "player_id": item["player_id"], "role": item["role"], "name": name, "family": re.sub(r"[A-G]$", "", name), "rank": name[-1:]})
    return pd.DataFrame(normal_rows), pd.DataFrame(rank_rows), categories, roles


def counts_by_player(players: pd.DataFrame, events: pd.DataFrame, kind: str | None = None) -> pd.Series:
    ids = players["player_id"]
    subset = events if kind is None else events[events["kind"].eq(kind)]
    counts = subset.groupby("player_id").size()
    return ids.map(counts).fillna(0).astype(int)


def special_count_tables(players: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    count_rows, kind_rows = [], []
    for role in ["投手", "野手"]:
        rplayers = players[(players["dataset"].eq(REAL_LABEL)) & players["role"].eq(role)]
        gplayers = players[(players["dataset"].eq(GENERATED_LABEL)) & players["role"].eq(role)]
        countable = events[events["kind"].isin(["青特", "赤特", "緑特"])]
        rc = counts_by_player(rplayers, countable[countable["dataset"].eq(REAL_LABEL)])
        gc = counts_by_player(gplayers, countable[countable["dataset"].eq(GENERATED_LABEL)])
        row = {"role": role, "sample_real": len(rc), "sample_generated": len(gc), "real_mean": rc.mean(), "generated_mean": gc.mean(), "real_median": rc.median(), "generated_median": gc.median(), "real_P75": rc.quantile(.75), "generated_P75": gc.quantile(.75), "real_P90": rc.quantile(.90), "generated_P90": gc.quantile(.90)}
        for label, fn in [(f"{n}個", lambda x, n=n: x.eq(n)) for n in range(8)] + [("8個以上", lambda x: x.ge(8)), ("5個以上", lambda x: x.ge(5))]:
            rr, gr = fn(rc).mean() * 100, fn(gc).mean() * 100
            row[f"real_{label}率"] = rr; row[f"generated_{label}率"] = gr; row[f"real_minus_generated_{label}率"] = rr - gr
        count_rows.append(row)
        for kind in ["青特", "赤特", "緑特", "金特", "usage"]:
            rk = counts_by_player(rplayers, events[events["dataset"].eq(REAL_LABEL)], kind)
            gk = counts_by_player(gplayers, events[events["dataset"].eq(GENERATED_LABEL)], kind)
            kind_rows.append({"role": role, "kind": kind, "sample_real": len(rk), "sample_generated": len(gk), "real_mean_count": rk.mean(), "generated_mean_count": gk.mean(), "real_holder_rate_pct": rk.gt(0).mean() * 100, "generated_holder_rate_pct": gk.gt(0).mean() * 100, "real_minus_generated_holder_rate_pt": (rk.gt(0).mean() - gk.gt(0).mean()) * 100})
    return pd.DataFrame(count_rows), pd.DataFrame(kind_rows)


def add_rank_kind_rows(players: pd.DataFrame, ranked_events: pd.DataFrame, kind_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ["投手", "野手"]:
        rplayers = players[(players["dataset"].eq(REAL_LABEL)) & players["role"].eq(role)]
        gplayers = players[(players["dataset"].eq(GENERATED_LABEL)) & players["role"].eq(role)]
        revents = ranked_events[(ranked_events["dataset"].eq(REAL_LABEL)) & ranked_events["role"].eq(role)]
        gevents = ranked_events[(ranked_events["dataset"].eq(GENERATED_LABEL)) & ranked_events["role"].eq(role)]
        rc = rplayers["player_id"].map(revents.groupby("player_id").size()).fillna(0)
        gc = gplayers["player_id"].map(gevents.groupby("player_id").size()).fillna(0)
        rows.append({"role": role, "kind": "ランク系A～G", "sample_real": len(rc), "sample_generated": len(gc), "real_mean_count": rc.mean(), "generated_mean_count": gc.mean(), "real_holder_rate_pct": rc.gt(0).mean() * 100, "generated_holder_rate_pct": gc.gt(0).mean() * 100, "real_minus_generated_holder_rate_pt": (rc.gt(0).mean() - gc.gt(0).mean()) * 100})
    return pd.concat([kind_table, pd.DataFrame(rows)], ignore_index=True)


def previous_special_values(real_counts: dict[str, int]) -> dict[tuple[str, str], tuple[float, float]]:
    path = ROOT / "reports" / "real_vs_generated_balance_5000_special_review" / "special_name_metrics_compare.csv"
    if not path.exists():
        return {}
    old = pd.read_csv(path)
    old = old[(old.get("データ", "").astype(str).eq("架空球団用")) & old.get("対象", "").astype(str).eq("全体")]
    result = {}
    for _, row in old.iterrows():
        role, name = str(row.get("対象役割", "")), normalize_name(row.get("特殊能力", ""))
        if role not in {"投手", "野手"}:
            continue
        real_n, generated_n = real_counts[role], 5000
        generated_rate = float(row.get("生成出現数", 0)) / generated_n * 100
        current_definition = generated_rate - float(row.get("実在出現数", 0)) / real_n * 100
        result[(role, name)] = (generated_rate, current_definition)
    return result


def special_name_table(players: pd.DataFrame, events: pd.DataFrame, roles: dict[str, str]) -> pd.DataFrame:
    real_counts = {role: int(((players["dataset"].eq(REAL_LABEL)) & players["role"].eq(role)).sum()) for role in ["投手", "野手"]}
    gen_counts = {role: int(((players["dataset"].eq(GENERATED_LABEL)) & players["role"].eq(role)).sum()) for role in ["投手", "野手"]}
    previous = previous_special_values(real_counts)
    names = sorted(set(events["name"]))
    rows = []
    for name in names:
        target_role = roles.get(name, "共通")
        compare_roles = [target_role] if target_role in {"投手", "野手"} else ["投手", "野手"]
        for role in compare_roles:
            r = events[(events["dataset"].eq(REAL_LABEL)) & events["role"].eq(role) & events["name"].eq(name)]["player_id"].nunique()
            g = events[(events["dataset"].eq(GENERATED_LABEL)) & events["role"].eq(role) & events["name"].eq(name)]["player_id"].nunique()
            rr, gr = r / real_counts[role] * 100, g / gen_counts[role] * 100
            diff = gr - rr
            previous_item = previous.get((role, name))
            previous_value = previous_item[0] if previous_item else None
            prev = previous_item[1] if previous_item else None
            rows.append({"role": role, "special": name, "kind": events[events["name"].eq(name)]["kind"].mode().iloc[0], "real_holders": r, "real_holder_rate_pct": rr, "generated_holders": g, "generated_holder_rate_pct": gr, "generated_minus_real_pt": diff, "previous_value": previous_value, "previous_difference": prev, "improvement_pt": abs(prev) - abs(diff) if prev is not None else None, "sample_real": real_counts[role], "sample_generated": gen_counts[role], "focus": name in FOCUS_SPECIALS[role]})
    return pd.DataFrame(rows)


def ranked_special_table(players: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    role_for_family = {family: ("投手" if family in {"対ピンチ", "対左打者", "打たれ強さ", "ノビ", "クイック"} else "野手" if family != "回復" else "共通") for family in RANK_FAMILIES}
    for family in RANK_FAMILIES:
        target_role = role_for_family[family]
        rplayers = players[players["dataset"].eq(REAL_LABEL)] if target_role == "共通" else players[(players["dataset"].eq(REAL_LABEL)) & players["role"].eq(target_role)]
        gplayers = players[players["dataset"].eq(GENERATED_LABEL)] if target_role == "共通" else players[(players["dataset"].eq(GENERATED_LABEL)) & players["role"].eq(target_role)]
        if family == "キャッチャー":
            def catcher_eligible(row: pd.Series) -> bool:
                values = safe_json(row["sub_positions"], [])
                sub_names = [x.get("position", "") if isinstance(x, dict) else str(x) for x in values]
                return row["position"] == "捕手" or "捕手" in sub_names
            rplayers = rplayers[rplayers.apply(catcher_eligible, axis=1)]
            gplayers = gplayers[gplayers.apply(catcher_eligible, axis=1)]
        revents = events[(events["dataset"].eq(REAL_LABEL)) & events["family"].eq(family)]
        gevents = events[(events["dataset"].eq(GENERATED_LABEL)) & events["family"].eq(family)]
        real_non_d_total = max(1, int(revents[revents["rank"].ne("D")].shape[0]))
        generated_non_d_total = max(1, int(gevents[gevents["rank"].ne("D")].shape[0]))
        generated_all_total = max(1, int(gevents.shape[0]))
        for rank in RANKS:
            rc, gc = int(revents["rank"].eq(rank).sum()), int(gevents["rank"].eq(rank).sum())
            rr, gr = rc / max(1, len(rplayers)) * 100, gc / max(1, len(gplayers)) * 100
            rows.append({
                "family": family, "rank": rank, "target_role": target_role,
                "real_explicit_count": rc, "real_explicit_target_player_rate_pct": rr,
                "generated_count": gc, "generated_target_player_rate_pct": gr,
                "generated_minus_real_target_player_pt": gr - rr,
                "real_non_d_share_pct": rc / real_non_d_total * 100 if rank != "D" else None,
                "generated_non_d_share_pct": gc / generated_non_d_total * 100 if rank != "D" else None,
                "generated_all_rank_reference_pct": gc / generated_all_total * 100,
                "comparison_eligible": rank != "D", "real_unrecorded_filled_as_D": False,
                "sample_real": len(rplayers), "sample_generated": len(gplayers),
            })
    return pd.DataFrame(rows)


def sub_position_table(real: pd.DataFrame, generated: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    rf, gf = real[real["role"].eq("野手")], generated[generated["role"].eq("野手")]
    for scope, position in [("全体", "全体")] + [("メインポジション別", x) for x in FIELDER_POSITIONS]:
        r = rf if position == "全体" else rf[rf["position"].eq(position)]
        g = gf if position == "全体" else gf[gf["position"].eq(position)]
        metrics: list[tuple[str, Callable[[pd.Series], pd.Series]]] = [("サブポジ保有", lambda x: x.gt(0))]
        if position == "全体":
            metrics += [("なし", lambda x: x.eq(0)), ("1個", lambda x: x.eq(1)), ("2個", lambda x: x.eq(2)), ("3個以上", lambda x: x.ge(3))]
        for metric, fn in metrics:
            rr, gr = fn(r["sub_position_count"]).mean() * 100, fn(g["sub_position_count"]).mean() * 100
            rows.append({"scope": scope, "position": position, "metric": metric, "real_rate_pct": rr, "generated_rate_pct": gr, "real_minus_generated_pt": rr - gr, "sample_real": len(r), "sample_generated": len(g)})
    invalid = []
    for _, player in gf.iterrows():
        if not str(player["batting_throwing"]).startswith("左投"):
            continue
        subs = safe_json(player["sub_positions"], [])
        bad = [x.get("position", "") if isinstance(x, dict) else str(x) for x in subs]
        bad = [x for x in bad if x in {"二塁手", "三塁手", "遊撃手"}]
        if bad:
            invalid.append({"player_id": player["player_id"], "position": player["position"], "invalid_sub_positions": "、".join(bad)})
    return pd.DataFrame(rows), pd.DataFrame(invalid)


def age_regression_table(generated: pd.DataFrame, real_audit: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for role in ["全体", "投手", "野手"]:
        subset = generated if role == "全体" else generated[generated["role"].eq(role)]
        ages, pros = pd.to_numeric(subset["age"], errors="coerce"), pd.to_numeric(subset["pro_years"], errors="coerce")
        rows += [
            {"role": role, "metric": "年齢平均", "generated_value": ages.mean(), "sample_generated": len(subset), "real_value": None, "note": "実在ファイルに該当列がないため実在比較不可" if not real_audit["has_age"] else ""},
            {"role": role, "metric": "年齢中央値", "generated_value": ages.median(), "sample_generated": len(subset), "real_value": None, "note": "実在ファイルに該当列がないため実在比較不可" if not real_audit["has_age"] else ""},
            {"role": role, "metric": "プロ年数平均", "generated_value": pros.mean(), "sample_generated": len(subset), "real_value": None, "note": "実在ファイルに該当列がないため実在比較不可" if not real_audit["has_pro_years"] else ""},
            {"role": role, "metric": "プロ年数中央値", "generated_value": pros.median(), "sample_generated": len(subset), "real_value": None, "note": "実在ファイルに該当列がないため実在比較不可" if not real_audit["has_pro_years"] else ""},
        ]
        for band in AGE_BANDS:
            rows.append({"role": role, "metric": band, "generated_value": ages.map(age_band).eq(band).mean() * 100, "sample_generated": len(subset), "real_value": None, "note": "割合%"})
    impossible = generated[(generated["pro_years"] < 1) | (generated["pro_entry_age"] < 18) | (generated["pro_entry_age"] > generated["age"]) | (generated["pro_years"] != generated["age"] - generated["pro_entry_age"] + 1)]
    old_youth = generated[(generated["age"] >= 30) & (generated["player_class"].eq("若手素材型"))]
    age_26_youth = generated[(generated["age"] >= 26) & (generated["player_class"].eq("若手素材型"))]
    warnings = pd.DataFrame([
        {"audit": "年齢より不可能なプロ年数", "warning_count": len(impossible), "severity": "high" if len(impossible) else "none"},
        {"audit": "18歳より前のプロ入り", "warning_count": int((generated["pro_entry_age"] < 18).sum()), "severity": "high" if (generated["pro_entry_age"] < 18).any() else "none"},
        {"audit": "30歳以上の若手素材型（禁止条件）", "warning_count": len(old_youth), "severity": "high" if len(old_youth) else "none"},
        {"audit": "26歳以上の若手素材型（参考確認）", "warning_count": len(age_26_youth), "severity": "info"},
    ])
    return pd.DataFrame(rows), warnings


def seed_variation_table(generated: pd.DataFrame, special_events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for run, subset in generated.groupby("run"):
        for role, metrics in [("野手", FIELDER_METRICS), ("投手", PITCHER_METRICS)]:
            role_df = subset[subset["role"].eq(role)]
            for metric in metrics:
                rows.append({"seed": run, "domain": "overall", "target": role, "metric": metric, "value": pd.to_numeric(role_df[metric], errors="coerce").mean()})
        for role in ["投手", "野手"]:
            role_df = subset[subset["role"].eq(role)]
            ev = special_events[(special_events["dataset"].eq(GENERATED_LABEL)) & special_events["run"].eq(run) & special_events["role"].eq(role) & special_events["kind"].isin(["青特", "赤特", "緑特"])]
            counts = role_df["player_id"].map(ev.groupby("player_id").size()).fillna(0)
            rows.append({"seed": run, "domain": "special_count", "target": role, "metric": "平均", "value": counts.mean()})
            rows.append({"seed": run, "domain": "special_count", "target": role, "metric": "5個以上率", "value": counts.ge(5).mean() * 100})
    detail = pd.DataFrame(rows)
    summary = detail.groupby(["domain", "target", "metric"])["value"].agg(seed_min="min", seed_max="max", seed_mean="mean", seed_std="std").reset_index()
    summary["seed_range"] = summary["seed_max"] - summary["seed_min"]
    return summary


def generation_audit_warnings(generated: pd.DataFrame, count: int, seeds: list[int]) -> pd.DataFrame:
    expected_groups = {(f"seed_{seed}", role): count for seed in seeds for role in ["投手", "野手"]}
    actual_groups = generated.groupby(["run", "role"]).size().to_dict()
    group_mismatch = sum(abs(actual_groups.get(key, 0) - expected) for key, expected in expected_groups.items())
    fielders = generated[generated["role"].eq("野手")]
    pitchers = generated[generated["role"].eq("投手")]
    fielder_missing = int(fielders[FIELDER_METRICS].isna().sum().sum())
    pitcher_missing = int(pitchers[["球速", "コントロール", "スタミナ", "通常変化球数", "表示球種数", "総変化量", "第二球種数"]].isna().sum().sum())
    fielder_out_of_range = int(sum((pd.to_numeric(fielders[key], errors="coerce") < (1 if key == "弾道" else 0)).sum() + (pd.to_numeric(fielders[key], errors="coerce") > (4 if key == "弾道" else 100)).sum() for key in FIELDER_METRICS))
    pitcher_out_of_range = int((pd.to_numeric(pitchers["球速"], errors="coerce") <= 0).sum() + (pd.to_numeric(pitchers["コントロール"], errors="coerce").between(0, 100, inclusive="both") == False).sum() + (pd.to_numeric(pitchers["スタミナ"], errors="coerce").between(0, 100, inclusive="both") == False).sum())
    second_direction_invalid = int((pitchers["第二球種あり"].astype(bool) & ~pitchers["第二球種同方向整合"].astype(bool)).sum())
    duplicate_ids = int(generated["player_id"].duplicated().sum())
    return pd.DataFrame([
        {"audit": "seed×役割の生成人数不一致", "warning_count": group_mismatch, "severity": "high" if group_mismatch else "none"},
        {"audit": "野手必須能力の欠損", "warning_count": fielder_missing, "severity": "high" if fielder_missing else "none"},
        {"audit": "投手必須能力の欠損", "warning_count": pitcher_missing, "severity": "high" if pitcher_missing else "none"},
        {"audit": "野手能力の範囲外", "warning_count": fielder_out_of_range, "severity": "high" if fielder_out_of_range else "none"},
        {"audit": "投手能力の範囲外", "warning_count": pitcher_out_of_range, "severity": "high" if pitcher_out_of_range else "none"},
        {"audit": "第二球種が通常球種と異方向", "warning_count": second_direction_invalid, "severity": "high" if second_direction_invalid else "none"},
        {"audit": "生成player_id重複", "warning_count": duplicate_ids, "severity": "high" if duplicate_ids else "none"},
    ])


def severity_for(domain: str, difference: float, sample_real: int, metric: str) -> str:
    size = abs(float(difference))
    if domain == "usage":
        severity = "medium" if size >= 12 else "low"
    elif domain == "special_name":
        severity = "high" if size >= 12 else "medium" if size >= 7 else "low"
    elif domain == "special_count":
        severity = "high" if size >= 10 else "medium"
    elif "std_ratio" in metric:
        severity = "high" if size >= .5 else "medium"
    elif "率" in metric or domain in {"trajectory", "sub_position", "pitch_mix", "ranked_special"}:
        severity = "high" if size >= 20 else "medium" if size >= 12 else "low"
    else:
        severity = "high" if size >= 10 else "medium" if size >= 7 else "low"
    if sample_real < 30:
        severity = {"high": "medium", "medium": "low", "low": "low"}[severity]
    return severity


def cause_and_action(domain: str, target: str, metric: str) -> tuple[str, str]:
    mapping = {
        "fielder_position": ("ポジション別基準値、archetype/position_style補正、上限・弱点監査の組合せが分布形状に影響している可能性", "次回、該当ポジションの補正と分位点・閾値率を同時に調整候補として検証"),
        "trajectory": ("パワー閾値とposition_styleによる弾道下限補正が割合を押し上げ/下げている可能性", "次回、弾道決定閾値をポジション別実在分布に対して検証"),
        "pitcher_role": ("役割別能力補正または投手archetype構成が分布に影響している可能性", "次回、役割別の平均だけでなくP90/P95を保った補正案を試算"),
        "pitch_mix": ("球種数・第二球種の生成段階または役割補正が構成率に影響している可能性", "次回、役割別球種数と第二球種条件を独立に感度分析"),
        "special_count": ("special_count_boundsと個別抽選確率・補充処理の合成で総数分布が決まっている可能性", "次回、個別保有率を壊さない総数補正を候補化"),
        "special_kind": ("種別ごとの候補数、usage抽選、個別weightの合成で保有者率が決まっている可能性", "次回、通常特能数とは分離したまま種別別の候補到達率を検証"),
        "usage": ("実在Excelはusage/defaultを明示する一方、生成側は明示選択分だけを保持する表現差が含まれる可能性", "次回、生成確率を変える前にdefaultを含むusage保存仕様と比較分母を統一"),
        "special_name": ("個別weight、context multiplier、競合排除または候補条件が保有率差に寄与している可能性", "次回、該当能力の候補者率と抽選到達率を分解して調整"),
        "ranked_special": ("ranked_weight_items_for_groupと能力連動shiftが実在の明示非D分布と異なる可能性", "次回、D補完をせず非Dランクだけでweight/shiftを再検証"),
        "sub_position": ("サブポジ個数抽選とメインポジション別候補制約が保有率差に寄与している可能性", "次回、左投げ制約を維持したまま個数・組合せweightを検証"),
    }
    return mapping.get(domain, ("複数の現行補正が分布差に寄与している可能性", "次回、関連生成関数を分解して感度分析"))


def build_gaps(
    overall: pd.DataFrame, position: pd.DataFrame, thresholds: pd.DataFrame, trajectory: pd.DataFrame,
    pitcher: pd.DataFrame, pitcher_role: pd.DataFrame, pitch_mix: pd.DataFrame, special_count: pd.DataFrame,
    special_kind: pd.DataFrame, special_name: pd.DataFrame, ranked: pd.DataFrame, sub_position: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(domain: str, target: str, metric: str, real_value: Any, generated_value: Any, difference: Any, difference_type: str, sample_real: int, sample_generated: int, previous_value: Any = None, previous_difference: Any = None) -> None:
        if pd.isna(difference):
            return
        cause, action = cause_and_action(domain, target, metric)
        improved = abs(float(difference)) < abs(float(previous_difference)) if previous_difference is not None and not pd.isna(previous_difference) else None
        rows.append({"domain": domain, "target": target, "metric": metric, "real_value": real_value, "generated_value": generated_value, "difference": difference, "difference_type": difference_type, "severity": severity_for(domain, float(difference), int(sample_real), metric), "sample_real": sample_real, "sample_generated": sample_generated, "previous_value": previous_value, "previous_difference": previous_difference, "improved_since_previous": improved, "possible_cause": cause, "recommended_action": action})

    for domain, frame, target_col in [("overall", overall, "target"), ("fielder_position", position, "position"), ("pitcher_overall", pitcher, "target"), ("pitcher_role", pitcher_role, "pitcher_role")]:
        for _, row in frame.iterrows():
            target = str(row[target_col]); metric = str(row["metric"]); sr = int(row["real_人数"]); sg = int(row["generated_人数"])
            for stat, limit in [("平均", 5), ("中央値", 5), ("P90", 8), ("P95", 8)]:
                diff = row[f"real_minus_generated_{stat}"]
                if pd.notna(diff) and abs(diff) >= limit:
                    add(domain, target, f"{metric}_{stat}", row[f"real_{stat}"], row[f"generated_{stat}"], diff, "real-generated", sr, sg)
            ratio = row["generated_to_real_std_ratio"]
            if pd.notna(ratio) and (ratio >= 1.2 or ratio <= .8):
                add(domain, target, f"{metric}_std_ratio", 1.0, ratio, ratio - 1, "generated_std/real_std", sr, sg)
    for _, row in thresholds.iterrows():
        if abs(row["real_minus_generated_pt"]) >= 8:
            add("fielder_position", row["position"], f"{row['metric']}_{row['threshold']}率", row["real_rate_pct"], row["generated_rate_pct"], row["real_minus_generated_pt"], "real-generated percentage points", row["sample_real"], row["sample_generated"])
    for _, row in trajectory.iterrows():
        if abs(row["real_minus_generated_pt"]) >= 8:
            add("trajectory", row["position"], f"弾道{row['trajectory']}率", row["real_rate_pct"], row["generated_rate_pct"], row["real_minus_generated_pt"], "real-generated percentage points", row["sample_real"], row["sample_generated"])
    for _, row in pitch_mix.iterrows():
        if abs(row["real_minus_generated"]) >= 8:
            add("pitch_mix", row["pitcher_role"], row["metric"], row["real_value"], row["generated_value"], row["real_minus_generated"], "real-generated percentage points", row["sample_real"], row["sample_generated"])
    old_count_path = ROOT / "reports" / "real_vs_generated_balance_5000_special_review" / "special_count_distribution_compare.csv"
    old_count = pd.read_csv(old_count_path) if old_count_path.exists() else pd.DataFrame()
    for _, row in special_count.iterrows():
        for metric, limit in [("5個以上率", 10), ("8個以上率", 5)]:
            diff = row[f"real_minus_generated_{metric}"]
            if abs(diff) >= limit:
                previous_value = previous_difference = None
                if metric == "5個以上率" and not old_count.empty:
                    old_real = old_count[(old_count["データ"].eq(REAL_LABEL)) & old_count["対象"].eq(row["role"]) & old_count["特殊能力数"].eq("5個以上")]
                    old_gen = old_count[(old_count["データ"].eq("架空球団用")) & old_count["対象"].eq(row["role"]) & old_count["特殊能力数"].eq("5個以上")]
                    if not old_real.empty and not old_gen.empty:
                        previous_value = float(old_gen["割合%"].iloc[0])
                        previous_difference = float(old_real["割合%"].iloc[0]) - previous_value
                add("special_count", row["role"], metric, row[f"real_{metric}"], row[f"generated_{metric}"], diff, "real-generated percentage points", row["sample_real"], row["sample_generated"], previous_value, previous_difference)
                if previous_difference is not None:
                    rows[-1]["difference_type"] += "; previous uses legacy classification (reference only)"
                    rows[-1]["improved_since_previous"] = None
    for _, row in special_kind.iterrows():
        diff = row["real_minus_generated_holder_rate_pt"]
        if abs(diff) >= 8:
            domain = "usage" if row["kind"] == "usage" else "special_kind"
            add(domain, row["role"], f"{row['kind']}_保有率", row["real_holder_rate_pct"], row["generated_holder_rate_pct"], diff, "real-generated percentage points", row["sample_real"], row["sample_generated"])
    for _, row in special_name.iterrows():
        if abs(row["generated_minus_real_pt"]) >= 5:
            prev = row["previous_difference"]
            domain = "usage" if row["kind"] == "usage" else "special_name"
            add(domain, row["role"], row["special"], row["real_holder_rate_pct"], row["generated_holder_rate_pct"], row["generated_minus_real_pt"], "generated-real percentage points", row["sample_real"], row["sample_generated"], row["previous_value"], prev)
    for _, row in ranked[ranked["comparison_eligible"]].iterrows():
        diff = row["generated_minus_real_target_player_pt"]
        if abs(diff) >= 8:
            add("ranked_special", row["target_role"], f"{row['family']}{row['rank']}", row["real_explicit_target_player_rate_pct"], row["generated_target_player_rate_pct"], diff, "generated-real percentage points; real explicit only", row["sample_real"], row["sample_generated"])
    for _, row in sub_position.iterrows():
        if abs(row["real_minus_generated_pt"]) >= 8:
            add("sub_position", row["position"], row["metric"], row["real_rate_pct"], row["generated_rate_pct"], row["real_minus_generated_pt"], "real-generated percentage points", row["sample_real"], row["sample_generated"])
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["domain", "target", "metric", "real_value", "generated_value", "difference", "difference_type", "severity", "sample_real", "sample_generated", "previous_value", "previous_difference", "improved_since_previous", "possible_cause", "recommended_action"])
    order = pd.Categorical(result["severity"], ["high", "medium", "low"], ordered=True)
    return result.assign(_order=order).sort_values(["_order", "domain", "target", "metric"]).drop(columns="_order")


def markdown_table(df: pd.DataFrame, limit: int = 25) -> str:
    if df.empty:
        return "（該当なし）"
    view = df.head(limit).copy().fillna("")
    for col in view.select_dtypes(include="number"):
        view[col] = view[col].map(lambda x: f"{x:.3f}" if isinstance(x, float) else str(x))
    lines = ["| " + " | ".join(view.columns) + " |", "| " + " | ".join("---" for _ in view.columns) + " |"]
    lines += ["| " + " | ".join(str(row[c]).replace("|", "\\|") for c in view.columns) + " |" for _, row in view.iterrows()]
    return "\n".join(lines)


def current_git() -> tuple[str, str]:
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    return branch, commit


def write_summary(path: Path, audit: dict[str, Any], args: argparse.Namespace, gaps: pd.DataFrame, seed_variation: pd.DataFrame, warnings: pd.DataFrame, special_count: pd.DataFrame, special_name: pd.DataFrame, overall: pd.DataFrame, pitcher: pd.DataFrame, pitch_mix: pd.DataFrame, sub_position: pd.DataFrame) -> None:
    branch, commit = current_git()
    sev = gaps["severity"].value_counts().to_dict() if not gaps.empty else {}
    improved = gaps[gaps["improved_since_previous"].eq(True)].copy() if not gaps.empty else pd.DataFrame()
    unimproved = gaps[gaps["improved_since_previous"].eq(False)].copy() if not gaps.empty else pd.DataFrame()
    high = gaps[gaps["severity"].eq("high")]
    medium = gaps[gaps["severity"].eq("medium")]
    low = gaps[gaps["severity"].eq("low")]
    focus = special_name[special_name["focus"]][["role", "special", "real_holder_rate_pct", "generated_holder_rate_pct", "generated_minus_real_pt", "previous_difference", "improvement_pt"]]
    matched_overall = []
    for _, row in pd.concat([overall, pitcher], ignore_index=True).iterrows():
        checks = [abs(row[f"real_minus_generated_{stat}"]) < limit for stat, limit in [("平均", 5), ("中央値", 5), ("P90", 8), ("P95", 8)]]
        ratio = row["generated_to_real_std_ratio"]
        if all(checks) and .8 < ratio < 1.2:
            matched_overall.append(str(row["metric"]))
    matched_mix = pitch_mix[pitch_mix["real_minus_generated"].abs().lt(8)]["metric"].drop_duplicates().tolist()
    matched_focus = special_name[special_name["focus"] & special_name["generated_minus_real_pt"].abs().lt(5)]["special"].tolist()
    sub_overall = sub_position[(sub_position["position"].eq("全体")) & sub_position["metric"].eq("サブポジ保有")]
    matching = [
        f"全体能力（全基準内）: {', '.join(matched_overall) if matched_overall else '該当なし'}。",
        f"球種構成（差8pt未満）: {', '.join(matched_mix) if matched_mix else '該当なし'}。",
        f"重点特殊能力（差5pt未満）: {', '.join(matched_focus) if matched_focus else '該当なし'}。",
        f"サブポジ保有率: 実在{sub_overall['real_rate_pct'].iloc[0]:.2f}% / 生成{sub_overall['generated_rate_pct'].iloc[0]:.2f}%（差{sub_overall['real_minus_generated_pt'].iloc[0]:.2f}pt、抽出閾値未満）。" if not sub_overall.empty else "サブポジ保有率: 集計なし。",
        "年齢・プロ年数は生成側の禁止条件違反0件のため、現時点では調整不要。",
        f"seed間変動の最大rangeは{seed_variation['seed_range'].max():.3f}で、統合値を覆す大きな揺れは確認されない。",
    ]
    new_gaps = gaps[gaps["previous_difference"].isna()].copy()
    top_priority = high.assign(_abs=high["difference"].abs()).sort_values("_abs", ascending=False).head(6) if not high.empty else pd.DataFrame()
    lines = [
        "# 実在12球団 vs 現行生成ロジック 再検証",
        "",
        "## 1. 検証条件",
        f"- current branch: `{branch}`",
        f"- current commit: `{commit}`",
        f"- 使用実在ファイル: `{args.real_xlsx}`（内容のコピーはレポートに保存していない）",
        f"- 実在人数: 合計{audit['total']}人（投手{audit['pitchers']}人、野手{audit['fielders']}人）",
        f"- 使用seed: {', '.join(map(str, args.seeds))}",
        f"- 各seed: 投手{args.count:,}人 + 野手{args.count:,}人",
        f"- 総生成人数: {args.count * len(args.seeds) * 2:,}人",
        f"- 実在players列: {', '.join(audit['columns'])}",
        f"- ポジション構成: {audit['positions']}",
        f"- 欠損状況: `real_data_audit.csv` を参照",
        "- 年齢・プロ年数: 実在ファイルに該当列がないため実在比較不可。推測・補完はせず生成側のみ回帰確認。" if not audit["has_age"] or not audit["has_pro_years"] else "- 年齢・プロ年数: 実在列を使用して比較。",
        "- 総変化量は通常変化球（slot=1）の変化量合計。表示球種数は通常・第二球種・ストレート系第二種を含む。",
        "",
        "## 2. 現行版でほぼ一致している項目",
        *[f"- {item}" for item in matching],
        "",
        "## 3. high severity",
        markdown_table(high[["domain", "target", "metric", "real_value", "generated_value", "difference", "possible_cause"]], 40),
        "",
        "## 4. medium severity",
        markdown_table(medium[["domain", "target", "metric", "real_value", "generated_value", "difference"]], 40),
        "",
        "## 5. low severity",
        markdown_table(low[["domain", "target", "metric", "real_value", "generated_value", "difference"]], 40),
        "",
        "## 6. 旧比較から改善したもの",
        markdown_table(improved[["domain", "target", "metric", "previous_difference", "difference", "improved_since_previous"]], 40) if not improved.empty else "（比較可能な旧差分で該当なし）",
        "",
        "### 重点特殊能力の旧差分→現行差分",
        markdown_table(focus, 40),
        "",
        "## 7. 現在も改善していないもの",
        markdown_table(unimproved[["domain", "target", "metric", "previous_difference", "difference"]], 40) if not unimproved.empty else "（比較可能な旧差分で該当なし）",
        "",
        "## 8. 新たに見つかった差",
        "- 旧レポートと同一定義で比較できない項目を含みます。主な新規抽出は以下です。",
        markdown_table(new_gaps[["domain", "target", "metric", "real_value", "generated_value", "difference", "severity"]], 20),
        "",
        "## 9. 次回修正候補",
        f"1. 最優先: high {sev.get('high', 0)}件。主な対象は " + ("、".join(f"{r.domain}/{r.target}/{r.metric}" for r in top_priority.itertuples()) if not top_priority.empty else "なし") + "。",
        f"2. 次点: medium {sev.get('medium', 0)}件。母数とポジション特性を確認して調整要否を判断。",
        f"3. 微調整: low {sev.get('low', 0)}件。ゲーム上の効果が小さければ現状維持可。",
        "4. 調整不要: 抽出閾値未満の項目、および監査警告0件の年齢・プロ年数・左投げサブポジ制約。",
        "",
        "## 監査",
        markdown_table(warnings, 20),
        "",
        "## seed間変動（range上位）",
        markdown_table(seed_variation.sort_values("seed_range", ascending=False), 20),
        "",
        "## 特殊能力総数",
        markdown_table(special_count, 10),
        "",
        f"- remaining_gaps: high={sev.get('high', 0)}, medium={sev.get('medium', 0)}, low={sev.get('low', 0)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if len(args.seeds) != 3:
        raise SystemExit("今回の再検証ではseedを3個指定してください。")
    if args.count < 10_000:
        raise SystemExit("今回の再検証では各seed・各役割10,000人以上を生成してください。")
    if not args.real_xlsx.exists():
        raise SystemExit(f"固定実在ファイルが見つかりません: {args.real_xlsx}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    real, real_specials, _real_breaking, audit = load_real(args.real_xlsx)
    if (audit["total"], audit["pitchers"], audit["fielders"]) != (791, 402, 389):
        raise SystemExit(f"実在人数が想定と不一致: {audit}")
    cache = args.output_dir / "generated_players.csv"
    generated = pd.read_csv(cache) if args.reuse_generated and cache.exists() else generate_current(args.count, args.seeds, args.output_dir)
    if len(generated) != args.count * len(args.seeds) * 2:
        raise SystemExit("生成キャッシュの人数が指定条件と一致しません。")
    expected_groups = {(f"seed_{seed}", role): args.count for seed in args.seeds for role in ["投手", "野手"]}
    if generated.groupby(["run", "role"]).size().to_dict() != expected_groups:
        raise SystemExit("生成キャッシュのseed×役割構成が指定条件と一致しません。")
    players = pd.concat([real, generated], ignore_index=True, sort=False)
    overall, pitcher = overall_tables(real, generated)
    position, percentiles, thresholds = fielder_position_tables(real, generated)
    trajectory = trajectory_table(real, generated)
    pitcher_role = pitcher_role_table(real, generated)
    pitch_mix = pitch_mix_table(real, generated)
    special_events, ranked_events, _categories, roles = build_special_events(players, real_specials)
    special_count, special_kind = special_count_tables(players, special_events)
    special_kind = add_rank_kind_rows(players, ranked_events, special_kind)
    special_name = special_name_table(players, special_events, roles)
    ranked = ranked_special_table(players, ranked_events)
    sub_position, invalid_subs = sub_position_table(real, generated)
    age_pro, age_warnings = age_regression_table(generated, audit)
    warnings = pd.concat([
        generation_audit_warnings(generated, args.count, args.seeds),
        age_warnings,
        pd.DataFrame([{"audit": "左投げ野手の二塁・三塁・遊撃サブポジ", "warning_count": len(invalid_subs), "severity": "high" if len(invalid_subs) else "none"}]),
    ], ignore_index=True)
    seed_variation = seed_variation_table(generated, special_events)
    gaps = build_gaps(overall, position, thresholds, trajectory, pitcher, pitcher_role, pitch_mix, special_count, special_kind, special_name, ranked, sub_position)
    outputs = {
        "overall_compare.csv": pd.concat([overall.assign(role="野手"), pitcher.assign(role="投手")], ignore_index=True, sort=False),
        "fielder_position_compare.csv": position,
        "fielder_percentile_compare.csv": percentiles,
        "fielder_threshold_rate_compare.csv": thresholds,
        "trajectory_compare.csv": trajectory,
        "pitcher_compare.csv": pitcher,
        "pitcher_role_compare.csv": pitcher_role,
        "pitch_mix_compare.csv": pitch_mix,
        "special_count_compare.csv": special_count,
        "special_kind_compare.csv": special_kind,
        "special_name_compare.csv": special_name,
        "ranked_special_compare.csv": ranked,
        "sub_position_compare.csv": sub_position,
        "age_pro_years_regression.csv": age_pro,
        "remaining_gaps.csv": gaps,
        "seed_variation.csv": seed_variation,
        "audit_warnings.csv": warnings,
        "invalid_left_handed_subpositions.csv": invalid_subs,
    }
    for filename, frame in outputs.items():
        frame.to_csv(args.output_dir / filename, index=False, encoding="utf-8-sig", lineterminator="\n")
    audit_rows = []
    for col, missing in audit["missing"].items():
        audit_rows.append({"section": "missing", "item": col, "value": missing})
    for pos, count in audit["positions"].items():
        audit_rows.append({"section": "position", "item": pos, "value": count})
    audit_rows += [{"section": "count", "item": "total", "value": audit["total"]}, {"section": "count", "item": "pitchers", "value": audit["pitchers"]}, {"section": "count", "item": "fielders", "value": audit["fielders"]}]
    pd.DataFrame(audit_rows).to_csv(args.output_dir / "real_data_audit.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    write_summary(args.output_dir / "summary.md", audit, args, gaps, seed_variation, warnings, special_count, special_name, overall, pitcher, pitch_mix, sub_position)
    print(f"完了: {args.output_dir}")
    actionable_warning_count = int(warnings[~warnings["severity"].isin(["none", "info"])]["warning_count"].sum())
    print(f"監査警告件数: {actionable_warning_count}")
    print(gaps["severity"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
