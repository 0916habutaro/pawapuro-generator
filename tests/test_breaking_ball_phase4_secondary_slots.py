from __future__ import annotations

import random

import pandas as pd

import app
from scripts.validate_breaking_ball_phase4 import AFTER, count_invalid_directions


def generated_pair(seed: int):
    master = app.load_master_data()
    app.PHASE4_SECONDARY_SLOTS_ENABLED = False
    before = app.generate_player("投手", "架空球団用", master, seed)
    app.PHASE4_SECONDARY_SLOTS_ENABLED = True
    after = app.generate_player("投手", "架空球団用", master, seed)
    return before, after


def visible_count(player):
    return len({ball["name"] for ball in player["breaking_balls"]})


def test_phase4_generation_is_seed_reproducible():
    master = app.load_master_data()
    assert app.generate_player("投手", "架空球団用", master, 440001) == app.generate_player("投手", "架空球団用", master, 440001)


def test_phase4_final_pitch_count_is_unchanged_for_same_seed():
    try:
        for seed in range(440100, 440350):
            before, after = generated_pair(seed)
            assert visible_count(before) == visible_count(after)
            assert visible_count(after) <= 4
    finally:
        app.PHASE4_SECONDARY_SLOTS_ENABLED = True


def test_phase4_secondary_types_are_mutually_exclusive():
    master = app.load_master_data()
    for seed in range(440400, 440900):
        player = app.generate_player("投手", "架空球団用", master, seed)
        second = any(ball.get("kind") == "breaking" and ball.get("is_second_pitch") for ball in player["breaking_balls"])
        fastball = any(ball.get("kind") == "second_fastball" for ball in player["breaking_balls"])
        assert not (second and fastball)


def test_phase4_second_breaking_has_same_direction_primary_and_valid_movement():
    master = app.load_master_data()
    for seed in range(440900, 442000):
        player = app.generate_player("投手", "架空球団用", master, seed)
        primaries = {
            str(ball["direction_code"]): ball
            for ball in player["breaking_balls"]
            if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")
        }
        for ball in player["breaking_balls"]:
            if ball.get("kind") != "breaking" or not ball.get("is_second_pitch"):
                continue
            code = str(ball["direction_code"])
            rule = app.BREAKING_BY_NAME[ball["name"]]
            assert code in primaries
            assert rule["min_movement"] <= app.pitch_movement(ball) <= rule["max_movement"]
            assert app.pitch_movement(ball) <= app.pitch_movement(primaries[code])


def test_phase4_second_fastball_type_weights_are_preserved():
    rng = random.Random(440010)
    values = [app.select_second_fastball_type(rng)["name"] for _ in range(5000)]
    assert set(values) == set(app.SECOND_FASTBALL_TYPES)
    assert values.count("ツーシームファスト") / len(values) > 0.88


def test_phase4_age_structure_is_smooth_and_veteran_rate_declines():
    breaking = [app.phase4_composition_chances(age, "先発")[0] for age in range(18, 41)]
    fastball = [app.phase4_composition_chances(age, "先発")[1] for age in range(18, 41)]
    assert max(abs(right - left) for left, right in zip(breaking, breaking[1:], strict=False)) < 0.05
    assert max(abs(right - left) for left, right in zip(fastball, fastball[1:], strict=False)) < 0.05
    assert fastball[30 - 18] > fastball[26 - 18] > fastball[22 - 18]
    assert fastball[34 - 18] > fastball[40 - 18]


def test_phase4_keeps_phase1_bounds_phase2_count_and_phase3_directions():
    master = app.load_master_data()
    for seed in range(442000, 442500):
        player = app.generate_player("投手", "架空球団用", master, seed)
        assert visible_count(player) <= 4
        directions = []
        for ball in player["breaking_balls"]:
            if ball.get("kind") != "breaking" or ball.get("is_second_pitch"):
                continue
            directions.append(str(ball["direction_code"]))
            rule = app.BREAKING_BY_NAME[ball["name"]]
            assert rule["min_movement"] <= app.pitch_movement(ball) <= rule["max_movement"]
        assert len(directions) == len(set(directions))
        assert set(directions) <= set(app.DIRECTION_NAMES)


def test_phase4_pitch_shortage_profile_is_not_forced_into_composition():
    balls = [app.make_breaking_ball("スライダー", 3, False, 1) for _ in range(3)]
    assert app.choose_repertoire_composition(random.Random(4), balls, 28, "先発", "架空球団用", "球種不足") == "primary_only"


def test_phase4_invalid_direction_count_detects_duplicate_and_hand_mismatch():
    valid = pd.DataFrame([{
        "dataset": AFTER,
        "hand": "左投",
        "balls": [app.make_breaking_ball("スクリュー", 2, False, 1)],
    }])
    invalid = pd.DataFrame([{
        "dataset": AFTER,
        "hand": "左投",
        "balls": [
            app.make_breaking_ball("シンカー", 2, False, 1),
            app.make_breaking_ball("スクリュー", 2, False, 1),
        ],
    }])
    assert count_invalid_directions(valid) == 0
    assert count_invalid_directions(invalid) == 1
