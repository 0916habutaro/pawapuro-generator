"""架空球団用の日本人野手の走力（野手の走力_改修指示.md）のテスト。

分布の判定は scripts/check_fielder_speed.py（球団生成300球団）で行う。ここでは変換の性質と、
21歳以下・ほかの区分が変わらないことを見る。
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

LEFT, RIGHT, SWITCH = "右投左打", "右投右打", "右投両打"


def adjust(speed: float, position: str = "外野手", age: int = 28, batting_throwing: str = RIGHT) -> float:
    return app.fictional_speed_adjust(speed, position, age, batting_throwing)


def fielder_abilities(speed: int) -> dict:
    return {key: app.ability(speed if key == "走力" else 55) for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}


def speed_of(age: int, position: str = "外野手", batting_throwing: str = RIGHT, speed: int = 60) -> int:
    result = app.fictional_fielder_abilities(random.Random(1), fielder_abilities(speed), position, age, batting_throwing)
    return result["走力"]["value"]


class BatsShiftTest(unittest.TestCase):
    def test_left_and_switch_faster_than_right_in_every_position(self):
        for position in ("一塁手", "二塁手", "三塁手", "遊撃手", "外野手", "捕手"):
            right = adjust(60.0, position, 28, RIGHT)
            self.assertGreater(adjust(60.0, position, 28, LEFT), right, position)
            self.assertEqual(adjust(60.0, position, 28, SWITCH), adjust(60.0, position, 28, LEFT), position)

    def test_first_and_second_base_have_larger_gap(self):
        def gap(position: str) -> float:
            return adjust(60.0, position, 28, LEFT) - adjust(60.0, position, 28, RIGHT)

        self.assertGreater(gap("一塁手"), gap("外野手"))
        self.assertGreater(gap("二塁手"), gap("外野手"))

    def test_batting_hand_is_read_from_batting_side_not_throwing_side(self):
        # 「左投右打」は右打、「右投左打」は左打（末尾の「打」の1つ前が打席）
        self.assertEqual(adjust(60.0, "外野手", 28, "左投右打"), adjust(60.0, "外野手", 28, "右投右打"))
        self.assertGreater(adjust(60.0, "外野手", 28, "左投左打"), adjust(60.0, "外野手", 28, "右投右打"))


class AgeShiftTest(unittest.TestCase):
    def test_peak_is_late_twenties_to_early_thirties_and_decline_starts_at_32(self):
        values = {age: adjust(60.0, "外野手", age, RIGHT) for age in range(22, 41)}
        self.assertLess(values[22], values[27])
        self.assertLess(values[27], values[31])
        self.assertGreater(values[31], values[34])
        self.assertGreater(values[31], values[32])

    def test_continuous_without_steps(self):
        values = [adjust(60.0, "外野手", age, RIGHT) for age in range(22, 45)]
        self.assertLessEqual(max(abs(b - a) for a, b in zip(values, values[1:])), 3.0)

    def test_flat_after_last_point(self):
        self.assertEqual(adjust(60.0, "外野手", 38), adjust(60.0, "外野手", 45))


class PositionTransformTest(unittest.TestCase):
    def test_outfielder_is_not_changed_except_tail_age_and_bats(self):
        base = adjust(60.0, "外野手", 28, RIGHT)
        shift = app.interpolate_age_chance(28, app.FICTIONAL_SPEED_AGE_SHIFTS) + app.FICTIONAL_SPEED_BATS_SHIFTS["既定"]["右"]
        self.assertAlmostEqual(base, 60.0 + shift)

    def test_first_base_and_shortstop_are_narrowed(self):
        for position in ("一塁手", "遊撃手"):
            low, high = adjust(40.0, position), adjust(90.0, position)
            self.assertLess(high - low, 50.0 * 0.95, position)

    def test_upper_tail_is_stretched_then_capped(self):
        shift = app.interpolate_age_chance(28, app.FICTIONAL_SPEED_AGE_SHIFTS) + app.FICTIONAL_SPEED_BATS_SHIFTS["既定"]["右"]
        # 70より上は倍率どおりに伸びる（上の端の境目より下）
        self.assertAlmostEqual(adjust(75.0, "外野手", 28) - shift, 70.0 + 5.0 * app.FICTIONAL_SPEED_UPPER_FACTOR)
        # 境目より上は縮む（境目から倍率分の距離）
        edge, factor = app.FICTIONAL_SPEED_UPPER_CAP
        uncapped = 70.0 + 30.0 * app.FICTIONAL_SPEED_UPPER_FACTOR + shift
        self.assertGreater(uncapped, edge)
        self.assertAlmostEqual(adjust(100.0, "外野手", 28), edge + (uncapped - edge) * factor)
        self.assertLess(adjust(100.0, "外野手", 28), uncapped)

    def test_monotonic_in_input_speed(self):
        for position in ("一塁手", "二塁手", "遊撃手", "外野手", "捕手", "三塁手"):
            values = [adjust(float(speed), position, 28, LEFT) for speed in range(20, 101)]
            self.assertEqual(values, sorted(values), position)


class YoungUnchangedTest(unittest.TestCase):
    def test_21_and_under_do_not_depend_on_batting_hand(self):
        for age in (18, 19, 20, 21):
            for position in ("一塁手", "遊撃手", "外野手"):
                self.assertEqual(speed_of(age, position, LEFT), speed_of(age, position, RIGHT), (age, position))

    def test_22_and_over_depend_on_batting_hand(self):
        self.assertGreater(speed_of(28, "一塁手", LEFT), speed_of(28, "一塁手", RIGHT))

    def test_21_and_under_ignore_the_new_constants(self):
        # 年齢・打席・ポジション・上側の倍率の新しい定数を変えても、21歳以下の走力は変わらない（若手の補正の範囲）
        before = {age: speed_of(age, "一塁手", LEFT, 90) for age in (18, 21)}
        before_adult = speed_of(28, "一塁手", LEFT, 90)
        original = app.FICTIONAL_SPEED_UPPER_FACTOR
        app.FICTIONAL_SPEED_UPPER_FACTOR = 1.0
        try:
            self.assertEqual({age: speed_of(age, "一塁手", LEFT, 90) for age in (18, 21)}, before)
            self.assertNotEqual(speed_of(28, "一塁手", LEFT, 90), before_adult)
        finally:
            app.FICTIONAL_SPEED_UPPER_FACTOR = original


if __name__ == "__main__":
    unittest.main()
