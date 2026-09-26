"""Generate a large deterministic sample and print pro-years balance checks."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


ENTRY_AGE_BANDS = ["18～19歳", "20～21歳", "22～23歳", "24～26歳", "27歳以上"]
PRO_YEAR_BANDS = ["1～2年", "3～5年", "6～9年", "10～14年", "15～19年", "20年以上"]


def entry_age_band(age: int) -> str:
    if age <= 19: return "18～19歳"
    if age <= 21: return "20～21歳"
    if age <= 23: return "22～23歳"
    if age <= 26: return "24～26歳"
    return "27歳以上"


def pro_year_band(years: int) -> str:
    if years <= 2: return "1～2年"
    if years <= 5: return "3～5年"
    if years <= 9: return "6～9年"
    if years <= 14: return "10～14年"
    if years <= 19: return "15～19年"
    return "20年以上"


def frame_for_role(master: app.MasterData | None, role: str, count: int, seed_start: int, *, career_only: bool = False) -> pd.DataFrame:
    rows = []
    for seed in range(seed_start, seed_start + count):
        if career_only:
            age = app.age_for(random.Random(seed), "架空球団用")
            player = {"seed": seed, "role": role, "age": age, **app.generate_career_history(category="架空球団用", age=age, seed=seed, role=role)}
        else:
            player = app.generate_player(role, "架空球団用", master, seed=seed)
        rows.append({key: player[key] for key in ["seed", "role", "age", "entry_route", "pro_entry_age", "pro_years"]})
    return pd.DataFrame(rows)


def print_table(title: str, frame: pd.DataFrame) -> None:
    print(f"\n## {title}")
    print(frame.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10_000, help="投手・野手それぞれの生成数")
    parser.add_argument("--batches", type=int, default=1, help="固定seed系列数")
    parser.add_argument("--career-only", action="store_true", help="能力生成を省略し、同じ年齢・経歴乱数列だけを高速検証")
    args = parser.parse_args()
    master = None if args.career_only else app.load_master_data()
    batches = []
    for batch in range(args.batches):
        pitchers = frame_for_role(master, "投手", args.count, 1_000_000 + batch * 2_000_000, career_only=args.career_only)
        fielders = frame_for_role(master, "野手", args.count, 2_000_000 + batch * 2_000_000, career_only=args.career_only)
        batch_frame = pd.concat([pitchers, fielders], ignore_index=True)
        batch_frame["固定seed系列"] = batch + 1
        batches.append(batch_frame)
    players = pd.concat(batches, ignore_index=True)
    players["年齢帯"] = pd.Categorical(players["age"].apply(app.career_age_band), categories=app.CAREER_AGE_BAND_ORDER, ordered=True)
    players["プロ入り年齢帯"] = pd.Categorical(players["pro_entry_age"].apply(entry_age_band), categories=ENTRY_AGE_BANDS, ordered=True)
    players["プロ年数帯"] = pd.Categorical(players["pro_years"].apply(pro_year_band), categories=PRO_YEAR_BANDS, ordered=True)

    grouped = players.groupby(["role", "年齢帯"], observed=False)["pro_years"]
    stats = grouped.agg(["count", "mean", "median", "min", "max"]).reset_index()
    quantiles = grouped.quantile([0.10, 0.25, 0.75, 0.90]).unstack().reset_index().rename(columns={0.10: "P10", 0.25: "P25", 0.75: "P75", 0.90: "P90"})
    stats = stats.merge(quantiles, on=["role", "年齢帯"], how="left")
    stats["mean"] = stats["mean"].round(2)
    print_table("年齢帯別プロ年数（投手・野手別）", stats.rename(columns={"role": "役割", "count": "人数", "mean": "平均", "median": "中央値", "min": "最小", "max": "最大"}))
    total_grouped = players.groupby("年齢帯", observed=False)["pro_years"]
    total_stats = total_grouped.agg(人数="count", 平均="mean", 中央値="median", 最小="min", 最大="max").reset_index()
    total_quantiles = total_grouped.quantile([0.10, 0.25, 0.75, 0.90]).unstack().reset_index().rename(
        columns={0.10: "P10", 0.25: "P25", 0.75: "P75", 0.90: "P90"}
    )
    total_stats = total_stats.merge(total_quantiles, on="年齢帯", how="left")
    total_stats["平均"] = total_stats["平均"].round(2)
    print_table("年齢帯別プロ年数（合計）", total_stats)

    batch_summary = players.groupby("固定seed系列")["pro_years"].agg(人数="count", 平均="mean", 中央値="median").reset_index()
    batch_summary["平均"] = batch_summary["平均"].round(3)
    print_table("固定seed系列別サマリー", batch_summary)
    batch_routes = pd.crosstab(players["固定seed系列"], players["entry_route"], normalize="index").mul(100).round(2).reset_index()
    print_table("固定seed系列別入団経路%", batch_routes)
    batch_ages = players.groupby(["固定seed系列", "年齢帯"], observed=False)["pro_years"].mean().round(2).unstack().reset_index()
    print_table("固定seed系列別年齢帯pro_years平均", batch_ages)
    batch_age_dist = pd.crosstab(players["固定seed系列"], players["年齢帯"], normalize="index").mul(100).round(2).reset_index()
    print_table("固定seed系列別年齢帯人数%", batch_age_dist)
    extreme_rows = []
    for batch, frame in players.groupby("固定seed系列"):
        checks = {
            "20歳以下かつ4年以上": frame.age.le(20) & frame.pro_years.ge(4),
            "22歳以下かつ6年以上": frame.age.le(22) & frame.pro_years.ge(6),
            "27～30歳かつ2年以下": frame.age.between(27, 30) & frame.pro_years.le(2),
            "27～30歳かつ10年以上": frame.age.between(27, 30) & frame.pro_years.ge(10),
            "35歳以上かつ5年以下": frame.age.ge(35) & frame.pro_years.le(5),
            "35歳以上かつ15年以上": frame.age.ge(35) & frame.pro_years.ge(15),
            "40歳以上かつ20年以上": frame.age.ge(40) & frame.pro_years.ge(20),
        }
        for label, mask in checks.items():
            extreme_rows.append({"固定seed系列": batch, "条件": label, "人数": int(mask.sum()), "全体比%": round(mask.mean() * 100, 3)})
    print_table("固定seed系列別極端ケース", pd.DataFrame(extreme_rows))

    entry_dist = players["プロ入り年齢帯"].value_counts(sort=False).rename_axis("プロ入り年齢帯").reset_index(name="人数")
    entry_dist["構成比%"] = (entry_dist["人数"] / len(players) * 100).round(2)
    print_table("プロ入り年齢分布", entry_dist)
    print_table("現在年齢帯 × プロ入り年齢帯%", pd.crosstab(players["年齢帯"], players["プロ入り年齢帯"], normalize="index").mul(100).round(2).reset_index())

    pro_dist = players["プロ年数帯"].value_counts(sort=False).rename_axis("プロ年数帯").reset_index(name="人数")
    pro_dist["構成比%"] = (pro_dist["人数"] / len(players) * 100).round(2)
    print_table("プロ年数帯 全体", pro_dist)
    role_pro = players.groupby(["role", "プロ年数帯"], observed=False).size().reset_index(name="人数")
    role_pro["構成比%"] = (role_pro["人数"] / role_pro.groupby("role")["人数"].transform("sum") * 100).round(2)
    print_table("プロ年数帯 投手野手別", role_pro)
    age_pro = players.groupby(["年齢帯", "プロ年数帯"], observed=False).size().reset_index(name="人数")
    age_pro["構成比%"] = (age_pro["人数"] / age_pro.groupby("年齢帯", observed=False)["人数"].transform("sum") * 100).round(2)
    print_table("プロ年数帯 年齢帯別", age_pro)

    specific_rows = []
    for label, mask in [
        ("22歳", players.age.eq(22)), ("25歳", players.age.eq(25)), ("28歳", players.age.eq(28)),
        ("30歳", players.age.eq(30)), ("32歳", players.age.eq(32)), ("35歳", players.age.eq(35)),
        ("38歳", players.age.eq(38)), ("40歳以上", players.age.ge(40)),
    ]:
        part = players[mask]
        modes = ", ".join(str(int(value)) for value in part.pro_years.mode().tolist())
        entry_text = ", ".join(f"{band}:{count / len(part) * 100:.1f}%" for band, count in part["プロ入り年齢帯"].value_counts(sort=False).items())
        specific_rows.append({"年齢": label, "人数": len(part), "平均": round(part.pro_years.mean(), 2), "中央値": part.pro_years.median(), "主なpro_years": modes, "プロ入り年齢帯分布": entry_text})
    print_table("特定年齢", pd.DataFrame(specific_rows))

    route_dist = players["entry_route"].value_counts().rename_axis("入団経路").reset_index(name="人数")
    route_dist["構成比%"] = (route_dist["人数"] / len(players) * 100).round(2)
    print_table("入団経路分布", route_dist)
    print_table("入団経路 × 年齢帯", pd.crosstab(players["entry_route"], players["年齢帯"]).reset_index())

    examples = pd.DataFrame([
        {"確認例": "22歳・高卒・5年目", "件数": int(((players.age == 22) & (players.entry_route == "高卒") & (players.pro_years == 5)).sum())},
        {"確認例": "22歳・大卒・1年目", "件数": int(((players.age == 22) & (players.entry_route == "大卒") & (players.pro_years == 1)).sum())},
        {"確認例": "28歳・高卒・11年目", "件数": int(((players.age == 28) & (players.entry_route == "高卒") & (players.pro_years == 11)).sum())},
        {"確認例": "28歳・大卒・7年目", "件数": int(((players.age == 28) & (players.entry_route == "大卒") & (players.pro_years == 7)).sum())},
        {"確認例": "28歳・社会人・3～6年目", "件数": int(((players.age == 28) & (players.entry_route == "社会人") & players.pro_years.between(3, 6)).sum())},
        {"確認例": "35歳・高卒・長期在籍（16年以上）", "件数": int(((players.age == 35) & (players.entry_route == "高卒") & (players.pro_years >= 16)).sum())},
        {"確認例": "35歳・大卒・中堅～ベテラン（12年以上）", "件数": int(((players.age == 35) & (players.entry_route == "大卒") & (players.pro_years >= 12)).sum())},
        {"確認例": "35歳・社会人・比較的短い（11年以下）", "件数": int(((players.age == 35) & (players.entry_route == "社会人") & (players.pro_years <= 11)).sum())},
    ])
    print_table("指定例の出現件数", examples)

    invalid = pd.DataFrame([
        {"監査項目": "pro_years < 1", "件数": int((players.pro_years < 1).sum())},
        {"監査項目": "pro_entry_age > age", "件数": int((players.pro_entry_age > players.age).sum())},
        {"監査項目": "基本式不一致", "件数": int((players.pro_years != players.age - players.pro_entry_age + 1).sum())},
        {"監査項目": "19歳・大卒", "件数": int(((players.age == 19) & (players.entry_route == "大卒")).sum())},
        {"監査項目": "20歳・プロ10年目", "件数": int(((players.age == 20) & (players.pro_years == 10)).sum())},
        {"監査項目": "22歳・プロ15年目", "件数": int(((players.age == 22) & (players.pro_years == 15)).sum())},
    ])
    print_table("不可能な組み合わせ監査", invalid)

    foreign = pd.DataFrame([
        app.generate_career_history(category="助っ人外国人用", age=28, seed=seed, role="野手")
        for seed in range(50_000, 60_000)
    ])
    foreign_dist = foreign["pro_years"].value_counts().sort_index().rename_axis("NPB在籍年数").reset_index(name="人数")
    foreign_dist["構成比%"] = (foreign_dist["人数"] / len(foreign) * 100).round(2)
    print_table("助っ人外国人 NPB在籍年数（28歳・10,000件）", foreign_dist)


if __name__ == "__main__":
    main()
