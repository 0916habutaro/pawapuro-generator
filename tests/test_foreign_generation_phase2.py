import random
from collections import Counter

import app


def sample(count, chooser):
    return Counter(chooser(random.Random(seed)) for seed in range(count))


def test_foreign_tenure_and_route_groups():
    assert [app.foreign_tenure_band(years) for years in (1, 2, 3, 4, 8)] == ["1", "2-3", "2-3", "4+", "4+"]
    assert app.foreign_route_group("north_america_pro") == "north_america_pro"
    assert app.foreign_route_group("latin_development") == "development_direct"
    assert app.foreign_route_group("taiwan_amateur_direct") == "development_direct"
    assert app.foreign_route_group("korea_pro") == "asian_pro"
    assert app.foreign_route_group("other_foreign_pro") == "other"


def test_long_tenure_selects_stronger_player_classes_without_hard_exclusions():
    first = sample(4_000, lambda rng: app.choose_player_class(rng, "助っ人外国人用", 30, 1, "north_america_pro"))
    long = sample(4_000, lambda rng: app.choose_player_class(rng, "助っ人外国人用", 30, 5, "north_america_pro"))
    first_core = first["大物実績者"] + first["主力期待級"]
    long_core = long["大物実績者"] + long["主力期待級"]
    assert long_core > first_core
    assert long["保険・バックアップ級"] < first["保険・バックアップ級"]
    assert long["保険・バックアップ級"] > 0
    assert long["再生候補"] > 0


def test_long_tenure_reduces_key_weaknesses_and_keeps_low_speed_possible():
    pitcher_first = sample(4_000, lambda rng: app.choose_weakness_profile(rng, "助っ人外国人用", "投手", "主力期待級", 1))
    pitcher_long = sample(4_000, lambda rng: app.choose_weakness_profile(rng, "助っ人外国人用", "投手", "主力期待級", 5))
    assert pitcher_long["低制球"] < pitcher_first["低制球"] / 2
    assert pitcher_long["明確な弱点なし"] > pitcher_first["明確な弱点なし"]

    fielder_first = sample(4_000, lambda rng: app.choose_weakness_profile(rng, "助っ人外国人用", "野手", "主力期待級", 1))
    fielder_long = sample(4_000, lambda rng: app.choose_weakness_profile(rng, "助っ人外国人用", "野手", "主力期待級", 5))
    assert fielder_long["低ミート"] < fielder_first["低ミート"] / 2
    assert fielder_long["低守備"] < fielder_first["低守備"]
    assert fielder_long["低捕球"] < fielder_first["低捕球"]
    assert fielder_long["低走力"] > 0


def test_long_tenure_softly_shifts_archetype_and_acquisition_role():
    first_archetype = sample(4_000, lambda rng: app.choose_archetype(rng, "野手", "助っ人外国人用", npb_years=1, foreign_route="north_america_pro"))
    long_archetype = sample(4_000, lambda rng: app.choose_archetype(rng, "野手", "助っ人外国人用", npb_years=5, foreign_route="north_america_pro"))
    assert long_archetype["巧打"] > first_archetype["巧打"]
    assert long_archetype["俊足"] < first_archetype["俊足"]
    assert long_archetype["俊足"] > 0

    first_role = sample(4_000, lambda rng: app.choose_acquisition_role(rng, "助っ人外国人用", "野手", "主力期待級", "一塁手", npb_years=1, foreign_route="north_america_pro"))
    long_role = sample(4_000, lambda rng: app.choose_acquisition_role(rng, "助っ人外国人用", "野手", "主力期待級", "一塁手", npb_years=5, foreign_route="north_america_pro"))
    assert long_role["主砲候補"] + long_role["中軸候補"] > first_role["主砲候補"] + first_role["中軸候補"]
    assert long_role["保険要員"] < first_role["保険要員"]
    assert long_role["保険要員"] > 0


def test_phase2_changes_only_foreign_import_classification_path():
    master = app.load_master_data()
    for role in ("投手", "野手"):
        player = app.generate_player(role, "助っ人外国人用", master, seed=20260928)
        assert player["roster_origin"] == "foreign_import"
        assert player["npb_years"] >= 1
        assert player["player_class"]
        assert player["weakness_profile"]
        assert player["archetype"]
        assert player["acquisition_role"]
