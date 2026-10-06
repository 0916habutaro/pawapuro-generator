"""架空球団用の日本人野手の打席ごとの能力（野手の打席の型_改修指示.md）のテスト。

分布の判定は scripts/check_fielder_batting.py（球団生成300球団）で行う。ここではずらしの向きと、
走力・両打・ほかの区分が変わらないことを見る。
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

LEFT, RIGHT, SWITCH = "右投左打", "右投右打", "右投両打"
SHIFTED = ("ミート", "パワー", "守備力", "肩力", "捕球")


def abilities_of(batting_throwing: str, age: int, position: str = "外野手") -> dict:
    base = {key: app.ability(55) for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}
    return app.fictional_fielder_abilities(random.Random(1), base, position, age, batting_throwing)


def values_of(batting_throwing: str, age: int, position: str = "外野手") -> dict:
    result = abilities_of(batting_throwing, age, position)
    return {key: result[key]["value"] for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}


def shifted_values_of(batting_throwing: str, age: int) -> dict:
    """打席のずらしの対象（走力は PR #113 の別のずらし）だけ。"""
    values = values_of(batting_throwing, age)
    return {key: values[key] for key in SHIFTED}


class AdultBatsShiftTest(unittest.TestCase):
    def test_left_has_higher_contact_fielding_catching_and_lower_power_arm(self):
        left, right = values_of(LEFT, 28), values_of(RIGHT, 28)
        self.assertGreater(left["ミート"], right["ミート"] + 4)
        self.assertGreater(left["守備力"], right["守備力"])
        self.assertGreater(left["捕球"], right["捕球"])
        self.assertLess(left["パワー"], right["パワー"])
        self.assertLess(left["肩力"], right["肩力"])

    def test_contact_gap_matches_table(self):
        shifts = app.FICTIONAL_FIELDER_BATS_SHIFTS["一般"]
        expected = shifts["左"]["ミート"] - shifts["右"].get("ミート", 0.0)
        gap = values_of(LEFT, 28)["ミート"] - values_of(RIGHT, 28)["ミート"]
        self.assertAlmostEqual(gap, expected, delta=1.0)  # 整数に丸める分

    def test_batting_hand_is_read_from_batting_side_not_throwing_side(self):
        self.assertEqual(values_of("左投右打", 28), values_of(RIGHT, 28))
        self.assertEqual(values_of("左投左打", 28), values_of(LEFT, 28))

    def test_switch_hitter_is_not_shifted(self):
        self.assertEqual(shifted_values_of(SWITCH, 28), shifted_values_of("", 28))

    def test_speed_is_not_shifted_here(self):
        for position in ("一塁手", "遊撃手", "外野手"):
            for age in (19, 28):
                self.assertNotIn("走力", app.FICTIONAL_FIELDER_BATS_SHIFTS["一般"]["左"])
                self.assertNotIn("走力", app.FICTIONAL_FIELDER_BATS_SHIFTS["若手"]["左"])
                if age <= app.FICTIONAL_YOUNG_MAX_AGE:  # 若手の走力は打席によらない
                    self.assertEqual(values_of(LEFT, age, position)["走力"], values_of(RIGHT, age, position)["走力"])

    def test_trajectory_follows_power(self):
        # 弾道はパワーから決め直すので、パワーのずらしで動く（弾道に直接のずらしは入れない）
        for table in app.FICTIONAL_FIELDER_BATS_SHIFTS.values():
            for shifts in table.values():
                self.assertNotIn("弾道", shifts)


class YoungBatsShiftTest(unittest.TestCase):
    def test_young_left_up_right_down_in_contact(self):
        for age in (18, 19, 20, 21):
            left, right = values_of(LEFT, age), values_of(RIGHT, age)
            self.assertGreater(left["ミート"], right["ミート"], age)

    def test_young_contact_shifts_keep_the_average(self):
        # 左打を上げた分だけ右打を下げる（若手の平均を崩さない）。実在の左打は約4割なので、重みつきで±0.5以内
        shifts = app.FICTIONAL_FIELDER_BATS_SHIFTS["若手"]
        mean_shift = 0.4 * shifts["左"]["ミート"] + 0.6 * shifts["右"]["ミート"]
        self.assertLess(abs(mean_shift), 0.5)

    def test_young_uses_young_table_and_22_uses_general_table(self):
        self.assertEqual(app.FICTIONAL_YOUNG_MAX_AGE, 21)
        gap21 = values_of(LEFT, 21)["ミート"] - values_of(RIGHT, 21)["ミート"]
        gap22 = values_of(LEFT, 22)["ミート"] - values_of(RIGHT, 22)["ミート"]
        self.assertGreater(gap22, gap21)  # 22歳以上は左打だけ大きく上げる

    def test_young_switch_hitter_is_not_shifted(self):
        self.assertEqual(shifted_values_of(SWITCH, 20), shifted_values_of("", 20))


class ShiftTableTest(unittest.TestCase):
    def test_only_the_five_abilities_are_shifted(self):
        for table in app.FICTIONAL_FIELDER_BATS_SHIFTS.values():
            for shifts in table.values():
                self.assertTrue(set(shifts) <= set(SHIFTED))
            self.assertNotIn("両", table)

    def test_result_is_deterministic(self):
        self.assertEqual(abilities_of(LEFT, 28, "一塁手"), abilities_of(LEFT, 28, "一塁手"))


if __name__ == "__main__":
    unittest.main()
