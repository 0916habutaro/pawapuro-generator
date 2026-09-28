"""外国人生成 Phase 3C の体格・再来日・球団ロスターを軽量監査する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from scripts import validate_foreign_generation_phase2 as phase2


REAL_SHEET = "combined_2022_2025_complete"
ROSTER_SHEET = "2025_complete_coverage"
PHYSIQUE_SHEET = "players"
ROLES = ("投手", "野手")
POSITIONS = ("投手", "捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")
FOREIGN_SEED_REGRESSION = {
    ("投手", "助っ人外国人用", 2026092803): "e31f52610544e1582057a655ea1ac039a227987217f1c4223d8050092f6ef1c9",
    ("野手", "助っ人外国人用", 2026092804): "0e32b366d9e4cc8cf1b2d10ba04f195045e95a89a39e0267d4e2ccd7003893d4",
}


def physique_metrics(frame: pd.DataFrame, dataset: str, group: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for label, part in frame.groupby(group, observed=False):
        height = pd.to_numeric(part["height_cm"], errors="coerce")
        weight = pd.to_numeric(part["weight_kg"], errors="coerce")
        valid = pd.DataFrame({"height": height, "weight": weight}).dropna()
        bmi = valid["weight"] / (valid["height"] / 100) ** 2
        rows.append({
            "dataset": dataset,
            "group": str(label),
            "n": len(valid),
            "height_mean": round(float(valid["height"].mean()), 2),
            "height_sd": round(float(valid["height"].std()), 2),
            "height_p10": round(float(valid["height"].quantile(.10)), 2),
            "height_p50": round(float(valid["height"].quantile(.50)), 2),
            "height_p90": round(float(valid["height"].quantile(.90)), 2),
            "weight_mean": round(float(valid["weight"].mean()), 2),
            "weight_sd": round(float(valid["weight"].std()), 2),
            "weight_p10": round(float(valid["weight"].quantile(.10)), 2),
            "weight_p50": round(float(valid["weight"].quantile(.50)), 2),
            "weight_p90": round(float(valid["weight"].quantile(.90)), 2),
            "bmi_mean": round(float(bmi.mean()), 2),
            "height_weight_corr": round(float(valid["height"].corr(valid["weight"])), 2),
            "small_sample": "参考値" if len(valid) < 20 else "",
        })
    return rows


def load_physique_reference(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(
        path,
        sheet_name=PHYSIQUE_SHEET,
        usecols=["role", "main_position", "age", "height_cm", "weight_kg"],
    )
    frame = frame.dropna(subset=["height_cm", "weight_kg"]).copy()
    frame["position"] = frame["role"].where(frame["role"].eq("投手"), frame["main_position"])
    return frame


def generate_physique_sample(count: int) -> pd.DataFrame:
    master = app.load_master_data()
    rows = []
    for role_index, role in enumerate(ROLES):
        for offset in range(count):
            player = app.generate_player(
                role,
                "助っ人外国人用",
                master,
                seed=202609300000 + role_index * 10_000_000 + offset,
            )
            rows.append({
                "role": role,
                "position": "投手" if role == "投手" else player["position"],
                "height_cm": player["height_cm"],
                "weight_kg": player["weight_kg"],
            })
    return pd.DataFrame(rows)


def load_returnee_target(path: Path) -> pd.DataFrame:
    columns = [
        "role", "npb_years", "npb_first_entry_year", "npb_stint_start_year",
        "include_foreign_analysis",
    ]
    frame = pd.read_excel(path, sheet_name=REAL_SHEET, usecols=columns)
    frame = frame[frame["include_foreign_analysis"].fillna(False).astype(bool)].copy()
    frame["is_returnee"] = (
        pd.to_numeric(frame["npb_first_entry_year"], errors="coerce")
        < pd.to_numeric(frame["npb_stint_start_year"], errors="coerce")
    )
    return frame


def generate_returnee_sample(count: int) -> pd.DataFrame:
    rows = []
    for role_index, role in enumerate(ROLES):
        for offset in range(count):
            context = app.generate_foreign_context(202609280000 + role_index * 10_000_000 + offset, role)
            rows.append({"role": role, **context})
    return pd.DataFrame(rows)


def returnee_summary(frame: pd.DataFrame, dataset: str) -> list[dict[str, object]]:
    rows = []
    for scope, part in (("全体", frame), *((role, frame[frame["role"].eq(role)]) for role in ROLES)):
        count = int(part["is_returnee"].sum())
        rows.append({
            "dataset": dataset,
            "scope": scope,
            "returnees": count,
            "n": len(part),
            "rate_pct": round(100 * count / len(part), 2),
        })
    return rows


def fictional_origin_summary(count: int) -> list[dict[str, object]]:
    rows = []
    for role_index, role in enumerate(ROLES):
        counts = {"domestic": 0, "foreign_import": 0}
        for offset in range(count):
            seed = 202610010000 + role_index * 10_000_000 + offset
            rng = random.Random(seed)
            age = app.age_for(rng, "架空球団用")
            app.choose_player_class(rng, "架空球団用", age)
            nationality = app.choose_nationality(rng, "架空球団用")
            counts[app.determine_roster_origin("架空球団用", nationality, seed)] += 1
        for origin, value in counts.items():
            rows.append({
                "守備": role,
                "roster_origin": origin,
                "件数": value,
                "割合_pct": round(100 * value / count, 2),
                "注記": "個別generator確率（1球団人数ではない）",
            })
    return rows


def load_roster_target(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(
        path,
        sheet_name=ROSTER_SHEET,
        usecols=["team", "foreign_players", "pitchers", "fielders", "status"],
    )
    for column in ("foreign_players", "pitchers", "fielders"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    return frame


def generate_roster_plans(count: int) -> pd.DataFrame:
    rows = []
    for offset in range(count):
        composition = app.choose_foreign_team_composition(202609290000 + offset)
        rows.append({
            "team": f"generated_{offset + 1}",
            "foreign_players": composition["投手"] + composition["野手"],
            "pitchers": composition["投手"],
            "fielders": composition["野手"],
        })
    return pd.DataFrame(rows)


def roster_count_summary(frame: pd.DataFrame, dataset: str) -> list[dict[str, object]]:
    rows = []
    for column, label in (("foreign_players", "外国人補強数"), ("pitchers", "外国人投手数"), ("fielders", "外国人野手数")):
        values = frame[column]
        rows.append({
            "dataset": dataset,
            "metric": label,
            "n_teams": len(frame),
            "mean": round(float(values.mean()), 2),
            "median": round(float(values.median()), 2),
            "p25": round(float(values.quantile(.25)), 2),
            "p75": round(float(values.quantile(.75)), 2),
            "min": int(values.min()),
            "max": int(values.max()),
        })
    return rows


def role_mix_summary(frame: pd.DataFrame, dataset: str) -> dict[str, object]:
    pitchers = int(frame["pitchers"].sum())
    fielders = int(frame["fielders"].sum())
    return {
        "dataset": dataset,
        "pitchers": pitchers,
        "fielders": fielders,
        "pitcher_share_pct": round(100 * pitchers / (pitchers + fielders), 2),
        "pitcher_fielder_ratio": round(pitchers / fielders, 3),
    }


def seed_regression_rows() -> list[dict[str, object]]:
    expected_rows = {**phase2.SEED_REGRESSION, **FOREIGN_SEED_REGRESSION}
    master = app.load_master_data()
    rows = []
    for (role, category, seed), expected in expected_rows.items():
        player = app.generate_player(role, category, master, seed=seed)
        payload = json.dumps(
            {key: player.get(key) for key in phase2.REGRESSION_KEYS},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        rows.append({
            "守備": role,
            "カテゴリ": category,
            "seed": seed,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "result": "PASS" if actual == expected else "FAIL",
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-data", type=Path, required=True)
    parser.add_argument("--physique-data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--physique-count", type=int, default=500)
    parser.add_argument("--profile-count", type=int, default=2000)
    parser.add_argument("--roster-count", type=int, default=1000)
    args = parser.parse_args()

    real_header = pd.read_excel(args.real_data, sheet_name=REAL_SHEET, nrows=0)
    foreign_physique_available = {"height", "weight"}.issubset(real_header.columns) or {"height_cm", "weight_kg"}.issubset(real_header.columns)
    physique_reference = load_physique_reference(args.physique_data)
    generated_physique = generate_physique_sample(args.physique_count)
    real_returnee = load_returnee_target(args.real_data)
    generated_returnee = generate_returnee_sample(args.profile_count)
    real_roster = load_roster_target(args.real_data)
    generated_roster = generate_roster_plans(args.roster_count)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"領域": "体格", "target取得": "不可", "根拠": "212 player-seasonに身長・体重列なし。2026 NPB全体を参考値として使用。"},
        {"領域": "再来日", "target取得": "可", "根拠": f"first/stint列あり（n={len(real_returnee)}）。"},
        {"領域": "球団ロスター人数", "target取得": "可", "根拠": f"2025決定版12球団スナップショット（n={len(real_roster)}）。"},
    ]).to_csv(args.output_dir / "data_coverage.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame(
        physique_metrics(physique_reference, "NPB全体参考", "role")
        + physique_metrics(generated_physique, "生成baseline", "role")
    ).to_csv(args.output_dir / "physique_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame(
        physique_metrics(physique_reference, "NPB全体参考", "position")
        + physique_metrics(generated_physique, "生成baseline", "position")
    ).to_csv(args.output_dir / "physique_position_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame(
        returnee_summary(real_returnee, "実在")
        + returnee_summary(generated_returnee, "生成")
    ).to_csv(args.output_dir / "returnee_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame(fictional_origin_summary(args.profile_count)).to_csv(
        args.output_dir / "roster_origin_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )
    pd.DataFrame(
        roster_count_summary(real_roster, "実在2025決定版")
        + roster_count_summary(generated_roster, "生成ロスター層")
    ).to_csv(args.output_dir / "foreign_roster_count_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame([
        role_mix_summary(real_roster, "実在2025決定版"),
        role_mix_summary(generated_roster, "生成ロスター層"),
    ]).to_csv(args.output_dir / "foreign_role_mix_compare.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    seed = pd.DataFrame(seed_regression_rows())
    seed.to_csv(args.output_dir / "seed_regression.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    if foreign_physique_available:
        raise AssertionError("外国人体格列を検出したため、coverage記述を更新してください。")
    if len(real_returnee) != 212:
        raise AssertionError(f"実在対象人数が想定外です: {len(real_returnee)}")
    if len(real_roster) != 12 or not real_roster["status"].astype(str).str.contains("決定版").all():
        raise AssertionError("2025決定版12球団スナップショットを確認できません。")
    if not seed["result"].eq("PASS").all():
        raise AssertionError("seed regressionが失敗しました。")

    print(f"physique: NPB参考 {len(physique_reference)} / 生成 {len(generated_physique)}")
    print(f"returnee: 実在 {len(real_returnee)} / 生成 {len(generated_returnee)}")
    print(f"roster: 実在 {len(real_roster)}球団 / 生成 {len(generated_roster)}球団")
    print(f"seed regression: {len(seed)}/{len(seed)} PASS")


if __name__ == "__main__":
    main()
