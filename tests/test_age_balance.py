import random
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def test_fictional_roster_age_distribution_is_npb_shaped():
    rng = random.Random(20260925)
    ages = [app.age_for(rng, "架空球団用") for _ in range(50_000)]
    bands = Counter(
        "18-22" if age <= 22 else
        "23-30" if age <= 30 else
        "31-34" if age <= 34 else
        "35+" if age >= 35 else "other"
        for age in ages
    )

    assert bands["23-30"] > bands["18-22"] * 3
    assert 0.06 <= bands["35+"] / len(ages) <= 0.10
    assert 0.02 <= sum(age >= 37 for age in ages) / len(ages) <= 0.05
    assert 0 < sum(age >= 40 for age in ages) / len(ages) < 0.02
    assert max(ages) == 46
    assert {43, 44, 45, 46}.issubset(ages)


def test_fictional_age_generation_is_seed_reproducible():
    first = random.Random(99173)
    second = random.Random(99173)
    assert [app.age_for(first, "架空球団用") for _ in range(100)] == [app.age_for(second, "架空球団用") for _ in range(100)]


def test_fielder_age_curve_keeps_youth_raw_and_veterans_viable():
    young = app.fielder_age_mods(18, "バランス", "一軍主力級")
    prime = app.fielder_age_mods(27, "バランス", "一軍主力級")
    veteran = app.fielder_age_mods(35, "バランス", "ベテラン型")
    veteran_prime = app.fielder_age_mods(27, "バランス", "ベテラン型")

    assert young["ミート"] < prime["ミート"]
    assert young["パワー"] < prime["パワー"]
    assert veteran["走力"] < veteran_prime["走力"]
    assert veteran["ミート"] >= veteran_prime["ミート"] - 6
    assert veteran["パワー"] >= veteran_prime["パワー"] - 8


def test_pitcher_age_curve_matures_control_and_reduces_veteran_speed():
    young = app.pitcher_age_mods(18, "制球", "一軍主力級")
    prime = app.pitcher_age_mods(28, "制球", "一軍主力級")
    veteran = app.pitcher_age_mods(35, "制球", "ベテラン型")

    assert young["コントロール"] < prime["コントロール"]
    assert veteran["球速"] < prime["球速"]
    assert veteran["コントロール"] >= prime["コントロール"]


def test_veteran_starter_stamina_is_role_dependent():
    starter = {"球速": 145, "コントロール": 55, "スタミナ": 50}
    reliever = starter.copy()
    app.apply_veteran_pitcher_role_mods(starter, 36, {"starter_aptitude": "◎"}, "ベテラン型", "制球")
    app.apply_veteran_pitcher_role_mods(reliever, 36, {"starter_aptitude": "-"}, "ベテラン型", "制球")
    assert starter["スタミナ"] == 55
    assert reliever["スタミナ"] == 50


def test_young_pitcher_stamina_reduction_keeps_top_starter_exception():
    ordinary = {"球速": 150, "コントロール": 40, "スタミナ": 50}
    prospect = ordinary.copy()
    app.apply_young_pitcher_stamina_mods(ordinary, 18, "架空球団用", {"starter_aptitude": "-"}, "若手素材型", "速球", "")
    app.apply_young_pitcher_stamina_mods(prospect, 18, "ドラフト候補用", {"starter_aptitude": "◎"}, "超上位候補", "スタミナ", "素材型")
    assert ordinary["スタミナ"] == 43
    assert prospect["スタミナ"] == 48


def test_veteran_player_class_distribution_has_survivor_bias():
    sample_size = 20_000
    prime_rng = random.Random(4201)
    veteran_rng = random.Random(4201)
    prime = Counter(app.choose_player_class(prime_rng, "架空球団用", 28) for _ in range(sample_size))
    veteran = Counter(app.choose_player_class(veteran_rng, "架空球団用", 36) for _ in range(sample_size))

    assert veteran["二軍級"] < prime["二軍級"] * 0.25
    assert veteran["一軍控え級"] < prime["一軍控え級"]
    assert veteran["一軍主力級"] > prime["一軍主力級"]
    assert veteran["ベテラン型"] > prime["ベテラン型"] * 2


def test_veteran_pitcher_archetype_distribution_favors_command_and_breaking():
    sample_size = 20_000
    prime_rng = random.Random(8102)
    veteran_rng = random.Random(8102)
    prime = Counter(app.choose_archetype(prime_rng, "投手", "架空球団用", age=28) for _ in range(sample_size))
    veteran = Counter(app.choose_archetype(veteran_rng, "投手", "架空球団用", age=36) for _ in range(sample_size))

    assert veteran["制球"] + veteran["変化球"] > prime["制球"] + prime["変化球"]
    assert veteran["速球"] < prime["速球"] * 0.60


def test_active_veterans_favor_late_growth_without_eliminating_early_types():
    young = app.growth_type_weight_map("架空球団用", 28, "一軍控え級", "", "")
    veteran = app.growth_type_weight_map("架空球団用", 36, "ベテラン型", "", "")

    assert veteran["late"] + veteran["very_late"] > young["late"] + young["very_late"]
    assert veteran["very_early"] + veteran["early"] < young["very_early"] + young["early"]
    assert veteran["very_early"] > 0
    assert veteran["early"] > 0


def test_veteran_growth_type_distribution_is_stable_with_fixed_seeds():
    sample_size = 20_000
    counts = Counter()
    for seed in range(700_000, 700_000 + sample_size):
        player_class = app.choose_player_class(random.Random(seed), "架空球団用", 36)
        growth_type = app.choose_growth_type(
            category="架空球団用",
            age=36,
            player_class=player_class,
            development_stage="",
            acquisition_role="",
            rng=app.create_growth_rng(seed, "投手", "架空球団用"),
        )
        counts[growth_type] += 1

    early_rate = (counts["very_early"] + counts["early"]) / sample_size
    late_rate = (counts["late"] + counts["very_late"]) / sample_size
    assert 0.03 <= early_rate <= 0.09
    assert 0.42 <= late_rate <= 0.55
    assert 0.40 <= counts["normal"] / sample_size <= 0.52
    assert all(counts[growth_type] > 0 for growth_type in app.VALID_GROWTH_TYPES)


def test_growth_delta_is_an_individual_deviation_at_old_age():
    assert app.growth_age_delta(36, "normal") == 0
    assert app.growth_age_delta(36, "very_early") < 0
    assert app.growth_age_delta(36, "very_late") > 0
    assert abs(app.growth_age_delta(38, "very_early")) < 10
