from __future__ import annotations

import inspect
import json

from app import (
    INDIVIDUAL_SPECIAL_AGE_CURVES,
    INDIVIDUAL_SPECIAL_AGE_PROFILES,
    extra_special_draws,
    generate_player,
    load_master_data,
    ranked_age_weight_adjustment,
    ranked_related_ability_score,
    special_age_multiplier,
    special_age_tail_adjustment,
    weighted_special_cap,
)


def test_ranked_age_adjustment_is_deterministic() -> None:
    abilities = {"ミート": {"value": 70}, "パワー": {"value": 65}}
    first = ranked_age_weight_adjustment("チャンス", "野手", 31, "一軍主力級", abilities)
    assert first == ranked_age_weight_adjustment("チャンス", "野手", 31, "一軍主力級", abilities)
    assert "random" not in inspect.getsource(ranked_age_weight_adjustment)


def test_young_good_rank_moves_down_without_hard_ban() -> None:
    adjustment = ranked_age_weight_adjustment("チャンス", "野手", 19, "若手素材型", {"ミート": {"value": 45}, "パワー": {"value": 45}})
    assert 0 < adjustment["A"] < adjustment["B"] < adjustment["C"] < 1.0


def test_middle_main_player_good_rank_moves_up() -> None:
    adjustment = ranked_age_weight_adjustment("送球", "野手", 32, "一軍主力級", {"肩力": {"value": 75}, "守備力": {"value": 72}})
    assert adjustment["A"] == 1.0
    assert adjustment["B"] > 1.0
    assert adjustment["C"] > adjustment["B"]


def test_young_star_exception_is_preserved() -> None:
    abilities = {"ミート": {"value": 82}, "パワー": {"value": 80}}
    star = ranked_age_weight_adjustment("チャンス", "野手", 20, "スター級", abilities)
    material = ranked_age_weight_adjustment("チャンス", "野手", 20, "若手素材型", abilities)
    assert star["A"] > material["A"]
    assert star["B"] > material["B"]
    assert star["C"] > material["C"]


def test_old_minor_player_has_no_unconditional_boost() -> None:
    adjustment = ranked_age_weight_adjustment("ノビ", "投手", 35, "二軍級", {"球速": 157, "コントロール": 78, "スタミナ": 75})
    assert adjustment["A"] == adjustment["B"] == adjustment["C"] == 1.0


def test_low_related_ability_does_not_gain_b_or_c() -> None:
    adjustment = ranked_age_weight_adjustment("盗塁", "野手", 34, "一軍主力級", {"走力": {"value": 40}})
    assert adjustment["B"] == 1.0
    assert adjustment["C"] == 1.0
    assert ranked_related_ability_score("盗塁", "野手", {"走力": {"value": 40}}) == 40


def test_phase1_count_logic_is_unchanged_by_phase3() -> None:
    for function in [special_age_tail_adjustment, weighted_special_cap, extra_special_draws]:
        assert "ranked_age" not in inspect.getsource(function)
    assert special_age_tail_adjustment("投手", 20, "一軍主力級", 90) == (-1, -1)
    assert special_age_tail_adjustment("野手", 32, "一軍主力級", 60) == (3, 2)


def test_phase2_profiles_are_unchanged_and_not_wrapped() -> None:
    assert INDIVIDUAL_SPECIAL_AGE_PROFILES[("投手", "変化球中心")] == "experience_up"
    assert INDIVIDUAL_SPECIAL_AGE_CURVES["experience_up"] == [(18, 0.85), (22, 0.90), (26, 0.97), (30, 1.08), (34, 1.18), (38, 1.15), (42, 1.07)]
    assert "ranked_age" not in inspect.getsource(special_age_multiplier)


def test_pro_years_is_not_connected_to_phase3() -> None:
    assert "pro_years" not in inspect.signature(ranked_age_weight_adjustment).parameters
    assert "pro_years" not in inspect.getsource(ranked_age_weight_adjustment)


def test_same_seed_preserves_all_non_ranked_generation() -> None:
    master = load_master_data()
    for role, seed in [("投手", 202609280113), ("野手", 202709280137)]:
        before = generate_player(role, "架空球団用", master, seed=seed, apply_ranked_age_profile=False)
        after = generate_player(role, "架空球団用", master, seed=seed, apply_ranked_age_profile=True)
        assert after == generate_player(role, "架空球団用", master, seed=seed, apply_ranked_age_profile=True)
        assert before["special_abilities"] == after["special_abilities"]
        before_copy = json.loads(json.dumps(before, ensure_ascii=False))
        after_copy = json.loads(json.dumps(after, ensure_ascii=False))
        before_copy["abilities"].pop("ranked_specials")
        after_copy["abilities"].pop("ranked_specials")
        assert before_copy == after_copy


def test_phase3_generated_constraints_remain_valid() -> None:
    master = load_master_data()
    for role, offset in [("投手", 0), ("野手", 10_000_000)]:
        for index in range(30):
            player = generate_player(role, "架空球団用", master, seed=202610010000 + offset + index)
            ranked = player["abilities"]["ranked_specials"]
            assert len(ranked) == len(set(ranked))
            assert all(str(name)[-1:] in set("ABCDEFG") for name in ranked.values())
