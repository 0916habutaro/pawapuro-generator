from __future__ import annotations

import inspect

from app import (
    INDIVIDUAL_SPECIAL_AGE_PROFILES,
    PICKOFF_PRO_YEAR_CURVE,
    extra_special_draws,
    generate_player,
    is_countable_special,
    is_special_allowed_for_player,
    load_master_data,
    pro_year_special_multiplier,
    ranked_age_weight_adjustment,
    special_age_multiplier,
    special_age_tail_adjustment,
    special_count_bounds,
    weighted_special_cap,
)


PHASE2_SPECIALS = {name for _, name in INDIVIDUAL_SPECIAL_AGE_PROFILES}


def test_pickoff_pro_year_multiplier_is_deterministic_without_random_draw() -> None:
    values = [pro_year_special_multiplier("牽制○", "投手", year) for year in range(1, 31)]
    assert values == [pro_year_special_multiplier("牽制○", "投手", year) for year in range(1, 31)]
    assert "random" not in inspect.getsource(pro_year_special_multiplier)


def test_pickoff_curve_is_smooth_monotonic_and_very_weak() -> None:
    values = [pro_year_special_multiplier("牽制○", "投手", year) for year in range(1, 31)]
    assert values == sorted(values)
    assert values[0] == 1.0 < values[-1]
    assert min(values) >= 1.0
    assert max(values) <= 1.30
    assert max(right - left for left, right in zip(values, values[1:])) <= 0.040_001
    assert PICKOFF_PRO_YEAR_CURVE[0][0] == 1


def test_non_target_and_missing_pro_year_multiplier_is_neutral() -> None:
    assert pro_year_special_multiplier("牽制○", "投手", None) == 1.0
    assert pro_year_special_multiplier("牽制○", "野手", 12) == 1.0
    assert pro_year_special_multiplier("逃げ球", "投手", 12) == 1.0
    assert pro_year_special_multiplier("選球眼", "野手", 12) == 1.0


def test_phase1_count_logic_is_untouched_by_phase4b() -> None:
    for function in [special_age_tail_adjustment, weighted_special_cap, extra_special_draws]:
        assert "pro_year_special_multiplier" not in inspect.getsource(function)
        assert "pro_years" not in inspect.signature(function).parameters


def test_phase2_profiles_are_untouched_by_phase4b() -> None:
    assert set(INDIVIDUAL_SPECIAL_AGE_PROFILES) == {
        ("投手", "変化球中心"),
        ("投手", "逃げ球"),
        ("投手", "キレ○"),
        ("野手", "選球眼"),
        ("野手", "積極守備"),
        ("野手", "バント○"),
        ("野手", "満塁男"),
        ("野手", "三振"),
    }
    assert "pro_year_special_multiplier" not in inspect.getsource(special_age_multiplier)


def test_ranked_logic_is_untouched_by_phase4b() -> None:
    assert "pro_years" not in inspect.signature(ranked_age_weight_adjustment).parameters
    assert "pro_year_special_multiplier" not in inspect.getsource(ranked_age_weight_adjustment)


def test_same_seed_reproducibility_and_protected_generation() -> None:
    master = load_master_data()
    for role, seed in [("投手", 202610020101), ("野手", 202710020101)]:
        after = generate_player(role, "架空球団用", master, seed=seed)
        assert after == generate_player(role, "架空球団用", master, seed=seed)
        before = generate_player(role, "架空球団用", master, seed=seed, apply_pro_year_profile=False)
        assert {key: value for key, value in after.items() if key != "special_abilities"} == {
            key: value for key, value in before.items() if key != "special_abilities"
        }


def test_phase2_special_outputs_are_protected_for_fixed_seed_sample() -> None:
    master = load_master_data()
    for role, offset in [("投手", 0), ("野手", 1_000_000)]:
        for index in range(50):
            seed = 202610030000 + offset + index
            before = generate_player(role, "架空球団用", master, seed=seed, apply_pro_year_profile=False)
            after = generate_player(role, "架空球団用", master, seed=seed, apply_pro_year_profile=True)
            assert PHASE2_SPECIALS.intersection(before["special_abilities"]) == PHASE2_SPECIALS.intersection(after["special_abilities"])


def test_phase4b_generated_constraints_remain_valid() -> None:
    master = load_master_data()
    groups = {str(row.get("name", "")): str(row.get("group", "") or "") for row in master.abilities}
    conflicts = {
        "積極打法": "慎重打法", "慎重打法": "積極打法", "強振多用": "ミート多用", "ミート多用": "強振多用",
        "積極盗塁": "慎重盗塁", "慎重盗塁": "積極盗塁", "速球中心": "変化球中心", "変化球中心": "速球中心",
        "投球位置左": "投球位置右", "投球位置右": "投球位置左", "チームプレイ○": "チームプレイ×", "チームプレイ×": "チームプレイ○",
    }
    for role, offset in [("投手", 0), ("野手", 10_000_000)]:
        for index in range(25):
            player = generate_player(role, "架空球団用", master, seed=202610040000 + offset + index)
            names = player["special_abilities"]
            name_set = set(names)
            assert len(names) == len(name_set)
            selected_groups = [groups[name] for name in names if groups.get(name)]
            assert len(selected_groups) == len(set(selected_groups))
            assert not any(conflicts.get(name) in name_set for name in names)
            aptitudes = {key: player.get(key, "") for key in ["starter_aptitude", "reliever_aptitude", "closer_aptitude"]}
            assert all(
                is_special_allowed_for_player(name, role, player["position"], player.get("sub_positions", []), aptitudes)
                for name in names
            )
            low, high = special_count_bounds("架空球団用", player["player_class"])
            count = sum(is_countable_special(name) for name in names)
            assert low <= count <= high
