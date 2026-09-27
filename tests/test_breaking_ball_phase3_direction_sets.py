from __future__ import annotations

import random

import app


def primary_balls(player):
    return [
        ball for ball in player["breaking_balls"]
        if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")
    ]


def test_phase3_generation_is_seed_reproducible():
    master = app.load_master_data()
    assert app.generate_player("投手", "架空球団用", master, 330001) == app.generate_player("投手", "架空球団用", master, 330001)


def test_phase3_two_direction_set_has_no_duplicates():
    rng = random.Random(330002)
    for hand in ["右投右打", "左投左打"]:
        for _ in range(500):
            values = app.weighted_direction_sample(rng, list(app.DIRECTION_NAMES), 2, "先発", hand)
            assert len(values) == len(set(values)) == 2


def test_phase3_three_direction_set_has_no_duplicates():
    rng = random.Random(330003)
    for hand in ["右投右打", "左投左打"]:
        for _ in range(500):
            values = app.weighted_direction_sample(rng, list(app.DIRECTION_NAMES), 3, "中継ぎ", hand)
            assert len(values) == len(set(values)) == 3


def test_phase3_uses_only_available_directions_for_each_hand():
    rng = random.Random(330004)
    allowed = {"1", "2", "3", "4", "5"}
    for hand in ["右投右打", "左投左打"]:
        for count in [1, 2, 3, 4]:
            values = app.weighted_direction_sample(rng, list(allowed), count, "先発", hand)
            assert set(values) <= allowed


def test_phase3_left_direction_four_never_uses_right_only_pitch():
    rng = random.Random(330005)
    forbidden = {"シンカー", "Hシンカー"}
    for _ in range(1000):
        name = app.weighted_breaking_names(rng, "4", "技巧派", "架空球団用", "左投左打")
        assert name not in forbidden
        assert name in app.ALLOWED_PITCHES_BY_DIRECTION_LEFT["4"]


def test_phase3_direction_mode_does_not_change_final_pitch_count_for_same_seed():
    master = app.load_master_data()
    try:
        for seed in range(330100, 330300):
            app.PHASE3_DIRECTION_SETS_ENABLED = False
            before = app.generate_player("投手", "架空球団用", master, seed)
            app.PHASE3_DIRECTION_SETS_ENABLED = True
            after = app.generate_player("投手", "架空球団用", master, seed)
            assert len({ball["name"] for ball in before["breaking_balls"]}) == len({ball["name"] for ball in after["breaking_balls"]})
    finally:
        app.PHASE3_DIRECTION_SETS_ENABLED = True


def test_phase3_keeps_movement_bounds_and_phase2_pitch_limit():
    master = app.load_master_data()
    for seed in range(330300, 330800):
        player = app.generate_player("投手", "架空球団用", master, seed)
        assert len({ball["name"] for ball in player["breaking_balls"]}) <= 4
        for ball in primary_balls(player):
            rule = app.BREAKING_BY_NAME[ball["name"]]
            assert rule["min_movement"] <= app.pitch_movement(ball) <= rule["max_movement"]


def test_phase3_direction_sampling_does_not_mutate_movement_rules():
    original = {
        ball["name"]: (ball["min_movement"], ball["max_movement"])
        for ball in app.BREAKING_BALL_MASTER
    }
    rng = random.Random(330800)
    for _ in range(1000):
        app.weighted_direction_sample(rng, list(app.DIRECTION_NAMES), 3, "先発", "左投左打")
    assert original == {
        ball["name"]: (ball["min_movement"], ball["max_movement"])
        for ball in app.BREAKING_BALL_MASTER
    }
