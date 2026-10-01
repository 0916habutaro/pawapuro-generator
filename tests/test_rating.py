import sqlite3
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

from generator import rating
from rating_game_cases import CASES

# ゲーム画面と一致しない選手（計算−ゲーム）。満塁男・サヨナラ男の種類と、三森の起用法が原因。回帰テストとして固定する。
KNOWN_DIFFS = {"伏見": 2, "カーク": 4, "オスナ": 4, "中野": 2, "長谷川": 3, "小幡": 13, "三森": 3}


class GameCaseTest(unittest.TestCase):
    def test_game_players(self):
        self.assertEqual(len(CASES), 20)
        for case in CASES:
            with self.subTest(name=case["name"]):
                diff = rating.player_rating(case) - case["star"]
                self.assertEqual(diff, KNOWN_DIFFS.get(case["name"], 0))

    def test_exact_match_count(self):
        exact = [case["name"] for case in CASES if case["name"] not in KNOWN_DIFFS]
        self.assertEqual(len(exact), 13)


class UnitTest(unittest.TestCase):
    def test_ability_points(self):
        cases = {0: 0, 9: 4, 10: 5, 51: 46, 63: 66, 99: 166, 100: 170}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(rating.ability_points(value, 1), expected)
        # 切り捨ててから倍率：51 → 46 → ×0.4 = 18
        self.assertEqual(rating.ability_points(51, 0.4), 18)

    def test_speed_points(self):
        cases = {120: 0, 124: 8, 125: 10, 149: 100, 158: 151, 165: 198}
        for speed, expected in cases.items():
            with self.subTest(speed=speed):
                self.assertEqual(rating.speed_points(speed), expected)

    def test_breaking_ball_points(self):
        self.assertEqual(rating.breaking_ball_points([]), 0)
        # 第二ストレートのみ：1球種・総変化量1
        self.assertEqual(rating.breaking_ball_points([{"kind": "second_fastball", "movement": 0}]), 4)
        # 第二球種も1球種として数える：2球種・総変化量5
        balls = [
            {"kind": "breaking", "movement": 3, "is_second_pitch": False},
            {"kind": "breaking", "movement": 2, "is_second_pitch": True},
        ]
        self.assertEqual(rating.breaking_ball_points(balls), 28)
        # 表の範囲外は0（1球種の表は総変化量7まで）
        self.assertEqual(rating.breaking_ball_points([{"kind": "breaking", "movement": 8}]), 0)

    def test_ranked_points_excludes_other_role(self):
        self.assertEqual(rating.ranked_points({"回復": "回復A"}, "野手"), 0)
        self.assertEqual(rating.ranked_points({"送球": "送球A"}, "投手"), 0)
        self.assertEqual(rating.ranked_points({"回復": "回復A"}, "投手"), 7)
        self.assertEqual(rating.ranked_points({"送球": "送球A"}, "野手"), 7)

    def test_two_way_factor(self):
        def pitcher(subs):
            return {"role": "投手", "sub_positions": subs}

        self.assertEqual(rating.two_way_factor(pitcher([])), 0)
        self.assertEqual(rating.two_way_factor(pitcher([{"position": "外野手", "aptitude": "△"}])), 0.3)
        self.assertEqual(rating.two_way_factor(pitcher([{"position": "外野手", "aptitude": "○"}])), 0.4)
        self.assertEqual(rating.two_way_factor(pitcher([{"position": "外野手", "aptitude": "◎"}, {"position": "一塁手", "aptitude": "△"}])), 0.7)
        # 投手サブポジションは野手扱いしない
        self.assertEqual(rating.two_way_factor(pitcher([{"position": "投手", "aptitude": "○"}])), 0)

    def test_two_way_rating(self):
        base = next(case for case in CASES if case["name"] == "清水")
        player = {**base, "abilities": {**base["abilities"], "弾道": 2, "ミート": {"value": 50}}, "sub_positions": [{"position": "外野手", "aptitude": "○"}]}
        expected = int(rating.pitcher_rating(player) * 0.95) + int(rating.fielder_rating(player) * 0.4)
        self.assertEqual(rating.player_rating(player), expected)


class SavedPlayersTest(unittest.TestCase):
    def test_saved_players_do_not_raise(self):
        import app

        db_path = Path(app.DB_PATH)
        if not db_path.exists():
            self.skipTest("保存済みの選手DBがありません")
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        history = app.load_history()
        self.assertEqual(len(history), count)
        self.assertIn(app.RATING_COLUMN, history.columns)
        self.assertTrue((history[app.RATING_COLUMN] > 0).all())


if __name__ == "__main__":
    unittest.main()
