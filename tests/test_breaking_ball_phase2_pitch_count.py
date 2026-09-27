import random

import app


APTITUDES = {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"}


def generate(seed: int, age: int = 28, aptitudes: dict | None = None) -> list[dict]:
    return app.generate_breaking_balls(
        random.Random(seed),
        "技巧派",
        "架空球団用",
        aptitudes or APTITUDES,
        "右投右打",
        age=age,
        player_class="一軍主力級",
        archetype="制球",
        position_style="技巧派先発",
    )


def display_count(balls: list[dict]) -> int:
    return sum(1 for ball in balls if ball.get("kind") in {"breaking", "second_fastball"})


def test_phase2_generation_is_seed_reproducible():
    assert generate(112233, 31) == generate(112233, 31)


def test_phase2_final_pitch_count_never_exceeds_four():
    for seed in range(1000):
        assert display_count(generate(seed, 18 + seed % 23)) <= 4


def test_phase2_prevents_young_four_pitch_excess():
    samples = [generate(seed, 18 + seed % 5) for seed in range(1000)]
    four_pitch_rate = sum(display_count(balls) >= 4 for balls in samples) / len(samples)
    assert four_pitch_rate <= 0.03


def test_phase2_second_pitch_and_second_fastball_compete():
    for seed in range(1500):
        balls = generate(seed, 30)
        has_second = any(ball.get("kind") == "breaking" and ball.get("is_second_pitch") for ball in balls)
        has_second_fastball = any(ball.get("kind") == "second_fastball" for ball in balls)
        assert not (has_second and has_second_fastball)


def test_phase2_keeps_phase1_movement_bounds_and_positive_values():
    for seed in range(500):
        for ball in generate(seed, 18 + seed % 23):
            if ball.get("kind") != "breaking":
                continue
            master = app.BREAKING_BY_NAME[ball["name"]]
            assert int(master["min_movement"]) <= app.pitch_movement(ball) <= int(master["max_movement"])
            assert isinstance(ball["movement"], int) and ball["movement"] > 0


def test_phase2_does_not_promote_pitch_shortage_profile():
    balls = app.generate_breaking_balls(
        random.Random(9),
        "技巧派",
        "架空球団用",
        APTITUDES,
        "右投右打",
        age=33,
        player_class="二軍級",
        archetype="制球",
        weakness_profile="球種不足",
    )
    primary = [ball for ball in balls if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")]
    assert len(primary) <= 2


def test_phase2_role_pitch_limits_remain_valid():
    roles = [
        {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"},
        {"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "-"},
        {"starter_aptitude": "-", "reliever_aptitude": "-", "closer_aptitude": "◎"},
    ]
    for aptitudes in roles:
        samples = [generate(seed, 29, aptitudes) for seed in range(200)]
        assert all(2 <= display_count(balls) <= 4 for balls in samples)
