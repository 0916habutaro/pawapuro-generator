from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import CATEGORIES, load_master_data, generate_player, ability_numeric_value, pitch_movement, POSITION_RESTRICTED_SPECIALS, RELIEF_REQUIRED_SPECIALS, has_position_aptitude, has_pitcher_aptitude, normalize_sub_positions
from scripts.validate_ability_balance import flatten_players

THRESHOLDS = {
    "rank_A_min": 1.0, "rank_A_max": 3.0, "rank_B_min": 5.0, "rank_B_max": 10.0,
    "rank_C_min": 14.0, "rank_C_max": 24.0, "rank_D_min": 38.0, "rank_D_max": 55.0,
    "rank_E_min": 14.0, "rank_E_max": 24.0, "rank_F_min": 5.0, "rank_F_max": 10.0,
    "rank_G_min": 1.0, "rank_G_max": 3.0, "subpos_rate_min": 60.0, "subpos_rate_max": 72.0,
    "subpos_3plus_nonutility_max": 0, "draft18_3plus_max": 0, "cleanup_3plus_max": 0,
}
CONFLICT_PAIRS = [("積極打法", "慎重打法"), ("強振多用", "ミート多用"), ("ミート多用", "強振多用"), ("積極盗塁", "慎重盗塁"), ("速球中心", "変化球中心"), ("投球位置左", "投球位置右"), ("チームプレイ○", "チームプレイ×")]
UTILITY_ROLES = {"ユーティリティ"}
UTILITY_STYLES = {"走攻守外野手", "守備走塁遊撃手", "守備走塁二塁手"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="第3段階の特殊能力・ランク系・サブポジション検証を行います。")
    p.add_argument("--count", type=int, default=10000, help="カテゴリ×投手/野手ごとの人数")
    p.add_argument("--seed", type=int, default=202607130000)
    p.add_argument("--output-dir", type=Path, default=Path("/tmp/pawapuro-phase3-validation"))
    return p.parse_args()


def classify_special(name: str) -> str:
    if any(word in name for word in ["怪童", "怪物", "精密機械", "鉄腕", "アーチスト", "安打製造機", "電光石火", "魔術師", "球界の頭脳"]): return "金特"
    if name in {"三振", "四球", "一発", "乱調", "エラー", "併殺", "負け運", "寸前", "抜け球", "軽い球"}: return "赤特"
    if name in {"積極打法", "慎重打法", "積極走塁", "慎重盗塁", "積極盗塁", "選球眼", "積極守備", "チームプレイ○", "チームプレイ×", "テンポ○", "速球中心", "変化球中心", "投球位置左", "投球位置右", "強振多用", "ミート多用"}: return "緑特"
    if "○" in name and "×" in name: return "青赤特"
    return "青特"


def generate(count: int, seed: int) -> list[dict[str, Any]]:
    master = load_master_data(); players=[]; offset=0
    for category in CATEGORIES:
        for role in ["投手", "野手"]:
            print(f"{category} / {role} / {count}人", flush=True)
            for _ in range(count):
                players.append(generate_player(role, category, master, seed + offset)); offset += 1
    return players


def special_constraint_violations(player: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    role = player.get("role", "")
    position = player.get("position", "")
    subs = normalize_sub_positions(player.get("sub_positions", []))
    pitcher_aptitudes = {key: player.get(key) or player.get("abilities", {}).get(key) for key in ["starter_aptitude", "reliever_aptitude", "closer_aptitude"]}
    all_specs = list(player.get("special_abilities", [])) + list(player.get("abilities", {}).get("ranked_specials", {}).values())
    for name in all_specs:
        reason = ""
        if role == "野手" and name in POSITION_RESTRICTED_SPECIALS and not has_position_aptitude(position, subs, POSITION_RESTRICTED_SPECIALS[name]):
            reason = f"{','.join(sorted(POSITION_RESTRICTED_SPECIALS[name]))}適性なし"
        elif role == "野手" and str(name).startswith("キャッチャー") and not has_position_aptitude(position, subs, {"捕手"}):
            reason = "捕手適性なし"
        elif role == "投手" and name in RELIEF_REQUIRED_SPECIALS and not has_pitcher_aptitude(pitcher_aptitudes, {"reliever_aptitude", "closer_aptitude"}):
            reason = "救援適性なし"
        if reason:
            rows.append({
                "seed": str(player.get("seed", "")), "category": str(player.get("category", "")), "role": str(role),
                "position": str(position), "sub_positions": " / ".join(f"{s['position']}{s['aptitude']}" for s in subs),
                "starter_aptitude": str(pitcher_aptitudes.get("starter_aptitude") or ""),
                "reliever_aptitude": str(pitcher_aptitudes.get("reliever_aptitude") or ""),
                "closer_aptitude": str(pitcher_aptitudes.get("closer_aptitude") or ""),
                "special": str(name), "reason": reason,
            })
    return rows

def special_tables(players: list[dict[str, Any]], df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    events=[]
    for p in players:
        violations = {v["special"]: v["reason"] for v in special_constraint_violations(p)}
        subs = normalize_sub_positions(p.get("sub_positions", []))
        for name in p.get("special_abilities", []):
            events.append({"seed":p["seed"], "category":p["category"], "role":p["role"], "position":p["position"], "sub_positions":" / ".join(f"{s['position']}{s['aptitude']}" for s in subs), "starter_aptitude":p.get("starter_aptitude", ""), "reliever_aptitude":p.get("reliever_aptitude", ""), "closer_aptitude":p.get("closer_aptitude", ""), "constraint_ok": name not in violations, "violation_reason": violations.get(name, ""), "player_class":p.get("player_class",""), "archetype":p.get("archetype",""), "position_style":p.get("position_style",""), "development_stage":p.get("development_stage",""), "acquisition_role":p.get("acquisition_role",""), "weakness_profile":p.get("weakness_profile",""), "special":name, "kind":classify_special(name)})
    ev=pd.DataFrame(events)
    work=df.copy()
    work["通常特殊能力数_検証"] = pd.to_numeric(work.get("特殊能力数", 0), errors="coerce").fillna(0).astype(int)
    rows=[]
    for cols in [[], ["category"], ["role"], ["position"], ["player_class"], ["archetype"], ["position_style"], ["development_stage"], ["acquisition_role"], ["weakness_profile"], ["category","role"]]:
        grouped=work.groupby(cols, dropna=False) if cols else [((), work)]
        for key, sub in grouped:
            if not isinstance(key, tuple): key=(key,)
            vals=sub["通常特殊能力数_検証"]
            base={"集計軸":"/".join(cols) if cols else "全体", **{c:v for c,v in zip(cols,key)}, "人数":len(sub), "平均":round(float(vals.mean()),3), "中央値":float(vals.median())}
            for n in range(6): base[f"{n}個率%"] = round(float(vals.eq(n).mean()*100),2)
            base["6個以上率%"] = round(float(vals.ge(6).mean()*100),2)
            rows.append(base)
    top=ev.groupby(["kind","special"]).size().reset_index(name="件数").sort_values("件数", ascending=False).groupby("kind").head(20) if not ev.empty else pd.DataFrame()
    kind=ev.groupby("kind").size().reset_index(name="件数") if not ev.empty else pd.DataFrame()
    return {"special_count_metrics":pd.DataFrame(rows), "special_kind_metrics":kind, "special_top20":top, "special_events":ev}

def ranked_tables(players: list[dict[str, Any]], df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rows=[]
    for p in players:
        for group,name in p["abilities"].get("ranked_specials", {}).items(): rows.append({"seed":p["seed"], "category":p["category"], "role":p["role"], "position":p["position"], "player_class":p.get("player_class",""), "archetype":p.get("archetype",""), "age_band":pd.cut(pd.Series([p["age"]]), [0,19,22,26,30,34,99], labels=["18-19","20-22","23-26","27-30","31-34","35+"]).iloc[0], "group":group, "rank":str(name)[-1:]})
    ev=pd.DataFrame(rows)
    if ev.empty: return {"rank_distribution":pd.DataFrame(), "rank_group_distribution":pd.DataFrame(), "rank_context_distribution":pd.DataFrame()}
    dist=ev.groupby("rank").size().reset_index(name="件数"); dist["割合%"]=(dist["件数"]/len(ev)*100).round(2)
    group=ev.groupby(["group","rank"]).size().reset_index(name="件数")
    ctx=[]
    for col in ["category","role","position","player_class","archetype","age_band"]:
        for keys, sub in ev.groupby([col,"rank"], dropna=False): ctx.append({"集計軸":col,"値":keys[0],"rank":keys[1],"件数":len(sub),"割合%":round(len(sub)/max(1,len(ev[ev[col].eq(keys[0])]))*100,2)})
    return {"rank_distribution":dist, "rank_group_distribution":group, "rank_context_distribution":pd.DataFrame(ctx)}


def subpos_tables(players: list[dict[str, Any]], df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    fielders=[p for p in players if p["role"]=="野手"]; rows=[]; combos=[]
    for p in fielders:
        subs=p.get("sub_positions",[])
        rows.append({"seed":p["seed"], "category":p["category"], "age":p["age"], "position":p["position"], "player_class":p.get("player_class",""), "position_style":p.get("position_style",""), "acquisition_role":p.get("acquisition_role",""), "count":len(subs), "has":bool(subs), "aptitudes":"".join(s.get("aptitude","") for s in subs)})
        for s in subs: combos.append({"main":p["position"], "sub":s.get("position"), "aptitude":s.get("aptitude"), "category":p["category"], "seed":p["seed"]})
    d=pd.DataFrame(rows); c=pd.DataFrame(combos)
    summary=[]
    for cols in [[], ["category"], ["player_class"], ["position_style"], ["acquisition_role"]]:
        grouped=d.groupby(cols, dropna=False) if cols else [((), d)]
        for key, sub in grouped:
            if not isinstance(key, tuple): key=(key,)
            total_apt=sum(len(x) for x in sub["aptitudes"])
            summary.append({"集計軸":"/".join(cols) if cols else "全体", **{col:val for col,val in zip(cols,key)}, "人数":len(sub), "保有率%":round(sub["has"].mean()*100,2), "0個率%":round(sub["count"].eq(0).mean()*100,2), "1個率%":round(sub["count"].eq(1).mean()*100,2), "2個率%":round(sub["count"].eq(2).mean()*100,2), "3個以上率%":round(sub["count"].ge(3).mean()*100,2), "◎%":round(sum(x.count("◎") for x in sub["aptitudes"])/max(1,total_apt)*100,2), "○%":round(sum(x.count("○") for x in sub["aptitudes"])/max(1,total_apt)*100,2), "△%":round(sum(x.count("△") for x in sub["aptitudes"])/max(1,total_apt)*100,2)})
    return {"sub_position_metrics":pd.DataFrame(summary), "sub_position_combinations":c.groupby(["main","sub","aptitude"]).size().reset_index(name="件数") if not c.empty else c}


def warnings(players: list[dict[str, Any]]) -> pd.DataFrame:
    rows=[]
    for p in players:
        specs=p.get("special_abilities",[]); specset=set(specs); subs=p.get("sub_positions",[])
        for a,b in CONFLICT_PAIRS:
            if a in specset and b in specset: rows.append({"seed":p["seed"],"type":"競合能力","detail":f"{a}/{b}"})
        for violation in special_constraint_violations(p):
            rows.append({"seed": p["seed"], "type": "特殊能力制約違反", "detail": f"{violation['special']}:{violation['reason']}", **{k: violation[k] for k in ["category", "role", "position", "sub_positions", "starter_aptitude", "reliever_aptitude", "closer_aptitude"]}})
        rks=p["abilities"].get("ranked_specials",{})
        positions=[s.get("position") for s in subs]
        if p["position"] in positions: rows.append({"seed":p["seed"],"type":"メインと同じサブポジション","detail":p["position"]})
        for pos,cnt in Counter(positions).items():
            if cnt>1: rows.append({"seed":p["seed"],"type":"同一サブポジション重複","detail":pos})
        if any(s.get("aptitude") not in {"◎","○","△"} for s in subs): rows.append({"seed":p["seed"],"type":"不正適性","detail":str(subs)})
        utility=p.get("acquisition_role") in UTILITY_ROLES or p.get("position_style") in UTILITY_STYLES
        if len(subs)>=3 and not utility: rows.append({"seed":p["seed"],"type":"ユーティリティ条件外の3個以上","detail":str(subs)})
        if p["category"]=="ドラフト候補用" and p["age"]<=18 and len(subs)>=3: rows.append({"seed":p["seed"],"type":"18歳ドラフト過剰多ポジション","detail":str(subs)})
        if p.get("acquisition_role")=="主砲候補" and len(subs)>=3: rows.append({"seed":p["seed"],"type":"主砲候補過剰多ポジション","detail":str(subs)})
        for s in subs:
            if s.get("position")=="捕手" and (ability_numeric_value(p["abilities"], "肩力") or 0)<60: rows.append({"seed":p["seed"],"type":"捕手適性条件不足","detail":str(s)})
            if s.get("position")=="遊撃手" and min(ability_numeric_value(p["abilities"], "肩力") or 0, ability_numeric_value(p["abilities"], "守備力") or 0)<50: rows.append({"seed":p["seed"],"type":"遊撃手適性条件不足","detail":str(s)})
    return pd.DataFrame(rows)


def main() -> None:
    args=parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    players=generate(args.count, args.seed); df=flatten_players(players)
    tables={"players":df, **special_tables(players, df), **ranked_tables(players, df), **subpos_tables(players, df), "warnings":warnings(players)}
    for name, table in tables.items(): table.to_csv(args.output_dir/f"{name}.csv", index=False, encoding="utf-8-sig")
    summary={"players":len(players), "warnings":len(tables["warnings"]), "warning_types":tables["warnings"]["type"].value_counts().to_dict() if not tables["warnings"].empty else {}}
    (args.output_dir/"phase3_summary.txt").write_text(str(summary), encoding="utf-8")
    print(summary)

if __name__ == "__main__":
    main()
