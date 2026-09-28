import copy
from collections import Counter

import app
import pandas as pd
from scripts import validate_foreign_generation_phase3d as validator


OBSERVED_TEAM_COMPOSITIONS = {
    tuple(composition)
    for composition, _weight in app.TEAM_ROSTER_COMPOSITION_WEIGHTS
}


def role_counts(players):
    return Counter(player["role"] for player in players)


def test_team_composition_is_deterministic_and_data_bounded():
    for seed in range(500):
        first = app.choose_team_roster_composition(seed)
        second = app.choose_team_roster_composition(seed)
        assert first == second
        assert (first["投手"], first["野手"]) in OBSERVED_TEAM_COMPOSITIONS


def test_team_roster_is_deterministic_and_follows_both_plans():
    seed = 202609290101
    master = app.load_master_data()
    first = app.generate_team_roster(seed, master)
    second = app.generate_team_roster(seed, master)

    assert first == second
    assert role_counts(first) == app.choose_team_roster_composition(seed)
    assert app.foreign_import_role_counts(first) == app.choose_foreign_team_composition(seed)
    assert [player["roster_index"] for player in first] == list(range(1, len(first) + 1))
    assert all(player["team_seed"] == seed for player in first)
    assert all(player["roster_group"] == player["roster_origin"] for player in first)


def test_team_roster_domestic_slots_and_names_are_valid():
    # このseedは上位層の重複再試行がない場合、国内選手名が衝突する。
    players = app.generate_team_roster(202610100027, app.load_master_data())
    domestic = [player for player in players if player["roster_group"] == "domestic"]
    names = [str(player["name"]) for player in players]

    assert domestic
    assert all(player["roster_origin"] == "domestic" for player in domestic)
    assert len(names) == len(set(names))
    position_counts = Counter(player["position"] for player in players if player["role"] == "野手")
    for position, minimum in app.TEAM_ROSTER_POSITION_MINIMUMS.items():
        assert position_counts[position] >= minimum


def test_foreign_national_domestic_stays_in_domestic_group(monkeypatch):
    serial = 0
    fielder_serial = 0

    def fake_generate_player(role, category, master, seed=None, used_names=None, **_kwargs):
        nonlocal serial, fielder_serial
        serial += 1
        if role == "野手":
            fielder_serial += 1
        origin = "foreign_import" if category == "助っ人外国人用" else "domestic"
        if fielder_serial <= 6:
            position = "捕手"
        elif fielder_serial == 7:
            position = "一塁手"
        elif fielder_serial == 8:
            position = "二塁手"
        elif fielder_serial <= 11:
            position = "遊撃手"
        else:
            position = "外野手"
        return {
            "seed": seed,
            "name": f"選手{serial}",
            "role": role,
            "category": category,
            "nationality": "アメリカ",
            "roster_origin": origin,
            "position": position,
        }

    monkeypatch.setattr(app, "generate_player", fake_generate_player)
    players = app.generate_team_roster(101, master=object())
    domestic = [player for player in players if player["roster_group"] == "domestic"]

    assert domestic
    assert all(player["nationality"] == "アメリカ" for player in domestic)
    assert app.foreign_import_role_counts(players) == app.choose_foreign_team_composition(101)


def test_transition_is_deterministic_and_uses_recruitment_floor():
    master = app.load_master_data()
    previous = app.generate_foreign_import_roster(202609290201, master)
    first = app.advance_foreign_import_roster_year(previous, 202609290202, master)
    second = app.advance_foreign_import_roster_year(previous, 202609290202, master)

    assert first == second
    target = app.choose_foreign_team_composition(202609290202)
    counts = app.foreign_import_role_counts(first)
    assert all(counts[role] >= target[role] for role in ("投手", "野手"))
    assert all(player["roster_year"] == app.NPB_CURRENT_YEAR + 1 for player in first)
    assert all(player["roster_origin"] == "foreign_import" for player in first)
    assert len({player["name"] for player in first}) == len(first)


def test_retained_player_identity_and_protected_fields_are_preserved(monkeypatch):
    master = app.load_master_data()
    previous = app.generate_foreign_import_roster(202609290301, master)
    before = copy.deepcopy(previous)
    monkeypatch.setattr(app, "FOREIGN_TEAM_RETENTION_RATE", 1.0)
    advanced = app.advance_foreign_import_roster_year(previous, 202609290302, master)
    retained = {player["seed"]: player for player in advanced if player["transition_status"] == "retained"}

    assert len(retained) == len(before)
    for old in before:
        new = retained[old["seed"]]
        assert new["name"] == old["name"]
        assert new["seed"] == old["seed"]
        assert new["age"] == old["age"] + 1
        assert new["npb_years"] == old["npb_years"] + 1
        assert new["pro_years"] == old["pro_years"] + 1
        assert new["npb_first_entry_year"] == old["npb_first_entry_year"]
        assert new["npb_stint_start_year"] == old["npb_stint_start_year"]
        assert new["is_returnee"] == old["is_returnee"]
        for key in ("abilities", "special_abilities", "breaking_balls", "height", "weight"):
            assert new[key] == old[key]

    assert previous == before


def test_transition_rejects_domestic_players():
    try:
        app.advance_foreign_import_roster_year(
            [{"name": "国内選手", "roster_origin": "domestic"}],
            1,
            master=object(),
        )
    except ValueError as exc:
        assert "foreign_import" in str(exc)
    else:
        raise AssertionError("domestic選手を年度遷移対象として受理しました。")


def test_validator_reads_team_roster_from_tmp_fixture(tmp_path):
    path = tmp_path / "roster.xlsx"
    rows = [
        {"team": "A", "name": "投手A", "role": "投手", "main_position": "投手"},
        {"team": "A", "name": "捕手A", "role": "野手", "main_position": "捕手"},
        {"team": "B", "name": "投手B", "role": "投手", "main_position": "投手"},
        {"team": "B", "name": "遊撃B", "role": "野手", "main_position": "遊撃手"},
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="players", index=False)

    teams, positions = validator.load_team_roster_target(path)

    assert teams.set_index("team").loc["A", "total_players"] == 2
    assert teams.set_index("team").loc["B", "pitchers"] == 1
    assert positions.set_index("team").loc["A", "捕手"] == 1
    assert positions.set_index("team").loc["B", "遊撃手"] == 1


def test_validator_matches_transition_identity_from_tmp_fixture(tmp_path):
    path = tmp_path / "foreign.xlsx"
    rows = []
    for index in range(73):
        rows.append({
            "season": 2024,
            "team": f"球団{index % 12}",
            "name": f"前年選手{index}",
            "role": "投手" if index % 2 else "野手",
            "nationality": "アメリカ",
            "birth_year": 1980 + index,
            "npb_years": index % 5 + 1,
            "npb_first_entry_year": 2024 - index % 5,
            "include_foreign_analysis": True,
        })
    for index in range(36):
        old = rows[index]
        rows.append({
            **old,
            "season": 2025,
            "team": old["team"] if index < 32 else "移籍先",
            "npb_years": old["npb_years"] + 1,
        })
    for index in range(35):
        rows.append({
            "season": 2025,
            "team": f"球団{index % 12}",
            "name": f"新規選手{index}",
            "role": "投手" if index % 2 else "野手",
            "nationality": "ドミニカ共和国",
            "birth_year": 2100 + index,
            "npb_years": 1,
            "npb_first_entry_year": 2025,
            "include_foreign_analysis": True,
        })
    pd.DataFrame(rows).to_excel(path, sheet_name=validator.FOREIGN_SHEET, index=False)

    previous, current = validator.load_foreign_transition_target(path)

    assert previous["transition"].value_counts().to_dict() == {
        "npb_exit": 37,
        "same_team": 32,
        "other_npb_team": 4,
    }
    assert current["transition"].eq("new_to_npb_dataset").sum() == 35
