from __future__ import annotations

import inspect

from app import (
    adjust_special_chance,
    extra_special_draws,
    generate_player,
    generate_ranked_specials,
    is_special_allowed_for_player,
    load_master_data,
    ranked_shift_for_group,
    ranked_weight_items_for_group,
    special_age_multiplier,
    special_age_tail_adjustment,
    weighted_special_cap,
)


def test_phase2_profile_helper_is_deterministic() -> None:
    values = [special_age_multiplier("変化球中心", "投手", age) for age in range(18, 43)]
    assert values == [special_age_multiplier("変化球中心", "投手", age) for age in range(18, 43)]
    assert "random" not in inspect.getsource(special_age_multiplier)
    assert special_age_multiplier("牽制○", "投手", 34) == 1.0


def test_increase_profile_moves_smoothly_up_with_age() -> None:
    values = [special_age_multiplier("選球眼", "野手", age) for age in [18, 22, 26, 30, 34]]
    assert values == sorted(values)
    assert values[0] < 1.0 < values[-1]


def test_flatten_profile_reduces_existing_age_bias() -> None:
    values = [special_age_multiplier("三振", "野手", age) for age in [18, 22, 26, 30, 34]]
    assert values == sorted(values, reverse=True)
    assert values[0] > 1.0 > values[-1]


def test_phase1_count_logic_is_not_wrapped_by_phase2() -> None:
    for function in [special_age_tail_adjustment, weighted_special_cap, extra_special_draws]:
        assert "special_age_multiplier" not in inspect.getsource(function)
    assert special_age_tail_adjustment("投手", 20, "一軍主力級", 90) == (-1, -1)
    assert special_age_tail_adjustment("野手", 32, "一軍主力級", 60) == (3, 2)


def test_ranked_logic_is_not_wrapped_by_phase2() -> None:
    for function in [ranked_weight_items_for_group, ranked_shift_for_group, generate_ranked_specials]:
        assert "special_age_multiplier" not in inspect.getsource(function)


def test_pro_years_is_not_connected_to_phase2() -> None:
    assert "pro_years" not in inspect.signature(special_age_multiplier).parameters
    assert "pro_year_special_multiplier" not in inspect.getsource(special_age_multiplier)


def test_phase2_same_seed_and_protected_generation() -> None:
    master = load_master_data()
    for role, seed in [("投手", 202609280102), ("野手", 202709280125)]:
        after = generate_player(role, "架空球団用", master, seed=seed)
        assert after == generate_player(role, "架空球団用", master, seed=seed)
        before = generate_player(role, "架空球団用", master, seed=seed, apply_individual_age_profile=False)
        assert {key: value for key, value in after.items() if key != "special_abilities"} == {
            key: value for key, value in before.items() if key != "special_abilities"
        }


def test_phase2_constraints_remain_valid() -> None:
    master = load_master_data()
    groups = {str(row.get("name", "")): str(row.get("group", "") or "") for row in master.abilities}
    conflicts = {
        "積極打法": "慎重打法", "慎重打法": "積極打法", "強振多用": "ミート多用", "ミート多用": "強振多用",
        "積極盗塁": "慎重盗塁", "慎重盗塁": "積極盗塁", "速球中心": "変化球中心", "変化球中心": "速球中心",
        "投球位置左": "投球位置右", "投球位置右": "投球位置左", "チームプレイ○": "チームプレイ×", "チームプレイ×": "チームプレイ○",
    }
    for role, offset in [("投手", 0), ("野手", 10_000_000)]:
        for index in range(40):
            player = generate_player(role, "架空球団用", master, seed=202609300000 + offset + index)
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
