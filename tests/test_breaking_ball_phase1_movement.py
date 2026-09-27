import random

import app


def primary_ball(name: str) -> dict:
    return app.make_breaking_ball(name, 2, False, 1)


def test_primary_movement_partition_preserves_feasible_target():
    names = ["スライダー", "フォーク", "カットボール"]
    for target in range(5, 11):
        balls = [primary_ball(name) for name in names]
        app.normalize_primary_movements(random.Random(target), balls, target)

        assert sum(app.pitch_movement(ball) for ball in balls) == target
        assert all(isinstance(ball["movement"], int) and ball["movement"] > 0 for ball in balls)


def test_primary_movement_partition_respects_hard_bounds():
    for seed in range(300):
        balls = app.generate_breaking_balls(
            random.Random(seed),
            "変化球派",
            "架空球団用",
            {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"},
            "右投右打",
            age=28,
            player_class="一軍主力級",
            archetype="変化球",
            position_style="変化球型先発",
        )
        for ball in balls:
            if ball.get("kind") != "breaking":
                continue
            master = app.BREAKING_BY_NAME[ball["name"]]
            assert int(master["min_movement"]) <= app.pitch_movement(ball) <= int(master["max_movement"])


def test_second_pitch_movement_uses_first_pitch_as_upper_bound():
    for first_value in range(1, 7):
        first = app.make_breaking_ball("フォーク", first_value, False, 1)
        for seed in range(50):
            value = app.select_second_pitch_movement(random.Random(seed), first, "SFF")
            master = app.BREAKING_BY_NAME["SFF"]
            assert int(master["min_movement"]) <= value <= int(master["max_movement"])
            assert value <= first_value


def test_phase1_generation_is_seed_reproducible():
    kwargs = dict(
        player_type="技巧派",
        category="架空球団用",
        aptitudes={"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"},
        batting_throwing="左投左打",
        age=31,
        player_class="一軍主力級",
        archetype="制球",
        position_style="技巧派先発",
    )
    assert app.generate_breaking_balls(random.Random(90210), **kwargs) == app.generate_breaking_balls(random.Random(90210), **kwargs)


def test_existing_pitch_name_and_second_direction_constraints_remain_valid():
    for seed in range(500):
        hand = "左投左打" if seed % 2 else "右投右打"
        balls = app.generate_breaking_balls(
            random.Random(seed),
            "技巧派",
            "架空球団用",
            {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"},
            hand,
            age=27,
            player_class="一軍主力級",
            archetype="制球",
            position_style="技巧派先発",
        )
        primary_directions = {
            str(ball["direction_code"])
            for ball in balls
            if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")
        }
        for ball in balls:
            if ball.get("kind") != "breaking":
                continue
            assert app.is_pitch_allowed_for_generation(str(ball["direction_code"]), ball["name"], hand)
            if ball.get("is_second_pitch"):
                assert str(ball["direction_code"]) in primary_directions
