"""外国人生成 Phase 3D の静的球団ロスターと1年遷移を監査する。"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from scripts import validate_foreign_generation_phase3c as phase3c


ROLES = ("投手", "野手")
POSITIONS = ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")
FOREIGN_SHEET = "combined_2022_2025_complete"
TEAM_SHEET = "players"
IDENTITY_COLUMNS = ["name", "role", "nationality", "birth_year"]


def describe_counts(frame: pd.DataFrame, columns: list[tuple[str, str]], dataset: str) -> pd.DataFrame:
    rows = []
    for column, label in columns:
        values = pd.to_numeric(frame[column], errors="raise")
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
    return pd.DataFrame(rows)


def load_team_roster_target(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    players = pd.read_excel(path, sheet_name=TEAM_SHEET, usecols=["team", "name", "role", "main_position"])
    required = {"team", "name", "role", "main_position"}
    if not required.issubset(players.columns) or players[list(required)].isna().any().any():
        raise ValueError("球団ロスターのteam/name/role/main_positionが完全ではありません。")
    team = players.groupby("team").agg(
        total_players=("name", "size"),
        pitchers=("role", lambda values: int(values.eq("投手").sum())),
        fielders=("role", lambda values: int(values.eq("野手").sum())),
    ).reset_index()
    positions = (
        players[players["role"].eq("野手")]
        .groupby(["team", "main_position"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=POSITIONS, fill_value=0)
        .reset_index()
    )
    return team, positions


def load_foreign_transition_target(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "season", "team", "name", "role", "nationality", "birth_year", "npb_years",
        "npb_first_entry_year", "include_foreign_analysis",
    ]
    frame = pd.read_excel(path, sheet_name=FOREIGN_SHEET, usecols=columns)
    frame = frame[frame["include_foreign_analysis"].fillna(False).astype(bool)].copy()
    previous = frame[frame["season"].eq(2024)].copy()
    current = frame[frame["season"].eq(2025)].copy()
    if len(previous) != 73 or len(current) != 71:
        raise ValueError(f"2024/2025対象人数が想定外です: {len(previous)}/{len(current)}")
    if previous[IDENTITY_COLUMNS].isna().any().any() or current[IDENTITY_COLUMNS].isna().any().any():
        raise ValueError("年度間identity候補に欠損があります。")
    if previous.duplicated(IDENTITY_COLUMNS).any() or current.duplicated(IDENTITY_COLUMNS).any():
        raise ValueError("年度内で複合identityが重複しています。")

    current_lookup = {
        tuple(row[column] for column in IDENTITY_COLUMNS): row
        for _, row in current.iterrows()
    }
    statuses = []
    next_teams = []
    for _, row in previous.iterrows():
        identity = tuple(row[column] for column in IDENTITY_COLUMNS)
        next_row = current_lookup.get(identity)
        if next_row is None:
            statuses.append("npb_exit")
            next_teams.append("")
        elif row["team"] == next_row["team"]:
            statuses.append("same_team")
            next_teams.append(next_row["team"])
        else:
            statuses.append("other_npb_team")
            next_teams.append(next_row["team"])
        if next_row is not None and row["npb_first_entry_year"] != next_row["npb_first_entry_year"]:
            raise ValueError(f"年度間で初来日年が不一致です: {row['name']}")
    previous["transition"] = statuses
    previous["team_2025"] = next_teams
    previous["tenure_band"] = pd.cut(
        pd.to_numeric(previous["npb_years"], errors="raise"),
        bins=[0, 1, 3, float("inf")],
        labels=["1年目", "2-3年目", "4年以上"],
    ).astype(str)

    previous_keys = set(map(tuple, previous[IDENTITY_COLUMNS].to_numpy()))
    current["transition"] = [
        "continued_from_2024" if tuple(row[column] for column in IDENTITY_COLUMNS) in previous_keys else "new_to_npb_dataset"
        for _, row in current.iterrows()
    ]
    return previous, current


def transition_group_summary(frame: pd.DataFrame, group: str, dataset: str) -> pd.DataFrame:
    rows = []
    for label, part in frame.groupby(group, observed=False):
        retained = int(part["retained"].sum()) if "retained" in part else int(part["transition"].eq("same_team").sum())
        rows.append({
            "dataset": dataset,
            "group": str(label),
            "n": len(part),
            "retained": retained,
            "retention_rate_pct": round(100 * retained / len(part), 2) if len(part) else 0,
        })
    return pd.DataFrame(rows)


def generate_validation_sample(count: int, full_roster_count: int) -> dict[str, pd.DataFrame]:
    if not 0 < full_roster_count <= count:
        raise ValueError("full_roster_countは1以上team_count以下にしてください。")
    master = app.load_master_data()
    roster_rows = []
    position_rows = []
    transition_rows = []
    transition_player_rows = []

    for offset in range(count):
        roster_seed = 202610100000 + offset
        transition_seed = 202610200000 + offset
        team_plan = app.choose_team_roster_composition(roster_seed)
        foreign_plan = app.choose_foreign_team_composition(roster_seed)
        roster_rows.append({
            "team": f"generated_{offset + 1}",
            "total_players": sum(team_plan.values()),
            "pitchers": team_plan["投手"],
            "fielders": team_plan["野手"],
            "foreign_players": sum(foreign_plan.values()),
            "foreign_pitchers": foreign_plan["投手"],
            "foreign_fielders": foreign_plan["野手"],
            "full_roster_verified": int(offset < full_roster_count),
        })
        if offset < full_roster_count:
            roster = app.generate_team_roster(roster_seed, master)
            if Counter(player["role"] for player in roster) != Counter(team_plan):
                raise AssertionError("完全ロスターのrole構成がplanと一致しません。")
            if app.foreign_import_role_counts(roster) != foreign_plan:
                raise AssertionError("完全ロスターの外国人構成がplanと一致しません。")
            if len({player["name"] for player in roster}) != len(roster):
                raise AssertionError("完全ロスター内で名前が重複しました。")
            position_counts = Counter(
                player["position"] for player in roster if player["role"] == "野手"
            )
            position_rows.append({
                "team": f"generated_{offset + 1}",
                **{position: position_counts[position] for position in POSITIONS},
            })
            previous_foreign = [player for player in roster if player["roster_origin"] == "foreign_import"]
            domestic_names = {player["name"] for player in roster if player["roster_origin"] == "domestic"}
        else:
            previous_foreign = app.generate_foreign_import_roster(roster_seed, master)
            domestic_names = set()
        advanced = app.advance_foreign_import_roster_year(
            previous_foreign,
            transition_seed,
            master,
            used_names=domestic_names,
        )
        retained = [player for player in advanced if player["transition_status"] == "retained"]
        newcomers = [player for player in advanced if player["transition_status"] == "new_joiner"]
        previous_by_seed = {player["seed"]: player for player in previous_foreign}
        for player in retained:
            old = previous_by_seed[player["seed"]]
            if player["age"] != old["age"] + 1 or player["npb_years"] != old["npb_years"] + 1:
                raise AssertionError("残留選手の年齢・NPB在籍年数が1増えていません。")
            for key in ("abilities", "special_abilities", "breaking_balls", "height", "weight"):
                if player[key] != old[key]:
                    raise AssertionError(f"残留選手の保護対象が変化しました: {key}")
        for old in previous_foreign:
            tenure_band = app.foreign_tenure_band(int(old["npb_years"]))
            transition_player_rows.append({
                "role": old["role"],
                "tenure_band": {"1": "1年目", "2-3": "2-3年目", "4+": "4年以上"}[tenure_band],
                "retained": int(old["seed"] in {player["seed"] for player in retained}),
            })
        next_counts = app.foreign_import_role_counts(advanced)
        transition_rows.append({
            "team": f"generated_{offset + 1}",
            "previous_foreign": len(previous_foreign),
            "retained": len(retained),
            "departed": len(previous_foreign) - len(retained),
            "new_joiners": len(newcomers),
            "next_foreign": len(advanced),
            "next_pitchers": next_counts["投手"],
            "next_fielders": next_counts["野手"],
            "next_age_mean": round(sum(player["age"] for player in advanced) / len(advanced), 3),
            "next_tenure_mean": round(sum(player["npb_years"] for player in advanced) / len(advanced), 3),
        })

    positions = pd.DataFrame(position_rows)
    position_audit = []
    for position in POSITIONS:
        values = positions[position]
        position_audit.append({
            "position": position,
            "n_teams": len(positions),
            "mean": round(float(values.mean()), 2),
            "median": round(float(values.median()), 2),
            "min": int(values.min()),
            "max": int(values.max()),
            "zero_teams": int(values.eq(0).sum()),
            "zero_rate_pct": round(100 * float(values.eq(0).mean()), 2),
        })
    return {
        "rosters": pd.DataFrame(roster_rows),
        "positions": pd.DataFrame(position_audit),
        "transitions": pd.DataFrame(transition_rows),
        "transition_players": pd.DataFrame(transition_player_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--foreign-data", type=Path, required=True)
    parser.add_argument("--roster-data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--team-count", type=int, default=1000)
    parser.add_argument("--full-roster-count", type=int, default=100)
    args = parser.parse_args()

    team_target, position_target = load_team_roster_target(args.roster_data)
    transition_2024, transition_2025 = load_foreign_transition_target(args.foreign_data)
    generated = generate_validation_sample(args.team_count, args.full_roster_count)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([
        {"領域": "球団全体ロスター", "target取得": "可", "根拠": f"team/role/main_position完備（{len(team_target)}球団）。支配下・育成区分はなし。"},
        {"領域": "2024→2025外国人identity", "target取得": "可", "根拠": "stable IDなし。氏名＋role＋国籍＋生年が各年度で一意、対応36人の初来日年一致。"},
    ]).to_csv(args.output_dir / "data_coverage.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    team_target.to_csv(args.output_dir / "team_roster_target.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    position_target.to_csv(args.output_dir / "position_roster_target.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    generated["rosters"].to_csv(args.output_dir / "team_roster_generated.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    generated["positions"].to_csv(args.output_dir / "position_roster_audit.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    transition_2024.to_csv(args.output_dir / "foreign_transition_target.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    generated["transitions"].to_csv(args.output_dir / "foreign_transition_generated.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.concat([
        transition_group_summary(transition_2024, "role", "実在2024→2025"),
        transition_group_summary(generated["transition_players"], "role", "生成"),
    ]).to_csv(args.output_dir / "foreign_transition_by_role.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.concat([
        transition_group_summary(transition_2024, "tenure_band", "実在2024→2025"),
        transition_group_summary(generated["transition_players"], "tenure_band", "生成"),
    ]).to_csv(args.output_dir / "foreign_transition_by_tenure.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    seed = pd.DataFrame(phase3c.seed_regression_rows())
    seed.to_csv(args.output_dir / "seed_regression.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    target_status = transition_2024["transition"].value_counts()
    if target_status.to_dict() != {"npb_exit": 37, "same_team": 32, "other_npb_team": 4}:
        raise AssertionError(f"遷移targetが想定外です: {target_status.to_dict()}")
    if int(transition_2025["transition"].eq("new_to_npb_dataset").sum()) != 35:
        raise AssertionError("2025新規dataset選手数が想定外です。")
    if not seed["result"].eq("PASS").all():
        raise AssertionError("seed regressionが失敗しました。")

    roster_stats = describe_counts(
        generated["rosters"],
        [("total_players", "総人数"), ("pitchers", "投手人数"), ("fielders", "野手人数")],
        "生成",
    )
    retention = 100 * generated["transitions"]["retained"].sum() / generated["transitions"]["previous_foreign"].sum()
    print(roster_stats.to_string(index=False))
    print(f"position zero: 捕手={int(generated['positions'].set_index('position').loc['捕手', 'zero_teams'])}, 遊撃手={int(generated['positions'].set_index('position').loc['遊撃手', 'zero_teams'])}")
    print(f"transition target: same_team=32, other_npb_team=4, npb_exit=37, new_to_npb_dataset=35")
    print(f"generated retention: {retention:.2f}% ({generated['transitions']['retained'].sum()}/{generated['transitions']['previous_foreign'].sum()})")
    print(f"seed regression: {len(seed)}/{len(seed)} PASS")


if __name__ == "__main__":
    main()
