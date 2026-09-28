"""Phase 2外国人生成のsurvivor selectionと能力分布を検証する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


ROLES = ("投手", "野手")
TENURE_BANDS = ("1年目", "2-3年目", "4年以上")
REAL_ROUTE_N = {
    "north_america_pro": 171, "cuba_domestic": 14, "latin_development": 9,
    "korea_pro": 6, "other_foreign_pro": 4, "north_america_amateur_direct": 3,
    "taiwan_amateur_direct": 3, "taiwan_pro": 2,
}
REAL_TENURE = {
    "投手": {
        "1年目": (58, {"球速": 155.50, "コントロール": 47.90, "スタミナ": 54.00}),
        "2-3年目": (45, {"球速": 156.00, "コントロール": 51.40, "スタミナ": 54.64}),
        "4年以上": (24, {"球速": 156.58, "コントロール": 54.75, "スタミナ": 53.50}),
    },
    "野手": {
        "1年目": (39, {"弾道": 2.90, "ミート": 43.74, "パワー": 69.74, "走力": 58.62, "肩力": 65.46, "守備力": 46.00, "捕球": 45.21, "6能力合計": 328.77}),
        "2-3年目": (23, {"弾道": 2.96, "ミート": 44.43, "パワー": 68.52, "走力": 55.26, "肩力": 69.22, "守備力": 47.13, "捕球": 45.91, "6能力合計": 330.48}),
        "4年以上": (23, {"弾道": 3.17, "ミート": 50.57, "パワー": 73.13, "走力": 48.83, "肩力": 69.52, "守備力": 46.35, "捕球": 48.09, "6能力合計": 336.48}),
    },
}
ROUTE_TARGETS = {
    "投手": {"north_america_pro": 79.5, "cuba_domestic": 5.5, "latin_development": 4.7, "korea_pro": 3.9, "north_america_amateur_direct": 2.4, "taiwan_amateur_direct": 2.4, "other_foreign_pro": 0.8, "taiwan_pro": 0.8},
    "野手": {"north_america_pro": 82.4, "cuba_domestic": 8.2, "latin_development": 3.5, "other_foreign_pro": 3.5, "korea_pro": 1.2, "taiwan_pro": 1.2, "taiwan_amateur_direct": 0.0, "north_america_amateur_direct": 0.0},
}
TENURE_TARGETS = {
    "投手": {"1年目": 45.7, "2-3年目": 35.4, "4年以上": 18.9},
    "野手": {"1年目": 45.9, "2-3年目": 27.1, "4年以上": 27.1},
}
AGE_MEAN_TARGETS = {"投手": 29.83, "野手": 30.58}
CORRELATION_TARGETS = {"投手": -0.03, "野手": 0.53}
REGRESSION_KEYS = [
    "seed", "role", "category", "name", "age", "entry_route", "pro_entry_age", "pro_years",
    "nationality", "birthplace", "position", "player_type", "player_class", "growth_type",
    "archetype", "position_style", "development_stage", "acquisition_role", "weakness_profile",
    "batting_throwing", "height", "weight", "abilities", "special_abilities", "breaking_balls", "sub_positions",
]
SEED_REGRESSION = {
    ("投手", "架空球団用", 246810): "a9f9505a3275e865f563aa57486ea4942cbd088898df5e790cef26e062cc4314",
    ("野手", "架空球団用", 246811): "08d1f2e3a3545b978f97f69d68172265383dceb69ebafda795f6a56d862a4755",
    ("投手", "ドラフト候補用", 135790): "7dd5514601bf9e0ee234b0780ddf2c7f6a684bc210679cb2a576564ffda23b3c",
    ("野手", "ドラフト候補用", 135791): "b460c00dafd74eba063c9c4a2244407f393d4a44b87c5d6404647e0facc8c2dc",
}


def tenure_band(years: int) -> str:
    return "1年目" if years == 1 else "2-3年目" if years <= 3 else "4年以上"


def numeric(abilities: dict, key: str) -> float:
    value = app.ability_numeric_value(abilities, key)
    return float(value or 0)


def player_row(player: dict) -> dict:
    abilities = player["abilities"]
    row = {
        "role": player["role"], "age": player["age"], "npb_years": player["npb_years"],
        "在籍年数帯": tenure_band(player["npb_years"]), "foreign_route": player["foreign_route"],
        "player_class": player["player_class"], "weakness_profile": player["weakness_profile"],
        "archetype": player["archetype"], "acquisition_role": player["acquisition_role"],
    }
    if player["role"] == "投手":
        row.update({"球速": float(app.pitcher_speed_value(abilities) or 0), "コントロール": numeric(abilities, "コントロール"), "スタミナ": numeric(abilities, "スタミナ")})
    else:
        row.update({"弾道": numeric(abilities, "弾道"), **{key: numeric(abilities, key) for key in app.FIELDER_ABILITY_KEYS}})
        row["6能力合計"] = sum(row[key] for key in app.FIELDER_ABILITY_KEYS)
    return row


def generate_sample(count: int, base_seed: int) -> pd.DataFrame:
    master = app.load_master_data()
    rows = []
    for role_index, role in enumerate(ROLES):
        for offset in range(count):
            player = app.generate_player(role, "助っ人外国人用", master, seed=base_seed + role_index * 10_000_000 + offset)
            rows.append(player_row(player))
    return pd.DataFrame(rows)


def tenure_ability_rows(frame: pd.DataFrame) -> list[dict]:
    rows = []
    for role in ROLES:
        metrics = list(next(iter(REAL_TENURE[role].values()))[1])
        role_frame = frame[frame["role"].eq(role)]
        real_total = sum(n for n, _ in REAL_TENURE[role].values())
        for band in ("全体", *TENURE_BANDS):
            part = role_frame if band == "全体" else role_frame[role_frame["在籍年数帯"].eq(band)]
            for metric in metrics:
                if band == "全体":
                    actual = sum(n * values[metric] for n, values in REAL_TENURE[role].values()) / real_total
                    actual_n = real_total
                else:
                    actual_n, values = REAL_TENURE[role][band]
                    actual = values[metric]
                generated = float(part[metric].mean())
                rows.append({"守備": role, "在籍年数帯": band, "指標": metric, "実在n": actual_n, "生成n": len(part), "実在平均": round(actual, 2), "生成平均": round(generated, 2), "差": round(generated - actual, 2)})
    return rows


def distribution(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    grouped = frame.groupby(["role", "在籍年数帯", column], observed=False).size().reset_index(name="人数")
    grouped["割合_pct"] = grouped.groupby(["role", "在籍年数帯"])["人数"].transform(lambda values: (100 * values / values.sum()).round(2))
    return grouped.rename(columns={"role": "守備", column: "区分"})


def route_ability(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (role, route), part in frame.groupby(["role", "foreign_route"]):
        metrics = ("球速", "コントロール", "スタミナ") if role == "投手" else ("弾道", *app.FIELDER_ABILITY_KEYS, "6能力合計")
        for metric in metrics:
            rows.append({"守備": role, "foreign_route": route, "指標": metric, "生成n": len(part), "生成平均": round(float(part[metric].mean()), 2), "実在route n": REAL_ROUTE_N.get(route, 0), "少標本警告": "n<10: 強い最適化禁止" if REAL_ROUTE_N.get(route, 0) < 10 else ""})
    return pd.DataFrame(rows)


def seed_regression_rows() -> list[dict]:
    master = app.load_master_data()
    rows = []
    for (role, category, seed), expected in SEED_REGRESSION.items():
        player = app.generate_player(role, category, master, seed=seed)
        payload = json.dumps({key: player.get(key) for key in REGRESSION_KEYS}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        rows.append({"守備": role, "カテゴリ": category, "seed": seed, "expected_sha256": expected, "actual_sha256": actual, "result": "PASS" if actual == expected else "FAIL"})
    return rows


def markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def phase1_stability(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role in ROLES:
        part = frame[frame["role"].eq(role)]
        route_rates = part["foreign_route"].value_counts(normalize=True).mul(100)
        tenure_rates = part["在籍年数帯"].value_counts(normalize=True).mul(100)
        rows.append({
            "守備": role, "平均年齢target": AGE_MEAN_TARGETS[role], "平均年齢generated": round(float(part["age"].mean()), 2),
            "route最大差pp": round(max(abs(float(route_rates.get(label, 0)) - target) for label, target in ROUTE_TARGETS[role].items()), 2),
            "tenure最大差pp": round(max(abs(float(tenure_rates.get(label, 0)) - target) for label, target in TENURE_TARGETS[role].items()), 2),
            "age×tenure target": CORRELATION_TARGETS[role], "age×tenure generated": round(float(part[["age", "npb_years"]].corr().iloc[0, 1]), 3),
        })
    return pd.DataFrame(rows)


def write_reports(frame: pd.DataFrame, output_dir: Path, test_result: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tenure = pd.DataFrame(tenure_ability_rows(frame))
    class_dist = distribution(frame, "player_class")
    weakness_dist = distribution(frame, "weakness_profile")
    archetype_dist = distribution(frame, "archetype")
    acquisition_dist = distribution(frame, "acquisition_role")
    route = route_ability(frame)
    seed = pd.DataFrame(seed_regression_rows())
    stability = phase1_stability(frame)
    files = {
        "tenure_ability_compare.csv": tenure, "player_class_by_tenure.csv": class_dist,
        "weakness_by_tenure.csv": weakness_dist, "archetype_by_tenure.csv": archetype_dist,
        "acquisition_role_by_tenure.csv": acquisition_dist, "route_ability_compare.csv": route,
        "seed_regression.csv": seed,
    }
    for name, data in files.items():
        data.to_csv(output_dir / name, index=False, encoding="utf-8-sig", lineterminator="\n")

    focus = tenure[(tenure["在籍年数帯"].isin(TENURE_BANDS)) & (((tenure["守備"] == "投手") & (tenure["指標"] == "コントロール")) | ((tenure["守備"] == "野手") & (tenure["指標"].isin(["ミート", "パワー", "走力", "6能力合計"]))))]
    summary = f"""# 外国人生成基盤 Phase 2

## 実装

- Phase 1のroute・年齢・NPB在籍年数生成は変更せず、tenureを選手格・弱点・アーキタイプ・獲得目的のsoft multiplierへ接続。
- routeは保存上の8分類を維持しつつ、能力構造では共有priorへまとめ、小標本routeを強く最適化していない。
- tenure / routeによる直接能力補正は未実装。特殊能力・球種・体格も変更していない。

## 検証

- 最終シミュレーション: 投手 {int((frame['role'] == '投手').sum()):,}人 / 野手 {int((frame['role'] == '野手').sum()):,}人
- pytest: {test_result}
- seed regression: {int(seed['result'].eq('PASS').sum())}/{len(seed)} PASS

### tenure別主要能力

{markdown_table(focus)}

### Phase 1分布の維持確認

{markdown_table(stability)}

route別能力は `route_ability_compare.csv` に記録した。実在n<10には警告を付け、独立した能力モデルや直接補正には使用していない。

## Phase 3へ残す項目

- 特殊能力、球種・変化量、体格、再来日率、架空球団ロスター全体構成の精密調整。
- 少標本routeは追加データが得られるまで強い補正を行わない。
"""
    (output_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players-per-role", type=int, default=5_000)
    parser.add_argument("--base-seed", type=int, default=9_280_000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "foreign_generation_phase2")
    parser.add_argument("--test-result", default="pytestは別途実行")
    args = parser.parse_args()
    frame = generate_sample(args.players_per_role, args.base_seed)
    write_reports(frame, args.output_dir, args.test_result)
    print(f"{len(frame):,}人分の検証結果を {args.output_dir} に出力しました。")


if __name__ == "__main__":
    main()
