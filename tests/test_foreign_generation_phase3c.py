import hashlib
import json

import app
from scripts import validate_foreign_generation_phase2 as phase2


OBSERVED_COMPOSITIONS = {
    tuple(composition)
    for composition, _weight in app.FOREIGN_TEAM_IMPORT_COMPOSITION_WEIGHTS
}


def test_foreign_team_composition_is_deterministic_and_data_bounded():
    for seed in range(500):
        first = app.choose_foreign_team_composition(seed)
        second = app.choose_foreign_team_composition(seed)
        assert first == second
        assert (first["投手"], first["野手"]) in OBSERVED_COMPOSITIONS


def test_foreign_team_composition_matches_observed_count_ranges():
    for seed in range(500):
        composition = app.choose_foreign_team_composition(seed)
        total = composition["投手"] + composition["野手"]
        assert 4 <= total <= 8
        assert 2 <= composition["投手"] <= 6
        assert 1 <= composition["野手"] <= 4


def test_foreign_import_count_uses_roster_origin_not_nationality():
    players = [
        {"role": "投手", "nationality": "アメリカ", "roster_origin": "domestic"},
        {"role": "野手", "nationality": "日本", "roster_origin": "foreign_import"},
        {"role": "投手", "nationality": "ドミニカ共和国", "roster_origin": "foreign_import"},
    ]
    assert app.foreign_import_role_counts(players) == {"投手": 1, "野手": 1}


def test_generated_foreign_import_roster_follows_composition():
    seed = 202609290001
    players = app.generate_foreign_import_roster(seed, app.load_master_data())
    assert app.foreign_import_role_counts(players) == app.choose_foreign_team_composition(seed)
    assert all(player["roster_origin"] == "foreign_import" for player in players)


def test_returnee_year_invariants_and_rate_parameter():
    assert app.FOREIGN_RETURNEE_RATE == 0.035
    for role_index, role in enumerate(("投手", "野手")):
        for offset in range(1000):
            context = app.generate_foreign_context(202609290100 + role_index * 10_000_000 + offset, role)
            assert context["npb_first_entry_year"] <= context["npb_stint_start_year"]
            if context["is_returnee"]:
                assert context["npb_first_entry_year"] < context["npb_stint_start_year"]


def test_existing_foreign_import_seed_regression():
    expected = {
        # 外国人投手は実在準拠バランス（apply_foreign_pitcher_balance）で再調整した値
        ("投手", 2026092803): "b187eed3b172d4990556b6ca9afca28dc3548e85be1176398e943f50be22c8f9",
        ("野手", 2026092804): "0e32b366d9e4cc8cf1b2d10ba04f195045e95a89a39e0267d4e2ccd7003893d4",
    }
    master = app.load_master_data()
    for (role, seed), expected_hash in expected.items():
        player = app.generate_player(role, "助っ人外国人用", master, seed=seed)
        payload = json.dumps(
            {key: player.get(key) for key in phase2.REGRESSION_KEYS},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == expected_hash
