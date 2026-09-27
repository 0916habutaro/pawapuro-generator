from __future__ import annotations

import inspect
import random

import app as app_module
from app import (
    adjust_special_chance,
    extra_special_draws,
    generate_player,
    generate_ranked_specials,
    is_countable_special,
    is_special_allowed_for_player,
    load_master_data,
    ranked_shift_for_group,
    ranked_weight_items_for_group,
    special_age_tail_adjustment,
    special_count_bounds,
    weighted_special_cap,
)


def test_phase1_age_tail_adjustment_directions() -> None:
    assert special_age_tail_adjustment("投手", 20, "一軍主力級", 60) == (-1, -1)
    assert special_age_tail_adjustment("野手", 29, "一軍主力級", 60) == (2, 1)
    assert special_age_tail_adjustment("野手", 32, "一軍主力級", 60) == (3, 2)
    assert special_age_tail_adjustment("投手", 32, "二軍級", 75) == (0, 0)
    assert special_age_tail_adjustment("野手", 38, "二軍級", 75) == (0, 0)


def test_young_star_high_tail_remains_possible() -> None:
    low, high = special_count_bounds("架空球団用", "スター級")
    caps = [
        weighted_special_cap(random.Random(seed), "架空球団用", "スター級", 72, role="野手", age=20)
        for seed in range(1000)
    ]
    assert min(caps) >= low
    assert max(caps) == high
    assert sum(cap >= 8 for cap in caps) > 100


def test_age_tail_distribution_moves_without_old_low_class_boost() -> None:
    young_main = [
        weighted_special_cap(random.Random(seed), "架空球団用", "一軍主力級", 90, role="投手", age=20)
        for seed in range(1000)
    ]
    prime_main = [
        weighted_special_cap(random.Random(seed), "架空球団用", "一軍主力級", 90, role="投手", age=29)
        for seed in range(1000)
    ]
    assert sum(prime_main) / len(prime_main) - sum(young_main) / len(young_main) >= 1.5

    young_low = [
        weighted_special_cap(random.Random(seed), "架空球団用", "二軍級", 70, role="野手", age=20)
        for seed in range(1000)
    ]
    old_low = [
        weighted_special_cap(random.Random(seed), "架空球団用", "二軍級", 70, role="野手", age=38)
        for seed in range(1000)
    ]
    assert young_low == old_low


def test_age_adjusted_caps_keep_existing_hard_bounds() -> None:
    for role in ["投手", "野手"]:
        for player_class in ["スター級", "一軍主力級", "ベテラン型", "一軍控え級", "二軍級", "若手素材型"]:
            low, high = special_count_bounds("架空球団用", player_class)
            for age in [18, 22, 25, 28, 32, 38]:
                for seed in range(50):
                    cap = weighted_special_cap(random.Random(seed), "架空球団用", player_class, 62, role=role, age=age)
                    assert low <= cap <= high


def test_pro_years_is_not_used_by_phase1_count_functions() -> None:
    assert "pro_years" not in inspect.signature(weighted_special_cap).parameters
    assert "pro_years" not in inspect.signature(extra_special_draws).parameters


def test_ranked_generation_functions_are_not_age_count_wrapped() -> None:
    assert "special_age_tail_adjustment" not in inspect.getsource(ranked_weight_items_for_group)
    assert "special_age_tail_adjustment" not in inspect.getsource(ranked_shift_for_group)
    assert "special_age_tail_adjustment" not in inspect.getsource(generate_ranked_specials)


def test_individual_special_chance_logic_is_not_age_count_wrapped() -> None:
    assert "special_age_tail_adjustment" not in inspect.getsource(adjust_special_chance)


def test_local_rng_protects_all_non_special_generation() -> None:
    master = load_master_data()
    seed = 202609280102
    after = generate_player("投手", "架空球団用", master, seed=seed)
    assert special_age_tail_adjustment(
        "投手",
        after["age"],
        after["player_class"],
        app_module.special_player_score("投手", after["abilities"]),
    ) != (0, 0)
    before = generate_player("投手", "架空球団用", master, seed=seed, apply_age_special_tail=False)
    assert {key: value for key, value in after.items() if key != "special_abilities"} == {
        key: value for key, value in before.items() if key != "special_abilities"
    }


def test_generated_special_constraints_and_restrictions_remain_valid() -> None:
    master = load_master_data()
    groups = {str(row.get("name", "")): str(row.get("group", "") or "") for row in master.abilities}
    conflicts = {
        "積極打法": "慎重打法", "慎重打法": "積極打法", "強振多用": "ミート多用", "ミート多用": "強振多用",
        "積極盗塁": "慎重盗塁", "慎重盗塁": "積極盗塁", "速球中心": "変化球中心", "変化球中心": "速球中心",
        "投球位置左": "投球位置右", "投球位置右": "投球位置左", "チームプレイ○": "チームプレイ×", "チームプレイ×": "チームプレイ○",
    }
    for role, offset in [("投手", 0), ("野手", 10_000_000)]:
        for index in range(80):
            player = generate_player(role, "架空球団用", master, seed=202609290000 + offset + index)
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


def test_same_seed_reproducibility_after_phase1() -> None:
    master = load_master_data()
    for role, seed in [("投手", 202609280101), ("野手", 202709280101)]:
        assert generate_player(role, "架空球団用", master, seed=seed) == generate_player(role, "架空球団用", master, seed=seed)
