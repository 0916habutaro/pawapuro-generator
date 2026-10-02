"""若手（〜21歳）の能力の幅・水準の補正（若手能力の幅_改修指示.md）のテスト。

分布の判定は scripts/check_age_profile.py（個別30000人＋球団500球団）で行う。ここでは変換の性質だけを見る。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402


def fielder_values(base: float) -> dict[str, float]:
    return {key: base for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}


def transformed(values: dict[str, float], age: int, position: str = "外野手") -> dict[str, float]:
    result = dict(values)
    app.fictional_young_transform(
        result, age, app.FICTIONAL_YOUNG_FIELDER_MEANS,
        app.FICTIONAL_YOUNG_FIELDER_POSITION_DEVS[position], app.FICTIONAL_YOUNG_FIELDER_TRANSFORM,
    )
    return result


class YoungTransformTest(unittest.TestCase):
    def test_22_and_older_unchanged(self):
        for age in (22, 23, 30, 38):
            values = fielder_values(55.0)
            self.assertEqual(transformed(values, age), values)

    def test_keeps_order_within_same_age_and_position(self):
        for age in (18, 19, 20, 21):
            for position in app.FICTIONAL_YOUNG_FIELDER_POSITION_DEVS:
                low, high = transformed(fielder_values(35.0), age, position), transformed(fielder_values(60.0), age, position)
                for key in app.FICTIONAL_FIELDER_ABILITY_KEYS:
                    self.assertLess(low[key], high[key], (age, position, key))

    def test_spread_shrinks_most_at_youngest_and_returns_to_one(self):
        def spread(age: int) -> float:
            return transformed(fielder_values(60.0), age)["ミート"] - transformed(fielder_values(40.0), age)["ミート"]

        spreads = [spread(age) for age in (18, 19, 20, 21, 22)]
        self.assertEqual(spreads, sorted(spreads))
        self.assertAlmostEqual(spreads[-1], 20.0)
        self.assertLess(spreads[0], 20.0 * 0.7)

    def test_position_gap_kept(self):
        # 同じ能力の捕手と外野手で、捕球の差（位置ごとの平均の差）が縮んでも残る
        devs = app.FICTIONAL_YOUNG_FIELDER_POSITION_DEVS
        index = app.FICTIONAL_FIELDER_ABILITY_KEYS.index("捕球")
        before_gap = devs["捕手"][index] - devs["外野手"][index]
        mean = app.FICTIONAL_YOUNG_FIELDER_MEANS[18][index]
        catcher = transformed(fielder_values(mean + devs["捕手"][index]), 18, "捕手")["捕球"]
        outfielder = transformed(fielder_values(mean + devs["外野手"][index]), 18, "外野手")["捕球"]
        self.assertGreater(catcher - outfielder, before_gap * 0.7)


class YoungBreakingBallTest(unittest.TestCase):
    def balls(self, movements: list[int]) -> list[dict]:
        names = ["スライダー", "カーブ", "フォーク"]
        return [app.make_breaking_ball(name, movement, False, 1) for name, movement in zip(names, movements)]

    def test_19_and_younger_capped(self):
        result = app.fictional_young_breaking_balls(self.balls([5, 4, 2]), 19)
        self.assertEqual([app.pitch_movement(ball) for ball in result], [3, 2, 1])

    def test_20_and_older_unchanged(self):
        balls = self.balls([5, 4, 2])
        self.assertEqual(app.fictional_young_breaking_balls(balls, 20), balls)


class YoungGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master = app.load_master_data()

    def test_young_pitchers_have_no_movement_four(self):
        found = 0
        for seed in range(1, 1500):
            player = app.generate_player("投手", "架空球団用", self.master, seed=seed)
            if player.get("roster_origin") == "foreign_import" or player["age"] > 19:
                continue
            found += 1
            movements = [app.pitch_movement(ball) for ball in player["breaking_balls"] if ball.get("kind") == "breaking"]
            self.assertLessEqual(max(movements), 3, seed)
        self.assertGreater(found, 10)


if __name__ == "__main__":
    unittest.main()
