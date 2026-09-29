from __future__ import annotations

import random

import app


def test_young_fictional_players_are_not_classified_as_veterans():
    for age in (18, 19, 20, 21, 22, 23, 24):
        for seed in range(200):
            assert app.choose_player_class(random.Random(seed), "架空球団用", age) != "ベテラン型"


def test_second_pitch_never_exceeds_same_direction_primary_pitch():
    master = app.load_master_data()
    for seed in (202610402184, 202610402362):
        player = app.generate_player("投手", "助っ人外国人用", master, seed=seed)
        primary = {
            str(ball["direction_code"]): ball
            for ball in player["breaking_balls"]
            if ball.get("kind", "breaking") == "breaking" and not ball.get("is_second_pitch")
        }
        for ball in player["breaking_balls"]:
            if ball.get("kind", "breaking") != "breaking" or not ball.get("is_second_pitch"):
                continue
            first = primary[str(ball["direction_code"])]
            assert app.pitch_movement(ball) <= app.pitch_movement(first)


def test_defensive_catcher_keeps_position_minimum_after_total_cap():
    player = app.generate_player(
        "野手", "架空球団用", app.load_master_data(), seed=202610402253,
    )
    assert player["position"] == "捕手"
    assert player["position_style"] == "守備型捕手"
    assert app.ability_numeric_value(player["abilities"], "守備力") >= 50
    assert app.ability_numeric_value(player["abilities"], "捕球") >= 50
