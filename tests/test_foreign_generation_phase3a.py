import random
from unittest.mock import patch

import app


def test_foreign_fielder_class_modifier_is_ability_specific():
    values = {key: 48 for key in app.FIELDER_ABILITY_KEYS}

    app.apply_fielder_player_class_mods(values, "助っ人外国人用", "主力期待級")

    assert values == {
        "ミート": 47, "パワー": 58, "走力": 53,
        "肩力": 61, "守備力": 43, "捕球": 42,
    }
    assert values["パワー"] > values["ミート"]
    assert values["守備力"] < values["肩力"]


def test_non_foreign_fielder_class_modifiers_are_unchanged():
    fictional = {key: 48 for key in app.FIELDER_ABILITY_KEYS}
    draft = {key: 48 for key in app.FIELDER_ABILITY_KEYS}

    app.apply_fielder_player_class_mods(fictional, "架空球団用", "一軍主力級")
    app.apply_fielder_player_class_mods(draft, "ドラフト候補用", "上位候補")

    assert fictional == {
        "ミート": 49, "パワー": 53, "走力": 53,
        "肩力": 54, "守備力": 48, "捕球": 47,
    }
    assert all(value == 51 for value in draft.values())


def test_foreign_pitcher_baseline_does_not_apply_to_other_categories():
    assert app.pitcher_base_values("助っ人外国人用") == {"球速": 155, "コントロール": 44, "スタミナ": 49}
    assert app.pitcher_base_values("架空球団用") == {"球速": 145, "コントロール": 48, "スタミナ": 48}
    assert app.pitcher_base_values("ドラフト候補用") == {"球速": 145, "コントロール": 48, "スタミナ": 48}


def test_foreign_high_speed_audit_stays_in_foreign_range():
    values = {"球速": 165, "コントロール": 50, "スタミナ": 50}

    app.finalize_pitcher_values(
        random.Random(17), values, "助っ人外国人用", 29,
        "主力期待級", "総合", "総合型先発", "先発", "",
    )

    assert 157 <= values["球速"] <= 159


def test_fictional_foreign_import_uses_common_foreign_ability_model():
    master = app.load_master_data()
    original = app.generate_fielder_abilities
    seen_categories = []

    def record_category(*args, **kwargs):
        seen_categories.append(args[4])
        return original(*args, **kwargs)

    with (
        patch.object(app, "choose_nationality", return_value="アメリカ"),
        patch.object(app, "determine_roster_origin", return_value="foreign_import"),
        patch.object(app, "generate_fielder_abilities", side_effect=record_category),
    ):
        player = app.generate_player("野手", "架空球団用", master, seed=990031)

    assert player["category"] == "架空球団用"
    assert player["roster_origin"] == "foreign_import"
    assert seen_categories and set(seen_categories) == {"助っ人外国人用"}


def test_phase3a_foreign_generation_is_deterministic_and_bounded():
    master = app.load_master_data()
    for role in ("投手", "野手"):
        first = app.generate_player(role, "助っ人外国人用", master, seed=2026092803)
        second = app.generate_player(role, "助っ人外国人用", master, seed=2026092803)
        assert first == second
        if role == "投手":
            assert 125 <= app.pitcher_speed_value(first["abilities"]) <= 165
            keys = ("コントロール", "スタミナ")
        else:
            keys = app.FIELDER_ABILITY_KEYS
        assert all(1 <= app.ability_numeric_value(first["abilities"], key) <= 100 for key in keys)
