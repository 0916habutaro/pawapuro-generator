"""Phase 1外国人contextの分布とseed回帰を最小構成で検証する。"""

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
AGE_BANDS = ("19-24", "25-27", "28-30", "31-33", "34+")
TENURE_BANDS = ("1年目", "2-3年目", "4年以上")
ROUTE_TARGETS = {
    "投手": {
        "north_america_pro": 79.5, "cuba_domestic": 5.5, "latin_development": 4.7,
        "korea_pro": 3.9, "north_america_amateur_direct": 2.4,
        "taiwan_amateur_direct": 2.4, "other_foreign_pro": 0.8, "taiwan_pro": 0.8,
    },
    "野手": {
        "north_america_pro": 82.4, "cuba_domestic": 8.2, "latin_development": 3.5,
        "other_foreign_pro": 3.5, "korea_pro": 1.2, "taiwan_pro": 1.2,
        "taiwan_amateur_direct": 0.0, "north_america_amateur_direct": 0.0,
    },
}
AGE_TARGETS = {
    "投手": dict(zip(AGE_BANDS, (1.6, 14.2, 46.5, 29.9, 7.9), strict=True)),
    "野手": dict(zip(AGE_BANDS, (4.7, 12.9, 31.8, 31.8, 18.8), strict=True)),
}
AGE_MEAN_TARGETS = {"投手": 29.83, "野手": 30.58}
TENURE_TARGETS = {
    "投手": dict(zip(TENURE_BANDS, (45.7, 35.4, 18.9), strict=True)),
    "野手": dict(zip(TENURE_BANDS, (45.9, 27.1, 27.1), strict=True)),
}
CORRELATION_TARGETS = {"投手": -0.03, "野手": 0.53}
REGRESSION_KEYS = [
    "seed", "role", "category", "name", "age", "entry_route", "pro_entry_age", "pro_years",
    "nationality", "birthplace", "position", "player_type", "player_class", "growth_type",
    "archetype", "position_style", "development_stage", "acquisition_role", "weakness_profile",
    "batting_throwing", "height", "weight", "abilities", "special_abilities", "breaking_balls",
    "sub_positions",
]
SEED_REGRESSION = {
    ("投手", "架空球団用", 246810): "a9f9505a3275e865f563aa57486ea4942cbd088898df5e790cef26e062cc4314",
    ("野手", "架空球団用", 246811): "08d1f2e3a3545b978f97f69d68172265383dceb69ebafda795f6a56d862a4755",
    ("投手", "ドラフト候補用", 135790): "7dd5514601bf9e0ee234b0780ddf2c7f6a684bc210679cb2a576564ffda23b3c",
    ("野手", "ドラフト候補用", 135791): "b460c00dafd74eba063c9c4a2244407f393d4a44b87c5d6404647e0facc8c2dc",
}


def age_band(age: int) -> str:
    if age <= 24:
        return "19-24"
    if age <= 27:
        return "25-27"
    if age <= 30:
        return "28-30"
    if age <= 33:
        return "31-33"
    return "34+"


def tenure_band(years: int) -> str:
    if years == 1:
        return "1年目"
    if years <= 3:
        return "2-3年目"
    return "4年以上"


def generate_context_sample(count: int, base_seed: int) -> pd.DataFrame:
    rows = []
    for role_index, role in enumerate(ROLES):
        for offset in range(count):
            context = app.generate_foreign_context(base_seed + role_index * 10_000_000 + offset, role)
            rows.append({"role": role, **context})
    frame = pd.DataFrame(rows)
    frame["年齢帯"] = frame["age"].map(age_band)
    frame["在籍年数帯"] = frame["npb_years"].map(tenure_band)
    return frame


def comparison_rows(frame: pd.DataFrame, column: str, labels: tuple[str, ...] | set[str], targets: dict[str, dict[str, float]]) -> list[dict[str, object]]:
    rows = []
    ordered_labels = list(labels)
    for role in ROLES:
        values = frame.loc[frame["role"].eq(role), column]
        rates = values.value_counts(normalize=True).mul(100)
        for label in ordered_labels:
            generated = float(rates.get(label, 0.0))
            target = float(targets[role].get(label, 0.0))
            rows.append({"守備": role, "区分": label, "target_pct": target, "generated_pct": round(generated, 2), "diff_pp": round(generated - target, 2)})
    return rows


def seed_regression_rows() -> list[dict[str, object]]:
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
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None)]
    return "\n".join([header, separator, *body])


def write_reports(frame: pd.DataFrame, output_dir: Path, test_result: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    route = pd.DataFrame(comparison_rows(frame, "foreign_route", tuple(sorted(app.FOREIGN_ROUTES)), ROUTE_TARGETS))
    age = pd.DataFrame(comparison_rows(frame, "年齢帯", AGE_BANDS, AGE_TARGETS))
    tenure = pd.DataFrame(comparison_rows(frame, "在籍年数帯", TENURE_BANDS, TENURE_TARGETS))
    joint = frame.groupby(["role", "年齢帯", "在籍年数帯"], observed=False).size().reset_index(name="count")
    totals = frame.groupby("role").size()
    joint["pct"] = joint.apply(lambda row: round(100 * row["count"] / totals[row["role"]], 2), axis=1)
    seed_regression = pd.DataFrame(seed_regression_rows())

    route.to_csv(output_dir / "route_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    age.to_csv(output_dir / "age_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    tenure.to_csv(output_dir / "tenure_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    joint.to_csv(output_dir / "age_tenure_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    seed_regression.to_csv(output_dir / "seed_regression.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    metrics = []
    route_joint_lines = []
    for role in ROLES:
        part = frame[frame["role"].eq(role)]
        correlation = float(part[["age", "npb_years"]].corr().iloc[0, 1])
        metrics.append({"守備": role, "人数": len(part), "平均年齢target": AGE_MEAN_TARGETS[role], "平均年齢generated": round(part["age"].mean(), 2), "age×tenure target": CORRELATION_TARGETS[role], "age×tenure generated": round(correlation, 3)})
        route_means = part.groupby("foreign_route").agg(人数=("age", "size"), 平均年齢=("age", "mean"), 平均NPB在籍=("npb_years", "mean")).round(2)
        route_joint_lines.append(f"### {role}: route×age / route×tenure\n\n{markdown_table(route_means.reset_index())}")

    summary = f"""# 外国人生成基盤 Phase 1

## 実装内容

- `roster_origin` で国内経由と外国人補強を分離し、架空球団用と助っ人外国人用の `foreign_import` を共通contextに統合。
- route条件付き国籍、守備別年齢、守備別NPB在籍年数、再来日フラグを追加。
- SQLite migration、履歴読み込み、CSV/Excel対象列、プロフィール表示を追加。routeによる能力補正は未実装。

## テスト結果

- {test_result}
- seed regression: {int(seed_regression["result"].eq("PASS").sum())}/{len(seed_regression)} PASS

## 実在targetとの主要比較

{markdown_table(pd.DataFrame(metrics))}

### route

{markdown_table(route)}

### age

{markdown_table(age)}

### tenure

{markdown_table(tenure)}

{chr(10).join(route_joint_lines)}

## 残課題 / Phase 2

- route別の直接能力補正、特殊能力、球種、体格の再調整はPhase 2以降。
- 少標本routeと再来日率は低確率eventとして残し、精密調整は行っていない。
- route×age / route×tenureに実在のセルtargetがないため、Phase 1ではソフトな条件付けと生成値の記録に留めた。
"""
    (output_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players-per-role", type=int, default=5_000)
    parser.add_argument("--base-seed", type=int, default=9_280_000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "foreign_generation_phase1")
    parser.add_argument("--test-result", default="pytestは別途実行")
    args = parser.parse_args()
    frame = generate_context_sample(args.players_per_role, args.base_seed)
    write_reports(frame, args.output_dir, args.test_result)
    print(f"{len(frame):,}人分の検証結果を {args.output_dir} に出力しました。")


if __name__ == "__main__":
    main()
