"""架空球団用の日本人野手の、22歳以上のポジション別の型（野手のポジション別の型_改修指示.md）のテスト。

分布の判定は scripts/check_fielder_position.py（球団生成300球団）で行う。ここでは変換の向き・21歳以下と走力が
変わらないこと・乱数の引く回数が変わらないことを見る。
"""
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

POSITIONS = ("捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手")
ABILITY_NAMES = ("ミート", "パワー", "肩力", "守備力", "捕球")
BATTING = ("右投右打", "右投左打", "右投両打")


def run(position: str, age: int, batting_throwing: str = "右投右打", seed: int = 1, base: int = 55) -> tuple[dict, float]:
    """(結果, 次に引く乱数)。次の乱数が同じなら、引いた回数も同じ。"""
    rng = random.Random(seed)
    abilities = {key: app.ability(base) for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}
    result = app.fictional_fielder_abilities(rng, abilities, position, age, batting_throwing)
    return result, rng.random()


def without_position_type():
    """ポジションの型と弾道のポジション差を外した状態（改修前と同じ）。"""
    stack = mock.patch.object(app, "FICTIONAL_FIELDER_POSITION_TYPE_TRANSFORM", {})
    stack2 = mock.patch.object(app, "FICTIONAL_TRAJECTORY_POSITION_BONUS", {})
    return stack, stack2


class TableTest(unittest.TestCase):
    def test_table_shape(self):
        self.assertEqual(set(app.FICTIONAL_FIELDER_POSITION_TYPE_TRANSFORM), set(POSITIONS))
        for position, table in app.FICTIONAL_FIELDER_POSITION_TYPE_TRANSFORM.items():
            self.assertTrue(set(table) <= set(ABILITY_NAMES), position)  # 走力・弾道は別の仕組み
            for center, scale, _shift in table.values():
                self.assertGreater(scale, 0)
                self.assertTrue(1 <= center <= 100)
        self.assertEqual(set(app.FICTIONAL_TRAJECTORY_POSITION_BONUS), set(POSITIONS))


class AdultTest(unittest.TestCase):
    def test_transform_formula(self):
        # c + k × (値 − c) + d。k=1・d=10 なら、改修前の値にちょうど10足される
        with mock.patch.dict(app.FICTIONAL_FIELDER_POSITION_TYPE_TRANSFORM, {"一塁手": {"パワー": (50.0, 1.0, 10.0)}}):
            shifted, _ = run("一塁手", 28)
        a, b = without_position_type()
        with a, b:
            base, _ = run("一塁手", 28)
        self.assertEqual(shifted["パワー"]["value"], base["パワー"]["value"] + 10)
        for key in ("ミート", "肩力", "守備力", "捕球", "走力"):
            self.assertEqual(shifted[key], base[key])

    def test_scale_narrows_around_center(self):
        with mock.patch.dict(app.FICTIONAL_FIELDER_POSITION_TYPE_TRANSFORM, {"三塁手": {"捕球": (50.0, 0.5, 0.0)}}):
            low, _ = run("三塁手", 28, base=30)
            high, _ = run("三塁手", 28, base=80)
        a, b = without_position_type()
        with a, b:
            low0, _ = run("三塁手", 28, base=30)
            high0, _ = run("三塁手", 28, base=80)
        self.assertGreater(low["捕球"]["value"], low0["捕球"]["value"])  # 中心より下は引き上がる
        self.assertLess(high["捕球"]["value"], high0["捕球"]["value"])  # 中心より上は引き下がる

    def test_first_base_has_more_power_than_shortstop(self):
        first, _ = run("一塁手", 28)
        short, _ = run("遊撃手", 28)
        self.assertGreater(first["パワー"]["value"], short["パワー"]["value"] + 5)

    def test_transform_changes_adult_abilities(self):
        a, b = without_position_type()
        with a, b:
            before, _ = run("捕手", 28)
        after, _ = run("捕手", 28)
        self.assertNotEqual([after[k]["value"] for k in ABILITY_NAMES], [before[k]["value"] for k in ABILITY_NAMES])

    def test_speed_and_bats_gap_are_kept(self):
        a, b = without_position_type()
        for position in POSITIONS:
            with a, b:
                before, _ = run(position, 28, "右投左打")
            after, _ = run(position, 28, "右投左打")
            self.assertEqual(after["走力"], before["走力"], position)
            right, _ = run(position, 28, "右投右打")
            self.assertGreater(after["ミート"]["value"], right["ミート"]["value"] + 3, position)  # 打席のずらしは残る

    def test_trajectory_bonus_applies_to_adults_only(self):
        with mock.patch.dict(app.FICTIONAL_TRAJECTORY_POSITION_BONUS, {"遊撃手": 1000.0}):
            self.assertEqual(run("遊撃手", 28)[0]["弾道"], 4)
            young, _ = run("遊撃手", 21)
        a, b = without_position_type()
        with a, b:
            young0, _ = run("遊撃手", 21)
        self.assertEqual(young["弾道"], young0["弾道"])

    def test_random_draw_count_is_unchanged(self):
        a, b = without_position_type()
        for position in POSITIONS:
            for age in (19, 28):
                with a, b:
                    _, before = run(position, age)
                _, after = run(position, age)
                self.assertEqual(before, after, (position, age))


class YoungTest(unittest.TestCase):
    def test_age_21_and_under_are_unchanged(self):
        a, b = without_position_type()
        for position in POSITIONS:
            for age in (18, 19, 20, 21):
                for batting in BATTING:
                    for seed in (1, 2, 3):
                        with a, b:
                            before, _ = run(position, age, batting, seed)
                        after, _ = run(position, age, batting, seed)
                        self.assertEqual(after, before, (position, age, batting, seed))

    def test_age_22_is_changed(self):
        a, b = without_position_type()
        with a, b:
            before, _ = run("一塁手", 22)
        after, _ = run("一塁手", 22)
        self.assertNotEqual(after, before)


if __name__ == "__main__":
    unittest.main()
